-- Migration 008_answer_tracking for jobs.db
-- Generated: 2026-09-26
--
-- Purpose:
--   Schema for edit tracking and the frozen send record
--   (docs/specs/2026-09-26-answer-edit-tracking-design.md).
--   (1) answers.draft -- the sweep's own draft text, kept alongside the value
--       Sam may edit before sending. `save_answers(source="sweep")` writes
--       both together; `source="you"` (the Hub edit route) writes value only,
--       so the draft survives his edit for the learning feed.
--   (2) sent_answers -- one row per (application, field) frozen the moment an
--       application is sent, with no FK to form_fields so a form re-read
--       (which deletes and re-inserts form_fields/answers) cannot touch it.
--       question and answer store display text, not raw values, so the row
--       reads on its own without a form_fields join.
--
--   answers already follows the STRICT convention (migration 007), so draft
--   is added with a plain ALTER TABLE ADD COLUMN. sent_answers is a new table
--   and is STRICT too.
--
-- ⚠ PRE-MIGRATION BACKUP REQUIRED
--   `python db/migrate.py up jobs` takes it automatically; after this applies
--   cleanly, at most one jobs.db.bak-pre-migration-* survives per the
--   warehouse-contract retention invariant.

-- +migrate up

ALTER TABLE answers ADD COLUMN draft TEXT NOT NULL DEFAULT '';

UPDATE answers SET draft = value;

CREATE TABLE sent_answers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    ord            INTEGER NOT NULL DEFAULT 0,
    question       TEXT NOT NULL DEFAULT '',
    field_type     TEXT NOT NULL DEFAULT '',
    answer         TEXT NOT NULL DEFAULT '',
    draft          TEXT NOT NULL DEFAULT '',
    edited         INTEGER NOT NULL DEFAULT 0,
    rewritten      INTEGER NOT NULL DEFAULT 0,
    sent_at        TEXT NOT NULL DEFAULT ''
) STRICT;

CREATE INDEX IF NOT EXISTS idx_sent_answers_application
    ON sent_answers (application_id);

-- +migrate down

DROP INDEX IF EXISTS idx_sent_answers_application;
DROP TABLE sent_answers;

ALTER TABLE answers DROP COLUMN draft;
