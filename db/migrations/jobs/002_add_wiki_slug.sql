-- Migration 002_add_wiki_slug for jobs.db
-- Generated: 2026-05-22
-- Purpose: add wiki_slug columns to applications and skills tables per warehouse
-- contract slug-as-FK rule.
--   applications.wiki_slug -> wiki/contacts/<company-slug> if a contact node exists
--   skills.wiki_slug       -> wiki/concepts/<skill-slug> if a concept node exists

-- +migrate up

ALTER TABLE applications ADD COLUMN wiki_slug TEXT DEFAULT NULL;
ALTER TABLE skills ADD COLUMN wiki_slug TEXT DEFAULT NULL;

-- +migrate down

-- SQLite does not support DROP COLUMN in all versions.
-- To reverse: recreate the tables without wiki_slug columns and migrate data across.
