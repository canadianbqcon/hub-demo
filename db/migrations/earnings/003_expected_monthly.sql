-- vault-code/db/migrations/earnings/003_expected_monthly.sql
-- Expected monthly earnings: scheduled shifts (from Google Calendar) priced at
-- the historical average for that job + day of week.
-- +migrate up

-- Future shifts pulled off the calendar. One row per job per day: a day IS the
-- shift unit, matching how the actuals views collapse rows below.
CREATE TABLE earnings_scheduled_shifts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source            TEXT NOT NULL,   -- matches earnings.source, e.g. 'juniper-and-co'
    shift_date        TEXT NOT NULL,   -- YYYY-MM-DD
    calendar_event_id TEXT,
    summary           TEXT,
    synced            TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (source, shift_date)
) STRICT;

CREATE INDEX idx_earnings_scheduled_date ON earnings_scheduled_shifts(shift_date);

-- Actual shifts collapsed to one row per worked day. A single shift can span
-- two earnings_shifts rows when a paycheck error is rectified in a later period
-- (e.g. 2026-07-05, where the wage line and the tip line paid out separately);
-- averaging the raw rows would read that as two half-price shifts.
CREATE VIEW earnings_shift_days AS
SELECT e.source                                   AS source,
       s.shift_date                               AS shift_date,
       CAST(strftime('%w', s.shift_date) AS INTEGER) AS dow,   -- 0=Sun .. 6=Sat
       SUM(s.shift_total)                         AS shift_total,
       SUM(s.hours)                               AS hours
FROM earnings_shifts s
JOIN earnings e ON e.id = s.earnings_id
WHERE s.shift_total IS NOT NULL
GROUP BY e.source, s.shift_date;

-- Historical average take per job per day of week.
CREATE VIEW earnings_dow_avg AS
SELECT source,
       dow,
       COUNT(*)                    AS sample_shifts,
       ROUND(AVG(shift_total), 2)  AS avg_shift_total,
       ROUND(AVG(hours), 2)        AS avg_hours,
       MIN(shift_date)             AS first_shift,
       MAX(shift_date)             AS last_shift
FROM earnings_shift_days
GROUP BY source, dow;

-- Whole-job average, used to price a scheduled day-of-week with no history.
CREATE VIEW earnings_source_avg AS
SELECT source,
       COUNT(*)                   AS sample_shifts,
       ROUND(AVG(shift_total), 2) AS avg_shift_total
FROM earnings_shift_days
GROUP BY source;

-- One scheduled shift, priced.
CREATE VIEW earnings_expected_shift AS
SELECT sch.source                                            AS source,
       sch.shift_date                                        AS shift_date,
       CAST(strftime('%w', sch.shift_date) AS INTEGER)       AS dow,
       strftime('%Y-%m', sch.shift_date)                     AS month,
       COALESCE(d.avg_shift_total, o.avg_shift_total)        AS expected_total,
       COALESCE(d.sample_shifts, 0)                          AS dow_sample_shifts,
       CASE WHEN d.avg_shift_total IS NULL THEN 1 ELSE 0 END AS used_fallback
FROM earnings_scheduled_shifts sch
LEFT JOIN earnings_dow_avg d
       ON d.source = sch.source
      AND d.dow = CAST(strftime('%w', sch.shift_date) AS INTEGER)
LEFT JOIN earnings_source_avg o
       ON o.source = sch.source;

-- The answer: expected earnings per month per job. Sum across jobs for the
-- month total (see earnings_expected_month_total).
CREATE VIEW earnings_expected_month AS
SELECT month,
       source,
       COUNT(*)                    AS scheduled_shifts,
       ROUND(SUM(expected_total), 2) AS expected_total,
       SUM(used_fallback)          AS shifts_priced_by_fallback
FROM earnings_expected_shift
GROUP BY month, source;

CREATE VIEW earnings_expected_month_total AS
SELECT month,
       COUNT(*)                      AS scheduled_shifts,
       COUNT(DISTINCT source)        AS jobs,
       ROUND(SUM(expected_total), 2) AS expected_total,
       SUM(used_fallback)            AS shifts_priced_by_fallback
FROM earnings_expected_shift
GROUP BY month;

-- +migrate down
DROP VIEW IF EXISTS earnings_expected_month_total;
DROP VIEW IF EXISTS earnings_expected_month;
DROP VIEW IF EXISTS earnings_expected_shift;
DROP VIEW IF EXISTS earnings_source_avg;
DROP VIEW IF EXISTS earnings_dow_avg;
DROP VIEW IF EXISTS earnings_shift_days;
DROP INDEX IF EXISTS idx_earnings_scheduled_date;
DROP TABLE IF EXISTS earnings_scheduled_shifts;
