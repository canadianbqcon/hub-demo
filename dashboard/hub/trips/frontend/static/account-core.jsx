/* hub · account page, core (2026-10-13): React port of account.js lines 1-430. The constants and
   helpers, the card, the nav, the "you" ladder, the details form and the preference blocks. Same
   DOM and classes as the plain page. crewcard.js is kept and called as is: it hands back HTML
   strings, which go in through dangerouslySetInnerHTML. Template globals: STATE, MODE, ME (read
   by account.jsx). The body, the form editor and the mount live in account.jsx.

   One page, five sections, and a card down the left that every one of them describes. Identity is
   never sent: every write posts to a route that reads the member key off the session, so there is
   no subject in any body on this page and no one else's record to reach. */
window.AccountUI = window.AccountUI || {};
(() => {
const { useState } = React;
const CC = window.CrewCard;
const AddrCombo = window.HubUI.AddrCombo;
const $ = (id) => document.getElementById(id);

// `ref` is honoured only where the session is pinned to nobody: Sam on Hub with no preview
// running. A guest's session is pinned, so the server drops it.
const REF = new URLSearchParams(location.search).get("ref") || "";
// Sam's own key, the one the server falls back to when Hub names nobody.
// Server twin: api.ME_SLUG. Same literal as trips.js and trips-cost.js.
const ME_SLUG = "sam-rivera";
const QS = REF ? `?ref=${encodeURIComponent(REF)}` : "";

const SECTIONS = [
  { id: "you", label: "you" },
  { id: "details", label: "details" },
  { id: "prefs", label: "preferences" },
  { id: "trips", label: "trips" },
];

// The three things a member fills in, and where each one is answered. `slot` is only the key the
// server reports completion under (api._card_unlocked).
const PILLARS = [
  { slot: "card_header", pillar: "your details",
    go: "details", why: "your name, so the card has something to set." },
  { slot: "card_shimmer", pillar: "the food form",
    go: "food", why: "how you eat, which is most of what a trip argues about." },
  { slot: "card_border", pillar: "the travel form",
    go: "travel", why: "your pace and your hard nos." },
];

const FIELDS = [
  { k: "first_name", l: "first name", ac: "given-name", max: 40, req: true },
  { k: "last_name", l: "last name", ac: "family-name", max: 40, req: true },
  { k: "email", l: "email", ac: "email", max: 120, req: true, type: "email" },
  { k: "phone", l: "phone", ac: "tel", max: 30, req: true, type: "tel" },
  // No `ac`: this one is a combobox and hardcodes autocomplete="off".
  { k: "address", l: "address", max: 200 },
];

const DASH = "—";

function esc(s) { return CC.esc(s); }

function when(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d) ? "" : d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

// The sticky offsets in account.css are measured, not guessed: the topbar is injected by
// theme-switch.js and its height moves with the theme's control sizing and the phone breakpoint.
function measureTopbar() {
  const bar = document.querySelector(".topbar");
  if (!bar) return;
  let h = Math.round(bar.getBoundingClientRect().height);
  const gate = $("acctGate");
  if (gate && !gate.hidden) h += Math.round(gate.getBoundingClientRect().height);
  document.documentElement.style.setProperty("--topbar-h", `${h}px`);
}

function prefersStill() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function goTo(id) {
  const el = $(`sec-${id}`);
  if (!el || el.hidden) return;
  history.replaceState(null, "", `#sec-${id}`);
  el.scrollIntoView({ behavior: prefersStill() ? "auto" : "smooth", block: "start" });
}

// Which section is being read: the topmost one whose top edge has passed the sticky chrome wins;
// nothing wins until one has, so the first entry lights on load.
function spyId() {
  const bar = parseInt(getComputedStyle(document.documentElement).getPropertyValue("--topbar-h"), 10) || 56;
  const line = bar + (window.innerHeight - bar) * 0.34;
  let on = SECTIONS[0].id;
  SECTIONS.forEach((s) => {
    const el = $(`sec-${s.id}`);
    if (!el || el.hidden) return;
    if (el.getBoundingClientRect().top <= line) on = s.id;
  });
  // the bottom of the page cannot put a short last section past the line
  if (window.innerHeight + window.scrollY >= document.body.scrollHeight - 4) {
    const last = SECTIONS.filter((s) => { const el = $(`sec-${s.id}`); return el && !el.hidden; }).pop();
    if (last) on = last.id;
  }
  return on;
}

function mine(A) { return !!A && !A.locked && A.ref === ME_SLUG; }

// The owed questions on one form, by kind. One lookup so the four places that badge this cannot
// disagree about who owes what.
function owedFor(A, kind) {
  const f = (A.forms || []).filter((x) => x.kind === kind)[0];
  return (f?.owed) || [];
}

// ── the card ──────────────────────────────────────────────────────────────────

// What crewcard.js needs to draw a person. The account payload is shaped around one member rather
// than a roster, so this is the adapter between the two.
function cardContact(A) {
  const me = A.me || {};
  return {
    path: me.path || "", slug: A.ref, name: me.name || "", summary: me.summary || "",
    aliases: me.aliases || [], travel_prefs: me.travel_prefs || {},
    food_prefs: me.food_prefs || {}, filled: me.filled || [], card: A.card || {},
  };
}

function Card({ A }) {
  let html = "";
  if (A) {
    const me = A.me || {};
    const c = cardContact(A);
    html = CC.card({ id: "me", name: me.name || A.ref }, c, c.travel_prefs);
  }
  return <div className="crewgrid" id="acctCard" dangerouslySetInnerHTML={{ __html: html }} />;
}

// ── nav ───────────────────────────────────────────────────────────────────────

function navCounts(A) {
  const missing = (A.forms || []).filter((f) => !f.done).length;
  const stale = A.owed_count || 0;
  const locked = PILLARS.filter((p) => !(A.unlocked?.[p.slot])).length;
  return {
    you: locked ? { n: `${locked} to fill in`, owe: true } : { n: "complete" },
    details: {},
    // A submitted form holding off-menu answers used to read "2 answered" here, which is the same
    // "finished" this whole nag exists to contradict.
    prefs: missing ? { n: `${missing} to answer`, owe: true }
         : stale ? { n: `${stale} to re-answer`, owe: true }
                : { n: `${(A.forms || []).length} answered` },
    trips: { n: String((A.trips || []).length) },
  };
}

function Nav({ A, shown, on, hidden }) {
  const counts = A ? navCounts(A) : {};
  // Scroll rather than jump: a hash jump lands the section under the sticky topbar.
  return (
    <nav className="acct-nav" id="acctNav" aria-label="account sections" hidden={hidden}>
      {A ? SECTIONS.filter((s) => shown[s.id]).map((s) => {
        const c = counts[s.id] || {};
        return (
          <a key={s.id} href={`#sec-${s.id}`} data-sec={s.id} className={on === s.id ? "on" : ""}
            onClick={(ev) => { ev.preventDefault(); goTo(s.id); }}>
            {s.label}
            {c.n ? <span className={`nav-n${c.owe ? " nav-owe" : ""}`}>{c.n}</span> : null}
          </a>
        );
      }) : null}
    </nav>
  );
}

// ── you ───────────────────────────────────────────────────────────────────────

function You({ A, onOpenForm }) {
  if (!A) return (
    <>
      <p className="asec-sub" id="youSummary"></p>
      <div className="ladder" id="youLadder"></div>
      <p className="asec-foot" id="youFoot"></p>
    </>
  );
  const me = A.me || {};
  const done = me.filled || [];
  const bits = [];
  if ((A.trips || []).length) {
    bits.push(`on ${A.trips.length} trip${A.trips.length === 1 ? "" : "s"}`);
  }
  if (done.length) bits.push(`${done.length} of ${(A.forms || []).length} forms answered`);
  return (
    <>
      <p className="asec-sub" id="youSummary">{mine(A)
        ? "Everything on this page is yours, and only you can change it."
        : `You are in ${me.name || A.ref}'s account. Every change here saves to them.`}</p>
      <div className="ladder" id="youLadder">{PILLARS.map((p) => {
        const open = !!(A.unlocked?.[p.slot]);
        // A rung stays ticked on a stale form (it is earned by answering once), but the tick alone
        // read as "nothing left to do here", so the rung keeps its tick and carries the count.
        const stale = p.go !== "details" ? owedFor(A, p.go).length : 0;
        const sub = stale
          ? stale + (stale === 1 ? " answer is" : " answers are") + " out of date " + DASH + " about "
            + (A.fix_minutes || 2) + " minutes"
          : open ? "done" : p.why;
        return (
          <div key={p.slot} className={`lrung${open ? " done" : ""}${stale ? " stale" : ""}`}>
            <span className="lrung-pip" aria-hidden="true">{open ? "✓" : ""}</span>
            <span><span className="lrung-t">{mine(A) ? p.pillar : p.pillar.replace("your ", "their ")}</span>
              <span className="lrung-s">{sub}</span></span>
            {stale ? <span className="owe-b">{stale}</span> : null}
            <button type="button" className={`lrung-go${stale ? " abtn-accent" : ""}`} data-go={p.go}
              onClick={() => { if (p.go === "details") goTo("details"); else onOpenForm(p.go); }}>
              {`${stale ? "bring it up to date" : open ? (p.go === "details" ? "edit" : "change answers") : "fill it in"} →`}
            </button>
          </div>
        );
      })}</div>
      <p className="asec-foot" id="youFoot">{bits.join(" · ")}</p>
    </>
  );
}

// ── details ───────────────────────────────────────────────────────────────────
//
// Rendered only where the signup row was passed, which is the mirror: a guest owns the row this
// edits. Hub renders the same page without it. Fields are controlled state hydrated from the row
// the server rendered; the request body is the trimmed value of every field, as before.

function Details({ me, onSaved }) {
  const seed = () => {
    const v = {};
    FIELDS.forEach((f) => { v[f.k] = me[f.k] || ""; });
    return v;
  };
  const [vals, setVals] = useState(seed);
  const [errs, setErrs] = useState({});
  const [note, setNote] = useState({ cls: "anote", text: "" });
  const [busy, setBusy] = useState(false);

  // The bar appears only once something is actually different.
  const dirty = FIELDS.some((f) => vals[f.k].trim() !== String(me[f.k] || "").trim());
  const edit = (k, v) => {
    setVals((cur) => { const n = Object.assign({}, cur); n[k] = v; return n; });
    setNote({ cls: "anote", text: "" });
  };

  // Client-side so the message lands on the field that is wrong. The server validates the same
  // rules and is what actually decides.
  const check = () => {
    const e = {};
    FIELDS.forEach((f) => {
      const v = vals[f.k].trim();
      if (f.req && !v) { e[f.k] = "required"; return; }
      if (v.length > f.max) { e[f.k] = `keep it under ${f.max} characters`; return; }
      if (f.k === "email" && v && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v)) {
        e[f.k] = "that doesn't look like an email";
      }
    });
    setErrs(e);
    return !Object.keys(e).length;
  };

  const save = () => {
    if (!check()) return;
    const body = {};
    FIELDS.forEach((f) => { body[f.k] = vals[f.k].trim(); });
    setBusy(true);
    setNote({ cls: "anote", text: "saving…" });
    fetch("/gate/me", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => r.json().then((out) => ({ ok: r.ok, out }))).then((res) => {
      if (!res.ok) {
        setNote({ cls: "anote anote-bad", text: res.out.error || "could not save that" });
        setBusy(false);
        return;
      }
      // Redraw from what was STORED, not from what was typed: the server trims.
      const next = {};
      FIELDS.forEach((f) => { next[f.k] = res.out[f.k] || ""; });
      setVals(next);
      setNote({ cls: "anote anote-ok", text: "saved" });
      setBusy(false);
      onSaved(res.out);
    }).catch(() => {
      setNote({ cls: "anote anote-bad", text: `could not save just now ${DASH} try again in a moment` });
      setBusy(false);
    });
  };

  const row = (f) => (
    <div className="arow" key={f.k}>
      <label htmlFor={`d-${f.k}`}>{f.l}{f.k === "address" ? <>{" "}<span className="anote">(optional)</span></> : null}</label>
      {f.k === "address"
        // the address input is a combobox: AddrCombo adds the roles and autocomplete="off"
        ? <AddrCombo id="d-address" maxLength={f.max} value={vals.address} onChange={(v) => { edit("address", v); }} />
        : <input id={`d-${f.k}`} type={f.type || "text"} maxLength={f.max} autoComplete={f.ac} value={vals[f.k]}
            aria-invalid={errs[f.k] ? "true" : undefined} onChange={(ev) => { edit(f.k, ev.target.value); }} />}
      <span className="arow-err" id={`e-${f.k}`}>{errs[f.k] || ""}</span>
    </div>
  );
  return (
    <>
      <div className="atwo">{FIELDS.slice(0, 2).map(row)}</div>
      {FIELDS.slice(2).map(row)}
      <div className="asave" id="dSave" hidden={!dirty}>
        <button type="button" className="abtn abtn-accent" id="dSaveBtn" disabled={busy} onClick={save}>save changes</button>
        <button type="button" className="abtn" id="dResetBtn" onClick={() => {
          setVals(seed()); setErrs({}); setNote({ cls: "anote", text: "" });
        }}>discard</button>
        <span className={note.cls} id="dNote">{note.text}</span>
      </div>
    </>
  );
}

// ── preferences ───────────────────────────────────────────────────────────────

// Which questions on THIS form the group read cannot place, named. A grid says how many of its
// rows are missing, because owed once and owed nine times are very different asks.
function OwedBlock({ f }) {
  if (!f.done || !(f.owed || []).length) return null;
  const list = f.owed.map((q) => q.title + (q.rows > 1 ? ` (${q.rows})` : "")).join(", ");
  return (
    <div className="pblock-owed"><b>{`${f.owed.length} question${f.owed.length === 1 ? "" : "s"} to bring up to date`}</b>
      {" " + DASH + " " + list + ". Your old answer is not on the form any more, so the group read skips you"
        + " on these until you re-answer."}</div>
  );
}

// The full spread of the interests grid, every answer at what was actually said, on the five-stop
// red-to-green ramp. CC.sbar hands back HTML, so the strip is built as a string like the plain page.
function spreadHTML(grid) {
  const ent = Object.entries(grid || {});
  if (!ent.length) return "";
  const order = ["must", "want", "neutral", "rather-not", "hate"];
  ent.sort((a, b) => order.indexOf(a[1]) - order.indexOf(b[1]));
  return `<div class="rateset">${ent.map((kv) => {
    const pos = CC.scalePos("interests", kv[1]);
    const tint = pos ? ` style="--c:${CC.rampColor(pos.t, true)}"` : "";
    return '<div class="rate"' + tint + ">"
      + '<span class="rate-t">' + esc(kv[0]) + "</span>"
      + '<span class="rate-v">' + esc(CC.label("interests", kv[1])) + "</span>"
      + CC.sbar("interests", kv[1]) + "</div>";
  }).join("")}</div>`;
}

// The crew card's own builders, not a second rendering of the same answers. Travel is one HTML
// string, like the plain page, because the spread strip and the card's notes are siblings of
// the headings and a wrapper element would change the DOM.
function travelHTML(p, fp) {
  const spread = spreadHTML(p.interests);
  return (spread ? `<h4 class="rb-h">every interest, at what you actually said</h4>${spread}` : "")
    + '<h4 class="rb-h">the three that can wreck a plan</h4>'
    + '<div class="hub-card-notes ccard-notes">' + CC.crewNotes(p, fp) + "</div>";
}

function FoodReadback({ fp }) {
  return (
    <>
      <div className="hub-card-facts ccard-facts" dangerouslySetInnerHTML={{ __html: CC.foodFacts(fp) }} />
      <div className="hub-card-notes ccard-notes" dangerouslySetInnerHTML={{ __html: CC.foodNotes(fp) }} />
    </>
  );
}

// Where you are the only one holding your position: the server reports only the tags where this
// person's rating is the unique extreme, which is the case the group's plan actually runs into.
function Outliers({ A }) {
  const rows = (A.outliers || []).slice(0, 8);
  if (!rows.length) return null;
  return (
    <div className="outs"><h3 className="outs-h">where you are the odd one out</h3>
      <p className="outs-sub">{"The tags nobody else rated the way you did. "
        + "Not a problem, just the thing worth saying out loud before somebody books it."}</p>
      <div className="hub-card-grid outs-list">{rows.map((r, i) => (
        <div key={i} className={`hub-card out out-${r.side}`}>
          {/* `r.grid` decides the vocabulary: the list mixes both grids, and they word the same value differently */}
          <span className="hub-card-l out-r">{CC.label(r.grid || "interests", r.yours)}</span>
          <span className="hub-card-t">{r.tag}</span>
          <span className="hub-card-s">{"nobody else went " + (r.side === "keener" ? "as high" : "as low")
            + " " + DASH + " nearest is " + r.nearest + " of " + r.others}</span>
        </div>
      ))}</div></div>
  );
}

function Prefs({ A, onOpenForm }) {
  if (!A) return null;
  const me = A.me || {};
  return (
    <>
      {(A.forms || []).map((f) => {
        const stale = f.done && (f.owed || []).length;
        return (
          <div key={f.kind} className={`pblock${stale ? " stale" : ""}`}><div className="pblock-h">
            <span className="pblock-t">{f.label}</span>
            {stale ? <span className="owe-b">{stale}</span> : null}
            <span className="pblock-when">{f.done ? `answered ${when(f.submitted_at)}` : "not answered yet"}</span>
            <button type="button" className={`abtn${f.done && !stale ? "" : " abtn-accent"}`} data-form={f.kind}
              onClick={() => { onOpenForm(f.kind); }}>
              {!f.done ? "fill it in" : stale ? "bring it up to date" : "change answers"}</button></div>
            <OwedBlock f={f} />
            {f.done
              ? (f.kind === "food"
                  ? <div className="pblock-body"><FoodReadback fp={me.food_prefs || {}} /></div>
                  : <div className="pblock-body"
                      dangerouslySetInnerHTML={{ __html: travelHTML(me.travel_prefs || {}, me.food_prefs || {}) }} />)
              : <div className="pblock-empty">{"Nothing here until you answer it. "
                  + "Nothing on it is required " + DASH + " a half-answered form counts."}</div>}
          </div>
        );
      })}
      <Outliers A={A} />
    </>
  );
}

Object.assign(window.AccountUI, {
  CC, REF, ME_SLUG, QS, SECTIONS, PILLARS, FIELDS, DASH, when, measureTopbar, prefersStill, goTo, spyId, mine,
  Card, Nav, You, Details, Prefs,
});
})();
