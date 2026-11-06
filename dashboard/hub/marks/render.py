"""Re-render a Hub page headlessly for a mark whose browser capture failed.

Opens the page in system Chrome at the marker's viewport and scroll, then
returns the viewport shot and a crop of the mark's frame (the marked rect with
room around it). The X-Hub-Render header keeps the mark-mode injector out of
the shot. None on any failure or a /login landing, so the caller saves the
mark without pictures. The before crop and the after shot both come from
frame(), so the walk-through flips between two pictures of the same size.
"""

import sys
import io
import json
import os
from urllib.parse import urlparse, urlsplit

HUB_URL = os.environ.get("HUB_URL", "http://127.0.0.1:5002")
DISABLE_ANIM_CSS = "* { animation: none !important; transition: none !important; }"
# the marker's look, replayed through the same localStorage keys theme-switch.js reads;
# a fresh headless profile has none and falls back to light, which is not what he saw
LOOKS = {"theme": ("hub.theme", ("cobalt", "liquid")),
         "surface": ("hub.surface", ("light", "dark")),
         "glass": ("hub.glass", ("frost", "solid"))}
INK = (0xE5, 0x17, 0x3F)  # --mk-ink, the mark layer's red
# ponytail: fixed padding rule, tune here if the context reads too tight or too loose
PAD_MIN, PAD_SCALE = 120, 0.5
# data-glass reads "refract" when frost runs the refraction pass; it is stored as frost
GLASS_STORED = {"refract": "frost"}


def _look_script(look, store=None):
    """localStorage seeding for the known look keys (unknown values dropped), plus
    the page's own remembered view (open tab, picked day) the mark recorded."""
    look = dict(look or {})
    if look.get("glass") in GLASS_STORED:
        look["glass"] = GLASS_STORED[look["glass"]]
    pairs = {k: v for k, v in (store or {}).items()
             if isinstance(k, str) and isinstance(v, str) and not k.startswith("hub.")}
    pairs.update({LOOKS[k][0]: v for k, v in look.items() if k in LOOKS and v in LOOKS[k][1]})
    return "".join(f"try{{localStorage.setItem({json.dumps(k)},{json.dumps(v)})}}catch(e){{}}" for k, v in pairs.items())


def hub_path(u) -> bool:
    """A same-origin Hub path only. Browsers strip tab and newline from URLs, so
    "/\t/evil.com" would load as "//evil.com": any control or space character
    is refused, and so is a leading "//" (urlsplit reads "///x" as hostless,
    Chrome reads it as host x); then the parsed URL must have no scheme or host."""
    if not isinstance(u, str) or not u.startswith("/") or u.startswith("//") or "\\" in u or any(c <= " " for c in u):
        return False
    p = urlsplit(u)
    return not p.scheme and not p.netloc


# PDFs the Hub draws with pdf.js sit on views the page keeps only in memory; a mark over one
# (its elements carry the canvas's data-pdf tag) replays with that view opened first
PDF_VIEWS = {"/jobs/": '[data-surface="application"]'}  # resume and cover letter viewers


def view_click(meta):
    """The selector to click before a replay of this mark, or None."""
    path = urlsplit(meta.get("url") or "").path
    if not any("data-pdf=" in (e.get("html") or "") for e in meta.get("elements") or [] if isinstance(e, dict)):
        return None
    return next((sel for pre, sel in PDF_VIEWS.items() if path.startswith(pre)), None)


def frame(rect, w, h):
    """The marked rect padded on every side, in viewport px. Near an edge the
    frame slides inward instead of shrinking, so it keeps its size."""
    pad = max(PAD_MIN, PAD_SCALE * max(rect["w"], rect["h"]))
    fw, fh = min(w, rect["w"] + 2 * pad), min(h, rect["h"] + 2 * pad)
    x = max(0, min(w - fw, rect["x"] - pad))
    y = max(0, min(h - fh, rect["y"] - pad))
    return {"x": x, "y": y, "w": fw, "h": fh}


