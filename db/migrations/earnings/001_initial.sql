-- vault-code/db/migrations/earnings/001_initial.sql
-- +migrate up
CREATE TABLE earnings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT NOT NULL,                       -- e.g. 'juniper-and-co'
    source_type   TEXT NOT NULL,                       -- tipped_hourly | salaried | venture | investment
    period_start  TEXT NOT NULL,                       -- ISO date
    period_end    TEXT NOT NULL,                       -- ISO date
    granularity   TEXT NOT NULL DEFAULT 'pay_period',  -- pay_period | annual | event
    gross         REAL,
    net           REAL,                                -- received / check amount, verbatim from stub
    hours         REAL,
    wages         REAL,
    cash_tips     REAL,
    cc_tips_gross REAL,
    cc_tips_net   REAL,                                -- after processing fee, verbatim from stub
    tax_withheld  REAL,                                -- total withheld per payroll stub
    source_doc    TEXT,                                -- path to preserved stub image
    notes         TEXT NOT NULL DEFAULT '',
    created       TEXT NOT NULL DEFAULT (datetime('now')),
    updated       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (source, period_start, period_end)
) STRICT;

CREATE TABLE earnings_shifts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    earnings_id   INTEGER NOT NULL REFERENCES earnings(id) ON DELETE CASCADE,
    shift_date    TEXT NOT NULL,                       -- ISO date
    clock_in      TEXT,                                -- ISO-8601 with UTC offset
    clock_out     TEXT,                                -- ISO-8601 with UTC offset
    hours         REAL,
    rate          REAL,
    tipped        INTEGER NOT NULL DEFAULT 0,          -- 0/1
    wage_pay      REAL,
    cash_tips     REAL,
    cc_tips_gross REAL,
    cc_tips_net   REAL,
    shift_total   REAL
) STRICT;

CREATE INDEX idx_earnings_shifts_parent ON earnings_shifts(earnings_id);

CREATE TABLE earnings_deductions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    earnings_id INTEGER NOT NULL REFERENCES earnings(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,   -- e.g. 'FICA-SS', 'FIT', 'New York SIT'
    amount      REAL,            -- this pay period, verbatim from stub
    ytd_amount  REAL             -- year-to-date, verbatim from stub
) STRICT;

CREATE INDEX idx_earnings_deductions_parent ON earnings_deductions(earnings_id);

-- +migrate down
DROP INDEX IF EXISTS idx_earnings_deductions_parent;
DROP TABLE IF EXISTS earnings_deductions;
DROP INDEX IF EXISTS idx_earnings_shifts_parent;
DROP TABLE IF EXISTS earnings_shifts;
DROP TABLE IF EXISTS earnings;
