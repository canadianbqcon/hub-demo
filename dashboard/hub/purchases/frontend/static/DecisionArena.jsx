/* DecisionArena.jsx — middle pane, jobs-focus parity. A ruled focus-head (title +
   delete + stage picker) carries a surface-tab strip for the seven-stage pipeline:
   need / landscape / priorities / market / candidates / compare / verdict (see
   ARENA_TABS below). Each tab is a flat hairline-ruled surface, no box-in-box.
   The compare tab is the match scoring grid (candidates × criteria → weighted
   score + rank), powered by candidate_scores. Inline edits call
   onPatchDecision(field, nv) — one hydrated field — per the GET invariant. */

const { useState: aUseState } = React;

const ARENA_TABS = [
  { key: "need",       label: "need",       stub: "the problem" },
  { key: "landscape",  label: "landscape",  stub: "what exists" },
  { key: "priorities", label: "priorities", stub: "what matters" },
  { key: "market",     label: "market",     stub: "price curves" },
  { key: "candidates", label: "candidates", stub: "options" },
  { key: "compare",    label: "compare",    stub: "score · top 5" },
  { key: "verdict",    label: "verdict",    stub: "pick · outcome" },
];

/* Which tabs get a side pane, and what goes in it. Only compare goes without:
   it is an n-candidate scoring grid and the whole pane is the content. On need
   the contract earns its place twice over — that tab's "hard constraints" is
   the prose version of the same thing, and reading the two side by side is how
   you notice the contract has drifted from what you actually wrote down. */
const NO_SIDE = ["compare"];

/* The price a candidate actually carries: newest price point, else its base.
   Used by the header's range and by the candidate rows, so the two agree. */
function candPrice(d, c) {
  const pp = (d.price_points || []).filter(p => p.candidate_id === c.id);
  return {
    price: pp.length ? pp[0].price : c.base_price,
    ccy: pp.length ? pp[0].currency : c.currency,
    vendor: (pp.length && pp[0].vendor) || c.vendor,
    count: pp.length,
  };
}

/* The header's facts row. The head used to carry the decision's name and
   nothing else, so the one surface always on screen said the least about
   where the decision stood. Only facts that exist are rendered — a decision
   with no candidates does not get a "0 candidates" cell it can do nothing
   about, it gets a shorter row. */
function decisionFacts(d) {
  const out = [];
  const cands = d.candidates || [];
  if (cands.length) out.push({ n: cands.length, l: "candidates" });
  if ((d.constraints || []).length) {
    const locked = d.constraints.filter(c => c.status === "locked").length;
    out.push({ n: locked || d.constraints.length, l: locked ? "locked specs" : "proposed specs" });
  }
  const prices = cands.map(c => candPrice(d, c).price).filter(p => p != null && p > 0);
  if (prices.length) {
    const lo = Math.min(...prices), hi = Math.max(...prices);
    out.push({
      n: lo === hi ? fmtMoney(lo, d.currency) : `${fmtMoney(lo, d.currency)}–${fmtMoney(hi, d.currency)}`,
      l: prices.length > 1 ? "price range" : "price",
    });
  }
  const lead = (d.candidates_ranked || []).map(id => cands.find(c => c.id === id)).find(Boolean);
  if (lead && lead.match_score != null) {
    // the name would truncate mid-word at this size, and the #1 row directly
    // below already says which candidate it is
    out.push({ n: lead.match_score, l: "best match /100", lead: true });
  }
  return out;
}

/* ResearchNull — teaching empty state for research tabs; also the pre-redesign
   decision banner (no landscape data exists for decisions made before 006). */
// biome-ignore lint/correctness/noUnusedVariables: classic script global — read by a sibling file loaded after this one (see file header); biome lints each file in isolation and can't see the cross-file read.
function ResearchNull({ what }) {
  return (
    <div className="research-null">
      <div className="research-null-what">no {what} yet</div>
      <div className="research-null-how">run <code>/purchase</code> in Claude to research this stage — results land here.</div>
    </div>
  );
}

