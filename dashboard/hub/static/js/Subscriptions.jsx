/* subscriptions panel — center bottom. price-change flagger. */

const { useState } = React;

const FLAG_LABELS = {
  review: "review",
};

const FLAG_DESCRIPTIONS = {
  review: "this subscription was flagged for review.",
};

function SubModal({ sub, onDismiss, onClose }) {
  const dref = useDialogA11y(onClose);

  const hasFlagActive = !!sub.flag;

  return (
    <div className="hub-modal-scrim sub-scrim" onClick={onClose}>
      <div className="sub-modal" ref={dref} tabIndex={-1} role="dialog" aria-modal="true" aria-label={`subscription: ${sub.name}`} onClick={(e) => e.stopPropagation()}>
        <div className="sub-modal-head">
          <span className="sub-modal-name">{sub.name}</span>
          <span className="sub-modal-amt">{sub.amt} / {sub.cycle}</span>
        </div>
        {hasFlagActive && (
          <>
            <div className="sub-modal-flag-row">
              <span className="sub-flag">▲ {FLAG_LABELS[sub.flag] || sub.flag}</span>
            </div>
            <p className="sub-modal-reason">
              {sub.flag_reason || FLAG_DESCRIPTIONS[sub.flag] || "flagged for review."}
            </p>
          </>
        )}
        <div className="sub-modal-actions">
          {hasFlagActive && (
            <button type="button" className="sub-modal-dismiss" onClick={() => { onDismiss(sub.name); onClose(); }}>
              dismiss flag
            </button>
          )}
          <button type="button" className="sub-modal-close" onClick={onClose}>
            close
          </button>
        </div>
      </div>
    </div>
  );
}

function Subscriptions({ subs }) {
  const STORAGE_KEY = "vesper.dismissed_flags";

  const [dismissed, setDismissed] = useState(() => {
    try { return new Set(JSON.parse(localStorage.getItem(STORAGE_KEY)) || []); }
    catch { return new Set(); }
  });

  const [selected, setSelected] = useState(null);

  const dismiss = (name) => {
    setDismissed((prev) => {
      const next = new Set(prev);
      next.add(name);
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify([...next])); } catch {}
      return next;
    });
  };

  const activeSubs = subs.map((s) => ({
    ...s,
    flag: dismissed.has(s.name) ? null : s.flag,
    flag_reason: dismissed.has(s.name) ? null : s.flag_reason,
  }));


  // Monthly total across every shown sub. amt is a display string ("$100.00"),
  // so strip $ and commas before summing. Exact cents — never round (see
  // feedback_money_show_cents). Derived from the same list the rows render, so it
  // always matches what's on screen.
  const total = subs.reduce((sum, s) => {
    const v = parseFloat(String(s.amt).replace(/[$,]/g, ""));
    return sum + (Number.isFinite(v) ? v : 0);
  }, 0);

  return (
    <>
      <div className="panel fixed">
        <div className="panel-head">
          {/* h3 — nested under the "recap" column head, not a peer section */}
          <h3 className="panel-title">subscriptions</h3>
        </div>
        <div className="panel-body">
          <div className="sub-list">
            {activeSubs.map((s, i) => (
              <button
                type="button"
                className="sub-row sub-row-clickable"
                key={i}
                onClick={() => setSelected(s)}
              >
                <span className="sub-name">
                  {s.name}
                  {s.flag && <span className="sub-flag">{FLAG_LABELS[s.flag] || s.flag}</span>}
                </span>
                <span className="sub-cycle">{s.days != null ? window.daysLabel(s.days) : (s.next_billing || s.cycle)}</span>
                <span className="sub-amt">{s.amt}</span>
              </button>
            ))}
          </div>
          {subs.length > 0 && (
            <div className="sub-total-row">
              <span className="sub-total-label">total</span>
              <span className="sub-total-amt">${total.toFixed(2)} / mo</span>
            </div>
          )}
        </div>
      </div>

      {selected && (
        <SubModal
          sub={selected}
          onDismiss={dismiss}
          onClose={() => setSelected(null)}
        />
      )}
    </>
  );
}

Object.assign(window, { Subscriptions });
