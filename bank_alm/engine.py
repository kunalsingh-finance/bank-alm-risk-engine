"""Transparent aggregate-bank ALM research, with a closed monthly ledger.

Public balances anchor scale only. Assumed cash flows are not actual bank ALM.
No network access, random numbers, optimization packages, or silent cash plugs.
"""
from __future__ import annotations

import copy
import math
from datetime import date

from .numerics import amortizing_cashflows, bullet_cashflows, interpolate_zero, present_value, shock_bps
from .segmentation import advance_assets, asset_values, initialize_state, inventory_snapshot, sell_securities, validate_segments

BASE = {"id": "baseline", "name": "Unshocked baseline", "description": "Static opening portfolio with loan runoff, retained modeled earnings and no requested deposit withdrawals.", "shape": "parallel", "shock_bps": 0, "deposit_runoff_fraction": 0}
TOLERANCE = 1.0  # Absolute dollars, far below source reporting precision.


def _assets(b: dict) -> float:
    return sum(b[k] for k in ("cash", "securities", "loans", "other_assets")) + sum(b.get(k, 0.0) for k in ("derivative_value", "posted_initial_margin", "posted_variation_margin", "received_collateral_cash", "pledged_cash"))


def _residual(b: dict) -> float:
    return _assets(b) - sum(b[k] for k in ("noninterest_deposits", "interest_deposits", "wholesale_funding", "other_liabilities", "equity")) - b.get("collateral_return_liability", 0.0) - b.get("payment_payable", 0.0)


def _index(curve: dict, scenario: dict) -> float:
    z = interpolate_zero(0.25, curve["tenors_years"], curve["zero_rates"]) + shock_bps(0.25, scenario) / 10000.0
    return math.expm1(z * 0.25) / 0.25


def _rates(a: dict, curve: dict, scenario: dict) -> dict:
    short = _index(curve, scenario)
    change = short - _index(curve, BASE)
    return {
        "cash": max(0.0, short - a["cash"]["yield_spread"]),
        "floating_loan": max(0.0, a["loans"]["floating_coupon"] + change),
        "deposit": max(a["deposits"]["minimum_interest_rate"], a["deposits"]["interest_rate"] + a["deposits"]["beta"] * change),
        "original_funding": max(0.0, a["funding"]["initial_coupon"] + a["funding"]["initial_repricing_beta"] * change),
        "new_funding": max(0.0, short + a["funding"]["incremental_spread"]),
        "prefunding": max(0.0, _index(curve, BASE) + a["funding"]["incremental_spread"]),
        "cpr": min(a["loans"]["maximum_cpr"], a["loans"]["prepayment_cpr"] * math.exp(-a["loans"]["prepayment_rate_sensitivity"] * change)),
    }


def economic_value(snapshot: dict, a: dict, curve: dict, scenario: dict,
                   prefunding_fraction: float = 0.0) -> dict:
    """Opening, pre-management estimated economic value of assumed cash flows."""
    b = snapshot["balance_sheet_usd"]
    r = _rates(a, curve, scenario)
    runoff = scenario.get("deposit_runoff_fraction", 0.0)
    loan = a["loans"]
    dep = a["deposits"]
    funding = a["funding"]
    prefunding = _assets(b) * prefunding_fraction
    pv = lambda flows, spread=0.0: present_value(flows, curve, scenario, spread)
    securities = pv(bullet_cashflows(b["securities"], a["securities"]["coupon"], a["securities"]["maturity_years"]))
    fixed = pv(amortizing_cashflows(b["loans"] * loan["fixed_fraction"], loan["fixed_coupon"], loan["maturity_years"], r["cpr"]), loan["discount_spread"])
    floating = pv(amortizing_cashflows(b["loans"] * (1 - loan["fixed_fraction"]), loan["floating_coupon"], loan["maturity_years"], r["cpr"], r["floating_loan"], loan["floating_reset_lag_months"]), loan["discount_spread"])
    noninterest = b["noninterest_deposits"] * runoff + pv(amortizing_cashflows(b["noninterest_deposits"] * (1 - runoff), 0.0, dep["noninterest_maturity_years"]))
    interest = b["interest_deposits"] * runoff + pv(amortizing_cashflows(b["interest_deposits"] * (1 - runoff), dep["interest_rate"], dep["interest_maturity_years"], 0.0, r["deposit"], dep["repricing_lag_months"]))
    original_funding = pv(bullet_cashflows(b["wholesale_funding"], funding["initial_coupon"], funding["initial_maturity_years"], r["original_funding"], 0), funding["discount_spread"])
    term_funding = pv(bullet_cashflows(prefunding, r["prefunding"], funding["prefunding_maturity_years"]), funding["discount_spread"])
    components = {"cash": b["cash"] + prefunding, "securities": securities, "fixed_loans": fixed, "floating_loans": floating, "other_assets": b["other_assets"], "noninterest_deposits": -noninterest, "interest_deposits": -interest, "existing_funding": -original_funding, "prefunding": -term_funding, "other_liabilities": -b["other_liabilities"]}
    if a.get("asset_segments", {}).get("enabled"):
        values = asset_values(a["asset_segments"], curve, scenario, r["cpr"], _index(curve, scenario) - _index(curve, BASE))
        components["securities"] = values["securities_usd"]
        del components["fixed_loans"], components["floating_loans"]
        components["segmented_loans"] = values["loans_usd"]
    return {"eve_usd": math.fsum(components.values()), "components_usd": components, "effective_cpr": r["cpr"], "repriced_deposit_rate": r["deposit"]}


def _sale_price_ratio(a: dict, curve: dict, scenario: dict, month: int) -> float:
    remaining = a["securities"]["maturity_years"] - month / 12.0
    if remaining <= 0:
        return 1.0
    flows = bullet_cashflows(1.0, a["securities"]["coupon"], remaining)
    return present_value(flows, curve, scenario) / present_value(flows, curve, BASE)


