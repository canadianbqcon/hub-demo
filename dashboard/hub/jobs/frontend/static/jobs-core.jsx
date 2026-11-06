/* Jobs · 1 of 5 (React): the shared vocabulary every other part reads. State object, status and
   category maps, the api wrapper, debounce, toast, the modal, the score model, and the read-locked
   textarea machinery. Ported from jobs-core.js.
   Creates window.JobsUI; the other four files (jobs-surfaces-a, jobs-surfaces-b, jobs-prep, jobs)
   assign into it and declare nothing at top level. The plain page re-drew by hand after each
   mutation; here the mutations are unchanged and bump() asks the App to draw again. The renderX()
   functions of the plain page keep their names where a call site still means "draw this again":
   they bump an epoch (a number in a React key, so the section is rebuilt the way clear() + rebuild
   did) or take the snapshot that section used to draw from. No async/await in this surface: Babel
   would hoist its helpers to the top level, so every flow is a promise chain. */
window.JobsUI = window.JobsUI || {};
(() => {
  const { useState, useEffect, useLayoutEffect, useRef, useReducer, useContext } = React;
  const U = window.JobsUI;

  if (typeof pdfjsLib !== "undefined") {
    pdfjsLib.GlobalWorkerOptions.workerSrc = "/static/vendor/pdfjs/pdf.worker.min.js";
  }

  // ── state ─────────────────────────────────────────────────────────────────────

  const S = {
    apps: [],
    current: null,          // full row + nested arrays from GET /applications/:id
    surface: "intake",      // current surface tab
    candidate: { positions: [], education: "", tools: "" },
    glossary: [],
    qaTemplate: [],
    baseResumes: [],
    positionToggles: {},    // {position_id: true|false}
    activeStepId: null,     // the prep step open in the pipeline
    stepView: null,         // {title, meta, step} as last drawn by renderActiveStep; null = none drawn
    pipeDrawn: false,       // renderPipeline has run at least once
    visibleIds: [],         // funnel rows as drawn, for arrow keys and the phone bar
    listScroll: 0,          // phone: list scroll saved when the detail view opens
    backPops: false,        // phone: a list entry sits behind the detail view
    // what the focus pane draws: "initial" is the template's own idle markup, "empty" is after a job
    // was deselected or deleted (title blank, tabs off), "app" has an open job
    focus: "initial",
    tabOn: "intake",        // the lit stage tab, or null
    shown: null,            // the surface body that is displayed, or null
    link: { text: "↗ posting", href: "#", off: true },   // the "open posting" link
    delOff: true,           // the focus bar's delete link is disabled
    title: null,            // {company, role} as last drawn by renderFocus
    metaMode: "static",     // the status strip: "static" (template idle), "empty" (cleared), "cells" (drawn)
    meta: null,             // {status, updated} as last drawn by renderMetaStrip
    glossMeta: "no terms detected",   // the glossary footer's count line as last drawn
    rail: null,             // {score, reqs, nice} snapshots taken by renderRail; null = idle
    pipe: null,             // [{status, label, order}] snapshot taken by renderRailPipeline
    detail: false,          // phone: the detail view is up (.is-detail)
    reviewOpen: false,      // the ready-to-send page is up
    review: { ready: [], needs: [], curId: null },
    readyPainted: false,    // paintReadyCounts has run at least once
    editing: new Set(),     // review: form field ids with their editor open
    paint: null,            // {rows, sort} the list filter last handed the funnel
    funnelVer: 0,           // bumped by renderFunnel so the filter recomputes
    railIdle: true,         // the template ships the rail muted until an application is picked
    pendingReveal: false,   // the next funnel paint should scroll the open row into view
    cursor: null,           // arrow-key row id that is selected but still loading
    // render epochs: a section whose plain renderX() cleared and rebuilt its DOM is keyed on one
    ep: { intake: 0, research: 0, application: 0, closed: 0, prepQ: 0, pipe: 0, step: 0, iv: 0,
          stories: 0, resumes: 0, qa: 0, review: 0, meta: 0 },
    snap: { intakeResearch: null, research: null, app: null, closed: null },
    dialog: null,           // the open modal: {kind: "newapp"} or {kind: "resume", isBase}
    exReqs: [],             // pending refreshExpandables requests, served after the next commit
  };

  const listeners = new Set();
  function bump() { listeners.forEach((fn) => { fn(); }); }
  // the App calls this once; every other component reads S during the App's render
  function useStore() {
    const [, setN] = useState(0);
    useEffect(() => {
      const fn = () => setN((n) => n + 1);
      listeners.add(fn);
      return () => { listeners.delete(fn); };
    }, []);
  }

  // ── constants ─────────────────────────────────────────────────────────────────

  const STATUS_LABELS = {
    intaking: "intaking",
    researching: "researching",
    applying: "applying",
    applied: "applied",
    interviewing: "interviewing",
    offer: "offer",
    rejected: "rejected",
    ignored: "ignored",
    closed: "closed",
  };

  // autopilot statuses that live in the ready-to-send view, never in the funnel list
  const PIPELINE_INTERNAL_STATUSES = ["sourced", "cut", "ready", "approved", "submitting", "manual", "manual_only", "unconfirmed"];

  const STATUS_PIP = {
    intaking: "researching",
    researching: "researching",
    applying: "applying",
    applied: "applying",
    interviewing: "interviewing",
    offer: "offer",
    rejected: "closed",
    ignored: "closed",
  };

  // funnel rail order: furthest-along on top, closed (rejected/ignored) sink to the bottom.
  // rows sort by this rank first, then by blended score descending within each rank.
  const STATUS_RANK = {
    offer: 0,
    interviewing: 1,
    applying: 2,
    applied: 2,
    researching: 3,
    intaking: 3,
    rejected: 4,
    ignored: 4,
  };
  const CLOSED_STATUSES = ["rejected", "ignored", "closed"];

  const RESEARCH_CATEGORIES = [
    {
      key: "role",
      label: "role",
      subs: [
        { key: "summary",     label: "summary",      intake: true },
        { key: "day_to_day",  label: "day to day",   intake: true },
        { key: "travel",      label: "travel",       intake: true },
        { key: "success",     label: "success" },
        { key: "customers",   label: "customers" },
        { key: "schedule",    label: "schedule" },
        { key: "tools",       label: "tools" },
        { key: "environment", label: "environment" },
      ],
    },
    {
      key: "company",
      label: "company",
      subs: [
        { key: "stage",   label: "stage",   intake: true },
        { key: "size",    label: "size",    intake: true },
        { key: "funding", label: "funding" },
        { key: "sites",   label: "sites" },
      ],
    },
    {
      key: "culture",
      label: "culture",
      subs: [
        { key: "vibe",            label: "vibe",            intake: true },
        { key: "looking_for",     label: "looking for",     intake: true },
        { key: "not_looking_for", label: "not looking for", intake: true },
        { key: "green_flags",     label: "green flags",     intake: true },
        { key: "red_flags",       label: "red flags",       intake: true },
        { key: "values",          label: "values" },
      ],
    },
    {
      key: "compensation",
      label: "compensation",
      subs: [
        { key: "base",       label: "base",       intake: true },
        { key: "equity",     label: "equity" },
        { key: "bonus",      label: "bonus" },
        { key: "comparison", label: "comparison" },
      ],
    },
    {
      key: "progression",
      label: "progression",
      subs: [
        { key: "internal_path", label: "internal path" },
        { key: "lateral",       label: "lateral moves" },
        { key: "tenure",        label: "tenure" },
      ],
    },
    {
      key: "benefits",
      label: "benefits",
      subs: [
        { key: "health",     label: "health" },
        { key: "retirement", label: "retirement" },
        { key: "time_off",   label: "time off" },
        { key: "perks",      label: "perks" },
      ],
    },
    {
      key: "process",
      label: "process",
      subs: [
        { key: "steps",    label: "steps" },
        { key: "rounds",   label: "rounds" },
        { key: "gating",   label: "gating" },
        { key: "timeline", label: "timeline" },
        { key: "referral", label: "referral" },
      ],
    },
    {
      key: "intel",
      label: "intel",
      subs: [
        { key: "insider",          label: "insider" },
        { key: "hypothesis",       label: "hypothesis" },
        { key: "tactical",         label: "tactical" },
        { key: "sample_questions", label: "sample questions" },
        { key: "unionization",     label: "unionization" },
      ],
    },
  ];

  const QA_TYPE_LABELS = {
    intro: "intro",
    motivation: "motivation",
    behavioral: "behavioral",
    situational: "situational",
    culture: "culture",
    ask_them: "questions for them",
    technical: "technical",
    curveball: "curveball",
  };

  const CLOSED_REASONS = [
    ["", "select"],
    ["weak_customer_signal", "weak customer signal"],
    ["technical_gap", "technical gap"],
    ["culture_mismatch", "culture mismatch"],
    ["comp_misalignment", "comp misalignment"],
    ["headcount_change", "headcount change"],
    ["candidate_withdrew", "candidate withdrew"],
    ["ineligible", "ineligible for the role"],
    ["no_reason_given", "no reason given"],
    ["offer_accepted", "offer accepted"],
  ];

  // ── toasts ────────────────────────────────────────────────────────────────────
  // Imperative on purpose: one element appended to <body>, outside the React root, the way the
  // plain page drew it (a toast has to outlive any re-render, including the page's own errors).

  let toastEl = null;
  let toastTimer = null;
  function toast(msg, kind) {
    if (!toastEl) {
      toastEl = document.createElement("div");
      toastEl.className = "hub-toast toast";
      document.body.appendChild(toastEl);
    }
    toastEl.className = "hub-toast toast";
    if (kind) toastEl.classList.add(kind);
    toastEl.textContent = msg;
    requestAnimationFrame(() => toastEl.classList.add("show"));
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove("show"), 1800);
  }

  // ── api ───────────────────────────────────────────────────────────────────────

  function api(method, url, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    return fetch(url, opts).then((res) => {
      if (res.status === 204) return null;
      if (!res.ok) {
        return res.text().catch(() => "").then((txt) => {
          console.error(`api ${method} ${url} ${res.status}`, txt);
          toast(`request failed (${res.status})`, "alert");
          throw new Error(`api ${res.status}`);
        });
      }
      const ct = res.headers.get("content-type") || "";
      if (ct.includes("application/json")) return res.json();
      return null;
    });
  }
  const apiGet = (u) => api("GET", u);
  const apiPost = (u, b) => api("POST", u, b);
  const apiPatch = (u, b) => api("PATCH", u, b);
  const apiDelete = (u) => api("DELETE", u);

  // ── debounce ──────────────────────────────────────────────────────────────────

  const debouncers = new Map(); // key -> { t, fn }
  function debounce(key, fn, ms) {
    if (debouncers.has(key)) clearTimeout(debouncers.get(key).t);
    debouncers.set(key, { fn, t: setTimeout(() => { debouncers.delete(key); fn(); }, ms) });
  }
  // Run every pending save now. selectApp calls this before switching jobs: a save that
  // fired later would read the new S.current.id and write the old job's text into it.
  function flushDebounced() {
    const pending = Array.from(debouncers.values());
    debouncers.clear();
    pending.forEach((d) => { clearTimeout(d.t); d.fn(); });
  }

  // ── date and score helpers ────────────────────────────────────────────────────

  function todayIso() { return new Date().toISOString().slice(0, 10); }
  // Staleness is computed server-side (jobs/db.py compute_staleness) because it needs
  // the process steps, which the funnel list payload does not otherwise carry. The old
  // client-side "updated > 7d" check fired on 14 of 15 rows: it measured the record's
  // last edit rather than the process's, and counted research rows that never started.
  function staleness(app) { return app.staleness || null; }
  // Same deal for the retro gap (jobs/db.py compute_retro_gap): a closed application
  // whose post-mortem is blank. The closeout fields were reachable all along and still
  // never got filled, because nothing surfaced the omission once the row sank to the
  // bottom of the rail.
  function retroGap(app) { return app.retro_gap || null; }

  function listingAge(dateStr) {
    if (!dateStr) return "—";
    const d = Math.floor((Date.now() - new Date(dateStr)) / 86400000);
    if (d < 0) return "—";
    if (d === 0) return "today";
    if (d === 1) return "1d ago";
    if (d < 30) return `${d}d ago`;
    if (d < 60) return "~1mo ago";
    return `${Math.floor(d / 30)}mo ago`;
  }

  function formatSalary(a) {
    const min = +a.salary_min || 0;
    const max = +a.salary_max || 0;
    if (!min && !max) return "—";
    if (min && max) return `$${(min / 1000).toFixed(0)}k · $${(max / 1000).toFixed(0)}k`;
    return `$${((min || max) / 1000).toFixed(0)}k`;
  }

  function compScore(app) {
    const mid = ((+app.salary_min || 0) + (+app.salary_max || 0)) / 2;
    if (!mid) return null;
    return Math.min(10, Math.round(mid / 10000));
  }
  function arrangementScore(arr) {
    const a = (arr || "").toLowerCase();
    if (a.includes("remote") || a === "wfh") return 10;
    if (a.includes("hybrid")) return 5;
    if (a.includes("onsite") || a.includes("on-site") || a.includes("in-person")) return 0;
    return null;
  }
  function cultureScore(app) {
    const vals = ["culture_rating", "culture_recommend", "culture_work_life"]
      .map((k) => +app[k]).filter((n) => !Number.isNaN(n) && n > 0);
    if (!vals.length) return null;
    // assume 0-5 rating, 0-100 recommend %, 0-5 wl. normalize to 0-10.
    const r = +app.culture_rating ? (+app.culture_rating * 2) : null;
    const rec = +app.culture_recommend ? (+app.culture_recommend / 10) : null;
    const wl = +app.culture_work_life ? (+app.culture_work_life * 2) : null;
    const norm = [r, rec, wl].filter((n) => n != null && !Number.isNaN(n));
    if (!norm.length) return null;
    return Math.round(norm.reduce((a, b) => a + b, 0) / norm.length);
  }
  function blendedScore(app) {
    const role = +app.score_role || 0;
    const comp = compScore(app);
    const cult = cultureScore(app);
    const arr = arrangementScore(app.work_arrangement);
    const compVal = comp == null ? 5 : comp;
    const cultVal = cult == null ? 5 : cult;
    const arrVal = arr == null ? 5 : arr;
    const blended = (role * 0.45) + (compVal * 0.25) + (cultVal * 0.15) + (arrVal * 0.15);
    return { blended: +blended.toFixed(1), role, comp, cult, arr };
  }

  // ── modal ─────────────────────────────────────────────────────────────────────
  // The plain openModal() built a backdrop on <body>; this is the same markup as a portal. A dialog
  // is {title, primary, secondary, onPrimary}; onPrimary returns (a promise of) true to close, and
  // anything else keeps the dialog open (the validation toasts).

  function closeDialog() { S.dialog = null; bump(); }

  function Modal({ title, primary, secondary, onPrimary, onSecondary, children }) {
    const close = closeDialog;
    return ReactDOM.createPortal(
      <div className="modal-backdrop open" onClick={(e) => { if (e.target === e.currentTarget) close(); }}>
        <div className="modal">
          <div className="modal-head">{title}</div>
          <div className="modal-body">{children}</div>
          <div className="modal-foot">
            <button className="hub-btn hub-btn--lg" type="button"
                    onClick={() => { if (onSecondary) onSecondary(); close(); }}>{secondary || "cancel"}</button>
            <button className="hub-btn hub-btn--lg primary" type="button"
                    onClick={() => { Promise.resolve(onPrimary ? onPrimary() : undefined).then((ok) => { if (ok) close(); }); }}>
              {primary || "save"}
            </button>
          </div>
        </div>
      </div>,
      document.body
    );
  }

  // ── read-locked textareas ─────────────────────────────────────────────────────
  // A box is read-only until its edit control is pressed: a plain click on the text never unlocks
  // it. The pencil (or, inside a headed plate card, the card's edit switch) enters edit; click-away
  // re-locks and re-collapses. Long read boxes collapse to ~2 rows and a click on one peeks it open.
  // Measuring needs the box visible, so a surface switch asks for refreshExpandables once the body is
  // shown (a display:none box reports scrollHeight 0). A box starts as a bare textarea and is wrapped
  // and locked the first time its surface asks, exactly like the plain ensureExpandable().

  const COLLAPSE_PX = 80;
  const CardCtx = React.createContext(null);
  const boxes = new Set();   // every mounted ExTa handle, for refreshExpandables

  // ask every box of `surface` to lock and measure itself once this render has committed
  function refreshExpandables(surface) {
    S.exReqs.push(surface);
    bump();
  }
  // the App calls this from a layout effect, after every commit
  function serveExpandRequests() {
    if (!S.exReqs.length) return;
    const wanted = S.exReqs.slice();
    S.exReqs.length = 0;
    boxes.forEach((h) => { if (wanted.indexOf(h.surface) !== -1) h.ensure(); });
  }

  function measureFull(t) {
    const prev = t.style.height;
    t.style.height = "auto";
    const full = t.scrollHeight;
    t.style.height = prev;
    return full;
  }

  /* props: id, cls (an extra class), surface, direct (a click enters edit, no pencil step), dynamic (built by a render
     rather than the template: sized while detached, i.e. 0px, until its surface refreshes),
     value + epoch (the record's text; a new epoch writes it into the box, like setVal),
     placeholder, label, style, onInput(read) (read() is the box's current text) */
  function ExTa(props) {
    const card = useContext(CardCtx);
    const own = !props.direct && card ? card : null;
    const [, force] = useReducer((n) => n + 1, 0);
    const ta = useRef(null);
    const m = useRef({ inited: false, editing: false, peek: false, expandable: false, collapsed: false,
                       cardEdit: false, orig: "", measure: false });
    const text = useRef(props.value == null ? "" : String(props.value));
    const [value, setValue] = useState(text.current);
    const propsRef = useRef(props);
    propsRef.current = props;
    const mm = m.current;

    function autoExpand() {
      const t = ta.current;
      if (!t || mm.collapsed) return;
      t.style.height = "auto";
      t.style.height = `${t.scrollHeight}px`;
    }
    function applyCollapse() {
      const t = ta.current;
      if (!t) return;
      const full = measureFull(t);
      if (full > COLLAPSE_PX) {
        mm.expandable = true;
        if (mm.peek) { mm.collapsed = false; t.style.height = `${full}px`; }
        else { mm.collapsed = true; t.style.height = ""; }
      } else {
        mm.expandable = false;
        mm.collapsed = false;
        t.style.height = `${full}px`;
      }
      force();
    }
    function setText(v) {
      text.current = v;
      setValue(v);
    }
    function enter() {
      mm.editing = true;
      mm.collapsed = false;
      ReactDOM.flushSync(force);
      autoExpand();
      if (ta.current) ta.current.focus();
    }
    function exit() {
      if (!mm.editing) return;
      mm.editing = false;
      ReactDOM.flushSync(force);
      applyCollapse();
    }
    function togglePeek() {
      if (mm.editing) return;                        // peek is a read-mode affordance only
      mm.collapsed = !mm.collapsed;
      if (mm.collapsed) { ta.current.style.height = ""; mm.peek = false; ReactDOM.flushSync(force); }
      else { mm.peek = true; ReactDOM.flushSync(force); ta.current.style.height = "auto"; ta.current.style.height = `${ta.current.scrollHeight}px`; }
    }
    const handle = useRef(null);
    if (!handle.current) {
      handle.current = {
        surface: props.surface,
        ensure() {
          if (mm.editing) return;
          if (!mm.inited) {
            mm.inited = true;
            if (own) mm.unreg = own.register(handle.current);
          }
          mm.measure = true;
          force();
        },
        enterCard() { mm.orig = text.current; mm.cardEdit = true; enter(); },
        finishCard(revert) {
          if (revert && text.current !== mm.orig) {
            ReactDOM.flushSync(() => { setText(mm.orig); force(); });
            if (propsRef.current.onInput) propsRef.current.onInput(() => text.current);
          }
          mm.cardEdit = false;
          exit();
        },
        focus() { if (ta.current) ta.current.focus(); },
      };
    }
    // registered in the layout phase so a box mounted by this commit is there when the App serves
    // the surface's refresh request
    useLayoutEffect(() => {
      boxes.add(handle.current);
      return () => { boxes.delete(handle.current); if (mm.unreg) mm.unreg(); };
    }, []);
    useLayoutEffect(() => {
      if (props.dynamic && ta.current) ta.current.style.height = "0px";   // autoExpand() on a detached node
    }, []);
    // measure once the wrapper and the read-only state are in the DOM
    useLayoutEffect(() => {
      if (mm.measure) { mm.measure = false; applyCollapse(); }
    });
    // a new epoch writes the record's text into the box (setVal), then sizes it
    const firstEpoch = useRef(true);
    useLayoutEffect(() => {
      if (firstEpoch.current) { firstEpoch.current = false; return; }
      const v = props.value == null ? "" : String(props.value);
      if (v === text.current) autoExpand();
      else { setText(v); }
    }, [props.epoch]);
    // typing grows the box (unless collapsed); so does any programmatic change
    const firstText = useRef(true);
    useLayoutEffect(() => {
      if (firstText.current) { firstText.current = false; return; }
      autoExpand();
    }, [value]);

    const cls = "field-textarea" + (props.cls ? ` ${props.cls}` : "") + (mm.expandable ? " expandable" : "") + (mm.collapsed ? " collapsed" : "")
      + (mm.editing ? " editing" : "");
    const box = (
      <textarea ref={ta} id={props.id} className={cls} style={props.style} placeholder={props.placeholder}
                aria-label={props.label} value={value} readOnly={mm.inited && !mm.editing}
                data-ex-init={mm.inited ? "1" : undefined} data-direct-edit={props.direct ? "1" : undefined}
                onChange={(e) => {
                  text.current = e.target.value;
                  setValue(e.target.value);
                  if (props.onInput) props.onInput(() => text.current);
                }}
                onClick={() => {
                  if (!mm.inited || mm.editing) return;
                  if (props.direct) enter();
                  else if (mm.expandable) togglePeek();
                }}
                onBlur={() => { if (mm.inited && !mm.cardEdit) exit(); }} />
    );
    if (!mm.inited) return box;
    return (
      <div className="ta-wrap">
        {box}
        {!own && (
          <button className="ta-btn ta-edit" type="button" title={mm.editing ? "done" : "edit"}
                  onMouseDown={(e) => e.preventDefault()}   // keep focus on the box when the button is clicked
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); if (mm.editing) ta.current.blur(); else enter(); }}>
            {mm.editing ? "✓" : "✎"}
          </button>
        )}
      </div>
    );
  }

  /* A plate card (workbench pick jobs-focus-edit-button C): one edit switch in the card's head that
     unlocks every locked box in the card at once; save re-locks them (typing already autosaves),
     cancel writes the text from before the edit back. The switch appears the first time a box in the
     card is locked. Boxes outside a headed plate card, and the direct-edit boxes, keep their own
     pencil. The head carries `extra` (a control that sits beside the title) when a card has one. */
  function Card({ cls, style, title, extra, children }) {
    const [mode, setMode] = useState(false);
    const [hasInit, setHasInit] = useState(false);
    const list = useRef([]);
    const app = useRef("");
    const ctx = useRef(null);
    if (!ctx.current) {
      ctx.current = {
        register(h) {
          list.current.push(h);
          setHasInit(true);
          return () => { list.current = list.current.filter((x) => x !== h); };
        },
      };
    }
    function edit() {
      app.current = String(S.current ? S.current.id : undefined);
      const bs = list.current;
      bs.forEach((h) => { h.enterCard(); });
      if (bs[0]) bs[0].focus();
      setMode(true);
    }
    function finish(revert) {
      // never write one job's text into another
      const same = String(S.current ? S.current.id : undefined) === app.current;
      list.current.forEach((h) => { h.finishCard(revert && same); });
      setMode(false);
    }
    return (
      <div className={`section hub-plate-card${cls ? ` ${cls}` : ""}`} style={style} data-edit-init={hasInit ? "1" : undefined}>
        <div className="section-head hub-section-head">
          <span className="section-title hub-section-head-t">{title}</span>
          {extra}
          {hasInit && (
            <span className="card-edit-acts">
              <button className="hub-section-head-act" type="button" hidden={mode} onClick={edit}>edit</button>
              <button className="hub-section-head-act" type="button" hidden={!mode} onClick={() => finish(true)}>cancel</button>
              <button className="hub-section-head-act card-edit-save" type="button" hidden={!mode} onClick={() => finish(false)}>save</button>
            </span>
          )}
        </div>
        <CardCtx.Provider value={ctx.current}>{children}</CardCtx.Provider>
      </div>
    );
  }

  /* An inline single-line editor that saves on blur: Enter blurs, Escape blurs (revert puts the
     value it opened with back first). Opens focused, text selected when it is a text box.
     onSave(value) runs from the blur. `type` is text, number or date. */
  function InlineEdit({ type, init, placeholder, label, revert, onSave }) {
    const ref = useRef(null);
    const [v, setV] = useState(init);
    useEffect(() => {
      ref.current.focus();
      if (ref.current.type === "text") ref.current.select();
    }, []);
    return (
      <input ref={ref} className="inline-edit" type={type || "text"} placeholder={placeholder} aria-label={label}
             value={v} onChange={(e) => setV(e.target.value)}
             onKeyDown={(e) => {
               if (e.key === "Enter") { e.preventDefault(); e.currentTarget.blur(); }
               if (e.key === "Escape") {
                 if (revert) ReactDOM.flushSync(() => setV(init));
                 e.currentTarget.blur();
               }
             }}
             onBlur={(e) => onSave(e.currentTarget.value)} />
    );
  }

  // the surface-body class every jobs surface uses, and a text box split into its non-blank lines
  const surfaceCls = (name) => `surface${S.shown === name ? " active" : ""}`;
  const linesOf = (v) => (v || "").split("\n").map((x) => x.trim()).filter(Boolean);

  Object.assign(U, {
    surfaceCls, linesOf,
    S, bump, useStore, api, apiGet, apiPost, apiPatch, apiDelete, debounce, flushDebounced, toast,
    STATUS_LABELS, PIPELINE_INTERNAL_STATUSES, STATUS_PIP, STATUS_RANK, CLOSED_STATUSES,
    RESEARCH_CATEGORIES, QA_TYPE_LABELS, CLOSED_REASONS,
    todayIso, staleness, retroGap, listingAge, formatSalary, blendedScore,
    Modal, closeDialog, ExTa, Card, InlineEdit, refreshExpandables, serveExpandRequests,
  });
})();
