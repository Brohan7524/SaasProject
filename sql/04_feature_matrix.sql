-- 04_feature_matrix.sql
-- QUESTION: For every client x feature, what share of the client's employees use it today?
-- This is the table behind the heat map.
--
-- DEFINITIONS
--   active      = employee with a 'book' or 'check_in' event in the last 90 days
--                 (2025-10-03 .. 2025-12-31).
--   adoption_pct_of_employees = active employees / ALL employees of the client.
--                 Using ALL employees (not just eligible ones) means a feature switched on
--                 in only 1 of 5 offices correctly looks weak.
--   adoption_pct_of_eligible  = active employees / employees in offices where the feature is on.
--   coverage_pct = eligible employees / all employees (how much of the client the rollout reaches).
--   Disabled features get NULL percentages (shown as blank in the heat map, not as 0).
--
-- Files 05 and 06 reuse the temp table `feature_matrix` built here, so run all files in
-- order with run_queries.py.

DROP TABLE IF EXISTS temp.feature_matrix;
CREATE TEMP TABLE feature_matrix AS
WITH params AS (
    SELECT '2025-10-03' AS window_start
),
client_totals AS (
    SELECT client_id, COUNT(*) AS total_employees
    FROM employees
    GROUP BY client_id
),
ranked_offices AS (
    SELECT office_id, client_id,
           ROW_NUMBER() OVER (PARTITION BY client_id ORDER BY office_id) AS office_rank
    FROM offices
),
eligible AS (
    SELECT cc.client_id, cc.feature, COUNT(*) AS eligible_employees
    FROM client_config cc
    JOIN ranked_offices ro ON ro.client_id = cc.client_id
                          AND ro.office_rank <= cc.offices_enabled
    JOIN employees e ON e.office_id = ro.office_id
    WHERE cc.enabled = 1
    GROUP BY cc.client_id, cc.feature
),
active AS (
    SELECT ev.client_id, ev.feature, COUNT(DISTINCT ev.employee_id) AS active_employees
    FROM events ev
    CROSS JOIN params p
    WHERE ev.action IN ('book', 'check_in')
      AND date(ev.ts) >= p.window_start
    GROUP BY ev.client_id, ev.feature
)
SELECT c.client_id,
       c.name AS client_name,
       c.region,
       c.plan,
       cc.feature,
       cc.enabled,
       cc.offices_enabled,
       (SELECT COUNT(*) FROM offices o WHERE o.client_id = c.client_id) AS total_offices,
       ct.total_employees,
       COALESCE(el.eligible_employees, 0) AS eligible_employees,
       COALESCE(ac.active_employees, 0)   AS active_employees,
       CASE WHEN cc.enabled = 1
            THEN ROUND(100.0 * COALESCE(ac.active_employees, 0) / ct.total_employees, 1) END AS adoption_pct_of_employees,
       CASE WHEN cc.enabled = 1
            THEN ROUND(100.0 * COALESCE(ac.active_employees, 0) / el.eligible_employees, 1) END AS adoption_pct_of_eligible,
       CASE WHEN cc.enabled = 1
            THEN ROUND(100.0 * el.eligible_employees / ct.total_employees, 1) END AS coverage_pct
FROM client_config cc
JOIN clients c        ON c.client_id = cc.client_id
JOIN client_totals ct ON ct.client_id = cc.client_id
LEFT JOIN eligible el ON el.client_id = cc.client_id AND el.feature = cc.feature
LEFT JOIN active ac   ON ac.client_id = cc.client_id AND ac.feature = cc.feature;

-- @result client_feature
-- Long format: one row per client x feature (240 rows). Best for Power BI.
SELECT * FROM feature_matrix ORDER BY client_id, feature;

-- @result matrix_wide
-- Wide format: one row per client, one column per feature (adoption_pct_of_employees).
-- Best for the Excel heat map.
SELECT client_id,
       client_name,
       region,
       plan,
       MAX(CASE WHEN feature = 'Desk Booking'         THEN adoption_pct_of_employees END) AS desk_booking,
       MAX(CASE WHEN feature = 'Meeting Room Booking' THEN adoption_pct_of_employees END) AS meeting_room,
       MAX(CASE WHEN feature = 'Parking'              THEN adoption_pct_of_employees END) AS parking,
       MAX(CASE WHEN feature = 'QR Check-in'          THEN adoption_pct_of_employees END) AS qr_checkin,
       MAX(CASE WHEN feature = 'Attendance Policy'    THEN adoption_pct_of_employees END) AS attendance_policy,
       MAX(CASE WHEN feature = 'Visitor Management'   THEN adoption_pct_of_employees END) AS visitor_mgmt
FROM feature_matrix
GROUP BY client_id
ORDER BY client_id;

-- @result by_feature
-- Portfolio view: how widely is each feature enabled, and how well is it used where enabled?
SELECT feature,
       SUM(enabled) AS clients_enabled,
       ROUND(100.0 * SUM(enabled) / COUNT(*), 1) AS pct_clients_enabled,
       ROUND(AVG(adoption_pct_of_employees), 1)  AS avg_adoption_pct_where_enabled,
       ROUND(MIN(adoption_pct_of_employees), 1)  AS min_adoption_pct,
       ROUND(MAX(adoption_pct_of_employees), 1)  AS max_adoption_pct
FROM feature_matrix
GROUP BY feature
ORDER BY avg_adoption_pct_where_enabled DESC;
