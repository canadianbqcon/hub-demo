-- Rework the task model: drop the `deferred` tier, add task grouping, add an
-- urgency triage chip.
--
-- 1. Drop `deferred`. The intentional-postponement tier is retired — the ~10 rows
--    that carried the flag simply become ordinary active tasks. `blocked` stays.
-- 2. Add `group_label` (nullable TEXT). Tasks that share a label render as a
--    visual cluster under a group sub-header inside their section, so multi-part
--    work spun off from one parent stays visibly together. NULL = ungrouped.
-- 3. Add `urgency` (nullable TEXT, 'critical' | 'quickwin'). A single-chip triage
--    signal: `critical` = must-do, `quickwin` = high value-to-effort. Mostly set by
--    auto-add processes, assignable to any task. NULL = no chip.
--
-- Non-destructive for the new columns (existing rows default NULL). DROP COLUMN is
-- supported on STRICT tables in SQLite >= 3.35.
-- See docs/archive/plans/2026-05-29-unified-task-sync.md and the /todo skill.

-- +migrate up
ALTER TABLE tasks DROP COLUMN deferred;
ALTER TABLE tasks ADD COLUMN group_label TEXT;            -- cluster label, nullable
ALTER TABLE tasks ADD COLUMN urgency     TEXT;            -- 'critical' | 'quickwin' | NULL

-- +migrate down
ALTER TABLE tasks DROP COLUMN urgency;
ALTER TABLE tasks DROP COLUMN group_label;
ALTER TABLE tasks ADD COLUMN deferred INTEGER NOT NULL DEFAULT 0;  -- 0 | 1