function DecisionArena({ decision, loading, selectedCandidateId, onPatchDecision, onSelectCandidate, refresh, setModal }) {
  const [tab, setTab] = aUseState(null);
  // A decision is on its way: three pulsing lines, not the previous decision
  // wearing the wrong name. Tab state survives, since this is the same
  // component instance returning a different tree.
  if (loading) {
    return <main className="pe-arena"><div className="pe-skel" role="status" aria-busy="true" aria-label="loading decision">
      <div className="pe-skel-line is-title" /><div className="pe-skel-line" /><div className="pe-skel-line" />
    </div></main>;
  }
  if (!decision) {
    return <main className="pe-arena"><div className="empty-state-main"><div>
      <div className="empty-state-glyph" aria-hidden="true">◆</div>
      <div>Select a decision, or create one.</div>
    </div></div></main>;
  }
  const d = decision;
  const sectionState = d.section_state || {};
  const activeTab = tab || (PIPELINE_STAGES.includes(d.stage) ? d.stage
    : d.stage === "decided" ? "verdict" : "candidates");
  const deleteDecision = () => {
    setModal({
      type: "confirm", title: "Delete this decision?",
      body: "This removes the decision and everything under it — candidates, scores, evidence, constraints. This cannot be undone.",
      confirmLabel: "Delete decision",
      onConfirm: async () => {
        await papi("DELETE", `/api/decisions/${d.id}`);
        if (d.project_id) await papi("DELETE", `/api/projects/${d.project_id}`).catch(() => {});
        await refresh();
      },
    });
  };

  const facts = decisionFacts(d);
  // On candidates the side pane is the open candidate — it used to stack
  // BELOW the card grid, which is why that tab ran a screen and a half tall
  // and ended in dead space no matter how few candidates there were.
  const openCand = activeTab === "candidates" && selectedCandidateId
    ? d.candidates.find(x => x.id === selectedCandidateId) : null;
  const showSide = !NO_SIDE.includes(activeTab);

  return (
    <main className="pe-arena">
      <div className="pe-focus-head">
        <div className="pe-focus-top">
          <h2 className="pe-focus-title">
            <Editable value={d.name} onSave={(nv) => onPatchDecision("name", nv)} />
          </h2>
          {/* single pipeline navigator: the tabs below switch the view; stage-setting
              is demoted to this compact dropdown override (was a second full row of
              the same 7 words — the P1 "two stacked navigators" finding). */}
          {/* biome-ignore lint/a11y/noLabelWithoutControl: StatusSelect renders a native <select> as its root element, so wrapping it gives an implicit label association — biome can't see through the component boundary. */}
          <label className="pe-stage-control">
            <span className="pe-stage-label">stage</span>
            <StatusSelect value={d.stage} options={STAGES} onChange={(nv) => onPatchDecision("stage", nv)} />
          </label>
          <button type="button" className="focus-action alert" onClick={deleteDecision}>delete</button>
        </div>

        {facts.length > 0 && (
          <div className="pe-facts">
            {facts.map(f => (
              <span key={f.l} className={`pfact${f.lead ? " is-lead" : ""}${f.n === 0 ? " is-zero" : ""}`}>
                <span className="pfact-n">{f.n}</span>
                <span className="pfact-l">{f.l}</span>
              </span>
            ))}
          </div>
        )}

        {/* Seven tabs each carrying a two-line label plus an italic gloss was
            fourteen lines of type above the content. The gloss belongs to the
            tab you are on; the rest are one word each. */}
        <div className="hub-tabs surface-tabs">
          {ARENA_TABS.map(t => (
            <button type="button" key={t.key} className={`hub-tab surface-tab${activeTab === t.key ? " active" : ""}`}
              title={t.stub} onClick={() => setTab(t.key)}>
              <SectionGlyph status={sectionState[t.key]} />
              {t.label}
              {activeTab === t.key ? <span className="stub">{t.stub}</span> : null}
            </button>
          ))}
        </div>
      </div>

      <div className="pe-split" data-split={activeTab}>
        <div className="pe-focus-body">
          {activeTab === "need" && <DefineTab d={d} onPatchDecision={onPatchDecision} />}
          {activeTab === "landscape" && <LandscapeTab d={d} refresh={refresh} setModal={setModal} />}
          {activeTab === "priorities" && <PrioritiesTab d={d} refresh={refresh} setModal={setModal} />}
          {activeTab === "market" && <MarketTab d={d} refresh={refresh} setModal={setModal} />}
          {activeTab === "candidates" && <CandidatesSection d={d} selectedCandidateId={selectedCandidateId}
            onSelectCandidate={onSelectCandidate} refresh={refresh} setModal={setModal} />}
          {activeTab === "compare" && <CompareTab d={d} refresh={refresh} setModal={setModal} />}
          {activeTab === "verdict" && <VerdictTab d={d} onPatchDecision={onPatchDecision} refresh={refresh} setModal={setModal} />}
        </div>
        {showSide && (
          <aside className="pe-context">
            {openCand
              ? <CandidateDeepDive d={d} c={openCand} refresh={refresh} setModal={setModal} />
              : <SpecContract decision={d} refresh={refresh} setModal={setModal} />}
          </aside>
        )}
      </div>
    </main>
  );
}

/* ── define: the decision scope (intake) ─────────────────────────────────────── */

