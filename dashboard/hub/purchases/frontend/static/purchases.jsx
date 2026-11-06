/* purchases.jsx — root of the purchases React 3-pane redesign. Owns all data
   state, the fetch/refresh layer, the modal dispatcher, and the shared
   Hub chrome (Topbar and StatusStrip from topbar.jsx). Data
   model matches the vanilla page: fetch projects -> project -> full decision; every
   mutation PATCH/POST/DELETE then re-fetch. /purchases/api/* endpoints unchanged. */

const { useState: pUseState, useEffect: pUseEffect, useCallback: pUseCallback, useRef: pUseRef } = React;

function PurchasesApp() {
  // Two halves, not two pages: "decisions" is the research pipeline, "orders" is
  // what came of it. They share the chrome and the modal dispatcher, so the mode
  // is one piece of state rather than a second route.
  const [mode, setMode] = pUseState("decisions");
  const [ordersKey, setOrdersKey] = pUseState(0);
  const [projects, setProjects] = pUseState([]);
  const [selectedProjectId, setSelectedProjectId] = pUseState(null);
  const [decision, setDecision] = pUseState(null);
  const [selectedCandidateId, setSelectedCandidateId] = pUseState(null);
  const [railCollapsed, setRailCollapsed] = pUseState(false);
  const [modal, setModal] = pUseState(null); // {type, ...} | null
  const [loadErr, setLoadErr] = pUseState(null);
  const [loading, setLoading] = pUseState(false); // a decision switch is in flight
  const [toast, setToast] = pUseState(null); // {kind: 'pending'|'ok'|'err', msg} | null
  const toastTimer = pUseRef(null);

  // papi() (editing.jsx) drives this via window.__pToast so every mutation gets
  // pending/success/error feedback without threading state through every caller.
  // pending holds until replaced; ok/err auto-clear (err lingers longer to read).
  pUseEffect(() => {
    window.__pToast = (kind, msg) => {
      if (toastTimer.current) { clearTimeout(toastTimer.current); toastTimer.current = null; }
      if (kind == null) { setToast(null); return; }
      setToast({ kind, msg });
      if (kind !== "pending") toastTimer.current = setTimeout(() => setToast(null), kind === "err" ? 4000 : 1600);
    };
    return () => { window.__pToast = null; };
  }, []);

  const loadDecisionFor = pUseCallback(async (pid) => {
    const proj = await papi("GET", `/api/projects/${pid}`);
    if (proj.decisions && proj.decisions.length > 0) {
      setDecision(await papi("GET", `/api/decisions/${proj.decisions[0].id}`));
    } else { setDecision(null); }
  }, []);

  const refreshProjects = pUseCallback(async () => {
    const list = await papi("GET", "/api/projects");
    setProjects(list);
    return list;
  }, []);

  const selectProject = pUseCallback(async (pid) => {
    setSelectedProjectId(pid);
    setSelectedCandidateId(null);
    setLoading(true);
    try { await loadDecisionFor(pid); } catch (e) { console.error("[purchases] load failed", e); setLoadErr(String(e)); }
    finally { setLoading(false); }
  }, [loadDecisionFor]);

  // re-fetch current decision after a mutation (keeps selectedCandidateId)
  const refresh = pUseCallback(async () => {
    await refreshProjects();
    if (selectedProjectId) { try { await loadDecisionFor(selectedProjectId); } catch (e) { console.error("[purchases] load failed", e); setLoadErr(String(e)); } }
  }, [refreshProjects, selectedProjectId, loadDecisionFor]);

  // initial load
  pUseEffect(() => {
    (async () => {
      try {
        const list = await refreshProjects();
        if (list.length > 0) await selectProject(list[0].id);
      } catch (e) { console.error("[purchases] load failed", e); setLoadErr(String(e)); }
    })();
  }, []); // eslint-disable-line

  // retry affordance for the .hub-error banner — re-runs whichever load path
  // was in flight (a selected project's decision, or the initial project list).
  const retryLoad = pUseCallback(async () => {
    setLoadErr(null);
    try {
      if (selectedProjectId) await refresh();
      else { const list = await refreshProjects(); if (list.length > 0) await selectProject(list[0].id); }
    } catch (e) { console.error("[purchases] retry failed", e); setLoadErr(String(e)); }
  }, [selectedProjectId, refresh, refreshProjects, selectProject]);

  // single-field decision PATCH — the only path inline-edits use, so exactly one
  // hydrated field is ever sent (GET-hydration invariant).
  const patchDecision = pUseCallback(async (field, nv) => {
    if (!decision) return;
    await papi("PATCH", `/api/decisions/${decision.id}`, { [field]: nv });
    await refresh();
  }, [decision, refresh]);

  return (
    <PErrorBoundary>
      <div className="hub-shell pe-shell" data-screen-label="purchases">
        <Topbar crumb="purchases" />
        {/* Two columns, not three. The spec contract used to be a permanent
            third pane; it is a per-tab share of the arena now, so the arena
            owns it (see DecisionArena's .pe-split). */}
        <div className="hub-tabs surface-tabs pe-modes">
          {[["decisions", "the pipeline"], ["orders", "what you bought"]].map(([k, stub]) => (
            <button type="button" key={k} className={`hub-tab surface-tab${mode === k ? " active" : ""}`}
              onClick={() => setMode(k)}>
              {k}
              {mode === k ? <span className="stub">{stub}</span> : null}
            </button>
          ))}
        </div>
        {mode === "orders" ? (
          /* Same two-track body the decisions half uses: orders renders its own
             rail into the first track and its own arena into the second, so the
             two halves of this page are one layout rather than two. */
          <div className="pe-body">
            <OrdersTab setModal={setModal} reloadKey={ordersKey} />
          </div>
        ) : (
        <div className="pe-body">
          <ProjectRail
            projects={projects} selectedProjectId={selectedProjectId} decision={decision}
            collapsed={railCollapsed} onToggleCollapse={() => setRailCollapsed(c => !c)}
            onSelect={selectProject}
            onNewProject={() => setModal({ type: "new-project" })}
          />
          <DecisionArena
            decision={decision} loading={loading} selectedCandidateId={selectedCandidateId}
            onPatchDecision={patchDecision} onSelectCandidate={setSelectedCandidateId}
            refresh={refresh} setModal={setModal}
          />
        </div>
        )}
        <StatusStrip />
        {modal && <PurchaseModals modal={modal} decision={decision} selectedProjectId={selectedProjectId}
          onClose={() => setModal(null)} refresh={refresh} selectProject={selectProject}
          refreshProjects={refreshProjects} bumpOrders={() => setOrdersKey(k => k + 1)} />}
        {loadErr && (
          <div className="hub-error pe-loaderr" role="alert">
            Couldn't load your purchase data.
            <button type="button" className="hub-error-retry" onClick={retryLoad}>Retry</button>
            <button type="button" className="hub-error-retry" onClick={() => setLoadErr(null)}>Dismiss</button>
          </div>
        )}
        {toast && <div id="toast" className={`show ${toast.kind}`}>{toast.msg}</div>}
      </div>
    </PErrorBoundary>
  );
}


