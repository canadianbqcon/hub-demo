# CLAUDE-items-and-runes — dashboard/hub/forge

Items, keystones and the rune picker. Split out of `CLAUDE.md` on
2026-08-29, which was 1,682 lines against the 250-line governance ceiling — past it
everything in the bottom half is underweighted at read time. Nothing was reworded.

## An item says which keystone it wants

`keystoneSpread()` is `itemsByKeystone` pivoted: instead of "under Conqueror, what
is good", it answers "this item, which keystone does it want". Nothing extra is
fetched. The card carries **one** line, the best qualifying reading and the sample
under it: Infinity Edge on Viego jungle reads `wants +0.85 under Hail of Blades ·
49k games` while the coachless line directly above it says -1.97, because Conqueror
is what the page currently has picked.

**A row only qualifies if it gained win probability over at least `MIN_GAMES`
games** — the same two conditions that make a figure render solid rather than dim,
so the rule is the one already visible in the shop: a reading you would not trust
there does not get to name a keystone here. Without the sample floor one player
going 1-0 out of Hail of Blades makes an item "want" Hail of Blades. The floor
takes the pool from 167 items carrying a line to 74, and every survivor sits on
thousands of games.

The worst reading was shown beside the best at first and was cut: an item's least
favourite keystone is not something you act on, and pairing them turned one usable
line into two you had to read past. `verify_frontend.py` checks both directions —
a qualifying item names its keystone and prints only one `under`, and an item whose
only positive reading is thin names none.

## Item figures are read under the keystone

`bake_stats.py` bakes items twice: the keystone-blind aggregate at
`roles.<role>.items`, and `roles.<role>.itemsByKeystone.<id>` for every keystone
clearing the same `MIN_OCCURRENCE` gate the rune breakdown uses. coachless takes a
`keystone` filter on `GetGlobalItemStatistics` and its own site sends it; passing
null flattens the readings into an average of build paths that do not resemble each
other. Viego jungle on 16.15 is the case: Umbral Glaive reads **+4.54 under Hail of
Blades and does not place at all under Conqueror**, whose best legendary is Kraken
Slayer at +0.17 over 137k games. The aggregate says Umbral Glaive +2.23 and describes
neither build.

This is the same reasoning `runes_for` had applied to runes since the module shipped
— a minor rune only means anything under the keystone above it — finally carried
across to the other half of the build.

`coachItems()` in `forge.html` prefers the conditioned rows and **falls back to the
aggregate** when the keystone was too thin to break out, rather than emptying the
shop: a rare keystone has no rows of its own and the aggregate is the honest reading
left. The shop legend says which of the two you are looking at, and says
`items read under <keystone>` rather than `under <keystone>` — the purchase count
beside it is the role's, not the keystone's, and a shorter phrase runs the two
together into a claim the data does not make. The keystone's own sample stays on
each tile, next to the figure it belongs to.

**A keystone click has to repaint step two.** That handler ends in `renderRunes()`,
which paints step one only; without the `if (slot === 'ks')` line after it the
conditioned data sits in the bake and the shop keeps showing the average. Guarded on
the keystone branch on purpose — a minor rune changes nothing about the items, and
repainting the shelf on every rune click is a full re-render per click.
`verify_frontend.py` asserts the shop's figures actually move across a keystone
switch and that the legend names it.

`starterId`, `firstPurchaseId`, `firstLegendaryId` and `secondLegendaryId` are the
same shape of filter on the same endpoint and are deliberately **not** baked. The
keystone is the one that reshapes the whole item list rather than one slot of it;
the others multiply the bake by their own cardinality for a narrower reading, and
`firstLegendaryId` × `secondLegendaryId` multiplies it twice over. Both of those
are served live instead (see above); `firstPurchaseId` and `starterId` are sent as
null forever, and `items_for` hard-codes them rather than taking them as arguments.

## The item step: click reads, drag moves, x removes

Three gestures, each doing exactly one thing, in the shop and in the set alike:

- **Click** anything — a shop tile, a slot in a block, a node in a build path —
  and it opens in the inspector. It never changes the set. Clicking a slot used
  to take the item back out, which meant looking at what you had built spent it
  one click at a time.
- **Drag** is the only thing that moves an item. From the shop or from a build
  path into a block adds (Shift adds five); from a slot into any block reorders
  or moves between blocks. The payload says which: `move:<bi>:<ii>` is a slot
  leaving its block, anything else is a bare item id. A drop lands **in front of**
  the slot under the pointer, or on the end when it lands in empty block space.
- **The x** on a slot, hidden until you hover it, is the only way an item leaves.
- **The `\u2261`** in the slot's other corner opens its note. It is the one
  affordance that stays lit once used, because the point of a note is that you can
  see which items have one before you go looking. See the qualitative layer below.

