from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from sqlite_helpers import connect as sqlite_connect

# Barback reads the J&Co work store. work.db is NOT owned by this module: its
# schema lives in db/migrations/work/ (warehouse contract). This module only
# opens connections and queries; it never CREATEs or migrates. It owns the
# checklist_* and stock_raw_item tables added by migration 014.
_db_path: Path | None = None

BAR_DAY_OFFSET_HOURS = 5  # "today" rolls at 05:00 local, not midnight.


def init(db_path: Path) -> None:
    """Point the module at work.db. Called once at app startup with data/work.db."""
    global _db_path
    if not db_path.exists():
        raise FileNotFoundError(
            f"work.db not found at {db_path}; run db/migrate.py up work"
        )
    _db_path = db_path


def _conn():
    return sqlite_connect(_db_path, "barback.db")


def bar_date(now: datetime) -> str:
    """The bar-day ISO date for a wall-clock instant. Rolls at 05:00 local."""
    return (now - timedelta(hours=BAR_DAY_OFFSET_HOURS)).date().isoformat()


# The day-of-week CADENCE constant lived here until 2026-07-29. It fed a weekday
# strip in a UI that no longer asks what day it is, and every rule it held (ghost
# ice Tue/Thu/Sat, the downstairs-clean deadlines, Tuesday's condense-juice and
# soak-bottle-covers) is recorded in the vault in more detail than it carried —
# wiki/notes/jc-staff-policies "Recurring cadences", jc-closing-duties,
# jc-barback-trainer. So it was deleted rather than kept as unread config.


# ── Stock check item generation ────────────────────────────────────────────────
# Built at run start from two sources: every made item in work.db (batch + prep,
# grouped by category) and the seeded raw goods. Display aliases let a stored
# recipe name show under a friendlier label on the stock list.
STOCK_ALIASES = {
    "Boba H2O": "Boba foam",
}


def generate_stock_items() -> list[dict]:
    """The stock-check item set: made items (batch+prep) then raw goods.

    Each item is {text, detail, section, deadline, priority}; section is the
    category so the frontend can group. New recipes appear automatically — this
    is the structural guarantee against missing a made item.
    """
    items: list[dict] = []
    with _conn() as conn:
        made = conn.execute(
            "SELECT name, category FROM recipes "
            "WHERE kind IN ('batch','prep') "
            "ORDER BY category COLLATE NOCASE, name COLLATE NOCASE"
        ).fetchall()
        raws = conn.execute(
            "SELECT name, category FROM stock_raw_item ORDER BY sort_order, id"
        ).fetchall()
    for r in made:
        items.append({
            "text": STOCK_ALIASES.get(r["name"], r["name"]),
            "detail": "",
            "section": r["category"] or "Other",
            "deadline": "",
            "priority": "",
        })
    for r in raws:
        items.append({
            "text": r["name"],
            "detail": "",
            "section": r["category"],
            "deadline": "",
            "priority": "",
        })
    return items


# ── Run lifecycle ──────────────────────────────────────────────────────────────
# Template -> run snapshot: starting a run copies the current template items (or,
# for stock, the generated set) into checklist_run_item. A run is then frozen, so
# editing a template or re-seeding never rewrites an in-flight run.
_DUTY_STATES = {"open", "done"}
_STOCK_STATES = {"open", "good", "low", "out"}
# fill: the state IS the count of units to grab. Tapping a row adds one; it does
# NOT wrap back to 0 (2026-08-16 — wrapping at 3 meant a row needing 8 was
# untappable, and walking one down to 0 took three more taps). Clearing is an
# explicit action instead: the row's own clear, or "clear all" on the run.
# Stored in the same TEXT column as the other two machines — the cap keeps it a
# finite state machine, so no extra column and no schema change.
_FILL_MAX = 99
_FILL_STATES = {str(n) for n in range(_FILL_MAX + 1)}
_OPEN = "open"
_ZERO = "0"

_STATES_BY_KIND = {"stock": _STOCK_STATES, "fill": _FILL_STATES}
# Resting state a fresh snapshot starts in: nothing walked yet (duty/stock), or
# nothing to grab yet (fill).
_RESTING_BY_KIND = {"fill": _ZERO}


