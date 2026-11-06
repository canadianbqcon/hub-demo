-- Add a `blocked` tier to tasks. A blocked task is waiting on an external gate
-- (e.g. "waiting on their reply") and is distinct from `deferred`, which is an
-- intentional postponement the user chose. Within a planner section the sort
-- order becomes: active -> blocked -> deferred.
--
-- Non-destructive: existing rows default to 0 (not blocked), so no re-seed is
-- needed and the planner round-trip is preserved unchanged.
-- See docs/archive/plans/2026-05-29-unified-task-sync.md.

-- +migrate up
ALTER TABLE tasks ADD COLUMN blocked INTEGER NOT NULL DEFAULT 0;  -- 0 | 1

-- +migrate down
ALTER TABLE tasks DROP COLUMN blocked;
