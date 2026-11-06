/* HubListFilter: pure search/facet/sort core for portable list rails, plus
   its localStorage-backed state helpers. Framework-free classic script: no
   modules, no build step, no React. window.HubListFilter is the browser
   entry point; it also assigns module.exports so the node self-test
   (tests/listfilter.selftest.js) can require it directly.

   mount(el, cfg) draws the DOM half (search bar + fold toggle, a raised sort
   field with its own listbox, and a bordered two-column stage grid headed by
   a tri-state select-all row) into `el` and keeps it in sync with state on
   every interaction. It never calls apply() itself outside reapply(); a host
   never calls apply() either: mount().update(rows) is the only entry point.
   Styling lives in static/css/components.css under `.hub-lf*`.

   cfg shape (docs/specs/2026-09-28-jobs-rail-filter-design.md, Design 2):
     {
       key,                                     // localStorage namespace
       search: { placeholder, fields: row => string },
       facet: { label, allLabel, options: [{ key, label, match: row => bool }],
                defaultOn: [keys], presets: [{ label, on: [keys] }] },
       sorts: [{ key, label, cmp(a, b), dir }],  // dir is that sort's own default
       defaultSort,
       onChange(state, { rows, counts })
     }
   state shape:
     { q, on: [optionKeys], sort, dir: "asc"|"desc", folded }
   facet.allLabel is optional: the select-all row's noun ("stages"), defaulting
   to facet.label + "s". facet.presets stays in the cfg shape (readState /
   presetState honour it) but mount() never renders a presets UI; the
   select-all row is the only all/none control (design ruling, plan Task 3).
*/
(() => {
  

  function findSort(cfg, key) {
    var sorts = cfg.sorts || [];
    for (let i = 0; i < sorts.length; i++) if (sorts[i].key === key) return sorts[i];
    return null;
  }

  // A sort can declare its own default direction (score, newest want "desc"
  // out of the box); falls back to "asc" when it doesn't say.
  function sortDir(cfg, key) {
    var def = findSort(cfg, key);
    return (def?.dir) || "asc";
  }

  function defaultState(cfg) {
    var defaultOn = (cfg.facet?.defaultOn) || [];
    return {
      q: "",
      on: defaultOn.slice(),
      sort: cfg.defaultSort,
      dir: sortDir(cfg, cfg.defaultSort),
      folded: false,
    };
  }

  // Drops anything a stored state could have gotten wrong: option keys that no
  // longer exist, a sort that was renamed or removed, a bad dir string. A
  // missing or malformed field falls back to its default rather than erroring.
  function sanitize(cfg, state) {
    if (!state || typeof state !== "object") return defaultState(cfg);

    var options = (cfg.facet?.options) || [];
    var optionKeys = options.map((o) => o.key);
    var on = Array.isArray(state.on)
      ? state.on.filter((k) => optionKeys.indexOf(k) !== -1)
      : ((cfg.facet?.defaultOn) || []).slice();

    // an unknown sort falls back to the default sort AND that sort's own
    // default dir; a dir paired with a sort that no longer exists is
    // meaningless, so it is not carried over.
    var sortKnown = !!findSort(cfg, state.sort);
    var sort = sortKnown ? state.sort : cfg.defaultSort;
    var dir = sortKnown && (state.dir === "asc" || state.dir === "desc")
      ? state.dir
      : sortDir(cfg, sort);

    return {
      q: typeof state.q === "string" ? state.q : "",
      on: on,
      sort: sort,
      dir: dir,
      folded: typeof state.folded === "boolean" ? state.folded : false,
    };
  }

  // Pure: search -> per-option counts -> facet -> sort. Counts are taken
  // after search and before the facet, so toggling a stage never moves the
  // numbers shown next to the other stages.
  function apply(rows, cfg, state) {
    var q = String(state.q || "").trim().toLowerCase();
    var searched = q
      ? rows.filter((row) => String(cfg.search.fields(row) || "").toLowerCase().indexOf(q) !== -1)
      : rows.slice();

    var options = (cfg.facet?.options) || [];
    var counts = {};
    options.forEach((opt) => {
      var n = 0;
      for (let i = 0; i < searched.length; i++) if (opt.match(searched[i])) n++;
      counts[opt.key] = n;
    });

    var on = state.on || [];
    var onOptions = options.filter((o) => on.indexOf(o.key) !== -1);
    // no option switched on -> no rows, rather than treating "no filter" as
    // "everything passes"; the empty-selection case has to be visibly empty.
    var filtered = onOptions.length === 0
      ? []
      : searched.filter((row) => onOptions.some((o) => o.match(row)));

    var sortDef = findSort(cfg, state.sort) || findSort(cfg, cfg.defaultSort);
    var sorted = filtered.slice();
    if (sortDef) {
      // negate rather than reverse, so tied rows keep their order either way
      const cmp = sortDef.cmp;
      sorted.sort(state.dir === "desc" ? ((a, b) => cmp(b, a)) : cmp);
    }

    return { rows: sorted, counts: counts };
  }

  function storageKey(cfg) { return `hub.lf.${cfg.key}`; }

  function readState(cfg) {
    try {
      if (typeof localStorage === "undefined") return defaultState(cfg);
      const raw = localStorage.getItem(storageKey(cfg));
      if (!raw) return defaultState(cfg);
      return sanitize(cfg, JSON.parse(raw));
    } catch {
      // storage missing, disabled (private mode), or the stored JSON is
      // corrupt: fail open to defaults rather than breaking the page.
      return defaultState(cfg);
    }
  }

  function writeState(cfg, state) {
    try {
      if (typeof localStorage === "undefined") return;
      localStorage.setItem(storageKey(cfg), JSON.stringify(state));
    } catch {
      // storage full or blocked: state just won't persist across reloads
    }
  }

  function presetState(cfg, state, preset) {
    var merged = Object.assign({}, state, { on: preset.on });
    return sanitize(cfg, merged);
  }

  // ── select-all tri-state ────────────────────────────────────────────────
  // Pure so it is node-testable without a DOM: "all" when every option is on,
  // "none" when none are, "some" for a partial selection (the dash box).
  function allState(on, options) {
    var opts = options || [];
    var onKeys = on || [];
    var onCount = 0;
    for (let i = 0; i < opts.length; i++) {
      if (onKeys.indexOf(opts[i].key) !== -1) onCount++;
    }
    if (onCount === 0) return "none";
    if (onCount === opts.length) return "all";
    return "some";
  }

  // "all stages" / "3 of 6 stages" / "no stages": cfg.facet.allLabel names an
  // irregular plural; otherwise the facet label gets a bare "s" (stage ->
  // stages, which is every current use).
  function allNoun(cfg) {
    if (cfg.facet?.allLabel) return cfg.facet.allLabel;
    return `${(cfg.facet?.label) || "option"}s`;
  }

  // ── mount ────────────────────────────────────────────────────────────────
  // The DOM half: a search bar with a fold toggle, a full-width raised sort
  // field with its own listbox, and a bordered two-column stage grid headed
  // by the tri-state select-all row. `el` becomes the `.hub-lf` root.
  // Design reference: data/workbench/options/list-filter-rail/options.html,
  // card B ("the select-all box shows a partial state").
  function mount(el, cfg) {
    var state = readState(cfg);
    var lastRows = [];
    var lastResult = { rows: [], counts: {} };

    el.classList.add("hub-lf");
    el.innerHTML =
      '<div class="hub-lf-bar">' +
        '<input type="search" class="hub-lf-search" placeholder="">' +
        '<button type="button" class="hub-lf-fold" aria-expanded="true"></button>' +
      "</div>" +
      '<div class="hub-lf-sort">' +
        '<button type="button" class="hub-lf-sort-body" aria-haspopup="listbox" aria-expanded="false">' +
          '<span class="hub-lf-sort-ico">⇅</span>' +
          '<b class="hub-lf-sort-label"></b>' +
          '<i class="hub-lf-sort-chev">▾</i>' +
        "</button>" +
        '<button type="button" class="hub-lf-sort-dir" aria-label="reverse order"></button>' +
        '<div class="hub-lf-sort-menu" role="listbox" hidden></div>' +
      "</div>" +
      '<div class="hub-lf-grid">' +
        '<button type="button" class="hub-lf-all" role="checkbox">' +
          '<i class="hub-lf-box"></i><span class="hub-lf-label"></span><span class="hub-lf-n"></span>' +
        "</button>" +
      "</div>";

    var searchEl = el.querySelector(".hub-lf-search");
    var foldEl = el.querySelector(".hub-lf-fold");
    var sortEl = el.querySelector(".hub-lf-sort");
    var sortBodyEl = el.querySelector(".hub-lf-sort-body");
    var sortLabelEl = el.querySelector(".hub-lf-sort-label");
    var sortDirEl = el.querySelector(".hub-lf-sort-dir");
    var sortMenuEl = el.querySelector(".hub-lf-sort-menu");
    var gridEl = el.querySelector(".hub-lf-grid");
    var allEl = el.querySelector(".hub-lf-all");

    searchEl.placeholder = (cfg.search?.placeholder) || "";

    var options = (cfg.facet?.options) || [];
    var sorts = cfg.sorts || [];
    var noun = allNoun(cfg);

    // the sort listbox is static (cfg.sorts doesn't change), so it is built
    // once rather than on every paint.
    sorts.forEach((s) => {
      var opt = document.createElement("button");
      opt.type = "button";
      opt.className = "hub-lf-sort-opt";
      opt.setAttribute("role", "option");
      opt.dataset.key = s.key;
      opt.textContent = s.label;
      opt.addEventListener("click", () => {
        setSort(s.key);
        closeSortMenu();
        sortBodyEl.focus();
      });
      sortMenuEl.appendChild(opt);
    });

    // one .hub-lf-opt button per facet option, rebuilt each paint (counts and
    // on/off change every call; six-ish rows is cheap to redraw whole).
    function buildOptionRow(opt) {
      var row = document.createElement("button");
      row.type = "button";
      row.className = "hub-lf-opt";
      row.setAttribute("role", "checkbox");
      row.dataset.key = opt.key;
      row.innerHTML = '<i class="hub-lf-box"></i><span class="hub-lf-label"></span><span class="hub-lf-n"></span>';
      row.querySelector(".hub-lf-label").textContent = opt.label;
      return row;
    }
    options.forEach((opt) => { gridEl.appendChild(buildOptionRow(opt)); });

    function setState(next) {
      state = sanitize(cfg, Object.assign({}, state, next));
      writeState(cfg, state);
      reapply(lastRows);
    }
    function setQuery(q) { setState({ q: q }); }
    function toggleFold() { setState({ folded: !state.folded }); }
    function toggleOption(key) {
      var on = state.on.slice();
      var i = on.indexOf(key);
      if (i === -1) on.push(key); else on.splice(i, 1);
      setState({ on: on });
    }
    function toggleAll() {
      var status = allState(state.on, options);
      setState({ on: status === "all" ? [] : options.map((o) => o.key) });
    }
    function setSort(key) { setState({ sort: key, dir: sortDir(cfg, key) }); }
    function toggleDir() { setState({ dir: state.dir === "desc" ? "asc" : "desc" }); }

    function openSortMenu() {
      sortMenuEl.hidden = false;
      sortBodyEl.setAttribute("aria-expanded", "true");
    }
    function closeSortMenu() {
      sortMenuEl.hidden = true;
      sortBodyEl.setAttribute("aria-expanded", "false");
    }
    function sortMenuOpen() { return !sortMenuEl.hidden; }

    searchEl.addEventListener("input", () => { setQuery(searchEl.value); });
    foldEl.addEventListener("click", toggleFold);
    sortDirEl.addEventListener("click", toggleDir);
    sortBodyEl.addEventListener("click", () => {
      sortMenuOpen() ? closeSortMenu() : openSortMenu();
    });
    gridEl.addEventListener("click", (e) => {
      var optBtn = e.target.closest(".hub-lf-opt");
      if (optBtn) { toggleOption(optBtn.dataset.key); return; }
      if (e.target.closest(".hub-lf-all")) toggleAll();
    });

    // outside click / Escape close the sort listbox; document-level so a
    // click anywhere else on the page (not just outside .hub-lf-sort) closes
    // it, same idiom as the theme picker in theme-switch.js.
    function onDocClick(e) { if (sortMenuOpen() && !sortEl.contains(e.target)) closeSortMenu(); }
    function onDocKeydown(e) {
      if (!sortMenuOpen()) return;
      if (e.key === "Escape") { closeSortMenu(); sortBodyEl.focus(); return; }
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp" && e.key !== "Enter") return;
      var opts = Array.prototype.slice.call(sortMenuEl.querySelectorAll(".hub-lf-sort-opt"));
      if (!opts.length) return;
      var active = document.activeElement;
      var i = opts.indexOf(active);
      // preventDefault: without it the browser replays Enter on the sort button
      // that closeSortMenu() just focused, reopening the menu.
      if (e.key === "Enter") { if (i !== -1) { e.preventDefault(); active.click(); } return; }
      e.preventDefault();
      if (i === -1) i = 0;
      else i = e.key === "ArrowDown" ? Math.min(i + 1, opts.length - 1) : Math.max(i - 1, 0);
      opts[i].focus();
    }
    document.addEventListener("click", onDocClick);
    document.addEventListener("keydown", onDocKeydown);

    function paint() {
      if (searchEl.value !== state.q) searchEl.value = state.q;

      var onCount = state.on.length;
      var total = options.length;
      var sortDef = findSort(cfg, state.sort);
      var sortLabel = sortDef ? sortDef.label : state.sort;
      foldEl.setAttribute("aria-expanded", state.folded ? "false" : "true");
      foldEl.textContent = state.folded
        ? "▾"
        : `${onCount}/${total} · ${sortLabel} ▴`;

      sortLabelEl.textContent = sortLabel;
      sortDirEl.textContent = state.dir === "desc" ? "↓" : "↑";
      var sortOpts = sortMenuEl.querySelectorAll(".hub-lf-sort-opt");
      for (let i = 0; i < sortOpts.length; i++) {
        sortOpts[i].setAttribute("aria-selected", sortOpts[i].dataset.key === state.sort ? "true" : "false");
      }

      gridEl.hidden = state.folded;

      var status = allState(state.on, options);
      allEl.className = `hub-lf-all is-${status}`;
      allEl.setAttribute("aria-checked", status === "some" ? "mixed" : status === "all" ? "true" : "false");
      allEl.querySelector(".hub-lf-label").textContent =
        status === "all" ? `all ${noun}` : status === "none" ? `no ${noun}` : `${onCount} of ${total} ${noun}`;
      allEl.querySelector(".hub-lf-n").textContent = String(lastResult.rows.length);

      var rows = gridEl.querySelectorAll(".hub-lf-opt");
      rows.forEach((row) => {
        var key = row.dataset.key;
        var on = state.on.indexOf(key) !== -1;
        var count = lastResult.counts[key] || 0;
        row.classList.toggle("is-on", on);
        row.classList.toggle("is-zero", count === 0);
        row.setAttribute("aria-checked", on ? "true" : "false");
        row.querySelector(".hub-lf-n").textContent = String(count);
      });
    }

    function reapply(rows) {
      lastRows = rows;
      lastResult = apply(rows, cfg, state);
      paint();
      if (cfg.onChange) cfg.onChange(state, lastResult);
      return lastResult;
    }

    reapply(lastRows);

    return {
      update: (rows) => reapply(rows),
      get state() { return state; },
      destroy: () => {
        document.removeEventListener("click", onDocClick);
        document.removeEventListener("keydown", onDocKeydown);
        el.innerHTML = "";
        el.classList.remove("hub-lf");
      },
    };
  }

  var HubListFilter = {
    defaultState: defaultState,
    sanitize: sanitize,
    apply: apply,
    readState: readState,
    writeState: writeState,
    presetState: presetState,
    allState: allState,
    mount: mount,
  };

  if (typeof window !== "undefined") window.HubListFilter = HubListFilter;
  if (typeof module !== "undefined" && module.exports) module.exports = HubListFilter;
})();