def crop_frame(png, rect, viewport, highlight=False):
    """PNG bytes of the mark's frame cut from a viewport shot. highlight paints
    the marked rect like a highlighter pen (a shot from the browser already
    has the mark drawn, so only a server re-render asks for it)."""
    from PIL import Image, ImageDraw
    img = Image.open(io.BytesIO(png)).convert("RGBA")
    w, h = float(viewport["w"]), float(viewport["h"])
    sx, sy = img.width / w, img.height / h
    if highlight:
        box = (round(rect["x"] * sx), round(rect["y"] * sy),
               round((rect["x"] + rect["w"]) * sx), round((rect["y"] + rect["h"]) * sy))
        over = Image.new("RGBA", img.size)
        ImageDraw.Draw(over).rectangle(box, fill=INK + (46,), outline=INK + (255,), width=max(2, round(2 * sx)))
        img = Image.alpha_composite(img, over)
    f = frame(rect, w, h)
    x0 = max(0, min(img.width - 1, round(f["x"] * sx)))
    y0 = max(0, min(img.height - 1, round(f["y"] * sy)))
    x1 = max(x0 + 1, min(img.width, round((f["x"] + f["w"]) * sx)))
    y1 = max(y0 + 1, min(img.height, round((f["y"] + f["h"]) * sy)))
    buf = io.BytesIO()
    img.crop((x0, y0, x1, y1)).convert("RGB").save(buf, "PNG")
    return buf.getvalue()


def shoot(url, viewport, scroll, rect, cookie=None, look=None, store=None, highlight=True, click=None):
    """(viewport shot, frame crop). highlight=False for the after shot, which
    shows the fix in the same frame with nothing painted over it. click is a CSS
    selector clicked after load, for a view the page keeps only in memory (the jobs
    page's Application tab, where the resume sits)."""
    # url comes from the browser: a Hub path only, or "@evil.com" would turn
    # HUB_URL into userinfo and send the shot (and any cookie) off the machine
    if not hub_path(url):
        return None
    try:
        from playwright.sync_api import sync_playwright

        # ponytail: 4000px cap per side, a real monitor never asks for more
        w, h = min(int(viewport["w"]), 4000), min(int(viewport["h"]), 4000)
        if w < 1 or h < 1:
            return None
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome")
            try:
                surface = (look or {}).get("surface")
                ctx = browser.new_context(viewport={"width": w, "height": h},
                                          color_scheme=surface if surface in ("light", "dark") else None)
                # the render header goes to Hub requests only: sent cross-origin it forces a CORS
                # preflight that Open-Meteo refuses, and Home rendered without its hourly weather
                ctx.route(HUB_URL + "/**", lambda r: r.continue_(headers={**r.request.headers, "x-hub-render": "1"}))
                if _look_script(look, store):
                    ctx.add_init_script(_look_script(look, store))
                if cookie:
                    # scoped to the Hub, so a third-party load on the page never sees the session
                    # one at a time: Chrome refuses some (another port's __Host- cookie), and one refusal must not cost the shot
                    for k, _, v in (c.partition("=") for c in cookie.split(";")):
                        if not k.strip():
                            continue
                        try:
                            ctx.add_cookies([{"name": k.strip(), "value": v, "url": HUB_URL}])
                        except Exception as e:
                            print(f"cookie {k.strip()!r} refused: {e}", file=sys.stderr)
                pg = ctx.new_page()
                pg.goto(HUB_URL + url, wait_until="networkidle", timeout=30000)
                if urlparse(pg.url).path.startswith("/login"):
                    return None
                if click:
                    pg.click(click, timeout=10000)
                    pg.wait_for_load_state("networkidle", timeout=30000)
                pg.evaluate("document.fonts.ready.then(() => true)")
                pg.add_style_tag(content=DISABLE_ANIM_CSS)
                pg.evaluate("([x, y]) => window.scrollTo(x, y)",
                            [scroll.get("x", 0), scroll.get("y", 0)])
                # Hub pages scroll inner panes; a selector that no longer matches is skipped
                panes = [q for q in (scroll.get("panes") or [])[:20]
                         if isinstance(q, dict) and isinstance(q.get("sel"), str)]
                pg.evaluate("ps => ps.forEach(q => { try { const e = document.querySelector(q.sel);"
                            " if (e) e.scrollTo(+q.x || 0, +q.y || 0); } catch (x) {} })", panes)
                pg.wait_for_timeout(400)
                full = pg.screenshot(timeout=30000)
            finally:
                browser.close()
        return full, crop_frame(full, rect, {"w": w, "h": h}, highlight)
    except Exception as e:
        print(f"mark render failed: {e}", file=sys.stderr)
        return None
