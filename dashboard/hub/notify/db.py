"""Store for data/notify.db (gitignored, per machine): post, cancel, list, mark read.

Schema comes from db/migrations/notify/; connect() self-heals a missing file the
way automations/db.py does. Timestamps are UTC, YYYY-MM-DDTHH:MM:SSZ, so text
order is time order. post() never touches the network; pushes go out from the
notify-push sweep.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from news.db import _ensure_schema
from sqlite_helpers import apply_pragmas

TITLE_MAX = 200
BODY_MAX = 2000
LIST_MAX = 30
MOVE_SECONDS = 300  # a due_at shifted by less than this counts as unchanged

_BAD_URL_CHARS = re.compile(r"[\x00-\x20\x7f]")


def default_path() -> Path:
    from vault_path import vault_root

    return vault_root() / "data" / "notify.db"


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open notify.db (default: VAULT/data/notify.db), creating the schema if
    absent. Caller closes. Tests pass a tmp path."""
    path = Path(path) if path else default_path()
    _ensure_schema(path, "notify")
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    apply_pragmas(conn)
    return conn


def _parse(value) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.strip())  # ValueError when malformed
    if not isinstance(value, datetime):
        raise ValueError("due_at must be a datetime or ISO string")
    if value.tzinfo is None:
        raise ValueError("due_at must be timezone-aware")
    return value.astimezone(timezone.utc)


