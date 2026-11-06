/* crew page body (React), on the entry-3-pane origin. Ported from static/js/trip-access.js, the ◉
   top-bar panel that rode on every Hub page; that file is gone and this page is the one way to
   manage trip access (2026-10-17, Workbench set crew-access-page, option F).
   Left: what is waiting on Sam (trip submissions, code requests), then members, then denied.
   Middle: the picked one as cards. Right: keypad state, the share link, counts.
   Members are the same guest_codes rows as the requests; approved is simply the live state, so
   re-linking is an approve with a different person and revoking is a deny. No endpoints of its own:
   /trips/api/guest-codes, /trips/api/intakes, /trips/api/gate-freeze, /trips/api/share-url,
   /trips/preview/<id> and /trips/preview/off.
   Every guest-typed string reaches the DOM as React text, never as HTML: names are typed by anyone
   on the internet and land in Sam's private Hub. The mirror never serves this file (it is off
   public_app's /jsx allowlist and /trips/crew is withheld there). URL: ?p=<row key>. */
(() => {
  const { useState, useEffect, useRef } = React;
  const $ = (id) => document.getElementById(id);
  const isPhone = () => window.matchMedia("(max-width: 900px)").matches;
  const shellEl = () => document.querySelector(".hub-e3p");
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;

  const S = { codes: null, intakes: [], names: {}, sel: null, q: "", showDenied: false, note: null, preview: null, visible: [], listScroll: 0 };
  let bump = null;
  const rerender = () => { if (bump) bump((n) => n + 1); };

  // ── small helpers ────────────────────────────────────────────────────────

  let toastTimer = null;
  function toast(msg) {
    const el = $("toast");
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 4000);
  }

  // stored as UTC "YYYY-MM-DD HH:MM:SS"
  const at = (iso) => new Date(`${iso.replace(" ", "T")}Z`);
  function ago(iso) {
    if (!iso) return "";
    const mins = Math.max(0, Math.round((Date.now() - at(iso).getTime()) / 60000));
    if (mins < 60) return `${mins}m ago`;
    if (mins < 1440) return `${Math.round(mins / 60)}h ago`;
    return `${Math.round(mins / 1440)}d ago`;
  }
  function when(iso) {
    if (!iso) return "";
    return at(iso).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  }

  const tripNames = (ids) => ids.map((id) => S.names[id] || `#${id}`).join(", ");
  const nameOf = (r) => [r.first_name, r.last_name].filter(Boolean).join(" ") || r.name || "no name";
  const initials = (n) => n.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
  const people = () => (S.codes ? S.codes.people : []);
  const personFor = (key) => people().filter((p) => p.contact_slug === key)[0];
  const setNote = (key, text, err) => { S.note = { key: key, text: text, err: !!err }; rerender(); };

  function split() {
    const reqs = S.codes ? S.codes.requests : [];
    const by = (s) => reqs.filter((r) => r.status === s);
    const members = by("approved"), claimed = {};
    // one person holds one code, so anyone already claimed is unpickable for a second row
    members.forEach((r) => { if (r.contact_slug) claimed[r.contact_slug] = r.code; });
    return { pending: by("pending"), members: members, denied: by("denied"), claimed: claimed };
  }

  function codeById(id) { return (S.codes ? S.codes.requests : []).filter((r) => String(r.id) === id)[0]; }
  function itemFor(key) {
    const m = /^(c|i):(\d+)$/.exec(key || "");
    if (!m) return null;
    if (m[1] === "i") { const i = S.intakes.filter((x) => String(x.id) === m[2])[0]; return i ? { kind: "intake", i: i } : null; }
    const r = codeById(m[2]);
    return r ? { kind: r.status === "approved" ? "member" : r.status === "pending" ? "request" : "denied", r: r } : null;
  }

  // ── data ─────────────────────────────────────────────────────────────────

  /* All three in flight at once: none needs another's answer, only the render does. A dead
     intake queue must not take the people with it. */
  function load() {
    return Promise.all([
      fetch("/trips/api/trips/summary").then((r) => (r.ok ? r.json() : [])).catch(() => []),
      fetch("/trips/api/guest-codes").then((r) => (r.ok ? r.json() : null)).catch(() => null),
      fetch("/trips/api/intakes").then((r) => (r.ok ? r.json() : [])).catch(() => []),
    ]).then(([trips, codes, intakes]) => {
      S.names = {};
      (trips || []).forEach((t) => { S.names[t.id] = t.name; });
      S.intakes = intakes || [];
      if (codes) S.codes = codes;
      $("statusMsg").textContent = codes ? "" : "couldn't load the crew";
      if (S.sel && !itemFor(S.sel)) S.sel = null;
      if (!S.sel && !isPhone()) S.sel = firstKey();
      rerender();
    });
  }

  // a JSON call answered as { ok, j }, so a refusal's message reaches the note
  function call(url, method, body) {
    return fetch(url, {
      method: method,
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }).then((r) => r.json().then((j) => ({ ok: r.ok, j: j }), () => ({ ok: r.ok, j: {} })))
      .catch(() => ({ ok: false, j: { error: "couldn't reach the server" } }));
  }

  const patch = (id, body) => call(`/trips/api/guest-codes/${id}`, "PATCH", body);

  // ── selection, URL, keyboard, phone bar ──────────────────────────────────

  function firstKey() {
    const s = split();
    if (S.intakes.length) return `i:${S.intakes[0].id}`;
    const r = s.pending[0] || s.members[0];
    return r ? `c:${r.id}` : null;
  }

  /* push: true = new history entry (row click), false = replaceState (arrows, previous / next) */
  function select(key, push) {
    const url = `?p=${encodeURIComponent(key)}`;
    if (push && url !== location.search) history.pushState({ crewFromList: !new URLSearchParams(location.search).get("p") }, "", url);
    else if (push === false && url !== location.search) history.replaceState(history.state, "", url);
    S.sel = key;
    S.note = null;
    if (isPhone() && !shellEl().classList.contains("is-detail")) {
      S.listScroll = window.scrollY;
      shellEl().classList.add("is-detail");
      window.scrollTo(0, 0);
    }
    rerender();
  }

  function leaveDetail() {
    if (!shellEl().classList.contains("is-detail")) return;
    shellEl().classList.remove("is-detail");
    requestAnimationFrame(() => {
      window.scrollTo(0, S.listScroll || 0);
      const row = S.sel && $("entries").querySelector(`[data-key="${CSS.escape(S.sel)}"]`);
      if (row) { row.focus({ preventScroll: true }); row.scrollIntoView({ block: "nearest" }); }
    });
  }

  function barBack() {
    // only pop when the entry behind this one is the list; a direct ?p= load has none
    if (history.state?.crewFromList) history.back();
    else { history.replaceState(null, "", location.pathname); leaveDetail(); }
  }

  function fromUrl() {
    const key = new URLSearchParams(location.search).get("p");
    if (key) { S.sel = key; if (isPhone()) shellEl().classList.add("is-detail"); rerender(); }
    else if (isPhone()) leaveDetail();
  }

  function stepBy(d) {
    const i = S.visible.indexOf(S.sel);
    if (i >= 0 && S.visible[i + d] != null) select(S.visible[i + d], false);
  }

  // arrow keys on the list only, so the search box keeps its caret keys
  function onListKey(e) {
    const row = e.target.closest?.(".hub-e3p-entry");
    const ids = S.visible;
    if (!row || !ids.length) return;
    const cur = ids.indexOf(row.dataset.key);
    let n;
    if (e.key === "ArrowDown") n = Math.min(cur + 1, ids.length - 1);
    else if (e.key === "ArrowUp") n = Math.max(cur - 1, 0);
    else if (e.key === "Home") n = 0;
    else if (e.key === "End") n = ids.length - 1;
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(ids[cur], true); return; }
    else return;
    e.preventDefault();
    if (n === cur) return;
    select(ids[n], false);
    const next = $("entries").querySelector(`[data-key="${CSS.escape(ids[n])}"]`);
    next.focus({ preventScroll: true });
    next.scrollIntoView({ block: "nearest" });
  }

  // ── the list ─────────────────────────────────────────────────────────────

  function Entry({ k, t, s, v, dot }) {
    const on = S.sel === k;
    return (
      <div className={`hub-e3p-entry${on ? " active" : ""}`} role="option" tabIndex={0} aria-selected={on} data-key={k} onClick={() => { select(k, true); }}>
        <span className="hub-e3p-entry-mark">{dot ? <span className="crew-dot" /> : null}</span>
        <span className="hub-e3p-entry-t">{t}</span>
        <span className="hub-e3p-entry-s">{s}</span>
        <span className="hub-e3p-entry-v">{v}</span>
      </div>
    );
  }

  function Group({ label, n, children }) {
    return <div className="hub-e3p-group">{label}<span className="hub-e3p-group-n">{n}</span>{children}</div>;
  }

  function List() {
    const s = split();
    const q = S.q.trim().toLowerCase();
    const hit = (...xs) => !q || xs.join(" ").toLowerCase().includes(q);
    const rowText = (r) => {
      const p = personFor(r.contact_slug);
      return [nameOf(r), r.phone, r.email, p ? tripNames(p.trip_ids) : ""];
    };
    const intakes = S.intakes.filter((i) => hit(i.trip_name, i.guest_key));
    const pending = s.pending.filter((r) => hit(...rowText(r)));
    const members = s.members.filter((r) => hit(...rowText(r)));
    const denied = s.denied.filter((r) => hit(...rowText(r)));
    const showDenied = S.showDenied || (q && denied.length);
    const keys = [];
    const out = [];
    if (intakes.length + pending.length) {
      out.push(<Group key="gw" label="Waiting on you" n={intakes.length + pending.length} />);
      intakes.forEach((i) => {
        keys.push(`i:${i.id}`);
        out.push(<Entry key={`i:${i.id}`} k={`i:${i.id}`} dot t={`${i.trip_name || `#${i.trip_id}`} changes`} s={`from ${i.guest_key.replace(/^name:/, "")}, ${ago(i.submitted_at)}`} />);
      });
      pending.forEach((r) => {
        keys.push(`c:${r.id}`);
        out.push(<Entry key={`c:${r.id}`} k={`c:${r.id}`} dot t={nameOf(r)} s={`code request, ${ago(r.created_at)}`} />);
      });
    }
    out.push(<Group key="gm" label="Members" n={members.length} />);
    if (!members.length) out.push(<div key="me" className="crew-empty">{q ? "no member matches" : "no one holds a code yet"}</div>);
    members.forEach((r) => {
      const p = personFor(r.contact_slug);
      keys.push(`c:${r.id}`);
      out.push(<Entry key={`c:${r.id}`} k={`c:${r.id}`} t={nameOf(r)} v={p ? p.trip_ids.length : 0}
        s={`${p ? tripNames(p.trip_ids) : "opens nothing"} · ${r.last_seen ? ago(r.last_seen) : "never signed in"}`} />);
    });
    // Denied rows are kept so a denied code cannot be instantly resubmitted, but they are
    // history: folded unless opened or a search reaches into them.
    if (denied.length) {
      out.push(
        <Group key="gd" label="Denied" n={denied.length}>
          <button type="button" className="hub-btn crew-fold" aria-expanded={!!showDenied} onClick={() => { S.showDenied = !S.showDenied; rerender(); }}>{showDenied ? "hide" : "show"}</button>
        </Group>
      );
      if (showDenied) {
        denied.forEach((r) => {
          keys.push(`c:${r.id}`);
          out.push(<Entry key={`c:${r.id}`} k={`c:${r.id}`} t={nameOf(r)} s={`denied ${ago(r.decided_at)}`} />);
        });
      }
    }
    S.visible = keys;
    return out;
  }

  // ── middle: the picked one ───────────────────────────────────────────────

  function Note({ k }) {
    const n = S.note;
    if (!n || n.key !== k || !n.text) return null;
    return <p className={`crew-note${n.err ? " is-err" : ""}`} role="status">{n.text}</p>;
  }

  function Card({ title, sum, children }) {
    return (
      <section className="hub-plate-card">
        <div className="hub-section-head"><span className="hub-section-head-t">{title}</span><span className="hub-section-head-sum">{sum}</span></div>
        <div className="crew-body">{children}</div>
      </section>
    );
  }

  /* The picker of who a code belongs to. A taken person is disabled, not hidden, so the list
     still says why they are missing; db.approve_guest_code refuses a second code too. */
  function Who({ value, claimed, blank, onChange }) {
    const orphan = value && !personFor(value);
    return (
      <select className="hub-input" value={value || ""} onChange={(e) => { onChange(e.target.value); }}>
        {blank ? <option value="">who is this?</option> : null}
        {orphan ? <option value={value}>{`${value.replace(/^name:/, "")} · on no trip`}</option> : null}
        {people().map((p) => {
          const taken = claimed[p.contact_slug] && p.contact_slug !== value;
          return <option key={p.contact_slug} value={p.contact_slug} disabled={!!taken}>
            {`${p.name} · ${taken ? `has code ${claimed[p.contact_slug]}` : plural(p.trip_ids.length, "trip")}`}</option>;
        })}
      </select>
    );
  }

  /* One inline field. Commits on blur or Enter, reverts on Escape, puts the old value back
     when the save fails. Uncontrolled on purpose: the address dropdown writes the value
     itself, and a reload must not rebuild the field being typed in. */
  function Field({ r, k, label, type, max, addr }) {
    const ref = useRef(null), was = useRef(r[k] || "");
    useEffect(() => {
      // attached before React's handlers run (React listens at the root), so Enter on a
      // highlighted suggestion picks it first and the commit-on-Enter saves what was picked
      if (addr && window.AddrCombo) window.AddrCombo.attach(ref.current);
    }, []);
    function save() {
      const el = ref.current, next = el.value.trim();
      if (next === was.current) return;
      patch(r.id, { [k]: next }).then((res) => {
        if (!res.ok) { el.value = was.current; setNote(`c:${r.id}`, res.j.error || "couldn't save that", true); return; }
        was.current = next;
        Object.assign(r, res.j);
        S.note = null;
        toast("saved");
        rerender();
      });
    }
    return <input ref={ref} className={`hub-input crew-edit crew-edit-${k}`} defaultValue={r[k] || ""} type={type || "text"} maxLength={max}
      aria-label={label} placeholder={label} onBlur={save}
      onKeyDown={(e) => { if (e.key === "Enter") e.target.blur(); else if (e.key === "Escape") { e.target.value = was.current; e.target.blur(); } }} />;
  }

  /* The code as the keypad's four digits. Typing a digit moves on; leaving the four commits.
     Checked here because a bad code is a typo the server would answer the same way a round
     trip later; everything else is validated where it is stored. */
  function Keys({ r }) {
    const refs = [useRef(null), useRef(null), useRef(null), useRef(null)];
    const was = useRef(r.code || "");
    const reset = () => { refs.forEach((x, i) => { x.current.value = was.current[i] || ""; }); };
    function commit() {
      const next = refs.map((x) => x.current.value).join("");
      if (next === was.current) return;
      if (!/^\d{4}$/.test(next)) { reset(); setNote(`c:${r.id}`, "a code is four digits", true); return; }
      patch(r.id, { code: next }).then((res) => {
        if (!res.ok) { reset(); setNote(`c:${r.id}`, res.j.error || "couldn't save that", true); return; }
        was.current = next;
        toast(`code changed to ${next}`);
        load();  // the code is in every other row's picker, so this one reloads
      });
    }
    function onInput(i, e) {
      const d = e.target.value.replace(/\D/g, "").slice(-1);
      e.target.value = d;
      if (d && i < 3) refs[i + 1].current.focus();
      else if (d) e.target.blur();
    }
    function onKey(i, e) {
      if (e.key === "Backspace" && !e.target.value && i > 0) refs[i - 1].current.focus();
      else if (e.key === "Enter") e.target.blur();
      else if (e.key === "Escape") { reset(); e.target.blur(); }
    }
    return (
      <div className="crew-keys" onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) commit(); }}>
        {refs.map((x, i) => <input key={i} ref={x} className="hub-input crew-key" defaultValue={(r.code || "")[i] || ""}
          inputMode="numeric" maxLength={2} aria-label={`code digit ${i + 1}`}
          onFocus={(e) => { e.target.select(); }} onInput={(e) => { onInput(i, e); }} onKeyDown={(e) => { onKey(i, e); }} />)}
      </div>
    );
  }

  function Revoke({ r }) {
    const [armed, setArmed] = useState(false);
    const timer = useRef(null);
    useEffect(() => () => clearTimeout(timer.current), []);
    // not undoable by picking again (the code stops working), so it asks once, in place
    function click() {
      if (!armed) {
        setArmed(true);
        timer.current = setTimeout(() => { setArmed(false); }, 3000);
        return;
      }
      clearTimeout(timer.current);
      call(`/trips/api/guest-codes/${r.id}`, "DELETE").then(() => { toast("access revoked"); load(); });
    }
    return <button type="button" className="hub-btn hub-btn--danger" onClick={click}>{armed ? "sure?" : "revoke code"}</button>;
  }

  function relink(r, slug, msg) {
    if (!slug) return;
    patch(r.id, { status: "approved", contact_slug: slug }).then((res) => {
      if (res.ok) { toast(msg); load(); } else setNote(`c:${r.id}`, res.j.error || "couldn't save", true);
    });
  }

  function MemberCards({ r, claimed }) {
    const p = personFor(r.contact_slug), k = `c:${r.id}`;
    return (
      <React.Fragment>
        <Card title="identity" sum={[r.phone, r.email].filter(Boolean).join(" · ")}>
          <div className="crew-id">
            <span className="crew-ini" aria-hidden="true">{initials(nameOf(r))}</span>
            <div className="crew-fields">
              <Field r={r} k="first_name" label="first name" max={40} />
              <Field r={r} k="last_name" label="last name" max={40} />
              <Field r={r} k="phone" label="phone" type="tel" max={30} />
              <Field r={r} k="email" label="email" type="email" max={120} />
              <Field r={r} k="address" label="address" max={200} addr />
            </div>
          </div>
          <Keys r={r} />
          <p className="crew-dim">Tap the digits to set a new code.</p>
          <Note k={k} />
        </Card>
        <Card title="access" sum={p ? plural(p.trip_ids.length, "trip") : "opens nothing"}>
          {/* linked to someone on no trip: looks like working access until they try it */}
          {p ? <p>Their code opens <b>{plural(p.trip_ids.length, "trip")}</b>, the ones they are on.</p>
            : <div className="hub-callout-warn">Linked to <b>{(r.contact_slug || "").replace(/^name:/, "")}</b>, who is on no trip. The code opens nothing.</div>}
          {p && p.trip_ids.length ? <div className="hub-tags">{p.trip_ids.map((id) => <span key={id} className="hub-tag is-on">{S.names[id] || `#${id}`}</span>)}</div> : null}
          {/* saves on change: a wrong pick is undone by picking again, so a confirm only adds a click */}
          <label className="crew-lab">Linked to<Who value={r.contact_slug} claimed={claimed} onChange={(v) => { relink(r, v, "access re-linked"); }} /></label>
          <p className="crew-dim">{r.last_seen ? `Last in ${ago(r.last_seen)}.` : "Never signed in."}</p>
        </Card>
        <Card title="history" sum="from three dates">
          <ol className="crew-hist">
            <li><b>Asked for a code</b><span className="crew-dim">{when(r.created_at)}</span></li>
            <li><b>{`Approved, linked to ${p ? p.name : (r.contact_slug || "").replace(/^name:/, "")}`}</b><span className="crew-dim">{when(r.decided_at)}</span></li>
            <li><b>{r.last_seen ? "Last in" : "Never signed in"}</b><span className="crew-dim">{when(r.last_seen)}</span></li>
          </ol>
        </Card>
        <Card title="actions" sum="">
          <div className="hub-btn-row">
            {/* a preview on Hub, not a sign-in on the mirror: nothing is signed into and last_seen
                is untouched, because a preview is not a sign-in */}
            <button type="button" className="hub-btn" onClick={() => { S.preview = { id: r.id, name: nameOf(r) }; rerender(); }}>{`view as ${r.first_name || nameOf(r)}`}</button>
            <Revoke key={r.id} r={r} />
          </div>
          <p className="crew-dim">Revoking stops the code at once. It asks once first.</p>
        </Card>
      </React.Fragment>
    );
  }

  function RequestCards({ r, claimed }) {
    const [pick, setPick] = useState("");
    const p = personFor(pick), k = `c:${r.id}`;
    function approve() {
      if (!pick) { setNote(k, "pick who this is first", true); return; }
      relink(r, pick, "code approved");
    }
    return (
      <Card title="code request" sum={`asked ${ago(r.created_at)}`}>
        {/* read-only here: if the details are wrong they are editable once it is a member */}
        <p className="crew-dim">{[r.phone, r.email].filter(Boolean).join(" · ") || "no contact details"}</p>
        <p>Wants the code <b className="crew-code">{r.code}</b>.</p>
        <label className="crew-lab">Who is this?<Who value={pick} claimed={claimed} blank onChange={(v) => { setPick(v); S.note = null; }} /></label>
        <p className="crew-dim">{p ? `Approving opens: ${tripNames(p.trip_ids) || "nothing yet"}` : "Pick who this is to see what approving opens."}</p>
        <div className="hub-btn-row">
          <button type="button" className="hub-btn hub-btn--accent" onClick={approve}>approve</button>
          <button type="button" className="hub-btn hub-btn--danger" onClick={() => { call(`/trips/api/guest-codes/${r.id}`, "DELETE").then(() => { toast("request denied"); load(); }); }}>deny</button>
        </div>
        <Note k={k} />
      </Card>
    );
  }

  /* Trip submissions: the diff Sam is approving. Added rows in full, removed rows struck
     through, changed fields old -> new. Crew rows match a code to a person by name, so they
     are access changes and say so. */
  function diffLines(d) {
    const out = [];
    const label = (k) => d.labels?.[k] || k;
    const rowText = (r) => Object.keys(r).filter((k) => k !== "key" && r[k] !== null && r[k] !== "").map((k) => `${k}: ${r[k]}`).join(" · ");
    const access = (sec, what) => (sec === "members" ? <b className="crew-access">{` ${what} trip access`}</b> : null);
    Object.keys(d.trip || {}).forEach((f) => { out.push(<li key={`t${f}`}>{`${f}: ${d.trip[f][0]} → ${d.trip[f][1]}`}</li>); });
    Object.keys(d.added || {}).forEach((sec) => d.added[sec].forEach((r, n) => {
      out.push(<li key={`a${sec}${n}`} className="crew-add">{`+ ${sec} · ${rowText(r)}`}{access(sec, "grants")}</li>);
    }));
    Object.keys(d.removed || {}).forEach((sec) => d.removed[sec].forEach((k) => {
      out.push(<li key={`r${sec}${k}`} className="crew-del">{`${sec} · ${label(k)}`}{access(sec, "removes")}</li>);
    }));
    Object.keys(d.changed || {}).forEach((sec) => Object.keys(d.changed[sec]).forEach((k) => {
      const f = d.changed[sec][k];
      out.push(<li key={`c${sec}${k}`}>{`${sec} · ${label(k)} · ${Object.keys(f).map((n) => `${n}: ${f[n][0]} → ${f[n][1]}`).join(", ")}`}</li>);
    }));
    return out.length ? out : [<li key="none">no changes</li>];
  }

  function IntakeCards({ i }) {
    const k = `i:${i.id}`;
    function act(verb) {
      call(`/trips/api/intakes/${i.id}/${verb}`, "POST", {}).then((res) => {
        if (!res.ok) { setNote(k, res.j.error || "couldn't save", true); return; }
        const n = (res.j.apply_log?.conflicts || []).length;
        toast(verb === "approve" ? (n ? `applied, ${plural(n, "field")} skipped (changed since)` : "changes applied") : "submission rejected");
        load();
      });
    }
    return (
      <Card title={i.trip_name || `#${i.trip_id}`} sum={`from ${i.guest_key.replace(/^name:/, "")} · sent ${ago(i.submitted_at)}`}>
        <ul className="crew-diff">{diffLines(i.diff || {})}</ul>
        <div className="hub-btn-row">
          <button type="button" className="hub-btn hub-btn--accent" onClick={() => { act("approve"); }}>apply to the trip</button>
          <button type="button" className="hub-btn hub-btn--danger" onClick={() => { act("reject"); }}>reject</button>
        </div>
        <Note k={k} />
      </Card>
    );
  }

  function DeniedCards({ r }) {
    return (
      <Card title="denied" sum={when(r.decided_at)}>
        <p className="crew-dim">{[r.phone, r.email].filter(Boolean).join(" · ") || "no contact details"}</p>
        <p>Asked with the code <b className="crew-code">{r.code}</b> {ago(r.created_at)}.</p>
        <p className="crew-dim">Kept so the same code cannot be sent in again straight away.</p>
      </Card>
    );
  }

  /* The person's lifecycle as the origin's stage track: asked, approved, signed in, with
     denied set apart. Display only, so the stages are spans, not tabs to press. */
  function Track({ r }) {
    const st = [
      { l: "asked", s: ago(r.created_at), done: true },
      { l: "approved", s: r.status === "approved" ? ago(r.decided_at) : "", done: r.status === "approved", now: r.status === "pending" },
      { l: "signed in", s: r.last_seen ? ago(r.last_seen) : "", done: !!r.last_seen, now: r.status === "approved" && !r.last_seen },
      { l: "denied", s: r.status === "denied" ? ago(r.decided_at) : "", done: r.status === "denied", apart: true },
    ];
    return st.map((x) => (
      <span key={x.l} className={`hub-tab${x.done ? " is-done" : ""}${x.now ? " is-now" : ""}${x.apart ? " is-apart" : ""}`}>
        <span className="hub-e3p-stage-dot" />{x.l}<span className="hub-e3p-stage-sub">{x.s || " "}</span>
      </span>
    ));
  }

  // ── right rail ───────────────────────────────────────────────────────────

  function copyShare() {
    // fetched on click rather than baked in, so it tracks /share and /unshare without a reload
    toast("reading share link…");
    fetch("/trips/api/share-url").then((r) => r.json()).then((d) => {
      if (!d.url) { toast("not shared right now, run /share to open the funnel"); return; }
      // clipboard writes need a secure context; a plain-http LAN address is not one
      return navigator.clipboard.writeText(d.url).then(() => { toast(`share link copied · ${d.url}`); })
        .catch(() => { toast(`copy blocked, the link is ${d.url}`); });
    }).catch(() => { toast("couldn't read the share link"); });
  }

  function Rail({ s }) {
    const st = (S.codes && S.codes.stats) || {};
    const never = s.members.filter((r) => !r.last_seen).length;
    return (
      <React.Fragment>
        {/* past the fifth strike the keypad stays shut until reopened here: loud on purpose,
            a frozen gate means someone was walking the code space */}
        <section className="hub-detail-card">
          <div className="hub-detail-card-head">keypad</div>
          {st.frozen_until ? (
            <div className="hub-callout-warn">{st.needs_clearing ? "Locked after " : "Paused after "}<b>{plural(st.strikes, "strike")}</b>
              {st.needs_clearing ? ". No one can enter a code." : ". Reopens on its own."}</div>
          ) : <p className="crew-big">open</p>}
          {st.frozen_until ? <div className="hub-btn-row crew-gap"><button type="button" className="hub-btn" onClick={() => {
            call("/trips/api/gate-freeze", "DELETE").then(() => { toast("keypad reopened"); load(); });
          }}>reopen</button></div> : null}
          <p className="crew-dim">{st.fails ? `${plural(st.fails, "wrong code")}, last on ${when(st.last_fail_at)}.` : "No wrong codes yet."} It pauses itself after a burst and locks after the fifth strike.</p>
        </section>
        <section className="hub-detail-card">
          <div className="hub-detail-card-head">share link</div>
          <p className="crew-dim">The public planner, for anyone with a code.</p>
          <div className="hub-btn-row crew-gap"><button type="button" className="hub-btn" onClick={copyShare}>copy link</button></div>
        </section>
        <section className="hub-detail-card">
          <div className="hub-detail-card-head">access</div>
          <div className="hub-kv-row"><span>Members</span><b>{s.members.length}</b></div>
          <div className="hub-kv-row"><span>Waiting on you</span><b>{s.pending.length + S.intakes.length}</b></div>
          <div className="hub-kv-row"><span>Never signed in</span><b>{never}</b></div>
          <div className="hub-kv-row"><span>Denied</span><b>{s.denied.length}</b></div>
        </section>
      </React.Fragment>
    );
  }

  /* "view as", in the same window. The preview flag lives in Sam's own session, so
     closing always clears it, or the next /trips he opens is still someone else's board. */
  function Preview() {
    const p = S.preview;
    const close = () => { S.preview = null; rerender(); fetch("/trips/preview/off"); };
    useEffect(() => {
      const onKey = (e) => { if (e.key === "Escape") close(); };
      document.addEventListener("keydown", onKey);
      return () => { document.removeEventListener("keydown", onKey); };
    }, []);
    // a frame that lands somewhere that is not a preview would make the bar lie about who is
    // being viewed, so the overlay closes with it; body.guest is what preview mode sets
    function onLoad(e) {
      try {
        const d = e.target.contentDocument;
        if (d?.body && !d.body.classList.contains("guest")) close();
      } catch { /* not ours to read: leave the overlay to its button */ }
    }
    return (
      <div className="crew-prev">
        <div className="crew-prev-bar"><span>{`viewing as ${p.name}`}</span><button type="button" className="hub-btn" onClick={close}>exit preview</button></div>
        <iframe className="crew-prev-frame" title="preview" src={`/trips/preview/${p.id}`} onLoad={onLoad} />
      </div>
    );
  }

  // ── the page ─────────────────────────────────────────────────────────────

  function App() {
    const [, setN] = useState(0);
    bump = setN;
    useEffect(() => {
      $("crew-root").setAttribute("data-react-mounted", "crew");
      window.addEventListener("popstate", fromUrl);
      const key = new URLSearchParams(location.search).get("p");
      if (key) { S.sel = key; if (isPhone()) shellEl().classList.add("is-detail"); }
      load();
      return () => { window.removeEventListener("popstate", fromUrl); };
    }, []);

    const s = split();
    const list = List();  // also sets S.visible, which the phone bar reads
    const it = itemFor(S.sel);
    const i = S.visible.indexOf(S.sel);
    const r = it && it.r;
    const head = !it ? { sub: "crew", t: S.codes ? "pick someone" : "loading…" }
      : it.kind === "intake" ? { sub: "trip submission", t: `${it.i.trip_name || `#${it.i.trip_id}`} changes` }
      : { sub: it.kind === "request" ? "code request" : it.kind, t: nameOf(r) };

    return (
      <React.Fragment>
        <section className="col hub-e3p-list-col">
          <div className="hub-e3p-tools">
            <div className="hub-lf"><div className="hub-lf-bar"><input type="search" className="hub-lf-search" placeholder="search people and trips" aria-label="search people and trips"
              onChange={(e) => { S.q = e.target.value; rerender(); }} /></div></div>
          </div>
          <div className="hub-e3p-entries" id="entries" role="listbox" aria-label="crew" onKeyDown={onListKey}>{list}</div>
        </section>

        <section className="col hub-e3p-pane">
          <div className="hub-e3p-bar">
            <button type="button" className="hub-e3p-back" onClick={barBack}><span aria-hidden="true">‹</span> all crew</button>
            <span className="hub-e3p-pos">{i < 0 ? "–" : `${i + 1} / ${S.visible.length}`}</span>
            <button type="button" className="hub-e3p-nav" aria-label="previous" disabled={i <= 0} onClick={() => { stepBy(-1); }}>‹</button>
            <button type="button" className="hub-e3p-nav" aria-label="next" disabled={i < 0 || i >= S.visible.length - 1} onClick={() => { stepBy(1); }}>›</button>
          </div>

          <div className="hub-split hub-e3p-split">
            <div className="hub-e3p-main">
              <div className="hub-e3p-head hub-plate-card">
                <div className="hub-e3p-head-row">
                  <span><span className="hub-e3p-head-sub">{head.sub}</span><span className="hub-e3p-head-sep" aria-hidden="true">·</span><span className="hub-e3p-head-t">{head.t}</span></span>
                  <div className="hub-e3p-head-acts">
                    {it && it.kind === "request" ? <span className="hub-pill is-warn">waiting</span> : null}
                    {it && it.kind === "intake" ? <span className="hub-pill is-warn">waiting</span> : null}
                  </div>
                </div>
                {/* hidden on a submission: it has no lifecycle of its own */}
                <div className="hub-tabs hub-e3p-stages" hidden={!r}>{r ? <Track r={r} /> : null}</div>
              </div>

              <div className="hub-e3p-cards" id="cards">
                {!it ? null
                  : it.kind === "intake" ? <IntakeCards key={S.sel} i={it.i} />
                  : it.kind === "member" ? <MemberCards key={S.sel} r={r} claimed={s.claimed} />
                  : it.kind === "request" ? <RequestCards key={S.sel} r={r} claimed={s.claimed} />
                  : <DeniedCards key={S.sel} r={r} />}
                <div className="hub-e3p-empty" hidden={!!it}>{S.codes ? "pick someone on the left" : ""}</div>
              </div>
            </div>

            <section className="col hub-detail-rail hub-e3p-rail" id="rail"><Rail s={s} /></section>
          </div>
        </section>
        {S.preview ? <Preview /> : null}
      </React.Fragment>
    );
  }

  // a render error leaves a message instead of a blank page
  class Boundary extends React.Component {
    constructor(p) { super(p); this.state = { failed: false }; }
    static getDerivedStateFromError() { return { failed: true }; }
    componentDidCatch(e) { console.error("crew render failed", e); }
    render() { return this.state.failed ? <div className="hub-error">page failed to load</div> : this.props.children; }
  }

  ReactDOM.createRoot($("crew-root")).render(<Boundary><App /></Boundary>);
})();
