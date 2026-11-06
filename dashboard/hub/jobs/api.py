from __future__ import annotations

from pathlib import Path

from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    render_template,
    request,
    send_file,
    stream_with_context,
)

from . import ai_research as ai_research_svc
from . import db, profile, resume_files

bp = Blueprint(
    "jobs",
    __name__,
    template_folder="frontend",
    static_folder="frontend/static",
    url_prefix="/jobs",
)

CLOSED_REASONS = frozenset(
    {
        "",  # cleared / not set
        "weak_customer_signal",
        "technical_gap",
        "culture_mismatch",
        "comp_misalignment",
        "headcount_change",
        "candidate_withdrew",
        "ineligible",
        "no_reason_given",
        "offer_accepted",
    }
)

# Validated for the same reason closed_reason is: an unrecognized status writes fine
# to the DB but matches no branch in the funnel's totals, so the row silently stops
# being counted anywhere. App #114 sat at status "active" — closed and withdrawn on
# 2026-07-15 — invisible in every bucket and unreachable from the post-mortem surface,
# which is why its retro was never written. Mirrors jobs-core.jsx STATUS_LABELS exactly.
STATUSES = frozenset(
    {
        "intaking",
        "researching",
        "applying",
        "applied",
        "interviewing",
        "offer",
        "rejected",
        "ignored",
    }
)


# ── Page ──────────────────────────────────────────────────────────────────────


@bp.route("/")
def index():
    return render_template(
        "jobs.html", exposed=current_app.config.get("EXPOSED", False)
    )


# ── Applications ──────────────────────────────────────────────────────────────


@bp.route("/api/applications", methods=["GET"])
def list_applications():
    return jsonify(db.list_applications())


@bp.route("/api/applications", methods=["POST"])
def create_application():
    data = request.get_json(force=True, silent=True) or {}
    if "status" in data and data["status"] not in STATUSES:
        return jsonify({"error": "invalid status", "allowed": sorted(STATUSES)}), 400
    return jsonify(db.create_application(data)), 201


@bp.route("/api/applications/<int:app_id>", methods=["GET"])
def get_application(app_id: int):
    app = db.get_application(app_id)
    if not app:
        return jsonify({"error": "not found"}), 404
    app["resume_notes"] = db.list_resume_notes(app_id)
    app["cover_letter"] = db.get_cover_letter(app_id)
    app["research"] = db.list_research(app_id)
    app["interviewers"] = db.list_interviewers(app_id)
    app["skills"] = db.list_app_skills(app_id)
    app["stories"] = db.list_app_stories(app_id)
    app["process_steps"] = db.list_process_steps(app_id)
    app["resumes"] = db.list_app_resumes(app_id)
    app["cover_pdf"] = db.get_cover_pdf(app_id)
    app["interview_qa"] = db.list_app_qa(app_id)
    app["sent_answers"] = db.get_sent_answers(app_id)
    app["form"] = db.get_form(app_id)  # the application questions and drafted answers
    return jsonify(app)


@bp.route("/api/applications/<int:app_id>", methods=["PATCH"])
def update_application(app_id: int):
    data = request.get_json(force=True, silent=True) or {}
    if "closed_reason" in data and data["closed_reason"] not in CLOSED_REASONS:
        return jsonify(
            {
                "error": "invalid closed_reason",
                "allowed": sorted(r for r in CLOSED_REASONS if r),
            }
        ), 400
    if "status" in data and data["status"] not in STATUSES:
        return jsonify(
            {"error": "invalid status", "allowed": sorted(STATUSES)}
        ), 400
    result = db.update_application(app_id, data)
    if not result:
        return jsonify({"error": "not found"}), 404
    return jsonify(result)


@bp.route("/api/applications/<int:app_id>", methods=["DELETE"])
def delete_application(app_id: int):
    # Collect resume files before the cascade removes their rows, then unlink
    # them so deleting a job leaves nothing stranded on disk.
    for resume in db.list_app_resumes(app_id):
        resume_files.unlink_resume_artifacts(resume.get("file_path"))
    db.delete_application(app_id)
    return "", 204


# ── Resume notes ──────────────────────────────────────────────────────────────


@bp.route("/api/applications/<int:app_id>/resume-notes", methods=["POST"])
def create_resume_note(app_id: int):
    data = request.get_json(force=True, silent=True) or {}
    return jsonify(db.create_resume_note(app_id, data)), 201


