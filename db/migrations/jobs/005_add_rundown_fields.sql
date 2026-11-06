-- Migration 005_add_rundown_fields for jobs.db
-- Generated: 2026-06-01
--
-- Purpose:
--   Add two plain-language rundown columns to applications, surfaced in a new
--   full-width section at the top of the Stage 1 intake tab (above the keep/cut
--   snap-card):
--     company_summary — what the company is + what their product/service is
--     role_summary    — what you'd do in the role + what it provides the company
--   Both are best-effort Stage 1 fills (no live AI in this module; Claude Code
--   writes them at intake). Editable + autosaving in the UI.
--
-- applications is already STRICT (migration 004), so this is purely additive —
-- ALTER TABLE ADD COLUMN is STRICT-safe. TEXT NOT NULL DEFAULT '' matches the
-- new-column convention from 004 (no historic NULLs possible).
--
-- ⚠ PRE-MIGRATION BACKUP REQUIRED
--   Before running `python data/migrate.py up jobs`, copy the DB:
--       cp data/jobs.db data/jobs.db.bak-pre-migration-005-2026-06-01
--   After this applies cleanly, delete the older
--   jobs.db.bak-pre-migration-004-* per the warehouse-contract
--   "at most one .bak per database" rule.

-- +migrate up

ALTER TABLE applications ADD COLUMN company_summary TEXT NOT NULL DEFAULT '';
ALTER TABLE applications ADD COLUMN role_summary    TEXT NOT NULL DEFAULT '';

-- +migrate down

ALTER TABLE applications DROP COLUMN role_summary;
ALTER TABLE applications DROP COLUMN company_summary;
