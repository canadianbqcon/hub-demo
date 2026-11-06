-- Migration 003_listener for music.db
-- Generated: 2026-10-27
-- Design: docs/specs/2026-10-27-song-listener-design.md (vault), section 5
--
-- The song listener's storage. `readings` is append-only: one row per attempt to
-- measure a song (ok or failed), tagged with the pipeline_id of the code and
-- models that made it, so a changed pipeline never overwrites older readings.
-- `fingerprints` holds the sound vector per song and pipeline. `blind_tests`
-- records each held-out accuracy run that gates the `check` command.

-- +migrate up

CREATE TABLE readings (
    id            INTEGER PRIMARY KEY,
    uri           TEXT NOT NULL REFERENCES tracks(uri),
    pipeline_id   TEXT NOT NULL,
    measured_at   TEXT NOT NULL,
    status        TEXT NOT NULL,
    reason        TEXT,                              -- why identity or measuring failed
    video_id      TEXT,                              -- the audio source that was matched
    acoustid_score REAL,
    recording_id  TEXT,                              -- MusicBrainz recording the audio resolved to
    isrc_match    INTEGER,                           -- 1 when that recording carries the track's ISRC
    audio_hash    TEXT,
    duration_s    REAL,
    intervals     TEXT,                              -- JSON: tempo intervals
    main_bpm      REAL,
    tempo_change  INTEGER,
    drops         TEXT,                              -- JSON
    votes         TEXT,                              -- JSON: BPM per source
    consensus_bpm REAL,
    agreement     TEXT,
    neighbours    TEXT,                              -- JSON: nearest settled songs and list vote
    CHECK (status IN ('ok', 'identity_failed', 'measure_failed'))
) STRICT;

CREATE INDEX idx_readings_uri ON readings(uri, pipeline_id);

CREATE TABLE fingerprints (
    uri         TEXT NOT NULL REFERENCES tracks(uri),
    pipeline_id TEXT NOT NULL,
    vector      BLOB,
    dims        INTEGER,
    measured_at TEXT NOT NULL,
    PRIMARY KEY (uri, pipeline_id, measured_at)
) STRICT;

CREATE TABLE blind_tests (
    id               INTEGER PRIMARY KEY,
    run_at           TEXT NOT NULL,
    pipeline_id      TEXT NOT NULL,
    seed             INTEGER,
    sample           TEXT,                           -- JSON: uris tested
    predictions      TEXT,                           -- JSON: per song
    identity_ok      INTEGER,
    measured_hits    INTEGER,
    consensus_hits   INTEGER,
    list_hits        INTEGER,
    baseline_hits    INTEGER,                        -- the majority-list baseline
    n                INTEGER,
    passed           INTEGER
) STRICT;

-- +migrate down

DROP TABLE blind_tests;
DROP TABLE fingerprints;
DROP INDEX idx_readings_uri;
DROP TABLE readings;
