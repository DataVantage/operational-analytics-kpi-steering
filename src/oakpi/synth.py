"""Deterministic synthetic sample in the shape of UCI Online Retail II.

Why this exists
---------------
The real source is a 45 MB Excel workbook that cannot sensibly be committed to
a public repository, and a CI runner has no reason to download it. This module
produces a small, seeded, schema-identical stand-in so that:

* ``git clone && make demo`` produces a working dashboard in under a minute,
* the test suite has a fixed dataset with *known* defects to assert on,
* every rule in ``config/dq_rules.yml`` is exercised at least once.

It is a fixture, not a finding. Every artefact built from it is stamped
``SYNTHETIC DEMO SAMPLE`` so it can never be mistaken for a real result.

The generative model
--------------------
Rows are generated from customer lifecycles rather than from a flat stream of
orders, because a flat stream produces a cohort chart that looks nothing like
a real one. Each customer gets an acquisition date and a lifetime; orders are
drawn inside that window against a seasonal intensity curve.

Three signals are planted for the analysis to find - and, importantly, for the
analysis to have to *distinguish from each other*:

1. a return rate that breaks on one product family from August 2011,
2. a German market whose repeat purchasing falls away over the same window,
3. a general trading dip, so that neither of the above can be read straight
   off the headline.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20260801

START = datetime(2009, 12, 1)
END = datetime(2011, 12, 9)

# The month from which the planted deterioration starts.
REGRESSION_START = datetime(2011, 8, 1)

COUNTRY_WEIGHTS = {
    "United Kingdom": 0.838,
    "Germany": 0.038,
    "France": 0.030,
    "EIRE": 0.025,
    "Netherlands": 0.016,
    "Spain": 0.012,
    "Belgium": 0.011,
    "Switzerland": 0.010,
    "Portugal": 0.009,
    "Australia": 0.006,
    "Norway": 0.005,
}

# family -> (description token, sku count, price low, price high)
FAMILIES = {
    "GLASS": ("GLASS", 24, 1.4, 6.5),
    "CERAMIC": ("CERAMIC", 20, 1.2, 5.0),
    "LANTERN": ("LANTERN", 16, 2.2, 12.0),
    "PAPER": ("PAPER", 24, 0.4, 3.2),
    "VINTAGE": ("VINTAGE", 20, 1.8, 9.5),
    "STORAGE": ("STORAGE", 16, 2.5, 14.0),
}

NOUNS = [
    "HEART T-LIGHT HOLDER", "STAR DECORATION", "TRINKET BOX", "CAKE STAND",
    "JAR", "BUNTING", "NAPKINS", "DOORSTOP", "PHOTO FRAME", "MUG",
    "HANGING DECORATION", "TEA TOWEL", "CANDLE PLATE", "GARLAND",
    "SIGN", "BOWL", "BASKET", "CLOCK", "LUNCH BAG", "NOTEBOOK",
    "CUSHION COVER", "COASTER SET", "APRON", "PLACEMAT", "WATER BOTTLE",
]

ADJECTIVES = [
    "RED", "WHITE", "CREAM", "BLUE", "PINK", "GREEN",
    "ANTIQUE", "SMALL", "LARGE", "SET OF 6",
]

NON_PRODUCT = [("POST", "POSTAGE", 18.0)]

MONTH_FACTOR = {
    1: 0.62, 2: 0.66, 3: 0.80, 4: 0.78, 5: 0.86, 6: 0.88,
    7: 0.85, 8: 0.84, 9: 1.05, 10: 1.30, 11: 1.72, 12: 1.40,
}
WEEKDAY_FACTOR = [1.05, 1.10, 1.08, 1.02, 0.92, 0.60, 0.70]


# ---------------------------------------------------------------------------
# catalogue and intensity curve
# ---------------------------------------------------------------------------

def _build_catalogue(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    code = 20000
    for family, (token, n, lo, hi) in FAMILIES.items():
        for _ in range(n):
            code += int(rng.integers(1, 9))
            rows.append(
                {
                    "stock_code": str(code),
                    "description": f"{rng.choice(ADJECTIVES)} {token} {rng.choice(NOUNS)}",
                    "family": family,
                    "base_price": round(float(rng.uniform(lo, hi)), 2),
                    "popularity": float(rng.gamma(2.0, 1.0)) + 0.2,
                }
            )
    cat = pd.DataFrame(rows)
    cat["popularity"] = cat["popularity"] / cat["popularity"].sum()
    return cat


def _daily_intensity() -> tuple[pd.DatetimeIndex, np.ndarray]:
    """Relative trading intensity per calendar day.

    Growth through 2010, flattening in the first half of 2011, and a
    deliberate step down from August 2011 - the trading dip the analysis has
    to separate from the returns problem and the German churn.
    """
    days = pd.date_range(START, END, freq="D")
    seasonal = np.array([MONTH_FACTOR[d.month] * WEEKDAY_FACTOR[d.weekday()] for d in days])
    trend = np.interp(
        np.arange(len(days)),
        [0, len(days) * 0.45, len(days) * 0.70, len(days) - 1],
        [0.88, 1.12, 1.18, 1.20],
    )
    dip = np.where(days >= REGRESSION_START, 0.95, 1.0)
    intensity = seasonal * trend * dip
    return days, intensity / intensity.sum()


# ---------------------------------------------------------------------------
# generation
# ---------------------------------------------------------------------------

def generate(n_customers: int = 2400, seed: int = SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    catalogue = _build_catalogue(rng)
    days, intensity = _daily_intensity()
    n_days = len(days)
    day_index = np.arange(n_days)

    countries = list(COUNTRY_WEIGHTS)
    country_p = np.array(list(COUNTRY_WEIGHTS.values()))
    country_p = country_p / country_p.sum()

    # Acquisition is front-loaded but spread across the whole window, so that
    # the cohort grid has enough cohorts to be readable.
    acquisition_w = np.exp(-day_index / (n_days * 0.95))
    acquisition_w /= acquisition_w.sum()

    join_idx = rng.choice(n_days, size=n_customers, p=acquisition_w)
    cust_country = rng.choice(countries, size=n_customers, p=country_p)
    cust_intensity = rng.gamma(1.35, 1.0, size=n_customers) + 0.15

    records: list[dict] = []
    invoice_seq = 489434

    for c in range(n_customers):
        start_i = int(join_idx[c])
        country = cust_country[c]

        # Lifetime in days. Cohorts acquired from 2011 churn faster, which is
        # what makes the retention grid worth reading rather than decorative.
        joined_late = days[start_i] >= datetime(2011, 1, 1)
        mean_life = 275.0 if joined_late else 340.0
        life = int(rng.exponential(mean_life)) + 20
        end_i = min(n_days - 1, start_i + life)
        if end_i <= start_i:
            end_i = min(n_days - 1, start_i + 1)

        window = intensity[start_i:end_i + 1]
        if window.sum() <= 0:
            continue
        window = window / window.sum()

        span_share = (end_i - start_i + 1) / n_days
        expected = 1.0 + cust_intensity[c] * 22.0 * span_share
        n_orders = int(max(1, rng.poisson(expected)))

        picks = rng.choice(end_i - start_i + 1, size=n_orders, p=window)
        for offset in picks:
            di = start_i + int(offset)
            ts = days[di].to_pydatetime() + timedelta(minutes=int(rng.integers(8 * 60, 19 * 60)))

            # Planted signal: German repeat purchasing collapses from Aug 2011.
            if country == "Germany" and ts >= REGRESSION_START and rng.random() < 0.55:
                continue

            invoice_seq += int(rng.integers(1, 3))
            invoice = str(invoice_seq)
            # Planted defect: ~21% of orders arrive with no customer id.
            customer = "" if rng.random() < 0.21 else str(c + 12400)

            n_lines = int(max(1, rng.poisson(3.9)))
            n_lines = min(n_lines, len(catalogue))
            chosen = rng.choice(
                len(catalogue), size=n_lines, replace=False,
                p=catalogue["popularity"].to_numpy(),
            )
            for p in chosen:
                prod = catalogue.iloc[int(p)]
                qty = int(max(1, rng.poisson(5) + rng.integers(1, 6)))
                price = max(0.12, round(float(prod["base_price"]) * float(rng.normal(1.0, 0.06)), 2))
                records.append(
                    {
                        "Invoice": invoice,
                        "StockCode": prod["stock_code"],
                        "Description": prod["description"],
                        "Quantity": qty,
                        "InvoiceDate": ts,
                        "Price": price,
                        "Customer ID": customer,
                        "Country": country,
                        "_family": prod["family"],
                    }
                )

            if country != "United Kingdom" and rng.random() < 0.55:
                code, desc, amount = NON_PRODUCT[0]
                records.append(
                    {
                        "Invoice": invoice, "StockCode": code, "Description": desc,
                        "Quantity": 1, "InvoiceDate": ts,
                        "Price": round(amount * float(rng.uniform(0.6, 1.6)), 2),
                        "Customer ID": customer, "Country": country,
                        "_family": "NON_PRODUCT",
                    }
                )

    df = pd.DataFrame(records)
    df = _inject_returns(df, rng)
    df = df.sort_values("InvoiceDate", kind="stable").reset_index(drop=True)
    # Defects are injected last, because several of them deliberately break the
    # column types the sort above depends on.
    df = _inject_defects(df, rng)
    return df.drop(columns=["_family"])


def _inject_returns(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Create cancellation documents.

    Planted signal: the GLASS family return rate rises from roughly 3% to
    roughly 20% from August 2011. It is the intended root cause of a large part
    of the net revenue miss, and it is deliberately *not* the only thing
    happening in that window.
    """
    sellable = df[df["_family"] != "NON_PRODUCT"]
    late = sellable["InvoiceDate"].to_numpy() >= np.datetime64(REGRESSION_START)
    glass = (sellable["_family"] == "GLASS").to_numpy()

    rates = np.full(len(sellable), 0.028)
    rates = np.where(late & glass, 0.205, rates)
    rates = np.where(late & ~glass, 0.034, rates)

    returns = sellable[rng.random(len(sellable)) < rates].copy()
    if not len(returns):
        return df
    returns["Invoice"] = "C" + returns["Invoice"].astype(str)
    returns["Quantity"] = -returns["Quantity"]
    returns["InvoiceDate"] = returns["InvoiceDate"] + pd.to_timedelta(
        rng.integers(2, 26, size=len(returns)), unit="D"
    )
    returns = returns[returns["InvoiceDate"] <= END]
    return pd.concat([df, returns], ignore_index=True)


