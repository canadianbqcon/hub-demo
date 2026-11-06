/* hub · account page body (2026-10-13): React port of account.js lines 431-868 plus the boot.
   Same DOM and classes as the plain page. The gate strip, the form editor, the Hub-only "who"
   picker, the trips list and the mount. The card, nav, ladder, details form and preference
   blocks come from account-core.jsx. Template globals: STATE, MODE, ME.

   Write-safety: the form editor holds its answers in controlled state hydrated from the form the
   server sent; save stays disabled until a form has loaded; a form response for a form that is
   no longer the one asked for is dropped. The request bodies are the plain page's, byte for byte
   (POST /trips/api/prefs/submit {kind, ref, answers}); the details form lives in the core file. */
(() => {
const { useState, useEffect, useLayoutEffect, useRef } = React;
const { CC, QS, ME_SLUG, SECTIONS, DASH, measureTopbar, prefersStill, goTo, spyId,
  Card, Nav, You, Details, Prefs } = window.AccountUI;

// The server renders one link per trip the intake form may open inside #sec-trips, after the list
// host. They are server markup, so they are kept as nodes and put back after React draws the section.
const secTrips = document.getElementById("sec-trips");
const INTAKE = secTrips ? Array.prototype.slice.call(secTrips.children, 3) : [];

/* A render error shows the same words the load fallback does. */
class Boundary extends React.Component {
  constructor(p) { super(p); this.state = { failed: false }; }
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(e) { console.error("account", e); }
  render() { return this.state.failed ? <div className="hub-error">page failed to load</div> : this.props.children; }
}

// ── the gate strip ────────────────────────────────────────────────────────────
//
// Two different debts, and the strip can say either or both. A form nobody filled is the old one:
// the board is shut until it is in. A form that IS in but holds answers the questions no longer
// offer is the new one, and the louder line because it is the invisible one. The minute count is
// stated because a nag that does not say how long reads as a project and gets deferred.
function Gate({ src }) {
  const host = document.getElementById("acctGate");
  const missing = (src.forms || []).filter((f) => !f.done);
  const owedN = src.owed_count || 0;
  const hide = (!missing.length && !owedN) || MODE === "hub";
  useLayoutEffect(() => { host.hidden = hide; });
  if (hide) return null;
  const mins = src.fix_minutes || 2;
  return ReactDOM.createPortal(
    <>
      {owedN ? <>
        <span><b>{`${owedN} answer${owedN === 1 ? " is" : "s are"} out of date`}</b>
          {` ${DASH} about ${mins} minute${mins === 1 ? "" : "s"} to bring back up to date`}</span>
        <span className="acct-gate-sub">{"Until you answer them you are left out of the"
          + " crew's picks for those " + DASH + " the group read skips anyone it cannot place."}</span>
      </> : null}
      {missing.length ? <>
        <span><b>{`${missing.length} form${missing.length === 1 ? "" : "s"}`}</b>{" before the trip opens"}</span>
        <span className="acct-gate-sub">{missing.map((f) => f.label).join(" and ")
          + ". Nothing on either is required " + DASH + " a half-answered form counts."}</span>
      </> : null}
    </>, host);
}

// ── who ───────────────────────────────────────────────────────────────────────
//
// Whose account this is, and on Hub the picker that changes it. Never on the mirror, and never in a
// preview: A.locked is the server's own answer to "was this session pinned", so a guest gets no
// picker even if MODE were wrong, and the roster is withheld from that process anyway. A button
// over the card, not a select: the native select opened the OS menu, unstyled in every theme. The
// menu borrows the theme picker's classes, the one styled dropdown the Hub has.
function Who({ A, people }) {
  const [open, setOpen] = useState(false);
  const host = useRef(null), btn = useRef(null);
  useEffect(() => {
    const away = (e) => { if (host.current && !host.current.contains(e.target)) setOpen(false); };
    document.addEventListener("click", away);
    return () => { document.removeEventListener("click", away); };
  }, []);
  let body = null;
  if (A && people) {
    // Sam first, then the crew as the roster orders them (newest trip first).
    const sorted = people.slice().sort((a, b) => (b.contact_slug === ME_SLUG) - (a.contact_slug === ME_SLUG));
    const label = (p) => p.contact_slug === ME_SLUG ? "your account" : p.name || p.contact_slug;
    const cur = sorted.filter((p) => p.contact_slug === A.ref)[0];
    body = (
      <>
        <button type="button" className="hub-btn theme-picker-btn acct-who-btn" aria-haspopup="listbox"
          aria-expanded={open ? "true" : "false"} ref={btn} onClick={() => { setOpen(!open); }}>
          <span className="acct-who-k">viewing</span><span className="theme-picker-optname">{cur ? label(cur) : "your account"}</span>
          <span className="theme-picker-caret" aria-hidden="true">{"▾"}</span></button>
        <HubCollapse open={open} float>
        <div className="theme-picker-menu" role="listbox" aria-label="whose account">
          {sorted.map((p) => {
            const on = p.contact_slug === A.ref;
            return (
              <button key={p.contact_slug} type="button" className={`theme-picker-opt${on ? " is-active" : ""}`}
                role="option" aria-selected={on ? "true" : "false"} data-ref={p.contact_slug}
                // location.href, not location.search: assigning "" leaves a bare "?" behind, and the
                // hash from the last section read would ride along to a page that is now somebody else's
                onClick={() => {
                  location.href = location.pathname + (p.contact_slug === ME_SLUG ? "" : `?ref=${encodeURIComponent(p.contact_slug)}`);
                }}>
                <span className="theme-picker-optname">{label(p)}</span>
                {on ? <span className="theme-picker-check">{"✓"}</span> : null}</button>
            );
          })}
        </div>
        </HubCollapse>
      </>
    );
  }
  return (
    <div className="acct-who theme-picker" id="acctWho" ref={host} hidden={!body}
      onKeyDown={(e) => { if (e.key === "Escape") { setOpen(false); if (btn.current) btn.current.focus(); } }}>{body}</div>
  );
}

// ── the form editor ───────────────────────────────────────────────────────────
//
// Rendered from the schema the server sends, never from a copy of the questions kept here. The
// server validates the same schema on the way back in, so what this draws and what it will accept
// cannot drift apart. Nothing here names who is answering: the submit route reads that off the
// session, so there is no field to tamper with and none to send.

// The axis in words, above the options, so the row is not just a list of phrases.
function ScaleAxis({ qkey }) {
  const sc = CC.scaleOf(qkey);
  if (!sc) return null;
  return <span className="fq-axis"><span>{sc.low}</span><span>{sc.high}</span></span>;
}

// `key` is the question this row answers, so the options can show that they ARE a scale while it
// is being answered. An option that is not a point on the scale gets no tint: a real answer that
// is not a position.
function OptRow({ name, opts, chosen, qkey, onPick }) {
  return (
    <div className="fq-opts">{opts.map((o, i) => {
      const id = `${name}-${i}`;
      const pos = CC.scalePos(qkey, o.value);
      return (
        <React.Fragment key={id}>
          <input type="radio" name={name} id={id} value={o.value} checked={o.value === chosen}
            onChange={() => { onPick(o.value); }} />
          <label htmlFor={id} className={pos ? "fq-scaled" : undefined}
            style={pos ? { "--c": CC.rampColor(pos.t, pos.valence) } : undefined}>{o.label}</label>
        </React.Fragment>
      );
    })}</div>
  );
}

// `owe` is this question's entry from the server's owed list, or undefined. On a grid only the
// ROWS the form can no longer place are marked. The badge is the marker, not a lock.
function Question({ q, val, owe, onVal }) {
  const stale = owe ? (owe.row_keys || []) : [];
  const mark = owe
    ? <span className="owe-b owe-b-q">{owe.rows > 1 ? `${owe.rows} to re-answer` : "answer this again"}</span>
    : null;
  let inner;
  if (q.type === "grid") {
    inner = (
      <>
        <span className="fq-t">{q.title}{mark}</span>
        {q.rows.map((r) => {
          const rowOwed = stale.indexOf(r.key) >= 0;
          return (
            <div key={r.key} className={`fgrid-row${rowOwed ? " owe" : ""}`}>
              <span className="fgrid-l">{r.label}{rowOwed ? <span className="owe-b owe-b-q">rate this one</span> : null}</span>
              <OptRow name={`g:${q.key}:${r.key}`} opts={q.options} chosen={val[r.key] || ""} qkey={q.key}
                onPick={(v) => { const n = Object.assign({}, val); n[r.key] = v; onVal(n); }} />
            </div>
          );
        })}
      </>
    );
  } else if (q.type === "radio") {
    inner = (
      <>
        <span className="fq-t">{q.title}{mark}</span>
        <ScaleAxis qkey={q.key} />
        <OptRow name={`r:${q.key}`} opts={q.options} chosen={val} qkey={q.key} onPick={onVal} />
      </>
    );
  } else if (q.type === "checkbox") {
    inner = (
      <>
        <span className="fq-t">{q.title}</span>
        <div className="fq-opts">{q.options.map((o, i) => {
          const id = `c:${q.key}-${i}`;
          return (
            <React.Fragment key={id}>
              <input type="checkbox" name={`c:${q.key}`} id={id} value={o.value} checked={val.indexOf(o.value) >= 0}
                onChange={(ev) => {
                  onVal(ev.target.checked ? val.concat([o.value]) : val.filter((x) => x !== o.value));
                }} />
              <label htmlFor={id}>{o.label}</label>
            </React.Fragment>
          );
        })}</div>
      </>
    );
  } else {
    inner = (
      <>
        <label className="fq-t" htmlFor={`t:${q.key}`}>{q.title}</label>
        {q.type === "paragraph"
          ? <textarea id={`t:${q.key}`} name={`t:${q.key}`} value={val} onChange={(ev) => { onVal(ev.target.value); }} />
          : <input type="text" id={`t:${q.key}`} name={`t:${q.key}`} value={val} onChange={(ev) => { onVal(ev.target.value); }} />}
      </>
    );
  }
  return <div className={`fq${owe ? " fq-owe" : ""}`} data-owe={owe ? q.key : undefined}>{inner}</div>;
}

// Seed the controlled answers from what the server says is stored, shaped per question type.
function hydrate(form) {
  const out = {};
  form.schema.sections.forEach((sec) => {
    sec.questions.forEach((q) => {
      const got = form.answers?.[q.key];
      if (q.type === "grid") out[q.key] = (got && typeof got === "object") ? Object.assign({}, got) : {};
      else if (q.type === "checkbox") out[q.key] = Array.isArray(got) ? got.slice() : [];
      else out[q.key] = typeof got === "string" ? got : "";
    });
  });
  return out;
}

// What goes in the request: the same answers the plain page read off the checked inputs. A stored
// value that is no longer one of the options has no checked input there, so it is left out here too.
function collect(form, vals) {
  const out = {};
  const has = (opts, v) => opts.some((o) => o.value === v);
  form.schema.sections.forEach((sec) => {
    sec.questions.forEach((q) => {
      const v = vals[q.key];
      if (q.type === "grid") {
        const grid = {};
        q.rows.forEach((r) => { if (v[r.key] && has(q.options, v[r.key])) grid[r.key] = v[r.key]; });
        if (Object.keys(grid).length) out[q.key] = grid;
      } else if (q.type === "radio") {
        if (v && has(q.options, v)) out[q.key] = v;
      } else if (q.type === "checkbox") {
        const on = q.options.filter((o) => v.indexOf(o.value) >= 0).map((o) => o.value);
        if (on.length) out[q.key] = on;
      } else if (v.trim()) {
        out[q.key] = v.trim();
      }
    });
  });
  return out;
}

function FormEditor({ A, form, vals, note, busy, onVal, onBack, onSave }) {
  let who = null, body = null;
  if (form) {
    const name = (A.me?.name) || form.ref;
    // Three readings of the same pinned/unpinned fact. A guest is told the lock is on their side;
    // Sam in a preview is told the lock is the preview's.
    who = (form.locked && MODE === "hub")
      ? <>view as <b>{form.ref}</b>{` ${DASH} saves to their preferences · `}<a href="/trips/preview/off">exit preview</a></>
      : form.locked
        ? <>answering as <b>{name}</b>{` ${DASH} this saves to your own preferences only`}</>
        : <>editing <b>{name}</b></>;
    const owe = {};
    (form.owed || []).forEach((o) => { owe[o.key] = o; });
    const owedN = (form.owed || []).length;
    // Said at the top of the form and not only in the section copy, because the form is reached from
    // a trip and reads like it is about that trip. It is not: one set of answers per person.
    body = (
      <>
        <div className="fstanding"><b>These are your standing preferences, not this trip's.</b>
          {" One set per person, and every trip you are on reads the same answers " + DASH + " so answer for how you travel and eat in general,"
            + " not for wherever you happen to be going next. You can change any of it"
            + " whenever it stops being true."}</div>
        {owedN ? <div className="fowe"><b>{`${owedN} question${owedN === 1 ? " is" : "s are"} marked below.`}</b>
          {" Your old answer" + (owedN === 1 ? " is" : "s are") + " not on this form any more, so the group"
            + " read cannot place " + (owedN === 1 ? "it" : "them") + " and skips you"
            + " on " + (owedN === 1 ? "that one" : "those") + ". Everything else is"
            + " already saved " + DASH + " you only have to touch the marked ones."}</div> : null}
        {form.schema.sections.map((sec) => (
          <div className="fsec" key={sec.title}><h3 className="fsec-h">{sec.title}</h3>
            {sec.questions.map((q) => (
              <Question key={q.key} q={q} val={vals[q.key]} owe={owe[q.key]}
                onVal={(v) => { onVal(q.key, v); }} />
            ))}
          </div>
        ))}
      </>
    );
  }
  return (
    <section className="asec aform" id="secForm" hidden={!form}>
      <div className="aform-bar">
        <button type="button" className="abtn" id="formBack" onClick={onBack}>{"← back"}</button>
        <span className="aform-who" id="formWho">{who}</span>
      </div>
      <div id="formBody">{body}</div>
      <div className="aform-save">
        <button type="button" className="abtn abtn-accent" id="formSave" disabled={busy || !form} onClick={onSave}>save</button>
        <span className={`anote${note.tone ? ` anote-${note.tone}` : ""}`} id="formNote">{note.text}</span>
      </div>
    </section>
  );
}

// ── the body ──────────────────────────────────────────────────────────────────

// ?s=<section> lands on a section. A hash does the same thing and survives a reload.
function landing() {
  const want = new URLSearchParams(location.search).get("s") || (location.hash || "").replace("#sec-", "");
  return SECTIONS.some((s) => s.id === want) ? want : "";
}

function Body() {
  // A: everything /trips/api/prefs/account answered, null until it lands. gen counts the full
  // repaints the plain page did (first paint, every form close) so the details form resets on each.
  const [A, setA] = useState(null);
  const [loadErr, setLoadErr] = useState(false);
  const [gen, setGen] = useState(0);
  // ME is the signup row the server rendered (mirror only); it moves to what the server stored on save
  const [me, setMe] = useState(() => ME);
  const [on, setOn] = useState(SECTIONS[0].id);
  const [people, setPeople] = useState(null);
  // the form editor: form is the loaded form or null; vals its controlled answers
  const [form, setForm] = useState(null);
  const [vals, setVals] = useState({});
  const [note, setNote] = useState({ text: "", tone: "" });
  const [busy, setBusy] = useState(false);
  const [opened, setOpened] = useState(0);
  const openTok = useRef(0);
  const goAfter = useRef("");
  const tripsRef = useRef(null);

  const loadA = () => fetch(`/trips/api/prefs/account${QS}`).then((r) => {
    if (!r.ok) throw new Error("account load failed");
    return r.json();
  }).then((a) => {
    // Before any paint: the card and the read-back both draw bars off these.
    CC.setScales(a.scales);
    CC.setLabels(a.labels);
    setA(a);
  });

  useEffect(() => {
    document.querySelector(".acct-wrap").setAttribute("data-react-mounted", "account");
    loadA().then(() => {
      setGen((g) => g + 1);
      const want = landing();
      // After paint, and after the sticky offset has been measured, or the jump lands the section
      // under the topbar it was measured to clear.
      if (want) requestAnimationFrame(() => { goTo(want); });
    }).catch(() => { setLoadErr(true); });
  }, []);
  useLayoutEffect(() => { INTAKE.forEach((n) => { tripsRef.current.appendChild(n); }); }, []);
  useLayoutEffect(() => { measureTopbar(); }, [gen]);
  useEffect(() => {
    if (!A) return;
    setOn(spyId());
    if (goAfter.current) { goTo(goAfter.current); goAfter.current = ""; }
  }, [gen]);
  useEffect(() => {
    if (!A) return undefined;
    const sc = () => { setOn(spyId()); };
    const rs = () => { measureTopbar(); setOn(spyId()); };
    window.addEventListener("scroll", sc, { passive: true });
    window.addEventListener("resize", rs, { passive: true });
    return () => { window.removeEventListener("scroll", sc); window.removeEventListener("resize", rs); };
  }, [A !== null]);

  // The picker, on every full repaint: Hub only, and only while the session is not pinned.
  useEffect(() => {
    if (!A || MODE !== "hub" || A.locked) return;
    fetch("/trips/api/guest-codes").then((r) => (r.ok ? r.json() : null)).then((d) => {
      const p = d?.people ? d.people : [];
      if (p.length) setPeople(p);
    }).catch(() => {});   // the page matters more than the picker
  }, [gen]);

  const setFormNote = (text, tone) => { setNote({ text: text || "", tone: tone || "" }); };

  const openForm = (kind) => {
    openTok.current += 1;
    const tok = openTok.current;
    setFormNote("loading…");
    fetch(`/trips/api/prefs/form/${encodeURIComponent(kind)}${QS}`).then((r) => {
      if (!r.ok) throw new Error("load failed");
      return r.json();
    }).then((data) => {
      if (tok !== openTok.current) return;   // a later open already owns the editor
      setFormNote("");
      setVals(hydrate(data));
      setForm(data);
      setOpened((n) => n + 1);
    }).catch(() => { if (tok === openTok.current) setFormNote("could not open that just now", "bad"); });
  };
  // walk to the top of the form, then to the first marked question after a frame, so the scroll
  // starts from a laid-out page
  useLayoutEffect(() => {
    if (!opened) return;
    window.scrollTo(0, 0);
    const first = document.querySelector("#formBody [data-owe]");
    if (first) {
      requestAnimationFrame(() => {
        first.scrollIntoView({ behavior: prefersStill() ? "auto" : "smooth", block: "center" });
      });
    }
  }, [opened]);

  const closeForm = (back) => {
    openTok.current += 1;
    setForm(null);
    goAfter.current = back || "";
    setGen((g) => g + 1);
  };
  const closeRef = useRef(closeForm);
  closeRef.current = closeForm;
  useEffect(() => {
    if (!form) return undefined;
    const esc = (ev) => { if (ev.key === "Escape") closeRef.current("prefs"); };
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("keydown", esc); };
  }, [form !== null]);

  const save = () => {
    if (!form) return;
    const answers = collect(form, vals);
    if (!Object.keys(answers).length) {
      setFormNote("answer at least one thing first", "bad");
      return;
    }
    setBusy(true);
    setFormNote("saving…");
    const before = A.complete;
    // No ref from the URL in the body: FORM.ref is what the SERVER said this session may write,
    // which for a guest or a preview is themselves no matter what the URL asked for.
    fetch("/trips/api/prefs/submit", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: form.schema.kind, ref: form.ref, answers: answers }),
    }).then((r) => {
      if (!r.ok) throw new Error("save failed");
      return r.json();
    }).then((state) => {
      // The submit answers with the cheap wall state. Everything else on this page comes off the
      // account route, so re-pull rather than paint half a truth from the half that came back.
      return loadA().then(() => {
        closeForm("prefs");
        if (state.complete && !before) {
          setFormNote("");
          location.href = "/trips/";
          return;
        }
        setBusy(false);
      });
    }).catch(() => {
      setFormNote(`could not save just now ${DASH} try again in a moment`, "bad");
      setBusy(false);
    });
  };

  const onSaved = (out) => {
    setMe(out);
    // The name is on the card, so the card is now stale.
    setA((cur) => {
      if (!cur?.me) return cur;
      const name = [out.first_name, out.last_name].filter(Boolean).join(" ") || cur.me.name;
      return Object.assign({}, cur, { me: Object.assign({}, cur.me, { name: name }) });
    });
  };

  const vis = A ? { you: true, details: !!me, prefs: true, trips: (A.trips || []).length > 0 } : {};
  const hid = (id) => !A || !!form || !vis[id];
  const ts = A ? (A.trips || []) : [];
  return (
    <>
      {/* STATE is the same cheap wall payload the server rendered this page from, so what gates the
          board is on screen before the account fetch resolves */}
      <Gate src={A || STATE} />
      <aside className="acct-aside">
        <Who A={A} people={people} />
        <div className="acct-cardhost">
          <Card A={A} />
          <p className="acct-cardnote" id="acctCardNote">{A ? "This is the card the crew sees." : ""}</p>
        </div>
        <Nav A={A} shown={vis} on={on} hidden={!!form} />
      </aside>
      <main className="acct-main" id="acctMain">
        <div className="acct-load" id="acctLoad" hidden={!!A}>{loadErr
          ? "could not load your account just now. Reload the page, or sign in again."
          : "loading your account…"}</div>

        <section className="asec" id="sec-you" hidden={hid("you")}>
          <h2 className="asec-h">you</h2>
          <You A={A} onOpenForm={openForm} />
        </section>

        <section className="asec" id="sec-details" hidden={hid("details")}>
          <h2 className="asec-h">details</h2>
          <p className="asec-sub">how Sam reaches you. None of it renders on the shared board.</p>
          <div id="detailsBody">{A && me ? <Details key={gen} me={me} onSaved={onSaved} /> : null}</div>
        </section>

        <section className="asec" id="sec-prefs" hidden={hid("prefs")}>
          <h2 className="asec-h">preferences</h2>
          <p className="asec-sub">{"What you answered, and the button to change any of it. These are your"
            + " standing preferences, not any one trip's " + DASH + " every trip you are on reads the same set."}</p>
          <div id="prefsBody"><Prefs A={A} onOpenForm={openForm} /></div>
        </section>

        <section className="asec" id="sec-trips" hidden={hid("trips")} ref={tripsRef}>
          <h2 className="asec-h">trips</h2>
          <p className="asec-sub">everything your code opens.</p>
          <div id="tripsBody">{ts.map((t) => {
            const dates = [t.start_date, t.end_date].filter(Boolean).join(" → ");
            const sub = [t.destination, dates].filter(Boolean).join(" · ");
            return (
              <a className="trip" href={`/trips/${t.id}`} key={t.id}>
                <span><span className="trip-n">{t.name || "untitled trip"}</span>
                  {sub ? <span className="trip-w">{sub}</span> : null}</span>
                <span className="trip-r">{`${t.crew} on it`}</span></a>
            );
          })}</div>
        </section>

        <FormEditor A={A} form={form} vals={vals} note={note} busy={busy}
          onVal={(k, v) => { setVals((cur) => { const n = Object.assign({}, cur); n[k] = v; return n; }); }}
          onBack={() => { closeForm("prefs"); }} onSave={save} />
      </main>
    </>
  );
}

const host = document.querySelector(".acct-wrap");
host.textContent = "";  // the template's static copy is only the load fallback
ReactDOM.createRoot(host).render(<Boundary><Body /></Boundary>);
})();
