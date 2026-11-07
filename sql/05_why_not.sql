-- 05_why_not.sql
-- QUESTION: For clients that adopt a feature poorly, WHY? Look at what employees do
-- (view without booking, cancelling, no-shows) and what they complain about (tickets).
--
-- DEFINITIONS
--   low adopter     = an enabled client x feature in the LOWEST QUARTILE of
--                     adoption_pct_of_employees for that feature (NTILE(4) = 1).
--                     Quartiles are per feature so a naturally niche feature like Visitor
--                     Management is compared with other Visitor Management clients only.
--   view_without_book_pct = share of 'view' sessions that did not become a booking
--                     (views - books) / views. Not available for QR (it has no views).
--   cancel_pct, no_show_pct = cancels or no-shows as a share of bookings.
--   Behaviour counts cover the whole year; tickets are all tickets for that client + feature.
--
-- Needs temp table feature_matrix from 04_feature_matrix.sql.

DROP TABLE IF EXISTS temp.behaviour;
CREATE TEMP TABLE behaviour AS
WITH ranked AS (
    SELECT client_id, feature,
           NTILE(4) OVER (PARTITION BY feature ORDER BY adoption_pct_of_employees) AS adoption_quartile
    FROM feature_matrix
    WHERE enabled = 1
),
actions AS (
    -- In SQLite a comparison like (action = 'view') is 1 or 0, so SUM counts matches.
    SELECT client_id, feature,
           SUM(action = 'view')     AS views,
           SUM(action = 'book')     AS books,
           SUM(action = 'cancel')   AS cancels,
           SUM(action = 'no_show')  AS no_shows,
           SUM(action = 'check_in') AS check_ins
    FROM events
    GROUP BY client_id, feature
),
tix AS (
    SELECT client_id, feature,
           COUNT(*) AS tickets_total,
           SUM(category = 'how_to')             AS t_how_to,
           SUM(category = 'bug')                AS t_bug,
           SUM(category = 'access')             AS t_access,
           SUM(category = 'feature_request')    AS t_feature_request,
           SUM(category = 'integration')        AS t_integration,
           SUM(category = 'configuration')      AS t_configuration,
           SUM(category = 'hardware')           AS t_hardware,
           SUM(category = 'policy_restriction') AS t_policy_restriction
    FROM support_tickets
    GROUP BY client_id, feature
)
SELECT fm.client_id,
       fm.client_name,
       fm.feature,
       fm.adoption_pct_of_employees,
       fm.coverage_pct,
       r.adoption_quartile,
       CASE WHEN r.adoption_quartile = 1 THEN 1 ELSE 0 END AS is_low_adopter,
       COALESCE(a.views, 0)     AS views,
       COALESCE(a.books, 0)     AS books,
       COALESCE(a.cancels, 0)   AS cancels,
       COALESCE(a.no_shows, 0)  AS no_shows,
       ROUND(100.0 * (a.views - a.books) / NULLIF(a.views, 0), 1) AS view_without_book_pct,
       ROUND(100.0 * a.cancels  / NULLIF(a.books, 0), 1)          AS cancel_pct,
       ROUND(100.0 * a.no_shows / NULLIF(a.books, 0), 1)          AS no_show_pct,
       COALESCE(t.tickets_total, 0)         AS tickets_total,
       ROUND(100.0 * COALESCE(t.tickets_total, 0) / fm.total_employees, 2) AS tickets_per_100_employees,
       COALESCE(t.t_how_to, 0)              AS t_how_to,
       COALESCE(t.t_bug, 0)                 AS t_bug,
       COALESCE(t.t_access, 0)              AS t_access,
       COALESCE(t.t_feature_request, 0)     AS t_feature_request,
       COALESCE(t.t_integration, 0)         AS t_integration,
       COALESCE(t.t_configuration, 0)       AS t_configuration,
       COALESCE(t.t_hardware, 0)            AS t_hardware,
       COALESCE(t.t_policy_restriction, 0)  AS t_policy_restriction,
       (SELECT st.category FROM support_tickets st
        WHERE st.client_id = fm.client_id AND st.feature = fm.feature
        GROUP BY st.category ORDER BY COUNT(*) DESC, st.category LIMIT 1) AS top_ticket_category
FROM feature_matrix fm
JOIN ranked r        ON r.client_id = fm.client_id AND r.feature = fm.feature
LEFT JOIN actions a  ON a.client_id = fm.client_id AND a.feature = fm.feature
LEFT JOIN tix t      ON t.client_id = fm.client_id AND t.feature = fm.feature
WHERE fm.enabled = 1;

-- @result low_adopters
-- Detail for every low adopter (lowest quartile), worst first within each feature.
SELECT *
FROM behaviour
WHERE is_low_adopter = 1
ORDER BY feature, adoption_pct_of_employees;

-- @result all_enabled
-- Same detail for every enabled client x feature (not only low adopters). Used by Power BI.
SELECT *
FROM behaviour
ORDER BY client_id, feature;

-- @result low_vs_rest_by_feature
-- Do low adopters behave differently from the rest? (Rates are pooled over all rows in each group.)
SELECT feature,
       CASE WHEN is_low_adopter = 1 THEN 'low adopters' ELSE 'other clients' END AS grp,
       COUNT(*)                                                           AS client_features,
       ROUND(100.0 * (SUM(views) - SUM(books)) / NULLIF(SUM(views), 0), 1) AS view_without_book_pct,
       ROUND(100.0 * SUM(cancels)  / NULLIF(SUM(books), 0), 1)            AS cancel_pct,
       ROUND(100.0 * SUM(no_shows) / NULLIF(SUM(books), 0), 1)            AS no_show_pct,
       ROUND(AVG(tickets_per_100_employees), 2)                           AS avg_tickets_per_100_employees
FROM behaviour
GROUP BY feature, is_low_adopter
ORDER BY feature, is_low_adopter DESC;

-- @result ticket_mix_low_vs_rest
-- Ticket categories as a share of tickets: low adopters vs the rest (all features pooled).
SELECT CASE WHEN is_low_adopter = 1 THEN 'low adopters' ELSE 'other clients' END AS grp,
       SUM(tickets_total) AS tickets,
       ROUND(100.0 * SUM(t_how_to)             / SUM(tickets_total), 1) AS how_to_pct,
       ROUND(100.0 * SUM(t_bug)                / SUM(tickets_total), 1) AS bug_pct,
       ROUND(100.0 * SUM(t_access)             / SUM(tickets_total), 1) AS access_pct,
       ROUND(100.0 * SUM(t_feature_request)    / SUM(tickets_total), 1) AS feature_request_pct,
       ROUND(100.0 * SUM(t_integration)        / SUM(tickets_total), 1) AS integration_pct,
       ROUND(100.0 * SUM(t_configuration)      / SUM(tickets_total), 1) AS configuration_pct,
       ROUND(100.0 * SUM(t_hardware)           / SUM(tickets_total), 1) AS hardware_pct,
       ROUND(100.0 * SUM(t_policy_restriction) / SUM(tickets_total), 1) AS policy_restriction_pct
FROM behaviour
GROUP BY is_low_adopter
ORDER BY is_low_adopter DESC;