def _simulate_unhedged(snapshot: dict, a: dict, curve: dict, scenario: dict,
                      policy: dict | None = None) -> dict:
    """Run 12 months. Unsettled withdrawals remain deposit liabilities."""
    policy = policy or {"prefunding_fraction": 0.0, "funding_order": "borrow_first"}
    b = {k: float(v) for k, v in snapshot["balance_sheet_usd"].items()}
    opening = b.copy()
    total_assets = _assets(b)
    original_deposits = b["noninterest_deposits"] + b["interest_deposits"]
    interest_share = b["interest_deposits"] / original_deposits if original_deposits else 0.0
    earning_fraction = snapshot.get("totals_usd", {}).get("interest_bearing_cash", b["cash"]) / b["cash"] if b["cash"] else 1.0
    floor = a["cash"]["floor_fraction_assets"] * total_assets
    capacity = a["funding"]["incremental_cap_fraction_assets"] * total_assets
    prefunding = policy["prefunding_fraction"] * total_assets
    if prefunding > capacity + TOLERANCE:
        raise ValueError("Prefunding cannot exceed the common incremental borrowing cap")
    b["cash"] += prefunding
    b["wholesale_funding"] += prefunding
    reactive = 0.0
    sold_book = 0.0
    cumulative_requested = 0.0
    cumulative_settled = 0.0
    pending = 0.0
    rates = _rates(a, curve, scenario)
    monthly = []
    loan = a["loans"]
    smm = 1.0 - (1.0 - rates["cpr"]) ** (1.0 / 12.0)
    scheduled_principal = opening["loans"] / round(loan["maturity_years"] * 12)
    base_eve = economic_value(snapshot, a, curve, BASE, policy["prefunding_fraction"])["eve_usd"]
    stressed_eve = economic_value(snapshot, a, curve, scenario, policy["prefunding_fraction"])
    for month in range(1, 13):
        start_cash = b["cash"]
        floating_coupon = rates["floating_loan"] if month > loan["floating_reset_lag_months"] else loan["floating_coupon"]
        deposit_rate = rates["deposit"] if month > a["deposits"]["repricing_lag_months"] else a["deposits"]["interest_rate"]
        cash_income = max(b["cash"], 0.0) * earning_fraction * rates["cash"] / 12
        security_income = b["securities"] * a["securities"]["coupon"] / 12
        loan_income = b["loans"] * (loan["fixed_fraction"] * loan["fixed_coupon"] + (1 - loan["fixed_fraction"]) * floating_coupon) / 12
        income = cash_income + security_income + loan_income
        deposit_expense = b["interest_deposits"] * deposit_rate / 12
        funding_expense = (opening["wholesale_funding"] * rates["original_funding"] + prefunding * rates["prefunding"] + reactive * rates["new_funding"]) / 12
        expense = deposit_expense + funding_expense
        nii = income - expense
        b["cash"] += nii
        b["equity"] += nii
        principal = min(b["loans"], scheduled_principal)
        principal += (b["loans"] - principal) * smm
        b["loans"] -= principal
        b["cash"] += principal
        security_principal = 0.0
        if month == round(a["securities"]["maturity_years"] * 12):
            security_principal = b["securities"]
            b["cash"] += security_principal
            b["securities"] = 0.0
        requested = original_deposits * scenario.get("deposit_runoff_fraction", 0.0) * a["runoff_monthly_weights"][month - 1]
        cumulative_requested += requested
        pending += requested
        need = max(0.0, pending + floor - b["cash"])
        proceeds = book_sale = pnl = new_borrowing = 0.0
        price = _sale_price_ratio(a, curve, scenario, month)
        actions = ("borrow", "sell") if policy["funding_order"] == "borrow_first" else ("sell", "borrow")
        for action in actions:
            if action == "borrow":
                draw = min(need, max(0.0, capacity - prefunding - reactive))
                b["cash"] += draw
                b["wholesale_funding"] += draw
                reactive += draw
                new_borrowing += draw
            else:
                available_book = min(b["securities"], max(0.0, opening["securities"] * a["securities"]["sale_cap_fraction"] - sold_book))
                sale = min(available_book, need / price)
                sale_proceeds = sale * price
                sale_pnl = sale_proceeds - sale
                b["securities"] -= sale
                b["cash"] += sale_proceeds
                b["equity"] += sale_pnl
                sold_book += sale
                book_sale += sale
                proceeds += sale_proceeds
                pnl += sale_pnl
            need = max(0.0, pending + floor - b["cash"])
        settled = min(pending, max(0.0, b["cash"]))
        b["cash"] -= settled
        b["interest_deposits"] -= settled * interest_share
        b["noninterest_deposits"] -= settled * (1 - interest_share)
        pending -= settled
        cumulative_settled += settled
        row = {"month": month, "cash_usd": b["cash"], "securities_usd": b["securities"], "loans_usd": b["loans"], "deposits_usd": b["interest_deposits"] + b["noninterest_deposits"], "wholesale_funding_usd": b["wholesale_funding"], "equity_usd": b["equity"], "interest_income_usd": income, "interest_expense_usd": expense, "nii_usd": nii, "asset_sales_usd": proceeds, "sale_pnl_usd": pnl, "accounting_residual_usd": _residual(b), "securities_sale_book_usd": book_sale, "securities_sale_price_ratio": price, "new_borrowing_usd": new_borrowing, "loan_principal_usd": principal, "security_principal_usd": security_principal, "requested_withdrawal_usd": requested, "settled_withdrawal_usd": settled, "cumulative_requested_withdrawals_usd": cumulative_requested, "cumulative_settled_withdrawals_usd": cumulative_settled, "cumulative_unfunded_withdrawals_usd": pending, "unmet_cash_floor_usd": max(0.0, floor - b["cash"]), "deposit_interest_rate": deposit_rate, "cash_interest_income_usd": cash_income, "deposit_interest_expense_usd": deposit_expense, "funding_interest_expense_usd": funding_expense, "cash_rollforward_residual_usd": b["cash"] - (start_cash + nii + principal + security_principal + new_borrowing + proceeds - settled), "deposit_conservation_residual_usd": original_deposits - (b["interest_deposits"] + b["noninterest_deposits"]) - cumulative_settled}
        monthly.append(row)
    delta_eve = stressed_eve["eve_usd"] - base_eve
    max_pending = max(row["cumulative_unfunded_withdrawals_usd"] for row in monthly)
    max_shortfall = max(row["unmet_cash_floor_usd"] for row in monthly)
    breaches = []
    if max_pending > TOLERANCE:
        breaches.append("requested_withdrawals_unfunded")
    if max_shortfall > TOLERANCE:
        breaches.append("cash_floor_breached")
    if -delta_eve > opening["equity"] * a["constraints"]["maximum_eve_loss_fraction_equity"] + TOLERANCE:
        breaches.append("assumed_eve_loss_limit_breached")
    nii_total = math.fsum(row["nii_usd"] for row in monthly)
    sale_pnl = math.fsum(row["sale_pnl_usd"] for row in monthly)
    return {"id": scenario["id"], "name": scenario["name"], "description": scenario["description"], "rate_shock_bps": shock_bps(0.25, scenario), "rate_shock_label": "parallel shift" if scenario.get("shape", "parallel") == "parallel" else "0.25-year zero-node shift; see shape", "shock_profile": [{"tenor_years": t, "shock_bps": shock_bps(t, scenario)} for t in curve["tenors_years"]], "deposit_runoff_pct": scenario.get("deposit_runoff_fraction", 0.0) * 100, "eve_usd": stressed_eve["eve_usd"], "delta_eve_usd": delta_eve, "eve_components_usd": stressed_eve["components_usd"], "nii_12m_usd": nii_total, "delta_nii_usd": 0.0, "modeled_earnings_usd": nii_total + sale_pnl, "min_cash_usd": min(row["cash_usd"] for row in monthly), "peak_wholesale_funding_usd": max(row["wholesale_funding_usd"] for row in monthly), "securities_sold_usd": sold_book, "securities_sale_proceeds_usd": math.fsum(row["asset_sales_usd"] for row in monthly), "realized_sale_pnl_usd": sale_pnl, "max_unfunded_withdrawals_usd": max_pending, "ending_unfunded_withdrawals_usd": pending, "max_cash_floor_shortfall_usd": max_shortfall, "cash_floor_usd": floor, "funding_cap_usd": opening["wholesale_funding"] + capacity, "max_accounting_residual_usd": max(abs(row["accounting_residual_usd"]) for row in monthly), "effective_cpr": rates["cpr"], "status": "breach" if breaches else "within_assumed_limits", "breaches": breaches, "monthly": monthly}


