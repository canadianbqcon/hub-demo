"""Canonical task store for the Hub home dashboard.

One table (data/tasks.db) is the source of truth. The work-planner markdown
files and any linked wiki/tasks/*.md nodes are projections regenerated from it,
and a linked Google Calendar event is edited in place on completion. Completing
or reopening a task anywhere propagates to all linked surfaces.

Spec: docs/archive/plans/2026-05-29-unified-task-sync.md

The module-level DB_PATH / PLANNER_MD / PLANNER_COMPLETED_MD / VAULT globals are
overridable (tests point them at temp files).
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# --- paths (overridable by tests) ---
_HUB = Path(__file__).resolve().parent
if str(_HUB.parent) not in sys.path:
    sys.path.insert(0, str(_HUB.parent))  # dashboard/, for vault_path
import sqlite_helpers
from vault_path import vault_root

logger = logging.getLogger(__name__)

VAULT = vault_root()
DB_PATH = VAULT / "data" / "tasks.db"
PLANNER_MD = VAULT / "wiki" / "notes" / "claude-work-planner.md"
PLANNER_COMPLETED_MD = VAULT / "wiki" / "notes" / "claude-work-planner-completed.md"

# Display names, in canonical planner order. Lowercase form is the stored `section`.
SECTION_NAMES = [
    "Loose Ends",
    "General",
    "Personal",
    "Work",
    "Setup & Workflow",
    "Dashboard",
    "Vault",
    "Claude Code & Skills",
    "Travel",
    "Explore",
    "Sorting",
]
SECTION_ORDER = {name.lower(): i for i, name in enumerate(SECTION_NAMES)}
_DISPLAY = {name.lower(): name for name in SECTION_NAMES}

_STOP_HEADERS = {"see also", "source basis"}


def _today() -> str:
    return date.today().isoformat()


def connect() -> sqlite3.Connection:
    """This thread's tasks.db connection, from the shared pool in sqlite_helpers.

    Was a fresh sqlite3.connect() plus the five-statement PRAGMA block on every
    call, and the home payload calls it eleven times — /api/home spent well over
    a tenth of a second opening connections to a database it already had open.
    The PRAGMA block moved with it: sqlite_helpers owns the canonical one and
    skips the expensive `journal_mode = WAL` write once the file is pinned.

    The ten callers below still say `con.close()` when they are done. That is now
    a no-op (see sqlite_helpers._Scoped) — the connection is released when the
    request ends, not when one query finishes with it.
    """
    return sqlite_helpers.scoped(DB_PATH, module="tasks")


def _ensure_indexes() -> None:
    """Codify the hot-path indexes the home page relies on (list_active/list_completed
    filter on `status`; sync_event() looks up rows by `cal_event_id` once per calendar
    event in the schedule-build loop). These already exist on current DBs but were
    created ad-hoc — defined in no migration or seed — so a DB rebuilt from
    seed_tasks.py would lose them. Re-creating them here from code is the safety net.
    Index NAMES match the established ones (idx_tasks_status, idx_tasks_cal) so this is
    a true no-op against existing DBs rather than creating duplicate indexes. tasks.db
    has no migration framework, so this runs at import; IF NOT EXISTS keeps it cheap.
    Guarded on the table existing so a pre-seed import on a fresh machine doesn't error.
    """
    con = connect()
    try:
        if con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tasks'"
        ).fetchone():
            con.executescript(
                "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);\n"
                "CREATE INDEX IF NOT EXISTS idx_tasks_cal ON tasks(cal_event_id);\n"
            )
    finally:
        con.close()


_ensure_indexes()


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _make_key(con: sqlite3.Connection, title: str) -> str:
    base = _slugify(title)[:32] or "task"
    for _ in range(50):
        key = f"{base}-{secrets.token_hex(2)}"
        if not con.execute("SELECT 1 FROM tasks WHERE task_key=?", (key,)).fetchone():
            return key
    return f"{base}-{secrets.token_hex(6)}"


def _calendar_key(con: sqlite3.Connection, title: str, eid: str) -> str:
    """Deterministic key for a calendar-sourced task: both machines' Hubs sync the
    same event and must mint the identical task_key, or a cross-machine merge sees
    two rows per event (the 2026-09-15 fork merge produced ten such pairs).
    Falls back to a random key only if the derived one is already taken by a
    different event."""
    base = _slugify(title)[:32] or "task"
    key = f"{base}-{hashlib.sha1(eid.encode(), usedforsecurity=False).hexdigest()[:4]}"
    taken = con.execute("SELECT cal_event_id FROM tasks WHERE task_key=?", (key,)).fetchone()
    if taken and taken[0] != eid:
        return _make_key(con, title)
    return key


def _due_target(due_date: str | None) -> str | None:
    """The instant a task's countdown runs out, as a local ISO datetime string the
    frontend can `new Date()`. Timed tasks (due_date carries a clock time) count
    down to that exact moment. Date-only deadlines count down to midnight at the
    END of the due day (00:00 the next day, local). None when there's no due_date.
    The frontend renders the live "Xd Yh" countdown from this; the server only
    fixes the target instant."""
    if not due_date:
        return None
    if "T" in due_date:
        return due_date  # already a full ISO datetime
    try:
        d = date.fromisoformat(due_date)
    except ValueError:
        return None
    end = datetime(d.year, d.month, d.day) + timedelta(days=1)  # next-day midnight
    return end.isoformat(timespec="seconds")


def _row_to_dict(r: sqlite3.Row) -> dict:
    """Shape a row for the dashboard API. `due_target` is the countdown target
    instant (None when no due_date); `timed` flags tasks with a clock time, which
    the panel groups into its top section. `group_label` clusters related tasks;
    `urgency` ('critical' | 'quickwin' | None) drives the triage chip;
    `input_level` ('none' | 'low' | 'high') drives the input pip."""
    return {
        "id": r["task_key"],
        "name": (r["title"] or "").lower(),
        "section": r["section"],
        "done": r["status"] == "done",
        "description": r["description"] or "",
        "blocked": bool(r["blocked"]),
        "group_label": r["group_label"] or "",
        "urgency": r["urgency"] or "",
        "input_level": r["input_level"] or "",
        "due_date": r["due_date"],
        "timed": bool(r["due_date"] and "T" in r["due_date"]),
        "due_target": _due_target(r["due_date"]),
        # The local YYYY-MM-DD the task was marked done (None while open). Lets the
        # briefing fold a completed task onto the day it was actually finished — the
        # "what I completed that day" view — independent of its due date.
        "completed_date": r["completed_date"],
    }


_URGENCY_VALUES = {"critical", "quickwin"}


def _norm_urgency(urgency) -> str | None:
    """Coerce an urgency input to a stored value: 'critical' | 'quickwin' | None.
    Anything else (None, '', 'none', a typo) clears it to None."""
    u = (urgency or "").strip().lower()
    return u if u in _URGENCY_VALUES else None


_INPUT_LEVELS = {"none", "low", "high"}


def _norm_input_level(input_level) -> str | None:
    """How much of Sam a task needs before Claude can finish it:
    'none' (zero questions), 'low' (up to 3), 'high' (full back-and-forth).
    Anything else coerces to None — untriaged, which the panel renders as a
    hollow pip so a missed triage is visible rather than silently green."""
    v = (input_level or "").strip().lower()
    return v if v in _INPUT_LEVELS else None


def _urgency_rank(urgency) -> int:
    """Within a cluster, float urgent work up: critical (0) -> quickwin (1) ->
    none (2). A high value-to-effort 'quickwin' sits just under must-do 'critical'."""
    if urgency == "critical":
        return 0
    return 1 if urgency == "quickwin" else 2


def _within_section_key(group_label, blocked, urgency, title):
    """Canonical within-section order: cluster by group (ungrouped first), then
    blocked sinks to the bottom of its cluster, then urgency floats up, then alpha."""
    return (
        (group_label or ""),
        1 if blocked else 0,
        _urgency_rank(urgency),
        (title or "").lower(),
    )


def _ordered(rows: list[sqlite3.Row]) -> list[dict]:
    out = [_row_to_dict(r) for r in rows]
    out.sort(
        key=lambda t: (
            SECTION_ORDER.get(t["section"], 99),
            *_within_section_key(
                t["group_label"], t["blocked"], t["urgency"], t["name"]
            ),
        )
    )
    return out


# --- reads ---


def list_active() -> list[dict]:
    con = connect()
    try:
        rows = con.execute("SELECT * FROM tasks WHERE status='open'").fetchall()
        return _ordered(rows)
    finally:
        con.close()


def list_completed() -> list[dict]:
    con = connect()
    try:
        rows = con.execute("SELECT * FROM tasks WHERE status='done'").fetchall()
        return _ordered(rows)
    finally:
        con.close()


def _get(con: sqlite3.Connection, task_key: str) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM tasks WHERE task_key=?", (task_key,)).fetchone()


# --- writes ---


def add(
    name: str,
    section: str = "general",
    description: str = "",
    blocked: bool = False,
    group_label: str | None = None,
    urgency: str | None = None,
    input_level: str | None = None,
    due_date: str | None = None,
    cal_event_id: str | None = None,
    cal_calendar_id: str | None = None,
    wiki_slug: str | None = None,
    source: str = "manual",
) -> dict:
    section = (section or "general").lower()
    group_label = (group_label or "").strip() or None
    urgency = _norm_urgency(urgency)
    input_level = _norm_input_level(input_level)
    con = connect()
    try:
        key = _make_key(con, name)
        con.execute(
            "INSERT INTO tasks (task_key, title, status, section, blocked, "
            "group_label, urgency, input_level, due_date, description, cal_event_id, "
            "cal_calendar_id, wiki_slug, source) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                key,
                name,
                "open",
                section,
                1 if blocked else 0,
                group_label,
                urgency,
                input_level,
                due_date,
                description,
                cal_event_id,
                cal_calendar_id,
                wiki_slug,
                source,
            ),
        )
        con.commit()
        row = _get(con, key)
    finally:
        con.close()
    regenerate()
    assert row is not None  # just inserted under this key
    return _row_to_dict(row)


def update(
    task_key: str,
    name: str | None = None,
    description: str | None = None,
    blocked: bool | None = None,
    section: str | None = None,
    group_label: str | None = None,
    urgency: str | None = None,
    input_level: str | None = None,
    **_ignored,
) -> bool:
    con = connect()
    try:
        if not _get(con, task_key):
            return False
        sets, vals = [], []
        if name is not None:
            sets.append("title=?")
            vals.append(name)
        if description is not None:
            sets.append("description=?")
            vals.append(description)
        if blocked is not None:
            sets.append("blocked=?")
            vals.append(1 if blocked else 0)
        if section is not None:
            sets.append("section=?")
            vals.append(section.lower())
        # group_label / urgency: an empty string is a deliberate clear (-> NULL),
        # so they update whenever the arg is not None.
        if group_label is not None:
            sets.append("group_label=?")
            vals.append(group_label.strip() or None)
        if urgency is not None:
            sets.append("urgency=?")
            vals.append(_norm_urgency(urgency))
        if input_level is not None:
            sets.append("input_level=?")
            vals.append(_norm_input_level(input_level))
        if not sets:
            return True
        sets.append("updated=datetime('now')")
        vals.append(task_key)
        con.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE task_key=?", vals)
        con.commit()
    finally:
        con.close()
    regenerate()
    return True


_LOOSE_END_RE = re.compile(r"^Loose End:\s*(\S+)\s*$", re.MULTILINE)


def park_pending(pending_path, label: str, note: str = "") -> dict:
    """Park a stranded .pending/ file into Loose Ends, at most once, ever.

    The park step is spec'd in `.claude/pending-spec.md` -> "Loose Ends
    carryover": a parked file carries a `Loose End: <task_key>` line and must
    never be re-parked. Enforcing that in prose failed twice -- a later scan
    read the file, missed the line, and called `add()` again, so the planner
    grew a second task nothing points at. (2026-08-28: two such orphans found
    and closed during a /reconcile sweep.) This routes every park through one
    place that reads the key first, so a duplicate is unreachable rather than
    merely discouraged.

    Returns the task dict either way. `created` says which happened, so a
    caller can tell a fresh park from a no-op without diffing the planner.
    """
    path = Path(pending_path)
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    existing = _LOOSE_END_RE.search(text)
    if existing:
        key = existing.group(1)
        con = connect()
        try:
            row = _get(con, key)
        finally:
            con.close()
        if row is not None:
            out = _row_to_dict(row)
            out["created"] = False
            return out
        # The key names a task that no longer exists -- the user discarded it.
        # Per the spec's cleanup check that is a discard, not an invitation to
        # re-park, so say so rather than quietly making a new one.
        raise ValueError(
            f"{path.name} is parked against task {key!r}, which is gone from the "
            "planner. That is a discard per pending-spec's cleanup check: delete "
            "the parked file, do not re-park it."
        )

    task = add(label, section="loose ends", description=note, source="park")
    stamped = text
    if "Loose End:" not in stamped:
        stamped = stamped.rstrip("\n") + f"\n\nLoose End: {task['id']}\n"
    stamped = re.sub(
        r"^(\*?\*?Status:?\*?\*?)\s*.*$",
        lambda m: f"{m.group(1)} parked",
        stamped,
        count=1,
        flags=re.MULTILINE,
    )
    if path.exists():
        path.write_text(stamped, encoding="utf-8")
    task["created"] = True
    return task


def delete(task_key: str, **_ignored) -> bool:
    """Remove the task row. Does NOT delete the linked calendar event or wiki
    node (matches legacy delete semantics — only drops the planner entry)."""
    con = connect()
    try:
        if not _get(con, task_key):
            return False
        con.execute("DELETE FROM tasks WHERE task_key=?", (task_key,))
        con.commit()
    finally:
        con.close()
    regenerate()
    return True


def complete(task_key: str) -> bool:
    con = connect()
    try:
        row = _get(con, task_key)
        if not row:
            return False
        if row["status"] == "done":
            return True
        today = _today()
        con.execute(
            "UPDATE tasks SET status='done', completed_date=?, updated=datetime('now') "
            "WHERE task_key=?",
            (today, task_key),
        )
        con.commit()
        cal_event_id, cal_calendar_id, wiki_slug = (
            row["cal_event_id"],
            row["cal_calendar_id"],
            row["wiki_slug"],
        )
    finally:
        con.close()

    if cal_event_id:
        _safe_cal(
            lambda g: g.mark_event_complete(
                cal_event_id, cal_calendar_id or "primary", today
            )
        )
    if wiki_slug:
        _flip_wiki_status(wiki_slug, done=True, when=today)
    # The engine never writes a recap line. Sam routinely clears stale tasks
    # that were finished days/weeks ago but never ticked off; stamping those
    # into *today's* daily-recap.md misreported them as done today. Completion
    # IS a recap event (a finished job leaves the due list for the recap card —
    # see briefing.logic.js::selectDueItemsForDay), but the line is written by
    # the /todo skill, which can judge whether the work was finished now and can
    # rewrite it as a real summary instead of the bare title. See log/log.md
    # 2026-07-24 and 2026-07-29.
    regenerate()
    return True


def reopen(task_key: str) -> bool:
    con = connect()
    try:
        row = _get(con, task_key)
        if not row:
            return False
        if row["status"] == "open":
            return True
        con.execute(
            "UPDATE tasks SET status='open', completed_date=NULL, updated=datetime('now') "
            "WHERE task_key=?",
            (task_key,),
        )
        con.commit()
        cal_event_id, cal_calendar_id, wiki_slug = (
            row["cal_event_id"],
            row["cal_calendar_id"],
            row["wiki_slug"],
        )
    finally:
        con.close()

    if cal_event_id:
        _safe_cal(
            lambda g: g.unmark_event_complete(
                cal_event_id, cal_calendar_id or "primary"
            )
        )
    if wiki_slug:
        _flip_wiki_status(wiki_slug, done=False, when=None)
    regenerate()
    return True


# --- schedule integration ---


def sync_event(event: dict) -> dict | None:
    """Given a calendar event dict (from gcal.fetch_week_events), return the
    linked task's {task_key, done} so the schedule can render a real checkbox.
    Every Tomato (colorId 11) event is a completable task — all-day deadlines and
    timed ones alike (timed deadlines, interviews, appointments). The schedule
    renders all-day tasks at the top of the day and timed tasks in their slot.
    Creates a row the first time an unseen task event is seen."""
    eid = event.get("id", "")
    if not eid:
        return None
    is_task = event.get("color_id") == "11"
    if not is_task:
        return None
    # All-day events store a date; timed ones keep the full datetime so the panel
    # can render the countdown + group them (see _due_target).
    start_dt = event.get("start_dt") or ""
    due = (start_dt[:10] if event.get("all_day") else start_dt) or None
    con = connect()
    due_changed = False
    try:
        row = con.execute("SELECT * FROM tasks WHERE cal_event_id=?", (eid,)).fetchone()
        if row:
            link = {"task_key": row["task_key"], "done": row["status"] == "done"}
            # Reconcile a moved deadline: when the calendar event's time is edited
            # the linked row's due_date must follow so the chip/planner aren't stale.
            if due != row["due_date"]:
                con.execute(
                    "UPDATE tasks SET due_date=?, updated=datetime('now') "
                    "WHERE cal_event_id=?",
                    (due, eid),
                )
                con.commit()
                due_changed = True
        else:
            key = _calendar_key(con, event.get("summary", "task"), eid)
            con.execute(
                "INSERT INTO tasks (task_key, title, status, section, due_date, "
                "cal_event_id, cal_calendar_id, source) VALUES (?,?,?,?,?,?,?,?)",
                (
                    key,
                    event.get("summary", "task"),
                    "open",
                    "general",
                    due,
                    eid,
                    event.get("calendar_id", "primary"),
                    "calendar",
                ),
            )
            con.commit()
            link = {"task_key": key, "done": False}
    finally:
        con.close()
    if due_changed:
        regenerate()  # rewrite the planner mirror with the new time
    return link


# --- calendar + wiki propagation helpers ---


def _safe_cal(fn) -> None:
    # Best-effort calendar mirror: tasks.db is authoritative and the calendar
    # checkmark is a cosmetic projection, so a sync failure must never break task
    # completion — hence the catch-all. complete() commits the task done *before*
    # calling this, so log the failure to stderr rather than swallow it: a
    # checkmark that never lands (expired token, network, API error) would
    # otherwise be undiagnosable.
    try:
        import gcal

        if gcal.is_authenticated():
            fn(gcal)
    except Exception as exc:
        logger.warning("calendar sync skipped: %s", exc)


def _flip_wiki_status(wiki_slug: str, done: bool, when: str | None) -> None:
    """Flip a wiki/tasks/<slug>.md node's ## Status block and bump frontmatter updated."""
    try:
        path = VAULT / f"{wiki_slug}.md"
        if not path.exists():
            return
        text = path.read_text(encoding="utf-8")
        new_status = f"Done — completed {when}" if done else "Open"
        # Replace the body of the ## Status section (up to the next ## heading).
        text2 = re.sub(
            r"(## Status\s*\n\n).*?(\n\n## )",
            lambda m: m.group(1) + new_status + m.group(2),
            text,
            count=1,
            flags=re.DOTALL,
        )
        text2 = re.sub(
            r"(?m)^updated: \d{4}-\d{2}-\d{2}.*$",
            f"updated: {_today()}",
            text2,
            count=1,
        )
        if text2 != text:
            path.write_text(text2, encoding="utf-8")
    except Exception:
        logger.exception("wiki status flip failed for %s", wiki_slug)


