"""Post or cancel a Hub notification per upgrade change. Never raises into the caller."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote


def key(row) -> str:
    return f"clash:{row['tag']}:{row['data_id']}:{row['from_level']}:{row['finishes_at']}"


def _notify():
    try:
        import notify  # at call time, so it is picked up without a restart
        return notify
    except Exception:
        return None


def available() -> bool:
    return _notify() is not None


def _name(data_id) -> str:
    try:
        from clash.gamedata import entity
        return entity(data_id)["name"]
    except Exception:
        return "Upgrade"


def scheduled(row) -> bool:
    """Post the done-notification for an upgrade row. True when posted."""
    try:
        n = _notify()
        if n is None:
            return False
        due = datetime.fromisoformat(str(row["finishes_at"]).replace("Z", "+00:00"))
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        n.post("clash", f"{_name(row['data_id'])} level {row['from_level'] + 1} done",
               url="/clash/?tag=" + quote(row["tag"], safe=""), push=True, due_at=due, key=key(row))
        return True
    except Exception:  # sqlite3.Error, ValueError, anything: the caller re-posts next run
        return False


def dropped(row) -> bool:
    try:
        n = _notify()
        if n is None:
            return False
        n.cancel(key(row))
        return True
    except Exception:
        return False


_FREE = {"builder": "Builder free", "lab": "Lab free", "pet_house": "Pet House free"}
_posted: dict = {}  # ponytail: per-process memo of queue id -> posted start; a restart re-posts each once


def queue_key(qid) -> str:
    return f"clash:q:{qid}"


def queued(item) -> bool:
    """Remind him to start a queued upgrade when its lane frees. Posting the same key again moves
    the reminder while it is not yet due; a fired one keeps its time. Never assumes he started it."""
    if _posted.get(item["id"]) == item["start"]:
        return True  # unchanged since the last post: the page polls every minute, skip the write
    try:
        n = _notify()
        if n is None:
            return False
        due = datetime.fromisoformat(str(item["start"]).replace("Z", "+00:00"))
        n.post("clash", f"{_FREE.get(item['facility'], 'Free')}: start {_name(item['data_id'])} level {item['from_level'] + 1}",
               url="/clash/?tag=" + quote(item["tag"], safe=""), push=True, due_at=due, key=queue_key(item["id"]))
        _posted[item["id"]] = item["start"]
        return True
    except Exception:
        return False


def unqueued(qid) -> bool:
    _posted.pop(qid, None)
    try:
        n = _notify()
        if n is None:
            return False
        n.cancel(queue_key(qid))
        return True
    except Exception:
        return False


def repost_open(conn) -> int:
    """Re-post every upgrade still running; returns how many posted. Finished ones are left out:
    notify purges read rows after 30 days, and a re-post then would push "done" a second time."""
    try:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = conn.execute("SELECT * FROM upgrade WHERE finishes_at > ?", (now,)).fetchall()
    except Exception:
        return 0
    return sum(scheduled(r) for r in rows)
