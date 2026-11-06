-- Migration 003_requests_and_payments for owed.db
-- Generated: 2026-09-02
-- Purpose: close the loop between asking for money and it arriving. Sam,
-- 2026-09-02: "put a button in the O tab where I can request on Zelle or Venmo
-- ... it can rectify my O tab, and it will show that they paid it. It will go
-- into a log of what people have paid me."
--
-- Neither Venmo nor Zelle can be asked for money programmatically — Venmo's
-- developer API was retired in 2016 and Zelle has never had a consumer one — so
-- the request half is a prefilled link he taps. What IS automatable is the other
-- direction: both send a notification email that names the payer, the amount,
-- and the note, and those parse cleanly.
--
-- Three tables:
--
--   person        the Venmo handle per debtor. Needed because a charge link has
--                 to name a recipient; nothing else in the vault stores one.
--
--   payment       one transfer that actually arrived. This is the log he asked
--                 for, and it is a different thing from an owed row marked paid:
--                 money can land before anyone knows which debt it settles, and
--                 one transfer routinely covers several debts at once (Brian has
--                 eight open lines). `ext_id` is the provider's own transaction
--                 id and is UNIQUE, which is the whole idempotency story — the
--                 scanner can re-read the same mailbox forever and insert once.
--
--   payment_line  which debts a payment was applied to. Without it, applying is
--                 a one-way door: the owed rows flip to paid and nothing records
--                 why, so a misapplied payment cannot be undone.
--
-- Nothing here auto-settles on a guess. A payment whose note carries the request
-- tag (#o41, or #o41.42.43 for a whole balance) and whose amount matches is
-- applied by the scanner; everything else lands unapplied and waits for a click.

-- +migrate up

CREATE TABLE person (
    person  TEXT PRIMARY KEY COLLATE NOCASE,   -- joins owed.person, which is free text
    venmo   TEXT,                              -- handle without the leading @
    updated TEXT NOT NULL DEFAULT (datetime('now'))
) STRICT;

CREATE TABLE payment (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    person   TEXT NOT NULL,                    -- as the notification named them
    amount   REAL NOT NULL,
    method   TEXT NOT NULL,                    -- venmo / zelle / cash
    received TEXT NOT NULL,                    -- ISO date the money landed
    note     TEXT NOT NULL DEFAULT '',         -- payment note / Zelle memo, verbatim
    ext_id   TEXT UNIQUE,                      -- provider transaction id; NULL when hand-entered
    msg_id   TEXT,                             -- gmail message id, to get back to the source
    status   TEXT NOT NULL DEFAULT 'unapplied',
    created  TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (status IN ('unapplied', 'applied', 'ignored')),
    CHECK (amount > 0)
) STRICT;

CREATE INDEX payment_open ON payment (status, received);

CREATE TABLE payment_line (
    payment_id INTEGER NOT NULL REFERENCES payment(id) ON DELETE CASCADE,
    owed_id    INTEGER NOT NULL REFERENCES owed(id)    ON DELETE CASCADE,
    amount     REAL NOT NULL,
    PRIMARY KEY (payment_id, owed_id)
) STRICT;

CREATE INDEX payment_line_owed ON payment_line (owed_id);

-- +migrate down

DROP INDEX IF EXISTS payment_line_owed;
DROP TABLE IF EXISTS payment_line;
DROP INDEX IF EXISTS payment_open;
DROP TABLE IF EXISTS payment;
DROP TABLE IF EXISTS person;
