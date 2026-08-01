-- ---------------------------------------------------------------------------
-- mart_cohort_retention - customers grouped by the month of their first order.
--
-- Grain: one row per (cohort month, months since acquisition).
--
-- Retention is what separates "we sold less this month" from "we are losing
-- the base". The revenue decomposition tells you the active customer count
-- fell; this mart tells you whether it fell because acquisition dried up or
-- because existing cohorts stopped coming back.
--
-- Month arithmetic note: month_key is an integer of the form YYYYMM, so the
-- distance in months is (yyyy1-yyyy0)*12 + (mm1-mm0). Doing it this way keeps
-- the query free of engine-specific date functions.
-- ---------------------------------------------------------------------------

DROP TABLE IF EXISTS mart_cohort_retention;

CREATE TABLE mart_cohort_retention AS
WITH activity AS (
    SELECT DISTINCT
        f.customer_key,
        f.month_key AS active_month_key
    FROM fct_sales_line f
    WHERE f.customer_key <> :guest_key
      AND f.is_cancellation_doc = 0
),
cohorts AS (
    SELECT customer_key, cohort_month_key
    FROM dim_customer
    WHERE is_guest = 0
),
cohort_size AS (
    SELECT cohort_month_key, COUNT(*) AS cohort_customers
    FROM cohorts
    GROUP BY cohort_month_key
),
spread AS (
    SELECT
        c.cohort_month_key,
        a.active_month_key,
        (CAST(a.active_month_key / 100 AS INTEGER) - CAST(c.cohort_month_key / 100 AS INTEGER)) * 12
            + ((a.active_month_key % 100) - (c.cohort_month_key % 100)) AS months_since_first_order,
        a.customer_key
    FROM activity a
    JOIN cohorts c ON c.customer_key = a.customer_key
)
SELECT
    s.cohort_month_key,
    s.months_since_first_order,
    cs.cohort_customers,
    COUNT(DISTINCT s.customer_key) AS active_customers,
    ROUND(100.0 * COUNT(DISTINCT s.customer_key) / NULLIF(cs.cohort_customers, 0), 2)
        AS retention_pct
FROM spread s
JOIN cohort_size cs ON cs.cohort_month_key = s.cohort_month_key
WHERE s.months_since_first_order >= 0
GROUP BY s.cohort_month_key, s.months_since_first_order, cs.cohort_customers
ORDER BY s.cohort_month_key, s.months_since_first_order;
