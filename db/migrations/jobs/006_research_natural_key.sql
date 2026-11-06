-- Migration 006_research_natural_key for jobs.db
-- Generated: 2026-07-24
--
-- Purpose:
--   Make (application_id, category, subcategory) the enforced natural key on
--   company_research so a second Stage 2 run cannot duplicate the 39-row set.
--
--   Two Claude sessions researching the same application both POST one research
--   row per subcategory; nothing stopped the second set landing alongside the
--   first (app #113, 2026-07-15). The UI already treats the triple as unique --
--   its research editors look the row up by subcategory and PATCH it if found
--   (jobs.js) -- so the index just makes the write path agree with the readers.
--   db.create_research becomes an upsert against this index.
--
--   Dedup keeps the highest id per group (the most recent write wins, matching
--   the upsert's DO UPDATE semantics).
--
-- ⚠ PRE-MIGRATION BACKUP REQUIRED
--   `python db/migrate.py up jobs` takes it automatically; after this applies
--   cleanly, at most one jobs.db.bak-pre-migration-* survives per the
--   warehouse-contract retention invariant.

-- +migrate up

DELETE FROM company_research
WHERE id NOT IN (
    SELECT MAX(id) FROM company_research
    GROUP BY application_id, category, subcategory
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_company_research_natural_key
    ON company_research (application_id, category, subcategory);

-- +migrate down

DROP INDEX IF EXISTS idx_company_research_natural_key;
