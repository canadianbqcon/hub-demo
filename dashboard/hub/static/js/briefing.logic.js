/* Pure briefing logic. No DOM, no fetch, no React. Unit-tested under node
   (briefing.logic.test.js) and reused by chrome.jsx in the browser. */

const LABEL_RE = /^\s*(bring|prep|leave|note)\s*:\s*(.+)$/i;

// Trip events carry no `description` key (built outside the gcal merge), so the
// raw field can be undefined. Always coerce before splitting.
function parseEventLabels(description) {
  const out = { bring: [], prep: [], leave: [], note: [] };
  const text = description || "";
  for (const line of text.split("\n")) {
    const m = line.match(LABEL_RE);
    if (!m) continue; // non-label lines are free text, ignored
    out[m[1].toLowerCase()].push(m[2].trim());
  }
  return out;
}

// Parse a clock time out of a free-text leave label -> minutes since midnight.
// Lets leave rows sort by actual time-of-day: a plain string compare puts
// "15:15" before "9:10" (because '1' < '9'), which is wrong. Supports 24h and
// both meridiem spellings ("5:30P" and the older "5:30pm"). Text with no
// parseable time sorts last (Infinity), tie-broken alphabetically so order
// stays stable.
function leaveSortKey(text) {
  const m = String(text).match(/(\d{1,2}):(\d{2})\s*([ap])?m?/i);
  if (!m) return Infinity;
  let h = parseInt(m[1], 10);
  const min = parseInt(m[2], 10);
  const ap = m[3]?.toLowerCase();
  if (ap === "p" && h < 12) h += 12;
  if (ap === "a" && h === 12) h = 0;
  return h * 60 + min;
}