@bp.route(
    "/api/applications/<int:app_id>/resume-notes/<int:note_id>", methods=["PATCH"]
)
def update_resume_note(app_id: int, note_id: int):
    data = request.get_json(force=True, silent=True) or {}
    result = db.update_resume_note(note_id, data)
    return jsonify(result) if result else ("", 404)


@bp.route(
    "/api/applications/<int:app_id>/resume-notes/<int:note_id>", methods=["DELETE"]
)
def delete_resume_note(app_id: int, note_id: int):
    db.delete_resume_note(note_id)
    return "", 204


# ── Candidate profile ─────────────────────────────────────────────────────────


@bp.route("/api/candidate-profile", methods=["GET"])
def get_candidate_profile():
    return jsonify(profile.load_candidate_profile())


# ── Cover letter ──────────────────────────────────────────────────────────────


@bp.route("/api/applications/<int:app_id>/cover-letter", methods=["POST"])
def upsert_cover_letter(app_id: int):
    data = request.get_json(force=True, silent=True) or {}
    return jsonify(db.upsert_cover_letter(app_id, data))


# ── Research ──────────────────────────────────────────────────────────────────


@bp.route("/api/applications/<int:app_id>/research", methods=["POST"])
def create_research(app_id: int):
    data = request.get_json(force=True, silent=True) or {}
    return jsonify(db.create_research(app_id, data)), 201


@bp.route("/api/applications/<int:app_id>/research/<int:item_id>", methods=["PATCH"])
def update_research(app_id: int, item_id: int):
    data = request.get_json(force=True, silent=True) or {}
    row = db.update_research(item_id, data)
    if row is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(row)


@bp.route("/api/applications/<int:app_id>/research/<int:item_id>", methods=["DELETE"])
def delete_research(app_id: int, item_id: int):
    db.delete_research(item_id)
    return "", 204


# ── Application process steps ─────────────────────────────────────────────────


@bp.route("/api/applications/<int:app_id>/process-steps", methods=["GET"])
def list_process_steps(app_id: int):
    return jsonify(db.list_process_steps(app_id))


@bp.route("/api/applications/<int:app_id>/process-steps", methods=["POST"])
def create_process_step(app_id: int):
    data = request.get_json(force=True, silent=True) or {}
    return jsonify(db.create_process_step(app_id, data)), 201


@bp.route(
    "/api/applications/<int:app_id>/process-steps/<int:step_id>", methods=["PATCH"]
)
def update_process_step(app_id: int, step_id: int):
    data = request.get_json(force=True, silent=True) or {}
    result = db.update_process_step(step_id, data)
    return jsonify(result) if result else ("", 404)


@bp.route(
    "/api/applications/<int:app_id>/process-steps/<int:step_id>", methods=["DELETE"]
)
def delete_process_step(app_id: int, step_id: int):
    db.delete_process_step(step_id)
    return "", 204


@bp.route("/api/applications/<int:app_id>/process-steps/bulk", methods=["POST"])
def bulk_set_process_steps(app_id: int):
    data = request.get_json(force=True, silent=True) or {}
    steps = data.get("steps", [])
    if not isinstance(steps, list):
        return jsonify({"error": "steps must be an array"}), 400
    rows = db.bulk_set_process_steps(app_id, steps, replace=bool(data.get("replace")))
    if rows is None:
        # Seeding an application that already has steps would delete them. Hand
        # back what is already there so the caller can see it did not need to write.
        return jsonify(
            {
                "error": "process steps already exist",
                "hint": "pass replace: true to overwrite them",
                "existing": db.list_process_steps(app_id),
            }
        ), 409
    return jsonify(rows)


# ── AI research stream ────────────────────────────────────────────────────────


