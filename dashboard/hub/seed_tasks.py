"""One-time idempotent seed for data/tasks.db.

Imports the two work-planner markdown files into task rows so the canonical
table mirrors what the planner already shows. Safe to re-run: rows are matched
by (source='planner-import', section, normalized title) and updated in place
rather than duplicated.

Scope (per the 2026-05-29 unified-task-sync handoff's next-action):
  1. parse claude-work-planner.md (open) + -completed.md (done) -> rows
  2. capture the first inline [[...]] wikilink on a line -> wiki_slug
  3. match all-day Tomato (colorId 11) calendar events by title -> cal_event_id
     (link an EXISTING row only; never fabricates a row from the calendar)

Deliberately out of scope (follow-up, plan section 6): scanning wiki/tasks/*.md
for orphan nodes that aren't in either planner (e.g. fix-unemployment-certification,
cancel-chatgpt). Those become rows later via a reviewable reconciliation pass, or
lazily via tasks.sync_event() when an unmatched all-day Tomato event renders on the
schedule. Seeding only the planner keeps regenerate() a faithful round-trip and
avoids dumping calendar noise into the planner markdown.

Run: python3 dashboard/hub/seed_tasks.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))  # dashboard/hub/ -> tasks.py
sys.path.insert(0, str(_HERE.parent))  # dashboard/        -> gcal.py
import tasks  # engine: connect(), _make_key(), PLANNER_MD / PLANNER_COMPLETED_MD

_WIKILINK = re.compile(r"\[\[([^\]]+?)\]\]")
_COMPLETED_DATE = re.compile(r"\s+completed\s+(\d{4}-\d{2}-\d{2})\s*$")
_COMPLETED_BARE = re.compile(r"\s+completed\s*$")
_URGENCY_TAG = re.compile(r"\s*\[(critical|quick win)\]\s*$", re.IGNORECASE)
_STOP_HEADERS = {"see also", "source basis"}


def _task_fields(raw: str) -> tuple[str, str | None, str | None, str | None]:
    """One bullet's raw text -> (title, wiki_slug, urgency, completed_date)."""
    wl = _WIKILINK.search(raw)
    wiki_slug = wl.group(1).strip() if wl else None

    # Strip the wikilink + its separator, mirroring the legacy parser, so the
    # stored title matches what regenerate() will re-emit as the bullet text.
    name = re.sub(r"\[\[.*?\]\]\s*[—-]?\s*", "", raw).strip()

    # Pull the trailing urgency tag ([critical] / [quick win]) off the title.
    urgency = None
    um = _URGENCY_TAG.search(name)
    if um:
        urgency = "critical" if um.group(1).lower() == "critical" else "quickwin"
        name = name[: um.start()].strip()

    completed_date = None
    dm = _COMPLETED_DATE.search(name)
    if dm:
        completed_date = dm.group(1)
        name = name[: dm.start()].strip()
    else:
        name = _COMPLETED_BARE.sub("", name).strip()

    return name, wiki_slug, urgency, completed_date


def _description_lines(lines: list[str], start: int) -> tuple[str, int]:
    """Indented "  - text" lines following a task bullet -> (joined description,
    index of the first line after them)."""
    parts = []
    j = start
    while j < len(lines):
        sub = re.match(r"^  - (.+)", lines[j])
        if not sub:
            break
        parts.append(sub.group(1).strip())
        j += 1
    return " ".join(parts), j


