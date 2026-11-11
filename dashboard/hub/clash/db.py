"""Clash store and the shared timer engine over data/clash.db (schema: db/migrations/clash)."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from sqlite_helpers import apply_pragmas

from . import notify_glue

_db_path: Path | None = None

FMT = "%Y-%m-%dT%H:%M:%SZ"  # every stored time: UTC, whole seconds


def now() -> str:
    return datetime.now(timezone.utc).strftime(FMT)


def parse(s: str) -> datetime:
    return datetime.strptime(s, FMT).replace(tzinfo=timezone.utc)


def accounts(c) -> list[dict]:
    return [dict(r) for r in c.execute("SELECT tag, name, th_level FROM account ORDER BY position, name COLLATE NOCASE, tag")]

FACILITIES = ("builder", "lab", "pet_house")


class FacilityFull(Exception):
    """Every builder, or the lab, or the pet house, is already busy."""


def init(db_path: Path) -> None:
    global _db_path
    _db_path = Path(db_path)
    _db_path.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def conn():
    c = sqlite3.connect(str(_db_path))
    c.row_factory = sqlite3.Row
    apply_pragmas(c)
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def _begin(c: sqlite3.Connection) -> None:
    # Python's sqlite3 only opens a transaction before DML; take the write lock up front
    # so the delete and the count move below are one unit. Nested use joins the open one.
    if not c.in_transaction:
        c.execute("BEGIN IMMEDIATE")


def _move_count(c: sqlite3.Connection, tag: str, data_id: int, frm: int, to: int, predicted: int) -> None:
    """Move one copy from level frm to level to. Decrement (delete at 0) then upsert."""
    took = c.execute("DELETE FROM structure WHERE tag=? AND data_id=? AND level=? AND cnt = 1", (tag, data_id, frm)).rowcount
    took += c.execute("UPDATE structure SET cnt = cnt - 1 WHERE tag=? AND data_id=? AND level=?", (tag, data_id, frm)).rowcount
    if not took:  # no copy left at frm (a re-paste moved it): adding one at `to` would invent a building
        return
    c.execute(
        "INSERT INTO structure (tag, data_id, level, cnt, predicted) VALUES (?,?,?,1,?) "
        "ON CONFLICT(tag, data_id, level) DO UPDATE SET cnt = cnt + 1, predicted = excluded.predicted, "
        "observed_at = strftime('%Y-%m-%dT%H:%M:%SZ','now')",
        (tag, data_id, to, predicted),
    )


def apply_due(c: sqlite3.Connection, now: str) -> list[dict]:
    """Apply every upgrade with finishes_at <= now (UTC ISO string). Returns the applied rows.

    DELETE ... RETURNING claims each row, so two overlapping calls cannot both apply it.
    """
    _begin(c)
    rows = c.execute("DELETE FROM upgrade WHERE finishes_at <= ? RETURNING *", (now,)).fetchall()
    out = [dict(r) for r in rows]
    for u in out:
        _move_count(c, u["tag"], u["data_id"], u["from_level"], u["from_level"] + 1, 1)
    return out


def start_upgrade(c: sqlite3.Connection, tag: str, data_id: int, from_level: int, facility: str,
                  finishes_at: str, source: str = "tap") -> int:
    """Start a timer; FacilityFull when the facility has no free slot."""
    if facility not in FACILITIES:
        raise ValueError(f"unknown facility {facility!r}")
    _begin(c)
    limit = 1
    if facility == "builder":
        row = c.execute("SELECT builders FROM account WHERE tag=?", (tag,)).fetchone()
        if row is None:
            raise ValueError(f"unknown account {tag!r}")
        limit = row["builders"]
    busy = c.execute("SELECT COUNT(*) FROM upgrade WHERE tag=? AND facility=?", (tag, facility)).fetchone()[0]
    if busy >= limit:
        raise FacilityFull(f"{facility} full ({busy}/{limit})")
    uid = c.execute(
        "INSERT INTO upgrade (tag, data_id, from_level, facility, finishes_at, source) VALUES (?,?,?,?,?,?)",
        (tag, data_id, from_level, facility, finishes_at, source),
    ).lastrowid
    notify_glue.scheduled({"tag": tag, "data_id": data_id, "from_level": from_level, "finishes_at": finishes_at})
    return uid


def edit_finish(c: sqlite3.Connection, upgrade_id: int, finishes_at: str, keep_boosts: bool = False) -> None:
    old = c.execute("SELECT * FROM upgrade WHERE id=?", (upgrade_id,)).fetchone()
    if not keep_boosts:  # a typed-in finish time is the truth; earlier boost windows no longer apply
        c.execute("DELETE FROM speedup WHERE upgrade_id=?", (upgrade_id,))
    cur = c.execute("UPDATE upgrade SET finishes_at=? WHERE id=?", (finishes_at, upgrade_id))
    if cur.rowcount == 0:
        raise LookupError(f"no upgrade {upgrade_id}")
    notify_glue.dropped(old)
    notify_glue.scheduled({**dict(old), "finishes_at": finishes_at})


def undo_upgrade(c: sqlite3.Connection, upgrade_id: int) -> None:
    old = c.execute("SELECT * FROM upgrade WHERE id=?", (upgrade_id,)).fetchone()
    c.execute("DELETE FROM upgrade WHERE id=?", (upgrade_id,))
    if old is not None:
        notify_glue.dropped(old)


def _work(wins: list, t0: float, t1: float) -> float:
    """Seconds of work done between t0 and t1 under the boost windows [(start, end, extra)]."""
    w = t1 - t0
    for a, b, x in wins:
        w += x * max(0.0, min(b, t1) - max(a, t0))
    return w


def _finish(wins: list, t0: float, work: float) -> float:
    """Time at which `work` seconds of work, started at t0, are done under the windows."""
    marks = sorted({t0, *(p for a, b, _ in wins for p in (a, b) if p > t0)})
    for a, b in zip(marks, marks[1:] + [float("inf")]):
        rate = 1 + sum(x for s, e, x in wins if s <= a and e >= b)
        if work <= rate * (b - a):
            return a + work / rate
        work -= rate * (b - a)
    return t0  # ponytail: unreachable, the last segment is open-ended


def speed_up(c: sqlite3.Connection, upgrade_id: int, rate: int, now: str, secs: int = 3600, kind: str = "") -> str:
    """Run one timer at `rate`x for `secs` from now (a potion, snack or helper). Stacked boosts add
    their extra rates (Potion 10x + Bite 2x = 11x); a second of the same kind runs after the first, as the
    game extends it. Returns the new finish."""
    kind = kind or f"x{rate}"
    row = c.execute("SELECT finishes_at FROM upgrade WHERE id=?", (upgrade_id,)).fetchone()
    if row is None:
        raise LookupError(f"no upgrade {upgrade_id}")
    t0 = parse(now).timestamp()
    rows = c.execute("SELECT * FROM speedup WHERE upgrade_id=? AND until > ?", (upgrade_id, now)).fetchall()
    wins = [(parse(r["starts_at"]).timestamp(), parse(r["until"]).timestamp(), r["extra"]) for r in rows]
    work = _work(wins, t0, max(t0, parse(row["finishes_at"]).timestamp()))
    s0 = max([t0] + [parse(r["until"]).timestamp() for r in rows if r["kind"] == kind])
    wins.append((s0, s0 + secs, rate - 1))
    fin = datetime.fromtimestamp(round(_finish(wins, t0, work)), timezone.utc).strftime(FMT)
    iso = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime(FMT)  # noqa: E731
    c.execute("INSERT INTO speedup (upgrade_id, kind, extra, starts_at, until) VALUES (?, ?, ?, ?, ?)",
              (upgrade_id, kind, rate - 1, iso(s0), iso(s0 + secs)))
    edit_finish(c, upgrade_id, fin, keep_boosts=True)
    return fin


def schedule(queue: list[dict], running: list[dict], builders: int, now: str) -> list[dict]:
    """Place queued items (in position order, each with facility and secs) on lanes. Lane i of a facility
    starts free at its i-th running upgrade's finish (running sorted by finishes_at, as the timeline draws
    them), or now; each item takes the lane that frees first. Returns the items with lane, start, end."""
    t0 = parse(now).timestamp()
    free = {}
    for f in FACILITIES:
        fins = sorted(max(t0, parse(u["finishes_at"]).timestamp()) for u in running if u["facility"] == f)
        n = max(builders, len(fins)) if f == "builder" else max(1, len(fins))
        free[f] = fins + [t0] * (n - len(fins))
    out = []
    iso = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime(FMT)  # noqa: E731
    for q in queue:
        lanes = free[q["facility"]]
        i = min(range(len(lanes)), key=lambda k: (lanes[k], k))
        s = lanes[i]
        lanes[i] = s + q["secs"]
        out.append({**q, "lane": i, "start": iso(s), "end": iso(lanes[i])})
    return out


def boost(c: sqlite3.Connection, tag: str, facility: str, rate: int, now: str, kind: str = "") -> int:
    """Speed up every running timer of one facility; returns how many moved."""
    ids = [r["id"] for r in c.execute("SELECT id FROM upgrade WHERE tag=? AND facility=? AND finishes_at > ?",
                                      (tag, facility, now))]
    for i in ids:
        speed_up(c, i, rate, now, kind=kind)
    return len(ids)
