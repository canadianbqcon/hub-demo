"""Applications CRUD, plus the staleness and closeout-retro derivations."""
from __future__ import annotations

import json

from .db_core import _conn, _row, _today


# ── Applications ──────────────────────────────────────────────────────────────


# ── Staleness ─────────────────────────────────────────────────────────────────
# An application stalls in one of two distinct ways, and conflating them is why the
# old client-side check (updated > 7d) fired on 14 of 15 rows and therefore said
# nothing: it flagged research rows that were never in play, and measured the
# record's last edit rather than the process's last movement.
#
# The current step is the lowest-ordered one not yet complete. Its type says whose
# court the ball is in:
#   submitted / assessment          -> HIS move (apply, finish the take-home)
#   screen / interview / panel      -> THEIR move (waiting to hear back)
# Anything with no live status, or no incomplete step, is not stalling.

_YOUR_MOVE_STEPS = {"submitted", "assessment"}
# The live statuses: the ones the funnel counts as in flight. A research
# row is not stalling, it just has not started; a row with closed_date set is done
# whatever its status says.
_LIVE_STATUSES = {"applying", "applied", "interviewing", "offer"}

# Days of silence before a stall is worth surfacing. His side gets a shorter fuse:
# an unfinished assessment is a deadline he controls and can miss outright.
STALE_AFTER_YOURS = 7
STALE_AFTER_THEIRS = 14


def _days_between(iso: str, today: str) -> int | None:
    """Whole days from an ISO date/datetime to `today`. None if unparseable."""
    from datetime import date

    try:
        return (date.fromisoformat(today[:10]) - date.fromisoformat((iso or "")[:10])).days
    except ValueError:
        return None


def compute_staleness(app: dict, steps: list[dict], today: str) -> dict | None:
    """Whose move is overdue on this application, or None if nothing is stalling.

    Pure so the thresholds stay testable without a DB or a clock.
    """
    if app.get("status") not in _LIVE_STATUSES or app.get("closed_date"):
        return None

    pending = [s for s in steps if s.get("status") != "complete"]
    if not pending:
        return None
    step = min(pending, key=lambda s: (s.get("step_order", 0), s.get("id", 0)))

    yours = step.get("step_type") in _YOUR_MOVE_STEPS
    # Measure from the last thing that actually moved: the step's own updated stamp,
    # falling back to the application's. date_applied is not it — a step completed
    # after applying resets the clock, which is the point.
    since = step.get("updated") or app.get("updated") or ""
    days = _days_between(since, today)
    if days is None:
        return None

    threshold = STALE_AFTER_YOURS if yours else STALE_AFTER_THEIRS
    if days < threshold:
        return None

    side = "yours" if yours else "theirs"
    verb = "waiting on you" if yours else "waiting on them"
    return {
        "side": side,
        "days": days,
        "step": step.get("label", ""),
        "reason": f"{verb} \u2014 \"{step.get('label', '')}\" has not moved in {days} days",
    }


# A closed application with no post-mortem is the whole reason the closeout fields
# existed and stayed empty: the surface was reachable but nothing ever asked for it.
# closed_date is the trigger rather than status, because an offer accepted and an
# application withdrawn are both closures worth a retro while only some carry a
# closed status.
_RETRO_FIELDS = ("closed_well", "closed_didnt", "closed_differently")
_CLOSED_STATUSES = {"rejected", "ignored", "offer"}


def compute_retro_gap(app: dict) -> dict | None:
    """A closed application whose post-mortem is still blank, or None.

    Pure, same as compute_staleness, so the rule is testable without a DB.
    """
    if not (app.get("closed_date") or app.get("status") in _CLOSED_STATUSES):
        return None

    written = [f for f in _RETRO_FIELDS if (app.get(f) or "").strip()]
    if len(written) == len(_RETRO_FIELDS):
        return None

    # A reason alone is a label, not a lesson — it does not count as a written retro.
    return {
        "written": len(written),
        "total": len(_RETRO_FIELDS),
        "reason": (
            "closed with no post-mortem written"
            if not written
            else f"post-mortem half-written ({len(written)} of {len(_RETRO_FIELDS)})"
        ),
    }


