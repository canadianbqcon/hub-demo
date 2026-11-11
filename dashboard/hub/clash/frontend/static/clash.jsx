/* clash.jsx - /clash/ village tracker. Picked on Workbench 2026-11-10 (clash-tracker-screen):
   option D's icon wall with option B's builder timeline.
   Check 2 send-back (2026-11-10): proportional zoomable timeline colored by resource, boosts and helper panels,
   wall grouped by Town Hall tier with search, filter and sort. Row 2: boosts and helpers sit above the timeline as a
   compact strip; each Town Hall tier is split again by category. Row 3: one tile per level, default Type then Town Hall,
   Resource grouping, Type and Show as checkboxes, equal tiles with the action on the bottom. Data: /clash/api/village. */

const GROUPS = [
  ["defense", "Defenses"], ["trap", "Traps"], ["resource", "Resources"], ["army", "Army"], ["hero", "Heroes"],
  ["troop", "Troops"], ["spell", "Spells"], ["pet", "Pets"], ["crafted", "Crafted"],
  ["other", "Other"],
];
// 2026-11-10 marks: walls, the Helper Hut and the Town Hall (shown in the band instead) stay off the walls.
const HIDDEN = new Set(["hero-equipment", "guardian", "wall", "town-hall"]);
const HIDDEN_IDS = new Set([1000093, 1000064]); // Helper Hut, B.O.B's Hut
// 2026-11-10 marks: siege machines sit with troops, and lab-levelled kinds skip the Town Hall split.
const ALIAS = { "siege-machine": "troop", research: "army", "crafted-module": "crafted" };
// supercharge tiers sit above the normal max on one level line: 16 then "16 +SC1"
const lvl = (n, b) => (b && n > b ? b + " +SC" + (n - b) : n);
const FLAT = new Set(["hero", "troop", "spell", "pet"]);
const WEEK = 7 * 86400;

const icoUrl = (f) => (f ? "/clash/static/icons/" + f : null);
function Ico({ f, cls }) {
  const u = icoUrl(f);
  return u ? <img className={"cx-ico " + (cls || "")} src={u} alt="" /> : <span className={"cx-ico cx-ico-x " + (cls || "")} />;
}

function dur(s) {
  s = Math.max(0, Math.round(s));
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? d + "d " + h + "h" : h ? h + "h " + m + "m" : m + "m";
}

function toLocalInput(iso) {
  const d = new Date(iso), p = (n) => String(n).padStart(2, "0");
  return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) + "T" + p(d.getHours()) + ":" + p(d.getMinutes());
}

function Band({ v }) {
  const a = v.account, now = Date.parse(v.now);
  const left = v.structures.reduce((n, s) => (s.facility && s.level < s.max ? n + (s.max - s.level) * s.cnt : n), 0);
  const next = v.upgrades[0];
  const busy = v.upgrades.filter((u) => u.facility === "builder").length;
  const th = v.structures.find((s) => s.category === "town-hall");
  return (
    <section className="cx-band">
      <img className="cx-th" src="/clash/static/icons/i-town-hall.png" alt={"Town Hall " + a.th_level} />
      <div className="cx-id"><p className="k">Clash of Clans</p><h2>Town Hall {a.th_level}</h2>{th && <p className="cx-thn">{th.level >= th.max ? "maxed" : th.next ? "next " + num(th.next.cost) + (th.next.secs ? " · " + dur(th.next.secs) : "") : "to " + th.max}</p>}<p>{a.name || a.tag}</p></div>
      <div className="cx-n">
        <div><p>Builders</p><b>{busy} / {v.builders}</b><span>busy</span></div>
        <div><p>Next done</p><b>{next ? dur((Date.parse(next.finishes_at) - now) / 1000) : "None"}</b><span>{next ? next.name : "nothing running"}</span></div>
        <div><p>Left to max</p><b>{left}</b><span>levels</span></div>
      </div>
    </section>
  );
}

