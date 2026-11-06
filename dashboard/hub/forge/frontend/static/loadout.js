/* The plan page: what you bring, how you level, where you walk, and what you ban.
 *
 * Three of those four are set-scoped and ride along inside the saved set as one
 * `plan` object. The fourth does not. A ban answers "who beats this champion",
 * which has nothing to do with which items you bought, so bans are keyed by
 * CHAMPION and live in their own store. Two Viego builds share one ban list, and
 * forking a set forward to a new patch does not fork the bans with it.
 *
 * Everything here is authored and displayed, never exported. The client imports
 * item sets and nothing else, so a summoner pair, a skill order and a jungle path
 * are all read off the saved build and typed in by hand, exactly like the rune
 * page above them.
 *
 * Both surfaces come out of this file: the builder mounts `mountPlan()` and the
 * saved-build overlay renders `planHTML()`. One shape read in two places is one
 * shape; two renderers typed in two files is two shapes a week later.
 */

const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;' }[c]));

/* The nine Summoner spells legal on Summoner's Rift, in the order you actually
 * reach for them rather than by id. Hardcoded on purpose: the list has not moved
 * in years, and the alternative is a tenth network round trip on a page that is
 * being tuned for weight. Image names verified against
 * ddragon /data/en_US/summoner.json, filtered to mode CLASSIC. */
export const SPELLS = [
  { id: 4,  n: 'Flash',    img: 'SummonerFlash' },
  { id: 11, n: 'Smite',    img: 'SummonerSmite' },
  { id: 14, n: 'Ignite',   img: 'SummonerDot' },
  { id: 12, n: 'Teleport', img: 'SummonerTeleport' },
  { id: 6,  n: 'Ghost',    img: 'SummonerHaste' },
  { id: 7,  n: 'Heal',     img: 'SummonerHeal' },
  { id: 21, n: 'Barrier',  img: 'SummonerBarrier' },
  { id: 3,  n: 'Exhaust',  img: 'SummonerExhaust' },
  { id: 1,  n: 'Cleanse',  img: 'SummonerBoost' },
];
const SPELL_BY_ID = new Map(SPELLS.map(s => [s.id, s]));
export const spellIcon = (s, ver) =>
  `https://ddragon.leagueoflegends.com/cdn/${ver}/img/spell/${s.img}.png`;

/* A path step is a camp, an objective, or a thing you do. Ganks and recalls are in
 * the list because a route that cannot say "back here" or "gank bot at 3:20" is a
 * clear order, not a path, and the clear order is the boring half. */
export const CAMPS = [
  { id: 'blue',        n: 'Blue',         g: 'camp' },
  { id: 'gromp',       n: 'Gromp',        g: 'camp' },
  { id: 'wolves',      n: 'Wolves',       g: 'camp' },
  { id: 'raptors',     n: 'Raptors',      g: 'camp' },
  { id: 'red',         n: 'Red',          g: 'camp' },
  { id: 'krugs',       n: 'Krugs',        g: 'camp' },
  { id: 'scuttle-top', n: 'Scuttle (top)', g: 'neutral' },
  { id: 'scuttle-bot', n: 'Scuttle (bot)', g: 'neutral' },
  { id: 'grubs',       n: 'Grubs',        g: 'objective' },
  { id: 'herald',      n: 'Herald',       g: 'objective' },
  { id: 'dragon',      n: 'Dragon',       g: 'objective' },
  { id: 'baron',       n: 'Baron',        g: 'objective' },
  { id: 'invade',      n: 'Invade',       g: 'action' },
  { id: 'gank-top',    n: 'Gank top',     g: 'action' },
  { id: 'gank-mid',    n: 'Gank mid',     g: 'action' },
  { id: 'gank-bot',    n: 'Gank bot',     g: 'action' },
  { id: 'recall',      n: 'Recall',       g: 'action' },
];
const CAMP_BY_ID = new Map(CAMPS.map(c => [c.id, c]));

