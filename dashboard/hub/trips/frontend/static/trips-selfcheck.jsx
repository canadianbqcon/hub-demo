/* hub · trips page, self-check + mount (2026-10-13): React-migration port of trips.js lines 9759-10692
   (selfCheck, the laminate hotspot, the Escape handler and the final boot call). Plain functions inside an IIFE;
   see trips-core.jsx for the shared interface. This is the last script: it ends in U.mount(), the only caller. */
(() => {
const U = window.TripsUI;
const { state, TC, status, isSettled, myFlights, busOf, carPickup, CHASE, costChart } = U;
const { sumMoney, differs, trailPath, markTrail, dropRepeatAirport, mergedMark, relax, markName, splitRuns, arcPts, stayHour, addLogi, lanes, instantLabels, nightsOf, perPersonNight, airlineFacts, knownAirline, allIn, stampMins, rentalTags, flightTrackLink, carLink, carHref, legFloor, otherHTML, carPanel, feeTableHTML, crewFlights, memberFor, flightlessMembers, flightGapHTML, bookedSplit, airBrand, flightLegBlock, ticketedAs, viewerFlightMissing, crewFlightsHTML, ownFlightsHTML, amenityItems, wifiCell, doorCell, photoItems, guestSafeNotes, amenityGroups, stayPanel, staySplit, delBtn, logiForm, gapCell, gapList, specFromLogi } = U.fwd("sumMoney", "differs", "trailPath", "markTrail", "dropRepeatAirport", "mergedMark", "relax", "markName", "splitRuns", "arcPts", "stayHour", "addLogi", "lanes", "instantLabels", "nightsOf", "perPersonNight", "airlineFacts", "knownAirline", "allIn", "stampMins", "rentalTags", "flightTrackLink", "carLink", "carHref", "legFloor", "otherHTML", "carPanel", "feeTableHTML", "crewFlights", "memberFor", "flightlessMembers", "flightGapHTML", "bookedSplit", "airBrand", "flightLegBlock", "ticketedAs", "viewerFlightMissing", "crewFlightsHTML", "ownFlightsHTML", "amenityItems", "wifiCell", "doorCell", "photoItems", "guestSafeNotes", "amenityGroups", "stayPanel", "staySplit", "delBtn", "logiForm", "gapCell", "gapList", "specFromLogi");
  // ── SELF-CHECK ───────────────────────────────────────────────────────────────
  // The two boards rest on money claims a table can't show you are wrong about:
  // a bag fee lands once per leg (twice on a roundtrip row), the far half of a
  // roundtrip ticket is free rather than $0-because-unpriced, and per-person is
  // per person per NIGHT. Loud in the console rather than a quietly wrong total.
  function selfCheck() {
    const fail = [], saveBags = state.bags, saveParty = state.party;
    // EVERY FIGURE BELOW IS HUB'S, so the reader has to be nobody for the length
    // of the check. The cost model asks who is reading now (TC.meId), and run on
    // a guest's own page these synthetic trips resolved to a member who is not on
    // them: every share came out $0.00 and the footer told a guest the money
    // self-check had failed. The blocks that deliberately vary the viewer save
    // and restore it themselves; this is the floor under them.
    const savedViewer = window.TRIP_VIEWER;
    window.TRIP_VIEWER = "";
    try {
    const eq = (got, want, what) => { if (Math.abs(got - want) > 0.005) fail.push(`${what}: got ${got}, want ${want}`); };
    // ── THE SHARE CELL ──────────────────────────────────────────────────────
    // One head's share, divided per ROW rather than off the trip total: a stay
    // across seven and a shuttle across two sit in the same category, and
    // dividing their sum by either number is wrong for the other. The points
    // ride along, because a share of an award booking is owed in points too.
    const shRows = [{ cash: 1866, ur: 0, urCash: 0, split: 7, mine: 1 / 7 },
                    { cash: 312.25, ur: 0, urCash: 0, split: 2, mine: 1 / 2 }];
    eq(sumMoney(shRows, true).cash, 1866 / 7 + 312.25 / 2, "a row's share is no longer divided by its OWN split");
    eq(sumMoney(shRows, false).cash, 2178.25, "the cash column stopped stating the whole line");
    eq(sumMoney([{ cash: 0, ur: 36500, urCash: 1241, split: 4, mine: 1 / 4 }], true).ur, 9125, "a points share is no longer divided");
    // A line tagged for somebody ELSE. He fronted it, so it is on the trip and
    // in the cash column, and it is nothing to him at the end of the day.
    eq(sumMoney([{ cash: 280.07, ur: 13000, urCash: 260, split: 1, mine: 0 }], true).cash, 0,
       "a seat bought for another traveller is still being billed to him");
    const own = [{ cash: 50, ur: 0, urCash: 0, split: 1, mine: 1 }];
    const half = [{ cash: 50, ur: 0, urCash: 0, split: 2, mine: 0.5 }];
    if (differs(sumMoney(own, true), sumMoney(own, false)))
      fail.push("a line that is entirely his is claiming a separate share");
    if (!differs(sumMoney(half, true), sumMoney(half, false)))
      fail.push("a split line is reporting no share at all");
    // The model's own rule, checked where the page reads it: a row whose
    // participants do not include him is worth nothing to him, and a row with
    // nobody named at all stays entirely his.
    eq(TC.myFactor(["33"], "30"), 0, "a line tagged for someone else is still landing on him");
    eq(TC.myFactor(["30", "33"], "30"), 0.5, "a two-way split is not halving");
    eq(TC.myFactor([], "30"), 1, "an unassigned line vanished from his own total");
    try {
      state.bags = { carry: false, checked: true };
      eq(allIn({ airline: "Southwest", cost: 226.39 }), 271.39, "one checked bag on a one-way");
      eq(allIn({ airline: "Southwest", cost: 226.39, direction: "roundtrip" }), 316.39, "one checked bag on a roundtrip row");
      eq(allIn({ airline: "Southwest", cost: null }), 0, "the far half of a roundtrip ticket pays no bag fee");
      state.bags = { carry: true, checked: false };
      eq(allIn({ airline: "United", cost: 179 }), 179 + U.CARRY_IF_BASIC, "carry-on on a basic-economy risk carrier");
      eq(allIn({ airline: "Delta", cost: 179 }), 179, "carry-on is free where the carrier allows it");
      // The fee table may print a price only for a carrier it actually knows.
      if (!knownAirline(airlineFacts("Avianca")) && /\$4[05]/.test(
            feeTableHTML({ id: -1, __feeProbe: [{ airline: "Avianca" }] })))
        fail.push("the fee table is quoting a default bag price for an airline it does not know");
      if (state.trip?.start_date && state.trip.end_date) {
        state.party = 4;
        const h = { total_cost: 1200, check_in: state.trip.start_date, check_out: state.trip.end_date };
        const n = nightsOf(h);
        if (n) eq(perPersonNight(h), 1200 / n / 4, "per person per night at a party of 4");
      }
    } finally { state.bags = saveBags; state.party = saveParty; }
    // Every delete on the page routes through these. They shipped once with
    // confirmDelete undefined - four dead buttons, silent until someone clicked one.
    // `typeof` on an undeclared name is safe, which is the whole point here.
    // No form carries a yes/no field any more - the amenity flags came off the
    // rental form 2026-08-25 and the listing scraper is the only thing that
    // writes them. unbool is now a pass-through and there is nothing left for it
    // to convert; the NOT_TYPED tripwire below is what fires if one comes back.
    // ── THE SPLIT ───────────────────────────────────────────────────────────
    // A stay draws one of two forms, so a column that fell out of BOTH lists can
    // never be typed in again. Some are meant to be unreachable - the listing
    // scraper fills them and hand-entry was only ever noise - but that has to be
    // a decision on this list, not an edit nobody noticed.
    const HOUSING_COLS = ("stay_type,name,area,address,check_in,check_out,confirmation_code,host,check_in_method,wifi,wifi_ssid,wifi_pass,"
      + "cancellation_deadline,total_cost,nightly_rate,points_total,points_nightly,points_program,points_transfer,"
      + "deposit,guests,bedrooms,beds,baths,parking,hot_tub,pool_table,pool,rating,reviews,url,status,"
      + "house_rules,checkout_tasks,amenities,notes,"
      // what a hotel answers and a house never asks (migration 024)
      + "room_type,loyalty,incidental_hold,resort_fee,breakfast,late_checkout").split(",");
    // Deliberately not hand-editable (Sam, 2026-08-25). rating/reviews and the
    // amenity set come off the listing; deposit and area were never filled; the
    // per-night award rate is the total over the nights.
    const NOT_TYPED = "area,rating,reviews,deposit,hot_tub,pool,pool_table,amenities,points_nightly".split(",");
    const covered = new Set([...U.LOGI_FIELDS.hotel, ...U.LOGI_FIELDS.rental].filter((f) => !f.sec).map((f) => f.k));
    const orphans = HOUSING_COLS.filter((k) => !covered.has(k) && NOT_TYPED.indexOf(k) < 0);
    if (orphans.length) fail.push(`housing column(s) reachable from neither form and not on the not-typed list: ${orphans.join(",")}`);
    const resurrected = NOT_TYPED.filter((k) => covered.has(k));
    if (resurrected.length) fail.push(`a field is back on a form but still listed as not hand-editable: ${resurrected.join(",")}`);
    const strays = [...covered].filter((k) => HOUSING_COLS.indexOf(k) < 0);
    if (strays.length) fail.push(`a housing form draws a field the table has no column for: ${strays.join(",")}`);
    // Section markers are layout, not data: one that reaches the PATCH body writes
    // a column called "undefined", and one that reaches the detail rail prints an
    // empty chip. They carry a label and nothing else.
    ["hotel", "rental"].forEach((k) => {
      const spec = specFromLogi(k, {});
      if (!spec.filter((f) => f.sec).length) fail.push(`${k}'s form lost its sections and is one flat column again`);
      if (spec.some((f) => (f.sec ? f.k : !f.k))) fail.push(`a ${k} form entry is both a section marker and a field`);
    });
    // …and the type is what chooses between them. A row saved before migration
    // 014 has no stay_type at all and has to land somewhere rather than nowhere.
    if (logiForm("housing", { stay_type: "rental" }) !== "rental") fail.push("a rental is no longer drawing the rental form");
    if (logiForm("housing", {}) !== "hotel") fail.push("a stay with no type set no longer falls back to the hotel form");
    // specFromLogi rebuilds every field from scratch, so a flag it forgets to copy
    // is dropped in silence - this one stops the type select from redrawing the
    // form, which just looks like the switch doing nothing.
    if (!specFromLogi("hotel", {}).find((f) => f.k === "stay_type")?.reform) fail.push("the kind-of-stay select no longer redraws the form when it changes");
    // detailLogistics splits the field list on `type === "textarea"`: chips above,
    // prose blocks below. A long field slipping back into the chip row is the
    // regression that put the same paragraph on the page twice.
    const longFields = U.LOGI_FIELDS.rental.filter((f) => f.type === "textarea").map((f) => f.k).join(",");
    if (longFields !== "check_in_method,house_rules,checkout_tasks,notes") fail.push(`a rental's prose fields changed, detail rail chips will carry a paragraph: ${longFields}`);
    // …and `amenities` is the one prose field the rail must NOT print: sixty-three
    // items down a 480px column buries the rules and the chores under a wall.
    const railFields = U.LOGI_FIELDS.rental.filter((f) => f.type === "textarea" && f.rail !== 0).map((f) => f.k).join(",");
    if (railFields !== "check_in_method,house_rules,checkout_tasks,notes") fail.push(`the detail rail's prose set changed: ${railFields}`);
    // The amenity blob is split on a BLANK line, because an item's own sub-detail
    // sits on the line under it. Splitting on \n orphans every one of those.
    const ai = amenityItems({ amenities: "Bathtub\n\nCoffee maker\nDrip, french press\n\nFire pit" });
    if (ai.length !== 3) fail.push(`amenityItems no longer splits on a blank line: ${ai.length} items`);
    if (ai[1].l !== "Coffee maker" || ai[1].d !== "Drip, french press") fail.push(`an amenity's sub-detail no longer separates from its label: ${JSON.stringify(ai[1])}`);
    if (amenityItems({}).length) fail.push("a row with no amenity list no longer reads as empty");
    // The noise filter: the obvious items go, the headings and the real ones stay,
    // and a group left with nothing under it disappears instead of rendering empty.
    const an = amenityItems({ amenities: "# Kitchen\n\nRefrigerator\n\nStainless steel oven\n\nBlender\n\n# Internet\n\nWifi" });
    if (an.map((a) => a.l).join("|") !== "# Kitchen|Blender|# Internet")
      fail.push(`the amenity noise filter changed: ${JSON.stringify(an.map((a) => a.l))}`);
    if (amenityGroups({ amenities: "# Internet\n\nWifi" }).length)
      fail.push("an amenity group cut to nothing is still rendering a heading");
    const keep = amenityItems({ amenities: "Private hot tub\n\nBathtub\n\nFree parking on premises\n\nCoffee" });
    if (keep.length !== 4) fail.push(`the noise filter is eating amenities that decide something: ${JSON.stringify(keep.map((a) => a.l))}`);
    // ── THE WIFI ROW ────────────────────────────────────────────────────────
    // Four states, and each one used to be the same dead sentence. Nothing here
    // checks how it looks; it checks that the row offers the ACTION its state
    // calls for, which is the thing that was missing.
    const wifiOf = (h) => wifiCell(h, 0, 0);
    if (wifiOf({ id: 42, wifi: "" }).indexOf('data-addfield="housing:42:wifi_ssid,wifi_pass,wifi"') < 0)
      fail.push("an empty wifi field no longer offers the add button");
    const split = wifiOf({ id: 42, wifi_ssid: "Net", wifi_pass: "pw" });
    if (split.indexOf('data-wificopy="pw"') < 0)
      fail.push("a known password no longer offers to copy itself");
    if (split.indexOf('data-wifiqr="42"') < 0)
      fail.push("a known network no longer offers its QR");
    // The one-line legacy rows print as they are - a parser guessing at the dash
    // hands somebody the wrong password at a door - but they say how to fix it.
    const legacy = wifiOf({ id: 42, wifi: "MyNet — hunter2" });
    if (legacy.indexOf("MyNet") < 0 || legacy.indexOf("data-wificopy") >= 0)
      fail.push("an unsplit wifi line is being parsed rather than printed");
    if (legacy.indexOf('data-addfield="housing:42:wifi_ssid,wifi_pass,wifi"') < 0)
      fail.push("an unsplit wifi line offers no way to split it");
    // A shared trip link is read-only, so no edit affordance reaches a guest -
    // but the wifi itself still does, because a guest is someone in the house.
    if (wifiCell({ id: 42, wifi: "" }, 0, 1).indexOf("<button") >= 0)
      fail.push("a guest is being offered the add-wifi button");
    if (wifiCell({ id: 42, wifi: "MyNet — hunter2" }, 0, 1).indexOf("data-addfield") >= 0)
      fail.push("a guest is being offered the split-the-wifi button");
    // …and the Airbnb waiting line survives beside the button, because "not
    // released yet" and "nobody looked it up" are different facts.
    if (wifiCell({ id: 42, wifi: "", url: "https://www.airbnb.com/rooms/1" }, 9, 0).indexOf("48 hours") < 0)
      fail.push("the Airbnb wifi-not-released-yet line is gone from the empty state");
    if (wifiCell({ id: 42, wifi: "", url: "https://www.hyatt.com/x" }, 9, 0).indexOf("48 hours") >= 0)
      fail.push("Airbnb's 48-hour rule is being printed over a hotel booking");
    // ── THE DOOR ────────────────────────────────────────────────────────────
    // Two patterns run over free prose here, and a pattern over prose that
    // silently stops matching just prints the old wall again. These hold it to
    // the shape the rows are actually written in.
    const realDoor = "Door code 4736 · front-door keypad, self check-in\n"
      + "Early check-in 2:00 PM confirmed (standard code window is 4:00 PM to 10:00 AM)\n"
      + "Locking up: lock button, bottom right of the keypad";
    const door = doorCell({ check_in_method: realDoor });
    if (door.indexOf('<span class="door-code">4736</span>') < 0)
      fail.push(`the door code is no longer being lifted out of the line: ${door}`);
    if (door.indexOf("Door code") >= 0)
      fail.push("the words that introduced the code are still printed beside it");
    if (door.indexOf("front-door keypad") < 0 || door.indexOf("Locking up") < 0)
      fail.push("lifting the code took the rest of the lock's instructions with it");
    if (door.indexOf("Early check-in") >= 0)
      fail.push("the check-in window is back on the door, and it is the row above it word for word");
    // "self check-in" carries the words but no clock - it is what the lock IS,
    // not when it opens, and the filter has to tell those apart.
    if (door.indexOf("self check-in") < 0)
      fail.push("the window filter is eating clauses that only mention check-in in passing");
    // A front desk has no code, and a stay with a phrasing neither pattern knows
    // must print exactly what was typed rather than an empty field.
    const desk = doorCell({ check_in_method: "Front desk from 3:00 PM · booked under Sam Rivera" });
    if (desk.indexOf("door-code") >= 0 || desk.indexOf("Front desk from 3:00 PM") < 0)
      fail.push(`a front-desk check-in is being parsed for a code it does not have: ${desk}`);
    // The one number that is NOT a door code sits three words from one that is.
    if (doorCell({ check_in_method: "The standard code window is 4:00 PM to 10:00 AM" }).indexOf("door-code") >= 0)
      fail.push("a code WINDOW is being read as a code");
    if (doorCell({ check_in_method: "" }) !== "")
      fail.push("an unfilled door field is rendering something instead of dropping its row");
    // The encoder is a separate file with its own pinned self-test; all this
    // needs to know is that it arrived. Without it the QR button opens a dialog
    // that throws, which looks like the row being broken.
    if (typeof QR === "undefined" || typeof QR.wifiPayload !== "function")
      fail.push("qr.js did not load — the show-QR button has nothing to draw");
    else if (QR.wifiPayload("Net", "pw") !== "WIFI:T:WPA;S:Net;P:pw;;")
      fail.push(`the wifi QR payload format changed: ${QR.wifiPayload("Net", "pw")}`);
    // ── THE BOOKED-STATE HANDOVER ───────────────────────────────────────────
    // A decision is over the moment one row commits, even with `considering`
    // siblings still sitting next to it - db.py only purges the rows that were
    // actively ruled out. Read this as "nothing open is left" and a booked leg
    // with a leftover quote goes on rendering as a live comparison.
    if (!isSettled({ rows: [{ status: "booked" }, { status: "considering" }] })) fail.push("a leg with a booked row and a surviving quote no longer reads as settled");
    if (isSettled({ rows: [{ status: "considering" }, { status: "rejected" }] })) fail.push("a leg nobody has booked is reading as settled");
    // …and the money that rests on it. On a booked leg the floor is what you PAID,
    // so the gap it contributes is zero; reading the cheapest live fare instead
    // reports a saving available on a ticket already bought.
    state.bags = { carry: false, checked: false };
    try {
      const booked = { rows: [{ status: "booked", cost: 226.39 }, { status: "considering", cost: 180 }] };
      eq(legFloor(booked), 226.39, "a booked leg's floor is what was paid, not the cheapest quote left beside it");
      eq(legFloor({ rows: [{ status: "considering", cost: 300 }, { status: "considering", cost: 180 }] }), 180, "an open leg's floor is the cheapest live fare");
      eq(legFloor({ rows: [{ status: "rejected", cost: 90 }] }), 0, "a leg with nothing live is floored at a fare you cannot buy");
    } finally { state.bags = saveBags; }
    // A car added before migration 007 carries the generic scheduled_* pair, so
    // every reader falls back to it rather than reporting no pickup at all.
    if (carPickup({ scheduled_date: "2026-05-14", scheduled_time: "10:30 AM" }) !== "2026-05-14 10:30 AM") fail.push("a pre-007 car row no longer falls back to scheduled_date/time for its pickup");
    if (carPickup({ pickup_time: "2026-09-10 12:30", scheduled_date: "2026-01-01" }) !== "2026-09-10 12:30") fail.push("the scheduled_* fallback is overriding a real pickup_time");
    // Somebody else's ticket renders as its own set of legs now, not as a footnote
    // under his. Two passengers, three tickets between them, and his own row must
    // not fall into either - that last one is the whole reason myFlights exists.
    const crewT = {
      members: [{ id: 1, name: "Sam Rivera", contact_slug: "sam-rivera" }, { id: 2, name: "Nina Ford" }, { id: 3, name: "Akshay Okafor" }],
      flights: [
        { id: 1, direction: "outbound", airline: "Avianca", flight_num: "AV569" },
        { id: 2, passenger: "Sophia Ford", direction: "outbound", airline: "Avianca", flight_num: "AV569" },
        { id: 3, passenger: "Sophia Ford", direction: "return", airline: "Avianca", flight_num: "AV566" },
        { id: 4, passenger: "Akshay Okafor", direction: "outbound", airline: "Delta", flight_num: "DL 710" },
      ],
    };
    const cf = crewFlights(crewT);
    if (cf.length !== 2) fail.push(`crewFlights no longer groups the other travellers one entry each — got ${cf.length}`);
    if (cf.some((g) => g.legs.some((lg) => lg.rows.some((r) => !(r.passenger || "").trim()))))
      fail.push("his own seat is leaking into a crew member's legs");
    const aria = cf.filter((g) => g.who === "Sophia Ford")[0];
    if (aria?.legs.length !== 2) fail.push("a crew member's two legs are no longer grouped as leaving + coming back");
    // The roster says Aria, the boarding pass says Sophia, and a strict match
    // would report her as having no flights while rendering her ticket above it.
    if (aria.member?.name !== "Nina Ford") fail.push("a ticket in a passport name no longer binds to its roster member");
    if (ticketedAs("Nina Ford", { passenger: "Sophia Ford" }) !== "ticketed as Sophia Ford") fail.push("the board no longer says which name the ticket is actually in");
    // ── A SHARED BOOKING IS TWO PEOPLE ON ONE FLIGHT ────────────────────────
    // "Aaron + Jasmine" in a passenger field is not a traveller called
    // "Aaron + Jasmine". The group is the flight; the names on it are the crew's
    // own, one each, and both read the same two cards.
    const sharedT = {
      members: [{ id: 1, name: "Sam Rivera", contact_slug: "sam-rivera" },
        { id: 2, name: "Owen Hale" }, { id: 3, name: "Jody Tran" }, { id: 4, name: "Akshay Okafor" }],
      flights: [
        { id: 1, passenger: "Aaron + Jasmine", direction: "outbound", airline: "Southwest", flight_num: "WN 468", departure_time: "2026-09-10 10:20" },
        { id: 2, passenger: "Aaron + Jasmine", direction: "return", airline: "Southwest", flight_num: "WN 4863", departure_time: "2026-09-14 17:15" },
        { id: 3, passenger: "Akshay Okafor", direction: "outbound", airline: "Delta", flight_num: "DL 710", departure_time: "2026-09-10 17:59" },
      ],
    };
    const shared = crewFlights(sharedT).filter((g) => g.who === "Aaron + Jasmine")[0];
    if (!shared) fail.push("a joint ticket no longer produces a group at all");
    else {
      if (shared.names.join("|") !== "Owen Hale|Jody Tran")
        fail.push(`a joint ticket is not naming both riders in roster order — got ${shared.names.join("|")}`);
      if (shared.legs.length !== 2) fail.push("a joint ticket lost one of its two legs in the regroup");
    }
    const sharedHTML = crewFlightsHTML(sharedT);
    if (sharedHTML.indexOf("Aaron + Jasmine") >= 0) fail.push("the board is still printing 'Aaron + Jasmine' as if it were somebody's name");
    if (sharedHTML.indexOf("Owen Hale") < 0 || sharedHTML.indexOf("Jody Tran") < 0)
      fail.push("a rider on a shared booking is missing from the head over their own cards");
    if (sharedHTML.indexOf("ticketed as") >= 0) fail.push("a shared booking is printing 'ticketed as Aaron + Jasmine' under cards whose head already names both");
    if (sharedHTML.indexOf("3 people") < 0) fail.push("the crew count is counting bookings rather than people");
    // Two rows entered separately for the same two flights are ONE journey, and
    // the point of keying on the itinerary is that they merge instead of stacking.
    const twoRows = { members: sharedT.members, flights: [
      { id: 1, passenger: "Owen Hale", direction: "outbound", airline: "Southwest", flight_num: "WN 468", departure_time: "2026-09-10 10:20" },
      { id: 2, passenger: "Jody Tran", direction: "outbound", airline: "Southwest", flight_num: "WN 468", departure_time: "2026-09-10 10:20" },
    ] };
    const tr = crewFlights(twoRows);
    if (tr.length !== 1) fail.push(`two riders entered separately on the same flight are still rendering as two separate journeys — got ${tr.length}`);
    if (tr[0] && tr[0].names.join("|") !== "Owen Hale|Jody Tran") fail.push("merging two rows on one flight lost a name");
    // …and two people who share an outbound but not a return are NOT one journey.
    const splitBack = { members: sharedT.members, flights: [
      { id: 1, passenger: "Owen Hale", direction: "outbound", airline: "Southwest", flight_num: "WN 468", departure_time: "2026-09-10 10:20" },
      { id: 2, passenger: "Jody Tran", direction: "outbound", airline: "Southwest", flight_num: "WN 468", departure_time: "2026-09-10 10:20" },
      { id: 3, passenger: "Jody Tran", direction: "return", airline: "Southwest", flight_num: "WN 4863", departure_time: "2026-09-14 17:15" },
    ] };
    if (crewFlights(splitBack).length !== 2) fail.push("two riders with different returns are being merged into one journey");
    // A row with nothing identifying on it signs as its own group - an empty
    // signature is not evidence two people are on the same plane.
    const blanks = { members: sharedT.members, flights: [
      { id: 1, passenger: "Owen Hale", direction: "outbound" },
      { id: 2, passenger: "Jody Tran", direction: "outbound" },
    ] };
    if (crewFlights(blanks).length !== 2) fail.push("two rows with no flight details are being merged as though they shared a plane");
    // Filling the flight number in on ONE of two rows for the same plane must not
    // split them. This is the exact break: Leonardo went onto Aaron and Jasmine's
    // flight, their return row later got its number typed in, his stayed blank,
    // and he fell out of the group he had just been put in.
    const halfNumbered = { members: sharedT.members, flights: [
      { id: 1, passenger: "Aaron + Jasmine", direction: "return", airline: "Southwest", flight_num: "WN 4863",
        from_airport: "DEN", to_airport: "LGA", departure_time: "2026-09-14 17:15" },
      { id: 2, passenger: "Leo Park", direction: "return", airline: "Southwest", flight_num: "",
        from_airport: "DEN", to_airport: "LGA", departure_time: "2026-09-14 17:15" },
    ] };
    const hn = crewFlights(halfNumbered);
    if (hn.length !== 1) fail.push(`filling the flight number in on one row of a shared flight has split the group — got ${hn.length}`);
    if (hn[0] && hn[0].names.join("|") !== "Owen Hale|Jody Tran|Leo Park")
      fail.push(`a rider is missing from the flight he was put on: ${hn[0] ? hn[0].names.join("|") : "-"}`);
    // …and a genuinely different departure is still a different flight.
    const otherPlane = { members: sharedT.members, flights: [
      { id: 1, passenger: "Owen Hale", direction: "return", airline: "Southwest",
        from_airport: "DEN", to_airport: "LGA", departure_time: "2026-09-14 17:15" },
      { id: 2, passenger: "Leo Park", direction: "return", airline: "Southwest",
        from_airport: "DEN", to_airport: "LGA", departure_time: "2026-09-14 20:40" },
    ] };
    if (crewFlights(otherPlane).length !== 2) fail.push("two riders on different departures are being merged onto one flight");
    // The card summary carries the route, the date and the countdown - and nothing
    // about who else is aboard. That line was never asked for and is not coming back.
    if (/· with [A-Z]/.test(crewFlightsHTML(sharedT)))
      fail.push("the leg summary is printing a '· with <names>' line nobody asked for");
    // ── WHOSE FLIGHT LEADS, AND WHAT SHAPE A LEG IS ─────────────────────────
    // A guest reading the shared board is looking for one thing: when do I fly.
    // Their own ticket rendering fourth, under somebody else's fare comparison,
    // is the failure this ordering exists to stop.
    const wasViewer = window.TRIP_VIEWER;
    try {
      window.TRIP_VIEWER = "";
      if (crewFlightsHTML(crewT, "yours")) fail.push("Hub is rendering a 'your flights' section with nobody logged in");
      if (crewFlightsHTML(crewT).indexOf("Nina Ford") < 0) fail.push("with no viewer, everyone should still be under 'travelling with you'");
      // Aria has no contact_slug on this roster, so she can only be matched on the
      // name: key - the half of member_key that a slug-only match silently drops.
      window.TRIP_VIEWER = "name:nina ford";
      const yours = crewFlightsHTML(crewT, "yours"), rest = crewFlightsHTML(crewT);
      if (yours.indexOf("your flights") < 0) fail.push("the viewer's own ticket is no longer lifted out into its own section");
      if (yours.indexOf("Nina Ford") < 0) fail.push("the 'your flights' head is not naming who is reading it");
      if (rest.indexOf("Aria") >= 0) fail.push("the viewer is being rendered twice — once as theirs and again under 'travelling with you'");
      if (rest.indexOf("Akshay") < 0) fail.push("lifting the viewer out has taken the rest of the crew with it");
      // …and he is not set apart from the crew list as "whose trip this is" -
      // he is one more name folded into "travelling with you", same as Akshay.
      if (rest.indexOf("Sam Rivera") < 0) fail.push("a guest is not seeing Sam's own legs under 'travelling with you'");
      if (ownFlightsHTML(crewT, "x") !== "") fail.push("a guest's board is rendering Sam's legs a second time outside the crew list");
      // Either rider on a shared booking is the viewer - the head leads with one
      // name, and reading it as "whose group this is" strands the other one under
      // "travelling with you" looking for a ticket that is already theirs.
      window.TRIP_VIEWER = "name:jody tran";
      if (crewFlightsHTML(sharedT, "yours").indexOf("Jody Tran") < 0)
        fail.push("the second name on a shared booking is not reading as the viewer's own flight");
      if (crewFlightsHTML(sharedT).indexOf("Jody Tran") >= 0)
        fail.push("a viewer on a shared booking is rendering twice — as theirs and again under 'travelling with you'");
      window.TRIP_VIEWER = "sam-rivera";
      if (ownFlightsHTML(crewT, "x").indexOf("Sam Rivera") >= 0) fail.push("his own board is labelling itself with his name for him");
    } finally { window.TRIP_VIEWER = wasViewer; }
    // Out and back are one journey, so they are two cards on one row, not two
    // full-width bars. Losing the wrapper is what turns this tab back into a list.
    const pairHTML = crewFlightsHTML(crewT);
    if (pairHTML.indexOf("legpair") < 0 || pairHTML.indexOf("legcard") < 0) fail.push("a crew member's legs are back to full-width bars instead of a card pair");
    if (pairHTML.indexOf("Sophia Ford · leaving") >= 0) fail.push("the name is back in the leg label as well as the person head");
    if (ticketedAs("Akshay Okafor", { passenger: "Akshay Okafor" }) !== "") fail.push("a ticket in the roster name is printing a redundant 'ticketed as' line");
    if (ticketedAs("Akshay Okafor", { passenger: "Akshay" }) !== "") fail.push("a first name is printing as if it were a different name on the ticket");
    if (ticketedAs("Nina Ford", { passenger: "Sophia Ford" }) !== "ticketed as Sophia Ford") fail.push("a genuinely different ticket name went silent");
    // ── THE PASS IS PAINTED IN THE CARRIER'S OWN LIVERY ─────────────────────
    // What breaks silently here is a mark or a colour going missing for a
    // carrier the board actually flies - the card still renders, it just stops
    // being that airline's card, and nothing on screen says so.
    if (airBrand("Southwest") === airBrand("Delta")) fail.push("two carriers are resolving to the same livery");
    if (airBrand("Southwest Airlines").key !== "sw") fail.push("a carrier name with a suffix no longer matches its livery");
    if (airBrand("Copa").key !== "generic") fail.push("a carrier with no mark on file is not falling through to the generic plate");
    // Avianca is wordmark-only, so the artwork check reads either slot - what must
    // never happen is a mapped carrier rendering with no vendor artwork at all.
    ["Southwest", "Delta", "United", "Avianca"].forEach((a) => {
      const br = airBrand(a);
      if (br === U.AIR_GENERIC) fail.push(`${a} fell through to the generic plate`);
      if ((br.mark + br.word).indexOf("<path") < 0) fail.push(`${a} lost the vendor artwork off its plate`);
      if (br.livery.length !== 3) fail.push(`${a} is not carrying three livery bands`);
    });
    // The generic plate must SAY the carrier rather than draw one - a blank
    // plate on an unmapped airline reads as a rendering fault.
    const genT = { members: crewT.members, flights: [{ id: 9, passenger: "Akshay Okafor",
      direction: "outbound", airline: "Copa", flight_num: "CM303",
      from_airport: "JFK", to_airport: "SAL", departure_time: "2026-12-16 05:50",
      arrival_time: "2026-12-16 09:55" }] };
    // tzOf reads the OPEN trip's airports, so this fixture only found its zones on
    // the one trip that flies JFK-SAL and failed on every other board. Lend it the
    // two zones for the length of the render.
    const liveTrip = state.trip;
    let genHTML = "";
    try {
      state.trip = Object.assign({}, (liveTrip || {}), { airports: Object.assign({}, (liveTrip?.airports || {}), { JFK: { tz: "America/New_York" }, SAL: { tz: "America/El_Salvador" } }) });
      genHTML = crewFlightsHTML(genT);
    } finally { state.trip = liveTrip; }
    if (genHTML.indexOf("Copa") < 0) fail.push("a carrier with no mark on file is not naming itself on the plate");
    if (genHTML.indexOf("pass-livery") < 0) fail.push("the generic plate lost its belly stripe");
    if (genHTML.indexOf("JFK") < 0 || genHTML.indexOf("SAL") < 0) fail.push("the pass is not printing both airport codes");
    // JFK is Eastern, SAL is Central: 05:50 to 09:55 local is 5h 05m in the air
    if (genHTML.indexOf("5h 05m") < 0) fail.push("the pass is not computing time in the air — got no duration");
    // A red-eye that lands tomorrow is the one case the date line has to catch.
    const overT = { members: crewT.members, flights: [{ id: 10, passenger: "Akshay Okafor",
      direction: "return", airline: "Avianca", flight_num: "AV566",
      from_airport: "SAL", to_airport: "JFK", departure_time: "2026-12-20 18:25",
      arrival_time: "2026-12-21 00:10" }] };
    if (crewFlightsHTML(overT).indexOf(">+1<") < 0) fail.push("a flight that lands the next day is not saying so");
    // A leg with no clock on either end must still render rather than throwing.
    const blankT = { members: crewT.members, flights: [{ id: 11, passenger: "Akshay Okafor",
      direction: "outbound", airline: "Delta", flight_num: "DL 1", from_airport: "LGA", to_airport: "DEN" }] };
    if (crewFlightsHTML(blankT).indexOf("legcard") < 0) fail.push("a leg with no times entered no longer renders at all");
    // A blank passenger accounts for HIM, so a full board leaves nobody flightless.
    if (flightlessMembers(crewT).length) fail.push("flightlessMembers is reporting a gap on a board where everyone has a ticket");
    const oneShort = { members: crewT.members.concat([{ id: 4, name: "Priya Shah" }]), flights: crewT.flights };
    const gap = flightlessMembers(oneShort);
    if (gap.length !== 1 || gap[0].name !== "Priya Shah") fail.push("a crew member with no ticket is not being counted as missing");
    if (flightGapHTML(oneShort).indexOf("1 of 4") < 0) fail.push("the missing-flights note no longer says how many of the crew it is");
    if (flightGapHTML(crewT) !== "") fail.push("the missing-flights note is rendering on a board with no gap");
    // A guest with no ticket of her own is not shown Sam's flight as if it
    // were hers - the slot reads missing, with a way to fix it, instead.
    try {
      window.TRIP_VIEWER = "name:priya shah";
      if (!viewerFlightMissing(oneShort)) fail.push("a guest with no ticket on the board is not reading as missing");
      const yoursMissing = crewFlightsHTML(oneShort, "yours");
      if (yoursMissing.indexOf("isn't on this board") < 0) fail.push("a flightless guest gets no prompt to send Sam her flight");
      window.TRIP_VIEWER = "sam-rivera";
      if (viewerFlightMissing(oneShort)) fail.push("Sam's own board is reading itself as a guest with a missing flight");
      window.TRIP_VIEWER = "";
      if (viewerFlightMissing(oneShort)) fail.push("Hub with no viewer is reading as a guest with a missing flight");
    } finally { window.TRIP_VIEWER = wasViewer; }
    // A second rider on his exact reservation has no field of her own to sit
    // in - only a name in the prose of his row, and that is not a ticket. She
    // reads as flightless like anybody else with nothing on the board, and the
    // note carries no weight either way. What still has to hold is the other
    // half: a name in his notes must not pull his own row out of `myFlights`,
    // which is what broke Denver once - his fare board went to "nothing entered"
    // because the one ticket that was his stopped looking like his.
    const sharedSeat = {
      members: crewT.members.concat([{ id: 4, name: "Priya Shah" }]),
      flights: crewT.flights.map((f) => (f.id === 1 ? Object.assign({}, f, { notes: "Megan is on this flight" }) : f)),
    };
    if (!flightlessMembers(sharedSeat).some((m) => m.name === "Priya Shah"))
      fail.push("a rider with no row of her own is being counted as covered because a note says her name");
    try {
      window.TRIP_VIEWER = "name:priya shah";
      if (!viewerFlightMissing(sharedSeat)) fail.push("a rider with no row of her own is not being told her flight is missing");
      if (!crewFlightsHTML(sharedSeat, "yours")) fail.push("a rider with no row of her own lost the 'your flight is missing' prompt");
    } finally { window.TRIP_VIEWER = wasViewer; }
    if (myFlights(sharedSeat).length !== crewT.flights.filter((f) => !(f.passenger || "").trim()).length)
      fail.push("noting a second rider on a blank-passenger row is pulling it out of Sam's own fare board");
    // Chase UR is how the award points were ACQUIRED, not what the booking was
    // sold for. Avianca charged 12,000 Aeroplan and $192.77; the transfer that
    // produced the Aeroplan is a separate transaction. None of the three prints
    // on a booked leg any more - they all still count, in the cost tab.
    const urRow = { id: 9, airline: "Avianca", flight_num: "AV569", direction: "outbound", status: "booked",
      cost: 192.77, points_total: 12500, points_program: "Aeroplan", points_transfer: 10500 };
    // Flight money leaves the MODEL on the public mirror, not only the board. Hide
    // it on the flights tab alone and the cost tab hands the same number straight
    // back, which is no hiding at all.
    const guestT = { members: [{ id: 1, name: "Sam Rivera" }],
      flights: [{ id: 1, cost: 192.77, status: "booked", points_transfer: 10500 }],
      housing: [{ id: 1, total_cost: 400, status: "booked" }] };
    const wasGuest = document.body.classList.contains("guest");
    try {
      document.body.classList.remove("guest");
      const hubBlock = flightLegBlock({ flights: [urRow], members: [] }, { leg: "outbound", rows: [urRow] }, urRow);
      if (hubBlock.indexOf("Chase UR") >= 0) fail.push("Chase UR is back on a booking row — it is how the points were bought, not what the flight cost");
      // A booked leg carries no price at all now, in either currency: the seat is
      // bought, so the fare and the award points are the cost tab's business and
      // the card's job is getting you on the plane. The two totals asserted below
      // are what proves the money did not vanish with the columns.
      if (hubBlock.indexOf("12,500") >= 0) fail.push("the award points are back on a booked leg — a bought seat's price belongs in the cost tab");
      if (hubBlock.indexOf("192.77") >= 0) fail.push("the fare is back on a booked leg — a bought seat's price belongs in the cost tab");
      // A `Key: value` note line is a field, and it reads as one: its own row,
      // its own key column, exactly like confirmation. The regression this
      // catches is the whole stack collapsing back under one "notes" label.
      const kRow = Object.assign({}, urRow, { confirmation: "ABC123",
        notes: "Ticket: 0142335174938\nRapid Rewards: 12345678\nNonstop, 5h05m" });
      const kBlock = flightLegBlock({ flights: [kRow], members: [] }, { leg: "outbound", rows: [kRow] }, kRow);
      if (kBlock.indexOf("<dt>Ticket</dt>") < 0) fail.push("a keyed flight note is back inside the notes value instead of its own row");
      if (kBlock.indexOf("<dt>Rapid Rewards</dt>") < 0) fail.push("a keyed flight note is back inside the notes value instead of its own row");
      if (kBlock.indexOf("Nonstop, 5h05m") < 0) fail.push("the prose half of a flight's notes was dropped when the keyed lines were promoted");
      // …and notes is always drawn, so an all-keyed row says blank rather than
      // silently losing the row and changing the card's shape.
      const bRow = Object.assign({}, urRow, { notes: "Ticket: 0142335174938" });
      const bBlock = flightLegBlock({ flights: [bRow], members: [] }, { leg: "outbound", rows: [bRow] }, bRow);
      if (bBlock.indexOf("<dt>notes</dt>") < 0) fail.push("the notes row vanishes when every note line is keyed — it should read blank");
      // Same rule, the other two booked surfaces (2026-08-25). The car panel used
      // to print "what you paid" and "on points"; the stay panel led with its
      // all-in figure and carried a whole "the money" block. Both moved to the
      // cost tab. Rendered here rather than asserted on a helper, because the
      // failure mode is a price creeping back into the markup.
      const carHTML = carPanel({ transportation: [] },
        { id: 1, type: "car_rental", description: "Corolla", location: "AUS", seats: 5,
          pickup_time: "2026-09-01 10:00", dropoff_time: "2026-09-04 10:00",
          cost: 318.44, points_total: 9800, points_program: "Chase UR", status: "booked" },
        [], { land: null, fly: null });
      if (carHTML.indexOf("318.44") >= 0) fail.push("the price is back on the booked car — a paid-for rental's cost belongs in the cost tab");
      if (carHTML.indexOf("9,800") >= 0 || carHTML.indexOf("9800") >= 0) fail.push("the award points are back on the booked car");
      const sHead = document.createElement("div"), sList = document.createElement("div");
      stayPanel(sHead, sList, { start_date: "2026-09-01", end_date: "2026-09-04" },
        { id: 1, status: "booked", name: "the house", check_in: "2026-09-01 15:00",
          check_out: "2026-09-04 11:00", total_cost: 1284.60, nightly_rate: 400,
          points_total: 36500, points_program: "World of Hyatt", deposit: 250 },
        [{ id: 1, status: "booked", total_cost: 1284.60 }]);
      const stayHTML = sHead.innerHTML + sList.innerHTML;
      if (stayHTML.indexOf("1,284.60") >= 0) fail.push("the all-in total is back on the booked stay — a paid-for room's price belongs in the cost tab");
      if (stayHTML.indexOf("36,500") >= 0) fail.push("the award points are back on the booked stay");
      if (stayHTML.indexOf("250.00") >= 0) fail.push("the security deposit is back on the booked stay");
      if (stayHTML.indexOf("check-in") < 0) fail.push("the booked stay headline lost the check-in day it was meant to fall back to");
      // 1284.60 over 3 nights, 4 ways = $107.05 a head a night. The split line went
      // with the rest of the prices - the cost tab owns what each person owes.
      if (stayHTML.indexOf("per person per night") >= 0) fail.push("the per-person split is back on the booked stay — the cost tab owns what each person owes");
      if (stayHTML.indexOf("splitting") >= 0) fail.push("the splitting stepper is back on the booked stay with nothing left for it to reprice");
      // …and it is still the comparison board's whole point.
      if (staySplit({ total_cost: 1284.60, check_in: "2026-09-01", check_out: "2026-09-04" }, { party: 4 })
            .indexOf("per person per night") < 0) fail.push("the comparison board lost its per-person-per-night line — that board is the research panel");
      // ── A HOTEL IS NOT A HOUSE ──────────────────────────────────────────
      // One row, rendered twice. The Hyatt was being drawn in a rental's shape:
      // asked for a door code it does not have, for house rules instead of the
      // fine print, and never asked what room was booked or what the desk holds
      // on the card. The two key sets are the contract the nudge lists attach to,
      // so a section label quietly renamed has to fail here rather than at a
      // keypad.
      const stayOf = (extra) => {
        const hd = document.createElement("div"), ls = document.createElement("div");
        stayPanel(hd, ls, { start_date: "2026-09-01", end_date: "2026-09-04" },
          Object.assign({ id: 1, status: "booked", name: "the stay", check_in: "2026-09-01 15:00",
            check_out: "2026-09-04 11:00", address: "1 Main St",
            check_in_method: "Door code 4736 \u00b7 front-door keypad",
            house_rules: "Quiet after 10pm" }, extra),
          [{ id: 1, status: "booked" }]);
        return ls.innerHTML;
      };
      const hotelHTML = stayOf({ stay_type: "hotel", room_type: "2 queens, 338 sq ft",
        resort_fee: "none", late_checkout: "2pm on request" });
      if (hotelHTML.indexOf("checking in") < 0) fail.push("a hotel's stay panel lost its checking-in block");
      if (hotelHTML.indexOf("the fine print") < 0) fail.push("a hotel's stay panel lost the fine print");
      if (hotelHTML.indexOf("what's in the house") >= 0) fail.push("a hotel is being asked what is in the house");
      if (hotelHTML.indexOf("the house rules") >= 0) fail.push("a hotel is being drawn a rental's house-rules block");
      // doorCell is a rental's helper: a hotel checks in at a desk, so its
      // check-in method prints as the prose it was typed as, never as a keypad
      // code in display type.
      if (hotelHTML.indexOf("door-code") >= 0) fail.push("a hotel's front desk is being rendered as a door keypad");
      if (hotelHTML.indexOf("2 queens") < 0) fail.push("the booked room type is not being drawn anywhere on a hotel's panel");
      const rentalHTML = stayOf({ stay_type: "rental", amenities: "Bathtub\n\nFire pit" });
      if (rentalHTML.indexOf("getting in") < 0) fail.push("a rental's stay panel lost its getting-in block");
      if (rentalHTML.indexOf("what's in the house") < 0) fail.push("a rental's stay panel lost its amenity grid");
      if (rentalHTML.indexOf("door-code") < 0) fail.push("a rental's door code is no longer lifted out of the prose");

      // ── WHAT IS STILL MISSING ───────────────────────────────────────────
      // The binding rule, and the one thing here that must never regress: a blank
      // field is a SUGGESTION, so nothing it renders may read as an error. These
      // cases hold the three edges that would turn it into one: prompting down a
      // shortlist nobody has decided, prompting a guest who cannot fill anything
      // in, and offering a button that opens an empty box.
      const booked = { id: 7, status: "booked", stay_type: "hotel" };
      const oneFilled = gapList("housing", Object.assign({}, booked, { resort_fee: "none" }),
        ["resort_fee", "incidental_hold", "breakfast", "late_checkout"]);
      const nPend = (s) => (s.match(/class="hub-pending"/g) || []).length;
      if (nPend(oneFilled) > 3) fail.push(`a section is prompting more than three blanks at once: ${nPend(oneFilled)}`);
      if (oneFilled.indexOf("resort_fee") >= 0) fail.push("a field that IS filled in is still being prompted for");
      if (gapList("housing", Object.assign({}, booked, { status: "considering" }), ["resort_fee"]))
        fail.push("a shortlist row nobody has decided is being prompted to fill itself in");
      if (gapList("housing", Object.assign({}, booked, { status: "rejected" }), ["resort_fee"]))
        fail.push("a ruled-out row is being prompted to fill itself in");
      {
        // isGuest() reads the body class the server stamps on a shared link, not
        // the viewer name, so that is what has to be flipped here.
        const wasGuest = document.body.classList.contains("guest");
        document.body.classList.add("guest");
        try {
          const asGuest = gapList("housing", booked, ["resort_fee", "incidental_hold"]);
          if (asGuest.indexOf("stay-add") >= 0) fail.push("a guest is being offered a button that would fail on a read-only link");
          if (asGuest.indexOf('class="hub-pending"') < 0) fail.push("a guest lost the line saying what is still missing — they read it, they just cannot fill it");
        } finally { if (!wasGuest) document.body.classList.remove("guest"); }
      }
      // Imported off a listing, on no form: the sentence stands, the button does
      // not, because there is no box for it to open.
      const imported = gapList("housing", booked, ["amenities", "photos"]);
      if (imported.indexOf('class="hub-pending"') < 0) fail.push("the imported fields lost their line saying nothing has been read in yet");
      if (imported.indexOf("<button") >= 0) fail.push("an imported field is offering a button that would open an empty box");
      // A key the row's own form cannot reach says nothing at all rather than
      // offering a dead affordance.
      if (gapList("housing", booked, ["deposit"])) fail.push("a field on neither form is being prompted with nowhere to type it");
      // The whole point of the cap and of caller-side suppression: a section made
      // ONLY of prompts does not render, so a hotel with no fees on top prints no
      // heading over three things it does not have.
      const bareHTML = stayOf({ stay_type: "hotel" });
      if (bareHTML.indexOf("what it costs on top") >= 0)
        fail.push("a section with nothing real in it is printing a heading over its own prompts");

      // ── THE SAME PROMPT, OFF THE STAY TAB ───────────────────────────────
      // A boarding pass and a booked car are the other two committed rows with
      // blanks somebody could fill, so they get the same helper, the same guest
      // rule and the same cap. Three edges held here: a pass gains a real button
      // where it used to print a dead sentence; a blank passenger is still never
      // prompted, because blank means his own seat; and a row that lives in a
      // table rather than a panel gains nothing at all, because a prompt in a
      // table cell is the punch-list reading this whole thing avoids.
      {
        // Breeze, not Southwest: TERMINALS knows Southwest at LGA and fills the
        // terminal in, so the pass would never ask and this check would lie.
        const leg = { id: 3, status: "booked", airline: "Breeze", flight_num: "561",
          from_airport: "LGA", to_airport: "CMH", direction: "outbound",
          departure_time: "2026-09-01 08:00", arrival_time: "2026-09-01 10:20", notes: "" };
        const pass = flightLegBlock({ start_date: "2026-09-01" }, { leg: "outbound" }, leg, "");
        if (pass.indexOf('data-addfield="flights:') < 0)
          fail.push("a booked pass with no confirmation offers no way to add one");
        if (gapCell("flights", leg, "passenger"))
          fail.push("a blank passenger is being prompted, and blank there means his own seat");
        if (gapCell("flights", Object.assign({}, leg, { status: "considering" }), "confirmation").indexOf("<button") >= 0)
          fail.push("a fare nobody has bought is being offered a box to type a confirmation into");
        if (pass.indexOf("which terminal it leaves from") < 0)
          fail.push("a pass with no terminals on it says nothing about them");
        const car = { id: 5, status: "booked", type: "car_rental", description: "midsize" };
        const carHTML = carPanel({}, car, [car], { land: null, fly: null });
        const nCar = (carHTML.match(/class="hub-pending"/g) || []).length;
        if (!nCar) fail.push("a booked car with nothing filled in is prompting nothing");
        if (nCar > 3) fail.push(`a booked car is prompting more than three blanks at once: ${nCar}`);
        if (/<td[\s>]/.test(carHTML)) fail.push("a nudge is being rendered into a table cell");
        const bus = { id: 9, status: "booked", type: "bus", description: "Dino Express" };
        if (otherHTML({ transportation: [bus] }).indexOf("hub-pending-row") >= 0)
          fail.push("a row with no panel of its own is being prompted inside a table");
      }

      // The photo strip's one piece of parsing. A caption is optional and tab-
      // separated; a line that isn't a URL is dropped rather than drawn as a
      // broken image, which is what a half-written column would otherwise render.
      const pics = photoItems("https://a.example/1.jpg\nhttps://a.example/2.jpg\tBedroom 1\nnot a url\n");
      if (pics.length !== 2) fail.push("the stay's photo strip is no longer dropping non-URL lines");
      if (pics[1].c !== "Bedroom 1" || pics[0].c !== "") fail.push("the stay's photo captions no longer split off the tab");
      // …and Hub keeps every figure - this fold is guest-only, a payback
      // breakdown for other travellers. His own words: "for me I want the true
      // point cash spread." $192.77 cash + $400 housing, 10,500 UR untouched;
      // priceText() in this file adds the UR's cash value alongside it for his
      // own reference, but this total never folds it in.
      const hubM = TC.tripMoney(guestT, 1);
      eq(hubM.committed.cash, 592.77, "Hub's own total lost the flight fare along with the guest's");
      eq(hubM.committed.ur, 10500, "Hub's own total lost the flight's UR — that pool belongs in the cost tab");
      // priceText shows the true spread on Hub: real cash, real points, and the
      // points' cash value as a bracketed reference - never folded into one.
      const pt = U.priceHtml({ cash: 192.77, ur: 10500 });
      if (pt.indexOf("192.77") < 0 || pt.indexOf("10,500") < 0 || pt.indexOf("131.25") < 0) fail.push("priceText is not showing the true cash+points spread with the UR's cash value");
      if (pt.indexOf("ur-mark") < 0) fail.push("the points figure lost its Chase mark");
      // The mark is Chase's real geometry, traced from their logo file, and it is
      // easy to "tidy" back into something that is merely octagon-shaped. Four
      // pieces, and the two coordinates that make it a pinwheel rather than a
      // ring: the outer corner arc lands at 0.847, the bevel tip at 23.428.
      if ((CHASE.match(/<path/g) || []).length !== 4) fail.push("the Chase mark is not four pieces any more — it is a pinwheel, not a ring");
      if (CHASE.indexOf("7.737.847") < 0 || CHASE.indexOf("23.428") < 0) fail.push("the Chase mark's geometry was redrawn — restore it from Chase's own logo file, not by hand");
      if (pt.indexOf("points") >= 0) fail.push("the word 'points' is back next to the mark — the mark is the unit");
      const ptPlain = U.priceHtml({ cash: 0, ur: 10500 }, true);
      if (ptPlain.indexOf("<") >= 0) fail.push("plain priceText is leaking markup into a title attribute");
      if (ptPlain.indexOf("10,500 points") < 0) fail.push("the tooltip figure has no unit at all — nothing can render the mark there");
      // …and his own board never converts. Points are what he actually spent, and
      // a cash equivalent on his side would be a number he did not pay.
      const hubAward = TC.tripMoney({ housing: [{ id: 1, status: "booked", points_transfer: 24000 }] }, 1);
      eq(hubAward.committed.cash, 0, "Hub is inventing a dollar figure for an award stay he paid in points");
      eq(hubAward.committed.ur, 24000, "Hub lost the award stay's points to the guest conversion");
      document.body.classList.add("guest");
      // The public COST TAB accounts for flights - it is the settle-up surface, and
      // omitting the biggest line makes every total on it wrong. What it does not
      // carry is points: $192.77 cash + 10,500 UR at 1.25c = $324.02, plus a $400
      // stay. The flights BOARD still hides the per-leg fare; the accounting and
      // the booking detail are different questions.
      const gm = TC.tripMoney(guestT, 1);
      eq(gm.committed.cash, 724.02, "the guest cost tab has lost flights again, or is not converting their UR to dollars");
      eq(gm.committed.ur, 0, "the guest cost tab is still printing a points figure");
      if (!gm.byCategory.filter((c) => c.key === "flights")[0]?.total.cash) fail.push("the guest cost breakdown has no flights figure — the line he reported missing");
      const gRow = Object.assign({}, urRow, { notes: "Nonstop, 5h05m, Airbus A320\nPaid CA$267.60 including the change fee" });
      const gBlock = flightLegBlock({ flights: [gRow], members: [] }, { leg: "outbound", rows: [gRow] }, gRow);
      if (gBlock.indexOf("192.77") >= 0) fail.push("a guest's flight leg is still printing the fare");
      if (gBlock.indexOf("12,500") >= 0) fail.push("a guest's flight leg is still printing the award points");
      // The notes are free prose, and on these rows the prose IS the fare.
      const gNotes = guestSafeNotes("Nonstop, 5h05m, Airbus A320\nPaid CA$267.60 = CA$194.10 + CA$75.00 change fee\nTicket 0142335174938");
      if (gNotes.indexOf("267.60") >= 0) fail.push("a guest's flight notes are still carrying the fare in prose");
      if (gNotes.indexOf("Airbus A320") < 0) fail.push("the note strip is taking the aircraft line with the money line");
      if (gNotes.indexOf("0142335174938") < 0) fail.push("the note strip is reading a ticket number as money");
      // An expense row can BE the flight. El Salvador files a second passenger's
      // ticket under "Flights (Sophia)", which is not what EXPENSE_COVERS matches.
      // The public page is in dollars. A guest cannot act on "24,000 World of
      // Hyatt", so the UR pool converts at his chosen rate and folds into
      // cash - one currency per line, never "$0.00 + 24,000 UR".
      const award = { housing: [{ id: 1, status: "booked", points_transfer: 24000 }] };
      const gAward = TC.tripMoney(award, 1);
      eq(gAward.committed.cash, 300, "the guest cost tab is not converting an award stay to dollars at 1.25c");
      eq(gAward.committed.ur, 0, "the guest cost tab is still printing a points figure alongside the cash");
      // A stay redeemed straight out of an existing partner balance - no fresh
      // Chase transfer, so points_transfer is null - has to fall back to
      // points_total, or it reads as a $0 stay with nothing spent at all
      // (reported 2026-08-24: the Lost Lands hotel, 36,500 World of Hyatt
      // points, vanished from the cost chart because rowUR only read
      // points_transfer). Hub keeps the raw points; the guest mirror converts.
      document.body.classList.remove("guest");
      const pointsOnly = { housing: [{ id: 1, status: "booked", points_total: 36500, points_program: "World of Hyatt" }] };
      const hubPointsOnly = TC.tripMoney(pointsOnly, 1);
      eq(hubPointsOnly.committed.cash, 0, "Hub is inventing a dollar figure for a points-only stay");
      eq(hubPointsOnly.committed.ur, 36500, "Hub dropped a points-only stay's points when there was no fresh Chase transfer");
      document.body.classList.add("guest");
      const guestPointsOnly = TC.tripMoney(pointsOnly, 1);
      eq(guestPointsOnly.committed.cash, 456.25, "the guest cost tab is not converting a points-only stay (no points_transfer) to dollars at 1.25c");
      eq(guestPointsOnly.committed.ur, 0, "the guest cost tab is still printing raw points for a points-only stay");
    } finally { if (wasGuest) document.body.classList.add("guest"); else document.body.classList.remove("guest"); }
    // PER PERSON, ALWAYS. Four heads, a $4,000 stay, his own $500 seat. A bar
    // chart compares its bars, so the stay has to enter at $1,000 - fed the
    // group breakdown it drew four times too long beside a flight that was one
    // ticket, which is the "the stay is 80% of this trip" he reported.
    const shared4 = { members: [{ id: 1, name: "Sam Rivera", contact_slug: "sam-rivera" },
        { id: 2, name: "Owen Hale" }, { id: 3, name: "Jody Tran" }, { id: 4, name: "Megan Lee" }],
      housing: [{ id: 1, status: "booked", total_cost: 4000 }],
      flights: [{ id: 1, status: "booked", cost: 500 }] };
    const sharedChart = costChart(TC.tripMoney(shared4));
    if (sharedChart.indexOf("4,000.00") >= 0) fail.push("the cost chart is back on the group's stay — a whole house beside one seat is what made the stay read as most of the trip");
    if (sharedChart.indexOf("1,000.00") < 0) fail.push("the cost chart lost the per-person stay figure");
    if (sharedChart.indexOf("500.00") < 0) fail.push("the cost chart lost his flight beside the split stay");
    // One row, two people. Denver's outbound is literally booked "Aaron + Jasmine",
    // and a whole-string match reports both of them as having no flight.
    const joint = { members: [{ id: 1, name: "Sam Rivera", contact_slug: "sam-rivera" }, { id: 2, name: "Owen Hale" }, { id: 3, name: "Jody Tran" }],
      flights: [{ id: 1 }, { id: 2, passenger: "Aaron + Jasmine" }] };
    if (flightlessMembers(joint).length) fail.push("a joint ticket is not accounting for both people on it");
    if (memberFor(joint, "Aaron + Jasmine")) fail.push("a joint ticket is being printed under one member's name");
    // Two members sharing a surname is an ambiguity. Binding either one would put
    // a ticket against the wrong person and clear the wrong name off the gap list.
    const twins = { members: [{ id: 1, name: "Dan Ortiz" }, { id: 2, name: "Amanda Ortiz" }], flights: [{ id: 1, passenger: "J Ortiz" }] };
    if (memberFor(twins, "J Ortiz")) fail.push("a shared surname is being guessed at instead of left unbound");
    if (flightlessMembers(twins).length !== 2) fail.push("an unbound ticket is clearing somebody off the missing list anyway");
    // A cancelled row is not a seat. Counting it would report a member as covered
    // by a flight they are not on.
    if (flightlessMembers({ members: [{ id: 1, name: "Nina Ford" }], flights: [{ id: 1, passenger: "Nina Ford", status: "cancelled" }] }).length !== 1)
      fail.push("a cancelled ticket is still counting as a member's flight");
    // One record locator or two is the thing you need at 5am, so it is the split
    // line's whole job now that the bag toggle is gone.
    const oneBk = bookedSplit([{ row: { airline: "Southwest", confirmation: "BGS5LY" } }, { row: { airline: "Southwest", confirmation: "BGS5LY" } }]);
    if (oneBk !== "Southwest · one booking · BGS5LY") fail.push(`bookedSplit no longer collapses two legs on one locator: ${oneBk}`);
    const twoBk = bookedSplit([{ row: { airline: "United", confirmation: "AAA" } }, { row: { airline: "Delta", confirmation: "BBB" } }]);
    if (twoBk !== "United + Delta · 2 bookings · AAA, BBB") fail.push(`bookedSplit no longer reports two separate bookings: ${twoBk}`);

    // Both ends of a stay are instants: end === start, which is the axis being told
    // to draw a rule at 3pm rather than a box from 3 to 3:30 that nobody agreed to.
    // Not an open bar either - open means the duration is unknown, this one is zero.
    const stayBlk = [];
    const stayAt = { date: "2026-09-10", minutes: 15 * 60 };
    addLogi((_d, it) => stayBlk.push(it), ["2026-09-10"], { "2026-09-10": 0 }, stayAt, stayHour(stayAt), { kind: "stay", raw: "Sep 10, 3:00 PM" });
    if (stayBlk[0].end !== 15 * 60 || stayBlk[0].open) fail.push(`a check-in is no longer a zero-length instant: ${JSON.stringify(stayBlk[0])}`);
    if (stayHour({ date: "2026-09-10", minutes: null }) !== null) fail.push("a stay stamp with no clock is being given an invented hour");
    // The whole treatment hangs off end === start being recognised in put(), and off
    // instants staying out of the lane packer - a departure that claims a lane puts
    // the day's real blocks at half width for a row that is two pixels tall.
    const packed = [{ start: 615, end: 615 }, { start: 720, end: 840 }]
      .map((b) => (Object.assign({}, b, { pos: b.start, inst: b.start != null && b.end === b.start })));
    lanes(packed);
    if (!packed[0].inst || packed[0].of !== 1) fail.push("a zero-length row is not being read as an instant");
    if (packed[1].of !== 1) fail.push(`an instant is stealing a lane from a real block: of=${packed[1].of}`);
    instantLabels(packed);
    if (packed[0].labOff !== -20) fail.push("a lone instant's label is not sitting above its own rule");
    const run = [600, 610, 620].map((m) => ({ start: m, end: m, pos: m, inst: true }));
    instantLabels(run);
    if (new Set(run.map((b) => b.labPos)).size !== 1 || run[2].labOff - run[0].labOff !== 36)
      fail.push(`a run of instants is not stacking its labels off one anchor: ${JSON.stringify(run.map((b) => [b.labPos, b.labOff]))}`);

    // The three ground boards all read one table, so the only thing keeping a
    // Turo off the bus board is this map - and the only thing keeping a rental
    // from being flagged wrongly is the window arithmetic.
    if (busOf({ type: "Car_Rental" }) !== "carrental" || busOf({ type: "turo" }) !== "turo"
      || busOf({ type: "bus" }) !== "other" || busOf({}) !== "other") fail.push("busOf no longer files rows onto the right ground board");
    const win = { land: stampMins({ date: "2026-09-10", minutes: 8 * 60 + 40 }), fly: stampMins({ date: "2026-09-14", minutes: 17 * 60 + 15 }), airport: "DEN" };
    const tagOf = (row) => rentalTags(row, { window: win, best: null }).map((x) => x.t);
    const good = { pickup_time: "2026-09-10 09:30", dropoff_time: "2026-09-14 14:30", seats: 99 };
    if (tagOf(good).indexOf("covers your flights") < 0) fail.push("a car inside the flight window no longer reads as covering it");
    // "before ANYONE lands" - the tag was rewritten when the window went from one
    // landing to a list of them, and this assertion was left on the old wording,
    // so it failed on every page load and drowned every real check under it.
    if (tagOf(Object.assign({}, good, { pickup_time: "2026-09-10 06:00" })).indexOf("before anyone lands") < 0) fail.push("a pickup before landing is no longer flagged");
    if (tagOf(Object.assign({}, good, { dropoff_time: "2026-09-14 18:00" })).indexOf("drops off after takeoff") < 0) fail.push("a drop-off after the return flight is no longer flagged");
    if (tagOf(Object.assign({}, good, { pickup_time: "2026-09-10 14:00" })).indexOf("5h wait after landing") < 0) fail.push("the wait-after-landing gap no longer reports in hours");
    // The fallback link a car row falls back to when it has no url of its own.
    // Kayak wants ISO dates, Turo wants mm/dd/yyyy - get the format wrong and the
    // link silently lands on an undated board, which is the bug this replaced.
    if (carLink(Object.assign({}, good, { type: "car_rental" }), win) !== "https://www.expedia.com/carsearch?locn=DEN&date1=09%2F10%2F2026&time1=930AM&date2=09%2F14%2F2026&time2=230PM") fail.push("carLink no longer builds the dated Expedia board for a counter rental");
    // The noon hour, pinned against a link pulled off the live site 2026-08-13.
    if (carLink(Object.assign({}, good, { pickup_time: "2026-09-10 12:30", type: "car_rental" }), win) !== "https://www.expedia.com/carsearch?locn=DEN&date1=09%2F10%2F2026&time1=1230PM&date2=09%2F14%2F2026&time2=230PM") fail.push("carLink no longer spells a 12:30pm pickup as Expedia does (1230PM)");
    if (carLink(Object.assign({}, good, { type: "turo" }), win) !== "https://turo.com/us/en/car-rental/united-states/den") fail.push("carLink no longer sends a Turo row to the airport's category page");
    if (carLink(Object.assign({}, good, { type: "car_rental" }), Object.assign({}, win, { airport: "" })) !== "") fail.push("carLink invents a link for a row with no landing airport");
    if (carLink({ type: "car_rental" }, win) !== "") fail.push("carLink invents a link for a row with no pickup or drop-off");
    // …and which of the two a row actually gets. Every url below is a real one
    // that was sitting in trips.db on 2026-08-17, which is when Sam reported
    // the board's links as broken again.
    const noonCar = Object.assign({}, good, { pickup_time: "2026-09-10 12:30", type: "car_rental" });
    const board = "https://www.expedia.com/carsearch?locn=DEN&date1=09%2F10%2F2026&time1=1230PM&date2=09%2F14%2F2026&time2=230PM";
    if (carHref(Object.assign({}, noonCar, { url: "https://rental24h.com/search/availability?pickupDateTime=2026-09-10T12:30:00&returnDateTime=2026-09-14T14:30:00#/vehicles" }), win).indexOf("rental24h") < 0) fail.push("carHref is throwing away a dated ISO search that works");
    if (carHref(Object.assign({}, noonCar, { url: "https://www.expedia.com/carsearch?locn=DEN&date1=9%2F10%2F2026&time1=1230PM" }), win).indexOf("date1=9%2F10%2F2026") < 0) fail.push("carHref no longer recognises Expedia's unpadded m/d/yyyy as this row's date");
    if (carHref(Object.assign({}, noonCar, { url: "https://www.milemarkervanrentals.com/results/?pickup=09%2F10%2F2026&pickuptime=12%3A30+PM" }), win).indexOf("milemarker") < 0) fail.push("carHref no longer recognises a zero-padded mm/dd/yyyy as this row's date");
    if (carHref(Object.assign({}, noonCar, { url: "https://www.nucarrentals.com/" }), win) !== board) fail.push("a bare vendor homepage is being linked again instead of the dated board");
    if (carHref(Object.assign({}, noonCar, { url: "https://www.expedia.com/carsearch/details?date1=9%2F10%2F2026&piid=AQh3XDzU&totalPriceShown=634.99" }), win) !== board) fail.push("a stale Expedia piid offer token is being linked again instead of the dated board");
    if (carHref(Object.assign({}, noonCar, { url: "" }), win) !== board) fail.push("a car row with no url of its own no longer falls back to the dated board");
    if (carHref(Object.assign({}, good, { type: "turo", url: "https://turo.com/us/en/suv-rental/united-states/den" }), win).indexOf("suv-rental") < 0) fail.push("the date test is eating a Turo listing url, which can never carry a date");
    // Falling back to nothing is worse than falling back to the homepage.
    if (carHref(Object.assign({}, noonCar, { url: "https://www.nucarrentals.com/" }), Object.assign({}, win, { airport: "" })) !== "https://www.nucarrentals.com/") fail.push("carHref drops the row's link entirely when no board can be built");
    // The booked leg's link out. Every one of these was checked against the live
    // page on 2026-08-17 - fr24 answers "no data available" for the zero-padded
    // ident, so the strip is the difference between a working link and a dead one.
    if (flightTrackLink({ flight_num: "WN 0561" }) !== "https://www.flightradar24.com/data/flights/wn561") fail.push("flightTrackLink no longer strips the zero padding fr24 rejects");
    if (flightTrackLink({ flight_num: "UA2110" }) !== "https://www.flightradar24.com/data/flights/ua2110") fail.push("flightTrackLink no longer reads an unspaced flight number");
    if (flightTrackLink({ flight_num: "B6 123" }) !== "https://www.flightradar24.com/data/flights/b6123") fail.push("flightTrackLink no longer handles a carrier code carrying a digit");
    // A bare number has no carrier, and "56" + "1" would link to a flight that
    // isn't this one. No link is right; the leg falls back to the route board.
    if (flightTrackLink({ flight_num: "561" }) !== "") fail.push("flightTrackLink invents a carrier for a bare flight number");
    if (flightTrackLink({ flight_num: "" }) !== "" || flightTrackLink({}) !== "") fail.push("flightTrackLink invents a link for a row with no flight number");
    // A crew member's ticket shares the flights table, so the ONLY thing keeping it
    // out of his fare comparison and his trip total is this filter. If it ever
    // stops holding, Akshay's Delta legs start bidding against Sam's own seat.
    const crewMix = { flights: [{ id: 1, cost: 226.39, status: "booked" }, { id: 2, cost: 480, status: "booked", passenger: "Akshay" }] };
    if (myFlights(crewMix).length !== 1 || myFlights(crewMix)[0].id !== 1) fail.push("myFlights no longer keeps a crew member's leg out of the fare board");
    if (myFlights({ flights: [{ id: 3, passenger: "  " }] }).length !== 1) fail.push("a whitespace-only passenger is being read as somebody else's ticket");
    // The day map's trail. A crew leg on the trail walks the route out to the
    // airport and back for a landing that isn't yours, which is what this stops.
    const mineSet = new Set(["flights:1"]);
    const dayIn = markTrail([
      { sel: "flights:1", kind: "flight", timed: true },    // your arrival - anchors
      { sel: "flights:2", kind: "flight", timed: true },    // Aaron + Jasmine - floats
      { sel: "9", kind: "act", timed: true },               // pick up Akshay - anchors
      { sel: "flights:3", kind: "flight", timed: true },    // Akshay - floats
      { sel: "12", kind: "act", timed: false },             // all-day, still a floater
    ], mineSet);
    const onTrailSels = dayIn.filter((s) => s.trail).map((s) => s.sel).join(",");
    if (onTrailSels !== "flights:1,9") fail.push(`the day map trail no longer reads as your flight plus real stops — got ${onTrailSels}`);
    // Two of your own legs on one day (a same-day connection typed as two rows):
    // both are your movement. Keeping only the first is what drew Columbus day 1
    // as IAD straight to the Hyatt, with CMH never touched.
    const twoMine = markTrail([
      { sel: "flights:1", kind: "flight", timed: true },
      { sel: "flights:4", kind: "flight", timed: true },
    ], new Set(["flights:1", "flights:4"]));
    if (twoMine.filter((s) => s.trail).length !== 2) fail.push("a same-day connection is losing its second leg off the trail");
    // A flown leg is not a road route. EWR→IAD→CMH→stay must cut into two air
    // legs and one ground run, or OSRM gets asked to drive Newark to Columbus.
    const air = splitRuns([[40.69, -74.18, false], [38.95, -77.45, true], [40.00, -82.89, true], [39.96, -82.99, false]]);
    if (air.map((r) => (r.air ? "air" : "ground")).join(",") !== "air,air,ground") fail.push(`flight legs are being routed on roads — got ${air.map((r) => (r.air ? "air" : "ground")).join(",")}`);
    if (splitRuns([[1, 1, false], [2, 2, false], [3, 3, false]]).length !== 1) fail.push("an all-ground day is being cut into more than one routed run");
    // EWR→IAD then IAD→CMH: the connection airport is one pin, not two stacked.
    const conn = dropRepeatAirport([
      { sel: "flights:14", kind: "flight", lat: 40.69, lng: -74.18 },
      { sel: "flights:14", kind: "flight", lat: 38.95, lng: -77.45 },
      { sel: "flights:15", kind: "flight", lat: 38.95, lng: -77.45 },
      { sel: "flights:15", kind: "flight", lat: 40.00, lng: -82.89 },
    ]);
    if (conn.length !== 3) fail.push("a connection airport is drawing two pins on the same spot");
    // Overlapping pins separate to a readable gap without leaving their own spot:
    // a pair 6px apart ends U.PIN_PX apart and 8px from where it started, not on a
    // ring around the pair's centre.
    const near = relax([{ x: 100, y: 100 }, { x: 106, y: 100 }]);
    if (Math.round(near[1].x - near[0].x) !== U.PIN_PX || near[0].y !== 100) fail.push("overlapping pins are no longer separating along their own axis");
    if (Math.round(near[0].x) !== 92 || Math.round(near[1].x) !== 114) fail.push("pins are being moved further than the overlap needs");
    const same = relax([{ x: 50, y: 50 }, { x: 50, y: 50 }, { x: 50, y: 50 }]);
    for (let i = 0; i < 3; i++) for (let k = i + 1; k < 3; k++) {
      if (Math.hypot(same[i].x - same[k].x, same[i].y - same[k].y) < U.PIN_PX - 0.5) fail.push("three pins on one spot are still overlapping after relax");
    }
    // Home bookends. A middle day leaves the stay and comes back; the first and
    // last days are open at the airport end and must not be closed artificially,
    // and neither end may draw a zero-length leg to the house it already sits on.
    const home = { lat: 39.8, lng: -105.1 }, spot = [39.7, -104.9];
    const mid = trailPath([spot], { start: home, end: home });
    if (mid.length !== 3 || mid[0][0] !== home.lat || mid[2][0] !== home.lat) fail.push("a middle day no longer starts and ends at the stay");
    const first = trailPath([[39.86, -104.67], [home.lat, home.lng]], { start: null, end: home });
    if (first.length !== 2) fail.push("day 1 is drawing a leg from the stay back to the stay");
    const last = trailPath([[home.lat, home.lng], spot], { start: home, end: null });
    if (last.length !== 2) fail.push("the last day is drawing a leg from the stay back to the stay");
    if (trailPath([], { start: home, end: home }).length !== 1) fail.push("an empty day is drawing a route from the stay to itself");
    if (typeof U.confirmDelete !== "function") fail.push("confirmDelete is not defined — every delete button is dead");
    if (typeof U.bindDeletes !== "function") fail.push("bindDeletes is not defined — row delete buttons are unwired");
    if (!/data-del="flights\/7"/.test(delBtn("flights/7", "x"))) fail.push("delBtn no longer emits the API path bindDeletes reads");
    // ── THE FLOWN LEG AND THE MARK IT LANDS ON ──────────────────────────────
    // The bow is what tells out from back when both legs share two endpoints, so
    // the arc has to actually leave the chord AND flip when the direction does.
    // Get the sign wrong and a round trip draws as one line twice.
    const A = [40.6413, -73.7781], B = [39.8561, -104.6737];
    const oub = arcPts(A, B, U.ARC_BEND), bak = arcPts(B, A, U.ARC_BEND);
    if (oub.length !== U.ARC_N + 1) fail.push(`arcPts no longer returns ARC_N+1 points: ${oub.length}`);
    if (Math.abs(oub[0][0] - A[0]) > 1e-9 || Math.abs(oub[U.ARC_N][1] - B[1]) > 1e-9) fail.push("the arc no longer starts and ends on the two airports");
    const chordLat = (A[0] + B[0]) / 2, bow = oub[U.ARC_N / 2][0] - chordLat;
    if (Math.abs(bow) < 0.05) fail.push("the arc is drawing flat — nothing distinguishes it from the straight line");
    if (Math.abs(bow + (bak[U.ARC_N / 2][0] - chordLat)) > 1e-9) fail.push("out and back are bowing the same way, so a round trip draws as one line");
    // The way home carries its own colour, and the flag has to survive the whole
    // trip from the flight row to the polyline: direction → block.back → the stop
    // → the [lat,lng,air,back] tuple → the run.
    const runs = splitRuns([[1, 1, false, false], [2, 2, true, true]]);
    if (runs.length !== 1 || !runs[0].air || !runs[0].back) fail.push(`splitRuns is dropping the return flag off a flown leg: ${JSON.stringify(runs)}`);
    // At the wide frame the whole ground day and its departure airport are ONE
    // place: one mark, numbered as a range, named for the airport the leg leaves.
    const mg = mergedMark([1, 2, 3, 4].map((k) => ({ item: { _num: String(k), kind: "act", title: `spot ${k}` } }))
      .concat([{ item: { _num: "5", kind: "flight", title: "DEN · Flight to NYC" } }]));
    if (mg.num !== "1–5") fail.push(`the merged wide mark is not reading as a range: ${mg.num}`);
    if (markName(mg.stop) !== "DEN") fail.push(`the merged mark is not anchored on its airport: ${markName(mg.stop)}`);
    if (markName({ kind: "act", title: "Larimer Square" }) !== "Larimer Square") fail.push("markName is truncating a plain activity title");
    } finally { window.TRIP_VIEWER = savedViewer; }
    if (fail.length) {
      console.error(`trips: money self-check failed —\n  ${fail.join("\n  ")}`);
      status("money self-check failed", fail[0]);
    }
    return fail;
  }

Object.assign(U, { selfCheck });
})();
