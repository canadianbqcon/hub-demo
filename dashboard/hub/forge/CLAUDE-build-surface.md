# CLAUDE-build-surface — dashboard/hub/forge

The build surface and the shop read out of it. Split out of `CLAUDE.md` on
2026-08-29, which was 1,682 lines against the 250-line governance ceiling — past it
everything in the bottom half is underweighted at read time. Nothing was reworded.

## The build is centred on its first item, and the shop is read out of it

**Items are step one and the rune page is step two.** The order was the other way
round until 2026-08-19 — rune page, then items — on the theory that a build is
chosen rune-first. It is not: the build is centred on its first item, so the shop
is what the tool is opened to look at.

`data-step` on the two nav buttons **names its section** (`items` / `runes`)
rather than numbering it, and reordering means moving the two buttons. Do not try
to reorder by renaming `#step1` / `#step2`: those ids are section names, not
positions, and half the file keys off them — `hoverCards($('step1'))`, the
delegated click handler, the arming state, and the `#step1 { overflow-y: auto }`
/ `#step2 { display: grid }` layout split. Swapping the ids was tried first and
silently unbound the rune hover card and the rune click handler while every read
still passed; the suite caught it. `#step1` is the rune page, `#step2` is the
shop, forever.

**The reading is the Core block's first legendaries — one or two, whichever it
holds.** `coreSlot()` takes slots 0 and 1 of the block named Core (falling back to
the first block with items that is not the starting one, so a block called "Rush"
still works) and returns its block index alongside those ids, because the set marks
those slots. It comes off the BUILD, not off a control you have to remember to set:
a set that rushes a Collector into Lord Dominik's is read out of exactly that pair
the moment it is imported, and a set with one core item is read out of the one.

**Two is the ceiling, and coachless sets it, not the design.** `thirdLegendaryId`
is accepted with a 200 and then silently ignored — the rows come back identical to
the first-only call, measured on Viego jungle 16.15. So a three-deep condition does
not read thin, it reads *fine* and is wrong: a shop measured under two items with
the page claiming three, and nothing in the response to give it away. `coreSlot()`
slices to two and the legend names what it actually asked. A Core block can hold
six items; the axis reads the first two. A slot 1 repeating slot 0 is dropped —
`secondLegendaryId == firstLegendaryId` is the same condition asked twice, not a
build path.

**The pair is the one cross that survives.** Collector into Immortal Shieldbow on
Viego jungle 16.15 is 22 rows with 11 over the thousand-game floor and a 14,322-game
top line, against 29/16/39,947 for Collector alone — thinner, still a reading.
Contrast the keystone cross below, which is six rows and NONE over the floor. That
gap is the whole argument: depth is worth having exactly as long as the cell still
clears the floor every other figure on the page clears.

**There is no jungle-pet selector, and there was one.** Until 2026-08-19 the start
was a second conditioning axis — a chip row in the shop legend, `STARTER` /
`buildStart()` / `openingStart()` / `paintStarters()`, `starterId` on the wire and
an `itemsByStarter` block in the bake. All of it is gone. A jungle pet is an
**ordinary item** that carries its own figures (coachless `itemType` 6, in
`item_rows`), read out of the first legendary like every other item, which is what
a pet always was on the page: it sits in the shop's Jungle pets aisle and you drag
it into a block. Do not rebuild the chip row. If a pet shows no reading, the fault
is `ITEM_CLASSES`, not a missing control.

**That reading is live, not baked** — `GET /forge/api/conditioned?champ&role&first`,
which is `item_rows(..., first=)`, cached in-process per key. It cannot be baked:
`itemsByKeystone` works baked because a champion/role has a fixed handful of
keystones, but the first item is a property of the build being edited, so baking it
is every legendary per champion/role for cells nobody opens. One call per opener
actually built costs nothing.

**`firstPurchaseId` is not the parameter.** It is a different question — the very
first thing bought — and returns zero rows for a legendary. `firstLegendaryId` is
the one the Core block corresponds to.

**The keystone crosses in too, and this reverses an earlier rule.** The module
used to say "the keystone is never crossed into it" and the endpoint ignored one on
the query string. The number behind that rule was Press the Attack with a Collector
rush on Viego jungle 16.15 — six rows, none over the thousand-game floor — and it
was read as a property of the CROSS. It is a property of Press the Attack, which
alone tops out at 2,909 games on this champion, so anything crossed with it dies.
Measured across the champion's real keystones, against 29/16/39,947 for the rush
alone:

| keystone | alone | × Collector first |
|---|---|---|
| Hail of Blades | 38 / 21 / 117,104 | **27 / 14 / 30,470** |
| Conqueror | 40 / 23 / 137,163 | **23 / 12 / 9,044** |
| Press the Attack | 19 / 8 / 2,909 | 8 / 0 / 292 |
| Dark Harvest | 5 / 0 / 221 | 0 / 0 / 0 |

Hail of Blades keeps 14 of the 16 rated items. That is a better cell than Collector
→ Lord Dominik's (15/8/5,211), which was already being served as a supported pair.
Even all three at once holds: Hail of Blades + Collector + Lord Dominik's is
13/8/4,792. **No axis is refused for being "too narrow" — the floor decides that
per cell.** The old rule survives, but as a special case of the floor rather than a
rule of its own: a thin keystone still fails, one rung down.

**Leaving it out was doing active harm, not just leaving a reading unbuilt.**
Conditioned rows are keystone-blind and they WIN over the baked `itemsByKeystone`
in `coachItems()`. So setting a first item silently re-pooled exactly the split the
keystone breakout exists to make — the Umbral Glaive case below, +4.54 under Hail of
Blades and unplaced under Conqueror, went back to being averaged the moment a Core
item was dropped in.

