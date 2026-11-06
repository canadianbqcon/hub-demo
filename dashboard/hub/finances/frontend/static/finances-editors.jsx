/* Finances · 4 of 5 (React): the two panels that write, the manual-entry form on the earnings tab and
   the owed tab (money other people owe him, data/owed.db). Ported from finances.js lines 634-704
   and 1651-2091. The plain page bound one delegated listener to the owed panel and read rows back
   out of the DOM; here each button carries its own handler, but every request keeps the plain
   body, method and order, and the native prompt / confirm / clipboard / window.open calls are the
   same. Forms are controlled and call preventDefault. The handles form stays disabled until the
   owed list has loaded (its rows and its "what changed" check come from that list), and every
   (re)load of the list redraws the lists from fresh state, as the plain page's innerHTML did.
   Assigns into window.FinancesUI; declares nothing else at top level. */
(() => {
  const { useState, useEffect, useRef } = React;
  const U = window.FinancesUI;
  const { moneyC, plural, owedDate, postJSON } = U;

  // ── Manual entry form (earnings tab) ────────────────────────────────────────

  const BLANK_MANUAL = { source: "", source_type: "", period_start: "", period_end: "", gross: "", net: "", hours: "", notes: "" };

  function ManualForm({ open, onSaved }) {
    const [f, setF] = useState(BLANK_MANUAL);
    const [err, setErr] = useState(null);
    const sourceRef = useRef(null);
    const first = useRef(true);
    const set = (k) => (e) => { const v = e.target.value; setF(prev => Object.assign({}, prev, { [k]: v })); };

    // opening clears the error and lands on the first field; closing by the toggle resets a
    // half-filled form so it doesn't linger for the next open
    useEffect(() => {
      if (first.current) { first.current = false; return; }
      if (open) { setErr(null); sourceRef.current.focus(); }
      else { setF(BLANK_MANUAL); setErr(null); }
    }, [open]);

    function submit(ev) {
      ev.preventDefault();
      setErr(null);
      // the body is every field in form order, the numbers coerced; blank hours and notes are left out
      const fd = { source: f.source, source_type: f.source_type, period_start: f.period_start,
                   period_end: f.period_end, gross: f.gross, net: f.net, hours: f.hours, notes: f.notes };
      ["gross", "net", "hours"].forEach(k => {
        if (fd[k] !== "" && fd[k] != null) fd[k] = Number(fd[k]);
        else if (k === "hours") delete fd[k]; // optional
      });
      if (!fd.notes) delete fd.notes; // optional

      // client-side sanity checks, the server is the authoritative guard, this just
      // catches the obvious typo before a round trip.
      if (fd.period_end < fd.period_start) {
        setErr("period end can't be before period start.");
        return;
      }
      if (fd.net > fd.gross) {
        setErr("net can't be greater than gross.");
        return;
      }

      fetch("/finances/api/manual", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fd),
      }).then(res => {
        if (res.ok) {
          setF(BLANK_MANUAL);
          return onSaved();
        }
        return res.json().catch(() => ({})).then(body => {
          setErr(body.error || "save failed \u2014 check the values and try again.");
        });
      }).catch(e => {
        console.error("manual submit failed:", e);
        setErr("network error \u2014 check your connection and try again.");
      });
    }

    return (
      <div className={`manual-wrap${open ? " open" : ""}`} id="manual-wrap">
       <div className="manual-panel">
        <div className="hub-error" id="manual-error" aria-live="polite" hidden={!err}>{err}</div>
        <form id="manual-form" onSubmit={submit}>
          <label htmlFor="f-source" className="sr-only">source</label>
          <input id="f-source" name="source" placeholder="source (e.g. freelance-x)" required ref={sourceRef}
                 value={f.source} onChange={set("source")} />

          <label htmlFor="f-source-type" className="sr-only">source type</label>
          <select id="f-source-type" name="source_type" required value={f.source_type} onChange={set("source_type")}>
            <option value="">-- type --</option>
            <option value="venture">venture</option>
            <option value="salaried">salaried</option>
            <option value="tipped_hourly">tipped hourly</option>
            <option value="investment">investment</option>
            <option value="benefits">benefits</option>
          </select>

          <label htmlFor="f-period-start" className="sr-only">period start</label>
          <input id="f-period-start" name="period_start" type="date" required value={f.period_start} onChange={set("period_start")} />

          <label htmlFor="f-period-end" className="sr-only">period end</label>
          <input id="f-period-end" name="period_end" type="date" required value={f.period_end} onChange={set("period_end")} />

          <label htmlFor="f-gross" className="sr-only">gross</label>
          <input id="f-gross" name="gross" type="number" step="0.01" placeholder="gross" required value={f.gross} onChange={set("gross")} />

          <label htmlFor="f-net" className="sr-only">net</label>
          <input id="f-net" name="net" type="number" step="0.01" placeholder="net" required value={f.net} onChange={set("net")} />

          <label htmlFor="f-hours" className="sr-only">hours (optional)</label>
          <input id="f-hours" name="hours" type="number" step="0.01" placeholder="hours (optional)" value={f.hours} onChange={set("hours")} />

          <label htmlFor="f-notes" className="sr-only">notes (optional)</label>
          <input id="f-notes" name="notes" placeholder="notes (optional)" value={f.notes} onChange={set("notes")} />

          <div className="form-actions">
            <button type="submit">save</button>
          </div>
        </form>
       </div>
      </div>
    );
  }
  U.ManualForm = ManualForm;

  // ── Owed ────────────────────────────────────────────────────────────────────
  // consumes: /finances/api/owed (GET, POST, PATCH /<id>, DELETE /<id>) and its /request, /handle and
  // /payments routes. The mirror of the debt tab: that one is what he owes, this one is what he is
  // owed. Replaces personal/money-owed-to-me.md, which could only be marked paid
  // by hand-editing a markdown table nobody opens.

  // "asked for" is the distinction the markdown could not carry: an unrequested
  // debt is not a slow payer, it is a message he never sent.
  const OWED_ACTS = [
    { act: "request", label: "ask",   when: r => r.status === "open" && r.dir !== -1 },
    { act: "open",    label: "unask", when: r => r.status === "requested" && r.dir !== -1 },
    { act: "paid",    label: "paid",  when: r => r.status !== "paid" },
  ];

  const BLANK_OWED = { person: "", what: "", amount: "", incurred: "", paid_out: "", grp: "", note: "" };

  // Venmo's default username at signup is the person's name hyphenated, so this is
  // a decent first guess and a terrible fact. It is offered as a prefilled value he
  // confirms, never saved on its own: a handle that is wrong but real belongs to a
  // stranger, and the only thing standing between a guess and charging them is him
  // reading the profile Venmo shows before he taps send.
  function guessHandle(name) {
    return (name || "").trim().split(/\s+/).filter(Boolean).join("-");
  }

  // a note he can open to read in full (the plain page toggled `is-open` on click)
  function OwedNote({ children }) {
    const [on, setOn] = useState(false);
    const flip = () => setOn(o => !o);
    return <span className={`owed-note${on ? " is-open" : ""}`} role="button" tabIndex={0} aria-expanded={on}
                 onClick={flip} onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); flip(); } }}>{children}</span>;
  }

  // Every debtor's Venmo handle in one pass. Nothing in Gmail carries another person's handle, so
  // these are typed once and kept. Each row is prefilled with the stored handle; an untouched blank
  // row must compare equal to "no handle" and is never sent.
  function HandlesForm({ d, send }) {
    const known = d ? (d.handles || {}) : {};
    const people = d ? [...new Set([...d.people.map(p => p.person), ...d.settled.map(r => r.person)])].sort() : [];
    const [vals, setVals] = useState(() => {
      const o = {};
      people.forEach(n => { o[n] = known[n] || ""; });
      return o;
    });
    return (
      <form id="owed-handles-form" onSubmit={ev => {
        ev.preventDefault();
        // Only what he actually typed is sent, and only where it differs from what is stored.
        send(people.map(n => ({ person: n, venmo: vals[n].trim() })).filter(r => r.venmo !== (known[r.person] || "")));
      }}>
        <div className="owed-handle-rows" id="owed-handle-rows">{people.map(n => (
          <label className="owed-handle-row" key={n}>
            <span className="owed-handle-who">{n}</span>
            <span className="owed-handle-at">@</span>
            <input name={n} value={vals[n]} placeholder={guessHandle(n)} spellCheck={false} autoComplete="off"
                   onChange={e => { const v = e.target.value; setVals(prev => Object.assign({}, prev, { [n]: v })); }} />
          </label>))}</div>
        <div className="form-actions">
          <button type="submit" disabled={!d}>save handles</button>
        </div>
      </form>
    );
  }

  // Live "$X of $Y selected", so a payment that does not add up to the lines
  // picked is visible before it is applied rather than after.
  function PayCard({ p, owedErr, reload }) {
    const [picked, setPicked] = useState(() => new Set((p.candidates || []).filter(l => l.suggested).map(l => l.id)));
    const cands = p.candidates || [];
    let sum = 0;
    cands.forEach(l => { if (picked.has(l.id)) sum += l.due; });
    const off = sum < p.amount - 0.005;  // money left with no line to land on
    // Short is fine now (it deducts, oldest line first); say what stays open.
    const sumText = !sum ? "" : sum > p.amount + 0.005
      ? `${moneyC(p.amount)} toward ${moneyC(sum)} · ${moneyC(sum - p.amount)} stays open`
      : `${moneyC(sum)} of ${moneyC(p.amount)}`;
    return (
      <article className="owed-pay" data-pid={p.id}>
        <header className="owed-pay-head">
          <span className="owed-pay-who">{p.matched_person
            ? p.matched_person
            : <React.Fragment>{p.person} <span className="cat-tag">no open debt under this name</span></React.Fragment>}</span>
          <span className="owed-pay-amt">{moneyC(p.amount)}</span>
        </header>
        <div className="owed-pay-meta">{`${owedDate(p.received)} · ${p.method}${p.note ? ` · “${p.note}”` : ""}`}</div>
        {cands.length ? <div className="owed-picks">{cands.map(l => (
          <label className="owed-pick" key={l.id}><input type="checkbox" value={l.id} checked={picked.has(l.id)}
            onChange={() => setPicked(prev => { const n = new Set(prev); n.has(l.id) ? n.delete(l.id) : n.add(l.id); return n; })} />
            <span className="owed-pick-what">{l.what}</span>
            <span className="owed-pick-amt">{moneyC(l.due)}</span></label>))}</div> : null}
        <footer className="owed-pay-foot">
          <span className={`owed-pay-sum${off && sum > 0 ? " is-off" : ""}`}>{sumText}</span>
          {cands.length ? <button type="button" data-pay="apply" onClick={() => {
            const ids = cands.filter(l => picked.has(l.id)).map(l => Number(l.id));
            if (!ids.length) { owedErr("tick the lines this payment covers first."); return; }
            postJSON(`/finances/api/owed/payments/${p.id}/apply`, { owed_ids: ids }).then(reload);
          }}>apply to these</button> : null}
          <button type="button" data-pay="ignore"
                  onClick={() => postJSON(`/finances/api/owed/payments/${p.id}`, { status: "ignored" }, "PATCH").then(reload)}>not a repayment</button>
        </footer>
      </article>
    );
  }

  function OwedPanel({ active }) {
    const [d, setD] = useState(null);
    const [err, setErr] = useState({ text: "", ok: false, hidden: true });
    const [seq, setSeq] = useState(0);             // every load redraws the lists
    const [addOpen, setAddOpen] = useState(false);
    const [hOpen, setHOpen] = useState(false);
    const [form, setForm] = useState(BLANK_OWED);
    const [scanning, setScanning] = useState(false);
    const [incOpen, setIncOpen] = useState(false);
    const O = useRef({ loaded: false, touched: false, data: null, loadSeq: 0 }).current;
    const personRef = useRef(null);

    const owedErr = (msg, ok) => setErr({ text: msg || "", ok: !!ok, hidden: !msg });

    function loadOwed() {
      const mine = ++O.loadSeq;
      return fetch("/finances/api/owed").then(r => r.json()).then(data => {
        if (mine !== O.loadSeq) return;   // a newer read already answered
        setErr(prev => Object.assign({}, prev, { hidden: true }));
        O.data = data;
        setD(data);
        setSeq(s => s + 1);
        // Open on its own only while the queue is short enough to act on in one look.
        const inc = data.incoming || [];
        if (!O.touched) setIncOpen(inc.length > 0 && inc.length <= 3);
      }).catch(e => {
        console.error("[owed] fetch failed", e);
        setErr(prev => ({ text: "could not load what you're owed \u2014 reopen the tab to retry.", ok: prev.ok, hidden: false }));
      });
    }

    useEffect(() => {
      if (!active || O.loaded) return;
      O.loaded = true;
      loadOwed();
    }, [active]);

    function owedPatch(id, patch) {
      return fetch(`/finances/api/owed/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      }).then(() => loadOwed()).catch(e => console.error("[owed] update failed", e));
    }

    // Neither Venmo nor Zelle can be sent a request by an API, so "ask" builds a
    // prefilled charge link and he taps send. The note it writes carries a tag
    // (#o41) that comes back verbatim in the payment notification, which is what
    // lets the money that arrives settle the right line without anyone matching a
    // name and an amount by eye.
    function owedAsk(ids, person) {
      return postJSON("/finances/api/owed/request", { ids }).then(d1 => {
        if (d1.error) { owedErr(d1.error); return; }
        let next = Promise.resolve(d1);
        if (!d1.handle) {
          const h = window.prompt(`Venmo handle for ${person}?\n\nLeave blank to open Venmo and pick them there.`, "");
          if (h?.trim()) {
            next = postJSON("/finances/api/owed/handle", { person, venmo: h.trim() })
              .then(() => postJSON("/finances/api/owed/request", { ids, mark: false }));
          }
        }
        return next.then(dd => {
          window.open(dd.venmo_url, "_blank", "noopener");
          return loadOwed();
        });
      }).catch(e => console.error("[owed] ask failed", e));
    }

    // Zelle has no link format at all, a request only exists inside the Chase app ,
    // so the most this can do is hand him the exact memo to paste, tag included, so
    // the return trip still matches automatically.
    function owedZelle(ids, person) {
      return postJSON("/finances/api/owed/request", { ids, mark: false }).then(d1 => {
        if (d1.error) { owedErr(d1.error); return; }
        const text = `${d1.amount.toFixed(2)} \u2014 ${d1.note}`;
        let wrote;
        try { wrote = navigator.clipboard.writeText(text); } catch (e) { wrote = Promise.reject(e); }
        return wrote.then(() => { owedErr(`copied for Zelle: ${text}`, true); }, () => {
          // Not a secure context (Hub reached over its Tailscale IP rather than
          // localhost). A prompt is still copyable by hand.
          window.prompt(`Zelle request for ${person} \u2014 copy this:`, text);
        });
      }).catch(e => console.error("[owed] zelle failed", e));
    }

    const askPerson = (name, zelle) => {
      const ids = (O.data.people.find(p => p.person === name)?.lines || [])
        .filter(l => l.dir !== -1).map(l => l.id);
      if (!ids.length) return;
      (zelle ? owedZelle : owedAsk)(ids, name);
    };

    function del(ev, id) {
      const line = ev.currentTarget.closest(".owed-line, tr");
      const what = line ? line.querySelector(".owed-what, td:nth-child(2)").textContent.trim() : "this line";
      if (!window.confirm(`Delete "${what}"? Marking it paid keeps the record; deleting does not.`)) return;
      fetch(`/finances/api/owed/${id}`, { method: "DELETE" }).then(loadOwed).catch(e => console.error("[owed] delete failed", e));
    }

    function act(_ev, id, a) {
      if (a === "request") {
        const line = O.data.people.flatMap(p => p.lines).find(l => String(l.id) === String(id));
        owedAsk([Number(id)], line ? line.person : "");
        return;
      }
      owedPatch(id, { status: a });
    }

    function OwedLine(r) {
      const acts = OWED_ACTS.filter(a => a.when(r));
      // paid_out is only worth printing when the debt is a share of something bigger ,
      // "owes $100.00" alone loses that he laid out $200.00 for it.
      const sharePart = (r.paid_out != null && Math.abs(r.paid_out - r.amount) > 0.005);
      const part = r.paid_in > 0.005;
      const neg = r.dir === -1;  // he owes them: a Venmo request sent to him
      return (
        <li className={`owed-line${r.status === "requested" ? " is-asked" : ""}${neg ? " is-neg" : ""}`} data-id={r.id} key={`${r.id}:${seq}`}>
          <span className="owed-when">{owedDate(r.incurred) || "\u2014"}</span>
          <span className="owed-what">{r.what}
            {sharePart ? <React.Fragment>{" "}<span className="owed-share">{`of ${moneyC(r.paid_out)}`}</span></React.Fragment> : null}
            {part ? <React.Fragment>{" "}<span className="owed-share">{`· ${moneyC(r.paid_in)} of ${moneyC(r.amount)} paid`}</span></React.Fragment> : null}
            {r.grp ? <React.Fragment>{" "}<span className="cat-tag">{r.grp}</span></React.Fragment> : null}
            {r.status === "requested" ? <React.Fragment>{" "}<span className="cat-tag">asked</span></React.Fragment> : null}
            {r.note ? <OwedNote>{r.note}</OwedNote> : null}</span>
          <span className="owed-amt">{moneyC(neg ? -r.due : r.due)}</span>
          <span className="owed-acts">{acts.map(a => (
            <button type="button" data-act={a.act} data-id={r.id} key={a.act} onClick={ev => act(ev, r.id, a.act)}>{a.label}</button>))}
            <button type="button" className="owed-del" data-act="delete" data-id={r.id} aria-label="delete"
                    onClick={ev => del(ev, r.id)}>&times;</button>
          </span>
        </li>
      );
    }

    function sendHandles(rows) {
      // one POST per changed row, in order, then the list reloads and the verdict lands after
      let chain = Promise.resolve();
      rows.forEach(r => { chain = chain.then(() => postJSON("/finances/api/owed/handle", r)); });
      chain.then(() => loadOwed()).then(() => {
        owedErr(rows.length ? `${plural(rows.length, "handle")} saved.` : "nothing changed.", true);
        setHOpen(false);
      }).catch(e => console.error("[owed] handles failed", e));
    }

    function submitDebt(ev) {
      ev.preventDefault();
      // every field in form order, as typed: blank optional inputs go out as "" strings
      const body = { person: form.person, what: form.what, amount: form.amount, incurred: form.incurred,
                     paid_out: form.paid_out, grp: form.grp, note: form.note };
      fetch("/finances/api/owed", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }).then(res => {
        if (!res.ok) {
          return res.json().catch(() => ({})).then(b => {
            setErr(prev => ({ text: b.error || "could not save that.", ok: prev.ok, hidden: false }));
          });
        }
        setErr(prev => Object.assign({}, prev, { hidden: true }));
        setForm(BLANK_OWED);
        setAddOpen(false);
        return loadOwed();
      }).catch(e => console.error("[owed] save failed", e));
    }

    function scan() {
      // Reading the mailbox is a live Gmail round-trip, so the button has to say it
      // is working; without that it reads as a dead click for several seconds.
      setScanning(true);
      postJSON("/finances/api/owed/payments/scan", { days: 60 }).then(r => {
        setScanning(false);
        // loadOwed clears the message strip, so it runs first and the verdict lands after.
        return loadOwed().then(() => {
          if (r.error) owedErr(`could not read email: ${r.error}`);
          else owedErr(r.new
            ? `${plural(r.new, "new payment")} found${r.auto_applied ? `, ${r.auto_applied} matched automatically` : ""}.`
            : "nothing new since the last check.", true);
        });
      }).catch(e => console.error("[owed] scan failed", e));
    }

    const t = d ? d.totals : null;
    const fig = t ? {
      outstanding: [moneyC(t.outstanding),
        `${plural(t.people, "person", "people")} · ${plural(t.lines, "line")}`,
        t.unrequested ? `${moneyC(t.unrequested)} never asked for` : ""],
      requested: [moneyC(t.requested), "asked for, not yet paid", ""],
      recovered: [moneyC(t.recovered), "settled, all time", ""],
      you_owe: [moneyC(t.you_owe),
        `${plural(t.you_owe_people, "person", "people")} · ${plural(t.you_owe_lines, "line")}`,
        `net ${moneyC(t.net)}`],
    } : null;
    const inc = d ? (d.incoming || []) : [];
    const pays = d ? (d.payments || []) : [];
    const peopleNames = d ? [...new Set([...d.people, ...d.settled.map(r => ({ person: r.person }))].map(p => p.person))] : [];

    return (
      <div className="owed-main fin-panel" role="tabpanel" id="panel-owed" aria-labelledby="tab-owed" tabIndex={0} hidden={!active}>

        <div className={`hub-error${err.ok ? " is-ok" : ""}`} id="owed-error" aria-live="polite" hidden={err.hidden}>{err.text}</div>

        {/* ─── TOTALS: outstanding split by whether he has actually asked ─── */}
        <section className="totals" id="owed-totals">
          {[["outstanding", "outstanding"], ["requested", "asked for"], ["recovered", "paid back"], ["you_owe", "you owe"]].map(([scope, title]) => (
            <div className="total-card" data-scope={scope} key={scope}>
              <h3>{title}</h3>
              <div className="figs">{fig ? <React.Fragment>
                <span className="net">{fig[scope][0]}</span>
                {fig[scope][1] ? <span className="sub">{fig[scope][1]}</span> : null}
                {fig[scope][2] ? <span className="sub">{fig[scope][2]}</span> : null}
              </React.Fragment> : null}</div>
            </div>))}
        </section>

        {/* ─── MONEY IN: arrivals read out of Venmo and Zelle notification email.
            Nothing here settles itself unless the payment note carried the tag
            the request button wrote and the amount matched to the cent; the rest
            waits for a click, because a payment applied to the wrong debt is
            indistinguishable from a debt that was paid. ─── */}
        <section className="periods" id="owed-incoming-sec">
          <div className="periods-head">
            <h3>money in</h3>
            <button id="owed-scan" type="button" disabled={scanning} onClick={scan}>{scanning ? "reading…" : "check email"}</button>
          </div>
          {/* Collapsed once the queue is more than a glance: this sits above the
              debt list, and a back-scan of a few months of already-settled
              history would otherwise push what he actually owes off the screen. */}
          <details id="owed-incoming-det" open={incOpen}
                   onToggle={e => { O.touched = true; setIncOpen(e.currentTarget.open); }}>
            <summary>
              <span className="pw-caret"></span>
              <span id="owed-incoming-note">{d ? (inc.length
                ? `${plural(inc.length, "payment")} waiting · ${moneyC(inc.reduce((s, p) => s + p.amount, 0))}`
                : "nothing waiting") : ""}</span>
            </summary>
            <div className="owed-incoming" id="owed-incoming">{d ? (inc.length
              ? inc.map(p => <PayCard p={p} owedErr={owedErr} reload={loadOwed} key={`${p.id}:${seq}`} />)
              : <p className="by-source-empty">nothing waiting &mdash; every payment that has landed is matched.</p>) : null}</div>
          </details>
        </section>

        {/* ─── WHO OWES WHAT: one card per person, biggest balance first ─── */}
        <section className="periods">
          <div className="periods-head">
            <h3>who owes what</h3>
            <button id="owed-handles-toggle" type="button" aria-expanded={hOpen} aria-controls="owed-handles-wrap"
                    onClick={() => {
                      const next = !hOpen;
                      setHOpen(next);
                      if (next) setTimeout(() => { const i = document.querySelector("#owed-handles-wrap input"); if (i) i.focus(); }, 0);
                    }}>venmo handles</button>
            <button id="owed-add-toggle" type="button" aria-expanded={addOpen} aria-controls="owed-add-wrap"
                    onClick={() => {
                      const next = !addOpen;
                      setAddOpen(next);
                      if (next) setTimeout(() => personRef.current?.focus(), 0);
                    }}>+ add a debt</button>
          </div>

          {/* Every debtor's Venmo handle in one pass. Nothing in Gmail carries
              another person's handle, the payment emails name only the account
              holder, and the transaction pages refuse anything that is not a
              logged-in browser, so these are typed once and kept. Each row is
              prefilled with Venmo's usual default (Firstname-Lastname), which is
              a guess and says so; the real check is Venmo showing him the profile
              before he taps send. */}
          <div className={`manual-wrap${hOpen ? " open" : ""}`} id="owed-handles-wrap">
           <div className="manual-panel">
            <HandlesForm d={d} send={sendHandles} key={seq} />
           </div>
          </div>

          <div className={`manual-wrap${addOpen ? " open" : ""}`} id="owed-add-wrap">
           <div className="manual-panel">
            <form id="owed-form" onSubmit={submitDebt}>
              <label htmlFor="o-person" className="sr-only">who owes</label>
              <input id="o-person" name="person" placeholder="who owes" required list="owed-people-list" ref={personRef}
                     value={form.person} onChange={e => { const v = e.target.value; setForm(p => Object.assign({}, p, { person: v })); }} />
              <datalist id="owed-people-list">{peopleNames.map(n => <option value={n} key={n} />)}</datalist>

              <label htmlFor="o-what" className="sr-only">what for</label>
              <input id="o-what" name="what" placeholder="what for" required
                     value={form.what} onChange={e => { const v = e.target.value; setForm(p => Object.assign({}, p, { what: v })); }} />

              <label htmlFor="o-amount" className="sr-only">amount (negative = you owe)</label>
              <input id="o-amount" name="amount" type="number" step="0.01" placeholder="amount (− = you owe)" required
                     value={form.amount} onChange={e => { const v = e.target.value; setForm(p => Object.assign({}, p, { amount: v })); }} />

              <label htmlFor="o-incurred" className="sr-only">date</label>
              <input id="o-incurred" name="incurred" type="date"
                     value={form.incurred} onChange={e => { const v = e.target.value; setForm(p => Object.assign({}, p, { incurred: v })); }} />

              <label htmlFor="o-paid-out" className="sr-only">what you paid (optional)</label>
              <input id="o-paid-out" name="paid_out" type="number" step="0.01" min="0" placeholder="what you paid (optional)"
                     value={form.paid_out} onChange={e => { const v = e.target.value; setForm(p => Object.assign({}, p, { paid_out: v })); }} />

              <label htmlFor="o-grp" className="sr-only">group (optional)</label>
              <input id="o-grp" name="grp" placeholder="group, e.g. Zedd In The Park (optional)"
                     value={form.grp} onChange={e => { const v = e.target.value; setForm(p => Object.assign({}, p, { grp: v })); }} />

              <label htmlFor="o-note" className="sr-only">note (optional)</label>
              <input id="o-note" name="note" placeholder="note (optional)"
                     value={form.note} onChange={e => { const v = e.target.value; setForm(p => Object.assign({}, p, { note: v })); }} />

              <div className="form-actions">
                <button type="submit">save</button>
              </div>
            </form>
           </div>
          </div>

          <div className="owed-people" id="owed-people">{d ? (d.people.length
            ? d.people.map(p => (
              <article className="owed-person" key={`${p.person}:${seq}`}>
                <header className="owed-person-head">
                  <h4>{p.person}</h4>
                  {d.handles[p.person] ? <span className="owed-handle">@{d.handles[p.person]}</span> : null}
                  <span className={`owed-person-total${p.total < 0 ? " is-neg" : ""}`}>{moneyC(p.total)}</span>
                  {p.lines.some(l => l.dir !== -1)
                    ? <span className="owed-person-acts">
                        <button type="button" data-ask-person={p.person} onClick={() => askPerson(p.person, false)}>ask for all</button>
                        <button type="button" data-zelle-person={p.person} onClick={() => askPerson(p.person, true)}>zelle memo</button>
                      </span>
                    : null}
                </header>
                <ul className="owed-lines">{p.lines.map(OwedLine)}</ul>
              </article>))
            : <p className="by-source-empty">nothing open either way.</p>) : null}</div>
        </section>

        {/* ─── GROUP FRONTS: one expense, several debtors; the total nobody owes alone ─── */}
        <section className="by-source" id="owed-groups" hidden={!d?.groups.length}>
          <h3>group fronts</h3>
          <ul>{d ? d.groups.map(g => (
            <li key={g.grp}><span className="src-name">{g.grp}</span>
              <span className="src-figs">{`${moneyC(g.total)} · ${plural(g.people, "share")}`}</span></li>)) : null}</ul>
        </section>

        {/* ─── UNASSIGNED: real money out with no confirmed debtor. Kept, not
            deleted: dropping these is how they were forgotten the first time. ─── */}
        <section className="periods" id="owed-unassigned-sec" hidden={!d?.unassigned.length}>
          <details>
            <summary>
              <span className="pw-caret"></span>
              <span>unassigned</span>
              <span className="pay-note">money out with no confirmed debtor</span>
            </summary>
            <table id="owed-unassigned-table">
              <thead><tr><th>date</th><th>what</th><th>who</th><th>amount</th><th></th></tr></thead>
              <tbody>{d ? d.unassigned.map(r => (
                <tr key={`${r.id}:${seq}`}><td>{owedDate(r.incurred) || "\u2014"}</td>
                  <td>{r.what}{r.note ? <OwedNote>{r.note}</OwedNote> : null}</td>
                  <td>{r.person === "unassigned" ? "\u2014" : r.person}</td>
                  <td>{moneyC(r.amount)}</td>
                  <td className="owed-acts"><button type="button" data-act="open" data-id={r.id} onClick={ev => act(ev, r.id, "open")}>claim</button>
                    <button type="button" className="owed-del" data-act="delete" data-id={r.id} aria-label="delete"
                            onClick={ev => del(ev, r.id)}>&times;</button></td></tr>)) : null}</tbody>
            </table>
          </details>
        </section>

        {/* ─── SETTLED: the paid-back log ─── */}
        <section className="periods">
          <details id="owed-settled">
            <summary>
              <span className="pw-caret"></span>
              <span>settled</span>
              <span className="pay-note" id="owed-settled-note">{d ? (d.settled.length ? `${plural(d.settled.length, "line")} · ${moneyC(t.recovered)}` : "nothing yet") : ""}</span>
            </summary>
            <table id="owed-settled-table">
              <thead><tr><th>paid</th><th>who</th><th>what</th><th>amount</th><th></th></tr></thead>
              <tbody>{d ? d.settled.map(r => (
                <tr key={`${r.id}:${seq}`}><td>{owedDate(r.settled) || "date unknown"}</td>
                  <td>{r.person}</td>
                  <td>{r.what}{r.method ? <React.Fragment>{" "}<span className="cat-tag">{r.method}</span></React.Fragment> : null}</td>
                  <td>{moneyC(r.amount)}</td>
                  <td className="owed-acts"><button type="button" data-act="open" data-id={r.id} onClick={ev => act(ev, r.id, "open")}>reopen</button></td></tr>)) : null}</tbody>
            </table>
          </details>
        </section>

        {/* ─── PAYMENTS RECEIVED: every transfer that actually landed, whether or
            not it has been matched to a debt. The settled table above is debts
            closed; this one is money in the door. ─── */}
        <section className="periods">
          <details id="owed-payments">
            <summary>
              <span className="pw-caret"></span>
              <span>payments received</span>
              <span className="pay-note" id="owed-payments-note">{d ? (pays.length
                ? `${plural(pays.length, "payment")} · ${moneyC(pays.reduce((s, p) => s + p.amount, 0))}`
                : "nothing recorded yet") : ""}</span>
            </summary>
            <table id="owed-payments-table">
              <thead><tr><th>date</th><th>who</th><th>note</th><th>amount</th><th>how</th><th></th></tr></thead>
              <tbody>{pays.map(p => (
                <tr key={`${p.id}:${seq}`}><td>{owedDate(p.received)}</td>
                  <td>{p.person}</td>
                  <td>{p.note || ""}{p.status === "ignored" ? <React.Fragment>{" "}<span className="cat-tag">not a repayment</span></React.Fragment> : null}
                    {p.lines?.length ? <OwedNote>{p.lines.map(l => `${l.what} (${moneyC(l.amount)})`).join(", ")}</OwedNote> : null}</td>
                  <td>{moneyC(p.amount)}</td>
                  <td><span className="cat-tag">{p.method}</span></td>
                  <td className="owed-acts">
                    {p.status === "applied" ? <button type="button" data-unapply={p.id}
                      onClick={() => postJSON(`/finances/api/owed/payments/${p.id}/apply`, {}, "DELETE").then(loadOwed)}>undo</button> : null}
                  </td></tr>))}</tbody>
            </table>
          </details>
        </section>

      </div>
    );
  }
  U.OwedPanel = OwedPanel;
})();
