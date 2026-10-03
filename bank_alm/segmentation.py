"""Source-anchored asset bands with explicit fixed/reset/contractual assumptions.

Reporting bands mix maturity and repricing; floating principal is never repaid
merely because its reported repricing interval expires. No network or file I/O.
"""
from __future__ import annotations

import copy
import math

from .numerics import present_value

BASE = {"shape": "parallel", "shock_bps": 0.0}


def build_asset_segments(profile: dict, assumptions: dict, overrides: dict | None = None) -> dict:
    config = {"representative_months": {"3LES": 2, "3T12": 8, "1T3": 24, "3T5": 48, "5T15": 120, "OV15": 240, "SCO3YLES": 24, "SCOOV3Y": 60}, "fixed_fractions": {"other_debt": 0.9, "mortgage_pass_through": 0.9, "residential_first_lien": 0.8, "other_loans": 0.2, "other_mbs": 1.0}, "floating_contractual_months": 60, "minimum_post_reset_life_months": 12, "other_mbs_coupon_treatment": "fixed-rate proxy", "equity_residual_valuation": "static book; zero coupon; excluded from forced sales", "nonaccrual_valuation": "static proportional net book; zero coupon or principal collection; not a recovery forecast", "encumbrance_allocation": "Pro rata original pledged fraction across securities; pledged inventory does not become sellable before its modeled maturity."}
    config["pledged_principal_treatment"] = "release_on_payment"
    for key, value in (overrides or {}).items():
        if key not in config:
            raise ValueError("Unknown segmentation assumption: " + key)
        if isinstance(value, dict) and isinstance(config[key], dict):
            config[key].update(value)
        else:
            config[key] = value
    totals = profile["totals_usd"]
    loan_scale = totals["net_loans"] / totals["gross_loans"]
    pledged_fraction = min(1.0, totals["pledged_securities"] / totals["securities_book"])
    segments = []
    for band in profile["bands"]:
        asset_class = band["asset_class"]
        band_key = band["id"] if band["group"] == "other_mbs" else band["id"][4:]
        months = config["representative_months"][band_key]
        fixed_fraction = config["fixed_fractions"][band["group"]]
        if not isinstance(months, int) or not 1 <= months <= 600 or not 0 <= fixed_fraction <= 1:
            raise ValueError("Invalid within-band assumption")
        if not band["lower_years_exclusive"] < months / 12 or (band["upper_years_inclusive"] is not None and months / 12 > band["upper_years_inclusive"]):
            raise ValueError("Representative horizon is outside the reported band: " + band["id"])
        for rate_type, share in (("fixed", fixed_fraction), ("floating", 1 - fixed_fraction)):
            if share == 0:
                continue
            balance = band["reported_balance_usd"] * share * (loan_scale if asset_class == "loans" else 1.0)
            maturity = months if rate_type == "fixed" else max(config["floating_contractual_months"], months + config["minimum_post_reset_life_months"])
            coupon = assumptions["securities"]["coupon"] if asset_class == "securities" else assumptions["loans"]["fixed_coupon" if rate_type == "fixed" else "floating_coupon"]
            segments.append({"id": band["id"] + "_" + rate_type, "source_field": band["source_field"], "group": band["group"], "asset_class": asset_class, "rate_type": rate_type, "source_band_balance_usd": band["reported_balance_usd"], "assumed_share": share, "opening_book_usd": balance, "coupon": coupon, "maturity_months": maturity, "reset_month": months if rate_type == "floating" else None, "amortization": "level_principal" if asset_class == "loans" or band["group"] == "mortgage_pass_through" else "bullet", "discount_spread": assumptions["loans"]["discount_spread"] if asset_class == "loans" else 0.0, "pledged_fraction": pledged_fraction if asset_class == "securities" else 0.0, "sale_eligible": asset_class == "securities", "source_basis": band["basis"], "prepayment_eligible": asset_class == "loans" or band["group"] == "mortgage_pass_through"})
    for name, asset_class, amount in (("equity_securities_residual", "securities", totals["equity_securities_residual"]), ("nonaccrual_debt_securities", "securities", totals["nonaccrual_debt_securities"]), ("nonaccrual_loans", "loans", totals["nonaccrual_loans"] * loan_scale)):
        if amount:
            segments.append({"id": name, "source_field": "SCEQNFT" if name == "equity_securities_residual" else "NASCDEBT" if asset_class == "securities" else "NALNLS", "group": name, "asset_class": asset_class, "rate_type": "static", "source_band_balance_usd": amount / loan_scale if asset_class == "loans" else amount, "assumed_share": 1.0, "opening_book_usd": amount, "coupon": 0.0, "maturity_months": None, "reset_month": None, "amortization": "static", "discount_spread": 0.0, "pledged_fraction": pledged_fraction if asset_class == "securities" else 0.0, "sale_eligible": False, "source_basis": "explicit schedule exclusion; separate residual", "prepayment_eligible": False})
    result = {"enabled": True, "schema_version": "bank-alm-asset-segments-v1", "certificate": profile["certificate"], "as_of": profile["as_of"], "segments": segments, "assumptions": config, "reported_totals_usd": copy.deepcopy(totals), "net_to_gross_loan_ratio": loan_scale, "source_records": copy.deepcopy(profile["source_records"]), "maximum_unpledged_sale_book_usd": math.fsum(s["opening_book_usd"] * (1 - s["pledged_fraction"]) for s in segments if s["sale_eligible"]), "limitations": copy.deepcopy(profile["limitations"])}
    result["permitted_security_sale_book_usd"] = min(result["maximum_unpledged_sale_book_usd"], totals["securities_book"] * assumptions["securities"]["sale_cap_fraction"])
    result["source_bands"] = copy.deepcopy(profile["bands"])
    result["limitations"].append("Pledged security principal is released into free cash by default. The retain_cash_collateral challenge instead retains it as a separate non-interest-bearing pledged-cash asset throughout the horizon, with no assumed release or substitution. This changes liquidity and subsequent cash income, not the opening contractual EVE cash flows.")
    validate_segments(result, {"securities": totals["securities_book"], "loans": totals["net_loans"]})
    return result


