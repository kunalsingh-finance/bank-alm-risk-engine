"""Operating cash costs and noncash credit losses have distinct ledger effects."""
import copy
import unittest

from bank_alm.engine import BASE, simulate_scenario, validate_inputs
from bank_alm.pipeline import ROOT, read_json


class BusinessCosts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = read_json(ROOT / "data/processed/bank_snapshot.json")
        cls.curve = read_json(ROOT / "data/processed/curve.json")
        cls.assumptions = read_json(ROOT / "configs/assumptions.json")

    def run_costs(self, operating=0.02, loss=0.01, snapshot=None):
        assumptions = copy.deepcopy(self.assumptions)
        assumptions["business_costs"] = {"enabled": True, "annual_operating_expense_fraction_assets": operating, "annual_credit_loss_fraction_loans": loss}
        return simulate_scenario(snapshot or self.snapshot, assumptions, self.curve, BASE)

    def test_costs_reduce_cash_and_credit_losses_reduce_loan_assets(self):
        out = self.run_costs()
        b = self.snapshot["balance_sheet_usd"]
        total_assets = sum(b[k] for k in ("cash", "securities", "loans", "other_assets"))
        first = out["monthly"][0]
        self.assertAlmostEqual(first["operating_expense_usd"], total_assets * .02 / 12)
        self.assertAlmostEqual(first["credit_loss_usd"], b["loans"] * .01 / 12)
        self.assertAlmostEqual(first["loans_usd"], b["loans"] - first["credit_loss_usd"] - first["loan_principal_usd"], delta=.01)
        self.assertAlmostEqual(first["cash_usd"], b["cash"] + first["nii_usd"] + first["loan_principal_usd"] - first["operating_expense_usd"], delta=.01)
        self.assertAlmostEqual(first["equity_usd"], b["equity"] + first["nii_usd"] - first["operating_expense_usd"] - first["credit_loss_usd"], delta=.01)
        self.assertAlmostEqual(out["monthly"][-1]["equity_usd"] - b["equity"], out["modeled_earnings_usd"], delta=.01)
        self.assertLess(out["max_accounting_residual_usd"], .01)

    def test_zero_cost_extension_agrees_with_legacy_unhedged_earnings(self):
        extension = self.run_costs(0, 0)
        legacy = simulate_scenario(self.snapshot, self.assumptions, self.curve, BASE)
        for field in ("nii_12m_usd", "modeled_earnings_usd", "min_cash_usd", "eve_usd"):
            self.assertAlmostEqual(extension[field], legacy[field], delta=.01)

    def test_unpaid_operating_cost_is_a_liability_when_funding_exhausts(self):
        snapshot = copy.deepcopy(self.snapshot)
        b = snapshot["balance_sheet_usd"]
        for key in ("cash", "loans", "securities"):
            b["other_assets"] += b[key]
            b[key] = 0
        snapshot["totals_usd"]["interest_bearing_cash"] = 0
        assumptions = copy.deepcopy(self.assumptions)
        assumptions["funding"]["incremental_cap_fraction_assets"] = 0
        assumptions["business_costs"] = {"enabled": True, "annual_operating_expense_fraction_assets": .02, "annual_credit_loss_fraction_loans": .01}
        out = simulate_scenario(snapshot, assumptions, self.curve, BASE)
        self.assertTrue(all(row["cash_usd"] == 0 for row in out["monthly"]))
        self.assertGreaterEqual(out["max_payment_payable_usd"], out["operating_expense_total_usd"])
        self.assertIn("payment_obligation_unsettled", out["breaches"])
        self.assertLess(out["max_accounting_residual_usd"], .01)

    def test_invalid_cost_assumptions_rejected(self):
        assumptions = copy.deepcopy(self.assumptions)
        assumptions["business_costs"] = {"enabled": True, "annual_operating_expense_fraction_assets": -.1, "annual_credit_loss_fraction_loans": .01}
        with self.assertRaisesRegex(ValueError, "business_costs"):
            validate_inputs(self.snapshot, assumptions, self.curve)


if __name__ == "__main__":
    unittest.main()
