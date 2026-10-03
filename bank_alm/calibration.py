"""Deterministic, bounded deposit-cost calibration with chronological holdout.

The target is a domestic interest-bearing deposit cost proxy. Realized policy
rates make the holdout a conditional hindcast, not an ex-ante forecast. Only
training rows estimate coefficients; no missing rate or bank data is filled.
"""
from __future__ import annotations

from datetime import date
import itertools
import math

TRAIN_END = "2023-12-31"
TEST_START = "2024-01-01"


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite numeric data")
    return float(value)


def _quarter_shift(quarter_end: str, offset: int) -> str:
    parsed = date.fromisoformat(quarter_end)
    index = parsed.year * 4 + (parsed.month - 1) // 3 + offset
    year, q = divmod(index, 4)
    return f"{year:04d}-{(q + 1) * 3:02d}-{30 if q in (1, 2) else 31:02d}"


def _solve(matrix: list[list[float]], target: list[float]) -> list[float] | None:
    """Pivoted elimination; singular active sets are skipped, never regularized."""
    n = len(target)
    if n == 0:
        return []
    rows = [list(row) + [value] for row, value in zip(matrix, target)]
    scale = max((abs(v) for row in matrix for v in row), default=0.0)
    for col in range(n):
        pivot = max(range(col, n), key=lambda i: abs(rows[i][col]))
        if abs(rows[pivot][col]) <= max(1e-14, scale * 1e-12):
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        divisor = rows[col][col]
        rows[col] = [v / divisor for v in rows[col]]
        for i in range(n):
            if i == col:
                continue
            factor = rows[i][col]
            rows[i] = [x - factor * y for x, y in zip(rows[i], rows[col])]
    return [rows[i][-1] for i in range(n)]


def _rank(matrix: list[list[float]]) -> int:
    rows = [row[:] for row in matrix]
    if not rows:
        return 0
    rank = 0
    tolerance = max(1.0, max(abs(v) for row in rows for v in row)) * 1e-10
    for col in range(len(rows[0])):
        pivot = max(range(rank, len(rows)), key=lambda i: abs(rows[i][col]), default=rank)
        if rank == len(rows) or abs(rows[pivot][col]) <= tolerance:
            continue
        rows[rank], rows[pivot] = rows[pivot], rows[rank]
        divisor = rows[rank][col]
        rows[rank] = [v / divisor for v in rows[rank]]
        for i in range(rank + 1, len(rows)):
            factor = rows[i][col]
            rows[i] = [x - factor * y for x, y in zip(rows[i], rows[rank])]
        rank += 1
    return rank


def bounded_fit(features: list[list[float]], targets: list[float]) -> dict:
    """OLS over nonnegative intercept/slopes with sum(slopes) <= 1.

    Inputs and output intercept are percentage points. All possible zero-bound
    active sets and the total-beta boundary are enumerated. No optimizer,
    random seed, ridge penalty or holdout data enters this calculation.
    """
    if not features or len(features) != len(targets):
        raise ValueError("Features and targets must have matching nonempty rows")
    width = len(features[0])
    if width < 2 or any(len(row) != width for row in features):
        raise ValueError("Each design row must contain an intercept and equal feature count")
    for row in features:
        if row[0] != 1.0:
            raise ValueError("First design column must be the intercept constant")
        for value in row:
            _number(value, "design value")
    targets = [_number(value, "target") for value in targets]
    best = None
    gram = [[math.fsum(row[i] * row[j] for row in features) for j in range(width)] for i in range(width)]
    rhs = [math.fsum(row[i] * y for row, y in zip(features, targets)) for i in range(width)]
    for mask in range(1 << width):
        free = [i for i in range(width) if mask & (1 << i)]
        for sum_bound in (False, True):
            if sum_bound and not any(i > 0 for i in free):
                continue
            mat = [[gram[i][j] for j in free] for i in free]
            vec = [rhs[i] for i in free]
            if sum_bound:
                constraint = [float(i > 0) for i in free]
                mat = [row + [v] for row, v in zip(mat, constraint)] + [constraint + [0.0]]
                vec += [1.0]
            solution = _solve(mat, vec)
            if solution is None:
                continue
            values = [0.0] * width
            for i, value in zip(free, solution):
                values[i] = value
            if any(v < -1e-9 for v in values) or sum(values[1:]) > 1 + 1e-9:
                continue
            values = [max(0.0, v) for v in values]
            sse = math.fsum((y - math.fsum(x * b for x, b in zip(row, values))) ** 2 for row, y in zip(features, targets))
            # Stable tie-break prefers the earlier enumerated simpler active set.
            if best is None or sse < best[0] - 1e-13:
                best = (sse, values)
    if best is None:
        raise ValueError("No feasible bounded regression solution")
    coefficients = best[1]
    return {"intercept_pct": coefficients[0], "lag_betas": coefficients[1:],
            "total_beta": sum(coefficients[1:]), "sse_pct_squared": best[0],
            "design_rank": _rank(features), "design_columns": width,
            "active_bounds": [f"coefficient_{i}_zero" for i, value in enumerate(coefficients) if value <= 1e-9]
            + (["total_beta_one"] if abs(sum(coefficients[1:]) - 1) <= 1e-9 else [])}


