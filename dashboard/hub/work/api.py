from __future__ import annotations
from flask import Blueprint, render_template
import logging

# Single source of truth for the launcher list — see hub_modules.py. (Used to be
# a hand-synced local copy that drifted: it was missing finances + capabilities
# and had checklists in the wrong tier.)
from hub_modules import MODULES as _MODULES

logger = logging.getLogger(__name__)

# Work portal: job-grouped entry point to all work dashboards. Static structure
# (no data API in v1); tiles route out to the per-job board pages.
bp = Blueprint(
    "work", __name__,
    template_folder="frontend",
    static_folder="frontend/static",
    url_prefix="/work",
)

def _connectors() -> dict:
    """Live connector dots for the shared Hub status strip — the same cheap
    is_authenticated()/is_configured() token-presence checks home and purchases
    use. Without this the work page never sets window.CONNECTORS, so the global
    footer's gcal/gmail/ynab pips render permanently-disconnected and the gmail
    reconnect link never clears even after a successful re-auth."""
    try:
        import gcal  # top-level modules in dashboard/, already on sys.path
        import gmail
        from finances import book

        return {
            "gcal": gcal.is_authenticated(),
            "gmail": gmail.is_authenticated(),
            "ynab": book.is_configured(),
        }
    except Exception as e:  # chrome still renders with empty/dim connector dots
        logger.warning("connector ctx unavailable: %s", e)
        return {}


@bp.route("/")
def index():
    return render_template("work.html", modules=_MODULES, connectors=_connectors())
