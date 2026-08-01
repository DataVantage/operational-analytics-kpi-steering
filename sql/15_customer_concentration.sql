-- ---------------------------------------------------------------------------
-- mart_customer_concentration - how much of the period rests on how few accounts.
--
-- Grain: one row per identified customer active in the current period.
--
-- Concentration is a risk KPI, not a vanity KPI. If the top twenty accounts
-- carry a third of net revenue, then a single churned account is a forecast
-- event, and the retention conversation belongs with named accounts rather
-- than with a segment average.
-- ---------------------------------------------------------------------------

DROP TABLE IF EXISTS mart_customer_concentration;

CREATE TABLE mart_customer_concentration AS
WITH cur AS (
    SELECT
        f.customer_key,
        SUM(f.line_amount)  AS net_revenue,
        SUM(f.return_amount) AS returns_value,
        COUNT(DISTINCT CASE WHEN f.is_cancellation_doc = 0 THEN f.invoice_no END) AS orders
    FROM fct_sales_line f
    WHERE f.month_key = :current_month_key
      AND f.customer_key <> :guest_key
    GROUP BY f.customer_key
),
prior AS (
    SELECT f.customer_key, SUM(f.line_amount) AS net_revenue_cmp
    FROM fct_sales_line f
    WHERE f.month_key = :comparison_month_key
      AND f.customer_key <> :guest_key
    GROUP BY f.customer_key
)
SELECT
    c.customer_key,
    dc.customer_id,
    dc.country,
    dc.cohort_label,
    ROUND(c.net_revenue, 2)   AS net_revenue,
    ROUND(COALESCE(p.net_revenue_cmp, 0), 2) AS net_revenue_cmp,
    ROUND(c.returns_value, 2) AS returns_value,
    c.orders,
    ROW_NUMBER() OVER (ORDER BY c.net_revenue DESC) AS revenue_rank,
    ROUND(100.0 * SUM(c.net_revenue) OVER (
              ORDER BY c.net_revenue DESC
              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
          / NULLIF(SUM(c.net_revenue) OVER (), 0), 2) AS cumulative_revenue_share_pct
FROM cur c
JOIN dim_customer dc ON dc.customer_key = c.customer_key
LEFT JOIN prior p    ON p.customer_key = c.customer_key
ORDER BY c.net_revenue DESC;