@bp.route("/api/applications/<int:app_id>/ai-research", methods=["POST"])
def ai_research(app_id: int):
    from finances.autocat import _api_key  # env first, then ~/.config/vault-api/.env  # pyright: ignore[reportMissingImports]  hub/ is on sys.path at runtime, as for news/digest_api.py
    api_key = _api_key()
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not set"}), 500

    app = db.get_application(app_id)
    if not app:
        return jsonify({"error": "not found"}), 404

    data = request.get_json(force=True, silent=True) or {}
    stream = ai_research_svc.research_stream(
        app,
        data.get("focus", "company"),  # company | interviewer | role
        data.get("interviewer_name", ""),
        api_key,
    )
    return Response(
        stream_with_context(stream),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Interviewers ──────────────────────────────────────────────────────────────


@bp.route("/api/applications/<int:app_id>/interviewers", methods=["POST"])
def create_interviewer(app_id: int):
    data = request.get_json(force=True, silent=True) or {}
    return jsonify(db.create_interviewer(app_id, data)), 201


@bp.route("/api/applications/<int:app_id>/interviewers/<int:iid>", methods=["PATCH"])
def update_interviewer(app_id: int, iid: int):
    data = request.get_json(force=True, silent=True) or {}
    result = db.update_interviewer(iid, data)
    return jsonify(result) if result else ("", 404)


@bp.route("/api/applications/<int:app_id>/interviewers/<int:iid>", methods=["DELETE"])
def delete_interviewer(app_id: int, iid: int):
    db.delete_interviewer(iid)
    return "", 204


# ── Skills ────────────────────────────────────────────────────────────────────


@bp.route("/api/skills", methods=["GET"])
def list_skills():
    return jsonify(db.list_skills())


@bp.route("/api/skills", methods=["POST"])
def create_skill():
    data = request.get_json(force=True, silent=True) or {}
    return jsonify(db.create_skill(data)), 201


@bp.route("/api/skills/<int:skill_id>", methods=["PATCH"])
def update_skill(skill_id: int):
    data = request.get_json(force=True, silent=True) or {}
    result = db.update_skill(skill_id, data)
    return jsonify(result) if result else ("", 404)


@bp.route("/api/skills/<int:skill_id>", methods=["DELETE"])
def delete_skill(skill_id: int):
    db.delete_skill(skill_id)
    return "", 204


@bp.route("/api/applications/<int:app_id>/skills", methods=["GET"])
def list_app_skills(app_id: int):
    return jsonify(db.list_app_skills(app_id))


@bp.route("/api/applications/<int:app_id>/skills", methods=["POST"])
def link_skill(app_id: int):
    data = request.get_json(force=True, silent=True) or {}
    skill_id = data.get("skill_id")
    if not skill_id:
        return jsonify({"error": "skill_id required"}), 400
    db.link_skill(app_id, skill_id, data)
    return "", 204


@bp.route("/api/applications/<int:app_id>/skills/<int:skill_id>", methods=["DELETE"])
def unlink_skill(app_id: int, skill_id: int):
    db.unlink_skill(app_id, skill_id)
    return "", 204


# ── Stories ───────────────────────────────────────────────────────────────────


@bp.route("/api/stories", methods=["GET"])
def list_stories():
    return jsonify(db.list_stories())


@bp.route("/api/stories", methods=["POST"])
def create_story():
    data = request.get_json(force=True, silent=True) or {}
    return jsonify(db.create_story(data)), 201


@bp.route("/api/stories/<int:story_id>", methods=["PATCH"])
def update_story(story_id: int):
    data = request.get_json(force=True, silent=True) or {}
    result = db.update_story(story_id, data)
    return jsonify(result) if result else ("", 404)


@bp.route("/api/stories/<int:story_id>", methods=["DELETE"])
def delete_story(story_id: int):
    db.delete_story(story_id)
    return "", 204


@bp.route("/api/applications/<int:app_id>/stories", methods=["POST"])
def link_story(app_id: int):
    data = request.get_json(force=True, silent=True) or {}
    story_id = data.get("story_id")
    if not story_id:
        return jsonify({"error": "story_id required"}), 400
    db.link_story(app_id, story_id, data.get("notes", ""))
    return "", 204


@bp.route("/api/applications/<int:app_id>/stories/<int:story_id>", methods=["DELETE"])
def unlink_story(app_id: int, story_id: int):
    db.unlink_story(app_id, story_id)
    return "", 204


# ── Glossary ──────────────────────────────────────────────────────────────────


@bp.route("/api/applications/<int:app_id>/glossary", methods=["GET"])
def app_glossary(app_id: int):
    return jsonify(db.get_app_glossary(app_id))


@bp.route("/api/glossary", methods=["GET"])
def list_glossary():
    return jsonify(db.list_glossary())


@bp.route("/api/glossary/<int:term_id>", methods=["PATCH"])
def update_glossary(term_id: int):
    data = request.get_json(force=True, silent=True) or {}
    result = db.set_glossary_known(term_id, bool(data.get("known")))
    if not result:
        return jsonify({"error": "not found"}), 404
    return jsonify(result)


@bp.route("/api/glossary/<int:term_id>", methods=["DELETE"])
def forget_glossary(term_id: int):
    if not db.delete_glossary(term_id):
        return jsonify({"error": "not found"}), 404
    return jsonify({"deleted": term_id})


# ── Resumes ───────────────────────────────────────────────────────────────────


def _reject_bad_resume_path(data: dict):
    """Validate a client-supplied file_path at write time.

    Empty/absent file_path is allowed (a resume row with no file attached yet).
    A non-empty path that fails the safety check returns a 400 response tuple;
    a clean path returns None so the caller proceeds.
    """
    fp = data.get("file_path")
    if fp in (None, ""):
        return None
    if resume_files.resolve_resume_path(fp) is None:
        return jsonify(
            {"error": "file_path must be a .pdf or .docx under data/resumes/"}
        ), 400
    return None


@bp.route("/api/resumes/base", methods=["GET"])
def list_resumes_base():
    return jsonify(db.list_resumes_base())


@bp.route("/api/resumes/base", methods=["POST"])
def create_base_resume():
    data = request.get_json(force=True, silent=True) or {}
    bad = _reject_bad_resume_path(data)
    if bad:
        return bad
    return jsonify(db.create_resume(None, data)), 201


@bp.route("/api/applications/<int:app_id>/resumes", methods=["GET"])
def list_app_resumes(app_id: int):
    return jsonify(db.list_app_resumes(app_id))


@bp.route("/api/applications/<int:app_id>/resumes", methods=["POST"])
def create_resume(app_id: int):
    data = request.get_json(force=True, silent=True) or {}
    bad = _reject_bad_resume_path(data)
    if bad:
        return bad
    return jsonify(db.create_resume(app_id, data)), 201


@bp.route("/api/resumes/<int:resume_id>", methods=["PATCH"])
def update_resume(resume_id: int):
    data = request.get_json(force=True, silent=True) or {}
    bad = _reject_bad_resume_path(data)
    if bad:
        return bad
    result = db.update_resume(resume_id, data)
    return jsonify(result) if result else ("", 404)


@bp.route("/api/resumes/<int:resume_id>", methods=["DELETE"])
def delete_resume(resume_id: int):
    row = db.get_resume(resume_id)
    if row:
        resume_files.unlink_resume_artifacts(row.get("file_path"))
    db.delete_resume(resume_id)
    return "", 204


@bp.route("/api/resumes/<int:resume_id>/download", methods=["GET"])
def download_resume(resume_id: int):
    row = db.get_resume(resume_id)
    if not row:
        return jsonify({"error": "not found"}), 404
    file_path = resume_files.resolve_resume_path(row["file_path"])
    if file_path is None:
        return jsonify({"error": "invalid path"}), 403
    if not file_path.exists():
        return jsonify({"error": "file not found on disk"}), 404
    return send_file(
        str(file_path),
        as_attachment=True,
        download_name=file_path.name,
    )


@bp.route("/api/resumes/<int:resume_id>/view", methods=["GET"])
def view_resume(resume_id: int):
    row = db.get_resume(resume_id)
    if not row:
        return jsonify({"error": "not found"}), 404
    file_path = resume_files.resolve_resume_path(row["file_path"])
    if file_path is None:
        return jsonify({"error": "invalid path"}), 403
    if not file_path.exists():
        return jsonify({"error": "file not found on disk"}), 404
    return send_file(str(file_path), as_attachment=False, mimetype="application/pdf")


@bp.route("/api/resumes/<int:resume_id>/reveal", methods=["POST"])
def reveal_resume(resume_id: int):
    """Open the host file manager (Windows Explorer / Finder) on the resume file."""
    row = db.get_resume(resume_id)
    if not row:
        return jsonify({"error": "not found"}), 404
    file_path = resume_files.resolve_resume_path(row["file_path"])
    if file_path is None:
        return jsonify({"error": "invalid path"}), 403
    if not file_path.exists():
        return jsonify({"error": "file not found on disk"}), 404
    ok, message = resume_files.reveal_in_file_manager(file_path)
    if not ok:
        return jsonify({"error": message}), 500
    return jsonify({"revealed": message})


# ── Interview Q&A ─────────────────────────────────────────────────────────────


@bp.route("/api/interview-qa/template", methods=["GET"])
def list_qa_template():
    return jsonify(db.list_qa_template())


@bp.route("/api/interview-qa/template", methods=["POST"])
def create_qa_template():
    data = request.get_json(force=True, silent=True) or {}
    data["is_template"] = 1
    return jsonify(db.create_qa(None, data)), 201


@bp.route("/api/interview-qa/<int:qa_id>", methods=["PATCH"])
def update_qa(qa_id: int):
    data = request.get_json(force=True, silent=True) or {}
    result = db.update_qa(qa_id, data)
    return jsonify(result) if result else ("", 404)


@bp.route("/api/interview-qa/<int:qa_id>", methods=["DELETE"])
def delete_qa(qa_id: int):
    db.delete_qa(qa_id)
    return "", 204


@bp.route("/api/applications/<int:app_id>/interview-qa", methods=["GET"])
def list_app_qa(app_id: int):
    return jsonify(db.list_app_qa(app_id))


@bp.route("/api/applications/<int:app_id>/interview-qa", methods=["POST"])
def create_app_qa(app_id: int):
    data = request.get_json(force=True, silent=True) or {}
    return jsonify(db.create_qa(app_id, data)), 201


@bp.route("/api/applications/<int:app_id>/interview-qa/from-template", methods=["POST"])
def clone_qa_template(app_id: int):
    rows = db.clone_template_to_app(app_id)
    return jsonify(rows)


# ── Autopilot: ready to send / needs you ──────────────────────────────────────
# Approve and approve-all only change status. The submit worker (submitter.py)
# is the one thing that opens a browser, one row at a time.


def _resume_url(app_id: int) -> str:
    resumes = db.list_app_resumes(app_id)
    pdf = next((r for r in resumes if (r.get("file_path") or "").lower().endswith(".pdf")), None)
    return f"/jobs/api/resumes/{pdf['id']}/view" if pdf else ""


def _screenshot_url(app: dict) -> str:
    return f"/jobs/api/applications/{app['id']}/screenshot" if app.get("screenshot_path") else ""


@bp.route("/api/ready", methods=["GET"])
def list_ready():
    ready = [
        {**a, "form": db.get_form(a["id"]), "resume_url": _resume_url(a["id"])}
        for a in db.list_ready()
    ]
    needs_you = [
        {**a, "reason": a.get("submit_log", ""), "screenshot_url": _screenshot_url(a),
         "form": db.get_form(a["id"]), "resume_url": _resume_url(a["id"])}
        for a in db.list_needs_you()
    ]
    return jsonify({"ready": ready, "needs_you": needs_you})


def _status_change(ok: bool, app_id: int, expected: str):
    if not ok:
        return jsonify({"error": f"application is not {expected}"}), 409
    return jsonify(db.get_application(app_id))


@bp.route("/api/applications/<int:app_id>/approve", methods=["POST"])
def approve_application(app_id: int):
    return _status_change(db.approve(app_id), app_id, "ready")


@bp.route("/api/applications/<int:app_id>/skip", methods=["POST"])
def skip_application(app_id: int):
    return _status_change(db.skip(app_id), app_id, "ready")


@bp.route("/api/applications/<int:app_id>/answers", methods=["POST"])
def save_form_answers(app_id: int):
    """{"<form_field id>": value} -> the same validated write the sweep uses."""
    from . import sweep_prep

    errors = sweep_prep.save_answers(app_id, request.get_json(force=True, silent=True) or {}, source="you")
    if errors:
        return jsonify({"error": "; ".join(errors)}), 400
    return jsonify({"form": db.get_form(app_id)})


@bp.route("/api/applications/<int:app_id>/mark-sent", methods=["POST"])
def mark_sent_application(app_id: int):
    return _status_change(db.mark_sent(app_id), app_id, "manual_only or manual")


@bp.route("/api/ready/approve-all", methods=["POST"])
def approve_all_ready():
    return jsonify({"approved": db.approve_all_ready()})


@bp.route("/api/applications/<int:app_id>/resolve", methods=["POST"])
def resolve_application(app_id: int):
    outcome = (request.get_json(force=True, silent=True) or {}).get("outcome")
    if outcome not in ("applied", "closed"):
        return jsonify({"error": "outcome must be applied or closed"}), 400
    return _status_change(db.resolve_unconfirmed(app_id, outcome), app_id, "unconfirmed")


@bp.route("/api/applications/<int:app_id>/screenshot", methods=["GET"])
def application_screenshot(app_id: int):
    app = db.get_application(app_id)
    stored = (app or {}).get("screenshot_path") or ""
    path = (resume_files._VAULT_ROOT / stored).resolve() if stored else None
    # Same containment rule as resume files: only a .png under data/resumes/.
    if (
        path is None
        or Path(stored).is_absolute()
        or not path.is_relative_to(resume_files.RESUME_ROOT)
        or path.suffix.lower() != ".png"
    ):
        return jsonify({"error": "not found"}), 404
    if not path.exists():
        return jsonify({"error": "file not found on disk"}), 404
    return send_file(str(path), mimetype="image/png")
