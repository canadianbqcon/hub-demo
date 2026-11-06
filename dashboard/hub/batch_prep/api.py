from __future__ import annotations

from flask import Blueprint, jsonify, redirect, request

from . import db

# Batch-prep surface for Juniper & Co, served by the Hub app (port 5002). The
# DATA API still lives here at /batch/api/batch/* and is unchanged; the page
# itself moved into the juniper & co umbrella (/jc/#batch, with the storage map
# lifted out to its own /jc/#map tab) when the three J&Co surfaces merged onto
# one tabbed page. Vanilla JS + fetch + a {status: ok|error} JSON envelope.
#
# Phase B endpoints: the scalable recipe viewer (list + detail) and the textual
# storage map (GET/PUT). Scaling itself is pure client-side and has no endpoint.
# Phase C endpoints: the prep-day planner (create / active / toggle component / reset).

bp = Blueprint(
    "batch_prep",
    __name__,
    template_folder="frontend",
    static_folder="frontend/static",
    url_prefix="/batch",
)


def _ok(data):
    return jsonify({"status": "ok", "data": data})


def _err(message: str, code: int = 400):
    return jsonify({"status": "error", "message": message}), code


@bp.route("/")
def index():
    """The page is a tab of /jc/ now — see the module note above. 308 so
    bookmarks and the phone's home-screen shortcut still land right."""
    return redirect("/jc/#batch", code=308)


@bp.route("/api/batch/recipes")
def api_recipes():
    """List recipes of one kind (default 'batch'): id + name, alpha."""
    kind = (request.args.get("kind") or "batch").strip()
    return _ok(db.list_recipes(kind=kind))


@bp.route("/api/batch/recipe/<int:recipe_id>")
def api_recipe(recipe_id: int):
    """Full recipe for the viewer: header, yield, structured ingredients."""
    recipe = db.get_recipe(recipe_id)
    if recipe is None:
        return _err(f"recipe {recipe_id} not found", 404)
    return _ok(recipe)


@bp.route("/api/batch/storage", methods=["GET", "PUT"])
def api_storage():
    """The textual storage map (single-row storage_note). GET reads, PUT overwrites."""
    if request.method == "GET":
        return _ok(db.get_storage())
    payload = request.get_json(silent=True) or {}
    body = payload.get("body")
    if body is None:
        return _err("body required", 400)
    if not isinstance(body, str):
        return _err("body must be a string", 400)
    return _ok(db.set_storage(body))


# ── Structured storage map (Phase D) ───────────────────────────────────────────
# The map view's live data: a four-level tree (area → unit → section → item) with
# full CRUD + up/down reorder. Every mutation returns the whole tree under
# {"tree": ...} so the frontend re-renders from authoritative state; adds also
# return {"new_id": ...}. The textual GET/PUT above stays as the archive blob.

_KINDS = ("area", "unit", "section", "subsection", "item")


@bp.route("/api/batch/storage/tree")
def api_storage_tree():
    """The full structured storage tree (areas → units → sections → items)."""
    return _ok(db.get_storage_tree())


@bp.route("/api/batch/storage/<kind>", methods=["POST"])
def api_storage_add(kind: str):
    """Append a node of `kind` under parent_id (null for an area). Returns tree + new_id."""
    if kind not in _KINDS:
        return _err(f"unknown level: {kind}", 400)
    payload = request.get_json(silent=True) or {}
    parent_id = payload.get("parent_id")
    label = payload.get("label", "")
    if kind != "area" and not isinstance(parent_id, int):
        return _err("parent_id (int) required", 400)
    if not isinstance(label, str):
        return _err("label must be a string", 400)
    if kind == "item" and not label.strip():
        return _err("item text required", 400)
    try:
        return _ok(db.add_node(kind, parent_id if kind != "area" else None, label))
    except ValueError as e:
        return _err(str(e), 400)


@bp.route("/api/batch/storage/<kind>/<int:node_id>", methods=["PUT"])
def api_storage_rename(kind: str, node_id: int):
    """Rename a node (label = name, or `text` for an item)."""
    if kind not in _KINDS:
        return _err(f"unknown level: {kind}", 400)
    payload = request.get_json(silent=True) or {}
    label = payload.get("label")
    if not isinstance(label, str):
        return _err("label (string) required", 400)
    if kind == "item" and not label.strip():
        return _err("item text can't be empty", 400)
    try:
        return _ok(db.rename_node(kind, node_id, label))
    except ValueError as e:
        return _err(str(e), 404)


