/* Home today-briefing · 2 of 4: the day-view calendar column: hour grid, dead-time skips, event placement.

   Split from today.jsx 2026-07-29 (1065 lines), which was itself split out of
   chrome.jsx the same day. index.html loads the four in this order and each is
   its own Babel script with its own scope, so every name another file needs is
   handed over explicitly through the Object.assign at the bottom, the same
   pattern chrome.jsx uses. React hooks are re-destructured per file for the
   same reason.
*/

const { useEffect, useLayoutEffect, useRef, useState } = React;

function eventsForDay(schedule, iso) {
  return (schedule || []).find((d) => d.isoDate === iso)?.events || [];
}

/* ---------------- DayColumn ----------------
   A Google-Calendar-style day view for today's events: an hour grid with each
   timed event placed and sized by its real start/end, overlaps laid out in
   side-by-side lanes, a "now" line, and an all-day band on top. Replaces the
   old flat box rail. The hour range auto-fits the day's events so we don't
   scroll past empty morning hours. */
const DAY_HOUR_PX = 72;   // vertical pixels per hour — comfortable, not compact
const DAY_MIN_EV = 30;    // shortest a block can render so its name still shows

// A single long event (a work shift, a flight day) can otherwise blow the
// fully-expanded (no-scroll) day view out to an unreasonable page height. A
// continuously-reduced-rate tail (tried first) read as asymmetrical — full
// size at the start, jammed together at the end. Instead: the first and last
// SKIP_EDGE_MIN of any long-enough event both render at the normal per-hour
// rate (so the start AND the end each read normally, full size), and only
// the empty middle collapses into a fixed-height "time skip" divider — a
// dashed band with a duration label standing in for the skipped stretch, so
// the true event length stays legible as text even though its box no longer
// scales with duration. Only collapses a stretch with no OTHER event inside
// it (a short meeting nested in the middle of a long one keeps everything
// linear instead of getting swallowed).
const SKIP_EDGE_MIN = 60;
const SKIP_MIN_MIDDLE_MIN = 60;   // don't bother collapsing under an hour of dead time
const SKIP_BAND_PX = 40;

// Builds a minute->pixel mapping over [rangeStart, rangeEnd] that is linear at
// DAY_HOUR_PX/hour, except inside `skips` ([start,end) minute ranges) where
// the WHOLE range — however long — collapses to a fixed SKIP_BAND_PX. Same
// mapping positions hour gridlines, the now-line, the skip divider, and every
// event's top/height, so nothing overlaps or drifts out of order.
function buildDayYOf(rangeStart, rangeEnd, skips) {
  const raw = new Set([rangeStart, rangeEnd]);
  for (const z of skips) {
    raw.add(Math.min(Math.max(z.start, rangeStart), rangeEnd));
    raw.add(Math.min(Math.max(z.end, rangeStart), rangeEnd));
  }
  const pts = Array.from(raw).sort((a, b) => a - b);
  const inSkip = (mid) => skips.some((z) => mid > z.start && mid < z.end);
  const cum = [0];
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i];
    cum.push(cum[i - 1] + (inSkip((a + b) / 2) ? SKIP_BAND_PX : (b - a) / 60 * DAY_HOUR_PX));
  }
  return (m) => {
    const clamped = Math.min(Math.max(m, rangeStart), rangeEnd);
    let i = 0;
    while (i < pts.length - 1 && pts[i + 1] < clamped) i++;
    if (clamped >= pts[pts.length - 1]) return cum[cum.length - 1];
    const a = pts[i], b = pts[i + 1];
    const frac = (clamped - a) / (b - a || 1);
    return cum[i] + frac * (inSkip((a + b) / 2) ? SKIP_BAND_PX : (b - a) / 60 * DAY_HOUR_PX);
  };
}

/* The hour range the grid draws, given the day's events and however many WHOLE
   extra hours the column has room for below the grid.

   The floor is a one-hour buffer either side of the day's events, snapped to
   whole hours. Anything past that is space the layout already handed this column
   — the left column is as tall as the right one whether the grid fills it or not
   — so leaving it blank buys nothing and a taller grid reads the same. Extra
   hours are split evenly and centred; whichever side hits the day's edge
   (midnight below, 4am above, so a rolled past-midnight night still frames) hands
   its share to the other. It only ever GROWS: `extra` is never negative, so the
   buffer is a minimum and the grid never shrinks below what it already showed. */
const DAY_RANGE_FLOOR = 0;
const DAY_RANGE_CEIL = 1680;   // 28:00 — rolled events sit at 24:00-27:00
const DAY_SPAN = 720;          // every day shows at least twelve hours

