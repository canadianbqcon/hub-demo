/* Address autofill: a dropdown of real addresses under a text input.
 *
 * Two pages need this and neither can own it. The guest account page runs on
 * Hub AND on the public mirror; the access panel runs on every Hub page. This
 * file sits in the trips blueprint's static folder because that is the one
 * directory both apps serve, and it is self-contained — it injects its own
 * styles, builds its own list, and needs nothing from the page but an <input>.
 *
 * Why a listbox we own rather than <datalist>: the datalist popup is browser
 * chrome, so it ignores the page's theme, cannot be styled, renders differently
 * in every browser, and on some only opens once the field already matches.
 *
 * The list is appended to <body>, not beside the input, and positioned fixed
 * from the input's rect. Both consumers would otherwise break it: the account
 * page's sections run an entrance animation with `fill-mode: both`, so
 * `transform: none` stays applied as the identity matrix and every section is
 * its own containing block AND stacking context; the access panel's body is a
 * 60vh scroller that would clip a dropdown on any row near the bottom.
 */
window.AddrCombo = (() => {
  // 450ms of quiet, not a request per keystroke: the lookup holds a shared
  // rate floor server-side, so a per-keystroke typeahead would queue behind
  // itself and land answers for a query three letters stale. `seq` drops those
  // anyway if one ever overtakes.
  var WAIT = 450, seq = 0, uid = 0, styled = false;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function style() {
    if (styled) return;
    styled = true;
    var el = document.createElement("style");
    el.textContent =
      ".acombo-list{position:fixed;z-index:2000;margin:0;padding:4px;list-style:none;" +
        "background:var(--bg-elev,#fff);border:1px solid var(--line,#ccc);" +
        "border-radius:var(--r,6px);box-shadow:0 8px 24px rgba(0,0,0,.28);" +
        "overflow-y:auto;}" +
      ".acombo-list[hidden]{display:none;}" +
      ".acombo-opt{padding:6px 8px;border-radius:calc(var(--r,6px) - 2px);cursor:pointer;" +
        "font-size:var(--fs-footnote);color:var(--fg,#111);white-space:nowrap;overflow:hidden;" +
        "text-overflow:ellipsis;}" +
      ".acombo-opt.is-at{background:var(--accent,#3b6);color:var(--on-accent,#fff);}";
    document.head.appendChild(el);
  }

  function attach(input) {
    if (!input || input.dataset.acombo) return;
    input.dataset.acombo = "1";
    style();

    var list = document.createElement("ul");
    list.className = "acombo-list";
    list.id = `acombo${++uid}`;
    list.setAttribute("role", "listbox");
    list.hidden = true;
    document.body.appendChild(list);

    // The browser's own saved-address popup would open over ours, and only one
    // of the two writes the postal shape this field exists to enforce.
    input.setAttribute("autocomplete", "off");
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-autocomplete", "list");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-controls", list.id);

    var items = [], at = -1, timer = 0;

    /* Fixed means the viewport is the whole budget: the list cannot be scrolled
       to the way an absolutely-positioned one could, so it has to fit on screen
       by itself. It opens downward, flips above the input when there is not
       room below, and clamps its height to whichever side it took. The account
       page is why — the address is the LAST field there, so downward-only put
       the suggestions off the bottom edge with no way to reach them. */
    var ROOM = 96;

    function place() {
      var r = input.getBoundingClientRect();
      var below = window.innerHeight - r.bottom - 8;
      var above = r.top - 8;
      var up = below < ROOM && above > below;
      var room = Math.max(ROOM, up ? above : below);
      list.style.left = `${r.left}px`;
      list.style.width = `${r.width}px`;
      list.style.maxHeight = `${Math.min(room, 272)}px`;
      if (up) {
        list.style.top = "auto";
        list.style.bottom = `${window.innerHeight - r.top + 2}px`;
      } else {
        list.style.bottom = "auto";
        list.style.top = `${r.bottom + 2}px`;
      }
    }

    // Closing hides the list and drops the highlight, but KEEPS `items`. Two
    // things depend on the last answers outliving the close: ArrowDown reopens
    // them instead of making you retype, and the input handler recognises a
    // pick by matching against them. Clearing here is what made a pick look
    // like typing, so 450ms later it searched the address back and reopened the
    // list under the answer. Only a new search replaces them.
    function close() {
      list.hidden = true;
      list.innerHTML = "";
      at = -1;
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
    }

    function open(results) {
      if (results) items = results;   // reopening passes nothing and reuses them
      at = -1;
      if (!items.length) { close(); return; }
      list.innerHTML = items.map((a, i) => '<li class="acombo-opt" role="option" id="' + list.id + "o" + i + '"'
          + ' aria-selected="false" data-i="' + i + '">' + esc(a) + "</li>").join("");
      place();
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
    }

    // aria-activedescendant rather than moving focus: focus has to stay in the
    // input or the caret leaves and typing stops working mid-selection.
    function highlight(i) {
      var opts = list.querySelectorAll(".acombo-opt");
      if (at >= 0 && opts[at]) {
        opts[at].classList.remove("is-at");
        opts[at].setAttribute("aria-selected", "false");
      }
      at = i;
      if (at < 0 || !opts[at]) { input.removeAttribute("aria-activedescendant"); return; }
      opts[at].classList.add("is-at");
      opts[at].setAttribute("aria-selected", "true");
      opts[at].scrollIntoView({ block: "nearest" });
      input.setAttribute("aria-activedescendant", opts[at].id);
    }

    function pick(i) {
      if (i < 0 || i >= items.length) return;
      input.value = items[i];
      // Setting .value raises no event, so anything the page hangs off `input`
      // (a save bar, a dirty flag) would miss the one change that did not come
      // from a keystroke. The handler below sees it as a pick, not as typing.
      input.dispatchEvent(new Event("input", { bubbles: true }));
      close();
      input.focus();
    }

    async function search(q) {
      var mine = ++seq;
      try {
        const r = await fetch(`/trips/api/prefs/address-search?q=${encodeURIComponent(q)}`);
        const out = await r.json();
        if (mine !== seq) return;   // a later keystroke already won
        // An empty answer LEAVES the list alone rather than clearing it. Typing
        // through a word passes prefixes nothing can match ("350 5t" between
        // "350 5" and "350 5th"), and blanking on those made the list flicker
        // shut and open again on nearly every word. Stale-by-one-letter beats
        // gone, and the next keystroke replaces it either way.
        if ((out.results || []).length) open(out.results);
      } catch {
        // The field is optional and hand-typing it still works, so a dead
        // lookup goes quiet rather than putting an error under a working input.
        if (mine === seq) close();
      }
    }

    input.addEventListener("input", () => {
      var q = input.value.trim();
      clearTimeout(timer);
      // A pick sets .value and re-fires input (see above); searching that back
      // would spend a request to be told the box already holds the answer.
      if (items.indexOf(q) !== -1) return;
      if (q.length < 3) { close(); return; }
      timer = setTimeout(() => { search(q); }, WAIT);
    });

    input.addEventListener("keydown", (ev) => {
      if (list.hidden) {
        // ArrowDown on a closed list reopens the last answers rather than
        // making you retype to see them again.
        if (ev.key === "ArrowDown" && items.length) { open(); highlight(0); ev.preventDefault(); }
        return;
      }
      if (ev.key === "ArrowDown") { highlight((at + 1) % items.length); ev.preventDefault(); }
      else if (ev.key === "ArrowUp") { highlight((at - 1 + items.length) % items.length); ev.preventDefault(); }
      // Enter with nothing highlighted must fall through to the page, not be
      // swallowed by a list the reader was ignoring. With something highlighted
      // it picks and the page's own Enter handler still runs, so a field that
      // commits on Enter commits the picked value.
      else if (ev.key === "Enter" && at >= 0) { pick(at); ev.preventDefault(); }
      // Escape closes the list and stops there. The access panel reverts the
      // field on Escape, which would throw away what you were typing when you
      // only meant to dismiss the suggestions.
      else if (ev.key === "Escape") { close(); ev.preventDefault(); ev.stopImmediatePropagation(); }
      else if (ev.key === "Tab") { close(); }
    });

    // mousedown, not click: blur fires first on a click and would close the list
    // out from under the pointer, so the option is gone before the click lands.
    list.addEventListener("mousedown", (ev) => {
      var li = ev.target.closest(".acombo-opt");
      if (!li) return;
      ev.preventDefault();
      pick(Number(li.dataset.i));
    });
    list.addEventListener("mousemove", (ev) => {
      var li = ev.target.closest(".acombo-opt");
      if (li) highlight(Number(li.dataset.i));
    });
    input.addEventListener("blur", () => { setTimeout(close, 120); });

    // The list is fixed and lives on <body>, so anything that moves the input
    // has to move it too. Capture, because the access panel scrolls its own
    // body rather than the window.
    window.addEventListener("scroll", () => { if (!list.hidden) place(); }, true);
    window.addEventListener("resize", () => { if (!list.hidden) place(); });
  }

  return { attach: attach };
})();