def _enrich_unhedged(out: dict, snapshot: dict, policy: dict) -> dict:
    """Keep the original zero-hedge numbers and expose the extended ledger schema."""
    opening = snapshot["balance_sheet_usd"]
    prefunding = _assets(opening) * policy.get("prefunding_fraction", 0.0)
    zero_fields = ("derivative_value_usd", "posted_initial_margin_usd", "posted_variation_margin_usd", "received_collateral_cash_usd", "collateral_return_liability_usd", "payment_payable_usd", "initial_margin_required_usd", "variation_margin_required_usd", "unfunded_margin_usd", "swap_net_coupon_usd", "swap_mtm_pnl_usd", "swap_closeout_cashflow_usd", "collateral_interest_usd", "received_collateral_interest_income_usd", "received_collateral_interest_expense_usd", "transaction_fee_usd", "collateral_posted_flow_usd", "collateral_released_flow_usd", "payment_obligations_incurred_usd", "equity_rollforward_residual_usd")
    initial = {key: 0.0 for key in out["monthly"][0]}
    initial.update({"month": 0, "cash_usd": opening["cash"] + prefunding, "opening_cash_usd": opening["cash"], "securities_usd": opening["securities"], "loans_usd": opening["loans"], "deposits_usd": opening["noninterest_deposits"] + opening["interest_deposits"], "wholesale_funding_usd": opening["wholesale_funding"] + prefunding, "equity_usd": opening["equity"], "prefunding_usd": prefunding, "unmet_cash_floor_usd": max(0.0, out["cash_floor_usd"] - opening["cash"] - prefunding), "payments_settled_usd": 0.0, "equity_change_usd": 0.0, "hedge_adjusted_interest_earnings_usd": 0.0})
    initial.update({key: 0.0 for key in zero_fields})
    previous_cash = initial["cash_usd"]
    for row in out["monthly"]:
        row.update({key: 0.0 for key in zero_fields})
        row.update({"operating_expense_usd": 0.0, "credit_loss_usd": 0.0})
        row.update({"opening_cash_usd": previous_cash, "prefunding_usd": 0.0, "payments_settled_usd": row["interest_expense_usd"], "payment_obligations_incurred_usd": row["interest_expense_usd"], "equity_change_usd": row["nii_usd"] + row["sale_pnl_usd"], "hedge_adjusted_interest_earnings_usd": row["nii_usd"]})
        previous_cash = row["cash_usd"]
    for row in [initial] + out["monthly"]:
        row.update({"pledged_principal_cash_flow_usd": 0.0, "pledged_cash_usd": 0.0})
        row.update({"collateral_required_usd": 0.0, "collateral_posted_usd": 0.0, "swap_payment_date": None, "swap_accrual_fraction": 0.0, "swap_fixed_payment_usd": 0.0, "swap_floating_receipt_usd": 0.0, "swap_collateral_rate": 0.0, "swap_discount_factor_from_open": 1.0})
    out.update({"initial_event": initial, "swap_notional_usd": 0.0, "swap_fixed_rate": None, "opening_swap_value_usd": 0.0, "swap_coupon_total_usd": 0.0, "collateral_interest_total_usd": 0.0, "swap_terminal_closeout_usd": 0.0, "swap_realized_total_pnl_usd": 0.0, "transaction_fee_usd": 0.0, "hedge_adjusted_interest_earnings_usd": out["nii_12m_usd"], "initial_margin_usd": 0.0, "max_collateral_required_usd": 0.0, "max_collateral_posted_usd": 0.0, "max_posted_variation_margin_usd": 0.0, "max_received_collateral_cash_usd": 0.0, "max_unfunded_margin_usd": 0.0, "max_payment_payable_usd": 0.0})
    out["minimum_observed_cash_usd"] = min(out["min_cash_usd"], initial["cash_usd"])
    initial.update({"operating_expense_usd": 0.0, "credit_loss_usd": 0.0})
    out.update({"operating_expense_total_usd": 0.0, "credit_loss_total_usd": 0.0, "business_costs_included": False})
    out["max_cash_floor_shortfall_usd"] = max(out["max_cash_floor_shortfall_usd"], initial["unmet_cash_floor_usd"])
    if initial["unmet_cash_floor_usd"] > TOLERANCE and "cash_floor_breached" not in out["breaches"]:
        out["breaches"].append("cash_floor_breached")
        out["status"] = "breach"
    return out


