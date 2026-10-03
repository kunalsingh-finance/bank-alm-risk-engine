"""Audit saved accounting records independently of engine helper functions."""
from __future__ import annotations

import math
from datetime import date
from itertools import product
from pathlib import Path

from .pipeline import ROOT, digest, fingerprint, read_json, validate_sources


def audit_saved_analysis(analysis: dict, snapshot: dict, assumptions: dict, *, _groups_only: bool = False) -> dict:
    """Reconcile saved nominal-dollar stocks and flows with a $1 tolerance."""
    tolerance = 1.0
    b = snapshot["balance_sheet_usd"]
    max_residual = 0.0
    tested = 0

    def close(actual: float, expected: float, label: str) -> None:
        nonlocal max_residual, tested
        if not math.isfinite(actual) or not math.isfinite(expected):
            raise ValueError(f"Nonfinite saved result: {label}")
        residual = abs(actual - expected)
        max_residual = max(max_residual, residual)
        tested += 1
        if residual > tolerance:
            raise ValueError(f"Saved audit failed ({label}): residual {residual:,.6f} USD")

    opening_assets = sum(b[k] for k in ("cash", "securities", "loans", "other_assets"))
    cash_floor = opening_assets * assumptions["cash"]["floor_fraction_assets"]
    funding_cap = b["wholesale_funding"] + opening_assets * assumptions["funding"]["incremental_cap_fraction_assets"]
    sale_cap = b["securities"] * assumptions["securities"]["sale_cap_fraction"]
    segmented = assumptions.get("asset_segments", {}).get("enabled", False)
    if segmented:
        sale_cap = min(sale_cap, assumptions["asset_segments"]["permitted_security_sale_book_usd"])
    eve_limit = b["equity"] * assumptions["constraints"]["maximum_eve_loss_fraction_equity"]
    audited_paths = 0

    def audit_scenario(scenario: dict, baseline: dict, group: str) -> None:
        nonlocal audited_paths
        audited_paths += 1
        previous = {"cash_usd": b["cash"], "securities_usd": b["securities"], "loans_usd": b["loans"], "deposits_usd": b["interest_deposits"] + b["noninterest_deposits"], "wholesale_funding_usd": b["wholesale_funding"], "equity_usd": b["equity"], "derivative_value_usd": 0.0, "payment_payable_usd": 0.0, "posted_initial_margin_usd": 0.0, "posted_variation_margin_usd": 0.0}
        requests = settled = sales = 0.0
        segment_specs = {s["id"]: s for s in assumptions.get("asset_segments", {}).get("segments", [])}
        segment_previous = {key: {"ending_book_usd": spec["opening_book_usd"], "pledged_book_usd": spec["opening_book_usd"] * spec["pledged_fraction"], "cumulative_principal_usd": 0.0, "cumulative_credit_loss_usd": 0.0, "cumulative_sale_book_usd": 0.0} for key, spec in segment_specs.items()}
        rows = scenario["monthly"]
        events = [scenario["initial_event"], *rows]
        if [row["month"] for row in rows] != list(range(1, 13)):
            raise ValueError("Saved monthly ledger must contain exactly months 1 through 12")
        if events[0]["month"] != 0:
            raise ValueError("Saved initial event must be month zero")
        for row in events:
            prefix = f"{group}/{scenario['id']} month {row['month']}"
            coupon = row["swap_net_coupon_usd"]
            closeout = row["swap_closeout_cashflow_usd"]
            remuneration = row["collateral_interest_usd"]
            fee = row["transaction_fee_usd"]
            operating_cost = row.get("operating_expense_usd", 0.0)
            credit_loss = row.get("credit_loss_usd", 0.0)
            restricted_flow = row.get("pledged_principal_cash_flow_usd", 0.0)
            restricted_cash = row.get("pledged_cash_usd", 0.0)
            close(row["nii_usd"], row["interest_income_usd"] - row["interest_expense_usd"], prefix + " NII")
            close(row["interest_expense_usd"], row["deposit_interest_expense_usd"] + row["funding_interest_expense_usd"], prefix + " interest costs")
            close(row["opening_cash_usd"], previous["cash_usd"], prefix + " opening cash")
            close(row["cash_usd"], previous["cash_usd"] + row["interest_income_usd"] + row["loan_principal_usd"] + row["security_principal_usd"] + row["prefunding_usd"] + row["new_borrowing_usd"] + row["asset_sales_usd"] + max(coupon, 0.0) + max(closeout, 0.0) + max(remuneration, 0.0) + row["collateral_released_flow_usd"] - row["payments_settled_usd"] - row["collateral_posted_flow_usd"] - row["settled_withdrawal_usd"] - restricted_flow, prefix + " cash")
            close(restricted_cash, previous.get("pledged_cash_usd", 0.0) + restricted_flow, prefix + " restricted principal cash")
            equity_change = row["nii_usd"] + row["sale_pnl_usd"] + coupon + remuneration + row["swap_mtm_pnl_usd"] - fee - operating_cost - credit_loss
            close(row["equity_change_usd"], equity_change, prefix + " earnings recognition")
            close(row["equity_usd"], previous["equity_usd"] + equity_change, prefix + " equity")
            obligations = row["interest_expense_usd"] + max(-coupon, 0.0) + max(-closeout, 0.0) + max(-remuneration, 0.0) + fee + operating_cost
            close(row["payment_obligations_incurred_usd"], obligations, prefix + " obligations incurred")
            close(row["payment_payable_usd"], previous["payment_payable_usd"] + obligations - row["payments_settled_usd"], prefix + " unpaid obligations")
            close(row["derivative_value_usd"], previous["derivative_value_usd"] + row["swap_mtm_pnl_usd"] - closeout, prefix + " derivative mark and unwind")
            posted = row["posted_initial_margin_usd"] + row["posted_variation_margin_usd"]
            previous_posted = previous["posted_initial_margin_usd"] + previous["posted_variation_margin_usd"]
            close(posted, previous_posted + row["collateral_posted_flow_usd"] - row["collateral_released_flow_usd"], prefix + " posted collateral stock")
            required_im = scenario["swap_notional_usd"] * assumptions["hedge"]["initial_margin_fraction"] if row["month"] < 12 else 0.0
            close(row["initial_margin_required_usd"], required_im, prefix + " IM requirement")
            close(row["variation_margin_required_usd"], max(-row["derivative_value_usd"], 0.0), prefix + " VM requirement")
            close(row["unfunded_margin_usd"], max(0.0, required_im + row["variation_margin_required_usd"] - posted), prefix + " unmet margin")
            close(row["received_collateral_cash_usd"], max(row["derivative_value_usd"], 0.0), prefix + " segregated received margin")
            close(row["collateral_return_liability_usd"], row["received_collateral_cash_usd"], prefix + " collateral return obligation")
            close(row["received_collateral_interest_income_usd"], row["received_collateral_interest_expense_usd"], prefix + " segregated remuneration")
            close(row["hedge_adjusted_interest_earnings_usd"], row["nii_usd"] + coupon + remuneration, prefix + " hedge interest earnings")
            close(row["loans_usd"], previous["loans_usd"] - row["loan_principal_usd"] - credit_loss, prefix + " loans")
            business_costs = assumptions.get("business_costs", {})
            expected_operating = opening_assets * business_costs["annual_operating_expense_fraction_assets"] / 12 if business_costs.get("enabled") and row["month"] else 0.0
            expected_credit_loss = previous["loans_usd"] * business_costs["annual_credit_loss_fraction_loans"] / 12 if business_costs.get("enabled") and row["month"] else 0.0
            close(operating_cost, expected_operating, prefix + " operating expense assumption")
            close(credit_loss, expected_credit_loss, prefix + " credit loss assumption")
            close(row["securities_usd"], previous["securities_usd"] - row["securities_sale_book_usd"] - row["security_principal_usd"], prefix + " securities")
            close(row["sale_pnl_usd"], row["asset_sales_usd"] - row["securities_sale_book_usd"], prefix + " sale PNL")
            close(row["asset_sales_usd"], row["securities_sale_book_usd"] * row["securities_sale_price_ratio"], prefix + " sale proceeds")
            close(row["deposits_usd"], previous["deposits_usd"] - row["settled_withdrawal_usd"], prefix + " deposit liability")
            close(row["wholesale_funding_usd"], previous["wholesale_funding_usd"] + row["prefunding_usd"] + row["new_borrowing_usd"], prefix + " debt")
            close(row["cash_usd"] + row["loans_usd"] + row["securities_usd"] + b["other_assets"] + row["derivative_value_usd"] + posted + row["received_collateral_cash_usd"] + restricted_cash, row["deposits_usd"] + row["wholesale_funding_usd"] + b["other_liabilities"] + row["equity_usd"] + row["collateral_return_liability_usd"] + row["payment_payable_usd"], prefix + " balance sheet")
            requests += row["requested_withdrawal_usd"]
            settled += row["settled_withdrawal_usd"]
            sales += row["securities_sale_book_usd"]
            close(row["cumulative_requested_withdrawals_usd"], requests, prefix + " requested cumulative")
            close(row["cumulative_settled_withdrawals_usd"], settled, prefix + " settled cumulative")
            close(row["cumulative_unfunded_withdrawals_usd"], requests - settled, prefix + " pending")
            close(row["unmet_cash_floor_usd"], max(0.0, cash_floor - row["cash_usd"]), prefix + " cash floor")
            if row["wholesale_funding_usd"] > funding_cap + tolerance or sales > sale_cap + tolerance:
                raise ValueError("Saved scenario exceeds a funding or securities sale cap")
            for field in ("cash_usd", "posted_initial_margin_usd", "posted_variation_margin_usd", "received_collateral_cash_usd", "payment_payable_usd", "payments_settled_usd", "collateral_posted_flow_usd", "collateral_released_flow_usd"):
                if row[field] < -tolerance:
                    raise ValueError(f"Negative saved stock or unsigned flow: {prefix} {field}")
            if row["posted_initial_margin_usd"] > required_im + tolerance or row["posted_variation_margin_usd"] > row["variation_margin_required_usd"] + tolerance:
                raise ValueError("Saved posted margin exceeds its requirement")
            if row["month"] != 0 and row["prefunding_usd"] != 0:
                raise ValueError("Prefunding must occur only in the initial event")
            if row["month"] != 12 and closeout != 0:
                raise ValueError("Swap liquidation must occur only at the terminal month")
            if scenario["swap_notional_usd"] and row["month"]:
                previous_date = date.fromisoformat(snapshot["as_of"] if row["month"] == 1 else previous["swap_payment_date"])
                payment_date = date.fromisoformat(row["swap_payment_date"])
                accrual = (payment_date - previous_date).days / 365.0
                if abs(row["swap_accrual_fraction"] - accrual) > 1e-12:
                    raise ValueError("Saved swap accrual does not match its dated ACT/365F period")
                close(row["swap_fixed_payment_usd"], scenario["swap_notional_usd"] * scenario["swap_fixed_rate"] * accrual, prefix + " fixed coupon")
                close(coupon, row["swap_floating_receipt_usd"] - row["swap_fixed_payment_usd"], prefix + " net coupon")
                previous_df = 1.0 if row["month"] == 1 else previous["swap_discount_factor_from_open"]
                discount = row["swap_discount_factor_from_open"]
                if discount <= 0 or accrual <= 0:
                    raise ValueError("Swap dates and discount factors must advance with positive accruals")
                interval_growth = previous_df / discount - 1.0
                if abs(row["swap_collateral_rate"] * accrual - interval_growth) > 1e-12:
                    raise ValueError("Saved collateral rate differs from the discount-implied interval return")
                close(remuneration, previous_posted * interval_growth, prefix + " interest on actual prior posted collateral")
                close(row["received_collateral_interest_income_usd"], previous["received_collateral_cash_usd"] * interval_growth, prefix + " segregated collateral income")
                fixing = scenario["swap_terms"]["first_floating_fixing"] * accrual if row["month"] == 1 else interval_growth
                close(row["swap_floating_receipt_usd"], scenario["swap_notional_usd"] * fixing, prefix + " forward floating coupon")
                close(previous["derivative_value_usd"] * previous_df / discount, coupon + row["derivative_value_usd"] + closeout, prefix + " discounted coupon and value identity")
            if segmented:
                inventory = {part["segment_id"]: part for part in row["asset_segment_inventory"]}
                flows = {part["segment_id"]: part for part in row["asset_segment_flows"]}
                sold = {part["segment_id"]: part for part in row["asset_segment_sales"]}
                expected_restricted = math.fsum(flow["principal_usd"] * segment_previous[key]["pledged_book_usd"] / segment_previous[key]["ending_book_usd"] for key, flow in flows.items() if flow["asset_class"] == "securities" and segment_previous[key]["ending_book_usd"]) if assumptions["asset_segments"]["assumptions"].get("pledged_principal_treatment") == "retain_cash_collateral" else 0.0
                close(restricted_flow, expected_restricted, prefix + " pledged principal segregation")
                if set(inventory) != set(segment_specs) or (row["month"] and set(flows) != set(segment_specs)):
                    raise ValueError("Saved per-band inventory or flow coverage is incomplete")
                for key, state in inventory.items():
                    start = segment_previous[key]
                    flow = flows.get(key, {})
                    sale = sold.get(key, {})
                    principal = flow.get("principal_usd", 0.0)
                    loss = flow.get("credit_loss_usd", 0.0)
                    book_sale = sale.get("book_sold_usd", 0.0)
                    before_sale = start["ending_book_usd"] - principal - loss
                    pledge = start["pledged_book_usd"] * before_sale / start["ending_book_usd"] if start["ending_book_usd"] else 0.0
                    close(state["initial_book_usd"], segment_specs[key]["opening_book_usd"], prefix + " segment opening " + key)
                    close(state["ending_book_usd"], before_sale - book_sale, prefix + " segment book " + key)
                    close(state["pledged_book_usd"], pledge, prefix + " segment pledge " + key)
                    for field, increment in (("cumulative_principal_usd", principal), ("cumulative_credit_loss_usd", loss), ("cumulative_sale_book_usd", book_sale)):
                        close(state[field], start[field] + increment, prefix + " segment " + field + " " + key)
                    close(state["initial_book_usd"], state["ending_book_usd"] + state["cumulative_principal_usd"] + state["cumulative_credit_loss_usd"] + state["cumulative_sale_book_usd"], prefix + " segment lifetime " + key)
                    if flow:
                        close(flow["opening_book_usd"], start["ending_book_usd"], prefix + " segment opening flow " + key)
                        close(flow["ending_book_before_sale_usd"], before_sale, prefix + " segment before sale " + key)
                    if sale:
                        close(sale["proceeds_usd"], book_sale * sale["price_ratio"], prefix + " segment sale " + key)
                    if state["ending_book_usd"] < -tolerance or book_sale > before_sale - pledge + tolerance or (not segment_specs[key]["sale_eligible"] and book_sale > tolerance):
                        raise ValueError("Saved segment sale consumes pledged or ineligible inventory")
                for asset_class, balance_key, principal_key in (("loans", "loans_usd", "loan_principal_usd"), ("securities", "securities_usd", "security_principal_usd")):
                    close(row[balance_key], math.fsum(part["ending_book_usd"] for part in inventory.values() if part["asset_class"] == asset_class), prefix + " segment total " + asset_class)
                    close(row[principal_key], math.fsum(part["principal_usd"] for part in flows.values() if part["asset_class"] == asset_class), prefix + " segment principal " + asset_class)
                close(row["interest_income_usd"] - row["cash_interest_income_usd"], math.fsum(part["interest_income_usd"] for part in flows.values()), prefix + " segment interest total")
                close(credit_loss, math.fsum(part["credit_loss_usd"] for part in flows.values()), prefix + " segment credit total")
                close(row["securities_sale_book_usd"], math.fsum(part["book_sold_usd"] for part in sold.values()), prefix + " segment sale total")
                close(row["asset_sales_usd"], math.fsum(part["proceeds_usd"] for part in sold.values()), prefix + " segment proceeds total")
                segment_previous = inventory
            previous = row
        close(requests, (b["interest_deposits"] + b["noninterest_deposits"]) * scenario["deposit_runoff_pct"] / 100, scenario["id"] + " requested scenario total")
        close(scenario["nii_12m_usd"], math.fsum(row["nii_usd"] for row in rows), scenario["id"] + " annual NII")
        close(scenario["delta_nii_usd"], scenario["nii_12m_usd"] - baseline["nii_12m_usd"], scenario["id"] + " NII delta")
        close(scenario["delta_eve_usd"], scenario["eve_usd"] - baseline["eve_usd"], scenario["id"] + " EVE delta")
        close(scenario["eve_usd"], math.fsum(scenario["eve_components_usd"].values()), scenario["id"] + " EVE components")
        close(scenario["min_cash_usd"], min(row["cash_usd"] for row in rows), scenario["id"] + " minimum cash")
        close(scenario["minimum_observed_cash_usd"], min(row["cash_usd"] for row in events), scenario["id"] + " cash including inception")
        close(scenario["securities_sold_usd"], sales, scenario["id"] + " securities sale total")
        close(scenario["securities_sale_proceeds_usd"], math.fsum(row["asset_sales_usd"] for row in events), scenario["id"] + " sale proceeds total")
        close(scenario["realized_sale_pnl_usd"], math.fsum(row["sale_pnl_usd"] for row in events), scenario["id"] + " sale PNL total")
        close(scenario["swap_coupon_total_usd"], math.fsum(row["swap_net_coupon_usd"] for row in events), scenario["id"] + " coupons total")
        close(scenario["collateral_interest_total_usd"], math.fsum(row["collateral_interest_usd"] for row in events), scenario["id"] + " collateral interest total")
        close(scenario["swap_terminal_closeout_usd"], rows[-1]["swap_closeout_cashflow_usd"], scenario["id"] + " terminal settlement")
        close(scenario["transaction_fee_usd"], math.fsum(row["transaction_fee_usd"] for row in events), scenario["id"] + " fees total")
        close(scenario["transaction_fee_usd"], scenario["swap_notional_usd"] * assumptions["hedge"]["transaction_fee_bps"] / 10000, scenario["id"] + " fee assumption")
        close(scenario["opening_swap_value_usd"], events[0]["derivative_value_usd"], scenario["id"] + " opening mark")
        close(scenario["hedge_adjusted_interest_earnings_usd"], scenario["nii_12m_usd"] + scenario["swap_coupon_total_usd"] + scenario["collateral_interest_total_usd"], scenario["id"] + " total hedge earnings")
        close(scenario.get("operating_expense_total_usd", 0.0), math.fsum(row.get("operating_expense_usd", 0.0) for row in events), scenario["id"] + " annual operating costs")
        close(scenario.get("credit_loss_total_usd", 0.0), math.fsum(row.get("credit_loss_usd", 0.0) for row in events), scenario["id"] + " annual credit losses")
        close(scenario["modeled_earnings_usd"], scenario["hedge_adjusted_interest_earnings_usd"] + scenario["realized_sale_pnl_usd"] + scenario["swap_terminal_closeout_usd"] - scenario["transaction_fee_usd"] - scenario.get("operating_expense_total_usd", 0.0) - scenario.get("credit_loss_total_usd", 0.0), scenario["id"] + " total modeled earnings")
        close(scenario["modeled_earnings_usd"], rows[-1]["equity_usd"] - b["equity"], scenario["id"] + " retained earnings and ending wealth")
        for field in ("derivative_value_usd", "posted_initial_margin_usd", "posted_variation_margin_usd", "received_collateral_cash_usd", "collateral_return_liability_usd"):
            close(rows[-1][field], 0.0, scenario["id"] + " terminal release " + field)
        maxima = {"peak_wholesale_funding_usd": "wholesale_funding_usd", "max_unfunded_withdrawals_usd": "cumulative_unfunded_withdrawals_usd", "max_unfunded_margin_usd": "unfunded_margin_usd", "max_payment_payable_usd": "payment_payable_usd", "max_cash_floor_shortfall_usd": "unmet_cash_floor_usd", "max_posted_variation_margin_usd": "posted_variation_margin_usd", "max_received_collateral_cash_usd": "received_collateral_cash_usd"}
        for summary, field in maxima.items():
            close(scenario[summary], max(row[field] for row in events), scenario["id"] + " " + summary)
        close(scenario["max_collateral_required_usd"], max(row["initial_margin_required_usd"] + row["variation_margin_required_usd"] for row in events), scenario["id"] + " peak required collateral")
        close(scenario["max_collateral_posted_usd"], max(row["posted_initial_margin_usd"] + row["posted_variation_margin_usd"] for row in events), scenario["id"] + " peak posted collateral")
        failures = []
        if max(row["cumulative_unfunded_withdrawals_usd"] for row in events) > tolerance:
            failures.append("requested_withdrawals_unfunded")
        if min(row["cash_usd"] for row in events) < cash_floor - tolerance:
            failures.append("cash_floor_breached")
        if max(row["unfunded_margin_usd"] for row in events) > tolerance:
            failures.append("margin_requirement_unfunded")
        if max(row["payment_payable_usd"] for row in events) > tolerance:
            failures.append("payment_obligation_unsettled")
        if scenario["delta_eve_usd"] < -eve_limit - tolerance:
            failures.append("assumed_eve_loss_limit_breached")
        if set(failures) != set(scenario["breaches"]):
            raise ValueError("Saved breach labels disagree with the financial evidence")

    def audit_group(scenarios: list[dict], group: str) -> None:
        baseline = next(row for row in scenarios if row["id"] == "baseline")
        if len({row["id"] for row in scenarios}) != len(scenarios):
            raise ValueError("Duplicate saved scenario identifiers")
        for scenario in scenarios:
            audit_scenario(scenario, baseline, group)

    audit_group(analysis["scenarios"], "unhedged reference")
    if _groups_only:
        return {"passed": True, "audited_scenario_paths": audited_paths, "independent_numeric_comparisons": tested, "max_residual_usd": max_residual, "tolerance_usd": tolerance}
    policies = analysis["policies"]
    grid = assumptions["policy_grid"]
    expected_grid = set(product(grid["prefunding_fractions_assets"], grid["funding_orders"], grid["hedge_fractions_assets"]))
    actual_grid = [(p["prefunding_fraction"], p["funding_order"], p["hedge_fraction_assets"]) for p in policies["candidates"]]
    if len(actual_grid) != len(expected_grid) or set(actual_grid) != expected_grid:
        raise ValueError("Saved policy grid is incomplete or contains duplicate combinations")
    for field, expected_limit in {"cash_floor_usd": cash_floor, "maximum_additional_funding_usd": funding_cap - b["wholesale_funding"], "maximum_securities_sale_book_usd": sale_cap, "maximum_eve_loss_usd": eve_limit, "unfunded_withdrawals_allowed_usd": 0.0, "unfunded_margin_allowed_usd": 0.0, "unsettled_payment_allowed_usd": 0.0}.items():
        close(policies["constraints"][field], expected_limit, "common constraint " + field)
    feasible = [p for p in policies["candidates"] if p["feasible"]]
    for policy in policies["candidates"]:
        audit_group(policy["scenarios"], policy["id"])
        if {s["id"] for s in policy["scenarios"]} != set(policies["evaluation_scenarios"]):
            raise ValueError("Policy scenarios differ from the frozen evaluation set")
        close(policy["swap_notional_usd"], opening_assets * policy["hedge_fraction_assets"], policy["id"] + " notional")
        for scenario in policy["scenarios"]:
            close(scenario["swap_notional_usd"], policy["swap_notional_usd"], policy["id"] + " scenario notional")
            close(scenario["initial_event"]["prefunding_usd"], opening_assets * policy["prefunding_fraction"], policy["id"] + " prefunding")
        if policy["feasible"] != all(not scenario["breaches"] for scenario in policy["scenarios"]):
            raise ValueError("Policy feasibility conflicts with its scenario results")
        close(policy["worst_case_earnings_usd"], min(s["modeled_earnings_usd"] for s in policy["scenarios"]), policy["id"] + " objective")
        close(policy["worst_case_nii_usd"], min(s["nii_12m_usd"] for s in policy["scenarios"]), policy["id"] + " worst NII")
        close(policy["worst_case_delta_eve_usd"], min(s["delta_eve_usd"] for s in policy["scenarios"]), policy["id"] + " worst EVE delta")
    if policies["feasible_count"] != len(feasible):
        raise ValueError("Incorrect feasible-policy count")
    best = max(feasible, key=lambda p: p["worst_case_earnings_usd"]) if feasible else None
    if policies["selected_policy_id"] != (best["id"] if best else None):
        raise ValueError("Policy selection violates the declared constrained objective")
    displayed = analysis["policy_analysis"]
    expected = best or max(policies["candidates"], key=lambda p: p["worst_case_earnings_usd"])
    if displayed["policy_id"] != expected["id"] or displayed["scenarios"] != expected["scenarios"] or displayed["selection_status"] != ("selected" if best else "diagnostic_unselected"):
        raise ValueError("Displayed policy analysis differs from the audited candidate or selection status")
    references = {s["id"]: s for s in analysis["scenarios"]}
    displayed_scenarios = {s["id"]: s for s in displayed["scenarios"]}
    if len(analysis["hedge_comparison"]) != len(displayed_scenarios):
        raise ValueError("Hedge comparison must cover the displayed scenarios")
    for comparison in analysis["hedge_comparison"]:
        for field in ("delta_eve_usd", "nii_12m_usd", "modeled_earnings_usd"):
            close(comparison["unhedged_" + field], references[comparison["scenario_id"]][field], "reference comparison " + field)
            close(comparison["policy_" + field], displayed_scenarios[comparison["scenario_id"]][field], "policy comparison " + field)
        close(comparison["policy_hedge_adjusted_interest_earnings_usd"], displayed_scenarios[comparison["scenario_id"]]["hedge_adjusted_interest_earnings_usd"], "policy comparison hedge earnings")
    reverse = analysis["reverse_stress"]
    ordered = sorted(reverse["grid"], key=lambda r: (r["rate_shock_bps"], r["deposit_runoff_pct"]))
    if ordered != reverse["grid"] or next((r for r in ordered if r["breaches"]), None) != reverse["first_observed_failure"]:
        raise ValueError("Reverse-stress result does not follow its declared grid order")
    return {"passed": True, "audited_scenario_paths": audited_paths, "independent_numeric_comparisons": tested, "max_residual_usd": max_residual, "tolerance_usd": tolerance}


