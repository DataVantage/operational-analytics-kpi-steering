"""Root cause analysis: which factor moved the number, and by how much.

The core of this module is a **driver decomposition**. A management question
of the form "why is net revenue down" is only answerable if the headline can be
split into factors whose contributions add back up to the headline change,
exactly. Two standard methods are implemented:

**LMDI-I** (logarithmic mean Divisia index) - the reported method. It is
*order independent*: no factor is privileged by being decomposed first, and the
contributions sum to the total change with no unexplained residual.

**Chain substitution** (Kettensubstitution) - the cross-check. It is the method
most German controlling departments recognise on sight, but it is order
dependent, so it is shown as an appendix rather than as the headline.

Both are asserted against the actual delta in the test suite. A decomposition
that does not add up is worse than no decomposition, because it looks precise.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# The KPI tree. net revenue = product of these five factors.
#   customers x orders/customer x units/order x price/unit x (1 - return rate)
FACTORS = [
    ("active_customers", "Active customers", "How many identified customers bought at all"),
    ("orders_per_customer", "Orders per customer", "How often each buying customer ordered"),
    ("units_per_order", "Units per order", "Basket size in units"),
    ("avg_unit_price", "Average unit price", "Realised price per unit, mix included"),
    ("revenue_retained", "Return retention", "Share of gross revenue not lost to returns"),
]


@dataclass
class Period:
    month_key: int
    label: str
    is_complete: bool


@dataclass
class PeriodPair:
    current: Period
    comparison: Period
    mode: str

    def as_dict(self) -> dict:
        return {
            "current": asdict(self.current),
            "comparison": asdict(self.comparison),
            "mode": self.mode,
        }


# ---------------------------------------------------------------------------
# period selection
# ---------------------------------------------------------------------------

def resolve_periods(kpi_monthly: pd.DataFrame, cfg) -> PeriodPair:
    """Pick the reporting month and its comparison month.

    Defaults to the most recent *complete* month. Comparing a part-month
    against a full one is the single most common way a monthly report ends up
    reporting a collapse that is really a calendar artefact, so incomplete
    months are excluded from selection by default rather than by convention.
    """
    df = kpi_monthly.sort_values("month_key")
    complete = df[df["is_complete_month"] == 1]
    pool = complete if len(complete) else df
    if not len(complete):
        log.warning("No complete month found; falling back to the last observed month.")

    requested = cfg.get("analysis.current_period", "auto")
    if requested in (None, "auto"):
        current_row = pool.iloc[-1]
    else:
        match = df[df["month_key"] == int(requested)]
        if not len(match):
            raise ValueError(f"Configured analysis.current_period={requested} is not in the data.")
        current_row = match.iloc[0]

    mode = cfg.get("analysis.comparison_mode", "yoy")
    target = _shift_month(int(current_row["month_key"]), -12 if mode == "yoy" else -1)
    match = df[df["month_key"] == target]
    if not len(match):
        fallback = _shift_month(int(current_row["month_key"]), -1)
        match = df[df["month_key"] == fallback]
        if not len(match):
            raise ValueError("No usable comparison month exists in the data.")
        log.warning("No %s comparison month available; using the prior month instead.", mode)
        mode = "pop"
    comparison_row = match.iloc[0]

    pair = PeriodPair(
        current=Period(int(current_row["month_key"]), str(current_row["month_label"]),
                       bool(current_row["is_complete_month"])),
        comparison=Period(int(comparison_row["month_key"]), str(comparison_row["month_label"]),
                          bool(comparison_row["is_complete_month"])),
        mode=mode,
    )
    log.info("Reporting period %s vs %s (%s)", pair.current.label, pair.comparison.label, mode)
    return pair


def shift_month(month_key: int, months: int) -> int:
    """Move a YYYYMM key by a number of months, without date arithmetic."""
    year, month = divmod(month_key, 100)
    index = year * 12 + (month - 1) + months
    return (index // 12) * 100 + (index % 12) + 1


# Backwards-compatible private alias used inside this module.
_shift_month = shift_month


# ---------------------------------------------------------------------------
# factor extraction
# ---------------------------------------------------------------------------

def factor_frame(kpi_monthly: pd.DataFrame) -> pd.DataFrame:
    """Add the derived 'revenue retained' factor and the tree's own product.

    ``kpi_tree_value`` is the product of the five factors. It must equal
    ``net_revenue_identified``; the gap is reported as ``kpi_tree_residual``
    and is expected to be pure floating point noise.
    """
    df = kpi_monthly.copy()
    df["revenue_retained"] = 1.0 - df["return_rate_identified"].fillna(0.0)
    df["kpi_tree_value"] = (
        df["active_customers"]
        * df["orders_per_customer"]
        * df["units_per_order"]
        * df["avg_unit_price"]
        * df["revenue_retained"]
    )
    df["kpi_tree_residual"] = df["net_revenue_identified"] - df["kpi_tree_value"]
    return df


# ---------------------------------------------------------------------------
# decomposition
# ---------------------------------------------------------------------------

def _lmdi_weight(v1: float, v0: float) -> float:
    """Logarithmic mean of the two totals - the LMDI-I weight."""
    if v1 <= 0 or v0 <= 0:
        raise ValueError("LMDI requires strictly positive totals in both periods.")
    if math.isclose(v1, v0, rel_tol=1e-12):
        return v1
    return (v1 - v0) / (math.log(v1) - math.log(v0))


def lmdi(current: pd.Series, comparison: pd.Series) -> pd.DataFrame:
    """Additive LMDI-I decomposition of the change in the KPI tree value."""
    v1 = float(current["kpi_tree_value"])
    v0 = float(comparison["kpi_tree_value"])
    weight = _lmdi_weight(v1, v0)

    rows = []
    for key, label, meaning in FACTORS:
        x1, x0 = float(current[key]), float(comparison[key])
        if x1 <= 0 or x0 <= 0:
            raise ValueError(f"Factor '{key}' is not strictly positive in both periods.")
        contribution = weight * math.log(x1 / x0)
        rows.append(
            {
                "factor": key,
                "label": label,
                "meaning": meaning,
                "value_comparison": round(x0, 6),
                "value_current": round(x1, 6),
                "change_pct": round(100.0 * (x1 / x0 - 1.0), 2),
                "contribution": round(contribution, 2),
            }
        )

    out = pd.DataFrame(rows)
    total_change = v1 - v0
    out["share_of_change_pct"] = (
        (100.0 * out["contribution"] / total_change).round(2) if total_change else np.nan
    )
    residual = total_change - out["contribution"].sum()
    log.info("LMDI residual: %.6f (target 0)", residual)
    return out


def chain_substitution(current: pd.Series, comparison: pd.Series) -> pd.DataFrame:
    """Sequential substitution, in the order the factors are listed.

    Included as a cross-check and because it is the method most controlling
    teams already use. It is order dependent by construction: the factor
    substituted first absorbs the interaction terms.
    """
    keys = [k for k, _, _ in FACTORS]
    baseline = [float(comparison[k]) for k in keys]
    rows = []
    running = baseline[:]
    previous = float(np.prod(running))
    for i, (key, label, _) in enumerate(FACTORS):
        running[i] = float(current[key])
        value = float(np.prod(running))
        rows.append({"factor": key, "label": label, "contribution": round(value - previous, 2)})
        previous = value
    return pd.DataFrame(rows)


def guest_bridge(current: pd.Series, comparison: pd.Series) -> dict:
    """Reconcile the identified-customer tree back to total net revenue.

    total delta = decomposed identified delta + guest delta + tree residual
    """
    return {
        "net_revenue_current": round(float(current["net_revenue"]), 2),
        "net_revenue_comparison": round(float(comparison["net_revenue"]), 2),
        "net_revenue_delta": round(float(current["net_revenue"] - comparison["net_revenue"]), 2),
        "identified_delta": round(
            float(current["net_revenue_identified"] - comparison["net_revenue_identified"]), 2
        ),
        "guest_delta": round(
            float(current["net_revenue_guest"] - comparison["net_revenue_guest"]), 2
        ),
        "tree_residual": round(
            float(current["kpi_tree_residual"] - comparison["kpi_tree_residual"]), 2
        ),
    }


# ---------------------------------------------------------------------------
# supporting diagnostics
# ---------------------------------------------------------------------------

def retention_summary(cohort: pd.DataFrame, horizon: int = 3) -> pd.DataFrame:
    """Share of each cohort still active *horizon* months after acquisition."""
    at_horizon = cohort[cohort["months_since_first_order"] == horizon]
    return (
        at_horizon[["cohort_month_key", "cohort_customers", "active_customers", "retention_pct"]]
        .sort_values("cohort_month_key")
        .reset_index(drop=True)
    )


def concentration_summary(conc: pd.DataFrame, buckets=(10, 20, 50)) -> pd.DataFrame:
    """Revenue share carried by the top N accounts."""
    rows = []
    total = conc["net_revenue"].sum()
    for n in buckets:
        head = conc.nsmallest(n, "revenue_rank")
        rows.append(
            {
                "bucket": f"Top {n} accounts",
                "customers": int(min(n, len(conc))),
                "net_revenue": round(float(head["net_revenue"].sum()), 2),
                "share_of_net_revenue_pct": round(
                    100.0 * float(head["net_revenue"].sum()) / total, 2
                ) if total else 0.0,
            }
        )
    return pd.DataFrame(rows)


def rank_movements(products: pd.DataFrame, top_n: int = 10) -> dict[str, pd.DataFrame]:
    """The products that lost and gained the most net revenue."""
    sellable = products[products["is_non_product"] == 0]
    cols = [
        "stock_code", "description", "product_family", "net_revenue_cmp",
        "net_revenue_cur", "net_revenue_delta", "return_rate_cur_pct", "return_rate_cmp_pct",
    ]
    return {
        "decliners": sellable.nsmallest(top_n, "net_revenue_delta")[cols].reset_index(drop=True),
        "growers": sellable.nlargest(top_n, "net_revenue_delta")[cols].reset_index(drop=True),
    }