/* The fields an order carries. Shared by the add and edit modals so the two can
   never drift — an order you typed and one you corrected answer the same
   questions. */
const ORDER_MODAL_FIELDS = (o = {}) => ([
  { name: "item", label: "What did you buy?", value: o.item, placeholder: "Monos Hybrid Carry-On" },
  { name: "vendor", label: "Vendor", value: o.vendor, placeholder: "Amazon / Best Buy / direct" },
  { name: "order_number", label: "Order number", value: o.order_number },
  { name: "ordered_on", label: "Ordered on", value: o.ordered_on, placeholder: "2026-09-05" },
  { name: "total", label: "Total paid", type: "number", value: o.total ?? "" },
  { name: "ship_status", label: "Status", type: "select", options: ORDER_STATUSES, value: o.ship_status || "ordered" },
  { name: "carrier", label: "Carrier", type: "select", options: window.CARRIER_OPTIONS || [""], value: o.carrier || "" },
  { name: "tracking_number", label: "Tracking number", value: o.tracking_number, placeholder: "1Z999AA10123456784" },
  { name: "eta", label: "ETA", value: o.eta, placeholder: "2026-09-12" },
  { name: "delivered_on", label: "Delivered on", value: o.delivered_on, placeholder: "left blank until it lands" },
  { name: "delivery_address", label: "Delivering to", value: o.delivery_address, placeholder: "street, city, state zip — this is what the map pins" },
  { name: "return_days", label: "Return window (days)", type: "number", value: o.return_days ?? "", placeholder: "30" },
  { name: "return_by", label: "Return by (overrides the window)", value: o.return_by },
  { name: "return_policy", label: "Return policy", type: "textarea", value: o.return_policy },
  { name: "url", label: "Product URL", value: o.url },
  { name: "notes", label: "Notes", type: "textarea", value: o.notes },
]);

