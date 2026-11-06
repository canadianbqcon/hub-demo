"""The Hub's public area: hand-written files a signed-out visitor may load.

One folder (public/), one route (/public/<path>), and the one exact list of
shared Hub files a signed-out page may load at their real /static/ URLs. Both the
Hub and the trips mirror read their sign-in exemptions from here.

Imports only stdlib, flask and (lazily) jsx_build: nothing here can reach a
database.
"""
from __future__ import annotations

from pathlib import Path

from flask import abort, make_response

PUBLIC_DIR = Path(__file__).resolve().parent / "public"

_JS = "application/javascript; charset=utf-8"
CONTENT_TYPES = {
    ".jsx": _JS,
    ".js": _JS,
    ".css": "text/css; charset=utf-8",
    ".png": "image/png",
    ".webp": "image/webp",
    ".woff2": "font/woff2",
}

SHARED_STATIC = frozenset({
    "css/base.css",
    "css/components.css",
    "css/themes/cobalt.css",
    "css/themes/liquid.css",
    "assets/brand-mark.svg",
    "assets/brand-mark-liquid.svg",
    "js/theme-switch.js",
    "css/liquid-scrollbar.css",  # theme-switch.js injects both on every page, login included
    "js/liquid-scrollbar.js",
    "js/early-fetch.js",      # injected into every head, login included; holds no data
    "vendor/react.production.min.js",
    "vendor/react-dom.production.min.js",
    "assets/favicon.png",
    "assets/apple-touch-icon.png",
    "assets/manifest-trips.webmanifest",
    "assets/icon-192.png",
    "assets/icon-512.png",
    "assets/icon-maskable-192.png",
    "assets/icon-maskable-512.png",
    "vendor/fonts/fonts.css",
    "vendor/fonts/archivo-black-normal-latin-ext.woff2",
    "vendor/fonts/archivo-black-normal-latin.woff2",
    "vendor/fonts/cormorant-garamond-italic-latin-ext.woff2",
    "vendor/fonts/cormorant-garamond-italic-latin.woff2",
    "vendor/fonts/cormorant-garamond-normal-latin-ext.woff2",
    "vendor/fonts/cormorant-garamond-normal-latin.woff2",
    "vendor/fonts/fraunces-normal-latin-ext.woff2",
    "vendor/fonts/fraunces-normal-latin.woff2",
    "vendor/fonts/space-grotesk-normal-latin-ext.woff2",
    "vendor/fonts/space-grotesk-normal-latin.woff2",
})
SHARED_STATIC_URLS = tuple(sorted("/static/" + p for p in SHARED_STATIC))
SCRIPT_URLS = ("/jsx/static/js/topbar.jsx", "/hub-modules.js")
# Matched exactly, never as prefixes: vendor/fonts/fonts.css as a prefix let fonts.css.header through.
PUBLIC_EXACT = frozenset(SHARED_STATIC_URLS + SCRIPT_URLS)


def _has_symlink(path: Path, root: Path) -> bool:
    """True if path or any parent up to (excluding) root is a symlink."""
    while path != root and root in path.parents:
        if path.is_symlink():
            return True
        path = path.parent
    return False


def public_file(rel):
    root = PUBLIC_DIR.resolve()
    if "\0" in rel or ".." in rel.split("/"):
        abort(404)
    raw = PUBLIC_DIR / rel
    src = raw.resolve()
    ctype = CONTENT_TYPES.get(src.suffix)
    if (ctype is None or not src.is_relative_to(root) or not src.is_file()
            or _has_symlink(raw, PUBLIC_DIR)):
        abort(404)
    if src.suffix == ".jsx":
        import jsx_build
        body = jsx_build.transpile(src)
    else:
        body = src.read_bytes()
    resp = make_response(body)
    resp.headers["Content-Type"] = ctype
    resp.headers["Cache-Control"] = "no-cache"
    return resp


def register(app):
    app.add_url_rule("/public/<path:rel>", "public_file", public_file)
