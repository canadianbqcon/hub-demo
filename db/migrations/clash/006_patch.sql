-- +migrate up
-- Patch page store: Supercell blog posts, their classified balance changes and notes, and Reddit leak posts.
CREATE TABLE blog_post (
    slug            TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    posted_on       TEXT NOT NULL,
    url             TEXT NOT NULL,
    kind            TEXT CHECK (kind IN ('balance', 'update', 'other')),
    classify_state  TEXT NOT NULL DEFAULT 'pending' CHECK (classify_state IN ('pending', 'done', 'failed')),
    classify_tries  INTEGER NOT NULL DEFAULT 0,
    fetched_at      TEXT NOT NULL,
    banner_url      TEXT
) STRICT;

CREATE TABLE patch_change (
    slug     TEXT NOT NULL REFERENCES blog_post(slug) ON DELETE CASCADE,
    pos      INTEGER NOT NULL,
    subject  TEXT NOT NULL,
    text     TEXT NOT NULL,
    effect   TEXT NOT NULL CHECK (effect IN ('buff', 'nerf', 'neutral')),
    section  TEXT NOT NULL CHECK (section IN ('Heroes', 'Troops', 'Equipment', 'Defenses', 'Fixes')),
    unit     TEXT NOT NULL,
    of_name  TEXT,
    PRIMARY KEY (slug, pos)
) STRICT;

CREATE TABLE patch_note (
    slug  TEXT NOT NULL REFERENCES blog_post(slug) ON DELETE CASCADE,
    pos   INTEGER NOT NULL,
    role  TEXT NOT NULL CHECK (role IN ('intro', 'reason', 'watching')),
    unit  TEXT,
    text  TEXT NOT NULL,
    PRIMARY KEY (slug, pos)
) STRICT;

CREATE TABLE leak_post (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    credit      TEXT,
    author      TEXT,
    score       INTEGER,
    comments    INTEGER,
    posted_at   TEXT NOT NULL,
    url         TEXT NOT NULL,
    image_url   TEXT,
    fetched_at  TEXT NOT NULL
) STRICT;
CREATE INDEX leak_post_posted_at ON leak_post (posted_at);

CREATE TABLE patch_fetch (
    source         TEXT PRIMARY KEY CHECK (source IN ('blog', 'leaks', 'classify')),
    ok_at          TEXT,
    last_error     TEXT,
    backfill_page  INTEGER
) STRICT;

-- +migrate down
DROP TABLE IF EXISTS patch_fetch;
DROP TABLE IF EXISTS leak_post;
DROP TABLE IF EXISTS patch_note;
DROP TABLE IF EXISTS patch_change;
DROP TABLE IF EXISTS blog_post;
