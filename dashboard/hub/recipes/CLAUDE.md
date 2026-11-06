# CLAUDE.md — recipes module

Hub module at `/recipes/`. Browse, search and cook the 123 five-star Paprika recipes in
the vault's `recipes/` folder. Built 2026-08-22.

- **Store: none.** `store.py` reads `<vault>/recipes/*.md` directly and caches the parse
  behind a 2-second TTL'd stat sweep (a full sweep of the folder measures **119.6 ms** on
  `/mnt/c` DrvFs — that number is why the cache exists and why it is not per-request
  statting). **Do not add a `data/recipes.db`.** The notes are the source of truth and
  Obsidian is the editor; a database would be a second copy that drifts. Revisit at
  ~2,000 recipes, not before.
- **Read-only over the notes.** Nothing here writes back to a `.md`. Cook-mode checkboxes
  live in `localStorage`; the grocery list lives in `checklists.db`.
- **Grocery list = one protected row in `checklists.db`, shared with `/checklists`.** Not a
  copy — a portal, so an edit on either surface is the same edit. `checklists_db.ensure_grocery_list()`
  is the only way in; it keys on `(category='grocery', protected=1)`, never on the name, so
  Sam can rename the list. Two triggers plus a partial unique index enforce it in the
  database rather than the API layer, because a trigger holds for scripts and future modules
  too. A trigger's `RAISE(ABORT)` arrives as `sqlite3.IntegrityError` (verified on
  Python 3.14.4 / SQLite 3.46.1 — it is NOT `OperationalError`; do not "fix" that back).
- **Card titles come from `dish-titles.json`, the note's `title` never changes.** The raw
  titles are Paprika/YouTube captures ("ABSOLUTE BEST CHICKEN CAPRESE SANDWICH",
  "🍣 Air Fryer Firecracker Salmon Bites ❤️"), so the grid had no parity. `store.py` adds a
  `dish` field, `_DISH.get(slug, title)`; the card shows `dish`, the detail page shows
  `dish` as the heading with the note's own title alive right underneath (`.rx-origtitle`)
  whenever the two differ. A missing key falls back to the raw title, so drift shows as a
  loud card rather than as wrong data. Kept as a code-side map, not a frontmatter key,
  because these notes are a Paprika export and a re-export would drop an added key. Loaded
  once at import — **restart :5002 after editing it** — and checked by
  `python3 -m recipes.dish_check`, which fails on a key whose note is gone and warns on a
  recipe still showing a loud title. Search matches both, so "Oyakodon" finds the note
  titled "Oyakadon".
- **`scale.py` is the part that can be wrong in a kitchen.** It parses a leading quantity off
  each `## Ingredients` bullet and scales it, snapping to a measurable fraction only while the
  distortion stays inside a 5% error budget — past that it renders a decimal, because 1/6
  snapped to 1/8 is 25% low. A line carrying a second quantity the scaler did not touch is
  flagged `unscaled` in the UI rather than silently half-scaled. 74 of the 123 notes have a
  parseable serving count; the other 49 get a plain multiplier (×0.5 … ×3), which needs no
  base. Every change here goes with `tests/test_recipes_scale.py`.
- **Wiring in `app.py`:** `from recipes import api as recipes_api`; `app.register_blueprint(recipes_api.bp)`.
  Tile in `hub_modules.py`. No `init()` — the vault path resolves directly.
- **Frontend:** vanilla, deferred, hub tokens only (no bespoke palette). `recipes.css` owns
  the page skeleton — `body` (font/bg/`overflow:hidden`) and `.shell` (the grid that gives
  `#recipes-root` a bounded row). `/static/css/base.css` deliberately carries **no `body`
  selector**, so a module without those two rules renders in the browser's default serif on
  white with an unbounded page; that is how this module shipped on 2026-08-22. It also carries
  `[hidden] { display: none !important }`, because `.rx-tray` / `.rx-grid` / `.rx-chips` each
  set `display` and an author `display` beats the UA `[hidden]` rule at any specificity —
  without it the empty selection tray sat on every index and the browse grid stayed under the
  pantry matcher. One card anatomy on both branches: the photo (or an empty tinted slot) on
  top, title and meta in `.rx-card-body`; never put the title in the thumb slot. `verify_frontend.py`
  is the module's render harness (its `SKELETON_PROBE` guards the two rules above): 8 real interactive states × 2560/1280/390, clip and porthole
  probes, screenshots to `Downloads/recipes-module-verify/`. Run it after any CSS or render
  change — a diff is not evidence. `/recipes/` is also in the shared first-paint guard,
  `dashboard/hub/tests/test_halfwidth_layout.py`.
- **Design + the per-claim adversarial verdicts:** `<vault>/docs/archive/specs/2026-08-22-recipes-hub-module-design.md`.
  Onboarding reversal: [[wiki/decisions/onboard-recipes]] (2026-08-22 amendment).
