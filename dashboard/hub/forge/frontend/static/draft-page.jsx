/* draft-page.jsx - the Forge Draft page body, as React.

   Reads api/draft every 0.5 s: the live champ select from the Windows poller
   (draft_feed), the engine's pick lists and team traits (draft_engine), and once he
   locks in, the build (build_engine). The app-wide ETag hook makes an unchanged poll
   a 304, and the page only re-renders when the body text changes.
   The head preflight in draft.html starts the first feed read, the catalog and the
   rune table; this component awaits those promises.
   Read-only apart from Save as set, which posts through the existing api/sets. */
window.ForgeUI = window.ForgeUI || {};

(() => {
  const { useState, useEffect, useRef } = React;

  const ROLE = { top: 'Top', jungle: 'Jungle', mid: 'Mid', bot: 'Bot', support: 'Support' };
  const role = r => ROLE[r] || (r ? r[0].toUpperCase() + r.slice(1) : '');

  /* Short code, plain sentence. The detail is in the Hub log. */
  const ERRORS = {
    POLLER_OFFLINE: 'The Windows poller has not posted in the last few seconds. Showing the last draft it sent.',
    LCU_SHAPE: 'The League client sent a champ select this page cannot read. A client patch may have changed it.',
    BAKE_STALE: 'A data bake is older than the current patch, so some numbers are from the last one.',
    ENGINE: 'The draft engine failed on this draft. The picks below are missing until the next change.',
  };
  const errCode = e => (e || '').split(':')[0];

  function ago(sec) {
    if (sec == null) return '';
    const s = Math.max(0, Date.now() / 1000 - sec);
    if (s < 10) return `${s.toFixed(1)} s ago`;
    if (s < 90) return `${Math.round(s)} s ago`;
    if (s < 5400) return `${Math.round(s / 60)} min ago`;
    return `${Math.round(s / 3600)} h ago`;
  }

  const signed = v => (v > 0 ? '+' : '') + v.toFixed(1);

  const PROVIDERS = ['lolalytics', 'op.gg'];

  /* "physicalShare" -> "Physical share"; the few that camel case mangles are named. */
  const LABEL = { hardCC: 'Hard CC', softCC: 'Soft CC', damage10s: 'Damage in 10 s', towerDps: 'Tower DPS',
    pctHealthShare: '% health share', aoeShare: 'AoE share', earlyLate: 'Late-game lean' };
  const human = k => LABEL[k] || k.replace(/([A-Z])/g, ' $1').toLowerCase().replace(/^./, c => c.toUpperCase());

  function Portrait({ c, size }) {
    return c ? <img src={c.u} alt="" width={size} height={size} loading="lazy" /> : <span className="blank">?</span>;
  }

  /* ── archetype on a seat: closed chip, and the seat opened in place ───── */

  const WHY = { yours: 'your pick', items: 'from items', keystone: 'your keystone', heuristic: 'heuristic', 'most-played': 'most-played' };
  const WHY_TONE = { yours: ' mine', items: ' items' };
  const WHY_NOTE = { 'api-miss': 'coachless: API miss', absent: 'coachless: none in this role', unbaked: 'coachless: not baked' };

  function ArchIcons({ arch, x }) {
    const k = x.R[String(arch.keystone)] || {};
    return (
      <span className="ax-icons">
        {k.icon ? <img className="ax-ic k" src={k.icon} alt={k.name || ''} title={k.name || ''} /> : null}
        {(arch.core || []).map(id => {
          const it = x.items[String(id)];
          return it ? <img className="ax-ic" key={id} src={it.u} alt={it.n} title={it.n} /> : null;
        })}
      </span>);
  }

  function ArchChip({ a, x, open, onToggle }) {
    const cur = a.list[a.index ?? 0];
    const k = x.R[String(cur.keystone)] || {};
    const data = x.mode && x.mode !== 'ranked' ? `${x.mode.toUpperCase()} data · ` : '';
    return (
      <React.Fragment>
        <button type="button" className="ax-btn ax-open" aria-expanded={open} onClick={onToggle}>
          <ArchIcons arch={cur} x={x} />
          <span className="ax-k">{k.name || cur.keystone}</span>
          <span className="ax-count">{`${a.n || 1}/${a.of}`}</span>
        </button>
        <div className={`ax-prov${WHY_TONE[a.why] || ''}`}>{data + (WHY[a.why] || a.why)}</div>
      </React.Fragment>);
  }

  /* coachless beside the lolalytics win rate: each reading says what it is conditioned
     on, and one coachless does not have is struck. */
  function Wpa({ arch, x }) {
    const cl = arch.coachless || {};
    if (cl.state !== 'ok') return <span className="ax-meta"><s>{WHY_NOTE[cl.state] || 'coachless: no reading'}</s></span>;
    const nm = (v, label) => v ? `${label} ${signed(v.wpa)}` : null;
    const ks = x.R[String(arch.keystone)]?.name || arch.keystone;
    const its = (arch.core || []).map(id => ({ label: x.items[String(id)]?.n || id, v: cl.items?.[String(id)] }));
    return (
      <span className="ax-meta">
        {'WPA '}{cl.keystone ? nm(cl.keystone, ks) : <s>{ks}</s>}{` (${cl.keystoneConditioning})`}
        {' · '}{its.map((t, i) => <React.Fragment key={i}>{i ? ', ' : ''}{t.v ? nm(t.v, t.label) : <s>{t.label}</s>}</React.Fragment>)}
        {` (${cl.itemsConditioning})`}
      </span>);
  }

  function ArchBody({ champ, a, x }) {
    const cur = a.list[a.index ?? 0];
    const name = id => x.items[String(id)]?.n || id;
    const path = arch => (arch.path || []).length
      ? 'then ' + arch.path.map(p => `${p.items.slice((arch.core || []).length).map(name).join(' + ')} (${p.games.toLocaleString()})`).join(', ')
      : 'no third item reading';
    const ks = x.R[String(cur.keystone)]?.name || cur.keystone;
    const q = a.identity;
    return (
      <div className="ax-body">
        {a.list.map((arch, i) => (
          <button type="button" className={`ax-row${i === (a.index ?? 0) ? ' on' : ''}`} key={arch.id}
            onClick={() => x.onPick(champ, arch.id)}>
            <ArchIcons arch={arch} x={x} />
            <span className="ax-name">{(arch.core || []).map(name).join(' + ')}</span>
            <span className="ax-meta">{`${arch.wr == null ? '–' : arch.wr.toFixed(1)}% · ${arch.games == null ? '–' : arch.games.toLocaleString()} games`}</span>
            <Wpa arch={arch} x={x} />
            <span className="ax-path">{path(arch)}</span>
          </button>))}
        <div className="ax-foot">
          <span className="ax-meta">{`${Math.round(cur.share * 100)}% of role · ${Math.round(cur.keystoneShare * 100)}% of ${ks}`}</span>
          <span className="ax-pills">{(a.sources || []).map(s => (
            <span className={`pill${s.struck ? ' off' : ''}`} key={s.name}>{s.label}</span>))}</span>
          {a.role ? <a className="ax-learn" href={`/forge/c/${encodeURIComponent(champ)}/${encodeURIComponent(a.role)}?arch=${encodeURIComponent(cur.id)}`}>{`Learn ${champ}`}</a> : null}
          {q ? <p className="ax-quote">{`"${q.quote}" `}{/^https:\/\//.test(q.url) ? <a href={q.url} target="_blank" rel="noopener">3 Minute guide</a> : null}</p> : null}
          {(a.spikes?.rows || []).map((r, n) => (
            <p className="ax-quote" key={`sp${n}`}>{`Spikes${a.spikes.rows.length > 1 ? ` (${r.label})` : ''}: ${[r.items, r.levels && `levels ${r.levels}`].filter(Boolean).join(' \u00b7 ')}${r.oldItems ? ' (pre-2024 items)' : ''}${r.authored ? ' (written by Claude)' : ''}.${r.tips}`}</p>))}
          {x.msg ? <span className="ax-meta" role="status">{x.msg}</span> : null}
        </div>
      </div>);
  }

  // One champion's chip (under the seat's name) and open body (full seat width).
  function archSeat(x, c) {
    const a = c && x.arch[c.n];
    if (!a) return {};
    if (!a.list?.length) return { chip: a.note ? <div className="ax-prov">{a.note}</div> : null };
    const open = x.open === c.n;
    return { chip: <ArchChip a={a} x={x} open={open} onToggle={() => x.toggle(c.n)} />,
      body: open ? <ArchBody champ={c.n} a={a} x={x} /> : null };
  }

  /* ── side columns ─────────────────────────────────────────────────────── */

  function YourTeam({ draft, byKey, x }) {
    const me = draft.me || {};
    const seats = [...(draft.allies || []), { ...me, isMe: true }].sort((a, b) => a.cellId - b.cellId);
    return (
      <div className="card" id="allies">{seats.map(s => {
        if (s.isMe) {
          const c = byKey[s.championId || s.hover];
          const locked = !!s.championId;
          const n = locked ? `${c ? c.n : '?'} (you)` : (c ? `${c.n} (you)` : 'You');
          const r = `${role(s.role)} · ${locked ? 'locked' : (s.hover ? 'hovering' : 'picking now')}`;
          const ax = archSeat(x, c);
          return (
            <div className={`seat me${!locked && s.hover ? ' hover' : ''}`} key="me" data-me="1">
              <Portrait c={c} size={64} />
              <div><div className="n">{n}</div><div className="r">{r}</div>{ax.chip}</div>
              {ax.body}
            </div>
          );
        }
        const c = byKey[s.championId];
        const ax = archSeat(x, c);
        return (
          <div className={`seat${s.provisional ? ' hover' : ''}`} key={s.cellId}>
            <Portrait c={c} size={64} />
            <div><div className="n">{c ? c.n : 'Not locked'}</div>
              <div className="r">{role(s.role)}{s.provisional ? ' · hovering' : ''}</div>{ax.chip}</div>
            {ax.body}
          </div>
        );
      })}</div>
    );
  }

  function EnemyTeam({ draft, advice, byKey, x }) {
    const roles = advice?.teams?.enemyRoles || {};
    const locked = (draft.enemies || []).map(e => byKey[e.championId]);
    const slots = [...locked, ...Array(Math.max(0, 5 - locked.length)).fill(null)];
    return (
      <div className="card" id="enemies">{slots.map((c, i) => {
        const ax = archSeat(x, c);
        return (
          <div className="seat" key={i}>
            <Portrait c={c} size={64} />
            <div><div className="n">{c ? c.n : 'Not locked'}</div>
              <div className="r">{c ? (roles[c.n] ? `likely ${roles[c.n]}` : 'role unclear') : 'picking'}</div>{ax.chip}</div>
            {ax.body}
          </div>);
      })}</div>
    );
  }

  /* ── pick lists ───────────────────────────────────────────────────────── */

  function PickList({ rows, byName, ranked, empty }) {
    if (!rows.length) return <p className="quiet">{empty}</p>;
    return rows.map((p, i) => {
      const c = byName[p.champ];
      const nodata = p.total == null;
      // Both provider pills on every row: lit when that provider had a reading for
      // this draft, dimmed (with the reason on hover) when it had none.
      const read = new Set(Object.values(p.sources || {}).flatMap(v => v.split(' + ')));
      return (
        <div className={`pick${nodata ? ' nodata' : ''}`} key={p.champ}>
          <span className="rank">{ranked ? i + 1 : ''}</span>
          <Portrait c={c} size={40} />
          <div>
            <div><span className="n">{p.champ}</span>
              {nodata ? null : <span className={`sc ${p.total >= 0 ? 'up' : 'down'}`}>{signed(p.total)}</span>}</div>
            <div className="why">{p.reason}</div>
          </div>
          <span className="pills">{nodata ? null : PROVIDERS.map(s => read.has(s)
            ? <span className="pill" key={s}>{s}</span>
            : <span className="pill off" key={s} title={`${s}: no reading for ${p.champ} in this draft`}>{s}</span>)}</span>
        </div>
      );
    });
  }

  /* ── locked: plan, build, runes ───────────────────────────────────────── */

  const SLOT = { 1: 'First item', 2: 'Second', 3: 'Third', 4: 'Fourth', 5: 'Fifth', 6: 'Sixth' };

  function Build({ build, items }) {
    const steps = [...(build.items || []), ...(build.boots ? [{ ...build.boots, boots: true }] : [])]
      .sort((a, b) => a.slot - b.slot);
    return (
      <div className="card" id="build">
        {build.set ? <div className="note">{steps.some(s => s.source === 'set')
          ? `Items swapped in from your set ${build.set.name}.`
          : `No counter swaps from ${build.set.name}: this draft is not skewed enough to give up a damage item.`}</div> : null}
        {steps.map(s => {
          const it = items[String(s.itemId)];
          return (
            <div className={s.thin ? 'step thin' : 'step'} key={`${s.slot}-${s.itemId}`}>
              {it ? <img src={it.u} alt="" /> : <span></span>}
              <div>
                <div><span className="n">{it ? it.n : s.itemId}</span>
                  <span className="slot">{s.boots ? `Boots, ${SLOT[s.slot] || s.slot}` : SLOT[s.slot] || s.slot}</span></div>
                <div className="why">{s.why}</div>
                {s.counter?.why?.length ? <div className="why">{`Counters: ${s.counter.why.join('; ')}.`}</div> : null}
                {s.replaced && !s.replaced.damage ? <div className="why">{`Score ${s.counter.score} vs ${s.replaced.score} for ${items[String(s.replaced.itemId)]?.n || s.replaced.itemId}.`}</div> : null}
              </div>
              <span className="pill">{s.thin ? `thin, ${s.lolalytics.n.toLocaleString()} games` : s.source === 'set' ? 'your set' : s.source}</span>
            </div>
          );
        })}
        {build.heal ? <Heal heal={build.heal} items={items}
          inBuild={steps.some(s => s.itemId === build.heal.pick)} /> : null}
      </div>
    );
  }

  /* ARAM: Mayhem: metasrc's build (or the ARAM fallback) and its top augments per
     rarity. No rune card: the mode has no runes. */
  function MayhemBuild({ build, items }) {
    const row = (id, label) => {
      const it = items[String(id)];
      return (
        <div className="step" key={`${label}-${id}`}>
          {it ? <img src={it.u} alt="" /> : <span></span>}
          <div><div><span className="n">{it ? it.n : id}</span><span className="slot">{label}</span></div></div>
        </div>
      );
    };
    return (
        <div className="card" id="build">
          <div className="note">{build.source === 'aram'
            ? `metasrc had no Mayhem build for ${build.champ}: this is the ARAM build${build.games ? `, ${build.games.toLocaleString()} games at ${build.wr}%` : ''}.`
            : `metasrc's Mayhem build over ${(build.games || 0).toLocaleString()} games. metasrc gives tiers, not win rates.`}
            {build.starting?.length ? ` Start: ${build.starting.map(i => items[String(i)]?.n || i).join(', ')}.` : ''}</div>
          {(build.items || []).map(s => row(s.itemId, SLOT[s.slot] || s.slot))}
          {build.boots ? row(build.boots.itemId, 'Boots') : null}
        </div>
    );
  }

  function Augments({ aug }) {
    return Object.keys(aug || {}).length ? <div className="card" id="augments">
          {['Silver', 'Gold', 'Prismatic'].filter(r => aug[r]?.length).map(r => (
            <div className="step" key={r}>
              <span></span>
              <div><span className="n">{r}</span><div className="why">{aug[r].join(', ')}</div></div>
            </div>
          ))}
        </div> : <div className="card"><p className="quiet">No Mayhem augment read for this champion.</p></div>;
  }

  /* Mortal Reminder vs Lord Dominik's, in net HP over the kill window. */
  function Heal({ heal, items, inBuild }) {
    const nm = id => items[String(id)]?.n || id;
    const T = Object.entries(heal.T || {}).map(([k, v]) => `${k} ${v.toFixed(1)} s`).join(', ');
    return (
      <div className="heal note" id="heal">
        <div><b>{nm(heal.pick)}</b>{' comes out ahead in the heal math.'}
          {inBuild ? '' : ' The build above keeps its own order; swap it in if you trust the math.'}</div>
        <div className="nums">{'Mortal Reminder '}<b>{Math.round(heal.mortal).toLocaleString()}</b>
          {' net HP · Lord Dominik\'s '}<b>{Math.round(heal.dominik).toLocaleString()}</b>
          {` · gold gap ${heal.goldGap}`}</div>
        <div>{`Kill window T: ${T || 'none'}. ${heal.assumption}`}</div>
      </div>
    );
  }

  function Runes({ build, runes }) {
    const r = build.runes;
    if (!r) return <p className="quiet">No rune page for this champion yet.</p>;
    const R = runes.runes || {}, Tr = runes.trees || {};
    const rules = Object.fromEntries((build.runeRules || []).map(x => [x.runeId, x]));
    const row = (id, label) => {
      const x = R[String(id)] || {};
      const rule = rules[id];
      return (
        <div className="rune" key={`${label}-${id}`}>
          {x.icon ? <img src={x.icon} alt="" /> : <span></span>}
          <div>
            <div><span className="n">{x.name || id}</span><span className="t">{label}</span></div>
            <div className={`why${rule ? ' rule' : ''}`}>{rule ? `rule: ${rule.why}` : `${r.source} page`}</div>
          </div>
        </div>
      );
    };
    const tree = id => Tr[String(R[String(id)]?.tree)]?.name || '';
    const shardNames = (r.shards || []).map(id => R[String(id)]?.name || id).join(' / ');
    return (
      <div className="card" id="runes">
        {row(r.keystone, `${tree(r.keystone)} keystone`)}
        {(r.primary || []).map(id => row(id, tree(id)))}
        {(r.secondary || []).map(id => row(id, tree(id)))}
        <div className="rune"><span></span><div><div><span className="n">Shards</span>
          <span className="t">{shardNames}</span></div></div></div>
        {(build.skipped || []).map((s, i) => <div className="note" key={i}>{`Skipped ${s.rule}: ${s.why}`}</div>)}
        <div className="note">Typed in by hand in the client; nothing is pushed to it.</div>
      </div>
    );
  }

  function Plan({ plan }) {
    if (!plan) return null;
    const lead = `Your job: ${plan.job}${plan.sharedWith ? `, shared with ${plan.sharedWith}` : ''}.`;
    const covers = Object.entries(plan.covers || {});
    const byAlly = {};
    covers.forEach(([job, who]) => { (byAlly[who] = byAlly[who] || []).push(job); });
    const rest = Object.entries(byAlly).map(([who, jobs]) => `${who} covers ${jobs.join(' and ')}`).join('; ');
    return (
      <div className="card plan" id="plan">
        {plan.provisional ? <span className="prov">provisional</span> : null}
        <b>{lead}</b>{rest ? ` ${rest}.` : ''}
      </div>
    );
  }

  /* Save the advised build as a Forge set, so it lands on the Champions shelf. */
  function SaveSet({ build, patch, champ, R }) {
    const [msg, setMsg] = useState('');
    const [busy, setBusy] = useState(false);
    const save = () => {
      setBusy(true);
      const steps = [...(build.items || []), ...(build.boots ? [build.boots] : [])].sort((a, b) => a.slot - b.slot);
      const r = build.runes;
      const tree = id => R[String(id)]?.tree;
      const runes = r ? {
        primary: tree(r.keystone), keystone: r.keystone, rows: r.primary,
        secondary: tree((r.secondary || [])[0]), sec: r.secondary,
        shards: { offense: r.shards[0], flex: r.shards[1], defense: r.shards[2] }, alts: [],
      } : null;
      const body = {
        name: `Draft ${build.champ} ${role(build.role)}`, patch, champion: build.champ, role: build.role,
        champions: champ ? [champ.k] : [],
        blocks: [{ type: 'Draft build', items: steps.map(s => ({ id: String(s.itemId), count: 1, note: s.why })) }],
        runes,
      };
      fetch('api/sets', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
        .then(res => res.json().then(j => setMsg(res.ok ? `Saved as ${body.name}` : (j.error || 'save failed'))))
        .catch(e => setMsg(String(e)))
        .finally(() => setBusy(false));
    };
    return <div className="save"><button type="button" id="saveSet" onClick={save} disabled={busy}>Save as set</button>
      <span role="status">{msg}</span></div>;
  }

  /* ── team traits ──────────────────────────────────────────────────────── */

  function traitVal(v) {
    if (v && typeof v === 'object') return 'max' in v ? v.max : null;
    return typeof v === 'number' ? v : null;
  }
  const fmt = (name, v) => /Share$/.test(name) ? `${Math.round(v * 100)}%`
    : Math.abs(v) >= 100 ? Math.round(v).toLocaleString() : (Number.isInteger(v) ? String(v) : v.toFixed(1));

  // The traits worth a glance during champ select; the rest fold under "More traits".
  const KEY_TRAITS = ['physicalShare', 'magicShare', 'damage10s', 'hardCC', 'engage', 'frontline', 'peel', 'dive'];

  function TraitRow({ t }) {
    // Fixed scale from the whole champion pool (engine's trait_scales), not the bigger team.
    const top = t.scale || Math.max(Math.abs(t.a), Math.abs(t.e)) || 1;
    return (
      <div className={`tr${t.gap ? ' gap' : ''}`} data-trait={t.name}>
        <span className="bar l"><i style={{ width: `${Math.min(100, 100 * Math.abs(t.a) / top)}%` }}></i></span>
        <span className="lab"><span>{fmt(t.name, t.a)}</span><span>{human(t.name)}{t.gap ? ' · gap' : t.gapState === 'partial' ? ' · partial' : ''}</span>
          <span>{fmt(t.name, t.e)}</span></span>
        <span className="bar r"><i style={{ width: `${Math.min(100, 100 * Math.abs(t.e) / top)}%` }}></i></span>
      </div>
    );
  }

  function Traits({ traits }) {
    const rows = (traits || []).map(t => ({ ...t, a: traitVal(t.ally), e: traitVal(t.enemy) }))
      .filter(t => t.a != null && t.e != null && (t.a || t.e || t.gap || t.gapState));
    if (!rows.length) return <p className="quiet">No traits until a champion locks.</p>;
    const key = rows.filter(t => t.gap || t.gapState || KEY_TRAITS.includes(t.name))
      .sort((x, y) => (y.gap - x.gap) || (KEY_TRAITS.indexOf(x.name) - KEY_TRAITS.indexOf(y.name)));
    const rest = rows.filter(t => !key.includes(t));
    const left = rows[0].excluded?.ally || [], right = rows[0].excluded?.enemy || [];
    return (
      <React.Fragment>
        <div className="tkey"><span>your team</span><span>theirs</span></div>
        <div className="traits">{key.map(t => <TraitRow t={t} key={t.name} />)}</div>
        {rest.length ? <details className="more">
          <summary>{`More traits (${rest.length})`}</summary>
          <div className="traits">{rest.map(t => <TraitRow t={t} key={t.name} />)}</div>
        </details> : null}
        <div className="note">{'Shares are weighted by each champion\'s damage in a 10 s fight, so a big damage dealer counts for more. '
          + (left.length || right.length ? `No trait data yet: ${[...left, ...right].join(', ')}.` : '')}</div>
      </React.Fragment>
    );
  }

  /* ── page ─────────────────────────────────────────────────────────────── */

  /* ── mock draft: he picks every seat; the mock route runs the same engine ── */

  const MOCK = new URLSearchParams(location.search).has('mock');
  const ROLES = ['top', 'jungle', 'mid', 'bot', 'support'];
  const MOCK0 = { me: '', role: 'jungle', locked: false,
    allies: ['', '', '', ''].map((c, i) => ({ c, r: ROLES.filter(x => x !== 'jungle')[i] })),
    enemies: ['', '', '', '', ''], bans: [], game: '' };

  function mockUrl(m) {
    const q = new URLSearchParams({ locked: m.locked ? '1' : '0', role: m.role });
    if (m.me) q.set('me', m.me);
    q.set('allies', m.allies.filter(a => a.c).map(a => `${a.c}:${a.r}`).join(','));
    q.set('enemies', m.enemies.filter(Boolean).join(','));
    if (m.bans.length) q.set('bans', m.bans.join(','));
    const picks = Object.entries(m.picks || {}).map(([c, id]) => `${c}:${id}`).join(',');
    if (picks) q.set('picks', picks);
    if (m.queue) q.set('queue', m.queue);
    return 'api/draft/mock?' + q;
  }

  // A random draft around his seat: his champion and role stay, every other seat
  // gets a champion who plays that role (api/draft/roles), no repeats.
  function shuffle(m, roles, byName) {
    const taken = new Set(m.me ? [String(m.me)] : []);
    const any = (names) => {
      const free = names.map(n => byName[n]).filter(c => c && !taken.has(String(c.k)));
      if (!free.length) return '';
      const c = free[Math.floor(Math.random() * free.length)];
      taken.add(String(c.k));
      return String(c.k);
    };
    const me = m.me || any(roles[m.role] || []);
    const allies = m.allies.map(a => ({ ...a, c: any(roles[a.r] || []) }));
    const enemies = ROLES.map(r => any(roles[r] || []));
    return { ...m, me, allies, enemies, bans: [], game: '', queue: null, picks: {} };
  }

  // The seat pickers. One champion fills one seat, so a champion already
  // used is greyed out everywhere else.
  function pickers(m, setM, champs) {
    const used = new Set([m.me, ...m.allies.map(a => a.c), ...m.enemies].filter(Boolean).map(String));
    const champ = (value, onChange, label) => (
      <select className="pickc" aria-label={label} value={value} onChange={e => onChange(e.target.value)}>
        <option value="">{label}</option>
        {champs.map(c => <option key={c.k} value={c.k}
          disabled={used.has(String(c.k)) && String(c.k) !== String(value)}>{c.n}</option>)}
      </select>);
    const role = (value, onChange, label) => (
      <select className="pickr" aria-label={label} value={value} onChange={e => onChange(e.target.value)}>
        {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
      </select>);
    const at = (arr, i, v) => arr.map((x, j) => j === i ? v : x);
    return { champ, role, at };
  }

  // A past game from his op.gg history, seated as it was: his champion hovering
  // (tick locked in for the build), allies by role, the enemy five, and the
  // game's bans kept out of the pick lists without being drawn.
  function PastGame({ m, setM }) {
    const [games, setGames] = useState(null);
    const [msg, setMsg] = useState('');
    useEffect(() => {
      fetch('api/draft/history').then(r => r.json())
        .then(g => Array.isArray(g) ? setGames(g) : setMsg('op.gg history unavailable')).catch(() => setMsg('op.gg history unavailable'));
    }, []);
    const pick = id => {
      const g = (games || []).find(x => x.id === id);
      if (!g) return;
      setMsg('loading the lobby');
      fetch('api/draft/history?' + new URLSearchParams({ id: g.id, at: g.at })).then(r => r.json()).then(lb => {
        if (lb.error) { setMsg('op.gg could not load that game'); return; }
        const s = k => (k == null ? '' : String(k));
        setM({ ...MOCK0, me: s(lb.me.k), role: lb.me.role || 'jungle', game: id, bans: lb.bans,
          queue: g.queue === 'ARAM' ? 450 : null,
          allies: lb.allies.map(a => ({ c: s(a.k), r: a.role || 'top' })),
          enemies: [...lb.enemies.map(s), '', '', '', '', ''].slice(0, 5) });
        setMsg('');   // the W or L is already in the picked option
      }).catch(() => setMsg('op.gg could not load that game'));
    };
    const when = at => new Date(at).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
    const queue = q => ({ SOLORANKED: 'Solo', FLEXRANKED: 'Flex', NORMAL: 'Normal', ARAM: 'ARAM' }[q] || q);
    return (
      <React.Fragment>
        <select id="pastGame" aria-label="Past game" value={m.game} disabled={!games} onChange={e => pick(e.target.value)}>
          <option value="">{games ? 'Past game' : 'Past game (loading)'}</option>
          {(games || []).map(g => <option key={g.id} value={g.id}>
            {`${when(g.at)} · ${g.champion} ${role(g.role)} · ${queue(g.queue)} · ${g.win ? 'W' : 'L'}`}</option>)}
        </select>
        {msg ? <span className="quiet" role="status">{msg}</span> : null}
      </React.Fragment>);
  }

  function MockTeam({ m, setM, champs, byKey, x }) {
    const { champ, role, at } = pickers(m, setM, champs);
    const c = byKey[m.me];
    const me = archSeat(x, c);
    return (
      <div className="card" id="allies">
        <div className={`seat me${m.me && !m.locked ? ' hover' : ''}`} data-me="1">
          <Portrait c={c} size={64} />
          <div>{champ(m.me, v => setM({ ...m, me: v }), 'You: pick a champion')}
            <div className="r">{role(m.role, v => setM({ ...m, role: v }), 'Your role')}
              <label><input type="checkbox" checked={m.locked}
                onChange={e => setM({ ...m, locked: e.target.checked })} /> locked in</label></div>{me.chip}</div>
          {me.body}
        </div>
        {m.allies.map((a, i) => {
          const ax = archSeat(x, byKey[a.c]);
          return (
            <div className="seat" key={i}>
              <Portrait c={byKey[a.c]} size={64} />
              <div>{champ(a.c, v => setM({ ...m, allies: at(m.allies, i, { ...a, c: v }) }), `Ally ${i + 1}`)}
                <div className="r">{role(a.r, v => setM({ ...m, allies: at(m.allies, i, { ...a, r: v }) }), `Ally ${i + 1} role`)}</div>{ax.chip}</div>
              {ax.body}
            </div>);
        })}
      </div>);
  }

  function MockEnemies({ m, setM, champs, byKey, advice, x }) {
    const { champ, at } = pickers(m, setM, champs);
    const roles = advice?.teams?.enemyRoles || {};
    return (
      <div className="card" id="enemies">{m.enemies.map((k, i) => {
        const c = byKey[k];
        const ax = archSeat(x, c);
        return (
          <div className="seat" key={i}>
            <Portrait c={c} size={64} />
            <div>{champ(k, v => setM({ ...m, enemies: at(m.enemies, i, v) }), `Enemy ${i + 1}`)}
              <div className="r">{c ? (roles[c.n] ? `likely ${roles[c.n]}` : 'role unclear') : 'empty'}</div>{ax.chip}</div>
            {ax.body}
          </div>);
      })}</div>);
  }

  function DraftPage() {
    const [D, setD] = useState(null);
    const [mk, setMk] = useState(MOCK0);
    const [roles, setRoles] = useState(null);
    const [cat, setCat] = useState(null);
    const [runes, setRunes] = useState(null);
    const [, tick] = useState(0);
    const [openSeat, setOpenSeat] = useState(null);
    const [pickMsg, setPickMsg] = useState('');
    const last = useRef('');

    useEffect(() => {
      document.getElementById('forge-root').setAttribute('data-react-mounted', 'forge-draft');
      window.__FORGE.catalog.then(setCat);
      window.__FORGE.runes.then(setRunes);
      if (MOCK) return undefined;                  // mock mode never reads or polls the live feed
      window.__FORGE.draft.then(d => { last.current = JSON.stringify(d); setD(d); });
      let stop = false;
      const poll = () => {
        if (stop) return;
        fetch('api/draft', { cache: 'no-cache' })
          .then(r => r.text())
          .then(t => { if (t !== last.current) { last.current = t; setD(JSON.parse(t)); } })
          .catch(() => {})
          .finally(() => { if (!stop) setTimeout(poll, 500); });
      };
      const t0 = setTimeout(poll, 500);
      const clock = setInterval(() => tick(n => n + 1), 1000);   // the "x s ago" text
      return () => { stop = true; clearTimeout(t0); clearInterval(clock); };
    }, []);

    useEffect(() => {
      if (!MOCK) return undefined;
      if (!roles) fetch('api/draft/roles').then(r => r.json()).then(setRoles).catch(() => {});
      let stale = false;
      const get = () => fetch(mockUrl(mk), { cache: 'no-cache' }).then(r => r.json()).then(d => { if (!stale) setD(d); }).catch(() => {});
      get();
      // op.gg synergy is fetched off the request path, so ask again while it lands.
      const later = [2000, 5000].map(ms => setTimeout(get, ms));
      return () => { stale = true; later.forEach(clearTimeout); };
    }, [mk]);

    useEffect(() => {
      if (!openSeat) return undefined;
      const key = e => {
        if (e.key !== 'Escape') return;
        document.querySelector('.ax-open[aria-expanded="true"]')?.focus();
        setOpenSeat(null);
      };
      const down = e => { if (!e.target.closest('.seat')) setOpenSeat(null); };
      document.addEventListener('keydown', key);
      document.addEventListener('mousedown', down);
      return () => { document.removeEventListener('keydown', key); document.removeEventListener('mousedown', down); };
    }, [openSeat]);

    const byKey = {}, byName = {}, items = {};
    (cat?.champs || []).forEach(c => { byKey[c.k] = c; byName[c.n] = c; });
    (cat?.items || []).forEach(i => { items[i.id] = i; });

    const draft = D?.draft;
    const advice = D?.advice;
    const build = D?.build;
    const onPick = (champ, id) => {
      if (MOCK) { setMk(m => ({ ...m, picks: { ...m.picks, [champ]: id } })); return; }
      fetch('api/draft/pick', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ champion: champ, archetypeId: id }) })
        .then(res => res.json().then(j => setPickMsg(res.ok ? '' : (j.error || j.message || 'pick not saved'))))
        .catch(e => setPickMsg(String(e)));
    };
    const x = { arch: advice?.archetypes || {}, mode: advice?.mode, items, R: runes?.runes || {}, open: openSeat, msg: pickMsg,
      toggle: n => { setPickMsg(''); setOpenSeat(o => (o === n ? null : n)); }, onPick };
    // An open seat is one champion: once they leave the draft it stays closed, here and next game.
    useEffect(() => {
      if (openSeat && advice && !advice.archetypes?.[openSeat]) setOpenSeat(null);
    }, [advice, openSeat]);
    // With nothing to replay, the offline sentence is the middle card's job.
    const err = D?.engineError || (D?.error === 'POLLER_OFFLINE' && !D?.draft ? null : D?.error);
    const meChamp = draft?.me?.championId ? byKey[draft.me.championId] : null;

    const status = !D ? 'loading' : D.status;
    const statusWord = { live: 'live', idle: 'waiting for champ select', offline: 'offline', loading: 'connecting', mock: 'mock draft' }[status] || status;
    const st = advice?.stores || {};
    const parts = [statusWord];
    if (D?.capturedAt) parts.push(`poller ${ago(D.capturedAt)}`);
    if (st.matchups) parts.push(`lolalytics ${st.matchups}`);
    if (st.traits) parts.push(`traits ${st.traits}`);
    if (st.opggFetchedAt) parts.push(`op.gg ${ago(st.opggFetchedAt)}`);
    if (meChamp) parts.push(`you locked ${meChamp.n}`);
    if (D?.replay && draft) parts.push('replay of the last draft');
    if (advice?.modeNote && !MOCK) parts.push(advice.modeNote);

    const patch = (cat?.ver || '').split('.').slice(0, 2).join('.');

    let middle;
    if (!draft) {
      middle = <div className="card"><p className="quiet">{status === 'offline'
        ? 'The poller is not running. Start it on Windows and open champ select.'
        : 'Waiting for champ select. The page fills in as soon as the client enters it.'}</p></div>;
    } else if (meChamp && build?.mode === 'mayhem') {
      middle = (
        <React.Fragment>
          <Plan plan={advice?.plan} />
          <div className="locked">
            <div className="col"><h3>Build <span className="pill">{build.source === 'aram' ? 'ARAM' : 'Mayhem'}</span></h3>
              <MayhemBuild build={build} items={items} /></div>
            <div className="col"><h3>Augments <span className="pill">metasrc</span></h3>
              <Augments aug={build.augments} /></div>
          </div>
        </React.Fragment>
      );
    } else if (meChamp && build) {
      middle = (
        <React.Fragment>
          <Plan plan={advice?.plan} />
          <div className="locked">
            <div className="col"><h3>Build <span className="pill">{build.source}</span></h3>
              <Build build={build} items={items} />
              <SaveSet build={build} patch={patch} champ={meChamp} R={runes?.runes || {}} /></div>
            <div className="col"><h3>Runes</h3>{runes ? <Runes build={build} runes={runes} /> : null}</div>
          </div>
        </React.Fragment>
      );
    } else {
      middle = (
        <div className="lists">
          <div className="col"><h3>Your pool</h3>
            <div className="card" id="pool"><PickList rows={advice?.pool || []} byName={byName}
              empty="Every pool champion is banned or taken." /></div></div>
          <div className="col"><h3>Best overall</h3>
            <div className="card" id="overall"><PickList rows={advice?.overall || []} byName={byName} ranked
              empty={advice ? 'No champion has matchup data for this draft yet.' : 'No advice yet.'} /></div></div>
        </div>
      );
    }

    return (
      <React.Fragment>
        <ForgeUI.Bar current="draft" />
        <div className="wrap">
          {/* the base href is /forge/, so these resolve to /forge/draft and /forge/draft?mock */}
          <nav className="modes" aria-label="Draft mode">
            <a href="draft" aria-current={MOCK ? undefined : 'page'}>Live draft</a>
            <a href="draft?mock" aria-current={MOCK ? 'page' : undefined}>Mock draft</a>
            {MOCK ? <React.Fragment>
              <button type="button" id="shuffle" disabled={!roles || !cat}
                onClick={() => setMk(shuffle(mk, roles, byName))}>Shuffle</button>
              <button type="button" id="clear" onClick={() => setMk({ ...MOCK0, me: mk.me, role: mk.role })}>Clear</button>
              <PastGame m={mk} setM={setMk} />
            </React.Fragment> : null}
          </nav>
          <div className={`status ${status}`} id="status"><span><span className="dot"></span>{parts.join(' · ')}</span></div>
          {err ? <div className="err" id="err" role="alert"><code>{errCode(err)}</code>{ERRORS[errCode(err)] || err}</div> : null}
          {draft ? (
            <div className="desk">
              <div className="col"><h3>Your team</h3>{MOCK
                ? <MockTeam m={mk} setM={setMk} champs={cat?.champs || []} byKey={byKey} x={x} />
                : <YourTeam draft={draft} byKey={byKey} x={x} />}</div>
              <div className="mid">
                {middle}
                <div className="col"><h3>Team traits</h3><div className="card" id="traits"><Traits traits={advice?.traits} /></div></div>
              </div>
              <div className="col"><h3>Enemy team</h3>{MOCK
                ? <MockEnemies m={mk} setM={setMk} champs={cat?.champs || []} byKey={byKey} advice={advice} x={x} />
                : <EnemyTeam draft={draft} advice={advice} byKey={byKey} x={x} />}
                {MOCK ? null : <React.Fragment><h3>Bans</h3><div className="bans" id="bans">{(draft.bans || []).map(k => byKey[k]
                  ? <img key={k} src={byKey[k].u} alt={byKey[k].n} title={byKey[k].n} /> : null)}</div></React.Fragment>}</div>
            </div>
          ) : middle}
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

  window.ForgeUI.DraftPage = DraftPage;
  ReactDOM.createRoot(document.getElementById('forge-root')).render(<ErrorBoundary><DraftPage /></ErrorBoundary>);
})();
