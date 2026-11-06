-- Migration 001_initial for owed.db
-- Generated: 2026-08-28
-- Onboarded via wiki/decisions/onboard-owed.md
--
-- Fresh-DB migration (the database does not exist yet):
--     python db/migrate.py up owed
--
-- Purpose: back the `owed` tab on /finances — money other people owe Sam.
-- Source of truth before this was personal/money-owed-to-me.md, a hand-kept
-- markdown file that went stale between edits and could not be marked paid
-- anywhere he actually looks.
--
-- One flat table on purpose. Every shape in the markdown (a solo IOU, a trip
-- split, a group front where five people each owe the same slice, and the
-- unassigned bucket) is one row per person per debt; grouping is a GROUP BY,
-- not a parent table.

-- +migrate up

CREATE TABLE owed (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    person   TEXT NOT NULL,                        -- who owes; free text, matched case-insensitively on read
    what     TEXT NOT NULL,                        -- the expense, in his words
    amount   REAL NOT NULL,                        -- what THEY owe, not what he paid
    incurred TEXT,                                 -- ISO date the expense happened; NULL when unknown
    paid_out REAL,                                 -- what he actually laid out, when the debt is a share of it
    status   TEXT NOT NULL DEFAULT 'open',
    settled  TEXT,                                 -- ISO date they paid it back
    method   TEXT,                                 -- venmo / zelle / cash — how it came back
    grp      TEXT,                                 -- group front label ("Zedd In The Park"); NULL for solo debts
    note     TEXT NOT NULL DEFAULT '',
    created  TEXT NOT NULL DEFAULT (datetime('now')),
    updated  TEXT NOT NULL DEFAULT (datetime('now')),
    -- 'unassigned' is the markdown's "ambiguous / not yet assigned" bucket: a real
    -- expense with no confirmed debtor. It is kept as a status rather than dropped,
    -- because deleting it is how those got forgotten the first time.
    CHECK (status IN ('open', 'requested', 'paid', 'unassigned')),
    CHECK (amount >= 0)
    -- No "paid implies a settled date" check: two real repayments in the markdown
    -- record (Tiffany's Mount Snow ticket) are confirmed paid with no date anyone
    -- kept. A constraint that would have forced a date to be invented is worse
    -- than a NULL that says nobody knows.
) STRICT;

CREATE INDEX idx_owed_person ON owed(person);
CREATE INDEX idx_owed_status ON owed(status);

-- +migrate down

DROP TABLE owed;