# --- planner markdown regeneration (projection) ---


_URGENCY_TAG = {"critical": "[critical]", "quickwin": "[quick win]"}


def _bullet(t: sqlite3.Row, done: bool) -> str:
    prefix = f"[[{t['wiki_slug']}]] — " if t["wiki_slug"] else ""
    box = "[x]" if done else "[ ]"
    line = f"- {box} {prefix}{t['title']}"
    tag = _URGENCY_TAG.get(t["urgency"] or "")
    if tag and not done:
        line += f" {tag}"
    if done and t["completed_date"]:
        line += f" completed {t['completed_date']}"
    # A description is planning context: what the task is and why it matters. It
    # earns its place while the task is open and stops earning it the moment the
    # task is done, so the completed mirror renders titles only. Measured
    # 2026-08-26: descriptions were 19,462 of the completed file's 22,321 words,
    # enough that it outranked real notes in almost every vault search. Dropped at
    # render time rather than cleared in the database, so reopen() still restores
    # the context and nothing is destroyed. The database is binary and never
    # matches a text search, so deleting the rows would buy nothing.
    desc = "" if done else (t["description"] or "").strip()
    if t["blocked"] and desc and not desc.lower().startswith("blocked"):
        desc = ("Blocked. " + desc).strip()
    out = [line]
    if desc:
        out.append(f"  - {desc}")
    return "\n".join(out)