const orderPayload = (v) => ({
  ...v,
  total: v.total === "" ? null : parseFloat(v.total),
  return_days: v.return_days === "" ? null : parseInt(v.return_days, 10),
});

/* PurchaseModals — modal dispatcher. Each branch renders a PromptModal with the
   EXACT payload shapes from payload-baselines.md Surface 3. */
function PurchaseModals({ modal, decision, onClose, refresh, selectProject, refreshProjects, bumpOrders }) {
  const did = decision?.id;
  const t = modal.type;

  if (t === "new-project") {
    return <PromptModal title="New Project" saveLabel="Create Decision" onClose={onClose}
      fields={[
        { name: "name", label: "What are you deciding?", placeholder: "Pick noise-cancelling headphones" },
        { name: "category", label: "Category", placeholder: "audio" },
        { name: "purchase_type", label: "Purchase type", type: "select",
          options: ["one-time-product","recurring-service","saas","service-contract"], value: "one-time-product" },
        { name: "budget_max", label: "Budget max", type: "number", placeholder: "500" },
        { name: "time_horizon", label: "Time horizon", placeholder: "this week / Q3 / later" },
        { name: "use_context", label: "Use", type: "textarea", placeholder: "What will you use this for?" },
        { name: "pain_point", label: "Pain point", type: "textarea" },
      ]}
      onSave={async (v) => {
        const name = (v.name || "").trim();
        if (!name) throw new Error("Name required");
        const category = (v.category || "").trim();
        const project = await papi("POST", "/api/projects", { name, category, status: "active" });
        await papi("POST", "/api/decisions", {
          project_id: project.id, name, category,
          purchase_type: v.purchase_type,
          budget_max: v.budget_max ? parseFloat(v.budget_max) : null,
          time_horizon: (v.time_horizon || "").trim(),
          use_context: (v.use_context || "").trim(),
          pain_point: (v.pain_point || "").trim(),
          stage: "need",
        });
        await refreshProjects();
        await selectProject(project.id);
      }} />;
  }

  if (t === "new-order") {
    return <PromptModal title="Add an order" saveLabel="Add order" onClose={onClose}
      fields={ORDER_MODAL_FIELDS()}
      onSave={async (v) => {
        if (!v.item.trim()) throw new Error("Name the thing you bought");
        await papi("POST", "/api/orders", orderPayload(v));
        bumpOrders?.();
      }} />;
  }

  if (t === "edit-order") {
    const o = modal.order;
    return <PromptModal title={`Edit order: ${o.item}`} onClose={onClose}
      fields={ORDER_MODAL_FIELDS(o)}
      onSave={async (v) => {
        await papi("PATCH", `/api/orders/${o.id}`, orderPayload(v));
        bumpOrders?.();
        await refresh();
      }} />;
  }

  if (t === "new-candidate") {
    return <PromptModal title="Add Candidate" saveLabel="Add Candidate" onClose={onClose}
      fields={[
        { name: "name", label: "Product / service name", placeholder: "Sony WH-1000XM5" },
        { name: "vendor", label: "Vendor", placeholder: "Amazon / Best Buy / direct" },
        { name: "base_price", label: "Base price", type: "number", placeholder: "399" },
        { name: "url", label: "URL", placeholder: "https://..." },
        { name: "status", label: "Status", type: "select", options: CANDIDATE_STATUSES, value: "considering" },
      ]}
      onSave={async (v) => {
        if (!v.name.trim()) throw new Error("Name required");
        await papi("POST", `/api/decisions/${did}/candidates`, {
          name: v.name.trim(), vendor: v.vendor.trim(),
          base_price: v.base_price ? parseFloat(v.base_price) : null,
          url: v.url.trim(), status: v.status,
        });
        await refresh();
      }} />;
  }

  if (t === "edit-candidate") {
    const c = modal.candidate;
    return <PromptModal title={`Edit candidate: ${c.name}`} onClose={onClose}
      fields={[
        { name: "name", label: "Name", value: c.name },
        { name: "vendor", label: "Vendor", value: c.vendor },
        { name: "base_price", label: "Base price", type: "number", value: c.base_price ?? "" },
        { name: "url", label: "URL", value: c.url },
        { name: "image_url", label: "Product image URL", value: c.image_url, placeholder: "https://... (shown on the verdict tab)" },
        { name: "ecosystem_notes", label: "Ecosystem / lock-in", type: "textarea", value: c.ecosystem_notes },
        { name: "return_policy", label: "Return policy", value: c.return_policy },
        { name: "warranty", label: "Warranty", value: c.warranty },
        { name: "notes", label: "Notes", type: "textarea", value: c.notes },
      ]}
      onSave={async (v) => {
        v.base_price = v.base_price === "" ? null : parseFloat(v.base_price);
        await papi("PATCH", `/api/decisions/${did}/candidates/${c.id}`, v);
        await refresh();
      }} />;
  }

  if (t === "dimension") {
    return <PromptModal title="Add spec" saveLabel="Add spec" onClose={onClose}
      fields={[
        { name: "name", label: "Spec name", placeholder: "Drive type (SSD vs HDD)" },
        { name: "explainer", label: "What it is", type: "textarea", placeholder: "plain-language: what this spec is" },
        { name: "deciding", label: "You're deciding", type: "textarea", placeholder: "what decision this spec asks of you" },
        { name: "fit_zone", label: "For you (which option)", placeholder: "the option that fits you" },
        { name: "fit_reasoning", label: "For you (why)", type: "textarea" },
      ]}
      onSave={async (v) => {
        if (!v.name.trim()) throw new Error("Spec name required");
        await papi("POST", `/api/decisions/${did}/dimensions`, {
          name: v.name.trim(), explainer: v.explainer.trim(), deciding: v.deciding.trim(),
          fit_zone: v.fit_zone.trim(), fit_reasoning: v.fit_reasoning.trim(),
          sort: (decision.dimensions?.length || 0) + 1, options: "[]",
        });
        await refresh();
      }} />;
  }

  if (t === "criterion") {
    return <PromptModal title="Add criterion" onClose={onClose}
      fields={[
        { name: "name", label: "Name", placeholder: "battery life" },
        { name: "priority", label: "Priority", type: "select", options: PRIORITIES, value: "nice-to-have" },
        { name: "weight", label: "Weight (1-5)", type: "number", value: 3 },
        { name: "notes", label: "Notes", type: "textarea" },
      ]}
      onSave={async (v) => { v.weight = parseInt(v.weight, 10) || 3;
        await papi("POST", `/api/decisions/${did}/criteria`, v); await refresh(); }} />;
  }

  if (t === "proscon") {
    return <PromptModal title="Add pro / con / failure mode" onClose={onClose}
      fields={[
        { name: "kind", label: "Kind", type: "select", options: ["pro","con","failure_mode","regret"], value: "pro" },
        { name: "text", label: "Text", type: "textarea" },
      ]}
      onSave={async (v) => { if (!v.text.trim()) return;
        await papi("POST", `/api/candidates/${modal.cid}/pros-cons`, v); await refresh(); }} />;
  }

  if (t === "price") {
    return <PromptModal title="Add price point" onClose={onClose}
      fields={[
        { name: "vendor", label: "Vendor", placeholder: "Amazon / Best Buy / direct" },
        { name: "price", label: "Price", type: "number" },
        { name: "currency", label: "Currency", value: "USD" },
        { name: "url", label: "URL" },
        { name: "channel_notes", label: "Channel notes", type: "textarea", placeholder: "5% CC cashback, $30 Rakuten" },
        { name: "notes", label: "Notes", type: "textarea" },
      ]}
      onSave={async (v) => { if (!v.price) throw new Error("Price required");
        v.price = parseFloat(v.price);
        await papi("POST", `/api/candidates/${modal.cid}/prices`, v); await refresh(); }} />;
  }

  if (t === "spec") {
    const cands = decision.candidates;
    // Add-spec button is disabled with zero candidates (CompareTab), so this is
    // just a defensive no-op, never a user-visible dead end.
    if (!cands.length) { onClose(); return null; }
    return <PromptModal title="Add spec value" onClose={onClose}
      fields={[
        { name: "candidate", label: "Candidate", type: "select", options: cands.map(c => c.name), value: cands[0].name },
        { name: "key", label: "Spec key", placeholder: "weight, battery, warranty" },
        { name: "value", label: "Value", placeholder: "250g / 30hr / 2yr" },
      ]}
      onSave={async (v) => { const cand = cands.find(c => c.name === v.candidate); if (!cand) return;
        await papi("POST", `/api/candidates/${cand.id}/specs`, { key: v.key, value: v.value }); await refresh(); }} />;
  }

  if (t === "constraint") {
    return <PromptModal title="Add constraint" onClose={onClose}
      fields={[
        { name: "name", label: "Name", placeholder: "drive type" },
        { name: "requirement", label: "Requirement", placeholder: "SSD, not HDD" },
        { name: "origin", label: "Origin", placeholder: "landscape: reliability evidence" },
        { name: "status", label: "Status", type: "select", options: ["proposed", "locked"], value: "proposed" },
      ]}
      onSave={async (v) => { if (!v.name.trim()) throw new Error("Name required");
        await papi("POST", `/api/decisions/${did}/constraints`, v); await refresh(); }} />;
  }

  // Themed replacement for window.confirm() — every destructive action routes
  // here with its own title/body/onConfirm instead of a native dialog.
  if (t === "confirm") {
    return <ConfirmModal title={modal.title} body={modal.body} danger={modal.danger !== false}
      confirmLabel={modal.confirmLabel || "Delete"} onClose={onClose}
      onConfirm={async () => { await modal.onConfirm(); onClose(); }} />;
  }

  // Themed replacement for window.prompt() — both "pick a winner" entry points
  // (candidate deep-dive ★ pick, verdict-tab pick) route here.
  if (t === "verdict-reason") {
    return <PromptModal title="Pick this as the winner" saveLabel="Confirm pick" onClose={onClose}
      fields={[{ name: "reason", label: "Why does this win? (one line)", value: modal.currentReason || "" }]}
      onSave={async (v) => {
        await papi("PATCH", `/api/decisions/${did}`, {
          verdict_candidate_id: modal.candidateId, verdict_reason: v.reason.trim(), stage: "decided",
        });
        // A pick is a purchase in waiting. Opening its order row here is what
        // keeps the orders tab complete without a second thing to remember.
        if (!decision.order) {
          const c = decision.candidates.find(x => x.id === modal.candidateId);
          await papi("POST", "/api/orders", {
            decision_id: did, item: c ? c.name : decision.name,
            vendor: (c?.vendor) || "", url: (c?.url) || "",
            image_url: (c?.image_url) || "",
            return_policy: (c?.return_policy) || "",
            source: "decision", ship_status: "ordered",
          });
          bumpOrders?.();
        }
        await refresh();
      }} />;
  }
  return null;
}

ReactDOM.createRoot(document.getElementById("root")).render(<PurchasesApp />);
