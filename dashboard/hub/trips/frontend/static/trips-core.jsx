/* hub · trips page, core (2026-10-13): React port of trips.js lines 1-611, plus the React shell the other
   parts hang off. Same DOM and classes as the plain page. The plain page renders by building HTML strings and
   writing them into fixed hosts (#focusHead, #focusList, #context, #dayMapHost, #funnelSub, #modal, #confirmModal,
   #calNotice) and then reading that DOM back (focus, scroll, querySelector). The later parts keep that: they are
   straight ports of their trips.js ranges, written as plain functions inside an IIFE, assigned onto TripsUI.
   React owns the shell, the mount, the error boundary and the store; every host above is rendered with NO React
   children, so React never touches what the parts write into them. No object spread, no async/await and no JSX
   prop spread in any trips JSX file (Babel would emit top-level helpers jsx_globals_check rejects): use
   Object.assign and promise chains.

   Template globals read here: window.TRIP_ID, window.TRIP_VIEWER (via TripCost), body.guest. The header, its
   [data-slot] extras and the Jinja blocks stay in trips.html; this file renders everything after the header.
   First file of the trips surface was trips-cost.jsx (it created window.TripsUI and TripsUI.TripsCost/Price/
   priceText). This file only adds keys. NOTE: TripsUI.priceText is that landing-page function; the plain page's
   priceText(p, plain) is exported here as TripsUI.priceHtml. Never reassign either.

   INTERFACE (everything below is on window.TripsUI; read it at CALL time as TripsUI.name, never destructure a
   name another part owns while your IIFE is loading; destructuring the names listed here is fine because this
   file loads before every part):

   Plumbing
     fwd(...names)                forwarders to functions another part owns (see below), mut {dayMap, dayMapKey, foodMounted, closeConfirmActive}
     api {get, post, patch, del}  base /trips/api; each returns a promise, rejects with Error(text || status)
     req(method, url, body)       the raw call api wraps
     state                        THE mutable page state (trips.js `state`), one object for the page's life
     store, TripsContext, useTrips()   subscribe/notify store for any real React component (see below)
     T, FC, TC, CC                window.TripTime, FlightChain, TripCost, CrewCard
   DOM and feedback (all take effect immediately, like the plain page)
     $(id), esc(s), setHTML(el, html), toast(msg), status(msg, meta), errMsg(e), renderLoadError(msg, retry)
   Formatting
     money, num1, points, pointsCell, parseTags, haversine, isGuest, viewerKey, memberKey, isViewer,
     statusLabel, pipVar, QUEUE, PIP_STATUSES, firstName, todayISO
   Stays and distances
     chosenStay, lastStay, housingAnchor, distFromStay
   Cost model (aliases of TripCost, all pure)
     isCommitted, isDead, isOpen, rowCost, sumCost, myFlights, busOf, isCar, myFares, supersededExpense,
     isSettled, carPickup, carDropoff, tripMoney(), tripLedger(), priceHtml(p, plain), CHASE, costChart(m),
     costContext()
   Constants
     FIRM, FULL_MODES, MODES, NAV_KEY(id)
   Nav memory and boot
     readNav(id), saveNav(), defaultDay(), boot(), selectTrip(id), statusCounts(msg), renderCalNotice(t),
     renderAll(), enterPane(), openDrawer(), closeDrawer(), syncNavHost(mql)
   React
     Boundary, Shell, Overlays, TripsApp, mount()   mount() is called once, by trips.jsx, after every part loaded

   WHAT THE PARTS MUST EXPORT for this file (called at call time as TripsUI.<name>):
     renderFunnelNav(), renderFocus(), renderContext()   renderAll() runs them in that order, synchronously
     wireChrome()  loadPrefs()  loadFood()  unmountFood()  hallmarkDef()  tripDays()  selfCheck()
     FunnelNav     React component: the twelve button.fnav, the #funnelSub div between itinerary and cost
   The full part-by-part contract is in /tmp/hub-sandbox/trips-parts-interface.md.

   The store: renderAll() re-draws the three hosts imperatively, then calls store.notify() so a part that adds a
   real React component can subscribe with useTrips() (returns the same `state` object, re-rendering on notify).
   Nothing here depends on a subscriber existing. */
