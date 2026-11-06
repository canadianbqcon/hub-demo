"""Write path for the /job-sweep skill's judgment steps.

The skill decides (cuts, scores, answers); this CLI is the only thing that
writes those decisions, and it checks them first: a select answer must be one
of the recorded options, every field must be answered before a row can go
`ready`, and the resume must be a one-page PDF under data/resumes/. So a
sloppy model run fails loudly here instead of parking a row that cannot be sent.

    python3 sweep_prep.py list                    # sourced + manual_only rows, fields, no answers
    python3 sweep_prep.py cut ID REASON           # sourced -> cut
    python3 sweep_prep.py score ID SCORE REASON   # fit_score / fit_reason
    python3 sweep_prep.py name ID COMPANY ROLE    # web-search rows arrive with neither
    python3 sweep_prep.py intake ID FILE.json     # posting details (stage1.md fields) for the card
    python3 sweep_prep.py research ID FILE.json   # Stage 2 payload: culture numbers, 39 rows, steps
    python3 sweep_prep.py answers ID FILE.json    # {"<form_field id>": "value", ...}
    python3 sweep_prep.py ready ID RESUME.pdf     # check, add the resumes row, sourced -> ready
    python3 sweep_prep.py resume ID RESUME.pdf    # add the resumes row only (manual_only rows)
    python3 sweep_prep.py manual-only ID REASON   # sourced -> manual_only (prepped, sent by hand)
    python3 sweep_prep.py promote HOST SLUG       # suggested slug -> active
    python3 sweep_prep.py edits [N]                # last N text edits + counts, for the sweep to read

Never prints or reads an answer value from a row with rewritten = 1: that
stored text is the Ollama rewrite and must stay out of model context.
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

_JOBS_DIR = Path(__file__).resolve().parent
for _p in (str(_JOBS_DIR.parent.parent), str(_JOBS_DIR.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from jobs import db, resume_files, sweep_sources  # noqa: E402
from vault_path import vault_root  # noqa: E402

_CHOICE_TYPES = {"multi_value_single_select", "select", "radio"}
_MULTI_TYPES = {"multi_value_multi_select", "checkbox_group"}
_DECLINE_WORDS = ("decline", "prefer not", "don't wish", "do not wish", "do not want",
                  "don't want", "not to disclose", "not to answer", "not to say")


def _decline_option(field: dict) -> str:
    for o in field.get("options") or []:
        if any(w in (o.get("label") or "").lower() for w in _DECLINE_WORDS):
            return str(o.get("value", ""))
    return ""


def _demographic_option(field: dict) -> str:
    """Sam's standing self-ID answers (candidate_profile.md): not a veteran,
    he/him, decline everything else. Falls back to decline when no option says it.
    Lever labels its survey with ids, so the name is searched too."""
    what = f"{field.get('label') or ''} {field.get('name') or ''}".lower()
    for o in field.get("options") or []:
        lab = (o.get("label") or "").lower().strip()
        if "veteran" in what and ("not a protected veteran" in lab or "not a veteran" in lab or lab == "no"):
            return str(o.get("value", ""))
        if "pronoun" in what and lab.startswith("he/him"):
            return str(o.get("value", ""))
    return _decline_option(field)


def check_answer(field: dict, value) -> str | None:
    """Why `value` is not a valid answer for `field`, or None if it is."""
    ftype = field.get("field_type", "")
    allowed = {str(o.get("value", "")) for o in field.get("options") or []}
    if ftype in _CHOICE_TYPES:
        return None if str(value) in allowed else f"{value!r} is not one of the options"
    if ftype in _MULTI_TYPES:
        values = value if isinstance(value, list) else [value]
        bad = [v for v in values if str(v) not in allowed]
        return f"{bad!r} not among the options" if bad else None
    if ftype == "input_checkbox":
        return None if str(value) in ("", "on", "true", "false") else "checkbox takes on/true/false"
    return None if isinstance(value, str) else "text answer must be a string"


def save_answers(app_id: int, answers: dict, source: str = "sweep") -> list[str]:
    """Validate then store every answer (rewritten=0). Returns errors; writes nothing on any.

    source="sweep" (the CLI, the default) writes the draft alongside the value,
    so the text the sweep proposed survives even after he edits it. source="you"
    (the Hub edit route) writes value only, leaving whatever draft is on record."""
    form = {f["id"]: f for f in db.get_form(app_id)}
    errors, rows = [], []
    for key, value in answers.items():
        field = form.get(int(key))
        if field is None:
            errors.append(f"field {key}: not a field of application {app_id}")
            continue
        if field.get("is_demographic"):
            value = _demographic_option(field)  # standing answer, whatever was sent
        why = check_answer(field, value) if value != "" else None
        if why:
            errors.append(f"field {key} ({field['label'][:40]}): {why}")
            continue
        stored = json.dumps(value) if isinstance(value, list) else str(value)
        rows.append((app_id, field["id"], stored))
    if errors:
        return errors
    with db._conn() as conn:
        if source == "sweep":
            conn.executemany(
                "INSERT INTO answers (application_id, form_field_id, value, draft, rewritten) "
                "VALUES (?, ?, ?, ?, 0) "
                "ON CONFLICT(application_id, form_field_id) DO UPDATE SET "
                "value = excluded.value, draft = excluded.draft, rewritten = 0",
                [(a, f, v, v) for a, f, v in rows],
            )
        else:
            conn.executemany(
                "INSERT INTO answers (application_id, form_field_id, value, rewritten) VALUES (?, ?, ?, 0) "
                "ON CONFLICT(application_id, form_field_id) DO UPDATE SET value = excluded.value, rewritten = 0",
                rows,
            )
    return []


_TEXT_TYPES = ("textarea", "input_text")


def recent_edits(limit: int = 15) -> list[dict]:
    """The last `limit` text edits (question, draft, answer), newest first.

    Two sources, never overlapping: sent_answers rows he edited before they
    went (edited=1), and live answers still open (value != draft) on an
    application that has not been sent yet -- once sent_answers exists for
    an application, its live answers are skipped, so a sent edit is never
    printed twice. Choice fields never show: edited is 0 for them by
    definition, and the live half only looks at textarea/input_text. Rows
    flagged rewritten=1 (the legacy Ollama rewrite) are excluded from both.
    """
    with db._conn() as conn:
        rows = conn.execute(
            "SELECT question, draft, answer, sent_at AS ts FROM sent_answers "
            "WHERE edited = 1 AND rewritten = 0 "
            "UNION ALL "
            "SELECT ff.label AS question, a.draft AS draft, a.value AS answer, ap.updated AS ts "
            "FROM answers a JOIN form_fields ff ON ff.id = a.form_field_id "
            "JOIN applications ap ON ap.id = a.application_id "
            "WHERE a.rewritten = 0 AND ff.field_type IN (?, ?) AND a.value != a.draft "
            "AND NOT EXISTS (SELECT 1 FROM sent_answers sa WHERE sa.application_id = a.application_id) "
            "ORDER BY ts DESC LIMIT ?",
            (*_TEXT_TYPES, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def edit_stats() -> dict:
    """Counts over every sent text answer (rewritten=0): how many went out,
    what share he edited, and the median answer-length change on those."""
    with db._conn() as conn:
        rows = conn.execute(
            "SELECT edited, length(answer) - length(draft) AS delta FROM sent_answers "
            "WHERE rewritten = 0 AND field_type IN (?, ?)",
            _TEXT_TYPES,
        ).fetchall()
    total = len(rows)
    deltas = [r["delta"] for r in rows if r["edited"]]
    return {
        "total": total,
        "edited": len(deltas),
        "share": len(deltas) / total if total else 0.0,
        "median": statistics.median(deltas) if deltas else 0,
    }


def print_edits(limit: int = 15) -> None:
    """The `edits` CLI command's output: each edit, then one counts line."""
    rows = recent_edits(limit)
    if not rows:
        print("no edits yet")
        return
    for r in rows:
        print(f"Q: {r['question']}")
        print(f"draft: {r['draft']}")
        print(f"his version: {r['answer']}")
        print()
    stats = edit_stats()
    print(f"{stats['total']} answer(s) sent, {stats['share']:.0%} edited, "
          f"median length change {stats['median']:+.0f}")


