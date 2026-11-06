/* automations: tabbed 3-pane page. Rail = seven tabs (gmail, finance, decisions, runs,
   burn, updates, rules), middle = stacked rows, right = the picked row's detail.

   Frame half (this part): four resources, busy / outcome / post, the tab and stack
   builder, namespaced selection, rail, drawer and the render tree. The detail half
   (Detail, one card per row kind, the action dock) replaces the stub below.

   Selection ids: g:<gmail id>  f:<txn uid>  d:<decision id>  o:<kind>:<id>
                  r:<job>:<t>   b:<burn run>[:<job>]   n:<digest date>  u:<line n>  l:<rule id>
   Promise chains, not async/await: babel's async helper would be a second top-level global. */
window.AutomationsUI = window.AutomationsUI || {};
(() => {
  const { useState, useEffect, useRef, useMemo, Component } = React;
  const $ = (id) => document.getElementById(id);

  const hhmm = (t) => (t || "").slice(11, 16);
  const shortDay = (t) => t ? new Date(`${t.slice(0, 10)}T12:00`).toLocaleDateString(undefined, {month: "short", day: "numeric"}) : "";
  const dayName = (d) => {
    const today = new Date().toLocaleDateString("en-CA");
    const y = new Date(Date.now() - 864e5).toLocaleDateString("en-CA");
    return d === today ? "today" : d === y ? "yesterday" : new Date(`${d}T12:00`).toLocaleDateString(undefined, {weekday: "long", month: "short", day: "numeric"});
  };
  const money = (c) => (c < 0 ? "-$" : "$") + (Math.abs(c) / 100).toFixed(2);
  // object spread would emit a top-level babel helper (ownKeys), so copy by hand
  const ext = (o, patch) => Object.assign({}, o, patch);
  const put = (o, k, v) => { const c = Object.assign({}, o); c[k] = v; return c; };
  const decMs = (d) => new Date(/[Z+]/.test(d.made_at) ? d.made_at : `${d.made_at}Z`).getTime();

  // ── resources ──────────────────────────────────────────────────────────────

  const URLS = {
    feed: "/automations/api/feed",
    dec: "/automations/api/decisions?days=7",
    cats: "/finances/api/book/categories",
    upd: "/automations/api/updates",
    rules: "/automations/api/rules",
    burns: "/automations/api/burns",
  };
  const fresh = (loading) => ({data: null, err: null, loading});
  const NEEDS = {gmail: ["feed"], finance: ["feed"], decisions: ["dec"], runs: ["feed"], burn: ["burns"], updates: ["upd"], rules: ["rules"]};
  const WAITING_KINDS = ["finwait"];
  const LANE_TAGS = [["all", "all"], ["gmail", "gmail"], ["finance-category", "category"], ["finance-memo", "memo"], ["voice-memo", "voice"]];

  // ── tab rail ───────────────────────────────────────────────────────────────

  const GLYPH = {
    gmail: <React.Fragment><rect x="3.6" y="6" width="16.8" height="12" rx="1.2" /><path d="M3.6 7.2 L12 13.2 L20.4 7.2" /></React.Fragment>,
    finance: <React.Fragment><circle cx="12" cy="12" r="8.4" /><path d="M14.7 9.3 C14.1 8.4 13.2 8 12 8 C10.4 8 9.3 8.8 9.3 10 C9.3 12.9 14.7 11.1 14.7 14 C14.7 15.2 13.6 16 12 16 C10.8 16 9.8 15.6 9.2 14.7 M12 6.2 V8 M12 16 V17.8" /></React.Fragment>,
    decisions: <path d="M4.2 6.6 L5.7 8.1 L8.4 5.4 M4.2 12 L5.7 13.5 L8.4 10.8 M4.2 17.4 L5.7 18.9 L8.4 16.2 M11.4 6.9 H19.8 M11.4 12.3 H19.8 M11.4 17.7 H19.8" />,
    runs: <React.Fragment><circle cx="12" cy="12" r="8.4" /><path d="M12 7.2 V12 L15.6 14.4" /></React.Fragment>,
    burn: <path d="M12 3.2 C12.6 6 16.8 8 16.8 13 C16.8 16.4 14.7 20.4 12 20.4 C9.3 20.4 7.2 17.6 7.2 14.4 C7.2 12.6 8 11.4 9 10.2 C9.4 11.4 10 12 10.8 12 C10.2 8.4 11.4 5.4 12 3.2 Z" />,
    updates: <path d="M12 3.6 V13.2 M8.4 9.6 L12 13.2 L15.6 9.6 M3.6 14.4 V19.2 H20.4 V14.4 M3.6 14.4 H8.4 L9.6 16.2 H14.4 L15.6 14.4 H20.4" />,
    rules: <React.Fragment><path d="M3.6 7.2 H11.4 M3.6 16.8 H8.4 M16.8 16.8 H20.4 M15.6 7.2 H20.4" /><circle cx="13.5" cy="7.2" r="2.1" /><circle cx="12.6" cy="16.8" r="2.1" /></React.Fragment>,
  };
  const TAB_IDS = ["gmail", "finance", "decisions", "runs", "burn", "updates", "rules"];

  function Nav({tabs, tab, onTab}) {
    return <nav className="hub-nav-rail" id="amNav">
      {tabs.map((t) => <button key={t.id} type="button" className={`hub-t3p-tab hub-nav-item${t.id === tab ? " active" : ""}`} data-tab={t.id} onClick={() => onTab(t.id)}>
        <span className="hub-t3p-tab-label hub-nav-label"><svg className="hub-t3p-tab-glyph" viewBox="0 0 24 24" aria-hidden="true">{GLYPH[t.id]}</svg>{t.id}</span>
        {t.count > 0 ? <span className="am-count">{t.count}</span> : null}
      </button>)}
    </nav>;
  }

  // phone nav drawer: is-open on the rail, scrim shown, toggle aria-expanded in sync
  function setDrawer(open) {
    const rail = $("amCol"), scrim = $("amScrim"), toggle = $("navToggle");
    if (!rail) return;
    rail.classList.toggle("is-open", open);
    if (scrim) scrim.hidden = !open;
    if (toggle) toggle.setAttribute("aria-expanded", String(open));
  }

  // ── tabs and stacks, built from the resources ─────────────────────────────

  const byDay = (rows) => {
    const m = new Map();
    for (const r of rows) (m.get(r.day) || m.set(r.day, []).get(r.day)).push(r);
    return [...m].map(([d, rs]) => ({key: `day:${d}`, title: dayName(d), rows: rs}));
  };
  const stack = (key, title, rows) => ({key, title, rows});
  const nonEmpty = (stacks) => stacks.filter((s) => s.rows.length);

  const runBits = (r) => {
    const bits = [];
    for (const k of ["considered", "moved", "proposed", "added", "updated", "errors", "failed"]) if (r[k]) bits.push(`${k} ${r[k]}`);
    if (r.cost_usd) bits.push(`$${Number(r.cost_usd).toFixed(4)}`);
    if (r.outcome && !["ok", "saved"].includes(r.outcome)) bits.unshift(r.outcome + (r.reason ? `: ${r.reason}` : ""));
    return bits.join(" · ") || r.detail || "";
  };

  // a row is {sel, kind, t, from, subj, sub, bad, day, ...payload for Detail}

  function mailRow(kind, i, e) {
    const sub = kind === "noted" ? `your note: ${i.note}` : `→ ${i.label || i.action} · ${i.state}`;
    return {sel: `g:${i.id}`, kind, t: e ? hhmm(e.t) : shortDay(i.received_at), from: i.sender, subj: i.subject, sub,
      bad: !!(e?.bad), day: e ? e.day : "", item: i, e};
  }

  const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
  const isFin = (r) => r.lane.startsWith("finance");
  const ruleSrc = (r) => ({note: r.scope === "once" ? "your note, judged this email only" : "your note", streak: "3 answers in a row",
    sender: "file-without-asking list", payee: `${r.count} of ${r.total} answers`})[r.source] || r.source;
  const ruleLast = (r) => r.source === "note" ? r.at : r.answers && r.answers.length ? r.answers[r.answers.length - 1].at : "";
  const RULE_STACKS = [["proposed", "to confirm"], ["confirmed", "confirmed"], ["off", "off"], ["rejected", "rejected"]];
  const ruleRow = (r) => {
    const n = (r.recent || []).length;
    return {sel: `l:${r.id}`, kind: "rule", t: shortDay(ruleLast(r)), from: r.who, subj: cap(r.does),
      sub: `${isFin(r) ? "category" : "gmail"} · ${ruleSrc(r)}${n ? ` · acted ${n}× this week` : ""}`, bad: false, day: "", rule: r};
  };

  function buildTabs(res, dlane) {
    const feed = res.feed.data, dec = res.dec.data, upd = res.upd.data, rl = res.rules.data;
    const ev = feed ? feed.events : [];
    const sorted = ev.filter((e) => e.kind === "sorted");

    const gmail = nonEmpty(feed ? [
      // waiting mail is settled on its thread in /mail; this tab keeps a count and the way there
      stack("waiting", "waiting on you", feed.waiting.length ? [{sel: "g:waiting", kind: "link", t: "", from: `${feed.waiting.length} waiting on you`,
        subj: "settle them in Mail", sub: "", bad: false, day: "", href: "/mail/?label=waiting"}] : []),
      stack("noted", "handed to Claude", feed.noted.map((i) => mailRow("noted", i))),
      stack("failed", "failed", sorted.filter((e) => e.bad).map((e) => mailRow("sorted", e.item, e))),
      // stale: he moved it in Mail or Gmail while it waited on him, so the lane did nothing
      stack("elsewhere", "handled outside the lane", sorted.filter((e) => e.item.state === "stale").map((e) => mailRow("sorted", e.item, e))),
      ...byDay(sorted.filter((e) => !e.bad && e.item.state !== "stale").map((e) => mailRow("sorted", e.item, e))),
    ] : []);

    const finance = nonEmpty(feed ? [
      stack("waiting", "waiting on you", feed.finance_waiting.map((f) => ({sel: `f:${f.uid}`, kind: "finwait", t: shortDay(f.date), from: f.payee,
        subj: f.amount_str, sub: f.needs.join(" · "), bad: false, day: "", txn: f}))),
      ...byDay(ev.filter((e) => e.kind === "finance").map((e) => ({sel: `f:${e.txn.id}`, kind: "finauto", t: hhmm(e.t),
        from: e.txn.payee || e.txn.raw_description, subj: money(e.txn.amount_cents), sub: `auto-approved as ${e.txn.category}`, bad: false, day: e.day, txn: e.txn, e}))),
    ] : []);

    // logged decisions plus the work done before decisions were logged (read only)
    let decisions = [];
    if (dec) {
      const first = dec.length ? Math.min(...dec.map(decMs)) : Infinity;
      const old = ev.filter((e) => (e.kind === "sorted" || e.kind === "finance") && new Date(e.t).getTime() < first)
        .map((e) => ({ms: new Date(e.t).getTime(), lane: e.kind === "sorted" ? "gmail" : "finance-category", row: {
          sel: `o:${e.kind}:${e.item ? e.item.id : e.txn.id}`, kind: "old",
          t: hhmm(e.t), from: e.item ? e.item.sender : e.txn.payee || e.txn.raw_description, subj: e.item ? e.item.subject : money(e.txn.amount_cents),
          sub: "auto · before the decision log", bad: false, item: e.item, txn: e.txn, e}}));
      const rows = [...dec.map((d) => ({ms: decMs(d), lane: d.lane, row: {
        sel: `d:${d.id}`, kind: "dec", t: new Date(decMs(d)).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", hourCycle: "h23"}),  // 24h like the other tabs; made_at is UTC so not hhmm
        from: d.title || d.ref, subj: d.state, sub: `${d.made_by === "auto" ? "auto" : "you"} · ${d.action}`, bad: d.state === "failed", d}})), ...old]
        .filter((r) => dlane === "all" || r.lane === dlane).sort((a, b) => b.ms - a.ms);
      decisions = byDay(rows.map((r) => ext(r.row, {day: new Date(r.ms).toLocaleDateString("en-CA")})));
    }

    const runRows = ev.filter((e) => e.kind === "run" || e.kind === "digest").map((e) => e.kind === "run"
      ? {sel: `r:${e.run.job}:${e.t}`, kind: "run", t: hhmm(e.t), from: e.run.job, subj: e.run.status, sub: runBits(e.run), bad: e.bad, day: e.day, run: e.run, e}
      : {sel: `n:${e.date}`, kind: "digest", t: hhmm(e.t), from: "news digest", subj: "", sub: `saved ${e.bullets} bullets`, bad: false, day: e.day, e});
    const runs = nonEmpty([stack("failed", "failed", runRows.filter((r) => r.bad)), ...byDay(runRows.filter((r) => !r.bad))]);

    let updates = [];
    if (upd && upd.state === "ok") {
      updates = nonEmpty([stack("log", "updater log", upd.lines.map((l) => ({sel: `u:${l.t}:${l.text}`, kind: "upd", state: "ok", t: hhmm(l.t), from: l.text, subj: "", sub: "", bad: l.bad, day: "", line: l})))]);
    } else if (upd) {  // missing or error: one row so the detail can say why
      updates = [stack("log", "updater log", [{sel: "u:state", kind: "upd", state: upd.state, t: "", from: "updater log",
        subj: "", sub: upd.state === "missing" ? "the updater runs on the PC" : "could not read the updater log", bad: upd.state === "error", day: ""}])];
    }

    const burn = burnStacks(res.burns.data);

    const rules = nonEmpty(rl ? RULE_STACKS.map(([k, t]) => ext(stack(k, t, rl.filter((r) => r.state === k).map(ruleRow)), {fold: k === "rejected"})) : []);

    // sel ids are unique within a tab, a repeat gets a suffix
    const uniq = (stacks) => {
      const seen = new Set();
      return stacks.map((s) => ext(s, {rows: s.rows.map((r) => {
        let sel = r.sel, k = 1;
        while (seen.has(sel)) sel = `${r.sel}#${++k}`;
        seen.add(sel);
        return sel === r.sel ? r : ext(r, {sel});
      })}));
    };
    const mk = (id, count, stacks, extra) => ext({id, count, stacks: uniq(stacks), needs: NEEDS[id]}, extra);
    return [
      mk("gmail", feed ? feed.waiting.length : null, gmail),
      mk("finance", feed ? feed.finance_waiting.length : null, finance),
      mk("decisions", null, decisions, {lanes: true}),
      mk("runs", null, runs),
      mk("burn", null, burn),
      mk("updates", null, updates),
      mk("rules", rl ? rl.filter((r) => r.state === "proposed").length : null, rules),
    ];
  }

  // ── burn tab: one stack per recorded /burn run (summary row, then a row per job) ──

  const pct = (v) => v === null || v === undefined ? "?" : `${Math.round(v * 10) / 10}%`;
  const burnWindow = (b) => `5h ${pct(b.five_start)} to ${pct(b.five_end)} (allowed ${pct(b.five_allow)})`;
  const BAD_JOB = ["failed", "conflict", "partial", "merged, live verify failed"];
  const show = (v) => typeof v === "object" ? JSON.stringify(v) : String(v);
  const has = (v) => !(v === null || v === undefined || v === "" || (Array.isArray(v) && !v.length) || (typeof v === "object" && !Array.isArray(v) && !Object.keys(v).length));

  function burnStacks(burns) {
    return (burns || []).map((b) => {
      const jobs = (b.report.jobs || []).map((j) => ({sel: `b:${b.run}:${j.id}`, kind: "burnjob", t: hhmm(j.started), from: j.id, subj: j.status,
        sub: `chain ${j.chain}${j.summary ? ` · ${j.summary}` : ""}`, bad: BAD_JOB.includes(j.status), day: "", job: j, burn: b}));
      const head = {sel: `b:${b.run}`, kind: "burnrun", t: hhmm(b.started_at), from: "run summary", subj: b.status,
        sub: `${b.merged} merged · ${b.failed} failed · ${burnWindow(b)}`, bad: b.failed > 0, day: "", burn: b};
      return stack(`burn:${b.run}`, `${shortDay(b.started_at)} ${hhmm(b.started_at)} · ${burnWindow(b)}`, [head].concat(jobs));
    });
  }

  const rowsOf = (t) => t.stacks.flatMap((s) => s.rows);

  // the next waiting item, from the stack order as it was before the refresh
  function nextWaiting(tab, sel) {
    for (const s of tab.stacks) {
      const k = s.rows.findIndex((r) => r.sel === sel);
      if (k >= 0 && s.rows[k + 1]) return s.rows[k + 1].sel;
    }
    const w = tab.stacks.find((s) => s.key === "waiting");
    const r = w?.rows.find((x) => x.sel !== sel);
    return r ? r.sel : null;
  }

  // ── list ───────────────────────────────────────────────────────────────────

  function Row({r, selected, onPick}) {
    if (r.href) return <a className="am-row" href={r.href}><span className="am-row-t">{r.t}</span>
      <span className="am-row-main"><span className="am-row-from">{r.from}</span><span className="am-row-subj">{r.subj}</span></span></a>;
    return <button type="button" className={`am-row${selected ? " is-sel" : ""}${r.bad ? " is-bad" : ""}`} data-sel={r.sel}
                   aria-current={selected ? "true" : undefined} onClick={() => onPick(r.sel)}>
      <span className="am-row-t">{r.t}</span>
      <span className="am-row-main">
        <span className="am-row-from">{r.from}</span>
        {r.subj ? <span className="am-row-subj">{r.subj}</span> : null}
        {r.sub ? <span className="am-row-sub">{r.sub}</span> : null}
      </span>
    </button>;
  }

  // ── detail: one card per row kind; actionable cards end in the dock ───────

  const LANES = {gmail: "gmail", "finance-category": "category", "finance-memo": "memo", "voice-memo": "voice"};
  const fmtVal = (k, v, cats) => {
    if (v === null || v === undefined || v === "") return "blank";
    if (k === "category_id") { const c = cats.find((c) => String(c.id) === String(v)); return c ? c.full_name : `#${v}`; }
    if (k === "approved") return v ? "approved" : "not approved";
    return typeof v === "object" ? JSON.stringify(v) : String(v);
  };
  const gmDate = (t) => (t || "").replace("T", " ").slice(0, 16);

  function Head({from, title, when}) {
    return <div className="am-head"><div className="am-from">{from}</div>
      <div className="am-title" role="heading" aria-level="2">{title}</div><div className="am-when">{when}</div></div>;
  }

  // own(key) says which action keys belong to this card; dis = one of them is running or the list is stale
  function guard(cx, own) {
    const o = cx.outcome, mine = !!(o && own(o.key));
    return {mine, dis: [...cx.busy].some(own) || (mine && o.kind === "stale")};
  }

  function Out({cx, mine}) {
    const o = cx.outcome;
    return <p className="am-outcome" role="status">{mine ? o.text : ""}
      {mine && o.kind === "stale" ? <button type="button" className="hub-btn" data-act="retry" onClick={() => cx.reload(["feed", "dec"])}>retry</button> : null}</p>;
  }

  function Dock({prop, g, cx, children, noterow}) {
    return <div className="am-dock"><p className="am-dock-prop">{prop}</p>{noterow || null}{children}<Out cx={cx} mine={g.mine} /></div>;
  }

  function OpenLink({i}) {
    return i.gmail_link ? <a className="hub-link-chip" href={i.gmail_link} target="_blank" rel="noopener">open in gmail</a> : null;
  }

  function Back({i, cx}) {
    const key = `g:${i.id}:back`, g = guard(cx, (k) => k === key);
    return <Dock g={g} cx={cx} prop={<React.Fragment><span className="hub-pill">{i.state}</span> moved by the sorter; put it back if it was wrong</React.Fragment>}>
      <div className="am-btns"><button type="button" className="hub-btn" data-act="back" disabled={g.dis}
        onClick={() => cx.post("/automations/api/act", {id: i.id, action: "back"}, key, "moved back")}>back to inbox</button></div>
    </Dock>;
  }

  // a row he answered in words: Claude carries the note out on the next /gmail run
  function GmailNoted({i}) {
    return <React.Fragment>
      <Head from={i.sender} title={i.subject} when={gmDate(i.received_at)} />
      <p className="am-sum">{i.details || i.summary}</p>
      <OpenLink i={i} />
      <p className="am-why"><span className="hub-pill">note sent</span> your note: {i.note}</p>
      <p className="am-note">the next /gmail run does this</p>
    </React.Fragment>;
  }

  function GmailSorted({row, cx}) {
    const i = row.item;
    return <React.Fragment>
      <Head from={i.sender} title={i.subject} when={row.e ? gmDate(row.e.t) : gmDate(i.received_at)} />
      <p className="am-sum">→ {i.label || i.action} <span className="hub-pill">{i.state}</span></p>
      <OpenLink i={i} />
      {i.state === "moved" ? <Back i={i} cx={cx} /> : null}
    </React.Fragment>;
  }

  // finance answer controls: category select (prefilled) + memo box, one save. Shared by waiting cards and fix.
  function FinForm({cx, cats, catPre, memoPre, text, act, canSkip, dis, onSave, noMemoBox}) {
    const [cat, setCat] = useState(null), [memo, setMemo] = useState(null);
    const rc = cx.res.cats, ready = !!rc.data, can = ready || !!rc.err;  // categories down: memo-only saves still go (old page)
    const catV = cat === null ? String(catPre ?? "") : cat, memoV = memo === null ? memoPre || "" : memo;
    const save = (noMemo) => onSave(ready && catV || undefined, noMemo ? "" : memoV.trim(), noMemo);
    return <div className="am-acts"><select className="hub-input" aria-label="category" disabled={!ready} value={ready ? catV : ""} onChange={(ev) => setCat(ev.target.value)}>
        <option value="">{ready ? "category…" : rc.loading ? "loading categories…" : "categories unavailable"}</option>
        {cats.map((c) => <option key={c.id} value={c.id}>{c.full_name}</option>)}</select>
      {noMemoBox ? null : <input className="hub-input" maxLength={500} value={memoV} onChange={(ev) => setMemo(ev.target.value)} placeholder="memo…" aria-label="memo" />}
      <div className="am-btns"><button type="button" className="hub-btn hub-btn--accent" data-act={act} disabled={dis || !can} onClick={() => save(false)}>{text}</button>
        {canSkip ? <button type="button" className="hub-btn" data-act="no_memo" disabled={dis || !can} onClick={() => save(true)}>no memo needed</button> : null}</div></div>;
  }

  function FinWait({f, cx}) {
    const cats = cx.cats, key = `f:${f.uid}`, g = guard(cx, (k) => k === key);
    const find = (n) => n && cats.find((c) => c.name === n || c.full_name === n);
    const pre = (find(f.suggested_category_name) || find(f.category_name))?.id;
    return <React.Fragment>
      <Head from={f.payee} title={f.amount_str} when={f.date} />
      <p className="am-sum">{f.category_name ? `now ${f.category_name}` : "no category"}{f.suggested_category_name ? ` · suggested ${f.suggested_category_name}` : ""}</p>
      <Dock g={g} cx={cx} prop={<React.Fragment><span className="hub-pill is-warn">{f.needs.join(" · ")}</span> {f.suggested_category_name ? `claude's pick: ${f.suggested_category_name}` : "claude has no category pick"}</React.Fragment>}>
        <FinForm cx={cx} cats={cats} catPre={pre} memoPre={f.memo || f.memo_draft} text="save and approve" act="save" dis={g.dis} canSkip={f.needs.includes("memo")}
          onSave={(cat, memo, noMemo) => cx.post("/automations/api/finance/act",
            {uid: f.uid, category_id: cat, memo: noMemo ? undefined : memo, approve: true, no_memo: noMemo || undefined}, key, "saved")} />
      </Dock>
    </React.Fragment>;
  }

  function FinAuto({row}) {
    const f = row.txn;
    return <React.Fragment>
      <Head from={f.payee || f.raw_description} title={money(f.amount_cents)} when={row.e ? gmDate(row.e.t) : ""} />
      <p className="am-sum">auto-approved as {f.category}</p>
    </React.Fragment>;
  }

  function DecCard({d, cx}) {
    const cats = cx.cats, fd = cx.res.feed.data, labels = fd ? fd.labels || [] : [];
    const [fixing, setFixing] = useState(false), [fold, setFold] = useState(null);
    const ukey = `undo:${d.id}`, fkey = `fix:${d.id}`, g = guard(cx, (k) => k === ukey || k === fkey);
    useEffect(() => { if (cx.outcome && cx.outcome.key === fkey && cx.outcome.kind === "ok") setFixing(false); }, [cx.outcome]);
    let ch = {};
    try { ch = JSON.parse(d.changed_json || "{}"); } catch (_e) { /* shown blank */ }
    const lab = (v) => { // gmail label ids: say what happened, not the ids
      const [b, a2] = v.map((x) => new Set(x)), add = [...a2].filter((x) => !b.has(x)), rm = [...b].filter((x) => !a2.has(x));
      return (rm.includes("INBOX") ? "left inbox" : "") + (add.includes("TRASH") ? ", trashed" : add.some((x) => x.startsWith("Label_")) ? ", filed" : "") || "no label change";
    };
    const diff = Object.entries(ch).filter(([, v]) => Array.isArray(v) && String(v[0]) !== String(v[1]))
      .map(([k, v]) => k === "labels" ? lab(v).replace(/^, /, "") : `${k.replace("_id", "")}: ${fmtVal(k, v[0], cats)} → ${fmtVal(k, v[1], cats)}`).join(" · ");
    const st = d.state, can = st === "applied" && d.undo !== "none", bad = st === "failed", fixable = d.lane !== "voice-memo";
    const utc = new Date(decMs(d));
    const fixPost = (answer) => cx.post(`/automations/api/decisions/${d.id}/fix`, {fix_key: crypto.randomUUID(), answer}, fkey, "fixed");
    const folder = labels.includes(fold) ? fold : labels[0];
    let ctl = null;
    if (fixing && d.lane === "gmail") {
      const off = g.dis || !fd;
      const b = (a, t, c) => <button type="button" className={`hub-btn ${c}`} data-act={a} disabled={off} onClick={() => fixPost({action: a, label: folder || ""})}>{t}</button>;
      ctl = <div className="am-acts"><select className="hub-input" aria-label="folder to move to" disabled={!fd} value={folder || ""} onChange={(ev) => setFold(ev.target.value)}>
          {fd ? labels.map((l) => <option key={l}>{l}</option>) : <option>folders unavailable</option>}</select>
        <div className="am-btns">{b("move", "move to", "")}{b("keep", "keep", "")}{b("delete", "delete", "hub-btn--danger")}</div></div>;
    } else if (fixing) {
      ctl = <FinForm cx={cx} cats={cats} memoPre="" text="fix" act="fix_save" dis={g.dis}
        onSave={(cat, memo) => fixPost({category_id: cat, memo: memo || undefined, approve: true})} />;
    }
    return <React.Fragment>
      <Head from={d.title || d.ref} title={`${LANES[d.lane] || d.lane} · ${d.action}`} when={utc.toLocaleString([], {month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"})} />
      <p className="am-sum"><span className="hub-pill">{LANES[d.lane] || d.lane}</span> <span className={`hub-pill${bad ? " is-alert" : st === "applied" ? " is-good" : ""}`}>{st}</span> {d.made_by === "auto" ? "auto" : "you"} · {d.action}</p>
      {diff ? <p className="am-sum">{diff}</p> : null}
      {d.reason ? <p className="am-why">{d.reason}</p> : null}
      {d.rule ? <p className="am-why">rule: <a href="#" className="rx-link" onClick={(ev) => { ev.preventDefault(); cx.go("rules", `l:${d.rule.id}`); }}>{d.rule.text}</a></p>
        : d.made_by === "auto" ? <p className="am-why">model's own call, no rule</p> : null}
      {st === "applied" ? <Dock g={g} cx={cx} prop={<React.Fragment><span className="hub-pill is-good">applied</span> {can ? (fixable ? "undo puts it back, fix answers it again" : "undo puts it back") : "this one cannot be undone"}</React.Fragment>}>
        <div className="am-btns">
          {can ? <button type="button" className="hub-btn" data-act="undo" disabled={g.dis} onClick={() => cx.post(`/automations/api/decisions/${d.id}/undo`, {}, ukey, "undone")}>undo</button> : <span className="am-note">cannot undo</span>}
          {fixable ? <button type="button" className="hub-btn" data-act="fix" onClick={() => setFixing(!fixing)}>{fixing ? "close" : "fix"}</button> : null}</div>
        {ctl}
      </Dock> : null}
    </React.Fragment>;
  }

  // a sorted mail or auto-approved finance row from before decisions were logged
  function OldCard({row, cx}) {
    const i = row.item, f = row.txn, e = row.e;
    return <React.Fragment>
      <Head from={i ? i.sender : f.payee || f.raw_description} title={i ? i.subject : money(f.amount_cents)} when={gmDate(e.t)} />
      <p className="am-sum"><span className="hub-pill">{i ? "gmail" : "category"}</span> <span className="hub-pill">{i ? i.state : "approved"}</span> auto · before the decision log</p>
      <p className="am-sum">{i ? `${i.subject} → ${i.label || i.action}` : `${money(f.amount_cents)} approved as ${f.category}`}</p>
      {i && i.state === "moved" ? <Back i={i} cx={cx} /> : <p className="am-note">cannot undo</p>}
    </React.Fragment>;
  }

  function RunCard({row}) {
    const r = row.run, bits = runBits(r);
    return <React.Fragment>
      <Head from={r.job} title={r.status} when={gmDate(row.e.t)} />
      <p className="am-sum"><span className={`hub-pill${row.bad ? " is-alert" : " is-good"}`}>{r.status}</span> {bits}</p>
      {r.detail && r.detail !== bits ? <p className="am-sum">{r.detail}</p> : null}
    </React.Fragment>;
  }

  function Facts({pairs}) {
    return <React.Fragment>{pairs.filter((p) => has(p[1])).map((p) => <p key={p[0]} className="am-why"><b>{p[0]}</b>{show(p[1])}</p>)}</React.Fragment>;
  }

  function BurnRunCard({b}) {
    const r = b.report, skip = ["jobs", "budget", "budget_end"];
    const extras = Object.keys(r).filter((k) => !skip.includes(k)).map((k) => [k.replace(/_/g, " "), r[k]]);
    return <React.Fragment>
      <Head from="burn run" title={`${shortDay(b.started_at)} ${hhmm(b.started_at)}`} when={`${gmDate(b.started_at)} to ${hhmm(b.ended_at)}`} />
      <p className="am-sum"><span className={`hub-pill${b.failed ? " is-alert" : " is-good"}`}>{b.status}</span> {b.merged} merged · {b.failed} failed</p>
      <Facts pairs={[["five-hour window", burnWindow(b)],
        ["week", `${pct(b.week_start)} to ${pct(b.week_end)} (allowed ${pct(b.week_allow)})`]].concat(extras, [["budget", r.budget], ["budget at end", r.budget_end], ["run id", b.run]])} />
    </React.Fragment>;
  }

  function BurnJobCard({j, b}) {
    const bad = BAD_JOB.includes(j.status);
    return <React.Fragment>
      <Head from={`${j.source} · chain ${j.chain}`} title={j.id} when={`${gmDate(j.started)} to ${hhmm(j.ended)}`} />
      <p className="am-sum"><span className={`hub-pill${bad ? " is-alert" : " is-good"}`}>{j.status}</span> {j.summary}</p>
      <Facts pairs={[["why it stopped", j.reason], ["worker said", j.worker_status], ["files changed", j.files], ["touched but not declared", j.undeclared],
        ["database writes", j.db_writes], ["copy check", j.copy_verify], ["live check", j.live_verify], ["tests", j.tests], ["run", b.run]]} />
    </React.Fragment>;
  }

  function UpdCard({row, cx}) {
    if (row.state !== "ok") {
      return <React.Fragment>
        <Head from="updater log" title={row.state === "missing" ? "the updater has not run yet" : "could not read the updater log"} when="" />
        <p className="am-sum">{row.state === "missing" ? "the updater runs on the PC" : "the log exists but could not be read"}</p>
        <div className="am-btns"><button type="button" className="hub-btn" data-act="retry" onClick={() => cx.reload(["upd"])}>retry</button></div>
      </React.Fragment>;
    }
    return <React.Fragment>
      <Head from="updater log" title={row.line.t || "update line"} when={`line ${row.line.n}`} />
      <p className={`am-sum${row.bad ? " is-bad" : ""}`}>{row.line.text}</p>
    </React.Fragment>;
  }

  const RULE_STATE = {proposed: ["is-warn", "to confirm", "nothing happens until you confirm"], confirmed: ["is-good", "confirmed", "acting on new mail now"],
    off: ["", "off", "turned off: it no longer acts"], rejected: ["is-alert", "rejected", "it comes back only after 3 new answers agree"]};

  function RuleEvidence({r}) {
    if (r.source === "note") return <React.Fragment>
      <p className="am-why"><b>your note · {shortDay(r.at)}</b>"{r.quote}"</p>
      {r.from_mail ? <p className="am-why"><b>written on</b>{r.from_mail.subject} · {shortDay(r.from_mail.at)}</p> : null}
      <p className="am-why"><b>judged as</b>{!r.scope ? "not judged yet: the next gmail run reads your note"
        : r.scope === "once" ? "this email only: carried out once, no standing rule"
        : `${r.scope === "both" ? "this email and " : ""}a standing rule for ${r.who}${r.kind ? ` ${r.kind}` : ""} mail`}</p>
    </React.Fragment>;
    if (r.source === "streak" || r.source === "payee") return <div className="am-why"><b>{r.source === "streak" ? "your last 3 answers" : `your last ${r.answers.length} answers`}</b>
      <ul className="rx-ev">{r.answers.map((a, k) => <li key={k}><span className="rx-ev-t">{shortDay(a.at)}</span><span>{a.subject || (a.amount != null ? money(a.amount) : "your answer")}</span><span className="rx-ev-a">{a.action || a.category}</span></li>)}</ul></div>;
    return <p className="am-why"><b>from the file-without-asking list</b>{r.comment}</p>;
  }

  function RuleCard({r, cx}) {
    const key = `l:${r.id}:`, g = guard(cx, (k) => k.startsWith(key));
    const [editing, setEditing] = useState(false);
    const fd = cx.res.feed.data, labels = fd ? fd.labels || [] : [];
    const [act, setAct] = useState(r.action || (/^delete/.test(r.does) ? "delete" : /^keep/.test(r.does) ? "keep" : "move"));
    const [fold, setFold] = useState(r.target || labels[0] || ""), [text, setText] = useState(r.note || r.does);
    useEffect(() => { if (cx.outcome && cx.outcome.key.startsWith(key) && cx.outcome.kind === "ok") setEditing(false); }, [cx.outcome]);
    const send = (what, fields, ok) => cx.post(`/automations/api/rules/${r.id}/${what}`, ext({rev: r.rev}, fields), key + what, ok);
    const n = (r.recent || []).length, w = r.waiting || [];
    const st = r.state === "rejected" && r.source === "note" ? ["is-alert", "rejected", "it comes back only if you write a new note"] : RULE_STATE[r.state];
    let ed = null;
    if (editing && isFin(r)) ed = <FinForm cx={cx} cats={cx.cats} catPre={r.action} noMemoBox text="save" act="edit_save" dis={g.dis}
      onSave={(cat) => cat && send("edit", {action: cat}, "saved")} />;
    else if (editing && r.source === "note") ed = <div className="am-acts"><input className="hub-input" maxLength={500} value={text} aria-label="rule text" onChange={(ev) => setText(ev.target.value)} />
      <div className="am-btns"><button type="button" className="hub-btn hub-btn--accent" data-act="edit_save" disabled={g.dis || !text.trim()} onClick={() => send("edit", {note: text.trim()}, "saved")}>save</button></div></div>;
    else if (editing) ed = <div className="am-acts"><select className="hub-input" aria-label="what it does" value={act} onChange={(ev) => setAct(ev.target.value)}>
        <option value="move">move to a folder</option><option value="delete">delete</option><option value="keep">keep</option></select>
      {act === "move" ? <select className="hub-input" aria-label="folder to move to" value={fold} onChange={(ev) => setFold(ev.target.value)}>
        {labels.map((l) => <option key={l}>{l}</option>)}</select> : null}
      <div className="am-btns"><button type="button" className="hub-btn hub-btn--accent" data-act="edit_save" disabled={g.dis || (act === "move" && !fold)}
        onClick={() => send("edit", act === "move" ? {action: act, target: fold} : {action: act}, "saved")}>save</button></div></div>;
    return <React.Fragment>
      <Head from={`${r.who} · ${isFin(r) ? "category" : "gmail"}`} title={cap(r.does)} when={`${ruleSrc(r)}${ruleLast(r) ? ` · ${shortDay(ruleLast(r))}` : ""}`} />
      <p className="am-why"><b>waiting now</b>{isFin(r)
        ? (r.waiting_n ? `${r.waiting_n} uncategorized ${r.who} transaction would be categorized` : `nothing from ${r.who} is waiting`)
        : w.length ? w.map((m, k) => <React.Fragment key={k}>{k ? <br /> : null}{m.subject} · {shortDay(m.at)}</React.Fragment>) : `no mail from ${r.who} is waiting`}</p>
      <RuleEvidence r={r} />
      {n ? <div className="am-why"><b>acted {n} time{n > 1 ? "s" : ""} in the last 7 days</b>
        <ul className="rx-ev">{r.recent.slice(0, 4).map((d) => <li key={d.id}><span className="rx-ev-t">{shortDay(d.made_at)}</span>
          <a href="#" className="rx-link" onClick={(ev) => { ev.preventDefault(); cx.go("decisions", `d:${d.id}`); }}>{d.title}</a><span className="rx-ev-a">{d.action}</span></li>)}
          {n > 4 ? <li className="rx-more">and {n - 4} more on the decisions tab</li> : null}</ul></div> : null}
      <Dock g={g} cx={cx} prop={<React.Fragment><span className={`hub-pill ${st[0]}`}>{st[1]}</span> {st[2]}</React.Fragment>}>
        {ed}
        {r.state === "proposed" || r.state === "confirmed" ? <div className="am-btns">
          {r.state === "proposed" ? <button type="button" className="hub-btn hub-btn--accent" data-act="confirm" disabled={g.dis} onClick={() => send("confirm", {}, "confirmed")}>confirm</button>
            : <button type="button" className="hub-btn" data-act="off" disabled={g.dis} onClick={() => send("off", {}, "turned off")}>turn off</button>}
          <button type="button" className="hub-btn" data-act="edit" onClick={() => setEditing(!editing)}>{editing ? "close" : "edit"}</button>
          {r.state === "proposed" ? <button type="button" className="hub-btn hub-btn--danger" data-act="reject" disabled={g.dis} onClick={() => send("reject", {}, "rejected")}>reject</button> : null}
        </div> : null}
      </Dock>
    </React.Fragment>;
  }

  function Detail({cx}) {
    const row = cx.row;
    switch (row.kind) {
      case "noted": return <GmailNoted i={row.item} />;
      case "sorted": return <GmailSorted row={row} cx={cx} />;
      case "finwait": return <FinWait f={row.txn} cx={cx} />;
      case "finauto": return <FinAuto row={row} />;
      case "dec": return <DecCard d={row.d} cx={cx} />;
      case "old": return <OldCard row={row} cx={cx} />;
      case "run": return <RunCard row={row} />;
      case "digest": return <React.Fragment><Head from="news digest" title={`saved ${row.e.bullets} bullets`} when={gmDate(row.e.t)} />
        <a className="hub-link-chip" href="/news/">open news</a></React.Fragment>;
      case "burnrun": return <BurnRunCard b={row.burn} />;
      case "burnjob": return <BurnJobCard j={row.job} b={row.burn} />;
      case "upd": return <UpdCard row={row} cx={cx} />;
      case "rule": return <RuleCard r={row.rule} cx={cx} />;
    }
  }

  // ── page ───────────────────────────────────────────────────────────────────

  function Body() {
    const [res, setRes] = useState({feed: fresh(true), dec: fresh(true), cats: fresh(true), upd: fresh(false), rules: fresh(true), burns: fresh(false)});
    const [busy, setBusy] = useState(() => new Set());
    const [outcome, setOutcome] = useState(null);
    const [tab, setTab] = useState(() => {
      try { const s = localStorage.getItem("automations.tab"); return TAB_IDS.includes(s) ? s : "gmail"; } catch (_e) { return "gmail"; }
    });
    const [lastSel, setLastSel] = useState({});
    const [open, setOpen] = useState(false);
    const [dlane, setDlane] = useState("all");
    const [rejOpen, setRejOpen] = useState(false);
    const seq = useRef({feed: 0, dec: 0, cats: 0, upd: 0, rules: 0, burns: 0});
    const decided = useRef(false);
    const now = useRef({});
    const picks = useRef(0);  // bumps on every row pick; a pick during a POST cancels its advance
    const outRef = useRef(null);
    outRef.current = outcome;

    function load(name) {
      const n = ++seq.current[name];
      setRes((r) => put(r, name, ext(r[name], {loading: true})));
      return fetch(URLS[name])
        .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
        .then((d) => { if (n === seq.current[name]) setRes((r) => put(r, name, {data: name === "cats" ? d.categories || [] : name === "rules" ? d.rules || [] : d, err: null, loading: false})); return true; })
        .catch((e) => { if (n === seq.current[name]) setRes((r) => put(r, name, ext(r[name], {err: e.message, loading: false}))); return false; });
    }
    // true when every listed resource reloaded; clears a stale outcome once the list is back
    function reload(names) {
      return Promise.all(names.map(load)).then((rs) => {
        const ok = rs.every(Boolean);
        if (ok && outRef.current && outRef.current.kind === "stale") setOutcome(null);
        return ok;
      });
    }

    const say = (key, kind, text) => setOutcome({key, kind, text});
    function run(key, promise) {
      setBusy((b) => new Set(b).add(key));
      const rm = () => setBusy((b) => { const c = new Set(b); c.delete(key); return c; });
      return promise.then((v) => { rm(); return v; }, (e) => { rm(); throw e; });
    }

    // 2xx: reload what changed, then ok (or stale); 4xx: rejected; 5xx or lost: reload before anything re-enables
    function post(url, body, key, okText) {
      const at = now.current, acted = at.row?.sel, tabId = at.tab, p0 = picks.current;
      const nxt = at.row && WAITING_KINDS.includes(at.row.kind) ? nextWaiting(at.tabObj, acted) : undefined;
      return run(key, fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)})
        .then((r) => r.json().catch(() => ({})).then((out) => {
          if (r.ok) {
            return reload(["feed", "dec", "rules"]).then((good) => {
              if (!good) { say(key, "stale", "done, but the list could not reload"); return; }
              say(key, "ok", out.detail || okText || "saved");
              if (nxt !== undefined && picks.current === p0 && now.current.tab === tabId && (now.current.sel === acted || now.current.sel === null)) {  // null: the drop effect below cleared it first
                setLastSel((p) => put(p, tabId, nxt));
                if (!nxt) setOpen(false);
              }
            });
          }
          if (r.status >= 500) throw new Error(String(r.status));
          say(key, "rejected", out.conflict || out.error || String(r.status));
          if (r.status === 409) reload(["rules"]);
        }))
        .catch(() => { say(key, "unknown", "may not have gone through: reloading"); return reload(["feed", "dec", "rules"]); }));
    }

    const tabs = useMemo(() => buildTabs(res, dlane), [res, dlane]);
    const cur = tabs.find((t) => t.id === tab);
    const rows = rowsOf(cur);
    const sel = lastSel[tab] || null;
    const row = rows.find((r) => r.sel === sel) || null;
    now.current = {tab, tabObj: cur, row, sel};
    const ready = cur.needs.every((n) => res[n].data && !res[n].loading);
    const cats = (res.cats.data || []).concat(res.feed.data ? res.feed.data.inflow || [] : []);

    function pickTab(t) {
      decided.current = true;
      try { localStorage.setItem("automations.tab", t); } catch (_e) { /* browser-local only */ }
      setTab(t);
      setOutcome(null);
      setOpen(false);
      setDrawer(false);
    }
    // jump to a row on another tab (a decision card's rule, a rule's recent action)
    function go(t, s) {
      pickTab(t);
      picks.current++;
      if (t === "decisions") setDlane("all");
      setLastSel((p) => put(p, t, s));
      setOpen(true);
    }
    const pickRow = (s) => { picks.current++; setLastSel((p) => put(p, tab, s)); setOpen(true); };

    // mount: marker, drawer wiring, first loads
    useEffect(() => {
      $("pane").setAttribute("data-react-mounted", "automations");
      const toggle = $("navToggle"), rail = $("amCol"), scrim = $("amScrim");
      const flip = () => setDrawer(!rail.classList.contains("is-open"));
      const shut = () => setDrawer(false);
      if (toggle && rail && scrim) { toggle.addEventListener("click", flip); scrim.addEventListener("click", shut); }
      load("feed"); load("dec"); load("cats"); load("rules");
      return () => { if (toggle) toggle.removeEventListener("click", flip); if (scrim) scrim.removeEventListener("click", shut); };
    }, []);

    // default tab, decided once after the feed first settles, never after a click
    useEffect(() => {
      const t0 = tabs.find((t) => t.id === tab);  // tab already holds the stored one (useState)
      if (decided.current || res.feed.loading || t0.needs.some((n) => res[n].loading)) return;
      decided.current = true;
      const f = res.feed.data;
      if (!f) return;
      const first = f.waiting.length ? "gmail" : f.finance_waiting.length ? "finance" : null;
      if (first && !t0.stacks.length) setTab(first);
    }, [res.feed, res.dec, res.upd]);

    useEffect(() => { $("crumbSection").textContent = tab; }, [tab]);
    useEffect(() => { if (tab === "updates") load("upd"); if (tab === "rules") load("rules"); if (tab === "burn") load("burns"); }, [tab]);

    // a refresh that drops the selected row leaves none selected
    useEffect(() => {
      if (sel && ready && !row) setLastSel((p) => p[tab] === sel ? put(p, tab, null) : p);
    });

    useEffect(() => {
      $("statusMsg").textContent = outcome ? outcome.text : `${tab} · ${rows.length}`;
    }, [tab, rows.length, outcome]);
    useEffect(() => {
      const f = res.feed.data, last = f?.events.find((e) => e.kind === "run");
      $("statusMeta").textContent = !f ? "" : last ? `last run ${hhmm(last.t)}` : "no runs";
    }, [res.feed]);

    const failed = cur.needs.filter((n) => res[n].err !== null);
    const showOpen = open && !!row;
    const loadingNow = !ready && failed.length === 0;

    return <React.Fragment>
      {ReactDOM.createPortal(<Nav tabs={tabs} tab={tab} onTab={pickTab} />, $("amCol"))}
      {failed.length ? <div className="hub-pane-head hub-t3p-head">
        <div className="hub-error"><span>could not load {failed.map((n) => ({feed: "the feed", dec: "decisions", upd: "the updater log", rules: "the rules", burns: "the burn runs"})[n]).join(", ")}</span>
          <button type="button" className="hub-error-retry" onClick={() => reload(failed)}>retry</button></div>
      </div> : null}
      <div className="hub-split hub-t3p-split">
        <div className="hub-pane-col hub-t3p-list-col">
          <div className="hub-pane-list hub-t3p-list am-list">
            {cur.lanes ? <div className="hub-tags">{LANE_TAGS.map(([k, t]) =>
              <span key={k} className={`hub-tag${dlane === k ? " is-on" : ""}`} role="button" tabIndex={0} onClick={() => setDlane(k)}
                onKeyDown={(ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); ev.currentTarget.click(); } }}>{t}</span>)}</div> : null}
            {cur.stacks.map((s) => { const shut = s.fold && !rejOpen && !s.rows.some((r) => r.sel === sel); return <React.Fragment key={s.key}>
              {s.fold ? <button type="button" className="hub-list-eyebrow rx-fold" aria-expanded={!shut} onClick={() => setRejOpen(!rejOpen)}>{shut ? "▸" : "▾"} {s.title} · {s.rows.length}</button>
                : <div className="hub-list-eyebrow">{s.title} · {s.rows.length}</div>}
              {shut ? null : s.rows.map((r) => <Row key={r.sel} r={r} selected={r.sel === sel} onPick={pickRow} />)}
            </React.Fragment>; })}
            {loadingNow ? <div className="hub-empty-state">loading…</div> : null}
            {ready && !rows.length ? <div className="hub-empty-state">nothing here</div> : null}
          </div>
        </div>
        <div className="side-pane hub-t3p-side">
          <section className={`hub-detail-rail hub-slide-over context${showOpen ? " is-open" : ""}`}>
            <button type="button" className="hub-slide-over-close" aria-label="back to list" onClick={() => setOpen(false)}>← back</button>
            <div className="hub-detail-rail-inner context-inner hub-t3p-context am-detail">
              {row ? <Detail key={row.sel} cx={{row, post, busy, outcome, say, reload, res, cats, go}} /> : <div className="hub-empty-state">Pick an item.</div>}
            </div>
          </section>
        </div>
      </div>
    </React.Fragment>;
  }

  class Boundary extends Component {
    constructor(p) { super(p); this.state = {failed: false}; }
    static getDerivedStateFromError() { return {failed: true}; }
    componentDidCatch(e) { console.error("automations body failed", e); }
    render() { return this.state.failed ? <div className="hub-error">page failed to load</div> : this.props.children; }
  }

  const host = $("pane");
  function App() { return <Boundary><Body /></Boundary>; }

  if (host) {
    if ($("amCol")) $("amCol").textContent = "";  // the static rail would sit above the portal's
    ReactDOM.createRoot(host).render(<App />);
  }
  window.AutomationsUI.App = App;
})();
