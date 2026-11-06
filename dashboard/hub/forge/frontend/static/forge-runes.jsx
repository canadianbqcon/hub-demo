/* forge-runes.jsx - the Forge builder's rune page, hover cards, step nav and patch strip, as React.

   Port of the last part of forge.html's main <script type="module"> (the rune picker, its
   alternatives, the hover card, the two steps and the patch strip). The data and the
   hooks come from forge-shop / forge-blocks / forge-stats (see the interface note at the
   top of forge-shop.jsx); this file adds the components the mount needs and the two
   hooks Task 22 owns: st.renderPatch and the hover-card handler objects.

   The plain page built the rune picker once and painted attributes after, to keep focus
   and transitions alive across a pick. Here the picker is a function of st.R, and React
   keeps the same nodes (all five trees stay in each column, four of them hidden), so the
   same property holds without the hand painting.

   Components: ForgeUI.Runes() (#step1), ForgeUI.StepNav() (#stepnav), ForgeUI.PatchStrip()
   (#patchstrip). Helper: ForgeUI.hoverCards(find) returns the handler object the Shop and
   Blocks props take. */
window.ForgeUI = window.ForgeUI || {};

(() => {
  const { memo, useRef, useEffect } = React;
  const UI = window.ForgeUI;
  const st = UI.state;
  const lib = () => window.ForgeLib;
  const M = st.M;
  const games = st.games;

  /* ── the hover card ───────────────────────────────────────────────────────
     Hovering a rune says what the rune does; hovering an item says what the item
     gives you. Both used to live in a `title` attribute, which is browser chrome:
     about a second of hover before it appears, no styling, and on a grid of 48px
     shop tiles it may as well not have existed. This is the same content, styled,
     beside the thing, at once.

     One card element for the whole page, moved and refilled, fed by handlers on the
     containers so it survives every repaint of the shop, the set and the picker. */
  const CARD = document.createElement('div');
  CARD.className = 'hovercard';
  CARD.hidden = true;
  document.body.append(CARD);

  function placeCard(el, html) {
    if (!html) return hideCard();
    CARD.innerHTML = html;
    CARD.hidden = false;
    // right of the thing where there is room, left of it where there is not, and
    // never off the bottom: the shard rows and the last shop shelf both sit low
    const r = el.getBoundingClientRect(), c = CARD.getBoundingClientRect();
    const x = r.right + 12 + c.width < innerWidth ? r.right + 12 : r.left - 12 - c.width;
    CARD.style.left = `${Math.max(8, x)}px`;
    CARD.style.top = `${Math.max(8, Math.min(r.top, innerHeight - c.height - 8))}px`;
  }
  function hideCard() { CARD.hidden = true; }

  const runeCardHTML = id => {
    const m = st.runeMeta(id);
    return m ? `<h4>${st.esc(m.name)}</h4><p>${st.esc(m.long || m.short || '')}</p>` : '';
  };

  /* One handler shape for every container: find the thing under the pointer, or hide. */
  function hoverCards(find) {
    const on = e => {
      const hit = find(e.target);
      if (hit) placeCard(hit.el, hit.html()); else hideCard();
    };
    return {
      onMouseOver: on, onFocus: on, onMouseLeave: hideCard, onBlur: hideCard,
      // a column scrolling under a fixed card would leave it pointing at the wrong row
      onScrollCapture: hideCard, onDragStart: hideCard,
    };
  }
  UI.hoverCards = hoverCards;

  const runeHover = hoverCards(t => {
    const btn = t.closest('[data-rune]');
    return btn && { el: btn, html: () => runeCardHTML(+btn.dataset.rune) };
  });
  UI.hoverShelves = hoverCards(t => {
    const el = t.closest('.item');
    return el && { el, html: () => st.itemCardHTML(el.dataset.id) };
  });
  UI.hoverSlots = hoverCards(t => {
    const slot = t.closest('.slot');
    if (!slot) return null;
    const it = st.S.blocks[+slot.dataset.bi]?.items[+slot.dataset.ii];
    return it && { el: slot, html: () => st.itemCardHTML(it.id, it.note) };
  });
  UI.hoverNodes = hoverCards(t => {
    const node = t.closest('[data-node]');
    return node && { el: node, html: () => st.itemCardHTML(node.dataset.node) };
  });
  /* The patch strip is icons now, so the numbers it dropped live here. Looked up by
     id off DIFF rather than stashed on the element: the entry is already in memory
     and a JSON blob in a data- attribute is the same object, spelled worse. */
  const changeHover = hoverCards(t => {
    const el = t.closest('[data-change]');
    if (!el) return null;
    const id = el.dataset.change;
    const entry = id.startsWith('champ:')
      ? st.DIFF.champions?.[id.slice(6)]
      : (st.DIFF.items || []).find(c => String(c.id) === id);
    return entry && { el, html: () => lib().changeCardHTML(entry) };
  });

  /* ── the rune picker ───────────────────────────────────────────────────────
     Two readings per rune, in two fixed lanes so the eye can run down either one:
     coachless' WPA and sample on the left, lolalytics' win rate and pick rate on
     the right. A lane with no reading holds its width with a dash rather than
     collapsing, otherwise the columns stop lining up the moment one source is
     thinner than the other, which is most of the page. */
  const lane = (text, cls, n, extra) =>
    ({ cls: `wpa${extra}${text === null ? ' thin' : ` ${cls}`}`, text: text === null ? '–' : text, n: n === null ? '' : n });

  /* Which pick this button answers to, and what each source reads under it. The
     slot prefix is the whole routing table, and the shard test comes first because
     'shard:offense' also starts with 's'; see the note on the click handler. */
  function RuneBtn({ m, slot, key_ }) {
    const R = st.R, id = +m.id;
    let sel = false, fig = null;
    if (slot === 'ks') {
      sel = R.keystone === id; fig = st.ksFig(id);
    } else if (slot.startsWith('shard:')) {
      const row = slot.slice(6);
      sel = R.shards[row] === id; fig = st.shardFig(row, id);
    } else if (slot[0] === 'p') {
      const row = +slot[1];
      sel = R.rows[row - 1] === id; fig = st.figFor(R.primary, row, id);
    } else {
      const row = +slot[1];
      sel = R.sec.includes(id); fig = st.figFor(R.secondary, row, id);
    }
    const a = lane(fig ? st.fmtWpa(fig.wpa) : null, fig ? st.wpaClass(fig.wpa, fig.n) : '',
                   fig ? games(fig.n) : null, '');
    const l = st.lolaRune(id, slot === 'ks');
    const b = lane(l ? st.fmtWr(l.wr) : null,
                   l ? st.wrClass(l.wr, l.n, slot === 'ks' ? st.lolaBase() : st.lolaRuneBase()) : '',
                   l ? `${l.pick.toFixed(1)}%` : null, ' lane');
    // no title= here: the hovercard already says all of this, and a native tooltip
    // fading in on top of it drew the same text twice, one layer over the other
    return (
      <button type="button" className={`rpick${key_ ? ' key' : ''}`} data-rune={m.id} data-slot={slot}
              aria-pressed={String(sel)}>
        <img src={m.icon} alt="" decoding="async" />
        <span className="nm">{m.name}</span>
        <span className={a.cls}>{a.text}</span><span className="rgames">{a.n}</span>
        <span className={b.cls}>{b.text}</span><span className="rgames">{b.n}</span>
      </button>
    );
  }

  const TreePick = memo(function TreePick({ side, picked }) {
    return (
      <div className="treepick">{st.TREE_IDS.map(t => {
        const m = st.treeMeta(t);
        return (
          <button type="button" data-tree={t} data-side={side} key={t} aria-pressed={String(t === picked)}
                  disabled={side === 'secondary' && t === st.R.primary}
                  title={m?.name || String(t)} aria-label={m?.name || String(t)}>
            <img src={m?.icon || ''} alt="" /></button>
        );
      })}</div>
    );
  });

  /* The lane labels. Only worth printing when at least one source has anything to
     say, so a champion-less page does not carry a header over six empty columns. */
  const SrcBar = ({ show }) => (
    <div className="srcbar" data-srcbar="" hidden={!show}>
      <span className="a">coachless</span><span className="b">lolalytics</span>
      <span className="u1">wpa</span><span className="u2">n</span>
      <span className="u3">wr</span><span className="u4">pick</span>
    </div>
  );

  /* One tree's rows, for whichever column asked. Only the primary column has a
     keystone row; the secondary picks two minor runes and no keystone at all. All five
     trees stay in the DOM and four are hidden: that is what keeps a tree switch from
     re-decoding sixty icons. */
  const TreeBody = ({ side, t, picked }) => (
    <div className="treebody" data-tree-body={t} hidden={t !== picked}>
      {side === 'primary' ? (
        <div className="rrow keys"><span className="lab">Keystone</span>{
          st.runesIn(t, 0).map(m => <RuneBtn m={m} slot="ks" key_={true} key={m.id} />)}</div>
      ) : null}
      {[1, 2, 3].map(row => (
        <div className="rrow" key={row}><span className="lab">{`Row ${row}`}</span>{
          st.runesIn(t, row).map(m => <RuneBtn m={m} slot={(side === 'primary' ? 'p' : 's') + row} key={m.id} />)
        }</div>
      ))}
    </div>
  );

  const RuneCol = ({ id, side, title, empty, picked, showSrc }) => (
    <div className="rune-col" id={id}>
      <h3>{title}</h3>
      <TreePick side={side} picked={picked} />
      <SrcBar show={showSrc} />
      <p className="quiet" data-empty="" hidden={picked != null}>{empty}</p>
      {st.TREE_IDS.map(t => <TreeBody side={side} t={t} picked={picked} key={t} />)}
    </div>
  );

  /* What is still missing, in the client's own terms, so "why is this page not
     finished" never needs working out by counting what is on screen. */
  function runeStatus() {
    const R = st.R;
    const primaryLeft = 3 - R.rows.filter(Boolean).length;
    const want = [
      !R.keystone && 'a keystone',
      primaryLeft > 0 && `${primaryLeft} more primary`,
      R.sec.length < 2 && `${2 - R.sec.length} more secondary`,
      Object.values(R.shards).some(v => !v) && 'all three shards',
    ].filter(Boolean);
    return want.length ? `still to pick: ${want.join(', ')}` : 'the page is complete';
  }

  /* ── alternatives: the page you did not take, and when you would ──────────
     A saved rune page is one pick per slot, which is the build but not the reason.
     An alternative is the swap plus the sentence saying when to make it, and it is
     what turns a build somebody else can read into one they can use.

     The keystone and the primary tree have no alternative on purpose. A different
     keystone reads every figure on the page differently and usually wants different
     items under it, so it is a different build, and the library already versions
     those separately, by name and patch. Everything below the keystone is a swap
     you make inside one build, which is exactly what this list holds. */
  let ARMED = false;
  let ARM_MSG = '';

  /* The slot-to-pick routing lives in static/itemset.js, shared with the overlay
     that reads a saved build back out. Only the name lookup is local, because the
     rune index is a different object on each surface. */
  const rowOf = id => st.runeMeta(id)?.row;
  function insteadOf(a) {
    const cur = lib().altReplaces(st.R, a, rowOf);
    if (!cur) return '';
    return `instead of ${(a.slot === 'secondary' ? st.treeMeta(cur) : st.runeMeta(cur))?.name || ''} · `;
  }

  /* Record one, ask for its note, keep it. A cancelled note cancels the whole
     alternative: an alt with nothing to say is the swap without the reason, which
     is the half this feature exists to add. */
  function addAlt(alt) {
    return st.askNote({
      title: alt.title,
      why: 'Shown on the saved build under the rune page. Say when you take this '
         + 'instead \u2014 the matchup, the lane state, what you are afraid of.',
    }).then(note => {
      if (note === null) return false;
      delete alt.title;
      st.R.alts.push(Object.assign({}, alt, { note }));
      return true;
    });
  }

  function Alts() {
    const R = st.R;
    // armed with nothing recorded yet still shows, because the instructions for
    // the mode you just entered live in this panel
    const hidden = !R.alts.length && !ARMED;
    const rows = hidden ? [] : R.alts.map((a, i) => {
      const isTree = a.slot === 'secondary';
      const m = isTree ? st.treeMeta(a.tree) : st.runeMeta(a.id);
      if (!m) return null;
      const withRunes = isTree && (a.sec || []).length
        ? ` with ${a.sec.map(x => st.runeMeta(x)?.name).filter(Boolean).join(' and ')}`
        : '';
      return (
        <div className="alt" key={i}>
          <img src={m.icon} alt="" />
          <p className="who"><b>{m.name}</b>{withRunes}
            <span className="instead">{insteadOf(a) + lib().altSlotLabel(a.slot)}</span></p>
          <p className="note">{a.note || ''}</p>
          <span className="acts">
            <button type="button" data-altedit={i}>Note</button>
            <button type="button" className="kill" data-altdrop={i} aria-label="Remove this alternative">{'×'}</button>
          </span>
        </div>
      );
    });
    return (
      <section className="alts" id="alts" hidden={hidden}>
        {hidden ? null : (
          <React.Fragment>
            <h3>Alternatives</h3>
            {ARM_MSG ? <p className="quiet">{ARM_MSG}</p> : null}
            {rows.some(Boolean) ? rows : <p className="quiet">Nothing recorded yet.</p>}
          </React.Fragment>
        )}
      </section>
    );
  }

  function onStepClick(e) {
    const R = st.R;
    /* The alternatives panel lives inside #step1, so its own buttons come first. */
    const drop = e.target.closest('[data-altdrop]');
    if (drop) { R.alts.splice(+drop.dataset.altdrop, 1); return st.renderRunes(); }
    const edit = e.target.closest('[data-altedit]');
    if (edit) {
      const a = R.alts[+edit.dataset.altedit];
      if (!a) return;
      const m = a.slot === 'secondary' ? st.treeMeta(a.tree) : st.runeMeta(a.id);
      return st.askNote({ title: m?.name || 'Alternative', value: a.note }).then(note => {
        if (note !== null) a.note = note;
        st.renderRunes();
      });
    }

    const tree = e.target.closest('[data-tree]');
    if (tree) {
      const t = +tree.dataset.tree;
      /* Armed, a tree click RECORDS rather than picks. Clicking the tree already
         in the secondary column brings its two runes along, because at that point
         the column IS the alternative you just finished building; any other tree
         is recorded bare and its runes become alternatives of their own. */
      if (ARMED) {
        if (tree.dataset.side === 'primary') {
          ARM_MSG = 'The primary tree is the build. A different one is a different '
            + 'keystone and a different set of items, so save it as its own build.';
          return st.renderRunes();
        }
        return addAlt({
          title: st.treeMeta(t)?.name || 'Second tree', slot: 'secondary', tree: t,
          sec: t === R.secondary ? [...R.sec] : [],
        }).then(ok => {
          if (ok) { ARMED = false; ARM_MSG = ''; }
          st.renderRunes();
        });
      }
      if (tree.dataset.side === 'primary') {
        if (R.primary === t) return;
        R.primary = t; R.keystone = null; R.rows = [null, null, null];
        if (R.secondary === t) { R.secondary = null; R.sec = []; }
      } else {
        if (R.secondary === t) return;
        R.secondary = t; R.sec = [];
      }
      return st.renderRunes();
    }

    const btn = e.target.closest('[data-rune]');
    if (!btn) return;
    const id = +btn.dataset.rune, slot = btn.dataset.slot;

    if (ARMED) {
      if (slot === 'ks') {
        ARM_MSG = 'The keystone is the build. Every figure on this page is read '
          + 'under it, so a different one is a different build, not a swap.';
        return st.renderRunes();
      }
      return addAlt({ title: st.runeMeta(id)?.name || 'Rune', slot, id }).then(ok => {
        if (ok) { ARMED = false; ARM_MSG = ''; }
        st.renderRunes();
      });
    }

    /* Order matters here and it is the bug this page shipped with: a shard's slot
       is 'shard:offense', whose first character is also 's', so the secondary-rune
       branch below caught every shard click. `+slot[1]` came out NaN, the shard was
       pushed into R.sec instead of R.shards, and both halves broke at once - the
       shard highlight never moved off the seeded pick while the page reported a
       different rune chosen, and the two real secondary picks got shifted out of a
       two-slot list by shard ids. Test the full prefix before the initial. */
    if (slot === 'ks') {
      /* The rows you picked stay picked. Their figures are read under the keystone
         so every number on them moves, which is the reading you switched keystones
         to see; the picks themselves are yours and re-seeding them from most-taken
         overwrote a deliberate choice every time you compared two keystones. */
      R.keystone = R.keystone === id ? null : id;
    } else if (slot.startsWith('shard:')) {
      const row = slot.slice(6);
      R.shards[row] = R.shards[row] === id ? null : id;
    } else if (slot[0] === 'p') {
      const i = +slot[1] - 1;
      R.rows[i] = R.rows[i] === id ? null : id;
    } else if (slot[0] === 's') {
      const row = +slot[1];
      const at = R.sec.indexOf(id);
      if (at >= 0) R.sec.splice(at, 1);
      else {
        // one per row, two in total, oldest out first: the client's own rule
        R.sec = R.sec.filter(x => st.RUNEDEX.runes?.[String(x)]?.row !== row);
        R.sec.push(id);
        if (R.sec.length > 2) R.sec.shift();
      }
    }
    st.renderRunes();
    /* Step two is read under the keystone now, so switching one moves every figure
       in the shop as well. Guarded on the keystone branch: a minor rune changes
       nothing about the items, and repainting the whole shelf on it would be a full
       re-render per click. */
    if (slot === 'ks') { st.paintItems(); st.renderBlocks(); st.applyFilters(); }
  }

  function Runes() {
    st.useStore();
    if (!st.loaded || !st.S) return null;
    const R = st.R;
    const data = st.current();
    const showSrc = !!(data || st.lola());
    // coachless only breaks a keystone down once enough games took it, so picking a
    // rare one empties every figure on the page. Saying why beats three silent rows.
    const thin = data && R.keystone && !st.ksEntry();
    const sub = thin
      ? `no reading under ${st.runeMeta(R.keystone)?.name || 'this keystone'} \u2014 too few games took it, `
        + 'so the rows below are yours to pick blind'
      : runeStatus();
    const note = data
      ? 'WPA is the change in win probability from just before to just after, so it is not a win '
        + 'rate. Every figure is read under the keystone you picked, because a minor rune only means '
        + `anything alongside one. Anything under ${st.MIN_GAMES.toLocaleString()} games is greyed rather `
        + 'than coloured, and a dash means coachless has no reading for it at all.'
        + (st.STATS.patch ? ` Figures are patch ${st.STATS.patch}, because coachless paywalls the live patch.` : '')
      : 'Pick a champion and a role above to read what these runes did. Without one the page is '
        + 'still yours to build, just with no figures on it.';

    return (
      <section className="runepage" id="step1" hidden={st.step !== 'runes'}
               data-arming={ARMED ? '' : undefined} onClick={onStepClick}
               onMouseOver={runeHover.onMouseOver} onFocus={runeHover.onFocus}
               onMouseLeave={runeHover.onMouseLeave} onBlur={runeHover.onBlur}
               onScrollCapture={runeHover.onScrollCapture} onDragStart={runeHover.onDragStart}>
        {/* Save sits at the top right, where the page is read from, not under a
            column whose height depends on which tree you picked. */}
        <div className="meta-head">
          <h2 id="metaTitle">{data ? `${M.champ} ${M.role} rune page` : 'Rune page'}</h2>
          <span className="sub" id="metaSub" aria-live="polite">{sub}</span>
          <span className="grow"></span>
          <div className="actions">
            <button type="button" id="armAlt" aria-pressed={String(ARMED)} onClick={() => {
              ARMED = !ARMED;
              ARM_MSG = ARMED
                ? 'Click any rune, shard, or a tree in the Secondary column to record it as '
                  + 'an alternative. Clicking the second tree you already have picked brings '
                  + 'its two runes along with it. The keystone and the primary tree are the '
                  + 'build itself, so they have no alternative.'
                : '';
              st.renderRunes();
            }}>Add alternative</button>
            <button type="button" id="clearRunes" onClick={() => {
              st.R = st.blankRunes(); ARMED = false; ARM_MSG = ''; st.renderRunes();
            }}>Clear the page</button>
            <button type="button" className="btn-primary" id="toItems" onClick={() => {
              // a rune page with no items yet is a real save
              st.saveSet().then(() => st.showStep('items'));
            }}>Save the page and go back to items</button>
          </div>
        </div>
        {/* The client's own shape: the primary tree on the left, the secondary tree
            and the shards stacked on the right. The keystones take up whatever slack
            that leaves, so the two columns finish level. */}
        <div className="rune-cols">
          <RuneCol id="primaryCol" side="primary" title="Primary" picked={R.primary} showSrc={showSrc}
                   empty="Pick a tree to see its keystones." />
          <div className="rune-side">
            <RuneCol id="secondaryCol" side="secondary" title="Secondary" picked={R.secondary} showSrc={showSrc}
                     empty="Pick a second tree, then any two of its runes." />
            <div className="rune-col" id="shardCol">
              <h3>Shards</h3>
              <SrcBar show={showSrc} />
              {Object.entries(st.SHARD_ROWS).map(([row, ids]) => (
                <div className="rrow" key={row}><span className="lab">{row}</span>{ids.map(id => {
                  const m = st.runeMeta(id);
                  return m ? <RuneBtn m={Object.assign({ id }, m)} slot={`shard:${row}`} key={id} /> : null;
                })}</div>
              ))}
            </div>
          </div>
        </div>
        {/* The alternatives sit under the page they are alternatives TO, not beside
            it: you read the page you built first, then what you would swap. */}
        <Alts />
        <p className="meta-note" id="metaNote">{note}</p>
      </section>
    );
  }

  /* ── the two steps ───────────────────────────────────────────────────────── */
  const WHY = {
    items: 'Drag items into blocks, then paste the JSON into Collection → Items.',
    runes: 'Runes have no import. You read this page off the saved build and type it in.',
    plan: 'Nothing here exports either. Spells, levels and pathing ride with the set; bans belong to the champion.',
  };

  function StepNav() {
    st.useStore();
    const b = (which, n, label) => (
      <button type="button" data-step={which} aria-pressed={String(st.step === which)}><b>{n}</b> {label}</button>
    );
    return (
      <nav className="stepnav" id="stepnav" onClick={e => {
        const t = e.target.closest('[data-step]');
        if (t) st.showStep(t.dataset.step);
      }}>
        {b('items', 1, 'Items')}
        {b('runes', 2, 'Rune page')}
        {b('plan', 3, 'Plan')}
        <span className="grow"></span>
        <span className="why" id="stepWhy">{WHY[st.step] || ''}</span>
      </nav>
    );
  }

  /* ── the patch strip ─────────────────────────────────────────────────────
     Same component the landing page uses. The champion's own items are marked, so
     "Black Cleaver got 5 AD" reads differently on a Viego page than on a Lillia one.
     renderStrip is imperative (it owns the strip's hidden flag, title and cards), so the
     elements are rendered empty and handed to it from an effect, once per renderPatch. */
  st.patchRev = 0;
  st.renderPatch = () => { st.patchRev++; st.emit(); };

  function PatchStrip() {
    st.useStore();
    const strip = useRef(null), title = useRef(null), changes = useRef(null), none = useRef(null);
    useEffect(() => {
      if (!st.loaded || !strip.current) return;
      const data = st.current();
      const mine = new Set((data?.items || []).map(i => String(i.id)));
      // the champion leads the strip when Riot touched them, since every figure on
      // the page is read for this champion specifically
      const c = st.CHAMPS.find(x => x.n.toLowerCase() === (M.champ || '').toLowerCase());
      lib().renderStrip({
        strip: strip.current, title: title.current,
        changes: changes.current, none: none.current,
      }, st.DIFF, mine, c && { name: c.n, icon: c.u });
    }, [st.patchRev]);
    return (
      <section className="patchstrip" id="patchstrip" style={{ margin: '14px 20px 0' }} hidden ref={strip}>
        <h3 id="patchTitle" ref={title}>This patch</h3>
        <div className="changes" id="patchChanges" ref={changes}
             onMouseOver={changeHover.onMouseOver} onFocus={changeHover.onFocus}
             onMouseLeave={changeHover.onMouseLeave} onBlur={changeHover.onBlur}
             onScrollCapture={changeHover.onScrollCapture} onDragStart={changeHover.onDragStart}></div>
        <p className="patch-none" id="patchNone" hidden ref={none}></p>
      </section>
    );
  }

  UI.Runes = Runes;
  UI.StepNav = StepNav;
  UI.PatchStrip = PatchStrip;
})();