# The Stage 1 fields a posting states (stage1.md). Status, score and dates are
# not here: the sweep owns those through its other commands.
_INTAKE_TEXT = {"location", "work_arrangement", "employment_type", "requirements", "nice_to_haves",
                "company_summary", "role_summary", "red_flags", "red_flags_risk", "listing_posted_date",
                "priority_reason"}
_INTAKE_NUM = {"salary_min", "salary_max", "years_required"}


def save_intake(app_id: int, data: dict) -> list[str]:
    """Validate then store the posting's intake fields. Returns errors; writes nothing on any."""
    errors = [f"{k}: not an intake field" for k in data if k not in _INTAKE_TEXT | _INTAKE_NUM]
    for k in _INTAKE_NUM & data.keys():
        if data[k] is not None and not isinstance(data[k], int):
            errors.append(f"{k}: must be a whole number or null, got {data[k]!r}")
    for k in _INTAKE_TEXT & data.keys():
        if not isinstance(data[k], str):
            errors.append(f"{k}: must be a string")
    if errors:
        return errors
    if db.update_application(app_id, data) is None:
        return [f"application {app_id} not found"]
    return []


# The 39 Stage 2 subcategories (job-research SKILL.md step 3). A missing one
# renders the same as never researched, so the command refuses a partial set.
RESEARCH_SUBS = {
    "role": ("summary", "day_to_day", "travel", "success", "customers", "schedule", "tools", "environment"),
    "company": ("stage", "size", "funding", "sites"),
    "culture": ("vibe", "looking_for", "not_looking_for", "green_flags", "red_flags", "values"),
    "compensation": ("base", "equity", "bonus", "comparison"),
    "progression": ("internal_path", "lateral", "tenure"),
    "benefits": ("health", "retirement", "time_off", "perks"),
    "process": ("steps", "rounds", "gating", "timeline", "referral"),
    "intel": ("insider", "hypothesis", "tactical", "sample_questions", "unionization"),
}
_CULTURE = {"culture_rating", "culture_recommend", "culture_work_life"}


