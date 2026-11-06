"""Forge Hub blueprint — routes under /forge.

The item-set editor, plus the coachless WPA statistics it is built around, plus
a set library that keeps every patch's build instead of overwriting it.

This was a claude.ai Artifact until the requirements outgrew one: a published
artifact runs under a CSP that blocks every external host, and four of the
things it needs (the patch scan, the coachless POST, the lolalytics scrape, a
set library worth more than localStorage) all cross the network. So it is
self-hosted and listed on /artifacts as a project.

Two surfaces. `/forge/` is the champion landing page — one card per champion in
the pool, which is what you actually open the tool for. `/forge/c/<champ>/<role>`
is the editor with that champion and role already loaded, so the statistics are
on screen the moment the page paints instead of after two dropdowns.

Reads, per request, so an edit or a re-bake shows without a restart:
  data/forge-stats.json      coachless items + runes, written by bake_stats.py
  data/forge-lolalytics.json live-patch win/pick rates, written by bake_lolalytics.py
  data/forge-sets.json       the set library, written through here
  data/forge-patch-diff.json what the newest patch changed, written by build_diff.py
  data/forge-patch-notes.json Riot's own notes for the live patch, written by
                             bake_patchnotes.py

Set versioning: a set is keyed by (name, patch). Saving under a patch that
already has that name overwrites it; saving under a NEW patch forks a new
version and leaves the old one intact. That is the whole "old builds stay,
new ones fork forward" requirement — no diffing, no migration.
"""

from __future__ import annotations

import bisect
import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from urllib.parse import quote

from flask import Blueprint, Response, current_app, jsonify, request, send_from_directory

from . import draft_feed, notes_read, opgg_me
from .bake_stats import POOL, ROLES, item_rows

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from vault_path import vault_root  # noqa: E402

bp = Blueprint(
    "forge",
    __name__,
    template_folder="frontend",
    static_folder="frontend/static",
    url_prefix="/forge",
)

# Conditional GETs (ETag -> 304) for these JSON reads are handled app-wide by
# _conditional_json in app.py; this module's own copy was hoisted there 2026-08-19.

_FRONTEND = os.path.join(os.path.dirname(__file__), "frontend")
_CATALOG = Path(_FRONTEND) / "static" / "catalog.json"
_STATS = vault_root() / "data" / "forge-stats.json"
_SETS = vault_root() / "data" / "forge-sets.json"
_DIFF = vault_root() / "data" / "forge-patch-diff.json"
_NOTES = vault_root() / "data" / "forge-patch-notes.json"
_LOLA = vault_root() / "data" / "forge-lolalytics.json"
_BANS = vault_root() / "data" / "forge-bans.json"
_PASSIVES = vault_root() / "data" / "forge-item-passives.json"
_ME = vault_root() / "data" / "forge-me.json"

# A set name becomes part of an id; keep it to something that survives a URL.
_SAFE = re.compile(r"[^a-z0-9]+")

# A card ranks items by WPA, but only among items enough games actually bought.
# The highest-WPA item on any champion is reliably a sub-1% outlier, so ranking
# on the headline number alone manufactures confident nonsense. Same floor the
# editor draws its grey edges at.
MIN_GAMES = 1000

# build_diff.py records Data Dragon's own stat keys, which is right for the file
# and unreadable on a page. Labelled here rather than in the bake so relabelling
# never costs a network round trip.
_FIELD = {
    "FlatPhysicalDamageMod": "attack damage",
    "FlatMagicDamageMod": "ability power",
    "FlatHPPoolMod": "health",
    "FlatMPPoolMod": "mana",
    "FlatArmorMod": "armor",
    "FlatSpellBlockMod": "magic resist",
    "FlatMovementSpeedMod": "move speed",
    "PercentMovementSpeedMod": "move speed %",
    "PercentAttackSpeedMod": "attack speed",
    "PercentLifeStealMod": "life steal",
    "FlatCritChanceMod": "crit chance",
    "FlatHPRegenMod": "health regen",
    "cost": "cost",
    "effect text": "effect text",
}


def _with_icon(entry: dict, items: dict) -> dict:
    """One diffed item, ready to render: its icon and readable field labels."""
    return dict(
        entry,
        icon=items.get(str(entry.get("id")), {}).get("u"),
        changes=[dict(c, label=_FIELD.get(c.get("field", ""), c.get("field", "")))
                 for c in (entry.get("changes") or [])],
    )


