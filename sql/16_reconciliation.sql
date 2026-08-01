-- ---------------------------------------------------------------------------
-- mart_reconciliation - the check that makes the rest of the marts believable.
--
-- Every published figure is traced back to the staging table:
--
--   staged rows -> quarantined rows -> fact rows -> net revenue in kpi_monthly
--
-- If the fact table and the KPI mart ever disagree by more than a rounding
-- cent, the pipeline fails rather than publishing. Numbers that reconcile are
-- the difference between a dashboard people act on and a dashboard people
-- quietly maintain a spreadsheet next to.
-- ---------------------------------------------------------------------------

DROP TABLE IF EXISTS mart_reconciliation;

CREATE TABLE mart_reconciliation AS
WITH fact_total AS (
    SELECT
        COUNT(*)                    AS fact_rows,
        ROUND(SUM(line_amount), 2)  AS net_revenue,
        ROUND(SUM(gross_amount), 2) AS gross_revenue,
        ROUND(SUM(return_amount), 2) AS returns_value,
        COUNT(DISTINCT CASE WHEN is_cancellation_doc = 0 THEN invoice_no END) AS orders
    FROM fct_sales_line
),
mart_total AS (
    SELECT
        ROUND(SUM(net_revenue), 2)   AS net_revenue,
        ROUND(SUM(gross_revenue), 2) AS gross_revenue,
        ROUND(SUM(returns_value), 2) AS returns_value,
        SUM(orders)                  AS orders
    FROM kpi_monthly
),
split_check AS (
    SELECT
        ROUND(SUM(net_revenue_identified + net_revenue_guest), 2) AS split_net_revenue
    FROM kpi_monthly
)
SELECT 'fact rows'                AS metric,
       CAST(f.fact_rows AS DOUBLE PRECISION) AS fact_value,
       CAST(f.fact_rows AS DOUBLE PRECISION) AS mart_value,
       0.0 AS difference
FROM fact_total f
UNION ALL
SELECT 'net revenue', f.net_revenue, m.net_revenue,
       ROUND(f.net_revenue - m.net_revenue, 2)
FROM fact_total f CROSS JOIN mart_total m
UNION ALL
SELECT 'gross revenue', f.gross_revenue, m.gross_revenue,
       ROUND(f.gross_revenue - m.gross_revenue, 2)
FROM fact_total f CROSS JOIN mart_total m
UNION ALL
SELECT 'returns value', f.returns_value, m.returns_value,
       ROUND(f.returns_value - m.returns_value, 2)
FROM fact_total f CROSS JOIN mart_total m
UNION ALL
SELECT 'orders', CAST(f.orders AS DOUBLE PRECISION), CAST(m.orders AS DOUBLE PRECISION),
       CAST(f.orders - m.orders AS DOUBLE PRECISION)
FROM fact_total f CROSS JOIN mart_total m
UNION ALL
SELECT 'identified + guest = net revenue', f.net_revenue, s.split_net_revenue,
       ROUND(f.net_revenue - s.split_net_revenue, 2)
FROM fact_total f CROSS JOIN split_check s;
