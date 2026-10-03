"""Dated payer-fixed swap research proxy with deterministic curve roll-down.

This is a Treasury single-curve, monthly ACT/365F model. It is not a SOFR
market-price implementation. It returns trade cash flows and signed values;
the caller separately accounts for collateral, financing and unpaid cash.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime
import math

from .numerics import interpolate_zero, shock_bps

BASE = {"shape": "parallel", "shock_bps": 0.0}


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite real number")
    return float(value)


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1200:
        raise ValueError(f"{name} must be a positive integer no greater than 1200")
    return value


def _date(value: str | date) -> date:
    if isinstance(value, datetime):
        raise ValueError("valuation_date must be a date without a time")
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError("valuation_date must be a date or ISO YYYY-MM-DD string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("valuation_date must be a valid ISO YYYY-MM-DD date") from error
    if parsed.isoformat() != value:
        raise ValueError("valuation_date must use ISO YYYY-MM-DD format")
    return parsed


def schedule(valuation_date: str | date, tenor_months: int = 60) -> list[dict]:
    """Monthly unadjusted dates, original-date anchoring and end-of-month rule.

    If the initial date is month-end, every payment is month-end. Otherwise
    retain its day when possible and clip only that month's short date. There
    is no holiday or business-day adjustment and no stub period.
    """
    start = _date(valuation_date)
    months = _positive_integer(tenor_months, "tenor_months")
    is_eom = start.day == calendar.monthrange(start.year, start.month)[1]
    previous = start
    rows = []
    for month in range(1, months + 1):
        target = start.year * 12 + start.month - 1 + month
        year, month_index = divmod(target, 12)
        if year > date.max.year:
            raise ValueError("Swap maturity exceeds supported calendar dates")
        last_day = calendar.monthrange(year, month_index + 1)[1]
        payment = date(year, month_index + 1, last_day if is_eom else min(start.day, last_day))
        days = (payment - previous).days
        rows.append({
            "month": month,
            "accrual_start_date": previous.isoformat(),
            "payment_date": payment.isoformat(),
            "accrual_days": days,
            "accrual_fraction": days / 365.0,
            "accrual_start_time_years": (previous - start).days / 365.0,
            "payment_time_years": (payment - start).days / 365.0,
        })
        previous = payment
    return rows


def _validate_curve(curve: dict, scenario: dict | None) -> dict:
    if not isinstance(curve, dict):
        raise ValueError("curve must contain tenor and zero-rate arrays")
    tenors, rates = curve.get("tenors_years"), curve.get("zero_rates")
    if not isinstance(tenors, (list, tuple)) or not isinstance(rates, (list, tuple)) or len(tenors) != len(rates) or len(tenors) < 2:
        raise ValueError("Curve tenor and zero-rate arrays must have equal length >=2")
    numbers = [_finite_number(t, "curve tenor") for t in tenors]
    if any(t <= 0 for t in numbers) or any(x >= y for x, y in zip(numbers, numbers[1:])):
        raise ValueError("Curve tenors must be positive and strictly increasing")
    for rate in rates:
        _finite_number(rate, "curve zero rate")
    selected = BASE if scenario is None else scenario
    if not isinstance(selected, dict):
        raise ValueError("scenario must be a dictionary or None")
    _finite_number(selected.get("shock_bps", 0.0), "scenario shock_bps")
    shock_bps(1.0, selected)  # Validate the selected shock shape as well.
    return selected


def _df(curve: dict, scenario: dict, years: float) -> float:
    if years == 0:
        return 1.0
    zero = interpolate_zero(years, curve["tenors_years"], curve["zero_rates"])
    exponent = -years * (zero + shock_bps(years, scenario) / 10000.0)
    try:
        value = math.exp(exponent)
    except OverflowError as error:
        raise ValueError("Curve produces an overflowing discount factor") from error
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Curve must produce finite positive discount factors")
    return value


def discount_factor(curve: dict, scenario: dict | None, years: float) -> float:
    """Time-zero discount factor D_s(t), using continuous zero rates."""
    selected = _validate_curve(curve, scenario)
    years = _finite_number(years, "years")
    if years < 0:
        raise ValueError("Discount time cannot be negative")
    return _df(curve, selected, years)


def par_swap_rate(curve: dict, valuation_date: str | date, tenor_months: int = 60) -> float:
    """Base-curve par coupon: (1 - D(T)) / sum(alpha_i * D(t_i))."""
    _validate_curve(curve, BASE)
    rows = schedule(valuation_date, tenor_months)
    annuity = math.fsum(row["accrual_fraction"] * _df(curve, BASE, row["payment_time_years"]) for row in rows)
    if annuity <= 0 or not math.isfinite(annuity):
        raise ValueError("Fixed-leg annuity must be finite and positive")
    return (1.0 - _df(curve, BASE, rows[-1]["payment_time_years"])) / annuity


def projected_cashflows(curve: dict, scenario: dict | None, valuation_date: str | date,
                        notional: float, tenor_months: int = 60,
                        fixed_rate: float | None = None,
                        first_floating_fixing: float | None = None) -> list[dict]:
    """Project each gross leg and net payer-fixed coupon, with no principal.

    Defaults calibrate a trade entered on the base curve immediately before
    the scenario. The first floating coupon is locked from that base curve.
    Explicit coupon/fixing overrides support independent reconciliation.
    """
    selected = _validate_curve(curve, scenario)
    notional = _finite_number(notional, "notional")
    if notional < 0:
        raise ValueError("Swap notional cannot be negative")
    rows = schedule(valuation_date, tenor_months)
    coupon = par_swap_rate(curve, valuation_date, tenor_months) if fixed_rate is None else _finite_number(fixed_rate, "fixed_rate")
    first = rows[0]
    fixing = ((1.0 / _df(curve, BASE, first["payment_time_years"]) - 1.0) / first["accrual_fraction"]
              if first_floating_fixing is None else _finite_number(first_floating_fixing, "first_floating_fixing"))
    output = []
    for row in rows:
        start_df = _df(curve, selected, row["accrual_start_time_years"])
        end_df = _df(curve, selected, row["payment_time_years"])
        curve_forward = (start_df / end_df - 1.0) / row["accrual_fraction"]
        floating_rate = fixing if row["month"] == 1 else curve_forward
        fixed = notional * coupon * row["accrual_fraction"]
        floating = notional * floating_rate * row["accrual_fraction"]
        net = floating - fixed
        if not all(math.isfinite(value) for value in (curve_forward, floating_rate, fixed, floating, net)):
            raise ValueError("Swap inputs produce nonfinite cash flows")
        output.append({**row, "fixed_rate": coupon, "floating_rate": floating_rate,
                       "first_fixing_locked": row["month"] == 1,
                       "fixed_payment_usd": fixed, "floating_receipt_usd": floating,
                       "net_coupon_usd": net, "principal_exchange_usd": 0.0,
                       "collateral_rate": curve_forward,
                       "discount_factor_from_open": end_df})
    return output


def value_remaining(cashflows: list[dict], curve: dict, scenario: dict | None,
                    elapsed_years: float = 0.0) -> float:
    """Ex-coupon value after time u, discounted with D_s(t) / D_s(u).

    Rows on the valuation time have already paid. The caller must supply the
    original projected cash flows; re-fixing them on a fresh tenor curve would
    create a different path and violate the conditional-value rollforward.
    """
    selected = _validate_curve(curve, scenario)
    elapsed = _finite_number(elapsed_years, "elapsed_years")
    if elapsed < 0:
        raise ValueError("Valuation time cannot be negative")
    origin_df = _df(curve, selected, elapsed)
    terms = []
    for row in cashflows:
        time = _finite_number(row["payment_time_years"], "cash-flow payment time")
        amount = _finite_number(row["net_coupon_usd"], "net coupon")
        if time <= 0:
            raise ValueError("Cash-flow payment times must be positive")
        if time > elapsed:
            terms.append(amount * _df(curve, selected, time) / origin_df)
    result = math.fsum(terms)
    if not math.isfinite(result):
        raise ValueError("Remaining swap value is nonfinite")
    return result


def swap_path(curve: dict, scenario: dict | None, valuation_date: str | date,
              notional: float, tenor_months: int = 60, horizon_months: int = 12) -> dict:
    """Return signed swap marks, coupons and separate horizon liquidation.

    At the final modeled payment the coupon is paid first; remaining ex-coupon
    value is then exchanged as closeout cash. swap_value_usd is that value
    BEFORE closeout; ending_swap_value_usd becomes zero after closeout.
    Positive coupons and marks belong to the payer-fixed bank.
    """
    horizon = _positive_integer(horizon_months, "horizon_months")
    tenor = _positive_integer(tenor_months, "tenor_months")
    if horizon > tenor:
        raise ValueError("Swap horizon cannot exceed contractual tenor")
    selected = _validate_curve(curve, scenario)
    flows = projected_cashflows(curve, selected, valuation_date, notional, tenor)
    base_flows = projected_cashflows(curve, BASE, valuation_date, notional, tenor)
    fixed_pv = math.fsum(row["fixed_payment_usd"] * row["discount_factor_from_open"] for row in flows)
    floating_pv = math.fsum(row["floating_receipt_usd"] * row["discount_factor_from_open"] for row in flows)
    opening = math.fsum(row["net_coupon_usd"] * row["discount_factor_from_open"] for row in flows)
    inception = math.fsum(row["net_coupon_usd"] * row["discount_factor_from_open"] for row in base_flows)
    # Cumulative suffix values preserve original time-zero scenario projection.
    discounted_future = [0.0] * (tenor + 1)
    for index in range(tenor - 1, -1, -1):
        discounted_future[index] = math.fsum((discounted_future[index + 1], flows[index]["net_coupon_usd"] * flows[index]["discount_factor_from_open"]))
    monthly = []
    previous_value = opening
    previous_df = 1.0
    for index in range(horizon):
        row = flows[index]
        remaining = discounted_future[index + 1] / row["discount_factor_from_open"]
        final = index == horizon - 1
        # D(u_previous)/D(u_current) rolls an ex-coupon value to next payment.
        residual = previous_value * previous_df / row["discount_factor_from_open"] - row["net_coupon_usd"] - remaining
        monthly.append({**row, "swap_value_usd": remaining,
                        "closeout_cashflow_usd": remaining if final else 0.0,
                        "ending_swap_value_usd": 0.0 if final else remaining,
                        "coupon_pv_rollforward_residual_usd": residual})
        previous_value = remaining
        previous_df = row["discount_factor_from_open"]
    start = _date(valuation_date)
    return {
        "terms": {"trade_date": start.isoformat(), "maturity_date": flows[-1]["payment_date"],
                  "notional_usd": float(notional), "tenor_months": tenor, "horizon_months": horizon,
                  "fixed_rate": flows[0]["fixed_rate"], "first_floating_fixing": flows[0]["floating_rate"],
                  "direction": "pay_fixed_receive_floating", "day_count": "ACT/365F",
                  "payment_frequency": "monthly", "business_day_adjustment": "none",
                  "end_of_month_rule": start.day == calendar.monthrange(start.year, start.month)[1],
                  "curve_convention": "Treasury fitted single-curve research proxy; deterministic D_s(t)/D_s(u) roll",
                  "settlement_convention": "Bilateral collateralized-to-market proxy; collateral is accounted for separately"},
        "inception_value_usd": inception,
        "opening_value_usd": opening,
        "opening_fixed_leg_pv_usd": fixed_pv,
        "opening_floating_leg_pv_usd": floating_pv,
        "terminal_closeout_usd": monthly[-1]["closeout_cashflow_usd"],
        "monthly": monthly,
    }
