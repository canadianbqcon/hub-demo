/* hub · address autofill combobox (2026-10-13): React port of addr-combo.js. HubUI.AddrCombo is a
   controlled text input with a listbox of real addresses under it. Same DOM and classes as the
   plain file: the input carries the combobox roles, the list is a <ul class="acombo-list"> on
   <body> (fixed, placed from the input's rect, flipping above when there is no room below), and
   the plain file's styles are injected once. The plain addr-combo.js stays for the access panel.
   HubUI may already exist (basemap.jsx creates it too), so the guard is the same one. */
window.HubUI = window.HubUI || {};
(() => {
const { useState, useRef, useEffect, useLayoutEffect } = React;

// 450ms of quiet, not a request per keystroke: the lookup holds a shared rate floor server-side,
// so a per-keystroke typeahead would queue behind itself. `seq` drops answers that were overtaken.
const WAIT = 450, ROOM = 96;
let seq = 0, uid = 0, styled = false;

function style() {
  if (styled) return;
  styled = true;
  const el = document.createElement("style");
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

/* props: id, value, onChange(string), maxLength. The page owns the value; picking an
   option hands the address to onChange exactly as typing would. */
function AddrCombo({ id, value, onChange, maxLength }) {
  const [listId] = useState(() => { style(); uid += 1; return `acombo${uid}`; });
  const inputRef = useRef(null), listRef = useRef(null);
  const timer = useRef(0);
  // items outlive a close: ArrowDown reopens them, and a pick is recognised by matching them
  const itemsRef = useRef([]);
  const [open, setOpen] = useState(false);
  const [at, setAt] = useState(-1);
  const [items, setItems] = useState([]);

  const close = () => { setOpen(false); setAt(-1); };
  const show = (results) => {
    if (results) { itemsRef.current = results; setItems(results); }   // reopening passes nothing
    setAt(-1);
    if (!itemsRef.current.length) { close(); return; }
    setOpen(true);
  };

  /* Fixed means the viewport is the whole budget: opens downward, flips above the input when
     there is not room below, and clamps its height to whichever side it took. */
  const place = () => {
    const input = inputRef.current, list = listRef.current;
    if (!input || !list) return;
    const r = input.getBoundingClientRect();
    const below = window.innerHeight - r.bottom - 8;
    const above = r.top - 8;
    const up = below < ROOM && above > below;
    const room = Math.max(ROOM, up ? above : below);
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
  };
  useLayoutEffect(() => { if (open) place(); }, [open, items]);
  // the list is fixed on <body>, so anything that moves the input has to move it too (capture:
  // the access panel scrolls its own body)
  useEffect(() => {
    if (!open) return undefined;
    const move = () => { place(); };
    window.addEventListener("scroll", move, true);
    window.addEventListener("resize", move);
    return () => { window.removeEventListener("scroll", move, true); window.removeEventListener("resize", move); };
  }, [open]);
  // aria-activedescendant rather than moving focus: the caret has to stay in the input
  useEffect(() => {
    if (open && at >= 0 && listRef.current?.children[at]) {
      listRef.current.children[at].scrollIntoView({ block: "nearest" });
    }
  }, [at, open]);
  useEffect(() => () => { clearTimeout(timer.current); }, []);

  const search = (q) => {
    seq += 1;
    const mine = seq;
    fetch(`/trips/api/prefs/address-search?q=${encodeURIComponent(q)}`)
      .then((r) => r.json())
      .then((out) => {
        if (mine !== seq) return;   // a later keystroke already won
        // An empty answer LEAVES the list alone: typing through a word passes prefixes nothing
        // can match, and blanking on those made the list flicker shut and open again.
        if ((out.results || []).length) show(out.results);
      })
      // the field is optional and hand-typing still works, so a dead lookup goes quiet
      .catch(() => { if (mine === seq) close(); });
  };

  const pick = (i) => {
    if (i < 0 || i >= itemsRef.current.length) return;
    clearTimeout(timer.current);
    onChange(itemsRef.current[i]);
    close();
    if (inputRef.current) inputRef.current.focus();
  };

  const typed = (ev) => {
    const v = ev.target.value;
    onChange(v);
    const q = v.trim();
    clearTimeout(timer.current);
    if (itemsRef.current.indexOf(q) !== -1) return;   // a pick, not typing
    if (q.length < 3) { close(); return; }
    timer.current = setTimeout(() => { search(q); }, WAIT);
  };

  const keys = (ev) => {
    const n = itemsRef.current.length;
    if (!open) {
      // ArrowDown on a closed list reopens the last answers rather than making you retype
      if (ev.key === "ArrowDown" && n) { show(); setAt(0); ev.preventDefault(); }
      return;
    }
    if (ev.key === "ArrowDown") { setAt((at + 1) % n); ev.preventDefault(); }
    else if (ev.key === "ArrowUp") { setAt((at - 1 + n) % n); ev.preventDefault(); }
    // Enter with nothing highlighted falls through to the page
    else if (ev.key === "Enter" && at >= 0) { pick(at); ev.preventDefault(); }
    // Escape closes the list and stops there, so a page-level Escape does not also fire
    else if (ev.key === "Escape") { close(); ev.preventDefault(); ev.nativeEvent.stopImmediatePropagation(); }
    else if (ev.key === "Tab") { close(); }
  };

  const active = open && at >= 0 ? `${listId}o${at}` : undefined;
  return (
    <>
      <input id={id} type="text" maxLength={maxLength} value={value} onChange={typed} onKeyDown={keys}
        onBlur={() => { setTimeout(close, 120); }}
        autoComplete="off" role="combobox" aria-autocomplete="list" aria-expanded={open ? "true" : "false"}
        aria-controls={listId} aria-activedescendant={active} data-acombo="1" ref={inputRef} />
      {ReactDOM.createPortal(
        <ul className="acombo-list" id={listId} role="listbox" hidden={!open} ref={listRef}>
          {open && items.map((a, i) => (
            // mousedown, not click: blur fires first on a click and would close the list under the pointer
            <li key={i} className={`acombo-opt${at === i ? " is-at" : ""}`} role="option" id={`${listId}o${i}`}
              aria-selected={at === i ? "true" : "false"} data-i={i}
              onMouseDown={(ev) => { ev.preventDefault(); pick(i); }} onMouseMove={() => { setAt(i); }}>{a}</li>
          ))}
        </ul>, document.body)}
    </>
  );
}

HubUI.AddrCombo = AddrCombo;
})();
