/* editing.jsx — shared primitives for the purchases React redesign:
   API helper, GET-hydrated inline-edit controls, modal + prompt, formatting,
   constants, error boundary. Loaded before the pane components. Classic-runtime
   globals (window.*), matching the Hub's chrome.jsx pattern. */

const { useState: eUseState, useEffect: eUseEffect, useRef: eUseRef, useId: eUseId, useMemo: eUseMemo } = React;

// Seven pipeline sections; decisions.stage uses the first six live keys plus
// the terminal decided/cancelled ("verdict" the section == "decided" the stage).
const PIPELINE_STAGES = ["need", "landscape", "priorities", "market", "candidates", "compare", "verdict"];
const STAGES = ["need", "landscape", "priorities", "market", "candidates", "compare", "decided", "cancelled"];
const SECTION_STATUSES = ["pending", "researching", "awaiting-you", "done", "skipped", "stale", "error"];
const CANDIDATE_STATUSES = ["considering", "shortlisted", "finalist", "chosen", "rejected", "purchased"];
const PRIORITIES = ["dealbreaker", "must-have", "nice-to-have"];
const SOURCE_TYPES = ["article", "reddit", "youtube", "forum", "professional", "owner-thread", "other"];

// Short rail-total labels for the 8 real STAGES — replaces a blind slice(0,5)
// that produced "LANDS/PRIOR/MARKE/COMPA/CANCE".
const STAGE_ABBR = {
  need: "need", landscape: "land", priorities: "prio", market: "mrkt",
  candidates: "cand", compare: "cmpr", decided: "done", cancelled: "cncl",
};

// friendlyError — maps a fetch/HTTP failure to plain language for the toast
// and modal error surfaces. status 0/undefined = network-level failure.
function friendlyError(status) {
  if (!status) return "Couldn't reach the server — check your connection and try again.";
  if (status >= 500) return "Server error — try again in a moment.";
  if (status === 404) return "That item is gone — refresh and try again.";
  if (status >= 400) return "That didn't save — check the values and try again.";
  return "Something went wrong — try again.";
}

// pToast — optional hook the root (PurchasesApp) registers on window so this
// shared fetch helper can drive the single #toast element without every
// caller threading state through. No-op until the root mounts.
function pToast(kind, msg) { if (window.__pToast) window.__pToast(kind, msg); }

// Mirrors vanilla api(): base /purchases, JSON body only when provided, 204 -> null,
// non-ok -> throw with method+path+status+text (preserved error handling). Also
// drives the shared toast: "saving…/loading…" while in flight, "saved" or a
// plain-language error on completion — the one place every mutation funnels
// through, so this single change covers every save/add/lock/delete at once.
const PAPI_BASE = "/purchases";
async function papi(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const isWrite = method !== "GET";
  pToast("pending", isWrite ? "saving…" : "loading…");
  let r;
  try { r = await fetch(PAPI_BASE + path, opts); }
  catch (netErr) { pToast("err", friendlyError(0)); throw netErr; }
  if (r.status === 204) { pToast(isWrite ? "ok" : null, "saved"); return null; }
  if (!r.ok) {
    const err = await r.text();
    pToast("err", friendlyError(r.status));
    throw new Error(`${method} ${path}: ${r.status} ${err}`);
  }
  const data = await r.json();
  pToast(isWrite ? "ok" : null, "saved");
  return data;
}

const fmtMoney = (v, ccy = "USD") => {
  if (v == null || v === "") return "—";
  try { return new Intl.NumberFormat(undefined, { style: "currency", currency: ccy }).format(v); }
  catch { return `${ccy} ${v}`; }
};
const truncate = (s, n) => (s && s.length > n ? `${s.slice(0, n - 1)}…` : s || "");

// bulletList: returns a React node. Splits on newline, else on ". " (matches vanilla).
function bulletList(str) {
  if (!str) return "—";
  const items = (str.includes("\n") ? str.split("\n") : str.split(/\.\s+/))
    .map(s => s.trim().replace(/\.$/, "")).filter(Boolean);
  if (!items.length) return str;
  return <ul className="bullet-list">{items.map((s, i) => <li key={i}>{s}</li>)}</ul>;
}

