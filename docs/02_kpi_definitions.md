# 2. KPI definitions

A KPI that is not defined precisely enough to be re-derived is not a KPI, it is a
number in a meeting. Every metric below states its formula, its grain, its
population and its known limitations. Where two defensible definitions exist,
the one chosen is stated *and so is the one rejected*.

All of these are materialised in [`sql/10_kpi_monthly.sql`](../sql/10_kpi_monthly.sql).

---

## Conventions used throughout

| Term | Definition |
|---|---|
| **Line** | One row of an invoice: an article, a quantity and a unit price |
| **Order** | One invoice that is *not* a cancellation document |
| **Credit note** | An invoice whose id begins with `C` — a return, never counted as an order |
| **Signed amount** | `quantity × unit_price`. Returns carry a negative quantity, so the sign takes care of itself and no `CASE` expression is needed downstream |
| **Identified customer** | A line carrying a customer id |
| **Guest** | A line with no customer id — real revenue, unusable for customer metrics |
| **Reporting period** | The most recent month that is *complete in the source* |

---

## Revenue

### Gross revenue

```
gross_revenue = Σ (quantity × unit_price)   where quantity > 0
```

Sales before returns. Grain: any slice. Population: all lines, guest included.

### Returns value

```
returns_value = −Σ (quantity × unit_price)  where quantity < 0
```

Reported as a **positive** number so it reads naturally in a table. Includes
credit notes raised in the period against orders placed in an earlier one —
returns are recognised when the credit is raised, matching how the cash actually
moves.

> **Limitation.** In a month where sales collapse but returns from the previous
> quarter arrive as normal, the return *rate* will spike for a reason that has
> nothing to do with product quality. The monthly return-rate series in the
> dashboard exists specifically so this can be spotted rather than mis-read.

### Net revenue — the headline

```
net_revenue = gross_revenue − returns_value = Σ (quantity × unit_price)
```

This is the number in the first KPI card and the one every decomposition
targets.

**Rejected alternative:** counting only positive lines and reporting returns
separately. That would make the headline flattering and non-comparable to the
P&L, which is the fastest way to lose finance's trust in a dashboard.

---

## The KPI tree

The five factors below multiply to net revenue from identified customers. The
identity holds to within floating-point noise and is asserted in
[`tests/test_analysis.py`](../tests/test_analysis.py); the residual is published
in the report rather than hidden.

```
net revenue = active customers × orders per customer × units per order
              × average unit price × (1 − return rate)
```

### 1. Active customers

```
active_customers = COUNT(DISTINCT customer_key)   where customer_key ≠ guest
```

A customer is active in a month if they appear on at least one line, order or
credit note. Grain: month.

**Population note.** Guests are excluded. They have no stable identity, so
counting them would mean counting the same person repeatedly, or not at all —
and there is no way to know which. Guest revenue is carried in a separate column
and reconciled to the headline in the report, so the two halves visibly add up.

### 2. Orders per customer

```
orders_per_customer = orders_identified / active_customers
```

Purchase frequency. Both numerator and denominator are restricted to identified
customers so the ratio is internally consistent.

### 3. Units per order

```
units_per_order = units_gross_identified / orders_identified
```

Basket size in units, before returns. Returns are handled by factor 5 rather
than being netted here — netting them into basket size would let a returns
problem masquerade as a demand problem, which is exactly the confusion this
project exists to resolve.

### 4. Average unit price

```
avg_unit_price = gross_revenue_identified / units_gross_identified
```

The **realised** price per unit, mix included. It moves when list prices change,
*and* when the mix shifts toward more expensive articles. That is intentional:
the commercial question is what was actually earned per unit, not what the price
list said.

**Rejected alternative:** a mix-adjusted price index. More correct in isolation,
but it requires a stable product hierarchy the source does not have, and it
would be a derived number nobody in the meeting could re-derive.

### 5. Return retention

```
return_rate      = returns_value_identified / gross_revenue_identified
return_retention = 1 − return_rate
```

The share of gross revenue that stayed sold. Expressed as retention rather than
as a rate so that all five factors point the same way: **every factor going up
is good.** In a waterfall chart read by non-analysts, that is not cosmetic.

---

## Reported ratios

| KPI | Formula | Note |
|---|---|---|
| **Return rate** | `returns_value / gross_revenue` | Reported on the full population including guests, unlike the tree factor |
| **Average order value** | `net_revenue / orders` | Net of returns, full population |
| **Revenue per active customer** | `net_revenue_identified / active_customers` | Identified only |
| **New customers** | Count of customers whose cohort month = this month | From `dim_customer.cohort_month_key` |
| **Returning customers** | `active_customers − new_customers` | The split that separates an acquisition problem from a retention problem |
| **Guest revenue share** | `net_revenue_guest / net_revenue` | The measurement blind spot, published rather than hidden |

---

## Diagnostic metrics

### Cohort retention

```
retention_pct(cohort c, offset n) = active customers from c in month (c + n)
                                    / total customers acquired in c
```

A customer is counted as active at offset `n` if they placed at least one order
in that month — not "at any point since". The stricter definition is the one
that shows churn.

**Two suppressions, both deliberate:**

- Cohorts under 20 customers are hidden — a 3-customer cohort produces retention
  values of 0%, 33% or 67% and nothing in between.
- Cohorts whose `+n` month has not finished are hidden. An open window always
  reads as a collapse, and that artefact has ended more than one real analysis
  in the wrong conclusion.

### Excess returns — the business-case number

```
excess_returns = returns_current
                 − gross_revenue_current × return_rate_comparison
```

What the period would have retained at the comparison period's return rate. This
is the number that belongs in a business case: it is the **size of the prize from
fixing the rate**, not the size of the problem. The distinction matters — total
returns include the baseline rate, which nobody is going to eliminate.

Reported only for families above `analysis.min_revenue_for_return_rate`, because
a ratio built on a two-line denominator will otherwise top every sorted table.

### Revenue concentration

```
cumulative_revenue_share_pct = running Σ net revenue (desc) / total net revenue
```

Computed over customers and over articles. Concentration is a **risk** KPI: if
the top twenty accounts carry a third of revenue, a single churned account is a
forecast event and retention belongs with named accounts, not with a segment
average.

---

## Data quality score

```
score = 100 × (1 − Σ(rows_failed × weight) / Σ(rows_checked × weight))

weights: blocker 5 · major 3 · minor 1
```

One number, trendable month over month, and enforceable: `--min-dq-score` stops
the build below a floor. Severity weighting means a thousand cosmetic casing
issues cost less than a hundred rows with no invoice date — which is the
behaviour a steering committee expects from a headline number.

---

## Known limitations, stated up front

1. **No cost data.** Every value figure is revenue, never margin.
2. **~20% of revenue is unattributable.** All customer-level KPIs are computed on
   the remaining ~80%, and that share is published on every build.
3. **Product families are derived from description keywords.** The source has no
   category column. It is a documented approximation and belongs in a governed
   product master in production.
4. **Returns are recognised on the credit-note date**, not the original order
   date, so a month's return rate is not a cohort measure of that month's sales.
5. **The two source workbook sheets overlap in December 2010.** Exact duplicate
   lines are quarantined by rule DQ010; near-duplicates that differ in a single
   field are not detectable and remain.
