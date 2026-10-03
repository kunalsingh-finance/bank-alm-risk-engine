"""Source scope, distinct reset/maturity semantics and inventory conservation."""
import copy
import json
import math
from pathlib import Path
import shutil
import tempfile
import unittest

from bank_alm.engine import BASE, simulate_scenario, validate_inputs
from bank_alm.segmentation import (advance_assets, asset_values, build_asset_segments,
                                   initialize_state, inventory_snapshot, sell_securities)
from scripts.fetch_maturity_data import load_verified_profile

ROOT = Path(__file__).resolve().parents[1]


class Segmentation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = load_verified_profile(ROOT)
        cls.a = json.loads((ROOT / "configs/assumptions.json").read_text())
        cls.snapshot = json.loads((ROOT / "data/processed/bank_snapshot.json").read_text())
        cls.curve = json.loads((ROOT / "data/processed/curve.json").read_text())
        cls.config = build_asset_segments(cls.profile, cls.a)

    def example(self, **changes):
        item = {"id": "example", "asset_class": "securities", "opening_book_usd": 120.0,
                "coupon": .12, "rate_type": "fixed", "maturity_months": 2,
                "reset_month": None, "amortization": "bullet", "discount_spread": 0,
                "pledged_fraction": 0, "sale_eligible": True, "prepayment_eligible": False}
        item.update(changes)
        return initialize_state({"segments": [item]})

    def test_reported_scope_bridges_are_exact(self):
        t = self.profile["totals_usd"]
        self.assertEqual(t["securities_bands"], 33_147_000_000)
        self.assertEqual(t["securities_bands"] + t["equity_securities_residual"] + t["nonaccrual_debt_securities"], t["securities_book"])
        self.assertEqual(t["loan_bands_accruing"] + t["nonaccrual_loans"], t["gross_loans"])
        self.assertEqual(t["gross_loans"] - t["allowance_for_loans"], t["net_loans"])
        self.assertEqual(t["unpledged_securities_aggregate"], 12_968_000_000)
        for kind, key in (("loans", "net_loans"), ("securities", "securities_book")):
            self.assertAlmostEqual(math.fsum(s["opening_book_usd"] for s in self.config["segments"] if s["asset_class"] == kind), t[key], delta=.01)

    def test_offline_replay_uses_supplied_root_and_rejects_processed_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "data/raw/maturity", root / "data/raw/maturity")
            (root / "data/processed").mkdir(parents=True)
            path = root / "data/processed/maturity_profile.json"
            path.write_text(json.dumps(self.profile))
            self.assertEqual(load_verified_profile(root), self.profile)
            changed = copy.deepcopy(self.profile)
            changed["totals_usd"]["net_loans"] += 1
            path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, "differs"):
                load_verified_profile(root)
            path.write_text(json.dumps(self.profile))
            record = self.profile["source_records"][0]
            source = root / record["local_path"]
            source.write_bytes(source.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                load_verified_profile(root)

    def test_reset_changes_coupon_without_redeeming_floating_principal(self):
        state = self.example(rate_type="floating", reset_month=2, maturity_months=60)
        one = advance_assets(state, 1, 0, .02)
        two = advance_assets(state, 2, 0, .02)
        three = advance_assets(state, 3, 0, .02)
        self.assertEqual(one["securities_principal_usd"] + two["securities_principal_usd"] + three["securities_principal_usd"], 0)
        self.assertEqual(two["securities_income_usd"], 1.2)
        self.assertAlmostEqual(three["securities_income_usd"], 1.4)
        self.assertEqual(state[0]["book_usd"], 120)

    def test_short_maturity_returns_principal_once_and_stops_interest(self):
        state = self.example()
        flows = [advance_assets(state, m, 0, 0) for m in range(1, 4)]
        self.assertEqual([f["securities_principal_usd"] for f in flows], [0, 120, 0])
        self.assertEqual([f["securities_income_usd"] for f in flows], [1.2, 1.2, 0])

    def test_encumbered_inventory_cannot_be_sold_or_freed_by_sale(self):
        state = self.example(maturity_months=24, pledged_fraction=.75)
        sale = sell_securities(state, 1_000, self.curve, BASE, 0, 1_000, 0)
        self.assertAlmostEqual(sale["book_sold_usd"], 30)
        self.assertAlmostEqual(sale["proceeds_usd"], 30)
        self.assertEqual(state[0]["pledged_book_usd"], 90)
        again = sell_securities(state, 1_000, self.curve, BASE, 0, 1_000, 0)
        self.assertEqual(again["book_sold_usd"], 0)
        self.assertEqual(state[0]["book_usd"], 90)

    def test_sale_unit_price_does_not_depend_on_notional_after_amortization(self):
        first = self.example(maturity_months=24, amortization="level_principal", prepayment_eligible=True)
        second = self.example(opening_book_usd=12_000, maturity_months=24, amortization="level_principal", prepayment_eligible=True)
        for month in range(1, 5):
            advance_assets(first, month, .08, 0)
            advance_assets(second, month, .08, 0)
        shock = {"shape": "parallel", "shock_bps": 200}
        small = sell_securities(first, 20, self.curve, shock, 4, 1e9, .02, .08, .08)
        large = sell_securities(second, 2_000, self.curve, shock, 4, 1e9, .02, .08, .08)
        self.assertAlmostEqual(small["weighted_price_ratio"], large["weighted_price_ratio"], places=12)
        self.assertLess(small["weighted_price_ratio"], 1)
        self.assertAlmostEqual(large["book_sold_usd"], 100 * small["book_sold_usd"], delta=1e-8)

    def test_credit_loss_principal_and_sales_conserve_every_segment(self):
        state = initialize_state(self.config)
        for month in range(1, 13):
            advance_assets(state, month, .08, .02, .0005)
            if month in (1, 4):
                sell_securities(state, 1e9, self.curve, {"shape": "parallel", "shock_bps": 200}, month, 1e10, .02, .08, .08)
        for row in inventory_snapshot(state):
            expected = math.fsum(row[k] for k in ("ending_book_usd", "cumulative_principal_usd", "cumulative_credit_loss_usd", "cumulative_sale_book_usd"))
            self.assertAlmostEqual(row["initial_book_usd"], expected, delta=.01)
            self.assertLessEqual(row["pledged_book_usd"], row["ending_book_usd"] + .01)
        nonaccrual = next(s for s in state if s["id"] == "nonaccrual_loans")
        self.assertGreater(nonaccrual["cumulative_credit_loss_usd"], 0)
        self.assertEqual(nonaccrual["cumulative_principal_usd"], 0)

    def test_full_named_paths_close_with_costs_hedge_and_sourced_bands(self):
        a = copy.deepcopy(self.a)
        a["asset_segments"] = self.config
        a["business_costs"] = {"enabled": True, "annual_operating_expense_fraction_assets": .025, "annual_credit_loss_fraction_loans": .006}
        validate_inputs(self.snapshot, a, self.curve)
        b = self.snapshot["balance_sheet_usd"]
        for scenario in [BASE] + a["scenarios"]:
            result = simulate_scenario(self.snapshot, a, self.curve, scenario, {"prefunding_fraction": .06, "funding_order": "sell_first", "hedge_fraction_assets": .05})
            previous_loans = b["loans"]
            previous_securities = b["securities"]
            for row in [result["initial_event"]] + result["monthly"]:
                assets = math.fsum(row[k] for k in ("cash_usd", "securities_usd", "loans_usd", "derivative_value_usd", "posted_initial_margin_usd", "posted_variation_margin_usd", "received_collateral_cash_usd")) + b["other_assets"]
                liabilities_equity = math.fsum(row[k] for k in ("deposits_usd", "wholesale_funding_usd", "equity_usd", "collateral_return_liability_usd", "payment_payable_usd")) + b["other_liabilities"]
                self.assertAlmostEqual(assets, liabilities_equity, delta=.01)
                self.assertAlmostEqual(previous_loans - row["credit_loss_usd"] - row["loan_principal_usd"], row["loans_usd"], delta=.01)
                self.assertAlmostEqual(previous_securities - row["security_principal_usd"] - row["securities_sale_book_usd"], row["securities_usd"], delta=.01)
                if row["month"]:
                    self.assertAlmostEqual(row["credit_loss_usd"], previous_loans * .006 / 12, delta=.01)
                previous_loans, previous_securities = row["loans_usd"], row["securities_usd"]
            self.assertAlmostEqual(result["monthly"][-1]["equity_usd"] - b["equity"], result["modeled_earnings_usd"], delta=.01)
            self.assertLessEqual(result["securities_sold_usd"], self.config["permitted_security_sale_book_usd"] + .01)

    def test_invalid_fixed_share_and_out_of_band_representative_are_rejected(self):
        for overrides in ({"fixed_fractions": {"other_loans": 1.2}}, {"representative_months": {"3LES": 13}}):
            with self.assertRaises(ValueError):
                build_asset_segments(self.profile, self.a, overrides)


if __name__ == "__main__":
    unittest.main()
