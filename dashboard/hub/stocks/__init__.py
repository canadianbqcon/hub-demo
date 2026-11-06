# stocks — Hub (port 5002) module: read-only stock watchlist + detail view.
# Reads data/stocks.db, written exclusively by the /stock skill (see
# stocks/CLAUDE.md). Structure mirrors dashboard/hub/purchases (blueprint +
# db.py + a single server-rendered template), simplified: no forms, no
# writes, no VaultReader — this module only displays what the skill already
# analyzed, plus a live price refresh.
