-- earnings/008_averages_from_first_tip.sql
-- Price shifts from tipped history only. A source that has ever logged a
-- tipped shift averages only from its first one; a source with no tipped
-- shift (salaried, venture) averages everything. The cutoff is read from the
-- data, not hardcoded.
-- (Demo copy: comments shortened, schema unchanged.)
-- +migrate up
DROP VIEW IF EXISTS earnings_dow_avg;
DROP VIEW IF EXISTS earnings_source_avg;

CREATE VIEW earnings_shift_days_priced AS
SELECT d.*
FROM earnings_shift_days d
WHERE d.shift_date >= COALESCE(
        (SELECT MIN(s.shift_date)
           FROM earnings_shifts s JOIN earnings e ON e.id = s.earnings_id
          WHERE s.tipped = 1 AND e.source = d.source), '');

CREATE VIEW earnings_dow_avg AS
SELECT source,
       dow,
       COUNT(*)                    AS sample_shifts,
       ROUND(AVG(shift_total), 2)  AS avg_shift_total,
       ROUND(AVG(hours), 2)        AS avg_hours,
       MIN(shift_date)             AS first_shift,
       MAX(shift_date)             AS last_shift
FROM earnings_shift_days_priced
GROUP BY source, dow;

CREATE VIEW earnings_source_avg AS
SELECT source,
       COUNT(*)                   AS sample_shifts,
       ROUND(AVG(shift_total), 2) AS avg_shift_total,
       ROUND(AVG(hours), 2)       AS avg_hours
FROM earnings_shift_days_priced
GROUP BY source;

-- +migrate down
DROP VIEW IF EXISTS earnings_dow_avg;
DROP VIEW IF EXISTS earnings_source_avg;
DROP VIEW IF EXISTS earnings_shift_days_priced;

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

CREATE VIEW earnings_source_avg AS
SELECT source,
       COUNT(*)                   AS sample_shifts,
       ROUND(AVG(shift_total), 2) AS avg_shift_total,
       ROUND(AVG(hours), 2)       AS avg_hours
FROM earnings_shift_days
GROUP BY source;
