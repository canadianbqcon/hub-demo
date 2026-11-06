/* champion.jsx - one page per champion: who they are, every archetype, abilities with
   the calculator's own numbers beside the wiki text, base stats, how to play, patch
   history, and the saved sets.

   Layout A from the Workbench pick (forge-champion-page-layout): everything to read on
   the left, the chosen build pinned on the right. Every value comes from
   /forge/api/champion/<champ> (the page store joined with archetypes, traits and quote),
   static/catalog.json (item names and icons) or static/runes.json; anything absent
   reads "not read". Text only: nothing from the store is rendered as HTML.

   The head preflight in champion.html starts every fetch (window.__FORGE). The saved
   sets list and the build overlay are unchanged from the build-list page. */
window.ForgeUI = window.ForgeUI || {};

(() => {
  const { useState, useEffect, useRef } = React;

  const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
  const games = n => n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k` : String(n);
  const num = (v, d = 1) => v == null ? null : (Math.round(v * 10 ** d) / 10 ** d).toLocaleString();
  const pct = v => `${Math.round(v * 100)}%`;
  const nth = n => n + ((n % 100 >= 11 && n % 100 <= 13) ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th'));
  const safeUrl = u => /^https:\/\//.test(u || '') ? u : null;

  const seg = location.pathname.match(/\/c\/([^/]+)(?:\/([^/]+))?\/?$/);
  const asked = seg ? decodeURIComponent(seg[1]) : '';
  const WANTED = decodeURIComponent(location.hash.slice(1));
  const ARCH0 = new URLSearchParams(location.search).get('arch');  // the draft seat's archetype
  const TAB0 = new URLSearchParams(location.search).get('tab');

  const countItems = s => (s.blocks || []).reduce((a, b) => a + (b.items || [])
    .reduce((x, i) => x + (i.count || 1), 0), 0);

  /* ── saved sets (unchanged) ─────────────────────────────────────────── */

  function SetRow({ s, runeMeta }) {
    const ks = s.runes?.keystone ? runeMeta(s.runes.keystone) : null;
    const stale = [...new Set(Object.values(s.sources || {}).filter(p => p && p !== s.patch))];
    const bits = [
      s.auto ? `patch ${s.patch}` : null,
      s.role ? s.role : null,
      countItems(s) ? `${plural((s.blocks || []).filter(b => b.items?.length).length, 'block')} · ${plural(countItems(s), 'item')}` : 'runes only',
      s.forkedFrom ? 'carried forward' : null,
      stale.length ? `data from ${stale.join(', ')}` : null,
    ].filter(Boolean);
    return (
      <button type="button" className="set" data-set={s.id}>
        {ks ? <img src={ks.icon} alt="" /> : <i className="ks-none"></i>}
        <span><strong>{s.name}</strong>{s.auto ? <span className="tag">Auto</span> : null}<span className="sub">{bits.join(' · ')}</span></span>
      </button>
    );
  }

  /* His builds and Auto sets are separate shelves: an Auto set is Autobuild's,
     read-only, rebuilt each patch rather than carried forward. */
  function Groups({ sets, live, champ, runeMeta }) {
    // the newest Auto set per source key: an older-patch one is superseded, not a second build
    const best = new Map();
    for (const s of sets.filter(x => x.auto === true)) {
      const k = `${s.role}|${s.autoKey || s.name}`, o = best.get(k);
      if (!o || (s.patch || '').localeCompare(o.patch || '', undefined, { numeric: true }) > 0) best.set(k, s);
    }
    const auto = [...best.values()]
      .sort((a, b) => (b.patch || '').localeCompare(a.patch || '', undefined, { numeric: true }) || (a.name || '').localeCompare(b.name || ''));
    return (
      <React.Fragment>
        <h4 className="shelf-h">My builds</h4>
        <MyGroups sets={sets.filter(s => s.auto !== true)} live={live} champ={champ} runeMeta={runeMeta} />
        {auto.length ? (
          <React.Fragment>
            <h4 className="shelf-h">Auto <span className="n">{plural(auto.length, 'set')}</span></h4>
            <div className="sets">{auto.map(s => <SetRow s={s} runeMeta={runeMeta} key={s.id} />)}</div>
          </React.Fragment>) : null}
      </React.Fragment>
    );
  }

  function MyGroups({ sets, live, champ, runeMeta }) {
    const by = new Map();
    for (const s of sets) {
      const p = s.patch || 'unfiled';
      if (!by.has(p)) by.set(p, []);
      by.get(p).push(s);
    }
    const patches = Array.from(by.keys()).sort((a, b) => b.localeCompare(a, undefined, { numeric: true }));
    if (live && !by.has(live)) patches.unshift(live);
    if (!patches.length) {
      return <p className="none"><b>{`Nothing saved for ${champ} yet.`}</b>{' New set opens the rune page first, then the items.'}</p>;
    }
    return patches.map(p => {
      const list = (by.get(p) || []).sort((a, b) => (b.updated || '').localeCompare(a.updated || ''));
      return (
        <section className="group" key={p}>
          <h3>{`Patch ${p}`}{p === live ? <span className="tag">current</span> : null}
            <span className="n">{list.length ? plural(list.length, 'set') : ''}</span></h3>
          {list.length
            ? <div className="sets">{list.map(s => <SetRow s={s} runeMeta={runeMeta} key={s.id} />)}</div>
            : <p className="none"><b>{`No sets yet on patch ${p}.`}</b>{' Start one, or open a build from an earlier patch below and copy it forward.'}</p>}
        </section>
      );
    });
  }

  /* ── shared bits ────────────────────────────────────────────────────── */

  const roleName = r => r === 'aram' ? 'ARAM' : r;
  const NotRead = () => <span className="cp-none">not read</span>;

  function Head({ id, t, sub, children }) {
    return <h3 className="cp-h" id={id}>{t}{sub ? <span className="cp-sub">{sub}</span> : null}{children}</h3>;
  }

  function Ic({ o, k }) {
    if (!o) return <i className={`cp-ic${k ? ' k' : ''}`}></i>;
    return <img className={`cp-ic${k ? ' k' : ''}`} src={o.u} alt={o.n} title={o.n} />;
  }

  /* traits: value with its unit, "not read" when the calculator has none */
  const TR = [['damage10s', '10 s damage'], ['damage10sPost', 'After resists'], ['physicalShare', 'Physical'], ['magicShare', 'Magic'], ['trueShare', 'True'],
    ['pctHealthShare', 'Percent health'], ['burstShare', 'First 3 s'], ['hardCC', 'Hard CC'], ['softCC', 'Soft CC'], ['engage', 'Engage'], ['peel', 'Peel'], ['dive', 'Dive'],
    ['frontline', 'Frontline'], ['zoneControl', 'Zone control'], ['autoReliance', 'Auto reliance'], ['attackRange', 'Attack range'], ['moveSpeed', 'Move speed'],
    ['towerDps', 'Tower damage per s'], ['hp', 'Health'], ['armor', 'Armor'], ['mr', 'Magic resist'], ['selfHeal', 'Self heal'], ['wallCrossing', 'Wall crossing'],
    ['execute', 'Execute'], ['cleanse', 'Cleanse'], ['vision', 'Vision']];
  const KEY = ['damage10s', 'trueShare', 'pctHealthShare', 'burstShare', 'hardCC', 'dive', 'peel', 'autoReliance'];

  function fmtVal(r, v) {
    if (v === true) return 'yes';
    if (v === false) return 'no';
    if (r.unit === 'share') return pct(v);
    if (r.unit === '0..5') return `${v} of 5`;
    if (typeof v === 'number') return num(v);
    return String(v);
  }
  /* an estimate rides on assumed stacks: "~" plus its low-to-high range, never shown as computed */
  function traitVal(r) {
    if (!r || r.value == null) return <NotRead />;
    if (r.source !== 'estimate') return fmtVal(r, r.value);
    const [lo, hi] = r.range ? r.range.map(x => fmtVal(r, x)) : [];
    const span = r.range && lo !== hi ? `${lo} to ${hi}` : 'estimate';   // ends that print alike are flat
    return <>{`~${fmtVal(r, r.value)}`}<span className="cp-num">{span}</span></>;
  }

  function Traits({ arch, list }) {
    const t = arch?.traits || {};
    return (
      <div className={`cp-traits${list === TR ? ' wide' : ''}`}>
        {list.map(([k, label]) => {
          // place: where this value sits among every champion, 0 lowest to 1 highest (mark 2026-11-04-065542:2)
          const p = t[k]?.place;
          return p == null
            ? <div className="cp-t" key={k}><span>{label}</span><b>{traitVal(t[k])}</b></div>
            : <div className="cp-t placed" key={k} style={{ '--p': p }}
                title={`Higher than ${Math.round(p * 100)}% of ${t[k].of} champions`}><span>{label}</span><b>{traitVal(t[k])}</b></div>;
        })}
      </div>);
  }

  /* ── left column sections ───────────────────────────────────────────── */

  function Identity({ name, i }) {
    if (!i) return <><Head id="identity" t={`Who ${name} is`} /><p className="cp-note">Identity not read.</p></>;
    return (
      <>
        <Head id="identity" t={`Who ${name} is`} />
        <div className="cp-tags">
          {(i.tags || []).map(t => <span key={t}>{t}</span>)}
          {i.resource ? <span>{i.resource === 'None' ? 'No resource' : i.resource}</span> : null}
          {i.released ? <span>{`Released ${i.released}`}</span> : null}
          {i.changes ? <span>{`Last changed ${i.changes}`}</span> : null}
        </div>
        {i.lore ? <p className="cp-lore">{i.lore}</p> : null}
      </>);
  }

  /* one calculator line, labelled by kind; parts are not summed because kit() keeps
     the percent-health part beside the flat lines rather than inside them */
  const LINE = { physical: 'physical', magic: 'magic', true: 'true', pct: 'from max health', heal_self: 'self heal',
    heal_ally: 'ally heal', shield_self: 'self shield', shield_ally: 'ally shield' };
  /* each part as [label, per-rank value]; ranks that share a label read "a / b / c label" */
  const lineParts = lines => Object.entries(lines || {}).flatMap(([k, v]) => k === 'ofHealth'
    ? v.map(([kind, which, ratio]) => [`${which} health ${kind}`, `${num(ratio * 100, 2)}%`])
    : [[LINE[k] || k, String(Math.round(v))]]);
  function effectParts(effects) {
    return (effects || []).filter(e => e.trigger !== 'note').map(e => {
      const when = e.once ? 'once' : e.trigger === 'every-n' ? `every ${nth(e.n)} hit` : e.trigger === 'on-hit' ? 'on every hit' : e.trigger;
      const what = e.kind || LINE[e.out] || e.out;  // heal and shield lines name `out`, not `kind`
      return e.pctTarget
        ? [`of target ${e.pctTarget} health as ${what}, ${when}`, `${num(e.ratio * 100, 1)}%`]
        : [`${what}, ${when}`, String(Math.round(e.base))];
    });
  }
  function byRank(perRank) {
    const labels = perRank.map(p => p.map(x => x[0]).join('|'));
    if (labels.every(l => l === labels[0]))
      return perRank[0].map(([label], i) => `${perRank.map(p => p[i][1]).join(' / ')} ${label}`).join(', ');
    return perRank.map(p => p.map(([label, v]) => `${v} ${label}`).join(', ') || 'none').join(' / ');
  }

  function CalcLine({ slot, rows, ctx }) {
    if (slot === 'I') return <p className="cp-calc none">The calculator does not read the innate; it covers Q, W, E and R.</p>;
    if (!rows?.length) return <p className="cp-calc none">No calculator row for this slot.</p>;
    const notes = [...new Set(rows.flatMap(r => (r.effects || []).filter(e => e.trigger === 'note').map(e => e.name)))];
    const unk = [...new Set(rows.flatMap(r => [...(r.unknown || []), ...(r.unread || [])]))];
    const stacks = [...new Map(rows.flatMap(r => r.stacks || []).map(s => [s.basis, s])).values()];
    const tail = (
      <>
        {stacks.map(s => <span className="cp-ctx" key={s.basis}>{`Estimate, read at ${s.typical} stacks (low ${s.low}, high ${s.high}): ${s.basis}.`}</span>)}
        {notes.length ? <span className="cp-ctx">{notes.join('. ')}</span> : null}
        {unk.length ? <span className="cp-ctx">{`Not read: ${unk.join(', ')}`}</span> : null}
        {ctx ? <span className="cp-ctx">{`Rank 1 to ${rows.length}, level ${ctx.level}, ${ctx.items}`}</span> : null}
      </>);
    if (!rows[0].lines) {  // no cast of its own (Vayne W): its numbers are effects
      const per = rows.map(r => effectParts(r.effects));
      return <p className="cp-calc"><b>{stacks.length ? 'Calculator estimate' : 'Calculator'}</b>{per.some(p => p.length) ? `${byRank(per)}. No cast of its own.` : 'no hit of its own.'}{tail}</p>;
    }
    const parts = rows.map(r => [...lineParts(r.lines), ...effectParts(r.effects)]);
    const cd = rows.map(r => r.cooldown == null ? '?' : num(r.cooldown, 2));
    const hard = rows[0].hard ? `, ${num(rows[0].hard, 2)} s hard CC` : '';
    const soft = rows[0].soft ? `, ${num(rows[0].soft, 2)} s soft CC` : '';
    return (
      <p className="cp-calc"><b>{stacks.length ? 'Calculator estimate' : 'Calculator'}</b>
        {parts.some(p => p.length) ? rich(`${byRank(parts)} per cast`) : 'no hit of its own'}
        {rich(`, cooldown ${cd.join(' / ')}${hard}${soft}`)}{tail}
      </p>);
  }

  function Checks({ a }) {
    if (a.slot === 'I') return null;
    return (
      <div className="cp-checks">{(a.check || []).map(c => (
        <span className={`cp-chk ${c.state.replace(' ', '-')}`} key={c.field}
          title={c.state === 'differs' ? `calculator ${JSON.stringify(c.bin)}, wiki ${c.wiki}` : undefined}>{`${c.field} ${c.state}`}</span>))}
      </div>);
  }

  /* Ability text read at a glance (mark 2026-11-04-065542:1): the Passive / Active
     label, damage types and scalings in their League colours, numbers in bold.
     ponytail: one regex over plain wiki text; nested scaling parens go one level deep. */
  const TOK = /^((?:Passive|Active|Innate|Toggle|Recast|Second Cast|Third Cast|Empowered)[^:]{0,30}):|(\(\+[^()]*(?:\([^()]*\)[^()]*)*\))|\b(magic|physical|true)( damage)\b|\b(heal(?:s|ing)?|shield(?:s|ing)?)\b|(\d+(?:\.\d+)?%?(?:\s*(?:\/|–|-|to)\s*\d+(?:\.\d+)?%?)*)/g;
  const scaleKind = t => /AP\b/.test(t) ? 'ap' : /AD\b/.test(t) ? 'ad' : /health|HP/i.test(t) ? 'hp' : /armor|magic resist|MR\b/i.test(t) ? 'res' : 'etc';
  /* "(+ 1% (+ 0.6% per 100 AP) of the target's maximum health)": League colours the
     outer part by what it scales off (health) and only the inner part by AP
     (send-back on mark 2026-11-04-065542:1) */
  function scaling(t) {
    const inner = t.slice(1, -1).match(/\([^()]*\)/);
    if (!inner) return <span className={`cp-sc ${scaleKind(t)}`}>{t}</span>;
    const kind = scaleKind(t.replace(inner[0], ''));
    const at = inner.index + 1;
    return <span className={`cp-sc ${kind}`}>{t.slice(0, at)}
      <span className={`cp-sc ${scaleKind(inner[0])}`}>{inner[0]}</span>{t.slice(at + inner[0].length)}</span>;
  }
  function rich(text) {
    const out = []; let last = 0, m, k = 0;
    TOK.lastIndex = 0;
    while ((m = TOK.exec(text))) {
      if (m.index > last) out.push(text.slice(last, m.index));
      if (m[1]) out.push(<b className="cp-lbl" key={k++}>{m[1]}</b>);
      else if (m[2]) out.push(<React.Fragment key={k++}>{scaling(m[2])}</React.Fragment>);
      else if (m[3]) out.push(<span className={`cp-dmg ${m[3]}`} key={k++}>{m[3] + m[4]}</span>);
      else if (m[5]) out.push(<span className="cp-dmg heal" key={k++}>{m[5]}</span>);
      else out.push(<b className="cp-n" key={k++}>{m[6]}</b>);
      last = TOK.lastIndex;
    }
    if (last < text.length) out.push(text.slice(last));
    return out;
  }

  // Evolved forms carry Riot's red icon (khazix_q_red.png), only on CommunityDragon (mark 2026-11-05-024817:3)
  function Ability({ a, icon, rows, ctx, evolved, fallback, evoIcon }) {
    const f = [a.cost, a.cooldown ? `${a.cooldown} s` : null, a.range ? `${a.range} range` : null].filter(Boolean);
    const url = safeUrl(a.url);
    return (
      <article className="cp-ab" id={`ab-${a.slot}-${a.form}`}>
        <div className="cp-ab-h">
          {icon ? <img src={icon} alt="" onError={fallback ? e => { e.currentTarget.onerror = null; e.currentTarget.src = fallback; } : undefined} /> : <i></i>}
          <span className="cp-key">{a.slot === 'I' ? 'P' : a.slot}</span>
          <div><b>{a.name}</b>{f.length ? <span className="cp-num">{f.join(', ')}</span> : null}</div>
        </div>
        {(a.text || []).map((t, i) => <p key={i}>{rich(t)}</p>)}
        {(a.ranks || []).length ? (
          <dl className="cp-ranks">{a.ranks.map((r, i) => <React.Fragment key={i}><dt>{r.label}</dt><dd>{rich(String(r.values))}</dd></React.Fragment>)}</dl>
        ) : null}
        {rows === null ? null : <CalcLine slot={a.slot} rows={rows} ctx={ctx} />}
        <Checks a={a} />
        {(a.notes || []).length || url ? (
          <details className="cp-more"><summary>{a.notes?.length ? plural(a.notes.length, 'wiki note') : 'wiki page'}</summary>
            {a.notes?.length ? <ul>{a.notes.map((n, i) => <li key={i}>{n}</li>)}</ul> : null}
            {url ? <a href={url} target="_blank" rel="noopener">Wiki page</a> : null}
          </details>) : null}
        {evolved?.length ? (
          <section className="cp-evo"><h5>Evolved</h5>
            {evolved.map(e => <Ability a={e} key={`${e.slot}-${e.form}`} icon={evoIcon ? evoIcon(e.slot) : icon} fallback={icon} rows={null} ctx={ctx} />)}
          </section>) : null}
      </article>);
  }

  const ORDER = { I: 0, Q: 1, W: 2, E: 3, R: 4 };
  function Abilities({ page, calc, ver }) {
    const ab = page?.abilities?.value;
    if (!ab) return <><Head id="abilities" t="Abilities" /><p className="cp-note">Abilities not read.</p></>;
    const icons = page.identity?.value?.icons || {};
    const iconOf = slot => {
      const base = `https://ddragon.leagueoflegends.com/cdn/${ver}/img/`;
      if (slot === 'I') return icons.passive ? `${base}passive/${icons.passive}` : null;
      const f = (icons.spells || [])[ORDER[slot] - 1];
      return f ? `${base}spell/${f}` : null;
    };
    const key = ((icons.spells || [])[0] || '').replace(/Q\.png$/, '').toLowerCase();  // ddragon id, KhazixQ.png -> khazix
    const evoIcon = key ? slot => `https://raw.communitydragon.org/latest/game/assets/characters/${key}/hud/icons2d/${key}_${slot.toLowerCase()}_red.png` : null;
    const gaps = Object.entries(page.abilities.slots || {}).filter(([, s]) => s.gap).map(([k, s]) => `${k}: ${[].concat(s.gap).join(', ')}`);
    const isEvo = a => /^Evolved /.test(a.name || '');
    const list = [...ab].filter(a => !isEvo(a) || !ab.some(b => b.slot === a.slot && !isEvo(b)))
      .sort((x, y) => ORDER[x.slot] - ORDER[y.slot]);
    return (
      <>
        <Head id="abilities" t="Abilities" sub="wiki text, calculator numbers beside it" />
        {list.map(a => <Ability a={a} key={`${a.slot}-${a.form}`} icon={iconOf(a.slot)}
          rows={calc?.byRank?.[a.slot]} ctx={calc?.context}
          evolved={isEvo(a) ? [] : ab.filter(e => e.slot === a.slot && isEvo(e))} evoIcon={evoIcon} />)}
        {gaps.length ? <p className="cp-note">{`Named by the wiki but not read: ${gaps.join('; ')}.`}</p> : null}
      </>);
  }

  function Play({ name, i, quote, ver, spikes }) {
    const q = quote && quote.quote ? quote : null;
    const ally = i?.allyTips || [], enemy = i?.enemyTips || [];
    return (
      <>
        <Head id="play" t="How to play" />
        {q ? (
          <blockquote className="cp-q">{`"${q.quote}"`}
            <cite>{safeUrl(q.url) ? <a href={q.url} target="_blank" rel="noopener">{q.title || 'Video'}</a> : q.title}
              {q.uploaded ? `, uploaded ${q.uploaded}` : ''}</cite>
          </blockquote>) : <p className="cp-note">No guide quote read for this champion.</p>}
        {ally.length || enemy.length ? (
          <>
            <div className="cp-tips">
              <div><h4>{`Playing ${name}`}</h4><ul>{ally.map((t, n) => <li key={n}>{t}</li>)}</ul></div>
              <div><h4>{`Against ${name}`}</h4><ul>{enemy.map((t, n) => <li key={n}>{t}</li>)}</ul></div>
            </div>
            <p className="cp-note">{`Riot's tips, patch ${ver}.`}</p>
          </>) : <p className="cp-note">{`Riot publishes no tips for ${name}.`}</p>}
        <Spikes name={name} s={spikes} />
      </>);
  }

  // The sheet's tips are one run-on paragraph; one sentence per bullet, words untouched.
  const sentences = t => t.split(/(?<=[.!?])\s+(?=[A-Z])/).map(x => x.trim()).filter(Boolean);

  // The community power-spikes sheet, verbatim (bake_spikes.py). Pre-2024 items are flagged.
  function Spikes({ name, s }) {
    if (!s) return <p className="cp-note">{`The power-spikes sheet has no row for ${name}.`}</p>;
    const many = s.rows.length > 1;
    return (
      <>
      <div className="cp-tips">
        {s.rows.map((r, n) => (
          <div key={n}><h4>{many || r.label !== name ? `Power spikes: ${r.label}` : 'Power spikes'}</h4><ul>
            {r.items ? <li>{`Items: ${r.items}`}</li> : null}
            {r.levels ? <li>{`Levels: ${r.levels}`}</li> : null}
            {r.tips ? <li>{`Fighting ${name}:`}<ul>{sentences(r.tips).map((t, k) => <li key={k}>{t}</li>)}</ul></li> : null}
          </ul></div>))}
      </div>
        {s.rows.some(r => r.authored) ? (
          <p className="cp-note">{`Written by Claude on 2026-11-04 (this champion is newer than the community sheet), from the wiki kit text and the current lolalytics builds`}
            {(s.rows[0].sources || []).filter(safeUrl).map((u, n) => <React.Fragment key={u}>{n ? ', ' : ', plus '}<a href={u} target="_blank" rel="noopener">{new URL(u).hostname}</a></React.Fragment>)}{'.'}</p>
        ) : <p className="cp-note">{'From a community '}{safeUrl(s.source) ? <a href={s.source} target="_blank" rel="noopener">power-spikes sheet</a> : 'power-spikes sheet'}
          {s.rows.some(r => r.oldItems) ? ', written before the 2024 item rework: "Mythic" means your first full item.' : '.'}</p>}
      </>);
  }

  function TraitsSection({ arch }) {
    const r = arch?.traits?.damage10s;
    const core = arch ? arch.coreNames : '';
    const ests = Object.values(arch?.traits || {}).filter(t => t?.source === 'estimate');
    const est = ests.length > 0;
    // each estimate row's basis minus the fight basis the note already printed, once per distinct text
    const estBases = [...new Set(ests.map(t => (t.basis || '').replace(r?.basis || '\u0000', '').replace(/^[;.\s]+/, '')).filter(Boolean))];
    return (
      <>
        <Head id="traits" t="What the calculators read" sub={core} />
        <Traits arch={arch} list={TR} />
        {r?.basis ? (
          <p className="cp-note">{`${r.source === 'estimate' ? 'Estimate' : 'Computed'}: ${r.basis}.`}
            {est ? ' A ~ number rides on estimated stacks; its low-to-high range sits under it when the fight reads one, else it says estimate.' : ''}
            {est && r.source !== 'estimate' && estBases.length ? ` Estimate: ${estBases.join('; ')}.` : ''}
            {r.excluded?.length ? ` Left out: ${r.excluded.join(', ')}.` : ''}
            {' A lone fight on a target that never hits back, for comparing champions, not a real trade.'}</p>) : null}
      </>);
  }

  const STATS = [['hp', 'Health'], ['mp', null], ['armor', 'Armor'], ['mr', 'Magic resist'], ['ad', 'Attack damage'],
    ['as', 'Attack speed'], ['ms', 'Move speed'], ['range', 'Attack range'], ['hp5', 'Health regen per 5 s'], ['mp5', null]];
  function Stats({ s, resource, places }) {
    if (!s) return <><Head id="stats" t="Base stats" /><p className="cp-note">Stats not read.</p></>;
    const res = resource && resource !== 'None' ? resource : 'Resource';  // Riot writes 'None' for no bar
    const state = key => {
      const c = (s.check || []).filter(x => x.field === key || x.field.startsWith(`${key} `)).map(x => x.state);
      if (!c.length) return 'not compared';
      if (c.includes('differs')) return 'differs';
      return c.every(x => x === 'verified') ? 'verified' : 'not comparable';
    };
    const fmt = v => v == null ? <NotRead /> : num(v, 3);
    // where the value sits among every champion, the trait rows' red-to-green scale
    const cell = (k, i, body) => {
      const p = places?.[k]?.[i];
      return p == null ? <td>{body}</td>
        : <td className="cp-pl" style={{ '--p': p }} title={`Higher than ${Math.round(p * 100)}% of champions`}>{body}</td>;
    };
    return (
      <>
        <Head id="stats" t="Base stats" sub="the calculators' inputs, wiki beside them; colour is the place among every champion, red low to green high" />
        <table className="cp-stats">
          <thead><tr><th>Stat</th><th>Base</th><th>Per level</th><th>Against wiki</th></tr></thead>
          <tbody>{STATS.map(([k, label]) => {
            const fromCalc = k in (s.calculator || {});
            const v = fromCalc ? s.calculator[k] : s.wiki?.[k];
            if (v === undefined) return null;
            const [base, lvl] = Array.isArray(v) ? v : [v, undefined];
            const st = fromCalc ? state(k) : 'not compared';
            const name = label || (k === 'mp' ? res : `${res} regen per 5 s`);
            return (
              <tr key={k}><td>{name}</td>{cell(k, 0, fmt(base))}
                {lvl === undefined ? <td></td> : cell(k, 1, lvl == null ? <NotRead /> : `${num(lvl, 3)}${k === 'as' ? '%' : ''}`)}
                <td><span className={`cp-chk ${st.replace(' ', '-')}`}>{fromCalc ? st : 'wiki only'}</span></td></tr>);
          })}</tbody>
        </table>
      </>);
  }

  /* "Base damage increased to 22 – 141 (based on level) from 17 – 136 (based on level)."
     reads "Base damage 17 – 136 → 22 – 141 (based on level)"; a line that does not
     parse keeps its sentence (mark 2026-11-05-024817:6) */
  function Change({ l }) {
    const m = l.text.match(/^(.+?) (?:increased|reduced) to (.+?) from (.+?)\.?$/);
    if (!m) return <span>{l.text}</span>;
    let [, field, now, was] = m, tail = '';
    const t = now.match(/ (\([^()]*\))$/);
    if (t && was.endsWith(t[0])) { tail = ` ${t[1]}`; now = now.slice(0, -t[0].length); was = was.slice(0, -t[0].length); }
    return <span>{`${field} `}<span className="cp-was">{was}</span>{' → '}
      <b className={`cp-now${l.verdict ? ` ${l.verdict}` : ''}`}>{now}</b>{tail}</span>;
  }
  const dayOf = d => new Date(`${d}T12:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

  function History({ h, limit, dates }) {
    const [filter, setFilter] = useState('all');
    const [all, setAll] = useState(false);
    if (!h) return <><Head id="history" t="Buffs and nerfs" /><p className="cp-note">Patch history not read.</p></>;
    const keep = l => filter === 'all' || (filter === 'change' ? !l.verdict : l.verdict === filter);
    const total = h.reduce((n, p) => n + p.lines.filter(keep).length, 0);
    let left = all ? Infinity : limit;
    const out = [];
    for (const p of h) {
      const L = p.lines.filter(keep).slice(0, left);
      if (!L.length) continue;
      left -= L.length;
      out.push(
        <section className="cp-p" key={p.patch}><h4>{p.patch}{dates?.[p.patch] ? <span className="cp-date">{dayOf(dates[p.patch])}</span> : null}</h4>
          <ul className="cp-lines">{L.map((l, i) => (
            <li key={i}><span className={`cp-v${l.verdict ? ` ${l.verdict}` : ''}`}>{l.verdict || 'change'}</span>
              <span className="cp-num">{l.on}</span><Change l={l} /></li>))}</ul>
        </section>);
    }
    return (
      <>
        <Head id="history" t="Buffs and nerfs" sub={`${h.length} patches, back to release`} />
        <div className="cp-seg small">{['all', 'buff', 'nerf', 'change'].map(x => (
          <button type="button" key={x} className={x === filter ? 'on' : ''} onClick={() => setFilter(x)}>{x}</button>))}</div>
        {out}
        {!all && total > limit ? <button type="button" className="cp-all" onClick={() => setAll(true)}>{`Show all ${total} lines`}</button> : null}
        <p className="cp-note">Buff or nerf is arithmetic on the wiki's numbers, set only when the whole line reads cleanly. Other lines say change.</p>
      </>);
  }

  /* ── right column: the build ────────────────────────────────────────── */

  function Side({ roles, role, setRole, entry, list, idx, setIdx, arch, x }) {
    return (
      <aside className="a-side">
        <h3 className="cp-h">Build</h3>
        <div className="cp-seg">{roles.map(r => (
          <button type="button" key={r.role} className={r.role === role ? 'on' : ''} onClick={() => setRole(r.role)}>{roleName(r.role)}
            {r.games != null ? <span>{` ${r.games.toLocaleString()} games, ${r.wr}%`}</span> : null}</button>))}</div>
        {!list.length ? <p className="cp-note">{`No archetype read for ${role || 'this champion'}${entry?.state && entry.state !== 'ok' ? ` (${entry.state})` : ''}.`}</p> : (
          <>
            <div className="cp-archs">{list.map((a, i) => (
              <button type="button" key={a.id} className={`cp-arch${i === idx ? ' on' : ''}`} data-arch={a.id} onClick={() => setIdx(i)}>
                <span className="cp-icons"><Ic o={x.rune(a.keystone)} k />{(a.core || []).map(id => <Ic o={x.item(id)} key={id} />)}</span>
                <span className="cp-name">{a.coreNames}</span>
                <span className="cp-num">{`${a.wr == null ? '?' : a.wr.toFixed(1)}% over ${a.games == null ? '?' : a.games.toLocaleString()} games, ${a.share == null ? '?' : pct(a.share)} of role`}</span>
              </button>))}</div>
            <Traits arch={arch} list={TR.filter(t => KEY.includes(t[0]))} />
            <h4>Then</h4>
            {(arch.path || []).length ? (
              <div className="cp-path">{arch.path.map((p, i) => (
                <span className="cp-step" key={i}>{p.items.slice((arch.core || []).length).map(id => <Ic o={x.item(id)} key={id} />)}
                  <span className="cp-name">{p.items.slice((arch.core || []).length).map(id => x.item(id)?.n || '?').join(', ')}</span>
                  <span className="cp-num">{`${p.wr == null ? '?' : p.wr.toFixed(1)}%, ${(p.games || 0).toLocaleString()}`}</span></span>))}</div>
            ) : <p className="cp-note">No third item reading.</p>}
            {(arch.full || []).length ? <>
              <h4>Full build</h4>
              <div className="cp-path">{arch.full.map((p, i) => (
                <span className="cp-step" key={i}><Ic o={x.item(p.items[p.items.length - 1])} />
                  <span className="cp-name">{x.item(p.items[p.items.length - 1])?.n || '?'}</span>
                  <span className="cp-num">{`item ${p.items.length}: ${p.wr == null ? '?' : p.wr.toFixed(1)}%, ${(p.games || 0).toLocaleString()}`}</span></span>))}</div>
            </> : null}
            <h4>Runes and boots</h4>
            <div className="cp-runes">
              {(arch.runes?.page || []).map((id, i) => <Ic o={x.rune(id)} k={i === 0} key={i} />)}
              {arch.boots?.id ? <><span className="cp-gap"></span><Ic o={x.item(arch.boots.id)} />
                <span className="cp-num">{`${num(arch.boots.pick, 0)}% of buyers`}</span></> : null}
            </div>
            {(arch.runes?.page || []).length ? <p className="cp-name cp-rnames">{arch.runes.page.map(id => x.rune(id)?.n || '?').join(' · ')}
              {arch.boots?.id ? `; ${x.item(arch.boots.id)?.n || '?'}` : ''}</p> : null}
            <h4>Skill order</h4>
            <Skills order={arch.skills?.order} />
            <p className="cp-note">
              {safeUrl(arch.url) ? <a href={arch.url} target="_blank" rel="noopener">lolalytics</a> : 'lolalytics'}
              {` · patch ${arch.patch || entry?.patch || '?'} · ${arch.coachless?.state === 'ok' ? 'coachless on file' : 'no coachless reading'}`}
              {arch.skills?.wr != null ? ` · skills ${arch.skills.source === 'op.gg' ? 'op.gg, R at 11' : 'lolalytics'} · ${arch.skills.wr.toFixed(1)}% · ${(arch.skills.n || 0).toLocaleString()} games · ${arch.skills.source === 'op.gg' ? 'role-wide' : 'keystone-wide'}` : ''}
            </p>
          </>)}
      </aside>);
  }

  function Skills({ order }) {
    if (!order) return <p className="cp-note">Skill order not read.</p>;
    const cells = [];
    for (const s of 'QWER') {
      cells.push(<span className="cp-sl" key={s}>{s}</span>);
      for (let i = 0; i < 18; i++) cells.push(order[i] === s ? <i className="on" key={s + i}>{i + 1}</i> : <i key={s + i}></i>);
    }
    return <div className="cp-skill">{cells}</div>;
  }

  /* Build styles (build_styles.py): what is possible on the champion, not only what is
     popular. Bold is a main style, plain a common one, dashed a niche build. */
  const Styles = ({ list }) => (list || []).length ? (
    <div className="styles">{list.map(s => (
      <span className={`style ${s.tier}`} key={s.style}
            title={`${s.tier}: ${s.score} of the first three items in its best role, bought early in ${(s.games || 0).toLocaleString()} games`}>{s.style}</span>))}</div>) : null;

  /* ── page ───────────────────────────────────────────────────────────── */

  function ChampionPage() {
    const [data, setData] = useState(null);
    const [sets, setSets] = useState([]);
    const [role, setRoleState] = useState(seg?.[2] ? decodeURIComponent(seg[2]) : '');
    const [idx, setIdxState] = useState(-1);  // -1: the URL's archetype, else the first
    // ?tab=build links straight to the build; a draft seat link (?arch=) lands there too
    const [tab, setTabState] = useState(TAB0 === 'build' || ARCH0 ? 'build' : 'read');
    const setTab = t => {
      setTabState(t);
      const q = new URLSearchParams(location.search);
      if (t === 'build') q.set('tab', 'build'); else q.delete('tab');
      history.replaceState(null, '', `${location.pathname}${q.size ? `?${q}` : ''}${location.hash}`);
    };
    const [building, setBuilding] = useState(false);
    const [buildNote, setBuildNote] = useState(null);
    const setsRef = useRef([]);
    const dlgRef = useRef(null);
    const openRef = useRef(null);

    useEffect(() => {
      document.getElementById('forge-root').setAttribute('data-react-mounted', 'forge-champion');
      const F = window.__FORGE;
      Promise.all([F.landing, F.sets, F.runes, F.champ, F.catalog]).then(([D, LIB, RUNEDEX, C, CAT]) => {
        const CHAMP = C?.name || asked;
        const mine = lib => (lib.sets || []).filter(s => (s.champion || '').toLowerCase() === CHAMP.toLowerCase());
        setsRef.current = mine(LIB);
        setSets(setsRef.current);
        const items = new Map((CAT.items || []).map(i => [String(i.id), i]));
        setData({
          D, RUNEDEX, mine, C, CHAMP,
          live: window.ForgeLib ? window.ForgeLib.shortPatch(D.catalogPatch) : D.catalogPatch,
          runeMeta: id => RUNEDEX.runes?.[String(id)] || null,
          x: {
            item: id => { const i = items.get(String(id)); return i ? { n: i.n, u: i.u } : null; },
            rune: id => { const r = RUNEDEX.runes?.[String(id)]; return r ? { n: r.name, u: r.icon } : null; },
          },
        });
      });
    }, []);

    useEffect(() => {
      if (!data) return undefined;
      const { RUNEDEX, mine } = data;
      const start = () => {
        const OV = window.ForgeUI.mountBuildOverlay({
          dialog: dlgRef.current, runedex: RUNEDEX, live: data.live,
          onChanged: () => fetch('api/sets').then(x => x.json()).catch(() => ({ sets: [] })).then(lib => {
            setsRef.current = mine(lib);
            setSets(setsRef.current);
          }),
        });
        openRef.current = id => OV.open(setsRef.current.find(x => x.id === id));
        window.ForgeLib.prefetchCatalog();
        if (WANTED && setsRef.current.some(x => x.id === WANTED)) openRef.current(WANTED);
      };
      if (window.ForgeLib) start();
      else window.addEventListener('forgelib:ready', start, { once: true });
      const dlg = dlgRef.current;
      const onClose = () => { if (location.hash) history.replaceState(null, '', location.pathname + location.search); };
      dlg.addEventListener('close', onClose);
      return () => dlg.removeEventListener('close', onClose);
    }, [data]);

    const C = data?.C?.name ? data.C : null;  // a 404 body is {error}, not a champion
    const CHAMP = data?.CHAMP || asked;
    const modes = C?.modes || {};
    const roles = [
      ...Object.entries(modes.ranked || {}).map(([r, e]) => ({ role: r, games: e.roleGames, wr: e.roleWr, e, mode: 'ranked' }))
        .sort((a, b) => (b.games || 0) - (a.games || 0)),
      ...Object.entries(modes.aram || {}).map(([r, e]) => ({ role: r, games: e.roleGames, wr: e.roleWr, e, mode: 'aram' })),
    ];
    const cur = roles.find(r => r.role === role) || roles[0] || null;
    const ROLE = cur?.role || '';
    const name = id => data?.x.item(id)?.n || String(id);
    const list = (cur?.e?.archetypes || []).map(a => ({ ...a, coreNames: (a.core || []).map(name).join(' + ') }));
    const at = idx >= 0 ? idx : Math.max(0, list.findIndex(a => String(a.id) === ARCH0));
    const arch = list[Math.min(at, list.length - 1)] || null;
    const page = C?.page;
    const calc = arch ? page?.calc?.value?.byArchetype?.[`${ROLE}/${arch.id}`] : null;
    const ver = (C?.versions?.page || '').split('-')[0] || data?.D?.catalogPatch || '';
    const ident = page?.identity?.value;

    const setRole = r => {
      setRoleState(r); setIdxState(0);
      history.replaceState(null, '', `c/${encodeURIComponent(CHAMP)}/${encodeURIComponent(r)}${tab === 'build' ? '?tab=build' : ''}${location.hash}`);
    };
    const setIdx = i => {
      setIdxState(i);
      const id = list[i]?.id;
      const q = new URLSearchParams(location.search);
      if (id) q.set('arch', id); else q.delete('arch');
      history.replaceState(null, '', `${location.pathname}${q.size ? `?${q}` : ''}${location.hash}`);
    };

    const autoLive = sets.some(s => s.auto && s.role === ROLE && s.patch === data?.live);
    const autobuild = () => {
      setBuilding(true); setBuildNote(null);
      fetch('api/autobuild', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ champion: CHAMP, role: ROLE }) })
        .then(r => r.json().catch(() => ({})).then(j => { if (!r.ok) throw new Error(j.error || `request failed (${r.status})`); return j; }))
        .then(j => {
          const miss = (j.outcomes || []).filter(o => o.state !== 'built').map(o => `${o.source === o.key ? o.source : `${o.source} ${o.key}`}: ${o.state}${o.why ? `, ${o.why}` : ''}`);
          if ((j.dropped || []).length) miss.push(`items dropped: ${j.dropped.join(', ')}`);
          setBuildNote(miss.length ? { b: 'Some pieces were not built.', t: miss.join('; ') } : null);
          return fetch('api/sets').then(x => x.json()).catch(() => ({ sets: [] })).then(lib => { setsRef.current = data.mine(lib); setSets(setsRef.current); });
        })
        .catch(e => setBuildNote({ b: 'Autobuild failed.', t: String(e.message || e) }))
        .then(() => setBuilding(false));
    };

    let who = null, newHref = 'edit', livePatch = '';
    if (data) {
      newHref = ROLE && cur.mode === 'ranked'
        ? `c/${encodeURIComponent(CHAMP)}/${encodeURIComponent(ROLE)}/build?new=1` : 'edit';
      if (data.D.catalogPatch) livePatch = `live ${data.D.catalogPatch}`;
      document.title = C ? `${CHAMP} · Item Set Forge` : 'Item Set Forge';
      who = (
        <React.Fragment>
          {safeUrl(C?.portrait) ? <img src={C.portrait} alt="" /> : <i></i>}
          <div>
            <h2>{C ? CHAMP : `No champion named ${asked}`}{ident?.title ? <span className="cp-title">{ident.title}</span> : null}</h2>
            <div className="roles">{roles.length ? roles.map(r => (
              <a className={`role${r.role === ROLE ? ' on' : ''}`} key={r.role}
                 href={`c/${encodeURIComponent(CHAMP)}/${encodeURIComponent(r.role)}`}
                 onClick={e => { e.preventDefault(); setRole(r.role); }}>{roleName(r.role)}
                {r.games != null ? <>{' '}<span className="n">{games(r.games)}</span></> : null}</a>
            )) : <span className="quiet">No archetypes are baked for this champion.</span>}</div>
            <Styles list={C?.styles} />
          </div>
        </React.Fragment>
      );
    }

    const tpl = (page?.abilities?.value || []).map(a => a.template).find(Boolean) || '';
    const wikiPage = (tpl.match(/^Template:Data (.+?)\//) || [])[1] || CHAMP;

    // saved sets list even when the champion lookup fails, so a set is never hidden
    const groups = data ? (
      <div id="groups" onClick={e => {
        const b = e.target.closest('[data-set]');
        if (b && openRef.current) openRef.current(b.dataset.set);
      }}><Groups sets={sets} live={data.live} champ={CHAMP} runeMeta={data.runeMeta} /></div>) : null;

    return (
      <React.Fragment>
        <ForgeUI.Bar current="champions" act={<a className="act go" id="new" href={newHref}>New set</a>}>
          <span className="meta" id="livePatch">{livePatch}</span>
          <span className="meta"></span>
        </ForgeUI.Bar>

        <div className="wrap">
          <div className="who" id="who">{who}</div>
          {data && C ? (
            <div className="cp-root">
              {!page ? <p className="none"><b>{`${CHAMP}'s page is not baked yet.`}</b>{' The build column still reads.'}</p> : null}
              <div className="cp-seg cp-tabs">{[['read', 'Read'], ['build', 'Build']].map(([k, t]) => (
                <button type="button" key={k} className={k === tab ? 'on' : ''} onClick={() => setTab(k)}>{t}</button>))}</div>
              <div className={`a-grid tab-${tab}`}>
                <div className="a-read">
                  <Identity name={CHAMP} i={ident} />
                  <Abilities page={page} calc={calc} ver={ver} />
                  <Play name={CHAMP} i={ident} quote={C.quote} ver={ver} spikes={C.spikes} />
                  <TraitsSection arch={arch} />
                  <Stats s={page?.stats?.value} resource={ident?.resource} places={C.statPlaces} />
                  <History h={page?.history?.value} limit={14} dates={C.patchDates} />
                  <Head id="sets" t="Saved sets">
                    {ROLE && cur.mode === 'ranked'
                      ? <span className="cp-seg"><button type="button" className="autobuild" disabled={building} onClick={autobuild}>
                          {building ? 'Building' : autoLive ? 'Rebuild auto sets' : 'Autobuild'}</button></span> : null}
                  </Head>
                  {buildNote ? <p className="none" role="status"><b>{buildNote.b}</b>{` ${buildNote.t}`}</p> : null}
                  {groups}
                </div>
                <Side roles={roles} role={ROLE} setRole={setRole} entry={cur?.e} list={list} idx={Math.min(at, Math.max(list.length - 1, 0))}
                  setIdx={setIdx} arch={arch} x={data.x} />
              </div>
              <footer className="cp-foot">
                <a href={`https://wiki.leagueoflegends.com/en-us/${encodeURIComponent(wikiPage.replace(/ /g, '_'))}`} target="_blank" rel="noopener">League of Legends Wiki</a>
                {` text reduced from the original, CC BY-SA 3.0. Riot's game text stays Riot's. Page ${C.versions?.page || 'not read'}, archetypes ${C.versions?.archetypes || 'not read'}, calculator ${C.versions?.calc || 'not read'}.`}
              </footer>
            </div>
          ) : groups}
        </div>

        <dialog id="ov" aria-label="Saved build" ref={dlgRef}></dialog>
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

  ReactDOM.createRoot(document.getElementById('forge-root')).render(<ErrorBoundary><ChampionPage /></ErrorBoundary>);
})();
