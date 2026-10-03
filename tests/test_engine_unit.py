"""Independent numerical and accounting examples, including exhausted liquidity."""
import copy
import json
import math
import unittest
from pathlib import Path

from bank_alm.engine import BASE, economic_value, run_analysis, simulate_scenario, validate_inputs
from bank_alm.numerics import amortizing_cashflows, bullet_cashflows, interpolate_zero, present_value

ROOT = Path(__file__).resolve().parents[1]


def assumptions():
    return json.loads((ROOT / "configs/assumptions.json").read_text())


def snapshot():
    return {"bank_name": "Synthetic accounting example", "certificate": 0, "as_of": "2025-12-31", "balance_sheet_usd": {"cash": 100.0, "securities": 200.0, "loans": 600.0, "other_assets": 100.0, "noninterest_deposits": 250.0, "interest_deposits": 500.0, "wholesale_funding": 50.0, "other_liabilities": 50.0, "equity": 150.0}, "totals_usd": {"interest_bearing_cash": 60.0}, "earnings": {"annual_nii_usd": 40.0}}


def zero_income_assumptions():
    a = assumptions()
    a["cash"]["yield_spread"] = 1.0
    a["securities"]["coupon"] = 0.0
    a["loans"]["fixed_coupon"] = 0.0
    a["loans"]["floating_coupon"] = 0.0
    a["loans"]["prepayment_cpr"] = 0.0
    a["deposits"]["interest_rate"] = 0.0
    a["deposits"]["beta"] = 0.0
    a["funding"]["initial_coupon"] = 0.0
    a["funding"]["initial_repricing_beta"] = 0.0
    a["funding"]["incremental_spread"] = 0.0
    a["cash"]["floor_fraction_assets"] = 0.0
    a["runoff_monthly_weights"] = [1.0] + [0.0] * 11
    return a


CURVE = {"as_of": "2025-12-31", "tenors_years": [0.25, 1.0, 5.0, 10.0], "zero_rates": [0.04] * 4}
ZERO_CURVE = {**CURVE, "zero_rates": [0.0] * 4}


class CashFlowNumerics(unittest.TestCase):
    def test_zero_coupon_bond_matches_closed_form(self):
        flows = bullet_cashflows(100.0, 0.0, 5.0)
        self.assertAlmostEqual(present_value(flows, CURVE), 100 * math.exp(-0.04 * 5), places=12)
        up = present_value(flows, CURVE, {"shock_bps": 200})
        down = present_value(flows, CURVE, {"shock_bps": -200})
        self.assertLess(up, present_value(flows, CURVE))
        self.assertGreater(down, present_value(flows, CURVE))

    def test_principal_conservation_with_prepayment(self):
        for cpr in (0.0, 0.08, 0.4):
            flows = amortizing_cashflows(100.0, 0.0, 5.0, cpr)
            self.assertAlmostEqual(sum(amount for _, amount in flows), 100.0, places=11)
            self.assertGreaterEqual(min(amount for _, amount in flows), 0.0)
        no_pre = present_value(amortizing_cashflows(100, 0, 5, 0), CURVE)
        pre = present_value(amortizing_cashflows(100, 0, 5, 0.4), CURVE)
        self.assertGreater(pre, no_pre)

    def test_interpolation_and_flat_endpoints(self):
        self.assertEqual(interpolate_zero(0.1, [1, 3], [0.02, 0.04]), 0.02)
        self.assertAlmostEqual(interpolate_zero(2, [1, 3], [0.02, 0.04]), 0.03)
        self.assertEqual(interpolate_zero(20, [1, 3], [0.02, 0.04]), 0.04)