def validate_segments(config: dict, balance: dict) -> None:
    if config.get("assumptions", {}).get("pledged_principal_treatment", "release_on_payment") not in ("release_on_payment", "retain_cash_collateral"):
        raise ValueError("Unknown pledged-principal treatment")
    segments = config["segments"]
    if not segments or len({s["id"] for s in segments}) != len(segments):
        raise ValueError("Asset segments must be nonempty and uniquely named")
    for asset_class in ("securities", "loans"):
        if abs(math.fsum(s["opening_book_usd"] for s in segments if s["asset_class"] == asset_class) - balance[asset_class]) > 1:
            raise ValueError("Segment book does not reconcile to " + asset_class)
    for s in segments:
        if not math.isfinite(s["opening_book_usd"]) or s["opening_book_usd"] < 0 or not 0 <= s["pledged_fraction"] <= 1:
            raise ValueError("Invalid segment book/encumbrance")
        if s["rate_type"] not in ("fixed", "floating", "static"):
            raise ValueError("Invalid rate type")
        if s["rate_type"] != "static" and (not isinstance(s["maturity_months"], int) or not 1 <= s["maturity_months"] <= 1200):
            raise ValueError("Invalid contractual segment maturity")
        if s["rate_type"] == "floating" and (not isinstance(s["reset_month"], int) or not 0 <= s["reset_month"] < s["maturity_months"]):
            raise ValueError("A floating reset must precede its separate principal maturity")
        if not math.isfinite(s["coupon"]) or not 0 <= s["coupon"] <= 1:
            raise ValueError("Invalid segment coupon")
        if s["asset_class"] not in ("securities", "loans") or s["amortization"] not in ("static", "bullet", "level_principal"):
            raise ValueError("Invalid asset class or amortization")
        if not isinstance(s["sale_eligible"], bool) or not isinstance(s["prepayment_eligible"], bool):
            raise ValueError("Segment eligibility flags must be boolean")
        if not math.isfinite(s["discount_spread"]) or not 0 <= s["discount_spread"] <= 1:
            raise ValueError("Invalid segment discount spread")
        if s["sale_eligible"] and (s["asset_class"] != "securities" or s["rate_type"] == "static"):
            raise ValueError("Only modeled debt securities are sale eligible")
    cap = config["permitted_security_sale_book_usd"]
    available = math.fsum(s["opening_book_usd"] * (1 - s["pledged_fraction"]) for s in segments if s["sale_eligible"])
    if not math.isfinite(cap) or not 0 <= cap <= available + 1:
        raise ValueError("Sale cap cannot exceed modeled unpledged debt inventory")


