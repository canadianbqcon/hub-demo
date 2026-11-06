"""Purchases Hub blueprint — routes under /purchases.

Ported from the legacy 5001 dashboard. Differences:
- The live-reload SSE (/api/events) is dropped: the Hub runs no vault watcher /
  event queue, so there is nothing to stream. The frontend no longer subscribes.
- The VaultReader behind /api/nodes and /api/node is built lazily (mirroring the
  trips port) instead of being injected through an init(reader, event_queue) call.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    jsonify,
    make_response,
    render_template,
    request,
)

from . import db

bp = Blueprint(
    "purchases",
    __name__,
    template_folder="frontend",
    static_folder="frontend/static",
    url_prefix="/purchases",
)

# dashboard/ on sys.path → vault_path, vault_reader (the Hub already inserts it,
# but make the blueprint importable standalone too).
if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vault_path import vault_root  # noqa: E402

_VAULT_ROOT = vault_root()

# VaultReader is optional and lazily built on first node lookup — the wiki may be
# absent on a given machine, and most purchases traffic never touches it.
_reader = None
_reader_tried = False


def _get_reader():
    global _reader, _reader_tried
    if _reader is None and not _reader_tried:
        _reader_tried = True
        try:
            from vault_reader import VaultReader

            _reader = VaultReader(_VAULT_ROOT / "wiki")
        except Exception as e:  # pragma: no cover
            logger.warning("VaultReader unavailable: %s", e)
    return _reader


# ── Page ──────────────────────────────────────────────────────────────────────


# Single source of truth for the launcher list — see hub_modules.py. The launcher
# marks the current tile from the URL path (isCurrentPath in chrome.jsx /
# theme-switch.js), not a hardcoded meta=="current", so one shared list is correct
# on every page. (Was a hand-synced local copy that drifted.)
from hub_modules import MODULES as _MODULES

logger = logging.getLogger(__name__)


def _render_ctx() -> dict:
    """Template globals the shared Hub chrome needs: password-gate flag, the
    module launcher list, and live connector dots. The connector checks are the
    cheap is_authenticated()/is_configured() calls (token/config presence), NOT
    the ~2s live home data fetch. This is the one allowed backend touch — it
    injects chrome data only; no endpoint or data-logic change."""
    connectors = {}
    try:
        import gcal  # top-level modules in dashboard/, already on sys.path
        import gmail
        from finances import book

        connectors = {
            "gcal": gcal.is_authenticated(),
            "gmail": gmail.is_authenticated(),
            "ynab": book.is_configured(),
        }
    except Exception as e:  # chrome still renders with empty/dim connector dots
        logger.warning("connector ctx unavailable: %s", e)
    return {
        "exposed": current_app.config.get("EXPOSED", False),
        "modules": _MODULES,
        "connectors": connectors,
    }


@bp.route("/")
def index():
    # never let the browser serve a stale HTML document — the page references
    # versioned css/js, but the document itself must always re-fetch so layout
    # changes land on a plain reload (no hard-refresh needed).
    resp = make_response(render_template("purchases.html", **_render_ctx()))
    resp.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
    return resp


# ── Projects ──────────────────────────────────────────────────────────────────


@bp.route("/api/projects", methods=["GET"])
def list_projects():
    return jsonify(db.list_projects())


@bp.route("/api/projects", methods=["POST"])
def create_project():
    data = request.get_json(force=True, silent=True) or {}
    return jsonify(db.create_project(data)), 201


@bp.route("/api/projects/<int:pid>", methods=["GET"])
def get_project(pid):
    full = db.get_full_project(pid)
    if not full:
        return jsonify({"error": "not found"}), 404
    return jsonify(full)


@bp.route("/api/projects/<int:pid>", methods=["PATCH"])
def patch_project(pid):
    data = request.get_json(force=True, silent=True) or {}
    updated = db.update_project(pid, data)
    return jsonify(updated) if updated else (jsonify({"error": "not found"}), 404)


@bp.route("/api/projects/<int:pid>", methods=["DELETE"])
def delete_project(pid):
    if db.delete_project(pid):
        return "", 204
    return jsonify({"error": "not found"}), 404


# ── Decisions ─────────────────────────────────────────────────────────────────


@bp.route("/api/decisions", methods=["GET"])
def list_decisions():
    return jsonify(db.list_decisions())


@bp.route("/api/decisions", methods=["POST"])
def create_decision():
    data = request.get_json(force=True, silent=True) or {}
    return jsonify(db.create_decision(data)), 201


@bp.route("/api/decisions/<int:did>", methods=["GET"])
def get_decision(did):
    full = db.get_full_decision(did)
    if not full:
        return jsonify({"error": "not found"}), 404
    return jsonify(full)


@bp.route("/api/decisions/<int:did>", methods=["PATCH"])
def patch_decision(did):
    data = request.get_json(force=True, silent=True) or {}
    updated = db.update_decision(did, data)
    if not updated:
        return jsonify({"error": "not found"}), 404
    return jsonify(updated)


@bp.route("/api/decisions/<int:did>", methods=["DELETE"])
def delete_decision(did):
    ok = db.delete_decision(did)
    return ("", 204) if ok else (jsonify({"error": "not found"}), 404)


# ── Generic sub-resource route builder ────────────────────────────────────────


def _register_sub(parent: str, child: str, add_fn, update_fn, delete_fn):
    """Register POST/PATCH/DELETE routes for a child resource under a parent."""
    base = f"/api/{parent}/<int:pid>/{child}"

    def _post(pid):
        data = request.get_json(force=True, silent=True) or {}
        return jsonify(add_fn(pid, data)), 201

    def _patch(pid, sub_id):
        data = request.get_json(force=True, silent=True) or {}
        row = update_fn(pid, sub_id, data)
        if not row:
            return jsonify({"error": "not found"}), 404
        return jsonify(row)

    def _delete(pid, sub_id):
        ok = delete_fn(pid, sub_id)
        return ("", 204) if ok else (jsonify({"error": "not found"}), 404)

    bp.add_url_rule(base, f"{child}_post", _post, methods=["POST"])
    bp.add_url_rule(f"{base}/<int:sub_id>", f"{child}_patch", _patch, methods=["PATCH"])
    bp.add_url_rule(f"{base}/<int:sub_id>", f"{child}_delete", _delete, methods=["DELETE"])


# Decision-scoped sub-resources
_register_sub("decisions", "candidates", db.add_candidate, db.update_candidate, db.delete_candidate)
_register_sub("decisions", "criteria", db.add_criterion, db.update_criterion, db.delete_criterion)
_register_sub("decisions", "reviews", db.add_review, db.update_review, db.delete_review)
_register_sub("decisions", "budget", db.add_budget, db.update_budget, db.delete_budget)

# Candidate-scoped sub-resources
_register_sub("candidates", "specs", db.add_spec, db.update_spec, db.delete_spec)
_register_sub("candidates", "pros-cons", db.add_proscon, db.update_proscon, db.delete_proscon)
_register_sub("candidates", "prices", db.add_price, db.update_price, db.delete_price)

# Pipeline research sub-resources (decision-scoped)
_register_sub("decisions", "dimensions", db.add_dimension, db.update_dimension, db.delete_dimension)
_register_sub("decisions", "brands", db.add_brand, db.update_brand, db.delete_brand)
_register_sub("decisions", "evidence", db.add_evidence, db.update_evidence, db.delete_evidence)
_register_sub("decisions", "price-steps", db.add_price_step, db.update_price_step, db.delete_price_step)
_register_sub("decisions", "constraints", db.add_constraint, db.update_constraint, db.delete_constraint)


# ── Constraint checks (upsert keyed by constraint, like scores) ───────────────


@bp.route("/api/candidates/<int:cid>/constraint-checks", methods=["POST"])
def set_constraint_check(cid):
    """Upsert one candidate's check on one constraint. Body: {constraint_id, status, note?}."""
    data = request.get_json(force=True, silent=True) or {}
    try:
        constraint_id = int(data["constraint_id"])
        status = str(data["status"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "constraint_id and status required"}), 400
    if status not in ("pass", "fail", "unknown"):
        return jsonify({"error": "status must be pass|fail|unknown"}), 400
    return jsonify(db.set_constraint_check(cid, constraint_id, status, data.get("note", ""))), 201


