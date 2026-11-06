-- Migration 003_add_cal_status for trips.db
-- Generated: 2026-06-23
-- Purpose: add cal_status column to trips. The trips↔Google-Calendar sync is
-- one-directional (DB → Calendar). When a trip's calendar event is deleted
-- directly in Google Calendar (outside the dashboard), the DB never hears about
-- it and the row is left pointing at a dead cal_event_id. The dashboard's
-- daily-gated reconcile sets cal_status='deleted' on such future trips so the UI
-- can surface the divergence instead of silently hard-deleting the row.
-- Empty string = healthy/unknown; 'deleted' = calendar event is gone.

-- +migrate up

ALTER TABLE trips ADD COLUMN cal_status TEXT DEFAULT '';

-- +migrate down

-- SQLite has no portable DROP COLUMN on older versions.
-- To reverse: recreate the table without cal_status and migrate data across.
-- Low-risk add (nullable column with default, no data loss).
