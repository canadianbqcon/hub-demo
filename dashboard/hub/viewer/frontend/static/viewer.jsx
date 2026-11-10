/* viewer.jsx: the Viewer page (/viewer/), contact sheet with kind filters.

   Renders the page body only: the kind rail, the thumbnail grid and the open
   item. The top bar is topbar.jsx's; this page sets the crumb section and the
   footer status by id. The feed is polled from /viewer/api/feed.

   Also here: the full-screen zoom overlay (fit / 100%, drag pan, version flip
   that keeps the focal point), video, web frame, upload (picker and page drop)
   and live arrival of new items. */

(() => {
const { useState, useEffect, useRef, useMemo } = React;

const $ = (id) => document.getElementById(id);
const PHONE = "(max-width: 900px)";  // where the tabbed-3-pane origin stacks into a document

const GLYPH = {
  everything: <path d="M4 6h16v12H4z M4 15l4-4 4 4 3-3 5 5"/>,
  photo: <React.Fragment><path d="M4 6h16v12H4z M4 15l4-4 4 4 3-3 5 5"/><circle cx="15.5" cy="9.5" r="1.3"/></React.Fragment>,
  web: <path d="M12 4a8 8 0 1 0 0 16a8 8 0 1 0 0-16z M4 12h16 M12 4c2.5 2.5 2.5 13.5 0 16 M12 4c-2.5 2.5-2.5 13.5 0 16"/>,
  video: <path d="M4 6h12v12H4z M16 10l4-2v8l-4-2"/>,
  file: <path d="M7 3h7l4 4v14H7z M14 3v4h4"/>,
  upload: <path d="M12 16V5 M7.5 9.5 12 5l4.5 4.5 M5 19h14"/>,
  paste: <path d="M9 4h6v3H9z M9 5.5H6v14.5h12V5.5h-3"/>,
  full: <path d="M4 9V4h5 M20 9V4h-5 M4 15v5h5 M20 15v5h-5"/>,
  down: <path d="M12 4v11 M7.5 10.5 12 15l4.5-4.5 M5 19h14"/>,
  close: <path d="M6 6l12 12 M18 6L6 18"/>,
};

// rail order and labels; "everything" is every kind
const KINDS = [
  { key: "everything", name: "Everything" },
  { key: "photo", name: "Photos" },
  { key: "video", name: "Video" },
  { key: "web", name: "Web pages" },
  { key: "file", name: "Files" },
  { key: "upload", name: "From you" },
];

function Glyph({ k, cls = "vw-g" }) {
  return <svg className={cls} viewBox="0 0 24 24" aria-hidden="true">{GLYPH[k]}</svg>;
}

// ── formatting ──────────────────────────────────────────────────────────────

const parse = (iso) => { const t = Date.parse(iso); return Number.isNaN(t) ? null : t; };

function age(iso, now) {
  const t = parse(iso);
  if (t === null) return "";
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min`;
  if (s < 86400) return `${Math.floor(s / 3600)} h`;
  const d = new Date(now), y = new Date(t);
  const days = Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()) -
    new Date(y.getFullYear(), y.getMonth(), y.getDate())) / 86400000);
  return days === 1 ? "Yesterday" : `${days} d`;
}
const ago = (iso, now) => { const a = age(iso, now); return a === "just now" ? a : `${a} ago`; };

const when = (iso) => {
  const t = parse(iso);
  return t === null ? "" : new Date(t).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
};

// folder part of a C:\ (or posix) path
const dir = (p) => p.replace(/[\\/][^\\/]*$/, "") || p;

function size(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${Math.round(n / 1024)} KB`;
  return n < 1073741824 ? `${(n / 1048576).toFixed(1)} MB` : `${(n / 1073741824).toFixed(1)} GB`;
}

const previewText = (it) => {
  const p = it.preview_status || "none";
  return p === "ready" ? "preview ready" : p === "making" ? "making preview" : p.startsWith("failed") ? "preview failed" : "";
};

// ── item helpers ────────────────────────────────────────────────────────────

const thumbOf = (it) => { const f = it.files.find((x) => x.thumb_url); return f ? f.thumb_url : null; };
// a RAW shows its preview; any other image shows itself
const shownSrc = (f) => f.preview_url || (/\.(arw|cr2|cr3|nef|dng|raf|orf|rw2)$/i.test(f.name) ? null : f.url);

// the Hub under any of its local names counts. Another alias (tailnet name, LAN IP)
// is framed and gets app.py's 403, whose text says the same thing as this placeholder.
const sameHub = (url) => {
  try {
    const u = new URL(url, location.href);
    return u.origin === location.origin || (u.protocol === location.protocol && u.port === location.port
      && ["localhost", "127.0.0.1", "[::1]"].includes(u.hostname));
  } catch (_) { return false; }
};

// ── the open item ───────────────────────────────────────────────────────────

// the files a viewer can show: a video item's videos, else every photo and video file
const mediaOf = (it) => it.files.filter((f) => (it.kind === "video" ? f.kind === "video" : f.kind === "photo" || f.kind === "video"));
const isVersions = (m) => m.length >= 2 && m.every((f) => f.kind === "photo");

function Versions({ media, ver, setVer }) {
  return <div className="hub-tabs hub-tabs--segmented vw-seg" role="tablist" aria-label="Versions">
    {media.map((f, i) => <button key={f.name} type="button" role="tab" className={`hub-tab${i === ver ? " active" : ""}`}
      aria-selected={i === ver} onClick={() => setVer(i)}>{f.label}</button>)}
  </div>;
}

// a video that offers the download when the browser cannot decode it
function VideoView({ f }) {
  const [bad, setBad] = useState(false);
  useEffect(() => setBad(false), [f.url]);
  return <div className="vw-vid">
    <video key={f.url} className="vw-video" src={f.url} controls preload="metadata" onError={() => setBad(true)} />
    {bad ? <div className="vw-ph"><span>This video can't play in the browser.</span>
      <a className="hub-btn vw-lnk" href={f.url} download>Download {f.orig}</a></div> : null}
  </div>;
}

// Stage: the item's picture area. `ver` indexes the item's media files.
function Stage({ item, ver = 0, onDims, onPick }) {
  const media = mediaOf(item);
  const f = media[Math.min(ver, media.length - 1)];
  const src = f && f.kind === "photo" ? shownSrc(f) : null;
  const listed = item.kind === "file" || item.kind === "upload";
  let body;
  if (item.kind === "web") {
    const link = <a className="hub-btn vw-lnk" href={item.url} target="_blank" rel="noopener noreferrer">Open in new tab</a>;
    body = <React.Fragment>
      <div className="vw-webbar"><span className="vw-dim">{item.url}</span>{link}</div>
      {sameHub(item.url)
        // a Hub page framed here would be same-origin with this tab and, with scripts,
        // could lift its sandbox; without allow-same-origin its own API calls fail
        ? <div className="vw-ph"><Glyph k="web" cls="vw-g vw-g--big" /><span>Hub pages open in their own tab.</span></div>
        : item.framable === false
        ? <div className="vw-ph"><Glyph k="web" cls="vw-g vw-g--big" /><span>This site does not allow being shown inside another page.</span></div>
        // no allow-top-navigation: a framed site cannot redirect the Hub tab; no allow-modals:
        // a looping alert() would lock it. A foreign page that redirects or navigates to the
        // Hub is refused by app.py's _refuse_cross_site_framing. key: a new frame per URL.
        // no-referrer is load-bearing: sw.js skips its kept copy only for frames without a
        // Hub referrer, and a foreign redirect to the Hub carries this frame's referrer.
        : <iframe key={item.url} className="vw-frame"
            sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox allow-downloads"
            src={item.url} referrerPolicy="no-referrer" title={item.title} />}
    </React.Fragment>;
  } else if (f && f.kind === "video") {
    body = <VideoView f={f} />;
  } else if (f && src) {
    body = <img className="vw-img" key={src} src={src} alt={item.title}
                onLoad={(e) => onDims && onDims({ src, v: `${e.target.naturalWidth} × ${e.target.naturalHeight}` })} />;
  } else if (f) {
    const st = item.preview_status || "";
    body = <div className="vw-ph"><Glyph k="photo" cls="vw-g vw-g--big" />
      <span>{st.startsWith("failed") ? "preview failed" : "making preview"}</span>
      {st.startsWith("failed") ? <a className="hub-btn vw-lnk" href={f.url} download>Download {f.orig}</a> : null}</div>;
  } else if (!listed) {
    body = <div className="vw-ph"><Glyph k={item.kind} cls="vw-g vw-g--big" /><span>{item.files.length === 1 ? item.files[0].orig : `${item.files.length} files`}</span></div>;
  }
  return <div className={`vw-stage${item.kind === "web" ? " vw-stage--web" : ""}`}>
    {body}
    {listed ? <div className="vw-files">{item.files.map((x) => {
      const mi = media.indexOf(x);
      return <div key={x.name} className={`vw-frow${mi >= 0 && mi === ver ? " active" : ""}`}>
        {mi >= 0 ? <button type="button" className="hub-btn vw-lnkbtn" onClick={() => onPick && onPick(mi)}>{x.orig}</button> : <span>{x.orig}</span>}
        <span className="vw-dim">{size(x.size)}</span>
        <a className="vw-dl" href={x.url} download aria-label={`Download ${x.orig}`}><Glyph k="down" /></a>
      </div>;
    })}</div> : null}
  </div>;
}

// ── full-screen zoom overlay ────────────────────────────────────────────────

const DRAG = 5;  // px of pointer travel before a press is a pan and not a click

// Zoom: a scrolling container with the picture at fit or 100%. A click toggles
// (centred on the clicked point going in); a drag over 5 px pans; switching
// version keeps the normalised point under the centre of the view.
function Zoom({ item, media, ver, setVer, onClose, zoomedRef }) {
  const f = media[Math.min(ver, media.length - 1)];
  const src = f ? shownSrc(f) : null;
  const [zoom, setZoom] = useState(false);
  const box = useRef(null), img = useRef(null);
  const want = useRef(null);   // {fx, fy, px, py}: image fraction to land at view offset px, py
  const drag = useRef(null);
  const moved = useRef(false);

  const place = () => {
    const w = want.current, b = box.current, i = img.current;
    if (!w || !b || !i || !i.naturalWidth) return;
    b.scrollLeft = w.fx * i.naturalWidth - w.px;
    b.scrollTop = w.fy * i.naturalHeight - w.py;
    want.current = null;
  };
  useEffect(place, [zoom]);
  useEffect(() => { zoomedRef.current = zoom; return () => { zoomedRef.current = false; }; }, [zoom]);
  // next version preloaded
  useEffect(() => {
    if (media.length < 2) return;
    const nf = media[(ver + 1) % media.length];
    const n = nf.kind === "photo" ? shownSrc(nf) : null;
    if (n) new Image().src = n;
  }, [ver, media.length]);

  const flip = (i) => {
    if (zoom && img.current && box.current) {
      const b = box.current, el = img.current, r = el.getBoundingClientRect();
      const frac = (sc, cl, len) => (len > cl ? Math.min(1, Math.max(0, (sc + cl / 2) / len)) : 0.5);
      want.current = { fx: frac(b.scrollLeft, b.clientWidth, r.width), fy: frac(b.scrollTop, b.clientHeight, r.height),
                       px: b.clientWidth / 2, py: b.clientHeight / 2 };
    }
    setVer(i);
  };

  const down = (e) => {
    if (e.pointerType === "touch" || e.button !== 0) return;  // touch pans natively
    drag.current = { x: e.clientX, y: e.clientY, sl: box.current.scrollLeft, st: box.current.scrollTop };
    moved.current = false;
    box.current.setPointerCapture(e.pointerId);
  };
  const move = (e) => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x, dy = e.clientY - d.y;
    if (!moved.current && Math.hypot(dx, dy) > DRAG) moved.current = true;
    if (moved.current && zoom) { box.current.scrollLeft = d.sl - dx; box.current.scrollTop = d.st - dy; }
  };
  const up = () => { drag.current = null; };
  const click = (e) => {
    if (moved.current) { moved.current = false; return; }
    const i = img.current;
    if (!i || !src) return;
    if (zoom) { setZoom(false); return; }
    const r = i.getBoundingClientRect(), b = box.current.getBoundingClientRect();
    want.current = { fx: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), fy: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)),
                     px: e.clientX - b.left, py: e.clientY - b.top };
    setZoom(true);
  };

  return (
    <div className="vw-zoom" role="dialog" aria-label={item.title}>
      <div className="hub-pane-head hub-t3p-head vw-head vw-zhead">
        <div className="vw-head-t"><b>{item.title}</b><span className="vw-dim">{zoom ? "100%" : "fit"}</span></div>
        {isVersions(media) ? <Versions media={media} ver={ver} setVer={flip} /> : null}
        <button type="button" className="hub-btn vw-btn is-icon vw-zclose" aria-label="Close" title="Close" onClick={onClose}><Glyph k="close" /></button>
      </div>
      <div className={`vw-zbox${zoom ? " is-100" : ""}`} ref={box} data-zoom={zoom ? "100" : "fit"}
           onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} onClick={click}>
        {src ? <img ref={img} className="vw-zimg" key={src} src={src} alt={item.title} draggable={false} onLoad={place} />
             : <div className="vw-ph"><Glyph k="photo" cls="vw-g vw-g--big" /><span>{(item.preview_status || "").startsWith("failed") ? "preview failed" : "making preview"}</span>
                 {f ? <a className="hub-btn vw-lnk" href={f.url} download>Download {f.orig}</a> : null}</div>}
      </div>
    </div>
  );
}