function Paste({ onDone, add }) {
  const [open, setOpen] = React.useState(false);
  const [text, setText] = React.useState("");
  const [msg, setMsg] = React.useState(null);
  const send = () => api("POST", "/clash/api/paste", { text })
    .then((r) => { setMsg({ ok: true, t: "Applied: " + r.added + " added, " + r.changed + " changed, " + r.kept_unknown + " kept unknown." }); setText(""); onDone(r.tag); })
    .catch((e) => setMsg({ ok: false, t: String(e.message) }));
  return (
    <React.Fragment>
      <button className={add ? "cx-lnk" : "cx-paste"} onClick={() => setOpen(!open)}>{open ? "Close" : add ? "+ Add village" : "Paste export"}</button>
      {open && (
        <div className="cx-box" style={{ flexBasis: "100%" }}>
          {add && <p className="cx-msg">Switch to the other village in game, then Settings, More Settings, Data Export, Copy. Paste it here; it gets its own tab.</p>}
          <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="Paste the village export JSON here" aria-label="Village export" />
          <div className="row">
            <button className="cx-start" style={{ width: "auto", padding: "6px 16px" }} disabled={!text.trim()} onClick={send}>Apply</button>
            {msg && <span className={"cx-msg" + (msg.ok ? "" : " err")}>{msg.t}</span>}
          </div>
        </div>
      )}
    </React.Fragment>
  );
}

const RES = { Gold: "g", Elixir: "e", "Dark Elixir": "de" };
const resCls = (r) => "res-" + (RES[r] || "x");
const H = 3600, D = 86400;
const SPAN_MIN = 2 * H, SPAN_MAX = 60 * D;
const STEPS = [H, 3 * H, 6 * H, 12 * H, D, 2 * D, 7 * D, 14 * D];