def _render_sections(rows: list[sqlite3.Row], done: bool) -> str:
    by_section: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        by_section.setdefault(r["section"], []).append(r)
    for sec in by_section:
        by_section[sec].sort(
            key=lambda r: _within_section_key(
                r["group_label"], r["blocked"], r["urgency"], r["title"]
            )
        )

    blocks = []
    for name in SECTION_NAMES:
        sec = name.lower()
        blocks.append(f"## {name}\n")
        items = by_section.get(sec, [])
        if not items:
            blocks.append("")
            blocks.append("*No tasks yet.*" if not done else "*No completed tasks.*")
            blocks.append("")
            continue
        blocks.append("")
        # The sort clusters ungrouped tasks first, then each group's tasks
        # contiguously. Emit a bold sub-header when the group label changes, so
        # related multi-part work reads as a labelled block.
        current_group = None
        for r in items:
            g = r["group_label"] or ""
            if g != current_group:
                current_group = g
                if g:
                    blocks.append("")
                    blocks.append(f"**{g}**")
            blocks.append(_bullet(r, done))
        blocks.append("")
    return "\n".join(blocks).rstrip() + "\n"


def _find_first_section(lines: list[str]) -> int | None:
    """Index of the first real section heading (past any stop header)."""
    for i, ln in enumerate(lines):
        m = re.match(r"^## (.+)$", ln)
        if m and m.group(1).strip().lower() not in _STOP_HEADERS:
            return i
    return None


