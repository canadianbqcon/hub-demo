-- Migration 005_airport_and_transport_coords for trips.db
-- Generated: 2026-08-10
-- Purpose: put the rest of the itinerary on the map. Activities and housing have
-- carried lat/lng since the start, but the two kinds of row that MOVE you around
-- carried none, so a day whose only entries were a flight and a car pickup drew
-- an empty map.
--
-- flights: coordinates are not a per-row property — LGA is LGA on every trip —
-- so they live in a shared `airports` cache keyed by IATA rather than as two more
-- columns on `flights`. Filled from Nominatim on first sight ("<IATA> airport",
-- which resolves DEN/LGA/AUS/SAL/CMH correctly) and reused forever after.
--
-- transportation: its `location` IS per-row free text ("Avis, 3400 Sable Blvd"),
-- so it geocodes in place the same way housing.address does.

-- +migrate up

CREATE TABLE IF NOT EXISTS airports (
    iata        TEXT PRIMARY KEY,
    name        TEXT DEFAULT '',
    lat         REAL,
    lng         REAL,
    resolved_at TEXT DEFAULT ''
);

ALTER TABLE transportation ADD COLUMN lat REAL;
ALTER TABLE transportation ADD COLUMN lng REAL;

-- +migrate down

DROP TABLE IF EXISTS airports;
-- SQLite has no portable DROP COLUMN on older versions.
-- To reverse the transportation columns: recreate the table without them.
-- Low-risk add (nullable columns, no data loss).
