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

  function PatchPage() {
    const [notes, setNotes] = useState(null);
    const [tab, setTab] = useState(0);

    useEffect(() => {
      window.__FORGE.notes.then(setNotes);
    }, []);

    const sections = notes ? (notes.sections || []).filter(s => RIFT.includes(s.name)) : [];
    const all = sections.reduce((a, s) => a.concat(s.entries), []);
    const n = t => all.filter(e => e.triage === t).length;
    const loaded = notes !== null;
    const baked = loaded && sections.length > 0;

    return (
      <React.Fragment>
        <ForgeUI.Bar current="patch"
          act={<a className="act" id="src" target="_blank" rel="noopener"
                  href={baked ? (notes.url || '#') : undefined}>Riot&rsquo;s notes</a>}>
          <span className="meta" id="patchTag">{baked ? `patch ${notes.patch}` : ''}</span>
          <span className="meta"></span>
        </ForgeUI.Bar>

        <div className="wrap">
          <div className="lede">
            <h2 id="title">{baked
              ? `Patch ${notes.patch}${notes.date ? ` · ${notes.date}` : ''}`
              : 'Patch notes'}</h2>
            {/* no explainer blurb (forge/CLAUDE-chrome.md): only loading and the empty state */}
            {!baked ? <p id="lede" className="quiet">{!loaded ? 'Loading…'
              : 'No patch notes are baked yet. Run bake_patchnotes.py.'}</p> : null}
          </div>

          <div className="tally" id="tally">
            {baked ? [['buff', n('buff')], ['nerf', n('nerf')], ['rework', n('rework')]]
              .filter(p => p[1])
              .map(p => (
                <span className={p[0]} key={p[0]}><b>{p[1]}</b> {p[0]}{p[1] === 1 ? '' : 's'}</span>
              )) : null}
          </div>

          <div className="bar">
            <nav className="tabs" id="tabs">
              {baked ? sections.map((sec, i) => (
                <button type="button" data-i={i} key={sec.name} aria-pressed={i === tab}
                        onClick={() => setTab(i)}>{sec.name}{' '}
                  <span className="n">{sec.entries.length}</span></button>
              )) : null}
            </nav>
          </div>

          <div className="entries" id="body">
            {baked ? sections[tab].entries.map((e, i) => <Entry e={e} key={`${tab}:${i}`} />) : null}
          </div>
        </div>
      </React.Fragment>
    );
  }

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

  ReactDOM.createRoot(document.getElementById('forge-root')).render(<Root />);
})();
