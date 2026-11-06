-- earnings/007_expected_hours_from_window.sql
-- Price an unmodelled scheduled shift by its own hours (start_at to end_at)
-- times the day's average pay per hour, instead of a flat per-shift average.
-- Also corrects two tip-pool point values; re-run
-- `shift_pricing.py --calibrate --price` afterwards.
-- (Demo copy: comments shortened, point values are placeholders.)
-- +migrate up

UPDATE earnings_tip_points SET points = 6, verified = 1,
       note = 'Placeholder share.'
 WHERE source = 'juniper-and-co' AND role = 'server';

UPDATE earnings_tip_points SET points = 9, verified = 1,
       note = 'Placeholder share.'
 WHERE source = 'juniper-and-co' AND role = 'bartender';

UPDATE earnings_tip_points SET points = 9, verified = 0,
       note = 'Placeholder share.'
 WHERE source = 'juniper-and-co' AND role = 'bar_captain';

DROP VIEW earnings_expected_month_total;
DROP VIEW earnings_expected_month;
DROP VIEW earnings_expected_shift;

-- window_hours is computed once in the subquery so the HH:MM arithmetic is not
-- repeated three times below. (end - start + 1440) % 1440 carries a shift that
-- crosses midnight into the next day, matching shift_pricing.span().
-- ponytail: a window whose end equals its start reads as 0 hours, not 24. No
-- such row exists and a zero is the safe way to be wrong.
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
       COALESCE(sch.model_total,
                ROUND(sch.window_hours * (d.avg_shift_total / NULLIF(d.avg_hours, 0)), 2),
                ROUND(sch.window_hours * (o.avg_shift_total / NULLIF(o.avg_hours, 0)), 2),
                d.avg_shift_total, o.avg_shift_total)        AS expected_total,
       COALESCE(sch.model_hours, sch.window_hours,
                d.avg_hours, o.avg_hours)                    AS expected_hours,
       sch.model_wages                                       AS expected_wages,
       sch.model_tips                                        AS expected_tips,
       COALESCE(d.sample_shifts, 0)                          AS dow_sample_shifts,
       CASE WHEN sch.model_total IS NOT NULL THEN 'model'
            WHEN sch.window_hours IS NOT NULL AND d.avg_hours > 0 THEN 'dow_rate'
            WHEN sch.window_hours IS NOT NULL AND o.avg_hours > 0 THEN 'source_rate'
            WHEN d.avg_shift_total IS NOT NULL THEN 'dow'
            ELSE 'fallback' END                              AS priced_by,
       CASE WHEN sch.model_total IS NULL
             AND NOT (sch.window_hours IS NOT NULL AND d.avg_hours > 0)
             AND d.avg_shift_total IS NULL
            THEN 1 ELSE 0 END                                AS used_fallback
FROM (SELECT *,
             CASE WHEN start_at IS NOT NULL AND end_at IS NOT NULL THEN
                 ((  (CAST(substr(end_at, 1, 2) AS INTEGER) * 60
                    + CAST(substr(end_at, 4, 2) AS INTEGER))
                   - (CAST(substr(start_at, 1, 2) AS INTEGER) * 60
                    + CAST(substr(start_at, 4, 2) AS INTEGER))
                   + 1440) % 1440) / 60.0
             END AS window_hours
      FROM earnings_scheduled_shifts) sch
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
UPDATE earnings_tip_points SET points = 5, verified = 1,
       note = 'Placeholder share.'
 WHERE source = 'juniper-and-co' AND role = 'server';
UPDATE earnings_tip_points SET points = 8, verified = 0,
       note = 'Placeholder share.'
 WHERE source = 'juniper-and-co' AND role = 'bartender';
UPDATE earnings_tip_points SET points = 8, verified = 0,
       note = 'Placeholder share.'
 WHERE source = 'juniper-and-co' AND role = 'bar_captain';

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
