/* workbench page body (React): one list of builds, each an ordered stage track (spec, option sets, plan),
   on the entry-3-pane origin. Ported from workbench.js; this file holds the page logic that ties the other
   two together (data load, selection, URL, history toggle, stage open) and the mount.
   The origin carries no JS, so every state class is toggled here or by the components: .active and
   aria-selected on rows, is-detail on the shell (phone) which stays in the template and is touched by class.
   API contract: /workbench/api/docs?kind=, /doc?path=, /decide, /history, /options, /option?set=, /option/delete.
   URL is the single history owner: ?build=<slug>&step=<key>, or ?walk=<marks session>
   (the /marks walk-through, read and answered through /marks/api/walk and /walk/decide).
   See docs/specs/2026-10-06-workbench-build-chain-design.md. Files: workbench-docs.jsx, workbench-decide.jsx. */
(() => {
  const UI = window.WorkbenchUI;
  const { useEffect } = React;
  const { S, API, setStatus } = UI;
  const $ = (id) => document.getElementById(id);

  const rerender = () => UI.rerender();
  const isPhone = () => window.matchMedia("(max-width: 900px)").matches;
  const shellEl = () => document.querySelector(".hub-e3p");
  const refs = { headWrap: null };

  // ── redraw helpers ───────────────────────────────────────────────────────

  function isAt(at) { return !!S.cur && S.cur.slug === at.slug && S.cur.key === at.key; }

  // reopen the same stage from disk; nothing else re-renders
  function reopen(at, msg) {
    if (isAt(at) && !S.hist) renderStage(UI.buildOf(at.slug), at.key);
    setStatus(msg);
  }

  // after a recorded decision: reload docs and ledger (a plan may have been written since
  // this page loaded), redraw the list and the open stage
  function refresh(at, msg) {
    setStatus(msg);
    loadAll().then(() => {
      setStatus(msg);
      // whichever stage of the decided build is open now: its lock may have moved. Same steps
      // redraw from memory (the click already drew the result); new steps reload the stage
      const b = S.cur && S.cur.slug === at.slug && !S.hist && UI.buildOf(at.slug);
      const c = S.cards;
      if (b && c && c.kind === "stage" && c.build.slug === b.slug && stepsSig(c.build) !== stepsSig(b)) renderStage(b, S.cur.key);
      else redraw();
    });
  }

  function stageSig(cur, lock, step) {
    const row = UI.latestRow(step.kind, step.path);
    return JSON.stringify([cur && cur.sub, lock.locked, row && row.verdict, row && row.choice]);
  }

  /* Redraw the open stage from what is in memory, no fetch: a provisional ledger row just went
     in or came out. The cards remount only when the stage's state changed, so a server row that
     confirms the provisional one leaves the page (and its live previews) alone. */
  function redraw() {
    renderRail();
    const c = S.cards;
    if (!c || c.kind !== "stage" || S.hist) return;
    const b = UI.buildOf(c.build.slug) || c.build;
    const cur = paintTrack(b, c.at.key).filter((x) => x.key === c.at.key)[0] || c.cur;
    UI.lockFor(b, c.step).then((lock) => {
      if (S.cards !== c) return;
      const sig = stageSig(cur, lock, c.step);
      if (sig === c.sig) { rerender(); return; }
      S.cards = Object.assign({}, c, { gen: ++S.gen, build: b, cur: cur, lock: lock, sig: sig });
      rerender();
    });
  }

  /* A tab left open across a build gains docs it never loaded (the plan lands after the
     spec sign-off). Coming back to the tab reloads, and reopens the build at its default
     stage when its steps changed; otherwise the open card (and any typed comment) is kept. */
  function stepsSig(b) { return b ? b.steps.map((s) => s.path).join("|") : ""; }
  function onVisible() {
    if (document.hidden || S.busy) return;
    const before = S.cur && stepsSig(UI.buildOf(S.cur.slug));
    loadAll().then(() => {
      if (!S.cur || S.hist) return;
      if (stepsSig(UI.buildOf(S.cur.slug)) !== before) selectBuild(S.cur.slug, null, false);
      else renderRail();
    });
  }

  // ── history toggle and context rail ──────────────────────────────────────

  // global history: every ledger row newest first, each expandable to its snapshot
  function renderHistory() {
    S.cards = { kind: "history", rows: UI.newestFirst(S.history) };
    S.empty.shown = false;
  }

  /* quiet = the caller is about to draw a build, so only the chrome flips */
  function setHist(on, quiet) {
    S.hist = on;
    if (on) {
      S.gen++;
      if (isPhone()) shellEl().classList.add("is-detail");
      renderHistory();
    } else if (!quiet) {
      if (S.cur) selectBuild(S.cur.slug, S.cur.key, null); else S.cards = null;
    }
    rerender();
  }

  // this build's decision log: ledger rows naming the build, one of its steps' slugs or paths
  function renderRail() {
    const b = S.cur && UI.buildOf(S.cur.slug);
    if (!b) { S.rail = null; rerender(); return; }
    const slugs = {}, paths = {};
    slugs[b.slug] = 1;
    b.steps.forEach((s) => { slugs[s.slug] = 1; paths[s.path] = 1; });
    S.rail = { kind: "log", rows: UI.newestFirst(S.history.filter((r) => slugs[r.build_slug] || paths[r.doc_path])) };
    rerender();
  }

  // ── stage track and open stage ───────────────────────────────────────────

  function paintTrack(b, key) {
    const stages = UI.stagesOf(b);
    S.track = { stages: stages, key: key, slug: b.slug };
    return stages;
  }

  /* Open one stage of a build. S.gen is the stale guard: a slower fetch for a stage the
     user has since left finds a newer gen and draws nothing. */
  function renderStage(b, key) {
    const gen = ++S.gen, at = { slug: b.slug, key: key };
    const live = () => gen === S.gen;
    S.memo = {};
    S.cards = null;
    const st = paintTrack(b, key).filter((x) => x.key === key)[0];
    rerender();
    if (!st) return;
    const idx = b.steps.indexOf(st.step);
    Promise.all(b.steps.map((s) => UI.fetchStep(s).catch(() => null))).then((res) => {
      if (!live()) return;
      const cur = paintTrack(b, key).filter((x) => x.key === key)[0];
      return UI.lockFor(b, st.step).then((lock) => {
        if (!live()) return;
        S.cards = { kind: "stage", gen: gen, build: b, step: st.step, cur: cur, at: at, d: res[idx], lock: lock, sig: stageSig(cur, lock, st.step) };
        rerender();
      });
    });
  }

  // ── data load ────────────────────────────────────────────────────────────

  /* Four fetches in parallel. A failed one keeps what loaded before (empty on the
     first load) and is named in the status bar, so a half-loaded page says so. */
  function loadAll() {
    setStatus("loading builds…");
    const src = [["specs", `${API}/docs?kind=spec`], ["plans", `${API}/docs?kind=plan`],
      ["options", `${API}/options`], ["history", `${API}/history`], ["marks", "/marks/api/walk/sessions"]];
    return Promise.all(src.map((s) => fetch(s[1]).then((r) => {
      if (!r.ok) throw new Error(s[0]);
      return r.json();
    }).catch(() => null))).then((res) => {
      const missing = [];
      src.forEach((s, i) => {
        if (res[i]) S[s[0]] = res[i]; else missing.push(s[0]);
      });
      if (res[3]) S.history = S.history.concat(S.pend);
      S.failed = missing;
      UI.groupBuilds();
      rerender();
      loadNames();
      setStatus(missing.length ? `failed to load ${missing.join(", ")}` : "");
    });
  }

  // asks only for titles it has not been answered on
  function loadNames() {
    const ask = S.builds.map((b) => b.title).filter((t) => !(t in S.names));
    if (!ask.length) return;
    ask.forEach((t) => { S.names[t] = S.names[t] || null; });
    fetch(`${API}/short-titles`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ titles: ask }) })
      .then((r) => (r.ok ? r.json() : {})).catch(() => ({})).then((got) => {
        Object.assign(S.names, got);
        const b = S.cur && UI.buildOf(S.cur.slug);
        if (b) S.head.title = UI.nameOf(b);
        rerender();
      });
  }

  // ── selection ────────────────────────────────────────────────────────────

  // the top inbox row, so the page opens on what the list shows first
  function firstWaiting() { return UI.inboxRows()[0]; }

  /* push: true = new history entry (row click), false = replaceState (arrows, previous/next),
     null = leave the URL alone (popstate, first load). */
  function selectBuild(slug, stepKey, push) {
    const b = UI.buildOf(slug);
    if (!b) {
      clearSelection(); showEmpty(`not found: ${slug}`); setStatus(`not found: ${slug}`);
      if (isPhone()) shellEl().classList.add("is-detail");
      return;
    }
    const stages = UI.stagesOf(b).filter((x) => !x.disabled);
    if (S.hist) setHist(false, true);
    const key = stages.some((x) => x.key === stepKey) ? stepKey : UI.defaultStage(stages);
    const url = `?build=${encodeURIComponent(slug)}&step=${encodeURIComponent(key)}`;
    // wbFromList marks an entry pushed over the list, so the phone back can pop to it
    if (push && url !== location.search) history.pushState({ wbFromList: !new URLSearchParams(location.search).get("build") }, "", url);
    else if (push === false && url !== location.search) history.replaceState(history.state, "", url);
    S.cur = { slug: slug, key: key };
    S.idle = false;
    S.head = { sub: "", title: UI.nameOf(b), tip: b.title };
    renderRail();
    renderStage(b, key);
    S.empty.shown = false;
    if (isPhone() && !shellEl().classList.contains("is-detail")) {
      S.listScroll = window.scrollY;
      shellEl().classList.add("is-detail");
      window.scrollTo(0, 0);
      if (refs.headWrap) refs.headWrap.focus({ preventScroll: true });
    }
    rerender();
  }

  function clearSelection() {
    S.cur = null;
    S.walk = null;
    S.head = { sub: "", title: "", tip: S.head.tip };
    S.gen++;
    S.track = null;
    S.rail = null;
    S.cards = null;
    S.idle = false;
    rerender();
  }

  function showEmpty(text, sub) {
    S.empty = { text: text, sub: sub || "", shown: true };
    rerender();
  }

  // nothing selected (and nothing waiting to auto-open): one general placeholder card fills the main
  // column, with no head plate and no stage names, since what opens depends on the row he picks
  // (mark 224744 #2). The decision log keeps its placeholder slot. selectBuild repaints both.
  function showIdle() {
    clearSelection();
    S.idle = true;
    S.cards = { kind: "idle" };
    S.rail = { kind: "idle" };
    rerender();
  }

  // ── phone bar: back, N of M, previous / next over the list as drawn ───────

  /* A row key (see visibleKeys) to its page: an inbox row opens its build at its step, a marks session
     opens the walk-through, a build row opens the build at its default stage. */
  function selectRow(key, push) {
    const walk = /^mark:(.+):walk$/.exec(key), r = UI.inboxRows().filter((x) => x.key === key)[0];
    S.rowKey = r ? key : null;
    if (walk) {
      const url = `?walk=${encodeURIComponent(walk[1])}`;
      if (S.hist) setHist(false, true);
      if (push && url !== location.search) history.pushState({ wbFromList: !new URLSearchParams(location.search).get("build") }, "", url);
      else if (push !== true && url !== location.search) history.replaceState(history.state, "", url); // BuildList reads ?walk= for the active row
      showWalk(walk[1]);
    } else if (r) selectBuild(r.open.build, r.open.step, push);
    else selectBuild(key.replace(/^build:/, ""), null, push);
  }

  function stepBy(d) {
    const i = S.visible.indexOf(S.active);
    if (i >= 0 && S.visible[i + d] != null) selectRow(S.visible[i + d], false);
  }

  // phone back: leave the detail view, keep the open build, restore the list and its scroll
  function leaveDetail() {
    if (!shellEl().classList.contains("is-detail")) return;
    if (S.hist) setHist(false, true);
    shellEl().classList.remove("is-detail");
    requestAnimationFrame(() => {
      window.scrollTo(0, S.listScroll || 0);
      const row = S.active && $("entries").querySelector(`[data-key="${CSS.escape(S.active)}"]`);
      if (row) { row.focus({ preventScroll: true }); row.scrollIntoView({ block: "nearest" }); }
    });
  }

  function barBack() {
    // only pop when the entry behind this one is the list; a direct ?build= load has none
    if (history.state?.wbFromList) history.back();
    else { history.replaceState(null, "", location.pathname); leaveDetail(); }
  }

  // arrow keys on the list only, so the search box keeps its caret keys. A move selects
  // without a history entry; Enter/Space selects like a click.
  function onListKey(e) {
    const row = e.target.closest?.(".hub-e3p-entry");
    const ids = S.visible;
    if (!row || !ids.length) return;
    const cur = ids.indexOf(row.dataset.key);
    let n;
    if (e.key === "ArrowDown") n = Math.min(cur + 1, ids.length - 1);
    else if (e.key === "ArrowUp") n = Math.max(cur - 1, 0);
    else if (e.key === "Home") n = 0;
    else if (e.key === "End") n = ids.length - 1;
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectRow(ids[cur], true); return; }
    else return;
    e.preventDefault();
    if (n === cur) return;
    selectRow(ids[n], false);
    const next = $("entries").querySelector(`[data-key="${CSS.escape(ids[n])}"]`);
    next.focus({ preventScroll: true });
    next.scrollIntoView({ block: "nearest" });
  }

  // ── marks walk-through: ?walk=<session>, one card per fixed mark, his Close / Send back ──

  function showWalk(session) {
    clearSelection();
    const gen = S.gen;
    S.head = { sub: "Marks walk-through", title: session.slice(0, 10), tip: S.head.tip };
    rerender();
    if (isPhone()) {
      if (!shellEl().classList.contains("is-detail")) S.listScroll = window.scrollY;
      shellEl().classList.add("is-detail");
    }
    fetch(`/marks/api/walk?session=${encodeURIComponent(session)}`).then((r) => r.json()).then((d) => {
      if (gen !== S.gen) return;
      if (d.error) { showEmpty(d.error); return; }
      if (!d.marks.length) { showEmpty("nothing left to look at", "every mark in this round is closed"); return; }
      S.cards = { kind: "walk", gen: gen, session: session, marks: d.marks };
      // the head names the page(s) the marks are on; the date moves to the head's bottom strip
      S.head = { sub: "Marks walk-through", title: UI.walkPages(d.marks).join(", "), tip: session };
      S.walk = d;
      rerender();
      const n = d.marks.filter((m) => m.status === "fixed" && !S.markHeld[`${session}:${m.n}`]).length;
      setStatus(n ? `${n} marks waiting on you` : "not fixed yet, nothing to check");
    }).catch(() => { showEmpty("couldn't load the walk-through"); });
  }

  function fromUrl() {
    const q = new URLSearchParams(location.search), slug = q.get("build");
    if (q.get("walk")) { showWalk(q.get("walk")); return; }
    if (slug) { selectBuild(slug, q.get("step"), null); return; }
    if (isPhone()) { leaveDetail(); return; }
    const first = firstWaiting();
    if (first) selectRow(first.key, null); else showIdle();
  }

  /* Old links (?tab=spec&doc=, ?tab=plan&doc=, ?tab=options&set=) become ?build=&step= once the
     data is in. Returns true when the query named something and it was handled. */
  function oldLink(q) {
    const tab = q.get("tab"), doc = q.get("doc"), set = q.get("set");
    let hit = null, name = doc || set;
    if (doc && (tab === "spec" || tab === "plan")) {
      const rel = doc.replace(/^\//, "");
      const d = S[`${tab}s`].filter((x) => x.path === doc || x.path.endsWith(`/${rel}`))[0];
      hit = d && S.builds.filter((b) => b.steps.some((s) => s.path === d.path))[0];
      if (hit) selectBuild(hit.slug, tab, false);
      name = doc.split("/").pop();
    } else if (set && tab === "options") {
      hit = S.builds.filter((b) => b.steps.some((s) => s.kind === "design" && s.key === set))[0];
      if (hit) selectBuild(hit.slug, set, false);
    } else return false;
    if (!hit) { clearSelection(); showEmpty(`not found: ${name}`); setStatus(`not found: ${name}`); }
    return true;
  }

  Object.assign(UI, { isAt, reopen, refresh, redraw, selectBuild, selectRow });

  // ── the page ─────────────────────────────────────────────────────────────

  function Cards() {
    const c = S.cards;
    if (!c) return null;
    if (c.kind === "history") return <UI.HistoryView rows={c.rows} />;
    if (c.kind === "idle") return <UI.IdleCards />;
    if (c.kind === "walk") return c.marks.map((m) => <UI.WalkCard key={`${c.gen}-${m.n}`} session={c.session} m={m} />);
    return <UI.StageCards key={c.gen} stage={c} />;
  }

  function App() {
    UI.useStore();
    const list = UI.BuildList(); // also sets S.visible, which the phone bar reads
    const i = S.visible.indexOf(S.active);
    const stages = S.track ? S.track.stages : [];
    const done = stages.filter((x) => x.done).length;

    useEffect(() => {
      $("wb-root").setAttribute("data-react-mounted", "workbench");
      document.addEventListener("visibilitychange", onVisible);
      window.addEventListener("popstate", fromUrl);
      loadAll().then(() => {
        const q = new URLSearchParams(location.search);
        if (q.get("build") || q.get("walk")) fromUrl();
        else if (!oldLink(q)) {
          // no query: the top inbox row on desktop, the list alone on a phone
          const first = firstWaiting();
          if (first && !isPhone()) selectRow(first.key, null);
          else if (!isPhone()) showIdle();
          // a bare ?tab=spec|plan|options is the default view at a clean URL
          if (q.get("tab") && q.get("tab") !== "history") history.replaceState(null, "", location.pathname);
        }
        if (q.get("tab") === "history") setHist(true);
      });
      return () => {
        document.removeEventListener("visibilitychange", onVisible);
        window.removeEventListener("popstate", fromUrl);
      };
    }, []);

    return (
      <React.Fragment>
        <section className={`col hub-e3p-list-col${S.hist ? " wb-dim" : ""}`}>
          <div className="hub-e3p-tools">
            <div className="hub-lf"><div className="hub-lf-bar"><input type="search" id="search" className="hub-lf-search" placeholder="search builds" aria-label="search builds"
              onChange={(e) => { S.q = e.target.value; rerender(); }} /></div></div>
            <button type="button" className="hub-btn" id="historyToggle" aria-pressed={String(S.hist)} onClick={() => { setHist(!S.hist); }}><span>history</span></button>
          </div>
          {/* data-sb-out: the liquid scroll bar sits in the gap past the list, not over its counts (mark 224744 #1) */}
          <div className="hub-e3p-entries" id="entries" role="listbox" aria-label="builds" data-sb-out="" onKeyDown={onListKey}>{list}</div>
        </section>

        <section className="col hub-e3p-pane">
          <div className="hub-e3p-bar">
            <button type="button" className="hub-e3p-back" id="barBack" onClick={barBack}><span aria-hidden="true">‹</span> all builds</button>
            <span className="hub-e3p-pos" id="barPos">{i < 0 ? "–" : `${i + 1} / ${S.visible.length}`}</span>
            <button type="button" className="hub-e3p-nav" id="barPrev" aria-label="previous build" disabled={i <= 0} onClick={() => { stepBy(-1); }}>‹</button>
            <button type="button" className="hub-e3p-nav" id="barNext" aria-label="next build" disabled={i < 0 || i >= S.visible.length - 1} onClick={() => { stepBy(1); }}>›</button>
          </div>

          <div className="hub-split hub-e3p-split">
            <div className="hub-e3p-main">

              <div className="hub-e3p-head hub-plate-card">
                <div className="hub-e3p-head-row">
                  <span tabIndex={-1} ref={(el) => { refs.headWrap = el; }}><span className="hub-e3p-head-sub" id="headSub">{S.head.sub}</span><span className="hub-e3p-head-sep" aria-hidden="true"></span><span className="hub-e3p-head-t" id="headTitle" title={S.head.tip || undefined}>{S.head.title}</span></span>
                  <div className="hub-e3p-head-acts" id="headActs">
                    {S.track ? <span className={`hub-pill${done === stages.length ? " is-good" : ""}`}><em>{done}</em>{` of ${stages.length} approved`}</span> : null}
                    {S.walk && !S.hist ? <UI.WalkPill marks={S.walk.marks} /> : null}
                  </div>
                </div>
                {S.walk && !S.hist ? <UI.WalkHead walk={S.walk} /> : null}
                <div className="hub-tabs hub-e3p-stages" id="stages" hidden={S.hist || !S.track}>
                  {S.track ? <UI.StageTrack track={S.track} /> : null}
                </div>
                <UI.Carousel track={S.track} hist={S.hist} />
                {S.rail && S.rail.kind === "log" && !S.hist ? <UI.HeadLog rows={S.rail.rows} key={S.cur?.slug} /> : null}
              </div>

              <div className="hub-e3p-cards" id="cards">
                <Cards />
                <div className="hub-e3p-empty" id="empty" hidden={!S.empty.shown}>
                  {S.empty.text || S.empty.sub ? <React.Fragment><div className="wb-empty-t">{S.empty.text}</div><div className="wb-empty-x">{S.empty.sub}</div></React.Fragment> : null}
                </div>
              </div>
            </div>

            <section className="col hub-detail-rail hub-e3p-rail" id="rail">
              {S.rail ? (S.rail.kind === "idle" ? <UI.IdleRail /> : <UI.DecisionLog rows={S.rail.rows} />) : null}
            </section>
          </div>
        </section>
      </React.Fragment>
    );
  }

  // a render error leaves the template's own fallback visible instead of a blank page
  class Boundary extends React.Component {
    constructor(p) { super(p); this.state = { failed: false }; }
    static getDerivedStateFromError() { return { failed: true }; }
    componentDidCatch(e) { console.error("workbench render failed", e); }
    render() { return this.state.failed ? <div className="hub-error">page failed to load</div> : this.props.children; }
  }

  ReactDOM.createRoot($("wb-root")).render(<Boundary><App /></Boundary>);
})();
