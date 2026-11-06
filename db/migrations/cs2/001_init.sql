-- +migrate up
-- cs2.db — CS2 inventory valuation store for the /ledger Hub module.
-- Append-only price snapshots plus a current-inventory table, per
-- docs/specs/2026-08-25-ledger-hub-module-design.md.
-- Collector writes; the valuation engine only reads, so the basis can be
-- re-run over the whole history without re-fetching. STRICT per the
-- warehouse contract. All money is INTEGER USD cents.

CREATE TABLE IF NOT EXISTS snapshot (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    taken_at TEXT NOT NULL DEFAULT (datetime('now')),
    source   TEXT NOT NULL,              -- steam | skinport_sales | skinport_listings
                                         -- | csfloat_listings | waxpeer_listings
                                         -- | csfloat_history
    ok       INTEGER NOT NULL DEFAULT 1, -- 0 when that source failed; the run continues
    note     TEXT NOT NULL DEFAULT ''    -- item counts on success, the error on failure
) STRICT;

-- One row per (run, item, source, basis, window). Append-only: a re-run writes a
-- new snapshot_id rather than updating. `basis` is what the number IS — a sale
-- statistic or an ask — and the two are never mixed by the engine.
CREATE TABLE IF NOT EXISTS item_price (
    snapshot_id      INTEGER NOT NULL REFERENCES snapshot(id) ON DELETE CASCADE,
    market_hash_name TEXT NOT NULL,
    source           TEXT NOT NULL,
    basis            TEXT NOT NULL CHECK (basis IN ('sale', 'listing')),
    window           TEXT NOT NULL,      -- sale: 24h|7d|30d|90d   listing: live
    price_cents      INTEGER,            -- sale median, or listing floor
    volume           INTEGER,            -- sales inside the window
    depth            INTEGER,            -- live listings at this venue
    PRIMARY KEY (snapshot_id, market_hash_name, source, basis, window)
) STRICT;

CREATE INDEX IF NOT EXISTS idx_item_price_name ON item_price(market_hash_name, snapshot_id DESC);

-- Current inventory. `marketable` (not `tradable`) is what gates valuation:
-- a trade-locked skin is tradable=0 but still worth money, while coins,
-- service medals and badges are marketable=0 and correctly excluded.
-- Floats stay NULL until a logged-in Steam session can supply inspect links.
CREATE TABLE IF NOT EXISTS holding (
    market_hash_name TEXT PRIMARY KEY,
    qty              INTEGER NOT NULL DEFAULT 0,
    first_seen       TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen        TEXT NOT NULL DEFAULT (datetime('now')),
    tradable         INTEGER NOT NULL DEFAULT 1,
    marketable       INTEGER NOT NULL DEFAULT 1,
    item_type        TEXT NOT NULL DEFAULT '',   -- Steam tag: Knife, Container, Agent...
    rarity           TEXT NOT NULL DEFAULT '',
    exterior         TEXT NOT NULL DEFAULT '',
    float_value      REAL,
    paint_seed       INTEGER
) STRICT;

-- CSFloat's daily series. avg_price, not a median, so thin days blow out: the
-- collector flags any day above 3x its own trailing-30-day median. The row is
-- KEPT and drawn greyed on the item page — a filter that hides its discards
-- cannot be checked by the person relying on it.
CREATE TABLE IF NOT EXISTS daily_sale (
    market_hash_name TEXT NOT NULL,
    day              TEXT NOT NULL,      -- YYYY-MM-DD
    avg_price_cents  INTEGER NOT NULL,
    trade_count      INTEGER NOT NULL DEFAULT 0,
    rejected         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (market_hash_name, day)
) STRICT;

-- +migrate down
DROP TABLE IF EXISTS daily_sale;
DROP TABLE IF EXISTS holding;
DROP INDEX IF EXISTS idx_item_price_name;
DROP TABLE IF EXISTS item_price;
DROP TABLE IF EXISTS snapshot;