export const ABILITIES = ['Q', 'W', 'E', 'R'];
/* Riot's own rule, and the only one worth enforcing in the grid: the ultimate is
 * legal at 6, 11 and 16 and nowhere else, and those three levels take nothing but
 * the ultimate. Everything else follows from it, including the 3-point cap on R. */
export const ULT_LEVELS = [6, 11, 16];
const MAX_BASIC = 5;

export const blankPlan = () => ({
  spells: [], spellNotes: {}, skills: Array(18).fill(''), paths: [],
});

/* An old set has no `plan` at all and a hand-edited one can have half of it, so
 * every read goes through here rather than trusting the shape on the way in. */
export function normalisePlan(p) {
  const out = blankPlan();
  if (!p || typeof p !== 'object') return out;
  out.spells = (Array.isArray(p.spells) ? p.spells : [])
    .map(Number).filter(id => SPELL_BY_ID.has(id)).slice(0, 2);
  if (p.spellNotes && typeof p.spellNotes === 'object')
    for (const [k, v] of Object.entries(p.spellNotes))
      if (SPELL_BY_ID.has(Number(k)) && typeof v === 'string' && v.trim())
        out.spellNotes[String(Number(k))] = v.trim();
  const sk = Array.isArray(p.skills) ? p.skills : [];
  for (let i = 0; i < 18; i++) {
    const a = String(sk[i] || '').toUpperCase();
    if (ABILITIES.includes(a) && legalAt(a, i + 1)) out.skills[i] = a;
  }
  out.paths = (Array.isArray(p.paths) ? p.paths : []).map(x => ({
    name: String(x?.name || '').trim(),
    camps: (Array.isArray(x?.camps) ? x.camps : []).filter(c => CAMP_BY_ID.has(c)),
    note: String(x?.note || '').trim(),
  })).filter(x => x.name || x.camps.length);
  return out;
}

export const legalAt = (ability, level) =>
  ULT_LEVELS.includes(level) ? ability === 'R' : ability !== 'R';

/* Everything a set carries has to survive a round trip, and an all-empty plan is
 * not worth a key on the row. Null means "this build has no plan yet". */
export function planPayload(plan) {
  const p = normalisePlan(plan);
  const any = p.spells.length || Object.keys(p.spellNotes).length
    || p.skills.some(Boolean) || p.paths.length;
  return any ? p : null;
}

/* The max order is READ OFF the grid, never typed, so the two can never disagree.
 * An ability is ranked by the level its fifth point lands on, which is the whole
 * meaning of "max this first". A half-levelled build has no fifth point yet, so it
 * falls back to how many points it has and then to where it started, which is the
 * order you would read off the grid yourself. */
export function maxOrder(skills) {
  const stat = { Q: null, W: null, E: null };
  for (const a of Object.keys(stat)) stat[a] = { n: 0, first: 99, done: 99 };
  (skills || []).forEach((a, i) => {
    const s = stat[a];
    if (!s) return;
    s.n++;
    if (i + 1 < s.first) s.first = i + 1;
    if (s.n === MAX_BASIC) s.done = i + 1;
  });
  return Object.keys(stat).filter(a => stat[a].n).sort((x, y) =>
    stat[x].done - stat[y].done || stat[y].n - stat[x].n || stat[x].first - stat[y].first);
}

/* ── read-only rendering, shared with the saved-build overlay ─────────────── */

function spellRowHTML(plan, ver) {
  if (!plan.spells.length) return '';
  return `<div class="pl-spells">${plan.spells.map(id => {
    const s = SPELL_BY_ID.get(id);
    const note = plan.spellNotes[String(id)];
    return `<span class="pl-spell${note ? ' noted' : ''}"${note ? ` title="${esc(note)}"` : ''}>
      <img src="${esc(spellIcon(s, ver))}" alt="" width="28" height="28" loading="lazy">
      ${esc(s.n)}</span>`;
  }).join('')}</div>`;
}

