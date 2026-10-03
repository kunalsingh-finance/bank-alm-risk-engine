"""Challenge a frozen grid-selected policy; never reselect on challenge results."""
from __future__ import annotations

import copy
import hashlib
import json
import math

from .engine import BASE, simulate_scenario, validate_inputs
from .numerics import interpolate_zero


def design_cases(segmented: bool = False) -> list[dict]:
    """A deterministic challenge set specified independently of policy returns."""
    cases = []
    for shock in (-300, -100, 100, 300):
        for runoff in (0.0, 0.2, 0.4, 0.6):
            cases.append({"id": f"unseen_{shock}_{round(runoff * 100)}", "group": "unseen_rate_runoff", "label": f"{shock:+} bp / {runoff:.0%} runoff", "scenario": {"shape": "parallel", "shock_bps": shock, "deposit_runoff_fraction": runoff}, "overrides": {}, "curve_variant": "source"})
    for shape in ("steepener", "flattener", "short_up", "short_down"):
        cases.append({"id": f"unseen_{shape}_40", "group": "unseen_rate_runoff", "label": shape.replace("_", " ").title() + " / 40% runoff", "scenario": {"shape": shape, "deposit_runoff_fraction": .4}, "overrides": {}, "curve_variant": "source"})
    for key, value in (("beta", .1), ("beta", .9), ("maturity", 1.0), ("maturity", 5.0), ("cpr", 0.0), ("cpr", .2)):
        overrides = {"deposits": {"beta": value}} if key == "beta" else {"deposits": {"interest_maturity_years": value, "noninterest_maturity_years": value}} if key == "maturity" else {"loans": {"prepayment_cpr": value}}
        cases.append({"id": f"behavior_{key}_{value}", "group": "behavioral_uncertainty", "label": f"{key.upper() if key == 'cpr' else key.title()} = {value:g}", "scenario": {"shape": "parallel", "shock_bps": 200, "deposit_runoff_fraction": .45}, "overrides": overrides, "curve_variant": "source"})
    for variant, label in (("proxy_plus_25bp", "Treasury proxy +25 bp"), ("proxy_minus_25bp", "Treasury proxy -25 bp"), ("short_end_flat_one_year", "Sub-one-year rates held at one-year zero"), ("short_end_linear_origin", "Linear short-end extension to one day")):
        cases.append({"id": variant, "group": "curve_model_risk", "label": label, "scenario": {"shape": "parallel", "shock_bps": 200, "deposit_runoff_fraction": .45}, "overrides": {}, "curve_variant": variant})
    if segmented:
        for key, label, overrides in (("fixed_low", "Other-loan fixed share 10%", {"fixed_fractions": {"other_loans": .1}}), ("fixed_high", "Other-loan fixed share 40%", {"fixed_fractions": {"other_loans": .4}}), ("floating_life", "Floating contractual life at least 84 months", {"floating_contractual_months": 84}), ("retain_pledged_proceeds", "Pledged principal stays restricted as cash collateral", {"pledged_principal_treatment": "retain_cash_collateral"})):
            cases.append({"id": "segment_" + key, "group": "asset_segment_uncertainty", "label": label, "scenario": {"shape": "parallel", "shock_bps": 200, "deposit_runoff_fraction": .45}, "overrides": {}, "segment_overrides": overrides, "curve_variant": "source"})
    return cases


def alternate_curve(curve: dict, variant: str) -> dict:
    out = copy.deepcopy(curve)
    if variant == "source":
        return out
    if variant in ("proxy_plus_25bp", "proxy_minus_25bp"):
        shift = .0025 if variant == "proxy_plus_25bp" else -.0025
        out["zero_rates"] = [rate + shift for rate in curve["zero_rates"]]
    elif variant == "short_end_flat_one_year":
        anchor = interpolate_zero(1.0, curve["tenors_years"], curve["zero_rates"])
        out["zero_rates"] = [anchor if tenor < 1 else rate for tenor, rate in zip(curve["tenors_years"], curve["zero_rates"])]
    elif variant == "short_end_linear_origin":
        tenors, rates = curve["tenors_years"], curve["zero_rates"]
        short_time = min(1 / 365, tenors[0] / 2)
        short_rate = rates[0] + (short_time - tenors[0]) * (rates[1] - rates[0]) / (tenors[1] - tenors[0])
        out["tenors_years"] = [short_time, *tenors]
        out["zero_rates"] = [short_rate, *rates]
    else:
        raise ValueError(f"Unknown curve model-risk variant: {variant}")
    out["research_variant"] = variant
    return out