# ── Orders — every purchase and where it is ───────────────────────────────────


@bp.route("/api/orders", methods=["GET"])
def list_orders():
    return jsonify(db.list_orders())


@bp.route("/api/orders", methods=["POST"])
def create_order():
    data = request.get_json(force=True, silent=True) or {}
    if not (data.get("item") or "").strip():
        return jsonify({"error": "item required"}), 400
    return jsonify(db.create_order(data)), 201


@bp.route("/api/orders/<int:oid>", methods=["PATCH"])
def patch_order(oid):
    data = request.get_json(force=True, silent=True) or {}
    updated = db.update_order(oid, data)
    return jsonify(updated) if updated else (jsonify({"error": "not found"}), 404)


@bp.route("/api/orders/<int:oid>", methods=["DELETE"])
def delete_order(oid):
    return ("", 204) if db.delete_order(oid) else (jsonify({"error": "not found"}), 404)


@bp.route("/api/orders/scan", methods=["POST"])
def scan_orders():
    """Fold recent order/shipping email into the orders table. Read-only against
    Gmail — it never labels, moves or deletes a message; the write is local."""
    data = request.get_json(force=True, silent=True) or {}
    try:
        days = max(1, min(365, int(data.get("days", 45))))
    except (TypeError, ValueError):
        days = 45
    from . import orders_mail

    try:
        report = orders_mail.scan(db, days=days)
    except Exception as e:  # a Gmail hiccup is a message in the UI, not a 500 page
        logger.exception("order mail scan failed")
        return jsonify({"error": str(e)}), 502
    return (jsonify(report), 502) if report.get("error") else jsonify(report)


