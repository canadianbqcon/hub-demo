/* pipeline.jsx — the three new research tabs (landscape / priorities / market)
   plus shared evidence rendering. Classic-runtime globals like the rest. */

const { useState: plUseState } = React;

/* EvidenceList — graded claims, one line each: grade badge, claim, source. */
function EvidenceList({ items }) {
  if (!items.length) return <div className="empty-hint">No graded evidence.</div>;
  return (
    <div className="evidence-list">
      {items.map(ev => (
        <div key={ev.id} className="evidence-row">
          <span className={`evidence-grade eg-${ev.grade || "ungraded"}`}>{ev.grade || "?"}</span>
          <span className="evidence-claim">{ev.claim}</span>
          <span className="evidence-src">
            {ev.longevity || ""}{ev.source_type ? ` · ${ev.source_type}` : ""}
            {ev.source_url ? <> · <a href={ev.source_url} target="_blank" rel="noopener">src ↗</a></> : null}
          </span>
          {ev.grade_reason ? <div className="evidence-why">{ev.grade_reason}</div> : null}
        </div>
      ))}
    </div>
  );
}

/* DimensionRow — the function map row: teaches the spec (what it is, the
   options and their tradeoffs, what you're deciding, the call for you). Every
   field is click-to-edit; options add/edit/delete; the spec itself deletes.
   Evidence collapsed behind the caret. */
function DimensionRow({ d, dim, refresh, setModal }) {
  const [open, setOpen] = plUseState(false);
  const evidence = (d.evidence || []).filter(e => e.subject_type === "dimension" && e.subject === dim.name);
  let options = [];
  try { const p = JSON.parse(dim.options || "[]"); if (Array.isArray(p)) options = p; } catch {}
  const patch = (field, val) =>
    papi("PATCH", `/api/decisions/${d.id}/dimensions/${dim.id}`, { [field]: val }).then(refresh);
  const patchOptions = (arr) => patch("options", JSON.stringify(arr));
  const setOpt = (i, key, val) => patchOptions(options.map((o, j) => j === i ? { ...o, [key]: (val ?? "") } : o));
  const addOpt = () => patchOptions([...options, { label: "new option", note: "" }]);
  const delOpt = (i) => patchOptions(options.filter((_, j) => j !== i));
  const del = () => {
    setModal({
      type: "confirm", title: `Remove spec "${dim.name}"?`, body: "This deletes the spec and its evidence.",
      onConfirm: async () => { await papi("DELETE", `/api/decisions/${d.id}/dimensions/${dim.id}`); await refresh(); },
    });
  };
  return (
    <div className="dim-row">
      <div className="dim-head">
        <span className="dim-name"><Editable value={dim.name} onSave={nv => nv && patch("name", nv)} /></span>
        <span className="dim-range" />
        <button type="button" className="dim-caret-btn" aria-expanded={open}
          aria-label={open ? "collapse evidence" : "expand evidence"}
          onClick={() => setOpen(o => !o)}>{open ? "▾" : "▸"}{evidence.length ? ` ${evidence.length}` : ""}</button>
        <button type="button" className="icon-btn danger" title="delete spec" aria-label="delete spec" onClick={del}>×</button>
      </div>
      <div className="dim-block">
        <div className="dim-label">what it is</div>
        <div className="dim-explainer"><Editable value={dim.explainer} multiline onSave={nv => patch("explainer", nv)} placeholder="what is this spec?" /></div>
      </div>
      <div className="dim-block">
        <div className="dim-label">your options</div>
        <div className="dim-opts">
          {options.map((o, i) => (
            <div className="dim-opt" key={i}>
              <span className="dim-opt-label"><Editable value={o.label} onSave={v => setOpt(i, "label", v)} placeholder="option" /></span>
              <span className="dim-opt-note"><Editable value={o.note} multiline onSave={v => setOpt(i, "note", v)} placeholder="what it is / the tradeoff" /></span>
              <button type="button" className="icon-btn danger dim-opt-del" title="remove option" aria-label="remove option" onClick={() => delOpt(i)}>×</button>
            </div>
          ))}
          <button type="button" className="dim-add-opt" onClick={addOpt}>+ option</button>
        </div>
      </div>
      <div className="dim-block">
        <div className="dim-label">you're deciding</div>
        <div className="dim-explainer"><Editable value={dim.deciding} multiline onSave={nv => patch("deciding", nv)} placeholder="what decision does this spec ask of you?" /></div>
      </div>
      <div className="dim-block">
        <div className="dim-label">for you</div>
        <div className="dim-foryou"><span className="dim-foryou-v"><Editable value={dim.fit_zone} onSave={nv => patch("fit_zone", nv)} placeholder="which option fits you" /></span></div>
        <div className="dim-why"><Editable value={dim.fit_reasoning} multiline onSave={nv => patch("fit_reasoning", nv)} placeholder="why" /></div>
      </div>
      <HubCollapse open={open}><EvidenceList items={evidence} /></HubCollapse>
    </div>
  );
}

