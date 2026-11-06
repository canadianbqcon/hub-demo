-- Migration 001_initial for cards.db
-- Generated: 2026-06-06
-- Onboarded via wiki/decisions/onboard-finance.md
--
-- This is a FRESH-DB migration (the database does not exist yet), so apply with:
--     python data/migrate.py up cards
-- (NOT `baseline` — baseline is only for the pre-Phase-1 databases whose tables
--  already existed. schema_migrations is created by migrate.py itself.)
--
-- Purpose: persist per-card payment-due metadata that YNAB's API does not expose
-- (dashboard/ynab.py::fetch_credit_cards returns due="" for every card). The
-- Vesper home merges this table over the live YNAB fetch (see dashboard/hub/
-- cards.py::enrich). due_day is a recurring day-of-month, not a fixed date, so the
-- value never goes stale month to month — the display layer computes the next
-- occurrence.

-- +migrate up

CREATE TABLE card (
    name      TEXT PRIMARY KEY,            -- canonical card name; matches the YNAB account name (case-insensitive merge)
    due_day   INTEGER NOT NULL,            -- payment due day-of-month (1-28), recurring monthly
    last4     TEXT,                        -- optional last four digits; NULL when unknown
    wiki_slug TEXT,                        -- cross-format ref (contract rule): rel path minus .md, when a node exists
    created   TEXT NOT NULL DEFAULT (datetime('now')),
    updated   TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (due_day BETWEEN 1 AND 28)       -- cap at 28 so every month has the day; avoids 29-31 edge cases
) STRICT;

-- +migrate down

DROP TABLE card;
