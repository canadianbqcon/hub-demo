/* ============================================================
   hub · trips — time parsing.

   trips.db holds times in whatever shape they were typed in:
   activities.scheduled_time is "11:00 AM" | "22:30" | "08:00" | "",
   and the logistics tables hold free-text stamps like
   "May 14, 5:30 AM" | "Sep 17, 2026 3:00pm" | "Dec 17" | "2026-09-10".

   Everything that needs to ORDER or POSITION those values routes
   through here. Sorting the raw strings is what made "1:00 PM" land
   before "11:00 AM" in the old schedule grid.

   No DOM, no fetch, no state. Loaded as a plain script (window.TripTime)
   and as a CommonJS module by tests/triptime.selftest.js.
   ============================================================ */
((root) => {
  

  var MONTHS = {
    jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6,
    jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12,
  };

  /* "10:30 PM" | "22:30" | "3:00pm" | "12:00 pM" -> minutes since midnight.
     Returns null for "", null, and anything that isn't a clock. */
  function parseClock(s) {
    if (s == null) return null;
    var m = String(s).trim().match(/^(\d{1,2}):(\d{2})\s*([ap])\.?m\.?$/i);
    if (m) {
      let h12 = Number(m[1]);
      if (h12 < 1 || h12 > 12) return null;
      const mm = Number(m[2]);
      if (mm > 59) return null;
      if (h12 === 12) h12 = 0;                     // 12:xx AM is 00:xx, 12:xx PM is 12:xx
      return h12 * 60 + mm + (m[3].toLowerCase() === "p" ? 720 : 0);
    }
    m = String(s).trim().match(/^(\d{1,2}):(\d{2})$/);
    if (!m) return null;
    var h = Number(m[1]), min = Number(m[2]);
    if (h > 23 || min > 59) return null;
    return h * 60 + min;
  }

  function pad2(n) { return (n < 10 ? "0" : "") + n; }
  function iso(y, mo, d) { return `${y}-${pad2(mo)}-${pad2(d)}`; }

  /* Free-text stamp -> { date: "YYYY-MM-DD", minutes: int|null, plusDays: int }.
     Returns null when there is no date to be found.

     tripYear anchors the month-only forms ("May 14", "Dec 17") that carry no
     year. A month more than 6 behind the trip's start month rolls forward a
     year, so a trip crossing New Year doesn't file its January leg 12 months
     early. An explicit 4-digit year in the string always wins.

     The trailing "+1" in "Dec 18, 12:37 PM+1" is captured as plusDays rather
     than folded into the date — the caller decides what to do with it. */
  function parseStamp(s, tripStartDate) {
    if (s == null) return null;
    var str = String(s).trim();
    if (!str) return null;

    var plus = 0;
    var pm = str.match(/\+(\d+)\s*$/);
    if (pm) { plus = Number(pm[1]); str = str.slice(0, pm.index).trim(); }

    // ISO first — "2026-09-10", "2026-09-10T14:30", "2026-09-10 14:30"
    var m = str.match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{1,2}:\d{2}))?/);
    if (m) {
      return { date: iso(Number(m[1]), Number(m[2]), Number(m[3])), minutes: m[4] ? parseClock(m[4]) : null, plusDays: plus };
    }

    // "May 14", "May 14, 5:30 AM", "Sep 17, 2026 3:00pm", "Dec 20"
    m = str.match(/^([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:\s*,)?(?:\s+(\d{4}))?(?:\s*,)?\s*(.*)$/);
    if (!m) return null;
    var mon = MONTHS[m[1].slice(0, 3).toLowerCase()];
    if (!mon) return null;
    var day = Number(m[2]);
    if (day < 1 || day > 31) return null;
    var year = m[3] ? Number(m[3]) : inferYear(mon, tripStartDate);
    return { date: iso(year, mon, day), minutes: parseClock(m[4]), plusDays: plus };
  }

  function inferYear(mon, tripStartDate) {
    var base = String(tripStartDate || "").match(/^(\d{4})-(\d{2})/);
    if (!base) return new Date().getFullYear();
    var y = Number(base[1]), startMon = Number(base[2]);
    return mon < startMon - 6 ? y + 1 : y;
  }

  /* Comparator for anything carrying {scheduled_date, scheduled_time}.
     Untimed rows sort after timed ones on the same day rather than to 00:00 —
     "no time set" is not "midnight". */
  function byDateTime(a, b) {
    var d = String(a.scheduled_date || "").localeCompare(String(b.scheduled_date || ""));
    if (d) return d;
    var am = parseClock(a.scheduled_time), bm = parseClock(b.scheduled_time);
    if (am == null && bm == null) return 0;
    if (am == null) return 1;
    if (bm == null) return -1;
    return am - bm;
  }

  /* "6:45 PM" -> "6:45p", "22:30" -> "10:30p". Compact label for a block.

     Lowercase a/p with no space is the one clock shape the whole hub prints —
     trips, the day rail, the briefing, the schedule picker and the shift table
     all route here or copy this. Nothing renders 24-hour: a bare "16:15" in a
     column of "4:15p" reads as a typo or as a missing meridiem, which is exactly
     how the day-of checkpoint column was read. */
  function fmtClock(mins) {
    if (mins == null) return "";
    var h = Math.floor(mins / 60) % 24, m = mins % 60;
    var mer = h < 12 ? "a" : "p";
    var h12 = h % 12 === 0 ? 12 : h % 12;
    return `${h12}:${pad2(m)}${mer}`;
  }

  /* A raw clock string the way it was typed ("22:30", "3:00pm", "") -> the house
     shape. Anything that is not a clock passes through untouched, so a free-text
     "after lunch" in a scheduled_time still prints itself. */
  function fmtClockText(s) {
    var m = parseClock(s);
    return m == null ? (s == null ? "" : String(s)) : fmtClock(m);
  }

  /* Every date from start to end inclusive. Built off a UTC clock so the
     rollover can't be shifted by the viewer's local offset. */
  function dayRange(start, end) {
    if (!start) return [];
    var s = Date.parse(`${start}T00:00:00Z`);
    var e = Date.parse(`${end || start}T00:00:00Z`);
    if (Number.isNaN(s) || Number.isNaN(e) || e < s) return [start];
    var out = [];
    for (let t = s; t <= e; t += 86400000) out.push(new Date(t).toISOString().slice(0, 10));
    return out;
  }

  var DEFAULT_AXIS = 300;   // 5am — where a day breaks when nothing argues otherwise
  var MIN_QUIET = 120;      // a day boundary needs at least a 2h lull to sit in

  /* Where should this trip's day start?

     A timeline has to cut the 24h cycle somewhere, and the cut should land where
     nothing is happening — otherwise it slices a night in half and the tail
     shows up as the next morning. 5am is right for most trips, so it wins
     whenever it already sits in the trip's quietest stretch. It only moves when
     the trip genuinely has something going on around 5am (a dawn flight, an
     all-nighter), and then it moves to the middle of the longest lull, snapped
     to the hour so the gutter still reads in round numbers.

     `starts` is every event's minutes-since-midnight for the whole trip.
     Returns minutes since midnight, always a whole hour. */
  function axisStart(starts) {
    var pts = (starts || []).filter((m) => typeof m === "number" && m >= 0 && m < 1440)
      .sort((a, b) => a - b);
    if (pts.length < 2) return DEFAULT_AXIS;

    // every circular gap between consecutive events, widest tracked
    var best = -1, from = 0, to = 0, gaps = [];
    for (let i = 0; i < pts.length; i++) {
      const a = pts[i], b = pts[(i + 1) % pts.length];
      const gap = i === pts.length - 1 ? b + 1440 - a : b - a;
      gaps.push([a, a + gap]);
      if (gap > best) { best = gap; from = a; to = a + gap; }
    }
    if (best < MIN_QUIET) return DEFAULT_AXIS;          // busy round the clock: no better answer

    // The default wins if it sits in ANY adequate lull — not just the widest
    // one. Checking only the widest moved the boundary off a perfectly quiet 5am
    // whenever some daytime gap happened to be longer, which is the opposite of
    // "5am unless the trip argues otherwise".
    for (let g = 0; g < gaps.length; g++) {
      if (gaps[g][1] - gaps[g][0] < MIN_QUIET) continue;
      for (let k = 0; k < 2; k++) {
        const d = DEFAULT_AXIS + k * 1440;
        if (d > gaps[g][0] && d < gaps[g][1]) return DEFAULT_AXIS;
      }
    }
    // otherwise: middle of the lull, snapped to an hour, kept strictly inside it
    var mid = Math.round((from + best / 2) / 60) * 60;
    if (mid <= from) mid = Math.ceil((from + 1) / 60) * 60;
    if (mid >= to) mid = Math.floor((to - 1) / 60) * 60;
    return ((mid % 1440) + 1440) % 1440;
  }

  /* Minutes east of UTC for an IANA zone ON A GIVEN DATE, or null when the zone
     is empty/unknown/unsupported.

     The date is not decoration. A zone's offset moves twice a year, so "what is
     Denver's offset" has no answer on its own — a September flight and a
     January flight out of the same gate differ by an hour. Callers pass the
     stamp's own date and get the offset in force that day.

     Intl does the work; there is no table here and no library. `longOffset`
     gives "GMT-06:00" (and a bare "GMT" for UTC), which is the whole parse. */
  var _tzCache = {};
  function tzOffset(tz, isoDate) {
    var zone = String(tz || "").trim();
    if (!zone) return null;
    var day = /^\d{4}-\d{2}-\d{2}$/.test(String(isoDate || "")) ? isoDate : null;
    if (!day) return null;
    var key = `${zone}@${day}`;
    if (key in _tzCache) return _tzCache[key];
    var out = null;
    try {
      // Noon, so the probe can't be pushed onto the wrong side of a DST
      // changeover — those land near midnight, and a midnight probe in a zone
      // that springs forward at 00:00 reads the day before's offset.
      const at = Date.parse(`${day}T12:00:00Z`);
      const parts = new Intl.DateTimeFormat("en-US", { timeZone: zone, timeZoneName: "longOffset" })
        .formatToParts(new Date(at));
      let name = "";
      for (let i = 0; i < parts.length; i++) if (parts[i].type === "timeZoneName") name = parts[i].value;
      const m = /^GMT([+-])(\d{1,2})(?::(\d{2}))?$/.exec(name);
      if (m) out = (m[1] === "-" ? -1 : 1) * (Number(m[2]) * 60 + Number(m[3] || 0));
      else if (name === "GMT" || name === "UTC") out = 0;
    } catch { out = null; }   // unknown zone: Intl throws RangeError
    _tzCache[key] = out;
    return out;
  }

  /* How far the clock JUMPS when you fly from one zone to the other on this
     date — what you add to a naive (arrival - departure) to get real elapsed
     time. LGA(-240) -> DEN(-360) on 2026-09-10 is +120: the 06:30 -> 08:40 that
     reads as 2h10m is 4h10m in the air.

     Null when either end's zone is unknown, and null is NOT zero — a caller that
     treats it as zero is back to the bug this exists to fix, so they have to
     decide out loud what an unknown zone means. */
  function zoneShift(fromTz, toTz, isoDate) {
    var a = tzOffset(fromTz, isoDate), b = tzOffset(toTz, isoDate);
    return a == null || b == null ? null : a - b;
  }

  /* "EDT" | "MDT" | "GMT+2" — what to print beside a clock so a reader can see
     WHICH zone it is written in. Empty string when the zone is unknown, so it
     concatenates into a label without leaving a stray separator behind. */
  function tzAbbr(tz, isoDate) {
    var zone = String(tz || "").trim();
    if (!zone || tzOffset(zone, isoDate) == null) return "";
    try {
      const parts = new Intl.DateTimeFormat("en-US", { timeZone: zone, timeZoneName: "short" })
        .formatToParts(new Date(Date.parse(`${isoDate}T12:00:00Z`)));
      for (let i = 0; i < parts.length; i++) if (parts[i].type === "timeZoneName") return parts[i].value;
    } catch { /* unknown zone: handled by the tzOffset guard above */ }
    return "";
  }

  var API = {
    parseClock: parseClock, parseStamp: parseStamp, byDateTime: byDateTime,
    fmtClock: fmtClock, fmtClockText: fmtClockText, dayRange: dayRange, axisStart: axisStart, DEFAULT_AXIS: DEFAULT_AXIS,
    tzOffset: tzOffset, zoneShift: zoneShift, tzAbbr: tzAbbr,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = API;
  root.TripTime = API;
})(typeof globalThis !== "undefined" ? globalThis : this);
