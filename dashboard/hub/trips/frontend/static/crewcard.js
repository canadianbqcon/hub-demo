/* crewcard.js — how a crew member renders as a card, and nothing else.
 *
 * Lifted verbatim out of trips.js so TWO surfaces can draw the same card: the
 * board's crew grid, and the account page's card designer. The designer's whole
 * claim is that its preview IS the board card rather than a specimen of one, and
 * a copied render is how that claim quietly stops being true. One file, one
 * answer, both callers.
 *
 * What did NOT come across is anything that needs the board: `state`, the delete
 * button, the forms footer, the "loading prefs…" marker. Those arrive through
 * `opts` on the render call, so this file has no idea a board exists.
 *
 * Styling lives in trips.css (the base .ccard block, plus its liquid block).
 * Any page loading this loads that. The card customization (header / shimmer /
 * border slots and the foil) was removed (2026-10-15); see git history for dashboard/archive/card-customization.
 */
window.CrewCard = (() => {
  

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const INTEREST_VERDICT_LABEL = {
    "everyone-must": "everyone must", "shared-want": "shared want",
    "ok-for-all": "ok for all", "someone-rather-not": "pushback",
    "vetoed": "vetoed", "unrated": "unrated",
  };
  // Same five server verdicts, said the way the cuisines grid asks its question.
  // Interests asks whether to DO a thing, so "everyone must" is the right read of
  // a floor of `must`; cuisines asks whether you LIKE a food, where the same floor
  // means everyone loves it and nobody is committing to eat it.
  const CUISINE_VERDICT_LABEL = {
    ...INTEREST_VERDICT_LABEL,
    "everyone-must": "everyone loves", "shared-want": "shared like",
  };
  // "1-2-mi" → "1–2 mi", but a dash between two digits is a range, not a word
  // separator. Fallback only — every real answer goes through label() below.
  const humanizeEnum = (raw) => raw == null ? "" : String(raw)
    .replace(/(\d)-(\d)/g, "$1–$2").replace(/-/g, " ").replace(/(\d)(min|hr|hrs|h|m)\b/gi, "$1 $2");

  // The summary is written for the contact node, where it opens with the person's
  // full name and can trail a "see the v2 revision in his source" aside. Both are
  // noise on a card that already shows the name and does not link the source.
  function cleanSummary(name, summary) {
    const nameRe = String(name || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const s = String(summary || "")
      .replace(new RegExp(`^${nameRe}\\s*[—–-]\\s*`, "i"), "")
      .replace(/\s*\([^()]*\b(?:see|revision|v\d|version|note in (?:his|her|their|the) source)\b[^()]*\)/gi, "")
      .replace(/\s*[—–-]\s*see [^—–.;)]*?\bsource\b[^.;)]*/gi, "")
      .replace(/\s+([,;.])/g, "$1").replace(/\s{2,}/g, " ").trim();
    return s ? s.charAt(0).toUpperCase() + s.slice(1) : "";
  }

  // All six always render, in this order, answered or not. Dropping an
  // unanswered one shifts every later fact into a different cell of the card's
  // 2-column grid, so "walking" would sit on the left for one person and on the
  // right for the next — the same unpredictability the grid exists to remove.
  // Each row is [caption, question key, raw value, free-text override]. The words
  // are NOT carried: factCell looks them up from the same key it draws the bar
  // from, so a cell cannot print one question's word over another question's
  // position. It used to carry them, and the two label maps that fed it disagreed
  // — `adventure` came through the travel map here and the food map two functions
  // down, for the same answer.
  function crewFacts(p, fp) {
    const chill = p.chill_days == null || p.chill_days === "" ? "" : String(p.chill_days);
    return [
      ["active", "active_hours", p.active_hours],
      ["start", "start_time", p.start_time],
      ["chill days", "chill_days", chill],
      // The food form owns this question. The travel form used to ask the same
      // one on the same scale, and the two answers drifted apart.
      ["food", "adventure", fp?.adventure],
      // walking_other is free text and has no place on the scale; passing it as
      // the override prints it and leaves the raw value empty, so no bar is drawn.
      ["walking", "walking", p.walking_other ? "" : p.walking, p.walking_other],
      ["travels for", "distance_willing", p.distance_willing],
    ].map(factCell).join("");
  }

  // One cell, one shape, both fact blocks. The bar rides inside the value span and
  // trips.css takes it out of flow (absolute, on 5px of reserved padding), for the
  // ellipsis rather than for the height: `.cfact-v` truncates a long value, which
  // needs its text to stay the block's only in-flow content. Nothing here is
  // height-floored to a fixed card — `.ccard-head` and `.ccard-pills` have their
  // own min-heights and the cards grow freely below them — so every card gains
  // the same 5px and the grid stays aligned.
  function factCell([k, key, raw, override]) {
    const v = override || label(key, raw);
    return `<span class="hub-card-fact cfact"><span class="hub-card-fact-k cfact-k">${esc(k)}</span>${v
      // free text (walking_other) outruns a half-card cell; the full value is
      // one hover away rather than wrapping the row to a second line
      ? `<span class="hub-card-fact-v cfact-v" title="${esc(v)}">${esc(v)}${sbar(key, raw)}</span>`
      : `<span class="hub-card-fact-v cfact-v cempty">—</span>`}</span>`;
  }

  // Only the three that can wreck a plan get a card slot, each with its own tone.
  // An empty one still renders — "no dealbreakers" is information, and a missing
  // row reads as unasked rather than as answered-none.
  function crewNotes(p, fp) {
    // The food form asks this properly — allergies and won't-eat as two separate
    // questions — where the travel form has one free-text line that predates it.
    // So the food answers SUPERSEDE rather than append: Akshay answered "I hate
    // seafood", "Seafood ew." and "Seafood. Sushi." across the two, and joining
    // them printed the same fact three times. The travel line still shows for
    // anyone who has not done the food form. An allergy is the one answer on
    // either form that can put someone in hospital, so it is not staying two
    // clicks deep in the detail rail.
    const diet = [(fp?.allergies || ""), (fp?.wont_eat || "")]
      .filter(Boolean).join(" · ");
    return [
      ["hard no", p.absolute_nos, "alert"],
      ["diet", diet, fp?.allergies ? "alert" : "warn"],
      ["limits", p.physical_limits, "warn"],
    ].map(([k, v, tone]) => `<div class="hub-card-note${v ? ` is-${tone} cnote-${tone}` : ""}">
        <span class="hub-card-note-k">${esc(k)}</span><span class="hub-card-note-v cnote-v">${v ? esc(v) : "none"}</span></div>`).join("");
  }

  // ── the words ───────────────────────────────────────────────────────────────
  //
  // Every display label, keyed by QUESTION then value, straight off the server
  // (preferences.LABELS) on the same payload as the scales. Nothing here keeps a
  // copy. Three maps used to: the Google Form's prose on the form, PREF_LABEL for
  // travel, FOOD_LABEL for food — so one answer was "About 9 hours, most of the
  // day with breaks" on the form and "~9 hrs" on the card, and `none` needed a
  // fourth map (FOOD_FIELD_LABEL) to stop the drinks row printing "mild only" for
  // a non-drinker. Keyed by question, that class of bug cannot be written.
  let LABELS = {};
  function setLabels(m) { if (m && typeof m === "object") LABELS = m; }
  // `key` is the question. humanizeEnum is the fallback for a value the table has
  // never heard of, which should look like a rough edge rather than a blank.
  const label = (key, raw) => (raw == null || raw === "") ? ""
    : (LABELS[key]?.[String(raw)] || humanizeEnum(raw));

  // Same shape as crewFacts, same reason every row renders answered or not: a
  // dropped row shifts every later one into a different cell of the grid.
  function foodFacts(fp) {
    return [
      ["spice", "spice", fp.spice],
      ["adventure", "adventure", fp.adventure],
      ["sharing", "sharing", fp.sharing],
      ["spend pp", "spend", fp.spend],
      ["goes for", "venue", fp.venue],
      ["booking", "reservations", fp.reservations],
      ["funk", "funk", fp.funk],
      ["offal", "offal", fp.offal],
      ["raw", "raw", fp.raw],
      ["drinks", "alcohol", fp.alcohol],
    ].map(factCell).join("");
  }

  // Allergies lead and carry alert tone. It is the one answer on either form that
  // can put someone in hospital, so it never sits below a preference.
  function foodNotes(fp) {
    // Still filtered even though the form no longer offers the option: five
    // member_prefs rows were saved while it did, and they read back until their
    // owner next saves the form.
    const diets = (fp.diets || []).filter((d) => d && d !== "No restrictions");
    return [
      ["allergies", fp.allergies, "alert"],
      ["won't eat", fp.wont_eat, "alert"],
      ["diet", diets.join(", "), "warn"],
      ["textures", fp.textures, "warn"],
    ].map(([k, v, tone]) => `<div class="hub-card-note${v ? ` is-${tone} cnote-${tone}` : ""}">
        <span class="hub-card-note-k">${esc(k)}</span><span class="hub-card-note-v cnote-v">${v ? esc(v) : "none"}</span></div>`).join("");
  }

  // Only must and want reach the card. The neutrals and the rather-nots are the
  // full spread, which belongs in the detail rail — a card showing all thirteen
  // says nothing about what this person actually wants out of the trip.
  // A rating's pill: must is the one filled chip, want a firmer hairline than a
  // neutral, and the two refusals take the shared warn and alert tones.
  const PILL_TONE = { must: " hub-pill--filled", want: " cpill-want", "rather-not": " is-warn", hate: " is-alert" };
  const pillClass = (r) => `hub-pill cpill${PILL_TONE[r] || ""}`;
  function crewPills(p) {
    const ent = Object.entries(p.interests || {});
    const pick = (r) => ent.filter(([, v]) => v === r).map(([tg]) => tg);
    return [...pick("must").map((tg) => ["must", tg]), ...pick("want").map((tg) => ["want", tg])]
      .map(([r, tg]) => `<span class="${pillClass(r)}">${esc(tg)}</span>`).join("");
  }
  // The card's footer row: two pips saying which of travel / food this
  // person has answered, and nothing more. It used to be the portal into those
  // forms, but a link on every card made the grid read as a to-do list for
  // Sam rather than a read on the crew. The way in still lives in the detail
  // rail, one person at a time (crewForms in trips.js).
  //
  // Off `filled`, never off the portal payload: the portal is access-controlled,
  // so on the public mirror only the bound viewer has one and keying the
  // indicator on it would blank every other card.
  function formStatus(c) {
    const done = (k) => !!(c && (c.filled || []).includes(k));
    return `<div class="cforms">` + [["travel", done("travel")], ["food", done("food")]]
      .map(([k, ok]) => `<span class="cform${ok ? " done" : ""}" title="${ok ? "answered" : "not answered yet"}">
        <span class="cform-pip" aria-hidden="true">${ok ? "\u2713" : "\u2022"}</span>${k}</span>`).join("")
      + `</div>`;
  }

  // One card per person. The card carries the long-form read — summary, aliases,
  // the must/want spread, and the three flags that can wreck a plan. Every slot
  // is floored to the same height in trips.css, so the pills, the rhythm facts,
  // and the flag block land at the same y on every card and a value still reads
  // across the grid. The full rating spread and the meals answer stay in the
  // detail rail, where one person at a time belongs.
  //
  // Everything the BOARD adds and the account page does not comes in through
  // `opts`, so this function never reaches for a `state` that only one of the two
  // callers has:
  //   selected   is this the card the detail rail is showing
  //   headExtra  html glued after the name (the board's delete button)
  //   footer     html at the foot of the card (the board's form pips)
  //   wait       what to print instead of "nothing submitted" while prefs load
  function card(m, c, p, opts) {
    const o = opts || {};
    const sel = o.selected ? " selected" : "";
    const aka = c && (c.aliases || []).length ? `<span class="caka hub-card-subtitle">aka ${esc(c.aliases.join(", "))}</span>` : "";
    const head = `<div class="ccard-head hub-card-head"><span class="hub-card-initial" aria-hidden="true">${esc((m.name || "?").trim().charAt(0))}</span><span class="cname hub-card-title">${esc(m.name)}</span>${aka}${o.headExtra || ""}</div>`;
    const foot = o.footer || "";
    if (!c) {
      // Before /preferences answers, NOBODY has a contact yet — so the unlinked
      // line was a claim about the record, printed before the record was read.
      // Once it has answered, the forms row is the actionable half of "no prefs
      // to show": the fix is to go fill one in, so the link sits right here.
      return `<div class="hub-card hub-card--selectable hub-stagger-item ccard${sel}" data-id="member:${m.id}">${head}
        <div class="ccard-unlinked">${o.wait || "no prefs yet — nothing submitted"}</div>
        ${foot}</div>`;
    }
    return `<div class="hub-card hub-card--selectable hub-stagger-item ccard${sel}" data-id="member:${m.id}">${head}
      <div class="csum">${esc(cleanSummary(c.name, c.summary))}</div>
      <div class="hub-tags ccard-pills">${crewPills(p)}</div>
      <div class="hub-card-facts ccard-facts">${crewFacts(p, c.food_prefs)}</div>
      <div class="hub-card-notes ccard-notes">${crewNotes(p, c.food_prefs)}</div>
      ${foot}</div>`;
  }
  // ── the scales ──────────────────────────────────────────────────────────────
  //
  // Every ordinal question, as an order. The table is the SERVER's
  // (preferences.SCALES) and arrives on the prefs payloads; nothing here keeps a
  // copy, because the ranks a rollup was computed with and the ranks a bar is
  // drawn from have to be the same ranks or a row quietly lights the wrong stop.
  //
  // Two ramps, and which one a question gets is the server's `valence` flag.
  // The must → hard-pass grids run red → green, because there the ends really
  // are bad and good. Everything else runs cool → warm, which reads as low to
  // high with no verdict attached: "own dish" is not worse than "family style",
  // and a colour that says it is would be the board scoring the crew's answers
  // instead of placing them.
  let SCALES = {};
  function setScales(s) { if (s && typeof s === "object") SCALES = s; }
  const scaleOf = (key) => SCALES[key] || null;

  // Where one answer sits, 0 at the low end and 1 at the high end, or null when
  // the value is off the scale ("depends", "mixed", "other") or the question has
  // no scale at all. Null is a real answer, so callers print the words and skip
  // the bar rather than treating it as missing.
  function scalePos(key, value) {
    const sc = scaleOf(key);
    if (!sc || value == null || value === "") return null;
    const i = sc.rank[String(value)];
    if (i == null) return null;
    const n = sc.order.length;
    return { i: i, n: n, t: n > 1 ? i / (n - 1) : 0, valence: !!sc.valence };
  }

  // The colour for a position. One expression, both ramps, both themes: the four
  // stops are theme tokens, so cobalt and vesper each paint their own without a
  // second table here.
  // oklch with a hue path, NOT oklab. oklab mixes on a straight line through the
  // colour solid, and between two hues this far apart that line passes next to
  // the neutral axis: the middle of every scale came out a grey-brown at 0.07–0.17
  // saturation while measuring a fine 5:1 against the ground. It read as dark
  // because it was colourless, not because it was dim.
  const rampColor = (t, valence) => valence
    ? `color-mix(in oklch shorter hue, var(--val-hi) ${Math.round(t * 100)}%, var(--val-lo))`
    : `color-mix(in oklch shorter hue, var(--scale-hi) ${Math.round(t * 100)}%, var(--scale-lo))`;

  // The bar under ONE answer, on a card fact or a read-back row. Deliberately not
  // a track with visible stops: the fact grid is height-floored across every card
  // in the crew grid, so this has to fit in the space a value already takes.
  function sbar(key, value) {
    const p = scalePos(key, value);
    if (!p) return "";
    const fill = ((p.i + 1) / p.n) * 100;
    return `<span class="sbar" role="img" aria-label="${p.i + 1} of ${p.n} on the scale"`
      + ` style="--fill:${fill.toFixed(1)}%;--c:${rampColor(p.t, p.valence)}"></span>`;
  }

  // The whole scale with a span lit on it: the group read. `lo`/`hi` are values,
  // not indexes, and either may be off the scale, in which case there is nothing
  // honest to light and the caller keeps its words.
  function strack(key, lo, hi) {
    const a = scalePos(key, lo), b = scalePos(key, hi);
    if (!a || !b) return "";
    const from = Math.min(a.i, b.i), to = Math.max(a.i, b.i);
    let stops = "";
    for (let i = 0; i < a.n; i++) {
      const t = a.n > 1 ? i / (a.n - 1) : 0;
      const on = i >= from && i <= to;
      stops += `<i class="${on ? "on" : ""}"${on ? ` style="--c:${rampColor(t, a.valence)}"` : ""}></i>`;
    }
    const sc = scaleOf(key);
    return `<span class="strack" aria-hidden="true">${stops}</span>`
      + `<span class="sends"><span>${esc(sc.low)}</span><span>${esc(sc.high)}</span></span>`;
  }

  // ── exports ─────────────────────────────────────────────────────────────────
  // label() and the fact/note builders go out too, not just the card: trips.js's
  // detail rail renders the same vocabulary one person at a time, and the account
  // page reads its own answers back with it. Two copies of the words is exactly
  // the drift this file exists to stop.
  return {
    esc, humanizeEnum, label, INTEREST_VERDICT_LABEL, CUISINE_VERDICT_LABEL, cleanSummary,
    setLabels, setScales, scaleOf, scalePos, rampColor, sbar, strack,
    crewFacts, crewNotes, crewPills, pillClass, foodFacts, foodNotes,
    formStatus, card,
  };
})();
