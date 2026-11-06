"""Recipes Hub blueprint — routes under /recipes.

Read-only over the recipe notes: nothing here writes a .md file. The module's only write
is to the canonical grocery list, and that goes through checklists/db.py rather than a
local copy, so /recipes and /checklists are two doors onto one list.
"""

from __future__ import annotations

from fractions import Fraction

from flask import Blueprint, abort, jsonify, render_template, request, send_file

from checklists import db as checklists_db

from . import scale, store

bp = Blueprint(
    "recipes",
    __name__,
    template_folder="frontend",
    static_folder="frontend/static",
    url_prefix="/recipes",
)

# Fields the index page never uses. Dropping them keeps the one-shot payload lean; the
# detail route serves them per recipe instead.
_DETAIL_ONLY = ("directions", "notes", "ingredients")


@bp.route("/")
def index():
    return render_template("recipes.html", view="index", slug="")


@bp.route("/<slug>")
def detail(slug: str):
    if store.get(slug) is None:
        return render_template("recipes.html", view="detail", slug=slug), 404
    return render_template("recipes.html", view="detail", slug=slug)


@bp.route("/api/index")
def api_index():
    light = [{k: v for k, v in r.items() if k not in _DETAIL_ONLY}
             for r in store.all_recipes()]
    return jsonify({"recipes": light, "categories": store.categories()})


@bp.route("/api/recipe/<slug>")
def api_recipe(slug: str):
    """One recipe, optionally scaled.

    `servings` targets a count (only meaningful when the note has a parseable base);
    `factor` is the base-free multiplier the 49 notes without one fall back to.
    """
    rec = store.get(slug)
    if rec is None:
        abort(404)
    out = dict(rec)
    factor = _requested_factor(rec)
    out["factor"] = f"{float(factor):g}"
    out["scaled_ingredients"] = [scale.scale_line(ln, factor) for ln in rec["ingredients"]]
    return jsonify(out)


def _requested_factor(rec: dict) -> Fraction:
    """Resolve the scale factor from the query, refusing anything absurd."""
    target = request.args.get("servings", type=int)
    if target and rec.get("servings"):
        factor = Fraction(target, rec["servings"])
    else:
        raw = request.args.get("factor", type=float)
        factor = Fraction(raw).limit_denominator(24) if raw else Fraction(1)
    # A 50x recipe is a typo or a crafted URL, not a dinner party.
    if factor <= 0 or factor > 20:
        return Fraction(1)
    return factor


@bp.route("/api/photo/<path:filename>")
@bp.route("/photo/<path:filename>")
def photo(filename: str):
    path = store.photo_path(filename)
    if path is None:
        abort(404)
    return send_file(path, max_age=86400)


@bp.route("/api/pantry", methods=["POST"])
def api_pantry():
    data = request.get_json(force=True, silent=True) or {}
    have = data.get("have") or []
    if isinstance(have, str):
        have = [ln for ln in have.replace(",", "\n").splitlines()]
    return jsonify({"matches": store.match_pantry(have)[:60]})


@bp.route("/api/grocery", methods=["GET"])
def api_grocery():
    """The shared list, read through checklists.db — /recipes keeps no copy of it."""
    return jsonify(checklists_db.ensure_grocery_list())


@bp.route("/api/grocery/add", methods=["POST"])
def api_grocery_add():
    """Consolidate the selected recipes and append them to the shared grocery list.

    Each selection may carry its own scale, so a doubled recipe contributes doubled
    quantities. The whole batch lands in one transaction — a half-added shopping list is
    worse than a failed one.
    """
    data = request.get_json(force=True, silent=True) or {}
    selections = data.get("recipes") or []
    entries = []
    for sel in selections:
        rec = store.get(sel.get("slug", "")) if isinstance(sel, dict) else store.get(sel)
        if rec is None:
            continue
        factor = Fraction(1)
        if isinstance(sel, dict):
            if sel.get("servings") and rec.get("servings"):
                factor = Fraction(int(sel["servings"]), rec["servings"])
            elif sel.get("factor"):
                factor = Fraction(float(sel["factor"])).limit_denominator(24)
        if factor <= 0 or factor > 20:
            factor = Fraction(1)
        for line in rec["ingredients"]:
            p = scale.parse_ingredient(line)
            entries.append({
                "raw": scale.scale_line(line, factor)["text"],
                "qty": p["qty"] * factor if p["qty"] is not None else None,
                "unit": p["unit"],
                "name": p["name"],
                "has_unscaled": p["has_unscaled"],
                "recipe": rec["dish"],
            })
    if not entries:
        return jsonify({"error": "no recipes resolved"}), 400

    items = [{"text": it["text"], "section": scale.aisle_for(it["name"])}
             for it in scale.consolidate(entries)]
    grocery = checklists_db.ensure_grocery_list()
    added = checklists_db.add_items_bulk(grocery["id"], items)
    return jsonify({"added": added, "checklist_id": grocery["id"],
                    "checklist": checklists_db.get_checklist(grocery["id"])})