/* Editable — click-to-edit text/number/multiline. `value` is hydrated from the
   server GET payload by the parent. onSave(nv) fires ONLY when the trimmed value
   actually changed; the parent issues the single-field PATCH. This is the core of
   the GET-hydration invariant: an unedited or reverted field never sends a write,
   so no unhydrated blank can wipe a column. Escape reverts. */
function Editable({ value, number = false, multiline = false, displayFn = null, onSave, placeholder = "—" }) {
  const [editing, setEditing] = eUseState(false);
  const cur = (value === "" || value == null) ? null : value;
  const display = displayFn ? displayFn(cur) : (cur != null ? String(cur) : placeholder);

  if (!editing) {
    // already a fully accessible custom control (role="button", tabIndex, onClick, onKeyDown for Enter/Space) — swapping to <button> would need a CSS reset for this inline value display.
    return <div className={`editable-value${cur == null ? " editable-empty" : ""}`}
                role="button" tabIndex={0}
                onClick={() => setEditing(true)}
                onKeyDown={e => { if (e.key === "Enter") setEditing(true); else if (e.key === " ") { e.preventDefault(); setEditing(true); } }}>{display}</div>;
  }
  const commit = (e) => {
    const raw = e.target.value.trim();
    const nv = number ? (raw !== "" ? parseFloat(raw) : null) : (raw || null);
    setEditing(false);
    if (nv !== cur) onSave(nv);
  };
  const onKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey && !multiline) { e.preventDefault(); e.target.blur(); }
    if (e.key === "Escape") { e.target.value = cur != null ? String(cur) : ""; setEditing(false); }
  };
  const common = {
    className: "editable-input", autoFocus: true, defaultValue: cur != null ? String(cur) : "",
    onBlur: commit, onKeyDown: onKey,
  };
  return multiline ? <textarea {...common} /> : <input type={number ? "number" : "text"} {...common} />;
}

function EditableSelect({ value, options, onSave, placeholder = "\u2014" }) {
  const [editing, setEditing] = eUseState(false);
  // already a fully accessible custom control (role="button", tabIndex, onClick, onKeyDown for Enter/Space) — swapping to <button> would need a CSS reset for this inline value display.
  if (!editing) return <div className="editable-value" role="button" tabIndex={0}
    onClick={() => setEditing(true)}
    onKeyDown={e => { if (e.key === "Enter") setEditing(true); else if (e.key === " ") { e.preventDefault(); setEditing(true); } }}>{value || placeholder}</div>;
  return (
    <select className="editable-input editable-select" autoFocus defaultValue={value || ""}
      onChange={(e) => { setEditing(false); if (e.target.value !== value) onSave(e.target.value); }}
      onBlur={() => setEditing(false)}>
      {options.map(o => <option key={o} value={o}>{o}</option>)}
    </select>
  );
}

// inline status dropdown (always visible, not click-to-edit) — matches vanilla statusSelect
function StatusSelect({ value, options, onChange }) {
  return (
    <select className="inline-select" value={value} onChange={(e) => onChange(e.target.value)}>
      {options.map(o => <option key={o} value={o}>{o}</option>)}
    </select>
  );
}

/* useListFilter: the purchases-side host for the shared HubListFilter
   control (static/js/list-filter.js). Mounts once into `ref.current`, keeps
   it fed with `rows` on every change, and holds the filtered/sorted result
   plus state in React state, so a caller that needs to know the active sort
   (ProjectRail's grouping) never calls apply() itself. `cfg` is read once at
   mount (a module-level object, never rebuilt per render, is what every
   caller passes); mirrors mount()'s own "cfg doesn't change" assumption.
   list-filter.js missing (failed to load) -> rows pass through unfiltered,
   per the spec's failure-mode table. */
