// Pure-function tests for the Today-briefing logic. Run with:
//   node briefing.logic.test.js
const assert = require("node:assert");
const L = require("./briefing.logic.js");

// --- parseEventLabels ---
// undefined description (trip events carry no description key) must not throw.
assert.deepStrictEqual(L.parseEventLabels(undefined), { bring: [], prep: [], leave: [], note: [] });
assert.deepStrictEqual(L.parseEventLabels(""), { bring: [], prep: [], leave: [], note: [] });

// one item per line; comma kept literal; case-insensitive label; value trimmed.
const parsed = L.parseEventLabels("Bring: passport, charger\nprep: pack bag\nLEAVE: 18:45\nnote: ID required\nfree text line");
assert.deepStrictEqual(parsed.bring, ["passport, charger"]);
assert.deepStrictEqual(parsed.prep, ["pack bag"]);
assert.deepStrictEqual(parsed.leave, ["18:45"]);
assert.deepStrictEqual(parsed.note, ["ID required"]);

// --- aggregateLabels ---
const agg = L.aggregateLabels([
  { name: "J&Co", description: "leave: 18:45\nbring: umbrella" },
  { name: "Gym", description: "bring: Umbrella\nbring: towel\nnote: locker 12" },
]);
// bring deduped case-insensitively across events, first-seen casing kept.
assert.deepStrictEqual(agg.bring, ["umbrella", "towel"]);
// leave items keep source + sort by text.
assert.deepStrictEqual(agg.leave, [{ text: "18:45", src: "J&Co" }]);
// note items keep source.
assert.deepStrictEqual(agg.note, [{ text: "locker 12", src: "Gym" }]);

// leave sorted by text across events.
const agg2 = L.aggregateLabels([
  { name: "Late", description: "leave: 19:30" },
  { name: "Early", description: "leave: 08:15" },
]);
assert.deepStrictEqual(agg2.leave, [
  { text: "08:15", src: "Early" },
  { text: "19:30", src: "Late" },
]);

// leave sorted by actual time, not string: 15:15 must come AFTER 9:10
// (a plain localeCompare would put "15:15" first because '1' < '9').
const aggTime = L.aggregateLabels([
  { name: "Afternoon", description: "leave: 15:15" },
  { name: "Morning", description: "leave: 9:10" },
]);
assert.deepStrictEqual(aggTime.leave, [
  { text: "9:10", src: "Morning" },
  { text: "15:15", src: "Afternoon" },
]);

// --- leaveSortKey ---
assert.strictEqual(L.leaveSortKey("9:10"), 550);          // 9*60+10
assert.strictEqual(L.leaveSortKey("15:15"), 915);         // 24h
assert.strictEqual(L.leaveSortKey("leave by 9:10am"), 550);
assert.strictEqual(L.leaveSortKey("3:15 pm"), 915);       // 12h pm
assert.strictEqual(L.leaveSortKey("12:00 am"), 0);        // midnight
assert.strictEqual(L.leaveSortKey("12:30 pm"), 750);      // noon stays 12
assert.strictEqual(L.leaveSortKey("no time here"), Infinity);

// --- localDayString ---
assert.strictEqual(L.localDayString("2026-06-22T09:00:00"), "2026-06-22");

// --- selectDueItems ---
const due = L.selectDueItems(
  [
    { id: 1, due_target: "2026-06-22T17:00:00" }, // due today
    { id: 2, due_target: "2026-06-20T09:00:00" }, // overdue
    { id: 3, due_target: "2026-06-25T09:00:00" }, // future -> excluded
    { id: 4 },                                    // no due_target -> excluded
  ],
  [
    { name: "A", status: "due", due_in_days: 0 },   // due today -> include
    { name: "B", status: "overdue", due_in_days: 3 }, // overdue status -> include
    { name: "C", status: "due", due_in_days: 5 },   // future -> exclude
    { name: "D", status: "paid", due_in_days: 0 },  // paid -> exclude
  ],
  "2026-06-22"
);
assert.deepStrictEqual(due.tasks.map((t) => t.id), [1, 2]);
assert.deepStrictEqual(due.cards.map((c) => c.name), ["A", "B"]);
// null inputs tolerated (progressive load).
assert.deepStrictEqual(L.selectDueItems(null, null, "2026-06-22"), { tasks: [], cards: [] });

