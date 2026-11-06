/* hub · trips page, daymap (2026-10-13): React port of trips.js lines 3439-4274 (day map, itinerary model and
   timeline, bookings helpers, all-in pricing). Near-verbatim: plain functions that build HTML strings and Leaflet
   layers, written onto TripsUI. The drawing state lives on U.mut (dayMap, dayMapKey); renderDayMap owns the
   dayMap assignment. Async functions are promise chains (no async/await in the trips JSX files). */
(() => {
const U = window.TripsUI;
const { $, esc, setHTML, state, statusLabel, haversine, rowCost, T, TC, FIRM } = U;
const { ghostStops, trailPath, addRecenter, renderContext, routeText, groceryRun } =
  U.fwd("ghostStops", "trailPath", "addRecenter", "renderContext", "routeText", "groceryRun");

  // ── DAY MAP ──────────────────────────────────────────────────────────────
  // day + pin signature of whatever the map is currently showing; see listDay (U.mut.dayMapKey)
  const routeCache = {};

  // opts: { route: false } for a set of places that isn't a sequence (the housing
  // board; you stay in one of them, you don't walk between them), and emptyNote
  // for what to say when nothing has coordinates yet.
  function renderDayMap(stops, opts) {
    const o = opts || {};
    const el = $("dayMap");
    if (!el) return;
    if (U.mut.dayMap) { U.mut.dayMap.remove(); U.mut.dayMap = null; }
    const placed = stops.filter((s) => s.lat != null && s.lng != null);
    // the shortlist layer only makes sense next to something that isn't the
    // shortlist; on the activities board every pin is already an activity
    const ghosts = o.ghosts === false ? [] : ghostStops(state.day, placed);
    if (!window.L) { setHTML(el, `<div class="dayv-map-note">map unavailable — leaflet didn't load</div>`); return; }
    if (!placed.length && !ghosts.length) {
      setHTML(el, `<div class="dayv-map-note">${esc(o.emptyNote || "nothing on this day has a location yet")}</div>`);
      return;
    }
    setHTML(el, "");
    const map = L.map(el, { scrollWheelZoom: true, attributionControl: false });
    U.mut.dayMap = map;
    hubBasemap(map);

    // markTrail decides this for the day map; the boards hand over plain stops
    // and fall back to "timed means sequenced".
    const onTrail = (p) => (p.trail == null ? p.timed : p.trail);
    const pts = trailPath(placed.filter(onTrail).map((p) => [p.lat, p.lng, !!p.air, !!p.back]), o.bookend);
    // Frame the day's own stops; timed or not, one or twenty. Ghosts only get a
    // say when the day has nothing of its own, so a single shortlisted spot
    // across town can't zoom the actual day out of view.
    const frame = placed.length ? placed.map((p) => [p.lat, p.lng]) : ghosts.map((g) => [g.lat, g.lng]);
    // The floor of the scope lock is the day's GROUND events. One 5:15p departure
    // used to blow the frame out to 1,600 miles and shrink the day itself to a
    // pixel, so the airports are out of the fit and live past the floor instead.
    // A day that never leaves the ground has no second frame and no way past it.
    const ground = placed.filter((p) => p.kind !== "flight").map((p) => [p.lat, p.lng]);
    const floorPts = ground.length ? ground : frame;
    const hasWide = ground.length > 0 && ground.length < frame.length;
    // One point has no extent to fit, so fitBounds runs to max zoom and lands you
    // on an unrecognisable patch of street. Back off far enough to show where it
    // actually is; the question a single pin is answering.
    // Framed before the markers are drawn, because the fan-out below measures in
    // screen pixels and needs the final zoom to convert them.
    const maxZ = floorPts.length > 1 ? 15 : 12;
    const floorB = L.latLngBounds(floorPts).pad(0.15);
    map.fitBounds(floorB, { maxZoom: maxZ });
    // The same frame the map opened on, on a button; two drags into a twelve-stop
    // day the stay is off-screen and there is no way back but a reload.
    addRecenter(map, el, () => map.fitBounds(floorB, { maxZoom: maxZ }));

    const markers = [];
    ghosts.forEach((g) => {
      markers.push({ item: g, marker: L.marker([g.lat, g.lng], { icon: pinIcon("", "ghost"), zIndexOffset: -500 })
        .addTo(map).bindTooltip(`${g.title} · ${statusLabel(g.status)}`) });
    });
    // Only the trail carries a number; a sequence you can follow. An untimed
    // stop is on the day but not at a point in it, and a crew member's flight is
    // not your movement at all, so numbering either would invent an order that
    // isn't there.
    let n = 0;
    placed.forEach((p) => {
      const label = onTrail(p) ? String(++n) : "";
      p._num = label;   // the wide frame collapses a run of these into one "1–5" mark
      markers.push({ item: p, marker: L.marker([p.lat, p.lng], { icon: stopIcon(p, label) })
        .addTo(map).bindTooltip(`${p.time} · ${p.title}`)
        .on("click", () => { state.selId = /^\d+$/.test(p.sel) ? Number(p.sel) : p.sel; renderContext(); }) });
    });

    // Overlap is a function of zoom, so it has to be answered at every zoom , 
    // not once at the opening bounds and then frozen into the coordinates.
    spread(map, markers);
    map.on("zoomend", () => spread(map, markers));
    // Landing in a new frame changes what the marks are (two thirds the size, and
    // the whole day collapsed to one), so the lock repaints them itself; zoomend
    // has already fired by the time the class lands.
    scopeLock(map, floorB, hasWide ? L.latLngBounds(frame) : null, maxZ, () => spread(map, markers));

    if (o.route !== false && pts.length > 1) drawRoute(map, pts);   // one stop is a place, not a route
  }

  // Two venues in the same block draw perfectly underneath one another and the
  // map reads as if one of them doesn't exist. Nudging a small group apart fixes
  // that. Doing the same to a big one does not: a trip spanning Red Rocks to
  // Rocky Mountain opens at a zoom where the whole Denver metro is narrower than
  // one pin, and ringing eighteen pins there drew a 68px circle that threw
  // downtown bars onto Boulder and Longmont. So past FAN_MAX the group collapses
  // to a single counted pin instead; the honest reading of "more here than fits,
  // zoom in". Both answers depend on the zoom, so both are recomputed on every
  // zoom rather than baked into the coordinates once at the opening bounds.
  const PIN_PX = 22;         // the pin box; closer than this and one hides the other
  const CHIP_PX = 96;        // a labelled chip is wide, so chips collide long before dots do
  const FAN_MAX = 6;         // past this the ring is wider than the thing it describes

  // Grouped by how close they land on screen, not by equal coordinates: two spots
  // 8m apart are separate rows in the database and the same dot on a city-wide map.
  // ponytail: O(n²) greedy pass, fine at ~100 pins; grid-bucket it if a trip ever has thousands.
  function clusterByPixel(map, markers, radius) {
    const r = radius || PIN_PX;
    const groups = [];
    markers.forEach((m) => {
      const c = map.latLngToContainerPoint([m.item.lat, m.item.lng]);
      const g = groups.find((q) => Math.hypot(q.c.x - c.x, q.c.y - c.y) < r);
      if (g) g.members.push(m); else groups.push({ c, members: [m] });
    });
    return groups;
  }

  // A C1 mark is a dot the label hangs off, so the two halves collide on different
  // scales and get answered separately: the dot decides what collapses, the chip
  // decides what climbs. The dot itself never moves; that is the whole contract.
  const markOf = (m) => { const el = m.marker.getElement(); return el ? el.querySelector(".mstop") : null; };

  function spread(map, markers) {
    // Groups reshuffle on every zoom, so last pass's badges are cleared wholesale
    // rather than tracked; a badge stranded on a marker that has since joined a
    // different group has no owner left to remove it.
    markers.forEach((m) => { if (m.badge) { map.removeLayer(m.badge); m.badge = null; } });
    const wide = map.getContainer().classList.contains("is-wide");
    const live = [];
    clusterByPixel(map, markers, PIN_PX).forEach((g) => {
      const alone = g.members.length === 1;
      // In the wide frame the ground day and the airport it leaves from land
      // inside a few pixels: that is one place and it gets one mark, whatever
      // FAN_MAX says. Fanning five chips across a continent reads as nothing.
      const fan = !alone && !wide && g.members.length <= FAN_MAX;
      const at = fan ? relax(g.members.map((m) => map.latLngToContainerPoint([m.item.lat, m.item.lng]))) : null;
      g.members.forEach((m, i) => {
        // Only a mark with no chip may be nudged off its point; a shortlist ghost
        // has no label to climb with, and two of them on one coordinate are one
        // dot. Anything carrying a chip stays put and lifts its label instead.
        if (fan && !markOf(m)) m.marker.setLatLng(map.containerPointToLatLng(at[i]));
        else m.marker.setLatLng([m.item.lat, m.item.lng]);
        const shown = alone || fan;
        m.marker.setOpacity(shown ? 1 : 0);
        // An invisible marker still answers the mouse, so a hidden member would
        // pop its own tooltip from under the badge covering it.
        const el = m.marker.getElement();
        if (el) el.style.pointerEvents = shown ? "" : "none";
        if (shown) live.push(m);
      });
      if (alone || fan) return;
      // Collapsed. At city zoom that is "more here than fits, zoom in" and a count
      // is the honest answer. In the wide frame it is the day itself, so it says
      // so; anchored on the airport, because that is where the leg terminates.
      const air = g.members.find((m) => m.item.kind === "flight");
      const anchor = wide && air ? [air.item.lat, air.item.lng] : map.containerPointToLatLng(g.c);
      const merged = wide ? mergedMark(g.members) : null;
      const badge = L.marker(anchor, {
        icon: merged ? stopIcon(merged.stop, merged.num) : pinIcon(String(g.members.length), "many"),
        zIndexOffset: 500,
      }).addTo(map).bindTooltip(merged
        ? g.members.map((m) => `${m.item.time} · ${m.item.title}`).join("<br>")
        : `${g.members.length} places here — zoom in`);
      g.members[0].badge = badge;
      const ll = L.latLng(anchor);
      if (merged) live.push({ marker: badge, item: { lat: ll.lat, lng: ll.lng } });
    });
    liftChips(map, live.map((m) => ({ marker: m.marker, lat: m.item.lat, lng: m.item.lng })));
  }

  // The whole Denver end of a flight day; four ground stops and the airport they
  // leave from; is one place at 1,600 miles wide. Drawing it as five put chips on
  // the same pixel with their leaders crossing through each other.
  function mergedMark(members) {
    const ns = members.map((m) => m.item._num).filter(Boolean).map(Number).sort((a, b) => a - b);
    const air = members.find((m) => m.item.kind === "flight");
    const num = !ns.length ? "" : ns.length > 1 ? `${ns[0]}–${ns[ns.length - 1]}` : String(ns[0]);
    return { num, stop: { kind: air ? "flight" : "act", time: "", title: air ? air.item.title : "the day" } };
  }

  // Chips are wide where dots are not, so they cluster on their own scale. The dot
  // stays on its coordinate and the label climbs: --lift raises the chip and
  // stretches its leader to match, so a crowded block stacks top to bottom without
  // any mark lying about where it stands.
  const CHIP_H = 22;         // a chip is ~19px tall; the rest is the gap between two
  /* `marks` is `[{ marker, lat, lng }]`; the marker to lift and where it stands.
     It used to read the day map's own `{ item: {lat, lng} }` rows, which is what
     kept the ride map on a hand-tuned stagger of magic lift numbers instead: two
     alternating heights that separated the pairs someone had thought of and left
     "G · Bergen St" drawn through the pickup chip beside it. One ladder, both maps
     (Sam 2026-08-31 on the transit pins); the day map shims its rows at the
     call site. */
  function liftChips(map, live) {
    const w = map.getSize().x;
    // Clustering the chips and laddering each group independently is what put two
    // labels on one row: `q.c` is the group's FIRST member, never a running centre,
    // so a run of marks spread across the frame split into groups whose ladders
    // then interleaved. A chip's box is the only thing that decides where a chip
    // can sit, so place them one at a time against the boxes already placed , 
    // south to north, so the ladder keeps the order the dots are already in and no
    // leader crosses the dot above it.
    const at = live.map((m) => map.latLngToContainerPoint([m.lat, m.lng]));
    const placed = [];
    live.map((_m, i) => i).sort((a, b) => at[b].y - at[a].y).forEach((i) => {
      const mark = markOf(live[i]);
      if (!mark) return;
      // A chip centred on a dot near the frame edge hangs half of itself off the
      // map, so near an edge it anchors to the dot instead of centring on it.
      const chip = mark.querySelector(".mchip");
      const edgeL = at[i].x < 90, edgeR = at[i].x > w - 90;
      if (chip) { chip.classList.toggle("at-l", edgeL); chip.classList.toggle("at-r", edgeR); }
      const cw = (chip?.offsetWidth) || CHIP_PX;
      const l = edgeL ? at[i].x - 4 : edgeR ? at[i].x + 4 - cw : at[i].x - cw / 2;
      const r = l + cw;
      // Climb a step at a time until the box clears everything already down. A tall
      // stack runs out of sky: a chip that climbs past the frame is drawn in half,
      // and dropping it to the empty bottom of the map parks a label 300px from the
      // dot it names, which is worse than not drawing it. So a chip with no free row
      // left above its dot is not drawn at all; the dot stays, its tooltip still
      // names it, and one click of zoom frees the rows. Same answer the collapsed
      // "N places here" badge gives: more here than fits.
      // ponytail: linear scan of the placed list. n is the marks in one frame.
      const bot = at[i].y - 15;
      const free = (lf) => {
        const b = bot - lf, t = b - CHIP_H;
        return t >= 0 && !placed.some((q) => l < q.r && r > q.l && t < q.b && b > q.t);
      };
      let lift = 0;
      while (lift <= bot - CHIP_H && !free(lift)) lift += CHIP_H;
      if (chip) chip.style.visibility = free(lift) ? "" : "hidden";
      if (!free(lift)) return;
      placed.push({ l, r, t: bot - lift - CHIP_H, b: bot - lift });
      mark.style.setProperty("--lift", `${lift}px`);
    });
  }

  // How the overlapping members of a group get separated. The ring this replaced
  // threw every one of them onto an arbitrary circle around the group centre, so
  // two airports eight miles apart drew as two pins on a vertical axis with the
  // route line running between two places neither pin was standing on. Push each
  // pin directly away from the ones it overlaps instead, and only by the
  // shortfall; the smallest move that still shows them all. Coincident points
  // have no axis of their own, so they split on a stable per-index bearing.
  // ponytail: 12 relaxation passes over an O(n²) inner loop, and n <= FAN_MAX.
  function relax(pts) {
    for (let pass = 0; pass < 12; pass++) {
      let moved = false;
      for (let i = 0; i < pts.length; i++) {
        for (let j = i + 1; j < pts.length; j++) {
          let dx = pts[j].x - pts[i].x, dy = pts[j].y - pts[i].y;
          let d = Math.hypot(dx, dy);
          if (d >= PIN_PX) continue;
          if (d < 0.5) { dx = Math.cos(i * 2.4); dy = Math.sin(i * 2.4); d = 1; }
          const k = (PIN_PX - d) / (2 * d);
          pts[i].x -= dx * k; pts[i].y -= dy * k;
          pts[j].x += dx * k; pts[j].y += dy * k;
          moved = true;
        }
      }
      if (!moved) break;
    }
    return pts;
  }

  function pinIcon(label, kind, anytime) {
    return L.divIcon({
      className: "",
      html: `<span class="mpin mpin-${kind}${anytime ? " mpin-anytime" : ""}">${esc(label)}</span>`,
      iconSize: [22, 22], iconAnchor: [11, 11],
    });
  }

  // A flight stop is titled "DEN · Flight to NYC"; on a chip the code is the part
  // that identifies the place, and the rest is the leg it belongs to.
  const markName = (p) => (p.kind === "flight" ? String(p.title || "").split(" · ")[0] : (p.title || ""));

  // The day's mark: a 10px dot welded to the coordinate with the label floating
  // above it on a leader. Order, clock and place all ride the chip, so the day
  // reads straight off the map with no hovering; and when two collide the chip
  // is what climbs, never the dot.
  // display:block on .mstop is load-bearing: width and height do not apply to a
  // non-replaced inline element, and a bare span silently rendered a 10px dot at
  // 4px because the absolute inset resolved against the text box instead.
  function stopIcon(p, num) {
    const chip = `<span class="mchip">${num ? `<b>${esc(String(num))}</b>` : ""}` +
      `${esc(p.time || "")}<em>${esc(markName(p))}</em></span><span class="mlead"></span>`;
    return L.divIcon({
      className: "",
      html: `<span class="mstop mstop-${p.kind || "act"}${num ? "" : " is-anytime"}" style="--lift:0px">` +
        `${chip}<span class="mdot"></span></span>`,
      iconSize: [10, 10], iconAnchor: [5, 5],
    });
  }

  // His spec, verbatim: "lock all itinerary maps to the scope of the itinerary
  // events. on flight days, lock it to the events without the flights, but on the
  // last click of zoom out, snap to see it as if scope includes all airports."
  // So there are exactly two frames and nothing between them. The default IS the
  // floor. Zoom in as far as you like; zooming out stops there. One more click and
  // the frame opens to include the airports; one click back in and it comes home.
  // The state this kills; the day one pixel wide with the country around it; is
  // simply not reachable any more.
  const BLOOM = 1.15;        // seconds; the frame change is a move, not a cut
  function scopeLock(map, floorB, wideB, maxZ, onLand) {
    const st = { wide: false, zFloor: map.getZoom(), zWide: 0, busy: false };
    // No airports to reveal: the floor is the whole story and also the hard stop.
    if (!wideB) { map.setMinZoom(st.zFloor); return st; }
    // one spare click of headroom below the floor; that click is the trigger
    map.setMinZoom(st.zFloor - 1);
    const land = (wide) => {
      if (wide) { st.zWide = map.getZoom(); map.setMinZoom(st.zWide); }
      else { st.zFloor = map.getZoom(); map.setMinZoom(st.zFloor - 1); }
      map.getContainer().classList.toggle("is-wide", wide);
      st.busy = false;
      onLand();
    };
    st.go = (wide) => {
      st.wide = wide; st.busy = true;
      map.setMinZoom(0);
      // The bloom. flyToBounds moves zoom and centre along one eased curve, so the
      // frame opens outward instead of cutting to the new one. easeLinearity under
      // Leaflet's 0.25 default is the weight: it leaves slowly and lands slowly.
      map.flyToBounds(wide ? wideB : floorB, {
        padding: wide ? [46, 30] : [0, 0], maxZoom: wide ? undefined : maxZ,
        duration: BLOOM, easeLinearity: 0.1,
      });
      // ponytail: land on a timer, not on once("moveend"). The wheel event that
      // triggered this fires its OWN moveend a beat later and the listener catches
      // that one instead of the flight's, which set minZoom from a mid-flight zoom
      // and clamped the bloom halfway open. The duration is known, so use it.
      setTimeout(() => land(wide), BLOOM * 1000 + 120);
    };
    map.on("zoomend", () => {
      if (st.busy) return;
      const z = map.getZoom();
      if (!st.wide && z < st.zFloor) st.go(true);
      else if (st.wide && z > st.zWide) st.go(false);
    });
    return st;
  }

  // Real walking geometry from OSRM, falling back to a dashed straight line.
  // A straight line between two stops lies about the walk; it hides the river
  // you have to go around; so the fallback is drawn dashed to say so.
  // Which way you'd actually get between these stops. A day inside one
  // neighbourhood is a walk; the moment one leg runs past WALK_MI it's a drive,
  // and routing it on foot returns both the wrong geometry and a "93.9 mi on
  // foot" label that reads as a joke.
  const WALK_MI = 1.6;
  function routeMode(pts) {
    for (let i = 1; i < pts.length; i++) {
      const d = haversine(pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1]);
      if (d != null && d > WALK_MI) return { profile: "driving", label: "mi driving" };
    }
    return { profile: "foot", label: "mi on foot" };
  }

  // A day that flies is not one continuous route. Handing the whole trail to
  // OSRM drew Newark→Dulles→Columbus as a road trip down I-95 and quoted the
  // driving miles for it, which is not what happened; so the trail is cut at
  // every flown leg: ground runs get real road geometry, air legs get the
  // straight line a flight actually is, and only the ground miles are totalled.
  function splitRuns(pts) {
    const runs = [];
    for (let i = 1; i < pts.length; i++) {
      const air = !!pts[i][2];
      const last = runs[runs.length - 1];
      if (last && !last.air && !air) last.pts.push(pts[i]);
      else runs.push({ air, back: !!pts[i][3], pts: [pts[i - 1], pts[i]] });
    }
    return runs;
  }

  function drawRoute(map, pts) {
    let miles = 0, label = "";
    const runs = splitRuns(pts);
    const finish = () => {
      if (!U.mut.dayMap || U.mut.dayMap !== map || !miles) return;
      const badge = document.createElement("div");
      badge.className = "dayv-map-dist";
      badge.textContent = `${(miles / 1609.34).toFixed(1)} ${label}`;
      map.getContainer().appendChild(badge);
    };
    // sequential: each ground run waits for the one before it (the awaiting loop of the plain page)
    const step = (i) => {
      if (i >= runs.length) { finish(); return Promise.resolve(); }
      const run = runs[i];
      if (!U.mut.dayMap || U.mut.dayMap !== map) return Promise.resolve();   // day switched while the route was in flight
      if (run.air) { drawAir(map, run); return step(i + 1); }
      return drawGround(map, run.pts).then((leg) => {
        if (leg) { miles += leg.dist; label = leg.label === "mi driving" ? leg.label : (label || leg.label); }
        return step(i + 1);
      });
    };
    return step(0);
  }

  // The flown leg. A quadratic bend through a control point offset perpendicular
  // to the leg, so the sign falls out of the direction of travel; westbound bows
  // one way and eastbound the other, and a round trip opens into a lens instead of
  // drawing one line twice.
  const ARC_BEND = 0.10, ARC_N = 64, STITCH_EVERY = 8;
  function arcPts(a, b, bend) {
    const cx = (a[0] + b[0]) / 2 - (b[1] - a[1]) * bend;
    const cy = (a[1] + b[1]) / 2 + (b[0] - a[0]) * bend;
    const out = [];
    for (let i = 0; i <= ARC_N; i++) {
      const t = i / ARC_N, u = 1 - t;
      out.push([u * u * a[0] + 2 * u * t * cx + t * t * b[0],
                u * u * a[1] + 2 * u * t * cy + t * t * b[1]]);
    }
    return out;
  }
  function screenAngle(map, pts, i) {
    const p1 = map.latLngToContainerPoint(pts[i]), p2 = map.latLngToContainerPoint(pts[i + 1]);
    return Math.atan2(p2.y - p1.y, p2.x - p1.x) * 180 / Math.PI;
  }
  // The heading mark shrinks and repeats along the leg instead of sitting once at
  // its midpoint; small enough that the row reads as a textured stroke rather
  // than a queue of arrows. The line stays under it, knocked back: the line
  // carries the route, the stitch carries the direction, one job each.
  function drawAir(map, run) {
    const a = run.pts[0], b = run.pts[run.pts.length - 1];
    const pts = arcPts(a, b, ARC_BEND);
    L.polyline(pts, { className: `mroute is-air${run.back ? " is-back" : ""}`,
      weight: 1.5, opacity: 0.5, dashArray: "1 6" }).addTo(map);
    // Mercator's scale is uniform, so the screen angle between two points does not
    // change with zoom or pan; computed once here, unlike the marks, which really
    // do have to be re-answered on every zoomend.
    for (let i = STITCH_EVERY; i < ARC_N; i += STITCH_EVERY) {
      L.marker(pts[i], { icon: L.divIcon({
        className: "",
        html: `<span class="matpoint"><span class="mstitch${run.back ? " is-back" : ""}"` +
          ` style="transform:rotate(${screenAngle(map, pts, i).toFixed(1)}deg)"></span></span>`,
        iconSize: [0, 0], iconAnchor: [0, 0],
      }) }).addTo(map);
    }
  }

  /* The road between a list of points, measured. One function and one cache for
     every map on the board; the day map asks it for the day's ground runs, the
     day-of ride card asks it for the run to the terminal, and two maps showing the
     same drive on the same page ask once.

     `dur` is OSRM's own seconds for the route. It is the only measured travel time
     anywhere in this file: everything else is driveMin(), a straight line times a
     road factor, which is why the leave-by clock reads better once this lands.

     null is a normal answer; no network, a rate limit, a point OSRM cannot snap to
     a road; and every caller falls back to the straight line rather than failing. */
  function osrmRoute(profile, pts) {
    const key = `${profile}|${pts.map((p) => `${p[0].toFixed(4)},${p[1].toFixed(4)}`).join(";")}`;
    if (routeCache[key] !== undefined) return Promise.resolve(routeCache[key]);
    const coords = pts.map((p) => `${p[1]},${p[0]}`).join(";");
    return fetch(`https://router.project-osrm.org/route/v1/${profile}/${coords}?overview=full&geometries=geojson`)
      .then((r) => r.json())
      .then((j) => {
        const rt = (j.routes || [])[0];
        return rt ? { line: rt.geometry.coordinates.map((c) => [c[1], c[0]]), dist: rt.distance, dur: rt.duration } : null;
      })
      .catch(() => null)
      .then((geo) => { routeCache[key] = geo; return geo; });
  }

  function drawGround(map, pts) {
    const mode = routeMode(pts);
    return osrmRoute(mode.profile, pts).then((geo) => {
    if (!U.mut.dayMap || U.mut.dayMap !== map) return null;
    const style = geo
      ? { className: "mroute", weight: 4, opacity: 0.9 }
      : { className: "mroute is-straight", weight: 3, opacity: 0.7, dashArray: "5 6" };
    L.polyline(geo ? geo.line : pts, style).addTo(map);
    return geo ? { dist: geo.dist, label: mode.label } : null;
    });
  }

  // Build [{ day, blocks:[{start,end,...}], tray:[...] }] for the whole trip.
  function itineraryModel(days) {
    const t = state.trip;
    const model = days.map((d) => ({ day: d, blocks: [], tray: [] }));
    const idx = {};
    days.forEach((d, i) => { (idx[d] = i); });
    // date+time in, column out. The axis is midnight, so an item's position down
    // its column is just its clock time; no shift, and the column is always the
    // date the item actually carries.
    const put = (date, item) => {
      // a stray date outside the trip: clamp to the nearest column and keep the
      // true date in the label
      let i = idx[date];
      if (i == null) {
        i = date < days[0] ? 0 : days.length - 1;
        item.off = date;
      }
      item.pos = item.start;
      // An instant is a timed item with no duration; a departure, a check-in. It
      // carries end === start, which is the row saying "zero minutes long" out loud;
      // a NULL end means the duration is merely unknown and still draws as a guess.
      // Every kind of row funnels through put(), so this is the only place that has
      // to know, and no caller can forget to set it.
      item.inst = item.start != null && item.end === item.start;
      const bucket = model[i];
      if (item.start == null) bucket.tray.push(item); else bucket.blocks.push(item);
    };

    (t.activities || []).filter((a) => a.status === "scheduled" && a.scheduled_date).forEach((a) => {
      const start = T.parseClock(a.scheduled_time);
      const end = T.parseClock(a.scheduled_time_end);
      put(a.scheduled_date, {
        sel: String(a.id), kind: "act", title: a.name,
        sub: (a.location || "").split(",")[0],
        start, end, open: start != null && end == null,
      });
    });

    const firm = (r) => FIRM.indexOf(r.status) >= 0;
    (t.flights || []).filter(firm).forEach((f) => {
      const dep = T.parseStamp(f.departure_time, t.start_date);
      const arr = T.parseStamp(f.arrival_time, t.start_date);
      // The whole set here, his rows and the crew's; the point of the calendar is
      // seeing that Akshay lands twelve hours after the 6:30am group. A crew leg
      // says whose it is; an unnamed one is his own and needs no label.
      const who = (f.passenger || "").trim();
      const title = `${who ? `${who} · ` : ""}${routeText(f.from_airport, f.to_airport)}`;
      addLogi(put, days, idx, dep, arr, {
        sel: `flights:${f.id}`, kind: "flight", title,
        sub: [f.airline, f.flight_num].filter(Boolean).join(" "),
        raw: f.departure_time,
        // Day 1 and day 5 both draw "a flight", and on the calendar the two ends of
        // the trip were the same hatched slab; you had to read the airport codes to
        // tell leaving from coming home. The return leg carries its own colour.
        back: (f.direction || "outbound") === "return",
      });
    });
    (t.housing || []).filter(firm).forEach((h) => {
      const ci = T.parseStamp(h.check_in, t.start_date);
      const co = T.parseStamp(h.check_out, t.start_date);
      const name = h.name || h.address || "stay";
      [[ci, "check in"], [co, "check out"]].forEach(([p, what], k) => {
        addLogi(put, days, idx, p, stayHour(p), {
          sel: `housing:${h.id}`, kind: "stay", title: name, sub: what,
          raw: k ? h.check_out : h.check_in,
        });
      });
    });
    (t.transportation || []).filter(firm).forEach((x) => {
      const p = x.scheduled_date
        ? { date: x.scheduled_date, minutes: T.parseClock(x.scheduled_time) }
        : T.parseStamp(x.departure, t.start_date);
      addLogi(put, days, idx, p, T.parseStamp(x.arrival, t.start_date), {
        sel: `transportation:${x.id}`, kind: "move",
        title: x.description || x.type || "transport", sub: x.type || "",
        raw: x.scheduled_date || x.departure,
      });
    });

    // The shopping run. It is the one block on this calendar that no table holds a
    // row for; it is derived from the two clocks either side of it (groceryRun),
    // which is why it can appear the moment a stay is booked and move itself when
    // the flight changes. Nothing to schedule by hand and nothing to go stale.
    // Placed last so it lanes against everything already on the day.
    const run = groceryRun(t);
    if (run.side && run.dateISO && run.start != null) {
      const rows = t.grocery || [];
      const left = rows.filter((g) => !Number(g.checked)).length;
      put(run.dateISO, {
        sel: "grocery", kind: "shop", title: "grocery run",
        // an empty list is not a finished one; "list is done" against nothing at
        // all reads as a shop you already did
        sub: !rows.length ? "nothing on it yet" : left ? `${left} to get` : "list is done",
        start: run.start, end: run.end,
      });
    }

    model.forEach((d) => {
      d.blocks.sort((a, b) => a.pos - b.pos);
      lanes(d.blocks);
      instantLabels(d.blocks);
    });
    return model;
  }

  // A check-in is a moment, and now it is drawn as one. It used to be padded out to
  // a half-hour block so the text would fit, which put a 3pm appointment on the axis
  // that nobody has. Both ends of a stay now end where they start, and the axis draws
  // them as rules. A stamp with no clock gets no block at all and stays a tray chip.
  const stayHour = (p) => (p && p.minutes != null ? { date: p.date, minutes: p.minutes } : null);

  // A logistics row becomes a block when its stamp parsed to a time, a tray chip
  // when it only gave a date, and a day-1 tray chip labelled with its raw string
  // when it parsed to nothing at all; never silently dropped.
  function addLogi(put, days, _idx, from, to, base) {
    if (!from) {
      if (base.raw) put(days[0], Object.assign({}, base, { start: null, note: base.raw }));
      return;
    }
    const sameDay = to && to.date === from.date && to.minutes != null && from.minutes != null;
    put(from.date, Object.assign({}, base, {
      start: from.minutes,
      end: sameDay ? to.minutes : null,
      open: from.minutes != null && !sameDay,
      note: to && to.date !== from.date ? `→ ${to.date || ""}` : "",
    }));
  }

  // Side-by-side packing for overlaps: each block gets a lane and a lane count.
  function lanes(blocks) {
    const MINH = 45;   // a block is at least this many minutes tall on screen
    const active = [];
    blocks.forEach((b) => {
      // An instant is drawn as a full-width rule, so it neither claims a lane nor
      // pushes a duration block into one. Half a day's blocks used to go half-width
      // because a departure and a check-in were sitting in the packer as boxes.
      if (b.inst) { b.lane = 0; b.of = 1; b.stop = b.pos; return; }
      const dur = (b.end != null && b.end !== b.start)
        ? (b.end - b.start + 1440) % 1440    // wraps past midnight cleanly
        : 60;
      b.stop = b.pos + Math.max(dur, MINH);
      while (active.length && active[0].stop <= b.pos) active.shift();
      const taken = new Set(active.map((x) => x.lane));
      let l = 0; while (taken.has(l)) l++;
      b.lane = l;
      active.push(b);
      active.sort((x, y) => x.stop - y.stop);
      const n = active.length;
      active.forEach((x) => { (x.of = Math.max(x.of || 1, n)); });
    });
    blocks.forEach((b) => { (b.of = b.of || 1); });
  }

  // A label is one 18px line. On the default 1440px axis a minute is a pixel, and on
  // the compressed 1150px axis it is 0.8 of one, so 24 minutes is the smallest gap
  // that still clears an 18px line on BOTH; hence 24 rather than 18.
  const INST_LAB_MIN = 24;
  // Instants keep their rules at the true minute no matter how many land together;
  // it is only the labels that move. A lone one sits above its own rule. A run of
  // them; four things between 5:45 and 6:30; stacks in reading order below the
  // last rule of the run, each line still carrying its own time, so the order stays
  // legible and no string is ever cut in half to make room.
  function instantLabels(blocks) {
    const ins = blocks.filter((b) => b.inst);       // already in time order
    for (let i = 0; i < ins.length; ) {
      let j = i + 1;
      while (j < ins.length && ins[j].pos - ins[j - 1].pos < INST_LAB_MIN) j++;
      const run = ins.slice(i, j);
      // anchor every label in the run to the SAME percent so the px stack below is
      // exact; mixing a per-label percent with a px offset is what drifts.
      const anchor = run[run.length - 1].pos;
      run.forEach((b, k) => {
        b.labPos = run.length === 1 ? b.pos : anchor;
        b.labOff = run.length === 1 ? -20 : 5 + k * 18;
      });
      i = j;
    }
  }

  const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  function dayLabel(iso) {
    const d = new Date(`${iso}T00:00:00Z`);
    return `${DOW[d.getUTCDay()]} ${d.getUTCDate()}`;
  }

  function timelineHTML(model) {
    const today = new Date();
    const todayISO = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    const nowMin = today.getHours() * 60 + today.getMinutes();
    const hours = [];
    for (let h = 0; h < 24; h++) {
      const lbl = h === 0 ? "12a" : h < 12 ? `${h}a` : h === 12 ? "12p" : `${h - 12}p`;
      hours.push(`<div class="hub-timeline-hr${h === 0 ? " is-mid" : ""}"><span>${lbl}</span></div>`);
    }
    const heads = model.map((d, i) => {
      const on = d.day === todayISO ? " is-today" : "";
      return `<div class="hub-timeline-head${on}"><span class="hub-timeline-head-d">day ${i + 1}</span><span class="hub-timeline-head-n">${esc(dayLabel(d.day))}</span></div>`;
    }).join("");
    const trays = model.map((d) => `<div class="hub-timeline-tray">${
      d.tray.length
        ? d.tray.map((it) => chipHTML(it)).join("")
        : `<span class="hub-timeline-tray-none">—</span>`
    }</div>`).join("");
    const cols = model.map((d) => {
      const marker = d.day === todayISO
        ? `<div class="hub-timeline-now" style="top:${(nowMin / 1440 * 100).toFixed(3)}%"></div>` : "";
      return `<div class="hub-timeline-col">${gridLines()}${marker}${d.blocks.map(blockHTML).join("")}</div>`;
    }).join("");
    return `<div class="hub-timeline" style="--tl-days:${model.length}">
      <div class="hub-timeline-corner"></div>
      <div class="hub-timeline-heads">${heads}</div>
      <div class="hub-timeline-tray-l">anytime</div>
      <div class="hub-timeline-trays">${trays}</div>
      <div class="hub-timeline-body">
        <div class="hub-timeline-gutter">${hours.join("")}</div>
        <div class="hub-timeline-cols">${cols}</div>
      </div>
    </div>`;
  }
  function gridLines() {
    // midnight needs no rule of its own; it IS the column edge now
    let s = "";
    for (let h = 1; h < 24; h++) {
      s += `<div class="hub-timeline-line${h % 6 === 0 ? " strong" : ""}" style="top:${(h / 24 * 100).toFixed(4)}%"></div>`;
    }
    return s;
  }
  function blockHTML(b) {
    const top = (b.pos / 1440 * 100).toFixed(3);
    if (b.inst) return instantHTML(b, top);
    const h = (Math.min(b.stop - b.pos, 1440 - b.pos) / 1440 * 100).toFixed(3);
    const w = 100 / b.of, left = w * b.lane;
    const time = T.fmtClock(b.start) + (b.end != null ? `–${T.fmtClock(b.end)}` : "");
    const sub = [b.sub, b.off ? `on ${b.off}` : "", b.note || ""].filter(Boolean).join(" · ");
    return `<div class="hub-timeline-block tl-${b.kind}${b.back ? " tl-back" : ""}${b.open ? " is-open" : ""}${b.sel === String(state.selId) ? " selected" : ""}"
      data-sel="${esc(b.sel)}" style="top:${top}%;height:${h}%;left:${left}%;width:calc(${w}% - 3px)"
      title="${esc(b.title)} · ${esc(time)}">
      <span class="hub-timeline-block-t">${esc(time)}</span>
      <span class="hub-timeline-block-n">${esc(b.title)}</span>
      ${sub ? `<span class="hub-timeline-block-s">${esc(sub)}</span>` : ""}
    </div>`;
  }
  // A rule at the exact minute, plus one full-width line of text. The line is never
  // lane-split and never clipped, which is the whole reason it is not a box: a real
  // 30-minute box on this axis is 30px trying to hold a time, a name and an address.
  // The address is not dropped, it moves to the detail rail on click.
  function instantHTML(b, top) {
    const on = b.sel === String(state.selId) ? " selected" : "";
    const time = T.fmtClock(b.start);
    const sub = [b.sub, b.off ? `on ${b.off}` : "", b.note || ""].filter(Boolean).join(" · ");
    // What moves to click is the ADDRESS, which is what an activity's sub is. A
    // logistics sub is the opposite: "check in" / "check out" is the only thing
    // telling two stay rows with the identical name apart, so it stays on the line.
    const tail = b.kind === "act" ? "" : sub;
    const cls = `tl-${b.kind}${b.back ? " tl-back" : ""}${on}`;
    const tip = `${esc(b.title)} · ${esc(time)}${sub ? ` · ${esc(sub)}` : ""}`;
    return `<div class="hub-timeline-inst ${cls}" data-sel="${esc(b.sel)}" style="top:${top}%" title="${tip}"></div>`
      + `<div class="hub-timeline-inst-l ${cls}" data-sel="${esc(b.sel)}"`
      + ` style="top:calc(${(b.labPos / 1440 * 100).toFixed(3)}% + ${b.labOff}px)" title="${tip}">`
      + `<i>${esc(time)}</i><span>${esc(b.title)}</span>`
      + `${tail ? `<em>${esc(tail)}</em>` : ""}</div>`;
  }
  function chipHTML(it) {
    const sub = [it.sub, it.note || ""].filter(Boolean).join(" · ");
    return `<span class="hub-timeline-chip tl-${it.kind}${it.back ? " tl-back" : ""}${it.sel === String(state.selId) ? " selected" : ""}" data-sel="${esc(it.sel)}"
      title="${esc(it.title)}${sub ? ` · ${esc(sub)}` : ""}">${esc(it.title)}${sub ? `<i>${esc(sub)}</i>` : ""}</span>`;
  }

  // ── BOOKINGS; the two decisions a trip turns on ─────────────────────────────
  // Flights and housing each get their own section, because they are two separate
  // choices made at different moments and nothing is gained by reading them as one
  // list. Both are built the same way, and that shape is lifted from the Denver
  // fare artifact: pick one option per decision, price it ALL-IN rather than at
  // sticker, mark why each option is interesting with badges derived from its own
  // fields, and say what the pick actually costs against the cheapest thing on the
  // board. What differs is the axis the choice turns on; for a fare it is time
  // (when you'd actually get there), for a stay it is fit (does it hold everyone).
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function dayShort(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
    return m ? `${MON[Number(m[2]) - 1]} ${Number(m[3])}` : (iso || "");
  }
  function stampShort(s) {
    const p = T.parseStamp(s, state.trip?.start_date);
    if (!p) return s ? String(s) : "—";
    return dayShort(p.date) + (p.minutes != null ? ` ${T.fmtClock(p.minutes)}` : "");
  }
  // The old cell printed the date twice; "Sep 17 10:00 → Sep 17 11:26"; which
  // buried the two numbers you read a fare for and hid the one case that
  // matters. Times lead; the date sits under them once, and only splits into
  // "May 18 → May 19" when the flight actually crosses midnight. A connection
  // says where it stops rather than pretending to be a nonstop.
  function whenCell(f) {
    const d = T.parseStamp(f.departure_time, state.trip?.start_date);
    const a = T.parseStamp(f.arrival_time, state.trip?.start_date);
    const via = f.via?.length ? `via ${f.via.join(", ")}` : "";
    const sub = (s) => s ? `<span class="lsub">${esc(s)}</span>` : "";
    if (!d) return esc(`${stampShort(f.departure_time)} → ${stampShort(f.arrival_time)}`) + sub(via);
    // no clock on the row; "Dec 20 → Dec 20" is the same day said twice
    if (d.minutes == null) {
      const span = a && a.date !== d.date ? `${dayShort(d.date)} → ${dayShort(a.date)}` : dayShort(d.date);
      return `<span class="lwhen">${esc(span)}</span>${sub(via)}`;
    }
    const arrive = a && a.minutes != null ? T.fmtClock(a.minutes) : "—";
    const day = a && a.date !== d.date ? `${dayShort(d.date)} → ${dayShort(a.date)}` : dayShort(d.date);
    return `<span class="lwhen">${esc(T.fmtClock(d.minutes))}<i>→</i>${esc(arrive)}</span>` +
      `<span class="lsub">${esc(via ? `${day} · ${via}` : day)}</span>`;
  }
  // Nights from the stay's own stamps, falling back to the trip length when
  // check-in/out are free text the parser can't reach.
  function nightsOf(h) {
    const a = T.parseStamp(h.check_in, state.trip.start_date);
    const b = T.parseStamp(h.check_out, state.trip.start_date);
    if (a && b) {
      const n = Math.round((Date.parse(`${b.date}T00:00:00Z`) - Date.parse(`${a.date}T00:00:00Z`)) / 86400000);
      if (n > 0) return n;
    }
    const d = T.dayRange(state.trip.start_date, state.trip.end_date).length - 1;
    return d > 0 ? d : null;
  }
  const perNight = (h) => { const n = nightsOf(h); const c = rowCost(h); return n && c ? c / n : null; };
  // How many heads the stay has to hold. Defaults to the crew list, because that
  // is already the answer; the control only exists for "what if the seventh comes".
  const partySize = () => TC.partyOf(state.trip || {}, state.party);
  const perPersonNight = (h) => { const p = perNight(h); return p ? p / partySize() : null; };
  // 3.5 stays 3.5, 2.0 reads as 2; a half-bath is real, a trailing .0 is noise
  const trim1 = (n) => (Math.round(n * 10) / 10).toString().replace(/\.0$/, "");

  // ── ALL-IN PRICING ──────────────────────────────────────────────────────────
  // A fare's sticker is not its price. Every airline here charges for the first
  // checked bag, and on the carriers whose cheap fare is Basic Economy a carry-on
  // costs too; so $179 on United and $179 on Delta are the same number only
  // until you pack. Checked Aug 2026: Southwest's free checked bag ended May 2025
  // and went to $45 in Apr 2026.
  // ponytail: a literal table. It moves maybe once a year, and owning a fees API
  //   for eight carriers is not worth it; correct these in place when it does.
  const AIRLINES = {
    southwest: { checked: 45, carryOn: 0,  freeChanges: true,  basicRisk: false, note: "The free checked bag ended in 2025." },
    united:    { checked: 45, carryOn: 0,  freeChanges: false, basicRisk: true,  note: "The cheap fares are usually Basic Economy: a personal item only, nothing in the overhead bin." },
    delta:     { checked: 45, carryOn: 0,  freeChanges: false, basicRisk: false, note: "Basic Economy keeps the carry-on, unlike United." },
    jetblue:   { checked: 45, carryOn: 0,  freeChanges: false, basicRisk: false, note: "Bag price moves with the date. Flies JFK, not LaGuardia." },
    american:  { checked: 40, carryOn: 0,  freeChanges: false, basicRisk: true,  note: "Basic Economy is a personal item only." },
    alaska:    { checked: 35, carryOn: 0,  freeChanges: true,  basicRisk: false, note: "Saver fares board last and can't be changed." },
    spirit:    { checked: 65, carryOn: 75, freeChanges: false, basicRisk: false, note: "Carry-on is paid on every fare. Cheapest sticker, rarely the cheapest total." },
    frontier:  { checked: 60, carryOn: 70, freeChanges: false, basicRisk: false, note: "Carry-on is paid on every fare." },
  };
  const AIRLINE_FALLBACK = { checked: 45, carryOn: 0, freeChanges: false, basicRisk: false, note: "" };
  const CARRY_IF_BASIC = 70;   // $45 bag + $25 gate handling, if the fare turns out to be Basic Economy
  function airlineFacts(name) {
    const k = String(name || "").toLowerCase();
    const hit = Object.keys(AIRLINES).filter((a) => k.indexOf(a) >= 0)[0];
    return hit ? AIRLINES[hit] : AIRLINE_FALLBACK;
  }
  // Whether the table actually knows this carrier, or handed back the fallback.
  // The fallback's $45 is a reasonable ESTIMATE and priced comparisons are welcome
  // to it; but a sentence that names the airline and quotes the figure is a claim,
  // and the day-of list was telling people Avianca charges $45 for a checked bag on
  // the strength of a default. Anywhere the number is stated rather than summed,
  // check this first.
  const knownAirline = (a) => a !== AIRLINE_FALLBACK;
  // A roundtrip row's cost covers both legs, so it carries both legs' bag fees.
  const legCount = (f) => (f.direction === "roundtrip" ? 2 : 1);
  function bagSurcharge(f) {
    const a = airlineFacts(f.airline);
    let per = 0;
    if (state.bags.checked) per += a.checked;
    if (state.bags.carry) per += a.carryOn || (a.basicRisk ? CARRY_IF_BASIC : 0);
    return per * legCount(f);
  }
  // A $0 leg is the far half of a roundtrip ticket, not a free flight; it pays
  // no bag fee of its own because the row that holds the price already did.
  const allIn = (f) => (rowCost(f) ? rowCost(f) + bagSurcharge(f) : 0);
  const cheapestBy = (rows, val) => rows.filter((r) => val(r) > 0).sort((a, b) => val(a) - val(b))[0] || null;



Object.assign(U, {
  renderDayMap, PIN_PX, spread, mergedMark, liftChips, relax, markName, splitRuns, drawRoute, ARC_BEND, arcPts,
  ARC_N, osrmRoute, itineraryModel, stayHour, addLogi, lanes, instantLabels, DOW, dayLabel, timelineHTML, MON,
  dayShort, stampShort, whenCell, nightsOf, partySize, perPersonNight, trim1, CARRY_IF_BASIC, airlineFacts,
  knownAirline, bagSurcharge, allIn, cheapestBy,
});
})();
