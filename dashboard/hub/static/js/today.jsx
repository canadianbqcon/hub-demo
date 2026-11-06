/* Home today-briefing · 4 of 4: the today zone itself: computeTodayView, the header, and the three column caps.

   Split from today.jsx 2026-07-29 (1065 lines), which was itself split out of
   chrome.jsx the same day. index.html loads the four in this order and each is
   its own Babel script with its own scope, so every name another file needs is
   handed over explicitly through the Object.assign at the bottom, the same
   pattern chrome.jsx uses. React hooks are re-destructured per file for the
   same reason.
*/

const { useState, useEffect } = React;

function computeTodayView({ now, schedule, wx, tasks, cards, snapshots, selectedIso, todayIso }) {
  const BL = window.BriefingLogic;
  const localDay = (dt) => `${dt.getFullYear()}-${String(dt.getMonth()+1).padStart(2,"0")}-${String(dt.getDate()).padStart(2,"0")}`;
  const tIso = todayIso || localDay(now);
  const selIso = selectedIso || tIso;
  const isToday = selIso === tIso;

  const events = eventsForDay(schedule, selIso);
  const agg = BL ? BL.aggregateLabels(events) : { bring: [], prep: [], leave: [], note: [] };
  const due = BL ? BL.selectDueItemsForDay(tasks, cards, selIso, tIso) : { tasks: [], cards: [] };
  // the week after the selected day, so the due card shows what is coming and not one row in a big box
  const soon = !BL ? [] : [
    ...(tasks || []).filter((t) => !t.done && t.due_target).map((t) => ({ key: `t${t.id}`, label: t.title || t.name, d: BL.dayOffset(selIso, BL.localDayString(t.due_target)) })),
    ...(cards || []).filter((c) => c.due_in_days != null).map((c) => ({ key: `c${c.name}`, label: c.name, d: c.due_in_days - BL.dayOffset(tIso, selIso) })),
  ].filter((x) => x.d >= 1 && x.d <= 14).sort((a, b) => a.d - b.d);
  // the next day in the coming week with prep on its calendar, and the next place to be
  const ahead = BL ? Array.from({ length: 7 }, (_, i) => {
    const iso = BL.addDays(selIso, i + 1), evs = eventsForDay(schedule, iso);
    return { d: i + 1, prep: BL.aggregateLabels(evs).prep, out: evs.find((e) => (e.location || "").trim() && !e.rolled) };
  }) : [];
  const nextPrep = ahead.find((a) => a.prep.length) || null;
  const nextOutDay = ahead.find((a) => a.out) || null;
  const snap = (snapshots?.[selIso]) || null;
  const dayWx = ((wx?.byDate?.[selIso]) || snap) || null;
  const wlabel = dayWx ? (WMO_LABEL[dayWx.code] || "") : "";
  // 24-hour rail: the selected day's own slice of the flat hourly series plus
  // that day's rain ceiling, and (on today only) where "now" falls across the
  // day as a 0-1 fraction. Derived here because only this function sees the
  // whole wx. A past day uses its snapshot's stored hours (31 days back).
  // A past day reads the hourly row its snapshot stored (kept 31 days).
  const liveRail = BL ? BL.dayRail(wx?.hours, selIso) : { hours: [], max: 0 };
  const rail = !liveRail.hours.length && BL && snap?.hours ? BL.dayRail(snap.hours, selIso) : liveRail;
  const nowFrac = isToday ? (now.getHours() + now.getMinutes() / 60) / 24 : null;
  const bringItems = mergedBringWithSnapshot(agg.bring, dayWx, snap);
  const prepItems = unionLabels(agg.prep, snap ? snap.prep : null);

  // Rain in words, and the forecast at the two moments that matter: when the
  // first timed event starts (leaving) and when the last one ends (coming back).
  // Rolled events belong to the prior night, so they set neither.
  const precip = BL ? BL.precipWords(rail.hours) : { kind: "dry", text: "" };
  let leaveMin = null, returnMin = null;
  for (const e of events) {
    if (e.rolled) continue;
    const t = dayEvMin(e);
    if (!t) continue;
    if (leaveMin == null || t.start < leaveMin) leaveMin = t.start;
    if (returnMin == null || t.end > returnMin) returnMin = t.end;
  }
  const leaveRead = BL && leaveMin != null ? BL.readingAt(rail.hours, leaveMin) : null;
  const returnRead = BL && returnMin != null ? BL.readingAt(rail.hours, returnMin) : null;
  // the week ahead, today first, straight off the daily forecast
  const week = [];
  // a past day shows only its own weather, not the week ahead (2026-11-03 mark)
  if (BL && wx?.byDate && selIso >= tIso) {
    for (let i = 0; i < 7; i++) {
      const iso = BL.addDays(tIso, i);
      const d = wx.byDate[iso];
      if (d) week.push({ iso, ...d });
    }
  }

  // header date fields derive from the selected day; the %-of-day bar uses the
  // live clock and only renders on today (see TodayHeader).
  const weekdays = ["sunday","monday","tuesday","wednesday","thursday","friday","saturday"];
  const months = ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"];
  const selDate = new Date(`${selIso}T00:00:00`);
  const onejan = new Date(selDate.getFullYear(), 0, 1);
  const wk = Math.ceil((((selDate - onejan) / 86400000) + onejan.getDay() + 1) / 7);
  const { doy, daysInYear } = BL ? BL.dayOfYear(selDate) : { doy: 0, daysInYear: 0 };

  // Day navigation. Forward stops at the +7 forecast horizon; backward is
  // unbounded over the durable record (any earlier day with a frozen snapshot).
  const offset = BL ? BL.dayOffset(tIso, selIso) : 0;
  const prevHasSnap = !!(snapshots && BL && snapshots[BL.addDays(selIso, -1)]);
  const canPrev = offset > -7 || prevHasSnap;
  const canNext = offset < 7;
  const navLabel =
    offset === 0 ? "today" :
    offset === -1 ? "yesterday" :
    offset === 1 ? "tomorrow" :
    weekdays[selDate.getDay()];

  return {
    BL, tIso, selIso, isToday, events, agg, due, snap, dayWx, wlabel, rail, nowFrac,
    bringItems, prepItems, soon, nextPrep, nextOutDay,
    precip, leaveMin, returnMin, leaveRead, returnRead, week, wx,
    weekdays, months, selDate, wk, doy, daysInYear, canPrev, canNext, navLabel,
    hasSnap: (d) => !!(snapshots && snapshots[d]),
  };
}

