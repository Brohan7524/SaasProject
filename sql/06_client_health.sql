-- 06_client_health.sql
-- QUESTION: Which clients are healthy, which need attention, and what is dragging them down?
--
-- health_score (0-100) = 0.30 * breadth + 0.30 * depth + 0.25 * trend + 0.15 * (100 - ticket_load)
--
--   breadth     = features in real use / 6 x 100.   "In real use" = enabled AND at least 5% of
--                 the client's employees active in the last 90 days.
--   depth       = average, over the features the client has enabled, of the client's PERCENT RANK
--                 versus all other clients on that feature (0-100). Peer-relative, so a client is
--                 judged against others using the same feature, not against an arbitrary target.
--   trend       = (book + check_in events in the last 60 days) / (same, the 60 days before that),
--                 capped at 1, x 100.  Last 60 days = 2025-11-02..2025-12-31; previous 60 =
--                 2025-09-03..2025-11-01. A drop to 40% scores 40; flat or growing scores 100.
--                 Every client dips a little (Diwali, Christmas), so normal clients sit around 80.
--                 A 60-day window is used because a quarter-on-quarter ratio dilutes a decline
--                 that is concentrated at the end of the year (changed after the first run).
--   ticket_load = percent rank of tickets per 100 employees in the last 90 days among clients
--                 (0 = fewest tickets, 100 = most). It is SUBTRACTED, so more tickets = lower score.
--
-- Bands (see DECISIONS.md):  Green >= 65,  Amber 55 to < 65,  Red < 55.
-- (The first draft used Red < 45, which no client reached because the peer-percentile
-- components pull every score toward the middle. Red was moved to the bottom quartile, ~55.)
--
-- Needs temp table feature_matrix from 04_feature_matrix.sql.

DROP TABLE IF EXISTS temp.client_health;
CREATE TEMP TABLE client_health AS
WITH breadth AS (
    SELECT client_id,
           SUM(CASE WHEN enabled = 1 AND adoption_pct_of_employees >= 5 THEN 1 ELSE 0 END) AS features_in_use,
           SUM(enabled) AS features_enabled
    FROM feature_matrix
    GROUP BY client_id
),
ranked AS (
    SELECT client_id, feature,
           PERCENT_RANK() OVER (PARTITION BY feature ORDER BY adoption_pct_of_employees) AS pr
    FROM feature_matrix
    WHERE enabled = 1
),
depth AS (
    SELECT client_id, 100.0 * AVG(pr) AS depth_score
    FROM ranked
    GROUP BY client_id
),
trend AS (
    SELECT client_id,
           SUM(CASE WHEN date(ts) >= '2025-11-02' THEN 1 ELSE 0 END)                           AS events_recent60,
           SUM(CASE WHEN date(ts) >= '2025-09-03' AND date(ts) < '2025-11-02' THEN 1 ELSE 0 END) AS events_prior60
    FROM events
    WHERE action IN ('book', 'check_in')
    GROUP BY client_id
),
tickets AS (
    SELECT t.client_id,
           COUNT(*) AS tickets_last_90d
    FROM support_tickets t
    WHERE date(t.created_at) >= '2025-10-03'
    GROUP BY t.client_id
),
client_totals AS (
    SELECT client_id, COUNT(*) AS total_employees FROM employees GROUP BY client_id
),
parts AS (
    SELECT c.client_id,
           c.name AS client_name,
           c.region,
           c.plan,
           ct.total_employees,
           b.features_enabled,
           b.features_in_use,
           100.0 * b.features_in_use / 6                                   AS breadth_score,
           COALESCE(d.depth_score, 0)                                      AS depth_score,
           tr.events_prior60,
           tr.events_recent60,
           -- If the client had no usage in the earlier window (brand new), do not penalise it.
           CASE WHEN tr.events_prior60 = 0 THEN CASE WHEN tr.events_recent60 > 0 THEN 100.0 ELSE 0.0 END
                ELSE 100.0 * MIN(1.0, 1.0 * tr.events_recent60 / tr.events_prior60) END AS trend_score,
           COALESCE(tk.tickets_last_90d, 0)                                AS tickets_last_90d,
           100.0 * COALESCE(tk.tickets_last_90d, 0) / ct.total_employees   AS tickets_per_100_employees
    FROM clients c
    JOIN client_totals ct ON ct.client_id = c.client_id
    JOIN breadth b        ON b.client_id = c.client_id
    LEFT JOIN depth d     ON d.client_id = c.client_id
    LEFT JOIN trend tr    ON tr.client_id = c.client_id
    LEFT JOIN tickets tk  ON tk.client_id = c.client_id
),
with_load AS (
    SELECT *,
           100.0 * PERCENT_RANK() OVER (ORDER BY tickets_per_100_employees) AS ticket_load_score
    FROM parts
),
scored AS (
    SELECT *,
           0.30 * breadth_score + 0.30 * depth_score + 0.25 * trend_score
         + 0.15 * (100 - ticket_load_score) AS health_score
    FROM with_load
)
SELECT client_id, client_name, region, plan, total_employees,
       features_enabled, features_in_use,
       ROUND(breadth_score, 1)  AS breadth_score,
       ROUND(depth_score, 1)    AS depth_score,
       events_prior60, events_recent60,
       ROUND(trend_score, 1)    AS trend_score,
       tickets_last_90d,
       ROUND(tickets_per_100_employees, 2) AS tickets_per_100_employees,
       ROUND(ticket_load_score, 1)         AS ticket_load_score,
       ROUND(health_score, 1)   AS health_score,
       CASE WHEN health_score >= 65 THEN 'Green'
            WHEN health_score >= 55 THEN 'Amber'
            ELSE 'Red' END     AS health_band,
       -- The component (out of 100, higher = better) that is lowest tells you where to look first.
       CASE WHEN breadth_score <= depth_score AND breadth_score <= trend_score AND breadth_score <= (100 - ticket_load_score) THEN 'breadth'
            WHEN depth_score <= trend_score AND depth_score <= (100 - ticket_load_score) THEN 'depth'
            WHEN trend_score <= (100 - ticket_load_score) THEN 'trend'
            ELSE 'ticket_load' END AS weakest_component
FROM scored;

-- @result client_health
SELECT * FROM client_health ORDER BY health_score;

-- @result band_summary
SELECT health_band,
       COUNT(*)                       AS clients,
       SUM(total_employees)           AS employees,
       ROUND(AVG(health_score), 1)    AS avg_score
FROM client_health
GROUP BY health_band
ORDER BY CASE health_band WHEN 'Green' THEN 1 WHEN 'Amber' THEN 2 ELSE 3 END;
