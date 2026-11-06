-- Migration 004_facts for music.db
-- Generated: 2026-11-03
-- Design: docs/specs/2026-11-02-song-fact-sheet-design.md (vault), section "Orchestration and storage"
--
-- The song fact sheet's storage. `fact_sheets` is append-only: one row per
-- attempt to describe a song (ok or failed), tagged with the facts_version of
-- the code that made it. `fact_sections` holds one row per section of an ok
-- sheet, one column per fact; slot columns are JSON objects keyed by slot label.
-- `fact_checks` records the ear check's result per fact and version.
-- Nullable facts (meter, slots, per-bar, per-beat, swing, wobble, sub_share,
-- bpm, key) are NULL when the song gives no evidence for them.

-- +migrate up

CREATE TABLE fact_sheets (
    id               INTEGER PRIMARY KEY,
    uri              TEXT NOT NULL REFERENCES tracks(uri),
    facts_version    TEXT NOT NULL,
    measured_at      TEXT NOT NULL,
    status           TEXT NOT NULL,
    reason           TEXT,                           -- why identity or measuring failed
    video_id         TEXT,
    recording_id     TEXT,
    acoustid_score   REAL,
    audio_hash       TEXT,
    duration_s       REAL,
    song_key         TEXT,
    song_mode        TEXT,
    song_key_strength REAL,
    thresholds       TEXT,                           -- JSON: every threshold constant used
    CHECK (status IN ('ok', 'identity_failed', 'measure_failed'))
) STRICT;

CREATE INDEX idx_fact_sheets_uri ON fact_sheets(uri, facts_version);

CREATE TABLE fact_sections (
    sheet_id         INTEGER NOT NULL REFERENCES fact_sheets(id) ON DELETE CASCADE,
    idx              INTEGER NOT NULL,
    start_s          REAL NOT NULL,
    end_s            REAL NOT NULL,
    beat_ok          INTEGER NOT NULL CHECK (beat_ok IN (0, 1)),
    drums_quiet      INTEGER NOT NULL CHECK (drums_quiet IN (0, 1)),
    bpm              REAL,
    bpm_unsure       INTEGER CHECK (bpm_unsure IN (0, 1)),
    tempo_moves      INTEGER,
    beats_per_bar    INTEGER,
    bar_share        REAL,
    bars_used        INTEGER,
    bars_other       INTEGER,
    kick_slots       TEXT,                           -- JSON: slot label to count
    kick_per_bar     REAL,
    kick_off_grid    INTEGER,
    snare_slots      TEXT,                           -- JSON
    snare_per_bar    REAL,
    snare_hits       INTEGER,
    snare_off_grid   INTEGER,
    hat_per_beat     REAL,
    hat_present      INTEGER CHECK (hat_present IN (0, 1)),
    hat_off_grid     INTEGER,
    swing_ratio      REAL,
    swing_n          INTEGER,
    swing_spread     REAL,
    swing_band       TEXT,
    sub_share        REAL,
    wobble_depth     REAL,
    wobble_rate_hz   REAL,
    wobble_per_beat  REAL,
    vocal_share      REAL,
    mean_burst_s     REAL,
    bursts_per_s     REAL,
    vocal_kind       TEXT,
    loud_db          REAL,
    jump_db          REAL,
    loud_slope_db_s  REAL,
    bright_slope_hz_s REAL,
    fit_frames       INTEGER,
    key              TEXT,
    mode             TEXT,
    key_strength     REAL,
    UNIQUE (sheet_id, idx)
) STRICT;

CREATE TABLE fact_checks (
    id            INTEGER PRIMARY KEY,
    facts_version TEXT NOT NULL,
    fact          TEXT NOT NULL,
    right         INTEGER NOT NULL,
    wrong         INTEGER NOT NULL,
    unsure        INTEGER NOT NULL,
    sheet_ids     TEXT,                              -- JSON
    checked_at    TEXT NOT NULL
) STRICT;

-- +migrate down

DROP TABLE fact_checks;
DROP TABLE fact_sections;
DROP INDEX idx_fact_sheets_uri;
DROP TABLE fact_sheets;
