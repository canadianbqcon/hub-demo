-- +migrate up
-- Nested sections — a shelf can now hold sub-shelves, to any depth.
--
-- Migration 015 built a fixed four-level tree (area → unit → section → item).
-- That is one level short of the physical reality of the upstairs lowboy, which
-- Sam describes as AREA > APPLIANCE > SECTION > SUBSECTION:
--
--   Upstairs (area) > Lowboy (unit) > Fridge 1 (section) > Bottom (subsection)
--                   > Syrups (subsection) > [items]
--
-- Rather than bolt on two more tables — each with its own CRUD, reorder scoping
-- and render pass — storage_section gains a self-referencing parent_id. A NULL
-- parent means the section hangs directly off its unit, which is exactly what
-- every existing row does, so nothing about the current tree changes. Depth is
-- then unbounded and costs one column.
--
-- unit_id stays populated on every row, nested or not: it is what scopes a whole
-- branch to its fixture without walking the chain, and it keeps the existing
-- queries and the ON DELETE CASCADE from the unit working unchanged.

ALTER TABLE storage_section
  ADD COLUMN parent_id INTEGER REFERENCES storage_section(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_storage_section_parent ON storage_section(parent_id);

-- +migrate down
-- Flatten first: any nested section is re-hung directly off its unit, so no row
-- is orphaned when the column goes. Sibling order within a unit is not preserved
-- (the flattened children land wherever their sort_order falls among the former
-- top-level sections) — this is a schema rollback, not a layout rollback.

UPDATE storage_section SET parent_id = NULL WHERE parent_id IS NOT NULL;

DROP INDEX IF EXISTS idx_storage_section_parent;

ALTER TABLE storage_section DROP COLUMN parent_id;
