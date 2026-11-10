/* Checklists · 1 of 4 (React): the API wrapper, storage keys, toast + themed confirm, and the
   shared mutable state every other file reads. Ported from app-core.js.
   Creates window.ChecklistsUI; the other three files assign into it and declare nothing at
   top level. The plain page re-rendered by hand after each mutation; here the mutations are
   unchanged and bump() asks the App to draw again. The toast and the confirm dialog stay
   imperative on the template's #cl-toast / #confirmScrim, which sit outside the React root. */
window.ChecklistsUI = window.ChecklistsUI || {};
(() => {
  const { useState, useEffect, useRef } = React;
  const U = window.ChecklistsUI;

  // 204 (section delete) has no body: resolve null instead of failing r.json() into a false error toast
  const API = {
    get:    url => fetch(url).then(r => r.json()),
    post:   (url, body) => fetch(url, { method: "POST",   headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(r => r.ok ? (r.status === 204 ? null : r.json()) : r.json().then(e => Promise.reject(e))),
    patch:  (url, body) => fetch(url, { method: "PATCH",  headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(r => r.ok ? (r.status === 204 ? null : r.json()) : r.json().then(e => Promise.reject(e))),
    // a failed DELETE (404/500) never rejects on its own, so the ok-check is what makes the
    // try/catch around each API.del() reachable
    del:    url => fetch(url, { method: "DELETE" }).then(r => r.ok ? r : Promise.reject(new Error(`${r.status} ${r.statusText}`))),
  };

  // human-readable text for a thrown value; never lets a raw object leak into a toast
  function errMsg(e) { return (e?.message) ? e.message : String(e); }

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // Group identity is stored in the DB as the checklist's `category` (the key).
  // Derive that key from the name the user types so the vault holds a real word
  // ("retired") instead of a throwaway "g-<timestamp>". Empty/symbol-only names
  // fall back to a timestamp key so creation never silently fails.
  function slugifyGroup(name) {
    const slug = String(name ?? "")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
    return slug || `g-${Date.now()}`;
  }

  // Turn a db-stored key ("winter-gear") into a display label ("Winter Gear")
  // so groups read correctly on any machine without relying on localStorage.
  function prettifyKey(key) {
    return String(key ?? "")
      .split("-")
      .filter(Boolean)
      .map(w => w.charAt(0).toUpperCase() + w.slice(1))
      .join(" ");
  }

  // ── Shared state ──────────────────────────────────────────────────────────────
  // `boot` and `main` are the loading / ready / failed states of the two panes; a pane draws
  // its data only when ready. activeId is the selection, active the loaded checklist, and a
  // response for a list that is no longer selected is dropped (see selectChecklist).
  const S = {
    boot: "loading", bootErr: "",
    all: [],
    activeId: null,
    active: null,
    main: "empty", mainErr: "", emptyMsg: "Select a checklist to get started.",
    // sidebar persistent state (localStorage)
    sidebar: { groupOrder: [], groupLabels: {}, itemOrder: {}, collapsed: {} },
    // section order per checklist (localStorage): { [checklistId]: { order: string[], collapsed: {} } }
    sections: {},
  };
  // drag state
  const D = { clId: null, groupKey: null, sectionName: null, itemId: null };

  const listeners = new Set();
  function bump() { listeners.forEach(fn => { fn(); }); }
  // the App calls this once; every other component reads S during the App's render
  function useStore() {
    const [, setN] = useState(0);
    useEffect(() => {
      const fn = () => setN(n => n + 1);
      listeners.add(fn);
      return () => { listeners.delete(fn); };
    }, []);
  }

  // ── Failure surfacing: toast + themed confirm (replaces bare awaits / native confirm()) ──

  let toastTimer = null;
  function toast(msg) {
    const t = document.getElementById("cl-toast");
    t.innerHTML = esc(msg);
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 4000);
  }
  // same as toast() but with an inline action button, held open longer
  function toastAction(msg, label, fn) {
    const t = document.getElementById("cl-toast");
    t.innerHTML = `${esc(msg)} <button class="hub-btn cl-toast-undo" id="cl-toast-action">${esc(label)}</button>`;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 5000);
    document.getElementById("cl-toast-action").onclick = () => {
      clearTimeout(toastTimer);
      t.hidden = true;
      fn();
    };
  }

  // themed confirm modal (replaces native confirm()); closeConfirmActive is the
  // cancel-resolver of whichever dialog is open, so the global Escape can close it
  U.closeConfirmActive = null;
  function confirmDialog(title, body, opts = {}) {
    return new Promise(resolve => {
      const scrim = document.getElementById("confirmScrim");
      const modal = document.getElementById("confirmModal");
      const trigger = document.activeElement; // restore focus here on close
      const done = v => {
        scrim.hidden = true;
        U.closeConfirmActive = null;
        document.removeEventListener("keydown", trapTab);
        if (trigger?.focus) trigger.focus();
        resolve(v);
      };
      // Tab/Shift+Tab cycles only among the modal's own focusable controls so
      // keyboard focus can't escape into the (still-present) page behind the scrim.
      const trapTab = e => {
        if (e.key !== "Tab") return;
        const focusable = [...modal.querySelectorAll("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])")]
          .filter(el => !el.disabled);
        if (!focusable.length) return;
        const first = focusable[0];
        const last  = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault(); last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault(); first.focus();
        }
      };
      modal.setAttribute("role", "dialog");
      modal.setAttribute("aria-modal", "true");
      modal.setAttribute("aria-labelledby", "cfTitle");
      modal.innerHTML = `
      <div class="hub-modal-title" id="cfTitle">${esc(title)}</div>
      <div class="hub-modal-body">${esc(body)}</div>
      <div class="hub-modal-actions">
        <button class="hub-modal-btn" id="cfCancel">cancel</button>
        <button class="hub-modal-btn${opts.danger ? " hub-modal-btn--danger" : ""}" id="cfOk">${esc(opts.confirmLabel || "confirm")}</button>
      </div>`;
      scrim.hidden = false;
      U.closeConfirmActive = () => done(false);
      document.getElementById("cfCancel").onclick = () => done(false);
      document.getElementById("cfOk").onclick = () => done(true);
      scrim.onclick = e => { if (e.target === scrim) done(false); };
      document.addEventListener("keydown", trapTab);
      document.getElementById("cfCancel").focus();
    });
  }

  // Reconcile the open checklist from the server; used after a persisted write
  // fails partway through an optimistic reorder, so the UI can't drift from the DB.
  // (promise chains throughout this surface, not async/await: babel's async helper would be a
  // second top-level global in every file that uses it, which jsx_globals_check refuses)
  function reloadActiveChecklist() {
    if (!S.active) return Promise.resolve();
    const cid = S.active.id;
    return API.get(`${U.BASE}/checklists/${cid}`)
      .then(cl => { if (S.activeId !== cid) return; S.active = cl; updateSidebarItem(); })
      .catch(e => toast(`couldn't refresh — ${errMsg(e)}`))
      .then(bump);
  }

  // keep the sidebar pill's counts in step with the open checklist
  function updateSidebarItem() {
    const cl = S.active;
    if (!cl) return;
    const entry = S.all.find(c => c.id === cl.id);
    if (entry) { entry.total = cl.items.length; entry.checked = cl.items.filter(i => i.checked).length; }
    bump();
  }

  // The inline editor every rename and add-row shares: focus + select on mount, Enter commits
  // through blur, Escape cancels, and a blur after either is ignored. onCommit gets the trimmed text.
  function InlineEdit({ className, initial, placeholder, onCommit, onCancel }) {
    const ref = useRef(null);
    const done = useRef(false);
    useEffect(() => { ref.current.focus(); ref.current.select(); }, []);
    return (
      <input ref={ref} type="text" className={className} defaultValue={initial} placeholder={placeholder}
             autoComplete={placeholder ? "off" : undefined}
             onKeyDown={e => {
               if (e.key === "Enter") { e.preventDefault(); e.currentTarget.blur(); }
               if (e.key === "Escape") { done.current = true; onCancel(); }
             }}
             onBlur={e => {
               if (done.current) return;
               done.current = true;
               onCommit(e.currentTarget.value.trim());
             }} />
    );
  }

  Object.assign(U, {
    InlineEdit,
    API, BASE: "/checklists/api",
    STORAGE_KEY: "cl_sidebar_state", SECTION_STORAGE_KEY: "cl_section_state", ACTIVE_KEY: "cl_active_id",
    errMsg, esc, slugifyGroup, prettifyKey, S, D, bump, useStore,
    toast, toastAction, confirmDialog, reloadActiveChecklist, updateSidebarItem,
  });
})();
