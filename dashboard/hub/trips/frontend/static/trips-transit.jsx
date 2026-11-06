/* hub · trips page, transit (2026-10-13): React port of trips.js lines 1533-2689 (the ride links, recenter, the
   getting-there card with its map, the transit router client, the day-of checklist and listDayOf). Near-verbatim
   port as plain functions inside an IIFE; every async function became a promise chain. Exports onto
   window.TripsUI: addRecenter, DAYOF_KEY, listDayOf. */
(() => {
const U = window.TripsUI;
const { esc, setHTML, money, rowCost, isGuest, viewerKey, state, T } = U;
const { absDate, dayOfSel, checkpointRead, terminalOf, rideMode, soloRide, ridePref, saveRidePref,
  blankStop, chainable, ridePlan, savePlan, shortAddr, liftChips, osrmRoute, airportLead, driveMin, absOf,
  groundOptions, readerMember, dayReadHTML, legKey, dayLong, flightLegBlock, viewerFlightMissing,
  daysAway, bindPanel, ctxLink } = U.fwd("absDate", "dayOfSel", "checkpointRead", "terminalOf", "rideMode",
  "soloRide", "ridePref", "saveRidePref", "blankStop", "chainable", "ridePlan", "savePlan", "shortAddr",
  "liftChips", "osrmRoute", "airportLead", "driveMin", "absOf", "groundOptions", "readerMember",
  "dayReadHTML", "legKey", "dayLong", "flightLegBlock", "viewerFlightMissing", "daysAway", "bindPanel",
  "ctxLink");
const hubBasemap = (map) => window.hubBasemap(map);

  /* ── THE LINKS ─────────────────────────────────────────────────────────────
     Uber takes a url-encoded JSON Location per stop and accepts a list of them,
     which is the only reason the chain is possible at all
     (developer.uber.com/docs/deep-linking). The terminal goes in as Uber's own
     PLACE, not as a coordinate: handed lat/lng it re-resolves against its place
     index and drops you at whatever is nearest, which is a concession stand as
     often as a terminal (see TERMINALS.uber). Everything else on the route is a
     front door, which has no place id and stays a coordinate.

     `pickup=my_location` when the chain is off: the app knows where the phone is
     better than the trip does, and this card deliberately records nowhere as the
     reader's own starting point. */
  const uberLoc = (p) => encodeURIComponent(JSON.stringify(p.uber || {
    latitude: p.lat, longitude: p.lng, addressLine1: p.addr || p.who || "" }));
  function uberURL(stops) {
    const chained = stops.length > 1;
    const pick = chained ? uberLoc(stops[0]) : "my_location";
    const drops = (chained ? stops.slice(1) : stops)
      .map((d, i) => `drop%5B${i}%5D=${uberLoc(d)}`);
    return `https://m.uber.com/looking?pickup=${pick}&${drops.join("&")}`;
  }
  // Lyft's universal link carries exactly one pickup and one destination, there
  // are no waypoints in it. A chain therefore renders as one link per hop, which
  // is honest about what the app can be handed rather than dropping stops.
  function lyftURL(from, to) {
    return "https://lyft.com/ride?id=lyft"
      + (from ? `&pickup[latitude]=${from.lat}&pickup[longitude]=${from.lng}` : "")
      + `&destination[latitude]=${to.lat}&destination[longitude]=${to.lng}`;
  }
  // Google takes intermediate stops as `waypoints`, so the chain survives. The
  // destination goes in as its NAME, not a coordinate, "LaGuardia Airport
  // Terminal B" is what puts the terminal on the screen you are looking at.
  function mapsURL(stops, travel) {
    const pt = (p) => `${p.lat},${p.lng}`;
    const last = stops[stops.length - 1], mid = stops.slice(0, -1);
    return "https://www.google.com/maps/dir/?api=1"
      + (mid.length ? `&origin=${encodeURIComponent(pt(mid[0]))}` : "")
      + "&destination=" + encodeURIComponent(last.addr || pt(last))
      + (mid.length > 1 ? `&waypoints=${encodeURIComponent(mid.slice(1).map(pt).join("|"))}` : "")
      + "&travelmode=" + travel;
  }

  // What the board itself already priced for this ride, if anything. The only
  // number on this card that came from anywhere: Uber's and Lyft's fare endpoints
  // are partner-gated, so a figure invented here would read exactly like a quote.
  function boardFare(t, sel) {
    const f = sel.row, dateISO = T.parseStamp(f.departure_time, t.start_date)?.date;
    const PORT = (f.from_airport || "").trim().toUpperCase();
    const hit = groundOptions(t, dateISO).filter((x) => (x.type || "") === "rideshare"
      && PORT && String(x.arrival || "").toUpperCase().indexOf(PORT) >= 0 && rowCost(x))[0];
    return hit ? rowCost(hit) : null;
  }

  /* How long the whole thing takes, and therefore when to walk out.

     driveMin is a straight line times a road factor, so this is an estimate and the
     card says so. PICKUP_PAUSE is the minute somebody spends actually getting in
     the car, which on a five-stop chain is the difference between leaving on time
     and missing bag drop. */
  const PICKUP_PAUSE = 5;
  /* When to walk out, and whether that time is measured or guessed.

     `sec` is OSRM's own duration for the run when the router has answered, and null
     until it does. The two paths differ only in where the driving minutes come from
    , the pickup pauses are the card's own either way, because no router knows how
     long somebody takes to find their shoes. Which one produced the number is put
     on the pill's tooltip rather than left for the reader to assume. */
  function leaveBy(_t, sel, stops, sec) {
    const dep = absOf(sel.row.departure_time);
    if (dep == null) return null;
    const pauses = Math.max(0, stops.length - 2) * PICKUP_PAUSE;
    const mins = sec == null ? rideMinutes(stops) : Math.round(sec / 60) + pauses;
    if (mins == null) return null;
    const door = dep - airportLead(sel.row);
    return { clock: T.fmtClock((((door - mins) % 1440) + 1440) % 1440), mins: mins, measured: sec != null };
  }
  // `kind` is what produced the number, because "measured" means a different thing
  // on each tab and a train time under the label "road time" reads as a bug.
  const leavePill = (l, kind) => (l
    ? `<span class="hub-pill ridepill" data-ridepill title="${esc(l.measured
        ? (kind === "transit"
            ? `timetabled · ${l.mins} min door to terminal`
            : `measured road time · ${l.mins} min door to kerb`)
        : `estimated · ${l.mins} min door to kerb`)}">leave by <b>${esc(l.clock)}</b></span>`
    : "");
  function rideMinutes(stops) {
    if (stops.length < 2) return null;
    let m = 0;
    for (let i = 1; i < stops.length; i++) m += driveMin(stops[i - 1], stops[i]);
    // Only the doors BETWEEN the ends are a pause. Your own is not a pickup you
    // wait through, so a plain two-stop ride adds nothing.
    return m + Math.max(0, stops.length - 2) * PICKUP_PAUSE;
  }

  /* The stops, as rows you can retype.

     Autofilled from the list above and then yours: the addresses on file are a
     good guess and a guess is all they are, because the morning of a flight is
     exactly when somebody stayed over somewhere else. Every commit rewrites both
     links and the map, so the row IS the route rather than a label describing it.

     Only the middles carry a remove button. The two ends are what the ride is -
     dropping the terminal would leave a car going nowhere, and dropping the start
     is what the empty field already does. */
  /* The label numbers the RIDE, not the list. A door the car is skipping is not
     "Stop 2", and the ones after it must not shuffle up a place on screen when it
     goes quiet, the row is still there, it is just not being driven to. */
  const stopLabel = (act) => (act === -2 ? "Destination" : act < 0 ? "Skipping"
    : act === 0 ? "Start" : `Stop ${act}`);
  function rideStopsHTML(plan) {
    const n = plan.stops.length;
    // No destination means no route to edit, the links already say why.
    if (!n) return "";
    let act = 0;
    const rows = plan.stops.map((x, i) => {
      // -2 is the terminal, which is what the ride IS and cannot be skipped.
      const pos = i === n - 1 ? -2 : x.off ? -1 : act++;
      const label = stopLabel(pos);
      // The node on the rail. Three shapes, because the reader is looking for
      // three different things: where the ride starts, where it is going, and
      // which doors it collects on the way.
      const node = pos === -2 ? " is-dest" : pos === 0 ? " is-start" : "";
      return `<div class="ridestop${x.off ? " is-skipped" : ""}">
      <span class="ridestop-n${node}" aria-hidden="true"></span>
      <span class="ridestop-k">${esc(label)}</span>
      <input class="ridestop-a${x.lat == null ? " is-nogeo" : ""}" type="text" data-stop="${i}"
        value="${esc(x.addr || x.who || "")}" spellcheck="false"
        aria-label="${esc(label)} address"
        placeholder="${i === 0 ? "where you're leaving from" : "an address"}">
      ${pos === 0
        ? `<button class="ridestop-x ridestop-loc" type="button" data-stoploc="${i}"
             title="use where I am right now"
             aria-label="start from where I am right now">\u2316</button>`
        // the same slot, empty, so every field ends at the same x as the start row's
        : `<span class="ridestop-x is-off" aria-hidden="true"></span>`}
      ${pos !== -2
        ? `<button class="ridestop-x" type="button" data-stopoff="${i}"
             aria-pressed="${x.off ? "true" : "false"}"
             title="${x.off ? "put this stop back in the ride" : "leave this stop out of this ride"}"
             aria-label="${x.off ? "put this stop back in the ride" : "leave this stop out of this ride"}"
             >${x.off ? "+" : "×"}</button>`
        : `<span class="ridestop-x is-off" aria-hidden="true"></span>`}
    </div>`;
    }).join("");
    // n - 2 middles today; n of 1 (a terminal and nothing else) has none, and the
    // button then adds the start it is missing.
    const mid = Math.max(0, n - 2);
    // The add button is the next node ON the rail, not a dashed box parked beside
    // it: a stop you have not added yet is a hollow dot in the same column as the
    // ones you have, which is the whole point the dashed rectangle was missing.
    // On every tab, including Transit. It was gated on `!soloRide()` on the reading
    // that a train collects nobody, true of the CHAIN, which is other people's
    // doors, and not true of a stop you choose to make on the way, which is a
    // place you are going whatever you are riding. The two were one flag; they are
    // not one thing.
    return rows + (mid < U.RIDE_MAX_MID
      ? `<button class="ridestop-add" type="button" data-stopadd>`
        + `<span class="ridestop-n is-add" aria-hidden="true"></span>`
        + `<span>add a stop along the way</span></button>` : "");
  }

  function gettingThereHTML(t, sel) {
    const f = sel.row, port = (f.from_airport || "").trim();
    const pref = ridePref();
    const mode = rideMode(pref.mode);
    const can = chainable(t, sel);
    const chained = !!pref.chain && can > 0 && !mode.solo;
    const plan = ridePlan(t, sel, chained);
    const term = terminalOf(f);
    // The estimate, which is on screen immediately. The measured one replaces it in
    // place when the router answers, see stampLeave in bindGettingThere.
    const leave = leaveBy(t, sel, plan.placed, null);
    const tabs = U.RIDE_MODES.map((m) => `<button class="hub-tab ridetab${m.k === mode.k ? " is-on" : ""}"
      data-ridemode="${esc(m.k)}" type="button" role="tab"
      aria-selected="${m.k === mode.k ? "true" : "false"}"
      ><svg class="hub-tab-glyph" viewBox="0 0 24 24" aria-hidden="true">${m.g}</svg
      ><span>${esc(m.l)}</span></button>`).join("");
    /* The tabs and the clock sit UNDER the map, on the seam between the picture and
       the details it belongs to (Sam 2026-08-31). They spent one round up in the
       card head beside the title, which read better than the full-bleed strip they
       started as but still put the choice a map's height away from the rows it
       rewrites. Here the reading order is the order of the questions actually asked
       at 4am: where am I going (the map), how am I getting there (the tabs), when do
       I have to leave (the clock), and then the addresses that answer it.

       The head goes back to the plain title it was, so `.hub-infocard-head` needs no
       override on this card any more.

       The stops and the links then sit SIDE BY SIDE at board width: stacked, each was
       a full-width band with an address in the left third and nothing in the other
       two. */
    return `<div class="hub-infocard hub-infocard--wide ridecard" data-ridecard>
      <div class="hub-infocard-head tlcard-head">
        <span class="hub-infocard-t">Getting there <i>${esc(term ? `${port} ${term.label}`
          : (port ? `${port} Airport` : "the airport"))}</i></span>
      </div>
      <div class="ridemap" data-ridemap><div class="dayv-map-note">loading map…</div></div>
      <div class="ridebar">
        <div class="hub-tabs hub-tabs--segmented ridetabs" role="tablist">${tabs}</div>
        <span class="hub-infocard-r" data-ridepillhost>${leavePill(leave)}</span>
      </div>
      <div class="ridebody">
        <div class="rideplan">
          <div class="ridestops" data-ridestops>${rideStopsHTML(plan)}</div>
          ${can ? `<label class="hub-chip-toggle ridechain" data-ridechainrow${mode.solo ? " hidden" : ""}><input type="checkbox" data-ridechain${chained ? " checked" : ""}>
            <span>one car for all ${can} of you — pick up furthest first</span></label>` : ""}
        </div>
        <div class="rideout" data-rideout></div>
      </div>
    </div>`;
  }

  /* The link half of the card, redrawn on every tab click without touching the
     rest of it. Separate from gettingThereHTML because switching tabs must not
     re-render the checkbox out from under the pointer, the same reason the
     checklist counter is stamped in place. */
  function rideLinksHTML(t, sel, mode, plan) {
    const f = sel.row, port = (f.from_airport || "").trim();
    if (!plan.dest) {
      return `<div class="hub-link-row hub-link-row--flat ctx-link ctx-link-flat"><span class="hub-link-row-t ctx-link-t">${
        port ? `${esc(port)} has no coordinates yet — geocode the trip and the ride links land`
             : "no departure airport on this leg yet"}</span></div>`;
    }
    const fare = boardFare(t, sel), stops = plan.placed, rows = [];
    const est = fare ? `${money(fare)} est.` : "";
    if (mode.k === "ride") {
      // Both apps, side by side, always. Uber's deep link carries every stop in
      // one ride; Lyft's carries exactly one pickup and one destination and there
      // are no waypoints in it, so a chain can only ever be handed its FIRST hop.
      // That is the hop to hand it: Lyft lets you add a stop inside the app, and
      // adding one to a ride already pointed at the next door is a tap. This used
      // to render one Lyft link per hop below the buttons, bloat, because nobody
      // opens three ride apps, they open one and add the stop (Sam 2026-08-31).
      const chain = stops.length > 2;
      rows.push(`<div class="ridebtns">${
        ctxLink("Open Uber", uberURL(stops), est || "every stop in one ride")}${
        ctxLink("Open Lyft", lyftURL(stops.length > 1 ? stops[0] : null,
          stops.length > 1 ? stops[1] : plan.dest),
          chain ? "first leg — add the rest in the app" : (est || "set and ready"))}</div>`);
    } else {
      // The trains land here when the router answers, above the Maps link, because
      // the card's own answer outranks the button that sends you off to get one.
      if (mode.k === "transit") {
        rows.push(`<div class="translist" data-transit><div class="hub-infocard-fine">`
          + `working out the trains…</div></div>`);
      }
      rows.push(ctxLink(mode.cta, mapsURL(stops, mode.travel), mode.sub));
    }
    // Anything the transport board already has for that morning that ends at this
    // airport. A booked airport ride outranks every link above it and used to be
    // three tabs away from the person trying to catch the plane.
    const dateISO = T.parseStamp(f.departure_time, t.start_date)?.date;
    const PORT = port.toUpperCase();
    groundOptions(t, dateISO).filter((x) =>
      PORT && String(x.arrival || "").toUpperCase().indexOf(PORT) >= 0)
      .forEach((x) => { rows.push(ctxLink(x.description || x.type, x.url || "",
        rowCost(x) ? money(rowCost(x)) : "on the board")); });
    // The one thing the links cannot do, said once rather than discovered at the
    // curb. Neither app's link carries a pickup time, verified against Uber's and
    // Lyft's own deep-link docs, so the time above is the card's answer, not the
    // app's, and a reserved ride still has to be set in the app.
    // BOTH notes are about a car, so both belong to the tab that has one. They were
    // written when this card was rideshare and nothing else, and stayed unscoped
    // when the other tabs arrived, which put "neither app's link can carry a
    // pickup time" under a list of trains, on a tab with no app link on it.
    const notes = [];
    if (mode.k === "ride") {
      if (plan.over.length) notes.push("no room in the car for " + plan.over.join(", ")
        + " — a ride holds four stops");
      notes.push(stops.length > 2
        ? "one car for the lot: Uber holds every stop, Lyft is set to the first one — add the rest in the app"
        : "neither app's link can carry a pickup time; open it now, or reserve in the app for the time above");
    }
    // The missing-address prompt belongs to every tab, not just the car: a crew
    // member with no address on file is absent from the map and the walk to the
    // train too. The link is the page they fix it on, the mirror's account page
    // for a guest, the same page on Hub for Sam, who can open anyone's.
    const gone = plan.noHome || [];
    const fix = gone.length
      ? `<div class="hub-note is-warn">${esc(gone.length === 1 ? `${gone[0]} has` : `${gone.join(", ")} have`)
          } no address on file, so they are not on this route —`
        + ` <a class="hub-infocard-note-a" href="${isGuest() ? "/gate/prefs" : "/trips/preferences"}">add ${
            gone.length === 1 ? "it" : "them"} in preferences</a></div>`
      : "";
    return rows.join("") + notes.map((n) =>
      `<div class="hub-infocard-fine">${esc(n)}</div>`).join("") + fix;
  }

  /* ── RECENTER ───────────────────────────────────────────────────────────────
     Every map here pans and zooms, and every map here therefore gets lost: two
     drags into a route and the airport is off-screen with no way back but a
     reload, which on the day-of card also throws away the tab and the stops you
     just typed. One control, added by every map that frames itself, that puts the
     view back where the map opened.

     It takes the frame as a THUNK rather than a bounds object because the day map
     re-fits against a floor that depends on what is on it, and a snapshot taken at
     build time would recenter onto a stale frame after a filter change.

     ponytail: a plain absolutely-positioned button, not L.Control. A leaflet
       control is a class, a factory and an onAdd for one button that never moves
       from the corner. */
  function addRecenter(map, el, refit) {
    if (!map || !el) return;
    const b = document.createElement("button");
    b.type = "button";
    b.className = "map-recenter";
    b.title = "back to the whole route";
    b.setAttribute("aria-label", "recenter the map");
    b.textContent = "⌖";
    b.onclick = (ev) => { ev.preventDefault(); ev.stopPropagation(); refit(); };
    // Leaflet listens on the container for drag and wheel; without this a click
    // on the button starts a map drag under it and the press never registers.
    if (window.L && L.DomEvent) {
      L.DomEvent.disableClickPropagation(b);
      L.DomEvent.disableScrollPropagation(b);
    }
    el.appendChild(b);
  }

  /* The map. Its own leaflet instance, not the shared dayMapHost one: that slot
     belongs to the three boards asking "where is this", and this card is inside
     the day-of list rather than above it.

     It is drawn in the Hub's own map vocabulary and nothing else, `.mstop` dots
     with a chip hung off them, a `.mroute is-straight` stroke, the tile treatment
     every map on the board shares. It takes no mode: switching tabs does not
     change what the ground looks like, because the route is the same route and a
     brand-tinted copy of one map is still one map.

     The route is the REAL ROAD, fetched from OSRM through the same osrmRoute the
     day map uses, and it starts as a dashed straight line only until that lands.
     The card used to stop at the dashed line on a note reading "public mirror, no
     directions host", which had stopped being true: router.project-osrm.org is in
     the mirror's own connect-src and the day map next door had been measuring road
     routes through it the whole time. A straight line to LGA lies about the drive,
     because the straight line goes over the East River and you do not.

     Dashed still means what it always meant: stops in this order, no road known.
     It is what a transit leg draws (OSRM has no transit graph, so that tab keeps
     it), and what any leg falls back to when the router says nothing. */
  /* Where you get on and where you get off, marked and named.

     A transit answer used to draw as coloured line, dashed line, coloured line -
     and the dashed walk ended in the middle of a block with nothing saying what
     was there. The thing the reader actually has to know at that point is the
     station name: it is what is on the sign above the stairs, and it is what
     tells them the seven-minute walk was to the right door. So every boarding
     and every alighting gets a mark carrying the line's roundel and the station.

     Transfers merge. Getting off the F and onto the G happens at one station, so
     one mark reads "F→G · Bergen St" rather than two chips stacked on the same
     dot. Keyed at four decimals, about eleven metres, which is close enough to
     treat two platform coordinates as the same station and far enough apart to
     keep two genuinely different stations separate.

     Anything already on the map as a numbered stop is skipped, the airport's own
     station would otherwise sit under the ✈ chip and hide it. */
  /* How close two platforms have to be to be called the same station.

     A transfer is one place to the person making it, you get off the F and get on
     the A without leaving the building, but the router hands back two coordinates
     for it, because the F platform and the A platform are two different pieces of
     track. They are typically 40-150m apart, which at the zoom this card sits at is
     two chips on top of each other (Sam 2026-08-31: "these pins start
     overlapping and it gets really messy").

     250m is set where it is because it has to clear the longest in-station walk in
     the system Sam actually uses, Times Sq-42 St to the shuttle is about 200m
     of passageway, while staying under the shortest gap between two stations that
     really are separate, which in Manhattan is a ~270m avenue block. Above this the
     two marks stay apart, and they should: a transfer that makes you walk 400m down
     a street is a walk, and both of its ends are things you need to see. */
  const XFER_M = 250;

  function stationMarks(map, legs, stops) {
    /* A place already marked as a numbered stop does not get marked again.

       By DISTANCE, for the same reason the transfers merge by distance: the airport's
       bus stop and the airport are one place to the reader, and they are ~30m apart
       in the data. The old exact-coordinate test agreed only when the router and the
       trip had rounded to the same four decimals, so on the LGA run the Q90 chip drew
       directly on top of the ✈ Terminal B chip and pushed itself off the top of the
       frame, one place, two chips, and the top one unreadable. */
    const near = (pt) => stops.some((q) => map.distance(q, pt) <= XFER_M);
    /* Travel order, board before alight, one entry per end of every ridden leg.
       A flat list rather than the coordinate-keyed Map this used to build: keying on
       the coordinate merges only the platforms that share one to four decimals (~11m),
       and the whole problem is the transfers whose platforms do not. */
    const marks = [];
    legs.forEach((lg) => {
      if (!lg.transit) return;
      [[lg.from_pt, lg.from], [lg.to_pt, lg.to]].forEach(([pt, name]) => {
        if (!pt || near(pt)) return;
        marks.push({ pt, name: name || "", lines: lg.line ? [lg.line] : [], color: lg.color || "" });
      });
    });
    /* Fold each transfer into one mark.

       Only NEIGHBOURS are considered, which is what makes a plain sweep correct
       here rather than a clustering pass: the list is in travel order, so the two
       halves of a transfer are always the alight of one leg immediately followed by
       the board of the next. Two stations that happen to be near each other but are
       not consecutive in the itinerary are never merged, however close they sit.

       The merged mark lands at the MIDPOINT of the two platforms, which is roughly
       where the station is, and carries both lines in the order they are ridden -
       so the chip reads "F→A" at the one dot instead of "F" and "A" fighting over
       the same forty pixels. */
    const merged = [];
    marks.forEach((m) => {
      const prev = merged[merged.length - 1];
      if (prev && map.distance(prev.pt, m.pt) <= XFER_M) {
        prev.pt = [(prev.pt[0] + m.pt[0]) / 2, (prev.pt[1] + m.pt[1]) / 2];
        m.lines.forEach((l) => { if (prev.lines.indexOf(l) < 0) prev.lines.push(l); });
        if (!prev.color) prev.color = m.color;
        // The longer name wins. Routers label the two platforms of one station
        // inconsistently ("Jay St" on one, "Jay St-MetroTech" on the other), and the
        // fuller one is the one written on the sign the reader is looking for.
        if ((m.name || "").length > (prev.name || "").length) prev.name = m.name;
        return;
      }
      merged.push(m);
    });
    /* Returned rather than just drawn, so the caller can hand them to liftChips
       with the ride stops. Every lift starts at 0 and the ladder decides the rest:
       the two alternating magic heights this used to carry separated the pairs
       somebody had anticipated and still drew "G · Bergen St" through the pickup
       chip a few hundred metres away. */
    return merged.map((at) => {
      const xfer = at.lines.length > 1;
      const roundel = at.lines.length ? at.lines.join("→") : "•";
      const marker = L.marker(at.pt, { icon: L.divIcon({
        className: "", iconSize: [8, 8], iconAnchor: [4, 4],
        html: `<span class="mstop mstation${xfer ? " is-xfer" : ""}" style="--lift:0px${
            at.color ? `;--tc:${esc(at.color)}` : ""}">`
          + `<span class="mchip"><b>${esc(roundel)}</b><em>${esc(at.name)}</em></span>`
          + `<span class="mlead"></span><span class="mdot"></span></span>` }) })
        .addTo(map).bindTooltip((xfer ? "transfer · " : "") + (at.name || "station"));
      return { marker, lat: at.pt[0], lng: at.pt[1] };
    });
  }

  let rideMap = null;
  function renderRideMap(el, stops, route, onRoute) {
    if (rideMap) { rideMap.remove(); rideMap = null; }
    if (!el) return;
    if (!window.L) { setHTML(el, `<div class="dayv-map-note">map unavailable — leaflet didn't load</div>`); return; }
    if (!stops.length) { setHTML(el, `<div class="dayv-map-note">nothing on this leg has coordinates yet</div>`); return; }
    setHTML(el, "");
    /* Frozen: a frame, not a map. Every gesture is off, drag, wheel, double-click,
       pinch, box, keyboard, and there is no zoom control and no recenter button,
       because with nothing able to move the frame there is nothing to recenter to.
       This is a picture of the route on the one morning it is read, and a map that
       pans is a map you can lose the route off the edge of at 4am.

       zoomSnap 0, and on this map alone. fitBounds otherwise rounds DOWN to a whole
       zoom level, so any frame less than twice as tall as the last one lands on the
       same integer and draws the route at exactly the size it already was. Giving
       this card a taller box bought nothing until this line: 420 -> 589px is a 1.4x
       gain, and a whole-step zoom throws all of it away. */
    const map = L.map(el, { attributionControl: false, zoomSnap: 0, zoomControl: false,
      dragging: false, scrollWheelZoom: false, doubleClickZoom: false,
      boxZoom: false, keyboard: false, touchZoom: false });
    rideMap = map;
    hubBasemap(map);
    const pts = stops.map((p) => [p.lat, p.lng]);
    let line = pts.length > 1
      ? L.polyline(pts, { className: "mroute is-straight", weight: 3, opacity: 0.75, dashArray: "5 6" }).addTo(map)
      : null;
    const n = stops.length;
    // Every mark on this map, in one list, because they all compete for the same sky.
    // Stations are appended to it when the router answers.
    let marks = stops.map((p, i) => {
      const lead = i === n - 1 ? "✈" : String(i + 1);
      const marker = L.marker([p.lat, p.lng], { icon: L.divIcon({
        className: "", iconSize: [10, 10], iconAnchor: [5, 5],
        html: `<span class="mstop" style="--lift:0px"><span class="mchip"><b>${esc(lead)}</b>`
          + `<em>${esc(p.who || p.term || shortAddr(p) || stopLabel(i, n))}</em></span>`
          + `<span class="mlead"></span><span class="mdot"></span></span>` }) })
        .addTo(map).bindTooltip(p.who ? p.who + (p.addr ? ` · ${p.addr}` : "") : (p.addr || "the terminal"));
      return { marker, lat: p.lat, lng: p.lng };
    });
    /* Frame the WHOLE route, as tight as it will go.

       Pixel padding, not `.pad(0.18)`: a ratio pad scales with the route, so the
       twenty-mile leg to LGA bought itself four miles of empty margin on every
       side and the whole thing sat small in the middle of the card. The pad is
       the room the chips need to not hang off the edge, and it is the same
       number of pixels at every distance (see chipPad below for the sideways
       half, which is measured off the chips rather than assumed).

       maxZoom only bites on a route with no extent to fit, one stop, which is
       the terminal alone when nobody's address is on file. Without the back-off
       fitBounds runs to street level and lands on an unrecognisable patch of
       kerb; with more than one point the fit itself is the limit and is allowed
       to go as close as the stops permit. */
    // Mutable, because the road is not the straight line: it bows around water and
    // out to the bridge, and a frame fitted to the two ends cuts the middle of the
    // drive off the card. The recenter button is a thunk for this exact reason.
    let fitB = L.latLngBounds(pts);
    /* Sideways, the pad is half the widest chip, not a flat 32. A chip is centred
       on its dot, so 32px of room only holds one 64px wide, and "✈ Terminal B" is
       90. A 1153px desktop map never showed it because the route runs down the
       middle there; a 310px phone map fits width-first and put both end chips
       straight through the edge. Floor 32 (the old value, for a map with no chips
       drawn yet), ceiling 72 so one long address cannot eat the route. */
    const chipPad = () => {
      const halves = [...el.querySelectorAll(".mchip")].map((c) => c.offsetWidth / 2);
      return Math.min(72, Math.max(32, Math.ceil(Math.max(0, ...halves))));
    };
    /* Vertically the pad is asymmetric, because a chip is always ABOVE its dot and
       never below it. A flat 32 was enough for a ride stop's chip (16px of leader
       plus the chip) and not for a station's, which rides up to 32px higher again -
       "✈ Terminal B" and the bus stop beside it were both cut off by the top edge.
       68 clears the tallest lift; the bottom keeps a plain 24, so the headroom does
       not cost the route the same margin twice. */
    const frame = () => map.fitBounds(fitB, {
      paddingTopLeft: [chipPad(), 68], paddingBottomRight: [chipPad(), 24],
      maxZoom: pts.length > 1 ? 17 : 13 });
    /* The day map's ladder, run on this map's marks. It does both jobs at once and
       is why this card no longer carries an `edgeChips` of its own: it anchors a
       chip near the frame edge to its dot (`.at-l` / `.at-r`, so "Newark Airport
       Rai…" is not cut to "ort Rai…") AND climbs each chip until it clears every
       chip already placed. The hand-rolled edge pass did only the first, which is
       why overlapping marks needed a stagger of magic numbers beside it.

       Re-run on every move, because both answers change with the frame. */
    const ladder = () => liftChips(map, marks);
    map.on("move zoom moveend zoomend", ladder);
    frame();
    ladder();
    // The card is drawn inside a container that is still laying out, so leaflet
    // measures zero and paints a grey box. One reflow, and the frame again after
    // it, a fit computed against a zero-width map is a fit onto nothing.
    setTimeout(() => {
      try { map.invalidateSize(); frame(); } catch { /* torn down already */ }
    }, 60);

    /* The real shape of the trip, once something knows it.

       `route` is a FETCHER rather than a hardcoded call to OSRM, because the two
       tabs ask different engines the same question: the road for a car, the
       timetable for a train. Either answers with `legs`, one leg for a drive,
       one per train, bus and walk for a transit trip, and the drawing below does
       not care which it got.

       A transit leg draws in the line's OWN colour, off the MTA's feed. That is
       the whole reason for naming the F: the yellow on the map is the yellow on
       the platform sign. The walks between them stay dashed, which is what dashed
       has meant on this map all along, these points in this order, no vehicle. */
    if (pts.length > 1 && route) {
      route(pts).then((geo) => {
        // The tab was switched, the stops were edited, or the day changed while this
        // was in flight, the map it belongs to is gone.
        if (rideMap !== map) return;
        const legs = geo && (geo.legs || (geo.line ? [{ pts: geo.line, transit: true }] : []));
        if (legs?.length) {
          if (line) map.removeLayer(line);
          line = null;
          let b = L.latLngBounds(pts);
          marks = marks.slice(0, n).concat(stationMarks(map, legs, pts));
          legs.forEach((lg) => {
            if (!lg.pts || lg.pts.length < 2) return;
            const poly = L.polyline(lg.pts, lg.transit
              ? { className: `mroute${lg.color ? " is-line" : ""}`, weight: 5, opacity: 0.95 }
              : { className: "mroute is-straight", weight: 3, opacity: 0.7, dashArray: "4 5" }
            ).addTo(map);
            // Leaflet's `color` sets the stroke PRESENTATION ATTRIBUTE, and
            // `.mroute { stroke: var(--accent) }` in map.css beats a presentation
            // attribute every time, so the colour goes in as a custom property the
            // stylesheet reads, not as leaflet's own option.
            if (lg.transit && lg.color) {
              const el2 = poly.getElement();
              if (el2) el2.style.setProperty("--tc", lg.color);
            }
            b = b.extend(poly.getBounds());
          });
          fitB = b;
          frame();
          ladder();
        }
        // Called even on nothing, so a caller waiting on an answer is told the
        // answer was "none" rather than left on a spinner for the rest of the day.
        onRoute(geo);
      });
    }
  }

  /* ── TRANSIT ────────────────────────────────────────────────────────────────
     Which trains, from the vault's own routing engine.

     The tab drew a straight dashed line for as long as it existed, on the honest
     grounds that nothing here could name a train. That is no longer true: MOTIS
     is self-hosted on this machine over the MTA's own GTFS, and `/trips/api/transit`
     proxies it. Proxied rather than called from the page, because the router
     listens on loopback and a guest on the shared link has no loopback to reach -
     and because a public router in the mirror's connect-src is a second host to
     trust. The mirror stays at 'self'.

     `arriveBy` is the whole point. The reader does not want the next train, they
     want the last one that still gets them to bag drop. */
  const transitCache = {};

  /* When you have to BE there, naive, the way the itinerary was typed. The proxy
     puts the zone on it, the browser must not, because a guest reading this from
     another country would stamp their own offset onto an American morning. */
  function bagDropISO(_t, sel) {
    const dep = absOf(sel.row.departure_time);
    if (dep == null) return "";
    const door = dep - airportLead(sel.row);
    const m = (((door % 1440) + 1440) % 1440);
    const two = (n) => (n < 10 ? "0" : "") + n;
    return `${absDate(door)}T${two(Math.floor(m / 60))}:${two(m % 60)}:00`;
  }

  /* Which of the offered itineraries the reader is looking at. Not persisted:
     the options are rebuilt from a timetable on every query, so a "2" remembered
     from yesterday would point at a different train today. It resets whenever the
     route changes, because a pick is a pick of THIS list. */
  let transitPick = 0, transitPickKey = "";

  function transitFetch(key, a, b, when) {
    if (transitCache[key] !== undefined) return Promise.resolve(transitCache[key]);
    return fetch("/trips/api/transit?from=" + a.join(",") + "&to=" + b.join(",")
      + "&arriveBy=1" + (when ? `&time=${encodeURIComponent(when)}` : ""))
      .then((r) => r.json())
      .then((j) => ({ its: j.itineraries || [], stale: j.stale_for || "", asked: j.asked_for || "" }))
      .catch(() => null)
      .then((res) => { transitCache[key] = res; return res; });
  }

  /* One routed leg, reduced to what the map draws. The station names and where they
     are come with it, so the map can mark the door you go in and the platform you
     come out at rather than ending a dashed walk in the middle of a block. */
  const mapLeg = (l) => ({
    pts: l.line_pts, color: l.color, transit: l.transit, line: l.line,
    from: l.from, to: l.to, from_pt: l.from_pt, to_pt: l.to_pt,
  });

  // Minutes-past-midnight out of a "YYYY-MM-DDTHH:MM:SS" stamp, and the stamp for a
  // given minute count on (or before) that date. `back` is the midnight wrap: a
  // departure LATER in the day than the arrival it has to make is last night's
  // train, so the date steps back a day rather than claiming you leave after you
  // land. UTC arithmetic on a date-only string, so no local zone can shift the day.
  const isoMin = (iso) => Number(iso.slice(11, 13)) * 60 + Number(iso.slice(14, 16));
  function isoAt(iso, min) {
    const two = (n) => (n < 10 ? "0" : "") + n;
    const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
    if (min > isoMin(iso)) d.setUTCDate(d.getUTCDate() - 1);
    return `${d.toISOString().slice(0, 10)}T${two(Math.floor(min / 60))}:${two(min % 60)}:00`;
  }

  /* A transit trip with a stop in the middle is a SEQUENCE of transit trips.

     The router takes one origin and one destination, there is no via, so a route
     through somebody's door is asked for as one query per hop rather than faked by
     routing the two ends and drawing a straight line past the middle, which is what
     enabling the stop button alone would have done: a pin the route ignores.

     Asked BACKWARDS, because the only fixed time on the whole trip is the last
     one. The final hop has to land by bag drop; every earlier hop has to land in
     time for the hop after it. Asking forwards would need a departure time nobody
     has, the reader knows when they must arrive, never when they must leave, which
     is the reason `arriveBy` exists at all.

     No picker on a chained trip. Three alternatives per hop over three hops is
     twenty-seven itineraries, which is not a choice, it is a menu, so each hop
     takes the router's best and the whole thing renders as the one route it is. */
  function transitChain(_t, _sel, pts, when) {
    const segs = [];
    // The backwards loop as a recursive step: each hop waits on the one after it.
    // Resolves false when a hop has no answer (the whole chain is then null).
    const step = (i, arrive) => {
      if (i < 0) return Promise.resolve(true);
      const a = pts[i], b = pts[i + 1];
      return transitFetch(`${a.join(",")}|${b.join(",")}|${arrive}`, a, b, arrive).then((raw) => {
        if (!raw?.its.length) return false;
        const it = raw.its[0];
        segs.unshift({ it: it, stale: raw.stale, asked: raw.asked });
        if (it.start_min == null) return true;   // an unscheduled hop cannot time the one before it
        return step(i - 1, isoAt(arrive, it.start_min));
      });
    };
    return step(pts.length - 2, when).then((ok) => (ok ? chainDone(segs) : null));
  }
  function chainDone(segs) {
    if (!segs.length) return null;
    const legs = segs.reduce((all, s) => all.concat(s.it.legs), []);
    // The sum of the hops, not end-minus-start: the gap between two hops is however
    // long the reader chooses to stand in somebody's kitchen, and the router has no
    // opinion on it. This is travel time, which is the number the tab is asked for.
    const dur = segs.reduce((n, s) => n + (s.it.dur || 0), 0);
    const stale = segs.map((x) => x.stale).filter(Boolean)[0] || "";
    const it = { legs: legs, dur: dur,
                 start_min: segs[0].it.start_min, end_min: segs[segs.length - 1].it.end_min,
                 transfers: Math.max(0, legs.filter((l) => l.transit).length - 1) };
    return {
      legs: legs.map(mapLeg), dur: dur, start_min: it.start_min,
      its: [it], pick: 0, stale: stale,
      asked: segs.map((x) => x.asked).filter(Boolean)[0] || "",
    };
  }

  function transitPlan(t, sel, pts) {
    const when = bagDropISO(t, sel);
    if (pts.length > 2) return transitChain(t, sel, pts, when);
    const a = pts[0], b = pts[pts.length - 1];
    const key = `${a.join(",")}|${b.join(",")}|${when}`;
    if (key !== transitPickKey) { transitPickKey = key; transitPick = 0; }
    return transitFetch(key, a, b, when).then((raw) => {
      if (!raw?.its.length) return null;
      const i = Math.min(transitPick, raw.its.length - 1);
      const it = raw.its[i];
      return {
        legs: it.legs.map(mapLeg),
        dur: it.dur, start_min: it.start_min, its: raw.its, pick: i,
        stale: raw.stale, asked: raw.asked,
      };
    });
  }

  /* The itineraries as rows: the lines you board, in order, in their own colours,
     with the clock and the transfer count.

     Every time here is minutes-past-midnight computed server-side in the airport's
     zone, run through the same T.fmtClock as every other clock on the card, so a
     train time cannot disagree with the bag-drop time above it. */
  function transitHTML(geo) {
    if (!geo || !(geo.its || []).length) {
      return `<div class="hub-infocard-fine">no train or bus times for that morning —`
        + ` the dashed line is the shape of the trip, not a schedule</div>`;
    }
    // Every option is a button. The map draws ONE itinerary, so which one is the
    // reader's call, the fastest is not the one you want if it means a transfer
    // you know is a long walk, and the router cannot know that.
    const rows = geo.its.slice(0, 3).map((it, n) => {
      const hops = it.legs.filter((l) => l.transit);
      const chips = hops.map((l) => `<b class="tline"${l.color ? ` style="--tc:${esc(l.color)}"` : ""}>${
        esc(l.line || (l.mode || "").toLowerCase().replace(/_/g, " "))}</b>`)
        .join(`<i class="tsep">→</i>`) || `<b class="tline">walk</b>`;
      const first = hops[0];
      // How long the trip takes is the number that decides between these rows, so
      // it is the number in the corner. The clock window still ships, it is how
      // you know whether you can finish your coffee, but it reads underneath as
      // "42 min, 3:00 to 3:42", not as two stamps you have to subtract yourself.
      // Clock times off a timetable that does not cover the asked day are for the
      // wrong morning, so they are not shown as times at all. The DURATION still is:
      // how long the route takes is the thing that barely moves between comparable
      // days, and it is the number the reader came for. Blank departure, real length.
      const clock = geo.stale
        ? `<span class="transit-clock is-unsched">not scheduled yet</span>`
        : it.start_min == null || it.end_min == null ? ""
        : `<span class="transit-clock">${esc(T.fmtClock(it.start_min))}<i>→</i>${
            esc(T.fmtClock(it.end_min))}</span>`;
      const rest = esc((it.transfers ? `${it.transfers} transfer${it.transfers > 1 ? "s" : ""}`
                                     : "direct")
        + (first?.from ? ` · from ${first.from.toLowerCase()}` : ""));
      return `<button type="button" class="transit-it${n === geo.pick ? " is-on" : ""}"
        data-pick="${n}" aria-pressed="${n === geo.pick ? "true" : "false"}">
        <span class="transit-lines">${chips}</span>
        <span class="transit-dur">${esc(Math.round((it.dur || 0) / 60))} min</span>
        <span class="transit-sub">${clock}${clock ? "<i>·</i>" : ""}${rest}</span>
      </button>`;
    }).join("");
    /* A stale schedule is said ONCE, by the rows themselves.

       Every row already reads "not scheduled yet" where its departure clock would
       be, and the pill above the list says "no timetable yet" with the full reason
       on its tooltip. A third statement of the same fact, in red, three lines long,
       under a list that is already saying it, is the card shouting (Sam
       2026-08-31: "it already says not scheduled yet, so I don't need this massive
       block of text"). The failure mode this guarded against, a plausible set of
       trains silently standing in for the wrong day, is covered: nothing on a
       stale answer renders a departure time at all, on the rows or the pill. */
    return rows + (geo.stale ? ""
      : `<div class="hub-infocard-fine">shortest trips that still reach bag drop in time</div>`);
  }

  /* Two levels of redraw, and the difference between them is where the caret is.

     `paint` is the links and the map, which is everything a tab click changes.
     `rebuild` also replaces the stop rows, which is what a chain toggle or an
     add/remove needs and what an EDIT must not do, re-rendering the row you are
     typing in takes the focus and the half-typed value with it. */
  function bindGettingThere(root, t, sel) {
    const card = root.querySelector("[data-ridecard]");
    if (!card) return;
    const out = card.querySelector("[data-rideout]");
    const host = card.querySelector("[data-ridestops]");
    const box = card.querySelector("[data-ridechain]");
    // The box keeps its tick while a solo tab is open, switching back to the car
    // must find the chain exactly as it was left, not silently unticked.
    const chained = () => !!(box?.checked) && !soloRide();
    let seq = 0;   // a slow geocode must not land on top of a newer one

    /* The leave-by clock is stamped twice: the straight-line estimate when the card
       draws, then the measured one the moment the router answers. Stamped IN PLACE
       rather than re-rendering the head, so a time that arrives 300ms later does not
       take the tab row and the stop rows with it.

       Transit gets no second stamp. OSRM has no transit graph, so asking it for a
       train and printing the answer as a leave-by would be a driving time wearing a
       train's label, worse than the estimate it replaced. */
    const stampLeave = (plan, geo, isT) => {
      const host = card.querySelector("[data-ridepillhost]");
      if (!host) return;
      // Transit never shows the estimate. The estimate is driveMin, a straight
      // line times a road factor, which is a car's twenty minutes standing in for
      // a train's eighty, and printing it under a tab labelled Transit would be a
      // wrong time that looks exactly like a right one. It waits, then it is
      // timetabled, or it says there is nothing.
      // A transit leave-by is the itinerary's OWN departure, not bag drop minus the
      // journey. The two are not the same number: a train that gets you there
      // twenty minutes early leaves twenty minutes earlier than the subtraction
      // says, and a pill that disagreed with the first row of the list under it
      // would be the card arguing with itself. Driving keeps the subtraction,
      // because a car leaves when you leave.
      // A STALE answer must not become a time. This is the whole reason the proxy
      // flags it: past the end of its timetable the router does not answer empty,
      // it answers with the last day it has, so "leave by 11:58p" for a 6:30a
      // flight was not a routing result at all, it was the end of the published
      // schedule wearing a leave-by's clothes. The warning under the map said so
      // and the pill said otherwise, and the pill is the thing that gets read.
      const l = (isT && (!geo || geo.stale)) ? null
        : (isT
            ? (geo.start_min == null ? null
               : { clock: T.fmtClock(geo.start_min), mins: Math.round((geo.dur || 0) / 60), measured: true })
            : leaveBy(t, sel, plan.placed, geo ? geo.dur : null));
      setHTML(host, l ? leavePill(l, isT ? "transit" : "road")
        : (isT
            ? `<span class="hub-pill hub-pill--dashed ridepill" title="${esc(geo?.stale
                ? "the bus timetable for this date is not published yet — the times below are "
                  + geo.stale + "'s, shown as the shape of the trip"
                : "the router returned nothing for this morning")}">${
                // No departure clock, but the LENGTH of the route still ships, it is
                // what he asked the tab for, and it is the part a week's difference
                // in the timetable barely moves.
                geo?.stale
                  ? `no timetable yet${geo.dur ? ` · ~${Math.round(geo.dur / 60)} min` : ""}`
                  : "no train times"}</span>`
            : ""));
    };
    const paint = () => {
      const mode = rideMode(ridePref().mode);
      const plan = ridePlan(t, sel, chained());
      const isT = mode.k === "transit";
      const chainRow = card.querySelector("[data-ridechainrow]");
      if (chainRow) chainRow.hidden = !!mode.solo;
      setHTML(out, rideLinksHTML(t, sel, mode, plan));
      if (isT) {
        // Nothing to route FROM stops the answer before it starts: the map holds
        // the terminal and nothing else, renderRideMap never asks the router, and
        // a "working out the trains…" that waits on a question nobody asked spins
        // for as long as the card is open. Say why instead, the note under the
        // links names whose address is missing.
        const host = card.querySelector("[data-ridepillhost]");
        const th0 = card.querySelector("[data-transit]");
        const ready = plan.placed.length > 1;
        if (host) setHTML(host, ready
          ? `<span class="hub-pill hub-pill--dashed ridepill">working out the trains…</span>`
          : `<span class="hub-pill hub-pill--dashed ridepill" title="no starting address on file, so there is nothing`
            + ` to route from">no start address</span>`);
        if (!ready && th0) setHTML(th0, `<div class="hub-infocard-fine">no address to leave from,`
          + ` so there are no trains to work out</div>`);
      } else {
        stampLeave(plan, null, false);
      }
      renderRideMap(card.querySelector("[data-ridemap]"), plan.placed,
        isT ? ((pts) => transitPlan(t, sel, pts)) : ((pts) => osrmRoute("driving", pts)),
        (geo) => {
          stampLeave(plan, geo, isT);
          const th = card.querySelector("[data-transit]");
          if (isT && th) setHTML(th, transitHTML(geo));
        });
    };
    const rebuild = () => {
      if (host) { setHTML(host, rideStopsHTML(ridePlan(t, sel, chained()))); bindStops(); }
      paint();
    };

    /* Picking a different train. Delegated off the links block because that block
       is replaced wholesale on every paint, so a listener bound to a row would be
       thrown away by the redraw its own click causes. */
    out.addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-pick]");
      if (!b || !out.contains(b)) return;
      ev.preventDefault();
      const n = parseInt(b.getAttribute("data-pick"), 10);
      if (Number.isNaN(n) || n === transitPick) return;
      transitPick = n;
      paint();
    });

    /* An edited row becomes a POINT before it becomes a link. AddrCombo has no
       pick callback, it sets .value and re-fires `input`, so the commit does its
       own lookup against the same endpoint and takes the first place, which the
       API now returns with coordinates attached (`places`) rather than as a bare
       string. One request per committed edit, and AddrCombo is untouched.

       A line nothing can place keeps its text and gets marked. Reverting it would
       throw away what the reader typed to tell them something they cannot see; the
       marked row says "no point for this" and the links are built from the stops
       that have one. */
    function commit(i, inp) {
      const q = inp.value.trim();
      const stops = ridePlan(t, sel, chained()).stops.slice();
      if (!stops[i]) return;
      if (q === String(stops[i].addr || "")) return;   // blurred without changing anything
      // `off` rides along through every rewrite below: correcting the spelling of an
      // address you are not stopping at today does not mean you are stopping at it.
      const off = !!stops[i].off;
      if (!q) {
        stops[i] = { who: "", addr: "", lat: null, lng: null, off: off };
        inp.classList.add("is-nogeo");
        savePlan(sel, chained(), stops); paint(); return;
      }
      const mine = ++seq;
      inp.classList.add("is-busy");
      let hit = null;
      return fetch(`/trips/api/prefs/address-search?q=${encodeURIComponent(q)}`)
        .then((r) => r.json())
        .then((j) => { hit = (j.places || [])[0] || null; })
        .catch(() => { /* offline, falls through to the unplaced branch below */ })
        .then(() => {
          if (mine !== seq) return;
          inp.classList.remove("is-busy");
          inp.classList.toggle("is-nogeo", !hit);
          if (hit) inp.value = hit.address;
          // The name goes with the address it belonged to. Retyping Jasmine's row to a
          // different address does not make that address Jasmine's house.
          stops[i] = hit
            ? { who: "", addr: hit.address, lat: hit.lat, lng: hit.lng, off: off }
            : { who: "", addr: q, lat: null, lng: null, off: off };
          savePlan(sel, chained(), stops);
          paint();
        });
    }

    function bindStops() {
      if (!host) return;
      host.querySelectorAll("[data-stop]").forEach((inp) => {
        if (window.AddrCombo) AddrCombo.attach(inp);
        inp.onchange = () => commit(Number(inp.dataset.stop), inp);
        // Enter commits by leaving the field, which is also what a pick from the
        // dropdown does. AddrCombo swallows Enter only while its list is open.
        inp.onkeydown = (ev) => { if (ev.key === "Enter") { ev.preventDefault(); inp.blur(); } };
      });
      /* "Start from where I am." The card's autofill is an address on file, which
         is a good guess and only a guess, the morning of a flight is exactly when
         somebody woke up somewhere else, and on the way home it is the stay you are
         checking out of. The browser knows better than the trip does, so one tap
         asks it. The point is written as a stop like any other: it draws on the map,
         it routes, and it carries the leave-by. It needs a secure context (https, or
         localhost on the Hub), so a refusal is reported on the button rather than
         swallowed, the row it would have filled is still there to type into. */
      host.querySelectorAll("[data-stoploc]").forEach((b) => {
        b.onclick = () => {
          if (!navigator.geolocation) {
            b.classList.add("is-nogeo");
            b.title = "this browser will not share a location — type the address instead";
            return;
          }
          b.classList.add("is-busy");
          navigator.geolocation.getCurrentPosition((pos) => {
            const stops = ridePlan(t, sel, chained()).stops.slice();
            const i = Number(b.dataset.stoploc);
            if (!stops[i]) return;
            stops[i] = { who: "", addr: "where I am now", lat: pos.coords.latitude,
              lng: pos.coords.longitude, cur: true, at: Date.now(), off: !!stops[i].off };
            savePlan(sel, chained(), stops);
            rebuild();
          }, (err) => {
            b.classList.remove("is-busy");
            b.classList.add("is-nogeo");
            b.title = err && err.code === 1
              ? "location is blocked for this page — allow it in the browser, or type the address"
              : "no location just now — type the address instead";
          }, { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
        };
      });
      const add = host.querySelector("[data-stopadd]");
      if (add) add.onclick = () => {
        const stops = ridePlan(t, sel, chained()).stops.slice();
        // Always BEFORE the destination: a stop added after the terminal is not a
        // stop on the way, and on a list of one it becomes the missing start.
        stops.splice(Math.max(0, stops.length - 1), 0, blankStop());
        savePlan(sel, chained(), stops);
        rebuild();
        const rows = host.querySelectorAll("[data-stop]");
        const fresh = rows[Math.max(0, rows.length - 2)];
        if (fresh) fresh.focus();
      };
      /* Skipping a door, not deleting it. Somebody staying over at somebody else's
         place is the normal reason one pickup drops off a shared car, and it is
         true for one morning, so the row stays on the list with its address, one
         click from being back in the ride. Retyping an address you already had is
         what the × used to cost.

         An EMPTY row is the exception, because there is nothing to bring back: it
         is the blank the "+ add a stop" button just made, and removing it is the
         only thing the button could usefully mean there. */
      host.querySelectorAll("[data-stopoff]").forEach((b) => {
        b.onclick = () => {
          const stops = ridePlan(t, sel, chained()).stops.slice();
          const i = Number(b.dataset.stopoff), x = stops[i];
          if (!x) return;
          if (!x.off && !String(x.addr || x.who || "").trim()) stops.splice(i, 1);
          else stops[i] = Object.assign({}, x, { off: !x.off });
          savePlan(sel, chained(), stops);
          rebuild();
        };
      });
    }

    card.querySelectorAll("[data-ridemode]").forEach((b) => {
      b.onclick = () => {
        saveRidePref({ mode: b.dataset.ridemode });
        card.querySelectorAll("[data-ridemode]").forEach((x) =>
          { x.classList.toggle("is-on", x === b); });
        // rebuild, not paint: a solo tab holds a different stop list to the car's,
        // so the rows under the map are the wrong ones until they are redrawn.
        rebuild();
      };
    });
    // The chain changes how many doors the car stops at, so the stored plan for the
    // other state is a different route and this rebuilds from the autofill.
    if (box) box.onchange = () => { saveRidePref({ chain: box.checked }); rebuild(); };
    bindStops();
    paint();
  }

  /* The list of things that are nobody's decision and everybody's problem.

     Ticks live in the browser, per trip and per reader: nothing about whether you
     packed a charger belongs in the trip database, and seven guests ticking one
     shared row would each be wiping the others' list. */
  /* The key carries the LEG, not just the trip. The row ids are literals, checkin,
     bag, bp, id, and they are the same six literals on the way out and on the way
     home, so a trip-scoped key meant ticking the outbound list also ticked the
     return's. You would land back at the airport on the last morning and find a
     list claiming you had already checked in for a flight that does not open for
     another day. The counter added on top of it made that silent handoff loud: "6
     of 6" on a list nobody had touched.

     legKey is the same signature crewFlights merges on, so the two legs of one
     booking cannot collide and a re-read of the same leg still finds its ticks.
     Changing the key orphans whatever is already stored, which resolves to an
     unticked list, the safe direction, and a one-time cost on a surface that only
     ever describes one morning. */
  const DAYOF_KEY = (t, sel) => "trips.dayof." + t.id + "." + (viewerKey() || "me")
    + (sel?.row ? `.${legKey(sel.row)}` : "");
  function dayOfTicks(t, sel) {
    try { const v = JSON.parse(localStorage.getItem(DAYOF_KEY(t, sel)) || "[]"); return Array.isArray(v) ? v : []; }
    catch { return []; }   // private mode / corrupt value, an unticked list, never a thrown tab
  }
  function saveTick(t, sel, id, on) {
    const cur = dayOfTicks(t, sel).filter((x) => x !== id);
    if (on) cur.push(id);
    try { localStorage.setItem(DAYOF_KEY(t, sel), JSON.stringify(cur)); } catch { /* nicety, not a failure */ }
  }
  /* Split by WHEN: the night before you can still fix a bag that is over weight,
     on the way out you cannot and only the walk-out-the-door rows matter. */
  function dayOfChecklist(t, sel) {
    /* ponytail: plain items, no airline names, prices, fare branches or timers.
       The bag fee, the carrier and the confirmation number already print on the
       cards above this one, so a checkbox repeating them is furniture. */
    const night = [
      { id: "checkin", w: "Checked in" },
      { id: "bag", w: "Bags packed" },
      { id: "charge", w: "Phone charged" },
      { id: "fit", w: "Outfit picked" },
      { id: "pass", w: "Passport found" },
    ];
    const out = [
      { id: "bp", w: "Boarding pass in your wallet app" },
      { id: "shot", w: "Screenshot of your boarding pass email" },
      { id: "id", w: "ID in your pocket — passport if you're leaving the country" },
      { id: "ride", w: "Ride to the airport sorted" },
    ];
    const on = dayOfTicks(t, sel), all = night.concat(out);
    const done = all.filter((x) => on.indexOf(x.id) >= 0).length;
    const rows = (items) => `<ul class="hub-checklist dolist">${items.map((x) => `<li class="hub-checklist-item doitem">
      <label class="hub-checkbox-label"><input type="checkbox" data-tick="${esc(x.id)}"${
        on.indexOf(x.id) >= 0 ? " checked" : ""}> <span class="hub-checklist-text">${esc(x.w)}</span></label></li>`).join("")}</ul>`;
    // The count replaces "6 things", which said how long the list was and never
    // how much of it was left. It is re-stamped in place on every tick (listDayOf
    // binds it) rather than re-rendering the card, because a re-render on a
    // checkbox change moves the box out from under the cursor mid-click.
    return `<div class="hub-infocard dochecklist">
      <div class="hub-infocard-head tlcard-head"><span class="hub-infocard-t">Before you leave</span>
        <span class="hub-infocard-r"><span class="hub-count-badge" data-tickcount>${done} of ${all.length}</span></span></div>
      <div class="dogroup">the night before</div>${rows(night)}
      <div class="dogroup">on your way out</div>${rows(out)}
      <div class="hub-infocard-fine">ticks stay in this browser — nobody else on the trip sees them</div>
    </div>`;
  }

  function listDayOf(head, list) {
    const t = state.trip;
    const sel = dayOfSel();
    if (!sel) {
      setHTML(head, "");
      setHTML(list, `<div class="hub-empty-state focus-empty">${viewerFlightMissing(t)
        ? "your flight isn't on this board yet — forward the confirmation email to Sam and he'll add it"
        : "no flight on the board yet — the day-of read lands once a leg has a time on it"}</div>`);
      return;
    }
    const f = sel.row, d = daysAway(f.departure_time);
    const home = sel.g.leg === "return";
    const dateISO = T.parseStamp(f.departure_time, t.start_date)?.date;
    const route = [f.from_airport, f.to_airport].filter(Boolean).join(" → ");
    const dep = absOf(f.departure_time);
    // The headline number is how long you have, said the way anyone actually says
    // it. "0 days" is today and today is the whole point of the tab.
    const big = d == null ? "—" : d === 0 ? "today" : d === 1 ? "tomorrow" : d > 1 ? `${d} days` : "flown";
    setHTML(head, `
      <div class="hub-figure">
        <div class="hub-figure-fig">
          <span class="hub-figure-n">${esc(big)}</span>
          <span class="hub-figure-l">${esc((home ? "flying home · " : "game day · ") + dayLong(dateISO))}</span>
        </div>
        <div class="hub-figure-split">${esc([f.flight_num || f.airline, route,
          `wheels up ${T.fmtClock(((dep % 1440) + 1440) % 1440)}`,
          `at the airport by ${T.fmtClock((((dep - airportLead(f)) % 1440) + 1440) % 1440)}`]
          .filter(Boolean).join(" · "))}</div>
      </div>`);

    const me = readerMember(t);
    setHTML(list,
      // No "your flight" head (Sam 2026-10-12 mark): it stacked on top of the
      // Getting there title, and its carrier and locator are already on the pass.
      `<!-- One grid, not the pass in .legpair above a separate .tlgrid: two grids
           gave the flight card a row of its own and started the 5am reading cards
           underneath it. Here the pass spans two tracks and the reading cards flow
           up beside it (trips.css, THE DAY-OF ROW). -->
      <!-- Getting there leads, and takes the whole row. On the one morning this
           tab is for, the map is what you are looking at and the reads are what
           you check against it — not the other way round. -->
      <div class="tlgrid dayofgrid">${gettingThereHTML(t, sel)}${
        flightLegBlock(t, sel.g, f, me ? me.name : "")}${
        dayReadHTML(checkpointRead(t, sel))}${
        dayOfChecklist(t, sel)}</div>`);

    bindPanel(list, t);
    bindGettingThere(list, t, sel);
    // The counter is stamped in place rather than by re-rendering the card: a
    // re-render on a checkbox change replaces the input under the pointer, which
    // eats the second click of a double-tick and drops focus mid-keyboard pass.
    const boxes = list.querySelectorAll("[data-tick]"), cnt = list.querySelector("[data-tickcount]");
    const sync = () => {
      if (!cnt) return;
      let n = 0;
      boxes.forEach((b) => { if (b.checked) n++; });
      cnt.textContent = `${n} of ${boxes.length}`;
      cnt.classList.toggle("is-done", n === boxes.length && boxes.length > 0);
    };
    boxes.forEach((b) => {
      b.onchange = () => { saveTick(t, sel, b.dataset.tick, b.checked); sync(); };
    });
    sync();
  }


Object.assign(U, { addRecenter, DAYOF_KEY, listDayOf });
})();
