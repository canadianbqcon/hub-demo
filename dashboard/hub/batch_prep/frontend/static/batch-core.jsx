/* J&Co batch prep · 1 of 3 (React): the shared mutable state, the API wrapper and every load and
   write that is not storage-map editing. Ported from batch.js (the DOM wiring half).
   Creates window.BatchUI; the other two files assign into it and declare nothing at top level.
   The plain page painted by hand after each change; here the logic is unchanged and bump() asks
   the App to draw again from S. The pure scaling engine is batch.js (node-tested), loaded
   as a plain script before this file.

   Write safety (spec Design 6): a pane draws data only when its load is ready, so no control that
   saves exists before its record is hydrated; every request below is built exactly as the plain
   page built it (same body, same headers, same method); a response for a record that is no longer
   the open one (a collapsed recipe, a reset prep day, a superseded load) is dropped; nothing saves
   on mount. */
window.BatchUI = window.BatchUI || {};
(() => {
  const { useState, useEffect } = React;
  const U = window.BatchUI;

  // the pure engine, from batch.js (global functions of that classic script)
  U.scaleAmount = window.scaleAmount;
  U.factorFromEdit = window.factorFromEdit;
  U.fmtWeighed = window.fmtWeighed;
  U.fmtCount = window.fmtCount;
  U.trimNum = window.trimNum;
  U.catBucket = window.catBucket;
  U.byCategoryThenName = window.byCategoryThenName;

  // ── shared state ──────────────────────────────────────────────────────────────────────────────
  // lists/listErr, open (the one expanded recipe row: loading | ready | failed), prepUI (loading |
  // failed | builder | active) and mapState (idle | loading | ready | failed) are the load states
  // of each pane; a pane draws its data only when ready.
  const S = {
    view: "recipes",          // batch panel sub-tab: recipes | prep
    kind: "batch",            // active recipes tab: 'batch' (drinks) | 'prep'
    search: "",               // current name filter within the active tab
    lists: { batch: null, prep: null },   // per-kind row cache
    listErr: { batch: null, prep: null },
    open: null,               // { id, status, rec, err } for the inline-expanded row (one at a time)
    factor: 1,
    ingVer: 0,                // bumped whenever the plain page rebuilt the ingredient rows
    prepLoaded: false,        // has the prep view been hydrated this load?
    prepUI: "loading",
    prepErr: "",
    prepSeq: 0,
    prep: null,               // active prep-day payload (steps + selection)
    prepMeta: "",
    prepSel: {},              // recipe id -> name, builder selection (spans tabs)
    pickKind: "batch",
    pickSearch: "",
    pickOpen: {},             // "<kind>::<category>" -> true when a bucket is open
    pickErr: "",
    pickSeq: 0,
    addMode: false,           // builder is adding a stage to the active day (not a fresh build)
    buildText: "build prep list",
    buildDisabled: true,
    pickCountText: "none selected",
    resetBusy: false,
    mapState: "idle",
    mapErr: "",
    mapLoaded: false,
    mapData: null,            // the structured storage tree {areas:[...]}
    mapEditing: false,
    mapOpen: {},              // storage_unit id -> true when its card is expanded
    mapMsg: { text: "", cls: "" },
    mapLoadSeq: 0,
    mutSeq: 0,                // each map write gets a number; an older answer never overwrites a newer tree
    mutApplied: 0,
    menu: null,               // { anchor, options } for the item action popover
  };
  U.S = S;

  const listeners = [];
  function bump() { listeners.forEach(f => { f(); }); }
  U.bump = bump;
  // the App subscribes once; every child reads S directly on its next draw
  U.useStore = () => {
    const st = useState(0);
    useEffect(() => {
      const f = () => st[1](n => n + 1);
      listeners.push(f);
      return () => { const i = listeners.indexOf(f); if (i >= 0) listeners.splice(i, 1); };
    }, []);
  };

  // --- api helper: unwrap the {status:'ok',data} envelope ---
  function api(path, opts) {
    return fetch(path, opts).then(r => r.json()).then(j => {
      if (j?.status !== "ok") {
        throw new Error((j?.message) || "request failed");
      }
      return j.data;
    });
  }
  U.api = api;

  function jreq(path, method, body) {
    const opts = { method: method };
    if (body !== undefined) {
      opts.headers = { "Content-Type": "application/json" };
      opts.body = JSON.stringify(body);
    }
    return api(path, opts);
  }
  U.jreq = jreq;

  // shared inline-error block: a themed .hub-error with a "retry" affordance. Drawn as a CHILD of
  // the pane, never in place of its own className (several panes carry their own layout class).
  U.ErrorBox = function ErrorBox(props) {
    return (
      <div className="hub-error">
        <span>{props.msg}</span>
        {props.retry ? <button type="button" className="hub-btn hub-error-retry" onClick={props.retry}>retry</button> : null}
      </div>
    );
  };

  // weighed values render in grams only; count units (quart/bottle/ml) show as stored
  U.fmtCardUnit = (grams) => `${U.fmtWeighed(grams, false)} g`;

  // a dotted leader between a row's name and its quantity (the module-wide leader treatment)
  U.Leader = function Leader() { return <span className="leader" aria-hidden="true"></span>; };

  // friendly yield string for a list row. grams convert to kg losslessly once they pass 1000
  U.yieldLabel = (qty, unit) => {
    if (qty == null) return "";
    if (unit === "g" && qty >= 1000) return `~${U.trimNum(qty / 1000, 1)} kg`;
    return `~${U.trimNum(qty, 0)} ${unit || "g"}`;
  };

  // --- view switching ---
  // Scoped to the batch-prep panel's own two views (recipes / prep day). The storage map is a
  // primary tab of the juniper & co page; the umbrella shell shows/hides it and the `jc:tab` cue
  // hydrates it (see batch.jsx).
  U.showView = (name) => {
    S.view = name;
    if (name === "prep" && !S.prepLoaded) U.loadPrep();
    bump();
    window.scrollTo(0, 0);
  };

  // --- recipe list (two tabs: drinks=batch / preps=prep, grouped by category, filtered by the
  //     search box) ---
  function resetOpen() {
    S.open = null;
  }

  U.loadList = () => {
    const kind = S.kind;
    // any open row belongs to the list being drawn again, so it is forgotten
    resetOpen();
    if (S.lists[kind]) { bump(); return; }
    S.listErr[kind] = null;
    bump();
    api(`/batch/api/batch/recipes?kind=${encodeURIComponent(kind)}`).then(rows => {
      S.lists[kind] = rows;
      if (S.kind === kind) resetOpen();   // a late answer for the other tab leaves this tab alone
      bump();
    }).catch(e => {
      S.listErr[kind] = e.message;
      bump();
    });
  };

  U.retryList = () => {
    S.lists[S.kind] = null;
    U.loadList();
  };

  U.setKind = (kind) => {
    if (kind === S.kind) return;
    S.kind = kind;
    S.search = "";
    U.loadList();
  };

  U.setSearch = (v) => {
    S.search = v || "";
    if (S.lists[S.kind]) resetOpen();
    bump();
  };

  // --- recipe detail (inline accordion: expands within the list row) ---
  function closeOpen() {
    S.open = null;
  }

  // fetch one recipe's detail into its already-open row. split out of toggleRecipe so a
  // failed-load retry re-runs just the fetch, not the open/close toggle.
  function loadDetail(o) {
    o.status = "loading";
    o.err = "";
    bump();
    api(`/batch/api/batch/recipe/${o.id}`).then(rec => {
      if (S.open !== o) return;   // user collapsed / switched mid-fetch
      o.status = "ready";
      o.rec = rec;
      S.factor = 1;
      S.ingVer++;
      bump();
    }).catch(e => {
      if (S.open !== o) return;
      o.status = "failed";
      o.err = e.message;
      bump();
    });
  }
  U.retryDetail = () => { if (S.open) loadDetail(S.open); };

  // tap a row: toggle its inline panel. opening one closes any other (accordion).
  U.toggleRecipe = (r) => {
    if (S.open && S.open.id === r.id) { closeOpen(); bump(); return; }
    closeOpen();
    const o = { id: r.id, status: "loading", rec: null, err: "" };
    S.open = o;
    loadDetail(o);
  };

  // --- scaler (ingredient-driven only) ---
  // No preset buttons: the batch factor is set by editing any one ingredient amount. applyFactor
  // just draws again at the new factor and toggles the reset affordance.
  U.applyFactor = (factor) => {
    if (!(factor > 0)) return;
    S.factor = factor;
    S.ingVer++;
    bump();
  };
  U.renderIngredients = () => {
    S.ingVer++;
    bump();
  };

  U.scaleNoteText = () => {
    const f = S.factor;
    if (Math.abs(f - 1) < 1e-9) return "full batch · tap an amount to rescale";
    if (Math.abs(f - 0.5) < 1e-9) return "half batch  (×0.5)";
    if (Math.abs(f - 0.25) < 1e-9) return "quarter batch  (×0.25)";
    return `×${U.trimNum(f, 3)}`;
  };

  // --- prep day ---------------------------------------------------------------
  // Two states share the view: a builder (pick batches, POST to generate the step list) and an
  // active day (the persisted raw, build-up, assemble checklist). The server is the source of
  // truth for what is open.

  U.loadPrep = () => {
    const tok = ++S.prepSeq;
    S.prepUI = "loading";
    bump();
    api("/batch/api/batch/prep-day/active").then(day => {
      if (tok !== S.prepSeq) return;
      S.prepLoaded = true;
      if (day) { S.prep = day; U.renderActive(); }
      else { S.prep = null; U.renderBuilder(); }
    }).catch(e => {
      if (tok !== S.prepSeq) return;
      S.prepErr = e.message;
      S.prepUI = "failed";
      bump();
    });
  };

  // builder: a tabbed (drinks/preps), category-bucketed, collapsible picker + a build button.
  // selection (S.prepSel) is keyed by recipe id and spans both tabs; the selected tray is the
  // always-visible source of truth so a collapsed bucket never hides a pick.
  U.renderBuilder = () => {
    S.prepSel = {};
    S.pickKind = "batch";
    S.pickSearch = "";
    S.pickOpen = {};
    // add mode vs fresh build: same picker, different copy + endpoint. add mode keeps the active
    // day intact and queues the picks as a new stage (see U.build).
    S.buildText = S.addMode ? "add to prep day" : "build prep list";
    S.prepUI = "builder";
    U.loadPickerData();
  };

  // fetch (if needed) + paint the picker. split out of renderBuilder so a failed-load retry just
  // re-fetches instead of re-running renderBuilder (which would wipe any picks made before).
  U.loadPickerData = () => {
    const tok = ++S.pickSeq;
    S.pickErr = "";
    ensurePickLists().then(() => {
      if (tok !== S.pickSeq) return;
      U.updatePickCount();
    }).catch(e => {
      if (tok !== S.pickSeq) return;
      S.pickErr = e.message;
      bump();
    });
    bump();
  };

  // ensure both kinds are cached: reuse the recipes-view cache, fetch any missing
  function ensurePickLists() {
    return Promise.all(["batch", "prep"].map(kind => {
      if (S.lists[kind]) return Promise.resolve();
      return api(`/batch/api/batch/recipes?kind=${encodeURIComponent(kind)}`).then(rows => {
        S.lists[kind] = rows;
      });
    }));
  }

  // group rows into category buckets: buckets alpha by category, rows alpha within
  U.groupByCategory = (rows) => {
    const sorted = rows.slice().sort(U.byCategoryThenName);
    const groups = [], byCat = {};
    sorted.forEach(r => {
      const cat = U.catBucket(r);
      if (!byCat[cat]) { byCat[cat] = { cat: cat, items: [] }; groups.push(byCat[cat]); }
      byCat[cat].items.push(r);
    });
    return groups;
  };

  // is this recipe already on the active day? (drives the add-mode greyed chip)
  U.inPlan = (id) => {
    const sel = (S.prep?.selection) || [];
    for (let i = 0; i < sel.length; i++) if (sel[i].recipe_id === id) return true;
    return false;
  };

  // flip one recipe's selected state; the value carries the name for the tray
  U.togglePick = (r) => {
    if (S.prepSel[r.id]) delete S.prepSel[r.id];
    else S.prepSel[r.id] = r.name;
    U.updatePickCount();
  };
  U.unpick = (id) => {
    delete S.prepSel[id];
    U.updatePickCount();
  };

  U.selectedIds = () => Object.keys(S.prepSel).map(k => parseInt(k, 10));

  U.updatePickCount = () => {
    const n = U.selectedIds().length;
    S.pickCountText = n === 0 ? "none selected"
      : `${n + (n === 1 ? " recipe" : " recipes")} selected`;
    S.buildDisabled = n === 0;
    bump();
  };

  U.setPickKind = (kind) => {
    if (kind === S.pickKind) return;
    S.pickKind = kind;
    S.pickSearch = "";
    bump();
  };
  U.setPickSearch = (v) => {
    S.pickSearch = v || "";
    bump();
  };
  U.togglePickOpen = (key, nowOpen) => {
    S.pickOpen[key] = nowOpen;
    bump();
  };
  // bulk expand/collapse the picker's category buckets in the active tab
  U.toggleAllPick = () => {
    const kind = S.pickKind;
    const keys = U.groupByCategory(S.lists[kind] || []).map(g => `${kind}::${g.cat}`);
    const allOpen = keys.length > 0 && keys.every(k => !!S.pickOpen[k]);
    keys.forEach(k => { S.pickOpen[k] = !allOpen; });
    bump();
  };

  U.build = () => {
    const ids = U.selectedIds();
    if (!ids.length || S.prepUI !== "builder") return;
    const adding = S.addMode;
    const path = adding ? "/batch/api/batch/prep-day/add" : "/batch/api/batch/prep-day";
    const restLabel = adding ? "add to prep day" : "build prep list";
    S.buildDisabled = true;
    S.buildText = adding ? "adding…" : "building…";
    bump();
    api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ recipe_ids: ids }),
    }).then(day => {
      S.addMode = false;
      S.prep = day;
      U.renderActive();
    }).catch(e => {
      S.buildDisabled = false;
      S.pickCountText = (adding ? "couldn't add: " : "couldn't build: ") + e.message;
    }).then(() => {
      S.buildText = restLabel;
      bump();
    });
  };

  // "+ add" on the active day: reopen the picker in add mode (active day kept)
  U.addStage = () => {
    S.addMode = true;
    U.renderBuilder();
  };

  // "cancel" in add mode: back to the active day, nothing changed
  U.cancelAdd = () => {
    S.addMode = false;
    U.renderActive();
  };

  // active: the persisted, grouped, checkable step list
  U.renderActive = () => {
    const day = S.prep;
    if (!day) return;
    S.prepUI = "active";
    // the meta line names the original plan (stage 0); each queued addition gets its own divider
    // down in the step list.
    const names = (day.selection || [])
      .filter(s => (s.stage || 0) === 0)
      .map(s => s.name);
    S.prepMeta = names.length ? `making ${names.join(", ")}` : "";
    bump();
  };

  // recipe names grouped by stage, for the added-stage dividers
  U.stageNames = (day) => {
    const m = {};
    (day.selection || []).forEach(s => {
      const st = s.stage || 0;
      (m[st] = m[st] || []).push(s.name);
    });
    return m;
  };

  // progress counts the checkable units: the build-up/assemble composition rows. Raw is a plain
  // gather list with no checks, and the step header is a derived summary, so neither is counted.
  U.prepProgress = (steps) => {
    let done = 0, total = 0;
    for (let i = 0; i < steps.length; i++) {
      if (steps[i].phase === "raw") continue;
      const comps = steps[i].components || [];
      for (let j = 0; j < comps.length; j++) {
        total++;
        if (comps[j].checked) done++;
      }
    }
    return { done: done, total: total };
  };

  // tick one component: optimistic, reconciled with the server's answer, reverted on failure.
  // An answer for a day that has since been reset or replaced is dropped.
  U.toggleComponent = (c) => {
    const day = S.prep;
    if (!day) return;
    const wanted = c.checked ? 0 : 1;        // optimistic
    c.checked = wanted;
    bump();
    api(`/batch/api/batch/prep-day/component/${c.id}`, { method: "PUT" })
      .then(res => {
        if (S.prep !== day) return;
        c.checked = res.checked;          // reconcile with server truth
        bump();
      })
      .catch(() => {                 // revert on failure
        if (S.prep !== day) return;
        c.checked = wanted ? 0 : 1;
        bump();
      });
  };

  U.resetDay = () => {
    if (!window.confirm("clear this prep day and start a new one?")) return;
    const day = S.prep;
    S.resetBusy = true;
    bump();
    api("/batch/api/batch/prep-day/reset", { method: "POST" }).then(() => {
      S.prep = null;
      S.addMode = false;
      U.renderBuilder();
    }).catch(e => {
      if (S.prep === day) S.prepMeta = `couldn't reset: ${e.message}`;
    }).then(() => {
      S.resetBusy = false;
      bump();
    });
  };
})();
