# CLAUDE-data-sources — dashboard/hub/forge

Where the numbers come from, and what is derived. Split out of `CLAUDE.md` on
2026-08-29, which was 1,682 lines against the 250-line governance ceiling — past it
everything in the bottom half is underweighted at read time. Nothing was reworded.

## Two sources, side by side, never merged

coachless and lolalytics both sit on every rune row and inside every item panel,
in two fixed lanes. They are **not** each other's correction. They measure
different things and each one covers what the other cannot:

| | coachless | lolalytics |
|---|---|---|
| the number | **WPA** — the change in win probability from just before a pick to just after | raw **win rate** and **pick rate** |
| the patch | one behind the game, always (the live patch is paywalled, 403) | the live patch |
| coverage | only keystones enough games took, so most rows read as a dash | every rune in every tree |
| keyed by | the chosen **keystone** — a minor rune only means anything under one | **runes** by keystone, **items and boots** by the role overall |
| items | one figure per item, **and** one per build slot (`itemsBySlot`, added 2026-08-24) | one figure per build slot |

Runes were role-overall on the lolalytics side until 2026-08-22. The page takes a
`&keystone=<id>` filter and the readings move hard under it — Legend: Alacrity is
8.0% pick on Shyvana jungle under Press the Attack and 80.0% under Conqueror — so
`bake_lolalytics.py` re-scrapes the grid per keystone into
`roles.<role>.runesByKeystone.<id>`, and `lolaRune()` prefers that block. It is
**all-or-nothing**: with a block, a rune the keystone has no reading for holds a
dash rather than falling back to the role figure, because two populations in one
lane is the thing this exists to stop. The lane falls back wholesale only when the
bake has no block for that keystone, which is every keystone under
`KEYSTONE_PICK_FLOOR` (5% of the role's games — two extra page loads on Shyvana
jungle, not seventeen).

**The keystone row itself is the exception and stays role-overall.** A keystone's
line in the keystone-blind grid is already only the games that took it, so
filtering by it adds nothing — and under the filter the picked keystone reads 100%
while every other reads a dash, destroying the column of pick rates that row exists
to compare. `lolaRune(id, ks)` takes the slot for exactly this.

Colouring follows the same split: `lolaRuneBase()` is the keystone's own win rate
(Shyvana jungle is 53.3% overall and 53.6% under Conqueror, so a 53.4% minor is
above the role and below the keystone), while items, boots and the keystone row
keep `lolaBase()`. Items and boots are still role-overall readings; they were not
part of this pass.

One caveat lives on the page rather than only here, because it changes how the
numbers read: lolalytics' win rate is coloured against **the champion's own win
rate** for the population it was measured in, not against 50 — a 51% rune on a 53%
champion loses you games.

Item figures are keyed by build slot on purpose. Immortal Shieldbow is 51.9%
bought second and 54.5% bought third on Viego jungle, and that gap is the
interesting part; flattening it to one number throws away the reading.

**The per-slot lane on the item hovercard is coachless-first, lolalytics only
where coachless has nothing.** Both sources publish a per-slot reading now, and
they are no longer treated as two lanes side by side there — coachless
conditions on game state (WPA) and lolalytics does not, so a slot with a
coachless reading uses it and a bare win rate next to it was never diagnostic.
lolalytics fills only the slots coachless has no reading for. Each line is
labeled `· coachless` or `· lolalytics` so the source is never ambiguous. This
is the one place in the doctrine above where the two sources are *not* kept
apart — decided 2026-08-24 after Sam pushed back twice on keeping
lolalytics as a cross-check (see `bake_stats.py::items_by_slot` docstring for
the full rationale).

## Stats is his record, and it is never averaged into anyone else's

`/forge/stats` is the third top-level tab. The rest of the tool reads the
**population** — coachless WPA over millions of games, lolalytics win rates,
Riot's notes. This page reads **him**: 189 ranked games, a ten-champion pool,
the last twenty matches. The two are never combined into one figure and never
put in the same table, for the same reason coachless and lolalytics are kept
apart — a personal 56% over 100 games and a global 51% over four million are
different measurements of different things, and a number that silently blends
them answers neither question.

Two rules the page holds to because the sample is small:

- **The sample rides next to every figure.** The win-rate bar's *length* is the
  game count on a square-root scale against the biggest pile in the pool, and its
  *fill* is the percentage. So Ashe's 100% is a 10px stub and Viego's 56% is the
  full width. A bar that redrew the percentage would say nothing the number
  beside it does not, while making one game and a hundred look equally settled.
