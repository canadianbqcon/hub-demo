/* patch.jsx - Clash patch page: Patch (balance notes as an article), Blog (every post), Leaks (r/ClashOfClansLeaks).
   Data: GET /clash/api/patch; POST /clash/api/patch/refresh. Every source string is set as text, never HTML.
   Ported from the approved Workbench preview (option A plus option B's glance board). */

const PX_HOSTS = ["supercell.com", "www.reddit.com", "i.redd.it", "clashofclans.inbox.supercell.com"];
const pxSafe = (u) => { try { const x = new URL(u); return x.protocol === "https:" && PX_HOSTS.includes(x.host) ? u : null; } catch (e) { return null; } };
const PX_EFF = { buff: "Buff", nerf: "Nerf", neutral: "Adjusted" };
const PX_SECTIONS = ["Heroes", "Troops", "Equipment", "Defenses", "Fixes"];
const PX_KIND = { balance: "Balance", update: "Update" };

function pxDay(iso) {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? iso + "T12:00:00" : iso);
  return isNaN(d) ? "" : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}
function pxAgo(iso) {
  const s = (new Date() - new Date(iso)) / 1000;
  return wpAge(isNaN(s) ? null : s);
}

// the server's majority rule (patch._group), so the tag and the "Buff." lead-in never disagree
const pxEffOf = (e) => ({ Buff: "buff", Nerf: "nerf" })[e.group] || "neutral";
function pxCounts(es) {
  const k = { buff: 0, nerf: 0, neutral: 0 };
  es.forEach((e) => { k[pxEffOf(e)]++; });
  return k;
}
const pxSum = (k) => [k.buff && k.buff + " buffed", k.nerf && k.nerf + " nerfed", k.neutral && k.neutral + " adjusted"].filter(Boolean).join(", ");
const pxEid = (p, e, i) => "u-" + p.slug.slice(0, 12) + "-" + i;

/* "goes from 20 to 18" -> "20 => 18" with the new value bold; the rest of the sentence is the post's own words. */
function PxVals({ text }) {
  const re = /(?:go(?:es|ing) )?from (\d[\d.,]*[\d%]|\d) to (\d[\d.,]*[\d%]|\d)/g;
  const out = [];
  let last = 0, m, i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push(<span className="pn-v" key={i++}><s>{m[1]}</s> {"⇒"} <b>{m[2]}</b></span>);
    last = m.index + m[0].length;
  }
  out.push(text.slice(last));
  return <>{out}</>;
}

function PxLink({ href, children }) {
  return pxSafe(href) ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> : <>{children}</>;
}

function PxIcon({ icon, unit, cls }) {
  const [bad, setBad] = React.useState(false);
  if (icon && !bad) return <img className={cls || "pn-ic"} src={"/clash/static/icons/" + icon} alt="" onError={() => setBad(true)} />;
  return <span className={(cls || "pn-ic") + " pn-ic-ph"} aria-hidden="true">{(unit || "?").charAt(0).toUpperCase()}</span>;
}

function PxTag({ e }) { return <span className={"px-tag px-" + e}>{PX_EFF[e]}</span>; }
const GLYPH = { buff: "▲", nerf: "▼", neutral: "●" };

function PxBanner({ p }) {
  const [bad, setBad] = React.useState(false);
  const src = pxSafe(p.banner_url);
  return (
    <header className="pn-ban pn-ban-s">
      {src && !bad && <img src={src} alt="" referrerPolicy="no-referrer" onError={() => setBad(true)} />}
      <div>
        <p className="pn-kick">{(PX_KIND[p.kind] || "Blog") + (p.kind === "balance" ? " update" : "") + ", " + pxDay(p.date)}</p>
        <h2>{p.title}</h2>
        {p.entries.length > 0 && <p className="pn-sum">{pxSum(pxCounts(p.entries))}</p>}
      </div>
    </header>
  );
}

