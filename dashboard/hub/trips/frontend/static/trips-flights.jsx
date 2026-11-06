/* hub · trips page, flights part (2026-10-13): React port of trips.js lines 4275-4981 (badges, the pick, the
   flights board, the car bucket). Near-verbatim plain functions inside an IIFE, assigned onto window.TripsUI;
   see trips-core.jsx for the shape. Names other parts own come through U.fwd / U.NAME at call time. */
(() => {
const U = window.TripsUI;
const { esc, setHTML, toast, state, T, FC, $, money, points, pointsCell, isGuest, isDead, isCommitted, isOpen,
  rowCost, isCar, busOf, carPickup, carDropoff, myFlights, isSettled } = U;
const { renderFocus, readerLegGroups, routeText, dayShort, stampShort, whenCell, partySize, perPersonNight, trim1,
  airlineFacts, bagSurcharge, allIn, cheapestBy, crewArrivals, feeTableHTML, flightResearchHTML, stampOrBlank, flightGapHTML,
  crewFlightsHTML, flightPanel, daysAway, countdown, stayBlock, stayFacts, stayList, bindPanel, repaint,
  groupHTML, renderContext, gapList } = U.fwd("renderFocus", "readerLegGroups", "routeText", "dayShort",
  "stampShort", "whenCell", "partySize", "perPersonNight", "trim1", "airlineFacts", "bagSurcharge", "allIn",
  "cheapestBy", "crewArrivals", "feeTableHTML", "flightResearchHTML", "stampOrBlank", "flightGapHTML", "crewFlightsHTML", "flightPanel",
  "daysAway", "countdown", "stayBlock", "stayFacts", "stayList", "bindPanel", "repaint", "groupHTML",
  "renderContext", "gapList");

  // ── BADGES, derived from the row, never typed in ────────────────────────────
  // Every row of a carrier carries that carrier's badges, and "cheapest" moves the
  // moment you tick a bag. Hand-written labels drift as soon as the data does.
  // Each badge carries its own explanation on hover (native title, no tooltip JS).
  const TIP = {
    cheapFare: "Lowest all-in price still on the table for this leg, counting the bags ticked above.",
    freeChanges: "This airline moves the flight later at no charge — you pay any fare difference and nothing else. The others charge a change fee, or won't change a Basic Economy ticket at all.",
    basicRisk: "This carrier's cheapest fares are usually Basic Economy: one personal item, no overhead carry-on, no seat choice, no changes. Tick carry-on above to price the worst case.",
    redEye: "Lands the next day. Whatever the fare saves, it takes out of the following morning.",
    cheapStay: "Lowest all-in total still on the table.",
    bestPP: "Lowest cost per person per night at the party size set above — not the same thing as the lowest total.",
    mostBeds: "More real beds than any other option, which is what decides whether anyone is on a couch.",
    mostBaths: "More bathrooms than any other option on the board.",
    freeParking: "Parking is included, so a rental car costs nothing extra to keep overnight.",
  };
  const tagHTML = (g) => `<span class="ltag hub-pill is-${g.tone === "bad" ? "alert" : g.tone}"${g.tip ? ` title="${esc(g.tip)}"` : ""}>${esc(g.t)}</span>`;
  const tagsHTML = (list) => list.length ? `<span class="ltags">${list.map(tagHTML).join("")}</span>` : "";

  function isRedEye(f) {
    const d = T.parseStamp(f.departure_time, state.trip?.start_date);
    const a = T.parseStamp(f.arrival_time, state.trip?.start_date);
    if (!d || !a || d.minutes == null || a.minutes == null) return false;
    return a.date > d.date || (d.minutes >= 21 * 60 && a.minutes < d.minutes);
  }
  function flightTags(f, best) {
    const a = airlineFacts(f.airline), out = [];
    // "cheapest" is a shopping badge, it only means anything next to the prices
    // it is ranking, and a guest is not shown those.
    if (best && f === best && !isGuest()) out.push({ t: "cheapest", tone: "good", tip: TIP.cheapFare });
    if (a.freeChanges) out.push({ t: "free changes", tone: "good", tip: TIP.freeChanges });
    if (a.carryOn) out.push({ t: `carry-on $${a.carryOn}`, tone: "warn", tip: "This carrier charges for a carry-on on every fare, not only the cheap ones." });
    else if (a.basicRisk) out.push(state.bags.carry
      ? { t: `+$${U.CARRY_IF_BASIC} if basic`, tone: "warn", tip: `Worst case: if this fare is Basic Economy, a carry-on costs the $${a.checked} bag fee plus a $25 gate charge. Knock it off if the fare turns out to be Main Cabin.` }
      : { t: "basic economy risk", tone: "warn", tip: TIP.basicRisk });
    if (isRedEye(f)) out.push({ t: "red-eye", tone: "warn", tip: TIP.redEye });
    return out;
  }
  // The stay's equivalent of the fare badges. Same rule: every one of these is a
  // fact already in the row, restated as the reason you'd pick it.
  function stayCtx(rows) {
    const live = rows.filter((r) => !isDead(r));
    const maxOf = (k) => { const v = live.filter((r) => r[k] != null).map((r) => r[k]); return v.length ? Math.max.apply(null, v) : null; };
    return {
      party: partySize(),
      best: cheapestBy(live, rowCost),
      // a baseline that can't hold the party isn't a baseline, the true cheapest
      // keeps its badge, but every delta is measured against what you could book
      bestFit: cheapestBy(live.filter(fitsParty), rowCost) || cheapestBy(live, rowCost),
      bestPP: cheapestBy(live.filter(fitsParty), (h) => perPersonNight(h) || 0) || cheapestBy(live, (h) => perPersonNight(h) || 0),
      // the MAX, not one winning row, three stays with five beds each all tie
      maxBeds: maxOf("beds"), maxBaths: maxOf("baths"),
    };
  }
  function housingTags(h, c) {
    const out = [];
    if (h === c.best) out.push({ t: "cheapest", tone: "good", tip: TIP.cheapStay });
    if (h === c.bestPP && h !== c.best) out.push({ t: "best per person", tone: "good", tip: TIP.bestPP });
    if (h.guests != null && h.guests < c.party) out.push({ t: `won't fit ${c.party}`, tone: "bad", tip: `The listing caps at ${h.guests}. At ${c.party} this is not an option, whatever it costs.` });
    else if (h.guests != null && h.guests > c.party) out.push({ t: `room for ${h.guests}`, tone: "good", tip: `Sleeps ${h.guests}, so it holds ${h.guests - c.party} more than you've set above.` });
    // A blank capacity is treated as eligible everywhere else in this panel, which
    // silently reads as "it fits". It isn't a pass, it's an unchecked field, the
    // row has to say so or an option gets compared on a number nobody confirmed.
    else if (h.guests == null) out.push({ t: "capacity unchecked", tone: "warn", tip: `Nothing on this row says how many it sleeps, so it's being priced at ${c.party} on an assumption. Open the listing before you compare it.` });
    if (h.beds != null && h.beds === c.maxBeds) out.push({ t: "most real beds", tone: "good", tip: TIP.mostBeds });
    if (h.baths != null && h.baths === c.maxBaths) out.push({ t: "most baths", tone: "good", tip: TIP.mostBaths });
    else if (h.baths != null && c.party / h.baths > 3) out.push({ t: `${trim1(c.party / h.baths)} per bath`, tone: "warn", tip: `${c.party} people to ${trim1(h.baths)} bathroom${h.baths === 1 ? "" : "s"}. Fine most days, ugly on an early start.` });
    if (/free/i.test(h.parking || "")) out.push({ t: "free parking", tone: "good", tip: TIP.freeParking + (h.parking ? ` — ${h.parking}.` : "") });
    else if (/^\s*none\s*$/i.test(h.parking || "")) out.push({ t: "no parking", tone: "warn", tip: "No parking with the listing. A rental car means paying for a spot or hunting the street." });
    AMENITIES.forEach((a) => { if (h[a.k] === 0) out.push({ t: `no ${a.l}`, tone: "bad", tip: a.tip }); });
    return out;
  }
  // The two things the crew asked about by name. Red only on a hard 0, the row was
  // read against the listing's own full amenity list and the thing is not on it.
  // null is left silent on purpose: an unchecked row saying "no hot tub" is a
  // false statement, not a missing one, and this board is what the call gets made on.
  // Pool was dropped 2026-08-11: not a criterion, and no listing in the metro has one,
  // so the chip fired on every row and carried no signal. The `pool` column stays in
  // the DB, the reads are done and cheap to keep.
  const AMENITIES = [
    { k: "pool_table", l: "pool table", tip: "No pool table on the listing's amenity list. A listing can say \"game room\" in its title and still not declare a table — this reads the amenity list, which is what Airbnb's own filters use." },
    { k: "hot_tub", l: "hot tub", tip: "No hot tub on the listing's amenity list." },
  ];
  // The artifact's "what it buys" column, derived instead of written: what this
  // option has more of than the cheapest one, and what the difference costs.
  function whatItBuys(h, c) {
    const base = c.bestFit;
    if (!base) return "";
    if (h === base) return "the floor — everything else is measured against this";
    if (!fitsParty(h)) return "";          // the won't-fit badge is the whole story
    const g = [], more = (k, one, many) => {
      if (h[k] == null || base[k] == null || h[k] <= base[k]) return;
      const d = h[k] - base[k];
      g.push(`${trim1(d)} more ${d === 1 ? one : many}`);
    };
    more("baths", "bath", "baths"); more("beds", "bed", "beds"); more("bedrooms", "bedroom", "bedrooms");
    if (h.guests != null && base.guests != null && h.guests > base.guests) g.push(`room for ${h.guests - base.guests} more`);
    const d = rowCost(h) - rowCost(base);
    if (!g.length) return d > 0 ? "nothing the fields show" : "";
    return g.join(", ") + (d > 0 ? ` for ${money(d)}` : d < 0 ? ` and ${money(-d)} less` : "");
  }

  // col: { l: header, v: row -> cell html, s: row -> sort key, num: right-align }
  const LOGI_COLS = {
    housing: [
      { l: "stay", v: (h) => `${esc(h.name || h.address || "stay")}${h.area ? `<span class="lsub">${esc(h.area)}</span>` : ""}`, s: (h) => (h.name || h.address || "").toLowerCase() },
      { l: "cash", num: 1, v: (h) => money(h.total_cost), s: (h) => rowCost(h) },
      { l: "points", num: 1, s: (h) => Number(h.points_total) || 0, v: pointsCell },
      { l: "per night", num: 1, v: (h) => money(perPersonNight(h)), s: (h) => perPersonNight(h) || 0 },
      { l: "fits", num: 1, v: (h) => h.guests != null ? h.guests : "—", s: (h) => h.guests || 0 },
      { l: "bed / bath", num: 1, v: (h) => h.beds == null && h.baths == null ? "—" : `${h.beds != null ? h.beds : "?"} / ${h.baths != null ? trim1(h.baths) : "?"}`, s: (h) => (h.beds || 0) * 10 + (h.baths || 0) },
    ],
    flights: [
      { l: "departs → arrives", v: whenCell, s: (f) => String(f.departure_time || "") },
      { l: "carrier", v: (f) => esc([f.airline, f.flight_num].filter((x) => x && x !== "—").join(" ") || "—"), s: (f) => String(f.airline || "") },
      { l: "route", v: (f) => esc(routeText(f.from_airport, f.to_airport)), s: (f) => String(f.from_airport || "") },
      {
        l: "cash", num: 1, s: (f) => allIn(f),
        v: (f) => {
          const add = bagSurcharge(f);
          if (!rowCost(f)) return `<span class="lfree" title="the far half of a roundtrip ticket — the price sits on the other row">same ticket</span>`;
          return money(allIn(f)) + (add ? `<span class="lsub">${money(rowCost(f))} + ${money(add)} bags</span>` : "");
        },
      },
      // an award seat's price is its points, and it belongs on the board next to
      // the cash fares it is competing with, not buried in the row's notes
      { l: "points", num: 1, s: (f) => Number(f.points_total) || 0, v: pointsCell },
    ],
    // A car is a decision with a clock on it: it has to be waiting when you land
    // and back at the counter before you fly out, and it has to seat everyone.
    // Those three facts are the columns, the same set serves the counter board
    // and the Turo board, because a Turo IS a rental with a different host.
    carrental: [
      { l: "car", v: (x) => `${esc(x.description || x.type || "car")}${
          x.location || x.departure ? `<span class="lsub">${esc(x.location || x.departure)}</span>` : ""}`,
        s: (x) => (x.description || "").toLowerCase() },
      { l: "pick up → drop off", v: rentalWhenCell, s: (x) => carPickup(x) },
      { l: "fits", num: 1, v: seatsCell, s: (x) => x.seats || 0 },
      {
        l: "all-in", num: 1, s: (x) => rowCost(x),
        v: (x) => rowCost(x) ? `${money(rowCost(x))}<span class="lsub">${money(rowCost(x) / partySize())} each</span>`
          : x.points_total != null && x.points_total !== "" ? points(x.points_total, x.points_program) : "—",
      },
    ],
    // Deliberately shape-agnostic: this board holds a $2.75 subway ride, a
    // booked intercity bus and "Karim drives" at the same time, so every column
    // has to survive its neighbours being blank. Nothing here is required.
    transportation: [
      { l: "what", v: (x) => esc(x.description || x.type || "transport"), s: (x) => (x.description || "").toLowerCase() },
      { l: "type", v: (x) => esc(x.type || "—"), s: (x) => String(x.type || "") },
      { l: "from → to", v: (x) => esc([x.departure || "—", x.arrival || "—"].join(" → ")), s: (x) => String(x.departure || "") },
      { l: "when", v: (x) => esc([x.scheduled_date ? dayShort(x.scheduled_date) : "", T.fmtClockText(x.scheduled_time)].filter(Boolean).join(" ") || "—"),
        s: (x) => `${String(x.scheduled_date || "")} ${String(x.scheduled_time || "")}` },
      { l: "cost", num: 1, v: (x) => money(x.cost), s: (x) => rowCost(x) },
      { l: "points", num: 1, s: (x) => Number(x.points_total) || 0, v: pointsCell },
    ],
  };

  // "Sep 10 9:30a → Sep 14 2:15p" over "4 days". Same two-line shape as the fare
  // cell, because it answers the same question about a different row.
  function rentalWhenCell(x) {
    const start = state.trip?.start_date;
    const p = T.parseStamp(carPickup(x), start), d = T.parseStamp(carDropoff(x), start);
    if (!p && !d) return "—";
    const side = (s) => s ? dayShort(s.date) + (s.minutes != null ? ` ${T.fmtClock(s.minutes)}` : "") : "?";
    const days = p && d ? Math.round((Date.parse(`${d.date}T00:00:00Z`) - Date.parse(`${p.date}T00:00:00Z`)) / 86400000) : null;
    return `<span class="lwhen">${esc(`${side(p)} → ${side(d)}`)}</span>`
      + (days ? `<span class="lsub">${days} day${days === 1 ? "" : "s"}</span>` : "");
  }
  // How many people the option carries WITH their bags, not how many seatbelts
  // it has. Two five-seat cars is ten belts and eight usable, and a Suburban with
  // four days of luggage behind row three is seven, not eight. Seatbelt counts are
  // what put a 15-passenger van on a board for a party of seven.
  // Only interesting against the party size, so print both when they disagree. An
  // unstated capacity is unknown, never "fine".
  function seatsCell(x) {
    if (x.seats == null || x.seats === "") return "—";
    const n = Number(x.seats), p = partySize();
    return n + (n < p ? `<span class="lsub">party of ${p}</span>` : "");
  }
  const fitsSeats = (x) => x.seats == null || x.seats === "" || Number(x.seats) >= partySize();

  // The window the car has to bracket: you collect it after you land and hand it
  // back before you fly out. Both ends come off the flights you have actually
  // PICKED, so every flag below moves the moment the fare pick moves.
  // Minutes-since-epoch, so a pickup the morning after landing still compares.
  const stampMins = (p) => p ? Date.parse(`${p.date}T00:00:00Z`) / 60000 + (p.minutes || 0) : null;
  function groundWindow() {
    const t = state.trip || {};
    const legs = flightLegs(t).filter((g) => g.live);
    const pick = (leg) => {
      const g = legs.filter((x) => x.leg === leg)[0];
      return g ? picked(`flights:${leg}`, g.rows.filter((r) => !isDead(r))) : null;
    };
    // a roundtrip row carries the outbound only, it knows when you land, not
    // when you fly home, so that end stays null rather than guessed
    const out = pick("outbound") || pick("roundtrip"), back = pick("return");
    // EVERY arrival, not only his. A minivan collected at 2pm is not "5h after
    // landing" because Sam landed at 8:40, it is 90 minutes after the flight
    // that is actually fetching it, and that badge was crying wolf on the one car
    // the crew booked. rentalTags picks the arrival each pickup is answerable to.
    // The fly end goes the other way: the EARLIEST departure is the binding one,
    // because the car has to be back before the first person on it flies.
    const lands = crewArrivals(t).map((a) => a.at);
    const flys = (t.flights || []).filter((f) => !isDead(f) && (f.direction || "") === "return")
      .map((f) => stampMins(T.parseStamp(f.departure_time, t.start_date))).filter((m) => m != null);
    const own = out ? stampMins(T.parseStamp(out.arrival_time, t.start_date)) : null;
    const ownFly = back ? stampMins(T.parseStamp(back.departure_time, t.start_date)) : null;
    if (own != null && lands.indexOf(own) < 0) lands.push(own);
    if (ownFly != null && flys.indexOf(ownFly) < 0) flys.push(ownFly);
    return {
      lands: lands,
      land: lands.length ? Math.min.apply(null, lands) : null,
      fly: flys.length ? Math.min.apply(null, flys) : null,
      airport: out ? out.to_airport : "",
    };
  }
  const RENTAL_TIP = {
    cheapest: "Lowest all-in price still on the table across both car boards — the counter rentals and the Turo listings compete for the same slot.",
    early: "This car is booked before the first flight on the trip lands. Either the pickup is wrong or you are paying for hours the whole crew is in the air.",
    wait: "The counter opens well after the last flight before it clears baggage claim. That gap is time somebody spends at the airport with the bags.",
    late: "You are scheduled to hand the car back after your flight has already left. Move the drop-off earlier.",
    tight: "Under two hours between handing the car back and takeoff — the shuttle from the return lot plus bag drop plus security eats most of that.",
    covers: "Waiting when you land, returned before you fly out, and it seats everyone.",
  };
  const HRS = 60;
  function rentalTags(x, c) {
    const w = c.window, out = [], start = state.trip?.start_date;
    const p = stampMins(T.parseStamp(carPickup(x), start)), d = stampMins(T.parseStamp(carDropoff(x), start));
    const warn = [];
    if (x.seats != null && x.seats !== "" && Number(x.seats) < partySize()) {
      warn.push({ t: `fits ${x.seats} of ${partySize()}`, tone: "warn", tip: `This carries ${x.seats} people with their bags. There are ${partySize()} of you, so it is a second vehicle or a different car.` });
    }
    // The arrival this pickup is answerable to: the last one that still precedes
    // it (the flight that collects the car), falling back to the first arrival
    // when the pickup is before everybody. Measuring against a fixed "first
    // landing" is what flagged a correctly-staggered pickup as a five-hour wait.
    const lands = w.lands?.length ? w.lands : (w.land != null ? [w.land] : []);
    if (lands.length && p != null) {
      const before = lands.filter((m) => m <= p);
      const ref = before.length ? Math.max.apply(null, before) : Math.min.apply(null, lands);
      const gap = p - ref;
      if (gap < 0) warn.push({ t: "before anyone lands", tone: "warn", tip: RENTAL_TIP.early });
      else if (gap > 3 * HRS) warn.push({ t: `${Math.round(gap / 60)}h wait after landing`, tone: "warn", tip: RENTAL_TIP.wait });
    }
    if (w.fly != null && d != null) {
      const lead = w.fly - d;
      if (lead < 0) warn.push({ t: "drops off after takeoff", tone: "warn", tip: RENTAL_TIP.late });
      else if (lead < 2 * HRS) warn.push({ t: "tight airport return", tone: "warn", tip: RENTAL_TIP.tight });
    }
    if (c.best && x === c.best) out.push({ t: "cheapest", tone: "good", tip: RENTAL_TIP.cheapest });
    // "covers your flights" is a claim, so it only prints when both ends were
    // actually checkable against a picked flight and nothing came back wrong
    if (!warn.length && p != null && d != null && lands.length && w.fly != null) {
      out.push({ t: "covers your flights", tone: "good", tip: RENTAL_TIP.covers });
    }
    return out.concat(warn);
  }
  // No url column on flights, so link out to the live Google Flights board for
  // that exact route and date, the place you'd go to act on the row anyway.
  function flightLink(f) {
    const p = T.parseStamp(f.departure_time, state.trip?.start_date);
    if (!f.from_airport || !f.to_airport || !p) return "";
    const stops = f.via?.length ? "" : " nonstop";   // don't ask for a nonstop you're not on
    return "https://www.google.com/travel/flights?q=" +
      encodeURIComponent(`Flights to ${f.to_airport} from ${f.from_airport} on ${p.date}` +
        (f.airline ? `${stops} on ${f.airline}` : ""));
  }
  // The link out of a leg that's already bought. flightLink above is a route+date
  // SEARCH by construction, which is right on the fare board and wrong the moment
  // a seat is ticketed: a booked leg wants THAT flight, not the shopping view you
  // already finished with.
  //
  // flightradar24's /data/flights/<ident>, and the choice was made by loading
  // every candidate and LOOKING at it (2026-08-17) rather than reasoning about
  // what a URL probably renders:
  //   fr24        takes the IATA ident the ticket prints (wn561) and renders the
  //               route, the timetable, and forward-scheduled dates. Picked.
  //   flightaware answers "Unknown Flight" for WN561, it keys on the ICAO code
  //               (SWA561), so it would need a carrier map to work at all, and
  //               its dated /history/<date>/<time>/<orig>/<dest> form is also
  //               Unknown Flight for any date that hasn't happened yet.
  //   flightstats "DATE IS OUT OF RANGE, tracking is available for flights
  //               scheduled 3 days before or after today", which is never true
  //               of a leg booked weeks out.
  //   flightera   Cloudflare bot wall. google.com/search, the same.
  //   Google      /travel/flights?q=<flight number> renders the Google Flights
  //               HOMEPAGE, no status card, not even a board.
  //   airline     southwest.com/air/manage-reservation ignores its own
  //               ?confirmationNumber= and renders an empty lookup form. A shell,
  //               exactly the trap carLink documents below.
  //
  // Nothing renders a status page for a flight three weeks out, that's the shape
  // of flight tracking, not a gap in this pick. Today the page answers "which
  // flight is this and when does it run"; as the date closes it turns into live
  // status for the exact leg.
  //
  // Stripping the zero padding is load-bearing, not tidiness: the row this was
  // reported on stores "WN 0561", and fr24 answers "no data available for your
  // request" for wn0561. The carrier code must hold a letter, or a bare "561"
  // parses as carrier 56 + flight 1 and links to a flight that doesn't exist.
  // ponytail: fr24 sometimes serves a paywalled empty table under repeated
  // automated hits; a single human click gets the full one. Revisit if that stops
  // being true.
  function flightTrackLink(f) {
    const m = /^\s*([a-z]\d|\d[a-z]|[a-z]{2})\s*0*(\d{1,4})\s*$/i.exec(f.flight_num || "");
    return m ? `https://www.flightradar24.com/data/flights/${(m[1] + m[2]).toLowerCase()}` : "";
  }
  // Car rows DO have a url column, but a row added without one rendered no link
  // at all, so the same escape hatch as flights: the dated board for the airport
  // you actually land at, built from the row's own pickup/dropoff.
  //
  // Expedia, not Kayak, and the choice was made by loading both and LOOKING at
  // them (2026-08-11): Expedia honours the pickup/drop-off clock (`time1=930AM`)
  // and takes a bare IATA code in `locn`, while Kayak silently forces both ends to
  // Noon and bounces any URL carrying a time to its generic landing page. Vendor
  // and branch pages are worse than either, every one tested was an undated
  // marketing shell with an empty date form, which is the bug this replaced.
  // A 200 and a matching <title> is not a dated board; look at the page.
  function carLink(x, w) {
    w = w || groundWindow();
    const at = (s) => T.parseStamp(s, state.trip?.start_date);
    const p = at(carPickup(x)), d = at(carDropoff(x));
    if (!w.airport || !p || !d) return "";
    const mdy = (s) => `${s.date.slice(5, 7)}/${s.date.slice(8, 10)}/${s.date.slice(0, 4)}`;
    // Turo's dated `/search?startDate=...` URL renders its own "There's been an
    // error" page (its API call comes back HTML), so it is not linkable. The
    // airport category page is, and it carries real listings with prices, you
    // just set the dates in the box at the top. Undated and working beats dated
    // and broken. ponytail: revisit if Turo ever ships a stable dated search URL.
    if (busOf(x) === "turo") {
      return `https://turo.com/us/en/car-rental/united-states/${encodeURIComponent(String(w.airport).toLowerCase())}`;
    }
    // Expedia wants "930AM" / "1230PM", no colon, no leading zero on the hour.
    // Do NOT "fix" the noon hour to 0. The stored piid links captured on 2026-08-11
    // carry `time1=030PM`, which reads like Expedia counts noon as 0, it does not.
    // A link Sam pulled off the live site on 2026-08-13 carries `time1=1230PM`
    // (and `time2=0230PM`, so the leading zero is optional). `030PM` is a stale
    // format, not the rule. This was changed to `h % 12` on that bad inference and
    // reverted the same day.
    const clock = (s) => {
      if (s.minutes == null) return "";
      const h = Math.floor(s.minutes / 60);
      return `${h % 12 === 0 ? 12 : h % 12}${String(s.minutes % 60).padStart(2, "0")}${h < 12 ? "AM" : "PM"}`;
    };
    const t1 = clock(p), t2 = clock(d);
    return "https://www.expedia.com/carsearch?locn=" + encodeURIComponent(w.airport) +
      `&date1=${encodeURIComponent(mdy(p))}` + (t1 ? `&time1=${t1}` : "") +
      `&date2=${encodeURIComponent(mdy(d))}` + (t2 ? `&time2=${t2}` : "");
  }

  // Which of the two links a car row actually gets. `x.url` used to win outright,
  // and that is the reason this board keeps coming back broken: every rescan
  // re-enters urls by hand, and two shapes keep getting entered that never point
  // at THIS rental.
  //   A bare vendor homepage, rows 39/40 landed on `nucarrentals.com/`, whose
  //   date box defaults to tomorrow and has never heard of Denver. That is the
  //   undated marketing shell carLink was written to replace, back again.
  //   An Expedia `/carsearch/details?piid=…`, a single search session's offer
  //   token, which dies with the quote it captured. The four still stored here
  //   were pulled 2026-08-11 carrying `totalPriceShown=600.00`; the 2026-08-17
  //   rescan repriced that same car to $600.00, so the token is already stale.
  // So a stored url is kept only when it carries the row's own pickup date ,
  // the cheap read of "does this link know about my rental." Everything real on
  // the board passes it (rental24h, Hotwire, MileMarker, Expedia's own dated
  // /carsearch board); the homepages do not. Nothing is deleted from the DB: the
  // piid still holds the price it was captured at, it just stops being the link.
  // ponytail: date-in-the-url is a proxy, not a fetch. A dated link that 404s
  // anyway wants someone to LOOK at the page, not a longer regex here.
  function carHref(x, w) {
    const u = String(x.url || "").trim();
    if (!u) return carLink(x, w);
    return carUrlIsDated(x, u) ? u : (carLink(x, w) || u);
  }
  function carUrlIsDated(x, u) {
    if (/[?&]piid=/.test(u)) return false;
    // A Turo url can never pass the date test, Turo has no working dated search
    // URL at all (carLink says why), so its category page is the best link that
    // exists. Testing it would throw away every real Turo listing somebody pastes.
    if (busOf(x) === "turo") return true;
    const p = T.parseStamp(carPickup(x), state.trip?.start_date);
    if (!p) return true;                       // no date to check it against
    let s = u;
    try { s = decodeURIComponent(u); } catch { /* malformed escape, read it raw */ }
    const [Y, M, D] = p.date.split("-");
    // "2026-09-10" (rental24h, Hotwire) or "9/10/2026" / "09/10/2026" (Expedia,
    // MileMarker), the same day, spelled the four ways these sites spell it.
    return s.indexOf(p.date) >= 0 || new RegExp(`\\b0?${Number(M)}/0?${Number(D)}/${Y}\\b`).test(s);
  }

  // ── THE PICK ────────────────────────────────────────────────────────────────
  // Which option each decision is currently resting on. A booked row wins outright
  //, that decision is made, otherwise the cheapest live one, because that is what
  // everything else is implicitly being compared against.
  function autoPick(rows, eligible) {
    const fits = eligible ? rows.filter(eligible) : rows;
    // an ineligible option is a last resort, never a default, but showing
    // nothing when every option is ruled out is worse than showing the cheapest
    const from = fits.length ? fits : rows;
    return from.filter(isCommitted)[0] || cheapestBy(from.filter(isOpen), allIn) || from.filter(isOpen)[0] || null;
  }
  function picked(key, rows, eligible) {
    const id = state.pick[key];
    return (id != null && rows.filter((r) => r.id === id)[0]) || autoPick(rows, eligible);
  }
  // a stay with no stated capacity is not known to be too small, so it stays in
  const fitsParty = (h) => h.guests == null || h.guests >= partySize();
  const LEG_ORDER = ["outbound", "return", "roundtrip"];
  const LEG_LABEL = { outbound: "leaving", return: "coming back", roundtrip: "round trip" };
  // Leg grouping for ONE traveller's rows. Split out of flightLegs because it is
  // no longer only his: a crew member's ticket gets grouped and rendered the same
  // way, and doing that off a copy of this logic is how the two boards would drift.
  function legsOf(F) {
    const seen = [];
    F.forEach((f) => { const d = f.direction || "outbound"; if (seen.indexOf(d) < 0) seen.push(d); });
    seen.sort((a, b) => LEG_ORDER.indexOf(a) - LEG_ORDER.indexOf(b));
    // A leg whose every row is dead is a leg you already ruled out wholesale ,
    // six rejected Denver roundtrips shouldn't stack onto the pair total.
    // chain() first: two rows on one ticket that meet nose-to-tail are one
    // journey, not two options for the same leg. Without it the Columbus
    // outbound read EWR→IAD and the arrival timeline used the Dulles landing.
    return seen.map((d) => ({ leg: d, rows: FC.chain(F.filter((f) => (f.direction || "outbound") === d)) }))
      .map((g) => Object.assign({}, g, { live: g.rows.some((r) => !isDead(r)) }));
  }
  function flightLegs(t) { return legsOf(myFlights(t)); }

  // The cheapest realistic outcome for one leg, which is what the board's
  // "$X over the cheapest pair" is measured against. On a BOOKED leg that is what
  // you paid: there is no saving left on a bought ticket, so it contributes
  // nothing to the gap and the delta reports only the legs still open. Reading
  // the cheapest live fare here instead is how a half-booked board came to offer
  // a saving on a seat already charged to a card.
  function legFloor(g) {
    const b = g.rows.filter(isCommitted)[0];
    if (b) return allIn(b);
    const c = cheapestBy(g.rows.filter((r) => !isDead(r)), allIn);
    return c ? allIn(c) : 0;
  }

  // ── FLIGHTS ─────────────────────────────────────────────────────────────────
  // The section covers three things that are never each other's context: the
  // fares, the car, and everything else that moves you around. Stacked, they were
  // one long scroll in which only one is ever the question you are asking, so they
  // are three buckets and you are always in exactly one. The strip lives in the
  // section head rather than the list, so it holds still while the board under it
  // changes and never scrolls out of reach.
  function groundTabs(t) {
    const rows = t.transportation || [];
    const n = (k) => rows.filter((x) => busOf(x) === k).length;
    const b = [
      // Every row on this tab, not only his, the crew's tickets render here now,
      // and a "2" over four visible legs is the counter lying about its own tab.
      { k: "flights", l: "flights", n: (t.flights || []).length },
      { k: "cars", l: "cars", n: n("carrental") + n("turo") },
      { k: "other", l: "additional transport", n: n("other") },
    ];
    const on = b.filter((x) => x.k === state.ground)[0] || b[0];
    const copy = on.k === "flights" && flightsText(t)
      ? `<button class="wifi-act gcopy" data-flightcopy title="copy your booked flights as a text message">copy flights</button>` : "";
    // copy sits beside the tablist, not in it: a button inside role=tablist is not a tab
    return { on: on.k, html: `<div class="gtabs-row"><div class="hub-tabs gtabs" role="tablist">${b.map((x) => `
      <button class="hub-tab gtab${x.k === on.k ? " active" : ""}" role="tab" aria-selected="${x.k === on.k}"
        data-ground="${esc(x.k)}">${esc(x.l)}<span class="gtab-n">${x.n}</span></button>`).join("")}</div>${copy}</div>` };
  }
  function bindGround(el) {
    el.querySelectorAll("[data-ground]").forEach((b) => {
      b.onclick = () => { state.ground = b.dataset.ground; state.selId = null; renderFocus(); renderContext(); };
    });
    const c = el.querySelector("[data-flightcopy]");
    if (c) c.onclick = () => {
      copyText(flightsText(state.trip)).then((ok) => { toast(ok ? "flights copied" : "could not copy"); });
    };
  }

  // The reader's booked flights as plain text for a message thread. One block per
  // segment, every block the same four lines, so a connection reads as two flights
  // with their own terminals instead of one flight that forgot where it stops.
  // "" when nothing is booked: a fare still being shopped is not an itinerary.
  const WEEKDAY = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  function textDay(iso) {
    const d = new Date(`${iso}T00:00:00Z`);
    return Number.isNaN(d) ? dayShort(iso) : `${WEEKDAY[d.getUTCDay()]}, ${dayShort(iso)}`;
  }
  function textTerminal(v) {
    v = String(v || "").trim();
    if (!v) return "terminal TBD";
    if (/terminal|concourse|gate/i.test(v)) return v;
    return v.length <= 3 ? `Terminal ${v}` : `${v} terminal`;
  }
  function flightsText(t) {
    const start = t.start_date;
    const blocks = [];
    readerLegGroups(t).forEach((g) => {
      const row = g.rows.filter(isCommitted)[0];
      if (!row) return;
      (row.segments || [row]).forEach((f) => {
        const dep = T.parseStamp(f.departure_time, start), arr = T.parseStamp(f.arrival_time, start);
        const clock = (p, raw) => p && p.minutes != null ? T.fmtClock(p.minutes) : (raw || "time TBD");
        // the arrival day is only worth a word when it is not the departure day
        const arrDay = arr && dep && (arr.date !== dep.date || arr.plusDays) ? ` (${textDay(arr.date)}${arr.plusDays ? ` +${arr.plusDays}` : ""})` : "";
        blocks.push([
          `${(LEG_LABEL[g.leg] || g.leg).toUpperCase()} · ${dep ? textDay(dep.date) : "date TBD"}`,
          [f.airline, f.flight_num].filter((x) => String(x || "").trim()).join(" ") || "flight # TBD",
          `Departs ${f.from_airport || "?"}, ${textTerminal(f.terminal_from)} at ${clock(dep, f.departure_time)}`,
          `Arrives ${f.to_airport || "?"}, ${textTerminal(f.terminal_to)} at ${clock(arr, f.arrival_time)}${arrDay}`,
        ].join("\n"));
      });
    });
    return blocks.length ? `${t.name} flights\n\n${blocks.join("\n\n")}` : "";
  }
  // navigator.clipboard is gated on a secure context and this Hub is plain http
  // over the tailnet, so the textarea fallback is the path that actually runs.
  function copyText(text) {
    // the textarea path, run when the clipboard API is absent or rejects
    const fallback = () => {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.cssText = "position:fixed;top:0;left:0;opacity:0";
      document.body.appendChild(ta);
      ta.select();
      let done = false;
      try { done = document.execCommand("copy"); } catch { done = false; }
      document.body.removeChild(ta);
      return done;
    };
    try {
      if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text).then(() => true, fallback);
    } catch { /* fall through */ }
    return new Promise((res) => res(fallback()));
  }

  function listFlights(head, list) {
    const t = state.trip;
    const tabs = groundTabs(t);
    if (tabs.on !== "flights") {
      setHTML(head, tabs.html);
      setHTML(list, tabs.on === "cars" ? carsHTML(t) : otherHTML(t));
      bindGround(head);
      return bindPanel(list, t);
    }
    const legs = flightLegs(t);
    const live = legs.filter((g) => g.live);
    // Same rule the stay board runs on: one committed row ends that leg's
    // comparison. When every live leg is settled there is no comparison left on
    // the board at all, so the whole panel hands over.
    if (live.length && live.every(isSettled)) return flightPanel(head, list, t, live, tabs.html);

    const sel = live
      .map((g) => ({ leg: g.leg, row: picked(`flights:${g.leg}`, g.rows.filter((r) => !isDead(r))) }))
      .filter((s) => s.row);
    const total = sel.reduce((s, x) => s + allIn(x.row), 0);
    const floor = live.reduce((s, g) => s + legFloor(g), 0);
    const over = total - floor;

    // The decision figure and the bag toggle are both price machinery: one reports
    // what a seat costs all-in, the other reprices the board. A guest is not
    // choosing a fare and is not being shown one, so neither has anything left to
    // say, the tabs are the whole head there.
    setHTML(head, tabs.html + (isGuest() ? "" : `
      <div class="hub-figure">
        <div class="hub-figure-fig">
          <span class="hub-figure-n">${money(total)}</span>
          <span class="hub-figure-l">a seat, all-in</span>
        </div>
        <div class="hub-figure-delta ${over > 0 ? "is-over" : "is-floor"}">${
          !sel.length ? "nothing on the board yet"
          : over > 0 ? `${money(over)} over the cheapest pair` : "the cheapest pair available"}</div>
        <div class="hub-figure-split">${esc(fareSplit(sel))}</div>
      </div>
      <div class="lbar">
        <span class="lbar-l" title="every airline here charges for the first checked bag, so the sticker fare is not the price">bringing</span>
        <label class="hub-checkbox-label"><input type="checkbox" id="bagCarry"${state.bags.carry ? " checked" : ""}> carry-on</label>
        <label class="hub-checkbox-label"><input type="checkbox" id="bagCheck"${state.bags.checked ? " checked" : ""}> checked bag</label>
        <span class="lbar-hint">prices below reprice to what you'd actually pay</span>
      </div>`));

    setHTML(list,
      // The reader's own ticket leads, above a fare comparison that is not theirs.
      crewFlightsHTML(t, "yours") +
      (legs.length
        ? legs.map((g) => groupHTML({
            kind: "flights", key: `flights:${g.leg}`, lead: 1,
            label: LEG_LABEL[g.leg] || g.leg, sub: legRoute(g.rows),
            pickKey: `flights:${g.leg}`, link: flightLink,
            tags: (f, ctx) => flightTags(f, ctx.best),
            // A settled leg keeps its table on a mixed board, but nothing on it
            // wins a "cheapest" badge, that badge is advice about a purchase,
            // and this one is made.
            ctx: (rows) => ({ best: rows.some(isCommitted) ? null : cheapestBy(rows.filter((r) => !isDead(r)), allIn) }),
          }, g.rows)).join("")
        : groupHTML({ kind: "flights", key: "flights", lead: 1, label: "flights", link: flightLink }, []))
      // Somebody else's ticket is not a fare he is choosing between, so it sits
      // under the board rather than in it, but it is on the board's page, which
      // is the whole change. Both paths render it: a half-shopped trip is exactly
      // when "who already has a seat" matters most.
      + crewFlightsHTML(t) + flightGapHTML(t) + flightResearchHTML(t) + feeTableHTML(t));

    bindGround(head);
    bindPanel(list, t);
    const carry = $("bagCarry"), check = $("bagCheck");
    if (carry) carry.onchange = (e) => { state.bags.carry = e.target.checked; repaint("bagCarry"); };
    if (check) check.onchange = (e) => { state.bags.checked = e.target.checked; repaint("bagCheck"); };
  }

  // ── THE CAR BUCKET ──────────────────────────────────────────────────────────
  // Counters and Turo sit in one bucket because they are quotes for the same
  // single decision, which is also why "cheapest" is judged across both, so a
  // $310 Turo has to beat the counters to earn the badge. They stay two boards
  // while it is still a comparison, and merge into one panel the moment a car is
  // booked: there is nothing left to compare, and the quotes it beat move
  // underneath as the record.
  function carsHTML(t) {
    const rows = t.transportation || [];
    const win = groundWindow();
    const cars = rows.filter(isCar).filter((r) => !isDead(r));
    const got = cars.filter(isCommitted)[0];
    if (got) return carPanel(t, got, cars, win);
    const ctx = () => ({ window: win, best: cheapestBy(cars, rowCost) });
    const carGroup = (key, label, sub, addType, empty) => groupHTML({
      kind: "transportation", cols: "carrental", key: key, label: label, sub: sub,
      addType: addType, pickKey: key, eligible: fitsSeats, empty: empty,
      link: (x) => carHref(x, win), tags: rentalTags, ctx: ctx,
    }, rows.filter((x) => busOf(x) === key));
    return carGroup("carrental",
        win.airport ? `car rental — ${win.airport}` : "car rental",
        rentalWindowSub(win), "car_rental",
        "no counter quotes yet — add one")
      + carGroup("turo", "turo", "picked up from a host, not a counter", "turo",
        "no turo listings yet — add one");
  }
  // ── THE EVERYTHING-ELSE BUCKET ──────────────────────────────────────────────
  // A LIST of things you are also doing, not a comparison, so it has no decided
  // state to hand over to and renders the same either way.
  function otherHTML(t) {
    return groupHTML({
      kind: "transportation", key: "transportation", label: "additional transport",
      sub: "buses, trains, shuttles, rides", addType: "", link: (x) => x.url || "",
    }, (t.transportation || []).filter((x) => busOf(x) === "other"));
  }

  // ── THE CAR, ONCE IT'S BOOKED ───────────────────────────────────────────────
  // What is left to know about a car you have already paid for is nothing the
  // quote board was built to say: where the counter actually is, what the booking
  // is called, and whether the window you reserved still brackets the flights you
  // reserved. That last one is the only check worth keeping from the comparison,
  // and it survives for free, `rentalTags` with no `best` never fires the
  // "cheapest" badge, so what is left is exactly the set that reads as "did we
  // get this right": does it wait for your landing, is it back before you fly,
  // does it hold everyone.
  function carPanel(_t, x, cars, win) {
    const rest = cars.filter((r) => r !== x);
    const p = carPickup(x), d = carDropoff(x);
    const mapsHref = x.location
      ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(x.location)}` : "";
    const flags = rentalTags(x, { window: win, best: null });
    return `<div class="stay hub-t3p-stack">${stayBlock("the car",
      [x.description || busOf(x), countdown(daysAway(p))].filter(Boolean).join(" · "),
      stayFacts([
        ["pick up", esc(stampOrBlank(p))],
        ["drop off", esc(stampOrBlank(d))],
        ["the counter", mapsHref
          ? `<span class="hub-text-act"><span>${esc(x.location)}</span><a class="hub-link-chip llink" href="${esc(mapsHref)}" target="_blank" rel="noopener">map ↗</a></span>`
          : esc(x.location || ""), 1],
        ["confirmation", esc(x.confirmation || "")],
        ["fits", x.seats != null && x.seats !== "" ? esc(`${x.seats} of ${partySize()}`) : ""],
        // No price on a booked car. What it cost stopped deciding anything the
        // moment the counter took the card, so it lives in the cost tab and this
        // panel answers "when and where", same rule as the booked fare board.
        ["against your flights", tagsHTML(flags), 1],
        ["notes", stayList(x.notes, ""), 1],
      ]) + gapList("transportation", x, ["confirmation", "pickup_time", "dropoff_time", "seats"]),
      `${x.url ? `<a class="hub-section-head-act lgroup-act" href="${esc(x.url)}" target="_blank" rel="noopener">booking ↗</a>` : ""
      }<button class="hub-section-head-act lgroup-act" data-editrow="transportation:${esc(x.id)}">edit the car</button>`)}</div>`
      + (rest.length ? groupHTML({
        kind: "transportation", cols: "carrental", key: "carbeat", lead: 0,
        label: "what it beat", sub: "", link: (r) => carHref(r, win),
        tags: (r, c) => rentalTags(r, c), ctx: () => ({ window: win, best: null }),
      }, rest) : "");
  }
  // The window every quote on the board is being judged against, said once above
  // the table instead of implied by seven badges.
  function rentalWindowSub(w) {
    if (w.land == null && w.fly == null) return "";
    const at = (m) => m == null ? "?" : `${dayShort(new Date(m * 60000).toISOString().slice(0, 10))} ${T.fmtClock(m % 1440)}`;
    return `land ${at(w.land)} · fly out ${at(w.fly)} · ${partySize()} people`;
  }

  // "$210.00 out on Southwest · return on the same ticket · no bags · one booking"
  function fareSplit(sel) {
    if (!sel.length) return "";
    const bags = !state.bags.carry && !state.bags.checked ? "no bags"
      : [state.bags.carry ? "carry-on" : "", state.bags.checked ? "checked bag" : ""].filter(Boolean).join(" + ");
    const parts = sel.map((s) => {
      const label = { outbound: "out", return: "back", roundtrip: "both ways" }[s.leg] || s.leg;
      return rowCost(s.row) ? `${money(allIn(s.row))} ${label} on ${s.row.airline || "—"}`
                            : `${label} on the same ticket`;
    });
    const airlines = sel.map((s) => s.row.airline).filter(Boolean);
    const conf = sel.map((s) => s.row.confirmation).filter(Boolean);
    const one = conf.length > 1 && conf.every((c) => c === conf[0]);
    parts.push(bags);
    parts.push(one || airlines.length < 2 ? "one booking"
      : airlines.every((a) => a === airlines[0]) ? "one airline, two tickets" : "two bookings");
    return parts.join(" · ");
  }
  function legRoute(rows) {
    const r = rows.filter((f) => f.from_airport || f.to_airport)[0];
    if (!r) return "";
    const p = T.parseStamp(r.departure_time, state.trip?.start_date);
    return `${routeText(r.from_airport, r.to_airport)}${p ? ` · ${stampShort(r.departure_time).split(" ")[0]} ${stampShort(r.departure_time).split(" ")[1]}` : ""}`;
  }


Object.assign(U, { tagsHTML, flightTags, stayCtx, housingTags, whatItBuys, LOGI_COLS, stampMins, rentalTags,
  flightLink, flightTrackLink, carLink, carHref, picked, fitsParty, LEG_LABEL, legsOf, flightLegs, legFloor,
  bindGround, copyText, listFlights, otherHTML, carPanel });
})();
