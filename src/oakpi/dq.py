"""Data quality layer.

The rules live in ``config/dq_rules.yml``; this module only knows how to
evaluate them. That separation is the point: a business analyst can review,
argue with, and change the rule set without touching Python, and every rule
carries a written rationale that ends up in the published report.

Three principles are enforced here:

1. **Nothing disappears silently.** Every excluded row lands in the
   ``quarantine`` table with the id of the rule that removed it.
2. **Fix, flag, quarantine are different decisions.** Removing rows is the
   last resort, not the default, because removal changes the revenue total.
3. **Quality is scored, not described.** A single weighted score makes the
   layer trendable and lets a threshold fail the build.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

SEVERITY_WEIGHT = {"blocker": 5, "major": 3, "minor": 1}

FLAG_COLUMNS = [
    "is_guest_customer",
    "is_zero_price",
    "is_quantity_outlier",
    "is_price_outlier",
    "is_inconsistent_cancellation",
]


@dataclass
class DQResult:
    clean: pd.DataFrame
    quarantine: pd.DataFrame
    report: pd.DataFrame
    score: float
    rows_in: int

    @property
    def rows_out(self) -> int:
        return len(self.clean)

    @property
    def quarantine_rate(self) -> float:
        return 100.0 * len(self.quarantine) / self.rows_in if self.rows_in else 0.0


def run(df: pd.DataFrame, rules: list[dict], cfg) -> DQResult:
    """Evaluate the full rule set and return clean, quarantined and report."""
    work = df.copy()
    rows_in = len(work)
    for col in FLAG_COLUMNS:
        work[col] = False

    records: list[dict] = []
    quarantine_reason = pd.Series([None] * len(work), index=work.index, dtype=object)

    # Fixes run first so that repaired rows are judged on their repaired value.
    ordered = sorted(rules, key=lambda r: {"fix": 0, "flag": 1, "quarantine": 2}[r["action"]])

    for rule in ordered:
        checked, failed_mask = _evaluate(work, rule, cfg)
        n_failed = int(failed_mask.sum())
        action = rule["action"]

        if action == "fix" and n_failed:
            work = _apply_fix(work, rule, failed_mask)
        elif action == "flag" and n_failed:
            work.loc[failed_mask, rule["flag_column"]] = True
        elif action == "quarantine" and n_failed:
            newly = failed_mask & quarantine_reason.isna()
            quarantine_reason.loc[newly] = rule["id"]

        records.append(
            {
                "rule_id": rule["id"],
                "name": rule["name"],
                "dimension": rule["dimension"],
                "severity": rule["severity"],
                "action": action,
                "weight": SEVERITY_WEIGHT[rule["severity"]],
                "rows_checked": int(checked),
                "rows_failed": n_failed,
                "fail_rate_pct": round(100.0 * n_failed / checked, 4) if checked else 0.0,
                "rationale": " ".join(str(rule.get("rationale", "")).split()),
            }
        )
        if n_failed:
            log.info("%s %-42s %6d rows -> %s", rule["id"], rule["name"], n_failed, action)

    report = pd.DataFrame(records).sort_values("rule_id").reset_index(drop=True)
    score = _score(report)

    quarantined_mask = quarantine_reason.notna()
    quarantine = work[quarantined_mask].copy()
    quarantine["quarantine_rule_id"] = quarantine_reason[quarantined_mask]
    clean = work[~quarantined_mask].copy().reset_index(drop=True)

    log.info(
        "Data quality score %.2f | %s rows in, %s clean, %s quarantined",
        score, f"{rows_in:,}", f"{len(clean):,}", f"{len(quarantine):,}",
    )
    return DQResult(clean, quarantine.reset_index(drop=True), report, score, rows_in)


# ---------------------------------------------------------------------------
# rule evaluation
# ---------------------------------------------------------------------------

def _threshold(rule: dict, cfg):
    if "value" in rule:
        return rule["value"]
    if "value_from" in rule:
        value = cfg.get(rule["value_from"])
        if value is None:
            raise KeyError(f"Rule {rule['id']} references missing config '{rule['value_from']}'")
        return value
    raise KeyError(f"Rule {rule['id']} needs 'value' or 'value_from'")


def _scope_mask(df: pd.DataFrame, rule: dict, cfg) -> pd.Series:
    """Restrict a rule to a subset of rows, e.g. sellable products only."""
    if rule.get("scope") != "product_lines_only":
        return pd.Series(True, index=df.index)
    non_product = {c.upper() for c in cfg.get("business_rules.non_product_stock_codes", [])}
    return ~df["stock_code"].astype("string").str.upper().isin(non_product).fillna(False)


def _evaluate(df: pd.DataFrame, rule: dict, cfg) -> tuple[int, pd.Series]:
    """Return ``(rows_checked, failed_mask)`` for one rule."""
    check = rule["check"]
    scope = _scope_mask(df, rule, cfg)

    if check == "duplicate_rows":
        failed = df.duplicated(subset=rule["key"], keep="first")
        return int(scope.sum()), failed & scope

    if check == "cancellation_consistency":
        prefix = cfg.get("business_rules.cancellation_prefix", "C")
        is_cancel = df["invoice_no"].astype("string").str.startswith(prefix).fillna(False)
        failed = is_cancel & (df["quantity"].fillna(0) > 0)
        return int(is_cancel.sum()), failed

    if check == "whitespace_and_case":
        col = df[rule["column"]].astype("string")
        normalised = col.str.strip().str.upper()
        failed = col.notna() & (col != normalised)
        return int(col.notna().sum()), failed.fillna(False)

    col = df[rule["column"]]
    checked = int(scope.sum())

    if check == "not_null":
        failed = col.isna()
    elif check == "not_equal":
        failed = col == _threshold(rule, cfg)
    elif check == "greater_equal":
        failed = col < _threshold(rule, cfg)
    elif check == "greater_than":
        failed = col <= _threshold(rule, cfg)
    elif check == "less_equal":
        failed = col > _threshold(rule, cfg)
    elif check == "abs_less_equal":
        failed = col.abs() > _threshold(rule, cfg)
    else:  # pragma: no cover - configuration error
        raise ValueError(f"Rule {rule['id']}: unknown check '{check}'")

    return checked, (failed.fillna(False) & scope)


def _apply_fix(df: pd.DataFrame, rule: dict, failed: pd.Series) -> pd.DataFrame:
    fix = rule["fix"]
    col = rule["column"]

    if fix == "trim_and_upper":
        df.loc[failed, col] = df.loc[failed, col].astype("string").str.strip().str.upper()
        return df

    if fix == "fill_from_stock_code_mode":
        known = df.loc[df[col].notna(), ["stock_code", col]]
        if len(known):
            mode = (
                known.groupby("stock_code")[col]
                .agg(lambda s: s.mode().iat[0] if not s.mode().empty else np.nan)
            )
            filled = df.loc[failed, "stock_code"].map(mode)
        else:  # pragma: no cover - degenerate input
            filled = pd.Series(np.nan, index=df.index[failed])
        df.loc[failed, col] = filled.fillna("UNKNOWN PRODUCT")
        return df

    raise ValueError(f"Rule {rule['id']}: unknown fix '{fix}'")  # pragma: no cover


def _score(report: pd.DataFrame) -> float:
    """Weighted share of checks passed, on a 0-100 scale.

    Weighting by severity means a thousand cosmetic casing issues cost less
    than a hundred rows with no invoice date, which is the behaviour a
    steering committee expects from a single headline number.
    """
    weighted_failed = float((report["rows_failed"] * report["weight"]).sum())
    weighted_total = float((report["rows_checked"] * report["weight"]).sum())
    if weighted_total == 0:
        return 100.0
    return round(100.0 * (1.0 - weighted_failed / weighted_total), 2)
