# CLAUDE-patch-strip — dashboard/hub/forge

The patch strip the BUILDER carries, as opposed to the patch note and the patch
page (those are in `CLAUDE-patch.md`). Split out of `CLAUDE.md` on 2026-08-29,
which was 1,682 lines against the 250-line governance ceiling. Nothing was
reworded.

## The patch strip on the builder is icons, and its edge is the whole message

The strip above the shop (`patchstrip.js`, `.patchstrip`/`.change` in
`forge-base.css`) answers exactly one question — **did anything under my figures
move** — because the statistics are a patch behind the live game. It is a caveat
on the numbers, not a feature of its own, so it renders small.

**It shows every item in the shop's catalog, not only the ones somebody bought.**
`build_diff.py` used to key its diff off the coachless bake, which hid a change to
an item you were about to consider on the grounds that nobody had rushed it yet —
backwards for this strip. The catalog (207 items) is still a filter, because Data
Dragon carries Ornn upgrades, dead ids and modes with no shelf here, and because an
entry with no icon has nothing to render now.

**One icon per item, and the border carries buff / nerf / rework** (`--buff` /
`--nerf` / `--rework`, the same palette the patch page's own badges use). Nine
two-line cards pushed the shop below the fold to say what nine coloured edges say
at a glance. The numbers live in the hover card, which is where the WORD lives
too: a red edge and a green edge are the same edge to about 8% of men, so
`changeCardHTML` prints `BUFF` / `NERF` / `REWORK` rather than implying it.

**The item changes come from RIOT'S OWN NOTES, not from a Data Dragon diff.**
`notes_items()` reads what `bake_patchnotes.py` baked into
`data/forge-patch-notes.json` and keys it to the catalog by item name;
`diff_items()` covers only what Riot did not write up. **Do not put ddragon back
in front.** Riot templates the passive numbers out of its item descriptions —
Sterak's Gage reads `Gain  bonus Attack Damage`, the number simply absent, and
that string is byte-identical across 16.15.1 and 16.16.1. Eclipse and Sterak's
both changed in 26.16 and a ddragon diff saw *nothing*. Across that patch Riot
listed 18 item changes; the diff found 12, three of which carried no number.
`bake_patchnotes.py`'s own docstring called this out before the strip acted on it.

Three things follow from the notes being the source:

- **A row that cannot be measured forces a `rework`.** `measured()` reads a row
  only when its two sides differ by their leading number and the tail holds still
  (`45% of Base Attack Damage` → `50% of Base Attack Damage` counts;
  `20 for 2s` → `[20 Melee || 10 Ranged] for 2s` does not). An unreadable row is a
  change Riot deliberately listed, so it outvotes everything. Sundered Sky took
  Health 400 → 450 next to a healing cut and a recipe strip; voting on the health
  alone published a nerfed item as a `buff`, which is the exact failure
  `bake_patchnotes.py` was written to expose.
- **`inverted()` matches on the label**, since Riot names things in words: a
  `cost`, a `recipe`, a `price` and a `cooldown` all read backwards.
- **The name is the join, so a miss is printed, never dropped.** `NOTE_ALIASES`
  holds the one case Riot writes by an older name (Sunfire Cape → Sunfire Aegis);
  anything else unmatched prints to stderr, because a silent miss is how an item
  goes missing from the strip. `notes_items()` also refuses to apply notes whose
  `ddragon` version is not the diff's `to`, which would attribute Riot's changes
  to the wrong pair of patches.

**The same hole eats the PASSIVE NUMBERS, and `bake_passives.py` fills them.**
The templating described above is not only a patch-strip problem: it is why an item
card read `Gain  bonus Attack Damage.` at all. Data Dragon ships the sentence with
the ratio removed, and `catalog.json`'s `ps` blocks come from there. The numbers do
exist, in Riot's own two pieces — `items.cdtb.bin.json` (the formula graph the client
evaluates: `mDataValues` plus `mItemCalculations`) and `lol.stringtable.json` (the
tooltip template, `item_<id>_tooltip`, holding the `@Placeholder@` tokens) — so the
baker walks the graph the client walks and writes the answer into the template. What
lands is a RATIO, not a number, and that is the honest answer: `@BonusAD@` is 50% of
the champion's base AD, so no absolute value exists outside a running game.

Four things about that pipeline are load-bearing and none are documented by Riot:

- **A hashed key is FNV-1a 32 of the lowercased name.** Sundered Sky's heal calc is
  filed under `{01099b16}`, which is fnv1a("healadsplit"). Riot obfuscates both the
  KEYS and the REFERENCES to them, sometimes in the same item, so every table is
  indexed from both sides and every lookup tries both forms.
- **An absent field holds its default.** A part with no `mStat` is stat 0, which is
  Ability Power — so Lich Bane's 45% AP scaling looks like a part with no stat at all.
  Reading that as "unknown" rather than "zero" left a tenth of the catalog unresolved.
- **The name is the join, not the item id** — the same rule `notes_items()` already
  runs. Data Dragon 16.16.1 calls id 3097 Stormrazor; Riot's live bin calls that id
  "Stayin' Alive", a different item with different passives. A disagreeing name is
  dropped and printed to stderr, never substituted.