- **A 0-death game is two different things.** 16/0/4 is a perfect game and 0/0/0
  in seven minutes is a remake. `kdaText()` prints `∞` for the first and `–` for
  the second; printing one infinity for both is the wrong call twice.

**The pool table joins to this tool's own shelf.** A champion row links to
`c/<champ>/<lead role>` when the Forge has baked that champion, and carries a
small accent dot saying so; a champion he plays that the Forge has never baked is
still listed, because the record is the record, it just does not link anywhere.
That join is the whole reason Stats lives here rather than being a bookmark to
op.gg — "56% on Viego over 100 games" is one click from the sets that produced it.

### Where the numbers come from

OP.GG's own **MCP server**, open and unauthenticated, over plain HTTP JSON-RPC.
It was picked over the Riot API because it carries the derived layer (op_score,
tier context, LP history) Riot makes you compute yourself, and because Riot's
free personal key expires every 24 hours. Full rationale, and the three
third-party wrappers that were checked and rejected, in the vault at
`wiki/decisions/opgg-mcp-for-league-stats`.

Three things about that server are load-bearing, and all three are in
`opgg_me.py`:

| | what happens | what it costs |
|---|---|---|
| `desired_output_fields` | omit it and the server returns the response **schema** — `class Summoner: id,summoner_id,...` — with no values in it | naming fields is not an optimisation, it is the difference between data and a class diagram |
| the response shape | it answers in Python-class-shaped text, not JSON: `LolGetSummonerProfile(Data(Summoner("CanadianBacon",225,[...])))` | `decode()` walks it with `ast`, not a regex — the values are quoted strings holding commas and parentheses, and splitting on those is how you lose `Kai'Sa` |
| unmatched field names | dropped silently, and reported back under `_field_diagnostics` rather than raised | a typo'd field is a missing column on the page, never an error in the log |

There is no npm package. Neither `@opgg/opgg-mcp` nor `opgg-mcp` exists on the
registry despite what search results imply — the server is remote-hosted only.

**Every figure OP.GG sends for the champion pool is a season TOTAL**, not an
average: 989 kills on Viego, not 9.9. `_champ()` takes the averages once, on the
server, because a total read as an average is the kind of wrong that looks
entirely plausible on screen.

**Kill participation is a different kind of total.** `ranked_most_champions`
sends `basic.kill_participation` as each game's share (0 to 1) summed over the
season: Viego `64.28` over 140 games is 45.9%, and his archived Viego games
average 45.86%. Read as a percent it looks like a share of the season (the top
two champions sum near 100), which is wrong. `_kps()` divides by games. Only
that block carries it; `most_champions` does not, so `fetch()` asks for both and
joins by champion name.

### OP.GG returns 20 games, so history is kept locally

`lol_list_summoner_matches` caps at 20 and ignores offset, end date and queue
(probed 2026-11-10); `lp_histories` holds about four points. `_archive()` merges
each fresh read into the cached file by game id (fresh copy wins, newest first)
and LP points by time (oldest first), so **load more, queue tabs and the LP
graph read the archive**, and it only grows from the day it started.

### One game's full detail

`GET /forge/api/me/game?id=<game id>&at=<created_at>` calls
`lol_get_summoner_game_detail` through `opgg_me.detail()`: both teams in role
order, his side first, per player KDA, kill share, damage share, CS, gold,
wards, OP score and rank, items, spells, keystone. 400 without `id`, 502 on an
OP.GG error, cached in memory per game (a finished game never changes). OP.GG
sends `vision_score` null for every player, so screens show wards placed.

### The cache is on disk, and a stale answer says so

`data/forge-me.json`, 15-minute TTL, `?refresh=1` to force past it. On disk
rather than in memory so a Hub restart does not cost a round trip, and so the
last good read survives OP.GG being unreachable — a stale page carries an amber
banner naming its age, which beats an empty one, and only a cold cache plus a
dead server is an actual error (502). The numbers move a few times a day; the
page is opened far more often than a game finishes.

## Three readings are derived, at serve time, never at bake time

`notes_read.py` turns the baked notes into what the page renders. It runs inside
`GET /api/patchnotes`, **not** in the bake, so `data/forge-patch-notes.json` stays
byte-for-byte what Riot published and a presentation change is a server restart
rather than a re-fetch of a page that may have since moved. `enrich()` is
non-destructive: `context`, `from` and `to` are all still on every object, so when
a rule here is wrong the source is on the page to check it against.