// --- buildSummary ---
assert.strictEqual(
  L.buildSummary({ eventCount: 3, bringCount: 2, earliestLeave: "18:45", dueCount: 1 }),
  "3 events · leave 18:45 · 2 to bring · 1 due"
);
// empty parts dropped.
assert.strictEqual(
  L.buildSummary({ eventCount: 2, bringCount: 0, earliestLeave: null, dueCount: 0 }),
  "2 events"
);
// nothing on -> sentinel.
assert.strictEqual(
  L.buildSummary({ eventCount: 0, bringCount: 0, earliestLeave: null, dueCount: 0 }),
  "nothing scheduled today"
);

// --- weatherBring ---
assert.deepStrictEqual(L.weatherBring(null), []);                                   // progressive load -> nothing
assert.deepStrictEqual(L.weatherBring({ code: 0, temp: 70, hi: 72, lo: 60, precip: 0 }), []); // clear, mild -> nothing
// heavy rain (code 65) -> umbrella + rain jacket
assert.deepStrictEqual(L.weatherBring({ code: 65, temp: 57, hi: 61, lo: 53, precip: 95 }), ["umbrella", "rain jacket"]);
// light rain (code 61), modest precip -> umbrella only
assert.deepStrictEqual(L.weatherBring({ code: 61, temp: 58, hi: 60, lo: 54, precip: 55 }), ["umbrella"]);
// high precip prob on an otherwise-dry code still suggests umbrella
assert.deepStrictEqual(L.weatherBring({ code: 3, temp: 60, hi: 62, lo: 55, precip: 70 }), ["umbrella"]);
// snow -> coat + gloves (no rain items)
assert.deepStrictEqual(L.weatherBring({ code: 73, temp: 28, hi: 31, lo: 22, precip: 90 }), ["warm coat", "gloves"]);
// cold + dry -> warm layers
assert.deepStrictEqual(L.weatherBring({ code: 1, temp: 30, hi: 34, lo: 28, precip: 0 }), ["warm layers"]);
// hot -> water + sunscreen
assert.deepStrictEqual(L.weatherBring({ code: 0, temp: 90, hi: 92, lo: 74, precip: 0 }), ["water", "sunscreen"]);
// missing hi/lo falls back to temp
assert.deepStrictEqual(L.weatherBring({ code: 0, temp: 88, hi: null, lo: null, precip: null }), ["water", "sunscreen"]);

// --- dayRail / hourLabel / clockLabel ---
// three consecutive days of hourly entries, exactly the shape useNycWeather builds
const series = [];
for (const d of ["2026-07-27", "2026-07-28", "2026-07-29"]) {
  for (let h = 0; h < 24; h++) {
    series.push({ iso: `${d}T${String(h).padStart(2, "0")}:00`, hour: h, temp: 60 + h, precip: h });
  }
}
// one calendar day out of the flat series, and that day's own rain ceiling
const rail = L.dayRail(series, "2026-07-28");
assert.strictEqual(rail.hours.length, 24);
assert.strictEqual(rail.hours[0].iso, "2026-07-28T00:00");
assert.strictEqual(rail.hours[23].iso, "2026-07-28T23:00");
assert.strictEqual(rail.max, 23);
// the ceiling is the DAY's peak, not 100 — this is what the fill scales against
assert.strictEqual(L.dayRail([
  { iso: "2026-07-28T00:00", hour: 0, precip: 1 },
  { iso: "2026-07-28T01:00", hour: 1, precip: 35 },
], "2026-07-28").max, 35);
// null precip counts as dry rather than poisoning the max
assert.strictEqual(L.dayRail([{ iso: "2026-07-28T00:00", hour: 0, precip: null }], "2026-07-28").max, 0);
// missing series / unknown day (past day, progressive load) -> no rail
assert.deepStrictEqual(L.dayRail([], "2026-07-27"), { hours: [], max: 0 });
assert.deepStrictEqual(L.dayRail(undefined, "2026-07-27"), { hours: [], max: 0 });
assert.deepStrictEqual(L.dayRail(series, null), { hours: [], max: 0 });
assert.deepStrictEqual(L.dayRail(series, "2026-01-01"), { hours: [], max: 0 });
assert.strictEqual(L.hourLabel(0), "12a");
assert.strictEqual(L.hourLabel(9), "9a");
assert.strictEqual(L.hourLabel(12), "12p");
assert.strictEqual(L.hourLabel(23), "11p");
assert.strictEqual(L.clockLabel("2026-07-27T05:42"), "5:42a");
assert.strictEqual(L.clockLabel("2026-07-27T20:24"), "8:24p");
assert.strictEqual(L.clockLabel("2026-07-27T00:05"), "12:05a");
assert.strictEqual(L.clockLabel(null), "");
assert.strictEqual(L.clockLabel("2026-07-27"), "");

