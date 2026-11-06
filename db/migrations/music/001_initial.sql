-- Migration 001_initial for music.db
-- Generated: 2026-09-28
-- Onboarded via wiki/decisions/onboard-music.md
-- Design: docs/specs/2026-09-28-music-library-db-design.md (vault)
--
-- Fresh-DB migration:
--     python db/migrate.py up music
--
-- Sam's Spotify playlists, what is in each, and a running change log.
-- History is the append-only `changes` table, not SCD Type 2 (the warehouse
-- contract keeps SCD2 for job status only): `playlist_tracks` is the current
-- membership and every refresh writes the added/removed rows that got it there.

-- +migrate up

CREATE TABLE tracks (
    uri              TEXT PRIMARY KEY,               -- spotify:track:... or spotify:local:...
    isrc             TEXT,
    name             TEXT NOT NULL,
    album            TEXT,
    artists          TEXT,                           -- ';'-joined, as Exportify writes them
    release_date     TEXT,
    duration_ms      INTEGER,
    explicit         INTEGER,
    is_local         INTEGER NOT NULL DEFAULT 0,
    -- Audio features come from the 2026-09-28 export only. Spotify returns 403
    -- for this app on /audio-features, so songs first seen by the pull stay NULL.
    danceability     REAL,
    energy           REAL,
    key              INTEGER,
    loudness         REAL,
    mode             INTEGER,
    speechiness      REAL,
    acousticness     REAL,
    instrumentalness REAL,
    liveness         REAL,
    valence          REAL,
    tempo            REAL,
    time_signature   INTEGER,
    first_seen       TEXT NOT NULL DEFAULT (datetime('now')),
    updated          TEXT NOT NULL DEFAULT (datetime('now'))
) STRICT;

CREATE TABLE playlists (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,                       -- Spotify name when known, else the file stem
    file_name   TEXT,                                -- export CSV name; NULL for lists first seen by the pull
    grp         TEXT,                                -- root / New Genres / Old Genres / Temp Genres / playlists; NULL = ungrouped
    spotify_id  TEXT UNIQUE,                         -- 'liked' for Liked Songs
    status      TEXT NOT NULL DEFAULT 'active',
    first_seen  TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen   TEXT,
    updated     TEXT NOT NULL DEFAULT (datetime('now')),
    -- unlinked: an export file the pull could not tie to a Spotify playlist, so
    -- its contents are frozen at export time. ignored: dropped by Sam, never re-added.
    CHECK (status IN ('active', 'unlinked', 'gone', 'ignored'))
) STRICT;

CREATE TABLE playlist_tracks (
    playlist_id INTEGER NOT NULL REFERENCES playlists(id),
    track_uri   TEXT NOT NULL REFERENCES tracks(uri),
    PRIMARY KEY (playlist_id, track_uri)
) STRICT;

CREATE INDEX idx_playlist_tracks_uri ON playlist_tracks(track_uri);

CREATE TABLE refreshes (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    taken_at TEXT NOT NULL DEFAULT (datetime('now')),
    source   TEXT NOT NULL,
    summary  TEXT NOT NULL DEFAULT '',
    CHECK (source IN ('export', 'pull'))
) STRICT;

CREATE TABLE changes (
    refresh_id  INTEGER NOT NULL REFERENCES refreshes(id),
    playlist_id INTEGER NOT NULL REFERENCES playlists(id),
    track_uri   TEXT NOT NULL REFERENCES tracks(uri),
    kind        TEXT NOT NULL,
    CHECK (kind IN ('added', 'removed'))
) STRICT;

CREATE INDEX idx_changes_refresh ON changes(refresh_id);
CREATE INDEX idx_changes_track ON changes(track_uri);

-- +migrate down

DROP TABLE changes;
DROP TABLE refreshes;
DROP TABLE playlist_tracks;
DROP TABLE playlists;
DROP TABLE tracks;
