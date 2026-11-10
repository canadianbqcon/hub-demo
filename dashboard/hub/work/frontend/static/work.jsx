/* work.jsx — root of the work portal: Juniper & Co's band of headline numbers
   over coming-up shifts, paid shifts and the board's sections. Picked on
   Workbench 2026-11-09 (work-page-richer, "Branded J&Co banner over three columns").
   Data: /work/api/summary (earnings.db + work.db). Every section opens /jc/,
   which has no per-tab links yet. */

const usd = (n) => "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const day = (s, o) => new Date(s + "T12:00:00").toLocaleDateString("en-US", o || { weekday: "short", month: "short", day: "numeric" });
const md = (s) => day(s, { month: "short", day: "numeric" });
const clock = (s) => { let [h, m] = s.split(":").map(Number); const p = h < 12 ? "a" : "p"; h = h % 12 || 12; return h + (m ? ":" + String(m).padStart(2, "0") : "") + p; };
const span = (u) => clock(u.start) + " – " + clock(u.end);
const hrs = (n) => (Number.isInteger(n) ? n : +n.toFixed(1)) + " h";

function Slab({ title, meta, children, className }) {
  return (
    <section className={"wx-slab " + (className || "")}>
      <div className="wx-row"><p className="wx-k">{title}</p>{meta && <p className="wx-k">{meta}</p>}</div>
      {children}
    </section>
  );
}

function Rows({ rows, empty }) {
  if (!rows.length) return <p className="wx-dim wx-empty">{empty}</p>;
  return (
    <ul className="wx-l">
      {rows.map((r, i) => <li key={i}><span className="b">{r[0]}</span><span className="dim">{r[1]}</span><span className="end">{r[2]}</span></li>)}
    </ul>
  );
}

function WorkPage({ d }) {
  const nx = d.up[0], p = d.last_pay;
  const booked = d.up.reduce((a, u) => a + u.hours, 0);
  return (
    <div className="wx">
      <section className="wc-band">
        <img className="wx-mark big" src="/jc/static/juniper.svg" alt="" />
        <div className="wc-id"><h1>Juniper &amp; Co</h1><p>Barback · {d.ytd.stubs} pay stubs this year</p></div>
        <div className="wc-nums">
          <div><p>Next shift</p><b>{nx ? day(nx.date) : "None booked"}</b><span>{nx ? span(nx) : "next two weeks"}</span></div>
          {p && <div><p>Last pay</p><b>{usd(p.net)}</b><span>net, week of {md(p.start)}</span></div>}
          <div><p>{d.today.slice(0, 4)} so far</p><b>{usd(d.ytd.gross)}</b><span>gross</span></div>
        </div>
        <a className="wx-open on-band" href="/jc/">Open board <b>›</b></a>
      </section>
      <div className="wx-three">
        <Slab title="Coming up" meta={hrs(booked)}>
          <Rows rows={d.up.map((u) => [day(u.date), span(u), hrs(u.hours)])} empty="No shifts in the next two weeks." />
        </Slab>
        <Slab title="Last paid shifts" meta="from stubs">
          <Rows rows={d.paid.map((s) => [day(s.date), s.hours.toFixed(2) + " h", usd(s.total)])} empty="No pay stubs yet." />
        </Slab>
        <Slab title="Board sections" meta="Juniper & Co" className="wx-tools">
          {d.tools.map((x) => <a className="wx-tool" key={x[0]} href="/jc/"><span className="b">{x[0]}</span><span className="dim">{x[1]}</span><b>›</b></a>)}
        </Slab>
      </div>
    </div>
  );
}

function WorkApp() {
  const [d, setD] = React.useState(null);
  const [err, setErr] = React.useState("");
  React.useEffect(() => {
    fetch("/work/api/summary")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
      .then(setD)
      .catch((e) => setErr(String(e.message || e)));
  }, []);
  return (
    <div className="hub-shell work-shell" data-screen-label="work">
      <Topbar crumb="work" />
      <main className="work-body">
        {d ? <WorkPage d={d} /> : err
          ? <div className="wx"><section className="wx-slab"><p className="wx-k">Could not load work data ({err})</p><a className="wx-open" href="/jc/">Open board <b>›</b></a></section></div>
          : null}
      </main>
      <StatusStrip />
    </div>
  );
}
ReactDOM.createRoot(document.getElementById("root")).render(<WorkApp />);