def _find_postamble_start(lines: list[str]) -> int:
    """Index where the See also postamble begins (including its preceding
    '---' separator, if any), or len(lines) if there is no See also section."""
    see_also = None
    for i, ln in enumerate(lines):
        if re.match(r"^## See also\s*$", ln):
            see_also = i
            break
    if see_also is None:
        return len(lines)
    j = see_also - 1
    while j >= 0 and lines[j].strip() == "":
        j -= 1
    return j if (j >= 0 and lines[j].strip() == "---") else see_also


def _bump_updated(preamble: list[str]) -> list[str]:
    return [
        re.sub(r"^updated: \d{4}-\d{2}-\d{2}.*$", f"updated: {_today()}", ln)
        if ln.startswith("updated:")
        else ln
        for ln in preamble
    ]


def _rewrite_planner(path: Path, rows: list[sqlite3.Row], done: bool) -> None:
    """Rewrite only the section bodies, preserving frontmatter/intro (preamble)
    and the See also / Source basis footer (postamble)."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    first_sec = _find_first_section(lines)
    if first_sec is None:
        return
    post_start = _find_postamble_start(lines)

    preamble = _bump_updated(lines[:first_sec])
    postamble = lines[post_start:]

    middle = _render_sections(rows, done)
    pre = "\n".join(preamble).rstrip() + "\n\n"
    post = ("\n" + "\n".join(postamble).lstrip("\n")) if postamble else ""
    content = pre + middle + post
    if not content.endswith("\n"):
        content += "\n"
    path.write_text(content, encoding="utf-8")


def regenerate() -> None:
    con = connect()
    try:
        active = con.execute("SELECT * FROM tasks WHERE status='open'").fetchall()
        done = con.execute("SELECT * FROM tasks WHERE status='done'").fetchall()
    finally:
        con.close()
    _rewrite_planner(PLANNER_MD, active, done=False)
    _rewrite_planner(PLANNER_COMPLETED_MD, done, done=True)
