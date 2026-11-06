-- Migration 001_initial for checklists.db
-- Generated: 2026-05-22
-- Source: snapshot of existing schema at Phase 1 Step 2.
-- This is a BASELINE migration. The four databases already contain these
-- tables before Phase 1; this file documents that starting state so future
-- migrations have a known baseline to diff against.
--
-- Apply with: python data/migrate.py baseline checklists
-- (DO NOT run via `up` against the existing databases — the CREATE
--  statements will collide with the live tables. `baseline` records
--  this migration as applied without executing the SQL.)

-- +migrate up

-- table: checklist_items
CREATE TABLE checklist_items (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                checklist_id INTEGER NOT NULL REFERENCES checklists(id) ON DELETE CASCADE,
                text         TEXT NOT NULL,
                section      TEXT DEFAULT '',
                checked      INTEGER DEFAULT 0,
                sort_order   INTEGER DEFAULT 0
            );

-- table: checklists
CREATE TABLE checklists (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                category    TEXT DEFAULT '',
                description TEXT DEFAULT ''
            );

-- +migrate down
-- No-op. Rolling back the baseline is not a meaningful operation —
-- it would mean dropping every table and losing all data. If you
-- truly need a fresh database, delete the .db file and re-baseline.
