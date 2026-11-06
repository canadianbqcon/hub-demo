# CLAUDE-new-module.md — blueprint for a new Hub dashboard module

Loaded in addition to `dashboard/CLAUDE.md` when scaffolding a **new** Hub module (a new
top-level dashboard surface under `hub/<module>/`, its own database, its own tab in the
launcher). Distilled from `trips/` — the largest, most-evolved module in the Hub — plus
the shared conventions every other module (purchases, jobs, stocks, recipes) already
follows. Read `dashboard/CLAUDE.md` first; this file is the worked pattern, not a
replacement for the standards it points at.

Before scaffolding anything, check `/blueprints` (or `python -m blueprints.resolve` when the
Hub isn't running) for a component that already does what the new page needs — see
`CLAUDE-blueprints.md`. A new module is new *data and routes*, not new buttons.

## File layout

```
hub/<module>/
  __init__.py
  api.py                    # Flask Blueprint: routes, page + /api/*
  db.py                     # SQLite layer: init(), CRUD, one module-level _db_path
  frontend/
    <module>.html           # the page template
    static/
      <module>.css          # token-only styling
      <module>.js           # page logic
```

One module = one file each for api/db, growing in place. Trips only split further
(`forms_intake.py`, `grocery_base.py`, `preferences.py`) because those are genuinely
separate concerns (Google Forms sync, a grocery-trim algorithm, a preferences merge) —
don't pre-split a new module into pieces it doesn't have yet.

**Past 500 lines, split behind a facade.** `trips/api.py`, `db.py`, `forms_intake.py` and
`public_app.py` were split this way on 2026-09-24 (spec
`docs/archive/specs/2026-09-24-trips-split-complexity-design.md` in the vault). The old file
stays as the facade. It owns every module-level name (`_db_path`, `bp`, constants, optional-module
globals, mutable state), and it re-exports moved functions by explicit name. Section files
(`db_<part>.py`, `api_<part>.py`) do `from . import db` or `from . import api as _api` and reach
every facade name at call time. They never use `from .db import X`, because tests
`monkeypatch.setattr` on the facade, and a by-value import would silently dodge the patch. At
import time a section may evaluate only `_api.bp` in its route decorators. The facade imports its
sections at the bottom. `dashboard/hub/tests/test_trips_facades.py` enforces all of this for
trips, so copy it when you split another module.

## Database layer (`db.py`)

Pattern, copied from `trips/db.py`:

```python
from sqlite_helpers import connect as sqlite_connect, row as _row, row_strict as _row_strict, rows as _rows

_db_path: Path | None = None

def init(db_path: Path) -> None:
    """Idempotent bootstrap: CREATE TABLE IF NOT EXISTS, then additive ALTER
    TABLE ... ADD COLUMN in a try/except-swallow loop for every column added
    since. Order matters: every CREATE before any ALTER, or a fresh file's
    ALTERs hit tables that don't exist yet and get silently swallowed."""
    global _db_path
    _db_path = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.executescript("PRAGMA foreign_keys = ON; CREATE TABLE IF NOT EXISTS ...")
        for table, col, defval in [...]:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT DEFAULT {defval}")
            except Exception:
                logger.debug(...)

def _conn():
    return sqlite_connect(_db_path, "<module>.db")
```

- **New tables are STRICT** (`data/CLAUDE.md` warehouse contract) — the legacy loose-typed
  tables in trips/jobs/purchases/checklists are grandfathered, a brand-new table is not.
- `app.py` calls `<module>_db.init(<MODULE>_DB)` once at boot, before
  `app.register_blueprint`. `<MODULE>_DB` is a `Path` constant next to the others near the
  top of `app.py`.
- Generic sub-resource CRUD: don't hand-write `add_x`/`update_x`/`delete_x` per table.
  Write the three generics once (`_add(table, parent_id, data, allowed_fields)`,
  `_update(...)`, `_delete(...)`) and give each table its own `_FOO_FIELDS` allow-set —
  trips has eight of these, all four lines long. The allow-set is also the schema
  documentation: a field not in it is not writable from the API, full stop.
- Every read returns plain dicts via `row()`/`rows()`/`row_strict()`, never a raw
  `sqlite3.Row` — those three helpers in `sqlite_helpers.py` are the only place that
  matters.
- Use `sqlite_helpers.connect()` (commits on clean exit, rolls back on exception, reuses
  the thread-local connection for the life of the request) for everything. Never open a
  bare `sqlite3.connect()` in module code — that's what made the trips guest-codes
  endpoint spend 315ms of a 312ms request opening connections before the pin/scoping
  layer existed. See `sqlite_helpers.py` docstrings if the why matters.

## API layer (`api.py`)

```python
from flask import Blueprint, jsonify, render_template, request

bp = Blueprint("<module>", __name__, template_folder="frontend",
               static_folder="frontend/static", url_prefix="/<module>")

@bp.route("/")
def index():
    return render_template("<module>.html")

@bp.route("/api/<things>", methods=["GET"])
def api_list_things():
    return jsonify(db.list_things())

@bp.route("/api/<things>", methods=["POST"])
def api_create_thing():
    data = request.get_json(force=True, silent=True) or {}
    if not data.get("required_field"):
        return jsonify({"error": "required_field required"}), 400
    return jsonify(db.create_thing(data)), 201
```

- Every JSON error response is `{"error": "..."}"` with a real HTTP status (400 bad
  input, 404 missing, 409 conflict, 502/503 upstream unavailable). Never a 200 with an
  error string buried in the body.
- Conditional GET (304s) and gzip are handled once, app-wide, in `app.py`
  (`_conditional_json`, registered in a specific hook order). Do not add a per-module
  copy.
- If the page needs a guaranteed-fresh document (edits should show on a plain reload,
  not just a hard refresh), wrap the render in trips' `_no_store` pattern — set
  `Cache-Control: no-store, max-age=0, must-revalidate` on the HTML response only. Static
  JS/CSS stay normally cached and cache-busted by `?v=<mtime>` (handled app-wide, not
  per-module).
- Register in `app.py`, in the same place the others are, after `db.init()`:
  ```python
  from <module> import api as <module>_api
  from <module> import db as <module>_db
  ...
  <module>_db.init(<MODULE>_DB)
  app.register_blueprint(<module>_api.bp)
  ```
- Add the launcher tile in `hub_modules.py`'s `MODULES` list (name, one-line `desc`,
  `meta`, `href`, `tier`: `home` / `workspaces` / `utilities`, and a hand-drawn stroke-only
  SVG `icon` on the 1.2n+0.6 grid documented at the top of that file). This is the single
  list every launcher and page reads — there is nowhere else to register a tile.