- **An absent `mValue` is UNRESOLVED, not zero** — the opposite resolution to the
  absent-`mStat` rule above, and the pair of them is why this is worth writing down.
  Spectre's Cowl declares `HealthRegenPassive` with no value and its real figure is
  100%, so defaulting to 0.0 published `gain 0% base Health Regen` on the card. Riot
  omits a field it means as zero AND a field it fills in elsewhere; only an explicit
  `mValue: 0.0` is a real zero.
- **`mEffectAmount` is a zero-filled legacy array.** Sterak's is eleven zeros. Eight
  refs across the catalog do read real numbers out of it (Plated Steelcaps' 10%,
  Guardian Angel, Runaan's, Umbral Glaive), so it stays a source — but a ZERO from it
  is the filler rather than a value, and counts as unresolved. Zeal's `@Effect1Amount@`
  is the one that reached the card, as `Gain 0% Move Speed`.

  Both of those shipped once and were caught by auditing the baked text for a zero,
  not by reading the code. **A confidently wrong number is worse than a missing one**,
  and both of these read as fine English. `bake_passives.py --check` does not catch
  them, because a zero is a perfectly well-formed value; the audit that does is
  grepping the output for `\b0%`.
- **A melee/ranged split is parenthesised, and the parens are load-bearing.** These
  land mid-sentence: without them Sundered Sky reads `restores 90% base AD melee /
  45% base AD ranged plus 4% of missing Health`, where the `plus` could attach to the
  ranged branch or to both. Riot's own `item_range_type_melee` brackets it too.

**In the card a ratio is drawn as its stat, by `withRatios()` in `forge.html`.** The
baker brackets every ratio (`Gain (50% base AD) bonus Attack Damage.`) because a
bracket is what makes it read as one figure rather than as words that happen to sit in
the sentence — and a SUM takes one bracket, not one per term, so Thornmail is
`deal (20 + 10% bonus Armor) magic damage`, which is Riot's own style. `ungroup()`
takes the inner brackets back off whenever an outer one already groups them, which is
what keeps a melee/ranged split from nesting.

The frontend then puts the stat's glyph in front of the number and tints the number in
that stat's colour. Two things about it:

- **The hues are Riot's, sampled from the brightest quartile of each glyph's own
  artwork** (`STAT_HUE`), so the number matches the icon beside it rather than a
  palette invented here. Movement's glyph is near-white, which is not a usable text
  colour against either theme family, so it falls through to `--ink` and lets the icon
  carry the identity alone.
- **The tint is `color-mix`ed toward `--ink`, never used raw.** `frost`'s ink is DARK
  (L 0.275 against an L 0.948 background), so the mix pulls every hue down to
  something legible on a light surface, while the four dark themes have near-white ink
  and the same mix lifts it. One rule instead of a colour table per theme, and nothing
  can go invisible when a theme changes. Verified by looking at Protoplasm Harness —
  gold Armor, cyan Magic Resist, untinted Move Speed — on both a dark theme and frost.

`withRatios()` takes text that is ALREADY escaped and matches nothing but digits, a
percent sign and a name off a fixed list, so it cannot introduce markup of its own. It
deliberately does NOT reach across intervening prose: Swiftmarch's `Gain 5% of your
Move Speed` stays plain, because chipping a number to a stat four words away looks
worse than leaving it alone. 108 chips over the 148 baked items, no false positives.

**A half-filled sentence is worse than a gutted one**, so an item whose template does
not fully resolve is OMITTED from the bake and keeps its Data Dragon text. The ACTIVE
half (`item_<id>_active`) is deliberately never read: its data values live in a spell
bin that file does not carry, and ddragon renders actives with their numbers intact,
so the two sources are complementary — Riot's for passives, ddragon's for actives,
each used where the other is gutted. Coverage on 16.16.1 is 144 of the 157
passive-bearing catalog items.

**The ddragon fallback keeps the description reader.** `desc_changes()` diffs the
two descriptions line by line and `_row()` sorts each changed line into a
**figure** (`"<number> <label>"` whose label held still, with a `unit` on a `%`)
or a **sentence** (carried verbatim, old and new). Riot's `stats` dict is only a
last resort under that — it is a subset of what the tooltip prints and spells its
values in engine units under engine keys — and `_figures()` drops any dict row
whose number pair the description already reported.

**In the card, labelled rows go in the two-column grid and `effect` rows below
it**, the dropped line struck through (`.hc-txt s`) above the line that replaced
it; a removal is struck lines and nothing else. Riot's reasoning (`why`) goes
last and quietest (`.hc-why`), because the strip's question is what moved, not
why. `build_diff.py --demo` pins the vote and the reader; `verify_frontend.py`
pins coverage against the SERVED notes — every item Riot names is on the strip,
with every row Riot listed — rather than against one patch's numbers.

**The accent border no longer marks "this champion buys it"** — the verdict owns
the border now. `mine` renders at full strength and everything else sits back at
half opacity, which is the right weighting for a caveat about THIS champion's
figures.
