"""Join verified research sources and explicit choices into an extended case."""
from __future__ import annotations

import copy
from pathlib import Path

from .calibration import calibrate
from .pipeline import ROOT, read_json
from .segmentation import build_asset_segments


def prepare_research_inputs(snapshot: dict, assumptions: dict, root: Path = ROOT) -> dict:
    from scripts.fetch_history import load_verified_history, load_verified_calibration
    from scripts.fetch_maturity_data import load_verified_profile

    history = load_verified_history(root)
    calibration = load_verified_calibration(root)
    profile = load_verified_profile(root)
    configuration = read_json(root / "configs/research_case.json")
    if calibration != calibrate(history):
        raise ValueError("Calibration does not reproduce from historical source data")
    if history["certificate"] != snapshot["certificate"] or profile["certificate"] != snapshot["certificate"]:
        raise ValueError("Research sources refer to a different legal entity")
    latest = history["quarters"][-1]
    if latest["quarter_end"] != snapshot["as_of"] or profile["as_of"] != snapshot["as_of"]:
        raise ValueError("Extended research source observation dates do not align")
    b = snapshot["balance_sheet_usd"]
    for key in ("assets", "total_deposits", "interest_bearing_deposits"):
        expected = sum(b[k] for k in ("cash", "securities", "loans", "other_assets")) if key == "assets" else b["interest_deposits"] + b["noninterest_deposits"] if key == "total_deposits" else b["interest_deposits"]
        if abs(latest["reported_balance_sheet_usd"][key] - expected) > 1:
            raise ValueError("Historical ending balance differs from public snapshot: " + key)
    total_assets = sum(b[k] for k in ("cash", "securities", "loans", "other_assets"))
    flows = history["annual_2025_cost_and_credit_evidence"]["flows_usd"]
    if flows["noninterest_expense_usd"] != profile["reported_annual_context_usd"]["noninterest_expense"] or flows["net_loan_chargeoffs_usd"] != profile["reported_annual_context_usd"]["net_chargeoffs"]:
        raise ValueError("Independent source queries disagree on annual cost/credit totals")
    extended = copy.deepcopy(assumptions)
    extended["deposits"]["interest_rate"] = latest["deposit_cost_annualized_proxy"]
    extended["business_costs"] = {"enabled": True, "annual_operating_expense_fraction_assets": flows["noninterest_expense_usd"] / total_assets, "annual_credit_loss_fraction_loans": flows["net_loan_chargeoffs_usd"] / b["loans"], "source_period": "2025", "operating_basis": configuration["operating_cost_policy"], "credit_basis": configuration["credit_cost_policy"], "excluded_income_note": configuration["excluded_income_note"]}
    extended["asset_segments"] = build_asset_segments(profile, extended, configuration["segment_overrides"])
    estimated_beta = calibration["coefficients"]["total_beta"]
    extended["sensitivity"]["deposit_betas"] = sorted(set([*extended["sensitivity"]["deposit_betas"], estimated_beta]))
    extended["notes"].extend([configuration["starting_deposit_cost"] + f": {latest['deposit_cost_annualized_proxy']:.8f}; the endpoint-average denominator is a proxy, not a reported daily average or current contract quote.", configuration["deposit_beta_policy"], configuration["operating_cost_policy"], configuration["credit_cost_policy"], configuration["excluded_income_note"], "Sourced bands mix fixed maturity and floating repricing. Assumed fixed/floating splits, representative tenors and gross-to-net allocation remain explicit."])
    return {"history": history, "calibration": calibration, "profile": profile, "configuration": configuration, "extended_assumptions": extended}