| | what it does | why |
|---|---|---|
| `gist()` | Riot's paragraph with the blog voice cut | Every entry opens "We are continuing to…". **Deletion and aliasing only — it never rewrites a clause**, so it can read clipped but cannot state something Riot did not. A test asserts every word it emits appears in the source. |
| `compare()` | the `from`/`to` pair read **one level band at a time** | A bullet is rarely one change. `60 / 80 / 100 / 120 / 140 (+35 / 40 / 45 / 50 / 55% AP)` against its twin is five numbers of change wearing forty characters of identical tail; every number that moved becomes its own small `old → new` sitting in place inside the line, and everything that did not move is printed once, dimmed. |
| `change_verdict()` / `triage()` | buff / nerf / **mixed** per row, buff / nerf / rework per card | Direction becomes a colour and a badge instead of arithmetic you do in your head. |

Things the rules learned the hard way, all of them regression-tested in
`dashboard/hub/tests/test_forge_notes_read.py` against verbatim 26.16 strings:

- **The badge reads Riot's words before it reads the numbers.** Riot's markup
  carries no buff/nerf classification anywhere — checked, there is no class,
  attribute or icon for it — but the prose states intent, and stated intent beats
  inferred arithmetic. Only sentences carrying a first-person plan count: *"Gwen
  has remained slightly weak since her nerfs earlier this year"* is history, and
  counting its "nerfs" turned a straight buff into a rework.
- **An explicit "buffing"/"nerf" outranks a sideways verb.** Chainlaced Crushers
  shifts mage power *and* says nerf, and it is a nerf.
- **Every number carries its own direction. A row is not one verdict.** This
  replaced a "read the list by its total" rule that was wrong, and Sam sent
  the page back for it. `5 / 15 / 25%` → `6 / 13 / 20%` is rank 1 **up** and
  ranks 2–3 **down**, which is precisely what Bel'Veth's own paragraph describes:
  her early game protected, her late game cut. Summing the row printed a flat
  `NERF` over a deliberate trade and hid the half that matters. Same for Nasus,
  where `3, increased to 12 on champions` → `4, increased to 10 on champions` is
  a base-stack **buff** and a champion/large-monster **nerf** — two opposite facts
  that one arrow spanning the whole string mashed into an unreadable line. A row
  whose numbers disagree is `mixed`, and `mixed` feeds `rework` to the card badge.
- **The unit of comparison is a RUN, not a number.** A run is a maximal number
  list — `10 / 15 / 20 / 25` is one, and so is a lone `20`. Two values are
  compared run for run only when the literal text *between* the runs is identical
  on both sides (`_skeleton()`), because that is what makes "run *i* on the left
  is the same quantity as run *i* on the right" a fact rather than a guess. A
  generic diff looks tempting and is wrong: `18 / 14 / 10 / 6s` against
  `14 / 11 / 8s` has a `14` on both sides, and the diff aligns them happily and
  reports rank 2 unchanged when the whole curve went from four ranks to three.
  The one exception to the skeleton rule is a clause **bolted onto the end** with
  everything before it untouched (`20 / 25 / 30 / 35 / 40%` gaining `(+8% per
  1000 bonus Health)`) — the runs before it are still comparable, and the new
  clause renders as an addition.
- **A curve that changed its band count is still readable, and it is the read
  worth having.** Pairing at run level rather than number level is what makes
  that true, because a flat value and a per-level curve then occupy the same
  slot. Three ways two lists of different length are still the same quantity
  (`_run_segs`):
  - **one side is flat → broadcast it.** A flat value is a curve that does not
    move. Camille's shield `20% Maximum Health` → `10 / 15 / 20 / 25%` is weaker
    until 13, level at 13, stronger after — *"weaker shield early, but I have it
    more often"*, which is the sentence Sam opens the page for. The page used
    to print one grey blob over it.
  - **a band annotation says which levels → extend the shorter with its own last
    value.** Camille's passive cooldown dropped its level-19 band, so 19+ keeps
    the level-13 value: `6s` → `8s`, a **nerf** sitting inside a change whose
    other three bands are all buffs, and the half Riot's paragraph never
    mentions.
  - **neither → that ONE RUN greys out.** The bail-out is localised to the run,
    never to the row; one unreadable list must not grey out the numbers beside
    it. The whole-row bail survives only for the case where the text *between*
    the runs is what moved (`20 for 2s` → `[20 Melee || 10 Ranged] for 2s`), and
    it is the last resort rather than the first.
- **A `(levels …)` annotation is context, not a value and not an addition.** Its
  numbers are level indices — pairing them says nothing, and tinting them green
  says the levels themselves got better. It comes off both sides before anything
  is compared and goes back on as dim trailing text; the one kept is the one
  naming more bands, since the narrower curve's legend is a subset of it.