The inspector is docked **above the set**, not above the shop. It opens and
closes on every click, and over the shop that threw a thousand tiles up and down
the moment you read a second item. Its **Add to &lt;block&gt;** button is what makes
that dock survivable: the expanded panel is tall enough to push the set below the
fold, so adding cannot depend on the set being on screen.

The shop sells **the role its own opening items**. A jungler starts on a pet, a
support starts on World Atlas, a laner starts on a Doran's or a Dark Seal, and
none of the three is a choice the other two have - so the two aisles that are not
yours are hidden rather than scrolled past on every build. `ROLE_SUBS` binds
exactly three sub-shelves (`Support items` -> support, `Jungle pets` -> jungle,
`Starter items` -> top/mid/bot); everything else is bought by everyone. With **no
role picked** nothing is hidden, because there is no role for anything to be
relevant to. The Utility shelf head names the aisles the role took away - a
hidden aisle is never hidden silently. Filtering is display-only: switching role
never touches items already in a block.

**Hovering anything shows a real card, never a `title` attribute.** One
`.hovercard` element serves the whole page: `itemCardHTML()` for shop tiles, set
slots and build-path nodes, `runeCardHTML()` for the picker, wired by
`hoverCards(host, find)`. An item card **leads with its stats** - glyph, number,
label, the same `statsDL()` the inspector uses - then the passive, then both
sources.

This binds the saved-build overlay too, not just the builder — its item slots
carried a `title` until the notes landed, which is why a note had nowhere to go.

The `title` attribute is not a visible change and must not be used for this. It
is browser chrome: about a second of hover before it appears, unstyleable, and on
a grid of 48px shop tiles nobody ever waited for it. The first attempt at "show
me the stats on the items" put them in a `title` and the check read the attribute
back, which proved a string existed in the DOM and nothing about what was on
screen. **Verify a hover by asserting the card is visible and reading the text
rendered inside it** - `verify_frontend.py` does exactly that.

There is no block gold total. What a block costs is not a number anyone builds
against, and the line moved everything under it every time an item landed.

## The source bar carries the same six columns as a rune row

`.srcbar` and `.rpick` share `28px minmax(0,1fr) 42px 34px 44px 36px`, so every
label sits over the figure it names: the source spans its pair on the top line,
the unit sits on the line under it. It used to run four columns
(`28px 1fr 76px 80px`) against the row's six, which put "wpa · n" over the seam
between two different numbers.

Two details that are load-bearing:

- **Everything is right-aligned**, headers and figures alike (`.rpick .wpa` too,
  which was not). A column of numbers lines up on its right edge or it does not
  line up at all, and the dash for a missing reading has to land in the same place
  as the figure it stands in for.
- **`.srcbar` gets `padding: 0 9px 4px` against `.rpick`'s `4px 8px`.** A `.rpick`
  is a `<button>` and carries a 1px border; the header does not. Without the extra
  pixel every column sits 2px wide of the numbers under it.

`.rpick.key` differs only in its first track (92px against 28px), so its remaining
four columns keep the same right edges and one header serves both.

## The rune picker is built once and painted after

`buildRunes()` lays out **all five trees** in both columns and hides four of them;
every click after that only sets attributes and text. Nothing under `#step1` is
ever destroyed by a pick.

This is the correction to what the page shipped with, where each of `renderPrimary`,
`renderSecondary` and `renderShards` reassigned its column's `innerHTML` on every
click. Sixty buttons and their icons were thrown away to change four numbers, and
three things broke with them: the focus ring left the button you had just pressed
(`document.activeElement` went to `<body>`), the hover card was left pointing at a
node that no longer existed, and no state change could transition because the
element a transition would run on was gone. Measured: 25 clicks destroyed 0
elements after, everything before.

The split is by what each thing is a function of. **Structure** is a function of
the rune tree, which never changes inside a session, so it is built once:

| | |
|---|---|
| `buildRunes()` | all five tree panels per column, the tree pickers, the shard rows. Called once at boot, before the first paint. |
| `renderRunes()` | which tree panel is visible, `aria-pressed` on every button, both figure lanes, the status line. Called by every click and by `renderMeta()`. |
| `paintRuneBtn(btn)` | one button: routes off `data-slot` to its pick and its two readings. The shard test comes before `slot[0] === 's'`, same order as the click handler. |

`runeBtnHTML()` emits **empty** lanes on purpose. Both sources move when the
keystone moves, so baking either into the markup would put the figure in two
places and drift one. Every figure on the page comes from `paintRuneBtn`.

Hiding the four unpicked trees rather than deleting them is what makes a tree
switch free: their icons are already fetched and decoded. `.treebody` and `.srcbar`
both set their own `display`, so both need an explicit `[hidden] { display: none }`
rule — the UA's `[hidden]` loses to any author `display`.

`setText()` guards every text write, because assigning `textContent` swaps the text
node whether or not the string changed, and `renderRunes()` touches 69 buttons.

`aria-live="polite"` sits on `#metaSub`, the status line, **not** on `#step1`. On
the section it made every repaint announce the whole picker.
