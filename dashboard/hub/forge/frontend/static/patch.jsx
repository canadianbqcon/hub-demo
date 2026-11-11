/* patch.jsx - the Forge patch-notes page body, as React.

   Same DOM and classes as the plain page's inline module (patch.html): the bar comes from
   ForgeUI.Bar (forge-bar.jsx), the notes from window.__FORGE.notes, the promise the head
   preflight started before any script ran. Read-only: no request is made from here.
   Mount marker: data-react-mounted="forge-patch" on #forge-root. */
window.ForgeUI = window.ForgeUI || {};

(() => {
  const { useState, useEffect } = React;

  /* Champions, Items, Runes and Systems are what touch a ranked Summoner's Rift
     build. Classic, ARAM: Mayhem, Arena and the bugfix list are all baked into the
     JSON and filtered out here - throwing them away at bake time would be the
     expensive mistake, and rendering them would put three other games on a page
     whose own title bar says Ranked Summoner's Rift. */
  const RIFT = ['Champions', 'Items', 'Runes', 'Systems'];

  /* Past this many characters COMBINED the two values of a WHOLE-value bullet stop
     sitting side by side and stack instead. Combined, not each: what has to fit is
     the entire `old -> new` line. */
  const SIDE_BY_SIDE_MAX = 62;

  /* One number that moved, or - when the whole value was replaced - the whole pair. */
  function Chip({ s, whole }) {
    const tall = whole && s.old.length + s.new.length > SIDE_BY_SIDE_MAX;
    return (
      <span className={`d${whole ? ' whole' : ''}${tall ? ' tall' : ''}`} data-v={s.v || ''}>
        <span className="was">{s.old}</span>
        <span className="ar">{'→'}</span>
        <span className="now">{s.new}</span>
      </span>
    );
  }

  function Delta({ c }) {
    const segs = c.segments || [{ t: 'chg', old: c.from, new: c.to, v: c.verdict }];
    /* a single segment covering the lot IS the whole-value case - nothing around
       it survived as context, so it gets the bordered, stackable treatment */
    const whole = segs.length === 1 && segs[0].t === 'chg';
    return segs.map((s, i) =>
      s.t === 'same' ? <span className="ctx" key={i}>{s.s}</span>
      : s.t === 'add' ? <span className="add" key={i}>{s.s}</span>
      : <Chip s={s} whole={whole} key={i} />);
  }

  function Rows({ changes }) {
    return (
      <dl className="rows">
        {changes.map((c, i) => {
          if (c.line !== undefined) {
            /* a flat bullet with no arrow: the field is a tag, not a column header */
            return [
              <dt key={`t${i}`}></dt>,
              <dd className="plain" key={`d${i}`}>
                {c.field ? <span className="tag">{c.field}</span> : null}{c.line}
              </dd>,
            ];
          }
          return [
            <dt key={`t${i}`}>{c.field || ''}</dt>,
            <dd key={`d${i}`}><Delta c={c} /></dd>,
          ];
        })}
      </dl>
    );
  }

  function Entry({ e }) {
    return (
      <article className="entry" data-triage={e.triage || 'rework'}>
        <h3>
          {e.icon ? <img src={e.icon} alt="" loading="lazy" /> : null}
          <span className="nm">{e.name}</span>
          <span className="tri">{e.triage || 'changed'}</span>
        </h3>
        {e.gist ? <p className="gist" title={e.context || ''}>{e.gist}</p> : null}
        <div className="sheet">
          {e.groups.map((g, gi) => (
            <div className="grp" key={gi}>
              {g.name ? (
                <h4>{g.icon ? <img src={g.icon} alt="" loading="lazy" /> : null}{g.name}</h4>
              ) : null}
              <Rows changes={g.changes} />
            </div>
          ))}
        </div>
      </article>
    );
  }

  /* Buffs, then nerfs, then reworks (mark 2026-11-10-043901 #2), each under its own
     heading, alphabetical inside. Anything untriaged sorts with the reworks. */
  const ORDER = [['buff', 'Buffs'], ['nerf', 'Nerfs'], ['rework', 'Reworks']];
  const triageOf = e => (e.triage === 'buff' || e.triage === 'nerf') ? e.triage : 'rework';

  /* A portrait ringed in its verdict colour; the name is the tooltip and alt text. */
  const Ico = ({ e }) => (
    <span className="phead-ico" data-triage={triageOf(e)} title={`${e.name} · ${triageOf(e)}`}>
      {e.icon ? <img src={e.icon} alt={e.name} loading="lazy" /> : null}
    </span>);

  /* "Nov 3, 2026 · 7 days ago" from the baked ISO date */
  function released(iso) {
    const d = new Date(`${iso}T12:00:00`);
    if (isNaN(d)) return iso;
    const ago = Math.max(0, Math.round((Date.now() - d) / 864e5));
    return `${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })} · ${
      ago === 0 ? 'today' : ago === 1 ? 'yesterday' : `${ago} days ago`}`;
  }

  /* The patch note body: header, section tabs, entries. Shared by /forge/patch and the
     landing page's inline Patch view, which hands it the same notes promise. */
  function PatchBody({ notes }) {
    const [tab, setTab] = useState(0);
    /* his pool: the landing's champion cards, the same list the rail draws. Both pages
       start the api/landing fetch in their head preflight. */
    const [pool, setPool] = useState(null);
    useEffect(() => {
      (window.__FORGE.landing || Promise.resolve({ champions: [] }))
        .then(d => setPool((d.champions || []).map(c => ({ name: c.name, roles: c.poolRoles || [] }))));
    }, []);
    const sections = notes ? (notes.sections || []).filter(s => RIFT.includes(s.name)) : [];
    const all = sections.reduce((a, s) => a.concat(s.entries), []);
    const n = t => all.filter(e => triageOf(e) === t).length;
    const loaded = notes !== null;
    const baked = loaded && sections.length > 0;
    const entries = baked ? sections[Math.min(tab, sections.length - 1)].entries : [];

    return (
      <div className="wrap pv">
        {/* Roster header (Workbench pick, mark 2026-11-10-043901 #1): title, then his pool,
            then every entry as a portrait under its verdict, so who changed reads before any card. */}
        <header className="phead">
          <div className="phead-top">
            <div className="phead-main">
              <p className="phead-kicker">Ranked Summoner&rsquo;s Rift</p>
              <h2 id="title">{baked ? `Patch ${notes.patch}` : 'Patch notes'}</h2>
              {baked && notes.date ? <p className="phead-date">Released {released(notes.date)}</p> : null}
              {/* no explainer blurb (forge/CLAUDE-chrome.md): only loading and the empty state */}
              {!baked ? <p id="lede" className="quiet">{!loaded ? 'Loading…'
                : 'No patch notes are baked yet. Run bake_patchnotes.py.'}</p> : null}
            </div>
            {baked && notes.url ? <a className="phead-src" href={notes.url} target="_blank" rel="noopener">Riot&rsquo;s notes &rarr;</a> : null}
          </div>
          {baked && pool ? (() => {
            const mine = all.filter(e => pool.some(p => p.name === e.name));
            return (
              <section className="phead-pool">
                <p className="phead-label">Your pool &middot; {mine.length} of {pool.length} changed</p>
                {mine.length ? mine.map(e => {
                  const roles = (pool.find(p => p.name === e.name) || {}).roles || [];
                  return (
                    <div className="phead-mine" data-triage={triageOf(e)} key={e.name}>
                      <Ico e={e} />
                      <div>
                        <p className="phead-mn">{e.name} <span className="tri">{triageOf(e)}</span>
                          {roles.length ? <span className="phead-roles">{roles.join(' · ')}</span> : null}</p>
                        {e.gist ? <p className="phead-gist" title={e.context || ''}>{e.gist}</p> : null}
                      </div>
                    </div>);
                }) : <p className="phead-none">Nothing in your pool moved this patch.</p>}
              </section>);
          })() : null}
          {baked ? (
            <div className="phead-roster" id="tally">
              {ORDER.filter(([t]) => n(t)).map(([t, label]) => (
                <div className="phead-grp" data-triage={t} key={t}>
                  <p className="phead-label">{label} <b>{n(t)}</b></p>
                  <div className="phead-icos">{all.filter(e => triageOf(e) === t).map(e => <Ico e={e} key={e.name} />)}</div>
                </div>))}
            </div>) : null}
        </header>

        <div className="bar">
          <nav className="tabs" id="tabs">
            {baked ? sections.map((sec, i) => (
              <button type="button" data-i={i} key={sec.name} aria-pressed={i === tab}
                      onClick={() => setTab(i)}>{sec.name}{' '}
                <span className="n">{sec.entries.length}</span></button>
            )) : null}
          </nav>
        </div>

        <div id="body">
          {ORDER.map(([t, label]) => {
            const group = entries.filter(e => triageOf(e) === t)
              .sort((x, y) => x.name.localeCompare(y.name));
            return group.length ? (
              <section className="tgroup" data-triage={t} key={`${tab}:${t}`}>
                <h3 className="tgroup-h">{label} <span className="n">{group.length}</span></h3>
                <div className="entries">{group.map((e, i) => <Entry e={e} key={i} />)}</div>
              </section>) : null;
          })}
        </div>
      </div>
    );
  }

  function PatchPage() {
    const [notes, setNotes] = useState(null);
    useEffect(() => { window.__FORGE.notes.then(setNotes); }, []);
    const baked = notes && (notes.sections || []).length;
    return (
      <React.Fragment>
        {/* Riot's link lives in the page header now, not twice */}
        <ForgeUI.Bar current="patch">
          <span className="meta" id="patchTag">{baked ? `patch ${notes.patch}` : ''}</span>
          <span className="meta"></span>
        </ForgeUI.Bar>
        <PatchBody notes={notes} />
      </React.Fragment>
    );
  }

  window.ForgeUI.PatchBody = PatchBody;

  /* Render errors land here; the plain page had no equivalent, so a failed render says so. */
  class Boundary extends React.Component {
    constructor(p) { super(p); this.state = { err: null }; }
    static getDerivedStateFromError(err) { return { err }; }
    componentDidCatch(err) { console.error('[forge-patch] render failed', err); }
    render() { return this.state.err ? <div className="hub-error">page failed to load</div> : this.props.children; }
  }

  function Root() {
    useEffect(() => {
      document.getElementById('forge-root').setAttribute('data-react-mounted', 'forge-patch');
    }, []);
    return <Boundary><PatchPage /></Boundary>;
  }

  // Only /forge/patch mounts itself; the landing page loads this file for PatchBody alone.
  const root = document.getElementById('forge-root');
  if (root && root.dataset.page === 'patch') ReactDOM.createRoot(root).render(<Root />);
})();
