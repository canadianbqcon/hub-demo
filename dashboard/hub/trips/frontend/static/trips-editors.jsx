/* hub · trips page, editors (2026-10-13): React port of trips.js lines 9272-9758 (modal and confirm machinery,
   add/edit specs, the cost editor, missing-field prompts). Plain functions inside an IIFE, same HTML strings,
   ids and request bodies as the plain page; exported onto window.TripsUI. See trips-core.jsx for the interface. */
(() => {
const U = window.TripsUI;
const { esc, setHTML, toast, status, errMsg, state, $, TC, parseTags, isCar, isGuest, isCommitted } = U;
const API = U.api;
const { routeText, costRowName, pointsField, reload } = U.fwd("routeText", "costRowName", "pointsField", "reload");
// CASH_FIELD is a money-part table: read U.CASH_FIELD inside editCostRow, never here.

  // ── themed confirm/choice modal (replaces native confirm()/prompt()) ────────
  // U.mut.closeConfirmActive: cancel-resolver of whichever dialog is open, so global Escape can close it
  function confirmDialog(title, body, opts = {}) {
    return new Promise((resolve) => {
      const scrim = $("confirmScrim"), m = $("confirmModal");
      const done = (v) => { scrim.hidden = true; U.mut.closeConfirmActive = null; resolve(v); };
      setHTML(m, `<div class="hub-modal-title">${esc(title)}</div>
        <div class="hub-modal-body">${esc(body)}</div>
        <div class="hub-modal-actions">
          <button class="hub-modal-btn" id="cfCancel">cancel</button>
          <button class="hub-modal-btn${opts.danger ? " hub-modal-btn--danger" : ""}" id="cfOk">${esc(opts.confirmLabel || "confirm")}</button>
        </div>`);
      scrim.hidden = false;
      U.mut.closeConfirmActive = () => done(false);
      $("cfCancel").onclick = () => done(false);
      $("cfOk").onclick = () => done(true);
      scrim.onclick = (e) => { if (e.target === scrim) done(false); };
    });
  }
  // A section marker inside a field list: everything after it belongs to that
  // section until the next one. `opt` sections collapse — they only matter once
  // a row is booked, so they stay shut until they actually hold something.
  const SEC = (sec, opt) => ({ sec, opt });
  // `opts.note` is one line under the title saying WHAT is being edited — a
  // modal titled "split between" never said between-what, so you had to
  // remember which row you clicked.
  function modalForm(title, fields, onSave, opts = {}) {
    const m = $("modal");
    const secs = [];
    fields.forEach((f) => {
      if (f.sec) { secs.push({ sec: f.sec, opt: f.opt, fields: [] }); return; }
      if (!secs.length) secs.push({ fields: [] });
      secs[secs.length - 1].fields.push(f);
    });
    const grid = (fs) => `<div class="hub-modal-grid">${fs.map((f) => fieldHTML(f)).join("")}</div>`;
    const body = secs.map((g) => {
      if (!g.sec) return grid(g.fields);
      if (!g.opt) return `<div class="hub-field-sec">${esc(g.sec)}</div>${grid(g.fields)}`;
      const filled = g.fields.some((f) => f.value != null && f.value !== "");
      return `<details class="hub-field-group"${filled ? " open" : ""}><summary>${esc(g.sec)}</summary>${grid(g.fields)}</details>`;
    }).join("");
    m.classList.toggle("hub-modal--wide", fields.length > 6);
    setHTML(m, `<div class="hub-modal-title">${esc(title)}</div>${opts.note ? `<div class="hub-modal-note">${esc(opts.note)}</div>` : ""}${body}
      <div class="hub-modal-actions"><button class="hub-btn" id="mCancel">cancel</button><button class="hub-btn hub-btn--accent" id="mSave">save</button></div>`);
    $("modalScrim").hidden = false;
    $("mCancel").onclick = closeModal;
    $("modalScrim").onclick = (e) => { if (e.target === $("modalScrim")) closeModal(); };
    // everyone / nobody. Seven ticks by hand to say "the whole crew" is the
    // work the default already does for free, so the shortcut has to be there.
    m.querySelectorAll("[data-mall]").forEach((b) => {
      b.onclick = () => {
        const box = $(`mf_${b.dataset.mall}`);
        if (box) box.querySelectorAll("input").forEach((c) => { (c.checked = b.dataset.mset === "1"); });
      };
    });
    const collect = () => {
      const data = {};
      fields.forEach((f) => {
        if (f.sec) return;
        if (f.type === "members") {
          const box = $(`mf_${f.k}`);
          data[f.k] = box ? Array.from(box.querySelectorAll("input:checked")).map((c) => c.value).join(",") : "";
          return;
        }
        const el = $(`mf_${f.k}`); if (!el) return; let v = el.value; if (f.type === "number") v = v === "" ? null : Number(v); data[f.k] = v;
      });
      return data;
    };
    // A `reform` field decides which fields EXIST, so changing it redraws the
    // whole form. Everything already typed rides across in collect(), and
    // nothing is written until save.
    if (opts.onReform) fields.filter((f) => f.reform).forEach((f) => {
      const el = $(`mf_${f.k}`); if (el) el.onchange = () => opts.onReform(collect());
    });
    $("mSave").onclick = () => {
      // A handler that returns a STRING is telling the reader something the
      // generic "saved" cannot — what the seed actually took off the list, say.
      // Anything else returned is a row or a response and keeps the old word.
      // promise chain: a throw anywhere in collect/onSave/reload lands in the same catch the try had
      Promise.resolve().then(() => onSave(collect())).then((r) => { closeModal(); return Promise.resolve(reload()).then(() => {
            toast(typeof r === "string" ? r : "saved"); }); })
      .catch((e) => { toast(`save failed — ${errMsg(e)}`); });  // modal stays open on failure — input is preserved, not lost
    };
  }
  // Which crew ids a cost item splits between. Empty means "the trip's own
  // default" (whole crew for housing/transportation, Sam alone for
  // flights/expenses/activities) — trips-cost.js reads it the same way.
  function fieldHTML(f) {
    const v = f.value == null ? "" : f.value;
    // a section header already says "points", so the field under it is "total",
    // not "points — total for the stay". The long label stays for the detail rail.
    const lab = esc(f.short || f.l);
    if (f.type === "textarea") return `<div class="hub-field field field--wide"><label>${lab}</label><textarea id="mf_${f.k}">${esc(v)}</textarea></div>`;
    if (f.type === "select") return `<div class="hub-field field"><label>${lab}</label><select id="mf_${f.k}">${f.opts.map((o) => `<option value="${esc(o)}"${o === v ? " selected" : ""}>${esc(o)}</option>`).join("")}</select></div>`;
    if (f.type === "member") {
      const crew = (state.trip.members || []);
      return `<div class="hub-field field"><label>${lab}</label>
        <select id="mf_${f.k}"><option value=""${String(v) ? "" : " selected"}>nobody yet</option>${
        crew.map((m) => `<option value="${esc(String(m.id))}"${String(m.id) === String(v) ? " selected" : ""}>${esc(m.name)}</option>`).join("")}</select>
        ${f.hint ? `<div class="hub-field-hint field-hint">${esc(f.hint)}</div>` : ""}</div>`;
    }
    if (f.type === "members") {
      const picked = String(v).split(",").map((s) => s.trim()).filter(Boolean);
      const crew = (state.trip.members || []);
      const rows = crew.map((m) => `<label class="hub-picker-item"><input type="checkbox" value="${esc(String(m.id))}"${picked.indexOf(String(m.id)) >= 0 ? " checked" : ""}><span>${esc(m.name)}</span></label>`).join("");
      // The bulk pair only earns its place against a real crew — with two people
      // on the trip, "everyone" is two clicks either way.
      const bulk = crew.length > 2 ? `<span class="hub-picker-actions">
        <button type="button" data-mall="${f.k}" data-mset="1">everyone</button>
        <button type="button" data-mall="${f.k}" data-mset="0">clear</button></span>` : "";
      return `<div class="hub-field field field--wide">
        <div class="hub-picker-head"><label>${lab}</label>${bulk}</div>
        <div id="mf_${f.k}" class="hub-picker-grid">${rows || "<i>no crew on this trip yet</i>"}</div>
        ${f.hint ? `<div class="hub-field-hint field-hint">${esc(f.hint)}</div>` : ""}</div>`;
    }
    // a hint under a plain field, same as the member pickers have always had —
    // "blank means the trip default" is the whole answer for cents-per-point and
    // it had nowhere to render.
    return `<div class="hub-field field"><label>${lab}</label><input id="mf_${f.k}" type="${f.type || "text"}" value="${esc(v)}">${
      f.hint ? `<div class="hub-field-hint field-hint">${esc(f.hint)}</div>` : ""}</div>`;
  }
  function closeModal() { $("modalScrim").hidden = true; }

  // ── add/edit specs ──────────────────────────────────────────────────────────
  const ACT_FIELDS = (a = {}) => [
    { k: "name", l: "name", value: a.name }, { k: "location", l: "location", value: a.location },
    { k: "cost", l: "cost", type: "number", value: a.cost }, { k: "url", l: "url", value: a.url },
    { k: "operating_days", l: "operating days", value: a.operating_days }, { k: "operating_hours", l: "operating hours", value: a.operating_hours },
    { k: "tags", l: "tags (comma)", value: parseTags(a.tags).join(", ") },
    { k: "score_p", l: "group score P (1–10)", type: "number", value: a.score_p }, { k: "score_c", l: "community score C (1–10)", type: "number", value: a.score_c },
    { k: "description", l: "description", type: "textarea", value: a.description }, { k: "notes", l: "notes", type: "textarea", value: a.notes },
  ];
  function withBlend(data) {
    if (data.score_p != null && data.score_c != null) data.score = Math.round((0.4 * data.score_p + 0.6 * data.score_c) * 10) / 10;
    if (typeof data.tags === "string") data.tags = JSON.stringify(data.tags.split(",").map((s) => s.trim()).filter(Boolean));
    return data;
  }
  function addActivity() { modalForm("add activity", ACT_FIELDS(), (d) => API.post(`/trips/${state.trip.id}/activities`, withBlend(d))); }
  function editActivity(a) { modalForm("edit activity", ACT_FIELDS(a), (d) => API.patch(`/trips/${state.trip.id}/activities/${a.id}`, withBlend(d))); }

  // Every logistics kind carries the same status vocabulary, because the whole
  // point of the comparison tables is picking one option and marking the rest
  // dead — which was impossible while status wasn't an editable field at all.
  const LOGI_STATUS = { k: "status", l: "status", type: "select", opts: ["considering", "booked", "confirmed", "unavailable", "rejected"] };
  // One field decides which fields exist, so changing it re-draws the modal in
  // place (`reform`) rather than making you save and reopen. Nothing is cleared
  // on a switch: a hidden field keeps its stored value and comes back if you
  // flip the type back.
  const STAY_TYPE = { k: "stay_type", l: "kind of stay", type: "select", opts: ["hotel", "rental"], reform: true };
  // The default when nobody is ticked, said in the words of the table it is on —
  // the whole point of the empty state, and the modal never used to explain it.
  const SPLIT_DEFAULT = {
    housing: "Leave every box empty and the stay divides across the whole crew.",
    transportation: "Leave every box empty and this divides across the whole crew.",
    flights: "Leave every box empty and this fare stays yours alone.",
    expenses: "Leave every box empty and this stays your own spending.",
    activities: "Leave every box empty and this stays yours alone.",
  };
  const splitField = (v, table) => ({
    k: "split_with", l: "who it divides between", type: "members", value: v,
    hint: SPLIT_DEFAULT[table] || "",
  });
  // ── THE COST EDITOR ────────────────────────────────────────────────────────
  // A row on the cost tab opens THIS, not the item's own booking form. Clicking
  // the stay used to open "edit housing" — twenty fields of check-in method,
  // house rules and checkout chores — on the one tab where the only question is
  // money. Sam, 2026-08-26: "it doesn't need to share the exact same edit
  // screen because I'm not going to be editing housing in the cost tab …
  // that would edit specifically how the housing appears in the cash
  // dashboard."
  // It is also where the row's in-table controls went. The split button, the
  // payer chip and the four unlocking money cells were five separate ways to
  // change one line, spread across its width; they are five fields in here now,
  // and the table went back to being a table.
  // Same PATCH shape every other edit form uses (`/trips/:id/<table>/<rowId>`),
  // so it works on all four money tables. `expenses` never got the points
  // columns (migration 012 gave them to housing / flights / transportation
  // only), so its form is cash, payer and split — asking for a redemption rate
  // on a $40 dinner would be a field with nowhere to save to.
  const payerField = (v) => ({
    k: "paid_by", l: "whose card it went on", type: "member", value: v,
    hint: "Leave it blank and the line still counts toward the trip's total — it just can't be paid back to anyone.",
  });
  const COST_CASH_LABEL = { housing: "total cost (all-in)", flights: "fare", transportation: "cost", expenses: "amount" };
  function editCostRow(table, row) {
    const cashKey = U.CASH_FIELD[table];
    const fields = [{ k: cashKey, l: COST_CASH_LABEL[table] || "cash", short: "cash",
                      type: "number", value: row[cashKey] }];
    if (table !== "expenses") {
      // Whichever points column this row is priced off — TC.rowUR reads
      // points_transfer when there is one and falls back to points_total, so an
      // edit has to land on the same field or the number bounces back on reload.
      const pk = pointsField(row);
      fields.push(
        { k: pk, l: pk === "points_transfer" ? "Chase UR spent" : "points spent", short: "points",
          type: "number", value: row[pk] },
        { k: "cents_per_point", l: "cents per point", short: "¢ / pt", type: "number",
          value: row.cents_per_point,
          hint: `Blank means the trip default, ${Number((TC.UR_CENTS * 100).toFixed(4))}¢ — what a point cashes out at.` });
    }
    fields.push(payerField(row.paid_by), splitField(row.split_with, table));
    modalForm("cost", fields,
      (d) => API.patch(`/trips/${state.trip.id}/${table}/${row.id}`, d),
      { note: costRowName({ table, row }) });
  }
  // "18,19" on its own means nothing to a human — resolve to the names the
  // checkboxes actually show, same list the split math already reads.
  function memberNames(v) {
    const ids = String(v || "").split(",").map((s) => s.trim()).filter(Boolean);
    if (!ids.length) return "";
    const crew = state.trip.members || [];
    return ids.map((id) => crew.find((m) => String(m.id) === id)?.name || id).join(", ");
  }
  const LOGI_FIELDS = {
    // guests through reviews are what the comparison actually turns on — they used
    // to be prose inside `notes`, where nothing could rank or badge them.
    // host through checkout tasks only matter once a row is booked (migration 009) —
    // a `considering` row leaves them blank and they don't render.
    // `amenities` and `photos` are on NEITHER half. Both are imported off a
    // listing rather than typed: sixty-three amenity lines and thirty-four photo
    // urls. The panel prints them, the form never asks for them, and a nudge on
    // either one carries no button because there is no box to open.
    // A stay is one of two things and the halves barely overlap: a hotel has an
    // award price and no host; a rental has a host, house rules, checkout chores
    // and an amenity list, and will never have an award price (migration 012's
    // own note). One list for both is what made this a 33-field wall.
    // `stay_type` (migration 014) picks the half.
    hotel: [
      STAY_TYPE,
      { k: "name", l: "name" }, { k: "address", l: "address" },
      { k: "url", l: "url", link: true }, LOGI_STATUS, { k: "confirmation_code", l: "confirmation" },
      SEC("dates"),
      { k: "check_in", l: "check in" }, { k: "check_out", l: "check out" }, { k: "guests", l: "sleeps (max guests)", short: "sleeps", num: true },
      SEC("cost"),
      { k: "total_cost", l: "total cost (all-in)", short: "total (all-in)", money: true }, { k: "nightly_rate", l: "nightly rate", short: "per night", money: true },
      { k: "cancellation_deadline", l: "free cancel until" },
      SEC("points", true),
      { k: "points_total", l: "points \u2014 total for the stay", short: "total for the stay", num: true },
      { k: "points_program", l: "points program (Hyatt / Aeroplan / IHG \u2026)", short: "program (Hyatt / IHG \u2026)" }, { k: "points_transfer", l: "Chase UR to produce that", num: true },
      SEC("once booked", true),
      { k: "confirmation_code", l: "confirmation" }, { k: "host", l: "front desk" },
      { k: "loyalty", l: "loyalty number on the booking", short: "loyalty number" },
      { k: "check_in_method", l: "checking in", type: "textarea" },
      { k: "wifi_ssid", l: "wifi network", short: "wifi network" }, { k: "wifi_pass", l: "wifi password", short: "wifi password" },
      { k: "wifi", l: "wifi \u2014 anything else (extenders, where to ask)", short: "wifi \u2014 anything else" },
      SEC("the room"),
      { k: "room_type", l: "room type (beds, size, view)", short: "room type" },
      { k: "late_checkout", l: "late checkout (what it takes to get it)", short: "late checkout" },
      SEC("what it costs on top"),
      { k: "resort_fee", l: "resort or destination fee", short: "resort fee" },
      { k: "incidental_hold", l: "incidental hold (what the desk authorises)", short: "incidental hold" },
      { k: "breakfast", l: "breakfast (included, or what it runs)", short: "breakfast" },
      { k: "parking", l: "parking" },
      SEC("notes & fine print", true),
      { k: "house_rules", l: "the fine print", type: "textarea" },
      { k: "notes", l: "notes", type: "textarea" },
    ],
    rental: [
      STAY_TYPE,
      { k: "name", l: "name" }, { k: "address", l: "address" },
      { k: "url", l: "url", link: true }, LOGI_STATUS,
      SEC("dates & size"),
      { k: "check_in", l: "check in" }, { k: "check_out", l: "check out" },
      { k: "guests", l: "sleeps (max guests)", short: "sleeps", num: true }, { k: "bedrooms", l: "bedrooms", num: true },
      { k: "beds", l: "real beds", num: true }, { k: "baths", l: "baths", num: true },
      SEC("cost"),
      { k: "total_cost", l: "total cost (all-in)", short: "total (all-in)", money: true }, { k: "nightly_rate", l: "nightly rate", short: "per night", money: true },
      { k: "cancellation_deadline", l: "free cancel until" }, { k: "parking", l: "parking" },
      SEC("once booked", true),
      { k: "confirmation_code", l: "confirmation" }, { k: "host", l: "host" },
      { k: "check_in_method", l: "getting in", type: "textarea" },
      { k: "wifi_ssid", l: "wifi network", short: "wifi network" }, { k: "wifi_pass", l: "wifi password", short: "wifi password" },
      { k: "wifi", l: "wifi \u2014 anything else (extenders, where to ask)", short: "wifi \u2014 anything else" },
      SEC("notes & rules", true),
      { k: "house_rules", l: "house rules", type: "textarea" }, { k: "checkout_tasks", l: "before you leave", type: "textarea" },
      { k: "notes", l: "notes", type: "textarea" },
    ],
    // Two columns, so the order has to pair off: identity, then route, then the
    // two ends of the flight. Confirmation sits second — with it down at slot 8
    // the form dealt "to | departs" and "arrives | confirmation", which splits the
    // one pair on the form that has to be read together.
    flights: [{ k: "airline", l: "airline" }, { k: "confirmation", l: "confirmation" }, { k: "flight_num", l: "flight #" }, { k: "direction", l: "leg", type: "select", opts: ["outbound", "return", "roundtrip"] }, { k: "from_airport", l: "from" }, { k: "to_airport", l: "to" }, { k: "terminal_from", l: "terminal out" }, { k: "terminal_to", l: "terminal in" }, { k: "departure_time", l: "departs" }, { k: "arrival_time", l: "arrives" }, { k: "passenger", l: "passenger (blank = you)" }, LOGI_STATUS, SEC("cost"), { k: "cost", l: "cost", money: true }, { k: "points_total", l: "points — total", short: "points — total", num: true }, { k: "points_program", l: "points program (Aeroplan / United …)", short: "program (Aeroplan / United …)" }, { k: "points_transfer", l: "Chase UR to produce that", num: true }, { k: "notes", l: "notes", type: "textarea" }],
    transportation: [{ k: "type", l: "type" }, { k: "description", l: "description" }, { k: "departure", l: "from" }, { k: "arrival", l: "to" }, { k: "scheduled_date", l: "date (YYYY-MM-DD)" }, { k: "scheduled_time", l: "time" }, { k: "confirmation", l: "confirmation" }, { k: "url", l: "url", link: true }, LOGI_STATUS, SEC("cost"), { k: "cost", l: "cost", money: true }, { k: "points_total", l: "points — total", short: "points — total", num: true }, { k: "points_program", l: "points program", short: "program" }, { k: "points_transfer", l: "Chase UR to produce that", num: true }, { k: "notes", l: "notes", type: "textarea" }],
    // A car's form is the rental's own vocabulary — pickup, drop-off, seats —
    // not the from/to a bus uses. `type` still leads because it is what files
    // the row onto the counter board or the Turo board. `confirmation` only
    // matters once the row is booked (migration 011) and a quote leaves it blank.
    carrental: [{ k: "type", l: "type", type: "select", opts: ["car_rental", "turo"] }, { k: "description", l: "car (class or model)" }, { k: "location", l: "pick-up location" }, { k: "pickup_time", l: "pick up (YYYY-MM-DD HH:MM)" }, { k: "dropoff_time", l: "drop off (YYYY-MM-DD HH:MM)" }, { k: "seats", l: "fits (people + bags)", num: true }, { k: "confirmation", l: "confirmation" }, { k: "cost", l: "all-in cost", money: true }, { k: "url", l: "url", link: true }, LOGI_STATUS, { k: "notes", l: "notes", type: "textarea" }],
  };
  // Which form a transportation row gets: the table is one, the shapes are two.
  const logiForm = (kind, r) => kind === "transportation" && isCar(r || {}) ? "carrental"
    : kind === "housing" ? (r?.stay_type === "rental" ? "rental" : "hotel") : kind;
  // ── WHAT IS STILL MISSING, SAID WHERE THE BLANK IS ──────────────────────────
  // Sam, 2026-09-15: "the missing info isnt something that is a key component
  // missing, the board is supposed to function for those who provide the info. it
  // is a suggestion for usage, not oh if this isnt here it breaks."
  //
  // So this is the quietest thing on the panel and stays that way. One faint grey
  // sentence naming what would go there, and where a form can take it, one small
  // dashed button that opens a box for that field alone. No colour, no border on
  // the section, no badge, no count, no "3 fields missing". The flights board's
  // own gap note is deliberately NOT reused here: it paints its border and its
  // label in --warn, which is the failure state this exists not to be. That class
  // must still appear exactly twice in this file, both times on that note.
  //
  // It is wifiCell's existing empty state generalised from one field to a list, so
  // there is no new CSS and the guest rule comes along for free: a guest reads
  // what is missing and is offered no control, because a read-only link cannot
  // write. `ask` is written as a sentence about the stay rather than about the
  // schema, because it is read by whoever is filling the board in.
  const GAPS = {
    housing: {
      wifi_ssid: { l: "wifi", ask: "the network and password would go here", keys: ["wifi_ssid", "wifi_pass", "wifi"] },
      room_type: { l: "room type", ask: "what room was booked, and how big it is" },
      resort_fee: { l: "resort fee", ask: "the resort or destination fee, if the rate does not include it" },
      incidental_hold: { l: "incidental hold", ask: "what the front desk authorises on the card, and when it drops" },
      breakfast: { l: "breakfast", ask: "whether breakfast is included, or what it runs" },
      late_checkout: { l: "late checkout", ask: "what a later checkout takes to get" },
      check_in_method: { l: "getting in", ask: "the door code, or how the keys get handed over" },
      house_rules: { l: "house rules", ask: "quiet hours, guests, anything the host asks for" },
      checkout_tasks: { l: "before you leave", ask: "what the host asks you to do on the way out" },
      parking: { l: "parking", ask: "where a car goes, and what it costs" },
      // Both come off a listing rather than a keyboard, so neither is on either
      // form: the sentence stands on its own and there is no button, because the
      // box it would open has no fields in it.
      amenities: { l: "amenities", ask: "the listing's amenity list has not been read into this row yet", noButton: true },
      photos: { l: "photos", ask: "no photos read in from the listing yet", noButton: true },
    },
    flights: {
      confirmation: { l: "confirmation", ask: "not filled in yet" },
      terminal_from: { l: "terminal out", ask: "which terminal it leaves from" },
      terminal_to: { l: "terminal in", ask: "which terminal it lands at" },
    },
    transportation: {
      confirmation: { l: "confirmation", ask: "not filled in yet" },
      pickup_time: { l: "pick up", ask: "when the car gets picked up" },
      dropoff_time: { l: "drop off", ask: "when it has to be back" },
      seats: { l: "fits", ask: "how many people and bags it takes" },
    },
  };
  // Entries are keyed by column name rather than held in a list, so a call site
  // names the field it means and a reordered list can never silently retarget one.
  const gapAsk = (table, k) => GAPS[table]?.[k];
  function gapCell(table, row, k) {
    const f = gapAsk(table, k);
    if (!f) return "";
    const v = row[k];
    if (v != null && String(v).trim() !== "") return "";
    const line = `<span class="hub-pending">${esc(f.ask)}</span>`;
    if (f.noButton) return line;
    // A button whose keys are on no form for this row would open an empty modal,
    // so the row says nothing at all rather than offering a dead control. Same
    // reason the whole thing goes quiet for a guest.
    const form = LOGI_FIELDS[logiForm(table, row)] || [];
    const reach = (f.keys || [k]).filter((x) => form.some((e) => e.k === x));
    if (!reach.length) return "";
    // A fare still being compared has no confirmation because nobody bought it,
    // which is not a blank anybody can fill. The boarding pass draws such a leg
    // when it is all the leg has, so the sentence stays and the control goes.
    if (isGuest() || !isCommitted(row)) return line;
    return `${line}<button class="hub-pending-add stay-add" data-addfield="${esc(table)}:${esc(String(row.id))}:${esc(reach.join(","))}">+ add</button>`;
  }
  // The cap is per SECTION, not per field, so it lives here rather than in the
  // stateless cell: three prompts under one heading reads as a suggestion and six
  // reads as a punch list. Only a row somebody has actually committed to is
  // prompted — six prompts down a shortlist is the exact "this is broken" reading
  // the whole thing is built to avoid.
  function gapList(table, row, keys, cap = 3) {
    if (!isCommitted(row)) return "";
    const on = keys.map((k) => gapCell(table, row, k)).filter(Boolean).slice(0, cap);
    return on.length ? `<div class="hub-pending-rows">${on.map((c) => `<div class="hub-pending-row">${c}</div>`).join("")}</div>` : "";
  }
  // A box for one field, out of the same form entries the full modal is built
  // from, so a label written once reads the same in both places. Deliberately not
  // the whole form: at a door, on a phone, the answer is one line off the
  // guidebook, and a twenty-field modal to write it is why these columns kept
  // coming up empty.
  function addFields(table, row, keys) {
    const form = logiForm(table, row);
    const fields = specFromLogi(form, row).filter((f) => !f.sec && keys.indexOf(f.k) >= 0);
    if (!fields.length) return;
    const named = gapAsk(table, keys[0]);
    modalForm(`add ${named ? named.l : (fields[0].short || fields[0].l)}`, fields,
      (d) => API.patch(`/trips/${state.trip.id}/${table}/${row.id}`, unbool(form, d)),
      { note: logiTitle(table, row) });
  }

  function logiTitle(kind, r) { return kind === "flights" ? routeText(r.from_airport, r.to_airport) : (r.name || r.description || r.address || kind); }
  // Amenity flags are stored 1/0/null but a number box for that needed a label
  // explaining the encoding, which ate more room in the detail rail than the
  // answer did. A yes/no dropdown carries the same three states and says it.
  function specFromLogi(kind, r = {}) {
    return LOGI_FIELDS[kind].map((f) => (f.sec ? f : f.bool ? {
      k: f.k, l: f.l, short: f.short, type: "select", opts: ["", "yes", "no"],
      value: r[f.k] == null || r[f.k] === "" ? "" : (Number(r[f.k]) ? "yes" : "no"),
    } : {
      k: f.k, l: f.l, short: f.short, opts: f.opts, reform: f.reform,
      type: f.type || (f.money || f.num ? "number" : "text"),
      value: r[f.k],
    }));
  }
  function unbool(kind, d) {
    LOGI_FIELDS[kind].filter((f) => f.bool).forEach((f) => { d[f.k] = d[f.k] === "" ? null : (d[f.k] === "yes" ? 1 : 0); });
    return d;
  }
  // Deciding a flight or a stay clears the options that were ruled out (db.py →
  // "Ruled-out cleanup"). It's a hard delete, so say how many went rather than
  // letting rows vanish between one render and the next.
  // Add and edit are the same modal: draw the form this row's own type calls
  // for, and redraw it if that type changes mid-edit.
  function logiModal(title, kind, row, onSave) {
    const open = (r) => {
      const form = logiForm(kind, r);
      modalForm(title, specFromLogi(form, r), (d) => onSave(form, d),
        { onReform: (d) => open(Object.assign({}, r, unbool(form, Object.assign({}, d)))) });
    };
    open(row);
  }
  // The QR is a hand-off: you hold the phone out and somebody else's camera reads
  // it. So the sheet is the code at the size of the screen and nothing else
  // competing for it, with the credentials underneath in plain type for the phone
  // that will not scan and the person who would rather type.
  function showQR(h) {
    const ssid = String(h.wifi_ssid || "").trim(), pass = String(h.wifi_pass || "").trim();
    const m = $("modal");
    m.classList.remove("hub-modal--wide");
    let code;
    try {
      code = QR.svg(QR.wifiPayload(ssid, pass), { label: `wifi for ${ssid || "this stay"}` });
    } catch (e) {
      // A payload too long for version 10 is the only way this throws, and a
      // broken square would be worse than saying so.
      code = `<div class="hub-pending">this network name and password are too long to fit in a QR — ${esc(errMsg(e))}</div>`;
    }
    setHTML(m, `<div class="hub-modal-title">point a camera at this</div>
      <div class="hub-qr-sheet">${code}</div>
      <div class="hub-qr-facts qr-facts">
        <div><span class="hub-fact-k stay-fk">network</span> <span class="hub-fact-v">${esc(ssid)}</span></div>
        ${pass ? `<div><span class="hub-fact-k stay-fk">password</span> <span class="hub-fact-v">${esc(pass)}</span></div>` : ""}
      </div>
      <div class="hub-modal-actions"><button class="hub-btn" id="mCancel">done</button></div>`);
    $("modalScrim").hidden = false;
    $("mCancel").onclick = closeModal;
    $("modalScrim").onclick = (e) => { if (e.target === $("modalScrim")) closeModal(); };
  }

  function editLogistics(kind, r) {
    logiModal(`edit ${kind}`, kind, r, (form, d) => {
      return API.patch(`/trips/${state.trip.id}/${kind}/${r.id}`, unbool(form, d)).then((res) => {
        if (res?.purged) status(`${kind} decided`, `${res.purged} ruled-out option${res.purged === 1 ? "" : "s"} deleted`);
        return res;
      });
    });
  }

  // Live fare search → candidate rows in the flights table. Runs the same
  // bin/flight-search.py the /flights skill uses, so the ALL-IN ranking, the
  // ULCC carry-on surcharge and the pointless-connection flag are already
  // applied; this just writes the top few into the comparison table.
  // The origin defaults to NYC (all three airports) — searching one is how the
  // cheapest fare gets missed, per the flight-rewards practice note.
  function searchFares() {
    const t = state.trip;
    modalForm("search fares", [
      { k: "origin", l: "from (airport or NYC / LON / BAY / CHI / WAS)", value: "NYC" },
      { k: "dest", l: "to (airport code)", value: "" },
      { k: "depart", l: "depart (YYYY-MM-DD)", value: t.start_date || "" },
      { k: "ret", l: "return (YYYY-MM-DD, blank for one-way)", value: t.end_date || "" },
    ], (d) => {
      if (!d.dest) return Promise.reject(new Error("a destination airport code is required"));
      // three sequential Google queries when origin is a metro group; say so
      // rather than letting a 90-second silence read as a hang
      status("searching fares — this takes up to a minute…");
      toast("searching fares…");
      return API.post(`/trips/${t.id}/flights/search`, d).then((r) => {
        if (r.error && !r.added) throw new Error(r.error);
        toast(`added ${r.added} fare${r.added === 1 ? "" : "s"} as candidates`);
        if ((r.errors || []).length) status("some routes returned nothing", r.errors.join(" · "));
      });
    });
  }

  const MEMBER_FIELDS = (m = {}) => [{ k: "name", l: "name", value: m.name }, { k: "email", l: "email", value: m.email }, { k: "contact_slug", l: "linked contact (wiki/contacts/…)", value: m.contact_slug }, { k: "notes", l: "notes", type: "textarea", value: m.notes }];
  function addMember() { modalForm("add crew member", MEMBER_FIELDS(), (d) => API.post(`/trips/${state.trip.id}/members`, d)); }
  function editMember(m) { modalForm("edit member", MEMBER_FIELDS(m), (d) => API.patch(`/trips/${state.trip.id}/members/${m.id}`, d)); }

  const EXP_FIELDS = (e = {}) => [{ k: "description", l: "description", value: e.description }, { k: "category", l: "category", value: e.category }, { k: "amount", l: "amount", type: "number", value: e.amount }, { k: "currency", l: "currency", value: e.currency || "USD" }, { k: "paid_by", l: "paid by", value: e.paid_by }, { k: "status", l: "status", type: "select", opts: ["estimated", "booked", "paid"], value: e.status }];
  function addExpense() { modalForm("add expense", EXP_FIELDS(), (d) => API.post(`/trips/${state.trip.id}/expenses`, d)); }
  function editExpense(e) { modalForm("edit expense", EXP_FIELDS(e), (d) => API.patch(`/trips/${state.trip.id}/expenses/${e.id}`, d)); }

Object.assign(U, {
  confirmDialog, modalForm, closeModal, addActivity, editActivity, editCostRow, memberNames, LOGI_FIELDS,
  logiForm, gapCell, gapList, addFields, logiTitle, specFromLogi, unbool, logiModal, showQR, editLogistics,
  searchFares, addMember, editMember, addExpense, editExpense,
});
})();
