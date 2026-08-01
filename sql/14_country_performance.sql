-- ---------------------------------------------------------------------------
-- mart_country_period - the same period comparison, sliced by market.
--
-- Grain: one row per country.
--
-- Country sits on the customer dimension rather than the fact, so guest lines
-- carry no market. They are reported as "Unidentified" instead of being
-- silently dropped, because dropping them would break reconciliation against
-- kpi_monthly - and a slice that does not add up to the headline is a slice
-- nobody will trust twice.
-- ---------------------------------------------------------------------------

DROP TABLE IF EXISTS mart_country_period;

CREATE TABLE mart_country_period AS
WITH scoped AS (
    SELECT
        c.country,
        CASE WHEN f.month_key = :current_month_key THEN 'current' ELSE 'comparison' END AS period,
        f.line_amount,
        f.gross_amount,
        f.return_amount,
        f.invoice_no,
        f.is_cancellation_doc,
        CASE WHEN f.customer_key = :guest_key THEN NULL ELSE f.customer_key END AS customer_key
    FROM fct_sales_line f
    JOIN dim_customer c ON c.customer_key = f.customer_key
    WHERE f.month_key IN (:current_month_key, :comparison_month_key)
)
SELECT
    country,
    ROUND(SUM(CASE WHEN period = 'current'    THEN line_amount ELSE 0 END), 2) AS net_revenue_cur,
    ROUND(SUM(CASE WHEN period = 'comparison' THEN line_amount ELSE 0 END), 2) AS net_revenue_cmp,
    ROUND(SUM(CASE WHEN period = 'current'    THEN line_amount ELSE 0 END)
        - SUM(CASE WHEN period = 'comparison' THEN line_amount ELSE 0 END), 2) AS net_revenue_delta,
    ROUND(100.0 * (SUM(CASE WHEN period = 'current' THEN line_amount ELSE 0 END)
                 - SUM(CASE WHEN period = 'comparison' THEN line_amount ELSE 0 END))
          / NULLIF(ABS(SUM(CASE WHEN period = 'comparison' THEN line_amount ELSE 0 END)), 0), 2)
        AS net_revenue_change_pct,
    COUNT(DISTINCT CASE WHEN period = 'current' THEN customer_key END)    AS active_customers_cur,
    COUNT(DISTINCT CASE WHEN period = 'comparison' THEN customer_key END) AS active_customers_cmp,
    COUNT(DISTINCT CASE WHEN period = 'current' AND is_cancellation_doc = 0
                        THEN invoice_no END) AS orders_cur,
    COUNT(DISTINCT CASE WHEN period = 'comparison' AND is_cancellation_doc = 0
                        THEN invoice_no END) AS orders_cmp,
    ROUND(100.0 * SUM(CASE WHEN period = 'current' THEN return_amount ELSE 0 END)
          / NULLIF(SUM(CASE WHEN period = 'current' THEN gross_amount ELSE 0 END), 0), 2)
        AS return_rate_cur_pct
FROM scoped
GROUP BY country
ORDER BY net_revenue_cur DESC;
