-- vault-code/db/migrations/earnings/005_shift_pricing_model.sql
-- Per-shift pricing, replacing "every Friday is worth the average Friday".
--
-- Migrations 003/004 price a scheduled shift at its day-of-week historical
-- average. That cannot tell a 6h late Friday (9pm-3am, sharing the pool with a
-- second barback) from a 10.5h solo Friday, or a 13.5h buyout from an ordinary
-- Sunday -- it prices each pair identically. Measured against the model this
-- adds, that under-forecast August 2026 by $900, of which $540 was the Aug 9
-- buyout priced as a normal Sunday.
--
-- What actually sets the number is the tip pool's POINTS-PER-HOUR split. Each
-- hour, the pool for that hour is divided by the points of whoever is on the
-- clock: barback 6, server 5, and so on. Two barbacks in the same hour each
-- take half the barback share for that hour. So the same 10.5h span pays
-- differently depending on who else is standing there, which is the fact the
-- day-of-week average throws away.
--
-- The math itself lives in finances/shift_pricing.py (hourly loops over a crew
-- roster are miserable in SQL and clear in Python). It writes its answer back
-- into model_total/model_hours here, so the existing view chain -- and
-- db.ui_forecast(), which reads earnings_expected_shift for benefit-week hours
-- -- keeps working with a single COALESCE change.
-- +migrate up

-- Tip-pool points by role, per job. `verified` separates what Sam confirmed
-- from what the model assumes: an assumed number still prices a shift, but the
-- UI labels it, because a forecast built on a guess must not read as measured.
CREATE TABLE earnings_tip_points (
    source   TEXT NOT NULL,
    role     TEXT NOT NULL,
    points   REAL NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    note     TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (source, role)
) STRICT;

INSERT INTO earnings_tip_points (source, role, points, verified, note) VALUES
    ('juniper-and-co', 'barback',      5, 1, 'Placeholder share.'),
    ('juniper-and-co', 'server',       5, 1, 'Placeholder share.'),
    ('juniper-and-co', 'bartender',    8, 0, 'Placeholder share, assumed.'),
    ('juniper-and-co', 'bar_captain',  8, 0, 'Placeholder share, assumed.'),
    ('juniper-and-co', 'host',         3, 0, 'Placeholder share, assumed.'),
    ('juniper-and-co', 'bar_prep',     0, 1, 'Untipped.'),
    ('juniper-and-co', 'manager',      0, 1, 'Untipped.'),
    ('juniper-and-co', 'chef',         0, 1, 'Untipped.');

-- Tunable inputs: the hourly tip-pool density by day part, the tipped wage rate,
-- and the buyout multiple. Densities are BACK-SOLVED from Sam's own paid
-- shifts, not picked -- see shift_pricing.py's calibration note. Kept in a table
-- rather than a constant so a wrong one is a row edit, not a code change.
CREATE TABLE earnings_pricing_params (
    source   TEXT NOT NULL,
    key      TEXT NOT NULL,
    value    REAL NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    note     TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (source, key)
) STRICT;

INSERT INTO earnings_pricing_params (source, key, value, verified, note) VALUES
    ('juniper-and-co', 'tipped_wage_rate',    10.00, 1, 'Placeholder tipped wage.'),
    ('juniper-and-co', 'pool_weekend_early', 100.00, 0, 'Placeholder density, Fri/Sat before 21:00.'),
    ('juniper-and-co', 'pool_weekend_peak',  150.00, 0, 'Placeholder density, Fri/Sat from 21:00.'),
    ('juniper-and-co', 'pool_sunday',         40.00, 0, 'Placeholder density.'),
    ('juniper-and-co', 'pool_weeknight',      40.00, 0, 'Placeholder density.'),
    ('juniper-and-co', 'pool_thursday',       50.00, 0, 'Placeholder density.'),
    ('juniper-and-co', 'buyout_multiple',      2.00, 0, 'Placeholder multiple.');

-- His own scheduled window and role, plus the model output written back.
-- Nullable throughout: a row the model has not priced falls through to the
-- day-of-week average exactly as before, so nothing breaks mid-backfill.
ALTER TABLE earnings_scheduled_shifts ADD COLUMN start_at     TEXT;    -- 'HH:MM' local
ALTER TABLE earnings_scheduled_shifts ADD COLUMN end_at       TEXT;    -- 'HH:MM'; < start_at means it crosses midnight
ALTER TABLE earnings_scheduled_shifts ADD COLUMN role         TEXT;
ALTER TABLE earnings_scheduled_shifts ADD COLUMN shift_kind   TEXT;    -- 'regular' | 'buyout'
ALTER TABLE earnings_scheduled_shifts ADD COLUMN model_hours  REAL;
ALTER TABLE earnings_scheduled_shifts ADD COLUMN model_wages  REAL;
ALTER TABLE earnings_scheduled_shifts ADD COLUMN model_tips   REAL;
ALTER TABLE earnings_scheduled_shifts ADD COLUMN model_total  REAL;
ALTER TABLE earnings_scheduled_shifts ADD COLUMN model_share  REAL;    -- mean points share across worked hours, for display
ALTER TABLE earnings_scheduled_shifts ADD COLUMN priced_at    TEXT;
ALTER TABLE earnings_scheduled_shifts ADD COLUMN pricing_note TEXT;

-- Everyone else sharing the pool that night. One row per coworker per shift;
-- `label` is display-only. An end_at earlier than start_at crosses midnight.
CREATE TABLE earnings_shift_crew (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    shift_id INTEGER NOT NULL REFERENCES earnings_scheduled_shifts(id) ON DELETE CASCADE,
    role     TEXT NOT NULL,
    start_at TEXT NOT NULL,
    end_at   TEXT NOT NULL,
    label    TEXT NOT NULL DEFAULT ''
) STRICT;

CREATE INDEX idx_earnings_shift_crew_shift ON earnings_shift_crew(shift_id);

-- Rebuilt: the model price wins when present, the day-of-week average is the
-- fallback, and `priced_by` says which produced the number so the UI never
-- passes off a fallback as a modelled figure.
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
SELECT month, source, COUNT(*) AS scheduled_shifts,
       ROUND(SUM(expected_total), 2) AS expected_total,
       SUM(used_fallback) AS shifts_priced_by_fallback
FROM earnings_expected_shift GROUP BY month, source;
CREATE VIEW earnings_expected_month_total AS
SELECT month, COUNT(*) AS scheduled_shifts, COUNT(DISTINCT source) AS jobs,
       ROUND(SUM(expected_total), 2) AS expected_total,
       SUM(used_fallback) AS shifts_priced_by_fallback
FROM earnings_expected_shift GROUP BY month;
DROP INDEX IF EXISTS idx_earnings_shift_crew_shift;
DROP TABLE IF EXISTS earnings_shift_crew;
DROP TABLE IF EXISTS earnings_pricing_params;
DROP TABLE IF EXISTS earnings_tip_points;
-- ALTER TABLE ... DROP COLUMN needs SQLite 3.35+; these are additive and
-- harmless if left, so the down migration leaves them rather than rebuilding
-- the table and risking the actuals scaffolding it carries.
