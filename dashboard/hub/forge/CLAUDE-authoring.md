# CLAUDE-authoring — dashboard/hub/forge

Authoring a set: blocks, alternatives, notes, versions. Split out of `CLAUDE.md` on
2026-08-29, which was 1,682 lines against the 250-line governance ceiling — past it
everything in the bottom half is underweighted at read time. Nothing was reworded.

## The qualitative layer: alternatives and notes

A build is a pick per slot and a list of item ids. That is what to do and none of
why, which is the half that decides whether the build survives contact with a
game that does not look like the average one. So a saved build also carries the
picks you did **not** take and the sentence saying when you would.

Two shapes, one list, on `runes.alts`:

| | |
|---|---|
| `{ slot, id, note }` | one minor rune or one shard swapped |
| `{ slot: 'secondary', tree, sec: [id, id], note }` | the whole second tree swapped |

`slot` is verbatim the rune picker's own `data-slot` (`p2`, `s1`, `shard:flex`,
`secondary`). Reading an alternative back to the pick it stands in for is
therefore the same routing table the click handler uses, and it lives in
`static/itemset.js` as `altSlotLabel()` / `altReplaces()` — shared, because the
builder and the saved-build overlay both do that read and a routing table typed
in two files is one that drifts. The name lookup deliberately stays local to each
surface: the rune index is a different object on each.

**The digit in a slot is a ROW, not a position in the list.** `p2` is primary row
two, and so is `s2` — secondary row two — even though `runes.sec` is a flat pair
rather than one entry per row. So an alternative for a secondary rune is named by
the row that rune sits in: with `sec: [Triumph, Coup de Grace]` the Cut Down swap is
`s3`, because Coup de Grace is row three. `s2` there names an empty row, `altReplaces()`
returns null, and the panel prints the alternative with no "instead of" line and no
error. Hand-authoring a set through the API is the only way to reach that state; the
picker cannot produce it.

**The keystone and the primary tree have no alternative, on purpose.** Every
figure on the rune page is read *under* the keystone, and a different one usually
wants different items beneath it — that is a different build, and the library
already versions those by `(name, patch)`. Everything below the keystone is a
swap you make inside one build, which is exactly what this list holds. Both
refusals print the reason into the panel rather than silently doing nothing.

**Authoring is a mode, not a hidden modifier.** `Add alternative` arms; the next
click on a rune, a shard, or a tree in the Secondary column records instead of
picks, then disarms. Clicking the second tree you already have picked brings its
two runes along with it, which is how you bank a tree you just finished building
before switching back. A shift-click or a right-click would have been fewer lines
and undiscoverable; the armed state is on the button, in the cursor, on the
dimmed half of the page, and in a sentence in the panel.

**A cancelled note cancels the whole alternative.** The swap without the reason is
the half this feature exists to add.

Items carry the same thing at slot level: `note` on an entry inside a block, edited
from the `\u2261` beside the slot's `x` and rendered **first** on the hover card,
above the stats. Every other line on that card is a measurement over a lot of
games; the note is the only one that knows why the item is in *this* build. A
slot with one stays marked when not hovered, on both the builder and the overlay
— the marker only says there are words here, the card carries them.

### How a note is written

Every note answers the dialog's own question and nothing else: **when would you
take this, and why.** It never describes the item. The card prints that item's
stats, its passive and both sources directly underneath the note, so a note that
explains what the thing does is the one line on the card saying nothing the card
did not already know.

The shape, read off the notes already in the library:

```
Take this <trigger>[, or <trigger>][ to <payoff>].
```

`Take this` is a fixed stem, not a suggestion. Four trigger shapes cover
everything a slot has to say, and they compose:

| shape | connectives | example |
|---|---|---|
| sequence | `after`, `when building` | Take this **after** Kraken Slayer **to** multiply its On-Hit effects. |
| matchup | `against`, `vs.` | Take this **against** heavy AD comps, or to counter burst damage. |
| role in the build | `as a <role> option` | Take this **as** a stat checking option **vs.** low damage comps. |
| exclusion | `when you aren't looking for` | Take this as the standard damage option **when you aren't looking for** tank or sustain. |

