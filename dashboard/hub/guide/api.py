"""Guide page for the public demo: a ten-minute tour, then every other page.

Server-rendered from pages.json (the copy picked on Workbench), inside the
same shell every Hub page uses. Registered by demo_mode.finish(); exists only
in the exported demo.
"""
import functools
import html
import json
from pathlib import Path

from flask import Blueprint, Response

HERE = Path(__file__).resolve().parent
bp = Blueprint("guide", __name__, static_folder="frontend", static_url_path="/static",
               url_prefix="/guide")
REPO_URL = "https://github.com/canadianbqcon/hub-demo"
MODULE = {
    "name": "guide", "desc": "a ten-minute tour of this demo, then every other page.",
    "meta": "→ /guide", "href": "/guide/", "tier": "home",
    "icon": '<path d="M5.4 4.2 H18.6 V19.8 H5.4 Z"/><path d="M9 7.8 H15 M9 11.4 H15 M9 15 H13.8"/>',
}


def load() -> dict:
    return json.loads((HERE / "pages.json").read_text())


def _e(s: str) -> str:
    return html.escape(s, quote=True)


def _stop(p: dict, num: int | None) -> str:
    head = f'<h3>{_e(p["name"])}' + (f' <i>{int(num * 1.5)} min</i>' if num else "") + "</h3>"
    marker = f'<span class="gd-num">{num}</span>' if num else '<span class="gd-num gd-num--dot"></span>'
    what = f'{p["what"].rstrip(". ")}. {p["try"][0].rstrip(".")}.'
    return (f'<li class="gd-step{" is-hit" if num == 1 else ""}">{marker}<div>{head}'
            f'<p class="gd-what">{_e(what)}</p><p class="gd-ai">{_e(p["ai"])}</p>'
            f'<a class="hub-link-chip" href="{_e(p["href"])}">Open {_e(p["name"])}</a></div></li>')


REFINING = ("Work in progress: many parts of the Hub are still being refined and completed, "
            "so some pages are rougher than others.")


@functools.lru_cache(maxsize=1)  # pages.json ships with the build
def body() -> str:
    d = load()
    by = {p["name"]: p for p in d["pages"]}
    tour = [by[n] for n in d["tour"]]
    rest = [p for p in d["pages"] if p["name"] not in d["tour"]]
    out = (
        '<div class="gd gd-c"><h1 class="gd-h">A ten-minute tour</h1>'
        f'<p class="gd-lede">{_e(d["lede"])}</p>'
        f'<p class="gd-wip">{_e(REFINING)}</p>'
        f'<ol class="gd-steps">{"".join(_stop(p, i + 1) for i, p in enumerate(tour))}</ol>'
        f'<h2 class="gd-h2">Every other page</h2>'
        f'<ul class="gd-steps gd-steps--rest">{"".join(_stop(p, None) for p in rest)}</ul>'
        '<h2 class="gd-h2">About this demo</h2><div class="gd-about">'
        "<p>The Hub is a personal dashboard: Python and Flask, one SQLite database per module, "
        "React pages transpiled at runtime with no build step, and Claude Code doing most of the "
        "building and the daily work through skills, hooks and headless runs.</p>"
        "<p>This copy runs on a fake persona's month. Outside calls (Claude, Google, banks, mail) "
        "are switched off and answer with a note instead; the data resets every day at 00:00 UTC.</p>"
        f'<p>Built by Brendan Quan. <a class="hub-link-chip" href="{REPO_URL}">Source code on GitHub</a></p>'
        "</div></div>"
    )
    return out


def render() -> str:
    shell = (HERE / "frontend" / "guide.html").read_text()
    return shell.replace("<!--GUIDE-->", body())


@bp.route("/")
def index():
    return Response(render(), mimetype="text/html")


@bp.route("/panel")
def panel():
    """The same tour as a bare fragment, for the side panel demo_mode puts on every page."""
    # text/plain: the page hooks (banner, pull-to-refresh script) only touch text/html
    return Response(body(), mimetype="text/plain")
