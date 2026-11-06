/* hub · trips page, money (2026-10-13): React port of trips.js lines 2690-3438 (cost tab, money cells,
   activities list, itinerary calendar, one day). Near-verbatim plain functions that build HTML strings and
   write them into the fixed hosts; see trips-core.jsx for the shape and /tmp/hub-sandbox/trips-parts-interface.md
   for the part contract. No object spread, no async/await (geocodeTrip is a promise chain). */
(() => {
const U = window.TripsUI;
const { esc, setHTML, toast, status, errMsg, state, $, T, TC, money, num1, parseTags, haversine,
  firstName, statusLabel, pipVar, PIP_STATUSES, viewerKey, isViewer, myFlights, chosenStay, housingAnchor,
  distFromStay, tripMoney, costChart, renderAll } = U;
const API = U.api;
const { renderFocus, renderContext, tripDays, delBtn, bindDeletes, renderDayMap, itineraryModel, dayLabel,
  timelineHTML, memberFor, meMember, logiPipVar, addActivity, editCostRow, memberNames
} = U.fwd("renderFocus", "renderContext", "tripDays", "delBtn", "bindDeletes", "renderDayMap", "itineraryModel",
  "dayLabel", "timelineHTML", "memberFor", "meMember", "logiPipVar", "addActivity", "editCostRow", "memberNames");
const myFares = U.myFares;

  /* ── COST: every line that makes the number ──────────────────────────────────
     The pinned money block answers "how much". This tab answers "out of what,
     and why isn't X in it" — the question the block cannot answer and the reason
     a total nobody can reconstruct is a total nobody trusts.

     Every other board shows its own rows at their own prices. What none of them
     shows is which of those rows the TOTAL counted. Six fares sit on the Denver
     flights board and exactly one is his seat; eighteen rows sit on the ground
     board and the projection counts one car, because rentals are alternatives to
     each other. So each category prints the lines that were counted, at both
     prices, and says in one line what it left out. */
  const COST_CATS = [
    { key: "housing", label: "stay" },
    { key: "flights", label: "flights" },
    { key: "transportation", label: "ground" },
    { key: "expenses", label: "other" },
  ];

  // "terminal" is the label the bare values need ("C", "5"), but Avianca's rows
  // already carry the word ("Terminal 4") and got it twice — "terminal Terminal 4",
  // which then broke across two lines. Prefix only what isn't already prefixed, and
  // bind the word to its value so the pair never splits.
  function terminalText(v) {
    const t = String(v || "").trim();
    if (!t) return "";
    // Single-terminal airports (IAD, CMH) carry the concourse instead.
    return /^(terminals?|concourse)\b/i.test(t) ? t.replace(/\s+/, "\u00a0") : `terminal\u00a0${t}`;
  }

  // An airport pair is one value, not three words: a plain " → " let the cost
  // table break the line between "LGA →" and "DEN" and read as half a route.
  const routeText = (from, to) => `${from || "?"}\u00a0\u2192\u00a0${to || "?"}`;

  function costRowName(r) {
    const x = r.row;
    if (r.table === "housing") return x.name || x.address || "the stay";
    if (r.table === "flights") {
      const leg = (x.from_airport || x.to_airport) ? routeText(x.from_airport, x.to_airport) : "";
      const id = [x.airline, x.flight_num].filter(Boolean).join(" ");
      return (id || "flight") + (leg ? ` · ${leg}` : "");
    }
    if (r.table === "transportation") return x.description || x.type || "transport";
    return x.description || x.category || "expense";
  }

  // WHO SHARES IT — chips under the line, and only chips. They used to sit
  // beside a "split" button at the far end of the row; the button is gone with
  // the rest of the in-table controls, and the names are now a pure readout of
  // what the cost editor holds. Sam, 2026-08-26: "instead of having a split
  // button and seeing the cents per point, we replace the expanded popup."
  // Untagged shared rows read `everyone · 7` (the crew list is the default);
  // a tagged row wears its people. Past three names the tail folds into `+N`,
  // because seven pills wrap the line four deep.
  function splitWho(r) {
    const crew = state.trip.members || [];
    const named = TC.splitIds(r.row);
    const first = (n) => String(n).trim().split(/\s+/)[0];
    const names = (named || []).map((id) => first(crew.find((m) => String(m.id) === id)?.name || id));
    const chips = named
      ? (named.length >= crew.length ? [`everyone · ${named.length}`]
         : names.length > 3 ? names.slice(0, 3).concat(`+${names.length - 3}`)
         : names)
      : r.split > 1 ? [`everyone · ${r.split}`] : [];
    if (!chips.length) return "";
    const tip = named ? `splits between ${memberNames(r.row.split_with)}`
                      : "splits across the whole crew";
    return `<span class="lsplit-who${named ? " is-set" : ""}" title="${esc(tip)}">${
      chips.map((c) => `<span class="hub-pill lsplit-chip">${esc(c)}</span>`).join("")}</span>`;
  }

  // Which column on each table holds the cash price, and which holds the points.
  // The cost editor writes through these; nothing on the table itself does.
  const CASH_FIELD = { housing: "total_cost", flights: "cost", transportation: "cost", expenses: "amount" };
  const pointsField = (row) => (Number(row.points_transfer) ? "points_transfer" : "points_total");

  // WHOSE CARD IT IS ON. The other half of splitWho: that one says who a line
  // divides between, this one says who actually put the money down, and it
  // takes only one name because that is how a till works. A readout, like the
  // chips — the answer is changed in the row's cost editor. Without it the
  // settlement has a hole: a $1,866 stay nobody claims can be counted but never
  // paid back, which is why an unclaimed line says so out loud.
  function payerCell(r) {
    const crew = state.trip.members || [];
    // TC.payerOf, not the raw column: a legacy typed name is not a crew id and
    // must read as unclaimed here too, or the chip and the ledger disagree.
    const who = crew.find((m) => String(m.id) === TC.payerOf(r.row, crew.map((x) => String(x.id))));
    return who
      ? `<span class="hub-pill lpayer is-set" title="${esc(`${who.name} put this down`)}">${esc(firstName(who.name))}</span>`
      : `<span class="lpaid-na" title="nobody has claimed this line — open the row to say whose card it went on">—</span>`;
  }
  // What the board holds versus what the total counted. Flights count his money,
  // not his seats, so the board's row count is the wrong denominator there — a
  // ticket somebody else bought is not an "uncounted option", it is not his
  // money at all, while one he bought for them is.
  function costLeftOut(t, table, counted) {
    const mine = table === "flights" ? myFares(t).length : (t[table] || []).length;
    const theirs = table === "flights" ? (t.flights || []).length - mine : 0;
    const spare = mine - counted;
    const bits = [];
    if (spare > 0) bits.push(`${spare} other row${spare === 1 ? "" : "s"} on the board`);
    if (theirs > 0) bits.push(`${theirs} ticket${theirs === 1 ? "" : "s"} someone else paid for`);
    return bits.join(" · ");
  }

  /* ── ONE TRAVELLER'S TICKET, NOT FOUR LOOSE FARES ──────────────────────────
     The flights block printed every counted leg flat, which on El Salvador reads
     as four unassigned fares when it is two round trips on two bookings — and one
     of those is a seat he bought for somebody else. So flight lines fold: a
     summary row per traveller carrying what their whole ticket came to, the legs
     underneath it, collapsed until clicked.
     Sam, 2026-08-25: "instead of having it look like there are four
     unassigned flights when there are only two round trips under the same
     booking … specify when a flight is for one person."
     ponytail: grouped by PERSON, not by record locator. Two separate bookings for
       one traveller on one trip would read as one ticket here; no trip has had
       them, and `confirmation` is blank on enough rows that keying on it would
       split a ticket in half on the trips that do. */
  function travellerOf(t, r) {
    const who = (r.row.passenger || "").trim();
    // The roster name wins: the ticket says Sophia because a passport has to
    // match, the crew list says Aria because that is who she is.
    const m = who ? memberFor(t, who) : meMember(t);
    // "you" only when the person READING it is that traveller. On Hub that is
    // always him; on the public mirror it is whoever unlocked the link, and
    // printing "you" over his ticket there addresses the wrong person.
    const you = viewerKey() ? isViewer(m) : !who;
    return { name: you ? "you" : (m ? m.name : who), mine: !who, you: you };
  }
  function ticketShape(rows) {
    const d = rows.map((r) => String(r.row.direction || "outbound").toLowerCase());
    const rt = d.indexOf("roundtrip") >= 0 || (d.indexOf("outbound") >= 0 && d.indexOf("return") >= 0);
    return `${rt ? "round trip" : "one way"} · ${rows.length}${rows.length === 1 ? " leg" : " legs"}`;
  }
  // Which groups are open, kept outside the render so an edit does not slam
  // every ticket shut again.
  const costGroupOpen = {};

  /* ── THE MONEY CELLS ───────────────────────────────────────────────────────
     Three figures, all of them read-only text: what the line cost in cash, what
     it cost in points where points were spent, and what one head's share of it
     comes to. Nothing here is an input any more — four unlocking cells and a
     back-solving total were a spreadsheet grafted onto a table you read.
     Sam, 2026-08-26: "the cash in points and cents per point, total, and
     all that bull crap … how we just simplify it."

     SHARE is the number the tab was missing. "Who is splitting it" and "what
     does that come to each" are one question, and the chips under the line only
     ever answered the first half. It carries BOTH currencies, because a stay
     bought on points is a points debt divided exactly the way a cash one is —
     "points, if relevant, so points can be owed there as well."
     A line that splits one way has no share to state: printing the total twice
     is not a second fact. */
  function sumMoney(rows, per) {
    return rows.reduce((a, r) => {
      const f = per ? (r.mine != null ? r.mine : 1 / (r.split || 1)) : 1;
      return { cash: a.cash + r.cash * f, ur: a.ur + r.ur * f, urCash: a.urCash + r.urCash * f };
    }, { cash: 0, ur: 0, urCash: 0 });
  }
  // Same figure the section head and the chart now use (TC.myFactor): YOUR
  // share, not "one head's". They have to agree — a flights block summing to
  // $180.00 over rows whose share column reads $250.00 is two answers to one
  // question. A ticket bought for somebody else reads $0.00 here, which is what
  // it costs him once she pays him back, and the rail says who owes it.
  const differs = (a, b) => Math.abs(a.cash - b.cash) > 0.005 || Math.abs(a.ur - b.ur) > 0.5;
  function moneyCells(rows, pointsCol) {
    const tot = sumMoney(rows, false);
    const mine = sumMoney(rows, true);
    const share = differs(mine, tot) ? mine : null;
    return `<td class="hub-num"><span class="hub-text-muted">${tot.cash ? money(tot.cash) : "—"}</span></td>`
      + (pointsCol ? `<td class="hub-num">${tot.ur
          ? `<span class="hub-text-muted">${Number(tot.ur).toLocaleString()}</span>`
          : `<span class="hub-text-faint" title="no points on this line">—</span>`}</td>` : "")
      + `<td class="hub-num">${share ? U.priceHtml(share)
          : `<span class="hub-text-faint" title="the whole line is yours — no share to state separately">—</span>`}</td>`;
  }

  function costGroupRow(g, pointsCol) {
    const open = !!costGroupOpen[g.key];
    const st = g.rows.map((r) => statusLabel(r.row.status || "—"));
    const uniform = st.every((x) => x === st[0]);
    const payers = g.rows.filter((r) => r.cash || r.ur).map((r) => TC.payerOf(r.row, (state.trip.members || []).map((m) => String(m.id))));
    const payer = payers.length && payers.every((x) => x && x === payers[0])
      ? (state.trip.members || []).find((m) => String(m.id) === payers[0]) : null;
    return `<tr class="lrow is-costgrp${open ? " is-open" : ""}" data-costgrp="${esc(g.key)}"
        style="cursor:pointer" title="${esc(g.you ? "your ticket — click for the legs"
          : `${g.name}'s ticket, on your card — click for the legs`)}">
      <td><span class="cost-grp-c">${open ? "▾" : "▸"}</span><span class="cost-grp-n">${esc(g.name)}</span>
        <span class="cost-grp-for">${esc(g.you ? "your seat" : `for ${firstName(g.name)}`)}</span>
        <span class="lsplit-line"><span class="cost-grp-shape">${esc(ticketShape(g.rows))}</span></span></td>
      <td class="lstatus"><span class="hub-dot" style="--dot-color: var(${logiPipVar(g.rows[0].row)})">${
        esc(uniform ? st[0] : "mixed")}</span></td>
      <td class="lpaid">${payer ? `<span class="hub-pill lpayer is-set">${esc(firstName(payer.name))}</span>`
        : `<span class="lpaid-na" title="the legs were not all put down by the same person">—</span>`}</td>
      ${moneyCells(g.rows, pointsCol)}</tr>`;
  }

  // The body of one cost category. Flights fold per traveller; everything else
  // is a flat list, because a stay and a car are one line each already.
  function costBodyHTML(t, key, rows, pointsCol) {
    const byPrice = (a, b) => (b.cash + b.ur / 1e6) - (a.cash + a.ur / 1e6);
    if (key !== "flights") return rows.slice().sort(byPrice).map((r) => costRowHTML(r, pointsCol)).join("");
    const groups = [];
    rows.forEach((r) => {
      const who = travellerOf(t, r);
      let g = groups.filter((x) => x.name === who.name)[0];
      if (!g) groups.push(g = { key: `${key}:${who.name}`, name: who.name, mine: who.mine, you: who.you, rows: [] });
      g.rows.push(r);
    });
    // The reader's own ticket first, then everyone whose fare is on this card.
    groups.sort((a, b) => (b.you ? 1 : 0) - (a.you ? 1 : 0) || (b.mine ? 1 : 0) - (a.mine ? 1 : 0));
    // Inside a ticket the order is the journey, not the price: out, then back.
    const legOrder = { outbound: 0, roundtrip: 1, return: 2 };
    return groups.map((g) => costGroupRow(g, pointsCol) + g.rows.slice().sort((a, b) => {
      const d = (legOrder[String(a.row.direction || "outbound").toLowerCase()] ?? 1)
              - (legOrder[String(b.row.direction || "outbound").toLowerCase()] ?? 1);
      return d || String(a.row.departure_time || "").localeCompare(String(b.row.departure_time || ""));
    }).map((r) => costRowHTML(r, pointsCol, g)).join("")).join("");
  }

  function costRowHTML(r, pointsCol, grp) {
    // A counted line with no charge of its own is real — the return leg of a
    // round trip is on the outbound's ticket. Dropping it would hide half
    // the journey; moneyCells prints it as dashes, which is the truth.
    const free = !r.cash && !r.ur;
    return `<tr class="lrow is-cost-editable${free ? " is-free" : ""}${
      grp ? ` is-costleg${costGroupOpen[grp.key] ? " is-shown" : ""}` : ""}"${
      grp ? ` data-costleg="${esc(grp.key)}"` : ""} data-editrow="${esc(r.table)}:${r.row.id}"${TC.isGuest() ? "" : ' style="cursor:pointer"'}${free ? ' title="counted, but carries no charge of its own — it is on another row\'s booking"' : ' title="click to edit what this costs and who it splits between"'}>
      <td>${grp ? `<span class="cost-leg-d">${esc(U.LEG_LABEL[String(r.row.direction || "outbound").toLowerCase()] || r.row.direction || "leg")}</span>` : ""}${esc(costRowName(r))}${r.state === "open" ? ` <span class="cost-open">assumed</span>` : ""}<span class="lsplit-line">${splitWho(r)}</span></td>
      <td class="lstatus"><span class="hub-dot" style="--dot-color: var(${logiPipVar(r.row)})">${esc(statusLabel(r.row.status || "—"))}</span></td>
      <td class="lpaid">${r.state === "committed" && (r.cash || r.ur) ? payerCell(r) : `<span class="lpaid-na" title="nothing has been paid on this line yet">—</span>`}</td>
      ${moneyCells([r], pointsCol)}</tr>`;
  }

  function listCost(head, list) {
    const t = state.trip, m = tripMoney();
    const shared = m.party > 1;
    // THE TAB IS YOURS. Every aggregate above the rows — the headline, the
    // per-category sums, the chart — is Sam's own share; the group's figures
    // live in one place, the bill card in the rail, which is the card that
    // actually splits the trip between people. It ran the other way from
    // 2026-08-25 ("any mention of your share is irrelevant, only needs to exist
    // in a personal summary in the trips bill") until those group figures turned
    // out to be unreadable side by side: a seven-way house against one seat.
    // Sam, 2026-08-26: "the number at the top above the three bars should be
    // your share total, not the whole trip total. The whole trip total can exist
    // in the trip bill … everything else is for you."
    // The ROWS keep the line's real price — what the stay cost is a fact about
    // the booking, not an aggregate — and the share column beside it is his.
    setHTML(head, `
      <div class="hub-figure">
        <div class="hub-figure-fig">
          <span class="hub-figure-n">${U.priceHtml(m.committed)}</span>
          <span class="hub-figure-l">your share${shared ? ` · ${m.party} ways` : ""}</span>
        </div>
        <div class="hub-figure-delta is-floor" title="your share of everything committed, plus your share of the cheapest still-open option in each undecided category">${U.priceHtml(m.projected)} projected</div>
      </div>`);

    const body = COST_CATS.map((cat) => {
      const rows = (m.rows || []).filter((r) => r.table === cat.key);
      const mine = (m.byCategory || []).filter((c) => c.key === cat.key)[0];
      const grp = (m.group?.byCategory || []).filter((c) => c.key === cat.key)[0];
      const isShared = mine?.shared && shared;
      // A category can sit under the line's own price without being a SHARED
      // table: a seat he bought for another traveller is in the flights column
      // at full price and in his share at nothing. Say so, or the number reads
      // as a missing row.
      const trimmed = mine && grp && differs(mine.total, grp.total);
      const sum = !rows.length ? "nothing counted"
        : U.priceHtml(mine.total)
          + (isShared ? ` · your share, ${m.party} ways` : trimmed ? " · your share" : "")
          + (mine.open.cash || mine.open.ur ? ` · ${U.priceHtml(mine.open)} of it still open` : "");
      const headHTML = `<div class="hub-section-head lgroup-head lgroup-sub">
        <span class="hub-section-head-t lgroup-l">${esc(cat.label)}</span>
        <span class="hub-section-head-sum lgroup-sum">${sum}</span></div>`;
      const out = costLeftOut(t, cat.key, rows.length);
      const note = out ? `<div class="cost-out">not counted — ${esc(out)}</div>` : "";
      if (!rows.length) return `${headHTML}<div class="hub-section-empty">nothing on this trip yet</div>${note}`;
      // `fronted by` earns a column of its own rather than a second chip in the
      // price cell: two unlabelled pills side by side, one reading "who paid?"
      // and the next reading a name, is a cell you have to decode. Under a
      // header the question answers itself.
      // POINTS, IF RELEVANT. The column used to be drawn for every category
      // that COULD hold points, which meant a dash down the whole flights block
      // on a trip paid for in cash. Now it appears when points were actually
      // spent somewhere in the category, and not otherwise. Sam, 2026-08-26:
      // "points, if relevant." A guest never sees it at all — the model has
      // already folded their points into cash by the time a row reaches here.
      // Per card, not per tab: forcing the column onto every card was tried and
      // undone (mark 2026-10-14, "undo").
      const pointsCol = !TC.isGuest() && rows.some((r) => r.ur);
      return `${headHTML}<table class="hub-table ltable ltable-cost${pointsCol ? " is-priced" : ""}"><thead><tr>
          <th>line</th><th class="lstatus-h">status</th><th class="lpaid-h">fronted by</th>
          <th class="hub-num lmoney-h">cash</th>${pointsCol ? `<th class="hub-num lmoney-h">points</th>` : ""}
          <th class="hub-num lshare-h" title="one person's share of this line">share</th></tr></thead><tbody>${
        costBodyHTML(t, cat.key, rows, pointsCol)}</tbody></table>${note}`;
    }).join("");

    setHTML(list, `<div class="cost-chart-full hub-t3p-card hub-plate-card">${costChart(m)}</div>${body}`);
    // A ticket opens and shuts in place. The state lives outside the render, so
    // an edit does not slam every other ticket closed.
    list.querySelectorAll("[data-costgrp]").forEach((tr) => {
      tr.onclick = () => {
        const k = tr.dataset.costgrp;
        const open = costGroupOpen[k] = !costGroupOpen[k];
        tr.classList.toggle("is-open", open);
        tr.querySelector(".cost-grp-c").textContent = open ? "▾" : "▸";
        list.querySelectorAll(`[data-costleg="${CSS.escape(k)}"]`)
            .forEach((x) => { x.classList.toggle("is-shown", open); });
      };
    });
    // ONE click, ONE form. Every cost-side field on the line — price, points,
    // rate, who fronted it, who it divides between — is behind this, and the
    // row carries no controls of its own any more.
    // Not on the shared mirror: the public app serves no PATCH route, so a guest
    // clicking a line got an editor that could only fail on save.
    if (!TC.isGuest()) list.querySelectorAll("[data-editrow]").forEach((tr) => {
      tr.onclick = () => {
        const cut = tr.dataset.editrow.indexOf(":");
        const kind = tr.dataset.editrow.slice(0, cut), id = tr.dataset.editrow.slice(cut + 1);
        const row = (t[kind] || []).find((x) => String(x.id) === id);
        if (row) editCostRow(kind, row);
      };
    });
  }

  function listActivities(head, list) {
    const acts = state.trip.activities || [];
    const count = (s) => acts.filter((a) => a.status === s).length;
    // distance needs a stay to measure from; without one the option isn't offered,
    // so a sort left over from a trip that had one would point at nothing
    if (state.sort === "dist" && !housingAnchor()) state.sort = "score-desc";
    setHTML(head, `
      <div class="funnel-totals">
        ${totBtn("considering", count("considering"))}
        ${totBtn("deciding", count("deciding"))}
        ${totBtn("scheduled", count("scheduled"))}
      </div>
      <div class="pip-legend" title="status legend">${PIP_STATUSES.map((s) => `<span class="hub-dot" style="--dot-color: var(${pipVar(s)})">${esc(statusLabel(s))}</span>`).join("")}</div>
      <div class="funnel-tools">
        <div class="funnel-search"><span aria-hidden="true">🔍</span><input id="fsearch" aria-label="search activities" placeholder="search activities" value="${esc(state.search)}"></div>
        <select class="funnel-sort" id="fsort" aria-label="sort order">
          ${sortOpt("score-desc", "score ↓")}${sortOpt("score-asc", "score ↑")}
          ${sortOpt("az", "a→z")}${housingAnchor() ? sortOpt("dist", "distance") : ""}${sortOpt("cost", "price")}
        </select>
        <button class="funnel-add is-primary" id="fadd">+ add</button>
      </div>
      <div class="funnel-tools" id="actPins">
        ${pinBtn("all", "all pins")}${pinBtn("scheduled", "scheduled pins")}
      </div>
      <div class="funnel-tools" id="actGeo"></div>`);
    // search/sort repaint only the rows — keeps the input focused while typing
    $("fsearch").oninput = (e) => { state.search = e.target.value; paintActivityRows(list); };
    $("fsort").value = state.sort;
    $("fsort").onchange = (e) => { state.sort = e.target.value; paintActivityRows(list); };
    $("fadd").onclick = addActivity;
    document.querySelectorAll(".fpin").forEach((b) => {
      const pick = () => {
        state.pinFilter = b.dataset.p;
        listActivities($("focusHead"), $("focusList"));  // full re-render to flip the active chip
      };
      b.onclick = pick;
      b.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } };
    });
    // :not(.fpin) — the pin chips borrow .ftot for its styling, not its behaviour
    document.querySelectorAll(".ftot:not(.fpin)").forEach((b) => {
      const toggle = () => {
        state.statusFilter = state.statusFilter === b.dataset.s ? null : b.dataset.s;
        listActivities($("focusHead"), $("focusList"));  // full re-render to flip the active total
      };
      b.onclick = toggle;
      b.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } };
    });
    paintActivityRows(list);
  }
  // The bucket is the first capitalized tag. "Time Sensitive" is a flag that
  // co-occurs with a real bucket, so it never becomes a section of its own.
  function actBucket(a) {
    return parseTags(a.tags).find((t) => /^[A-Z]/.test(t) && t !== "Time Sensitive") || "Other";
  }
  const collapsedBuckets = new Set();
  function paintActivityRows(list) {
    const acts = state.trip.activities || [];
    let rows = acts.slice();
    if (state.statusFilter) rows = rows.filter((a) => a.status === state.statusFilter);
    else rows = rows.filter((a) => a.status !== "skip");
    const q = state.search.trim().toLowerCase();
    if (q) rows = rows.filter((a) => (`${a.name} ${a.location || ""} ${a.tags || ""}`).toLowerCase().includes(q));
    rows.sort(sorter(state.sort));
    // The map lives here rather than in listActivities because it has to follow
    // the search, the sort and the status filter — the whole point is that
    // narrowing the list narrows what's on the map. Selecting a row calls this
    // too, and the key guard is what stops that from resetting pan and zoom.
    paintActivityMap(rows);
    if (!rows.length) { setHTML(list, `<div class="hub-empty-state empty">nothing here</div>`); return; }
    // A trip nobody has scored renders `num1()`'s em dash on every row — a column
    // of thirty dashes in a 19px display face, carrying nothing. The column is
    // hidden until at least one activity in view actually has a score; the CSS
    // reads this flag (see .frow-score in trips.css).
    list.toggleAttribute("data-no-scores", !rows.some((a) => a.score != null && a.score !== ""));
    // Fifty-plus rows in one flat list is unreadable — Sam said so. They arrive
    // grouped by the category already sitting in their tags, in the order the active
    // sort put them, so the best-scoring bucket still leads. <details> does the
    // collapsing; the rows stay .frow descendants of `list`, so bindRows/bindDeletes
    // find them either way.
    const groups = new Map();
    rows.forEach((a) => {
      const b = actBucket(a);
      if (!groups.has(b)) groups.set(b, []);
      groups.get(b).push(a);
    });
    setHTML(list, [...groups].map(([b, rs]) => `<details class="hub-collapsible-group fgrp hub-t3p-card hub-plate-card"${collapsedBuckets.has(b) ? "" : " open"} data-b="${esc(b)}">
      <summary class="hub-section-head lgroup-head lgroup-sub"><span class="hub-section-head-t lgroup-l">${esc(b)}</span><span class="hub-section-head-sum lgroup-sum">${rs.length} option${rs.length === 1 ? "" : "s"}</span></summary>
      ${rs.map(activityRow).join("")}</details>`).join(""));
    // remembered across repaints — selecting a row shouldn't reopen what you closed
    list.querySelectorAll(".fgrp").forEach((d) => {
      d.ontoggle = () => { if (d.open) collapsedBuckets.delete(d.dataset.b); else collapsedBuckets.add(d.dataset.b); };
    });
    bindRows(list, (id) => { state.selId = Number(id); paintActivityRows(list); renderContext(); });
    bindDeletes(list);
  }
  // Numbered in the list's own order, so pin 3 is the third row you're reading.
  function paintActivityMap(rows) {
    const shown = state.pinFilter === "scheduled" ? rows.filter((a) => a.status === "scheduled") : rows;
    const stops = shown.map((a) => ({
      sel: String(a.id), kind: "act", timed: true,
      title: a.name,
      time: [statusLabel(a.status), a.score == null ? "" : `${a.score} pts`].filter(Boolean).join(" · "),
      lat: a.lat == null ? null : a.lat, lng: a.lng == null ? null : a.lng,
    }));
    // counted over the whole list, not the pin filter — narrowing the map shouldn't
    // make the "these have no coordinates" nudge disappear
    const missing = rows.filter((a) => a.lat == null).length;
    const bar = $("actGeo");
    if (bar) setHTML(bar, missing
      ? `<span class="ftot-l">${missing} of ${rows.length} not on the map yet</span><button class="funnel-add" id="ageo">geocode locations</button>`
      : "");
    const geo = $("ageo");
    if (geo) geo.onclick = geocodeTrip;
    const mapKey = `acts|${state.pinFilter}|${stops.map((s) => `${s.sel}@${s.lat},${s.lng}`).join(";")}`;
    if (mapKey === U.mut.dayMapKey) return;
    U.mut.dayMapKey = mapKey;
    setHTML($("dayMapHost"), `<div class="dayv-map" id="dayMap"><div class="dayv-map-note">loading map…</div></div>`);
    renderDayMap(stops, { route: false, ghosts: false, emptyNote: state.pinFilter === "scheduled"
      ? "nothing scheduled has a location yet — switch to all pins"
      : "nothing in this list has a location yet — geocode to put them on the map" });
  }
  // Pins only — the status totals above already filter list and map together, so
  // this control's whole reason to exist is narrowing the map while the list stays whole.
  function pinBtn(p, label) {
    const on = state.pinFilter === p;
    return `<div class="ftot fpin${on ? " active" : ""}" data-p="${p}" role="button" tabindex="0" aria-pressed="${on}"><span class="ftot-l">${label}</span></div>`;
  }
  function totBtn(s, n) {
    const on = state.statusFilter === s;
    // A count of zero was rendering at the same size and weight as the biggest
    // bucket, so an empty queue read as loudly as twenty-seven live options. It
    // stays clickable and stays legible; it just stops competing.
    return `<div class="ftot${on ? " active" : ""}${n ? "" : " is-zero"}" data-s="${s}" role="button" tabindex="0" aria-pressed="${on}"><span class="ftot-n">${n}</span><span class="ftot-l">${statusLabel(s)}</span></div>`;
  }
  function sortOpt(v, label) { return `<option value="${v}">${label}</option>`; }
  function sorter(mode) {
    const sc = (a) => (a.score == null ? -1 : a.score);
    if (mode === "score-asc") return (a, b) => sc(a) - sc(b);
    if (mode === "az") return (a, b) => (a.name || "").localeCompare(b.name || "");
    if (mode === "cost") return (a, b) => (a.cost || 0) - (b.cost || 0);
    if (mode === "dist") return (a, b) => (distFromStay(a) ?? 1e9) - (distFromStay(b) ?? 1e9);
    return (a, b) => sc(b) - sc(a);
  }
  function activityRow(a) {
    const sel = a.id === state.selId ? " selected" : "";
    const d = distFromStay(a);
    const sub = [a.location ? esc(a.location.split(",")[0]) : "", d != null ? `${d.toFixed(1)}\u00a0mi` : ""].filter(Boolean).join(" · ");
    // data-status is a styling hook, not a second source of truth: three scheduled
    // rows out of thirty were separated from the rest by an 8px dot alone, and a
    // skipped row sat at full weight next to options still live. Both now take the
    // weight the logistics board already gives a booked / ruled-out row.
    return `<div class="hub-row frow hub-stagger-item${sel}" data-id="${a.id}" data-status="${esc(a.status || "")}">
      <div class="hub-row-meat"><span class="hub-row-title frow-title">${esc(a.name)}</span><span class="hub-row-sub frow-sub">${sub}</span></div>
      <div class="hub-row-right frow-right"><span class="frow-score">${num1(a.score)}</span><span class="hub-dot frow-pip" style="--dot-color: var(${pipVar(a.status)})">${esc(statusLabel(a.status))}</span>${delBtn(`activities/${a.id}`, a.name)}</div>
    </div>`;
  }
  function bindRows(list, cb, sel) {
    list.querySelectorAll(sel || ".frow").forEach((r) => {
      r.setAttribute("role", "button");
      r.tabIndex = 0;
      r.onclick = () => cb(r.dataset.id);
      r.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); cb(r.dataset.id); } };
    });
  }

  // ── ITINERARY — proportional day timeline ────────────────────────────────
  // One column per trip day, a literal 00:00–24:00 axis, blocks positioned and
  // sized by real time. What the flat schedule list couldn't show: duration,
  // gaps, and back-to-back crunches.
  function listItinerary(head, list) {
    const days = tripDays();
    if (!days.length) {
      setHTML(head, `<div class="funnel-tools"><span class="ftot-l">set trip dates to build an itinerary</span></div>`);
      setHTML(list, `<div class="hub-empty-state empty">set trip dates to build an itinerary</div>`);
      return;
    }
    if (state.day !== "cal" && days.indexOf(state.day) >= 0) return listDay(head, list, days, state.day);
    listCalendar(head, list, days);
  }

  function listCalendar(head, list, days) {
    const model = itineraryModel(days);
    const placed = model.reduce((n, d) => n + d.blocks.length, 0);
    const loose = model.reduce((n, d) => n + d.tray.length, 0);
    setHTML(head, `<div class="funnel-tools">
      <span class="ftot-l">${days.length} days · ${placed} placed${loose ? ` · ${loose} untimed` : ""}</span>
      <button class="funnel-add is-primary" id="iadd">+ add</button>
    </div>`);
    $("iadd").onclick = addActivity;
    setHTML(list, timelineHTML(model));

    const body = list.querySelector(".hub-timeline-body");
    // Open on the first thing that happens. The axis runs midnight to midnight, so
    // earliest position IS the earliest event, so no special-casing needed.
    if (body && model.some((d) => d.blocks.length)) {
      const first = model.reduce((m, d) => d.blocks.reduce((n, b) => Math.min(n, b.pos), m), 1440);
      body.scrollTop = Math.max(0, (first / 1440) * body.scrollHeight - 56);
    }
    bindSel(list);
  }

  // Timeline blocks, tray chips and map pins all carry data-sel — a bare number
  // is an activity, "kind:id" a logistics row. One binder for every surface.
  function bindSel(root) {
    root.querySelectorAll("[data-sel]").forEach((el) => {
      const raw = el.dataset.sel;
      // The shopping run has no row to focus — it is derived. Clicking it opens the
      // list it is a picture of, which is the only thing there is to do with it.
      const select = () => {
        if (raw === "grocery") {
          const tab = document.querySelector('.fnav[data-mode="grocery"]');
          if (tab) tab.click();   // the nav button owns the whole switch — saveNav, re-render, pane
          return;
        }
        state.selId = /^\d+$/.test(raw) ? Number(raw) : raw; renderFocus(); renderContext();
      };
      el.setAttribute("role", "button");
      el.tabIndex = 0;
      el.onclick = select;
      el.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(); } };
    });
  }

  // ── ONE DAY — summary, routed map, full-width timeline ───────────────────
  // The day is the unit you plan in, so it gets the whole pane: what the day
  // costs and how packed it is up top, where it physically goes in the middle,
  // and when each piece happens underneath. The map is the part the old
  // itinerary had no answer for — a list of stops never shows that two of them
  // are forty minutes apart in opposite directions.
  function listDay(head, list, days, day) {
    const model = itineraryModel(days);
    const i = days.indexOf(day);
    const d = model[i];
    const s = daySummary(d);
    const stops = dayStops(d);
    const missing = stops.filter((x) => x.lat == null).length;

    setHTML(head, `<div class="funnel-tools">
      <span class="dsum-day">${esc(dayLabel(day))}<i>day ${i + 1} of ${days.length}</i></span>
      <div class="dsum">
        ${dstat(s.items, "items")}
        ${dstat(s.booked != null ? `${s.booked.toFixed(1)}h` : "—", "booked")}
        ${dstat(s.span || "—", "first → last")}
      </div>
      <button class="funnel-add is-primary" id="iadd">+ add</button>
    </div>${missing ? `<div class="funnel-tools hub-text-act dmiss"><span>${missing} stop${missing > 1 ? "s" : ""} not on the map yet</span><button class="funnel-add" id="igeo">geocode locations</button></div>` : ""}`);
    $("iadd").onclick = addActivity;
    if (missing) $("igeo").onclick = geocodeTrip;

    // the map moved to the top of the right column (over the item detail), so
    // the left column is the day itself — nothing but the timeline.
    // Rebuilt only when the day or its pins actually change: selecting a block
    // re-renders this whole view, and tearing the map down each time threw away
    // whatever you'd panned or zoomed to.
    // First day starts at the airport, last day ends there; every day between
    // both leaves from and returns to the stay.
    const anc = housingAnchor();
    const bookend = { start: i > 0 ? anc : null, end: i < days.length - 1 ? anc : null };
    const mapKey = day + "|" + stops.map((s) => `${s.sel}@${s.lat},${s.lng}`).join(";")
      + "|" + (anc ? `${anc.lat},${anc.lng}` : "");
    const remap = mapKey !== U.mut.dayMapKey;
    if (remap) {
      U.mut.dayMapKey = mapKey;
      setHTML($("dayMapHost"), `<div class="dayv-map" id="dayMap"><div class="dayv-map-note">loading map…</div></div>`);
    }
    setHTML(list, `<div class="dayv"><div class="dayv-tl">${timelineHTML([d])}</div></div>`);
    bindSel(list);
    // open on the first thing that happens, not on the overnight dead air —
    // measured off the block's own box rather than computed from the axis,
    // because the tray row between the two drifts with its content
    const blk = list.querySelector(".dayv-tl .hub-timeline-block");   // blocks render in time order
    if (blk) list.scrollTop += blk.getBoundingClientRect().top - list.getBoundingClientRect().top - 20;
    if (remap) renderDayMap(stops, { bookend });
  }

  function dstat(v, l) { return `<div class="dstat hub-stat"><span class="dstat-v hub-stat-v">${esc(String(v))}</span><span class="dstat-l">${esc(l)}</span></div>`; }

  function daySummary(d) {
    const timed = d.blocks.filter((b) => b.start != null);
    const mins = d.blocks.reduce((n, b) => n + (b.end != null && b.end !== b.start ? (b.end - b.start + 1440) % 1440 : 0), 0);
    const first = timed.length ? timed[0] : null;
    const last = timed.length ? timed[timed.length - 1] : null;
    return {
      items: d.blocks.length + d.tray.length,
      booked: mins ? mins / 60 : null,
      span: first ? `${T.fmtClock(first.start)} → ${T.fmtClock(last.end != null ? last.end : last.start)}` : "",
    };
  }

  // The day's stops, with coordinates where we have them. Every kind on the
  // timeline can be somewhere: an activity and a stay carry their own lat/lng, a
  // car leg geocodes its pickup address, and a flight resolves to an airport
  // through the trip's IATA lookup. Untimed items come along too — they were the
  // reason a day whose only entry was an all-day hike drew an empty map.
  function dayStops(d) {
    const acts = state.trip.activities || [], hous = state.trip.housing || [];
    const tran = state.trip.transportation || [];
    const coords = (b) => {
      if (b.kind === "act") return acts.find((a) => String(a.id) === b.sel);
      if (b.kind === "stay") return hous.find((h) => `housing:${h.id}` === b.sel);
      if (b.kind === "move") return tran.find((x) => `transportation:${x.id}` === b.sel);
      return null;
    };
    const one = (b, timed) => {
      const src = coords(b) || {};
      return {
        sel: b.sel, kind: b.kind, title: b.title, timed,
        time: timed ? T.fmtClock(b.start) : "anytime",
        lat: src.lat == null ? null : src.lat, lng: src.lng == null ? null : src.lng,
      };
    };
    const many = (b, timed) => (b.kind === "flight" ? flightStops(b, timed) : [one(b, timed)]);
    const mine = new Set(myFlights(state.trip).map((f) => `flights:${f.id}`));
    // A connection is one airport, not two: leg 1 lands at IAD and leg 2 leaves
    // from it, and drawing both put a second numbered pin on top of the first.
    const stops = markTrail(dropRepeatAirport(
      d.blocks.flatMap((b) => many(b, true)).concat(d.tray.flatMap((b) => many(b, false)))), mine);
    // The stay belongs on every day's map, not only the two days it appears on
    // the timeline. You sleep there — it is the fixed point the day leaves from
    // and comes back to, and a day-3 map with no house on it hid the one
    // location every other pin is measured against. Unnumbered: home is where
    // the sequence starts, not a stop within it.
    const stay = chosenStay();
    if (stay && stay.lat != null && stay.lng != null && !stops.some((s) => s.sel === `housing:${stay.id}`)) {
      stops.push({
        sel: `housing:${stay.id}`, kind: "stay", title: stay.name || stay.address || "stay",
        timed: false, trail: false, time: "home base", lat: stay.lat, lng: stay.lng,
      });
    }
    return stops;
  }

  // The line the day actually travels. Every day leaves from the Airbnb and
  // returns to it — except the first, which begins at the airport, and the last,
  // which ends there. Those two home legs are real driving and the route was
  // dropping them silently, so a day out at Red Rocks drew as a single point.
  // Day 1 already ends on the stay (check-in) and the last day already starts
  // there (check-out), so adjacent duplicates collapse rather than drawing a
  // zero-length leg back to the house you are standing in.
  function trailPath(pts, bookend) {
    const b = bookend || {};
    // [lat, lng, air, back] — leaflet reads a third element as altitude and
    // ignores anything past it, so both flags ride along to drawRoute without a
    // parallel array.
    const at = (h) => [[h.lat, h.lng, false, false]];
    const all = (b.start ? at(b.start) : []).concat(pts, b.end ? at(b.end) : []);
    return all.filter((p, i) => !i || p[0] !== all[i - 1][0] || p[1] !== all[i - 1][1]);
  }

  // Which stops are the day's actual trail. A crew member's flight is a fact
  // about the day, not a place you go — numbering it dragged the route out to
  // the airport for somebody else's landing and back again, twice on a day two
  // people fly in. So ownership is the whole test: your own legs are your
  // movement, every one of them, and a crew leg floats unnumbered and off the
  // route the same way an untimed item does. It used to keep only your FIRST
  // leg of the day, which on a connecting itinerary dropped the second half of
  // the journey and drew the trail from the connection airport to the stay.
  // When a crew arrival genuinely IS part of your day it exists as its own stop
  // — "pick up Akshay" — and that anchors like any other activity, which is why
  // nothing here special-cases it.
  // Stops arrive in time order (blocks sorted by pos, then the untimed tray).
  function markTrail(stops, mine) {
    return stops.map((s) => Object.assign({}, s, { trail: s.kind === "flight" ? s.timed && mine.has(s.sel) : s.timed }));
  }

  // A flight is a movement, not a place, so BOTH its ends go on the map in the
  // order you pass through them. Pinning one end used to hide where the day
  // started — EWR was simply absent from Columbus day 1 — and on a connecting
  // itinerary it pinned the connection (IAD) as though that were the arrival,
  // which drew the trail straight from Dulles to the Columbus stay without ever
  // touching CMH. The arrival end carries `air`: the leg INTO it was flown.
  function dropRepeatAirport(stops) {
    return stops.filter((s, i) => {
      const prev = stops[i - 1];
      return !(i && s.kind === "flight" && prev.kind === "flight" &&
        s.lat === prev.lat && s.lng === prev.lng && s.sel !== prev.sel);
    });
  }

  function flightStops(b, timed) {
    const f = (state.trip.flights || []).find((x) => `flights:${x.id}` === b.sel);
    if (!f) return [];
    const A = state.trip.airports || {};
    return [[f.from_airport, b.start, false], [f.to_airport, b.end != null ? b.end : b.start, true]]
      .map(([raw, clock, air]) => {
        const code = (raw || "").trim().toUpperCase();
        if (!code) return null;
        const a = A[code];
        return {
          sel: b.sel, kind: "flight", title: `${code} · ${b.title}`, timed, air, back: !!b.back,
          time: timed && clock != null ? T.fmtClock(clock) : "anytime",
          lat: a ? a.lat : null, lng: a ? a.lng : null,
        };
      }).filter(Boolean);
  }

  // Everything still on the shortlist, drawn faint. The point is proximity: a
  // "considering" taco place two blocks off the day's path is a decision you can
  // only make when you can see it sitting there. So it is filtered BY proximity —
  // dropping all 80 shortlisted spots on the map buries the day's own five under
  // a wall of pins and answers no question at all.
  const GHOST_MI = 1.5;      // "near the path" — a walk you'd actually make mid-day
  const GHOST_MAX = 24;      // past this the map is pins, not information
  function ghostStops(day, placed) {
    const anchors = placed.length ? placed : [housingAnchor()].filter(Boolean);
    const near = (a) => !anchors.length ||
      anchors.some((p) => (haversine(p.lat, p.lng, a.lat, a.lng) ?? 1e9) <= GHOST_MI);
    return (state.trip.activities || [])
      .filter((a) => a.lat != null && a.lng != null && a.status !== "skip" &&
        !(a.status === "scheduled" && a.scheduled_date === day))
      .filter(near)
      .sort((a, b) => (b.score == null ? -1 : b.score) - (a.score == null ? -1 : a.score))
      .slice(0, GHOST_MAX)
      .map((a) => ({ sel: String(a.id), title: a.name, lat: a.lat, lng: a.lng, status: a.status }));
  }

  function geocodeTrip() {
    status("geocoding…");
    return API.post(`/trips/${state.trip.id}/geocode`).then((r) => {
      state.trip = r.trip;
      toast(`geocoded ${r.updated}${r.failed ? ` · ${r.failed} failed` : ""}`);
      renderAll();
    }).catch((e) => { toast(`geocode failed — ${errMsg(e)}`); status("ready"); });
  }


Object.assign(U, { terminalText, routeText, costRowName, CASH_FIELD, pointsField, sumMoney, differs, listCost,
  listActivities, bindRows, listItinerary, listDay, trailPath, markTrail, dropRepeatAirport, ghostStops, geocodeTrip });
})();