def _read(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


# The catalog is 553 KB of base64 icons and never changes between patches, so it
# is parsed once and kept. Keyed by mtime so a rebuild still lands without a
# restart, the same promise the per-request reads above make.
_catalog_cache: tuple[float, dict] | None = None


def _catalog() -> dict:
    global _catalog_cache
    try:
        stamp = _CATALOG.stat().st_mtime
    except OSError:
        return {"items": [], "champs": []}
    if _catalog_cache is None or _catalog_cache[0] != stamp:
        _catalog_cache = (stamp, _read(_CATALOG, {"items": [], "champs": []}))
    return _catalog_cache[1]


def _sets() -> dict:
    data = _read(_SETS, None)
    if not isinstance(data, dict) or not isinstance(data.get("sets"), list):
        return {"sets": []}
    return data


class LibraryUnreadable(Exception):
    """The set library file exists but is not JSON with a `sets` list."""


# One lock around load, place and write, so a builder autosave and an autobuild
# run cannot interleave. ponytail: process-wide, fine for one Hub process.
_SAVE_LOCK = threading.Lock()


def _load_library() -> dict:
    """Strict read for the write routes: absent file is an empty library, an
    unparseable one raises, so a save never replaces the library with one set."""
    try:
        data = json.loads(_SETS.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"sets": []}
    except (OSError, ValueError) as exc:
        raise LibraryUnreadable(str(exc)) from exc
    if not isinstance(data, dict) or not isinstance(data.get("sets"), list):
        raise LibraryUnreadable("no sets list")
    return data


def _write_library(data: dict) -> None:
    """Temp file in the same folder, then os.replace: a failed write cannot
    truncate the library."""
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    tmp = _SETS.with_name(_SETS.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, _SETS)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _set_id(name: str, patch: str) -> str:
    slug = _SAFE.sub("-", name.strip().lower()).strip("-") or "set"
    return f"{slug}@{patch}"


@bp.route("/")
def index():
    """The champion landing page — what you open the tool for."""
    return send_from_directory(_FRONTEND, "landing.html")


@bp.route("/patch")
def patch():
    """The patch note, on its own surface.

    A peer of the build shelf, not a header on top of it. It used to sit above
    the champion cards on the landing page, where a 22-entry patch pushed the
    thing you actually opened the tool for below the fold every second Tuesday.
    """
    return send_from_directory(_FRONTEND, "patch.html")


@bp.route("/stats")
def stats():
    """His own record, on its own surface.

    The third top-level tab, and the other half of what the rest of the tool
    reads: Champions is what he has built, Patch is what Riot changed under it,
    Stats is how the games actually went. A pool figure here is his, not the
    global average the builder shows — the two are deliberately never mixed on
    one page, for the same reason coachless and lolalytics are kept apart.
    """
    return send_from_directory(_FRONTEND, "stats.html")


@bp.route("/c/<champ>")
@bp.route("/c/<champ>/<role>")
def champion(champ: str = "", role: str = ""):
    """A champion's build list — every set saved for them, grouped by patch.

    This is what opening a champion lands on, not the builder. The sets you have
    already made are the thing you want first; a new one is one click away.
    """
    return send_from_directory(_FRONTEND, "champion.html")


@bp.route("/c/<champ>/<role>/build")
@bp.route("/edit")
def editor(champ: str = "", role: str = ""):
    """The builder. It reads the champion and role off its own URL, so both the
    path form and the bare /forge/edit (a set with no champion) serve one file."""
    return send_from_directory(_FRONTEND, "forge.html")


def _card(name: str, champ: dict, portraits: dict, sets: list) -> dict:
    """One landing card's worth of reading for a champion.

    The card is the champion's own build shelf, not a statistics readout and not
    a patch feed: the front door answers "what have I built for this champion"
    first. The figures live one click in, on the page where you are choosing an
    item, and the patch notes live on the strip above the cards, which reads the
    patch whole rather than once per champion. `roles` is
    every role the champion is played in UNION every role a saved set sits in,
    so a chip exists both for a role you have built and for one you have not.
    """
    roles = champ.get("roles") or {}
    ranked = sorted(roles.items(), key=lambda kv: kv[1].get("n", 0), reverse=True)
    lead_name = ranked[0][0] if ranked else ""

    mine = [s for s in sets if (s.get("champion") or "").lower() == name.lower()]
    chips = [{"role": r, "n": v.get("n", 0)} for r, v in ranked]
    known = {c["role"] for c in chips}
    for s in mine:
        r = s.get("role")
        if r and r not in known:
            known.add(r)
            chips.append({"role": r, "n": 0})

    return {
        "name": name,
        "id": champ.get("id"),
        "portrait": portraits.get(name.lower()),
        "roles": chips,
        "lead": lead_name,
        "sets": [_set_stub(s) for s in mine],
    }


def _set_stub(s: dict) -> dict:
    """A saved set flattened to what a landing card renders: the name, the patch
    it is filed under, its keystone (the landing page already has runes.json, so
    the id is enough to draw it) and how much of it is built. The blocks
    themselves stay behind /api/sets - four cards' worth of full item sets would
    put the catalog back on the front door it was sliced off."""
    blocks = [b for b in (s.get("blocks") or []) if b.get("items")]
    return {
        "id": s.get("id"),
        "name": s.get("name"),
        "patch": s.get("patch"),
        "role": s.get("role"),
        "keystone": (s.get("runes") or {}).get("keystone"),
        "blocks": len(blocks),
        "items": sum(i.get("count", 1) for b in blocks for i in b["items"]),
        "forkedFrom": s.get("forkedFrom"),
        "auto": s.get("auto") is True,
        "autoKey": s.get("autoKey"),
        "updated": s.get("updated"),
    }


@bp.route("/api/landing", methods=["GET"])
def api_landing():
    """Everything the landing page needs, already sliced.

    Sliced server-side on purpose: the cards want a portrait each and an icon per
    patch note, and shipping the whole 553 KB catalog to get them would make the
    front door the heaviest page in the tool. Saved sets arrive as stubs for the
    same reason - see _set_stub.
    """
    stats = _read(_STATS, {"champions": {}, "patch": None})
    diff = _read(_DIFF, {})
    cat = _catalog()
    items = {str(i["id"]): i for i in cat.get("items", [])}
    portraits = {c["n"].lower(): c.get("u") for c in cat.get("champs", [])}

    sets = _sets().get("sets", [])
    styles = _styles()
    cards = [dict(_card(name, champ, portraits, sets), styles=styles.get(name) or [])
             for name, champ in sorted(stats.get("champions", {}).items())]
    # the strip above the cards renders the same entries, so it wants the same
    # readable labels the cards get rather than Data Dragon's raw stat keys
    if diff.get("items"):
        diff = dict(diff, items=[_with_icon(c, items) for c in diff["items"]])
    # Busiest champion first; the pool is small enough that this is the whole sort.
    cards.sort(key=lambda c: sum(r["n"] for r in c["roles"]), reverse=True)
    # Every other champion, each linking to its champion page per role (Sam, 2026-11-04).
    shares, pool = _role_shares(), {c["name"].lower() for c in cards}
    roster = [{"name": c["n"], "portrait": c.get("u"), "styles": styles.get(c["n"]) or [],
               "roles": [r for r, v in sorted((shares.get(c["n"]) or {}).items(), key=lambda kv: -kv[1])
                         if v >= 0.05] or ["top"]}
              for c in sorted(cat.get("champs", []), key=lambda c: c["n"]) if c["n"].lower() not in pool]

    return Response(json.dumps({
        "patch": stats.get("patch"),
        "catalogPatch": cat.get("ver"),
        "tiers": stats.get("tiers"),
        "minGames": MIN_GAMES,
        "diff": diff,
        "champions": cards,
        "roster": roster,
    }), mimetype="application/json")


_styles_cache: dict = {}


def _styles() -> dict:
    """{champion: [build style rows]} off the lolalytics item tables, re-read only when
    the bake or the catalog changes: the bake is 2.8 MB and every champion wants a row."""
    from .build_styles import all_styles
    arch = vault_root() / "data" / "forge-archetypes.json"
    key = tuple(f.stat().st_mtime if f.exists() else 0 for f in (_LOLA, _CATALOG, arch))
    if _styles_cache.get("key") != key:
        _styles_cache.update(key=key, styles=all_styles(_read(_LOLA, {}), _catalog(), _read(arch, {})))
    return _styles_cache["styles"]


_shares_cache: dict = {}


def _role_shares() -> dict:
    """{champion: {role: share}} off the matchups store, re-read only when it changes:
    the store is 10 MB and the landing page wants only this block."""
    f = vault_root() / "data" / "forge-matchups.json"
    key = f.stat().st_mtime if f.exists() else 0
    if _shares_cache.get("key") != key:
        _shares_cache.update(key=key, shares=_read(f, {}).get("roleShares") or {})
    return _shares_cache["shares"]


@bp.route("/api/patchnotes", methods=["GET"])
def api_patchnotes():
    """Riot's own notes for the live patch, baked by bake_patchnotes.py.

    Separate from /api/diff because it is a different kind of claim. The diff is
    computed - two Data Dragon blobs subtracted, so it only ever sees stats and
    gold. This is quoted: what Riot wrote, including the passive and recipe
    changes no data file carries. When the two disagree about whether a patch
    was good for an item, this is the one that knows.

    Served enriched, not raw: notes_read adds a gist of each paragraph, a
    head/tail-factored split of each from/to pair, and a buff/nerf/rework read
    per change and per entry. That runs HERE rather than in the bake so the file
    on disk stays byte-for-byte what Riot published - a presentation change is
    then a server restart, never a re-fetch of a page that may have since moved.
    """
    return Response(json.dumps(notes_read.enrich(_read(_NOTES, {"sections": []}))),
                    mimetype="application/json")


@bp.route("/api/passives", methods=["GET"])
def api_passives():
    """Item passives with their numbers in, baked by bake_passives.py.

    Not folded into catalog.json even though that is where the `ps` blocks it
    replaces live: the catalog is generated OUTSIDE this repo (build_assets.py in
    Downloads) and a re-run of that would silently drop the numbers again. A file
    of its own, merged client-side, survives that.
    """
    return Response(json.dumps(_read(_PASSIVES, {"items": {}})),
                    mimetype="application/json")


@bp.route("/api/diff", methods=["GET"])
def api_diff():
    """What the newest Data Dragon patch changed since the statistics patch."""
    diff = _read(_DIFF, {})
    cat = _catalog()
    items = {str(i["id"]): i for i in cat.get("items", [])}
    if diff.get("items"):
        diff = dict(diff, items=[_with_icon(c, items) for c in diff["items"]])
    return Response(json.dumps(diff), mimetype="application/json")


@bp.route("/api/stats", methods=["GET"])
def api_stats():
    """The whole bake. Still one file, still not worth slicing, but no longer the
    60 KB this said when items were a single flat list — items are broken out per
    keystone as well as flat."""
    return Response(json.dumps(_read(_STATS, {"champions": {}, "patch": None})),
                    mimetype="application/json")


# role name -> the int enum coachless takes. The bake writes role NAMES into the
# stats file and the API only speaks the enum, so the page sends what it has.
_ROLE_ID = {v: k for k, v in ROLES.items()}

# One coachless call per first item the page actually opens, kept for the life of
# the process. The whole point of going live rather than baking this is that the
# first item is whatever sits in HIS Core block: baking every possible opener is
# hundreds of calls per champion/role for cells nobody looks at, while a cache
# keyed on what he built costs one call the first time and nothing after.
# ponytail: plain dict, no eviction — the pool is five champions and the keys are
# bounded by what one session clicks. Swap for an LRU if it ever serves more.
_conditioned_cache: dict[tuple, list] = {}


def _int_arg(name: str) -> int | None:
    raw = request.args.get(name, "")
    return int(raw) if raw.isdigit() else None


@bp.route("/api/conditioned", methods=["GET"])
def api_conditioned():
    """Item WPA measured out of the build's first legendaries, live from coachless.

    The axis the bake cannot hold. `itemsByKeystone` works baked because a
    champion/role has a fixed handful of keystones; the first legendary is a
    property of the BUILD being edited, so it is only known once there is
    something in the Core block.

    `second` is the same axis one slot deeper — the Core block's slot 1 — and
    `keystone` crosses in alongside them. Nothing is refused here for being "too
    narrow": the sample floor decides that per cell, in the caller.

    The keystone being honoured is a correction. It used to be ignored on this
    endpoint, on the rule that one keystone supports several different first items
    and so slices the sample into cells reporting nothing. The number behind that
    rule was Press the Attack crossed with a Collector rush on Viego jungle 16.15 —
    6 rows, none over the floor — and it was read as a property of the CROSS when it
    is a property of Press the Attack, which alone tops out at 2,909 games on that
    champion. A popular keystone crosses in and keeps almost everything: Hail of
    Blades with the same rush is 27 rows with 14 over the floor and a 30,470-game
    top line, against 29/16/39,947 for the rush alone. Conqueror is 23/12/9,044.

    Leaving it out was also doing active harm. Conditioned rows are keystone-blind
    and they WIN over the baked `itemsByKeystone`, so setting a first item silently
    re-pooled the split the keystone breakout exists to make — Umbral Glaive reads
    +4.54 under Hail of Blades and does not place at all under Conqueror.

    The start is still out: the jungle pet is an ordinary item carrying its own
    figures (itemType 6, in `item_rows`) rather than a filter, so there is nothing
    to cross.

    **Two is the ceiling, and coachless sets it.** `thirdLegendaryId` is accepted
    with a 200 and then silently ignored — the rows come back identical to the
    first-only call. So a deeper condition is not thin, it is a LIE: the shop would
    be measured under two items while the page claimed three, with nothing in the
    response to say so. The caller caps at two and the legend names the cap.

    Degrading is the caller's job, not this endpoint's: it serves exactly the
    condition asked and reports the rows, and `refreshConditioned` in forge.html
    walks keystone+pair, keystone+opener, pair, opener, then down the baked chain.

    An empty answer is a real absence and is returned as one: nobody rushes
    Immortal Shieldbow on Viego, so conditioning on it correctly has nothing to
    say. The page says so rather than pretending the aggregate was the answer.
    """
    stats = _read(_STATS, {})
    champ = request.args.get("champ", "")
    role = request.args.get("role", "")
    entry = (stats.get("champions") or {}).get(champ)
    patch = stats.get("patchFilter")
    role_id = _ROLE_ID.get(role)
    first = _int_arg("first")
    # Slot 1 without slot 0 is not a condition anyone builds; it is a half-read
    # query string. The pair is anchored on the first or it is not asked.
    second = _int_arg("second") if first else None
    # The keystone rides along with a first item and is never asked for on its own:
    # keystone-only is `roles.<role>.itemsByKeystone`, which is baked and already on
    # the page. Serving it live too would be a second answer to a settled question.
    keystone = _int_arg("keystone") if first else None
    # No first item is the unconditioned aggregate, which the page already holds.
    if not entry or role_id is None or not patch or not first:
        return jsonify([])

    key = (stats.get("patch"), entry.get("id"), role_id, first, second, keystone)
    if key not in _conditioned_cache:
        _conditioned_cache[key] = item_rows(entry["id"], role_id, patch, first=first,
                                            second=second, keystone=keystone)
    return jsonify(_conditioned_cache[key])


@bp.route("/api/lolalytics", methods=["GET"])
def api_lolalytics():
    """The lolalytics bake: the live patch's win rate and pick rate per rune and
    per item, read beside the coachless WPA rather than instead of it.

    Separate from /api/stats because it is a separate measurement of a different
    thing on a different patch, and merging the two files would make it possible
    to lose track of which number came from where."""
    return Response(json.dumps(_read(_LOLA, {"champions": {}, "patch": None})),
                    mimetype="application/json")


@bp.route("/api/sets", methods=["GET"])
def api_sets():
    data = _sets()
    # Newest first, so the current patch's work is what you land on.
    data["sets"].sort(key=lambda s: s.get("updated", ""), reverse=True)
    return Response(json.dumps(data), mimetype="application/json")


def _set_body_error(body: dict):
    """The (json, status) pair for a malformed already-dict payload, or None
    when `body` has everything a save needs."""
    if not (body.get("name") or "").strip():
        return {"error": "a set needs a name"}, 400
    if not (body.get("patch") or "").strip():
        return {"error": "a set needs the patch it was built on"}, 400
    if not isinstance(body.get("blocks"), list):
        return {"error": "blocks must be a list"}, 400
    # The builder saves after the rune page and before any item is placed, so a
    # runes-only set is a real state, not a malformed one. Empty on both halves
    # is still nothing worth keeping.
    if not body["blocks"] and not body.get("runes"):
        return {"error": "a set needs runes or at least one block"}, 400
    return None


def _resolve_rename(data, patch, body, existing):
    """A rename-in-place target for the row `body["id"]` names, merged with
    `existing` when the new name collided with a row already on this patch.

    A rename is an edit, not a new build. The id is derived from the name, so
    without this a renamed set lands on a fresh id and the old row survives as
    a copy nobody asked for — and the builder autosaves on every keystroke, so
    one rename could leave a trail of them. `id` is the row the editor has open:
    same patch, so this is that row being renamed, and it is rewritten in place.
    A different patch is still a fork, which is the whole point of the versioning.
    """
    owned = next((s for s in data["sets"] if s.get("id") == (body.get("id") or "")), None)
    if owned is None or owned is existing or owned.get("patch") != patch:
        return existing
    if existing is None:
        return owned                # plain rename: keep the row, its slot and its created
    data["sets"].remove(owned)      # renamed onto a name already taken — the client
    return existing                 # confirmed the replace before sending this


def _place_set(data, entry, existing, name, now):
    """Insert or replace `entry` in `data["sets"]`; returns the id it forked
    from, or None on a replace or a fresh set with no earlier patch to fork."""
    if existing:
        entry["created"] = existing.get("created", now)
        if existing.get("forkedFrom"):
            entry["forkedFrom"] = existing["forkedFrom"]
        data["sets"][data["sets"].index(existing)] = entry
        return None
    entry["created"] = now
    # Same name on an earlier patch → this is that set moved forward.
    # Auto sets are rebuilt each patch, never carried forward, so they fork from nothing
    # and nothing of his forks from them.
    prior = [] if entry.get("auto") else [
        s for s in data["sets"] if s.get("name", "").lower() == name.lower() and s.get("auto") is not True]
    forked_from = max(prior, key=lambda s: s.get("updated", ""))["id"] if prior else None
    if forked_from:
        entry["forkedFrom"] = forked_from
    data["sets"].insert(0, entry)
    return forked_from


def _save(data, body, auto: bool, now):
    """Build the entry from a validated body and place it in the already-loaded
    `data`. The caller holds _SAVE_LOCK and writes. `auto` comes from the caller,
    never from the body. Returns (entry, existing, forked_from)."""
    name = (body.get("name") or "").strip()
    patch = (body.get("patch") or "").strip()
    sid = _set_id(name, patch)

    entry = {
        "id": sid,
        "name": name,
        "patch": patch,
        "champion": body.get("champion") or None,
        "role": body.get("role") or None,
        "champions": body.get("champions") or [],
        # The rune page is stored, never exported: the client has no rune import,
        # so this is what you read off the saved build and type in yourself.
        "runes": body.get("runes") or None,
        # Summoner spells, ability levels and jungle pathing. Bans are NOT here:
        # they belong to the champion, not the build; see /api/bans below.
        "plan": body.get("plan") or None,
        "blocks": body["blocks"],
        "auto": auto,
        "updated": now,
    }
    if auto:
        for k in ("autoKey", "sources"):
            if body.get(k) is not None:
                entry[k] = body[k]

    existing = next((s for s in data["sets"] if s.get("id") == sid), None)
    existing = _resolve_rename(data, patch, body, existing)
    forked_from = _place_set(data, entry, existing, name, now)
    return entry, existing, forked_from


_UNREADABLE = {"error": "the set library is unreadable, nothing was saved"}


@bp.route("/api/sets", methods=["POST"])
def api_save_set():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "expected a JSON object"}), 400
    err = _set_body_error(body)
    if err:
        payload, status = err
        return jsonify(payload), status

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _SAVE_LOCK:
        try:
            data = _load_library()
        except LibraryUnreadable:
            return jsonify(_UNREADABLE), 500
        # Auto sets are read-only: only api_autobuild writes them. A save that
        # would land on one (same id, or a rename of one) is refused, so the
        # builder can never strip `auto` and hide the row from the next Autobuild.
        sid = _set_id((body.get("name") or "").strip(), (body.get("patch") or "").strip())
        if any(s.get("auto") is True and s.get("id") in (sid, body.get("id")) for s in data["sets"]):
            return jsonify({"error": "auto sets are read-only, copy it to your builds to edit"}), 409
        entry, existing, forked_from = _save(data, body, False, now)
        try:
            _write_library(data)
        except OSError as exc:
            return jsonify({"error": f"could not write the set library: {exc}"}), 500

    return jsonify({"saved": entry, "replaced": bool(existing), "forkedFrom": forked_from})


