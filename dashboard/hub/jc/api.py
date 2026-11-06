from __future__ import annotations

from flask import Blueprint, render_template

# The Juniper & Co umbrella: ONE page, three tabs — batch prep, bar back, the
# map. Before this the same three surfaces were two separate pages with the map
# buried inside batch prep and a one-way link from barback to batch, so which
# chrome you got depended on which door you came in.
#
# This blueprint owns the shell only (page + tab controller + tab CSS). Both
# payloads keep their own module, data API and static assets untouched:
# /batch/api/batch/* and /barback/api/barback/*. /batch/ and /barback/ still
# resolve — their index routes 308 here — the same way /apply/ redirects to
# /jobs/.
bp = Blueprint(
    "jc",
    __name__,
    template_folder="frontend",
    static_folder="frontend/static",
    url_prefix="/jc",
)


@bp.route("/")
def index():
    return render_template("jc.html")
