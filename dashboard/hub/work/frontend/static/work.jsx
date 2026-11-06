/* work.jsx — root of the work portal. Job tiles grouped by employer. */

// One tile per board. J&Co's three surfaces (batch prep, bar back, the map)
// merged into a single tabbed page, so it is one board now, not two tiles that
// happened to link at each other.
const BOARDS = [
  { job: "Juniper & Co", tiles: [
    { name: "Juniper & Co", desc: "Bar back, batch prep, the map", href: "/jc/" },
  ]},
];

function WorkBoards() {
  return (
    <main className="work-body">
      {BOARDS.map((g) => (
        <section className="work-job" key={g.job}>
          <div className="work-job-head">
            <h2 className="work-job-title">{g.job}</h2>
            <span className="work-job-meta">{g.tiles.length} board{g.tiles.length === 1 ? "" : "s"}</span>
          </div>
          <div className="work-grid">
            {g.tiles.map((t) => (
              <a className="launch-tile" key={t.name} href={t.href}>
                <span className="tile-name">{t.name}</span>
                <span className="tile-desc">{t.desc}</span>
                <span className="tile-meta">{`→ ${t.href.replace(/\/$/, "")}`}</span>
              </a>
            ))}
          </div>
        </section>
      ))}
    </main>
  );
}

function WorkApp() {
  return (
    <div className="hub-shell work-shell" data-screen-label="work">
      <Topbar crumb="work" />
      <WorkBoards />
      <StatusStrip />
    </div>
  );
}
ReactDOM.createRoot(document.getElementById("root")).render(<WorkApp />);
