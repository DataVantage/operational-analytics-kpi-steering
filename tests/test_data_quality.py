"""Tests for the data quality rule engine.

These are written against a hand-built frame with defects placed on purpose,
so that a failure points at a specific rule rather than at "something in the
pipeline". Written with :mod:`unittest` so they run under ``python -m
unittest`` with no third-party dependency; ``pytest`` collects them too.
"""

from __future__ import annotations

import unittest

import pandas as pd

from oakpi import dq
from oakpi.config import Config, load_dq_rules

RULES = load_dq_rules()
CFG = Config.load()


def frame() -> pd.DataFrame:
    """Eleven rows, each defect placed deliberately."""
    rows = [
        # clean baseline
        dict(invoice_no="1001", stock_code="20001", description="RED MUG",
             quantity=5, unit_price=2.5, customer_id=1, country="United Kingdom"),
        # DQ001 no invoice id -> quarantine
        dict(invoice_no=None, stock_code="20001", description="RED MUG",
             quantity=5, unit_price=2.5, customer_id=1, country="United Kingdom"),
        # DQ004 zero quantity -> quarantine
        dict(invoice_no="1003", stock_code="20001", description="RED MUG",
             quantity=0, unit_price=2.5, customer_id=1, country="United Kingdom"),
        # DQ005 negative price -> quarantine
        dict(invoice_no="1004", stock_code="20001", description="RED MUG",
             quantity=3, unit_price=-9.0, customer_id=1, country="United Kingdom"),
        # DQ006 zero price on a sellable product -> flag only
        dict(invoice_no="1005", stock_code="20001", description="RED MUG",
             quantity=3, unit_price=0.0, customer_id=1, country="United Kingdom"),
        # DQ007 no customer id -> flag only, revenue must survive
        dict(invoice_no="1006", stock_code="20001", description="RED MUG",
             quantity=3, unit_price=2.5, customer_id=None, country="United Kingdom"),
        # DQ008 implausible quantity -> flag only
        dict(invoice_no="1007", stock_code="20001", description="RED MUG",
             quantity=99999, unit_price=0.4, customer_id=1, country="United Kingdom"),
        # DQ011 cancellation prefix with a positive quantity -> flag
        dict(invoice_no="C1008", stock_code="20001", description="RED MUG",
             quantity=4, unit_price=2.5, customer_id=1, country="United Kingdom"),
        # DQ012 missing description -> repaired from the stock code
        dict(invoice_no="1009", stock_code="20001", description=None,
             quantity=2, unit_price=2.5, customer_id=1, country="United Kingdom"),
        # DQ013 casing and whitespace noise -> normalised
        dict(invoice_no="1010", stock_code="20001", description="red mug  ",
             quantity=2, unit_price=2.5, customer_id=1, country="United Kingdom"),
        # DQ010 exact duplicate of row 0 -> quarantine
        dict(invoice_no="1001", stock_code="20001", description="RED MUG",
             quantity=5, unit_price=2.5, customer_id=1, country="United Kingdom"),
    ]
    df = pd.DataFrame(rows)
    df["invoice_ts"] = pd.Timestamp("2011-11-15 10:00")
    df["source_sheet"] = "test"
    df.insert(0, "source_row_id", range(1, len(df) + 1))
    df["customer_id"] = df["customer_id"].astype("Int64")
    for col in ("invoice_no", "stock_code", "description", "country"):
        df[col] = df[col].astype("string")
    return df


class DataQualityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.result = dq.run(frame(), RULES, CFG)

    # -- the guarantee the whole layer rests on ---------------------------
    def test_no_row_disappears_without_a_reason(self):
        self.assertEqual(
            len(self.result.clean) + len(self.result.quarantine),
            self.result.rows_in,
            "rows must be either clean or quarantined, never silently dropped",
        )
        self.assertTrue(
            self.result.quarantine["quarantine_rule_id"].notna().all(),
            "every quarantined row must name the rule that removed it",
        )

    def test_quarantined_rules_are_the_expected_ones(self):
        fired = set(self.result.quarantine["quarantine_rule_id"])
        self.assertEqual(fired, {"DQ001", "DQ004", "DQ005", "DQ010"})

    # -- flags keep revenue, they do not remove it ------------------------
    def test_missing_customer_id_is_flagged_not_removed(self):
        guests = self.result.clean[self.result.clean["is_guest_customer"]]
        self.assertEqual(len(guests), 1)
        self.assertEqual(float(guests["unit_price"].iat[0]), 2.5)

    def test_outliers_are_flagged_not_removed(self):
        self.assertEqual(int(self.result.clean["is_quantity_outlier"].sum()), 1)
        self.assertIn(99999, self.result.clean["quantity"].tolist())

    def test_inconsistent_cancellation_is_flagged(self):
        self.assertEqual(int(self.result.clean["is_inconsistent_cancellation"].sum()), 1)

    def test_zero_price_product_line_is_flagged_not_removed(self):
        self.assertEqual(int(self.result.clean["is_zero_price"].sum()), 1)

    # -- fixes are applied, and applied deterministically ------------------
    def test_missing_description_is_filled_from_the_stock_code(self):
        row = self.result.clean[self.result.clean["source_row_id"] == 9]
        self.assertEqual(row["description"].iat[0], "RED MUG")

    def test_description_is_normalised(self):
        row = self.result.clean[self.result.clean["source_row_id"] == 10]
        self.assertEqual(row["description"].iat[0], "RED MUG")

    # -- the score ---------------------------------------------------------
    def test_score_is_bounded_and_penalises_defects(self):
        self.assertLess(self.result.score, 100.0)
        self.assertGreater(self.result.score, 0.0)

    def test_clean_input_scores_one_hundred(self):
        clean_only = frame().head(1)
        self.assertEqual(dq.run(clean_only, RULES, CFG).score, 100.0)

    # -- the report is complete -------------------------------------------
    def test_every_configured_rule_appears_in_the_report(self):
        self.assertEqual(
            sorted(self.result.report["rule_id"]),
            sorted(r["id"] for r in RULES),
        )

    def test_every_rule_carries_a_written_rationale(self):
        self.assertTrue((self.result.report["rationale"].str.len() > 20).all())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
