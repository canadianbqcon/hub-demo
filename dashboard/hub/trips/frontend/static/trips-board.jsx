/* hub · trips page, board (2026-10-13): React port of trips.js lines 8189-9271 (weather board, packing,
   renderContext, the nearby rail, the ground plan, the day-of rail, tripDays, reload and the delete writes).
   Near-verbatim plain functions that build HTML strings and write them into the fixed hosts; see
   trips-core.jsx for the shape and /tmp/hub-sandbox/trips-parts-interface.md for the part contract. No object
   spread, no async/await (the writes are promise chains with the same catch scope). */
(() => {
const U = window.TripsUI;
const { esc, setHTML, toast, errMsg, state, $, T, CC, todayISO, chosenStay, tripMoney, costChart, costContext,
  carPickup, carDropoff, isCommitted, statusCounts, renderAll } = U;
const API = U.api;
const priceText = U.priceHtml;
const { absDate, defaultDir, bindRows, itineraryModel, dayLabel, dayShort, stampShort,
  ptOf, airportPt, driveMin, dur, absOf, baseOf, bookedCar, rowBrand, carAddr, noteVal, onCar, readerLegs,
  readerMember, timelineReads, crewLegs, crewArrivals, dayReadHTML, legKey, flightlessMembers,
  viewerFlightMissing, prefsWait, shortName, detailActivity, detailLogistics, detailMember, detailExpense,
  gSections, wxLabel, wxArt, wxAnchor, wxWindow, wxUrl, wxRows, wxHours, wxDate, wxLongDay, wxWet, wxNum, wxHas,
  wxClock, wxHourLabel, wxSunHour, wxDaylight, wxDir, wxUvWord, wxTripChart, wxHourChart, wxKey, confirmDialog
} = U.fwd("absDate", "defaultDir", "bindRows", "itineraryModel", "dayLabel", "dayShort", "stampShort",
  "ptOf", "airportPt", "driveMin", "dur", "absOf", "baseOf", "bookedCar", "rowBrand", "carAddr", "noteVal", "onCar",
  "readerLegs", "readerMember", "timelineReads", "crewLegs", "crewArrivals", "dayReadHTML", "legKey",
  "flightlessMembers", "viewerFlightMissing", "prefsWait", "shortName", "detailActivity", "detailLogistics",
  "detailMember", "detailExpense", "gSections", "wxLabel", "wxArt", "wxAnchor", "wxWindow", "wxUrl", "wxRows",
  "wxHours", "wxDate", "wxLongDay", "wxWet", "wxNum", "wxHas", "wxClock", "wxHourLabel", "wxSunHour", "wxDaylight",
  "wxDir", "wxUvWord", "wxTripChart", "wxHourChart", "wxKey", "confirmDialog");
// the crew card vocabulary, as the plain page destructures it from CC (crewcard.js)
const { label, INTEREST_VERDICT_LABEL, CUISINE_VERDICT_LABEL } = CC;

  // ── THE BOARD ───────────────────────────────────────────────────────────────
  // One payload, held so the day view can be drawn without re-fetching. Keyed by
  // trip so switching trips can never paint the last city's hours under this
  // one's name — the same guard the fetch callback already makes, kept here
  // because renderContext runs on its own and has no callback to check.
  let wxData = null;

  function listWeather(head, list) {
    const t = state.trip;
    const days = tripDays();
    const a = wxAnchor(t);
    const win = wxWindow(days, todayISO());

    const say = (fig, label, line) => setHTML(head, `
      <div class="hub-figure">
        <div class="hub-figure-fig">
          <span class="hub-figure-n">${fig}</span>
          <span class="hub-figure-l">${esc(label)}</span>
        </div>
        <div class="hub-figure-split">${line}</div>
      </div>`);
    const dead = (msg) => { wxData = null; state.selId = null; setHTML(list, `<div class="hub-empty-state focus-empty">${msg}</div>`); renderContext(); };

    if (!a) {
      say("—", "no forecast", "no stay on this trip has been placed on the map yet, and the stay is what the forecast is measured from. Geocode a room on the housing tab and this fills in.");
      return dead("nowhere to read the weather from");
    }
    if (win.state === "past") {
      say("—", "trip is over", `${esc(a.name)} · these days have already happened, so there is nothing left to forecast`);
      return dead("this trip is in the past");
    }
    if (win.state === "far") {
      say(String(days.length), days.length === 1 ? "day" : "days", `${esc(a.name)} · the forecast only runs ${U.WX_HORIZON + 1} days out, so it opens on ${esc(wxDate(win.opens))}`);
      return dead(`too far out to forecast, check back ${esc(wxDate(win.opens))}`);
    }

    // Already read for this trip and this range — repaint from memory rather than
    // going back out. Clicking a day re-enters through here, and a spinner between
    // a click and a chart that is already in hand is the board pretending to work.
    const key = `${t.id}|${win.shown[0]}|${win.shown[win.shown.length - 1]}`;
    if (wxData && wxData.key === key) return paintWeather(head, list, wxData, a, win, say);

    say("…", "reading", `${esc(a.name)}`);
    setHTML(list, `<div class="hub-empty-state focus-empty">reading the forecast…</div>`);
    const from = win.shown[0], to = win.shown[win.shown.length - 1];
    fetch(wxUrl(a, from, to))
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => {
        // moved on before the read landed, or switched trips — the payload is for
        // one place and one date range, so a stale one paints the wrong city.
        if (state.mode !== "weather" || !state.trip || state.trip.id !== t.id) return;
        wxData = { key, tripId: t.id, rows: wxRows(d), hours: wxHours(d) };
        paintWeather(head, list, wxData, a, win, say);
      })
      .catch((e) => {
        if (state.mode !== "weather") return;
        say("—", "no forecast", `couldn't reach the weather service — ${esc(errMsg(e))}`);
        dead("couldn't read the forecast");
      });
  }

  function paintWeather(head, list, data, a, win, say) {
    const keepTop = list.scrollTop;
    const rows = data.rows;
    if (!rows.length) {
      say("—", "no forecast", `${esc(a.name)} · the service returned no days for this range`);
      wxData = null; state.selId = null;
      setHTML(list, `<div class="hub-empty-state focus-empty">no days came back</div>`);
      return renderContext();
    }
    // What you pack against is the whole trip's spread, not any one day: the
    // coldest night and the warmest afternoon, stated as one range.
    const today = todayISO();
    const los = rows.map((r) => r.lo).filter(wxHas);
    const his = rows.map((r) => r.hi).filter(wxHas);
    const wet = rows.filter(wxWet).length;
    const tail = win.state === "partial"
      ? ` · the last ${win.missing} ${win.missing === 1 ? "day is" : "days are"} past the forecast's reach for now`
      : "";
    const rain = !wet ? "nothing wet in the run"
      : `${wet} of ${rows.length} ${rows.length === 1 ? "day" : "days"} ${wet === 1 ? "carries" : "carry"} a real chance of rain`;
    say(`${wxNum(Math.min(...los), "°")} – ${wxNum(Math.max(...his), "°")}`,
        "across the trip",
        `${esc(a.name)}${a.firm ? "" : " (not booked yet)"} · ${rain}${tail}`);

    // The day that opens by default is today if the trip is running, otherwise its
    // first day — never nothing, because a board that ends on a list you have to
    // click reads as unfinished. The old width test picked nothing on a phone,
    // where the day used to be a slide-over you opted into; it is the bottom of
    // this column now, so a narrow screen simply scrolls to it.
    if (!rows.some((r) => r.date === state.selId)) {
      state.selId = rows.some((r) => r.date === today) ? today : rows[0].date;
    }

    setHTML(list, `
      <div class="lcard hub-t3p-card hub-plate-card">
        <div class="hub-section-head lgroup-head lgroup-sub">
          <span class="hub-section-head-t lgroup-l">the shape of the run</span>
          <span class="hub-section-head-sum lgroup-sum">${rows.length} ${rows.length === 1 ? "day" : "days"}</span>
        </div>
        ${wxTripChart(rows)}
        ${wxKey([{ cls: "is-hi", label: "high" }, { cls: "is-lo", label: "low" }, { cls: "is-bar", label: "chance of rain" }])}
      </div>
      <div class="lcard hub-t3p-card hub-plate-card">
        <div class="hub-section-head lgroup-head lgroup-sub">
          <span class="hub-section-head-t lgroup-l">day by day</span>
          <span class="hub-section-head-sum lgroup-sum">pick one</span>
        </div>
        <div class="wxlist">${rows.map((r) => `
          <div class="wxrow${r.date === state.selId ? " selected" : ""}${r.date === today ? " is-today" : ""}" data-id="${esc(r.date)}">
            <div class="wxrow-d">
              <b>${esc(dayLabel(r.date))}</b>
              <span>${r.date === today ? "today" : esc(wxDate(r.date))}</span>
            </div>
            ${wxArt(r.code, "wxrow-i")}
            <div class="wxrow-c">
              <b>${esc(wxLabel(r.code))}</b>
              <span>feels ${wxNum(r.feelsLo, "°")}–${wxNum(r.feelsHi, "°")}</span>
            </div>
            <div class="wxrow-t"><b>${wxNum(r.hi, "°")}</b><span>${wxNum(r.lo, "°")}</span></div>
            <div class="wxrow-w${wxWet(r) ? " is-wet" : ""}">
              <b>${wxNum(r.pop, "%")}</b>
              <span>${(r.snow || 0) >= 0.05 ? `${r.snow.toFixed(1)}" snow`
                    : (r.rain || 0) >= 0.01 ? `${r.rain.toFixed(2)}"` : "dry"}</span>
            </div>
            <div class="wxrow-g"><b>${wxNum(r.wind, "")}</b><span>mph ${esc(wxDir(r.dir))}</span></div>
          </div>`).join("")}</div>
      </div>
      ${detailWeather()}`);

    // Picking a day repaints this whole column, so the scroll offset has to be
    // carried across it — without this the board jumps back to the chart every
    // time you click a row you had scrolled down to. Reading scrollHeight first
    // is load-bearing: it forces the layout the fresh HTML has not had yet, and
    // without it the assignment clamps against a stale height and lands short.
    if (keepTop) { void list.scrollHeight; list.scrollTop = keepTop; }
    bindRows(list, (id) => { state.selId = id; paintWeather(head, list, data, a, win, say); }, ".wxrow");
    // The chart's day columns are the same control as the rows under them, so a
    // click on the peak you are squinting at opens that day rather than doing
    // nothing — which is what a chart that is not a control teaches you it does.
    list.querySelectorAll("[data-wxday]").forEach((g) => {
      g.style.cursor = "pointer";
      g.onclick = () => { state.selId = g.dataset.wxday; paintWeather(head, list, data, a, win, say); };
    });
    renderContext();
  }

  // ── THE DAY ─────────────────────────────────────────────────────────────────
  // Everything the summary row could not carry: what it actually feels like at
  // each end, when the sun is up, how hard the wind gets, and the four hourly
  // curves. This is the expansion the tab was missing — the old board's whole
  // answer to "what is Saturday like" was one line of text.
  function detailWeather() {
    const t = state.trip;
    if (!wxData || !t || wxData.tripId !== t.id) return "";
    const day = wxData.rows.filter((r) => r.date === state.selId)[0];
    if (!day) return `<div class="lcard hub-t3p-card hub-plate-card is-wxday"><div class="wxdet"><div class="ctx-sub">pick a day above to open it.</div></div></div>`;
    const hrs = (wxData.hours[day.date] || []).slice().sort((x, y) => x.hour - y.hour);
    const today = todayISO();

    // The warmest and coldest hours, named. "High 81" is a number; "81 at 3pm" is
    // a plan, and the difference is whether you know to be indoors at three.
    const peak = hrs.filter((h) => wxHas(h.temp)).sort((x, y) => y.temp - x.temp)[0];
    const trough = hrs.filter((h) => wxHas(h.temp)).sort((x, y) => x.temp - y.temp)[0];
    const wettest = hrs.filter((h) => wxHas(h.pop)).sort((x, y) => y.pop - x.pop)[0];
    const gustiest = hrs.filter((h) => wxHas(h.gust)).sort((x, y) => y.gust - x.gust)[0];
    const wetRun = hrs.filter((h) => (h.pop || 0) >= 40 || (h.precip || 0) >= 0.01);

    const stat = (l, v, sub) => `<div class="wxs hub-stat hub-stat--tile">
      <div class="wxs-l">${esc(l)}</div><div class="wxs-v hub-stat-v">${v}</div>
      ${sub ? `<div class="wxs-s">${sub}</div>` : ""}</div>`;

    // The sentence under the headline is the day's actual verdict, assembled from
    // what the day is rather than picked from a list of moods. It says the wet
    // window when there is one, because "60% chance" over a whole day and "60%
    // between 2 and 5" are different days and only one of them cancels a hike.
    const verdict = [
      wetRun.length
        ? `wet between ${wxHourLabel(wetRun[0].hour)} and ${wxHourLabel(wetRun[wetRun.length - 1].hour + 1)}`
        : (day.pop || 0) >= 20 ? "a small chance of rain, nothing settled" : "dry all day",
      wxHas(day.gust) && day.gust >= 25 ? `gusting to ${wxNum(day.gust, "")} mph` : "",
      wxHas(day.uv) && day.uv >= 6 ? `${wxUvWord(day.uv)} sun at midday` : "",
    ].filter(Boolean).join(" · ");

    return `
      <div class="lcard hub-t3p-card hub-plate-card is-wxday">
        <div class="hub-section-head lgroup-head lgroup-sub">
          <span class="hub-section-head-t lgroup-l">${esc(wxLongDay(day.date))}</span>
          <span class="hub-section-head-sum lgroup-sum">${day.date === today ? "today" : "the day you picked"}</span>
        </div>
        <div class="wxdet">
        <div class="wxdet-head">
          ${wxArt(day.code, "wxdet-i")}
          <div class="wxdet-hl">
            <div class="wxdet-c">${esc(wxLabel(day.code))}</div>
          </div>
          <div class="wxdet-t"><b>${wxNum(day.hi, "°")}</b><span>${wxNum(day.lo, "°")}</span></div>
        </div>
        <div class="wxdet-verdict">${esc(verdict)}</div>

        <div class="hub-stat-grid">
          ${stat("feels like", `${wxNum(day.feelsLo, "°")} – ${wxNum(day.feelsHi, "°")}`,
                 peak && trough ? `coldest ${wxHourLabel(trough.hour)} · warmest ${wxHourLabel(peak.hour)}` : "")}
          ${stat("rain", wxNum(day.pop, "%"),
                 (day.rain || 0) >= 0.01 ? `${day.rain.toFixed(2)}" over ${wxNum(day.wetHours, "")} hr` : "nothing forecast to fall")}
          ${(day.snow || 0) >= 0.05 ? stat("snow", `${day.snow.toFixed(1)}"`, "") : ""}
          ${stat("wind", `${wxNum(day.wind, "")} mph`,
                 `${esc(wxDir(day.dir))}${wxHas(day.gust) ? ` · gusts ${wxNum(day.gust, "")}` : ""}${gustiest ? ` at ${wxHourLabel(gustiest.hour)}` : ""}`)}
          ${stat("uv", wxNum(day.uv, ""), wxUvWord(day.uv))}
          ${stat("sun", `${esc(wxClock(day.sunrise))} → ${esc(wxClock(day.sunset))}`, `${esc(wxDaylight(day.daylight))} of daylight`)}
        </div>

        ${hrs.length ? `
        <div class="wxblock">
          <div class="wxblock-h">temperature<span>${peak ? `peaks ${wxNum(peak.temp, "°")} at ${wxHourLabel(peak.hour)}` : ""}</span></div>
          ${wxHourChart(hrs, "temp", day, today)}
          ${wxKey([{ cls: "is-0", label: "air" }, { cls: "is-1", label: "feels like" }, { cls: "is-night", label: "dark" }])}
        </div>
        <div class="wxblock">
          <div class="wxblock-h">chance of rain<span>${wettest ? `worst ${wxNum(wettest.pop, "%")} at ${wxHourLabel(wettest.hour)}` : ""}</span></div>
          ${wxHourChart(hrs, "rain", day, today)}
          ${wxKey([{ cls: "is-bar", label: "chance" }, { cls: "is-wetbar", label: "rain actually falling" }])}
        </div>
        <div class="wxblock">
          <div class="wxblock-h">wind<span>${gustiest ? `gusts ${wxNum(gustiest.gust, "")} mph at ${wxHourLabel(gustiest.hour)}` : ""}</span></div>
          ${wxHourChart(hrs, "wind", day, today)}
          ${wxKey([{ cls: "is-0", label: "gusts" }, { cls: "is-1", label: "sustained" }])}
        </div>
        <div class="wxblock">
          <div class="wxblock-h">humidity and cloud<span>mugginess and cover</span></div>
          ${wxHourChart(hrs, "hum", day, today)}
          ${wxKey([{ cls: "is-0", label: "humidity" }, { cls: "is-1", label: "cloud cover" }])}
        </div>
        <div class="wxhours">
          <div class="wxblock-h">hour by hour</div>
          <div class="hub-scroll-table wxhr-scroll"><table class="wxhr">
            <thead><tr><th>hr</th><th></th><th>temp</th><th>feels</th><th>rain</th><th>wind</th><th>hum</th></tr></thead>
            <tbody>${hrs.filter((h) => h.hour % 2 === 0).map((h) => {
              const up = wxSunHour(day.sunrise), down = wxSunHour(day.sunset);
              const dark = up != null && down != null && (h.hour < up || h.hour >= down);
              return `
              <tr${day.date === today && h.hour === new Date().getHours() ? ` class="is-now"` : ""}>
                <td>${wxHourLabel(h.hour)}</td>
                <td>${wxArt(h.code, "wxhr-i", dark)}</td>
                <td>${wxNum(h.temp, "°")}</td>
                <td>${wxNum(h.feels, "°")}</td>
                <td>${wxNum(h.pop, "%")}</td>
                <td>${wxNum(h.wind, "")}</td>
                <td>${wxNum(h.hum, "%")}</td>
              </tr>`; }).join("")}</tbody>
          </table></div>
        </div>` : `<div class="ctx-sub">the service returned no hourly readings for this day.</div>`}
        </div>
      </div>`;
  }

  // ── PACKING: Sam's own lists, portalled from /checklists ─────────────────
  // The rows are /checklists' rows (category packing, plus Camera Gear beside
  // them, plus whichever of Beach/Snowboarding/Rave this trip has added); the
  // CONTENTS are never copied, so an edit over there shows up here on the next
  // open. The TICKS are this trip's alone — they live in trips.db keyed by trip,
  // and /checklists never sees them, because "packed" is a fact about one trip
  // and the same list gets packed again for the next one.
  function listPacking(head, list) {
    setHTML(head, "");
    setHTML(list, `<div class="hub-empty-state focus-empty">reading your lists…</div>`);
    const tid = state.trip.id;
    API.get(`/packing/${tid}`).then((lists) => {
      // moved on — or switched trips — before the read landed. The payload is
      // scoped to one trip now, so a stale one would paint the wrong ticks.
      if (state.mode !== "packing" || !state.trip || state.trip.id !== tid) return;
      paintPacking(head, list, lists || []);
    }).catch((e) => setHTML(list, `<div class="hub-empty-state focus-empty">couldn't read the lists — ${esc(errMsg(e))}</div>`));
  }

  // Which of the optional lists this trip has pulled in. Per trip and per reader,
  // same shape and same reasoning as HM_KEY — a beach list added to Austin has no
  // business appearing on the snowboarding trip.
  const PK_KEY = (t) => `trips.packing.${t.id}`;
  function pkAdded(t) {
    try { const v = JSON.parse(localStorage.getItem(PK_KEY(t)) || "[]"); return new Set(Array.isArray(v) ? v : []); }
    catch { return new Set(); }
  }
  function pkAdd(t, id, on) {
    const v = pkAdded(t); if (on) v.add(id); else v.delete(id);
    try { localStorage.setItem(PK_KEY(t), JSON.stringify([...v])); } catch { /* private mode */ }
  }

  function paintPacking(head, list, lists) {
    // The three activity lists are opt-in: most trips are not a rave. They come
    // back flagged from /api/packing/<trip> and only draw once this trip has added one.
    const optional = lists.filter((l) => l.optional);
    const on       = pkAdded(state.trip);
    const shown    = lists.filter((l) => !l.optional || on.has(l.id));
    const all = shown.flatMap((l) => l.items || []);
    const packed = all.filter((i) => Number(i.checked)).length;
    setHTML(head, `
      <div class="hub-figure">
        <div class="hub-figure-fig">
          <span class="hub-figure-n${packed === all.length && all.length ? " docount-all" : ""}">${packed} of ${all.length}</span>
          <span class="hub-figure-l">packed</span>
        </div>
        <div class="hub-figure-split">${shown.length} lists, the same ones as <a href="/checklists/">/checklists</a> — edit them there; ticks stay on this trip</div>
        ${optional.length ? `<div class="pkopts"><span class="hub-figure-split">for this trip</span>${
          optional.map((l) => `<button class="hub-section-head-act lgroup-act${on.has(l.id) ? " is-on" : ""}" data-pkopt="${esc(String(l.id))}">${
            on.has(l.id) ? "" : "+ "}${esc(l.name)}</button>`).join("")}</div>` : ""}
      </div>`);
    head.querySelectorAll("[data-pkopt]").forEach((b) => {
      b.onclick = () => {
        const id = Number(b.dataset.pkopt);
        pkAdd(state.trip, id, !on.has(id));
        paintPacking(head, list, lists);
      };
    });
    const sumOf = (items) => {
      const got = items.filter((i) => Number(i.checked)).length;
      return !items.length ? "nothing on it" : got === items.length ? "all packed"
        : got ? `${items.length - got} still to pack` : `${items.length} things`;
    };
    const row = (l, g) => `<li class="hub-checklist-item doitem gitem">
            <label class="hub-checkbox-label"><input type="checkbox" data-pk="${esc(String(l.id))}:${esc(String(g.id))}"${
              Number(g.checked) ? " checked" : ""}>
              <span class="hub-checklist-text"><b class="gitem-n">${esc(g.text || "")}</b>${
                g.qty ? `<i class="gqty">${esc(g.qty)}</i>` : ""}${
                g.note ? `<span class="gnote">${esc(g.note)}</span>` : ""}${
              Number(g.covered) ? `<span class="gnote">${esc(state.trip.grocery_stay || "the stay")} has it</span>` : ""}</span></label>
          </li>`;
    const cnt = head.querySelector(".decide-n");
    const recount = () => {
      const n = all.filter((i) => Number(i.checked)).length;
      if (cnt) { cnt.textContent = `${n} of ${all.length}`; cnt.classList.toggle("docount-all", n === all.length && all.length > 0); }
    };
    // Each list runs the full width, head across the top, and ITS items flow into
    // columns underneath (.pkcols, trips.css); then the next list. A section is
    // the unit that never splits across two columns, hence the .pksec wrapper.
    // A tick moves the row out of its list and into the completed card at the
    // bottom, so the board above always reads as what is still left to do — which
    // means a tick redraws the grid rather than only restyling the row in place.
    // Trips-only in both directions: the tick is stored against this trip, and
    // /checklists goes on drawing its lists whole and knows nothing about it.
    const drawGrid = () => {
      const top = list.scrollTop;   // setHTML on the scroller drops you back to Travel
      const done = shown.flatMap((l) => (l.items || []).filter((i) => Number(i.checked)).map((i) => [l, i]));
      setHTML(list, shown.length ? `<div class="pkgrid">` + shown.map((l) => {
        const items = l.items || [];
        const open  = items.filter((i) => !Number(i.checked));
        return `<div class="pklist hub-t3p-card hub-plate-card"><div class="hub-section-head lgroup-head lgroup-sub" data-pklist="${esc(String(l.id))}">
            <span class="hub-section-head-t lgroup-l">${esc(l.name)}</span>
            <span class="hub-section-head-sum lgroup-sum">${esc(sumOf(items))}</span>
            <button class="hub-section-head-act lgroup-act" data-pkreset="${esc(String(l.id))}"${items.some((i) => Number(i.checked)) ? "" : " hidden"}>clear ticks</button></div>`
          + (open.length ? `<div class="hub-column-list pkcols">`
            + gSections(open).map(([sec, rows]) => `<div class="pksec">` + (sec ? `<div class="hub-list-eyebrow gsec">${esc(sec)}</div>` : "")
              + `<ul class="hub-checklist dolist glist">${rows.map((g) => row(l, g)).join("")}</ul></div>`).join("") + `</div>`
            : `<div class="hub-section-empty">${items.length ? "all of it is packed" : "nothing on it"}</div>`)
          + `</div>`;
      }).join("")
      // The completed card. Grouped by the list each row came from, because "where
      // does this go back to" is the only question you ask of a packed item.
      + (done.length ? `<div class="pklist hub-t3p-card hub-plate-card pkdone"><div class="hub-section-head lgroup-head lgroup-sub">
            <span class="hub-section-head-t lgroup-l">completed</span>
            <span class="hub-section-head-sum lgroup-sum">${done.length} packed</span></div><div class="hub-column-list pkcols">`
        + shown.filter((l) => done.some(([x]) => x === l)).map((l) => `<div class="pksec">
            <div class="hub-list-eyebrow gsec">${esc(l.name)}</div>
            <ul class="hub-checklist dolist glist">${done.filter(([x]) => x === l).map(([, g]) => row(l, g)).join("")}</ul></div>`).join("")
        + `</div></div>` : "")
      + `</div>` : `<div class="hub-section-empty">no packing lists on /checklists yet</div>`);
      list.scrollTop = top;
      recount();
      bind();
    };
    const bind = () => {
      list.querySelectorAll("[data-pk]").forEach((b) => {
        b.onchange = () => {
          const [cid, iid] = b.dataset.pk.split(":");
          const l = shown.filter((x) => String(x.id) === cid)[0];
          const g = l && (l.items || []).filter((x) => String(x.id) === iid)[0];
          const was = g ? g.checked : 0;
          const now = b.checked ? 1 : 0;
          if (g) g.checked = now;
          drawGrid();
          API.patch(`/packing/${state.trip.id}/${cid}/items/${iid}`, { checked: now }).catch((e) => {
            // The tick did not land, so it must not stay drawn — and the row has to
            // travel back to the card it just left.
            if (g) g.checked = was;
            drawGrid();
            toast(`tick didn't save — ${errMsg(e)}`);
          });
        };
      });
      list.querySelectorAll("[data-pkreset]").forEach((btn) => {
        btn.onclick = () => {
          const l = shown.filter((x) => String(x.id) === btn.dataset.pkreset)[0];
          if (!l) return;
          API.post(`/packing/${state.trip.id}/${l.id}/reset`).then(() => {
            (l.items || []).forEach((i) => { i.checked = 0; });
            drawGrid();
          }, (e) => { toast(`couldn't clear — ${errMsg(e)}`); });
        };
      });
    };
    drawGrid();
  }

  function renderContext() {
    const c = $("context"), rail = $("contextCol");
    // mobile (<900px): a selection takes over the context rail as a full-viewport
    // slide-over instead of the old display:none-forever dead end (see trips.css)
    rail.classList.toggle("is-open", state.selId != null);
    if (!state.trip) { setHTML(c, ""); rail.classList.remove("context--summary"); return; }
    // a selected item takes over the context rail with its full detail — never fade
    // this state, it can be tall/scrollable and the dot-grid mask must not hide content
    if (state.selId != null) {
      rail.classList.remove("context--summary");
      // the itinerary mixes both id shapes in one view — a bare number is an
      // activity, "kind:id" is a logistics row — so route by shape, not by mode
      if (state.mode === "itinerary") {
        return typeof state.selId === "number" ? detailActivity(c) : detailLogistics(c);
      }
      if (state.mode === "activities") return detailActivity(c);
      // both booking panels carry expenses too, so route on the id prefix the
      // same way the itinerary does rather than assuming a kind
      if (state.mode === "flights" || state.mode === "housing") {
        return String(state.selId).startsWith("expense:") ? detailExpense(c) : detailLogistics(c);
      }
      if (state.mode === "crew") return detailMember(c);
    }
    // Food's rail belongs to FoodView: the map above it and the place read inside it
    // are both drawn there, and anything written here would land on top of them.
    if (state.mode === "food" && U.mut.foodMounted) return;
    // The bottom fade (cobalt only) exists to kill the empty dot-grid under short
    // summary cards — so it can only be decided AFTER the content lands, from
    // whether there is actually slack to fade. Adding it up front was fine while
    // every summary was three fixed-height cards; the crew read is a card per
    // axis and tall enough to have its last rows masked away. See trips.css.
    if (state.mode === "crew") { setHTML(c, crewContext()); return fadeIfSlack(rail, c); }
    // Transportation asks one question — does the day actually work — and the
    // arrival/departure read is the answer, so it owns the rail here instead of
    // sitting three screens down the board. Budget, activities and where-you're-
    // staying belong to the tabs that own those decisions; on this one they were
    // four cards of someone else's business next to the thing you came to read.
    if (state.mode === "flights") { setHTML(c, groundContext(state.trip)); return fadeIfSlack(rail, c); }
    // Housing owns its rail the same way transportation does. The map above it
    // shows where the house is; the only question that raises is what is within
    // reach of it, and nothing on the page answered that. The four generic cards
    // that used to sit here were three other tabs' business.
    if (state.mode === "housing") { return nearbyContext(c, rail); }
    // Cost owns its rail the same way. The body is entirely his share, so the
    // rail carries the half it drops — what the trip costs everyone together,
    // which is the figure on the invoice and what he collects against. The four
    // generic cards would have been three other tabs' business here too.
    if (state.mode === "cost") { setHTML(c, costContext()); return fadeIfSlack(rail, c); }
    // Day-of has no rail at all — the tab is full width (trips.css). Clear it so
    // the previous tab's cards don't survive the switch in the hidden column.
    // ponytail: dayOfContext/crewTodayCard/farEndCard are now unwired; left in
    // place because the dayof body is still being reworked and they are the
    // built read of the crew's morning and the far end if either is re-homed.
    if (state.mode === "dayof") { setHTML(c, ""); rail.classList.remove("context--summary"); return; }
    // Grocery is full width too (trips.css). The run card is already the head of
    // the tab; a rail repeating the check-in it was derived from, next to four
    // cards of other tabs' business, is two reads competing with a shopping list.
    if (state.mode === "grocery") { setHTML(c, ""); rail.classList.remove("context--summary"); return; }
    // Weather is full width too (trips.css) — the day it opens is drawn under the
    // day list in the same column, not beside it. Clear the hidden rail so the
    // previous tab's cards don't survive the switch inside it.
    if (state.mode === "weather") { setHTML(c, ""); rail.classList.remove("context--summary"); return; }
    // Packing likewise: the lists ARE the read, nothing belongs beside them.
    if (state.mode === "packing") { setHTML(c, ""); rail.classList.remove("context--summary"); return; }
    const t = state.trip;
    const next = nextScheduled();
    const anc = chosenStay();   // the row you booked or picked, never just the first one
    const total = tripMoney();   // every money table, not just `expenses`
    const acts = t.activities || [];
    setHTML(c, `
      <div class="hub-detail-card"><div class="hub-detail-card-head ctx-card-head">up next</div>
        ${next ? `<div class="hub-kv-row ctx-row"><b>${esc(next.name)}</b></div><div class="ctx-sub">${esc(next.scheduled_date)}${next.scheduled_time ? ` · ${esc(T.fmtClockText(next.scheduled_time))}` : ""}</div>` : `<div class="ctx-sub">nothing scheduled yet</div>`}</div>
      <div class="hub-detail-card"><div class="hub-detail-card-head ctx-card-head">activities</div>
        <div class="hub-kv-row ctx-row"><span>considering</span><b>${acts.filter((a) => a.status === "considering").length}</b></div>
        <div class="hub-kv-row ctx-row"><span>queue</span><b>${acts.filter((a) => a.status === "deciding").length}</b></div>
        <div class="hub-kv-row ctx-row"><span>scheduled</span><b>${acts.filter((a) => a.status === "scheduled").length}</b></div></div>
      <div class="hub-detail-card"><div class="hub-detail-card-head ctx-card-head">where you're staying</div>
        ${anc ? `<div class="hub-kv-row ctx-row"><b>${esc(anc.name || anc.address || "stay")}</b></div>${anc.check_in ? `<div class="ctx-sub">${esc(stampShort(anc.check_in))} → ${esc(anc.check_out ? stampShort(anc.check_out) : "")}</div>` : ""}`
          : `<div class="ctx-sub">${(t.housing || []).length ? `still deciding · ${(t.housing || []).length} options` : "no housing set"}</div>`}</div>
      <div class="hub-detail-card"><div class="hub-detail-card-head ctx-card-head">your share</div>
        <div class="ctx-big">${priceText(total.committed)}</div>
        <div class="ctx-sub">committed · ${priceText(total.projected)} projected${total.party > 1 ? ` · split ${total.party}\u00a0ways` : ""}</div>
        ${costChart(total)}</div>`);
    fadeIfSlack(rail, c);
  }

  // ── WHAT'S AROUND THE STAY ──────────────────────────────────────────────────
  // Everything here is scoped by a hard radius the server enforces (nearby.py,
  // 1.2 km — a fifteen-minute walk, or two minutes of driving). An empty
  // category renders as "nothing this close" and stays empty. That is the whole
  // point: a nearest-match with no radius answers "where's the pharmacy" with
  // one three miles down a highway, which reads as an answer and isn't one.
  // OSM carries no ratings, so "is it any good" is a question this data cannot
  // answer. Every name links out to Maps, which can.
  const mapsLink = (n) => "https://www.google.com/maps/search/?api=1&query="
    + encodeURIComponent(`${n.name} ${n.lat},${n.lng}`);
  // minutes only: the card is already "within a N min walk", and a 0.0 mi beside
  // 1 min said nothing the minutes had not (mark 2026-10-14, "miles not needed")
  const nearDist = (n) => `${n.walk_min} min`;

  // One line per place. `kind` (OSM's cuisine/shop value, already stripped
  // server-side when it just repeats the heading) and the chain flag ride inline
  // after the name — as a row of their own they doubled the panel's height to
  // carry one word.
  function nearPlace(n) {
    const tag = [n.kind, n.chain ? "chain" : ""].filter(Boolean).join(" · ");
    return `<li class="near-p">
      <span class="near-nm"><a class="near-n" href="${esc(mapsLink(n))}" target="_blank" rel="noopener">${esc(n.name)}</a>${
        tag ? `<span class="near-t">${esc(tag)}</span>` : ""}</span>
      <span class="near-d">${esc(nearDist(n))}</span>
    </li>`;
  }

  function nearCard(data) {
    const cats = (data.headline || []).map((g) =>
      `<div class="near-cat"><div class="near-k">${esc(g.cat)}</div>${
        g.places.length ? `<ul class="near-ul">${g.places.map(nearPlace).join("")}</ul>`
          : `<div class="near-none">nothing this close</div>`}</div>`).join("");
    const extra = data.extra || [];
    return `<div class="hub-detail-card">
        <div class="hub-detail-card-head ctx-card-head">within a ${data.walk_min} min walk</div>${cats}</div>${
      extra.length ? `<div class="hub-detail-card"><div class="hub-detail-card-head ctx-card-head">also in range</div>
        <div class="near-chips">${extra.map((g) =>
          `<a class="near-chip" href="${esc(mapsLink(g.place))}" target="_blank" rel="noopener"
            ><span class="near-ck">${esc(g.cat)}</span> ${esc(g.place.name)} <b>${g.place.walk_min} min</b></a>`
        ).join("")}</div></div>` : ""}
      <div class="hub-detail-card"><div class="ctx-sub">from OpenStreetMap, which has no reviews — the names link out to Maps for that. Anything past the walk isn't listed.</div></div>`;
  }

  function nearHead(h) {
    const addr = h.address || "";
    const href = addr ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(addr)}` : "";
    return `<div class="hub-detail-card"><div class="hub-detail-card-head ctx-card-head">you're staying at</div>
      <div class="near-stay">${esc(h.name || addr || "the stay")}</div>
      ${addr ? `<div class="hub-text-act near-addr"><span>${esc(addr)}</span>${href
        ? `<a class="hub-link-chip llink" href="${esc(href)}" target="_blank" rel="noopener">map ↗</a>` : ""}</div>` : ""}</div>`;
  }

  function nearbyContext(c, rail) {
    rail.classList.remove("context--summary");
    const h = chosenStay();
    if (!h) {
      setHTML(c, `<div class="hub-detail-card"><div class="hub-detail-card-head ctx-card-head">what's around it</div>
        <div class="ctx-sub">pick an option on the board and this reads what's within a walk of that exact address</div></div>`);
      return;
    }
    if (h.lat == null || h.lng == null) {
      setHTML(c, `${nearHead(h)}<div class="hub-detail-card"><div class="ctx-sub">this row has no coordinates yet — geocode it and what's around it lands here</div></div>`);
      return;
    }
    const n = state.near;
    if (n && n.hid === h.id) {
      setHTML(c, nearHead(h) + (n.error
        ? `<div class="hub-detail-card"><div class="ctx-sub">couldn't read what's nearby — ${esc(n.error)}</div></div>`
        : nearCard(n.data)));
      return fadeIfSlack(rail, c);
    }
    setHTML(c, `${nearHead(h)}<div class="hub-detail-card"><div class="ctx-sub">reading what's within a walk…</div></div>`);
    // Fire once per stay and keep the answer on state: flipping tabs shouldn't
    // re-hit Overpass, and the server caches for a month on top of that.
    API.get(`/trips/${state.trip.id}/housing/${h.id}/nearby`)
      .then((data) => { state.near = { hid: h.id, data }; })
      .catch((e) => { state.near = { hid: h.id, error: String(e.message || e).slice(0, 120) }; })
      .then(() => { if (state.mode === "housing" && state.selId == null) renderContext(); });
  }

  // ── THE GROUND PLAN — the transportation rail ───────────────────────────────
  // What replaced "what that gets you", and why (Sam, 2026-08-26: "why are we
  // using phrases as titles for things ... check in this time, check out that
  // time, 40 minutes from the airport, what the fuck ever — include that in a
  // proper information logistics system, don't include it just as a random
  // phrase"). The old card was one poetic heading over one sentence that dumped
  // three unrelated facts as prose, and every number in it was a constant rather
  // than something read off the trip.
  //
  // Four cards now, each headed by what is IN it, and each answering one question
  // the transportation tab actually raises:
  //   your arrival / your departure — YOUR day, walked forward hour by hour
  //   the car                       — the vehicle everyone's day is built around
  //   when everyone lands           — why the pickup is at the hour it is
  //   fixed times                   — the clock nobody on the trip can move
  // What the car IS, without the bookkeeping. The description carries a trailing
  // "— booked by <name>" that is a record of who paid, not a fact about the
  // vehicle, and the driver line came off with it — Sam, 2026-08-26: "it
  // doesn't need to say 'booked by Jasmine' ... it doesn't matter that we have
  // multiple people that can drive." The named driver still appears in the
  // pickup crew's arrival read, where it is an at-the-desk requirement rather
  // than a credit.
  const carLead = (x) => String((x?.description) || "")
    .replace(/\s*[—–-]\s*(?:booked|reserved|paid)\s+by\b[^—–]*$/i, "").trim() || rowBrand(x);
  // One shape for every outbound link in the rail. Sam, 2026-08-26: the old
  // ones were "a tiny little ball on the left or a box on the left side" — a
  // bordered pill hugging the left edge of a row whose number sat at the far
  // right, so the thing you press and the number you are deciding on read as two
  // objects with a gap between them. The whole row is the target now: label left,
  // value right, the outbound mark at the edge, one border around all of it.
  // Same left-label/right-value skeleton as .ctx-row, so a pressable row and a
  // stated fact line up in the same card.
  function ctxLink(label, href, value) {
    const body = `<span class="hub-link-row-t ctx-link-t">${esc(label)}</span>`
      + (value ? `<span class="hub-link-row-v ctx-link-v">${esc(value)}</span>` : "")
      + (href ? `<span class="hub-link-row-x ctx-link-x" aria-hidden="true">↗</span>` : "");
    return href
      ? `<a class="hub-link-row ctx-link" href="${esc(href)}" target="_blank" rel="noopener">${body}</a>`
      : `<div class="hub-link-row hub-link-row--flat ctx-link ctx-link-flat">${body}</div>`;
  }
  function carCard(t) {
    const car = bookedCar(t);
    if (!car) return "";
    const addr = carAddr(car);
    const href = addr ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(addr)}` : "";
    const shuttle = noteVal(car, "Shuttle");
    const row = (k, v) => v ? `<div class="hub-kv-row ctx-row"><span>${esc(k)}</span><b>${esc(v)}</b></div>` : "";
    return `<div class="hub-detail-card"><div class="hub-detail-card-head ctx-card-head">the car</div>
      <div class="ctx-lead">${esc(carLead(car))}</div>
      ${row("pick up", stampShort(carPickup(car)))}
      ${row("back by", stampShort(carDropoff(car)))}
      ${row("seats", car.seats != null && car.seats !== "" ? String(car.seats) : "")}
      ${row("shuttle", shuttle)}
      ${row("confirmation", car.confirmation || "")}
      ${addr ? ctxLink(addr, href, "") : ""}</div>`;
  }
  // The staggered-arrival picture, with the car pickup sorted INTO it rather than
  // appended under it — the whole value of the card is seeing that the pickup sits
  // between the flight that fetches it and the one that misses it.
  function arrivalsCard(t) {
    const rows = crewArrivals(t);
    if (rows.length < 2) return "";
    const car = bookedCar(t), pk = car ? absOf(carPickup(car)) : null;
    const me = readerMember(t), mine = me ? me.name : "";
    const at = (abs, stamp) => T.fmtClock(((abs - baseOf(stamp)) % 1440 + 1440) % 1440);
    const items = rows.map((r) => ({
      at: r.at, when: at(r.at, r.row.arrival_time),
      label: r.names.map(shortName).join(" + "),
      you: !!(mine && r.names.indexOf(mine) >= 0),
    }));
    if (pk != null) items.push({ at: pk, when: at(pk, carPickup(car)), label: `${rowBrand(car)} pickup`, mark: 1 });
    items.sort((a, b) => a.at - b.at);
    const gap = flightlessMembers(t);
    return `<div class="hub-detail-card"><div class="hub-detail-card-head ctx-card-head">when everyone lands</div>${
      items.map((x) => `<div class="hub-kv-row ctx-row${x.you ? " ctx-row-you" : ""}${x.mark ? " ctx-row-mark" : ""}">
        <span>${esc(x.label)}${x.you ? " · you" : ""}</span><b>${esc(x.when)}</b></div>`).join("")}${
      gap.length ? `<div class="ctx-sub ctx-sub-warn">no flight on the board: ${
        esc(gap.map((m) => shortName(m.name)).join(", "))}</div>` : ""}</div>`;
  }
  // A clock that says WHICH DAY when it is not the base one. clockOf does this in
  // 24-hour, which is right on a timeline column and wrong in a rail row where
  // every other time is 12-hour. Same day-offset rule, same "+1d" / "-1d" marker.
  // Without it a return that lands at 00:59 prints "12:59a" and reads as the
  // morning you left rather than the one after.
  const dayClock = (abs, base) => {
    const d = Math.floor((abs - base) / 1440);
    return T.fmtClock(((abs % 1440) + 1440) % 1440) + (d ? `${(d > 0 ? " +" : " ") + d}d` : "");
  };

  /* ── DAY-OF RAIL ────────────────────────────────────────────────────────────
     The day-of body answers YOUR side of the morning and stops at wheels down.
     These two cards carry the half it drops: the rest of the crew's morning, and
     what is waiting at the far end. They are independent builders on purpose —
     card 2 needs a leg of your own, card 1 does not, and a guest whose ticket is
     not on the board yet is exactly the reader who most needs the crew picture. */

  // One row per FLIGHT, not per booking. crewLegs hands back a party per source
  // row, which puts the owner and Megan on two rows for the same WN0561: those
  // rows come from complementary filters (myFlights is the exact complement of
  // crewFlights's) and nothing in either walk can join them. legKey is the
  // signature crewFlights already merges on — carrier, route, departure, and
  // deliberately not the flight number — applied one level up so the merge
  // crosses the owner/crew boundary too. Names dedupe first-seen, which puts the
  // owner at the head of his own row without needing a sort.
  function crewTodayRows(t, dir) {
    const seen = {}, buckets = [];
    crewLegs(t, dir).forEach((x) => {
      const k = legKey(x.row);
      let b = seen[k];
      if (!b) buckets.push((seen[k] = b = { row: x.row, names: [] }));
      x.names.forEach((n) => { if (n && b.names.indexOf(n) < 0) b.names.push(n); });
    });
    const me = readerMember(t), mine = me ? me.name : "";
    const rows = buckets.map((b) => ({
      names: b.names, row: b.row,
      dep: absOf(b.row.departure_time), land: absOf(b.row.arrival_time),
      you: !!(mine && b.names.indexOf(mine) >= 0),
    }));
    // Departure order, with an unparsable time last rather than sorted as zero.
    rows.sort((a, b) => (a.dep == null) - (b.dep == null) || a.dep - b.dep);
    // The day a row is measured against is the READER'S, when they have one. A
    // crew member flying a day earlier is what the date badge exists to say, and
    // saying it relative to somebody else's morning would be backwards.
    const anchor = (rows.filter((r) => r.you)[0] || rows[0])?.dep;
    rows.forEach((r) => {
      r.offday = r.dep != null && anchor != null && absDate(r.dep) !== absDate(anchor);
    });
    return rows;
  }

  // It says when people take off and when they land, and claims nothing more than
  // that. Not that anyone is at the house — there is a drive from the airport,
  // which the far-end card states separately — and not that anyone will actually
  // make it. These are booked itineraries, not live status.
  function crewTodayCard(t, dir) {
    const rows = crewTodayRows(t, dir), gap = flightlessMembers(t);
    if (!rows.length && !gap.length) return "";
    // One flight is not a table. With nothing on the board but your own row there
    // is no staggering to read, and the boarding pass in the body already has the
    // times — so say the fact instead of drawing a one-row grid of it.
    const solo = rows.length === 1 && rows[0].you;
    const body = solo
      ? `<div class="ctx-sub">you're the only one on the board for this leg</div>`
      : rows.map((r) => {
        const base = baseOf(r.row.departure_time);
        // No landing time is a blank, never a dash: a dash reads as a checked
        // answer of "none" when nobody has filled the field in.
        // The clock PAIR is one value, not three words. At the rail's 300px floor a
        // plain " → " let the return row (five names) break between "5:15p →" and
        // "10:55p" and read as half a range. Same non-breaking bind routeText
        // already uses on an airport pair, for the same reason.
        const when = r.dep == null ? ""
          : dayClock(r.dep, base) + (r.land != null ? `\u00a0\u2192\u00a0${dayClock(r.land, base)}` : "");
        return `<div class="hub-kv-row ctx-row${r.you ? " ctx-row-you" : ""}">
          <span>${esc(r.names.map(shortName).join(" + "))}${r.you ? " · you" : ""}</span>
          <b>${esc((r.offday ? `${dayShort(absDate(r.dep))} ` : "") + when)}</b></div>`;
      }).join("");
    return `<div class="hub-detail-card"><div class="hub-detail-card-head ctx-card-head">the crew today</div>${body}${
      gap.length ? `<div class="ctx-sub ctx-sub-warn">no flight on this board: ${
        esc(gap.map((m) => shortName(m.name)).join(", "))}</div>` : ""}</div>`;
  }

  // The fixed clock of the FAR END — what is waiting when you land, or what has to
  // happen before you go. The body stops at wheels down, and every figure here is
  // one the reader needs before they are in the air rather than after.
  //
  // Four helpers this card deliberately does NOT call, each because it answers a
  // slightly different question and would answer it confidently:
  //   stayClock()  falls back to 15:00 / 11:00 when the row has no parsable time.
  //                Right on the transport rail, where a rule of thumb beats a
  //                blank. Wrong here, where a blank field means nobody filled it
  //                in and the row drops.
  //   chosenStay() returns a booked row OR one merely hand-picked in the UI. This
  //                card states facts about where you are actually sleeping.
  //   driveMin()   returns the DRIVE_MIN constant when either point is null, which
  //                prints a guess that reads exactly like a measurement.
  //   carCard()    is the transport tab's card and puts the PICKUP on screen. The
  //                pickup is never the reader's morning (2026-08-26: "we are not
  //                going to be picking up the ride"); the return is a deadline.
  function farEndRows(t, sel) {
    const home = sel.g.leg === "return";
    // `?:` binds looser than `||`, so the obvious one-liner leaves from_airport
    // reaching .trim() unguarded on the return. Parenthesise the branch.
    const port = ((home ? sel.row.from_airport : sel.row.to_airport) || "").trim();
    const stay = (t?.housing || []).filter(isCommitted)[0] || null;
    const ap = airportPt(port), sp = ptOf(stay);
    const drive = ap && sp ? `~${driveMin(ap, sp)} min` : "";
    // Every clock on this card is drawn against the day the LEG leaves, so a
    // figure on another date says which. A return that lands 00:59 the next
    // morning printed "12:59a" and read as the morning you left.
    const base = baseOf(sel.row.departure_time);
    const clk = (abs) => (abs == null || base == null) ? "" : dayClock(abs, base);
    const stayAt = (k) => clk(stay ? absOf(stay[k]) : null);
    const land = absOf(sel.row.arrival_time);
    const rows = [], out = { head: home ? "before you go" : "when you land", rows: rows, note: "" };

    if (home) {
      const car = bookedCar(t);
      // onCar answers whether you are ON the car's return, not whether returning
      // it is your job — trip 61's minivan was booked by Jasmine. So this is
      // shared logistics on the morning's clock, never a task assigned to you.
      const back = car && onCar(car, readerMember(t)) ? absOf(carDropoff(car)) : null;
      const dep = absOf(sel.row.departure_time);
      if (stayAt("check_out")) rows.push(["checkout", stayAt("check_out")]);
      if (back != null) rows.push(["car back by", clk(back)]);
      if (drive) rows.push([`to ${port || "the airport"}`, drive]);
      if (land != null) rows.push(["home", clk(land)]);
      if (back != null && dep != null && back < dep) {
        out.note = "The car is due back before the flight is, and that is what sets the morning.";
      }
      return out;
    }

    if (land != null) {
      rows.push(["wheels down", clk(land) + (port ? ` · ${port}` : "")]);
    }
    if (drive) rows.push(["to the stay", drive]);
    if (stayAt("check_in")) rows.push(["the house opens", stayAt("check_in")]);
    if (land != null) {
      const [label, what] = firstThing(t, land);
      rows.push([label, what]);
      const open = stay && absOf(stay.check_in);
      if (open != null && open > land) {
        out.note = `You are on the ground about ${dur(open - land)} before the house opens.`;
      }
    }
    return out;
  }

  // The first thing scheduled AFTER you land, which is not the day's earliest
  // block: Akshay gets in at 8:39p, and a noon activity rendered under his landing
  // as "first thing" is simply false. Read through itineraryModel so the rail and
  // the itinerary board cannot disagree about what is on a day — but over the
  // trip's whole range, because itineraryModel CLAMPS an out-of-range date into
  // the nearest column, so asking it for one day hands back every day.
  // Activities only: the logistics blocks it also carries are the flight you are
  // sitting on and the check-in this card already prints one row above.
  // biome-ignore lint/correctness/noUnusedFunctionParameters: t is unused, but dayofrail.selftest.js lifts this function by its exact signature text — renaming the param breaks the test's regex, not the code.
  function firstThing(t, land) {
    const day = absDate(land), mins = ((land % 1440) + 1440) % 1440;
    const col = itineraryModel(tripDays()).filter((d) => d.day === day)[0];
    const blocks = ((col?.blocks) || []).filter((b) => b.kind === "act" && b.pos != null);
    if (!blocks.length) return ["first thing", "nothing scheduled that day"];
    const next = blocks.filter((b) => b.pos >= mins)[0];
    const b = next || blocks[blocks.length - 1];
    const what = `${b.title} · ${T.fmtClock(b.pos)}`;
    return [next ? "first thing" : "earlier that day", what];
  }

  function farEndCard(t, sel) {
    const m = farEndRows(t, sel);
    if (!m.rows.length) return "";
    return `<div class="hub-detail-card"><div class="hub-detail-card-head ctx-card-head">${esc(m.head)}</div>${
      m.rows.map(([k, v]) => `<div class="hub-kv-row ctx-row"><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join("")}${
      m.note ? `<div class="ctx-sub">${esc(m.note)}</div>` : ""}</div>`;
  }

  // Two cards, and deliberately NOT one gate: card 2 is about your landing and
  // genuinely needs a leg, while card 1 is the crew picture, and a guest whose
  // ticket is not on the board yet is exactly the person who most needs to see
  // it. So they are independent builders and the rail is their concatenation.
  // biome-ignore lint/correctness/noUnusedVariables: unwired but kept for planned rework (see comment above) and lifted by exact-signature regex in dashboard/hub/tests/dayofrail.selftest.js; never rename or delete.
  function dayOfContext(sel) {
    const dir = sel ? (sel.g.leg === "return" ? "return" : "outbound") : defaultDir(state.trip);
    return crewTodayCard(state.trip, dir) + (sel ? farEndCard(state.trip, sel) : "");
  }

  // The clock nobody can move: when the house opens, when it closes, and how far
  // it is from the airport. These are the three facts the old prose sentence
  // carried, said as rows against the stay that is actually booked instead of as
  // two hardcoded constants and a guess.
  // The airport you actually land at. On a connection that is the LAST outbound
  // leg, not the first — the Columbus trip flies EWR → IAD → CMH, and reading
  // flights[0] told it the stay was 530 minutes from Dulles. The constant hid
  // that; a measured drive printed it. Read the same row the arrival read reads,
  // so the two cards cannot disagree about where you got off the plane.
  function arrivalPort(t) {
    const sel = readerLegs(t).filter((s) => s.leg === "outbound" || s.leg === "roundtrip")[0];
    if (sel && (sel.row.to_airport || "").trim()) return sel.row.to_airport.trim();
    const rows = (t.flights || []).filter((f) => (f.direction || "outbound") !== "return")
      .filter((f) => (f.to_airport || "").trim())
      .sort((a, b) => (absOf(a.arrival_time) || 0) - (absOf(b.arrival_time) || 0));
    return rows.length ? rows[rows.length - 1].to_airport.trim() : "";
  }
  function fixedCard(t) {
    const stay = chosenStay();
    if (!stay) return "";
    const addr = stay.address || "";
    const href = addr ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(addr)}` : "";
    const port = arrivalPort(t) || "the airport";
    const row = (k, v) => v ? `<div class="hub-kv-row ctx-row"><span>${esc(k)}</span><b>${esc(v)}</b></div>` : "";
    // a figure space before a one-digit hour, so "3:00p" and "12:00p" end on the
    // same column (mark 2026-10-14, "a place holder space")
    const clock = (v) => v ? stampShort(v).replace(/(^|\s)(\d:)/, "$1\u2007$2") : "";
    return `<div class="hub-detail-card"><div class="hub-detail-card-head ctx-card-head">fixed times</div>
      ${row("check-in", clock(stay.check_in))}
      ${row("checkout", clock(stay.check_out))}
      ${row(`${port} → ${stay.area || "the stay"}`, `~${driveMin(airportPt(port), ptOf(stay))} min`)}
      ${addr ? ctxLink(addr, href, "") : ""}</div>`;
  }
  function groundContext(t) {
    const sel = readerLegs(t);
    const reads = sel.length ? timelineReads(t, sel) : [];
    // A reader with no ticket on the board is told that, in their own terms — not
    // handed the owner's day with no word that it isn't theirs.
    const none = reads.length ? "" : `<div class="hub-detail-card"><div class="hub-detail-card-head ctx-card-head">your day</div>
      <div class="ctx-sub">${viewerFlightMissing(t)
        ? "your flight isn't on this board yet — forward the confirmation email to Sam and he'll add it"
        : "nothing on the board yet — the arrival and departure read lands once a leg has a fare"}</div></div>`;
    return none
      + (reads.length ? `<div class="tlgrid">${reads.map(dayReadHTML).join("")}</div>` : "")
      + carCard(t) + arrivalsCard(t) + fixedCard(t);
  }

  // The mask is a cosmetic fix for empty space, so it only earns its place when
  // there IS empty space. Measured, not assumed: content that fills the rail keeps
  // its last rows at full opacity.
  function fadeIfSlack(rail, c) {
    const slack = c.scrollHeight < rail.clientHeight - 24;
    rail.classList.toggle("context--summary", slack);
    // Start the fade where the CONTENT ends, not at a fixed 55% of the column.
    // The stop was tuned against two short cards; a rail carrying three tall
    // ones reaches past it and real rows get masked into the void the fade
    // exists to hide. Every caller gets this — it was never a cost-tab problem.
    if (slack) rail.style.setProperty("--ctx-fade",
      `${Math.min(100, (c.scrollHeight / Math.max(1, rail.clientHeight)) * 100 + 4).toFixed(1)}%`);
    else rail.style.removeProperty("--ctx-fade");
  }

  // The group read: what the crew agrees on, where they split, and what would
  // sink the trip. Every field here comes straight off /preferences — the spreads
  // and alignment scoring are computed server-side in preferences.py.
  function crewContext() {
    const p = state.prefs;
    if (!p) return `<div class="hub-detail-card"><div class="ctx-sub">${prefsWait()}</div></div>`;
    const ag = p.aggregate || {};
    const linked = (p.members || []).length;
    const unlinked = p.members_without_contact || [];
    // With nobody on the trip the rollups are all "unrated" — six rows of nothing
    // dressed up as data. Say the actual state instead.
    if (!(state.trip.members || []).length) {
      return `<div class="hub-detail-card"><div class="hub-detail-card-head ctx-card-head">crew</div>
        <div class="ctx-big">0</div>
        <div class="ctx-sub">nobody on this trip yet — the group read fills in as you add people</div></div>`;
    }

    // One row shape for both ratings grids — the travel form's six interests and
    // the food form's thirteen cuisines are the same must→hate question asked
    // about different things, and they read the same way in the rail.
    // The verdict is a FLOOR, and a floor makes a bad badge: five musts and one
    // want floors to the same "shared want" as one must and five wants, so the
    // interests card printed the identical pill on four of its six rows and
    // ranked Music under Arts while two people were pulling for it. Only
    // `everyone-must` and `vetoed` are absolute enough to stay words. Everything
    // between them badges heads — how hard, how many, how many against — and both
    // cards sort on appetite so the order carries what one badge cannot. A row
    // nobody rated either way keeps the floor's word; there are no heads to count.
    const VERDICT_TONE = { "everyone-must": "good", "shared-want": "good", appetite: "good", "someone-rather-not": "warn", vetoed: "alert" };
    const gridRow = (key, LABELS) => (i) => {
      const per = Object.entries(i.per_member || {});
      const who = per.map(([n, r]) => `${n}: ${label(key, r)}`).join("\n");
      const mustN = per.filter(([, r]) => r === "must").length;
      const forN = per.filter(([, r]) => r === "must" || r === "want").length;
      const noN = per.filter(([, r]) => r === "rather-not" || r === "hate").length;
      const absolute = i.verdict === "everyone-must" || i.verdict === "vetoed";
      const cls = absolute || noN ? i.verdict : (forN > 1 ? "appetite" : "");
      const badge = absolute || !(forN || noN)
        ? (LABELS[i.verdict] || i.verdict)
        : `${mustN ? `${mustN} must · ` : ""}${forN} for${noN ? ` · ${noN} no` : ""}`;
      // appetite is a head count: nobody objected and more than one is pulling for it
      const tone = VERDICT_TONE[cls] ? ` is-${VERDICT_TONE[cls]}` : "";
      return `<div class="hub-kv-row ctx-row" title="${esc(who)}"><span>${esc(i.tag)}</span>
        <span class="verdict hub-pill${tone}">${esc(badge)}</span></div>`;
    };
    // Six tags always render — silence on the travel form counts as neutral, not
    // as an objection — so this one sorts without filtering.
    const interests = (ag.interests || []).slice()
      .sort((a, b) => b.score - a.score)
      .map(gridRow("interests", INTEREST_VERDICT_LABEL)).join("");

    // Thirteen cuisines is a wall, and the two rows that decide a dinner are
    // "what does this crew want" and "what will somebody refuse". So the card is
    // appetite-ordered, not verdict-ordered: every cuisine the group is net
    // positive on, plus anything carrying a hate, which the score sinks to the
    // bottom on its own. The other eight — the all-neutrals and the ones one
    // person soured — are the null result, and they stay on the member rails
    // where the full per-person spread belongs.
    const cuisines = (ag.cuisines || [])
      .filter((c) => c.score > 0 || c.verdict === "vetoed")
      .sort((a, b) => b.score - a.score)
      .map(gridRow("cuisines", CUISINE_VERDICT_LABEL)).join("");

    // A spread is only worth a row if somebody answered; "n/a" rows are filler.
    // `lbl` is per-question because the food form reuses raw values the travel
    // form also uses ("none", "any", "hard-no") and they read differently there.
    // The words, and under them the scale they sit on. The words alone could not
    // say how far apart the crew actually is: "mild → very-hot" spans four of the
    // five stops and "balanced → very-adventurous" spans three, and both printed
    // the identical word "diverging", because alignment tops out at "2 or more
    // apart". The track is the magnitude the badge cannot carry.
    // `key` is the question, and it is now the only thing a row needs: the words,
    // the track and the tooltip all come off it, so a row cannot label itself with
    // one question's vocabulary and draw another's scale. Each caller used to pass
    // a label function AND the key, which is two chances to pass the wrong pair.
    const spreadRow = (caption, v, key) => {
      if (!v?.min_value) return "";
      const lbl = (raw) => label(key, raw);
      // Includes the members _spread could not rank (depends / other) — they are
      // absent from the range on purpose, so the tooltip is where they show up.
      const who = (v.per_member || []).map((x) => `${x.member}: ${lbl(x.value) || "—"}`).join("\n");
      const val = v.min_value === v.max_value
        ? lbl(v.min_value)
        : `${lbl(v.min_value)} → ${lbl(v.max_value)}`;
      const track = CC.strack(key, v.min_value, v.max_value);
      return `<div class="hub-kv-row ctx-row ctx-row-scale" title="${esc(who)}"><span>${esc(caption)}</span>
        <span class="align align-${esc(v.alignment || "unknown")}">${esc(val)}</span>
        ${track}</div>`;
    };
    const pace = ag.pace || {}, food = ag.food || {};
    const rhythm = [
      spreadRow("active hours", pace.active_hours, "active_hours"),
      spreadRow("start time", pace.start_time, "start_time"),
      spreadRow("chill days", pace.chill_days, "chill_days"),
    ].join("");
    // How the crew eats, in the order a meal actually gets decided: what kind of
    // food, how hot, how the table works, what it costs, where, and whether it
    // needs booking. `meals` is the travel form's question, but it is a food
    // fact — it belongs with the rest of them, not stranded in rhythm.
    const foodRows = [
      spreadRow("food style", food.adventure, "adventure"),
      spreadRow("spice", food.spice, "spice"),
      spreadRow("sharing", food.sharing, "sharing"),
      spreadRow("spend pp", food.spend, "spend"),
      spreadRow("goes for", food.venue, "venue"),
      spreadRow("booking", food.reservations, "reservations"),
      spreadRow("drinks", food.alcohol, "alcohol"),
      spreadRow("group meals", food.meals, "meals_coordinated"),
    ].join("");
    // An empty food card has two very different causes and they are not the same
    // news: nobody has filled the form, or they filled it and every answer was
    // unrankable. A partial read says so rather than passing two voices off as
    // the whole crew's.
    const answered = ag.food_responses || 0;
    const crewSize = (state.trip.members || []).length;
    const foodNone = answered ? "answered, but nothing lands on a scale yet" : "nobody has filled the food form yet";
    const foodPartial = answered && answered < crewSize
      ? `<div class="ctx-sub">${answered} of ${crewSize} filled the food form</div>` : "";

    const warn = (rows, kind) => (rows || []).map((d) =>
      `<div class="warnrow warnrow-${kind}"><b>${esc(shortName(d.member))}</b> ${esc(d.text)}</div>`).join("");
    const flags = warn(ag.dealbreakers, "no") + warn(ag.diet_restrictions, "diet") + warn(ag.physical_limits, "limit");

    return `
      <div class="hub-detail-card"><div class="hub-detail-card-head ctx-card-head">crew</div>
        <div class="ctx-big">${(state.trip.members || []).length}</div>
        <div class="ctx-sub">${linked} with travel profiles${unlinked.length ? ` · ${unlinked.length} unlinked` : ""}</div>
        ${unlinked.length ? `<div class="ctx-sub ctx-sub-warn">no form yet: ${esc(unlinked.map((u) => shortName(u.name)).join(", "))}</div>` : ""}</div>
      <div class="hub-detail-card"><div class="hub-detail-card-head ctx-card-head">shared interests</div>${interests || `<div class="ctx-sub">no data</div>`}</div>
      <div class="hub-detail-card"><div class="hub-detail-card-head ctx-card-head">rhythm</div>${rhythm || `<div class="ctx-sub">no data</div>`}</div>
      <div class="hub-detail-card"><div class="hub-detail-card-head ctx-card-head">cuisines</div>${cuisines
        || `<div class="ctx-sub">${answered ? "nobody is pulling for a cuisine and nobody is refusing one" : foodNone}</div>`}</div>
      <div class="hub-detail-card"><div class="hub-detail-card-head ctx-card-head">food</div>${foodPartial}${foodRows
        || `<div class="ctx-sub">${foodNone}</div>`}</div>
      <div class="hub-detail-card"><div class="hub-detail-card-head ctx-card-head">flags</div>${flags || `<div class="ctx-sub">nothing flagged</div>`}</div>`;
  }

  // ── helpers: days / scheduling ───────────────────────────────────────────────
  function tripDays() {
    const t = state.trip;
    return t ? T.dayRange(t.start_date, t.end_date) : [];
  }
  // Ordered by parsed time, not raw string — sorting "1:00 PM" against
  // "11:00 AM" as text is what used to put the wrong item here.
  function nextScheduled() {
    const list = (state.trip.activities || [])
      .filter((a) => a.status === "scheduled" && a.scheduled_date)
      .sort(T.byDateTime);
    return list[0] || null;
  }

  // ── writes: activities ───────────────────────────────────────────────────────
  function reload() { const id = state.trip.id; return API.get(`/trips/${id}`).then((trip) => { state.trip = trip; statusCounts("loaded"); renderAll(); }); }
  function patchActivity(id, body, msg) {
    return API.patch(`/trips/${state.trip.id}/activities/${id}`, body).then(() => reload()).then(() => { if (msg) toast(msg); })
      .catch((e) => { toast(`update failed — ${errMsg(e)}`); });
  }
  function delActivity(a) { return confirmDelete(a.name, () => API.del(`/trips/${state.trip.id}/activities/${a.id}`)); }

  // ── deletes ──────────────────────────────────────────────────────────────────
  // Every detail pane had a delete button calling this, and it was never defined —
  // so all four of them threw ReferenceError and nothing in the planner could be
  // deleted from the UI at all. The server endpoints were there the whole time.
  function confirmDelete(name, run) {
    return confirmDialog("delete", `Delete "${name}"? This can't be undone.`,
      { danger: true, confirmLabel: "delete" }).then((ok) => {
      if (!ok) return false;
      return Promise.resolve().then(() => run()).then(() => {
        state.selId = null;               // the detail rail was showing the row that just went
        return reload();
      }).then(() => {
        toast("deleted");
        return true;
      }).catch((e) => { toast(`delete failed — ${errMsg(e)}`); return false; });
    });
  }
  // One affordance for every list surface. `path` is the API tail after the trip
  // (`flights/12`, `expenses/4`), which is exactly what the row ids already encode.
  const delBtn = (path, label) => `<button class="hub-row-delete rdel" data-del="${esc(path)}" data-dellabel="${esc(label)}"
    title="delete ${esc(label)}" aria-label="delete ${esc(label)}">×</button>`;
  function bindDeletes(root) {
    root.querySelectorAll("[data-del]").forEach((b) => {
      b.onclick = (e) => {
        e.stopPropagation();            // a delete is not a row selection
        confirmDelete(b.dataset.dellabel, () => API.del(`/trips/${state.trip.id}/${b.dataset.del}`));
      };
    });
  }

Object.assign(U, { listWeather, listPacking, renderContext, ctxLink, groundContext, tripDays, reload,
  patchActivity, delActivity, confirmDelete, delBtn, bindDeletes });
})();
