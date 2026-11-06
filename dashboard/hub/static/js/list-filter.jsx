/* HubUI.ListFilter: the portable list-rail filter (search + fold toggle, sort field with its
   listbox, stage grid headed by a tri-state select-all) as a component. React port of the DOM
   half of list-filter.js; the plain file stays until its last consumer (purchases) converts.

   The pure half is NOT ported: search/facet/sort/state all come from window.HubListFilter
   (apply, readState, writeState, sanitize, allState), which is why list-filter.js must still be
   loaded before this file runs and why tests/listfilter.selftest.js keeps covering the logic.

   <HubUI.ListFilter id cfg rows onChange />
     cfg      the same shape list-filter.js documents; pass the SAME object every render
     rows     the unfiltered rows; pass a new array only when the data changed. The filtered result
              is recomputed (and onChange called) when `rows` or the filter state changes, which is
              the mount().update(rows) contract of the plain control
     onChange (state, { rows, counts }) after every recompute, same as cfg.onChange there
   The markup and class names are the plain control's, so components.css (.hub-lf*) applies as is. */
window.HubUI = window.HubUI || {};
(() => {
  const { useState, useEffect, useLayoutEffect, useRef, useMemo } = React;

  function ListFilter({ id, cfg, rows, onChange }) {
    const LF = window.HubListFilter;
    const [state, setState] = useState(() => LF.readState(cfg));
    const [menuOpen, setMenuOpen] = useState(false);
    const stateRef = useRef(state);
    const menuRef = useRef(menuOpen);
    const sortRef = useRef(null);
    const sortBodyRef = useRef(null);
    const menuEl = useRef(null);
    menuRef.current = menuOpen;

    const options = (cfg.facet?.options) || [];
    const sorts = cfg.sorts || [];
    const noun = (cfg.facet?.allLabel) || (`${(cfg.facet?.label) || "option"}s`);
    const result = useMemo(() => LF.apply(rows, cfg, state), [rows, state]);

    // a change goes through sanitize and is persisted before the next event reads it
    function commit(patch) {
      const next = LF.sanitize(cfg, Object.assign({}, stateRef.current, patch));
      stateRef.current = next;
      LF.writeState(cfg, next);
      setState(next);
    }
    function sortDirOf(key) {
      const def = sorts.find((s) => s.key === key);
      return (def?.dir) || "asc";
    }
    function toggleOption(key) {
      const on = stateRef.current.on.slice();
      const i = on.indexOf(key);
      if (i === -1) on.push(key); else on.splice(i, 1);
      commit({ on });
    }
    function toggleAll() {
      commit({ on: LF.allState(stateRef.current.on, options) === "all" ? [] : options.map((o) => o.key) });
    }
    function setSort(key) { commit({ sort: key, dir: sortDirOf(key) }); }

    useLayoutEffect(() => { if (onChange) onChange(state, result); }, [result]);

    // outside click / Escape close the sort listbox; document-level so a click anywhere else on the
    // page closes it (same idiom as the theme picker in theme-switch.js)
    useEffect(() => {
      function onDocClick(e) {
        if (menuRef.current && sortRef.current && !sortRef.current.contains(e.target)) setMenuOpen(false);
      }
      function onDocKeydown(e) {
        if (!menuRef.current) return;
        if (e.key === "Escape") { setMenuOpen(false); sortBodyRef.current.focus(); return; }
        if (e.key !== "ArrowDown" && e.key !== "ArrowUp" && e.key !== "Enter") return;
        const opts = Array.prototype.slice.call(menuEl.current.querySelectorAll(".hub-lf-sort-opt"));
        if (!opts.length) return;
        const active = document.activeElement;
        let i = opts.indexOf(active);
        // preventDefault: without it the browser replays Enter on the sort button that closing the
        // menu just focused, reopening it
        if (e.key === "Enter") { if (i !== -1) { e.preventDefault(); active.click(); } return; }
        e.preventDefault();
        if (i === -1) i = 0;
        else i = e.key === "ArrowDown" ? Math.min(i + 1, opts.length - 1) : Math.max(i - 1, 0);
        opts[i].focus();
      }
      document.addEventListener("click", onDocClick);
      document.addEventListener("keydown", onDocKeydown);
      return () => {
        document.removeEventListener("click", onDocClick);
        document.removeEventListener("keydown", onDocKeydown);
      };
    }, []);

    const onCount = state.on.length;
    const total = options.length;
    const sortDef = sorts.find((s) => s.key === state.sort);
    const sortLabel = sortDef ? sortDef.label : state.sort;
    const status = LF.allState(state.on, options);

    return (
      <div className="hub-lf" id={id}>
        <div className="hub-lf-bar">
          <input type="search" className="hub-lf-search" placeholder={(cfg.search?.placeholder) || ""}
                 value={state.q} onChange={(e) => commit({ q: e.target.value })} />
          <button type="button" className="hub-lf-fold" aria-expanded={state.folded ? "false" : "true"}
                  onClick={() => commit({ folded: !stateRef.current.folded })}>
            {state.folded ? "▾" : `${onCount}/${total} · ${sortLabel} ▴`}
          </button>
        </div>
        <div className="hub-lf-sort" ref={sortRef}>
          <button type="button" className="hub-lf-sort-body" aria-haspopup="listbox" aria-expanded={menuOpen ? "true" : "false"}
                  ref={sortBodyRef} onClick={() => setMenuOpen(!menuRef.current)}>
            <span className="hub-lf-sort-ico">⇅</span>
            <b className="hub-lf-sort-label">{sortLabel}</b>
            <i className="hub-lf-sort-chev">▾</i>
          </button>
          <button type="button" className="hub-lf-sort-dir" aria-label="reverse order"
                  onClick={() => commit({ dir: stateRef.current.dir === "desc" ? "asc" : "desc" })}>
            {state.dir === "desc" ? "↓" : "↑"}
          </button>
          <div className="hub-lf-sort-menu" role="listbox" hidden={!menuOpen} ref={menuEl}>
            {sorts.map((s) => (
              <button type="button" className="hub-lf-sort-opt" role="option" key={s.key} data-key={s.key}
                      aria-selected={s.key === state.sort ? "true" : "false"}
                      onClick={() => { setSort(s.key); setMenuOpen(false); sortBodyRef.current.focus(); }}>
                {s.label}
              </button>
            ))}
          </div>
        </div>
        <div className="hub-lf-grid" hidden={state.folded}>
          <button type="button" className={`hub-lf-all is-${status}`} role="checkbox"
                  aria-checked={status === "some" ? "mixed" : status === "all" ? "true" : "false"} onClick={toggleAll}>
            <i className="hub-lf-box"></i>
            <span className="hub-lf-label">
              {status === "all" ? `all ${noun}` : status === "none" ? `no ${noun}` : `${onCount} of ${total} ${noun}`}
            </span>
            <span className="hub-lf-n">{String(result.rows.length)}</span>
          </button>
          {options.map((opt) => {
            const on = state.on.indexOf(opt.key) !== -1;
            const count = result.counts[opt.key] || 0;
            return (
              <button type="button" role="checkbox" key={opt.key} data-key={opt.key} aria-checked={on ? "true" : "false"}
                      className={`hub-lf-opt${on ? " is-on" : ""}${count === 0 ? " is-zero" : ""}`}
                      onClick={() => toggleOption(opt.key)}>
                <i className="hub-lf-box"></i>
                <span className="hub-lf-label">{opt.label}</span>
                <span className="hub-lf-n">{String(count)}</span>
              </button>
            );
          })}
        </div>
      </div>
    );
  }

  window.HubUI.ListFilter = ListFilter;
})();
