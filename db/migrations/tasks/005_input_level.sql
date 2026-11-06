-- Input-level triage: how much of Sam a task needs before Claude can finish
-- it. 'none' = zero questions (Claude runs it start to finish), 'low' = up to
-- three questions, 'high' = full back-and-forth. NULL means never triaged, which
-- the panel renders as a hollow pip so a missed triage stays visible instead of
-- silently reading as autonomous.
--
-- Drives the colored pip on each task row (green/yellow/red) and the /tasks skill,
-- which runs the 'none' queue in one pass then optionally sweeps 'low'.
--
-- Non-destructive: existing rows land NULL (untriaged) and are backfilled by the
-- one-time triage pass, not by this migration.

-- +migrate up
ALTER TABLE tasks ADD COLUMN input_level TEXT;  -- 'none' | 'low' | 'high' | NULL

-- +migrate down
ALTER TABLE tasks DROP COLUMN input_level;