function skillGridHTML(plan, { editable = false } = {}) {
  if (!editable && !plan.skills.some(Boolean)) return '';
  const order = maxOrder(plan.skills);
  const head = `<div class="pl-sk-lv"></div>${plan.skills.map((_, i) =>
    `<div class="pl-sk-lv${ULT_LEVELS.includes(i + 1) ? ' ult' : ''}">${i + 1}</div>`).join('')}`;
  const rows = ABILITIES.map(a => `<div class="pl-sk-key">${a}</div>${plan.skills.map((got, i) => {
    const lv = i + 1, on = got === a, legal = legalAt(a, lv);
    // The three ultimate columns are marked on every row, not just on the R
    // one: the levelling rule is a COLUMN, and drawing it as three holes in
    // Q/W/E and three floating boxes in R reads as broken alignment instead.
    const cell = `class="pl-sk${on ? ' on' : ''}${legal ? '' : ' off'}"`
      + (ULT_LEVELS.includes(lv) ? ' data-ult' : '');
    return editable
      ? `<button ${cell} data-sk="${a}" data-lv="${lv}"${legal ? '' : ' disabled'}
           aria-pressed="${on}" aria-label="${a} at level ${lv}">${on ? a : ''}</button>`
      : `<div ${cell}>${on ? a : ''}</div>`;
  }).join('')}`).join('');
  return `<div class="pl-skills">${head}${rows}</div>
    <p class="pl-order">${order.length
      ? `max order <b>${order.join(' &gt; ')}</b>`
      : 'max order reads off the grid once points are placed'}</p>`;
}

function pathsHTML(plan) {
  if (!plan.paths.length) return '';
  return `<ul class="pl-paths">${plan.paths.map(p => `<li>
    <span class="pl-path-nm">${esc(p.name || 'Unnamed path')}</span>
    <span class="pl-route">${p.camps.map(c => {
      const camp = CAMP_BY_ID.get(c);
      return `<span class="pl-camp" data-g="${camp.g}">${esc(camp.n)}</span>`;
    }).join('<i>›</i>')}</span>
    ${p.note ? `<span class="pl-note">${esc(p.note)}</span>` : ''}
  </li>`).join('')}</ul>`;
}

export function bansHTML(bans, byKey) {
  if (!bans?.length) return '';
  return `<div class="pl-bans">${bans.map(k => {
    const c = byKey.get(k) || byKey.get(String(k));
    return c ? `<span class="pl-ban"><img src="${esc(c.u)}" alt="" width="24" height="24"
      loading="lazy"> ${esc(c.n)}</span>` : '';
  }).join('')}</div>`;
}

/* The whole plan, read-only. `bans` is passed in rather than fetched here: the
 * overlay already knows the champion and one fetch per open is one too many. */
export function planHTML(rawPlan, { ver, role, bans, byKey } = {}) {
  const plan = normalisePlan(rawPlan);
  const jungle = String(role || '').toLowerCase() === 'jungle';
  const parts = [
    ['Summoner spells', spellRowHTML(plan, ver)],
    ['Ability levels', skillGridHTML(plan)],
    // A path on a mid set is noise, and the ONLY thing that makes it noise is the
    // role, so the role is what gates it rather than whether one happens to exist.
    ...(jungle ? [['Jungle pathing', pathsHTML(plan)]] : []),
    ['Bans', bansHTML(bans, byKey || new Map())],
  ].filter(([, html]) => html);
  if (!parts.length) return '';
  return parts.map(([h, html]) => `<h4 class="pl-h">${h}</h4>${html}`).join('');
}

/* ── the builder page ─────────────────────────────────────────────────────── */

/* Mount the authoring page. Returns { render }.
 *
 *   root       - the <section> to fill
 *   champs     - the catalog's champion list, for the ban picker
 *   ver        - the live Data Dragon version, for spell icons
 *   askNote    - the page's own note dialog, so this file ships no second one
 *   getPlan    - () => the live plan object off the builder's state
 *   getRole    - () => the set's role, which is what shows or hides pathing
 *   getChampion- () => the set's champion name, which is what bans are keyed by
 *   onChange   - called after every mutation, so the builder persists and autosaves
 *   getFigures - () => ({ cl, lo }) - the coachless and lolalytics nodes for the
 *                CURRENT champion/role, straight off the two bakes forge.html
 *                already holds. Optional: without it the page renders exactly as
 *                it did before, which is what the read-only overlay wants.
 *   fig        - the page's own figure formatters, passed rather than copied.
 *                A second fmtWpa in a second file is a second answer to "is
 *                +0.5 good" the first week one of them changes.
 */