## Frontend

- `<head>` mirrors an existing module's (trips or jobs): the no-flash inline theme-init
  script first (sets `data-theme`/`data-surface` before first paint, reading
  `localStorage["hub.theme"]`/`["hub.surface"]`), then `chrome.css`, `base.css`,
  `components.css`, the origin (for a database-backed page, `static/css/origins/tabbed-3-pane.css`),
  the theme CSS files, then the module's own stylesheet last. A module that renders a Leaflet
  map also links `static/css/map.css` after the theme files.
- **Universal chrome is never coded per page.** Ship `<header class="topbar">` holding only the
  page's crumb and extras, each tagged `data-slot` (`crumb`, `lead`, `left`, `right`); load
  `/hub-modules.js`, `theme-switch.js`, react + react-dom and `/jsx/static/js/topbar.jsx` (copy
  the script line from an existing module); register in `hub_modules.py`. The bar, island on
  scroll, back button, toggles, sign-out and launcher arrive on their own. Never restyle or exempt them in module
  CSS. The list and where each is built: `dashboard/hub/DESIGN.md` → "Always the same".
- **Token-only CSS.** Every color, radius, spacing value is `var(--*)` — never a literal
  hex or px value for anything DESIGN.md governs. See `dashboard/hub/DESIGN.md` for the
  full token table (`--bg`, `--fg`, `--accent`, `--warn`/`--alert`/`--good`, the `--s-*`
  spacing scale, `--r`/`--r-card`/`--r-pill`). This is what makes a module render
  correctly under vesper/cobalt/glass × dark/light with zero module-side theme code.
- **Any database-backed page is a derivative of the tabbed 3-pane origin**: a rail of tabs
  down the left (with an optional sub-tab list), a focus header (count tiles, search, sort,
  add) over a focus column of cards, a context rail of cards on the right, a status bar —
  never restyle these, compose them. Link `static/css/origins/tabbed-3-pane.css` right after
  `components.css`, paste the skeleton off the **layouts** tab of `/blueprints` with the
  origin's shell as a direct child of `<body>`, register the page in `blueprints.json`'s
  `derivatives` list, and write only page mods: trip/order/job facts, qualified by a module
  class or `body.<page>` so they never bare-restyle an origin class. Purchases' older
  `.pe-body`/`.pe-rail`/`.pe-split[data-split=...]`/`.pe-context` chassis is the pre-origin
  pattern, not the one to copy — it predates this build and hasn't been migrated yet. Full
  pattern: `wiki/patterns/dashboard-three-pane-layout.md`; the origin, its classes and the
  derivative contract: `CLAUDE-blueprints.md`.
- **Responsive is not a follow-up.** Every tab renders correctly headless at
  2560x1300, 1280x1300, and 390x844 before the module is done — zero clipped elements is
  the floor. `wiki/patterns/dashboard-responsive-layout.md` has the three binding rules
  (viewport-locked panels scroll, not clip; breakpoints fire where content stops
  *fitting*; components inside a column use `@container`, not viewport media queries).
- Before adding a new shared-looking component (a card header treatment, a button style,
  a modal), check `/blueprints` first. If nothing fits and the thing genuinely is shared
  across modules, it gets a blueprint entry in the same change — `CLAUDE-blueprints.md`'s
  suite fails a shared class with no blueprint.
- No third-party library from a CDN — vendor it under `hub/static/vendor/`, pinned by
  version (react/leaflet/maplibre/pdf.js already live there). `.jsx` needs no build step:
  it's transpiled server-side by `hub/jsx_build.py` and served at `/jsx/<path>`, cached on
  mtime. `<script>` tags for it carry `defer`.

## What NOT to copy from trips

Trips is the richest module in the Hub and most of that richness is trip-specific, not
part of the pattern: the guest-code passcode gate, the public mirror
(`trips/public_app.py`), the hallmark per-trip pages, the Google Forms preference sync,
the calendar reconcile daemon. A new module inherits the *shape* (blueprint + db.py +
three-pane frontend + token CSS) and none of that trip-only machinery. Start from the
CRUD skeleton above; add complexity only when the module's own requirements demand it.

## See also

- `wiki/notes/dashboard-code-structure.md` — full project layout and layer separation
- `wiki/notes/dashboard-code-quality-standards.md` — SQLite/Python hygiene, security
- `CLAUDE-blueprints.md` — shared UI component index (read first, always)
- `CLAUDE-trips.md` — trips-specific rules (duo planner files, activity field
  requirements) if the new module touches trips data
- `dashboard/hub/DESIGN.md` — the token system in full