**The walk is keystone+pair, keystone+opener, pair, opener, then the baked chain,
and the caller owns it.** `/api/conditioned` serves exactly the condition it was
handed and nothing more; `refreshConditioned()` in `forge.html` walks down that
list, stopping at the first cell that clears `MIN_GAMES`, before falling into
`itemsByKeystone` and then the aggregate. The second item is dropped before the
keystone because it narrows one slot of the build while the keystone reshapes the
whole list. Extra fetches happen only in the drop case, all cached in-process.
Putting the degrade in the endpoint was rejected: it would have to return which
depth it served, and the response is a bare array that `verify_frontend.py` and the
shop both read positionally.

Keystone-only is never asked for live — that is `roles.<role>.itemsByKeystone`,
baked and already on the page. `/api/conditioned` returns `[]` for a keystone with
no first item rather than serving a second answer to a settled question.

**A second slot holding boots or a pet lands in the drop path by itself.** It is
not a legendary, `secondLegendaryId` comes back empty, the pair fails the floor and
the opener is what gets served. No special case, and none should be added.

**The cross must clear the same MIN_GAMES floor as everything else, or it is not
the answer.** Conditioning on an item nobody rushes comes back with a single
106-game row; taken at face value that empties the shop to one dim tile and
captions it as measured. Below the floor the shop falls back down the baked chain
and the legend says which condition went unmet: `items read under Press the Attack
— too few games rush Immortal Shieldbow`.

**The set marks the slots the figures are read out of, in three states.** A 2px
ring plus a 3px halo on the Core block's slots 0 and 1, and one line under that
block's row (`.fnote`, and `data-first` on each slot): `read` when rows landed,
`thin` when the condition was asked and came back under the floor, `pending` while
the fetch is out. Three, not two, because a confident marker and a silent one are
both read as "measured" — and the LINE carries the state, never the ring's colour
alone, the same rule the patch badges follow.

**A dropped slot 1 is marked `thin`, never left unmarked.** One lit slot with a
bare one beside it reads as "both of these count", which is the exact claim the
second marker exists to deny. So `condState(id, pos)` returns `thin` for any slot
`COND.asked` does not name, and the note says which of the three happened: `stats
based on these as the first two items`, `stats based on this as first item — too
few games take that one second`, or `too few games rush this first item, so the
shop is not read out of it`.

`condState()` reads `COND.asked`, never the live Core block: a drop-in repaints
synchronously while the fetch is still out, so asking the build would announce a
drop that has not happened yet. `asked` stays null until an answer lands — that is
the `pending` state — and a repaint only ever fires once the whole walk has settled,
so no intermediate rung is ever painted. The marker is also gated on `current()` —
with no champion nothing is fetched, and a marker claiming a reading would be
describing a request that never goes out.

**The legend is written from what the rows were MEASURED under (`COND.asked`),
never from the live picks.** A chip click repaints synchronously while the fetch
is still in flight, so captioning from the picks names a condition the figures on
screen are not yet under. That shipped for one round and read as a flaky test
before it was recognised as the bug it was. Set `asked` with `rows`, read `asked`
with `rows`, and the two cannot drift.

**No article in front of an item name in that legend.** Half the items in the game
are called "The <something>", and an article gets you `a The Collector rush`.

`bake_stats.py` bakes items two ways — the unconditioned aggregate at
`roles.<role>.items` and `roles.<role>.itemsByKeystone.<id>` — and `coachItems()`
falls down that chain whenever the live reading has nothing: conditioned, then the
keystone, then the aggregate. The shop never goes blank and never waits on the
network to paint.

**The legend names the condition and stops** — `Viego jungle · 977,456 purchases ·
emerald+ · items read under Hail of Blades · The Collector into Lord Dominik's
Regards first two items`, dropping whichever clauses the walk dropped: `· The
Collector first item` when the build has one core item or the pair was dropped, and
`· too few games under Press the Attack` in place of the `read under` clause when a
keystone was picked and its cross missed the floor. That last one is not optional
politeness — silence there shows a keystone lit on step one with no mention of it in
the sentence, which reads as "of course these are read under it", the same failure
the dropped-first-item clause exists for. It is captioned off `COND.ks`, stashed at
walk start beside `rows: null`, never off the live `R.keystone`: a keystone click
calls `paintItems()` synchronously before `renderBlocks()` starts the walk. The keystone clause keeps the
`items read under X` phrasing the baked rung already uses, so the sentence reads the
same whether that half came off the live cross or off the bake. It used to spell out `items read out of X
first (not crossed with the keystone)`; the parenthetical went by request, and then
stopped being true when the keystone joined the walk. The sentence now names every
filter the rows survived and says which ones they did not. The swatch key beside it (`gains win probability` / `loses
it` / `edge length = share of these games`) went at the same time: every tile
already says that in colour and edge length.

**One hook drives the refetch: the end of `renderBlocks()`.** Every block
mutation, every keystone and champion/role change ends there, so hooking it once
beats hooking six call sites. It recurses exactly one level — the repaint
re-enters with the same key and `refreshConditioned()` returns false on a key it
already holds.

**There is no endpoint listing starting items.** That is why the retired starter
axis needed a hard-coded probe list of the ten the game offers, and part of why it
is not worth rebuilding: the shop's own Jungle pets / Starter items aisles already
know which openings a role has, from the item catalog rather than from a probe.