def simulate_scenario(snapshot: dict, a: dict, curve: dict, scenario: dict,
                      policy: dict | None = None) -> dict:
    """Run a bilateral collateralized swap and bank ledger, including time zero.

    VM received is segregated and cannot fund withdrawals. Negative cash
    obligations accrue as liabilities until paid. Margin requirements that
    cannot be posted are explicit breaches, not fictitious posted assets.
    """
    policy = policy or {"prefunding_fraction": 0.0, "funding_order": "borrow_first", "hedge_fraction_assets": 0.0}
    costs = a.get("business_costs", {})
    costs_enabled = costs.get("enabled", False)
    segment_config = a.get("asset_segments", {})
    segmented = segment_config.get("enabled", False)
    retain_pledged_principal = segmented and segment_config.get("assumptions", {}).get("pledged_principal_treatment", "release_on_payment") == "retain_cash_collateral"
    if not policy.get("hedge_fraction_assets", 0.0) and not costs_enabled and not segmented:
        return _enrich_unhedged(_simulate_unhedged(snapshot, a, curve, scenario, policy), snapshot, policy)
    from .swaps import swap_path
    b = {k: float(v) for k, v in snapshot["balance_sheet_usd"].items()}
    opening = b.copy()
    total_assets = _assets(opening)
    notional = total_assets * policy.get("hedge_fraction_assets", 0.0)
    path = swap_path(curve, scenario, snapshot["as_of"], notional, tenor_months=a["hedge"]["tenor_months"], horizon_months=12)
    hedge = a["hedge"]
    fee = notional * hedge["transaction_fee_bps"] / 10000
    initial_margin = notional * hedge["initial_margin_fraction"]
    prefunding = total_assets * policy["prefunding_fraction"]
    capacity = total_assets * a["funding"]["incremental_cap_fraction_assets"]
    if prefunding > capacity + TOLERANCE:
        raise ValueError("Prefunding cannot exceed the common incremental borrowing cap")
    floor = total_assets * a["cash"]["floor_fraction_assets"]
    original_deposits = opening["noninterest_deposits"] + opening["interest_deposits"]
    interest_share = opening["interest_deposits"] / original_deposits if original_deposits else 0.0
    earning_fraction = snapshot.get("totals_usd", {}).get("interest_bearing_cash", opening["cash"]) / opening["cash"] if opening["cash"] else 1.0
    for key in ("derivative_value", "posted_initial_margin", "posted_variation_margin", "received_collateral_cash", "collateral_return_liability", "payment_payable", "pledged_cash"):
        b[key] = 0.0
    rates = _rates(a, curve, scenario)
    short_rate_change = _index(curve, scenario) - _index(curve, BASE)
    asset_state = initialize_state(segment_config) if segmented else None
    security_sale_cap = min(opening["securities"] * a["securities"]["sale_cap_fraction"], segment_config["permitted_security_sale_book_usd"]) if segmented else opening["securities"] * a["securities"]["sale_cap_fraction"]
    loan = a["loans"]
    smm = 1 - (1 - rates["cpr"]) ** (1 / 12)
    scheduled_principal = opening["loans"] / round(loan["maturity_years"] * 12)
    reactive = sold_book = requested_total = settled_total = pending = 0.0
    events = []

    for month in range(13):
        start_cash = b["cash"]
        start_equity = b["equity"]
        start_payable = b["payment_payable"]
        previous_derivative = b["derivative_value"]
        incoming_coupon = incoming_closeout = incoming_collateral_interest = 0.0
        income = expense = nii = principal = security_principal = coupon = mark_pnl = closeout = collateral_interest = received_interest = deposit_expense = funding_expense = cash_income = requested = event_fee = event_prefunding = 0.0
        operating_expense = credit_loss = pledged_principal = 0.0
        segment_flows = None
        segment_sales = []
        deposit_rate = a["deposits"]["interest_rate"]
        if month == 0:
            event_prefunding = prefunding
            event_fee = fee
            b["cash"] += prefunding
            b["wholesale_funding"] += prefunding
            b["payment_payable"] += fee
            b["equity"] -= fee
            mark = path["opening_value_usd"]
            mark_pnl = mark
            b["derivative_value"] = mark
            b["equity"] += mark
        else:
            swap_row = path["monthly"][month - 1]
            floating_coupon = rates["floating_loan"] if month > loan["floating_reset_lag_months"] else loan["floating_coupon"]
            deposit_rate = rates["deposit"] if month > a["deposits"]["repricing_lag_months"] else a["deposits"]["interest_rate"]
            cash_income = b["cash"] * earning_fraction * rates["cash"] / 12
            income = cash_income + b["securities"] * a["securities"]["coupon"] / 12 + b["loans"] * (loan["fixed_fraction"] * loan["fixed_coupon"] + (1 - loan["fixed_fraction"]) * floating_coupon) / 12
            if segmented:
                segment_flows = advance_assets(asset_state, month, rates["cpr"], short_rate_change, costs["annual_credit_loss_fraction_loans"] / 12 if costs_enabled else 0.0)
                income = cash_income + segment_flows["securities_income_usd"] + segment_flows["loans_income_usd"]
            deposit_expense = b["interest_deposits"] * deposit_rate / 12
            funding_expense = (opening["wholesale_funding"] * rates["original_funding"] + prefunding * rates["prefunding"] + reactive * rates["new_funding"]) / 12
            expense = deposit_expense + funding_expense
            nii = income - expense
            b["cash"] += income
            b["payment_payable"] += expense
            b["equity"] += nii
            if costs_enabled:
                operating_expense = total_assets * costs["annual_operating_expense_fraction_assets"] / 12
                credit_loss = min(b["loans"], b["loans"] * costs["annual_credit_loss_fraction_loans"] / 12)
                if segmented:
                    credit_loss = segment_flows["credit_loss_usd"]
                b["payment_payable"] += operating_expense
                b["equity"] -= operating_expense + credit_loss
                b["loans"] -= credit_loss
            principal = min(b["loans"], scheduled_principal)
            principal += (b["loans"] - principal) * smm
            if segmented:
                principal = segment_flows["loans_principal_usd"]
                security_principal = segment_flows["securities_principal_usd"]
                b["securities"] -= security_principal
            b["loans"] -= principal
            b["cash"] += principal + security_principal
            if retain_pledged_principal:
                pledged_principal = segment_flows["pledged_securities_principal_usd"]
                b["cash"] -= pledged_principal
                b["pledged_cash"] += pledged_principal
            collateral_interest = (b["posted_initial_margin"] + b["posted_variation_margin"]) * swap_row["collateral_rate"] * swap_row["accrual_fraction"]
            received_interest = b["received_collateral_cash"] * swap_row["collateral_rate"] * swap_row["accrual_fraction"]
            # Segregated received collateral earns and owes identical interest;
            # both are settled within the segregated account, with zero free cash.
            incoming_collateral_interest = max(collateral_interest, 0.0)
            b["cash"] += incoming_collateral_interest
            b["payment_payable"] += max(-collateral_interest, 0.0)
            b["equity"] += collateral_interest
            coupon = swap_row["net_coupon_usd"]
            incoming_coupon = max(coupon, 0.0)
            b["cash"] += incoming_coupon
            b["payment_payable"] += max(-coupon, 0.0)
            b["equity"] += coupon
            mark = swap_row["swap_value_usd"]
            mark_pnl = mark - previous_derivative
            b["derivative_value"] = mark
            b["equity"] += mark_pnl
            if month == 12:
                closeout = swap_row["closeout_cashflow_usd"]
                incoming_closeout = max(closeout, 0.0)
                b["cash"] += incoming_closeout
                b["payment_payable"] += max(-closeout, 0.0)
                b["derivative_value"] = 0.0
            requested = original_deposits * scenario.get("deposit_runoff_fraction", 0.0) * a["runoff_monthly_weights"][month - 1]
            requested_total += requested
            pending += requested
        target_im = initial_margin if month < 12 else 0.0
        target_vm = max(-b["derivative_value"], 0.0) if month < 12 else 0.0
        target_received = max(b["derivative_value"], 0.0) if month < 12 else 0.0
        b["received_collateral_cash"] = target_received
        b["collateral_return_liability"] = target_received
        released = max(0.0, b["posted_initial_margin"] - target_im) + max(0.0, b["posted_variation_margin"] - target_vm)
        b["cash"] += released
        b["posted_initial_margin"] = min(b["posted_initial_margin"], target_im)
        b["posted_variation_margin"] = min(b["posted_variation_margin"], target_vm)
        im_due = target_im - b["posted_initial_margin"]
        vm_due = target_vm - b["posted_variation_margin"]
        need = max(0.0, b["payment_payable"] + im_due + vm_due + pending + floor - b["cash"])
        proceeds = book_sale = sale_pnl = borrowing = 0.0
        price = 1.0 if segmented else _sale_price_ratio(a, curve, scenario, month)
        actions = ("borrow", "sell") if policy["funding_order"] == "borrow_first" else ("sell", "borrow")
        for action in actions:
            if action == "borrow":
                draw = min(need, max(0.0, capacity - prefunding - reactive))
                b["cash"] += draw
                b["wholesale_funding"] += draw
                reactive += draw
                borrowing += draw
            else:
                if segmented:
                    allocation = sell_securities(asset_state, need, curve, scenario, month, max(0.0, security_sale_cap - sold_book), short_rate_change, rates["cpr"], a["loans"]["prepayment_cpr"])
                    sale, cash_sale, price = allocation["book_sold_usd"], allocation["proceeds_usd"], allocation["weighted_price_ratio"]
                    segment_sales = allocation["rows"]
                else:
                    available = min(b["securities"], max(0.0, security_sale_cap - sold_book))
                    sale = min(available, need / price)
                    cash_sale = sale * price
                b["securities"] -= sale
                b["cash"] += cash_sale
                b["equity"] += cash_sale - sale
                sold_book += sale
                book_sale += sale
                proceeds += cash_sale
                sale_pnl += cash_sale - sale
            need = max(0.0, b["payment_payable"] + im_due + vm_due + pending + floor - b["cash"])
        incurred = b["payment_payable"] - start_payable
        payments = min(b["payment_payable"], b["cash"])
        b["cash"] -= payments
        b["payment_payable"] -= payments
        im_posted = min(im_due, b["cash"])
        b["cash"] -= im_posted
        b["posted_initial_margin"] += im_posted
        vm_posted = min(vm_due, b["cash"])
        b["cash"] -= vm_posted
        b["posted_variation_margin"] += vm_posted
        settled = min(pending, b["cash"])
        b["cash"] -= settled
        b["interest_deposits"] -= settled * interest_share
        b["noninterest_deposits"] -= settled * (1 - interest_share)
        pending -= settled
        settled_total += settled
        margin_shortfall = max(0.0, target_im + target_vm - b["posted_initial_margin"] - b["posted_variation_margin"])
        equity_change = nii + coupon + collateral_interest + mark_pnl + sale_pnl - event_fee - operating_expense - credit_loss
        expected_cash = start_cash + event_prefunding + income + principal + security_principal + incoming_coupon + incoming_closeout + incoming_collateral_interest + released + borrowing + proceeds - payments - im_posted - vm_posted - settled - pledged_principal
        row = {"month": month, "opening_cash_usd": start_cash, "prefunding_usd": event_prefunding, "cash_usd": b["cash"], "securities_usd": b["securities"], "loans_usd": b["loans"], "deposits_usd": b["interest_deposits"] + b["noninterest_deposits"], "wholesale_funding_usd": b["wholesale_funding"], "equity_usd": b["equity"], "interest_income_usd": income, "interest_expense_usd": expense, "nii_usd": nii, "asset_sales_usd": proceeds, "sale_pnl_usd": sale_pnl, "accounting_residual_usd": _residual(b), "securities_sale_book_usd": book_sale, "securities_sale_price_ratio": price, "new_borrowing_usd": borrowing, "loan_principal_usd": principal, "security_principal_usd": security_principal, "requested_withdrawal_usd": requested, "settled_withdrawal_usd": settled, "cumulative_requested_withdrawals_usd": requested_total, "cumulative_settled_withdrawals_usd": settled_total, "cumulative_unfunded_withdrawals_usd": pending, "unmet_cash_floor_usd": max(0.0, floor - b["cash"]), "deposit_interest_rate": deposit_rate, "cash_interest_income_usd": cash_income, "deposit_interest_expense_usd": deposit_expense, "funding_interest_expense_usd": funding_expense, "cash_rollforward_residual_usd": b["cash"] - expected_cash, "deposit_conservation_residual_usd": original_deposits - b["interest_deposits"] - b["noninterest_deposits"] - settled_total, "derivative_value_usd": b["derivative_value"], "posted_initial_margin_usd": b["posted_initial_margin"], "posted_variation_margin_usd": b["posted_variation_margin"], "received_collateral_cash_usd": b["received_collateral_cash"], "collateral_return_liability_usd": b["collateral_return_liability"], "payment_payable_usd": b["payment_payable"], "initial_margin_required_usd": target_im, "variation_margin_required_usd": target_vm, "unfunded_margin_usd": margin_shortfall, "swap_net_coupon_usd": coupon, "swap_mtm_pnl_usd": mark_pnl, "swap_closeout_cashflow_usd": closeout, "collateral_interest_usd": collateral_interest, "received_collateral_interest_income_usd": received_interest, "received_collateral_interest_expense_usd": received_interest, "transaction_fee_usd": event_fee, "collateral_posted_flow_usd": im_posted + vm_posted, "collateral_released_flow_usd": released, "payments_settled_usd": payments, "payment_obligations_incurred_usd": incurred, "equity_change_usd": equity_change, "equity_rollforward_residual_usd": b["equity"] - start_equity - equity_change, "hedge_adjusted_interest_earnings_usd": nii + coupon + collateral_interest}
        row.update({"collateral_required_usd": target_im + target_vm, "collateral_posted_usd": b["posted_initial_margin"] + b["posted_variation_margin"], "swap_payment_date": snapshot["as_of"] if month == 0 else swap_row["payment_date"], "swap_accrual_fraction": 0.0 if month == 0 else swap_row["accrual_fraction"], "swap_fixed_payment_usd": 0.0 if month == 0 else swap_row["fixed_payment_usd"], "swap_floating_receipt_usd": 0.0 if month == 0 else swap_row["floating_receipt_usd"], "swap_collateral_rate": 0.0 if month == 0 else swap_row["collateral_rate"], "swap_discount_factor_from_open": 1.0 if month == 0 else swap_row["discount_factor_from_open"]})
        row.update({"operating_expense_usd": operating_expense, "credit_loss_usd": credit_loss})
        row.update({"pledged_principal_cash_flow_usd": pledged_principal, "pledged_cash_usd": b["pledged_cash"]})
        if segmented:
            row.update({"asset_segment_flows": segment_flows["rows"] if segment_flows else [], "asset_segment_sales": segment_sales, "asset_segment_inventory": inventory_snapshot(asset_state), "securities_inventory_residual_usd": b["securities"] - math.fsum(s["book_usd"] for s in asset_state if s["asset_class"] == "securities"), "loans_inventory_residual_usd": b["loans"] - math.fsum(s["book_usd"] for s in asset_state if s["asset_class"] == "loans")})
        events.append(row)
    base_value = economic_value(snapshot, a, curve, BASE, policy["prefunding_fraction"])["eve_usd"] - fee
    stressed = economic_value(snapshot, a, curve, scenario, policy["prefunding_fraction"])
    stressed["components_usd"].update({"swap": path["opening_value_usd"], "transaction_fee": -fee})
    eve = stressed["eve_usd"] + path["opening_value_usd"] - fee
    delta_eve = eve - base_value
    max_pending = max(row["cumulative_unfunded_withdrawals_usd"] for row in events)
    max_floor = max(row["unmet_cash_floor_usd"] for row in events)
    max_margin = max(row["unfunded_margin_usd"] for row in events)
    max_payable = max(row["payment_payable_usd"] for row in events)
    breaches = []
    for test, name in ((max_pending > TOLERANCE, "requested_withdrawals_unfunded"), (max_floor > TOLERANCE, "cash_floor_breached"), (max_margin > TOLERANCE, "margin_requirement_unfunded"), (max_payable > TOLERANCE, "payment_obligation_unsettled"), (-delta_eve > opening["equity"] * a["constraints"]["maximum_eve_loss_fraction_equity"] + TOLERANCE, "assumed_eve_loss_limit_breached")):
        if test: breaches.append(name)
    nii_total = math.fsum(row["nii_usd"] for row in events)
    coupons = math.fsum(row["swap_net_coupon_usd"] for row in events)
    collateral_income = math.fsum(row["collateral_interest_usd"] for row in events)
    sales_pnl = math.fsum(row["sale_pnl_usd"] for row in events)
    terminal = events[-1]["swap_closeout_cashflow_usd"]
    operating_total = math.fsum(row["operating_expense_usd"] for row in events)
    credit_total = math.fsum(row["credit_loss_usd"] for row in events)
    return {"id": scenario["id"], "name": scenario["name"], "description": scenario["description"], "rate_shock_bps": shock_bps(0.25, scenario), "rate_shock_label": "parallel shift" if scenario.get("shape", "parallel") == "parallel" else "0.25-year zero-node shift; see shape", "shock_profile": [{"tenor_years": t, "shock_bps": shock_bps(t, scenario)} for t in curve["tenors_years"]], "deposit_runoff_pct": scenario.get("deposit_runoff_fraction", 0.0) * 100, "eve_usd": eve, "delta_eve_usd": delta_eve, "eve_components_usd": stressed["components_usd"], "nii_12m_usd": nii_total, "delta_nii_usd": 0.0, "hedge_adjusted_interest_earnings_usd": nii_total + coupons + collateral_income, "modeled_earnings_usd": nii_total + coupons + collateral_income + sales_pnl + terminal - fee - operating_total - credit_total, "operating_expense_total_usd": operating_total, "credit_loss_total_usd": credit_total, "business_costs_included": costs_enabled, "min_cash_usd": min(row["cash_usd"] for row in events[1:]), "minimum_observed_cash_usd": min(row["cash_usd"] for row in events), "peak_wholesale_funding_usd": max(row["wholesale_funding_usd"] for row in events), "securities_sold_usd": sold_book, "securities_sale_proceeds_usd": math.fsum(row["asset_sales_usd"] for row in events), "realized_sale_pnl_usd": sales_pnl, "max_unfunded_withdrawals_usd": max_pending, "ending_unfunded_withdrawals_usd": pending, "max_cash_floor_shortfall_usd": max_floor, "cash_floor_usd": floor, "funding_cap_usd": opening["wholesale_funding"] + capacity, "max_accounting_residual_usd": max(abs(row["accounting_residual_usd"]) for row in events), "effective_cpr": rates["cpr"], "status": "breach" if breaches else "within_assumed_limits", "breaches": breaches, "monthly": events[1:], "initial_event": events[0], "swap_notional_usd": notional, "swap_fixed_rate": path["terms"]["fixed_rate"], "swap_terms": path["terms"], "opening_swap_value_usd": path["opening_value_usd"], "swap_coupon_total_usd": coupons, "collateral_interest_total_usd": collateral_income, "swap_terminal_closeout_usd": terminal, "swap_realized_total_pnl_usd": coupons + terminal, "transaction_fee_usd": fee, "initial_margin_usd": initial_margin, "max_collateral_required_usd": max(row["initial_margin_required_usd"] + row["variation_margin_required_usd"] for row in events), "max_collateral_posted_usd": max(row["posted_initial_margin_usd"] + row["posted_variation_margin_usd"] for row in events), "max_posted_variation_margin_usd": max(row["posted_variation_margin_usd"] for row in events), "max_received_collateral_cash_usd": max(row["received_collateral_cash_usd"] for row in events), "max_unfunded_margin_usd": max_margin, "max_payment_payable_usd": max_payable}