window.TripsUI = window.TripsUI || {};
(() => {
const { useState, useEffect, useLayoutEffect } = React;
const U = window.TripsUI;

// ── API ───────────────────────────────────────────────────────────────────
const BASE = "/trips/api";
function req(method, url, body) {
  const opt = { method: method, headers: {} };
  if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  return fetch(BASE + url, opt).then((r) => {
    if (!r.ok) return r.text().then((t) => { throw new Error(t || r.status); });
    const ct = r.headers.get("content-type") || "";
    return ct.includes("json") ? r.json() : r.text();
  });
}
const API = {
  get: (u) => req("GET", u),
  post: (u, b) => req("POST", u, b || {}),
  patch: (u, b) => req("PATCH", u, b || {}),
  del: (u) => req("DELETE", u),
};

const T = window.TripTime;      // time parsing, see triptime.js
const FC = window.FlightChain;  // connecting-segment collapse, see flightchain.js
const CC = window.CrewCard;     // crew card HTML, see crewcard.js

// ── State ─────────────────────────────────────────────────────────────────
const state = {
  trip: null,
  mode: "flights",        // fallback landing section; the last one you used wins (see readNav)
  day: null,              // itinerary sub-tab: a trip date, or "cal" for the whole-trip overview
  selId: null,            // selected funnel item id (scoped per mode)
  search: "",
  sort: "score-desc",
  statusFilter: null,     // activities: 'considering'|'deciding'|'scheduled' or null
  pinFilter: "all",       // activities map only: "all" | "scheduled", narrows pins, keeps the list whole
  prefs: null,            // crew preferences payload (lazy)
  food: null,             // this trip's city's /food research (lazy), null until loadFood answers
  foodErr: "",
  lsort: {},              // comparison sort, per kind: { col, dir }
  ground: null,           // transportation sub-tab; null = land on the board that has rows

  // What you're bringing. Sticker fares hide it: every airline on a US domestic
  // route now charges for the first checked bag, so two $179 fares are not the
  // same price once one of them is on United Basic Economy. Ticking these
  // reprices every fare row to what you'd actually pay.
  bags: { carry: false, checked: false },
  party: null,            // housing: heads sleeping there. null = however many are on the crew list
  near: null,             // { hid, data | error }, what's walkable from that stay (see nearbyContext)
  // The option you're currently weighing, per decision. Clicking a row picks it,
  // which is also what opens its detail, one gesture, because "the one I'm
  // looking at" and "the one I'd take" are the same thing while you compare.
  pick: {},
};
// Only booked/confirmed logistics land on the itinerary. Without this the
// El Salvador trip stacks four "considering" JFK→SAL flights (three of them
// alternatives for the same leg) on one hour, and Denver draws six
// simultaneous check-ins. An itinerary is what's happening, not the shortlist.
const FIRM = ["booked", "confirmed"];
// the five tabs the origin's hub-t3p-split[data-split] full-width rules
// (moved to tabbed-3-pane.css) used to key on directly -- the body IS the
// answer on these, and a side pane beside it is a second read competing
// with the one thing the tab is for.
const FULL_MODES = new Set(["dayof", "hallmark", "grocery", "packing", "weather"]);

// The store a real React component subscribes to. renderAll() notifies after the imperative redraw.
const listeners = new Set();
const store = {
  state: state,
  subscribe: (fn) => { listeners.add(fn); return () => { listeners.delete(fn); }; },
  notify: () => { listeners.forEach((fn) => { fn(state); }); },
};
const TripsContext = React.createContext(store);
function useTrips() {
  const [, bump] = useState(0);
  useEffect(() => store.subscribe(() => { bump((n) => n + 1); }), []);
  return state;
}

// ── Tiny DOM helpers ────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
function setHTML(el, html) { el.innerHTML = html; }
function toast(msg) {
  const t = $("toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 2200);
}
function status(msg, meta) { $("statusMsg").textContent = msg; if (meta !== undefined) $("statusMeta").textContent = meta; }
// human-readable text for a thrown value, never lets a raw object leak into a toast as "[object Object]"
function errMsg(e) { return (e?.message) ? e.message : String(e); }
// boot/load failure: message in the status bar + a retryable .hub-error block where the list would go
function renderLoadError(msg, retryFn) {
  status(msg);
  setHTML($("focusList"), `<div class="hub-error">${esc(msg)}<button class="hub-error-retry" id="loadRetry">retry</button></div>`);
  $("loadRetry").onclick = retryFn;
}

// ── Formatting ──────────────────────────────────────────────────────────────
const money = (n) => (n == null || n === "" ? "—" : `$${Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
const num1 = (n) => (n == null || n === "" ? "—" : Number(n).toFixed(1));
// Award prices sit beside cash prices and follow the same ",  means not
// relevant" rule money() uses. An Airbnb has no points price and never will;
// that is a fact about the listing, not a missing value, so it renders as a
// dash rather than 0 (which would read as free).
const points = (n, prog) => (n == null || n === "" ? "—"
  : Number(n).toLocaleString() + (prog ? ` ${prog}` : " pts"));
// The public mirror (trips/public_app.py) sets body.guest; Hub never does.
// Read lazily rather than once at module load, this file is parsed before the
// body exists.
const isGuest = () => !!(document.body?.classList.contains("guest"));

// WHO IS READING THIS. The public mirror injects the member key of whoever
// typed the passcode (window.TRIP_VIEWER, set from the guest_codes row); Hub
// leaves it empty, because the board is already his. It orders the flight
// section and nothing else: a guest opens a shared itinerary to find out when
// THEY fly, and their own ticket was rendering fourth, under two legs of
// somebody else's fare comparison.
//
// The key is db.member_key spelled in JS: a contact slug when the member has a
// wiki contact node, otherwise "name:" + their name lowercased. Both spellings
// have to match here, or half the crew never matches their own code.
// Both live in trips-cost.js: the cost model has to answer "who is reading
// this" too, every "your share" figure on the cost tab was Sam's no matter
// whose link was open, and one definition is what keeps the board and the
// money agreeing about who you are.
const TC = window.TripCost;
const viewerKey = () => TC.viewerKey();
const memberKey = (m) => TC.memberKey(m);
const isViewer = (m) => { const v = viewerKey(); return !!(v && m && memberKey(m) === v); };

// Chase UR no longer appears on a booking row, and this is a deliberate model
// change rather than a tidy-up. `points_transfer` is what left the Chase
// account to PRODUCE the award points, it is how the currency was acquired,
// not what the booking was sold for. Avianca charged 12,000 Aeroplan and
// $180.00; that the Aeroplan came from a UR transfer is a separate transaction
// that would have been just as true if the seat were never bought. Printing it
// as "costs you in Chase UR" on the leg read as a third price for one flight.
//
// It is still spent money, so it still counts, in the COST tab and the trip
// total, which is where a cross-cutting pool belongs. `rowUR` in trips-cost.js
// reads `points_transfer` when a fresh Chase transfer produced the award, and
// falls back to `points_total` when it didn't. Either way it renders through
// the ordinary "on points" line. Just the number: the programme name and the
// Chase UR it converts from are one click away on the row.
const pointsCell = (r) => (!r || r.points_total == null || r.points_total === ""
  ? "—" : Number(r.points_total).toLocaleString());
function parseTags(t) {
  if (Array.isArray(t)) return t;
  if (!t) return [];
  try { const p = JSON.parse(t); return Array.isArray(p) ? p : String(t).split(","); }
  catch { return String(t).split(",").map((s) => s.trim()).filter(Boolean); }
}
function haversine(a, b, c, d) {
  if ([a, b, c, d].some((v) => v == null)) return null;
  const R = 3958.8, toR = Math.PI / 180;
  const dLat = (c - a) * toR, dLng = (d - b) * toR;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a * toR) * Math.cos(c * toR) * Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
}

// ── Cost model ──────────────────────────────────────────────────────────────
// Lives in trips-cost.js, shared with the landing page so both pages report
// the same number, see the header there for the model itself and for the
// shared-vs-personal split rule. These are local names for the parts this
// file reads; nothing here re-derives anything.
const isCommitted = TC.isCommitted, isDead = TC.isDead, isOpen = TC.isOpen;
const rowCost = TC.rowCost;
const sumCost = TC.sumCost;
const myFlights = TC.myFlights, busOf = TC.busOf, isCar = TC.isCar;
// Whose SEAT it is (myFlights) versus whose CARD it was (myFares). The board
// cares about the first, the money cares about the second.
const myFares = TC.myFares;
const supersededExpense = (e) => TC.supersededExpense(state.trip || {}, e);
// A decision with a committed row in it is over, even when `considering`
// siblings survive next to it, db.py only purges the rows that were actively
// ruled out, so a shortlist outlives the booking that ended it. Every board
// hands over on this, not on "nothing open is left".
const isSettled = (g) => g.rows.some(isCommitted);
// Migration 007 gave rentals their own clock. A car added before it, trip 1's
// Enterprise pickup at AUS, still carries the generic scheduled_date /
// scheduled_time that the bus rows use, so every reader falls back to those
// rather than reporting a booked car as having no pickup time at all. Read
// through these, never `x.pickup_time` directly.
const carPickup = (x) => x.pickup_time || [x.scheduled_date, x.scheduled_time].filter(Boolean).join(" ");
// No generic analogue for the far end, scheduled_* is a single point in time,
// so a pre-007 row genuinely has no drop-off and says so by staying blank.
const carDropoff = (x) => x.dropoff_time || "";

// The stay you have actually settled on: one you've booked, or one you picked
// by hand. Deliberately NOT the first row that happens to have coordinates , 
// that read as an answer while being an accident of row order, and every
// "3.1 mi" on the board was silently measured from a house nobody had chosen.
// While the housing decision is still open there is no anchor, and the honest
// output is no distance at all.
function chosenStay() {
  const rows = (state.trip?.housing) || [];
  return rows.filter(isCommitted)[0] ||
    (state.pick.housing != null && rows.filter((h) => h.id === state.pick.housing)[0]) || null;
}
// The stay you wake up in on the last morning. A trip can hold two booked
// stays (Columbus 2026-09: a cancelled flight home added a night at a second
// hotel), and chosenStay()'s first-booked row is then the one already checked
// out of.
// ponytail: orders check_out as a string, which holds for the "YYYY-MM-DD HH:MM"
// form booked rows carry. Parse dates if free-text ones ever get booked.
function lastStay() {
  const booked = ((state.trip?.housing) || []).filter(isCommitted);
  return booked.length > 1
    ? booked.slice().sort((a, b) => String(b.check_out || "").localeCompare(String(a.check_out || "")))[0]
    : chosenStay();
}
function housingAnchor() {
  const h = chosenStay();
  return h && h.lat != null && h.lng != null ? { lat: h.lat, lng: h.lng } : null;
}
function distFromStay(a) {
  const anc = housingAnchor();
  if (!anc || a.lat == null || a.lng == null) return null;
  return haversine(anc.lat, anc.lng, a.lat, a.lng);
}

// Per-person by default: `committed` / `projected` / `open` are HIS share, and
// `.group` carries the same three for everyone together. The stay is the whole
// reason, a $1,750 house across seven heads is $250 of his money, and reading
// it as $1,866 made every Denver total wrong by a factor of seven.
function tripMoney() { return TC.tripMoney(state.trip || {}, state.party); }

// What a total actually cost, in the currencies it actually cost it. Cash-only
// reads as it always did; a stay paid entirely in points reads as points and
// never invents a dollar figure for it; a booking that took both shows both.
// Zero of everything is "$0.00", not a blank, a trip with nothing committed
// has a real answer.
//
// `p.ur` is only ever nonzero on Hub (the guest fold in trips-cost.js already
// collapsed it into `p.cash` for the shared mirror before this ever runs), so
// the parenthesized cash value is Hub-only by construction, a reference figure
// alongside the real points count, never substituted for it and never added
// into any total.
// Chase's octagon is the currency mark for a UR figure the way $ is for cash.
// Inline so it costs no request. The geometry is the REAL mark, not a
// hand-drawn approximation: the four paths come from Chase's own logo file
// (Wikimedia "Chase logo 2007.svg", fill #117aca), rescaled to a 24-unit
// viewBox. It is MARKUP, so a call whose result lands in a title="" attribute
// passes plain:true and gets the bare word instead.
const CHASE = '<svg class="ur-mark" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M8.584 0C8.116 0 7.737.379 7.737.847V6.786H23.428L16.281 0Z"/><path d="M24 8.584C24 8.116 23.621 7.737 23.153 7.737H17.214V23.428L24 16.281Z"/><path d="M15.416 24C15.884 24 16.263 23.621 16.263 23.153V17.214H.572L7.719 24Z"/><path d="M0 15.416C0 15.884.379 16.263.847 16.263H6.786V.572L0 7.719Z"/></svg>';
// Exported as priceHtml: TripsUI.priceText already belongs to trips-cost.jsx (the landing page's version).
function priceHtml(p, plain) {
  const parts = [];
  if (p.cash) parts.push(money(p.cash));
  // The mark IS the unit, so it carries no word, same as "$12.00". A title=""
  // caller can't render the mark, so the word stands in there and only there.
  // The dollar figure beside the points is the sum of what each row's own
  // points were worth at that row's own rate (`urCash`, carried by the model
  // since migration 016), NOT this pooled figure run through one rate. A
  // hand-built value with no urCash on it falls back to the trip-wide default.
  if (p.ur) parts.push((plain ? "" : CHASE) + Number(p.ur).toLocaleString()
    + (plain ? " points" : "")
    + " (" + money(p.urCash != null ? p.urCash : p.ur * TC.UR_CENTS) + ")");
  // Each part is its own unbreakable run, so a two-currency value can wrap at
  // the "+" instead of overflowing a fixed-width money column and painting over
  // the column beside it. Plain callers (title="") stay tag-free.
  if (plain) return parts.length ? parts.join(" + ") : money(0);
  var wrapped = (parts.length ? parts : [money(0)])
    .map((x) => `<span class="pmoney">${x}</span>`);
  return wrapped.join(" + ");
}

/* ── COST CHART ─────────────────────────────────────────────────────────────
   Where his money goes on this trip, per category, per person. One bar per
   money table on a shared scale, so "the stay is most of it" is readable
   without doing arithmetic.

   ONE hue, two states. Category identity comes from the row label, not from
   colour. Committed is a solid fill and still-open is the same hue hatched, which
   separates by form and survives every theme and every kind of colour vision.
   Every bar is direct-labeled.

   Points never become dollars: the bar measures cash, and a category paid in
   UR says so in its own label instead of drawing a phantom $0 bar.

   PER PERSON, ALWAYS. It takes the whole money object and reads `byCategory`,
   the per-head view, never `group.byCategory`: a bar chart compares its bars,
   and the only way that comparison is true is if every bar is the same
   person's money. The group figures are still on the page, the tab headline
   and the rail's bill card, they just never reach this chart. */
function costChart(m) {
  const cats = (m.byCategory || []).filter((c) => c.total.cash > 0 || c.total.ur > 0);
  if (!cats.length) return "";
  // One scale across all four bars, a per-row scale would make $50 of tips
  // look the same size as a $250 stay.
  const top = Math.max.apply(null, cats.map((c) => c.total.cash));
  const pct = (v) => (top > 0 ? (v / top) * 100 : 0);
  const rows = cats.map((c) => {
    const label = c.label + (c.shared && m.party > 1 ? ` <span class="cchart-split">${m.party} ways</span>` : "");
    // A points-only category has no cash length, so it gets NO bar, drawing one
    // on the cash scale made El Salvador's 10,000 UR stay the longest bar in a
    // chart whose scale topped out at $200. It says so in words instead.
    const bar = c.total.cash > 0
      ? `<div class="hub-track cchart-track">` +
        (c.committed.cash > 0 ? `<span class="hub-bar cchart-b is-done" style="width:${pct(c.committed.cash).toFixed(2)}%"></span>` : "") +
        (c.open.cash > 0 ? `<span class="hub-bar cchart-b is-open" style="width:${pct(c.open.cash).toFixed(2)}%"></span>` : "") +
        `</div>`
      : `<div class="cchart-none">points only · no cash</div>`;
    const tip = `${c.label} — ${priceHtml(c.committed, true)} committed` +
      (c.open.cash || c.open.ur ? `, ${priceHtml(c.open, true)} still open` : "") +
      (c.shared && m.party > 1 ? ` · split ${m.party} ways` : "");
    return `<div class="cchart-row" title="${esc(tip)}">
      <div class="cchart-head"><span class="cchart-l">${label}</span><span class="cchart-v">${priceHtml(c.total)}</span></div>
      ${bar}</div>`;
  }).join("");
  const anyOpen = cats.some((c) => c.open.cash > 0);
  return `<div class="cchart">
    <div class="cchart-rows">${rows}</div>
    <div class="cchart-key">
      <span><i class="hub-check-dot is-done"></i>committed</span>
      ${anyOpen ? '<span><i class="hub-check-dot is-open"></i>still open</span>' : ""}
      <span class="cchart-scale">per person · full bar ${money(top)}</span>
    </div></div>`;
}

/* ── THE RAIL: where the money came from, and who owes whom ────────────────
   The body of the cost tab is his share, line by line. The rail restates the
   group's money as three cards in the order they get asked:

     1. what does this thing cost, all in, everybody              (the bill)
     2. whose card is it sitting on right now                     (fronted)
     3. so who sends money to whom                                (settle up)

   Assumed prices are kept OUT of 2 and 3 entirely and printed apart in 1.
   Nobody has paid the $200 Saturday-night rideshare, so nobody is owed for it
   and nobody owes it, it is a plan, not a debt, and folding it into a payback
   figure is how a settlement list starts lying. */
function tripLedger() { return TC.ledger(state.trip || {}, state.party); }
const firstName = (n) => String(n || "").trim().split(/\s+/)[0] || "someone";

function costContext() {
  const m = tripMoney();
  const g = m.group || {};
  const led = tripLedger();
  const cats = (g.byCategory || []).filter((c) => c.committed.cash > 0 || c.committed.ur > 0 || c.open.cash > 0 || c.open.ur > 0);
  const anyOpen = g.open && (g.open.cash > 0 || g.open.ur > 0);

  // 1 · THE BILL. One dollar figure: cash plus each row's points at that row's
  // own priced rate, so the headline reads as one number (mark 2026-10-14,
  // "floating text", option B on Workbench set trip-bill-card). The real points
  // count stays in the line under it. Assumed money is never added in, it gets
  // its own dashed key row and only reaches "your share" as a stated "once".
  const usd = (p) => (p ? p.cash + (p.urCash || 0) : 0);
  const done = g.committed || { cash: 0, ur: 0, urCash: 0 };
  const billCats = cats.filter((c) => usd(c.committed) > 0);
  const openCats = cats.filter((c) => usd(c.open) > 0);
  const seg = (i) => `var(--bill-c${i})`;
  const catIdx = (c) => (g.byCategory || []).indexOf(c);
  const bar = billCats.length > 1
    ? `<div class="bill-bar">${billCats.map((c) => `<i style="flex:${usd(c.committed).toFixed(2)};background:${seg(catIdx(c))}"></i>`).join("")}</div>`
    : "";
  const key = billCats.map((c) => `<div><span class="bill-dot" style="background:${seg(catIdx(c))}"></span>${esc(c.label)}${
      c.shared && m.party > 1 ? ` <span class="cchart-split">${m.party} ways</span>` : ""}<b>${money(usd(c.committed))}</b></div>`).join("")
    + (anyOpen ? `<div><span class="bill-dot is-assumed"></span>${openCats.map((c) => esc(c.label)).join(" + ")}<b><em>${money(usd(g.open))} assumed</em></b></div>` : "");
  const split = (p) => [p.cash ? `${money(p.cash)}${p.ur ? " cash" : ""}` : "", p.ur ? `${CHASE}${Number(p.ur).toLocaleString()} points` : ""].filter(Boolean).join(" + ");
  const shareSplit = (p) => [p.cash ? money(p.cash) : "", p.ur ? CHASE + Number(Math.round(p.ur)).toLocaleString() : ""].filter(Boolean).join(" + ");
  const bill = `<div class="hub-detail-card bill-card">
    <div><div class="bill-l">the trip's bill${m.party > 1 ? ` · ${m.party} people` : ""}</div>
      <div class="bill-n">${money(usd(done))}</div>
      ${done.ur ? `<div class="bill-s">${split(done)} (${money(done.urCash || 0)}), booked</div>` : `<div class="bill-s">booked so far</div>`}</div>
    ${bar}
    ${key ? `<div class="bill-k">${key}</div>` : ""}
    ${m.party > 1 ? `<div class="bill-you"><div class="bill-l">your share</div><div class="bill-n">${money(usd(m.committed))}</div>
      ${m.committed.ur || anyOpen ? `<div class="bill-s">${m.committed.ur ? shareSplit(m.committed) : ""}${m.committed.ur && anyOpen ? " · " : ""}${anyOpen ? `${money(usd(m.projected))} once assumed lands` : ""}</div>` : ""}</div>` : ""}</div>`;

  // 2 · WHO FRONTED IT. Only people who actually put money down get a row , 
  // a list of everyone with $0.00 beside six of them is a wall, not an answer.
  const payers = led.people.filter((p) => p.paid.cash > 0 || p.paid.ur > 0);
  const standing = (p) => {
    // esc()'d by its caller, so it takes the plain form, the marked-up one
    // would render its spans and its Chase SVG as literal text.
    if (p.net.cash > TC.EPS.cash || p.net.ur > TC.EPS.ur) return `owed ${priceHtml(p.net, true)} back`;
    if (p.net.cash < -TC.EPS.cash || p.net.ur < -TC.EPS.ur) return `still owes ${priceHtml({ cash: -p.net.cash, ur: -p.net.ur }, true)}`;
    return "square";
  };
  const fronted = led.fronted.reduce((a, f) => ({ cash: a.cash + f.cash, ur: a.ur + f.ur, urCash: a.urCash + (f.urCash || 0) }), { cash: 0, ur: 0, urCash: 0 });
  const owner = payers.length
    ? payers.map((p) => `<div class="hub-kv-row ctx-row"><span>${esc(firstName(p.name))}</span><b>${priceHtml(p.paid)}</b></div>
        <div class="ctx-est">${esc(standing(p))}</div>`).join("")
    : `<div class="ctx-sub">no line has an owner yet — open a cost row and set who paid, and this fills itself in</div>`;
  const gaps =
    (led.unclaimed.rows
      ? `<div class="hub-callout-warn"><b>${priceHtml(led.unclaimed)}</b> on ${led.unclaimed.rows} line${led.unclaimed.rows === 1 ? "" : "s"} with nobody's name on ${led.unclaimed.rows === 1 ? "it" : "them"} — it counts toward the bill, it just can't be paid back</div>`
      : "") +
    (led.fronted.length
      ? `<div class="hub-callout-warn"><b>${priceHtml(fronted)}</b> fronted for someone else with no one set to pay it back — tick who owes it on ${led.fronted.length === 1 ? "that line" : "those lines"}</div>`
      : "");
  const front = `<div class="hub-detail-card"><div class="hub-detail-card-head ctx-card-head">who fronted it</div>${owner}${gaps}</div>`;

  // 3 · SETTLE UP. The fewest payments that clear the board, each one a
  // sentence you can act on without doing any arithmetic yourself.
  const settle = `<div class="hub-detail-card"><div class="hub-detail-card-head ctx-card-head">settle up</div>${
    led.transfers.length
      ? led.transfers.map((t) => `<div class="ctx-pay">
          <span class="ctx-pay-who"><b>${esc(firstName(t.fromName))}</b> <i>→</i> ${esc(firstName(t.toName))}</span>
          <span class="ctx-pay-amt">${priceHtml({ cash: t.cash, ur: t.ur })}</span></div>`).join("")
      + `<div class="ctx-sub">${led.transfers.length} payment${led.transfers.length === 1 ? "" : "s"} clears everything booked so far${
          led.people.some((p) => p.paid.ur) ? ", in dollars — nobody pays anybody back in points, so a share of an award booking is valued at the rate that row is priced on" : ""}</div>`
      : led.claimed
        ? `<div class="ctx-sub">everyone is square — every booked line is paid for by the people on it</div>`
        : `<div class="ctx-sub">nothing to settle until a booked line says who paid for it</div>`}</div>`;

  return bill + front + settle;
}

// status → funnel-total bucket
const QUEUE = "deciding";
function statusLabel(s) { return s === QUEUE ? "queue" : s; }
// status → themed color token, for the .hub-dot pip (color is never the only signal, always paired with statusLabel text)
const PIP_STATUSES = ["considering", "deciding", "scheduled", "flex", "skip"];
function pipVar(s) { return { considering: "--fg-faint", deciding: "--warn", scheduled: "--good", flex: "--accent-dim", skip: "--alert" }[s] || "--fg-faint"; }

// ── Nav memory ───────────────────────────────────────────────────────────
// Which section (and which itinerary day) you were last on, per trip. Per trip
// rather than global because "where I left off" means something different on a
// trip you're still pricing flights for than on one that's fully booked.
const NAV_KEY = (id) => `trips.nav.${id}`;
const MODES = ["dayof", "packing", "weather", "crew", "flights", "housing", "hallmark", "grocery", "activities", "food", "cost", "itinerary"];
function readNav(id) {
  try {
    const v = JSON.parse(localStorage.getItem(NAV_KEY(id)) || "null");
    if (v && MODES.indexOf(v.mode) >= 0) return v;
  } catch { /* corrupt or storage blocked, fall through to the default */ }
  return null;
}
function saveNav() {
  if (!state.trip) return;
  try { localStorage.setItem(NAV_KEY(state.trip.id), JSON.stringify({ mode: state.mode, day: state.day })); }
  catch { /* private mode / quota, memory is a nicety, never a hard failure */ }
}
// The day you land on when opening the itinerary: today if the trip is running,
// otherwise day one. Only used when nothing was remembered.
function defaultDay() {
  const days = U.tripDays();
  if (!days.length) return "cal";
  return days.indexOf(todayISO()) >= 0 ? todayISO() : days[0];
}
function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// ── Boot ─────────────────────────────────────────────────────────────────
// The trip is the URL now (/trips/<id>, injected as window.TRIP_ID). The old
// top-bar <select> and its localStorage memory are gone, the landing page at
// /trips/ is the trip picker.
function boot() {
  U.wireChrome();
  const id = Number(window.TRIP_ID);
  if (!id) { status("no trip"); renderAll(); return Promise.resolve(); }
  return selectTrip(id);
}

function selectTrip(id) {
  status("loading…");
  return API.get(`/trips/${id}`).then((trip) => {
    state.trip = trip;
    state.selId = null; state.prefs = null; state.statusFilter = null; state.search = ""; state.pinFilter = "all";
    state.food = null; state.foodErr = "";   // a different trip is a different city
    U.unmountFood();
    state.ground = null;    // a ground board you opened on one trip means nothing on the next
    const t = state.trip;
    // land where you left off, the tab is remembered per trip, the day within it too
    const nav = readNav(t.id);
    if (nav) state.mode = nav.mode;
    // A remembered hallmark on a trip that has none, or that this reader is not
    // served one for, would strand the board on a hidden tab. MODES cannot catch
    // it: "hallmark" is a real mode, just not on every trip.
    if (state.mode === "hallmark" && !U.hallmarkDef()) state.mode = "flights";
    // Same strand for packing on the mirror: the tab is Sam's and is hidden
    // from every guest (renderFunnelNav), so a remembered one must not land there.
    if (state.mode === "packing" && isGuest()) state.mode = "flights";
    const days = U.tripDays();
    state.day = nav && (nav.day === "cal" || days.indexOf(nav.day) >= 0) ? nav.day : defaultDay();
    if (state.mode === "crew") U.loadPrefs();
    if (state.mode === "food") U.loadFood();
    $("crumbName").textContent = t.name || "untitled";
    renderCalNotice(t);
    statusCounts("loaded");
    renderAll();
    U.selfCheck();
  }, (e) => { renderLoadError(`couldn't load trip — ${errMsg(e)}`, () => selectTrip(id)); });
}
// The footer counts are derived from the trip payload, so they have to be
// recomputed on every reload, not stamped once at boot, otherwise adding crew
// (or anything else) leaves the footer reporting the numbers from page load.
function statusCounts(msg) {
  const t = state.trip;
  status(msg, `${(t.activities || []).length} activities · ${(t.members || []).length} crew`);
}

// Calendar-sync notice: the daily reconcile flags trips whose Google Calendar
// event was deleted outside the dashboard (cal_status='deleted'). Surface it
// with a one-click remove rather than silently hard-deleting the row.
function renderCalNotice(t) {
  const el = $("calNotice");
  if (!el) return;
  // empty content collapses the row via `.cal-notice:empty`, don't use `hidden`
  // (display:none would drop it as a grid item and break the shell row mapping)
  if (t?.cal_status !== "deleted") { el.innerHTML = ""; return; }
  el.innerHTML =
    `<span class="cal-notice-msg"><strong>calendar event deleted</strong> — this trip's Google Calendar event was removed outside the dashboard. Remove the trip, or dismiss if you want to keep it.</span>` +
    `<button class="hub-btn hub-btn--danger" id="calRemove">remove trip</button>` +
    `<button class="hub-btn btn-dismiss" id="calDismiss">dismiss</button>`;
  $("calRemove").onclick = () => {
    U.confirmDialog("remove trip", `Remove "${t.name}" and all its trip data? This can't be undone.`, { danger: true, confirmLabel: "remove" })
      .then((ok) => {
        if (!ok) return;
        return API.del(`/trips/${t.id}`).then(
          () => { toast("trip removed"); location.href = "/trips/"; },
          (e) => { toast(`remove failed — ${errMsg(e)}`); });
      });
  };
  $("calDismiss").onclick = () => { el.innerHTML = ""; };
}
// The three hosts redraw synchronously and in this order, like the plain page; subscribers hear about it after.
function renderAll() { U.renderFunnelNav(); U.renderFocus(); U.renderContext(); store.notify(); }

/* The section-switch entrance. Fired ONLY from the .fnav click handler, never
   from renderFocus(), renderFocus also runs when you select a row, and a
   CSS-only entrance would re-stagger all thirty activity rows on every click.
   remove -> reflow -> add is what restarts the animation when you switch back
   to a section you were already on. See hub-stagger-in in components.css.

   The class is stripped when the run finishes, and that is load-bearing, not
   tidiness: if it stayed on, every .frow that renderFocus() later inserts on
   a row click would match .hub-stagger-in .hub-stagger-item and animate in, the exact
   re-render noise this hook exists to prevent. */
let paneTimer = null;
function enterPane() {
  const el = $("focusSplit");
  if (!el) return;
  clearTimeout(paneTimer);
  el.classList.remove("hub-stagger-in");
  void el.offsetWidth;
  el.classList.add("hub-stagger-in");
  // 240ms row animation + 150ms deepest stagger delay, rounded up
  paneTimer = setTimeout(() => el.classList.remove("hub-stagger-in"), 420);
}

/* The day picker lives in two places and belongs to whichever one the width
   says. On desktop it hangs in the rail between itinerary and cost, which is
   the reading order the rail was built around. Under 900px the rail is a
   drawer, so the picker moves into the pane where it stays on screen.

   insertBefore, NOT appendChild, on the way back up: appendChild would park
   the day list after the cost button and quietly reorder the desktop rail.

   Moving a node keeps its identity, so FoodView's cached els.rail still points
   at it and nothing needs remounting. Both consumers look it up by id. */
/* Open and close are two functions rather than a toggle class flip because
   opening has to evict the other full-screen panel first: the context rail
   also goes fixed at this width, and two of them stacked leaves the back
   gesture ambiguous. Picking a tab already clears the selection, so closing
   the rail here matches what the click was going to do anyway. */
function openDrawer() {
  const f = $("funnelCol");
  if (!f) return;
  const ctx = $("contextCol");
  if (ctx) ctx.classList.remove("is-open");
  f.classList.add("is-open");
  const scrim = $("funnelScrim");
  if (scrim) scrim.hidden = false;
  const t = $("navToggle");
  if (t) t.setAttribute("aria-expanded", "true");
}
function closeDrawer() {
  const f = $("funnelCol");
  if (!f) return;
  f.classList.remove("is-open");
  const scrim = $("funnelScrim");
  if (scrim) scrim.hidden = true;
  const t = $("navToggle");
  if (t) t.setAttribute("aria-expanded", "false");
}

function syncNavHost(mql) {
  const sub = $("funnelSub");
  if (!sub) return;
  const host = $("funnelSubHost");
  const cost = document.querySelector('.fnav[data-mode="cost"]');
  if (mql.matches) {
    if (host && sub.parentNode !== host) host.appendChild(sub);
  } else {
    if (cost && sub.nextElementSibling !== cost) cost.parentNode.insertBefore(sub, cost);
    // a drawer left open across a resize is a fixed panel stranded over the
    // desktop rail, which has no toggle to shut it again.
    closeDrawer();
  }
}

// ── React: error boundary, shell, overlays, mount ──────────────────────────
/* A render error shows the same words the template's load fallback does. */
class Boundary extends React.Component {
  constructor(p) { super(p); this.state = { failed: false }; }
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(e) { console.error("trips", e); }
  render() { return this.state.failed ? <div className="hub-error">page failed to load</div> : this.props.children; }
}

/* Everything after the header inside .hub-shell. Rendered once and never re-rendered (no state, no props), and
   every host the parts write into is childless, so React never reconciles over their content. The twelve nav
   buttons and the #funnelSub div come from the nav part (TripsUI.FunnelNav). The phone drawer toggle
   (#navToggle) and the crumb spans live in the header and stay in the template. */
function Shell() {
  const FunnelNav = U.FunnelNav;
  return (
    <>
      {/* ===== CALENDAR-SYNC NOTICE (shown when the selected trip's gcal event was deleted) ===== */}
      <div id="calNotice" className="cal-notice"></div>

      {/* ===== BODY (section nav on the left | the working pane) ===== */}
      <div className="body hub-t3p-body">

        {/* FUNNEL RAIL: vertical section nav. Leads the row: it is the page's primary control. */}
        <section className="col hub-t3p-col funnel hub-t3p-rail" id="funnelCol">
          <nav className="hub-nav-rail funnel-nav" id="funnelNav">
            {FunnelNav ? <FunnelNav /> : null}
          </nav>
        </section>

        {/* WORK PANE: the section header spans both columns, then the section splits into its list and
            its detail side. Each tab owns its own column ratio (.focus-split[data-split] in trips.css). */}
        <section className="col hub-t3p-col pane hub-t3p-pane" id="pane">
          {/* Phone-only host for the day picker (see syncNavHost); empty on desktop. */}
          <div className="fsub-host" id="funnelSubHost"></div>
          <div className="hub-pane-head focus-head hub-t3p-head" id="focusHead"></div>
          <div className="hub-split focus-split hub-t3p-split" id="focusSplit" data-split="flights">

            {/* LEFT: the active section's list */}
            <div className="hub-pane-col focus-col hub-t3p-list-col" id="focusCol">
              <div className="hub-pane-list focus-list hub-t3p-list" id="focusList"></div>
            </div>

            {/* RIGHT: day map on top (itinerary day view only), detail underneath. On mobile the detail
                becomes a full-viewport slide-over; the close button only shows there. */}
            <div className="side-pane hub-t3p-side" id="sidePane">
              <div className="side-map" id="dayMapHost"></div>
              <section className="hub-detail-rail hub-slide-over context" id="contextCol">
                <button type="button" className="hub-slide-over-close" id="contextMobileClose" aria-label="back to list">← back</button>
                <div className="hub-detail-rail-inner context-inner hub-t3p-context" id="context"></div>
              </section>
            </div>

          </div>
        </section>

      </div>

      {/* The drawer's way out on a phone: takes the tap on what is left of the page. */}
      <div className="funnel-scrim hub-t3p-scrim" id="funnelScrim" hidden></div>

      {/* ===== STATUS BAR ===== */}
      <StatusStrip id="status">
        <span className="status-l" id="statusMsg">ready</span>
        <span className="status-r" id="statusMeta"></span>
      </StatusStrip>
    </>
  );
}

/* The lightweight modal host, the themed confirm host and the toast: siblings of .shell in the plain page. */
function Overlays() {
  return (
    <>
      <div className="hub-modal-scrim" id="modalScrim" hidden><div className="hub-modal" id="modal"></div></div>
      <div className="hub-modal-scrim" id="confirmScrim" hidden><div className="hub-modal" id="confirmModal"></div></div>
      <div className="hub-toast toast" id="toast" hidden></div>
    </>
  );
}

/* Portals, not a root on .hub-shell: the header (drawn by topbar.jsx and holding the page's [data-slot]
   extras) must stay where it is, and a portal appends after it without clearing it. boot() runs in a layout
   effect, after the hosts exist and before first paint, which is where the plain script's boot() ran. */
function TripsApp({ shell }) {
  useLayoutEffect(() => {
    shell.setAttribute("data-react-mounted", "trips");
    boot();
  }, []);
  return (
    <TripsContext.Provider value={store}>
      {ReactDOM.createPortal(<Shell />, shell)}
      {ReactDOM.createPortal(<Overlays />, document.body)}
    </TripsContext.Provider>
  );
}

/* Called once by trips.jsx after every part has registered. The template's static copy of the body (everything
   after the header, plus the modal hosts and the toast) is only the load fallback: clear it first, or clicks
   land on the dead static markup. */
function mount() {
  const shell = document.querySelector(".hub-shell.hub-t3p");
  Array.from(shell.children).forEach((n) => { if (n.tagName !== "HEADER") n.remove(); });
  ["modalScrim", "confirmScrim", "toast"].forEach((id) => { const n = $(id); if (n) n.remove(); });
  const host = document.createElement("div");
  host.id = "tripsHost";
  host.hidden = true;
  document.body.appendChild(host);
  ReactDOM.flushSync(() => { ReactDOM.createRoot(host).render(<Boundary><TripsApp shell={shell} /></Boundary>); });
}

/* Four trips.js top-level `let`s are assigned in one range and read in another, which a copied binding cannot
   do, so they live on one shared object instead: dayMap and dayMapKey (day map part, reset by renderFocus), foodMounted
   (context part, read by the nav and board parts), closeConfirmActive (editors part, read by the Escape handler).
   Read and write them as TripsUI.mut.<name>. */
const mut = { dayMap: null, dayMapKey: null, foodMounted: null, closeConfirmActive: null };

/* Forwarders for functions another part owns: const { tripDays, renderFocus } = TripsUI.fwd("tripDays", "renderFocus").
   Each call looks the name up on TripsUI at call time, so load order between parts does not matter. */
function fwd(...names) {
  const o = {};
  names.forEach((n) => { o[n] = (...args) => U[n].apply(null, args); });
  return o;
}

Object.assign(U, {
  mut, fwd, api: API, req, state, store, TripsContext, useTrips, T, FC, TC, CC,
  $, esc, setHTML, toast, status, errMsg, renderLoadError,
  money, num1, points, pointsCell, parseTags, haversine, isGuest, viewerKey, memberKey, isViewer,
  statusLabel, pipVar, QUEUE, PIP_STATUSES, firstName, todayISO,
  chosenStay, lastStay, housingAnchor, distFromStay,
  isCommitted, isDead, isOpen, rowCost, sumCost, myFlights, busOf, isCar, myFares, supersededExpense,
  isSettled, carPickup, carDropoff, tripMoney, tripLedger, priceHtml, CHASE, costChart, costContext,
  FIRM, FULL_MODES, MODES, NAV_KEY,
  readNav, saveNav, defaultDay, boot, selectTrip, statusCounts, renderCalNotice, renderAll, enterPane,
  openDrawer, closeDrawer, syncNavHost,
  Boundary, Shell, Overlays, TripsApp, mount,
});
})();
