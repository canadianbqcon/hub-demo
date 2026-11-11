/* plan.jsx: /clash/plan. Builder queue lanes, wall costs, resource shortfall. */
const RES = ["Gold", "Elixir", "Dark Elixir"];
const fmt = (n) => Number(n).toLocaleString("en-US");
const when = (s) => {
  const d = new Date(s);  // the queue runs into later years: name the year whenever it is not this one
  return d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
    ...(d.getFullYear() !== new Date().getFullYear() && { year: "numeric" }) });
};

function Lanes({ d }) {
  return (
    <section className="cx-slab">
      <div className="cx-hd"><h3>Builder queue</h3><span className="est">Done around {when(d.done_at)}</span></div>
      <p className="est">{d.estimate}</p>
      {d.lanes.map((lane, i) => (
        <div className="lane" key={i}>
          <h4>Builder {i + 1}</h4>
          {lane.length === 0 && <p className="est">Nothing left to build.</p>}
          {lane.map((s, j) => (
            <div className="step" key={j}>
              <img className="cx-ico cx-ico-sm" src={"/clash/static/icons/" + s.icon} alt="" />
              <b>{s.name} to level {s.level}</b>
              <span>{when(s.start)} to {when(s.end)}</span>
            </div>
          ))}
        </div>
      ))}
    </section>
  );
}

function Walls({ walls }) {
  const cell = (o) => RES.filter((r) => o[r]).map((r) => fmt(o[r]) + " " + r).join(", ") || "None";
  return (
    <section className="cx-slab">
      <div className="cx-hd"><h3>Walls</h3></div>
      <table>
        <thead><tr><th>Level</th><th className="n">Count</th><th>To next level</th><th>To max</th></tr></thead>
        <tbody>
          {walls.map((w) => (
            <tr key={w.level}><td>{w.level}</td><td className="n">{fmt(w.count)}</td><td>{cell(w.to_next)}</td><td>{cell(w.to_max)}</td></tr>
          ))}
          {walls.length === 0 && <tr><td colSpan="4">No walls in this village.</td></tr>}
        </tbody>
      </table>
    </section>
  );
}

function Resources({ have, setHave, rows }) {
  return (
    <section className="cx-slab">
      <div className="cx-hd"><h3>Resources</h3></div>
      <div className="row">
        {RES.map((r) => (
          <label key={r}>{r}{" "}
            <input type="number" min="0" value={have[r] ?? ""} onChange={(e) => setHave({ ...have, [r]: Number(e.target.value) || 0 })} />
          </label>
        ))}
      </div>
      <table>
        <thead><tr><th>Resource</th><th className="n">Need</th><th className="n">Have</th><th className="n">Short</th></tr></thead>
        <tbody>
          {Object.entries(rows).map(([r, v]) => (
            <tr key={r}><td>{r}</td><td className="n">{fmt(v.need)}</td><td className="n">{fmt(v.have)}</td>
              <td className={"n" + (v.short ? " short" : "")}>{fmt(v.short)}</td></tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function PlanApp() {
  const [d, setD] = React.useState(null);
  const [err, setErr] = React.useState("");
  const [have, setHave] = React.useState({});
  React.useEffect(() => {
    const t = setTimeout(() => {
      api("GET", "/clash/api/plan?tag=" + encodeURIComponent(tagQ) + "&have=" + encodeURIComponent(JSON.stringify(have)))
        .then((j) => { setD(j); setErr(""); })
        .catch((e) => setErr(String(e.message || e)));
    }, 250);
    return () => clearTimeout(t);
  }, [have]);
  return (
    <div className="hub-shell gaming-shell" data-screen-label="clash plan">
      <Topbar crumb="clash plan" />
      <main className="gaming-body">
        <div className="gx cx cp g-clash">
        <header className="gx-page"><div><h1>Plan</h1><p>Builder queue to max, walls and resources, as an estimate</p></div></header>
        <div className="row"><a className="cx-lnk" href="/clash/">Back to tracker</a><a className="cx-lnk" href="/clash/layouts">Layouts</a></div>
        {err && <p className="err">Could not load the plan ({err})</p>}
        {d && <React.Fragment><Lanes d={d} /><Resources have={have} setHave={setHave} rows={d.resources} /><Walls walls={d.walls} /></React.Fragment>}
        </div>
      </main>
      <StatusStrip />
    </div>
  );
}
ReactDOM.createRoot(document.getElementById("root")).render(<PlanApp />);