function useListFilter(ref, cfg, rows) {
  const cfgRef = eUseRef(cfg);
  const ctrlRef = eUseRef(null);
  const [result, setResult] = eUseState({ rows: [], counts: {} });
  const [state, setState] = eUseState(null);

  eUseEffect(() => {
    if (!window.HubListFilter || !ref.current) return;
    const ctrl = window.HubListFilter.mount(ref.current, Object.assign({}, cfgRef.current, {
      onChange: (st, res) => { setState(st); setResult(res); },
    }));
    ctrlRef.current = ctrl;
    return () => { ctrl.destroy(); ctrlRef.current = null; };
  }, []); // mount once; the DOM node and the cfg are both stable for the component's life

  eUseEffect(() => { if (ctrlRef.current) ctrlRef.current.update(rows); }, [rows]);

  // filter `rows` in render rather than trusting result.rows, which lags one
  // render behind a rows change; a caller effect reading it could pick a row
  // that was just deleted.
  const fresh = eUseMemo(
    () => (window.HubListFilter && state ? window.HubListFilter.apply(rows, cfgRef.current, state) : null),
    [rows, state]);
  if (!window.HubListFilter) return { rows, counts: {}, state: null };
  if (fresh) return { rows: fresh.rows, counts: fresh.counts, state };
  return { rows: result.rows, counts: result.counts, state };
}

// useDialogKeydown — shared Escape-to-close + Tab focus-trap for Modal/ConfirmModal.
// Tab past the last focusable in panelRef wraps to the first; Shift+Tab past the
// first wraps to the last. Keeps keyboard focus from ever reaching the page
// behind the (visually) modal scrim.
function useDialogKeydown(panelRef, onClose) {
  eUseEffect(() => {
    const fn = (e) => {
      if (e.key === "Escape") { onClose(); return; }
      if (e.key !== "Tab" || !panelRef.current) return;
      const focusables = panelRef.current.querySelectorAll(
        'input, textarea, select, button, [href], [tabindex]:not([tabindex="-1"])'
      );
      if (!focusables.length) return;
      const first = focusables[0], last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", fn); return () => window.removeEventListener("keydown", fn);
  }, [onClose]);
}

/* Modal — the form dialog's frame. The hub's .hub-modal (base.css), same as
   ConfirmModal below: one scrim, one panel, one title face across the page. */
function Modal({ title, children, onClose }) {
  const titleId = eUseId();
  const panelRef = eUseRef(null);
  useDialogKeydown(panelRef, onClose);
  // mount-only: focus the first field, restore focus to whatever opened the
  // modal on close. Deliberately NOT in the escape-key effect above (that one
  // re-runs whenever onClose's identity changes) — re-running this would steal
  // focus back to the first field mid-edit.
  eUseEffect(() => {
    const prevFocused = document.activeElement;
    const first = panelRef.current?.querySelector("input, textarea, select, button");
    if (first) first.focus();
    return () => { if (prevFocused?.focus) prevFocused.focus(); };
  }, []);
  return (
    <div className="hub-modal-scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="hub-modal hub-modal--wide" ref={panelRef} role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <h3 id={titleId} className="hub-modal-title">{title}</h3>{children}
      </div>
    </div>
  );
}

/* PromptModal — replaces vanilla openPrompt. Controlled inputs built from a fields
   spec; submits via <form onSubmit> with preventDefault; calls onSave(values). A
   thrown Error is shown inline (.hub-error) instead of a native alert() — a plain
   validation message ("Name required") passes through as-is, an underlying papi()
   failure (shape "METHOD /path: 500 …") is swapped for plain language.
   fields: [{name, label, type?:'text'|'number'|'textarea'|'select'|'date', options?, value?, placeholder?, rows?}] */
function PromptModal({ title, fields, saveLabel = "Save", onSave, onClose }) {
  const init = {};
  fields.forEach(f => { init[f.name] = f.value != null ? String(f.value) : ""; });
  const [vals, setVals] = eUseState(init);
  const [err, setErr] = eUseState(null);
  const [busy, setBusy] = eUseState(false);
  const set = (k, v) => setVals(s => ({ ...s, [k]: v }));
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try { await onSave({ ...vals }); onClose(); }
    catch (err) {
      console.error("[purchases] save failed", err);
      const isHttp = /: \d{3}\b/.test(err.message || "");
      setErr(isHttp ? friendlyError(0) : (err.message || "Couldn't save — try again."));
    } finally { setBusy(false); }
  };
  return (
    <Modal title={title} onClose={onClose}>
      <form onSubmit={submit}>
        <div className="modal-fields">
          {fields.map(f => {
            const fid = `pm-field-${f.name}`;
            return (
              <div key={f.name} className="hub-field form-field">
                <label htmlFor={fid}>{f.label}</label>
                {f.type === "textarea"
                  ? <textarea id={fid} className="form-input" rows={f.rows || 2} placeholder={f.placeholder || ""}
                      value={vals[f.name]} onChange={e => set(f.name, e.target.value)} />
                  : f.type === "select"
                  ? <select id={fid} className="form-input" value={vals[f.name]} onChange={e => set(f.name, e.target.value)}>
                      {f.options.map(o => <option key={o} value={o}>{o}</option>)}
                    </select>
                  : <input id={fid} className="form-input" type={f.type || "text"} placeholder={f.placeholder || ""}
                      value={vals[f.name]} onChange={e => set(f.name, e.target.value)} />}
              </div>
            );
          })}
        </div>
        {err && <div className="hub-error">{err}</div>}
        <div className="hub-modal-actions">
          <button type="button" className="hub-modal-btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="hub-modal-btn hub-modal-btn--primary" disabled={busy}>{busy ? "Saving…" : saveLabel}</button>
        </div>
      </form>
    </Modal>
  );
}

