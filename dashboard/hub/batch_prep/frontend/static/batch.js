// ============================================================
// j&co batch-prep frontend.
//
// The pure scaling engine: no DOM, no fetch, so it unit-tests under node (see
// frontend/static/batch.scaling.test.js). The panel itself is the React body in
// batch-core.jsx, batch-rows.jsx and batch.jsx, which call these globals.
// ============================================================

// ---- pure scaling engine ----------------------------------------------------

// One fixed display factor, fluid-ounce-of-water basis. Matches the laminated
// recipe cards exactly (see the module CLAUDE.md units model). Applied only to
// weighed (unit==='g') rows; counts and to-taste text sit outside it.
var OZ_IN_G = 29.5735;

// Resolve one ingredient at a given batch factor into a display shape.
//   scalable===0 / no qty  -> {kind:'text', text}              (e.g. "to taste")
//   weighed (unit==='g')   -> {kind:'weighed', grams}          (toggle g/oz)
//   count  (other unit)    -> {kind:'count', value, unit}      (e.g. 1.5 quart)
function scaleAmount(ing, factor) {
  if (!ing.scalable || ing.qty == null) {
    return { kind: "text", text: (ing.amount && String(ing.amount).trim()) || "to taste" };
  }
  var scaled = ing.qty * factor;
  if (ing.unit === "g") {
    return { kind: "weighed", grams: scaled };
  }
  return { kind: "count", value: scaled, unit: ing.unit };
}

// Convert a weighed gram value to the chosen display unit.
function formatWeighed(grams, useOz) {
  if (useOz) return { num: grams / OZ_IN_G, unit: "oz" };
  return { num: grams, unit: "g" };
}

// New batch factor when the user types a value straight into one ingredient row.
// The typed value is read in whatever unit is currently displayed, normalised
// back to the row's stored base (grams for weighed, native count otherwise), and
// divided by the row's base qty. Non-scalable rows return the factor unchanged.
function factorFromEdit(ing, newValue, useOz) {
  if (!ing.scalable || ing.qty == null || !(ing.qty > 0)) return null;
  var grams;
  if (ing.unit === "g" && useOz) {
    grams = newValue * OZ_IN_G;
  } else {
    grams = newValue; // already in grams (weighed+g) or in native count units
  }
  return grams / ing.qty;
}

// Round to `places` decimals and trim trailing zeros ("1.50"->"1.5", "3.0"->"3").
function trimNum(n, places) {
  if (!Number.isFinite(n)) return "0";
  var s = n.toFixed(places);
  if (s.indexOf(".") !== -1) s = s.replace(/0+$/, "").replace(/\.$/, "");
  return s;
}

// Display string for a scaled weighed value. Grams read whole at scale (a bar
// scale doesn't show sub-gram); ounces keep one decimal (two when under 10).
function fmtWeighed(grams, useOz) {
  var w = formatWeighed(grams, useOz);
  if (useOz) return trimNum(w.num, w.num < 10 ? 2 : 1);
  return trimNum(w.num, 0);
}

// Display string for a scaled count (quarts/cans/gallons): up to 2 decimals.
function fmtCount(value) {
  return trimNum(value, 2);
}

// Discontinued/retired recipes collapse into ONE bucket pinned to the bottom of
// the list instead of scattering alphabetically ("Discontinued — Syrup" landing
// between "Cordial" and "Float"). The full stored category still shows in the
// recipe panel, so the old sub-type isn't lost.
var DEAD_CAT = /^\s*(discontinued|retired)\b/i;
function catBucket(r) {
  var cat = (r?.category) || "Uncategorized";
  return DEAD_CAT.test(cat) ? "Discontinued" : cat;
}
function byCategoryThenName(a, b) {
  var ca = catBucket(a), cb = catBucket(b);
  var da = ca === "Discontinued" ? 1 : 0, db = cb === "Discontinued" ? 1 : 0;
  if (da !== db) return da - db;
  var la = ca.toLowerCase(), lb = cb.toLowerCase();
  if (la !== lb) return la < lb ? -1 : 1;
  var na = a.name.toLowerCase(), nb = b.name.toLowerCase();
  return na < nb ? -1 : (na > nb ? 1 : 0);
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    OZ_IN_G: OZ_IN_G,
    scaleAmount: scaleAmount,
    formatWeighed: formatWeighed,
    factorFromEdit: factorFromEdit,
    fmtWeighed: fmtWeighed,
    fmtCount: fmtCount,
    trimNum: trimNum,
    catBucket: catBucket,
    byCategoryThenName: byCategoryThenName,
  };
}