def list_applications(today: str | None = None) -> list[dict]:
    from datetime import date

    today = today or date.today().isoformat()
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM applications ORDER BY updated DESC").fetchall()
        steps_by_app: dict[int, list[dict]] = {}
        for r in conn.execute(
            "SELECT * FROM application_process_steps ORDER BY step_order, id"
        ).fetchall():
            steps_by_app.setdefault(r["application_id"], []).append(dict(r))
    apps = [_row(r) for r in rows]
    for a in apps:
        a["staleness"] = compute_staleness(a, steps_by_app.get(a["id"], []), today)
        a["retro_gap"] = compute_retro_gap(a)
    return apps


def get_application(app_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM applications WHERE id = ?", (app_id,)
        ).fetchone()
    return _row(row) if row else None


def create_application(data: dict) -> dict:
    with _conn() as conn:
        cur = conn.execute(
            """INSERT INTO applications (company, role, status, priority, source, job_url,
               salary_min, salary_max, date_applied, location, notes, priority_reason, score_role,
               work_arrangement, employment_type, red_flags, red_flags_risk,
               culture_rating, culture_recommend, culture_work_life,
               requirements, nice_to_haves, years_required, listing_posted_date,
               company_summary, role_summary)
               VALUES (:company, :role, :status, :priority, :source, :job_url,
               :salary_min, :salary_max, :date_applied, :location, :notes, :priority_reason, :score_role,
               :work_arrangement, :employment_type, :red_flags, :red_flags_risk,
               :culture_rating, :culture_recommend, :culture_work_life,
               :requirements, :nice_to_haves, :years_required, :listing_posted_date,
               :company_summary, :role_summary)""",
            {
                "company": data.get("company", ""),
                "role": data.get("role", ""),
                "status": data.get("status", "intaking"),
                "priority": data.get("priority", "medium"),
                "source": data.get("source", ""),
                "job_url": data.get("job_url", ""),
                "salary_min": data.get("salary_min"),
                "salary_max": data.get("salary_max"),
                "date_applied": data.get("date_applied", ""),
                "location": data.get("location", ""),
                "notes": data.get("notes", ""),
                "priority_reason": data.get("priority_reason", ""),
                "score_role": data.get("score_role", 0),
                "work_arrangement": data.get("work_arrangement", ""),
                "employment_type": data.get("employment_type", ""),
                "red_flags": data.get("red_flags", ""),
                "red_flags_risk": data.get("red_flags_risk", ""),
                "culture_rating": data.get("culture_rating"),
                "culture_recommend": data.get("culture_recommend"),
                "culture_work_life": data.get("culture_work_life"),
                "requirements": data.get("requirements", ""),
                "nice_to_haves": data.get("nice_to_haves", ""),
                "years_required": data.get("years_required"),
                "listing_posted_date": data.get("listing_posted_date") or "",
                "company_summary": data.get("company_summary", ""),
                "role_summary": data.get("role_summary", ""),
            },
        )
        row = conn.execute(
            "SELECT * FROM applications WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
    return _row(row)


def update_application(app_id: int, data: dict) -> dict | None:
    fields = {
        k: v
        for k, v in data.items()
        if k
        in (
            "company",
            "role",
            "status",
            "priority",
            "source",
            "job_url",
            "salary_min",
            "salary_max",
            "date_applied",
            "location",
            "notes",
            "priority_reason",
            "score_role",
            "work_arrangement",
            "employment_type",
            "red_flags",
            "red_flags_risk",
            "culture_rating",
            "culture_recommend",
            "culture_work_life",
            "requirements",
            "nice_to_haves",
            # added in migration 004
            "years_required",
            "listing_posted_date",
            "url_verified_at",
            "closed_well",
            "closed_didnt",
            "closed_differently",
            "closed_reason",
            "closed_date",
            # added in migration 005
            "company_summary",
            "role_summary",
        )
    }
    if not fields:
        return get_application(app_id)
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields["updated"] = _today()
    fields["app_id"] = app_id
    with _conn() as conn:
        conn.execute(
            f"UPDATE applications SET {set_clause}, updated = :updated WHERE id = :app_id",
            fields,
        )
        row = conn.execute(
            "SELECT * FROM applications WHERE id = ?", (app_id,)
        ).fetchone()
    return _row(row) if row else None


def delete_application(app_id: int) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))


