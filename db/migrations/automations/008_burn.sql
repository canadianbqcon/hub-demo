-- +migrate up
-- burn_run: one row per /burn run, written by <vault>/.claude/skills/burn/record.py at the
-- run's finish and read by the Burn tab on /automations. The run's own files under
-- .claude/.burn/ are deleted after 7 days, so this row is the lasting record. report_json
-- holds the whole report (jobs, chains, tests, dropped, held back, conflicts); the columns
-- beside it are what the tab's row shows without parsing it.
CREATE TABLE burn_run (
    run          TEXT PRIMARY KEY,
    started_at   TEXT NOT NULL,
    ended_at     TEXT,
    status       TEXT NOT NULL,
    five_allow   REAL,
    week_allow   REAL,
    five_start   REAL,
    five_end     REAL,
    week_start   REAL,
    week_end     REAL,
    merged       INTEGER NOT NULL DEFAULT 0,
    failed       INTEGER NOT NULL DEFAULT 0,
    report_json  TEXT NOT NULL,
    recorded_at  TEXT NOT NULL
) STRICT;

-- +migrate down
DROP TABLE IF EXISTS burn_run;
