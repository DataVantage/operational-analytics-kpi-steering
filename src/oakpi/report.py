"""Generation of the written findings.

Every number in the published markdown is read out of the marts at build time.
Nothing is typed by hand, which means the document cannot drift away from the
pipeline, and re-running against a different period or a different source
produces a correspondingly different document rather than a stale one.

The recommendations are produced by a small set of explicit trigger rules
(:data:`INSIGHT_RULES`). Each rule states the condition that fires it and the
figure it quantifies. That is a deliberate choice: an analyst should be able to
disagree with the threshold, and to see immediately which threshold produced a
given sentence.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# formatting helpers
# ---------------------------------------------------------------------------

def money(value: float, currency: str = "GBP") -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}{currency} {abs(value):,.0f}"


def pct(value: float, digits: int = 1) -> str:
    return f"{value:+.{digits}f}%"


def _table(df: pd.DataFrame, columns: dict[str, str], formatters: dict | None = None) -> str:
    """Render a dataframe as a GitHub markdown table."""
    formatters = formatters or {}
    head = "| " + " | ".join(columns.values()) + " |"
    rule = "|" + "|".join("---" for _ in columns) + "|"
    lines = [head, rule]
    for _, row in df.iterrows():
        cells = []
        for key in columns:
            value = row[key]
            fmt = formatters.get(key)
            cells.append(fmt(value) if fmt else str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# insight rules
# ---------------------------------------------------------------------------

INSIGHT_RULES = [
    {
        "id": "R1",
        "title": "Contain the return rate on the worst-performing product family",
        "when": "the family with the largest excess return value costs more than "
                "1% of period net revenue",
        "owner": "Category management with Quality and Returns Operations",
    },
    {
        "id": "R2",
        "title": "Re-activate the shrinking active-customer base",
        "when": "the active customer factor contributes more than a quarter of "
                "the total revenue change",
        "owner": "CRM with Sales",
    },
    {
        "id": "R3",
        "title": "Protect concentrated revenue with named-account cover",
        "when": "the top 20 accounts carry more than 25% of period net revenue",
        "owner": "Key account management",
    },
    {
        "id": "R4",
        "title": "Close the customer identification gap at checkout",
        "when": "more than 10% of net revenue arrives without a customer id",
        "owner": "E-commerce with Data Governance",
    },
    {
        "id": "R5",
        "title": "Fix the highest-severity data quality defect at source",
        "when": "any blocker-severity rule quarantines rows",
        "owner": "Data Governance with the source system owner",
    },
    {
        "id": "R6",
        "title": "Investigate the market that fell fastest",
        "when": "a market worth at least 2% of period revenue falls more than "
                "15 percentage points faster than the group",
        "owner": "Regional sales with Country management",
    },
]


def _safe_pct(current: float, comparison: float) -> float:
    """Percentage change that returns 0 rather than raising on a zero base."""
    current, comparison = float(current), float(comparison)
    return 100.0 * (current - comparison) / comparison if comparison else 0.0


def _build_recommendations(marts: dict, ctx: dict) -> list[dict]:
    cur_key = ctx["periods"]["current"]["month_key"]
    monthly = marts["kpi_monthly"]
    cur = monthly[monthly["month_key"] == cur_key].iloc[0]
    currency = ctx["currency"]
    net_revenue = float(cur["net_revenue"])
    out: list[dict] = []

    # R1 - returns
    fam = marts["returns_family"]
    if len(fam):
        worst = fam.sort_values("excess_returns_value", ascending=False).iloc[0]
        excess = float(worst["excess_returns_value"])
        if net_revenue > 0 and excess > 0.01 * net_revenue:
            out.append(
                {
                    **INSIGHT_RULES[0],
                    "finding": (
                        f"The **{worst['product_family']}** family returned "
                        f"{worst['return_rate_cur_pct']:.1f}% of gross revenue in "
                        f"{ctx['periods']['current']['label']}, against "
                        f"{worst['return_rate_cmp_pct']:.1f}% in "
                        f"{ctx['periods']['comparison']['label']}. Holding last "
                        f"period's rate would have retained "
                        f"**{money(excess, currency)}**, equal to "
                        f"{100 * excess / net_revenue:.1f}% of period net revenue."
                    ),
                    "action": (
                        "Pull the return reason codes for the family's top ten stock "
                        "codes, separate quality defects from expectation gaps "
                        "(imagery, sizing, description), and re-test the rate four "
                        "weeks after the fix."
                    ),
                    "value": excess,
                }
            )

    # R2 - customer base
    decomposition = marts["decomposition"]
    total_change = float(decomposition["contribution"].sum())
    cust = decomposition[decomposition["factor"] == "active_customers"]
    if len(cust) and total_change != 0:
        share = float(cust["share_of_change_pct"].iat[0])
        contribution = float(cust["contribution"].iat[0])
        if share > 25:
            # Is the base shrinking because fewer customers are acquired, or
            # because acquired customers stop coming back? The two need
            # different owners and different budgets, so the recommendation
            # branches on the evidence instead of hedging.
            cmp_row = monthly[
                monthly["month_key"] == ctx["periods"]["comparison"]["month_key"]
            ].iloc[0]
            new_change = _safe_pct(cur["new_customers"], cmp_row["new_customers"])
            ret_change = _safe_pct(cur["returning_customers"], cmp_row["returning_customers"])
            acquisition_led = new_change < ret_change
            diagnosis = (
                f"New customers moved {new_change:+.0f}% and returning customers "
                f"{ret_change:+.0f}%, so the shortfall is "
                + ("**acquisition led**" if acquisition_led else "**retention led**")
                + "."
            )
            action = (
                "Treat this as a top-of-funnel problem: review acquisition spend "
                "and channel mix before spending on win-back, and track the "
                "active-customer factor rather than revenue as the campaign KPI."
                if acquisition_led else
                "Treat this as a retention problem: target the cohorts whose curve "
                "breaks first with a re-activation contact, and measure the "
                "campaign against the active-customer factor rather than revenue."
            )
            out.append(
                {
                    **INSIGHT_RULES[1],
                    "finding": (
                        f"Active identified customers moved "
                        f"{cust['change_pct'].iat[0]:+.1f}% and account for "
                        f"**{share:.0f}%** of the total change, worth "
                        f"{money(contribution, currency)}. The movement is in how "
                        f"many customers bought, not in what they spent. {diagnosis}"
                    ),
                    "action": action,
                    "value": abs(contribution),
                }
            )

    # R6 - a single market carrying disproportionate decline
    countries = marts["countries"]
    # Materiality is applied *before* ranking. Ranking first would hand the
    # headline to whichever micro-market happened to lose its only customer.
    named = countries[
        (~countries["country"].isin(["Unidentified"]))
        & (countries["net_revenue_cmp"] >= 0.02 * float(cur["net_revenue"]))
    ]
    if len(named):
        worst = named.nsmallest(1, "net_revenue_change_pct").iloc[0]
        overall_pct = _safe_pct(cur["net_revenue"], monthly[
            monthly["month_key"] == ctx["periods"]["comparison"]["month_key"]
        ].iloc[0]["net_revenue"])
        gap = float(worst["net_revenue_change_pct"]) - overall_pct
        if gap < -15:
            out.append(
                {
                    **INSIGHT_RULES[5],
                    "finding": (
                        f"**{worst['country']}** fell "
                        f"{float(worst['net_revenue_change_pct']):.0f}% against an "
                        f"overall {overall_pct:.0f}%, a gap of "
                        f"{abs(gap):.0f} percentage points, on "
                        f"{int(worst['active_customers_cmp'])} to "
                        f"{int(worst['active_customers_cur'])} active customers. "
                        f"That is a market-specific problem sitting inside a "
                        f"group-level number."
                    ),
                    "action": (
                        "Check the market's own funnel before reading anything into "
                        "the group figure: local competitor entry, a delivery or "
                        "pricing change, or a lapsed key account. A group-level "
                        "campaign will not fix a single-market cause."
                    ),
                    "value": abs(float(worst["net_revenue_delta"])),
                }
            )

    # R3 - concentration
    conc = marts["concentration"]
    if len(conc):
        total = float(conc["net_revenue"].sum())
        top20 = float(conc.nsmallest(20, "revenue_rank")["net_revenue"].sum())
        share = 100 * top20 / total if total else 0.0
        if share > 25:
            out.append(
                {
                    **INSIGHT_RULES[2],
                    "finding": (
                        f"The 20 largest accounts carry **{share:.0f}%** of identified "
                        f"net revenue ({money(top20, currency)}). At this "
                        f"concentration a single lost account is a forecast event, "
                        f"not a rounding difference."
                    ),
                    "action": (
                        "Move the top 20 into a named-account review with an explicit "
                        "owner and a monthly revenue-at-risk flag, and report "
                        "concentration alongside revenue every month."
                    ),
                    "value": top20,
                }
            )

    # R4 - identification gap
    guest_share = float(cur["guest_revenue_share_pct"])
    if guest_share > 10:
        out.append(
            {
                **INSIGHT_RULES[3],
                "finding": (
                    f"**{guest_share:.0f}%** of net revenue in the period carries no "
                    f"customer id ({money(float(cur['net_revenue_guest']), currency)}). "
                    f"That revenue is invisible to retention, cohort and lifetime "
                    f"value analysis, so every customer KPI in this report is "
                    f"computed on the remaining {100 - guest_share:.0f}%."
                ),
                "action": (
                    "Treat identification rate as an owned operational KPI: capture "
                    "an identifier at checkout, backfill by order-to-email matching "
                    "where consent allows, and target a measurable reduction."
                ),
                "value": float(cur["net_revenue_guest"]),
            }
        )

    # R5 - data quality
    dq_report = marts["dq_report"]
    blockers = dq_report[(dq_report["severity"] == "blocker") & (dq_report["rows_failed"] > 0)]
    if len(blockers):
        worst = blockers.sort_values("rows_failed", ascending=False).iloc[0]
        out.append(
            {
                **INSIGHT_RULES[4],
                "finding": (
                    f"Rule **{worst['rule_id']} - {worst['name']}** removed "
                    f"{int(worst['rows_failed']):,} rows "
                    f"({worst['fail_rate_pct']:.2f}% of those checked). Blocker "
                    f"defects are repaired downstream on every single run, which is "
                    f"cost paid repeatedly for a problem that exists once, upstream."
                ),
                "action": (
                    "Raise a change request against the source system with the "
                    "quarantine extract attached, and keep the rule as a regression "
                    "guard after the fix."
                ),
                "value": float(worst["rows_failed"]),
            }
        )

    return out


# ---------------------------------------------------------------------------
# document
# ---------------------------------------------------------------------------

def write(cfg, marts: dict, ctx: dict) -> Path:
    path = cfg.path("output.findings_file")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(marts, ctx), encoding="utf-8")
    log.info("Wrote findings: %s", path)
    return path


def render(marts: dict, ctx: dict) -> str:
    currency = ctx["currency"]
    cur_label = ctx["periods"]["current"]["label"]
    cmp_label = ctx["periods"]["comparison"]["label"]
    monthly = marts["kpi_monthly"]
    cur = monthly[monthly["month_key"] == ctx["periods"]["current"]["month_key"]].iloc[0]
    cmp_ = monthly[monthly["month_key"] == ctx["periods"]["comparison"]["month_key"]].iloc[0]
    bridge = ctx["bridge"]
    decomposition = marts["decomposition"]
    recommendations = _build_recommendations(marts, ctx)

    delta = bridge["net_revenue_delta"]
    delta_pct = 100 * delta / bridge["net_revenue_comparison"] if bridge["net_revenue_comparison"] else 0.0
    direction = "below" if delta < 0 else "above"

    parts: list[str] = []
    a = parts.append

    # -- header ------------------------------------------------------------
    a(f"# Findings and recommendations - {cur_label}\n")
    if ctx["is_synthetic"]:
        a(
            "> **SYNTHETIC DEMO SAMPLE.** This build ran against the offline "
            "fixture in `data/sample/`, not against the real UCI dataset. The "
            "figures below are therefore a demonstration of the method, not a "
            "statement about the real data. Run `python -m oakpi data && "
            "python -m oakpi run` to regenerate this document from the real "
            "source.\n"
        )
    a(
        f"*Generated {ctx['generated_at']} by `oakpi` v{ctx['version']} from "
        f"{ctx['source_label']}. Every figure in this document is read from the "
        f"marts at build time; none of it is typed by hand.*\n"
    )

    # -- executive summary -------------------------------------------------
    a("## 1. The answer in three sentences\n")
    top = decomposition.reindex(decomposition["contribution"].abs().sort_values(ascending=False).index)
    lead = top.iloc[0]
    second = top.iloc[1]
    returns_factor = decomposition[decomposition["factor"] == "revenue_retained"].iloc[0]
    a(
        f"Net revenue in **{cur_label}** was **{money(bridge['net_revenue_current'], currency)}**, "
        f"{money(abs(delta), currency)} ({pct(delta_pct)}) {direction} **{cmp_label}**. "
        f"The largest single driver is **{lead['label'].lower()}** "
        f"({money(lead['contribution'], currency)}, {abs(lead['share_of_change_pct']):.0f}% of the "
        f"movement), followed by **{second['label'].lower()}** "
        f"({money(second['contribution'], currency)}); the return rate moved "
        f"{float(cur['return_rate_pct']) - float(cmp_['return_rate_pct']):+.1f} percentage "
        f"points and is worth {money(returns_factor['contribution'], currency)} on its own. "
        f"The five factors add back to the total change with no residual, so nothing "
        f"in this answer is hiding in an “other” bucket.\n"
    )
    if recommendations:
        a("The recommended actions, in order of quantified value:\n")
        for i, rec in enumerate(sorted(recommendations, key=lambda r: -r["value"]), start=1):
            a(f"{i}. **{rec['title']}** - {rec['owner']}")
        a("")

    # -- period comparison -------------------------------------------------
    a("## 2. What changed\n")
    kpi_rows = [
        ("Net revenue", cur["net_revenue"], cmp_["net_revenue"], "money"),
        ("Gross revenue", cur["gross_revenue"], cmp_["gross_revenue"], "money"),
        ("Returns", cur["returns_value"], cmp_["returns_value"], "money"),
        ("Return rate", cur["return_rate_pct"], cmp_["return_rate_pct"], "pct_abs"),
        ("Orders", cur["orders"], cmp_["orders"], "int"),
        ("Active customers (identified)", cur["active_customers"], cmp_["active_customers"], "int"),
        ("New customers", cur["new_customers"], cmp_["new_customers"], "int"),
        ("Average order value", cur["aov"], cmp_["aov"], "money"),
        ("Revenue per active customer", cur["revenue_per_active_customer"],
         cmp_["revenue_per_active_customer"], "money"),
        ("Guest revenue share", cur["guest_revenue_share_pct"],
         cmp_["guest_revenue_share_pct"], "pct_abs"),
    ]
    a(f"| KPI | {cmp_label} | {cur_label} | Change |")
    a("|---|---:|---:|---:|")
    for name, c, p, kind in kpi_rows:
        c, p = float(c), float(p)
        if kind == "money":
            cs, ps = money(c, currency), money(p, currency)
            change = pct(100 * (c - p) / p) if p else "n/a"
        elif kind == "int":
            cs, ps = f"{int(c):,}", f"{int(p):,}"
            change = pct(100 * (c - p) / p) if p else "n/a"
        else:
            cs, ps = f"{c:.2f}%", f"{p:.2f}%"
            change = f"{c - p:+.2f} pp"
        a(f"| {name} | {ps} | {cs} | {change} |")
    a("")

    # -- decomposition -----------------------------------------------------
    a("## 3. Why it changed - driver decomposition\n")
    a(
        "The KPI tree multiplies out to net revenue from identified customers:\n\n"
        "```\n"
        "net revenue = active customers\n"
        "              x orders per customer\n"
        "              x units per order\n"
        "              x average unit price\n"
        "              x (1 - return rate)\n"
        "```\n"
    )
    a(
        "Contributions are computed with an additive **LMDI-I** index, so they sum "
        "to the total change with no residual and no factor is privileged by "
        "ordering. A chain-substitution cross-check is in the appendix.\n"
    )
    a(_table(
        decomposition,
        {
            "label": "Factor",
            "value_comparison": cmp_label,
            "value_current": cur_label,
            "change_pct": "Change",
            "contribution": f"Contribution ({currency})",
            "share_of_change_pct": "Share of change",
        },
        {
            "value_comparison": lambda v: f"{v:,.2f}",
            "value_current": lambda v: f"{v:,.2f}",
            "change_pct": lambda v: f"{v:+.1f}%",
            "contribution": lambda v: f"{v:,.0f}",
            "share_of_change_pct": lambda v: f"{v:.0f}%",
        },
    ))
    a("")
    a(
        "*Share of change is signed against the overall movement. A negative "
        "share means the factor pushed in the opposite direction to the "
        "headline - it cushioned the move rather than causing it.*\n"
    )
    a("**Reconciliation of the decomposition to the reported total**\n")
    a("| Component | Value |")
    a("|---|---:|")
    a(f"| Change in net revenue, all customers | {money(bridge['net_revenue_delta'], currency)} |")
    a(f"| of which identified customers (decomposed above) | {money(bridge['identified_delta'], currency)} |")
    a(f"| of which guest orders (not attributable to a customer) | {money(bridge['guest_delta'], currency)} |")
    a(f"| KPI tree rounding residual | {money(bridge['tree_residual'], currency)} |")
    a("")

    # -- returns -----------------------------------------------------------
    fam = marts["returns_family"]
    if len(fam):
        a("## 4. Where the returns sit\n")
        a(
            "`excess returns` is the value the period would have retained at the "
            "comparison period's return rate. It is the number that belongs in a "
            "business case, because it is the size of the prize from fixing the "
            "rate rather than the size of the problem.\n"
        )
        a(_table(
            fam.head(8),
            {
                "product_family": "Family",
                "gross_revenue_cur": f"Gross revenue {cur_label}",
                "return_rate_cmp_pct": f"Return rate {cmp_label}",
                "return_rate_cur_pct": f"Return rate {cur_label}",
                "excess_returns_value": f"Excess returns ({currency})",
            },
            {
                "gross_revenue_cur": lambda v: f"{v:,.0f}",
                "return_rate_cmp_pct": lambda v: f"{v:.2f}%",
                "return_rate_cur_pct": lambda v: f"{v:.2f}%",
                "excess_returns_value": lambda v: f"{v:,.0f}",
            },
        ))
        a("")

    # -- markets -----------------------------------------------------------
    countries = marts["countries"]
    if len(countries):
        a("## 5. Which markets moved\n")
        movers = countries.reindex(
            countries["net_revenue_delta"].abs().sort_values(ascending=False).index
        ).head(8)
        a(_table(
            movers,
            {
                "country": "Market",
                "net_revenue_cmp": f"Net revenue {cmp_label}",
                "net_revenue_cur": f"Net revenue {cur_label}",
                "net_revenue_delta": "Change",
                "active_customers_cmp": f"Customers {cmp_label}",
                "active_customers_cur": f"Customers {cur_label}",
            },
            {
                "net_revenue_cmp": lambda v: f"{v:,.0f}",
                "net_revenue_cur": lambda v: f"{v:,.0f}",
                "net_revenue_delta": lambda v: f"{v:,.0f}",
            },
        ))
        a("")

    # -- products ----------------------------------------------------------
    products = marts["products"]
    sellable = products[products["is_non_product"] == 0]
    if len(sellable):
        a("## 6. Which articles moved\n")
        a("**Largest declines**\n")
        a(_table(
            sellable.nsmallest(8, "net_revenue_delta"),
            {
                "stock_code": "Stock code",
                "description": "Description",
                "net_revenue_cmp": cmp_label,
                "net_revenue_cur": cur_label,
                "net_revenue_delta": "Change",
                "return_rate_cur_pct": "Return rate",
            },
            {
                "net_revenue_cmp": lambda v: f"{v:,.0f}",
                "net_revenue_cur": lambda v: f"{v:,.0f}",
                "net_revenue_delta": lambda v: f"{v:,.0f}",
                "return_rate_cur_pct": lambda v: "n/a" if pd.isna(v) else f"{v:.1f}%",
            },
        ))
        a("")
        top_share = sellable.nsmallest(20, "revenue_rank")["net_revenue_cur"].sum()
        total_share = sellable["net_revenue_cur"].sum()
        if total_share:
            a(
                f"The 20 highest-revenue articles carry "
                f"{100 * top_share / total_share:.0f}% of sellable net revenue in "
                f"{cur_label}, out of {len(sellable):,} articles sold.\n"
            )

    # -- retention ---------------------------------------------------------
    a("## 7. Is the customer base holding\n")
    from .analysis import retention_summary, shift_month

    horizon = ctx["retention_horizon"]
    ret = retention_summary(marts["cohort"], horizon)
    ret = ret[ret["cohort_customers"] >= 20]
    # A cohort can only be judged at +horizon months once that month has
    # actually finished. Without this filter the newest cohorts always look
    # like a collapse, because their window is still open.
    complete = monthly[monthly["is_complete_month"] == 1]["month_key"]
    last_complete = int(complete.max()) if len(complete) else int(monthly["month_key"].max())
    ret = ret[
        ret["cohort_month_key"].apply(lambda k: shift_month(int(k), horizon)) <= last_complete
    ].tail(12)
    if len(ret):
        a(
            f"Share of each acquisition cohort still buying **{horizon} months** "
            f"after its first order. Cohorts below 20 customers are suppressed, "
            f"and so is any cohort whose +{horizon} month has not finished yet - "
            f"an open window always reads as a collapse.\n"
        )
        a(_table(
            ret,
            {
                "cohort_month_key": "Cohort",
                "cohort_customers": "Customers acquired",
                "active_customers": f"Still active at +{horizon}m",
                "retention_pct": "Retention",
            },
            {
                "cohort_month_key": lambda v: f"{int(v) // 100}-{int(v) % 100:02d}",
                "cohort_customers": lambda v: f"{int(v):,}",
                "active_customers": lambda v: f"{int(v):,}",
                "retention_pct": lambda v: f"{v:.1f}%",
            },
        ))
        a("")

    # -- recommendations ---------------------------------------------------
    a("## 8. Recommendations\n")
    if not recommendations:
        a(
            "No trigger rule fired for this period. The rule set and its "
            "thresholds are listed in `src/oakpi/report.py`; a period with no "
            "recommendation is a result, not a gap.\n"
        )
    for rec in sorted(recommendations, key=lambda r: -r["value"]):
        a(f"### {rec['id']} - {rec['title']}\n")
        a(f"**Finding.** {rec['finding']}\n")
        a(f"**Action.** {rec['action']}\n")
        a(f"**Owner.** {rec['owner']}  ")
        a(f"**Trigger.** This recommendation appears when {rec['when']}.\n")

    # -- trust -------------------------------------------------------------
    a("## 9. How far these numbers can be trusted\n")
    a(
        f"- Data quality score: **{ctx['dq_score']:.2f} / 100** "
        f"(severity-weighted share of checks passed).\n"
        f"- Rows read from source: **{ctx['rows_read']:,}**; quarantined and "
        f"excluded from all KPIs: **{ctx['rows_quarantined']:,}** "
        f"({ctx['quarantine_rate']:.2f}%). Every excluded row is retrievable "
        f"from the `quarantine` table together with the rule that removed it.\n"
        f"- Customer-level KPIs cover the "
        f"{100 - float(cur['guest_revenue_share_pct']):.0f}% of net revenue that "
        f"carries a customer id.\n"
        f"- The reporting month was selected as the most recent **complete** "
        f"month in the source, so no part-month is compared against a full one.\n"
    )
    dq_report = marts["dq_report"]
    firing = dq_report[dq_report["rows_failed"] > 0]
    if len(firing):
        a("**Rules that fired**\n")
        a(_table(
            firing.sort_values("rows_failed", ascending=False),
            {
                "rule_id": "Rule",
                "name": "Check",
                "dimension": "Dimension",
                "severity": "Severity",
                "action": "Action",
                "rows_failed": "Rows",
                "fail_rate_pct": "Rate",
            },
            {
                "rows_failed": lambda v: f"{int(v):,}",
                "fail_rate_pct": lambda v: f"{v:.2f}%",
            },
        ))
        a("")

    recon = marts["reconciliation"]
    a("**Reconciliation**\n")
    a(_table(
        recon,
        {"metric": "Check", "fact_value": "Fact table", "mart_value": "KPI mart",
         "difference": "Difference"},
        {
            "fact_value": lambda v: f"{v:,.2f}",
            "mart_value": lambda v: f"{v:,.2f}",
            "difference": lambda v: f"{v:,.2f}",
        },
    ))
    a("\nThe pipeline aborts rather than publishing if any difference exceeds "
      "0.05 in absolute value.\n")

    # -- appendix ----------------------------------------------------------
    a("## Appendix - chain substitution cross-check\n")
    a(
        "The same change decomposed by sequential substitution "
        "(*Kettensubstitutionsverfahren*), in the factor order given above. It "
        "reaches the same total but assigns the interaction terms to whichever "
        "factor is substituted first, which is why LMDI is reported as the "
        "headline.\n"
    )
    chain = marts["chain"]
    a(_table(
        chain,
        {"label": "Factor", "contribution": f"Contribution ({currency})"},
        {"contribution": lambda v: f"{v:,.0f}"},
    ))
    a("")
    return "\n".join(parts)
