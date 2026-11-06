/* hub · trips page, crew part (2026-10-13): React port of trips.js lines 6372-7270 (the stay in pictures,
   stayPanel and its helpers, the shared board/table builders groupHTML + otherCostsHTML, the crew cards, forms
   sync and the roster picker). Plain functions inside an IIFE, same HTML strings, ids, handlers and request
   bodies as the plain page; the three async functions are promise chains. See trips-core.jsx for the contract. */
(() => {
const U = window.TripsUI;
const { esc, setHTML, toast, state, $, errMsg, T, isGuest, money, rowCost, sumCost, supersededExpense,
  isCommitted, isDead, isOpen } = U;
const API = U.api;
const { photoItems, trim1, nightsOf, daysAway, stampShort, countdown, dayShort, amenityGroups, lines, logiForm,
  gapList, stayBlock, stayFacts, wifiCell, doorCell, stayList, housingTags, stayCtx, tagsHTML, renderDayMap,
  perPersonNight, allIn, picked, fitsParty, bindRows, bindDeletes, delBtn, addExpense, logiModal, unbool,
  searchFares, editLogistics, addFields, showQR, copyText, renderFocus, renderContext, loadPrefs, reload,
  closeModal, addMember, logiTitle } = U.fwd("photoItems", "trim1", "nightsOf", "daysAway", "stampShort",
  "countdown", "dayShort", "amenityGroups", "lines", "logiForm", "gapList", "stayBlock", "stayFacts", "wifiCell",
  "doorCell", "stayList", "housingTags", "stayCtx", "tagsHTML", "renderDayMap", "perPersonNight", "allIn",
  "picked", "fitsParty", "bindRows", "bindDeletes", "delBtn", "addExpense", "logiModal", "unbool", "searchFares",
  "editLogistics", "addFields", "showQR", "copyText", "renderFocus", "renderContext", "loadPrefs", "reload",
  "closeModal", "addMember", "logiTitle");
  // ── THE STAY, IN PICTURES ───────────────────────────────────────────────────
  // Every field on this panel is a word: 4BR, 7 beds, hot tub, Arvada. Not one of
  // them says what the house looks like, which is the first thing anyone opening
  // the tab wants and the thing they were leaving for Airbnb to answer. The
  // photos are the listing's own, hotlinked off Airbnb's CDN - see migration 017
  // for why they are not copied into the vault.
  //
  // A scroll-snap strip, not a JS carousel: the browser already does momentum,
  // touch drag, snapping and keyboard scrolling, and does all four better than a
  // hand-rolled transform. The buttons only call scrollBy. Each shot is a little
  // narrower than the strip so the next one's edge shows - a carousel that looks
  // like a single photo doesn't get scrolled.
  const SPECS = [
    { k: "guests", l: "sleeps" },
    { k: "bedrooms", l: "bedrooms" },
    { k: "beds", l: "beds" },
    { k: "baths", l: "baths" },
  ];
  function stayHero(h) {
    const shots = photoItems(h.photos);
    // The spec strip stands on its own - a stay with no photos read yet still has
    // a shape, and printing it is better than printing nothing.
    const spec = SPECS.filter((f) => h[f.k] != null)
      .map((f) => `<div class="stay-sp"><span class="stay-spn">${esc(trim1(h[f.k]))}</span>
        <span class="stay-spl">${esc(f.l)}</span></div>`).join("")
      + (h.rating != null ? `<div class="stay-sp"><span class="stay-spn">${esc(h.rating)}<span class="stay-spstar">★</span></span>
        <span class="stay-spl">${h.reviews != null ? `${esc(h.reviews)} reviews` : "rating"}</span></div>` : "");
    // Only the two the crew asked for by name, and only on a 1 - a null is an
    // unread amenity list, and a chip on it would be a claim nobody checked.
    const chips = [
      h.hot_tub === 1 ? "hot tub" : "", h.pool_table === 1 ? "pool table" : "",
      /free/i.test(h.parking || "") ? "free parking" : "",
    ].filter(Boolean).map((t) => `<span class="ltag hub-pill is-good">${esc(t)}</span>`).join("");
    // What a hotel has instead of 4BR / 7 beds. A room type is a sentence rather
    // than four counts ("2 queens, 338 sq ft, Arena District view"), so it sits on
    // its own line under the strip instead of being cut into spec tiles.
    const room = String(h.room_type || "").trim();
    if (!shots.length && !spec && !room) return "";
    return `<div class="stay-hero hub-t3p-card hub-plate-card">
      ${shots.length ? `<div class="hub-carousel">
        <div class="hub-carousel-track" id="stayShots" tabindex="0" aria-label="photos of the stay">
          ${shots.map((p, i) => `<figure class="hub-carousel-slide">
            <img src="${esc(p.u)}" alt="${esc(p.c || `${h.name || "the stay"} — photo ${i + 1}`)}"
              loading="${i < 2 ? "eager" : "lazy"}" decoding="async" draggable="false">
            ${p.c ? `<figcaption>${esc(p.c)}</figcaption>` : ""}
          </figure>`).join("")}
        </div>
        <button class="hub-carousel-nav is-prev" id="shotPrev" aria-label="previous photo">‹</button>
        <button class="hub-carousel-nav is-next" id="shotNext" aria-label="next photo">›</button>
        <div class="hub-carousel-count"><span id="shotAt">1</span> / ${shots.length}</div>
        ${h.photo_credit ? `<a class="hub-carousel-credit" href="${esc(h.photo_credit_url || "#")}"
          target="_blank" rel="noopener">photos via ${esc(h.photo_credit)}</a>` : ""}
      </div>` : ""}
      ${spec || chips || room ? `<div class="stay-spec">${spec}${room ? `<div class="stay-sproom">${esc(room)}</div>` : ""}${chips ? `<div class="stay-spchips">${chips}</div>` : ""}</div>` : ""}
    </div>`;
  }

  // How the strip throws. Native scroll already flings on a trackpad and on
  // touch, better than any hand-rolled easing - but a MOUSE can't fling at all,
  // and mandatory snap turned every gesture into a page turn. So the native
  // gestures keep the browser's own physics (proximity snap in CSS, which notches
  // only if you land near an edge), and the mouse gets a real throw: velocity off
  // the drag, friction while it coasts, and a light pull to the nearest photo
  // only at the tail end. Enough to notch, not enough to fight the throw.
  // Sam, 2026-08-26: "slight friction to notch on pages but not too much, i
  // want it to have some inertia".
  //
  // All four are per-16ms so the feel is the same on a 60Hz and a 120Hz screen -
  // the loop scales them by the real frame delta rather than assuming a frame is
  // a frame. Tune `friction` for how far a throw carries and `notch` for how hard
  // the photo edges grab; `catch` is what keeps the two out of each other's way,
  // because a notch that pulls during the fast part of a glide is a page turn
  // wearing a costume.
  //
  // Sam, 2026-08-26 (second pass): "less aggression so it's not as teleporty
  // and is more like it slowly finds its notch". `notch` halved and then some,
  // `catch` raised so the pull starts earlier and therefore spreads over a longer
  // approach instead of arriving late and hard, and `rest` dropped to match - a
  // soft notch moves less per frame, so the old 0.4px floor would have cut the
  // glide off while it was still visibly closing.
  const SPIN = {
    friction: 0.94,   // share of velocity kept per 16ms - a hard throw coasts ~1.3s
    catch: 0.6,       // px/ms: below this the nearest photo starts pulling
    notch: 0.09,      // share of the remaining gap closed per 16ms once caught
    rest: 0.15,       // px moved in a frame below which the throw has stopped
  };

  // The strip's own wiring. Shots are their own natural widths, so a step is not
  // a constant - the next shot is the next child along, and the counter is
  // whichever child's edge the scroll is nearest. Both read the DOM, so a width
  // change in CSS can't desync them.
  function bindShots() {
    const strip = $("stayShots");
    if (!strip) return;
    const at = $("shotAt"), kids = () => Array.prototype.slice.call(strip.children);
    // Where a photo sits in the strip's own scroll coordinates - the position it
    // would have at scrollLeft 0. offsetLeft is relative to the FRAME (the nearest
    // positioned ancestor, not the strip) and counts from the strip's border box,
    // so the strip's own offset and its border both come off. offsetLeft is
    // scroll-invariant (verified), so these are constants, not a moving target.
    const posIn = (el) => el.offsetLeft - strip.offsetLeft - strip.clientLeft;
    const maxX = () => Math.max(0, strip.scrollWidth - strip.clientWidth);
    // CENTRED, not flush left. A photo parked against the left edge reads as a
    // list that happens to have stopped; centred, it reads as the one you're
    // looking at, with its neighbours acknowledged either side. The scroll
    // position that centres a photo is its middle minus the frame's middle, and
    // it clamps - the first and last photos can't reach the centre, and pulling
    // toward a target past the end is what a rubber band would be.
    // No padding term: clientWidth is the padding box, and posIn measures from
    // that same origin, so the strip's 12px gutter cancels out of both sides.
    const edge = (el) =>
      Math.max(0, Math.min(maxX(), posIn(el) + el.offsetWidth / 2 - strip.clientWidth / 2));
    // Nearest is measured on CENTRES, not on targets: the end photos share a
    // clamped target with their neighbour, so comparing targets makes the counter
    // ambiguous at both ends. Comparing what's actually nearest the middle of the
    // frame is both the honest question and immune to the clamp.
    const nearestTo = (x) => {
      const k = kids(), mid = x + strip.clientWidth / 2;
      const off = (el) => Math.abs(posIn(el) + el.offsetWidth / 2 - mid);
      let best = 0;
      k.forEach((el, i) => { if (off(el) < off(k[best])) best = i; });
      return best;
    };
    const nearest = () => nearestTo(strip.scrollLeft);

    // `pos` is the glide's own position, in float px. Reading scrollLeft back each
    // frame instead looks equivalent and is not: the browser quantises it to the
    // device pixel (0.5px at 2x), so once the notch's pull drops under half a
    // pixel per frame it rounds to nothing, the gap stops closing, and the strip
    // parks a few px off the photo with the rAF loop spinning forever behind it.
    // Measured: settled 4px off its edge, snap never restored. Keep the float.
    let pos = 0, vx = 0, glide = 0, dragging = false, lastX = 0, lastT = 0, moved = 0;
    // Snap is turned off for the duration of a throw and restored at rest: a
    // mandatory or proximity snap point fights a scrollLeft written every frame,
    // and what you feel is the glide stuttering back a few pixels each time.
    const halt = () => {
      if (glide) cancelAnimationFrame(glide);
      glide = 0;
      strip.style.scrollSnapType = "";
    };

    const step = (t) => {
      const dt = Math.min(32, t - lastT) || 16;
      lastT = t;
      const was = pos;
      vx *= SPIN.friction ** (dt / 16);
      pos += vx * dt;
      const target = edge(kids()[nearestTo(pos)]);
      if (Math.abs(vx) < SPIN.catch) pos += (target - pos) * (1 - (1 - SPIN.notch) ** (dt / 16));
      // The ends stop dead rather than bouncing - a rubber-band on a strip of
      // photographs reads as a bug, not as physics.
      const cap = maxX(), wall = pos <= 0 || pos >= cap;
      if (wall) { vx = 0; pos = Math.max(0, Math.min(cap, pos)); }
      strip.scrollLeft = pos;
      // Done when nothing is MOVING any more, not when velocity is small. Those
      // are different once the notch is pulling: it cancels the last of the
      // velocity, so the strip visibly parks while `vx` keeps the loop alive for
      // another second, creeping the final pixels. Measured before this: 86% of
      // the throw covered in 400ms, then 10px over the next 1.3 seconds.
      // Below `rest` the notch can only be within ~3px of its target anyway
      // (gap × notch < rest), so the close is exact and imperceptible.
      if (Math.abs(pos - was) < SPIN.rest) {
        if (!wall) strip.scrollLeft = pos = target;
        return halt();
      }
      glide = requestAnimationFrame(step);
    };

    const go = (d) => {
      const k = kids(), i = Math.max(0, Math.min(k.length - 1, nearest() + d));
      halt();
      strip.scrollTo({ left: edge(k[i]), behavior: "smooth" });
    };
    $("shotPrev").onclick = () => go(-1);
    $("shotNext").onclick = () => go(1);

    // Mouse only. Touch and trackpad already have the browser's own momentum, and
    // taking those over means reimplementing - worse - something that already
    // works, on the two inputs where it works best.
    strip.onpointerdown = (e) => {
      if (e.pointerType !== "mouse" || e.button !== 0) return;
      halt();
      dragging = true; moved = 0; vx = 0;
      pos = strip.scrollLeft;
      lastX = e.clientX; lastT = e.timeStamp;
      strip.style.scrollSnapType = "none";
      strip.setPointerCapture(e.pointerId);
      strip.classList.add("is-drag");
    };
    strip.onpointermove = (e) => {
      if (!dragging) return;
      const dx = e.clientX - lastX, dt = Math.max(1, e.timeStamp - lastT);
      pos = Math.max(0, Math.min(maxX(), pos - dx));
      strip.scrollLeft = pos;
      moved += Math.abs(dx);
      // Smoothed, because one stray sample at the moment you let go decides the
      // whole throw otherwise - a flick that ends on a 1px frame reads as a stop.
      vx = vx * 0.7 + (-dx / dt) * 0.3;
      lastX = e.clientX; lastT = e.timeStamp;
    };
    const release = (e) => {
      if (!dragging) return;
      dragging = false;
      strip.classList.remove("is-drag");
      try { strip.releasePointerCapture(e.pointerId); } catch { /* already gone */ }
      // A click is not a throw. Without this, pressing on a photo starts a glide
      // with no velocity, the notch takes over on frame one, and the strip lurches
      // to the nearest edge because you clicked it.
      if (moved <= 4) return halt();
      lastT = performance.now();
      pos = strip.scrollLeft;
      glide = requestAnimationFrame(step);
    };
    strip.onpointerup = release;
    strip.onpointercancel = release;
    // A wheel or trackpad scroll mid-glide is the user overriding the throw; the
    // loop would otherwise keep writing its own position over theirs.
    strip.onwheel = halt;
    // A drag that travelled is a drag, not a click on whatever it ended over.
    strip.onclick = (e) => { if (moved > 4) { e.preventDefault(); e.stopPropagation(); } };

    const sync = () => {
      if (at) at.textContent = nearest() + 1;
      strip.classList.toggle("at-start", strip.scrollLeft < 4);
      strip.classList.toggle("at-end", strip.scrollLeft + strip.clientWidth >= strip.scrollWidth - 4);
    };
    strip.onscroll = sync;
    // Run once now and again as the photos land. At bind time the images have no
    // dimensions yet, so scrollWidth is one screen wide and the strip reads as
    // scrolled to the end - which hid the next arrow on a 34-photo carousel that
    // had never been scrolled. Capture phase: `load` doesn't bubble, so one
    // listener on the strip catches all thirty-four.
    strip.addEventListener("load", sync, true);
    sync();
  }

  function stayPanel(head, list, t, h, rows) {
    const nights = nightsOf(h);
    const inD = daysAway(h.check_in), cancelD = daysAway(h.cancellation_deadline);
    const when = [
      h.check_in ? `in ${stampShort(h.check_in)}` : "",
      h.check_out ? `out ${stampShort(h.check_out)}` : "",
      nights ? `${nights} night${nights === 1 ? "" : "s"}` : "",
      countdown(inD),
    ].filter(Boolean).join(" · ");

    // The headline on a booked stay is the day you check in, not what it cost -
    // same rule as the booked fare board. The room stopped being a decision the
    // moment it was paid for, in dollars or in points, so the figure moves to the
    // cost tab and this panel goes back to answering "when".
    const stayFig = esc(dayShort(T.parseStamp(h.check_in, t.start_date)?.date) || "—");
    // The night count is already in the `when` line right below; "booked" is the
    // half of the flight board's "departure · booked one way" that still applies.
    const stayFigL = "check-in · booked";
    setHTML(head, `
      <div class="hub-figure">
        <div class="hub-figure-fig">
          <span class="hub-figure-n">${stayFig}</span>
          <span class="hub-figure-l">${stayFigL}</span>
        </div>
        <div class="stay-when">${esc(when)}</div>
      </div>`);
    // staySplit's booked form (4BR / 7 beds / 2 baths · Arvada · 4.99★) is what
    // the hero's spec strip draws now, in bigger type and beside the photos it
    // belongs to. Printing it here as well was the same line twice.

    const groups = amenityGroups(h);
    const nAms = groups.reduce((n, g) => n + g.items.length, 0);
    const nRules = lines(h.house_rules).length;
    const mapsHref = h.address ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(h.address)}` : "";
    // A stay is one of two things and the halves barely overlap. The EDIT FORM
    // has known that since migration 014; this panel did not, so the Hyatt was
    // asked for a door code it does not have, given house rules instead of the
    // fine print, and never asked what room was booked or what the desk holds on
    // the card. Same one-line test logiForm() makes, so form and panel cannot
    // disagree about which kind of stay a row is.
    const rental = logiForm("housing", h) === "rental";
    // The amenity grid is the one block both halves draw identically, so it is
    // written once. Its filter wiring below is keyed on ids inside it and works
    // the same in either branch.
    const amGrid = nAms ? `<div class="funnel-search stay-find">
            <input id="amFilter" type="search" placeholder="is there a…" aria-label="search the amenities">
            <span class="hub-section-head-sum lgroup-sum" id="amCount">${nAms} listed</span>
          </div>
          <div class="hub-col-groups">${groups.map((g) => `<div class="hub-col-group">
            ${g.k ? `<div class="hub-col-group-k">${esc(g.k)}</div>` : ""}
            <ul class="hub-col-list">${g.items.map((a) => `<li class="stay-am" data-am="${
              esc((`${a.l} ${a.d}`).toLowerCase())}">${esc(a.l)}${
              // the sub-detail is shown, not hidden behind a hover - "Essentials"
              // alone doesn't tell you the towels are provided, and there is no
              // hover on the phone this actually gets read on
              a.d ? `<span class="hub-col-list-sub">${esc(a.d)}</span>` : ""}</li>`).join("")}</ul>
          </div>`).join("")}</div>`
          : `<div class="hub-pending">the listing's amenity list hasn't been read into this row yet — nothing here means unread, not absent</div>`;
    const amSum = nAms ? `${nAms} things, in ${groups.length} group${groups.length === 1 ? "" : "s"}` : "";
    // Both halves need a way back to the form: taking the comparison table away
    // took away the row you clicked to reach it, and on a hotel the front desk
    // number and the loyalty number are only ever filled in from here.
    // The suppression rule, done here rather than inside gapList or stayBlock: a
    // section builds its real body FIRST and gets its prompts only if that body
    // came back with something in it. So a hotel with no fees on top hands
    // stayBlock an empty body and stayBlock's existing truthy-body rule drops the
    // heading, unchanged. A heading over three things the stay does not have is
    // the exact "reads as broken" outcome this is built to avoid.
    const withGaps = (body, keys) => body ? body + gapList("housing", h, keys) : "";
    const stayActs = `${h.url ? `<a class="hub-section-head-act lgroup-act" href="${esc(h.url)}" target="_blank" rel="noopener">listing ↗</a>` : ""}<button class="hub-section-head-act lgroup-act" data-editrow="housing:${esc(h.id)}">edit the stay</button>`;

    setHTML(list, `<div class="stay hub-t3p-stack">
      ${stayHero(h)}
      ${rental ? `
      ${stayBlock("getting in", h.area || "", withGaps(stayFacts([
        ["address", mapsHref ? `<span class="hub-text-act"><span>${esc(h.address)}</span><a class="hub-link-chip llink" href="${esc(mapsHref)}" target="_blank" rel="noopener">map ↗</a></span>` : esc(h.address || ""), 1],
        // The in and out stamps are drawn by the same stampShort() calls as the
        // `when` line at the top of this panel, so as rows here they were the
        // same two clocks printed a second time four inches lower. The line above
        // keeps them; this block goes back to being only how you get through the
        // door once you are there.
        // Getting in is a checklist, not a paragraph: a code, and what you do to
        // the lock on the way out. It is read one-handed at a door, so it renders
        // one fact per line like the house rules do, rather than as the run-on
        // sentence a single escaped string collapses into.
        ["the door", doorCell(h), 1],
        ["wifi", wifiCell(h, inD, isGuest()), 1],
        ["host", esc(h.host || "")],
        ["confirmation", esc(h.confirmation_code || "")],
        ["parking", esc(h.parking || "")],
      ]), ["check_in_method", "parking"]), stayActs)}

      ${stayBlock("what's in the house", amSum, withGaps(amGrid, ["amenities", "photos"]))}

      ${stayBlock("the house rules", nRules ? `${nRules} rules` : "", stayList(h.house_rules, "hub-col-list--two"))}
      ${stayBlock("before you leave", h.check_out ? `out by ${stampShort(h.check_out)}` : "", withGaps(stayList(h.checkout_tasks, "hub-col-list--steps"), ["checkout_tasks"]))}
      ` : `
      ${/* A hotel's own vocabulary. Nothing here is a relabelled house rule: you
            check in at a desk rather than at a keypad, the charges that are not in
            the nightly rate are their own question, and "the fine print" is the
            state tax and the change policy rather than quiet hours. */""}
      ${stayBlock("checking in", h.area || "", withGaps(stayFacts([
        ["address", mapsHref ? `<span class="hub-text-act"><span>${esc(h.address)}</span><a class="hub-link-chip llink" href="${esc(mapsHref)}" target="_blank" rel="noopener">map ↗</a></span>` : esc(h.address || ""), 1],
        // doorCell lifts a keypad code out of the prose in display type, which is
        // the right answer at a lock in the dark and the wrong one at a staffed
        // desk. A hotel's check-in method prints as the sentence it was typed as.
        ["checking in", lines(h.check_in_method).map(esc).join("<br>"), 1],
        ["wifi", wifiCell(h, inD, isGuest()), 1],
        ["front desk", esc(h.host || "")],
        ["loyalty", esc(h.loyalty || "")],
        ["confirmation", esc(h.confirmation_code || "")],
      ]), ["room_type"]), stayActs)}

      ${stayBlock("what it costs on top", "", withGaps(stayFacts([
        ["resort fee", esc(h.resort_fee || "")],
        ["incidental hold", esc(h.incidental_hold || "")],
        ["breakfast", esc(h.breakfast || "")],
        ["parking", esc(h.parking || "")],
      ]), ["resort_fee", "incidental_hold", "breakfast"]))}

      ${stayBlock("what the hotel has", amSum, withGaps(nAms ? amGrid : "", ["amenities", "photos"]))}

      ${stayBlock("checking out", h.check_out ? `out by ${stampShort(h.check_out)}` : "", withGaps(stayFacts([
        ["late checkout", esc(h.late_checkout || ""), 1],
      ]) + stayList(h.checkout_tasks, "hub-col-list--steps"), ["late_checkout"]))}

      ${stayBlock("the fine print", nRules ? `${nRules} lines` : "", stayList(h.house_rules, "hub-col-list--two"))}
      `}

      ${/* What the room cost - cash, points, deposit, the per-person maths - moved
            to the cost tab with the rest of the booked prices. The cancellation
            window is the one line here that was never a price: it is a date that
            still decides something, so it keeps its place on the board. */""}
      ${stayBlock("cancelling", h.cancellation_deadline ? "" : "no deadline on this row yet", stayFacts([
        ["free cancel until", h.cancellation_deadline
          ? esc(stampShort(h.cancellation_deadline)) + (cancelD != null
            ? ` <span class="${cancelD < 0 ? "stay-gone" : "stay-live"}">${esc(cancelD < 0 ? "window closed" : `${cancelD} days left`)}</span>` : "")
          : "", 1],
      ]))}

      ${stayBlock("notes", "", stayList(h.notes, "hub-col-list--two"))}
    </div>${rows.length > 1 ? groupHTML({
      kind: "housing", key: "housing", lead: 0, label: "what it beat",
      sub: "", link: (x) => x.url || "", tags: housingTags, ctx: stayCtx,
    }, rows.filter((r) => r !== h)) : ""}${otherCostsHTML(t)}`);

    bindPanel(list, t);
    bindShots();
    const filt = $("amFilter"), count = $("amCount");
    if (filt) filt.oninput = () => {
      const q = filt.value.trim().toLowerCase();
      let n = 0;
      // A group whose every item just went has to go too, or the headings stay put
      // and the result reads as eleven empty categories instead of two matches.
      list.querySelectorAll(".hub-col-group").forEach((g) => {
        let live = 0;
        g.querySelectorAll(".stay-am").forEach((el) => {
          const hit = !q || el.dataset.am.indexOf(q) >= 0;
          el.hidden = !hit;
          if (hit) live++;
        });
        g.hidden = !live;
        n += live;
      });
      // "0 of 63" is the answer to "is there a sauna" - never hide the count
      count.textContent = q ? `${n} of ${nAms} match` : `${nAms} listed`;
    };

    // One pin: the place you are actually staying. The losing options had their
    // map when the map was the point, and re-plotting them now says "still
    // deciding" on a panel whose whole premise is that you aren't.
    // The map slot is global, addressed by id, but this panel is also rendered
    // into DETACHED nodes by the self-check on every page load - with a synthetic
    // stay that has no coordinates. That render was reaching the real side pane
    // and printing "no location on the booked stay" into whatever tab you had
    // landed on, the cost tab included, where a map has no business being.
    // A panel that isn't on the page doesn't get to draw on it.
    const stops = list.isConnected ? stayStops([h], 1) : null;
    const mapKey = stops && `stay|${stops.map((s) => `${s.sel}@${s.lat},${s.lng}`).join(";")}`;
    if (stops && mapKey !== U.mut.dayMapKey) {
      U.mut.dayMapKey = mapKey;
      setHTML($("dayMapHost"), `<div class="dayv-map" id="dayMap"><div class="dayv-map-note">loading map…</div></div>`);
      renderDayMap(stops, { route: false, emptyNote: "no location on the booked stay — geocode to put it on the map" });
    }
  }

  const stayMissing = (rows) => rows.filter((h) => h.lat == null || h.lng == null).length;
  // Cheapest first, so the pin numbers mean something on their own - the tooltip
  // carries the name and the price the number is ranking.
  // `booked` swaps the pin's price for where it is. On the comparison board the
  // price IS the ranking the pin number stands for; on the booked panel it is a
  // number nothing can act on, and for an award room `money(rowCost(h))` floored
  // it to a flat "$0.00" - a stay that cost 30,000 points reading as free.
  function stayStops(rows, booked) {
    return rows.slice()
      .sort((a, b) => (rowCost(a) || Infinity) - (rowCost(b) || Infinity))
      .map((h) => ({
        sel: `housing:${h.id}`, kind: "stay", timed: true,
        title: h.name || h.address || "stay",
        time: booked ? (h.area || stampShort(h.check_in) || "")
                     : money(rowCost(h)) + (h.area ? ` · ${h.area}` : ""),
        lat: h.lat == null ? null : h.lat, lng: h.lng == null ? null : h.lng,
      }));
  }
  // "$45.00 per person per night at 6 · 3BR / 5 beds / 2 baths · Berkeley", and on
  // a booked stay the same line without its first bit. What each person owes on a
  // room already paid for is the cost tab's answer - it gives the full price, your
  // share and the way count beside every other line on the trip, which is more than
  // this line ever said. Sam, 2026-08-25, asked where the split belongs: "cost tab".
  function staySplit(h, c, booked) {
    const bits = [];
    const pp = booked ? 0 : perPersonNight(h);
    if (pp) bits.push(`${money(pp)} per person per night at ${c.party}`);
    const spec = [h.bedrooms != null ? `${trim1(h.bedrooms)}BR` : "", h.beds != null ? `${h.beds} beds` : "",
      h.baths != null ? `${trim1(h.baths)} baths` : ""].filter(Boolean).join(" / ");
    if (spec) bits.push(spec);
    if (h.area) bits.push(h.area);
    if (h.rating != null) bits.push(`${h.rating}★${h.reviews != null ? ` (${h.reviews})` : ""}`);
    return bits.join(" · ");
  }

  // Both panels wire the same things: sortable headers, add buttons, the fare
  // search, links that escape without selecting, and a row click that both picks
  // the option and opens it.
  function bindPanel(list, t) {
    list.querySelectorAll("[data-sortcol]").forEach((th) => {
      th.onclick = () => {
        const k = th.dataset.key, i = Number(th.dataset.sortcol);
        const cur = state.lsort[k];
        state.lsort[k] = (cur && cur.col === i) ? { col: i, dir: -cur.dir } : { col: i, dir: 1 };
        renderFocus();
      };
      // role=button + tabindex=0 promised keyboard operation the header never
      // delivered - it only had a click handler, so Enter and Space did nothing.
      th.onkeydown = (e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        e.preventDefault(); th.onclick();
      };
    });
    list.querySelectorAll("[data-sortreset]").forEach((b) => {
      b.onclick = (e) => { e.stopPropagation(); delete state.lsort[b.dataset.sortreset]; renderFocus(); };
    });
    list.querySelectorAll("[data-addkind]").forEach((b) => {
      b.onclick = () => {
        const k = b.dataset.addkind;
        if (k === "expense") return addExpense();
        // three boards post to the same table, so the button carries which form
        // to draw and which `type` that board's rows are filed under
        const seed = b.dataset.addtype ? { type: b.dataset.addtype } : {};
        logiModal(`add ${(b.dataset.addtype || k).replace("_", " ")}`, k, seed,
          (form, d) => API.post(`/trips/${t.id}/${k}`, unbool(form, d)));
      };
    });
    const fs = $("fareSearch");
    if (fs) fs.onclick = searchFares;
    // Taking a comparison table away also takes away the row you clicked to reach
    // the edit form, which is the only route to fields like wifi, the door code or
    // a rental's confirmation. Every booked panel carries its own way back in, so
    // the binding is generic - `data-editrow="<table>:<id>"` - rather than one
    // hand-wired button id per panel.
    list.querySelectorAll("[data-editrow]").forEach((b) => {
      b.onclick = (e) => {
        e.stopPropagation();
        const cut = b.dataset.editrow.indexOf(":");
        const kind = b.dataset.editrow.slice(0, cut), id = b.dataset.editrow.slice(cut + 1);
        const r = (t[kind] || []).filter((x) => String(x.id) === id)[0];
        if (r) editLogistics(kind, r);
      };
    });
    // …and a single blank field gets its own, because "edit the stay" is the wrong
    // size of door for one string. `<table>:<id>:<k1>,<k2>` rather than a per-field
    // attribute: one handler covers the wifi pair, a hotel's fees and a car's
    // pickup times, and a new prompt needs no new binding.
    list.querySelectorAll("[data-addfield]").forEach((b) => {
      b.onclick = (e) => {
        e.stopPropagation();
        const [kind, id, keys] = b.dataset.addfield.split(":");
        const r = (t[kind] || []).filter((x) => String(x.id) === id)[0];
        if (r) addFields(kind, r, String(keys || "").split(",").filter(Boolean));
      };
    });
    list.querySelectorAll("[data-wifiqr]").forEach((b) => {
      b.onclick = (e) => {
        e.stopPropagation();
        const r = (t.housing || []).filter((x) => String(x.id) === b.dataset.wifiqr)[0];
        if (r) showQR(r);
      };
    });
    // Copy is the control for the phone you are holding (see copyText).
    list.querySelectorAll("[data-wificopy]").forEach((b) => {
      b.onclick = (e) => {
        e.stopPropagation();
        return Promise.resolve(copyText(b.dataset.wificopy)).then((done) => {
          // Never claim a copy that did not happen - the password is on screen and
          // "copied" that silently failed is how you paste the wrong thing.
          toast(done ? "password copied" : "could not copy — the password is on the row");
        });
      };
    });
    // a link is an escape hatch out of the page, not a row selection
    list.querySelectorAll(".llink").forEach((a) => { (a.onclick = (e) => e.stopPropagation()); });
    bindRows(list, (id) => {
      state.selId = id;
      const tr = list.querySelector(`.lrow[data-id="${id}"]`);
      if (tr?.dataset.pickkey) state.pick[tr.dataset.pickkey] = Number(String(id).split(":")[1]);
      renderFocus(); renderContext();
    }, ".lrow");
    bindDeletes(list);
  }
  // Re-rendering the head throws away the control you just clicked, so arrow keys
  // and repeated clicks dead-end after one press. Put focus back where it was.
  // The party stepper changes what every shared row costs per head, so it moves
  // the pinned money block and the context rail too - not just the board under
  // the cursor. Repainting only the focus left the housing tab showing "÷ 8"
  // beside a money block still reading its seventh, which is the exact
  // disagreement the per-person work existed to remove. Both steppers route
  // through here, so the fix is one call, not one per caller.
  function repaint(focusId) {
    U.renderAll();
    const el = $(focusId);
    if (el) el.focus();
  }

  // Expenses that aren't standing in for a booking - food, tips, gifts. Kept out
  // of the two decision panels because they aren't options being weighed.
  function otherCostsHTML(t) {
    const rows = (t.expenses || []).filter((e) => !supersededExpense(e));
    const head = `<div class="hub-section-head lgroup-head lgroup-sub">
      <span class="hub-section-head-t lgroup-l">other costs</span>
      <span class="hub-section-head-sum lgroup-sum">${rows.length ? `${money(sumCost(rows))} across ${rows.length} line${rows.length === 1 ? "" : "s"}` : "nothing entered"}</span>
      <button class="hub-section-head-act lgroup-act" data-addkind="expense">+ add</button></div>`;
    if (!rows.length) return `${head}<div class="hub-section-empty">none yet</div>`;
    return `${head}<table class="hub-table ltable"><thead><tr><th>item</th><th>category</th><th class="hub-num">amount</th><th class="lstatus-h">status</th><th class="llink-h"></th></tr></thead><tbody>${
      rows.slice().sort((a, b) => rowCost(b) - rowCost(a)).map((e) => {
        const id = `expense:${e.id}`;
        return `<tr class="lrow${id === state.selId ? " selected" : ""}" data-id="${id}">
          <td>${esc(e.description || e.category || "expense")}</td><td class="bsrc">${esc(e.category || "—")}</td>
          <td class="hub-num">${money(e.amount)}</td>
          <td class="lstatus"><span class="hub-dot" style="--dot-color: var(${logiPipVar(e)})">${esc(e.status || "—")}</span></td>
          <td class="llink-c">${delBtn(`expenses/${e.id}`, e.description || e.category || "expense")}</td></tr>`;
      }).join("")}</tbody></table>`;
  }

  // "6 options · $1,184 – $1,836 · 2 unavailable", or the booked one by name.
  // Prices are all-in, so the spread moves with the bag toggles above it.
  function groupSummary(kind, rows) {
    if (!rows.length) return "nothing entered";
    const done = rows.filter(isCommitted), open = rows.filter(isOpen), dead = rows.filter(isDead);
    const bits = [];
    if (done.length) bits.push(`${done.length} booked`);
    if (open.length) bits.push(`${open.length + (done.length ? " other" : "")} option${open.length === 1 ? "" : "s"}`);
    const val = kind === "flights" ? allIn : rowCost;
    const priced = open.filter((r) => val(r) > 0).map(val).sort((a, b) => a - b);
    const lo = priced[0], hi = priced[priced.length - 1];
    // "$300.00 – $300.00" is a spread that isn't one; six fares at the same price
    // is a real outcome and should read as one number
    if (priced.length && (lo !== hi)) bits.push(`${money(lo)} – ${money(hi)}`);
    else if (priced.length && !done.length) bits.push(money(lo) + (priced.length > 1 ? " each" : ""));
    if (dead.length) bits.push(`${dead.length} unavailable`);
    return bits.join(" · ");
  }

  function groupHTML(g, rows) {
    // `kind` is the API table (and so the row id, the delete path and the add
    // endpoint); `cols` is which column set to draw it with. They were the same
    // thing until one table started backing three boards.
    const shape = g.cols || g.kind;
    // A guest reads the flight board for the itinerary, not the fares - so the
    // two money columns come off it there. Filtered at use rather than baked out
    // of U.LOGI_COLS, because that object is built before the body (and its guest
    // class) exists. `sort` keys by index, so a stored sort on a dropped column
    // simply finds nothing and the default order stands.
    const cols = (g.kind === "flights" && isGuest())
      ? U.LOGI_COLS[shape].filter((c) => c.l !== "cash" && c.l !== "points")
      : U.LOGI_COLS[shape];
    const key = g.key || g.kind;
    const sort = state.lsort[key];
    const view = rows.slice();
    if (sort && cols[sort.col]) {
      const s = cols[sort.col].s;
      view.sort((a, b) => {
        const x = s(a), y = s(b);
        const c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
        return c * sort.dir;
      });
    }
    // Default order answers the question the table exists for: what did we pick,
    // then what's the cheapest thing still on the table, then what's ruled out.
    // Arriving in insert order interleaved two unavailable Denver houses with the
    // four live ones, so the shortlist couldn't be read top-down.
    const val = g.kind === "flights" ? allIn : rowCost;
    if (!sort) {
      const rank = (r) => (isCommitted(r) ? 0 : isDead(r) ? 2 : 1);
      view.sort((a, b) => rank(a) - rank(b) || (val(a) || Infinity) - (val(b) || Infinity));
    }

    const action = (g.kind === "flights"
      ? `<button class="hub-section-head-act lgroup-act" id="fareSearch" title="run a live Google Flights search for this trip">search fares</button>` : "")
      + `<button class="hub-section-head-act lgroup-act" data-addkind="${g.kind}" data-addform="${esc(shape)}"${
        g.addType ? ` data-addtype="${esc(g.addType)}"` : ""}>+ add</button>`;
    // The table was always sortable - every header took a click - but nothing on
    // screen said so, and the order you landed on was unexplained. Naming the
    // current order (including the default) is what turns a hidden behaviour into
    // a control: you can see what you're looking at and get back from it.
    const sortName = sort && cols[sort.col]
      ? `${cols[sort.col].l} ${sort.dir > 0 ? "↑ low to high" : "↓ high to low"}`
      : "pick, then cheapest";
    const sortBar = rows.length ? `<span class="hub-sortbar lsortbar">
      <span class="hub-sortbar-k">sorted by</span><span class="hub-sortbar-v">${esc(sortName)}</span>
      ${sort ? `<button class="hub-sortbar-x" data-sortreset="${esc(key)}" title="back to the default order">reset</button>`
        : `<span class="hub-sortbar-h">click a column to change</span>`}</span>` : "";
    const headHTML = `<div class="hub-section-head lgroup-head${g.lead ? " lgroup-lead" : " lgroup-sub"}">
      <span class="hub-section-head-t lgroup-l">${esc(g.label)}</span>
      ${g.sub ? `<span class="lgroup-r">${esc(g.sub)}</span>` : ""}
      <span class="hub-section-head-sum lgroup-sum">${esc(groupSummary(g.kind, rows))}</span>${sortBar}${action}</div>`;

    if (!rows.length) return `${headHTML}<div class="hub-section-empty">${esc(g.empty || (g.kind === "flights" ? "no fares on the table yet — search or add one" : "none yet"))}</div>`;

    const ctx = g.ctx ? g.ctx(rows) : null;
    const ths = cols.map((c, i) => {
      const on = sort && sort.col === i;
      // A dim ↕ on every sortable header is the affordance the table never had.
      // It resolves to the live direction once that column is the sort.
      return `<th class="hub-sortable${c.num ? " hub-num" : ""}${on ? " hub-sorted" : ""}" data-key="${esc(key)}" data-sortcol="${i}"
        role="button" tabindex="0" aria-sort="${on ? (sort.dir > 0 ? "ascending" : "descending") : "none"}"
        title="${on ? `sorted ${sort.dir > 0 ? "low to high" : "high to low"} — click to flip` : `sort by ${esc(c.l)}`}"
        ><span>${esc(c.l)}<span class="hub-sort-indicator" aria-hidden="true">${on ? (sort.dir > 0 ? "↑" : "↓") : "↕"}</span></span></th>`;
    }).join("")
      // One "why" column, not two. The derived sentence and the badges answer the
      // same question about a row, and as separate columns neither fitted: nine
      // columns in a 985px panel squeezed the badges to one-per-line and starved
      // the stay name down to a six-line wrap.
      + (g.buys || g.tags ? `<th class="lwhy-h${g.buys ? " lwhy-wide" : ""}">${g.buys ? "what it buys" : "flags"}</th>` : "")
      + `<th class="lstatus-h">status</th><th class="llink-h"></th>`;

    // The option this decision is currently resting on gets marked, so the row you
    // are comparing everything against is read, not hunted for. That's the booked
    // one when there is one, and the cheapest live one when there isn't.
    const pickRow = g.pickKey ? picked(g.pickKey, view.filter((r) => !isDead(r)), g.eligible || (g.pickKey === "housing" ? fitsParty : null)) : null;
    const trs = view.map((r) => {
      const id = `${g.kind}:${r.id}`;
      const cls = [isCommitted(r) ? "is-booked" : "", isDead(r) ? "is-dead" : "",
        (pickRow && r === pickRow) ? "is-pick" : "",
        id === state.selId ? "selected" : ""].filter(Boolean).join(" ");
      const tds = cols.map((c) => `<td class="${c.num ? "hub-num" : ""}">${c.v(r)}</td>`).join("");
      const href = g.link ? g.link(r) : "";
      return `<tr class="lrow ${cls}" data-id="${esc(id)}"${g.pickKey ? ` data-pickkey="${esc(g.pickKey)}"` : ""}>${tds}
        ${g.buys || g.tags ? `<td class="lwhy${g.buys ? " lwhy-wide" : ""}">${
          g.buys?.(r, ctx) ? `<span class="lwhy-t">${esc(g.buys(r, ctx))}</span>` : ""}${
          g.tags ? tagsHTML(g.tags(r, ctx)) : ""}</td>` : ""}
        <td class="lstatus"><span class="hub-dot" style="--dot-color: var(${logiPipVar(r)})">${esc(r.status || "—")}</span></td>
        <td class="llink-c">${href ? `<a class="hub-link-chip llink" href="${esc(href)}" target="_blank" rel="noopener"
          title="${g.kind === "flights" ? "open this route on Google Flights" : "open the listing"}"
          >${g.kind === "flights" ? "fares" : "listing"} ↗</a>` : ""}${
          delBtn(`${g.kind}/${r.id}`, logiTitle(g.kind, r))}</td></tr>`;
    }).join("");

    // Every leg renders its own <table>, and under auto layout each one sized
    // its columns to its own contents - so "leaving" and "coming back" came out
    // on two different grids sitting one above the other. Flights always have
    // the same seven columns, so pin them and the groups read as one board.
    const w = LOGI_W[shape];
    const cg = w ? `<colgroup>${w.map((x) => `<col style="width:${x}">`).join("")}</colgroup>` : "";
    return `${headHTML}<table class="hub-table ltable${w ? " ltable-fixed" : ""}">${cg}<thead><tr>${ths}</tr></thead><tbody>${trs}</tbody></table>`;
  }
  // Column widths for the boards whose groups have to line up with each other, or
  // whose last columns were being starved off the edge as leftovers. Measured
  // against the widest real content, not guessed: the status word needs ~118px
  // and the trailing link ~88px, whatever the table.
  const LOGI_W = {
    // departs→arrives · carrier · route · all-in · flags · status · fares↗ + delete
    flights: ["17%", "14%", "10%", "11%", "11%", "15%", "11%", "11%"],
    // stay · all-in · /person/night · sleeps · beds/baths · what it buys · status · listing↗ + delete
    // the delete column's 3% came off the stay name and the two money columns -
    // every other column here is either prose that wraps ("what it buys") or a
    // two-character cell whose HEADER is the wide part (sleeps, beds/baths)
    // 2026-08-14: an "on points" column landed between all-in and /person/night,
    // so this list went one short and the last column fell back to auto width.
    // Nine entries now. Squeezing the trailing column to make room was the wrong
    // place to take it from - measured at 1280px, "listing ↗" needs ~82px and a
    // 7% claim gave it 46, which was the whole 36px board overflow. It keeps 12%;
    // the room comes off the wide prose and identity columns instead.
    // Sized against measured header widths at a 1280px half-screen, where this
    // board pane is only ~663px: cash needs 61px, fits 55, "bed/bath" 89 on one
    // line (45 broken at its slash), "listing ↗" 82. The identity and prose
    // columns give up the room because they wrap gracefully and these do not.
    // 2026-10-14: liquid draws status as a capsule with an icon, and "considering"
    // came out ~100px against a 13% (82px) column, so it sat on the delete button.
    // "capacity unchecked" needs ~100px of flags column for the same reason. Both
    // take it from fits and bed/bath (one-character cells, heads that wrap), the
    // stay name and the two money columns that never hold more than "$450.00".
    // 2026-10-14 (one board scale): the grey money lane is back and only its outer
    // edges pad 14px, so cash and bed/bath carry that inset; the link and delete
    // stack as two 28px circles, which frees the trailing column to 8%.
    housing: ["15%", "11%", "9%", "9%", "7%", "8%", "16%", "17%", "8%"],
    // car · pick up→drop off · seats · all-in · flags · status · listing↗ + delete
    // pinned so the counter board and the Turo board below it read as one grid.
    // the trailing column carries "listing ↗" (~58px of button) at every window
    // size, so 8% starved it the moment the pane dropped under ~1500px - 4% off
    // the car name buys it back and the name still wraps fine.
    carrental: ["20%", "19%", "8%", "13%", "16%", "12%", "12%"],
    // what · type · from → to · when · cost · points · status · listing↗ + delete
    // Unpinned until 2026-08-14, because the board it sits on threw before it ever
    // painted (`flightLegBlock` referenced an undefined `x`), so nothing measured
    // the overflow. Auto width came out 780px in a 733px pane at a 1280px
    // half-screen. The 47px comes off the two columns that wrap without losing
    // anything - the description and the route - and every other column keeps at
    // least its natural width.
    transportation: ["18%", "11%", "12%", "10%", "11%", "12%", "13%", "13%"],
  };
  function logiPipVar(r) { return isCommitted(r) ? "--good" : isDead(r) ? "--alert" : "--fg-faint"; }

  // ── CREW ────────────────────────────────────────────────────────────────────
  // A crew row is a person, not a line item, so it renders as a card carrying
  // everything their contact node knows: who they are, what they want out of a
  // trip, and what will ruin it for them. The /preferences endpoint has always
  // returned all of this; the list just used to throw it away and print a name.

  // The card itself lives in crewcard.js, shared with the account page's
  // designer so the preview there IS this card rather than a copy of it. What
  // comes back here is the whole render vocabulary - label(), the fact and note
  // builders - because the detail rail below renders the same words one
  // person at a time.
  // CC is U.CC (core); label()/crewFacts() etc. were destructured here in the plain page but
  // nothing in this range calls them, so only CC itself is kept.
  const CC = U.CC;

  // `state.prefs` is null in two different situations - the fetch is still in
  // flight, or it failed - and the crew card, the member rail, and the group
  // read each used to collapse both into whatever they said about a person with
  // no contact node. Returns the marker to print, or false once prefs are in.
  const prefsWait = () => !state.prefs && (state.prefsErr
    ? `couldn't load travel prefs — ${esc(state.prefsErr)}` : "loading travel prefs…");
  const shortName = (n) => String(n || "").split(/\s+/)[0];


  // One card per person. The card carries the long-form read - summary, aliases,
  // the must/want spread, and the three flags that can wreck a plan. Every slot
  // is floored to the same height in trips.css, so the pills, the rhythm facts,
  // and the flag block land at the same y on every card and a value still reads
  // across the grid. The full rating spread and the meals answer stay in the
  // detail rail, where one person at a time belongs.
  // The portal into the two Google Forms. Anchors, never buttons: guest mode
  // hides every button inside the focus list, and this is the one control a
  // guest is supposed to have.
  //
  // `f` is null for everyone but the pinned member - a guest on the mirror, or
  // whoever "view as" is running as on Hub (see api._bound_key). Unpinned Hub
  // gets every card's portal, which is how Sam opens a crew member's sheet.
  //
  // These used to be links out to the Google form. The form is answered on the
  // board now, so they open /trips/preferences instead - same page the guest
  // gets, carrying the member key for the unpinned case. The Google forms still
  // exist and still sync; they are just no longer the way in.
  function crewForms(f) {
    if (!f?.forms) return "";
    const q = f.ref ? `?ref=${encodeURIComponent(f.ref)}` : "";
    return `<div class="cforms">${f.forms.map((x) => `
      <a class="cform${x.done ? " done" : ""}" href="/trips/preferences${q}"
         title="${x.done ? `answered ${esc(x.submitted_at.slice(0, 10))} — open to change it`
                         : "not answered yet"}">
        <span class="cform-pip" aria-hidden="true">${x.done ? "✓" : "•"}</span>${esc(x.kind)} →</a>`).join("")}</div>`;
  }

  function memberForms(mid) {
    const all = [...((state.prefs?.members) || []),
                 ...((state.prefs?.members_without_contact) || [])];
    const hit = all.find((c) => c.member_id === mid);
    return hit?.forms;
  }

  function listCrew(head, list) {
    setHTML(head, `<div class="funnel-tools">
      <button class="funnel-add" id="mfsync">sync forms</button>
      <button class="funnel-add" id="mroster">+ from roster</button>
      <button class="funnel-add is-primary" id="madd">+ new</button></div>`);
    $("madd").onclick = addMember;
    $("mroster").onclick = rosterPicker;
    $("mfsync").onclick = syncForms;
    const ms = state.trip.members || [];
    if (!ms.length) {
      setHTML(list, `<div class="hub-empty-state empty">no crew yet — pull them in from a past trip with <b>+ from roster</b></div>`);
      return;
    }
    const byId = {}, statusById = {};
    ((state.prefs?.members) || []).forEach((c) => { (byId[c.member_id] = c); });
    // Both lists for the footer indicator, only the contact list for the card
    // body: a members_without_contact entry carries `filled` and `card` but no
    // prefs at all, so feeding it to the card would swap the honest "no prefs
    // yet" line for a body of em-dashes.
    [...((state.prefs?.members) || []),
     ...((state.prefs?.members_without_contact) || [])]
      .forEach((c) => { (statusById[c.member_id] = c); });
    setHTML(list, `<div class="crewgrid">${ms.map((m) => {
      const c = byId[m.id];
      return CC.card(m, c, (c?.travel_prefs) || {}, {
        selected: (`member:${m.id}`) === state.selId,
        headExtra: delBtn(`members/${m.id}`, m.name),
        footer: CC.formStatus(statusById[m.id]),
        wait: prefsWait(),
      });
    }).join("")}</div>`);
    bindRows(list, (id) => { state.selId = id; renderFocus(); renderContext(); }, ".ccard");
    bindDeletes(list);
    if (!state.prefs) loadPrefs();
  }

  // Re-read both Google Forms and pull anything new into the board. Hub only -
  // guest mode hides every button in the funnel head, and the guest's own way to
  // do this is the check on their preferences page.
  function syncForms() {
    const b = $("mfsync");
    b.disabled = true; b.textContent = "syncing…";
    return API.post("/prefs/sync", {}).then((r) => {
      state.prefs = null;
      return Promise.resolve(loadPrefs()).then(() => {
        U.renderAll(); // trips.js calls an undefined render() here; renderAll is what it meant
        const un = ["travel", "food"].reduce((n, k) => n + ((r[k]?.unmatched) || 0), 0);
        toast(r.throttled ? "just synced — try again in a moment"
          : un ? `synced · ${un} response${un === 1 ? "" : "s"} nobody could be matched to`
               : "forms synced");
      });
    }).catch((e) => { toast(`sync failed — ${errMsg(e)}`); }).then(() => {
      b.disabled = false; b.textContent = "sync forms";
    });
  }

  // Pull someone you have already travelled with onto this trip. The roster is a
  // DISTINCT over the members table (see db.roster) - no separate people store to
  // keep in sync, and the contact_slug rides along so travel prefs light up the
  // moment they land.
  function rosterPicker() {
    const m = $("modal");
    setHTML(m, `<div class="hub-modal-title">add from roster</div><div class="ctx-sub">loading…</div>`);
    $("modalScrim").hidden = false;
    $("modalScrim").onclick = (e) => { if (e.target === $("modalScrim")) closeModal(); };
    return API.get(`/trips/roster?exclude=${state.trip.id}`).then(rosterList, (e) => {
      setHTML(m, `<div class="hub-modal-title">add from roster</div><div class="ctx-sub">could not load roster — ${esc(errMsg(e))}</div>
      <div class="hub-modal-actions"><button class="hub-btn" id="mCancel">close</button></div>`); $("mCancel").onclick = closeModal;
    });
    function rosterList(people) {
    if (!people.length) {
      setHTML(m, `<div class="hub-modal-title">add from roster</div><div class="ctx-sub">everyone you have travelled with is already on this trip.</div>
        <div class="hub-modal-actions"><button class="hub-btn" id="mCancel">close</button></div>`);
      $("mCancel").onclick = closeModal; return;
    }
    setHTML(m, `<div class="hub-modal-title">add from roster</div>
      <div class="rosterlist">${people.map((p, i) => `
        <label class="rosteritem"><input type="checkbox" data-i="${i}">
          <span class="rosteritem-meat">
            <span class="rosteritem-name">${esc(p.name)}</span>
            <span class="rosteritem-sub">${esc(p.trips.map((t) => t.name).join(" · "))}</span>
          </span>
          ${p.contact_slug ? `<span class="rosteritem-tag">prefs</span>` : ""}
        </label>`).join("")}</div>
      <div class="hub-modal-actions"><button class="hub-btn" id="mCancel">cancel</button><button class="hub-btn hub-btn--accent" id="mSave">add selected</button></div>`);
    $("mCancel").onclick = closeModal;
    $("mSave").onclick = () => {
      const picked = [...m.querySelectorAll(".rosteritem input:checked")].map((el) => people[Number(el.dataset.i)]);
      if (!picked.length) { toast("nobody selected"); return; }
      // ponytail: one POST per person against the endpoint that already exists,
      // rather than a bulk route for a list that is never more than a dozen long.
      let chain = Promise.resolve();
      picked.forEach((p) => {
        chain = chain.then(() => API.post(`/trips/${state.trip.id}/members`, { name: p.name, email: p.email, contact_slug: p.contact_slug }));
      });
      return chain.then(() => {
        closeModal();
        return reload();
      }).then(() => loadPrefs())   // the new crew's prefs are not in the cached payload
        .then(() => { toast(`added ${picked.length}`); })
        .catch((e) => { toast(`add failed — ${errMsg(e)}`); });
    };
    }
  }

Object.assign(U, { stayPanel, stayMissing, stayStops, staySplit, bindPanel, repaint, otherCostsHTML, groupHTML,
  logiPipVar, prefsWait, shortName, crewForms, memberForms, listCrew });
})();
