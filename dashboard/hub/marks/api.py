"""Mark mode Hub blueprint: /marks/frame and /marks/api/*.

The frame page wraps a Hub page in an iframe so the marker overlay can sit
over it. Save takes multipart meta (JSON) plus an optional full PNG (the crop is cut from it); when
the browser could not capture, the page is re-rendered headlessly. Design:
docs/specs/2026-10-12-hub-mark-mode-design.md.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
from urllib.parse import urlsplit

from flask import Blueprint, jsonify, render_template, request, send_from_directory

# package imports: a bare "import store" would collide with workbench's store module
from marks import render, store  # noqa: E402

bp = Blueprint("marks", __name__, template_folder="frontend", url_prefix="/marks")

MAX_UPLOAD = 25 * 1024 * 1024  # ponytail: two viewport PNGs at 4K fit with room to spare


def _ours(host) -> bool:
    """A DNS-rebinding page controls Host and Origin together, so each is checked
    on its own: a non-public IP literal (loopback, LAN, WSL, tailnet; rebinding
    needs a name, and a public one would let any VPS page post over plain http,
    where browsers send no Sec-Fetch-Site), localhost, this machine's name, or a
    tailnet *.ts.net name."""
    h = urlsplit("//" + (host or "")).hostname or ""
    try:
        ip = ipaddress.ip_address(h)
        # 6to4 and Teredo wrap a public IPv4 but read as non-global
        return not ip.is_global and not getattr(ip, "sixtofour", None) and not getattr(ip, "teredo", None)
    except ValueError:
        return h in ("localhost", socket.gethostname().lower()) or h.endswith(".ts.net")


@bp.get("/frame")
def frame():
    u = request.args.get("u", "")
    if not render.hub_path(u):
        return jsonify({"error": "u must be a Hub path"}), 400
    # the session name is fixed when the frame opens, so a retried first save
    # whose response was lost lands in the same session
    return render_template("frame.html", u=u, session=store.session_name())


@bp.get("/api/session")
def session():
    """The session name for mark mode opened over a page (marks.js), fixed on entry like the frame's."""
    return jsonify({"session": store.session_name()})


def _same_site() -> bool:
    site = request.headers.get("Sec-Fetch-Site")
    origin = request.headers.get("Origin")
    return not ((site and site not in ("same-origin", "none")) or not _ours(request.host)
                or (origin is not None and not _ours(urlsplit(origin).netloc)))


@bp.post("/api/mark")
def save_mark():
    # Another site's page can post here (multipart needs no CORS preflight), and
    # /marks treats the comment as Sam's request: same-origin callers only.
    if not _same_site():
        return jsonify({"error": "cross-site save refused"}), 403
    # a chunked body has no length to check up front; the browser always sends one
    if request.content_length is None:
        return jsonify({"error": "Content-Length required"}), 411
    if request.content_length > MAX_UPLOAD:
        return jsonify({"error": "upload too large"}), 413
    try:
        meta = json.loads(request.form.get("meta", ""))
        if not isinstance(meta, dict):
            raise ValueError
    except ValueError:
        return jsonify({"error": "meta must be a JSON object"}), 400
    full = request.files["full"].read() if "full" in request.files else None
    if full is not None and not full.startswith(b"\x89PNG"):
        return jsonify({"error": "full must be a PNG"}), 400
    crop = None
    try:
        session = meta.pop("session", None) or store.new_session()
        capture = meta.get("capture")
        # the crop is always cut here, from the full shot (which already has the mark drawn on it),
        # so the before and the after shot share render.frame
        if full is not None and capture != "rerender":
            try:
                crop = render.crop_frame(full, meta["rect"], meta["viewport"])
            except Exception:
                full = None
        if capture == "rerender" or (crop is None and capture != "none"):
            cookie = request.headers.get("Cookie") if os.environ.get("DASHBOARD_EXPOSED") == "1" else None
            try:
                shot = render.shoot(meta["url"], meta["viewport"], meta["scroll"], meta["rect"], cookie, meta.get("look"), meta.get("store"),
                                    click=render.view_click(meta))
            except (KeyError, TypeError):
                shot = None
            if shot:
                full, crop = shot
                meta["capture"] = "rerender"
            else:
                full = crop = None
                meta["capture"] = "none"
        n = store.add_mark(session, meta, crop, full)
    except (json.JSONDecodeError, OSError) as e:
        return jsonify({"error": f"mark store unreadable: {e}"}), 500
    except ValueError:
        return jsonify({"error": "bad session name"}), 400
    return jsonify({"session": session, "n": n})