- **A range is one quantity, not two comparisons.** `10-25` → `12-40` split at the
  hyphen renders as `10→12-25→40`, which reads as neither. The two ends are
  rejoined into a single comparison when they agree on direction, and left apart
  when they genuinely disagree.
- **A leading dot is part of the number.** Riot writes sub-1 values with no
  leading zero, and a pattern starting at a digit reads `.658` as `658` and
  `.55` as `55`. Found on 26.17's Vayne card: `.658 + 3.3%/Level` rendered as
  `.658 -> 67`, the wrong magnitude, and one row up `3.5 + .55/Level` ->
  `4 + .5/Level` rendered `.55 -> 5` and tinted it a **buff** — a regen growth
  cut showing green, next to a real buff, so the row read as a straight buff.
  The lookbehind on the pattern is what keeps it from also splitting `3.3` into
  `3` and `.3`, or eating the period that ends a sentence after a digit.
- **Numbers are read as magnitudes, never signed.** `10-130` is a range, not a
  subtraction, and reading that hyphen as a minus flipped Fleet Footwork's healing
  buff into a nerf. Penalties are written negative (`-25%` → `-33%`) and get worse
  as they grow, so the sign carries nothing either way.
- **`LOWER_IS_BETTER` fields invert the reading** — cooldown, cost, recipe,
  consumption, penalty, recharge, cast/charge time. Everything else defaults to
  higher-is-better, which is what a stat line means: the notes are written from
  the champion's or the item's side.
- **No verdict is a real answer.** When the *shape* changed rather than the values
  (`20 for 2s` → `[20 Melee || 10 Ranged] for 2s`), no arithmetic on them means
  anything, so the run renders uncoloured — which reads as "look at this one
  yourself". A confidently wrong colour is the failure this module has a scar
  from; an uncoloured run is not. But *reaching* for it early is its own failure:
  giving up on every curve whose band count moved greyed out exactly the rows
  where "what got weaker and where" is both knowable and most worth knowing, and
  Sam sent the page back for that too.
- **A bracket can no longer be cut in half, by construction.** Only *numbers* are
  ever a side of a comparison; every bracket, unit and word around them stays in
  the unchanged text. `(+22.5%` cannot be a value any more, which is what used to
  render as `(+6.5%] → (+7%] AP)`. The old head/tail-balancing machinery that
  existed to patch that up is gone with it.

## Archetypes and traits

`data/forge-archetypes.json` holds every champion-role's archetypes off lolalytics
(keystone plus 2-item core, `path` = top three next steps of any length, `full` = the
most-played chain to five items, boots, runes, skills). `bake_lolalytics.py
--archetypes` stages `.next.json`; `bake_traits.py --archetypes` computes each
archetype's traits and publishes both live files together, only with failures at or
under 5%. `data/forge-traits.json` carries the calibration boundaries and
`rubricVersion: 2`. Trait rules and how a spell's lines are read: `CLAUDE-draft.md`.

Build styles per champion (`build_styles.py`, served as `styles` on `/api/landing` and
`/api/champion/<champ>`) are derived at serve time from `forge-lolalytics.json` item
tables and the catalog's item stats, cached on both files' mtimes; nothing is baked.
The item-to-style rule reads stats, plus three id sets the stats cannot tell apart
(`ON_HIT`, `BURN`, `BRUISER_NO_HP`). Rule and thresholds: `CLAUDE-landing.md`.

Counter tags live in `build_styles.COUNTERS`, a name table placed by reading each item's
stats and passive text (approved by Sam 2026-11-05); `bake_traits.py --items` writes
them onto `data/forge-item-traits.json` and fails when a name leaves the shop. Never tag
by keyword or popularity. `threats()` turns per-champion trait rows into a 0..1 threat per
tag (anti-vision reads `TRAPS` by name plus stealth, since the `vision` trait means
"grants vision" on 123 of 173 champions); `item_score()` adds resist stats against the
enemy damage mix. The Draft build reads `data/forge-sets.json` for counter swaps
(`CLAUDE-draft.md`).

`data/forge-mayhem.json` holds ARAM: Mayhem per champion: `build {games, starting,
items, augments{Silver,Gold,Prismatic}}` off metasrc's Mayhem page, written by
`python -m forge.bake_mayhem [--champ X]` (headless, about 15 s a champion; `failed` lists
the ones metasrc did not serve, and a rerun with `--champ` fills them). Rerun on a patch.