@bp.route("/api/sets/<path:set_id>", methods=["DELETE"])
def api_delete_set(set_id: str):
    with _SAVE_LOCK:
        try:
            data = _load_library()
        except LibraryUnreadable:
            return jsonify(_UNREADABLE), 500
        kept = [s for s in data["sets"] if s.get("id") != set_id]
        if len(kept) == len(data["sets"]):
            return jsonify({"error": "no set with that id"}), 404
        data["sets"] = kept
        try:
            _write_library(data)
        except OSError as exc:
            return jsonify({"error": f"could not write the set library: {exc}"}), 500
    return jsonify({"deleted": set_id})


@bp.route("/api/autobuild", methods=["POST"])
def api_autobuild():
    from . import autobuild
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "expected a JSON object"}), 400
    champ, role = body.get("champion"), body.get("role")
    if champ not in {c.get("n") for c in _catalog().get("champs") or []}:
        return jsonify({"error": "unknown champion"}), 400
    if role not in ROLES.values():
        return jsonify({"error": "role must be top, jungle, mid, bot or support"}), 400

    live = ".".join(_catalog()["ver"].split(".")[:2])
    gen = autobuild.generate(champ, role, _advice_stores(), POOL, live)  # outside the lock
    outcomes = gen["outcomes"]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    saved: list = []
    with _SAVE_LOCK:
        try:
            data = _load_library()
        except LibraryUnreadable:
            return jsonify(_UNREADABLE), 500
        for b in gen["bodies"]:
            sid = _set_id(b["name"], b["patch"])
            own = next((s for s in data["sets"] if s.get("id") == sid), None)
            if own and own.get("auto") is not True:  # his set, never touched
                o = next(o for o in outcomes if o["key"] == b["autoKey"])
                o.update(state="skipped", why="a set of his own already has this name")
                continue
            saved.append(_save(data, b, True, now)[0]["id"])
        # An auto set goes only when its source was read this run and did not rebuild it.
        down = {o["key"] for o in outcomes if o["state"] == "unavailable"}
        gone = [s["id"] for s in data["sets"]
                if s.get("id") and s.get("auto") is True and s.get("champion") == champ and s.get("role") == role
                and s.get("patch") == live and s.get("id") not in saved
                and s.get("autoKey") not in down
                and not (str(s.get("autoKey")).startswith("lola:") and "lolalytics" in down)]
        data["sets"] = [s for s in data["sets"] if s.get("id") not in gone]
        try:
            _write_library(data)
        except OSError as exc:
            return jsonify({"error": f"could not write the set library: {exc}"}), 500
    return jsonify({"saved": saved, "deleted": gone, "outcomes": outcomes, "dropped": gen["dropped"]})


