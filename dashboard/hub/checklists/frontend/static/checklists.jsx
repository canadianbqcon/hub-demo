/* Checklists · 4 of 4 (React): the new-checklist dialog, the App that draws the two panes, and
   the mount. Ported from app.js. The React root is the template's .cl-layout (the shell and
   its top bar stay as they were); the sidebar's static header and footer are redrawn here so
   they sit in the same place as before. Render errors land in Boundary; errors in async code
   and event handlers are toasted where they happen, as on the plain page. */
(() => {
  const { useState, useEffect } = React;
  const U = window.ChecklistsUI;
  const { API, BASE, S, toast, errMsg } = U;

  // ── New checklist dialog ──────────────────────────────────────────────────────

  function NewModal({ onClose }) {
    const [name, setName] = useState("");
    const [category, setCategory] = useState(S.sidebar.groupOrder[0] || "");
    const [description, setDescription] = useState("");

    // Esc closes it too, for consistency with every inline editor on the page.
    useEffect(() => {
      const onKey = e => { if (e.key === "Escape") onClose(); };
      document.addEventListener("keydown", onKey);
      return () => document.removeEventListener("keydown", onKey);
    }, [onClose]);

    const create = () => {
      const n = name.trim();
      if (!n) return;
      API.post(`${BASE}/checklists`, { name: n, category, description: description.trim() }).then(cl => {
        cl.total = 0;
        cl.checked = 0;
        S.all.push(cl);
        onClose();
        return U.selectChecklist(cl.id);
      }).catch(e => toast(`couldn't create checklist — ${errMsg(e)}`));
    };

    return ReactDOM.createPortal(
      <div className="hub-modal-scrim cl-modal-backdrop" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
        <div className="cl-modal">
          <h2>New Checklist</h2>
          <div>
            <label htmlFor="modal-name">Name</label>
            <input type="text" id="modal-name" placeholder="Checklist name" autoComplete="off" autoFocus
                   value={name} onChange={e => setName(e.target.value)} />
          </div>
          <div>
            <label htmlFor="modal-cat">Group</label>
            <select id="modal-cat" value={category} onChange={e => setCategory(e.target.value)}>
              {S.sidebar.groupOrder.map(key => <option key={key} value={key}>{S.sidebar.groupLabels[key] || key}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="modal-desc">Description (optional)</label>
            <input type="text" id="modal-desc" placeholder="e.g. Sony a6300" autoComplete="off"
                   value={description} onChange={e => setDescription(e.target.value)} />
          </div>
          <div className="cl-modal-actions">
            <button type="button" className="cl-btn" id="modal-cancel" onClick={onClose}>Cancel</button>
            <button type="button" className="cl-btn cl-btn-primary" id="modal-create" onClick={create}>Create</button>
          </div>
        </div>
      </div>,
      document.body
    );
  }

  // ── App ───────────────────────────────────────────────────────────────────────

  const root = document.querySelector(".cl-layout");

  function App() {
    U.useStore();
    const [modal, setModal] = useState(false);
    useEffect(() => {
      root.setAttribute("data-react-mounted", "checklists");
      U.boot();
    }, []);
    const closeModal = React.useCallback(() => setModal(false), []);
    return (
      <React.Fragment>
        <aside className="cl-sidebar">
          <div className="cl-sidebar-header">
            <span className="cl-sidebar-title">Lists</span>
            <span className="cl-sidebar-meta">Drag to reorder · group to organize</span>
          </div>
          <div className="cl-sidebar-body" id="sidebar-body">
            <U.SidebarBody />
          </div>
          <div className="cl-sidebar-footer">
            <button type="button" className="cl-new-btn" id="new-checklist-btn" onClick={() => { U.syncGroupOrder(); setModal(true); }}>+ New checklist</button>
          </div>
        </aside>

        <main className="cl-main" id="cl-main">
          <U.MainPane />
        </main>
        {modal && <NewModal onClose={closeModal} />}
      </React.Fragment>
    );
  }

  // Render errors land here; async/handler errors are caught where they happen.
  class Boundary extends React.Component {
    constructor(p) { super(p); this.state = { err: null }; }
    static getDerivedStateFromError(err) { return { err }; }
    componentDidCatch(err) { console.error("[checklists] render failed", err); }
    render() { return this.state.err ? <div className="hub-error">page failed to load</div> : this.props.children; }
  }

  // Global Escape: closes whichever themed confirm dialog is open.
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && U.closeConfirmActive) U.closeConfirmActive();
  });

  ReactDOM.createRoot(root).render(<Boundary><App /></Boundary>);
})();
