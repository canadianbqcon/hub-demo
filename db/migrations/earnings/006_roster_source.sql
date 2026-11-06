-- earnings/006_roster_source.sql
-- Separate a shift projected from a recurring pattern from one read off a
-- posted roster. The calendar event description carries the provenance, so
-- shift_calendar.py derives roster_source at sync time. Nullable with no
-- default: NULL means "not determined yet" and the UI shows nothing for it.
-- (Demo copy: comments shortened, schema unchanged.)
-- +migrate up

ALTER TABLE earnings_scheduled_shifts ADD COLUMN roster_source TEXT;

-- Rebuilt only to carry roster_source through; every other column and the
-- COALESCE fallback chain are unchanged from 005.
DROP VIEW earnings_expected_month_total;
DROP VIEW earnings_expected_month;
DROP VIEW earnings_expected_shift;
CREATE VIEW earnings_expected_shift AS
SELECT sch.source                                            AS source,
       sch.shift_date                                        AS shift_date,
       CAST(strftime('%w', sch.shift_date) AS INTEGER)       AS dow,
       strftime('%Y-%m', sch.shift_date)                     AS month,
       DATE(sch.shift_date, '+' || ((7 - CAST(strftime('%w', sch.shift_date) AS INTEGER)) % 7) || ' days')
                                                             AS week_end,
       sch.start_at                                          AS start_at,
       sch.end_at                                            AS end_at,
       sch.role                                              AS role,
       sch.shift_kind                                        AS shift_kind,
       sch.roster_source                                     AS roster_source,
       sch.model_share                                       AS model_share,
       sch.pricing_note                                      AS pricing_note,
       COALESCE(sch.model_total, d.avg_shift_total, o.avg_shift_total) AS expected_total,
       COALESCE(sch.model_hours, d.avg_hours, o.avg_hours)             AS expected_hours,
       sch.model_wages                                       AS expected_wages,
       sch.model_tips                                        AS expected_tips,
       COALESCE(d.sample_shifts, 0)                          AS dow_sample_shifts,
       CASE WHEN sch.model_total IS NOT NULL THEN 'model'
            WHEN d.avg_shift_total IS NOT NULL THEN 'dow'
            ELSE 'fallback' END                              AS priced_by,
       CASE WHEN sch.model_total IS NULL AND d.avg_shift_total IS NULL
            THEN 1 ELSE 0 END                                AS used_fallback
FROM earnings_scheduled_shifts sch
LEFT JOIN earnings_dow_avg d
       ON d.source = sch.source
      AND d.dow = CAST(strftime('%w', sch.shift_date) AS INTEGER)
LEFT JOIN earnings_source_avg o
       ON o.source = sch.source;

-- Month rollups gain an assumed count so a month total can say how much of
-- itself is projected, the same way it already reports fallback pricing.
CREATE VIEW earnings_expected_month AS
SELECT month, source,
       COUNT(*)                      AS scheduled_shifts,
       ROUND(SUM(expected_total), 2) AS expected_total,
       SUM(used_fallback)            AS shifts_priced_by_fallback,
       SUM(CASE WHEN priced_by = 'model' THEN 1 ELSE 0 END)      AS shifts_priced_by_model,
       SUM(CASE WHEN roster_source = 'assumed' THEN 1 ELSE 0 END) AS shifts_assumed,
       ROUND(SUM(CASE WHEN roster_source = 'assumed' THEN expected_total ELSE 0 END), 2)
                                                                 AS assumed_total
FROM earnings_expected_shift
GROUP BY month, source;

CREATE VIEW earnings_expected_month_total AS
SELECT month,
       COUNT(*)                      AS scheduled_shifts,
       COUNT(DISTINCT source)        AS jobs,
       ROUND(SUM(expected_total), 2) AS expected_total,
       SUM(used_fallback)            AS shifts_priced_by_fallback,
       SUM(CASE WHEN priced_by = 'model' THEN 1 ELSE 0 END)      AS shifts_priced_by_model,
       SUM(CASE WHEN roster_source = 'assumed' THEN 1 ELSE 0 END) AS shifts_assumed,
       ROUND(SUM(CASE WHEN roster_source = 'assumed' THEN expected_total ELSE 0 END), 2)
                                                                 AS assumed_total
FROM earnings_expected_shift
GROUP BY month;

-- +migrate down
DROP VIEW IF EXISTS earnings_expected_month_total;
DROP VIEW IF EXISTS earnings_expected_month;
DROP VIEW IF EXISTS earnings_expected_shift;
CREATE VIEW earnings_expected_shift AS
SELECT sch.source                                            AS source,
       sch.shift_date                                        AS shift_date,
       CAST(strftime('%w', sch.shift_date) AS INTEGER)       AS dow,
       strftime('%Y-%m', sch.shift_date)                     AS month,
       DATE(sch.shift_date, '+' || ((7 - CAST(strftime('%w', sch.shift_date) AS INTEGER)) % 7) || ' days')
                                                             AS week_end,
       sch.start_at                                          AS start_at,
       sch.end_at                                            AS end_at,
       sch.role                                              AS role,
       sch.shift_kind                                        AS shift_kind,
       sch.model_share                                       AS model_share,
       sch.pricing_note                                      AS pricing_note,
       COALESCE(sch.model_total, d.avg_shift_total, o.avg_shift_total) AS expected_total,
       COALESCE(sch.model_hours, d.avg_hours, o.avg_hours)             AS expected_hours,
       sch.model_wages                                       AS expected_wages,
       sch.model_tips                                        AS expected_tips,
       COALESCE(d.sample_shifts, 0)                          AS dow_sample_shifts,
       CASE WHEN sch.model_total IS NOT NULL THEN 'model'
            WHEN d.avg_shift_total IS NOT NULL THEN 'dow'
            ELSE 'fallback' END                              AS priced_by,
       CASE WHEN sch.model_total IS NULL AND d.avg_shift_total IS NULL
            THEN 1 ELSE 0 END                                AS used_fallback
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
       SUM(used_fallback)            AS shifts_priced_by_fallback,
       SUM(CASE WHEN priced_by = 'model' THEN 1 ELSE 0 END) AS shifts_priced_by_model
FROM earnings_expected_shift
GROUP BY month, source;
CREATE VIEW earnings_expected_month_total AS
SELECT month,
       COUNT(*)                      AS scheduled_shifts,
       COUNT(DISTINCT source)        AS jobs,
       ROUND(SUM(expected_total), 2) AS expected_total,
       SUM(used_fallback)            AS shifts_priced_by_fallback,
       SUM(CASE WHEN priced_by = 'model' THEN 1 ELSE 0 END) AS shifts_priced_by_model
FROM earnings_expected_shift
GROUP BY month;