def _states_for_kind(kind: str) -> set[str]:
    return _STATES_BY_KIND.get(kind, _DUTY_STATES)


def _resting_for_kind(kind: str) -> str:
    return _RESTING_BY_KIND.get(kind, _OPEN)


def next_fill_state(state: str) -> str:
    """Tap adds one, clamped at _FILL_MAX. Never wraps — clearing is explicit.
    Anything unrecognized starts the count at 1, since the tap meant 'add one'."""
    try:
        return str(min(int(state) + 1, _FILL_MAX))
    except (TypeError, ValueError):
        return "1"


def clear_fill_run(run_id: int) -> int:
    """Zero every row in a fill run. One statement instead of N per-item PUTs,
    so a 40-row low boy clears in a single trip. Returns rows actually changed.
    Fill-only: zeroing a duty or stock run would wipe the shift's progress."""
    with _conn() as conn:
        if _kind_for_run(conn, run_id) != "fill":
            raise ValueError(f"run {run_id} is not a fill run")
        cur = conn.execute(
            "UPDATE checklist_run_item SET state=?, state_at=? "
            "WHERE run_id=? AND state<>?",
            (_ZERO, datetime.now().isoformat(timespec="seconds"), run_id, _ZERO),
        )
        _refresh_completed(conn, run_id)
        return cur.rowcount


def _template_by_key(conn, key: str):
    return conn.execute(
        "SELECT id, key, name, kind FROM checklist_template WHERE key=?", (key,)
    ).fetchone()


def _run_dict(conn, run_id: int) -> dict | None:
    run = conn.execute(
        "SELECT r.id, r.bar_date, r.status, r.completed_at, "
        "       t.key AS template_key, t.name, t.kind "
        "FROM checklist_run r JOIN checklist_template t ON t.id=r.template_id "
        "WHERE r.id=?",
        (run_id,),
    ).fetchone()
    if run is None:
        return None
    items = conn.execute(
        "SELECT id, text_snapshot AS text, detail_snapshot AS detail, section, "
        "       deadline, priority, state, state_at, sort_order "
        "FROM checklist_run_item WHERE run_id=? ORDER BY sort_order, id",
        (run_id,),
    ).fetchall()
    out = dict(run)
    out["items"] = [dict(i) for i in items]
    return out


def _snapshot_items(conn, run_id: int, template) -> None:
    """Copy the template's items (or generated stock set) into the run, frozen."""
    if template["kind"] == "stock":
        rows = [
            (it["text"], it["detail"], it["section"], it["deadline"], it["priority"])
            for it in generate_stock_items()
        ]
    else:
        tpl_items = conn.execute(
            "SELECT text, detail, section, deadline, priority "
            "FROM checklist_template_item WHERE template_id=? ORDER BY sort_order, id",
            (template["id"],),
        ).fetchall()
        rows = [
            (r["text"], r["detail"], r["section"], r["deadline"], r["priority"])
            for r in tpl_items
        ]
    resting = _resting_for_kind(template["kind"])
    for i, (text, detail, section, deadline, priority) in enumerate(rows):
        conn.execute(
            "INSERT INTO checklist_run_item "
            "(run_id, text_snapshot, detail_snapshot, section, deadline, priority, "
            " state, sort_order) VALUES (?,?,?,?,?,?,?,?)",
            (run_id, text, detail, section, deadline, priority, resting, i),
        )


def _archive_stale_runs(conn, today: str) -> None:
    """Close out any run left active on an earlier bar-day. Partial item states are
    preserved, so an archived run with any 'open' item still reads as incomplete."""
    conn.execute(
        "UPDATE checklist_run SET status='archived' "
        "WHERE status='active' AND bar_date < ?",
        (today,),
    )


