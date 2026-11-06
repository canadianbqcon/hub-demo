-- Migration 021_airport_timezone for trips.db
-- Date: 2026-09-09
-- Purpose: give every airport the zone its clocks are written in.
--
-- Flight stamps are local wall-clock at their own end — LGA 06:30 is Eastern,
-- DEN 08:40 is Mountain — which is the right thing to PRINT and the wrong thing
-- to SUBTRACT. Every consumer that took a difference assumed one zone, so the
-- board called a 4h10m flight "2h 10m". gcal.py carries the same gap in a
-- comment ("trips.db holds no destination timezone to write a time in") and
-- writes its event bodies without one.
--
-- The zone is a property of the AIRPORT, not of the flight, so it caches beside
-- lat/lng by IATA and is resolved once — same shape and same reasoning as
-- migration 005. IANA name rather than a stored offset: the offset changes
-- twice a year and a September flight and a January flight out of the same gate
-- do not share one.

-- +migrate up

ALTER TABLE airports ADD COLUMN tz TEXT DEFAULT '';

-- The nine already cached. Resolving these from the network would work too, but
-- they are known and this keeps the fix from depending on a lookup at run time.
UPDATE airports SET tz = 'America/New_York'   WHERE iata IN ('LGA','JFK','EWR','IAD');
UPDATE airports SET tz = 'America/Denver'     WHERE iata = 'DEN';
UPDATE airports SET tz = 'America/Chicago'    WHERE iata IN ('AUS','IAH');
UPDATE airports SET tz = 'America/New_York'   WHERE iata = 'CMH';
UPDATE airports SET tz = 'America/El_Salvador' WHERE iata = 'SAL';

-- +migrate down

-- SQLite has no portable DROP COLUMN on older versions; the column is nullable
-- with an empty default, and an empty tz reads as "unknown" everywhere it is
-- consumed, so leaving it in place is harmless.
