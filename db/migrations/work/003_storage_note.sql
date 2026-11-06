-- +migrate up
-- Phase A2 of the batch-prep dashboard (design doc:
-- docs/archive/specs/2026-06-05-jc-batch-prep-dashboard-design.md).
--
-- PIVOT 2026-06-05: Sam chose a *textual* storage map over the structured
-- tree. The original 003 (storage_location self-ref tree + stock_item +
-- recipes.location_id) was applied then rolled back unseeded; this replaces it
-- with a single editable text block. The Map tab is a textarea — type the
-- layout, save over the tailnet. No per-recipe location links, so prep-day
-- steps carry no location annotations (accepted trade-off).
--
-- Single-row table (id is pinned to 1 by the app's upsert). `body` is free-form
-- markdown/plain text; `updated` stamps the last edit.

CREATE TABLE storage_note (
    id      INTEGER PRIMARY KEY,
    body    TEXT NOT NULL DEFAULT '',
    updated TEXT NOT NULL DEFAULT (datetime('now'))
) STRICT;

-- +migrate down
DROP TABLE storage_note;
