/* stats-page.jsx - the Forge Stats page body, as React.

   His own OP.GG record from api/me: ranks, seasons, rank graph, match history and
   champion pool. Read-only, no writes. The head preflight in stats.html still starts the fetch
   (window.__FORGE.me), so the data is on the wire before this file runs; this component
   awaits the promise that is already in flight.
   The Forge top bar and theme pop-out come from forge-bar.jsx (ForgeUI.Bar), loaded first. */
window.ForgeUI = window.ForgeUI || {};

(() => {
  const { useState, useEffect, useRef } = React;

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
          <th title="Average share of your team's kills you took part in">KP</th>
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
            <td className="num">{c.kp == null ? '–' : `${c.kp}%`}</td>
          </tr>
        ))}</tbody>
      </table>
    );
  }

  /* LP graph. One continuous ladder value (each division is 100, each tier 400) so
     a promotion reads as a climb rather than LP falling from 86 to 6. OP.GG keeps
     only a few points; the archive in opgg_me grows them, and his current rank is
     the last point. */
  const TIERS = ['IRON', 'BRONZE', 'SILVER', 'GOLD', 'PLATINUM', 'EMERALD', 'DIAMOND', 'MASTER', 'GRANDMASTER', 'CHALLENGER'];
  const ladder = p => {
    const t = TIERS.indexOf(p.tier);
    if (t < 0) return null;
    return t >= 7 ? 2800 + (p.lp || 0) : t * 400 + (4 - (p.division || 4)) * 100 + (p.lp || 0);
  };
  const ladderName = v => {
    const t = Math.min(6, Math.floor(v / 400));
    if (v >= 2800) return 'Master';
    return `${TIERS[t][0]}${TIERS[t].slice(1).toLowerCase()} ${4 - Math.floor((v - t * 400) / 100)}`;
  };
  const day = iso => new Date(Date.parse(iso)).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

  /* Good-vs-bad colour for one stat (marks 2026-11-10-103343 #2, #3): q runs 0 at
     `bad` to 1 at `good`, and .grade turns it into red -> amber -> green. Benchmarks,
     ponytail: rough solo-queue rules of thumb, not per-rank or per-role tables:
     OP score 3 / 9, kill share 35% / 60%, CS per minute 5 / 8 (supports left
     uncoloured), gold per minute 300 / 450. */
  const grade = (v, bad, good) => v == null || Number.isNaN(+v) ? null
    : { '--q': Math.max(0, Math.min(1, (v - bad) / (good - bad))) };

  /* By game (mark 2026-11-10-103235 #1): the rank opgg_me stamped on each Solo / Duo
     game, oldest first, one point per game. Stamping began 2026-11-10, so older games
     have no point; games that shared one refresh share its reading. */
  const GRAPH_MODES = [['time', 'By day'], [20, 'Last 20'], [100, 'Last 100'], ['season', 'Season']];
  function LpGraph({ ME }) {
    const [hot, setHot] = useState(null);
    const [mode, setMode] = useState('time');
    /* The viewBox is the card's real width, so the 11px labels stay 11px on a phone
       instead of scaling down with a fixed 720-wide drawing. */
    const box = useRef(null);
    const [W, setW] = useState(720);
    useEffect(() => {
      const el = box.current;
      if (!el) return undefined;
      const ro = new ResizeObserver(([e]) => setW(Math.max(260, Math.round(e.contentRect.width))));
      ro.observe(el);
      return () => ro.disconnect();
    }, []);
    const byGame = mode !== 'time';
    const stamped = (ME.matches || []).filter(g => g.queue === 'SOLORANKED' && g.rank)
      .sort((a, b) => Date.parse(a.at) - Date.parse(b.at))
      .map(g => ({ ...g.rank, at: g.at, champion: g.champion, win: g.win, v: ladder(g.rank) }));
    const pts = byGame ? (typeof mode === 'number' ? stamped.slice(-mode) : stamped)
      : (ME.lp || []).map(p => ({ ...p, v: ladder(p) })).filter(p => p.v !== null);
    const now = (ME.ranks || []).find(r => r.queue === 'SOLORANKED');
    const tabs = (
      <div className="ml-tabs" role="tablist">{GRAPH_MODES.map(([k, label]) => (
        <button type="button" key={k} className={`ml-tab${mode === k ? ' on' : ''}`} role="tab" aria-selected={mode === k}
          onClick={() => { setMode(k); setHot(null); }}>{label}</button>))}</div>
    );
    if (!byGame && now && ladder(now) !== null) {
      const last = pts[pts.length - 1];
      if (!last || last.v !== ladder(now)) pts.push({ ...now, at: new Date((ME.fetchedAt || Date.now() / 1000) * 1000).toISOString(), v: ladder(now), now: true });
    }
    if (pts.length < 2) return (
      <div className="lpg">{tabs}<p className="empty">{byGame
        ? `${pts.length ? 'One ranked game' : 'No ranked games'} saved with its rank yet. Each Solo / Duo game from Nov 10 on gets one.`
        : 'Not enough ranked games yet to draw a line.'}</p></div>
    );
    const H = 180, L = 64, R = 16, T = 14, B = 26;
    const ts = byGame ? pts.map((p, i) => i) : pts.map(p => Date.parse(p.at));
    const t0 = Math.min(...ts), t1 = Math.max(...ts) || t0 + 1;
    const lo = Math.floor((Math.min(...pts.map(p => p.v)) - 10) / 100) * 100;
    const hi = Math.ceil((Math.max(...pts.map(p => p.v)) + 10) / 100) * 100;
    const x = t => L + (W - L - R) * (t - t0) / ((t1 - t0) || 1);
    const y = v => T + (H - T - B) * (hi - v) / ((hi - lo) || 1);
    const grid = [];
    for (let v = lo; v <= hi; v += 100) grid.push(v);
    const h = hot === null ? null : pts[hot];
    return (
      <div className="lpg" ref={box}>
        {tabs}
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Solo / Duo rank over time" onMouseLeave={() => setHot(null)}>
          {grid.map(v => (
            <g key={v}>
              <line className="gl" x1={L} x2={W - R} y1={y(v)} y2={y(v)} />
              {v < hi ? <text className="ax" x={L - 8} y={y(v + 50) + 4} textAnchor="end">{ladderName(v)}</text> : null}
            </g>
          ))}
          <polyline className="ln" points={pts.map((p, i) => `${x(ts[i])},${y(p.v)}`).join(' ')} />
          {pts.map((p, i) => (
            <g key={i} onMouseEnter={() => setHot(i)} onFocus={() => setHot(i)} tabIndex="0">
              <circle className="hit" cx={x(ts[i])} cy={y(p.v)} r="14" />
              <circle className={`dot${hot === i ? ' on' : ''}`} cx={x(ts[i])} cy={y(p.v)} r="4" />
            </g>
          ))}
          <text className="ax" x={L} y={H - 6}>{byGame ? `${pts.length} games ago` : day(pts[0].at)}</text>
          <text className="ax" x={W - R} y={H - 6} textAnchor="end">{byGame ? 'last game' : pts[pts.length - 1].now ? 'now' : day(pts[pts.length - 1].at)}</text>
        </svg>
        <p className="lpg-read">{h
          ? <React.Fragment><b>{`${tier(h)} ${h.lp ?? 0} LP`}</b>{byGame
            ? ` · after ${h.win ? 'a win' : 'a loss'} on ${h.champion}, ${day(h.at)}${h.games > 1 ? ` (shared with ${h.games - 1} other game${h.games > 2 ? 's' : ''})` : ''}`
            : ` · ${h.now ? 'now' : day(h.at)}`}</React.Fragment>
          : `${pts.length} ${byGame ? 'games' : 'points'} since ${day(pts[0].at)}. Hover a point for its rank.`}</p>
      </div>
    );
  }

  /* Match history, Workbench set forge-opgg-match-list option A (Scoreboard rows):
     summary strip over the games in the current tab, queue tabs, one wide row per
     game, ten at a time from the local archive (OP.GG itself only sends 20). */
  const ROLE = { TOP: 'Top', JUNGLE: 'Jungle', MID: 'Mid', ADC: 'Bot', SUPPORT: 'Support' };
  const QORDER = ['SOLORANKED', 'FLEXRANKED', 'NORMAL', 'ARAM', 'ARENA'];
  const k1 = v => v == null ? '–' : (v >= 1000 ? `${(v / 1000).toFixed(1)}k` : String(v));
  const avg = (gs, f) => { const v = gs.map(f).filter(x => x != null); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };

  function Ic({ icons, kind, id, cls = '' }) {
    const o = ((icons || {})[kind] || {})[String(id)];
    return o ? <img className={`ml-ic ${cls}`} src={o.u} alt={o.n} title={o.n} loading="lazy" /> : <i className={`ml-ic ${cls} none`}></i>;
  }

  function RankTag({ g }) {
    if (!g.opRank) return null;
    if (g.opRank === 1) return <span className={`ml-tag ${g.win ? 'mvp' : 'ace'}`}>{g.win ? 'MVP' : 'ACE'}</span>;
    return <span className="ml-tag">{`${g.opRank}${g.opRank === 2 ? 'nd' : g.opRank === 3 ? 'rd' : 'th'}`}</span>;
  }

  const MULTI = { 2: 'Double kill', 3: 'Triple kill', 4: 'Quadra kill', 5: 'Penta kill' };

  const Items = ({ p, icons }) => {
    const it = (p.items || []).slice(0, 6);
    while (it.length < 6) it.push(null);
    return <span className="ml-items">{it.map((x, i) => x
      ? <Ic key={i} icons={icons} kind="items" id={x} /> : <i key={i} className="ml-ic none"></i>)}</span>;
  };
  const Kda = ({ p }) => <span className="ml-kda"><b>{p.kill}</b>{' / '}<b className="d">{p.death}</b>{' / '}<b>{p.assist}</b></span>;

  /* Full game, Workbench set forge-game-detail option A (Two scoreboards) with his
     two notes: a team-against-team overview on top (option C's tug bars), and both
     teams in ONE table so the blue and red columns line up. Fetched on first open,
     kept for the page's life. */
  const DETAIL = {};
  function loadGame(g) {
    if (!DETAIL[g.id]) {
      DETAIL[g.id] = fetch(`/forge/api/me/game?id=${encodeURIComponent(g.id)}&at=${encodeURIComponent(g.at)}`)
        .then(r => r.json()).catch(e => ({ error: String(e) }));
    }
    return DETAIL[g.id];
  }

  function Tug({ label, a, b, fmt = String }) {
    a = a || 0; b = b || 0;
    // The bar is an honest share of the total, so gold always sits near 50%; the lead says how far apart.
    const lead = a === b ? '' : ` · ${a > b ? '+' : '−'}${fmt(Math.abs(a - b))}`;
    return (
      <div className="gd-tug">
        <span className="ml-num">{fmt(a)}</span>
        <div><small>{label}{lead}</small><div className="gd-tbar"><i style={{ width: `${Math.round(100 * a / ((a + b) || 1))}%` }}></i></div></div>
        <span className="ml-num">{fmt(b)}</span>
      </div>
    );
  }

  function GameDetail({ g, icons }) {
    const [d, setD] = useState(null);
    useEffect(() => { let live = true; loadGame(g).then(x => { if (live) setD(x); }); return () => { live = false; }; }, [g.id]);
    if (!d) return <div className="gd-wait ml-dim">Loading the full game from OP.GG</div>;
    if (d.error || !(d.teams || []).length) return <div className="gd-wait ml-loss">{d.error || 'OP.GG sent no teams for this game.'}</div>;
    const ic = { ...(icons || {}) };
    ['items', 'spells', 'runes', 'trees'].forEach(k => { ic[k] = { ...((icons || {})[k] || {}), ...((d.icons || {})[k] || {}) }; });
    const [A, B] = d.teams;
    const max = Math.max(1, ...d.teams.flatMap(t => t.players.map(p => p.damage || 0)));
    const side = t => (t.side === 'BLUE' ? 'Blue side' : 'Red side');
    return (
      <div className="gd-body">
        <div className="gd-vs">
          <div className="gd-vs-h"><b className={A.win ? 'ml-win' : 'ml-loss'}>{`Your team · ${side(A)}`}</b>
            <b className={B && B.win ? 'ml-win' : 'ml-loss'}>{B ? side(B) : ''}</b></div>
          {B ? <div className="gd-tugs">
            <Tug label="Kills" a={A.kills} b={B.kills} />
            <Tug label="Gold" a={A.gold} b={B.gold} fmt={k1} />
            <Tug label="Towers" a={A.tower} b={B.tower} />
            <Tug label="Drakes" a={A.dragon} b={B.dragon} />
            <Tug label="Barons" a={A.baron} b={B.baron} />
            <Tug label="Grubs" a={A.horde} b={B.horde} />
          </div> : null}
        </div>
        <div className="gd-scroll">
          <table className="gd-tb">
            {d.teams.map((t, ti) => (
              <tbody key={ti}>
                <tr className="gd-th">
                  <th className={t.win ? 'ml-win' : 'ml-loss'}>{`${t.win ? 'Victory' : 'Defeat'} · ${side(t)}`}</th>
                  <th>KDA · share</th><th>Damage</th><th>Gold</th><th>CS</th><th>Wards</th><th>Items</th><th>OP</th>
                </tr>
                {t.players.map((p, i) => (
                  <tr key={i} className={p.me ? 'gd-me' : ''}>
                    <td className="gd-who">
                      {p.portrait ? <img className="ml-pt sm" src={p.portrait} alt={p.champion} /> : <i className="ml-pt sm none"></i>}
                      <span className="ml-spells">{(p.spells || []).map((x, j) => <Ic key={j} icons={ic} kind="spells" id={x} />)}</span>
                      <span className="ml-runes"><Ic icons={ic} kind="runes" id={p.keystone} cls="key" /><Ic icons={ic} kind="trees" id={p.secondary} cls="tree" /></span>
                      <div><b>{p.champion}</b><span className="ml-dim">{String(p.name || '').split('#')[0]}</span></div>
                    </td>
                    <td><Kda p={p} /><span className="ml-dim ml-num">{`${kdaText(p)} · ${p.kp == null ? '–' : `${p.kp}%`}`}</span></td>
                    <td><span className="ml-num">{k1(p.damage)}</span>
                      <div className={`gd-bar${ti ? ' red' : ''}`}><i style={{ width: `${Math.round(100 * (p.damage || 0) / max)}%` }}></i></div></td>
                    <td className="ml-num">{k1(p.gold)}</td>
                    <td className="ml-num">{p.cs} <span className="ml-dim">{`(${p.csPerMin ?? '–'})`}</span></td>
                    <td className="ml-num">{p.wards ?? '–'}</td>
                    <td><Items p={p} icons={ic} /></td>
                    <td className="ml-num"><b className="grade" style={grade(p.opScore, 3, 9)}>{p.opScore == null ? '–' : (+p.opScore).toFixed(1)}</b> <RankTag g={{ ...p, win: t.win }} /></td>
                  </tr>
                ))}
                {(t.bans || []).length ? <tr className="gd-bans"><td colSpan="8" className="ml-dim">{`Bans ${t.bans.join(', ')}`}</td></tr> : null}
              </tbody>
            ))}
          </table>
        </div>
      </div>
    );
  }

  function GameRow({ g, icons }) {
    const [open, setOpen] = useState(false);
    const items = (g.items || []).slice(0, 6);
    while (items.length < 6) items.push(null);
    /* the whole row toggles; the champion name stays a link to its build shelf */
    const toggle = e => { if (!e.target.closest('a, button')) setOpen(!open); };
    return (
      <div className={`a-game${open ? ' on' : ''}`}>
      <div className={`a-row ${g.win ? 'w' : 'l'}`} onClick={toggle}>
        <div className="a-meta"><b>{q(g.queue)}</b><span>{ago(g.at)}</span><i></i>
          <b className={g.win ? 'ml-win' : 'ml-loss'}>{g.win ? 'Win' : 'Loss'}{lpText(g)}</b><span>{mmss(g.seconds)}</span></div>
        <div className="a-who">
          {g.portrait ? <img className="ml-pt" src={g.portrait} alt={g.champion} /> : <i className="ml-pt none"></i>}
          <span className="ml-spells">{(g.spells || []).map((s, i) => <Ic key={i} icons={icons} kind="spells" id={s} />)}</span>
          <span className="ml-runes"><Ic icons={icons} kind="runes" id={g.keystone} cls="key" /><Ic icons={icons} kind="trees" id={g.secondary} cls="tree" /></span>
          <div className="a-cn">
            <b>{g.href ? <a href={g.href} title={`Builds for ${g.champion}`}>{g.champion}</a> : g.champion}</b>
            <span className="ml-dim">{`${ROLE[g.position] || ''} · lvl ${g.level || '–'}`}</span>
          </div>
        </div>
        <div className="a-k">
          <span className="ml-kda"><b>{g.kill}</b>{' / '}<b className="d">{g.death}</b>{' / '}<b>{g.assist}</b></span>
          <span className="ml-num ml-dim">{`${kdaText(g)} KDA`}</span>
          {MULTI[g.multi] ? <span className="ml-multi">{MULTI[g.multi]}</span> : null}
        </div>
        <div className="a-st ml-num">
          <span>Kill share <b className="grade" style={grade(g.kp, 35, 60)}>{g.kp == null ? '–' : `${g.kp}%`}</b></span>
          <span>CS <b className="grade" style={g.position === 'SUPPORT' || g.position === 'UTILITY' ? null : grade(g.csPerMin, 5, 8)}>{g.cs}</b>{` (${g.csPerMin})`}</span>
          <span>Gold <b className="grade" style={g.seconds ? grade(g.gold / (g.seconds / 60), 300, 450) : null}>{k1(g.gold)}</b></span>
        </div>
        <div className="a-it"><span className="ml-items">{items.map((it, i) => it
          ? <Ic key={i} icons={icons} kind="items" id={it} /> : <i key={i} className="ml-ic none"></i>)}</span></div>
        <div className="a-op"><b className="grade" style={grade(g.opScore, 3, 9)}>{g.opScore == null ? '–' : (+g.opScore).toFixed(1)}</b><RankTag g={g} /></div>
        <button type="button" className="a-open" aria-expanded={open} onClick={() => setOpen(!open)}
          title={open ? 'Close this game' : 'Open the full game'}>{open ? 'Close' : 'Open'}</button>
      </div>
      {open ? <GameDetail g={g} icons={icons} /> : null}
      </div>
    );
  }

  /* LP the game moved him (mark 2026-11-10-103343 #1), from opgg_me's per-refresh
     rank stamp. A stamp shared by several games is their combined change, said so. */
  const lpText = g => {
    const r = g.rank;
    if (!r || r.delta == null) return null;
    const t = `${r.delta > 0 ? '+' : r.delta < 0 ? '−' : '±'}${Math.abs(r.delta)} LP`;
    return <span className={`a-lp ${r.delta >= 0 ? 'ml-win' : 'ml-loss'}`}
      title={r.games > 1 ? `Combined change over ${r.games} games read in one refresh; now ${tier(r)} ${r.lp} LP` : `Now ${tier(r)} ${r.lp} LP`}>
      {r.games > 1 ? ` ${t} (${r.games} games)` : ` ${t}`}</span>;
  };

  function Strip({ games }) {
    const n = games.length, w = games.filter(g => g.win).length;
    const wr = n ? Math.round(100 * w / n) : null;
    const K = avg(games, g => g.kill), D = avg(games, g => g.death), A = avg(games, g => g.assist);
    const kp = avg(games, g => g.kp), op = avg(games, g => g.opScore);
    const by = {};
    games.forEach(g => {
      const c = by[g.champion] = by[g.champion] || { name: g.champion, portrait: g.portrait, n: 0, w: 0, k: 0, d: 0, a: 0 };
      c.n++; c.w += g.win ? 1 : 0; c.k += g.kill; c.d += g.death; c.a += g.assist;
    });
    const champs = Object.values(by).sort((a, b) => b.n - a.n || b.w - a.w).slice(0, 3);
    const roles = ['TOP', 'JUNGLE', 'MID', 'ADC', 'SUPPORT'].map(r => ({ r, n: games.filter(g => g.position === r).length }));
    const maxR = Math.max(1, ...roles.map(r => r.n));
    return (
      <div className="a-strip">
        <div className="a-rec">
          <div className={`a-big ${wr >= 50 ? 'ml-win' : 'ml-loss'}`}>{wr == null ? '–' : `${wr}%`}</div>
          <div className="ml-num ml-dim">{`${n}G ${w}W ${n - w}L`}</div>
        </div>
        <div className="a-avg">
          <div className="ml-num">{`${n1(K)} / `}<span className="ml-loss">{n1(D)}</span>{` / ${n1(A)}`}</div>
          <div className="a-big">{D ? ((K + A) / D).toFixed(2) : '–'} <small>KDA</small></div>
          <div className="ml-dim ml-num">{`Kill share ${kp == null ? '–' : `${Math.round(kp)}%`} · OP ${n1(op)}`}</div>
        </div>
        <div className="a-chs">{champs.map(c => (
          <div className="a-ch" key={c.name}>
            {c.portrait ? <img className="ml-pt" src={c.portrait} alt={c.name} /> : <i className="ml-pt none"></i>}
            <div><b>{c.name}</b><span className="ml-num">{`${c.w}W ${c.n - c.w}L · ${c.d ? ((c.k + c.a) / c.d).toFixed(2) : '∞'} KDA`}</span></div>
          </div>
        ))}</div>
        <div className="a-roles">{roles.map(r => (
          <div className="a-role" key={r.r} title={`${ROLE[r.r]} ${r.n}`}>
            <i style={{ height: `${Math.round(100 * r.n / maxR)}%` }}></i><span>{ROLE[r.r].slice(0, 3)}</span>
          </div>
        ))}</div>
      </div>
    );
  }

  function History({ ME }) {
    const [filter, setFilter] = useState('ALL');
    const [shown, setShown] = useState(10);
    const all = ME.matches || [];
    if (!all.length) return <p className="empty">No recent games.</p>;
    const counts = {};
    all.forEach(g => { counts[g.queue] = (counts[g.queue] || 0) + 1; });
    const keys = QORDER.filter(k => counts[k]).concat(Object.keys(counts).filter(k => !QORDER.includes(k)));
    const list = filter === 'ALL' ? all : all.filter(g => g.queue === filter);
    const left = list.length - shown;
    const tab = (k, label, n) => (
      <button type="button" key={k} className={`ml-tab${filter === k ? ' on' : ''}`} role="tab" aria-selected={filter === k}
        onClick={() => { setFilter(k); setShown(10); }}>{label} <span>{n}</span></button>
    );
    return (
      <React.Fragment>
        <div className="ml-tabs" role="tablist">{tab('ALL', 'All', all.length)}{keys.map(k => tab(k, q(k), counts[k]))}</div>
        <Strip games={list} />
        <div className="a-list">{list.slice(0, shown).map(g => <GameRow key={g.id} g={g} icons={ME.icons} />)}</div>
        {left > 0
          ? <button type="button" className="ml-more" onClick={() => setShown(shown + 10)}>{`Show ${Math.min(10, left)} more `}<span>{`${left} left`}</span></button>
          : <p className="ml-end">{`All ${list.length} saved games shown. OP.GG sends the newest 20; every game after that is kept here, so the list grows as you play.`}</p>}
      </React.Fragment>
    );
  }

  function StatsPage() {
    const [ME, setME] = useState(null);
    const [busy, setBusy] = useState(false);
    // past the 15-minute cache (api/me?refresh=1); a failed read keeps what is showing
    const refresh = () => {
      setBusy(true);
      fetch('api/me?refresh=1').then(r => r.json()).then(d => { if (!d.error || d.champions) setME(d); })
        .catch(() => {}).finally(() => setBusy(false));
    };

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
            <div className="lede-hd">
              <h2 id="title">{title}</h2>
              {ME ? <button type="button" className="ml-tab" id="refresh" disabled={busy} onClick={refresh}
                title="Read OP.GG again now">{busy ? 'Refreshing…' : 'Refresh'}</button> : null}
            </div>
            {lede ? <p id="lede">{lede}</p> : null}
          </div>

          <div id="alert">{alert}</div>

          <div className="ranks" id="ranks">{okME ? <Ranks ME={ME} /> : null}</div>
          <div className="seasons" id="seasons">{okME ? <Seasons ME={ME} se={se} /> : null}</div>

          {okME ? (
            <section className="pane">
              <h3>Solo / Duo rank <span className="sub">over time</span></h3>
              <div className="card"><LpGraph ME={ME} /></div>
            </section>
          ) : null}

          {okME ? (
            <section className="pane ml ml-a">
              <h3>Match history <span className="sub" id="gamesSub">{games.length
                ? `${games.length} saved games · ${won}W – ${games.length - won}L` : ''}</span></h3>
              <History ME={ME} />
            </section>
          ) : null}

          <div className="panes">
            <section className="pane">
              <h3>Champion pool <span className="sub" id="poolSub">{okME && pool.length
                ? `season ${se.id ?? ''} ranked · ${linked} of ${pool.length} have a shelf here` : ''}</span></h3>
              <div className="card scroll"><div id="pool">{okME ? <Pool pool={pool} most={most} /> : null}</div></div>
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
