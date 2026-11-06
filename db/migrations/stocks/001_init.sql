-- +migrate up
-- stocks.db — per-ticker viability analyses for the /stock skill + /stocks dashboard.
-- Two tables: `stocks` (current-state, one row per ticker) and `analyses`
-- (append-only history, one row per /stock run). STRICT per the warehouse contract.

CREATE TABLE IF NOT EXISTS analyses (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker            TEXT NOT NULL,
    run_date          TEXT NOT NULL DEFAULT (datetime('now')),
    price_at_run      REAL,
    viability_score   INTEGER,          -- 0–100, rubric-anchored (see /stock SKILL.md)
    -- scenarios
    bull_case         TEXT NOT NULL DEFAULT '',
    base_case         TEXT NOT NULL DEFAULT '',
    bear_case         TEXT NOT NULL DEFAULT '',
    -- long-term thesis
    lt_thesis         TEXT NOT NULL DEFAULT '',
    lt_fair_value     TEXT NOT NULL DEFAULT '',
    lt_allocation     TEXT NOT NULL DEFAULT '',
    lt_exit_triggers  TEXT NOT NULL DEFAULT '',
    -- trade setup: text rationale/range + the single number the dashboard sorts on
    trade_entry       TEXT NOT NULL DEFAULT '',
    trade_entry_num   REAL,
    trade_targets     TEXT NOT NULL DEFAULT '',
    trade_target_num  REAL,
    trade_stop        TEXT NOT NULL DEFAULT '',
    trade_stop_num    REAL,
    trade_timeframe   TEXT NOT NULL DEFAULT '',
    trade_risk_reward TEXT NOT NULL DEFAULT '',
    verdict_summary   TEXT NOT NULL DEFAULT '',
    next_earnings     TEXT,             -- for the dashboard staleness guard
    metrics_json      TEXT NOT NULL DEFAULT '{}'  -- raw Stage-1 fetch() snapshot
) STRICT;

CREATE TABLE IF NOT EXISTS stocks (
    ticker                  TEXT PRIMARY KEY,
    company                 TEXT NOT NULL DEFAULT '',
    sector                  TEXT NOT NULL DEFAULT '',
    first_analyzed          TEXT NOT NULL DEFAULT (datetime('now')),
    last_analyzed           TEXT NOT NULL DEFAULT (datetime('now')),
    latest_viability_score  INTEGER,
    latest_verdict_summary  TEXT NOT NULL DEFAULT '',
    latest_price            REAL,
    latest_analysis_id      INTEGER REFERENCES analyses(id) ON DELETE SET NULL
) STRICT;

CREATE INDEX IF NOT EXISTS idx_analyses_ticker ON analyses(ticker, run_date DESC);

-- +migrate down
DROP INDEX IF EXISTS idx_analyses_ticker;
DROP TABLE IF EXISTS stocks;
DROP TABLE IF EXISTS analyses;