def save_research(app_id: int, payload: dict) -> list[str]:
    """Store a job-research payload ({gap_fill, research_rows, process_steps}).
    Validates everything first; writes nothing on any error."""
    gap = dict(payload.get("gap_fill") or {})
    culture = {k: gap.pop(k) for k in list(gap) if k in _CULTURE}
    errors = [f"{k}: must be a number or null" for k, v in culture.items()
              if v is not None and not isinstance(v, (int, float))]
    for k in ("salary_min", "salary_max", "years_required"):  # researchers return 65000.0
        if isinstance(gap.get(k), float) and gap[k].is_integer():
            gap[k] = int(gap[k])
    rows = {(r.get("category"), r.get("subcategory")): (r.get("content") or "").strip()
            for r in payload.get("research_rows") or []}
    for cat, subs in RESEARCH_SUBS.items():
        errors += [f"research {cat}.{sub}: missing or blank" for sub in subs if not rows.get((cat, sub))]
    steps = payload.get("process_steps") or []
    if not steps:
        errors.append("process_steps: empty")
    if errors:
        return errors
    errors = save_intake(app_id, gap) if gap else []
    if errors:
        return errors
    if culture:
        db.update_application(app_id, culture)
    for (cat, sub), content in rows.items():
        if sub in RESEARCH_SUBS.get(cat, ()):
            db.create_research(app_id, {"category": cat, "subcategory": sub, "content": content})
    db.bulk_set_process_steps(app_id, steps)  # refuses to clobber existing steps; that is fine
    return []


def _one_page_pdf(path: Path) -> str | None:
    import fitz

    if path.suffix.lower() != ".pdf" or not path.exists():
        return f"{path} is not an existing .pdf"
    with fitz.open(path) as doc:
        return None if doc.page_count == 1 else f"resume has {doc.page_count} pages, must be 1"


def add_resume(app_id: int, pdf: str) -> str | None:
    """Insert the resumes row for a one-page PDF under data/resumes/. Error string or None."""
    path = Path(pdf).resolve()
    try:
        rel = path.relative_to(vault_root().resolve()).as_posix()
    except ValueError:
        return f"{pdf} is not under the vault"
    if resume_files.resolve_resume_path(rel) is None:
        return f"{rel} is not a .pdf under data/resumes/"
    err = _one_page_pdf(path)
    if err:
        return err
    app = db.get_application(app_id) or {}
    with db._conn() as conn:
        if not conn.execute(
            "SELECT 1 FROM resumes WHERE application_id = ? AND file_path = ?", (app_id, rel)
        ).fetchone():
            conn.execute(
                "INSERT INTO resumes (application_id, file_path, variant, label) VALUES (?, ?, 'tailored', ?)",
                (app_id, rel, f"{app.get('company', '')} - {app.get('role', '')}"),
            )
    return None


