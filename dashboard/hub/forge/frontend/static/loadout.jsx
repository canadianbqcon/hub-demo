/* loadout.jsx - the Forge builder's plan page (step 3), as React.

   The authoring half of loadout.js: summoner spells, the ability-level grid, jungle
   pathing and bans. loadout.js stays the logic module (plan shape, normalisePlan,
   planPayload, maxOrder, the spell and camp tables, and planHTML for the read-only
   overlay) and reaches this file through window.ForgeLib; the plain mountPlan() it still
   exports is the pre-React page, kept until cleanup. Save bodies are not built here:
   the plan lives on st.S.plan and goes out through planPayload() in forge-blocks.jsx, so
   the request is the module's own.

   Component: ForgeUI.Plan() renders the whole #step3 section (hidden off the plan step).
   A mutation is st.emit() (repaint) plus st.persist() (localStorage and autosave), the
   same pair every other mutation on the page ends in. Bans are kept apart from the set:
   they save straight away to api/bans/<champion> and never ride the set's autosave. */
window.ForgeUI = window.ForgeUI || {};

(() => {
  const { useState, useEffect, useRef } = React;
  const UI = window.ForgeUI;
  const st = UI.state;
  const lib = () => window.ForgeLib;
  const M = st.M;

  /* Riot's cap on a basic ability: five points, and R is bounded by its own levels. */
  const MAX_BASIC = 5;

  /* The two-cell reading a row carries: the figure and the sample it was measured on,
     in the same tracks and the same order the rune picker uses. */
  function Lane({ val, cls, n }) {
    return val != null
      ? <React.Fragment><span className={`wpa ${cls}`}>{val}</span><span className="rgames">{n}</span></React.Fragment>
      : <React.Fragment><span className="wpa thin">{'\u2014'}</span><span className="rgames"></span></React.Fragment>;
  }

  const Sep = () => <i>{'›'}</i>;
  const joined = (list, sep) => list.reduce((acc, x, i) => (i ? acc.concat([sep(i), x]) : [x]), []);

  function Plan() {
    st.useStore();
    const [bans, setBans] = useState([]);
    const [msg, setMsg] = useState('');
    const bansRef = useRef([]);
    const sayT = useRef(null);
    const banIn = useRef(null);
    const ready = st.loaded && !!st.S;
    const champ = ready ? M.champ : '';

    /* The champion is set on the Items step, so it can change under this page: the bans
       follow it. Nothing is fetched for a set with no champion. */
    useEffect(() => {
      let live = true;
      bansRef.current = [];
      setBans([]);
      if (!champ) return undefined;
      fetch(`api/bans/${encodeURIComponent(champ)}`)
        .then(r => r.json()).then(j => j.champions || []).catch(() => [])
        .then(list => { if (live) { bansRef.current = list; setBans(list); } });
      return () => { live = false; };
    }, [champ]);

    /* The ban box commits on the native `change` event (a pick out of the datalist, or
       a full name and a tab), not on every keystroke, so it is wired by hand rather than
       through React's onChange. */
    useEffect(() => {
      const el = banIn.current;
      if (!el) return undefined;
      const on = () => {
        const c = st.CHAMPS.find(x => x.n.toLowerCase() === el.value.trim().toLowerCase());
        el.value = '';
        if (!c || bansRef.current.includes(c.k)) return;
        setList(bansRef.current.concat([c.k]));
      };
      el.addEventListener('change', on);
      return () => el.removeEventListener('change', on);
    }, [ready]);
    if (!ready) return <section className="planpage" id="step3" hidden></section>;

    const plan = st.S.plan;
    const jungle = String(M.role || '').toLowerCase() === 'jungle';
    const cl = st.STATS.champions[M.champ]?.roles?.[M.role] || null;
    const lo = st.lola();

    function say(m) {
      setMsg(m);
      clearTimeout(sayT.current);
      sayT.current = setTimeout(() => setMsg(''), 4000);
    }
    const changed = () => { st.emit(); st.persist(); };

    /* Bans save on their own, straight away, and never ride the set's autosave: they
       are not on the set, and a build you never saved should still be able to record
       that Kayle is unplayable into this champion. */
    function setList(list) {
      bansRef.current = list;
      setBans(list);
      if (!M.champ) return;
      fetch(`api/bans/${encodeURIComponent(M.champ)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ champions: list }),
      }).catch(() => say('Could not reach the ban list.'));
    }

    /* Two slots, and the third click has to mean something rather than nothing. It
       drops the OLDER of the two, which is almost always the one you were replacing:
       the pair is kept in pick order for exactly that reason. */
    function toggleSpell(id) {
      const at = plan.spells.indexOf(id);
      if (at >= 0) plan.spells.splice(at, 1);
      else {
        if (plan.spells.length >= 2) plan.spells.shift();
        plan.spells.push(id);
      }
      changed();
    }

    function setSkill(ability, level) {
      const i = level - 1;
      if (plan.skills[i] === ability) { plan.skills[i] = ''; return changed(); }
      if (!lib().legalAt(ability, level)) return;
      // The cap is the one rule the grid cannot show, so it has to say it out loud
      // rather than swallowing the click and looking broken.
      if (ability !== 'R' && plan.skills.filter(a => a === ability).length >= MAX_BASIC)
        return say(`${ability} is already at ${MAX_BASIC} points. Clear one first.`);
      plan.skills[i] = ability;
      changed();
    }

    function spellNote(id) {
      const s = lib().SPELLS.find(x => x.id === id);
      return st.askNote({
        title: `Note: ${s.n}`,
        why: 'When would you bring this, and why? One sentence.',
        value: plan.spellNotes[String(id)] || '',
      }).then(note => {
        if (note === null) return;
        if (note) plan.spellNotes[String(id)] = note;
        else delete plan.spellNotes[String(id)];
        changed();
      });
    }

    function pathNote(n) {
      const p = plan.paths[n];
      return st.askNote({
        title: `Note: ${p.name || 'this path'}`,
        why: 'When would you take this path, and why? One sentence.',
        value: p.note,
      }).then(note => {
        if (note === null) return;
        p.note = note;
        changed();
      });
    }

    /* ── spells ── */
    const by = new Map((cl?.spells || []).map(r => [r.id, r]));
    const pair = lo?.plan?.spells;
    const pairNames = pair?.ids.map(id => lib().SPELLS.find(s => s.id === id)?.n).filter(Boolean);

    /* ── skills ── */
    const order = lib().maxOrder(plan.skills);
    const skillRows = ['Q', 'W', 'E', 'R'];
    const lv = lo?.plan?.levels, pr = lo?.plan?.priority;
    const figRow = (k, body, wr, n) => (
      <div className="r" key={k}><span className="k">{k}</span><span><b>{body}</b>
        {' · '}<b className={st.wrClass(wr, n)}>{st.fmtWr(wr)}</b>{' win · '}{st.games(n)}{' games'}</span></div>
    );
    const figRows = [];
    if (lo?.plan) {
      if (lv) figRows.push(figRow('order', lib().ABILITIES.filter(a => lv.levels[a]?.length)
        .map(a => `${a} ${lv.levels[a].join('·')}`).join('   '), lv.wr, lv.n));
      if (pr) figRows.push(figRow('priority', pr.order.join(' > '), pr.wr, pr.n));
    }

    /* ── bans ── */
    const byKey = new Map(st.CHAMPS.map(c => [c.k, c]));
    const byName = new Map(st.CHAMPS.map(c => [c.n.toLowerCase(), c]));
    /* The list a ban is actually chosen from: the champions this one loses to,
       worst first, with the win rate that says so. coachless has no matchup data
       at all, so this figure has one source and the header says which. */
    const sug = (lo?.counters || []).map(r => ({ r, c: byName.get(r.n.toLowerCase()) })).filter(x => x.c);

    const onClick = e => {
      const t = e.target;
      const hit = sel => t.closest(`[${sel}]`)?.getAttribute(sel);

      const spell = hit('data-spell');
      if (spell) return toggleSpell(+spell);
      const sn = hit('data-spellnote');
      if (sn) return spellNote(+sn);
      const sk = t.closest('[data-sk]');
      if (sk) return setSkill(sk.dataset.sk, +sk.dataset.lv);
      if (t.closest('#planSkillClear')) { plan.skills = Array(18).fill(''); return changed(); }
      if (t.closest('#planPathAdd')) { plan.paths.push({ name: '', camps: [], note: '' }); return changed(); }
      const add = hit('data-pathadd');
      if (add) {
        const [n, camp] = add.split(':');
        plan.paths[+n].camps.push(camp);
        return changed();
      }
      const pop = hit('data-pathpop');
      if (pop) {
        const [n, at] = pop.split(':').map(Number);
        plan.paths[n].camps.splice(at, 1);
        return changed();
      }
      const drop = hit('data-pathdrop');
      if (drop) { plan.paths.splice(+drop, 1); return changed(); }
      const pn = hit('data-pathnote');
      if (pn) return pathNote(+pn);
      const off = hit('data-banoff');
      if (off) return setList(bansRef.current.filter(k => k !== +off));
      const bs = hit('data-bansug');
      if (bs) {
        const k = +bs, cur = bansRef.current;
        return setList(cur.includes(k) ? cur.filter(x => x !== k) : cur.concat([k]));
      }
    };

    return (
      <section className="planpage" id="step3" hidden={st.step !== 'plan'} onClick={onClick}>
        {/* Two columns, and the split is what each half IS rather than a way to fill
            space: the left is what you PICK - two spells and a ban list, short rows
            that carry a figure each - and the right is what you SEQUENCE, an
            18-column grid and a route, which are the only two things here that need
            the width. */}
        <div className="meta-head">
          <h2>Plan</h2>
          <span className="sub" id="planSub" aria-live="polite">{msg}</span>
        </div>

        <div className="pl-col pl-col-pick">
          <section className="pl-card">
            <h3>Summoner spells</h3>
            <p className="pl-why">Two. A note says when you would bring a third one instead.</p>
            <div className="srcbar" id="planSpellSrc" hidden={!by.size}>
              <span className="a">coachless</span><span className="u1">wpa</span><span className="u2">n</span>
            </div>
            <div className="pl-pick" id="planSpells">{lib().SPELLS.map(s => {
              const on = plan.spells.includes(s.id);
              const note = plan.spellNotes[String(s.id)];
              const r = by.get(s.id);
              return (
                <span className={`pl-opt${on ? ' on' : ''}${note ? ' noted' : ''}`} key={s.id}>
                  <button type="button" data-spell={s.id} aria-pressed={String(on)} title={s.n}>
                    <img src={lib().spellIcon(s, st.BAKED.ver)} alt="" width="32" height="32" loading="lazy" />
                    <span className="nm">{s.n}</span>
                    {r ? <Lane val={st.fmtWpa(r.wpa)} cls={st.wpaClass(r.wpa, r.n)} n={st.games(r.n)} /> : <Lane />}
                  </button>
                  <button type="button" className="pl-notebtn" data-spellnote={s.id} aria-label={`Note for ${s.n}`}
                          title={note ? note : 'When would you take this?'}>{'≡'}</button>
                </span>
              );
            })}</div>
            {/* lolalytics publishes the single top PAIR and nothing per spell, so it is
                printed once under the list. Put it in a per-row lane and it reads as a
                figure for that spell, which is not what it measures. */}
            <p className="pl-pair" id="planSpellPair">{pairNames && pairNames.length === 2 ? (
              <React.Fragment>
                <span className="k">lolalytics</span>
                <span>{'most-played pair is '}<b>{pairNames.join(' + ')}</b>{' at '}
                  <b className={st.wrClass(pair.wr, pair.n)}>{st.fmtWr(pair.wr)}</b>{' win over '}
                  {st.games(pair.n)}{' games'}</span>
              </React.Fragment>
            ) : null}</p>
          </section>

          <section className="pl-card">
            <h3>Bans</h3>
            <p className="pl-why" id="planBanWhy">{champ
              ? `Kept against ${champ}, not against this build. Every ${champ} set reads the same list.`
              : 'Name the champion on the Items step first. A ban belongs to a champion, not to a set.'}</p>
            <input id="planBanIn" list="planBanList" placeholder="Ban a champion" autoComplete="off"
                   disabled={!champ} ref={banIn} />
            <datalist id="planBanList">{st.CHAMPS.map(c => <option value={c.n} key={c.k} />)}</datalist>
            <div className="chips" id="planBans">{bans.map(k => {
              const c = byKey.get(k);
              return c ? (
                <button type="button" className="chip" data-banoff={k} title={`Remove ${c.n}`} key={k}>
                  <img src={c.u} alt="" /> {c.n}</button>
              ) : null;
            })}</div>
            <div id="planBanSugWrap" hidden={!sug.length}>
              <span className="pl-lab">Worst matchups</span>
              <div className="srcbar">
                <span className="a">lolalytics</span><span className="u1">win</span><span className="u2">n</span>
              </div>
              <div className="pl-pick" id="planBanSug">{sug.map(({ r, c }) => {
                const on = bans.includes(c.k);
                return (
                  <span className={`pl-opt solo${on ? ' on' : ''}`} key={c.k}>
                    <button type="button" data-bansug={c.k} aria-pressed={String(on)}
                            title={on ? 'Already banned' : `Ban ${c.n}`}>
                      <img src={c.u} alt="" width="32" height="32" loading="lazy" />
                      <span className="nm">{c.n}</span>
                      <Lane val={st.fmtWr(r.wr)} cls={st.wrClass(r.wr, r.g)} n={st.games(r.g)} />
                    </button></span>
                );
              })}</div>
            </div>
          </section>
        </div>

        <div className="pl-col pl-col-seq">
          <section className="pl-card pl-lead">
            <h3>Ability levels</h3>
            <p className="pl-why">One ability per level. The max order underneath is read off the
              grid, so it can never disagree with it.</p>
            <div id="planSkillWrap">
              <div className="pl-skills">
                <div className="pl-sk-lv"></div>
                {plan.skills.map((_, i) => (
                  <div className={`pl-sk-lv${lib().ULT_LEVELS.includes(i + 1) ? ' ult' : ''}`} key={i}>{i + 1}</div>
                ))}
                {skillRows.map(a => (
                  <React.Fragment key={a}>
                    <div className="pl-sk-key">{a}</div>
                    {plan.skills.map((got, i) => {
                      const l = i + 1, on = got === a, legal = lib().legalAt(a, l);
                      // The three ultimate columns are marked on every row, not just on
                      // the R one: the levelling rule is a COLUMN, and drawing it as three
                      // holes in Q/W/E and three floating boxes in R reads as broken.
                      return (
                        <button type="button" className={`pl-sk${on ? ' on' : ''}${legal ? '' : ' off'}`} key={l}
                                data-ult={lib().ULT_LEVELS.includes(l) ? '' : undefined}
                                data-sk={a} data-lv={l} disabled={!legal} aria-pressed={String(on)}
                                aria-label={`${a} at level ${l}`}>{on ? a : ''}</button>
                      );
                    })}
                  </React.Fragment>
                ))}
              </div>
              <p className="pl-order">{order.length
                ? <React.Fragment>{'max order '}<b>{order.join(' > ')}</b></React.Fragment>
                : 'max order reads off the grid once points are placed'}</p>
            </div>
            {/* lolalytics' own levelling, printed as prose under the grid rather than as a
                second grid beside it. Two readings, measured differently on purpose: the
                priority is the whole game, the order is measured at level 15, which is why
                R comes back as 6 and 11 with no 16. */}
            <div id="planSkillFig">{figRows.length ? (
              <React.Fragment>
                <p className="pl-lab">lolalytics</p><div className="pl-lola-sk">{figRows}</div>
              </React.Fragment>
            ) : null}</div>
            <div className="pl-actions"><button type="button" id="planSkillClear">Clear the order</button></div>
          </section>

          <section className="pl-card" id="planPathCard" hidden={!jungle}>
            <h3>Jungle pathing</h3>
            <p className="pl-why">Click camps in the order you take them. A path with no note is a
              route with no reason, so every one of them gets the trigger it answers.
              Neither coachless nor lolalytics publishes a figure for a jungle route, so
              this is the one card on the page with nothing to read it against.</p>
            <div id="planPaths">{plan.paths.length ? plan.paths.map((p, n) => (
              <div className="pl-edit" key={n}>
                <div className="pl-edit-head">
                  {/* a path name is a text field, so it writes on input */}
                  <input className="pl-nm" data-pathname={n} value={p.name} placeholder="Name this path"
                         autoComplete="off" onChange={e => { p.name = e.target.value; changed(); }} />
                  <button type="button" className="pl-notebtn" data-pathnote={n}
                          title={p.note ? p.note : 'When would you take this path?'}>{'≡'}</button>
                  <button type="button" className="del" data-pathdrop={n} aria-label="Delete this path">Delete</button>
                </div>
                <span className="pl-lab">Route</span>
                <div className="pl-route built">{p.camps.length ? joined(p.camps.map((c, at) => {
                  const camp = lib().CAMPS.find(x => x.id === c);
                  return (
                    <button type="button" className="pl-camp" data-g={camp.g} data-pathpop={`${n}:${at}`}
                            title={`Remove ${camp.n}`} key={at}>{camp.n}</button>
                  );
                }), i => <Sep key={`s${i}`} />) : <span className="pl-empty">No camps yet.</span>}</div>
                {p.note ? <p className="pl-note">{p.note}</p> : null}
                <div className="pl-pool-wrap">
                  <span className="pl-lab">Add a step</span>
                  <div className="pl-pool">{lib().CAMPS.map(c => (
                    <button type="button" className="pl-camp add" data-g={c.g} data-pathadd={`${n}:${c.id}`} key={c.id}>{c.n}</button>
                  ))}</div>
                </div>
              </div>
            )) : <p className="pl-empty">No paths yet.</p>}</div>
            <div className="pl-actions"><button type="button" id="planPathAdd">Add a path</button></div>
          </section>
        </div>
      </section>
    );
  }

  UI.Plan = Plan;
})();