// --- shouldDefaultOpen ---
assert.strictEqual(L.shouldDefaultOpen("2026-06-21", false, "2026-06-22"), true);  // new day -> open
assert.strictEqual(L.shouldDefaultOpen(null, false, "2026-06-22"), true);          // never opened -> open
assert.strictEqual(L.shouldDefaultOpen("2026-06-22", false, "2026-06-22"), false); // same day -> keep closed
assert.strictEqual(L.shouldDefaultOpen("2026-06-22", true, "2026-06-22"), true);   // same day -> keep open

// --- addDays / dayOffset ---
assert.strictEqual(L.addDays("2026-06-24", 1), "2026-06-25");
assert.strictEqual(L.addDays("2026-06-24", -1), "2026-06-23");
assert.strictEqual(L.addDays("2026-06-30", 1), "2026-07-01");   // month rollover
assert.strictEqual(L.addDays("2026-03-01", -1), "2026-02-28");  // month underflow
assert.strictEqual(L.addDays("2026-06-24", 7), "2026-07-01");
assert.strictEqual(L.dayOffset("2026-06-24", "2026-06-24"), 0);
assert.strictEqual(L.dayOffset("2026-06-24", "2026-06-27"), 3);
assert.strictEqual(L.dayOffset("2026-06-24", "2026-06-21"), -3);
assert.strictEqual(L.dayOffset("2026-06-30", "2026-07-01"), 1); // across month boundary

// --- selectDueItemsForDay ---
const dfdTasks = [
  { id: 1, title: "overdue", due_target: "2026-06-22T09:00:00" },
  { id: 2, title: "due today", due_target: "2026-06-24T09:00:00" },
  { id: 3, title: "due +3", due_target: "2026-06-27T09:00:00" },
];
const dfdCards = [
  { name: "card today", status: "due", due_in_days: 0 },
  { name: "card +3", status: "due", due_in_days: 3 },
  { name: "card overdue", status: "overdue", due_in_days: -2 },
];
// Completed (done) tasks are never due items on any day — a finished job belongs
// in the recap, not an action list. id:10 was due 06-22 and finished 06-23,
// id:11 had no due date and was finished 06-22, id:12 was due and finished
// 06-21; none of them may surface below.
const dfdDone = [
  { id: 10, title: "done late", due_target: "2026-06-22T09:00:00", completed_date: "2026-06-23", done: true },
  { id: 11, title: "done, no due", completed_date: "2026-06-22", done: true },
  { id: 12, title: "done same day", due_target: "2026-06-21T09:00:00", completed_date: "2026-06-21", done: true },
];
// today (selected === today): identical to selectDueItems — overdue + due-today.
const dfdToday = L.selectDueItemsForDay(dfdTasks, dfdCards, "2026-06-24", "2026-06-24");
assert.deepStrictEqual(dfdToday.tasks.map((t) => t.id), [1, 2]);
assert.deepStrictEqual(dfdToday.cards.map((c) => c.name), ["card today", "card overdue"]);
// a future day: only what's due on that exact day (task by due_target, card by offset).
const dfdFuture = L.selectDueItemsForDay(dfdTasks, dfdCards, "2026-06-27", "2026-06-24");
assert.deepStrictEqual(dfdFuture.tasks.map((t) => t.id), [3]);
assert.deepStrictEqual(dfdFuture.cards.map((c) => c.name), ["card +3"]);
// a past day (06-22): only the open task due then (id:1) and the card whose
// offset (-2) matches. id:10/id:11 are done, so they stay out.
const dfdPast = L.selectDueItemsForDay(dfdTasks, dfdCards, "2026-06-22", "2026-06-24");
assert.deepStrictEqual(dfdPast.tasks.map((t) => t.id), [1]);
assert.deepStrictEqual(dfdPast.cards.map((c) => c.name), ["card overdue"]);
// a past day whose only candidate is a completed task (06-23, id:10 finished
// then; 06-21, id:12 due and finished then) carries nothing.
assert.deepStrictEqual(L.selectDueItemsForDay(dfdTasks, dfdCards, "2026-06-23", "2026-06-24").tasks, []);
assert.deepStrictEqual(L.selectDueItemsForDay(dfdTasks, dfdCards, "2026-06-21", "2026-06-24").tasks, []);
// a stray 5th arg (an old caller passing its completed list) changes nothing.
assert.deepStrictEqual(
  L.selectDueItemsForDay(dfdTasks, dfdCards, "2026-06-22", "2026-06-24", dfdDone).tasks.map((t) => t.id), [1]
);
// a future day with nothing due carries no cards.
assert.deepStrictEqual(L.selectDueItemsForDay(dfdTasks, dfdCards, "2026-06-25", "2026-06-24").cards, []);
// null inputs -> empty lists, no throw.
assert.deepStrictEqual(L.selectDueItemsForDay(null, null, "2026-06-25", "2026-06-24"), { tasks: [], cards: [] });