# ── Pipeline section state + checkpoint ───────────────────────────────────────


@bp.route("/api/decisions/<int:did>/sections", methods=["PATCH"])
def patch_section(did):
    """Set one section's status chip. Body: {section, status}."""
    data = request.get_json(force=True, silent=True) or {}
    section, status = data.get("section"), data.get("status")
    if section not in db.PIPELINE_SECTIONS:
        return jsonify({"error": "unknown section"}), 400
    if status not in ("pending", "researching", "awaiting-you", "done", "skipped", "stale", "error"):
        return jsonify({"error": "unknown status"}), 400
    if not db.get_decision(did):
        return jsonify({"error": "not found"}), 404
    return jsonify(db.set_section_status(did, section, status))


@bp.route("/api/decisions/<int:did>/confirm-priorities", methods=["POST"])
def confirm_priorities(did):
    """The checkpoint. 409 unless the priorities section is awaiting-you."""
    if not db.get_decision(did):
        return jsonify({"error": "not found"}), 404
    try:
        return jsonify(db.confirm_priorities(did))
    except ValueError as e:
        return jsonify({"error": str(e)}), 409


# ── Candidate scores (upsert keyed by criterion, not a generic sub-resource) ──


@bp.route("/api/candidates/<int:cid>/scores", methods=["POST"])
def set_score(cid):
    """Upsert one candidate's score on one criterion. Body: {criterion_id, score, notes?}."""
    data = request.get_json(force=True, silent=True) or {}
    try:
        criterion_id = int(data["criterion_id"])
        score = float(data["score"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "criterion_id and numeric score required"}), 400
    return jsonify(db.set_score(cid, criterion_id, score, data.get("notes", ""))), 201


@bp.route("/api/candidates/<int:cid>/scores/<int:criterion_id>", methods=["DELETE"])
def delete_score(cid, criterion_id):
    """Clear a candidate's score on one criterion (mark that cell unscored)."""
    ok = db.delete_score(cid, criterion_id)
    return ("", 204) if ok else (jsonify({"error": "not found"}), 404)


# ── Vault lookups (read-only) ─────────────────────────────────────────────────


@bp.route("/api/nodes", methods=["GET"])
def list_nodes():
    types = request.args.get("types", "").split(",") if request.args.get("types") else None
    tags_any = (
        request.args.get("tags_any", "").split(",") if request.args.get("tags_any") else None
    )
    reader = _get_reader()
    nodes = reader.get_nodes(types=types, tags_any=tags_any) if reader else []
    return jsonify(
        [
            {
                "path": n.path,
                "title": n.title,
                "type": n.type,
                "summary": n.summary,
                "tags": n.tags,
                "updated": n.updated,
            }
            for n in nodes[:200]
        ]
    )


@bp.route("/api/node", methods=["GET"])
def get_node():
    path = request.args.get("path", "")
    reader = _get_reader()
    if not path or not reader:
        return jsonify({"error": "missing path"}), 400
    n = reader.get_node(path)
    if not n:
        return jsonify({"error": "not found"}), 404
    return jsonify(
        {
            "path": n.path,
            "title": n.title,
            "type": n.type,
            "summary": n.summary,
            "tags": n.tags,
            "body": n.body,
            "relationships": n.relationships,
            "created": n.created,
            "updated": n.updated,
        }
    )
