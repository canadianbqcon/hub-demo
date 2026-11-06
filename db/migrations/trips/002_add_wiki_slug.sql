-- Migration 002_add_wiki_slug for trips.db
-- Generated: 2026-05-22
-- Purpose: add wiki_slug column to trips table per warehouse contract slug-as-FK rule.
-- A trip row can reference a wiki note (e.g. wiki/notes/texas-trip-2026) for
-- trip research, maps, and planning context.
-- Note: trips.members already has contact_slug from the original schema.

-- +migrate up

ALTER TABLE trips ADD COLUMN wiki_slug TEXT DEFAULT NULL;

-- +migrate down

-- SQLite does not support DROP COLUMN in all versions.
-- To reverse: recreate the table without wiki_slug and migrate data across.
-- In practice this migration is low-risk (nullable column, no data loss on add).
