# purchases — Hub (port 5002) module: purchase-research planner.
# Backend ported from the legacy 5001 dashboard. Reads the same
# data/purchases.db the 5001 app used — one DB, no duplication. Differences from
# the 5001 module: the live-reload SSE (/api/events, which needed the 5001 app's
# vault watcher + event queue) is dropped, and the VaultReader for node lookups
# is built lazily instead of injected via init() — mirroring the trips port.