// "send to terminal": lists live Claude tabs when opened; picking one types a line into
// that tab pointing it at this item, so the session starts on it
function SendTo({ item }) {
  const [open, setOpen] = useState(false);
  const [list, setList] = useState(null);
  const [msg, setMsg] = useState({ text: "", bad: false });
  useEffect(() => { setOpen(false); setMsg({ text: "", bad: false }); }, [item.id]);
  const toggle = () => {
    if (open) return setOpen(false);
    setOpen(true); setList(null);
    fetch("/viewer/api/terminals").then((r) => r.json())
      .then((j) => setList(j.terminals || []), () => setList([]));
  };
  const go = (t) => {
    setOpen(false); setMsg({ text: `Sending to ${t.label}…`, bad: false });
    fetch("/viewer/api/send", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item: item.id, pane: t.pane }) })
      .then((r) => r.json().then((j) => (r.ok ? setMsg({ text: `Sent to ${t.label}`, bad: false })
        : setMsg({ text: `Not sent: ${j.error || r.status}`, bad: true }))))
      .catch(() => setMsg({ text: "Not sent: could not reach the Hub", bad: true }));
  };
  return (
    <span className="vw-menu vw-send">
      {msg.text ? <span className={msg.bad ? "vw-bad" : ""} role="status">{msg.text}</span>
        : <button type="button" className="hub-btn vw-lnkbtn" aria-expanded={open} onClick={toggle}>send to Claude</button>}
      {open ? <span className="vw-pop">
        {list === null ? <span className="vw-dim">Finding terminals…</span>
          : !list.length ? <span className="vw-dim">No Claude terminals open in herdr</span>
          : list.map((t) => <button key={t.pane} type="button" className="hub-btn vw-term" onClick={() => go(t)}>
              <b>{t.label}</b>{t.title ? ` · ${t.title}` : ""}<span className="vw-dim"> · {t.status}</span></button>)}
      </span> : null}
    </span>
  );
}