/* Week strip at the top of the today panel: seven day chips between two arrows
   that roll the week back or forward. Forward stops at the week holding today;
   a chip past the +7 forecast horizon, or older than a week with no frozen
   snapshot, is disabled (the canPrev / canNext bounds). Today's chip reads
   "today" and keeps its accent dot. */
function WeekStrip({ view, onSelectDay }) {
  const BL = view && view.BL;
  const { tIso, selIso, weekdays, months, hasSnap } = view || {};
  // The strip shows the week holding the selected day: page 0 starts on today.
  const page = BL ? Math.floor(BL.dayOffset(tIso, selIso) / 7) : 0;
  if (!BL) return null;
  const start = BL.addDays(tIso, page * 7);
  const days = Array.from({ length: 7 }, (_, i) => BL.addDays(start, i));
  // Same bounds as computeTodayView's canPrev / canNext.
  const reachable = (d) => { const o = BL.dayOffset(tIso, d); return o <= 7 && (o >= -7 || hasSnap(d)); };
  // The arrows step the selected day, not the week (2026-10-20 mark); the strip
  // follows the selection into the next week through the effect above.
  const prevD = BL.addDays(selIso, -1), nextD = BL.addDays(selIso, 1);
  const dn = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
  // Off today, a where-you-are line under the strip carries the way back
  // (2026-11-03 Workbench pick A, snap-to-today; replaced the in-strip chip).
  const off = BL.dayOffset(tIso, selIso);
  const sd = new Date(`${selIso}T00:00:00`);
  const ago = off === -1 ? "yesterday" : off === 1 ? "tomorrow" : off < 0 ? `${-off} days ago` : `in ${off} days`;
  return (
    <>
    <nav className="week-strip" aria-label="day">
      <button type="button" className="hub-btn ws-step" aria-label="previous day" disabled={!reachable(prevD)}
        onClick={() => onSelectDay(prevD)}>‹</button>
      {days.map((d) => {
        const dt = new Date(`${d}T00:00:00`);
        const isT = d === tIso;
        return (
          <button key={d} type="button" className={`ws-chip${isT ? " is-today" : ""}`} aria-pressed={d === selIso}
            disabled={!reachable(d)}
            aria-label={`${isT ? "today, " : ""}${weekdays[dt.getDay()]} ${months[dt.getMonth()]} ${dt.getDate()}`}
            onClick={() => onSelectDay(d)}>
            <span className="ws-d">{isT ? <><span className="ws-today">today</span><span className="ws-wd">{dn[dt.getDay()]}</span></> : dn[dt.getDay()]}</span>
            <span className="ws-n">{dt.getDate()}</span>
          </button>
        );
      })}
      <button type="button" className="hub-btn ws-step" aria-label="next day" disabled={!reachable(nextD)}
        onClick={() => onSelectDay(nextD)}>›</button>
    </nav>
    {off !== 0 ? (
      <div className="ws-where">
        <span className="ws-where-at">viewing {weekdays[sd.getDay()].slice(0, 3)} {months[sd.getMonth()]} {sd.getDate()} · {ago}</span>
        <button type="button" className="hub-btn ws-back" onClick={() => onSelectDay(tIso)}>back to today <span aria-hidden="true">›</span></button>
      </div>
    ) : null}
    </>
  );
}

/* Full-width header below the topbar: weekday and date meta. Replaces the old AlwaysSeeTab handle. */
function TodayHeader({ view, now, schedule, wx, todayIso }) {
  const BL = window.BriefingLogic;
  // Freeze today's briefing: once the forecast + events are loaded, persist today's
  // forecast + merged bring/prep so a past day keeps them after rollover. Only
  // today is ever sent (the server also keys on its own local day). Idempotent
  // upsert; re-fires when schedule/weather/day change, NOT on the 1s clock tick
  // (deps use todayIso, which only flips at midnight). Lives here because this is
  // the one today-zone component that always mounts. Hook precedes any early return.
  useEffect(() => {
    if (!BL) return;
    const tIsoNow = todayIso || BL.localDayString(now);
    const fwx = (wx?.byDate?.[tIsoNow]) || null;
    if (!fwx) return; // wait for the first weather response
    const a = BL.aggregateLabels(eventsForDay(schedule, tIsoNow));
    const bring = mergedBring(a.bring, fwx).map((b) => b.label);
    fetch("/api/briefing/snapshot", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // the day's own hourly row rides along, so a past day can show it (kept 31 days)
      body: JSON.stringify({ forecast: { ...fwx, hours: BL.dayRail(wx.hours, tIsoNow).hours }, bring, prep: a.prep }),
    }).catch(() => {});
  }, [BL, schedule, wx, todayIso]);

  if (!view || !BL) return null;
  const { selDate, weekdays, months, wk, doy, daysInYear } = view;
  return (
    <header className="today-header">
      <div className="th-date">
        <div className="th-weekday">
          <span className="tb-weekday-name">{weekdays[selDate.getDay()]}</span>
        </div>
        <div className="tb-datemeta">{months[selDate.getMonth()]} {selDate.getDate()} · week {wk} · day {doy}/{daysInYear}</div>
      </div>
    </header>
  );
}

