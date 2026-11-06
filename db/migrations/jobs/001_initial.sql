-- Migration 001_initial for jobs.db
-- Generated: 2026-05-22
-- Source: snapshot of existing schema at Phase 1 Step 2.
-- This is a BASELINE migration. The four databases already contain these
-- tables before Phase 1; this file documents that starting state so future
-- migrations have a known baseline to diff against.
--
-- Apply with: python data/migrate.py baseline jobs
-- (DO NOT run via `up` against the existing databases — the CREATE
--  statements will collide with the live tables. `baseline` records
--  this migration as applied without executing the SQL.)

-- +migrate up

-- table: application_process_steps
CREATE TABLE application_process_steps (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
                step_order     INTEGER NOT NULL DEFAULT 0,
                label          TEXT NOT NULL,
                step_type      TEXT DEFAULT 'interview',
                status         TEXT DEFAULT 'pending',
                notes          TEXT DEFAULT '',
                created        TEXT DEFAULT (date('now')),
                updated        TEXT DEFAULT (date('now'))
            );

-- table: application_skills
CREATE TABLE application_skills (
                application_id INTEGER REFERENCES applications(id) ON DELETE CASCADE,
                skill_id       INTEGER REFERENCES skills(id) ON DELETE CASCADE,
                gap            TEXT DEFAULT 'medium',
                notes          TEXT DEFAULT '',
                PRIMARY KEY (application_id, skill_id)
            );

-- table: application_stories
CREATE TABLE application_stories (
                application_id INTEGER REFERENCES applications(id) ON DELETE CASCADE,
                story_id       INTEGER REFERENCES stories(id) ON DELETE CASCADE,
                notes          TEXT DEFAULT '',
                PRIMARY KEY (application_id, story_id)
            );

-- table: applications
CREATE TABLE applications (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                company     TEXT NOT NULL,
                role        TEXT NOT NULL,
                status      TEXT DEFAULT 'researching',
                priority    TEXT DEFAULT 'medium',
                source      TEXT DEFAULT '',
                job_url     TEXT DEFAULT '',
                salary_min  REAL,
                salary_max  REAL,
                date_applied TEXT DEFAULT '',
                notes       TEXT DEFAULT '',
                created     TEXT DEFAULT (date('now')),
                updated     TEXT DEFAULT (date('now'))
            , location TEXT DEFAULT '', priority_reason TEXT DEFAULT '', score_role INTEGER DEFAULT 0, work_arrangement TEXT DEFAULT '', employment_type TEXT DEFAULT '', red_flags TEXT DEFAULT '', red_flags_risk TEXT DEFAULT '', culture_rating REAL DEFAULT NULL, culture_recommend INTEGER DEFAULT NULL, culture_work_life REAL DEFAULT NULL, requirements TEXT DEFAULT '', nice_to_haves TEXT DEFAULT '');

-- table: company_research
CREATE TABLE company_research (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
                category       TEXT DEFAULT 'general',
                content        TEXT DEFAULT '',
                created        TEXT DEFAULT (date('now'))
            , subcategory TEXT DEFAULT '');

-- table: cover_letters
CREATE TABLE cover_letters (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
                tone           TEXT DEFAULT '',
                angle          TEXT DEFAULT '',
                draft          TEXT DEFAULT '',
                created        TEXT DEFAULT (date('now')),
                updated        TEXT DEFAULT (date('now'))
            );

-- table: glossary
CREATE TABLE glossary (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                term       TEXT NOT NULL,
                definition TEXT DEFAULT '',
                category   TEXT DEFAULT 'general',
                known      INTEGER DEFAULT 0
            );

-- table: interviewers
CREATE TABLE interviewers (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
                name           TEXT NOT NULL,
                role           TEXT DEFAULT '',
                linkedin_url   TEXT DEFAULT '',
                background     TEXT DEFAULT '',
                notes          TEXT DEFAULT '',
                created        TEXT DEFAULT (date('now'))
            );

-- table: resume_notes
CREATE TABLE resume_notes (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
                section        TEXT DEFAULT 'general',
                note           TEXT DEFAULT '',
                created        TEXT DEFAULT (date('now'))
            );

-- table: skills
CREATE TABLE skills (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                name     TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                level    TEXT DEFAULT 'learning',
                notes    TEXT DEFAULT '',
                created  TEXT DEFAULT (date('now')),
                updated  TEXT DEFAULT (date('now'))
            );

-- table: stories
CREATE TABLE stories (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                title      TEXT NOT NULL,
                situation  TEXT DEFAULT '',
                task       TEXT DEFAULT '',
                action     TEXT DEFAULT '',
                result     TEXT DEFAULT '',
                tags       TEXT DEFAULT '[]',
                created    TEXT DEFAULT (date('now')),
                updated    TEXT DEFAULT (date('now'))
            );

-- +migrate down
-- No-op. Rolling back the baseline is not a meaningful operation —
-- it would mean dropping every table and losing all data. If you
-- truly need a fresh database, delete the .db file and re-baseline.
