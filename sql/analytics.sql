-- Prepared CSV tables are written to data/processed/ by prepare_dashboard.py.
CREATE TABLE dim_date (
  date date PRIMARY KEY, year smallint, quarter text, month smallint,
  month_name text, month_start date, weekday text, weekday_num smallint
);
CREATE TABLE dim_product (stockcode text PRIMARY KEY, description text);
CREATE TABLE dim_customer (
  customerid bigint PRIMARY KEY, country text, first_order timestamp,
  orders integer, segment text
);
CREATE TABLE dim_country (country text PRIMARY KEY);
CREATE TABLE fact_sales (
  invoiceno text NOT NULL, stockcode text NOT NULL, customerid bigint,
  invoicedate timestamp NOT NULL, invoice_date date NOT NULL, quantity integer NOT NULL,
  unitprice numeric(12,4) NOT NULL, revenue numeric(14,4) NOT NULL,
  country text NOT NULL,
  FOREIGN KEY (stockcode) REFERENCES dim_product(stockcode),
  FOREIGN KEY (invoice_date) REFERENCES dim_date(date),
  FOREIGN KEY (customerid) REFERENCES dim_customer(customerid),
  FOREIGN KEY (country) REFERENCES dim_country(country)
);

-- Monthly performance (positive sales, cancellation invoices already excluded).
SELECT date_trunc('month', invoicedate)::date AS month,
       SUM(revenue) AS revenue_gbp,
       COUNT(DISTINCT invoiceno) AS orders,
       COUNT(DISTINCT customerid) AS identified_customers,
       SUM(quantity) AS units
FROM fact_sales
GROUP BY 1 ORDER BY 1;

-- Repeat-customer contribution. Customers without IDs are intentionally excluded.
WITH customer_value AS (
  SELECT customerid, COUNT(DISTINCT invoiceno) AS orders,
         SUM(revenue) AS revenue_gbp
  FROM fact_sales WHERE customerid IS NOT NULL GROUP BY customerid
)
SELECT CASE WHEN orders >= 2 THEN 'Repeat' ELSE 'One-time' END AS segment,
       COUNT(*) AS customers, SUM(revenue_gbp) AS revenue_gbp,
       AVG(revenue_gbp) AS avg_customer_revenue
FROM customer_value GROUP BY 1 ORDER BY 1;

-- Monthly retention by first-purchase cohort. Anonymous sales are excluded.
WITH customer_month AS (
  SELECT customerid, date_trunc('month', invoice_date)::date AS month_start
  FROM fact_sales WHERE customerid IS NOT NULL
  GROUP BY customerid, date_trunc('month', invoice_date)::date
), assigned AS (
  SELECT customerid, month_start,
         MIN(month_start) OVER (PARTITION BY customerid) AS cohort_month
  FROM customer_month
), cohort_counts AS (
  SELECT cohort_month,
         ((EXTRACT(YEAR FROM month_start) - EXTRACT(YEAR FROM cohort_month)) * 12
           + EXTRACT(MONTH FROM month_start) - EXTRACT(MONTH FROM cohort_month) + 1)::integer AS cohort_index,
         COUNT(DISTINCT customerid) AS active_customers
  FROM assigned GROUP BY 1, 2
), sized AS (
  SELECT c.*, MAX(active_customers) FILTER (WHERE cohort_index = 1)
           OVER (PARTITION BY cohort_month) AS cohort_size
  FROM cohort_counts c
)
SELECT cohort_month, cohort_index, active_customers, cohort_size,
       active_customers::numeric / NULLIF(cohort_size, 0) AS retention_rate
FROM sized ORDER BY cohort_month, cohort_index;

-- Product and country revenue concentration.
SELECT p.stockcode, p.description, SUM(f.revenue) AS revenue_gbp,
       SUM(f.quantity) AS units, COUNT(DISTINCT f.invoiceno) AS orders
FROM fact_sales f JOIN dim_product p USING (stockcode)
GROUP BY 1, 2 ORDER BY revenue_gbp DESC LIMIT 20;

SELECT country, SUM(revenue) AS revenue_gbp,
       COUNT(DISTINCT invoiceno) AS orders,
       COUNT(DISTINCT customerid) AS identified_customers
FROM fact_sales GROUP BY country ORDER BY revenue_gbp DESC;