/* Day-scoped checkmark state (bring / prep / due-card) persists to one localStorage
   key per day. bring now lives in a different column from due/prep, so two components
   write the same key — persist via read-modify-write so neither clobbers the other's
   checks. */
function tbDoneKey(dayStr) { return `hub.tb.done.${dayStr}`; }
function readTbDone(dayStr) {
  try { const a = JSON.parse(localStorage.getItem(tbDoneKey(dayStr))); return new Set(Array.isArray(a) ? a : []); }
  catch { return new Set(); }
}
function toggleTbDone(dayStr, k) {
  const cur = readTbDone(dayStr);
  if (cur.has(k)) cur.delete(k); else cur.add(k);
  try { localStorage.setItem(tbDoneKey(dayStr), JSON.stringify([...cur])); } catch {}
  return cur;
}

/* Weather block: the top of the two-column box beside the schedule, the first
   thing on a morning glance. Five tiers, quietest-last:
     1. hero     — the reading, big (--wx-hero), with condition + H/L/feels beside it,
                   and the day's rain IN WORDS (how heavy, when, how much) on the right
     2. today    — the standing readings: humidity, air quality, pollen, wind, uv, sun
     3. cells: twelve two-hour cells (time, temp, rain chance; rain fills the cell),
                   the current slot ringed on today
     4. trips    — the forecast at the moment he leaves and the moment he is back
     5. week     — seven days, today first
   Tiers 2-5 self-hide when their data is absent, which is exactly the case for a
   PAST day: briefing_snapshot freezes only temp/code/hi/lo/precip. */
