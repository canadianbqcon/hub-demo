/* workbench body, part 1 (React): shared state, the build grouping, the doc cards, the history and
   decision-log views and the build list. Ported from workbench.js lines 1-500 plus the list/grouping helpers
   they lean on: same DOM, ids, classes and request bodies as the plain page.
   One store (UI.S) holds what the plain page kept in `state`; code outside React mutates it and calls
   UI.rerender(), and workbench.jsx's App re-draws from it. Components below are pure over their props.
   The topbar, the footer status bar and the shell's is-detail class stay in the template and are touched
   by id, as the plain page did. See workbench-decide.jsx (stages, options, walk) and workbench.jsx (mount). */
window.WorkbenchUI = window.WorkbenchUI || {};
(() => {
  const UI = window.WorkbenchUI;
  const { useState, useEffect, useLayoutEffect, useRef, useReducer } = React;

  UI.API = "/workbench/api";
  const $ = (id) => document.getElementById(id);

  /* options = /api/options as sent (newest first); builds = grouped, see groupBuilds.
     The rest is what the plain page painted by hand: head (title block), track (painted stage list),
     rail (decision log rows), cards (what #cards holds), idle, empty. */
  const S = {
    specs: [], plans: [], options: [], history: [], pend: [], builds: [], visible: [], cur: null, hist: false, gen: 0, memo: {},
    names: {}, failed: [], rowKey: null, active: null, busy: 0, q: "", listScroll: 0,
    head: { sub: "", title: "", tip: "" }, track: null, rail: null, cards: null, idle: false,
    empty: { text: "", sub: "", shown: false },
    // "<session>:<n>" -> verdict for a mark answer still inside its 5 s hold: the server still says
    // fixed, so without this the inbox row kept its count and a reopened walk drew Close again (2026-11-03)
    markHeld: {},
  };
  UI.S = S;

  const subs = new Set();
  UI.rerender = () => { subs.forEach((f) => { f(); }); };
  UI.useStore = () => {
    const [, tick] = useReducer((x) => x + 1, 0);
    useEffect(() => { subs.add(tick); return () => { subs.delete(tick); }; }, []);
  };

  UI.setStatus = (msg) => { $("statusMsg").textContent = msg; };
  const setStatus = UI.setStatus;
  /* Every write waits 5 s behind its own Undo toast over the page, so a misclick costs nothing.
     The click has already drawn its result; revert takes it back on undo or a failed write.
     Writes run one at a time in click order, never dropped. Resolves to fn()'s result, or null
     when he undid it; S.busy counts writes not yet settled (the tab-return reload waits on it). */
  UI.HOLD_S = 5;
  let queue = Promise.resolve();
  /* Held writes not yet sent. A reload inside the hold used to drop the write with no trace,
     and a hidden tab's timers can be frozen for as long as it stays hidden (a 2026-10-27
     send-back landed ~50 min late), so leaving the tab sends what is held at once and an
     unload while anything is unsettled asks first. */
  const held = new Set();
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") held.forEach((send) => { send(true); });
  });
  window.addEventListener("beforeunload", (e) => { if (S.busy) e.preventDefault(); });
  UI.hold = (label, fn, revert) => {
    S.busy++;
    return new Promise((done) => {
      const chip = document.createElement("span"), txt = document.createTextNode(""), b = document.createElement("button");
      let left = UI.HOLD_S;
      const show = () => { txt.textContent = `${label} · sends in ${left}s`; };
      chip.className = "hub-toast wb-hold";
      b.type = "button"; b.className = "hub-btn hub-btn--accent wb-undo"; b.textContent = "undo";
      chip.append(txt, b); $("statusHold").appendChild(chip); show();
      const tick = setInterval(() => { left--; show(); }, 1000);
      const end = () => { clearTimeout(go); clearInterval(tick); chip.remove(); held.delete(send); };
      // leaving: start now instead of behind the queue, whose earlier fetch may never settle once
      // the page is gone (keepalive keeps a started fetch alive, not a not-yet-started one)
      const send = (leaving) => {
        end();
        const run = leaving ? Promise.resolve().then(fn) : queue.then(fn);
        queue = run.catch(() => null);
        run.catch(() => null).then((r) => { S.busy--; if (!r && revert) revert(); done(r); });
      };
      const go = setTimeout(() => send(false), UI.HOLD_S * 1000);
      held.add(send);
      b.onclick = () => { end(); S.busy--; if (revert) revert(); setStatus(`${label} undone`); done(null); };
    });
  };

  // ── ledger helpers ───────────────────────────────────────────────────────

  // ledger decided_at is SQLite UTC with no zone; a bare spec date already parses as UTC
  function stamp(s) { return s ? (Date.parse(String(s).replace(" ", "T") + (String(s).length > 10 ? "Z" : "")) || 0) : 0; }

  // "Oct 12, 9:27 PM" in local time; the ledger stores UTC
  function when(s) {
    const t = stamp(s);
    return t ? new Date(t).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";
  }

  function newestFirst(rows) {
    return rows.slice().sort((a, b) => stamp(b.decided_at) - stamp(a.decided_at) || (b.seq || 0) - (a.seq || 0));
  }

  function latestRow(kind, path) {
    let row = null;
    S.history.forEach((r) => {
      if (r.kind === kind && r.doc_path === path && (!row || (r.seq || 0) > (row.seq || 0))) row = r;
    });
    return row;
  }

  /* Latest row (highest seq) for this kind+path. An approval is final: later edits to the
     files are his own, made in session, so they never reopen it; new work is a new set. */
  function badgeFor(kind, path) {
    const row = latestRow(kind, path);
    return row ? row.verdict : null;
  }

  function VerdictPill({ v }) {
    if (!v) return <span className="hub-pill hub-pill--dashed">none</span>;
    if (v === "approved") return <span className="hub-pill is-good">approved</span>;
    if (v === "sent_back") return <span className="hub-pill is-warn">sent back</span>;
    if (v === "abandoned") return <span className="hub-pill is-alert">abandoned</span>;
    return <span className="hub-pill hub-pill--dashed">{v}</span>;
  }

  // ── action helpers ───────────────────────────────────────────────────────

  function ActBtn({ label, cls, onClick, disabled }) {
    return <button type="button" className={`hub-btn${cls ? ` ${cls}` : ""}`} onClick={onClick} disabled={disabled}>{label}</button>;
  }

  /* A card's comment strip: one box per card, one panel shown at a time. show() opens a panel and
     cancel hands focus back to the opener. Field ids run wb-cmt-1.. in card order, as the plain page's. */
  let fieldSeq = 0;
  function useStrip(names) {
    const [active, setActive] = useState(null);
    const [nonce, setNonce] = useState(0);
    const [vals, setVals] = useState({});
    const [labels, setLabels] = useState({});
    const opener = useRef(null);
    const ids = useRef(null);
    if (!ids.current) { ids.current = {}; names.forEach((n) => { ids.current[n] = `wb-cmt-${++fieldSeq}`; }); }
    return {
      active, nonce, vals, labels, ids: ids.current,
      setVal: (k, v) => { setVals((s) => Object.assign({}, s, { [k]: v })); },
      show: (k, o, label) => {
        opener.current = o;
        if (label != null) setLabels((s) => Object.assign({}, s, { [k]: label }));
        setActive(k); setNonce((n) => n + 1);
      },
      hide: () => { setActive(null); },
      cancel: () => {
        setActive(null);
        const o = opener.current;
        if (o?.isConnected) o.focus();
      },
    };
  }
  UI.useStrip = useStrip;

  // defs: { panel: { label, placeholder, confirmLabel, onConfirm(text) } }
  function CardStrip({ strip, defs }) {
    const ta = useRef(null);
    useEffect(() => { if (strip.active && ta.current) ta.current.focus(); }, [strip.nonce]);
    const k = strip.active, p = k && defs[k];
    return (
      <div className="wb-strip" hidden={!k}>
        {p && (
          <React.Fragment>
            <div className="hub-field">
              <label htmlFor={strip.ids[k]}>{strip.labels[k] != null ? strip.labels[k] : p.label}</label>
              <textarea className="wb-textarea" id={strip.ids[k]} placeholder={p.placeholder || undefined} ref={ta}
                        value={strip.vals[k] || ""} onChange={(e) => strip.setVal(k, e.target.value)} />
            </div>
            <div className="hub-btn-row">
              <ActBtn label={p.confirmLabel} cls="hub-btn--accent" onClick={() => p.onConfirm((strip.vals[k] || "").trim())} />
              <ActBtn label="cancel" onClick={strip.cancel} />
            </div>
          </React.Fragment>
        )}
      </div>
    );
  }

  // ── stage cards ──────────────────────────────────────────────────────────

  /* One plate card in #cards: title and state on the plate, sign-off buttons in acts,
     the comment strip under the plate, content in the body (html = trusted markup from the server). */
  function PlateCard({ title, sum, acts, strip, bodyClass, html, bodyRef, extra, children }) {
    return (
      <section className={`hub-plate-card${extra ? ` ${extra}` : ""}`}>
        <div className="hub-section-head">
          <span className="hub-section-head-t">{title}</span>
          <span className="hub-section-head-sum">{sum || ""}</span>
          <div className="hub-section-head-act wb-acts">{acts}</div>
        </div>
        {strip || <div className="wb-strip" hidden></div>}
        {html != null
          ? <div className={bodyClass || "wb-card-body"} ref={bodyRef} dangerouslySetInnerHTML={{ __html: html }} />
          : <div className={bodyClass || "wb-card-body"} ref={bodyRef}>{children}</div>}
      </section>
    );
  }

  // a wide table scrolls in its own box, so the table keeps its semantics and full width
  function wrapTables(root) {
    if (!root) return;
    Array.prototype.forEach.call(root.querySelectorAll("table"), (t) => {
      if (t.parentNode.classList.contains("wb-table")) return;
      const box = document.createElement("div");
      box.className = "wb-table";
      t.parentNode.insertBefore(box, t);
      box.appendChild(t);
    });
  }

  /* A spec or plan: the rendered doc (and a plan's quality gates) with approve / send back.
     locked = the order lock: every sign-off control reads it, so a retry that flips it just re-renders. */
  function DocCards({ d, step, st, at, locked }) {
    const strip = useStrip(["back"]);
    const docRef = useRef(null), gatesRef = useRef(null);
    useLayoutEffect(() => { wrapTables(docRef.current); wrapTables(gatesRef.current); }, [d]);
    const defs = {
      back: {
        label: "reason", placeholder: "what should change…", confirmLabel: "send",
        onConfirm: (cmt) => {
          if (!cmt) { setStatus("a comment is required to send back"); return; }
          UI.decide(d, step, at, "sent_back", cmt);
        },
      },
    };
    // an approval is final: no send back on an approved doc, new work is a new build
    const backOff = locked || !d || !!st.done;
    return (
      <React.Fragment>
        <PlateCard title={step.title || step.slug} sum={st.sub} bodyClass="wb-card-body wb-doc" bodyRef={docRef}
                   html={d ? d.html : undefined}
                   strip={<CardStrip strip={strip} defs={defs} />}
                   acts={[
                     <ActBtn key="a" label={st.done ? "approved" : "approve"} cls="hub-btn--accent" disabled={backOff}
                             onClick={() => { UI.decide(d, step, at, "approved"); }} />,
                     <ActBtn key="b" label="send back" cls="hub-btn--danger" disabled={backOff}
                             onClick={(e) => { strip.show("back", e.currentTarget); }} />,
                   ]}>
          {d ? null : "couldn't load this document"}
        </PlateCard>
        {d?.gates_html
          ? <PlateCard title="quality gates" sum="" bodyClass="wb-card-body wb-doc wb-gates" bodyRef={gatesRef} html={d.gates_html} />
          : null}
      </React.Fragment>
    );
  }

  // ── history toggle and context rail ──────────────────────────────────────

  // a ledger row's detail: path, decided, choice, comment, snapshot
  // the list leaves doc snapshots out (they were ~1.9 MB); this fetches one when its row opens
  function Snapshot({ row }) {
    const [text, setText] = useState(row.snapshot);
    useEffect(() => {
      if (text != null || !row.id) return;
      fetch(`${UI.API}/history/snapshot?id=${encodeURIComponent(row.id)}`)
        .then((r) => (r.ok ? r.json() : { snapshot: "(snapshot unavailable)" }))
        .then((d) => setText(d.snapshot || ""), () => setText("(snapshot unavailable)"));
    }, [row.id]);
    return (
      <div className="hub-trd-measure">
        <div className="hub-meta-strip">
          <span><b>path</b> {row.doc_path || ""}</span>
          <span><b>decided</b> {row.decided_at || ""}</span>
          {row.choice ? <span><b>choice</b> {row.choice}</span> : null}
        </div>
        {row.comment ? <div><div className="hub-block-label">comment</div><div className="hub-block-text">{row.comment}</div></div> : null}
        <div><div className="hub-block-label">snapshot</div><div className="hub-block-text">{text == null ? (row.id ? "loading…" : "") : text}</div></div>
      </div>
    );
  }

  /* A mark row has no doc: build_slug is the marks session, choice the mark number, comment his words
     and snapshot the JSON of the mark as it stood. It reads "mark N" under the session name. */
  function markOf(r) {
    try { return JSON.parse(r.snapshot) || {}; } catch (_e) { return {}; }
  }

  function MarkSnapshot({ row }) {
    const m = markOf(row);
    return (
      <div className="hub-trd-measure">
        <div className="hub-meta-strip">
          <span><b>decided</b> {row.decided_at || ""}</span>
          {m.status_before ? <span><b>was</b> {m.status_before}</span> : null}
        </div>
        {m.comment ? <div><div className="hub-block-label">mark</div><div className="hub-block-text">{m.comment}</div></div> : null}
        {row.comment ? <div><div className="hub-block-label">his words</div><div className="hub-block-text">{row.comment}</div></div> : null}
      </div>
    );
  }

  // the body mounts on first open: a closed <details> still renders its children, which would fetch every snapshot
  function HistRow({ r }) {
    const [seen, setSeen] = useState(false);
    return (
      <details className="wb-hist" onToggle={(e) => { if (e.currentTarget.open) setSeen(true); }}>
        {r.kind === "mark"
          ? <summary>{r.build_slug}<span className="wb-hist-sub">{`mark ${r.choice || ""}`}</span><VerdictPill v={r.verdict} />{" "}<span>{r.decided_at || ""}</span></summary>
          : <summary>{`${r.kind} · ${r.build_slug} `}<VerdictPill v={r.verdict} />{" "}<span>{r.decided_at || ""}</span></summary>}
        {seen ? (r.kind === "mark" ? <MarkSnapshot row={r} /> : <Snapshot row={r} />) : null}
      </details>
    );
  }

  // global history: every ledger row newest first, each expandable to its snapshot
  function HistoryView({ rows }) {
    return (
      <PlateCard title="history" sum={`${rows.length} decisions`}>
        {rows.length ? rows.map((r) => <HistRow r={r} key={r.id || r.seq + r.build_slug + r.decided_at} />) : "no decisions yet"}
      </PlateCard>
    );
  }

  // this build's decision log: ledger rows naming the build, one of its steps' slugs or paths
  // collapsed it shows only the newest decision (rows arrive newest first); the head toggles the rest
  function DecisionLog({ rows }) {
    const [open, setOpen] = React.useState(false);
    const more = rows.length > 1;
    return (
      <section className="hub-plate-card wb-log">
        <div className="hub-section-head">
          <span className="hub-section-head-t">Decision log</span>
          {more ? (
            <button type="button" className="hub-btn wb-log-toggle" aria-expanded={String(open)} onClick={() => setOpen(!open)}>
              {open ? "latest only" : `show all ${rows.length}`}
            </button>
          ) : <span className="hub-section-head-sum">{rows.length || ""}</span>}
        </div>
        {rows.length ? null : <div className="wb-rail-row hub-block-text">nothing decided yet</div>}
        {rows.slice(0, 1).map((r, i) => <LogRow r={r} key={i} />)}
        <HubCollapse open={open}>{rows.slice(1).map((r, i) => <LogRow r={r} key={i + 1} />)}</HubCollapse>
      </section>
    );
  }

  function LogRow({ r }) {
    return (
      <div className="wb-rail-row">
        <div className="wb-rail-head"><span className="wb-rail-kind">{r.kind === "mark" ? `mark ${r.choice || ""}` : r.kind}</span><VerdictPill v={r.verdict} /></div>
        <div className="wb-rail-when">{when(r.decided_at) + (r.choice && r.kind !== "mark" ? ` · picked ${r.choice}` : "")}</div>
        {r.comment ? <div className="wb-rail-said">{r.comment.replace(/^title: /, "")}</div> : null}
      </div>
    );
  }

  // half-browser form of the log: the newest decision as the header card's bottom strip, opening into a
  // dropdown over the cards with every decision (CSS shows it only where the rail column is gone)
  function HeadLog({ rows }) {
    if (!rows.length) return null;
    const r = rows[0];
    return (
      <details className="wb-head-log">
        <summary>
          <span className="wb-head-log-l">Last decision</span>
          <span className="wb-rail-kind">{r.kind}</span>
          <VerdictPill v={r.verdict} />
          <span className="wb-head-log-when">{when(r.decided_at) + (r.choice ? ` · picked ${r.choice}` : "")}</span>
          {rows.length > 1 ? <span className="wb-head-log-n">{`all ${rows.length}`}</span> : null}
        </summary>
        <div className="wb-head-log-list">{rows.map((x, i) => <LogRow r={x} key={i} />)}</div>
      </details>
    );
  }

  const Bars = ({ n }) => Array.from({ length: n }, (_, i) => <span className="wb-skel-bar" key={i}></span>);

  // nothing selected: a general placeholder that fills the column (mark 224744 #2)
  function IdleCards() {
    return (
      <section className="hub-plate-card wb-idle">
        <svg className="wb-idle-g" viewBox="0 0 48 48" aria-hidden="true"><rect x="8" y="8" width="32" height="32" rx="6" /><path d="M16 18 H32 M16 24 H32 M16 30 H25" /></svg>
        <div className="wb-empty-t">Nothing open</div>
        <div className="wb-empty-x">Pick a build, a walk-through or a history entry from the list to open it here.</div>
      </section>
    );
  }
  function IdleRail() {
    return (
      <section className="hub-plate-card wb-log">
        <div className="hub-section-head"><span className="hub-section-head-t">Decision log</span></div>
        {[0, 1, 2].map((i) => <div className="wb-rail-row wb-skel" key={i}><Bars n={2} /></div>)}
      </section>
    );
  }

  // ── stage track model and order lock ─────────────────────────────────────

  /* One stage per step in build order, plus a hollow disabled plan stage when a spec has no
     plan file yet (the plan is still owed). */
  function stagesOf(b) {
    const out = []; let clear = true;
    b.steps.forEach((s) => {
      const v = latestRow(s.kind, s.path)?.verdict;
      const done = v === "approved";
      const sub = done ? "approved"
        : v === "sent_back" ? "sent back" : v === "abandoned" ? "abandoned"
        : clear ? "waiting on you" : "locked";
      clear = clear && done;
      out.push({ key: s.key, label: s.kind === "design" ? (s.title || s.slug) : s.key, step: s, done: done, sub: sub });
    });
    if (b.steps.some((s) => s.kind === "spec") && !b.steps.some((s) => s.kind === "plan")) {
      out.push({ key: "plan", label: "plan", disabled: true, done: false, sub: "not written yet" });
    }
    const now = out.filter((x) => !x.done)[0];
    if (now) now.now = true;
    return out;
  }

  function defaultStage(stages) {
    const open = stages.filter((x) => !x.disabled);
    return (open.filter((x) => !x.done)[0] || open[open.length - 1])?.key;
  }

  /* The track is spec, options, plan, minus any the build has none of. Every option set sits
     under options, and when there is more than one the carousel under the track steps through them. */
  const GROUPS = [["spec", "Spec"], ["options", "Options"], ["plan", "Plan"]];
  function groupOf(st) { return st.key === "spec" || st.key === "plan" ? st.key : "options"; }

  function groupSummary(_g, members) {
    const open = members.filter((x) => !x.disabled), done = open.filter((x) => x.done).length;
    if (!open.length) return { disabled: true, sub: members.length ? members[0].sub : "none" };
    // the stage a click opens: the one already open, else the first still waiting, else the first
    const to = open.filter((x) => !x.done)[0] || open[0];
    const sub = open.length === 1 ? open[0].sub : done === open.length ? `${open.length} sets approved` : `${open.length} sets, ${open.length - done} open`;
    return { to: to.key, done: done === open.length, now: members.some((x) => x.now), sub: sub };
  }

  // ── grouping ─────────────────────────────────────────────────────────────

  // finished-ness of a step's verdict; the lowest-ranked step gives the row's pip
  const RANK = { none: 0, sent_back: 1, abandoned: 2, approved: 3 };
  const PIP = { none: "is-waiting", sent_back: "is-sent-back", abandoned: "is-abandoned", approved: "is-approved" };

  // waiting on him: nothing decided yet
  function isWaiting(v) { return !v; }

  /* An inbox doc waits on him when it has no verdict, or it was sent back (a fork included) and
     its files changed since: the rework is done and the next round is his. */
  function waitsOnHim(kind, d) {
    const row = latestRow(kind, d.path);
    if (!row) return true;
    return row.verdict === "sent_back" && !!d.sha256 && !!row.doc_sha256 && d.sha256 !== row.doc_sha256;
  }

  function groupBuilds() {
    const by = {}, order = [];
    function get(slug) {
      if (!by[slug]) { by[slug] = { slug: slug, title: "", spec: null, plan: null, sets: [], times: [] }; order.push(slug); }
      return by[slug];
    }
    function step(key, kind, d) {
      return { key: key, kind: kind, path: d.path, slug: d.slug, title: d.title, verdict: badgeFor(kind, d.path) };
    }
    S.specs.forEach((d) => { const b = get(d.slug); b.spec = step("spec", "spec", d); b.times.push(stamp(d.date)); });
    S.plans.forEach((d) => { const b = get(d.slug); b.plan = step("plan", "plan", d); b.times.push(stamp(d.date)); });
    // /api/options is newest first; the chain reads oldest first
    S.options.slice().reverse().forEach((d) => { get(d.build || d.slug).sets.push(step(d.slug, "design", d)); });
    // a rebuilt set gets a new mtime and would jump to the end of the chain; a numbered
    // slug (liquid-03-pills) keeps its place by number, after the unnumbered sets
    function setNo(s) { const m = /-(\d+)-/.exec(s.slug); return m ? +m[1] : -1; }
    order.forEach((slug) => { by[slug].sets.sort((a, z) => setNo(a) - setNo(z)); });

    S.builds = order.map((slug) => {
      const b = by[slug];
      const steps = [].concat(b.spec || [], b.sets, b.plan || []);
      const title = (b.spec || b.plan || b.sets[0])?.title || slug;
      const slugs = {}, paths = {};
      slugs[slug] = 1;
      steps.forEach((s) => { slugs[s.slug] = 1; paths[s.path] = 1; });
      S.history.forEach((r) => {
        // newest = latest of the build's doc dates and any ledger time touching it: options carry no date of their own
        if (paths[r.doc_path] || slugs[r.build_slug]) b.times.push(stamp(r.decided_at));
      });
      // a spec with no plan file yet still owes one: count it so the row reads 1/2, not a finished 1/1
      return { slug: slug, title: title, steps: steps, planDue: !!b.spec && !b.plan,
        newest: Math.max.apply(null, b.times.concat(0)) };
    }).filter((b) => b.steps.length);
  }

  function buildOf(slug) { return S.builds.filter((x) => x.slug === slug)[0]; }

  // ── build list ───────────────────────────────────────────────────────────

  function pipOf(b) {
    let worst = b.planDue ? "none" : "approved";
    b.steps.forEach((s) => { const v = s.verdict || "none"; if ((RANK[v] == null ? 0 : RANK[v]) < RANK[worst]) worst = RANK[v] == null ? "none" : v; });
    return PIP[worst];
  }

  // the doc kind is already the stage track's job: "Hub mark mode — design" reads "Hub mark mode"
  function shortTitle(t) {
    return String(t || "").replace(/\s*(?:[—–:-]\s*)?(?:design(?: spec)?|spec|implementation plan|plan)$/i, "").trim() || t;
  }

  /* Haiku's 2-4 word name for a build (names.py, cached server-side); the trimmed title
     until it lands or when there is no key. */
  function nameOf(b) { return S.names[b.title] || shortTitle(b.title); }

  /* The inbox: one row per thing waiting on him, newest first. Pure over S (specs, plans, options,
     marks, names, history) so inbox.selftest.js can lift it. Spec and plan rows read the build name
     off S.builds; an option set with no build.txt is a one-off and opens as its own build. */
  function inboxRows() {
    const rows = [];
    function name(slug) {
      const b = S.builds.filter((x) => x.slug === slug)[0];
      return b ? nameOf(b) : slug;
    }
    // the order lock keeps a step shut until every earlier one is approved: one row per chain, its first unapproved step
    function isNext(slug, path) {
      const b = S.builds.filter((x) => x.slug === slug)[0];
      const first = b && (b.steps || []).filter((s) => badgeFor(s.kind, s.path) !== "approved")[0];
      return !first || first.path === path;
    }
    [["spec", S.specs], ["plan", S.plans]].forEach((g) => {
      g[1].forEach((d, i) => {
        // groupBuilds keeps the last doc per slug (a re-dated spec); only that one is a row
        if (g[1].some((o, j) => j > i && o.slug === d.slug)) return;
        if (!waitsOnHim(g[0], d) || !isNext(d.slug, d.path)) return;
        const n = name(d.slug);
        rows.push({ key: `build:${d.slug}:${g[0]}`, source: "build", kind: "sign-off", verb: "Sign off",
          object: `the ${n} ${g[0]}`, tag: n, time: stamp(d.date), open: { build: d.slug, step: g[0] } });
      });
    });
    S.options.forEach((d) => {
      const one = d.cards === 1, oneoff = !d.build, slug = d.build || d.slug;
      if (!waitsOnHim("design", d) || !isNext(slug, d.path)) return;
      rows.push({ key: `${oneoff ? "oneoff" : "build"}:${slug}:${d.slug}`, source: oneoff ? "oneoff" : "build",
        kind: one ? "check" : "pick", verb: one ? "Check" : "Pick", object: shortTitle(d.title),
        tag: oneoff ? "One-off" : name(slug), time: (d.mtime || 0) * 1000, open: { build: slug, step: d.slug } });
    });
    (S.marks || []).forEach((m) => {
      const w = waitingOf(m);
      if (!(w > 0)) return;
      const s = m.session, t = new Date(sessionStart(s));
      const h = t.getHours();
      rows.push({ key: `mark:${s}:walk`, source: "mark", kind: "check", verb: "Check",
        object: `${w} fixed mark${w === 1 ? "" : "s"}`,
        tag: `Marks, ${h % 12 || 12}:${String(t.getMinutes()).padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`,
        time: t.getTime(), open: { walk: s } });
    });
    return rows.sort((a, z) => z.time - a.time || (a.key < z.key ? -1 : a.key > z.key ? 1 : 0));
  }

  // the empty inbox says so, unless a load failed: then the list may be short and the line says that instead
  function inboxEmptyLine(failed) {
    return failed.length ? `couldn't load ${failed.join(", ")}, list may be incomplete` : "nothing waiting on you";
  }

  /* Row keys: `<source>:<slug>:<step>` for inbox rows, `build:<slug>` for build rows, `mark:<session>:walk`
     for a marks session. S.visible holds them in draw order: the inbox first, then the rest, each key once. */
  function visibleKeys(rows, rest) {
    const seen = new Set();
    return rows.map((r) => r.key).concat(rest.map((o) => (o.session ? `mark:${o.session}:walk` : `build:${o.slug}`)))
      .filter((k) => !seen.has(k) && seen.add(k));
  }

  // "40m", "3h", "yest.", then the date
  function ageOf(t) {
    if (!t) return "";
    const m = Math.round((Date.now() - t) / 6e4);
    if (m < 1) return "now";
    if (m < 60) return `${m}m`;
    if (m < 1440) return `${Math.floor(m / 60)}h`;
    const d = dayOf(t);
    return d === "Yesterday" ? "yest." : d;
  }

  // treatment B: the verb carries the kind, source and age sit under it
  function InboxRow({ r, active, stop }) {
    return (
      <div className={`hub-e3p-entry wb-ask${active ? " active" : ""}`} role="option" aria-selected={String(active)}
           tabIndex={stop ? 0 : -1} data-key={r.key} title={`${r.verb} ${r.object}`}
           onClick={() => { UI.selectRow(r.key, true); }}>
        <span className="hub-e3p-entry-mark"><span className="wb-pip is-waiting"></span></span>
        <span className="wb-ask-2l">
          <span className="hub-e3p-entry-t"><b className="wb-ask-verb">{r.verb}</b>{` ${r.object}`}</span>
          <span className="wb-ask-meta">{`${r.tag} · ${ageOf(r.time)}`}</span>
        </span>
      </div>
    );
  }

  function BuildRow({ b, active, stop }) {
    const signed = b.steps.filter((s) => s.verdict === "approved").length, total = b.steps.length + (b.planDue ? 1 : 0);
    return (
      <div className={`hub-e3p-entry${active ? " active" : ""}`} role="option" aria-selected={String(active)}
           tabIndex={stop ? 0 : -1} data-key={`build:${b.slug}`} title={b.title}
           onClick={() => { UI.selectRow(`build:${b.slug}`, true); }}>
        <span className="hub-e3p-entry-mark"><span className={`wb-pip ${pipOf(b)}`}></span></span>
        <span className="hub-e3p-entry-t">{nameOf(b)}</span>
        <span className="hub-e3p-entry-v"><span className={`hub-pill${signed < total ? " hub-pill--filled" : ""}`}>{`${signed}/${total}`}</span></span>
      </div>
    );
  }

  // fixed marks still to answer: the server's count less the answers held in their undo window
  function waitingOf(m) { return Math.max(0, (m.waiting || 0) - Object.keys(S.markHeld || {}).filter((k) => k.startsWith(`${m.session}:`)).length); }

  // session names start YYYY-MM-DD-HHMMSS, read as local time
  function sessionStart(s) { return new Date(`${s.slice(0, 10)}T${s.slice(11, 13)}:${s.slice(13, 15)}`).getTime(); }

  // a marks session whose marks are all still on Claude; the ones with something to check are inbox rows
  function MarksRow({ m, active, stop }) {
    const s = m.session, t = sessionStart(s);
    const when = `${dayOf(t)}, ${new Date(t).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}`;
    return (
      // opens in place like the other rows; a link here reloaded the whole page (every build, set and the ledger)
      <div className={`hub-e3p-entry${active ? " active" : ""}`} role="option" aria-selected={String(active)} title={s}
           tabIndex={stop ? 0 : -1} data-key={`mark:${s}:walk`}
           onClick={() => { UI.selectRow(`mark:${s}:walk`, true); }}>
        <span className="hub-e3p-entry-mark"><span className="wb-pip"></span></span>
        <span className="hub-e3p-entry-t">{when}</span>
        <span className="hub-e3p-entry-v"><span className="hub-pill">{`${m.open} open`}</span></span>
      </div>
    );
  }

  /* "Waiting on you" first and always (one row per waiting item), then "Pending": marks sessions and
     unfinished builds that are on Claude, then "Completed": fully signed builds, newest first with day
     dividers. Sets S.visible (arrow keys and the phone bar walk it) and S.active (the drawn row: the inbox
     row he opened while that step is open, else the build's row); the active row is the one tab stop, else the first. */
  function BuildList() {
    const q = S.q.trim().toLowerCase();
    const hit = (t) => !q || t.toLowerCase().indexOf(q) >= 0;
    const inbox = inboxRows().filter((r) => hit(`${r.object} ${r.tag}`));
    const asked = new Set(inbox.map((r) => r.open.build).filter(Boolean));
    const marks = q ? [] : (S.marks || []).filter((m) => !waitingOf(m) && m.open > 0).map((m) => ({ session: m.session, newest: sessionStart(m.session), m: m }));
    const builds = S.builds.filter((b) => hit(b.title) || hit(b.slug));
    const done = (b) => !b.planDue && b.steps.every((s) => s.verdict === "approved");
    // a build with a step waiting on him already has its inbox row
    const pending = builds.filter((b) => !done(b) && !asked.has(b.slug)).concat(marks).sort((a, b) => b.newest - a.newest);
    const completed = builds.filter(done).sort((a, b) => b.newest - a.newest);
    const rest = pending.concat(completed);
    S.visible = visibleKeys(inbox, rest);
    const cur = S.cur, walking = new URLSearchParams(location.search).get("walk");
    const opened = inbox.filter((r) => r.key === S.rowKey && cur && r.open.build === cur.slug && r.open.step === cur.key)[0];
    S.active = walking ? `mark:${walking}:walk` : opened ? opened.key : cur ? `build:${cur.slug}` : null;
    const stop = S.visible.indexOf(S.active) >= 0 ? S.active : S.visible[0];
    const out = [{ head: "Waiting on you", n: inbox.length }];
    if (!inbox.length && !q) out.push({ quiet: inboxEmptyLine(S.failed || []) });
    inbox.forEach((r) => { out.push({ r }); });
    if (pending.length) out.push({ head: "Pending", n: pending.length });
    pending.forEach((o) => { out.push(o.session ? { m: o.m } : { b: o }); });
    if (completed.length) out.push({ head: "Completed" });
    let last = null;
    completed.forEach((o) => {
      const d = dayOf(o.newest);
      if (d !== last) { out.push({ day: d, key: d }); last = d; }
      out.push(o.session ? { m: o.m } : { b: o });
    });
    return out.map((o) => o.head
      ? <div className="hub-e3p-group" role="presentation" key={`g${o.head}`}><span className="hub-e3p-group-n">{o.head}</span>{o.n ? <span className="wb-ask-n">{o.n}</span> : null}</div>
      : o.quiet ? <div className="wb-ask-none" role="presentation" key="quiet">{o.quiet}</div>
      : o.day ? <div className="wb-day" role="presentation" key={`d${o.key}`}>{o.day}</div>
      : o.r ? <InboxRow key={o.r.key} r={o.r} active={o.r.key === S.active} stop={o.r.key === stop} />
      : o.m ? <MarksRow key={`m${o.m.session}`} m={o.m} active={`mark:${o.m.session}:walk` === S.active} stop={`mark:${o.m.session}:walk` === stop} />
      : <BuildRow key={`b${o.b.slug}`} b={o.b} active={`build:${o.b.slug}` === S.active} stop={`build:${o.b.slug}` === stop} />);
  }

  // the list's date divider: Today, Yesterday, then "Oct 10" (with the year once it is not this year's)
  function dayOf(t) {
    if (!t) return "Undated";
    const d = new Date(t), now = new Date(), day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
    const ago = Math.round((day(now) - day(d)) / 864e5);
    if (ago === 0) return "Today";
    if (ago === 1) return "Yesterday";
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: d.getFullYear() === now.getFullYear() ? undefined : "numeric" });
  }

  Object.assign(UI, {
    stamp, when, newestFirst, latestRow, badgeFor, VerdictPill, ActBtn, CardStrip, PlateCard, DocCards, HistoryView,
    DecisionLog, HeadLog, IdleCards, IdleRail, stagesOf, defaultStage, GROUPS, groupOf, groupSummary, groupBuilds, buildOf, inboxRows,
    nameOf, BuildList, wrapTables,
  });
})();
