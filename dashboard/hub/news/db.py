"""Data layer for the news dashboard, split across two databases.

data/news.db (tracked, small): sources, topics, digests -- config Sam edits
directly plus the daily digest. Schema comes from db/migrations/news/, never
from this file.

data/news-cache.db (gitignored, rebuildable): items, clusters, articles, alerts,
poll_state -- everything the 15-minute poll writes. Schema comes from
db/migrations/news-cache/.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from sqlite_helpers import apply_pragmas, connect as sqlite_connect, row as _row, rows as _rows

_news_path: Path | None = None
_cache_path: Path | None = None

# repo_root/db/migrations/<module>/NNN_label.sql -- same layout db/migrate.py
# reads, three levels up from this file (news/ -> hub/ -> dashboard/ -> repo root).
_MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "db" / "migrations"
_MIGRATION_FILENAME_RE = re.compile(r"^(\d{3})_([a-z0-9_-]+)\.sql$")
_MARKER_TABLE = {"news": "sources", "news-cache": "items", "automations": "gmail_item", "mail": "account", "notify": "notification"}
# Gitignored, per-machine and rebuildable, so it also takes its later migrations
# here: the Mac's copy would otherwise fail every grouping call on a missing
# table until someone ran migrate.py there. Tracked dbs keep migrate.py's backups.
_SELF_MIGRATING = {"news-cache", "notify"}


def _migration_files(module: str) -> list[tuple[int, str, Path]]:
    out = []
    for path in sorted((_MIGRATIONS_DIR / module).glob("*.sql")):
        m = _MIGRATION_FILENAME_RE.match(path.name)
        if m:
            out.append((int(m.group(1)), m.group(2), path))
    return out


def _migration_up_sql(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"--\s*\+migrate\s+up\s*\n(.*?)(?=--\s*\+migrate\s+down|\Z)", text,
                  re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


_schema_ok: set[tuple[str, str]] = set()


def _ensure_schema(db_path: Path, module: str) -> None:
    """Self-heal: apply `module`'s migrations if its marker table is missing
    (a fresh db, or news-cache.db deleted/rebuilt -- gitignored, spec posture
    is "rebuilt on next poll"). A no-op once the marker table exists, so an
    already-migrated live db is untouched (news-cache excepted, see
    _SELF_MIGRATING); bringing a schema up to a LATER
    migration once tables already exist is still `db/migrate.py up`'s job,
    not this -- see that script for the full apply/backup/guard machinery
    this deliberately does not reuse for a startup-time path.

    Writes the same schema_migrations bookkeeping db/migrate.py itself reads,
    so `python db/migrate.py current <module>` stays accurate afterward.

    Remembered per path once the marker table is seen: automations and mail call
    this on every connect, and the extra open + CREATE on /mnt/c cost ~20 ms each
    time. A file that has since vanished is checked again, so a deleted db still heals.
    """
    key = (str(db_path), module)
    if key in _schema_ok and db_path.exists():
        return
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    apply_pragmas(conn)  # warehouse PRAGMA baseline
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, label TEXT NOT NULL, "
            "applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        marker = _MARKER_TABLE[module]
        exists = conn.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?", (marker,)
        ).fetchone()
        applied = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
        if exists and not (module in _SELF_MIGRATING and applied):
            _schema_ok.add(key)
            return
        floor = max(applied) if exists else 0  # existing db: only migrations newer than its last one
        for version, label, path in _migration_files(module):
            if version in applied or version <= floor:
                continue
            up_sql = _migration_up_sql(path)
            if up_sql:
                conn.executescript(up_sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, label) VALUES (?, ?)",
                (version, label),
            )
        conn.commit()
        _schema_ok.add(key)
    finally:
        conn.close()


def init(news_path: Path, cache_path: Path) -> None:
    """Point the module at both database files, self-healing an empty one.

    Migrations remain the source of truth for schema (see db/migrate.py); this
    only fills in a database that has no tables at all, so a first-time run or
    a deleted news-cache.db comes back up on its own instead of every poll/API
    call erroring on "no such table" until someone remembers to run `up` by
    hand.
    """
    global _news_path, _cache_path
    _news_path = news_path
    _cache_path = cache_path
    _ensure_schema(news_path, "news")
    _ensure_schema(cache_path, "news-cache")


def _news():
    return sqlite_connect(_news_path, "news")


def _cache():
    return sqlite_connect(_cache_path, "news-cache")


# ── Seeding (INSERT OR IGNORE -- his later edits always win) ──────────────────

_SOURCE_FIELDS = {
    "name", "url", "kind", "section", "lane", "lean",
    "factual", "owner", "state_affiliation", "paywall", "enabled", "rating_note",
}

# url is seed-file-only: the PATCH endpoint can toggle/edit everything else
# about a source, but never repoint its url. poll.py's SSRF-relevant checks
# (scheme, redirect cap, size cap) all trust that a source's url is one of the
# curated ones in sources_seed.json, not something the live API can rewrite to
# an arbitrary address after the fact.
_PATCHABLE_SOURCE_FIELDS = _SOURCE_FIELDS - {"url"}

_TOPIC_FIELDS = {"kind", "query", "enabled"}


def seed_sources(seed_path: Path) -> int:
    """Insert every source in the seed JSON that isn't already there (matched on
    id). Returns the number of rows actually inserted, so a re-run against an
    already-seeded db reports 0 -- his own edits to an existing row are never
    touched, per the design's INSERT OR IGNORE contract."""
    entries = json.loads(Path(seed_path).read_text(encoding="utf-8"))
    inserted = 0
    with _news() as conn:
        for entry in entries:
            fields = {"id": entry["id"]}
            fields.update({k: entry.get(k) for k in _SOURCE_FIELDS if k in entry})
            cols = ", ".join(fields)
            placeholders = ", ".join(f":{k}" for k in fields)
            cur = conn.execute(
                f"INSERT OR IGNORE INTO sources ({cols}) VALUES ({placeholders})",
                fields,
            )
            inserted += cur.rowcount
    return inserted


