/* Jobs · 5 of 5 (React): the app shell and the mount. Ported from jobs.js: boot, the funnel list and
   its filters, hash selection, the focus pane, the context rail, the new-application dialog, and the
   top-bar and footer bits the template owns outside the body root. Assigns into window.JobsUI and
   declares nothing at top level; it loads last because it ends by mounting.

   The body root is #body. The template's own markup inside it is a skeleton the React tree replaces
   on mount. The few nodes outside it (the topbar's needs-you pill, mode switch and new button, the
   footer clock, the .hub-e3p shell classes) stay the template's: React portals into the mode switch
   and otherwise only sets text, hidden and class on them, as the plain page did. */
(() => {
  const { useState, useEffect, useLayoutEffect, useRef, useMemo } = React;
  const U = window.JobsUI;
  const S = U.S;
  const bump = U.bump;

  // ── funnel: data, sorts, groups ────────────────────────────────────────────────

  // the sweep's autopilot statuses never reach the funnel list at all; dropped
  // before the list filter ever sees the rows, so they are never shown and never
  // counted against any stage's number.
  function filteredInternal(apps) {
    return apps.filter((a) => !U.PIPELINE_INTERNAL_STATUSES.includes(a.status));
  }

  // pipeline is the fixed order the funnel always used: furthest-along on top,
  // closed sinks to the bottom, blended score breaks ties within a stage.
  function pipelineCmp(a, b) {
    const ra = U.STATUS_RANK[a.status] == null ? 3 : U.STATUS_RANK[a.status];
    const rb = U.STATUS_RANK[b.status] == null ? 3 : U.STATUS_RANK[b.status];
    if (ra !== rb) return ra - rb;
    return U.blendedScore(b).blended - U.blendedScore(a).blended;
  }
  function scoreCmp(a, b) { return U.blendedScore(a).blended - U.blendedScore(b).blended; }
  function addedCmp(a, b) { return (a.created || "").localeCompare(b.created || ""); }
  function updatedCmp(a, b) { return (a.updated || "").localeCompare(b.updated || ""); }
  function companyCmp(a, b) { return (a.company || "").localeCompare(b.company || ""); }

  const FILTER_CFG = {
    key: "jobs",
    search: {
      placeholder: "company or role",
      fields: (a) => `${a.company || ""} ${a.role || ""} ${a.location || ""}`,
    },
    facet: {
      label: "stage",
      allLabel: "stages",
      options: [
        { key: "intaking", label: "intaking", match: (a) => a.status === "intaking" },
        { key: "researching", label: "researching", match: (a) => a.status === "researching" },
        { key: "applying", label: "applying", match: (a) => a.status === "applying" || a.status === "applied" },
        { key: "interviewing", label: "interviewing", match: (a) => a.status === "interviewing" },
        { key: "offer", label: "offer", match: (a) => a.status === "offer" },
        { key: "closed", label: "closed", match: (a) => U.CLOSED_STATUSES.includes(a.status) },
      ],
      defaultOn: ["intaking", "researching", "applying", "interviewing", "offer"],
    },
    sorts: [
      { key: "pipeline", label: "Pipeline", cmp: pipelineCmp },
      { key: "score", label: "Score", cmp: scoreCmp, dir: "desc" },
      { key: "added", label: "Newest Added", cmp: addedCmp, dir: "desc" },
      { key: "updated", label: "Recently Updated", cmp: updatedCmp, dir: "desc" },
      { key: "company", label: "Company A-Z", cmp: companyCmp },
    ],
    defaultSort: "pipeline",
  };

  // status groups, furthest along first (the order STATUS_RANK sorts by)
  const FUNNEL_GROUPS = [
    ["Offer", ["offer"]],
    ["Interviewing", ["interviewing"]],
    ["Applying", ["applying", "applied"]],
    ["Researching", ["researching"]],
    ["Intaking", ["intaking"]],
    ["Closed", ["rejected", "ignored"]],
  ];

  // The rows the list filter handed over, laid out as drawn: status group headings only make sense
  // under the pipeline sort; every other sort reads as one flat, already-ordered list.
  function funnelLayout(paint) {
    const items = [];
    const ids = [];
    if (!paint?.rows.length) return { items, ids };
    const place = (a) => { ids.push(a.id); items.push({ row: a }); };
    if (paint.sort === "pipeline") {
      // one head per status group, in the order the sort already puts them; anything unmapped lands in "Other"
      const groups = FUNNEL_GROUPS.map(([label, statuses]) => ({ label, statuses, rows: [] }));
      const other = { label: "Other", rows: [] };
      for (const a of paint.rows) (groups.find((g) => g.statuses.includes(a.status)) || other).rows.push(a);
      for (const g of groups.concat([other])) {
        if (!g.rows.length) continue;
        items.push({ group: g.label, n: g.rows.length });
        g.rows.forEach(place);
      }
    } else {
      paint.rows.forEach(place);
    }
    return { items, ids };
  }

  // ── funnel: load + render ──────────────────────────────────────────────────────

  function loadApplications() {
    return U.apiGet("/jobs/api/applications").then((apps) => {
      S.apps = apps || [];
      renderFunnel();
    });
  }

  // data-driven refresh: S.apps changed (load, patch, selection). It goes through the list filter so
  // search/stage/sort stay applied; reveal scrolls the open row into view, which a plain data refresh
  // (search keystroke, background patch) must not.
  function renderFunnel(reveal) {
    S.pendingReveal = !!reveal;
    S.cursor = null;
    S.funnelVer += 1;
    bump();
  }

  // select without adding a history entry (arrow keys, phone previous/next)
  function stepTo(id) {
    history.replaceState(null, "", `#app/${id}`);
    return selectApp(id);
  }

  // ── candidate profile + qa template + base resumes ─────────────────────────────

  function loadCandidate() {
    return U.apiGet("/jobs/api/candidate-profile").then((c) => { S.candidate = c || S.candidate; }, () => {});
  }
  function loadQaTemplate() {
    return U.apiGet("/jobs/api/interview-qa/template").then((t) => { S.qaTemplate = t || []; }, () => {});
  }
  function loadBaseResumes() {
    return U.apiGet("/jobs/api/resumes/base").then((r) => { S.baseResumes = r || []; }, () => { S.baseResumes = []; });
  }

  // one-time cleanup: the two rail chips the list filter replaced kept their on/off state under
  // these two keys; HubListFilter owns filter state under "hub.lf.jobs" now.
  function clearLegacyFunnelFilterKeys() {
    try {
      localStorage.removeItem("funnelActiveOnly");
      localStorage.removeItem("funnelShowClosed");
    } catch {}
  }

  // ── hash selection ─────────────────────────────────────────────────────────────

  const isPhone = () => matchMedia("(max-width: 900px)").matches;

  function hashSelect() {
    const ready = location.hash === "#ready";
    U.setReviewOpen(ready);
    if (ready) { showDetail(); return; }
    const m = location.hash.match(/^#app\/(\d+)/);
    if (m) { selectApp(+m[1]); return; }
    // phone Back (bar or browser): leave the detail view, keep the open job, restore the list
    if (!S.detail) return;
    S.detail = false;
    bump();
    requestAnimationFrame(() => {
      window.scrollTo(0, S.listScroll || 0);
      const row = S.current && document.querySelector(`#funnelList [data-id="${S.current.id}"]`);
      if (row) { row.focus({ preventScroll: true }); row.scrollIntoView({ block: "nearest" }); }
    });
  }

  // ── select app + render focus ──────────────────────────────────────────────────

  // last-wins: fast arrow keys or taps can resolve out of order, so only the latest call applies
  let selectSeq = 0;
  function selectApp(id) {
    const seq = ++selectSeq;
    U.flushDebounced();
    if (!id) { S.current = null; renderFocusEmpty(); renderFunnel(); return Promise.resolve(); }
    return U.apiGet(`/jobs/api/applications/${id}`).then((app) => {
      if (seq !== selectSeq || !app) return;
      S.current = app;
      // a click pushes one entry; a stepTo() already replaced the hash, so this is a no-op then
      const pushed = location.hash !== `#app/${id}`;
      // pushState fires no hashchange, so hashSelect does not re-enter selectApp for the same id
      if (pushed) history.pushState(null, "", `#app/${id}`);
      return Promise.all([loadGlossary(id), U.loadPositionToggles()]).then((got) => {
        if (seq !== selectSeq) return;
        S.glossary = got[0];
        renderFunnel(true);
        renderFocus();
        switchSurface(autoSurfaceFor(S.current), false);
        U.setReviewOpen(false);
        if (showDetail()) {
          S.backPops = pushed;
          const t = document.getElementById("focusTitle");
          if (t) t.focus({ preventScroll: true });
        }
      });
    }, () => {
      if (seq !== selectSeq) return;
      S.current = null;
      renderFocusEmpty();
    });
  }

  // phone: list to detail. True when it switched, the one moment the list scroll is worth saving.
  function showDetail() {
    if (!isPhone() || S.detail) return false;
    S.listScroll = window.scrollY;
    S.detail = true;
    window.scrollTo(0, 0);
    bump();
    return true;
  }

  function stepBy(d) {
    const ids = S.visibleIds || [];
    const i = S.current ? ids.indexOf(S.current.id) : -1;
    if (i >= 0 && ids[i + d] != null) stepTo(ids[i + d]);
  }

  // ── surface tabs ───────────────────────────────────────────────────────────────

  function switchSurface(name) {
    S.surface = name;
    S.tabOn = name;
    S.shown = name;
    U.refreshExpandables(name);   // measured once the body is displayed
  }

  function autoSurfaceFor() { return "intake"; }

  function renderSurfaceBodies() {
    U.renderIntake();
    U.renderResearch();
    U.renderApplication();
    U.renderPrep();
    U.renderClosed();
  }

  function renderFocusEmpty() {
    S.focus = "empty";
    S.shown = null;
    S.tabOn = null;
    S.metaMode = "empty";
    S.link = Object.assign({}, S.link, { off: true });
    S.delOff = true;
    setRailIdle(true);
  }

  // Nothing selected: mute the rail cards and swap their placeholders to one plain "select an
  // application" line instead of leaving live-looking values sitting there (they read as broken,
  // not at rest). Toggled off the moment an app is picked: renderRail() repopulates real content.
  function setRailIdle(idle) {
    S.railIdle = idle;
    bump();
  }

  function renderFocus() {
    const a = S.current;
    S.focus = "app";
    setRailIdle(false);
    S.title = { company: a.company || "(no company)", role: a.role || "(no role)" };
    const url = a.job_url || "";
    S.link = url ? { text: "Open posting", href: url, off: false } : { text: "no url", href: null, off: true };
    S.delOff = false;
    renderMetaStrip();
    renderRail();
    renderSurfaceBodies();
  }

  function renderMetaStrip() {
    const a = S.current;
    S.metaMode = "cells";
    S.meta = { status: U.STATUS_LABELS[a.status] || a.status, updated: a.updated || "—" };
    S.ep.meta += 1;
    bump();
  }

  function patchApp(patch) {
    if (!S.current) return Promise.resolve();
    const id = S.current.id;
    return U.apiPatch(`/jobs/api/applications/${id}`, patch).then((res) => {
      if (res) {
        // a reply for a job that is no longer open is not merged into the open one
        if (S.current && S.current.id === res.id) Object.assign(S.current, res);
        const i = S.apps.findIndex((x) => x.id === res.id);
        if (i >= 0) S.apps[i] = Object.assign({}, S.apps[i], res);
        U.syncReadyRow(res);
        renderFunnel();
      }
    });
  }

  // ── context rail ───────────────────────────────────────────────────────────────


  function renderRail() {
    const a = S.current;
    S.rail = { score: U.blendedScore(a), reqs: U.linesOf(a.requirements), nice: U.linesOf(a.nice_to_haves) };
    renderRailPipeline();
    renderRailGlossary();
  }

  function renderRailScore() {
    if (!S.current) return;
    S.rail = Object.assign({}, S.rail, { score: U.blendedScore(S.current) });
    bump();
  }

  function renderRailPipeline() {
    const steps = (S.current?.process_steps) || [];
    if (!steps.length) {
      S.pipe = { meta: "", steps: [] };
    } else {
      const done = steps.filter((s) => s.status === "complete").length;
      S.pipe = {
        meta: `${done}/${steps.length} complete`,
        steps: steps.map((s) => ({ status: s.status, label: s.label || `(step ${s.step_order + 1})` })),
      };
    }
    bump();
  }

  // returns the list; selectApp assigns it only if its selection is still the latest
  function loadGlossary(id) {
    return U.apiGet(`/jobs/api/applications/${id}/glossary`).then((g) => g || [], () => []);
  }

  function renderRailGlossary() {
    const terms = S.glossary || [];
    if (!terms.length) {
      S.glossMeta = "no terms detected";
    } else {
      const toLearn = terms.filter((t) => !t.known);
      const known = terms.filter((t) => t.known);
      S.glossMeta = `${toLearn.length} to learn · ${known.length} known`;
    }
    bump();
  }

  // ── components: funnel ─────────────────────────────────────────────────────────

  function FunnelRow({ a, on, tab }) {
    const stale = U.staleness(a);
    const retro = U.retroGap(a);
    // A row is never both: staleness only fires on live statuses, the retro gap only on closed ones.
    const flag = stale || retro;
    const label = U.STATUS_LABELS[a.status] || a.status;
    return (
      <div className={`hub-e3p-entry app-row${on ? " active" : ""}${stale ? ` stale stale-${stale.side}` : ""}${retro ? " needs-retro" : ""}`}
           data-id={String(a.id)} role="option" aria-selected={on ? "true" : "false"} tabIndex={tab ? 0 : -1}
           title={flag ? flag.reason : ""}
           aria-label={`${a.company || "(no company)"} · ${a.role || "(no role)"} · ${label}${flag ? ` · ${flag.reason}` : ""}`}
           onClick={() => selectApp(a.id)}>
        <span className="hub-e3p-entry-mark"><span className={`status-pip pip-${U.STATUS_PIP[a.status] || "researching"}`} title={label}></span></span>
        <span className="hub-e3p-entry-t app-row-co">{a.company || "(no company)"}</span>
        <span className="hub-e3p-entry-s app-row-role">{a.role || "(no role)"}</span>
        <span className="hub-e3p-entry-v app-row-prio" title="blended score">{U.blendedScore(a).blended.toFixed(1)}</span>
      </div>
    );
  }

  // arrow keys on the list only, so the search box and every textarea keep their caret keys.
  // A move selects without a history entry; Enter/Space selects like a click.
  function onListKey(e, list) {
    const row = e.target.closest?.(".hub-e3p-entry");
    const ids = S.visibleIds || [];
    if (!row || !ids.length) return;
    const cur = ids.indexOf(Number(row.dataset.id));
    let n;
    if (e.key === "ArrowDown") n = Math.min(cur + 1, ids.length - 1);
    else if (e.key === "ArrowUp") n = Math.max(cur - 1, 0);
    else if (e.key === "Home") n = 0;
    else if (e.key === "End") n = ids.length - 1;
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectApp(ids[cur]); return; }
    else return;
    e.preventDefault();
    if (n === cur) return;
    // move the cursor now, so fast repeats step from here and not from a row still loading
    S.cursor = ids[n];
    ReactDOM.flushSync(bump);
    const next = list.querySelector(`[data-id="${ids[n]}"]`);
    next.focus({ preventScroll: true });
    next.scrollIntoView({ block: "nearest" });
    stepTo(ids[n]);
  }

  function Funnel({ layout }) {
    const rows = useMemo(() => filteredInternal(S.apps), [S.funnelVer]);
    const list = useRef(null);
    const hadFocus = useRef(false);
    // read before this render commits: did the list own the focus when its rows were replaced
    hadFocus.current = !!list.current && list.current.contains(document.activeElement);
    const curId = S.cursor != null ? S.cursor : (S.current ? S.current.id : undefined);
    const tabId = layout.ids.indexOf(curId) !== -1 ? curId : layout.ids[0];

    // draws what the filter handed over; the open row scrolls into view only for a new selection
    useLayoutEffect(() => {
      const p = S.paint;
      if (!p || !list.current) return;
      const active = list.current.querySelector(".hub-e3p-entry.active");
      const tabRow = list.current.querySelector('.hub-e3p-entry[tabindex="0"]');
      if (hadFocus.current && tabRow) tabRow.focus({ preventScroll: true });
      if (p.reveal && active) active.scrollIntoView({ block: "nearest" });
    }, [S.paint]);

    return (
      <React.Fragment>
        <div className="funnel-summary hub-e3p-tools">
          <window.HubUI.ListFilter id="funnelFilter" cfg={FILTER_CFG} rows={rows}
                                   onChange={(fstate, result) => {
                                     S.paint = { rows: result.rows, sort: fstate.sort, reveal: S.pendingReveal };
                                     S.pendingReveal = false;
                                     bump();
                                   }} />
        </div>

        <div className="funnel-list hub-e3p-entries" id="funnelList" role="listbox" aria-label="applications" ref={list}
             onKeyDown={(e) => onListKey(e, list.current)}>
          {S.paint && !S.paint.rows.length ? (
            <div className="funnel-empty">{S.apps.length
              ? "no applications match · clear the search or turn a stage on"
              : "no applications yet · use the new application action to add one"}</div>
          ) : null}
          {layout.items.map((it) => it.group
            ? <div className="hub-e3p-group" role="presentation" key={`g-${it.group}`}>{it.group}<span className="hub-e3p-group-n">{String(it.n)}</span></div>
            : <FunnelRow a={it.row} on={it.row.id === curId} tab={it.row.id === tabId} key={it.row.id} />)}
        </div>
      </React.Fragment>
    );
  }

  function ReadyRow() {
    const waiting = U.waitingRows().length;
    const k = S.review.needs.length;
    const painted = S.readyPainted;
    return (
      <button type="button" className="funnel-ready-row" id="readyRow" onClick={openReady}>
        <span className="frr-n" id="readyRowCount">{painted ? String(waiting) : "0"}</span>
        <span className="frr-t">ready to send <span aria-hidden="true">›</span></span>
        <span className="frr-s" id="readyRowSub">
          {painted ? ([waiting && `${waiting} waiting for your ok`, k && `${k} need you`].filter(Boolean).join(" · ") || "nothing waiting") : ""}
        </span>
      </button>
    );
  }

  function openReady() {
    if (location.hash !== "#ready") { history.pushState(null, "", "#ready"); S.backPops = true; }
    hashSelect();
  }

  // ── components: focus pane ─────────────────────────────────────────────────────

  const STAGE_OF = {
    intaking: "intake", researching: "research", applying: "application", applied: "application",
    interviewing: "prep", offer: "prep", rejected: "closed", ignored: "closed",
  };
  const STAGES = [
    ["intake", "decide"], ["research", "context"], ["application", "tailor"], ["prep", "interviews"], ["closed", "post-mortem"],
  ];

  // the stage track: stages passed are done, the one the job sits at is now. Closed is set apart
  // and only ever "now" (how far a closed job got is not recorded). An unknown status marks nothing.
  function StageTabs() {
    const now = S.current ? STAGE_OF[S.current.status] : null;
    const at = STAGES.findIndex((t) => t[0] === now);
    return (
      <div className="hub-tabs surface-tabs hub-e3p-stages" id="surfaceTabs">
        {STAGES.map(([name, sub], i) => (
          <button type="button" key={name}
                  className={`hub-tab surface-tab${name === "closed" ? " is-apart" : ""}${S.tabOn === name ? " active" : ""}${i === at ? " is-now" : ""}${now !== "closed" && at >= 0 && i < at ? " is-done" : ""}`}
                  data-surface={name} onClick={() => switchSurface(name, true)}>
            <span className="hub-e3p-stage-dot" aria-hidden="true"></span>{name}<span className="stub hub-e3p-stage-sub">{sub}</span>
          </button>
        ))}
      </div>
    );
  }

  function FocusHead() {
    const f = S.focus;
    return (
      <div className="focus-head hub-e3p-head" id="focusHead">
        <div className="focus-head-top hub-e3p-head-row">
          <span className={`focus-title${f === "app" ? "" : " focus-title-placeholder"}`} id="focusTitle" tabIndex={-1}>
            {f === "initial" ? "no application selected" : f === "empty" ? "" : (
              <React.Fragment>
                <span className="hub-e3p-head-sub">{S.title.company}</span>
                <span className="hub-e3p-head-sep" aria-hidden="true">·</span>
                <span className="hub-e3p-head-t">{S.title.role}</span>
              </React.Fragment>
            )}
          </span>
          <div className="focus-actions hub-e3p-head-acts">
            <a className={`focus-action${S.link.off ? " disabled" : ""}`} id="focusOpenUrl" href={S.link.href == null ? undefined : S.link.href}
               target="_blank" rel="noopener">{S.link.text}</a>
            {/* biome-ignore lint/a11y/useValidAnchor: styled as a header action link; onClick calls preventDefault and runs a confirmed delete */}
            <a className={`focus-action alert${S.delOff ? " disabled" : ""}`} id="focusDelete" href="#"
               onClick={(e) => {
                 // an href="#" link: without this a cancelled confirm still clears the hash and drops the phone detail view
                 e.preventDefault();
                 if (!S.current) return;
                 if (!confirm(`delete ${S.current.company} · ${S.current.role}?`)) return;
                 return U.apiDelete(`/jobs/api/applications/${S.current.id}`).then(() => {
                   S.current = null;
                   location.hash = "";
                   return loadApplications();
                 }).then(() => {
                   renderFocusEmpty();
                   U.toast("application deleted");
                 });
               }}>Delete</a>
          </div>
        </div>
        <U.ReviewBar />
        <StageTabs />
      </div>
    );
  }

  // the status editor: moved out of the head (head pick B has no room)
  function MetaCell({ field, label, value, editable }) {
    const [editing, setEditing] = useState(false);
    const text = value;
    const init = text === "—" ? "" : text;
    function save(v) {
      const patch = {};
      patch[field] = v;
      return patchApp(patch).then(() => renderMetaStrip());
    }
    const open = () => { if (!editing) setEditing(true); };
    // an editable cell is a button: click, Enter or Space opens the editor. Only keys aimed at the
    // cell itself count: Enter in the open editor bubbles here, and reopening it with the old value
    // made the save that followed write the old status back.
    const onKeyDown = editable ? (e) => {
      if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); open(); }
    } : undefined;
    return (
      // biome-ignore lint/a11y/useAriaPropsSupportedByRole: aria-label is only set when role="button" is set (both keyed on `editable`)
      <div className={`meta-cell${editable ? " editable" : ""}`} data-field={field}
           role={editable ? "button" : undefined} tabIndex={editable ? 0 : undefined}
           aria-label={editable ? `edit ${label}` : undefined} onClick={editable ? open : undefined} onKeyDown={onKeyDown}>
        <div className="meta-cell-label">{label}</div>
        <div className="meta-cell-value">
          {editing ? <U.InlineEdit init={init} revert={true} label={field.replace(/_/g, " ")} onSave={save} /> : text}
        </div>
      </div>
    );
  }

  function MetaStrip() {
    return (
      <div className="focus-meta-strip rail-card" id="focusMetaStrip">
        {S.metaMode === "static" ? (
          <React.Fragment>
            <div className="focus-meta-cell"><span className="focus-meta-cell-l">status</span><span className="focus-meta-cell-v empty" data-cell="status">—</span></div>
            <div className="focus-meta-cell"><span className="focus-meta-cell-l">last update</span><span className="focus-meta-cell-v empty" data-cell="updated">—</span></div>
          </React.Fragment>
        ) : S.metaMode === "cells" ? (
          <React.Fragment key={S.ep.meta}>
            <MetaCell field="status" label="status" value={S.meta.status} editable={true} />
            <MetaCell field="updated" label="updated" value={S.meta.updated} editable={false} />
          </React.Fragment>
        ) : null}
      </div>
    );
  }

  // ── components: context rail ───────────────────────────────────────────────────

  function RailScore() {
    const s = S.rail ? S.rail.score : null;
    const items = s ? [["role", s.role, 45], ["comp", s.comp, 25], ["culture", s.cult, 15], ["arrange", s.arr, 15]]
      : [["role", null, 45], ["comp", null, 25], ["culture", null, 15], ["arrange", null, 15]];
    return (
      <div className="rail-card" id="railScore">
        <div style={{ display: "flex", alignItems: "baseline", gap: "11px" }}>
          <span className={`score-big${s ? "" : " empty"}`} id="railScoreBig">{s ? s.blended.toFixed(1) : "—"}</span>
          <span className="score-meta" id="railScoreMeta">{s ? "/ 10 · blended" : "/ 10 · no app selected"}</span>
        </div>
        <div className="score-rows" id="railScoreRows">
          {items.map(([label, val, weight]) => {
            const has = typeof val === "number";
            const pct = has ? Math.max(0, Math.min(100, val * 10)) : 0;
            return (
              <div className="score-row" key={label}>
                <span className="score-l">{label}<span className="score-w">{`${weight}%`}</span></span>
                <div className="hub-track score-track">
                  <div className={has ? "hub-bar score-fill" : "hub-bar score-fill empty"} style={{ width: `${pct}%` }}></div>
                </div>
                <span className={has ? "score-n" : "score-n empty"}>{has ? val.toFixed(1) : "—"}</span>
              </div>
            );
          })}
        </div>
        <span className="score-key">tick = 8, strong</span>
      </div>
    );
  }

  function ReqRows({ lines, empty }) {
    if (S.railIdle || !S.rail) return <div className="rail-empty">select an application</div>;
    if (!lines.length) return <div className="req-empty">{empty}</div>;
    return (
      <React.Fragment>
        {lines.map((r, i) => (
          <div className="req-row" key={i}>
            <div className="req-pip"></div>
            <div className="req-text">{r}</div>
          </div>
        ))}
      </React.Fragment>
    );
  }

  function RailPipeline() {
    if (S.railIdle || !S.pipe) return <div className="rail-empty">select an application</div>;
    if (!S.pipe.steps.length) return <div className="req-empty">no steps yet</div>;
    return (
      <React.Fragment>
        {S.pipe.steps.map((s, i) => (
          <div className={`rail-step ${s.status}`} key={i}>
            <div className="rail-step-pip"></div>
            <div className="rail-step-label">{s.label}</div>
          </div>
        ))}
      </React.Fragment>
    );
  }

  // One glossary term card. Click body toggles known (to-learn ⇄ known).
  // In the known section, the ✕ button permanently forgets the term (second confirm).
  function GlossaryCard({ t, isKnown }) {
    const toggleKnown = (e) => {
      if (e.target.closest?.(".glossary-forget")) return;
      return U.apiPatch(`/jobs/api/glossary/${t.id}`, { known: !t.known }).then((updated) => {
        if (updated) { t.known = updated.known; renderRailGlossary(); }
      });
    };
    return (
      <div className={`glossary-def${isKnown ? " known" : ""}`}
           title={isKnown ? "click to move back to ‘to learn’" : "click to mark known"}
           role="checkbox" tabIndex={0} aria-checked={String(isKnown)}
           onClick={toggleKnown}
           onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleKnown(e); } }}>
        <div className="glossary-def-term">{t.term}</div>
        <div className="glossary-def-text">{(t.definition || "").trim() || "no definition recorded"}</div>
        {isKnown ? (
          <button className="glossary-forget" type="button" title="remove — delete permanently"
                  onClick={(e) => {
                    e.stopPropagation();
                    return U.apiDelete(`/jobs/api/glossary/${t.id}`).then((res) => {
                      if (res) { S.glossary = (S.glossary || []).filter((x) => x.id !== t.id); renderRailGlossary(); }
                    });
                  }}>✕</button>
        ) : null}
      </div>
    );
  }

  function RailGlossary() {
    const terms = S.glossary || [];
    if (S.railIdle || !S.rail) return <div id="railGlossary" className="glossary-empty">select an application</div>;
    if (!terms.length) {
      return <div id="railGlossary" className="glossary-empty"><div>terms surface here as you fill in research and intake</div></div>;
    }
    const toLearn = terms.filter((t) => !t.known);
    const known = terms.filter((t) => t.known);
    return (
      <div id="railGlossary" className="glossary-defs">
        {toLearn.map((t) => <GlossaryCard t={t} isKnown={false} key={t.id} />)}
        {known.length ? (
          <div className="glossary-known-head">
            <span className="glossary-known-l">known · learned</span>
            <span className="glossary-known-meta">✕ to remove</span>
          </div>
        ) : null}
        {known.map((t) => <GlossaryCard t={t} isKnown={true} key={t.id} />)}
      </div>
    );
  }

  function Rail() {
    return (
      <section className={`col${S.railIdle ? " rail-idle" : ""} hub-detail-rail hub-e3p-rail`} id="contextRail">

        <div className="panel">
          <div className="panel-head">
            <h2 className="panel-title">status</h2>
          </div>
          <MetaStrip />
        </div>

        <div className="panel">
          <div className="panel-head">
            <h2 className="panel-title">01 — score</h2>
          </div>
          <RailScore />
        </div>

        <div className="panel">
          <div className="panel-head">
            <h2 className="panel-title">02 — requirements</h2>
          </div>
          <div className="rail-card tight" id="railRequirements"><ReqRows lines={S.rail ? S.rail.reqs : []} empty="no requirements logged" /></div>
        </div>

        <div className="panel">
          <div className="panel-head">
            <h2 className="panel-title">03 — nice to have</h2>
          </div>
          <div className="rail-card tight" id="railNiceToHave"><ReqRows lines={S.rail ? S.rail.nice : []} empty="no nice-to-haves logged" /></div>
        </div>

        <div className="panel">
          <div className="panel-head">
            <h2 className="panel-title">04 — pipeline</h2>
            <span className="panel-meta" id="railPipelineMeta">{S.pipe ? S.pipe.meta : "no steps"}</span>
          </div>
          <div className="rail-card tight" id="railPipeline"><RailPipeline /></div>
        </div>

        <div className="glossary-footer">
          <div className="glossary-head">
            <span className="glossary-l">05 — glossary</span>
            <span className="glossary-meta" id="railGlossaryMeta">{S.glossMeta}</span>
          </div>
          <RailGlossary />
        </div>

      </section>
    );
  }

  // the rail splitter drags the context rail between 300 and 640px wide
  function Splitter() {
    const [dragging, setDragging] = useState(false);
    const on = useRef(false);
    useEffect(() => {
      const move = (e) => {
        if (!on.current) return;
        const w = Math.max(300, Math.min(640, window.innerWidth - e.clientX));
        document.documentElement.style.setProperty("--rail-w", `${w}px`);
      };
      const up = () => {
        if (!on.current) return;
        on.current = false;
        setDragging(false);
        document.body.style.cursor = "";
      };
      document.addEventListener("mousemove", move);
      document.addEventListener("mouseup", up);
      return () => { document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up); };
    }, []);
    return (
      <div className={`splitter-v${dragging ? " dragging" : ""}`} id="splitter"
           onMouseDown={(e) => {
             e.preventDefault();
             on.current = true;
             setDragging(true);
             document.body.style.cursor = "col-resize";
           }}></div>
    );
  }

  // ── new application dialog ─────────────────────────────────────────────────────

  function NewAppDialog() {
    const company = useRef(null), role = useRef(null), url = useRef(null), source = useRef(null);
    return (
      <U.Modal title="new application" primary="create"
               onPrimary={() => {
                 if (!company.current.value.trim() || !role.current.value.trim()) { U.toast("company and role required", "alert"); return false; }
                 return U.apiPost("/jobs/api/applications", {
                   company: company.current.value, role: role.current.value, job_url: url.current.value, source: source.current.value,
                   status: "intaking",
                 }).then((created) => {
                   if (!created) return true;
                   return loadApplications().then(() => selectApp(created.id)).then(() => {
                     U.toast("application created");
                     return true;
                   });
                 });
               }}>
        <div>
          <div className="hub-field field"><label htmlFor="njf-company">company</label>
            <input id="njf-company" ref={company} className="field-input" type="text" placeholder="company" aria-label="company" /></div>
          <div className="hub-field field"><label htmlFor="njf-role">role</label>
            <input id="njf-role" ref={role} className="field-input" type="text" placeholder="role" aria-label="role" /></div>
          <div className="hub-field field"><label htmlFor="njf-url">url</label>
            <input id="njf-url" ref={url} className="field-input" type="text" placeholder="job posting url" aria-label="job posting url" /></div>
          <div className="hub-field field"><label htmlFor="njf-source">source</label>
            <input id="njf-source" ref={source} className="field-input" type="text" placeholder="source (linkedin, indeed, referral…)" aria-label="source" /></div>
        </div>
      </U.Modal>
    );
  }

  // ── template-owned bits outside the body root ──────────────────────────────────

  const byId = (id) => document.getElementById(id);

  // the top bar's mode switch is portaled into its own nav; the static buttons it held are cleared
  // first (the node itself is moved into the bar by topbar.jsx, which does not matter to a portal)
  // both mounts are React's own nodes now: the Pipeline column's header, and the Ready to send
  // page's top line (that page hides the Pipeline column, so the switch back lives there too)
  function Modes() {
    const waiting = U.waitingRows().length;
    const k = S.review.needs.length;
    const switchTo = (mode) => {
      if (mode === "ready") return openReady();
      const back = S.current ? `#app/${S.current.id}` : location.pathname + location.search;
      history.pushState(null, "", back);
      hashSelect();
    };
    const buttons = (withId) => (
      <React.Fragment>
        <button type="button" className={`jobs-mode${S.reviewOpen ? "" : " active"}`} data-mode="pipeline" onClick={() => switchTo("pipeline")}>Pipeline</button>
        <button type="button" className={`jobs-mode${S.reviewOpen ? " active" : ""}`} data-mode="ready" onClick={() => switchTo("ready")}>Ready to send <span className="jobs-mode-n" id={withId ? "readyModeCount" : undefined}>{String(S.readyPainted ? waiting + k : 0)}</span></button>
      </React.Fragment>
    );
    const main = byId("jobsModes"), rts = byId("rtsModes");
    // both mounts are drawn by this same render pass, so they exist only after it: look again once
    const [, again] = useState(0);
    useLayoutEffect(() => { if (byId("jobsModes") !== main || byId("rtsModes") !== rts) again((n) => n + 1); });
    return <React.Fragment>
      {main ? ReactDOM.createPortal(buttons(true), main) : null}
      {rts ? ReactDOM.createPortal(buttons(false), rts) : null}
    </React.Fragment>;
  }

  function Chrome() {
    // the needs-you pill and the .hub-e3p shell classes are the template's nodes: set, never owned
    useLayoutEffect(() => {
      const shell = document.querySelector(".hub-e3p");
      if (shell) {
        shell.classList.toggle("is-detail", S.detail);
        shell.classList.toggle("is-ready-page", S.reviewOpen);
      }
      if (S.readyPainted) {
        const pill = byId("needsYouPill");
        const k = S.review.needs.length;
        if (pill) { pill.hidden = k === 0; pill.textContent = `${k} need you`; }
      }
    });
    useEffect(() => {
      const btn = byId("newAppBtn");
      const open = () => { S.dialog = { kind: "newapp" }; bump(); };
      if (btn) btn.addEventListener("click", open);
      // cmd+k / ctrl+k lands in the funnel search; the review page answers its own keys
      const onKey = (e) => {
        if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
          e.preventDefault();
          const s = document.querySelector("#funnelFilter .hub-lf-search");
          if (s) { s.focus(); s.select(); }
        }
      };
      document.addEventListener("keydown", onKey);
      document.addEventListener("keydown", U.reviewKey);
      // another tab (or the submit worker) may have moved rows while this one sat idle
      const onFocus = () => U.loadReady();
      window.addEventListener("focus", onFocus);
      return () => {
        if (btn) btn.removeEventListener("click", open);
        document.removeEventListener("keydown", onKey);
        document.removeEventListener("keydown", U.reviewKey);
        window.removeEventListener("focus", onFocus);
      };
    }, []);
    return null;
  }

  // ── the page ───────────────────────────────────────────────────────────────────

  const root = byId("body");

  function boot() {
    // light/dark surface is owned end-to-end by theme-switch.js (build + click + persist); the
    // no-flash <head> snippet seeds it pre-paint. Nothing to wire here.
    clearLegacyFunnelFilterKeys();
    return Promise.all([
      loadCandidate(),
      loadQaTemplate(),
      loadBaseResumes(),
      loadApplications(),
      U.loadReady(),
    ]).then(() => {
      hashSelect();
      window.addEventListener("hashchange", hashSelect);
    });
  }

  function App() {
    U.useStore();
    const layout = funnelLayout(S.paint);
    S.visibleIds = layout.ids;
    const ids = layout.ids;
    const i = S.current ? ids.indexOf(S.current.id) : -1;
    useLayoutEffect(() => { U.serveExpandRequests(); });
    useEffect(() => {
      root.setAttribute("data-react-mounted", "jobs");
      boot();
    }, []);
    return (
      <React.Fragment>
        <section className="col hub-e3p-list-col" id="funnelCol">
          <Funnel layout={layout} />
          <ReadyRow />
          {/* view switch and needs-you count sit at the bottom of the rail (mark 2026-11-03-180641:3) */}
          <div className="funnel-col-header funnel-col-foot">
            <nav className="jobs-modes" id="jobsModes" aria-label="view"></nav>
            <span className="hub-pill is-alert crumb-pill" id="needsYouPill" hidden></span>
          </div>
        </section>

        <section className="col hub-e3p-pane">

          {/* phone only: back to the list, position, previous / next */}
          <div className="hub-e3p-bar">
            <button type="button" className="hub-e3p-back" id="e3pBack"
                    onClick={() => {
                      // a direct load of #app/<id> has no list entry behind it to go back to
                      if (S.backPops) history.back();
                      else { history.replaceState(null, "", location.pathname + location.search); hashSelect(); }
                    }}><span aria-hidden="true">‹</span> all jobs</button>
            <span className="hub-e3p-pos" id="e3pPos">{S.paint ? (i < 0 ? "–" : `${i + 1} of ${ids.length}`) : "–"}</span>
            <button type="button" className="hub-e3p-nav" id="e3pPrev" aria-label="previous job" disabled={S.paint ? i <= 0 : undefined}
                    onClick={() => stepBy(-1)}>‹</button>
            <button type="button" className="hub-e3p-nav" id="e3pNext" aria-label="next job" disabled={S.paint ? (i < 0 || i >= ids.length - 1) : undefined}
                    onClick={() => stepBy(1)}>›</button>
          </div>

          <div className="hub-split hub-e3p-split">
            <div className={`focus hub-e3p-main${S.reviewOpen ? " is-review" : ""}`}>

              <FocusHead />

              <div className="focus-body hub-e3p-cards" id="focusBody">

                {/* empty state when no app selected */}
                <div className="focus-empty-state hub-e3p-empty" id="focusEmptyState" style={{ display: S.focus === "app" ? "none" : "" }}>
                  <div className="focus-empty-icon">✦</div>
                  <div className="focus-empty-title">select an application</div>
                  <div className="focus-empty-text">pick a row from the funnel rail on the left, or click <em>+ new</em> in the top bar to start a new application.</div>
                </div>

                <U.IntakeSurface />
                <U.ResearchSurface />
                <U.ApplicationSurface />
                <U.PrepSurface />
                <U.ClosedSurface />

              </div>

              {/* autopilot review: needs-you cards over the one-at-a-time ready deck */}
              <U.ReviewView />
            </div>

            <Splitter />

            <Rail />
          </div>
        </section>

        {S.dialog && S.dialog.kind === "newapp" ? <NewAppDialog /> : null}
        {S.dialog && S.dialog.kind === "resume" ? <U.ResumeDialog isBase={S.dialog.isBase} /> : null}
        <Modes />
        <Chrome />
      </React.Fragment>
    );
  }

  // Render errors land here; async/handler errors are caught where they happen.
  class Boundary extends React.Component {
    constructor(p) { super(p); this.state = { err: null }; }
    static getDerivedStateFromError(err) { return { err }; }
    componentDidCatch(err) { console.error("[jobs] render failed", err); }
    render() { return this.state.err ? <div className="hub-error">page failed to load</div> : this.props.children; }
  }

  Object.assign(U, {
    patchApp, selectApp, loadApplications, renderFunnel, renderFocusEmpty, hashSelect, switchSurface, loadGlossary,
    renderRailPipeline, renderRailScore, renderSurfaceBodies,
  });

  ReactDOM.createRoot(root).render(<Boundary><App /></Boundary>);
})();
