// Unit tests for the pure scaling engine in batch.js. Run: `node batch.scaling.test.js`
// (zero deps — the engine is pure; the DOM half of batch.js is guarded so require works).

const assert = require("node:assert");
const S = require("./batch.js");

let passed = 0;
function ok(name, cond) {
  assert.ok(cond, name);
  passed++;
}
function near(name, a, b, eps) {
  assert.ok(Math.abs(a - b) <= (eps || 1e-6), `${name} (got ${a}, want ${b})`);
  passed++;
}

// --- factor math: weighed row scales linearly ---
const cordial = { ingredient: "citrus cordial", amount: "oz/2", qty: 3375, unit: "g", scalable: 1 };
near("full batch keeps grams", S.scaleAmount(cordial, 1).grams, 3375);
near("half batch halves grams", S.scaleAmount(cordial, 0.5).grams, 1687.5);
near("quarter batch quarters grams", S.scaleAmount(cordial, 0.25).grams, 843.75);
near("custom 1.47x", S.scaleAmount(cordial, 1.47).grams, 4961.25);
ok("weighed kind is 'weighed'", S.scaleAmount(cordial, 1).kind === "weighed");

// --- oz conversion uses the 29.5735 g/oz card basis ---
near("oz conversion factor", S.OZ_IN_G, 29.5735);
near("3375 g -> oz", S.formatWeighed(3375, true).num, 3375 / 29.5735);
ok("formatWeighed oz unit", S.formatWeighed(100, true).unit === "oz");
ok("formatWeighed g unit", S.formatWeighed(100, false).unit === "g");
// 128 oz of water = 1 US gallon = 3785.41 g (the reconciliation proof)
near("gallon-of-water check", S.formatWeighed(3785.41, true).num, 128, 0.01);

// --- non-scalable passthrough: 'to taste' / 'in batch' show their text, never a number ---
const demerara = { ingredient: "Demerara", amount: "to taste", qty: null, unit: null, scalable: 0 };
ok("non-scalable kind is 'text'", S.scaleAmount(demerara, 0.5).kind === "text");
ok("non-scalable shows its text", S.scaleAmount(demerara, 0.5).text === "to taste");
const emptyText = { ingredient: "x", amount: "", qty: null, unit: null, scalable: 0 };
ok("empty amount falls back to 'to taste'", S.scaleAmount(emptyText, 1).text === "to taste");

// --- count scaling: containers scale by count, stay outside the g/oz toggle ---
const sugarcane = { ingredient: "sugar cane", amount: "1 gallon", qty: 1, unit: "gallon", scalable: 1 };
const c = S.scaleAmount(sugarcane, 1.5);
ok("count kind is 'count'", c.kind === "count");
near("count scales by factor", c.value, 1.5);
ok("count keeps its unit", c.unit === "gallon");
ok("count formats trimmed", S.fmtCount(1.5) === "1.5" && S.fmtCount(3) === "3");

// --- edit-any-ingredient: typing a value derives the whole-batch factor ---
near("edit weighed in g -> factor", S.factorFromEdit(cordial, 1687.5, false), 0.5);
near("edit weighed in oz -> factor (normalises to g)", S.factorFromEdit(cordial, (3375 / 29.5735), true), 1);
near("edit count -> factor (no oz normalise)", S.factorFromEdit(sugarcane, 3, true), 3);
ok("edit non-scalable returns null", S.factorFromEdit(demerara, 5, false) === null);
ok("edit zero-base returns null", S.factorFromEdit({ qty: 0, scalable: 1, unit: "g" }, 5, false) === null);

// --- display formatting: grams whole, oz to 1-2 dp, trailing zeros trimmed ---
ok("grams render whole at scale", S.fmtWeighed(1687.5, false) === "1688" || S.fmtWeighed(1687.5, false) === "1687");
ok("oz under 10 -> 2dp", S.fmtWeighed(150, true) === S.trimNum(150 / 29.5735, 2));
ok("trimNum strips trailing zeros", S.trimNum(3.0, 2) === "3" && S.trimNum(1.5, 2) === "1.5");

// --- category bucketing: discontinued/retired collapse and sink to the bottom ---
ok("discontinued sub-type collapses", S.catBucket({ category: "Discontinued \u2014 Syrup" }) === "Discontinued");
ok("retired collapses too", S.catBucket({ category: "Retired \u2014 House Batch" }) === "Discontinued");
ok("live category untouched", S.catBucket({ category: "Cordial" }) === "Cordial");
ok("null category falls back", S.catBucket({}) === "Uncategorized");
ok("a name merely containing the word is live",
   S.catBucket({ category: "Syrup (discontinued vendor)" }) === "Syrup (discontinued vendor)");
const order = [
  { category: "Syrup", name: "Honey" },
  { category: "Discontinued \u2014 Garnish", name: "Dead A" },
  { category: "Cordial", name: "Citrus" },
  { category: "Retired \u2014 House Batch", name: "Dead B" },
  { category: "Coffee", name: "Cold Brew" },
].sort(S.byCategoryThenName).map((r) => r.name);
ok("live categories stay alpha, dead ones sink to one bucket at the end",
   JSON.stringify(order) === JSON.stringify(["Cold Brew", "Citrus", "Honey", "Dead A", "Dead B"]));

console.log(`\n  batch engine: ${passed} assertions passed\n`);