function Detail({ item, now, ver, setVer, onFull, sheet, onClose }) {
  const media = mediaOf(item);
  const [panel, setPanel] = useState(false);
  const [menu, setMenu] = useState(false);
  const [dims, setDims] = useState({ src: "", v: "" });  // from the shown image's onLoad
  useEffect(() => { setPanel(false); setMenu(false); }, [item.id]);
  const v = Math.min(ver, Math.max(0, media.length - 1));
  const cur = media[v];
  // dimensions belong to one picture: anything else on screen shows none
  const d = cur && cur.kind === "photo" && dims.src === shownSrc(cur) ? dims.v : "";
  const total = item.files.reduce((n, f) => n + f.size, 0);
  const ps = previewText(item);
  return (
    <React.Fragment>
      <div className="hub-pane-head hub-t3p-head vw-head">
        <div className="vw-head-t"><b>{item.title}</b><span className="vw-dim">{ago(item.created, now)}</span></div>
        {sheet ? <button type="button" className="hub-btn vw-btn is-icon vw-close" aria-label="Close" title="Close" onClick={onClose}><Glyph k="close" /></button> : null}
      </div>
      <div className="vw-tools">
        {isVersions(media) ? <Versions media={media} ver={v} setVer={setVer} /> : null}
        {!sheet && cur && cur.kind === "photo" ? <button type="button" className="hub-btn vw-btn is-icon vw-full" aria-label="Full screen" title="Full screen" onClick={onFull}><Glyph k="full" /></button> : null}
      </div>
      <Stage item={item} ver={v} onDims={setDims} onPick={setVer} />
      {panel ? <div className="vw-details-panel hub-t3p-context">
        <div className="hub-detail-card">
          <div className="hub-detail-card-head">Details</div>
          <div className="hub-kv-row vw-kv"><span>From</span><b>{item.source || "Claude"}</b></div>
          {item.files[0] && item.files[0].src ? <div className="hub-kv-row vw-kv vw-kv--stack"><span>Source</span><b>{dir(item.files[0].src)}</b></div> : null}
          {item.files[0] ? <div className="hub-kv-row vw-kv vw-kv--stack"><span>Stored in</span><b>{dir(item.files[0].path)}</b></div> : null}
          <div className="hub-kv-row vw-kv"><span>Shown</span><b>{when(item.created)}</b></div>
          <div className="hub-kv-row vw-kv"><span>Size</span><b>{[d, size(total)].filter(Boolean).join(" · ")}</b></div>
          {ps ? <div className="hub-kv-row vw-kv"><span>Preview</span><b>{ps.replace("preview ", "")}</b></div> : null}
        </div>
        <div className="hub-detail-card">
          <div className="hub-detail-card-head">Files</div>
          {item.files.map((f) => <div key={f.name} className="hub-kv-row vw-kv vw-file">
            <span>{f.orig} · {size(f.size)}</span>
            <b><a className="vw-dl" href={f.url} download aria-label={`Download ${f.orig}`}><Glyph k="down" /></a></b></div>)}
        </div>
      </div> : null}
      <div className="vw-line vw-details">
        <span><b>{item.source || "Claude"}</b> · {ago(item.created, now)}</span>
        {d ? <span>{d}</span> : null}
        {ps ? <span>{ps}</span> : null}
        {item.files.length ? <span className="vw-menu">
          <button type="button" className="hub-btn vw-lnkbtn" aria-expanded={menu} onClick={() => setMenu(!menu)}>
            {item.files.length} {item.files.length === 1 ? "file" : "files"} ↓</button>
          {menu ? <span className="vw-pop">{item.files.map((f) =>
            <a key={f.name} href={f.url} download>{f.orig}</a>)}</span> : null}
        </span> : null}
        {item.files.length || item.url ? <SendTo item={item} /> : null}
        <button type="button" className="hub-btn vw-lnkbtn" aria-expanded={panel} onClick={() => setPanel(!panel)}>details</button>
      </div>
    </React.Fragment>
  );
}

