from decimal import Decimal
import tempfile
import unittest
from pathlib import Path

from frontier_diplomacy.accounting import BudgetExceeded, CostLedger, PriceSnapshot, UsageRecord


class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ledger = CostLedger(Path(self.temp.name) / "costs.sqlite")
        self.price = self.ledger.add_price(PriceSnapshot("model", "openai", Decimal("1"), Decimal("2")))

    def tearDown(self):
        self.temp.cleanup()

    def test_usage_is_idempotent_and_prices_are_versioned(self):
        usage = UsageRecord("call-1", "experiment", "game", "FRANCE", "S1901M", "order", "model", "openai", input_tokens=1000, output_tokens=500, calculated_cost_usd=Decimal("0.002"), certainty="calculated")
        self.assertTrue(self.ledger.record_usage(usage))
        self.assertFalse(self.ledger.record_usage(usage))
        self.assertEqual("model", self.ledger.latest_price("model", "openai").model_id)

    def test_reservations_cannot_exceed_budget(self):
        self.ledger.set_budget("experiment", Decimal("1"))
        reservation = self.ledger.reserve("experiment", "call-1", Decimal("0.75"))
        with self.assertRaises(BudgetExceeded):
            self.ledger.reserve("experiment", "call-2", Decimal("0.26"))
        self.ledger.reconcile(reservation)
        self.assertEqual(Decimal("1.000000"), self.ledger.budget_state("experiment")["remaining_usd"])

    def test_forecast_uses_historical_calls(self):
        self.ledger.record_usage(UsageRecord("call-1", "prior", None, None, None, "order", "model", "openai", calculated_cost_usd=Decimal("0.50"), certainty="calculated"))
        estimate = self.ledger.estimate([("model", "openai")], {("model", "openai", "order"): 4})
        self.assertEqual(Decimal("2.000000"), estimate.expected_usd)
        self.assertEqual("low", estimate.confidence)