function BrandRow({ d, brand }) {
  const [open, setOpen] = plUseState(false);
  const evidence = (d.evidence || []).filter(e => e.subject_type === "brand" && e.subject === brand.name);
  return (
    <div className="dim-row">
      <div className="dim-head" role="button" tabIndex={0} aria-expanded={open}
        onClick={() => setOpen(o => !o)}
        onKeyDown={e => { if (e.key === "Enter") setOpen(o => !o); else if (e.key === " ") { e.preventDefault(); setOpen(o => !o); } }}>
        <span className="dim-name">{brand.name}</span>
        <span className="dim-range">{brand.summary || "—"}</span>
        <span className="dim-caret">{open ? "▾" : "▸"}{evidence.length ? ` ${evidence.length}` : ""}</span>
      </div>
      <HubCollapse open={open}><EvidenceList items={evidence} /></HubCollapse>
    </div>
  );
}

function LandscapeTab({ d, refresh, setModal }) {
  return (
    <div className="pe-tab">
      <div className="pe-section-head">
        <h2 className="section-title">function map ({d.dimensions.length})</h2>
        <button type="button" className="section-add" onClick={() => setModal({ type: "dimension" })}>+ add spec</button>
      </div>
      {d.dimensions.length === 0
        ? <div className="empty-hint">No specs yet. Add one, or run landscape research.</div>
        : d.dimensions.map(dim => <DimensionRow key={dim.id} d={d} dim={dim} refresh={refresh} setModal={setModal} />)}
      <div className="pe-section-head is-second">
        <h2 className="section-title">brand map ({d.brands.length})</h2>
      </div>
      {d.brands.length === 0 ? <div className="empty-hint">No brands mapped.</div>
        : d.brands.map(b => <BrandRow key={b.id} d={d} brand={b} />)}
    </div>
  );
}

Object.assign(window, { LandscapeTab, EvidenceList });

/* PrioritiesTab — proposed weights, inline-editable; the confirm button is THE
   checkpoint and stays disabled (with the reason) until awaiting-you. */
function PrioritiesTab({ d, refresh, setModal }) {
  const status = d.section_state?.priorities || "pending";
  const dimName = (id) => d.dimensions.find(x => x.id === id)?.name || null;
  const confirm = async () => {
    await papi("POST", `/api/decisions/${d.id}/confirm-priorities`);
    await refresh();
  };
  if (!d.criteria.length) return <div className="pe-tab"><ResearchNull what="proposed priorities" /></div>;
  return (
    <div className="pe-tab">
      <div className="pe-section-head">
        <h2 className="section-title">priorities ({d.criteria.length})</h2>
        <button type="button" className="section-add" onClick={() => setModal({ type: "criterion" })}>+ add criterion</button>
      </div>
      <table className="specs">
        <thead><tr><th>criterion</th><th>dimension</th><th>priority</th><th>weight</th><th>notes</th></tr></thead>
        <tbody>{d.criteria.map(c => (
          <tr key={c.id}>
            <td>{c.name}</td>
            <td className="dim">{dimName(c.dimension_id) || "need-derived"}</td>
            <td><EditableSelect value={c.priority} options={PRIORITIES}
              onSave={async nv => { await papi("PATCH", `/api/decisions/${d.id}/criteria/${c.id}`, { priority: nv }); await refresh(); }} /></td>
            <td className="numeric"><Editable value={c.weight} number
              onSave={async nv => { await papi("PATCH", `/api/decisions/${d.id}/criteria/${c.id}`, { weight: nv }); await refresh(); }} /></td>
            <td className="dim">{c.notes || ""}</td>
          </tr>
        ))}</tbody>
      </table>
      {status === "done"
        ? <div className="checkpoint-done">✓ priorities confirmed — later stages built on these weights</div>
        : <button type="button" className="btn btn-primary checkpoint-btn" disabled={status !== "awaiting-you"}
            title={status !== "awaiting-you" ? `research is ${status} — confirm unlocks when it's your turn` : ""}
            onClick={confirm}>
            {status === "awaiting-you" ? "confirm priorities — unlock market research"
              : `confirm priorities (research ${status})`}
          </button>}
    </div>
  );
}