function PxGlance({ p, jump }) {
  const cols = [["buff", "Buffs"], ["nerf", "Nerfs"], ["neutral", "Adjusted"]]
    .map(([f, h]) => [f, h, p.entries.map((e, i) => [e, i]).filter(([e]) => pxEffOf(e) === f)]).filter(([, , l]) => l.length);
  if (!cols.length) return null;
  return (
    <div className="pb2-glance">
      <p className="pn-kick">Patch at a glance</p>
      <div className="pb2-cols">
        {cols.map(([f, h, l]) => (
          <div className={"pb2-col pb2-" + f} key={f}>
            <h3><span className={"px-gl px-" + f} aria-label={PX_EFF[f]}>{GLYPH[f]}</span> {h}</h3>
            <div className="pb2-ics">
              {l.map(([e, i]) => (
                <button className="pb2-ic" key={i} onClick={() => jump(pxEid(p, e, i))}>
                  <PxIcon icon={e.icon} unit={e.unit} /><span>{e.unit}</span>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function PxEntry({ p, e, i }) {
  return (
    <article className="pn-entry" id={pxEid(p, e, i)}>
      <PxIcon icon={e.icon} unit={e.unit} />
      <div className="pn-body">
        <div className="pn-eh">
          <h3 className="pn-name">{e.unit}{e.of && <small>{e.of}</small>}</h3>
          <PxTag e={pxEffOf(e)} />
        </div>
        {e.why && <blockquote className="pn-why">{e.group && <b>{e.group}. </b>}{e.why}</blockquote>}
        <ul className="pn-ch">{e.changes.map((c, j) => <li className={"pn-" + c.effect} key={j}><PxVals text={c.text} /></li>)}</ul>
      </div>
    </article>
  );
}

function PxWatching({ w }) {
  if (!w) return null;
  return (
    <section className="pn-watch">
      <h2 className="pn-sec"><span>Watching, not changed</span></h2>
      <div className="pn-wic">
        {(w.names || []).map((n, i) => <span key={i}><PxIcon icon={(w.icons || [])[i]} unit={n} cls="pn-ic pn-ic-s" /><em>{n}</em></span>)}
      </div>
      {w.text && <p>{w.text}</p>}
    </section>
  );
}

function PxArticle({ p, jump }) {
  const idx = p.entries.map((e, i) => [e, i]);
  const sections = PX_SECTIONS.map((s) => [s, idx.filter(([e]) => e.section === s)]).filter(([, l]) => l.length);
  return (
    <section className="gx-slab g-clash pn-art">
      <PxBanner p={p} />
      <PxGlance p={p} jump={jump} />
      <div className="pn-intro">
        {p.intro.map((t, i) => <p key={i}>{t}</p>)}
        {p.entries.length === 0 && <p>No balance changes in this post.</p>}
        <p className="pn-src"><PxLink href={p.url}>Read the post on Supercell {"↗"}</PxLink></p>
      </div>
      {sections.map(([s, l]) => (
        <React.Fragment key={s}>
          <h2 className="pn-sec"><span>{s}</span><small>{pxSum(pxCounts(l.map(([e]) => e)))}</small></h2>
          {l.map(([e, i]) => <PxEntry key={i} p={p} e={e} i={i} />)}
        </React.Fragment>
      ))}
      <PxWatching w={p.watching} />
    </section>
  );
}

function PxPatchTab({ d, cur, setCur, jump }) {
  if (!d.posts.length) return <p className="wp-note">No sorted posts yet. Press Refresh.</p>;
  const p = d.posts.find((x) => x.slug === cur) || d.posts[0];
  return (
    <>
      <div className="pn-pick" role="group" aria-label="Patch">
        {d.posts.map((x) => (
          <button className="pn-pk" key={x.slug} aria-pressed={x.slug === p.slug} onClick={() => setCur(x.slug)}>
            <b>{x.title}</b><small>{pxDay(x.date)}</small>
          </button>
        ))}
      </div>
      <PxArticle key={p.slug} p={p} jump={jump} />
    </>
  );
}

function PxBlogTab({ d }) {
  return (
    <section className="gx-slab g-clash">
      <div className="gx-hd"><p className="k">Every Clash blog post</p><p className="k">{d.blog.length < d.blog_total ? "newest " + d.blog.length + " of " + d.blog_total : d.blog_total + " so far"}</p></div>
      {d.blog.length === 0 ? <p className="wp-note">No posts yet. Press Refresh.</p> : (
        <ul className="px-blog">
          {d.blog.map((b) => (
            <li key={b.slug}>
              <PxLink href={b.url}>{b.title}</PxLink>
              <span className="px-d">{pxDay(b.date)}</span>
              {b.kind ? <span className="px-kind">{PX_KIND[b.kind] || "Other"}</span>
                : <span className="px-kind px-none">{b.classify_state === "failed" ? "could not sort" : "not sorted"}</span>}
            </li>
          ))}
        </ul>
      )}
      {!d.backfill_done && <p className="px-notice">Older posts still loading.</p>}
    </section>
  );
}

function PxLeakCard({ l }) {
  const [bad, setBad] = React.useState(false);
  const src = pxSafe(l.image_url);
  return (
    <article className="gx-slab g-clash la-card">
      {src && !bad && <img className="px-img" loading="lazy" referrerPolicy="no-referrer" src={src} alt="" onError={() => setBad(true)} />}
      <h3><PxLink href={l.url}>{l.title}</PxLink></h3>
      <p className="px-meta">
        {l.credit ? <span className="px-credit">{l.credit}</span> : <span className="px-credit px-none">no credit</span>}
        <span>u/{l.author}</span><span>{l.score} pts, {l.comments} comments at fetch</span><span>{pxAgo(l.posted_at)}</span>
      </p>
    </article>
  );
}

function PxLeaksTab({ d }) {
  if (!d.leaks.length) return <p className="wp-note">No leaks yet. Press Refresh.</p>;
  return <div className="la-grid">{d.leaks.map((l) => <PxLeakCard key={l.id} l={l} />)}</div>;
}

const PX_TABS = [["patch", "Patch"], ["blog", "Blog"], ["leaks", "Leaks"]];
const pxHashTab = () => { const t = location.hash.slice(1).split("/")[0]; return PX_TABS.some(([k]) => k === t) ? t : "patch"; };

function PatchApp() {
  const [d, setD] = React.useState(null);
  const [err, setErr] = React.useState("");
  const [tab, setTab] = React.useState(pxHashTab());
  const [cur, setCur] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [msg, setMsg] = React.useState("");
  const load = React.useCallback(() => api("GET", "/clash/api/patch").then((j) => { setD(j); setErr(""); }).catch((e) => setErr(String(e.message || e))), []);
  React.useEffect(() => { load(); }, [load]);
  React.useEffect(() => {
    const on = () => setTab(pxHashTab());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const refresh = () => {
    setBusy(true); setMsg("");
    api("POST", "/clash/api/patch/refresh")
      .then((j) => {  // each step reports its own error inside a 200
        const errs = Object.entries(j).filter(([, v]) => v && v.error).map(([k, v]) => k + ": " + v.error);
        if (errs.length) setMsg("Refresh finished with errors (" + errs.join("; ") + ")");
        return load();
      })
      .catch((e) => setMsg("Refresh failed: " + String(e.message || e)))
      .finally(() => setBusy(false));
  };
  const jump = (id) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.scrollIntoView({ block: "start", behavior: "smooth" });
    el.classList.add("pn-hit");
    setTimeout(() => el.classList.remove("pn-hit"), 1200);
  };
  const counts = d ? { patch: d.posts.length + " patches", blog: d.blog_total + " posts", leaks: d.leaks.length + " leaks" } : {};
  const f = d && d.fetch[tab === "patch" ? "classify" : tab];
  return (
    <div className="hub-shell gaming-shell" data-screen-label="clash patch">
      <Topbar crumb="clash patch" />
      <main className="gaming-body">
        <div className="gx g-clash px">
          <header className="gx-page"><div><h1>Patch</h1><p>Supercell's balance changes, every blog post, and what is leaking for the next update</p></div></header>
          {err && <p className="gx-err">Could not load ({err})</p>}
          {d && (
            <>
              <div className="px-tabs px-tabs-a pn-tabs" role="tablist">
                {PX_TABS.map(([k, l]) => (
                  <button role="tab" className="px-tab" key={k} aria-selected={k === tab} onClick={() => { location.hash = k; setTab(k); }}>
                    {l}<small>{counts[k]}</small>
                  </button>
                ))}
              </div>
              <div className="px-bar">
                <button className="wp-btn" disabled={busy} onClick={refresh}>{busy ? "Refreshing, this can take a minute" : "Refresh"}</button>
                <p className="px-upd">Updated {f && f.age_secs != null ? wpAge(f.age_secs) : "never"}{f && f.last_error ? ". Last error: " + f.last_error : ""}</p>
                {msg && <p className="px-upd" role="status">{msg}</p>}
              </div>
              <div className="px-panel" role="tabpanel">
                {tab === "patch" && <PxPatchTab d={d} cur={cur} setCur={setCur} jump={jump} />}
                {tab === "blog" && <PxBlogTab d={d} />}
                {tab === "leaks" && <PxLeaksTab d={d} />}
              </div>
              {tab === "patch" && (
                <p className="px-notice">
                  {d.unsorted} blog posts not sorted yet (the newest show on the Blog tab){d.failed > 0 ? ", " + d.failed + " could not be sorted" : ""}.
                  {!d.backfill_done ? " Older posts still loading." : ""}
                </p>
              )}
            </>
          )}
        </div>
      </main>
      <StatusStrip />
    </div>
  );
}
ReactDOM.createRoot(document.getElementById("root")).render(<PatchApp />);
