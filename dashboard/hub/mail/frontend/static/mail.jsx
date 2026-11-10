/* mail: tabbed 3-pane page. Rail = search (from: and in: filters), Inbox / All / Sent / Drafts / Trash / Spam and the
   label tree; middle = the thread list, either one line per sender (opens in place) or the
   plain newest-first list; right = the open thread (ThreadPanel).

   Picked layout: Workbench set mail-layout, 2026-10-20, "One line per sender, opens in place".
   URL state: ?label=<label id> and ?sender=<address> (the last sender opened).
   Reads and label writes only; there is no send, compose or Outlook code on this page.
   Promise chains, not async/await, and no object spread: babel's helpers would be top-level globals. */
window.MailUI = window.MailUI || {};
(() => {
  const { useState, useEffect, useRef, useMemo, Component } = React;
  const $ = (id) => document.getElementById(id);

  const J = (url, opts) => fetch(url, opts).then(
    (r) => r.json().then((d) => { if (!r.ok) throw new Error((d && d.error) || `HTTP ${r.status}`); return d; },
      () => { throw new Error(`HTTP ${r.status}`); }));
  const post = (url, body) => J(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});

  const STALE_MIN = 15;  // the sync job runs every 5 minutes
  const MODE_KEY = "mail.mode";
  // Unread gave way to All (mark 221739 #1; named "All" so the list head never wraps, marks 223145 #1, 223156 #1);
  // ALL is every mirrored message outside Spam and Trash, Gmail's All Mail.
  // No Waiting tab: a waiting thread is always in the Inbox with its amber dot; null is a divider (mark 224420 #1)
  const FIXED = [["INBOX", "Inbox", "inbox"], ["ALL", "All", "all"], null,
                 ["BRIEF", "Brief", "brief"], null,
                 ["SENT", "Sent", "sent"], ["DRAFT", "Drafts", "drafts"], null,
                 ["TRASH", "Trash", "trash"], ["SPAM", "Spam", "spam"]];
  const TABS = FIXED.filter(Boolean);
  // Spam and Trash mirror Gmail's own (it empties both after 30 days); mark 221739 #2
  const BIN = {SPAM: 1, TRASH: 1};
  const COUNTED = {INBOX: 1};  // the rest have no unread worth counting

  const GLYPH = {
    inbox: <path d="M3.6 13.2 L6.6 5.4 H17.4 L20.4 13.2 V18.6 H3.6 Z M3.6 13.2 H8.4 L9.6 15.6 H14.4 L15.6 13.2 H20.4" />,
    all: <React.Fragment><rect x="3.6" y="8.4" width="16.8" height="10.8" rx="1.2" /><path d="M5.4 6 H18.6 M7.2 3.6 H16.8" /></React.Fragment>,
    brief: <path d="M4.8 5.4 H16.2 V18.6 H6.6 A1.8 1.8 0 0 1 4.8 16.8 Z M16.2 9 H19.2 V16.8 A1.8 1.8 0 0 1 17.4 18.6 H16.2 M7.8 8.4 H13.2 M7.8 11.4 H13.2 M7.8 14.4 H11.4" />,
    sent: <path d="M4.2 12 L19.8 4.8 L16.2 19.2 L11.4 13.8 Z M11.4 13.8 L19.8 4.8" />,
    drafts: <path d="M5.4 19.2 L6 15.6 L16.2 5.4 L18.6 7.8 L8.4 18 Z M14.4 7.2 L16.8 9.6" />,
    spam: <React.Fragment><path d="M8.4 3.6 H15.6 L20.4 8.4 V15.6 L15.6 20.4 H8.4 L3.6 15.6 V8.4 Z" /><path d="M12 7.8 V12.6 M12 15.6 V16.2" /></React.Fragment>,
    trash: <path d="M4.2 6.6 H19.8 M9.6 6.6 V4.2 H14.4 V6.6 M6 6.6 L7.2 19.8 H16.8 L18 6.6 M10.2 10.2 V16.2 M13.8 10.2 V16.2" />,
  };

  // ── small helpers ──────────────────────────────────────────────────────────

  const readUrl = () => {
    const p = new URLSearchParams(location.search);
    const label = p.get("label");
    return {label: !label || label === "waiting" ? "INBOX" : label, sender: p.get("sender") || ""};
  };
  const writeUrl = (label, sender) => {
    const p = new URLSearchParams();
    p.set("label", label);
    if (sender) p.set("sender", sender);
    history.replaceState(null, "", `${location.pathname}?${p.toString()}`);
  };
  const readMode = () => { try { return localStorage.getItem(MODE_KEY) === "newest" ? "newest" : "sender"; } catch (_e) { return "sender"; } };
  const saveMode = (m) => { try { localStorage.setItem(MODE_KEY, m); } catch (_e) { /* private mode: the switch just is not remembered */ } };

  const when = (ms) => {
    const d = new Date(Number(ms)), n = new Date();
    if (d.toDateString() === n.toDateString()) return d.toLocaleTimeString([], {hour: "numeric", minute: "2-digit"});
    const o = {month: "short", day: "numeric"};
    if (d.getFullYear() !== n.getFullYear()) o.year = "numeric";
    return d.toLocaleDateString([], o);
  };
  const minutesSince = (iso) => iso ? Math.max(0, Math.floor((Date.now() - Date.parse(iso)) / 60000)) : null;
  const agoText = (m) => m === null ? "Never synced" : m < 1 ? "Synced just now" : m < 60 ? `Synced ${m} min ago` : m < 1440 ? `Synced ${Math.floor(m / 60)} h ago` : `Synced ${Math.floor(m / 1440)} d ago`;
  // Gmail label names carry "I. ", "A. ", "1. ", "a. " only to sort the folders; the Hub shows them without
  // (mark 221413 #1). Display only: ids and the stored names are untouched.
  const shown = (name) => name.split("/").map((p) => p.replace(/^(?:[IVXLC]+|[A-Za-z]|\d+)\.\s+/, "")).join("/");
  const leaf = (name) => shown(name).split("/").pop();
  const plural = (n, w) =>`${n} ${w}${n === 1 ? "" : "s"}`;
  const keyAct = (fn) => (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); fn(); } };

  const threadsUrl = (params, cursor) => {
    const p = new URLSearchParams();
    p.set("label", params.label);
    if (params.q) p.set("q", params.q);
    if (params.from !== undefined) p.set("from", params.from);  // "" is a sender key (no parsable From), not "everyone"
    if (cursor) p.set("cursor", cursor);
    return `/mail/api/threads?${p.toString()}`;
  };


  // paged thread list for one set of params; reloads when params or `rev` change
  function useThreads(params, on, rev) {
    const [st, setSt] = useState({threads: [], cursor: null, loading: false, err: null});
    const seq = useRef(0);
    const key = `${params.label}|${params.q}|${params.from || ""}|${rev}`;
    const load = (cursor) => {
      const n = ++seq.current;
      setSt((s) => ({threads: s.threads, cursor: s.cursor, loading: true, err: null}));
      J(threadsUrl(params, cursor)).then((d) => {
        if (n === seq.current) setSt((s) => ({threads: cursor ? s.threads.concat(d.threads) : d.threads, cursor: d.cursor, loading: false, err: null}));
      }).catch((e) => {
        if (n === seq.current) setSt((s) => ({threads: s.threads, cursor: s.cursor, loading: false, err: e.message}));
      });
    };
    useEffect(() => { if (on) load(""); }, [key, on]);
    return [st, () => { if (st.cursor && !st.loading) load(st.cursor); }];
  }

  // ── rail ───────────────────────────────────────────────────────────────────

  // a typed word searches All mail by keyword. Filters are typed, Discord style: an empty box offers
  // from: and in:, and only once one is typed does the box autofill senders or folders and labels;
  // a pick becomes a chip (send-back on mark 221739 #3). The From chip stays across tabs until its x
  // or Backspace in an empty box clears it; the In chip scopes the search in place of All.
  // from: and in: are chips too, in the menu and in the box once typed or picked; while one sits in the box
  // the text after it only autofills and the search keeps its words (second send-back, "make it a chip").
  // Senders are /api/senders over All mail, fetched once on first focus and filtered here.
  const OPS = [["from:", "a sender"], ["in:", "a folder or label"]];
  const keywords = (q) => q.split(/\s+/).filter((w) => w && !/^(from|in):/i.test(w)).join(" ");

  function SearchBox({q, onQ, from, onFrom, scope, onScope, labels}) {
    const [all, setAll] = useState(null), [focus, setFocus] = useState(false), [hi, setHi] = useState(-1);
    const asked = useRef(false);
    const load = () => {
      if (asked.current) return;
      asked.current = true;
      J("/mail/api/senders?label=ALL").then(setAll).catch(() => { asked.current = false; });
    };
    const [pend, setPend] = useState(null), [term, setTerm] = useState("");  // the from/in chip in the box, and the text after it
    const op = pend ? {op: pend, t: term.trim().toLowerCase()} : null;
    const places = TABS.map(([id, name]) => ({id, name})).concat(labels.filter((l) => l.type === "user").map((l) => ({id: l.id, name: shown(l.name)})));
    const hits = !op ? (q.trim() ? [] : OPS.filter(([o]) => o === "from:" ? !from : !scope).map(([o, x]) => ({kind: "op", key: o, name: o, x})))
      : op.op === "from" ? (all || []).filter((g) => !op.t || g.name.toLowerCase().indexOf(op.t) >= 0 || g.key.indexOf(op.t) >= 0).slice(0, 8).map((g) => ({kind: "from", key: g.key, name: g.name, x: g.name !== g.key ? g.key : "", n: g.threads}))
      : places.filter((p) => !op.t || p.name.toLowerCase().indexOf(op.t) >= 0).slice(0, 8).map((p) => ({kind: "in", key: p.id, name: p.name, x: ""}));
    const open = focus && hits.length > 0;
    const strip = () => { setPend(null); setTerm(""); };
    const pick = (h) => {
      setHi(-1);
      if (h.kind === "op") { setPend(h.key.slice(0, -1)); setTerm(""); }
      else if (h.kind === "from") { onFrom({key: h.key, name: h.name}); strip(); }
      else { onScope({id: h.key, name: h.name}); strip(); }
    };
    const onType = (v) => {
      if (pend) { setTerm(v); return; }
      // typing from: or in: turns it into the chip; the words before it stay the search
      const m = /(?:^|\s)(from|in):(\S*)$/i.exec(v);
      if (!m) { onQ(v); return; }
      onQ(v.slice(0, m.index).replace(/\s+$/, ""));
      setPend(m[1].toLowerCase());
      setTerm(m[2]);
    };
    const onKey = (ev) => {
      if (ev.key === "Backspace" && pend && !term) { strip(); return; }
      if (ev.key === "Backspace" && !q && (scope || from)) { if (scope) onScope(null); else onFrom(null); return; }
      if (!open) return;
      if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
        ev.preventDefault();
        const d = ev.key === "ArrowDown" ? 1 : -1;
        // -1 is the typed text itself; the arrows wrap through it
        setHi((i) => { const n = i + d; return n >= hits.length ? -1 : n < -1 ? hits.length - 1 : n; });
      } else if (ev.key === "Enter" && (hi >= 0 || op)) { ev.preventDefault(); pick(hits[Math.max(hi, 0)]); }
      else if (ev.key === "Escape") { setFocus(false); setHi(-1); }
    };
    const scoped = scope ? scope.name : "All";
    return <React.Fragment><div className={`mx-search${pend ? " has-op" : ""}`}>
      <svg className="mx-ic" viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.6" /><path d="M16 16 L20.4 20.4" /></svg>
      {pend ? <span className="hub-pill mx-op-chip mx-op-in">{pend}:</span> : null}
      <input className="hub-input" type="text" aria-label={pend ? `Search mail, ${pend}:` : "Search mail"}
        placeholder={pend ? (pend === "from" ? "a sender" : "a folder") : from ? `Search ${from.name}` : scope ? `Search ${scope.name}` : "Search mail"}
        style={pend ? {paddingLeft: `calc(${pend.length + 1}ch + 48px)`} : undefined}
        role="combobox" aria-autocomplete="list" aria-expanded={open} aria-controls="mxSugg" aria-activedescendant={open && hi >= 0 ? `mxSugg${hi}` : undefined}
        value={pend ? term : q} onFocus={() => { setFocus(true); load(); }} onBlur={() => { setFocus(false); setHi(-1); }}
        onChange={(ev) => { onType(ev.target.value); setFocus(true); setHi(-1); }} onKeyDown={onKey} />
      {open ? <ul className="mx-sugg" id="mxSugg" role="listbox" aria-label={op ? (op.op === "from" ? "Senders" : "Folders and labels") : "Filters"}>
        {!op ? <li className="mx-sugg-h" role="presentation">Searching {scoped} · filter by</li> : null}
        {hits.map((h, i) => <li key={h.kind + h.key} id={`mxSugg${i}`} role="option" aria-selected={i === hi} className={`${i === hi ? "active" : ""}${h.kind === "op" ? " is-op" : ""}`}
          onMouseDown={(ev) => { ev.preventDefault(); pick(h); }} onMouseEnter={() => setHi(i)}>
          {h.kind === "op" ? <b><span className="hub-pill mx-op-chip">{h.name}</span></b> : <b>{h.name}</b>}{h.x ? <span>{h.x}</span> : null}{h.n ? <i>{h.n}</i> : null}
        </li>)}
      </ul> : null}
    </div>
    {from || scope ? <div className="mx-from">
      {from ? <span className="hub-pill mx-from-chip" title={from.key}><span>From: {from.name}</span>
        <button type="button" className="hub-pill-x" aria-label={`Stop filtering to ${from.name}`} onClick={() => onFrom(null)}>&times;</button></span> : null}
      {scope ? <span className="hub-pill mx-from-chip"><span>In: {scope.name}</span>
        <button type="button" className="hub-pill-x" aria-label={`Search all mail, not only ${scope.name}`} onClick={() => onScope(null)}>&times;</button></span> : null}
    </div> : null}
    </React.Fragment>;
  }

  function Rail({labels, label, onPick, q, onQ, from, onFrom, scope, onScope, briefN}) {
    const byId = {};
    labels.forEach((l) => { byId[l.id] = l; });
    const count = (id) => id === "BRIEF" ? (briefN || "") : COUNTED[id] && byId[id] && byId[id].unread > 0 ? byId[id].unread : "";
    // the whole label tree, always expanded, each with its own count (mark 224420 #2, "full expand always")
    const user = labels.filter((l) => l.type === "user");
    // double-click a parent label to fold its children (marks 093936 #2 / 095433 #3); open by default, remembered here
    const [folded, setFolded] = useState(() => { try { return new Set(JSON.parse(localStorage.getItem("mx-folded") || "[]")); } catch (e) { return new Set(); } });
    const hasKids = (l) => user.some((k) => k.name.startsWith(l.name + "/"));
    const hidden = (l) => [...folded].some((f) => l.name.startsWith(f + "/"));
    const fold = (l) => setFolded((s) => {
      const n = new Set(s); if (n.has(l.name)) n.delete(l.name); else n.add(l.name);
      try { localStorage.setItem("mx-folded", JSON.stringify([...n])); } catch (e) { /* private window: fold for this visit only */ }
      return n;
    });
    return <nav className="hub-nav-rail" id="mxNav">
      <SearchBox q={q} onQ={onQ} from={from} onFrom={onFrom} scope={scope} onScope={onScope} labels={labels} />
      {FIXED.map((f, i) => f ? <button key={f[0]} type="button" className={`hub-t3p-tab hub-nav-item${label === f[0] ? " active" : ""}`} onClick={() => onPick(f[0])}>
        <span className="hub-t3p-tab-label hub-nav-label"><svg className="hub-t3p-tab-glyph" viewBox="0 0 24 24" aria-hidden="true">{GLYPH[f[2]]}</svg>{f[1]}</span>
        <span className="mx-count">{count(f[0])}</span>
      </button> : <hr key={`div${i}`} className="mx-rail-div" />)}
      {user.length ? <div className="mx-rail-h">Labels</div> : null}
      {user.filter((l) => !hidden(l)).map((l) => <button key={l.id} type="button" className={`hub-nav-item mx-lab${label === l.id ? " active" : ""}${folded.has(l.name) ? " is-folded" : ""}`} style={{"--mx-depth": l.name.split("/").length - 1}} onClick={() => onPick(l.id)}
        onDoubleClick={hasKids(l) ? () => fold(l) : undefined} aria-expanded={hasKids(l) ? !folded.has(l.name) : undefined} title={hasKids(l) ? "Double-click to fold or unfold" : undefined}>
        <span className="hub-nav-label">{leaf(l.name)}</span>
        <span className="mx-count">{l.unread > 0 ? l.unread : ""}</span>
      </button>)}
    </nav>;
  }

  // ── list ───────────────────────────────────────────────────────────────────

  // waiting is a small amber dot, never a chip; the count lives in its label;
  // with nothing waiting it still holds its slot, so the times line up
  function Pip({n}) { return n ? <span className="mx-pip" role="img" title={`${n} waiting`} aria-label={`${n} waiting`} /> : <span className="mx-pip is-none" aria-hidden="true" />; }
  function Chip({t}) { return <Pip n={t.waiting ? 1 : 0} />; }

  // flat newest-first row
  function ThreadRow({t, active, onOpen}) {
    return <div className={`mx-row${t.unread ? " is-unread" : ""}${active ? " active" : ""}`} role="button" tabIndex={0}
      onClick={() => onOpen(t)} onKeyDown={keyAct(() => onOpen(t))}>
      <span className="mx-row-top">
        <b className="mx-row-from">{t.sender_name || t.sender_addr}{t.count > 1 ? <i> {t.count}</i> : null}</b>
        <Chip t={t} />
        <span className="mx-row-time">{when(t.newest_date)}</span>
      </span>
      <span className="mx-row-subj" title={t.subject}>{t.title || t.subject || "(no subject)"}</span>
      <span className="mx-row-snip">{t.preview || t.snippet}</span>
    </div>;
  }

  // one line inside an opened sender
  function SubRow({t, active, onOpen}) {
    return <div className={`mx-sub${t.unread ? " is-unread" : ""}${active ? " active" : ""}`} role="button" tabIndex={0}
      onClick={() => onOpen(t)} onKeyDown={keyAct(() => onOpen(t))}>
      <span className="mx-sub-subj" title={t.subject}>{t.title || t.subject || "(no subject)"}{t.count > 1 ? <i> {t.count}</i> : null}</span>
      <Chip t={t} />
      <span className="mx-row-time">{when(t.newest_date)}</span>
    </div>;
  }

  function MoreButton({st, onMore}) {
    if (st.err) return <div className="hub-error mx-pad">{st.err}</div>;
    if (st.cursor) return <div className="mx-pad"><button type="button" className="hub-btn" disabled={st.loading} onClick={onMore}>Load more</button></div>;
    return null;
  }

  // one sender: a native details line that opens in place to its threads
  function SenderGroup({g, params, rev, isOpen, onToggle, selected, onOpen}) {
    const [st, more] = useThreads({label: params.label, q: params.q, from: g.key}, isOpen, rev);
    return <details className="hub-collapsible-group mx-acc" open={isOpen} onToggle={(ev) => { if (ev.currentTarget.open !== isOpen) onToggle(g.key, ev.currentTarget.open); }}>
      <summary className={`hub-section-head mx-head${g.unread ? " is-unread" : ""}`}>
        <b className="mx-who">{g.name}</b>
        <span className="mx-count">{g.threads}</span>
        <span className="mx-last" title={isOpen ? undefined : g.newest_subject}>{isOpen ? "" : g.newest_title || g.newest_subject}</span>
        <Pip n={g.waiting} />
        <span className="mx-row-time">{when(g.newest_date)}</span>
      </summary>
      {isOpen ? <div className="mx-acc-body">
        {st.threads.map((t) => <SubRow key={t.thread_id} t={t} active={t.thread_id === selected} onOpen={onOpen} />)}
        {st.loading && !st.threads.length ? <div className="mx-dim mx-pad">Loading...</div> : null}
        <MoreButton st={st} onMore={more} />
      </div> : null}
    </details>;
  }

  // senders sharing a mail domain (google.com: Google, Google One, Google Play...) sit under one company heading.
  // ponytail: the domain is its last two labels, so a co.uk sender groups by "co.uk"; use a public-suffix list if one shows up
  const domainOf = (addr) => (addr.split("@")[1] || "").toLowerCase().split(".").slice(-2).join(".");
  const companies = (list) => {
    const by = new Map(), out = [];
    list.forEach((g) => {
      const d = domainOf(g.key);
      if (!d) { out.push(g); return; }
      if (!by.has(d)) { const c = {key: `co:${d}`, members: []}; by.set(d, c); out.push(c); }
      by.get(d).members.push(g);
    });
    // biggest group first, by the count each line shows; ties keep newest-first (sort is stable)
    const big = (a, b) => b.threads - a.threads;
    return out.map((c) => {
      if (!c.members || c.members.length < 2) return c.members ? c.members[0] : c;
      const newest = c.members[0];  // the list arrives newest-first
      c.members.sort(big);
      const named = c.members.map((g) => g.name).filter((n) => n.indexOf("@") < 0).sort((a, b) => a.length - b.length);
      const sum = (k) => c.members.reduce((n, g) => n + g[k], 0);
      return {key: c.key, members: c.members, name: named[0] || c.key.slice(3), threads: sum("threads"), unread: sum("unread"),
        waiting: sum("waiting"), newest_date: newest.newest_date, newest_subject: newest.newest_subject, newest_title: newest.newest_title};
    }).sort(big);
  };

  // one company: a heading with its total, its senders under it as cards.
  // Pick: Workbench set mail-company-group, 2026-10-20, "Company as a heading" + "turn sub groups into cards"
  function CompanyGroup({c, openKeys, onToggle, groupProps}) {
    // a sender named like the company (or with no name) reads by its mailbox: "noreply-accounts"
    const sub = (g) => g.name === c.name || g.name.indexOf("@") >= 0 ? Object.assign({}, g, {name: g.key.split("@")[0]}) : g;
    return <section className="mx-co-sec">
      <div className="mx-co-h"><b>{c.name}</b><span className="mx-count">{c.threads}</span></div>
      {c.members.map((g) => <SenderGroup key={g.key} g={sub(g)} isOpen={openKeys.has(g.key)} onToggle={onToggle} {...groupProps} />)}
    </section>;
  }

  function SenderList({senders, params, rev, openKeys, onToggle, selected, onOpen, onChanged, say}) {
    const groupProps = {params, rev, selected, onOpen, onChanged, say};
    return <div className="mx-list mx-groups" data-sb-out="">
      {senders.data === null && !senders.err ? <div className="hub-empty-state mx-pad">Loading...</div> : null}
      {senders.err ? <div className="hub-error mx-pad">{senders.err}</div> : null}
      {senders.data && !senders.data.length ? <div className="hub-empty-state mx-pad">Nothing here.</div> : null}
      {companies(senders.data || []).map((g) => g.members
        ? <CompanyGroup key={g.key} c={g} openKeys={openKeys} onToggle={onToggle} groupProps={groupProps} />
        : <SenderGroup key={g.key} g={g} isOpen={openKeys.has(g.key)} onToggle={onToggle} {...groupProps} />)}
    </div>;
  }

  function ThreadList({st, onMore, selected, onOpen}) {
    return <div className="mx-list" data-sb-out="">
      {st.loading && !st.threads.length ? <div className="hub-empty-state mx-pad">Loading...</div> : null}
      {!st.loading && !st.err && !st.threads.length ? <div className="hub-empty-state mx-pad">Nothing here.</div> : null}
      {st.threads.map((t) => <ThreadRow key={t.thread_id} t={t} active={t.thread_id === selected} onOpen={onOpen} />)}
      <MoreButton st={st} onMore={onMore} />
    </div>;
  }

  // ── thread panel ───────────────────────────────────────────────────────────

  const seenSum = new Map();  // thread id -> last summary shown this session (a stale marker needs it)
  const pickOf = (d) => ({MOVE: "move", KEEP: "keep", SECURITY_ALERT: "keep", DELETE: "delete"})[(d.action || "").toUpperCase()];
  const fullDate = (ms) => new Date(Number(ms)).toLocaleString([], {weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit"});
  const sizeText = (n) => n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : n >= 1024 ? `${Math.round(n / 1024)} KB` : `${n || 0} B`;
  const sendMsg = (r) => r.error || r.detail || r.state || "done";

  // The doc a message body renders in. Default-deny CSP plus base target: CSS imports, fonts, media,
  // frames and forms load nothing; images load on open (https, never http; he asked for no click, 2026-10-20).
  // The iframe sandbox (no scripts) is the second wall. It allows same-origin only so the page can read
  // the body's height and show the whole email with no inner scroller (mark 140045 #1, 2026-10-20,
  // "this should be fully expanded always"); with scripts blocked twice, nothing in the email can use it. The frame cannot see the
  // Hub type tokens, so the body keeps the browser default size (medium) under the email's own CSS.
  // Dark surface: the page goes clear (the card shows through) and the body is colour-inverted with hues kept,
  // images and background pictures inverted back so photos and logos stay true.
  // An email that ships its own dark styles (data-own) is never inverted; themeFrame switches those styles on instead.
  // ponytail: a regex sniff of the raw html; a dark query that styles almost nothing leaves the email's light colours on the dark card
  const ownsDark = (html) => /prefers-color-scheme\s*:\s*dark/i.test(html || "");
  const srcdocFor = (html) =>
    `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data: https:">` + (ownsDark(html) ? "<html data-own>" : "") +
    '<base target="_blank"><style>html{background:#fff;color:#111}body{margin:12px;font:medium/1.5 system-ui,sans-serif;overflow-wrap:break-word}img{max-width:100%;height:auto}' +
    // an inverted email's own white body still paints the canvas UNinverted; black there (white, inverted) stops it
    // fringing the card's rounded corner as a light arc (mark 095433 #1 "artifacting", 2026-10-22)
    'html[data-surface=dark]{background:transparent}html[data-surface=dark]:not([data-own]){background:#000}html[data-own][data-surface=dark]{color:#eee}' +
    'html[data-surface=dark]:not([data-own]) body,html[data-surface=dark]:not([data-own]) body :is(img,picture,video,svg,[background],[style*="url("]){filter:invert(1) hue-rotate(180deg)}' +
    'html[data-surface=dark]:not([data-own]) body :is(img,picture,video,svg,[background],[style*="url("]) :is(img,picture,video,svg,[background],[style*="url("]){filter:none}</style>' + inert(html);
  const surfaceOf = () => document.documentElement.getAttribute("data-surface") || "dark";
  // prefers-color-scheme inside the frame tracks the OS, not the Hub surface, so an own-dark email's scheme queries
  // are rewritten by hand: the one matching the surface becomes always-true, the other never-true
  const schemeQ = /\(\s*prefers-color-scheme\s*:\s*(dark|light)\s*\)/gi;
  const mediaOrig = new WeakMap();  // rule -> its media text as the email wrote it
  const themeFrame = (f) => {
    const d = f.contentDocument; if (!d) return;
    const s = surfaceOf(); d.documentElement.setAttribute("data-surface", s);
    if (!d.documentElement.hasAttribute("data-own")) return;
    const walk = (rules) => { for (const r of rules) {
      if (r.media && r.cssRules) {
        if (!mediaOrig.has(r)) mediaOrig.set(r, r.media.mediaText);
        const o = mediaOrig.get(r);
        if (/prefers-color-scheme/i.test(o)) r.media.mediaText = o.replace(schemeQ, (_q, c) => c.toLowerCase() === s ? "(min-width: 0px)" : "(max-width: 0px)");
      }
      if (r.cssRules) walk(r.cssRules);
    } };
    for (const sh of d.styleSheets) walk(sh.cssRules);
  };
  // a surface flip re-themes every open email in place, no reload
  document.addEventListener("hub:surfacechange", () => document.querySelectorAll("iframe.mx-frame").forEach(themeFrame));

  // CSP has no prefetch/preconnect/refresh coverage, so those tags are dropped in an inert DOMParser
  // document (it loads nothing) before the body is written into the srcdoc
  const inert = (html) => {
    const doc = new DOMParser().parseFromString(html, "text/html");
    doc.querySelectorAll("link, meta, base, script").forEach((n) => n.remove());
    return doc.documentElement.outerHTML;
  };

  // The frame wraps with break-word, so a table column is never squeezed to one character (an Uber total
  // stacked "$ 2 2 . 1 3", 2026-10-22). A run over 40 characters with no space (a printed link) still breaks
  // anywhere, or it would widen its table and shrink the whole email to fit.
  const breakLongRuns = (d) => {
    const w = d.createTreeWalker(d.body, NodeFilter.SHOW_TEXT);
    for (let n; (n = w.nextNode());) if (/\S{41}/.test(n.data) && n.parentElement) n.parentElement.style.overflowWrap = "anywhere";
  };

  // A sign-in or verification code in the subject or body, for the Copy code button. Anchored on a code keyword:
  // a token right after it ("code: 9Jul4l3M", "passcode is 2689"), a 4-8 digit run within 100 characters after it,
  // or a run just before "is your ... code" (UPS). Tuned on 3000 mirrored messages, 2026-10-23: 19 hits, Zoom
  // dial-in passcodes the only non-sign-in ones; promo and reward codes are left out on purpose.
  const codeOf = (m) => {
    let text = m.body_text;
    if (!text && m.body_html) {
      const doc = new DOMParser().parseFromString(m.body_html, "text/html");
      doc.querySelectorAll("style, script").forEach((n) => n.remove());
      text = doc.body ? doc.body.textContent : "";
    }
    const t = `${m.subject || ""}\n${text || m.snippet || ""}`.replace(/\s+/g, " ").slice(0, 4000);
    const key = /\b(?:verification|security|login|log-in|sign[- ]?in|one[- ]time|authentication|2fa|device|your)\s+(?:code|pin)\b|\bpass ?code\b|\bOTP\b/gi;
    for (let k; (k = key.exec(t));) {
      const after = t.slice(k.index + k[0].length, k.index + k[0].length + 100);
      const tight = /^\W{0,4}(?:is\W{0,3}|for \w+\W{1,3})?([A-Za-z0-9]{6,10})\b/.exec(after);
      if (tight && /\d/.test(tight[1]) && /^\d{4,8}$|[a-z].*[A-Z]|[A-Z].*[a-z]/.test(tight[1])) return tight[1];
      const colon = /^[^.]{0,60}?:\s*([A-Za-z0-9]{6,10})\b/.exec(after);
      if (colon && /\d/.test(colon[1]) && /[A-Za-z]/.test(colon[1])) return colon[1];
      const d = /(?<![\d$.,:\/#-])\b(\d{3}[- ]\d{3}|\d{4,8})\b(?![\d.,:\/%-])/.exec(after);
      if (d && !/^(19|20)\d\d$/.test(d[1])) return d[1].replace(/[- ]/g, "");
      const b = /\b(\d{4,8})\b\W{0,4}is your(?: [\w-]+){0,3}$/i.exec(t.slice(Math.max(0, k.index - 40), k.index + k[0].length));
      if (b) return b[1];
    }
    return null;
  };

  function CopyCode({code, className}) {
    const [said, setSaid] = useState(null);
    // clipboard is missing on a plain-http address, so the call sits inside the chain and fails soft
    const copy = () => Promise.resolve().then(() => navigator.clipboard.writeText(code)).then(() => setSaid("Copied"), () => setSaid("Copy failed"))
      .then(() => setTimeout(() => setSaid(null), 1500));
    return <button type="button" className={`hub-btn hub-btn--accent mx-head-btn ${className || ""}`} title="Copy the verification code" onClick={copy}>{said || `Copy ${code}`}</button>;
  }

  function Msg({m, first}) {
    const [open, setOpen] = useState(first);
    const code = useMemo(() => codeOf(m), [m]);
    const who = m.from_name || m.from_addr;
    // an email wider than the frame is zoomed down to fit, so neither axis ever scrolls (mark 223943 #2)
    // ponytail: measured on load only (images included); a window resize that rewraps the email is not re-measured
    const fit = (ev) => {
      const f = ev.target, d = f.contentDocument; if (!d) return;
      themeFrame(f); breakLongRuns(d); const e = d.documentElement;
      const z = Math.min(1, f.clientWidth / e.scrollWidth);
      e.style.zoom = z; f.style.height = `${e.scrollHeight}px`;
    };
    // the open newest message has no head row: the thread head above already names its sender and date,
    // and Hide floats as a glass pill over the email's top right (mark 222722 #1)
    const bare = first && open;
    // English under the original, one Haiku call per click (mark 095433 #2); a second click hides it
    const [tr, setTr] = useState(null);
    const translate = () => {
      if (tr && !tr.busy) { setTr(null); return; }
      setTr({busy: true}); setOpen(true);
      post(`/mail/api/message/${encodeURIComponent(m.id)}/translate`, {}).then((r) => setTr({text: r.text}), (e) => setTr({err: e.message}));
    };
    const trBtn = (cls) => <button type="button" className={`hub-btn mx-head-btn ${cls || ""}`} disabled={!!(tr && tr.busy)} onClick={translate}>
      {tr && tr.busy ? "Translating..." : tr ? "Hide English" : "Translate"}</button>;
    return <div className="hub-plate-card mx-msg">
      {bare ? null : <div className="hub-section-head">
        <span className="hub-section-head-t">{who}</span>
        <span className="hub-section-head-sum">{when(m.internal_date)}</span>
        {code ? <CopyCode code={code} /> : null}
        {trBtn()}
        <button type="button" className="hub-btn mx-head-btn" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Hide" : "Show"}</button>
      </div>}
      {!open ? <div className="mx-msg-snip">{m.snippet}</div> : <React.Fragment>
        <div className="mx-msg-main">
          {m.body_html
            ? <div className="mx-body"><iframe className="mx-frame" title={`Message from ${who}`} sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox" onLoad={fit} srcDoc={srcdocFor(m.body_html)} /></div>
            : <div className="mx-msg-text">{m.body_text}</div>}
          {bare ? <div className="mx-float-acts">
            {code ? <CopyCode code={code} className="mx-hide" /> : null}
            {trBtn("mx-hide")}
            <button type="button" className="hub-btn mx-head-btn mx-hide" aria-expanded={true} onClick={() => setOpen(false)}>Hide</button>
          </div> : null}
        </div>
        {tr && !tr.busy ? <div className="mx-tr">
          <div className="hub-detail-card-head">English</div>
          {tr.err ? <p className="hub-error">{tr.err}</p> : <div className="mx-tr-text">{tr.text}</div>}
        </div> : null}
        {(m.attachments || []).length ? <div className="mx-atts">{m.attachments.map((a) => a.attachmentId
          ? <a key={a.attachmentId} className="hub-link-chip" href={`/mail/api/attachment/${encodeURIComponent(m.id)}/${encodeURIComponent(a.attachmentId)}`}>{a.filename || "attachment"} ({sizeText(a.size)})</a>
          : null)}</div> : null}
      </React.Fragment>}
    </div>;
  }

  const SCOPE_SAID = {once: "this email only", standing: "proposed as a rule", both: "this email and a rule"};
  const SCOPE_BTN = {once: "This email only", standing: "A rule", both: "Both"};

  // the waiting sort decision, with every action /automations offered
  function Decision({d, extra, names, busy, run}) {
    const [fold, setFold] = useState(null), [note, setNote] = useState("");
    const a = (d.action || "").toUpperCase();
    const rec = pickOf(d);
    const x = extra || {};
    const folder = names.indexOf(fold) >= 0 ? fold : names.indexOf(d.label) >= 0 ? d.label : names[0];
    const cls = (act) => act === rec ? "hub-btn--accent" : act === "delete" ? "hub-btn--danger" : "";
    const send = (action) => {
      const n = note.trim() || undefined;
      if (action === "note" && !n) { run(d.id, null, "Type a note first"); return; }
      run(d.id, {action, label: action === "move" ? folder || "" : undefined, note: n});
    };
    const b = (action, text, c) => <button type="button" className={`hub-btn ${c}`} disabled={busy} onClick={() => send(action)}>{text}</button>;
    if (d.note) {
      const sc = d.note_scope;
      const said = sc ? SCOPE_SAID[sc] : (d.note_tries || 0) >= 3 ? "couldn't judge, pick one" : "judging what it covers";
      const pick = (s) => <button key={s} type="button" className={`hub-btn mx-head-btn ${s === sc ? "hub-btn--accent" : ""}`} disabled={busy || !d.note_id}
        onClick={() => run(d.id, {scope: s, note_id: d.note_id})}>{SCOPE_BTN[s]}</button>;
      return <div className="hub-detail-card mx-card"><div className="hub-detail-card-head">Sort decision</div>
        <p className="mx-p"><span className="hub-pill mx-chip">Note sent</span> Your note: {d.note}</p>
        <p className="mx-cost">Reads as: {said}</p>
        <div className="mx-acts">{["once", "standing", "both"].map(pick)}</div>
        <p className="mx-cost">{sc === "standing" ? "A rule waits on the Automations rules tab; this email still waits for your answer."
          : "The next /gmail run carries it out."}</p></div>;
    }
    let go = null;
    if (d.state === "unconfirmed") go = b("unsubscribed", "Done, unsubscribed", "hub-btn--accent");
    else if (a === "UNSUBSCRIBE" && x.unsub_safe) go = b("unsubscribe", "Unsubscribe", "hub-btn--accent");
    else if (x.wants_read) go = b("read", "Read, then trash", "hub-btn--accent");
    const link = d.state === "unconfirmed" && /^https:\/\//i.test(d.unsub_url || "")
      ? <p className="mx-p">Finish it in a browser: <a href={d.unsub_url} target="_blank" rel="noopener noreferrer">unsubscribe page</a></p>
      : a === "UNSUBSCRIBE" && !x.unsub_safe && d.unsub_url ? <p className="mx-p">Unsubscribe link not checked, not linked: {d.unsub_url}</p> : null;
    const chip = d.state === "unconfirmed" ? "Unsubscribe not confirmed" : a === "UNSUBSCRIBE" ? "Unsubscribe" : a === "DELETE" ? "Delete" : a === "MOVE" ? `Move to ${d.label}` : "Your call";
    return <div className="hub-detail-card mx-card">
      <div className="mx-dec"><span className="hub-detail-card-head">Sort decision</span><span className="hub-pill mx-chip is-low">{chip}</span>
        <span className="mx-dim">{rec ? `Claude's pick: ${rec}${rec === "move" && d.label ? ` to ${d.label}` : ""}` : "Claude has no pick"}</span></div>
      {d.reason ? <p className="mx-p mx-why"><b>Why Claude stopped:</b> {d.reason}</p> : null}
      {link}
      {go ? <div className="hub-btn-row mx-wrap">{go}</div> : null}
      <div className="mx-noterow"><input className="hub-input" maxLength={2000} placeholder="Other..." aria-label="Other answer" value={note} disabled={busy}
        onChange={(ev) => setNote(ev.target.value)} onKeyDown={(ev) => { if (ev.key === "Enter" && !busy) send("note"); }} />{b("note", "Send note", "")}</div>
      <div className="mx-fold">
        <select className="hub-input" aria-label="Folder to move to" value={folder || ""} disabled={busy} onChange={(ev) => setFold(ev.target.value)}>
          {names.map((l) => <option key={l}>{l}</option>)}</select>
        <div className="hub-btn-row mx-wrap">{b("move", "File to folder", cls("move"))}{b("keep", "Keep in inbox", cls("keep"))}{b("delete", "Delete", cls("delete"))}</div>
      </div>
    </div>;
  }

  // runs on its own, outside the panel's one-request guard, so the open-time summary never greys out Archive or Move
  function SummaryCard({id, server}) {
    const [fresh, setFresh] = useState(null), [busy, setBusy] = useState(false), [err, setErr] = useState(null);
    const s = fresh || server;  // "Summarize again" must replace the one the page loaded with
    const old = !s ? seenSum.get(id) : null;
    const shown = s || old;
    const go = () => {
      setBusy(true); setErr(null);
      post(`/mail/api/thread/${encodeURIComponent(id)}/summary`, {}).then((r) => { seenSum.set(id, r); setFresh(r); })
        .catch((e) => setErr(e.message)).then(() => setBusy(false));
    };
    useEffect(() => { if (!s) go(); }, []);  // the first summary writes itself; the button only redoes it
    return <div className="hub-detail-card mx-card">
      <div className="hub-detail-card-head">Summary</div>
      {old ? <p className="mx-p"><span className="hub-pill mx-chip is-low">Out of date</span> New mail arrived since this was written.</p> : null}
      {shown ? <React.Fragment>
        <ul className="mx-bul">{(shown.bullets || []).map((b, i) => <li key={i}>{b}</li>)}</ul>
        {shown.needs ? <p className="mx-need"><b>Needs from you:</b> {shown.needs}</p> : null}
        {shown.cut ? <p className="mx-cost">Older messages were left out.</p> : null}
      </React.Fragment> : null}
      {err ? <p className="hub-error">{err}</p> : null}
      <div className="hub-btn-row"><button type="button" className="hub-btn" disabled={busy} onClick={go}>{busy ? "Summarizing..." : shown ? "Summarize again" : "Summarize"}</button></div>
    </div>;
  }

  const autoDrafts = new Map();  // thread id -> the draft written on open this session, or "skip" (one model call per thread)

  function DraftCard({id, busy, run, err, setDirty, bin}) {
    const [instr, setInstr] = useState(""), [draft, setDraft] = useState(null), [draftId, setDraftId] = useState(null), [saved, setSaved] = useState(false);
    const [auto, setAuto] = useState(false), [notes, setNotes] = useState("");
    const base = `/mail/api/thread/${encodeURIComponent(id)}`;
    const edit = (k, v) => { const n = {to: draft.to, subject: draft.subject, body: draft.body}; n[k] = v; setDraft(n); setDirty(true); setSaved(false); setAuto(false); };
    const make = () => run("draft", () => post(`${base}/draft`, {instruction: instr}).then((r) => { setDraft(r); setDirty(true); setSaved(false); setAuto(false); }));
    // sent back with notes: the current draft is revised, not started over (mark 094537 #1)
    const redo = () => run("draft", () => post(`${base}/draft`, {instruction: notes, previous: draft.body}).then((r) => {
      setDraft({to: draft.to, subject: draft.subject, body: r.body}); setNotes(""); setDirty(true); setSaved(false); setAuto(false); }));
    // opening a thread writes the likely reply on its own, outside the panel's one-request guard. It stays a
    // preview: not dirty (switching threads drops it without asking) and never in Gmail until he saves.
    const [autoBusy, setAutoBusy] = useState(false);
    useEffect(() => {
      if (bin) return;
      const had = autoDrafts.get(id);
      if (had) { if (had !== "skip") { setDraft(had); setAuto(true); } return; }
      setAutoBusy(true);
      post(`${base}/draft`, {auto: true}).then((r) => {
        autoDrafts.set(id, r.skipped ? "skip" : r);
        if (!r.skipped) setDraft((d) => { if (d) return d; setAuto(true); return r; });  // a draft he asked for meanwhile wins
      }, () => {}).then(() => setAutoBusy(false));
    }, [id]);
    const save = () => run("save", () => post(`${base}/draft/save`, {to: draft.to, subject: draft.subject, body: draft.body, draft_id: draftId || undefined})
      .then((r) => { setDraftId(r.draft_id); setDirty(false); setSaved(true); }));
    // once it is a Gmail draft, edits save themselves 1.5s after typing stops (mark 094537 #1: "verify this
    // auto saves"; it did not). The first save stays a click, so nothing lands in Gmail he did not ask for.
    useEffect(() => {
      if (!draftId || saved || !draft || busy) return;
      const t = setTimeout(save, 1500);
      return () => clearTimeout(t);
    }, [draft, draftId, saved]);
    return <div className="hub-detail-card mx-card">
      <div className="hub-detail-card-head">Draft reply</div>
      <div className="hub-field"><label htmlFor="mxInstr">What should it say?</label>
        <textarea id="mxInstr" className="hub-input mx-ta" rows={2} value={instr} disabled={busy} placeholder="Ask for the new departure time before I accept" onChange={(ev) => setInstr(ev.target.value)} /></div>
      <div className="hub-btn-row"><button type="button" className="hub-btn hub-btn--accent" disabled={busy || !instr.trim()} onClick={make}>{busy === "draft" ? "Drafting..." : draft ? "Draft again" : "Draft reply"}</button></div>
      {autoBusy && !draft ? <p className="mx-cost">Writing a likely reply...</p> : null}
      {auto && draft ? <p className="mx-cost">Claude wrote this when you opened the email. Nothing is saved until you save it.</p> : null}
      {draft ? <React.Fragment>
        <div className="hub-field"><label htmlFor="mxTo">To</label><input id="mxTo" className="hub-input" value={draft.to} onChange={(ev) => edit("to", ev.target.value)} /></div>
        <div className="hub-field"><label htmlFor="mxSub">Subject</label><input id="mxSub" className="hub-input" value={draft.subject} onChange={(ev) => edit("subject", ev.target.value)} /></div>
        <div className="hub-field"><label htmlFor="mxBody">Body</label><textarea id="mxBody" className="hub-input mx-ta mx-ta-body" rows={8} value={draft.body} onChange={(ev) => edit("body", ev.target.value)} /></div>
        <div className="mx-noterow"><input className="hub-input" maxLength={2000} placeholder="Notes for a new version..." aria-label="Notes for a new version of the draft" value={notes} disabled={!!busy}
          onChange={(ev) => setNotes(ev.target.value)} onKeyDown={(ev) => { if (ev.key === "Enter" && notes.trim() && !busy) redo(); }} />
          <button type="button" className="hub-btn" disabled={!!busy || !notes.trim()} onClick={redo}>{busy === "draft" ? "Revising..." : "Send back"}</button></div>
        <div className="hub-btn-row"><button type="button" className="hub-btn hub-btn--accent" disabled={busy} onClick={save}>{busy === "save" ? "Saving..." : draftId ? "Update draft" : "Save to drafts"}</button></div>
        {saved ? <p className="mx-p">Saved to Gmail drafts.{draftId ? " Edits save on their own." : ""}</p> : null}
      </React.Fragment> : null}
      {err ? <p className="hub-error">{err}</p> : null}
    </div>;
  }

  function ThreadBody({id, hint, labels, onChanged, say, bin}) {
    const [data, setData] = useState(null), [err, setErr] = useState(null), [busy, setBusy] = useState(""), [errs, setErrs] = useState({});
    const [extras, setExtras] = useState({}), [feedNames, setFeedNames] = useState(null), [movePick, setMovePick] = useState(false), [dirty, setDirty] = useState(false);
    const base = `/mail/api/thread/${encodeURIComponent(id)}`;
    // opened from Spam or Trash it reads the binned messages; a thread gone from the mirror drops its stale copy
    const load = () => J(bin ? `${base}?bin=1` : base).then((d) => { setData(d); setErr(null); return d; })
      .catch((e) => { setErr(e.message); if (e.message === "no such thread") setData(null); return null; });
    // opening a thread marks it read, like Gmail (he asked 2026-10-20); silent, a failure only leaves it unread
    useEffect(() => {
      load().then((d) => {
        const unread = d ? d.messages.filter((m) => m.label_ids.includes("UNREAD")).map((m) => m.id) : [];
        if (unread.length) post(`${base}/act`, {action: "read", message_ids: unread}).then(() => { onChanged(); load(); }, () => {});
      });
    }, [id]);
    // the decision card's flags (unsub_safe, wants_read) and its folder names come from the read-only automations feed
    const nDec = data ? data.decisions.length : 0;
    useEffect(() => {
      if (!nDec) return;
      J("/automations/api/feed").then((f) => {
        const m = {};
        (f.waiting || []).concat(f.noted || []).forEach((i) => { m[i.id] = i; });
        setExtras(m); setFeedNames(f.labels || []);
      }).catch(() => {});
    }, [nDec, id]);
    useEffect(() => {
      if (!dirty) return;
      const h = (ev) => { ev.preventDefault(); ev.returnValue = ""; };
      window.addEventListener("beforeunload", h);
      window.MailUI.draftDirty = true;  // openRow asks before another thread replaces this one
      return () => { window.removeEventListener("beforeunload", h); window.MailUI.draftDirty = false; };
    }, [dirty]);

    const userNames = labels.filter((l) => l.type === "user").map((l) => l.name);
    const names = feedNames && feedNames.length ? feedNames : userNames;
    const ids = data ? data.messages.map((m) => m.id) : [];
    const setE = (k, v) => setErrs((e) => { const n = {}; Object.keys(e).forEach((j) => { n[j] = e[j]; }); n[k] = v; return n; });

    // one request at a time; the buttons stay disabled until it settles
    const guarded = (key, fn, after) => {
      if (busy) return Promise.resolve();
      setBusy(key); setE(key, null);
      return fn().then(() => after && after()).catch((e) => { setE(key, e.message); say(e.message); }).then(() => setBusy(""));
    };
    const act = (action, label, done) => guarded("act", () => post(`${base}/act`, {action, message_ids: ids, label}),
      () => { say(done); setMovePick(false); onChanged(); return load(); });
    const decide = (itemId, body, msg) => {
      if (!body) { say(msg); return; }
      if (body.scope) {  // a note's reach, re-picked: changes the proposed rule, never the email
        guarded("dec", () => post(`/automations/api/note/${body.note_id}/scope`, {scope: body.scope}).then(() => say("Saved")),
          () => { onChanged(); return load(); });
        return;
      }
      guarded("dec", () => fetch(`/mail/api/decision/${itemId}`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)})
        .then((r) => r.json().then((d) => ({ok: r.ok, status: r.status, d}), () => ({ok: false, status: r.status, d: {}})))
        .then((r) => {
          if (r.status === 409) { say("Already handled; reloaded"); return; }
          if (!r.ok) throw new Error(sendMsg(r.d || {}) === "done" ? `HTTP ${r.status}` : sendMsg(r.d));
          say(sendMsg(r.d));
        }), () => { onChanged(); return load(); });
    };
    const run = (key, fn) => guarded(key, fn);
    // Reply glides down to the draft box and puts the cursor in it (mark 221413 #5)
    const toReply = () => {
      const ta = $("mxInstr");
      if (!ta) return;
      const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      ta.scrollIntoView({behavior: still ? "auto" : "smooth", block: "center"});
      ta.focus({preventScroll: true});
    };

    if (err && !data) return err === "no such thread"
      ? <Empty t="Thread gone" x="It was archived, trashed or moved since the list loaded. Pick another on the left." />
      : <div className="hub-empty-state">{err}</div>;
    if (!data) return <div className="hub-empty-state">Loading...</div>;
    const msgs = data.messages.slice().reverse();  // newest first, newest open
    const last = msgs[0];
    const subj = (last && last.subject) || hint || "(no subject)";
    const off = !!busy;
    // in a bin (or once everything here is trashed) Move and Trash go: a moved message would keep its TRASH label
    const binned = bin || data.messages.every((m) => m.label_ids.some((l) => BIN[l]));
    // one decision at a time, never stacked: the newest email's; the next shows once it is settled
    const dec = data.decisions.slice().sort((a, b) => (b.received_at || "").localeCompare(a.received_at || ""))[0];
    return <React.Fragment>
      <div className="hub-t3p-read-head">
        <h2 className="hub-t3p-read-title">{subj}</h2>
        {last ? <div className="hub-t3p-read-meta"><b>{last.from_name || last.from_addr}</b> {last.from_name ? <span className="hub-pill mx-addr" title={last.from_addr}><span>{last.from_addr}</span></span> : null} <span className="mx-dim">{plural(msgs.length, "message")} · {fullDate(last.internal_date)}</span></div> : null}
        <div className="hub-btn-row">
          <button type="button" className="hub-btn hub-btn--accent" onClick={toReply}>Reply</button>
          {binned ? null : <React.Fragment>
            <button type="button" className="hub-btn" disabled={off} aria-expanded={movePick} onClick={() => setMovePick(!movePick)}>Move</button>
            <button type="button" className="hub-btn hub-btn--danger" disabled={off} onClick={() => act("trash", undefined, "Trashed")}>Trash</button>
          </React.Fragment>}
        </div>
        {movePick && !binned ? <select className="hub-input" aria-label="Move to label" defaultValue="" disabled={off}
          onChange={(ev) => { if (ev.target.value) act("move", ev.target.value, "Moved"); }}>
          <option value="">Pick a label...</option>
          {labels.filter((l) => l.type === "user").map((l) => <option key={l.id} value={l.id}>{shown(l.name)}</option>)}</select> : null}
        {errs.act ? <p className="hub-error">{errs.act}</p> : null}
      </div>
      <div className="hub-t3p-read-stack">
        <SummaryCard id={id} server={data.summary} />
        {msgs.map((m, i) => <Msg key={m.id} m={m} first={i === 0} />)}
        <DraftCard id={id} busy={busy === "draft" ? "draft" : busy === "save" ? "save" : off ? "other" : ""} run={run} err={errs.draft || errs.save} setDirty={setDirty} bin={binned} />
        {errs.dec ? <p className="hub-error">{errs.dec}</p> : null}
        {dec ? <div className="hub-t3p-read-float mx-float"><Decision key={dec.id} d={dec} extra={extras[dec.id]} names={names} busy={busy === "dec"} run={decide} /></div> : null}
      </div>
    </React.Fragment>;
  }

  // the reading pane with nothing in it: an envelope, a title and one line, centred in the panel
  function Empty({t, x}) {
    return <div className="mx-empty">
      <svg className="mx-empty-g" viewBox="0 0 48 48" aria-hidden="true"><rect x="6" y="11" width="36" height="26" rx="4" /><path d="M7.5 13.5 L24 26 L40.5 13.5" /></svg>
      <div className="mx-empty-t">{t}</div>
      <div className="mx-empty-x">{x}</div>
    </div>;
  }

  function ThreadPanel({id, hint, open, onBack, labels, onChanged, say, bin}) {
    return <section className={`hub-detail-rail hub-slide-over${open ? " is-open" : ""}`}>
      <button type="button" className="hub-slide-over-close" aria-label="Back to the list" onClick={onBack}>&larr; Back</button>
      <div className="hub-detail-rail-inner hub-t3p-context hub-t3p-read mx-thread">
        {/* wide screens: a chevron on the email closes it and the list slides back over (send-back on mark 224420 #3) */}
        {/* kept while closing so it leaves with the pane instead of vanishing first */}
        {id ? <button type="button" className="hub-btn hub-t3p-reader-close" aria-label="Close this email" title="Close" onClick={onBack}>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6 L15 12 L9 18" /></svg></button> : null}
        {id ? <ThreadBody key={`${id}|${bin ? 1 : 0}`} id={id} hint={hint} labels={labels} onChanged={onChanged} say={say} bin={bin} /> : <Empty t="No thread open" x="Pick one from the list to read it here." />}
      </div>
    </section>;
  }

  // ── page ───────────────────────────────────────────────────────────────────

  function setDrawer(open) {
    const rail = $("mxCol"), scrim = $("mxScrim"), toggle = $("navToggle");
    if (!rail) return;
    rail.classList.toggle("is-open", open);
    if (scrim) scrim.hidden = !open;
    if (toggle) toggle.setAttribute("aria-expanded", String(open));
  }

  // ── Brief ──────────────────────────────────────────────────────────────────
  // Picked layout: Workbench set mail-brief-layout, 2026-11-09, option C "Headlines that open in place".
  // One line per entry under day headers; each opens in place to its points, links, the sender's Read /
  // Unsubscribe choice and Delete. Entries / Trash switch; the server purges deleted entries after 30 days.

  const dayName = (iso) => {
    const d = new Date(iso), n = new Date(), y = new Date(n.getFullYear(), n.getMonth(), n.getDate() - 1);
    const base = d.toLocaleDateString([], {weekday: "short", month: "short", day: "numeric"});
    if (d.toDateString() === n.toDateString()) return `Today · ${base}`;
    if (d.toDateString() === y.toDateString()) return `Yesterday · ${base}`;
    return base;
  };
  const clock = (iso) => new Date(iso).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"});
  const safeUrl = (u) => /^https?:\/\//i.test(u || "");

  function Brief({say, onCount}) {
    const [trash, setTrash] = useState(false);
    const [st, setSt] = useState({data: null, err: null});
    const [picks, setPicks] = useState({});  // domain -> the sender answer from this visit
    const seq = useRef(0);  // only the newest request may land: a slow Trash reply must not fill Entries
    const load = () => {
      const n = ++seq.current;
      return J(`/mail/api/brief?trash=${trash ? 1 : 0}`)
        .then((d) => { if (n === seq.current) { setSt({data: d.entries, err: null}); onCount(d.count); } })
        .catch((e) => { if (n === seq.current) setSt((s) => ({data: s.data, err: e.message})); });
    };
    useEffect(() => { setSt({data: null, err: null}); load(); }, [trash]);

    const mark = (e, what) => post(`/mail/api/brief/${e.id}/${what}`, {})
      .then(() => { say(what === "delete" ? "Moved to Brief trash" : "Restored"); return load(); })
      .catch((x) => say(x.message));
    const setPick = (domain, r) => setPicks((p) => { const n = Object.assign({}, p); n[domain] = r; return n; });
    const pick = (e, choice) => post("/mail/api/brief/sender", {domain: e.domain, choice})
      .then((r) => {
        setPick(e.domain, r);
        if (r.detail === "unsafe") say("That unsubscribe link looked unsafe; nothing was sent");
      }).catch((x) => say(x.message));
    const done = (e) => post("/mail/api/brief/sender/done", {domain: e.domain})
      .then((r) => setPick(e.domain, {choice: r.choice, unsub_state: r.unsub_state})).catch((x) => say(x.message));

    const list = st.data || [];
    const rows = [];
    let last = "";
    list.forEach((e) => {
      const day = dayName(e.received_at);
      if (day !== last) { rows.push(<div key={`d${e.id}`} className="bx-day">{day}</div>); last = day; }
      const p = picks[e.domain] || {choice: e.choice, unsub_state: e.unsub_state};
      const fb = e.source === "fallback";
      rows.push(<details key={e.id} className="bx-acc">
        <summary className="bx-acc-s">
          <span className="bx-acc-t"><b>{e.title}</b><i>{fb || !e.points.length ? "Summary unavailable" : e.points[0]}</i></span>
          <span className="bx-acc-m"><span className="bx-from">{e.sender}</span><span className="mx-row-time">{clock(e.received_at)}</span></span>
        </summary>
        <div className="bx-acc-b">
          {fb ? <p className="bx-fb">Summary unavailable, showing the lane's note.</p> : null}
          {e.points.length ? <ul className="bx-pts">{e.points.map((t, i) => <li key={i}>{t}</li>)}</ul> : null}
          {e.links.some((l) => safeUrl(l.url))
            ? <div className="bx-links">{e.links.filter((l) => safeUrl(l.url)).map((l, i) =>
              <a key={i} className="hub-btn bx-link" href={l.url} target="_blank" rel="noopener noreferrer">{l.label} <span className="bx-host">{l.host}</span></a>)}</div>
            : <p className="bx-none">No links worth keeping in this email.</p>}
          <div className="bx-card-f">
            <div className="bx-pick">
              <span className="bx-pick-l">Everything from <b>{e.domain}</b></span>
              <div className="hub-tabs hub-tabs--segmented mx-seg" role="tablist" aria-label={`What to do with mail from ${e.domain}`}>
                <button type="button" role="tab" aria-selected={p.choice !== "unsub"} className={`hub-tab${p.choice !== "unsub" ? " active" : ""}`} onClick={() => pick(e, "read")}>Read</button>
                <button type="button" role="tab" aria-selected={p.choice === "unsub"} className={`hub-tab is-unsub${p.choice === "unsub" ? " active" : ""}`} onClick={() => pick(e, "unsub")}>Unsubscribe</button>
              </div>
              {p.choice === "unsub" && p.unsub_state === "done"
                ? <p className="bx-unsub">Unsubscribed. New mail from {e.domain} is trashed with no entry; these stay until you delete them.</p> : null}
              {p.choice === "unsub" && p.unsub_state !== "done"
                ? <p className="bx-unsub">Unsubscribe not confirmed yet. New mail from {e.domain} is trashed with no entry.
                  {p.url && safeUrl(p.url) ? <React.Fragment> <a className="hub-btn bx-link" href={p.url} target="_blank" rel="noopener noreferrer">Open unsubscribe page</a></React.Fragment> : null}
                  {" "}<button type="button" className="hub-btn" onClick={() => done(e)}>Done</button></p> : null}
            </div>
            {trash
              ? <button type="button" className="hub-btn" onClick={() => mark(e, "restore")}>Restore</button>
              : <button type="button" className="hub-btn hub-btn--danger" onClick={() => mark(e, "delete")}>Delete</button>}
          </div>
        </div>
      </details>);
    });

    return <div className="hub-split hub-t3p-split is-reader mx-split is-empty">
      <div className="hub-pane-col hub-t3p-list-col">
        <div className="hub-pane-head hub-t3p-head mx-list-h">
          <b>{trash ? "Brief trash" : "Brief"}</b><span className="mx-dim">{st.data && list.length ? list.length : ""}</span>
          <div className="mx-list-ctl">
            <div className="hub-tabs hub-tabs--segmented mx-seg" role="tablist" aria-label="Brief or its trash">
              <button type="button" role="tab" aria-selected={!trash} className={`hub-tab${trash ? "" : " active"}`} onClick={() => setTrash(false)}>Entries</button>
              <button type="button" role="tab" aria-selected={trash} className={`hub-tab${trash ? " active" : ""}`} onClick={() => setTrash(true)}>Trash</button>
            </div>
          </div>
        </div>
        {trash ? <p className="bx-trashline">Deleted entries clear 30 days after you delete them.</p> : null}
        <div className="mx-list bx-list" data-sb-out="">
          {st.err && !st.data ? <Empty t="Could not load the Brief" x={st.err} />
            : !st.data ? null
            : list.length ? <div className="bx-col">{rows}</div>
            : <Empty t={trash ? "Brief trash is empty" : "Nothing in the Brief"} x={trash ? "Deleted entries wait here for 30 days, then clear." : "Newsletters the lane trashes land here."} />}
        </div>
      </div>
      <div className="hub-t3p-side" />
    </div>;
  }

  function Body() {
    const first = useRef(readUrl());
    const [label, setLabel] = useState(first.current.label);
    const [sender, setSender] = useState(first.current.sender);
    const [openKeys, setOpenKeys] = useState(() => new Set(first.current.sender ? [first.current.sender] : []));
    const [q, setQ] = useState("");
    const [qLive, setQLive] = useState("");
    const [from, setFrom] = useState(null);  // {key, name}: the picked sender, kept across tabs
    const [scope, setScope] = useState(null);  // {id, name}: an in: pick; a search without one covers All
    const [mode, setMode] = useState(readMode);
    const [rev, setRev] = useState(0);
    const [briefN, setBriefN] = useState(0);
    const [labels, setLabels] = useState([]);
    const [senders, setSenders] = useState({data: null, err: null});
    const [status, setStatus] = useState({loaded: false, synced_at: null});
    const [, setTick] = useState(0);
    const [openId, setOpenId] = useState(null);
    const [panelOpen, setPanelOpen] = useState(false);
    const [note, setNote] = useState("");
    const [syncing, setSyncing] = useState(false);
    const known = useRef(new Map());

    // a search runs over All (or its In chip) whatever tab is open; a From chip alone keeps the tab
    const eff = qLive || scope ? (scope ? scope.id : "ALL") : label;
    const params = {label: eff, q: qLive, from: from ? from.key : undefined};
    const inBrief = eff === "BRIEF";
    const [newest, moreNewest] = useThreads(params, mode === "newest" && !inBrief, rev);

    // select a thread by id and show its panel
    const openThread = (id) => { setOpenId(id); setPanelOpen(true); };
    const openRow = (t) => {
      if (t.thread_id !== openId && window.MailUI.draftDirty && !window.confirm("Drop the unsaved draft reply?")) return;
      known.current.set(t.thread_id, t); openThread(t.thread_id);
    };
    window.MailUI.openThread = openThread;
    newest.threads.forEach((t) => known.current.set(t.thread_id, t));

    const changed = () => setRev((r) => r + 1);
    const say = (s) => setNote(s);
    // an outcome line gives the status bar back to the label count after a few seconds
    useEffect(() => { if (!note) return; const h = setTimeout(() => setNote(""), 4000); return () => clearTimeout(h); }, [note]);

    useEffect(() => {
      $("pane").setAttribute("data-react-mounted", "mail");
      const toggle = $("navToggle"), rail = $("mxCol"), scrim = $("mxScrim");
      const flip = () => setDrawer(!rail.classList.contains("is-open"));
      const shut = () => setDrawer(false);
      if (toggle && rail && scrim) { toggle.addEventListener("click", flip); scrim.addEventListener("click", shut); }
      return () => { if (toggle) toggle.removeEventListener("click", flip); if (scrim) scrim.removeEventListener("click", shut); };
    }, []);

    // search is debounced so a typed word is one query, not one per key
    useEffect(() => { const h = setTimeout(() => setQLive(keywords(q)), 250); return () => clearTimeout(h); }, [q]);

    useEffect(() => { writeUrl(label, sender); }, [label, sender]);

    // labels and the synced-ago line refresh on every change and on a timer
    const loadStatus = () => J("/mail/api/status").then((d) => setStatus({loaded: true, synced_at: d.synced_at})).catch(() => setStatus((s) => ({loaded: s.loaded, synced_at: s.synced_at})));
    useEffect(() => { J("/mail/api/labels").then(setLabels).catch(() => {}); loadStatus(); }, [rev]);
    useEffect(() => {
      const h = setInterval(() => { loadStatus(); setTick((n) => n + 1); }, 30000);
      return () => clearInterval(h);
    }, []);

    useEffect(() => { J("/mail/api/brief").then((d) => setBriefN(d.count)).catch(() => {}); }, []);

    useEffect(() => {
      if (mode !== "sender" || inBrief) return;
      let live = true;
      const p = new URLSearchParams();
      p.set("label", eff);
      if (qLive) p.set("q", qLive);
      if (from) p.set("from", from.key);
      J(`/mail/api/senders?${p.toString()}`).then((d) => { if (live) setSenders({data: d, err: null}); })
        .catch((e) => { if (live) setSenders((s) => ({data: s.data, err: e.message})); });
      return () => { live = false; };
    }, [mode, eff, qLive, from && from.key, rev]);

    // a tab leaves the search: the keyword and the In chip go, the From chip stays
    const pickLabel = (id) => {
      setQ(""); setQLive(""); setScope(null);
      setLabel(id); setSender(""); setOpenKeys(new Set()); setSenders({data: null, err: null}); setDrawer(false);
    };
    const pickMode = (m) => { saveMode(m); setMode(m); };
    const toggleSender = (key, open) => {
      setOpenKeys((s) => { const n = new Set(s); if (open) n.add(key); else n.delete(key); return n; });
      setSender((cur) => open ? key : cur === key ? "" : cur);
    };
    const refresh = () => {
      setSyncing(true);
      post("/mail/api/sync", {}).then(() => say("Synced"))
        .catch((e) => say(`Sync failed: ${e.message}`))
        .then(() => { setSyncing(false); changed(); });
    };

    const labelName = shown((TABS.find((f) => f[0] === eff) || [0, (labels.find((l) => l.id === eff) || {name: eff}).name])[1]);
    const nThreads = mode === "sender" ? (senders.data || []).reduce((n, g) => n + g.threads, 0) : newest.threads.length;
    const countLine = inBrief ? `${briefN} ${briefN === 1 ? "entry" : "entries"}` : mode === "sender"
      ? (senders.data ? `${plural(senders.data.length, "sender")} · ${plural(nThreads, "thread")}` : "")
      : `${nThreads}${newest.cursor ? "+" : ""} ${nThreads === 1 && !newest.cursor ? "thread" : "threads"}`;

    const mins = minutesSince(status.synced_at);
    const stale = status.loaded && (mins === null || mins > STALE_MIN);
    useEffect(() => { $("crumbSection").textContent = labelName; }, [labelName]);
    useEffect(() => { $("statusMsg").textContent = note || `${labelName}${countLine ? ` · ${countLine}` : ""}`; }, [note, labelName, countLine]);
    useEffect(() => {
      const el = $("statusMeta");
      el.textContent = status.loaded ? agoText(mins) : "";
      el.classList.toggle("is-stale", !!stale);
    }, [status, mins, stale]);

    const openThreadObj = openId ? known.current.get(openId) || {subject: ""} : null;

    return <React.Fragment>
      {ReactDOM.createPortal(<Rail labels={labels} label={eff} onPick={pickLabel} q={q} onQ={setQ} from={from} scope={scope} onScope={setScope} briefN={briefN}
        onFrom={(f) => { setFrom(f); setOpenKeys(new Set(f ? [f.key] : [])); setSenders({data: null, err: null}); }} />, $("mxCol"))}
      {/* with no thread open the list takes the page; picking one slides the thread in (mark 224420 #3) */}
      {inBrief ? <Brief say={say} onCount={setBriefN} /> : null}
      {inBrief ? null : <div className={`hub-split hub-t3p-split is-reader mx-split${panelOpen && openId ? "" : " is-empty"}`}>
        <div className="hub-pane-col hub-t3p-list-col">
          <div className="hub-pane-head hub-t3p-head mx-list-h">
            <b title={labelName}>{labelName.split("/").pop()}</b>
            <span className="mx-dim">{nThreads ? `${nThreads}${mode === "newest" && newest.cursor ? "+" : ""}` : ""}</span>
            <div className="mx-list-ctl">
            <div className="hub-tabs hub-tabs--segmented mx-seg" role="tablist" aria-label="List order">
              <button type="button" role="tab" aria-selected={mode === "newest"} className={`hub-tab${mode === "newest" ? " active" : ""}`} onClick={() => pickMode("newest")}>Newest</button>
              <button type="button" role="tab" aria-selected={mode === "sender"} className={`hub-tab${mode === "sender" ? " active" : ""}`} onClick={() => pickMode("sender")}>By sender</button>
            </div>
            <button type="button" className={`hub-btn mx-refresh${syncing ? " is-busy" : ""}`} disabled={syncing} onClick={refresh}
              aria-label={syncing ? "Syncing" : "Refresh"} title={syncing ? "Syncing..." : "Refresh"}>
              <svg className="mx-ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3" /><path d="M19.8 4.2v4.6h-4.6" /></svg>
            </button>
            </div>
          </div>
          {mode === "sender"
            ? <SenderList senders={senders} params={params} rev={rev} openKeys={openKeys} onToggle={toggleSender}
                selected={openId} onOpen={openRow} onChanged={changed} say={say} />
            : <ThreadList st={newest} onMore={moreNewest} selected={openId} onOpen={openRow} />}
        </div>
        <div className="hub-t3p-side">
          <ThreadPanel id={openId} hint={openThreadObj ? openThreadObj.subject : ""} open={panelOpen && !!openId} onBack={() => setPanelOpen(false)}
            labels={labels} onChanged={changed} say={say} bin={!!BIN[eff]} />
        </div>
      </div>}
    </React.Fragment>;
  }

  class Boundary extends Component {
    constructor(p) { super(p); this.state = {failed: false}; }
    static getDerivedStateFromError() { return {failed: true}; }
    componentDidCatch(e) { console.error("mail body failed", e); }
    render() { return this.state.failed ? <div className="hub-error">page failed to load</div> : this.props.children; }
  }

  const host = $("pane");
  function App() { return <Boundary><Body /></Boundary>; }

  if (host) {
    if ($("mxCol")) $("mxCol").textContent = "";  // the static rail would sit above the portal's
    ReactDOM.createRoot(host).render(<App />);
  }
  window.MailUI.App = App;
  window.MailUI.Rail = Rail;
  window.MailUI.SenderList = SenderList;
  window.MailUI.ThreadList = ThreadList;
})();
