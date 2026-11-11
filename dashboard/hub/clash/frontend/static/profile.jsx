/* profile.jsx - Clash player profile: heroes, troops, spells and equipment as level over the
   Town Hall max. Data: /clash/api/profile (last good official-API answer). */

const WP_SECTIONS = [["heroes", "Heroes"], ["troops", "Troops, siege and pets"], ["spells", "Spells"], ["equipment", "Hero equipment"]];

function ItemGrid({ rows }) {
  return (
    <div className="wp-grid">
      {rows.map((it) => (
        <div key={it.name} className={"wp-item" + (it.level >= it.max ? " maxed" : "")}>
          {it.icon ? <img src={"/clash/static/icons/" + it.icon} alt="" /> : <span className="ph" />}
          <span className="n" title={it.name}>{it.name}</span>
          <span className="l">{it.level} / {it.max}</span>
        </div>
      ))}
    </div>
  );
}

function ProfileBody({ d }) {
  if (!d.account) return <p className="wp-note">No account yet. Paste an export on the village page first.</p>;
  if (!d.player) return <p className="wp-note">{d.error ? "No data yet (" + d.error + ")." : "No data yet."} Press Refresh.</p>;
  const p = d.player;
  return (
    <>
      <section className="gx-slab g-clash">
        <div className="gx-hd"><p className="k">{p.name} {p.tag}</p><p className="k">{p.clan ? p.clan.name : "No clan"}</p></div>
        <div className="wp-facts">
          <p><span className="k">Town Hall</span><b>{p.townHallLevel}</b></p>
          <p><span className="k">Trophies</span><b>{p.trophies}</b></p>
          <p><span className="k">Best</span><b>{p.bestTrophies}</b></p>
          <p><span className="k">War stars</span><b>{p.warStars}</b></p>
          <p><span className="k">Donations</span><b>{p.donations}</b></p>
        </div>
      </section>
      {WP_SECTIONS.map(([k, label]) => d.items[k].length > 0 && (
        <section key={k} className="gx-slab g-clash">
          <div className="gx-hd"><p className="k">{label}</p><p className="k">level / Town Hall {p.townHallLevel} max</p></div>
          <ItemGrid rows={d.items[k]} />
        </section>
      ))}
    </>
  );
}

function ProfileApp() {
  const w = useWp("/clash/api/profile");
  return <WpPage crumb="clash profile" title="Profile" sub="Heroes, troops, spells and equipment against your Town Hall max" w={w}>
    <ProfileBody d={w.d} />
  </WpPage>;
}
ReactDOM.createRoot(document.getElementById("root")).render(<ProfileApp />);
