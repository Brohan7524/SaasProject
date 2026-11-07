-- 07_client_monthly_usage.sql
-- SUPPORTING QUERY (not one of the six core questions): monthly usage per client x feature.
-- Feeds the trend visuals and client drill-down in Power BI / the dashboard.
--
-- active_employees = distinct employees with a 'book' or 'check_in' event in the month.
-- use_events       = number of those book/check_in events.
SELECT client_id,
       feature,
       strftime('%Y-%m', ts) AS month,
       COUNT(DISTINCT CASE WHEN action IN ('book', 'check_in') THEN employee_id END) AS active_employees,
       SUM(action IN ('book', 'check_in')) AS use_events,
       SUM(action = 'view')     AS views,
       SUM(action = 'book')     AS bookings,
       SUM(action = 'cancel')   AS cancels,
       SUM(action = 'no_show')  AS no_shows
FROM events
GROUP BY client_id, feature, month
ORDER BY client_id, feature, month;