def _inject_defects(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Plant the exact defects the data quality rule set is written against."""
    df = df.reset_index(drop=True)
    n = len(df)

    def sample(frac: float) -> np.ndarray:
        return rng.choice(n, size=max(1, int(n * frac)), replace=False)

    df.loc[sample(0.0006), "Invoice"] = None                       # DQ001
    bad_dates = sample(0.0005)                                     # DQ002
    df["InvoiceDate"] = df["InvoiceDate"].astype(object)
    df.loc[bad_dates, "InvoiceDate"] = "n/a"
    df.loc[sample(0.0004), "StockCode"] = None                     # DQ003
    df.loc[sample(0.0012), "Quantity"] = 0                         # DQ004
    df.loc[sample(0.0015), "Price"] = -round(float(rng.uniform(5, 90)), 2)  # DQ005
    df.loc[sample(0.0040), "Price"] = 0.0                          # DQ006

    # DQ008 - genuine bulk wholesale lines, priced like the cheap paper goods
    # they are in the real source. Large enough to trip the rule, small enough
    # not to swamp a fixture of this size.
    bulk = sample(0.0004)
    df.loc[bulk, "Quantity"] = rng.integers(1100, 2600, size=len(bulk))
    df.loc[bulk, "Price"] = np.round(rng.uniform(0.28, 0.85, size=len(bulk)), 2)

    df.loc[sample(0.0003), "Price"] = round(float(rng.uniform(1200, 4000)), 2)  # DQ009
    df.loc[sample(0.0050), "Description"] = None                   # DQ012

    noisy = sample(0.020)                                          # DQ013
    df.loc[noisy, "Description"] = df.loc[noisy, "Description"].astype(str).str.lower() + "  "

    cancels = df.index[df["Invoice"].astype(str).str.startswith("C")]  # DQ011
    if len(cancels):
        broken = rng.choice(cancels, size=max(1, int(len(cancels) * 0.02)), replace=False)
        df.loc[broken, "Quantity"] = df.loc[broken, "Quantity"].abs()

    dupes = df.iloc[sample(0.0030)].copy()                         # DQ010
    return pd.concat([df, dupes], ignore_index=True)


def write_sample(path: str | Path, n_customers: int = 2400, seed: int = SEED) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    df = generate(n_customers=n_customers, seed=seed)
    df.to_csv(out, index=False, compression="gzip" if out.suffix == ".gz" else None)
    return out
