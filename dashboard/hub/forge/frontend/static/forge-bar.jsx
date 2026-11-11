/* forge-bar.jsx - Item Set Forge's shell under the Hub bar, as React.

   The header is the Hub's own top bar (topbar.jsx mounts each page's static
   <header class="topbar">), pinned to Liquid Glass in Rift colours by the page's
   head script and forge-base.css. The five-theme picker went with Forge's own
   header on 2026-11-09. This renders the search, the left rail and the status pill.

   First Forge JSX file: it creates the namespace every other Forge file assigns into.
   Usage: <ForgeUI.Bar current="champions" act={<a className="act" ...>}>{metas}</ForgeUI.Bar>
   renders the whole shell (header, left rail, status pill); see Bar() below for the
   landing-only props. `current` is champions | patch | stats | draft | "" (the builder). */
window.ForgeUI = window.ForgeUI || {};

(() => {
  const ICO = {
    champions: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="4" y="4" width="6.5" height="6.5" rx="2"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="2"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="2"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="2"/></svg>,
    patch: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 3h9l4 4v14H6Z"/><path d="M9 11h7M9 15h7"/></svg>,
    stats: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 20V11M12 20V5M19 20v-6"/></svg>,
    draft: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M5 5l14 14M19 5 5 19M4 8V4h4M20 8V4h-4"/></svg>,
    search: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="6"/><path d="m20 20-4.5-4.5"/></svg>,
  };
  const SECTIONS = [['champions', './', 'Champions'], ['patch', 'patch', 'Patch'], ['stats', 'stats', 'Stats'], ['draft', 'draft', 'Draft']];

  /* The shell, picked on Workbench 2026-11-05 (set forge-hub-shape-layout, B "Left rail,
     like Jobs"): under the Hub bar, a full-width search (mark 2026-11-05-175436 #1
     moved it out of the rail), a floating left rail and a bottom status pill.
     #forge-root (or the builder's body) is the grid they sit in; see forge-base.css "shell".
     `act` is the page's own action, drawn in the rail above the new-set tile. Children are the .meta spans,
     now carried by the status pill. Landing only: `pool` [{name, img, n}] fills the rail's
     pool list, `query`/`onQuery` make the search filter the cards in place, `total` is the
     build count. Elsewhere the search is a GET to the landing page (?q=). */
  /* `onSection(key)`: the landing page shows Patch inline (mark 2026-11-10-042636 #1), so it
     takes the click for that section and returns true; anything it declines navigates. */
  function Bar({ current, act, children, pool, query, onQuery, total, onSection, onPick }) {
    const onLanding = !!onQuery;
    const q = (query || '').trim().toLowerCase();
    const go = p => {
      // from the inline Patch view the cards are not drawn yet: back to them first
      if (onSection) onSection('champions');
      if (onPick) onPick(p);
      requestAnimationFrame(() => {
        const card = document.querySelector(`.card[data-champ="${CSS.escape(p.name)}"]`);
        if (card) card.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    };
    /* The pool sorted by lane (mark 2026-11-10-042636 #2): entries carrying a `role`
       sit under that lane's heading, in ROLES order; a champion in no lane goes last. */
    const shownPool = (pool || []).filter(p => p.name.toLowerCase().includes(q));
    const lanes = shownPool.some(p => 'role' in p)
      ? [...ForgeUI.ROLES, ''].map(r => [r, shownPool.filter(p => (p.role || '') === r)]).filter(([, l]) => l.length)
      : [[null, shownPool]];
    const poolRow = p => (
      <a href={`c/${encodeURIComponent(p.name)}`} key={`${p.role}|${p.name}`}
         onClick={e => { e.preventDefault(); go(p); }}>
        {p.img ? <img src={p.img} alt="" /> : <i></i>}<span>{p.name}</span>
        <em className={p.n ? undefined : 'z'}>{p.n}</em></a>);
    return (
      <React.Fragment>
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
              <a href={href} key={key} aria-current={current === key ? 'page' : undefined}
                 onClick={onSection ? e => {
                   if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
                   if (onSection(key)) e.preventDefault();
                 } : undefined}>
                <span className="ic" aria-hidden="true">{ICO[key]}</span><span>{label}</span></a>))}
          </nav>
          {pool && pool.length ? (
            <React.Fragment>
              <p className="fs-cap">Pool</p>
              <div className="fs-pool">
                {lanes.map(([r, list]) => r === null ? list.map(poolRow) : (
                  <React.Fragment key={r || 'none'}>
                    <p className="fs-lane">{r ? <RoleGlyph role={r} /> : null}{r ? r[0].toUpperCase() + r.slice(1) : 'No lane'}</p>
                    {list.map(poolRow)}
                  </React.Fragment>))}
              </div>
            </React.Fragment>) : null}
          {act}
          <a className="fs-tilecta" href="edit"><b aria-hidden="true">+</b><div><strong>Set with no champion</strong>
            {total != null ? <span>{`${total} build${total === 1 ? '' : 's'} saved so far`}</span> : null}</div></a>
        </aside>

        <div className="fs-status">
          {children}
          {total != null && pool ? <span className="fs-tot"><i className="dot"></i>{`${total} builds · ${new Set(pool.map(p => p.name)).size} champions`}</span> : null}
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
})();