# Bans are the one thing in the tool NOT keyed by (name, patch). A ban answers
# "who beats this champion", which has nothing to do with which items you bought,
# so every set on a champion reads one list and forking a set forward to a new
# patch does not fork the bans with it. Own file, own two endpoints, keyed by
# champion name lowercased so the builder's casing never splits the list in two.
def _bans() -> dict:
    data = _read(_BANS, None)
    return data if isinstance(data, dict) else {}


@bp.route("/api/me", methods=["GET"])
def api_me():
    """His OP.GG record, decoded, cached, and joined to this tool's own pool.

    The join is the point: a champion row that exists in the Forge links straight
    to its build shelf, so "56% on Viego over 100 games" is one click from the
    sets that produced it. Champions he plays that the Forge has never baked are
    still listed — the record is the record — they just do not link anywhere.

    `?refresh=1` forces past the 15-minute cache, for the button on the page.
    """
    try:
        data = opgg_me.read(_ME, force=request.args.get("refresh") == "1")
    except Exception as e:  # cold cache and OP.GG unreachable: the one real error
        return Response(json.dumps({"error": f"{type(e).__name__}: {e}"}),
                        status=502, mimetype="application/json")

    portraits = {c["n"].lower(): c.get("u") for c in _catalog().get("champs", [])}
    pool = _read(_STATS, {}).get("champions", {})
    lead = {}
    for name, champ in pool.items():
        roles = sorted((champ.get("roles") or {}).items(),
                       key=lambda kv: kv[1].get("n", 0), reverse=True)
        lead[name.lower()] = roles[0][0] if roles else ""

    def link(name: str):
        key = (name or "").lower()
        if key not in lead:
            return None
        # A champion name is a path segment, and "Master Yi" has a space in it.
        slug = quote(name)
        return f"c/{slug}/{lead[key]}" if lead[key] else f"c/{slug}"

    for row in data.get("champions", []):
        row["portrait"] = portraits.get((row.get("champion") or "").lower())
        row["href"] = link(row.get("champion"))
    for row in data.get("matches", []):
        row["portrait"] = portraits.get((row.get("champion") or "").lower())
        row["href"] = link(row.get("champion"))

    return Response(json.dumps(data), mimetype="application/json")


