"""Dashboard generation.

Produces one self-contained HTML file that can be opened from disk, committed,
and served by GitHub Pages without a build step or a server. Plotly is pulled
from a CDN; all data is embedded as JSON at build time, so the page has no
back end and cannot go stale relative to its own numbers.

The layout follows the order a decision-maker actually reads in: headline,
what changed, why it changed, where it sits, and only then how much the
underlying data can be trusted.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

PALETTE = {
    "ink": "#0f172a",
    "muted": "#64748b",
    "line": "#e2e8f0",
    "accent": "#0d9488",
    "accent_soft": "#99f6e4",
    "warn": "#b45309",
    "bad": "#be123c",
    "good": "#15803d",
    "neutral": "#94a3b8",
}


def build(cfg, marts: dict, ctx: dict) -> Path:
    path = cfg.path("output.dashboard_file")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(marts, ctx), encoding="utf-8")
    log.info("Wrote dashboard: %s", path)
    return path


# ---------------------------------------------------------------------------
# payload
# ---------------------------------------------------------------------------

def _payload(marts: dict, ctx: dict) -> dict:
    monthly = marts["kpi_monthly"].sort_values("month_key")
    cur_key = ctx["periods"]["current"]["month_key"]
    cmp_key = ctx["periods"]["comparison"]["month_key"]
    cur = monthly[monthly["month_key"] == cur_key].iloc[0]
    cmp_ = monthly[monthly["month_key"] == cmp_key].iloc[0]

    decomposition = marts["decomposition"]
    countries = marts["countries"]
    products = marts["products"]
    sellable = products[products["is_non_product"] == 0].copy()
    returns_monthly = marts["returns_monthly"]
    cohort = marts["cohort"]

    # Pareto over the top articles, everything else collapsed into a rest bar.
    top_n = int(ctx["top_n"])
    pareto = sellable.nlargest(top_n, "net_revenue_cur")[
        ["stock_code", "description", "net_revenue_cur", "cumulative_revenue_share_pct"]
    ]

    # Return-rate trend for the families that matter in the current period.
    fam_focus = (
        marts["returns_family"].sort_values("gross_revenue_cur", ascending=False)
        ["product_family"].head(6).tolist()
    )
    trend = returns_monthly[returns_monthly["product_family"].isin(fam_focus)]

    # Cohort heatmap: cohorts of meaningful size whose window has had time to
    # develop. A cohort acquired last month is all 100% and nothing else, and
    # putting it on the grid invites exactly the wrong reading.
    from .analysis import shift_month

    complete = monthly[monthly["is_complete_month"] == 1]["month_key"]
    last_complete = int(complete.max()) if len(complete) else int(monthly["month_key"].max())
    min_history = int(ctx["retention_horizon"])
    big = cohort[
        (cohort["cohort_customers"] >= 20)
        & (cohort["cohort_month_key"] <= shift_month(last_complete, -min_history))
    ]
    heat = big.pivot_table(
        index="cohort_month_key", columns="months_since_first_order",
        values="retention_pct", aggfunc="first",
    ).sort_index()
    heat = heat.iloc[-14:, :13] if len(heat) else heat

    movers = countries.reindex(
        countries["net_revenue_delta"].abs().sort_values(ascending=False).index
    ).head(10)

    decliners = sellable.nsmallest(10, "net_revenue_delta")[
        ["stock_code", "description", "product_family", "net_revenue_cmp",
         "net_revenue_cur", "net_revenue_delta", "return_rate_cur_pct"]
    ]

    delta = float(cur["net_revenue"] - cmp_["net_revenue"])
    delta_pct = 100 * delta / float(cmp_["net_revenue"]) if float(cmp_["net_revenue"]) else 0.0

    return {
        "meta": {
            "project": ctx["project"],
            "owner": ctx["owner"],
            "currency": ctx["currency"],
            "version": ctx["version"],
            "generated_at": ctx["generated_at"],
            "source_label": ctx["source_label"],
            "is_synthetic": bool(ctx["is_synthetic"]),
            "current_label": ctx["periods"]["current"]["label"],
            "comparison_label": ctx["periods"]["comparison"]["label"],
            "comparison_mode": ctx["periods"]["mode"],
            "retention_horizon": ctx["retention_horizon"],
        },
        "cards": _cards(cur, cmp_, ctx, delta, delta_pct),
        "trend": {
            "labels": monthly["month_label"].tolist(),
            "net_revenue": monthly["net_revenue"].tolist(),
            "gross_revenue": monthly["gross_revenue"].tolist(),
            "returns": monthly["returns_value"].tolist(),
            "return_rate": monthly["return_rate_pct"].tolist(),
            "active_customers": monthly["active_customers"].tolist(),
            "orders": monthly["orders"].tolist(),
            "aov": monthly["aov"].tolist(),
            "is_complete": monthly["is_complete_month"].astype(int).tolist(),
            "current_label": ctx["periods"]["current"]["label"],
            "comparison_label": ctx["periods"]["comparison"]["label"],
        },
        "waterfall": {
            "labels": decomposition["label"].tolist(),
            "contributions": decomposition["contribution"].tolist(),
            "change_pct": decomposition["change_pct"].tolist(),
            "shares": decomposition["share_of_change_pct"].tolist(),
            "meanings": decomposition["meaning"].tolist(),
            "start": float(cmp_["net_revenue_identified"]),
            "end": float(cur["net_revenue_identified"]),
            "bridge": ctx["bridge"],
        },
        "returns_trend": {
            "families": fam_focus,
            "series": {
                fam: {
                    "labels": trend[trend["product_family"] == fam]["month_label"].tolist(),
                    "rate": trend[trend["product_family"] == fam]["return_rate_pct"].tolist(),
                }
                for fam in fam_focus
            },
            "family_table": _records(marts["returns_family"].head(8)),
        },
        "countries": _records(movers),
        "pareto": {
            "labels": pareto["stock_code"].tolist(),
            "descriptions": pareto["description"].tolist(),
            "revenue": pareto["net_revenue_cur"].tolist(),
            "cumulative": pareto["cumulative_revenue_share_pct"].tolist(),
        },
        "cohort": {
            "cohorts": [f"{int(k) // 100}-{int(k) % 100:02d}" for k in heat.index] if len(heat) else [],
            "offsets": [int(c) for c in heat.columns] if len(heat) else [],
            "values": [[None if pd.isna(v) else float(v) for v in row]
                       for row in heat.to_numpy()] if len(heat) else [],
        },
        "decliners": _records(decliners),
        "dq": {
            "score": ctx["dq_score"],
            "rows_read": ctx["rows_read"],
            "rows_quarantined": ctx["rows_quarantined"],
            "quarantine_rate": ctx["quarantine_rate"],
            "rules": _records(marts["dq_report"]),
        },
        "reconciliation": _records(marts["reconciliation"]),
    }


def _cards(cur, cmp_, ctx, delta, delta_pct) -> list[dict]:
    def change(a, b, unit="%"):
        if unit == "pp":
            return {"text": f"{a - b:+.2f} pp", "good": a < b}
        if b == 0:
            return {"text": "n/a", "good": None}
        v = 100 * (a - b) / b
        return {"text": f"{v:+.1f}%", "good": v >= 0}

    return [
        {
            "label": "Net revenue",
            "value": f"{float(cur['net_revenue']):,.0f}",
            "unit": ctx["currency"],
            "delta": {"text": f"{delta_pct:+.1f}%", "good": delta >= 0},
            "note": f"vs {ctx['periods']['comparison']['label']}",
        },
        {
            "label": "Return rate",
            "value": f"{float(cur['return_rate_pct']):.2f}",
            "unit": "%",
            "delta": change(float(cur["return_rate_pct"]), float(cmp_["return_rate_pct"]), "pp"),
            "note": "of gross revenue",
        },
        {
            "label": "Active customers",
            "value": f"{int(cur['active_customers']):,}",
            "unit": "",
            "delta": change(float(cur["active_customers"]), float(cmp_["active_customers"])),
            "note": "identified only",
        },
        {
            "label": "Orders",
            "value": f"{int(cur['orders']):,}",
            "unit": "",
            "delta": change(float(cur["orders"]), float(cmp_["orders"])),
            "note": "excl. credit notes",
        },
        {
            "label": "Average order value",
            "value": f"{float(cur['aov']):,.2f}",
            "unit": ctx["currency"],
            "delta": change(float(cur["aov"]), float(cmp_["aov"])),
            "note": "net of returns",
        },
        {
            "label": "Data quality score",
            "value": f"{ctx['dq_score']:.1f}",
            "unit": "/100",
            "delta": {"text": f"{ctx['quarantine_rate']:.2f}% quarantined", "good": None},
            "note": "severity weighted",
        },
    ]


def _records(df: pd.DataFrame) -> list[dict]:
    clean = df.replace({np.nan: None})
    return json.loads(clean.to_json(orient="records", date_format="iso"))


# ---------------------------------------------------------------------------
# html
# ---------------------------------------------------------------------------

def render(marts: dict, ctx: dict) -> str:
    data = _payload(marts, ctx)
    blob = json.dumps(data, indent=None, allow_nan=False)
    meta = data["meta"]
    banner = (
        '<div class="banner">This build ran against the <strong>synthetic demo '
        'sample</strong>, not the real UCI dataset. It demonstrates the method; '
        'it is not a statement about real trading. Run '
        '<code>python -m oakpi data &amp;&amp; python -m oakpi run</code> to '
        'rebuild from the real source.</div>'
        if meta["is_synthetic"] else ""
    )
    return _TEMPLATE.format(
        title=f"{meta['project']} - {meta['current_label']}",
        project=meta["project"],
        owner=meta["owner"],
        current=meta["current_label"],
        comparison=meta["comparison_label"],
        mode="year over year" if meta["comparison_mode"] == "yoy" else "period over period",
        generated=meta["generated_at"],
        source=meta["source_label"],
        version=meta["version"],
        banner=banner,
        palette=json.dumps(PALETTE),
        data=blob,
    )


_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js" charset="utf-8"></script>
<style>
  :root {{
    --ink:#0f172a; --muted:#64748b; --line:#e2e8f0; --bg:#f8fafc;
    --card:#ffffff; --accent:#0d9488; --bad:#be123c; --good:#15803d; --warn:#b45309;
  }}
  * {{ box-sizing:border-box; }}
  body {{
    margin:0; background:var(--bg); color:var(--ink);
    font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,Helvetica,Arial,sans-serif;
  }}
  .wrap {{ max-width:1240px; margin:0 auto; padding:32px 24px 80px; }}
  header {{ border-bottom:1px solid var(--line); padding-bottom:20px; margin-bottom:24px; }}
  h1 {{ font-size:26px; margin:0 0 6px; letter-spacing:-0.02em; }}
  h2 {{ font-size:17px; margin:0 0 4px; letter-spacing:-0.01em; }}
  .sub {{ color:var(--muted); font-size:13.5px; }}
  .banner {{
    background:#fffbeb; border:1px solid #fcd34d; color:#78350f;
    padding:12px 16px; border-radius:10px; margin:16px 0 0; font-size:13.5px;
  }}
  .banner code {{ background:#fef3c7; padding:1px 5px; border-radius:4px; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:14px; margin:24px 0 8px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px 18px; }}
  .card .lbl {{ font-size:12px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); }}
  .card .val {{ font-size:27px; font-weight:640; margin:6px 0 2px; letter-spacing:-0.02em; }}
  .card .val span {{ font-size:14px; font-weight:500; color:var(--muted); margin-left:3px; }}
  .card .dlt {{ font-size:13px; font-weight:600; }}
  .card .note {{ font-size:12px; color:var(--muted); margin-top:2px; }}
  .up {{ color:var(--good); }} .down {{ color:var(--bad); }} .flat {{ color:var(--muted); }}
  section {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:20px 22px; margin-top:18px; }}
  .lead {{ color:var(--muted); font-size:13.5px; margin:4px 0 14px; max-width:78ch; }}
  .grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }}
  @media (max-width:900px) {{ .grid2 {{ grid-template-columns:1fr; }} }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th, td {{ padding:7px 10px; text-align:right; border-bottom:1px solid var(--line); white-space:nowrap; }}
  th:first-child, td:first-child, th.l, td.l {{ text-align:left; }}
  th {{ font-size:11.5px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); font-weight:600; }}
  tbody tr:hover {{ background:#f1f5f9; }}
  .pill {{ display:inline-block; padding:1px 8px; border-radius:999px; font-size:11px; font-weight:600; }}
  .pill.blocker {{ background:#fee2e2; color:#991b1b; }}
  .pill.major {{ background:#ffedd5; color:#9a3412; }}
  .pill.minor {{ background:#e0f2fe; color:#075985; }}
  .pill.ok {{ background:#dcfce7; color:#166534; }}
  .scroll {{ overflow-x:auto; }}
  footer {{ color:var(--muted); font-size:12.5px; margin-top:28px; border-top:1px solid var(--line); padding-top:16px; }}
  .chart {{ width:100%; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>{project}</h1>
    <div class="sub">
      Reporting period <strong>{current}</strong> against <strong>{comparison}</strong> ({mode})
      &middot; source: {source} &middot; built {generated} by oakpi v{version} &middot; {owner}
    </div>
    {banner}
  </header>

  <div class="cards" id="cards"></div>

  <section>
    <h2>1. What changed</h2>
    <p class="lead">Net revenue against gross revenue and returns, by month. Months that
      are not complete in the source are drawn faded and are never used as a reporting
      period.</p>
    <div id="chart-trend" class="chart"></div>
  </section>

  <section>
    <h2>2. Why it changed</h2>
    <p class="lead">Additive LMDI-I decomposition of the change in net revenue from
      identified customers. The five factors multiply out to net revenue, and their
      contributions sum to the total change with no residual, so nothing is hidden in
      an "other" bar.</p>
    <div id="chart-waterfall" class="chart"></div>
    <div id="bridge"></div>
  </section>

  <div class="grid2">
    <section>
      <h2>3. Returns by product family</h2>
      <p class="lead">Return rate as a share of gross revenue, by month.</p>
      <div id="chart-returns" class="chart"></div>
    </section>
    <section>
      <h2>4. Excess returns</h2>
      <p class="lead">Value the current period would have kept at the comparison
        period's return rate.</p>
      <div class="scroll"><table id="tbl-returns"></table></div>
    </section>
  </div>

  <div class="grid2">
    <section>
      <h2>5. Where the change sits by market</h2>
      <p class="lead">Change in net revenue by country. "Unidentified" is guest
        revenue, kept in view so the slice reconciles to the headline.</p>
      <div id="chart-country" class="chart"></div>
    </section>
    <section>
      <h2>6. Revenue concentration by article</h2>
      <p class="lead">Bars are net revenue in the current period, the line is the
        cumulative share of it.</p>
      <div id="chart-pareto" class="chart"></div>
    </section>
  </div>

  <section>
    <h2>7. Cohort retention</h2>
    <p class="lead">Share of each acquisition cohort still buying n months after its
      first order. Cohorts under 20 customers are suppressed. This is what separates
      "a weak month" from "a shrinking base".</p>
    <div id="chart-cohort" class="chart"></div>
  </section>

  <section>
    <h2>8. Largest article declines</h2>
    <div class="scroll"><table id="tbl-decliners"></table></div>
  </section>

  <section>
    <h2>9. Can these numbers be trusted</h2>
    <p class="lead">Every rule below is declared in <code>config/dq_rules.yml</code>
      with a written rationale. Quarantined rows are excluded from all KPIs and remain
      retrievable from the <code>quarantine</code> table together with the rule that
      removed them.</p>
    <div class="scroll"><table id="tbl-dq"></table></div>
    <h2 style="margin-top:22px">Reconciliation</h2>
    <p class="lead">The fact table against the published KPI mart. The pipeline aborts
      rather than publishing if any difference exceeds 0.05.</p>
    <div class="scroll"><table id="tbl-recon"></table></div>
  </section>

  <footer>
    Generated by <code>oakpi</code> v{version}. All figures are read from the marts at
    build time. Source data: {source}.
  </footer>
</div>

<script>
const P = {palette};
const D = {data};
const CUR = D.meta.currency;

const fmt = (v, d = 0) => v === null || v === undefined || isNaN(v)
  ? "n/a" : Number(v).toLocaleString("en-GB", {{minimumFractionDigits: d, maximumFractionDigits: d}});
const money = v => fmt(v, 0);
const pct = (v, d = 1) => v === null || v === undefined || isNaN(v) ? "n/a" : Number(v).toFixed(d) + "%";

const LAYOUT = {{
  margin: {{l: 62, r: 24, t: 16, b: 48}},
  height: 340,
  paper_bgcolor: "rgba(0,0,0,0)",
  plot_bgcolor: "rgba(0,0,0,0)",
  font: {{family: "-apple-system, Segoe UI, Inter, Roboto, sans-serif", size: 12, color: P.ink}},
  xaxis: {{gridcolor: P.line, zerolinecolor: P.line}},
  yaxis: {{gridcolor: P.line, zerolinecolor: P.line}},
  legend: {{orientation: "h", y: -0.22, x: 0}},
  hovermode: "x unified"
}};
const CONFIG = {{displayModeBar: false, responsive: true}};

/* ---- cards ---- */
document.getElementById("cards").innerHTML = D.cards.map(c => {{
  const cls = c.delta.good === null ? "flat" : (c.delta.good ? "up" : "down");
  return `<div class="card">
    <div class="lbl">${{c.label}}</div>
    <div class="val">${{c.value}}<span>${{c.unit}}</span></div>
    <div class="dlt ${{cls}}">${{c.delta.text}}</div>
    <div class="note">${{c.note}}</div>
  </div>`;
}}).join("");

/* ---- 1. trend ---- */
(function () {{
  const t = D.trend;
  const colours = t.is_complete.map(c => c ? P.accent : "#cbd5e1");
  Plotly.newPlot("chart-trend", [
    {{
      type: "bar", name: "Net revenue", x: t.labels, y: t.net_revenue,
      marker: {{color: colours}},
      hovertemplate: "%{{x}}<br>Net revenue " + CUR + " %{{y:,.0f}}<extra></extra>"
    }},
    {{
      type: "scatter", mode: "lines", name: "Return rate (right axis)",
      x: t.labels, y: t.return_rate, yaxis: "y2",
      line: {{color: P.bad, width: 2}},
      hovertemplate: "Return rate %{{y:.2f}}%<extra></extra>"
    }}
  ], Object.assign({{}}, LAYOUT, {{
    height: 380,
    yaxis: Object.assign({{}}, LAYOUT.yaxis, {{title: "Net revenue (" + CUR + ")"}}),
    yaxis2: {{overlaying: "y", side: "right", title: "Return rate", ticksuffix: "%",
             gridcolor: "rgba(0,0,0,0)", rangemode: "tozero"}},
    xaxis: Object.assign({{}}, LAYOUT.xaxis, {{tickangle: -45}})
  }}), CONFIG);
}})();

/* ---- 2. waterfall ---- */
(function () {{
  const w = D.waterfall;
  const x = [D.meta.comparison_label].concat(w.labels).concat([D.meta.current_label]);
  const measure = ["absolute"].concat(w.labels.map(() => "relative")).concat(["total"]);
  const y = [w.start].concat(w.contributions).concat([0]);
  const text = ["", ...w.contributions.map(v => (v >= 0 ? "+" : "") + money(v)), ""];
  Plotly.newPlot("chart-waterfall", [{{
    type: "waterfall", orientation: "v", x: x, y: y, measure: measure,
    text: text, textposition: "outside",
    connector: {{line: {{color: P.line}}}},
    increasing: {{marker: {{color: P.good}}}},
    decreasing: {{marker: {{color: P.bad}}}},
    totals: {{marker: {{color: P.ink}}}},
    hovertemplate: "%{{x}}<br>" + CUR + " %{{y:,.0f}}<extra></extra>"
  }}], Object.assign({{}}, LAYOUT, {{
    height: 400, hovermode: "closest",
    yaxis: Object.assign({{}}, LAYOUT.yaxis, {{title: "Net revenue, identified customers (" + CUR + ")"}}),
    xaxis: Object.assign({{}}, LAYOUT.xaxis, {{tickangle: -20}})
  }}), CONFIG);

  const b = w.bridge;
  document.getElementById("bridge").innerHTML = `
    <table style="margin-top:14px">
      <thead><tr><th class="l">Reconciliation of the decomposition</th><th>${{CUR}}</th></tr></thead>
      <tbody>
        <tr><td class="l">Change in net revenue, all customers</td><td>${{money(b.net_revenue_delta)}}</td></tr>
        <tr><td class="l">of which identified customers (decomposed above)</td><td>${{money(b.identified_delta)}}</td></tr>
        <tr><td class="l">of which guest orders, no customer id</td><td>${{money(b.guest_delta)}}</td></tr>
        <tr><td class="l">KPI tree rounding residual</td><td>${{money(b.tree_residual)}}</td></tr>
      </tbody>
    </table>`;
}})();

/* ---- 3. returns trend ---- */
(function () {{
  const r = D.returns_trend;
  const traces = r.families.map((fam, i) => ({{
    type: "scatter", mode: "lines", name: fam,
    x: r.series[fam].labels, y: r.series[fam].rate,
    line: {{width: 2}},
    hovertemplate: fam + " %{{y:.2f}}%<extra></extra>"
  }}));
  Plotly.newPlot("chart-returns", traces, Object.assign({{}}, LAYOUT, {{
    yaxis: Object.assign({{}}, LAYOUT.yaxis, {{title: "Return rate", ticksuffix: "%"}}),
    xaxis: Object.assign({{}}, LAYOUT.xaxis, {{tickangle: -45}})
  }}), CONFIG);

  const rows = r.family_table.map(f => `<tr>
      <td class="l">${{f.product_family}}</td>
      <td>${{money(f.gross_revenue_cur)}}</td>
      <td>${{pct(f.return_rate_cmp_pct, 2)}}</td>
      <td>${{pct(f.return_rate_cur_pct, 2)}}</td>
      <td style="color:${{f.excess_returns_value > 0 ? P.bad : P.muted}}">${{money(f.excess_returns_value)}}</td>
    </tr>`).join("");
  document.getElementById("tbl-returns").innerHTML =
    `<thead><tr><th class="l">Family</th><th>Gross rev.</th><th>Rate ${{D.meta.comparison_label}}</th>
     <th>Rate ${{D.meta.current_label}}</th><th>Excess returns</th></tr></thead><tbody>${{rows}}</tbody>`;
}})();

/* ---- 5. country ---- */
(function () {{
  const c = D.countries.slice().sort((a, b) => a.net_revenue_delta - b.net_revenue_delta);
  Plotly.newPlot("chart-country", [{{
    type: "bar", orientation: "h",
    x: c.map(d => d.net_revenue_delta),
    y: c.map(d => d.country),
    marker: {{color: c.map(d => d.net_revenue_delta >= 0 ? P.good : P.bad)}},
    hovertemplate: "%{{y}}<br>Change " + CUR + " %{{x:,.0f}}<extra></extra>"
  }}], Object.assign({{}}, LAYOUT, {{
    height: 360, hovermode: "closest",
    margin: {{l: 120, r: 24, t: 16, b: 48}},
    xaxis: Object.assign({{}}, LAYOUT.xaxis, {{title: "Change in net revenue (" + CUR + ")"}})
  }}), CONFIG);
}})();

/* ---- 6. pareto ---- */
(function () {{
  const p = D.pareto;
  Plotly.newPlot("chart-pareto", [
    {{
      type: "bar", name: "Net revenue", x: p.labels, y: p.revenue,
      marker: {{color: P.accent}}, customdata: p.descriptions,
      hovertemplate: "%{{customdata}}<br>" + CUR + " %{{y:,.0f}}<extra></extra>"
    }},
    {{
      type: "scatter", mode: "lines+markers", name: "Cumulative share",
      x: p.labels, y: p.cumulative, yaxis: "y2",
      line: {{color: P.warn, width: 2}}, marker: {{size: 5}},
      hovertemplate: "Cumulative %{{y:.1f}}%<extra></extra>"
    }}
  ], Object.assign({{}}, LAYOUT, {{
    height: 360,
    yaxis: Object.assign({{}}, LAYOUT.yaxis, {{title: "Net revenue (" + CUR + ")"}}),
    yaxis2: {{overlaying: "y", side: "right", ticksuffix: "%", range: [0, 100],
             gridcolor: "rgba(0,0,0,0)"}},
    xaxis: Object.assign({{}}, LAYOUT.xaxis, {{tickangle: -45, type: "category"}})
  }}), CONFIG);
}})();

/* ---- 7. cohort heatmap ---- */
(function () {{
  const c = D.cohort;
  if (!c.cohorts.length) {{ document.getElementById("chart-cohort").innerHTML =
    '<p class="lead">Not enough cohort history in this source to draw a retention grid.</p>'; return; }}
  Plotly.newPlot("chart-cohort", [{{
    type: "heatmap", z: c.values, x: c.offsets, y: c.cohorts,
    colorscale: [[0, "#f8fafc"], [0.35, "#99f6e4"], [1, P.accent]],
    hoverongaps: false, colorbar: {{title: "%", thickness: 12, len: 0.8}},
    hovertemplate: "Cohort %{{y}}<br>+%{{x}} months<br>%{{z:.1f}}% still active<extra></extra>"
  }}], Object.assign({{}}, LAYOUT, {{
    height: 400, hovermode: "closest",
    margin: {{l: 78, r: 24, t: 16, b: 48}},
    xaxis: Object.assign({{}}, LAYOUT.xaxis, {{title: "Months since first order", dtick: 1}}),
    yaxis: Object.assign({{}}, LAYOUT.yaxis, {{title: "Acquisition cohort", autorange: "reversed"}})
  }}), CONFIG);
}})();

/* ---- 8. decliners ---- */
(function () {{
  const rows = D.decliners.map(d => `<tr>
      <td class="l">${{d.stock_code}}</td>
      <td class="l">${{d.description}}</td>
      <td class="l">${{d.product_family}}</td>
      <td>${{money(d.net_revenue_cmp)}}</td>
      <td>${{money(d.net_revenue_cur)}}</td>
      <td style="color:${{P.bad}}">${{money(d.net_revenue_delta)}}</td>
      <td>${{pct(d.return_rate_cur_pct, 1)}}</td>
    </tr>`).join("");
  document.getElementById("tbl-decliners").innerHTML =
    `<thead><tr><th class="l">Stock code</th><th class="l">Description</th><th class="l">Family</th>
      <th>${{D.meta.comparison_label}}</th><th>${{D.meta.current_label}}</th><th>Change</th>
      <th>Return rate</th></tr></thead><tbody>${{rows}}</tbody>`;
}})();

/* ---- 9. data quality + reconciliation ---- */
(function () {{
  const rows = D.dq.rules.map(r => {{
    const cls = r.rows_failed > 0 ? r.severity : "ok";
    return `<tr>
      <td class="l">${{r.rule_id}}</td>
      <td class="l">${{r.name}}</td>
      <td class="l">${{r.dimension}}</td>
      <td class="l"><span class="pill ${{cls}}">${{r.severity}}</span></td>
      <td class="l">${{r.action}}</td>
      <td>${{fmt(r.rows_checked)}}</td>
      <td>${{fmt(r.rows_failed)}}</td>
      <td>${{pct(r.fail_rate_pct, 2)}}</td>
    </tr>`;
  }}).join("");
  document.getElementById("tbl-dq").innerHTML =
    `<thead><tr><th class="l">Rule</th><th class="l">Check</th><th class="l">Dimension</th>
      <th class="l">Severity</th><th class="l">Action</th><th>Checked</th><th>Failed</th>
      <th>Rate</th></tr></thead><tbody>${{rows}}</tbody>`;

  const rrows = D.reconciliation.map(r => `<tr>
      <td class="l">${{r.metric}}</td>
      <td>${{fmt(r.fact_value, 2)}}</td>
      <td>${{fmt(r.mart_value, 2)}}</td>
      <td style="color:${{Math.abs(r.difference) > 0.05 ? P.bad : P.good}}">${{fmt(r.difference, 2)}}</td>
    </tr>`).join("");
  document.getElementById("tbl-recon").innerHTML =
    `<thead><tr><th class="l">Check</th><th>Fact table</th><th>KPI mart</th>
      <th>Difference</th></tr></thead><tbody>${{rrows}}</tbody>`;
}})();
</script>
</body>
</html>
"""
