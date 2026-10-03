"""Independent release and failure-behavior checks on pinned public inputs."""
import copy
import json
import math
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from bank_alm.engine import run_analysis
from bank_alm.pipeline import ROOT, _curve_replay_matches, build, read_json, validate_sources
from bank_alm.verification import audit_saved_analysis
from scripts.fetch_bank_data import validate_snapshot


class CurveReplayTests(unittest.TestCase):
    def setUp(self):
        self.curve = read_json(ROOT / "data/processed/curve.json")

    def test_one_ulp_derived_roundoff_is_accepted(self):
        changed = copy.deepcopy(self.curve)
        changed["zero_rates"] = [math.nextafter(rate, math.inf) for rate in changed["zero_rates"]]
        changed["max_published_zero_error_bps"] = math.nextafter(changed["max_published_zero_error_bps"], math.inf)
        self.assertNotEqual(changed, self.curve)
        self.assertTrue(_curve_replay_matches(changed, self.curve))
        self.assertTrue(_curve_replay_matches(self.curve, changed))

    def test_derived_drift_beyond_absolute_tolerances_is_rejected(self):
        for field, delta in (("zero_rates", 2e-14), ("zero_rates", 1e-4), ("max_published_zero_error_bps", 2e-10)):
            with self.subTest(field=field, delta=delta):
                changed = copy.deepcopy(self.curve)
                if field == "zero_rates":
                    changed[field][0] += delta
                else:
                    changed[field] += delta
                self.assertFalse(_curve_replay_matches(changed, self.curve))

    def test_metadata_parameters_tenors_and_schema_remain_exact(self):
        changes = [
            ("source_sha256", "0" * 64),
            ("schema_version", True),
            ("schema_version", 1.0),
            ("tenors_years", [math.nextafter(self.curve["tenors_years"][0], math.inf)] + self.curve["tenors_years"][1:]),
            ("parameters", {**self.curve["parameters"], "BETA0": math.nextafter(self.curve["parameters"]["BETA0"], math.inf)}),
            ("validation_tolerance_bps", math.nextafter(self.curve["validation_tolerance_bps"], math.inf)),
        ]
        for field, value in changes:
            with self.subTest(field=field, value=value):
                changed = copy.deepcopy(self.curve)
                changed[field] = value
                self.assertFalse(_curve_replay_matches(changed, self.curve))
        for changed in ({**self.curve, "extra": None}, {k: v for k, v in self.curve.items() if k != "source"}, {**self.curve, "zero_rates": self.curve["zero_rates"][:-1]}):
            self.assertFalse(_curve_replay_matches(changed, self.curve))

    def test_invalid_derived_types_and_nonfinite_values_are_rejected(self):
        for field in ("zero_rates", "max_published_zero_error_bps"):
            for value in (True, False, None, "0.036", math.nan, math.inf, -math.inf, 10 ** 1000):
                with self.subTest(field=field, value=value):
                    changed = copy.deepcopy(self.curve)
                    if field == "zero_rates":
                        changed[field][0] = value
                    else:
                        changed[field] = value
                    self.assertFalse(_curve_replay_matches(changed, self.curve))
                    self.assertFalse(_curve_replay_matches(self.curve, changed))
                    self.assertFalse(_curve_replay_matches(changed, changed))


class SourceAndReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot, cls.curve = validate_sources()
        cls.assumptions = read_json(ROOT / "configs/assumptions.json")
        cls.analysis = run_analysis(cls.snapshot, cls.assumptions, cls.curve)

    def test_exact_public_equity_includes_noncontrolling_interests(self):
        totals = self.snapshot["totals_usd"]
        self.assertEqual(totals["total_equity"], totals["bank_equity"] + totals["noncontrolling_interests"])
        self.assertEqual(totals["noncontrolling_interests"], 60_000_000)
        self.assertEqual(totals["assets"], totals["liabilities"] + totals["total_equity"])

    def test_source_replay_rejects_normalized_tampering(self):
        changed = copy.deepcopy(self.snapshot)
        changed["balance_sheet_usd"]["cash"] += 1
        with self.assertRaises(ValueError):
            validate_snapshot(changed)

    def test_copied_sources_are_verified_at_the_requested_root(self):
        with tempfile.TemporaryDirectory(prefix="bank_alm_sources_") as folder:
            root = Path(folder)
            shutil.copytree(ROOT / "data", root / "data")
            snapshot, curve = validate_sources(root)
            self.assertEqual(snapshot, self.snapshot)
            self.assertEqual(curve, self.curve)
            raw_path = root / snapshot["source_records"][1]["local_path"]
            raw_path.write_bytes(raw_path.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                validate_sources(root)

    def test_curve_roundoff_is_accepted_without_rewriting_pinned_inputs(self):
        with tempfile.TemporaryDirectory(prefix="bank_alm_curve_") as folder:
            root = Path(folder)
            shutil.copytree(ROOT / "data", root / "data")
            path = root / "data/processed/curve.json"
            changed = copy.deepcopy(self.curve)
            changed["zero_rates"][0] = math.nextafter(changed["zero_rates"][0], math.inf)
            changed["max_published_zero_error_bps"] = math.nextafter(changed["max_published_zero_error_bps"], math.inf)
            path.write_text(json.dumps(changed), encoding="utf-8")
            pinned_bytes = path.read_bytes()
            _, accepted = validate_sources(root)
            self.assertEqual(accepted, changed)
            self.assertEqual(path.read_bytes(), pinned_bytes)
            changed["zero_rates"][0] += 1e-4
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Normalized curve differs"):
                validate_sources(root)

    def test_independent_saved_ledger_audit(self):
        result = audit_saved_analysis(self.analysis, self.snapshot, self.assumptions)
        self.assertTrue(result["passed"])
        self.assertGreater(result["independent_numeric_comparisons"], 1000)

    def test_zero_hedge_preserves_verified_first_release(self):
        reference = read_json(ROOT / "tests/fixtures/v1_reference.json")
        saved = {scenario["id"]: scenario for scenario in self.analysis["scenarios"]}
        self.assertEqual(set(saved), {scenario["id"] for scenario in reference["scenarios"]})
        for scenario in reference["scenarios"]:
            for field, expected in scenario.items():
                if field != "id":
                    with self.subTest(scenario=scenario["id"], field=field):
                        self.assertAlmostEqual(saved[scenario["id"]][field], expected, delta=0.0001)

    def test_saved_flow_tampering_is_detected(self):
        changed = copy.deepcopy(self.analysis)
        changed["scenarios"][-1]["monthly"][0]["settled_withdrawal_usd"] += 1_000
        with self.assertRaisesRegex(ValueError, "Saved audit failed"):
            audit_saved_analysis(changed, self.snapshot, self.assumptions)

    def test_summary_cannot_override_the_saved_monthly_ledger(self):
        changed = copy.deepcopy(self.analysis)
        changed["scenarios"][0]["nii_12m_usd"] += 1_000
        with self.assertRaisesRegex(ValueError, "Saved audit failed"):
            audit_saved_analysis(changed, self.snapshot, self.assumptions)

    def test_independent_audit_rejects_derivative_and_collateral_tampering(self):
        for field in ("derivative_value_usd", "posted_variation_margin_usd", "received_collateral_cash_usd", "payment_payable_usd", "swap_net_coupon_usd", "collateral_interest_usd", "swap_closeout_cashflow_usd"):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.analysis)
                candidate = next(p for p in changed["policies"]["candidates"] if p["hedge_fraction_assets"] > 0)
                candidate["scenarios"][2]["monthly"][0][field] += 1_000
                with self.assertRaisesRegex(ValueError, "Saved audit failed"):
                    audit_saved_analysis(changed, self.snapshot, self.assumptions)

    def test_independent_audit_includes_opening_margin_event(self):
        changed = copy.deepcopy(self.analysis)
        candidate = next(p for p in changed["policies"]["candidates"] if p["hedge_fraction_assets"] > 0)
        candidate["scenarios"][0]["initial_event"]["collateral_posted_flow_usd"] += 1_000
        with self.assertRaisesRegex(ValueError, "Saved audit failed"):
            audit_saved_analysis(changed, self.snapshot, self.assumptions)

    def test_selected_detail_cannot_disagree_with_audited_policy(self):
        changed = copy.deepcopy(self.analysis)
        changed["policy_analysis"]["scenarios"] = copy.deepcopy(changed["policy_analysis"]["scenarios"])
        changed["policy_analysis"]["scenarios"][0]["modeled_earnings_usd"] += 1_000
        with self.assertRaisesRegex(ValueError, "Displayed policy analysis"):
            audit_saved_analysis(changed, self.snapshot, self.assumptions)

    def test_failed_build_replaces_old_success_report(self):
        with tempfile.TemporaryDirectory(prefix="bank_alm_failure_") as folder:
            output = Path(folder)
            (output / "report.html").write_text("OLD SUCCESS REPORT", encoding="utf-8")
            (output / "analysis.json").write_text('{"old": true}', encoding="utf-8")
            with patch("bank_alm.pipeline.validate_sources", side_effect=ValueError("deliberate test source failure")):
                with self.assertRaises(ValueError):
                    build(output)
            self.assertEqual(read_json(output / "run_status.json")["status"], "blocked")
            self.assertNotIn("OLD SUCCESS REPORT", (output / "report.html").read_text())
            self.assertIn("Report build blocked", (output / "report.html").read_text())
            self.assertTrue(read_json(output / "analysis.json")["old"])

    def test_independent_audit_failure_blocks_otherwise_passing_build(self):
        changed = copy.deepcopy(self.analysis)
        candidate = next(p for p in changed["policies"]["candidates"] if p["hedge_fraction_assets"] > 0)
        candidate["scenarios"][0]["initial_event"]["cash_usd"] += 1_000
        self.assertTrue(all(check["passed"] for check in changed["checks"]))
        with tempfile.TemporaryDirectory(prefix="bank_alm_audit_failure_") as folder:
            output = Path(folder)
            with patch("bank_alm.engine.run_analysis", return_value=changed), patch("bank_alm.research.prepare_research_inputs", return_value={"extended_assumptions": self.assumptions}):
                with self.assertRaisesRegex(ValueError, "Saved audit failed"):
                    build(output)
            self.assertEqual(read_json(output / "run_status.json")["status"], "blocked")
            self.assertIn("Report build blocked", (output / "report.html").read_text())


if __name__ == "__main__":
    unittest.main()
