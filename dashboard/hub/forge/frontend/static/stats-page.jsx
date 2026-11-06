/* stats-page.jsx - the Forge Stats page body, as React.

   His own OP.GG record from api/me: ranks, seasons, champion pool and the recent-games
   feed. Read-only, no writes. The head preflight in stats.html still starts the fetch
   (window.__FORGE.me), so the data is on the wire before this file runs; this component
   awaits the promise that is already in flight.
   The Forge top bar and theme pop-out come from forge-bar.jsx (ForgeUI.Bar), loaded first. */
window.ForgeUI = window.ForgeUI || {};

(() => {
  const { useState, useEffect } = React;

  const n1 = v => (v === null || v === undefined) ? '–' : v.toFixed(1);

  /* OP.GG's queue keys, in his words rather than theirs. */
  const QUEUE = {
    SOLORANKED: 'Solo / Duo', FLEXRANKED: 'Flex 5v5', ARENA: 'Arena',
    NORMAL: 'Normal', ARAM: 'ARAM', RANKED: 'Ranked', URF: 'URF', BOT: 'Co-op vs AI',
  };
  const q = k => QUEUE[k] || (k || '').toLowerCase();

  const tier = r => [r.tier ? r.tier[0] + r.tier.slice(1).toLowerCase() : '', r.division || ''].join(' ').trim();

  /* Elapsed time in the unit he would say out loud. Anything past a week is a
     date, because "13 days ago" is a subtraction and "Aug 8" is not. */
  function ago(iso) {
    const t = Date.parse(iso);
    if (!t) return '';
    const s = (Date.now() - t) / 1000;
    if (s < 90) return 'just now';
    if (s < 5400) return `${Math.round(s / 60)}m ago`;
    if (s < 172800) return `${Math.round(s / 3600)}h ago`;
    if (s < 604800) return `${Math.round(s / 86400)}d ago`;
    return new Date(t).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }

  /* A 0-death game has no ratio. Which of the two things that means is decided by
     whether anything happened: 16/0/4 is a perfect game, 0/0/0 in seven minutes is
     a remake, and printing the same infinity for both is the wrong call twice. */
  const kdaText = g => g.death ? g.kda.toFixed(2) : ((g.kill || 0) + (g.assist || 0) ? '∞' : '–');

  const mmss = s => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;

  const fetchedAgo = ME => ago(new Date(ME.fetchedAt * 1000).toISOString());

  /* 50% is the line, so the colour turns there and nowhere else.
     The bar's LENGTH is the sample and its FILL is the win rate, on a square-root
     scale against the biggest pile in the pool - linear would render everything
     outside the one-trick as a sliver, and this page's whole point is that 100
     games on Viego and 1 on Ashe are not the same kind of number. */
  function Wr({ pct, played, most }) {
    if (pct === null || pct === undefined) return <span className="wr"><b>–</b></span>;
    const cls = pct >= 50 ? 'up' : 'down';
    const w = Math.max(10, Math.round(74 * Math.sqrt((played || 0) / (most || 1))));
    return (
      <span className={`wr ${cls}`}>
        <b>{pct.toFixed(0)}%</b>
        <span className="bar" style={{ width: `${w}px` }} title={`${played} game${played === 1 ? '' : 's'}`}>
          <i style={{ width: `${Math.max(0, Math.min(100, pct))}%` }}></i></span>
      </span>
    );
  }

  function Champ({ row }) {
    return (
      <div className="champ">
        {row.portrait ? <img src={row.portrait} alt="" loading="lazy" /> : <i></i>}
        {row.href
          ? <React.Fragment>
              <a href={row.href} title={`Builds for ${row.champion}`}>{row.champion}</a>
              <span className="dot" title="has a build shelf in the Forge"></span>
            </React.Fragment>
          : <span className="name">{row.champion}</span>}
      </div>
    );
  }

  function Emblem({ src }) { return src ? <img src={src} alt="" /> : null; }

  function Ranks({ ME }) {
    const ranks = ME.ranks || [];
    if (!ranks.length) return <p className="quiet">No ranked queue played this season.</p>;
    return ranks.map((r, i) => (
      <div className="rank" key={i}>
        <Emblem src={r.emblem} />
        <div>
          <div className="q">{q(r.queue)}</div>
          <div className="t">{`${tier(r)} `}<span className="lp">{`${r.lp ?? 0} LP`}</span></div>
          <div className="rec"><b>{`${r.win ?? 0}W`}</b>{' – '}<b>{`${r.lose ?? 0}L`}</b>{` · ${r.winrate === null ? '–' : `${n1(r.winrate)}%`}`}</div>
        </div>
      </div>
    ));
  }

  function Seasons({ ME, se }) {
    /* Oldest first: the climb reads as a shape, and the current season is the pin
       on the right rather than a row you have to find. */
    const past = (ME.seasons || []).slice().sort((a, b) => a.season - b.season);
    const now = (ME.ranks || []).find(r => r.queue === 'SOLORANKED');
    return (
      <React.Fragment>
        {past.map((s, i) => (
          <span className="season" title={`Season ${s.season}`} key={i}>
            <Emblem src={s.emblem} />
            <span className="s">{`S${s.season}`}</span>{` ${tier(s)}`}
          </span>
        ))}
        {now && se.id ? (
          <span className="season now" title={`Season ${se.id}, in progress`}>
            <Emblem src={now.emblem} />
            <span className="s">{`S${se.id}`}</span>{` ${tier(now)}`}
          </span>
        ) : null}
      </React.Fragment>
    );
  }

  function Pool({ pool, most }) {
    if (!pool.length) return <p className="empty">No ranked champion record this season.</p>;
    return (
      <table>
        <thead><tr>
          <th>Champion</th><th>Games</th><th>Win rate</th><th>KDA</th>
          <th>K / D / A</th><th title="OP.GG's own 0-10 per-game rating">OP</th>
          <th title="Creep score per minute">CS/m</th>
        </tr></thead>
        <tbody>{pool.map((c, i) => (
          <tr key={i}>
            <td><Champ row={c} /></td>
            <td className="num">{c.play}</td>
            <td><Wr pct={c.winrate} played={c.play} most={most} /></td>
            <td className="num">{c.kda === null ? '–' : c.kda.toFixed(2)}</td>
            <td className="num">{n1(c.kill)} / {n1(c.death)} / {n1(c.assist)}</td>
            <td className="num"><span className="op">{c.opScore === null ? '–' : c.opScore.toFixed(2)}</span></td>
            <td className="num">{n1(c.csPerMin)}</td>
          </tr>
        ))}</tbody>
      </table>
    );
  }

  function Games({ games }) {
    if (!games.length) return <p className="empty">No recent games.</p>;
    return (
      <div className="games">{games.map((g, i) => (
        <div className={`game ${g.win ? 'win' : 'loss'}`} key={i}>
          <span className="edge" aria-hidden="true"></span>
          {g.portrait ? <img src={g.portrait} alt="" loading="lazy" /> : <i></i>}
          <div className="who">
            <span className="n">{g.href
              ? <a href={g.href} style={{ color: 'inherit', textDecoration: 'none' }}>{g.champion}</a>
              : g.champion}{' '}<span className="queue">{q(g.queue)}</span></span>
            <span className="m">{`${g.kill}/${g.death}/${g.assist} · ${n1(g.csPerMin)} cs/m · `}<span className="op">{g.opScore === null ? '–' : g.opScore.toFixed(1)}</span>{`${g.opRank ? ` #${g.opRank}` : ''} · ${mmss(g.seconds)}`}</span>
          </div>
          <div className="right">
            <span className="res">{g.win ? 'Win' : 'Loss'}</span>
            <span className="kda">{kdaText(g)}</span>
            <span className="when">{ago(g.at)}</span>
          </div>
        </div>
      ))}</div>
    );
  }

  function StatsPage() {
    const [ME, setME] = useState(null);

    useEffect(() => {
      window.__FORGE.me.then(setME);
      document.getElementById('forge-root').setAttribute('data-react-mounted', 'forge-stats');
    }, []);

    const failed = !!(ME?.error && !ME.champions);
    const id = ME && !failed ? (ME.riotId || `${ME.name}#${ME.tagline}`) : '';
    useEffect(() => { if (id) document.title = `${id} · Stats · Item Set Forge`; }, [id]);

    let title = 'Loading…', lede = null, alert = null;
    let pool = [], games = [], se = {}, won = 0;
    if (failed) {
      title = 'Could not reach OP.GG';
      lede = 'Nothing is cached yet, so there is nothing to show. Reload once OP.GG answers again.';
      alert = <div className="stale"><b>No data</b><code>{ME.error}</code></div>;
    } else if (ME) {
      se = ME.season || {};
      title = <React.Fragment>{`${id} `}<span className="queue">{`level ${ME.level}`}</span></React.Fragment>;
      lede = se.play
        ? <React.Fragment>{`Season ${se.id} ranked: `}<b>{se.play}</b>{' games, '}<b>{`${se.win}W – ${se.lose}L`}</b>
            {' ('}<b>{`${n1(se.winrate)}%`}</b>{')'}</React.Fragment>
        : 'No ranked games recorded this season.';
      if (ME.stale) {
        alert = (
          <div className="stale"><b>Showing the last good read.</b>
            {` OP.GG did not answer, so these numbers are from ${fetchedAgo(ME)}. `}<code>{ME.error || ''}</code></div>
        );
      }
      pool = ME.champions || [];
      games = ME.matches || [];
      won = games.filter(g => g.win).length;
    }
    const most = Math.max(1, ...pool.map(c => c.play || 0));
    const linked = pool.filter(c => c.href).length;
    const okME = ME && !failed;
    const lad = okME && ME.ladder;

    return (
      <React.Fragment>
        <ForgeUI.Bar current="stats"
          act={<a className="act" id="src" target="_blank" rel="noopener" href={okME ? (ME.opggUrl || '#') : undefined}>On OP.GG</a>}>
          <span className="meta" id="ladder"
            title={lad ? `Ladder rank ${lad.rank.toLocaleString()} of ${lad.total.toLocaleString()}` : undefined}>
            {lad ? `top ${(100 * lad.rank / lad.total).toFixed(1)}%` : ''}</span>
          <span className="meta" id="fetched" title={okME && ME.fetchedAt ? 'When this page last read OP.GG' : undefined}>
            {okME && ME.fetchedAt ? fetchedAgo(ME) : ''}</span>
        </ForgeUI.Bar>

        <div className="wrap">
          <div className="lede">
            <h2 id="title">{title}</h2>
            {lede ? <p id="lede">{lede}</p> : null}
          </div>

          <div id="alert">{alert}</div>

          <div className="ranks" id="ranks">{okME ? <Ranks ME={ME} /> : null}</div>
          <div className="seasons" id="seasons">{okME ? <Seasons ME={ME} se={se} /> : null}</div>

          <div className="panes">
            <section className="pane">
              <h3>Champion pool <span className="sub" id="poolSub">{okME && pool.length
                ? `season ${se.id ?? ''} ranked · ${linked} of ${pool.length} have a shelf here` : ''}</span></h3>
              <div className="card scroll"><div id="pool">{okME ? <Pool pool={pool} most={most} /> : null}</div></div>
            </section>

            <section className="pane">
              <h3>Recent games <span className="sub" id="gamesSub">{okME && games.length
                ? `last ${games.length} · ${won}W – ${games.length - won}L` : ''}</span></h3>
              <div className="card feed"><div id="games">{okME ? <Games games={games} /> : null}</div></div>
            </section>
          </div>
        </div>
      </React.Fragment>
    );
  }

  class ErrorBoundary extends React.Component {
    constructor(p) { super(p); this.state = { err: null }; }
    static getDerivedStateFromError(err) { return { err }; }
    render() {
      if (this.state.err) return <p className="quiet">page failed to load: {String(this.state.err.message || this.state.err)}</p>;
      return this.props.children;
    }
  }

  window.ForgeUI.StatsPage = StatsPage;
  ReactDOM.createRoot(document.getElementById('forge-root')).render(<ErrorBoundary><StatsPage /></ErrorBoundary>);
})();