Object.assign(window, { PrioritiesTab });

/* MarketTab — price rungs grouped by dimension. Every rung shown at equal
   weight; the knee is a marker + note, never a de-emphasis. */
function MarketTab({ d }) {
  if (!d.price_steps.length) return <div className="pe-tab"><ResearchNull what="market price research" /></div>;
  const byDim = {};
  d.price_steps.forEach(ps => {
    const k = ps.dimension_id || 0;
    (byDim[k] = byDim[k] || []).push(ps);
  });
  const dimName = (id) => d.dimensions.find(x => x.id === Number(id))?.name || "general";
  return (
    <div className="pe-tab">
      {Object.entries(byDim).map(([dimId, steps]) => (
        <div key={dimId}>
          <div className="pe-section-head">
            <h2 className="section-title">price steps — {dimName(dimId)}</h2>
          </div>
          <table className="specs price-steps">
            <thead><tr><th>rung</th><th>spec</th><th>price</th><th>per unit</th><th></th></tr></thead>
            <tbody>{steps.map(ps => (
              <tr key={ps.id}>
                <td>{ps.label}</td>
                <td>{ps.spec_value || "—"}</td>
                <td className="numeric">{fmtMoney(ps.price)}</td>
                <td className="dim">{ps.per_unit_note || "—"}</td>
                <td>{ps.knee ? <span className="knee-flag" title={ps.note || "diminishing returns past here"}>⌁ knee</span>
                  : (ps.note || null)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

Object.assign(window, { MarketTab });

/* failsFor — the locked/proposed constraints a candidate FAILS, for flag chips. */
function failsFor(d, candidateId) {
  const byId = {};
  (d.constraints || []).forEach(c => { byId[c.id] = c; });
  return (d.candidate_constraints || [])
    .filter(cc => cc.candidate_id === candidateId && cc.status === "fail" && byId[cc.constraint_id])
    .map(cc => ({ name: byId[cc.constraint_id].name, req: byId[cc.constraint_id].requirement, note: cc.note }));
}
Object.assign(window, { failsFor });

/* ── moved from ContextPane.jsx: candidate deep-dive + its review card ──────── */

function ReviewCard({ r, onDelete, candName }) {
  return (
    <div className="card">
      <div className="card-header">
        <div>
          <div className="card-title">{r.title || "(untitled)"}</div>
          <div className="card-meta">{r.source_type}{r.author ? ` · ${r.author}` : ""}{candName ? ` · ${candName}` : ""}
            {!r.is_current_version ? " · ⚠ pre-update version" : ""}</div>
        </div>
        <span className={`sentiment sentiment-${r.sentiment}`}>{r.sentiment}</span>
      </div>
      {r.takeaway ? <div className="card-meta card-takeaway">{r.takeaway}</div> : null}
      {r.notes ? <div className="card-caveat">{r.notes}</div> : null}
      {r.url ? <div className="card-meta"><a href={r.url} target="_blank" rel="noopener">open ↗</a></div> : null}
      <div className="card-actions"><button type="button" className="icon-btn danger" title="delete review" aria-label="delete review" onClick={onDelete}>×</button></div>
    </div>
  );
}

function Panel({ n, title, meta, action, children }) {
  return (
    <div className="panel">
      <div className="panel-head">
        <h2 className="panel-title">{n ? `${n} — ` : ""}{title}</h2>
        {action || (meta ? <div className="panel-meta">{meta}</div> : null)}
      </div>
      <div className="panel-body">{children}</div>
    </div>
  );
}

function CandidateDeepDive({ d, c, refresh, setModal }) {
  const pc = (d.pros_cons || []).filter(p => p.candidate_id === c.id);
  const prices = (d.price_points || []).filter(p => p.candidate_id === c.id);
  const specs = d.specs.filter(s => s.candidate_id === c.id);
  const reviews = d.reviews.filter(r => r.candidate_id === c.id);
  const scores = (d.candidate_scores || []).filter(s => s.candidate_id === c.id);
  const critName = (crid) => d.criteria.find(x => x.id === crid)?.name || "—";

  const setVerdict = () => setModal({ type: "verdict-reason", candidateId: c.id, currentReason: d.verdict_reason });
  const delCand = () => {
    setModal({
      type: "confirm", title: "Delete this candidate?",
      body: "This removes the candidate along with its scores, prices, specs, and reviews.",
      onConfirm: async () => { await papi("DELETE", `/api/decisions/${d.id}/candidates/${c.id}`); await refresh(); },
    });
  };
  const delReview = async (rid) => { await papi("DELETE", `/api/decisions/${d.id}/reviews/${rid}`); await refresh(); };

  return (
    <div>
      <Panel title={c.name}
        meta={c.match_score != null ? `${c.match_score} · ${c.score_coverage}` : "unscored"}>
        <div className="panel-pad">
          {/* status moved here from the candidate row: the row is a ranked
              comparison line and a native <select> in every one of them
              out-shouted the prices you are there to read. One editor, on
              the candidate you actually have open. */}
          <div className="card-meta">
            {c.vendor || "—"} · {fmtMoney(c.base_price, c.currency)} ·{" "}
            <StatusSelect value={c.status} options={CANDIDATE_STATUSES}
              onChange={async (v) => {
                await papi("PATCH", `/api/decisions/${d.id}/candidates/${c.id}`, { status: v });
                await refresh();
              }} />
          </div>
          {c.url ? <div className="card-meta"><a href={c.url} target="_blank" rel="noopener">open link ↗</a></div> : null}
          <div className="card-actions">
            <button type="button" className="icon-btn" onClick={() => setModal({ type: "proscon", cid: c.id })}>+ pro/con</button>
            <button type="button" className="icon-btn" onClick={() => setModal({ type: "price", cid: c.id })}>+ price</button>
            <button type="button" className="icon-btn" onClick={() => setModal({ type: "edit-candidate", candidate: c })}>edit</button>
            <button type="button" className="icon-btn" aria-label="pick as winner" onClick={setVerdict}>★ pick</button>
            <button type="button" className="icon-btn danger" onClick={delCand}>delete</button>
          </div>
        </div>
      </Panel>

      {scores.length > 0 && (
        <Panel title="scores" meta={c.score_coverage}>
          <div className="panel-pad"><table className="specs"><tbody>{scores.map(s => (
            <tr key={s.id}><td>{critName(s.criterion_id)}</td><td className="numeric">{s.score}</td></tr>
          ))}</tbody></table></div>
        </Panel>
      )}

      <Panel title="pros / cons" meta={String(pc.length)}>
        <div className="panel-pad">
          {pc.length === 0 ? <div className="empty-hint">None yet.</div>
            : <div className="procon-col">{pc.map(p => <ProConPill key={p.id} p={p} />)}</div>}
        </div>
      </Panel>

      <Panel title="price points" meta={String(prices.length)}>
        <div className="panel-pad">
          {prices.length === 0 ? <div className="empty-hint">None yet.</div>
            : <table className="specs">
                <thead><tr><th>vendor</th><th>price</th><th>notes</th></tr></thead>
                <tbody>{prices.map(p => (
                  <tr key={p.id}><td>{p.vendor || "—"}</td><td className="numeric">{fmtMoney(p.price, p.currency)}</td>
                    <td>{p.channel_notes || p.notes || "—"}</td></tr>
                ))}</tbody>
              </table>}
        </div>
      </Panel>

      {specs.length > 0 && (
        <Panel title="specs">
          <div className="panel-pad"><table className="specs"><tbody>{specs.map(s => (
            <tr key={s.id}><td>{s.key}</td><td className="numeric">{s.value || "—"}</td></tr>
          ))}</tbody></table></div>
        </Panel>
      )}

      {reviews.length > 0 && (
        <Panel title="reviews" meta={String(reviews.length)}>
          <div className="panel-pad">{reviews.map(r => <ReviewCard key={r.id} r={r} onDelete={() => delReview(r.id)} />)}</div>
        </Panel>
      )}
    </div>
  );
}
Object.assign(window, { CandidateDeepDive });
