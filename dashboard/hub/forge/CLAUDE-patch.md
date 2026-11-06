# CLAUDE-patch — dashboard/hub/forge

The patch note, the patch page and the builder's patch strip. Split out of `CLAUDE.md` on
2026-08-29, which was 1,682 lines against the 250-line governance ceiling — past it
everything in the bottom half is underweighted at read time. Nothing was reworded.

## The patch note is quoted, not computed — and it is its own tab

`/forge/patch` is a **peer of the build shelf, not a header on it**. The note used
to be a section on top of the champion cards, which meant a 22-entry patch pushed
the shelf — the thing you open the tool for — below the fold every second Tuesday.
`Champions`, `Patch` and `Stats` are the three top-level surfaces and **all five**
top bars carry the same `.navtabs` (see "One shell, six surfaces" in CLAUDE-chrome.md).
The landing page does not fetch `/api/patchnotes` at all any more.

Its content is **Riot's own patch notes**, baked from
leagueoflegends.com by `bake_patchnotes.py`. It used to be a strip of item stat
diffs computed by `build_diff.py` from two Data Dragon blobs, and that strip was
wrong in the way that matters. Patch 26.16:

| what happened | what Data Dragon could see |
|---|---|
| Sundered Sky healing cut `100%/6%` → `90%/4%`, recipe stripped of a Ruby Crystal, Health `400` → `450` | `FlatHPPoolMod 400 → 450` |
| Black Cleaver AD `40` → `45`, Fervor move speed split to `[20 Melee \|\| 10 Ranged]` | `FlatPhysicalDamageMod 40 → 45` |

Both numbers were right and both readings were wrong: a nerfed item showed as a
buff, because a passive and a recipe are not fields in `item.json`. No amount of
diffing recovers them — the information is not in the data. **When the diff and
the notes disagree about whether a patch was good for an item, the notes are the
one that knows.**

`build_diff.py` is still there and still useful: it answers a narrower question
the notes cannot, which is *which* of the patch lands on an item this pool
actually buys. It is what the builder's strip reads. The two files are never
merged, for the same reason coachless and lolalytics are not.

**The bake keeps every section; the page renders four.** Champions, Items, Runes
and Systems are what touch a ranked Summoner's Rift build. Classic, ARAM: Mayhem,
Arena and the bugfix list are baked into the JSON and filtered out at render —
throwing them away at bake time would be the expensive mistake, and rendering
them would put three other games on the front door of a tool whose own title bar
says Ranked Summoner's Rift.

**The designer context stays on the page.** The blockquote explaining *why* a
number moved is the half a stat diff can never carry, and it is what turns
"Health 400 ⇒ 450" back into "we cut its healing and gave some of it back as
stats."

## The patch page is one aligned sheet per card, and nothing wraps mid-comparison

Two layout rules, both of them things Sam sent the page back for.

**One grid per CARD, not per group.** Base Stats and each ability used to own a
separate two-column `<dl>`, so the label column was sized independently in every
block and no value on a card began at the same x as the one above it — a card
with a long ability name and a short stat name read as two ragged tables stacked
on each other. The groups are `display: contents` inside a single `.sheet` grid
now, so however many abilities a card carries, every label shares one column and
every value starts at one x. `verify_frontend.py` asserts it: every `.rows dd` on
a card reports the same `left`.

**A comparison never breaks across lines.** A number list broken in half cannot
be compared, which is the whole complaint the page was rebuilt to answer. So:

- Each `.d` comparison is `nowrap`. Only the **dim unchanged text around it** may
  wrap — that is what stops a long tail dragging the compared numbers off the
  card.
- `.d` uses padding with a **matching negative margin**, so its tint bleeds around
  the numbers instead of pushing the line apart. A chip with real side padding put
  a space between a value and the unit Riot wrote against it: `25% AP` rendered as
  `25 % AP`, `11s` as `11 s`, `40/level` as `40 /level`.
- `SIDE_BY_SIDE_MAX` now applies **only** to the handful of bullets a patch where
  Riot replaced the whole value instead of a number inside it, since those are the
  only ones with no per-number reading. Past that many characters combined (not
  each — what has to fit is the whole `old → new` line) the pair **stacks**, old
  above new, left-aligned. That is not a wrap; each value is whole on its own line.
- Anything that will not fit even stacked scrolls its own row, with a permanently
  drawn scrollbar — the platform's overlay bar only appears once you are already
  scrolling, which is no use as the hint that there is more to the right.
- `verify_frontend.py` asserts the lot on the rendered page: no `.was`/`.now`
  reports more than one client rect, at least one row carries a buff **and** a
  nerf chip (or the per-element reading has collapsed back to one verdict a row),
  no row's box extends past its card, and the document never scrolls sideways.

**The patch page is themed like every other page in the module.** It shipped
without the `forge-themes.css` link, the pre-paint `forge:theme` read, or the
`mountThemePicker` mount, so it was the one surface stuck on the default while
the rest of the Forge followed the picker. `frost` is the only light theme and so
the only one that has to restate `--buff` / `--nerf` / `--rework`: the base values
are light type on a near-black tint, which on a white card is invisible type on a
black smear.

**Colour is never the only carrier.** The badge prints the word (`BUFF`, `NERF`,
`REWORK`) next to its colour and the card's left edge repeats it, because a red
number and a green number are the same number to about 8% of men.