function DayWeather({ view }) {
  const BL = window.BriefingLogic;
  if (!view || !BL) return null;
  const { dayWx, wlabel, isToday, rail, nowFrac, precip, leaveMin, returnMin, leaveRead, returnRead, week, wx } = view;
  if (!dayWx) {
    return (
      <section className="day-weather" aria-label="weather">
        <p className="wx-void">{isToday ? "weather unavailable" : "no forecast"}</p>
      </section>
    );
  }
  const feelsOff = dayWx.feels != null && dayWx.temp != null && Math.abs(dayWx.feels - dayWx.temp) >= 3;
  const sunrise = BL.clockLabel(dayWx.sunrise);
  const sunset = BL.clockLabel(dayWx.sunset);
  const hasRail = !!(rail && rail.hours.length > 1);
  const isWet = precip && (precip.kind === "rain" || precip.kind === "snow");
  // A past day has only the frozen daily chance, so the words fall back to it.
  const precipText = hasRail ? (precip?.text) : (dayWx.precip ? `${dayWx.precip}% chance of rain` : "");

  // Tier 2: the day's standing conditions. Humidity is the live reading on
  // today and the noon hour on a forecast day; air and pollen are today-only
  // (they are current readings with no forecast series behind them).
  const noon = hasRail ? (rail.hours.find((h) => h.hour === 12) || {}) : {};
  const hum = dayWx.hum != null ? dayWx.hum : noon.hum;
  const cond = [];
  if (hum != null) cond.push(["humidity", `${hum}%`]);
  if (isToday && wx && wx.aqi != null) cond.push(["air", `${wx.aqi} ${BL.aqiWords(wx.aqi)}`]);
  if (isToday && wx?.pollen) {
    const pl = wx.pollen;
    const trig = pl.triggers?.length ? ` (${pl.triggers.slice(0, 2).join(", ").toLowerCase()})` : "";
    cond.push(["pollen", `${pl.index} ${pl.level}${trig}`]);
  }
  if (dayWx.wind != null) cond.push(["wind", `${dayWx.wind} mph`]);
  if (dayWx.uv != null) cond.push(["uv", String(dayWx.uv)]);
  if (sunrise && sunset) cond.push(["sun", `${sunrise}–${sunset}`]);

  // twelve two-hour cells. Today they start at the current slot ("now") and run
  // 24 hours ahead into tomorrow; other days show midnight to midnight.
  const nowH = nowFrac != null ? Math.floor((nowFrac * 24) / 2) * 2 : null;
  const all = wx?.hours || [];
  const from = isToday && nowH != null ? all.findIndex((h) => h.iso.slice(0, 10) === rail.hours[0]?.iso.slice(0, 10) && h.hour === nowH) : -1;
  const cells = !hasRail ? []
    : from >= 0 ? all.slice(from).filter((h) => h.hour % 2 === 0).slice(0, 12)
    : rail.hours.filter((h) => h.hour % 2 === 0);
  // The forecast at the moment he leaves and the moment he is back.
  const tripLine = (label, read, m) => {
    if (!read) return null;
    const bits = [];
    if (read.temp != null) bits.push(`${read.temp}°`);
    if ((read.precip || 0) >= 30) bits.push(`${read.precip}% rain`);
    else if (read.code != null && WMO_LABEL[read.code]) bits.push(WMO_LABEL[read.code]);
    return (
      <span key={label}>
        <span className="wx-trip-k">{label}</span> {dayFmtMin(m)} <span className="t-num">{bits.join(", ")}</span>
      </span>
    );
  };
  const trips = [tripLine("leave", leaveRead, leaveMin), tripLine("back", returnRead, returnMin)].filter(Boolean);
  const dows = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
  // the hours a cell draws a moon instead of a sun: before sunrise, from sunset on
  const hourOf = (iso, dflt) => { const m = /T(\d{2})/.exec(iso || ""); return m ? +m[1] : dflt; };
  const sunUpH = hourOf(dayWx.sunrise, 7), sunDownH = hourOf(dayWx.sunset, 19);
  const weekLo = week ? Math.min(...week.map(d => d.lo)) : 0, weekHi = week ? Math.max(...week.map(d => d.hi)) : 0;
  const weekSpan = Math.max(1, weekHi - weekLo);

  return (
    <section className="day-weather" aria-label="weather">
      <div className="wx-hero">
        <span className="wx-temp t-num">{dayWx.temp}°</span>
        <div className="wx-hero-side">
          <span className="wx-cond">{wlabel}</span>
          {(dayWx.hi != null || dayWx.lo != null || feelsOff) ? (
            <span className="wx-temps t-num">
              {dayWx.hi != null ? <span>H {dayWx.hi}°</span> : null}
              {dayWx.lo != null ? <span>L {dayWx.lo}°</span> : null}
              {feelsOff ? <span className="wx-feels">feels {dayWx.feels}°</span> : null}
            </span>
          ) : null}
        </div>
        {precipText ? (
          <p className={`wx-precip${isWet ? " is-wet" : ""}`}>{precipText}</p>
        ) : null}
      </div>
      {cond.length ? (
        <p className="wx-cond-meta t-num">
          {cond.map(([k, v]) => <span key={k}><span className="wx-k">{k}</span> {v}</span>)}
        </p>
      ) : null}
      <div className="wx-fc">
      {cells.length ? (
        <ol className="wxh t-num" aria-label={from >= 0 ? "the next 24 hours, every two hours" : "the day every two hours"}>
          {cells.map((h, i) => (
            <li key={h.iso} className={from >= 0 && i === 0 ? "is-now" : ""} style={{ "--p": `${h.precip || 0}%` }}
                title={`${BL.hourLabel(h.hour)}: ${h.temp}°, ${h.precip || 0}% chance of rain`}>
              <span className="wxh-h">{from >= 0 && i === 0 ? "now" : BL.hourLabel(h.hour)}</span>
              <WxGlyph code={h.code} night={h.hour < sunUpH || h.hour >= sunDownH} />
              <span className="wxh-t">{h.temp}°</span>
              <span className="wxh-r">{(h.precip || 0) >= 20 ? `${h.precip}%` : ""}</span>
            </li>
          ))}
        </ol>
      ) : null}
      {week && week.length > 1 ? (
        <ol className="wx-week t-num" aria-label="the week ahead">
          {week.map((d, i) => (
            <li key={d.iso} className={i === 0 ? "is-today" : ""} title={WMO_LABEL[d.code] || ""}>
              <span className="wx-week-d">{i === 0 ? "today" : dows[new Date(`${d.iso}T00:00:00`).getDay()]}</span>
              <WxGlyph code={d.code} />
              <span className="wx-week-r">{d.precip >= 30 ? `${d.precip}%` : ""}</span>
              <span className="wx-week-lo">{d.lo}°</span>
              {/* the day's low-to-high span on one scale for the whole week */}
              <span className="wx-week-bar"><i style={{ left: `${(d.lo - weekLo) / weekSpan * 100}%`, right: `${(weekHi - d.hi) / weekSpan * 100}%` }} /></span>
              <span className="wx-week-t">{d.hi}°</span>
            </li>
          ))}
        </ol>
      ) : null}
      </div>
      {trips.length ? <p className="wx-trips">{trips}</p> : null}
    </section>
  );
}

/* "getting there": the next place he has to be, the actual trains and buses that
   get him there, the three ways to ride, and the subway lines that matter today.
   Destinations are today's calendar locations; the Hub geocodes them and hands
   back the point he is starting from — his own door, or the housing of whatever
   trip covers today (transit.py, origin()). The routes themselves come from the
   self-hosted router the trips board uses, asked to ARRIVE BY the event's start
   rather than to leave now (trips/MOTIS.md). Alerts are still scoped to the stops
   on the trip, in the direction of travel. Alerts and the lines row are today
   only; a later day still gets its routes, from where he is staying that day. */
const LINE_COLORS = {
  "1": "#EE352E", "2": "#EE352E", "3": "#EE352E", "4": "#00933C", "5": "#00933C", "6": "#00933C",
  "7": "#B933AD", A: "#0039A6", C: "#0039A6", E: "#0039A6", B: "#FF6319", D: "#FF6319", F: "#FF6319", M: "#FF6319",
  G: "#6CBE45", J: "#996633", Z: "#996633", L: "#A7A9AC", N: "#FCCC0A", Q: "#FCCC0A", R: "#FCCC0A", W: "#FCCC0A", S: "#808183",
};
// Letter colour for a bullet: white when it reads at AA (4.5) on the line colour, black when not
// (the lime G, the orange B and the yellow N/Q/R/W fail with white).
function lineInk(bg) {
  const L = window.hexLuminance(bg);
  if (L == null) return "#fff";
  return 1.05 / (L + 0.05) >= 4.5 ? "#fff" : "#000";
}
function LineBullet({ line, hit }) {
  const bg = LINE_COLORS[line] || "#808183";
  return (
    <span className={`gt-line${hit ? " is-hit" : ""}`}
          style={{ background: bg, color: lineInk(bg) }}>{line}</span>
  );
}

