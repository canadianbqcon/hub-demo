-- +migrate up
-- workbench.db: /build creation-mode sign-off ledger. One append-only table:
-- every Approve / Send back / not_applicable / abandoned click on the Hub's
-- Workbench page writes one new row here, never an update or delete. Current
-- verdict for a build/kind = the highest-seq row whose doc_sha256 still
-- matches the file on disk (see workbench/store.py current()).
-- Spec: docs/archive/specs/2026-09-24-build-creation-mode-design.md §3.

CREATE TABLE IF NOT EXISTS decisions (
    id          TEXT PRIMARY KEY,   -- uuid4, so rows merge across machines by key
    seq         INTEGER NOT NULL,   -- 1.. per build_slug, server-assigned
    build_slug  TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('spec', 'design', 'plan')),
    doc_path    TEXT,               -- NULL only for not_applicable/abandoned rows
    doc_sha256  TEXT,               -- file hash, or option-folder manifest hash
    verdict     TEXT NOT NULL CHECK (verdict IN ('approved', 'sent_back', 'not_applicable', 'abandoned')),
    choice      TEXT,               -- picked option letter, design kind only
    comment     TEXT,               -- required by the API layer for sent_back
    snapshot    TEXT,               -- approved text, or the option-folder manifest JSON
    decided_at  TEXT NOT NULL DEFAULT (datetime('now'))
) STRICT;

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

-- +migrate down
DROP TRIGGER IF EXISTS decisions_no_delete;
DROP TRIGGER IF EXISTS decisions_no_update;
DROP INDEX IF EXISTS idx_decisions_build;
DROP TABLE IF EXISTS decisions;