# ── Autopilot (migration 007) ────────────────────────────────────────────────
# One insert path, one dedupe, so every collector (Gmail, ATS boards, web
# search) drops a repeat the same way regardless of source. Checked in order:
# canonical URL forever, (ats_host, ats_posting_id) forever, then
# (company, role, location) for 90 days -- a role reposted after that is a new
# candidate, not a duplicate.
_DEDUPE_WINDOW_DAYS = 90
_NEEDS_YOU_STATUSES = ("manual", "manual_only", "unconfirmed")


def insert_candidate(data: dict) -> int | None:
    """Insert a new `sourced` application, or None if it's a duplicate."""
    company = data.get("company", "")
    title = data.get("title") or data.get("role", "")
    location = data.get("location", "")
    canonical_url = data.get("canonical_url", "")
    ats_host = data.get("ats_host", "")
    ats_posting_id = data.get("ats_posting_id", "")
    source = data.get("source", "")
    job_url = data.get("job_url") or canonical_url

    with _conn() as conn:
        if canonical_url and conn.execute(
            "SELECT 1 FROM applications WHERE canonical_url = ? LIMIT 1",
            (canonical_url,),
        ).fetchone():
            return None
        if ats_host and ats_posting_id and conn.execute(
            "SELECT 1 FROM applications WHERE ats_host = ? AND ats_posting_id = ? LIMIT 1",
            (ats_host, ats_posting_id),
        ).fetchone():
            return None
        # Blank company+title (web URLs, unparsed Gmail links) would all match each other.
        if company and title and conn.execute(
            "SELECT 1 FROM applications WHERE company = ? AND role = ? AND location = ? "
            "AND julianday('now') - julianday(created) <= ? LIMIT 1",
            (company, title, location, _DEDUPE_WINDOW_DAYS),
        ).fetchone():
            return None
        cur = conn.execute(
            """INSERT INTO applications
               (company, role, location, status, source, job_url, canonical_url,
                ats_host, ats_posting_id)
               VALUES (?, ?, ?, 'sourced', ?, ?, ?, ?, ?)""",
            (company, title, location, source, job_url, canonical_url, ats_host, ats_posting_id),
        )
        return cur.lastrowid


def list_ready() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM applications WHERE status = 'ready' ORDER BY fit_score DESC, id"
        ).fetchall()
    return [_row(r) for r in rows]


def list_needs_you() -> list[dict]:
    placeholders = ",".join("?" for _ in _NEEDS_YOU_STATUSES)
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM applications WHERE status IN ({placeholders}) ORDER BY updated DESC",
            _NEEDS_YOU_STATUSES,
        ).fetchall()
    return [_row(r) for r in rows]


def approve(app_id: int) -> bool:
    """ready -> approved. False (and no write) if the row wasn't `ready`."""
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE applications SET status = 'approved', approved_at = datetime('now'), "
            "updated = date('now', 'localtime') WHERE id = ? AND status = 'ready'",
            (app_id,),
        )
    return cur.rowcount == 1


def skip(app_id: int) -> bool:
    """ready -> cut, closed_reason='skipped'. False if the row wasn't `ready`."""
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE applications SET status = 'cut', closed_reason = 'skipped', "
            "closed_date = date('now', 'localtime'), updated = date('now', 'localtime') WHERE id = ? AND status = 'ready'",
            (app_id,),
        )
    return cur.rowcount == 1


def approve_all_ready() -> int:
    """Every `ready` row -> approved. Status-only write; never launches a browser."""
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE applications SET status = 'approved', approved_at = datetime('now'), "
            "updated = date('now', 'localtime') WHERE status = 'ready'"
        )
    return cur.rowcount