/* One leg of a route. A subway line is its roundel; a bus is its number in the
   MTA's bus blue — never a subway colour, or a B43 reads as the 1/2/3. Colours
   come from the router, which already normalises the feed's muted palette to the
   one on the signs (trips/api.py, _line_color). A walk is minutes, not a chip:
   the chips are things you board and a walk is the gap between them. Spelled out
   as a walker glyph plus "13m": a bare 13′ read as an unexplained number, and the
   word "walk" was too long for an action (2026-10-21 mark, sent back). Glyph is
   Material's directions_walk (Apache 2.0). */
const WALK_D = "M13.5 5.5c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zM9.8 8.9L7 23h2.1l1.8-8 2.1 2v6h2v-7.5l-2.1-2 .6-3C14.8 12 16.8 13 19 13v-2c-1.9 0-3.5-1-4.3-2.4l-1-1.6c-.4-.6-1-1-1.7-1-.3 0-.5.1-.8.1L6 8.3V13h2V9.6l1.8-.7";
function LegChip({ leg }) {
  const mins = Math.round((leg.dur || 0) / 60);
  if (!leg.transit) return (
    <span className="gt-leg-walk t-num" title={`walk ${mins} min`} aria-label={`walk ${mins} minutes`}>
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d={WALK_D} fill="currentColor" /></svg>{mins}m
    </span>
  );
  const wide = (leg.line || "").length > 2;
  return (
    <span className={`gt-line${wide ? " is-wide" : ""}`}
          style={{ background: leg.color || "#808183", color: lineInk(leg.color || "#808183") }}
          title={`${leg.line} ${leg.headsign ? `→ ${leg.headsign}` : ""} · ${leg.from} → ${leg.to} · ${mins} min`}>
      {leg.line || leg.mode.toLowerCase()}
    </span>
  );
}
function GettingThere({ view, now }) {
  const isToday = view?.isToday;
  const events = (view?.events) || [];
  const nowMin = now.getHours() * 60 + now.getMinutes();
  // every location on today's calendar, deduped, in order; drives the fetch
  const dests = [];
  for (const e of events) {
    const loc = (e.location || "").trim();
    if (loc && !dests.includes(loc) && !e.rolled) dests.push(loc);
  }
  const key = dests.join("|");
  const [tr, setTr] = useState(null);
  // Every hook must run before any early return — a hook
  // placed after it renders on today but not on other days, so switching days
  // trips React's "fewer hooks than expected" (#300) and unmounts the page.
  const [showAll, setShowAll] = useState(false);
  const [routes, setRoutes] = useState(null);
  const [feedsEnded, setFeedsEnded] = useState(null);
  /* The SUBWAY lines the router put him on, once it has answered. They go back up
     with the next alert fetch, which then watches each of them end to end instead
     of guessing from the station nearest the destination — the card was calling
     good service on the N while the route rode the 2 and the F. Subway only: the
     alert feed is the subway's, so a bus number in this list would be watched by
     nothing and still say "good service". */
  const riding = routes && isToday
    ? Array.from(new Set(routes.flatMap((it) =>
        it.legs.filter((l) => l.transit && l.mode === "SUBWAY" && l.line).map((l) => l.line))))
    : [];
  const ridingKey = riding.join(",");
  // fetched on today and later days (a later day needs the geo for its ride links), polled
  // only on today; a past day has no next place, so nothing to ask
  const past = !isToday && !(view?.selIso > view?.tIso);
  useEffect(() => {
    if (past || !dests.length) return;
    let cancelled = false;
    const q = dests.map((d) => `dest=${encodeURIComponent(d)}`)
      .concat(riding.map((l) => `line=${encodeURIComponent(l)}`))
      .concat(isToday ? [] : [`day=${view.selIso}`]).join("&");
    const load = () => fetch(`/api/transit?${q}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => { if (!cancelled && d) setTr(d); })
      .catch(() => {});
    load();
    const id = isToday ? setInterval(load, 5 * 60 * 1000) : null;
    return () => { cancelled = true; clearInterval(id); };
  }, [key, ridingKey, isToday, past, view?.selIso]);

  // the next place: first event with a location that has not ended yet.
  // Computed above the render because the routes hook below
  // needs it, and every hook has to run on every day (React #300).
  const next = events.find((e) => {
    if (e.rolled || !(e.location || "").trim()) return false;
    const t = dayEvMin(e);
    // today: not ended yet; a later day: all of it; an earlier day: none
    return t && (isToday ? t.end > nowMin : view.selIso > view.tIso);
  });
  const geo = next && tr ? tr.destinations.find((d) => d.query === next.location.trim()) : null;
  const nextT = next ? dayEvMin(next) : null;
  // origin and routes on today and later days (2026-11-03 mark "where is the info": a
  // later shift showed only a transit button); alerts stay today's, the trains running now
  const org = past ? null : tr?.origin;

  /* The actual trains and buses, from wherever he is sleeping tonight to the next
     place, asked of the self-hosted router the trips board already talks to (see
     trips/MOTIS.md). `arriveBy` is the point: he does not want the next train, he
     wants the ones that still land before the thing starts. Empty is a working
     answer — the router only holds NY/NJ timetables, so a day on a trip in Denver
     legitimately has nothing to say and the card falls back to the ride buttons. */
  const routeKey = org && org.lat != null && geo && geo.lat != null && next
    ? `${org.lat},${org.lng}|${geo.lat},${geo.lng}|${next.startDt || ""}`
    : "";
  useEffect(() => {
    if (!routeKey) { setRoutes(null); return; }
    let cancelled = false;
    const [frm, to, when] = routeKey.split("|");
    const q = `from=${frm}&to=${to}&arriveBy=1${when ? `&time=${encodeURIComponent(when)}` : ""}`;
    fetch(`/trips/api/transit?${q}`)
      .then((r) => (r.ok ? r.json() : null))
      /* An answer for the WRONG DAY is the one failure this card must not pass
         off as real: past the end of a timetable the router answers with the last
         day it holds, dated that day, with no flag on it (trips/MOTIS.md — the
         bus feeds are the horizon and they run out first). `stale_for` is the
         endpoint's own catch; a stale answer is thrown away here rather than
         drawn, because a plausible set of last-week's trains is worse than none. */
      /* `feeds_ended`: one timetable (the subway, 2026-11-01) ran out while the buses
         kept going, so the router answered a four-bus slog, correctly dated. Those
         routes are thrown away too, and the card names the timetable that ended. */
      .then((d) => {
        if (cancelled) return;
        setFeedsEnded(d?.feeds_ended?.length ? d.feeds_ended : null);
        setRoutes(d?.itineraries && !d.stale_for && !d.feeds_ended ? d.itineraries : []);
      })
      .catch(() => { if (!cancelled) setRoutes([]); });
    return () => { cancelled = true; };
  }, [routeKey]);

  // Shown on every day (2026-10-20 mark: "always show getting there"); live
  // transit and routes stay today-only, a later day gets the ride and map links.
  // Pickup is the origin (home, or the trip's stay that night), not the phone's
  // location (2026-11-03 mark); my_location only when there is no origin.
  const hasOrg = org && org.lat != null;
  const uber = geo && geo.lat != null
    ? `https://m.uber.com/looking?pickup=${hasOrg ? encodeURIComponent(JSON.stringify({ latitude: org.lat, longitude: org.lng, addressLine1: org.address || org.label })) : "my_location"}&drop%5B0%5D=${encodeURIComponent(JSON.stringify({ latitude: geo.lat, longitude: geo.lng, addressLine1: next.location }))}`
    : null;
  const lyft = geo && geo.lat != null
    ? `https://lyft.com/ride?id=lyft${hasOrg ? `&pickup[latitude]=${org.lat}&pickup[longitude]=${org.lng}` : ""}&destination[latitude]=${geo.lat}&destination[longitude]=${geo.lng}`
    : null;
  const transit = next ? `${dayMapsUrl(next.location)}&travelmode=transit${hasOrg ? `&origin=${encodeURIComponent(org.address || `${org.lat},${org.lng}`)}` : ""}` : null;
  const watched = tr ? tr.watched : ["F", "G", "4", "5"];
  /* Alerts are judged against HIS RIDE, not the clock (2026-10-21 mark: "is this for
     the time of the event or now?"). The ride runs from the earliest route's departure
     (or an hour before the event when there are no routes) to the event's start; an
     alert counts when one of its windows overlaps that. Those lead, badge and turn the
     card red; the rest of today's sit behind the "more" toggle. */
  const midnight = new Date(now); midnight.setHours(0, 0, 0, 0);
  const startLabel = (ts) => dayFmtMin(Math.round((ts * 1000 - midnight.getTime()) / 60000));
  const rideFrom = nextT ? Math.max(nowMin, routes?.length
    ? Math.min(...routes.map((it) => it.start_min)) : nextT.start - 60) : null;
  const toTs = (m) => midnight.getTime() / 1000 + m * 60;
  const onRide = (a) => !a.periods || !a.periods.length || a.periods.some(([s, e]) =>
    s <= toTs(nextT.start) && (e == null || e >= toTs(rideFrom)));
  const all = (tr && isToday && next ? tr.alerts : []).slice().sort((a, b) => (a.starts || 0) - (b.starts || 0));
  const ride = nextT ? all.filter(onRide) : [];
  const later = all.filter((a) => !ride.includes(a));
  const alerts = ride.concat(later);
  const shown = Math.min(ride.length, 3);
  const rideLabel = nextT ? `${dayFmtMin(rideFrom)}–${dayFmtMin(nextT.start)}` : "";
  const hitLines = new Set(ride.flatMap((a) => a.lines));
  const alertRow = (a, i) => (
    <div className="gt-alert" key={i}>
      <span className="gt-alert-lines">{a.lines.filter((l) => watched.includes(l)).map((l) => <LineBullet key={l} line={l} hit={ride.includes(a)} />)}</span>
      <span className="gt-alert-text">
        {a.starts ? <span className="gt-alert-when">from {startLabel(a.starts)}: </span> : null}
        {a.text}
      </span>
    </div>
  );
  return (
    <div className={`tb-card gt-card${ride.length ? " tb-card-alert" : ""}`}>
      <div className="tb-card-h">
        <span className="tb-card-name">getting there</span>
        {ride.length ? <span className="tb-card-badge">{ride.length}</span> : null}
      </div>
      <div className="tb-card-b">
        {next ? (
          <div className="gt-next">
            <div className="gt-next-t">
              <span className="gt-when t-num">{nextT ? dayFmtMin(nextT.start) : ""}</span>
              <span className="gt-name">{next.name}</span>
            </div>
            {/* 2026-11-03 mark: the nearest station said nothing the routes below do not */}
            <div className="gt-loc">{next.location}</div>
            {org ? (
              <div className="gt-from">
                from {org.label}{org.trip ? ` · ${org.trip}` : ""}
              </div>
            ) : null}
            {routes?.length ? (
              <div className="gt-routes">
                {routes.map((it, i) => (
                  <div className="gt-route" key={i}>
                    <span className="gt-route-t t-num">{dayFmtMin(it.start_min)}</span>
                    <span className="gt-route-legs">
                      {it.legs.map((l, j) => <LegChip key={j} leg={l} />)}
                    </span>
                    <span className="gt-route-dur t-num">{Math.round((it.dur || 0) / 60)}m</span>
                  </div>
                ))}
              </div>
            ) : routes && !routes.length ? (
              <div className="gt-routes-none">
                {feedsEnded
                  ? `${feedsEnded.map((f) => f.feed.replace("gtfs_", "")).join(", ")} timetable ran out ${feedsEnded[0].ended}, router needs a re-import`
                  : org?.trip ? "no timetable loaded for this trip" : "no train or bus times for this one"}
              </div>
            ) : null}
            <div className="gt-btns">
              {uber ? <a className="gt-btn" href={uber} target="_blank" rel="noreferrer">uber</a> : null}
              {lyft ? <a className="gt-btn" href={lyft} target="_blank" rel="noreferrer">lyft</a> : null}
              {transit ? <a className="gt-btn" href={transit} target="_blank" rel="noreferrer">transit</a> : null}
            </div>
          </div>
        ) : (
          <>
          <div className="gt-none">nowhere to be{!isToday ? " that day" : dests.length ? " for the rest of today" : " today"}</div>
          {view?.nextOutDay ? (
            <div className="tb-soon">
              <div className="tb-soon-k">next out · {view.nextOutDay.d === 1 ? "tomorrow" : `in ${view.nextOutDay.d} days`}</div>
              <div className="gt-next-t">
                <span className="gt-when t-num">{dayEvMin(view.nextOutDay.out) ? dayFmtMin(dayEvMin(view.nextOutDay.out).start) : ""}</span>
                <span className="gt-name">{view.nextOutDay.out.name}</span>
              </div>
              <div className="gt-loc">{view.nextOutDay.out.location}</div>
            </div>
          ) : null}
          </>
        )}
        {next && isToday ? (
          <>
        <div className="gt-lines">
          <span className="wx-k">lines</span>
          {watched.map((l) => <LineBullet key={l} line={l} hit={hitLines.has(l)} />)}
          {tr && !ride.length ? <span className="gt-ok">good service {rideLabel}</span> : null}
        </div>
        {ride.length ? <div className="gt-alert-when gt-ride-k">during your ride, {rideLabel}</div> : null}
        {alerts.slice(0, shown).map((a, i) => alertRow(a, i))}
        <HubCollapse open={showAll}>{alerts.slice(shown).map((a, i) => alertRow(a, i))}</HubCollapse>
        {alerts.length > shown ? (
          <button type="button" className="gt-more" aria-expanded={showAll} onClick={() => setShowAll((v) => !v)}>
            {showAll ? "fewer" : `+${alerts.length - shown} more today${ride.length <= shown ? ", not on your ride" : ""}`}
          </button>
        ) : null}
          </>
        ) : null}
      </div>
    </div>
  );
}

/* LEFT column cap: the selected day's calendar (Google-Calendar-style DayColumn),
   above the forward schedule + trip. Owns its own edit-event modal. */
function TodayCalendarCap({ view, now }) {
  const [eventModal, setEventModal] = useState(null);
  if (!view) return null;
  const { events, isToday, navLabel, selIso } = view;
  const EventModalCmp = window.EventModal;
  return (
    <div className="col-cal">
      <div className="tb-rail-head">
        <span className="tb-rail-t">{navLabel}</span>
        {events.length ? <span className="tb-count">{events.length}</span> : null}
        <span className="tb-rail-rule"></span>
      </div>
      <DayColumn
        events={events}
        now={now}
        isToday={isToday}
        onEdit={(ev) => setEventModal({ mode: "edit", event: ev })}
        onCreate={() => setEventModal({ mode: "create", date: selIso })}
      />
      {eventModal && EventModalCmp ? (
        <EventModalCmp modalState={eventModal} onClose={() => setEventModal(null)} onSaved={() => window.location.reload()} />
      ) : null}
    </div>
  );
}

/* RIGHT column cap: weather + due + bring + prep + leave + note for the day, above
   the non-scheduled task backlog. Owns the day-scoped checklist completion (bring/
   prep/due-card, client-side) and the real due-task completion (server write +
   parent re-hydrate). Due and prep always show, saying so when empty; leave and note
   self-hide. The glance grid stretches the cards to the calendar's height. */
function TodayPrepCap({ view, onRefresh }) {
  const dayStr = (view?.selIso) || "";
  const [done, setDone] = useState(() => readTbDone(dayStr));
  useEffect(() => { setDone(readTbDone(dayStr)); }, [dayStr]);
  const toggleDone = (k) => setDone(toggleTbDone(dayStr, k));

  const [completing, setCompleting] = useState(() => new Set());
  // tasks ticked off on this card today (mark 2026-11-03: "keep them here checked, dont delete them").
  // ponytail: per browser, a task finished elsewhere does not show here
  const keptKey = `hub.tb.kept.${dayStr}`;
  const readKept = () => { try { const a = JSON.parse(localStorage.getItem(keptKey)); return Array.isArray(a) ? a : []; } catch { return []; } };
  const [keptDone, setKeptDone] = useState(readKept);
  useEffect(() => { setKeptDone(readKept()); }, [dayStr]);
  const completeTask = async (t) => {
    if (t.id == null || completing.has(t.id)) return;
    setCompleting((prev) => new Set(prev).add(t.id));
    try {
      const res = await fetch("/api/tasks/complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: t.id }),
      });
      if (res.ok) {
        // the refresh drops done tasks from the due list; keep this one on the card, checked, for the day
        const kept = keptDone.filter((k) => k.id !== t.id).concat({ id: t.id, title: t.title || t.name });
        setKeptDone(kept);
        try { localStorage.setItem(keptKey, JSON.stringify(kept)); } catch {}
        if (onRefresh) onRefresh();
      }
    } catch {
      setCompleting((prev) => { const n = new Set(prev); n.delete(t.id); return n; });
    }
  };

  const BL = window.BriefingLogic;
  if (!view || !BL) return null;
  const { tIso, due, agg, prepItems, bringItems = [], soon, nextPrep } = view;
  const todayStr = tIso;
  const kept = keptDone.filter((k) => !due.tasks.some((t) => t.id === k.id));
  const dueCount = due.tasks.length + due.cards.length + kept.length;
  const taskOverdue = (t) => !t.done && t.due_target && BL.localDayString(t.due_target) < todayStr;
  const hasOverdue = due.tasks.some(taskOverdue) || due.cards.some((c) => c.status === "overdue");
  // Same tiering as the tasks panel (Tasks.jsx STALE_OVERDUE_DAYS) — a months-old
  // overdue item shouldn't shout as loud as one that just slipped.
  const overdueDays = (t) => Math.floor((Date.now() - new Date(t.due_target).getTime()) / 86400000);
  const overduePill = (t) => {
    const days = overdueDays(t);
    return days >= 30
      ? <span className="tb-pill tb-pill-stale">{days}d overdue</span>
      : <span className="tb-pill">overdue</span>;
  };
  return (
    <div className="col-prep">
      <Card name="due" count={dueCount} badge={dueCount - kept.length} alert={hasOverdue} placeholder="nothing due today"
        after={soon.length ? (
          <div className="tb-soon">
            <div className="tb-soon-k">coming up</div>
            {soon.map((x) => (
              <div className="tb-li tb-soon-li" key={x.key}>
                <span className="tb-soon-t">{x.label}</span>
                <span className="tb-soon-d t-num">{x.d === 1 ? "tomorrow" : `in ${x.d}d`}</span>
              </div>
            ))}
          </div>
        ) : null}>
        {due.tasks.map((t, i) => (
          <DueRow
            key={t.id != null ? `t${t.id}` : `t${i}`}
            label={t.title || t.name}
            done={t.done || completing.has(t.id)}
            pill={!t.done && taskOverdue(t) ? overduePill(t) : null}
            onToggle={t.done ? undefined : () => completeTask(t)}
          />
        ))}
        {kept.map((k) => <DueRow key={`k${k.id}`} label={k.title} done />)}
        {due.cards.map((c, i) => (
          <DueRow
            key={`c${i}`}
            label={c.name}
            done={done.has(`due-card:${c.name}`)}
            pill={<span className={`tb-pill${c.status === "overdue" ? "" : " tb-pill-soft"}`}>{c.status === "overdue" ? "overdue" : "today"}</span>}
            onToggle={() => toggleDone(`due-card:${c.name}`)}
          />
        ))}
      </Card>

      {/* one card for everything before you head out: Prep: lines to do, then things to
          pack (2026-11-03 send-back "merge" on "what is prep vs bring") */}
      <Card name="before you go" count={prepItems.length + bringItems.length} placeholder="nothing to do or pack"
        after={!prepItems.length && !bringItems.length && nextPrep ? (
          <div className="tb-soon">
            <div className="tb-soon-k">{nextPrep.d === 1 ? "tomorrow" : `in ${nextPrep.d} days`}</div>
            {nextPrep.prep.map((it) => <div className="tb-li tb-soon-li" key={it}><span className="tb-soon-t">{it}</span></div>)}
          </div>
        ) : null}>
        {prepItems.map((it) => (
          <CheckItem
            key={it}
            itemKey={`prep:${it}`}
            label={it}
            done={done.has(`prep:${it}`)}
            onToggle={toggleDone}
          />
        ))}
        {bringItems.map((it) => (
          <CheckItem
            key={`bring:${it.label}`}
            itemKey={`bring:${it.label}`}
            label={it.label}
            tag={it.weather ? "weather" : "pack"}
            done={done.has(`bring:${it.label}`)}
            onToggle={toggleDone}
          />
        ))}
      </Card>

      <Card name="leave" count={agg.leave.length}>
        {agg.leave.map((it) => (
          <div className="tb-li" key={`${it.text}|${it.src}`}>
            <span className="tb-li-when">{it.text}</span>
            <span className="tb-li-src">{it.src}</span>
          </div>
        ))}
      </Card>

      <Card name="note" count={agg.note.length}>
        {agg.note.map((it) => (
          <div className="tb-li" key={`${it.text}|${it.src}`}>{it.text} <span className="tb-li-src">{it.src}</span></div>
        ))}
      </Card>
    </div>
  );
}


Object.assign(window, { useNycWeather, todayBriefingSummary, computeTodayView, WeekStrip, TodayHeader, DayWeather, GettingThere, TodayCalendarCap, TodayPrepCap });
