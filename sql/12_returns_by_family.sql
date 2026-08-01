-- ---------------------------------------------------------------------------
-- mart_returns_family / mart_returns_monthly
--
-- Returns are the factor in the KPI tree that is easiest to ignore and most
-- expensive to ignore: they hit revenue, logistics cost and customer trust at
-- the same time. These two marts answer "where" and "since when".
--
-- The `min_revenue_for_return_rate` guard exists because a return rate is a
-- ratio, and a ratio built on a two-line denominator will always outrank a
-- real problem in a sorted table.
-- ---------------------------------------------------------------------------

DROP TABLE IF EXISTS mart_returns_family;

CREATE TABLE mart_returns_family AS
WITH scoped AS (
    SELECT
        p.product_family,
        CASE WHEN f.month_key = :current_month_key THEN 'current' ELSE 'comparison' END AS period,
        f.gross_amount,
        f.return_amount,
        f.line_amount
    FROM fct_sales_line f
    JOIN dim_product p ON p.product_key = f.product_key
    WHERE f.month_key IN (:current_month_key, :comparison_month_key)
)
SELECT
    product_family,
    ROUND(SUM(CASE WHEN period = 'current'    THEN gross_amount  ELSE 0 END), 2) AS gross_revenue_cur,
    ROUND(SUM(CASE WHEN period = 'comparison' THEN gross_amount  ELSE 0 END), 2) AS gross_revenue_cmp,
    ROUND(SUM(CASE WHEN period = 'current'    THEN return_amount ELSE 0 END), 2) AS returns_cur,
    ROUND(SUM(CASE WHEN period = 'comparison' THEN return_amount ELSE 0 END), 2) AS returns_cmp,
    ROUND(SUM(CASE WHEN period = 'current'    THEN line_amount   ELSE 0 END), 2) AS net_revenue_cur,
    ROUND(SUM(CASE WHEN period = 'comparison' THEN line_amount   ELSE 0 END), 2) AS net_revenue_cmp,
    ROUND(100.0 * SUM(CASE WHEN period = 'current' THEN return_amount ELSE 0 END)
          / NULLIF(SUM(CASE WHEN period = 'current' THEN gross_amount ELSE 0 END), 0), 2)
        AS return_rate_cur_pct,
    ROUND(100.0 * SUM(CASE WHEN period = 'comparison' THEN return_amount ELSE 0 END)
          / NULLIF(SUM(CASE WHEN period = 'comparison' THEN gross_amount ELSE 0 END), 0), 2)
        AS return_rate_cmp_pct,
    -- Value at stake: what the current period would have kept at last year's
    -- return rate. This is the number that belongs in a business case.
    ROUND(
        SUM(CASE WHEN period = 'current' THEN return_amount ELSE 0 END)
        - SUM(CASE WHEN period = 'current' THEN gross_amount ELSE 0 END)
          * (SUM(CASE WHEN period = 'comparison' THEN return_amount ELSE 0 END)
             / NULLIF(SUM(CASE WHEN period = 'comparison' THEN gross_amount ELSE 0 END), 0))
    , 2) AS excess_returns_value
FROM scoped
GROUP BY product_family
HAVING SUM(CASE WHEN period = 'current' THEN gross_amount ELSE 0 END) >= :min_revenue
ORDER BY excess_returns_value DESC;


DROP TABLE IF EXISTS mart_returns_monthly;

CREATE TABLE mart_returns_monthly AS
SELECT
    f.month_key,
    d.month_label,
    p.product_family,
    ROUND(SUM(f.gross_amount), 2)  AS gross_revenue,
    ROUND(SUM(f.return_amount), 2) AS returns_value,
    ROUND(100.0 * SUM(f.return_amount) / NULLIF(SUM(f.gross_amount), 0), 2) AS return_rate_pct
FROM fct_sales_line f
JOIN dim_product p ON p.product_key = f.product_key
JOIN dim_date d    ON d.date_key    = f.date_key
GROUP BY f.month_key, d.month_label, p.product_family
HAVING SUM(f.gross_amount) > 0
ORDER BY f.month_key, p.product_family;
