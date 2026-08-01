"""Acquisition and staging.

Responsibilities
----------------
1. Locate a source: the real UCI workbook if it is present, otherwise the
   committed sample.
2. Rename the source columns to stable, snake_case names so that nothing
   downstream depends on the vendor's spelling.
3. Coerce types once, in one place, recording *how many* values failed to
   coerce rather than dropping them quietly.

Nothing is filtered here. Deciding what to keep is the data quality layer's
job, and keeping the two apart is what makes the quality report honest.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

# Vendor spelling -> canonical name. The workbook and the 2019 CSV release of
# the same data disagree on two of these, so both spellings are mapped.
COLUMN_MAP = {
    "Invoice": "invoice_no",
    "InvoiceNo": "invoice_no",
    "StockCode": "stock_code",
    "Description": "description",
    "Quantity": "quantity",
    "InvoiceDate": "invoice_ts",
    "Price": "unit_price",
    "UnitPrice": "unit_price",
    "Customer ID": "customer_id",
    "CustomerID": "customer_id",
    "Country": "country",
}

CANONICAL_COLUMNS = [
    "invoice_no", "stock_code", "description", "quantity",
    "invoice_ts", "unit_price", "customer_id", "country",
]


@dataclass
class IngestResult:
    frame: pd.DataFrame
    source_label: str
    is_synthetic: bool
    rows_read: int
    coercion_failures: dict[str, int] = field(default_factory=dict)


def resolve_source(cfg) -> tuple[Path, bool]:
    """Prefer the real workbook; fall back to the committed sample.

    Returns ``(path, is_synthetic)``.
    """
    workbook = cfg.path("source.raw_dir") / cfg.get("source.excel_file")
    if workbook.exists():
        return workbook, False

    for candidate in sorted(cfg.path("source.raw_dir").glob("*.csv*")):
        return candidate, False

    sample = cfg.path("source.sample_csv")
    if sample.exists():
        return sample, True

    raise FileNotFoundError(
        "No source data found.\n"
        f"  Expected the UCI workbook at: {workbook}\n"
        f"  or the offline sample at:     {sample}\n"
        "Run `make data` to download the real dataset, or `make sample` to "
        "regenerate the offline fixture."
    )


def is_sample(cfg, path: Path) -> bool:
    """Is this path the committed offline fixture rather than real data?

    Provenance has to survive an explicit ``--source`` override, otherwise a
    demo build could be published without its warning banner - which is exactly
    the failure this project is meant to make impossible.
    """
    try:
        return Path(path).resolve() == cfg.path("source.sample_csv").resolve()
    except OSError:  # pragma: no cover - unresolvable path
        return False


def read_source(cfg, path: Path | None = None) -> IngestResult:
    src, synthetic = (path, is_sample(cfg, path)) if path else resolve_source(cfg)
    log.info("Reading source: %s", src)

    if src.suffix.lower() in {".xlsx", ".xls"}:
        sheets = cfg.get("source.sheets") or None
        frames = []
        book = pd.read_excel(src, sheet_name=sheets)
        if isinstance(book, dict):
            for sheet_name, sheet in book.items():
                sheet = sheet.copy()
                sheet["source_sheet"] = sheet_name
                frames.append(sheet)
        else:
            book = book.copy()
            book["source_sheet"] = "sheet1"
            frames.append(book)
        raw = pd.concat(frames, ignore_index=True)
    else:
        raw = pd.read_csv(src, dtype=str, keep_default_na=True)
        raw["source_sheet"] = src.name

    rows_read = len(raw)
    frame, failures = _standardise(raw)
    label = "SYNTHETIC DEMO SAMPLE" if synthetic else f"{cfg.get('source.name')} ({src.name})"
    log.info("Staged %s rows from %s", f"{len(frame):,}", label)
    return IngestResult(frame, label, synthetic, rows_read, failures)


def _standardise(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    df = raw.rename(columns=COLUMN_MAP).copy()

    missing = [c for c in CANONICAL_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            f"Source is missing expected column(s): {missing}. "
            f"Columns found: {sorted(raw.columns)}"
        )

    failures: dict[str, int] = {}

    df["invoice_no"] = _clean_string(df["invoice_no"])
    df["stock_code"] = _clean_string(df["stock_code"]).str.upper()
    df["description"] = _clean_string(df["description"])
    df["country"] = _clean_string(df["country"])

    ts = pd.to_datetime(df["invoice_ts"], errors="coerce")
    failures["invoice_ts"] = int(ts.isna().sum() - df["invoice_ts"].isna().sum())
    df["invoice_ts"] = ts

    qty = pd.to_numeric(df["quantity"], errors="coerce")
    failures["quantity"] = int(qty.isna().sum() - df["quantity"].isna().sum())
    df["quantity"] = qty

    price = pd.to_numeric(df["unit_price"], errors="coerce")
    failures["unit_price"] = int(price.isna().sum() - df["unit_price"].isna().sum())
    df["unit_price"] = price

    cust = pd.to_numeric(df["customer_id"], errors="coerce")
    df["customer_id"] = cust.astype("Int64")

    df = df[CANONICAL_COLUMNS + ["source_sheet"]].copy()
    df.insert(0, "source_row_id", range(1, len(df) + 1))
    return df, {k: v for k, v in failures.items() if v}


def _clean_string(series: pd.Series) -> pd.Series:
    out = series.astype("string").str.strip()
    return out.mask(out.str.len() == 0)