def validate_inputs(snapshot: dict, a: dict, curve: dict) -> None:
    def require(condition: bool, message: str) -> None:
        if not condition:
            raise ValueError(message)
    def finite(value: object) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    b = snapshot["balance_sheet_usd"]
    keys = ("cash", "securities", "loans", "other_assets", "noninterest_deposits", "interest_deposits", "wholesale_funding", "other_liabilities", "equity")
    require(all(k in b and finite(b[k]) and b[k] >= 0 for k in keys), "Balance buckets must be finite nonnegative USD")
    require(_assets(b) > 0 and b["equity"] > 0, "Positive assets and equity required")
    require(abs(_residual(b)) <= TOLERANCE, "Opening balance sheet does not close")
    require(date.fromisoformat(curve["as_of"]) <= date.fromisoformat(snapshot["as_of"]), "Curve observation date is later than bank date")
    tenors, rates = curve["tenors_years"], curve["zero_rates"]
    require(len(tenors) == len(rates) and len(tenors) >= 2, "Curve nodes must have equal lengths >=2")
    require(all(finite(t) and t > 0 for t in tenors) and all(x < y for x, y in zip(tenors, tenors[1:])), "Curve tenors must increase strictly")
    require(all(finite(r) and -0.25 < r < 1.0 for r in rates), "Curve rates must be finite decimals in supported range")
    require(a["horizon_months"] == 12, "Only the documented 12-month horizon is supported")
    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("enabled", "sale_eligible", "prepayment_eligible") and isinstance(value, bool):
                    continue
                walk(value)
        elif isinstance(node, list):
            for v in node: walk(v)
        elif isinstance(node, (int, float)):
            require(finite(node), "Assumption numbers must be finite")
    walk(a)
    for section, key in (("loans", "fixed_fraction"), ("loans", "prepayment_cpr"), ("loans", "maximum_cpr"), ("deposits", "beta"), ("securities", "sale_cap_fraction"), ("funding", "incremental_cap_fraction_assets"), ("cash", "floor_fraction_assets")):
        require(0 <= a[section][key] <= 1, f"{section}.{key} must be between 0 and 1")
    require(a["loans"]["prepayment_cpr"] <= a["loans"]["maximum_cpr"] < 1, "CPR must be below 1 and within maximum")
    for section, key in (("loans", "maturity_years"), ("securities", "maturity_years"), ("funding", "initial_maturity_years"), ("funding", "prefunding_maturity_years")):
        months = a[section][key] * 12
        require(abs(months - round(months)) < 1e-9 and round(months) > 12, f"{section}.{key} must be on a whole-month grid and exceed 12 months in this ledger")
    for key in ("interest_maturity_years", "noninterest_maturity_years"):
        months = a["deposits"][key] * 12
        require(months >= 1 and abs(months - round(months)) < 1e-9, "Deposit maturity must be on a whole-month grid of at least one month")
    for section, key in (("loans", "floating_reset_lag_months"), ("deposits", "repricing_lag_months")):
        lag = a[section][key]
        require(isinstance(lag, int) and not isinstance(lag, bool) and 0 <= lag <= 120, "Reset lags must be integer months in [0,120]")
    for section, keys in {"cash": ("yield_spread",), "securities": ("coupon",), "loans": ("fixed_coupon", "floating_coupon", "discount_spread"), "deposits": ("interest_rate", "minimum_interest_rate"), "funding": ("initial_coupon", "discount_spread", "incremental_spread", "initial_repricing_beta")}.items():
        for key in keys:
            require(0 <= a[section][key] <= 1, f"{section}.{key} must be a supported nonnegative decimal in [0,1]")
    require(0 <= a["loans"]["prepayment_rate_sensitivity"] <= 100, "Prepayment sensitivity must be in [0,100]")
    require(0 <= a["constraints"]["maximum_eve_loss_fraction_equity"] <= 1, "EVE loss limit must be in [0,1]")
    weights = a["runoff_monthly_weights"]
    require(len(weights) == 12 and all(w >= 0 for w in weights) and abs(sum(weights) - 1) < 1e-12, "Runoff weights must be 12 nonnegative values summing to one")
    require(len({s["id"] for s in a["scenarios"]}) == len(a["scenarios"]) and all(s["id"] != "baseline" for s in a["scenarios"]), "Scenario IDs must be unique and exclude baseline")
    for s in a["scenarios"]:
        require(0 <= s.get("deposit_runoff_fraction", 0) <= 1, "Runoff fraction must be in [0,1]")
        require(abs(s.get("shock_bps", 0)) <= 10000, "Shock magnitude outside supported +/-10000 bps")
        shock_bps(0.25, s)
    grid = a["policy_grid"]
    require(bool(grid["evaluation_scenario_ids"]) and set(grid["evaluation_scenario_ids"]) <= {s["id"] for s in a["scenarios"]}, "Policy evaluation must name existing scenarios")
    require(bool(grid["prefunding_fractions_assets"]) and all(0 <= p <= a["funding"]["incremental_cap_fraction_assets"] for p in grid["prefunding_fractions_assets"]), "Policy prefunding must respect common cap")
    require(bool(grid["funding_orders"]) and set(grid["funding_orders"]) <= {"borrow_first", "sell_first"}, "Unknown funding policy order")
    require(bool(grid["hedge_fractions_assets"]) and all(0 <= h <= 1 for h in grid["hedge_fractions_assets"]), "Hedge fractions must be nonempty and in [0,1]")
    require(isinstance(a["hedge"]["tenor_months"], int) and 12 < a["hedge"]["tenor_months"] <= 360, "Swap tenor must be integer months greater than12 and at most360")
    require(0 <= a["hedge"]["initial_margin_fraction"] <= 1 and 0 <= a["hedge"]["transaction_fee_bps"] <= 1000, "Invalid collateral or transaction fee assumption")
    require(a["hedge"]["type"] == "pay_fixed_receive_floating" and a["hedge"]["closeout_month"] == 12, "Only payer-fixed trades unwound at month12 are supported")
    require(bool(a["reverse_stress"]["deposit_runoff_fractions"]) and all(0 <= v <= 1 for v in a["reverse_stress"]["deposit_runoff_fractions"]), "Reverse stress runoff fractions must be nonempty and in [0,1]")
    require(bool(a["reverse_stress"]["parallel_shocks_bps"]) and all(abs(v) <= 10000 for v in a["reverse_stress"]["parallel_shocks_bps"]), "Reverse stress shocks must be nonempty and within supported range")
    require(all(0 <= v <= 1 for v in a["sensitivity"]["deposit_betas"]), "Sensitivity beta must be in [0,1]")
    require(all(0 <= v <= a["loans"]["maximum_cpr"] for v in a["sensitivity"]["prepayment_cprs"]), "Sensitivity CPR must remain within configured maximum")
    require(all(v >= 1 / 12 and abs(v * 12 - round(v * 12)) < 1e-9 for v in a["sensitivity"]["deposit_maturity_years"]), "Sensitivity deposit maturity must lie on a positive whole-month grid")
    earning = snapshot.get("totals_usd", {}).get("interest_bearing_cash", b["cash"])
    require(finite(earning) and 0 <= earning <= b["cash"], "Interest-bearing cash must be within total cash")
    if a.get("asset_segments", {}).get("enabled"):
        segments = a["asset_segments"]
        require(segments["certificate"] == snapshot["certificate"] and segments["as_of"] == snapshot["as_of"], "Asset segment legal entity or date mismatch")
        validate_segments(segments, b)
    costs = a.get("business_costs", {})
    require(isinstance(costs.get("enabled", False), bool), "Business-cost enabled flag must be boolean")
    if costs.get("enabled", False):
        for key in ("annual_operating_expense_fraction_assets", "annual_credit_loss_fraction_loans"):
            require(finite(costs.get(key)) and 0 <= costs[key] <= 1, f"business_costs.{key} must be a decimal in [0,1]")


