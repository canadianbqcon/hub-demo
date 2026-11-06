-- +migrate up
-- mail.db -- gitignored (data/mail.db), a local mirror of Gmail written by
-- mail/gmail_sync.py, only on the active machine, so it is never synced.
-- account.provider is 'gmail' today; that column is the whole Outlook slot.
-- message.rfc_message_id / rfc_references are the RFC 5322 headers (reply
-- threading), not Gmail ids. All tables STRICT except the FTS5 virtual table.

CREATE TABLE IF NOT EXISTS account (
    id         INTEGER PRIMARY KEY,
    provider   TEXT NOT NULL DEFAULT 'gmail',
    address    TEXT NOT NULL,
    history_id TEXT,
    synced_at  TEXT,
    scan_gen   INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE TABLE IF NOT EXISTS label (
    account_id INTEGER NOT NULL,
    id         TEXT NOT NULL,
    name       TEXT NOT NULL,
    type       TEXT,
    PRIMARY KEY (account_id, id)
) STRICT;

CREATE TABLE IF NOT EXISTS message (
    account_id       INTEGER NOT NULL,
    id               TEXT NOT NULL,
    thread_id        TEXT NOT NULL,
    internal_date    INTEGER NOT NULL,
    from_addr        TEXT,
    from_name        TEXT,
    to_addrs         TEXT,
    cc_addrs         TEXT,
    reply_to         TEXT,
    subject          TEXT,
    snippet          TEXT,
    body_text        TEXT,
    body_html        TEXT,
    label_ids        TEXT,
    rfc_message_id   TEXT,
    rfc_references   TEXT,
    attachments_json TEXT,
    scan_gen         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (account_id, id)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_message_thread ON message(account_id, thread_id);
CREATE INDEX IF NOT EXISTS idx_message_date ON message(internal_date);

-- External-content FTS5: the index stores no text of its own, rowid maps to
-- message.rowid, and the triggers below keep it in step.
CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(
    subject, from_name, from_addr, body_text,
    content='message', content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS message_ai AFTER INSERT ON message BEGIN
    INSERT INTO message_fts(rowid, subject, from_name, from_addr, body_text)
    VALUES (new.rowid, new.subject, new.from_name, new.from_addr, new.body_text);
END;

CREATE TRIGGER IF NOT EXISTS message_ad AFTER DELETE ON message BEGIN
    INSERT INTO message_fts(message_fts, rowid, subject, from_name, from_addr, body_text)
    VALUES ('delete', old.rowid, old.subject, old.from_name, old.from_addr, old.body_text);
END;

CREATE TRIGGER IF NOT EXISTS message_au AFTER UPDATE ON message BEGIN
    INSERT INTO message_fts(message_fts, rowid, subject, from_name, from_addr, body_text)
    VALUES ('delete', old.rowid, old.subject, old.from_name, old.from_addr, old.body_text);
    INSERT INTO message_fts(rowid, subject, from_name, from_addr, body_text)
    VALUES (new.rowid, new.subject, new.from_name, new.from_addr, new.body_text);
END;

-- source_hash is a hash of the sorted message ids the summary covered, so any
-- arrival or deletion makes it stale.
CREATE TABLE IF NOT EXISTS summary (
    thread_id      TEXT PRIMARY KEY,
    source_hash    TEXT NOT NULL,
    text           TEXT NOT NULL,
    model          TEXT,
    prompt_version TEXT,
    cost_usd       REAL NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL
) STRICT;

-- One row per thread editing session; a second save calls drafts.update on
-- the same gmail_draft_id.
CREATE TABLE IF NOT EXISTS draft_log (
    id             INTEGER PRIMARY KEY,
    thread_id      TEXT NOT NULL,
    gmail_draft_id TEXT,
    model          TEXT,
    cost_usd       REAL NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL
) STRICT;

-- +migrate down
DROP TABLE IF EXISTS draft_log;
DROP TABLE IF EXISTS summary;
DROP TRIGGER IF EXISTS message_au;
DROP TRIGGER IF EXISTS message_ad;
DROP TRIGGER IF EXISTS message_ai;
DROP TABLE IF EXISTS message_fts;
DROP INDEX IF EXISTS idx_message_date;
DROP INDEX IF EXISTS idx_message_thread;
DROP TABLE IF EXISTS message;
DROP TABLE IF EXISTS label;
DROP TABLE IF EXISTS account;
