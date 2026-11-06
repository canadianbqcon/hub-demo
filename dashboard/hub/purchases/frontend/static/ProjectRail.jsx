/* ProjectRail.jsx — left rail: the decision list, with the two states a
   decision is actually in at the top and the money it resolves to at the
   foot.

   Rebuilt 2026-08-28, then again 2026-09-06 off the option rig, where every
   part of the rail got four treatments and he picked one each. What landed:

   - NO HEADER ROW. It said "decisions" directly under a tab that already
     says decisions, and cost 41px to do it. Collapse moves to a tab on the
     rail's own right edge, which is the border it actually drags.
   - TWO FILTER CELLS, NOT THREE. Live and decided are buttons; open budget
     never was one and no longer looks like one — it reads as a labelled
     line under them. A control shaped like a button is a button.
   - SEARCH RESTS AS AN ICON, under the totals rather than in a header there
     no longer is. It costs nothing across the sessions where nothing is
     searched, and expands in place when it is.
   - ROWS GROUP UNDER STAGE HEADINGS and drop the stage word. "decided"
     appeared five times down one column; the list says it once, in a sticky
     heading, and the row is a name and a number.
   - THE CREATE BUTTON FLOATS over the foot of the list on a fade, with no
     bordered strip around it. Same place, one less band of chrome.

   The money foot is the one part he left alone: it stays exactly as it was. */

const { useRef: rUseRef } = React;

const CLOSED_STAGES = ["decided", "cancelled"];
const _isClosed = (stage) => CLOSED_STAGES.includes(stage);

/* The price the decision resolves to. While it is open that is the leading
   candidate (the price ladder's pick) — what the decision is currently asking of you, as opposed to the
   ceiling you set. Once it is closed the leader is the wrong number: you may
   not have bought it, and a settled decision quoting a stranger's list price
   reads as what the thing cost when it did not (carry-on luggage showed $299
   for a Bellroy against $198.40 actually paid for a Monos). So a closed
   decision reads its own verdict, and prefers the real all-in order total
   over any list price. Prefers the newest price point over the candidate's
   base price otherwise, same as the candidate rows do. */
function leadPrice(d) {
  if (!d) return null;
  const closed = _isClosed(d.stage);
  const cands = d.candidates || [];
  // an open decision asks for the price ladder's pick, not the best match:
  // the best match can be the one a step up too expensive to earn its price
  const ranked = d.ladder_pick != null ? [d.ladder_pick] : (d.candidates_ranked || []);
  const verdict = cands.find(c => c.id === d.verdict_candidate_id) || null;
  const lead = closed
    ? (verdict || (ranked.length && cands.find(c => c.id === ranked[0])) || null)
    : ((ranked.length && cands.find(c => c.id === ranked[0])) || verdict || null);
  if (!lead) return null;
  // The order total is what left his account — shipping and tax included —
  // so it outranks every list price once it exists.
  if (closed && verdict && lead.id === verdict.id && d.order_total != null) {
    return { price: d.order_total, ccy: d.currency, name: lead.name, label: "paid" };
  }
  const pp = (d.price_points || []).filter(p => p.candidate_id === lead.id);
  const price = pp.length ? pp[0].price : lead.base_price;
  if (price == null) return null;
  return { price, ccy: (pp.length ? pp[0].currency : lead.currency), name: lead.name,
           label: closed && verdict && lead.id === verdict.id ? "paid" : "ask" };
}

/* The three buckets the list groups into, in the order a queue is read: what
   is still moving, what is settled, what was abandoned. A group with nothing
   in it renders nothing at all — an empty heading is worse than no heading. */
const GROUPS = [
  { key: "live", label: "live", match: (p) => !_isClosed(p.stage) },
  { key: "decided", label: "decided", match: (p) => p.stage === "decided" },
  { key: "cancelled", label: "cancelled", match: (p) => p.stage === "cancelled" },
];

// stage rank for the "stage" sort: live (any non-terminal stage) before
// decided before cancelled; the bucket order GROUPS already renders.
// list-filter's sort is stable, so within a bucket this leaves the incoming
// (p.updated DESC, from the API) order alone rather than re-deriving it.
function _stageRank(p) {
  if (p.stage === "cancelled") return 2;
  if (p.stage === "decided") return 1;
  return 0;
}

const DECISIONS_LF_CFG = {
  key: "purchases.decisions",
  search: { placeholder: "search a decision…", fields: (p) => p.name || "" },
  facet: {
    label: "stage", allLabel: "stages",
    options: GROUPS, // same three buckets, same shape ({key, label, match})
    defaultOn: GROUPS.map(g => g.key),
  },
  sorts: [
    { key: "stage", label: "stage", cmp: (a, b) => _stageRank(a) - _stageRank(b) },
    { key: "name", label: "name", cmp: (a, b) => (a.name || "").localeCompare(b.name || "") },
    { key: "budget", label: "budget", dir: "desc",
      cmp: (a, b) => (a.budget_max ?? -Infinity) - (b.budget_max ?? -Infinity) },
    { key: "updated", label: "updated", dir: "desc",
      cmp: (a, b) => (a.updated || "").localeCompare(b.updated || "") },
  ],
  defaultSort: "stage",
};