def initialize_state(config: dict) -> list[dict]:
    result = copy.deepcopy(config["segments"])
    for s in result:
        s.update({"book_usd": s["opening_book_usd"], "cumulative_principal_usd": 0.0, "cumulative_credit_loss_usd": 0.0, "cumulative_sale_book_usd": 0.0, "scheduled_principal_usd": s["opening_book_usd"] / s["maturity_months"] if s["maturity_months"] else 0.0})
        s["pledged_book_usd"] = s["opening_book_usd"] * s["pledged_fraction"]
    return result


def _coupon(s: dict, month: int, short_rate_change: float) -> float:
    if s["rate_type"] == "static":
        return 0.0
    change = short_rate_change if s["rate_type"] == "floating" and month > s["reset_month"] else 0.0
    return max(0.0, s["coupon"] + change)


def _principal(s: dict, balance: float, month: int, cpr: float) -> float:
    if s["rate_type"] == "static":
        return 0.0
    if month >= s["maturity_months"]:
        return balance
    if s["amortization"] == "bullet":
        return 0.0
    scheduled = min(balance, s.get("scheduled_principal_usd", s["opening_book_usd"] / s["maturity_months"]))
    smm = 1.0 - (1.0 - cpr) ** (1.0 / 12.0)
    return scheduled + (balance - scheduled) * smm


def _cashflows(s: dict, balance: float, start_month: int, cpr: float,
               short_rate_change: float) -> list[tuple[float, float]]:
    flows = []
    s = s.copy()
    current_book = s.get("book_usd", s["opening_book_usd"])
    s["scheduled_principal_usd"] = s.get("scheduled_principal_usd", s["opening_book_usd"] / s["maturity_months"]) * balance / current_book if current_book else 0.0
    for month in range(start_month + 1, s["maturity_months"] + 1):
        income = balance * _coupon(s, month, short_rate_change) / 12
        principal = _principal(s, balance, month, cpr)
        flows.append(((month - start_month) / 12, income + principal))
        balance = max(0.0, balance - principal)
    return flows


def asset_values(config: dict, curve: dict, scenario: dict, cpr: float,
                 short_rate_change: float) -> dict:
    parts = []
    for s in config["segments"]:
        value = s["opening_book_usd"] if s["rate_type"] == "static" else present_value(_cashflows(s, s["opening_book_usd"], 0, cpr if s.get("prepayment_eligible") else 0, short_rate_change), curve, scenario, s["discount_spread"])
        parts.append({"segment_id": s["id"], "asset_class": s["asset_class"], "present_value_usd": value})
    return {"securities_usd": math.fsum(p["present_value_usd"] for p in parts if p["asset_class"] == "securities"), "loans_usd": math.fsum(p["present_value_usd"] for p in parts if p["asset_class"] == "loans"), "segments": parts}


