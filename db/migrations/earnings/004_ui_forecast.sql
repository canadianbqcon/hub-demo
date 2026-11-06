-- vault-code/db/migrations/earnings/004_ui_forecast.sql
-- Unemployment benefits in the forecast. A scheduled shift now carries predicted
-- HOURS as well as predicted pay, because NYSDOL prices a benefit week off hours
-- worked -- so the same shift that earns wages also decides that week's UI check.
-- +migrate up

-- Claim terms. One row per claim; a new benefit year is a new row, so the old
-- claim's numbers stay intact rather than being overwritten in place.
CREATE TABLE earnings_ui_claim (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source           TEXT NOT NULL UNIQUE,  -- matches earnings.source
    effective_date   TEXT NOT NULL,
    benefit_year_end TEXT NOT NULL,         -- no benefit payable after this date
    weekly_rate      REAL NOT NULL,         -- full week, all effective days
    days_per_week    INTEGER NOT NULL DEFAULT 4,
    max_payable      REAL NOT NULL,         -- lifetime ceiling; the real constraint
    withholding_rate REAL,                  -- fraction, e.g. 0.125
    notes            TEXT NOT NULL DEFAULT ''
) STRICT;

-- Demo copy: the claim row below is placeholder numbers, not a real claim.
INSERT INTO earnings_ui_claim
    (source, effective_date, benefit_year_end, weekly_rate, days_per_week,
     max_payable, withholding_rate, notes)
VALUES
    ('state-unemployment', '2026-01-05', '2027-01-03', 180.00, 4, 4680.00, 0.10,
     'Placeholder claim for the demo.');

-- Rebuilt: the job-wide fallback now carries average hours as well as average pay,
-- so a scheduled day of week with no history can still be priced for UI.
DROP VIEW earnings_source_avg;
CREATE VIEW earnings_source_avg AS
SELECT source,
       COUNT(*)                   AS sample_shifts,
       ROUND(AVG(shift_total), 2) AS avg_shift_total,
       ROUND(AVG(hours), 2)       AS avg_hours
FROM earnings_shift_days
GROUP BY source;

-- Rebuilt: adds expected_hours (what the UI week is priced from) and the
-- Monday-Sunday benefit week the shift falls in.
DROP VIEW earnings_expected_month;
DROP VIEW earnings_expected_month_total;
DROP VIEW earnings_expected_shift;
CREATE VIEW earnings_expected_shift AS
SELECT sch.source                                            AS source,
       sch.shift_date                                        AS shift_date,
       CAST(strftime('%w', sch.shift_date) AS INTEGER)       AS dow,
       strftime('%Y-%m', sch.shift_date)                     AS month,
       -- benefit week ends the coming Sunday ('%w' is 0=Sun, so Sunday maps to itself)
       DATE(sch.shift_date, '+' || ((7 - CAST(strftime('%w', sch.shift_date) AS INTEGER)) % 7) || ' days')
                                                             AS week_end,
       COALESCE(d.avg_shift_total, o.avg_shift_total)        AS expected_total,
       COALESCE(d.avg_hours, o.avg_hours)                    AS expected_hours,
       COALESCE(d.sample_shifts, 0)                          AS dow_sample_shifts,
       CASE WHEN d.avg_shift_total IS NULL THEN 1 ELSE 0 END AS used_fallback
FROM earnings_scheduled_shifts sch
LEFT JOIN earnings_dow_avg d
       ON d.source = sch.source
      AND d.dow = CAST(strftime('%w', sch.shift_date) AS INTEGER)
LEFT JOIN earnings_source_avg o
       ON o.source = sch.source;

CREATE VIEW earnings_expected_month AS
SELECT month, source,
       COUNT(*)                      AS scheduled_shifts,
       ROUND(SUM(expected_total), 2) AS expected_total,
       SUM(used_fallback)            AS shifts_priced_by_fallback
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

-- Predicted hours per benefit week, across every job -- NYSDOL counts total hours
-- worked in the week, not hours per employer. Each calendar day is capped at 10
-- hours before summing, per the DOL instruction.
CREATE VIEW earnings_expected_week_hours AS
SELECT week_end,
       ROUND(SUM(capped_hours), 2) AS hours,
       COUNT(*)                    AS shifts
FROM (SELECT week_end, shift_date, MIN(SUM(expected_hours), 10.0) AS capped_hours
      FROM earnings_expected_shift
      GROUP BY week_end, shift_date)
GROUP BY week_end;

-- +migrate down
DROP VIEW IF EXISTS earnings_expected_week_hours;
DROP VIEW IF EXISTS earnings_expected_month_total;
DROP VIEW IF EXISTS earnings_expected_month;
DROP VIEW IF EXISTS earnings_expected_shift;
DROP VIEW IF EXISTS earnings_source_avg;
CREATE VIEW earnings_source_avg AS
SELECT source,
       COUNT(*)                   AS sample_shifts,
       ROUND(AVG(shift_total), 2) AS avg_shift_total
FROM earnings_shift_days
GROUP BY source;
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
CREATE VIEW earnings_expected_month AS
SELECT month, source, COUNT(*) AS scheduled_shifts,
       ROUND(SUM(expected_total), 2) AS expected_total,
       SUM(used_fallback) AS shifts_priced_by_fallback
FROM earnings_expected_shift GROUP BY month, source;
CREATE VIEW earnings_expected_month_total AS
SELECT month, COUNT(*) AS scheduled_shifts, COUNT(DISTINCT source) AS jobs,
       ROUND(SUM(expected_total), 2) AS expected_total,
       SUM(used_fallback) AS shifts_priced_by_fallback
FROM earnings_expected_shift GROUP BY month;
DROP TABLE IF EXISTS earnings_ui_claim;
