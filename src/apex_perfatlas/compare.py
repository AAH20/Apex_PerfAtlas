"""Metric-specific eligibility, with explicit system changes."""
from __future__ import annotations
from pathlib import Path
from .evidence import validate


def compare(baseline: dict, candidate: dict, baseline_root: Path, candidate_root: Path, allow_platform_change=False) -> dict:
    reasons = [f"baseline: {e}" for e in validate(baseline, baseline_root)]
    reasons += [f"candidate: {e}" for e in validate(candidate, candidate_root)]
    for label, record in (("baseline", baseline), ("candidate", candidate)):
        if record.get("claim_kind") != "measured" or record.get("status") != "valid":
            reasons.append(f"{label}: not a valid measured run")
    if reasons:
        return {"eligible": False, "reasons": reasons, "metrics": []}
    for key in ("id", "version", "kind", "spec_sha256", "input_sha256", "semantics", "frame_integrity_policy"):
        if baseline["workload"][key] != candidate["workload"][key]:
            reasons.append(f"workload differs: {key}")
    for key in ("method", "start_boundary", "stop_boundary", "resolution_ns", "warmup_policy", "sampling_policy"):
        if baseline["measurement"][key] != candidate["measurement"][key]:
            reasons.append(f"measurement differs: {key}")
    for key in ("transport_backend", "backend_status"):
        if baseline["platform"][key] != candidate["platform"][key]:
            reasons.append(f"backend differs: {key}")
    for record in (baseline, candidate):
        t=record["traffic"]
        if t["dropped_count"] or t["unresolved_count"] or t["rejected_count"]:
            reasons.append("v0 comparison requires zero drops, unresolved operations and rejections")
    def artifact_hash(record, identifier):
        return next(a["sha256"] for a in record["artifacts"] if a["id"] == identifier)
    platform_changed = artifact_hash(baseline, baseline["platform"]["inventory_artifact"]) != artifact_hash(candidate, candidate["platform"]["inventory_artifact"])
    if platform_changed and not allow_platform_change:
        reasons.append("platform changed; explicitly request a cross-platform system comparison")
    output=[]
    base={m["id"]:m for m in baseline["metrics"]}
    for metric in candidate["metrics"]:
        old=base.get(metric["id"])
        if old is None:
            reasons.append(f"metric missing from baseline: {metric['id']}")
            continue
        if any(old[k] != metric[k] for k in ("unit", "statistic", "population", "direction")):
            reasons.append(f"incompatible metric definition: {metric['id']}")
            continue
        delta=metric["value"]-old["value"]
        output.append({"id":metric["id"], "baseline":old["value"], "candidate":metric["value"], "unit":metric["unit"],
            "change_percent": None if old["value"]==0 else delta/old["value"]*100,
            "observed_improvement": delta<0 if metric["direction"]=="lower" else delta>0 if metric["direction"]=="higher" else None})
    if set(base) != {m["id"] for m in candidate["metrics"]}:
        reasons.append("metric sets differ")
    return {"eligible": not reasons, "comparison_type": "cross_platform_system_comparison" if platform_changed else "same_platform_regression",
        "reasons": reasons, "metrics": output if not reasons else [],
        "interpretation": "Observed differences only; no statistical significance, external validation or record-win inference."}