function ProjectRail({ projects, selectedProjectId, decision,
                       collapsed, onToggleCollapse, onSelect, onNewProject }) {
  const lfRef = rUseRef(null);
  const { rows: items, state: lfState } = useListFilter(lfRef, DECISIONS_LF_CFG, projects);

  // A decision with a budget is one you have sized; the sum is what the open
  // queue could cost you, which is the only cross-decision figure the rail
  // can honestly show (individual asks live on the decision itself). Reads
  // the full list, not the filtered one; the figure is "what's open", not
  // "what's currently shown".
  const openBudget = projects
    .filter(p => !_isClosed(p.stage) && p.budget_max != null)
    .reduce((a, p) => a + p.budget_max, 0);

  // Grouped headings are the "stage" sort's own shape (it IS the bucket
  // order); any other sort renders the flat list that sort actually means.
  const groups = lfState && lfState.sort === "stage"
    ? GROUPS.map(g => ({ ...g, rows: items.filter(g.match) })).filter(g => g.rows.length)
    : null;

  const renderRow = (p) => (
    <button key={p.id} type="button"
      className={"pe-proj-row"
        + (p.id === selectedProjectId ? " active" : "")
        + (p.stage === "cancelled" ? " is-cancelled" : "")}
      onClick={() => onSelect(p.id)}>
      <span className="pe-proj-name">{p.name}</span>
      {p.budget_max != null ? <span className="pe-proj-budget">{fmtMoney(p.budget_max)}</span> : null}
    </button>
  );

  const lead = leadPrice(decision);
  const budget = decision ? decision.budget_max : null;
  const over = lead && budget != null && lead.price > budget;

  return (
    <aside className={`pe-rail${collapsed ? " collapsed" : ""}`}>
      {/* Collapse lives on the border it moves, not in a header row. */}
      <button type="button" className="pe-rail-edge" title="Collapse"
        aria-label={collapsed ? "expand rail" : "collapse rail"}
        onClick={onToggleCollapse}>{collapsed ? "›" : "‹"}</button>

      <div className="pe-rail-summary">
        <div ref={lfRef} />

        {/* Not a filter and no longer shaped like one. */}
        <div className="pe-budline" title="sum of the budgets set on live decisions">
          <span className="pe-budline-l">open budget</span>
          <span className="pe-budline-n">{openBudget ? fmtMoney(openBudget) : "—"}</span>
        </div>
      </div>

      <div className="pe-rail-list">
        {!projects.length
          ? <div className="empty-hint">No decisions yet. Create one below.</div>
          : !items.length
          ? <div className="empty-hint">No matches.</div>
          : groups
          ? groups.map(g => (
            <div className="pe-group" key={g.key}>
              <div className="pe-group-head">
                <span className="pe-group-l">{g.label}</span>
                <span className="pe-group-n">{g.rows.length}</span>
              </div>
              {g.rows.map(renderRow)}
            </div>
          ))
          : items.map(renderRow)}
      </div>

      {/* One filled action per view. It sits over the foot of the list on a
          fade rather than inside a bordered strip: same place the hand goes,
          one less band of chrome, and the fade says the list runs on under
          it where a hard border claimed it had ended. */}
      <div className="pe-rail-newfloat">
        <button type="button" className="sidebar-btn primary" onClick={onNewProject}>+ new decision</button>
      </div>

      {/* The number the page resolves to. Budget is the ceiling you set; the
          figure above it is what the current leader costs while the decision
          is open and what he actually paid once it is closed, so the pair
          reads as "what I allowed" over "what it costs" and going over says
          so. The label switches ask -> paid with it. */}
      {decision && (budget != null || lead) ? (
        <div className="pe-rail-money">
          {lead ? (
            <div className={`pmoney${over ? " is-over" : ""}`}>
              <span className="pmoney-n">{fmtMoney(lead.price, lead.ccy)}</span>
              <span className="pmoney-l">{lead.label} · {truncate(lead.name, 17)}</span>
            </div>
          ) : null}
          {budget != null ? (
            <div className={`pmoney${lead ? " is-sub" : ""}`}>
              <span className="pmoney-n">{fmtMoney(budget, decision.currency)}</span>
              <span className="pmoney-l">{over ? "budget · over" : "budget"}</span>
            </div>
          ) : null}
        </div>
      ) : null}
    </aside>
  );
}
Object.assign(window, { ProjectRail });
