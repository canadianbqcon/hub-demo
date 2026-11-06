/* hub · trips page, nav part (2026-10-13): React port of trips.js lines 612-1532 (chrome wiring, funnel nav and
   sub-nav, focus dispatch, hallmark, day-of helpers, getting-there terminals and ride plan). Plain string builders
   kept as plain functions; the one React piece is FunnelNav. See trips-core.jsx for the interface. */
(() => {
const U = window.TripsUI;
const { esc, setHTML, state, $, money, points, errMsg, isGuest, viewerKey, memberKey, isViewer, isDead,
  isCommitted, todayISO, lastStay, haversine, FULL_MODES, defaultDay, saveNav, renderAll, enterPane, openDrawer,
  closeDrawer, syncNavHost, CC } = U;
const API = U.api;
const { listDayOf, listCost, listActivities, listItinerary, itineraryModel, dayLabel, dayShort, flightLegs,
  listFlights, airportPt, airportLead, clockOf, dur, absOf, baseOf, readerMember, legKey, crewFlights,
  groupIsViewer, meMember, dayLong, listHousing, daysAway, listCrew, loadFood, unmountFood, listFood,
  listGrocery, listWeather, listPacking, renderContext, tripDays } = U.fwd(
  "listDayOf", "listCost", "listActivities", "listItinerary", "itineraryModel", "dayLabel", "dayShort",
  "flightLegs", "listFlights", "airportPt", "airportLead", "clockOf", "dur", "absOf", "baseOf", "readerMember",
  "legKey", "crewFlights", "groupIsViewer", "meMember", "dayLong", "listHousing", "daysAway", "listCrew",
  "loadFood", "unmountFood", "listFood", "listGrocery", "listWeather", "listPacking", "renderContext",
  "tripDays");

  // ── Chrome: section nav, surface toggle ─────────────────────────────────────
  function wireChrome() {
    document.querySelectorAll(".fnav").forEach((b) => {
      b.onclick = () => {
        state.mode = b.dataset.mode; state.selId = null; state.search = ""; state.statusFilter = null;
        if (state.mode === "itinerary" && !state.day) state.day = defaultDay();
        if (state.mode === "crew" && state.trip && !state.prefs) loadPrefs();
        if (state.mode === "food" && state.trip && !state.food) loadFood();
        saveNav();
        renderAll();
        enterPane();
        closeDrawer();
      };
    });
    // mobile slide-over close/back button (see trips.css @900px + renderContext())
    const mc = $("contextMobileClose");
    if (mc) mc.onclick = () => {
      if (state.mode === "food" && U.mut.foodMounted) return window.FoodView.close();
      state.selId = null; renderFocus(); renderContext();
    };
    // surface (light/dark) toggle is owned entirely by theme-switch.js now
    // (build + click + persist to "hub.surface"); nothing to wire per-page.
    // no splitter to wire: the detail side is a per-tab share of the pane now
    // (.focus-split[data-split] in trips.css), not a draggable fixed-width rail.

    /* Called outright BEFORE the listener is bound, and that order is the whole
       point: a MediaQueryList fires `change` when the viewport crosses the
       threshold and never on first paint. Binding the listener alone reads as
       correct and strands the day picker inside the closed drawer for every
       phone that opens the board directly, which is most of them. */
    const navMql = window.matchMedia("(max-width: 900px)");
    syncNavHost(navMql);
    navMql.addEventListener("change", syncNavHost);

    const nt = $("navToggle");
    if (nt) nt.onclick = () => {
      const f = $("funnelCol");
      (f?.classList.contains("is-open") ? closeDrawer : openDrawer)();
    };
    const scrim = $("funnelScrim");
    if (scrim) scrim.onclick = closeDrawer;
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeDrawer();
    });
  }

  // state.prefs stays null until this answers, and the crew cards read that null
  // as "still loading" — so a failure has to be recorded, or every card sits on
  // a loading marker forever with nothing to say why.
  function loadPrefs() {
    if (!state.trip) return Promise.resolve();
    state.prefsErr = "";
    return API.get(`/trips/${state.trip.id}/preferences`).then((p) => {
      state.prefs = p;
      // Before any render: the cards and the rail both draw off it, and a card
      // painted without it silently loses every bar rather than failing.
      CC.setScales(state.prefs.scales);
      CC.setLabels(state.prefs.labels);
    }).catch((e) => { state.prefsErr = errMsg(e); }).then(() => {
      renderContext(); renderFocus();
    });
  }

  // ── FUNNEL NAV (vertical section switcher) ───────────────────────────────────
  // The per-tab counts were removed 2026-08-26: each one measured something
  // different (rows on a board, cost lines, scheduled-only activities), so the
  // column of numbers did not compare and read as a scoreboard that was not one.
  function renderFunnelNav() {
    // The hallmark button is the one entry that is not the same tab on every trip:
    // it ships blank and hidden, and the trip's own module names it. No module
    // means either the trip has no hallmark or this reader is not allowed one —
    // the server decides which, and from here the two are indistinguishable on
    // purpose (see hallmarkDef).
    const hb = document.querySelector('.fnav[data-mode="hallmark"]');
    if (hb) {
      const h = hallmarkDef();
      hb.hidden = !h;
      const lab = hb.querySelector("[data-hlabel]");
      if (lab) lab.textContent = h ? (h.label || "hallmark") : "";
    }
    // Packing is the other conditional tab: Sam's own lists, never a guest's.
    const pb = document.querySelector('.fnav[data-mode="packing"]');
    if (pb) pb.hidden = isGuest();
    document.querySelectorAll(".fnav").forEach((b) => {
      b.classList.toggle("active", b.dataset.mode === state.mode);
    });
    /* Read off the button, never off state.mode: the two do not agree. flights
       is labelled transport, dayof is labelled liftoff, and the hallmark's label
       is whatever the trip's own module called it, which only exists in the DOM
       by this point. Taking the rendered text is correct for all three by
       construction. */
    const cs = $("crumbSection");
    const on = document.querySelector(".fnav.active .fnav-l");
    if (cs) cs.textContent = on ? on.textContent.trim() : "";
    renderFunnelSub();
  }

  // The itinerary expands in place: a row per trip day, then the whole-trip
  // calendar last. A day is the unit you actually plan in — the calendar is the
  // step back you take once, not the thing you live in.
  function renderFunnelSub() {
    const el = $("funnelSub");
    if (!el) return;
    // On the food tab this slot holds the research view's own rail, drawn by
    // FoodView. Clearing it here would wipe the filters mid-session.
    if (state.mode === "food" && U.mut.foodMounted) return;
    const days = state.mode === "itinerary" ? tripDays() : [];
    if (!days.length) {
      el.hidden = true; setHTML(el, "");
      return;
    }
    el.hidden = false;
    const perDay = dayCounts();
    const rows = days.map((d, i) => {
      const on = state.day === d ? " active" : "";
      const n = perDay[d] || 0;
      return `<button class="fsub-b hub-nav-subitem${on}${d === todayISO() ? " is-today" : ""}" data-day="${d}">
        <span class="fsub-d">day ${i + 1}</span>
        <span class="fsub-n">${esc(dayLabel(d))}</span>
        <span class="fsub-c">${n || ""}</span></button>`;
    }).join("");
    setHTML(el, `${rows}<button class="fsub-b hub-nav-subitem fsub-cal${state.day === "cal" ? " active" : ""}" data-day="cal">
      <span class="fsub-d">calendar</span><span class="fsub-n">all ${days.length} days</span><span class="fsub-c"></span></button>`);
    el.querySelectorAll(".fsub-b").forEach((b) => {
      b.onclick = () => {
        state.day = b.dataset.day; state.selId = null;
        saveNav();
        renderFunnelSub(); renderFocus(); renderContext();
      };
    });
  }

  // How many things land on each day — the same set the itinerary draws, so the
  // sub-nav count and the day view can never disagree.
  function dayCounts() {
    const out = {};
    if (!state.trip) return out;
    itineraryModel(tripDays()).forEach((d) => { (out[d.day] = d.blocks.length + d.tray.length); });
    return out;
  }

  // ── FOCUS: per-section list (was the funnel tab body) ────────────────────────
  function renderFocus() {
    const head = $("focusHead"), list = $("focusList");
    // which column ratio this tab gets. The day view is its own split — the map
    // lives in the right column there, so it can't share the calendar's shape.
    const onDay = state.mode === "itinerary" && state.day !== "cal" && tripDays().indexOf(state.day) >= 0;
    $("focusSplit").dataset.split = onDay ? "day" : state.mode;
    // the origin's full-width state class, toggled off the value just set above
    // (not state.mode) so it reproduces the five data-split rules it replaces
    // exactly, including the day view's "day" split.
    $("focusSplit").classList.toggle("is-full", FULL_MODES.has($("focusSplit").dataset.split));
    // the active tab on the body so CSS can react to it — on a phone the pinned
    // money block sits directly above the cost tab's own figure block and prints
    // the same three numbers twice. `data-tab`, not `data-mode`: the nav buttons
    // own that attribute and a body carrying it turns up in every
    // querySelectorAll("[data-mode]") as a seventh, invisible tab.
    document.body.dataset.tab = state.mode;
    // the map slot belongs to the three views that are asking a "where is this"
    // question — the day, the housing board, the activities board. :empty collapses
    // it everywhere else. Left alone in those three: each decides whether it needs
    // rebuilding, so clicking a row doesn't reset the map's pan and zoom.
    const mapped = onDay || state.mode === "housing" || state.mode === "activities"
      || state.mode === "food";
    if (!mapped) { setHTML($("dayMapHost"), ""); U.mut.dayMapKey = null; }
    // Leaving food takes the renderer down with it: it holds a leaflet map and a rail
    // in the funnel's sub-nav, and both would outlive the tab that owns them.
    if (state.mode !== "food") unmountFood();
    if (!state.trip) { setHTML(head, ""); setHTML(list, `<div class="hub-empty-state focus-empty">no trip selected</div>`); return; }
    ({ activities: listActivities, itinerary: listItinerary, flights: listFlights, housing: listHousing, crew: listCrew, cost: listCost, food: listFood, grocery: listGrocery, dayof: listDayOf, hallmark: listHallmark, packing: listPacking, weather: listWeather }[state.mode] || listFlights)(head, list);
    // the stay panel nests the same head-and-body pattern one level down, so it
    // gets the same pass — its six sections are six reads, not one long panel.
    [list].concat([...list.querySelectorAll(".stay")]).forEach(groupIntoCards);
    stampColumnLabels(list);
  }

  /* Every read on the board is a card. Most of them had no element to draw one
     around: the renderers emit a section head and its body as SIBLINGS — a head,
     then a table, then the note under the table — so the board read as one column
     of hairline-divided strips while the crew grid beside it was made of real
     cards the whole time.

     Wrapped here rather than in the eleven renderers that emit .lgroup-head, for
     the same reason stampColumnLabels below stamps rather than edits: one pass over
     the rendered DOM covers every board, and the next one written gets it without
     knowing this exists. A run starts at a section head and ends at the next one,
     so a note that trails its table stays inside the card it belongs to. Anything
     already boxed by its own renderer — the crew grid, the packing lists, the
     activity groups, the stay panel — has no head at this level and is left alone;
     CSS cards those directly. */
  function groupIntoCards(root) {
    let card = null;
    [...root.children].forEach((el) => {
      // Section heads only. An aisle label (.gsec) is a separator INSIDE a list,
      // not a head — and grocery is the only board that emits one at this level,
      // so listing it here gave that board a card per aisle and left its real head
      // alone in an empty one. Packing's aisle labels sit inside .pksec and never
      // reached this pass, which is why only grocery ever showed it.
      if (el.matches(".lgroup-head")) {
        card = document.createElement("section");
        card.className = "lcard hub-t3p-card hub-plate-card";
        root.insertBefore(card, el);
      }
      if (card) card.appendChild(el);
    });
  }

  /* Every board's cells carry their own column name, so a phone can stack the row
     and still say what each line is.

     A table is a grid whose labels live in one row at the top. That is a deal a
     390px screen cannot hold up its end of: the additional-transport board's eight
     columns came out at 34px each and broke every cell mid-word — "trai n", "Denv
     er Unio n Stati on", a header reading "CO ST". Nothing clipped and nothing
     overflowed, so both existing probes called it clean; it was simply unreadable.
     The phone rule in trips.css stacks each row into label/value lines instead, and
     this is where the labels come from.

     Stamped here rather than written into each renderer because there are four of
     them (the generic board, cost, baggage, expenses) and two build their cells in
     per-branch literals. One pass over the rendered DOM covers all four, and the
     next board written gets it without knowing this exists. */
  function stampColumnLabels(root) {
    root.querySelectorAll("table.ltable").forEach((tb) => {
      const heads = [...tb.querySelectorAll("thead th")].map((th) => th.textContent.replace(/[↕↑↓]/g, "").trim());
      if (!heads.length) return;
      tb.querySelectorAll("tbody tr").forEach((tr) => {
        [...tr.children].forEach((td, i) => { if (heads[i]) td.setAttribute("data-l", heads[i]); });
      });
    });
  }

  /* ── HALLMARK: the one thing the trip is actually for ───────────────────────
     Every other tab is a stage of getting there. This one is the reason — the
     birthday, the festival, the wedding — and so it is the only tab whose CONTENT
     is per-trip rather than per-shape. Each trip that has one ships a module:

       trips/frontend/hallmark/<slug>.js   → window.TripHallmark[<trip id>] = {…}
       trips/frontend/hallmark/<slug>.css  → its own styles, prefixed .hm-

     Those files are served from /trips/<id>/hallmark.js|css, a GATED route in
     api.py — not from /trips/static/, which any guest can read by guessing a
     filename. That distinction is the whole hiding mechanism: Denver's page is
     kept from one member of its own crew, and a page hidden only by a CSS rule is
     a surprise party announced in view-source. When the server withholds the
     module the tab does not exist here at all.

     The module contract, all of it:

       label   string   what the nav button says on this trip ("birthday")
       title   string   the head line
       sub     string   optional second line under the title
       hidden  string[] member keys this page is kept from — DISPLAY ONLY. The
                        server enforces it; this list is what draws the notice
                        telling everyone else who cannot see the tab.
       render(ctx) -> html   the whole page, one string
       wire(root, ctx)       optional, after mount: listeners, maps, ticks

     ctx carries the board's own helpers so a module never re-implements them:
       trip, crew, esc, money, viewer, isGuest, tick/ticked (localStorage, the
       same per-trip store the day-of checklist uses), and reload(). */
  function hallmarkDef() {
    const t = state.trip;
    return (t && window.TripHallmark?.[t.id]) || null;
  }

  // Per-trip, per-reader tick store, shared by every checklist a hallmark page
  // draws. Same shape and same reasoning as DAYOF_KEY: scoped tight enough that
  // ticking one list never silently ticks another.
  const HM_KEY = (t) => `trips.hallmark.${t.id}`;
  function hmTicks(t) {
    try {
      const v = JSON.parse(localStorage.getItem(HM_KEY(t)) || "{}") || {};
      // one-time carry-over (2026-09-25): lostlands kept its meeting point under its own key
      const old = localStorage.getItem(`${HM_KEY(t)}.meet`);
      if (old !== null) {
        if (old && !v.meet) { v.meet = old; localStorage.setItem(HM_KEY(t), JSON.stringify(v)); }
        localStorage.removeItem(`${HM_KEY(t)}.meet`);
      }
      return v;
    } catch { return {}; }
  }
  function hmTick(t, k, on) {
    const v = hmTicks(t); if (on) v[k] = on === true ? 1 : on; else delete v[k];  // a string value rides along (free-text notes)
    try { localStorage.setItem(HM_KEY(t), JSON.stringify(v)); } catch { /* private mode */ }
  }

  function hallmarkCtx() {
    const t = state.trip;
    return {
      trip: t,
      crew: (t?.members) || [],
      esc, money, points, dayLong, dayShort, daysAway, todayISO,
      viewer: viewerKey(),
      isGuest: isGuest(),
      ticks: hmTicks(t),
      ticked: (k) => !!hmTicks(t)[k],
      tick: (k, on) => hmTick(t, k, on),
      api: API,
      reload: () => { renderFocus(); },
    };
  }

  // Who is being kept out, named, for everyone who is not them. A shared board
  // where one tab is invisible to one person is a fact the other six have to
  // know — otherwise somebody links Aaron straight to his own surprise party.
  function hallmarkNotice(h, ctx) {
    const keys = h.hidden || [];
    if (!keys.length) return "";
    const names = keys.map((k) => {
      const m = ctx.crew.find((x) => memberKey(x) === k);
      return m ? m.name : k.replace(/^name:/, "").replace(/-/g, " ");
    });
    return `<div class="hub-notice-warn" role="note">
      <span class="hub-notice-warn-t">kept from ${esc(names.join(" and "))}</span>
      <span class="hub-notice-warn-s">This tab is not on the board ${esc(names.join(" or "))}
        sees. It is withheld by the server, not hidden by a setting, so there is
        nothing here for them to stumble onto. Keep it that way: don't paste
        anything off this page into a chat they are in.</span></div>`;
  }

  function listHallmark(head, list) {
    const h = hallmarkDef();
    if (!h) {
      setHTML(head, "");
      setHTML(list, `<div class="hub-empty-state focus-empty">this trip has no hallmark page</div>`);
      return;
    }
    const ctx = hallmarkCtx();
    setHTML(head, `<div class="hub-figure">
      <div class="hub-figure-fig">
        <span class="hub-figure-n">${esc(h.title || h.label || "")}</span>
        <span class="hub-figure-l">${esc(h.sub || "")}</span>
      </div>
    </div>`);
    let body = "";
    try { body = h.render(ctx) || ""; }
    catch (e) { body = `<div class="hub-empty-state empty">the ${esc(h.label || "hallmark")} page failed to draw — ${esc(String(e?.message || e))}</div>`; }
    setHTML(list, `<div class="hm">${hallmarkNotice(h, ctx)}${body}</div>`);
    // Ticks are wired here rather than in every module: any [data-hmtick] on the
    // page persists, so a module writes a checkbox and gets memory for free.
    list.querySelectorAll("[data-hmtick]").forEach((b) => {
      b.checked = ctx.ticked(b.dataset.hmtick);
      b.onchange = () => { ctx.tick(b.dataset.hmtick, b.checked); hmSyncCounts(list, ctx); };
    });
    hmSyncCounts(list, ctx);
    if (typeof h.wire === "function") {
      try { h.wire(list, ctx); } catch (e) { console.error("hallmark wire", e); }
    }
  }

  // "N of M" for any group of ticks sharing a data-hmgroup, stamped in place so a
  // tick never re-renders the input under the pointer (the day-of tab learned
  // that one the hard way).
  function hmSyncCounts(root, _ctx) {
    root.querySelectorAll("[data-hmcount]").forEach((el) => {
      const g = el.dataset.hmcount;
      const boxes = root.querySelectorAll(`[data-hmtick][data-hmgroup="${g}"]`);
      let n = 0; boxes.forEach((b) => { if (b.checked) n++; });
      el.textContent = boxes.length ? `${n} of ${boxes.length}` : "";
      el.classList.toggle("docount-all", boxes.length > 0 && n === boxes.length);
    });
  }

  /* ── DAY OF: the tab you open on the morning it actually starts ──────────────
     Every other section answers a question you are still deciding. This one
     answers a question you are already inside: it is 4am, you are holding a bag,
     what time do you have to be where. So it says, in that order — how long
     until it starts, the flight you are catching, what has to be done before you
     leave, the clock you are running against, and what can take you to the
     airport.

     It leads the rail because on the one day it matters it outranks every
     decision underneath it, and reads as the countdown the rest of the time. */

  /* The airport-side clock, counted back from take-off. AIRPORT_LEAD is the same
     140 minutes the departure read on the transport tab runs on — one knob, so
     the two surfaces cannot name different times to be at the same terminal.

     What is deliberately NOT here is "leave the house at". That depends on where
     you are leaving from, and the trip records nowhere for the outbound: seven
     people leave from seven different addresses on the same morning. An invented
     drive time reads exactly like a measured one, so this tab states the time you
     have to be AT the door and hands you a ride link that measures the journey
     itself.

     The lead is per-leg (airportLead) rather than one constant: an international
     departure wants the carriers' three hours, not the domestic two. The other
     three constants stay flat — security, boarding and door close are the same
     clock whichever way the plane is pointed. */
  const SECURITY_BY = 75, BOARDING_BY = 35, DOORS_BY = 15;
  /* Time in the security line, PreCheck lane and standard lane. TSA's own national
     figures, not this airport's live line: 99% of PreCheck travellers wait under
     10 minutes (TSA PreCheck release, Jan 2026) and TSA holds standard lanes to
     under 30. No free live feed exists (MyTSA returns nothing, the others are
     keyed), and this page reaches guests through the public mirror with no fetch.
     ponytail: national ceilings; swap in a per-airport feed if one ever opens. */
  const LINE_PRE = 10, LINE_STD = 30;

  // absOf() gives epoch-minutes; this turns one back into something readable
  // without round-tripping through a stamp string nobody typed.
  const absDate = (abs) => new Date(Math.floor(abs / 1440) * 86400000).toISOString().slice(0, 10);

  // The reader's own legs, kept as GROUPS rather than the {leg,row} pairs
  // readerLegs() hands back — flightLegBlock draws a group, not a row. Same two
  // branches, so the tab and the transport rail cannot disagree about whose
  // ticket is whose.
  function readerLegGroups(t) {
    if (viewerKey() && !isViewer(meMember(t))) {
      const g = crewFlights(t).filter(groupIsViewer)[0];
      return g ? g.legs : [];
    }
    return flightLegs(t).filter((g) => g.live);
  }

  // The flight this tab is about: the next one you still have to catch. Once
  // every leg is behind you it is the last one — a finished trip should read as
  // finished rather than as an empty tab.
  function dayOfLeg(t) {
    const legs = readerLegGroups(t)
      .map((g) => ({ g: g, row: g.rows.filter(isCommitted)[0] || g.rows[0] }))
      .filter((x) => x.row && absOf(x.row.departure_time) != null)
      .sort((a, b) => absOf(a.row.departure_time) - absOf(b.row.departure_time));
    if (!legs.length) return null;
    return legs.filter((x) => daysAway(x.row.departure_time) >= 0)[0] || legs[legs.length - 1];
  }

  // The one place that decides which leg the day-of tab is about. The body and
  // the rail are two renderings of this answer, never two answers — and it is an
  // accessor rather than a value threaded through, because renderContext() runs
  // BEFORE renderFocus() on the tab-switch path (trips.js, switchMode) so
  // anything the body stashed would be read stale.
  function dayOfSel() { return dayOfLeg(state.trip); }

  // Which way the trip is pointing for a reader with no leg of their own: out,
  // until the last outbound landing is behind us, home after it. The crew card
  // takes a direction rather than a leg precisely so a guest whose ticket is not
  // on the board yet still gets the crew picture — they are the person who most
  // needs it.
  function defaultDir(t) {
    const out = (t?.flights || []).filter((f) => !isDead(f))
      .filter((f) => (f.direction || "outbound") !== "return")
      .map((f) => daysAway(f.arrival_time)).filter((d) => d != null);
    return out.length && Math.max.apply(null, out) < 0 ? "return" : "outbound";
  }

  // The checkpoint read, in the same card the arrival and departure reads use —
  // one timeline component, so a step means the same thing wherever you meet it.
  /* Flight day's actual first question, and the only one on this tab the page
     cannot answer from the trip: is it on time. One Google query rather than eight
     carrier deep links — Google resolves a status card from the flight number for
     any carrier, and a per-airline URL is eight strings to keep true instead of
     one. No fetch, for the same reason driveMin() does not fetch: this page is
     served to guests through the public mirror. */
  function statusLink(f) {
    // A chained booking carries its whole label in flight_num ("UA1618 + UA204 via
    // IAD"), and a search for that string finds nothing. The flight whose status
    // you need at 7am is the first one, so cut at the join.
    const num = String(f.flight_num || "").split(/\s*(?:\+|,|\/|\bvia\b)/i)[0].trim();
    const q = [f.airline, num].filter((x) => String(x || "").trim()).join(" ").trim();
    if (!q) return null;
    return { l: "is it on time ↗", u: `https://www.google.com/search?q=${encodeURIComponent(`${q} flight status`)}` };
  }

  // biome-ignore lint/correctness/noUnusedFunctionParameters: t is unused, but test_trips_tab_wiring.py lifts this function by its exact signature text — renaming the param breaks the test's regex, not the code.
  function checkpointRead(t, sel) {
    const f = sel.row, dep = absOf(f.departure_time), base = baseOf(f.departure_time);
    const cl = (m) => m - base;
    const port = (f.from_airport || "").trim(), to = (f.to_airport || "").trim();
    // Which building, not just which airport — LGA's B and C are a shuttle ride
    // apart and the wrong one at 4:10am is the whole margin. Printed only when the
    // row carries it: a guessed terminal is worse than none.
    // Normalised to one spelling, because the field is hand-typed and "B", "T4"
    // and "Terminal 4" are all things people write. Strip whatever prefix is on it
    // and put one back, so the step never reads "At LGA · TB".
    const term = (x) => {
      const v = bareTerm(x);
      if (!v) return "";
      return /^concourse\b/i.test(v) ? ` · ${v}` : ` · Terminal ${v}`;
    };
    // The departure side falls back to the carrier lookup (TERMINALS) when the row
    // is blank, which it is on every Southwest booking on this board. The ride
    // links resolve the same way through terminalOf, so the step you read and the
    // curb the app drives to are one answer, never two.
    const lead = terminalOf(f);
    const tf = term(f.terminal_from) || (lead ? ` · ${lead.label}` : "");
    const tt = term(f.terminal_to);
    const door = dep - airportLead(f);
    // Before 5am at the door is not a preference, it is an alarm. It rides as the
    // first STEP rather than as a pill in the head, because that is what it is:
    // the earliest thing that happens on the timeline, and the head at this card's
    // 300px floor could not carry a title, a link and a pill without wrapping the
    // title onto two lines. Ninety minutes is a rule of thumb, so the row says so
    // — an unhedged "Alarm 02:40" reads like a measured figure.
    const early = ((door % 1440) + 1440) % 1440 < 5 * 60;
    // Only a US departure has a TSA line; San Salvador's queue is not TSA's figure.
    const fromPt = airportPt(port);
    const lineNote = fromPt && U.inUS(fromPt)
      ? `line under ${LINE_PRE} min PreCheck, ${LINE_STD} min standard` : "";
    const steps = [
      { c: cl(door), w: `At ${port || "the airport"}${tf} · bag drop`, hit: 1 },
      { c: cl(dep - SECURITY_BY), w: lineNote ? `Through security · ${lineNote}` : "Through security" },
      { c: cl(dep - BOARDING_BY), w: "At the gate — boarding starts" },
      { c: cl(dep - DOORS_BY), w: "Doors close" },
      { c: cl(dep), w: `Take off${to ? ` · ${port || "?"} → ${to}` : ""}` },
    ];
    const land = absOf(f.arrival_time);
    if (land != null) steps.push({ c: cl(land), w: `Wheels down${to ? ` · ${to}${tt}` : ""}` });
    if (early) steps.unshift({ c: cl(door - 90), w: "Alarm, at the latest" });
    return {
      // `who` and the countdown pill both went. The page headline prints the
      // countdown in 48px and the boarding pass directly above prints the date, the
      // carrier and the clock; three copies of one number is not emphasis. What
      // takes the freed space is the one flight-day answer nothing on this page can
      // compute for itself.
      title: "Your checkpoints", who: "", link: statusLink(f), pill: "",
      steps: steps, tone: early ? "warn" : "good",
      note: `Be at ${port || "the airport"}${tf} by ${clockOf(cl(door))} — ${dur(airportLead(f))} before `
        + `take-off, bag drop included.${lineNote ? ` Bag drop to through security leaves `
        + `${dur(airportLead(f) - SECURITY_BY)}; the line itself runs under ${LINE_PRE} min in PreCheck and `
        + `under ${LINE_STD} in standard on TSA's national figures, so that window holds either lane.` : ""} `
        + `The rides below measure the leg from wherever you are starting.`,
    };
  }

  /* ── GETTING THERE ──────────────────────────────────────────────────────────
     The first card on the morning it matters, and the only one that is a drawing
     rather than a read: how you physically get from where you are standing to the
     right door of the right building, with the app already holding the answer
     before you open it.

     Four things it fixes that four link rows could not:

     1. THE TERMINAL. A rideshare link that names only "LGA" drops you at whichever
        curb the app picks, and LGA's B and C are a shuttle ride apart at 4am. The
        row's own terminal_from is the answer when somebody typed it — nobody ever
        does — so TERMINALS resolves it from the carrier instead.
     2. THE PICTURE. Everyone can read a map and nobody can read four URLs. The map
        is the card; the links are what it is a picture OF.
     3. THE CHAIN. Seven people on one flight take four cars to the same terminal
        because no link can carry more than one pickup. Uber's can — drop[0..n] —
        so the chain collects furthest-first and arrives as one fare.
     4. THE REAL ROAD. The line follows the streets and the leave-by clock is the
        drive OSRM measured over them, not a straight line times a road factor.
        This card spent an afternoon drawing a dashed line on a note claiming the
        mirror had no directions host — which had stopped being true: OSRM is in
        the mirror's own connect-src and the day map next door had been measuring
        road routes through it the whole time. Both maps share one call and one
        cache now. The dashed line survives as what it should always have been:
        the fallback when nothing can route the leg, which is every transit leg
        (OSRM has no transit graph) and any leg the router declines.

     What is NOT here, verified 2026-08-28 rather than assumed:
     - A scheduled pickup time in the link. Neither Uber's universal link
       (developer.uber.com/docs/deep-linking) nor Lyft's carries one — Uber Reserve
       is reachable only inside the app. The card states the leave-by time it works
       out instead, which is the part it can actually be right about.
     - A live fare. Uber's and Lyft's price endpoints are partner-gated. The only
       honest number is the estimate already recorded on the transportation board,
       so that is the only one printed, labelled as the board's own. */

  /* Which building at which airport, by carrier.

     Only the three New York departure airports are in here, and that is the whole
     table on purpose: they are the only airports on this board where the question
     has more than one answer. DEN, AUS, CMH, IAD and SAL are one terminal each,
     and printing "Terminal 1" at an airport with one terminal is noise.

     Coordinates are OSM's own aeroway=terminal polygon centres (read 2026-08-28
     via Overpass), not estimates. A wrong curb is worse than no curb, so a carrier
     this table does not name resolves to NOTHING and every link falls back to the
     airport — the same rule the checkpoint card already runs on.

     ponytail: a literal table, not an API. Terminal assignments change once every
       few years and there is no free feed for them; when one moves, the fix is one
       line here.

     `uber` is the SAME building said in Uber's words, and it exists because Uber
     does not read ours. Handed a dropoff it IGNORES the address we send and
     re-resolves the raw coordinate against its own place index, snapping to
     whatever it has nearest. That is how a Terminal B drop came back as "Porter
     Airlines" for every carrier at LGA, and how six of these ten centres resolved
     to a whiskey bar, a deli, a cafe and a terminal that closed years ago (swept
     headlessly against real links, 2026-08-31). A place `id` is the one thing Uber
     will not second-guess, so each carrier carries the id of its OWN airline
     place: more precise than the terminal, and it is the door printed on the
     ticket. All 22 were round-tripped through a real link and echoed back exactly.

     The fourth element is the terminal the id belongs to, and it is checked
     against the terminal this card actually resolved. A link that quietly
     disagrees with the terminal printed beside it is the exact failure this card
     exists to prevent, so a mismatch drops the id and falls back to the
     coordinate. Two entries are deliberately absent for that reason: Uber files
     Delta at JFK under Terminal 1 where this table says 4, and Alaska at EWR
     under B where this table says A. Whichever is right, the card and the link
     agree or the id is not used. */
  const TERMINALS = {
    LGA: { name: "LaGuardia Airport",
      at: { A: [40.77354, -73.88464], B: [40.77291, -73.87163], C: [40.77015, -73.86214] },
      by: { southwest: "B", united: "B", american: "B", jetblue: "B", frontier: "B",
            "air canada": "B", porter: "B", delta: "C", spirit: "A" },
      uber: {
        southwest: ["Southwest Airlines", "Terminal B, LaGuardia Airport (LGA), Queens, NY", "e4dcffa5-91e5-3ab3-9a57-890c0aa7896e", "B"],
        united: ["United", "Terminal B, LaGuardia Airport (LGA), Queens, NY", "a3705cd4-1ca6-402b-83ce-58ee2c7e3fcf", "B"],
        american: ["American Airlines", "Terminal B, LaGuardia Airport (LGA), Queens, NY", "184c53c0-ca69-35e8-8923-b76010bddeff", "B"],
        jetblue: ["JetBlue", "Terminal B, LaGuardia Airport (LGA), Queens, NY", "bb651f3f-41b8-427e-b656-5bd201627b9c", "B"],
        frontier: ["Frontier", "Terminal B, LaGuardia Airport (LGA), Queens, NY", "b0a65982-6731-4fc4-9fa6-7897083343bd", "B"],
        "air canada": ["Air Canada", "Terminal B, LaGuardia Airport (LGA), Queens, NY", "b7d8d236-6939-4ad1-9635-5c9383cd8462", "B"],
        porter: ["Porter Airlines", "Terminal B, LaGuardia Airport (LGA), Queens, NY", "a361636c-b298-45a7-8ff7-fab60ea49f32", "B"],
        delta: ["Delta", "Terminal C, LaGuardia Airport (LGA), Flushing, NY", "e33caba7-272a-4dbe-8a69-5ceec5912955", "C"],
        spirit: ["Spirit", "Terminal A, LaGuardia Airport (LGA), Queens, NY", "f325bde6-8b02-486a-a81c-a86f5bc6503e", "A"] } },
    EWR: { name: "Newark Liberty International Airport",
      at: { A: [40.68397, -74.18553], B: [40.69002, -74.17598], C: [40.69632, -74.17659] },
      by: { united: "C", delta: "A", american: "A", jetblue: "A", southwest: "A",
            alaska: "A", spirit: "B" },
      uber: {
        united: ["United", "Terminal C, Newark Liberty International Airport (EWR), Newark, NJ", "4ea7a787-faf6-cd64-da0a-d903318a496c", "C"],
        delta: ["Delta", "Terminal A, Newark Liberty International Airport (EWR), Newark, NJ", "d06afbe3-d679-f60c-5213-ee06e0d2eba2", "A"],
        american: ["American Airlines", "Terminal A, Newark Liberty International Airport (EWR), Newark, NJ", "e66b3a1c-a42f-3134-3add-977777ad4ad5", "A"],
        jetblue: ["JetBlue", "Terminal A, Newark Liberty International Airport (EWR), Elizabeth, NJ", "247930b0-ec90-66a5-0316-f9b0ddb43f33", "A"],
        southwest: ["Southwest Airlines", "Terminal A, Newark Liberty International Airport (EWR), Newark, NJ", "2dd23ee3-95aa-d630-1332-08c0b1d67890", "A"],
        // alaska: Uber files it at EWR Terminal B, this table says A. No id until
        // one of the two is settled — a link that contradicts the card is the bug.
        spirit: ["Spirit", "Terminal B, Newark Liberty International Airport (EWR), Newark, NJ", "c1ba9562-157c-4210-919e-ed8f0bdd4c01", "B"] } },
    JFK: { name: "John F. Kennedy International Airport",
      at: { 1: [40.64266, -73.79135], 4: [40.64066, -73.78089],
            5: [40.64631, -73.77560], 8: [40.64867, -73.79262] },
      by: { avianca: "4", delta: "4", "korean air": "4", emirates: "4",
            jetblue: "5", american: "8", "british airways": "8" },
      uber: {
        avianca: ["Avianca", "Terminal 4, John F. Kennedy International Airport (JFK), New York, NY", "46de14f7-bab1-4f47-be42-8b753d5f7983", "4"],
        "korean air": ["Korean Air", "Terminal 4, John F. Kennedy International Airport (JFK), New York, NY", "25dcadb2-b20b-4379-a1b8-9de6b4512f8f", "4"],
        emirates: ["Emirates", "Terminal 4, John F. Kennedy International Airport (JFK), New York, NY", "19961201-3472-468a-846d-76832d72b6f1", "4"],
        jetblue: ["JetBlue", "Terminal 5, John F. Kennedy International Airport (JFK), New York, NY", "8e3cd3aa-0f77-63b4-1d50-f40cc83454ee", "5"],
        american: ["American Airlines", "Terminal 8, John F. Kennedy International Airport (JFK), Jamaica, NY", "99f93c9b-86d4-31cf-bfd4-275aafe6f55e", "8"],
        "british airways": ["British Airways", "Terminal 8, John F. Kennedy International Airport (JFK), New York, NY", "8ca1faa9-55d1-4e82-8e25-9c486fe32901", "8"] } },
  };

  // One spelling for a hand-typed field. "B", "T4" and "Terminal 4" are all things
  // people write into terminal_from, and the lookup key has to be the bare one.
  const bareTerm = (x) => String(x || "").trim().replace(/^(terminal|term|t)\s*[.:-]?\s*/i, "");

  /* The departure terminal for a flight, or null when nothing knows it.

     The row wins over the table — a boarding pass beats a lookup — and a table hit
     is only used when the row is blank, which on the Southwest rows is every time.
     Null is a normal answer, not a failure: it means the link points at the airport
     and the card says nothing about a building, which is correct at DEN. */
  function terminalOf(f) {
    const A = TERMINALS[(f.from_airport || "").trim().toUpperCase()];
    if (!A) return null;
    const air = (f.airline || "").trim().toLowerCase();
    const key = (bareTerm(f.terminal_from) || A.by[air] || "").toUpperCase();
    const at = A.at[key];
    if (!key || !at) return null;
    // Only when Uber's own place sits at the terminal this card just resolved.
    // A hand-typed terminal_from that disagrees with the carrier's usual building
    // is exactly when the id would send the car somewhere the card never said.
    const u = A.uber?.[air];
    return { code: key, label: `Terminal ${key}`, name: `${A.name} Terminal ${key}`,
             lat: at[0], lng: at[1],
             uber: u && String(u[3]).toUpperCase() === key
               ? { addressLine1: u[0], addressLine2: u[1], id: u[2],
                   source: "SEARCH", provider: "uber_places" }
               : null };
  }

  /* The three ways to get there.

     Uber and Lyft are ONE tab, not two. They are the same journey drawn the same
     way — same stops, same order, same terminal at the end — and splitting them
     made the reader pick a company before picking a route, then re-pick the route
     after switching. The tab is the mode of transport; which app drives is a
     button under the map, and both buttons are always there.

     There is no per-mode map styling any more either. `map.css` is the Hub's one
     map treatment and this card inherits it like every other map on the board:
     the same knocked-back tiles, the same `.mstop` marks, the same `.mroute`
     stroke. The brand-tinted tile filter this card used to carry was a fourth
     look for a map that is the same map (and never reached CSS in the first
     place — nothing consumed `--tilefx`).

     `travel` and `sub` are the Google modes; the rideshare tab has neither
     because it builds its own two links. */
  /* `g` is the tab's glyph, in the Hub's one icon idiom — a 24-box, stroke-only,
     currentColor, no fill — the same one `.fnav-g` and the launcher tiles draw in.
     It is here rather than in the template because the three tabs are the same
     object three times and a mode that grew a fourth would otherwise need a
     branch in the renderer. Trusted constant markup: it goes in raw, unescaped,
     which is why nothing from the trip is ever interpolated into it. */
  const RIDE_MODES = [
    { k: "ride", l: "Uber / Lyft",
      g: `<path d="M3.6 16.4h16.8v-3l-1.7-4.1a2 2 0 0 0-1.85-1.25H7.15A2 2 0 0 0 5.3 9.3l-1.7 4.1z"/>`
       + `<path d="M5 16.4v2.1M19 16.4v2.1"/><circle cx="7.6" cy="13.6" r=".9"/>`
       + `<circle cx="16.4" cy="13.6" r=".9"/>` },
    { k: "transit", l: "Transit", cta: "Open in Google Maps", travel: "transit", sub: "train / bus",
      solo: true,
      g: `<rect x="5.6" y="3.4" width="12.8" height="13" rx="3"/><path d="M5.6 10.4h12.8"/>`
       + `<circle cx="9" cy="13.4" r=".9"/><circle cx="15" cy="13.4" r=".9"/>`
       + `<path d="M8.6 16.4 6.6 20.6M15.4 16.4l2 4.2"/>` },
    { k: "drive", l: "Drive", cta: "Open in Google Maps", travel: "driving", sub: "your own car",
      g: `<circle cx="12" cy="12" r="8.4"/><circle cx="12" cy="12" r="2.9"/>`
       + `<path d="M12 3.6v5.5M4.3 14.3l5-1.6M19.7 14.3l-5-1.6"/>` },
  ];
  // An unknown key resolves to the first tab, which is also the migration for the
  // "uber" and "lyft" sitting in browsers from when they were two of them.
  const rideMode = (k) => RIDE_MODES.filter((m) => m.k === k)[0] || RIDE_MODES[0];
  /* A train is a solo ride. The chain, the middle stops and the add button all
     exist because a car can collect four people on the way to the terminal; a
     train collects nobody, everyone walks to their own station, and a list of
     four doors on the Transit tab was the car's route wearing a train's label
     (Sam 2026-08-31: "transit does not need multi stop, those are solo
     rides"). Read off the mode rather than passed down, so nothing below has to
     grow a parameter for it. */
  const soloRide = () => !!rideMode(ridePref().mode).solo;

  // Which tab and whether the chain is on. Per browser, like the day-of ticks and
  // for the same reason: this is how one person is travelling, not a fact about
  // the trip, and writing it to the trip would change it for six other people.
  const RIDE_PREF = `trips.ride.${viewerKey() || "me"}`;
  function ridePref() {
    try { const v = JSON.parse(localStorage.getItem(RIDE_PREF) || "{}"); return v && typeof v === "object" ? v : {}; }
    catch { return {}; }
  }
  function saveRidePref(patch) {
    try { localStorage.setItem(RIDE_PREF, JSON.stringify(Object.assign(ridePref(), patch))); }
    catch { /* private mode — a tab that forgets, never a thrown card */ }
  }

  /* A member's front door, as a point.

     `home` reaches BOTH surfaces — db.get_full_trip attaches it behind `with_home`
     and api_get_trip asks for it true on either port, so the crew get the ride
     chain on their own phones (Sam, 2026-08-28). This comment used to say the
     mirror asked for it false; that stopped being true with that widening and the
     note was left behind, which is worth knowing because the sentence it ended on
     was right: an itinerary you send to six people must not carry their addresses.
     So since 2026-09-10 the mirror ships the POINT and not the street text — the
     chain still orders the pickups, and no guest reads where anyone lives.

     An address with no coordinates yet is not a home for this purpose — a link
     needs a point, and the geocode pass fills it in on the next run. */
  function homeOf(m) {
    const h = m?.home;
    if (!h || h.lat == null || h.lng == null) return null;
    return { who: (m.name || "").trim(), addr: h.address || "", lat: h.lat, lng: h.lng };
  }

  /* Everyone on this exact flight, including the reader.

     Matched on legKey — carrier, route, departure minute — which is the same
     signature crewFlights merges bookings on, so two people who bought separately
     still count as being on one plane. Sam's own rows carry a blank passenger
     (that is what marks them his), so he is never in a crew group and is added
     here by hand. */
  function legMates(t, sel) {
    const key = legKey(sel.row), out = [];
    const add = (m) => { if (m && out.indexOf(m) < 0) out.push(m); };
    add(readerMember(t) || meMember(t));
    crewFlights(t).forEach((g) => {
      if (!g.legs.some((l) => l.rows.some((r) => legKey(r) === key))) return;
      (g.people || []).forEach(add);
    });
    return out;
  }

  /* Four is the whole list: a start, up to two stops along the way, and the
     terminal. Not a limit invented for the editor — Uber's own multi-stop ride
     takes a pickup and three drops, and a car that stops five times on the way to
     a 6am flight has stopped being a shortcut. Anyone the cap leaves out is NAMED
     rather than quietly dropped. */
  const RIDE_MAX_STOPS = 4;
  const RIDE_MAX_MID = RIDE_MAX_STOPS - 2;
  // A row with nowhere in it. It is a real stop on the list — the placeholder asks
  // the question and the locate button answers it — and it stays out of `placed`,
  // so no link and no clock is ever built from a blank.
  const blankStop = () => ({ who: "", addr: "", lat: null, lng: null });
  // How long a dropped "where I am" pin is worth anything. It is one morning's
  // answer, and the leave-by clock is measured off it.
  const CUR_PIN_TTL = 6 * 3600 * 1000;

  /* The ride, as an ordered list of stops: where you start, who you collect, the
     terminal.

     The START is in the list even when there is nobody to collect. It used to
     not be — an unchained ride was the single point of the terminal — and a
     one-point route is what made the map open zoomed onto the airport with the
     rest of the morning off-screen. Your own front door is the other end of the
     line, so it goes in the line (Sam, 2026-08-28: "it should naturally
     center to encompass the entire trip, not just be centered around the terminal
     or centered around your house").

     Chained, it is everyone on the flight who has a home on file, sorted
     furthest-from-the-airport first, so the car fills up on its way in and nobody
     doubles back. Two people at the same address collapse to one stop; the car
     does not stop twice at one door.

     The destination is the TERMINAL when the table knows it, and the airport when
     it does not. That single substitution is the whole "it doesn't know what
     terminal" fix — every link below is built from this list. */
  function rideStops(t, sel, chained) {
    const f = sel.row, port = (f.from_airport || "").trim();
    const term = terminalOf(f), ap = airportPt(port);
    const dest = term
      ? { who: "", addr: term.name, lat: term.lat, lng: term.lng, term: term.label,
          uber: term.uber }
      : (ap ? { who: "", addr: (port ? `${port} Airport` : "the airport"), lat: ap.lat, lng: ap.lng } : null);
    if (!dest) return { stops: [], dest: null, over: [], noHome: [] };
    /* Flying home, the ride does not start at anybody's front door — it starts
       where you slept (Sam, 2026-09-20). The tab swaps to the return leg by
       itself the moment the outbound has landed (dayOfLeg), and the swap used to
       carry the outbound's start across with it: a car ordered from a house two
       thousand miles from the airport it is driving to, with a leave-by clock
       measured off that drive. Everyone on the leg is under one roof by then, so
       there is no chain to build and no missing address to ask anyone for.

       A stay with no coordinates leaves the row BLANK rather than wrong. The
       locate button beside it is the one-tap answer, and on this leg it is the
       likelier answer anyway: the last morning starts wherever you woke up.
    */
    if (sel.g.leg === "return") {
      const stay = lastStay();
      const from = stay && stay.lat != null && stay.lng != null
        ? { who: "", addr: stay.address || stay.name || "the stay", lat: stay.lat, lng: stay.lng }
        : blankStop();
      return { stops: [from, dest], dest: dest, over: [], noHome: [] };
    }
    // Anyone on this flight whose preferences carry no address at all. They are
    // not on the route and there is no way to tell from the route WHY — a car
    // that never offers to collect them looks the same as a car that cannot.
    // Named here, and only for a missing address: a member whose address is on
    // file but will not geocode has already answered, and asking them again for
    // the thing they gave would be the card blaming the reader for its own miss.
    // Tested on the PRESENCE of `home`, not on its address text. _attach_homes
    // only ever sets `home` for a member whose account carries an address, so on
    // Hub the two are the same test. On the shared link the street text is now
    // withheld and only the point ships (api._hide_home_addresses), so reading
    // `.address` there would have named every single person as missing one.
    const noHome = legMates(t, sel)
      .filter((m) => !m?.home)
      .map((m) => (m.name || "").trim()).filter(Boolean);
    const seen = {}, homes = [];
    const take = (m) => {
      const h = homeOf(m);
      if (!h) return;
      const at = `${h.lat.toFixed(4)},${h.lng.toFixed(4)}`;
      if (seen[at]) { seen[at].who += ` + ${h.who}`; return; }
      seen[at] = h;
      homes.push(h);
    };
    // Unchained the list is just yours, so only your own door goes on it. With no
    // home on file that is nothing, the route is the terminal alone, and the links
    // fall back to my_location — the honest answer to "we don't know where you are".
    if (chained) legMates(t, sel).forEach(take);
    else take(readerMember(t) || meMember(t));
    homes.sort((a, b) => (haversine(b.lat, b.lng, dest.lat, dest.lng) || 0)
      - (haversine(a.lat, a.lng, dest.lat, dest.lng) || 0));
    const line = homes.slice(0, RIDE_MAX_STOPS - 1);
    return {
      // The start stays on the list even when nothing filled it in. Without a row
      // there is nowhere on the card to say where you are standing, and "no home
      // on file" was reading as a card that had decided not to ask.
      stops: (line.length ? line : [blankStop()]).concat([dest]),
      dest: dest,
      over: homes.slice(RIDE_MAX_STOPS - 1).map((h) => h.who).filter(Boolean),
      noHome: noHome,
    };
  }

  // Everyone on the flight who could be chained, the ones past the cap included:
  // the checkbox offers the group, and the card says separately who did not fit.
  // Below two it is not a chain, it is a ride, and the checkbox does not appear.
  function chainable(t, sel) {
    const r = rideStops(t, sel, true);
    const n = r.stops.length - 1 + r.over.length;
    return n >= 2 ? n : 0;
  }

  /* The stops the reader is actually going with.

     rideStops() is the answer the card works out; the plan is the answer that is
     on screen, which is the same list until somebody edits a row. It is scoped to
     the leg AND to the chain state, so it is rebuilt from scratch whenever the
     question changes — a stop list carried across a leg change is somebody else's
     route, and one carried across a chain toggle is the wrong number of doors.

     `placed` is the subset that has coordinates. A row you typed that nothing can
     geocode stays visible and stays yours, but it cannot go in a link or on a map,
     so the two are kept apart rather than the row being silently reverted. */
  /* The route is the route, whichever way you travel it (Sam 2026-08-31:
     "if you're going to add it at all, you might as well have it for all"). Transit
     used to key its own separate list, so a stop added on the Uber tab vanished on
     switching to Transit and came back on switching away — one trip keeping two
     itineraries. The chain still splits the key, because chaining genuinely changes
     how many doors are on the list; the tab does not. */
  const planKey = (sel, chained) =>
    `${legKey(sel.row)}|${chained ? "chain" : "solo"}`;
  function ridePlan(t, sel, chained) {
    const auto = rideStops(t, sel, chained);
    if (!auto.dest) return { stops: [], placed: [], dest: null, over: [], noHome: [], edited: false };
    const key = planKey(sel, chained), saved = ridePref().plan;
    const stops = (saved && saved.key === key && Array.isArray(saved.stops) && saved.stops.length)
      ? saved.stops.slice(0, RIDE_MAX_STOPS) : auto.stops;
    // A plan saved before the terminal carried an Uber place still holds a bare
    // coordinate for it, and would keep sending the car to the wrong door until
    // the reader happened to edit the row. The terminal is the one stop nobody
    // can edit, so it is safe to refresh from the dest just computed.
    stops.forEach((x) => {
      if (x && !x.who && x.lat === auto.dest.lat && x.lng === auto.dest.lng) x.uber = auto.dest.uber;
    });
    /* A pin dropped on "where I am" is true for the morning it was dropped and
       false by the next one. The plan is saved per leg, so yesterday's kerb would
       otherwise still be timing today's ride — and a leave-by built off a stale
       point looks exactly like one built off a fresh one. Expired, the row goes
       back to whatever the card would have autofilled. */
    stops.forEach((x, i) => {
      if (x?.cur && Date.now() - (x.at || 0) > CUR_PIN_TTL) stops[i] = auto.stops[i] || blankStop();
    });
    return {
      stops: stops,
      // `off` is a door on the list that this ride is not stopping at. It stays a
      // row so it can be put back with one click; it is out of `placed`, which is
      // what the map, the links and the leave-by are all built from.
      placed: stops.filter((x) => x && !x.off && x.lat != null && x.lng != null),
      dest: auto.dest,
      over: auto.over,
      noHome: auto.noHome,
      edited: stops !== auto.stops,
    };
  }
  const savePlan = (sel, chained, stops) =>
    saveRidePref({ plan: { key: planKey(sel, chained), stops: stops } });
  // The first line of an address is what a person reads a stop as. The rest is
  // the city and the state, which on a map of one city is the same on every pin.
  const shortAddr = (p) => String((p?.addr) || "").split(",")[0].trim();


  // The rail's twelve buttons and the sub-rail host, from trips.html. Every prop is a constant: renderFunnelNav
  // flips hidden/active imperatively like the plain page, and a constant prop is never rewritten on re-render.
  function FunnelNav() {
    return (
      <>
      <button type="button" className="fnav hub-t3p-tab hub-nav-item" data-mode="dayof"><span className="fnav-l hub-t3p-tab-label hub-nav-label"><svg className="fnav-g hub-t3p-tab-glyph" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.4"/><path d="M12 7.2 V12 L15.6 14.4"/></svg>liftoff</span></button>
      <button type="button" className="fnav hub-t3p-tab hub-nav-item" data-mode="packing"><span className="fnav-l hub-t3p-tab-label hub-nav-label"><svg className="fnav-g hub-t3p-tab-glyph" viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="7.8" width="18" height="12.6" rx="1.5"/><path d="M8.4 7.8 V4.8 A1.2 1.2 0 0 1 9.6 3.6 H14.4 A1.2 1.2 0 0 1 15.6 4.8 V7.8"/><path d="M8.4 7.8 V20.4 M15.6 7.8 V20.4"/></svg>packing</span></button>
      <button type="button" className="fnav hub-t3p-tab hub-nav-item" data-mode="weather"><span className="fnav-l hub-t3p-tab-label hub-nav-label"><svg className="fnav-g hub-t3p-tab-glyph" viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="8.4" r="3.6"/><path d="M9 1.8 V3.3 M9 13.5 V15 M3.3 8.4 H1.8 M16.2 8.4 H14.7 M4.95 4.35 L3.9 3.3 M14.05 13.45 L13 12.4 M13.05 4.35 L14.1 3.3 M4.95 12.45 L3.9 13.5"/><path d="M8.4 20.4 A3.6 3.6 0 0 1 8.4 13.2 A5.4 5.4 0 0 1 18.6 14.7 A3 3 0 0 1 18.6 20.4 Z"/></svg>weather</span></button>
      <button type="button" className="fnav hub-t3p-tab hub-nav-item" data-mode="crew"><span className="fnav-l hub-t3p-tab-label hub-nav-label"><svg className="fnav-g hub-t3p-tab-glyph" viewBox="0 0 24 24" aria-hidden="true"><circle cx="9.6" cy="8.4" r="3"/><path d="M4.2 19.8 C4.2 16.2 6.6 14.4 9.6 14.4 C12.6 14.4 15 16.2 15 19.8"/><path d="M16.2 6.6 A3 3 0 0 1 16.2 12.6"/><path d="M17.4 14.7 C19.8 15.3 21 17.1 21 19.8"/></svg>crew</span></button>
      <button type="button" className="fnav hub-t3p-tab hub-nav-item active" data-mode="flights"><span className="fnav-l hub-t3p-tab-label hub-nav-label"><svg className="fnav-g hub-t3p-tab-glyph" viewBox="0 0 24 24" aria-hidden="true"><path d="M12.6 3 C13.5 3 13.8 4.2 13.8 5.4 V10.2 L22.2 15 V16.2 L13.8 13.8 V18.6 L16.2 19.8 V21 L12.6 19.8 L9 21 V19.8 L11.4 18.6 V13.8 L3 16.2 V15 L11.4 10.2 V5.4 C11.4 4.2 11.7 3 12.6 3 Z"/></svg>transport</span></button>
      <button type="button" className="fnav hub-t3p-tab hub-nav-item" data-mode="housing"><span className="fnav-l hub-t3p-tab-label hub-nav-label"><svg className="fnav-g hub-t3p-tab-glyph" viewBox="0 0 24 24" aria-hidden="true"><path d="M4.2 10.2 L12.6 3 L21 10.2 V21 H4.2 Z"/><path d="M10.2 21 V13.8 H15 V21"/></svg>housing</span></button>
      <button type="button" className="fnav hub-t3p-tab hub-nav-item fnav-hallmark" data-mode="hallmark" hidden><span className="fnav-l hub-t3p-tab-label hub-nav-label"><svg className="fnav-g hub-t3p-tab-glyph" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 L14.4 9 L21 9.6 L16.2 14.1 L17.6 21 L12 17.6 L6.4 21 L7.8 14.1 L3 9.6 L9.6 9 Z"/></svg><span className="fnav-t" data-hlabel=""></span></span></button>
      <button type="button" className="fnav hub-t3p-tab hub-nav-item" data-mode="grocery"><span className="fnav-l hub-t3p-tab-label hub-nav-label"><svg className="fnav-g hub-t3p-tab-glyph" viewBox="0 0 24 24" aria-hidden="true"><path d="M2.4 4.2 H5.4 L8.4 15.6 H18.6 L21.6 8.4 H6.3"/><circle cx="9.6" cy="19.8" r="1.5"/><circle cx="17.4" cy="19.8" r="1.5"/></svg>grocery</span></button>
      <button type="button" className="fnav hub-t3p-tab hub-nav-item" data-mode="activities"><span className="fnav-l hub-t3p-tab-label hub-nav-label"><svg className="fnav-g hub-t3p-tab-glyph" viewBox="0 0 24 24" aria-hidden="true"><path d="M6.6 3 V21"/><path d="M6.6 4.2 H18.6 L15.6 8.4 L18.6 12.6 H6.6"/></svg>activities</span></button>
      <button type="button" className="fnav hub-t3p-tab hub-nav-item" data-mode="food"><span className="fnav-l hub-t3p-tab-label hub-nav-label"><svg className="fnav-g hub-t3p-tab-glyph" viewBox="0 0 24 24" aria-hidden="true"><path d="M6.6 3 V8.4 C6.6 9.9 7.8 10.8 9 10.8 C10.2 10.8 11.4 9.9 11.4 8.4 V3"/><path d="M9 10.8 V21"/><path d="M17.4 21 V13.2"/><path d="M17.4 13.2 C15.6 13.2 15 11.4 15.6 7.8 C16 5.4 16.8 3 17.4 3 Z"/></svg>food</span></button>
      <button type="button" className="fnav hub-t3p-tab hub-nav-item" data-mode="itinerary"><span className="fnav-l hub-t3p-tab-label hub-nav-label"><svg className="fnav-g hub-t3p-tab-glyph" viewBox="0 0 24 24" aria-hidden="true"><rect x="4.2" y="5.4" width="16.8" height="15.6" rx="1.2"/><path d="M4.2 10.2 H21"/><path d="M9 3 V6.6 M16.2 3 V6.6"/></svg>itinerary</span></button>
      <div className="fsub hub-nav-subrail" id="funnelSub" hidden></div>
      <button type="button" className="fnav hub-t3p-tab hub-nav-item" data-mode="cost"><span className="fnav-l hub-t3p-tab-label hub-nav-label"><svg className="fnav-g hub-t3p-tab-glyph" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 21 H22.2 M5.4 21 V16.2 M10.2 21 V13.8 M15 21 V10.2 M19.8 21 V6.6"/></svg>cost</span></button>
      </>
    );
  }

Object.assign(U, {
  FunnelNav, wireChrome, loadPrefs, renderFunnelNav, renderFunnelSub, renderFocus, hallmarkDef, HM_KEY, absDate,
  readerLegGroups, dayOfSel, defaultDir, checkpointRead, TERMINALS, terminalOf, RIDE_MODES, rideMode, soloRide,
  ridePref, saveRidePref, RIDE_MAX_MID, blankStop, chainable, ridePlan, savePlan, shortAddr, groupIntoCards,
  stampColumnLabels,
});
})();
