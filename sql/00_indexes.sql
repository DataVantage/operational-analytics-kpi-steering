-- ---------------------------------------------------------------------------
-- Indexes on the star schema.
--
-- The fact table is queried almost exclusively by month and by dimension key,
-- so those are the indexes that matter. They are created after the load rather
-- than before, because building an index once over a finished table is cheaper
-- than maintaining it during a bulk insert.
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS ix_fact_month      ON fct_sales_line (month_key);
CREATE INDEX IF NOT EXISTS ix_fact_date       ON fct_sales_line (date_key);
CREATE INDEX IF NOT EXISTS ix_fact_customer   ON fct_sales_line (customer_key);
CREATE INDEX IF NOT EXISTS ix_fact_product    ON fct_sales_line (product_key);
CREATE INDEX IF NOT EXISTS ix_date_month      ON dim_date (month_key);
CREATE INDEX IF NOT EXISTS ix_customer_cohort ON dim_customer (cohort_month_key);