def start_run(template_key: str, now: datetime) -> dict:
    """Resume the active run for (template_key, today's bar_date), else create it.

    Fires lazy archival first. That used to hang off the Today summary read, which
    is gone — archival belongs to any touch of the run layer, not to one endpoint.
    """
    bd = bar_date(now)
    with _conn() as conn:
        _archive_stale_runs(conn, bd)
        template = _template_by_key(conn, template_key)
        if template is None:
            raise ValueError(f"unknown template key: {template_key}")
        existing = conn.execute(
            "SELECT id FROM checklist_run "
            "WHERE template_id=? AND bar_date=? AND status='active'",
            (template["id"], bd),
        ).fetchone()
        if existing is not None:
            resumed = _run_dict(conn, existing["id"])
            assert resumed is not None  # id was just read in this txn; row exists
            return resumed
        cur = conn.execute(
            "INSERT INTO checklist_run (template_id, bar_date, started_at, status) "
            "VALUES (?,?,?, 'active')",
            (template["id"], bd, now.isoformat(timespec="seconds")),
        )
        run_id = cur.lastrowid
        assert run_id is not None  # SQLite always assigns a rowid on a successful INSERT
        _snapshot_items(conn, run_id, template)
        created = _run_dict(conn, run_id)
        assert created is not None  # row was just inserted; cannot be missing
        return created


def get_run(run_id: int) -> dict | None:
    with _conn() as conn:
        return _run_dict(conn, run_id)


def set_item_state(item_id: int, state: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT ri.run_id, t.kind FROM checklist_run_item ri "
            "JOIN checklist_run r ON r.id=ri.run_id "
            "JOIN checklist_template t ON t.id=r.template_id WHERE ri.id=?",
            (item_id,),
        ).fetchone()
        if row is None:
            return None
        valid = _states_for_kind(row["kind"])
        if state not in valid:
            raise ValueError(f"invalid state {state!r} for kind {row['kind']!r}")
        conn.execute(
            "UPDATE checklist_run_item SET state=?, state_at=? WHERE id=?",
            (state, datetime.now().isoformat(timespec="seconds"), item_id),
        )
        _refresh_completed(conn, row["run_id"])
        item = conn.execute(
            "SELECT id, text_snapshot AS text, detail_snapshot AS detail, section, "
            "       deadline, priority, state, state_at, sort_order "
            "FROM checklist_run_item WHERE id=?",
            (item_id,),
        ).fetchone()
        return dict(item)


def _kind_for_run(conn, run_id: int) -> str:
    row = conn.execute(
        "SELECT t.kind FROM checklist_run r JOIN checklist_template t ON t.id=r.template_id "
        "WHERE r.id=?",
        (run_id,),
    ).fetchone()
    return row["kind"] if row else "duty"


def _refresh_completed(conn, run_id: int) -> None:
    """Set completed_at when every item has left 'open', clear it otherwise.

    A fill run is a survey, not a checklist — its rows rest at "0" and never
    leave an 'open' state, so completion does not apply and is never stamped.
    """
    if _kind_for_run(conn, run_id) == "fill":
        return
    open_left = conn.execute(
        "SELECT COUNT(*) FROM checklist_run_item WHERE run_id=? AND state=?",
        (run_id, _OPEN),
    ).fetchone()[0]
    if open_left == 0:
        conn.execute(
            "UPDATE checklist_run SET completed_at=? WHERE id=? AND completed_at IS NULL",
            (datetime.now().isoformat(timespec="seconds"), run_id),
        )
    else:
        conn.execute(
            "UPDATE checklist_run SET completed_at=NULL WHERE id=?", (run_id,)
        )


# ── Low boy grab sweep ─────────────────────────────────────────────────────────
# A restock is walked one AREA at a time: clear everything the front room owes you
# before going anywhere else, instead of front-back-front-side. Locations come from
# ingredient_location (seeded off the storage map by seed_lowboy_location.py); this
# constant is the only thing that groups those shelf-level locations into the
# coarse areas you actually walk between.
#
# Area order follows the storage map's own heading order — it is NOT a claim about
# which room is physically closest. Reorder _SWEEP_ORDER if the real walk differs;
# it stays a Python config constant rather than a table because it changes a few
# times a year and a DB table would be schema + migration overhead for that.
# Every prefix a location string in seed_lowboy_location.py can start with has to
# appear here or the product silently falls to Unsorted, which is indistinguishable
# from never having been placed. Four did exactly that between 2026-08-17 and
# 2026-09-02: "Keg fridge" (the rename of "Back fridge"), "Back rack",
# "Front freezer shelf" and, briefly, "Alcohol drawer" — 18 placed products walked
# as unplaced. Regression: test_every_seeded_location_maps_to_a_walk_area.
_AREA_BY_PREFIX = {
    "Back fridge": "Front room",
    "Keg fridge": "Front room",
    "Right fridge": "Front room",
    "Left fridge": "Front room",
    "Lowboy": "Back room",
    "Left metal shelf": "Back room",
    "Right metal shelf": "Back room",
    "Kitchen table": "Back room",
    "Overhead shelf": "Back room",
    "Back rack": "Back room",
    "Freezer": "Freezer",
    "Front freezer shelf": "Freezer",
    "Alcohol room": "Alcohol room",
    "Bar well": "Bar",
    "Alcohol drawer": "Bar",
}
_SWEEP_ORDER = ["Front room", "Back room", "Freezer", "Alcohol room", "Bar"]
_UNSORTED = "Unsorted"


