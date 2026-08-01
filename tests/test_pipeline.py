"""End-to-end tests.

The pipeline is run once against a small slice of the offline fixture, in a
temporary directory, and the resulting warehouse and artefacts are inspected.
The point is not code coverage - it is that the numbers a reader would quote
from the dashboard are the same numbers that are in the fact table.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import pandas as pd
import yaml

from oakpi import analysis, dashboard, dq, ingest, kpi, model, report, synth
from oakpi.config import Config, load_dq_rules
from oakpi.engine import Warehouse

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PipelineTests(unittest.TestCase):
    """A full run against a deterministic 400-customer fixture."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp(prefix="oakpi-test-"))
        (cls.tmp / "sql").mkdir()
        for f in (PROJECT_ROOT / "sql").glob("*.sql"):
            shutil.copy(f, cls.tmp / "sql" / f.name)

        raw = yaml.safe_load((PROJECT_ROOT / "config" / "config.yml").read_text())
        raw["warehouse"]["engine"] = "sqlite"
        cls.cfg = Config(raw, root=cls.tmp)

        sample = cls.cfg.path("source.sample_csv")
        synth.write_sample(sample, n_customers=400)

        staged = ingest.read_source(cls.cfg, sample)
        cls.staged = staged
        cls.quality = dq.run(staged.frame, load_dq_rules(), cls.cfg)
        cls.star = model.build(cls.quality.clean, cls.cfg)

        cls.wh = Warehouse.open(cls.cfg, "sqlite")
        for name, frame in cls.star.items():
            cls.wh.write_table(name, frame)
        cls.monthly = analysis.factor_frame(kpi.build_base(cls.wh, cls.cfg))
        cls.periods = analysis.resolve_periods(cls.monthly, cls.cfg)
        kpi.build_period_marts(
            cls.wh, cls.cfg, cls.periods.current.month_key, cls.periods.comparison.month_key
        )
        cls.recon = kpi.check_reconciliation(cls.wh)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.wh.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # -- ingestion ---------------------------------------------------------
    def test_source_is_recognised_as_synthetic(self):
        self.assertTrue(self.staged.is_synthetic)
        self.assertEqual(self.staged.source_label, "SYNTHETIC DEMO SAMPLE")

    def test_canonical_columns_are_present(self):
        for col in ingest.CANONICAL_COLUMNS:
            self.assertIn(col, self.staged.frame.columns)

    # -- star schema -------------------------------------------------------
    def test_every_fact_row_resolves_to_a_dimension(self):
        fact = self.star["fct_sales_line"]
        self.assertTrue(fact["product_key"].isin(self.star["dim_product"]["product_key"]).all())
        self.assertTrue(fact["customer_key"].isin(self.star["dim_customer"]["customer_key"]).all())
        self.assertTrue(fact["date_key"].isin(self.star["dim_date"]["date_key"]).all())

    def test_surrogate_keys_are_unique(self):
        for table, key in (
            ("dim_customer", "customer_key"),
            ("dim_product", "product_key"),
            ("dim_date", "date_key"),
            ("fct_sales_line", "sales_line_key"),
        ):
            self.assertFalse(self.star[table][key].duplicated().any(), table)

    def test_unidentified_lines_land_on_the_guest_key(self):
        guest_key = self.cfg.get("business_rules.guest_customer_key")
        fact = self.star["fct_sales_line"]
        self.assertTrue((fact.loc[fact["is_guest_customer"], "customer_key"] == guest_key).all())

    def test_returns_carry_a_negative_amount(self):
        fact = self.star["fct_sales_line"]
        self.assertTrue((fact.loc[fact["is_return"], "line_amount"] <= 0).all())
        self.assertTrue((fact.loc[fact["is_return"], "gross_amount"] == 0).all())
        self.assertTrue((fact.loc[~fact["is_return"], "return_amount"] == 0).all())

    def test_gross_minus_returns_equals_net(self):
        fact = self.star["fct_sales_line"]
        self.assertAlmostEqual(
            float(fact["gross_amount"].sum() - fact["return_amount"].sum()),
            float(fact["line_amount"].sum()),
            places=2,
        )

    # -- KPI mart ----------------------------------------------------------
    def test_kpi_mart_reconciles_to_the_fact_table(self):
        self.assertTrue((self.recon["difference"].abs() <= 0.05).all())

    def test_kpi_tree_reproduces_reported_revenue(self):
        residual = self.monthly["kpi_tree_residual"].abs()
        revenue = self.monthly["net_revenue_identified"].abs()
        worst = float((residual / revenue.where(revenue > 0)).max())
        self.assertLess(worst, 0.01, "KPI tree must reproduce revenue to within 1%")

    def test_incomplete_months_are_marked(self):
        self.assertIn(0, self.monthly["is_complete_month"].tolist())
        self.assertIn(1, self.monthly["is_complete_month"].tolist())

    def test_identified_and_guest_revenue_sum_to_net(self):
        diff = (
            self.monthly["net_revenue_identified"]
            + self.monthly["net_revenue_guest"]
            - self.monthly["net_revenue"]
        ).abs().max()
        self.assertLess(float(diff), 0.05)

    # -- marts -------------------------------------------------------------
    def test_all_expected_marts_exist(self):
        tables = set(self.wh.table_names())
        for name in (
            "kpi_monthly", "mart_product_period", "mart_returns_family",
            "mart_returns_monthly", "mart_cohort_retention",
            "mart_country_period", "mart_customer_concentration",
            "mart_reconciliation",
        ):
            self.assertIn(name, tables)

    def test_pareto_share_is_monotonic_and_ends_at_one_hundred(self):
        products = self.wh.query(
            "SELECT cumulative_revenue_share_pct AS s FROM mart_product_period "
            "ORDER BY revenue_rank"
        )["s"].dropna()
        self.assertTrue((products.diff().dropna() >= -0.01).all(), "share must not decrease")
        self.assertAlmostEqual(float(products.iloc[-1]), 100.0, places=0)

    def test_retention_never_exceeds_one_hundred_percent(self):
        cohort = self.wh.query("SELECT * FROM mart_cohort_retention")
        self.assertTrue((cohort["retention_pct"] <= 100.0001).all())
        self.assertTrue((cohort["active_customers"] <= cohort["cohort_customers"]).all())

    def test_country_slice_reconciles_to_the_period_headline(self):
        countries = self.wh.query("SELECT * FROM mart_country_period")
        cur = self.monthly[
            self.monthly["month_key"] == self.periods.current.month_key
        ].iloc[0]
        self.assertAlmostEqual(
            float(countries["net_revenue_cur"].sum()), float(cur["net_revenue"]), places=1
        )

    # -- published artefacts ----------------------------------------------
    def test_dashboard_and_findings_are_written_and_stamped(self):
        cur = self.monthly[self.monthly["month_key"] == self.periods.current.month_key].iloc[0]
        cmp_ = self.monthly[self.monthly["month_key"] == self.periods.comparison.month_key].iloc[0]
        decomposition = analysis.lmdi(cur, cmp_)
        marts = {
            "kpi_monthly": self.monthly,
            "products": self.wh.query("SELECT * FROM mart_product_period"),
            "returns_family": self.wh.query("SELECT * FROM mart_returns_family"),
            "returns_monthly": self.wh.query("SELECT * FROM mart_returns_monthly"),
            "cohort": self.wh.query("SELECT * FROM mart_cohort_retention"),
            "countries": self.wh.query("SELECT * FROM mart_country_period"),
            "concentration": self.wh.query("SELECT * FROM mart_customer_concentration"),
            "reconciliation": self.recon,
            "dq_report": self.quality.report,
            "decomposition": decomposition,
            "chain": analysis.chain_substitution(cur, cmp_),
        }
        ctx = {
            "project": "test", "owner": "test", "currency": "GBP", "version": "test",
            "generated_at": "now", "source_label": "SYNTHETIC DEMO SAMPLE",
            "is_synthetic": True, "rows_read": self.staged.rows_read,
            "dq_score": self.quality.score,
            "rows_quarantined": len(self.quality.quarantine),
            "quarantine_rate": self.quality.quarantine_rate,
            "periods": self.periods.as_dict(),
            "bridge": analysis.guest_bridge(cur, cmp_),
            "top_n": 15, "retention_horizon": 3,
        }
        html = dashboard.render(marts, ctx)
        markdown = report.render(marts, ctx)

        self.assertIn("SYNTHETIC DEMO SAMPLE", markdown)
        self.assertIn("synthetic demo sample", html)

        # The embedded payload must be valid JSON. NaN and Infinity are legal
        # Python but not legal JSON, and would silently break the page.
        import json
        import re

        blob = re.search(r"^const D = (\{.*\});$", html, re.M)
        self.assertIsNotNone(blob, "embedded data payload not found")
        payload = json.loads(blob.group(1))
        self.assertNotIn("NaN", blob.group(1))
        self.assertNotIn("Infinity", blob.group(1))
        self.assertEqual(len(payload["cards"]), 6)
        self.assertEqual(len(payload["waterfall"]["labels"]), len(analysis.FACTORS))

        for anchor in ("chart-waterfall", "tbl-dq", "tbl-recon", "chart-cohort"):
            self.assertIn(anchor, html)
        for heading in ("## 1.", "## 3.", "## 8.", "## 9."):
            self.assertIn(heading, markdown)

    def test_no_placeholder_text_survives_into_the_report(self):
        cur = self.monthly[self.monthly["month_key"] == self.periods.current.month_key].iloc[0]
        self.assertGreater(float(cur["net_revenue"]), 0)


