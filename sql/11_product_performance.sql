-- ---------------------------------------------------------------------------
-- mart_product_period - product performance, current period vs comparison.
--
-- Grain: one row per product.
--
-- The window function at the end turns the table into a Pareto view: products
-- are ranked by net revenue in the current period and carry their running
-- share of it, so "how much of the miss sits in how few articles" is a lookup
-- rather than a calculation.
-- ---------------------------------------------------------------------------

DROP TABLE IF EXISTS mart_product_period;

CREATE TABLE mart_product_period AS
WITH scoped AS (
    SELECT
        f.product_key,
        CASE WHEN f.month_key = :current_month_key THEN 'current' ELSE 'comparison' END AS period,
        f.gross_amount,
        f.return_amount,
        f.line_amount,
        f.units_sold,
        f.invoice_no,
        f.is_cancellation_doc
    FROM fct_sales_line f
    WHERE f.month_key IN (:current_month_key, :comparison_month_key)
),
agg AS (
    SELECT
        product_key,
        SUM(CASE WHEN period = 'current'    THEN line_amount   ELSE 0 END) AS net_revenue_cur,
        SUM(CASE WHEN period = 'comparison' THEN line_amount   ELSE 0 END) AS net_revenue_cmp,
        SUM(CASE WHEN period = 'current'    THEN gross_amount  ELSE 0 END) AS gross_revenue_cur,
        SUM(CASE WHEN period = 'comparison' THEN gross_amount  ELSE 0 END) AS gross_revenue_cmp,
        SUM(CASE WHEN period = 'current'    THEN return_amount ELSE 0 END) AS returns_cur,
        SUM(CASE WHEN period = 'comparison' THEN return_amount ELSE 0 END) AS returns_cmp,
        SUM(CASE WHEN period = 'current'    THEN units_sold    ELSE 0 END) AS units_cur,
        SUM(CASE WHEN period = 'comparison' THEN units_sold    ELSE 0 END) AS units_cmp,
        COUNT(DISTINCT CASE WHEN period = 'current' AND is_cancellation_doc = 0
                            THEN invoice_no END) AS orders_cur
    FROM scoped
    GROUP BY product_key
),
joined AS (
    SELECT
        p.product_key,
        p.stock_code,
        p.description,
        p.product_family,
        p.is_non_product,
        ROUND(a.net_revenue_cur, 2)   AS net_revenue_cur,
        ROUND(a.net_revenue_cmp, 2)   AS net_revenue_cmp,
        ROUND(a.net_revenue_cur - a.net_revenue_cmp, 2) AS net_revenue_delta,
        ROUND(a.gross_revenue_cur, 2) AS gross_revenue_cur,
        ROUND(a.gross_revenue_cmp, 2) AS gross_revenue_cmp,
        ROUND(a.returns_cur, 2)       AS returns_cur,
        ROUND(a.returns_cmp, 2)       AS returns_cmp,
        a.units_cur,
        a.units_cmp,
        a.orders_cur,
        ROUND(100.0 * a.returns_cur / NULLIF(a.gross_revenue_cur, 0), 2) AS return_rate_cur_pct,
        ROUND(100.0 * a.returns_cmp / NULLIF(a.gross_revenue_cmp, 0), 2) AS return_rate_cmp_pct,
        ROUND(100.0 * (a.net_revenue_cur - a.net_revenue_cmp)
              / NULLIF(ABS(a.net_revenue_cmp), 0), 2) AS net_revenue_change_pct
    FROM agg a
    JOIN dim_product p ON p.product_key = a.product_key
)
SELECT
    j.*,
    ROW_NUMBER() OVER (ORDER BY net_revenue_cur DESC) AS revenue_rank,
    ROUND(100.0 * SUM(net_revenue_cur) OVER (
              ORDER BY net_revenue_cur DESC
              ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
          / NULLIF(SUM(net_revenue_cur) OVER (), 0), 2) AS cumulative_revenue_share_pct
FROM joined j
ORDER BY net_revenue_cur DESC;
