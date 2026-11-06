-- Migration 007_autopilot for jobs.db
-- Generated: 2026-09-25
--
-- Purpose:
--   Schema for the job-autopilot pipeline (docs/specs/2026-09-25-job-autopilot-design.md).
--   (1) 8 new columns on applications: the autopilot's own bookkeeping (fit
--       score/reason, approve stamp, submit log, ATS identity, canonical dedupe
--       URL) plus a screenshot_path for the confirmation / post-click capture --
--       a dedicated column rather than packing a path into submit_log, since the
--       API route serving the screenshot (Task 5) needs to select it directly.
--   (2) form_fields -- one row per application-form field, read by
--       hub/jobs/form_schema.py (Task 3).
--   (3) answers -- one row per (application, field), the value that gets typed
--       in at submit time; UNIQUE(application_id, form_field_id) so a re-read of
--       the form upserts rather than duplicating.
--
--   applications is already STRICT (migration 004) so the new columns are added
--   with plain ALTER TABLE ADD COLUMN, same as migration 005. form_fields and
--   answers are new tables and follow the STRICT convention migration 003 set
--   for tables added after 004.
--
-- ⚠ PRE-MIGRATION BACKUP REQUIRED
--   `python db/migrate.py up jobs` takes it automatically; after this applies
--   cleanly, at most one jobs.db.bak-pre-migration-* survives per the
--   warehouse-contract retention invariant.

-- +migrate up

ALTER TABLE applications ADD COLUMN fit_score       REAL;
ALTER TABLE applications ADD COLUMN fit_reason       TEXT NOT NULL DEFAULT '';
ALTER TABLE applications ADD COLUMN approved_at      TEXT NOT NULL DEFAULT '';
ALTER TABLE applications ADD COLUMN submit_log       TEXT NOT NULL DEFAULT '';
ALTER TABLE applications ADD COLUMN ats_posting_id   TEXT NOT NULL DEFAULT '';
ALTER TABLE applications ADD COLUMN ats_host         TEXT NOT NULL DEFAULT '';
ALTER TABLE applications ADD COLUMN canonical_url    TEXT NOT NULL DEFAULT '';
ALTER TABLE applications ADD COLUMN screenshot_path  TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_applications_canonical_url
    ON applications (canonical_url);
CREATE INDEX IF NOT EXISTS idx_applications_ats_posting
    ON applications (ats_host, ats_posting_id);

CREATE TABLE form_fields (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    ord            INTEGER NOT NULL DEFAULT 0,
    label          TEXT NOT NULL DEFAULT '',
    name           TEXT NOT NULL DEFAULT '',
    field_type     TEXT NOT NULL DEFAULT '',
    required       INTEGER NOT NULL DEFAULT 0,
    options_json   TEXT NOT NULL DEFAULT '[]',
    is_demographic INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE INDEX IF NOT EXISTS idx_form_fields_application
    ON form_fields (application_id);

CREATE TABLE answers (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    form_field_id  INTEGER NOT NULL REFERENCES form_fields(id) ON DELETE CASCADE,
    value          TEXT NOT NULL DEFAULT '',
    rewritten      INTEGER NOT NULL DEFAULT 0,
    UNIQUE(application_id, form_field_id)
) STRICT;

-- +migrate down

DROP INDEX IF EXISTS idx_form_fields_application;
DROP TABLE answers;
DROP TABLE form_fields;

DROP INDEX IF EXISTS idx_applications_ats_posting;
DROP INDEX IF EXISTS idx_applications_canonical_url;

ALTER TABLE applications DROP COLUMN screenshot_path;
ALTER TABLE applications DROP COLUMN canonical_url;
ALTER TABLE applications DROP COLUMN ats_host;
ALTER TABLE applications DROP COLUMN ats_posting_id;
ALTER TABLE applications DROP COLUMN submit_log;
ALTER TABLE applications DROP COLUMN approved_at;
ALTER TABLE applications DROP COLUMN fit_reason;
ALTER TABLE applications DROP COLUMN fit_score;
