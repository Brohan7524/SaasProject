-- 01_adoption_funnel.sql
-- QUESTION: For every client and feature, how far down the funnel do employees get?
--     enabled  ->  first use  ->  used in >= 3 of the last 4 weeks ("habitual")
--
-- DEFINITIONS (also in DECISIONS.md)
--   "use"      = a 'book' or 'check_in' event. A 'view' alone is only browsing, so it
--                does not count as adoption.
--   eligible   = employees in the offices where the feature is switched on
--                (the first `offices_enabled` offices of the client).
--   last 4 wks = the 28 days ending 2025-12-31 (2025-12-04 .. 2025-12-31).
--                A "week" is a 7-day block counted backwards from 2025-12-31.
--
-- This file has a setup block (temp tables) followed by several result queries.
-- Lines starting with "-- @result <name>" tell run_queries.py to save the next query.

DROP TABLE IF EXISTS temp.funnel;
CREATE TEMP TABLE funnel AS
WITH params AS (
    SELECT '2025-12-31' AS as_of, '2025-12-04' AS window_start
),
-- Number each client's offices so we can pick "the first N offices".
ranked_offices AS (
    SELECT office_id, client_id,
           ROW_NUMBER() OVER (PARTITION BY client_id ORDER BY office_id) AS office_rank
    FROM offices
),
-- One row per (enabled client-feature, eligible employee).
eligible AS (
    SELECT cc.client_id, cc.feature, e.employee_id
    FROM client_config cc
    JOIN ranked_offices ro ON ro.client_id = cc.client_id
                          AND ro.office_rank <= cc.offices_enabled
    JOIN employees e ON e.office_id = ro.office_id
    WHERE cc.enabled = 1
),
-- Per employee and feature: first real use, and how many of the last 4 weeks had use.
usage AS (
    SELECT ev.employee_id, ev.client_id, ev.feature,
           MIN(ev.ts) AS first_use_ts,
           COUNT(DISTINCT CASE
                    WHEN date(ev.ts) >= p.window_start
                    THEN CAST((julianday(p.as_of) - julianday(date(ev.ts))) / 7 AS INTEGER)
                 END) AS active_weeks_last4
    FROM events ev
    CROSS JOIN params p
    WHERE ev.action IN ('book', 'check_in')
    GROUP BY ev.employee_id, ev.client_id, ev.feature
),
-- Combine: for each eligible employee, did they use it / use it habitually?
per_employee AS (
    SELECT el.client_id, el.feature,
           CASE WHEN u.employee_id IS NOT NULL THEN 1 ELSE 0 END AS ever_used,
           CASE WHEN COALESCE(u.active_weeks_last4, 0) >= 3 THEN 1 ELSE 0 END AS habitual,
           u.first_use_ts
    FROM eligible el
    LEFT JOIN usage u ON u.employee_id = el.employee_id
                     AND u.client_id = el.client_id
                     AND u.feature = el.feature
)
SELECT cc.client_id,
       c.name AS client_name,
       cc.feature,
       cc.enabled_date,
       cc.offices_enabled,
       (SELECT COUNT(*) FROM offices o WHERE o.client_id = cc.client_id) AS total_offices,
       COUNT(*)                                   AS eligible_employees,
       SUM(pe.ever_used)                          AS employees_ever_used,
       SUM(pe.habitual)                           AS employees_habitual,
       ROUND(100.0 * SUM(pe.ever_used) / COUNT(*), 1) AS pct_ever_used,
       ROUND(100.0 * SUM(pe.habitual)  / COUNT(*), 1) AS pct_habitual,
       date(MIN(pe.first_use_ts))                 AS first_use_date,
       CAST(julianday(date(MIN(pe.first_use_ts))) - julianday(cc.enabled_date) AS INTEGER) AS days_enable_to_first_use
FROM client_config cc
JOIN clients c ON c.client_id = cc.client_id
JOIN per_employee pe ON pe.client_id = cc.client_id AND pe.feature = cc.feature
WHERE cc.enabled = 1
GROUP BY cc.client_id, cc.feature;