def _parse(path: Path, done: bool) -> list[dict]:
    """Parse one planner file into row dicts. Mirrors the legacy _parse_planner
    (app.py:179) but keeps the wikilink (as wiki_slug), the original title case,
    and the trailing completion date."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []

    task_pat = re.compile(r"- \[x\] (.+)" if done else r"- \[ \] (.+)")
    group_pat = re.compile(r"^\*\*(.+?)\*\*\s*$")
    rows: list[dict] = []
    section: str | None = None
    group: str | None = None

    i = 0
    while i < len(lines):
        line = lines[i]

        hm = re.match(r"^## (.+)$", line)
        if hm:
            header = hm.group(1).strip()
            if header.lower() in _STOP_HEADERS:
                break
            section = header.lower()
            group = None  # group sub-headers are scoped to their section
            i += 1
            continue

        if section is None:
            i += 1
            continue

        gm = group_pat.match(line)
        if gm:
            group = gm.group(1).strip() or None
            i += 1
            continue

        tm = task_pat.match(line)
        if not tm:
            i += 1
            continue

        raw = tm.group(1)
        name, wiki_slug, urgency, completed_date = _task_fields(raw)

        if not name:
            i += 1
            continue

        # Indented "  - text" lines are the task's description.
        desc, j = _description_lines(lines, i + 1)

        rows.append(
            {
                "section": section,
                "title": name,
                "wiki_slug": wiki_slug,
                "description": desc,
                "blocked": 1 if desc.lower().startswith("blocked") else 0,
                "group_label": group,
                "urgency": urgency,
                "completed_date": completed_date,
                "status": "done" if done else "open",
            }
        )
        i = j

    return rows


def _upsert(con, r: dict) -> tuple[str, str]:
    """Insert or update one planner row. Idempotent on (source, section, title)."""
    norm = r["title"].strip().lower()
    existing = con.execute(
        "SELECT id, task_key FROM tasks "
        "WHERE source='planner-import' AND section=? AND lower(title)=?",
        (r["section"], norm),
    ).fetchone()

    if existing:
        con.execute(
            "UPDATE tasks SET title=?, status=?, blocked=?, group_label=?, urgency=?, "
            "description=?, wiki_slug=?, completed_date=?, updated=datetime('now') "
            "WHERE id=?",
            (
                r["title"],
                r["status"],
                r["blocked"],
                r["group_label"],
                r["urgency"],
                r["description"],
                r["wiki_slug"],
                r["completed_date"],
                existing["id"],
            ),
        )
        return "updated", existing["task_key"]

    key = tasks._make_key(con, r["title"])
    con.execute(
        "INSERT INTO tasks (task_key, title, status, section, blocked, group_label, "
        "urgency, description, wiki_slug, completed_date, source) "
        "VALUES (?,?,?,?,?,?,?,?,?,?, 'planner-import')",
        (
            key,
            r["title"],
            r["status"],
            r["section"],
            r["blocked"],
            r["group_label"],
            r["urgency"],
            r["description"],
            r["wiki_slug"],
            r["completed_date"],
        ),
    )
    return "created", key


def _link_calendar(con) -> tuple[list[tuple[str, str]], str]:
    """Link all-day Tomato calendar events to existing open rows by title.
    Never creates a row. Returns (linked pairs, status message)."""
    try:
        import gcal

        if not gcal.is_authenticated():
            return [], "calendar: skipped (not authenticated)"
    except Exception as e:  # noqa: BLE001 - any import/auth failure is non-fatal
        return [], f"calendar: skipped (gcal unavailable: {e})"

    try:
        events = gcal.fetch_week_events(days=200)
    except Exception as e:  # noqa: BLE001
        return [], f"calendar: skipped (fetch failed: {e})"

    rows = con.execute(
        "SELECT id, title FROM tasks WHERE cal_event_id IS NULL AND status='open'"
    ).fetchall()
    by_title = {r["title"].strip().lower(): r for r in rows}

    linked: list[tuple[str, str]] = []
    for ev in events:
        if not (ev.get("all_day") and ev.get("color_id") == "11"):
            continue
        summ = (ev.get("summary") or "").strip().lower().lstrip("✓ ").strip()
        match = by_title.get(summ)
        eid = ev.get("id")
        if match and eid:
            con.execute(
                "UPDATE tasks SET cal_event_id=?, cal_calendar_id=?, "
                "updated=datetime('now') WHERE id=?",
                (eid, ev.get("calendar_id", "primary"), match["id"]),
            )
            linked.append((match["title"], eid))
            del by_title[summ]  # one event per row
    return linked, f"calendar: matched {len(linked)} row(s)"


def main() -> None:
    con = tasks.connect()
    try:
        active = _parse(tasks.PLANNER_MD, done=False)
        completed = _parse(tasks.PLANNER_COMPLETED_MD, done=True)

        created = updated = 0
        report = []
        for r in active + completed:
            action, _ = _upsert(con, r)
            created += action == "created"
            updated += action == "updated"
            slug = f"  <- {r['wiki_slug']}" if r["wiki_slug"] else ""
            report.append(
                f"  [{action:7}] {r['status']:4} {r['section'][:18]:>18} | "
                f"{r['title'][:58]}{slug}"
            )
        con.commit()

        linked, cal_msg = _link_calendar(con)
        con.commit()

        total = con.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        open_n = con.execute(
            "SELECT COUNT(*) FROM tasks WHERE status='open'"
        ).fetchone()[0]
        done_n = con.execute(
            "SELECT COUNT(*) FROM tasks WHERE status='done'"
        ).fetchone()[0]
    finally:
        con.close()

    print("\n".join(report))
    print(f"\nplanner import: {created} created, {updated} updated")
    print(cal_msg)
    for title, eid in linked:
        print(f"  linked: {title}  ->  {eid}")
    print(f"\ntable now: {total} rows ({open_n} open, {done_n} done)")


if __name__ == "__main__":
    main()