/* ConfirmModal — replaces native confirm() for destructive actions. Uses the
   shared hub-modal-* classes (base.css), per the cross-page themed-dialog
   convention. onConfirm's own failure surfaces
   inline instead of the caller finding out via a swallowed exception. */
function ConfirmModal({ title, body, danger = true, confirmLabel = "Delete", onConfirm, onClose }) {
  const [err, setErr] = eUseState(null);
  const [busy, setBusy] = eUseState(false);
  const titleId = eUseId();
  const panelRef = eUseRef(null);
  useDialogKeydown(panelRef, onClose);
  // mount-only focus-in / focus-restore-on-close — see Modal's identical comment.
  eUseEffect(() => {
    const prevFocused = document.activeElement;
    const first = panelRef.current?.querySelector("button");
    if (first) first.focus();
    return () => { if (prevFocused?.focus) prevFocused.focus(); };
  }, []);
  const confirm = async () => {
    setBusy(true); setErr(null);
    try { await onConfirm(); }
    catch (e) { console.error("[purchases] confirm action failed", e); setErr(friendlyError(0)); }
    finally { setBusy(false); }
  };
  return (
    <div className="hub-modal-scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="hub-modal" ref={panelRef} role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <h3 id={titleId} className="hub-modal-title">{title}</h3>
        {body ? <p className="hub-modal-body">{body}</p> : null}
        {err && <div className="hub-error">{err}</div>}
        <div className="hub-modal-actions">
          <button type="button" className="hub-modal-btn" onClick={onClose}>Cancel</button>
          <button type="button" className={`hub-modal-btn${danger ? " hub-modal-btn--danger" : ""}`}
            disabled={busy} onClick={confirm}>{busy ? "Working…" : confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}

class PErrorBoundary extends React.Component {
  constructor(p) { super(p); this.state = { err: null }; }
  static getDerivedStateFromError(err) { return { err }; }
  componentDidCatch(err, info) { console.error("[purchases] render error", err, info); }
  render() {
    if (this.state.err) {
      return <div className="pe-crash">
        <h3>Something broke in the purchases UI.</h3>
        <pre>{String(this.state.err)}</pre>
      </div>;
    }
    return this.props.children;
  }
}

/* SectionGlyph — the per-tab status marker. awaiting-you is the only
   accent-colored state; researching pulses (reduced-motion: static). */
const SECTION_GLYPHS = {
  "pending": "·", "researching": "◌", "awaiting-you": "❯",
  "done": "✓", "skipped": "–", "stale": "↻", "error": "!",
};
function SectionGlyph({ status }) {
  const st = status || "pending";
  return <span className={`section-glyph sg-${st}`} title={st}>{SECTION_GLYPHS[st]}</span>;
}

Object.assign(window, {
  papi, fmtMoney, truncate, bulletList, friendlyError,
  Editable, EditableSelect, StatusSelect, Modal, PromptModal, ConfirmModal, PErrorBoundary,
  STAGES, STAGE_ABBR, CANDIDATE_STATUSES, PRIORITIES, SOURCE_TYPES,
  PIPELINE_STAGES, SECTION_STATUSES, SectionGlyph, useListFilter,
});