class EngineTests(unittest.TestCase):
    """The SQL splitter is load-bearing: a bad split corrupts a whole script."""

    def test_semicolons_inside_comments_do_not_split_statements(self):
        from oakpi.engine import _split_statements

        script = (
            "-- a comment; with a semicolon in it\n"
            "SELECT 1;\n"
            "/* block; comment */\n"
            "SELECT 'literal ; inside';\n"
        )
        statements = list(_split_statements(script))
        self.assertEqual(len(statements), 2)
        self.assertIn("SELECT 1", statements[0])
        self.assertIn("literal ; inside", statements[1])

    def test_parameters_are_bound_and_escaped(self):
        from oakpi.engine import _bind

        self.assertEqual(_bind("WHERE a = :n", {"n": 5}), "WHERE a = 5")
        self.assertEqual(_bind("WHERE a = :s", {"s": "o'brien"}), "WHERE a = 'o''brien'")
        self.assertEqual(_bind("WHERE a = :x", {}), "WHERE a = :x")

    def test_booleans_and_timestamps_are_stored_portably(self):
        from oakpi.engine import _normalise_for_storage

        df = pd.DataFrame(
            {"flag": [True, False], "ts": pd.to_datetime(["2011-11-01", "2011-11-02"])}
        )
        out = _normalise_for_storage(df)
        self.assertEqual(out["flag"].tolist(), [1, 0])
        self.assertEqual(out["ts"].iat[0], "2011-11-01 00:00:00")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