def evidence_summary(inputs: dict, primary: dict, primary_challenges: dict, reference_challenges: dict) -> dict:
    cal, history, profile = inputs["calibration"], inputs["history"], inputs["profile"]
    metrics = cal["metrics"]
    best = cal["diagnostics"]["holdout_best_benchmark"]
    benchmark_label = best.replace("_", " ")
    fixed = inputs["extended_assumptions"]
    totals = profile["totals_usd"]
    costs = fixed["business_costs"]
    challenge_rows = []
    case_rows = []
    for label, result in (("Sourced extended case", primary_challenges), ("Original aggregate case", reference_challenges)):
        if result["selected_policy_id"] is None:
            challenge_rows.append([label, "No feasible selection to test", "—", "—"])
            continue
        for group in ("unseen_rate_runoff", "behavioral_uncertainty", "curve_model_risk", "asset_segment_uncertainty"):
            cases = [case for case in result["cases"] if case["group"] == group]
            if not cases:
                continue
            challenge_rows.append([label + " / " + group.replace("_", " "), result["selected_policy_id"], sum(case["policy_feasible"] for case in cases), sum(not case["policy_feasible"] for case in cases)])
        for case in result["cases"]:
            case_rows.append([label + ": " + case["label"], "Pass" if case["policy_feasible"] else "; ".join(b.replace("_", " ") for b in case["policy_breaches"]), f"${case['policy_modeled_earnings_usd'] / 1e9:,.3f}bn", f"${case['policy_delta_eve_usd'] / 1e9:,.3f}bn"])
    return {"case_label": inputs["configuration"]["case_label"], "decision_context": "The main report includes sourced asset bands, an encumbrance constraint and explicit operating/credit costs. " + ("No joint policy meets every selection-scenario limit." if primary["policies"]["selected_policy_id"] is None else "The selected policy meets the selection scenarios; broader challenges remain separate."), "calibration": {"description": f"{history['quarter_count']} quarterly bank observations; fitted persistent-response beta {cal['coefficients']['total_beta']:.3f}. The engine retains the 0.5 research beta and includes the estimate in sensitivity.", "fit_description": f"Training {cal['split']['training_start']} to {cal['split']['training_end']}; holdout {cal['split']['holdout_start']} to {cal['split']['holdout_end']}. No holdout targets enter coefficient fitting.", "holdout_description": f"The lagged model's holdout RMSE is {metrics['lagged_model']['holdout']['rmse_bps']:.2f} bp, versus {metrics[best]['holdout']['rmse_bps']:.2f} bp for {benchmark_label}. This does not support replacing the research assumption with a validated forecast.", "availability_note": "Historical observations are later retrieved vintages. Exact bank-quarter submission/publication timestamps remain unobserved; the documented FFIEC submission service requires an authenticated account. The test conditions on realized policy rates.", "denominator_note": "Deposit expense is converted from YTD to quarterly flow and divided by the mean of adjacent domestic interest-bearing deposit balances. Reported daily/weekly deposit averages were not obtained.", "metric_rows": [["Training RMSE (bp)", f"{metrics['lagged_model']['train']['rmse_bps']:.2f}", f"{metrics[best]['train']['rmse_bps']:.2f}"], ["Holdout RMSE (bp)", f"{metrics['lagged_model']['holdout']['rmse_bps']:.2f}", f"{metrics[best]['holdout']['rmse_bps']:.2f}"], ["Holdout mean error (bp)", f"{metrics['lagged_model']['holdout']['mean_error_bps']:.2f}", f"{metrics[best]['holdout']['mean_error_bps']:.2f}"]], "prediction_rows": [[row["quarter_end"], f"{100 * row['actual_deposit_cost']:.3f}%", f"{100 * row['lagged_model_prediction']:.3f}%", f"{100 * row[best + '_prediction']:.3f}%"] for row in cal["predictions"] if row["sample"] == "holdout"]}, "coverage": {"description": "Official FDIC maturity/repricing bands reconcile to the same bank legal entity and date. They do not reveal every contract's maturity or coupon.", "rows": [["Reported securities", totals["securities_book"]], ["Securities in source bands", totals["securities_bands"]], ["Equity securities residual", totals["equity_securities_residual"]], ["Reported pledged securities", totals["pledged_securities"]], ["Opening sale-eligible unpledged debt (modeled)", fixed["asset_segments"]["permitted_security_sale_book_usd"]], ["Accruing gross loan bands", totals["loan_bands_accruing"]], ["Nonaccrual gross loans", totals["nonaccrual_loans"]], ["Allowance", totals["allowance_for_loans"]], ["Net loans", totals["net_loans"]]], "notes": profile["limitations"][:5]}, "business_costs": {"description": inputs["configuration"]["excluded_income_note"], "rows": [["Starting deposit cost", f"{100 * fixed['deposits']['interest_rate']:.3f}%", "2025 Q4 annualized expense / endpoint-average domestic interest-bearing deposits"], ["Annual operating cost / opening assets", f"{100 * costs['annual_operating_expense_fraction_assets']:.3f}%", "2025 reported noninterest expense, scaled to opening total assets"], ["Annual credit-loss rate", f"{100 * costs['annual_credit_loss_fraction_loans']:.3f}%", "2025 net chargeoffs / opening net loans; applied to monthly beginning net loans, noncash"], ["Historical noninterest income (excluded)", f"${history['annual_2025_cost_and_credit_evidence']['flows_usd']['noninterest_income_usd'] / 1e9:.3f}bn", "Not forecast or added to modeled earnings"]]}, "robustness": {"description": "Each policy is frozen before its challenge results are evaluated. No failing result is used to change its hedge size, funding choice or risk limits.", "summary_rows": challenge_rows, "case_rows": case_rows, "notes": ["These are hypothetical unseen combinations and model-assumption challenges, not empirical future bank outcomes.", "When the extended selection grid has no feasible policy, no infeasible diagnostic is promoted for challenge testing. The original aggregate choice is still challenged and explicitly labeled.", "Alternate proxy curves affect projection and discounting and recalibrate hypothetical inception par coupons; they do not value an executed trade with unchanged terms."]}}