function num(n) {
  return n >= 1e6 ? +(n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + "M" : n >= 1e3 ? Math.round(n / 1e3) + "K" : String(n);
}

function tickLabel(t, step) {
  const d = new Date(t);
  if (step >= D) return step >= 7 * D ? d.toLocaleDateString("en-US", { month: "short", day: "numeric" }) : d.toLocaleDateString("en-US", { weekday: "short" });
  const hr = d.toLocaleTimeString("en-US", { hour: "numeric" });
  return d.getHours() < step / H ? d.toLocaleDateString("en-US", { weekday: "short" }) + " " + hr : hr;
}

// Mark 2026-11-10 #5: queued upgrades are planned bars after the lane that frees first; drag one onto another to
// take its place in the queue (the order re-flows across lanes). A bar whose lane is free turns into Start.
function Lane({ name, u, qs = [], now, span, sel, onPick, q }) {
  const left = u ? Math.max(0, (Date.parse(u.finishes_at) - now) / 1000) : 0;
  const pct = Math.min(100, (100 * left) / span); // ponytail: no minimum width, a sliver grows when zoomed in
  const at = (t) => (100 * (Date.parse(t) - now)) / 1000 / span;
  const vis = qs.filter((x) => at(x.start) < 100), later = qs.length - vis.length;
  return (
    <div className="cx-lane">
      <span className="cx-ln">{name}</span>
      <div className="cx-track">
        {u ? (
          <button className={"cx-blk " + resCls(u.resource) + (sel === u.id ? " sel" : "")} onClick={() => onPick(u)}
            style={qs.length ? { right: 100 - pct + "%" } : null /* the queue follows it, so the bar ends at its finish */}
            title={u.name + " " + lvl(u.from_level + 1, u.sc_base) + ", " + dur(left) + " left. Edit finish time or undo"}>
            <i className="cx-fill" style={{ width: qs.length ? "100%" : pct + "%" }} />
            <span className="cx-lbl"><Ico f={u.icon} cls="cx-ico-sm" /><b>{u.name} {lvl(u.from_level + 1, u.sc_base)}</b><em>{dur(left)}{pct >= 100 ? " ›" : ""}</em></span>
          </button>
        ) : !qs.length && <i className="cx-gap">free</i>}
        {vis.map((x) => {
          const ready = Date.parse(x.start) <= now, l = Math.max(0, at(x.start)), w = Math.max(4, Math.min(100 - l, (100 * x.secs) / span));
          return (
            <button key={x.id} draggable className={"cx-q " + resCls(x.resource) + (ready ? " ready" : "") + (q.sel === x.id ? " sel" : "") + (q.over === x.id ? " over" : "")}
              style={{ left: l + "%", width: w + "%" }}
              onClick={() => (ready ? q.start(x) : q.pick(x))}
              onDragStart={(e) => { e.dataTransfer.setData("text/plain", String(x.id)); e.dataTransfer.effectAllowed = "move"; }}
              onDragOver={(e) => { e.preventDefault(); q.setOver(x.id); }} onDragLeave={() => q.setOver(null)}
              onDrop={(e) => { e.preventDefault(); q.setOver(null); q.move(+e.dataTransfer.getData("text/plain"), x.id); }}
              title={x.name + " " + lvl(x.from_level + 1, x.sc_base) + (ready ? ": lane is free, tap Start once you start it in game" : ", queued, starts in " + dur((Date.parse(x.start) - now) / 1000) + ". Drag to reorder, tap for options")}>
              <span className="cx-lbl"><Ico f={x.icon} cls="cx-ico-sm" /><b>{x.name} {lvl(x.from_level + 1, x.sc_base)}</b><em>{ready ? "Start" : "queued"}</em></span>
            </button>
          );
        })}
        {later > 0 && <i className="cx-qmore">+{later} later ›</i>}
      </div>
    </div>
  );
}

function Timeline({ v, tag, reload, fail }) {
  const now = Date.parse(v.now);
  const [pick, setPick] = React.useState(null);
  const [when, setWhen] = React.useState("");
  const [span, setSpan] = React.useState(WEEK);
  const ref = React.useRef(null);
  const zoom = (f) => setSpan((s) => Math.min(SPAN_MAX, Math.max(SPAN_MIN, s * f)));
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const wheel = (e) => { e.preventDefault(); zoom(e.deltaY > 0 ? 1.2 : 1 / 1.2); };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  }, []);
  const by = (f) => v.upgrades.filter((u) => u.facility === f);
  const b = by("builder");
  const lanes = Math.max(v.builders, b.length);
  const step = STEPS.find((x) => span / x <= 8) || STEPS[STEPS.length - 1];
  const ticks = [<span key="now" style={{ left: 0 }}>now</span>], lines = [];
  const tz = new Date(now).getTimezoneOffset() * 60; // ticks sit on local midnights and hours, not UTC
  const first = Math.ceil((now / 1000 + -tz) / step) * step + tz;
  for (let t = first; t < now / 1000 + span; t += step) {
    const x = ((t - now / 1000) / span) * 100;
    lines.push(<i key={t} className="cx-vl" style={{ "--x": x / 100 }} />);
    if (x > 6) ticks.push(<span key={t} style={{ left: x + "%" }}>{tickLabel(t * 1000, step)}</span>);
  }
  const choose = (u) => { setPick(u); setWhen(toLocalInput(u.finishes_at)); };
  React.useEffect(() => { // a boost or helper moved this timer: never let Save time put the old finish back
    if (!pick) return;
    const u = v.upgrades.find((x) => x.id === pick.id);
    if (!u) setPick(null); else if (u.finishes_at !== pick.finishes_at) choose(u);
  }, [v]);
  const post = (iso) => api("POST", "/clash/api/finish", { id: pick.id, finishes_at: iso }).then(() => { setPick(null); reload(); }).catch(fail);
  const undo = () => api("POST", "/clash/api/undo", { id: pick.id }).then(() => { setPick(null); reload(); }).catch(fail);
  const setB = (n) => api("PUT", "/clash/api/builders", { tag, builders: n }).then(reload).catch(fail);
  const sel = pick ? pick.id : null;
  const queue = v.queue || [];
  const [qp, setQp] = React.useState(null);
  const [over, setOver] = React.useState(null);
  const qPick = qp && queue.find((x) => x.id === qp);
  const order = (ids) => api("PUT", "/clash/api/queue/order", { tag, ids }).then(reload).catch(fail);
  const q = {
    sel: qp, over, setOver,
    pick: (x) => { setPick(null); setQp(x.id); },
    start: (x) => api("POST", "/clash/api/start", { tag, data_id: x.data_id, from_level: x.from_level, queue_id: x.id }).then(() => { setQp(null); reload(); }).catch(fail),
    move: (from, to) => { // dragged item takes the target's slot
      if (!from || from === to) return;
      const ids = queue.map((x) => x.id).filter((i) => i !== from);
      ids.splice(ids.indexOf(to) + (queue.findIndex((x) => x.id === from) < queue.findIndex((x) => x.id === to) ? 1 : 0), 0, from);
      order(ids);
    },
  };
  const same = qPick ? queue.filter((x) => x.facility === qPick.facility) : [];
  const si = qPick ? same.indexOf(qPick) : -1;
  const nudge = (d) => { // swap with the nearest queued item of the same facility (the touch path for drag)
    const ids = queue.map((x) => x.id), i = ids.indexOf(qp), j = ids.indexOf(same[si + d].id);
    [ids[i], ids[j]] = [ids[j], ids[i]];
    order(ids);
  };
  const remove = () => api("POST", "/clash/api/queue/remove", { id: qp }).then(() => { setQp(null); reload(); }).catch(fail);
  const lq = (f, i) => queue.filter((x) => x.facility === f && x.lane === i);
  const spanTxt = span >= D ? +(span / D).toFixed(span < 3 * D ? 1 : 0) + " days" : Math.round(span / H) + " hours";
  return (
    <section className="cx-gantt" ref={ref}>
      <div className="cx-hd">
        <h3>Next {spanTxt}</h3>
        <span className="cx-step">Zoom
          <button aria-label="Zoom in" disabled={span <= SPAN_MIN} onClick={() => zoom(1 / 1.5)}>+</button>
          <button aria-label="Zoom out" disabled={span >= SPAN_MAX} onClick={() => zoom(1.5)}>-</button>
        </span>
        <span className="cx-step">Builders
          <button aria-label="Fewer builders" disabled={v.builders <= 1} onClick={() => setB(v.builders - 1)}>-</button>
          <b>{v.builders}</b>
          <button aria-label="More builders" disabled={v.builders >= 8} onClick={() => setB(v.builders + 1)}>+</button>
        </span>
      </div>
      <div className="cx-ticks">{ticks}</div>
      <div className="cx-lanes">
        {lines}
        {Array.from({ length: lanes }, (_, i) => <Lane key={i} name={"Builder " + (i + 1)} u={b[i]} qs={lq("builder", i)} now={now} span={span} sel={sel} onPick={(u) => { setQp(null); choose(u); }} q={q} />)}
        <Lane name="Lab" u={by("lab")[0]} qs={lq("lab", 0)} now={now} span={span} sel={sel} onPick={(u) => { setQp(null); choose(u); }} q={q} />
        <Lane name="Pet House" u={by("pet_house")[0]} qs={lq("pet_house", 0)} now={now} span={span} sel={sel} onPick={(u) => { setQp(null); choose(u); }} q={q} />
      </div>
      <p className="cx-legend"><span><i className="cx-r cx-r-g" />Gold</span><span><i className="cx-r cx-r-e" />Elixir</span><span><i className="cx-r cx-r-de" />Dark Elixir</span><span><i className="cx-r cx-r-q" />Queued</span><span className="cx-t">Scroll to zoom{queue.length > 1 ? ", drag queued bars to reorder" : ""}</span></p>
      {qPick && (
        <div className="cx-edit">
          <b>{qPick.name} {lvl(qPick.from_level, qPick.sc_base)} to {lvl(qPick.from_level + 1, qPick.sc_base)}</b>
          <span className="cx-t">{Date.parse(qPick.start) <= now ? "Lane is free now" : "Queued, starts in " + dur((Date.parse(qPick.start) - now) / 1000)}</span>
          {Date.parse(qPick.start) <= now && <button onClick={() => q.start(qPick)}>Start</button>}
          <button disabled={si <= 0} onClick={() => nudge(-1)}>Earlier</button>
          <button disabled={si >= same.length - 1} onClick={() => nudge(1)}>Later</button>
          <button onClick={remove}>Remove from queue</button>
          <button onClick={() => setQp(null)}>Close</button>
        </div>
      )}
      {pick && (
        <div className="cx-edit">
          <b>{pick.name} {lvl(pick.from_level, pick.sc_base)} to {lvl(pick.from_level + 1, pick.sc_base)}</b>
          <label>Done at <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} /></label>
          <button onClick={() => post(new Date(when).toISOString())} disabled={!when}>Save time</button>
          <button onClick={() => post(new Date().toISOString())} title="Used a Book or Hammer">Finish now</button>
          <button onClick={undo}>Undo upgrade</button>
          <button onClick={() => setPick(null)}>Close</button>
        </div>
      )}
    </section>
  );
}

