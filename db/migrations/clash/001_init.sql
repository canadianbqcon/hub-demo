-- +migrate up
-- clash.db: Clash of Clans village tracker for the /clash Hub module.
-- All times are UTC ISO strings. Every child table cascades from account(tag).

CREATE TABLE IF NOT EXISTS account (
    tag            TEXT PRIMARY KEY,
    name           TEXT NOT NULL DEFAULT '',
    th_level       INTEGER NOT NULL DEFAULT 1,
    clan_tag       TEXT NOT NULL DEFAULT '',
    builders       INTEGER NOT NULL DEFAULT 5,
    last_export_ts TEXT,
    updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
) STRICT;

CREATE TABLE IF NOT EXISTS structure (
    tag         TEXT NOT NULL REFERENCES account(tag) ON DELETE CASCADE,
    data_id     INTEGER NOT NULL,
    level       INTEGER NOT NULL,
    cnt         INTEGER NOT NULL CHECK (cnt > 0),
    observed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    predicted   INTEGER NOT NULL DEFAULT 0 CHECK (predicted IN (0, 1)),
    PRIMARY KEY (tag, data_id, level)
) STRICT;

CREATE TABLE IF NOT EXISTS upgrade (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tag         TEXT NOT NULL REFERENCES account(tag) ON DELETE CASCADE,
    data_id     INTEGER NOT NULL,
    from_level  INTEGER NOT NULL,
    facility    TEXT NOT NULL CHECK (facility IN ('builder', 'lab', 'pet_house')),
    finishes_at TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'tap' CHECK (source IN ('export', 'tap')),
    UNIQUE (tag, data_id, from_level, finishes_at)
) STRICT;

CREATE TABLE IF NOT EXISTS import_run (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tag          TEXT NOT NULL REFERENCES account(tag) ON DELETE CASCADE,
    pasted_at    TEXT NOT NULL,
    export_ts    TEXT,
    added        INTEGER NOT NULL DEFAULT 0,
    changed      INTEGER NOT NULL DEFAULT 0,
    kept_unknown INTEGER NOT NULL DEFAULT 0,
    skipped_json TEXT NOT NULL DEFAULT '[]',
    data_version TEXT NOT NULL DEFAULT ''
) STRICT;

CREATE TABLE IF NOT EXISTS layout (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tag        TEXT NOT NULL REFERENCES account(tag) ON DELETE CASCADE,
    th_level   INTEGER NOT NULL,
    link       TEXT NOT NULL DEFAULT '',
    image_file TEXT NOT NULL DEFAULT '',
    notes      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
) STRICT;

CREATE TABLE IF NOT EXISTS war_plan (
    war_key      TEXT NOT NULL,
    attacker_tag TEXT NOT NULL REFERENCES account(tag) ON DELETE CASCADE,
    target_tag   TEXT NOT NULL,
    target_pos   INTEGER,
    note         TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (war_key, attacker_tag)
) STRICT;

CREATE TABLE IF NOT EXISTS api_cache (
    path            TEXT PRIMARY KEY,
    ok_body         TEXT,
    ok_at           TEXT,
    last_attempt_at TEXT,
    last_status     INTEGER,
    last_error      TEXT
) STRICT;

-- +migrate down
DROP TABLE IF EXISTS api_cache;
DROP TABLE IF EXISTS war_plan;
DROP TABLE IF EXISTS layout;
DROP TABLE IF EXISTS import_run;
DROP TABLE IF EXISTS upgrade;
DROP TABLE IF EXISTS structure;
DROP TABLE IF EXISTS account;
