# Findings and recommendations - 2011-11

> **SYNTHETIC DEMO SAMPLE.** This build ran against the offline fixture in `data/sample/`, not against the real UCI dataset. The figures below are therefore a demonstration of the method, not a statement about the real data. Run `python -m oakpi data && python -m oakpi run` to regenerate this document from the real source.

*Generated 2026-08-01 16:08 UTC by `oakpi` v1.0.0 from SYNTHETIC DEMO SAMPLE. Every figure in this document is read from the marts at build time; none of it is typed by hand.*

## 1. The answer in three sentences

Net revenue in **2011-11** was **GBP 283,005**, GBP 93,900 (-24.9%) below **2010-11**. The largest single driver is **active customers** (-GBP 32,687, 56% of the movement), followed by **orders per customer** (-GBP 22,935); the return rate moved +3.2 percentage points and is worth -GBP 8,055 on its own. The five factors add back to the total change with no residual, so nothing in this answer is hiding in an “other” bucket.

The recommended actions, in order of quantified value:

1. **Close the customer identification gap at checkout** - E-commerce with Data Governance
2. **Re-activate the shrinking active-customer base** - CRM with Sales
3. **Investigate the market that fell fastest** - Regional sales with Country management
4. **Contain the return rate on the worst-performing product family** - Category management with Quality and Returns Operations
5. **Fix the highest-severity data quality defect at source** - Data Governance with the source system owner

## 2. What changed

| KPI | 2010-11 | 2011-11 | Change |
|---|---:|---:|---:|
| Net revenue | GBP 376,905 | GBP 283,005 | -24.9% |
| Gross revenue | GBP 385,212 | GBP 298,936 | -22.4% |
| Returns | GBP 8,307 | GBP 15,932 | +91.8% |
| Return rate | 2.16% | 5.33% | +3.17 pp |
| Orders | 2,292 | 1,844 | -19.5% |
| Active customers (identified) | 725 | 639 | -11.9% |
| New customers | 132 | 86 | -34.8% |
| Average order value | GBP 164 | GBP 153 | -6.7% |
| Revenue per active customer | GBP 399 | GBP 361 | -9.6% |
| Guest revenue share | 23.23% | 18.52% | -4.71 pp |

## 3. Why it changed - driver decomposition

The KPI tree multiplies out to net revenue from identified customers:

```
net revenue = active customers
              x orders per customer
              x units per order
              x average unit price
              x (1 - return rate)
```

Contributions are computed with an additive **LMDI-I** index, so they sum to the total change with no residual and no factor is privileged by ordering. A chain-substitution cross-check is in the appendix.

| Factor | 2010-11 | 2011-11 | Change | Contribution (GBP) | Share of change |
|---|---|---|---|---|---|
| Active customers | 725.00 | 639.00 | -11.9% | -32,687 | 56% |
| Orders per customer | 2.48 | 2.27 | -8.5% | -22,935 | 39% |
| Units per order | 34.05 | 33.63 | -1.2% | -3,197 | 5% |
| Average unit price | 4.83 | 4.98 | +3.2% | 8,106 | -14% |
| Return retention | 0.98 | 0.95 | -3.1% | -8,055 | 14% |

*Share of change is signed against the overall movement. A negative share means the factor pushed in the opposite direction to the headline - it cushioned the move rather than causing it.*

**Reconciliation of the decomposition to the reported total**

| Component | Value |
|---|---:|
| Change in net revenue, all customers | -GBP 93,900 |
| of which identified customers (decomposed above) | -GBP 58,764 |
| of which guest orders (not attributable to a customer) | -GBP 35,137 |
| KPI tree rounding residual | GBP 4 |

## 4. Where the returns sit

`excess returns` is the value the period would have retained at the comparison period's return rate. It is the number that belongs in a business case, because it is the size of the prize from fixing the rate rather than the size of the problem.

| Family | Gross revenue 2011-11 | Return rate 2010-11 | Return rate 2011-11 | Excess returns (GBP) |
|---|---|---|---|---|
| GLASS | 41,652 | 1.74% | 18.18% | 6,846 |
| LANTERN | 39,308 | 1.81% | 4.25% | 958 |
| VINTAGE | 44,449 | 2.06% | 3.14% | 478 |
| STORAGE | 93,421 | 2.87% | 3.38% | 476 |
| CERAMIC | 38,509 | 1.99% | 3.05% | 405 |
| PAPER | 39,219 | 1.91% | 2.45% | 212 |
| NON_PRODUCT | 2,379 | 0.00% | 0.00% | 0 |