def mark_ready(app_id: int, pdf: str) -> list[str]:
    """sourced -> ready, only when every field is answered and the resume checks out."""
    form = [f for f in db.get_form(app_id) if f["field_type"] != "input_file"]
    unanswered = [f["label"][:40] for f in form if f["required"] and not f.get("answer")]
    if unanswered:
        return [f"unanswered required field(s): {unanswered}"]
    # an optional field may be left blank, but on purpose: send "" for it
    skipped = [f["label"][:40] for f in form if f.get("answer") is None]
    if skipped:
        return [f"no answer sent for optional field(s) (send \"\" to leave blank): {skipped}"]
    err = add_resume(app_id, pdf)
    if err:
        return [err]
    with db._conn() as conn:
        cur = conn.execute(
            "UPDATE applications SET status = 'ready', updated = date('now', 'localtime') WHERE id = ? AND status = 'sourced'",
            (app_id,),
        )
    return [] if cur.rowcount == 1 else ["application is not sourced"]


def _update(sql: str, params: tuple) -> bool:
    with db._conn() as conn:
        return conn.execute(sql, params).rowcount == 1


def list_candidates() -> list[dict]:
    with db._conn() as conn:
        rows = conn.execute(
            "SELECT id, company, role, location, status, source, job_url, canonical_url, ats_host, fit_score "
            "FROM applications WHERE status IN ('sourced', 'manual_only') ORDER BY id"
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["fields"] = [
            {k: f[k] for k in ("id", "label", "field_type", "required", "options", "is_demographic")}
            for f in db.get_form(d["id"])
        ]
        out.append(d)
    return out


def main(argv: list[str]) -> int:
    db.init(vault_root() / "data" / "jobs.db")
    cmd, args = (argv[0], argv[1:]) if argv else ("", [])
    if cmd == "list":
        print(json.dumps(list_candidates(), indent=1))
        return 0
    if cmd == "edits":
        print_edits(int(args[0]) if args else 15)
        return 0
    if cmd == "cut" and len(args) == 2:
        ok = _update(
            "UPDATE applications SET status = 'cut', closed_reason = ?, closed_date = date('now', 'localtime'), "
            "updated = date('now', 'localtime') WHERE id = ? AND status IN ('sourced', 'manual_only')",
            (args[1], int(args[0])),
        )
    elif cmd == "manual-only" and len(args) == 2:
        ok = _update(
            "UPDATE applications SET status = 'manual_only', submit_log = ?, updated = date('now', 'localtime') "
            "WHERE id = ? AND status = 'sourced'",
            (args[1], int(args[0])),
        )
    elif cmd == "score" and len(args) == 3:
        ok = _update(
            # score_role is the page's 0-10 role fit; mirror the sweep's 0-100 score into it
            "UPDATE applications SET fit_score = ?, fit_reason = ?, score_role = ?, updated = date('now', 'localtime') WHERE id = ?",
            (float(args[1]), args[2], round(float(args[1]) / 10), int(args[0])),
        )
    elif cmd == "name" and len(args) == 3:
        ok = _update(
            "UPDATE applications SET company = ?, role = ?, updated = date('now', 'localtime') WHERE id = ?",
            (args[1], args[2], int(args[0])),
        )
    elif cmd == "answers" and len(args) == 2:
        errors = save_answers(int(args[0]), json.loads(Path(args[1]).read_text(encoding="utf-8")), source="sweep")
        for e in errors:
            print(e)
        return 2 if errors else 0
    elif cmd == "intake" and len(args) == 2:
        errors = save_intake(int(args[0]), json.loads(Path(args[1]).read_text(encoding="utf-8")))
        for e in errors:
            print(e)
        return 2 if errors else 0
    elif cmd == "research" and len(args) == 2:
        errors = save_research(int(args[0]), json.loads(Path(args[1]).read_text(encoding="utf-8")))
        for e in errors:
            print(e)
        return 2 if errors else 0
    elif cmd == "ready" and len(args) == 2:
        errors = mark_ready(int(args[0]), args[1])
        for e in errors:
            print(e)
        return 2 if errors else 0
    elif cmd == "resume" and len(args) == 2:
        err = add_resume(int(args[0]), args[1])
        if err:
            print(err)
        return 2 if err else 0
    elif cmd == "promote" and len(args) == 2:
        sweep_sources.promote(args[0], args[1])
        ok = True
    else:
        print(__doc__)
        return 1
    print("ok" if ok else "no change (row missing or in another status)")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