const BOOSTS = [
  ["builder_potion", "Builder Potion", "builders 10x, 1h", "builder"],
  ["builder_bite", "Builder Bite", "builders 2x, 1h", "builder"],
  ["research_potion", "Research Potion", "lab 24x, 1h", "lab"],
  ["study_soup", "Study Soup", "lab 4x, 1h", "lab"],
  ["pet_potion", "Pet Potion", "pets 24x, 1h", "pet_house"],
];

function Boosts({ v, tag, reload, fail }) {
  const [armed, setArmed] = React.useState(null);
  const [msg, setMsg] = React.useState("");
  const now = Date.parse(v.now);
  const running = (f) => v.upgrades.filter((u) => u.facility === f && Date.parse(u.finishes_at) > now).length;
  const use = (k, label) => {
    if (armed !== k) { setArmed(k); return; }
    setArmed(null);
    api("POST", "/clash/api/boost", { tag, kind: k }).then((r) => { setMsg(label + ": " + r.moved + " timer" + (r.moved === 1 ? "" : "s") + " moved up."); reload(); }).catch(fail);
  };
  return (
    <section className="cx-slab cx-side">
      <div className="cx-hd"><h3>Boosts</h3><p className="k">Magic items and snacks</p></div>
      <ul className="cx-boosts cx-chips">
        {BOOSTS.map(([k, label, eff, f]) => {
          const n = running(f);
          return (
            <li key={k} title={eff}>
              <span><b>{label}</b> <small>{eff}</small></span>
              {/* 2026-11-10 mark "used button looks bad": a check symbol; a second tap confirms */}
              <button className={"cx-start cx-used" + (armed === k ? " armed" : "")} disabled={!n} onClick={() => use(k, label)}
                aria-label={!n ? label + ": nothing running" : armed === k ? "Confirm " + label + " used" : "Mark " + label + " used"}
                title={!n ? "Nothing running to boost" : armed === k ? "Tap again to confirm" : "Mark used"}>
                {armed === k ? "✓?" : "✓"}
              </button>
            </li>
          );
        })}
      </ul>
      <p className="cx-t cx-note">{msg || "Tap when used in game; timers move up. Books and hammers: tap the upgrade in the timeline, then Finish now."}</p>
    </section>
  );
}

