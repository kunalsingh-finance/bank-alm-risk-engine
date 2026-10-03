"""Restricted principal transfers conserve wealth without financing payments."""
import copy
import json
import math
from pathlib import Path
import unittest

from bank_alm.engine import BASE, simulate_scenario, validate_inputs
from bank_alm.segmentation import build_asset_segments
from scripts.fetch_maturity_data import load_verified_profile
from tests.test_engine_unit import zero_income_assumptions

ROOT = Path(__file__).resolve().parents[1]


class PledgedProceeds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = load_verified_profile(ROOT)
        cls.snapshot = json.loads((ROOT / "data/processed/bank_snapshot.json").read_text())
        cls.curve = {"as_of": cls.snapshot["as_of"], "tenors_years": [.25, 30], "zero_rates": [0, 0]}

    def config(self, treatment="release_on_payment"):
        a = zero_income_assumptions()
        a["asset_segments"] = build_asset_segments(self.profile, a, {"pledged_principal_treatment": treatment})
        return a

    def test_default_release_and_retained_cash_have_equal_zero_interest_wealth(self):
        released = simulate_scenario(self.snapshot, self.config(), self.curve, BASE)
        retained = simulate_scenario(self.snapshot, self.config("retain_cash_collateral"), self.curve, BASE)
        self.assertEqual(released["eve_usd"], retained["eve_usd"])
        self.assertEqual(released["nii_12m_usd"], 0)
        self.assertEqual(retained["nii_12m_usd"], 0)
        self.assertEqual(retained["initial_event"]["pledged_cash_usd"], 0)
        for free, restricted in zip(released["monthly"], retained["monthly"]):
            self.assertEqual(free["pledged_cash_usd"], 0)
            self.assertGreater(restricted["pledged_cash_usd"], 0)
            self.assertAlmostEqual(free["cash_usd"], restricted["cash_usd"] + restricted["pledged_cash_usd"], delta=.01)
            self.assertEqual(free["equity_usd"], restricted["equity_usd"])
            self.assertEqual(free["loans_usd"], restricted["loans_usd"])
            self.assertEqual(free["securities_usd"], restricted["securities_usd"])
        self.assertGreater(retained["monthly"][-1]["pledged_cash_usd"], 0)

    def test_transfer_uses_beginning_pledged_share_and_is_never_spent(self):
        a = self.config("retain_cash_collateral")
        scenario = {**BASE, "deposit_runoff_fraction": 1.0}
        result = simulate_scenario(self.snapshot, a, self.curve, scenario)
        previous = {r["segment_id"]: r for r in result["initial_event"]["asset_segment_inventory"]}
        pledged_cash = 0
        for row in result["monthly"]:
            expected = math.fsum(flow["principal_usd"] * previous[flow["segment_id"]]["pledged_book_usd"] / previous[flow["segment_id"]]["ending_book_usd"] for flow in row["asset_segment_flows"] if flow["asset_class"] == "securities" and previous[flow["segment_id"]]["ending_book_usd"] > 0)
            self.assertAlmostEqual(expected, row["pledged_principal_cash_flow_usd"], delta=.01)
            pledged_cash += expected
            self.assertAlmostEqual(pledged_cash, row["pledged_cash_usd"], delta=.01)
            assets = self.snapshot["balance_sheet_usd"]["other_assets"] + math.fsum(row[k] for k in ("cash_usd", "pledged_cash_usd", "securities_usd", "loans_usd", "derivative_value_usd", "posted_initial_margin_usd", "posted_variation_margin_usd", "received_collateral_cash_usd"))
            claims = self.snapshot["balance_sheet_usd"]["other_liabilities"] + math.fsum(row[k] for k in ("deposits_usd", "wholesale_funding_usd", "equity_usd", "collateral_return_liability_usd", "payment_payable_usd"))
            self.assertAlmostEqual(assets, claims, delta=.01)
            previous = {r["segment_id"]: r for r in row["asset_segment_inventory"]}
        self.assertGreater(result["max_unfunded_withdrawals_usd"], 0)
        self.assertGreater(result["securities_sold_usd"], 0)
        self.assertEqual(result["monthly"][0]["cash_usd"], 0)
        self.assertGreater(result["monthly"][0]["pledged_cash_usd"], 0)
        self.assertIn("requested_withdrawals_unfunded", result["breaches"])

    def test_source_bands_preserved_and_unknown_treatment_rejected(self):
        a = self.config()
        self.assertEqual(a["asset_segments"]["source_bands"], self.profile["bands"])
        a["asset_segments"]["assumptions"]["pledged_principal_treatment"] = "invent_cash"
        with self.assertRaisesRegex(ValueError, "pledged-principal"):
            validate_inputs(self.snapshot, a, self.curve)


if __name__ == "__main__":
    unittest.main()
