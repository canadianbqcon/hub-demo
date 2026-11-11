/* gaming.jsx - root of the gaming hub: one brand band per game (League, CS2, Clash)
   over a list of that game's Hub pages (modules and data displays).
   Picked on Workbench 2026-11-09 (gaming-page-look, option A).
   Data: /gaming/api/summary. */

const MARKS = { league: "/gaming/static/lol.svg", cs2: "/gaming/static/cs2o.svg",
  clash: "/clash/static/icons/i-town-hall.png" };

function Go({ launch, band }) {
  if (!launch) return null;
  return <a className={"gx-go" + (band ? " on-band" : "")} href={launch[1]}>{launch[0]} <b>›</b></a>;
}

function Band({ g }) {
  return (
    <section className={"gb g-" + g.id}>
      <img className={"gm gm-" + g.id} src={MARKS[g.id]} alt={g.name} />
      <div className="gb-id"><h2>{g.name}</h2><p>{g.sub}</p></div>
      <div className="gb-n">
        <div><p>Modules</p><b>{g.count}</b><span>{g.count === 1 ? "Hub page" : "Hub pages"}</span></div>
        {g.headline && <div><p>{g.headline.label}</p><b>{g.headline.value}</b><span>live</span></div>}
      </div>
      <Go launch={g.launch} band />
    </section>
  );
}

function ModuleList({ g }) {
  return (
    <section className={"gx-slab g-" + g.id}>
      <div className="gx-hd">
        <p className="k">{g.name}</p>
        <p className="k">{g.count} {g.count === 1 ? "module" : "modules"}</p>
      </div>
      <ul className="gx-l">
        {g.modules.map((m) => (
          <li key={m.url}>
            <a className="b" href={m.url}>{m.title}</a>
            {m.stat && <span className="t">{m.stat}</span>}
            <span className="d">{m.desc}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function GamingPage({ d }) {
  const total = d.games.reduce((a, g) => a + g.count, 0);
  return (
    <div className="gx">
      <header className="gx-page"><div><h1>Gaming</h1><p>{total} modules across {d.games.length} games</p></div></header>
      {d.games.map((g) => (
        <React.Fragment key={g.id}>
          <Band g={g} />
          <ModuleList g={g} />
        </React.Fragment>
      ))}
    </div>
  );
}

function GamingApp() {
  const [d, setD] = React.useState(null);
  const [err, setErr] = React.useState("");
  React.useEffect(() => {
    fetch("/gaming/api/summary")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
      .then(setD)
      .catch((e) => setErr(String(e.message || e)));
  }, []);
  return (
    <div className="hub-shell gaming-shell" data-screen-label="gaming">
      <Topbar crumb="gaming" />
      <main className="gaming-body">
        {d ? <GamingPage d={d} /> : err
          ? <div className="gx"><p className="gx-err">Could not load gaming data ({err})</p></div>
          : null}
      </main>
      <StatusStrip />
    </div>
  );
}
ReactDOM.createRoot(document.getElementById("root")).render(<GamingApp />);
