-- Canonical task store. Source of truth for the Vesper home TASKS panel,
-- the SCHEDULE panel's checkable items, the work-planner markdown mirror,
-- and wiki/tasks/*.md nodes. Completion propagates across all surfaces.
-- See docs/archive/plans/2026-05-29-unified-task-sync.md.

-- +migrate up
CREATE TABLE tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_key        TEXT NOT NULL,                       -- stable external id (API boundary); internal id never crosses out
    title           TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open',        -- 'open' | 'done'
    section         TEXT NOT NULL DEFAULT 'general',     -- planner section, lowercase
    deferred        INTEGER NOT NULL DEFAULT 0,          -- 0 | 1
    due_date        TEXT,                                -- ISO date, nullable
    completed_date  TEXT,                                -- ISO date, nullable
    description     TEXT NOT NULL DEFAULT '',
    cal_event_id    TEXT,                                -- google calendar event id, nullable
    cal_calendar_id TEXT,                                -- which calendar, nullable (default primary at write time)
    wiki_slug       TEXT,                                -- vault ref: wiki/tasks/<slug>, no [[]] no .md; nullable
    source          TEXT NOT NULL DEFAULT 'manual',      -- manual | calendar | planner-import
    created         TEXT NOT NULL DEFAULT (datetime('now')),
    updated         TEXT NOT NULL DEFAULT (datetime('now'))
) STRICT;

CREATE UNIQUE INDEX idx_tasks_key ON tasks(task_key);
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_due ON tasks(due_date);
CREATE INDEX idx_tasks_cal ON tasks(cal_event_id);

-- +migrate down
DROP TABLE tasks;
