# 3. The data quality framework

## Why this is a layer and not a cleanup script

Most analysis projects contain a cell that quietly does this:

```python
df = df[df["Quantity"] > 0]
df = df.dropna(subset=["Customer ID"])
```

Two lines, and the analysis is now wrong in a way nobody can see. The first
deletes every return, so the revenue total no longer matches the P&L. The second
deletes a fifth of the revenue, so every total in the report is understated —
and neither the number of removed rows nor the reason for removing them appears
anywhere in the output.

This project treats data quality as a **governed layer** with three properties:

1. **Rules are declared, not coded.** They live in
   [`config/dq_rules.yml`](../config/dq_rules.yml) where an analyst who does not
   read Python can review, argue with and change them.
2. **Every rule carries a written rationale**, and that rationale is published in
   the report. A rule nobody can justify is a rule that should not exist.
3. **Nothing disappears silently.** `rows_in == rows_clean + rows_quarantined` is
   asserted in the test suite, and every quarantined row keeps the id of the rule
   that removed it.

---

## Three actions, three different decisions

Deleting a row is the most destructive option available, so it is the last one
reached for, not the default.

### `fix` — repair deterministically, and say how

Used where the correct value is recoverable from the data itself.

| Rule | Defect | Repair |
|---|---|---|
| DQ012 | Missing description | Filled from the most frequent description for that stock code; falls back to `UNKNOWN PRODUCT` only if the code never carries one |
| DQ013 | Casing and whitespace noise | Trimmed and upper-cased |

DQ013 looks cosmetic and is not. `"red mug  "`, `"Red Mug"` and `"RED MUG"` are
three rows in every `GROUP BY` in the project. Left alone it fragments the
product dimension and quietly understates every top-N table.

### `flag` — keep the row, mark the row

Used where the row is **valid revenue but unusable for some purpose**. The row
stays in the fact table with its money intact and a boolean column set.

| Rule | Defect | Why it must not be removed |
|---|---|---|
| DQ007 | No customer id (~21% of lines) | Real revenue. Removing it understates every total by a fifth. It simply cannot enter retention, cohort or lifetime-value analysis |
| DQ006 | Zero-priced product line | Giveaways, samples or entry errors. Must not drag average unit price down unnoticed |
| DQ008 | Implausible quantity | Genuine wholesale orders exist in this source. They are not errors, but they distort averages and should be excludable in a sensitivity check |
| DQ009 | Implausible unit price | Mostly manual adjustments and postage corrections |
| DQ011 | Cancellation prefix, positive quantity | The invoice prefix and the sign disagree; the line cannot be trusted for return-rate reporting |

DQ007 is the rule that carries the most weight in this project. Roughly a fifth
of revenue has no customer attached. The only honest handling is to keep the
money, route the row to a guest segment, exclude it from customer KPIs, and
**publish the share** so every reader knows the denominator they are looking at.

### `quarantine` — remove, but leave a receipt

Used where the row cannot support any analysis at all.

| Rule | Severity | Defect |
|---|---|---|
| DQ001 | blocker | No invoice id — cannot be attributed to an order |
| DQ002 | blocker | No parseable timestamp — cannot be assigned to a period |
| DQ005 | blocker | Negative unit price — adjustment postings, not sales |
| DQ003 | major | No stock code — the product dimension keys on it |
| DQ004 | major | Zero quantity — no revenue, no units, an editing artefact |
| DQ010 | major | Exact duplicate line — a source re-export; keeping it double counts |

Quarantined rows go to the `quarantine` table with a `quarantine_rule_id`
column. When someone asks "why is November GBP 4,000 lower than in the source
system", the answer is a query, not an archaeology project.

---

## Severity and the score

```
score = 100 × (1 − Σ(rows_failed × weight) / Σ(rows_checked × weight))

blocker = 5   major = 3   minor = 1
```

Weighting matters. Without it, 24,000 rows missing a customer id (minor,
expected, handled) would dominate 68 rows missing an invoice id (blocker,
unexpected, unhandleable) and the headline number would move for the wrong
reason.

The score is a gate as well as a metric: `--min-dq-score` aborts the run below a
configurable floor. A pipeline that publishes regardless of its input quality is
a pipeline that will eventually publish something embarrassing.

---

## Rule evaluation order

Rules are evaluated `fix` → `flag` → `quarantine`, not in the order they are
written. A repaired row must be judged on its repaired value, and a row that is
about to be removed should not first be flagged for a defect that no longer
matters.

Within `quarantine`, the **first** rule to catch a row owns it. A row with both
a missing invoice id and a zero quantity is attributed to DQ001, so the counts
stay additive and no row appears twice in the exclusion tally.

---

## Adding a rule

1. Add a block to `config/dq_rules.yml` with `id`, `name`, `dimension`,
   `severity`, `action` and — required — a `rationale` written for a business
   reader.
2. If the check does not already exist, add it to `_evaluate` in
   [`src/oakpi/dq.py`](../src/oakpi/dq.py).
3. Add a row to the fixture in `tests/test_data_quality.py` that triggers it, and
   assert the behaviour you expect.

Available checks: `not_null`, `not_equal`, `greater_than`, `greater_equal`,
`less_equal`, `abs_less_equal`, `duplicate_rows`, `cancellation_consistency`,
`whitespace_and_case`. Thresholds can be literal (`value`) or read from the
configuration (`value_from`) so that a business rule is defined once and used
everywhere.

---

## The six dimensions in use

| Dimension | Question it answers | Rules |
|---|---|---|
| **Completeness** | Is the value there at all? | DQ001, DQ003, DQ007, DQ012 |
| **Validity** | Is the value possible? | DQ002, DQ004, DQ005, DQ006 |
| **Accuracy** | Is the value plausible? | DQ008, DQ009 |
| **Uniqueness** | Is the row counted once? | DQ010 |
| **Consistency** | Do two fields agree? | DQ011 |
| **Timeliness** | Is the period closed? | Handled in period selection rather than as a row-level rule — see `analysis.resolve_periods` |

Timeliness deliberately sits outside the row-level rule set. It is not a
property of a row; it is a property of a *period*, and it is enforced by
refusing to select an incomplete month as a reporting period.
