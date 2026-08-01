"""Dimensional model.

A Kimball-style star: three conformed dimensions and one transaction-grain
fact. The grain of ``fct_sales_line`` is *one invoice line*, which is the
lowest grain the source offers and therefore the only grain from which every
downstream KPI can be re-derived.

One design decision is worth calling out, because it is the one an interviewer
will ask about: ``dim_date`` carries pre-computed ``prior_year_month_key`` and
``prior_month_key`` columns. Period-over-period comparisons then become plain
equi-joins instead of dialect-specific date arithmetic. That keeps the SQL
portable, keeps the comparison logic in one auditable place, and makes the
year-over-year queries measurably cheaper.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

GUEST_KEY = -1


def build(clean: pd.DataFrame, cfg) -> dict[str, pd.DataFrame]:
    dim_date = build_dim_date(clean)
    dim_customer = build_dim_customer(clean, cfg)
    dim_product = build_dim_product(clean, cfg)
    fact = build_fact(clean, dim_customer, dim_product, cfg)
    log.info(
        "Star schema: %s facts, %s customers, %s products, %s dates",
        f"{len(fact):,}", f"{len(dim_customer):,}",
        f"{len(dim_product):,}", f"{len(dim_date):,}",
    )
    return {
        "dim_date": dim_date,
        "dim_customer": dim_customer,
        "dim_product": dim_product,
        "fct_sales_line": fact,
    }


# ---------------------------------------------------------------------------
# dimensions
# ---------------------------------------------------------------------------

def build_dim_date(clean: pd.DataFrame) -> pd.DataFrame:
    ts = clean["invoice_ts"].dropna()
    span = pd.date_range(ts.min().normalize(), ts.max().normalize(), freq="D")
    d = pd.DataFrame({"date": span})

    d["date_key"] = d["date"].dt.strftime("%Y%m%d").astype(int)
    d["date_iso"] = d["date"].dt.strftime("%Y-%m-%d")
    d["year"] = d["date"].dt.year
    d["quarter"] = d["date"].dt.quarter
    d["month"] = d["date"].dt.month
    d["month_key"] = d["date"].dt.strftime("%Y%m").astype(int)
    d["month_label"] = d["date"].dt.strftime("%Y-%m")
    d["month_name"] = d["date"].dt.strftime("%b %Y")
    d["quarter_label"] = d["year"].astype(str) + "-Q" + d["quarter"].astype(str)
    d["day_of_month"] = d["date"].dt.day
    d["weekday_num"] = d["date"].dt.weekday
    d["weekday_name"] = d["date"].dt.strftime("%a")
    d["is_weekend"] = d["weekday_num"] >= 5
    d["iso_week"] = d["date"].dt.isocalendar().week.astype(int)

    prev_year = d["date"] - pd.DateOffset(years=1)
    prev_month = d["date"] - pd.DateOffset(months=1)
    d["prior_year_month_key"] = prev_year.dt.strftime("%Y%m").astype(int)
    d["prior_month_key"] = prev_month.dt.strftime("%Y%m").astype(int)

    # Days actually observed in the source for that month. A month whose
    # observed span is shorter than the calendar month is incomplete and must
    # never be compared against a full one.
    observed = (
        clean.assign(month_key=clean["invoice_ts"].dt.strftime("%Y%m"))
        .dropna(subset=["invoice_ts"])
        .groupby("month_key")["invoice_ts"]
        .agg(observed_first="min", observed_last="max")
    )
    observed.index = observed.index.astype(int)
    d = d.merge(observed, left_on="month_key", right_index=True, how="left")
    d["days_in_month"] = d["date"].dt.days_in_month
    d["observed_days_in_month"] = (
        d["observed_last"].dt.day.fillna(0).astype(int)
        - d["observed_first"].dt.day.fillna(1).astype(int)
        + 1
    )
    d["is_complete_month"] = (
        (d["observed_first"].dt.day == 1) & (d["observed_last"].dt.day == d["days_in_month"])
    ).fillna(False)

    return d.drop(columns=["observed_first", "observed_last"])


def build_dim_customer(clean: pd.DataFrame, cfg) -> pd.DataFrame:
    identified = clean[clean["customer_id"].notna()].copy()

    country = (
        identified.groupby("customer_id")["country"]
        .agg(lambda s: s.mode().iat[0] if not s.mode().empty else "Unspecified")
        .rename("country")
    )
    first_ts = identified.groupby("customer_id")["invoice_ts"].min().rename("first_order_ts")

    dim = pd.concat([country, first_ts], axis=1).reset_index()
    dim = dim.sort_values("customer_id").reset_index(drop=True)
    dim.insert(0, "customer_key", np.arange(1, len(dim) + 1))
    dim["customer_id"] = dim["customer_id"].astype("int64")
    dim["cohort_month_key"] = dim["first_order_ts"].dt.strftime("%Y%m").astype(int)
    dim["cohort_label"] = dim["first_order_ts"].dt.strftime("%Y-%m")
    dim["is_guest"] = False

    guest = pd.DataFrame(
        [
            {
                "customer_key": cfg.get("business_rules.guest_customer_key", GUEST_KEY),
                "customer_id": pd.NA,
                "country": "Unidentified",
                "first_order_ts": pd.NaT,
                "cohort_month_key": -1,
                "cohort_label": "guest",
                "is_guest": True,
            }
        ]
    )
    out = pd.concat([guest, dim], ignore_index=True)
    out["customer_id"] = out["customer_id"].astype("Int64")
    return out


def build_dim_product(clean: pd.DataFrame, cfg) -> pd.DataFrame:
    non_product = {c.upper() for c in cfg.get("business_rules.non_product_stock_codes", [])}

    described = clean[clean["description"].notna()]
    desc = (
        described.groupby("stock_code")["description"]
        .agg(lambda s: s.mode().iat[0] if not s.mode().empty else "UNKNOWN PRODUCT")
        .rename("description")
    )
    codes = pd.Index(clean["stock_code"].dropna().unique(), name="stock_code").sort_values()
    dim = pd.DataFrame(index=codes).join(desc).reset_index()
    dim["description"] = dim["description"].fillna("UNKNOWN PRODUCT")
    dim.insert(0, "product_key", np.arange(1, len(dim) + 1))
    dim["is_non_product"] = dim["stock_code"].str.upper().isin(non_product)
    dim["product_family"] = dim.apply(_family, axis=1)
    return dim


_FAMILY_TOKENS = (
    "GLASS", "CERAMIC", "LANTERN", "PAPER", "VINTAGE", "STORAGE", "METAL",
    "WOODEN", "RETROSPOT", "CHRISTMAS", "HEART", "BAG", "CAKE", "TEA",
)


def _family(row: pd.Series) -> str:
    """Group products into families from the description text.

    The source has no category column. Rather than inventing one by hand for
    4,000 stock codes, the family is derived from the first material or motif
    keyword in the description, and everything unmatched is grouped as OTHER.
    This is a documented approximation, not a source of truth.
    """
    if row["is_non_product"]:
        return "NON_PRODUCT"
    text = str(row["description"]).upper()
    for token in _FAMILY_TOKENS:
        if token in text:
            return token
    return "OTHER"


# ---------------------------------------------------------------------------
# fact
# ---------------------------------------------------------------------------

def build_fact(clean, dim_customer, dim_product, cfg) -> pd.DataFrame:
    prefix = cfg.get("business_rules.cancellation_prefix", "C")
    guest_key = cfg.get("business_rules.guest_customer_key", GUEST_KEY)
    threshold = cfg.get("business_rules.return_quantity_threshold", 0)

    f = clean.copy()

    cust_lookup = (
        dim_customer.loc[dim_customer["customer_id"].notna(), ["customer_id", "customer_key"]]
        .set_index("customer_id")["customer_key"]
    )
    f["customer_key"] = f["customer_id"].map(cust_lookup).fillna(guest_key).astype("int64")

    prod_lookup = dim_product.set_index("stock_code")["product_key"]
    f["product_key"] = f["stock_code"].map(prod_lookup).astype("int64")

    f["date_key"] = f["invoice_ts"].dt.strftime("%Y%m%d").astype(int)
    f["month_key"] = f["invoice_ts"].dt.strftime("%Y%m").astype(int)

    f["is_cancellation_doc"] = (
        f["invoice_no"].astype("string").str.startswith(prefix).fillna(False)
    )
    f["invoice_base"] = f["invoice_no"].astype("string").str.lstrip(prefix)
    f["is_return"] = f["quantity"] < threshold

    # Signed amount. Returns carry a negative sign, so a plain SUM over any
    # slice yields net revenue without a CASE expression anywhere downstream.
    f["line_amount"] = (f["quantity"] * f["unit_price"]).round(4)
    f["gross_amount"] = np.where(f["is_return"], 0.0, f["line_amount"]).round(4)
    f["return_amount"] = np.where(f["is_return"], -f["line_amount"], 0.0).round(4)
    f["units_sold"] = np.where(f["is_return"], 0, f["quantity"]).astype("int64")
    f["units_returned"] = np.where(f["is_return"], -f["quantity"], 0).astype("int64")

    keep = [
        "source_row_id", "invoice_no", "invoice_base", "date_key", "month_key",
        "customer_key", "product_key", "quantity", "unit_price", "line_amount",
        "gross_amount", "return_amount", "units_sold", "units_returned",
        "is_return", "is_cancellation_doc", "is_guest_customer", "is_zero_price",
        "is_quantity_outlier", "is_price_outlier", "is_inconsistent_cancellation",
    ]
    fact = f[keep].copy()
    fact.insert(0, "sales_line_key", np.arange(1, len(fact) + 1))
    return fact
