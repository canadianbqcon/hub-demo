// Pure state-transition + progress helpers. No DOM, no fetch — unit-tested under
// node and reused by barback.js in the browser.
function nextDutyState(state) {
  return state === "done" ? "open" : "done";
}

function nextStockState(state) {
  // open -> good -> low -> out -> good (tap never returns to 'open').
  const cycle = { open: "good", good: "low", low: "out", out: "good" };
  return cycle[state] || "good";
}

// fill: the state IS the count to grab. Tap ADDS one and never wraps — clearing
// is an explicit action (the row's clear, or "clear all"). Mirrors
// db.next_fill_state / db._FILL_MAX — keep the two in step.
const FILL_MAX = 99;
// Where the color ramp tops out. Separate from FILL_MAX because the cap only
// exists to bound the stored value; spreading green->red over 99 would make
// every realistic count look identically green.
const FILL_COLOR_FULL = 5;

function nextFillState(state) {
  const n = parseInt(state, 10);
  if (!Number.isFinite(n)) return "1"; // the tap meant "add one"
  return String(Math.min(n + 1, FILL_MAX));
}

// 1 green -> FILL_COLOR_FULL red, stepping through the hues between, then held
// at red for anything higher. Returned as an hsl() string so one expression
// covers every step and a bigger count needs no new color.
function fillColor(state) {
  const n = Math.max(parseInt(state, 10) || 0, 0);
  if (n === 0) return null; // resting rows stay in the default row color
  const hue = 90 - (Math.min(n, FILL_COLOR_FULL) / FILL_COLOR_FULL) * 90; // 90 green ... 0 red
  return `hsl(${Math.round(hue)}, 72%, 44%)`;
}

function summarizeProgress(items) {
  const total = items.length;
  const done = items.filter((i) => i.state !== "open").length;
  return { total, done, complete: total > 0 && done === total };
}

// fill runs have no "done" — the number that matters is what is still owed.
function summarizeFill(items) {
  const rows = items.filter((i) => (parseInt(i.state, 10) || 0) > 0);
  const units = rows.reduce((sum, i) => sum + (parseInt(i.state, 10) || 0), 0);
  return { rows: rows.length, units };
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    nextDutyState, nextStockState, nextFillState, fillColor,
    summarizeProgress, summarizeFill, FILL_MAX, FILL_COLOR_FULL,
  };
} else {
  window.BarbackLogic = {
    nextDutyState, nextStockState, nextFillState, fillColor,
    summarizeProgress, summarizeFill, FILL_MAX, FILL_COLOR_FULL,
  };
}
