"""Canonical hub module list — the ONE source of truth for the launcher.

Lives in its own importable module (not app.py) because app.py runs as
``__main__``; importing app.py to reach the list would re-execute the whole
server. Both app.py and work/api.py import ``MODULES`` from here, and the
``/hub-modules.js`` route serves it to every page's ``window.MODULES`` so the
vanilla launcher (theme-switch.js) and the React pages all read one list.

Previously this list was copied three ways (app.py, work/api.py, theme-switch.js)
and silently drifted — finances fell out of two copies. Add or rename a module
HERE and it propagates everywhere.

Tiers: `home` mainstay on top, then four groups by what he goes there to do:
`today`, `life`, `career`, `system` (one launcher column each, picked on
Workbench 2026-10-11 as "Soft header bands"). Order is tier-contiguous and is
the order inside each column.

``icon`` is the body of a ``<svg viewBox="0 0 24 24">`` drawn per module, so the
launcher tile reads as a shape before it reads as text. Both launchers render it
the same way; the styling contract lives in chrome.css ``.tile-glyph``:

* Stroke-only, no fill, ``currentColor`` — every theme and surface paints it free.
* **Every straight stroke center sits on the sequence 1.2n + 0.6**
  (3.0, 4.2, 5.4 … 21.0). The glyphs render at exactly 20px, and 20/24 is a 5/6
  scale, so those values are the ones that land a stroke center on a whole CSS
  pixel; anything else smears the stroke across two pixels. Measured, not
  assumed. This is also why the tile-home glyph is not scaled up: the sequence
  only holds at 20px (and 60px), so a 28px copy would render blurrier, not bigger.
  Diagonal vertices are exempt — no grid helps a 45-degree line.
* Every glyph is centered on **x = 12.6**, not 12.0, so the axis itself lands on
  the grid. Uniform across the set, so the marks still align with each other.
* Enclosed counters (the tag hole, the vault-map nodes) stay at r >= 2.1, or the
  1.4 stroke closes them into solid dots at 20px.

Redrawn 2026-08-10 after an /adversarial pass on the first set.
"""

