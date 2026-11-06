# CLAUDE-stat-rail — dashboard/hub/forge

The stat rail and its two columns. Split out of `CLAUDE.md` on
2026-08-29, which was 1,682 lines against the 250-line governance ceiling — past it
everything in the bottom half is underweighted at read time. Nothing was reworded.

## The stat rail names a stat the way the client names it

**Every glyph comes from one place, and it is a NAMED file set, not an atlas:**

```
plugins/rcp-be-lol-game-data/global/default/assets/ux/fonts/texticons/lol/statsicon/
```

These are the client's **text icons** - the glyphs it drops inline into tooltips - and
each one ships as its own PNG with Riot's own name on it: `onhit`, `scalehealshield`,
`scalehealth`, `scalehpregen`, `scalemana`, `scalemanaregen`, `scalels`, `scalesv`,
and so on. 36 files. Take glyphs from here and nowhere else.

**Do not go back to the atlases.** `game/assets/ux/lol/statspanel_atlas.png` and the
shop's `game/assets/ux/itemshop/itemshop_texture_atlas4.png` hold the same art with no
labels on it, and reading art off a contact sheet is how two rows got their symbols
swapped: **`scalels` (Life Steal) is the crossed drop and `scalesv` (SpellVamp, which
is the Omnivamp row's tag) is the fangs.** Fangs *look* like life steal. The file name
is what settles it, and the atlases do not have one. That was found by grepping
CommunityDragon's own full index, which is one request and the fastest way to answer
"does the client ship an icon for X":

```
https://raw.communitydragon.org/latest/cdragon/files.exported.txt      # ~726k paths
```

The named set is also what makes the rail's shape possible: it carries plain
`scalehealth` and plain `scalemana` **apart from** `scalehpregen` and `scalemanaregen`,
so health and mana each sit in a row of their own rather than folded into one
`Health & Regen` row; and it carries `scalehealshield`, so Heal and Shield Power is a
row rather than a blank.

Glyphs are inlined as data URIs, so the rail costs no request and cannot break on a
dead CDN path. `bake_glyphs.py` is what writes that block - it holds the label -> file
map, fetches, normalises and prints the whole `GLYPH` literal ready to paste, and
`--check` asserts the four properties below against what is shipped.

**20x20 is all Riot has.** The two atlases carry the same art at the same scale (~20px
of content on a 27px pitch) and the exported index has no 2x variant anywhere, so more
resolution is not available at any price. What IS available is not resampling the art
twice on the way to the screen. The set before 2026-08-19 was nearest-neighbour doubled
to 40x40 and then downsampled by the browser into a 22px box - an uneven ratio over
blocky pixels, which is what made the rail read soft. Every glyph is now baked at
**44x44, exactly 2x the largest box one is drawn in** (22px rail, 20px inspector, 18px
hover card), so a 1x screen halves it cleanly and a 2x screen draws it 1:1. See "Art is
drawn at the size it exists" below; `verify_frontend.py` fails any CSS box wider than
its pixels.

**Riot's tiles are not uniformly inset, so the bake normalises them.** Most glyphs sit
in 18x18 of their 20x20 tile, but `onhit`, `scalems` and `scaletenacity` run edge to
edge - so those three rows read ~11% larger than every other row and touched their box.
Each glyph is cropped to its own alpha bounds, scaled so its **long side is 40**, and
centred on the 44 canvas, with the short side rounded to an even number so the centring
is exact rather than half a pixel off. Uniform weight, a margin on every side, nothing
clipped. Do not paste a glyph in by hand around that: run the baker.

**One glyph is not Riot's: the Capstone crown.** The client ships no crown in this
idiom anywhere (`scalecapstone` is Arena's chevron-and-diamond, and every other crown
in the index is TFT augment art or a skin particle), so it is drawn on the same 20px
grid in the set's own gold, rgb(226,186,61). Nothing else in `GLYPH` is hand-made, and
nothing else should become hand-made without the same note.

`GLYPH` and the inspector's `STAT_GLYPH` must name the same keys, or a number in the
panel and a row in the rail stop being recognisably the same stat.

### Rows are tags, except the two Riot has no tag for

A `STAT_GROUPS` row is `[label, tags]` where `tags` is a list of Riot item tags - the
shop's own checkboxes - **or a predicate on the item**. Two rows need the predicate:

- **Heal & Shield Power** reads the stat line the item already prints (`i.st`), because
  Riot ships no tag for it. 7 items.
- **Capstone -> Scales off your stats** is a hand-kept id list, `CAPSTONE`. 16 items.

**Capstone is not a stat you buy - it is a stat that buys itself off the rest of your
sheet.** Sterak's is bonus health turned into AD and a shield; Jak'Sho is your
resistances turned into 30% more of themselves; Rabadon's is your own AP times 1.3.
Whether one of these is worth a slot depends entirely on what the other five already
hold, which is exactly the question a set is answering - and no Riot tag marks any of
them, so the list is by hand. **Check it when a patch reworks one of these items.**

The `Slow` row was removed in the same pass: six items carry the tag, none of them are
bought for the slow, and it sat where a Capstone row belongs.

## Two columns, in the client's own shape

The primary tree on the left; the secondary tree and the shards stacked on the
right. Not three equal columns, which is what it shipped as and which left the
primary column reading as the odd one out while the shards, three rows of three,
carried a column of their own.

**Every block is sized against the client, and the columns do not finish level.**
A keystone block is 1.13x a minor and a shard is 0.50x, measured off Sam's
screenshot of the League client's rune page (`Downloads/runes.png`). The left
column therefore ends ~156px above the shard stack, and that raggedness is the
settled call (2026-08-18, his): this picker shows all three or four keystones in
the tree where the client shows only the one you took, so growing them to fill
the column meant four boxes of mostly empty space. The keystone row used to be
flexed to fill (`flex: 1` on the tree body, `.rrow.keys` the only thing growing)
and that is gone.

`verify_frontend.py` asserts the two ratios and asserts the primary column ends
at or above the shard stack. It does **not** compare `#primaryCol` to
`.rune-side`: `align-items: stretch` makes both boxes report the same height
whatever the content does, so that check passed on 1073 == 1073 no matter what.
Read the blocks, never the column boxes.

The grid counts its tracks off `minmax(420px, 1fr)` and the whole grid is capped
at `max-width: 1302px`, **not** `minmax(420px, 640px)`. `auto-fit` sizes the track
count from the max when the max is a fixed length, so the 640px version collapsed
to a single 640px column below 1302px and left the rest of the row empty.

Save and Clear sit in `.meta-head`, top right. They used to sit under the columns,
whose height depends on which tree is picked, so the button moved every time.