@bp.route("/api/bans/<champ>", methods=["GET"])
def api_bans(champ: str):
    """One champion's ban list. Champion keys, as the catalog numbers them."""
    return jsonify({"champion": champ,
                    "champions": _bans().get(champ.strip().lower(), [])})


@bp.route("/api/bans/<champ>", methods=["PUT"])
def api_save_bans(champ: str):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"error": "expected a JSON object"}), 400
    raw = body.get("champions")
    if not isinstance(raw, list):
        return jsonify({"error": "champions must be a list"}), 400
    # Ints only, deduped, order kept: these are catalog champion keys, and a
    # string that looks like one would miss every lookup on the page.
    seen, keys = set(), []
    for k in raw:
        try:
            n = int(k)
        except (TypeError, ValueError):
            return jsonify({"error": f"not a champion key: {k!r}"}), 400
        if n not in seen:
            seen.add(n)
            keys.append(n)

    data = _bans()
    key = champ.strip().lower()
    if keys:
        data[key] = keys
    else:
        data.pop(key, None)   # an emptied list is a removed entry, not an empty one
    try:
        _BANS.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
    except OSError as exc:
        return jsonify({"error": f"could not write the ban list: {exc}"}), 500
    return jsonify({"champion": champ, "champions": keys})


@bp.route("/draft")
def draft():
    """The Draft surface: his live champ select, picks, then build and game plan."""
    return send_from_directory(_FRONTEND, "draft.html")


def _post_gate():
    """(error response | None, remote) for a loopback-only POST, one rule for all three.
    The Host check stops a DNS-rebound web page posting through his browser."""
    if request.host.rsplit(":", 1)[0] not in ("127.0.0.1", "localhost", "[::1]"):
        return (jsonify({"ok": False, "error": "loopback host only"}), 403), ""
    proxied = "X-Forwarded-For" in request.headers or "Tailscale-User-Login" in request.headers
    bad = draft_feed.check_post(request.content_length, proxied, request.remote_addr)
    if bad:
        return (jsonify({"ok": False, "error": bad[1]}), bad[0]), ""
    return None, request.remote_addr or ""


@bp.route("/api/draft/session", methods=["POST"])
def api_draft_session():
    """The Windows poller's post (forge/lcu_poller.py). Loopback callers only."""
    bad, remote = _post_gate()
    if bad:
        return bad
    code, msg = draft_feed.accept(request.get_json(silent=True), remote, time.time())
    return jsonify({"ok": code < 300, "message": msg}), code


