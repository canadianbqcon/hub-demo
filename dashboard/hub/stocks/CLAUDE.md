# CLAUDE.md — dashboard/hub/stocks/ (stock watchlist + detail view)

Scoped rules for the stocks module. For cross-module dashboard rules (wiki–implementation sync, code standards), see `dashboard/CLAUDE.md` — it loads in addition to this file when you work here.

Lives under the Hub dashboard (port 5002) — no React/JSX in this module. As of 2026-07-24 the **view** is a tab inside the finances umbrella (`/finances#stocks`); this blueprint keeps serving the `/stocks/api/*` data the finances page reads, and its `/stocks/` page route now 302-redirects to `/finances/#stocks` so old links resolve. The watchlist/detail markup + JS were ported into `finances/frontend/` (scoped under `#panel-stocks`); the old standalone `stocks.html` was deleted on 2026-10-13 (Sam), after a check that the finances tab calls the same two endpoints and shows every field it showed. Chrome (topbar/theme via `theme-switch.js`) comes from the finances page.

## Read-only [BINDING]

This module **never writes** to `data/stocks.db`. The `/stock` skill (Claude-only action skill) is the sole writer — it researches a ticker and inserts one `analyses` row per run, then upserts the `stocks` rollup row. `db.py`'s `init()` does not create tables (schema is frozen, owned by the migration); it only points `_conn()` at the file. If a future change needs the Hub to write here, that's a scope change to raise explicitly, not something to add quietly.

## Schema (owned by the migration, not this module)

- `stocks` — one row per ticker: `ticker` (PK), `company`, `sector`, `first_analyzed`, `last_analyzed`, `latest_viability_score`, `latest_verdict_summary`, `latest_price`, `latest_analysis_id` (FK-by-convention into `analyses.id`, not a real FK).
- `analyses` — append-only, one row per run: `id`, `ticker`, `run_date`, `price_at_run`, `viability_score`, `bull_case`/`base_case`/`bear_case`, `lt_thesis`/`lt_fair_value`/`lt_allocation`/`lt_exit_triggers`, `trade_entry`/`trade_entry_num`, `trade_targets`/`trade_target_num`, `trade_stop`/`trade_stop_num`, `trade_timeframe`, `trade_risk_reward`, `verdict_summary`, `next_earnings` (unix-timestamp string, often blank), `metrics_json`.

`db.list_stocks()` joins `stocks` to its `latest_analysis_id` row for the trade numbers the watchlist table needs. `db.get_stock(ticker)` returns the rollup row plus the full `analyses` history (newest first, `metrics_json` parsed to a dict on the newest entry only).

## Live price refresh — batched, never per-ticker [BINDING]

`api._fetch_prices()` makes **one** `yfinance.download()` call for the whole watchlist (`group_by="ticker"`, space-joined ticker string), not one request per row — a per-ticker loop is the mistake this guards against as the watchlist grows. On any fetch failure it returns an empty dict and a `fetch_failed` flag; `_watchlist()` then falls back to each row's own `latest_price` and marks `price_stale: true` so the frontend can flag it.

## Staleness guard [BINDING]

Independent of the price fetch, `api._is_stale()` flags a row `stale: true` when either:
- `last_analyzed` is 30+ days old (`_STALE_DAYS`), or
- `next_earnings` parses as a unix timestamp that has already passed.

Stale rows render greyed with a warning marker and are **excluded from a distance-to-entry sort** (they sink to the bottom) — a game plan built on facts that may have changed shouldn't rank as "close to entry" next to a fresh one. They still render at full detail; nothing is hidden, only flagged.

## Endpoints

`GET /stocks/` (302 → `/finances/#stocks`), `GET /stocks/api/stocks` (watchlist, live-priced), `GET /stocks/api/stocks/<ticker>` (rollup + history, 404 if unknown).

## Wiki–implementation sync

When the schema, staleness thresholds, or the batching behavior above changes, update this file in the same operation (per the cross-module sync rule in `dashboard/CLAUDE.md`).
