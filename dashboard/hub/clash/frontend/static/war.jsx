/* war.jsx - Clash war page: current war with the who-hits-whom plan, CWL rounds, war log.
   Data: /clash/api/war; plan saves via PUT /clash/api/war-plan (one target per member per war). */

function WarTable({ v, reload }) {
  const pick = (m, tag) => {
    const t = v.targets.find((x) => x.tag === tag);
    api("PUT", "/clash/api/war-plan", { war_key: v.key, attacker_tag: m.tag, target_tag: tag || null, target_pos: t ? t.pos : null })
      .then(reload, (e) => alert("Plan not saved: " + e.message));
  };
  return (
    <>
      <div className="wp-score">
        <span>{v.us.name}</span><b>{v.us.stars ?? 0}</b><span>stars vs</span><span>{v.them.name}</span><b>{v.them.stars ?? 0}</b>
        <span>{v.state}</span>
      </div>
      <div className="wp-scroll">
        <table className="wp-tbl">
          <thead><tr><th>#</th><th>Member</th><th className="num">TH</th><th className="num">Stars</th><th className="num">Attacks left</th><th>Plan: hits</th></tr></thead>
          <tbody>
            {v.members.map((m) => (
              <tr key={m.tag}>
                <td>{m.pos}</td><td>{m.name}</td><td className="num">{m.th}</td><td className="num">{m.stars}</td><td className="num">{m.attacks_left}</td>
                <td>
                  <select className="wp-pick" aria-label={"Target for " + m.name} value={m.plan && !m.plan.gone ? m.plan.target_tag : ""}
                    onChange={(e) => pick(m, e.target.value)}>
                    <option value="">No target</option>
                    {v.targets.map((t) => <option key={t.tag} value={t.tag}>#{t.pos} {t.name} (TH {t.th})</option>)}
                  </select>
                  {m.plan && m.plan.gone && <span className="wp-gone"> Target is no longer in the enemy roster</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

const WP_NOTE = {
  not_in_war: "Not in war.", no_clan: "This account is not in a clan.", no_data: "No data yet. Press Refresh.",
  error: "The last fetch failed and there is no earlier answer. Press Refresh.",
};

function WarBody({ d, reload }) {
  if (!d.account) return <p className="wp-note">No account yet. Paste an export on the village page first.</p>;
  return (
    <>
      <section className="gx-slab g-clash">
        <div className="gx-hd"><p className="k">Current war</p><p className="k">{d.current ? d.current.state : ""}</p></div>
        {d.current ? <WarTable v={d.current} reload={reload} /> : <p className="wp-note">{WP_NOTE[d.status]}</p>}
      </section>
      {d.cwl.length > 0 && (
        <section className="gx-slab g-clash">
          <div className="gx-hd"><p className="k">Clan War League</p><p className="k">{d.cwl.length} rounds</p></div>
          {d.cwl.map((r) => (
            <div key={r.war_tag}>
              <div className="wp-score"><span>Round {r.round}</span></div>
              <WarTable v={r} reload={reload} />
            </div>
          ))}
        </section>
      )}
      <section className="gx-slab g-clash">
        <div className="gx-hd"><p className="k">War log</p><p className="k">last {d.log.length}</p></div>
        {d.log.length > 0 ? (
          <div className="wp-scroll">
            <table className="wp-tbl">
              <thead><tr><th>Result</th><th>Opponent</th><th className="num">Size</th><th className="num">Stars</th><th>Ended</th></tr></thead>
              <tbody>
                {d.log.map((w, i) => (
                  <tr key={i}><td>{w.result || "Draw"}</td><td>{w.opponent}</td><td className="num">{w.size}</td>
                    <td className="num">{w.us} to {w.them}</td><td>{(w.end || "").slice(0, 8).replace(/(\d{4})(\d\d)(\d\d)/, "$1-$2-$3")}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="wp-note">{d.log_status === "private" ? "War log private." : d.log_status === "error" ? "War log failed to load." : "No war log yet."}</p>}
      </section>
    </>
  );
}

function WarApp() {
  const w = useWp("/clash/api/war");
  return <WpPage crumb="clash war" title="War" sub="Current war, league rounds, war log and who hits whom" w={w}>
    <WarBody d={w.d} reload={w.load} />
  </WpPage>;
}
ReactDOM.createRoot(document.getElementById("root")).render(<WarApp />);
