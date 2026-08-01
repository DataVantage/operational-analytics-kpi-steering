"""Command line entry point.

    python -m oakpi sample      regenerate the offline fixture
    python -m oakpi data        download the real UCI dataset
    python -m oakpi run         ingest -> quality -> star schema -> KPIs -> outputs
    python -m oakpi info        show what is currently in the warehouse

``run`` is deliberately a single command. A pipeline that needs six commands in
the right order is a pipeline that will be run in the wrong order.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd

from . import __version__, analysis, dashboard, dq, ingest, kpi, model, report, synth
from .config import Config, load_dq_rules
from .engine import Warehouse, duckdb_available


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)-14s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("matplotlib").setLevel(logging.WARNING)


log = logging.getLogger("oakpi")


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_sample(args: argparse.Namespace) -> int:
    cfg = Config.load(args.config)
    out = synth.write_sample(cfg.path("source.sample_csv"), n_customers=args.customers)
    size_mb = out.stat().st_size / 1e6
    log.info("Wrote offline fixture: %s (%.2f MB)", out, size_mb)
    return 0


def cmd_data(args: argparse.Namespace) -> int:
    """Download and unpack the real UCI Online Retail II dataset."""
    import urllib.request

    cfg = Config.load(args.config)
    url = cfg.get("source.url")
    raw_dir = cfg.path("source.raw_dir")
    raw_dir.mkdir(parents=True, exist_ok=True)
    archive = raw_dir / "online_retail_II.zip"

    log.info("Downloading %s", url)
    try:
        with urllib.request.urlopen(url, timeout=180) as response, open(archive, "wb") as fh:
            shutil.copyfileobj(response, fh)
    except Exception as exc:  # pragma: no cover - network dependent
        log.error("Download failed: %s", exc)
        log.error(
            "Download the workbook manually from\n"
            "  https://archive.ics.uci.edu/dataset/502/online+retail+ii\n"
            "and place online_retail_II.xlsx in %s",
            raw_dir,
        )
        return 1

    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(raw_dir)
        archive.unlink()
    log.info("Raw data ready in %s: %s", raw_dir, [p.name for p in raw_dir.iterdir()])
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    cfg = Config.load(args.config)
    with Warehouse.open(cfg, args.engine) as wh:
        tables = wh.table_names()
        if not tables:
            log.info("Warehouse is empty. Run `python -m oakpi run` first.")
            return 0
        print(f"\nWarehouse: {wh.path}  (engine: {wh.kind})\n")
        for name in tables:
            n = wh.query(f'SELECT COUNT(*) AS n FROM "{name}"')["n"].iat[0]
            print(f"  {name:<32} {int(n):>10,} rows")
        print()
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    started = time.time()
    cfg = Config.load(args.config)
    rules = load_dq_rules()

    log.info("=" * 74)
    log.info("%s  v%s", cfg.get("project.name"), __version__)
    log.info("=" * 74)

    # -- 1. ingest ---------------------------------------------------------
    source_path = Path(args.source) if args.source else None
    staged = ingest.read_source(cfg, source_path)
    if staged.coercion_failures:
        log.warning("Type coercion failures: %s", staged.coercion_failures)

    # -- 2. data quality ---------------------------------------------------
    quality = dq.run(staged.frame, rules, cfg)
    if quality.score < args.min_dq_score:
        log.error(
            "Data quality score %.2f is below the configured floor of %.2f. Stopping.",
            quality.score, args.min_dq_score,
        )
        return 2

    # -- 3. dimensional model ---------------------------------------------
    star = model.build(quality.clean, cfg)

    with Warehouse.open(cfg, args.engine) as wh:
        log.info("Warehouse engine: %s (%s)", wh.kind, wh.path.name)
        for name, frame in star.items():
            wh.write_table(name, frame)
        wh.write_table("stg_transactions", quality.clean)
        wh.write_table("quarantine", quality.quarantine)
        wh.write_table("dq_report", quality.report)

        # -- 4. KPI layer --------------------------------------------------
        monthly = analysis.factor_frame(kpi.build_base(wh, cfg))
        wh.write_table("kpi_monthly_factors", monthly)

        periods = analysis.resolve_periods(monthly, cfg)
        kpi.build_period_marts(wh, cfg, periods.current.month_key, periods.comparison.month_key)
        recon = kpi.check_reconciliation(wh)

        cur = monthly[monthly["month_key"] == periods.current.month_key].iloc[0]
        cmp_ = monthly[monthly["month_key"] == periods.comparison.month_key].iloc[0]

        # -- 5. root cause -------------------------------------------------
        decomposition = analysis.lmdi(cur, cmp_)
        chain = analysis.chain_substitution(cur, cmp_)
        bridge = analysis.guest_bridge(cur, cmp_)
        wh.write_table("mart_driver_decomposition", decomposition)

        marts = {
            "kpi_monthly": monthly,
            "products": wh.query("SELECT * FROM mart_product_period"),
            "returns_family": wh.query("SELECT * FROM mart_returns_family"),
            "returns_monthly": wh.query("SELECT * FROM mart_returns_monthly"),
            "cohort": wh.query("SELECT * FROM mart_cohort_retention"),
            "countries": wh.query("SELECT * FROM mart_country_period"),
            "concentration": wh.query("SELECT * FROM mart_customer_concentration"),
            "reconciliation": recon,
            "dq_report": quality.report,
            "decomposition": decomposition,
            "chain": chain,
        }

    context = {
        "project": cfg.get("project.name"),
        "owner": cfg.get("project.owner"),
        "currency": cfg.get("project.currency"),
        "version": __version__,
        "generated_at": pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "source_label": staged.source_label,
        "is_synthetic": staged.is_synthetic,
        "rows_read": staged.rows_read,
        "dq_score": quality.score,
        "rows_quarantined": len(quality.quarantine),
        "quarantine_rate": round(quality.quarantine_rate, 3),
        "periods": periods.as_dict(),
        "bridge": bridge,
        "top_n": cfg.get("analysis.top_n", 15),
        "retention_horizon": cfg.get("analysis.retention_window_months", 3),
    }

    # -- 6. publish --------------------------------------------------------
    _export_marts(cfg, marts)
    dash = dashboard.build(cfg, marts, context)
    findings = report.write(cfg, marts, context)
    _write_run_log(cfg, context, marts)

    log.info("-" * 74)
    log.info("Dashboard : %s", dash)
    log.info("Findings  : %s", findings)
    log.info("Completed in %.1fs", time.time() - started)
    if staged.is_synthetic:
        log.warning(
            "This build used the SYNTHETIC DEMO SAMPLE. Run `python -m oakpi data` "
            "and re-run to publish figures from the real UCI dataset."
        )
    return 0


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _export_marts(cfg, marts: dict[str, pd.DataFrame]) -> None:
    out_dir = cfg.path("output.marts_dir")
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in marts.items():
        frame.to_csv(out_dir / f"{name}.csv", index=False)
    log.info("Exported %d marts to %s", len(marts), out_dir)


def _write_run_log(cfg, context: dict, marts: dict) -> None:
    path = cfg.path("output.run_log")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(context)
    payload["mart_row_counts"] = {k: int(len(v)) for k, v in marts.items()}
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="oakpi", description=__doc__)
    parser.add_argument("--config", help="path to config.yml")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sample = sub.add_parser("sample", help="regenerate the offline fixture")
    p_sample.add_argument("--customers", type=int, default=2400)
    p_sample.set_defaults(func=cmd_sample)

    p_data = sub.add_parser("data", help="download the real UCI dataset")
    p_data.set_defaults(func=cmd_data)

    p_run = sub.add_parser("run", help="run the full pipeline")
    p_run.add_argument("--engine", choices=["auto", "duckdb", "sqlite"], default=None)
    p_run.add_argument("--source", help="explicit path to a source file")
    p_run.add_argument(
        "--min-dq-score", type=float, default=80.0,
        help="fail the run if the data quality score falls below this value",
    )
    p_run.set_defaults(func=cmd_run)

    p_info = sub.add_parser("info", help="describe the current warehouse")
    p_info.add_argument("--engine", choices=["auto", "duckdb", "sqlite"], default=None)
    p_info.set_defaults(func=cmd_info)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(getattr(args, "verbose", False))
    if not duckdb_available():
        log.info("duckdb is not installed - falling back to sqlite (identical SQL).")
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