def next_approved() -> dict | None:
    """The oldest `approved` row, or None. The submit worker uses this to pick
    its next target before claiming it -- a tiny read helper added for Task 4
    (submitter.py), not a status-changing write."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM applications WHERE status = 'approved' "
            "ORDER BY approved_at, id LIMIT 1"
        ).fetchone()
    return _row(row) if row else None


def claim_for_submit(app_id: int) -> bool:
    """approved -> submitting. The conditional UPDATE is the claim: SQLite's

    write lock serializes concurrent callers, so of any number racing on the
    same row, exactly one sees rowcount == 1.
    """
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE applications SET status = 'submitting', updated = date('now', 'localtime') "
            "WHERE id = ? AND status = 'approved'",
            (app_id,),
        )
    return cur.rowcount == 1


def set_submit_result(app_id: int, status: str, log: str, screenshot: str | None = None) -> bool:
    """submitting -> `status` (applied / manual / unconfirmed), recording the log.

    Applied additionally stamps today's date_applied. False if the row wasn't
    `submitting` (it was already resolved, or never claimed). `applied` and
    `unconfirmed` freeze the answers that went, in the same transaction --
    the outcomes where the answers actually left.
    """
    fields = {"status": status, "submit_log": log or "", "updated": _today(), "app_id": app_id}
    extra_set = ""
    if status == "applied":
        fields["date_applied"] = _today()
        extra_set += ", date_applied = :date_applied"
    if screenshot is not None:
        fields["screenshot_path"] = screenshot
        extra_set += ", screenshot_path = :screenshot_path"
    with _conn() as conn:
        cur = conn.execute(
            f"UPDATE applications SET status = :status, submit_log = :submit_log, "
            f"updated = :updated{extra_set} WHERE id = :app_id AND status = 'submitting'",
            fields,
        )
        if cur.rowcount == 1 and status in ("applied", "unconfirmed"):
            freeze_answers(conn, app_id)
    return cur.rowcount == 1


def mark_sent(app_id: int) -> bool:
    """manual_only / manual -> applied, stamping date_applied and freezing the

    answers that actually went. False (and no write) if the row wasn't in
    either status -- the you-submit path has no "submitting" claim to race,
    so this is the whole check.
    """
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE applications SET status = 'applied', date_applied = date('now', 'localtime'), "
            "updated = date('now', 'localtime') WHERE id = ? AND status IN ('manual_only', 'manual')",
            (app_id,),
        )
        if cur.rowcount == 1:
            freeze_answers(conn, app_id)
    return cur.rowcount == 1


def resolve_unconfirmed(app_id: int, outcome: str) -> bool:
    """unconfirmed -> applied or closed, the only two truthful outcomes once he's

    checked his email by hand. Any other outcome value is refused.
    """
    if outcome not in ("applied", "closed"):
        return False
    with _conn() as conn:
        if outcome == "applied":
            cur = conn.execute(
                "UPDATE applications SET status = 'applied', date_applied = date('now', 'localtime'), "
                "updated = date('now', 'localtime') WHERE id = ? AND status = 'unconfirmed'",
                (app_id,),
            )
        else:
            cur = conn.execute(
                "UPDATE applications SET status = 'closed', closed_date = date('now', 'localtime'), "
                "updated = date('now', 'localtime') WHERE id = ? AND status = 'unconfirmed'",
                (app_id,),
            )
    return cur.rowcount == 1


def save_form_fields(app_id: int, fields: list[dict]) -> list[dict]:
    """Replace this application's form_fields with `fields`.

    A DELETE-then-insert rather than an upsert: form_fields has no natural key
    across a form re-read, and the FK's ON DELETE CASCADE drops any answers tied
    to the fields it replaces, so a changed form never leaves a stale answer
    pointed at a field that no longer exists.
    """
    with _conn() as conn:
        conn.execute("DELETE FROM form_fields WHERE application_id = ?", (app_id,))
        saved = []
        for i, f in enumerate(fields):
            options = f.get("options_json", f.get("options"))
            if options is None:
                options = "[]"
            elif not isinstance(options, str):
                options = json.dumps(options)
            cur = conn.execute(
                """INSERT INTO form_fields
                   (application_id, ord, label, name, field_type, required,
                    options_json, is_demographic)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    app_id,
                    f.get("ord", i),
                    f.get("label", ""),
                    f.get("name", ""),
                    f.get("field_type", ""),
                    int(bool(f.get("required"))),
                    options,
                    int(bool(f.get("is_demographic"))),
                ),
            )
            saved.append({**f, "id": cur.lastrowid, "application_id": app_id})
    return saved


