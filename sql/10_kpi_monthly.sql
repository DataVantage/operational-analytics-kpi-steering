-- ---------------------------------------------------------------------------
-- kpi_monthly - the single monthly KPI mart every downstream artefact reads.
--
-- Grain: one row per calendar month.
--
-- The measures are laid out so that the KPI tree multiplies out exactly:
--
--   net revenue = customers x orders/customer x units/order x price/unit
--                 x (1 - return rate)
--
-- Each factor is a column here, so the driver decomposition never has to
-- re-derive anything and the identity can be asserted in a unit test.
--
-- Two conventions worth stating explicitly:
--   * Orders are counted on non-cancellation documents only. A credit note is
--     not a second order.
--   * Customer-level factors are computed on identified customers only.
--     Roughly a fifth of revenue arrives with no customer id and would
--     otherwise inflate "revenue per customer" without inflating the count.
--     Guest revenue is carried as its own column and reconciled separately.
-- ---------------------------------------------------------------------------

DROP TABLE IF EXISTS kpi_monthly;

CREATE TABLE kpi_monthly AS
WITH lines AS (
    SELECT
        f.month_key,
        d.month_label,
        d.year,
        d.quarter_label,
        d.is_complete_month,
        f.invoice_no,
        f.customer_key,
        f.gross_amount,
        f.return_amount,
        f.line_amount,
        f.units_sold,
        f.units_returned,
        f.is_cancellation_doc,
        CASE WHEN f.customer_key = :guest_key THEN 0 ELSE 1 END AS is_identified
    FROM fct_sales_line f
    JOIN dim_date d ON d.date_key = f.date_key
),
base AS (
    SELECT
        month_key,
        MIN(month_label)      AS month_label,
        MIN(year)             AS year,
        MIN(quarter_label)    AS quarter_label,
        MAX(is_complete_month) AS is_complete_month,

        SUM(gross_amount)     AS gross_revenue,
        SUM(return_amount)    AS returns_value,
        SUM(line_amount)      AS net_revenue,
        SUM(units_sold)       AS units_gross,
        SUM(units_returned)   AS units_returned,
        COUNT(DISTINCT CASE WHEN is_cancellation_doc = 0 THEN invoice_no END) AS orders,
        COUNT(DISTINCT CASE WHEN is_cancellation_doc = 1 THEN invoice_no END) AS credit_notes,

        SUM(CASE WHEN is_identified = 1 THEN gross_amount  ELSE 0 END) AS gross_revenue_identified,
        SUM(CASE WHEN is_identified = 1 THEN return_amount ELSE 0 END) AS returns_value_identified,
        SUM(CASE WHEN is_identified = 1 THEN line_amount   ELSE 0 END) AS net_revenue_identified,
        SUM(CASE WHEN is_identified = 1 THEN units_sold    ELSE 0 END) AS units_gross_identified,
        SUM(CASE WHEN is_identified = 0 THEN line_amount   ELSE 0 END) AS net_revenue_guest,

        COUNT(DISTINCT CASE WHEN is_identified = 1 THEN customer_key END) AS active_customers,
        COUNT(DISTINCT CASE WHEN is_identified = 1 AND is_cancellation_doc = 0
                            THEN invoice_no END) AS orders_identified
    FROM lines
    GROUP BY month_key
),
new_customers AS (
    SELECT cohort_month_key AS month_key, COUNT(*) AS new_customers
    FROM dim_customer
    WHERE is_guest = 0
    GROUP BY cohort_month_key
)
SELECT
    b.month_key,
    b.month_label,
    b.year,
    b.quarter_label,
    b.is_complete_month,

    ROUND(b.gross_revenue, 2)  AS gross_revenue,
    ROUND(b.returns_value, 2)  AS returns_value,
    ROUND(b.net_revenue, 2)    AS net_revenue,
    ROUND(b.net_revenue_guest, 2)      AS net_revenue_guest,
    ROUND(b.net_revenue_identified, 2) AS net_revenue_identified,
    ROUND(b.gross_revenue_identified, 2) AS gross_revenue_identified,

    b.units_gross,
    b.units_returned,
    b.units_gross_identified,
    b.orders,
    b.orders_identified,
    b.credit_notes,
    b.active_customers,
    COALESCE(n.new_customers, 0) AS new_customers,
    b.active_customers - COALESCE(n.new_customers, 0) AS returning_customers,

    -- KPI tree factors, computed on the identified population.
    ROUND(1.0 * b.orders_identified / NULLIF(b.active_customers, 0), 4)
        AS orders_per_customer,
    ROUND(1.0 * b.units_gross_identified / NULLIF(b.orders_identified, 0), 4)
        AS units_per_order,
    ROUND(1.0 * b.gross_revenue_identified / NULLIF(b.units_gross_identified, 0), 4)
        AS avg_unit_price,
    ROUND(1.0 * b.returns_value_identified / NULLIF(b.gross_revenue_identified, 0), 6)
        AS return_rate_identified,

    -- Headline ratios reported to the business.
    ROUND(100.0 * b.returns_value / NULLIF(b.gross_revenue, 0), 4) AS return_rate_pct,
    ROUND(1.0 * b.net_revenue / NULLIF(b.orders, 0), 2)            AS aov,
    ROUND(1.0 * b.net_revenue_identified / NULLIF(b.active_customers, 0), 2)
        AS revenue_per_active_customer,
    ROUND(100.0 * b.net_revenue_guest / NULLIF(b.net_revenue, 0), 2)
        AS guest_revenue_share_pct
FROM base b
LEFT JOIN new_customers n ON n.month_key = b.month_key
ORDER BY b.month_key;
