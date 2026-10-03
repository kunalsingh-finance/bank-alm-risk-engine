"""Source replay, accounting scope, chronological separation and fit identities."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from bank_alm.calibration import bounded_fit, calibrate, metrics
from scripts.fetch_history import (
    ROOT, build_history, derive_quarters, load_verified_calibration,
    load_verified_history, quarterly_policy_rates, verified_bytes,
)


class BoundedRegression(unittest.TestCase):
    def test_identifiable_exact_model_recovers_coefficients(self):
        design = [[1.0, float(i % 3), float((i // 3) % 3), float(i // 9)] for i in range(27)]
        truth = [0.12, 0.2, 0.3, 0.1]
        targets = [sum(x * b for x, b in zip(row, truth)) for row in design]
        fit = bounded_fit(design, targets)
        for actual, expected in zip([fit["intercept_pct"]] + fit["lag_betas"], truth):
            self.assertAlmostEqual(actual, expected, places=11)
        self.assertLess(fit["sse_pct_squared"], 1e-20)
        self.assertEqual(fit["design_rank"], 4)

    def test_binding_sum_constraint_has_analytical_solution(self):
        fit = bounded_fit([[1.0, x] for x in (0.0, 1.0, 2.0)], [0.0, 2.0, 4.0])
        self.assertAlmostEqual(fit["intercept_pct"], 1.0)
        self.assertAlmostEqual(fit["total_beta"], 1.0)
        self.assertAlmostEqual(fit["sse_pct_squared"], 2.0)
        self.assertIn("total_beta_one", fit["active_bounds"])

    def test_rank_deficiency_is_diagnosed_without_invented_identification(self):
        fit = bounded_fit([[1.0, x, x] for x in (0.0, 1.0, 2.0, 3.0)], [0.1, 0.5, 0.9, 1.3])
        self.assertEqual(fit["design_rank"], 2)
        self.assertEqual(fit["design_columns"], 3)
        self.assertAlmostEqual(fit["total_beta"], 0.4)
        self.assertLess(fit["sse_pct_squared"], 1e-20)
        self.assertTrue(all(v >= 0 for v in fit["lag_betas"]))

    def test_invalid_fit_data_and_metric_units(self):
        for features, targets in (([], []), ([[1, 2]], []), ([[2, 3]], [1]),
                                  ([[1, float("nan")]], [1]), ([[1, 2]], [True])):
            with self.subTest(features=features), self.assertRaises(ValueError):
                bounded_fit(features, targets)
        score = metrics([0.01, 0.03], [0.011, 0.029])
        self.assertAlmostEqual(score["rmse_bps"], 10.0)
        self.assertAlmostEqual(score["mean_error_bps"], 0.0)


class HistoricalCalibration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.history = load_verified_history()
        cls.result = load_verified_calibration()
        cls.sources = {s["source_id"]: s for s in cls.history["source_records"]}
        cls.bank_rows = [r["data"] for r in json.loads(verified_bytes(cls.sources["fdic_history"]))["data"]]

    def test_verified_replay_and_legal_entity(self):
        self.assertEqual(build_history(), self.history)
        self.assertEqual(calibrate(self.history), self.result)
        self.assertEqual((self.history["certificate"], self.history["rssd_id"]), (12368, 233031))
        self.assertEqual(self.history["quarter_count"], 44)
        self.assertEqual(self.history["reconciliations"]["ytd_quarter_comparisons"], 264)
        self.assertEqual(self.history["reconciliations"]["maximum_quarter_flow_residual_usd"], 0)
        self.assertTrue(all(r["publication_date"] is None and r["submission_datetime"] is None for r in self.history["quarters"]))

    def test_ytd_resets_and_scope_excludes_noninterest_and_foreign_deposits(self):
        rows = copy.deepcopy(self.bank_rows[:3])
        # An arbitrary prior December income cannot affect new-year first-quarter income.
        rows[0]["EDEPDOM"] = 987654321
        normal, _ = derive_quarters(rows, self.history["policy_quarter_means"])
        self.assertEqual(normal[0]["quarter_flows_usd"]["deposit_interest_expense_usd"], rows[1]["EDEPDOM"] * 1000)
        self.assertEqual(normal[1]["quarter_flows_usd"]["deposit_interest_expense_usd"], (rows[2]["EDEPDOM"] - rows[1]["EDEPDOM"]) * 1000)
        denominator = (rows[0]["DEPIDOM"] + rows[1]["DEPIDOM"]) * 1000 / 2
        self.assertEqual(normal[0]["average_domestic_interest_bearing_deposits_proxy_usd"], denominator)
        self.assertAlmostEqual(normal[0]["deposit_cost_annualized_proxy"], rows[1]["EDEPDOM"] * 1000 * (365 / 90) / denominator)
        for row in rows:
            row["DEPNI"] += 1_000_000_000
            row["DEP"] += 1_001_000_000
            row["DEPIFOR"] += 1_000_000
            row["DEPI"] += 1_000_000
        changed, _ = derive_quarters(rows, self.history["policy_quarter_means"])
        self.assertEqual([r["deposit_cost_annualized_proxy"] for r in normal], [r["deposit_cost_annualized_proxy"] for r in changed])

    def test_leap_quarter_uses_actual_days_and_annual_cost_denominator_is_explicit(self):
        leap = next(r for r in self.history["quarters"] if r["quarter_end"] == "2016-03-31")
        self.assertEqual(leap["days_in_quarter"], 91)
        self.assertEqual(leap["annualization_factor"], 365 / 91)
        annual = self.history["annual_2025_cost_and_credit_evidence"]
        expected = annual["flows_usd"]["noninterest_expense_usd"] / annual["time_weighted_quarter_endpoint_average_assets_proxy_usd"]
        self.assertEqual(annual["noninterest_expense_to_average_assets_proxy"], expected)
        self.assertIn("Unverified", annual["reported_average_assets_period_basis"])

    def test_bad_flow_identity_or_missing_bank_quarter_fails(self):
        rows = copy.deepcopy(self.bank_rows[:3])
        rows[2]["EDEPDOMQ"] += 1
        with self.assertRaisesRegex(ValueError, "reconciliation"):
            derive_quarters(rows, self.history["policy_quarter_means"])
        with self.assertRaisesRegex(ValueError, "Quarter gap"):
            derive_quarters([self.bank_rows[0], self.bank_rows[2]], self.history["policy_quarter_means"])

    def test_missing_daily_policy_observation_is_not_filled(self):
        raw = verified_bytes(self.sources["fred_dff"])
        lines = raw.splitlines(keepends=True)
        with self.assertRaisesRegex(ValueError, "no missing days"):
            quarterly_policy_rates(b"".join(lines[:3] + lines[4:]))
        periods = quarterly_policy_rates(raw)
        self.assertEqual(periods["2024-03-31"]["observations"], 91)
        self.assertEqual(len(periods), 48)

    def test_chronological_holdout_cannot_change_fit(self):
        changed = copy.deepcopy(self.history)
        for row in changed["quarters"]:
            if row["quarter_end"] >= "2024-01-01":
                row["deposit_cost_annualized_proxy"] += 0.25
        changed_result = calibrate(changed)
        self.assertEqual(self.result["coefficients"], changed_result["coefficients"])
        self.assertEqual(self.result["static_coefficients"], changed_result["static_coefficients"])
        self.assertEqual(self.result["diagnostics"]["expanding_window_estimates"], changed_result["diagnostics"]["expanding_window_estimates"])
        self.assertNotEqual(self.result["metrics"]["lagged_model"]["holdout"], changed_result["metrics"]["lagged_model"]["holdout"])
        self.assertEqual(self.result["split"]["training_quarters"], 36)
        self.assertEqual(self.result["split"]["holdout_quarters"], 8)
        for row in self.result["predictions"]:
            self.assertTrue(all(day <= row["quarter_end"] for day in row["feature_quarter_ends"]))

    def test_missing_lag_duplicate_quarter_or_negative_target_rejected(self):
        altered = copy.deepcopy(self.history)
        del altered["policy_quarter_means"]["2014-09-30"]
        with self.assertRaisesRegex(ValueError, "no fill"):
            calibrate(altered)
        altered = copy.deepcopy(self.history)
        altered["quarters"].append(altered["quarters"][-1])
        with self.assertRaisesRegex(ValueError, "uniquely dated"):
            calibrate(altered)
        altered = copy.deepcopy(self.history)
        altered["quarters"][0]["deposit_cost_annualized_proxy"] = -0.01
        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            calibrate(altered)

    def test_holdout_failure_is_not_promoted_to_engine(self):
        recommendation = self.result["recommended_illustrative_beta"]
        self.assertFalse(recommendation["apply_to_engine"])
        self.assertFalse(recommendation["holdout_support"])
        self.assertGreater(self.result["metrics"]["lagged_model"]["holdout"]["rmse_bps"], self.result["metrics"]["train_end_persistence"]["holdout"]["rmse_bps"])
        self.assertIsNone(self.result["diagnostics"]["statistical_confidence_interval"])

    def test_copied_root_replays_and_detects_raw_and_normalized_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory)
            for relative in [s["local_path"] for s in self.sources.values()] + ["data/processed/history.json", "data/processed/calibration.json", "data/raw/history/source_bundle.json"]:
                destination = checkout / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, destination)
            self.assertEqual(load_verified_calibration(checkout), self.result)
            calibration_path = checkout / "data/processed/calibration.json"
            corrupted = copy.deepcopy(self.result)
            corrupted["coefficients"]["total_beta"] += 0.1
            calibration_path.write_text(json.dumps(corrupted), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "deterministic historical replay"):
                load_verified_calibration(checkout)
            shutil.copy2(ROOT / "data/processed/calibration.json", calibration_path)
            raw_path = checkout / self.sources["fred_dff"]["local_path"]
            raw_path.write_bytes(raw_path.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                load_verified_calibration(checkout)


if __name__ == "__main__":
    unittest.main()