## 5. Which markets moved

| Market | Net revenue 2010-11 | Net revenue 2011-11 | Change | Customers 2010-11 | Customers 2011-11 |
|---|---|---|---|---|---|
| United Kingdom | 243,592 | 203,453 | -40,139 | 614 | 551 |
| Unidentified | 87,542 | 52,406 | -35,137 | 0 | 0 |
| Germany | 14,003 | 4,815 | -9,189 | 29 | 18 |
| France | 11,805 | 9,111 | -2,694 | 25 | 21 |
| Belgium | 3,851 | 1,700 | -2,151 | 10 | 8 |
| Australia | 2,652 | 719 | -1,932 | 6 | 2 |
| Portugal | 1,296 | 125 | -1,171 | 6 | 2 |
| EIRE | 4,943 | 3,870 | -1,073 | 12 | 10 |

## 6. Which articles moved

**Largest declines**

| Stock code | Description | 2010-11 | 2011-11 | Change | Return rate |
|---|---|---|---|---|---|
| 20417 | RED VINTAGE NOTEBOOK | 17,737 | 2,576 | -15,162 | 6.9% |
| 20364 | WHITE PAPER JAR | 17,159 | 2,468 | -14,691 | 1.1% |
| 20055 | RED GLASS SIGN | 12,459 | 1,891 | -10,568 | 12.1% |
| 20529 | GREEN STORAGE LUNCH BAG | 15,330 | 8,873 | -6,457 | 5.1% |
| 20531 | GREEN STORAGE DOORSTOP | 11,172 | 7,182 | -3,990 | 3.0% |
| 20036 | PINK GLASS CAKE STAND | 6,285 | 2,561 | -3,723 | 29.3% |
| 20522 | WHITE STORAGE CANDLE PLATE | 11,846 | 8,548 | -3,298 | 3.0% |
| 20352 | GREEN PAPER CANDLE PLATE | 9,982 | 6,925 | -3,058 | 3.9% |

The 20 highest-revenue articles carry 50% of sellable net revenue in 2011-11, out of 120 articles sold.

## 7. Is the customer base holding

Share of each acquisition cohort still buying **3 months** after its first order. Cohorts below 20 customers are suppressed, and so is any cohort whose +3 month has not finished yet - an open window always reads as a collapse.

| Cohort | Customers acquired | Still active at +3m | Retention |
|---|---|---|---|
| 2010-09 | 114 | 65 | 57.0% |
| 2010-10 | 123 | 43 | 35.0% |
| 2010-11 | 132 | 43 | 32.6% |
| 2010-12 | 107 | 43 | 40.2% |
| 2011-01 | 59 | 25 | 42.4% |
| 2011-02 | 79 | 33 | 41.8% |
| 2011-03 | 78 | 34 | 43.6% |
| 2011-04 | 71 | 32 | 45.1% |
| 2011-05 | 79 | 27 | 34.2% |
| 2011-06 | 74 | 30 | 40.5% |
| 2011-07 | 68 | 28 | 41.2% |
| 2011-08 | 69 | 33 | 47.8% |

## 8. Recommendations

### R4 - Close the customer identification gap at checkout

**Finding.** **19%** of net revenue in the period carries no customer id (GBP 52,406). That revenue is invisible to retention, cohort and lifetime value analysis, so every customer KPI in this report is computed on the remaining 81%.

**Action.** Treat identification rate as an owned operational KPI: capture an identifier at checkout, backfill by order-to-email matching where consent allows, and target a measurable reduction.

**Owner.** E-commerce with Data Governance  
**Trigger.** This recommendation appears when more than 10% of net revenue arrives without a customer id.

### R2 - Re-activate the shrinking active-customer base

**Finding.** Active identified customers moved -11.9% and account for **56%** of the total change, worth -GBP 32,687. The movement is in how many customers bought, not in what they spent. New customers moved -35% and returning customers -7%, so the shortfall is **acquisition led**.

**Action.** Treat this as a top-of-funnel problem: review acquisition spend and channel mix before spending on win-back, and track the active-customer factor rather than revenue as the campaign KPI.

**Owner.** CRM with Sales  
**Trigger.** This recommendation appears when the active customer factor contributes more than a quarter of the total revenue change.

### R6 - Investigate the market that fell fastest

**Finding.** **Germany** fell -66% against an overall -25%, a gap of 41 percentage points, on 29 to 18 active customers. That is a market-specific problem sitting inside a group-level number.

