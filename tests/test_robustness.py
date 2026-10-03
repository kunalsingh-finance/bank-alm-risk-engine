"""A selected policy remains fixed when independent challenge cases fail."""
import copy
import unittest

from bank_alm.engine import run_analysis
from bank_alm.pipeline import ROOT, read_json
from bank_alm.robustness import alternate_curve, audit_robustness, design_cases, evaluate_robustness


class Robustness(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = read_json(ROOT / "data/processed/bank_snapshot.json")
        cls.curve = read_json(ROOT / "data/processed/curve.json")
        cls.assumptions = read_json(ROOT / "configs/assumptions.json")
        cls.analysis = run_analysis(cls.snapshot, cls.assumptions, cls.curve)
        cls.result = evaluate_robustness(cls.snapshot, cls.assumptions, cls.curve, cls.analysis)

    def test_frozen_selection_and_failures_are_retained(self):
        self.assertEqual(self.result["selected_policy_id"], self.analysis["policies"]["selected_policy_id"])
        self.assertEqual(self.result["summary"]["case_count"], 30)
        self.assertGreater(self.result["summary"]["failed_case_count"], 0)
        self.assertTrue(all(row["policy_id"] == self.result["selected_policy_id"] for row in self.result["cases"]))
        audited = audit_robustness(self.result, self.snapshot, self.analysis)
        self.assertTrue(audited["passed"])
        self.assertEqual(audited["audited_scenario_paths"], 120)

    def test_no_selected_policy_is_not_silently_replaced(self):
        analysis = copy.deepcopy(self.analysis)
        analysis["policies"]["selected_policy_id"] = None
        result = evaluate_robustness(self.snapshot, self.assumptions, self.curve, analysis)
        self.assertEqual(result["status"], "no_selected_policy")
        self.assertEqual(result["cases"], [])

    def test_curve_variants_are_transparent_and_do_not_mutate_source(self):
        old = copy.deepcopy(self.curve)
        shifted = alternate_curve(self.curve, "proxy_plus_25bp")
        for actual, original in zip(shifted["zero_rates"], old["zero_rates"]):
            self.assertAlmostEqual(actual - original, .0025)
        flat = alternate_curve(self.curve, "short_end_flat_one_year")
        short = [rate for tenor, rate in zip(flat["tenors_years"], flat["zero_rates"]) if tenor <= 1]
        self.assertEqual(len(set(short)), 1)
        linear = alternate_curve(self.curve, "short_end_linear_origin")
        self.assertLess(linear["tenors_years"][0], old["tenors_years"][0])
        self.assertEqual(self.curve, old)

    def test_unseen_rate_runoff_combinations_exclude_selection_cases(self):
        training = {(scenario.get("shape", "parallel"), scenario.get("shock_bps", 0), scenario.get("deposit_runoff_fraction", 0)) for scenario in self.assumptions["scenarios"]}
        training.add(("parallel", 0, 0))
        for case in design_cases():
            if case["group"] == "unseen_rate_runoff":
                scenario = case["scenario"]
                self.assertNotIn((scenario["shape"], scenario.get("shock_bps", 0), scenario["deposit_runoff_fraction"]), training)

    def test_challenge_cash_tampering_is_detected(self):
        changed = copy.deepcopy(self.result)
        changed["cases"][0]["policy_result"]["monthly"][0]["cash_usd"] += 1_000
        with self.assertRaises(ValueError):
            audit_robustness(changed, self.snapshot, self.analysis)


if __name__ == "__main__":
    unittest.main()