@bp.route("/api/draft/ingame", methods=["POST"])
def api_draft_ingame():
    """The poller's Live Client read: each player's keystone and items. Loopback only."""
    bad, remote = _post_gate()
    if bad:
        return bad
    code, msg = draft_feed.accept_ingame(request.get_json(silent=True), remote, time.time())
    return jsonify({"ok": code < 300, "message": msg}), code


@bp.route("/api/draft/pick", methods=["POST"])
def api_draft_pick():
    """His archetype choice for one champion on the live page: {champion, archetypeId}.
    Held in memory until the next champ select. Loopback only, like the posts above."""
    bad, _ = _post_gate()
    if bad:
        return bad
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"ok": False, "message": "expected a JSON object"}), 400
    champ, arch = body.get("champion"), body.get("archetypeId")
    if arch and not _known_archetype(champ, arch):
        return jsonify({"ok": False, "message": "no such archetype"}), 400
    code, msg = draft_feed.set_pick(champ, arch)
    return jsonify({"ok": code < 300, "message": msg}), code


@bp.route("/api/draft", methods=["GET"])
def api_draft():
    """Feed state for the Draft page. The app-wide _conditional_json hook gives it
    an ETag over the whole body, so a 0.5 s poll costs a 304 until something moves."""
    now = time.time()
    out = draft_feed.state(now)
    out.update(_draft_advice(out.get("draft"), draft_feed.picks(), draft_feed.ingame_players(now)))
    return jsonify(out)


@bp.route("/api/draft/mock", methods=["GET"])
def api_draft_mock():
    """A draft he builds by hand, run through the same engine. Reads and writes
    nothing in the live feed. Ids are champion ids (catalog `k`); `allies` is
    `id:role` pairs, `enemies` and `bans` are id lists, `locked=1` locks `me`.
    `queue` is the queue id (450 ARAM), `picks` is `champion:archetypeId` pairs. It never
    reads the live feed's picks or in-game state (Check 9)."""
    def ids(name):
        return [int(x) for x in request.args.get(name, "").split(",") if x.isascii() and x.strip().isdigit()]

    def seats(name):
        out = []
        for i, pair in enumerate(x for x in request.args.get(name, "").split(",") if x.strip()):
            cid, _, role = pair.partition(":")
            out.append({"cellId": i + 1, "role": role or None, "championId": int(cid) if cid.isascii() and cid.isdigit() else None,
                        "provisional": False, "spells": [0, 0]})
        return out

    me_id = request.args.get("me", type=int)
    locked = request.args.get("locked") == "1"
    draft = {"me": {"cellId": 0, "role": request.args.get("role") or None,
                    "championId": me_id if locked else None, "hover": None if locked else me_id,
                    "spells": [0, 0]},
             "allies": seats("allies"),
             "enemies": [{"championId": c, "likelyRole": None} for c in ids("enemies")],
             "bans": ids("bans"), "runes": None, "queueId": request.args.get("queue", type=int)}
    picks = {c: i for c, _, i in (p.partition(":") for p in request.args.get("picks", "").split(",")) if c and i}
    out = {"live": False, "status": "mock", "seq": None, "capturedAt": None, "draft": draft,
           "replay": False, "error": None}
    out.update(_draft_advice(draft, picks))
    return jsonify(out)


@bp.route("/api/draft/roles", methods=["GET"])
def api_draft_roles():
    """Champions who play each role (at least ROLE_FLOOR of their games there), for
    the mock draft's Shuffle. Names, as the pick lists use them."""
    from . import draft_engine
    shares = _advice_stores()["matchups"].get("roleShares") or {}
    roles = {r: sorted(c for c, s in shares.items() if (s or {}).get(r, 0) >= draft_engine.ROLE_FLOOR)
             for r in ("top", "jungle", "mid", "bot", "support")}
    return jsonify(roles)


_lobbies: dict = {}   # ponytail: a finished game never changes, so no expiry; a few KB per game opened


@bp.route("/api/draft/history", methods=["GET"])
def api_draft_history():
    """His recent games for the mock draft's Past game picker, off the /api/me cache.
    `?id=&at=` instead returns that game's lobby as catalog keys, ready for the mock."""
    try:
        gid, at = request.args.get("id"), request.args.get("at")
        if not gid:
            games = opgg_me.read(_ME).get("matches", [])
            return jsonify([dict({k: g.get(k) for k in ("id", "at", "queue", "champion", "win")},
                                 role=opgg_me._POSITION.get(g.get("position"))) for g in games])
        if gid not in _lobbies:
            _lobbies[gid] = opgg_me.lobby(gid, at or "")
        lb = _lobbies[gid]
    except Exception as e:  # op.gg down or the game id unknown to it
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 502

    keys = {c["n"].lower(): c["k"] for c in _catalog().get("champs", [])}
    key = lambda n: keys.get((n or "").lower())
    return jsonify({"win": lb["win"],
                    "me": {"k": key(lb["me"]["champion"]), "role": lb["me"]["role"]},
                    "allies": [{"k": key(a["champion"]), "role": a["role"]} for a in lb["allies"]],
                    "enemies": [key(e["champion"]) for e in lb["enemies"]],
                    "bans": [k for k in map(key, lb["bans"]) if k is not None]})


_ADVICE_FILES = ("forge-traits.json", "forge-matchups.json", "forge-draft.json", "forge-me.json",
                 "forge-stats.json", "forge-lolalytics.json", "forge-mino.json", "forge-item-traits.json",
                 "forge-archetypes.json", "forge-identity.json", "forge-stats-roster.json", "forge-spikes.json",
                 "forge-sets.json", "forge-mayhem.json")
_advice_cache: dict = {}
_pages_cache: dict = {}


def _pages() -> dict:
    """The champion page store (14 MB), read only by the champion route under its own
    mtime, so a draft-poll store change never re-parses it."""
    f = vault_root() / "data" / "forge-champions.json"
    key = f.stat().st_mtime if f.exists() else 0
    if _pages_cache.get("key") != key:
        try:
            pages = json.loads(f.read_text(encoding="utf-8")) if key else {}
        except ValueError:
            pages = {}
        _pages_cache.update(key=key, pages=pages)
    return _pages_cache["pages"]


def _advice_stores() -> dict:
    """Both engines' stores, re-read only when a store file changes on disk."""
    from . import build_engine
    data, static = vault_root() / "data", Path(__file__).resolve().parent / "frontend" / "static"
    paths = [data / f for f in _ADVICE_FILES] + [static / "catalog.json", static / "runes.json"]
    key = tuple(p.stat().st_mtime if p.exists() else 0 for p in paths)
    if _advice_cache.get("key") != key:
        stores = build_engine.load_stores()
        for k, name, empty in (("identity", "forge-identity.json", {}),
                               ("roster", "forge-stats-roster.json", None),
                               ("spikes", "forge-spikes.json", {})):
            f = data / name
            try:
                stores[k] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else empty
            except ValueError:
                stores[k] = empty
        _advice_cache.update(key=key, stores=stores)
    return _advice_cache["stores"]