MODULES = [
    {
        "name": "home",
        "desc": "overview. today, schedule, cards, tasks.",
        "meta": "current",
        "href": "/",
        "tier": "home",
        "icon": (
            '<path d="M4.2 10.2 L12.6 3 L21 10.2 V21 H4.2 Z"/>'
            '<path d="M10.2 21 V13.8 H15 V21"/>'
        ),
    },
    {
        "name": "news",
        "desc": "clustered coverage across outlets, lean-balanced.",
        "meta": "→ /news",
        "href": "/news/",
        "tier": "today",
        # A page with a headline rule and two body lines, the last one short,
        # a newspaper column. Straight stroke centres on 1.2n + 0.6 per the grid
        # rules at the top of this file.
        "icon": (
            '<rect x="4.2" y="3" width="16.8" height="18" rx="1.2"/>'
            '<path d="M6.6 7.8 H18.6"/>'
            '<path d="M6.6 11.4 H18.6"/>'
            '<path d="M6.6 13.8 H15"/>'
        ),
    },
    {
        "name": "checklists",
        "desc": "reusable checklists — packing, prep, recurring routines.",
        "meta": "→ /checklists",
        "href": "/checklists/",
        "tier": "today",
        "icon": (
            '<rect x="4.2" y="3" width="7.2" height="7.2" rx="1.2"/>'
            '<path d="M6 6.6 L7.8 8.4 L10.2 5.4"/>'
            '<rect x="4.2" y="13.8" width="7.2" height="7.2" rx="1.2"/>'
            '<path d="M13.8 6.6 H21"/>'
            '<path d="M13.8 17.4 H21"/>'
        ),
    },
    {
        "name": "automations",
        "desc": "background lanes: what they did, what awaits your yes.",
        "meta": "→ /automations",
        "href": "/automations/",
        "tier": "today",
        # A bolt of lightning. Diagonal vertices are exempt from the grid
        # rules at the top of this file; the top and bottom ends sit on the
        # 1.2n + 0.6 sequence (3.0, 21.0).
        "icon": (
            '<path d="M13.8 3 L5.4 13.2 H12.6 L11.4 21 L19.8 10.8 H12.6 Z"/>'
        ),
    },
    {
        "name": "mail",
        "desc": "inbox by sender: read, sort, summarize and draft. never sends.",
        "meta": "→ /mail",
        "href": "/mail/",
        "tier": "today",
        # An envelope; straight strokes on 1.2n + 0.6, the flap's diagonals exempt.
        "icon": (
            '<rect x="4.2" y="5.4" width="16.8" height="13.2" rx="1.2"/>'
            '<path d="M4.2 7.8 L12.6 13.8 L21 7.8"/>'
        ),
    },
    {
        # the money umbrella — earnings + stocks live here as tabs; each still
        # backed by its own db (earnings.db / stocks.db). Adding a money surface
        # = a new tab in /finances, not a new launcher tile.
        "name": "finances",
        "desc": "earnings + stocks — the money umbrella.",
        "meta": "→ /finances",
        "href": "/finances/",
        "tier": "life",
        # bars climb monotonically. The first draft had a dip and a spike, which
        # read as a random chart rather than as "money".
        "icon": '<path d="M3 21 H22.2 M5.4 21 V16.2 M10.2 21 V13.8 M15 21 V10.2 M19.8 21 V6.6"/>',
    },
    {
        "name": "purchases",
        "desc": "buy-or-skip research decisions.",
        "meta": "→ /purchases",
        "href": "/purchases/",
        "tier": "life",
        "icon": (
            '<path d="M12.6 3 H19.8 A1.2 1.2 0 0 1 21 4.2 V12.6 L12.6 21 L4.2 12.6 Z"/>'
            '<circle cx="17.4" cy="7.8" r="2.1"/>'
        ),
    },
    {
        "name": "trips",
        "desc": "trip planner — flights, housing, activities.",
        "meta": "→ /trips",
        "href": "/trips/",
        "tier": "life",
        "icon": (
            '<path d="M12.6 3 C13.5 3 13.8 4.2 13.8 5.4 V10.2 L22.2 15 V16.2 L13.8 13.8 V18.6 '
            "L16.2 19.8 V21 L12.6 19.8 L9 21 V19.8 L11.4 18.6 V13.8 L3 16.2 V15 L11.4 10.2 V5.4 "
            'C11.4 4.2 11.7 3 12.6 3 Z"/>'
        ),
    },
    {
        "name": "food",
        "desc": "restaurants worth eating at, with the evidence.",
        "meta": "→ /food",
        "href": "/food/",
        "tier": "life",
        # Bowl with steam. Every straight stroke centre sits on 1.2n + 0.6 and the
        # glyph is centred on x = 12.6, per the grid rules at the top of this file.
        "icon": (
            '<path d="M4.2 11.4 H21"/>'
            '<path d="M5.4 11.4 A7.2 7.2 0 0 0 19.8 11.4"/>'
            '<path d="M10.2 4.2 V8.4"/>'
            '<path d="M15 4.2 V8.4"/>'
        ),
    },
    {
        "name": "recipes",
        "desc": "mom's recipe library — scale it, shop it, cook it.",
        "meta": "→ /recipes",
        "href": "/recipes/",
        "tier": "life",
        # Open book / splayed pages: two leaves off a centre spine at x = 12.6. Straight
        # stroke centres on 1.2n + 0.6 (4.2, 6.6, 12.6, 18.6, 21.0) per the grid rules at
        # the top of this file; the page curves are arcs, which the grid does not govern.
        "icon": (
            '<path d="M12.6 6.6 V21"/>'
            '<path d="M12.6 6.6 C10.2 4.2 7.2 4.2 4.2 5.4 V18.6 C7.2 17.4 10.2 17.4 12.6 19.8"/>'
            '<path d="M12.6 6.6 C15 4.2 18 4.2 21 5.4 V18.6 C18 17.4 15 17.4 12.6 19.8"/>'
        ),
    },
    {
        "name": "gaming",
        "desc": "league and cs2 tools, notes and dossiers.",
        "meta": "→ /gaming",
        "href": "/gaming/",
        "tier": "life",
        # A game controller from above: rounded body, d-pad cross left, two button ticks
        # right. Straight stroke centres on 1.2n + 0.6 per the grid rules at the top of
        # this file; body spans 3.0 to 22.2, centred on x = 12.6.
        "icon": (
            '<rect x="3" y="7.8" width="19.2" height="9.6" rx="4.2"/>'
            '<path d="M7.8 10.2 V15"/>'
            '<path d="M5.4 12.6 H10.2"/>'
            '<path d="M16.2 11.4 H17.4"/>'
            '<path d="M18.6 13.8 H19.8"/>'
        ),
    },
    {
        "name": "work",
        "desc": "all your work dashboards, by job.",
        "meta": "→ /work",
        "href": "/work/",
        "tier": "career",
        "icon": (
            '<rect x="4.2" y="7.8" width="16.8" height="13.2" rx="1.2"/>'
            '<path d="M10.2 7.8 V5.4 A1.2 1.2 0 0 1 11.4 4.2 H13.8 A1.2 1.2 0 0 1 15 5.4 V7.8"/>'
            '<path d="M4.2 13.8 H21"/>'
        ),
    },
    # (standalone "barback" tile removed — barback lives inside /work/)
    {
        # renamed apply → jobs (2026-09-28), reversing the earlier jobs → apply
        # rename. /apply/* still 308-redirects (app.py) so old bookmarks and
        # links keep working.
        "name": "jobs",
        "desc": "application pipeline — intake, research, prep.",
        "meta": "→ /jobs",
        "href": "/jobs/",
        "tier": "career",
        "icon": (
            '<path d="M6.6 3 H15 L18.6 6.6 V21 H6.6 Z"/>'
            '<path d="M15 3 V6.6 H18.6"/>'
            '<path d="M9 12.6 H16.2"/>'
            '<path d="M9 16.2 H13.8"/>'
        ),
    },
    {
        "name": "workbench",
        "desc": "specs, plans and design picks: approve or send back.",
        "meta": "→ /workbench",
        "href": "/workbench/",
        "tier": "system",
        # a checkmark in a box: sign-off.
        "icon": (
            '<rect x="3" y="3" width="18" height="18" rx="1.2"/>'
            '<path d="M6.6 12.6 L10.2 16.2 L18 7.8"/>'
        ),
    },
    {
        "name": "blueprints",
        "desc": "the shared ui blueprints — build from these, not from scratch.",
        "meta": "→ /blueprints",
        "href": "/blueprints/",
        "tier": "system",
        # three stacked bars of decreasing width: a component sheet. Drawn on the
        # same 1.2n+0.6 stroke grid as the other marks so it lands on whole pixels
        # at 20px (see chrome.css .tile-glyph).
        "icon": (
            '<rect x="3" y="4.2" width="18" height="4.8" rx="1.2"/>'
            '<rect x="3" y="12" width="12" height="4.8" rx="1.2"/>'
            '<path d="M18 14.4 H21"/>'
        ),
    },
    {
        "name": "capabilities",
        "desc": "every skill on the machine — what it does and where it lives.",
        "meta": "→ /capabilities",
        "href": "/capabilities/",
        "tier": "system",
        # the four-point glint from static/assets/mark-*.svg — the Hub's own mark,
        # reused rather than invented. Waist sits 2.4 off center so the arms keep a
        # body; pulled tighter it collapses into needles.
        "icon": (
            '<path d="M12.6 3 L15 10.2 L22.2 12.6 L15 15 L12.6 22.2 L10.2 15 L3 12.6 L10.2 10.2 Z"/>'
        ),
    },
    {
        "name": "inventory",
        "desc": "every program on each computer, and how to put them back.",
        "meta": "→ /inventory",
        "href": "/inventory/",
        "tier": "system",
        # a box with a lid line and a label bar: stock on a shelf.
        "icon": (
            '<path d="M4.2 5.4 H21 V10.2 H4.2 Z M5.4 10.2 V19.8 H19.8 V10.2 M10.2 14.4 H15"/>'
        ),
    },
    {
        "name": "artifacts",
        "desc": "every published claude.ai artifact, grouped by category.",
        "meta": "→ /artifacts",
        "href": "/artifacts/",
        "tier": "system",
        "icon": (
            '<path d="M12.6 3 L21 7.5 L12.6 12 L4.2 7.5 Z"/>'
            '<path d="M4.2 12 L12.6 16.2 L21 12"/>'
            '<path d="M4.2 16.2 L12.6 20.4 L21 16.2"/>'
        ),
    },
    {
        "name": "viewer",
        "desc": "what Claude shows you, full size, and a drop box for files back.",
        "meta": "→ /viewer",
        "href": "/viewer/",
        "tier": "system",
        "icon": (
            '<rect x="3.6" y="4.8" width="17.4" height="14.4" rx="2"/>'
            '<circle cx="9" cy="10.2" r="1.8"/>'
            '<path d="M3.6 17 L9.6 12.6 L14 16 L17 13.8 L21 17"/>'
        ),
    },
    {
        "name": "vault map",
        "desc": "every file in the second brain, classified and described.",
        "meta": "→ /vault-map",
        "href": "/vault-map/",
        "tier": "system",
        "icon": (
            '<circle cx="12.6" cy="4.2" r="2.4"/>'
            '<circle cx="5.4" cy="18.6" r="2.4"/>'
            '<circle cx="19.8" cy="18.6" r="2.4"/>'
            '<path d="M12.6 6.6 V11.4 M5.4 11.4 H19.8 M5.4 11.4 V16.2 M19.8 11.4 V16.2"/>'
        ),
    },
]