/* Where the day opens (2026-10-20 mark): one gridline above the first event, or
   on an empty today one gridline above the current hour (3:39 opens at 2), or on
   an empty other day at midnight. Twelve hours from there, longer if the events
   run past it. */
function dayBase(timed, isToday, nowM) {
  const first = timed.length ? Math.min(...timed.map((t) => t.start)) : (isToday ? nowM : 60);
  const start = Math.max(DAY_RANGE_FLOOR, Math.floor(first / 60) * 60 - 60);
  const last = timed.length ? Math.ceil(Math.max(...timed.map((t) => t.end)) / 60) * 60 + 60 : 0;
  return [start, Math.max(start + DAY_SPAN, last)];
}

// Grows the base window into the room the column already has: downward first, so
// the opening hour stays put, and upward only once the bottom reaches `ceil`.
function dayRange([s, e], extraHours = 0, ceil = DAY_RANGE_CEIL) {
  let start = s, end = Math.min(e, ceil);
  let extra = Math.max(0, Math.round(extraHours));
  while (extra > 0 && (start > DAY_RANGE_FLOOR || end < ceil)) {
    if (end < ceil) end += 60; else start -= 60;
    extra--;
  }
  return [start, end];
}

// minutes-past-midnight from an ISO datetime ("...T19:00..."), else null
function dayDtMin(dt) {
  const m = String(dt || "").match(/T(\d{2}):(\d{2})/);
  return m ? (+m[1]) * 60 + (+m[2]) : null;
}
// minutes-past-midnight from a display label, else null. Both meridiem spellings
// parse — the hub now prints "7:00p", but a cached payload from before the switch
// still says "7:00pm" and a label that stops parsing plots the event at 7am.
function dayLabelMin(t) {
  const m = String(t || "").match(/(\d{1,2}):(\d{2})\s*([ap])?m?/i);
  if (!m) return null;
  let h = +m[1]; const mn = +m[2]; const ap = (m[3] || "").toLowerCase();
  if (ap === "p" && h < 12) h += 12;
  if (ap === "a" && h === 12) h = 0;
  return h * 60 + mn;
}
// {start,end} in minutes for a timed event. ISO datetimes are preferred
// (timezone-safe via the literal HH:MM); display labels are the fallback. A
// next-day end (ends after midnight) clamps to 1440 so the block runs to the
// bottom of the view instead of wrapping to 0. A `rolled` event belongs to the
// prior night but its clock time is after midnight (e.g. Paschal's 12a–3a
// bucketed onto last night), so both ends shift +1440 to plot after the
// evening events (24:00–27:00) instead of at the top of the day.
function dayEvMin(e) {
  let start = dayDtMin(e.startDt); if (start == null) start = dayLabelMin(e.time);
  let end = dayDtMin(e.endDt); if (end == null) end = dayLabelMin(e.timeEnd);
  if (start == null) return null;
  const sd = String(e.startDt || "").slice(0, 10);
  const ed = String(e.endDt || "").slice(0, 10);
  if (end == null) end = Math.min(start + 60, 1440);
  else if (ed && sd && ed > sd) end = end + 1440;  // ends next day → shift into after-midnight range
  else if (end <= start) end = Math.min(start + 60, 1440);  // bad/zero-length → 1h
  if (e.rolled) { start += 1440; end += 1440; }    // rolled past-midnight → after the evening
  return { start, end };
}
// compact time, e.g. "7p", "8:30p", "12a". Wraps past-midnight buffer minutes
// (1440 → "12a", 1500 → "1a") so the bottom buffer hour labels read correctly.
function dayFmtMin(m) {
  const w = ((m % 1440) + 1440) % 1440;
  const h = Math.floor(w / 60), mn = w % 60;
  const ap = h < 12 ? "a" : "p";
  const hh = h % 12 || 12;
  return mn ? `${hh}:${String(mn).padStart(2, "0")}${ap}` : `${hh}${ap}`;
}
// duration label for a skip divider, e.g. "4h 12m", "1h", "45m"
function fmtSkipDuration(mins) {
  const h = Math.floor(mins / 60), m = Math.round(mins % 60);
  if (h && m) return `${h}h ${m}m`;
  if (h) return `${h}h`;
  return `${m}m`;
}

