/* The guest trip form body (2026-10-13): React port of trip-intake.js. The form is the same
   DOM and classes the plain page built; field values stay uncontrolled and are read back
   from the DOM on save, exactly as before, so the request body is unchanged. Template
   globals: INTAKE {trip_id, prefill, base}. The pure part between the pure markers is
   also what tests/trip-intake.selftest.js loads, so keep it free of JSX and React. */
window.TripIntakeUI = window.TripIntakeUI || {};
(() => {
const { useState, useRef, useLayoutEffect, useEffect } = React;

/* pure:begin */
  var TRIP_FIELDS = [
    ["name", "Trip name"], ["destination", "Where"], ["start_date", "Start date (YYYY-MM-DD)"],
    ["end_date", "End date (YYYY-MM-DD)"], ["notes", "Notes", "t"],
    ["trip_interests", "What the group is into", "t"], ["grocery_extras", "Grocery extras", "t"],
  ];
  /* [field, label, kind] kind: n number, t textarea, default text. A leading "more"
     marker splits the rarely used fields into a folded group. */
  var SECTIONS = [
    { id: "members", title: "Crew", one: "person", add: "+ add a person", fields: [
      ["name", "Name"], ["email", "Email"], ["notes", "Notes", "t"]] },
    { id: "housing", title: "Housing", one: "place", add: "+ add a place", fields: [
      ["name", "Name"], ["address", "Address"], ["check_in", "Check in"], ["check_out", "Check out"],
      ["nightly_rate", "Per night", "n"], ["total_cost", "Total cost", "n"], ["url", "Link"],
      ["notes", "Notes", "t"], "more",
      ["confirmation_code", "Confirmation code"], ["guests", "Guests", "n"], ["bedrooms", "Bedrooms", "n"],
      ["beds", "Beds", "n"], ["baths", "Baths", "n"], ["parking", "Parking"], ["amenities", "Amenities"],
      ["paid_by", "Paid by"], ["split_with", "Split with"]] },
    { id: "flights", title: "Flights", one: "flight", add: "+ add a flight", fields: [
      ["direction", "Direction (to / from)"], ["airline", "Airline"], ["flight_num", "Flight number"],
      ["from_airport", "From airport"], ["to_airport", "To airport"], ["departure_time", "Departs"],
      ["arrival_time", "Arrives"], ["passenger", "Who is flying"], ["cost", "Cost", "n"],
      ["confirmation", "Confirmation"], ["notes", "Notes", "t"], "more",
      ["paid_by", "Paid by"], ["split_with", "Split with"]] },
    { id: "transportation", title: "Getting around", one: "ride", add: "+ add a ride", fields: [
      ["type", "Kind (rental, bus, ...)"], ["description", "What it is"], ["departure", "From"],
      ["arrival", "To"], ["scheduled_date", "Date"], ["scheduled_time", "Time"], ["cost", "Cost", "n"],
      ["url", "Link"], ["notes", "Notes", "t"], "more",
      ["seats", "Seats", "n"], ["confirmation", "Confirmation"], ["pickup_time", "Pickup time"],
      ["dropoff_time", "Dropoff time"], ["paid_by", "Paid by"], ["split_with", "Split with"]] },
    { id: "activities", title: "Activities", one: "activity", add: "+ add an activity", fields: [
      ["name", "Name"], ["location", "Where"], ["description", "What it is", "t"], ["scheduled_date", "Date"],
      ["scheduled_time", "Start time"], ["cost", "Cost", "n"], ["url", "Link"], ["notes", "Notes", "t"],
      "more", ["scheduled_time_end", "End time"], ["split_with", "Split with"]] },
    { id: "expenses", title: "Expenses", one: "expense", add: "+ add an expense", fields: [
      ["description", "What for"], ["category", "Category"], ["amount", "Amount", "n"],
      ["currency", "Currency"], ["paid_by", "Paid by"], ["split_with", "Split with"]] },
  ];

  function secOf(id) { return SECTIONS.filter((x) => x.id === id)[0]; }
  function byKey(rows) { var m = {}; (rows || []).forEach((r) => { m[r.key] = r; }); return m; }
  function blank(v) { return v === null || v === undefined || v === ""; }
  /* Number fields compare as numbers (120 vs "120.0"); text never does ("0123" vs "123"). */
  function same(a, b, num) {
    if (blank(a) && blank(b)) return true;
    if (blank(a) || blank(b)) return false;
    if (num) return Number(a) === Number(b);
    return String(a) === String(b);
  }
  function isNum(sec, f) {
    var s = secOf(sec);
    return !!s && s.fields.some((x) => x[0] === f && x[2] === "n");
  }

  /* prefill and now share the payload shape. Same result shape as intake.intake_diff. */
  function intakeDiff(prefill, now) {
    var d = { trip: {}, added: {}, removed: {}, changed: {} };
    var pt = prefill.trip || {};
    Object.keys(now.trip || {}).forEach((f) => {
      if (!same(pt[f], now.trip[f])) d.trip[f] = [blank(pt[f]) ? null : pt[f], now.trip[f]];
    });
    Object.keys(now.sections || {}).forEach((sec) => {
      var live = byKey(prefill.sections?.[sec]);
      var sent = {};
      now.sections[sec].forEach((r) => {
        sent[r.key] = 1;
        var old = live[r.key];
        if (!old) { (d.added[sec] = d.added[sec] || []).push(r); return; }
        Object.keys(r).forEach((f) => {
          if (f === "key" || same(old[f], r[f], isNum(sec, f))) return;
          d.changed[sec] = d.changed[sec] || {};
          (d.changed[sec][r.key] = d.changed[sec][r.key] || {})[f] = [blank(old[f]) ? null : old[f], r[f]];
        });
      });
      var gone = Object.keys(live).filter((k) => !sent[k]);
      if (gone.length) d.removed[sec] = gone;
    });
    return d;
  }

  function isEmpty(d) {
    return !Object.keys(d.trip).length && !Object.keys(d.added).length &&
      !Object.keys(d.removed).length && !Object.keys(d.changed).length;
  }

  function labelOf(list, f) {
    for (let i = 0; i < list.length; i++) if (list[i][0] === f) return list[i][1];
    return f;
  }
  function show(v) { return blank(v) ? "(blank)" : String(v); }
  function rowName(sec, row) {
    var s = secOf(sec);
    return row.name || row.description || row.airline || row.type || (`a ${s.one}`);
  }

  /* Plain-language lines for the confirm dialog. */
  function describe(prefill, d) {
    var out = [];
    Object.keys(d.trip).forEach((f) => {
      out.push(`Trip ${labelOf(TRIP_FIELDS, f).toLowerCase()}: ${show(d.trip[f][0])} -> ${show(d.trip[f][1])}`);
    });
    SECTIONS.forEach((s) => {
      var live = byKey(prefill.sections?.[s.id]);
      ((d.changed[s.id]) ? Object.keys(d.changed[s.id]) : []).forEach((k) => {
        Object.keys(d.changed[s.id][k]).forEach((f) => {
          var c = d.changed[s.id][k][f];
          out.push(s.title + ", " + rowName(s.id, live[k]) + ", " + labelOf(s.fields, f).toLowerCase() +
            ": " + show(c[0]) + " -> " + show(c[1]));
        });
      });
      (d.added[s.id] || []).forEach((r) => { out.push(`Added ${s.one}: ${rowName(s.id, r)}`); });
      (d.removed[s.id] || []).forEach((k) => { out.push(`Removed ${s.one}: ${rowName(s.id, live[k])}`); });
    });
    return out;
  }

/* pure:end */

const INTAKE = window.INTAKE, PRE = INTAKE.prefill || { trip: {}, sections: {} };

function Field({ f, val, readOnly }) {
  const kind = f[2], v = blank(val) ? "" : String(val);
  const [id] = useState(() => `f${Math.random().toString(36).slice(2, 9)}`);
  return (
    <div className="hub-field">
      <label htmlFor={id}>{f[1]}</label>
      {kind === "t"
        ? <textarea id={id} data-f={f[0]} defaultValue={v}></textarea>
        : <input id={id} data-f={f[0]} data-n={kind === "n" ? 1 : 0} type={kind === "n" ? "number" : "text"}
            step={kind === "n" ? "any" : undefined} inputMode={kind === "n" ? "decimal" : undefined} defaultValue={v} readOnly={readOnly || undefined} />}
    </div>
  );
}

function Row({ sec, row, onDelete }) {
  const more = sec.fields.indexOf("more");
  const main = sec.fields.filter((f, i) => f !== "more" && (more < 0 || i < more));
  const fold = more < 0 ? [] : sec.fields.filter((_f, i) => i > more);
  const nm = rowName(sec.id, row);
  /* Existing crew names decide trip access, so they are Sam's to change (intake.clean). */
  const lock = sec.id === "members" && row.key.indexOf("db:") === 0;
  return (
    <div className="hub-card" data-key={row.key}>
      <div className="ix-head"><span className="hub-card-l">{sec.one}</span>
        <button type="button" className="hub-row-delete" title={`remove ${nm}`} aria-label={`remove ${nm}`}
          onClick={onDelete}>×</button></div>
      {main.map((f) => <Field key={f[0]} f={f} val={row[f[0]]} readOnly={lock && f[0] === "name"} />)}
      {fold.length ? <details className="hub-field-group"><summary>more</summary>
        {fold.map((f) => <Field key={f[0]} f={f} val={row[f[0]]} />)}</details> : null}
    </div>
  );
}

function val(el) {
  const v = el.value.trim();
  if (v === "") return null;
  if (el.dataset.n === "1") { const n = Number(v); return Number.isFinite(n) ? n : null; }
  return v;
}

/* A render error shows the same words the load fallback does. */
class Boundary extends React.Component {
  constructor(p) { super(p); this.state = { failed: false }; }
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(e) { console.error("trip-intake", e); }
  render() { return this.state.failed ? <div className="hub-error">page failed to load</div> : this.props.children; }
}

function Body() {
  const [rows, setRows] = useState(() => {
    const m = {};
    SECTIONS.forEach((s) => { m[s.id] = (PRE.sections?.[s.id] || []).slice(); });
    return m;
  });
  const [open, setOpen] = useState(false);
  const [lines, setLines] = useState([]);
  const [sending, setSending] = useState(false);
  const [note, setNote] = useState({ msg: "", bad: false, sent: false });
  const form = useRef(null), pending = useRef(null), focusKey = useRef(null);
  const scrim = document.getElementById("ixScrim");

  useLayoutEffect(() => {
    if (!focusKey.current) return;
    const card = form.current.querySelector(`[data-key="${focusKey.current}"]`);
    focusKey.current = null;
    if (card) card.querySelector("input,textarea").focus();
  });
  useEffect(() => { scrim.hidden = !open; }, [open]);
  useEffect(() => { document.getElementById("ixMain").setAttribute("data-react-mounted", "trip-intake"); }, []);

  function collect() {
    const p = { trip: {}, sections: {} };
    form.current.querySelector("#ixTrip").querySelectorAll("[data-f]").forEach((el) => { p.trip[el.dataset.f] = val(el); });
    SECTIONS.forEach((s) => {
      p.sections[s.id] = [].map.call(form.current.querySelectorAll(`[data-sec="${s.id}"] [data-key]`), (card) => {
        const r = { key: card.dataset.key };
        card.querySelectorAll("[data-f]").forEach((el) => { r[el.dataset.f] = val(el); });
        return r;
      }).filter((r) => {  /* an added card left empty is not a row */
        return r.key.indexOf("new:") !== 0 || Object.keys(r).some((f) => f !== "key" && !blank(r[f]));
      });
    });
    return p;
  }

  const del = (sec, key) => setRows((m) => Object.assign({}, m, { [sec]: m[sec].filter((r) => r.key !== key) }));
  function add(s) {
    const key = `new:${crypto.randomUUID()}`;
    focusKey.current = key;
    setRows((m) => Object.assign({}, m, { [s.id]: m[s.id].concat([{ key }]) }));
  }

  function save() {
    const now = collect(), d = intakeDiff(PRE, now);
    if (isEmpty(d)) { setNote({ msg: "Nothing changed.", bad: false, sent: false }); return; }
    pending.current = now;
    setLines(describe(PRE, d));
    setOpen(true);
  }

  function confirm() {
    setOpen(false);
    setSending(true);
    fetch(`/trips/api/trips/${INTAKE.trip_id}/intake`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ payload: pending.current, base: INTAKE.base }),
    }).then((r) => r.json().catch(() => ({})).then((j) => [r.ok, j]))
      .then((res) => {
        if (res[0] && res[1].ok) { setNote((n) => ({ msg: "", bad: n.bad, sent: true })); return; }
        setSending(false);
        setNote({ msg: res[1].error || "Could not send. Try again.", bad: true, sent: false });
      })
      .catch(() => { setSending(false); setNote({ msg: "Could not reach the server. Try again.", bad: true, sent: false }); });
  }

  return (
    <>
      <h1 className="asec-h" id="ixTitle">{PRE.trip?.name ? PRE.trip.name : "trip details"}</h1>
      <p className="asec-sub">Fix anything that is wrong and add anything that is missing. Nothing goes live
        until Sam reviews it.</p>
      <div id="ixForm" ref={form}>
        <section className="asec"><h2 className="asec-h">Trip basics</h2><div className="ix-rows hub-card" id="ixTrip">
          {TRIP_FIELDS.map((f) => <Field key={f[0]} f={f} val={PRE.trip?.[f[0]]} />)}
        </div></section>
        {SECTIONS.map((s) => (
          <section className="asec" data-sec={s.id} key={s.id}><h2 className="asec-h">{s.title}</h2>
            <div className="ix-rows">
              {rows[s.id].map((r) => <Row key={r.key} sec={s} row={r} onDelete={() => del(s.id, r.key)} />)}
            </div>
            <button type="button" className="hub-pending-add" data-add={s.id} onClick={() => add(s)}>{s.add}</button>
          </section>
        ))}
      </div>
      <div className="ix-bar">
        <button type="button" className="abtn abtn-accent" id="ixSave" disabled={sending} onClick={save}>save</button>
        <span className={`anote${note.bad ? " anote-bad" : ""}`} id="ixNote">
          {note.sent
            ? <><span className="hub-pending">Sent to Sam for review</span> <span className="hub-pill hub-pill--dashed">pending</span></>
            : note.msg}
        </span>
      </div>
      {ReactDOM.createPortal(
        <div className="hub-modal" role="dialog" aria-modal="true" aria-labelledby="ixMTitle">
          <div className="hub-modal-title" id="ixMTitle">You changed:</div>
          <div className="hub-modal-body" id="ixMBody"><ul className="ix-lines">{lines.map((l, i) => <li key={i}>{l}</li>)}</ul></div>
          <div className="hub-modal-actions">
            <button type="button" className="hub-modal-btn" id="ixKeep" onClick={() => setOpen(false)}>Keep editing</button>
            <button type="button" className="hub-modal-btn" id="ixConfirm" onClick={confirm}>Confirm</button>
          </div>
        </div>, scrim)}
    </>
  );
}

const host = document.getElementById("ixMain");
host.textContent = "";  // the template's static copy is only the load fallback
document.getElementById("ixScrim").textContent = "";  // the portal below fills it; hidden is toggled by Body
ReactDOM.createRoot(host).render(<Boundary><Body /></Boundary>);
})();
