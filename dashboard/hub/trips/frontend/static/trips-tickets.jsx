/* hub · trips page, tickets (2026-10-13): React-migration port of trips.js lines 4982-5788 (whose day, seats,
   tickets, route). Pure helpers and markup builders, no network. Plain functions inside an IIFE, assigned onto
   TripsUI; see trips-core.jsx for the shared interface. */
(() => {
const U = window.TripsUI;
const { esc, state, money, rowCost, T, TC, haversine, viewerKey, isViewer, isCar, isDead, isCommitted, isSettled, myFlights,
  carPickup, carDropoff, chosenStay, lastStay } = U;
const { stampMins, picked, fitsParty, legsOf, flightLegs, dayShort, stampShort,
  airlineFacts, knownAirline, lines, ctxLink } = U.fwd("stampMins", "picked", "fitsParty", "legsOf",
  "flightLegs", "listFlights", "timelineHTML", "dayShort", "stampShort", "airlineFacts", "knownAirline",
  "stayFacts", "lines", "ctxLink");
  // ── WHOSE DAY IS THIS, EXACTLY ───────────────────────────────────────────────
  // A fare is a time, not a price. The 9:05pm saves $65 and costs the evening; the
  // 6:30am lands you at the door five hours before check-in. Neither is visible in
  // a table of numbers, so the pick gets walked forward through the real day.
  //
  // Two things this read got wrong for a crew that does not fly together, both
  // fixed here (Sam, 2026-08-26: "if Leo is viewing it, his information is not
  // 'wheels down at 8:40' because that's not his flight"):
  //
  //  1. It was always SAM'S day. flightSel() reads myFlights(), which is
  //     blank-passenger rows by definition, so every guest on the shared link was
  //     handed the trip owner's landing time as their own. readerLegs() picks the
  //     legs belonging to whoever is actually reading.
  //  2. It ignored the car. On the Denver trip one minivan is collected at 2pm by
  //     the flight that lands at 12:30; the 8:40 pair have five hours to fill and
  //     the 8:39pm arrival is landing after the car has already driven to the
  //     house. Those are three different days, and the difference is entirely
  //     "when do you land relative to the pickup" - which is data, not a name.
  const CHECK_IN = 15 * 60, CHECK_OUT = 11 * 60;   // fallback only - see stayClock
  // DRIVE_MIN is the fallback now, not the answer - see driveMin() below.
  const BAGS_MIN = 25, DRIVE_MIN = 40, AIRPORT_LEAD = 140, AIRPORT_LEAD_INTL = 200;
  // Curb to keys at an off-airport counter: the shuttle plus the queue. Every car
  // on this board is off-airport (DEN has no in-terminal counter), so it is one
  // constant rather than a per-row field nobody would fill in.
  const LOT_MIN = 35, SHUTTLE_MIN = 20;

  // Drive time from the coordinates the rows already carry, instead of one number
  // for every leg on every trip. DRIVE_MIN happened to be right for DEN → Arvada
  // and wrong for everything else - the pickup crew drives from an off-airport
  // counter, the last morning drives back to it, and the rail reported 40 minutes
  // for all of them.
  //
  // Straight line × a road factor, not a routing call: this page is served to
  // guests through the public mirror, and a client-side fetch to a directions host
  // is a dependency the share link should not carry. 1.75 min per straight-line
  // mile reproduces the 40 min everyone already lives with for DEN → Arvada
  // (22.8 mi), which is the calibration this number is tuned against.
  //
  // ponytail: one factor, one knob. It is a metro-highway average - a mountain
  //   road or a Manhattan crosstown mile is slower, and the fix is ROAD_FACTOR or
  //   a per-trip field, never a call site doing its own arithmetic.
  const ROAD_FACTOR = 1.75, DRIVE_FLOOR = 10;
  const ptOf = (r) => (r && r.lat != null && r.lng != null) ? { lat: r.lat, lng: r.lng } : null;
  const airportPt = (code) => ptOf(state.trip?.airports?.[String(code || "").trim().toUpperCase()]);

  /* US airspace as boxes: the lower 48, Alaska, Hawaii, Puerto Rico, the USVI,
     Guam. The test runs ONE WAY on purpose. A point outside every box is certainly
     not in the United States, and that is the only direction anything downstream
     acts on. A point INSIDE is evidence of nothing - Toronto and Tijuana both land
     in the lower-48 box - so a leg that fails the test simply reads exactly as it
     did before. The inverse would be a page telling somebody to leave their
     passport at home on the strength of a rectangle, which is the one mistake this
     card must not be capable of making.

     ponytail: boxes, not a country lookup. Swap in an IATA-to-country table the
       day something needs to know WHICH country, rather than whether it is this
       one. */
  const US_BOXES = [
    [24.4, -125.0, 49.5, -66.9],    // lower 48
    [51.0, -180.0, 71.6, -129.0],   // Alaska
    [18.8, -160.3, 22.3, -154.7],   // Hawaii
    [17.8, -67.5, 18.6, -65.2],     // Puerto Rico
    [17.6, -65.1, 18.6, -64.5],     // US Virgin Islands
    [13.2, 144.5, 13.7, 145.0],     // Guam
  ];
  const inUS = (pt) => !!pt && US_BOXES.some((b) => pt.lat >= b[0] && pt.lat <= b[2] && pt.lng >= b[1] && pt.lng <= b[3]);
  // Both endpoints resolved AND one of them outside every box. An airport whose
  // coordinates were never cached is unknown, never international - same rule.
  function certainlyIntl(f) {
    const a = airportPt((f.from_airport || "").trim()), b = airportPt((f.to_airport || "").trim());
    return !!a && !!b && (!inUS(a) || !inUS(b));
  }
  // The one knob both the day-of checkpoints and the transport tab's departure read
  // turn, so the two surfaces cannot name different times to be at the same
  // terminal. Domestic is two hours plus twenty; international is the carriers' own
  // three, plus the same twenty. Both are rules of thumb and the cards say so.
  const airportLead = (f) => (certainlyIntl(f) ? AIRPORT_LEAD_INTL : AIRPORT_LEAD);
  // The rental counter, when it has been placed. Most off-airport counters are a
  // street number OSM has never heard of, so this is null far more often than not
  // and the fallback is the normal path, not the error path.
  const carPt = (x) => ptOf(x);
  function driveMin(a, b) {
    const mi = a && b ? haversine(a.lat, a.lng, b.lat, b.lng) : null;
    if (mi == null) return DRIVE_MIN;
    return Math.max(DRIVE_FLOOR, Math.round(mi * ROAD_FACTOR / 5) * 5);
  }
  // How near the pickup you have to land to be the crew collecting the car, and
  // how late the counter will plausibly hold it for you. Outside that band you are
  // either killing time before it exists or chasing it after it has gone.
  const PICKUP_SLACK = 120, PICKUP_GRACE = 45;
  // "+1d", not " next day" - the clock column is one number wide and the words
  // wrapped a landing time over three lines. The day offset is floored rather
  // than tested against 1440 so a step BEFORE the card's base day reads "-1d"
  // instead of printing a bare clock a day out of place: the day-of checkpoints
  // count backwards from take-off, and a 00:30 departure puts bag drop on the
  // previous evening. `m % 60` was negative there too, which printed "22:-50".
  //
  // The clock itself is T.fmtClock, not a local 24-hour pad. This column used to
  // be the one place on the trip that printed "04:10" while every card around it
  // printed "4:10p", and a reader cannot tell that apart from a 12-hour time with
  // the meridiem dropped - which is the wrong read to hand someone at 4am.
  const clockOf = (m) => {
    const d = Math.floor(m / 1440);
    return T.fmtClock(((m % 1440) + 1440) % 1440) + (d ? `${(d > 0 ? " +" : " ") + d}d` : "");
  };
  const dur = (m) => { const h = Math.floor(Math.abs(m) / 60), r = Math.abs(m) % 60; return `${(h ? `${h}h ` : "") + r}m`; };
  const minutesOf = (stamp) => { const p = T.parseStamp(stamp, state.trip?.start_date); return p && p.minutes != null ? p.minutes : null; };
  // Absolute minutes and the midnight the clock column is drawn against. The old
  // read worked in minutes-since-midnight only, which is fine until you compare a
  // landing to a car pickup - two values that are not guaranteed to share a day.
  // Everything below compares in absolute time and renders through cl(), so a
  // step past midnight still prints "+1d" and a cross-day gap is still a real gap.
  const absOf = (stamp) => stampMins(T.parseStamp(stamp, state.trip?.start_date));
  const baseOf = (stamp) => {
    const p = T.parseStamp(stamp, state.trip?.start_date);
    return p ? Date.parse(`${p.date}T00:00:00Z`) / 60000 : null;
  };

  // The stay's own clock when the booked row carries one. 15:00 / 11:00 was an
  // Airbnb average standing in for a fact the row actually holds - the Arvada
  // house is 16:00 / 10:00, so every "you beat check-in by X" was an hour out at
  // one end of the trip and an hour out at the other.
  function stayClock(stay, base) {
    const inAbs = stay && absOf(stay.check_in), outAbs = stay && absOf(stay.check_out);
    const inM = stay && minutesOf(stay.check_in), outM = stay && minutesOf(stay.check_out);
    return {
      in: inAbs != null && inM != null ? inAbs : base + (inM == null ? CHECK_IN : inM),
      out: outAbs != null && outM != null ? outAbs : base + (outM == null ? CHECK_OUT : outM),
    };
  }

  // The car everyone is actually riding in, as opposed to the fifteen quotes it
  // beat. Only a committed row: an arrival read built on a shortlist entry would
  // tell you to catch a shuttle to a counter nobody has booked.
  function bookedCar(t) {
    return (t?.transportation || []).filter(isCar).filter(isCommitted)[0] || null;
  }
  // "ACE - Dodge Grand Caravan or similar (1 minivan) - booked by Jasmine" is the
  // row's identity and the wrong length for a timeline step. The counter's name is
  // the part a step needs. Called on trains and rideshares too ("RTD A Line - DEN
  // to Union Station" -> "RTD A Line"), so it is not named for cars.
  const rowBrand = (x, dflt) => String((x?.description) || "").split("—")[0].trim() || (dflt || "the rental");
  // location reads "Off-airport, free shuttle to counter and car (6130 N Jackson
  // Gap Way, Aurora)" - the address in the parentheses is the half you can put in
  // a map, the prose in front of it is the half you already know.
  const carAddr = (x) => {
    const s = String((x?.location) || "");
    const m = /\(([^)]+)\)\s*$/.exec(s);
    return (m ? m[1] : s).trim();
  };
  // The logistics tables hold "Key: value" note lines by convention (Driver:,
  // Shuttle:, Ticket:, Fare:). Reading one back is not parsing prose - it is
  // reading a field that has no column yet.
  // ponytail: a driver column on transportation would make this exact. Until a
  //   second reader needs it, the convention is cheaper than a migration.
  const noteVal = (x, key) => (lines(x?.notes) || [])
    .map((l) => String(l).trim())
    .filter((l) => l.toLowerCase().indexOf(`${key.toLowerCase()}:`) === 0)
    .map((l) => l.slice(key.length + 1).trim())
    .filter(Boolean)[0] || "";
  // Who is on this vehicle. split_with is a members.id list and an empty one means
  // the whole crew - the same rule the cost model splits on, so the ride and the
  // bill can never disagree about who was in the car.
  function onCar(car, m) {
    if (!car) return false;
    const ids = String(car.split_with || "").split(",").map((s) => s.trim()).filter(Boolean);
    if (!ids.length) return true;
    return !!m && ids.indexOf(String(m.id)) >= 0;
  }
  // What is already on the transportation board for a given day, which is the only
  // honest answer to "so what do we do with five hours". A suggestion invented in
  // the rail is a suggestion nobody priced.
  function groundOptions(t, dateISO, stay) {
    const same = (t?.transportation || [])
      .filter((x) => !isCar(x) && !isDead(x))
      .filter((x) => {
        const p = T.parseStamp(x.scheduled_date || "", t?.start_date);
        return !p || !dateISO || p.date === dateISO;
      });
    // `stay` narrows it to the rides that end where you are actually going. The
    // A Line is a fine answer to "five hours to kill downtown" and a useless one
    // to "the car left without me" - that leg ends at Union Station and the house
    // is in Arvada. A row with no stated end is not known to be wrong, so it
    // stays; if narrowing empties the list, the unnarrowed list is the answer.
    if (!stay) return same;
    const at = (x) => String(x.arrival || "").toLowerCase();
    const home = [stay.area, stay.name, "airbnb", "the stay"].filter(Boolean).map((s) => String(s).toLowerCase());
    const near = same.filter((x) => !at(x) || home.some((h) => at(x).indexOf(h) >= 0 || h.indexOf(at(x)) >= 0));
    return near.length ? near : same;
  }

  // A ride's own duration, when the row states one. The A Line's note reads
  // "$10/person one way x7, 37 min, every 15 min" - the first number is the
  // journey and the second is the headway, and reading the wrong one turns a
  // 37-minute train into a 15-minute one. Headways are dropped before looking.
  // A train is not a car, so driveMin() is the wrong estimator for it; the row's
  // own stated time outranks any estimate.
  // ponytail: prose, because transportation has no duration column. If a second
  //   reader ever needs this number, that column is the fix, not a bigger regex.
  function statedMin(x) {
    const txt = String((x?.notes) || "")
      .replace(/\b(?:every|each)\s+\d+\s*(?:min|mins|minutes|h|hr|hrs|hours)\b/gi, "");
    const m = /(?:(\d+)\s*(?:h|hr|hrs|hours)\s*)?(\d+)\s*(?:min|mins|minutes)\b/i.exec(txt);
    return m ? (m[1] ? +m[1] * 60 : 0) + +m[2] : null;
  }
  // The ride that takes you INTO town, as opposed to the one that takes you to
  // the house. groundOptions() already knows which rides are on a given day;
  // this is the half of that list ending somewhere other than where you sleep,
  // which is the only half any use to a morning with hours to fill. A row with
  // coordinates wins, because it is the one that can say how long the leg takes.
  function cityRide(t, dateISO, stay) {
    const home = [stay?.area, stay?.name, "airbnb", "the stay"]
      .filter(Boolean).map((x) => String(x).toLowerCase());
    const away = groundOptions(t, dateISO).filter((x) => {
      const at = String(x.arrival || "").toLowerCase();
      return at && !home.some((h) => at.indexOf(h) >= 0 || h.indexOf(at) >= 0);
    });
    return away.filter(ptOf)[0] || away[0] || null;
  }

  function arrivalRead(t, f, stay, car) {
    const land = absOf(f.arrival_time), base = baseOf(f.arrival_time);
    if (land == null || base == null) return null;
    const cl = (m) => m - base;
    const curb = land + BAGS_MIN;
    const sc = stayClock(stay, base);
    const port = (f.to_airport || "").trim();
    const where = stay && (stay.area || stay.name) ? ` to ${stay.area || stay.name}` : "";
    const pk = car ? absOf(carPickup(car)) : null;
    const gap = pk == null ? null : pk - curb;
    // Two different drives, and they are not the same length. Anyone getting
    // themselves there leaves from the terminal; the crew collecting the car
    // leaves from the counter, which is off-airport by definition.
    const fromPort = driveMin(airportPt(port), ptOf(stay));
    const fromLot = driveMin(carPt(car), ptOf(stay));
    const dateISO = T.parseStamp(f.arrival_time, t.start_date)?.date;
    const homeName = (stay && (stay.area || stay.name)) || "the stay";
    let steps, door = null, note = "", opts = [], pill = "", tone = "";

    if (gap == null) {
      // No car booked. The generic read: you land, you get bags, you get in
      // something, you arrive. Same shape this has always had.
      door = curb + fromPort;
      steps = [
        { c: cl(land), w: `Wheels down${port ? ` · ${port}` : ""}` },
        { c: cl(curb), w: `Bags, then in a car · ~${fromPort} min${where}` },
        { c: cl(door), w: "At the place", hit: 1 },
      ];
    } else if (gap <= PICKUP_SLACK && gap >= -PICKUP_GRACE) {
      // YOU are the ride. Your flight is the one the pickup was booked around, so
      // the shuttle and the counter are steps in your day, not somebody else's.
      const shuttle = noteVal(car, "Shuttle"), driver = noteVal(car, "Driver");
      door = pk + fromLot;
      steps = [
        { c: cl(land), w: `Wheels down${port ? ` · ${port}` : ""}` },
        { c: cl(curb), w: `Bags, then the ${rowBrand(car)} shuttle${shuttle ? ` · ${shuttle}` : ""}` },
        { c: cl(pk), w: `Keys — ${rowBrand(car)}`, hit: 1 },
        { c: cl(door), w: `Drive${where} · ~${fromLot} min` },
      ];
      note = `You are the ride. Pickup is booked for ${clockOf(cl(pk))} and you clear bags around ${clockOf(cl(curb))}`
        + (gap >= LOT_MIN ? `, which leaves ${dur(gap)} for the shuttle and the counter. ` : ` — tight against the ${LOT_MIN} min the shuttle and counter take. `)
        + (driver ? `${driver.split(",")[0]} is the name on the booking, so that licence has to be at the desk. ` : "");
    } else if (gap > PICKUP_SLACK) {
      // You land hours before the car is collected, and it is not your ride - so
      // the pickup is not a step in YOUR day and no longer appears on this
      // timeline at all (Sam, 2026-08-26: "we are not going to be picking up
      // the ride. That should not be on my itinerary or on my plan"). What the
      // morning actually is: a ride into town, food, and being back out at the
      // house for check-in. Three numbers he asked for by name - how long the
      // leg takes, what time you are in town, and how long you have there.
      const ride = cityRide(t, dateISO, stay);
      const ridePt = ptOf(ride);
      if (ride) {
        // The train's own 37 minutes beats a road estimate; a rideshare with no
        // stated time falls back to the same measured drive as every other leg.
        const inMin = statedMin(ride) || driveMin(airportPt(port), ridePt);
        const outMin = driveMin(ridePt, ptOf(stay));
        const cityAt = curb + inMin, leave = sc.in - outMin, free = leave - cityAt;
        // Two different labels: the step names the station you actually get off
        // at, the sentence names the city you spend the morning in. "6h 3m in
        // Denver Union Station to eat and wander" is not a thing anyone does.
        const town = String(ride.arrival || "").trim() || "the city";
        const cityName = String((t.destination || "").split(",")[0] || "").trim() || "town";
        steps = [
          { c: cl(land), w: `Wheels down${port ? ` · ${port}` : ""}` },
          { c: cl(curb), w: `Bags, then ${rowBrand(ride, "a ride")} in · ~${inMin} min` },
          { c: cl(cityAt), w: `In town · ${town}`, hit: 1 },
          { c: cl(leave), w: `Out to ${homeName} · ~${outMin} min` },
          { c: cl(sc.in), w: "Check-in" },
        ];
        // A negative window is a real answer, not a rendering bug: it means the
        // ride in does not leave enough of the day to be worth taking.
        tone = free >= 60 ? "good" : "warn";
        pill = free > 0 ? `${dur(free)} in town` : "no room for town";
        note = free > 0
          ? `${dur(free)} in ${cityName} to eat and wander before you have to be moving — check-in is `
            + `${clockOf(cl(sc.in))}, and it is ~${outMin} min back out to ${homeName}.`
          : `The house does not open until ${clockOf(cl(sc.in))} and the leg in and back out eats the gap. `
            + `Bags somewhere and stay close, or wait it out.`;
        // The chosen leg stays in the list. It was filtered out for a turn on the
        // reasoning that a step should not repeat as an option - but the option
        // row is what carries the fare link, and dropping it took the transit
        // link off the card (Sam, 2026-08-26: "also include a link to the
        // Metro or whatnot"). A step tells you when; the option tells you what it
        // costs and where to buy it, and those are not the same row doing the
        // same job.
        opts = groundOptions(t, dateISO);
      } else {
        // Nothing on the board goes anywhere but the house, so there is no leg to
        // put a clock on. Say the size of the gap and stop.
        steps = [
          { c: cl(land), w: `Wheels down${port ? ` · ${port}` : ""}` },
          { c: cl(curb), w: "Bags — and nothing here to wait for", hit: 1 },
        ];
        note = `${dur(gap)} on the ground before the car is even collected, and the house is not open until `
          + `${clockOf(cl(sc.in))}. Nothing on the board goes into town yet.`;
        opts = groundOptions(t, dateISO);
      }
    } else {
      // The car has already driven to the house. You are getting yourself there.
      door = curb + fromPort;
      steps = [
        { c: cl(land), w: `Wheels down${port ? ` · ${port}` : ""}` },
        { c: cl(curb), w: `Bags, then your own ride${where}` },
        { c: cl(door), w: `At the place · ~${fromPort} min`, hit: 1 },
      ];
      note = `The car was collected at ${clockOf(cl(pk))} and is at the house — you are ${dur(-gap)} behind it. `
        + `This leg is your own${where ? ` Uber${where}` : " Uber"}, or somebody drives back out for you.`;
      opts = groundOptions(t, dateISO, stay);
    }

    if (note) note += " ";
    if (door == null) { tone = tone || "warn"; pill = pill || `${dur(gap)} to kill`; }
    else if (door < sc.in) { tone = "warn"; pill = `${dur(sc.in - door)} early`; note += `You reach the door ${dur(sc.in - door)} before check-in opens at ${clockOf(cl(sc.in))} — that is a lunch, not a wait, but the bags have to go somewhere.`; }
    else if (cl(door) <= 20 * 60) { tone = "good"; pill = "lands well"; note += "Straight in, evening intact."; }
    else if (cl(door) < 24 * 60) { tone = "warn"; pill = "night gone"; note += `In at ${clockOf(cl(door))}. Bed, not dinner.`; }
    else { tone = "bad"; pill = "after midnight"; note += `In around ${clockOf(cl(door))}. Check the host allows a late self check-in.`; }
    return { title: "Your arrival", who: `${stampShort(f.departure_time)} · ${f.airline || ""}`.trim(),
      steps, tone, pill, note: note.trim(), opts };
  }

  // biome-ignore lint/correctness/noUnusedFunctionParameters: t is unused, but groundplan.selftest.js lifts this function by its exact signature text - renaming the param breaks the test's regex, not the code.
  function departureRead(t, f, stay, car, riding) {
    const dep = absOf(f.departure_time), base = baseOf(f.departure_time);
    if (dep == null || base == null) return null;
    const cl = (m) => m - base;
    const sc = stayClock(stay, base);
    const port = (f.from_airport || "").trim();
    // The car's return time OUTRANKS the airport-lead constant, because it is a
    // contract and the constant is a rule of thumb. On the Denver trip the car is
    // due back at 2pm for a 5:15pm flight - the morning is set by the counter,
    // and a read that said "leave at 2:55" would have you returning it late.
    const back = riding && car ? absOf(carDropoff(car)) : null;
    // The morning drives to whichever the last stop is: the counter if you are on
    // the car return, the terminal if you are making your own way.
    const toLot = driveMin(ptOf(stay), carPt(car));
    const toPort = driveMin(ptOf(stay), airportPt(port));
    const leave = back != null ? back - toLot : dep - airportLead(f);
    const spare = leave - sc.out;
    const steps = [{ c: cl(sc.out), w: "Checkout" }];
    if (back != null) {
      steps.push({ c: cl(leave), w: `Leave for the return lot · ~${toLot} min`, hit: 1 });
      steps.push({ c: cl(back), w: `Car back — ${rowBrand(car)}` });
      steps.push({ c: cl(back + SHUTTLE_MIN), w: `Shuttle to ${port || "the terminal"}` });
    } else {
      steps.push({ c: cl(leave), w: `Leave for the airport · ~${toPort} min drive`, hit: 1 });
    }
    // Take-off ends it. Sam, 2026-08-26: "remove the land in LGA. There is no
    // real reason, because this is all a pre-flight checklist." Nothing after the
    // gate is something you can still act on.
    steps.push({ c: cl(dep), w: "Take off" });

    const atPort = back != null ? dep - (back + SHUTTLE_MIN) : airportLead(f);
    let tone, pill, note;
    if (spare < 0) { tone = "warn"; pill = "out before checkout"; note = `Gone ${dur(spare)} before checkout. The last morning is an airport morning.`; }
    else if (atPort < 2 * 60) { tone = "warn"; pill = `tight at ${port || "the airport"}`; note = `Only ${dur(atPort)} between handing the car back and takeoff — bag drop and security eat most of that.`; }
    else { tone = "good"; pill = `${dur(spare)} spare`; note = `${dur(spare)} of a real last day after checkout${back != null ? `, then ${dur(atPort)} at ${port || "the airport"} once the car is returned.` : `.`}`; }
    if (back != null) note = `The car is due back at ${clockOf(cl(back))}, and that is what sets this morning — not the ${clockOf(cl(dep))} flight. ${note}`;
    else if (car) note = `You are not on the ${rowBrand(car)} return, so this is your own ride to ${port || "the airport"}. ${note}`;
    return { title: "Your departure", who: `${stampShort(f.departure_time)} · ${f.airline || ""}`.trim(),
      steps, tone, pill, note, opts: [] };
  }

  // THE LEGS THE RAIL READS - the reader's, not the owner's. flightSel() below is
  // myFlights(), which is blank-passenger rows by definition, so on the shared
  // link it handed every guest Sam's ticket as though it were theirs.
  function readerLegs(t) {
    if (viewerKey() && !isViewer(meMember(t))) {
      const g = crewFlights(t).filter(groupIsViewer)[0];
      return g ? g.legs
        .map((lg) => ({ leg: lg.leg, row: lg.rows.filter(isCommitted)[0] || lg.rows[0] }))
        .filter((s) => s.row) : [];
    }
    return flightSel(t);
  }
  const readerMember = (t) => (viewerKey() ? ((t.members || []).filter(isViewer)[0] || meMember(t)) : meMember(t));

  function timelineReads(t, sel) {
    const live = (t.housing || []).filter((r) => !isDead(r));
    const stay = chosenStay() || picked("housing", live, fitsParty);
    const car = bookedCar(t);
    const out = sel.filter((s) => s.leg === "outbound" || s.leg === "roundtrip")[0];
    const back = sel.filter((s) => s.leg === "return")[0];
    return [
      out && arrivalRead(t, out.row, stay, car),
      // The last morning is timed off the stay you wake up in, which is not the
      // arrival's stay when a second one was booked (see lastStay).
      back && departureRead(t, back.row, lastStay() || stay, car, onCar(car, readerMember(t))),
    ].filter(Boolean);
  }
  // Everyone's landing on the outbound, in the order they actually touch down.
  // This is the card that explains the rest of the rail: a 2pm pickup is not an
  // arbitrary hour, it is the hour the third flight gets in.
  // Every travelling party on one direction of the trip, as {names, row}. The one
  // place that decides who is flying with whom, so the crew card and the arrivals
  // card cannot answer it differently. The two halves are NOT symmetrical and the
  // asymmetry is deliberate: the owner contributes every live leg, a crew group
  // contributes only its first. That is not a bug to tidy, it is what the flights
  // board and the transport rail already agree on.
  // `dir` is "return" (exact) or "outbound", which means NOT return - it accepts
  // roundtrip and any unrecognised or absent leg value, matching the test this
  // replaced. An equality check here would silently drop rows the board keeps.
  // Deliberately does NOT filter on arrival_time: a crew row with a departure and
  // no landing is still somebody you are flying with, and the day-of card prints
  // it. crewArrivals, which is about landings, applies that filter itself.
  function crewLegs(t, dir) {
    const want = dir === "return" ? (x) => x.leg === "return" : (x) => x.leg !== "return";
    const pick = (rows) => rows.filter(isCommitted)[0] || rows[0];
    const out = [], me = meMember(t);
    legsOf(myFlights(t)).filter((g) => g.live && want(g))
      .forEach((g) => { out.push({ names: [me?.name].filter(Boolean), row: pick(g.rows) }); });
    crewFlights(t).forEach((g) => {
      const lg = g.legs.filter(want)[0];
      if (lg) out.push({ names: g.names, row: pick(lg.rows) });
    });
    return out.filter((x) => x.row);
  }
  function crewArrivals(t) {
    return crewLegs(t, "outbound")
      .map((x) => ({ names: x.names, row: x.row, at: absOf(x.row.arrival_time) }))
      .filter((x) => x.at != null)
      .sort((a, b) => a.at - b.at);
  }
  // The row per leg the day read is measured against - the committed one once the
  // board has handed over, the marked/cheapest one while it is still a comparison.
  // Same two branches `listFlights` splits on, said once so the rail and the board
  // can never disagree about which fare the arrival read belongs to.
  function flightSel(t) {
    const live = flightLegs(t).filter((g) => g.live);
    const rows = (live.length && live.every(isSettled))
      ? live.map((g) => ({ leg: g.leg, row: g.rows.filter(isCommitted)[0] }))
      : live.map((g) => ({ leg: g.leg, row: picked(`flights:${g.leg}`, g.rows.filter((r) => !isDead(r))) }));
    return rows.filter((s) => s.row);
  }
  // NOT the itinerary timeline - this is the arrival/departure day read on a fare
  // card. It was called timelineHTML too, and being declared second it silently
  // shadowed the itinerary's timelineHTML for the whole module, which is why the
  // itinerary section threw on every render.
  // The head's right side is a slot, not a fixed pair: `who` and `pill` are both
  // optional now because the day-of card's copies of them were already printed in
  // 48px at the top of the page, and `link` is new - the one flight-day answer
  // this page cannot compute (is it on time) has to leave the page to get it.
  function dayReadHTML(r) {
    return `<div class="hub-infocard">
      <div class="hub-infocard-head tlcard-head"><span class="hub-infocard-t">${esc(r.title)}${r.who ? ` <i>${esc(r.who)}</i>` : ""}</span>
        <span class="hub-infocard-r">${r.link
          ? `<a class="hub-infocard-a" href="${esc(r.link.u)}" target="_blank" rel="noopener">${esc(r.link.l)}</a>` : ""}${
          r.pill ? `<span class="tlpill tlpill-${r.tone}">${esc(r.pill)}</span>` : ""}</span></div>
      <ul class="hub-steplist">${r.steps.map((s) => `<li${s.hit ? ' class="is-hit"' : ""}>
        <span class="hub-steplist-clock">${esc(clockOf(s.c))}</span><span class="hub-steplist-bar"></span><span class="hub-steplist-what">${esc(s.w)}</span></li>`).join("")}</ul>
      <div class="hub-note${r.tone === "bad" ? " is-warn" : ""}">${esc(r.note)}</div>${
      (r.opts?.length) ? `<div class="tlopts">${r.opts.map((x) =>
        ctxLink(x.description || x.type, x.url || "", rowCost(x) ? money(rowCost(x)) : "")
      ).join("")}</div>` : ""}
    </div>`;
  }
  // What each airline on this board charges. Only the carriers actually in play -
  // a reference table for eight airlines you aren't flying is furniture.
  function feeTableHTML(t) {
    const names = [];
    // __feeProbe is the selftest's way to hand this a flight list without a board.
    ((t?.__feeProbe) || myFlights(t)).forEach((f) => { const n = (f.airline || "").trim(); if (n && names.indexOf(n) < 0) names.push(n); });
    if (!names.length) return "";
    return `<div class="hub-section-head lgroup-head lgroup-sub"><span class="hub-section-head-t lgroup-l">what they charge</span>
      <span class="hub-section-head-sum lgroup-sum">per person, each way, on the cheap fares — checked Aug 2026</span></div>
      <table class="hub-table ltable"><thead><tr><th>airline</th><th class="hub-num">carry-on</th><th class="hub-num">1st checked</th><th>changes</th><th>catch</th></tr></thead><tbody>${
        names.map((n) => {
          const a = airlineFacts(n);
          // A carrier the table has never heard of gets the fallback, whose $45 is
          // an estimate the PRICING is welcome to. Printing it here is different:
          // this row names the airline and sits under a "checked Aug 2026" header,
          // so a quoted default reads as a fact somebody went and looked up. Every
          // cell says unknown instead, which is the true answer. Said once across the
          // three fee columns: three "unknown"s, two right-aligned and one left, read
          // as a misaligned row (mark 2026-10-14, "looks jank"). It spans the two
          // money columns only and stays a lane cell, so the grey runs unbroken
          // from their heads down, and "changes" says the same thing in its own column.
          if (!knownAirline(a)) return `<tr><td>${esc(n)}</td>
            <td colspan="2" class="hub-num lfee-unknown"><span class="hub-text-warn lwarn">fees unknown</span></td>
            <td class="hub-text-warn">unknown</td>
            <td class="bsrc">not in this table — check the fare rules on the airline's own site</td></tr>`;
          return `<tr><td>${esc(n)}</td>
            <td class="hub-num">${a.carryOn ? money(a.carryOn) : a.basicRisk ? `<span class="hub-text-warn lwarn">free, unless basic</span>` : "free"}</td>
            <td class="hub-num">${money(a.checked)}</td>
            <td>${a.freeChanges ? `<span class="hub-text-good">free</span>` : "fee"}</td>
            <td class="bsrc">${esc(a.note)}</td></tr>`;
        }).join("")}</tbody></table>`;
  }
  // What `flight-search.py --trip N` found, one block per search, newest first.
  // The trips.db trigger clears these once his own flight is booked.
  function flightResearchHTML(t) {
    const runs = t?.flight_research || [];
    if (!runs.length) return "";
    const durOf = (m) => `${Math.floor(m / 60)}h${String(m % 60).padStart(2, "0")}m`;
    return runs.map((s) => {
      const q = s.query || {}, res = s.results || [], errs = s.errors || [];
      const dates = [q.depart, q.ret].filter(Boolean).map(dayShort).join(" – ");
      return `<div class="hub-section-head lgroup-head lgroup-sub"><span class="hub-section-head-t lgroup-l">flight research · ${esc(`${q.origin || ""} → ${q.dest || ""}`)}</span>
        <span class="hub-section-head-sum lgroup-sum">${esc(dates)}${q.ret ? " round trip" : " one way"} · searched ${esc(new Date(s.searched_at.replace(" ", "T") + "Z").toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }))}</span></div>
        <table class="hub-table ltable"><thead><tr><th>airline</th><th>times</th><th>stops</th><th class="hub-num">duration</th><th class="hub-num">fare</th><th class="hub-num">all-in</th><th>points</th></tr></thead><tbody>${
          res.map((r) => {
            const o = r.outbound || {}, p = r.points;
            return `<tr><td>${esc((r.airlines || []).join(", "))}<span class="lsub">${esc(r.route || "")}</span></td>
              <td style="white-space:nowrap">${esc(`${o.depart || ""} → ${o.arrive || ""}`)}</td>
              <td>${o.stops ? esc(`${o.stops} via ${(o.via || []).join("/")}`) : "nonstop"}</td>
              <td class="hub-num">${o.duration_min ? durOf(o.duration_min) : ""}</td>
              <td class="hub-num">${money(r.price)}</td>
              <td class="hub-num">${money(r.effective)}${r.ulcc ? ` <span class="hub-text-warn lwarn">+bag</span>` : ""}</td>
              <td>${!p ? `<span class="bsrc">no partner</span>` : p.check ? `<span class="hub-text-good">${esc(p.programs.join("/"))}</span>` : esc(p.programs.join("/"))}</td></tr>`;
          }).join("")}</tbody></table>${errs.length ? `<div class="hub-note is-warn">${esc(errs.join("; "))}</div>` : ""}`;
    }).join("");
  }

  // ── THE SEAT, ONCE IT'S BOOKED ──────────────────────────────────────────────
  // The same handover the stay panel makes, one axis over. A fare board exists to
  // answer "which of these do we buy". The moment a leg is ticketed that question
  // is closed, and the board kept answering it anyway: badging a bought seat
  // "cheapest", measuring it against fares nobody can take, and offering a bag
  // toggle that reprices a total already charged to a card. What replaces it is
  // the set of facts you go looking for once you are actually flying - the record
  // locator, the terminal, and who else is on the plane.
  //
  // The comparison is not deleted; it moves under "what it beat", the same way
  // the shortlist does on a booked stay, so the decision stays re-readable.

  // stampShort answers "-" for a blank, which is right on a comparison table and
  // wrong here: this panel's rule is that an empty field means nobody filled it
  // in, so `stayFacts` drops it - and a dash smuggles it back as a checked answer
  // of "none". Austin's rental has no drop-off recorded and was reading as a car
  // you never have to return.
  const stampOrBlank = (s) => s ? stampShort(s) : "";

  // ── EVERYBODY ELSE'S TICKETS ────────────────────────────────────────────────
  // Rows carrying a `passenger` are somebody else's ticket. They ride in the same
  // table so the itinerary knows when everyone lands, and `myFlights` keeps them
  // out of his fare comparison and his money - correctly, it is not his seat and
  // not his bill. But that filter had become the DISPLAY rule too, so a crew
  // member's booked ticket surfaced as a one-line "who else is going" footnote
  // under his own leg: same flight, own record locator, own fare, own terminal,
  // rendered as a note. Their legs get the same block his do now. The money model
  // is untouched - `myFlights` still decides whose dollars count.
  //
  // The group is a FLIGHT, not a person. It used to key on the passenger string,
  // which made "Aaron + Jasmine" one traveller called "Aaron + Jasmine" - a name
  // nobody has, printed where a name goes. Two people sharing a booking are two
  // people, and the thing they share is the plane. So rows group by ITINERARY -
  // the ordered set of legs they are actually on - and the head lists everyone on
  // it by their own roster name. Two separately-entered rows on the same flights
  // land in one group; two people on the same outbound but different returns stay
  // apart, because those are not the same journey.
  // The signature is carrier + route + departure, and deliberately NOT the flight
  // NUMBER. Two rows for the same plane routinely disagree about the number -
  // somebody's ticket has it, somebody else's row is still waiting on them to say
  // - and keying on it splits a group the moment ONE of the two rows gets filled
  // in. That is what pulled Leonardo out of Aaron and Jasmine's block minutes
  // after he was put in it. No two flights leave the same airport for the same
  // airport on the same carrier at the same minute, so the number adds nothing the
  // rest of the key does not already say, and it takes a fragility with it.
  const legKey = (f) => [f.direction || "outbound", (f.airline || "").trim().toLowerCase(),
    (f.from_airport || "").trim().toUpperCase(), (f.to_airport || "").trim().toUpperCase(),
    (f.departure_time || "").trim()].join("|");
  function crewFlights(t) {
    const by = [];
    (t.flights || []).forEach((f) => {
      const who = (f.passenger || "").trim();
      if (!who) return;
      let g = by.filter((x) => x.who === who)[0];
      if (!g) by.push(g = { who: who, rows: [] });
      g.rows.push(f);
    });
    // Signature first, so the merge is on the journey rather than on the spelling
    // of the name. A row with nothing identifying on it at all (no carrier, no
    // number, no time) signs as its own group instead of colliding with every
    // other blank - an empty signature is not evidence of a shared plane.
    const merged = [];
    by.forEach((g) => {
      const sig = g.rows.map(legKey).sort().join("~");
      const solo = sig.split("~").every((k) => k.split("|").slice(1).join("") === "");
      const hit = solo ? null : merged.filter((m) => m.sig === sig)[0];
      if (hit) { hit.whos.push(g.who); hit.rows = hit.rows.concat(g.rows); }
      else merged.push({ sig: sig, who: g.who, whos: [g.who], rows: g.rows });
    });
    return merged.map((g) => {
      // Everyone the passenger fields name, deduped, in roster order - that is the
      // list the head prints. A ticket whose tokens match nobody keeps the string
      // written on it, so an unmatched name still shows up as somebody.
      // Per PASSENGER STRING, not per group. The fallback used to be "if this whole
      // group matched nobody, print the ticket names" - so on a merged group where
      // one row's name resolved and another's did not, the unresolved rider was
      // dropped from a head that was still printing his flight. Each name now
      // resolves or survives on its own.
      const people = [], loose = [];
      g.whos.forEach((w) => {
        const hit = membersNamed(t, w);
        if (hit.length) hit.forEach((m) => { if (people.indexOf(m) < 0) people.push(m); });
        else if (w && loose.indexOf(w) < 0) loose.push(w);
      });
      const order = (t.members || []).map((m) => m.id);
      people.sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id));
      const names = people.map((m) => m.name.trim()).concat(loose);
      return { who: g.who, whos: g.whos, people: people, names: names,
        member: people.length === 1 ? people[0] : memberFor(t, g.who),
        legs: legsOf(g.rows).filter((x) => x.live) };
    }).filter((g) => g.legs.length);
  }
  // Anyone in the group is the viewer, not just the one the head happens to lead
  // with - a shared booking has two readers and both came for the same card.
  const groupIsViewer = (g) => (g.people || []).some(isViewer) || isViewer(g.member);

  // The roster and the boarding pass do not have to agree on a name. A ticket has
  // to match a passport; the crew list is what Sam calls people. Nina Ford
  // flies as Sophia Ford, and a strict name match would report her as having
  // no flights while rendering her ticket two inches above. And one row can carry
  // two people: Denver's outbound is booked as "Aaron + Jasmine".
  //
  // So the match runs per NAME TOKEN, not per string: each token in the passenger
  // field names a member if exactly one member's name carries that token, and the
  // ticket covers everyone it names. "Sophia Ford" reaches Aria on `ford`,
  // "Aaron + Jasmine" reaches both on a token each.
  // ponytail: a token two members share - Josh and Amanda Ortiz on `ortiz` - is
  //   an ambiguity, and it gets left alone rather than guessed at: it names nobody,
  //   the ticket renders under the name written on it, and both still read as
  //   unaccounted for. A contact_slug on the flight row would make this exact.
  // Moved into trips-cost.js - the cost model needs the same answer, to know
  // whose seat a fare is when the row carries a name instead of a split.
  const membersNamed = (t, who) => TC.membersNamed(t, who);
  // The heading needs ONE name to print, so it only takes an unambiguous single
  // hit - a joint ticket keeps the name that is actually on it.
  function memberFor(t, who) {
    const hit = membersNamed(t, who);
    return hit.length === 1 ? hit[0] : null;
  }
  // A blank passenger is his own seat, so it accounts for HIM on the roster.
  // ponytail: matched on the contact slug, falling back to the first member -
  //   there is no owner flag on `members` and adding one for a single boolean
  //   the roster already implies is the wrong order.
  const ME_SLUG = "sam-rivera";
  function meMember(t) {
    const M = (t.members || []).filter((m) => (m.name || "").trim());
    return M.filter((m) => (m.contact_slug || "") === ME_SLUG)[0] || M[0] || null;
  }
  // Who on the crew list has no ticket on this board at all. This is the half of
  // the request that is not a rendering change: a flights tab that shows four of
  // six travellers looks complete, and the two nobody has asked about are exactly
  // the ones that strand a pickup at the airport.
  function flightlessMembers(t) {
    const M = (t.members || []).filter((m) => (m.name || "").trim());
    if (!M.length) return [];
    const seat = {};
    (t.flights || []).filter((f) => !isDead(f)).forEach((f) => {
      const who = (f.passenger || "").trim();
      const on = who ? membersNamed(t, who) : [meMember(t)];
      on.filter(Boolean).forEach((m) => { seat[m.id] = 1; });
    });
    return M.filter((m) => !seat[m.id]);
  }
  // The count, said as a sentence rather than a badge, because "2" on its own does
  // not tell you which two and the names are the actionable part.
  function flightGapHTML(t) {
    const gap = flightlessMembers(t);
    if (!gap.length) return "";
    const n = (t.members || []).length;
    return `<div class="hub-note is-warn"><b>${gap.length} of ${n}</b> on the crew list ${
      gap.length === 1 ? "has" : "have"} no flight on this board — ${
      esc(gap.map((m) => m.name.trim()).join(", "))}. Nobody knows when they land yet.</div>`;
  }
  // The fare board's split line is a shopping sentence - "no bags · one booking"
  // reads the bag toggle, which this panel does not have. Past tense instead: who
  // you are flying, and whether it is one record locator to find at 5am or two.
  function bookedSplit(picks) {
    const airlines = [];
    picks.forEach((x) => {
      const a = (x.row.airline || "").trim();
      if (a && airlines.indexOf(a) < 0) airlines.push(a);
    });
    const conf = picks.map((x) => (x.row.confirmation || "").trim()).filter(Boolean);
    const uniq = conf.filter((c, i) => conf.indexOf(c) === i);
    const bits = airlines.length ? [airlines.join(" + ")] : [];
    if (uniq.length === 1) bits.push(`one booking · ${uniq[0]}`);
    else if (uniq.length > 1) bits.push(`${uniq.length} bookings · ${uniq.join(", ")}`);
    return bits.join(" · ");
  }
  // ── CARRIER MARKS ───────────────────────────────────────────────────────────
  // Every path and every hex below is lifted straight out of the carrier's own
  // SVG (Wikimedia Commons), not redrawn: the Southwest heart keeps its three real
  // gradients, the Delta widget its two real reds. A carrier with no mark on file
  // gets its name set in the display face and the trip accent - an honest blank,
  // never a guessed logo.
  const LIVERY = {
    southwest: { key: "sw", ink: "#fff", plate: ["#304CB2", "#3656CC"], livery: ["#304CB2", "#E61C23", "#FDBC11"],
      mark: "<svg class=\"pass-mark\" viewBox=\"189 10 25 24\" aria-hidden=\"true\"><linearGradient id=\"swg1_\" gradientUnits=\"userSpaceOnUse\" x1=\"190.944\" y1=\"781.4805\" x2=\"206.401\" y2=\"781.4805\" gradientTransform=\"matrix(1 0 0 1 0 -757)\"> <stop offset=\"0\" style=\"stop-color:#3656CC\"/> <stop offset=\"0.35\" style=\"stop-color:#304CB2\"/> <stop offset=\"0.72\" style=\"stop-color:#283B80\"/> </linearGradient><linearGradient id=\"swg2_\" gradientUnits=\"userSpaceOnUse\" x1=\"193.1394\" y1=\"769.2701\" x2=\"210.601\" y2=\"781.4969\" gradientTransform=\"matrix(1 0 0 1 0 -757)\"> <stop offset=\"0.3\" style=\"stop-color:#E61C23\"/> <stop offset=\"0.8\" style=\"stop-color:#C3161C\"/> </linearGradient><linearGradient id=\"swg3_\" gradientUnits=\"userSpaceOnUse\" x1=\"203.9645\" y1=\"767.6895\" x2=\"213.9482\" y2=\"774.6802\" gradientTransform=\"matrix(1 0 0 1 0 -757)\"> <stop offset=\"0\" style=\"stop-color:#FDBC11\"/> <stop offset=\"0.25\" style=\"stop-color:#FCB415\"/> <stop offset=\"0.8\" style=\"stop-color:#F89E1C\"/> </linearGradient><path fill=\"#CCCCCC\" d=\"M207,10.8c-2,0-3.7,0.7-5,1.4c-1.3-0.7-2.9-1.4-5-1.4c-4.1,0-6.7,2.6-6.7,7.2c0,5.5,5.3,10.9,11.7,15.3 c6.4-4.3,11.7-9.7,11.7-15.3C213.7,13.4,211,10.8,207,10.8z\"/><path fill=\"url(#swg1_)\" d=\"M190.9,18.1c0,5.6,6,10.9,11,14.4c1.5-1,3-2.2,4.4-3.4c-6.7-5.6-13.1-10.7-15.3-12.5 C191,17,190.9,17.5,190.9,18.1z\"/><path fill=\"url(#swg2_)\" d=\"M212.6,20.7c-4.9-4-7.8-6.1-11-8c-0.9-0.5-2.6-1.3-4.5-1.3c-1.8,0-3.4,0.6-4.5,1.7c-0.7,0.7-1.2,1.6-1.4,2.7 c2.5,1.8,9.4,6.7,16.3,12.2C209.8,25.8,211.7,23.3,212.6,20.7z\"/><path fill=\"url(#swg3_)\" d=\"M211.3,13.1c-1.1-1.1-2.6-1.7-4.4-1.7c-1.9,0-3.3,0.6-4.4,1.2c1.9,1.1,6,3.4,10.3,6.6 c0.1-0.4,0.1-0.9,0.1-1.3C213,15.9,212.4,14.2,211.3,13.1z\"/></svg>",
      word: "<svg class=\"pass-word\" viewBox=\"0 0 190 34\" aria-label=\"Southwest\"><path fill=\"currentColor\" d=\"M59,27c-0.9,0.2-2,0.3-3.1,0.3c-3.2,0-3.9-1.1-3.9-3.2V12h-6l0,12.8c0,5.7,3.2,8.3,9.6,8.3 c3.1,0,6-0.6,9.5-1.4V12H59V27z M78.5,27.6c-2.2,0-2.5-1-2.5-2.7l0-7.8l5,0V12h-5V6h-6v6l-3,0v5l3,0l0,8.2c0,3.6,0.7,7.8,6.7,7.8 c1.8,0,3.3-0.4,5-0.9l-0.6-5C80.2,27.4,79.4,27.6,78.5,27.6z M15.4,16.3c-1.1-0.4-2.4-0.8-3.7-1.2c-3.5-1-4.6-1.5-4.6-3.1 c0-1.8,1.3-2.7,4.5-2.7c2.6,0,4.9,0.7,7.2,1.5L20.1,5c-2.7-1-5.2-1.9-8.3-1.9c-7.2,0-11.2,4.1-11.2,9c0,3.7,1.6,6.1,5.2,7.6 c1,0.4,2.3,0.8,3.6,1.2c3.9,1.2,5.1,1.8,5.1,3.3c0,1.8-1.5,2.8-4.6,2.8c-2.8,0-5.4-0.8-8.1-2L0.4,31c3,1.2,5.9,2,9.5,2 c7.4,0,11.2-4.1,11.2-9.1C21.1,19.9,18.8,17.6,15.4,16.3z M94.2,11c-2,0-3.9,0.5-5.2,0.9V2h-6v31h6l0-15.5 c1.1-0.4,2.3-0.8,3.8-0.8c2.3,0,3.2,0.9,3.2,3.1L96,33h6l0-13.9C102,13.6,99.5,11,94.2,11z M33.4,10.9c-6.1,0-11,4.3-11,11 c0,6.7,4.9,11.2,11,11.2c6.1,0,11-4.4,11-11.2S39.5,10.9,33.4,10.9z M33.4,27.1c-2.6,0-4.7-1.9-4.7-5.3s2-5.2,4.7-5.2 c2.7,0,4.7,1.8,4.7,5.2C38.1,25.3,36,27.1,33.4,27.1z M168.1,20.2c-0.9-0.3-1.8-0.6-2.9-0.9c-2.1-0.6-2.9-0.9-2.9-1.8 c0-0.9,0.8-1.5,2.7-1.5c2,0,3.8,0.4,5.8,1l1-5.2c-2.2-0.5-4.3-0.9-6.7-0.9c-5.7,0-8.8,2.9-8.8,6.9c0,2.8,1.4,4.6,4.2,5.8 c0.8,0.3,1.7,0.7,2.8,1c2.2,0.6,3.3,0.9,3.3,1.9c0,1-1.3,1.4-3.1,1.4c-2.2,0-4.2-0.4-6.3-1.2l-0.9,5.2c2.6,0.7,5,1.2,7.7,1.2 c6,0,8.7-3.1,8.7-7C172.6,23.4,171.5,21.4,168.1,20.2z M145.6,10.9c-6.3,0-10.8,4.4-10.8,11.4c0,6.5,3.9,10.8,10.9,10.8 c3.1,0,5.6-0.9,8.2-2l-0.9-5c-2,0.9-4,1.6-6.4,1.6c-3.6,0-5.1-1.5-5.3-3.7l13.5,0c0,0,0.2-2.4,0.2-2.9 C155,15.4,151.9,10.9,145.6,10.9z M141.4,20c0.4-1.8,1.3-4.1,3.9-4.1c2.6,0,3.4,2.6,3.4,4.1L141.4,20z M184.5,27.6 c-2.2,0-2.5-1-2.5-2.7l0-7.8l5,0V12h-5V6h-6v6l-3.1,0v5.1l3.1,0l0,8.2c0,3.6,0.9,7.8,6.9,7.8c1.8,0,3.3-0.4,5-0.9l-0.7-5 C186.2,27.4,185.4,27.6,184.5,27.6z M188.5,3.2c-1.5,0-2.6,1.2-2.7,2.7s1.2,2.7,2.6,2.7c1.5,0,2.7-1.2,2.7-2.7S190,3.2,188.5,3.2z M188.5,8.1c-1.2,0-2.1-0.9-2.1-2.2c0-1.3,0.9-2.2,2.2-2.2c1.2,0,2.2,0.9,2.1,2.2C190.6,7.2,189.7,8.1,188.5,8.1z M188.8,6 c0.5-0.1,0.8-0.3,0.8-0.8c0-0.5-0.4-0.9-1-0.9l-1,0l0,3.1l0.6,0V6.1c0.2,0,0.3,0.1,0.4,0.3l0.7,1h0.7l-0.6-1 C189,6.2,188.9,6.1,188.8,6z M188.4,5.7l-0.3,0l0-0.9l0.4,0c0.4,0,0.5,0.2,0.5,0.4C189,5.6,188.7,5.7,188.4,5.7z M129.2,12 l-3.8,11.5L121.6,12h-5.2l-3.9,11.5L108.7,12h-6.5l7.5,21h5.5l3.8-11.4l3.8,11.4h5.5l7.5-21C135.8,12,129.2,12,129.2,12z\"/></svg>" },
    delta: { key: "dl", ink: "#fff", plate: ["#003D79", "#0a4f96"], livery: ["#003D79", "#E31837", "#98002E"],
      mark: "<svg class=\"pass-mark\" viewBox=\"0 0 208 154\" aria-hidden=\"true\"><path fill=\"#98002E\" d=\"M185.7,137.6l-89.3-43V0L185.7,137.6z M192.8,154l-96.4-40.7V154H192.8z\"/><polyline fill=\"#E31837\" points=\"7.1,137.6 96.4,0 96.4,94.6 7.1,137.6\"/><polyline fill=\"#E31837\" points=\"0,154 96.4,154 96.4,113.3 0,154\"/></svg>",
      word: "<svg class=\"pass-word\" viewBox=\"260 0 745 154\" aria-label=\"Delta\"><path fill=\"currentColor\" d=\"M268.1,137.6h43.3c44.6,0,71.1-23.1,71.1-61.4S356,14.9,311.4,14.9h-43.3V137.6z M295.5,36.2h15.9 c28.9,0,43.4,14.3,43.4,40s-14.5,40-43.4,40h-15.9V36.2z\"/><polygon fill=\"currentColor\" points=\"475.7,84.4 527.8,84.4 527.8,63.1 475.7,63.1 475.7,36.2 534.6,36.2 534.6,14.9 448.2,14.9 448.2,137.6 536.5,137.6 536.5,116.3 475.7,116.3\"/><polygon fill=\"currentColor\" points=\"692.7,116.3 639.8,116.3 639.8,14.9 612.3,14.9 612.3,137.6 692.7,137.6\"/><polygon fill=\"currentColor\" points=\"840.7,14.9 730.6,14.9 730.6,36.2 771.8,36.2 771.8,137.6 799.4,137.6 799.4,36.2 840.7,36.2\"/><path fill=\"currentColor\" d=\"M1000,137.6h-28.7l-12-30.7h-49.9l-12,30.7h-26.8l51.3-123.2h27.7L1000,137.6z M951.5,86.3l-17.1-43.6 l-17.2,43.6H951.5z\"/></svg>" },
    // United ships one hex in its own file, #1414d2, so the plate and the bands
    // are that hex and two tints of it rather than a second brand colour nobody
    // sourced. The mark is the vendor globe whole: a blue square that sinks into
    // the plate and the white grid that reads on top, which is how United paints
    // it on a blue tail.
    united: { key: "ua", ink: "#fff", plate: ["#1414d2", "#2a2ae4"], livery: ["#1414d2", "#0d0d8f", "#5b5bef"],
      mark: "<svg class=\"pass-mark\" viewBox=\"716.98 0 162.91 162.88\" aria-hidden=\"true\"><path fill=\"#1414d2\" d=\"M890.77,153.75v1.87h2.15c.69,0,1.03-.33,1.03-.92s-.36-.95-1.03-.95h-2.15ZM889.77,152.8h3.18c1.23,0,2.05.72,2.05,1.82s-.72,1.74-1.79,1.87l2.18,2.85h-1.31l-2.03-2.79h-1.28v2.79h-1v-6.54ZM892.17,150.47c3.15,0,5.71,2.56,5.71,5.71s-2.56,5.71-5.71,5.71-5.71-2.56-5.71-5.71,2.56-5.71,5.71-5.71M892.17,149.48c-3.7,0-6.7,3-6.7,6.7s3,6.7,6.7,6.7,6.7-3,6.7-6.7-3-6.7-6.7-6.7h0ZM838.44,162.88c3.23-6.05,6.82-13.57,9.21-19.97,0,0,0,0,0,.01.08.2,1.27,3.36,2.16,6.65,1.85-6.54,3.17-13.33,3.9-20.33h0c-.23-.91-.72-2.38-1-3.28,0,0,1.18-5.94,1.65-12.72.64,4.65.97,9.38.97,14.15,0,8.28-.98,16.4-2.87,24.24-.97,3.87-2.16,7.67-3.45,11.23h-10.59ZM826.8,162.88h6.12c17.42-25.74,18.3-48.54,18.3-52.91,0-8.25-1.39-15.84-3.7-21.85,0,0-3.62-9.33-9.24-17.64.61,1.86,1.79,5.62,2.45,8.98.04.22.08.42.11.61,1.11,1.85,6.11,10.67,6.78,20.37,0,.02,0,.03,0,.03,0,0-3.53-4.95-6.16-8.08-.09,5.33-.79,10.66-1.9,15.82,0,0,5.24,6.06,7.58,9.98,0,0-1.59,8.53-5.01,16.7-3.48-5.05-7.91-9.96-7.91-9.96-2.6,6.42-5.89,12.88-9.54,18.85,0,0,6.64,7.76,8.09,9.98-1.95,3.28-3.85,6.14-5.96,9.13ZM805,162.88c11.56-12.93,21.41-28.14,27.33-44.43,5.13-14.13,7.93-31.39,3.38-46.74-.3-1.01-.65-2.03-1.05-3.06-1.45-3.75-3.34-7.03-5.39-9.6-5.53-6.18-11.79-11.69-18.65-16.38,1.01,1.3,1.93,2.64,2.73,4,0,0,8.35,6.2,13.2,12.49-6.22-4.43-9.74-6.23-10.2-6.45-.02,0-.04-.02-.05-.03,2.36,5.83,3.07,10.65,3.08,10.66,0,0,7.38,3.85,14.03,9.61.92,4.26,1.3,8.62,1.24,12.98-6.7-5.89-14.45-10.5-14.45-10.5-.14,4.99-.83,10.04-1.93,14.96,0,0,7.32,4.64,14.45,11.13,0,0-2.05,9.21-5.35,16.45-6.84-6.37-13.52-11.33-14.04-11.72,0,0-3.4,8.86-8.9,17.75,6.85,5.96,13.29,12.14,13.29,12.14-3.93,6.14-8.39,11.98-13.19,17.45h0s-12.26-12.2-12.26-12.2c-4.98,6.16-10.44,11.97-16.24,17.31.28.31,2.75,3.05,3.76,4.17h25.21ZM808.14,44.04c-.79-1.08-1.69-2.19-2.72-3.17-.9-.86-1.78-1.64-2.71-2.34-10.2-7.69-28.97-11.53-28.97-11.53,1.79.95,3.28,1.93,3.29,1.94.09.02,7.66,1.92,14.37,5.2,0,0-6.11-1.39-10.02-1.93,1.62,1.42,3.16,3.06,4.51,4.77,0,0,12.45,2.27,17.92,5.27,0,0,2.62,2.69,4.76,7.42-8.54-3.47-18.2-5.27-18.2-5.27,1.28,2.88,2.2,5.95,2.76,9.16,0,0,10.63,2.6,18.61,6.44.69,3.79.94,7.71.8,11.68-9.43-4.73-18.79-7.7-18.79-7.7-.19,4.09-.85,8.32-1.95,12.65,0,0,12.88,5.75,18.66,9.24-1.28,5.11-3.07,10.12-5.23,14.94-8.81-5.73-18.14-10.82-18.14-10.82-2.34,5.63-8.11,14.84-8.11,14.84h0s0,0,0,0h0c.14.1,9.74,6.69,17.1,12.53-3.66,5.54-7.78,10.86-12.26,15.92-1.55-1.48-15.69-14.03-15.69-14.03-4.27,4.95-9.02,9.77-14.22,14.38,0,0,0,0,0,0l13.63,15.43s0,0,0,0h0c-8.84,7.28-17.66,12.8-17.66,12.8l-11.38-16.15s-8,6.09-21.52,12.48v4.68h44.37c49.52-37.47,67.09-91.04,46.78-118.84ZM783.02,38.41c-12.3-16.55-31.55-14.19-37.29-13.39-6.31.88-11.07,2.26-11.07,2.26,1.41.13,3.33.38,4.71.66,1.02-.24,9.87-2.26,16.31-1.42,0,0,.02,0,.02,0-4.73.51-11.18,2.46-11.85,2.67,0,0,0,0-.02,0,0,0,.01,0,.02,0,.23.07,2.09.63,4.48,2.03.7-.19,9.46-2.51,17.81-2.67h0s3.09,1.37,6.06,3.41c-10.79-.04-19.73,2.03-19.97,2.09,1.26,1.12,2.52,2.47,3.65,4.09,11.83-1.77,22.04-1,22.04-1,0,0,1.39,1.69,2.01,2.6.79,1.15,1.59,2.57,2.22,3.82-12.07-1.41-23.62-.4-23.63-.4.8,2.06,1.34,4.25,1.63,6.57,1.33,0,11.56,0,24.59,2.35.42,2.99.46,6.19.13,9.56-2.21-.58-12.91-3.25-24.58-4.4-.24,2.92-.79,5.95-1.64,9.07,1.31.31,15.72,3.74,23.8,7.01-.16.51-.32,1.02-.49,1.53-1.16,3.47-2.6,6.95-4.31,10.42-6.5-3.2-22.45-9.43-22.45-9.43-1.59,3.57-3.54,7.18-5.82,10.78,0,0,13.67,7.8,20.25,12.12-3.04,4.34-6.47,8.61-10.26,12.73-4.77-4.28-16.72-13.54-17.62-14.24-3.85,4.59-8.7,9.41-10.16,10.84l14.33,16.43c-.13.12-.27.24-.41.36-3.1,2.57-6.44,4.99-9.27,6.93-2.45,1.67-4.47,2.96-5.17,3.4-.17-.25-9.55-15.24-10.96-17.62-1.03.76-2.07,1.49-3.11,2.21v30.8c1.69-.81,3.38-1.65,5.06-2.55,8.08-3.98,15.92-9.03,23.22-14.86,4.68-3.71,9.58-8.07,14.43-13.1,5.75-5.9,10.75-12.08,14.92-18.35,15.81-23.33,20.04-47.66,8.4-63.34ZM751.12,37.17c-5.86-6.72-15.61-9.02-26.93-7.41-.31.05-.63.09-.92.14-.86.15-1.74.32-2.62.52-1.75.41-2.95.81-3.65,1.08v3.39c1.12-.88,2.25-1.72,3.43-2.5,2.26-.48,4.45-.79,6.56-.93-3.27,1.87-7.05,4.4-9.99,6.74v2.61l.1.06s8.3-6.57,14.9-9.4c1.59.11,3.11.34,4.56.67-9.86,4.18-17.13,9.37-17.64,9.73,1.01.6,1.93,1.35,2.06,1.45.13-.08,9.68-6.06,20.2-9.64,1.43.65,2.81,1.46,4,2.38-11.45,3.22-22.46,8.96-22.46,8.96.62.72,1.17,1.5,1.64,2.34.07-.03.14-.06.2-.08,11.72-5.02,24.17-7.59,24.17-7.59.97,1.33,1.78,2.82,2.39,4.47,0,0-11.18,1.28-25.55,5.89.63,1.99.81,3.48.81,3.49,0,0,13.55-3.03,26.05-3.37.17,2.01.11,4.26-.18,6.57-7.4-.39-25.04.55-25.73.6,0,0-.06,2.54-.72,4.93,0,0,12.88.41,24.6,2.6-.91,2.81-2.06,5.57-3.44,8.28-7.81-2.35-19.66-5.2-22.78-5.91-.82,2.02-1.85,4.03-3.08,5.97,0,0,14.48,6.32,20.04,9.41h.01,0c-2.41,3.62-7.19,8.67-7.19,8.67-1.39-1.04-2.7-2.01-3.94-2.91-3.84-2.69-13.02-9.1-13.03-9.11v11.98l7.51,8.77c-2.47,1.99-5,3.81-7.51,5.44v7.15c.09-.06.18-.12.28-.18,3.43-2.34,6.82-4.94,10.12-7.81,25.92-22.55,36.54-52.75,23.72-67.45ZM717,71.49c6.62-9.43,7.58-20.24,1.77-25.52-.55-.5-1.14-.92-1.77-1.29v26.81ZM753.15,20.82c58.73,0,106.52,47.96,106.52,106.92,0,11.96-2.02,23.85-5.93,35.14h26.15V0h-162.88v27.17l.13-.05c11.56-4.18,23.68-6.31,36.02-6.31Z\"/><path fill=\"#fff\" d=\"M730.03,88.38c-3.84-2.69-13.02-9.1-13.03-9.11v-7.78c6.62-9.43,7.58-20.24,1.77-25.52-.55-.5-1.14-.92-1.77-1.29v-3.88l.1.06s8.3-6.57,14.9-9.4c1.59.11,3.11.34,4.56.67-9.86,4.18-17.13,9.37-17.64,9.73,1.01.6,1.93,1.35,2.06,1.45.13-.08,9.68-6.06,20.2-9.64,1.43.65,2.81,1.46,4,2.38-11.45,3.22-22.46,8.96-22.46,8.96.62.72,1.17,1.5,1.64,2.34.07-.03.14-.06.2-.08,11.72-5.02,24.17-7.59,24.17-7.59.97,1.33,1.78,2.82,2.39,4.47,0,0-11.18,1.28-25.55,5.89.63,1.99.81,3.48.81,3.49,0,0,13.55-3.03,26.05-3.37.17,2.01.11,4.26-.18,6.57-7.4-.39-25.04.55-25.73.6,0,0-.06,2.54-.72,4.93,0,0,12.88.41,24.6,2.6-.91,2.81-2.06,5.57-3.44,8.28-7.81-2.35-19.66-5.2-22.78-5.91-.82,2.02-1.85,4.03-3.08,5.97,0,0,14.48,6.32,20.04,9.41h.01,0c-2.41,3.62-7.19,8.67-7.19,8.67-1.39-1.04-2.7-2.01-3.94-2.91ZM720.42,32.38c-1.17.79-2.31,1.62-3.43,2.5v3.31c2.94-2.34,6.72-4.87,9.99-6.74-2.11.14-4.31.45-6.56.93ZM717,91.25v14.22c2.52-1.63,5.04-3.45,7.51-5.44l-7.51-8.77ZM753.15,20.82c-12.34,0-24.46,2.12-36.02,6.31l-.13.05v4.33c.7-.27,1.9-.67,3.65-1.08.88-.19,1.76-.37,2.62-.52.29-.05.61-.09.92-.14,11.33-1.62,21.08.68,26.93,7.41,12.82,14.7,2.2,44.9-23.72,67.45-3.3,2.87-6.69,5.48-10.12,7.81-.09.06-.18.12-.28.18v7.2c1.04-.72,2.08-1.45,3.11-2.21,1.41,2.38,10.79,17.37,10.96,17.62.7-.45,2.72-1.74,5.17-3.4,2.82-1.94,6.17-4.36,9.27-6.93.14-.12.28-.24.41-.36l-14.33-16.43c1.45-1.43,6.3-6.25,10.16-10.84.9.7,12.85,9.95,17.62,14.24,3.79-4.12,7.22-8.38,10.26-12.73-6.58-4.32-20.25-12.12-20.25-12.12,2.28-3.6,4.23-7.21,5.82-10.78,0,0,15.94,6.23,22.45,9.43,1.71-3.47,3.15-6.95,4.31-10.42.17-.51.33-1.02.49-1.53-8.08-3.27-22.49-6.71-23.8-7.01.85-3.11,1.41-6.15,1.64-9.07,11.67,1.16,22.36,3.83,24.58,4.4.33-3.38.29-6.57-.13-9.56-13.02-2.34-23.25-2.36-24.59-2.35-.3-2.31-.83-4.51-1.63-6.57,0,0,11.56-1.01,23.63.4-.63-1.25-1.43-2.67-2.22-3.82-.62-.91-2.01-2.6-2.01-2.6,0,0-10.21-.77-22.04,1-1.13-1.62-2.39-2.97-3.65-4.09.24-.06,9.18-2.13,19.97-2.09-2.97-2.04-6.06-3.41-6.06-3.41h0c-8.35.16-17.11,2.49-17.81,2.67-2.39-1.4-4.24-1.96-4.48-2.03,0,0-.01,0-.02,0,0,0,0,0,.02,0,.67-.21,7.12-2.16,11.85-2.67,0,0,0,0-.02,0-6.43-.84-15.28,1.17-16.31,1.42-1.38-.28-3.3-.53-4.71-.66,0,0,4.77-1.38,11.07-2.26,5.74-.8,24.99-3.17,37.29,13.39,11.65,15.68,7.41,40-8.4,63.34-4.17,6.27-9.17,12.45-14.92,18.35-4.84,5.03-9.75,9.39-14.43,13.1-7.3,5.83-15.14,10.88-23.22,14.86-1.69.9-3.37,1.74-5.06,2.55v7.58c13.51-6.39,21.52-12.48,21.52-12.48l11.38,16.15s8.82-5.52,17.66-12.8h0s0,0,0,0l-13.63-15.43s0,0,0,0c5.2-4.61,9.96-9.44,14.22-14.38,0,0,14.14,12.55,15.69,14.03,4.49-5.06,8.61-10.38,12.26-15.92-7.36-5.84-16.95-12.43-17.1-12.53h0s0,0,0,0h0s5.76-9.22,8.11-14.84c0,0,9.33,5.09,18.14,10.82,2.16-4.82,3.95-9.83,5.23-14.94-5.79-3.49-18.66-9.24-18.66-9.24,1.1-4.33,1.76-8.57,1.95-12.65,0,0,9.36,2.97,18.79,7.7.15-3.97-.11-7.89-.8-11.68-7.99-3.83-18.61-6.44-18.61-6.44-.56-3.2-1.48-6.28-2.76-9.16,0,0,9.67,1.81,18.2,5.27-2.14-4.72-4.76-7.42-4.76-7.42-5.47-3-17.92-5.27-17.92-5.27-1.35-1.71-2.89-3.35-4.51-4.77,3.92.54,10.02,1.93,10.02,1.93-6.71-3.28-14.28-5.18-14.37-5.2,0,0-1.5-.99-3.29-1.94,0,0,18.77,3.85,28.97,11.53.93.7,1.81,1.47,2.71,2.34,1.03.98,1.93,2.09,2.72,3.17,20.32,27.8,2.74,81.37-46.78,118.84h18.42c-1.01-1.12-3.48-3.86-3.76-4.17,5.8-5.34,11.26-11.15,16.24-17.31l12.26,12.21h0c4.8-5.47,9.25-11.31,13.19-17.45,0,0-6.44-6.18-13.29-12.14,5.5-8.89,8.9-17.75,8.9-17.75.53.39,7.2,5.35,14.04,11.72,3.31-7.24,5.35-16.45,5.35-16.45-7.13-6.5-14.45-11.13-14.45-11.13,1.1-4.91,1.79-9.97,1.93-14.96,0,0,7.75,4.6,14.45,10.5.06-4.37-.32-8.72-1.24-12.98-6.65-5.75-14.03-9.61-14.03-9.61,0,0-.71-4.83-3.08-10.66.02,0,.04.02.05.03.46.23,3.98,2.02,10.2,6.45-4.85-6.3-13.2-12.49-13.2-12.49-.8-1.36-1.72-2.7-2.73-4,6.86,4.69,13.12,10.2,18.65,16.38,2.05,2.57,3.94,5.85,5.39,9.6.4,1.03.74,2.05,1.05,3.06,4.55,15.35,1.75,32.61-3.38,46.74-5.92,16.29-15.77,31.5-27.33,44.43h21.81c2.11-3,4.01-5.85,5.96-9.13-1.46-2.21-8.09-9.98-8.09-9.98,3.65-5.97,6.94-12.43,9.54-18.85,0,0,4.44,4.91,7.91,9.96,3.42-8.17,5.01-16.7,5.01-16.7-2.34-3.91-7.58-9.98-7.58-9.98,1.12-5.15,1.81-10.49,1.9-15.82,2.62,3.13,6.16,8.08,6.16,8.08,0,0,0-.01,0-.03-.67-9.7-5.67-18.52-6.78-20.37-.03-.18-.07-.38-.11-.61-.65-3.36-1.83-7.12-2.45-8.98,5.63,8.31,9.24,17.64,9.24,17.64,2.32,6.01,3.7,13.59,3.7,21.85,0,4.37-.88,27.18-18.3,52.91h5.51c3.23-6.05,6.82-13.57,9.21-19.97,0,0,0,0,0,.01.08.2,1.27,3.36,2.16,6.65,1.85-6.54,3.17-13.33,3.9-20.33h0c-.23-.91-.72-2.38-1-3.28,0,0,1.18-5.94,1.65-12.72.64,4.65.97,9.38.97,14.15,0,8.28-.98,16.4-2.87,24.24-.97,3.87-2.16,7.67-3.45,11.23h4.7c3.91-11.29,5.93-23.19,5.93-35.14,0-58.96-47.78-106.92-106.52-106.92Z\"/></svg>",
      word: "<svg class=\"pass-word\" viewBox=\"0 40.55 660.4 83.44\" aria-label=\"United\"><path fill=\"currentColor\" d=\"M0,82.27v-41.72h24.25v40.5c0,15.58,7.4,22.14,21.64,22.14,14.24,0,21.64-6.56,21.64-22.14v-40.5h24.25v41.72c0,29.15-14.74,41.72-45.89,41.72C14.74,123.99,0,111.42,0,82.27ZM200.93,88.14l-45.17-47.59h-23.92v81.77h22.58v-51.83l49.29,51.83h19.8V40.55h-22.58v47.59ZM265.79,122.32h24.25V40.55h-24.25v81.77ZM566.28,40.55h46.73c32.49,0,47.39,14.11,47.39,40.89s-14.91,40.89-47.39,40.89h-46.73V40.55ZM590.54,100.33h21.58c15.8,0,22.92-5.78,22.92-18.89s-7.12-18.89-22.92-18.89h-21.58v37.78ZM473.39,90.12h50.4v-17.36h-50.4v-12.18h54.29v-20.03h-78.55v81.77h78.99v-20.03h-54.74v-12.18ZM325.98,62.55h31.48v59.77h24.25v-59.77h31.48v-22h-87.22v22Z\"/></svg>" },
    // Avianca's current lockup is the condor to the RIGHT of the wordmark, both
    // out of `Logo Avianca (Colombia) 2023.svg` - the same file, so mark and word
    // match in weight. Set in currentColor, which is the carrier's own reversed
    // treatment: white on the red plate, exactly as Avianca prints it.
    avianca: { key: "av", ink: "#fff", plate: ["#d40000", "#ff0000"], livery: ["#ff0000", "#d40000", "#ff6b6b"],
      mark: "<svg class=\"pass-mark\" viewBox=\"132.89 0 35.69 40\" aria-hidden=\"true\"><path fill=\"currentColor\" d=\"M154.467 31.2565H158.152C159.68 31.2565 160.358 31.3831 160.784 31.5759C160.13 29.5448 158.068 27.9616 150.8 27.4183C151.961 28.762 153.18 30.0492 154.465 31.2565H154.467Z\"/><path fill=\"currentColor\" d=\"M150.801 27.4203C143.747 19.224 138.996 8.73765 137.091 0C137.091 0 133.214 3.4195 132.907 10.611C132.566 18.4704 136.782 26.394 150.666 27.4047C150.711 27.4125 150.758 27.4125 150.801 27.4183V27.4203Z\"/><path fill=\"currentColor\" d=\"M154.465 31.2565C148.991 31.2565 139.541 31.2565 139.541 31.2565C139.74 31.72 140.423 32.0452 141.979 32.1367C151.295 32.6897 152.613 40 165.947 40C167.117 40 167.847 39.9299 168.585 39.7916C163.316 38.1715 158.584 35.1258 154.465 31.2546V31.2565Z\"/></svg>",
      word: "<svg class=\"pass-word\" viewBox=\"0.45 4.41 123.8 27.74\" aria-label=\"Avianca\"><path fill=\"currentColor\" d=\"M43.19 4.40874C41.5211 4.40874 40.16 5.73681 40.16 7.36478C40.16 8.99274 41.49 10.3539 43.19 10.3539C44.89 10.3539 46.259 9.01611 46.259 7.36478C46.259 5.71344 44.9114 4.40874 43.19 4.40874Z\"/><path fill=\"currentColor\" d=\"M123.798 19.2785C123.798 14.4375 121.229 12.089 115.952 12.089C112.984 12.089 110.283 12.9263 108.149 14.342L109.954 17.8024C111.681 16.7567 113.245 16.2796 114.855 16.2796C116.466 16.2796 118.39 16.7976 118.39 19.2805V19.5453L115.212 19.6563C109.97 19.8335 106.957 22.2034 106.957 26.1662C106.957 30.129 109.641 32.5554 113.473 32.5554C115.597 32.5554 117.397 31.9128 118.964 30.5847C119.352 31.6304 119.862 32.1523 121.171 32.1523H124.244C123.944 31.1377 123.796 29.9771 123.796 28.2518V19.2785H123.798ZM118.392 27.1535C117.523 27.876 116.446 28.244 115.173 28.244C113.37 28.244 112.293 27.3346 112.293 25.8001C112.293 24.8362 112.659 23.5412 115.87 23.4419L118.392 23.3679V27.1554V27.1535Z\"/><path fill=\"currentColor\" d=\"M40.5261 32.1523H45.8559V30.2595V12.531H40.5261V32.1523Z\"/><path fill=\"currentColor\" d=\"M28.9025 32.1523H30.7525L38.9195 12.5291H33.5897L28.848 25.2451L24.1861 12.5291H18.8212L25.9854 30.018C26.5307 31.3714 27.3505 32.1523 28.9045 32.1523H28.9025Z\"/><path fill=\"currentColor\" d=\"M86.738 32.1523V19.2045C86.738 13.9545 83.4938 12.089 80.4618 12.089C78.1756 12.089 76.1329 12.8153 73.8721 14.4414L73.8448 14.3401C73.3969 13.1269 72.433 12.531 70.879 12.531H68.8441V32.1542H74.1661V18.6301C75.8856 17.3468 77.3967 16.7256 78.8027 16.7256C80.6001 16.7256 81.4043 17.9349 81.4043 20.6592V32.1523H86.738Z\"/><path fill=\"currentColor\" d=\"M105.826 30.5379L104.429 26.7484C103.312 27.3969 101.69 28.1661 99.7871 28.1661C95.834 28.1661 94.4358 24.9491 94.4358 22.1975C94.4358 18.7664 96.7044 16.2777 99.828 16.2777C101.645 16.2777 103.409 16.8736 104.794 17.9154L104.971 13.5281C103.267 12.5758 101.477 12.087 99.2632 12.087C96.4377 12.087 93.8555 13.1328 91.9997 15.0314C90.1303 16.93 89.106 19.5609 89.106 22.441C89.106 25.3211 89.9784 27.7649 91.5499 29.5526C93.2674 31.5194 95.7736 32.5534 98.7764 32.5534C101.594 32.5534 104.408 31.5077 105.828 30.536L105.826 30.5379Z\"/><path fill=\"currentColor\" d=\"M65.7731 32.1523C65.4732 31.1377 65.3213 29.9771 65.3213 28.2518V19.2785C65.3213 14.4375 62.7528 12.089 57.4697 12.089C54.5079 12.089 51.8089 12.9263 49.6707 14.342L51.4759 17.8024C53.207 16.7567 54.7688 16.2796 56.3734 16.2796C57.978 16.2796 59.9117 16.7976 59.9117 19.2805V19.5453L56.7336 19.6563C51.4934 19.8335 48.4848 22.2034 48.4848 26.1662C48.4848 30.129 51.1662 32.5554 54.9986 32.5554C57.127 32.5554 58.9185 31.9128 60.4881 30.5847C60.8834 31.6304 61.3877 32.1523 62.7002 32.1523H65.7731ZM59.9156 27.1535C59.051 27.876 57.9663 28.244 56.7025 28.244C54.8954 28.244 53.8185 27.3346 53.8185 25.8001C53.8185 24.8362 54.1846 23.5412 57.3977 23.4419L59.9156 23.3679V27.1554V27.1535Z\"/><path fill=\"currentColor\" d=\"M17.7404 32.1523C17.4405 31.1377 17.2886 29.9771 17.2886 28.2518V19.2785C17.2886 14.4375 14.7201 12.089 9.43703 12.089C6.47515 12.089 3.77616 12.9263 1.638 14.342L3.44317 17.8024C5.17434 16.7567 6.73609 16.2796 8.34069 16.2796C9.94529 16.2796 11.879 16.7976 11.879 19.2805V19.5453L8.70094 19.6563C3.46264 19.8335 0.454025 22.2034 0.454025 26.1662C0.454025 30.129 3.13549 32.5554 6.96783 32.5554C9.09625 32.5554 10.8878 31.9128 12.4573 30.5847C12.8526 31.6304 13.357 32.1523 14.6695 32.1523H17.7424H17.7404ZM11.8829 27.1535C11.0183 27.876 9.9336 28.244 8.66979 28.244C6.86267 28.244 5.7858 27.3346 5.7858 25.8001C5.7858 24.8362 6.1519 23.5412 9.36498 23.4419L11.8829 23.3679V27.1554V27.1535Z\"/></svg>" },
  };

  const AIR_GENERIC = { key: "generic", ink: "var(--on-accent)", plate: ["var(--accent)", "var(--accent)"],
    livery: ["var(--accent)", "var(--line-strong)", "var(--line-soft)"], mark: "", word: "" };
  // Matched on a token, not on the whole string, so "Southwest Airlines" and a bare
  // "Southwest" land on the same livery and a codeshare prefix cannot miss it.
  function airBrand(name) {
    const bits = String(name || "").toLowerCase().split(/[^a-z]+/).filter(Boolean);
    for (let i = 0; i < bits.length; i++) if (LIVERY[bits[i]]) return LIVERY[bits[i]];
    return AIR_GENERIC;
  }
  // The IANA zone an airport's clocks are written in, "" when we have not
  // resolved one. Cached on `airports` by IATA - see trips migration 021.
  const tzOf = (code) => (state.trip?.airports?.[String(code || "").trim().toUpperCase()])?.tz || "";

  // Minutes in the air, or null when either end is missing a clock. Days carry, so
  // a red-eye that lands tomorrow reads 6h 05m rather than going negative.
  //
  // Both stamps are LOCAL WALL-CLOCK AT THEIR OWN END, which is what you want
  // printed on the card and not what you can subtract. LGA 06:30 -> DEN 08:40 is
  // 4h10m in the air; read as one zone it is "2h 10m", and that is what the board
  // said. `zoneShift` supplies the jump between the two ends on that date.
  //
  // An unresolved zone falls back to the naive difference rather than to nothing:
  // a duration that is right whenever the two ends share a zone - which most of
  // this board's legs do - beats a blank on every leg. `legExact` is how a caller
  // asks which one it got, so an uncorrected cross-country number is never
  // printed as though it were measured.
  function legMinutes(f) {
    const sd = state.trip?.start_date;
    const d = T.parseStamp(f.departure_time, sd), a = T.parseStamp(f.arrival_time, sd);
    if (!d || !a || d.minutes == null || a.minutes == null) return null;
    const day = (Date.parse(`${a.date}T00:00:00Z`) - Date.parse(`${d.date}T00:00:00Z`)) / 86400000;
    const shift = T.zoneShift(tzOf(f.from_airport), tzOf(f.to_airport), d.date);
    const m = Math.round(day) * 1440 + a.minutes - d.minutes + (shift || 0);
    return m > 0 && m < 3 * 1440 ? m : null;
  }

  // True when legMinutes() had both zones and the number is the real elapsed
  // time; false when it is a same-zone assumption that nobody has confirmed.
  function legExact(f) {
    const from = tzOf(f.from_airport), to = tzOf(f.to_airport);
    if (!from || !to) return false;
    const sd = state.trip?.start_date;
    const d = T.parseStamp(f.departure_time, sd);
    return d ? T.zoneShift(from, to, d.date) != null : false;
  }
  // "Thu Sep 10". dayShort gives the month and date; the weekday in front is what
  // a pass is read by - nobody checks a boarding pass against a date number.
  function dayLong(iso) {
    const d = Date.parse(`${iso || ""}T00:00:00Z`);
    return Number.isNaN(d) ? dayShort(iso) : `${U.DOW[new Date(d).getUTCDay()]} ${dayShort(iso)}`;
  }
  // The clock, split so the meridiem can be set small beside a big number. fmtClock
  // returns "10:20a"; anything it cannot parse passes through whole rather than
  // getting chopped.
  function clockParts(mins) {
    const m = /^(\d+:\d\d)([ap])$/.exec(T.fmtClock(mins) || "");
    return m ? [m[1], `${m[2]}m`] : [T.fmtClock(mins) || "—", ""];
  }

  // ── THE ROUTE, DRAWN ────────────────────────────────────────────────────────
  // The diagram has to agree with the label over it. A one-stop itinerary drawn
  // as one unbroken run asserts "nonstop" in the one place on the card that draws
  // the journey, while `via IAD` sits right beside it saying otherwise.
  //
  // So it is an altitude profile: climb, cruise, descend, once per leg, in the
  // carrier's own colour, under the duration and stops (Sam 2026-10-13 Workbench
  // pick "Altitude profile", over a route trace, sky strip, dial and ruler; the tall
  // dashed arch before it was rejected). A connection is a second hump, which you
  // count without reading. Legs are drawn equal width: the row carries one total
  // duration, not per-leg times, so a wider hump would be a claim with no data.
  //
  // The profile stretches to its cell (preserveAspectRatio none, strokes kept
  // 2px by non-scaling-stroke); the plane is its own fixed-size svg on the cruise
  // line over the first leg, so the stretch never distorts it.
  const PLANE = "M23 12 L13 10.6 L5 3.5 L3.5 5 L10 10.9 L3.5 10.9 L0.8 7.4 L0 8.4 L1.6 12 "
    + "L0 15.6 L0.8 16.6 L3.5 13.1 L10 13.1 L3.5 19 L5 20.5 L13 13.4 Z";
  let altSeq = 0;                     // gradient ids: one per card, or every card paints the first card's livery
  function routeSvg(stops) {
    const W = 300, G = 59, TOP = 3, legs = stops + 1, lw = W / legs, n = (x) => Math.round(x * 10) / 10;
    let d = `M0 ${G}`;
    for (let i = 0; i < legs; i++) {
      const a = i * lw, b = a + lw, c = Math.min(30, lw * 0.24);
      d += ` L${n(a)} ${G} C${n(a + c * .6)} ${G} ${n(a + c * .5)} ${TOP} ${n(a + c * 1.4)} ${TOP}`
        + ` L${n(b - c * 1.4)} ${TOP} C${n(b - c * .5)} ${TOP} ${n(b - c * .6)} ${G} ${n(b)} ${G}`;
    }
    const id = `pass-alt${++altSeq}`;
    return `<svg class="pass-alt" viewBox="0 0 ${W} 60" preserveAspectRatio="none" aria-hidden="true">
            <defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0"/><stop offset="1"/></linearGradient></defs>
            <path class="pass-alt-fill" d="${d} Z" fill="url(#${id})"/><path class="pass-alt-line" d="${d}"/>
            <path class="pass-alt-ground" d="M0 ${G}H${W}"/>
          </svg><svg class="pass-plane" viewBox="0 0 24 24" style="left:calc(${n(50 / legs)}% - 10px)" aria-hidden="true">
            <path d="${PLANE}"/></svg>`;
  }

  // the pass's two actions as drawn symbols (arrow up-right, pencil) rather than the
  // ↗ and ✎ text glyphs, which set in the fallback font and read as web, not Apple
  // (Sam 2026-10-12 mark: "these are not apple buttons")
  const PASS_ICON = {
    out: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5 11 11 5M6 5h5v5"/></svg>',
    edit: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 13l.6-2.8L10.8 3a1.4 1.4 0 0 1 2 2L5.6 12.4 3 13Zm6.6-8.8 2 2"/></svg>',
  };



Object.assign(U, { BAGS_MIN, ptOf, airportPt, inUS, airportLead, driveMin, clockOf, dur, absOf, baseOf, stayClock, bookedCar,
  rowBrand, carAddr, noteVal, onCar, groundOptions, readerLegs, readerMember, timelineReads, crewLegs, crewArrivals,
  dayReadHTML, feeTableHTML, flightResearchHTML, stampOrBlank, legKey, crewFlights, groupIsViewer, memberFor, meMember, flightlessMembers,
  flightGapHTML, bookedSplit, LIVERY, AIR_GENERIC, airBrand, tzOf, legMinutes, legExact, dayLong, clockParts, routeSvg,
  PASS_ICON });
})();
