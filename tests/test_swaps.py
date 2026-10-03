"""Independent dated swap identities; no market-price or bank calibration claim."""
import copy
from datetime import date, datetime
import math
import unittest

from bank_alm.swaps import discount_factor, par_swap_rate, projected_cashflows, schedule, swap_path, value_remaining


FLAT = {"tenors_years": [1 / 12, 1, 5, 10], "zero_rates": [0.04] * 4}
SLOPED = {"tenors_years": [1 / 12, 1, 3, 5, 10], "zero_rates": [0.045, 0.04, 0.035, 0.041, 0.05]}
BASE = {"shape": "parallel", "shock_bps": 0}
UP = {"shape": "parallel", "shock_bps": 200}
DOWN = {"shape": "parallel", "shock_bps": -200}
START = "2025-12-31"
NOTIONAL = 1_000_000_000


class DatedSchedule(unittest.TestCase):
    def test_end_of_month_preserves_leap_dates_and_actual_days(self):
        rows = schedule("2023-12-31", 3)
        self.assertEqual([r["payment_date"] for r in rows], ["2024-01-31", "2024-02-29", "2024-03-31"])
        self.assertEqual([r["accrual_days"] for r in rows], [31, 29, 31])
        self.assertEqual(rows[1]["accrual_fraction"], 29 / 365)
        self.assertEqual(rows[2]["payment_time_years"], 91 / 365)
        self.assertEqual(schedule("2024-02-29", 12)[-1]["payment_date"], "2025-02-28")
        self.assertEqual(schedule("2023-12-31", 12)[-1]["payment_time_years"], 366 / 365)

    def test_clipped_non_month_end_date_does_not_drift(self):
        self.assertEqual([r["payment_date"] for r in schedule("2024-01-30", 3)], ["2024-02-29", "2024-03-30", "2024-04-30"])
        self.assertEqual(schedule(date(2025, 4, 15), 1)[0]["payment_date"], "2025-05-15")

    def test_invalid_date_and_month_arguments(self):
        for start in ("2025-02-29", "20251231", "2025-W01-1", 20251231, datetime(2025, 12, 31)):
            with self.subTest(start=start), self.assertRaises(ValueError):
                schedule(start)
        for tenor in (0, -1, 1.5, True, 1201):
            with self.subTest(tenor=tenor), self.assertRaises(ValueError):
                schedule(START, tenor)
        with self.assertRaises(ValueError):
            schedule("9999-12-31", 1)


