/* The item-set JSON the League client imports, and the patch a save is stamped
 * with. Both are contracts, and both are now needed in two places — the builder
 * writes them, the champion build list reads a saved set back out and offers the
 * same Copy JSON — so they live here rather than being typed twice.
 */

/* Data Dragon versions are three-part (16.16.1) and a set is filed under the
 * two-part patch you played it on (16.16), which is also the format already in
 * the library. Trimming here rather than at each call site is what keeps a set
 * saved today from landing under a patch nobody calls it. */
export const shortPatch = v => String(v || '').split('.').slice(0, 2).join('.');

/* Blocks with no items are dropped: the client shows an empty block as a bare
 * heading, and a set is usually built with a spare block open at the bottom. */
export function itemSetJSON({ title, champions, blocks }) {
  return {
    title: (title || '').trim() || 'Untitled Set',
    type: 'custom', map: 'SR', mode: 'CLASSIC', priority: false, sortrank: 1,
    associatedMaps: [11],
    associatedChampions: [...(champions || [])],
    blocks: (blocks || []).filter(b => b.items?.length).map(b => ({
      type: (b.type || '').trim() || 'Items',
      recMath: false, minSummonerLevel: -1, maxSummonerLevel: -1,
      showIfSummonerSpell: '', hideIfSummonerSpell: '',
      items: b.items.map(i => ({ id: String(i.id), count: i.count })),
    })),
  };
}

/* ── the alternatives contract ────────────────────────────────────────────
 * An alternative names the slot it stands in for, in the rune picker's own
 * `data-slot` language ('p2', 's1', 'shard:flex', 'secondary'). Reading one back
 * to the pick it replaces is a routing table, and a routing table typed in two
 * files is a routing table that drifts — the builder and the saved-build overlay
 * both do this read, so it lives here with the item-set shape for the same reason
 * that does.
 *
 * The NAME lookup deliberately stays at each call site: the builder holds the
 * rune index as RUNEDEX and the overlay holds it as whatever it was handed, and
 * threading a metadata source through here buys nothing.
 */
export const altSlotLabel = slot =>
  slot === 'secondary' ? 'second tree'
    : slot.startsWith('shard:') ? `${slot.slice(6)} shard`
      : (slot[0] === 'p' ? 'primary row ' : 'secondary row ') + slot[1];

/* The id this alternative would replace, or null when there is nothing in that
 * slot yet — and null too when the alternative IS the current pick, which is the
 * normal state right after banking a second tree you just finished building and
 * before switching back. Printing "Inspiration instead of Inspiration" there is
 * true and unreadable.
 *
 * `rowOf(id)` answers which row a rune sits in; only the secondary rows need it,
 * because R.sec is a flat two-item list rather than one slot per row.
 */
export function altReplaces(runes, alt, rowOf) {
  const slot = alt.slot;
  const cur = slot === 'secondary' ? runes.secondary
    : slot.startsWith('shard:') ? runes.shards?.[slot.slice(6)]
      : slot[0] === 'p' ? (runes.rows || [])[+slot[1] - 1]
        : (runes.sec || []).find(x => rowOf(x) === +slot[1]);
  const mine = slot === 'secondary' ? alt.tree : alt.id;
  return cur && cur !== mine ? cur : null;
}

/* Data Dragon templates the numbers OUT of item descriptions, so the `ps` blocks
 * baked into catalog.json read "Gain  bonus Attack Damage." with the ratio simply
 * absent. `bake_passives.py` resolves Riot's own tooltip templates against Riot's
 * own calculation graph and serves the filled-in blocks at /forge/api/passives;
 * this drops them over the catalog in place.
 *
 * It lives here rather than at either call site because BOTH surfaces load the
 * catalog independently — the builder in its head preflight, the saved-build
 * overlay lazily on first open — and both render `ps`. One contract typed in two
 * files is one contract that drifts.
 *
 * An item Riot could not be read for keeps its Data Dragon text: a half-filled
 * sentence is worse than a gutted one, so the baker omits those rather than
 * shipping a token, and this only ever overwrites what it was handed.
 */
export function applyPassives(items, baked) {
  const by = baked?.items;
  if (!by) return items;
  for (const i of items) {
    const ps = by[String(i.id)];
    if (ps) i.ps = ps;
  }
  return items;
}