// What a Partiful host asks guests to bring, read from the invite text the
// Partiful calendar copies into the description. Hosts write it freehand
// ("bring ur towels n seltzers", "BYOB", "if you have gum please bring"), so
// this lifts the host's own clause rather than guessing a noun.
// ponytail: phrase heuristics, tuned on the 19 Partiful invites of 2025-11..2026-11.
const BRING_SKIP_RE = /\+\s*1|friends|vibes|yourself|people/i;
function partifulAsks(ev) {
  const out = { bring: [], prep: [] };
  const text = (ev && ev.description) || "";
  if (!/partiful/i.test(((ev && ev.name) || "") + text)) return out;
  const tidy = (s) => {
    s = s.replace(/[^\p{L}\p{N}\s'’&/+\-:()]/gu, "").replace(/\s+/g, " ").trim();
    return s === s.toUpperCase() ? s.toLowerCase() : s;   // de-shout ALL CAPS
  };
  if (/\bBYOB\b/i.test(text)) out.bring.push("drinks (BYOB)");
  if (/\bcostume/i.test(text)) out.bring.push("costume");
  for (const sentence of text.split(/(?<=[.!?])\s+|\n/)) {
    if (LABEL_RE.test(sentence)) continue;   // typed bring:/prep: lines are parseEventLabels' job
    const m = sentence.match(/\bbring\b(.*)$/i);
    if (m && !/\bBYOB\b/i.test(sentence)) {
      let what = m[1].split(/[.,;!?]|\bbut\b|\bas\b/i)[0];
      // "If you have gum and/or a toothbrush please bring": the item comes before the verb
      if (!tidy(what)) what = sentence.slice(0, m.index).replace(/^.*?\bif you have\b|\bplease\b\s*$/gi, "");
      what = tidy(what);
      if (what && !BRING_SKIP_RE.test(what)) out.bring.push(what);
    }
    const w = sentence.match(/\bwear\b([^.!?(]*)/i);
    if (w && tidy(w[1])) out.prep.push("wear " + tidy(w[1]));
  }
  return out;
}

// Event kits: what a kind of event needs, matched on its name and place. Items
// came from Sam's 2026-11-09 decision-strip pass over a year of events. A
// kit with `checklist` pulls that Hub checklist's live items instead of a
// copy, so editing the checklist edits the card. Stay asks (stayPrep) are
// attached server-side from the booked stay's own check-in / checkout text.
// ponytail: a short list of the big US airports; a flight touching any other
// code reads as international (worst case: an extra "tell the card company").
const US_AIRPORTS = new Set(("ATL LAX ORD DFW DEN JFK SFO SEA LAS MCO EWR CLT PHX IAH MIA BOS MSP FLL DTW " +
  "PHL LGA BWI SLC SAN IAD DCA MDW TPA PDX HNL AUS BNA DAL STL HOU SJC OAK SMF MSY RDU SNA CLE MCI " +
  "SAT IND PIT CVG CMH JAX OGG BDL RSW BUR ONT ABQ OMA BUF ANC HPN ISP SWF").split(" "));
const placeName = (ev) => {          // "Bohemian Hall & Beer Garden, 29-19 24th Ave" -> the venue; a bare address -> ""
  const first = String((ev && ev.location) || "").split(",")[0].trim();
  return /^\d/.test(first) ? "" : first;
};
const SPORT_KITS = [
  [/badminton/i, ["racket", "shuttlecocks", "court shoes", "water", "towel"]],
  [/box(ing|club)|clinch|muay thai|kickbox/i, ["hand wraps", "gloves", "water", "towel", "change of shirt"]],
  [/basketball|hoops/i, ["basketball shoes", "water", "towel"]],
  [/pickleball|tennis|squash|padel/i, ["paddle or racket", "balls", "court shoes", "water"]],
  [/climb|boulder/i, ["climbing shoes", "chalk bag", "water"]],
  [/soccer|futsal/i, ["cleats or turf shoes", "shin guards", "water"]],
  [/volleyball/i, ["court shoes", "knee pads", "water"]],
  [/\bgym\b|lift|workout/i, ["gym shoes", "water", "towel", "headphones"]],
  [/\bgolf\b|driving range|topgolf/i, ["golf shoes", "glove", "water"]],
  [/swim(ming)? laps|lap swim/i, ["swimsuit", "goggles", "towel", "flip-flops"]],
];
function eventKits(ev) {
  const out = { bring: [], prep: [], checklists: [] };
  if (!ev) return out;
  const name = String(ev.name || ""), desc = String(ev.description || "");
  // a reminder about an event ("✓ Lost Lands Payment") is not the event
  if (ev.task || /^✓|payment|\bdue\b|renews|rsvp/i.test(name)) return out;
  const where = name + " " + placeName(ev);
  const add = (bring = [], prep = [], checklist) => {
    out.bring.push(...bring); out.prep.push(...prep);
    if (checklist) out.checklists.push(checklist);
  };
  const codes = (name.match(/\b([A-Z]{3})\s*(?:→|->)\s*([A-Z]{3})\b/) || []).slice(1)
    .concat((name.match(/^flight to\s+([A-Z]{3})\b/i) || []).slice(1));
  const flight = codes.length > 0 || /^flight to\b/i.test(name);
  if (flight) {
    add([], [], "Travel");
    if (codes.some((c) => !US_AIRPORTS.has(c.toUpperCase())))
      add([], ["tell the card company you're traveling", "set up phone roaming"]);
  }
  if (!flight && (/^(train|bus|rhb)\b/i.test(name) || (/→/.test(name) && /station|terminal/i.test(ev.location || ""))))
    add(["ticket or QR code"], ["buy the ticket ahead"]);
  if (/rental pick-?up|u-?haul|load u-?haul/i.test(name) && !/return|drop/i.test(name))
    add(["driver's license", "the card you booked with"]);
  if (/rental drop-?off|return u-?haul/i.test(name))
    add([], ["refill the gas", "photos of the car"]);
  if (Array.isArray(ev.stayPrep)) add([], ev.stayPrep);
  if (/snowboard|\bski(ing)?\b|mount snow|camelback|big snow|killington|stowe|okemo/i.test(where))
    add([], [], "Snowboarding");
  if (/lost lands|\bultra\b|festival|zedd in the park|blaze|\bedc\b|electric zoo|governors ball/i.test(where) || /\bfestival\b/i.test(desc))
    add([], [], "Rave");
  // A pregame counts only at a bar; most are at someone's place. A place named
  // "... Bar" that is really a restaurant, spa or gym gets nothing.
  const place = placeName(ev);
  const notABar = /grill|wing|burger|sushi|raw bar|oyster|spa\b|boxclub|gym/i.test(place);
  const barPlace = !notABar && /\bbar\b|pub|beer|lounge|club|tavern|saloon|brewery|karaoke|ktv/i.test(place);
  const barName = !/pregame/i.test(name) && /\bktv\b|karaoke|\bclub\b|\bbar\b|marquee|nightclub/i.test(name) && !/burger|food/i.test(name);
  if (!/shift|training/i.test(name) && (barPlace || barName)) add(["ID", "earplugs"]);
  if (!/^stay\b/i.test(name) && /beach|\bpool\b|\bspa\b|sauna|paddleboard|barton springs|swim(?!ming laps)/i.test(where))
    add([], [], "Beach");
  if (/\bhike|hiking|trailhead|mount bonnell|reimers ranch/i.test(where))
    add(["snacks", "water", "long pants", "camera", "charger", "sunglasses", "first aid kit"]);
  if (/marathon|\b\d+k\b|\brace\b|triathlon/i.test(name))
    add(["bib", "gels"], ["carbo load", "warm up", "stretch"]);
  // name only: a wedding at a golf course is not golf
  for (const [re, kit] of SPORT_KITS) if (re.test(name)) add(kit);
  // errands: bring the thing the event names ("Drop off Mikka's glasses")
  const carry = name.match(/^(?:drop[ -]?off|return)\s+(.+)$/i);
  if (carry && !/^at\b|u-?haul/i.test(carry[1])) add([carry[1].replace(/\s+pt\.?\s*\d+$/i, "").trim()]);
  if (/^return amazon/i.test(name)) add(["return QR code"]);
  if (/^cash (j&co )?check/i.test(name)) add(["the check", "ID"]);
  if (/^pick[ -]?up\b/i.test(name) && !/check|mom|rental/i.test(name)) add(["order number"]);
  // in person = a street address and no video link
  if (/interview/i.test(name) && /\d/.test(ev.location || "") && !/zoom\.us|meet\.google|teams\.microsoft|webex/i.test(desc + (ev.location || "")))
    add(["printed resume"]);
  return out;
}

// Merge labels across all of today's events. bring/prep are flat, deduped
// case-insensitively (first-seen casing wins). leave/note keep their source
// event name; leave is sorted by actual time-of-day (see leaveSortKey).
function aggregateLabels(events) {
  const bring = [];
  const prep = [];
  const leave = [];
  const note = [];
  const checklists = [];   // Hub checklist names an event kit pulls in
  const seen = { bring: new Set(), prep: new Set() };
  const pushDedup = (arr, key, val) => {
    const k = val.toLowerCase();
    if (seen[key].has(k)) return;
    seen[key].add(k);
    arr.push(val);
  };
  for (const ev of events || []) {
    const p = parseEventLabels(ev.description);
    p.bring.forEach((v) => { pushDedup(bring, "bring", v); });
    p.prep.forEach((v) => { pushDedup(prep, "prep", v); });
    p.leave.forEach((v) => { leave.push({ text: v, src: ev.name }); });
    p.note.forEach((v) => { note.push({ text: v, src: ev.name }); });
    const asks = partifulAsks(ev);
    asks.bring.forEach((v) => { pushDedup(bring, "bring", v); });
    asks.prep.forEach((v) => { pushDedup(prep, "prep", v); });
    const kit = eventKits(ev);
    kit.bring.forEach((v) => { pushDedup(bring, "bring", v); });
    kit.prep.forEach((v) => { pushDedup(prep, "prep", v); });
    kit.checklists.forEach((v) => { if (!checklists.includes(v)) checklists.push(v); });
  }
  leave.sort((a, b) => {
    const ka = leaveSortKey(a.text);
    const kb = leaveSortKey(b.text);
    return ka !== kb ? ka - kb : a.text.localeCompare(b.text);
  });
  return { bring, prep, leave, note, checklists };
}

// Local-time YYYY-MM-DD key from a Date or an ISO-ish string.
function localDayString(dateOrIso) {
  const d = dateOrIso instanceof Date ? dateOrIso : new Date(dateOrIso);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

// Tasks: only those with a due_target whose local day is today or earlier
// (overdue + due-today). Cards: status overdue, or (status due and due_in_days === 0).
// Null inputs (progressive load) yield empty lists.
function selectDueItems(tasks, cards, todayStr) {
  const dueTasks = (tasks || []).filter(
    (t) => t.due_target && localDayString(t.due_target) <= todayStr
  );
  const dueCards = (cards || []).filter(
    (c) => c.status === "overdue" || (c.status === "due" && c.due_in_days === 0)
  );
  return { tasks: dueTasks, cards: dueCards };
}

// Day arithmetic on YYYY-MM-DD keys, in local time. addDays shifts a key by n
// days; dayOffset returns whole days between two keys (b - a). Both parse the
// key as local midnight so a same-day diff is exactly 0 regardless of DST.
function addDays(dayStr, n) {
  const [y, m, d] = String(dayStr).split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  dt.setDate(dt.getDate() + n);
  return localDayString(dt);
}
function dayOffset(fromStr, toStr) {
  const a = new Date(`${fromStr}T00:00:00`);
  const b = new Date(`${toStr}T00:00:00`);
  return Math.round((b - a) / 86400000);
}

// Day-scoped variant of selectDueItems. For today (selectedStr === todayStr) it
// is identical to selectDueItems (overdue + due-today rolled up). For any other
// day it shows the open tasks whose due_target fell on that day — what was still
// outstanding then. Cards surface on the day matching their due_in_days offset
// from today (symmetric past and future). Null inputs yield empty lists.
//
// Completed tasks are deliberately NOT folded in. A finished job is not a due
// item; the /todo skill records it in log/daily-recap.md at completion time
// (no longer rendered on the home page since 2026-09-03). This used to fold
// completed tasks onto their due day and their completion day, which put done
// work in an action list.
function selectDueItemsForDay(tasks, cards, selectedStr, todayStr) {
  if (selectedStr === todayStr) return selectDueItems(tasks, cards, todayStr);
  const offset = dayOffset(todayStr, selectedStr);
  const openDue = (tasks || []).filter(
    (t) => t.due_target && localDayString(t.due_target) === selectedStr
  );
  const dueCards = (cards || []).filter(
    (c) => c.due_in_days != null && c.due_in_days === offset
  );
  return { tasks: openDue, cards: dueCards };
}

// One-line collapsed summary. Empty parts are dropped; nothing on -> sentinel.
function buildSummary({ eventCount, bringCount, earliestLeave, dueCount }) {
  const parts = [];
  if (eventCount > 0) parts.push(`${eventCount} event${eventCount === 1 ? "" : "s"}`);
  if (earliestLeave) parts.push(`leave ${earliestLeave}`);
  if (bringCount > 0) parts.push(`${bringCount} to bring`);
  if (dueCount > 0) parts.push(`${dueCount} due`);
  return parts.length ? parts.join(" · ") : "nothing scheduled today";
}

// Default-open-once-per-day: a new calendar day (or never-opened) forces open;
// otherwise the user's persisted toggle stands.
function shouldDefaultOpen(storedDay, persistedOpen, todayStr) {
  if (storedDay !== todayStr) return true;
  return !!persistedOpen;
}

// Suggested "bring" items derived purely from the forecast — what the day's
// weather implies you should grab, independent of any calendar event. Returns []
// when wx is null (progressive load) or nothing applies. Temps are °F (the app
// fetches Fahrenheit); codes are WMO weather codes. Order is intentional so the
// most weather-defining item leads. Kept here (pure, tested) and tagged in the UI
// so an auto-suggestion reads differently from an event-authored bring.
function weatherBring(wx) {
  if (!wx) return [];
  const out = [];
  const code = wx.code;
  const precip = wx.precip;                 // daily max precipitation probability %
  const hi = wx.hi != null ? wx.hi : wx.temp;
  const lo = wx.lo != null ? wx.lo : wx.temp;
  const rainy =
    (code >= 51 && code <= 67) || (code >= 80 && code <= 82) || code >= 95;
  const heavyRain =
    code === 65 || code === 82 || code === 99 || (precip != null && precip >= 80);
  const snowy = (code >= 71 && code <= 77) || code === 85 || code === 86;

  // snow days carry high precip too, so the precip->umbrella heuristic must yield
  // to snow: you want a coat, not an umbrella.
  if (!snowy && (rainy || (precip != null && precip >= 50))) out.push("umbrella");
  if (!snowy && heavyRain) out.push("rain jacket");
  if (snowy) { out.push("warm coat"); out.push("gloves"); }
  if (!snowy && lo != null && lo <= 35) out.push("warm layers");
  if (hi != null && hi >= 85) { out.push("water"); out.push("sunscreen"); }
  return out;
}

// Slice the flat forecast series down to one calendar day, for the 24-hour rail.
// `hours` is the WHOLE series (ascending, one entry per hour, each carrying a
// local `iso` "YYYY-MM-DDTHH:MM" and `hour` 0-23); the date half of the iso IS
// the local day key, so a string compare is the whole filter.
// Returns { hours, max } where `max` is the day's own peak rain chance — the
// rail scales its fill to that ceiling and prints it, because a 1%→35% climb
// drawn on a fixed 0-100% axis renders flat and reads as "nothing happens today".
// `hours` is [] and `max` 0 when the series is absent (a past day carries only
// its frozen daily summary), which is what makes the rail self-hide.
function dayRail(hours, dayIso) {
  if (!hours?.length || !dayIso) return { hours: [], max: 0 };
  const out = hours.filter((x) => x.iso.slice(0, 10) === dayIso);
  return { hours: out, max: out.reduce((m, x) => Math.max(m, x.precip || 0), 0) };
}

// "5p" / "12a" — compact 12-hour label for an hourly slot. Lowercase a/p with no
// space is the hub-wide clock shape (trips/triptime.js fmtClock is the canonical
// one); nothing here prints 24-hour.
function hourLabel(h) {
  const ampm = h >= 12 ? "p" : "a";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}${ampm}`;
}

// "5:42a" from an Open-Meteo local timestamp ("YYYY-MM-DDTHH:MM"). Returns ""
// for anything unparseable so a missing sunrise just renders nothing.
function clockLabel(iso) {
  if (!iso || iso.length < 16) return "";
  const h = parseInt(iso.slice(11, 13), 10);
  const m = iso.slice(14, 16);
  if (Number.isNaN(h)) return "";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:${m}${h >= 12 ? "p" : "a"}`;
}

/* ---- richer weather, all pure -------------------------------------------- */

// Rain (or snow) for one day, in words. `hours` is the day's rail slice, each
// hour carrying precip (% chance), inches (liquid, this hour), snow (inches).
// A wet hour is >=30% chance or measurable water. Returns
//   { kind: "dry" | "chance" | "rain" | "snow", text, from, to, peak, intensity, total }
// where from/to are hour numbers (to is exclusive), peak the wettest hour.
// Intensity bands are per-hour liquid: light <0.1 in, moderate <0.3, heavy after.
function precipWords(hours) {
  const hs = hours || [];
  if (!hs.length) return { kind: "dry", text: "" };
  const wet = hs.filter((h) => (h.precip || 0) >= 30 || (h.inches || 0) > 0 || (h.snow || 0) > 0);
  const snowy = hs.some((h) => (h.snow || 0) > 0);
  const maxP = hs.reduce((m, h) => Math.max(m, h.precip || 0), 0);
  if (!wet.length) {
    if (maxP < 15) return { kind: "dry", text: "no rain expected" };
    const at = hs.find((h) => h.precip === maxP);
    return { kind: "chance", text: `slight chance of rain, ${maxP}% around ${hourLabel(at.hour)}` };
  }
  const from = wet[0].hour;
  const to = wet[wet.length - 1].hour + 1;
  const amt = (h) => (snowy ? h.snow || 0 : h.inches || 0);
  const peak = wet.reduce((b, h) => (amt(h) > amt(b) || (amt(h) === amt(b) && (h.precip || 0) > (b.precip || 0)) ? h : b), wet[0]);
  const total = Math.round(hs.reduce((t, h) => t + amt(h), 0) * 100) / 100;
  const perHr = amt(peak);
  const intensity = perHr >= 0.3 ? "heavy" : perHr >= 0.1 ? "moderate" : perHr > 0 ? "light" : null;
  const span = to - from >= 24 ? "all day" : `${hourLabel(from)}–${hourLabel(to % 24)}`;
  const word = snowy ? "snow" : "rain";
  let text = `${intensity ? `${intensity} ` : ""}${word} ${span}`;
  if (to - from > 2 && intensity) text += `, heaviest ${hourLabel(peak.hour)}`;
  if (total > 0) text += `, ${total} in`;
  else if (!intensity) text = `chance of ${word} ${span}, up to ${maxP}%`;
  return { kind: snowy ? "snow" : "rain", text, from, to, peak: peak.hour, intensity, total };
}

// The rail hour under a minutes-since-midnight clock (a leave/return time).
// Past-midnight minutes (a rolled 1am end) clamp to the last hour of the day.
function readingAt(hours, minutes) {
  if (!hours?.length || minutes == null) return null;
  const h = Math.min(23, Math.max(0, Math.floor(minutes / 60)));
  return hours.find((x) => x.hour === h) || null;
}

// US AQI bands (EPA), lowercase to match the hub's voice.
function aqiWords(aqi) {
  if (aqi == null) return "";
  if (aqi <= 50) return "good";
  if (aqi <= 100) return "moderate";
  if (aqi <= 150) return "unhealthy for sensitive groups";
  if (aqi <= 200) return "unhealthy";
  if (aqi <= 300) return "very unhealthy";
  return "hazardous";
}

// Day of year from the local y/m/d via UTC arithmetic, so DST cannot shift it.
function dayOfYear(date) {
  const y = date.getFullYear();
  const jan1 = Date.UTC(y, 0, 1);
  return {
    doy: Math.round((Date.UTC(y, date.getMonth(), date.getDate()) - jan1) / 86400000) + 1,
    daysInYear: (Date.UTC(y + 1, 0, 1) - jan1) / 86400000,
  };
}

const API = {
  parseEventLabels,
  partifulAsks,
  eventKits,
  aggregateLabels,
  leaveSortKey,
  localDayString,
  addDays,
  dayOffset,
  selectDueItems,
  selectDueItemsForDay,
  buildSummary,
  shouldDefaultOpen,
  weatherBring,
  dayRail,
  hourLabel,
  clockLabel,
  precipWords,
  readingAt,
  aqiWords,
  dayOfYear,
};

if (typeof module !== "undefined" && module.exports) {
  module.exports = API;
} else {
  window.BriefingLogic = API;
}