class LedgerExamples(unittest.TestCase):
    def test_cash_withdrawals_conserve_equity_and_deposits(self):
        s = snapshot()
        s["balance_sheet_usd"] = {"cash": 1000.0, "securities": 0.0, "loans": 0.0, "other_assets": 0.0, "noninterest_deposits": 300.0, "interest_deposits": 600.0, "wholesale_funding": 0.0, "other_liabilities": 0.0, "equity": 100.0}
        out = simulate_scenario(s, zero_income_assumptions(), ZERO_CURVE, {**BASE, "deposit_runoff_fraction": 0.5})
        row = out["monthly"][0]
        self.assertEqual(row["cash_usd"], 550.0)
        self.assertEqual(row["deposits_usd"], 450.0)
        self.assertEqual(row["equity_usd"], 100.0)
        self.assertEqual(row["accounting_residual_usd"], 0.0)

    def test_exhausted_borrowing_and_sales_keep_unsettled_liability(self):
        s = snapshot()
        s["balance_sheet_usd"] = {"cash": 10.0, "securities": 100.0, "loans": 0.0, "other_assets": 890.0, "noninterest_deposits": 300.0, "interest_deposits": 600.0, "wholesale_funding": 0.0, "other_liabilities": 0.0, "equity": 100.0}
        s["totals_usd"]["interest_bearing_cash"] = 0.0
        a = zero_income_assumptions()
        a["funding"]["incremental_cap_fraction_assets"] = 0.01
        a["securities"]["sale_cap_fraction"] = 0.5
        out = simulate_scenario(s, a, ZERO_CURVE, {**BASE, "deposit_runoff_fraction": 1.0})
        row = out["monthly"][0]
        self.assertEqual(row["wholesale_funding_usd"], 10.0)
        self.assertEqual(row["securities_sale_book_usd"], 50.0)
        self.assertEqual(row["settled_withdrawal_usd"], 70.0)
        self.assertEqual(row["cumulative_unfunded_withdrawals_usd"], 830.0)
        self.assertEqual(row["deposits_usd"], 830.0)
        self.assertEqual(row["cash_usd"], 0.0)
        self.assertEqual(row["accounting_residual_usd"], 0.0)
        self.assertIn("requested_withdrawals_unfunded", out["breaches"])

    def test_sale_loss_matches_independent_discount_factor(self):
        s = snapshot()
        s["balance_sheet_usd"] = {"cash": 100.0, "securities": 600.0, "loans": 0.0, "other_assets": 300.0, "noninterest_deposits": 300.0, "interest_deposits": 600.0, "wholesale_funding": 0.0, "other_liabilities": 0.0, "equity": 100.0}
        a = zero_income_assumptions()
        a["funding"]["incremental_cap_fraction_assets"] = 0.0
        out = simulate_scenario(s, a, ZERO_CURVE, {**BASE, "shock_bps": 200, "deposit_runoff_fraction": 0.5})
        row = out["monthly"][0]
        expected_price = math.exp(-0.02 * (5 - 1 / 12))
        expected_book_sale = 350 / expected_price
        self.assertAlmostEqual(row["securities_sale_book_usd"], expected_book_sale, places=10)
        self.assertAlmostEqual(row["sale_pnl_usd"], 350 - expected_book_sale, places=10)
        self.assertAlmostEqual(row["equity_usd"], 100 + 350 - expected_book_sale, places=10)
        self.assertAlmostEqual(row["accounting_residual_usd"], 0.0, places=10)

    def test_prefunding_adds_equal_cash_and_debt_and_own_eve_delta(self):
        s, a = snapshot(), assumptions()
        policy = {"prefunding_fraction": 0.03, "funding_order": "borrow_first"}
        out = simulate_scenario(s, a, CURVE, BASE, policy)
        self.assertEqual(out["delta_eve_usd"], 0.0)
        self.assertGreaterEqual(out["monthly"][0]["wholesale_funding_usd"], 80.0)
        for row in out["monthly"]:
            self.assertAlmostEqual(row["accounting_residual_usd"], 0.0, places=9)

    def test_all_grids_close_and_inputs_are_immutable(self):
        s, a, curve = snapshot(), assumptions(), copy.deepcopy(CURVE)
        original = copy.deepcopy((s, a, curve))
        out = run_analysis(s, a, curve)
        self.assertTrue(all(c["passed"] for c in out["checks"]))
        self.assertEqual((s, a, curve), original)
        self.assertEqual(out["scenarios"][0]["delta_nii_usd"], 0.0)
        self.assertEqual(out["scenarios"][0]["delta_eve_usd"], 0.0)

    def test_rate_floor_creates_nonlinear_deposit_response(self):
        s, a = snapshot(), assumptions()
        mild = economic_value(s, a, CURVE, {**BASE, "shock_bps": -200})
        severe = economic_value(s, a, CURVE, {**BASE, "shock_bps": -1000})
        self.assertGreater(mild["repriced_deposit_rate"], 0)
        self.assertEqual(severe["repriced_deposit_rate"], 0)
        self.assertGreater(severe["effective_cpr"], mild["effective_cpr"])

    def test_future_curve_and_unbalanced_snapshot_rejected(self):
        s, a = snapshot(), assumptions()
        with self.assertRaisesRegex(ValueError, "later"):
            validate_inputs(s, a, {**CURVE, "as_of": "2026-01-01"})
        s["balance_sheet_usd"]["equity"] += 10
        with self.assertRaisesRegex(ValueError, "does not close"):
            validate_inputs(s, a, CURVE)

    def test_fractional_maturity_and_invalid_economic_inputs_rejected(self):
        for section, key, value in (("funding", "initial_maturity_years", 1.01), ("funding", "prefunding_maturity_years", 1.01), ("loans", "fixed_coupon", -0.5), ("deposits", "repricing_lag_months", 1.5), ("loans", "floating_reset_lag_months", -1)):
            with self.subTest(section=section, key=key):
                a = assumptions()
                a[section][key] = value
                with self.assertRaises(ValueError):
                    validate_inputs(snapshot(), a, CURVE)


if __name__ == "__main__":
    unittest.main()
