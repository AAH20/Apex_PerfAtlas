"""Offline evidence checks. A submitted validation label is not authenticated by this tool."""
from __future__ import annotations
import hashlib
import json
import math
from importlib.resources import files
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def schema() -> dict:
    return json.loads(files("apex_perfatlas").joinpath("data/run.schema.json").read_text())


def quantile(samples: list[int | float], probability: float) -> float:
    return sorted(samples)[max(0, math.ceil(probability * len(samples)) - 1)]


def validate(record: dict, artifact_root: Path) -> list[str]:
    issues = [f"schema {'.'.join(map(str, e.absolute_path))}: {e.message}"
              for e in Draft202012Validator(schema(), format_checker=FormatChecker()).iter_errors(record)]
    if issues:
        return issues
    artifacts = {}
    root = artifact_root.resolve()
    for artifact in record["artifacts"]:
        if artifact["id"] in artifacts:
            issues.append(f"duplicate artifact ID: {artifact['id']}")
        path = (root / artifact["location"]).resolve()
        if not path.is_relative_to(root):
            issues.append(f"artifact escapes root: {artifact['id']}")
            continue
        if not path.is_file():
            issues.append(f"artifact unavailable for verification: {artifact['id']}")
            continue
        if digest(path) != artifact["sha256"]:
            issues.append(f"artifact hash mismatch: {artifact['id']}")
            continue
        artifacts[artifact["id"]] = (artifact, path)
    if record["status"] == "not_run":
        return issues
    if record["claim_kind"] != "measured":
        return issues + ["estimates and targets are not executable measured run records"]
    for field in ("inventory_artifact", "implementation_artifact"):
        if record["platform"][field] not in artifacts:
            issues.append(f"missing platform evidence: {field}")
    if record["workload"]["rights"] == "unresolved":
        issues.append("workload rights unresolved")
    if record["workload"]["frame_integrity_policy"] == "unknown":
        issues.append("frame integrity policy unknown")
    if record["evidence"]["environment"] == "not_run":
        issues.append("measured claim has no execution environment")
    if record["measurement"]["method"] == "external_instrument":
        for field in ("calibration_artifact", "clock_artifact", "uncertainty_artifact"):
            if record["measurement"][field] not in artifacts:
                issues.append(f"external measurement missing {field}")
        if record["platform"]["backend_status"] != "real":
            issues.append("external network measurement requires real backend")
    for field in ("clock_artifact", "calibration_artifact", "uncertainty_artifact"):
        value = record["measurement"][field]
        if value is not None and value not in artifacts:
            issues.append(f"unresolved measurement artifact: {field}")
    for label, value in (("configuration", record["provenance"]["config_sha256"]),
                         ("workload specification", record["workload"]["spec_sha256"]),
                         ("workload input", record["workload"]["input_sha256"])):
        if value not in {a["sha256"] for a, _ in artifacts.values()}:
            issues.append(f"missing hash-bound {label} artifact")
    for field, role in (("inventory_artifact", "platform_inventory"), ("implementation_artifact", "implementation")):
        item = artifacts.get(record["platform"][field])
        if item is not None and item[0]["role"] != role:
            issues.append(f"incorrect platform artifact role: {field}")
    traffic = record["traffic"]
    if traffic["schedule_artifact"] not in artifacts:
        issues.append("missing traffic schedule artifact")
    count_fields = [k for k in traffic if k.endswith("_count")]
    if any(traffic[k] is None for k in count_fields):
        issues.append("measured run has unknown traffic accounting")
    else:
        if traffic["offered_count"] != traffic["accepted_count"] + traffic["rejected_count"] + traffic["dropped_count"]:
            issues.append("offered != accepted + rejected + dropped")
        if traffic["accepted_count"] != traffic["completed_count"] + traffic["unresolved_count"]:
            issues.append("accepted != completed + unresolved")
        if traffic["duplicate_output_count"] or traffic["wrong_output_count"]:
            issues.append("output correctness violation")
    seen = set()
    samples = None
    for artifact, path in artifacts.values():
        if artifact["role"] == "chronological_latency_samples_ns":
            if samples is not None:
                issues.append("multiple sample populations require separate run envelopes")
                continue
            try:
                samples = json.loads(path.read_text())
                if not isinstance(samples, list) or not samples or any(
                    isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x < 0 for x in samples
                ):
                    issues.append("invalid chronological latency samples")
                    samples = None
            except (ValueError, OSError):
                issues.append("unreadable latency samples")
    rate_accounting = []
    for artifact, path in artifacts.values():
        if artifact["role"] == "throughput_accounting":
            try:
                data = json.loads(path.read_text())
                elapsed = data["elapsed_ns"]
                count = data["completed_count"]
                if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or elapsed <= 0:
                    raise ValueError("invalid elapsed time")
                if isinstance(count, bool) or not isinstance(count, int) or count != traffic["completed_count"]:
                    raise ValueError("invalid completed count")
                rate_accounting.append((data, count * 1e9 / elapsed))
            except (OSError, ValueError, TypeError, KeyError):
                issues.append("invalid throughput accounting")
    for metric in record["metrics"]:
        if metric["id"] in seen:
            issues.append(f"duplicate metric ID: {metric['id']}")
        seen.add(metric["id"])
        if not math.isfinite(metric["value"]):
            issues.append(f"nonfinite metric: {metric['id']}")
        if metric["statistic"] == "rate":
            if metric["unit"] != "events/s" or len(rate_accounting) != 1 or rate_accounting[0][0].get("population") != metric["population"] or not math.isclose(metric["value"], rate_accounting[0][1], rel_tol=1e-9):
                issues.append(f"rate does not match retained accounting: {metric['id']}")
        if metric["unit"] != "ns":
            continue
        if samples is None:
            issues.append(f"latency metric lacks raw samples: {metric['id']}")
            continue
        resolution=record["measurement"]["resolution_ns"]
        if resolution is not None and metric["value"] < resolution:
            issues.append(f"latency metric below declared clock resolution: {metric['id']}")
        statistic = metric["statistic"]
        expected = {"minimum": min(samples), "maximum_observed": max(samples), "mean": sum(samples)/len(samples)}
        for label, q in (("p50", .5), ("p90", .9), ("p99", .99), ("p99.9", .999), ("p99.99", .9999)):
            expected[label] = quantile(samples, q)
        if statistic not in expected or not math.isclose(metric["value"], expected[statistic], rel_tol=1e-9, abs_tol=1e-6):
            issues.append(f"latency summary does not match raw samples: {metric['id']}")
    for artifact, path in artifacts.values():
        if artifact["role"] == "cycle_transition_trace":
            try:
                trace=json.loads(path.read_text())
                if not isinstance(trace,list) or len(trace)!=record["measurement"]["sample_count"]:
                    issues.append("simulation trace length mismatch")
                for metric in record["metrics"]:
                    if metric["id"]=="simulation.matched_transitions" and metric["value"]!=len(trace):
                        issues.append("simulation count does not match retained trace")
            except (OSError,ValueError,TypeError):
                issues.append("invalid simulation trace")
    if samples is not None and len(samples) != record["measurement"]["sample_count"]:
        issues.append("sample count does not match raw artifact")
    if record["status"] != "valid":
        issues.append(f"run is {record['status']}; excluded from measured comparisons")
    return issues
