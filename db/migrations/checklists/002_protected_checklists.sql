-- Migration 002_protected_checklists for checklists.db
-- Date: 2026-08-22
-- Spec: docs/archive/specs/2026-08-22-recipes-hub-module-design.md
--
-- Adds the `protected` flag that makes the canonical grocery list undeletable, so
-- /recipes and /checklists can share one list without either surface being able to
-- break the link.
--
-- Enforcement is in the database, not the API layer: any writer -- a future module, a
-- script, a sqlite3 session -- walks past an app-level check, and this list is meant to
-- survive all of them.
--
-- The identity trigger is not redundant with the delete trigger. ensure_grocery_list()
-- looks the row up by `category='grocery' AND protected=1`; without it, a category edit
-- (allowed by update_checklist's {name, category, description} allowlist) orphans the
-- canonical row and the next read silently creates a SECOND grocery list. De-protection
-- would likewise re-open the delete path.
--
-- NOTE: checklists/db.py:init() carries a hardcoded CREATE TABLE IF NOT EXISTS block and
-- nothing runs migrations at boot (app.py calls init() directly). init() has been updated
-- to build this same schema for a fresh database. The two paths must stay in agreement;
-- tests/test_checklists_bootstrap.py asserts they do.

-- +migrate up

ALTER TABLE checklists ADD COLUMN protected INTEGER NOT NULL DEFAULT 0;

CREATE TRIGGER IF NOT EXISTS checklists_protect_delete
BEFORE DELETE ON checklists
FOR EACH ROW WHEN OLD.protected = 1
BEGIN
    SELECT RAISE(ABORT, 'checklist is protected and cannot be deleted');
END;

CREATE TRIGGER IF NOT EXISTS checklists_protect_identity
BEFORE UPDATE ON checklists
FOR EACH ROW
WHEN OLD.protected = 1 AND (NEW.protected <> 1 OR NEW.category <> OLD.category)
BEGIN
    SELECT RAISE(ABORT, 'protected checklist identity is immutable');
END;

-- Backstop for the ensure race: select-then-insert is not atomic across two tabs.
CREATE UNIQUE INDEX IF NOT EXISTS checklists_one_protected_per_category
ON checklists(category) WHERE protected = 1;

-- +migrate down

DROP INDEX IF EXISTS checklists_one_protected_per_category;
DROP TRIGGER IF EXISTS checklists_protect_identity;
DROP TRIGGER IF EXISTS checklists_protect_delete;
-- The column is left in place. Dropping it would destroy the protection flag on a row
-- that the up-migration may have created, and SQLite's DROP COLUMN cannot run while the
-- partial index references it. Re-running `up` is idempotent for the triggers and index;
-- the ALTER will fail loudly on a database that already has the column, which is correct.