// hour-gutter label, e.g. "7p", "12a", "1a" (buffer hour past midnight). Same
// a/p shape as every event time in the column beside it — the gutter used to say
// "7 PM" over a block labelled "7:30p", which is two spellings of one clock.
function dayFmtHour(m) {
  const w = ((m % 1440) + 1440) % 1440;
  const h = Math.floor(w / 60);
  const hh = h % 12 || 12;
  return `${hh}${h < 12 ? "a" : "p"}`;
}

// Google Maps directions to a place from the user's current location (origin
// omitted → "Your location"). Drives the clickable location on each event.
function dayMapsUrl(loc) {
  return `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(loc)}`;
}

// candidate skip: the middle of any event long enough to have a real gap
// once both edges keep SKIP_EDGE_MIN of full scale, and only if no OTHER
// event's span reaches into that middle (an overlapping short meeting
// keeps the whole stretch linear instead of getting swallowed).
function daySkips(timed) {
  const rawSkips = [];
  for (const it of timed) {
    const midStart = it.start + SKIP_EDGE_MIN;
    const midEnd = it.end - SKIP_EDGE_MIN;
    if (midEnd - midStart < SKIP_MIN_MIDDLE_MIN) continue;
    const overlapped = timed.some((o) => o !== it && o.start < midEnd && o.end > midStart);
    if (overlapped) continue;
    rawSkips.push({ start: midStart, end: midEnd, color: it.ev.color });
  }
  rawSkips.sort((a, b) => a.start - b.start);
  const skips = [];
  for (const z of rawSkips) {
    const last = skips[skips.length - 1];
    if (last && z.start <= last.end) last.end = Math.max(last.end, z.end);
    else skips.push(z);
  }
  return skips;
}

