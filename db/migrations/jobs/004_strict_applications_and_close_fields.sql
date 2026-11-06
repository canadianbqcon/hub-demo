-- Migration 004_strict_applications_and_close_fields for jobs.db
-- Generated: 2026-05-25
--
-- Purpose:
--   (1) Convert applications from loose to STRICT (opportunistic per
--       data/CLAUDE.md schema-touch rule).
--   (2) Add 8 new columns to applications for the Vesper jobs dashboard
--       rebuild:
--         years_required        — INTEGER (nullable, NULL = unknown)
--         listing_posted_date   — TEXT, ISO date when the JD was posted
--         url_verified_at       — TEXT, ISO datetime the job_url last checked
--         closed_well           — TEXT, retro free-text: what went well
--         closed_didnt          — TEXT, retro free-text: what did not
--         closed_differently    — TEXT, retro free-text: what to do differently
--         closed_reason         — TEXT, enum (validated at API layer):
--                                   weak_customer_signal, technical_gap,
--                                   culture_mismatch, comp_misalignment,
--                                   headcount_change, candidate_withdrew,
--                                   no_reason_given, offer_accepted,
--                                   ineligible (added 2026-07-29)
--         closed_date           — TEXT, ISO date the application was closed
--   (3) Introduce a new first-stage pipeline status 'intaking' by changing
--       applications.status DEFAULT from 'researching' to 'intaking'.
--       Existing rows are NOT remapped — they keep whatever status they had.
--   (4) Convert resume_notes from loose to STRICT and add
--         char_limit INTEGER (nullable, NULL = no limit set)
--       Used by the application-prompt cards in the new UI to track
--       per-prompt char caps without polluting the note body.
--
-- ⚠ PRE-MIGRATION BACKUP REQUIRED
--   Before running `python data/migrate.py up jobs`, copy the DB:
--       cp data/jobs.db data/jobs.db.bak-pre-migration-004-2026-05-25
--   Then, after this migration applies cleanly, delete the older .bak
--   files (jobs.db.bak-pre-migration-001-* and -003-*) per the
--   warehouse-contract "at most one .bak per database" rule.
--
-- ⚠ FOREIGN-KEY HANDLING
--   applications is referenced by 9 child tables. We DROP and rebuild it,
--   so foreign_keys must be OFF for the duration of the script. SQLite
--   requires this to happen in autocommit mode; executescript() commits
--   any pending transaction first, so the first PRAGMA is effective.
--
-- ⚠ NOT NULL POLICY
--   Existing columns preserve their original nullability semantics
--   (mostly `TEXT DEFAULT ''` — nullable with a default). The 8 NEW
--   text-typed columns are `TEXT NOT NULL DEFAULT ''` because there is
--   no historic data that could be NULL. INSERT SELECT uses COALESCE
--   on every TEXT-default-empty source column as a defensive guard
--   against historic NULLs.

-- +migrate up

PRAGMA foreign_keys = OFF;

-- (1) applications → STRICT + new default status + 8 new columns
CREATE TABLE applications_strict (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    company               TEXT NOT NULL,
    role                  TEXT NOT NULL,
    status                TEXT DEFAULT 'intaking',
    priority              TEXT DEFAULT 'medium',
    source                TEXT DEFAULT '',
    job_url               TEXT DEFAULT '',
    salary_min            REAL,
    salary_max            REAL,
    date_applied          TEXT DEFAULT '',
    notes                 TEXT DEFAULT '',
    created               TEXT DEFAULT (date('now')),
    updated               TEXT DEFAULT (date('now')),
    location              TEXT DEFAULT '',
    priority_reason       TEXT DEFAULT '',
    score_role            INTEGER DEFAULT 0,
    work_arrangement      TEXT DEFAULT '',
    employment_type       TEXT DEFAULT '',
    red_flags             TEXT DEFAULT '',
    red_flags_risk        TEXT DEFAULT '',
    culture_rating        REAL,
    culture_recommend     INTEGER,
    culture_work_life     REAL,
    requirements          TEXT DEFAULT '',
    nice_to_haves         TEXT DEFAULT '',
    wiki_slug             TEXT,
    -- ── new in 004 ──
    years_required        INTEGER,
    listing_posted_date   TEXT NOT NULL DEFAULT '',
    url_verified_at       TEXT NOT NULL DEFAULT '',
    closed_well           TEXT NOT NULL DEFAULT '',
    closed_didnt          TEXT NOT NULL DEFAULT '',
    closed_differently    TEXT NOT NULL DEFAULT '',
    closed_reason         TEXT NOT NULL DEFAULT '',
    closed_date           TEXT NOT NULL DEFAULT ''
) STRICT;