class SwapValuation(unittest.TestCase):
    def test_par_rate_matches_flat_curve_closed_form_and_initial_pv_zero(self):
        for start in (START, "2023-12-31", "2024-01-30"):
            rows = schedule(start)
            # Closed-form coupon, built directly from calendar day differences.
            origin = date.fromisoformat(start)
            annuity = sum((date.fromisoformat(r["payment_date"]) - date.fromisoformat(r["accrual_start_date"])).days / 365 * math.exp(-0.04 * (date.fromisoformat(r["payment_date"]) - origin).days / 365) for r in rows)
            maturity = (date.fromisoformat(rows[-1]["payment_date"]) - origin).days / 365
            expected = -math.expm1(-0.04 * maturity) / annuity
            self.assertAlmostEqual(par_swap_rate(FLAT, start), expected, places=14)
            path = swap_path(FLAT, BASE, start, NOTIONAL)
            self.assertAlmostEqual(path["inception_value_usd"], 0.0, delta=0.00002)
            self.assertAlmostEqual(path["opening_value_usd"], 0.0, delta=0.00002)
            self.assertAlmostEqual(path["opening_fixed_leg_pv_usd"], path["opening_floating_leg_pv_usd"], delta=0.00002)

    def test_payer_fixed_direction_and_first_fixing_locked(self):
        base = swap_path(FLAT, BASE, START, NOTIONAL)
        up = swap_path(FLAT, UP, START, NOTIONAL)
        down = swap_path(FLAT, DOWN, START, NOTIONAL)
        self.assertGreater(up["opening_value_usd"], 0)
        self.assertLess(down["opening_value_usd"], 0)
        for path in (up, down):
            self.assertEqual(path["terms"]["fixed_rate"], base["terms"]["fixed_rate"])
            self.assertEqual(path["monthly"][0]["floating_receipt_usd"], base["monthly"][0]["floating_receipt_usd"])
            self.assertEqual(path["monthly"][0]["net_coupon_usd"], base["monthly"][0]["net_coupon_usd"])
        first_alpha = up["monthly"][0]["accrual_fraction"]
        self.assertAlmostEqual(up["monthly"][0]["floating_receipt_usd"], NOTIONAL * math.expm1(0.04 * first_alpha), delta=0.000001)
        second_alpha = up["monthly"][1]["accrual_fraction"]
        self.assertAlmostEqual(up["monthly"][1]["floating_receipt_usd"], NOTIONAL * math.expm1(0.06 * second_alpha), delta=0.000001)

    def test_float_leg_telescoping_includes_locked_first_fixing_correction(self):
        for curve in (FLAT, SLOPED):
            for scenario in (BASE, UP, DOWN, {"shape": "steepener"}):
                flows = projected_cashflows(curve, scenario, START, NOTIONAL)
                first = flows[0]
                first_df = discount_factor(curve, scenario, first["payment_time_years"])
                shock_first_forward = (1 / first_df - 1) / first["accrual_fraction"]
                locked_adjustment = NOTIONAL * first["accrual_fraction"] * (first["floating_rate"] - shock_first_forward) * first_df
                expected = NOTIONAL * (1 - discount_factor(curve, scenario, flows[-1]["payment_time_years"])) + locked_adjustment
                actual = math.fsum(r["floating_receipt_usd"] * r["discount_factor_from_open"] for r in flows)
                self.assertAlmostEqual(actual, expected, delta=0.00002)
                # The telescoping principal is an identity, never a cash exchange.
                self.assertTrue(all(r["principal_exchange_usd"] == 0 for r in flows))
                self.assertLess(abs(flows[-1]["floating_receipt_usd"]), NOTIONAL / 20)
                self.assertLess(abs(flows[-1]["fixed_payment_usd"]), NOTIONAL / 20)

    def test_conditional_value_rollforward_with_coupons_and_closeout(self):
        for curve in (FLAT, SLOPED):
            for scenario in (BASE, UP, DOWN, {"shape": "flattener"}):
                path = swap_path(curve, scenario, "2023-12-31", NOTIONAL)
                flows = projected_cashflows(curve, scenario, "2023-12-31", NOTIONAL)
                previous_value = path["opening_value_usd"]
                previous_df = 1.0
                for row in path["monthly"]:
                    conditional = value_remaining(flows, curve, scenario, row["payment_time_years"])
                    self.assertAlmostEqual(row["swap_value_usd"], conditional, delta=0.00002)
                    evolved = previous_value * previous_df / row["discount_factor_from_open"]
                    self.assertAlmostEqual(evolved, row["net_coupon_usd"] + conditional, delta=0.00002)
                    self.assertAlmostEqual(previous_df / row["discount_factor_from_open"], 1 + row["collateral_rate"] * row["accrual_fraction"], places=14)
                    self.assertAlmostEqual(row["coupon_pv_rollforward_residual_usd"], 0, delta=0.00002)
                    previous_value = conditional
                    previous_df = row["discount_factor_from_open"]
                received_pv = math.fsum((r["net_coupon_usd"] + r["closeout_cashflow_usd"]) * r["discount_factor_from_open"] for r in path["monthly"])
                self.assertAlmostEqual(received_pv, path["opening_value_usd"], delta=0.00002)
                last = path["monthly"][-1]
                self.assertEqual(last["closeout_cashflow_usd"], last["swap_value_usd"])
                self.assertEqual(last["ending_swap_value_usd"], 0)
                self.assertTrue(all(r["closeout_cashflow_usd"] == 0 for r in path["monthly"][:-1]))

    def test_full_tenor_maturity_has_zero_closeout_and_no_principal(self):
        path = swap_path(FLAT, UP, START, NOTIONAL, tenor_months=12, horizon_months=12)
        last = path["monthly"][-1]
        self.assertEqual(last["swap_value_usd"], 0)
        self.assertEqual(last["closeout_cashflow_usd"], 0)
        self.assertEqual(last["principal_exchange_usd"], 0)

    def test_zero_notional_has_no_cash_or_mark_and_negative_rates_are_consistent(self):
        path = swap_path(SLOPED, UP, START, 0)
        for key in ("inception_value_usd", "opening_value_usd", "opening_fixed_leg_pv_usd", "opening_floating_leg_pv_usd", "terminal_closeout_usd"):
            self.assertEqual(path[key], 0)
        for row in path["monthly"]:
            for key in ("fixed_payment_usd", "floating_receipt_usd", "net_coupon_usd", "swap_value_usd", "closeout_cashflow_usd", "ending_swap_value_usd"):
                self.assertEqual(row[key], 0)
        negative = {**FLAT, "zero_rates": [-0.01] * 4}
        path = swap_path(negative, BASE, START, NOTIONAL)
        self.assertLess(path["terms"]["fixed_rate"], 0)
        self.assertAlmostEqual(path["opening_value_usd"], 0, delta=0.00002)

    def test_invalid_notional_horizon_curve_and_shock(self):
        for amount in (-1, math.inf, math.nan, True, "100"):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                swap_path(FLAT, BASE, START, amount)
        for months in (0, -1, 1.5, True, 61):
            with self.subTest(months=months), self.assertRaises(ValueError):
                swap_path(FLAT, BASE, START, 1, horizon_months=months)
        for bad_curve in ({"tenors_years": [1], "zero_rates": [0.04]}, {"tenors_years": [1, 1], "zero_rates": [0.04, 0.04]}, {"tenors_years": [0, 1], "zero_rates": [0.04, 0.04]}, {"tenors_years": [1, 2], "zero_rates": [math.nan, 0.04]}, {"tenors_years": [1, 2], "zero_rates": [0.04]}):
            with self.subTest(curve=bad_curve), self.assertRaises(ValueError):
                swap_path(bad_curve, BASE, START, 1)
        for scenario in ({"shape": "unknown"}, {"shock_bps": math.nan}, {"shock_bps": True}):
            with self.subTest(scenario=scenario), self.assertRaises(ValueError):
                swap_path(FLAT, scenario, START, 1)
        with self.assertRaises(ValueError):
            discount_factor(FLAT, BASE, -1)
        with self.assertRaises(ValueError):
            value_remaining(projected_cashflows(FLAT, BASE, START, 1), FLAT, BASE, -1)
        with self.assertRaises(ValueError):
            projected_cashflows(FLAT, BASE, START, 1, fixed_rate=math.inf)
        with self.assertRaises(ValueError):
            projected_cashflows(FLAT, BASE, START, 1, first_floating_fixing=math.nan)


if __name__ == "__main__":
    unittest.main()
