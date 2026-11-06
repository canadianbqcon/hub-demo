-- Migration 001_initial for book.db
-- Fresh-DB migration:  python db/migrate.py up book
--
-- Local ledger (YNAB replacement fed by SimpleFIN). Money is INTEGER cents,
-- outflow negative. txn.uid is the identity APIs and URLs use ('ynab:<id>',
-- 'sf:<id>'); integer ids are machine-local and db-merge.py matches by the
-- natural keys in db/merge-keys.json.

-- +migrate up

CREATE TABLE account (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    type          TEXT NOT NULL CHECK (type IN ('checking', 'credit', 'savings')),
    simplefin_id  TEXT UNIQUE,
    ynab_id       TEXT UNIQUE,
    balance_sign  INTEGER NOT NULL DEFAULT 1 CHECK (balance_sign IN (1, -1)),
    balance_cents INTEGER,
    balance_at    TEXT,
    closed        INTEGER NOT NULL DEFAULT 0,
    sync_from     TEXT
) STRICT;

CREATE TABLE category_group (
    id       INTEGER PRIMARY KEY,
    name     TEXT NOT NULL UNIQUE,
    ynab_id  TEXT,
    hidden   INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE TABLE category (
    id        INTEGER PRIMARY KEY,
    group_id  INTEGER NOT NULL REFERENCES category_group(id),
    name      TEXT NOT NULL,
    ynab_id   TEXT,
    hidden    INTEGER NOT NULL DEFAULT 0,
    UNIQUE (group_id, name)
) STRICT;

CREATE TABLE payee (
    id                  INTEGER PRIMARY KEY,
    name                TEXT NOT NULL UNIQUE,
    ynab_id             TEXT,
    transfer_account_id INTEGER REFERENCES account(id)
) STRICT;

-- learned mapping: raw bank description to clean payee
CREATE TABLE payee_alias (
    raw       TEXT PRIMARY KEY,
    payee_id  INTEGER NOT NULL REFERENCES payee(id)
) STRICT;

CREATE TABLE txn (
    id                  INTEGER PRIMARY KEY,
    uid                 TEXT NOT NULL UNIQUE,
    simplefin_id        TEXT UNIQUE,
    ynab_id             TEXT UNIQUE,
    account_id          INTEGER NOT NULL REFERENCES account(id),
    date                TEXT NOT NULL,
    amount_cents        INTEGER NOT NULL,
    payee_id            INTEGER REFERENCES payee(id),
    raw_description     TEXT NOT NULL DEFAULT '',
    category_id         INTEGER REFERENCES category(id),
    memo                TEXT NOT NULL DEFAULT '',
    approved            INTEGER NOT NULL DEFAULT 0,
    cleared             INTEGER NOT NULL DEFAULT 0,
    pending             INTEGER NOT NULL DEFAULT 0,
    transfer_account_id INTEGER REFERENCES account(id),
    transfer_txn_uid    TEXT,
    deleted             INTEGER NOT NULL DEFAULT 0,
    source              TEXT NOT NULL CHECK (source IN ('ynab', 'simplefin')),
    updated_at          TEXT
) STRICT;

CREATE INDEX idx_txn_account_date ON txn(account_id, date);
CREATE INDEX idx_txn_date ON txn(date);

CREATE TABLE split (
    id            INTEGER PRIMARY KEY,
    txn_id        INTEGER NOT NULL REFERENCES txn(id) ON DELETE CASCADE,
    ord           INTEGER NOT NULL,
    amount_cents  INTEGER NOT NULL,
    category_id   INTEGER REFERENCES category(id),
    memo          TEXT NOT NULL DEFAULT '',
    payee_id      INTEGER REFERENCES payee(id),
    UNIQUE (txn_id, ord)
) STRICT;

CREATE TABLE sync_run (
    id          INTEGER PRIMARY KEY,
    at          TEXT NOT NULL,
    status      TEXT NOT NULL,
    added       INTEGER NOT NULL DEFAULT 0,
    updated     INTEGER NOT NULL DEFAULT 0,
    superseded  INTEGER NOT NULL DEFAULT 0,
    errors      TEXT NOT NULL DEFAULT '[]'
) STRICT;

-- +migrate down

DROP TABLE sync_run;
DROP TABLE split;
DROP TABLE txn;
DROP TABLE payee_alias;
DROP TABLE payee;
DROP TABLE category;
DROP TABLE category_group;
DROP TABLE account;
