-- +migrate up
-- Structured storage map — revives the "Phase D structured storage browse" that
-- migration 003 cut in favour of the single-row free-text storage_note blob.
-- Sam reversed that 2026-06-20: he wants a real editable UI, not a textarea.
--
-- A four-level tree mirrors the physical layout the markdown blob encoded:
--   area    — a room (Front room, Back room, Freezer, Alcohol room, Notes)
--   unit    — a fixture inside a room (Right fridge, Lowboy, Kitchen table); the
--             collapsible card in the UI
--   section — a shelf/row inside a unit (Top row, Second row, Bottom row)
--   item    — the actual thing stored (Bitter melon, Sorrel, …)
--
-- The blob is irregular: some items sit directly under a room (Alcohol room) or a
-- unit (Left fridge's loose "Sugar cane juice in bag") with no fixture/shelf, and
-- "Notes" is freeform reminders. Those are modelled uniformly with a blank-named
-- ('') passthrough unit/section, which the frontend renders without a sub-header.
-- So the tree stays regular while the page reads exactly like the old map.
--
-- sort_order is explicit at every level because physical order is meaningful
-- (top row sits above bottom row). storage_note (migration 003) is left intact as
-- the seed source + archive; the map view stops reading it once this is seeded.

CREATE TABLE storage_area (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE TABLE storage_unit (
    id         INTEGER PRIMARY KEY,
    area_id    INTEGER NOT NULL REFERENCES storage_area(id) ON DELETE CASCADE,
    name       TEXT NOT NULL DEFAULT '',   -- '' = passthrough (room with loose items, no fixture)
    sort_order INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE TABLE storage_section (
    id         INTEGER PRIMARY KEY,
    unit_id    INTEGER NOT NULL REFERENCES storage_unit(id) ON DELETE CASCADE,
    name       TEXT NOT NULL DEFAULT '',   -- '' = passthrough (unit with loose items, no shelf)
    sort_order INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE TABLE storage_item (
    id         INTEGER PRIMARY KEY,
    section_id INTEGER NOT NULL REFERENCES storage_section(id) ON DELETE CASCADE,
    text       TEXT NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0
) STRICT;

CREATE INDEX idx_storage_unit_area    ON storage_unit(area_id);
CREATE INDEX idx_storage_section_unit ON storage_section(unit_id);
CREATE INDEX idx_storage_item_section ON storage_item(section_id);

-- +migrate down
DROP TABLE storage_item;
DROP TABLE storage_section;
DROP TABLE storage_unit;
DROP TABLE storage_area;