def _draft_advice(draft, picks=None, players=None) -> dict:
    """Engine output for the page: pick lists and traits while picking, plus the
    build once he locks. `picks` is his archetype choices, `players` the in-game
    reads (live only; mock passes neither). A failure is a short code, never a 500
    on a 0.5 s poll."""
    if not draft:
        return {"advice": None, "build": None}
    from . import build_engine, draft_engine
    try:
        stores = _advice_stores()
        ingame = _ingame_matches(draft, stores, players)
        advice = draft_engine.run(draft, stores, picks or None, ingame or None)
        _seat_archetypes(advice, draft, stores)
        build = None
        me = draft.get("me") or {}
        if me.get("championId") and advice.get("me") and draft.get("queueId") in draft_engine.MAYHEM_QUEUES:
            advice["mayhem"] = True
            build = build_engine.mayhem(advice["me"], stores)
        elif me.get("championId") and advice.get("me") and me.get("role"):
            cur = (advice.get("archetypes") or {}).get(advice["me"]) or {}
            arch = cur["list"][cur["index"]] if cur.get("index") is not None else {}
            build = build_engine.run(advice["me"], me["role"], draft, stores, arch.get("keystone"))
        m = stores["matchups"]
        advice["stores"] = {"matchups": m.get("patch"), "traits": stores.get("traitsPatch"),
                            "opggFetchedAt": getattr(stores.get("opgg"), "fetched_at", None)}
        return {"advice": advice, "build": build}
    except Exception as exc:  # noqa: BLE001 - shown as ENGINE, detail to the log
        current_app.logger.exception("draft engine failed")
        return {"advice": None, "build": None, "engineError": f"ENGINE: {type(exc).__name__}"}


def _known_archetype(champ, arch_id) -> bool:
    """Whether any mode holds this build for this champion, so a pick the engine would
    silently ignore is refused instead of answered ok."""
    modes = (_advice_stores().get("archetypes") or {}).get("modes") or {}
    return any(a.get("id") == arch_id for by_champ in modes.values()
               for entry in (by_champ.get(champ) or {}).values() for a in entry.get("archetypes") or [])


def _role_entries(stores: dict, mode: str, champ: str) -> dict:
    from . import draft_engine
    return draft_engine.role_entries(stores, mode, champ)


def _ingame_matches(draft: dict, stores: dict, players) -> dict:
    """{champion: archetypeId} for every in-game player whose keystone and items point
    at one archetype. ponytail: matches across all of the champion's roles at once
    (a player's role is not in the read), so a tie across roles keeps the pick."""
    from . import draft_engine
    mode = draft_engine.mode_for(draft)[0]
    out = {}
    for pl in players or []:
        arches = [a for r in _role_entries(stores, mode, pl.get("champion")).values()
                  for a in r.get("archetypes") or []]
        hit = draft_feed.match_items(pl, arches) if arches else None
        if hit:
            out[pl["champion"]] = hit
    return out


def _coachless(roster, champ: str, role: str, arch: dict) -> dict:
    """WPA beside the lolalytics win rate, with what each reading is conditioned on.
    A keystone reading is never core-specific; None is a reading coachless does not
    have (the page strikes it); `state` keeps an API miss apart from a real absence."""
    if not isinstance(roster, dict):
        return {"state": "unbaked"}
    got = ((roster.get("champions") or {}).get(champ) or {}).get(role)
    if got is None:
        return {"state": "unbaked", "patch": roster.get("patch")}
    if got.get("miss"):
        return {"state": "api-miss" if got["miss"] == "api" else "absent", "patch": roster.get("patch")}
    ks = next((k for k in got.get("keystones") or [] if k.get("id") == arch.get("keystone")), None)
    by_ks = (got.get("items") or {}).get("byKeystone") or {}
    rows = {r.get("id"): r for r in by_ks.get(str(arch.get("keystone"))) or []}

    def pick(r):
        return {"wpa": r.get("wpa"), "n": r.get("n")} if r and r.get("wpa") is not None else None
    return {"state": "ok", "patch": roster.get("patch"),
            "keystone": pick(ks), "keystoneConditioning": "role",
            "items": {str(i): pick(rows.get(i)) for i in arch.get("core") or []},
            "itemsConditioning": "role + keystone"}


def _facts(row) -> dict:
    """Trait rows the page may state as fact: a judged row is an opinion, never one."""
    return {k: v for k, v in (row or {}).items() if not (isinstance(v, dict) and v.get("source") == "judged")}


def _trait_spread(stores: dict, mode: str) -> dict:
    """{trait: sorted numbers} over every champion's best archetype reading in one mode,
    for placing one champion's value among the rest (mark 2026-11-04-065542:2). One
    value per champion, its highest across roles and archetypes, so a champion with
    nine archetypes does not count nine times. Cached with the stores it reads."""
    cache = _advice_cache.setdefault("spread", {})
    if cache.get("of") is not stores:
        cache.clear()
        cache["of"] = stores
    if mode not in cache:
        per: dict[str, list[float]] = {}
        for roles in (((stores.get("archetypeTraits") or {}).get(mode)) or {}).values():
            best: dict[str, float] = {}
            for arches in (roles or {}).values():
                for row in (_facts(r) for r in (arches or {}).values()):
                    for k, t in row.items():
                        v = t.get("value") if isinstance(t, dict) else None
                        if isinstance(v, (int, float)) and not isinstance(v, bool):
                            best[k] = max(best.get(k, v), v)
            for k, v in best.items():
                per.setdefault(k, []).append(v)
        cache[mode] = {k: sorted(v) for k, v in per.items()}
    return cache[mode]


def _placed(spread: list, v) -> float | None:
    """Share of champions below v, ties counted half: 0 lowest, 1 highest. None
    when there is nothing to compare against or every champion reads the same."""
    if not isinstance(v, (int, float)) or isinstance(v, bool) or len(spread) < 5 or spread[0] == spread[-1]:
        return None
    lo, hi = bisect.bisect_left(spread, v), bisect.bisect_right(spread, v)
    return round((lo + (hi - lo) / 2) / len(spread), 3)


def _with_place(row: dict, spread: dict) -> dict:
    out = {}
    for k, t in row.items():
        place = _placed(spread.get(k) or [], t.get("value")) if isinstance(t, dict) else None
        out[k] = {**t, "place": place, "of": len(spread.get(k) or [])} if place is not None else t
    return out