-- Month-1 vs later QR check-ins per QR-enabled client.
--   month 1       = the 30 days starting at enabled_date
--   "later"       = from day 30 onwards, converted to a 30-day rate so clients enabled
--                   at different times can be compared
--   repeat_ratio  = later 30-day rate / month-1 count.  Healthy clients keep ramping
--                   up (ratio >= 1). A ratio < 0.25 means usage fell to under a quarter
--                   of month 1, i.e. no real repeat use. (0.25 was fixed before looking at results.)
DROP TABLE IF EXISTS temp.qr_repeat;
CREATE TEMP TABLE qr_repeat AS
WITH qr AS (
    SELECT client_id, enabled_date, date(enabled_date, '+30 days') AS month1_end
    FROM client_config
    WHERE feature = 'QR Check-in' AND enabled = 1
),
counts AS (
    SELECT qr.client_id, qr.enabled_date, qr.month1_end,
           COALESCE(SUM(CASE WHEN date(ev.ts) <  qr.month1_end AND date(ev.ts) >= qr.enabled_date THEN 1 ELSE 0 END), 0) AS month1_checkins,
           COALESCE(SUM(CASE WHEN date(ev.ts) >= qr.month1_end THEN 1 ELSE 0 END), 0) AS later_checkins
    FROM qr
    LEFT JOIN events ev ON ev.client_id = qr.client_id
                       AND ev.feature = 'QR Check-in'
                       AND ev.action = 'check_in'
    GROUP BY qr.client_id
),
rates AS (
    SELECT *,
           julianday('2026-01-01') - julianday(month1_end) AS days_after_month1,
           later_checkins * 30.0 / (julianday('2026-01-01') - julianday(month1_end)) AS later_per_30d
    FROM counts
)
SELECT client_id, enabled_date, month1_checkins, later_checkins,
       CAST(days_after_month1 AS INTEGER) AS days_after_month1,
       ROUND(later_per_30d, 1) AS later_per_30d,
       CASE WHEN month1_checkins = 0 THEN NULL
            ELSE ROUND(later_per_30d / month1_checkins, 2) END AS repeat_ratio,
       -- Flag: never used in month 1, or fell below 25% of month 1.
       CASE WHEN month1_checkins = 0 OR later_per_30d / month1_checkins < 0.25
            THEN 1 ELSE 0 END AS no_repeat_use
FROM rates;

-- @result client_feature
-- Full funnel, one row per enabled client x feature.
SELECT * FROM funnel ORDER BY client_id, feature;

-- @result by_feature
-- Funnel rolled up to feature level (employee-weighted).
SELECT feature,
       COUNT(*)                                        AS clients_enabled,
       SUM(CASE WHEN employees_ever_used > 0 THEN 1 ELSE 0 END) AS clients_with_any_use,
       SUM(eligible_employees)                         AS eligible_employees,
       SUM(employees_ever_used)                        AS employees_ever_used,
       SUM(employees_habitual)                         AS employees_habitual,
       ROUND(100.0 * SUM(employees_ever_used) / SUM(eligible_employees), 1) AS pct_ever_used,
       ROUND(100.0 * SUM(employees_habitual)  / SUM(eligible_employees), 1) AS pct_habitual
FROM funnel
GROUP BY feature
ORDER BY pct_habitual DESC;

-- @result qr_repeat_by_client
SELECT q.*, c.name AS client_name
FROM qr_repeat q
JOIN clients c ON c.client_id = q.client_id
ORDER BY q.repeat_ratio;

-- @result qr_headline
-- Resume number X: share of QR-enabled clients with no repeat use after month 1.
SELECT COUNT(*)                         AS qr_enabled_clients,
       SUM(no_repeat_use)               AS clients_no_repeat_use,
       ROUND(100.0 * SUM(no_repeat_use) / COUNT(*), 1) AS pct_no_repeat_use
FROM qr_repeat;