console.log("briefing.logic.test.js: all passed");

// --- precipWords ---
const H = (hour, precip, inches = 0, snow = 0, temp = 70) => ({ hour, precip, inches, snow, temp });
assert.deepStrictEqual(L.precipWords([]), { kind: "dry", text: "" });
assert.strictEqual(L.precipWords([H(0, 5), H(1, 10)]).text, "no rain expected");
assert.strictEqual(L.precipWords([H(0, 5), H(15, 22)]).text, "slight chance of rain, 22% around 3p");
// 2p-6p, heaviest at 4p, moderate, totals summed and rounded
const rain = L.precipWords([H(13, 10), H(14, 60, 0.05), H(15, 80, 0.12), H(16, 90, 0.25), H(17, 70, 0.08), H(18, 20)]);
assert.strictEqual(rain.kind, "rain");
assert.strictEqual(rain.text, "moderate rain 2p–6p, heaviest 4p, 0.5 in");
assert.deepStrictEqual([rain.from, rain.to, rain.peak], [14, 18, 16]);
// chance without measurable water: no intensity word, ceiling printed
assert.strictEqual(L.precipWords([H(8, 40), H(9, 35)]).text, "chance of rain 8a–10a, up to 40%");
// snow wins over rain wording; snowfall amounts drive the peak
const snow = L.precipWords([H(6, 70, 0.02, 0.4), H(7, 80, 0.03, 0.8), H(8, 60, 0.01, 0.2)]);
assert.strictEqual(snow.kind, "snow");
assert.strictEqual(snow.text, "heavy snow 6a–9a, heaviest 7a, 1.4 in");
// every hour wet reads "all day"
assert.strictEqual(L.precipWords(Array.from({ length: 24 }, (_, i) => H(i, 50, 0.05))).text, "light rain all day, heaviest 12a, 1.2 in");

// --- readingAt ---
const day = [H(7, 0, 0, 0, 61), H(8, 0, 0, 0, 63), H(23, 0, 0, 0, 55)];
assert.strictEqual(L.readingAt(day, 8 * 60 + 30).temp, 63);
assert.strictEqual(L.readingAt(day, 25 * 60).temp, 55);   // rolled past midnight clamps to 11p
assert.strictEqual(L.readingAt(day, 9 * 60), null);         // no entry for that hour
assert.strictEqual(L.readingAt(null, 60), null);

// --- aqiWords ---
assert.strictEqual(L.aqiWords(null), "");
assert.strictEqual(L.aqiWords(42), "good");
assert.strictEqual(L.aqiWords(58), "moderate");
assert.strictEqual(L.aqiWords(151), "unhealthy");
assert.strictEqual(L.aqiWords(400), "hazardous");

// --- dayOfYear ---
const D = (...a) => L.dayOfYear(new Date(...a));
assert.strictEqual(D(2026, 0, 1).doy, 1);
assert.strictEqual(D(2028, 1, 29).doy, 60);
assert.strictEqual(D(2028, 11, 31).doy, 366);
assert.strictEqual(D(2026, 9, 15).doy, 288);
assert.strictEqual(D(2026, 9, 15, 23, 59).doy, 288);
assert.strictEqual(D(2026, 2, 8).doy, 67);   // DST start day in the US
assert.strictEqual(D(2026, 10, 1).doy, 305); // day after DST end
assert.strictEqual(D(2026, 5, 1).daysInYear, 365);
assert.strictEqual(D(2028, 5, 1).daysInYear, 366);

console.log("briefing.logic tests ok");
