/* forge-shop.jsx - the Forge builder's page state module and its shop, as React.

   Straight port of the first part of forge.html's main <script type="module">: loading
   the seven bakes, shelving the catalog, the stat rail, the filters, the inspector's
   formatting helpers and the persistence the whole page leans on. Behaviour is the plain
   page's, quirks included (see the comments where they bite).

   INTERFACE NOTE (for forge-blocks.jsx, forge-stats.jsx and Task 22)
   -------------------------------------------------------------------
   Every file is an IIFE that assigns into window.ForgeUI. This file creates ForgeUI.state
   (`st` below), the page's single mutable store. State is mutated in place, exactly as the
   plain page mutated its module variables, and a mutation ends in st.emit(), which
   re-renders every component that called st.useStore(). Components derive their markup
   from st on each render; nothing paints DOM by hand except the drag classes
   (.over/.before/.dragging) and the hover card.

   Data, set once by st.ready (a promise, resolved when the seven bakes and ForgeLib are in;
   st.loaded is true after): BAKED, STATS, RUNEDEX, DIFF, LOLA, SETS0, PASSIVES, ITEMS,
   CHAMPS, BY_ID, BY_KEY, HAYSTACK, LIVE_PATCH, PARAMS (the query string, read at load).
   Page state, reassigned freely so always read off st: S (the set: title, champs, active,
   plan, blocks), R (the rune page), OWNED (the library row this session writes), SAVES,
   INSPECT, COND (the crossed reading), P (the shop paint snapshot), step.
   Stable objects: M (champ, role), F (q, stats, metaOnly, metaTouched), RATED.
   Transient flags: savedFlash (Save button reads "Saved"), copied (Copy reads "Copied").

   Hooks other files call, with the file that defines them:
     forge-shop    persist autosave markSaved blank restore emit useStore subscribe
                   clearFilters esc plural games statsDL withRatios figsHTML
                   showStep (default, Task 22 may refine) renderPatch (default no-op)
                   PLAN (default {render(){}}, Task 22 replaces it after mounting #step3)
     forge-blocks  inspect addToBlock moveItem renderBlocks sync renderAll buildSet
                   saveSet fetchSaves loadSet bootSet
     forge-stats   boot afterMount planConfig renderMeta renderRunes seedRunes blankRunes
                   runePayload askNote loadMeta saveMeta attachChamp current coachItem
                   coachItems lola lolaItem lolaRune lolaBoot lolaBase lolaRuneBase
                   keystoneSpread coachSlots itemCardHTML seedRowsForKeystone readingLabel paintItems
                   condState coreSlot refreshConditioned runeMeta treeMeta ksEntry
                   ksFig figFor shardFig fmtWpa wpaClass fmtWr wrClass ordinal MIN_GAMES
                   rolesFor fillRoleSelect SHARD_ROWS TREE_IDS runesIn mostTaken

   Components (props): ForgeUI.Shop({hover}) the stat rail and the shop column, two siblings
   for <main>; ForgeUI.Blocks({hoverSlots, hoverNodes}) the "Your set" column with the
   inspector, blocks, export and saved sets; ForgeUI.Roles() the .buildhead strip;
   ForgeUI.Readings() the shop legend (rendered inside Shop); ForgeUI.NoteDialog() the
   #noteDlg markup, rendered once by the mount. The hover props are objects of optional
   React handlers {onMouseOver, onFocus, onMouseLeave, onBlur, onScrollCapture, onDragStart}
   that Task 22's hoverCards helper builds; they land on #shelves, #blocks and #inspect.

   Task 22 wiring: render <ForgeUI.Bar> (children: <span id="statsPatch">{st.statsPatchLabel()}
   </span>, <span id="patch">{st.patchLabel()}</span>), <ForgeUI.Roles/>, the step nav and
   #step1/#step2/#step3 sections, <main><ForgeUI.Shop/><ForgeUI.Blocks/></main> inside
   #step2, <ForgeUI.NoteDialog/>; wait for st.ready, call st.boot() before the first render,
   then st.afterMount(document.getElementById('step3')) from an effect. */
window.ForgeUI = window.ForgeUI || {};

