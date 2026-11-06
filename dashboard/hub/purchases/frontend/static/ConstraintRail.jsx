/* ConstraintRail.jsx — the spec contract: hard constraints, locked above
   proposed, with aggregate fail counts. Nothing here ever filters candidates;
   it is the contract the candidates are measured against.

   Rebuilt 2026-08-28 from a pane into a panel. It used to be a permanent
   340px third column of the shell, which meant the compare tab's scoring
   grid lost 340px it needed and the need tab gained 340px it had no use for.
   The arena decides where and whether it renders now (see DecisionArena's
   .pe-split), so this component owns only the panel. */

function SpecContract({ decision, refresh, setModal }) {
  const d = decision;
  const total = d.candidates.length;
  const failCount = (conId) =>
    (d.candidate_constraints || []).filter(cc => cc.constraint_id === conId && cc.status === "fail").length;
  const toggle = async (con) => {
    await papi("PATCH", `/api/decisions/${d.id}/constraints/${con.id}`,
      { status: con.status === "locked" ? "proposed" : "locked" });
    await refresh();
  };
  const del = (con) => {
    setModal({
      type: "confirm", title: `Remove constraint "${con.name}"?`,
      onConfirm: async () => { await papi("DELETE", `/api/decisions/${d.id}/constraints/${con.id}`); await refresh(); },
    });
  };
  const groups = [
    ["locked", d.constraints.filter(c => c.status === "locked")],
    ["proposed", d.constraints.filter(c => c.status !== "locked")],
  ].filter(([, items]) => items.length);

  return (
    <div className="panel">
      <div className="panel-head">
        <h2 className="panel-title">spec contract</h2>
        <button type="button" className="section-add" onClick={() => setModal({ type: "constraint" })}>+ add</button>
      </div>
      <div className="panel-body panel-pad">
        {!d.constraints.length
          ? <div className="research-null">
              <div className="research-null-what">no constraints yet</div>
              <div className="research-null-how">research proposes them; you lock the ones that are non-negotiable.</div>
            </div>
          : groups.map(([label, items]) => (
            <div key={label} className="con-group">
              <div className="con-group-head">{label} · {items.length}</div>
              {items.map(con => (
                <div key={con.id} className={`con-row${con.status === "locked" ? " locked" : ""}`}>
                  <button type="button" className={`con-lock${con.status === "locked" ? " on" : ""}`}
                    title={con.status === "locked" ? "locked — click to unlock" : "proposed — click to lock"}
                    aria-label={con.status === "locked" ? "unlock constraint" : "lock constraint"}
                    onClick={() => toggle(con)}>{con.status === "locked" ? "●" : "○"}</button>
                  <div className="con-body">
                    <span className="con-name">{con.name}</span>
                    <span className="con-req">{con.requirement}</span>
                    {con.origin ? <span className="con-origin">{con.origin}</span> : null}
                    {total > 0 && <span className={`con-fails${failCount(con.id) ? " some" : ""}`}>
                      {failCount(con.id)}/{total} fail</span>}
                  </div>
                  <button type="button" className="icon-btn danger" title="delete constraint" aria-label="delete constraint" onClick={() => del(con)}>×</button>
                </div>
              ))}
            </div>
          ))}
      </div>
    </div>
  );
}
Object.assign(window, { SpecContract });
