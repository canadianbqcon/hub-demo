# CLAUDE.md — artifacts module

Hub module at `/artifacts/`. Catalogs Sam's published claude.ai Artifacts,
grouped by category. Tier `utilities` (sits with vault-map, capabilities).

- **Store:** `data/artifacts.json` (vault), read via `vault_root()` in `api.py`.
  No database — the list is tiny and hand-maintained. Each entry:
  `{title, url, updated, category, description, favicon}`.
  Optional `icon` (since 2026-11-10) replaces the emoji `favicon` on the card:
  `brand/<name>` is a vendor's mark from its source file (Commons first, per the
  brand-marks rule), shown in its own colours on a white tile; `mono/<name>` is a
  Lucide (ISC) topic icon drawn white on a colour tile (colour hashed from the
  icon name in `RowIcon`). Every icon is the same 28px rounded tile, centred on
  the title's first line (mark 2026-11-09-231213 #1 send-back). Files live in
  `frontend/static/icons/{brand,mono}/<name>.svg`. Every Research row has one;
  a new artifact arrives with only the emoji until someone picks its icon.
- **Refresh:** automatic since 2026-08-10. The vault hook
  `.claude/hooks/vault-artifact-register.py` (PostToolUse:Artifact) upserts an
  entry on every publish, keyed by URL. Sam's rule is that **every** artifact
  lands here whatever kind it is, so a new one Claude did not categorise arrives
  as `Unsorted` rather than not arriving — recategorise it afterwards. A
  republish only bumps `updated` and refreshes supplied fields, so hand-written
  categories and descriptions survive redeploys. Hand-editing the JSON still
  works and needs no restart. Reconcile against `Artifact action:list` if the
  file is ever suspected stale.
- **Pattern:** mirrors the `capabilities` module (vanilla-JS utility, own
  topbar, JSON `/api/data` fetch). No React, no SQLite — both settled.
- **Wiring in `app.py`:** `from artifacts import api as artifacts_api`;
  `app.register_blueprint(artifacts_api.bp)`. No `init()` — vault path is
  resolved directly (purchases pattern). Tile in `hub_modules.py`.
- **Design:** inherits the Hub token system (base.css + liquid/cobalt/vesper themes, liquid the default),
  no bespoke palette. Onboarded via [[wiki/decisions/onboard-artifacts]].
