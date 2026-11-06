-- +migrate up
-- news.db -- tracked, small: sources, topics, digests. Changes only when Sam
-- edits a source/topic or the 06:30 digest lands, so this adds one small blob a
-- day to history, not one per 15-minute poll (that's data/news-cache.db, gitignored,
-- see db/migrations/news-cache/001_init.sql). All tables STRICT.

CREATE TABLE IF NOT EXISTS sources (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    url               TEXT NOT NULL,
    kind              TEXT NOT NULL CHECK (kind IN ('rss', 'sitemap', 'gnews')),
    section           TEXT NOT NULL CHECK (section IN ('economy', 'politics', 'world', 'nyc', 'tech', 'topics')),
    lane              TEXT NOT NULL CHECK (lane IN ('reporting', 'primary', 'opinion', 'audience', 'community')),
    lean              TEXT NOT NULL CHECK (lean IN ('left', 'lean_left', 'center', 'lean_right', 'right', 'primary')),
    factual           TEXT NOT NULL DEFAULT 'unrated',
    owner             TEXT NOT NULL DEFAULT '',
    state_affiliation TEXT,
    paywall           INTEGER NOT NULL DEFAULT 0,
    enabled           INTEGER NOT NULL DEFAULT 1,
    rating_note       TEXT NOT NULL DEFAULT ''
) STRICT;

CREATE TABLE IF NOT EXISTS topics (
    id      INTEGER PRIMARY KEY,
    kind    TEXT NOT NULL CHECK (kind IN ('keyword', 'ticker', 'repo', 'pypi', 'subreddit')),
    query   TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    UNIQUE (kind, query)
) STRICT;

CREATE TABLE IF NOT EXISTS digests (
    date       TEXT PRIMARY KEY,
    markdown   TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
) STRICT;

-- +migrate down
DROP TABLE IF EXISTS digests;
DROP TABLE IF EXISTS topics;
DROP TABLE IF EXISTS sources;
