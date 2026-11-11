# CLAUDE-landing — dashboard/hub/forge

The champion landing page and what a card carries. Split out of `CLAUDE.md` on
2026-08-29, which was 1,682 lines against the 250-line governance ceiling — past it
everything in the bottom half is underweighted at read time. Nothing was reworded.

## The landing card is a build shelf, not a statistics readout

A card carries the champion's portrait, a row of role chips, and **the sets saved
under the chip you are on**. It carries no WPA, no win rate, no game counts and
no patch notes. Those all still exist; they are one click in, on the page where
you are actually choosing something. A figure on the front door has nothing to
choose between, so it reads as a recommendation the tool never meant to make.

**The chips cycle the shelf in place, they do not navigate.** Clicking `mid`
repaints that card's list and re-aims its two footer links; it does not leave the
page. The count on a chip is **builds, not games**. The chip list is every role
the champion is played in UNION every role a saved set sits in, so a role you
have built in always has a chip even if coachless never measured it. A card opens
on the role you have most built in, falling back to the played-most role when the
shelf is empty — the shelf you reach for is your own.

**Pool membership is per lane** (mark 2026-11-10-042636 #2). `data/forge-pool-roles.json`
holds `{champion: [lanes]}`, written by `POST api/pool-roles {champion, role, on}`; a
champion with no entry is in the lanes he has his own non-Auto builds in, else its lead
role (`_pool_roles()` in `api.py`, sent as `poolRoles` on each `/api/landing` card). It
is separate from `bake_stats` `POOL`, which decides what gets baked; adding a champion
that is not in `POOL` is not done here. The pool shows one card per (champion, lane); the
shelf heading carries the `In <lane> pool` / `Add to <lane> pool` toggle.

**Auto folds behind your own builds** (mark 2026-11-10-042636 #4): when a role has his
own sets, its Auto sets sit behind a `.fold` header button (`AUTO <lane> N ▸`), shut by
default. `.fold.fold:hover` doubles the class to beat `forge-base.css`
`button:hover:not(:disabled)`, which otherwise paints a fill on the header.

**Card size** (mark 2026-11-10-042636 #3, "these are too big"): `minmax(290px)` columns,
three across at 1280, 14/16 padding, 48px portrait, small role chips. The rule lives in
`landing.html`'s later "shell's panel shape" block, which beats the earlier `.cards` rule.

Each row links to `c/<champ>/<role>#<set-id>`, and `champion.html` opens that
set's overlay on load. Closing the overlay drops the hash, so a reload lands on
the list rather than reopening what you just closed.

**Opening a champion lands on their builds, not on the builder.** The sets already
made are what you want first; a new one is one click away. The list groups by the
patch a set was saved on, newest first, and the current patch always gets a section
even when it is empty ("No sets yet on patch 16.16") — a build ages along exactly
one axis, which is the patch that changed the items under it. Clicking a set opens
an overlay with its rune page and its item blocks, plus **Copy to patch &lt;live&gt;**,
Edit, Copy JSON and Delete. The copy forward is just a save under the live patch;
the library's own `(name, patch)` versioning does the forking.

**The builder is two steps in the order the build happens.** Step one is the rune
page, step two is the items, and step one saves — a set with `runes` and zero
blocks is a real state the pipeline produces on every build, not a malformed one.
Step two saves the items onto that same `(name, patch)` row.

**Past that first save, the set keeps itself current.** Every edit — an item into a
block, a keystone swapped, a shard, the title — writes itself back to the same
`(name, patch)` row about a second later, and the Save button flashes `Saved` so a
silent write is still an observable one. The autosave rides `persist()` for the
item half and `renderRunes()` for the rune half (rune state lives in `R`, which
`persist()` never touched), rather than being wired onto each handler.

Two conditions gate it, both deliberate: the set must already have a **name** and
already own a **row**. Before that a save would have to prompt for a title, and a
prompt on a timer is worse than no autosave — so the first save stays the manual
one. An autosave also never takes a row it does not own: a name clash with someone
else's earlier save is skipped silently instead of raising the replace prompt on a
timer. Failures are silent by design; the manual Save still reports.

The champion and role live in the URL, not in a dropdown: the page is linkable and
bookmarkable, and it paints with the statistics already on screen. Changing either
dropdown rewrites the address bar (`history.replaceState`), so a copied link always
reopens what was on screen. `/forge/edit` is the same builder with no champion, for
a set that is not about one.

This is the correction to the state the module shipped in first, where `/forge/`
served the editor with both selects empty — so the whole statistics half, the thing
the tool exists for, was invisible until you worked two dropdowns.

## Boots and jungle pets are separate item classes, not slots

`GetGlobalItemStatistics` splits its catalog by `itemType`, and the bake asks for
three of them — `ITEM_CLASSES = (1, 2, 6)`: **1 is the legendaries, 2 is the boots,
6 is the jungle pets** (exactly {1101, 1102, 1103}, measured by probing types 0-8).
Asking only for 1 — which is what shipped first — returns a build with no boots in
it anywhere, on every champion, which reads as a display bug and is not one. Types
0, 3, 4, 5, 7 and 8 answer with nothing worth baking.

The extra classes are appended **after** `played` is summed, so `MIN_OCCURRENCE`
still measures legendary purchases only and the set of roles that clear the gate is
unchanged by boots or pets existing. Moving that line above the sum would quietly
re-open roles the threshold was built to keep out.

**Every conditioned read has to ask for all three too, and for a while only the
overview did.** The conditioned reads each called `items_for` once and took the
`item_type=1` default, so every keystone list was baked with zero boots in it. That
is not a cosmetic gap: the shop hides anything without a reading when "Only items
with a reading" is on, that toggle turns itself on the moment a reading exists, and
the Boots shelf is **not** in the Utility exemption — so picking a keystone emptied
the entire shelf. Shyvana jungle read 0 boots under Conqueror and 0 under Dark
Harvest; the same calls through the fix return 5 and 6.

`item_rows()` is the single place that knows about the classes now. `items_by_keystone`
and the live `/api/conditioned` endpoint both go through it. `main()` deliberately
keeps its own calls, because of the `played`-sum ordering above. **A new conditioned
read calls `item_rows`, never `items_for` directly** — a bare `items_for` is the
shape of this bug.

Class 6 is what makes a jungle pet an ordinary item with its own figures rather
than a filter you pick (see the first-item section below). Dropping it from
`ITEM_CLASSES` silently returns three of a jungler's items to unrated, on a page
whose entire subject is what an item is worth; `bake_stats.py --demo` asserts the
tuple, and `verify_frontend.py` asserts the three pets carry figures on screen.

## Runes are authored and displayed, never exported

The League client has **no rune import**. Sam reads the rune page off the saved
build and types it into the client by hand. So: no rune JSON, no LCU push, no
"send runes to the client" path — do not build one. Item-set JSON export is
unchanged and is the only export the tool has.

The step-one picker is an **authoring** control with the WPA figures on the runes
themselves, not a picker beside a read-only stats panel: you are choosing while you
read, and splitting the two would mean holding a figure in your head to cross a gap.

## Every champion below the pool cards

Under the pool's build shelves, `Every champion` lists each catalog champion not in
the pool (161 on 16.21) as a tile: portrait, name and one chip per role it is played
in at 5%+ of its games (the matchups store's `roleShares`, read through `_role_shares()`
on its own mtime cache), each a link to `/forge/c/<champ>/<role>`, the champion page.
A search box filters by name. Added 2026-11-04 on his ask: the champion pages existed
for all 173 but the front door only reached the pool.

Tile portraits are `loading="lazy"`: eager, the ~160 of them (~5 MB from Data Dragon)
held the page's load event to 2.3 s cold and 220 requests; lazy, 0.84 s and 61
(2026-11-10). Pool card portraits stay eager, they are above the fold.

## Build style chips

Every roster tile and the champion page header carry a second chip row under the
roles (not the pool cards: mark 2026-11-10-042636 #5, "hide from top card view"): the build styles the champion is actually built in (crit,
lethality, on-hit, bruiser, tank, burst AP, burn AP, AP bruiser, enchanter). They are
labels, not links. `build_styles.py` scores each style as the expected number of its
items among the first three completed items, in the champion's best role for it, off
the lolalytics item tables: bold `main` at 1.0 or more, plain `common` at 0.15 or more.
**The chips list what is possible, not only what is popular** (Sam, 2026-11-05):
under 0.15 a style still shows as a dashed `niche` chip when its items were bought
early in 40 games or more, counting ranked roles plus the ARAM archetype chains, so
Irelia burst AP (308 games) and Miss Fortune burn AP (47) both appear. The item tables,
not the ranked archetype list, because that list keeps only each role's top builds.