def metrics(actual: list[float], predicted: list[float]) -> dict:
    """Rate inputs are decimals; errors are returned in basis points."""
    if not actual or len(actual) != len(predicted):
        raise ValueError("Metrics need equal nonempty arrays")
    errors = [(p - y) * 10000 for y, p in zip(actual, predicted)]
    if not all(math.isfinite(v) for v in errors):
        raise ValueError("Metrics contain nonfinite errors")
    return {"count": len(errors), "mae_bps": math.fsum(abs(v) for v in errors) / len(errors),
            "rmse_bps": math.sqrt(math.fsum(v * v for v in errors) / len(errors)),
            "mean_error_bps": math.fsum(errors) / len(errors), "maximum_absolute_error_bps": max(abs(v) for v in errors)}


def _correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    dx, dy = [x - mx for x in xs], [y - my for y in ys]
    denominator = math.sqrt(sum(x * x for x in dx) * sum(y * y for y in dy))
    return None if denominator == 0 else sum(x * y for x, y in zip(dx, dy)) / denominator


def calibrate(history: dict) -> dict:
    """Train through 2023 and report untouched 2024–25 conditional outcomes."""
    rows = history.get("quarters", [])
    if not rows or len({row["quarter_end"] for row in rows}) != len(rows):
        raise ValueError("Quarter history must be nonempty and uniquely dated")
    if [r["quarter_end"] for r in rows] != sorted(r["quarter_end"] for r in rows):
        raise ValueError("Quarter history must be in chronological order")
    policy = history["policy_quarter_means"]
    enriched = []
    previous = None
    for row in rows:
        quarter = row["quarter_end"]
        if _quarter_shift(quarter, 0) != quarter:
            raise ValueError("Bank observations must be calendar quarter ends")
        if previous and _quarter_shift(previous, 1) != quarter:
            raise ValueError("Quarter history has a gap; no future fill is allowed")
        target = _number(row["deposit_cost_annualized_proxy"], "deposit cost proxy")
        if target < 0:
            raise ValueError("Deposit cost target cannot be negative")
        feature_dates = [_quarter_shift(quarter, -lag) for lag in range(3)]
        if any(q not in policy for q in feature_dates):
            raise ValueError(f"Missing policy-rate period for {quarter}; no fill is allowed")
        rates = [_number(policy[q]["mean_rate_decimal"], "policy rate") for q in feature_dates]
        enriched.append({"quarter_end": quarter, "target": target, "rates": rates,
                         "feature_dates": feature_dates, "x": [1.0] + [v * 100 for v in rates]})
        previous = quarter
    train = [r for r in enriched if r["quarter_end"] <= TRAIN_END]
    test = [r for r in enriched if TEST_START <= r["quarter_end"] <= "2025-12-31"]
    if len(train) < 16 or len(test) != 8:
        raise ValueError("Calibration needs >=16 training quarters and all eight 2024–25 holdout quarters")
    fitted = bounded_fit([r["x"] for r in train], [r["target"] * 100 for r in train])
    static = bounded_fit([r["x"][:2] for r in train], [r["target"] * 100 for r in train])
    constant = sum(r["target"] for r in train) / len(train)
    last_target, last_rate = train[-1]["target"], train[-1]["rates"][0]

    def predict(row: dict, model: dict) -> float:
        return (model["intercept_pct"] + sum(beta * value * 100 for beta, value in zip(model["lag_betas"], row["rates"]))) / 100

    predictions = []
    for row in train + test:
        predictions.append({"quarter_end": row["quarter_end"], "sample": "train" if row["quarter_end"] <= TRAIN_END else "holdout",
                            "actual_deposit_cost": row["target"], "lagged_model_prediction": predict(row, fitted),
                            "static_model_prediction": predict(row, static), "train_mean_prediction": constant,
                            "train_end_persistence_prediction": last_target,
                            "fixed_0_5_beta_prediction": max(0.0, last_target + 0.5 * (row["rates"][0] - last_rate)),
                            "policy_rates_decimal": row["rates"], "feature_quarter_ends": row["feature_dates"],
                            "publication_date": None, "availability_status": "Unknown exact filing/publication date; later retrieved vintage"})
    scored = {}
    for key in ("lagged_model", "static_model", "train_mean", "train_end_persistence", "fixed_0_5_beta"):
        scored[key] = {}
        for sample in ("train", "holdout"):
            values = [r for r in predictions if r["sample"] == sample]
            scored[key][sample] = metrics([r["actual_deposit_cost"] for r in values], [r[key + "_prediction"] for r in values])
    expanding = []
    for year in range(2018, 2024):
        subset = [r for r in train if r["quarter_end"] <= f"{year}-12-31"]
        if len(subset) >= 16:
            fit = bounded_fit([r["x"] for r in subset], [r["target"] * 100 for r in subset])
            expanding.append({"training_end": subset[-1]["quarter_end"], "training_quarters": len(subset), "total_beta": fit["total_beta"], "lag_betas": fit["lag_betas"], "active_bounds": fit["active_bounds"]})
    residuals = [r["target"] - predict(r, fitted) for r in train]
    correlations = [{"lags": [i, j], "correlation": _correlation([r["rates"][i] for r in train], [r["rates"][j] for r in train])} for i, j in itertools.combinations(range(3), 2)]
    best_benchmark = min((key for key in scored if key != "lagged_model"), key=lambda key: scored[key]["holdout"]["rmse_bps"])
    beats = scored["lagged_model"]["holdout"]["rmse_bps"] < scored[best_benchmark]["holdout"]["rmse_bps"]
    warnings = [
        "Quarter-end domestic interest-bearing deposit averages approximate, and do not equal, reported daily or weekly RC-K averages.",
        "Holdout conditions on realized contemporaneous policy rates and later-revised bank data; this is not an ex-ante or point-in-time forecast.",
        "Aggregate deposit mix changes can move this beta even without customer-level repricing changes; deposit decay and retention are not identified.",
        "Nonnegative bounds and a total-beta cap are modeling constraints, not empirical findings. Individual lag coefficients can be weakly identified.",
        "Only eight holdout quarters and one bank are available in this split. Expanding-window estimates measure instability, not confidence-interval coverage.",
        "Benchmark rankings are reported after the fixed split; the lag specification and coefficient estimates never use holdout targets.",
    ]
    if fitted["design_rank"] < fitted["design_columns"]:
        warnings.append("Training design is rank deficient. A bounded numerical solution does not uniquely identify the lag coefficients.")
    if fitted["active_bounds"]:
        warnings.append("The fitted model lies on parameter bounds; ordinary unconstrained regression standard errors would be misleading.")
    if not beats:
        warnings.append("The lagged calibration does not beat every transparent benchmark on the holdout. Do not promote it to a validated forecasting model.")
    return {"schema_version": "bank-alm-deposit-calibration-v1", "bank_name": history["bank_name"], "certificate": history["certificate"],
            "target": "ACT/365F annualized domestic deposit interest expense / arithmetic mean of previous/current domestic interest-bearing deposit balances",
            "model_equation": "cost_t = nonnegative_intercept + beta_0*policy_t + beta_1*policy_(t-1) + beta_2*policy_(t-2); betas >= 0 and sum <= 1",
            "split": {"training_start": train[0]["quarter_end"], "training_end": train[-1]["quarter_end"], "holdout_start": test[0]["quarter_end"], "holdout_end": test[-1]["quarter_end"], "training_quarters": len(train), "holdout_quarters": len(test), "selection": "Fixed before fitting; no random split, future fill, holdout tuning or refit"},
            "coefficients": {"intercept_decimal": fitted["intercept_pct"] / 100, "lag_betas": fitted["lag_betas"], "total_beta": fitted["total_beta"]},
            "static_coefficients": {"intercept_decimal": static["intercept_pct"] / 100, "beta": static["total_beta"]},
            "metrics": scored, "predictions": predictions,
            "diagnostics": {"design_rank": fitted["design_rank"], "design_columns": fitted["design_columns"], "active_bounds": fitted["active_bounds"], "policy_lag_correlations": correlations, "training_residual_lag1_correlation": _correlation(residuals[1:], residuals[:-1]), "expanding_window_estimates": expanding, "holdout_best_benchmark": best_benchmark, "lagged_model_beats_all_benchmarks": beats, "statistical_confidence_interval": None, "confidence_interval_reason": "Serial dependence, proxy measurement error and active constraints; no coverage claim from naive OLS intervals"},
            "recommended_illustrative_beta": {"value": fitted["total_beta"], "status": "Descriptive sensitivity input only; not approved for automatic production use", "apply_to_engine": False, "holdout_support": beats,
                "rationale": f"Fixed 2024–25 holdout RMSE is {scored['lagged_model']['holdout']['rmse_bps']:.2f} bps for the lagged model versus {scored[best_benchmark]['holdout']['rmse_bps']:.2f} bps for {best_benchmark}. Retain the separately disclosed engine beta assumption; use this estimate only as a challenge sensitivity. Serial dependence, correlated policy lags and coefficient instability further limit inference.",
                "interpretation": "Total response to a persistent policy-rate change in the constrained aggregate cost model; not a measured customer beta"},
            "limitations": warnings}