export function mountPlan({ root, champs, ver, askNote, getPlan, getRole, getChampion,
                            onChange, getFigures, fig }) {
  const byKey = new Map(champs.map(c => [c.k, c]));
  const byName = new Map(champs.map(c => [c.n.toLowerCase(), c]));
  let BANS = [];          // champion keys, for the CURRENT champion
  let banChamp = null;    // the champion those bans belong to
  const $ = id => root.querySelector(`#${id}`);

  /* Two columns, and the split is what each half IS rather than a way to fill
     space: the left is what you PICK - two spells and a ban list, short rows
     that carry a figure each - and the right is what you SEQUENCE, an
     18-column grid and a route, which are the only two things here that need
     the width. Four full-bleed cards holding content that stopped at 40% of
     them is what this replaces. */
  root.innerHTML = `
    <div class="meta-head">
      <h2>Plan</h2>
      <span class="sub" id="planSub" aria-live="polite"></span>
    </div>

    <div class="pl-col pl-col-pick">
      <section class="pl-card">
        <h3>Summoner spells</h3>
        <p class="pl-why">Two. A note says when you would bring a third one instead.</p>
        <div class="srcbar" id="planSpellSrc" hidden>
          <span class="a">coachless</span><span class="u1">wpa</span><span class="u2">n</span>
        </div>
        <div class="pl-pick" id="planSpells"></div>
        <p class="pl-pair" id="planSpellPair"></p>
      </section>

      <section class="pl-card">
        <h3>Bans</h3>
        <p class="pl-why" id="planBanWhy"></p>
        <input id="planBanIn" list="planBanList" placeholder="Ban a champion" autocomplete="off">
        <datalist id="planBanList"></datalist>
        <div class="chips" id="planBans"></div>
        <div id="planBanSugWrap" hidden>
          <span class="pl-lab">Worst matchups</span>
          <div class="srcbar">
            <span class="a">lolalytics</span><span class="u1">win</span><span class="u2">n</span>
          </div>
          <div class="pl-pick" id="planBanSug"></div>
        </div>
      </section>
    </div>

    <div class="pl-col pl-col-seq">
      <section class="pl-card pl-lead">
        <h3>Ability levels</h3>
        <p class="pl-why">One ability per level. The max order underneath is read off the
          grid, so it can never disagree with it.</p>
        <div id="planSkillWrap"></div>
        <div id="planSkillFig"></div>
        <div class="pl-actions"><button id="planSkillClear">Clear the order</button></div>
      </section>

      <section class="pl-card" id="planPathCard">
        <h3>Jungle pathing</h3>
        <p class="pl-why">Click camps in the order you take them. A path with no note is a
          route with no reason, so every one of them gets the trigger it answers.
          Neither coachless nor lolalytics publishes a figure for a jungle route, so
          this is the one card on the page with nothing to read it against.</p>
        <div id="planPaths"></div>
        <div class="pl-actions"><button id="planPathAdd">Add a path</button></div>
      </section>
    </div>`;

  $('planBanList').innerHTML = champs.map(c => `<option value="${esc(c.n)}">`).join('');

  /* The figures. Everything below degrades to nothing when the page did not
     pass them through, so the same file still mounts on a surface that has no
     bakes behind it. `lane` is the two-cell reading a row carries: the figure
     and the sample it was measured on, in the same tracks and the same order
     the rune picker uses. */
  const figs = () => (getFigures?.()) || {};
  const lane = (val, cls, n) => fig && val != null
    ? `<span class="wpa ${cls}">${val}</span><span class="rgames">${n}</span>`
    : '<span class="wpa thin">\u2014</span><span class="rgames"></span>';

  /* ── spells ── */
  function renderSpells() {
    const plan = getPlan();
    const { cl, lo } = figs();
    const by = new Map((cl?.spells || []).map(r => [r.id, r]));
    $('planSpellSrc').hidden = !by.size;

    $('planSpells').innerHTML = SPELLS.map(s => {
      const on = plan.spells.includes(s.id);
      const note = plan.spellNotes[String(s.id)];
      const r = by.get(s.id);
      return `<span class="pl-opt${on ? ' on' : ''}${note ? ' noted' : ''}">
        <button data-spell="${s.id}" aria-pressed="${on}" title="${esc(s.n)}">
          <img src="${esc(spellIcon(s, ver))}" alt="" width="32" height="32" loading="lazy">
          <span class="nm">${esc(s.n)}</span>
          ${r ? lane(fig.fmtWpa(r.wpa), fig.wpaClass(r.wpa, r.n), fig.games(r.n)) : lane()}
        </button>
        <button class="pl-notebtn" data-spellnote="${s.id}"
          aria-label="Note for ${esc(s.n)}" title="${note ? esc(note) : 'When would you take this?'}"
          >≡</button>
      </span>`;
    }).join('');

    /* lolalytics publishes the single top PAIR and nothing per spell, so it is
       printed once under the list. Put it in a per-row lane and it reads as a
       figure for that spell, which is not what it measures. */
    const pair = lo?.plan?.spells;
    const names = pair?.ids.map(id => SPELL_BY_ID.get(id)?.n).filter(Boolean);
    $('planSpellPair').innerHTML = names && names.length === 2 && fig
      ? `<span class="k">lolalytics</span><span>most-played pair is
         <b>${esc(names.join(' + '))}</b> at
         <b class="${fig.wrClass(pair.wr, pair.n)}">${fig.fmtWr(pair.wr)}</b> win over
         ${fig.games(pair.n)} games</span>`
      : '';
  }

  /* Two slots, and the third click has to mean something rather than nothing. It
   * drops the OLDER of the two, which is almost always the one you were replacing:
   * the pair is kept in pick order for exactly that reason. */
  function toggleSpell(id) {
    const plan = getPlan();
    const at = plan.spells.indexOf(id);
    if (at >= 0) plan.spells.splice(at, 1);
    else {
      if (plan.spells.length >= 2) plan.spells.shift();
      plan.spells.push(id);
    }
    changed();
  }

  /* ── skills ── */
  function renderSkills() {
    $('planSkillWrap').innerHTML = skillGridHTML(getPlan(), { editable: true });
    $('planSkillFig').innerHTML = skillFigHTML();
  }

  /* lolalytics' own levelling, printed as prose under the grid rather than as a
     second grid beside it. Two readings, and they are measured differently on
     purpose: the priority is the whole game, the order is measured at level 15,
     which is why R comes back as 6 and 11 with no 16. Neither is padded out to
     look complete. */
  function skillFigHTML() {
    const lo = figs().lo;
    if (!fig || !lo?.plan) return '';
    const rows = [];
    const lv = lo.plan.levels;
    if (lv) rows.push(row('order', ABILITIES.filter(a => lv.levels[a]?.length)
      .map(a => `${a} ${lv.levels[a].join('\u00b7')}`).join('   '), lv.wr, lv.n));
    const pr = lo.plan.priority;
    if (pr) rows.push(row('priority', pr.order.join(' > '), pr.wr, pr.n));
    // Bans and the spell pair both carry a source label already; this was the
    // one lolalytics-sourced figure on the page reading unmarked.
    return rows.length
      ? `<p class="pl-lab">lolalytics</p><div class="pl-lola-sk">${rows.join('')}</div>` : '';

    function row(k, body, wr, n) {
      return `<div class="r"><span class="k">${k}</span><span><b>${esc(body)}</b>
        \u00b7 <b class="${fig.wrClass(wr, n)}">${fig.fmtWr(wr)}</b> win
        \u00b7 ${fig.games(n)} games</span></div>`;
    }
  }

  function setSkill(ability, level) {
    const plan = getPlan();
    const i = level - 1;
    if (plan.skills[i] === ability) { plan.skills[i] = ''; return changed(); }
    if (!legalAt(ability, level)) return;
    // The cap is the one rule the grid cannot show, so it has to say it out loud
    // rather than swallowing the click and looking broken.
    if (ability !== 'R' && plan.skills.filter(a => a === ability).length >= MAX_BASIC)
      return say(`${ability} is already at ${MAX_BASIC} points. Clear one first.`);
    plan.skills[i] = ability;
    changed();
  }

  /* ── paths ── */
  function renderPaths() {
    const plan = getPlan();
    const jungle = String(getRole() || '').toLowerCase() === 'jungle';
    $('planPathCard').hidden = !jungle;
    if (!jungle) return;
    $('planPaths').innerHTML = plan.paths.length
      ? plan.paths.map((p, n) => `<div class="pl-edit">
          <div class="pl-edit-head">
            <input class="pl-nm" data-pathname="${n}" value="${esc(p.name)}"
              placeholder="Name this path" autocomplete="off">
            <button class="pl-notebtn" data-pathnote="${n}"
              title="${p.note ? esc(p.note) : 'When would you take this path?'}">≡</button>
            <button class="del" data-pathdrop="${n}" aria-label="Delete this path">Delete</button>
          </div>
          <span class="pl-lab">Route</span>
          <div class="pl-route built">${p.camps.map((c, at) => {
            const camp = CAMP_BY_ID.get(c);
            return `<button class="pl-camp" data-g="${camp.g}" data-pathpop="${n}:${at}"
              title="Remove ${esc(camp.n)}">${esc(camp.n)}</button>`;
          }).join('<i>›</i>') || '<span class="pl-empty">No camps yet.</span>'}</div>
          ${p.note ? `<p class="pl-note">${esc(p.note)}</p>` : ''}
          <div class="pl-pool-wrap">
            <span class="pl-lab">Add a step</span>
            <div class="pl-pool">${CAMPS.map(c =>
              `<button class="pl-camp add" data-g="${c.g}" data-pathadd="${n}:${c.id}"
                >${esc(c.n)}</button>`).join('')}</div>
          </div>
        </div>`).join('')
      : '<p class="pl-empty">No paths yet.</p>';
  }

  /* ── bans ── */
  async function loadBans() {
    const champ = getChampion();
    banChamp = champ;
    BANS = [];
    if (champ) {
      try {
        const r = await fetch(`api/bans/${encodeURIComponent(champ)}`);
        BANS = (await r.json()).champions || [];
      } catch { BANS = []; }
    }
    renderBans();
  }

  function renderBans() {
    const champ = getChampion();
    $('planBanWhy').textContent = champ
      ? `Kept against ${champ}, not against this build. Every ${champ} set reads the same list.`
      : 'Name the champion on the Items step first. A ban belongs to a champion, not to a set.';
    $('planBanIn').disabled = !champ;
    $('planBans').innerHTML = BANS.map(k => {
      const c = byKey.get(k);
      return c ? `<button class="chip" data-banoff="${k}" title="Remove ${esc(c.n)}">
        <img src="${esc(c.u)}" alt=""> ${esc(c.n)}</button>` : '';
    }).join('');
    renderBanSuggestions();
  }

  /* The list a ban is actually chosen from: the champions this one loses to,
     worst first, with the win rate that says so. coachless has no matchup data
     at all - eleven endpoint names across three controllers, all misses, and
     their own nav has no matchup page - so this figure has one source and the
     header says which. */
  function renderBanSuggestions() {
    const rows = (figs().lo?.counters || []).map(r => ({ r, c: byName.get(r.n.toLowerCase()) }))
      .filter(x => x.c);
    $('planBanSugWrap').hidden = !rows.length || !fig;
    if (!rows.length || !fig) return;
    $('planBanSug').innerHTML = rows.map(({ r, c }) => {
      const on = BANS.includes(c.k);
      return `<span class="pl-opt solo${on ? ' on' : ''}">
        <button data-bansug="${c.k}" aria-pressed="${on}"
          title="${on ? 'Already banned' : `Ban ${esc(c.n)}`}">
          <img src="${esc(c.u)}" alt="" width="32" height="32" loading="lazy">
          <span class="nm">${esc(c.n)}</span>
          ${lane(fig.fmtWr(r.wr), fig.wrClass(r.wr, r.g), fig.games(r.g))}
        </button></span>`;
    }).join('');
  }

  /* Bans save on their own, straight away, and never ride the set's autosave: they
   * are not on the set, and a build you never saved should still be able to record
   * that Kayle is unplayable into this champion. */
  async function saveBans() {
    const champ = getChampion();
    if (!champ) return;
    try {
      await fetch(`api/bans/${encodeURIComponent(champ)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ champions: BANS }),
      });
    } catch { say('Could not reach the ban list.'); }
  }

  /* ── glue ── */
  let sayT = null;
  function say(msg) {
    $('planSub').textContent = msg;
    clearTimeout(sayT);
    sayT = setTimeout(() => { $('planSub').textContent = ''; }, 4000);
  }

  function changed() { render(); onChange(); }

  root.addEventListener('click', async e => {
    const t = e.target;
    const hit = sel => t.closest(`[${sel}]`)?.getAttribute(sel);

    const spell = hit('data-spell');
    if (spell) return toggleSpell(+spell);

    const sn = hit('data-spellnote');
    if (sn) {
      const plan = getPlan(), s = SPELL_BY_ID.get(+sn);
      const was = plan.spellNotes[String(sn)] || '';
      const note = await askNote({
        title: `Note: ${s.n}`,
        why: 'When would you bring this, and why? One sentence.',
        value: was,
      });
      if (note === null) return;
      if (note) plan.spellNotes[String(sn)] = note;
      else delete plan.spellNotes[String(sn)];
      return changed();
    }

    const sk = t.closest('[data-sk]');
    if (sk) return setSkill(sk.dataset.sk, +sk.dataset.lv);

    if (t.closest('#planSkillClear')) {
      getPlan().skills = Array(18).fill('');
      return changed();
    }

    if (t.closest('#planPathAdd')) {
      getPlan().paths.push({ name: '', camps: [], note: '' });
      return changed();
    }

    const add = hit('data-pathadd');
    if (add) {
      const [n, camp] = add.split(':');
      getPlan().paths[+n].camps.push(camp);
      return changed();
    }

    const pop = hit('data-pathpop');
    if (pop) {
      const [n, at] = pop.split(':').map(Number);
      getPlan().paths[n].camps.splice(at, 1);
      return changed();
    }

    const drop = hit('data-pathdrop');
    if (drop) {
      getPlan().paths.splice(+drop, 1);
      return changed();
    }

    const pn = hit('data-pathnote');
    if (pn) {
      const p = getPlan().paths[+pn];
      const note = await askNote({
        title: `Note: ${p.name || 'this path'}`,
        why: 'When would you take this path, and why? One sentence.',
        value: p.note,
      });
      if (note === null) return;
      p.note = note;
      return changed();
    }

    const off = hit('data-banoff');
    if (off) {
      BANS = BANS.filter(k => k !== +off);
      renderBans();
      return saveBans();
    }

    const sug = hit('data-bansug');
    if (sug) {
      const k = +sug;
      BANS = BANS.includes(k) ? BANS.filter(x => x !== k) : [...BANS, k];
      renderBans();
      return saveBans();
    }
  });

  // A path name is a text field, so it writes on input and repaints nothing: a
  // re-render mid-keystroke would take the caret with it.
  root.addEventListener('input', e => {
    const n = e.target.getAttribute?.('data-pathname');
    if (n === null || n === undefined) return;
    getPlan().paths[+n].name = e.target.value;
    onChange();
  });

  $('planBanIn').addEventListener('change', () => {
    const el = $('planBanIn');
    const c = byName.get(el.value.trim().toLowerCase());
    el.value = '';
    if (!c || BANS.includes(c.k)) return;
    BANS.push(c.k);
    renderBans();
    saveBans();
  });

  function render() {
    renderSpells();
    renderSkills();
    renderPaths();
    // The champion is set on the Items step, so it can change under this page.
    if (getChampion() !== banChamp) loadBans(); else renderBans();
  }

  render();
  return { render };
}