def audit_scenario_group(scenarios: list[dict], snapshot: dict, assumptions: dict) -> dict:
    """Audit a baseline and its challenges without reselecting any policy."""
    return audit_saved_analysis({"scenarios": scenarios}, snapshot, assumptions, _groups_only=True)


def verify_release(output: Path | None = None) -> dict:
    destination = output or ROOT / "output"
    status = read_json(destination / "run_status.json")
    if status.get("status") != "verified_build":
        raise ValueError("The latest build is not verified")
    if status["manifest_sha256"] != digest(destination / "manifest.json"):
        raise ValueError("Build status refers to a different manifest")
    manifest = read_json(destination / "manifest.json")
    if manifest["input_hashes"] != fingerprint():
        raise ValueError("Source, assumptions or code changed after the saved build")
    for name, expected in manifest["artifact_hashes"].items():
        if digest(destination / name) != expected:
            raise ValueError(f"Saved artifact changed: {name}")
    from .research import prepare_research_inputs, evidence_summary
    from .storage import read_gzip_json, compact_analysis, compact_challenges
    from .robustness import audit_robustness
    snapshot, _ = validate_sources()
    reference_assumptions = read_json(ROOT / "configs/assumptions.json")
    research = prepare_research_inputs(snapshot, reference_assumptions)
    analysis = read_gzip_json(destination / "analysis_full.json.gz")
    reference = read_gzip_json(destination / "reference_analysis_full.json.gz")
    challenges = read_gzip_json(destination / "robustness_full.json.gz")
    if compact_analysis(analysis) != read_json(destination / "analysis.json") or compact_analysis(reference) != read_json(destination / "reference_analysis.json"):
        raise ValueError("Portable analysis differs from the full saved ledger evidence")
    if compact_challenges(challenges) != read_json(destination / "robustness.json"):
        raise ValueError("Portable challenges differ from full saved ledger evidence")
    if analysis["assumptions"] != research["extended_assumptions"] or reference["assumptions"] != reference_assumptions:
        raise ValueError("Saved assumptions do not match verified source/configuration preparation")
    if analysis["research_evidence"] != evidence_summary(research, analysis, challenges["primary"], challenges["reference"]):
        raise ValueError("Research summary does not reproduce from the saved evidence")
    if not analysis.get("checks") or any(c.get("passed") is not True for c in analysis["checks"]):
        raise ValueError("Saved technical controls do not all pass")
    primary_audit = audit_saved_analysis(analysis, snapshot, analysis["assumptions"])
    reference_audit = audit_saved_analysis(reference, snapshot, reference_assumptions)
    challenge_audits = {key: audit_robustness(value, snapshot, analysis if key == "primary" else reference) for key, value in challenges.items()}
    return {"passed": True, "primary": primary_audit, "reference": reference_audit, "challenges": challenge_audits}