Rules that hold across all four:

- **One sentence, two at the outside.** It renders at `--t-xs` inside a hover
  card that is capped to the width of the columns above it. A paragraph there is
  a paragraph nobody reads with a pointer held still.
- **Sentence case, terminal period, one grammatical subject.** The stem carries
  the subject, so a clause that silently switches to an elided *you* breaks the
  sentence in half.
- **Name the other item, never the stat it gives.** `after Kraken Slayer` is a
  trigger you can act on mid-game; `after an attack speed item` is a category you
  then have to resolve yourself.
- **A note goes on a decision, never on a default.** The marker beside a slot
  stays lit once there is a note on it, and it exists so you can see which items
  have something to say before you go hovering. Light it on the Health Potion
  every build starts with and it stops meaning anything on the items where the
  choice was real. Consumables, the trinket and the ward are defaults; a pet, a
  fork in the core, and every optional slot are decisions.

**A note belongs to the item, and changes only when the champion or the build
changes the answer.** Randuin's Omen says *Take this vs. high crit damage.* in
every set that carries it, byte for byte, because the reason to buy it does not
depend on who is buying. Reword that per build and reading two builds side by
side turns into reading two ways of saying one thing. So: look for the item in
another set and copy what is there.

The exception is real, though, and it is the whole reason this is a default and
not a lock — when the kit or the build genuinely changes *when* you take the
item, the note changes with it. Guardian Angel is *when you need to kamikaze a
single fed enemy* on Shyvana and *last at full crit with a slot to spare* on
Viego, because those are two different buys. Core notes are always fresh, since
they are about this build's sequence.

**A guide that disagrees gets a second sentence, not a rewrite** (ruled
2026-11-03). The shared note stays byte for byte and the build appends one line
naming the guide and its call: Mosstomper on every Viego set ends *Mino's Viego
guide rates this the only real Smite option.* A shared note that every set
carries still has to say why the pick is good, so the three jungle pets each take
a `to <payoff>` clause (*…to walk into every fight behind a full shield.*).

**Name the trigger and stop.** *Take this vs. 3+ HP stackers.* — not "…when your
damage has to be percentage-based". The reason you would want percentage damage
is not something the note has to teach. A second condition joins with `and`
(*…and have big AP threat on your team*, *…and can use the armor*), never with a
because-clause.

Rune and shard alternatives on `runes.alts` take the same sentence. The trigger
there is usually a matchup, because that is what a swap inside one page answers.

None of it reaches the client. `itemSetJSON()` maps an item to `{id, count}` and
always did, so the export is unchanged; `tests/test_forge_api.py` pins that the
whole layer survives a save and a copy-forward, since the endpoint passes `runes`
and `blocks` through opaquely and the thing that would break it is a future
endpoint that rebuilds them field by field.

**The note editor is a `<dialog>` with a textarea, not a `prompt()`.** The rest of
this file uses `prompt()` for one-word answers like a set name. A note is a
sentence or two you write once and read for a season, and a prompt gives you one
line you cannot read back.

## Every build starts on the same ten blocks

`DEFAULT_BLOCKS` in `forge.html` is the skeleton a new set opens with, and it is
the PTA Shyvana jungle set's shape promoted to the default: **Starting Items,
Utility, Boots, Components, Core, Post-Core, Niche, Armor, Magic Resist,
Capstone.** Every saved set in the library is on it.

It is one skeleton for every champion on purpose. A block named before it is
filled is a prompt — an empty **Magic Resist** shelf is the tool asking what you
buy into an AP comp, which a build authored block-by-block never gets around to
answering. Armour and magic resist stay apart for the same reason: the defensive
answer is one shelf you read, not a scan through a mixed pile mid-game.