(() => {
  const { memo } = React;
  const UI = window.ForgeUI;
  const st = UI.state = UI.state || {};

  const lib = () => window.ForgeLib;
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;' }[c]));
  const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
  const games = n => n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n);
  st.esc = esc; st.plural = plural; st.games = games;

  /* ── the store ──────────────────────────────────────────────────────────────
     One version counter. useSyncExternalStore re-renders a subscriber whenever it moves,
     and a component reads whatever it needs off st while rendering. */
  st.v = 0;
  const subs = new Set();
  st.subscribe = fn => { subs.add(fn); return () => { subs.delete(fn); }; };
  st.snapshot = () => st.v;
  st.emit = () => { st.v++; subs.forEach(fn => { fn(); }); };
  st.useStore = () => React.useSyncExternalStore(st.subscribe, st.snapshot);

  /* Read before anything rewrites the address bar - saveMeta() normalises the
     path and drops the query with it. */
  st.PARAMS = new URLSearchParams(location.search);

  /* ── load ────────────────────────────────────────────────────────────────────
     The head snippet started the seven fetches; this waits on them (and on the ES-module
     bridge, which normally ran first) and then does the one-time work the plain page did
     under its top-level await. A promise chain, not async/await: Babel's async helpers
     would become top-level globals. */
  const libReady = () => window.ForgeLib
    ? Promise.resolve()
    : new Promise(res => window.addEventListener('forgelib:ready', () => res(), { once: true }));
  const PRE = window.__FORGE;
  st.loaded = false;
  st.ready = Promise.all([PRE.catalog, PRE.stats, PRE.runes, PRE.diff, PRE.lola, PRE.sets,
    PRE.passives, libReady()]).then(r => { init(r); return st; });

  /* ── shelving ────────────────────────────────────────────────────────────
     Riot's `depth` is not the shop's tier and its tags are not the shop's aisle, which is
     how v4 filed Infinity Edge and Rabadon's as components (depth 2), Mejai's likewise,
     Stormsurge as a support item (it carries GoldPer for its takedown gold) and Gunmetal
     Greaves as a legendary (tier-3 boots carry no Boots tag). The build graph is the honest
     signal, so this reads it instead:

       nothing builds out of it + it has parts  -> Legendary, the finished item
       it builds into something + it has parts  -> Epic component
       it builds into something, made of nothing -> Basic component
       boots                                     -> anything reachable from a Boots-tagged
                                                    item, tier = how deep in that chain
       nothing either way                        -> a shelf item: ward, potion, support
                                                    starter, jungle pet or lane starter    */
  const SHELVES = ['Utility', 'Boots', 'Components', 'Legendary'];
  const SUBS = {
    Utility: ['Starter items', 'Potions', 'Wards', 'Support items', 'Jungle pets'],
    Boots: ['Tier 1', 'Tier 2', 'Tier 3'],
    Components: ['Basic', 'Epic'],
    Legendary: ['Legendary'],
  };
  const SHELF_BLURB = {
    Utility: 'what you open on and what you top up with',
    Boots: 'tier one, the upgrades, and the tier three finishers',
    Components: 'parts that build into something bigger',
    Legendary: 'finished items, nothing builds out of them',
  };

  function init(r) {
    st.BAKED = r[0]; st.STATS = r[1]; st.RUNEDEX = r[2]; st.DIFF = r[3]; st.LOLA = r[4];
    st.SETS0 = r[5]; st.PASSIVES = r[6];
    /* Before ITEMS is read by anything: the catalog's own passive text has the numbers
       templated out by Data Dragon, and this puts Riot's back in. Done once here rather
       than at the places that render `ps`, and before HAYSTACK, so the filled-in
       ratios are searchable too. */
    const ITEMS = st.ITEMS = lib().applyPassives(st.BAKED.items, st.PASSIVES);
    st.CHAMPS = st.BAKED.champs;
    const BY_ID = st.BY_ID = new Map(ITEMS.map(i => [i.id, i]));
    st.BY_KEY = new Map(st.CHAMPS.map(c => [c.k, c]));
    st.HAYSTACK = new Map(ITEMS.map(i => [i.id,
      [i.n, i.p, ...i.t, ...i.st, ...i.ps.flatMap(b => [b.h, b.t])].join(' ').toLowerCase()]));

    /* A save is stamped with the LIVE patch, not the statistics patch: coachless
       trails the game by one, and filing today's build under 16.15 while the game
       is on 16.16 puts it in the wrong bucket on the day it is made. */
    st.LIVE_PATCH = lib().shortPatch(st.BAKED.ver);

    const BOOTS = new Set(ITEMS.filter(i => i.t.includes('Boots')).map(i => i.id));
    for (let pass = 0; pass < 4; pass++)
      for (const i of ITEMS) if (i.f.some(c => BOOTS.has(c))) BOOTS.add(i.id);

    const bootTier = i => {
      let n = 1;
      const seen = new Set(), q = [...i.f];
      while (q.length) {
        const x = q.pop();
        if (BOOTS.has(x) && !seen.has(x)) { seen.add(x); n++; q.push(...(BY_ID.get(x)?.f || [])); }
      }
      return n;
    };
    const classify = i => {
      const T = new Set(i.t);
      if (T.has('Trinket') || (T.has('Vision') && T.has('Consumable'))) return ['Utility', 'Wards'];
      if (T.has('Consumable')) return ['Utility', 'Potions'];
      if (T.has('GoldPer') && !i.f.length) return ['Utility', 'Support items'];
      if (i.t.length === 1 && T.has('Jungle')) return ['Utility', 'Jungle pets'];
      if (BOOTS.has(i.id)) return ['Boots', `Tier ${bootTier(i)}`];
      if (!i.f.length && !i.to.length) return ['Utility', 'Starter items'];
      if (!i.to.length) return ['Legendary', 'Legendary'];
      return ['Components', i.f.length ? 'Epic' : 'Basic'];
    };
    for (const i of ITEMS) [i.sh, i.k] = classify(i);

    /* The shop's layout, fixed for the page: which sub-shelves exist and which items
       sit in each grid, in catalog order (shelf, then gold, then name). paintItems
       re-sorts a copy of each grid by reading; this is the order it starts from. */
    const order = new Map(SHELVES.map((s, n) => [s, n]));
    const sorted = [...ITEMS].sort((a, b) =>
      order.get(a.sh) - order.get(b.sh) || a.g - b.g || a.n.localeCompare(b.n));
    st.LAYOUT = SHELVES.map(s => {
      const subs2 = SUBS[s].filter(k => ITEMS.some(i => i.sh === s && i.k === k));
      return { s, subs: subs2, flat: subs2.length === 1 };
    });
    st.GRID = new Map();
    for (const i of sorted) {
      const key = `${i.sh}|${i.k}`;
      if (!st.GRID.has(key)) st.GRID.set(key, []);
      st.GRID.get(key).push(i.id);
    }
    st.SAVES = st.SETS0.sets || [];   // already fetched up top; fetchSaves() is for refreshes
    st.loaded = true;
  }

  /* The client opens you on what your role can actually start with, and the three
     openings are mutually exclusive: a jungler starts on a pet, a support starts on
     World Atlas, a laner starts on a Doran's or a Dark Seal. None of the three is a
     choice the other two have, so the shop hides the two aisles that are not yours
     rather than making you scroll past them on every build.

     Only these three sub-shelves are role-bound; everything else is bought by
     everyone. With no role picked - a set built for no champion - nothing is
     hidden, because there is no role for anything to be relevant to. */
  const ROLE_SUBS = {
    'Support items': ['support'],
    'Jungle pets': ['jungle'],
    'Starter items': ['top', 'mid', 'bot'],
  };
  const M = st.M = { champ: '', role: '' };
  const roleAllows = i => {
    const roles = ROLE_SUBS[i.k];
    return !roles || !M.role || roles.includes(M.role);
  };

  /* ── stat rail: the client's shop filter. Each row is one or more Riot tags, and
     checking several narrows, exactly like the shop's own checkboxes. ───────── */
  /* Riot ships every one of these as a named file: it is a TEXT-ICON set, the glyphs the
     client drops inline into tooltips, under
     plugins/rcp-be-lol-game-data/global/default/assets/ux/fonts/texticons/lol/statsicon/.
     The file name settles which glyph is which where the picture does not (`scalels` IS the
     crossed drop and `scalesv` IS the fangs, which is how Life Steal and Omnivamp got read
     backwards off a contact sheet). Inlined as data URIs, so the rail costs no request and
     cannot break on a dead CDN path.

     Riot ships them at 20x20 and nothing larger exists, so resolution is not the lever; the
     number of times the art is resampled on the way to the screen is. These are baked by
     bake_glyphs.py at 44x44, exactly 2x the largest box a glyph is drawn in (22px rail,
     20px inspector, 18px hover card), so a 1x screen halves it cleanly and a 2x screen
     draws it 1:1. Each glyph is cropped to its own alpha bounds, scaled so its LONG side is
     40, and centred, because Riot's tiles are not consistently inset (onhit, scalems and
     scaletenacity run edge to edge and read ~11% larger than the rest).

     The one glyph that is not Riot's is the Capstone crown: the client has no crown in this
     idiom anywhere (`scalecapstone` is Arena's chevron), so it is drawn on the same 20px
     grid in the set's own gold. Nothing else here is hand-made. */
  const GLYPH = {
    "Attack Damage": "data:image/webp;base64,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",
    "Critical Strike": "data:image/webp;base64,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",
    "Attack Speed": "data:image/webp;base64,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",
    "On-Hit Effects": "data:image/webp;base64,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",
    "Armor Penetration": "data:image/webp;base64,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",
    "Life Steal": "data:image/webp;base64,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",
    "Omnivamp": "data:image/webp;base64,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",
    "Ability Power": "data:image/webp;base64,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",
    "Magic Penetration": "data:image/webp;base64,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",
    "Mana": "data:image/webp;base64,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",
    "Mana Regen": "data:image/webp;base64,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",
    "Ability Haste": "data:image/webp;base64,UklGRi4JAABXRUJQVlA4TCIJAAAvK8AKEDXRtbZ/lZ1w57mf3ERuACd6bM7s///3++89GvdkH5nZ0Qv4YiXuDhUpsyihdi19NovW3a3NNeDuULq7XoA78aTC3b1114ouNafDHSIdGg/u7ta5u54uKyUSmQrXLhncKemokrCW5EaSHEmKnemurvDIql7OOXntcxU4JVaf0/eEOMmRJDmSU6cJlII+0AdKnAL3BOdsd7sisnpvwJmZLNq2TTka5Ypt27a/2rY7tm3btm3bNgttp21FhZfDwG0jRc3iMbZ/QEkMIaN5c0Im4TEjhIkgWzQvSraYMRyOJF8TALgQrr7aQFAI4bAOsNvVRcluI4fD5ZOvCQAMAm4AD4AbwQBIksuAK8LVV7dr545gSbslr756yV+TtJLHQNlXTgUAJtuUUJR5zuSrgqMwI53NT8bXTKiEJMYdJqTuKUOypHsi5MaNp9nrjdHDL9zX4Z8jAEARG8F2okwYm1bl3o0o/KPMrDLZ5HjKjG2DBjJjR4w9oQMxDkntJDVr1qQx9jfffHODBgumKJgtHWHY5diiklBiO74JAKYKo6lYqJ2V2fqx2YkwflZQ6uJ8Ro6Dr06d9Cq8qcKl+1NYU7dYC9q3alWnzucPKiwdIcK4zRlfdzspmSpiHQQQpeGUiQ2bVUJE4ntOknxZGihK9GwNBQkEuyEiq3Jcrd2SA0HE9S0liTv33gxJ/MSQ6yosTL0nApkuw3G7qVeEKL0mVHvW1C3x2WfLVnPoPbFznVjL9wfA1ImVa1umEH4MMW7I2m5ej0SgTD3BNxENLYphbMlhV/wlK10U76jb74JI/1141ZeMxPNkvAiDlPGUxE253ZPg3q4tKAlWxoOyTkTVN4HOfwoH4/qH8OOM/d7uzwjHbUpC9bRmk3IAYOoG5VARtXXUlQkmXA9lC4cUyAzhYqIAU4Xy6Iv4fkwvL8r4VGaoyj5heDLhF0wogxDuUlyUMSAeRWy4h0oySZY1b/OuHoxOZNnoBqoatXM7+18oALA7V+GULtKqtw2bsVD+FeD4T2RatJErjtMrt238e8rO6Ky85sIFFsAUUOjQkAvgq4JHYNOCxwZVAQpLsnSNOh9OU4/Qn2uZ2zIO6gRMDagIMhnjjLXqF+lKNgCYKmwaFVppsTExICwi/JmvNRiASEJxVgqM2aey7h95wBUVDtYUJrwBTG2o7wPYIF8DTAU2kDULFDy5RhXZdeLnyjUtqZX4wotgSmCgka1SjqG6XWwVTN3hAGBIQJsHr4x2MhmVyZ4LQAFNJSRZpoq5jCsBlL5HYVzH3wbSIhEdaIy/bxc1jp6L15yJl+8cmFOlSIfXjEwDj730HuEKGU/5cPABAYvrAKYKLYeKqmNHZkCnDwosC/ywL3AuLgSLtCYgfZIQ4aEynQq/5EzDxINS0ukcsY7frzKA3paGA0IlWfUBs8DSoMOePhzQKu6qLfW0v4UB+gMAG98DThTVe7sQLLkByQ7A+IvNiAjeWi7qaf4WGs79I8/NFKbZMD/+++Zun+958O98IuPNdoTJr4rzsHtJ1rhkuowo8D1sIGiImcnLy+Oe8BnaxTnW/qnBUPTEI3Z8VQTcTSVOB5BpD29nTOQBrVrDkfYTdjhH6+//+2DfDeMieDnGqARcWhA2gDouFDHcrsrs/F/osIDwh1bpdM6xEf4pDlOfWAYWcHZnb7uo9YqxhfWRMELOr/xrQ57eoGCbK67xlz9ETD3GALBhUVolPQhnXdREJyFbWMu79B8/gHe7viFslbVvifMRrxP1VQTnfs/z37OO1yK6NhQEOhEM+Zufz8zVei8bTRYxIy5XLaClqSd4G1Z0D6BrLTaxjrELo92GlNsNBU4OGiVfZZLPhaVbLzhSgZbxl4rQ8JIoa9j8yH/YjJwBjPhUjWTH7cepbp+LB0Da34cYWMs2VdhKSH9V7DF1veKYGc/tZpr6D7looDglZh7K8y2R+EWhnDYPebHrLJP5RU39gVzAjJszHTX33cz33/hRaR37e2t9n6zM98W/7yuXjr3oj2Lo7NzvZfsDDhYe8cElM/XE8bkN8/eYypX0V7Anq3trnQRgorh9Tm1lwLNFJzxNVGq0kcuTm7rDff/9wb6zzaXV1YpIwVgXLODpTXLR0WJdxuMCsJZd7mDgkU7X52rs+RH8m58oDhA6GvNeTt0utu9bV7Lnd6OoFu+ISmvWdV6dmXfpP6doNiH6fNSAlq1sWB+o5XdHH/TpESfLOCTmeKta6gBaVwIQPZGXwUZC+2kFj8D/IyceqI71geoAcIxRaeHG8T7zbg05Wn/TKkPRczy1jDrdn1mRtD6tCoNUpP9+infuyMWNdtIqgzkaPy72Is0VJ0TiNbPVN2Dje8DJJ1FGFzZLbkQqzkXJkJjxiqpRtYH2QMB2tmN8UxFze6k4xPir4maES6tnuvwhavFt9QccPKwk7kYxoONegQXwGUTgWtzYQfpZa0apCMD3AarTvQ3H6wOiOPuhFTu3vzBzPnNYYGnQ4UDigDaudnKo+H3QsBwgHw4+cjyJrHhh7zEiiI6vCYvlGJNWQDoVFqkAkIqkT6qVE/VpW2mMFCZ0I4JM9kTNqIx22jx4gSEBYP40KvQjw5GtYqSZCiws7XNnpYrN9az7wQu7UisE0dpUYW14NJxMn3aSPEKSHpH/lx3q/Z4qrAMAdiW/3kur3jYj3WFqQEcg7BOVq9n0hc8G7AoWb8UGsFg8npeZRg7/CiwNhAjHUc5Y+3SWqmQDQOq5qi11o3UQ2+XR864cyMpbxUpw7ksW9rmVbEsqOfSemPgXXUJJKNPkHPRBiCprRgxUbdTONXWDCvQaEbTIhjHsEB7fxdhvpB/E3HwTxPw9kc6sH0bpNSHqqwhBvPfhmT21Atc3Ab2vOwxd7viTEZiQaCRUb63ZpFywh3F3M1QrxdXPll3fFBuKimdd/WKlQk6yh5G3JBDsjWTXQgS7ChL0s6WBosSX1px1hhDjyuNNgKLx3DqWDBnguRdZeq7RseFNpwAvHzNlQdWxLaW69rVVx86S2rVLlVKOR4oyswFerm86XgYAemd71aCM0DtUNqQh2JKLyBBDDBaUEauuCwAuC8HZ88rVV79SRK6++pXg7Omn+GZacc7KkhcA",
    "Health": "data:image/webp;base64,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",
    "Health Regen": "data:image/webp;base64,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",
    "Armor": "data:image/webp;base64,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",
    "Magic Resist": "data:image/webp;base64,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",
    "Tenacity": "data:image/webp;base64,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",
    "Movement": "data:image/webp;base64,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",
    "Heal & Shield Power": "data:image/webp;base64,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",
    "Gold Per 10 Seconds": "data:image/webp;base64,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",
    "Scales off your stats": "data:image/webp;base64,UklGRiQDAABXRUJQVlA4TBcDAAAvK8AKEJfkNpIkRareJwnV99+lNwIlxi43HDWS5EhRcxbBMTv+APZ53syU40iSHCXnDg3v8wwrMU5rMQ05sm1V1bqGWxLM3dMgE1IiGgLwkbvrl8s9YSlQ2KuDpxcq/IQKhb9Q4S8U2kagoH4kRv24/JJkW3QGgQXBBlo/NjEK8GIp/jMgv1YU9U8TrKgFgi0okGDpFjQIFBDgCwKCAJ4CLFgRlICAA0UBZxIhLERRvykFCgw4cOEs70SQBY2WCyoKc8IHCV+TCEvGEiWkUmNXSoO3PQ2fJLooDZvU/xgRUlkNxxGX9O+YdeuuHuRvMuKahZ4ls5F+xbgm+vNzMcZQirRVBaI2PdAZFf5DF8f31U4WJvfdLrnX7PuYHctKrH1J0z+s2Yli7PnZf0z/VvKMr/2aw28zGJdOLn07l8el95pz2d7/ieezPzv+r7ednLZJ9teDSKTd1nZmjothbdsd22Zt27Ztt/nJD/J2/DFX8txxnkT0fwKMCfjTIMvEj6efV6V+8MOEehowmXy9nDQyvO/BlQ/fJZ7i0qNDmxOVhggkXG098Jj5+Rchq3Egl1o90gk+SACuCpmapefvffyXLUpOzeopIx2kichL7HvW0hqGWpoL9kD8F6dL6soodWyEAsAqaFZlHGos2i0BnCxmimPIJkUhCeq3tt/e9RV/kPNBH78ztMkqIyt0ouNa58BDGvjtql604+22wkXP8RsABqZvebeTCP6WKDYAOLBU4L3VItJ962tfPfmFm9/ODa6p0mVEpG03jb/BsJ6Etev7dJkE1a9ueIYvuDZz3na1k7hQkWdfM2Ik7mqH5G65Nx6/Ma6ueF9eJulHKxTeONq9ZYJ2UtvcM38uL9vRLGNpO/FcJySQiX7aMOMsPi0xE31CkDplvhmipnXD+49tJJMuwuE4Ib7Uznd26YJWM17i2j4yQbqhs5JMp8rVlJH/P3GoGJn1vJUjcVW8toXTNRK7/V7N+TkSX7+8cLeaGaHXpy1k9o7Egw9P3D/LlI7ExXlHDW7nSOyYc+TDC6ZsJHbOPow/UwsTbQA=",
  };

  /* A row is either a list of Riot item tags - the shop's own checkboxes - or a
     predicate, for the two things Riot has no tag for. */
  const CAPSTONE = new Set([
    '3089',  // Rabadon's Deathcap    total AP x1.3
    '3003',  // Archangel's Staff     AP from bonus mana
    '3004',  // Manamune              AD from bonus mana
    '3119',  // Winter's Approach     health, then a shield, off max mana
    '2526',  // Whispering Circlet    heal and shield power off max mana
    '6621',  // Dawncore              heal and shield power + AP off base mana regen
    '4633',  // Riftmaker             AP from bonus health
    '2501',  // Overlord's Bloodmail  AD from bonus health
    '3053',  // Sterak's Gage         AD and the lifeline shield off bonus health
    '3084',  // Heartsteel            damage off max health
    '3748',  // Titanic Hydra         damage off max health
    '3083',  // Warmog's Armor        bonus health off item health, regen off bonus health
    '2525',  // Protoplasm Harness    shield and heal off max health
    '6665',  // Jak'Sho, The Protean  +30% of your bonus armor and MR
    '2517',  // Endless Hunger        ability haste off bonus AD
    '3170',  // Swiftmarch            adaptive force off move speed
  ]);

  const STAT_GROUPS = [
    ['Attack', [
      ['Attack Damage', ['Damage']],
      ['Critical Strike', ['CriticalStrike']],
      ['Attack Speed', ['AttackSpeed']],
      ['On-Hit Effects', ['OnHit']],
      ['Armor Penetration', ['ArmorPenetration']],
    ]],
    ['Magic', [
      ['Ability Power', ['SpellDamage']],
      ['Magic Penetration', ['MagicPenetration']],
      ['Mana', ['Mana']],
      ['Mana Regen', ['ManaRegen']],
      ['Ability Haste', ['AbilityHaste', 'CooldownReduction']],
    ]],
    ['Defense', [
      ['Health', ['Health']],
      ['Health Regen', ['HealthRegen']],
      ['Life Steal', ['LifeSteal']],
      ['Omnivamp', ['SpellVamp']],
      ['Armor', ['Armor']],
      ['Magic Resist', ['SpellBlock', 'MagicResist']],
      ['Tenacity', ['Tenacity']],
    ]],
    ['Utility', [
      ['Movement', ['Boots', 'NonbootsMovement']],
      // Riot ships no tag for it, so the row reads the stat line the item already prints
      ['Heal & Shield Power', i => i.st.some(t => t.endsWith('Heal and Shield Power'))],
    ]],
    /* Not a stat you buy - a stat that buys itself off the rest of your sheet. Sterak's
       is bonus health turned into AD and a shield, Jak'Sho is your resistances turned
       into more of themselves. Which of these is worth a slot depends entirely on what
       is already in the other five, which is exactly the question a set is answering,
       and no Riot tag marks any of them. Hand-kept: check it when a patch reworks one. */
    ['Capstone', [
      ['Scales off your stats', i => CAPSTONE.has(i.id)],
    ]],
  ];
  const STAT_TAGS = new Map();
  for (const [, rows] of STAT_GROUPS) for (const [label, tags] of rows) STAT_TAGS.set(label, tags);

  /* The block skeleton every build starts from - the PTA Shyvana jungle set's
     shape, promoted to the default because it is the one that answers "what do I
     buy" in every game state: the pet, the consumables, the four boots, the early
     components, what you always build, what comes after it, the situational picks,
     then armour and magic resist kept apart so the defensive answer is one shelf
     and not a scan of a mixed pile, and the sixth-item capstone last. Empty blocks
     cost nothing and a named empty block is a prompt; a build that needs fewer
     deletes the ones it does not use. */
  const DEFAULT_BLOCKS = [
    'Starting Items', 'Utility', 'Boots', 'Components', 'Core',
    'Post-Core', 'Niche', 'Armor', 'Magic Resist', 'Capstone',
  ];
  st.blank = () => ({
    title: '', champs: [], active: 0, plan: lib().blankPlan(),
    blocks: DEFAULT_BLOCKS.map(type => ({ type, items: [] })),
  });

  /* a view, not part of the document. `metaOnly` narrows the shop to the items
     coachless has a reading for, which is the only way the WPA edges are
     scannable: 107 legendary items with 15 marked is not something an eye can
     sweep, and the whole point of the panel is gauging items at a glance.

     It defaults ON the moment a champion/role has a reading, and paintItems is
     what flips it. Shipping it off buried every number: on Shyvana jungle only
     44 of 195 items carry one and the first sat 1,765px down. `metaTouched` is the
     one thing this needs: once you press the button yourself, your choice is yours
     and the default stops overriding it on every repaint. */
  const F = st.F = { q: '', stats: new Set(), metaOnly: false, metaTouched: false };
  const RATED = st.RATED = new Set();   // item ids with a reading for the current champion/role

  st.S = null;          // set by boot(): restore() || blank()
  st.OWNED = null;
  st.SAVES = [];
  st.INSPECT = null;
  st.INSPECTED = false; // aria-current appears on the tiles after the first inspect(), as before
  st.COND = { key: '', rows: null, asked: null };
  st.savedFlash = false;
  st.copied = false;
  /* The shop's paint snapshot, written by paintItems() (forge-stats.jsx): the reading each
     item carries, the legend sentence, and each grid's reading order. The shop renders off
     this and not off the live bakes, so its figures move exactly when the plain page's
     did - at paintItems - and not whenever something else repaints. */
  st.P = { data: null, by: new Map(), where: '', grids: null };

  /* Defaults for hooks Task 22 owns; the real ones overwrite these. */
  st.PLAN = { render() {} };
  st.renderPatch = () => { st.emit(); };
  st.step = 'items';
  st.showStep = which => {
    st.step = which;
    st.emit();
    if (which === 'plan') st.PLAN.render();   // the champion can have changed under it
    window.scrollTo(0, 0);
  };
  st.applyFilters = () => { st.emit(); };     // filters are derived at render now
  st.patchLabel = () => `patch ${st.BAKED.ver}`;
  st.statsPatchLabel = () => st.STATS.patch ? `stats ${st.STATS.patch}` : '';

  st.restore = () => {
    try {
      const raw = JSON.parse(localStorage.getItem('itemSetForge') || 'null');
      if (!raw || !Array.isArray(raw.blocks)) return null;
      // Storage predates the plan page and a hand-edited entry can be half a shape,
      // so it is normalised on the way in rather than trusted.
      raw.plan = lib().normalisePlan(raw.plan);
      return raw;
    } catch { return null; }
  };
  st.persist = () => {
    // A locked Auto set never reaches storage or the server: any edit snaps back.
    if (st.LOCKED) return st.snapBack();
    try { localStorage.setItem('itemSetForge', JSON.stringify(st.S)); } catch { /* storage full or off */ }
    autosave();
  };

  /* ponytail: autosave rides persist(), which every mutation already calls, rather
     than being wired onto each handler. It writes only a set that is already named
     AND already has a row of its own - before that a save would have to prompt for
     a title, and a prompt on a timer is worse than no autosave. Hit Save once and
     it keeps itself current from then on. Silent: the manual Save still reports. */
  let autosaveT = null, autosaveMute = false;
  function autosave() {
    if (st.LOCKED) return st.snapBack();
    if (autosaveMute || !st.OWNED || !st.S.title.trim()) return;
    clearTimeout(autosaveT);
    autosaveT = setTimeout(() => {
      autosaveMute = true;
      st.saveSet(true).finally(() => { autosaveMute = false; });
    }, 1200);
  }
  st.autosave = autosave;

  /* The one bit of autosave the user sees: the Save button reports it happened,
     so a silent write is still an observable one. */
  let savedT = 0;
  st.markSaved = () => {
    st.savedFlash = true;
    st.emit();
    clearTimeout(savedT);
    savedT = setTimeout(() => { st.savedFlash = false; st.emit(); }, 1600);
  };

  /* ── filters ───────────────────────────────────────────────────────────────── */
  const hasStat = (i, label) => {
    const m = STAT_TAGS.get(label);
    return typeof m === 'function' ? m(i) : m.some(t => i.t.includes(t));
  };

  function matches(i) {
    if (!roleAllows(i)) return false;
    // Utility is exempt: neither source rates a potion, a ward or a
    // starter, and hiding what you open on would make the default unbuildable.
    // Tier 1 and tier 3 boots likewise have no reading for any champion, so the
    // Boots shelf would show tier 2 alone under a blurb promising all three.
    const unratable = i.sh === 'Utility' || (i.sh === 'Boots' && i.k !== 'Tier 2');
    if (F.metaOnly && !RATED.has(i.id) && !unratable) return false;
    for (const label of F.stats) if (!hasStat(i, label)) return false;
    return !F.q || st.HAYSTACK.get(i.id).includes(F.q);
  }

  /* applyFilters() of the plain page, as a pure read: what is visible, how many per
     shelf and sub-shelf, and what each unchecked stat would leave if checked. */
  function filterView() {
    const ITEMS = st.ITEMS;
    let shown = 0;
    const ok = new Map(), per = new Map(), perSub = new Map();
    for (const i of ITEMS) {
      const m = matches(i);
      ok.set(i.id, m);
      if (!m) continue;
      shown++;
      per.set(i.sh, (per.get(i.sh) || 0) + 1);
      const key = `${i.sh}|${i.k}`;
      perSub.set(key, (perSub.get(key) || 0) + 1);
    }
    // each unchecked stat shows what checking it would leave, so the rail never lies
    const statN = new Map();
    for (const [, rows] of STAT_GROUPS) for (const [label] of rows) {
      const on = F.stats.has(label);
      statN.set(label, ITEMS.filter(i => (on || hasStat(i, label)) && matches(i)
        && (on || [...F.stats].every(l => hasStat(i, l)))).length);
    }
    return { shown, ok, per, perSub, statN };
  }

  const SEARCH = { el: null };
  st.clearFilters = () => {
    F.q = ''; F.stats.clear();
    if (SEARCH.el) SEARCH.el.value = '';
    st.emit();
  };

  /* ── inspector formatting ─────────────────────────────────────────────────────
     Shared by the inspector panel (forge-blocks.jsx) and the hover card
     (itemCardHTML in forge-stats.jsx), which is why they are HTML strings: the same
     escaped markup lands in innerHTML in both places. */
  /* Riot's own hues, sampled from the brightest quartile of each glyph's artwork,
     so a ratio's number is tinted the same colour as the icon standing next to it,
     rather than a palette invented here. Movement's glyph is near-white, which is not
     a usable text colour against either theme family, so it falls through to --ink
     and lets its icon carry the identity alone. */
  const STAT_HUE = {
    'Attack Damage': '#f59336', 'Ability Power': '#7c6fff', 'Health': '#229d5f',
    'Armor': '#fbc45e', 'Magic Resist': '#56e9ff', 'Critical Strike': '#ef351c',
    'Armor Penetration': '#ff6357', 'Mana': '#199eed',
  };

  /* bake_passives.py abbreviates a stat where spelling it out would say it twice in
     one sentence ("Gain 50% base AD bonus Attack Damage"). Those two are the only
     names that do not already key STAT_GLYPH. */
  const RATIO_STAT = { 'AD': 'Attack Damage', 'AP': 'Ability Power' };

  /* The baker's whole stat vocabulary, longest first so `Magic Resist` is not read as
     two words and `Critical Strike Chance` wins over nothing at all. */
  const RATIO_RE = new RegExp(
    '(\\d[\\d.,]*\\s*%?)(\\s+(?:x\\s+)?(?:base |bonus |max )?)'
    + '(Critical Strike Chance|Magic Resist|Move Speed|Attack Range|Lethality'
    + '|Health|Armor|Mana|AD|AP)\\b', 'g');

  const STAT_GLYPH = {
    'Health': 'Health',
    'Base Health Regen': 'Health Regen',
    'Mana': 'Mana',
    'Base Mana Regen': 'Mana Regen',
    'Heal and Shield Power': 'Heal & Shield Power',
    'Attack Damage': 'Attack Damage',
    'Attack Speed': 'Attack Speed',
    'Ability Power': 'Ability Power',
    'Ability Haste': 'Ability Haste',
    'Armor': 'Armor',
    'Magic Resist': 'Magic Resist',
    'Armor Penetration': 'Armor Penetration',
    'Lethality': 'Armor Penetration',
    'Magic Penetration': 'Magic Penetration',
    'Critical Strike Chance': 'Critical Strike',
    'Critical Strike Damage': 'Critical Strike',
    'Life Steal': 'Life Steal',
    'Omnivamp': 'Omnivamp',
    'Tenacity': 'Tenacity',
    'Move Speed': 'Movement',
    'Gold Per 10 Seconds': 'Gold Per 10 Seconds',
  };

  /* Draw each stat ratio as its stat: the glyph in front of the number, the number in
     the glyph's colour. The numbers themselves come from Riot's calculation graph via
     bake_passives.py; this is only what makes them read as ratios rather than as words
     that happen to sit in the sentence.

     Takes text that is ALREADY escaped, and matches nothing but digits, a percent sign
     and a name off the fixed list above, so it cannot introduce markup of its own. */
  st.withRatios = escaped => escaped.replace(RATIO_RE, (_m, num, sep, stat) => {
    const key = STAT_GLYPH[RATIO_STAT[stat] || stat];
    const g = GLYPH[key], hue = STAT_HUE[key];
    return `<span class="ratio"${hue ? ` style="--sc:${hue}"` : ''}>`
      + (g ? `<img src="${g}" alt="">` : '')
      + `${num}${sep}${stat}</span>`;
  });

  const fline = (k, body) => `<div class="fline"><span class="k">${k}</span><span>${body}</span></div>`;

  /* The rail's own glyph beside each number, so the panel, the hover card and the
     filter rail all name a stat the same way. Stat lines read "55 Attack Damage",
     so the split is the first token off the front. */
  st.statsDL = i => {
    if (!i.st.length) return '';
    return `<dl>${i.st.map(s => {
      const m = s.match(/^(\S+)\s+(.*)$/);
      const num = m ? m[1] : '', label = m ? m[2] : s;
      const g = GLYPH[STAT_GLYPH[label]];
      return `<div>${g ? `<img src="${g}" alt="">` : '<i class="glyph-none"></i>'}`
        + `<dt>${esc(num)}</dt><dd>${esc(label)}</dd></div>`;
    }).join('')}</dl>`;
  };

  /* Both sources in full. The tile caption is one number; this is the reading behind
     it, plus the slot-by-slot lolalytics figures that have nowhere else to go - an
     item bought second and the same item bought fifth are different items. */
  st.figsHTML = id => {
    const out = [];
    const s = st.coachItem(id);
    if (s && s.wpa != null) {
      out.push(`<h4>coachless${st.STATS.patch ? ` · patch ${esc(st.STATS.patch)}` : ''}</h4>`);
      out.push(fline('WPA', `<b class="${st.wpaClass(s.wpa, s.n)}">${st.fmtWpa(s.wpa)}</b> points of win probability`));
      out.push(fline('swing', `<b>${s.wrPre.toFixed(1)}%</b> before → <b>${s.wrPost.toFixed(1)}%</b> after`));
      out.push(fline('sample', `<b>${s.share.toFixed(1)}%</b> of these purchases · <b>${s.n.toLocaleString()}</b> bought`
        + (s.n < st.MIN_GAMES ? ' · under the floor, so read it as noise' : '')));
      if (s.buyAt) out.push(fline('timing', `bought around <b>${Math.round(s.buyAt / 60000)}</b> min in`));
    }
    const l = st.lolaItem(id) || {};
    const slots = Object.keys(l).sort((a, b) => +a - +b);
    if (slots.length) {
      out.push(`<h4>lolalytics${st.LOLA.patch ? ` · patch ${esc(st.LOLA.patch)}` : ''}</h4>`);
      for (const slot of slots) {
        const v = l[slot];
        out.push(fline(st.ordinal(+slot), `<b class="${st.wrClass(v.wr, v.n)}">${st.fmtWr(v.wr)}</b> win`
          + ` · <b>${v.pick.toFixed(1)}%</b> pick · ${v.n.toLocaleString()} games`
          + (v.at ? ` · ~${v.at} min` : '')));
      }
      out.push(`<p class="fnote">Win rate is coloured against ${esc(M.champ)}'s own `
        + `${st.lolaBase().toFixed(1)}% in this role, not against 50 \u2014 a 51% item on a 53% `
        + 'champion is an item that loses you games.</p>');
    }
    if (out.length) return `<div class="figs">${out.join('')}</div>`;
    return (st.current() || st.lola())
      ? '<p class="fnote">Neither source has a reading for this item on this champion.</p>'
      : '';
  };

  /* ── the shop ───────────────────────────────────────────────────────────────── */
  /* One tile. Memoised on primitives and stable refs only (`s` is a row out of the
     paint snapshot), so a keystroke in the set title does not re-render 250 tiles. */
  const Tile = memo(function Tile({ item, ok, s, cur }) {
    const rated = !!s && s.wpa != null;
    const thin = rated && s.n < st.MIN_GAMES;
    return (
      <div className="item" role="button" tabIndex={0} draggable={true}
           data-id={item.id} data-shelf={item.sh} hidden={!ok} aria-current={cur}>
        <img src={item.u} alt={item.n} />
        <span className="cost">{item.g}</span>
        <span className="fig">{rated ? (
          /* the shop's own scan line: WPA over the sample it rests on. The sample is
             never dropped, because the highest WPA on the shelf is always an outlier. */
          <React.Fragment>
            <b className={st.wpaClass(s.wpa, s.n)}>{st.fmtWpa(s.wpa)}</b><i>{games(s.n)}</i>
          </React.Fragment>) : null}</span>
        {rated ? (
          // share is a percent of this champion's purchases; 25%+ fills the tile
          <i className={`meta-edge ${thin ? '' : (s.wpa >= 0 ? 'up' : 'down')}`}
             style={{ width: `${Math.max(4, Math.min(46, (s.share / 25) * 46))}px`,
                      background: thin ? 'var(--line-lit)' : undefined }} />) : null}
      </div>
    );
  });

  function Shop({ hover }) {
    st.useStore();
    if (!st.loaded) return null;
    const hv = hover || {};
    const ITEMS = st.ITEMS, BY_ID = st.BY_ID;
    const v = filterView();

    /* Click reads, drag adds. They used to be the same gesture, which meant reading an item
       silently bought it. */
    const onClick = e => {
      const el = e.target.closest('.item');
      if (el) st.inspect(el.dataset.id);
    };
    const onKeyDown = e => {
      const el = e.target.closest('.item');
      if (!el || (e.key !== 'Enter' && e.key !== ' ')) return;
      e.preventDefault();
      st.inspect(el.dataset.id);
    };
    const onDragStart = e => {
      const el = e.target.closest('.item');
      if (el) {
        e.dataTransfer.setData('text/plain', el.dataset.id);
        e.dataTransfer.effectAllowed = 'copy';
        el.classList.add('dragging');
      }
      if (hv.onDragStart) hv.onDragStart(e);
    };
    const onDragEnd = e => {
      const el = e.target.closest('.item');
      if (el) el.classList.remove('dragging');
    };

    // an aisle the role removed is never removed silently: the shelf it came off
    // says which ones went and whose shop this is
    const gone = Object.entries(ROLE_SUBS)
      .filter(([, roles]) => M.role && !roles.includes(M.role))
      .map(([k]) => k.toLowerCase());
    const utilityWhat = gone.length
      ? `${SHELF_BLURB.Utility} · ${gone.join(' and ')} are not bought ${M.role === 'jungle' ? 'in the jungle' : `on ${M.role}`}`
      : SHELF_BLURB.Utility;
    const on = [...(F.q ? [`"${F.q}"`] : []), ...F.stats];

    return (
      <React.Fragment>
        <aside className="col col-rail">
          <div className="rail" id="rail">
            <div className="rail-top">
              <h2>Stats</h2>
              <button type="button" id="clearStats" disabled={F.stats.size === 0}
                      onClick={() => { F.stats.clear(); st.emit(); }}>Clear</button>
            </div>
            <div id="railBody" onClick={e => {
              const b = e.target.closest('[data-stat]');
              if (!b) return;
              const label = b.dataset.stat;
              if (F.stats.has(label)) F.stats.delete(label); else F.stats.add(label);
              st.emit();
            }}>
              {STAT_GROUPS.map(([head, rows]) => (
                <div className="rail-group" key={head}>
                  <h3>{head}</h3>
                  {rows.map(([label]) => {
                    const sel = F.stats.has(label), n = v.statN.get(label);
                    return (
                      <button type="button" className="stat" key={label} data-stat={label}
                              aria-pressed={String(sel)} disabled={!sel && n === 0}>
                        {GLYPH[label] ? <img src={GLYPH[label]} alt="" /> : <i className="glyph-none"></i>}
                        <span>{label}</span><span className="n" data-statn="">{n}</span>
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
          </div>
        </aside>

        <section className="col">
          <div className="col-head">
            <h2>Shop</h2>
            <span className="count" id="shopCount">{v.shown === ITEMS.length
              ? `${ITEMS.length} items` : `${v.shown} of ${ITEMS.length}`}</span>
          </div>

          <input id="search" placeholder="Search a name, a passive, an effect. Try spellblade, tenacity, execute"
                 aria-label="Search items" ref={el => { SEARCH.el = el; }}
                 onChange={e => { F.q = e.target.value.trim().toLowerCase(); st.emit(); }} />

          <UI.Readings />

          <div id="shelves" onClick={onClick} onKeyDown={onKeyDown} onDragStart={onDragStart}
               onDragEnd={onDragEnd} onMouseOver={hv.onMouseOver} onFocus={hv.onFocus}
               onMouseLeave={hv.onMouseLeave} onBlur={hv.onBlur} onScrollCapture={hv.onScrollCapture}>
            {st.LAYOUT.map(({ s, subs: subList, flat }) => {
              const n = v.per.get(s) || 0;
              return (
                <section className="shelf" data-shelf={s} key={s} hidden={n === 0}>
                  <div className="shelf-head">
                    <h3>{s}</h3><span className="n" data-n="">{n}</span>
                    <span className="what">{s === 'Utility' ? utilityWhat : (SHELF_BLURB[s] || '')}</span>
                  </div>
                  {subList.map(k => {
                    const key = `${s}|${k}`, sn = v.perSub.get(key) || 0;
                    const ids = (st.P.grids?.get(key)) || st.GRID.get(key);
                    return (
                      <div className="sub" data-sub={key} key={k} hidden={sn === 0}>
                        {flat ? null : <div className="sub-head"><h4>{k}</h4><span className="n" data-subn="">{sn}</span></div>}
                        <div className="grid" data-grid={key}>
                          {ids.map(id => {
                            const item = BY_ID.get(id);
                            return <Tile key={id} item={item} ok={v.ok.get(id)} s={st.P.by.get(id) || null}
                                         cur={st.INSPECTED ? String(id === st.INSPECT) : undefined} />;
                          })}
                        </div>
                      </div>
                    );
                  })}
                </section>
              );
            })}
          </div>

          <div className="empty" id="empty" hidden={v.shown > 0}>
            <b>No items match</b>
            <span id="emptyWhy">{on.length
              ? `Nothing matches ${on.join(' and ')}${M.role ? ` in the ${M.role} shop` : ''}.` : ''}</span>
            <button type="button" id="clearAll" onClick={st.clearFilters}>Clear the filters</button>
          </div>
        </section>
      </React.Fragment>
    );
  }

  UI.Shop = Shop;
})();
