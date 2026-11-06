/* J&Co batch prep · 3 of 3 (React): the active prep day (step list, checks, reset), the storage map
   with its edit mode, the keyboard accelerators, the App and the mount. Ported from batch.js and
   the batch parts of jc.js (jc.js itself stays: it is the tab shell shared with bar back, and the
   only contract with it is the `jc:tab` event and window.JcTabs). Assigns into window.BatchUI and
   declares nothing else at top level.

   The page's static batch and map markup is replaced, not augmented: the root is the #panel-batch
   section itself and the storage map draws into #view-map through a portal, so every selector in
   batch.css and jc.css (child combinators, sticky bars) still matches. */
(() => {
  const { useEffect, useLayoutEffect, useRef } = React;
  const U = window.BatchUI;
  const S = U.S;
  const bump = U.bump;

  // ── active prep day ───────────────────────────────────────────────────────────────────────────

  const PHASE_LABEL = { raw: "raw", "build-up": "build up", assemble: "assemble" };

  // quantity shown on a step line: the gram part plus any non-gram units, joined
  function qtyText(s) {
    const parts = [];
    if (s.qty_g != null) parts.push(U.fmtCardUnit(s.qty_g));
    if (s.qty_extra) parts.push(s.qty_extra);
    return parts.join(" + ");
  }

  // a raw-stage line: the gather list. name left, quantity right, no checkbox and no click (raw is
  // a condensed list, not a checklist; the checkable unit lives on the build-up/assemble parts).
  function RawItem(props) {
    return (
      <div className="raw-item">
        <span className="raw-name">{props.s.label}</span>
        <U.Leader />
        <span className="raw-qty">{qtyText(props.s)}</span>
      </div>
    );
  }

  // a build-up/assemble step = a derived header row + an indented composition sub-list. The
  // checkable unit is each component, so the header shows a "done/total" count and strikes through
  // once every sub-item is ticked.
  function StepItem(props) {
    const s = props.s;
    const comps = s.components || [];
    let done = 0;
    for (let i = 0; i < comps.length; i++) if (comps[i].checked) done++;
    const total = comps.length;
    return (
      <div className="step-item">
        <div className={total > 0 && done === total ? "step is-checked" : "step"}>
          <span className="step-count">{total ? `${done} / ${total}` : ""}</span>
          <span className="step-label">{s.label}</span>
          <U.Leader />
          <span className="step-qty">{qtyText(s)}</span>
        </div>
        {/* brew-time on its own indented line directly under the title row */}
        {s.lead_label ? <div className="step-lead">{s.lead_label}</div> : null}
        {comps.length ? (
          <ul className="step-comps">
            {comps.map(c => {
              let q;
              if (c.qty_g != null) q = U.fmtCardUnit(c.qty_g);
              else if (c.unit) q = `${c.label || ""} ${c.unit}`;   // "1 gal"
              else q = c.label || "to taste";                       // to-taste
              return (
                <li key={c.id}>
                  <button type="button" className={`comp${c.checked ? " is-checked" : ""}`}
                          onClick={() => U.toggleComponent(c)}>
                    <span className="comp-box">{c.checked ? "✓" : ""}</span>
                    <span className="comp-name">{c.name}</span>
                    <U.Leader />
                    <span className="comp-qty">{q}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        ) : null}
        {s.note ? <div className="step-note">{s.note}</div> : null}
      </div>
    );
  }

  function PrepSteps() {
    const day = S.prep;
    if (!day) return null;
    const steps = day.steps || [];
    // grouped by phase (the seq already enforces order). within the raw phase a second-level
    // sub-header per tier makes the fresh-to-stable ordering visible. stage 0 is the original
    // plan; stages 1+ are queued additions, each behind a divider naming what was added.
    const snames = U.stageNames(day);
    const out = [];
    let lastPhase = null, lastTier = null, lastStage = null;
    steps.forEach((s, i) => {
      const st = s.stage || 0;
      if (st !== lastStage) {
        lastStage = st;
        lastPhase = null;           // restart phase + tier headers inside the new block
        lastTier = null;
        if (st > 0) {
          const added = snames[st] || [];
          out.push(<div className="stage-head" key={`st${i}`}>{added.length ? `added — ${added.join(", ")}` : "added"}</div>);
        }
      }
      if (s.phase !== lastPhase) {
        lastPhase = s.phase;
        lastTier = null;            // tiers don't carry across a phase boundary
        out.push(<div className="phase-head" key={`ph${i}`}>{PHASE_LABEL[s.phase] || s.phase}</div>);
      }
      if (s.tier && s.tier !== lastTier) {
        lastTier = s.tier;
        out.push(<div className="tier-head" key={`ti${i}`}>{s.tier}</div>);
      }
      out.push(s.phase === "raw" ? <RawItem key={`s${i}`} s={s} /> : <StepItem key={`s${i}`} s={s} />);
    });
    return <React.Fragment>{out}</React.Fragment>;
  }

  function PrepActive() {
    const day = S.prep;
    const p = day ? U.prepProgress(day.steps || []) : null;
    return (
      <div className="prep-active" id="prepActive" hidden={S.prepUI !== "active"}>
        <div className="prep-head">
          <div className="prep-head-l">
            <h1>prep day</h1>
            <p className="detail-meta" id="prepMeta">{S.prepMeta}</p>
          </div>
          <div className="prep-head-actions">
            <button className="prep-add" id="prepAdd" type="button" onClick={U.addStage}>+ add</button>
            <button className="prep-reset" id="prepReset" type="button" disabled={S.resetBusy}
                    onClick={U.resetDay}>reset</button>
          </div>
        </div>
        <div className={p && p.total > 0 && p.done === p.total ? "prep-progress is-complete" : "prep-progress"}
             id="prepProgress">{p ? `${p.done} / ${p.total} done` : ""}</div>
        <div className="prep-steps" id="prepSteps"><PrepSteps /></div>
      </div>
    );
  }

  // ── storage map (structured tree) ─────────────────────────────────────────────────────────────
  // Renders the four-level tree (area, unit, section, item) as collapsible unit cards with item
  // chips. An "edit" toggle reveals inline controls (reorder, rename, delete, add); every mutation
  // hits the CRUD API, which returns the whole tree, and we draw again from that authoritative
  // state. Edit controls exist only once the tree has loaded (mapState ready).

  const SAPI = "/batch/api/batch/storage";

  function setMapStatus(msg, cls) {
    S.mapMsg = { text: msg || "", cls: cls || "" };
  }

  function loadMap() {
    const seq = ++S.mapLoadSeq;
    S.mapState = "loading";
    bump();
    U.jreq(`${SAPI}/tree`, "GET").then(d => {
      if (seq !== S.mapLoadSeq) return;   // a newer read superseded this one
      S.mapData = d;
      S.mapLoaded = true;
      S.mapState = "ready";
      bump();
    }).catch(e => {
      if (seq !== S.mapLoadSeq) return;
      setMapStatus("");
      S.mapErr = e.message;
      S.mapState = "failed";
      bump();
    });
  }

  // run a CRUD call; on success swap in the returned tree + draw again. Returns the response
  // payload (or undefined on error) so callers can read e.g. new_id. `send` builds the request,
  // so nothing is sent unless the tree is loaded; an older answer never overwrites a newer tree.
  function mapMutate(send) {
    if (S.mapState !== "ready") return Promise.resolve();
    const seq = ++S.mutSeq;
    setMapStatus("saving…");
    bump();
    return send().then(d => {
      const areas = d.tree.areas;
      if (seq > S.mutApplied) { S.mutApplied = seq; S.mapData = { areas: areas }; }
      setMapStatus("saved", "ok");
      bump();
      return d;
    }).catch(e => {
      setMapStatus(e.message, "err");
      bump();
    });
  }

  function itemCount(node) {
    let n = 0;
    (node.sections || []).forEach(s => { n += s.items.length + itemCount(s); });
    return n;
  }

  function renameNode(kind, id, current) {
    let v = window.prompt(kind === "item" ? "Item:" : "Name:", current || "");
    if (v === null) return;
    v = v.trim();
    if (kind === "item" && !v) return;       // item text can't be blank
    mapMutate(() => U.jreq(`${SAPI}/${kind}/${id}`, "PUT", { label: v }));
  }

  function deleteNode(kind, id, label, childWarn) {
    let msg = `Delete ${label ? `“${label}”` : `this ${kind}`}?`;
    if (childWarn) msg += `\n${childWarn}`;
    if (!window.confirm(msg)) return;
    mapMutate(() => U.jreq(`${SAPI}/${kind}/${id}`, "DELETE"));
  }

  function addNode(kind, parentId, promptLabel) {
    let v = window.prompt(promptLabel, "");
    if (v === null) return;
    v = v.trim();
    if (kind === "item" && !v) return;
    const body = { label: v };
    if (parentId != null) body.parent_id = parentId;
    mapMutate(() => U.jreq(`${SAPI}/${kind}`, "POST", body)).then(d => {
      // auto-open a freshly added fixture so its shelves/items are reachable
      if (d && kind === "unit" && d.new_id) { S.mapOpen[d.new_id] = true; bump(); }
    });
  }

  // ── lightweight action-menu popover (item edit actions) ──
  function closeMenu() {
    if (S.menu) { S.menu = null; bump(); }
  }
  function openMenu(anchor, options) {
    closeMenu();
    S.menu = { anchor: anchor, options: options };
    bump();
    setTimeout(() => { document.addEventListener("click", closeMenu, { once: true }); }, 0);
  }

  function editNote(it) {
    const v = window.prompt("Note (small grey detail):", it.note || "");
    if (v === null) return;
    mapMutate(() => U.jreq(`${SAPI}/item/${it.id}/note`, "PUT", { note: v.trim() }));
  }
  function moveItemMenu(it, anchor) {
    const opts = [];
    S.mapData.areas.forEach(a => {
      a.units.forEach(u => {
        // walk nested shelves too, so a sub-shelf is a valid move target
        (function walk(secs, prefix) {
          secs.forEach(s => {
            const path = prefix + (s.name ? ` · ${s.name}` : "");
            opts.push({ label: path, fn: () => {
              mapMutate(() => U.jreq(`${SAPI}/item/${it.id}/reparent`, "POST", { section_id: s.id }));
            } });
            walk(s.sections, path);
          });
        })(u.sections, `${a.name || "?"} · ${u.name || "loose"}`);
      });
    });
    if (!opts.length) { window.alert("No other shelves to move to."); return; }
    openMenu(anchor, opts);
  }
  function itemMenu(it, anchor) {
    openMenu(anchor, [
      { label: "Rename", fn: () => { renameNode("item", it.id, it.text); } },
      { label: it.note ? "Edit note" : "Add note", fn: () => { editNote(it); } },
      { label: "Move to shelf…", fn: () => { moveItemMenu(it, anchor); } },
      { label: "Delete", danger: true, fn: () => { deleteNode("item", it.id, it.text, ""); } },
    ]);
  }

  function MapMenu() {
    const m = S.menu;
    const ref = useRef(null);
    useLayoutEffect(() => {
      if (!m || !ref.current) return;
      const el = ref.current;
      const r = m.anchor.getBoundingClientRect();
      const maxLeft = window.scrollX + document.documentElement.clientWidth - el.offsetWidth - 8;
      el.style.top = `${window.scrollY + r.bottom + 4}px`;
      el.style.left = `${Math.max(8, Math.min(window.scrollX + r.left, maxLeft))}px`;
    }, [m]);
    if (!m) return null;
    return ReactDOM.createPortal(
      <div className="map-menu" ref={ref}>
        {m.options.map((o, i) => (
          <button type="button" key={i} className={`map-menu-item${o.danger ? " is-danger" : ""}`}
                  onClick={ev => { ev.stopPropagation(); closeMenu(); o.fn(); }}>{o.label}</button>
        ))}
      </div>,
      document.body
    );
  }

  // every fixture id across every room: the unit of expand/collapse-all
  function allMapUnitIds() {
    const ids = [];
    ((S.mapData?.areas) || []).forEach(a => {
      a.units.forEach(u => { ids.push(u.id); });
    });
    return ids;
  }

  // small round tool button (up, down, rename, delete), shown only in edit mode
  function Tool(props) {
    return (
      <button type="button" className={`map-tool${props.danger ? " is-danger" : ""}`} title={props.title}
              disabled={!!props.disabled}
              onClick={props.disabled ? undefined : ev => { ev.stopPropagation(); props.fn(); }}>{props.glyph}</button>
    );
  }

  // a reorder pair for node `kind`/`id` at position i of n siblings (ends disabled)
  function MoveTools(props) {
    const kind = props.kind, id = props.id;
    return (
      <span className="map-tools">
        <Tool glyph="▲" title="move up" disabled={props.i === 0} fn={() => {
          mapMutate(() => U.jreq(`${SAPI}/${kind}/${id}/move`, "POST", { direction: "up" }));
        }} />
        <Tool glyph="▼" title="move down" disabled={props.i === props.n - 1} fn={() => {
          mapMutate(() => U.jreq(`${SAPI}/${kind}/${id}/move`, "POST", { direction: "down" }));
        }} />
      </span>
    );
  }

  function AddBtn(props) {
    return (
      <button type="button" className={props.item ? "map-add map-add-item" : "map-add"}
              onClick={props.onClick}>{props.label}</button>
    );
  }

  function Chip(props) {
    const it = props.it, editing = S.mapEditing;
    return (
      <span className={`map-chip${editing ? " is-edit" : ""}`}
            onClick={editing ? ev => itemMenu(it, ev.currentTarget) : undefined}>
        <span className="chip-label">{it.text}</span>
        {it.note ? <span className="chip-note">{it.note}</span> : null}
        {editing ? (
          <span className="map-chip-x" onClick={ev => { ev.stopPropagation(); deleteNode("item", it.id, it.text, ""); }}>✕</span>
        ) : null}
      </span>
    );
  }

  // Sections nest to any depth. `parent` is the container this section hangs off (the unit for a
  // top-level shelf, another section for a sub-shelf) and `kind` is which of the two, so the CRUD
  // calls scope to the right parent column. Depth only drives the indent class.
  function Section(props) {
    const parent = props.parent, section = props.section, si = props.si, depth = props.depth || 0;
    const kind = depth ? "subsection" : "section";
    const editing = S.mapEditing;
    return (
      <div className={`map-section${depth ? " is-nested" : ""}`}>
        {section.name || editing ? (
          <div className="map-section-label">
            <span className="map-section-name">{section.name || "(loose)"}</span>
            {editing ? <MoveTools kind={kind} id={section.id} i={si} n={parent.sections.length} /> : null}
            {editing ? <Tool glyph="✎" title="rename shelf" fn={() => { renameNode(kind, section.id, section.name); }} /> : null}
            {editing ? <Tool glyph="✕" title="delete shelf" danger fn={() => {
              const kids = section.items.length + itemCount(section);
              deleteNode(kind, section.id, section.name, kids ? "Its items go too." : "");
            }} /> : null}
          </div>
        ) : null}
        <div className="map-chips">
          {!section.items.length && !section.sections.length && !editing ? <span className="map-empty">—</span> : null}
          {section.items.map(it => <Chip key={it.id} it={it} />)}
        </div>
        {section.sections.map((child, ci) => (
          <Section key={child.id} parent={section} section={child} si={ci} depth={depth + 1} />
        ))}
        {editing ? <AddBtn item label="+ item" onClick={() => { addNode("item", section.id, "New item:"); }} /> : null}
        {editing ? <AddBtn item label="+ sub-shelf" onClick={() => { addNode("subsection", section.id, "New sub-shelf name:"); }} /> : null}
      </div>
    );
  }

  function Unit(props) {
    const area = props.area, unit = props.unit, i = props.i;
    const editing = S.mapEditing;
    const open = !!S.mapOpen[unit.id];
    const toggleUnitOpen = () => { S.mapOpen[unit.id] = !open; bump(); };
    // a div, so it is made keyboard/SR operable: focusable, role=button, Enter/Space. Nested tool
    // buttons stopPropagation() their own clicks; the e.target guard does the same for keydown so
    // Enter on rename/delete doesn't also toggle the card.
    return (
      <div className={open ? "map-unit is-open" : "map-unit"}>
        <div className="map-unit-head" tabIndex={0} role="button" aria-expanded={open ? "true" : "false"}
             onClick={toggleUnitOpen}
             onKeyDown={e => {
               if (e.target !== e.currentTarget) return;
               if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleUnitOpen(); }
             }}>
          <span className="map-chev">{open ? "▾" : "▸"}</span>
          <span className={`map-unit-name${unit.name ? "" : " is-loose"}`}>{unit.name || "loose items"}</span>
          {editing ? <MoveTools kind="unit" id={unit.id} i={i} n={area.units.length} /> : null}
          {editing ? <Tool glyph="✎" title="rename fixture" fn={() => { renameNode("unit", unit.id, unit.name); }} /> : null}
          {editing ? <Tool glyph="✕" title="delete fixture" danger fn={() => {
            deleteNode("unit", unit.id, unit.name, itemCount(unit) ? "Its shelves and items go too." : "");
          }} /> : null}
          <span className="map-unit-count">{String(itemCount(unit))}</span>
        </div>
        <HubCollapse open={open}>
        <div className="map-unit-body">
          {unit.sections.map((s, si) => <Section key={s.id} parent={unit} section={s} si={si} />)}
          {editing ? <AddBtn label="+ shelf" onClick={() => { addNode("section", unit.id, "New shelf name (leave blank for loose):"); }} /> : null}
        </div>
        </HubCollapse>
      </div>
    );
  }

  function Area(props) {
    const area = props.area, editing = S.mapEditing;
    const i = S.mapData.areas.indexOf(area);
    return (
      <div className="map-area">
        <div className="map-area-head">
          <span className="map-area-name">{area.name || "(unnamed)"}</span>
          {editing ? <MoveTools kind="area" id={area.id} i={i} n={S.mapData.areas.length} /> : null}
          {editing ? <Tool glyph="✎" title="rename room" fn={() => { renameNode("area", area.id, area.name); }} /> : null}
          {editing ? <Tool glyph="✕" title="delete room" danger fn={() => {
            deleteNode("area", area.id, area.name, area.units.length ? "Its fixtures and items go too." : "");
          }} /> : null}
        </div>
        <div className="map-units">
          {area.units.map((u, ui) => <Unit key={u.id} area={area} unit={u} i={ui} />)}
        </div>
        {editing ? <AddBtn label="+ fixture" onClick={() => {
          addNode("unit", area.id, "New fixture name (leave blank for loose items):");
        }} /> : null}
      </div>
    );
  }

  function MapTree() {
    const ready = S.mapState === "ready";
    const data = S.mapData;
    let body;
    if (S.mapState === "failed") {
      body = <U.ErrorBox msg={`couldn't load storage map: ${S.mapErr}`} retry={loadMap} />;
    } else if (!ready) {
      body = <p className="muted">loading storage map…</p>;
    } else {
      body = (
        <React.Fragment>
          {data?.areas?.length
            ? data.areas.map(area => <Area key={area.id} area={area} />)
            : <p className="muted">no storage areas yet.</p>}
          {S.mapEditing ? <AddBtn label="+ room" onClick={() => { addNode("area", null, "New room name:"); }} /> : null}
        </React.Fragment>
      );
    }
    return (
      <div className={ready && S.mapEditing ? "map-tree is-editing" : "map-tree"} id="mapTree" aria-live="polite"
           onKeyDown={U.arrowNav(".map-unit-head")}>{body}</div>
    );
  }

  function MapPane() {
    const ids = allMapUnitIds();
    const allOpen = ids.length > 0 && ids.every(id => !!S.mapOpen[id]);
    return (
      <div className="map-wrap pad">
        <div className="map-head">
          <div className="map-head-l">
            <h1>storage map</h1>
            <p className="muted" id="mapMeta">where everything lives</p>
          </div>
          <div className="map-head-actions">
            <button className="map-expand-toggle" id="mapExpandToggle" type="button"
                    hidden={ids.length === 0}
                    onClick={() => {
                      ids.forEach(id => { S.mapOpen[id] = !allOpen; });
                      bump();
                    }}>{allOpen ? "collapse all" : "expand all"}</button>
            <button className={S.mapEditing ? "map-edit-toggle is-on" : "map-edit-toggle"} id="mapEditToggle"
                    type="button" aria-pressed={S.mapEditing ? "true" : "false"}
                    onClick={() => {
                      S.mapEditing = !S.mapEditing;
                      setMapStatus("");
                      bump();
                    }}>{S.mapEditing ? "done" : "edit"}</button>
          </div>
        </div>
        {/* the rendered tree: collapsible unit cards */}
        <MapTree />
        <span className={S.mapMsg.cls ? `save-status ${S.mapMsg.cls}` : "save-status"} id="mapStatus"
              role="status">{S.mapMsg.text}</span>
      </div>
    );
  }

  // ── batch panel ───────────────────────────────────────────────────────────────────────────────

  function App(props) {
    U.useStore();
    useEffect(() => {
      document.getElementById("panel-batch").setAttribute("data-react-mounted", "jc-batch");

      // The map is a sibling section, not a view inside this one. It hydrates lazily: the umbrella
      // fires `jc:tab` on every switch, and the live tab is read once at boot because the shell's
      // first fire lands before this file is compiled.
      const hydrateMapIfShown = tab => { if (tab === "map" && !S.mapLoaded && S.mapState !== "loading") loadMap(); };
      const onTab = e => { hydrateMapIfShown(e.detail.tab); };
      document.addEventListener("jc:tab", onTab);

      // Esc dismisses the item popover; "/" focuses whichever search box belongs to the visible
      // view (the recipes search, or the prep builder's picker search when it is open)
      const onKey = e => {
        if (e.key === "Escape" && S.menu) closeMenu();
        if (e.key !== "/") return;
        const activeTag = (document.activeElement?.tagName) || "";
        if (activeTag === "INPUT" || activeTag === "TEXTAREA" || activeTag === "SELECT") return;
        // scoped to this panel: the map is a sibling tab and owns no search box
        const batchPanel = document.getElementById("panel-batch");
        if (!batchPanel || batchPanel.hidden) return;
        let target = null;
        if (S.view === "recipes") target = document.getElementById("recipeSearch");
        else if (S.view === "prep" && S.prepUI === "builder") target = document.getElementById("pickSearch");
        if (target) { e.preventDefault(); target.focus(); }
      };
      document.addEventListener("keydown", onKey);

      hydrateMapIfShown(window.JcTabs ? window.JcTabs.current() : null);
      U.loadList();
      return () => {
        document.removeEventListener("jc:tab", onTab);
        document.removeEventListener("keydown", onKey);
      };
    }, []);

    const sub = (name, label) => (
      <button className={S.view === name ? "jc-tab nav-item is-on" : "jc-tab nav-item"} type="button" role="tab"
              data-target={name} aria-selected={S.view === name ? "true" : "false"}
              tabIndex={S.view === name ? 0 : -1} onClick={() => U.showView(name)}>{label}</button>
    );
    const kindTab = (kind, label) => (
      <button className={S.kind === kind ? "rtab is-on" : "rtab"} data-kind={kind} type="button" role="tab"
              onClick={() => U.setKind(kind)}>{label}</button>
    );
    const ui = S.prepUI;
    return (
      <React.Fragment>
        <nav className="jc-subtabs" id="batchSubtabs" role="tablist" aria-label="batch prep views">
          {sub("recipes", "recipes")}
          {sub("prep", "prep day")}
        </nav>

        <div className="views">

          {/* recipes */}
          <section className={S.view === "recipes" ? "view is-active" : "view"} id="view-recipes" data-view="recipes">
            {/* sticky controls: drinks/preps tabs + name search */}
            <div className="recipe-controls" id="recipeControls">
              <div className="recipe-tabs" id="recipeTabs" role="tablist" aria-label="recipe kind">
                {kindTab("batch", "drinks")}
                {kindTab("prep", "preps")}
              </div>
              <input className="recipe-search" id="recipeSearch" type="search"
                     inputMode="search" autoComplete="off" placeholder="search…"
                     aria-label="search recipes by name" value={S.search}
                     onChange={e => U.setSearch(e.target.value)} />
            </div>
            {/* list (grouped by batch type, alpha within; each row expands inline into its own panel) */}
            <div className="recipe-list" id="recipeList" aria-live="polite"
                 onKeyDown={U.arrowNav(".recipe-row")}>
              <U.RecipeList />
            </div>
          </section>

          {/* prep day */}
          <section className={S.view === "prep" ? "view is-active" : "view"} id="view-prep" data-view="prep">
            <U.PrepBuilder />
            <PrepActive />
            <div className="muted pad" id="prepLoading" hidden={ui === "builder" || ui === "active"}>
              {ui === "failed"
                ? <U.ErrorBox msg={`couldn't load prep day: ${S.prepErr}`} retry={U.loadPrep} />
                : "loading prep day…"}
            </div>
          </section>

        </div>
        {ReactDOM.createPortal(<MapPane />, props.mapHost)}
        <MapMenu />
      </React.Fragment>
    );
  }

  // Render errors land here; async/handler errors are caught where they happen.
  class Boundary extends React.Component {
    constructor(p) { super(p); this.state = { err: null }; }
    static getDerivedStateFromError(err) { return { err }; }
    componentDidCatch(err) { console.error("[batch] render failed", err); }
    render() { return this.state.err ? <div className="hub-error">page failed to load</div> : this.props.children; }
  }

  // Mount. The template's static batch and map markup is cleared first, so React draws into an
  // empty container and no click can land on a dead static copy.
  const host = document.getElementById("panel-batch");
  const mapHost = document.getElementById("view-map");
  if (host && mapHost) {
    host.textContent = "";
    mapHost.textContent = "";
    const root = ReactDOM.createRoot(host);
    ReactDOM.flushSync(() => { root.render(<Boundary><App mapHost={mapHost} /></Boundary>); });
  }
})();
