/* hub · trips landing body (2026-10-13): React port of trips-landing.js. Same DOM and classes
   as the plain page. One fetch (/trips/api/trips/summary), one vertical spine, one job: pick
   a trip. "next up" is picked here, not in SQL (scheduled_time holds mixed formats SQLite
   can't order chronologically). Template globals: TRIP_VIEWER (read by trips-cost.js). The
   cost stat is TripsUI.TripsCost from trips-cost.jsx. */
window.TripsUI = window.TripsUI || {};
(() => {
const { useState, useEffect } = React;
const T = window.TripTime;
const { TripsCost } = window.TripsUI;

function status(msg, meta) {
  document.getElementById("statusMsg").textContent = msg;
  if (meta !== undefined) document.getElementById("statusMeta").textContent = meta;
}

/* Today as YYYY-MM-DD in the viewer's own calendar. Trip dates are bare local dates with no
   zone, so "today" has to be local too: Date#toISOString would hand back the UTC day and roll
   over at 8pm here. */
function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
const daysBetween = (a, b) => Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86400000);

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function fmtDay(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
  return m ? `${MON[Number(m[2]) - 1]} ${Number(m[3])}` : "";
}
/* "Sep 10 - 14" when one month, "Dec 30 - Jan 2" when it straddles. */
function fmtRange(start, end) {
  if (!start) return "dates not set";
  if (!end || end === start) return fmtDay(start);
  const sameMonth = start.slice(0, 7) === end.slice(0, 7);
  return `${fmtDay(start)} – ${sameMonth ? String(Number(end.slice(8, 10))) : fmtDay(end)}`;
}

/* The spine label. Returns {n, u}, a big number and its unit, so past, upcoming and
   in-progress all render through the same two slots. */
function countdown(trip, today) {
  const start = trip.start_date, end = trip.end_date || trip.start_date;
  if (!start) return { n: "—", u: "no dates", cls: "" };
  if (today >= start && today <= end) {
    const span = daysBetween(start, end) + 1;
    return { n: `day ${daysBetween(start, today) + 1}`, u: `of ${span}`, cls: "is-now" };
  }
  /* Days, always, never months: the spine exists to compare one trip's distance against
     another's at a glance. */
  const d = daysBetween(today, start);
  if (d > 0) return { n: String(d), u: d === 1 ? "day out" : "days out", cls: "" };
  const ago = daysBetween(end, today);
  if (ago < 60) return { n: String(ago), u: "days ago", cls: "is-past" };
  return { n: String(Math.round(ago / 30.44)), u: "months ago", cls: "is-past" };
}

function nextUp(trip, today) {
  const rows = (trip.scheduled || []).slice().sort(T.byDateTime);
  for (let i = 0; i < rows.length; i++) if (rows[i].scheduled_date >= today) return rows[i];
  return rows[0] || null;   // wholly in the past: show its opener
}

function nightCount(trip) {
  if (!trip.start_date || !trip.end_date) return null;
  const n = daysBetween(trip.start_date, trip.end_date);
  return n > 0 ? n : null;
}

function Stat({ n, label }) {
  return (
    <span className={`stat${n ? "" : " is-zero"}`}>
      <span className="stat-n">{n}</span><span className="stat-l">{label}</span>
    </span>
  );
}

/* booked / not-yet / none-added are three different states, so the pip says which one
   rather than just going dark. */
function Pip({ label, one, booked, total }) {
  if (!total) return <span className="pip">no {label}</span>;
  if (booked) return <span className="pip on">{label} booked</span>;
  return <span className="pip">{total} {one} option{total === 1 ? "" : "s"}</span>;
}

function Card({ trip, today }) {
  const nights = nightCount(trip);
  const next = nextUp(trip, today);
  const nextTime = next ? T.fmtClock(T.parseClock(next.scheduled_time)) : "";
  const name = String(trip.name || "untitled").replace(/\s+trip$/i, "");
  const where = String(trip.destination || "");
  const showWhere = where && where.toLowerCase().indexOf(name.toLowerCase()) !== 0;
  return (
    <a className="node-card" href={`/trips/${trip.id}`}>
      <div className="card-name">{name}</div>
      {showWhere && <div className="card-where">{where}</div>}
      <div className="card-dates"><b>{fmtRange(trip.start_date, trip.end_date)}</b>
        {nights ? ` · ${nights}${nights === 1 ? " night" : " nights"}` : ""}</div>
      {next && <div className="card-next"><span className="card-next-l">first up</span>
        <span><b>{next.name}</b> {`· ${fmtDay(next.scheduled_date)}${nextTime ? ` ${nextTime}` : ""}`}</span></div>}
      <div className="card-stats">
        <Stat n={trip.n_scheduled} label="scheduled" />
        <Stat n={trip.n_ideas} label="ideas" />
        <Stat n={trip.n_crew} label="crew" />
        <TripsCost trip={trip} />
        <span className="card-pips">
          <Pip label="stay" one="stay" booked={trip.n_housing_booked} total={trip.n_housing} />
          <Pip label="flights" one="flight" booked={trip.n_flights_booked} total={trip.n_flights} />
        </span>
      </div>
      {trip.cal_status === "deleted" && <div className="card-warn">calendar event was deleted outside the dashboard</div>}
    </a>
  );
}

function Node({ trip, today, isNext }) {
  const c = countdown(trip, today);
  const cls = ["node", c.cls, isNext ? "is-next" : ""].filter(Boolean).join(" ");
  return (
    <article className={cls}>
      <div className="node-when"><span className="when-n">{c.n}</span><span className="when-u">{c.u}</span></div>
      <div className="node-rail" aria-hidden="true"></div>
      <Card trip={trip} today={today} />
    </article>
  );
}

/* The trip list, fetched at most once per page. Cleared on failure so a retry really retries. */
function tripSummary() {
  if (!window.__hubTripSummary) {
    window.__hubTripSummary = fetch("/trips/api/trips/summary").then((r) => {
      if (!r.ok) { window.__hubTripSummary = null; throw new Error(`${r.status}`); }
      return r.json();
    });
  }
  return window.__hubTripSummary;
}

/* A render error shows the same words the load fallback does. */
class Boundary extends React.Component {
  constructor(p) { super(p); this.state = { failed: false }; }
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(e) { console.error("trips-landing", e); }
  render() { return this.state.failed ? <div className="hub-error">page failed to load</div> : this.props.children; }
}

function Body() {
  // trips: null while loading, else the summary rows; err: the message when the load failed
  const [trips, setTrips] = useState(null);
  const [err, setErr] = useState(null);
  const [pastOpen, setPastOpen] = useState(false);

  const boot = () => {
    tripSummary().then((rows) => { setErr(null); setTrips(rows); }).catch((e) => {
      status(`couldn't load trips — ${e.message || e}`);
      setErr(true);
    });
  };
  useEffect(() => { document.getElementById("landing").setAttribute("data-react-mounted", "trips-landing"); boot(); }, []);
  useEffect(() => {
    if (!trips) return;
    status(trips.length ? "loaded" : "no trips", trips.length ? `${trips.length} trip${trips.length === 1 ? "" : "s"}` : undefined);
  }, [trips]);

  if (trips && !trips.length) return <div className="spine-empty">no trips yet</div>;
  if (trips) {
    const today = todayISO();
    const upcoming = [], past = [];
    trips.forEach((t) => {
      const end = t.end_date || t.start_date;
      (end && end < today ? past : upcoming).push(t);
    });
    upcoming.sort((a, b) => String(a.start_date).localeCompare(String(b.start_date)));
    past.sort((a, b) => String(b.start_date).localeCompare(String(a.start_date)));
    return (
      <div className="spine">
        {/* the first upcoming trip is the one the page is really about */}
        {upcoming.map((t, i) => <Node key={t.id} trip={t} today={today} isNext={i === 0} />)}
        {past.length > 0 && <>
          <button type="button" className="past-toggle" id="pastToggle" aria-expanded={pastOpen ? "true" : "false"}
            aria-controls="pastList" onClick={() => setPastOpen(!pastOpen)}>
            <span className="past-caret">{"›"}</span> past · {past.length}</button>
          <div id="pastList"><HubCollapse open={pastOpen}>{past.map((t) => <Node key={t.id} trip={t} today={today} isNext={false} />)}</HubCollapse></div>
        </>}
      </div>
    );
  }
  if (err) return (
    <div className="spine-empty">couldn't load trips
      <div><button type="button" className="spine-empty-cta" id="retry" onClick={boot}>retry</button></div></div>
  );
  return <div className="spine-loading">loading trips…</div>;
}

const host = document.getElementById("landing");
host.textContent = "";  // the template's static copy is only the load fallback
ReactDOM.createRoot(host).render(<Boundary><Body /></Boundary>);
})();
