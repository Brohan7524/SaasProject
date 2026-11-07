-- 02_cohort_retention.sql
-- QUESTION: Of the employees who made their first booking in month M (their "cohort"),
-- what share are still booking N months later?
--
-- cohort_month = month of the employee's first 'book' event
-- month_n      = months since that cohort month (0 = the cohort month itself)
-- retention    = employees booking in month_n / employees in the cohort
--
-- Caveat: later cohorts have fewer months of history (the data ends in Dec 2025),
-- so their rows stop early. Cohorts also include employees who joined mid-year.

-- @result all_features
-- Cohort = first booking of ANY feature; "active" = any booking in that month.
WITH monthly AS (
    SELECT DISTINCT employee_id, strftime('%Y-%m', ts) AS active_month
    FROM events
    WHERE action = 'book'
),
cohorts AS (
    SELECT employee_id, active_month,
           MIN(active_month) OVER (PARTITION BY employee_id) AS cohort_month
    FROM monthly
),
with_n AS (
    SELECT cohort_month, active_month,
           (CAST(substr(active_month, 1, 4) AS INTEGER) * 12 + CAST(substr(active_month, 6, 2) AS INTEGER))
         - (CAST(substr(cohort_month, 1, 4) AS INTEGER) * 12 + CAST(substr(cohort_month, 6, 2) AS INTEGER)) AS month_n
    FROM cohorts
),
agg AS (
    SELECT cohort_month, month_n, COUNT(*) AS active_employees
    FROM with_n
    GROUP BY cohort_month, month_n
)
SELECT cohort_month, month_n, active_employees,
       -- month_n = 0 is the cohort itself, so the first value is the cohort size
       FIRST_VALUE(active_employees) OVER (PARTITION BY cohort_month ORDER BY month_n) AS cohort_size,
       ROUND(100.0 * active_employees /
             FIRST_VALUE(active_employees) OVER (PARTITION BY cohort_month ORDER BY month_n), 1) AS retention_pct
FROM agg
ORDER BY cohort_month, month_n;

-- @result by_feature
-- Same idea, but cohort and activity are both per feature (first booking OF THAT FEATURE).
WITH monthly AS (
    SELECT DISTINCT employee_id, feature, strftime('%Y-%m', ts) AS active_month
    FROM events
    WHERE action = 'book'
),
cohorts AS (
    SELECT employee_id, feature, active_month,
           MIN(active_month) OVER (PARTITION BY employee_id, feature) AS cohort_month
    FROM monthly
),
with_n AS (
    SELECT feature, cohort_month, active_month,
           (CAST(substr(active_month, 1, 4) AS INTEGER) * 12 + CAST(substr(active_month, 6, 2) AS INTEGER))
         - (CAST(substr(cohort_month, 1, 4) AS INTEGER) * 12 + CAST(substr(cohort_month, 6, 2) AS INTEGER)) AS month_n
    FROM cohorts
),
agg AS (
    SELECT feature, cohort_month, month_n, COUNT(*) AS active_employees
    FROM with_n
    GROUP BY feature, cohort_month, month_n
)
SELECT feature, cohort_month, month_n, active_employees,
       FIRST_VALUE(active_employees) OVER (PARTITION BY feature, cohort_month ORDER BY month_n) AS cohort_size,
       ROUND(100.0 * active_employees /
             FIRST_VALUE(active_employees) OVER (PARTITION BY feature, cohort_month ORDER BY month_n), 1) AS retention_pct
FROM agg
ORDER BY feature, cohort_month, month_n;