def get_form(app_id: int) -> list[dict]:
    """form_fields for this application, each with its answer (None if unanswered)."""
    with _conn() as conn:
        rows = conn.execute(
            """SELECT ff.id, ff.application_id, ff.ord, ff.label, ff.name, ff.field_type,
                      ff.required, ff.options_json, ff.is_demographic,
                      a.value AS answer, a.draft AS draft, a.rewritten AS rewritten
               FROM form_fields ff
               LEFT JOIN answers a ON a.form_field_id = ff.id
               WHERE ff.application_id = ?
               ORDER BY ff.ord, ff.id""",
            (app_id,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["options"] = json.loads(d.get("options_json") or "[]")
        except (TypeError, ValueError):
            d["options"] = []
        out.append(d)
    return out


# ── Frozen record (migration 008) ────────────────────────────────────────────
# A field's raw answer is an option's value (an id, "1"), not something worth
# reading back cold on an application he closed weeks ago. display_answer
# mirrors answerText in jobs-surfaces-b.jsx so the frozen row carries what a
# person would actually read, with no join back to form_fields required.

_TEXT_TYPES = {"textarea", "input_text"}


def display_answer(field: dict) -> str:
    """A field dict's answer as a person would read it. "" for no answer."""
    value = field.get("answer")
    if value is None or value == "":
        return ""
    opts = field.get("options") or []
    if opts:
        try:
            vals = json.loads(value)
        except (TypeError, ValueError):
            vals = value
        vals = vals if isinstance(vals, list) else [vals]
        by_value = {str(o.get("value")): o.get("label", "") for o in opts}
        return ", ".join(by_value.get(str(v), str(v)) for v in vals)
    if field.get("field_type") == "input_checkbox":
        return "Yes" if value in ("true", "on") else "No"
    return value


def freeze_answers(conn, app_id: int) -> int:
    """Snapshot every non-demographic, non-file answer onto sent_answers.

    Deletes any prior snapshot for this application first. Runs inside the
    caller's `with _conn()` block -- get_form() opens its own nested one, but
    sqlite_helpers.connect hands back this thread's single connection with a
    depth counter, so the nested read shares the caller's transaction and only
    the outermost block commits. Callers: set_submit_result, mark_sent.
    """
    fields = [f for f in get_form(app_id) if f["field_type"] != "input_file" and not f["is_demographic"]]
    conn.execute("DELETE FROM sent_answers WHERE application_id = ?", (app_id,))
    rows = []
    for f in fields:
        edited = int(
            f["field_type"] in _TEXT_TYPES
            and (f.get("answer") or "") != (f.get("draft") or "")
        )
        rows.append((
            app_id, f["ord"], f["label"], f["field_type"],
            display_answer(f), display_answer({**f, "answer": f.get("draft")}),
            edited, int(f.get("rewritten") or 0),
        ))
    if rows:
        conn.executemany(
            "INSERT INTO sent_answers "
            "(application_id, ord, question, field_type, answer, draft, edited, rewritten, sent_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))",
            rows,
        )
    return len(rows)


def get_sent_answers(app_id: int) -> list[dict]:
    """This application's frozen record, oldest field order first."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM sent_answers WHERE application_id = ? ORDER BY ord, id",
            (app_id,),
        ).fetchall()
    return [dict(r) for r in rows]
