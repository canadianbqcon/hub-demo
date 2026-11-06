-- +migrate up

CREATE TABLE areas (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    slug             TEXT NOT NULL UNIQUE,
    level            TEXT NOT NULL,            -- 'city' | 'borough' | 'neighborhood'
    name             TEXT NOT NULL,
    city             TEXT NOT NULL,
    borough          TEXT,
    country          TEXT NOT NULL,
    lat              REAL,
    lng              REAL,
    scene            TEXT NOT NULL DEFAULT '',
    scene_researched TEXT,
    created          TEXT NOT NULL DEFAULT (datetime('now')),
    updated          TEXT NOT NULL DEFAULT (datetime('now'))
) STRICT;

CREATE TABLE places (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    slug                 TEXT NOT NULL UNIQUE,
    name                 TEXT NOT NULL,
    address              TEXT NOT NULL DEFAULT '',
    neighborhood         TEXT NOT NULL DEFAULT '',
    borough              TEXT,
    city                 TEXT NOT NULL,
    country              TEXT NOT NULL DEFAULT '',
    lat                  REAL,
    lng                  REAL,
    cuisine_broad        TEXT NOT NULL,
    cuisine_specific     TEXT NOT NULL,
    cuisines_extra       TEXT NOT NULL DEFAULT '[]',
    depth_score          REAL,
    depth_confidence     TEXT NOT NULL DEFAULT 'none',
    execution_score      REAL,
    execution_confidence TEXT NOT NULL DEFAULT 'none',
    discovery            TEXT NOT NULL,
    summary              TEXT NOT NULL DEFAULT '',
    pros                 TEXT NOT NULL DEFAULT '[]',
    cons                 TEXT NOT NULL DEFAULT '[]',
    order_this           TEXT NOT NULL DEFAULT '[]',
    price_band           TEXT,
    practical            TEXT NOT NULL DEFAULT '{}',
    practical_checked    TEXT,
    status               TEXT NOT NULL DEFAULT 'open',
    researched           TEXT NOT NULL,
    created              TEXT NOT NULL DEFAULT (datetime('now')),
    updated              TEXT NOT NULL DEFAULT (datetime('now'))
) STRICT;

CREATE INDEX idx_places_city ON places(city, cuisine_broad);
CREATE INDEX idx_places_hood ON places(neighborhood, cuisine_broad);

CREATE TABLE evidence (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    place_id      INTEGER NOT NULL REFERENCES places(id) ON DELETE CASCADE,
    source        TEXT NOT NULL,
    url           TEXT NOT NULL,
    author        TEXT NOT NULL DEFAULT '',
    dated         TEXT,
    quote         TEXT NOT NULL,
    cohort        TEXT NOT NULL,             -- 'literate' | 'general' | 'unknown'
    cohort_reason TEXT NOT NULL DEFAULT '',
    polarity      TEXT NOT NULL,             -- 'positive' | 'negative' | 'mixed'
    axis          TEXT NOT NULL,             -- 'depth' | 'execution' | 'practical'
    collected     TEXT NOT NULL DEFAULT (datetime('now'))
) STRICT;

CREATE INDEX idx_evidence_place ON evidence(place_id, cohort);

CREATE TABLE runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    area_slug        TEXT NOT NULL,
    cuisines         TEXT NOT NULL DEFAULT '[]',
    started          TEXT NOT NULL,
    finished         TEXT,
    candidates_found INTEGER NOT NULL DEFAULT 0,
    places_written   INTEGER NOT NULL DEFAULT 0,
    sources_worked   TEXT NOT NULL DEFAULT '{}',
    notes            TEXT NOT NULL DEFAULT ''
) STRICT;

-- +migrate down

DROP TABLE runs;
DROP TABLE evidence;
DROP TABLE places;
DROP TABLE areas;