def advance_assets(state: list[dict], month: int, cpr: float, short_rate_change: float,
                   credit_loss_fraction: float = 0.0) -> dict:
    rows = []
    for s in state:
        start = s["book_usd"]
        income = start * _coupon(s, month, short_rate_change) / 12
        loss = min(start, start * credit_loss_fraction) if s["asset_class"] == "loans" else 0.0
        remaining = start - loss
        principal = _principal(s, remaining, month, cpr if s.get("prepayment_eligible") else 0.0)
        pledged_principal = principal * s["pledged_book_usd"] / start if start else 0.0
        s["pledged_book_usd"] *= (remaining - principal) / start if start else 0.0
        s["book_usd"] = max(0.0, remaining - principal)
        s["cumulative_credit_loss_usd"] += loss
        s["cumulative_principal_usd"] += principal
        rows.append({"segment_id": s["id"], "asset_class": s["asset_class"], "opening_book_usd": start, "interest_income_usd": income, "credit_loss_usd": loss, "principal_usd": principal, "pledged_principal_usd": pledged_principal, "ending_book_before_sale_usd": s["book_usd"], "rate_type": s["rate_type"], "contractual_maturity_month": s["maturity_months"], "repricing_month": s["reset_month"]})
    return {"securities_income_usd": math.fsum(r["interest_income_usd"] for r in rows if r["asset_class"] == "securities"), "loans_income_usd": math.fsum(r["interest_income_usd"] for r in rows if r["asset_class"] == "loans"), "securities_principal_usd": math.fsum(r["principal_usd"] for r in rows if r["asset_class"] == "securities"), "pledged_securities_principal_usd": math.fsum(r["pledged_principal_usd"] for r in rows if r["asset_class"] == "securities"), "loans_principal_usd": math.fsum(r["principal_usd"] for r in rows if r["asset_class"] == "loans"), "credit_loss_usd": math.fsum(r["credit_loss_usd"] for r in rows), "rows": rows}


def sell_securities(state: list[dict], needed_cash: float, curve: dict, scenario: dict,
                    month: int, book_cap_remaining: float, short_rate_change: float, cpr: float = 0.0, base_cpr: float = 0.0) -> dict:
    offers = []
    if needed_cash > 0 and book_cap_remaining > 0:
        for s in state:
            if not s["sale_eligible"] or s["book_usd"] <= 0:
                continue
            available = max(0.0, s["book_usd"] - s["pledged_book_usd"])
            if available <= 0:
                continue
            shocked = present_value(_cashflows(s, 1.0, month, cpr if s.get("prepayment_eligible") else 0.0, short_rate_change), curve, scenario)
            unshocked = present_value(_cashflows(s, 1.0, month, base_cpr if s.get("prepayment_eligible") else 0.0, 0.0), curve, BASE)
            if not math.isfinite(shocked) or unshocked <= 0 or shocked <= 0:
                raise ValueError("Invalid sale pricing for " + s["id"])
            offers.append((s, available, shocked / unshocked))
    available_book = math.fsum(amount for _, amount, _ in offers)
    available_cash = math.fsum(amount * price for _, amount, price in offers)
    fraction = min(1.0, needed_cash / available_cash, book_cap_remaining / available_book) if offers else 0.0
    rows = []
    for s, amount, price in offers:
        book = amount * fraction
        proceeds = book * price
        if s["book_usd"]:
            s["scheduled_principal_usd"] *= 1 - book / s["book_usd"]
        s["book_usd"] -= book
        s["cumulative_sale_book_usd"] += book
        rows.append({"segment_id": s["id"], "book_sold_usd": book, "proceeds_usd": proceeds, "price_ratio": price, "ending_book_usd": s["book_usd"]})
    book = math.fsum(r["book_sold_usd"] for r in rows)
    proceeds = math.fsum(r["proceeds_usd"] for r in rows)
    return {"book_sold_usd": book, "proceeds_usd": proceeds, "sale_pnl_usd": proceeds - book, "weighted_price_ratio": proceeds / book if book else 1.0, "rows": rows}


def inventory_snapshot(state: list[dict]) -> list[dict]:
    return [{"segment_id": s["id"], "asset_class": s["asset_class"], "sale_eligible": s["sale_eligible"], "initial_book_usd": s["opening_book_usd"], "ending_book_usd": s["book_usd"], "pledged_book_usd": s["pledged_book_usd"], "cumulative_principal_usd": s["cumulative_principal_usd"], "cumulative_credit_loss_usd": s["cumulative_credit_loss_usd"], "cumulative_sale_book_usd": s["cumulative_sale_book_usd"], "conservation_residual_usd": s["opening_book_usd"] - s["book_usd"] - s["cumulative_principal_usd"] - s["cumulative_credit_loss_usd"] - s["cumulative_sale_book_usd"]} for s in state]
