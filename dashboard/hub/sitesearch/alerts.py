"""Saved searches and the sitesearch-alerts job (phone push for new listings under a price)."""

import fcntl
import logging
import os
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from . import _env, search as _search, stores

log = logging.getLogger(__name__)
MAX_PUSHES = 5


def _db_path():
    if _env._DASHBOARD not in sys.path:
        sys.path.append(_env._DASHBOARD)
    from vault_path import vault_root
    return vault_root() / "data" / "purchases.db"


def _connect(db=None):
    """`db` is an open connection (tests) or None for the live purchases.db."""
    if db is not None:
        return db
    conn = sqlite3.connect(_db_path(), timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def save(query, sites, max_price, db=None) -> int:
    conn = _connect(db)
    cur = conn.execute(
        "INSERT INTO saved_searches (query, sites, max_price, created) VALUES (?, ?, ?, ?)",
        (query, ",".join(sites) if not isinstance(sites, str) else sites, max_price,
         datetime.now(timezone.utc).isoformat()))
    return cur.lastrowid  # pyright: ignore[reportReturnType]  lastrowid is set after an INSERT


def list_searches(db=None) -> list[dict]:
    return [dict(r) for r in _connect(db).execute("SELECT * FROM saved_searches ORDER BY id")]


def remove(id, db=None) -> bool:
    return _connect(db).execute("DELETE FROM saved_searches WHERE id = ?", (int(id),)).rowcount > 0


def _alert_sites(sites: str) -> list[str]:
    ok = {"ebay", *(n for n in stores.names() if stores._load().get(n, {}).get("backend") != "headless")}
    if _env.key("KEEPA_KEY"):
        ok.add("amazon")
    return [s for s in sites.split(",") if s in ok]


def _send(title, body, url):
    from news.alerts import _post
    _post(title, body, url)


def _fresh(search, s, sites):
    """(listings, all_sites_ok); listings de-duplicated by url, priced only."""
    res = search(s["query"], sites, max_price=s["max_price"], newest=True)
    seen, out = set(), []
    for r in res:
        for x in r.rows:
            if x.price is not None and x.url not in seen:
                seen.add(x.url)
                out.append(x)
    # no_key and blocked are standing states, not failures: seed without that site (adding the key later
    # alerts at most MAX_PUSHES + 1 summary for its backlog). error stays a failure.
    return out, all(r.status in ("ok", "no_key", "blocked") for r in res)


def run_once(now, search=None, send=None, db=None) -> dict:
    """One pass over active saved searches. Returns {id: {"seeded"|"sent"|"failed"|"error": n}}."""
    search = search or _search
    send = send or _send
    conn = _connect(db)
    stamp = now.isoformat()
    counts = {}
    for s in conn.execute("SELECT * FROM saved_searches WHERE active = 1").fetchall():
        c = counts[s["id"]] = {}
        try:
            sites = _alert_sites(s["sites"])
            rows, all_ok = _fresh(search, s, sites) if sites else ([], True)
            if s["seeded_at"] is None:
                if not all_ok:  # a partial seed would alert on the missing site's listings later
                    c["error"] = 1
                    continue
                conn.execute("BEGIN")
                try:
                    conn.executemany(
                        "INSERT OR IGNORE INTO seen_listings (search_id, url, price, first_seen) VALUES (?, ?, ?, ?)",
                        [(s["id"], x.url, x.price, stamp) for x in rows])
                    conn.execute("UPDATE saved_searches SET seeded_at = ? WHERE id = ?", (stamp, s["id"]))
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                c["seeded"] = len(rows)
                continue
            known = {r[0] for r in conn.execute("SELECT url FROM seen_listings WHERE search_id = ?", (s["id"],))}
            cap = s["max_price"]
            new = [x for x in rows if x.url not in known and (cap is None or x.price <= cap)]
            sent = 0
            for x in new[:MAX_PUSHES]:
                try:
                    send(f"{s['query']}: ${x.price:.2f}", x.title, x.url)
                except Exception:
                    log.exception("sitesearch push failed: %s", x.url)
                    c["failed"] = c.get("failed", 0) + 1
                    continue
                conn.execute("INSERT INTO seen_listings (search_id, url, price, first_seen) VALUES (?, ?, ?, ?)",
                             (s["id"], x.url, x.price, stamp))
                sent += 1
            rest = new[MAX_PUSHES:]
            if rest:
                try:
                    under = f" under ${cap:.2f}" if cap is not None else ""
                    send(f"{s['query']}: {len(rest)} more{under}", "", rest[0].url)
                    conn.executemany(
                        "INSERT INTO seen_listings (search_id, url, price, first_seen) VALUES (?, ?, ?, ?)",
                        [(s["id"], x.url, x.price, stamp) for x in rest])
                    sent += 1
                except Exception:
                    log.exception("sitesearch summary push failed")
                    c["failed"] = c.get("failed", 0) + 1
            c["sent"] = sent
        except Exception:
            log.exception("sitesearch search failed: %s", s["query"])
            c["error"] = 1
        finally:
            conn.execute("UPDATE saved_searches SET last_run = ? WHERE id = ?", (stamp, s["id"]))
    return counts


@contextmanager
def _lock():
    """Non-blocking flock beside purchases.db (same pattern as news/poll.py process_poll_lock)."""
    path = _db_path().with_suffix(".alerts.lock")
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        yield False
        return
    try:
        yield True
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def run(job: dict) -> None:
    """TRIGGER_JOBS["sitesearch-alerts"]: cadence, quiet hours and overlap guard, then run_once."""
    from news.alerts import TZ, _in_quiet_hours
    now = datetime.now(timezone.utc)
    if _in_quiet_hours(now.astimezone(TZ)):
        return
    with _lock() as got:
        if not got:
            return
        conn = _connect()
        last = conn.execute("SELECT MAX(last_run) FROM saved_searches").fetchone()[0]
        if last and now - datetime.fromisoformat(last) < timedelta(minutes=job.get("interval_minutes", 30)):
            return
        run_once(now, db=conn)
