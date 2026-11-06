from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from . import db

bp = Blueprint(
    "checklists",
    __name__,
    template_folder="frontend",
    static_folder="frontend/static",
    url_prefix="/checklists",
)


# ── Page ──────────────────────────────────────────────────────────────────────


@bp.route("/")
def index():
    return render_template("checklists.html")


# ── Checklists ────────────────────────────────────────────────────────────────


@bp.route("/api/checklists", methods=["GET"])
def list_checklists():
    return jsonify(db.list_checklists())


@bp.route("/api/checklists", methods=["POST"])
def create_checklist():
    data = request.get_json(force=True, silent=True) or {}
    if not data.get("name"):
        return jsonify({"error": "name required"}), 400
    return jsonify(db.create_checklist(data)), 201


@bp.route("/api/checklists/<int:cid>", methods=["GET"])
def get_checklist(cid):
    cl = db.get_checklist(cid)
    if not cl:
        return jsonify({"error": "not found"}), 404
    return jsonify(cl)


@bp.route("/api/checklists/<int:cid>", methods=["PATCH"])
def update_checklist(cid):
    data = request.get_json(force=True, silent=True) or {}
    try:
        cl = db.update_checklist(cid, data)
    except db.ProtectedChecklist as e:
        return jsonify({"error": str(e), "protected": True}), 409
    if not cl:
        return jsonify({"error": "not found"}), 404
    return jsonify(cl)


@bp.route("/api/checklists/<int:cid>", methods=["DELETE"])
def delete_checklist(cid):
    try:
        ok = db.delete_checklist(cid)
    except db.ProtectedChecklist as e:
        # The grocery list is shared with /recipes; deleting it would break that link.
        return jsonify({"error": str(e), "protected": True}), 409
    return ("", 204) if ok else (jsonify({"error": "not found"}), 404)


@bp.route("/api/grocery", methods=["GET"])
def api_grocery():
    """The canonical grocery list — the same rows /recipes writes to."""
    return jsonify(db.ensure_grocery_list())


@bp.route("/api/checklists/<int:cid>/clear-checked", methods=["POST"])
def clear_checked(cid):
    removed = db.clear_checked(cid)
    return jsonify({"removed": removed, "checklist": db.get_checklist(cid)})


@bp.route("/api/checklists/<int:cid>/reset", methods=["POST"])
def reset_checklist(cid):
    cl = db.reset_checklist(cid)
    if not cl:
        return jsonify({"error": "not found"}), 404
    return jsonify(cl)


# ── Items ─────────────────────────────────────────────────────────────────────


@bp.route("/api/checklists/<int:cid>/items", methods=["POST"])
def add_item(cid):
    data = request.get_json(force=True, silent=True) or {}
    if not data.get("text"):
        return jsonify({"error": "text required"}), 400
    return jsonify(db.add_item(cid, data)), 201


@bp.route("/api/checklists/<int:cid>/items/<int:item_id>", methods=["PATCH"])
def update_item(cid, item_id):
    data = request.get_json(force=True, silent=True) or {}
    row = db.update_item(cid, item_id, data)
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify(row)


@bp.route("/api/checklists/<int:cid>/items/<int:item_id>", methods=["DELETE"])
def delete_item(cid, item_id):
    ok = db.delete_item(cid, item_id)
    return ("", 204) if ok else (jsonify({"error": "not found"}), 404)


@bp.route("/api/checklists/<int:cid>/items/reorder", methods=["POST"])
def reorder_items(cid):
    data = request.get_json(force=True, silent=True) or {}
    ids = data.get("ids", [])
    if not isinstance(ids, list):
        return jsonify({"error": "ids must be a list"}), 400
    db.reorder_items(cid, ids)
    return jsonify({"ok": True})


# ── Sections ──────────────────────────────────────────────────────────────────


@bp.route("/api/checklists/<int:cid>/sections/rename", methods=["POST"])
def rename_section(cid):
    data = request.get_json(force=True, silent=True) or {}
    to_name = (data.get("to") or "").strip()
    if not to_name:
        return jsonify({"error": "to required"}), 400
    db.rename_section(cid, data.get("from", ""), to_name)
    return jsonify({"ok": True})


@bp.route("/api/checklists/<int:cid>/sections/delete", methods=["POST"])
def delete_section(cid):
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name", "")
    keep = data.get("keep_items", True)
    db.delete_section(cid, name, keep_items=keep)
    return ("", 204)