function DefineTab({ d, onPatchDecision }) {
  // Each cell carries its key. Unlabelled, the strip read as a row of five
  // bare values — and an unset budget rendered the word "budget", which looks
  // like a value rather than a blank.
  const meta = [
    { field: "category", k: "category", display: v => v || "—" },
    { field: "purchase_type", k: "type", select: ["one-time-product", "recurring-service", "saas", "service-contract"] },
    { field: "budget_max", k: "budget", number: true, display: v => v != null ? `≤ ${fmtMoney(v, d.currency)}` : "—" },
    { field: "time_horizon", k: "horizon", display: v => v || "—" },
    { field: "depth", k: "depth", select: ["triage", "standard", "deep-dive"] },
  ];
  const fields = [
    { label: "Use case", field: "use_context", multiline: true },
    { label: "Pain point", field: "pain_point", multiline: true, bullets: true },
    { label: "Hard constraints", field: "hard_constraints", multiline: true, bullets: true },
    { label: "Soft preferences", field: "soft_preferences", multiline: true, bullets: true },
    { label: "Notes", field: "notes", multiline: true },
  ];
  return (
    <div className="pe-tab">
      <div className="pe-meta-strip">
        {meta.map(m => (
          <span key={m.field} className="pe-meta-cell">
            <span className="reflect-k">{m.k}</span>
            {m.select
              ? <EditableSelect value={d[m.field]} options={m.select} onSave={nv => onPatchDecision(m.field, nv)} />
              : <Editable value={d[m.field]} number={m.number} displayFn={m.display}
                  onSave={nv => onPatchDecision(m.field, nv)} />}
          </span>
        ))}
      </div>
      <div className="pe-fieldset">
        {fields.map(f => (
          <div key={f.field} className="pe-field">
            <div className="pe-field-label">{f.label}</div>
            <div className="pe-field-value">
              <Editable value={d[f.field]} multiline={f.multiline}
                displayFn={f.bullets ? (v => bulletList(v)) : null}
                onSave={nv => onPatchDecision(f.field, nv)} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── candidates: the options, now carrying match score + rank ─────────────── */

/* A ranked list, not a card grid. Eight products in eight identically-framed
   boxes is the card grid the hub bans by name, and it could not do the one
   thing this list is for — reading two prices or two scores against each
   other. It was ragged too: a candidate with a second price point grew its
   box and knocked the whole row out of alignment. As rows, price and score
   are columns you run your eye down, rank is the sort, and the open
   candidate's detail goes in the side pane instead of below the fold. */
function CandidatesSection({ d, selectedCandidateId, onSelectCandidate, setModal }) {
  const ranked = d.candidates_ranked || [];
  const rankOf = (cid) => {
    const i = ranked.indexOf(cid);
    const c = d.candidates.find(x => x.id === cid);
    return (i >= 0 && c && c.match_score != null) ? i + 1 : null;
  };
  // scored candidates in rank order first, then the unscored in their own
  // order — an unranked row floating between #2 and #3 breaks the column.
  const rows = d.candidates.slice().sort((a, b) => {
    const ra = rankOf(a.id), rb = rankOf(b.id);
    if (ra && rb) return ra - rb;
    if (ra) return -1;
    if (rb) return 1;
    return 0;
  });
  return (
    <div className="pe-tab">
      <div className="pe-section-head">
        <h2 className="section-title">candidates</h2>
        <button type="button" className="section-add" onClick={() => setModal({ type: "new-candidate" })}>+ add candidate</button>
      </div>
      {d.candidates.length === 0
        ? <div className="empty-hint">No candidates yet. Add the products or services you're weighing.</div>
        : <div className="crow-list">{rows.map(c => {
          const { price, ccy, vendor, count } = candPrice(d, c);
          const rank = rankOf(c.id);
          const fails = failsFor(d, c.id);
          return (
            <button key={c.id} type="button"
              className={"crow"
                + (c.id === selectedCandidateId ? " selected" : "")
                + (rank === 1 ? " is-lead" : "")
                + (c.status === "chosen" || c.status === "purchased" ? " is-chosen" : "")
                + (c.status === "rejected" ? " is-rejected" : "")}
              aria-pressed={c.id === selectedCandidateId}
              onClick={() => onSelectCandidate(c.id === selectedCandidateId ? null : c.id)}>
              <span className="crow-rank">{rank ? `#${rank}` : "·"}</span>
              <span className="crow-meat">
                <span className="crow-name">{c.name}</span>
                <span className="crow-sub">
                  <span>{vendor || "—"}</span>
                  <span>·</span>
                  <span>{c.status}</span>
                  {count > 1 ? <><span>·</span><span>{count} prices</span></> : null}
                  {fails.map(f => (
                    <span key={f.name} className="fail-flag" title={f.note || f.req}>fails: {f.name}</span>
                  ))}
                </span>
              </span>
              <span className="crow-price">{fmtMoney(price, ccy)}</span>
              {c.match_score != null
                ? <span className="crow-score" title={`match score out of 100, price left out · ${c.score_coverage} criteria scored`}>{c.match_score}</span>
                : <span className="crow-score empty" title="not scored — rate it in compare">unscored</span>}
            </button>
          );
        })}</div>}
    </div>
  );
}

/* pros/cons as jobs-style dot + text (semantic green/red kept via the dot, fill
   dropped) instead of a filled pill. */
function ProConPill({ p, truncated }) {
  const sym = { pro: "+", con: "−", failure_mode: "!", regret: "~" }[p.kind] || "·";
  const text = truncated ? truncate(p.text, 40) : p.text;
  return <span className={`procon procon-${p.kind}`} title={p.text}>
    <span className="procon-dot">{sym}</span>{text}</span>;
}

/* ── compare: the match scoring grid + specs matrix ──────────────────────────── */

function CompareTab({ d, refresh, setModal }) {
  if (!d.candidates.length || !d.criteria.length) {
    return <div className="pe-tab"><div className="empty-hint">
      Add at least one candidate and one criterion, then score each candidate per
      criterion here to rank them.</div></div>;
  }
  const noteFor = (cid, crid) => {
    const s = (d.candidate_scores || []).find(x => x.candidate_id === cid && x.criterion_id === crid);
    return (s?.notes) ? s.notes : null;
  };
  const scoreFor = (cid, crid) => {
    const s = (d.candidate_scores || []).find(x => x.candidate_id === cid && x.criterion_id === crid);
    return s ? s.score : null;
  };
  const setScore = async (cid, crid, val) => {
    if (val == null) await papi("DELETE", `/api/candidates/${cid}/scores/${crid}`).catch(() => {});
    else await papi("POST", `/api/candidates/${cid}/scores`, { criterion_id: crid, score: val });
    await refresh();
  };
  const ranked = d.candidates_ranked || [];
  const rankOf = (cid) => {
    const c = d.candidates.find(x => x.id === cid);
    const i = ranked.indexOf(cid);
    return (i >= 0 && c && c.match_score != null) ? i + 1 : null;
  };
  return (
    <div className="pe-tab">
      <div className="pe-section-head">
        <h2 className="section-title">compare — match score</h2>
        <div className="section-meta">score each cell 0–10 · weighted by criterion · price left out, the verdict ladder judges it</div>
      </div>
      <div className="hub-scroll-table">
        <table className="hub-table score-grid">
          <thead>
            <tr>
              <th className="sg-corner">criterion <span className="sg-w">·w</span></th>
              {d.candidates.map(c => (
                <th key={c.id} className="sg-cand">
                  {c.name}
                  {/* name only: in a 130px column head the "fails:" prefix
                      pushed the chip past the last column's edge, and the red
                      border already says which way it failed. */}
                  {failsFor(d, c.id).map(f => <span key={f.name} className="fail-flag" title={`fails: ${f.req || f.name}${f.note ? ` — ${f.note}` : ""}`}>{f.name}</span>)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {d.criteria.map(cr => (
              <tr key={cr.id}>
                <td className="sg-crit">
                  <span className={`crit-dot prio-${cr.priority}`} />
                  {cr.name}<span className="sg-w"> ·{cr.weight ?? 3}</span>
                </td>
                {d.candidates.map(c => (
                  <td key={c.id} className="sg-cell">
                    <ScoreCell value={scoreFor(c.id, cr.id)} onSave={v => setScore(c.id, cr.id, v)}
                      cand={c.name} crit={cr.name} note={noteFor(c.id, cr.id)} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="sg-foot-score">
              <td className="sg-crit">match /100</td>
              {/* Only the winning column is accent. Every total used to be,
                  which made the row a band of blue with no leader in it. */}
              {d.candidates.map(c => (
                <td key={c.id} className="sg-cell">
                  {c.match_score != null
                    ? <span className={`sg-weighted${rankOf(c.id) === 1 ? " is-lead" : ""}`}>{c.match_score}</span>
                    : <span className="sg-weighted empty">—</span>}
                </td>
              ))}
            </tr>
            <tr className="sg-foot-rank">
              <td className="sg-crit">rank · coverage</td>
              {d.candidates.map(c => {
                const r = rankOf(c.id);
                return <td key={c.id} className="sg-cell">
                  {r ? <span className={`rank-badge${r === 1 ? " lead" : ""}`}>#{r}</span> : null}
                  <span className="sg-cov"> {c.score_coverage}</span>
                </td>;
              })}
            </tr>
          </tfoot>
        </table>
      </div>

      <div className="pe-section-head is-second">
        <h2 className="section-title">specs</h2>
        <button type="button" className="section-add" disabled={!d.candidates.length}
          title={!d.candidates.length ? "Add a candidate first" : ""}
          onClick={() => setModal({ type: "spec" })}>+ add spec</button>
      </div>
      <SpecsMatrix d={d} />

      <div className="pe-section-head is-second">
        <h2 className="section-title">top 5 — graded, reasoning in full</h2>
      </div>
      {(d.candidates_ranked || []).slice(0, 5).map((cid, i) => {
        const c = d.candidates.find(x => x.id === cid);
        if (!c) return null;
        return <TopFiveRow key={cid} d={d} c={c} rank={i + 1} />;
      })}
    </div>
  );
}

function TopFiveRow({ d, c, rank }) {
  const [open, setOpen] = aUseState(rank === 1);
  return (
    <div className="topfive-row">
      <div className="topfive-head" role="button" tabIndex={0} aria-expanded={open}
        onClick={() => setOpen(o => !o)}
        onKeyDown={e => { if (e.key === "Enter") setOpen(o => !o); else if (e.key === " ") { e.preventDefault(); setOpen(o => !o); } }}>
        <span className="topfive-rank">#{rank}</span>
        <span className="topfive-name">{c.name}</span>
        <span className="topfive-score">{c.match_score != null ? `${c.match_score} (${c.score_coverage})` : "unscored"}</span>
        {failsFor(d, c.id).map(f => <span key={f.name} className="fail-flag">fails: {f.name}</span>)}
        <span className="dim-caret">{open ? "▾" : "▸"}</span>
      </div>
      <HubCollapse open={open}><div className="topfive-assessment">{c.assessment || <span className="dim">no assessment written yet — /purchase fills this at the compare stage.</span>}</div></HubCollapse>
    </div>
  );
}

/* ScoreCell — click-to-edit 0–10 score. Empty input clears the score (delete).
   aria-label carries the candidate/criterion pair + current value since the
   visible glyph is just a number or "·" — meaningless read out of context. */
function ScoreCell({ value, onSave, cand, crit, note }) {
  const [editing, setEditing] = aUseState(false);
  const label = `score ${cand} on ${crit}` + (value == null ? ", not scored" : `, currently ${value}`)
    + (note ? `. Rationale: ${note}` : "");
  if (!editing) {
    // ponytail: native title tooltip carries the rationale — 241 of these exist and had no
    // render path at all. A popover would need positioning, focus and dismiss logic for zero gain.
    return <button type="button" className={`score-cell${value == null ? " empty" : ""}${note ? " has-note" : ""}`}
      aria-label={label} title={note || undefined}
      onClick={() => setEditing(true)}>{value == null ? "·" : value}</button>;
  }
  const commit = (e) => {
    const raw = e.target.value.trim();
    setEditing(false);
    if (raw === "") { if (value != null) onSave(null); return; }
    let n = parseFloat(raw);
    if (Number.isNaN(n)) return;
    n = Math.max(0, Math.min(10, n));
    if (n !== value) onSave(n);
  };
  return <input className="score-cell-input" type="number" min="0" max="10" step="0.5" autoFocus
    aria-label={label}
    defaultValue={value == null ? "" : value} onBlur={commit}
    onKeyDown={e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") { e.target.value = value == null ? "" : value; setEditing(false); } }} />;
}

function SpecsMatrix({ d }) {
  const keys = [...new Set(d.specs.map(s => s.key))];
  if (keys.length === 0) return <div className="empty-hint">No specs yet.</div>;
  return (
    <table className="specs">
      <thead><tr><th>spec</th>{d.candidates.map(c => <th key={c.id}>{c.name}</th>)}</tr></thead>
      <tbody>{keys.map(k => (
        <tr key={k}><td>{k}</td>{d.candidates.map(c => {
          const s = d.specs.find(x => x.candidate_id === c.id && x.key === k);
          return <td key={c.id} className="numeric">{s?.value || "—"}</td>;
        })}</tr>
      ))}</tbody>
    </table>
  );
}

/* ── the item: what you actually bought ──────────────────────────────────────
   Once a winner exists the decision stops being a comparison and becomes an
   object in transit, then an object you own. This block is that object: the
   product itself, where the parcel is, and the specs it shipped with. Tracking
   lives on the decision (one decision buys one thing), specs on the winning
   candidate — so nothing here is re-entered, it is the research row surfacing
   as the receipt. */

/* Carrier → tracking URL. A plain string join, not an API: the point is one
   click to the carrier's own page, and every carrier below takes the number as
   a query param. Amazon is deliberately absent — its tracking needs an order id
   plus a shipment index, so an Amazon order shows its number as text. */
const CARRIERS = {
  ups: "https://www.ups.com/track?tracknum=",
  fedex: "https://www.fedex.com/fedextrack/?trknbr=",
  usps: "https://tools.usps.com/go/TrackConfirmAction?tLabels=",
  dhl: "https://www.dhl.com/us-en/home/tracking.html?tracking-id=",
  ontrac: "https://www.ontrac.com/tracking/?number=",
  "canada post": "https://www.canadapost-postescanada.ca/track-reperage/en#/resultList?searchFor=",
};
const CARRIER_OPTIONS = ["", "ups", "fedex", "usps", "dhl", "ontrac", "canada post", "amazon", "freight", "pickup"];

/* A tracking number he typed in himself arrives with no carrier beside it, and
   without a carrier there is nothing to link to — which is the whole reason a
   number could sit on a row with no way to click through to the carrier's own
   page. These shapes are self-identifying, so the carrier does not have to be
   asked for. Only unambiguous ones are here: a bare 10- or 20-digit number is
   several carriers at once, so it stays unguessed rather than linking wrong.
   Order matters — a USPS number is 20 digits and so is one FedEx format. */
const TRACK_SHAPES = [
  ["ups", /^1Z[0-9A-Z]{16}$/i],
  ["usps", /^9[2345]\d{20}$/],
  ["usps", /^[A-Z]{2}\d{9}US$/i],
  ["ontrac", /^[CD]\d{14}$/i],
  ["fedex", /^\d{12}$/],
];

function carrierFor(number) {
  const n = (number || "").replace(/[\s-]/g, "");
  const hit = TRACK_SHAPES.find(([, re]) => re.test(n));
  return hit ? hit[0] : "";
}

function trackingUrl(carrier, number) {
  const n = (number || "").trim();
  if (!n) return null;
  const base = CARRIERS[(carrier || "").trim().toLowerCase() || carrierFor(n)];
  return base ? base + encodeURIComponent(n.replace(/\s/g, "")) : null;
}

/* What the link should say. "track on ups" beats "track": it names the site the
   click lands on, which is the difference between a link you trust and one you
   hover over first. */
function trackingLabel(carrier, number) {
  const c = (carrier || "").trim().toLowerCase() || carrierFor(number);
  return c ? `track on ${c} ↗` : "track ↗";
}
Object.assign(window, { trackingUrl, trackingLabel, carrierFor, CARRIERS, CARRIER_OPTIONS });

function OwnedItem({ d, winner, refresh, setModal }) {
  const specs = (d.specs || []).filter(s => s.candidate_id === winner.id);
  const { price, ccy, vendor } = candPrice(d, winner);
  // The parcel's facts live on the decision's order row, not on the decision —
  // one store, so this block and the orders tab can never disagree about where
  // the thing is. Migration 007 moved them; the old decision columns are dead.
  const o = d.order;
  const track = o ? trackingUrl(o.carrier, o.tracking_number) : null;
  const patchOrder = async (field, nv) => {
    await papi("PATCH", `/api/orders/${o.id}`, { [field]: nv });
    await refresh();
  };
  const openOrder = async () => {
    await papi("POST", "/api/orders", {
      decision_id: d.id, item: winner.name, vendor: winner.vendor || "",
      url: winner.url || "", image_url: winner.image_url || "",
      return_policy: winner.return_policy || "", source: "decision", ship_status: "ordered",
    });
    await refresh();
  };
  // Warranty and returns are prose here, not values — a paragraph of Trustpilot
  // caveat in the identity line pushed the vendor and the price off their own
  // row. They are facts about the object, so they go in the fact table.
  const rows = [
    ...specs.map(s => [s.key, s.value]),
    ...(winner.warranty ? [["warranty", winner.warranty]] : []),
    ...(winner.return_policy ? [["returns", winner.return_policy]] : []),
  ];
  const delivered = o && (o.ship_status === "delivered" || o.ship_status === "returned");
  const tracking = [
    { field: "ship_status", k: "status", select: ORDER_STATUSES },
    { field: "carrier", k: "carrier", select: CARRIER_OPTIONS },
    { field: "order_number", k: "order #" },
    { field: "ordered_on", k: "ordered" },
    delivered ? { field: "delivered_on", k: "delivered" } : { field: "eta", k: "eta" },
  ];
  const ret = delivered ? returnLine(o) : null;
  return (
    <>
      <div className="pe-section-head">
        <h2 className="section-title">the item</h2>
        {o?.ship_status
          ? <div className={`ship-chip is-${o.ship_status.replace(/ /g, "-")}`}>{o.ship_status}</div>
          : <div className="section-meta">what you bought · where it is</div>}
      </div>

      <div className="owned">
        {winner.image_url
          ? <img className="owned-shot" src={winner.image_url} alt="" loading="lazy"
              onError={e => { e.target.style.display = "none"; }} />
          : <div className="owned-shot is-empty" aria-hidden="true">◆</div>}
        <div className="owned-meat">
          <div className="owned-name">{winner.name}</div>
          {/* The price here IS the order total's editor — paid beats quoted, and
              until an order total is entered it shows the researched price so the
              line is never blank. One number, one editor, no second copy in the
              strip below. */}
          <div className="owned-sub">
            <span>{(o?.vendor) || vendor || "—"}</span>
            <span>·</span>
            <span className="owned-paid" title="what you actually paid">
              {o
                ? <Editable value={o.total} number
                    displayFn={v => fmtMoney(v != null ? v : price, v != null ? o.currency : ccy)}
                    onSave={nv => patchOrder("total", nv)} />
                : fmtMoney(price, ccy)}
            </span>
          </div>
          {d.verdict_reason ? <div className="owned-why">{d.verdict_reason}</div> : null}
          <div className="card-actions">
            {winner.url ? <a className="icon-btn" href={winner.url} target="_blank" rel="noopener">product page ↗</a> : null}
            {track ? <a className="icon-btn" href={track} target="_blank" rel="noopener">{trackingLabel(o.carrier, o.tracking_number)}</a> : null}
            <button type="button" className="icon-btn" onClick={() => setModal({ type: "edit-candidate", candidate: winner })}>edit item</button>
          </div>
        </div>
      </div>

      {o ? (
        <>
          <div className="pe-meta-strip owned-tracking">
            {tracking.map(t => (
              <span key={t.field} className="pe-meta-cell">
                <span className="reflect-k">{t.k}</span>
                {t.select
                  ? <EditableSelect value={o[t.field]} options={t.select} onSave={nv => patchOrder(t.field, nv)} />
                  : <Editable value={o[t.field]} onSave={nv => patchOrder(t.field, nv)} />}
              </span>
            ))}
            <span className={`pe-meta-cell${o.tracking_number ? "" : " is-missing"}`}>
              <span className="reflect-k">tracking</span>
              <Editable value={o.tracking_number} placeholder="+ add tracking number"
                onSave={nv => patchOrder("tracking_number", nv)} />
            </span>
          </div>
          {delivered ? (
            <div className="pe-meta-strip owned-returns">
              <span className="pe-meta-cell">
                <span className="reflect-k">return window</span>
                <Editable value={o.return_days} number displayFn={v => v != null ? `${v} days` : "—"}
                  onSave={nv => patchOrder("return_days", nv)} />
              </span>
              <span className={`pe-meta-cell ord-return tone-${ret.tone}`}>{ret.text}</span>
            </div>
          ) : null}
        </>
      ) : (
        <div className="empty-hint">
          No order recorded for this one.{" "}
          <button type="button" className="icon-btn" onClick={openOrder}>record the order</button>
        </div>
      )}

      <div className="pe-section-head is-second">
        <h2 className="section-title">specs</h2>
        <div className="section-meta">{rows.length ? `${rows.length} recorded` : "none recorded"}</div>
      </div>
      {rows.length === 0
        ? <div className="empty-hint">No specs recorded for this one. Add them on the compare tab.</div>
        : <table className="specs"><tbody>{rows.map(([k, v]) => (
            <tr key={k}><td>{k}</td><td className="numeric">{v || "—"}</td></tr>
          ))}</tbody></table>}
    </>
  );
}

/* ── verdict: the pick + post-purchase reflection ────────────────────────────── */

function VerdictTab({ d, onPatchDecision, refresh, setModal }) {
  const winner = d.verdict_candidate_id ? d.candidates.find(c => c.id === d.verdict_candidate_id) : null;
  const pick = (cid) => setModal({ type: "verdict-reason", candidateId: cid, currentReason: d.verdict_reason });
  const reflection = [
    { label: "What it got right", field: "outcome_well", multiline: true, bullets: true },
    { label: "What disappointed", field: "outcome_regret", multiline: true, bullets: true },
  ];
  return (
    <div className="pe-tab">
      {winner && <OwnedItem d={d} winner={winner} onPatchDecision={onPatchDecision} refresh={refresh} setModal={setModal} />}
      <div className={`pe-section-head${winner ? " is-second" : ""}`}>
        <h2 className="section-title">the pick</h2>
        <div className="section-meta">sub scores, then match /100 (price left out), then the price ladder · click a header to sort</div>
      </div>
      {d.candidates.length === 0
        ? <div className="empty-hint">No candidates to choose between yet.</div>
        : <VerdictTable d={d} winner={winner} pick={pick} />}

      <div className="pe-section-head is-second">
        <h2 className="section-title">post-purchase reflection</h2>
        <div className="section-meta">fill in once you've lived with it</div>
      </div>
      <div className="pe-meta-strip">
        <span className="pe-meta-cell">
          <span className="reflect-k">satisfaction</span>
          <Editable value={d.outcome_rating} number displayFn={v => v != null ? `${v}/5` : "rate 1–5"}
            onSave={nv => onPatchDecision("outcome_rating", nv == null ? null : Math.max(1, Math.min(5, Math.round(nv))))} />
        </span>
        <span className="pe-meta-cell">
          <span className="reflect-k">would re-buy</span>
          <EditableSelect value={d.would_repurchase} options={["", "yes", "no", "maybe"]}
            onSave={nv => onPatchDecision("would_repurchase", nv)} />
        </span>
        <span className="pe-meta-cell">
          <span className="reflect-k">decided</span>
          <Editable value={d.decided_date} displayFn={v => v || "date"}
            onSave={nv => onPatchDecision("decided_date", nv)} />
        </span>
      </div>
      <div className="pe-fieldset">
        {reflection.map(f => (
          <div key={f.field} className="pe-field">
            <div className="pe-field-label">{f.label}</div>
            <div className="pe-field-value">
              <Editable value={d[f.field]} multiline displayFn={f.bullets ? (v => bulletList(v)) : null}
                onSave={nv => onPatchDecision(f.field, nv)} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* VerdictTable — one table, one ranking at a time: each criterion's sub score,
   the match score they add up to (price left out), then the price ladder's
   columns: all-in price with tax, what the step up from the best cheaper
   option costs per match point, and whether it earned it (≤ step_cutoff).
   Every column but the pick button sorts; a second click flips direction. */
function VerdictTable({ d, winner, pick }) {
  const [sort, setSort] = aUseState({ key: "match", dir: -1 });
  const money = (v) => fmtMoney(v, d.currency);
  const crits = d.criteria.filter(cr => cr.in_match);
  const stepBy = Object.fromEntries((d.ladder || []).map(s => [s.candidate_id, s]));
  const scoreBy = {};
  (d.candidate_scores || []).forEach(s => { scoreBy[`${s.candidate_id}:${s.criterion_id}`] = s.score; });
  const verdictOf = (s) => !s ? null : s.candidate_id === d.ladder_pick ? "★ ladder pick"
    : s.vs_id == null ? "base" : s.accepted ? "worth it" : "not worth it";
  const cols = [
    { key: "name", label: "candidate", val: c => c.name.toLowerCase() },
    ...crits.map(cr => ({ key: `cr${cr.id}`, label: cr.name.split(/[\s/]+/)[0], title: `${cr.name} · weight ${cr.weight ?? 3}`, num: true, sub: true,
      val: c => scoreBy[`${c.id}:${cr.id}`] ?? null })),
    { key: "match", label: "match /100", num: true, end: true, val: c => c.match_score },
    { key: "price", label: "all-in", num: true, val: c => c.all_in_price },
    { key: "step", label: "$ / point", num: true, title: `extra dollars per match point over the best cheaper option; worth it at ≤ ${money(d.step_cutoff)}`,
      val: c => (stepBy[c.id] || {}).per_point ?? null },
    { key: "verdict", label: "ladder", val: c => { const s = stepBy[c.id]; return !s ? null : s.candidate_id === d.ladder_pick ? 3 : s.accepted ? 2 : 1; } },
  ];
  const col = cols.find(x => x.key === sort.key) || cols[0];
  // nulls sink in both directions: an unscored cell is missing, not low
  const rows = [...d.candidates].sort((a, b) => {
    const va = col.val(a), vb = col.val(b);
    if (va == null || vb == null) return (va == null) - (vb == null);
    return (va < vb ? -1 : va > vb ? 1 : 0) * sort.dir;
  });
  const flip = (k) => setSort(s => ({ key: k, dir: s.key === k ? -s.dir : (k === "name" || k === "price" || k === "step" ? 1 : -1) }));
  const th = (x) => {
    const on = sort.key === x.key;
    return (
      <th key={x.key} title={x.title} tabIndex={0}
        className={`hub-sortable${x.num ? " numeric" : ""}${x.sub ? " vt-subh" : ""}${x.end ? " vt-end" : ""}${x.key === "name" ? " vt-name" : ""}${on ? " hub-sorted" : ""}`}
        aria-sort={on ? (sort.dir > 0 ? "ascending" : "descending") : "none"}
        onClick={() => flip(x.key)}
        onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); flip(x.key); } }}>
        <span>{x.label}<span className="hub-sort-indicator">{on ? (sort.dir > 0 ? "▲" : "▼") : "↕"}</span></span>
      </th>);
  };
  const stepText = (s) => !s || s.vs_id == null ? "—" : s.gain <= 0 ? "no gain" : money(s.per_point);
  const stepTitle = (s) => !s || s.vs_id == null ? "cheapest scored option, the starting point"
    : `${s.gain > 0 ? "+" : ""}${s.gain} match points for ${money(s.extra)} more than ${(d.candidates.find(x => x.id === s.vs_id) || {}).name}`;
  return (
    <div className="hub-scroll-table">
      <table className="hub-table verdict-table">
        <thead><tr>{cols.map(th)}<th aria-label="pick" /></tr></thead>
        <tbody>
          {rows.map(c => {
            const s = stepBy[c.id], v = verdictOf(s);
            return (
              <tr key={c.id} className={`${winner && winner.id === c.id ? "chosen" : ""}${d.ladder_pick === c.id ? " is-lead" : ""}`}>
                <td className="vt-name">{c.name}</td>
                {crits.map(cr => <td key={cr.id} className="numeric vt-sub">{scoreBy[`${c.id}:${cr.id}`] ?? "·"}</td>)}
                <td className="numeric vt-end">{c.match_score ?? "—"}</td>
                <td className="numeric">{c.all_in_price != null ? money(c.all_in_price) : "—"}</td>
                <td className="numeric vt-step" title={stepTitle(s)}>{stepText(s)}</td>
                <td className={`vt-verdict${s && !s.accepted ? " ladder-no" : ""}`}>{v || "—"}</td>
                <td>{winner && winner.id === c.id
                  ? <span className="verdict-tag">★ chosen</span>
                  : <button type="button" className="icon-btn" onClick={() => pick(c.id)}>pick</button>}</td>
              </tr>);
          })}
        </tbody>
      </table>
    </div>
  );
}

Object.assign(window, { DecisionArena, ProConPill, OwnedItem });