// ── the grid ────────────────────────────────────────────────────────────────

function Card({ it, on, now, fresh, onPick }) {
  const th = thumbOf(it);
  return (
    <button type="button" className={`vw-card vw-tile${on ? " active" : ""}`} data-id={it.id} aria-pressed={on} onClick={() => onPick(it.id)}>
      {th ? <img className="vw-th" src={th} alt="" loading="lazy" />
          : <span className="vw-th vw-th--g"><Glyph k={it.kind === "upload" ? "upload" : it.kind} /></span>}
      <b>{it.title}</b>
      <span className="vw-row-m">{it.kind === "upload" ? <span className="vw-you">you</span> : null}{fresh ? <span className="vw-new">New</span> : null}{age(it.created, now)}</span>
    </button>
  );
}

// ── the page ────────────────────────────────────────────────────────────────

function ViewerApp() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("everything");
  const [sel, setSel] = useState(() => new URLSearchParams(location.search).get("item"));
  const [now, setNow] = useState(Date.now());
  const [drawer, setDrawer] = useState(false);
  const [sheet, setSheet] = useState(false);   // phone sheet for items that are not a photo
  const [full, setFull] = useState(false);      // full-screen zoom overlay
  const [ver, setVer] = useState(0);
  const [fresh, setFresh] = useState(() => new Set());   // ids that arrived while he was busy
  const [up, setUp] = useState({ msg: "", bad: false });
  const [drop, setDrop] = useState(false);
  const lastOk = useRef(0);
  const picker = useRef(null);
  const cur = useRef({});          // what the poll needs to know about the screen
  const zoomed = useRef(false);    // set by the overlay while at 100%
  const known = useRef(null);      // ids seen so far (null before the first feed)
  const load = useRef(null);
  const fullNext = useRef(false);  // open the overlay once the picked item becomes the open one

  // poll: 3 s while the tab is visible, 30 s after an error
  useEffect(() => {
    let stop = false, timer;
    const arrive = (list) => {
      const prev = known.current;
      known.current = new Set(list.map((x) => x.id));
      if (!prev) return;
      const added = list.filter((x) => !prev.has(x.id));
      if (!added.length) return;
      // follow the newest item only when he is on the previous newest, at fit, with no video playing
      const v = document.querySelector(".vw-stage video");
      const calm = cur.current.onTop && !zoomed.current && !(v && !v.paused);
      if (calm) setSel(list[0].id);
      else setFresh((s) => new Set([...s, ...added.map((x) => x.id)]));
    };
    const once = async () => {
      const r = await fetch("/viewer/api/feed");
      if (!r.ok) throw new Error(`feed ${r.status}`);
      const j = await r.json();
      if (!stop) { arrive(j.items); setItems(j.items); setError(""); lastOk.current = Date.now(); }
    };
    load.current = () => once().catch(() => {});
    const tick = async () => {
      let next = 3000;
      if (document.visibilityState === "visible") {
        try { await once(); } catch (e) { if (!stop) setError(String(e.message || e)); next = 30000; }
      }
      if (!stop) timer = setTimeout(tick, next);
    };
    tick();
    return () => { stop = true; clearTimeout(timer); };
  }, []);

  // one-second clock for the ages and the footer
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);

  // mount marker, phone drawer wiring, Escape closes the sheet
  useEffect(() => {
    $("viewer-root").setAttribute("data-react-mounted", "viewer");
    const toggle = $("navToggle"), scrim = $("vwScrim");
    const flip = () => setDrawer((o) => !o), shut = () => setDrawer(false);
    const esc = (e) => { if (e.key === "Escape") { setFull(false); setSheet(false); setDrawer(false); } };
    toggle.addEventListener("click", flip); scrim.addEventListener("click", shut);
    document.addEventListener("keydown", esc);
    return () => { toggle.removeEventListener("click", flip); scrim.removeEventListener("click", shut); document.removeEventListener("keydown", esc); };
  }, []);
  useEffect(() => {
    $("vwScrim").hidden = !drawer;
    $("navToggle").setAttribute("aria-expanded", String(drawer));
  }, [drawer]);

  const all = items || [];
  const counts = useMemo(() => {
    const c = { everything: all.length };
    for (const it of all) c[it.kind] = (c[it.kind] || 0) + 1;
    return c;
  }, [items]);
  const shown = filter === "everything" ? all : all.filter((it) => it.kind === filter);
  const open = shown.find((it) => it.id === sel) || shown[0] || null;
  const fname = KINDS.find((k) => k.key === filter).name;
  const mine = counts.upload || 0;

  useEffect(() => { $("crumbSection").textContent = fname; }, [fname]);
  useEffect(() => {
    $("statusMsg").textContent = items ? `${all.length} items · ${mine} from you · kept 30 days` : "loading";
    $("statusMeta").textContent = error ? `feed error · ${error}`
      : lastOk.current ? `updated ${Math.max(0, Math.round((now - lastOk.current) / 1000))} s ago` : "";
  }, [items, error, now]);

  cur.current.onTop = !!(open && all[0] && open.id === all[0].id);
  // a phone tap on a photo opens it full screen; any other change of item closes the overlay
  useEffect(() => { setVer(0); setFull(fullNext.current); fullNext.current = false; }, [open && open.id]);
  const media = open ? mediaOf(open) : [];
  const pick = (id) => {
    setSel(id);
    setFresh((s) => { if (!s.has(id)) return s; const n = new Set(s); n.delete(id); return n; });
    if (!window.matchMedia(PHONE).matches) return;
    const it = all.find((x) => x.id === id), m = it ? mediaOf(it) : [];
    if (m[0] && m[0].kind === "photo") { setVer(0); setFull(true); fullNext.current = id !== (open && open.id); } else setSheet(true);
  };

  // upload: XHR for the progress, the server's own error text on 4xx/5xx
  const send = (files) => {
    if (!files || !files.length) return;
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    const x = new XMLHttpRequest();
    x.open("POST", "/viewer/api/upload");
    x.upload.onprogress = (e) => e.lengthComputable && setUp({ msg: `Uploading ${files.length} ${files.length === 1 ? "file" : "files"}: ${Math.round(100 * e.loaded / e.total)}%`, bad: false });
    x.onerror = () => setUp({ msg: "Upload failed: could not reach the Hub", bad: true });
    x.onload = () => {
      let err = "";
      try { err = JSON.parse(x.responseText).error || ""; } catch (_) { err = ""; }
      if (x.status >= 200 && x.status < 300) {
        setUp({ msg: `Uploaded ${files.length} ${files.length === 1 ? "file" : "files"}`, bad: false });
        setFilter("everything");
        load.current && load.current();
        setTimeout(() => setUp((u) => (u.bad ? u : { msg: "", bad: false })), 4000);
      } else setUp({ msg: `Upload failed: ${err || x.status}`, bad: true });
    };
    setUp({ msg: `Uploading ${files.length} ${files.length === 1 ? "file" : "files"}: 0%`, bad: false });
    x.send(fd);
  };

  // whole page is a drop target for files
  useEffect(() => {
    let depth = 0;
    const has = (e) => e.dataTransfer && [...e.dataTransfer.types].includes("Files");
    const over = (e) => { if (has(e)) e.preventDefault(); };
    const enter = (e) => { if (has(e)) { depth++; setDrop(true); } };
    const leave = (e) => { if (has(e) && --depth <= 0) { depth = 0; setDrop(false); } };
    const dropped = (e) => { if (!has(e)) return; e.preventDefault(); depth = 0; setDrop(false); send(e.dataTransfer.files); };
    document.addEventListener("dragover", over); document.addEventListener("dragenter", enter);
    document.addEventListener("dragleave", leave); document.addEventListener("drop", dropped);
    return () => { document.removeEventListener("dragover", over); document.removeEventListener("dragenter", enter);
      document.removeEventListener("dragleave", leave); document.removeEventListener("drop", dropped); };
  }, []);
  // paste: a clipboard screenshot comes in as a bare "image.png", so it gets a dated name;
  // files copied in Explorer keep theirs
  const pasted = (files) => {
    const t = new Date(), p = (n) => String(n).padStart(2, "0");
    const stamp = `${t.getFullYear()}${p(t.getMonth() + 1)}${p(t.getDate())}-${p(t.getHours())}${p(t.getMinutes())}${p(t.getSeconds())}`;
    send(files.map((f, i) => /^image\.\w+$/.test(f.name) || !f.name
      ? new File([f], `paste-${stamp}${files.length > 1 ? `-${i + 1}` : ""}.${(f.type.split("/")[1] || "png").replace("jpeg", "jpg")}`, { type: f.type })
      : f));
  };
  useEffect(() => {
    const onPaste = (e) => {
      const el = e.target;
      if (el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName))) return;
      const fs = [...((e.clipboardData && e.clipboardData.files) || [])];
      if (!fs.length) return;
      e.preventDefault();
      pasted(fs);
    };
    document.addEventListener("paste", onPaste);
    return () => document.removeEventListener("paste", onPaste);
  }, []);
  // the button reads images only (the async clipboard API has no files) and needs a secure
  // context: localhost yes, the tailnet's http address no, so there it points at Ctrl+V
  const pasteBtn = async () => {
    const bad = (msg) => setUp({ msg, bad: true });
    if (!(navigator.clipboard && navigator.clipboard.read)) return bad("Paste button needs localhost: press Ctrl+V instead");
    try {
      const fs = [];
      for (const it of await navigator.clipboard.read()) {
        const type = it.types.find((t) => t.startsWith("image/"));
        if (type) fs.push(new File([await it.getType(type)], "image.png", { type }));
      }
      fs.length ? pasted(fs) : bad("No image on the clipboard (for copied files press Ctrl+V)");
    } catch (_) { bad("Clipboard blocked: press Ctrl+V instead"); }
  };
  const setKind = (k) => { setFilter(k); setDrawer(false); };
  const chips = KINDS.filter((k) => k.key === "everything" || k.key === "photo" || k.key === "upload" || counts[k.key]);

  return (
    <React.Fragment>
      <section className={`col hub-t3p-col funnel hub-t3p-rail${drawer ? " is-open" : ""}`} id="vwRail">
        <nav className="hub-nav-rail vw-nav">
          <button type="button" className="hub-btn vw-up" onClick={() => picker.current && picker.current.click()}>
            <Glyph k="upload" />Upload</button>
          <button type="button" className="hub-btn vw-up vw-paste" title="Paste a screenshot (Ctrl+V anywhere on the page also takes copied files)" onClick={pasteBtn}>
            <Glyph k="paste" />Paste</button>
          <input ref={picker} type="file" multiple hidden onChange={(e) => { const fs = [...e.target.files]; e.target.value = ""; send(fs); }} />
          {KINDS.map((k) => (
            <button key={k.key} type="button" data-kind={k.key}
                    className={`hub-t3p-tab hub-nav-item vw-filter${filter === k.key ? " active" : ""}`}
                    aria-pressed={filter === k.key} onClick={() => setKind(k.key)}>
              <span className="hub-t3p-tab-label hub-nav-label"><Glyph k={k.key} cls="hub-t3p-tab-glyph" />{k.name}</span>
              <span className="vw-cnt">{counts[k.key] || 0}</span>
            </button>
          ))}
        </nav>
      </section>
      <section className="col hub-t3p-col hub-t3p-pane">
        <div className="hub-split hub-t3p-split vw-split vw-b">
          <div className="hub-pane-col hub-t3p-list-col">
            <div className="hub-pane-head hub-t3p-head vw-head">
              <div className="vw-head-t"><b>{fname}</b><span className="vw-dim">{shown.length} {shown.length === 1 ? "item" : "items"} · newest first</span></div>
            </div>
            <div className="vw-chips hub-tabs hub-tabs--segmented" role="tablist" aria-label="Kinds">
              {chips.map((k) => <button key={k.key} type="button" role="tab" data-kind={k.key} aria-selected={filter === k.key}
                className={`hub-tab vw-chip${filter === k.key ? " active" : ""}`} onClick={() => setKind(k.key)}>
                {k.key === "everything" ? `All ${counts.everything || 0}` : k.name}</button>)}
            </div>
            {up.msg ? <div className={`vw-upmsg${up.bad ? " is-bad" : ""}`} role="status">{up.msg}</div> : null}
            {error && !items ? <div className="hub-error">couldn't load the feed: {error}</div>
              : items && !shown.length ? <div className="vw-empty">Nothing here yet.</div> : null}
            <div className="vw-grid">
              {shown.map((it) => <Card key={it.id} it={it} on={open && open.id === it.id} fresh={fresh.has(it.id)} now={now} onPick={pick} />)}
            </div>
          </div>
          <div className="hub-t3p-side vw-pane">
            {open ? <Detail item={open} now={now} ver={ver} setVer={setVer} onFull={() => setFull(true)} /> : null}
          </div>
        </div>
      </section>
      {sheet && open ? <div className="vw-sheet" role="dialog" aria-label={open.title}>
        <Detail item={open} now={now} ver={ver} setVer={setVer} sheet onClose={() => setSheet(false)} /></div> : null}
      {full && open && media.length > 0 && media[Math.min(ver, media.length - 1)].kind === "photo"
        ? <Zoom item={open} media={media} ver={Math.min(ver, media.length - 1)} setVer={setVer} zoomedRef={zoomed} onClose={() => setFull(false)} /> : null}
      {drop ? <div className="vw-drop"><span>Drop to upload</span></div> : null}
    </React.Fragment>
  );
}

class ErrorBoundary extends React.Component {
  constructor(p) { super(p); this.state = { err: null }; }
  static getDerivedStateFromError(err) { return { err }; }
  render() {
    if (this.state.err) return <div className="hub-error">page failed to load: {String(this.state.err.message || this.state.err)}</div>;
    return this.props.children;
  }
}

ReactDOM.createRoot($("viewer-root")).render(<ErrorBoundary><ViewerApp /></ErrorBoundary>);
})();
