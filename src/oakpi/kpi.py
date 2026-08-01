"""Execution of the SQL layer.

The analytical logic lives in ``sql/`` as plain, reviewable statements. This
module only decides *which* scripts run, in what order, and with which
parameters. Keeping orchestration and logic apart means the SQL can be lifted
into dbt, a scheduler, or a Power BI dataflow without rewriting it.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

# Scripts that only need the star schema.
STRUCTURE_SCRIPTS = ["00_indexes.sql"]
BASE_SCRIPTS = ["10_kpi_monthly.sql"]
# Scripts that need a resolved reporting period.
PERIOD_SCRIPTS = [
    "11_product_performance.sql",
    "12_returns_by_family.sql",
    "13_cohort_retention.sql",
    "14_country_performance.sql",
    "15_customer_concentration.sql",
]
FINAL_SCRIPTS = ["16_reconciliation.sql"]


def sql_dir(cfg) -> Path:
    return cfg.root / "sql"


def _run(warehouse, cfg, scripts: list[str], params: dict) -> None:
    for name in scripts:
        path = sql_dir(cfg) / name
        log.info("Running %s", name)
        warehouse.execute_script(path.read_text(encoding="utf-8"), params)


def build_base(warehouse, cfg) -> pd.DataFrame:
    """Create indexes and the monthly KPI mart."""
    params = {"guest_key": cfg.get("business_rules.guest_customer_key", -1)}
    _run(warehouse, cfg, STRUCTURE_SCRIPTS + BASE_SCRIPTS, params)
    return warehouse.query("SELECT * FROM kpi_monthly ORDER BY month_key")


def build_period_marts(warehouse, cfg, current_key: int, comparison_key: int) -> None:
    params = {
        "guest_key": cfg.get("business_rules.guest_customer_key", -1),
        "current_month_key": current_key,
        "comparison_month_key": comparison_key,
        "min_revenue": cfg.get("analysis.min_revenue_for_return_rate", 0),
    }
    _run(warehouse, cfg, PERIOD_SCRIPTS + FINAL_SCRIPTS, params)


def check_reconciliation(warehouse, tolerance: float = 0.05) -> pd.DataFrame:
    """Fail loudly when the fact table and the KPI mart disagree."""
    recon = warehouse.query("SELECT * FROM mart_reconciliation")
    breaches = recon[recon["difference"].abs() > tolerance]
    if len(breaches):
        raise AssertionError(
            "Reconciliation failed. The KPI mart does not tie back to the fact "
            f"table:\n{breaches.to_string(index=False)}"
        )
    log.info("Reconciliation passed for %d checks", len(recon))
    return recon
