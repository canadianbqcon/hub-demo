/* forge-blocks.jsx - the "Your set" column of the Forge builder, as React: the inspector
   docked above it, the blocks and their drag and drop, the export, the saved-set library
   and the save path that autosave rides.

   Port of forge.html lines 1832-2397 (inspect, set mutations, blocks, export, events,
   library) plus loadSet / bootSet (3579-3598), which belong to the library. Logic is
   attached to ForgeUI.state; ForgeUI.Blocks renders the column. The delegated-handler
   shape of the plain page is kept (closest() off e.target, data-* indices), so the DOM a
   scenario drives is the DOM it always was.

   Props: ForgeUI.Blocks({ hoverSlots, hoverNodes }) - optional hover-card handler objects
   (see forge-shop.jsx) for the slots in #blocks and the build-path nodes in #inspect. */
(() => {
  const { useEffect, useRef } = React;
  const UI = window.ForgeUI;
  const st = UI.state;
  const lib = () => window.ForgeLib;
  const { plural } = st;

  /* ── inspector ──────────────────────────────────────────────────────────────
     Clicking reads and never changes the set. The panel itself is derived from
     st.INSPECT; this only moves the pointer and asks for the scroll. */
  st.inspect = id => {
    const i = st.BY_ID.get(id);
    const moved = st.INSPECT !== (i ? id : null);
    st.INSPECT = i ? id : null;
    st.INSPECTED = true;
    /* the panel is docked above the set, so an item clicked four thousand pixels down
       the shop would otherwise open somewhere you cannot see. 'nearest' is a no-op when
       it is already on screen, and the guard keeps an add from yanking the page around. */
    if (i && moved) st.scrollInspect = true;
    st.emit();
  };

  /* ── your set ───────────────────────────────────────────────────────────── */
  st.addToBlock = (id, n, bi, at) => {
    if (bi === undefined) bi = st.S.active;
    if (at === undefined) at = null;
    const block = st.S.blocks[bi];
    if (!block || !st.BY_ID.has(id)) return;
    const hit = block.items.find(i => i.id === id);
    // an item already in the block keeps its place and counts up; a new one lands
    // where it was dropped, which is the whole point of dropping it there
    if (hit) hit.count += n;
    else block.items.splice(at == null ? block.items.length : at, 0, { id, count: n });
    st.sync();
  };

  /* Reorder within a block and move between blocks are the same operation: take it
     out, put it back in at the landing index. The one wrinkle is that removing it
     first shifts everything after it down, so a move to a later slot in the SAME
     block has to come back one. */
  st.moveItem = (fb, fi, tb, at) => {
    const from = st.S.blocks[fb], to = st.S.blocks[tb];
    if (!from || !to || !from.items[fi]) return;
    const [it] = from.items.splice(fi, 1);
    let landing = at == null ? to.items.length : at;
    if (fb === tb && fi < landing) landing--;
    // dropping onto an item already in the target block merges rather than duplicates
    const hit = to.items.find(x => x.id === it.id);
    if (hit) hit.count += it.count;
    else to.items.splice(Math.max(0, Math.min(landing, to.items.length)), 0, it);
    st.S.active = tb;
    st.sync();
  };

  /* The single hook for the crossed reading. Every block mutation - a drop, an x,
     a reorder, a load - ends in this function, and so does every keystone,
     starter and champion/role change, so hooking it once beats hooking six call
     sites. It recurses exactly one level deep: the repaint below re-enters with
     the same key, and `refreshConditioned` returns false on a key it already
     holds. The markup itself is derived from state, so "render" is an emit. */
  st.renderBlocks = () => {
    st.emit();
    st.refreshConditioned().then(changed => {
      if (changed) { st.paintItems(); st.renderBlocks(); st.applyFilters(); }
    });
  };

  /* The JSON shape lives in static/itemset.js: the champion build list reads a
     saved set back out and offers the same Copy JSON, and one contract typed in
     two files is one contract that drifts. */
  st.buildSet = () => lib().itemSetJSON({
    title: st.S.title, champions: st.S.champs, blocks: st.S.blocks });

  st.sync = () => {
    st.renderBlocks();   // the export, the counts and the inspector's Add label derive from state
    st.persist();
  };

  // the title, the chips and the filters are derived too, so a full repaint is a sync
  st.renderAll = () => { st.sync(); };

  /* --- the set library ------------------------------------------------------
     Server-backed, and keyed by (name, patch) rather than name alone. Saving
     "Viego clear" again on the same patch replaces it; saving it once a new
     patch has landed leaves the old one alone and starts a new version. That is
     what keeps a build you liked on 16.14 readable after 16.15 changed the item
     it was built around, which localStorage-keyed-by-name could never do. */
  st.fetchSaves = () => fetch('api/sets')
    .then(r => r.json())
    .then(j => { st.SAVES = j.sets || []; })
    .catch(() => { st.SAVES = []; })
    .then(() => { st.emit(); });

  /* One save path for both steps. Step one saves a rune page with no items yet -
     which is a real state, not a half-finished one: the page is chosen and stored
     before the first item is placed, and the items update the same row later.

     The Save button passes its click event as `silent` (the plain page wired the
     function straight to the listener), so a button click is always the quiet path:
     no prompt, no confirm, no alert. Only #toItems and #dupe call it with no
     argument and get the loud one. Kept on purpose; the parity scenarios depend on it. */
  st.saveSet = silent => {
    if (st.LOCKED)
      return Promise.resolve(silent ? false : alert('Auto sets are read-only. Copy it to your builds to edit.'));
    const S = st.S;
    const runes = st.runePayload();
    if (!runes && !S.blocks.some(b => b.items.length))
      return Promise.resolve(silent ? false : alert('Pick a rune page or put an item in a block first.'));

    const title = (S.title.trim() || (silent ? '' : prompt('Name this set:', '')) || '').trim();
    if (!title) return Promise.resolve(false);
    const patch = st.LIVE_PATCH;
    if (!patch)
      return Promise.resolve(silent ? false : alert('No patch is known, so there is nothing to version this against.'));

    const clash = st.SAVES.find(s => s.name.toLowerCase() === title.toLowerCase() && s.patch === patch);
    // An autosave never takes someone else's row: it writes only what it already owns.
    if (clash && clash.id !== st.OWNED
        && (silent || !confirm(`"${title}" already has a patch ${patch} version. Replace it?`)))
      return Promise.resolve(false);

    S.title = title;
    st.emit();
    return fetch('api/sets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: st.OWNED, name: title, patch, champion: st.M.champ || null,
        role: st.M.role || null, champions: S.champs, runes, blocks: S.blocks,
        plan: lib().planPayload(S.plan),
      }),
    }).then(r => r.json().then(out => {
      if (!r.ok) { if (!silent) alert(out.error || 'That set did not save.'); return false; }
      st.OWNED = out.saved?.id || null;
      return st.fetchSaves().then(() => {
        st.emit(); st.persist();
        if (out.forkedFrom && !silent)
          alert(`Saved as the patch ${patch} version. The earlier one is still in the log.`);
        if (silent) st.markSaved();
        return true;
      });
    })).catch(err => {
      if (!silent) alert(`Could not reach the set library: ${err.message}`);
      return false;
    });
  };

  /* ── opening an existing build ────────────────────────────────────────────
     The champion build list hands the builder a set id (?set=), and New set hands
     it ?new=1 so a fresh build never opens on the last one restored from
     localStorage. Both are read before saveMeta() normalises the address bar. */
  st.loadSet = s => {
    st.S = {
      title: s.name || '',
      champs: s.champions || [],
      active: 0,
      plan: lib().normalisePlan(s.plan),
      blocks: (s.blocks || []).length ? structuredClone(s.blocks) : st.blank().blocks,
    };
    st.R = s.runes ? Object.assign({}, st.blankRunes(), structuredClone(s.runes)) : st.blankRunes();
    // An Auto set is read-only: only Autobuild writes it (the server answers 409),
    // so it opens unowned, with no autosave, and edits wait for Copy to my builds.
    st.LOCKED = s.auto === true;
    st.LOCKED_SRC = st.LOCKED ? s : null;
    st.OWNED = st.LOCKED ? null : s.id;  // editing your own build writes back to it, no clash prompt
    if (!st.LOCKED) st.persist();        // schedules an autosave POST about 1.2s out
  };

  /* Copy to my builds: the open Auto set becomes a new set of his own. "Auto " comes
     off the name, " copy" goes on while the name is taken on this patch, and no
     autoKey or sources travel (the builder POST never sends them). */
  /* Every mutation runs persist() or autosave(); while locked they put the stored set
     back (keyboard edits included), keeping only which block is active. */
  st.snapBack = () => {
    const s = st.LOCKED_SRC, active = st.S?.active || 0;
    if (!s) return;
    st.S = { title: s.name || '', champs: s.champions || [], active, plan: lib().normalisePlan(s.plan),
             blocks: (s.blocks || []).length ? structuredClone(s.blocks) : st.blank().blocks };
    st.R = s.runes ? Object.assign({}, st.blankRunes(), structuredClone(s.runes)) : st.blankRunes();
    st.emit();
  };

  // the server's row key (api._set_id), so a name that only collides once slugged counts as taken
  const slugId = (n, p) => `${n.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'set'}@${p}`;
  st.copyAuto = () => {
    st.snapBack();   // copy the stored set, never a half-edited view of it
    let name = st.S.title.replace(/^Auto\s+/i, '').trim() || 'My build';
    const ids = new Set(st.SAVES.map(s => s.id));
    while (ids.has(slugId(name, st.LIVE_PATCH))) name += ' copy';
    const src = st.LOCKED_SRC;
    st.S.title = name;
    st.LOCKED = false;
    st.LOCKED_SRC = null;
    st.OWNED = null;
    st.emit();
    return st.saveSet().then(ok => {
      if (ok) { st.renderAll(); return ok; }
      st.LOCKED = true; st.LOCKED_SRC = src; st.snapBack();   // failed: back to the locked Auto set
      return ok;
    });
  };

  st.bootSet = () => {
    st.LOCKED = false;
    st.LOCKED_SRC = null;
    if (st.PARAMS.get('new')) { st.S = st.blank(); st.R = st.blankRunes(); st.OWNED = null; st.persist(); return; }
    const want = st.PARAMS.get('set');
    if (!want) return;
    const s = (st.SETS0.sets || []).find(x => x.id === want);
    if (s) st.loadSet(s);
  };

  /* ── the column ───────────────────────────────────────────────────────────── */
  /* A drag inside the set MOVES; a drag from the shop or from a build path ADDS.
     The payload says which: "move:<bi>:<ii>" is a slot leaving its block, anything
     else is an item id. Nothing here reads the DOM for the source, because the
     drop can land in a different block than the one the drag started in. */
  const slotUnder = (e, block) => {
    const slot = e.target.closest('.slot');
    return slot && block.contains(slot) ? slot : null;
  };
  const clearOver = () => {
    for (const b of document.querySelectorAll('.block.over')) b.classList.remove('over');
    for (const s of document.querySelectorAll('.slot.before')) s.classList.remove('before');
  };

  // A locked (Auto) set takes no drop: without preventDefault the browser refuses it.
  const onBlocksDragOver = e => {
    const block = e.target.closest('.block');
    if (!block || st.LOCKED) return;
    e.preventDefault();
    clearOver();
    block.classList.add('over');
    // the drop lands in FRONT of the slot under the pointer, so mark that slot:
    // dropping a reorder with no landing mark is dropping it blind
    const hit = slotUnder(e, block);
    if (hit) hit.classList.add('before');
  };
  const onBlocksDragLeave = e => {
    if (!e.relatedTarget || !e.currentTarget.contains(e.relatedTarget)) clearOver();
  };
  const onBlocksDrop = e => {
    const block = e.target.closest('.block');
    if (!block || st.LOCKED) return;
    e.preventDefault();
    clearOver();

    const payload = e.dataTransfer.getData('text/plain');
    const bi = +block.dataset.bi;
    const hit = slotUnder(e, block);
    const at = hit ? +hit.dataset.ii : null;      // null = the empty space past the last slot

    if (payload.startsWith('move:')) {
      const [, fb, fi] = payload.split(':');
      return st.moveItem(+fb, +fi, bi, at);
    }
    st.S.active = bi;
    st.addToBlock(payload, e.shiftKey ? 5 : 1, bi, at);
  };

  /* Dragging out of the set is a move within the set, never a removal: dropping a
     slot outside a block is a no-op, and the x is the only way an item leaves. */
  const onBlocksDragStart = hv => e => {
    const slot = e.target.closest('.slot');
    if (slot) {
      e.dataTransfer.setData('text/plain', `move:${slot.dataset.bi}:${slot.dataset.ii}`);
      e.dataTransfer.effectAllowed = 'move';
      slot.classList.add('dragging');
    }
    if (hv.onDragStart) hv.onDragStart(e);
  };
  const onBlocksDragEnd = e => {
    const slot = e.target.closest('.slot');
    if (slot) slot.classList.remove('dragging');
    for (const s of document.querySelectorAll('.slot.before')) s.classList.remove('before');
  };

  /* Clicking a slot READS it. It used to take the item back out, which meant looking
     at what you had built spent it one click at a time. */
  const onBlocksClick = e => {
    const S = st.S;
    // Locked: a slot click still reads the item; every editing control is inert.
    if (st.LOCKED && e.target.closest('[data-nt-bi],[data-rm-bi],[data-move],[data-kill]')) return;
    /* Before the x and before the slot's own read, because the note button sits
       inside the slot and both of those would swallow the click. */
    const nt = e.target.closest('[data-nt-bi]');
    if (nt) {
      const it = S.blocks[+nt.dataset.ntBi]?.items[+nt.dataset.ntIi];
      if (!it) return;
      const m = st.BY_ID.get(it.id);
      st.askNote({
        title: m ? m.n : 'This item',
        why: 'Shown when you hover this item on the saved build. Say when you buy '
           + 'it, what you skip for it, or what makes it wrong here.',
        value: it.note || '',
      }).then(note => {
        if (note === null) return;
        if (note) it.note = note; else delete it.note;
        st.sync();
      });
      return;
    }
    const rm = e.target.closest('[data-rm-bi]');
    if (rm) {
      const items = S.blocks[+rm.dataset.rmBi]?.items, ii = +rm.dataset.rmIi;
      if (!items?.[ii]) return;
      if (items[ii].count > 1) items[ii].count--; else items.splice(ii, 1);
      return st.sync();
    }
    const slot = e.target.closest('.slot');
    if (slot) {
      const it = S.blocks[+slot.dataset.bi]?.items[+slot.dataset.ii];
      S.active = +slot.dataset.bi;
      if (it) st.inspect(it.id);
      return st.sync();
    }
    const move = e.target.closest('[data-move]');
    if (move) {
      const i = +move.dataset.move, j = i + +move.dataset.dir;
      if (j < 0 || j >= S.blocks.length) return;
      [S.blocks[i], S.blocks[j]] = [S.blocks[j], S.blocks[i]];
      S.active = j;
      return st.sync();
    }
    const kill = e.target.closest('[data-kill]');
    if (kill) {
      S.blocks.splice(+kill.dataset.kill, 1);
      S.active = Math.min(S.active, S.blocks.length - 1);
      return st.sync();
    }
    const block = e.target.closest('.block');
    if (block && !e.target.closest('input')) { S.active = +block.dataset.bi; st.sync(); }
  };

  const onBlocksKeyDown = e => {
    const slot = e.target.closest('.slot');
    if (!slot || (e.key !== 'Enter' && e.key !== ' ')) return;
    e.preventDefault();
    const it = st.S.blocks[+slot.dataset.bi]?.items[+slot.dataset.ii];
    if (it) st.inspect(it.id);
  };

  /* A build-path node drags into a block like a shop tile does: the part you just
     decided you wanted is right there, and going back to find it in the shop is a
     trip you should not have to make. */
  const onInspectClick = e => {
    if (e.target.closest('#insClose')) return st.inspect(null);
    if (e.target.closest('#insAdd')) return st.addToBlock(st.INSPECT, 1);
    const node = e.target.closest('[data-node]');
    if (node) st.inspect(node.dataset.node);          // walks the path, never adds
  };
  const onInspectDragStart = hv => e => {
    const node = e.target.closest('[data-node]');
    if (node) {
      e.dataTransfer.setData('text/plain', node.dataset.node);
      e.dataTransfer.effectAllowed = 'copy';
      node.classList.add('dragging');
    }
    if (hv.onDragStart) hv.onDragStart(e);
  };
  const onInspectDragEnd = e => {
    const node = e.target.closest('[data-node]');
    if (node) node.classList.remove('dragging');
  };

  /* A build-path node reads itself: name, what it gives, what it costs. It used to
     be a bare 38px icon with the whole thing in a title attribute, which meant the
     path was unreadable without hovering every square. Draggable, so the component
     you decided you wanted goes straight into a block from here. */
  const pathNode = (id, self, n) => {
    const i = st.BY_ID.get(String(id));
    if (!i) return null;
    return (
      <button type="button" className={`node${self ? ' self' : ''}`} data-node={i.id} draggable={true} key={n}>
        <img src={i.u} alt="" />
        <span className="nn"><strong>{i.n}</strong>
          <span>{i.st.join(' · ') || i.k}</span></span>
        <span className="ng">{i.g}g</span>
      </button>
    );
  };

  function Inspector({ hoverNodes }) {
    const ref = useRef(null);
    /* scrolled after the commit, because the panel is hidden until this render */
    useEffect(() => {
      if (st.scrollInspect && ref.current) {
        st.scrollInspect = false;
        ref.current.scrollIntoView({ block: 'nearest' });
      }
    });
    const hv = hoverNodes || {};
    const i = st.INSPECT ? st.BY_ID.get(st.INSPECT) : null;

    let body = null;
    if (i) {
      const stats = st.statsDL(i);
      const passives = i.ps.length
        ? i.ps.map(b => `<p class="pas">${b.h ? `<b>${st.esc(b.h)}</b>` : ''}${st.withRatios(st.esc(b.t))}</p>`).join('')
        : (stats ? '' : '<p class="empty-note">No passive or active effect.</p>');

      // two steps in each direction, so a component shows what it feeds and a legendary
      // shows the parts and the parts of the parts
      const up = i.to;
      const upUp = [...new Set(up.flatMap(x => st.BY_ID.get(x)?.to || []))];
      const down = i.f;
      const downDown = [...new Set(down.flatMap(x => st.BY_ID.get(x)?.f || []))];
      const rail = key => <div className="tier rail-arrow" key={key}><span className="arrow">{'↑'}</span></div>;
      const tier = (key, lab, ids, self) => (
        <div className="tier" key={key}><span className="lab">{lab}</span>
          {ids.map((x, n) => pathNode(x, self, n))}</div>);
      const target = st.S.blocks[st.S.active];

      body = (
        <React.Fragment>
          <div className="ins-top">
            <img src={i.u} alt="" />
            <div><h3>{i.n}</h3><p className="sub"><b>{i.g.toLocaleString()}</b>{` gold · ${i.k}`}</p></div>
            {target ? <button type="button" className="put" id="insAdd">{`Add to ${target.type || 'block'}`}</button> : null}
            <button type="button" className="x" id="insClose" aria-label="Close details">{'×'}</button>
          </div>
          <div className="ins-body">
            {/* every piece of this string is built from esc()'d catalog text and the baker's fixed
                vocabulary (statsDL, figsHTML, withRatios), the same strings the hover card takes */}
            <div className="ins" dangerouslySetInnerHTML={{ __html: stats + st.figsHTML(i.id) + passives }} />
            {(up.length || down.length) ? (
              <div className="tree">
                {upUp.length ? tier('uu', 'then into', upUp) : null}
                {upUp.length ? rail('uur') : null}
                {up.length ? tier('u', 'Builds into', up) : null}
                {up.length ? rail('ur') : null}
                {tier('s', 'This item', [i.id], true)}
                {down.length ? rail('dr') : null}
                {down.length ? tier('d', 'Built from', down) : null}
                {downDown.length ? rail('ddr') : null}
                {downDown.length ? tier('dd', 'which need', downDown) : null}
              </div>
            ) : <p className="empty-note">Bought whole. It has no build path.</p>}
          </div>
        </React.Fragment>
      );
    }

    return (
      <aside className="inspect" id="inspect" hidden={!i} aria-live="polite" ref={ref}
             onClick={onInspectClick} onDragStart={onInspectDragStart(hv)} onDragEnd={onInspectDragEnd}
             onMouseOver={hv.onMouseOver} onFocus={hv.onFocus} onMouseLeave={hv.onMouseLeave}
             onBlur={hv.onBlur} onScrollCapture={hv.onScrollCapture}>
        {body}
      </aside>
    );
  }

  function Slot({ bi, it, ii, mark }) {
    const m = st.BY_ID.get(it.id);
    const name = m ? m.n : it.id;
    return (
      <div className="slot" data-bi={bi} data-ii={ii} draggable={true} role="button" tabIndex={0}
           data-noted={it.note ? '' : undefined} data-first={mark || undefined}
           aria-current={String(it.id === st.INSPECT)}>
        <img src={m ? m.u : ''} alt={name} />
        {m ? <span className="sgold">{m.g}</span> : null}
        {it.count > 1 ? <span className="count">{it.count}</span> : null}
        <button type="button" className="nt" data-nt-bi={bi} data-nt-ii={ii}
                aria-label={(it.note ? 'Edit the note on ' : 'Add a note to ') + name}>{'≡'}</button>
        <button type="button" className="rm" data-rm-bi={bi} data-rm-ii={ii}
                aria-label={`Take one ${name} out`}>{'×'}</button>
      </div>
    );
  }

  function SavedSets() {
    if (!st.SAVES.length)
      return <p className="none">Nothing saved yet. Build a set and hit Save to log.</p>;
    // grouped by name, so one set's patch history reads as one thing
    const byName = new Map();
    for (const s of st.SAVES) {
      if (!byName.has(s.name)) byName.set(s.name, []);
      byName.get(s.name).push(s);
    }
    return (
      <ul>{[...byName].map(([name, versions]) => versions
        .sort((a, b) => (b.patch || '').localeCompare(a.patch || '', undefined, { numeric: true }))
        .map((s, n) => {
          const items = s.blocks.reduce((a, b) => a + b.items.reduce((x, i) => x + i.count, 0), 0);
          const where = [s.champion, s.role].filter(Boolean).join(' ');
          return (
            <li key={s.id}>
              <span className="nm"><strong>{n === 0 ? name : ''}</strong>
                <span>{`patch ${s.patch} · ${plural(s.blocks.length, 'block')} · ${plural(items, 'item')}${
                  where ? ` · ${where}` : ''}${s.forkedFrom ? ' · carried forward' : ''}`}</span></span>
              <button type="button" data-load={s.id}>Load</button>
              <button type="button" className="del" data-drop={s.id}
                      aria-label={`Delete ${name} on patch ${s.patch}`}>Delete</button>
            </li>
          );
        }))}</ul>
    );
  }

  const onSavesClick = e => {
    const load = e.target.closest('[data-load]');
    if (load) {
      const s = st.SAVES.find(x => x.id === load.dataset.load);
      if (!s) return;
      if (st.S.blocks.some(b => b.items.length) && !confirm('Load this set? The one open now is replaced.')) return;
      st.loadSet(s);
      if (s.champion && st.STATS.champions[s.champion]) {
        st.M.champ = s.champion;
        st.fillRoleSelect();
        if (s.role && st.STATS.champions[s.champion].roles[s.role]) st.M.role = s.role;
        st.saveMeta();
      }
      st.renderAll();
      return st.renderMeta();
    }
    const drop = e.target.closest('[data-drop]');
    if (drop) {
      const s = st.SAVES.find(x => x.id === drop.dataset.drop);
      if (!s || !confirm(`Delete the patch ${s.patch} version of "${s.name}"?`)) return;
      fetch(`api/sets/${encodeURIComponent(s.id)}`, { method: 'DELETE' })
        .then(() => st.fetchSaves())
        .catch(err => { alert(`Could not delete that: ${err.message}`); });
    }
  };

  const onCopy = () => {
    const text = JSON.stringify(st.buildSet(), null, 2);
    Promise.resolve().then(() => navigator.clipboard.writeText(text)).catch(() => {
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.append(ta);
      ta.select();
      document.execCommand('copy');
      ta.remove();
    }).then(() => {
      st.copied = true;
      st.emit();
      setTimeout(() => { st.copied = false; st.emit(); }, 1300);
    });
  };

  const onImport = () => {
    const raw = prompt('Paste an item set JSON to load it for editing:');
    if (!raw) return;
    let j;
    try { j = JSON.parse(raw); } catch { return alert('That is not valid JSON.'); }
    if (!Array.isArray(j.blocks)) return alert('No "blocks" list in there, so it is not an item set.');
    const blocks = j.blocks.map(b => ({
      type: b.type || 'Items',
      items: (b.items || []).filter(i => st.BY_ID.has(String(i.id)))
        .map(i => ({ id: String(i.id), count: Math.max(1, i.count || 1) })),
    }));
    const dropped = j.blocks.reduce((n, b) => n + (b.items || []).length, 0)
      - blocks.reduce((n, b) => n + b.items.length, 0);
    st.LOCKED = false;
    st.LOCKED_SRC = null;
    st.S = {
      title: j.title || '',
      champs: (j.associatedChampions || []).map(Number).filter(k => st.BY_KEY.has(k)),
      active: 0,
      // an item set carries no plan, and keeping the open one would hang a skill
      // order off a build it was never written for
      plan: lib().blankPlan(),
      blocks: blocks.length ? blocks : st.blank().blocks,
    };
    st.renderAll();
    if (dropped) alert(`Loaded. ${plural(dropped, 'item')} dropped: not sold in ranked Summoner's Rift.`);
  };

  const onReset = () => {
    if (!confirm('Start a new set? Anything not saved to the log is discarded.')) return;
    st.S = st.blank();
    st.R = st.blankRunes();
    st.OWNED = null;
    st.LOCKED = false;
    st.LOCKED_SRC = null;
    st.seedRunes();
    st.renderAll();
    st.renderRunes();
    st.showStep('items');
  };

  /* Duplicate is the other half of renaming in place: a rename now edits the row
     you are on, so branching a variant off a build needs its own button rather
     than the old accident of retyping the name. It drops OWNED and saves under a
     new name, which the (name, patch) keying files as a new row, and leaves you
     editing the copy - the variant is what you opened this for. */
  const onDupe = () => {
    const from = st.S.title.trim();
    if (!from) return alert('Name this set first, then duplicate it.');
    const name = (prompt('Name for the duplicate:', `${from} copy`) || '').trim();
    if (!name || name.toLowerCase() === from.toLowerCase()) return;
    st.S.title = name;
    st.OWNED = null;
    st.emit();
    st.saveSet().then(ok => { if (ok) st.renderAll(); });
  };

  function Blocks({ hoverSlots, hoverNodes }) {
    st.useStore();
    // Escape closes the inspector from anywhere on the page, as the plain page's
    // document listener did
    useEffect(() => {
      const onKey = e => { if (e.key === 'Escape' && st.INSPECT) st.inspect(null); };
      document.addEventListener('keydown', onKey);
      return () => document.removeEventListener('keydown', onKey);
    }, []);
    // body.locked switches off every edit surface in CSS (forge.html) while an Auto set is open
    useEffect(() => { document.body.classList.toggle('locked', !!st.LOCKED); });
    if (!st.loaded || !st.S) return null;

    const S = st.S, hs = hoverSlots || {};
    const only = S.blocks.length === 1;
    const total = S.blocks.reduce((a, b) => a + b.items.reduce((x, i) => x + i.count, 0), 0);
    const set = st.buildSet();
    const outN = set.blocks.reduce((a, b) => a + b.items.reduce((x, i) => x + i.count, 0), 0);
    /* Which slots the shop's figures are read out of - one or two, whichever the
       Core block holds. Gated on there being a reading to be read at all: with no
       champion picked nothing is fetched, and a marker saying the shop is being read
       out of these items would be describing a request that never goes out. */
    const core = st.current() ? st.coreSlot() : null;

    return (
      <section className="col col-set">
        {/* Docked above the set rather than above the shop: it opens and closes on
            every click, and over the shop that meant a thousand tiles jumping up and
            down the moment you read a second item. Above the set, nothing below it
            is something you are scanning. */}
        <Inspector hoverNodes={hoverNodes} />

        <div className="col-head">
          <h2>Your set</h2>
          <span className="count" id="setCount">{`${plural(S.blocks.length, 'block')} · ${plural(total, 'item')}`}</span>
        </div>
        <div className="chips" id="champs" onClick={e => {
          const chip = e.target.closest('[data-champ]');
          if (!chip) return;
          S.champs = S.champs.filter(k => k !== +chip.dataset.champ);
          st.emit(); st.persist();
        }}>
          {S.champs.map(k => {
            const c = st.BY_KEY.get(k);
            return c ? (
              <button type="button" className="chip" data-champ={k} title={`Remove ${c.n}`} key={k}>
                <img src={c.u} alt="" />{` ${c.n}`}</button>) : null;
          })}
        </div>
        <div id="blocks" onClick={onBlocksClick} onKeyDown={onBlocksKeyDown}
             onDragOver={onBlocksDragOver} onDragLeave={onBlocksDragLeave} onDrop={onBlocksDrop}
             onDragStart={onBlocksDragStart(hs)} onDragEnd={onBlocksDragEnd}
             onMouseOver={hs.onMouseOver} onFocus={hs.onFocus} onMouseLeave={hs.onMouseLeave}
             onBlur={hs.onBlur} onScrollCapture={hs.onScrollCapture}>
          {S.blocks.map((b, bi) => {
            /* A slot carries its own gold, its own count and its own x. The block total
               that used to sit under the row is gone: what a block costs is not a number
               anyone builds against, and it pushed the next block down every time an item
               landed. */
            const marks = core && core.bi === bi ? core.ids.map((id, pos) => st.condState(id, pos)) : [];
            return (
              <div className="block" data-bi={bi} data-active={String(bi === S.active)} key={bi}>
                <div className="bhead">
                  <input value={b.type} data-name={bi} placeholder="Block name" aria-label="Block name"
                         onChange={e => { S.blocks[bi].type = e.target.value; st.emit(); st.persist(); }} />
                  <button type="button" data-move={bi} data-dir="-1" title="Move up" aria-label="Move block up"
                          disabled={bi === 0}>&uarr;</button>
                  <button type="button" data-move={bi} data-dir="1" title="Move down" aria-label="Move block down"
                          disabled={bi === S.blocks.length - 1}>&darr;</button>
                  <button type="button" className="kill" data-kill={bi} title="Delete block" aria-label="Delete block"
                          disabled={only}>{'×'}</button>
                </div>
                <div className="slots" data-hint="Drag items here from the shop.">
                  {b.items.map((it, ii) => (
                    <Slot bi={bi} it={it} ii={ii} mark={marks[ii]} key={ii} />))}
                </div>
                {marks.length ? (
                  <p className="fnote" data-state={marks[0]}>{`↑ ${st.CORE_NOTE(marks[0], marks[1] || '')}`}</p>
                ) : null}
              </div>
            );
          })}
        </div>
        <div className="actions"><button type="button" id="addBlock" onClick={() => {
          S.blocks.push({ type: 'New block', items: [] });
          S.active = S.blocks.length - 1;
          st.sync();
        }}>Add block</button></div>
        <p className="help">
          <b>Click</b> any item, in the shop or in a block, to read it: stats, passives, both
          sources' figures and its build path. Clicking never changes the set.{' '}
          <b>Drag</b> to change it {'\u2014'} from the shop or from the build path into a block to add,
          and within or between blocks to reorder. Hold <kbd>Shift</kbd> while you drop from the
          shop to add five. The <b>{'×'}</b> on a slot takes one back.
        </p>

        <div className="col-head" style={{ marginTop: '6px' }}>
          <h2>Export</h2>
          <span className="count" id="outCount">{set.blocks.length
            ? `${plural(set.blocks.length, 'block')}, ${plural(outN, 'item')}`
            : 'nothing to export yet'}</span>
        </div>
        <div className="actions">
          <button type="button" className="btn-primary" id="copy" disabled={!set.blocks.length}
                  onClick={onCopy}>{st.copied ? 'Copied' : 'Copy JSON'}</button>
          {!st.LOCKED && <button type="button" id="save" onClick={e => { st.saveSet(e); }}>{st.savedFlash ? 'Saved' : 'Save to log'}</button>}
          {!st.LOCKED && <button type="button" id="dupe" onClick={onDupe}>Duplicate</button>}
          <button type="button" id="import" onClick={onImport}>Import...</button>
          <button type="button" id="reset" onClick={onReset}>New set</button>
        </div>
        <pre id="out">{JSON.stringify(set, null, 2)}</pre>
        <ol className="steps">
          <li><span>Copy the JSON above.</span></li>
          <li><span>In League, open <b>Collection {'→'} Items</b>.</span></li>
          <li><span>Hit <b>Import</b> and paste. The set is yours.</span></li>
        </ol>

        <div className="col-head" style={{ marginTop: '6px' }}><h2>Saved sets</h2></div>
        <div className="saves" id="savesBody" onClick={onSavesClick}><SavedSets /></div>
      </section>
    );
  }

  UI.Blocks = Blocks;
})();
