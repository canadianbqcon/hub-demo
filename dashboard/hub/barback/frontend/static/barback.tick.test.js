// Pure-function tests for the optimistic-tick + three-state cycle. Run with:
//   node barback.tick.test.js
const assert = require("node:assert");
const {
  nextDutyState, nextStockState, nextFillState, fillColor,
  summarizeProgress, summarizeFill, FILL_MAX, FILL_COLOR_FULL,
} = require("./barback.logic.js");

// Duty: open <-> done.
assert.strictEqual(nextDutyState("open"), "done");
assert.strictEqual(nextDutyState("done"), "open");

// Stock cycle: open -> good -> low -> out -> good (never back to open by tap).
assert.strictEqual(nextStockState("open"), "good");
assert.strictEqual(nextStockState("good"), "low");
assert.strictEqual(nextStockState("low"), "out");
assert.strictEqual(nextStockState("out"), "good");

// Progress: count items not 'open'.
assert.deepStrictEqual(
  summarizeProgress([{ state: "open" }, { state: "done" }, { state: "low" }]),
  { total: 3, done: 2, complete: false }
);
assert.deepStrictEqual(
  summarizeProgress([{ state: "done" }, { state: "good" }]),
  { total: 2, done: 2, complete: true }
);

// Fill: the state IS the count to grab. Tap ADDS one and never wraps — the old
// 0-1-2-3-0 cycle made a row needing 8 untappable and cost 3 taps to undo one.
assert.strictEqual(nextFillState("0"), "1");
assert.strictEqual(nextFillState("1"), "2");
assert.strictEqual(nextFillState("2"), "3");
assert.strictEqual(nextFillState("3"), "4"); // the regression this guards: was "0"
assert.strictEqual(nextFillState("7"), "8"); // counts past 3 are the point
// Clamped at the cap so a stuck finger cannot write an unbounded value.
assert.strictEqual(nextFillState(String(FILL_MAX)), String(FILL_MAX));
// A row left from the pre-017 binary model must not wedge the counter. The tap
// meant "add one", so it starts the count at 1 rather than resting at 0.
assert.strictEqual(nextFillState("done"), "1");
assert.strictEqual(nextFillState(undefined), "1");

// Gradient: 0 keeps the default row color, then green -> red as the count rises.
assert.strictEqual(fillColor("0"), null);
const hue = (s) => parseInt(fillColor(s).match(/hsl\((\d+)/)[1], 10);
assert.strictEqual(hue("1") < 90 && hue("1") > hue("2"), true);
assert.strictEqual(hue("2") > hue("3"), true);
assert.strictEqual(hue(String(FILL_COLOR_FULL)), 0); // ramp tops out red
// Past the ramp it holds red rather than wrapping back toward green.
assert.strictEqual(fillColor("40"), fillColor(String(FILL_COLOR_FULL)));
assert.strictEqual(hue("3") > 0, true); // 3 is no longer the red end

// Fill summary counts rows owing something and total units, ignoring 0s.
assert.deepStrictEqual(
  summarizeFill([{ state: "0" }, { state: "3" }, { state: "2" }]),
  { rows: 2, units: 5 }
);
assert.deepStrictEqual(summarizeFill([{ state: "0" }]), { rows: 0, units: 0 });

console.log("barback.tick.test.js: all passed");