def evaluate_robustness(snapshot: dict, assumptions: dict, curve: dict, training_analysis: dict) -> dict:
    """Return full challenge ledgers for the frozen choice and zero-hedge reference."""
    selected = training_analysis["policies"]["selected_policy_id"]
    if selected is None:
        return {"status": "no_selected_policy", "selected_policy_id": None, "selection_frozen": True, "cases": [], "summary": {"case_count": 0}, "interpretation": "The training grid has no feasible policy. No diagnostic candidate is silently promoted for robustness evaluation."}
    candidate = next(p for p in training_analysis["policies"]["candidates"] if p["id"] == selected)
    policy = {key: candidate[key] for key in ("prefunding_fraction", "funding_order", "hedge_fraction_assets")}
    reference = {"prefunding_fraction": 0.0, "funding_order": "borrow_first", "hedge_fraction_assets": 0.0}
    segmented = assumptions.get("asset_segments", {}).get("enabled", False)
    design = design_cases(segmented)
    outputs = []
    for case in design:
        config = copy.deepcopy(assumptions)
        for section, overrides in case["overrides"].items():
            config[section].update(overrides)
        if case.get("segment_overrides"):
            from .segmentation import build_asset_segments
            original = assumptions["asset_segments"]
            profile = {"bands": original["source_bands"], "totals_usd": original["reported_totals_usd"], "certificate": original["certificate"], "as_of": original["as_of"], "source_records": original["source_records"], "limitations": original["limitations"]}
            overrides = copy.deepcopy(original["assumptions"])
            for key, value in case["segment_overrides"].items():
                if isinstance(value, dict):
                    overrides[key].update(value)
                else:
                    overrides[key] = value
            config["asset_segments"] = build_asset_segments(profile, config, overrides)
        variant = alternate_curve(curve, case["curve_variant"])
        validate_inputs(snapshot, config, variant)
        scenario = {**BASE, **case["scenario"], "id": case["id"], "name": case["label"], "description": "Frozen-policy challenge case; not used to choose or retune the policy."}
        own_base = simulate_scenario(snapshot, config, variant, BASE, policy)
        reference_base = simulate_scenario(snapshot, config, variant, BASE, reference)
        outcome = simulate_scenario(snapshot, config, variant, scenario, policy)
        unhedged = simulate_scenario(snapshot, config, variant, scenario, reference)
        for result, baseline in ((outcome, own_base), (unhedged, reference_base)):
            result["delta_nii_usd"] = result["nii_12m_usd"] - baseline["nii_12m_usd"]
        curve_probes = [{"tenor_days": days, "zero_rate": interpolate_zero(days / 365, variant["tenors_years"], variant["zero_rates"]), "discount_factor": math.exp(-days / 365 * interpolate_zero(days / 365, variant["tenors_years"], variant["zero_rates"]))} for days in (1, 7, 30, 91, 365)]
        outputs.append({**case, "policy_id": selected, "policy_feasible": not outcome["breaches"], "reference_feasible": not unhedged["breaches"], "policy_modeled_earnings_usd": outcome["modeled_earnings_usd"], "reference_modeled_earnings_usd": unhedged["modeled_earnings_usd"], "policy_delta_eve_usd": outcome["delta_eve_usd"], "policy_minimum_cash_usd": outcome["minimum_observed_cash_usd"], "policy_max_margin_shortfall_usd": outcome["max_unfunded_margin_usd"], "policy_breaches": outcome["breaches"], "curve_probes": curve_probes, "assumptions": config, "curve": variant, "policy_baseline": own_base, "reference_baseline": reference_base, "policy_result": outcome, "reference_result": unhedged})
    failing = [case for case in outputs if not case["policy_feasible"]]
    worst = min(outputs, key=lambda case: case["policy_modeled_earnings_usd"])
    return {"status": "challenge_failures" if failing else "all_sampled_challenges_passed", "selected_policy_id": selected, "policy": policy, "selection_frozen": True, "design_sha256": hashlib.sha256(json.dumps(design, sort_keys=True, separators=(",", ":")).encode()).hexdigest(), "selection_basis": "Original baseline and seven named stress cases only; challenge results do not update the policy.", "summary": {"case_count": len(outputs), "passed_case_count": len(outputs) - len(failing), "failed_case_count": len(failing), "worst_case_id": worst["id"], "worst_modeled_earnings_usd": worst["policy_modeled_earnings_usd"], "worst_delta_eve_usd": min(case["policy_delta_eve_usd"] for case in outputs)}, "cases": outputs, "limitations": ["Designed hypothetical challenges, not realized future observations or empirical out-of-sample performance.", "Alternate proxy curves change both projection and discounting and recalibrate the hypothetical inception par coupon at the same frozen hedge notional; this is model specification risk, not repricing an executed trade with unchanged contractual coupon.", "No probabilities are assigned to cases. Passing a finite set does not prove robustness between grid points.", "A policy failure remains a finding. Selection is never repaired by tuning on the challenge set."]}


def audit_robustness(result: dict, snapshot: dict, training_analysis: dict) -> dict:
    """Independently reconcile challenge ledgers using the saved-ledger verifier."""
    from .verification import audit_scenario_group
    if result["selected_policy_id"] != training_analysis["policies"]["selected_policy_id"] or result.get("selection_frozen") is not True:
        raise ValueError("Robustness policy differs from the frozen training selection")
    if result["selected_policy_id"] is None:
        if result["cases"]:
            raise ValueError("An unselected policy cannot have claimed selected challenge results")
        return {"passed": True, "audited_cases": 0, "audited_scenario_paths": 0}
    expected = design_cases(training_analysis["assumptions"].get("asset_segments", {}).get("enabled", False))
    if [case["id"] for case in result["cases"]] != [case["id"] for case in expected]:
        raise ValueError("Robustness cases differ from the frozen challenge design")
    count = 0
    max_residual = 0.0
    for case in result["cases"]:
        for kind in ("policy", "reference"):
            audit = audit_scenario_group([case[f"{kind}_baseline"], case[f"{kind}_result"]], snapshot, case["assumptions"])
            count += audit["audited_scenario_paths"]
            max_residual = max(max_residual, audit["max_residual_usd"])
        if case["policy_feasible"] != (not case["policy_result"]["breaches"]):
            raise ValueError("Challenge feasibility disagrees with its ledger")
    failures = sum(not case["policy_feasible"] for case in result["cases"])
    if result["summary"]["failed_case_count"] != failures or result["summary"]["case_count"] != len(expected):
        raise ValueError("Challenge summary disagrees with saved cases")
    return {"passed": True, "audited_cases": len(expected), "audited_scenario_paths": count, "max_residual_usd": max_residual}