function DayColumn({ events, now, onEdit, onCreate, isToday = true }) {
  const scrollRef = useRef(null);
  const allDay = (events || []).filter((e) => e.allDay || e.time === "all day");
  const timed = [];
  for (const e of (events || [])) {
    if (e.allDay || e.time === "all day") continue;
    const t = dayEvMin(e);
    if (t) timed.push({ ev: e, start: t.start, end: t.end });
  }
  // What the grid is framed on (see dayBase). An empty day draws the same grid with
  // nothing on it (2026-10-20 send-back: an empty plate, not a different view). The
  // ceiling sits past 4am when needed so a late night still gets all twelve hours.
  const base = dayBase(timed, isToday, now.getHours() * 60 + now.getMinutes());
  const skips = daySkips(timed);
  // Twelve hours means twelve hours of HEIGHT (2026-11-03 mark): a long shift's
  // skipped middle shrinks to one band, so add hours below until the grid is as
  // tall as an unskipped twelve-hour day.
  while (buildDayYOf(base[0], base[1], skips)(base[1]) < (DAY_SPAN / 60) * DAY_HOUR_PX) base[1] += 60;
  const frame = [{ start: base[0], end: base[1] }];
  const ceil = Math.max(DAY_RANGE_CEIL, base[1]);

  // overlap layout: break into clusters of chained-overlapping events, then
  // greedily pack each cluster into the fewest side-by-side lanes.
  timed.sort((a, b) => a.start - b.start || a.end - b.end);
  const clusters = [];
  let cur = [], curMaxEnd = -1;
  for (const it of timed) {
    if (cur.length && it.start >= curMaxEnd) { clusters.push(cur); cur = []; curMaxEnd = -1; }
    cur.push(it); curMaxEnd = Math.max(curMaxEnd, it.end);
  }
  if (cur.length) clusters.push(cur);
  for (const cl of clusters) {
    const colEnds = [];
    for (const it of cl) {
      let placed = false;
      for (let c = 0; c < colEnds.length; c++) {
        if (it.start >= colEnds[c]) { it.col = c; colEnds[c] = it.end; placed = true; break; }
      }
      if (!placed) { it.col = colEnds.length; colEnds.push(it.end); }
    }
    for (const it of cl) it.ncol = colEnds.length;
  }

  // The grid spans the day's events with a one-hour buffer on each end, snapped
  // to whole hours (e.g. events 7:15p–12a → grid 6p–1a), then grows into whatever
  // vertical room the column was already given — see dayRange. `extra` is
  // measured after paint below and only ever climbs, so this settles in one or
  // two passes and never oscillates.
  const [extra, setExtra] = useState(0);
  const [rangeStart, rangeEnd] = dayRange(base, extra, ceil);

  /* How many more whole hours fit under the grid before it reaches the bottom of
     the space the column already occupies. Measured rather than derived, because
     the height comes from the OTHER column: this one is as tall as the tallest
     card beside it, and no stylesheet here knows that number.

     Resets to 0 on a day change or a resize so the grid can shrink back when the
     room genuinely goes away; between those it only grows, one measurement per
     paint, until less than an hour is left over. */
  const dayKey = frame.map((t) => `${t.start}-${t.end}`).join(",");
  useLayoutEffect(() => { setExtra(0); }, [dayKey]);
  useLayoutEffect(() => {
    const el = scrollRef.current;
    const parent = el?.parentElement;
    if (!el || !parent) return;
    // the add-event row sits under the grid, so its height is not room to grow into
    const tail = el.nextElementSibling ? el.nextElementSibling.offsetHeight : 0;
    const spare = parent.getBoundingClientRect().bottom - el.getBoundingClientRect().bottom - tail;
    const more = Math.floor(spare / DAY_HOUR_PX);
    if (more <= 0) return;
    // Stop the moment more hours stop widening the range, or a day that already
    // reaches both edges (a rolled overnight) would re-render forever chasing
    // room the clamp will not give it.
    setExtra((v) => {
      const [a, b] = dayRange(base, v + more, ceil);
      return a === rangeStart && b === rangeEnd ? v : v + more;
    });
  });
  useEffect(() => {
    const onResize = () => setExtra(0);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  // `extra` only climbs, so a first measurement taken while the right column was briefly
  // taller (weather arriving, the getting-there card still loading) would leave the grid
  // taller than the settled row needs and the today view with leftover height (spec
  // Check 2). Whenever the right column's own content changes height or the glance cards
  // come and go, start over so the grow pass measures the settled column. A content
  // change that leaves every height as it was (a transit poll with the same rows) does
  // nothing. Only natural boxes are observed (the weather panel and the cards' header
  // and body), never the stretched grids or the cards themselves, which stretch to the
  // row, so this grid's own growth cannot trigger it.
  useEffect(() => {
    const top = scrollRef.current?.closest(".lh-top");
    const glance = top?.querySelector(".lp-glance");
    if (!top || !glance || !window.ResizeObserver) return;
    const heights = new WeakMap();
    const ro = new ResizeObserver((entries) => {
      let changed = false;
      for (const en of entries) {
        const h = Math.round(en.contentRect.height);
        if (heights.get(en.target) !== h) { changed = changed || heights.has(en.target); heights.set(en.target, h); }
      }
      if (changed) setExtra(0);
    });
    // re-observing a box re-reports its height, which the map above already holds, so no reset
    const watch = () => top.querySelectorAll(".lp-wx, .lp-glance .tb-card > *").forEach((n) => ro.observe(n));
    watch();
    // a card arriving or leaving changes the column even when no watched box resized
    const mo = new MutationObserver((recs) => {
      if (recs.some((r) => [...r.addedNodes, ...r.removedNodes].some((n) => n.classList?.contains("tb-card") || n.querySelector?.(".tb-card")))) setExtra(0);
      watch();
    });
    mo.observe(glance, { childList: true, subtree: true });
    return () => { ro.disconnect(); mo.disconnect(); };
  }, [dayKey]);

  // scroll the now-line into view on first paint when the grid overflows. On a
  // non-today day there is no now-line, so scroll to the first event instead.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const anchorM = isToday ? now.getHours() * 60 + now.getMinutes() : rangeStart;
    el.scrollTop = Math.max(0, ((anchorM - rangeStart) / 60) * DAY_HOUR_PX - 80);
  }, []);

  const yOf = buildDayYOf(rangeStart, rangeEnd, skips);
  const gridH = Math.max(yOf(rangeEnd), DAY_HOUR_PX);

  // hour gridlines inside a skip band would bunch into an illegible mess —
  // the skip divider stands in for them instead.
  const hours = [];
  for (let m = rangeStart; m <= rangeEnd; m += 60) {
    if (!skips.some((z) => m > z.start && m < z.end)) hours.push(m);
  }

  const nowM = now.getHours() * 60 + now.getMinutes();
  const showNow = isToday && nowM >= rangeStart && nowM <= rangeEnd;

  const grid = (
    <div className="tb-day-grid" style={{ height: `${gridH + 8}px` }}>
      {hours.map((m) => (
        <div className="tb-day-hr" style={{ top: `${yOf(m)}px` }} key={m}>
          <span className="tb-day-hr-label">{dayFmtHour(m)}</span>
          <span className="tb-day-hr-line"></span>
        </div>
      ))}
      {showNow ? (
        <div className="tb-day-now" style={{ top: `${yOf(nowM)}px` }}>
          <span className="tb-day-now-dot"></span>
        </div>
      ) : null}
      {skips.map((z, i) => (
        <div className="tb-day-skip" key={`skip${i}`} style={{ top: `${yOf(z.start)}px`, height: `${SKIP_BAND_PX}px`,
          // a dimmed ghost of the event it cuts through (2026-10-20 send-back)
          ...(z.color ? { background: `color-mix(in srgb, ${z.color} 32%, var(--bg-elev))` } : {}) }}>
          <span className="tb-day-skip-label">{fmtSkipDuration(z.end - z.start)} skipped</span>
        </div>
      ))}
      <div className="tb-day-lanes">
        {timed.map((it, i) => {
          const e = it.ev;
          const top = yOf(it.start);
          const h = Math.max(yOf(it.end) - top, DAY_MIN_EV);
          const w = 100 / it.ncol;
          return (
            <div
              key={i}
              className={`tb-day-ev${e.color ? " tinted" : ""}${e.done ? " done" : ""}${e.task ? " is-task" : ""}${e.link ? " has-link" : ""}`}
              style={{ top: `${top}px`, height: `${h}px`, left: `${it.col * w}%`, width: `${w}%`,
                ...(e.color ? { "--ev-c": e.color, "--ev-ink": window.eventInk(e.color) } : {}) }}
              title={e.link ? `${e.name} · ${dayFmtMin(it.start)}–${dayFmtMin(it.end)} · open` : `${e.name} · ${dayFmtMin(it.start)}–${dayFmtMin(it.end)}`}
              onClick={e.link ? () => window.open(e.link, "_blank", "noreferrer") : undefined}
              role={e.link ? "button" : undefined}
              tabIndex={e.link ? 0 : undefined}
              onKeyDown={e.link ? (ev) => {
                if (ev.key === "Enter") window.open(e.link, "_blank", "noreferrer");
                else if (ev.key === " ") { ev.preventDefault(); window.open(e.link, "_blank", "noreferrer"); }
              } : undefined}
            >
              {onEdit ? (
                <button
                  type="button"
                  className="tb-day-ev-edit"
                  title="edit event"
                  onClick={(ev) => { ev.stopPropagation(); onEdit(e); }}
                >
                  <svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true"><path fill="currentColor" d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>
                </button>
              ) : null}
              <span className="tb-day-ev-name">{e.name}</span>
              <span className="tb-day-ev-time">{dayFmtMin(it.start)}–{dayFmtMin(it.end)}</span>
              {e.location ? (
                <a
                  className="tb-day-ev-loc"
                  href={dayMapsUrl(e.location)}
                  target="_blank"
                  rel="noreferrer"
                  title={`directions to ${e.location}`}
                  onClick={(ev) => ev.stopPropagation()}
                >
                  <svg className="tb-day-ev-loc-pin" viewBox="0 0 24 24" width="11" height="11" aria-hidden="true"><path fill="currentColor" d="M12 2a7 7 0 0 0-7 7c0 5.25 7 13 7 13s7-7.75 7-13a7 7 0 0 0-7-7zm0 9.5A2.5 2.5 0 1 1 12 6a2.5 2.5 0 0 1 0 5.5z"/></svg>
                  <span className="tb-day-ev-loc-txt">{e.location}</span>
                </a>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );

  return (
    <>
      <div className="tb-day" ref={scrollRef}>
        {allDay.length ? (
          // a row of the grid: label in the hour gutter, chips in the event column (2026-10-21 mark)
          <div className="tb-day-allday">
            <span className="tb-day-allday-k">all day</span>
            <div className="tb-day-allday-chips">
              {allDay.map((e, i) => (
                <span key={i} className={`tb-day-chip${e.color ? " tinted" : ""}${e.done ? " done" : ""}`}
                      style={e.color ? { "--ev-c": e.color, "--ev-ink": window.eventInk(e.color) } : undefined}>{e.name}</span>
              ))}
            </div>
          </div>
        ) : null}
        {grid}
      </div>
      {onCreate ? (
        <button type="button" className="event-row-ghost" onClick={onCreate}>
          <span className="ghost-time">—</span>
          <span className="ghost-pip"></span>
          <span className="ghost-label">add event</span>
        </button>
      ) : null}
    </>
  );
}

// Case-insensitive merge of event-authored bring + forecast-derived bring, used
// by both the collapsed summary and the open card so the count stays consistent.

Object.assign(window, { eventsForDay, DayColumn, dayEvMin, dayFmtMin, dayMapsUrl, dayRange });
