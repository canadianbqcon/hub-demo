/* forge-stats.jsx - the Forge builder's champion and role pickers and the statistics
   layer under every figure on the page, as React.

   Port of forge.html lines 2399-3053 (the meta layer: champion/role in the URL, coachless
   and lolalytics readings, the crossed first-item reading, the hover-card body, the
   shop's paint, the note editor and the rune page's data model), plus the champion and
   role handlers (3553-3573) and the boot sequence (3600-3629) that were scattered
   through the next part. Logic is attached to ForgeUI.state (see the interface note in
   forge-shop.jsx); this file renders the .buildhead strip (ForgeUI.Roles), the shop
   legend (ForgeUI.Readings) and the note dialog (ForgeUI.NoteDialog).

   Everything the rune page's UI needs from this file (R, seedRunes, runePayload, the
   figure lookups) is here; its buttons, tree columns, alternatives and hover cards are
   Task 22's. */
(() => {
  const { memo, useEffect, useRef } = React;
  const UI = window.ForgeUI;
  const st = UI.state;
  const esc = st.esc, games = st.games;
  const M = st.M, F = st.F, RATED = st.RATED;

  /* ── the meta layer ───────────────────────────────────────────────────────
     coachless' WPA for this champion in this role: what an item or a rune did
     to the win probability, measured against where the game already stood.

     The one judgement encoded here is that WPA alone is not a ranking. The
     highest-WPA item on any champion is reliably something 200 games bought,
     and a page that sorts on it hands you a confident recommendation built on
     noise. So sample size is never hidden: it sets the length of the bar under
     an item, it is printed next to every rune, and anything under MIN_GAMES is
     drawn as "thin" rather than coloured. Read the wide marks. */
  const MIN_GAMES = st.MIN_GAMES = 1000;

  /* The champion and role live in the URL, not in a dropdown you have to work.
     /forge/c/Viego/jungle/build IS the Viego jungle builder, so it is linkable
     from that champion's build list, bookmarkable, and loads with the statistics
     already on screen. Matched case-insensitively because a hand-typed
     /c/viego/jungle/build should work. The three-segment path is why <base> in the
     head is load-bearing: without it every relative fetch resolves against
     /forge/c/Viego/jungle/ and 404s. */
  function fromURL() {
    const m = location.pathname.match(/\/c\/([^/]+)\/([^/]+)\/build\/?$/);
    if (!m) return null;
    const want = decodeURIComponent(m[1]).toLowerCase();
    const champ = Object.keys(st.STATS.champions).find(n => n.toLowerCase() === want);
    if (!champ) return null;
    const role = Object.keys(st.STATS.champions[champ].roles || {})
      .find(r => r.toLowerCase() === decodeURIComponent(m[2]).toLowerCase());
    return role ? { champ, role } : null;
  }

  st.loadMeta = () => {
    // the URL wins over the last session's pick: a link has to mean what it says
    const seed = fromURL();
    if (seed) { M.champ = seed.champ; M.role = seed.role; return; }
    try {
      const v = JSON.parse(localStorage.getItem('itemSetForge.meta') || 'null');
      if (v && st.STATS.champions[v.champ]?.roles[v.role]) { M.champ = v.champ; M.role = v.role; }
    } catch { /* a hand-edited entry is just not used */ }
  };

  /* The way out goes to this champion's build list, one level up; it is read by Roles. */
  const backLink = () => ({
    href: M.champ && M.role
      ? `c/${encodeURIComponent(M.champ)}/${encodeURIComponent(M.role)}`
      : './',
    text: M.champ ? `← ${M.champ} builds` : '← Champions',
  });

  st.saveMeta = () => {
    try { localStorage.setItem('itemSetForge.meta', JSON.stringify({ champ: M.champ, role: M.role })); } catch { /* private mode */ }
    // keep the address bar honest, so a copied link reopens what is on screen
    const want = M.champ && M.role
      ? `c/${encodeURIComponent(M.champ)}/${encodeURIComponent(M.role)}/build`
      : 'edit';
    const url = new URL(want, document.baseURI).pathname;
    if (url !== location.pathname) history.replaceState(null, '', url);
    st.emit();      // the back link under the bar reads M
  };

  const current = st.current = () => st.STATS.champions[M.champ]?.roles[M.role] || null;
  const runeMeta = st.runeMeta = id => st.RUNEDEX.runes?.[String(id)] || null;
  st.treeMeta = id => st.RUNEDEX.trees?.[String(id)] || null;

  /* WPA is in points of win probability. Two decimals is the honest resolution -
     a third would imply the model separates 0.001 from 0.002, which it does not. */
  st.fmtWpa = w => (w >= 0 ? '+' : '−') + Math.abs(w).toFixed(2);
  st.wpaClass = (w, n) => n < MIN_GAMES ? 'thin' : (w >= 0 ? 'up' : 'down');
  const fmtWpa = st.fmtWpa, wpaClass = st.wpaClass;

  /* ── the second opinion: lolalytics ───────────────────────────────────────
     coachless is paywalled on the live patch and only breaks a champion down by
     the keystones enough games took, so most of the rune page reads as dashes on
     a patch-old figure. lolalytics is on the live patch and carries a number for
     every rune, so the two sit side by side: WPA where coachless has one, win rate
     and pick rate always. Neither is the other's correction - they measure
     different things, which is exactly why both are on screen.

     The caveat that stays on the page rather than getting buried here: lolalytics'
     win rate is a raw win rate, not WPA. */
  const lola = st.lola = () => st.LOLA.champions?.[M.champ]?.[M.role] || null;
  /* Runes are read under the picked keystone when the bake has a block for it, the
     same way every coachless figure on this page is. It matters: Legend: Alacrity is
     8.0% pick on Shyvana jungle under Press the Attack and 80.0% under Conqueror,
     and the keystone-blind grid averages the two into a figure describing neither.

     All-or-nothing on purpose. With a block, a rune the keystone has no reading for
     holds a dash rather than falling back to the role-overall figure, because two
     populations in one lane is the thing this change exists to stop. The whole lane
     falls back only when the bake has no block for this keystone at all, which is
     every keystone under the bake's pick floor. */
  const lolaKs = () => lola()?.runesByKeystone?.[String(st.R.keystone)] || null;
  /* The KEYSTONE row is the exception and keeps the role-overall reading. A
     keystone's line in the keystone-blind grid is already only the games that took
     it, so filtering by it adds nothing - and under the filter the picked keystone
     reads 100% while every other one reads a dash, which is exactly the column of
     pick rates you switched to that row to compare. */
  st.lolaRune = (id, ks) => (ks ? lola() : (lolaKs() || lola()))?.runes?.[String(id)] || null;
  const lolaItem = st.lolaItem = id => lola()?.items?.[String(id)] || null;
  /* Boots are their own key, not a slot in `items`: lolalytics publishes them in a
     separate unlinked strip with one reading each and no build-slot breakdown. */
  st.lolaBoot = id => lola()?.boots?.[String(id)] || null;

  /* Read against the champion's own win rate in this role, not against 50: a 51%
     rune on a 53% champion is a rune that loses you games. Runes pass the keystone's
     own win rate instead, because that is the population they were measured in -
     Shyvana jungle is 53.3% overall and 53.6% under Conqueror, so a 53.4% minor rune
     is above the role and below the keystone. Items and boots are still role-overall
     readings and keep the role-overall base. */
  const lolaBase = st.lolaBase = () => lola()?.wr ?? 50;
  st.lolaRuneBase = () => lolaKs()?.wr ?? lolaBase();
  st.fmtWr = w => `${w.toFixed(1)}%`;
  st.wrClass = (w, n, base) =>
    n < MIN_GAMES ? 'thin' : (w >= (base === undefined ? lolaBase() : base) ? 'up' : 'down');
  const fmtWr = st.fmtWr, wrClass = st.wrClass;

  /* The role list a champion's select offers, ordered by games so the role a
     champion is actually played in leads. fillRoleSelect keeps M.role on it. */
  st.rolesFor = champ => {
    const roles = Object.keys(st.STATS.champions[champ]?.roles || {});
    roles.sort((a, b) => st.STATS.champions[champ].roles[b].n - st.STATS.champions[champ].roles[a].n);
    return roles;
  };
  st.fillRoleSelect = () => {
    const roles = st.rolesFor(M.champ);
    if (!roles.includes(M.role)) M.role = roles[0] || '';
    st.emit();
  };

  /* ── items: a coloured edge on the tile, width = share of these games ──────
     Read under the chosen keystone when the bake has rows for it, the same way
     every figure on step one is. What Kraken Slayer is worth under Conqueror is not
     what Umbral Glaive is worth under Hail of Blades - on Viego jungle the Glaive
     reads +4.54 under Hail of Blades and does not place at all under Conqueror -
     and the keystone-blind list averages the two into a figure describing neither.

     The flat list stays as the fallback rather than the shop going blank: coachless
     only breaks a keystone out once enough games took it, so a rare keystone has no
     rows of its own and the aggregate is the honest reading left. */
  /* The Core block's first legendaries, and WHERE they sit - the set marks those
     slots, so the block index travels with the ids rather than being looked up twice
     against a rule that could drift. A build is centred on a keystone and on what it
     buys first, so this is the second axis every figure in the shop is read under.
     Named blocks are renameable, so it matches on the name and falls back to the
     first block holding items that is not the starting one - a set called "Rush"
     still has a first item. It is always that block's slots 0 and 1.

     There is no starting-item axis any more. A jungle pet used to be a condition
     you picked, crossed into the reading; it is now an ordinary item carrying its
     own figures (coachless itemType 6), which is what a pet always was on the page. */
  const coreSlot = st.coreSlot = () => {
    const blocks = st.S.blocks;
    const bi = blocks.findIndex(b => /core/i.test(b.type) && b.items.length);
    const i = bi >= 0 ? bi : blocks.findIndex(b => b.items.length && !/start/i.test(b.type));
    if (i < 0) return null;
    /* Slots 0 and 1, and no further. The depth is the build's to choose - one core
       item conditions on one, two conditions on both - but the ceiling is coachless'
       and not a design choice: `thirdLegendaryId` is accepted with a 200 and then
       ignored, rows byte-identical to the first-only call. A three-slot condition
       would paint a shop measured under two while the page said three, and nothing
       in the answer would give it away. So the block can hold six; the axis reads
       two and the legend says which.

       A repeat of the same item in slot 1 is dropped: `secondLegendaryId` equal to
       `firstLegendaryId` is not a build path, it is the same condition asked twice. */
    const ids = blocks[i].items.slice(0, 2).map(it => it.id);
    if (ids[1] === ids[0]) ids.length = 1;
    return { bi: i, ids };
  };

  /* The first-item reading, fetched rather than baked. `itemsByKeystone` is one
     axis and sits in the bake because a champion/role has a fixed handful of
     keystones. The first item does not work that way: it is whatever is in the Core
     block right now, so baking every possible first item is hundreds of calls per
     champion/role for cells nobody opens. One call per opener actually built, cached
     server-side, costs nothing.

     The second legendary and the keystone both cross into it, and nothing is kept
     out on the argument that it is "too narrow" - the floor decides that per cell.
     Collector into Immortal Shieldbow on Viego jungle 16.15 is 22 rows with 11 over
     the thousand-game floor; Hail of Blades with the same rush is 27/14. What fails
     is a thin keystone, not the cross: Press the Attack is 2,909 games alone on this
     champion, so it comes back six rows with none over the floor and the walk drops
     it. The start stays out because there is no longer a start to cross.

     Depth stops at two, and coachless is what stops it: `thirdLegendaryId` answers
     200 and is then ignored, rows identical to the first-only call. `coreSlot` caps
     it and the legend names the cap.

     `rows` stays null until an answer with rows in it lands, so every path below
     falls back down the baked chain - the shop never goes blank and never waits on
     the network to paint.

     `asked` is the deepest condition that actually went out, and it is the only
     thing the legend and the slot markers are allowed to read. Captioning from the
     live picks instead is a caption that runs ahead of its own figures: a click
     repaints synchronously, so for the length of the round trip the sentence named a
     condition the figures on screen were not yet under. It stays null until an
     answer lands, so mid-flight is `pending` for every marker, and a repaint only
     ever happens once the walk below has settled.

     Resolves true when COND moved and the page should repaint. A promise chain rather
     than async/await so no Babel helper becomes a top-level global. */
  st.refreshConditioned = () => {
    const core = current() ? coreSlot() : null;
    const [first, second] = core?.ids || [];
    const ks = st.R.keystone || null;
    const key = [M.champ, M.role, first || '', second || '', ks || ''].join('|');
    if (st.COND.key === key) return Promise.resolve(false);
    /* `ks` is stashed on COND, not read live off `R` at caption time. A keystone
       click calls paintItems() synchronously BEFORE renderBlocks() kicks the walk
       off, so a legend reading `R.keystone` would name a keystone the figures on
       screen were not measured against - the same drift `asked` exists to prevent.
       Set at reset with `rows: null`, so the two can only ever be read together. */
    st.COND = { key, rows: null, asked: null, ks };
    if (!first) return Promise.resolve(false);
    /* Deepest first, dropping one filter at a time, and the baked chain below that.
       The second core item goes first because it narrows one slot of the build; the
       keystone goes last because it reshapes the whole list. Every rung is gated on
       the same floor, so a cell that cannot support itself simply hands over.

       This is what replaced "the keystone is never crossed in". That rule was
       measured on Press the Attack - 6 rows, none over the floor - and generalised,
       but the thinness was Press the Attack's (2,909 games alone on Viego), not the
       cross's. Hail of Blades with the same rush is 27 rows with 14 over the floor
       on a 30,470-game top line, against 29/16/39,947 for the rush alone. The rare
       keystone still fails, one rung down, which is the old rule surviving as a
       special case of the floor rather than as a rule of its own.

       A second slot holding boots or a pet lands in the drop path too: it is not a
       legendary, the pair comes back empty, and the shallower cell gets served. */
    const base = second ? [{ first, second }, { first }] : [{ first }];
    const rungs = ks ? base.map(c => Object.assign({}, c, { keystone: ks })).concat(base) : base;
    const walk = n => {
      if (n >= rungs.length) return Promise.resolve(true);
      const cond = rungs[n];
      const q = new URLSearchParams(Object.assign({ champ: M.champ, role: M.role }, cond));
      return fetch(`api/conditioned?${q}`).then(r => r.json()).catch(() => null).then(rows => {
        // A newer condition set was clicked while this was in flight; it owns COND now.
        if (st.COND.key !== key) return false;
        /* One row under the floor is not a reading. Conditioning on a first item nobody
           actually rushes comes back with a single 106-game row, and taken at face value
           that empties the shop down to one dim tile and captions it as measured. The
           cross has to clear the same 1,000-game floor every other figure here does or
           it does not get to be the answer. */
        st.COND.asked = cond;
        if (Array.isArray(rows) && rows.some(r => (r.n || 0) >= MIN_GAMES)) {
          st.COND.rows = rows;
          return true;
        }
        return walk(n + 1);
      });
    };
    return walk(0);
  };

  const coachItems = st.coachItems = () => {
    const data = current();
    if (!data) return [];
    /* Conditioned first, then the keystone's baked list, then the aggregate. The
       shop never goes blank and never waits on the network to paint. */
    return st.COND.rows
        || (st.R.keystone && data.itemsByKeystone?.[String(st.R.keystone)])
        || data.items || [];
  };
  st.coachItem = id => coachItems().find(i => String(i.id) === String(id)) || null;

  /* The same bake read backwards. `coachItems` answers "under Conqueror, what is
     good"; this answers "this item, which keystone does it want" - the question you
     are actually asking when the item is the thing you are committed to and the rune
     page is still open. Nothing extra is fetched; it is itemsByKeystone pivoted.

     A row only qualifies if it clears MIN_GAMES **and** gained win probability - the
     two conditions that make the figure render solid rather than dim, so the rule is
     the one already on screen: if it is not a reading you would trust in the shop, it
     is not a reading that gets to name a keystone. Without the sample floor, one
     player going 1-0 out of Hail of Blades makes an item "want" Hail of Blades, which
     is the case this exists to refuse.

     The best qualifying row is the whole answer. The worst was shown alongside it at
     first and carried nothing: an item's least favourite keystone is not a thing you
     act on, and pairing them turned one usable line into two you had to read past. */
  st.keystoneSpread = id => {
    const by = current()?.itemsByKeystone || {};
    const rows = [];
    for (const [kid, list] of Object.entries(by)) {
      const hit = list.find(i => String(i.id) === String(id));
      if (hit && hit.wpa != null && hit.wpa >= 0 && hit.n >= MIN_GAMES)
        rows.push({ kid, wpa: hit.wpa, n: hit.n });
    }
    return rows.sort((a, b) => b.wpa - a.wpa);
  };

  const ordinal = st.ordinal = n =>
    n + (['th', 'st', 'nd', 'rd'][(n % 10 > 3 || (n % 100) - (n % 10) === 10) ? 0 : n % 10]);

  /* `itemsBySlot` read backwards, same pivot `keystoneSpread` does for
     keystones: the bake is keyed by slot -> item list, this answers "this item,
     which of its slots does coachless have a reading for". No floor here - a
     thin slot still shows, dimmed by `wpaClass`, exactly like the flat shop
     figure. Only a slot coachless has NOTHING for (not in the bake at all)
     counts as absent, which is what sends that slot to the lolalytics fallback
     below. */
  st.coachSlots = id => {
    const by = current()?.itemsBySlot || {};
    const out = {};
    for (const [slot, list] of Object.entries(by)) {
      const hit = list.find(i => String(i.id) === String(id));
      if (hit && hit.wpa != null) out[slot] = hit;
    }
    return out;
  };

  /* One hover-card body, used by the shop tiles, the slots inside a block and the
     nodes in a build path. The figures are the same figures wherever the icon
     happens to be, and three near-identical builders is how they stop being the
     same figures.

     This replaced `itemTitle()`, which built the same content into a `title`
     attribute. That was not a visible change: a native tooltip takes about a second
     to appear, renders as unstyleable browser chrome, and on a grid of 48px tiles
     nobody ever waited for it. Stats lead, because "what does this give me" is the
     question your pointer is asking. Returns an HTML string for Task 22's card. */
  st.itemCardHTML = (id, note) => {
    const i = st.BY_ID.get(String(id));
    if (!i) return '';
    /* The note goes directly under the name, above everything else. Every other
       line on this card is a measurement of what the item did in a lot of games;
       this is the one line that knows why it is in THIS build, and it is worth
       nothing underneath a stat list. Only a slot in the set has one - a shop
       tile is not in any build yet, so it has nothing to say. */
    const hasNote = note ? `<p class="hc-note">${esc(note)}</p>` : '';
    const stats = st.statsDL(i) || '<p class="hc-pas">No stats. It is bought for what it does.</p>';
    const pas = i.ps.map(b =>
      `<p class="hc-pas">${b.h ? `<b>${esc(b.h)}</b> ` : ''}${st.withRatios(esc(b.t))}</p>`).join('');

    const figs = [];
    const c = st.coachItem(id);
    if (c && c.wpa != null)
      figs.push(`<span class="k">coachless</span><span>WPA <b class="${wpaClass(c.wpa, c.n)}">`
        + `${fmtWpa(c.wpa)}</b> · ${c.share.toFixed(1)}% of games · ${games(c.n)} bought</span>`);
    const best = st.keystoneSpread(id)[0];
    if (best)
      figs.push(`<span class="k">wants</span><span>`
        + `<b class="${wpaClass(best.wpa, best.n)}">${fmtWpa(best.wpa)}</b> under `
        + `${esc(runeMeta(best.kid)?.name || best.kid)} · ${games(best.n)} games</span>`);
    /* Per slot: coachless first, since it conditions on game state and lolalytics'
       raw win rate does not. Only a slot coachless has nothing for falls back to
       lolalytics, and that fallback is named on the line - the two are not the
       same measurement and a reader has to know which one they're looking at. */
    const l = lolaItem(id) || {};
    const cs = st.coachSlots(id);
    const slots = new Set([...Object.keys(cs), ...Object.keys(l)]);
    for (const slot of [...slots].sort((a, b) => +a - +b)) {
      const c2 = cs[slot];
      if (c2) {
        figs.push(`<span class="k">${ordinal(+slot)} · coachless</span><span>`
          + `WPA <b class="${wpaClass(c2.wpa, c2.n)}">${fmtWpa(c2.wpa)}</b>`
          + ` · ${c2.share.toFixed(1)}% of this slot · ${games(c2.n)} bought</span>`);
        continue;
      }
      const v = l[slot];
      figs.push(`<span class="k">${ordinal(+slot)} · lolalytics</span><span>`
        + `<b class="${wrClass(v.wr, v.n)}">${fmtWr(v.wr)}</b> win`
        + ` · ${v.pick.toFixed(1)}% pick · ${games(v.n)} games</span>`);
    }

    return `<h4>${esc(i.n)}<b>${i.g.toLocaleString()}g</b></h4>${hasNote}${stats}${pas}`
      + (figs.length ? `<div class="hc-figs">${figs.join('')}</div>` : '');
  };

  /* One sentence naming exactly which games the figures on screen are drawn from.
     It names every filter the rows survived and no others, in the order they cross:
     the keystone, then the first item, then the second.

     Whatever was asked about and came back too thin has to be named as DROPPED
     rather than left out silently - nobody rushes Immortal Shieldbow on Viego, and
     silence there reads as "measured, and here it is". That applies to the keystone
     the same way: a lit keystone with no mention in this sentence reads as "of course
     these are read under it". */
  const readingLabel = st.readingLabel = data => {
    if (!data) return '';
    const name = id => st.BY_ID.get(String(id))?.n;
    const asked = st.COND.asked;
    const R = st.R;

    /* No article in front of either name: half the items in the game are called
       "The <something>", and "a The Collector rush" is what an article gets you.
       Both halves of the condition, in the order they were crossed. "items read
       under X" keeps the phrasing the baked-keystone rung already uses, so the
       sentence reads the same whether the keystone came off the live cross or off
       the bake - the only difference the reader cares about is which items follow. */
    if (st.COND.rows && asked) {
      const under = asked.keystone
        ? ` · items read under ${runeMeta(asked.keystone)?.name || 'this keystone'}`
        /* A keystone that was picked and did NOT make the floor has to be said out
           loud. Silence here is the same failure the dropped-first-item clause was
           written for: the reader sees a keystone lit on step one, no mention of it
           in the sentence, and reads that as "of course these are read under it". */
        : st.COND.ks ? ` · too few games under ${
            runeMeta(st.COND.ks)?.name || 'this keystone'}` : '';
      return under + (asked.second
        ? ` · ${name(asked.first) || 'this item'} into ${
            name(asked.second) || 'this item'} first two items`
        : ` · ${name(asked.first) || 'this item'} first item`);
    }

    /* Read the drop off `asked`, not off the live Core block, so a request still in
       flight stays quiet rather than announcing a drop that has not happened yet. */
    const dropped = asked?.first
      ? ` \u2014 too few games rush ${name(asked.first) || 'that first item'}` : '';

    if (!R.keystone)
      return dropped ? ` · items read across every build${dropped}` : '';
    return data.itemsByKeystone?.[String(R.keystone)]
      ? ` · items read under ${runeMeta(R.keystone)?.name || 'this keystone'}${dropped}`
      : ' · items read across all keystones \u2014 too few games under this one';
  };

  /* The same sentence readingLabel writes for the shop, said inside the set and
     pointed at the slots it is about. Three states, because a confident marker and a
     silent one are both read as "measured": the condition can be asked and come back
     under the thousand-game floor, and the set has to say so rather than sit there
     ringed in accent.

     The line is written from BOTH marks, not from the block's. A second core item
     whose cross was dropped is the case that needs saying out loud: the ring on slot
     0 is honest, the shop really is read out of it, and the only thing that tells
     you slot 1 was tried and did not make the floor is this sentence.

     State comes off `COND.asked`, never off the live Core block - the same rule the
     legend runs on. A drop-in repaints synchronously while the fetch is still out,
     and asking the Core block instead would announce a drop that has not happened
     yet. */
  st.CORE_NOTE = (m0, m1) =>
    m0 === 'pending' ? 'reading the shop out of this build…'
    : m0 === 'thin' ? 'too few games rush this first item, so the shop is not read out of it'
    : m1 === 'read' ? 'stats based on these as the first two items'
    : m1 ? 'stats based on this as first item \u2014 too few games take that one second'
    : 'stats based on this as first item';

  /* `pos` is the Core slot, 0 or 1. Only `asked` decides: it is null for the length
     of the round trip, which is the pending state, and past that it names the
     deepest condition that actually went out. A slot the answer does not name was
     asked about and dropped, so it is thin rather than silent - an unmarked slot 1
     beside a lit slot 0 would read as "both of these count", which is the one thing
     the marker exists to prevent. */
  st.condState = (id, pos) => {
    const a = st.COND.asked;
    if (!a) return 'pending';
    return String((pos === 0 ? a.first : a.second) ?? '') === String(id)
      ? (st.COND.rows ? 'read' : 'thin') : 'thin';
  };

  /* paintItems() of the plain page: take the snapshot the shop draws from. It decides
     which items carry a reading (RATED), the legend sentence, whether the "only items
     with a reading" filter is on, and each grid's order. The tile markup itself
     (figure, edge, hidden) is derived from this snapshot in ForgeUI.Shop. */
  st.paintItems = () => {
    const data = current();
    const by = new Map(coachItems().map(i => [String(i.id), i]));
    /* Which games these figures are drawn from is the whole meaning of them, so a
       keystone too thin to break out says so rather than quietly serving the
       aggregate under a keystone you can see is picked. "items read under X" rather
       than "under X": the purchase count above it is the role's, not the keystone's,
       and the two run together into a claim that 977k games were played on this
       keystone if the phrase is any shorter. */
    const where = !data ? ''
      : `${M.champ} ${M.role} · ${data.n.toLocaleString()} purchases · emerald+`
        + readingLabel(data);
    RATED.clear();
    for (const id of by.keys()) if (st.BY_ID.has(id)) RATED.add(id);
    /* Boots also count as read when only lolalytics has them, and this is why the
       shop used to hide some of them. coachless' boots coverage is incomplete -
       Shyvana jungle's aggregate list has six of the nine and no Boots, Slightly
       Magical Boots or Berserker's - and it narrows AGAIN per keystone. metaOnly then
       hid whatever was missing, so the shelf changed shape depending on the keystone.
       lolalytics carries every boot in one strip, so the second source closes the gap
       the first one leaves. Boots only, deliberately: widening this to every
       lolalytics item would add ten more non-boot tiles on Shyvana jungle alone, which
       is a different decision than fixing a shelf that was visibly incomplete.
       Slightly Magical Boots (2422) is in lolalytics and not in the catalog, so the
       BY_ID guard drops it the same way it drops anything unbuyable. */
    for (const id of Object.keys(lola()?.boots || {})) if (st.BY_ID.has(id)) RATED.add(id);
    // no reading at all forces it off; a reading turns it on until you say otherwise
    if (!data || !F.metaTouched) F.metaOnly = !!data;

    /* Highest WPA first within each grid - but a thin row is still an outlier
       (the note above MIN_GAMES), so a tile under the floor never outranks one that
       cleared it just because its WPA is louder. Rated first by that, then by WPA;
       unrated items keep the shelf's cost/name order they already had, pushed after
       everything that has a reading. */
    const rank = id => {
      const s = by.get(id);
      return !s || s.wpa == null ? [-1, 0] : [s.n >= MIN_GAMES ? 1 : 0, s.wpa];
    };
    const grids = new Map();
    for (const [key, ids] of st.GRID) {
      grids.set(key, ids.slice().sort((a, b) => {
        const [af, aw] = rank(a), [bf, bw] = rank(b);
        return bf - af || bw - aw;
      }));
    }
    st.P = { data, by, where, grids };
    st.emit();
  };

  /* ── the note editor ─────────────────────────────────────────
     One dialog for every note in the tool: a rune alternative's, a shard's, an
     item's. A `prompt()` would have been fewer lines and is what the rest of this
     file uses for a one-word answer like a set name, but a note is a sentence or
     two of guidance you write once and read for a season, and a prompt gives you
     one line you cannot read back. Resolves to the trimmed text, or null when the
     dialog was cancelled or escaped - null means "leave what was there".

     The dialog is static markup (NoteDialog below) that is filled in by hand here, as
     it always was: a form method=dialog owns its own open/close, and React never
     re-renders it, so what this writes stays written. */
  st.askNote = ({ title, why, value = '' }) => {
    const $ = id => document.getElementById(id);
    const dlg = $('noteDlg');
    return new Promise(resolve => {
      $('noteTitle').textContent = title;
      $('noteWhy').textContent = why || '';
      $('noteText').value = value || '';
      dlg.addEventListener('close', function done() {
        dlg.removeEventListener('close', done);
        resolve(dlg.returnValue === 'ok' ? $('noteText').value.trim() : null);
      });
      dlg.showModal();
      $('noteText').focus();
    });
  };

  const NoteDialog = memo(function NoteDialog() {
    return (
      <dialog className="notedlg" id="noteDlg" aria-label="Note">
        <form method="dialog">
          <h3 id="noteTitle">Note</h3>
          <p id="noteWhy"></p>
          <textarea id="noteText" placeholder="When would you take this, and why?"></textarea>
          <div className="actions">
            <button type="submit" value="">Cancel</button>
            <button type="submit" className="btn-primary" value="ok" id="noteOk">Save the note</button>
          </div>
        </form>
      </dialog>
    );
  });

  /* ── the rune page's data model ────────────────────────────────────────────
     The whole tree comes from static/runes.json (5 trees x rows 0-3, plus the 7
     stat shards filed at tree 0 row 4), so every rune is pickable whether or not
     coachless measured it. The WPA figures are an overlay on that list, never its
     source: a picker that only offered measured runes would silently hide the ones
     nobody in the sample took, which is exactly the choice you might be making.

     coachless keys its rune readings BY KEYSTONE, and that is not a storage
     detail - a minor rune's WPA only means anything under the keystone it was
     taken with. So changing the keystone repaints every figure on the page. */

  /* The client's three shard rows, hardcoded because coachless only returns the
     shards people actually took and the rows overlap: Adaptive Force sits in two
     of them and Health Scaling in two others, so a row rebuilt from the data would
     come out short and in the wrong order. */
  const SHARD_ROWS = st.SHARD_ROWS = {
    offense: [5008, 5005, 5007],
    flex:    [5008, 5010, 5001],
    defense: [5011, 5013, 5001],
  };
  st.TREE_IDS = [];   // filled by boot(), once the rune index has loaded
  st.runesIn = (tree, row) => Object.entries(st.RUNEDEX.runes || {})
    .filter(([, v]) => v.tree === tree && v.row === row)
    .map(([id, v]) => Object.assign({ id: +id }, v));

  /* `alts` is the qualitative half of a rune page: the picks you did NOT take, and
     the sentence saying when you would. Two shapes in one list, told apart by
     `slot`, because they are the same idea at two sizes:

       { slot: 'p2'|'s1'|'shard:flex'|..., id, note }   one rune or shard swapped
       { slot: 'secondary', tree, sec: [id, id], note } the whole second tree swapped

     `slot` is verbatim the picker's own `data-slot`, so reading an alt back to the
     thing it replaces reuses the click handler's routing table rather than a second
     copy of it. The keystone and the primary tree have no alt: a different keystone
     is a different build, and the build list already versions those separately. */
  st.blankRunes = () => ({
    primary: null, keystone: null, rows: [null, null, null],
    secondary: null, sec: [], shards: { offense: null, flex: null, defense: null },
    alts: [],
  });
  st.R = st.blankRunes();

  const ksEntry = st.ksEntry = () => current()?.runes?.byKeystone?.[String(st.R.keystone)] || null;
  st.ksFig = id => (current()?.runes?.keystones || []).find(k => +k.id === +id) || null;

  st.figFor = (tree, row, id) => {
    const packed = ksEntry()?.trees?.[String(tree)];
    if (!packed) return null;
    const list = [packed.rowOnes, packed.rowTwos, packed.rowThrees][row - 1] || [];
    return list.find(r => +r.id === +id) || null;
  };
  st.shardFig = (row, id) =>
    (ksEntry()?.shards?.[row] || []).find(r => +r.id === +id) || null;

  /* An empty page opens on what this champion's games actually did: the most-taken
     keystone and the most-taken rune under it in each row. A starting point you
     overwrite, not a recommendation - most-taken is not best, which is why the
     figures stay on screen while you change it. */
  const mostTaken = st.mostTaken = list => (list?.length)
    ? +list.reduce((a, b) => (b.n > a.n ? b : a)).id : null;

  /* The three rows under a keystone are measured under THAT keystone, so a switch
     cannot carry the old picks forward. Re-reading them beats blanking them: an
     empty row is three more clicks and hides what this keystone is usually paired
     with, which is the reading you switched keystones to see. */
  st.seedRowsForKeystone = () => {
    const packed = ksEntry()?.trees?.[String(st.R.primary)];
    st.R.rows = [mostTaken(packed?.rowOnes), mostTaken(packed?.rowTwos), mostTaken(packed?.rowThrees)];
  };

  st.seedRunes = () => {
    const R = st.R;
    const data = current();
    const ks = data?.runes?.keystones || [];
    if (!ks.length || R.keystone) return;

    const broken = ks.filter(k => data.runes.byKeystone?.[String(k.id)]);
    R.keystone = mostTaken(broken.length ? broken : ks);
    R.primary = runeMeta(R.keystone)?.tree ?? null;
    st.seedRowsForKeystone();

    const e = ksEntry();
    const pick = [...(e?.secondary || [])].filter(s => s.tree !== R.primary)
      .sort((a, b) => b.share - a.share)[0];
    R.secondary = pick ? pick.tree : null;
    const second = e?.trees?.[String(R.secondary)];
    R.sec = [mostTaken(second?.rowOnes), mostTaken(second?.rowTwos)].filter(Boolean);

    for (const [row, allowed] of Object.entries(SHARD_ROWS)) {
      const taken = (e?.shards?.[row] || []).filter(r => allowed.includes(+r.id));
      R.shards[row] = mostTaken(taken) ?? allowed[0];
    }
  };

  /* A page with nothing on it saves as no page at all, so a set built for its items
     alone does not carry an empty rune object around forever. */
  st.runePayload = () => {
    const R = st.R;
    const any = R.keystone || R.rows.some(Boolean) || R.sec.length
      || Object.values(R.shards).some(Boolean);
    return any ? structuredClone(R) : null;
  };

  /* Rune edits mutate R, which persist() never sees - so the rune half of the
     autosave hangs off the render every rune mutation already calls. The picker itself
     is derived from R, so "render" is the autosave plus an emit. */
  st.renderRunes = () => {
    st.autosave();
    st.emit();
  };

  /* ── page boot ────────────────────────────────────────────────────────────────
     The state half of the plain page's bottom-of-file sequence, in its order. Call it
     once after st.ready and before the first render; the DOM half (select options, the
     back link, shelves, the rune columns) is derived from what this leaves behind. */
  st.boot = () => {
    st.TREE_IDS = Object.keys(st.RUNEDEX.trees || {}).map(Number).sort((a, b) => a - b);
    st.S = st.restore() || st.blank();
    st.loadMeta();
    st.fillRoleSelect();   // fillChampSelect() ended in this: it also puts M.role on a real role
    st.bootSet();
    // arriving on /c/<champ>/<role>/build means the set is for that champion, same
    // as picking them from the dropdown does
    st.attachChamp();
    st.saveMeta();         // also normalises the address bar when the pick came from storage
  };

  /* The plan page's options. It reads its figures out of the two bakes this page
     already holds, and borrows the formatters rather than copying them: a second
     fmtWpa in a second file is a second answer to "is +0.5 good" the first week one of
     them changes. The plan is held on S like everything else, so onChange is the same
     persist() every other mutation on the page goes through and autosave rides it. */
  st.planConfig = root => ({
    root, champs: st.CHAMPS, ver: st.BAKED.ver, askNote: st.askNote,
    getPlan: () => st.S.plan,
    getRole: () => M.role,
    getChampion: () => M.champ,
    onChange: st.persist,
    getFigures: () => ({ cl: st.STATS.champions[M.champ]?.roles?.[M.role] || null, lo: lola() }),
    fig: { MIN_GAMES, fmtWpa, wpaClass, fmtWr, wrClass, games, base: lolaBase },
  });

  /* Mounted after M exists and before the first renderMeta(), which calls into it.
     `root` is the rendered #step3 element. Call from an effect once the page body is in
     the DOM. */
  st.afterMount = _root => {
    /* The plan page is React now (loadout.jsx): it repaints off the store, so there is
       nothing to mount into `root` and st.PLAN stays the no-op default. */
    st.renderAll();
    st.renderMeta();
    st.showStep('items');   // items lead; the rune page is one click away
  };

  /* Everything a champion/role change repaints. The shop figures, the blocks' hover
     figures and the crossed reading all hang off it. */
  st.renderMeta = () => {
    st.seedRunes();      // no-op once a page has been picked or loaded
    st.renderRunes();
    st.paintItems();
    st.renderBlocks();   // slot tooltips carry this champion's figures, so they repaint too
    st.renderPatch();
    st.PLAN.render();    // pathing shows on role, and bans are keyed by champion
    st.applyFilters();   // RATED just changed, so the meta filter has to re-run
  };

  // naming a champion to read stats for is also saying the set is for them
  st.attachChamp = () => {
    const c = st.CHAMPS.find(x => x.n.toLowerCase() === M.champ.toLowerCase());
    if (!c || st.S.champs.includes(c.k)) return;
    st.S.champs.push(c.k);
    st.emit(); st.persist();
  };

  /* ── components ────────────────────────────────────────────────────────────── */
  /* The .buildhead strip: what this set IS - its name, its champion, its role. The
     back link retargets itself to the champion you are building for, so its label
     changes as you work. `Champions` in the bar is the fixed way home; this is the
     contextual way one level up. */
  function Roles() {
    st.useStore();
    const champIn = useRef(null);
    const ready = st.loaded && !!st.S;
    /* The "also applies to" box listens for the native `change` event, not React's
       onChange (which is the input event): picking a champion out of the datalist, or
       typing a full name and tabbing away, commits it, and a name that is a prefix of
       another ("Vi", "Viego") must not commit while it is still being typed. */
    useEffect(() => {
      const el = champIn.current;
      if (!el) return undefined;
      const on = e => {
        const want = e.target.value.trim().toLowerCase();
        const c = st.CHAMPS.find(x => x.n.toLowerCase() === want);
        if (c && !st.S.champs.includes(c.k)) { st.S.champs.push(c.k); st.emit(); st.persist(); }
        e.target.value = '';
      };
      el.addEventListener('change', on);
      return () => el.removeEventListener('change', on);
    }, [ready]);
    if (!ready) return null;

    const back = backLink();
    const names = Object.keys(st.STATS.champions).sort();
    const roles = st.rolesFor(M.champ);
    return (
      <section className="buildhead">
        <a className="back" id="back" href={back.href} aria-label="Back to the champion list">{back.text}</a>
        <input id="title" placeholder="Set name" aria-label="Set name" value={st.S.title} readOnly={!!st.LOCKED}
               onChange={e => { st.S.title = e.target.value; st.emit(); st.persist(); }} />
        {st.LOCKED && <span className="locked-tag" role="status">Auto · read-only</span>}
        {st.LOCKED && <button type="button" id="copyAuto" className="btn-primary"
                              onClick={() => { st.copyAuto(); }}>Copy to my builds</button>}
        <select id="metaChamp" aria-label="Champion" value={M.champ} onChange={e => {
          M.champ = e.target.value;
          st.fillRoleSelect();
          st.saveMeta();
          st.renderMeta();
          st.attachChamp();
        }}>
          <option value="">Champion{'…'}</option>
          {names.map(n => <option value={n} key={n}>{n}</option>)}
        </select>
        <select id="metaRole" aria-label="Role" disabled={roles.length === 0} value={M.role}
                onChange={e => {
                  M.role = e.target.value;
                  st.saveMeta();
                  st.renderMeta();
                }}>
          <option value="">Role{'…'}</option>
          {roles.map(r => (
            <option value={r} key={r}>{`${r} · ${(st.STATS.champions[M.champ].roles[r].n / 1000).toFixed(0)}k`}</option>
          ))}
        </select>
        <input id="champIn" list="champList" placeholder="Also applies to..."
               aria-label="Add another champion this set applies to" ref={champIn} />
        <datalist id="champList">{st.CHAMPS.map(c => <option value={c.n} key={c.k} />)}</datalist>
      </section>
    );
  }

  /* The shop legend: which games the figures on the tiles are drawn from, and the
     toggle that narrows the shop to the items with a reading. It sits inside the shop
     column (ForgeUI.Shop renders it). */
  function Readings() {
    st.useStore();
    return (
      <div className="shop-legend" id="shopLegend" hidden={!st.P.data}>
        <b id="metaWhere">{st.P.where}</b>
        <button type="button" id="metaOnly" aria-pressed={String(F.metaOnly)} onClick={() => {
          F.metaTouched = true;   // your choice now outranks the default on every repaint
          F.metaOnly = !F.metaOnly;
          st.emit();
        }}>Only items with a reading</button>
      </div>
    );
  }

  UI.Roles = Roles;
  UI.Readings = Readings;
  UI.NoteDialog = NoteDialog;
})();