def run_analysis(snapshot: dict, assumptions: dict, curve: dict) -> dict:
    validate_inputs(snapshot, assumptions, curve)
    a = assumptions
    all_runs = []
    def run(scenario: dict, config: dict = a, policy: dict | None = None) -> dict:
        outcome = simulate_scenario(snapshot, config, curve, scenario, policy)
        outcome["asset_model"] = "sourced_bands_with_explicit_assumptions" if config.get("asset_segments", {}).get("enabled") else "aggregate_reference"
        outcome["securities_sale_cap_usd"] = min(snapshot["balance_sheet_usd"]["securities"] * config["securities"]["sale_cap_fraction"], config["asset_segments"]["permitted_security_sale_book_usd"]) if config.get("asset_segments", {}).get("enabled") else snapshot["balance_sheet_usd"]["securities"] * config["securities"]["sale_cap_fraction"]
        all_runs.append(outcome)
        return outcome
    baseline = run(BASE)
    scenarios = [baseline] + [run(s) for s in a["scenarios"]]
    for s in scenarios:
        s["delta_nii_usd"] = s["nii_12m_usd"] - baseline["nii_12m_usd"]
    selected_scenarios = [BASE] + [s for s in a["scenarios"] if s["id"] in a["policy_grid"]["evaluation_scenario_ids"]]
    candidates = []
    for fraction in a["policy_grid"]["prefunding_fractions_assets"]:
        for order in a["policy_grid"]["funding_orders"]:
            for hedge_fraction in a["policy_grid"]["hedge_fractions_assets"]:
                policy = {"prefunding_fraction": fraction, "funding_order": order, "hedge_fraction_assets": hedge_fraction}
                outcomes = [run(s, policy=policy) for s in selected_scenarios]
                for outcome in outcomes:
                    outcome["delta_nii_usd"] = outcome["nii_12m_usd"] - outcomes[0]["nii_12m_usd"]
                candidates.append({"id": f"prefund_{round(fraction * 100)}pct_{order}_hedge_{round(hedge_fraction * 100)}pct", **policy, "swap_notional_usd": _assets(snapshot["balance_sheet_usd"]) * hedge_fraction, "feasible": all(not s["breaches"] for s in outcomes), "worst_case_nii_usd": min(s["nii_12m_usd"] for s in outcomes), "worst_case_earnings_usd": min(s["modeled_earnings_usd"] for s in outcomes), "worst_case_delta_eve_usd": min(s["delta_eve_usd"] for s in outcomes), "max_unfunded_withdrawals_usd": max(s["max_unfunded_withdrawals_usd"] for s in outcomes), "max_cash_floor_shortfall_usd": max(s["max_cash_floor_shortfall_usd"] for s in outcomes), "max_unfunded_margin_usd": max(s["max_unfunded_margin_usd"] for s in outcomes), "max_payment_payable_usd": max(s["max_payment_payable_usd"] for s in outcomes), "scenarios": outcomes})
    feasible = [p for p in candidates if p["feasible"]]
    best = max(feasible, key=lambda p: p["worst_case_earnings_usd"]) if feasible else None
    diagnostic = best or max(candidates, key=lambda p: p["worst_case_earnings_usd"])
    policy_analysis = {"policy_id": diagnostic["id"], "selection_status": "selected" if best else "diagnostic_unselected", "policy": {k: diagnostic[k] for k in ("prefunding_fraction", "funding_order", "hedge_fraction_assets", "swap_notional_usd")}, "scenarios": diagnostic["scenarios"], "explanation": "Highest worst-case modeled earnings among feasible grid candidates." if best else "No candidate satisfies all limits. This is the highest-objective infeasible candidate shown for diagnosis; it is not selected."}
    hedge_comparison = []
    reference_by_id = {s["id"]: s for s in scenarios}
    for result in diagnostic["scenarios"]:
        reference = reference_by_id[result["id"]]
        hedge_comparison.append({"scenario_id": result["id"], "unhedged_delta_eve_usd": reference["delta_eve_usd"], "policy_delta_eve_usd": result["delta_eve_usd"], "unhedged_nii_12m_usd": reference["nii_12m_usd"], "policy_nii_12m_usd": result["nii_12m_usd"], "policy_hedge_adjusted_interest_earnings_usd": result["hedge_adjusted_interest_earnings_usd"], "unhedged_modeled_earnings_usd": reference["modeled_earnings_usd"], "policy_modeled_earnings_usd": result["modeled_earnings_usd"], "policy_status": result["status"]})
    reverse = []
    for shock in sorted(a["reverse_stress"]["parallel_shocks_bps"]):
        for runoff in sorted(a["reverse_stress"]["deposit_runoff_fractions"]):
            out = run({"id": f"reverse_{shock}_{runoff}", "name": "Reverse-stress grid", "description": "Discrete research grid cell", "shape": "parallel", "shock_bps": shock, "deposit_runoff_fraction": runoff})
            reverse.append({"rate_shock_bps": shock, "deposit_runoff_pct": runoff * 100, "status": out["status"], "unfunded_withdrawals_usd": out["max_unfunded_withdrawals_usd"], "cash_floor_shortfall_usd": out["max_cash_floor_shortfall_usd"], "delta_eve_usd": out["delta_eve_usd"], "breaches": out["breaches"]})
    sensitivity = []
    sensitivity_scenarios = [{"id": "sensitivity_up", "name": "+200 bp", "description": "Assumption sensitivity", "shape": "parallel", "shock_bps": 200, "deposit_runoff_fraction": 0.0}, {"id": "sensitivity_down", "name": "-200 bp", "description": "Assumption sensitivity", "shape": "parallel", "shock_bps": -200, "deposit_runoff_fraction": 0.0}]
    refs = {s["id"]: run(s) for s in sensitivity_scenarios}
    for param, section, key, values in (("deposit_beta", "deposits", "beta", a["sensitivity"]["deposit_betas"]), ("deposit_maturity_years", "deposits", "interest_maturity_years", a["sensitivity"]["deposit_maturity_years"]), ("prepayment_cpr", "loans", "prepayment_cpr", a["sensitivity"]["prepayment_cprs"])):
        for value in values:
            modified = copy.deepcopy(a)
            modified[section][key] = value
            if param == "deposit_maturity_years": modified["deposits"]["noninterest_maturity_years"] = value
            for s in sensitivity_scenarios:
                out = run(s, config=modified)
                sensitivity.append({"parameter": param, "value": value, "scenario_id": s["id"], "delta_eve_usd": out["delta_eve_usd"], "nii_12m_usd": out["nii_12m_usd"], "delta_nii_vs_reference_usd": out["nii_12m_usd"] - refs[s["id"]]["nii_12m_usd"], "delta_eve_vs_reference_usd": out["delta_eve_usd"] - refs[s["id"]]["delta_eve_usd"]})
    checks = []
    def check(name: str, actual: float, tolerance: float, message: str) -> None:
        checks.append({"name": name, "passed": math.isfinite(actual) and abs(actual) <= tolerance, "actual": actual, "tolerance": tolerance, "message": message, "detail": message})
    check("opening_balance_sheet", _residual(snapshot["balance_sheet_usd"]), TOLERANCE, "Public aggregate assets equal liabilities plus total consolidated equity.")
    check("curve_observation_date_alignment", max(0, (date.fromisoformat(curve["as_of"]) - date.fromisoformat(snapshot["as_of"])).days), 0.0, "Curve observation date does not exceed the bank statement date; this does not establish publication-time availability.")
    for key in ("accounting_residual_usd", "cash_rollforward_residual_usd", "deposit_conservation_residual_usd"):
        check(key, max(abs(row[key]) for run_out in all_runs for row in [run_out["initial_event"]] + run_out["monthly"]), TOLERANCE, "Maximum absolute residual across baseline, named scenarios, every policy, reverse grid and sensitivity case.")
    check("zero_shock_eve_delta", baseline["delta_eve_usd"], TOLERANCE, "Identical cash-flow reconstruction reprices identically.")
    check("equity_event_rollforward", max(abs(row["equity_rollforward_residual_usd"]) for run_out in all_runs for row in [run_out["initial_event"]] + run_out["monthly"]), TOLERANCE, "Each event books bank NII, coupons, collateral interest, derivative mark change, sale PNL and fees exactly once.")
    check("segregated_collateral_conservation", max(abs(row["received_collateral_cash_usd"] - row["collateral_return_liability_usd"]) for run_out in all_runs for row in [run_out["initial_event"]] + run_out["monthly"]), TOLERANCE, "Received variation margin has an equal return liability and does not become free cash.")
    check("swap_mark_to_closeout_conservation", max(abs(math.fsum(row["swap_mtm_pnl_usd"] for row in [run_out["initial_event"]] + run_out["monthly"]) - run_out["swap_terminal_closeout_usd"]) for run_out in all_runs), TOLERANCE, "Opening and subsequent mark changes telescope to terminal fair value; closeout settlement is not additional income.")
    check("terminal_derivative_and_collateral_release", max(abs(run_out["monthly"][-1][key]) for run_out in all_runs for key in ("derivative_value_usd", "posted_initial_margin_usd", "posted_variation_margin_usd", "received_collateral_cash_usd", "collateral_return_liability_usd")), TOLERANCE, "All modeled trades unwind at month12 and all actual posted or received collateral is released or returned.")
    check("withdrawal_request_conservation", max(abs(row["cumulative_requested_withdrawals_usd"] - row["cumulative_settled_withdrawals_usd"] - row["cumulative_unfunded_withdrawals_usd"]) for run_out in all_runs for row in [run_out["initial_event"]] + run_out["monthly"]), TOLERANCE, "Every requested dollar is either settled or still recorded as an unsettled withdrawal request.")
    check("incremental_funding_cap", max(max(0.0, row["wholesale_funding_usd"] - run_out["funding_cap_usd"]) for run_out in all_runs for row in [run_out["initial_event"]] + run_out["monthly"]), TOLERANCE, "No scenario can borrow beyond the declared cap.")
    check("securities_sale_cap", max(max(0.0, run_out["securities_sold_usd"] - snapshot["balance_sheet_usd"]["securities"] * a["securities"]["sale_cap_fraction"]) for run_out in all_runs), TOLERANCE, "Sold book amount remains within the common limit.")
    check("retained_pledged_cash_conservation", max(abs(row["pledged_cash_usd"] - math.fsum(previous["pledged_principal_cash_flow_usd"] for previous in ([result["initial_event"]] + result["monthly"])[:index + 1])) for result in all_runs for index, row in enumerate([result["initial_event"]] + result["monthly"])), TOLERANCE, "Retained pledged principal remains a separate non-interest-bearing asset and is never spent or released during the horizon.")
    if a.get("asset_segments", {}).get("enabled"):
        check("sourced_unpledged_inventory_sale_cap", max(max(0.0, result["securities_sold_usd"] - result["securities_sale_cap_usd"]) for result in all_runs), TOLERANCE, "Sales are further limited by source-anchored, assumed pro-rata unpledged debt inventory.")
        for inventory_key in ("securities_inventory_residual_usd", "loans_inventory_residual_usd"):
            check(inventory_key, max(abs(row[inventory_key]) for result in all_runs for row in [result["initial_event"]] + result["monthly"]), TOLERANCE, "Per-band inventory aggregates exactly to the accounting ledger after principal, credit losses and sales.")
        check("segment_lifetime_book_conservation", max(abs(s["conservation_residual_usd"]) for result in all_runs for row in [result["initial_event"]] + result["monthly"] for s in row["asset_segment_inventory"]), TOLERANCE, "Each segment's initial book equals ending book plus collected principal plus credit loss plus sold book.")
    check("equity_earnings_conservation", max(abs(run_out["monthly"][-1]["equity_usd"] - snapshot["balance_sheet_usd"]["equity"] - run_out["modeled_earnings_usd"]) for run_out in all_runs), TOLERANCE, "Terminal equity change equals modeled earnings including hedges; intermediate swap marks are not counted twice on closeout.")
    check("no_negative_ledger_positions", max(max(0.0, -row[key]) for run_out in all_runs for row in [run_out["initial_event"]] + run_out["monthly"] for key in ("cash_usd", "securities_usd", "loans_usd", "deposits_usd", "wholesale_funding_usd", "posted_initial_margin_usd", "posted_variation_margin_usd", "received_collateral_cash_usd", "collateral_return_liability_usd", "payment_payable_usd")), TOLERANCE, "Unsettled requests and payments stay liabilities; collateral posted is limited to cash actually available. Derivative value alone is a signed asset.")
    earnings = snapshot.get("earnings", {})
    result = {"schema_version": "bank-alm-analysis-v2", "bank": {"name": snapshot["bank_name"], "certificate": snapshot["certificate"], "as_of": snapshot["as_of"]}, "units": "USD (nominal dollars); rates are decimals except bps and deposit_runoff_pct", "baseline": {"nii_12m_usd": baseline["nii_12m_usd"], "eve_usd": baseline["eve_usd"], "historical_nii_usd": earnings.get("annual_nii_usd"), "historical_nii_period": f"{earnings.get('period_start', 'unknown')} through {earnings.get('period_end', 'unknown')}", "modeled_earnings_usd": baseline["modeled_earnings_usd"]}, "scenarios": scenarios, "policies": {"objective": "Maximize minimum modeled retained earnings: raw bank NII + swap coupons + posted-collateral interest + securities sale PNL + terminal swap fair-value closeout - upfront fee, across baseline and the frozen named shocks, subject to unchanged common limits.", "evaluation_scenarios": ["baseline"] + a["policy_grid"]["evaluation_scenario_ids"], "constraints": {"cash_floor_usd": baseline["cash_floor_usd"], "maximum_additional_funding_usd": _assets(snapshot["balance_sheet_usd"]) * a["funding"]["incremental_cap_fraction_assets"], "maximum_securities_sale_book_usd": snapshot["balance_sheet_usd"]["securities"] * a["securities"]["sale_cap_fraction"], "maximum_eve_loss_usd": snapshot["balance_sheet_usd"]["equity"] * a["constraints"]["maximum_eve_loss_fraction_equity"], "unfunded_withdrawals_allowed_usd": 0.0}, "candidates": candidates, "selected_policy_id": best["id"] if best else None, "feasible_count": len(feasible), "caveat": "Finite grid evaluated on these same scenarios; not independent validation or proof of a global optimum. EVE is an opening shock measure before reactive funding and asset sales; policy EVE delta is relative to its own prefunded baseline."}, "reverse_stress": {"definition": "Failure means any common research EVE, cash-floor or withdrawal-service limit breaches under the default borrow-first policy.", "grid": reverse, "first_observed_failure": next((cell for cell in reverse if cell["breaches"]), None), "search_order": "Parallel shock ascending, then runoff ascending within each shock.", "limitations": "First observed means first failing sampled cell in this declared order, not the smallest joint shock, a continuous threshold, or a bank failure probability. Grids can miss failures between sampled points; rate and runoff have no shared severity scale."}, "sensitivity": sensitivity, "checks": checks, "assumptions": copy.deepcopy(a), "limitations": ["An aggregate public-balance reconstruction, not Regions Bank's internal ALM model, forecast, disclosed stress result or regulatory compliance assessment.", "Model NII is a prospective 12-month runoff-book measure; reported historical NII covers a different period and actual activity. No forced calibration is performed.", "EVE prices simplified assumed cash flows and holds residual other assets/liabilities at book. It excludes credit migration, embedded-option calibration, basis risk, franchise value and detailed deposit segmentation.", "EVE uses finite behavioral deposit runoff with no replacement deposits. The NII ledger holds deposits absent explicit stress runoff; the two views use deliberately distinct ALM conventions and are not a single lifetime cash-flow forecast.", "Loan principal and prepayments accumulate as cash. The opening interest-bearing share of cash is held constant as an explicit composition assumption.", "Earnings exclude operating expense, tax, non-swap fees, credit losses and OCI; the disclosed swap transaction fee is included. They cannot be presented as forecast net income.", "Securities sales use relative PV changes on remaining assumed cash flows applied to reported book. Portfolio accounting categories, actual encumbrance, bid-ask, and execution market depth are not recovered.", "Additional borrowing availability and its price are assumed. Unfunded withdrawal requests remain recorded deposits and explicit breaches; negative cash or balancing cash is not introduced.", "Existing funding is assumed to reprice immediately and remains outstanding throughout the 12-month ledger. No funding maturity rollover occurs within the horizon under the supported assumptions.", "Swaps use a dated monthly ACT365F Treasury single-curve proxy, not a market SOFR curve. First fixing is held; later coupons follow frozen shocked forwards. Bilateral collateralized-to-market assumptions differ from actual cleared settlement. No actual execution, legal netting, counterparty default or intramonth margin paths are modeled.", "Snapshot and curve are retrieved later vintages; observation date alignment is not a point-in-time historical backtest."]}

    result["policy_analysis"] = policy_analysis
    result["hedge_comparison"] = hedge_comparison
    result["policies"]["caveat"] = "Thirty joint funding/hedge policies are evaluated on the same baseline and seven named shocks. This is in-sample finite-grid selection, not independent validation or a global optimum. Policy EVE compares its own prefunded and hedged baseline, with the same upfront fee. Collateral and payment obligations add constraints without relaxing any existing limit."
    result["policies"]["constraints"].update({"unfunded_margin_allowed_usd": 0.0, "unsettled_payment_allowed_usd": 0.0})
    result["reverse_stress"]["reference_policy"] = "Unhedged, zero prefunding, borrow first; unchanged v1 reference."
    result["sensitivity_reference_policy"] = "Unhedged, zero prefunding, borrow first; no selected-policy feedback."
    result["limitations"].append("Received variation margin is segregated and unavailable to fund withdrawals. Unpaid obligations remain liabilities; unmet margin calls and payments are historical breaches even after recovery. Cash monitoring covers time zero and month ends, not intramonth liquidity.")
    if a.get("business_costs", {}).get("enabled"):
        result["policies"]["objective"] += " The extended case also deducts the disclosed operating-expense and new credit-loss proxies."
        result["limitations"][5] = "The extended case deducts explicit operating-expense and new credit-loss proxies plus the swap transaction fee. Earnings exclude tax, noninterest revenue, other fees and OCI and are not forecast net income."
        result["limitations"].append("EVE remains a gross interest-rate cash-flow valuation before future operating costs and new credit losses. The earnings-only overlays are not calibrated lifetime credit or franchise cash flows, so they are not inserted into the EVE reconstruction; the two measures answer different questions.")
    if a.get("asset_segments", {}).get("enabled"):
        result["asset_model"] = "sourced_bands_with_explicit_assumptions"
        result["policies"]["constraints"]["maximum_securities_sale_book_usd"] = baseline["securities_sale_cap_usd"]
        result["reverse_stress"]["reference_policy"] = "Unhedged, zero prefunding, borrow first; extended asset bands and configured business costs."
        result["limitations"][0] = "Public bank balances and reported maturity-or-repricing bands with assumed cash-flow reconstruction, not Regions Bank's internal ALM model, forecast, disclosed stress result or regulatory compliance assessment."
        result["limitations"][6] = "Securities sales use remaining per-band shocked/base PV ratios applied to book. Source-reported aggregate pledges are allocated proportionally, equity securities are excluded from sales, and actual security-level encumbrance, execution spreads and market depth are unknown."
        result["limitations"].extend(a["asset_segments"]["limitations"])
    return result
