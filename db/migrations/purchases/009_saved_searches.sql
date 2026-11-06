-- 009_saved_searches.sql - saved site searches and the listings already alerted on.
--
-- The sitesearch-alerts job runs each active saved search every 30 minutes and
-- pushes only listings under max_price that are not yet in seen_listings.
-- seeded_at stays null until the first run records the existing listings
-- silently, so a new saved search does not alert on everything already listed.

-- +migrate up

CREATE TABLE saved_searches (
    id        INTEGER PRIMARY KEY,
    query     TEXT NOT NULL,
    sites     TEXT NOT NULL,
    max_price REAL,
    active    INTEGER NOT NULL DEFAULT 1,
    seeded_at TEXT,
    last_run  TEXT,
    created   TEXT NOT NULL
) STRICT;

CREATE TABLE seen_listings (
    search_id  INTEGER NOT NULL REFERENCES saved_searches(id) ON DELETE CASCADE,
    url        TEXT NOT NULL,
    price      REAL,
    first_seen TEXT NOT NULL,
    PRIMARY KEY (search_id, url)
) STRICT;

-- +migrate down

DROP TABLE seen_listings;
DROP TABLE saved_searches;