def _mode_roles(stores: dict, mode: str, champ: str) -> dict:
    """Every role and archetype of one mode, with coachless and traits beside each;
    each numeric trait carries `place`, where it sits among every champion (0 to 1)."""
    traits = ((stores.get("archetypeTraits") or {}).get(mode) or {}).get(champ) or {}
    spread = _trait_spread(stores, mode)
    out = {}
    for role, entry in _role_entries(stores, mode, champ).items():
        out[role] = {**entry, "archetypes": [
            {**a, "coachless": _coachless(stores.get("roster"), champ, role, a),
             "traits": _with_place(_facts((traits.get(role) or {}).get(a.get("id"))), spread)}
            for a in entry.get("archetypes") or []]}
    return out


@bp.route("/api/champion/<champ>", methods=["GET"])
def champion_page(champ: str):
    """One champion's page: the store row joined at serve time with archetypes, traits,
    coachless and the quote, each store's version named so the page can say what is stale."""
    stores = _advice_stores()
    cat = next((c for c in stores.get("catalogChamps") or [] if c["n"].lower() == champ.lower()), None)
    if cat is None:
        return jsonify({"error": f"no champion named {champ}"}), 404
    name, pages = cat["n"], _pages()
    page = (pages.get("champions") or {}).get(name)
    calc = ((page or {}).get("calc") or {}).get("src") or {}
    arch, roster = stores.get("archetypes") or {}, stores.get("roster")
    return jsonify({
        "name": name, "id": cat["i"], "portrait": cat.get("u"), "page": page,
        "quote": (stores.get("identity") or {}).get(name),
        "spikes": _spikes(stores, name),
        "styles": _styles().get(name) or [],
        "patchDates": _patch_dates(page, pages.get("patchDates") or {}),
        "statPlaces": _stat_places(pages.get("champions") or {}, name),
        "modes": {m: _mode_roles(stores, m, name) for m in (arch.get("modes") or {})},
        "versions": {"page": pages.get("generation"), "archetypes": arch.get("generation"),
                     "traits": stores.get("traitsGeneration"),
                     "roster": roster.get("patch") if isinstance(roster, dict) else None,
                     "calc": "not read" if not calc else
                             "current" if calc.get("version") == stores.get("traitsGeneration") else "stale"},
    })


def _stat_values(page) -> dict:
    """{stat: [base, per level]} off one page, calculator first, wiki where it has none."""
    s = ((page or {}).get("stats") or {}).get("value") or {}
    out = {**(s.get("wiki") or {}), **(s.get("calculator") or {})}
    return {k: (v if isinstance(v, list) else [v, None]) for k, v in out.items()}


def _stat_places(champs: dict, name: str) -> dict:
    """{stat: [base place, per-level place]}: where this champion's base stats sit among
    every baked champion, 0 lowest to 1 highest (mark 2026-11-05-024817:4). A column every
    champion shares (most read 0 mana) gets None.
    ponytail: rebuilt per request, ~170 pages; cache on the pages generation if it shows."""
    mine = _stat_values(champs.get(name))
    spread: dict = {}
    for page in champs.values():
        for k, pair in _stat_values(page).items():
            for i, v in enumerate(pair[:2]):
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    spread.setdefault((k, i), []).append(v)
    return {k: [_placed(sorted(spread.get((k, i)) or []), v) for i, v in enumerate(pair[:2])]
            for k, pair in mine.items()}


def _patch_dates(page, dates: dict) -> dict:
    """{history heading: release date} for this champion's patches that the wiki dates."""
    from .bake_champions import patch_date
    heads = [p.get("patch") for p in (((page or {}).get("history") or {}).get("value") or [])]
    return {h: d for h in heads if (d := patch_date(h, dates))}


def _spikes(stores: dict, champ: str, role: str | None = None) -> dict | None:
    """The power-spikes sheet rows for one champion: the role's own row when the sheet
    has one, every row otherwise (Kayn has Blue and Red)."""
    doc = stores.get("spikes") or {}
    rows = (doc.get("champions") or {}).get(champ) or []
    if role:
        rows = [r for r in rows if r.get("role") == role] or [r for r in rows if r.get("role") is None] or rows
    return {"rows": rows, "source": doc.get("source")} if rows else None


def _seat_archetypes(advice: dict, draft: dict, stores: dict) -> None:
    """Widen the engine's {id, why, state, note} per champion into everything the seat
    draws: the list of builds (with coachless beside lolalytics), the resolved index,
    source pills and the champion identity quote."""
    mode = advice.get("mode") or "ranked"
    me = draft.get("me") or {}
    roles = dict((advice.get("teams") or {}).get("enemyRoles") or {})
    names = stores["names"]
    roles.update({names[a["championId"]]: a.get("role") for a in draft.get("allies") or []
                  if a.get("championId") in names})
    if advice.get("me"):
        roles[advice["me"]] = me.get("role")
    store = stores.get("archetypes") or {}
    patch = store.get("patch")
    for champ, cur in (advice.get("archetypes") or {}).items():
        by_role = _role_entries(stores, mode, champ)
        role = "aram" if mode == "aram" else roles.get(champ)
        if role is None and by_role:    # the engine's own fallback: the champion's biggest role
            role = max(by_role, key=lambda r: by_role[r].get("roleGames") or 0) if by_role else None
        entry = by_role.get(role) or {}
        lst = []
        for a in entry.get("archetypes") or []:
            lst.append({k: a.get(k) for k in ("id", "keystone", "core", "share", "keystoneShare", "wr",
                                              "games", "state", "path", "boots", "runes", "skills")}
                       | {"coachless": _coachless(stores.get("roster"), champ, role, a)})
        idx = next((i for i, a in enumerate(lst) if a["id"] == cur.get("id")), None)
        cl = [a["coachless"].get("state") for a in lst]
        ident = (stores.get("identity") or {}).get(champ)
        cur.update(role=role, roleGames=entry.get("roleGames"), roleWr=entry.get("roleWr"),
                   list=lst, index=idx, n=None if idx is None else idx + 1, of=len(lst),
                   sources=[{"name": "lolalytics", "label": f"lolalytics {patch}" if patch else "lolalytics",
                             "struck": not lst},
                            {"name": "coachless",
                             "label": f"coachless (patch {(stores.get('roster') or {}).get('patch')})"
                                      if isinstance(stores.get("roster"), dict) else "coachless",
                             "struck": not any(c == "ok" for c in cl)}],
                   identity={k: ident.get(k) for k in ("quote", "url", "title", "uploaded")} if ident else None,
                   spikes=_spikes(stores, champ, role))