def _area_for(location: str | None) -> str:
    """Coarse walkable area for a shelf-level location. Unknown -> Unsorted."""
    if not location:
        return _UNSORTED
    head = location.split("·")[0].strip()
    return _AREA_BY_PREFIX.get(head, _UNSORTED)


def grab_sweep(run_id: int) -> dict:
    """Everything this fill run says to grab, grouped by area then by shelf.

    Unplaced products are not dropped and not guessed at — they collect under an
    explicit Unsorted area, which is the signal that seed_lowboy_location.py needs
    a row for them.
    """
    with _conn() as conn:
        rows = conn.execute(
            "SELECT ri.id AS item_id, ri.text_snapshot AS text, "
            "       ri.detail_snapshot AS detail, "
            "       ri.section, ri.state, il.location "
            "FROM checklist_run_item ri "
            "LEFT JOIN ingredient_location il ON il.name = ri.text_snapshot "
            # CAST, not an IN-list: the list used to be ('1','2','3') and silently
            # dropped every count above 3 from the grab list once tapping stopped
            # wrapping at 3. CAST also reads any stale 'done'/'open' row as 0.
            "WHERE ri.run_id=? AND CAST(ri.state AS INTEGER) > 0 "
            "ORDER BY ri.sort_order, ri.id",
            (run_id,),
        ).fetchall()

    areas: dict[str, dict] = {}
    for r in rows:
        area = _area_for(r["location"])
        stop = r["location"] or "Not on the storage map"
        bucket = areas.setdefault(area, {"area": area, "stops": {}, "units": 0})
        entry = bucket["stops"].setdefault(stop, {"location": stop, "items": []})
        entry["items"].append({
            # item_id addresses the run row, so the sweep can clear a line
            # straight from the grab list (PUT /run/item/<id> state '0').
            "item_id": r["item_id"],
            "text": r["text"],
            "detail": r["detail"] or "",
            "section": r["section"],
            "count": int(r["state"]),
        })
        bucket["units"] += int(r["state"])

    order = {name: i for i, name in enumerate(_SWEEP_ORDER)}
    ordered = sorted(areas.values(), key=lambda a: (order.get(a["area"], 98)
                                                    if a["area"] != _UNSORTED else 99,
                                                    a["area"]))
    for a in ordered:
        a["stops"] = sorted(a["stops"].values(), key=lambda s: s["location"])
    return {
        "areas": ordered,
        "units": sum(a["units"] for a in ordered),
        "rows": len(rows),
    }


# ── Stock Low/Out summary ──────────────────────────────────────────────────────
def lowout_summary(run_id: int) -> dict:
    """Report-ready Low/Out lists + text for the WhatsApp 'low not out' rule."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT text_snapshot AS text, state FROM checklist_run_item "
            "WHERE run_id=? ORDER BY sort_order, id",
            (run_id,),
        ).fetchall()
    low = [r["text"] for r in rows if r["state"] == "low"]
    out = [r["text"] for r in rows if r["state"] == "out"]
    if not low and not out:
        text = "Stock check: all stocked, nothing low or out."
    else:
        lines = []
        if out:
            lines.append("Out:")
            lines.extend(f"  - {n}" for n in out)
        if low:
            lines.append("Low:")
            lines.extend(f"  - {n}" for n in low)
        text = "\n".join(lines)
    return {"low": low, "out": out, "text": text}