# ── walk-through (Workbench ?walk=<session>): his Close / Send back per fixed mark ──


@bp.get("/api/walk")
def walk():
    """Every mark in the session with its status (fixed ones wait on his answer),
    with picture URLs for the before crop and the after shot."""
    session = request.args.get("session", "")
    try:
        data = store.load(session)
    except ValueError:
        return jsonify({"error": "bad session name"}), 400
    except FileNotFoundError:
        data = {"marks": []}  # every mark closed: the folder goes with the last one
    out = []
    # open marks come too, so the Workbench Marks row always opens to something; only fixed ones get Close / Send back
    for m in data["marks"]:
        # ?v=<mtime>: a re-fix rewrites NN-after.png under the same name, and an open walk page
        # kept drawing the old picture from the browser's image cache (2026-10-26, "you didnt do it?")
        pics = {k: f"/marks/api/png/{session}/{p.name}?v={int(p.stat().st_mtime)}"
                for k in ("crop", "after") if (p := store.marks_root() / session / f"{m['n']:02d}-{k}.png").exists()}
        # NN-play.js: a script that plays the fix's motion in the live page (the walk card's Motion play view)
        if (store.marks_root() / session / f"{m['n']:02d}-play.js").exists():
            pics["play"] = f"/marks/api/png/{session}/{m['n']:02d}-play.js"
        out.append({k: m.get(k) for k in ("n", "url", "title", "comment", "kind", "status", "fix_note", "reply", "options", "answered", "quote")} | pics)
    # the session header feeds the walk page's head card (when, which machine, which code)
    return jsonify({"session": session, "marks": out} | {k: data.get(k) for k in ("started", "machine", "code_commit")})


@bp.get("/api/walk/sessions")
def walk_sessions():
    """Every session with marks, for Workbench's Marks group: `waiting` are fixes for his
    Close / Send back, `open` are marks still on Claude (sent-back ones included)."""
    out = []
    for s in store.list_sessions():
        n = sum(m.get("status") == "fixed" for m in s["marks"])
        out.append({"session": s["session"], "waiting": n, "open": len(s["marks"]) - n})
    return jsonify([o for o in out if o["waiting"] or o["open"]])


@bp.get("/api/png/<session>/<name>")
def png(session, name):
    if not re.fullmatch(r"\d{2}-((crop|after|full)\.png|play\.js)", name):
        return jsonify({"error": "bad file"}), 400
    try:
        folder = store._folder(session)
    except ValueError:
        return jsonify({"error": "bad session name"}), 400
    return send_from_directory(folder, name, max_age=0)


@bp.post("/api/walk/decide")
def walk_decide():
    """close: delete the mark (same as `cli.py close`). send_back: back to
    fixing with his words as `reply`, which `cli.py wait` hands the session.
    options: back to fixing flagged for a Workbench option set (store.decide).
    All write the ledger row first (store.decide)."""
    if not _same_site():
        return jsonify({"error": "cross-site answer refused"}), 403
    d = request.get_json(silent=True) or {}
    session, n, verdict, reply = d.get("session"), d.get("n"), d.get("verdict"), (d.get("reply") or "").strip()
    if verdict not in ("close", "send_back", "options") or not isinstance(n, int):
        return jsonify({"error": "verdict must be close, send_back or options, n an integer"}), 400
    if verdict == "send_back" and not reply:
        return jsonify({"error": "say what is still off"}), 400
    try:
        if verdict == "close":
            stuck = store.decide(session, n, "close")
            if stuck:
                return jsonify({"error": f"could not delete {stuck[0]}; close it again"}), 409
        else:
            store.decide(session, n, verdict, reply=reply)
    except ValueError:
        return jsonify({"error": "bad session name"}), 400
    except store.NotWaiting:
        return jsonify({"error": "already answered"}), 409
    except store.LedgerError as e:
        return jsonify({"error": f"could not record the answer, nothing changed: {e}"}), 503
    except (KeyError, FileNotFoundError):
        return jsonify({"error": f"mark {n} is already closed"}), 404
    except OSError as e:
        return jsonify({"error": f"recorded, but could not update the mark: {e}; answer again"}), 409
    return jsonify({"ok": True})