INSERT INTO applications_strict (
    id, company, role, status, priority, source, job_url,
    salary_min, salary_max, date_applied, notes, created, updated,
    location, priority_reason, score_role, work_arrangement, employment_type,
    red_flags, red_flags_risk, culture_rating, culture_recommend,
    culture_work_life, requirements, nice_to_haves, wiki_slug
)
SELECT
    id,
    company,
    role,
    COALESCE(status, 'researching'),
    COALESCE(priority, 'medium'),
    COALESCE(source, ''),
    COALESCE(job_url, ''),
    salary_min,
    salary_max,
    COALESCE(date_applied, ''),
    COALESCE(notes, ''),
    COALESCE(created, date('now')),
    COALESCE(updated, date('now')),
    COALESCE(location, ''),
    COALESCE(priority_reason, ''),
    COALESCE(score_role, 0),
    COALESCE(work_arrangement, ''),
    COALESCE(employment_type, ''),
    COALESCE(red_flags, ''),
    COALESCE(red_flags_risk, ''),
    culture_rating,
    culture_recommend,
    culture_work_life,
    COALESCE(requirements, ''),
    COALESCE(nice_to_haves, ''),
    wiki_slug
FROM applications;

DROP TABLE applications;
ALTER TABLE applications_strict RENAME TO applications;

-- (2) resume_notes → STRICT + new char_limit column
CREATE TABLE resume_notes_strict (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id  INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    section         TEXT DEFAULT 'general',
    note            TEXT DEFAULT '',
    char_limit      INTEGER,
    created         TEXT DEFAULT (date('now'))
) STRICT;

INSERT INTO resume_notes_strict (id, application_id, section, note, char_limit, created)
SELECT
    id,
    application_id,
    COALESCE(section, 'general'),
    COALESCE(note, ''),
    NULL,
    COALESCE(created, date('now'))
FROM resume_notes;

DROP TABLE resume_notes;
ALTER TABLE resume_notes_strict RENAME TO resume_notes;

PRAGMA foreign_keys = ON;

-- +migrate down
--
-- Reverse the STRICT conversions back to the loose schemas and drop the 8
-- new application columns + char_limit on resume_notes. The 'intaking'
-- default reverts to 'researching'; existing rows with status='intaking'
-- are NOT remapped on down — that value may have been chosen deliberately,
-- and the loose schema accepts arbitrary text in status anyway.

PRAGMA foreign_keys = OFF;

CREATE TABLE applications_old (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    company               TEXT NOT NULL,
    role                  TEXT NOT NULL,
    status                TEXT DEFAULT 'researching',
    priority              TEXT DEFAULT 'medium',
    source                TEXT DEFAULT '',
    job_url               TEXT DEFAULT '',
    salary_min            REAL,
    salary_max            REAL,
    date_applied          TEXT DEFAULT '',
    notes                 TEXT DEFAULT '',
    created               TEXT DEFAULT (date('now')),
    updated               TEXT DEFAULT (date('now')),
    location              TEXT DEFAULT '',
    priority_reason       TEXT DEFAULT '',
    score_role            INTEGER DEFAULT 0,
    work_arrangement      TEXT DEFAULT '',
    employment_type       TEXT DEFAULT '',
    red_flags             TEXT DEFAULT '',
    red_flags_risk        TEXT DEFAULT '',
    culture_rating        REAL DEFAULT NULL,
    culture_recommend     INTEGER DEFAULT NULL,
    culture_work_life     REAL DEFAULT NULL,
    requirements          TEXT DEFAULT '',
    nice_to_haves         TEXT DEFAULT '',
    wiki_slug             TEXT DEFAULT NULL
);

INSERT INTO applications_old (
    id, company, role, status, priority, source, job_url,
    salary_min, salary_max, date_applied, notes, created, updated,
    location, priority_reason, score_role, work_arrangement, employment_type,
    red_flags, red_flags_risk, culture_rating, culture_recommend,
    culture_work_life, requirements, nice_to_haves, wiki_slug
)
SELECT
    id, company, role, status, priority, source, job_url,
    salary_min, salary_max, date_applied, notes, created, updated,
    location, priority_reason, score_role, work_arrangement, employment_type,
    red_flags, red_flags_risk, culture_rating, culture_recommend,
    culture_work_life, requirements, nice_to_haves, wiki_slug
FROM applications;

DROP TABLE applications;
ALTER TABLE applications_old RENAME TO applications;

CREATE TABLE resume_notes_old (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    section        TEXT DEFAULT 'general',
    note           TEXT DEFAULT '',
    created        TEXT DEFAULT (date('now'))
);

INSERT INTO resume_notes_old (id, application_id, section, note, created)
SELECT id, application_id, section, note, created FROM resume_notes;

DROP TABLE resume_notes;
ALTER TABLE resume_notes_old RENAME TO resume_notes;

PRAGMA foreign_keys = ON;