**Action.** Check the market's own funnel before reading anything into the group figure: local competitor entry, a delivery or pricing change, or a lapsed key account. A group-level campaign will not fix a single-market cause.

**Owner.** Regional sales with Country management  
**Trigger.** This recommendation appears when a market worth at least 2% of period revenue falls more than 15 percentage points faster than the group.

### R1 - Contain the return rate on the worst-performing product family

**Finding.** The **GLASS** family returned 18.2% of gross revenue in 2011-11, against 1.7% in 2010-11. Holding last period's rate would have retained **GBP 6,846**, equal to 2.4% of period net revenue.

**Action.** Pull the return reason codes for the family's top ten stock codes, separate quality defects from expectation gaps (imagery, sizing, description), and re-test the rate four weeks after the fix.

**Owner.** Category management with Quality and Returns Operations  
**Trigger.** This recommendation appears when the family with the largest excess return value costs more than 1% of period net revenue.

### R5 - Fix the highest-severity data quality defect at source

**Finding.** Rule **DQ005 - Unit price is not negative** removed 172 rows (0.15% of those checked). Blocker defects are repaired downstream on every single run, which is cost paid repeatedly for a problem that exists once, upstream.

**Action.** Raise a change request against the source system with the quarantine extract attached, and keep the rule as a regression guard after the fix.

**Owner.** Data Governance with the source system owner  
**Trigger.** This recommendation appears when any blocker-severity rule quarantines rows.

## 9. How far these numbers can be trusted

- Data quality score: **99.12 / 100** (severity-weighted share of checks passed).
- Rows read from source: **115,207**; quarantined and excluded from all KPIs: **823** (0.71%). Every excluded row is retrievable from the `quarantine` table together with the rule that removed it.
- Customer-level KPIs cover the 81% of net revenue that carries a customer id.
- The reporting month was selected as the most recent **complete** month in the source, so no part-month is compared against a full one.

**Rules that fired**

| Rule | Check | Dimension | Severity | Action | Rows | Rate |
|---|---|---|---|---|---|---|
| DQ007 | Customer id present | completeness | minor | flag | 24,358 | 21.14% |
| DQ013 | Description normalised | consistency | minor | fix | 2,305 | 2.00% |
| DQ006 | Unit price is greater than zero for sellable products | validity | major | flag | 616 | 0.55% |
| DQ012 | Product description present | completeness | minor | fix | 563 | 0.49% |
| DQ010 | No exact duplicate transaction lines | uniqueness | major | quarantine | 344 | 0.30% |
| DQ005 | Unit price is not negative | validity | blocker | quarantine | 172 | 0.15% |
| DQ004 | Quantity is not zero | validity | major | quarantine | 138 | 0.12% |
| DQ011 | Cancellation lines carry a negative quantity | consistency | major | flag | 75 | 2.04% |
| DQ001 | Invoice id present | completeness | blocker | quarantine | 68 | 0.06% |
| DQ002 | Invoice date present and parseable | validity | blocker | quarantine | 57 | 0.05% |
| DQ003 | Stock code present | completeness | major | quarantine | 45 | 0.04% |
| DQ008 | Quantity within plausible range | accuracy | minor | flag | 45 | 0.04% |
| DQ009 | Unit price within plausible range | accuracy | minor | flag | 35 | 0.03% |

**Reconciliation**

| Check | Fact table | KPI mart | Difference |
|---|---|---|---|
| fact rows | 114,384.00 | 114,384.00 | 0.00 |
| net revenue | 4,360,194.74 | 4,360,194.74 | 0.00 |
| gross revenue | 4,526,325.43 | 4,526,325.43 | 0.00 |
| returns value | 166,130.69 | 166,130.69 | 0.00 |
| orders | 27,751.00 | 27,751.00 | 0.00 |
| identified + guest = net revenue | 4,360,194.74 | 4,360,194.74 | 0.00 |

The pipeline aborts rather than publishing if any difference exceeds 0.05 in absolute value.

## Appendix - chain substitution cross-check

The same change decomposed by sequential substitution (*Kettensubstitutionsverfahren*), in the factor order given above. It reaches the same total but assigns the interaction terms to whichever factor is substituted first, which is why LMDI is reported as the headline.

| Factor | Contribution (GBP) |
|---|---|
| Active customers | -34,325 |
| Orders per customer | -21,623 |
| Units per order | -2,865 |
| Average unit price | 7,333 |
| Return retention | -7,288 |
