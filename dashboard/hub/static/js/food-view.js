/* food-view.js — the /food area view, as one renderer mounted by two surfaces.
 *
 * The Hub's /food module and the trips board's food tab show the same research
 * from the same database, and they used to show it through two separate bodies of
 * code: /food's own page script, and a hand-ported subset inside trips.js. The
 * port was already drifting on the day it was written (its own comment says the
 * score block was "lifted from the /food module") and every later change to one
 * side was a change the other never got.
 *
 * So there is one renderer now and it is this file. It owns the rail, the list,
 * the map and the place detail; it owns nothing about where those live. The
 * caller hands it five elements and a way to fetch one place, and the caller is
 * what differs between the two surfaces:
 *
 *   /food        elements from its own page shell, places fetched by area member,
 *                child areas are links to /food/<slug>.
 *   trips board  elements from the trips shell (the funnel sub-nav, the focus
 *                column, the context rail), places fetched trip-scoped, child
 *                areas filter in place because the mirror has no /food to link to.
 *
 * Read-only, on both. The /food skill is the only writer of that database and
 * nothing in this file may change that: there is no POST here and there is not
 * meant to be one.
 */

(() => {
  

  const UNIT_SEP = "\x1f";          // group_concat(char(31)) separator from db.get_areas
  const STALE_MS = 90 * 864e5;      // practical facts go stale by policy at 90 days

  function esc(s) {
    // Every string here came from a research run that quoted the open web verbatim,
    // so it reaches the DOM as text, never as markup.
    return String(s ?? "").replace(/[&<>"']/g, c => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  const parseJSON = (s, fallback) => {
    if (Array.isArray(s) || (s && typeof s === "object")) return s;
    try { return JSON.parse(s); } catch { return fallback; }
  };

  const fold = s => String(s || "").normalize("NFKD").replace(/[̀-ͯ]/g, "")
    .toLowerCase().trim();

  const areaHref = slug => `/food/${String(slug).split("/").map(encodeURIComponent).join("/")}`;

  /* ------------------------------------------------------------- scores ---
     Three states, three renderings, and the middle one is the reason this is not
     a one-liner. A thin score shows its number WITH the size of the ledger under
     it, because "8" and "8, on two reviews" are different claims. A place with no
     literate evidence has no number at all: not a zero, not a dash. */

  function scoreBlock(score, confidence, rows, emptyLabel) {
    if (score === null || score === undefined || confidence === "none") {
      return `<div class="score"><span class="score-none">${esc(emptyLabel)}</span></div>`;
    }
    const n = Number(score).toFixed(1);
    const thin = confidence === "thin";
    const label = thin
      ? `thin · ${rows} source${rows === 1 ? "" : "s"}`
      : `${esc(confidence)} · ${rows} source${rows === 1 ? "" : "s"}`;
    return `<div class="score">
      <span class="score-num">${n}</span>
      <span class="score-conf${thin ? " thin" : ""}">${label}</span>
    </div>`;
  }

  const depthBlock = p =>
    scoreBlock(p.depth_score, p.depth_confidence, p.literate_count ?? 0, "no expert signal found");
  const execBlock = p =>
    scoreBlock(p.execution_score, p.execution_confidence, p.evidence_count ?? 0, "no evidence yet");

  const statusFlag = p =>
    p.status === "unverified" ? `<span class="status-flag status-unverified">unverified</span>`
    : p.status === "closed" ? `<span class="status-flag status-closed">closed</span>`
    : "";

  const scored = p => p.depth_score !== null && p.depth_score !== undefined
    && p.depth_confidence !== "none";

  /* -------------------------------------------------------------- state --- */

  const state = {
    els: null, api: null, navigate: null,
    area: null, children: [], places: [], scene: { city: [], neighborhoods: [] },
    view: "places", selected: null,
    map: null, pinLayer: null, overlay: null, homeView: null, markers: new Map(),
    filters: { hood: "", broad: "", specific: "", price: new Set(), discovery: new Set(), minDepth: 0 },
  };

  const el = k => state.els?.[k];

  function fail(err, what) {
    console.error(err);
    const host = el("list");
    if (host) host.innerHTML = `<div class="hub-error">could not load ${esc(what)}. ${esc(err.message || err)}</div>`;
  }

  /* -------------------------------------------------------------- scene ---
     Labelled sections of short entries, each with its handle in its own column.
     This is a reference surface you scan for the one tradition you came for; the
     essay it replaced made you read four hundred words to find two.

     Three input shapes are accepted, newest first, because an area researched
     under an older contract still has to render:
       {city:[...], neighborhoods:[...]}   the current format
       [{label, items}]                    sections only, no neighborhood split
       "prose"                             the original free text */

  function parseScene(raw) {
    const empty = { city: [], neighborhoods: [] };
    if (!raw) return empty;
    const v = parseJSON(raw, null);
    if (v && !Array.isArray(v) && typeof v === "object") {
      return { city: v.city || [], neighborhoods: v.neighborhoods || [] };
    }
    if (Array.isArray(v) && v.every(s => s && Array.isArray(s.items))) {
      return { city: v, neighborhoods: [] };
    }
    return {
      city: [{ label: "rundown", items: String(raw).split(/\n{2,}/).filter(s => s.trim()).map(p => ({ v: p.trim() })) }],
      neighborhoods: [],
    };
  }

  const sceneCount = sections => sections.reduce((n, s) => n + s.items.length, 0);

  function noRundown() {
    return `<div class="empty">
      <p class="lead">No rundown for this area yet.</p>
      <p class="hint">Run <code>/food ${esc(state.area.name)}</code> to write one.</p>
    </div>`;
  }

  function sceneHTML(sections) {
    if (!sections.length) return noRundown();
    return sections.map(sec => `<section class="sc-sec">
      <h3 class="sc-head">${esc(sec.label || "")}</h3>
      ${sec.items.map(it => it.k
        ? `<div class="sc-row"><span class="k">${esc(it.k)}</span><span class="v">${esc(it.v)}</span></div>`
        : `<div class="sc-row bare"><span class="v">${esc(it.v)}</span></div>`).join("")}
    </section>`).join("");
  }

  /* One grid, not two. The rundown's curated neighborhood cards and the areas that
     actually hold places are the same set seen from two sides, and rendering them
     separately left the reader working out why Gowanus was in one and not the other.
     A child that has a card keeps the card; a child with no card still shows up,
     because it is a real destination nobody has written up yet. */
  function withinCards() {
    const cards = new Map((state.scene.neighborhoods || [])
      .filter(h => h?.name).map(h => [fold(h.name), h]));
    const out = state.children.map(c => {
      const card = cards.get(fold(c.name));
      cards.delete(fold(c.name));
      return { ...c, note: card?.note, traditions: card?.traditions,
               streets: card?.streets, heads_up: card?.heads_up };
    });
    // Left over: the rundown names somewhere that holds no places yet. Kept, but not a link.
    return out.concat([...cards.values()].map(h => ({ ...h, orphan: true, place_count: 0 })));
  }

  /* Neighborhoods are cards, not rows: you read them against each other to pick where
     to go, and that comparison is what a card grid is for. Every slot is pinned to the
     same height on every card, so a value still reads across the grid. */
  function hoodCard(h) {
    const traditions = (h.traditions || []).filter(Boolean);
    const cuisines = (h.cuisines || "").split(UNIT_SEP).filter(Boolean).slice(0, 3);
    // Where a caller handles child areas itself (the trips board, which has no /food to
    // reach) the card is a button on this page rather than a link off it.
    const tag = h.orphan ? "div" : (state.navigate ? "button" : "a");
    const open = h.orphan ? ""
      : state.navigate ? `type="button" data-child="${esc(h.slug || h.name)}"`
      : `href="${areaHref(h.slug)}"`;
    return `<${tag} class="hcard${h.orphan ? " hcard-orphan" : ""}" ${open}
      ${h.orphan ? "" : `data-member="${esc(JSON.stringify(h.member))}"`}>
      <div class="hcard-head">
        <span class="hname">${esc(h.name)}</span>
        ${h.orphan
          ? `<span class="hboro">not researched</span>`
          : `<span class="hboro">${h.place_count} place${h.place_count === 1 ? "" : "s"}</span>`}
      </div>
      ${h.note ? `<p class="hsum">${esc(h.note)}</p>` : ""}
      <div class="hcard-pills">
        ${(traditions.length ? traditions : cuisines).length
          ? (traditions.length ? traditions : cuisines)
              .map(t => `<span class="hpill">${esc(t)}</span>`).join("")
          : `<span class="hpill hpill-none">no tradition recorded</span>`}
      </div>
      <div class="hcard-foot">
        <span class="hfact-k">where exactly</span>
        <span class="hfact-v">${esc(h.streets || "not narrowed down yet")}</span>
        ${h.heads_up ? `<span class="hnote">${esc(h.heads_up)}</span>` : ""}
      </div>
    </${tag}>`;
  }

  function withinHTML() {
    const cards = withinCards();
    if (!cards.length) return noRundown();
    const real = cards.filter(c => !c.orphan);
    const orphans = cards.filter(c => c.orphan);
    const group = (label, items) => items.length ? `
      <div class="group-head"><span>${label}</span><span class="n">${items.length}</span></div>
      <div class="hoodgrid">${items.map(hoodCard).join("")}</div>` : "";
    return group(`inside ${esc(state.area.name)}`, real)
         + group("noted, not researched", orphans);
  }

  /* ------------------------------------------------------------ filters --- */

  const cuisinesOf = p =>
    [p.cuisine_specific, ...parseJSON(p.cuisines_extra, [])].filter(Boolean);

  function matches(p, f) {
    // A borough or city page is a roll-up of several neighborhoods, and "where do I
    // go" is a neighborhood question, not a borough one. Without this the only way to
    // read one neighborhood is to open a separate area for it.
    if (f.hood && p.neighborhood !== f.hood) return false;
    if (f.broad && p.cuisine_broad !== f.broad) return false;
    // A place that also cooks a second tradition surfaces under both, which is the
    // point of storing cuisines_extra rather than one flat label.
    if (f.specific && !cuisinesOf(p).includes(f.specific)) return false;
    if (f.price.size && !f.price.has(p.price_band)) return false;
    if (f.discovery.size && !f.discovery.has(p.discovery)) return false;
    if (f.minDepth && !(p.depth_score >= f.minDepth)) return false;
    if (f.q) {
      const hay = [p.name, p.cuisine_specific, p.cuisine_broad, p.neighborhood, p.borough, p.summary]
        .map(v => String(v || "").toLowerCase()).join(" ");
      if (!hay.includes(f.q)) return false;
    }
    return true;
  }

  // Count for one chip = what the list would hold if that chip alone were toggled on,
  // every other filter still applied. Anything else and the number lies about the click.
  function countWith(dimension, value) {
    const f = { ...state.filters, price: new Set(state.filters.price), discovery: new Set(state.filters.discovery) };
    if (dimension === "price" || dimension === "discovery") { f[dimension] = new Set([value]); }
    else { f[dimension] = value; }
    return state.places.filter(p => matches(p, f)).length;
  }

  const specificsUnder = broad =>
    [...new Set(state.places.filter(p => !broad || p.cuisine_broad === broad).flatMap(cuisinesOf))];

  const filtersActive = () => {
    const f = state.filters;
    return !!(f.hood || f.broad || f.specific || f.price.size || f.discovery.size || f.minDepth || f.q);
  };

  /* --------------------------------------------------------------- rail ---
     The rail is the view's control: it picks what the focus column shows, and
     carries the filters under it when that is the place list. Filters do NOT live
     over the list — the list column is the thing being filtered, and stacking the
     controls on top of it is what made the working column so short. */

  function renderRail() {
    const rail = el("rail");
    if (!rail) return;
    const f = state.filters;
    // Only worth a control when the view actually spans more than one: a neighborhood
    // holds one value and the select would be a no-op.
    const hoods = [...new Set(state.places.map(p => p.neighborhood).filter(Boolean))].sort();
    const broads = [...new Set(state.places.map(p => p.cuisine_broad).filter(Boolean))].sort();
    const specifics = specificsUnder(f.broad).sort();
    const prices = [...new Set(state.places.map(p => p.price_band).filter(Boolean))]
      .sort((a, b) => a.length - b.length);

    const chip = (dim, value, label) => {
      const on = state.filters[dim].has(value);
      const n = countWith(dim, value);
      return `<button class="filter-chip${on ? " active" : ""}" data-dim="${dim}" data-val="${esc(value)}"
        ${n === 0 && !on ? "disabled" : ""} aria-pressed="${on}">
        <span class="filter-chip-box"></span>${esc(label)}
        <span class="filter-chip-count">${n}</span>
      </button>`;
    };

    const nav = (view, label, n) => `<button class="hub-nav-item fvtab${state.view === view ? " active" : ""}" data-view="${view}"
        aria-pressed="${state.view === view}">
        <span class="hub-nav-label fvtab-l">${label}</span><span class="fvtab-n">${n}</span>
      </button>`;

    const within = withinCards().filter(c => !c.orphan).length;
    rail.innerHTML = `
      <nav class="hub-nav-rail fview-nav">
        ${nav("places", "places", state.places.length)}
        ${nav("city", "the city", sceneCount(state.scene.city))}
        ${withinCards().length
          // The count is the areas you can actually open, which is what the label
          // promises. Counting the rundown's orphan cards too made the nav read 9
          // over a grid of 8.
          ? nav("within", "areas within", within) : ""}
      </nav>
      ${state.children.length && !state.compact ? `<div class="within">
        <span class="filters-head">areas within</span>
        ${state.children.map(c => {
          const tag = state.navigate ? "button" : "a";
          const open = state.navigate
            ? `type="button" data-child="${esc(c.slug || c.name)}"` : `href="${areaHref(c.slug)}"`;
          return `<${tag} class="within-row${f.hood && f.hood === c.name ? " active" : ""}" ${open}
             data-member="${esc(JSON.stringify(c.member))}">
            <span class="within-name">${esc(c.name)}</span>
            <span class="chip">${esc(c.level)}</span>
            <span class="within-n">${c.place_count}</span>
          </${tag}>`;
        }).join("")}
      </div>` : ""}
      ${state.view === "places" && state.places.length ? `<details class="filters" ${!state.compact && window.innerWidth > 680 ? "open" : ""}>
        <summary class="filters-head">filter</summary>
        <div class="filter-row">
          ${hoods.length > 1 ? `<span class="f-sel"><select class="f-select" id="fvHood" aria-label="neighborhood">
            <option value="">every neighborhood</option>
            ${hoods.map(h => `<option value="${esc(h)}"${f.hood === h ? " selected" : ""}>${esc(h)}</option>`).join("")}
          </select></span>` : ""}
          <span class="f-sel"><select class="f-select" id="fvBroad" aria-label="cuisine">
            <option value="">every cuisine</option>
            ${broads.map(c => `<option value="${esc(c)}"${f.broad === c ? " selected" : ""}>${esc(c)}</option>`).join("")}
          </select></span>
          <span class="f-sel"><select class="f-select" id="fvSpecific" aria-label="tradition" ${specifics.length ? "" : "disabled"}>
            <option value="">every tradition</option>
            ${specifics.map(c => `<option value="${esc(c)}"${f.specific === c ? " selected" : ""}>${esc(c)}</option>`).join("")}
          </select></span>
          <span class="f-sel"><select class="f-select" id="fvDepth" aria-label="minimum depth">
            <option value="0">any depth</option>
            ${[6, 7, 8, 9].map(v => `<option value="${v}"${f.minDepth === v ? " selected" : ""}>depth ${v}+</option>`).join("")}
          </select></span>
        </div>
        <div class="filter-row wrap">
          ${chip("discovery", "consensus", "consensus")}
          ${chip("discovery", "dig", "dig")}
        </div>
        ${prices.length ? `<div class="filter-row wrap">${prices.map(pb => chip("price", pb, pb)).join("")}</div>` : ""}
      </details>` : ""}`;

    rail.querySelectorAll(".fvtab").forEach(b => { b.addEventListener("click", () => {
      state.view = b.dataset.view;
      renderRail();
      renderFocus();
    }); });
    rail.querySelectorAll(".filter-chip").forEach(b => { b.addEventListener("click", () => {
      const set = state.filters[b.dataset.dim];
      set.has(b.dataset.val) ? set.delete(b.dataset.val) : set.add(b.dataset.val);
      refresh();
    }); });
    if (state.navigate) {
      rail.querySelectorAll("[data-child]").forEach(b => { b.addEventListener("click", () => {
        state.navigate(b.dataset.child);
      }); });
    }
    const on = (id, fn) => { const n = rail.querySelector(id); if (n) n.addEventListener("change", fn); };
    on("#fvBroad", e => {
      state.filters.broad = e.target.value;
      // A tradition picked under the old cuisine may not exist under the new one.
      if (state.filters.specific && !specificsUnder(e.target.value).includes(state.filters.specific)) {
        state.filters.specific = "";
      }
      refresh();
    });
    on("#fvHood", e => { state.filters.hood = e.target.value; refresh(); });
    on("#fvSpecific", e => { state.filters.specific = e.target.value; refresh(); });
    on("#fvDepth", e => { state.filters.minDepth = Number(e.target.value); refresh(); });
  }

  /* -------------------------------------------------------------- focus --- */

  function renderFocus() {
    const head = el("head"), list = el("list");
    if (!head || !list) return;

    if (state.view === "city" || state.view === "within") {
      const stamp = state.area.scene_researched
        ? `researched ${esc(state.area.scene_researched)}` : "not researched yet";
      const within = withinCards().filter(c => !c.orphan).length;
      const count = state.view === "city"
        ? `${sceneCount(state.scene.city)} across ${state.scene.city.length} section${state.scene.city.length === 1 ? "" : "s"}`
        : `${within} area${within === 1 ? "" : "s"} within`;
      head.innerHTML = `<div class="fview-head"><span>${count}</span><span>${stamp}</span></div>`;
      list.innerHTML = state.view === "city"
        ? `<div class="scene-view">${sceneHTML(state.scene.city)}</div>`
        : `<div class="scene-view hoods-view">${withinHTML()}</div>`;
      if (state.navigate) {
        list.querySelectorAll("[data-child]").forEach(b => { b.addEventListener("click", () => {
          state.navigate(b.dataset.child);
        }); });
      }
      return;
    }

    const shown = state.places.filter(p => matches(p, state.filters));
    head.innerHTML = `<div class="fview-head">
      <span class="fview-search"><span aria-hidden="true">🔍</span><input id="fvSearch" type="search"
        aria-label="search ${esc(state.area.name)}" placeholder="cuisine, neighborhood, name"
        value="${esc(state.filters.q || "")}"></span>
      <span class="fview-count">${shown.length} of ${state.places.length} shown</span>
      <button class="filter-reset" id="fvReset" ${filtersActive() ? "" : "hidden"}>clear filters</button>
      ${state.portal ? `<a class="fview-portal" href="${esc(state.portal)}">open the full research</a>` : ""}
    </div>`;
    list.innerHTML = `<div class="results">${resultsHTML(shown)}</div>`;

    const search = head.querySelector("#fvSearch");
    search.addEventListener("input", e => {
      state.filters.q = e.target.value.trim().toLowerCase();
      // Only the list and the pins move on a keystroke; re-rendering the head would
      // take the caret out of the box the user is typing in.
      paint();
      const n = head.querySelector(".fview-count");
      if (n) n.textContent = `${state.places.filter(p => matches(p, state.filters)).length} of ${state.places.length} shown`;
      const r = head.querySelector("#fvReset");
      if (r) r.hidden = !filtersActive();
    });
    head.querySelector("#fvReset").addEventListener("click", () => {
      state.filters = { hood: "", broad: "", specific: "", price: new Set(), discovery: new Set(), minDepth: 0, q: "" };
      refresh();
    });
    bindRows(list);
  }

  // The list alone, for a keystroke. renderFocus rebuilds the head with it.
  function paint() {
    const list = el("list");
    const box = list?.querySelector(".results");
    if (!box) return;
    box.innerHTML = resultsHTML(state.places.filter(p => matches(p, state.filters)));
    drawPins();
  }

  function bindRows(list) {
    const box = list.querySelector(".results");
    if (box) box.addEventListener("click", e => {
      const row = e.target.closest(".row");
      if (row) showPlace(row.dataset.slug);
    });
  }

  function refresh() {
    renderRail();
    renderFocus();
    drawPins();
  }

  function resultsHTML(shown) {
    if (!shown.length) {
      return `<div class="empty">
        <p class="lead">${state.places.length ? "Nothing matches these filters." : "No places researched in this area yet."}</p>
        <p class="hint">${state.places.length
          ? "Clear a filter to widen the set."
          : `Run <code>/food ${esc(state.area.name)}</code> to research it.`}</p>
      </div>`;
    }
    // Judged and unjudged are separate groups, not one numeric sort with the unknowns
    // swept to the tail. A place nobody qualified has assessed is not a bad place.
    const judged = shown.filter(scored);
    const unjudged = shown.filter(p => !scored(p));
    const group = (label, items) => items.length ? `
      <div class="group-head"><span>${label}</span><span class="n">${items.length}</span></div>
      ${items.map(placeRow).join("")}` : "";
    return group("scored on depth", judged) + group("no expert signal yet", unjudged);
  }

  function placeRow(p) {
    const sel = state.selected === p.slug ? " selected" : "";
    const hood = p.neighborhood || p.borough || "";
    return `<button class="row${sel}" data-slug="${esc(p.slug)}">
      <span class="row-name">${esc(p.name)}</span>
      ${depthBlock(p)}
      <span class="row-sub">
        <span class="chip chip-cuisine" title="${esc(p.cuisine_specific || p.cuisine_broad || "")}">${esc(p.cuisine_specific || p.cuisine_broad || "—")}</span>
        ${p.price_band ? `<span class="chip chip-price">${esc(p.price_band)}</span>` : ""}
        ${hood ? `<span>${esc(hood)}</span><span class="dot">·</span>` : ""}
        <span class="mark mark-${esc(p.discovery)}">${esc(p.discovery)}</span>
        ${statusFlag(p)}
      </span>
    </button>`;
  }

  /* ---------------------------------------------------------------- map ---
     The mark is the Hub's shared one (map.css): a dot that never leaves its
     coordinate, with the label hung above it on a leader. Where the trips map leads
     its chip with a clock, this one leads with the depth score — same grammar, this
     map's number. The chip IS the label, so there is no tooltip repeating it. */

  function markIcon(p) {
    const cls = [
      "mstop", `mstop-${p.discovery}`,
      scored(p) ? "" : "is-anytime",           // nothing qualified has scored it: hollow dot
      state.selected === p.slug ? "is-selected" : "",
    ].filter(Boolean).join(" ");
    return L.divIcon({
      className: "",
      html: `<span class="${cls}">`
        + `<span class="mchip">${scored(p) ? `<b>${Number(p.depth_score).toFixed(1)}</b>` : ""}`
        + `<em>${esc(p.name)}</em></span><span class="mlead"></span><span class="mdot"></span></span>`,
      iconSize: [10, 10], iconAnchor: [5, 5],
    });
  }

  /* Chips are hover-only, so nothing collides and there is no stack to build. What is
     left is the frame edge: a chip centred on a dot near the left or right side hangs
     half of itself off the map, so near an edge it anchors to the dot instead of
     centring on it. Recomputed on move because which dots are near an edge changes
     with the pan. */
  function edgeAnchor() {
    if (!state.map) return;
    const w = state.map.getSize().x;
    state.markers.forEach(m => {
      const chip = m.getElement()?.querySelector(".mchip");
      if (!chip) return;
      const x = state.map.latLngToContainerPoint(m.getLatLng()).x;
      chip.classList.toggle("at-l", x < 90);
      chip.classList.toggle("at-r", x > w - 90);
    });
  }

  function drawMap() {
    const host = el("map");
    if (!host) return;
    if (!window.L) {
      host.innerHTML = `<div class="map-note">map unavailable — leaflet did not load. The list is unaffected.</div>`;
      return;
    }
    host.innerHTML = `<div class="fview-map"></div>`;
    const canvas = host.querySelector(".fview-map");
    // The view is set here, not left to drawPins' fitBounds. A leaflet map with no
    // view yet throws out of every geometry read (getPixelOrigin, getCenter), and
    // edgeAnchor does one per marker BEFORE the fit runs — so on any area that had
    // pins the first draw threw, the tile layer never got a view, and the panel was
    // blank with only the zoom buttons on it.
    state.map = L.map(canvas, { scrollWheelZoom: true, attributionControl: false })
      .setView([state.area.lat ?? 40.7, state.area.lng ?? -73.95], 11);
    hubBasemap(state.map);
    state.pinLayer = L.layerGroup().addTo(state.map);
    // Groups reshuffle on every zoom and pan, so the stack is recomputed rather than kept.
    state.map.on("moveend zoomend", edgeAnchor);
    // Back to the whole area, for the same reason the trips maps have one: a food
    // board is thirty pins across a borough and two drags loses half of them. It
    // re-runs the FIT, not a redraw — the pins on screen are already the right pins,
    // and rebuilding them would drop the overlay and the open place panel with it.
    addRecenter(canvas, () => fitPins(visiblePins()));
    drawPins(true);
  }

  /* The frame the map opens on, split out of drawPins so the recenter button can
     ask for it again without redrawing anything. */
  function visiblePins() {
    return state.places.filter(p => matches(p, state.filters) && p.lat !== null && p.lng !== null);
  }
  function fitPins(pins) {
    if (!state.map) return;
    if (pins.length) state.map.fitBounds(pins.map(p => [p.lat, p.lng]),
                                         { padding: [40, 40], maxZoom: 15, animate: false });
    else state.map.setView([state.area.lat ?? 40.7, state.area.lng ?? -73.95], 11);
  }
  /* ponytail: a plain positioned button, styled by css/map.css alongside the zoom
     bar. A leaflet L.Control is a class, a factory and an onAdd for one button that
     never moves from the corner. disableClickPropagation is not optional — leaflet
     listens for drag on the container, so without it the press starts a pan under
     the pointer and never registers as a click. */
  function addRecenter(host, refit) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "map-recenter";
    b.title = "back to the whole area";
    b.setAttribute("aria-label", "recenter the map");
    b.textContent = "\u2316";
    b.onclick = ev => { ev.preventDefault(); ev.stopPropagation(); refit(); };
    if (window.L && L.DomEvent) {
      L.DomEvent.disableClickPropagation(b);
      L.DomEvent.disableScrollPropagation(b);
    }
    host.appendChild(b);
  }

  function drawPins(fit) {
    if (!state.map) return;
    clearOverlay();          // the markers it highlighted are about to be replaced
    state.pinLayer.clearLayers();
    state.markers.clear();
    const pins = visiblePins();

    pins.forEach(p => {
      const m = L.marker([p.lat, p.lng], { icon: markIcon(p), title: p.name })
        .on("click", () => showPlace(p.slug));
      state.markers.set(p.slug, m);
      state.pinLayer.addLayer(m);
    });
    edgeAnchor();

    if (fit) fitPins(pins);
  }

  /* ------------------------------------------------------------ overlay ---
     Pointing at a child area shows where it is. A name in a list does not tell you Red
     Hook is the peninsula.

     The shape is the hull of that child's own places, not its civic boundary. Two
     reasons: the boundary needs a stored polygon nobody has fetched, and the hull
     answers the question the page is actually about, which is where this area's food
     is. Its own honesty is that it can only ever cover places we know about. */

  const OVERLAY_STYLE = { className: "area-overlay", weight: 2, dashArray: "5 4",
                          fillOpacity: 0.12, interactive: false };

  const centroid = pts => [
    pts.reduce((s, p) => s + p[0], 0) / pts.length,
    pts.reduce((s, p) => s + p[1], 0) / pts.length,
  ];

  /* Monotone chain. `cross <= 0` drops collinear points, which is also the degenerate
     test: a collinear or coincident set cannot produce three vertices, so it falls
     through to the circle. Point count alone would not catch it — four live Denver
     places sit on the exact same coordinate, the city centroid a failed geocode fell
     back to. */
  function hullOf(pts) {
    if (pts.length < 3) return null;
    const P = pts.map(([lat, lng]) => [lng, lat]).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    const half = src => src.reduce((h, p) => {
      while (h.length >= 2 && cross(h[h.length - 2], h[h.length - 1], p) <= 0) h.pop();
      h.push(p);
      return h;
    }, []);
    const ring = half(P).slice(0, -1).concat(half([...P].reverse()).slice(0, -1));
    return ring.length < 3 ? null : ring.map(([lng, lat]) => [lat, lng]);
  }

  /* Push each vertex out from the centre so pins sit inside the edge rather than on it.
     ponytail: a metre offset applied per-vertex, not a real polygon buffer — good enough
     at neighborhood scale; swap in a buffering library if a concave area ever needs one. */
  function padRing(ring, metres) {
    const c = centroid(ring);
    const k = Math.cos(c[0] * Math.PI / 180) || 1;
    return ring.map(([lat, lng]) => {
      const dy = lat - c[0], dx = (lng - c[1]) * k;
      const d = Math.hypot(dx, dy) || 1;
      return [lat + (metres / 111320) * dy / d, lng + (metres / 111320) * dx / d / k];
    });
  }

  const metresBetween = (a, b) => Math.hypot(
    (a[0] - b[0]) * 111320,
    (a[1] - b[1]) * 111320 * Math.cos(a[0] * Math.PI / 180));

  const inMember = (p, m) =>
    p.city === m.city
    && (!("borough" in m) || (m.borough === null
        ? !String(p.borough || "").trim() : p.borough === m.borough))
    && (!("neighborhood" in m) || p.neighborhood === m.neighborhood);

  function clearOverlay() {
    if (state.overlay) { state.map.removeLayer(state.overlay); state.overlay = null; }
    el("map")?.querySelector(".fview-map")?.classList.remove("map-silhouette");
    // The view was borrowed to show the shape, so it goes back. Only ever set by
    // showOverlay, so a clear with no overlay up leaves the map exactly where it is.
    if (state.homeView) {
      state.map.flyTo(state.homeView.c, state.homeView.z, { duration: 0.4 });
      state.homeView = null;
    }
  }

  function showOverlay(member) {
    if (!state.map || !member) return;
    clearOverlay();
    const pts = [...new Map(state.places
      .filter(p => inMember(p, member) && p.lat !== null && p.lng !== null)
      .map(p => [`${p.lat},${p.lng}`, [p.lat, p.lng]])).values()];
    if (!pts.length) return;                     // card says "no places mapped yet"

    const hull = hullOf(pts);
    state.overlay = hull
      ? L.polygon(padRing(hull, 60), OVERLAY_STYLE)
      : L.circle(centroid(pts), {
          ...OVERLAY_STYLE,
          radius: Math.max(150, ...pts.map(p => metresBetween(centroid(pts), p))),
        });
    state.overlay.addTo(state.map);
    // Drawing it is not showing it. A city is fitted to every place it holds, and at that
    // zoom a neighborhood hull is a dozen pixels across — the shape was on the map the
    // whole time and simply could not be seen, which reads as nothing highlighted. So the
    // map goes to the shape while the pointer is held, and clearOverlay brings it back.
    if (!state.homeView) state.homeView = { c: state.map.getCenter(), z: state.map.getZoom() };
    state.map.flyToBounds(state.overlay.getBounds(), { padding: [60, 60], maxZoom: 14, duration: 0.5 });
    // Pins go away entirely while an area is held. The question being asked is "where is
    // this area", and eighty numbered pins are the answer to a different one.
    el("map")?.querySelector(".fview-map")?.classList.add("map-silhouette");
  }

  /* Delegated hover with a 220ms leave delay: moving from one card to the next fires
     pointerout before pointerover, so without it every step would flash the overlay off
     and back on. focusin/focusout ride along because the cards are focusable. */
  let overlayT = null;
  const overlayTarget = e => e.target.closest?.("[data-member]");

  function wireOverlay(host) {
    if (!host || host.dataset.fvOverlay) return;
    host.dataset.fvOverlay = "1";
    host.addEventListener("pointerover", e => {
      const n = overlayTarget(e);
      if (n) { clearTimeout(overlayT); showOverlay(JSON.parse(n.dataset.member)); }
    });
    host.addEventListener("focusin", e => {
      const n = overlayTarget(e);
      if (n) { clearTimeout(overlayT); showOverlay(JSON.parse(n.dataset.member)); }
    });
    ["pointerout", "focusout"].forEach(evt => { host.addEventListener(evt, e => {
      if (!overlayTarget(e)) return;
      clearTimeout(overlayT);
      overlayT = setTimeout(clearOverlay, 220);
    }); });
  }

  /* ------------------------------------------------------------- detail --- */

  async function showPlace(slug) {
    state.selected = slug;
    let p;
    try { p = await state.api.place(slug); }
    catch (e) { return fail(e, "this place"); }

    const lit = p.evidence.filter(e => e.cohort === "literate");
    const rest = p.evidence.filter(e => e.cohort !== "literate");
    // The list rows carry these counts as columns; the detail already has the whole
    // ledger in hand, so it counts what it is about to render rather than trusting a
    // second source for the same number.
    p.literate_count = lit.length;
    p.evidence_count = p.evidence.length;

    const practical = parseJSON(p.practical, {});
    const stale = p.practical_checked && (Date.now() - Date.parse(p.practical_checked)) > STALE_MS;
    const order = parseJSON(p.order_this, []);
    const pros = parseJSON(p.pros, []);
    const cons = parseJSON(p.cons, []);
    const maps = p.address
      ? `<a class="detail-maps" target="_blank" rel="noreferrer"
           href="https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${p.name} ${p.address}`)}">maps</a>`
      : "";

    const col = el("detail");
    el("sidePane")?.classList.add("has-detail");
    col.innerHTML = `
      <div class="detail">
        <div class="detail-head">
          <button class="detail-back" id="fvDetailBack" aria-label="close">✕</button>
          <div class="detail-title">
            <h2>${esc(p.name)}</h2>
            <span class="addr">${esc(p.address || "")}</span>
          </div>
          ${maps}
        </div>
        <div class="detail-body">
          <div class="score-pair">
            <div class="score-cell">
              <span class="axis">depth</span>
              ${depthBlock(p)}
              <span class="axis-note">how real it is within ${esc(p.cuisine_specific || "its tradition")}</span>
            </div>
            <div class="score-cell">
              <span class="axis">execution</span>
              ${execBlock(p)}
              <span class="axis-note">how well it does what it is going for</span>
            </div>
          </div>

          <p class="summary">${esc(p.summary)}</p>

          <div class="sec"><h3>identity</h3>
            <div class="idrow">
              <span class="chip chip-cuisine" title="${esc(p.cuisine_specific || p.cuisine_broad || "")}">${esc(p.cuisine_specific || "—")}</span>
              ${parseJSON(p.cuisines_extra, []).map(c => `<span class="chip chip-cuisine" title="${esc(c)}">${esc(c)}</span>`).join("")}
              ${p.price_band ? `<span class="chip chip-price">${esc(p.price_band)}</span>` : ""}
              <span class="mark mark-${esc(p.discovery)}">${esc(p.discovery)}</span>
              ${statusFlag(p)}
            </div>
          </div>

          ${order.length ? `<div class="sec"><h3>order this</h3><ul class="order">
            ${order.map(o => `<li><span class="dish">${esc(o.dish ?? o)}</span><span class="why">${esc(o.why ?? "")}</span></li>`).join("")}
          </ul></div>` : ""}

          ${pros.length ? `<div class="sec"><h3>pros</h3><ul class="pros">${pros.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>` : ""}
          ${cons.length ? `<div class="sec"><h3>cons</h3><ul class="cons">${cons.map(x => `<li>${esc(x)}</li>`).join("")}</ul></div>` : ""}

          <div class="sec"><h3>practical
            ${p.practical_checked ? `<span class="stamp${stale ? " stale" : ""}">checked ${esc(p.practical_checked)}${stale ? " — over 90 days, re-check before you go" : ""}</span>` : ""}
          </h3>
            <ul class="pc">${Object.entries(practical).length
              ? Object.entries(practical).map(([k, v]) =>
                  `<li><span class="k">${esc(k.replace(/_/g, " "))}</span><span>${esc(typeof v === "boolean" ? (v ? "yes" : "no") : v)}</span></li>`).join("")
              : `<li><span class="score-none">nothing checked yet</span></li>`}</ul>
          </div>

          <div class="sec"><h3>evidence <span class="stamp">${lit.length} literate · ${rest.length} other</span></h3>
            ${p.evidence.length
              ? `<div class="ledger">${lit.map(quoteHTML).join("")}${rest.map(quoteHTML).join("")}</div>`
              : `<p class="score-none">No quotes were recorded for this place. Both scores are withheld.</p>`}
          </div>
        </div>
      </div>`;

    col.querySelector("#fvDetailBack").addEventListener("click", backToList);
    if (state.onSelect) state.onSelect(slug);
    renderFocus();          // repaint the list so the selected row reads as selected
    drawPins();
    // The map just lost height to the detail, so Leaflet has to be told.
    if (state.map) state.map.invalidateSize();
    const m = state.markers.get(slug);
    if (m && state.map) state.map.setView(m.getLatLng(), Math.max(state.map.getZoom(), 15), { animate: true });
  }

  function quoteHTML(e) {
    return `<div class="ev ev-${esc(e.cohort)} ev-polarity-${esc(e.polarity)}">
      <blockquote>${esc(e.quote)}</blockquote>
      ${e.cohort_reason ? `<p class="why">${esc(e.cohort_reason)}</p>` : ""}
      <div class="ev-foot">
        <span class="ev-cohort">${esc(e.cohort)}</span>
        <a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.source)}</a>
        ${e.author ? `<span class="who">${esc(e.author)}</span>` : ""}
        ${e.dated ? `<span class="who">${esc(e.dated)}</span>` : ""}
      </div>
    </div>`;
  }

  function backToList() {
    state.selected = null;
    el("sidePane")?.classList.remove("has-detail");
    el("detail").innerHTML = "";
    if (state.onSelect) state.onSelect(null);
    renderFocus();
    drawPins();
    if (state.map) state.map.invalidateSize();
  }

  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && state.selected) backToList();
  });

  /* --------------------------------------------------------------- mount --- */

  /* opts:
       els      {rail, head, list, map, detail, sidePane} — where the view draws
       data     {area, children, places, portal?} straight off either endpoint
       api      {place(slug) -> place with .evidence}
       navigate optional fn(childSlugOrName). Present = the caller handles child
                areas itself (the trips board filters in place, because the public
                mirror has no /food to link to). Absent = they render as links.
       onSelect optional fn(slug|null), fired when the detail opens or closes.
       compact  the rail is a slot inside someone else's nav, not the page. Drops the
                areas-within list (the "areas within" tab already holds that set) and
                starts the filters closed, so the host's own nav stays on screen. */
  function mount(opts) {
    state.els = opts.els;
    // The trips board's guest CSS hides every button inside the list and the detail
    // pane, because on that board a button is an edit affordance. Here it is a place
    // to open and a filter to clear: this file has no POST in it and its routes are
    // GET-only, so nothing it draws can change anything. Marking the elements it owns
    // is what lets that stylesheet's deny-by-default rule skip exactly this subtree
    // and keep applying to the board around it.
    Object.values(state.els).forEach(e => { e?.classList.add("fview-own"); });
    state.api = opts.api;
    state.navigate = opts.navigate || null;
    state.onSelect = opts.onSelect || null;
    state.compact = !!opts.compact;
    state.area = opts.data.area;
    state.children = opts.data.children || [];
    state.places = opts.data.places || [];
    state.portal = opts.data.portal || null;
    state.scene = parseScene(state.area.scene);
    state.selected = null;
    state.map = null; state.pinLayer = null; state.overlay = null;
    state.homeView = null; state.markers = new Map();
    state.filters = { hood: "", broad: "", specific: "", price: new Set(), discovery: new Set(), minDepth: 0, q: "" };
    // The rundown is the whole view when there is nothing else in it yet.
    state.view = state.places.length ? "places" : (state.scene.city.length ? "city" : "places");

    el("sidePane")?.classList.remove("has-detail");
    if (el("detail")) el("detail").innerHTML = "";
    wireOverlay(el("rail"));
    wireOverlay(el("list"));

    renderRail();
    renderFocus();
    drawMap();
  }

  // Filtering to one child area. The trips board has no second page to open, so a
  // child is a filter here rather than a destination — same set of places either way.
  function filterToChild(nameOrSlug) {
    const child = state.children.find(c => c.slug === nameOrSlug || c.name === nameOrSlug);
    if (!child) return;
    const m = child.member || {};
    state.filters.hood = m.neighborhood || (child.level === "neighborhood" ? child.name : "");
    if (!state.filters.hood && child.level === "borough") {
      // A borough has no hood filter of its own; fall back to showing everything and
      // letting the map's overlay carry where it is.
      state.filters.hood = "";
    }
    state.view = "places";
    refresh();
  }

  function teardown() {
    Object.values(state.els || {}).forEach(e => { e?.classList.remove("fview-own"); });
    if (state.map) { state.map.remove(); state.map = null; }
    state.markers.clear();
    state.selected = null;
    state.els = null;
  }

  window.FoodView = { mount, teardown, close: backToList, filterToChild, esc, scored };
})();