def seed_ticker_topics(stocks_db: Path) -> int:
    """One 'ticker' topic per row already tracked in the shared stocks.db.
    Returns the number of topics rows actually inserted."""
    tconn = sqlite3.connect(str(stocks_db))
    apply_pragmas(tconn)  # warehouse PRAGMA baseline
    try:
        tickers = [r[0] for r in tconn.execute("SELECT ticker FROM stocks")]
    finally:
        tconn.close()
    inserted = 0
    with _news() as conn:
        for ticker in tickers:
            cur = conn.execute(
                "INSERT OR IGNORE INTO topics (kind, query, enabled) "
                "VALUES ('ticker', ?, 1)",
                (ticker,),
            )
            inserted += cur.rowcount
    return inserted


# ── Generic CRUD (allow-set decides what's writable from the API) ─────────────
#
# Both sources and topics key their primary key column "id" (sources: a slug;
# topics: autoincrement), so one generic trio covers both without a parent_id
# the way trips'/purchases' sub-resource CRUD needs -- these are top-level rows.


def _add(conn: sqlite3.Connection, table: str, data: dict, allowed: set) -> dict:
    fields = {k: v for k, v in data.items() if k in allowed}
    cols = ", ".join(fields)
    placeholders = ", ".join(f":{k}" for k in fields)
    cur = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", fields)
    return _row(  # pyright: ignore[reportReturnType]  row was just written, fetchone is not None
        conn.execute(f"SELECT * FROM {table} WHERE id=?", (cur.lastrowid,)).fetchone()
    )


def _update(conn: sqlite3.Connection, table: str, row_id, data: dict, allowed: set) -> dict | None:
    updates = {k: v for k, v in data.items() if k in allowed}
    if updates:
        sets = ", ".join(f"{k}=?" for k in updates)
        conn.execute(
            f"UPDATE {table} SET {sets} WHERE id=?", (*updates.values(), row_id)
        )
    return _row(conn.execute(f"SELECT * FROM {table} WHERE id=?", (row_id,)).fetchone())


def _delete(conn: sqlite3.Connection, table: str, row_id) -> bool:
    cur = conn.execute(f"DELETE FROM {table} WHERE id=?", (row_id,))
    return cur.rowcount > 0


# ── Sources ─────────────────────────────────────────────────────────────────
# No add/delete: the seed file is the only source of new rows; the API only
# ever toggles/edits an existing one (Task 8).


def list_sources() -> list[dict]:
    with _news() as conn:
        return _rows(conn.execute("SELECT * FROM sources ORDER BY section, name").fetchall())


def update_source(id: str, data: dict) -> dict | None:
    with _news() as conn:
        return _update(conn, "sources", id, data, _PATCHABLE_SOURCE_FIELDS)


# ── Topics ──────────────────────────────────────────────────────────────────


def list_topics() -> list[dict]:
    with _news() as conn:
        return _rows(conn.execute("SELECT * FROM topics ORDER BY kind, query").fetchall())


def add_topic(data: dict) -> dict:
    with _news() as conn:
        return _add(conn, "topics", data, _TOPIC_FIELDS)


def update_topic(id: int, data: dict) -> dict | None:
    with _news() as conn:
        return _update(conn, "topics", id, data, _TOPIC_FIELDS)


def delete_topic(id: int) -> bool:
    with _news() as conn:
        return _delete(conn, "topics", id)


# ── Digest ──────────────────────────────────────────────────────────────────


def get_digest(date: str) -> dict | None:
    with _news() as conn:
        return _row(conn.execute("SELECT * FROM digests WHERE date=?", (date,)).fetchone())


def save_digest(date: str, markdown: str) -> dict:
    """Write (or overwrite) today's digest. cli.py checks citations first."""
    with _news() as conn:
        conn.execute(
            """INSERT INTO digests (date, markdown) VALUES (?, ?)
               ON CONFLICT(date) DO UPDATE SET
                 markdown = excluded.markdown, created_at = datetime('now')""",
            (date, markdown),
        )
        return _row(conn.execute("SELECT * FROM digests WHERE date=?", (date,)).fetchone())  # pyright: ignore[reportReturnType]  row was just written, fetchone is not None
