# CLAUDE.md — artifacts module

Hub module at `/artifacts/`. Catalogs Sam's published claude.ai Artifacts,
grouped by category. Tier `utilities` (sits with vault-map, capabilities).

- **Store:** `data/artifacts.json` (vault), read via `vault_root()` in `api.py`.
  No database — the list is tiny and hand-maintained. Each entry:
  `{title, url, updated, category, description, favicon}`.
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
