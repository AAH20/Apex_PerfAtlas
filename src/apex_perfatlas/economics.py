"""Cash economics with explicit unknowns and homogeneous currency."""
import math


def evaluate(scenario: dict) -> dict:
    required=("currency", "initial_investment", "annual_opex", "annual_incremental_revenue", "annual_incident_rate", "hours_per_incident", "loss_per_hour", "years", "discount_rate", "residual_value")
    missing=[k for k in required if scenario.get(k) is None]
    if missing:
        return {"status":"unknown", "missing":missing, "npv":None, "payback_years":None}
    if not scenario["currency"] or not isinstance(scenario["years"],int) or isinstance(scenario["years"],bool) or scenario["years"]<=0:
        raise ValueError("currency and positive integer horizon required")
    for key in required[1:]:
        value=scenario[key]
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
            raise ValueError(f"invalid nonnegative numeric input: {key}")
    outage=scenario["annual_incident_rate"]*scenario["hours_per_incident"]*scenario["loss_per_hour"]
    cash=scenario["annual_incremental_revenue"]-scenario["annual_opex"]-outage
    rate=scenario["discount_rate"]; years=scenario["years"]
    npv=-scenario["initial_investment"]+sum(cash/(1+rate)**t for t in range(1,years+1))+scenario["residual_value"]/(1+rate)**years
    return {"status":"scenario", "currency":scenario["currency"], "annual_expected_outage_cost":outage, "annual_net_cashflow":cash,
        "npv":npv, "payback_years":scenario["initial_investment"]/cash if cash>0 else None,
        "payback_policy":"undiscounted, constant annual net cashflow; residual value excluded", "input_provenance":scenario.get("input_provenance",{}),
        "limitations":["Scenario arithmetic is not observed customer revenue or an investment recommendation.", "All cash inputs must already share currency, tax and scope assumptions."]}


def asic_break_even(nre, fpga_unit, asic_unit):
    if any(v is None for v in (nre,fpga_unit,asic_unit)):
        return None
    if any(not math.isfinite(v) or v<0 for v in (nre,fpga_unit,asic_unit)):
        raise ValueError("costs must be finite and nonnegative")
    return None if fpga_unit<=asic_unit else math.ceil(nre/(fpga_unit-asic_unit))
