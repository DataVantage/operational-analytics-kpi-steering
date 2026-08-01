"""Tests for period selection and the driver decomposition.

The decomposition tests are the important ones. A decomposition that does not
sum back to the observed change is worse than no decomposition at all, because
it looks precise while being wrong, so the identity is asserted rather than
assumed.
"""

from __future__ import annotations

import unittest

import pandas as pd

from oakpi import analysis
from oakpi.config import Config


class MiniConfig:
    """A stand-in for Config with only the keys the analysis layer reads."""

    def __init__(self, **overrides):
        self._values = {
            "analysis.current_period": "auto",
            "analysis.comparison_mode": "yoy",
            **overrides,
        }

    def get(self, dotted, default=None):
        return self._values.get(dotted, default)


def monthly_frame() -> pd.DataFrame:
    """Two comparable months plus one deliberately incomplete month."""
    rows = [
        dict(month_key=201011, month_label="2010-11", is_complete_month=1,
             active_customers=700, orders_per_customer=2.5, units_per_order=34.0,
             avg_unit_price=4.80, return_rate_identified=0.020,
             net_revenue=380000.0, net_revenue_identified=280000.0,
             net_revenue_guest=100000.0),
        dict(month_key=201111, month_label="2011-11", is_complete_month=1,
             active_customers=640, orders_per_customer=2.3, units_per_order=33.5,
             avg_unit_price=4.95, return_rate_identified=0.053,
             net_revenue=285000.0, net_revenue_identified=232000.0,
             net_revenue_guest=53000.0),
        dict(month_key=201112, month_label="2011-12", is_complete_month=0,
             active_customers=210, orders_per_customer=1.4, units_per_order=30.0,
             avg_unit_price=4.90, return_rate_identified=0.060,
             net_revenue=61000.0, net_revenue_identified=49000.0,
             net_revenue_guest=12000.0),
    ]
    return analysis.factor_frame(pd.DataFrame(rows))


class PeriodSelectionTests(unittest.TestCase):
    def test_incomplete_month_is_never_selected(self):
        pair = analysis.resolve_periods(monthly_frame(), MiniConfig())
        self.assertEqual(pair.current.month_key, 201111)
        self.assertTrue(pair.current.is_complete)

    def test_year_over_year_comparison_is_twelve_months_back(self):
        pair = analysis.resolve_periods(monthly_frame(), MiniConfig())
        self.assertEqual(pair.comparison.month_key, 201011)
        self.assertEqual(pair.mode, "yoy")

    def test_explicit_period_is_honoured(self):
        pair = analysis.resolve_periods(
            monthly_frame(), MiniConfig(**{"analysis.current_period": 201112})
        )
        self.assertEqual(pair.current.month_key, 201112)
        self.assertFalse(pair.current.is_complete)

    def test_unknown_period_fails_loudly(self):
        with self.assertRaises(ValueError):
            analysis.resolve_periods(
                monthly_frame(), MiniConfig(**{"analysis.current_period": 209901})
            )

    def test_month_shift_crosses_year_boundaries(self):
        self.assertEqual(analysis.shift_month(201101, -1), 201012)
        self.assertEqual(analysis.shift_month(201012, 1), 201101)
        self.assertEqual(analysis.shift_month(201111, -12), 201011)
        self.assertEqual(analysis.shift_month(201001, -12), 200901)


class DecompositionTests(unittest.TestCase):
    def setUp(self) -> None:
        df = monthly_frame()
        self.cur = df[df["month_key"] == 201111].iloc[0]
        self.cmp = df[df["month_key"] == 201011].iloc[0]
        self.delta = float(self.cur["kpi_tree_value"] - self.cmp["kpi_tree_value"])

    def test_kpi_tree_multiplies_out_to_reported_revenue(self):
        """The five factors must reproduce net revenue, not approximate it."""
        for row in (self.cur, self.cmp):
            self.assertAlmostEqual(
                float(row["kpi_tree_value"]),
                float(row["net_revenue_identified"]),
                delta=0.02 * float(row["net_revenue_identified"]),
            )

    def test_lmdi_contributions_sum_to_the_actual_change(self):
        result = analysis.lmdi(self.cur, self.cmp)
        self.assertAlmostEqual(float(result["contribution"].sum()), self.delta, places=1)

    def test_chain_substitution_also_sums_to_the_actual_change(self):
        result = analysis.chain_substitution(self.cur, self.cmp)
        self.assertAlmostEqual(float(result["contribution"].sum()), self.delta, places=1)

    def test_the_two_methods_disagree_only_on_allocation(self):
        a = analysis.lmdi(self.cur, self.cmp)["contribution"].sum()
        b = analysis.chain_substitution(self.cur, self.cmp)["contribution"].sum()
        self.assertAlmostEqual(float(a), float(b), places=1)

    def test_lmdi_covers_every_declared_factor(self):
        result = analysis.lmdi(self.cur, self.cmp)
        self.assertEqual(list(result["factor"]), [f[0] for f in analysis.FACTORS])

    def test_rising_returns_reduce_revenue(self):
        result = analysis.lmdi(self.cur, self.cmp)
        retained = result[result["factor"] == "revenue_retained"].iloc[0]
        self.assertLess(float(retained["contribution"]), 0.0)

    def test_shares_sum_to_one_hundred_percent(self):
        result = analysis.lmdi(self.cur, self.cmp)
        self.assertAlmostEqual(float(result["share_of_change_pct"].sum()), 100.0, places=0)

    def test_non_positive_totals_are_rejected_rather_than_fudged(self):
        broken = self.cur.copy()
        broken["kpi_tree_value"] = 0.0
        with self.assertRaises(ValueError):
            analysis.lmdi(broken, self.cmp)

    def test_guest_bridge_reconciles_to_total_revenue(self):
        bridge = analysis.guest_bridge(self.cur, self.cmp)
        rebuilt = (
            bridge["identified_delta"] + bridge["guest_delta"]
        )
        self.assertAlmostEqual(rebuilt, bridge["net_revenue_delta"], places=2)


class ConfigTests(unittest.TestCase):
    def test_shipped_config_declares_everything_the_code_reads(self):
        cfg = Config.load()
        for key in (
            "project.currency", "source.url", "source.sample_csv",
            "warehouse.engine", "business_rules.guest_customer_key",
            "business_rules.cancellation_prefix", "analysis.current_period",
            "analysis.comparison_mode", "output.dashboard_file",
            "output.findings_file",
        ):
            self.assertIsNotNone(cfg.get(key), f"missing config key: {key}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