const HELP_FX = { builder: (n) => "Saves " + n + "h on one builder upgrade", lab: (n) => "Saves " + n + "h on one research" };

function Helpers({ v, tag, reload, fail }) {
  const now = Date.parse(v.now);
  const [to, setTo] = React.useState({});
  const [busy, setBusy] = React.useState(false);
  const hs = v.helpers || [];
  const assign = (h, uid) => { setBusy(true); api("POST", "/clash/api/helper", { tag, data_id: h.data_id, upgrade_id: uid }).then(reload).catch(fail).finally(() => setBusy(false)); };
  return (
    <section className="cx-slab cx-side">
      <div className="cx-hd"><h3>Helper Hut</h3><p className="k">{hs.length ? "Resets once a day" : ""}</p></div>
      {!hs.length && <p className="cx-empty">Paste a new export to load your helper levels.</p>}
      <ul className="cx-boosts">
        {hs.map((h) => {
          const rest = h.ready_at && Date.parse(h.ready_at) > now ? (Date.parse(h.ready_at) - now) / 1000 : 0;
          const ups = h.facility ? v.upgrades.filter((u) => u.facility === h.facility && Date.parse(u.finishes_at) > now) : [];
          const pick = ups.some((u) => u.id === to[h.data_id]) ? to[h.data_id] : ups[0] && ups[0].id;
          return (
            <li key={h.data_id}>
              <Ico f={h.icon} cls="cx-ico-xs" />
              <span title={h.facility ? HELP_FX[h.facility](h.work_rate) : h.name === "Alchemist" ? "Converts gold, elixir and dark elixir" : "Converts ore"}>
                <b>{h.name} <em>{h.level}/{h.max}</em></b> <small className={rest ? "" : "cx-ready"}>{rest ? "ready in " + dur(rest) : "Ready"}</small></span>
              {h.facility && !rest && ups.length > 0 && (
                <span className="cx-assign">
                  <select aria-label={"Upgrade for " + h.name} value={pick} onChange={(e) => setTo({ ...to, [h.data_id]: +e.target.value })}>
                    {ups.map((u) => <option key={u.id} value={u.id}>{u.name} {lvl(u.from_level + 1, u.sc_base)}</option>)}
                  </select>
                  <button className="cx-start" disabled={busy} onClick={() => assign(h, pick)}>Assign</button>
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

// 2026-11-10 mark: just these five. Default is the game's unlock order (buildings by name); maxed items sort last.
const SORTS = [["unlock", "Default"], ["short", "Shortest"], ["long", "Longest"], ["cheap", "Cheapest"], ["pricey", "Priciest"]];
const RES_GROUPS = [["Gold", "Gold"], ["Elixir", "Elixir"], ["Dark Elixir", "Dark Elixir"], ["", "Maxed and other"]];

function Checks({ label, opts, on, set }) {
  const flip = (k) => { const n = new Set(on); n.has(k) ? n.delete(k) : n.add(k); set(n); };
  return (
    <fieldset className="cx-checks"><legend>{label}</legend>
      {opts.map(([k, l]) => (
        <label key={k} className={on.has(k) ? "on" : ""}><input type="checkbox" checked={on.has(k)} onChange={() => flip(k)} />{l}</label>
      ))}
    </fieldset>
  );
}

function Wall({ v, tag, reload, fail }) {
  const [q, setQ] = React.useState("");
  const [grp, setGrp] = React.useState("cat");
  const [cats, setCats] = React.useState(new Set()); // empty = every type
  const [sort, setSort] = React.useState("unlock"); // 2026-11-10 marks: lab, spells, heroes, pets in the order the game unlocks them
  const th = v.account.th_level;
  const runAt = new Map(); // "data_id:level" -> running upgrades from that level
  v.upgrades.forEach((u) => runAt.set(u.data_id + ":" + u.from_level, (runAt.get(u.data_id + ":" + u.from_level) || 0) + 1));
  const qAt = new Map();
  (v.queue || []).forEach((x) => qAt.set(x.data_id + ":" + x.from_level, (qAt.get(x.data_id + ":" + x.from_level) || 0) + 1));
  // mark 2026-11-10 #5: every builder (or the lab, or the pet house) busy -> the tile queues instead of starting
  const full = (f) => v.upgrades.filter((u) => u.facility === f).length >= (f === "builder" ? v.builders : 1);
  // one tile per structure per level: four archer towers at 20 and two at 21 are two tiles
  const ents = v.structures.filter((s) => !HIDDEN.has(s.category) && !HIDDEN_IDS.has(s.data_id)).map((s) => {
    const run = runAt.get(s.data_id + ":" + s.level) || 0, qd = qAt.get(s.data_id + ":" + s.level) || 0;
    const mx = s.level >= s.max;
    return { ...s, run, qd, mx, st: mx ? "max" : run ? "busy" : "open", free: !mx && s.cnt > run + qd };
  });
  const known = new Set(GROUPS.map((g) => g[0]));
  const catOf = (e) => { const c = ALIAS[e.category] || e.category; return known.has(c) ? c : "other"; };
  const tier = (e) => (e.mx || !e.next ? 99 : Math.min(3, Math.max(0, th - (e.next.th || th))));
  const tierName = (t) => (t === 99 ? "Maxed" : t === 3 ? "Town Hall " + (th - 3) + " and below" : "Town Hall " + (th - t) + (t ? "" : " (current)"));
  const resOf = (e) => (e.mx || !e.next || !RES[e.next.resource] ? "" : e.next.resource);
  const ql = q.trim().toLowerCase();
  const list = ents.filter((e) => (!ql || e.name.toLowerCase().includes(ql)) && (!cats.size || cats.has(catOf(e))));
  const key = { unlock: (e) => (e.order ?? 1e9), short: (e) => (e.next ? e.next.secs : 1e12), long: (e) => (e.next ? -e.next.secs : 1e12),
    cheap: (e) => (e.next ? e.next.cost : 1e15), pricey: (e) => (e.next ? -e.next.cost : 1e15) }[sort] || (() => 0);
  list.sort((a, b) => key(a) - key(b) || a.name.localeCompare(b.name) || a.level - b.level);
  const start = (e) => api("POST", full(e.facility) ? "/clash/api/queue" : "/clash/api/start", { tag, data_id: e.data_id, from_level: e.level }).then(reload).catch(fail);
  const by = { cat: [GROUPS.map(([k, l]) => [k, l]), catOf], th: [[0, 1, 2, 3, 99].map((t) => [t, tierName(t)]), tier], res: [RES_GROUPS, resOf], flat: [[[0, ""], [99, "Maxed"]], (e) => (e.mx ? 99 : 0)] };
  const split = (items, g) => by[g][0].map(([k, l]) => [l, items.filter((e) => by[g][1](e) === k)]).filter((x) => x[1].length);
  const inner = { cat: "th", th: "cat", res: "cat" }[grp];
  const shown = split(list, grp);
  const sel = (val, set, opts, label) => (
    <label className="cx-sel">{label}<select value={val} onChange={(e) => set(e.target.value)}>{opts.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
  );
  if (!ents.length) return <section className="cx-slab"><p className="cx-empty">No structures yet. Paste an export to fill the wall.</p></section>;
  return (
    <React.Fragment>
      <section className="cx-filters" aria-label="Filter upgrades">
        <div className="cx-frow">
          <input type="search" placeholder="Search" aria-label="Search structures" value={q} onChange={(e) => setQ(e.target.value)} />
          {sel(grp, setGrp, [["cat", "Type, then Town Hall"], ["th", "Town Hall, then type"], ["res", "Resource, then type"]], "Group")}
          {sel(sort, setSort, SORTS, "Sort")}
        </div>
        <Checks label="Type" opts={GROUPS} on={cats} set={setCats} />
      </section>
      {!shown.length && <section className="cx-slab"><p className="cx-empty">Nothing matches these filters.</p></section>}
      {shown.map(([label, items]) => (
        <section className="cx-slab" key={label}>
          <div className="cx-hd"><h3>{label}</h3><p className="k">{items.filter((e) => e.mx).length + " of " + items.length + " maxed"}</p></div>
          {split(items, grp === "cat" && FLAT.has(catOf(items[0])) ? "flat" : inner).map(([sub, its]) => {
            // 2026-11-10 mark "collapse maxed": the Maxed group starts folded; click its heading to open.
            const Box = sub === "Maxed" ? "details" : "div";
            const Head = sub === "Maxed" ? "summary" : "h4";
            return (
            <Box className="cx-sub" key={sub}>
              {sub && <Head className="cx-sh">{sub} <small>{its.length}</small></Head>}
              <div className="cx-wall">
                {its.map((e) => (
                  <div key={e.data_id + ":" + e.level} className={"cx-tile" + (e.mx ? " is-max" : "") + (e.run ? " is-busy" : "")}>
                    <span className="cx-badge" title={e.predicted ? "Predicted from a finished timer" : ""}>{e.sc_base ? Math.min(e.level, e.sc_base) + "/" + e.sc_base : e.level + "/" + e.max}</span>
                    {e.sc_base && <span className="cx-badge cx-sc" title="Supercharge tiers done / available">SC {Math.max(0, e.level - e.sc_base)}/{e.max - e.sc_base}</span>}
                    {e.cnt > 1 && <span className="cx-cnt">x{e.cnt}</span>}
                    <Ico f={e.icon} cls="cx-ico-lg" />
                    <span className="cx-tn">{e.name}</span>
                    {!e.mx && e.next && <span className="cx-ts cx-nxt"><i className={"cx-r cx-r-" + (RES[e.next.resource] || "x")} />{num(e.next.cost)}{e.next.secs ? " · " + dur(e.next.secs) : ""}</span>}
                    <span className="cx-tf">
                      {e.mx ? <span className="cx-ts">max</span>
                        : e.facility && e.free ? (full(e.facility)
                          ? <button className="cx-start cx-queue" onClick={() => start(e)} title="Every slot is busy: queue it after the timer that ends first">{e.run + e.qd ? "Queue " + (e.run + e.qd + 1) + "/" + e.cnt : "Queue"}</button>
                          : <button className="cx-start" onClick={() => start(e)}>{e.run + e.qd ? "Start " + (e.run + e.qd + 1) + "/" + e.cnt : "Start"}</button>)
                        : <span className="cx-ts">{e.qd && !e.run ? "queued" : e.run ? (e.cnt > 1 ? e.run + "/" + e.cnt + " upgrading" : "upgrading") : "to " + lvl(e.max, e.sc_base)}</span>}
                    </span>
                  </div>
                ))}
              </div>
            </Box>
            );
          })}
        </section>
      ))}
    </React.Fragment>
  );
}

function ClashApp() {
  const [tag, setTag] = React.useState(tagQ);
  const [v, setV] = React.useState(null);
  const [err, setErr] = React.useState("");
  const load = React.useCallback((t) => api("GET", "/clash/api/village?tag=" + encodeURIComponent(t === undefined ? tag : t))
    .then((j) => { setV(j); setErr(""); if (j.account && j.account.tag !== tag) setTag(j.account.tag); })
    .catch((e) => setErr(String(e.message))), [tag]);
  React.useEffect(() => { load(); const t = setInterval(load, 60000); return () => clearInterval(t); }, [load]);
  const fail = (e) => setErr(String(e.message));
  const pasted = (t) => { if (t) setTag(t); return load(t || tag); };
  return (
    <div className="hub-shell gaming-shell" data-screen-label="clash">
      <Topbar crumb="clash" />
      <main className="gaming-body">
        <div className="gx cx g-clash">
          {v && v.account && <Band v={v} />}
          <div className="cx-acct">
            <div className="cx-tabs">
              {/* 2026-11-10 mark: reorder arrows removed. 2026-11-11 Workbench pick: each village a status card with its own builders. */}
              {v && v.accounts.map((a) => (
                <button key={a.tag} className={v.account && v.account.tag === a.tag ? "sel" : ""} onClick={() => setTag(a.tag)}>
                  <img className="cx-vth" src="/clash/static/icons/i-town-hall.png" alt="" />
                  <span>{(a.name || a.tag) + " · TH" + a.th_level}</span>
                  {a.builders != null && <span className="cx-vs">
                    {a.busy < a.builders ? <b className="idle">{a.builders - a.busy} idle</b> : <b>{a.busy + "/" + a.builders + " busy"}</b>}
                    {a.next_at ? " · next " + dur((Date.parse(a.next_at) - Date.parse(v.now)) / 1000) : ""}
                  </span>}
                </button>
              ))}
            </div>
            <div className="cx-acts">{v && v.account && <Paste add onDone={pasted} />}<Paste onDone={pasted} /></div>
          </div>
          {err && <p className="cx-msg err" role="alert">{err}</p>}
          {v && v.account && <div className="cx-pair"><Boosts v={v} tag={tag} reload={() => load()} fail={fail} /><Helpers v={v} tag={tag} reload={() => load()} fail={fail} /></div>}
          {v && v.account && <Timeline v={v} tag={tag} reload={() => load()} fail={fail} />}
          {v && v.account && <Wall v={v} tag={tag} reload={() => load()} fail={fail} />}
          {v && !v.account && <section className="cx-slab"><p className="cx-empty">No village yet. Paste your export above to start tracking.</p></section>}
          {v && <p className="cx-foot">Game data {v.data_version} · finish times are estimates without boosts{v.notify_on ? "" : " · Notifications off"}</p>}
        </div>
      </main>
      <StatusStrip />
    </div>
  );
}
ReactDOM.createRoot(document.getElementById("root")).render(<ClashApp />);
