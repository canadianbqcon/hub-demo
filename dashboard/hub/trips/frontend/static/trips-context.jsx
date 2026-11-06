/* hub · trips page, context (2026-10-13): React port of trips.js lines 7271-8188 (Task 62). The detail rails
   (activity, logistics, member, expense), the food tab, the grocery run and list, and the weather helpers and
   charts. Near-verbatim: the same HTML strings, ids and classes, written into the hosts the caller passes in.
   Async functions became promise chains; object spreads became Object.assign (jsx_globals_check bans both
   Babel helpers). Everything listed in the Object.assign at the bottom is exported on window.TripsUI.
   The weather fetch itself lives in the board part (listWeather); this part holds its pure helpers. */
(() => {
const U = window.TripsUI;
const { esc, setHTML, toast, state, errMsg, money, num1, parseTags, pipVar, statusLabel, distFromStay, chosenStay, $, T, TC } = U;
const API = U.api;
// The crew card's render vocabulary (crewcard.js): the detail rail renders the same words one person at a time.
const { label, cleanSummary, crewFacts, crewNotes, pillClass, foodFacts } = U.CC;
// Functions another part owns, looked up on TripsUI at call time.
const { renderFunnelNav, renderFunnelSub, renderFocus, dayLabel, dayLong, baseOf, absOf, dur, stayClock, readerLegs,
        prefsWait, crewForms, memberForms, tripDays, reload, patchActivity, delActivity, confirmDelete, delBtn,
        bindDeletes, modalForm, editActivity, memberNames, logiForm, logiTitle, editLogistics, editMember,
        editExpense } = U.fwd("renderFunnelNav", "renderFunnelSub", "renderFocus", "dayLabel", "dayLong", "baseOf",
  "absOf", "dur", "stayClock", "readerLegs", "prefsWait", "crewForms", "memberForms", "tripDays", "reload",
  "patchActivity", "delActivity", "confirmDelete", "delBtn", "bindDeletes", "modalForm", "editActivity",
  "memberNames", "logiForm", "logiTitle", "editLogistics", "editMember", "editExpense");
// Constants owned by other parts (MON, BAGS_MIN, LOGI_FIELDS) are read as U.NAME inside the functions below.

  // ── DETAIL (renders into the CONTEXT rail when an item is selected) ──────────
  function detailActivity(f) {
    const a = (state.trip.activities || []).find((x) => x.id === state.selId);
    if (!a) { setHTML(f, `<div class="hub-empty-state focus-empty">not found</div>`); return; }
    const d = distFromStay(a);
    const meta = [
      a.location ? `<span><b aria-hidden="true">📍</b> ${esc(a.location)}${d != null ? ` · ${d.toFixed(1)} mi from stay` : ""}</span>` : "",
      (a.operating_days || a.operating_hours) ? `<span><b aria-hidden="true">🕐</b> ${esc([a.operating_days, a.operating_hours].filter(Boolean).join(" · "))}</span>` : "",
      a.cost != null ? `<span><b aria-hidden="true">$</b> ${esc(money(a.cost))}</span>` : "",
      a.url ? `<span><a href="${esc(a.url)}" target="_blank" rel="noopener">link ↗</a></span>` : "",
    ].filter(Boolean).join("");
    const tags = parseTags(a.tags);
    const members = state.trip.members || [];
    const ops = a.opinions || {};
    const opinionRows = members.map((m) => `
      <div class="opinion"><span class="opinion-who">${esc(m.name)}</span>
      <input class="opinion-rate" type="number" min="1" max="10" data-mid="${m.id}" value="${ops[m.id] != null ? ops[m.id] : ""}" placeholder="–" aria-label="rating for ${esc(m.name)}"></div>`).join("") || `<div class="ctx-sub">no crew</div>`;
    const days = tripDays();
    const dayOpts = `<option value="">— not scheduled —</option>${days.map((dd, i) => `<option value="${dd}"${a.scheduled_date === dd ? " selected" : ""}>day ${i + 1} · ${dd}</option>`).join("")}`;
    setHTML(f, `<div class="hub-detail fdetail">
      <div class="hub-detail-head fdetail-head">
        <div><div class="hub-detail-title fdetail-title">${esc(a.name)}</div></div>
        <div class="hub-detail-actions">
          <span class="hub-pill statuschip"><span class="hub-dot" style="--dot-color: var(${pipVar(a.status)})">${esc(statusLabel(a.status))}</span></span>
          <button class="hub-btn" id="aEdit">edit</button>
          <button class="hub-btn hub-btn--danger" id="aDel">delete</button>
        </div>
      </div>
      <div class="hub-meta-strip fmeta">${meta || '<span class="ctx-sub">no location set</span>'}</div>
      <div class="scores hub-stat-row">
        <div class="sp hub-stat hub-stat--tile lead"><div class="sp-v hub-stat-v">${num1(a.score)}</div><div class="sp-k">score</div></div>
        <div class="sp hub-stat hub-stat--tile"><div class="sp-v hub-stat-v">${num1(a.score_p)}</div><div class="sp-k" title="your personal rating (1–10) — 40% of the blended score">group · P</div></div>
        <div class="sp hub-stat hub-stat--tile"><div class="sp-v hub-stat-v">${num1(a.score_c)}</div><div class="sp-k" title="community/review rating (1–10) — 60% of the blended score">community · C</div></div>
        <div class="scores-spacer"></div>
        <div class="sp hub-stat hub-stat--tile muted"><div class="sp-v hub-stat-v">${num1(a.true_score)}</div><div class="sp-k">actual</div></div>
      </div>
      ${tags.length ? `<div class="tags">${tags.map((t) => `<span class="hub-pill tagchip">${esc(t)}</span>`).join("")}</div>` : ""}
      <div class="hub-detail-body fbody">
        <div class="hub-detail-body-main fbody-main">
          <div><div class="hub-block-label fblk-l">description</div><div class="hub-block-text">${esc(a.description) || "—"}</div></div>
          <div><div class="hub-block-label fblk-l">notes</div><div class="hub-block-text">${esc(a.notes) || "—"}</div></div>
          ${a.decision_reason ? `<div><div class="hub-block-label fblk-l">decision reason</div><div class="hub-block-text">${esc(a.decision_reason)}</div></div>` : ""}
          ${a.log_notes ? `<div><div class="hub-block-label fblk-l">trip log</div><div class="hub-block-text">${esc(a.log_notes)}</div></div>` : ""}
        </div>
        <div class="hub-detail-body-side fbody-side">
          <div><div class="hub-block-label fblk-l">move</div>
            <div class="sched-controls">
              <select class="opinion-rate" id="aStatus" style="width:100%" aria-label="status">
                ${["considering", "deciding", "scheduled", "flex", "skip"].map((s) => `<option value="${s}"${a.status === s ? " selected" : ""}>${statusLabel(s)}</option>`).join("")}
              </select>
            </div>
          </div>
          <div><div class="hub-block-label fblk-l">schedule</div>
            <div class="sched-controls">
              <select class="hub-field field" id="aDay" style="width:100%" aria-label="scheduled day">${dayOpts}</select>
              <div class="hub-field-row">
                <input class="opinion-rate" id="aFrom" type="time" style="width:100%" aria-label="start time" value="${esc(a.scheduled_time || "")}">
                <input class="opinion-rate" id="aTo" type="time" style="width:100%" aria-label="end time" value="${esc(a.scheduled_time_end || "")}">
              </div>
              <button class="hub-btn hub-btn--accent" id="aSave">save schedule</button>
            </div>
          </div>
          <div><div class="hub-block-label fblk-l">crew opinions (1–10)</div>${opinionRows}</div>
        </div>
      </div>
    </div>`);
    $("aEdit").onclick = () => editActivity(a);
    $("aDel").onclick = () => delActivity(a);
    $("aStatus").onchange = (e) => patchActivity(a.id, { status: e.target.value }, `moved to ${statusLabel(e.target.value)}`);
    $("aSave").onclick = () => {
      const day = $("aDay").value;
      patchActivity(a.id, { scheduled_date: day, scheduled_time: $("aFrom").value, scheduled_time_end: $("aTo").value, status: day ? "scheduled" : a.status }, day ? "scheduled" : "schedule cleared");
    };
    f.querySelectorAll(".opinion-rate[data-mid]").forEach((inp) => { inp.onchange = () => {
      const v = inp.value === "" ? null : Number(inp.value);
      API.post(`/trips/${state.trip.id}/activities/${a.id}/opinions`, { member_id: Number(inp.dataset.mid), rating: v })
        .then(() => { toast("opinion saved"); })
        .catch((e) => { toast(`opinion save failed — ${errMsg(e)}`); });
    }; });
  }

  function detailLogistics(f) {
    const [kind, idStr] = String(state.selId).split(":");
    const arr = { housing: state.trip.housing, flights: state.trip.flights, transportation: state.trip.transportation }[kind] || [];
    const row = arr.find((x) => x.id === Number(idStr));
    if (!row) { setHTML(f, `<div class="hub-empty-state focus-empty">not found</div>`); return; }
    // Long text is a block below, not a chip, rendering the whole field list
    // printed the same paragraph twice, once squeezed into the meta row. Splitting
    // on `type === "textarea"` rather than on the key `notes` means house rules and
    // checkout chores land in the same place without a second special case.
    const spec = U.LOGI_FIELDS[logiForm(kind, row)];
    const fields = spec.filter((fl) => fl.type !== "textarea");
    const cell = (fl, v) => fl.link ? `<a class="hub-link-chip llink" href="${esc(v)}" target="_blank" rel="noopener">open ↗</a>`
      : fl.bool ? (Number(v) ? "yes" : "no")
      : fl.type === "members" ? esc(memberNames(v))
      : esc(fl.money ? money(v) : v);
    const body = fields.map((fl) => row[fl.k] != null && row[fl.k] !== "" ? `<span><b>${esc(fl.l)}</b> ${cell(fl, row[fl.k])}</span>` : "").filter(Boolean).join("");
    const blocks = spec.filter((fl) => fl.type === "textarea" && fl.rail !== 0 && row[fl.k])
      .map((fl) => `<div><div class="hub-block-label fblk-l">${esc(fl.l)}</div><div class="hub-block-text">${esc(row[fl.k])}</div></div>`).join("");
    setHTML(f, `<div class="hub-detail fdetail">
      <div class="hub-detail-head fdetail-head"><div class="hub-detail-title fdetail-title">${esc(logiTitle(kind, row))}</div>
        <div class="hub-detail-actions"><button class="hub-btn" id="lEdit">edit</button><button class="hub-btn hub-btn--danger" id="lDel">delete</button></div></div>
      <div class="hub-meta-strip fmeta">${body || '<span class="ctx-sub">no details</span>'}</div>
      ${blocks ? `<div class="hub-detail-body-main fbody-main">${blocks}</div>` : ""}
    </div>`);
    $("lEdit").onclick = () => editLogistics(kind, row);
    $("lDel").onclick = () => confirmDelete(logiTitle(kind, row), () => API.del(`/trips/${state.trip.id}/${kind}/${row.id}`));
  }

  function detailMember(f) {
    const mid = Number(String(state.selId).split(":")[1]);
    const m = (state.trip.members || []).find((x) => x.id === mid);
    if (!m) { setHTML(f, `<div class="hub-empty-state focus-empty">not found</div>`); return; }
    const contact = state.prefs && (state.prefs.members || []).find((c) => c.member_id === mid);
    const p = contact?.travel_prefs || {};
    const fp = (contact?.food_prefs) || {};
    const hasFood = Object.keys(fp).length > 0;
    // Full spread, all thirteen, same reason the travel interests are: the card
    // carries the highlights, the rail is where "what did they say to everything"
    // belongs.
    // The pill prints the WORD, not the enum: the class still keys on the stored
    // value (pillClass gives "must" the fill) while the reader sees "love".
    const cuisines = Object.entries(fp.cuisines || {})
      .map(([k, v]) => `<span class="${pillClass(v)}">${esc(k)}<span class="cpill-r">${esc(label("cuisines", v))}</span></span>`).join("");
    // full rating spread here, not just must/want, the card already carries the
    // highlights, so the detail rail is where "what did they say to everything"
    // belongs, including the neutrals and the rather-nots.
    const ratings = Object.entries(p.interests || {})
      .map(([k, v]) => `<span class="${pillClass(v)}">${esc(k)}<span class="cpill-r">${esc(label("interests", v))}</span></span>`).join("");
    const facts = crewFacts(p, fp);
    const prefBlock = contact ? `
      <div class="hub-detail-body fbody">
        <div class="hub-detail-body-main fbody-main">
          ${contact.summary ? `<div><div class="hub-block-label fblk-l">read</div><div class="hub-block-text">${esc(cleanSummary(contact.name, contact.summary))}</div></div>` : ""}
          ${ratings ? `<div><div class="hub-block-label fblk-l">interests</div><div class="hub-tags ccard-pills">${ratings}</div></div>` : ""}
          ${p.extra_notes ? `<div><div class="hub-block-label fblk-l">their note</div><div class="hub-block-text">${esc(p.extra_notes)}</div></div>` : ""}
        </div>
        <div class="hub-detail-body-side fbody-side">
          ${facts ? `<div><div class="hub-block-label fblk-l">rhythm</div><div class="hub-card-facts ccard-facts">${facts}</div></div>` : ""}
          <div><div class="hub-block-label fblk-l">flags</div><div class="hub-card-notes ccard-notes">${crewNotes(p, fp)}</div></div>
          ${p.meals_coordinated ? `<div><div class="hub-block-label fblk-l">meals</div><div class="hub-block-text">${esc(p.meals_coordinated_other || label("meals_coordinated", p.meals_coordinated))}</div></div>` : ""}
        </div>
      </div>
      ${hasFood ? `<div class="hub-detail-body fbody">
        <div class="hub-detail-body-main fbody-main">
          ${cuisines ? `<div><div class="hub-block-label fblk-l">cuisines</div><div class="hub-tags ccard-pills">${cuisines}</div></div>` : ""}
          ${fp.extra_notes ? `<div><div class="hub-block-label fblk-l">how they eat</div><div class="hub-block-text">${esc(fp.extra_notes)}</div></div>` : ""}
        </div>
        <div class="hub-detail-body-side fbody-side">
          <div><div class="hub-block-label fblk-l">at the table</div><div class="hub-card-facts ccard-facts">${foodFacts(fp)}</div></div>
          ${(fp.drinks || []).length ? `<div><div class="hub-block-label fblk-l">drinks</div><div class="hub-block-text">${esc((fp.drinks || []).join(", "))}</div></div>` : ""}
        </div>
      </div>` : ""}` : `<div class="hub-meta-strip fmeta"><span class="ctx-sub">${prefsWait()
        || "no linked contact — set a contact slug with <b>edit</b> to pull their travel prefs"}</span></div>`;
    setHTML(f, `<div class="hub-detail fdetail">
      <div class="hub-detail-head fdetail-head"><div class="hub-detail-title fdetail-title">${esc(m.name)}</div>
        <div class="hub-detail-actions"><button class="hub-btn" id="mEdit">edit</button><button class="hub-btn hub-btn--danger" id="mDel">delete</button></div></div>
      <div class="hub-meta-strip fmeta">${contact && (contact.aliases || []).length ? `<span><b>aka</b> ${esc(contact.aliases.join(", "))}</span>` : ""}${m.email || (contact?.email) ? `<span><b>email</b> ${esc(m.email || contact.email)}</span>` : ""}${contact ? `<span><b>contact</b> ${esc(contact.slug)}</span>` : ""}${m.notes ? `<span><b>notes</b> ${esc(m.notes)}</span>` : ""}</div>
      ${prefBlock}
      ${crewForms(memberForms(mid))}</div>`);
    $("mEdit").onclick = () => editMember(m);
    $("mDel").onclick = () => confirmDelete(m.name, () => API.del(`/trips/${state.trip.id}/members/${m.id}`));
  }

  function detailExpense(f) {
    const eid = Number(String(state.selId).split(":")[1]);
    const e = (state.trip.expenses || []).find((x) => x.id === eid);
    if (!e) { setHTML(f, `<div class="hub-empty-state focus-empty">not found</div>`); return; }
    setHTML(f, `<div class="hub-detail fdetail">
      <div class="hub-detail-head fdetail-head"><div class="hub-detail-title fdetail-title">${esc(e.description || e.category)}</div>
        <div class="hub-detail-actions"><button class="hub-btn" id="eEdit">edit</button><button class="hub-btn hub-btn--danger" id="eDel">delete</button></div></div>
      <div class="scores hub-stat-row"><div class="sp hub-stat hub-stat--tile lead"><div class="sp-v hub-stat-v">${money(e.amount)}</div><div class="sp-k">${esc(e.currency || "USD")}</div></div></div>
      <div class="hub-meta-strip fmeta"><span><b>category</b> ${esc(e.category)}</span><span><b>status</b> ${esc(e.status)}</span>${e.paid_by ? `<span><b>paid by</b> ${esc(e.paid_by)}</span>` : ""}</div>
    </div>`);
    $("eEdit").onclick = () => editExpense(e);
    $("eDel").onclick = () => confirmDelete(e.description || e.category, () => API.del(`/trips/${state.trip.id}/expenses/${e.id}`));
  }

  /* ── FOOD: the restaurant research for wherever this trip goes ───────────────
     Served by the trips blueprint (GET /trips/api/trips/<id>/food), never linked
     to /food: the public mirror registers trips and nothing else, so a link there
     is a dead end for every guest, and registering the food module on the mirror
     would hand out the entire research DB instead of this one city. The endpoint
     takes a trip id rather than an area, so a guest cannot ask for a city their
     trip is not in.

     Read-only on both surfaces. The /food skill is the only writer. */

  // state.food stays null until this answers and the tab reads that null as "still
  // loading", so a failure has to be recorded or the tab sits on the loading line
  // forever with nothing to say why. Same shape as loadPrefs.
  function loadFood() {
    if (!state.trip) return Promise.resolve();
    state.foodErr = "";
    return API.get(`/trips/${state.trip.id}/food`)
      .then((r) => { state.food = r; }, (e) => { state.foodErr = errMsg(e); })
      .then(() => { renderFunnelNav(); renderFocus(); });
  }

  // Mounted once per trip, not once per render: the renderer owns a leaflet map and
  // an open place, and rebuilding it on every repaint would throw away the pan, the
  // zoom and whatever the user was reading. Lives on U.mut.foodMounted (nav and board read it).

  function unmountFood() {
    if (!U.mut.foodMounted) return;
    window.FoodView.teardown();
    U.mut.foodMounted = null;
    // Hand the rail slot back to whoever owns it now, rather than blanking it.
    // setMode() draws the itinerary's day list BEFORE the render that unmounts
    // food, so a blanket wipe here erased the days it had just drawn: opening
    // food once and going back to the itinerary left it with no day picker at
    // all until a reload. renderFunnelSub() re-reads the mode, so it redraws the
    // days on the itinerary and does the same clear-and-hide anywhere else.
    renderFunnelSub();
    $("sidePane").classList.remove("has-detail");
  }

  function listFood(head, list) {
    if (!state.food) {
      setHTML(head, "");
      setHTML(list, state.foodErr
        ? `<div class="hub-empty-state empty">couldn’t load the food research — ${esc(state.foodErr)}</div>`
        : `<div class="hub-empty-state empty">loading…</div>`);
      if (!state.foodErr) loadFood();
      return;
    }
    const f = state.food;
    // No research is the common case, not an error: most trips go somewhere nobody
    // has looked at yet. Name the city so the empty state says which one.
    if (!f.area) {
      // The city comes off the NAME, not the destination: names read "Columbus, OH
      // Trip" while destinations read "Hyatt Regency Columbus, Columbus", and the
      // first segment of that is a hotel, so the suggested command named one.
      const city = String(state.trip.name || state.trip.destination || "")
        .split(",")[0].replace(/\s+trip$/i, "").trim();
      setHTML(head, "");
      // one span: liquid makes the empty state a flex row, and bare text, <br> and
      // <b> each became their own item, which stranded "run" on a line of its own
      setHTML(list, `<div class="hub-empty-state empty"><span>nobody has researched the food in ${esc(city || "this city")} yet.<br>
        run <b>/food ${esc(city)}</b> and it shows up here.</span></div>`);
      return;
    }
    if (U.mut.foodMounted === state.trip.id) return;   // already up; leave it alone

    // The rail slot is the funnel's own sub-nav, the same place the itinerary hangs
    // its days, one level under the tab it belongs to.
    const sub = $("funnelSub");
    sub.hidden = false;
    setHTML(list, "");
    setHTML($("dayMapHost"), "");
    window.FoodView.mount({
      els: { rail: sub, head, list, map: $("dayMapHost"),
             detail: $("context"), sidePane: $("sidePane") },
      data: f,
      api: { place: (s) => API.get(`/trips/${state.trip.id}/food/place/${encodeURIComponent(s)}`) },
      // A child area is a filter here, not a destination. The public mirror registers
      // the trips blueprint and nothing else, so /food does not exist over there and a
      // link to it is a dead end for every guest, and the whole city is already in
      // hand, so filtering answers the same question without a second page.
      navigate: (child) => window.FoodView.filterToChild(child),
      // The rail is a slot inside the trips funnel, not a page of its own: it stays
      // short enough that the tabs ordered below it are still on screen.
      compact: true,
      // The renderer owns the selection; trips only needs it for the mobile slide-over.
      onSelect: (slug) => {
        state.selId = slug;
        $("contextCol").classList.toggle("is-open", slug != null);
      },
    });
    U.mut.foodMounted = state.trip.id;
  }

  // ── CONTEXT RAIL ─────────────────────────────────────────────────────────────
  /* ── GROCERY: the shop you do on arrival ─────────────────────────────────────
     A trip has one shopping run and it happens on a clock nobody writes down.
     Lost Lands needed distilled water bought in Columbus, and the only record of
     that was somebody's memory of having said it, which is how you get to the
     festival without it.

     The list is DB state, not a per-reader tick like the day-of checklist: one
     person walks the store for the whole crew, and a tick only that person can
     see is a second trip for the water.

     WHEN is a RELATION to check-in, never a stored time. `after` (and the empty
     default) puts the run once you have the room, so the bags go straight in.
     `before` is for the trips where the flight lands early enough that arriving
     with the water beats going back out for it, and what it prints is the real
     gap between clearing bags and the stay's own check-in. Derived on every
     render from the booked stay and the outbound leg, a copied-down datetime
     would go stale the moment the house is rebooked, and nothing on screen would
     say so. */

  // The two clocks the run sits between. Both can be missing and that is a real
  // state, not an error: a trip with no booked stay has no check-in to hang a
  // shopping run off, and saying so is the honest output.
  function groceryClocks(t) {
    const stay = chosenStay();
    const base = stay?.check_in ? baseOf(stay.check_in) : null;
    const out = (readerLegs(t) || []).filter((s) => s.leg === "outbound" || s.leg === "roundtrip")[0];
    const land = out ? absOf(out.row.arrival_time) : null;
    return {
      stay,
      // stayClock reads the row's OWN check-in when it carries one, do not
      // substitute 15:00 here, the Arvada house is 16:00 and that bug has been
      // fixed on this board once already.
      sc: base == null ? null : stayClock(stay, base),
      dateISO: base == null ? null : T.parseStamp(stay.check_in, t.start_date)?.date,
      curb: land == null ? null : land + U.BAGS_MIN,
    };
  }

  // How long a shop takes, so the run draws as a block on the calendar rather than
  // a nameless instant. One number, deliberately generous: a store you have never
  // been in, with a list, is not a fifteen-minute stop.
  const SHOP_MIN = 60;
  // The window that has to exist before landing-then-shopping beats
  // room-then-shopping. Below it you are watching a clock in an aisle, which is
  // why the old hand-pick drew this same figure as a warning.
  const SHOP_GAP_MIN = 90;

  /* WHEN the run happens, derived, never picked and never stored.

     The board already holds the answer. The outbound leg's arrival plus the bag
     wait gives the curb time; the booked stay gives check-in. If there is a real
     gap between them the run goes there, because arriving with the water beats
     going back out for it. If there is not, it goes once you have the room. A
     hand-picked side was asking a question the data had answered, and a stored
     one went stale the moment either end moved, which is the whole reason
     migration 019 kept this a RELATION to check-in in the first place.

     `side` is the derived answer, `why` says out loud what decided it, and both
     ends are real clock minutes so the itinerary can place the block. A trip with
     no booked stay has no run at all, and saying so is the honest output. */
  function groceryRun(t) {
    const { sc, dateISO, curb } = groceryClocks(t);
    // groceryClocks works in absolute minutes-since-epoch, because a gap between two
    // stamps is only meaningful across days. A timeline column is the opposite: an
    // item's position down it IS its clock time, so `start` and `end` come back
    // converted, the same day-relative minutes every other item reaches put() with.
    // Getting this wrong does not throw, the block is laid out at top: 2070640%
    // and simply is not on the screen.
    const clock = (abs) => ((abs % 1440) + 1440) % 1440;
    // A run that would spill past midnight is cut at the end of its own day rather
    // than wrapping to 00:30 and drawing as a negative-height block on the wrong one.
    const span = (from, to) => ({ start: clock(from), end: Math.max(clock(from), Math.min(clock(to), 1439)) });
    const hhmm = (abs) => T.fmtClock(clock(abs));
    const day = dateISO ? ` ${dayLong(dateISO)}` : "";
    if (!sc) {
      return { side: null, dateISO: null, start: null, end: null, tone: "",
               text: "once a stay is booked — the run hangs off its check-in",
               why: "no booked stay to hang it off" };
    }
    const gap = curb == null ? null : sc.in - curb;
    if (gap != null && gap >= SHOP_GAP_MIN) {
      return Object.assign({ side: "before", dateISO }, span(curb, Math.min(curb + SHOP_MIN, sc.in)), {
        tone: "",
        text: `${hhmm(curb)} to ${hhmm(sc.in)}${day} · ${dur(gap)} between clearing bags and the room`,
        why: "you land early enough to shop before check-in",
      });
    }
    const why = curb == null ? "no arrival on the board to measure a gap from"
      : gap <= 0 ? `you clear bags at ${hhmm(curb)}, after check-in`
      : `only ${dur(gap)} between clearing bags and the room`;
    return Object.assign({ side: "after", dateISO }, span(sc.in, sc.in + SHOP_MIN), {
      tone: curb == null ? "warn" : "",
      text: `from ${hhmm(sc.in)}${day} — once you have the room`, why,
    });
  }

  // `text` and `checked`, not `item` and `got`: these rows ARE checklist rows now,
  // read straight out of checklists.db, and a second set of names for the same two
  // fields is how the two copies drifted apart in the first place.
  const GROCERY_FIELDS = (g = {}) => [
    { k: "text", l: "item", value: g.text },
    { k: "qty", l: "how much", value: g.qty },
    { k: "note", l: "note", value: g.note },
  ];

  /* A shopping list is read in a store, so it groups the way a store does.

     The shared list arrives ~30 items long across several sections, and add_items_bulk
     numbers sort_order WITHIN a section, so read back flat, ordered by that
     number, the sections interleave and the run reads as noise. Grouping here
     rather than sorting server-side keeps the section an ordinary editable field
     and leaves a hand-added item (no section) exactly where it was typed: first,
     unlabelled, because that is the row Sam added on purpose.

     Insertion order, not alphabetical, the sections are already in the order the
     seed declares them. */
  function gSections(rows) {
    const order = [], byName = {};
    rows.forEach((r) => {
      const sec = r.section || "";
      if (!(sec in byName)) { byName[sec] = []; order.push(sec); }
      byName[sec].push(r);
    });
    if (order.indexOf("") > 0) { order.splice(order.indexOf(""), 1); order.unshift(""); }
    return order.map((sec) => [sec, byName[sec]]);
  }

  function listGrocery(head, list) {
    // One list shared by every trip; the ticks are this trip's. Covered rows are
    // what the booked stay already stocks (or a kitchen item in a hotel): shown,
    // muted, and left out of the count, so the reader can still overrule it.
    const t = state.trip, all = t.grocery || [];
    const rows = all.filter((r) => !Number(r.covered));
    const got = rows.filter((r) => Number(r.checked)).length;
    const run = groceryRun(t);
    const guest = TC.isGuest();
    // No pick here any more. The side of check-in is derived (groceryRun) and the
    // run draws itself on the itinerary, so the head STATES the answer and says
    // what decided it, a reader who disagrees with the placement is being told
    // which of the two clocks to go and fix.
    const label = run.side ? `${run.side} check-in · ` : "";
    setHTML(head, `
      <div class="hub-figure">
        <div class="hub-figure-fig">
          <span class="hub-figure-n">${got} of ${rows.length}</span>
          <span class="hub-figure-l">in the cart</span>
        </div>
        <div class="hub-figure-split gwin${run.tone ? ` gwin-${run.tone}` : ""}">${esc(label + run.text)}
          <span class="gwhy">${esc(run.why)}</span></div>
      </div>`);

    const left = rows.length - got;
    const sum = !rows.length ? "nothing on it yet"
      : left ? `${left} still to get` : "everything's in the cart";
    const nCov = all.length - rows.length;
    const scope = nCov ? `${nCov} covered by ${t.grocery_stay || "the stay"}` : "";
    const ex = t.grocery_extras || "";
    const extras = guest ? (ex ? `<span class="hub-section-head-sum lgroup-sum">${esc(ex)} extras</span>` : "")
      : `<select class="hub-section-head-act lgroup-act" id="gExtras" aria-label="grocery extras">${
        [["", "no extras"], ["rave", "rave extras"], ["snowboarding", "snowboarding extras"]]
          .map(([v, l]) => `<option value="${v}"${v === ex ? " selected" : ""}>${l}</option>`).join("")}</select>`;
    // Writes are hidden rather than disabled on the mirror: the public app serves
    // no POST/PATCH/DELETE outside its writable set, so a control there could
    // only ever fail on click. Guests read the list; Sam owns it.
    setHTML(list, `<div class="hub-section-head lgroup-head lgroup-sub">
        <span class="hub-section-head-t lgroup-l">the list${scope ? ` <i class="gnote">${esc(scope)}</i>` : ""}</span>
        <span class="hub-section-head-sum lgroup-sum">${esc(sum)}</span>
        ${extras}
        ${guest ? "" : `<button class="hub-section-head-act lgroup-act" id="gAdd">+ add to every trip</button>`}</div>${all.length
      // The same .pkcols the packing lists flow into, and the same reason: an aisle
      // is short, so stacking them puts the back half of the run below the fold on a
      // board you read while walking. An aisle is the unit that never splits across
      // two columns, hence the .pksec wrapper. Reused rather than restated because
      // the packing rules are already keyed on the wrapper, not on the board.
      ? `<div class="hub-column-list pkcols">${gSections(all).map(([sec, items]) => `<div class="pksec">`
        + (sec ? `<div class="hub-list-eyebrow gsec">${esc(sec)}</div>` : "")
        + `<ul class="hub-checklist dolist glist">${items.map((g) => `<li class="hub-checklist-item doitem gitem${Number(g.covered) ? " gitem-covered" : ""}">
          <label class="hub-checkbox-label"><input type="checkbox"${Number(g.covered) ? "" : ` data-got="${esc(String(g.id))}"`}${
            Number(g.checked) ? " checked" : ""}${guest || Number(g.covered) ? " disabled" : ""}>
            <span class="hub-checklist-text"><b class="gitem-n">${esc(g.text || "")}</b>${
              g.qty ? `<i class="gqty">${esc(g.qty)}</i>` : ""}${
              g.note ? `<span class="gnote">${esc(g.note)}</span>` : ""}${
              Number(g.covered) ? `<span class="gnote">${esc(t.grocery_stay || "the stay")} has it</span>` : ""}</span></label>
          ${guest ? "" : `<span class="hub-row-actions"><button class="hub-section-head-act hub-section-head-act-i lgroup-act" data-gedit="${
            esc(String(g.id))}" title="edit ${esc(g.text || "item")}" aria-label="edit ${
            esc(g.text || "item")}">✎</button>${delBtn(`grocery/${g.id}`, g.text || "item")}</span>`}
        </li>`).join("")}</ul></div>`).join("")}</div>`
      : `<div class="hub-section-empty">nothing on the list yet${guest ? "" : " — add the things you can only buy once you're there"}</div>`}`);

    if (guest) return;
    bindDeletes(list);
    $("gAdd").onclick = () => modalForm("add to every trip's grocery run", GROCERY_FIELDS(),
      (d) => API.post(`/trips/${t.id}/grocery`, d), { note: "the list is shared, so this shows on every trip" });
    // Extras are a per-trip choice, so this writes the trip, then reloads it.
    $("gExtras").onchange = (e) => {
      API.patch(`/trips/${t.id}`, { grocery_extras: e.target.value }).then(() => reload())
        .catch((err) => { toast(`extras didn't save — ${errMsg(err)}`); });
    };
    list.querySelectorAll("[data-gedit]").forEach((b) => {
      b.onclick = () => {
        const g = rows.filter((r) => String(r.id) === b.dataset.gedit)[0];
        if (g) modalForm("edit item", GROCERY_FIELDS(g),
          (d) => API.patch(`/trips/${t.id}/grocery/${g.id}`, d), { note: "changes it on every trip" });
      };
    });
    // Ticked in place, never by re-rendering: the list sorts got-last, so a
    // re-render on a tick pulls the row out from under the pointer mid-click and
    // eats the second tick of a two-item pass. The local row is updated with it
    // so the next real render agrees with what is on screen.
    const boxes = list.querySelectorAll("[data-got]"), cnt = head.querySelector(".decide-n");
    const sumEl = list.querySelector(".lgroup-sum");
    boxes.forEach((b) => {
      b.onchange = () => {
        const g = rows.filter((r) => String(r.id) === b.dataset.got)[0];
        const was = g ? g.checked : 0;
        if (g) g.checked = b.checked ? 1 : 0;
        let n = 0;
        boxes.forEach((x) => { if (x.checked) n++; });
        if (cnt) cnt.textContent = `${n} of ${boxes.length}`;
        if (cnt) cnt.classList.toggle("docount-all", n === boxes.length && boxes.length > 0);
        if (sumEl) sumEl.textContent = boxes.length - n
          ? `${boxes.length - n} still to get` : "everything's in the cart";
        API.patch(`/trips/${t.id}/grocery/${b.dataset.got}`, { checked: b.checked ? 1 : 0 }).catch((e) => {
          // The tick did not land, so it must not stay drawn, a checkbox that
          // says "got it" against a row nobody saved is the one failure this
          // list cannot survive.
          b.checked = !b.checked;
          if (g) g.checked = was;
          toast(`tick didn't save — ${errMsg(e)}`);
        });
      };
    });
  }

  // ── WEATHER: what the trip days are actually going to be like ────────────────
  // Its own tab rather than a strip on packing, but it is packing's question: you
  // pack against the low and the rain, not against the destination's reputation.
  // Open-Meteo, the same free no-key CORS-open source the home briefing already
  // reads (static/js/today-weather.jsx), so the code table and the unit params
  // below are that file's, not a second opinion about what "63" means.
  //
  // The board is a LIST and a DAY, the same shape every other tab on this page
  // has: the left column is the run of days with the trip's temperature shape
  // drawn over it, the right column is the day you picked, hour by hour. The old
  // board was a row of five summary cards and nothing else, five sentences with
  // no way to ask any of them a question. One fetch feeds both columns: the daily
  // arrays draw the run, the hourly arrays draw whichever day is open.
  const WX_LABEL = {
    0: "clear",
    1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "rime fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "light showers", 81: "showers", 82: "heavy showers",
    85: "snow showers", 86: "snow showers",
    95: "thunderstorm", 96: "thunderstorm", 99: "hail thunderstorm",
  };
  const wxLabel = (c) => WX_LABEL[c] || "—";

  // One glyph per weather family, drawn on the same 24-box every other icon on
  // this page uses so it inherits .fnav-g's stroke treatment. Grouped by what you
  // would actually do differently, clear, cloudy, wet, frozen, violent, because
  // twenty-eight distinct pictograms is a legend, not a read.
  const WX_ART = {
    sun:   `<circle cx="12" cy="12" r="4.4"/><path d="M12 3.2V5.4M12 18.6V20.8M3.2 12H5.4M18.6 12H20.8M5.8 5.8 7.4 7.4M16.6 16.6 18.2 18.2M18.2 5.8 16.6 7.4M7.4 16.6 5.8 18.2"/>`,
    part:  `<circle cx="9" cy="8.6" r="3.3"/><path d="M9 2.6V4.2M3 8.6H4.6M4.9 4.5 6 5.6M13.1 4.5 12 5.6"/><path d="M8.6 20.4A3.5 3.5 0 0 1 8.6 13.4A5.3 5.3 0 0 1 18.6 14.9A3 3 0 0 1 18.6 20.4Z"/>`,
    cloud: `<path d="M7.4 19.6A4 4 0 0 1 7.9 11.7A6 6 0 0 1 19.2 13.4A3.2 3.2 0 0 1 18.6 19.6Z"/>`,
    fog:   `<path d="M7.6 13.4A3.4 3.4 0 0 1 8.1 6.4A5.4 5.4 0 0 1 18.4 7.9A2.9 2.9 0 0 1 17.9 13.4Z"/><path d="M4.4 16.8H19.6M6.8 20H17.2"/>`,
    rain:  `<path d="M7.6 14.4A3.6 3.6 0 0 1 8.1 7.1A5.6 5.6 0 0 1 18.7 8.6A3 3 0 0 1 18.2 14.4Z"/><path d="M8.8 17.2 7.6 20.6M13 17.2 11.8 20.6M17.2 17.2 16 20.6"/>`,
    snow:  `<path d="M7.6 13.6A3.6 3.6 0 0 1 8.1 6.3A5.6 5.6 0 0 1 18.7 7.8A3 3 0 0 1 18.2 13.6Z"/><path d="M8.6 17.2v2.6M7.4 18.5h2.4M15.4 17.2v2.6M14.2 18.5h2.4M12 19.4v2.4M10.9 20.6h2.2"/>`,
    storm: `<path d="M7.6 13.6A3.6 3.6 0 0 1 8.1 6.3A5.6 5.6 0 0 1 18.7 7.8A3 3 0 0 1 18.2 13.6Z"/><path d="M13.4 15.4 10 19.2h3.2L11.4 22.4"/>`,
    moon:  `<path d="M20.2 14.6A8.6 8.6 0 0 1 9.4 3.8A8.6 8.6 0 1 0 20.2 14.6Z"/>`,
    pmoon: `<path d="M14.6 9.6A5.2 5.2 0 0 1 8.2 3.2A5.2 5.2 0 1 0 14.6 9.6Z"/><path d="M8.4 20.4A3.5 3.5 0 0 1 8.4 13.4A5.3 5.3 0 0 1 18.4 14.9A3 3 0 0 1 18.4 20.4Z"/>`,
  };
  // `night` swaps the two clear-sky glyphs for their moon. A sun printed against
  // 12a in the hour table is the kind of wrong that makes a reader distrust the
  // rest of the row, and it is one branch to not do it. Everything cloudier looks
  // the same after dark, so only those two have a night form.
  function wxArt(code, cls, night) {
    const c = Number(code);
    const k = c === 0 ? (night ? "moon" : "sun") : c <= 2 ? (night ? "pmoon" : "part") : c === 3 ? "cloud"
      : c <= 48 ? "fog"
      : (c >= 71 && c <= 77) || c === 85 || c === 86 || c === 56 || c === 57 || c === 66 || c === 67 ? "snow"
      : c >= 95 ? "storm"
      : c >= 51 ? "rain" : "cloud";
    return `<svg class="wxi ${cls || ""} is-${k}" viewBox="0 0 24 24" aria-hidden="true">${WX_ART[k]}</svg>`;
  }

  // Where the forecast is measured. A trip has no coordinates of its own, so the
  // stay is the anchor: it is the one address you are guaranteed to stand at every
  // day of the trip, and on a trip with several candidates the BOOKED one is the
  // only one that is a fact. Falls back to any stay that has been geocoded, so a
  // trip still pricing rooms gets the right city rather than nothing.
  function wxAnchor(t) {
    const rows = (t?.housing) || [];
    const has = (h) => h && typeof h.lat === "number" && typeof h.lng === "number";
    const booked = rows.filter((h) => has(h) && String(h.status || "").toLowerCase() === "booked")[0];
    const any = rows.filter(has)[0];
    const h = booked || any;
    return h ? { lat: h.lat, lng: h.lng, name: h.name || "", firm: h === booked } : null;
  }

  // Which trip days a forecast can actually cover. Open-Meteo runs 16 days out and
  // does not go backwards, so a trip is in one of four states and each one is said
  // outright rather than rendered as an empty board. Dates are compared as ISO
  // strings on purpose: they are already local calendar days on both sides, and
  // parsing them into Date objects is what introduces a timezone to be wrong about.
  const WX_HORIZON = 15;   // today + 15 = the 16th day, Open-Meteo's last
  // Shifted through UTC midnight, the same footing T.dayRange and dayLabel already
  // stand on, so a day never lands one off across a DST boundary.
  const wxShift = (iso, n) =>
    new Date(Date.parse(`${iso}T00:00:00Z`) + n * 86400000).toISOString().slice(0, 10);
  function wxWindow(days, today) {
    if (!days.length) return { shown: [], state: "none" };
    const last = wxShift(today, WX_HORIZON);
    const shown = days.filter((d) => d >= today && d <= last);
    if (days[days.length - 1] < today) return { shown: [], state: "past" };
    if (days[0] > last) return { shown: [], state: "far", opens: wxShift(days[0], -WX_HORIZON) };
    return { shown, state: shown.length === days.length ? "ok" : "partial", missing: days.length - shown.length };
  }

  // One fetch, both columns. `hourly` is what the day view is made of and it is
  // the expensive half of the payload, roughly 24 numbers per field per day ,
  // but it arrives in the same round trip as the summary, and a second fetch on
  // every day click would put a spinner between a click and a chart that is
  // already in memory. Ten fields over a five-day trip is ~1200 numbers, which is
  // smaller than the housing board's photo list.
  function wxUrl(a, from, to) {
    return "https://api.open-meteo.com/v1/forecast?latitude=" + a.lat + "&longitude=" + a.lng
      + "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
      + "apparent_temperature_max,apparent_temperature_min,"
      + "precipitation_probability_max,precipitation_sum,snowfall_sum,precipitation_hours,"
      + "wind_speed_10m_max,wind_gusts_10m_max,wind_direction_10m_dominant,"
      + "uv_index_max,sunrise,sunset,daylight_duration"
      + "&hourly=temperature_2m,apparent_temperature,relative_humidity_2m,"
      + "precipitation_probability,precipitation,weather_code,cloud_cover,"
      + "wind_speed_10m,wind_gusts_10m,uv_index"
      + "&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch"
      + "&timezone=auto&start_date=" + from + "&end_date=" + to;
  }

  // The daily arrays come back column-wise (one array per field, all the same
  // length, indexed by date). Turned into a row per day here so nothing downstream
  // has to index four arrays in step.
  function wxRows(d) {
    const dt = (d?.daily) || {};
    const at = (k, i) => (Array.isArray(dt[k]) ? dt[k][i] : null);
    return (dt.time || []).map((iso, i) => ({
      date: iso,
      code: at("weather_code", i),
      hi: at("temperature_2m_max", i),
      lo: at("temperature_2m_min", i),
      feelsHi: at("apparent_temperature_max", i),
      feelsLo: at("apparent_temperature_min", i),
      pop: at("precipitation_probability_max", i),
      rain: at("precipitation_sum", i),
      snow: at("snowfall_sum", i),
      wetHours: at("precipitation_hours", i),
      wind: at("wind_speed_10m_max", i),
      gust: at("wind_gusts_10m_max", i),
      dir: at("wind_direction_10m_dominant", i),
      uv: at("uv_index_max", i),
      sunrise: at("sunrise", i),
      sunset: at("sunset", i),
      daylight: at("daylight_duration", i),
    }));
  }

  // The hourly arrays are one flat run across the whole range, so they are cut
  // into days here, keyed by the date the timestamp already carries, never by
  // dividing the index by 24. A range that starts mid-day, or a DST day with 23
  // or 25 hours in it, breaks the division and not the key.
  function wxHours(d) {
    const h = (d?.hourly) || {};
    const at = (k, i) => (Array.isArray(h[k]) ? h[k][i] : null);
    const by = {};
    (h.time || []).forEach((ts, i) => {
      const day = String(ts).slice(0, 10);
      (by[day] || (by[day] = [])).push({
        at: ts,
        hour: Number(String(ts).slice(11, 13)),
        temp: at("temperature_2m", i),
        feels: at("apparent_temperature", i),
        hum: at("relative_humidity_2m", i),
        pop: at("precipitation_probability", i),
        precip: at("precipitation", i),
        code: at("weather_code", i),
        cloud: at("cloud_cover", i),
        wind: at("wind_speed_10m", i),
        gust: at("wind_gusts_10m", i),
        uv: at("uv_index", i),
      });
    });
    return by;
  }

  // Month and day, not the weekday: this stamp is only ever used for a date months
  // out, where "Tue 1" is the one form that cannot tell you which Tuesday.
  const wxDate = (iso) => {
    const d = new Date(`${iso}T00:00:00Z`);
    return `${U.MON[d.getUTCMonth()]} ${d.getUTCDate()}`;
  };
  const WX_DOW = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  const wxLongDay = (iso) => `${WX_DOW[new Date(`${iso}T00:00:00Z`).getUTCDay()]}, ${wxDate(iso)}`;
  // A day is wet if rain is actually forecast to FALL on it, not only if the
  // probability clears a bar. Denver's Saturday and Monday came back at 9% and 29%
  // with 0.06" and 0.09" on them and the word "drizzle" printed on the card, and a
  // headline reading "nothing wet in the run" over that is the board arguing with
  // itself. Probability still counts on its own: a 60% day with no accumulation
  // forecast yet is exactly the day you want the shell for.
  const wxWet = (r) => (r.pop || 0) >= 40 || (r.rain || 0) >= 0.05 || (r.snow || 0) >= 0.05;
  const wxNum = (v, unit) => (v === null || v === undefined || Number.isNaN(v) ? "—" : Math.round(v) + (unit || ""));
  const wxHas = (v) => v !== null && v !== undefined && !Number.isNaN(v);

  // "6:41a", the clock form the rest of the board uses. Open-Meteo hands sun times
  // back as a local ISO stamp with no zone on it, which is exactly what is wanted
  // here, the destination's own clock, so the string is sliced, never parsed.
  function wxClock(stamp) {
    const m = /T(\d{2}):(\d{2})/.exec(String(stamp || ""));
    if (!m) return "—";
    const h = Number(m[1]);
    return `${(h % 12) || 12}:${m[2]}${h < 12 ? "a" : "p"}`;
  }
  const wxHourLabel = (h) => ((h % 12) || 12) + (h < 12 ? "a" : "p");
  // Fractional hour, for placing the sun line on an hourly axis.
  function wxSunHour(stamp) {
    const m = /T(\d{2}):(\d{2})/.exec(String(stamp || ""));
    return m ? Number(m[1]) + Number(m[2]) / 60 : null;
  }
  const wxDaylight = (sec) => {
    if (!wxHas(sec)) return "—";
    const h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60);
    return `${h}h ${String(m).padStart(2, "0")}m`;
  };
  const WX_COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                      "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
  const wxDir = (deg) => (wxHas(deg) ? WX_COMPASS[Math.round((((deg % 360) + 360) % 360) / 22.5) % 16] : "—");
  // The UV number alone means nothing to anyone who has not memorised the scale,
  // so it is always said in words. WHO's bands, not invented ones.
  const wxUvWord = (v) => (!wxHas(v) ? "—" : v < 3 ? "low" : v < 6 ? "moderate" : v < 8 ? "high" : v < 11 ? "very high" : "extreme");

  // ── THE CHART PRIMITIVES ────────────────────────────────────────────────────
  // Hand-rolled inline SVG rather than a charting library. Four shapes are needed
  // here, a filled band between two series, a line, a row of bars, and a shaded
  // region, all on one abstract viewBox that CSS scales to whatever the column
  // is, and every colour is a theme token so the charts follow vesper/cobalt/glass
  // like everything else on the board. A library would be ninety kilobytes to draw
  // a polyline, would ship its own palette to fight, and would need a second
  // theme adapter written anyway.
  //
  // Every chart draws into a box measured in viewBox units. `l/r/t/b` are the
  // gutters the axis labels live in; the plot is what is left.
  const wxPlot = (B) => ({ w: B.w - B.l - B.r, h: B.h - B.t - B.b });

  // Point-x: the first and last samples sit ON the edges, which is what a line
  // wants. Band-x (wxBX) puts each sample in a slot of its own, which is what a
  // bar wants, a bar centred on the edge is half outside the plot.
  const wxPX = (i, n, B) => (n <= 1 ? B.l + wxPlot(B).w / 2 : B.l + (i / (n - 1)) * wxPlot(B).w);
  const wxBX = (i, n, B) => B.l + (i / Math.max(n, 1)) * wxPlot(B).w;
  const wxBW = (n, B) => wxPlot(B).w / Math.max(n, 1);
  const wxY = (v, s, B) => B.t + (s.hi === s.lo ? 0.5 : (s.hi - v) / (s.hi - s.lo)) * wxPlot(B).h;

  // The y range for a set of series, padded so a flat line is not welded to the
  // frame and a peak is not clipped by it. `floor`/`ceil` pin an axis that has a
  // meaningful end, a rain-chance axis always runs 0 to 100, whatever the day.
  function wxScale(vals, opt) {
    const o = opt || {};
    const v = vals.filter(wxHas);
    if (!v.length) return null;
    let lo = Math.min(...v), hi = Math.max(...v);
    if (hi === lo) { hi += 1; lo -= 1; }
    const pad = (hi - lo) * (o.pad == null ? 0.14 : o.pad);
    lo -= pad; hi += pad;
    if (o.floor != null) lo = o.floor;
    if (o.ceil != null) hi = o.ceil;
    return { lo, hi };
  }

  // A polyline through the samples, breaking at every hole rather than drawing a
  // straight line across it. A missing hour is missing, and a chart that bridges
  // it is inventing a reading.
  function wxLine(vals, s, B, xf) {
    const X = xf || wxPX;
    let d = "", pen = false;
    vals.forEach((v, i) => {
      if (!wxHas(v)) { pen = false; return; }
      d += `${(pen ? "L" : "M") + X(i, vals.length, B).toFixed(1)} ${wxY(v, s, B).toFixed(1)} `;
      pen = true;
    });
    return d.trim();
  }
  // The area under a line, closed to the floor of the plot. Only ever used on a
  // series that has no holes worth arguing about (temperature, wind); a broken
  // area reads as two separate days.
  function wxArea(vals, s, B, xf) {
    const d = wxLine(vals, s, B, xf);
    if (!d) return "";
    const idx = vals.map((v, i) => (wxHas(v) ? i : -1)).filter((i) => i >= 0);
    const X = xf || wxPX;
    const base = (B.h - B.b).toFixed(1);
    return d + " L" + X(idx[idx.length - 1], vals.length, B).toFixed(1) + " " + base
             + " L" + X(idx[0], vals.length, B).toFixed(1) + " " + base + " Z";
  }
  // Band between two series, the trip's high and low, closed into one shape. The
  // read it carries that two lines do not: the THICKNESS is the day's swing, so a
  // trip with a 40-degree diurnal range looks different from a flat one at a
  // glance, before any number is read.
  function wxBand(his, los, s, B, xf) {
    const X = xf || wxPX;
    const ok = his.map((v, i) => wxHas(v) && wxHas(los[i]));
    if (!ok.some(Boolean)) return "";
    let up = "", down = "";
    his.forEach((v, i) => { if (ok[i]) up += `${(up ? "L" : "M") + X(i, his.length, B).toFixed(1)} ${wxY(v, s, B).toFixed(1)} `; });
    for (let i = los.length - 1; i >= 0; i--) {
      if (ok[i]) down += `L${X(i, los.length, B).toFixed(1)} ${wxY(los[i], s, B).toFixed(1)} `;
    }
    return `${(up + down).trim()} Z`;
  }
  // Horizontal gridlines with their value in the left gutter. Three of them: any
  // more and the chart is a table with a line drawn through it.
  function wxGrid(s, B, unit, ticks) {
    const n = ticks || 3;
    let out = "";
    for (let i = 0; i < n; i++) {
      const v = s.lo + ((s.hi - s.lo) * i) / (n - 1);
      const y = wxY(v, s, B).toFixed(1);
      out += `<line class="hub-chart-grid" x1="${B.l}" x2="${B.w - B.r}" y1="${y}" y2="${y}"/>`
           + `<text class="hub-chart-ax" x="${B.l - 6}" y="${y}" text-anchor="end" dominant-baseline="middle">${Math.round(v) + (unit || "")}</text>`;
    }
    return out;
  }

  // ── THE TRIP SHAPE, one chart over the whole run ───────────────────────────
  // Two stacked plots sharing an x axis of trip days: the temperature band on
  // top, the rain chance underneath. Stacked rather than dual-axis on purpose ,
  // a second y axis on the right is the chart convention that most reliably gets
  // misread, and these two quantities are never compared to each other, only
  // read down the same column of days.
  function wxTripChart(rows) {
    const B = { w: 680, h: 222, l: 30, r: 26, t: 14, b: 78 };   // r holds half a day label; b holds the rain strip + labels
    const his = rows.map((r) => r.hi), los = rows.map((r) => r.lo);
    const s = wxScale(his.concat(los), { pad: 0.22 });
    if (!s) return "";
    const n = rows.length;
    const rainTop = B.h - 56, rainH = 32;                       // the strip under the temp plot
    const rainY = (p) => rainTop + rainH - (Math.max(0, Math.min(100, p || 0)) / 100) * rainH;
    const bw = wxBW(n, B), gap = Math.min(bw * 0.34, 14);

    const band = wxBand(his, los, s, B);
    const pts = rows.map((r, i) => {
      const x = wxPX(i, n, B);
      const sel = r.date === state.selId;
      return `<g class="hub-chart-col${sel ? " is-sel" : ""}" data-wxday="${esc(r.date)}">
        <rect class="hub-chart-hit" x="${(x - bw / 2).toFixed(1)}" y="${B.t}" width="${bw.toFixed(1)}" height="${(B.h - B.t - 18).toFixed(1)}"/>
        ${wxHas(r.hi) ? `<circle class="hub-chart-dot wxg-dot is-hi" cx="${x.toFixed(1)}" cy="${wxY(r.hi, s, B).toFixed(1)}" r="3.4"/>
          <text class="hub-chart-v" x="${x.toFixed(1)}" y="${(wxY(r.hi, s, B) - 8).toFixed(1)}" text-anchor="middle">${wxNum(r.hi, "°")}</text>` : ""}
        ${wxHas(r.lo) ? `<circle class="hub-chart-dot wxg-dot is-lo" cx="${x.toFixed(1)}" cy="${wxY(r.lo, s, B).toFixed(1)}" r="3.4"/>
          <text class="hub-chart-v wxg-v is-lo" x="${x.toFixed(1)}" y="${(wxY(r.lo, s, B) + 15).toFixed(1)}" text-anchor="middle">${wxNum(r.lo, "°")}</text>` : ""}
        <rect class="hub-chart-bar wxg-bar${wxWet(r) ? " is-wet" : ""}" x="${(x - bw / 2 + gap / 2).toFixed(1)}" y="${rainY(r.pop).toFixed(1)}"
              width="${Math.max(bw - gap, 3).toFixed(1)}" height="${(rainTop + rainH - rainY(r.pop)).toFixed(1)}"/>
        <text class="hub-chart-minor" x="${x.toFixed(1)}" y="${(rainTop - 4).toFixed(1)}" text-anchor="middle">${wxNum(r.pop, "%")}</text>
        <text class="hub-chart-cat" x="${x.toFixed(1)}" y="${(B.h - 4).toFixed(1)}" text-anchor="middle">${esc(dayLabel(r.date))}</text>
      </g>`;
    }).join("");

    return `<div class="hub-chart wxchart is-trip"><svg viewBox="0 0 ${B.w} ${B.h}" role="img"
        aria-label="high and low temperature and rain chance for each day of the trip">
      ${wxGrid(s, Object.assign({}, B, { b: B.b }), "°")}
      <path class="hub-chart-band" d="${band}"/>
      <path class="hub-chart-line wxg-ln is-hi" d="${wxLine(his, s, B)}"/>
      <path class="hub-chart-line wxg-ln is-lo" d="${wxLine(los, s, B)}"/>
      <line class="hub-chart-base" x1="${B.l}" x2="${B.w - B.r}" y1="${rainTop + rainH}" y2="${rainTop + rainH}"/>
      <text class="hub-chart-ax" x="${B.l - 6}" y="${rainTop + rainH / 2}" text-anchor="end" dominant-baseline="middle">rain</text>
      ${pts}
    </svg></div>`;
  }

  // ── ONE HOURLY CHART ────────────────────────────────────────────────────────
  // Four kinds, one builder: they share the axis, the night shading, the now-line
  // and the hole handling, and differ only in which series they pull and how they
  // draw it. Four near-identical functions is how a chart set drifts, one gets a
  // fix for a hole in the data and the other three keep bridging it.
  function wxHourChart(hrs, kind, day, today) {
    const B = { w: 680, h: 168, l: 32, r: 10, t: 16, b: 26 };
    const n = hrs.length;
    if (!n) return "";
    const spec = {
      temp: { series: ["temp", "feels"], unit: "°", label: "temperature through the day" },
      rain: { series: ["pop"], unit: "%", label: "chance of rain hour by hour", bars: true, scale: { floor: 0, ceil: 100 } },
      wind: { series: ["gust", "wind"], unit: "", label: "wind and gusts through the day", scale: { floor: 0 } },
      // cloud is a LINE here, not an area under the humidity line. Drawn as a fill
      // it spends most of an overcast day pinned at 100%, which paints a grey slab
      // over the whole plot in the same grey the night shading uses, two different
      // facts rendered as one indistinguishable block.
      hum:  { series: ["hum", "cloud"], unit: "%", label: "humidity and cloud cover through the day", scale: { floor: 0, ceil: 100 } },
    }[kind];
    const cols = spec.series.map((k) => hrs.map((h) => h[k]));
    const s = wxScale(cols.flat(), Object.assign({}, spec.scale || {}, { pad: spec.scale ? 0 : 0.18 }));
    if (!s) return "";

    // Night is shaded rather than labelled: the eye reads "this peak is at 3pm"
    // off the band without a tick being consulted. Sun times come from the DAY
    // row, so a chart drawn for a day with no sun data simply has no shading.
    const sunUp = wxSunHour(day.sunrise), sunDown = wxSunHour(day.sunset);
    const hx = (h) => wxPX(h, 24, B);
    const night = (sunUp != null && sunDown != null)
      ? `<rect class="hub-chart-shade" x="${B.l}" y="${B.t}" width="${Math.max(0, hx(sunUp) - B.l).toFixed(1)}" height="${wxPlot(B).h}"/>`
        + `<rect class="hub-chart-shade" x="${hx(sunDown).toFixed(1)}" y="${B.t}" width="${Math.max(0, B.w - B.r - hx(sunDown)).toFixed(1)}" height="${wxPlot(B).h}"/>`
      : "";

    // The hour you are standing in, but only on the day you are standing in.
    const nowH = day.date === today ? new Date().getHours() + new Date().getMinutes() / 60 : null;
    const now = nowH != null
      ? `<line class="wxg-now" x1="${hx(nowH).toFixed(1)}" x2="${hx(nowH).toFixed(1)}" y1="${B.t}" y2="${B.h - B.b}"/>`
      : "";

    let body;
    if (spec.bars) {
      const bw = wxBW(n, B);
      body = hrs.map((h, i) => (wxHas(h.pop) ? `<rect class="hub-chart-bar wxg-bar${(h.precip || 0) >= 0.01 ? " is-wet" : ""}"
        x="${(wxBX(i, n, B) + 0.6).toFixed(1)}" y="${wxY(h.pop, s, B).toFixed(1)}"
        width="${Math.max(bw - 1.2, 1).toFixed(1)}" height="${Math.max(0, B.h - B.b - wxY(h.pop, s, B)).toFixed(1)}"
        ><title>${wxHourLabel(h.hour)} · ${wxNum(h.pop, "%")}${(h.precip || 0) >= 0.01 ? ` · ${h.precip.toFixed(2)}"` : ""}</title></rect>` : "")).join("");
    } else {
      body = `<path class="wxg-fill" d="${wxArea(cols[0], s, B)}"/>`
        + cols.map((c, i) => `<path class="hub-chart-line wxg-ln is-${i}" d="${wxLine(c, s, B)}"/>`).join("");
    }

    // Every third hour, so the axis reads 12a 3a 6a … on any column width.
    const ticks = hrs.filter((h) => h.hour % 3 === 0).map((h) =>
      `<text class="hub-chart-cat" x="${hx(h.hour).toFixed(1)}" y="${(B.h - 6).toFixed(1)}" text-anchor="middle">${wxHourLabel(h.hour)}</text>`).join("");

    return `<div class="hub-chart wxchart is-hour"><svg viewBox="0 0 ${B.w} ${B.h}" role="img" aria-label="${esc(spec.label)}">
      ${night}${wxGrid(s, B, spec.unit)}${body}${now}${ticks}
    </svg></div>`;
  }

  // A chart is only half a read without saying which line is which, and a legend
  // that is a coloured square and a word is cheaper than annotating the lines.
  const wxKey = (items) => `<div class="hub-legend wxkey">${items.map((k) =>
    `<span class="hub-legend-item"><i class="hub-legend-swatch wxk-s ${esc(k.cls)}"></i>${esc(k.label)}</span>`).join("")}</div>`;


Object.assign(U, {
  detailActivity, detailLogistics, detailMember, detailExpense,
  loadFood, unmountFood, listFood, groceryRun,
  gSections, listGrocery, wxLabel, wxArt,
  wxAnchor, WX_HORIZON, wxWindow, wxUrl,
  wxRows, wxHours, wxDate, wxLongDay,
  wxWet, wxNum, wxHas, wxClock,
  wxHourLabel, wxSunHour, wxDaylight, wxDir,
  wxUvWord, wxTripChart, wxHourChart, wxKey,
});
})();