@bp.route("/api/batch/storage/<kind>/<int:node_id>", methods=["DELETE"])
def api_storage_delete(kind: str, node_id: int):
    """Delete a node; its children cascade."""
    if kind not in _KINDS:
        return _err(f"unknown level: {kind}", 400)
    try:
        return _ok(db.delete_node(kind, node_id))
    except ValueError as e:
        return _err(str(e), 404)


@bp.route("/api/batch/storage/<kind>/<int:node_id>/move", methods=["POST"])
def api_storage_move(kind: str, node_id: int):
    """Reorder a node up/down within its parent (sort_order swap)."""
    if kind not in _KINDS:
        return _err(f"unknown level: {kind}", 400)
    payload = request.get_json(silent=True) or {}
    direction = payload.get("direction")
    if direction not in ("up", "down"):
        return _err("direction must be 'up' or 'down'", 400)
    try:
        return _ok(db.move_node(kind, node_id, direction))
    except ValueError as e:
        return _err(str(e), 400)


@bp.route("/api/batch/storage/item/<int:item_id>/note", methods=["PUT"])
def api_storage_item_note(item_id: int):
    """Set an item's note (the small grey detail under its name)."""
    payload = request.get_json(silent=True) or {}
    note = payload.get("note", "")
    if not isinstance(note, str):
        return _err("note must be a string", 400)
    try:
        return _ok(db.set_item_note(item_id, note))
    except ValueError as e:
        return _err(str(e), 404)


@bp.route("/api/batch/storage/item/<int:item_id>/reparent", methods=["POST"])
def api_storage_item_reparent(item_id: int):
    """Move an item to another section."""
    payload = request.get_json(silent=True) or {}
    section_id = payload.get("section_id")
    if not isinstance(section_id, int):
        return _err("section_id (int) required", 400)
    try:
        return _ok(db.reparent_item(item_id, section_id))
    except ValueError as e:
        return _err(str(e), 400)


# ── Prep-day planner (Phase C) ─────────────────────────────────────────────────


@bp.route("/api/batch/prep-day", methods=["POST"])
def api_prep_day_create():
    """Start a prep day from selected recipe ids → generate + persist the steps."""
    payload = request.get_json(silent=True) or {}
    recipe_ids = payload.get("recipe_ids")
    if not isinstance(recipe_ids, list) or not recipe_ids:
        return _err("recipe_ids must be a non-empty list", 400)
    if not all(isinstance(i, int) for i in recipe_ids):
        return _err("recipe_ids must be integers", 400)
    try:
        return _ok(db.create_prep_day(recipe_ids))
    except ValueError as e:
        return _err(str(e), 400)


@bp.route("/api/batch/prep-day/add", methods=["POST"])
def api_prep_day_add():
    """Append recipes to the active prep day as a new standalone stage (a queue)."""
    payload = request.get_json(silent=True) or {}
    recipe_ids = payload.get("recipe_ids")
    if not isinstance(recipe_ids, list) or not recipe_ids:
        return _err("recipe_ids must be a non-empty list", 400)
    if not all(isinstance(i, int) for i in recipe_ids):
        return _err("recipe_ids must be integers", 400)
    try:
        return _ok(db.add_to_prep_day(recipe_ids))
    except ValueError as e:
        return _err(str(e), 400)


@bp.route("/api/batch/prep-day/active")
def api_prep_day_active():
    """The active prep day (selection + ordered steps), or null when none is open."""
    return _ok(db.get_active_prep_day())


@bp.route("/api/batch/prep-day/component/<int:cid>", methods=["PUT"])
def api_prep_day_component(cid: int):
    """Toggle a recipe sub-item's checked state (the primary check action, Stage B).

    Checks live on the build-up/assemble composition rows, not the step header — the
    old PUT .../step/<id> endpoint was retired with this change.
    """
    result = db.toggle_component(cid)
    if result is None:
        return _err(f"component {cid} not found", 404)
    return _ok(result)


@bp.route("/api/batch/prep-day/reset", methods=["POST"])
def api_prep_day_reset():
    """Clear the active prep day so the next create starts fresh."""
    return _ok(db.reset_prep_day())
