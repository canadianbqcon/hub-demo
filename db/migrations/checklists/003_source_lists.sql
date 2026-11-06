-- Migration 003_source_lists for checklists.db
-- Date: 2026-09-02
--
-- Makes checklists.db the ONE store for every checklist on the Hub, with the other
-- modules as doors onto it rather than owners of their own copies. /recipes already
-- worked that way for the grocery list; /trips did not — it carried a `grocery` table
-- of its own in trips.db, so the same shopping list existed twice with nothing keeping
-- the two in step.
--
-- `source` is the link. It names the module and record a list belongs to
-- ("trips:59:grocery") and is empty for a list that is nobody's but Sam's. It is
-- deliberately NOT in update_checklist's allowlist: it is the identity a module looks
-- its list up by, and an edit would orphan the row exactly the way a category edit
-- orphans the protected grocery list.
--
-- The partial unique index is the same backstop 002 gave the protected row:
-- ensure_source_list() is select-then-insert and that is not atomic across two
-- requests, so the loser of a race must fail rather than create a second list for the
-- same trip.
--
-- `qty` and `note` come across with the trips rows. They are not trip-specific — "how
-- much" and "why" fit any checklist item — and folding them into `text` would have
-- lost the distinction between "Distilled water" and the 2 gallons of it.
--
-- NOTE: checklists/db.py:init() carries a hardcoded CREATE block and nothing runs
-- migrations at boot. Both paths were updated together; tests/test_checklists_bootstrap.py
-- asserts they still agree.

-- +migrate up

ALTER TABLE checklists ADD COLUMN source TEXT DEFAULT '';

ALTER TABLE checklist_items ADD COLUMN qty TEXT DEFAULT '';
ALTER TABLE checklist_items ADD COLUMN note TEXT DEFAULT '';

CREATE UNIQUE INDEX IF NOT EXISTS checklists_one_per_source
ON checklists(source) WHERE source <> '';

-- +migrate down

DROP INDEX IF EXISTS checklists_one_per_source;
-- The columns are left in place. Dropping `source` cannot run while the partial index
-- references it, and dropping qty/note would destroy the detail the trips rows moved in
-- with. Re-running `up` fails loudly on a database that already has the columns, which
-- is correct.
