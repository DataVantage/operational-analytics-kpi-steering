# 1. The business question

## Context

A UK-based online giftware retailer sells to a mix of small independent shops and
direct consumers, across the UK and eleven other markets. Roughly 4,000 stock
codes, a few thousand active accounts, strong Q4 seasonality, and a returns
process that is handled as credit notes against the original invoice.

The commercial review meets monthly. The pack that goes into that meeting has,
historically, been a revenue chart and a top-ten product table.

## The question actually being asked

> *"Net revenue in the last complete month is behind the same month last year.
> Where did it go, how much of the gap can we actually get back, and what do we
> do on Monday?"*

Note what is **not** being asked:

- Not "what was revenue" — they can already see that.
- Not "build a dashboard" — that is a possible answer, not the question.
- Not "which model predicts revenue" — nobody in that room will act on a
  prediction they cannot decompose.

The question has three parts, and a useful answer needs all three:

| Part | What it demands |
|---|---|
| *Where did it go* | A decomposition whose parts add back to the whole, exactly |
| *How much is recoverable* | A counterfactual — what the period would have earned if the broken thing had not broken |
| *What do we do* | A named owner, a specific action, and a number attached to it |

## Why "revenue is down 25%" is not an answer

Net revenue is a product of five independent things. Any of them can move on its
own, and they routinely move against each other:

```
net revenue = active customers        how many customers bought
              × orders per customer   how often they bought
              × units per order        how much they bought each time
              × average unit price     what they paid per unit
              × (1 − return rate)      how much of it stayed sold
```

A 25% drop could be 4,000 lost customers, or the same customers ordering half as
often, or a price cut, or a quality problem pushing returns up — and each of
those has a different owner, a different budget and a different lead time. A
single number cannot distinguish them, and a chart of that single number cannot
either.

Worse, the factors mask each other. In the demo build, average unit price rose
enough to offset roughly a third of the damage from the customer decline. Read
off the headline alone, that improvement is invisible; read off the
decomposition, it is a lever someone deliberately pulled and should keep pulling.

## Scope

**In scope**

- Monthly net revenue and its five drivers, group-wide and by market
- Returns as a first-class KPI, at product-family and article level
- Customer cohort retention and revenue concentration
- Data quality as a published, scored layer rather than an invisible step

**Out of scope, and why**

- *Gross margin.* The source has no cost of goods. Every "value at stake" figure
  in this project is therefore revenue, not margin, and is labelled as such.
  Overstating a revenue figure as a margin figure is how business cases lose
  credibility on the second slide.
- *Forecasting.* The question is diagnostic, not predictive. A forecast built
  before the drivers are understood forecasts the wrong thing accurately.
- *Marketing attribution.* No channel or campaign data exists in the source.

## What "done" looks like

The pipeline is finished when someone who was not in the room can:

1. read one paragraph and know what happened,
2. see which of five factors caused it and by how much,
3. see how much money is recoverable and from what,
4. find the owner and the action next to the number,
5. check what data was excluded, under which rule, and why,
6. reproduce every figure from raw source with one command.

Points 5 and 6 are the ones that get skipped, and they are the ones that decide
whether the analysis is believed the second time it disagrees with somebody's
intuition.
