-- Migration 001_initial for purchases.db
-- Generated: 2026-05-22
-- Source: snapshot of existing schema at Phase 1 Step 2.
-- This is a BASELINE migration. The four databases already contain these
-- tables before Phase 1; this file documents that starting state so future
-- migrations have a known baseline to diff against.
--
-- Apply with: python data/migrate.py baseline purchases
-- (DO NOT run via `up` against the existing databases — the CREATE
--  statements will collide with the live tables. `baseline` records
--  this migration as applied without executing the SQL.)

-- +migrate up

-- table: budget_entries
CREATE TABLE budget_entries (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id     INTEGER NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
                label           TEXT DEFAULT '',
                planned_amount  REAL DEFAULT 0,
                actual_amount   REAL,
                currency        TEXT DEFAULT 'USD',
                paid_on         TEXT DEFAULT '',
                payment_method  TEXT DEFAULT '',
                status          TEXT DEFAULT 'planned'
            );

-- table: candidates
CREATE TABLE candidates (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id     INTEGER NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
                name            TEXT NOT NULL,
                vendor          TEXT DEFAULT '',
                base_price      REAL,
                currency        TEXT DEFAULT 'USD',
                url             TEXT DEFAULT '',
                image_url       TEXT DEFAULT '',
                status          TEXT DEFAULT 'considering',
                rank            INTEGER,
                ecosystem_notes TEXT DEFAULT '',
                return_policy   TEXT DEFAULT '',
                warranty        TEXT DEFAULT '',
                notes           TEXT DEFAULT ''
            );

-- table: criteria
CREATE TABLE criteria (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id INTEGER NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
                name        TEXT NOT NULL,
                priority    TEXT DEFAULT 'nice-to-have',
                weight      INTEGER DEFAULT 3,
                notes       TEXT DEFAULT ''
            );

-- table: decisions
CREATE TABLE decisions (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                name             TEXT NOT NULL,
                category         TEXT DEFAULT '',
                use_case         TEXT DEFAULT '',
                purchase_type    TEXT DEFAULT 'one-time-product',
                stage            TEXT DEFAULT 'exploring',
                time_horizon     TEXT DEFAULT '',
                depth            TEXT DEFAULT 'standard',
                budget_max       REAL,
                currency         TEXT DEFAULT 'USD',
                hard_constraints TEXT DEFAULT '',
                soft_preferences TEXT DEFAULT '',
                verdict_candidate_id INTEGER,
                verdict_reason   TEXT DEFAULT '',
                notes            TEXT DEFAULT '',
                created          TEXT DEFAULT (date('now')),
                updated          TEXT DEFAULT (date('now'))
            , project_id INTEGER, use_context TEXT DEFAULT '', pain_point TEXT DEFAULT '', value_prop TEXT DEFAULT '');

-- table: price_points
CREATE TABLE price_points (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id  INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
                vendor        TEXT DEFAULT '',
                price         REAL NOT NULL,
                currency      TEXT DEFAULT 'USD',
                url           TEXT DEFAULT '',
                observed_on   TEXT DEFAULT (date('now')),
                in_stock      INTEGER DEFAULT 1,
                channel_notes TEXT DEFAULT '',
                notes         TEXT DEFAULT ''
            );

-- table: projects
CREATE TABLE projects (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                name     TEXT NOT NULL,
                status   TEXT DEFAULT 'active',
                category TEXT DEFAULT '',
                notes    TEXT DEFAULT '',
                created  TEXT DEFAULT (date('now')),
                updated  TEXT DEFAULT (date('now'))
            );

-- table: pros_cons
CREATE TABLE pros_cons (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
                kind         TEXT DEFAULT 'pro',
                text         TEXT NOT NULL
            );

-- table: reviews
CREATE TABLE reviews (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_id       INTEGER NOT NULL REFERENCES decisions(id) ON DELETE CASCADE,
                candidate_id      INTEGER REFERENCES candidates(id) ON DELETE CASCADE,
                source_type       TEXT DEFAULT 'article',
                url               TEXT DEFAULT '',
                title             TEXT DEFAULT '',
                author            TEXT DEFAULT '',
                takeaway          TEXT DEFAULT '',
                sentiment         TEXT DEFAULT 'mixed',
                is_current_version INTEGER DEFAULT 1,
                notes             TEXT DEFAULT ''
            );

-- table: specs
CREATE TABLE specs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
                criterion_id INTEGER REFERENCES criteria(id) ON DELETE SET NULL,
                key          TEXT NOT NULL,
                value        TEXT DEFAULT ''
            );

-- +migrate down
-- No-op. Rolling back the baseline is not a meaningful operation —
-- it would mean dropping every table and losing all data. If you
-- truly need a fresh database, delete the .db file and re-baseline.
