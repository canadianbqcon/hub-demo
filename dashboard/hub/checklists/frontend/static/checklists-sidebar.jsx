/* Checklists · 2 of 4 (React): boot, sidebar and section state persistence, and the sidebar.
   Ported from app-sidebar.js: same DOM and classes, same requests. The localStorage
   keys (cl_sidebar_state, cl_section_state, cl_active_id) and their shapes are unchanged.
   Drop-target highlights are classList toggles on the dragged-over node, as before. */
(() => {
  const { useState, useRef } = React;
  const U = window.ChecklistsUI;
  const { API, BASE, S, D, InlineEdit, bump, toast, confirmDialog, errMsg, slugifyGroup, prettifyKey } = U;
  const sb = S.sidebar;

  // ── Sidebar state (localStorage) ──────────────────────────────────────────────

  function loadSidebarState() {
    try {
      const stored = JSON.parse(localStorage.getItem(U.STORAGE_KEY) || "{}");
      sb.groupLabels = stored.groupLabels || {};
      sb.groupOrder  = stored.groupOrder  || [];
      sb.collapsed   = stored.collapsed   || {};
      sb.itemOrder   = stored.itemOrder   || {};
    } catch {}
  }

  function saveSidebarState() {
    localStorage.setItem(U.STORAGE_KEY, JSON.stringify(sb));
  }

  // One-time reconciliation: older builds keyed user-made groups as "g-<timestamp>"
  // and kept the real name only in localStorage, so the db stored the random id.
  // New builds key groups by slug(name) and the db rename moves those rows to the
  // slug. Remap any lingering legacy keys in localStorage to match, so the group
  // doesn't split into a real one (with lists) + an empty ghost (old key).
  function migrateLegacyGroupKeys() {
    const legacy = (sb.groupOrder || []).filter(k => /^g-\d+$/.test(k));
    if (!legacy.length) return;
    for (const oldKey of legacy) {
      const label  = sb.groupLabels[oldKey] || oldKey;
      const newKey = slugifyGroup(label);
      if (!newKey || newKey === oldKey) continue;

      sb.groupOrder = [...new Set(sb.groupOrder.map(k => (k === oldKey ? newKey : k)))];

      sb.groupLabels[newKey] = label;
      delete sb.groupLabels[oldKey];

      if (sb.itemOrder[oldKey]) {
        const existing = sb.itemOrder[newKey] || [];
        sb.itemOrder[newKey] = [
          ...existing,
          ...sb.itemOrder[oldKey].filter(id => !existing.includes(id)),
        ];
        delete sb.itemOrder[oldKey];
      }

      if (sb.collapsed && oldKey in sb.collapsed) {
        sb.collapsed[newKey] = sb.collapsed[oldKey];
        delete sb.collapsed[oldKey];
      }
    }
    saveSidebarState();
  }

  function syncGroupOrder() {
    const defaultOrder  = ["packing", "activity", "general"];
    const defaultLabels = { packing: "Packing", activity: "Activity-Specific", general: "General" };

    if (sb.groupOrder.length === 0) {
      sb.groupOrder = [...defaultOrder];
    }

    const knownKeys = new Set(sb.groupOrder);

    for (const cl of S.all) {
      const key = cl.category || "general";
      if (!knownKeys.has(key)) {
        sb.groupOrder.push(key);
        knownKeys.add(key);
      }
    }

    for (const key of sb.groupOrder) {
      if (!sb.groupLabels[key]) {
        sb.groupLabels[key] = defaultLabels[key] || prettifyKey(key);
      }
    }
  }

  // ── Section state (localStorage) ─────────────────────────────────────────────

  function loadSectionState() {
    try { S.sections = JSON.parse(localStorage.getItem(U.SECTION_STORAGE_KEY) || "{}"); } catch { S.sections = {}; }
  }

  function saveSectionState() {
    localStorage.setItem(U.SECTION_STORAGE_KEY, JSON.stringify(S.sections));
  }

  function isSectionCollapsed(cid, name) {
    return !!(S.sections[cid]?.collapsed?.[name]);
  }

  // Derive section order for a checklist: stored order merged with any new sections from items.
  function getSectionOrder(cid, items) {
    const fromItems = [];
    const seen = new Set();
    for (const item of items) {
      const sec = item.section || "";
      if (sec !== "" && !seen.has(sec)) { seen.add(sec); fromItems.push(sec); }
    }
    if (!S.sections[cid]) S.sections[cid] = {};
    const stored = S.sections[cid].order || [];
    const merged = [...stored];
    const mergedSet = new Set(merged);
    for (const sec of fromItems) {
      if (!mergedSet.has(sec)) { merged.push(sec); mergedSet.add(sec); }
    }
    S.sections[cid].order = merged;
    saveSectionState();
    return merged;
  }

  // A group's lists in display order: the stored order first, then any not yet in it.
  function orderedLists(key, lists) {
    const storedOrder = sb.itemOrder[key] || [];
    return [
      ...storedOrder.map(id => lists.find(c => c.id === id)).filter(Boolean),
      ...lists.filter(c => !storedOrder.includes(c.id)),
    ];
  }

  // Return the id of the first checklist in sidebar display order.
  function firstSidebarId() {
    syncGroupOrder();
    for (const key of sb.groupOrder) {
      const lists   = S.all.filter(c => (c.category || "general") === key);
      const ordered = orderedLists(key, lists);
      if (ordered.length) return ordered[0].id;
    }
    return S.all[0]?.id ?? null;
  }

  // ── Boot ──────────────────────────────────────────────────────────────────────

  function boot() {
    loadSidebarState();
    migrateLegacyGroupKeys();
    loadSectionState();
    API.get(`${BASE}/checklists`).then(all => {
      S.all = all;
      S.boot = "ready";
      bump();
      if (S.all.length) {
        const storedId = +(localStorage.getItem(U.ACTIVE_KEY) || 0);
        const startId  = (storedId && S.all.find(c => c.id === storedId))
          ? storedId
          : firstSidebarId();
        if (startId) U.selectChecklist(startId);
      }
    }, e => {
      S.boot = "failed";
      S.bootErr = errMsg(e);
      bump();
    });
  }

  // ── Sidebar ───────────────────────────────────────────────────────────────────

  // perf: only re-sweep/re-apply the drop-target classes when the highlighted
  // row+side actually changes, instead of on every dragover fire (many/sec).
  const dragLast = { cur: null }; // { el, before }
  const clearDrop = () => {
    document.getElementById("sidebar-body")?.querySelectorAll(".cl-drop-before, .cl-drop-after")
      .forEach(n => { n.classList.remove("cl-drop-before", "cl-drop-after"); });
  };

  // Move a list to another group server-side; resolves false when the PATCH failed (already toasted).
  function moveToGroup(cl, targetKey) {
    return API.patch(`${BASE}/checklists/${cl.id}`, { category: targetKey }).then(() => {
      cl.category = targetKey;
      return true;
    }, e => {
      toast(`couldn't move list — ${errMsg(e)}`);
      return false;
    });
  }

  function SidebarItem({ cl, groupKey }) {
    const [editing, setEditing] = useState(false);
    const timer = useRef(null);
    const select = () => U.selectChecklist(cl.id);
    const complete = cl.total > 0 && cl.checked === cl.total;

    const onClick = e => {
      if (e.target.closest(".cl-drag-handle")) return;
      if (e.target.closest(".cl-item-name")) {
        clearTimeout(timer.current);
        timer.current = setTimeout(select, 220);
        return;
      }
      clearTimeout(timer.current);
      select();
    };

    // rename: PATCH {name}; empty or unchanged sends nothing
    const commit = name => {
      const finish = () => { setEditing(false); bump(); };
      if (!name || name === cl.name) { finish(); return; }
      API.patch(`${BASE}/checklists/${cl.id}`, { name })
        .then(() => {
          cl.name = name;
          if (S.active?.id === cl.id) S.active.name = name;
        })
        .catch(e => toast(`couldn't rename — ${errMsg(e)}`))
        .then(finish);
    };

    const onDragStart = e => {
      const el = e.currentTarget;
      D.clId = cl.id;
      D.groupKey = null;
      e.dataTransfer.effectAllowed = "move";
      e.stopPropagation();
      setTimeout(() => el.classList.add("cl-dragging"), 0);
    };
    const onDragEnd = e => {
      e.currentTarget.classList.remove("cl-dragging");
      clearDrop();
      D.clId = null;
      dragLast.cur = null;
    };
    const onDragOver = e => {
      if (D.clId === null || D.clId === cl.id) return;
      e.preventDefault();
      e.stopPropagation();
      const el = e.currentTarget;
      const rect = el.getBoundingClientRect();
      const before = e.clientY < rect.top + rect.height / 2;
      if (dragLast.cur && dragLast.cur.el === el && dragLast.cur.before === before) return;
      dragLast.cur = { el, before };
      clearDrop();
      el.classList.add(before ? "cl-drop-before" : "cl-drop-after");
    };
    const onDragLeave = e => {
      const el = e.currentTarget;
      if (!el.contains(e.relatedTarget)) {
        el.classList.remove("cl-drop-before", "cl-drop-after");
        if (dragLast.cur && dragLast.cur.el === el) dragLast.cur = null;
      }
    };
    const onDrop = e => {
      e.preventDefault();
      e.stopPropagation();
      const el = e.currentTarget;
      const isBefore = el.classList.contains("cl-drop-before");
      el.classList.remove("cl-drop-before", "cl-drop-after");
      dragLast.cur = null;

      if (D.clId === null || D.clId === cl.id) return;
      const dragId = D.clId;
      D.clId = null; // the move below remounts the row, so its dragend would never reach this root
      const dragged = S.all.find(c => c.id === dragId);
      if (!dragged) return;

      const sourceKey = dragged.category || "general";
      const targetKey = groupKey;

      const place = () => {
        sb.itemOrder[sourceKey] = (sb.itemOrder[sourceKey] || []).filter(id => id !== dragId);

        const targetOrder = (sb.itemOrder[targetKey] || []).filter(id => id !== dragId);
        const refIdx    = targetOrder.indexOf(cl.id);
        const insertAt  = refIdx < 0 ? targetOrder.length : (isBefore ? refIdx : refIdx + 1);
        targetOrder.splice(insertAt, 0, dragId);
        sb.itemOrder[targetKey] = targetOrder;

        saveSidebarState();
        bump();
      };
      if (sourceKey === targetKey) place();
      else moveToGroup(dragged, targetKey).then(ok => { if (ok) place(); });
    };

    return (
      <div className={`cl-sidebar-item${cl.id === S.activeId ? " active" : ""}`} data-id={cl.id} data-group={groupKey} draggable="true"
           onClick={onClick} onDragStart={onDragStart} onDragEnd={onDragEnd} onDragOver={onDragOver}
           onDragLeave={onDragLeave} onDrop={onDrop}>
        <span className="cl-drag-handle" title="Drag to move">⠿</span>
        {editing
          ? <InlineEdit className="cl-rename-input" initial={cl.name} onCommit={commit} onCancel={() => setEditing(false)} />
          : <span className="cl-item-name" onDoubleClick={e => { e.stopPropagation(); clearTimeout(timer.current); setEditing(true); }}>{cl.name}</span>}
        {cl.total > 0 && <span className={`cl-progress-pill${complete ? " complete" : ""}`}>{cl.checked}/{cl.total}</span>}
      </div>
    );
  }

  function Group({ gkey, lists }) {
    const [editing, setEditing] = useState(false);
    const label = sb.groupLabels[gkey] || gkey;
    const bodyRef = useRef(null);

    const delGroup = () => {
      const listsInGroup = S.all.filter(c => (c.category || "general") === gkey);
      const finish = () => {
        sb.groupOrder = sb.groupOrder.filter(k => k !== gkey);
        delete sb.groupLabels[gkey];
        saveSidebarState();
        bump();
      };
      if (listsInGroup.length === 0) { finish(); return; }
      confirmDialog("delete group", `Move ${listsInGroup.length} list(s) to "General" and delete this group?`, { danger: true, confirmLabel: "delete" }).then(ok => {
        if (!ok) return;
        // one PATCH per list, in order; the first failure stops the rest
        listsInGroup.reduce((p, cl) => p.then(() =>
          API.patch(`${BASE}/checklists/${cl.id}`, { category: "general" }).then(() => { cl.category = "general"; })
        ), Promise.resolve()).then(() => {
          if (!sb.groupOrder.includes("general")) {
            sb.groupOrder.push("general");
          }
          finish();
        }, e => { toast(`couldn't move lists — ${errMsg(e)}`); bump(); });
      });
    };

    // rename a group: labels live in localStorage only, so no request
    const commit = name => {
      if (name) {
        sb.groupLabels[gkey] = name;
        saveSidebarState();
      }
      setEditing(false);
      bump();
    };

    // ── header: drag a group to reorder; a list dragged over it targets the body ──
    const onHeadDragStart = e => {
      if (D.clId !== null) return;
      const el = e.currentTarget;
      D.groupKey = gkey;
      D.clId = null;
      e.dataTransfer.effectAllowed = "move";
      setTimeout(() => el.closest(".cl-group").classList.add("cl-dragging"), 0);
    };
    const onHeadDragEnd = e => {
      e.currentTarget.closest(".cl-group")?.classList.remove("cl-dragging");
      D.groupKey = null;
    };
    const onHeadDragOver = e => {
      // Checklist item drag over the header; highlight the body as the drop zone
      if (D.clId !== null) {
        e.preventDefault();
        bodyRef.current?.classList.add("cl-drop-target");
        return;
      }
      if (D.groupKey === null || D.groupKey === gkey) return;
      e.preventDefault();
      e.currentTarget.classList.add("cl-group-drop-target");
    };
    const onHeadDragLeave = e => {
      const el = e.currentTarget;
      if (!el.contains(e.relatedTarget)) {
        el.classList.remove("cl-group-drop-target");
        bodyRef.current?.classList.remove("cl-drop-target");
      }
    };
    const onHeadDrop = e => {
      e.preventDefault();
      e.currentTarget.classList.remove("cl-group-drop-target");
      bodyRef.current?.classList.remove("cl-drop-target");

      // Checklist item dropped on group header → move to this group
      if (D.clId !== null) {
        const dragId = D.clId;
        D.clId = null; // see SidebarItem's onDrop
        const cl = S.all.find(c => c.id === dragId);
        if (!cl) return;
        const sourceKey = cl.category || "general";
        const place = () => {
          sb.itemOrder[sourceKey] = (sb.itemOrder[sourceKey] || []).filter(id => id !== dragId);
          if (!sb.itemOrder[gkey]) sb.itemOrder[gkey] = [];
          if (!sb.itemOrder[gkey].includes(dragId)) {
            sb.itemOrder[gkey].push(dragId);
          }
          saveSidebarState();
          bump();
        };
        if (sourceKey === gkey) place();
        else moveToGroup(cl, gkey).then(ok => { if (ok) place(); });
        return;
      }

      if (D.groupKey === null || D.groupKey === gkey) return;
      const moved = D.groupKey;
      D.groupKey = null;
      const from = sb.groupOrder.indexOf(moved);
      const to   = sb.groupOrder.indexOf(gkey);
      if (from < 0 || to < 0) return;
      sb.groupOrder.splice(from, 1);
      sb.groupOrder.splice(to, 0, moved);
      saveSidebarState();
      bump();
    };

    // ── body: receives dropped checklists ──
    const onBodyDragOver = e => {
      if (D.clId === null) return;
      e.preventDefault();
      e.currentTarget.classList.add("cl-drop-target");
    };
    const onBodyDragLeave = e => {
      const el = e.currentTarget;
      if (!el.contains(e.relatedTarget)) el.classList.remove("cl-drop-target");
    };
    const onBodyDrop = e => {
      e.preventDefault();
      e.currentTarget.classList.remove("cl-drop-target");
      if (D.clId === null) return;
      const dragId = D.clId;
      D.clId = null; // see SidebarItem's onDrop
      const cl = S.all.find(c => c.id === dragId);
      if (!cl) return;
      if ((cl.category || "general") !== gkey) {
        moveToGroup(cl, gkey).then(ok => { if (ok) bump(); });
      }
    };

    return (
      <div className="cl-group" data-key={gkey}>
        <div className="cl-group-header" data-key={gkey} draggable="true"
             onDragStart={onHeadDragStart} onDragEnd={onHeadDragEnd} onDragOver={onHeadDragOver}
             onDragLeave={onHeadDragLeave} onDrop={onHeadDrop}>
          <span className="cl-drag-handle" title="Drag to reorder group">⠿</span>
          {editing
            ? <InlineEdit className="cl-rename-input" initial={label} onCommit={commit} onCancel={() => setEditing(false)} />
            : <span className="cl-group-label" onDoubleClick={e => { e.stopPropagation(); setEditing(true); }}>{label}</span>}
          <div className="cl-group-actions">
            <button type="button" className="cl-group-del" data-key={gkey} title="Delete group" onClick={delGroup}>✕</button>
          </div>
        </div>
        <div className="cl-group-body" data-key={gkey} ref={bodyRef}
             onDragOver={onBodyDragOver} onDragLeave={onBodyDragLeave} onDrop={onBodyDrop}>
          {lists.map(cl => <SidebarItem key={cl.id} cl={cl} groupKey={gkey} />)}
          {lists.length === 0 && <div className="cl-group-empty">Drop lists here</div>}
        </div>
      </div>
    );
  }

  // "+ New group" turns into an inline input; a name adds the group client-side (no request)
  function AddGroupRow() {
    const [adding, setAdding] = useState(false);
    const commit = name => {
      if (name) {
        const key = slugifyGroup(name);
        if (!sb.groupOrder.includes(key)) {
          sb.groupOrder.push(key);
        }
        sb.groupLabels[key] = name;
        saveSidebarState();
      }
      setAdding(false);
      bump();
    };
    return (
      <div className="cl-add-group-row">
        {adding
          ? <InlineEdit className="cl-rename-input cl-add-group-input" initial="" placeholder="Group name…" onCommit={commit} onCancel={() => setAdding(false)} />
          : <button type="button" id="add-group-btn" className="cl-add-group-btn" onClick={() => setAdding(true)}>+ New group</button>}
      </div>
    );
  }

  function SidebarBody() {
    if (S.boot === "loading") return <div className="cl-loading">Loading…</div>;
    if (S.boot === "failed") {
      return (
        <div className="hub-error">Couldn't load checklists — {S.bootErr}<button type="button" className="hub-error-retry" id="cl-boot-retry" onClick={boot}>retry</button></div>
      );
    }
    syncGroupOrder();
    const byKey = {};
    for (const cl of S.all) {
      const key = cl.category || "general";
      if (!byKey[key]) byKey[key] = [];
      byKey[key].push(cl);
    }
    return (
      <React.Fragment>
        {sb.groupOrder.map(key => <Group key={key} gkey={key} lists={orderedLists(key, byKey[key] || [])} />)}
        <AddGroupRow />
      </React.Fragment>
    );
  }

  Object.assign(U, { boot, syncGroupOrder, saveSectionState, isSectionCollapsed, getSectionOrder, SidebarBody });
})();
