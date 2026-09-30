import copy
import json
from pathlib import Path
import pytest
from apex_perfatlas.evidence import validate, digest, schema
from apex_perfatlas.compare import compare
from apex_perfatlas.economics import evaluate, asic_break_even
from jsonschema import Draft202012Validator

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def run(tmp_path):
    record=json.loads((ROOT/"examples/design-only.json").read_text())
    record["status"]="valid";record["claim_kind"]="measured"
    record["provenance"].update(repository_url="https://example.invalid/test-fixture",commit="a"*40,dirty=False,config_sha256="b"*64)
    record["workload"].update(spec_sha256="c"*64,input_sha256="d"*64,frame_integrity_policy="not_applicable")
    record["evidence"].update(implementation="software",environment="cpu")
    record["measurement"].update(method="software_clock",start_boundary="fixture start",stop_boundary="fixture stop",sample_count=4,clock_artifact="clock",resolution_ns=1)
    record["platform"].update(inventory_artifact="inventory",implementation_artifact="build",transport_backend="in_memory",backend_status="simulated")
    record["traffic"].update(offered_count=4,accepted_count=4,completed_count=4,rejected_count=0,dropped_count=0,duplicate_output_count=0,wrong_output_count=0,unresolved_count=0)
    for name,role,data in (("inventory","platform_inventory",{"test_fixture":True}),("build","implementation",{"test_fixture":True}),("samples","chronological_latency_samples_ns",[1,100,1,100]),("config","configuration",{"config":1}),("workload","workload",{"workload":1}),("input","input",{"input":1}),("clock","clock",{"resolution_ns":1,"fixture":True})):
        path=tmp_path/(name+".json");path.write_text(json.dumps(data))
        record["artifacts"].append({"id":name,"role":role,"location":path.name,"sha256":digest(path),"visibility":"public"})
    record["provenance"]["config_sha256"]=digest(tmp_path/"config.json")
    record["workload"]["spec_sha256"]=digest(tmp_path/"workload.json")
    record["workload"]["input_sha256"]=digest(tmp_path/"input.json")
    record["traffic"]["schedule_artifact"]="input"
    record["metrics"]=[{"id":"latency.p99","value":100,"unit":"ns","statistic":"p99","population":"test fixture samples","direction":"lower"}]
    record["limitations"]=["Artificial validator test fixture, never published as a performance result."]
    return record


def test_schema_and_design_record(tmp_path):
    Draft202012Validator.check_schema(schema())
    assert validate(json.loads((ROOT/"examples/design-only.json").read_text()),tmp_path)==[]


def test_valid_record_and_self_comparison(run,tmp_path):
    assert validate(run,tmp_path)==[]
    result=compare(run,run,tmp_path,tmp_path)
    assert result["eligible"]
    assert result["metrics"][0]["observed_improvement"] is False


@pytest.mark.parametrize("change",["hash","boundary","statistic","loss","integrity","precision","target","independent","traversal","summary","nonfinite","population"])
def test_adversarial_evidence_and_comparison(run,tmp_path,change):
    changed=copy.deepcopy(run)
    if change=="hash": changed["artifacts"][0]["sha256"]="0"*64
    elif change=="boundary": changed["measurement"]["stop_boundary"]="different stop"
    elif change=="statistic": changed["metrics"][0]["statistic"]="minimum"
    elif change=="loss": changed["traffic"]["dropped_count"]=1
    elif change=="integrity": changed["workload"]["frame_integrity_policy"]="early_action_before_fcs"
    elif change=="precision": changed["measurement"]["resolution_ns"]=4
    elif change=="target": changed["claim_kind"]="target"
    elif change=="independent": changed["evidence"]["validation"]="independent_measurement"
    elif change=="traversal": changed["artifacts"][0]["location"]="../outside.json"
    elif change=="summary": changed["metrics"][0]["value"]=99
    elif change=="nonfinite": changed["metrics"][0]["value"]=float("nan")
    elif change=="population": changed["metrics"][0]["population"]="different work"
    assert not compare(run,changed,tmp_path,tmp_path)["eligible"]


def test_external_scope_requires_actual_backend_and_calibration(run,tmp_path):
    run["measurement"]["method"]="external_instrument"
    assert any("real backend" in x for x in validate(run,tmp_path))


def test_unknown_costs_and_cashflow():
    assert evaluate({})["npv"] is None
    scenario=json.loads((ROOT/"examples/cost-scenario.json").read_text())
    result=evaluate(scenario)
    assert result["annual_expected_outage_cost"]==500
    assert result["payback_years"]==pytest.approx(100000/49500)
    assert asic_break_even(5_000_000,10_000,3000)==715
    assert asic_break_even(5_000_000,1000,3000) is None
    assert asic_break_even(None,1000,3000) is None


def test_packaged_contract_and_catalog_do_not_drift():
    assert json.loads((ROOT/"contracts/run.schema.json").read_text())==schema()
    assert (ROOT/"catalog/catalog.json").read_bytes()==(ROOT/"src/apex_perfatlas/data/catalog.json").read_bytes()


def test_below_resolution_latency_is_not_a_win(run,tmp_path):
    run["measurement"]["resolution_ns"]=1000
    assert any("below declared clock resolution" in issue for issue in validate(run,tmp_path))


@pytest.mark.parametrize("field",["config", "spec", "input", "schedule"])
def test_missing_provenance_binding_rejected(run,tmp_path,field):
    if field=="config": run["provenance"]["config_sha256"]="0"*64
    elif field=="spec": run["workload"]["spec_sha256"]="0"*64
    elif field=="input": run["workload"]["input_sha256"]="0"*64
    else: run["traffic"]["schedule_artifact"]="absent"
    assert validate(run,tmp_path)


def test_unaccounted_rate_rejected(run,tmp_path):
    run["metrics"]=[{"id":"rate","value":4,"unit":"events/s","statistic":"rate","population":"fixture","direction":"higher"}]
    assert any("retained accounting" in item for item in validate(run,tmp_path))


@pytest.mark.parametrize("change",["stub","simulation","clock"])
def test_execution_class_is_enforced(run,tmp_path,change):
    if change=="stub":run["evidence"]["implementation"]="stub"
    elif change=="simulation":run["evidence"]["environment"]="simulator";run["measurement"]["method"]="simulation"
    else:run["measurement"]["clock_artifact"]=None
    assert validate(run,tmp_path)
