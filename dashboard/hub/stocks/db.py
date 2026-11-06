"""Stock watchlist data layer for the Hub module.

Read-only over the shared data/stocks.db. Schema is frozen by the migration
(schema_migrations at version 1) and owned by the /stock skill, which is the
only writer of `stocks` (one row per ticker, current rollup) and `analyses`
(append-only, one row per run). init() therefore does NOT create tables — it
only points _conn() at the file, mirroring purchases/db.py's connection
pattern but skipping the CREATE-IF-NOT-EXISTS bootstrap that module needs and
this one doesn't.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from sqlite_helpers import apply_pragmas

_db_path: Path | None = None


def init(db_path: Path) -> None:
    global _db_path
    _db_path = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def _conn():
    conn = sqlite3.connect(str(_db_path))
    conn.row_factory = sqlite3.Row
    apply_pragmas(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row(r):
    return dict(r) if r else None


def _rows(rs):
    return [dict(r) for r in rs]


def list_stocks() -> list[dict]:
    """Every ticker's current rollup, joined to its latest analysis for the
    trade numbers the watchlist table needs (entry/target/stop/earnings/run
    date live on `analyses`, not `stocks`)."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT s.*, "
            " a.trade_entry_num, a.trade_target_num, a.trade_stop_num, "
            " a.next_earnings, a.run_date "
            "FROM stocks s "
            "LEFT JOIN analyses a ON a.id = s.latest_analysis_id "
            "ORDER BY s.last_analyzed DESC"
        ).fetchall()
    return _rows(rows)


def get_stock(ticker: str) -> dict | None:
    """One ticker's rollup row plus its full analysis history, newest first.
    The newest history entry has metrics_json parsed to a dict; older entries
    keep it as raw text (nothing currently reads history metrics)."""
    with _conn() as conn:
        stock = _row(
            conn.execute("SELECT * FROM stocks WHERE ticker=?", (ticker,)).fetchone()
        )
        if stock is None:
            return None
        history = _rows(
            conn.execute(
                "SELECT * FROM analyses WHERE ticker=? ORDER BY run_date DESC",
                (ticker,),
            ).fetchall()
        )
    if history:
        try:
            history[0]["metrics_json"] = json.loads(history[0]["metrics_json"] or "{}")
        except (TypeError, ValueError):
            history[0]["metrics_json"] = {}
    stock["history"] = history
    return stock
