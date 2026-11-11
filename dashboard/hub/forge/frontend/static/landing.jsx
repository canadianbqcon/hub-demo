/* landing.jsx - the Forge front door body, as React.

   Same DOM and classes as the plain page's inline module (landing.html): ForgeUI.Bar for
   the top bar, one card per champion, role chips that cycle the shelf and re-aim the card's
   two footer links, shelf rows that pop the build overlay. The overlay itself is
   build-overlay.jsx, which reaches the build-overlay.js logic through window.ForgeLib
   (forge-lib-bridge.js), so its fork POST, DELETE and Copy JSON bodies are unchanged.
   Mount marker: data-react-mounted="forge-landing" on #forge-root. */
window.ForgeUI = window.ForgeUI || {};

(() => {
  const { useState, useEffect, useRef } = React;

  const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;

  /* ForgeLib arrives from a module script that runs ahead of this one; the event covers a late reader. */
  const withLib = cb => {
    if (window.ForgeLib) cb();
    else window.addEventListener('forgelib:ready', cb, { once: true });
  };

  /* A card opens on the role you have most built in, not on the role the champion
     is most PLAYED in: the shelf you reach for is your own. The played-most role
     only breaks the tie, and it is what an empty shelf opens on so a first build
     starts in the sane lane. */
  const openingRole = c => {
    const counted = c.roles.map(r => ({ role: r.role, n: c.sets.filter(s => s.role === r.role).length }));
    const best = counted.filter(r => r.n).sort((a, b) => b.n - a.n)[0];
    return best ? best.role : (c.lead || counted[0]?.role || '');
  };

  const buildHref = (champ, role, id) =>
    `c/${encodeURIComponent(champ)}/${encodeURIComponent(role)}`
    + (id ? `#${encodeURIComponent(id)}` : '');

  /* The ids of the newest Auto set per source key (autoKey, else name), by patch. */
  const latestAuto = sets => {
    const best = new Map();
    for (const s of sets) {
      if (!s.auto) continue;
      const k = `${s.role}|${s.autoKey || s.name}`, b = best.get(k);
      if (!b || (s.patch || '').localeCompare(b.patch || '', undefined, { numeric: true }) > 0) best.set(k, s);
    }
    return new Set([...best.values()].map(s => s.id));
  };

  function Build({ c, s, live, runedex, onOpen }) {
    const ks = s.keystone ? runedex.runes?.[String(s.keystone)] || null : null;
    const bits = [
      s.items ? `${plural(s.blocks, 'block')} · ${plural(s.items, 'item')}` : 'runes only',
      s.forkedFrom ? 'carried forward' : null,
    ].filter(Boolean);
    return (
      <a className="build" data-set={s.id} href={buildHref(c.name, s.role || openingRole(c), s.id)}
         onClick={e => {
           if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;  // let the link be a link
           e.preventDefault();
           onOpen(s.id);
         }}>
        {ks ? <img src={ks.icon} alt="" /> : <i className="ks-none"></i>}
        <span className="nm"><strong>{s.name}</strong><span className="sub">{bits.join(' · ')}</span></span>
        {s.patch && s.patch !== live ? <span className="patch">{s.patch}</span> : <span></span>}
      </a>
    );
  }

  /* The card keeps its chosen role in state keyed by champion, so a reload that swaps in
     fresh data does not bounce you back to the card's default. */
  // A set carried forward to a newer patch replaces the one it came from on the shelf.
  // An Auto set is replaced by the newer-patch Auto set with the same source key.
  // Shared by the role chips and the rail's pool counts, so the two agree.
  const isCurrent = c => {
    const newest = latestAuto(c.sets);
    const replaced = new Set([...c.sets.map(s => s.forkedFrom).filter(Boolean),
      ...c.sets.filter(s => s.auto && !newest.has(s.id)).map(s => s.id)]);
    return s => !replaced.has(s.id);
  };

  function Card({ c, live, runedex, onOpen, onBuilt, tab, focus }) {
    const [building, setBuilding] = useState(false);
    const [err, setErr] = useState(null);
    const [picked, setPicked] = useState(tab || null);
    // a role tab turns every shown card to that role's shelf; its chips still switch after
    useEffect(() => { if (tab) setPicked(tab); }, [tab]);
    // a rail click under a lane heading turns this card to that lane
    useEffect(() => { if (focus && focus.role) setPicked(focus.role); }, [focus]);
    /* Auto sets fold away once he has builds of his own on the role (mark 2026-11-10-042636 #4) */
    const [autoOpen, setAutoOpen] = useState(false);
    const [poolBusy, setPoolBusy] = useState(false);
    const [old, setOld] = useState(false);
    const on = picked && c.roles.some(r => r.role === picked) ? picked : openingRole(c);
    const current = isCurrent(c);
    const all = c.sets.filter(s => s.role === on)
      .sort((a, b) => (b.updated || '').localeCompare(a.updated || ''));
    const shown = old ? all : all.filter(current);
    // His builds and Auto sets sit on separate shelves: Auto is Autobuild's, read-only.
    const mine = shown.filter(s => !s.auto), auto = shown.filter(s => s.auto);
    const hidden = all.length - all.filter(current).length;
    const foldAuto = mine.length > 0 && auto.length > 0;
    const inPool = (c.poolRoles || []).includes(on);
    /* Mark 2026-11-10-042636 #2: which lanes this champion is in his pool for; the rail sorts by it. */
    const togglePool = () => {
      setPoolBusy(true); setErr(null);
      fetch('api/pool-roles', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ champion: c.name, role: on, on: !inPool }) })
        .then(r => { if (!r.ok) throw new Error(`request failed (${r.status})`); return onBuilt(); })
        .catch(e => setErr(`Pool not changed. ${e.message || e}`))
        .then(() => setPoolBusy(false));
    };
    const autobuild = () => {
      setBuilding(true); setErr(null);
      fetch('api/autobuild', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ champion: c.name, role: on }) })
        .then(r => r.json().catch(() => ({})).then(j => { if (!r.ok) throw new Error(j.error || `request failed (${r.status})`); return j; }))
        .then(j => {
          // Nothing saved is still a 200: say why, as the champion page does.
          if (!(j.saved || []).length) setErr('Nothing built. ' + ((j.outcomes || []).map(o => `${o.source === o.key ? o.source : `${o.source} ${o.key}`}: ${o.state}${o.why ? `, ${o.why}` : ''}`).join('; ') || 'no source had a build'));
          onBuilt();
        })
        .catch(e => setErr(`Autobuild failed. ${e.message || e}`))
        .then(() => setBuilding(false));
    };
    return (
      <article className="card" data-champ={c.name}>
        <div className="card-head">
          {c.portrait ? <img src={c.portrait} alt="" /> : <i></i>}
          <div>
            <h3>{c.name}</h3>
            <div className="roles">
              {c.roles.map(r => {
                const n = c.sets.filter(s => s.role === r.role && current(s)).length;
                return (
                  <button type="button" className={`role${n ? '' : ' empty'}`} data-role={r.role}
                          key={r.role} aria-pressed={r.role === on} onClick={() => setPicked(r.role)}
                          aria-label={r.role} title={r.role}>
                    <ForgeUI.RoleGlyph role={r.role} /></button>
                );
              })}
            </div>
            {/* no build style chips on the card (mark 2026-11-10-042636 #5): the champion page header carries them */}
          </div>
        </div>
        <section className="shelf">
          <h4>My builds <span className="where">{on}</span>
            <button type="button" className="inpool" aria-pressed={inPool} disabled={poolBusy} onClick={togglePool}
                    title={inPool ? `In your ${on} pool. Click to take ${c.name} out of it.` : `Add ${c.name} to your ${on} pool`}>
              {inPool ? `In ${on} pool` : `Add to ${on} pool`}</button></h4>
          {mine.length
            ? <div className="builds">{mine.map(s => (
                <Build c={c} s={s} live={live} runedex={runedex} onOpen={onOpen} key={s.id} />))}</div>
            : <p className="quiet">No {on} builds saved yet.</p>}
          {auto.length ? (foldAuto
            ? <h4><button type="button" className="fold" aria-expanded={autoOpen} onClick={() => setAutoOpen(!autoOpen)}>
                Auto <span className="where">{on}</span><span className="where">{auto.length}</span></button></h4>
            : <h4>Auto <span className="where">{on}</span></h4>) : null}
          {auto.length && (!foldAuto || autoOpen) ? <div className="builds">{auto.map(s => (
            <Build c={c} s={s} live={live} runedex={runedex} onOpen={onOpen} key={s.id} />))}</div> : null}
          {/* Shown until the role has a build of his or a live-patch Auto set: stale Auto
              sets have no carry-forward, so this is how they come up to the live patch. */}
          {all.some(s => !s.auto) || all.some(s => s.auto && s.patch === live) ? null
            : <button type="button" className="older" disabled={building} onClick={autobuild}>
                {building ? 'Building' : all.length ? 'Rebuild auto sets' : 'Autobuild'}</button>}
          {err ? <p className="quiet" role="status">{err}</p> : null}
          {hidden ? <button type="button" className="older" onClick={() => setOld(!old)}>
            {old ? 'Hide older patches' : `Show ${hidden} older patch${hidden === 1 ? '' : 'es'}`}</button> : null}
        </section>
        <div className="card-foot">
          <a className="open" href={buildHref(c.name, on)}>All {c.name} builds</a>
          <a className="fresh" href={`${buildHref(c.name, on)}/build?new=1`}>New set</a>
        </div>
      </article>
    );
  }

  /* Build styles (build_styles.py): what is possible on the champion, not only what is
     popular. Bold is a main style, plain a common one, dashed a niche build. */
  const Styles = ({ list }) => (list || []).length ? (
    <div className="styles">{list.map(s => (
      <span className={`style ${s.tier}`} key={s.style}
            title={`${s.tier}: ${s.score} of the first three items in its best role, bought early in ${(s.games || 0).toLocaleString()} games`}>{s.style}</span>))}</div>) : null;

  /* The role tabs: All, then one per lane, each with how many pool champions play it.
     A tab narrows the cards and the roster to that lane and turns each card to its shelf. */
  const LANE_NAME = { top: 'Top', jungle: 'Jungle', mid: 'Mid', bot: 'Bot', support: 'Support' };
  function RoleTabs({ tab, onTab, counts }) {
    return (
      <nav className="roletabs" aria-label="Role">
        <button type="button" aria-pressed={!tab} onClick={() => onTab('')}>All</button>
        {ForgeUI.ROLES.map((r, i) => (
          <button type="button" key={r} aria-pressed={tab === r} disabled={!counts[i]} onClick={() => onTab(r)}>
            <ForgeUI.RoleGlyph role={r} />{LANE_NAME[r] || r}</button>))}
      </nav>);
  }

  /* Every champion past the pool: a tile per champion, a link per role it is played in
     (5%+ of its games), each to that champion's page. The search filters by name. */
  function Roster({ roster, tab }) {
    const [q, setQ] = useState('');
    const shown = roster.filter(c => c.name.toLowerCase().includes(q.trim().toLowerCase())
      && (!tab || c.roles.includes(tab)));
    return (
      <section className="roster" id="roster">
        <div className="roster-head">
          <h2>Every champion</h2>
          <input type="search" placeholder="Find a champion" aria-label="Find a champion"
                 value={q} onChange={e => setQ(e.target.value)} />
        </div>
        <div className="roster-grid">
          {shown.map(c => (
            <div className="tile" data-champ={c.name} key={c.name}>
              {/* lazy: ~170 portraits (~5 MB) sit below the fold; eager, they held the load event to 2 s */}
              {c.portrait ? <img src={c.portrait} alt="" loading="lazy" decoding="async" width="40" height="40" /> : <i></i>}
              <div>
                <a className="nm" href={buildHref(c.name, c.roles[0])}>{c.name}</a>
                <div className="roles">{c.roles.map(r => (
                  <a className="role" href={buildHref(c.name, r)} key={r} aria-label={r} title={r}>
                    <ForgeUI.RoleGlyph role={r} /></a>))}</div>
                <Styles list={c.styles} />
              </div>
            </div>))}
          {shown.length ? null : <p className="quiet">No champion matches “{q}”.</p>}
        </div>
      </section>
    );
  }

  function Landing() {
    /* data = { D, runedex, live }: set once the three head fetches and ForgeLib are all in */
    const [data, setData] = useState(null);
    /* the rail's search: filters the cards here; other pages land here with ?q= */
    const [query, setQuery] = useState(() => new URLSearchParams(location.search).get('q') || '');
    const [tab, setTab] = useState('');   // '' is every role
    const [focus, setFocus] = useState(null);   // the rail's last click: {name, role}
    /* Patch opens here, in place of the cards, not as a separate page (mark 2026-11-10-042636 #1).
       It rides the hash so Back returns to the cards and a link to /forge/#patch reopens it. */
    const viewOf = () => location.hash === '#patch' ? 'patch' : 'champions';
    const [view, setView] = useState(viewOf);
    const [notes, setNotes] = useState(null);
    useEffect(() => {
      const sync = () => setView(viewOf());
      window.addEventListener('hashchange', sync);
      return () => window.removeEventListener('hashchange', sync);
    }, []);
    useEffect(() => {
      if (view === 'patch' && !notes) window.__FORGE.notes.then(setNotes);
      const crumb = document.querySelector('[data-slot="crumb"]');
      if (crumb) crumb.textContent = 'forge · ' + view;
    }, [view]);
    const onSection = key => {
      if (key === 'champions') { if (view !== 'champions') history.pushState(null, '', location.pathname + location.search); setView('champions'); return true; }
      if (key === 'patch') { if (view !== 'patch') location.hash = 'patch'; setView('patch'); window.scrollTo(0, 0); return true; }
      return false;
    };
    const setsRef = useRef(new Map());
    const ovRef = useRef(null);
    const reloadRef = useRef(null);

    /* A fork or a delete changes the shelf AND the count on the role chip above it, so
       the card data is refetched; api/sets feeds the overlay's lookup. */
    reloadRef.current = () => {
      return Promise.all([
        fetch('api/sets').then(r => r.json()).catch(() => ({ sets: [] })),
        fetch('api/landing').then(r => r.json()).catch(() => null),
      ]).then(res => {
        setsRef.current = new Map((res[0].sets || []).map(s => [s.id, s]));
        if (!res[1]) return;
        setData(d => ({ D: res[1], runedex: d.runedex, live: d.live }));
      });
    };

    useEffect(() => {
      withLib(() => {
        Promise.all([window.__FORGE.landing, window.__FORGE.runes, window.__FORGE.sets]).then(res => {
          setsRef.current = new Map((res[2].sets || []).map(s => [s.id, s]));
          setData({ D: res[0], runedex: res[1], live: window.ForgeLib.shortPatch(res[0].catalogPatch) });
        });
      });
    }, []);

    /* A shelf row opens its build HERE, on the front door, rather than loading the
       champion page and letting that page open the same dialog off the hash. */
    const mounted = data !== null;
    useEffect(() => {
      if (!mounted) return;
      ovRef.current = window.ForgeUI.mountBuildOverlay({
        dialog: document.getElementById('ov'),
        runedex: data.runedex,
        live: data.live,
        onChanged: () => reloadRef.current(),
      });
      /* Warm the catalog while nothing is waiting on it, so the first pop-out draws its
         item icons immediately instead of stalling on the download. */
      window.ForgeLib.prefetchCatalog();
    }, [mounted]);

    const D = data ? data.D : null;
    const totalSets = D ? D.champions.reduce((a, c) => a + c.sets.length, 0) : 0;

    return (
      <React.Fragment>
        <ForgeUI.Bar current={view} act={<a className="act" href="edit">New set</a>} onSection={onSection}
          query={query} onQuery={setQuery} total={D ? totalSets : null} onPick={setFocus}
          pool={D ? D.champions.flatMap(c => {
            const cur = c.sets.filter(isCurrent(c));
            const roles = c.poolRoles || [];
            return roles.length
              ? roles.map(role => ({ name: c.name, img: c.portrait, role, n: cur.filter(s => s.role === role).length }))
              : [{ name: c.name, img: c.portrait, role: '', n: cur.length }];
          }) : null}>
          <span className="meta" id="statsPatch">{D?.patch ? `stats ${D.patch}` : ''}</span>
          <span className="meta" id="livePatch">{D?.catalogPatch ? `live ${D.catalogPatch}` : ''}</span>
        </ForgeUI.Bar>

        {view === 'patch' ? <ForgeUI.PatchBody notes={notes} /> :
        <div className="wrap">
          {/* No explainer blurb over the cards (mark 2026-11-05-173522 #1, sent back twice):
              the page opens on the tabs. Only loading and the empty pool get a line. */}
          {!D ? <p className="lede loading">Loading the pool…</p>
            : !D.champions.length
              ? <p className="lede">No statistics are baked yet. Run <b>bake_stats.py</b> to fill the pool.</p>
              : null}

          {D ? <RoleTabs tab={tab} onTab={setTab} counts={ForgeUI.ROLES.map(r => D.champions.filter(c => c.roles.some(x => x.role === r)).length)} /> : null}

          <div className="cards" id="cards">
            {D ? D.champions.filter(c => c.name.toLowerCase().includes(query.trim().toLowerCase())
                && (!tab || c.roles.some(r => r.role === tab))).map(c => (
              <Card c={c} live={data.live} runedex={data.runedex} key={c.name} tab={tab}
                    focus={focus && focus.name === c.name ? focus : null}
                    onOpen={id => ovRef.current.open(setsRef.current.get(id))}
                    onBuilt={() => reloadRef.current()} />)) : null}
          </div>
          {D?.roster?.length ? <Roster roster={D.roster} tab={tab} /> : null}
        </div>}
      </React.Fragment>
    );
  }

  /* Render errors land here; the plain page had no equivalent, so a failed render says so. */
  class Boundary extends React.Component {
    constructor(p) { super(p); this.state = { err: null }; }
    static getDerivedStateFromError(err) { return { err }; }
    componentDidCatch(err) { console.error('[forge-landing] render failed', err); }
    render() { return this.state.err ? <div className="hub-error">page failed to load</div> : this.props.children; }
  }

  function Root() {
    useEffect(() => {
      document.getElementById('forge-root').setAttribute('data-react-mounted', 'forge-landing');
    }, []);
    return <Boundary><Landing /></Boundary>;
  }

  ReactDOM.createRoot(document.getElementById('forge-root')).render(<Root />);
})();
