"""Source-to-model joins and complete compressed evidence are independently checked."""
import copy
from pathlib import Path
import tempfile
import unittest

from bank_alm.engine import run_analysis
from bank_alm.pipeline import ROOT, read_json, validate_sources
from bank_alm.research import prepare_research_inputs
from bank_alm.storage import compact_analysis, read_gzip_json, write_gzip_json
from bank_alm.verification import audit_saved_analysis, audit_scenario_group


class ExtendedResearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot, cls.curve = validate_sources()
        cls.reference = read_json(ROOT / "configs/assumptions.json")
        cls.inputs = prepare_research_inputs(cls.snapshot, cls.reference)
        cls.assumptions = cls.inputs["extended_assumptions"]
        cls.analysis = run_analysis(cls.snapshot, cls.assumptions, cls.curve)

    def test_source_join_and_failed_calibration_do_not_rewrite_reference(self):
        self.assertEqual(self.reference["deposits"]["interest_rate"], .022)
        self.assertAlmostEqual(self.assumptions["deposits"]["interest_rate"], .018199438337660963)
        self.assertEqual(self.assumptions["deposits"]["beta"], self.reference["deposits"]["beta"])
        self.assertFalse(self.inputs["calibration"]["recommended_illustrative_beta"]["apply_to_engine"])
        self.assertIn(self.inputs["calibration"]["coefficients"]["total_beta"], self.assumptions["sensitivity"]["deposit_betas"])
        self.assertAlmostEqual(self.assumptions["business_costs"]["annual_operating_expense_fraction_assets"] * 157_412_000_000, 4_166_000_000)

    def test_entire_sourced_policy_grid_passes_independent_ledger_audit(self):
        audit = audit_saved_analysis(self.analysis, self.snapshot, self.assumptions)
        self.assertTrue(audit["passed"])
        self.assertEqual(audit["audited_scenario_paths"], 248)
        self.assertGreater(audit["independent_numeric_comparisons"], 1_000_000)

    def test_per_band_principal_and_pledge_tampering_are_detected(self):
        for field in ("ending_book_usd", "pledged_book_usd", "cumulative_principal_usd"):
            with self.subTest(field=field):
                scenario = copy.deepcopy(self.analysis["scenarios"][0])
                scenario["monthly"][0]["asset_segment_inventory"][0][field] += 1000
                with self.assertRaises(ValueError):
                    audit_scenario_group([scenario], self.snapshot, self.assumptions)

    def test_compact_view_retains_accounts_and_full_compressed_file_retains_bands(self):
        scenario = self.analysis["scenarios"][0]
        sample = {"scenarios": [scenario], "policies": {"candidates": [{"id": "sample", "scenarios": [scenario]}]}, "policy_analysis": {"scenarios": [scenario]}}
        compact = compact_analysis(sample)
        self.assertNotIn("asset_segment_inventory", compact["scenarios"][0]["monthly"][0])
        self.assertEqual(compact["scenarios"][0]["monthly"][0]["loans_usd"], scenario["monthly"][0]["loans_usd"])
        self.assertIn("asset_segment_inventory", scenario["monthly"][0])
        with tempfile.TemporaryDirectory(prefix="alm_full_evidence_") as folder:
            path = Path(folder) / "analysis.json.gz"
            write_gzip_json(path, sample)
            restored = read_gzip_json(path)
            self.assertEqual(restored, sample)
            self.assertEqual(compact_analysis(restored), compact)


if __name__ == "__main__":
    unittest.main()
