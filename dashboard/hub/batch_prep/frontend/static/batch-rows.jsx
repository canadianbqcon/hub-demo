/* J&Co batch prep · 2 of 3 (React): the recipe list with its inline accordion rows, the ingredient
   rows and their amount editor, and the prep-day builder (picker, tray, build bar). Ported from
   batch.js; assigns into window.BatchUI (created by batch-core.jsx) and declares nothing else at
   top level. Markup and classes are the plain page's, so batch.css applies unchanged. */
(() => {
  const { useState, useEffect, useRef } = React;
  const U = window.BatchUI;
  const S = U.S;

  // arrow-key roving focus within a list of same-type controls in the container. Delegated on the
  // (stable) container, not the items, so it keeps working across draws.
  U.arrowNav = (selector) => (e) => {
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      const items = Array.prototype.slice.call(e.currentTarget.querySelectorAll(selector));
      const i = items.indexOf(document.activeElement);
      if (i === -1) return;
      e.preventDefault();
      const next = items[(i + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length];
      next.focus();
    };

  // ── recipes view ──────────────────────────────────────────────────────────────────────────────

  // read-only ingredient line inside an expanded sub-recipe (factor 1, no edit)
  function SubRow(props) {
    const disp = U.scaleAmount(props.ing, 1);
    let text;
    if (disp.kind === "weighed") text = U.fmtCardUnit(disp.grams);
    else if (disp.kind === "count") text = `${U.fmtCount(disp.value)} ${disp.unit}`;
    else text = disp.text;
    return (
      <li className="comp">
        <span className="comp-name">{props.ing.ingredient}</span>
        <U.Leader />
        <span className="comp-qty">{text}</span>
      </li>
    );
  }

  // tap a value -> type the amount you actually want; sets the whole batch factor
  function IngEdit(props) {
    const ref = useRef(null);
    const done = useRef(false);
    useEffect(() => { ref.current.focus(); ref.current.select(); }, []);
    function commit(apply) {
      if (done.current) return;
      done.current = true;
      if (apply) {
        const v = parseFloat(ref.current.value);
        const f = U.factorFromEdit(props.ing, v, false);
        if (f && f > 0) { U.applyFactor(f); return; } // draws the whole list again
      }
      U.renderIngredients(); // restore (cancel, or invalid)
    }
    return (
      <input ref={ref} className="ing-edit" type="number" inputMode="decimal" step="any"
             defaultValue={props.current}
             onBlur={() => commit(true)}
             onKeyDown={e => {
               if (e.key === "Enter") { e.preventDefault(); e.currentTarget.blur(); }
               else if (e.key === "Escape") commit(false);
             }} />
    );
  }

  function IngRow(props) {
    const ing = props.ing;
    const ed = useState(false);
    const editing = ed[0], setEditing = ed[1];
    const sb = useState({ open: false, status: "idle", rec: null, err: "" });
    const sub = sb[0], setSub = sb[1];
    const alive = useRef(true);
    useEffect(() => () => { alive.current = false; }, []);

    const isSub = !!ing.produces_recipe_id;
    const disp = U.scaleAmount(ing, S.factor);

    // fetch a sub-recipe's ingredients into its (already-open) wrap. split out of the toggle so a
    // failed-load retry just re-fetches instead of re-running the open/close toggle.
    function loadSub() {
      setSub(p => Object.assign({}, p, { status: "loading" }));
      U.api(`/batch/api/batch/recipe/${ing.produces_recipe_id}`).then(rec => {
        if (alive.current) setSub(p => Object.assign({}, p, { status: "ready", rec: rec }));
      }).catch(e => {
        if (alive.current) setSub(p => Object.assign({}, p, { status: "failed", err: e.message }));
      });
    }
    // open/close a sub-recipe's inline ingredient card under its parent row
    function toggleSub() {
      const open = !sub.open;
      setSub(p => Object.assign({}, p, { open: open }));
      if (!open || sub.status === "ready") return;
      loadSub();
    }

    let val;
    if (disp.kind === "text") {
      val = <div className="ing-val is-text"><span className="ing-num">{disp.text}</span></div>;
    } else {
      const weighed = disp.kind === "weighed";
      const num = weighed ? U.fmtWeighed(disp.grams, false) : U.fmtCount(disp.value);
      val = editing
        ? <IngEdit ing={ing} current={num} />
        : (
          <div className="ing-val is-editable" onClick={() => setEditing(true)}>
            <span className="ing-num">{num}</span>
            <span className="ing-unit">{weighed ? "g" : disp.unit}</span>
          </div>
        );
    }

    return (
      <li className="ing">
        <div className="ing-head">
          <div className={isSub ? "ing-main is-expander" : "ing-main"} onClick={isSub ? toggleSub : undefined}>
            <span className="ing-name">{ing.ingredient}</span>
            {ing.produces_name ? <span className="ing-caret">{isSub ? (sub.open ? "▾" : "▸") : ""}</span> : null}
            {ing.produces_name ? <span className="ing-bom">{`↳ ${ing.produces_name}`}</span> : null}
            {ing.amount ? <span className="ing-src">{ing.amount}</span> : null}
          </div>
          <U.Leader />
          {val}
        </div>
        {isSub ? (
          <div className="ing-sub" hidden={!sub.open}>
            {sub.status === "loading" ? <p className="ing-sub-note">loading…</p> : null}
            {sub.status === "failed" ? <U.ErrorBox msg={`couldn't load: ${sub.err}`} retry={loadSub} /> : null}
            {sub.status === "ready" ? (
              <React.Fragment>
                <ul className="ing-sub-list">
                  {(sub.rec.ingredients || []).map((s, i) => <SubRow key={i} ing={s} />)}
                </ul>
                {sub.rec.method ? <p className="ing-sub-note">{sub.rec.method}</p> : null}
              </React.Fragment>
            ) : null}
          </div>
        ) : null}
      </li>
    );
  }

  // the inline recipe body (meta, scaler, ingredients, method) in the open row's panel
  function RecipePanel(props) {
    const rec = props.rec;
    const bits = [];
    if (rec.category) bits.push(rec.category);
    if (rec.yield_qty) bits.push(`yields ~${U.trimNum(rec.yield_qty, 0)} ${rec.yield_unit || "g"}`);
    return (
      <React.Fragment>
        <p className="detail-meta">{bits.join("  ·  ")}</p>
        {/* notes carry mid-shift prep warnings ("make fresh, don't prebatch"), always visible */}
        {rec.notes ? <p className="detail-note">{rec.notes}</p> : null}
        {/* scaling is ingredient-driven: tap any amount to rescale the whole recipe */}
        <div className="scaler">
          <p className="scale-note">{U.scaleNoteText()}</p>
          <button type="button" className="scale-reset" hidden={Math.abs(S.factor - 1) < 1e-9}
                  onClick={() => U.applyFactor(1)}>reset to full</button>
        </div>
        <ul className="ing-list">
          {(rec.ingredients || []).map((ing, i) => <IngRow key={`${S.ingVer}:${i}`} ing={ing} />)}
        </ul>
        {rec.method ? (
          <details className="method-box">
            <summary>method</summary>
            <p>{rec.method}</p>
          </details>
        ) : null}
      </React.Fragment>
    );
  }

  // a list entry = a tappable header row + an inline panel that expands the full recipe right
  // here (accordion: one open at a time), so reading a recipe never leaves the listing.
  function RecipeRow(props) {
    const r = props.r;
    const o = S.open && S.open.id === r.id ? S.open : null;
    const metaBits = [];
    const yl = U.yieldLabel(r.yield_qty, r.yield_unit);
    if (yl) metaBits.push(`yields ${yl}`);
    if (r.ingredient_count != null) {
      metaBits.push(r.ingredient_count + (r.ingredient_count === 1 ? " ingredient" : " ingredients"));
    }
    const multi = r.sub_count > 0;
    return (
      <div className="recipe-item">
        <button type="button" className={o ? "recipe-row is-open" : "recipe-row"} onClick={() => U.toggleRecipe(r)}>
          <span className="r-main">
            <span className="r-name">{r.name}</span>
            {metaBits.length ? <span className="r-meta">{metaBits.join("  ·  ")}</span> : null}
          </span>
          <span className={`r-tag${multi ? " is-multi" : " is-direct"}`}>{multi ? "multi-step" : "direct"}</span>
          <span className="chev">{o ? "▾" : "›"}</span>
        </button>
        <div className="recipe-panel" hidden={!o}>
          {o && o.status === "loading" ? <p className="panel-note">loading…</p> : null}
          {o && o.status === "failed" ? <U.ErrorBox msg={`couldn't load recipe: ${o.err}`} retry={U.retryDetail} /> : null}
          {o && o.status === "ready" ? <RecipePanel rec={o.rec} /> : null}
        </div>
      </div>
    );
  }

  // the recipes tab body: a failed or pending read of the ACTIVE tab shows its own state; a late
  // answer for the other tab never repaints this one
  U.RecipeList = function RecipeList() {
    const kind = S.kind;
    const all = S.lists[kind];
    if (!all) {
      if (S.listErr[kind] != null) {
        return <U.ErrorBox msg={`couldn't load recipes: ${S.listErr[kind]}`} retry={U.retryList} />;
      }
      return <p className="muted pad">loading recipes…</p>;
    }
    let rows = all.slice();
    const q = S.search.trim().toLowerCase();
    if (q) rows = rows.filter(r => r.name.toLowerCase().indexOf(q) !== -1);
    // sort by batch type (category) first, then alphabetically by name within; discontinued and
    // retired sink to their own bucket at the bottom
    rows.sort(U.byCategoryThenName);
    if (!rows.length) {
      return (
        <p className="muted pad">{q ? `no recipes match “${S.search.trim()}”.` : "no recipes found."}</p>
      );
    }
    const out = [];
    let lastCat = null;
    rows.forEach(r => {
      const cat = U.catBucket(r);
      if (cat !== lastCat) {
        lastCat = cat;
        out.push(<div className="cat-head" key={`h:${cat}`}>{cat}</div>);
      }
      out.push(<RecipeRow key={r.id} r={r} />);
    });
    return <React.Fragment>{out}</React.Fragment>;
  };

  // ── prep day builder ──────────────────────────────────────────────────────────────────────────

  // one collapsible category bucket: a tappable header (chevron, name, count) over a wrap of pick
  // chips. the count reads "selected / total" when any chip is on.
  function PickGroup(props) {
    const g = props.g, open = props.open, key = props.k;
    let selN = 0;
    for (let i = 0; i < g.items.length; i++) if (S.prepSel[g.items[i].id]) selN++;
    return (
      <div className="pick-group">
        <button type="button" className={`pick-cat${open ? " is-open" : ""}${selN > 0 ? " has-sel" : ""}`}
                aria-expanded={open} onClick={() => U.togglePickOpen(key, !open)}>
          <span className="pick-chev">{open ? "▾" : "▸"}</span>
          <span className="pick-cat-label">{g.cat}</span>
          <span className="pick-cat-count">{selN ? `${selN} / ${g.items.length}` : String(g.items.length)}</span>
        </button>
        <HubCollapse open={open}>
        <div className="pick-chips">
          {g.items.map(r => {
            // in add mode a recipe already on the day can't be re-added (no repeat batches); show
            // it greyed + disabled so the skip is visible, not a silent surprise.
            if (S.addMode && U.inPlan(r.id)) {
              return <button type="button" key={r.id} className="pick-chip is-inplan" disabled
                             title="already in this prep day">{r.name}</button>;
            }
            return <button type="button" key={r.id} className={`pick-chip${S.prepSel[r.id] ? " is-on" : ""}`}
                           onClick={() => U.togglePick(r)}>{r.name}</button>;
          })}
        </div>
        </HubCollapse>
      </div>
    );
  }

  // render the active tab as collapsible buckets, filtered by the search box and with
  // discontinued recipes dropped. while searching, matching buckets force-expand so hits show.
  function pickBody() {
    const kind = S.pickKind;
    if (S.pickErr) return { node: <U.ErrorBox msg={`couldn't load recipes: ${S.pickErr}`} retry={U.loadPickerData} />, toggle: null };
    if (!S.lists.batch || !S.lists.prep) return { node: <p className="muted">loading recipes…</p>, toggle: null };
    // discontinued recipes are readable in the recipes view but never pickable for a prep day
    let rows = (S.lists[kind] || []).filter(r => U.catBucket(r) !== "Discontinued");
    const q = S.pickSearch.trim().toLowerCase();
    if (q) rows = rows.filter(r => r.name.toLowerCase().indexOf(q) !== -1);
    const groups = U.groupByCategory(rows);
    // hidden while searching: a search hit already force-expands its bucket
    const keys = groups.map(g => `${kind}::${g.cat}`);
    const allOpen = keys.length > 0 && keys.every(k => !!S.pickOpen[k]);
    const toggle = { hidden: !!q || !groups.length, text: allOpen ? "collapse all" : "expand all" };
    if (!rows.length) {
      return {
        node: <p className="muted pad">{q ? `no recipes match “${S.pickSearch.trim()}”.` : "no recipes found."}</p>,
        toggle: toggle,
      };
    }
    return {
      node: <React.Fragment>{groups.map(g => {
        const key = `${kind}::${g.cat}`;
        return <PickGroup key={key} g={g} k={key} open={!!q || !!S.pickOpen[key]} />;
      })}</React.Fragment>,
      toggle: toggle,
    };
  }

  U.PrepBuilder = function PrepBuilder() {
    const adding = S.addMode;
    const ids = U.selectedIds();
    const body = pickBody();
    const tab = (kind, label) => (
      <button className={`rtab${S.pickKind === kind ? " is-on" : ""}`} data-kind={kind} type="button" role="tab"
              onClick={() => U.setPickKind(kind)}>{label}</button>
    );
    return (
      <div className="prep-builder pad" id="prepBuilder" hidden={S.prepUI !== "builder"}>
        <h1 id="prepBuilderTitle">{adding ? "add to prep day" : "prep day"}</h1>
        <p className="muted" id="prepBuilderIntro">{adding
          ? "pick what to queue — it's appended after your current plan as its own raw → build-up → assemble block. nothing already on your list changes."
          : "pick what you're making — drinks and preps. you'll get a raw → build-up → assemble checklist — gather every raw part first, then make each sub-recipe from it, then assemble — that survives a refresh."}</p>

        {/* picker: drinks/preps tabs + name search. categories below collapse by default so the
            list never floods with a wall of chips. */}
        <div className="pick-controls">
          <div className="recipe-tabs" id="pickTabs" role="tablist" aria-label="recipe kind">
            {tab("batch", "drinks")}
            {tab("prep", "preps")}
          </div>
          <input className="recipe-search" id="pickSearch" type="search"
                 inputMode="search" autoComplete="off" placeholder="search…"
                 aria-label="search recipes by name" value={S.pickSearch}
                 onChange={e => U.setPickSearch(e.target.value)} />
        </div>

        {/* selected tray: every pick as a removable chip; survives tab/collapse */}
        <div className="pick-tray" id="pickTray" aria-live="polite" hidden={!ids.length}>
          {ids.length ? <span className="tray-lbl">selected</span> : null}
          {ids.map(id => (
            <button type="button" key={id} className="tray-chip" onClick={() => U.unpick(id)}>
              <span>{S.prepSel[id]}</span>
              <span className="tray-x">✕</span>
            </button>
          ))}
        </div>

        {/* bulk expand/collapse for the category buckets below */}
        <div className="pick-toolbar">
          <button className="pick-expand-toggle" id="pickExpandToggle" type="button"
                  hidden={!body.toggle || body.toggle.hidden}
                  onClick={U.toggleAllPick}>{body.toggle ? body.toggle.text : "expand all"}</button>
        </div>

        {/* grouped, collapsible picker */}
        <div className="prep-pick" id="prepPick" aria-live="polite"
             onKeyDown={U.arrowNav(".pick-chip:not(:disabled)")}>{body.node}</div>

        <div className="prep-build-bar">
          <button className="prep-cancel" id="prepCancel" type="button" hidden={!adding}
                  onClick={U.cancelAdd}>cancel</button>
          <span className="muted" id="prepPickCount">{S.pickCountText}</span>
          <button className="btn-save" id="prepBuild" type="button" disabled={S.buildDisabled}
                  onClick={U.build}>{S.buildText}</button>
        </div>
      </div>
    );
  };
})();
