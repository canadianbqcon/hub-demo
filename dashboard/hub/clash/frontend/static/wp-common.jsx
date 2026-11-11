/* wp-common.jsx - loaded first on every Clash page: api() and the ?tag= value; then the pieces
   the profile and war pages share: account picker, Refresh button with the data's age, key and IP banner. */

const tagQ = new URLSearchParams(location.search).get("tag") || "";

/* JSON in and out (FormData goes as is); a non-2xx answer rejects with the server's error text. */
function api(method, url, body) {
  const form = body instanceof FormData;
  return fetch(url, { method, headers: body && !form ? { "Content-Type": "application/json" } : undefined,
    body: form ? body : body ? JSON.stringify(body) : undefined })
    .then((r) => r.json().catch(() => ({})).then((j) => (r.ok ? j : Promise.reject(new Error(j.error || j.reason || "HTTP " + r.status)))));
}

function wpAge(secs) {
  if (secs == null) return "never";
  if (secs < 90) return "just now";
  if (secs < 5400) return Math.round(secs / 60) + " min ago";
  if (secs < 129600) return Math.round(secs / 3600) + " h ago";
  return Math.round(secs / 86400) + " d ago";
}

function WpBanner({ b }) {
  if (!b) return null;
  if (b.kind === "no_key") return (
    <div className="wp-banner" role="alert"><b>Add an API key.</b> Create a key at developer.clashofclans.com, then add the line
      {" "}<code>COC_API_KEY=your-key</code> to <code>~/.config/vault-api/.env</code> and press Refresh.</div>);
  if (b.kind === "invalid_ip") return (
    <div className="wp-banner" role="alert"><b>The key rejects this PC's address{b.ip ? " (" + b.ip + ")" : ""}.</b> Open the key at
      {" "}developer.clashofclans.com and add {b.ip ? <code>{b.ip}</code> : "the PC's current public IP"} to its allowed IP addresses, then press Refresh.</div>);
  return <div className="wp-banner" role="alert"><b>The API refused the key.</b> Check that the key is current and not revoked, then press Refresh.</div>;
}

function WpBar({ d, tag, setTag, onRefresh, busy }) {
  return (
    <div className="wp-bar">
      {d.accounts.length > 1 && (
        <select aria-label="Account" value={d.account ? d.account.tag : ""} onChange={(e) => setTag(e.target.value)}>
          {d.accounts.map((a) => <option key={a.tag} value={a.tag}>{a.name || a.tag}</option>)}
        </select>)}
      <button className="wp-btn" disabled={busy || !d.account} onClick={onRefresh}>{busy ? "Refreshing" : "Refresh"}</button>
      <span className="wp-age">Data from {d.ok_at ? wpAge(d.age_secs) : "never"}</span>
    </div>
  );
}

/* Loads url (with ?tag=), exposes refresh(); the refresh answer's banner (it carries the live IP) wins over the stored one. */
function useWp(url) {
  const [tag, setTag] = React.useState(tagQ);
  const [d, setD] = React.useState(null);
  const [err, setErr] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [live, setLive] = React.useState(null);
  const load = React.useCallback(() => api("GET", url + "?tag=" + encodeURIComponent(tag))
    .then((j) => { setD(j); setErr(""); })
    .catch((e) => setErr(String(e.message || e))), [url, tag]);
  React.useEffect(() => { load(); }, [load]);
  const refresh = () => {
    if (!d || !d.account) return;
    setBusy(true);
    fetch("/clash/api/refresh?tag=" + encodeURIComponent(d.account.tag), { method: "POST" })
      .then((r) => r.json()).then((j) => { setLive(j.banner || null); return load(); })
      .catch((e) => setErr(String(e.message || e))).finally(() => setBusy(false));
  };
  return { d, err, tag, setTag, busy, refresh, load, banner: live || (d && d.banner) };
}

function WpPage({ crumb, title, sub, w, children }) {
  return (
    <div className="hub-shell gaming-shell" data-screen-label={crumb}>
      <Topbar crumb={crumb} />
      <main className="gaming-body">
        <div className="gx g-clash">
          <header className="gx-page"><div><h1>{title}</h1><p>{sub}</p></div></header>
          {w.err && <p className="gx-err">Could not load ({w.err})</p>}
          {w.d && <WpBar d={w.d} tag={w.tag} setTag={w.setTag} onRefresh={w.refresh} busy={w.busy} />}
          {w.d && <WpBanner b={w.banner} />}
          {w.d && children}
        </div>
      </main>
      <StatusStrip />
    </div>
  );
}
