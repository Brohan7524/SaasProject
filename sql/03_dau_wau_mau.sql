-- 03_dau_wau_mau.sql
-- QUESTION: How sticky is each feature? (How many employees use it daily vs monthly.)
--
-- "active" = employee with a 'book' or 'check_in' event.
-- avg_dau  = average daily active employees over the WEEKDAYS (Mon-Fri) of the month.
--            Weekends are left out because hybrid offices are nearly empty then, which
--            would make every feature look unsticky. Weekdays with zero activity count as 0
--            (that is why we build a calendar first).
-- avg_wau  = average weekly active employees over weeks (Mon-Sun) that START in the month.
-- mau      = distinct active employees in the month.
-- dau_mau  = avg_dau / mau  (the usual "stickiness" ratio; 1.0 = everyone every day).

-- @result by_feature_month
WITH RECURSIVE calendar(day) AS (
    SELECT '2025-01-01'
    UNION ALL
    SELECT date(day, '+1 day') FROM calendar WHERE day < '2025-12-31'
),
features AS (
    SELECT DISTINCT feature FROM client_config
),
active_events AS (
    SELECT employee_id, feature, date(ts) AS day
    FROM events
    WHERE action IN ('book', 'check_in')
),
daily AS (
    SELECT feature, day, COUNT(DISTINCT employee_id) AS dau
    FROM active_events
    GROUP BY feature, day
),
-- Every weekday x feature, with 0 where nothing happened.
daily_full AS (
    SELECT f.feature, strftime('%Y-%m', c.day) AS month, COALESCE(d.dau, 0) AS dau
    FROM calendar c
    CROSS JOIN features f
    LEFT JOIN daily d ON d.feature = f.feature AND d.day = c.day
    WHERE strftime('%w', c.day) NOT IN ('0', '6')
),
dau_month AS (
    SELECT feature, month, ROUND(AVG(dau), 1) AS avg_dau
    FROM daily_full
    GROUP BY feature, month
),
weekly AS (
    -- date(day, 'weekday 0', '-6 days') = the Monday of that day's week
    SELECT feature,
           date(day, 'weekday 0', '-6 days') AS week_start,
           COUNT(DISTINCT employee_id) AS wau
    FROM active_events
    GROUP BY feature, week_start
),
wau_month AS (
    SELECT feature, strftime('%Y-%m', week_start) AS month, ROUND(AVG(wau), 1) AS avg_wau
    FROM weekly
    WHERE week_start >= '2025-01-01'
    GROUP BY feature, month
),
mau_month AS (
    SELECT feature, strftime('%Y-%m', day) AS month, COUNT(DISTINCT employee_id) AS mau
    FROM active_events
    GROUP BY feature, month
)
SELECT m.feature, m.month, d.avg_dau, w.avg_wau, m.mau,
       ROUND(1.0 * d.avg_dau / m.mau, 3) AS dau_mau
FROM mau_month m
JOIN dau_month d ON d.feature = m.feature AND d.month = m.month
LEFT JOIN wau_month w ON w.feature = m.feature AND w.month = m.month
ORDER BY m.feature, m.month;
