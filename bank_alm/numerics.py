"""Small deterministic cash-flow helpers. Rates are continuous zero yields."""
from __future__ import annotations

import math


def interpolate_zero(years: float, tenors: list[float], rates: list[float]) -> float:
    """Linear zero-rate interpolation with explicitly flat endpoints."""
    if years <= tenors[0]:
        return rates[0]
    for i in range(1, len(tenors)):
        if years <= tenors[i]:
            w = (years - tenors[i - 1]) / (tenors[i] - tenors[i - 1])
            return rates[i - 1] * (1.0 - w) + rates[i] * w
    return rates[-1]


def shock_bps(years: float, scenario: dict) -> float:
    """Research shock shapes; these are not prescribed supervisory scenarios."""
    shape = scenario.get("shape", "parallel")
    size = float(scenario.get("shock_bps", 0.0))
    decay = math.exp(-max(years, 0.0) / 4.0)
    if shape == "parallel":
        return size
    if shape == "steepener":
        return -65.0 * decay + 90.0 * (1.0 - decay)
    if shape == "flattener":
        return 80.0 * decay - 60.0 * (1.0 - decay)
    if shape == "short_up":
        return 250.0 * decay
    if shape == "short_down":
        return -250.0 * decay
    raise ValueError(f"Unknown research shock shape: {shape}")


def present_value(cashflows: list[tuple[float, float]], curve: dict,
                  scenario: dict | None = None, spread: float = 0.0) -> float:
    scenario = scenario or {"shape": "parallel", "shock_bps": 0.0}
    return math.fsum(amount * math.exp(-time * (
        interpolate_zero(time, curve["tenors_years"], curve["zero_rates"])
        + shock_bps(time, scenario) / 10000.0 + spread))
        for time, amount in cashflows)


def bullet_cashflows(principal: float, coupon: float, maturity_years: float,
                     coupon_after_reset: float | None = None,
                     reset_lag_months: int = 0) -> list[tuple[float, float]]:
    months = max(1, round(maturity_years * 12))
    result = []
    for month in range(1, months + 1):
        rate = coupon_after_reset if coupon_after_reset is not None and month > reset_lag_months else coupon
        amount = principal * rate / 12.0 + (principal if month == months else 0.0)
        result.append((month / 12.0, amount))
    return result


def amortizing_cashflows(principal: float, coupon: float, maturity_years: float,
                         annual_prepayment: float = 0.0,
                         coupon_after_reset: float | None = None,
                         reset_lag_months: int = 0) -> list[tuple[float, float]]:
    """Level scheduled principal plus optional CPR; final residual repaid."""
    months = max(1, round(maturity_years * 12))
    scheduled = principal / months
    smm = 1.0 - (1.0 - annual_prepayment) ** (1.0 / 12.0)
    remaining = principal
    result = []
    for month in range(1, months + 1):
        rate = coupon_after_reset if coupon_after_reset is not None and month > reset_lag_months else coupon
        repayment = min(remaining, scheduled)
        repayment += (remaining - repayment) * smm
        if month == months:
            repayment = remaining
        result.append((month / 12.0, remaining * rate / 12.0 + repayment))
        remaining = max(0.0, remaining - repayment)
    return result
