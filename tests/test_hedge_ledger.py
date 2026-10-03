"""Independent cash, collateral and equity checks for the hedge extension."""
import copy
import json
import math
from pathlib import Path
import unittest

from bank_alm.engine import BASE, run_analysis, simulate_scenario

ROOT = Path(__file__).resolve().parents[1]


class HedgeLedger(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = json.loads((ROOT / "data/processed/bank_snapshot.json").read_text())
        cls.assumptions = json.loads((ROOT / "configs/assumptions.json").read_text())
        cls.curve = json.loads((ROOT / "data/processed/curve.json").read_text())
        cls.analysis = run_analysis(cls.snapshot, cls.assumptions, cls.curve)

    def run_hedge(self, shock, fraction=0.2, snapshot=None, assumptions=None):
        return simulate_scenario(snapshot or self.snapshot, assumptions or self.assumptions, self.curve, {**BASE, "shock_bps": shock}, {"prefunding_fraction": 0.0, "funding_order": "borrow_first", "hedge_fraction_assets": fraction})

    def test_v1_zero_hedge_reference_exactly_preserved(self):
        fixture = json.loads((ROOT / "tests/fixtures/v1_reference.json").read_text())
        self.assertEqual(self.analysis["baseline"], fixture["baseline"])
        for old, new in zip(fixture["scenarios"], self.analysis["scenarios"]):
            for key, value in old.items():
                self.assertEqual(new[key], value, (old["id"], key))
        self.assertLess(self.analysis["scenarios"][0]["minimum_observed_cash_usd"], self.analysis["scenarios"][0]["min_cash_usd"])

    def test_positive_swap_mark_is_segregated_not_spendable(self):
        result = self.run_hedge(200)
        event = result["initial_event"]
        self.assertGreater(event["derivative_value_usd"], 0)
        self.assertEqual(event["received_collateral_cash_usd"], event["derivative_value_usd"])
        self.assertEqual(event["collateral_return_liability_usd"], event["received_collateral_cash_usd"])
        expected_cash = self.snapshot["balance_sheet_usd"]["cash"] - result["initial_margin_usd"] - result["transaction_fee_usd"]
        self.assertAlmostEqual(event["cash_usd"], expected_cash, delta=0.01)
        self.assertEqual(event["posted_variation_margin_usd"], 0)

    def test_negative_mark_requires_actual_posted_cash(self):
        result = self.run_hedge(-200)
        event = result["initial_event"]
        self.assertLess(event["derivative_value_usd"], 0)
        self.assertEqual(event["posted_variation_margin_usd"], -event["derivative_value_usd"])
        expected_cash = self.snapshot["balance_sheet_usd"]["cash"] - result["initial_margin_usd"] - event["posted_variation_margin_usd"] - result["transaction_fee_usd"]
        self.assertAlmostEqual(event["cash_usd"], expected_cash, delta=0.01)
        self.assertEqual(event["received_collateral_cash_usd"], 0)

    def test_all_policy_ledgers_balance_without_using_reported_residual(self):
        opening = self.snapshot["balance_sheet_usd"]
        self.assertEqual(len(self.analysis["policies"]["candidates"]), 30)
        for candidate in self.analysis["policies"]["candidates"]:
            self.assertEqual(len(candidate["scenarios"]), 8)
            for result in candidate["scenarios"]:
                for row in [result["initial_event"]] + result["monthly"]:
                    assets = math.fsum(row[key] for key in ("cash_usd", "securities_usd", "loans_usd", "derivative_value_usd", "posted_initial_margin_usd", "posted_variation_margin_usd", "received_collateral_cash_usd")) + opening["other_assets"]
                    claims = math.fsum(row[key] for key in ("deposits_usd", "wholesale_funding_usd", "equity_usd", "collateral_return_liability_usd", "payment_payable_usd")) + opening["other_liabilities"]
                    self.assertAlmostEqual(assets, claims, delta=0.01)
                    self.assertGreaterEqual(row["cash_usd"], 0)
                    self.assertAlmostEqual(row["swap_net_coupon_usd"], row["swap_floating_receipt_usd"] - row["swap_fixed_payment_usd"], delta=0.01)

    def test_terminal_closeout_does_not_double_count_initial_mark(self):
        for shock in (-200, 0, 200):
            result = self.run_hedge(shock)
            events = [result["initial_event"]] + result["monthly"]
            expected_profit = sum(r["nii_usd"] + r["swap_net_coupon_usd"] + r["collateral_interest_usd"] + r["sale_pnl_usd"] - r["transaction_fee_usd"] for r in events) + result["monthly"][-1]["swap_closeout_cashflow_usd"]
            self.assertAlmostEqual(result["monthly"][-1]["equity_usd"] - self.snapshot["balance_sheet_usd"]["equity"], expected_profit, delta=0.01)
            self.assertAlmostEqual(result["modeled_earnings_usd"], expected_profit, delta=0.01)
            self.assertAlmostEqual(sum(r["swap_mtm_pnl_usd"] for r in events), result["swap_terminal_closeout_usd"], delta=0.01)
            for key in ("derivative_value_usd", "posted_initial_margin_usd", "posted_variation_margin_usd", "received_collateral_cash_usd", "collateral_return_liability_usd"):
                self.assertEqual(result["monthly"][-1][key], 0)

    def test_posted_collateral_interest_uses_prior_actual_balance(self):
        result = self.run_hedge(-200)
        previous = result["initial_event"]
        for row in result["monthly"]:
            expected = (previous["posted_initial_margin_usd"] + previous["posted_variation_margin_usd"]) * row["swap_collateral_rate"] * row["swap_accrual_fraction"]
            self.assertAlmostEqual(row["collateral_interest_usd"], expected, delta=0.01)
            self.assertEqual(row["received_collateral_interest_income_usd"], row["received_collateral_interest_expense_usd"])
            previous = row

    def test_opening_margin_failure_is_retained_after_recovery(self):
        snapshot, assumptions = copy.deepcopy(self.snapshot), copy.deepcopy(self.assumptions)
        balance = snapshot["balance_sheet_usd"]
        balance["other_assets"] += balance["cash"] - 1.0
        balance["cash"] = 1.0
        snapshot["totals_usd"]["interest_bearing_cash"] = 0.0
        assumptions["funding"]["incremental_cap_fraction_assets"] = 0.0
        assumptions["securities"]["sale_cap_fraction"] = 0.0
        result = self.run_hedge(-200, snapshot=snapshot, assumptions=assumptions)
        self.assertGreater(result["initial_event"]["unfunded_margin_usd"], 1e6)
        self.assertGreater(result["initial_event"]["payment_payable_usd"], 1)
        self.assertEqual(result["monthly"][-1]["unfunded_margin_usd"], 0)
        self.assertIn("margin_requirement_unfunded", result["breaches"])
        self.assertIn("payment_obligation_unsettled", result["breaches"])
        self.assertLess(result["max_accounting_residual_usd"], 0.01)

    def test_unpaid_coupon_and_closeout_remain_liabilities(self):
        snapshot, assumptions = copy.deepcopy(self.snapshot), copy.deepcopy(self.assumptions)
        balance = snapshot["balance_sheet_usd"]
        balance["other_assets"] += balance["cash"] + balance["securities"] + balance["loans"]
        balance["cash"] = balance["securities"] = balance["loans"] = 0.0
        snapshot["totals_usd"]["interest_bearing_cash"] = 0.0
        assumptions["funding"]["incremental_cap_fraction_assets"] = 0.0
        assumptions["securities"]["sale_cap_fraction"] = 0.0
        result = self.run_hedge(-200, snapshot=snapshot, assumptions=assumptions)
        self.assertLess(result["swap_terminal_closeout_usd"], 0)
        self.assertGreater(result["monthly"][-1]["payment_payable_usd"], -result["swap_terminal_closeout_usd"])
        self.assertTrue(all(r["cash_usd"] == 0 for r in result["monthly"]))
        self.assertLess(result["max_accounting_residual_usd"], 0.01)
        self.assertIn("payment_obligation_unsettled", result["breaches"])

    def test_joint_policy_selection_respects_all_common_constraints(self):
        policies = self.analysis["policies"]
        feasible = [p for p in policies["candidates"] if p["feasible"]]
        self.assertTrue(feasible)
        selected = next(p for p in feasible if p["id"] == policies["selected_policy_id"])
        self.assertEqual(selected["worst_case_earnings_usd"], max(p["worst_case_earnings_usd"] for p in feasible))
        self.assertTrue(all(not s["breaches"] for s in selected["scenarios"]))
        self.assertTrue(all(not p["feasible"] for p in policies["candidates"] if p["hedge_fraction_assets"] == 0))


if __name__ == "__main__":
    unittest.main()