def _ts(value) -> str:
    """Normalize an aware datetime or ISO string to YYYY-MM-DDTHH:MM:SSZ (UTC)."""
    return _parse(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now() -> str:
    return _ts(datetime.now(timezone.utc))


def _secs(ts: str) -> float:
    return _parse(ts.replace("Z", "+00:00")).timestamp()


def _check_url(url: str | None) -> str | None:
    if url is None or url == "":
        return None
    if _BAD_URL_CHARS.search(url):  # browsers strip tabs and newlines, so "/\n/evil.com" is "//evil.com"
        raise ValueError("url has whitespace or control characters")
    if url.startswith("/") and not url.startswith(("//", "/\\")):
        return url
    p = urlparse(url)
    if p.scheme == "https" and p.hostname:
        return url
    raise ValueError("url must be a Hub path or an https:// link")


def post(source, title, body=None, url=None, push=False, due_at=None, key=None, *, conn=None) -> int:
    """Post a notification, or update the one `key` names. See the design spec's
    "Post call" block for the key rules. Raises ValueError on bad input and
    sqlite3.Error when the store is unavailable."""
    source = (source or "").strip()
    title = (title or "").strip()[:TITLE_MAX]
    if not source:
        raise ValueError("source is required")
    if not title:
        raise ValueError("title is required")
    body = body.strip()[:BODY_MAX] if body else None
    url = _check_url(url)
    due = _ts(due_at) if due_at is not None else None
    key = (key or "").strip() or None

    own = conn is None
    if own:
        conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            now = _now()
            old = conn.execute("SELECT * FROM notification WHERE key=?", (key,)).fetchone() if key else None
            if old is None:
                cur = conn.execute(
                    "INSERT INTO notification (key, source, title, body, url, created_at, due_at, push_state) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (key, source, title, body, url, now, due or now, "pending" if push else "none"),
                )
                nid = cur.lastrowid
            else:
                nid = old["id"]
                new_due, read_at, state = old["due_at"], old["read_at"], old["push_state"]
                moved = due is not None and abs(_secs(due) - _secs(old["due_at"])) >= MOVE_SECONDS
                if moved and old["due_at"] > now:  # a row already due has fired; it keeps its time
                    new_due, read_at = due, None
                    if push:
                        state = "pending"
                if push and state == "none":
                    state = "pending"
                elif not push and state == "pending":
                    state = "none"
                conn.execute(
                    "UPDATE notification SET source=?, title=?, body=?, url=?, due_at=?, read_at=?, push_state=? "
                    "WHERE id=?",
                    (source, title, body, url, new_due, read_at, state, nid),
                )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        return nid
    finally:
        if own:
            conn.close()


def cancel(key, *, conn=None) -> bool:
    """Delete the row `key` names while it is not yet due. True when it did."""
    key = (key or "").strip() or None  # same normalization as post()
    own = conn is None
    if own:
        conn = connect()
    try:
        cur = conn.execute("DELETE FROM notification WHERE key=? AND due_at > ?", (key, _now()))
        conn.commit()
        return cur.rowcount > 0
    finally:
        if own:
            conn.close()


def _item(r) -> dict:
    return {
        "id": r["id"], "source": r["source"], "title": r["title"], "body": r["body"],
        "url": r["url"], "due_at": r["due_at"], "read": r["read_at"] is not None,
    }


def list_items(conn, now=None) -> dict:
    """{"unread": n, "items": [...]}: every due unread row first, then the newest
    read ones, LIST_MAX in all but never fewer than every due unread row."""
    now = _ts(now) if now is not None else _now()
    unread = conn.execute(
        "SELECT * FROM notification WHERE due_at <= ? AND read_at IS NULL AND deleted_at IS NULL ORDER BY due_at DESC, id DESC",
        (now,),
    ).fetchall()
    room = max(0, LIST_MAX - len(unread))
    read = conn.execute(
        "SELECT * FROM notification WHERE due_at <= ? AND read_at IS NOT NULL AND deleted_at IS NULL "
        "ORDER BY due_at DESC, id DESC LIMIT ?",
        (now, room),
    ).fetchall()
    return {"unread": len(unread), "items": [_item(r) for r in unread + read]}


def mark_read(conn, ids, now=None) -> int:
    """Mark the listed due rows read. Returns rows changed. There is no "mark
    every row": the bell sends the ids it showed, so a row due since stays unread."""
    now = _ts(now) if now is not None else _now()
    cur = conn.execute(
        "UPDATE notification SET read_at=? WHERE read_at IS NULL AND due_at <= ? "
        "AND id IN (SELECT value FROM json_each(?))",
        (now, now, json.dumps(list(ids))),
    )
    conn.commit()
    return cur.rowcount


def delete(conn, ids, now=None) -> int:
    """Delete rows from the bell (no confirm). A tombstone, not a DELETE: a source that
    posts the same key again while its item still waits must not bring it back. Read is
    set too, so the 30-day prune takes it; a push not sent yet is skipped."""
    now = _ts(now) if now is not None else _now()
    cur = conn.execute(
        "UPDATE notification SET deleted_at=?, read_at=COALESCE(read_at, ?), "
        "push_state=CASE WHEN push_state='pending' THEN 'skipped' ELSE push_state END "
        "WHERE deleted_at IS NULL AND id IN (SELECT value FROM json_each(?))",
        (now, now, json.dumps(list(ids))),
    )
    conn.commit()
    return cur.rowcount


def sync(source, waiting, *, conn) -> dict:
    """Make `source`'s rows match what waits on him now. `waiting` maps key -> post()
    kwargs (title, body, url, due_at); every key starts "<source>:". A key that is no
    longer waiting is removed outright, tombstone included, so if it waits again later
    it shows as new; a key still waiting keeps its tombstone. Raises sqlite3.Error."""
    prefix = source + ":"
    if any(not k.startswith(prefix) for k in waiting):
        raise ValueError(f"every key must start with {prefix!r}")
    have = {r["key"]: r for r in conn.execute(
        "SELECT key, title, body, url FROM notification WHERE substr(key, 1, ?) = ?", (len(prefix), prefix))}
    gone = [k for k in have if k not in waiting]
    if gone:
        conn.execute("DELETE FROM notification WHERE key IN (SELECT value FROM json_each(?))", (json.dumps(gone),))
        conn.commit()
    added = 0
    for k, f in waiting.items():
        old = have.get(k)
        if old and (old["title"], old["body"], old["url"]) == (
                (f["title"] or "").strip()[:TITLE_MAX], (f.get("body") or "").strip()[:BODY_MAX] or None, f.get("url") or None):
            continue  # unchanged: skip the write
        post(source, key=k, conn=conn, **f)
        added += old is None
    return {"added": added, "removed": len(gone)}


STALE_SENDING = 300
SKIP_AFTER = 6 * 3600
KEEP_READ = 30 * 86400


def _ago(now: str, seconds: int) -> str:
    return _ts(datetime.fromtimestamp(_secs(now) - seconds, timezone.utc))


def sweep(conn, now=None, send=None, topic_path=None) -> dict:
    """Push every due `pending` row at most once, then prune old read rows.

    Claim (pending -> sending, committed) comes before the network call, so a
    crash mid-send never resends; a boost between select and claim fails the
    claim. Pushes nothing without a non-empty topic file, because news.alerts
    would mint a fresh topic the phone does not follow; the prune runs anyway.
    Failures log row ids only: the request URL holds the topic."""
    counts = {"sent": 0, "failed": 0, "skipped": 0, "pruned": 0}
    now = _ts(now) if now is not None else _now()
    try:  # lazy: news.alerts pulls in the news stack, and a failure there must not stop the prune
        from news.alerts import HUB_BASE, NTFY_TOPIC_PATH, _post
        tp = Path(topic_path) if topic_path else NTFY_TOPIC_PATH
        has_topic = bool(tp.read_text(encoding="utf-8").strip())
    except FileNotFoundError:
        has_topic = False
    except Exception as e:  # unreadable topic or a broken import: no push, the prune still runs
        logging.getLogger(__name__).warning("notify push skipped: %s", type(e).__name__)
        has_topic = False
    if has_topic:
        _push(conn, now, send or _post, counts, HUB_BASE)
    cur = conn.execute(
        "DELETE FROM notification WHERE read_at IS NOT NULL AND read_at < ?", (_ago(now, KEEP_READ),)
    )
    conn.commit()
    counts["pruned"] = cur.rowcount
    return counts


def _push(conn, now, send, counts, hub_base) -> None:
    log = logging.getLogger(__name__)

    cur = conn.execute(
        "UPDATE notification SET push_state='failed' WHERE push_state='sending' AND pushed_at <= ?",
        (_ago(now, STALE_SENDING),),
    )
    counts["failed"] += cur.rowcount
    conn.commit()

    rows = conn.execute(
        "SELECT id, title, body, url, due_at FROM notification WHERE push_state='pending' AND due_at <= ?",
        (now,),
    ).fetchall()
    cutoff = _ago(now, SKIP_AFTER)
    for r in rows:
        if r["due_at"] < cutoff:
            cur = conn.execute(
                "UPDATE notification SET push_state='skipped' WHERE id=? AND push_state='pending' AND due_at=?",
                (r["id"], r["due_at"]),
            )
            conn.commit()
            counts["skipped"] += cur.rowcount
            continue
        cur = conn.execute(
            "UPDATE notification SET push_state='sending', pushed_at=? "
            "WHERE id=? AND push_state='pending' AND due_at=? AND due_at<=?",
            (now, r["id"], r["due_at"], now),
        )
        conn.commit()
        if cur.rowcount != 1:
            continue
        url = r["url"] or ""
        if url.startswith("/"):
            url = hub_base + url
        try:
            send(r["title"], r["body"] or "", url)
            state = "sent"
        except Exception:
            state = "failed"
            log.error("notify push failed for row %s", r["id"])  # no exc info: it can carry the topic URL
        conn.execute("UPDATE notification SET push_state=?, pushed_at=? WHERE id=?", (state, now, r["id"]))
        conn.commit()
        counts[state] += 1
