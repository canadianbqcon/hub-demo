/* hub · trips page, housing (2026-10-13): React port of trips.js lines 5789-6371 (boarding pass, flight panel,
   housing board, booked stay helpers). Near-verbatim: plain functions that build HTML strings and write them
   into the fixed hosts, mounted by trips-core.jsx. Part contract: see trips-core.jsx header. */
(() => {
const U = window.TripsUI;
const { esc, setHTML, state, T, $, money, isGuest, viewerKey, isViewer, myFlights, isCommitted, isDead, rowCost } = U;
const { terminalOf, terminalText, geocodeTrip, renderDayMap, dayShort, stampShort, nightsOf, partySize,
  flightTags, stayCtx, housingTags, whatItBuys, flightLink, flightTrackLink, picked, fitsParty, legsOf, bindGround,
  feeTableHTML, flightResearchHTML, stampOrBlank, crewFlights, groupIsViewer, meMember, flightGapHTML, bookedSplit, airBrand, tzOf,
  legMinutes, legExact, dayLong, clockParts, routeSvg, stayPanel, stayMissing, stayStops, staySplit, bindPanel,
  repaint, otherCostsHTML, groupHTML, gapCell, gapList } = U.fwd("terminalOf", "terminalText", "geocodeTrip",
  "renderDayMap", "dayShort", "stampShort", "nightsOf", "partySize", "flightTags", "stayCtx", "housingTags",
  "whatItBuys", "flightLink", "flightTrackLink", "picked", "fitsParty", "legsOf", "bindGround", "feeTableHTML", "flightResearchHTML",
  "stampOrBlank", "crewFlights", "groupIsViewer", "meMember", "flightGapHTML", "bookedSplit", "airBrand", "tzOf",
  "legMinutes", "legExact", "dayLong", "clockParts", "routeSvg", "stayPanel", "stayMissing", "stayStops",
  "staySplit", "bindPanel", "repaint", "otherCostsHTML", "groupHTML", "gapCell", "gapList");

  // ── ONE LEG, AS THE PASS IT IS ──────────────────────────────────────────────
  // This was a fact grid: five label/value pairs, the flight number one of them,
  // and every carrier rendered identically. On a board where three people fly
  // three airlines that is three cards you have to read to tell apart.
  //
  // A boarding pass is not a fact grid. The carrier is the first thing you see,
  // the two airport codes are the biggest thing on it, and the times sit under
  // them in the order you use them. So the card is painted in the carrier's own
  // livery - plate, mark, belly stripe - and the identifying facts drop to rows
  // underneath, where a locator you only read at 5am belongs.
  //
  // It borrows the crew card's physical stack MINUS the foil and the shimmer:
  // stock, print, and a laminate hotspot that tracks the cursor. A pass is
  // printed card under lamination, not a chase card, and making it shiny would
  // say "rare" about a seat somebody simply bought.
  //
  // Still one function and one call: the three callers (his own legs, a crew
  // member's, a guest's own) all come through here, so the board cannot end up
  // half ported.
  function flightLegBlock(_t, g, f, who) {
    const br = airBrand(f.airline);
    const sd = state.trip?.start_date;
    const d = T.parseStamp(f.departure_time, sd), a = T.parseStamp(f.arrival_time, sd);
    const mins = legMinutes(f);
    const dc = d && d.minutes != null ? clockParts(d.minutes) : ["—", ""];
    const ac = a && a.minutes != null ? clockParts(a.minutes) : ["—", ""];
    // Each clock is local to ITS OWN airport, which is invisible until the two
    // disagree - and then the card reads as a contradiction: 6:30a to 8:40a
    // labelled 4h 10m. So the zone is named under the clock, but only on a leg
    // that actually crosses one. Tagging every leg would put "EDT / EDT" on a
    // shuttle to Boston and teach the reader to stop seeing the tag.
    const dz = tzOf(f.from_airport), az = tzOf(f.to_airport);
    const cross = dz && az && T.zoneShift(dz, az, d?.date) ? 1 : 0;
    const dzl = cross ? T.tzAbbr(dz, d?.date) : "";
    const azl = cross ? T.tzAbbr(az, (a?.date) || (d?.date)) : "";
    // +1 only when it actually crosses midnight. The old cell printed the date on
    // both ends, which said "Dec 20 → Dec 20" on every same-day flight and buried
    // the one case where the day is the thing you need to notice.
    const over = d && a?.date && d.date && a.date !== d.date
      ? Math.round((Date.parse(`${a.date}T00:00:00Z`) - Date.parse(`${d.date}T00:00:00Z`)) / 86400000) : 0;
    // A stop is a fact about the ROUTE, so it belongs over the profile between the
    // two codes, not tacked onto the flight number where it read as part of the
    // number ("WN 0561 via ORD") in 16px display type on a plate with no room.
    const via = (f.via?.length) ? `via ${f.via.join(", ")}` : "";
    const num = (f.flight_num && f.flight_num !== "—") ? String(f.flight_num).trim() : "";
    // The seat is bought, so this points at the flight itself. A row carrying no
    // usable flight number can't be identified, and only then does it fall back
    // to the route board - which is also why the label changes with the target.
    const track = flightTrackLink(f), out = track || flightLink(f);
    // A note line written `Ticket: 0142335174938` is a FIELD with no column, and
    // rendering it inside the notes VALUE put its own label in column 2 while the
    // word "notes" sat in column 1 - the key column saying the wrong thing about
    // every line under it. Keyed lines are promoted to rows of their own, so
    // ticket, fare and Rapid Rewards read exactly like confirmation does. What is
    // left is prose and stays under notes, drawn even when empty so the card has
    // one shape and a blank says "nothing written" rather than "row missing".
    const nl = lines(guestSafeNotes(f.notes));
    const keyedAll = nl.map((l) => KEYED.exec(l)).filter(Boolean);
    const prose = nl.filter((l) => !KEYED.test(l));
    // Boarding time is the clock the morning is actually run on: it is the one you
    // have to BE somewhere for, and the departure beside it is the one you can do
    // nothing about. It arrives as a keyed note line, which filed it as row six of
    // a label column at 13px - the same weight as a record locator. So it is lifted
    // out of the rows and set as a clock beside the other two, and drops out of
    // `keyed` in the same move rather than being printed in both places.
    // Only when it parses AS a clock: a boarding note reading "at the gate" is not
    // a time and stays a row, where prose belongs.
    const bt = keyedAll.find((m) => /^boarding\s*time$/i.test(m[1].trim()) && T.parseClock(m[2]) != null);
    const bc = bt ? clockParts(T.parseClock(bt[2])) : null;
    const keyed = keyedAll.filter((m) => m !== bt);
    // The date leaves the middle of the clock row to make that space, and lands on
    // the tag line beside the countdown - which is the same fact one step coarser
    // ("Thu Sep 10 · tomorrow"), so the two belong together and neither is lost.
    const sub = [ticketedAs(who, f), d ? dayLong(d.date) : stampOrBlank(f.departure_time),
      countdown(daysAway(f.departure_time))].filter(Boolean).join(" · ");
    const end = (code, term, right) => `<div class="pass-end${right ? " pass-end-r" : ""}">
      <b>${esc(code || "—")}</b>${term ? `<i>${esc(term)}</i>` : ""}</div>`;
    const row = (k, v) => v ? `<div><dt>${esc(k)}</dt><dd>${v}</dd></div>` : "";
    return `<div class="legcard legcard-${esc(g.leg)} pass" data-air="${esc(br.key)}" style="${
      `--plate-a:${br.plate[0]};--plate-b:${br.plate[1]};--air-ink:${br.ink};`
      + br.livery.map((c, i) => `--l${i + 1}:${c}`).join(";")}">
      <div class="pass-plate">
        <span class="pass-brand">${br.mark || ""}${
          br.word || `<span class="pass-name">${esc(f.airline || "flight")}</span>`}</span>
        <span class="pass-no">${esc(num || "—")}</span>
      </div>
      <div class="pass-tag">
        <span class="pass-leg">${esc(U.LEG_LABEL[g.leg] || g.leg)}</span>
        ${sub ? `<span class="pass-sub" title="${esc(sub)}">${esc(sub)}</span>` : ""}
        <span class="pass-acts">${out ? `<a class="hub-section-head-act hub-section-head-act-i lgroup-act" href="${esc(out)}"
          target="_blank" rel="noopener"
          title="${track ? "track this flight" : "open the route board"}"
          aria-label="${track ? "track this flight" : "open the route board"}">${U.PASS_ICON.out}</a>` : ""
        }<button class="hub-section-head-act hub-section-head-act-i lgroup-act" data-editrow="flights:${esc(f.id)}"
          title="edit this leg" aria-label="edit this leg">${U.PASS_ICON.edit}</button></span>
      </div>
      <div class="pass-route">
        ${end(f.from_airport, terminalText(f.terminal_from || terminalOf(f)?.code), 0)}
        <div class="pass-arc">
          ${routeSvg(f.via?.length ? f.via.length : 0)}
          <em${mins && !legExact(f) ? ' class="pass-approx" title="both ends are read as the same time zone — one of these airports has no zone on file yet, so this is time on the clock, not time in the air"' : ""
            }>${mins ? `${Math.floor(mins / 60)}h ${String(mins % 60).padStart(2, "0")}m` : "\u00a0"}</em>
          ${via || bc ? `<small title="${esc([via, bc ? `boards ${bc.join("")}` : ""].filter(Boolean).join(" · "))}">${esc(via)}${
            via && bc ? " · " : ""}${bc ? `<span class="pass-board">boards <b>${esc(bc[0])}</b><i>${esc(bc[1])}</i></span>` : ""}</small>` : ""}
        </div>
        ${end(f.to_airport, terminalText(f.terminal_to), 1)}
        <div class="pass-clock"><b>${esc(dc[0])}</b><i>${esc(dc[1])}</i><span>departs${dzl ? ` · ${esc(dzl)}` : ""}</span></div>
        <div class="pass-clock pass-r"><b>${esc(ac[0])}</b><i>${esc(ac[1])}</i>${
          over ? `<u>+${over}</u>` : ""}<span>arrives${azl ? ` · ${esc(azl)}` : ""}</span></div>
      </div>
      <dl class="pass-rows">
        ${row("confirmation", f.confirmation ? `<span class="mono">${esc(f.confirmation)}</span>`
          : gapCell("flights", f, "confirmation"))}
        ${keyed.map((m) => row(m[1], esc(m[2]))).join("")}
        ${row("terminals", gapList("flights",
          Object.assign({}, f, { terminal_from: f.terminal_from || terminalOf(f)?.code || "" }),
          ["terminal_from", "terminal_to"]))}
        <div><dt>notes</dt><dd>${prose.length ? stayList(prose.join("\n"), "")
          : `<span class="hub-pending">—</span>`}</dd></div>
      </dl>
      <div class="pass-livery"></div>
      <div class="pass-glare"></div>
    </div>`;
  }

  // The heading uses the roster name - he thinks in "Aria" - so the summary line
  // has to carry the name actually on the ticket, or the record locator, the
  // check-in kiosk and the boarding pass all disagree with the board and no
  // explanation is on screen. Silent when the two names are the same.
  // A short form of the same name is not a different name: "Akshay" under a head
  // that reads "Akshay Okafor" tells him nothing he cannot see. Silent
  // whenever every token of the ticket name is already in the roster name.
  function ticketedAs(who, f) {
    const on = (f.passenger || "").trim();
    if (!who || !on || on === who) return "";
    const rosterTokens = who.toLowerCase().split(/\s+/);
    const shortForm = on.toLowerCase().split(/\s+/).every((t) => rosterTokens.indexOf(t) >= 0);
    return shortForm ? "" : `ticketed as ${on}`;
  }
  // Every other traveller's legs, rendered with the block his own get, in roster
  // order so the section reads in the same order as the crew list.
  //
  // `want` splits the section in two, and that split is the whole point of
  // VIEWER. A guest opened this page to find out when THEY fly; their own ticket
  // was rendering under "travelling with you", below two legs of a fare
  // comparison that is not theirs and cannot be. So the person reading gets
  // pulled out and rendered first, above his board, and everybody else stays
  // under it. On Hub there is no viewer, "yours" is empty, and the board reads
  // exactly as it did.
  // A guest reading the board with no ticket of their own on it - never true on
  // Hub (there is no viewer) and never true for Sam reading his own link.
  // What this rules out: crewFlightsHTML(t, "yours") going quiet just because
  // nobody has entered the guest's ticket yet, which otherwise leaves the "your
  // flights" slot empty and the fare figures above it defaulting to his board
  // with no word that it isn't the reader's.
  // A row of your own or nothing. A rider named only in the prose of somebody
  // else's row used to count as covered, which quietly asserted a seat nobody on
  // this board paid for or booked. Sam's rule, 2026-08-25: "i didnt buy her
  // ticket, if she wants it on the board she can share it. otherwise same as
  // anyone without a flight info listed."
  function viewerFlightMissing(t) {
    return !!viewerKey() && !isViewer(meMember(t)) && !crewFlights(t).some(groupIsViewer);
  }

  // What the row of cards IS, said once above it: the carrier they are all on and
  // how many legs it comes to. The flight numbers stay on the cards, where each
  // one belongs to exactly one leg - hoisting them into the head would print two
  // numbers over two cards and leave you matching them up by eye.
  function legLabelSummary(g) {
    const al = [];
    g.legs.forEach((lg) => { lg.rows.forEach((r) => {
      const a = (r.airline || "").trim();
      if (a && al.indexOf(a) < 0) al.push(a);
    }); });
    const n = g.legs.length;
    return [al.join(" + "), n + (n === 1 ? " leg" : " legs")].filter(Boolean).join(" · ");
  }

  function crewFlightsHTML(t, want) {
    const mine = want === "yours";
    const crew = crewFlights(t).filter((g) => groupIsViewer(g) === mine);
    // Sam's blank-passenger rows never show up in crewFlights - that field
    // is what keeps them his for the cost model on Hub. But a guest reading
    // someone else's trip isn't the trip's default reader either, so on
    // "travelling with you" he goes in as one more name, not a header set
    // apart from the crew list he's reading (see ownFlightsHTML, which used to
    // print that header and now defers to this instead).
    if (!mine && viewerKey() && !isViewer(meMember(t))) {
      const me = meMember(t), ownLegs = legsOf(myFlights(t)).filter((g) => g.live);
      if (me && ownLegs.length) crew.push({ who: me.name, whos: [me.name], people: [me], names: [me.name], member: me, legs: ownLegs });
    }
    if (!crew.length) {
      if (mine && viewerFlightMissing(t)) return `<div class="hub-section-head lgroup-head lgroup-sub lgroup-you">
        <span class="hub-section-head-t lgroup-l">your flights</span></div>
        <div class="hub-note is-warn">your flight isn't on this board yet — forward the confirmation
        email to Sam and he'll add it.</div>`;
      return "";
    }
    const nms = (g) => (g.names?.length ? g.names : [(g.member?.name || g.who)])
      .map((x) => String(x).trim()).filter(Boolean);
    const nm = (g) => nms(g).join(" and ");
    const order = (t.members || []).map((m) => m.id);
    crew.sort((a, b) => (a.member ? order.indexOf(a.member.id) : 99) - (b.member ? order.indexOf(b.member.id) : 99));
    const legs = crew.reduce((n, g) => n + g.legs.length, 0);
    const people = crew.reduce((n, g) => n + nms(g).length, 0);
    // The name on the card only earns its place when the ticket disagrees with the
    // roster, and only when there is ONE person to disagree about. On a shared
    // booking the head already prints both roster names and the passenger field is
    // "Aaron + Jasmine" - repeating that under every card names nobody twice.
    const pairs = (g) => `<div class="legpair">${g.legs.map((lg) =>
      flightLegBlock(t, lg, lg.rows.filter(isCommitted)[0] || lg.rows[0],
        nms(g).length === 1 ? nms(g)[0] : "")).join("")}</div>`;
    // One traveller needs no name repeated under a head that already names them.
    if (mine) return `<div class="hub-section-head lgroup-head lgroup-sub lgroup-you"><span class="hub-section-head-t lgroup-l">your flights</span>
      <span class="hub-section-head-sum lgroup-sum">${esc(nm(crew[0]))} · ${legs} ${legs === 1 ? "leg" : "legs"} on ${
        nms(crew[0]).length > 1 ? "the booking you share" : "your own ticket"}</span></div>
      ${crew.map(pairs).join("")}`;
    // The head over a row of cards is the FLIGHT, and the names are who is on it -
    // one chip each, never "Aaron + Jasmine" as though that were somebody. Two
    // people on one booking read as two people sharing one journey, which is what
    // they are, and both get the whole card rather than half a name.
    return `<div class="hub-section-head lgroup-head lgroup-sub"><span class="hub-section-head-t lgroup-l">travelling with you</span>
      <span class="hub-section-head-sum lgroup-sum">${people} ${people === 1 ? "person" : "people"} · ${
        legs} ${legs === 1 ? "leg" : "legs"} on ${crew.length === 1 ? "one booking" : `${crew.length} bookings`}</span></div>
      ${crew.map((g) => `<div class="tvl"><div class="tvl-head">${
        nms(g).map((n) => `<span class="tvl-n">${esc(n)}</span>`).join("")}
        <span class="tvl-sum">${legLabelSummary(g)}</span></div>${pairs(g)}</div>`).join("")}`;
  }

  // A guest reading someone else's trip does not get told whose trip it is -
  // he is not the reader's default, he is one more name on the crew list, and
  // his legs render inside "travelling with you" (see crewFlightsHTML) instead
  // of a header set apart from everyone else. Rendering him here too would
  // print his legs twice.
  function ownFlightsHTML(t, inner) {
    const me = meMember(t);
    if (viewerKey() && me && !isViewer(me)) return "";
    return `<div class="legpair">${inner}</div>`;
  }

  function flightPanel(head, list, t, live, tabsHTML) {
    const picks = live.map((g) => ({ leg: g.leg, row: g.rows.filter(isCommitted)[0] }));
    const first = picks.filter((x) => x.leg !== "return")[0] || picks[0];
    const bothWays = picks.length > 1 || picks.some((x) => x.leg === "roundtrip");
    const when = picks.map((x) => `${U.LEG_LABEL[x.leg] || x.leg} ${stampShort(x.row.departure_time)}`)
      .concat(countdown(daysAway(first.row.departure_time)) || []).join(" · ");

    // The headline on a booked board is the day you fly, not what it cost. The
    // fare stopped being a decision the moment the seat was bought, so it moves
    // to the cost tab and the board goes back to answering "when".
    //
    // Unless the reader isn't on this leg at all - then "the day you fly" is
    // Sam's day, not theirs, and a guest reads a headline as their own
    // flight by default. Say it's missing instead of handing over his.
    setHTML(head, tabsHTML + (isGuest() && viewerFlightMissing(t) ? `
      <div class="hub-figure">
        <div class="hub-figure-fig">
          <span class="hub-figure-n">—</span>
          <span class="hub-figure-l">your flight isn't on the board</span>
        </div>
        <div class="hub-figure-split">forward your confirmation email to Sam and he'll add it</div>
      </div>` : `
      <div class="hub-figure">
        <div class="hub-figure-fig">
          <span class="hub-figure-n">${esc(dayShort(T.parseStamp(first.row.departure_time, t.start_date)?.date) || "—")}</span>
          <span class="hub-figure-l">${bothWays ? "departure · booked both ways" : "departure · booked one way"}</span>
        </div>
        <div class="stay-when">${esc(when)}</div>
        <div class="hub-figure-split">${esc(bookedSplit(picks))}</div>
      </div>`));

    // The losers, per leg, and only where there are any. A leg holding nothing but
    // its booked row renders no "what it beat" heading - an empty one reads as a
    // comparison that happened and is missing, rather than one that never had a
    // second entrant.
    const beaten = live.map((g, i) => {
      const rest = g.rows.filter((r) => r !== picks[i].row);
      return rest.length ? groupHTML({
        kind: "flights", key: `flights:${g.leg}:beat`, lead: 0,
        label: `what ${U.LEG_LABEL[g.leg] || g.leg} beat`, sub: "",
        link: flightLink, tags: (f) => flightTags(f, null), ctx: () => ({ best: null }),
      }, rest) : "";
    }).join("");

    setHTML(list, crewFlightsHTML(t, "yours")
      + ownFlightsHTML(t, live.map((g, i) => flightLegBlock(t, g, picks[i].row)).join(""))
      + crewFlightsHTML(t) + flightGapHTML(t)
      // The fee table survives the handover - a bag still costs what it costs at
      // the counter on a ticket you already own. (The day read lives in the right
      // rail now - see groundContext - for both the comparison and the booked board.)
      + flightResearchHTML(t) + feeTableHTML(t) + beaten);

    bindGround(head);
    bindPanel(list, t);
  }

  // ── HOUSING ─────────────────────────────────────────────────────────────────
  // Same shape as the fare board, one axis over. A stay's all-in total is already
  // in the row, so the control that reprices everything isn't bags - it's how many
  // people are sleeping there, which turns one number into six per-person numbers
  // and decides outright whether an option is even eligible.
  function listHousing(head, list) {
    const t = state.trip;
    const rows = t.housing || [], live = rows.filter((r) => !isDead(r));
    // The decision, once made, stops being the question. Hand the panel over.
    const booked = rows.filter(isCommitted)[0];
    if (booked) return stayPanel(head, list, t, booked, rows);
    const c = stayCtx(rows);
    const pick = picked("housing", live, fitsParty);
    const base = c.bestFit;
    const over = pick && base ? rowCost(pick) - rowCost(base) : 0;
    // "over the cheapest" is a number nobody can act on when the cheapest can't
    // hold everyone - name which floor the gap is being measured from
    const floorLabel = base && c.best && base !== c.best ? `the cheapest that fits ${c.party}` : "the cheapest";
    const nights = pick ? nightsOf(pick) : null;

    setHTML(head, `
      <div class="hub-figure">
        <div class="hub-figure-fig">
          <span class="hub-figure-n">${money(pick ? rowCost(pick) : 0)}</span>
          <span class="hub-figure-l">${pick && nights ? `all-in, ${nights} night${nights === 1 ? "" : "s"}` : "all-in"}</span>
        </div>
        <div class="hub-figure-delta ${over > 0 ? "is-over" : "is-floor"}">${
          !pick ? "nothing on the board yet"
          : over > 0 ? `${money(over)} over ${floorLabel}` : `${floorLabel} on the board`}</div>
        <div class="hub-figure-split">${pick ? esc(staySplit(pick, c)) : ""}</div>
      </div>
      <div class="lbar">
        <span class="lbar-l" title="defaults to the crew list — change it to see what a seventh head does to every option">sleeping</span>
        <span class="lstep"><button class="lstep-b" id="partyDown" aria-label="one fewer">−</button
          ><span class="lstep-n" id="partyN">${c.party}</span
          ><button class="lstep-b" id="partyUp" aria-label="one more">+</button></span>
        <span class="lbar-hint">reprices every option per person, and rules out the ones that won't hold everyone</span>
      </div>${stayMissing(live) ? `<div class="funnel-tools"><span class="ftot-l">${stayMissing(live)} option${stayMissing(live) > 1 ? "s" : ""} not on the map yet</span><button class="funnel-add" id="hgeo">geocode locations</button></div>` : ""}`);
    if (stayMissing(live)) $("hgeo").onclick = geocodeTrip;

    // The map is the half of a housing decision a table can't hold: four options
    // at the same price are not the same option when one is 25 minutes further
    // out. Same slot and same rebuild rule as the day view - only redraw when the
    // pins actually change, or picking a row throws away your pan and zoom.
    const stops = stayStops(live);
    const mapKey = `housing|${stops.map((s) => `${s.sel}@${s.lat},${s.lng}`).join(";")}`;
    const remap = mapKey !== U.mut.dayMapKey;
    if (remap) {
      U.mut.dayMapKey = mapKey;
      setHTML($("dayMapHost"), `<div class="dayv-map" id="dayMap"><div class="dayv-map-note">loading map…</div></div>`);
    }

    setHTML(list, groupHTML({
      kind: "housing", key: "housing", lead: 1, label: "the stay",
      sub: t.destination || "", pickKey: "housing", link: (h) => h.url || "",
      tags: housingTags, ctx: stayCtx, buys: whatItBuys,
    }, rows) + otherCostsHTML(t));

    bindPanel(list, t);
    const dn = $("partyDown"), up = $("partyUp");
    if (dn) dn.onclick = () => { state.party = Math.max(1, partySize() - 1); repaint("partyDown"); };
    if (up) up.onclick = () => { state.party = partySize() + 1; repaint("partyUp"); };
    if (remap) renderDayMap(stops, { route: false, emptyNote: "no option has a location yet — geocode to put them on the map" });
  }
  // ── THE STAY, ONCE IT'S BOOKED ──────────────────────────────────────────────
  // A booked row ends the comparison and starts a different job. From here every
  // question this panel gets asked is operational - what's the wifi, do I need to
  // bring a towel, what time do we have to be out, what do I owe - and not one of
  // them is answerable from a table whose every column asks "is this the one".
  // The comparison board answered the question it was built for and then kept
  // rendering: a board of one row, badged "cheapest" against itself, measuring a
  // $1,866 floor it also is. Same rows, same data, different surface. The
  // shortlist stays underneath when there is still one, because a decision with
  // the options deleted out from under it can't be re-read later.

  // An item's own sub-detail sits on the line under it, so items are separated by
  // a BLANK line - see migration 010. Splitting on \n instead shatters the nine
  // items that carry one into orphan fragments.
  // Airbnb lists everything, including the things every house has. Sixty-three
  // items where about twenty decide anything means the record player and the fire
  // pit are buried under hot water, plates and a smoke alarm. The test each entry
  // below had to pass: would its ABSENCE be the surprising fact? If yes it stays
  // on the board; if no it is noise and gets dropped on render. Cut per Sam
  // 2026-08-26. Family items go as a group (no kids on these trips), safety items
  // go because all four are legally required anyway.
  //
  // Matched whole-word against the label, so one entry covers its variants:
  // "oven" takes "Stainless steel oven", "children" takes both the books and the
  // dinnerware, "hot water" takes the kettle with it. Nothing is deleted from the
  // DB - this is a render filter, so putting a line back here brings the item back.
  const AMENITY_NOISE = [
    "hair dryer", "shampoo", "conditioner", "body soap", "hot water",
    "essentials", "hangers", "bed linens", "room-darkening shades", "iron", "clothing storage",
    "tv",
    "travel crib", "children", "high chair", "baby bath",
    "central air", "portable fans", "central heating",
    "smoke alarm", "carbon monoxide alarm", "fire extinguisher", "first aid kit",
    "wifi",
    "kitchen", "refrigerator", "microwave", "cooking basics", "dishes and silverware",
    "freezer", "oven", "stove", "wine glasses", "toaster", "baking sheet", "dining table",
    "outdoor furniture", "outdoor dining area", "private patio or balcony", "private backyard",
    "free street parking",
    "long term stays allowed", "self check-in", "smart lock",
  ];
  const AMENITY_NOISE_RE = new RegExp(`\\b(?:${AMENITY_NOISE.join("|")})\\b`, "i");

  function amenityItems(h) {
    return String(h.amenities || "").split(/\n\s*\n/).map((s) => s.trim()).filter(Boolean)
      .map((a) => {
        const i = a.indexOf("\n");
        return i < 0 ? { l: a, d: "" } : { l: a.slice(0, i).trim(), d: a.slice(i + 1).replace(/\s+/g, " ").trim() };
      })
      // A `# Heading` always survives the filter; amenityGroups drops the ones
      // left with nothing under them, so a group cut to zero disappears whole.
      .filter((a) => a.l.indexOf("# ") === 0 || !AMENITY_NOISE_RE.test(a.l));
  }
  // Whole days from today to a stamp's date. Normalised through UTC midnight on
  // both sides so an 11pm render doesn't report the trip a day nearer than it is.
  function daysAway(stamp) {
    const p = T.parseStamp(stamp, state.trip?.start_date);
    if (!p) return null;
    const now = new Date();
    return Math.round((Date.parse(`${p.date}T00:00:00Z`)
      - Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())) / 86400000);
  }
  const countdown = (d) => d == null ? "" : d > 1 ? `${d} days out` : d === 1 ? "tomorrow" : d === 0 ? "today" : "";

  const stayBlock = (label, sum, body, act) => !body ? "" : `<div class="hub-section-head lgroup-head lgroup-sub">
    <span class="hub-section-head-t lgroup-l">${esc(label)}</span>${sum ? `<span class="hub-section-head-sum lgroup-sum">${esc(sum)}</span>` : ""}${act || ""}</div>
    <div class="stay-body">${body}</div>`;
  // pairs: [label, already-escaped html, wide?]. A pair with an empty value is
  // dropped rather than rendered as "-": on this surface a blank field means
  // nobody has looked it up, and a dash reads as a checked answer of "none".
  // A value whose leading text (past any wrapping spans) is a sentence (over 28 characters, has a space) is
  // set at medium weight; a code, a time or a network name stays bold to be found.
  const isProse = (v) => { const t = String(v).replace(/^(\s*<span\b[^>]*>)+/, "").split("<")[0].trim(); return t.length > 28 && t.indexOf(" ") > 0; };
  const stayFacts = (pairs) => {
    const on = pairs.filter((p) => p[1]);
    return on.length ? `<div class="hub-fact-grid">${on.map(([k, v, wide]) =>
      `<div class="hub-fact${wide ? " hub-fact--wide" : ""}"><span class="hub-fact-k">${esc(k)}</span>
        <span class="hub-fact-v stay-fv${isProse(v) ? " stay-fv--prose" : ""}">${v}</span></div>`).join("")}</div>` : "";
  };
  // Every one of these fields is a LIST that was being rendered as a wall: nine
  // house rules in one paragraph means finding the one you came for is a parsing
  // job. The DB stores one item per line, so render one per line. A row still
  // holding a paragraph renders as a single item rather than getting sentence-split
  // - splitting "No parties or events. Evidence of one means you leave with no
  // refund" in half would tear a rule from its consequence.
  const lines = (v) => String(v || "").split("\n").map((s) => s.trim()).filter(Boolean);
  // On an Airbnb the wifi arrives on Airbnb's clock, not ours - 48 hours before
  // check-in - so an empty field before then is the system working rather than a
  // lost password, and saying which beats a blank. That sentence is only true of
  // an Airbnb, though: printing it over a Hyatt booking states something false
  // about the hotel, so it is gated on the listing actually being one.
  //
  // But the empty state used to be that sentence and NOTHING else, which is a note
  // describing a job rather than a way to do it: the only route to typing the
  // password in was the twenty-field edit form behind "edit the stay". The wifi is
  // read off a guidebook, on a phone, standing in the doorway - so the field that
  // wants it gets one box, one tap away. The waiting line survives beside the
  // button because it answers a question the button can't: why it is blank.
  // Named rather than inlined so the self-check can hold it to its one rule.
  function wifiCell(h, inD, guest) {
    const ssid = String(h.wifi_ssid || "").trim();
    const pass = String(h.wifi_pass || "").trim();
    const rest = String(h.wifi || "").trim();
    // Two columns filled is the state the row was rebuilt for: the network name
    // reads, the password COPIES, and the QR is there for the phone that is not
    // in your hand. Sam's own objection is what settled that order - a code
    // on the screen you are holding cannot be scanned by the screen you are
    // holding, so copy is the control for you and the QR is what you turn round
    // and show somebody else.
    if (ssid || pass) {
      const bits = [`<span class="wifi-ssid">${esc(ssid || "network not named")}</span>`];
      if (pass) bits.push(`<button class="wifi-act" data-wificopy="${esc(pass)}">copy password</button>`);
      if (ssid) bits.push(`<button class="wifi-act" data-wifiqr="${esc(String(h.id))}">show QR</button>`);
      if (rest) bits.push(`<span class="wifi-rest">${esc(rest)}</span>`);
      return `<span class="wifi-row">${bits.join("")}</span>`;
    }
    // A row still holding the old one-line sentence prints it unchanged. Nothing
    // guesses which half is the password: a wrong string handed over at a door is
    // worse than a sentence you read yourself.
    if (rest) return `<span class="wifi-row"><span class="wifi-rest wifi-rest-only">${esc(rest)}</span>`
      + (guest ? "" : `<button class="wifi-act" data-addfield="housing:${esc(String(h.id))}:wifi_ssid,wifi_pass,wifi">split into network + password</button>`)
      + `</span>`;
    const wait = /airbnb\./i.test(h.url || "") && inD != null && inD > 2;
    if (guest) return `<span class="hub-pending">${wait
      ? "not released yet — Airbnb posts it 48 hours before check-in" : "not filled in yet"}</span>`;
    return `<button class="hub-pending-add stay-add" data-addfield="housing:${esc(String(h.id))}:wifi_ssid,wifi_pass,wifi">+ add wifi</button>${
      wait ? `<span class="hub-pending">Airbnb posts it 48 hours before check-in</span>` : ""}`;
  }

  // The code is what somebody opens this panel for, and it was arriving as the
  // third word of a sentence at 14px - read one-handed, at arm's length, at a
  // keypad, in the dark. So it comes out of the prose and goes up in display
  // type, and what is left of the line (which keypad, how you lock up on the way
  // out) sits under it as the context it always was.
  //
  // The check-in window goes with it. "Early check-in 2:00 PM confirmed" is the
  // check-in row directly above word for word, and a time printed twice on one
  // screen is a time you read twice to check the two agree. The stored field is
  // untouched - the edit form still shows every line exactly as it was typed.
  //
  // ponytail: both the code and the window are pattern-matched out of free text,
  //   clause by clause on the `·` these lines are actually written with, so a
  //   phrasing neither pattern knows falls through and prints unchanged. Nothing
  //   is dropped because half a match fired.
  const DOOR_CODE = /\bcodes?\b\s*(?:is|:|-|—|=)?\s*([0-9]{3,12}[#*]?)/i;
  const DOOR_WINDOW = /check[\s-]?(?:in|out)/i;
  const DOOR_CLOCK = /\b\d{1,2}:\d{2}\b|\b\d{1,2}\s*[ap]\.?m\.?\b/i;
  function doorCell(h) {
    const raw = lines(h.check_in_method);
    let code = "";
    const rest = [];
    raw.forEach((l) => {
      const keep = l.split("·").map((s) => s.trim()).filter(Boolean).filter((p) => {
        if (!code) {
          const m = DOOR_CODE.exec(p);
          // The words that introduce the code leave with it: the clause is the
          // unit, so "Door code 4736" goes whole and the keypad it belongs to
          // stays. Only the first code on the field is lifted - a second number
          // further down is a different lock, not a second copy of this one.
          if (m) { code = m[1]; return false; }
        }
        return !(DOOR_WINDOW.test(p) && DOOR_CLOCK.test(p));
      });
      if (keep.length) rest.push(keep.join(" · "));
    });
    // No code found is a front desk, a lockbox described in words, a phrasing
    // the pattern has not met. It prints as it always did.
    if (!code) return (rest.length ? rest : raw).map(esc).join("<br>");
    return `<span class="door-row"><span class="door-code">${esc(code)}</span>${
      rest.length ? `<span class="door-rest">${rest.map(esc).join("<br>")}</span>` : ""}</span>`;
  }

  // One photo per line, `url` or `url<TAB>caption` - see migration 017. The
  // caption is the host's own ("Bedroom 3 with 2 queen beds"), present on about
  // one photo in eight, so it is drawn when it exists and nothing stands in for
  // it when it doesn't. A line that isn't an http(s) URL is dropped rather than
  // rendered as a broken image.
  const photoItems = (v) => lines(v).map((l) => {
    const [u, c] = l.split("\t");
    return { u: (u || "").trim(), c: (c || "").trim() };
  }).filter((p) => /^https?:\/\//.test(p.u));
  // A flight row's notes are free prose, and on these rows the prose carries the
  // fare: "Paid CA$267.60 = CA$194.10 original + CA$75.00 change fee". Hiding the
  // money FIELDS from a guest while rendering that verbatim hides nothing, which
  // is what the public mirror was still doing after the fact grid went quiet.
  // Whole lines go, not the amounts inside them - half a sentence with a hole in
  // it reads as damage, and the rest of the line is usually about the money too.
  // ponytail: pattern-matched, so it is best-effort on free text. It catches a
  //   currency symbol, a decimal amount, a comma-grouped points figure and a card
  //   fragment; a fare written out in words would survive. The structured fields
  //   are the guarantee - this is the backstop on the one field that has no shape.
  const MONEYISH = /[$£€¥]|\b\d[\d,]*\.\d{2}\b|\b[\d,]{4,}\s*(?:pts|points|UR|miles|Aeroplan)\b|(?:card|•{2,}|\*{2,})\s*[•*\d]{4}/i;
  const guestSafeNotes = (v) => isGuest() ? lines(v).filter((l) => !MONEYISH.test(l)).join("\n") : v;
  // A note line is written `Label: value`, so render it as one: the label reads as
  // a key and the value carries the weight, which is the difference between a
  // stack of facts you scan and a paragraph you have to read. A line without a
  // label (a house rule, a checkout chore) renders exactly as before.
  const KEYED = /^([^:]{1,22}):\s+(\S.*)$/;
  // A note line can carry a URL of its own - the host's guidebook, a booking page -
  // and a link you have to select and paste is not a link. esc() runs FIRST and the
  // anchor is built out of the escaped text, so the only markup in the result is the
  // markup this line put there. The trailing class drops the sentence punctuation a
  // URL at the end of a line picks up. The chip shows only the host: a whole URL in
  // a capsule wrapped into a slab mid-sentence (hub-text-act rule, 2026-10-14).
  const URLISH = /\bhttps?:\/\/[^\s<]+[^\s<.,;:!?)\]]/g;
  const noteText = (s) => esc(s).replace(URLISH, (u) =>
    `<a class="hub-link-chip llink" href="${u}" target="_blank" rel="noopener">${u.replace(/^https?:\/\/(?:www\.)?([^/]+).*$/, "$1")} \u2197</a>`);
  const stayList = (v, cls) => {
    const L = lines(v);
    return L.length ? `<ul class="hub-col-list${cls ? ` ${cls}` : ""}">${L.map((x) => {
      const m = KEYED.exec(x);
      return `<li>${m ? `<span class="hub-col-list-k">${esc(m[1])}</span><span class="hub-col-list-v">${noteText(m[2])}</span>`
        : noteText(x)}</li>`;
    }).join("")}</ul>` : "";
  };
  // A `# Heading` block carries Airbnb's own section name, read off the amenity
  // modal's headings rather than guessed at by keyword - see migration 010. A list
  // stored before the sections existed has none, and falls into one unnamed group.
  function amenityGroups(h) {
    const out = [];
    amenityItems(h).forEach((a) => {
      if (a.l.indexOf("# ") === 0) { out.push({ k: a.l.slice(2).trim(), items: [] }); return; }
      if (!out.length) out.push({ k: "", items: [] });
      out[out.length - 1].items.push(a);
    });
    return out.filter((g) => g.items.length);
  }


Object.assign(U, { flightLegBlock, ticketedAs, viewerFlightMissing, crewFlightsHTML, ownFlightsHTML, flightPanel,
  listHousing, amenityItems, daysAway, countdown, stayBlock, stayFacts, lines, wifiCell, doorCell, photoItems,
  guestSafeNotes, stayList, amenityGroups });
})();
