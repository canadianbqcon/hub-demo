-- +migrate up
CREATE TABLE ingredient_location (
    name     TEXT PRIMARY KEY,   -- lowercased ingredient or recipe name
    location TEXT NOT NULL,      -- human path e.g. "Right fridge · second row"
    note     TEXT
) STRICT;

-- +migrate down
DROP TABLE ingredient_location;