Empty blocks cost nothing (`itemSetJSON()` drops any block with no items, so the
export is unaffected), so a build that needs fewer deletes the ones it does not
use rather than the default shrinking to the smallest common build.

### What goes in which block

A block is about **why you buy the item on this build**, not what its stat line
says — and an item sits in exactly one. The same item lands in different blocks
on different builds: Guardian Angel is a situational kamikaze buy on Shyvana
(Niche) and the last item you finish on with Viego (Capstone). Read the block
name as a question about this champion, not as a category.

| block | holds | not |
|---|---|---|
| Starting Items | the three jungle pets | — |
| Utility | potion, trinket, ward, both elixirs. No notes: these are defaults, not decisions | — |
| Boots | tier one, then every upgrade worth a game — plus anything the boot plan ends in, like Youmuu's after selling them | — |
| Components | what one early back actually buys: **nothing over 1000g** | Phage, Hearthbound Axe, Tunneler and the rest of the ~1100g combines |
| Core | the items the build *is*, in order where the order is fixed. The block whose notes are always written fresh per build | — |
| Post-Core | the standard follow-ups you buy without a matchup asking you to. Two, three, four — however many the build has | anything you only buy sometimes |
| Niche | everything situational, no cap: sidelane, revive, shred, anti-kite, the matchup answers that are not pure resistances | — |
| Armor / Magic Resist | reactive resistance buys, kept on separate shelves. A build that never buys them deletes both blocks (Lethality Viego does) | a resist item bought for its damage (Maw, Wit's End) — that is Post-Core or Niche |
| Capstone | what this build finishes on. Usually the stat-scaling class (Sterak's, Jak'Sho, Endless Hunger, Overlord's), but on a crit build it is Guardian Angel and Death's Dance | — |

Capstone is **not** "everything in `CAPSTONE` in `forge.html`" — that set is the
stat rail's grouping and includes Riftmaker and Titanic Hydra, which are bought
second and situationally. The criterion is the slot, not the class.

### Two rules that come off the champion, not the item

- **One Spellblade item per build.** Sheen, Trinity Force, Iceborn Gauntlet,
  Lich Bane, Essence Reaver, Dusk and Dawn and Divine Sunderer share one unique
  passive, so the client will not let you own two. Iceborn beside Trinity is not
  a worse choice, it is an impossible one — and the same goes for Iceborn beside
  Dusk and Dawn, which is the Sheen item PTA Shyvana is built on.
- **An item the kit already gives is not an option.** Shyvana's passive hands her
  armour and magic resist, so Maw is buying her a stat she has and a slot she
  could spend better; Highlander is slow immunity, so Dead Man's Plate is anti-kite
  Yi already owns in the fight he bought it for. Check the passive and the
  ultimate before a resist or a movement item goes on a shelf.

The mechanical checks worth re-running after an edit: nothing in a Components
block over 1000g, no set holding two Spellblade items, no item in two blocks,
and every note starting `Take ` and ending in a period. All four hold across
every saved build.

## Set versioning

A set is keyed by `(name, patch)`. Saving on the same patch replaces; saving
once a new patch has landed inserts a new row and stamps `forkedFrom`. Nothing
is ever migrated or rewritten, so an old build stays exactly as it was.

## Auto sets

`POST /forge/api/autobuild` ({champion, role}) writes sets from the baked sources. Names are
`Auto <Keystone> <Champion> <Role>` (archetypes and Lolalytics) and `Auto Coachless ...`.
Each carries `auto: true`, `autoKey`, `sources` ({source: patch}) and `patch`. Auto sets are
read-only: `POST /forge/api/sets` onto an auto id (by name or rename) answers 409, the builder
opens them locked with a Copy to my builds button (a new non-auto set, "Auto " dropped), and
they are never carried forward or forked from; Autobuild rebuilds them each patch. A rerun replaces and prunes only
`auto: true` sets for that champion, role and patch, and only for sources read this run.
The champion page shows an Auto tag, and `data from <patch>` when a source patch differs
from the set's patch.
