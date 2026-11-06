/* credit cards panel — center middle. minimum-due tracking. */

// days until a due or billing date, as the cards and subscriptions panels both show it
function daysLabel(n) {
  return n === 0 ? "today" : n === 1 ? "1 day" : n < 0 ? `${-n}d late` : `${n} days`;
}

function CreditCards({ cards, now, syncedAt }) {
  return (
    <div className="panel fixed">
      <div className="panel-head">
        {/* h3, not h2 — this panel always renders nested under the "recap" column
            head (App.jsx), so it's a subsection, not a peer, in the heading
            outline (home critique P2: no real heading hierarchy). */}
        <h3 className="panel-title">cards · minimum due</h3>
        <span className="panel-meta">{`simplefin · synced ${relAgo(syncedAt, now)}`}</span>
      </div>
      <div className="panel-body">
        <div className="cc-list">
          {cards.map((c, i) => (
            <div className="cc-row" key={i}>
              <span className="cc-name">
                {c.name}{c.last4 ? <span className="last4">··{c.last4}</span> : null}
              </span>
              <span className="cc-due">{c.due_in_days == null ? c.due : daysLabel(c.due_in_days)}</span>
              <span className="cc-amt">{c.amt}</span>
              {c.status !== "ok" && <span className={`cc-status ${c.status}`}>{c.status}</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { CreditCards, daysLabel });