Item effects for that fight come from `bake_passives.py` into
`data/forge-item-passives.json`, block by block off the item bin. A passive that feeds no
number in a lone 10 s fight goes to `NOT_IN_FIGHT`, keyed by name, so a new Riot item
stays unknown until someone reads it. `handler: null` with a reason marks a passive that
changes fight damage in a way the model does not run (Opening Barrage, Juxtaposition,
Noxian Fervor): the archetype's damage rows read `unknown`.

## Champion page store

`data/forge-champions.json` holds one row per champion for `/forge/c/<champ>`,
written by `bake_champions.py` (`--champ <name>` repeatable, else all 173). Spec:
`docs/specs/2026-10-30-forge-champion-page-design.md` in the vault.

| Component | Source | Refresh key |
|---|---|---|
| `identity` | Data Dragon (lore, tips, icons) plus the wiki's `Module:ChampionData/data` row | dd version, Module revision |
| `stats` | the Module row beside the bin's own stats; `check` per stat | dd version, Module revision, `PARSER` |
| `abilities` | the wiki's rendered `Template:Data <Champ>/<Ability>` per form; `slots` names every form and any gap | page and form `lastrevid`, `PARSER` |
| `history` | `<Champ>/Patch history` wikitext, one verdict per line | page `lastrevid`, `PARSER` |
| `calc` | `kit()` per slot per rank, per archetype (`byArchetype["<role>/<id>"]`) | dd version, archetypes generation, stats and abilities keys |

- **Nothing is written by hand.** A field comes from a read source or reads missing.
  Each component carries `src` (source, url, version or `lastrevid`) and goes stale
  on its own: a failed read keeps the last good value marked stale; a first run with
  nothing read exits 1. `removed at source` is told apart from a failed request.
- **Verdicts are narrow on purpose.** Only a whole `<field> increased|reduced to <run>
  from <run>` line on the field allowlist gets `buff`, `nerf` or `mixed`, through
  `notes_read.change_verdict`; everything else is `null`, with `raw` kept on every
  line. Direction is arithmetic on the wiki's numbers, not Riot's intent. A unit word
  after the run (`10 seconds from`) leaves the line null under this rule.
- **The check compares only identified fields.** `verified`, `differs` or
  `not comparable` per stat and per form's cost, cooldown and range. No bind of the
  wiki form to a bin spell means not comparable; an equal number on an unidentified
  spell proves nothing. Cooldown compares the calculator's `cooldownTime`, so a
  stale bin mirror shows as `differs` until the engine reads `Cooldown.values`;
  cost reads `manaValues`. No `arType` or no `{726ee5cd}` means no bar (`[None, None]`).
- **Pacing.** One lock (`forge-champions.lock`), 30 s timeout, 3 retries,
  `Retry-After` honoured, a 429 stops wiki work for the run; unchanged `lastrevid`
  skips the render, so a second run is about 49 requests (revision batches plus the
  Module read). A full first run is about 1170 requests. Staged in
  `forge-champions.work.json`, published only with failures at or under 5%.
- **Attribution.** Wiki text is CC BY-SA 3.0; the page footer credits it and Riot's IP.
- **Page API.** `GET /forge/api/champion/<champ>` joins this row with archetypes,
  traits, roster and calc versions; judged rows never render as facts.

## Power spikes sheet

`bake_spikes.py` reads a community Google Sheet (tabs `Stats` and `Before You Read`,
public, fetched as CSV) into `data/forge-spikes.json`: per champion, item spikes, level
spikes and how to fight them, verbatim. Shown in "How to play" on the champion page and
under the identity quote in each draft seat (`_spikes()` in `api.py` picks the seat's
role row when the sheet has one; Kayn keeps Blue and Red).

- **The sheet predates the 2024 item rework.** A row naming a Mythic carries `oldItems`
  and the page says so; the text is never rewritten.
- **Names are matched to the catalog, and a miss refuses the write.** Cells read
  `Name | Nickname (Role)`; the Fizz row has its tip pasted over the name, so a name cell
  over 40 characters is cut to its first word. 164 of 173 champions on 2026-11-03.
- **The nine newest champions have Claude-written rows** in `data/forge-spikes-authored.json`
  (2026-11-04, from the wiki kit text, lolalytics cores and the sources on each row). The
  bake merges them marked `authored`, the page says who wrote them, and a sheet row for the
  same champion always wins. A champion added later gets a row there, not a hand edit of
  `forge-spikes.json`.
- **Riot's own data gives K'Sante Lee Sin's enemy tips** (`identity.enemyTips` in
  `forge-champions.json`); that is the source, not a bake bug.
- Re-run `python3 bake_spikes.py` if the sheet changes; `--check` validates without writing.
