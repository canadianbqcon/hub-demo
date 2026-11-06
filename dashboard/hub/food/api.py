"""Food Hub blueprint — routes under /food.

GET-only on purpose. The /food skill is the only writer; this module renders what a
research run produced and can never modify it.
"""

from __future__ import annotations

from flask import Blueprint, abort, jsonify, redirect, render_template, request

from . import db

bp = Blueprint(
    "food",
    __name__,
    template_folder="frontend",
    static_folder="frontend/static",
    url_prefix="/food",
)


@bp.route("/")
def index():
    return render_template("food.html", view="areas")


@bp.route("/<path:area_slug>")
def area(area_slug: str):
    """One page per area, at any grain, real or derived from places.

    The resolve happens here rather than in the client because only a server redirect moves
    the address bar. A 302 on the API route would be followed by fetch() transparently: the
    page would render correctly and leave the user holding a stale URL that looks canonical.
    """
    try:
        resolved = db.resolve_area(area_slug)
    except db.AmbiguousArea:
        abort(409)
    if resolved is None:
        # Same empty state as before, now with the status to match it.
        return render_template("food.html", view="area", area_slug=area_slug), 404
    if resolved["slug"] != area_slug:
        return redirect(f"/food/{resolved['slug']}")
    return render_template("food.html", view="area", area_slug=area_slug)


@bp.route("/api/areas")
def api_areas():
    return jsonify(db.get_areas())


@bp.route("/api/area/<path:slug>")
def api_area(slug: str):
    """Everything the page needs about one area: itself, what it sits in, what sits in it.

    No redirect here on purpose — see the page route. `area.slug` is already canonical, so a
    client that cares can compare.
    """
    try:
        resolved = db.resolve_area(slug)
    except db.AmbiguousArea as e:
        return jsonify({"error": str(e)}), 409
    if resolved is None:
        abort(404)
    return jsonify({
        "area": resolved,
        "ancestors": db.ancestors_of(resolved),
        "children": db.get_children(resolved),
    })


def _level_arg(name: str):
    """Three states from two query params: absent, a value, or explicitly none."""
    if request.args.get(f"{name}_none"):
        return None
    return request.args.get(name, db.ANY)


@bp.route("/api/places")
def api_places():
    min_depth = request.args.get("min_depth", type=float)
    return jsonify(db.get_places(
        city=request.args.get("city"),
        borough=_level_arg("borough"),
        neighborhood=_level_arg("neighborhood"),
        cuisine_broad=request.args.get("cuisine_broad"),
        cuisine_specific=request.args.get("cuisine_specific"),
        discovery=request.args.get("discovery"),
        price_band=request.args.get("price_band"),
        min_depth=min_depth,
    ))


@bp.route("/api/place/<slug>")
def api_place(slug: str):
    place = db.get_place(slug)
    if place is None:
        abort(404)
    place["evidence"] = db.get_evidence(place["id"])
    return jsonify(place)
