-- +migrate up
-- decisions.kind gains 'mark': the Marks walk page's Close / Send back clicks
-- now land in this ledger (workbench/store.py record_mark). SQLite cannot alter
-- a CHECK, so the table is rebuilt (STRICT preserved, every row copied) -- same
-- pattern as db/migrations/news-cache/002_autoincrement_ids.sql.
--
-- This file carries its own transaction. db/migrate.py runs executescript()
-- non-atomically (see its comment in _apply_pending), so without BEGIN/COMMIT a
-- failure after the DROP TABLE would leave the append-only ledger half rebuilt.
-- SQLite DDL is transactional: a failure inside rolls the whole rebuild back.

BEGIN IMMEDIATE;

DROP TRIGGER IF EXISTS decisions_no_delete;
DROP TRIGGER IF EXISTS decisions_no_update;

CREATE TABLE decisions_new (
    id          TEXT PRIMARY KEY,   -- uuid4, so rows merge across machines by key
    seq         INTEGER NOT NULL,   -- 1.. per build_slug, server-assigned
    build_slug  TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('spec', 'design', 'plan', 'mark')),
    doc_path    TEXT,               -- NULL for not_applicable/abandoned and mark rows
    doc_sha256  TEXT,               -- file hash, or option-folder manifest hash
    verdict     TEXT NOT NULL CHECK (verdict IN ('approved', 'sent_back', 'not_applicable', 'abandoned')),
    choice      TEXT,               -- picked option letter (design), or the mark number (mark)
    comment     TEXT,               -- required by the API layer for sent_back
    snapshot    TEXT,               -- approved text, option-folder manifest JSON, or mark entry JSON
    decided_at  TEXT NOT NULL DEFAULT (datetime('now'))
) STRICT;

INSERT INTO decisions_new (id, seq, build_slug, kind, doc_path, doc_sha256,
                           verdict, choice, comment, snapshot, decided_at)
    SELECT id, seq, build_slug, kind, doc_path, doc_sha256,
           verdict, choice, comment, snapshot, decided_at
    FROM decisions ORDER BY rowid;

DROP TABLE decisions;
ALTER TABLE decisions_new RENAME TO decisions;

CREATE INDEX IF NOT EXISTS idx_decisions_build ON decisions(build_slug, kind, seq DESC);

-- Append-only: no row is ever changed or removed once written.
CREATE TRIGGER IF NOT EXISTS decisions_no_update
BEFORE UPDATE ON decisions
BEGIN
    SELECT RAISE(ABORT, 'decisions is append-only: no UPDATE');
END;

CREATE TRIGGER IF NOT EXISTS decisions_no_delete
BEFORE DELETE ON decisions
BEGIN
    SELECT RAISE(ABORT, 'decisions is append-only: no DELETE');
END;

COMMIT;

-- +migrate down
-- Reversing would mean the same rebuild without 'mark' in the CHECK, which
-- fails once a mark row exists; the ledger is append-only, so there is no
-- reason to ever run it.
