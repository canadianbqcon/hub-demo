-- Migration 002_add_wiki_slug for purchases.db
-- Generated: 2026-05-22
-- Purpose: add wiki_slug column to decisions table per warehouse contract slug-as-FK rule.
-- A purchase decision row can reference a wiki decision node (e.g.
-- wiki/decisions/carry-on-luggage-pick) where the reasoning and outcome live.

-- +migrate up

ALTER TABLE decisions ADD COLUMN wiki_slug TEXT DEFAULT NULL;

-- +migrate down

-- SQLite does not support DROP COLUMN in all versions.
-- To reverse: recreate the table without wiki_slug and migrate data across.
