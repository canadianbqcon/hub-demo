# gaming module

`/gaming/`: one brand band per game (League, CS2, Clash of Clans) over a list of that game's own Hub pages (modules and data displays), each with a live number where one exists. Shaped like `/work/`; picked on Workbench set `gaming-page-look`, option A. Research artifacts are deliberately not here; they live on `/artifacts/` (Sam, 2026-11-10).

- **Data:** `GET /gaming/api/summary` (`api.py`). Games and their modules are the `_GAMES` constant. Live numbers: League from `data/forge-stats.json`, `forge-sets.json`, `forge-patch-notes.json` (Riot's patch label, 26.x) and `forge-me.json` (`_solo_rank()`: his Solo / Duo rank for the band headline, falling back to the patch, and his season record on the Champion stats tile; the cache file only, never a call to OP.GG); CS2 from `ledger.value.book()` over `data/cs2.db`. Clash from `data/clash.db`, opened read-only by `_clash_stats()` (account with the latest `updated_at`; builder upgrades with `finishes_at` in the future, so the Tracker tile reads "N of M builders busy, next in ...", and the band headline is "Builders busy"); a missing db file blanks its numbers without creating one. A failing source blanks its numbers, never the page.
- **Adding a module:** add a row to the game's list in `_GAMES`, and a case in `_stat` if it has a number.
- **Page:** `frontend/gaming.html` (theme pinned to Liquid, frost, dark, like Forge), `static/gaming.jsx` (root), `static/gaming.css` (band and slab rules, per-game `--g*` tints, transparent shell so the Liquid wallpaper shows, phone rules at 640px).
- **Marks:** `static/lol.svg` and `static/cs2o.svg` are the unaltered Commons files from the Workbench set. Never redraw or edit their geometry; the lever is render size in `gaming.css`.
- **Clash mark:** the band uses the Town Hall icon served by the clash module (`/clash/static/icons/i-town-hall.png`), set in `MARKS` in `gaming.jsx`; five pages (`/clash/`, `profile`, `war`, `plan`, `layouts`) are linked whether or not built yet.
- **Tile:** `hub_modules.py` entry `gaming`, tier `life`.
- **Tests:** `python3 -m pytest gaming/test_gaming.py clash/test_clash.py -q`.
