/* forge-bar.jsx - Item Set Forge's own top bar and theme pop-out, as React.

   Forge keeps its own bar look: this renders the plain pages' <header class="topbar">
   markup and does not take part in the Hub theme switch. The theme pop-out is a
   straight port of theme-picker.js: the rail lists the five materials, the stage
   beside it renders the one under the pointer from the page's own components.
   Hover previews, click applies. The choice lives in localStorage `forge:theme`
   and is read back by the pre-paint snippet in each page's <head>.

   First Forge JSX file: it creates the namespace every other Forge file assigns into.
   Usage: <ForgeUI.Bar current="champions" act={<a className="act" ...>}>{metas}</ForgeUI.Bar>
   renders the whole shell (header, left rail, status pill); see Bar() below for the
   landing-only props. `current` is champions | patch | stats | draft | "" (the builder). */
window.ForgeUI = window.ForgeUI || {};

(() => {
  const { useState, useRef, useEffect } = React;

  const KEY = 'forge:theme';

  const THEMES = [
    {
      key: 'rift',
      name: 'Rift Standard',
      note: 'Cold near-monochrome. The shipped look.',
      say: 'Near-monochrome by design: item art is already riotously saturated, so the chrome '
         + 'stays out of its way. Cyan means state, gold means money, nothing else is coloured.',
    },
    {
      key: 'hextech',
      name: 'Hextech Foundry',
      note: 'Client navy, blueprint grid, gold hairlines.',
      say: 'The modern client, read as a workshop drawing. Gold moves to the edges where the '
         + 'client puts it, so a gold line never has to compete with the gold in the item art.',
    },
    {
      key: 'runic',
      name: 'Runic Bronze',
      note: 'Cast bronze, engraved. Square corners, patina green.',
      say: 'Runeterra before the client. Panels are cut into the surface rather than laid on it, '
         + 'corners are square because stone does not round, and the state colour is the patina '
         + 'in the grooves.',
    },
    {
      key: 'void',
      name: 'Void Static',
      note: 'Near-black violet, scanlines, acid green.',
      say: 'What the tool looks like running on something it should not be. The loudest theme '
         + 'here and deliberately the one you would not leave on all night.',
    },
    {
      key: 'frost',
      name: 'Frostguard',
      note: 'Glacial paper and navy ink. The light one.',
      say: 'The argument against this module’s own scene note: not every build happens at 11pm. '
         + 'The accent goes dark rather than bright, because on a light ground a pale cyan is not '
         + 'a state, it is a smudge.',
    },
  ];

  const KEYS = new Set(THEMES.map(t => t.key));
  let fadeTimer = 0;

  function currentTheme() {
    const t = document.documentElement.dataset.theme;
    return KEYS.has(t) ? t : 'rift';
  }

  /* The swap is a whole-page repaint, so it crossfades rather than snapping. The
     transition rule is carried by a class that is taken off again 300ms later. */
  function applyTheme(key) {
    const root = document.documentElement;
    if (!KEYS.has(key) || root.dataset.theme === key) return;
    root.classList.add('theming');
    root.dataset.theme = key;
    try { localStorage.setItem(KEY, key); } catch { /* private mode: the choice just does not stick */ }
    clearTimeout(fadeTimer);
    fadeTimer = setTimeout(() => root.classList.remove('theming'), 300);
  }

  /* The stage: a slice of the real page, in whichever theme is being looked at. */
  function Stage({ showing, applied }) {
    const t = THEMES.find(x => x.key === showing) || THEMES[0];
    const on = t.key === applied;
    return (
      <div className="tp-stage" data-theme={t.key}>
        <div className="tp-bar">
          <span className="tp-title">Item Set Forge</span>
          <span className="rift">Ranked Summoner&rsquo;s Rift</span>
          <span className="grow"></span>
          <span className="meta">patch 16.16</span>
        </div>

        <div className="patchstrip">
          <h3>Changed on 16.16, since the 16.15 statistics</h3>
          <div className="changes">
            <div className="change mine"><i></i><span className="lab"><span className="nm">Sundered Sky</span>
              <span className="fig">Health <span className="was">400</span> &rarr; 450</span></span></div>
            <div className="change"><i></i><span className="lab"><span className="nm">Black Cleaver</span>
              <span className="fig">Attack damage <span className="was">40</span> &rarr; 45</span></span></div>
          </div>
        </div>

        <div className="tp-figs">
          <span className="tp-fig acc"><b>+2.41</b><em>wpa, coachless</em></span>
          <span className="tp-fig"><b>54.5%</b><em>win rate, 3rd item</em></span>
          <span className="tp-fig gold"><b>3200</b><em>gold</em></span>
        </div>

        <div className="tp-controls">
          <input placeholder="Set name" aria-label="Set name (preview)" tabIndex={-1} />
          <button type="button" tabIndex={-1}>Clear</button>
          <button type="button" className="btn-primary" tabIndex={-1}>Save set</button>
          <button type="button" disabled tabIndex={-1}>Copy JSON</button>
        </div>

        <p className="tp-say"><span className="tp-state" data-on={on ? 'applied' : 'preview'}>
          {on ? 'applied' : 'preview · click to keep'}</span><span className="tp-words">{t.say}</span></p>
      </div>
    );
  }

  /* The dialog is portalled to <body>, as theme-picker.js appended it. `btnRef` is
     the Theme button in the bar. `showing` is what the stage renders, the applied
     theme is what the page is on; they differ only while the pointer is off the
     applied row. */
  function ThemePicker({ btnRef }) {
    const dlgRef = useRef(null);
    const [showing, setShowing] = useState(currentTheme);
    const [applied, setApplied] = useState(currentTheme);

    const paint = key => { setShowing(key); setApplied(currentTheme()); };

    useEffect(() => {
      const btn = btnRef.current;
      if (!btn) return undefined;
      const open = () => { paint(currentTheme()); dlgRef.current.showModal(); };
      btn.addEventListener('click', open);
      return () => btn.removeEventListener('click', open);
    }, []);

    return ReactDOM.createPortal(
      <dialog className="tpick" aria-label="Forge theme" ref={dlgRef}
              onClick={e => { if (e.target === dlgRef.current) dlgRef.current.close(); }}>
        <div className="tp-head">
          <div>
            <h2>Forge theme</h2>
            <p>Five materials for the same tool. The panel on the right is the real page under
               whichever one you are pointing at: hover to look, click to keep.</p>
          </div>
          <button type="button" className="tp-x" aria-label="Close"
                  onClick={() => dlgRef.current.close()}>&#10005;</button>
        </div>
        <div className="tp-body">
          <div className="tp-rail" role="group" aria-label="Themes"
               onPointerLeave={() => paint(currentTheme())}>
            {THEMES.map(t => (
              <button type="button" className="tp-opt" data-key={t.key} key={t.key}
                      aria-pressed={String(t.key === applied)}
                      onPointerEnter={() => paint(t.key)}
                      onFocus={() => paint(t.key)}
                      onClick={() => { applyTheme(t.key); paint(t.key); }}>
                <span className="tp-swatch" data-theme={t.key} aria-hidden="true"><i></i><b></b><u></u></span>
                <span className="tp-name">{t.name}</span>
                <span className="tp-note">{t.note}</span>
                <span className="tp-tick" aria-hidden="true">&#10003;</span>
              </button>
            ))}
          </div>
          <Stage showing={showing} applied={applied} />
        </div>
      </dialog>,
      document.body);
  }

  const ICO = {
    gem: <svg viewBox="0 0 24 24"><path d="M12 2 21 9 12 22 3 9Z" fill="currentColor" opacity=".9"/><path d="M3 9h18M12 2 8.5 9 12 22l3.5-13Z" fill="none" stroke="#0007" strokeWidth="1"/></svg>,
    champions: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="4" y="4" width="6.5" height="6.5" rx="2"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="2"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="2"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="2"/></svg>,
    patch: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 3h9l4 4v14H6Z"/><path d="M9 11h7M9 15h7"/></svg>,
    stats: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 20V11M12 20V5M19 20v-6"/></svg>,
    draft: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 5l14 14M19 5 5 19M4 8V4h4M20 8V4h-4"/></svg>,
    search: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="6"/><path d="m20 20-4.5-4.5"/></svg>,
  };
  const SECTIONS = [['champions', './', 'Champions'], ['patch', 'patch', 'Patch'], ['stats', 'stats', 'Stats'], ['draft', 'draft', 'Draft']];

  /* The shell, picked on Workbench 2026-11-05 (set forge-hub-shape-layout, B "Left rail,
     like Jobs"): a Hub-style header, a full-width search under it (mark 2026-11-05-175436 #1
     moved it out of the rail), a floating left rail and a bottom status pill.
     #forge-root (or the builder's body) is the grid they sit in; see forge-base.css "shell".
     `act` is the page's own action, drawn as the header pill. Children are the .meta spans,
     now carried by the status pill. Landing only: `pool` [{name, img, n}] fills the rail's
     pool list, `query`/`onQuery` make the search filter the cards in place, `total` is the
     build count. Elsewhere the search is a GET to the landing page (?q=). */
  function Bar({ current, act, children, pool, query, onQuery, total }) {
    const btnRef = useRef(null);
    const here = current || 'builder';
    const onLanding = !!onQuery;
    const q = (query || '').trim().toLowerCase();
    const go = name => {
      const card = document.querySelector(`.card[data-champ="${CSS.escape(name)}"]`);
      if (card) card.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };
    return (
      <React.Fragment>
        <header className="topbar">
          <a className="fh-brand" href="./"><span className="fh-tile" aria-hidden="true">{ICO.gem}</span><h1>forge</h1></a>
          <span className="fh-sep" aria-hidden="true"></span>
          <span className="fh-page">{here}</span>
          <span className="grow"></span>
          {act}
          <button type="button" className="themebtn" aria-haspopup="dialog" aria-label="Theme" title="Theme" ref={btnRef}>
            {ICO.gem}</button>
          <ThemePicker btnRef={btnRef} />
        </header>

        <form className="fs-search" action="./" method="get" role="search"
              onSubmit={onLanding ? e => e.preventDefault() : undefined}>
          {ICO.search}
          <input type="search" name="q" placeholder="Champion in your pool" aria-label="Champion in your pool"
                 value={onLanding ? query : undefined}
                 onChange={onLanding ? e => onQuery(e.target.value) : undefined} />
        </form>

        <aside className="frail">
          <nav className="navtabs" aria-label="Forge sections">
            {SECTIONS.map(([key, href, label]) => (
              <a href={href} key={key} aria-current={current === key ? 'page' : undefined}>
                <span className="ic" aria-hidden="true">{ICO[key]}</span><span>{label}</span></a>))}
          </nav>
          {pool && pool.length ? (
            <React.Fragment>
              <p className="fs-cap">Pool</p>
              <div className="fs-pool">
                {pool.filter(p => p.name.toLowerCase().includes(q)).map(p => (
                  <a href={`c/${encodeURIComponent(p.name)}`} key={p.name}
                     onClick={e => { e.preventDefault(); go(p.name); }}>
                    {p.img ? <img src={p.img} alt="" /> : <i></i>}<span>{p.name}</span>
                    <em className={p.n ? undefined : 'z'}>{p.n}</em></a>))}
              </div>
            </React.Fragment>) : null}
          <a className="fs-tilecta" href="edit"><b aria-hidden="true">+</b><div><strong>Set with no champion</strong>
            {total != null ? <span>{`${total} build${total === 1 ? '' : 's'} saved so far`}</span> : null}</div></a>
        </aside>

        <div className="fs-status">
          {children}
          {total != null && pool ? <span className="fs-tot"><i className="dot"></i>{`${total} builds · ${pool.length} champions`}</span> : null}
          <span className="fs-where">FORGE · /forge/</span>
        </div>
      </React.Fragment>
    );
  }

  /* Riot's own position icons, paths copied unchanged from CommunityDragon
     (rcp-fe-lol-static-assets/global/default/svg/position-<lane>.svg). The gold fills
     became currentColor so a chip's state colours them; the file's dim half keeps its
     0.5 opacity. Keyed by the role names the Forge data uses. */
  const LANE = {
    top: [['M21,14H14v7h7V14Zm5-3V26L11.014,26l-4,4H30V7.016Z', 1], ['M4 4 4.003 28.045 9 23 9 9 23 9 28.045 4.003 4 4Z', 0]],
    jungle: [['M25,3c-2.128,3.3-5.147,6.851-6.966,11.469A42.373,42.373,0,0,1,20,20a27.7,27.7,0,0,1,1-3C21,12.023,22.856,8.277,25,3ZM13,20c-1.488-4.487-4.76-6.966-9-9,3.868,3.136,4.422,7.52,5,12l3.743,3.312C14.215,27.917,16.527,30.451,17,31c4.555-9.445-3.366-20.8-8-28C11.67,9.573,13.717,13.342,13,20Zm8,5a15.271,15.271,0,0,1,0,2l4-4c0.578-4.48,1.132-8.864,5-12C24.712,13.537,22.134,18.854,21,25Z', 0]],
    mid: [['M30,12.968l-4.008,4L26,26H17l-4,4H30ZM16.979,8L21,4H4V20.977L8,17,8,8h8.981Z', 1], ['M25 4 4 25 4 30 9 30 30 9 30 4 25 4Z', 0]],
    bot: [['M13,20h7V13H13v7ZM4,4V26.984l3.955-4L8,8,22.986,8l4-4H4Z', 1], ['M29.997 5.955 25 11 25 25 11 25 5.955 29.997 30 30 29.997 5.955Z', 0]],
    support: [['M26,13c3.535,0,8-4,8-4H23l-3,3,2,7,5-2-3-4h2ZM22,5L20.827,3H13.062L12,5l5,6Zm-5,9-1-1L13,28l4,3,4-3L18,13ZM11,9H0s4.465,4,8,4h2L7,17l5,2,2-7Z', 0]],
  };
  function RoleGlyph({ role }) {
    const parts = LANE[role];
    if (!parts) return <span className="role-txt">{role}</span>;
    return (
      <svg className="role-ico" viewBox="0 0 34 34" aria-hidden="true">
        {parts.map(([d, dim], i) => <path key={i} d={d} fill="currentColor" fillRule="evenodd" opacity={dim ? 0.5 : 1} />)}
      </svg>);
  }

  window.ForgeUI.Bar = Bar;
  window.ForgeUI.RoleGlyph = RoleGlyph;
  window.ForgeUI.ROLES = Object.keys(LANE);
  window.ForgeUI.applyTheme = applyTheme;
  window.ForgeUI.currentTheme = currentTheme;
})();
