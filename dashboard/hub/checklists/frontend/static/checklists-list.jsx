/* Checklists · 3 of 4 (React): selecting a checklist, the detail pane, and every item and
   section action. Ported from app-render.js and app-events.js: same DOM and classes, same
   request bodies in the same order. The plain page mutated activeChecklist in place and
   re-rendered; here the same mutations run and bump() redraws. The two inline-editor
   pairs (rename a title / section / item, add a section) are components instead of
   replaceWith() calls, so a redraw can no longer drop one mid-edit. */
(() => {
  const { useState, useRef } = React;
  const U = window.ChecklistsUI;
  const { API, BASE, S, D, InlineEdit, bump, toast, toastAction, confirmDialog, errMsg,
          updateSidebarItem, reloadActiveChecklist } = U;

  // ── Select & load a checklist ─────────────────────────────────────────────────

  function selectChecklist(id) {
    S.activeId = id;
    localStorage.setItem(U.ACTIVE_KEY, String(id));
    S.main = "loading"; // the sidebar shows the active highlight now, without waiting on the fetch
    bump();
    return API.get(`${BASE}/checklists/${id}`).then(cl => {
      if (S.activeId !== id) return; // moved on before the read landed: drop it
      S.active = cl;
      S.main = "ready";
      bump();
    }, e => {
      if (S.activeId !== id) return; // a newer selection owns the pane
      S.main = "failed";
      S.mainErr = errMsg(e);
      bump();
    });
  }

  // Swap an item with its neighbor within its own section, then persist the new
  // section order via the same `/items/reorder` endpoint the drag-drop path uses
  // (find target = swap-only == smallest keyboard-reachable reorder step).
  function moveItem(itemId, dir) {
    const cid = S.active.id;
    const items = S.active.items;
    const item = items.find(i => i.id === itemId);
    if (!item) return;
    const section = item.section || "";
    const secIds = items.filter(i => (i.section || "") === section).map(i => i.id);
    const idx = secIds.indexOf(itemId);
    const swapIdx = idx + dir;
    if (swapIdx < 0 || swapIdx >= secIds.length) return; // already at the edge

    const otherId = secIds[swapIdx];
    const idxA = items.findIndex(i => i.id === itemId);
    const idxB = items.findIndex(i => i.id === otherId);
    [items[idxA], items[idxB]] = [items[idxB], items[idxA]];
    bump();

    const newSecIds = items.filter(i => (i.section || "") === section).map(i => i.id);
    API.post(`${BASE}/checklists/${cid}/items/reorder`, { ids: newSecIds }).catch(e => {
      toast(`couldn't save reorder — ${errMsg(e)}`);
      return reloadActiveChecklist();
    });
  }

  // After an item has been moved in memory: persist its section change, the new section's
  // order, and the order of the section it left (only when that still holds items).
  function persistMove(cid, itemId, newSection, oldSection) {
    const items = S.active.items;
    const moved = newSection !== oldSection;
    const reorder = section => {
      const ids = items.filter(i => (i.section || "") === section).map(i => i.id);
      return API.post(`${BASE}/checklists/${cid}/items/reorder`, { ids });
    };
    return (moved ? API.patch(`${BASE}/checklists/${cid}/items/${itemId}`, { section: newSection }) : Promise.resolve())
      .then(() => reorder(newSection))
      .then(() => {
        if (moved && items.some(i => (i.section || "") === oldSection)) return reorder(oldSection);
      })
      .then(bump)
      .catch(e => {
        // the in-memory reorder already happened optimistically; a failed persist
        // would leave the screen out of step with the DB, so re-pull the truth instead
        toast(`couldn't save reorder — ${errMsg(e)}`);
        return reloadActiveChecklist();
      });
  }

  // ── One item row ──────────────────────────────────────────────────────────────

  // perf: same last-target tracking as the sidebar drag; skip the sweep
  // when the highlighted row+side hasn't changed since the last dragover.
  const itemDragLast = { cur: null }; // { el, before }
  const clearItemDrop = () => {
    document.querySelectorAll(".cl-item-drop-above, .cl-item-drop-below")
      .forEach(n => { n.classList.remove("cl-item-drop-above", "cl-item-drop-below"); });
  };

  function ItemRow({ item, idx, count, cid }) {
    const [editing, setEditing] = useState(false);

    // the box flips at once; a failed save puts it back and says so
    const toggle = e => {
      const wasChecked = e.target.checked;
      const items = S.active.items;
      item.checked = wasChecked ? 1 : 0;
      bump();
      API.patch(`${BASE}/checklists/${cid}/items/${item.id}`, { checked: wasChecked ? 1 : 0 }).then(saved => {
        const at = items.findIndex(i => i.id === item.id);
        if (at >= 0) items[at] = saved;
        updateSidebarItem();
      }, err => {
        item.checked = wasChecked ? 0 : 1; // revert so the box matches the DB
        toast(`couldn't save check — ${errMsg(err)}`);
        bump();
      });
    };

    // Delete: no confirm dialog (cheaper on the happy path); instead a soft-delete-style
    // undo via the toast, since the item is really gone from the DB the instant this fires.
    const del = () => {
      const items = S.active.items;
      const at = items.findIndex(i => i.id === item.id);
      if (at < 0) return;
      const removed = items[at];
      API.del(`${BASE}/checklists/${cid}/items/${item.id}`).then(() => {
        const gone = items.findIndex(i => i.id === removed.id);
        if (gone >= 0) items.splice(gone, 1);
        updateSidebarItem();
        toastAction(`"${removed.text}" deleted`, "undo", () => {
          API.post(`${BASE}/checklists/${cid}/items`, { text: removed.text, section: removed.section || "" })
            .then(restored => (removed.checked
              ? API.patch(`${BASE}/checklists/${cid}/items/${restored.id}`, { checked: 1 }).then(() => { restored.checked = 1; return restored; })
              : restored))
            .then(restored => {
              // ponytail: restore lands at the end of its section, not its original position;
              // full position restore needs an extra reorder call; upgrade if that's ever missed.
              if (S.active && S.active.id === cid) {
                S.active.items.push(restored);
                updateSidebarItem();
              }
            })
            .catch(e => toast(`couldn't restore item — ${errMsg(e)}`));
        });
      }, e => toast(`couldn't delete item — ${errMsg(e)}`));
    };

    // rename: PATCH {text}; empty or unchanged sends nothing
    const commit = text => {
      const finish = () => { setEditing(false); bump(); };
      if (!text || text === item.text) { finish(); return; }
      API.patch(`${BASE}/checklists/${cid}/items/${item.id}`, { text })
        .then(() => { item.text = text; })
        .catch(e => toast(`couldn't rename item — ${errMsg(e)}`))
        .then(finish);
    };

    const onDragStart = e => {
      const el = e.currentTarget;
      D.itemId = item.id;
      D.sectionName = null;
      e.dataTransfer.effectAllowed = "move";
      e.stopPropagation();
      setTimeout(() => el.classList.add("cl-dragging"), 0);
    };
    const onDragEnd = e => {
      e.currentTarget.classList.remove("cl-dragging");
      clearItemDrop();
      D.itemId = null;
      itemDragLast.cur = null;
    };
    const onDragOver = e => {
      if (D.itemId === null || D.itemId === item.id) return;
      e.preventDefault();
      e.stopPropagation();
      const el = e.currentTarget;
      const rect = el.getBoundingClientRect();
      const before = e.clientY < rect.top + rect.height / 2;
      if (itemDragLast.cur && itemDragLast.cur.el === el && itemDragLast.cur.before === before) return;
      itemDragLast.cur = { el, before };
      clearItemDrop();
      el.classList.add(before ? "cl-item-drop-above" : "cl-item-drop-below");
    };
    const onDragLeave = e => {
      const el = e.currentTarget;
      if (!el.contains(e.relatedTarget)) {
        el.classList.remove("cl-item-drop-above", "cl-item-drop-below");
        if (itemDragLast.cur && itemDragLast.cur.el === el) itemDragLast.cur = null;
      }
    };
    const onDrop = e => {
      e.preventDefault();
      e.stopPropagation();
      const el = e.currentTarget;
      const insertBefore = el.classList.contains("cl-item-drop-above");
      el.classList.remove("cl-item-drop-above", "cl-item-drop-below");
      itemDragLast.cur = null;

      if (D.itemId === null || D.itemId === item.id) return;
      const dragId = D.itemId;
      D.itemId = null; // a move to another section remounts the row, so its dragend would never reach this root
      const items = S.active.items;
      const fromIdx = items.findIndex(i => i.id === dragId);
      const toIdx   = items.findIndex(i => i.id === item.id);
      if (fromIdx < 0 || toIdx < 0) return;

      const draggedItem = items[fromIdx];
      const targetItem  = items[toIdx];
      const newSection  = targetItem.section || "";
      const oldSection  = draggedItem.section || "";

      // Reorder in memory
      items.splice(fromIdx, 1);
      draggedItem.section = newSection;
      const newToIdx = items.findIndex(i => i.id === item.id);
      items.splice(insertBefore ? newToIdx : newToIdx + 1, 0, draggedItem);

      persistMove(cid, dragId, newSection, oldSection);
    };

    return (
      <div className={`hub-checklist-item cl-item${item.checked ? " checked" : ""}`} data-id={item.id} data-section={item.section || ""} draggable="true"
           onDragStart={onDragStart} onDragEnd={onDragEnd} onDragOver={onDragOver} onDragLeave={onDragLeave} onDrop={onDrop}>
        <span className="cl-drag-handle cl-item-drag" title="Drag to reorder">⠿</span>
        <input type="checkbox" checked={!!item.checked} data-id={item.id} aria-labelledby={`cl-item-text-${item.id}`} onChange={toggle} />
        {editing
          ? <InlineEdit className="cl-item-rename-input" initial={item.text} onCommit={commit} onCancel={() => setEditing(false)} />
          : <span className="hub-checklist-text cl-item-text" id={`cl-item-text-${item.id}`} title="Double-click to rename"
                  onDoubleClick={e => { e.stopPropagation(); setEditing(true); }}>{item.text}</span>}
        <div className="cl-item-move-group">
          <button type="button" className="cl-item-move cl-item-move-up" data-id={item.id} aria-label="Move up" title="Move up" disabled={idx === 0} onClick={() => moveItem(item.id, -1)}>↑</button>
          <button type="button" className="cl-item-move cl-item-move-down" data-id={item.id} aria-label="Move down" title="Move down" disabled={idx === count - 1} onClick={() => moveItem(item.id, 1)}>↓</button>
        </div>
        <button type="button" className="cl-item-del" data-id={item.id} title="Remove" onClick={del}>✕</button>
      </div>
    );
  }

  // ── The add-item row of one section ───────────────────────────────────────────

  function AddItemRow({ name, cid }) {
    const [text, setText] = useState("");
    const ref = useRef(null);
    const submit = () => {
      const t = text.trim();
      if (!t) return;
      API.post(`${BASE}/checklists/${cid}/items`, { text: t, section: name }).then(item => {
        if (S.active && S.active.id === cid) S.active.items.push(item);
        setText("");
        updateSidebarItem();
        ref.current?.focus();
      }, e => toast(`couldn't add item — ${errMsg(e)}`));
    };
    return (
      <div className="cl-item cl-add-item-row">
        <span className="cl-drag-handle cl-item-drag" aria-hidden="true">⠿</span>
        <span className="cl-add-item-ghost" aria-hidden="true"></span>
        <input ref={ref} type="text" className="cl-add-item-input" placeholder="Add item…" data-section={name}
               value={text} onChange={e => setText(e.target.value)}
               onKeyDown={e => { if (e.key === "Enter") submit(); }} />
        <button type="button" className="cl-add-item-submit" data-section={name} onClick={submit}>Add</button>
      </div>
    );
  }

  // ── One section ───────────────────────────────────────────────────────────────

  function Section({ name, items, cid }) {
    const [editing, setEditing] = useState(false);
    const collapsed = name ? U.isSectionCollapsed(cid, name) : false;

    const toggleCollapse = e => {
      e.stopPropagation();
      if (!S.sections[cid]) S.sections[cid] = {};
      if (!S.sections[cid].collapsed) S.sections[cid].collapsed = {};
      S.sections[cid].collapsed[name] = !S.sections[cid].collapsed[name];
      U.saveSectionState();
      bump();
    };

    const delSection = () => {
      const secItems = S.active.items.filter(i => (i.section || "") === name);
      const finish = () => {
        if (!S.sections[cid]) S.sections[cid] = {};
        S.sections[cid].order = (S.sections[cid].order || []).filter(s => s !== name);
        U.saveSectionState();
        bump();
      };
      if (secItems.length === 0) { finish(); return; }
      confirmDialog("delete section", `Delete "${name}" section? ${secItems.length} item(s) will be moved to unsectioned.`, { danger: true, confirmLabel: "delete" }).then(ok => {
        if (!ok) return;
        API.post(`${BASE}/checklists/${cid}/sections/delete`, { name, keep_items: true }).then(() => {
          for (const item of S.active.items) {
            if ((item.section || "") === name) item.section = "";
          }
          finish();
        }, e => toast(`couldn't delete section — ${errMsg(e)}`));
      });
    };

    // rename: POST {from, to}; empty or unchanged sends nothing
    const commit = newName => {
      const finish = () => { setEditing(false); bump(); };
      if (!newName || newName === name) { finish(); return; }
      API.post(`${BASE}/checklists/${cid}/sections/rename`, { from: name, to: newName })
        .then(() => {
          for (const item of S.active.items) {
            if ((item.section || "") === name) item.section = newName;
          }
          if (S.sections[cid]?.order) {
            const idx = S.sections[cid].order.indexOf(name);
            if (idx >= 0) S.sections[cid].order[idx] = newName;
            U.saveSectionState();
          }
        })
        .catch(e => toast(`couldn't rename section — ${errMsg(e)}`))
        .then(finish);
    };

    // ── section header drag: reorder sections ──
    const onHeadDragStart = e => {
      if (D.itemId !== null) return;
      const el = e.currentTarget;
      D.sectionName = name;
      e.dataTransfer.effectAllowed = "move";
      setTimeout(() => el.closest(".cl-section").classList.add("cl-dragging"), 0);
    };
    const onHeadDragEnd = e => {
      e.currentTarget.closest(".cl-section")?.classList.remove("cl-dragging");
      D.sectionName = null;
    };
    const onHeadDragOver = e => {
      if (!D.sectionName || D.sectionName === name) return;
      e.preventDefault();
      e.currentTarget.classList.add("cl-section-drop-target");
    };
    const onHeadDragLeave = e => {
      const el = e.currentTarget;
      if (!el.contains(e.relatedTarget)) el.classList.remove("cl-section-drop-target");
    };
    const onHeadDrop = e => {
      e.preventDefault();
      e.currentTarget.classList.remove("cl-section-drop-target");
      if (!D.sectionName || D.sectionName === name) return;
      const moved = D.sectionName;
      D.sectionName = null;
      const order = S.sections[cid]?.order || [];
      const from = order.indexOf(moved);
      const to   = order.indexOf(name);
      if (from < 0 || to < 0) return;
      order.splice(from, 1);
      order.splice(to, 0, moved);
      U.saveSectionState();
      bump();
    };

    // ── body drop zone: catches items dropped on empty space or an empty section ──
    const onBodyDragOver = e => {
      if (D.itemId === null) return;
      if (e.target.closest(".cl-item")) return; // item handles its own dragover
      e.preventDefault();
      e.currentTarget.classList.add("cl-section-body-drop");
    };
    const onBodyDragLeave = e => {
      const el = e.currentTarget;
      if (!el.contains(e.relatedTarget)) el.classList.remove("cl-section-body-drop");
    };
    const onBodyDrop = e => {
      if (D.itemId === null) return;
      if (e.target.closest(".cl-item")) return; // item handled it
      e.preventDefault();
      e.currentTarget.classList.remove("cl-section-body-drop");

      const dragId = D.itemId;
      D.itemId = null; // see ItemRow's onDrop
      const all = S.active.items;
      const fromIdx = all.findIndex(i => i.id === dragId);
      if (fromIdx < 0) return;

      const draggedItem = all[fromIdx];
      const oldSection  = draggedItem.section || "";
      all.splice(fromIdx, 1);
      draggedItem.section = name;
      all.push(draggedItem);

      persistMove(cid, dragId, name, oldSection);
    };

    return (
      <div className="cl-section" data-section={name}>
        {name && (
          <div className="cl-section-header" data-section={name} draggable="true"
               onDragStart={onHeadDragStart} onDragEnd={onHeadDragEnd} onDragOver={onHeadDragOver}
               onDragLeave={onHeadDragLeave} onDrop={onHeadDrop}>
            <span className="cl-drag-handle" title="Drag to reorder section">⠿</span>
            <button type="button" className="cl-section-collapse" data-section={name} title={collapsed ? "Expand" : "Collapse"} aria-expanded={!collapsed} onClick={toggleCollapse}>{collapsed ? "▶" : "▼"}</button>
            {editing
              ? <InlineEdit className="cl-rename-input" initial={name} onCommit={commit} onCancel={() => setEditing(false)} />
              : <span className="cl-section-title" onDoubleClick={e => { e.stopPropagation(); setEditing(true); }}>{name}</span>}
            <div className="cl-section-actions">
              <button type="button" className="cl-section-del" data-section={name} title="Delete section" onClick={delSection}>✕</button>
            </div>
          </div>
        )}
        <div className={`cl-section-body${collapsed ? " collapsed" : ""}`}
             onDragOver={onBodyDragOver} onDragLeave={onBodyDragLeave} onDrop={onBodyDrop}>
          {/* Move-up/down are the keyboard-reachable reorder path (drag-drop is mouse-only).
              Scoped to items only; groups/sections stay drag-only, per audit finding P3. */}
          <HubCollapse open={!collapsed}>
            {items.map((item, idx) => <ItemRow key={item.id} item={item} idx={idx} count={items.length} cid={cid} />)}
            <AddItemRow name={name} cid={cid} />
          </HubCollapse>
        </div>
      </div>
    );
  }

  // "+ Add section" turns into an inline input; a name adds a client-side section (no request)
  // that stays until an item is added to it
  function AddSectionRow({ cid }) {
    const [adding, setAdding] = useState(false);
    const commit = name => {
      if (name) {
        if (!S.sections[cid]) S.sections[cid] = {};
        if (!S.sections[cid].order) S.sections[cid].order = [];
        if (!S.sections[cid].order.includes(name)) {
          S.sections[cid].order.push(name);
          U.saveSectionState();
        }
      }
      setAdding(false);
      bump();
    };
    return (
      <div className="cl-add-section-row">
        {adding
          ? <InlineEdit className="cl-add-section-input" initial="" placeholder="Section name…" onCommit={commit} onCancel={() => setAdding(false)} />
          : <button type="button" id="add-section-btn" className="cl-add-section-btn" onClick={() => setAdding(true)}>+ Add section</button>}
      </div>
    );
  }

  // ── The open checklist ────────────────────────────────────────────────────────

  function Checklist() {
    const [renaming, setRenaming] = useState(false);
    const cl = S.active;
    const cid = cl.id;
    const total = cl.items.length;
    const checked = cl.items.filter(i => i.checked).length;
    const pct = total > 0 ? Math.round((checked / total) * 100) : 0;
    const complete = total > 0 && checked === total;

    const bySection = {};
    for (const item of cl.items) {
      const sec = item.section || "";
      if (!bySection[sec]) bySection[sec] = [];
      bySection[sec].push(item);
    }
    const sectionOrder = U.getSectionOrder(cid, cl.items);
    const hasUnsectioned = bySection[""] && bySection[""].length > 0;

    // rename from the title: PATCH {name}; empty or unchanged sends nothing
    const commitTitle = name => {
      const entry = S.all.find(c => c.id === cid);
      const finish = () => { setRenaming(false); bump(); };
      if (!entry || !name || name === entry.name) { finish(); return; }
      API.patch(`${BASE}/checklists/${cid}`, { name })
        .then(() => {
          entry.name = name;
          S.active.name = name;
        })
        .catch(e => toast(`couldn't rename — ${errMsg(e)}`))
        .then(finish);
    };

    const reset = () => {
      const checkedCount = S.active.items.filter(i => i.checked).length;
      const send = () => API.post(`${BASE}/checklists/${cid}/reset`, {})
        .then(fresh => { if (S.activeId !== cid) return; S.active = fresh; updateSidebarItem(); })
        .catch(e => toast(`couldn't reset — ${errMsg(e)}`));
      if (checkedCount === 0) { send(); return; }
      confirmDialog("reset checklist", `Uncheck all ${checkedCount} checked item(s)?`, { danger: true, confirmLabel: "reset" })
        .then(ok => { if (ok) send(); });
    };

    const delChecklist = () => {
      confirmDialog("delete checklist", `Delete "${S.active.name}"? This can't be undone.`, { danger: true, confirmLabel: "delete" }).then(ok => {
        if (!ok) return;
        API.del(`${BASE}/checklists/${cid}`).then(() => {
          S.all = S.all.filter(c => c.id !== cid);
          S.activeId = S.all.length ? S.all[0].id : null;
          S.active = null;
          if (S.activeId) {
            selectChecklist(S.activeId);
          } else {
            S.main = "empty";
            S.emptyMsg = "No checklists yet. Create one below.";
            bump();
          }
        }, e => toast(`couldn't delete checklist — ${errMsg(e)}`));
      });
    };

    return (
      <React.Fragment>
        <div className="cl-header">
          <div className="cl-header-left">
            {renaming
              ? <InlineEdit className="cl-title-input" initial={cl.name} onCommit={commitTitle} onCancel={() => setRenaming(false)} />
              : <div className="cl-title" title="Double-click to rename" onDoubleClick={() => setRenaming(true)}>{cl.name}</div>}
            {cl.description ? <div className="cl-description">{cl.description}</div> : null}
          </div>
          <div className="cl-header-actions">
            <button type="button" className="cl-btn" id="reset-btn" onClick={reset}>↺ Reset</button>
            <button type="button" className="cl-btn cl-btn-danger" id="delete-cl-btn" onClick={delChecklist}>Delete</button>
          </div>
        </div>

        <div className="cl-progress-bar-wrap">
          <div className="cl-progress-text">{`${checked} of ${total} checked${complete ? " — all done ✓" : ""}`}</div>
          <div className="cl-progress-bar">
            <div className={`cl-progress-fill${complete ? " complete" : ""}`} style={{ width: `${pct}%` }}></div>
          </div>
        </div>

        {sectionOrder.map(sec => <Section key={sec} name={sec} items={bySection[sec] || []} cid={cid} />)}
        {hasUnsectioned && <Section key="" name="" items={bySection[""]} cid={cid} />}

        <AddSectionRow cid={cid} />
      </React.Fragment>
    );
  }

  // The #cl-main pane: empty prompt, loading, load failure with retry, or the open checklist.
  function MainPane() {
    if (S.main === "loading") return <div className="cl-loading">Loading…</div>;
    if (S.main === "failed") {
      const id = S.activeId;
      return (
        <div className="hub-error">Couldn't load checklist — {S.mainErr}<button type="button" className="hub-error-retry" id="cl-select-retry" onClick={() => selectChecklist(id)}>retry</button></div>
      );
    }
    if (S.main === "ready" && S.active) return <Checklist key={S.active.id} />;
    return (
      <div className="hub-empty-state cl-empty-state">
        <div className="cl-empty-icon">☑</div>
        <p>{S.emptyMsg}</p>
      </div>
    );
  }

  Object.assign(U, { selectChecklist, MainPane });
})();
