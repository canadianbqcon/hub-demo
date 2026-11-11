/* workbench body, part 2 (React): the sign-off writes (decide, option pick/fork/delete), the option-set
   cards, the stage track and carousel, the order lock and the marks walk-through. Ported from
   workbench.js lines 144-370 and 479-612 and 912-963: same DOM, classes and request bodies.
   The doc hash rides every write as rendered_sha256, exactly as the plain page sent it (the server
   passes it to store.record as expected_sha256). Needs workbench-docs.jsx first (UI.S, the cards) and
   workbench.jsx after it (UI.refresh, UI.reopen, UI.selectBuild, the mount). */
(() => {
  const UI = window.WorkbenchUI;
  const { useState, useRef, useLayoutEffect } = React;
  const { S, API, setStatus, hold, PlateCard, ActBtn, CardStrip, VerdictPill, DocCards } = UI;

  const JSON_HEADERS = { "Content-Type": "application/json" };
  const msgOf = (e) => String((e?.message) || e);

  /* POST a held write. fetch rejects only when no response came back: on this box that is the Hub
     restarting (other sessions restart it often; it takes ~10 s to listen again). A write that hit
     that gap used to revert with one line in the status bar, which read as the pick resetting
     (2026-11-11, league-overlay-card F). So it retries every 2 s for a minute before giving up.
     An HTTP error is an answer, never retried. */
  const RETRY_MS = 2000, RETRY_FOR_MS = 60000;
  function post(url, body, label) {
    const t0 = Date.now();
    const once = () => fetch(url, { method: "POST", headers: JSON_HEADERS, keepalive: true, body: JSON.stringify(body) })
      .catch((e) => {
        if (Date.now() - t0 >= RETRY_FOR_MS) throw new Error(`the Hub did not answer for a minute; ${label} not recorded`);
        setStatus(`the Hub is restarting; ${label} will send when it is back…`);
        return new Promise((ok) => { setTimeout(ok, RETRY_MS); }).then(once);
      });
    return once();
  }

  // ── writes ───────────────────────────────────────────────────────────────

  /* The ledger row a write will record, drawn now so the click lands at once. It sits in S.pend,
     which every ledger load re-appends, until its write settles: the server's row then replaces it.
     Returns [settle, revert]; revert takes it back after an undo or a failed write. */
  function provisional(row) {
    const r = Object.assign({ seq: Number.MAX_SAFE_INTEGER, decided_at: new Date().toISOString().slice(0, 19).replace("T", " ") }, row);
    S.pend.push(r);
    S.history = S.history.concat([r]);
    UI.redraw();
    const settle = () => { S.pend = S.pend.filter((x) => x !== r); };
    return [settle, () => { settle(); S.history = S.history.filter((x) => x !== r); UI.redraw(); }];
  }

  // runs before the success refresh's ledger load lands, so the server row takes over cleanly
  const settled = (settle, p) => p.then((row) => { settle(); return row; });

  function decide(doc, step, at, verdict, comment) {
    if (!doc) return;
    const [settle, back] = provisional({ kind: step.kind, doc_path: step.path, build_slug: at.slug, verdict: verdict, comment: comment || null });
    hold(verdict, () => settled(settle, decideNow(doc, step, at, verdict, comment)), back);
  }

  /* Resolves to the recorded row, or null after reporting the failure. */
  function decideNow(doc, step, at, verdict, comment) {
    setStatus(`recording ${verdict}…`);
    // keepalive (in post): a held write sent as the tab closes must outlive it
    return post(`${API}/decide`, {
      slug: step.slug, kind: step.kind, path: step.path,
      rendered_sha256: doc.sha256, verdict: verdict, comment: comment,
    }, verdict).then((r) => {
      if (r.status === 409) {
        // stale page: the doc changed, or it is already approved at this version
        return r.json().catch(() => ({})).then((e) => {
          const why = `${e.error || "this document changed since it was rendered"}; nothing recorded`;
          // reopen refetches the doc and the ledger; a redraw would keep the stale copy
          if (UI.isAt(at)) UI.reopen(at, why); else setStatus(why);
          return null;
        });
      }
      if (!r.ok) return r.json().then((e) => { throw new Error(e.error || "failed"); });
      return r.json();
    }).then((row) => {
      if (row) UI.refresh(at, `${verdict} recorded`);
      return row;
    }).catch((e) => { setStatus(msgOf(e)); return null; });
  }

  // the cards a delete or fork drops leave the grid at the click; the returned function puts them back
  function hideCards(letters) {
    const els = letters.map((L) => document.getElementById(`opt-${L.toLowerCase()}`)).filter(Boolean);
    els.forEach((el) => { el.hidden = true; });
    return () => { els.forEach((el) => { el.hidden = false; }); };
  }

  /* Resolves to the folder's new hash, or null after reporting the failure or his undo. */
  function deleteCards(set, at, letters) {
    set.pending = (set.pending || 0) + 1;
    return hold(`delete ${letters.join(", ")}`, () => deleteNow(set, at, letters), hideCards(letters))
      .then((sha) => { set.pending--; return sha; });
  }

  function idxOf(L) { return /^\d+$/.test(L) ? +L - 1 : L.charCodeAt(0) - 65; }

  /* letters are positions in the render he clicked on. Writes from that render run one after another
     (UI.hold queues them), and each removed card shifts the later ones left, so a second delete is
     mapped through set.gone to where its card sits now, and carries each card's title so the server
     refuses a letter that no longer names that card. */
  function deleteNow(set, at, letters) {
    const gone = set.gone || (set.gone = []);
    const live = letters.filter((L) => gone.indexOf(L) < 0);
    if (!live.length) return Promise.resolve(set.sha256);
    const now = live.map((L) => letter(idxOf(L) - gone.filter((G) => idxOf(G) < idxOf(L)).length));
    setStatus(`deleting ${live.join(", ")}…`);
    return post(`${API}/option/delete`,
      { set: set.slug, letters: now, titles: live.map((L) => (set.titles || [])[idxOf(L)] || ""), sha256: set.sha256 },
      `delete ${live.join(", ")}`).then((r) => {
      if (r.status === 409) { staleSet(at); return null; }
      return r.json().then((b) => {
        if (!r.ok) throw new Error(b.error || "failed");
        gone.push(...live);
        set.sha256 = b.sha256;
        setStatus(`deleted ${live.join(", ")}`);
        return b.sha256;
      });
    }).catch((e) => { setStatus(msgOf(e)); return null; });
  }

  function staleSet(at) {
    if (UI.isAt(at)) UI.reopen(at, "this option set changed since it was rendered; reloaded, nothing recorded");
    else setStatus("that option set changed since it was rendered; nothing recorded");
  }

  function decideSet(set, at, verdict, comment, choice) {
    const [settle, back] = provisional({ kind: "design", doc_path: set.path, build_slug: at.slug, verdict: verdict, comment: comment || null, choice: choice || null });
    hold(choice ? `pick ${choice}` : verdict, () => settled(settle, decideSetNow(set, at, verdict, comment, choice)), back);
  }

  /* Resolves to the recorded row, or null after reporting the failure. */
  function decideSetNow(set, at, verdict, comment, choice) {
    setStatus(`recording ${choice ? `pick ${choice}` : verdict}…`);
    return post(`${API}/decide`, { slug: set.slug, kind: "design", path: set.path,
      rendered_sha256: set.sha256, verdict: verdict, comment: comment, choice: choice },
      choice ? `pick ${choice}` : verdict).then((r) => {
      if (r.status === 409) {
        // the same pick again is "already approved", not a changed set
        return r.json().catch(() => ({})).then((e) => {
          if (/already approved/.test(e.error || "")) setStatus(`pick ${choice} is already recorded`); else staleSet(at);
          return null;
        });
      }
      if (!r.ok) return r.json().then((e) => { throw new Error(e.error || "failed"); });
      return r.json();
    }).then((row) => {
      if (row) UI.refresh(at, `${choice ? `pick ${choice}` : verdict} recorded`);
      return row;
    }).catch((e) => { setStatus(msgOf(e)); return null; });
  }

  // ── step fetches and the order lock ──────────────────────────────────────

  /* A step's current document or option set, memoised per stage open so the track,
     the lock and the card share one request each. A failure is not kept, so retry refetches. */
  function fetchStep(s) {
    const memo = S.memo;
    if (memo[s.key]) return memo[s.key];
    const url = s.kind === "design" ? `${API}/option?set=${encodeURIComponent(s.key)}` : `${API}/doc?path=${encodeURIComponent(s.path)}`;
    return (memo[s.key] = fetch(url).then((r) => {
      if (!r.ok) throw new Error(s.key);
      return r.json();
    }).catch((e) => { delete memo[s.key]; throw e; }));
  }

  function fetchLedger() {
    const memo = S.memo;
    return memo["#ledger"] || (memo["#ledger"] = fetch(`${API}/history`).then((r) => {
      if (!r.ok) throw new Error("history");
      return r.json();
    }).then((rows) => { S.history = (rows || []).concat(S.pend); }).catch((e) => { delete memo["#ledger"]; throw e; }));
  }

  /* Order lock: unlocked only when every earlier step is approved (an approval is final, edits
     after it do not relock). A ledger fetch that fails keeps it locked (the server never checks
     earlier steps, so missing data must not open it). */
  function lockFor(b, step) {
    const before = b.steps.slice(0, b.steps.indexOf(step));
    return fetchLedger().then(() => {
      for (const s of before) {
        const name = s.kind === "design" ? s.title || s.slug : s.key;
        if (UI.latestRow(s.kind, s.path)?.verdict !== "approved") return { locked: true, note: `approve the ${name} first` };
      }
      return { locked: false, note: "" };
    }, () => ({ locked: true, failed: true, note: "couldn't check the earlier steps" }));
  }

  // ── option-set cards ─────────────────────────────────────────────────────

  function letter(i) { return i < 26 ? String.fromCharCode(65 + i) : String(i + 1); }

  /* The rig chassis: a set's options.html carries bare cards; the page letters
     them in document order and adds the Focus and Pick buttons, so a run never
     hand-writes them. A Pick is a design row with choice = the letter, bound to
     the manifest hash of the whole folder the server sent with this render.
     The cards are server markup, so they are decorated in place after mount and wired with native
     listeners, as the plain page did; React owns the plate, the buttons and the strip. */
  // a preview tab bar sits right before its .lgx-row; show frame k, mark tab k selected
  function showFrame(bar, k) {
    const frames = Array.prototype.filter.call(bar.nextElementSibling.children, (c) => c.matches(".lgx-desk, .lgx-phone"));
    frames.forEach((f, i) => { f.hidden = i !== k; });
    Array.prototype.forEach.call(bar.children, (b, i) => { b.setAttribute("aria-selected", String(i === k)); });
  }

  function OptionCards({ set, step, st, at, locked: orderLocked }) {
    const [n, setN] = useState(0);
    const strip = UI.useStrip(["fork", "back"]);
    const bodyRef = useRef(null);
    const totalRef = useRef(0);
    const pickedRef = useRef(undefined);
    if (pickedRef.current === undefined) {
      let picked = null;
      S.history.forEach((r) => {
        // only an approval is a pick: a send-back on a review card read "approved" and locked it
        if (r.kind === "design" && r.verdict === "approved" && r.doc_path === set.path &&
            (!picked || r.seq > picked.seq)) picked = r;
      });
      pickedRef.current = picked;
    }
    const picked = pickedRef.current;
    // an approval is final: a picked set takes no fork, delete, send back or second pick
    const locked = orderLocked || !!picked;
    const lockRef = useRef(locked);
    lockRef.current = locked;
    // one card is a before/after review, not a choice: no letters, ticks, fork or delete, just approve / send back
    const review = (set.options.match(/<article class="opt\b/g) || []).length === 1;
    const htmlRef = useRef(null);
    if (htmlRef.current === null) {
      htmlRef.current = "<style>" + set.styles + "</style>" +
        '<div class="wb-rig' + (review ? " wb-review" : "") + '">' + set.head + '<div class="wb-grid" id="optGrid">' + set.options + "</div></div>";
    }
    const pickA = () => {
      const h = grid().querySelector(".opt h2");
      if (!lockRef.current) decideSet(set, at, "approved", h ? `title: ${h.textContent.replace(/\s+/g, " ").trim()}` : null, "A");
    };

    const grid = () => bodyRef.current.querySelector("#optGrid");
    // a card hidden by a held delete is gone as far as the ticks go
    const sel = () => Array.prototype.map.call(grid().querySelectorAll(".opt:not([hidden]) [data-sel]:checked"), (c) => c.dataset.sel);
    // what a fork keeps is fixed at the click that opened it, not read again at confirm
    const keepRef = useRef([]);

    /* keep these letters, drop every other card of this render, send back for 4 branches */
    function forkFrom(keep, note) {
      const titles = keep.map((L) => (set.titles || [])[idxOf(L)] || L);
      const drop = [];
      for (let i = 0; i < totalRef.current; i++) if (keep.indexOf(letter(i)) < 0) drop.push(letter(i));
      const comment = `fork: add 4 new options that branch from the kept ones (${titles.join("; ")})${note ? `. Note: ${note}` : ""}`;
      hold(`fork ${keep.join(", ")}`, () => deleteNow(set, at, drop).then((sha) => (
        sha ? decideSetNow(Object.assign({}, set, { sha256: sha }), at, "sent_back", comment, null) : null
      )), hideCards(drop));
    }

    useLayoutEffect(() => {
      const g = grid(), observers = [];
      // the title at each letter of this render, read the way the server reads it (api.py card_title)
      set.titles = Array.prototype.map.call(g.querySelectorAll(".opt"), (opt) => {
        const h = opt.querySelector("h2");
        return h ? h.textContent.replace(/\s+/g, " ").trim() : "";
      });
      Array.prototype.forEach.call(g.querySelectorAll(".opt"), (opt, i) => {
        const L = letter(i);
        opt.id = `opt-${L.toLowerCase()}`;
        opt.dataset.letter = L;
        if (picked && picked.choice === L) opt.classList.add("picked");
        if (review) return;
        const head = document.createElement("div");
        head.className = "opt-head";
        head.innerHTML = `<label class="wb-sel" title="select ${L}"><input type="checkbox" data-sel="${L}" aria-label="select option ${L}"></label><span class="wb-badge">${L}</span>`;
        // title reads as the first line of the description, not the header
        const h2 = opt.querySelector("h2"), spec = opt.querySelector(".spec");
        // collapsed, the card is just this head, so the title rides in it to say which option is folded
        const ft = document.createElement("span");
        ft.className = "wb-fold-t";
        ft.textContent = h2 ? h2.textContent.replace(/\s+/g, " ").trim() : "";
        head.appendChild(ft);
        head.insertAdjacentHTML("beforeend", `<button type="button" class="hub-btn wb-fold" data-fold aria-expanded="true" aria-label="collapse option ${L}" title="collapse ${L}">▾</button>`);
        // tagged: once moved below the stage, a bare querySelector("h2") finds a preview heading first
        if (h2) h2.classList.add("opt-title");
        if (h2 && spec) spec.insertBefore(h2, spec.firstChild);
        opt.insertBefore(head, opt.firstChild);
        // the card's own submission row at its foot: a note box that is always there, then the pick
        const foot = document.createElement("div");
        foot.className = "opt-submit";
        foot.innerHTML = `<textarea class="wb-textarea" data-note="${L}" placeholder="optional note for the build or the fork" aria-label="note for option ${L}"></textarea>` +
          `<div class="opt-acts"><button type="button" class="hub-btn hub-btn--danger" data-del="${L}">delete ${L}</button>` +
          `<button type="button" class="hub-btn" data-fork="${L}">fork ${L}</button>` +
          `<button type="button" class="hub-btn hub-btn--accent" data-pick="${L}">pick ${L}</button></div>`;
        opt.appendChild(foot);
        const stage = opt.querySelector(".stage");
        if (stage) {
          const wrap = document.createElement("div");
          wrap.className = "stage-wrap";
          stage.parentNode.insertBefore(wrap, stage);
          wrap.appendChild(stage);
          const meta = document.createElement("div");
          meta.className = "stage-meta";
          wrap.appendChild(meta);
          const ro = new ResizeObserver((en) => {
            meta.textContent = `stage · ${Math.round(en[0].contentRect.width)}px`;
          });
          ro.observe(stage);
          observers.push(ro);
        }
      });
      // two-frame previews become Desktop / Phone tabs: one frame at a time, at the card's full width
      Array.prototype.forEach.call(g.querySelectorAll(".lgx-row"), (row) => {
        const frames = Array.prototype.filter.call(row.children, (c) => c.matches(".lgx-desk, .lgx-phone"));
        if (frames.length < 2) return;
        const bar = document.createElement("div");
        bar.className = "hub-tabs hub-tabs--segmented wb-lgx-tabs";
        bar.setAttribute("role", "tablist");
        frames.forEach((f, k) => {
          const cap = f.querySelector(".lgx-cap");
          const b = document.createElement("button");
          b.type = "button";
          b.className = "hub-tab";
          b.setAttribute("role", "tab");
          b.textContent = cap ? cap.textContent.trim() : (f.matches(".lgx-phone") ? "Phone" : "Desktop");
          b.dataset.lgx = String(k);
          bar.appendChild(b);
        });
        row.classList.add("wb-tabbed");
        row.parentNode.insertBefore(bar, row);
        showFrame(bar, 0);
      });
      // the pick leads the grid; letters stay in document order, so C still reads C
      const pickedOpt = g.querySelector(".opt.picked");
      if (pickedOpt) g.prepend(pickedOpt);
      // live previews: the real Hub page in an iframe (same origin), with the set's own css and js from
      // its assets/ folder added once it loads. src goes on last: moving an iframe in the DOM reloads it.
      // Each frame boots a whole Hub page (~42 requests), so src waits until the frame is near the
      // viewport and on its open tab (a hidden tab is display:none, which never intersects): all 12 at
      // once was 22 s and 664 requests on 2026-11-03.
      const lazy = new IntersectionObserver((en) => {
        en.forEach((e) => {
          if (!e.isIntersecting) return;
          lazy.unobserve(e.target);
          e.target.src = e.target.dataset.src;
        });
      }, { rootMargin: "400px 0px" });
      observers.push(lazy);
      Array.prototype.forEach.call(g.querySelectorAll("iframe.wb-live[data-src]"), (fr) => {
        const asset = (p) => `${API}/option/asset?set=${encodeURIComponent(set.slug)}&path=${encodeURIComponent(p)}`;
        const list = (a) => (fr.dataset[a] || "").split(/\s+/).filter(Boolean);
        fr.addEventListener("load", () => {
          const doc = fr.contentDocument;
          if (!doc) return;
          list("css").forEach((p) => {
            const l = doc.createElement("link");
            l.rel = "stylesheet";
            l.href = asset(p);
            doc.head.appendChild(l);
          });
          list("js").forEach((p) => {
            const s = doc.createElement("script");
            s.src = asset(p);
            s.async = false; // run in listed order: a shared prototype before the option's own script
            doc.body.appendChild(s);
          });
        });
        lazy.observe(fr);
      });
      totalRef.current = g.querySelectorAll(".opt").length;

      const onChange = (e) => {
        if (!e.target.matches("[data-sel]")) return;
        e.target.closest(".opt").classList.toggle("selected", e.target.checked);
        setN(sel().length);
      };
      const onClick = (e) => {
        const t = e.target.closest("[data-lgx]");
        if (t) { showFrame(t.parentNode, +t.dataset.lgx); return; }
        const f = e.target.closest("[data-fold]");
        if (f) {
          const opt = f.closest(".opt"), L = opt.id.slice(4).toUpperCase(), folded = opt.classList.toggle("folded");
          f.setAttribute("aria-expanded", String(!folded));
          f.setAttribute("aria-label", `${folded ? "expand" : "collapse"} option ${L}`);
          f.title = `${folded ? "expand" : "collapse"} ${L}`;
          return;
        }
        // per-card delete and fork: the letter is the one stamped on this card at this render, the
        // same render the set's hash and titles came from, so it names the card under the click
        const dl = e.target.closest("[data-del]");
        if (dl) {
          if (lockRef.current) return;
          const L = dl.dataset.del, t = (set.titles || [])[idxOf(L)] || L;
          if (g.querySelectorAll(".opt:not([hidden])").length < 2) {
            setStatus("the last option in a set can't be deleted; send it back instead");
            return;
          }
          if (!confirm(`Delete option ${L} "${t}"? The rest re-letter.`)) return;
          deleteCards(set, at, [L]).then((sha) => { if (sha && !set.pending) UI.reopen(at, `deleted ${L} "${t}"`); });
          return;
        }
        const fk = e.target.closest("[data-fork]");
        if (fk) {
          if (lockRef.current) return;
          const L = fk.dataset.fork, t = (set.titles || [])[idxOf(L)] || L;
          const others = g.querySelectorAll(".opt:not([hidden])").length - 1;
          if (!confirm(`Fork from option ${L} "${t}"? Keeps ${L}, drops the other ${others}, and asks for 4 new options that branch from it. The note box on ${L} rides along.`)) return;
          forkFrom([L], fk.closest(".opt").querySelector("[data-note]").value.replace(/\s+/g, " ").trim());
          return;
        }
        const p = e.target.closest("[data-pick]");
        // letters are positions and re-letter after a delete or fork, so the pick also
        // records the card's title: that is what /workbench builds from (workbench cli.py)
        const h = p?.closest(".opt").querySelector(".opt-title");
        // prefixed lines, so the CLI can tell them from other writers' comments (import_rig);
        // the note box beside the button rides along as one line
        if (p && !lockRef.current) {
          const note = p.closest(".opt").querySelector("[data-note]").value.replace(/\s+/g, " ").trim();
          const lines = [];
          if (h) lines.push(`title: ${h.textContent.replace(/\s+/g, " ").trim()}`);
          if (note) lines.push(`note: ${note}`);
          decideSet(set, at, "approved", lines.length ? lines.join("\n") : null, p.dataset.pick);
        }
      };
      g.addEventListener("change", onChange);
      g.addEventListener("click", onClick);
      return () => {
        g.removeEventListener("change", onChange);
        g.removeEventListener("click", onClick);
        observers.forEach((o) => { o.disconnect(); });
      };
    }, []);

    // the order lock also gates the Pick buttons and note boxes the decoration added
    useLayoutEffect(() => {
      Array.prototype.forEach.call(grid().querySelectorAll("[data-pick], [data-note], [data-del], [data-fork]"), (p) => { p.disabled = locked; });
    }, [locked]);

    /* Carousel: one card at a time, full screen. The rig itself goes to the top layer as a popover,
       so no card moves in the DOM: moving an iframe reloads it, and the card listeners stay wired. */
    function carousel() {
      const rig = bodyRef.current.querySelector(".wb-rig");
      const cards = () => Array.prototype.filter.call(grid().querySelectorAll(".opt"), (o) => !o.hidden);
      let i = 0;
      const bar = document.createElement("div");
      bar.className = "wb-car-bar";
      bar.innerHTML = '<button type="button" class="hub-btn" data-car="-1" aria-label="previous option">‹ prev</button>' +
        '<span class="wb-car-t" aria-live="polite"></span>' +
        '<button type="button" class="hub-btn" data-car="1" aria-label="next option">next ›</button>' +
        '<button type="button" class="hub-btn" data-car="x" aria-label="close carousel">close</button>';
      const show = (k) => {
        const c = cards();
        i = (k + c.length) % c.length;
        c.forEach((o, j) => { o.classList.toggle("wb-cur", j === i); });
        const t = c[i].querySelector(".opt-title");
        bar.querySelector(".wb-car-t").textContent = `${c[i].dataset.letter}${t ? ` · ${t.textContent.replace(/\s+/g, " ").trim()}` : ""} · ${i + 1} / ${c.length}`;
        rig.scrollTop = 0;
      };
      const onBar = (e) => {
        const b = e.target.closest("[data-car]");
        if (!b) return;
        if (b.dataset.car === "x") rig.hidePopover(); else show(i + +b.dataset.car);
      };
      // arrows step, Escape closes; typing in a note box keeps its own keys
      const onKey = (e) => {
        if (e.target.closest("textarea, input")) return;
        if (e.key === "ArrowLeft") show(i - 1);
        else if (e.key === "ArrowRight") show(i + 1);
        else if (e.key === "Escape") rig.hidePopover();
        else return;
        e.preventDefault();
      };
      /* swipe: a mostly-sideways drag of 60px steps. A drag that starts on something that scrolls
         sideways (a wide stage) scrolls it instead; touches inside a live preview stay in its iframe. */
      let x0 = null, y0 = 0;
      const scrollsX = (el) => {
        for (; el && el !== rig; el = el.parentElement) if (el.scrollWidth > el.clientWidth + 1 && /auto|scroll/.test(getComputedStyle(el).overflowX)) return true;
        return false;
      };
      const onStart = (e) => {
        x0 = e.touches.length === 1 && !scrollsX(e.target) ? e.touches[0].clientX : null;
        y0 = e.touches[0].clientY;
      };
      const onEnd = (e) => {
        if (x0 === null) return;
        const t = e.changedTouches[0], dx = t.clientX - x0, dy = t.clientY - y0;
        x0 = null;
        if (Math.abs(dx) > 60 && Math.abs(dx) > 2 * Math.abs(dy)) show(i + (dx < 0 ? 1 : -1));
      };
      const onToggle = (e) => {
        if (e.newState !== "closed") return;
        rig.removeEventListener("toggle", onToggle);
        rig.removeEventListener("touchstart", onStart);
        rig.removeEventListener("touchend", onEnd);
        document.removeEventListener("keydown", onKey);
        bar.remove();
        rig.classList.remove("wb-carousel");
        cards().forEach((o) => { o.classList.remove("wb-cur"); });
        rig.removeAttribute("popover");
      };
      bar.addEventListener("click", onBar);
      rig.prepend(bar);
      rig.setAttribute("popover", "manual");
      rig.classList.add("wb-carousel");
      rig.addEventListener("toggle", onToggle);
      rig.addEventListener("touchstart", onStart, { passive: true });
      rig.addEventListener("touchend", onEnd);
      document.addEventListener("keydown", onKey);
      show(0);
      rig.showPopover();
      bar.querySelector('[data-car="1"]').focus();
    }

    const total = totalRef.current;
    const defs = {
      fork: {
        label: "", placeholder: "optional note for the new options", confirmLabel: "confirm fork",
        onConfirm: (note) => {
          const s = keepRef.current;
          // a fork keeps the ticked cards; nothing ticked would drop every card
          if (!s.length) { setStatus("tick at least one option to keep"); return; }
          strip.hide();
          forkFrom(s, note);
        },
      },
      back: {
        label: "reason", placeholder: "what should change…", confirmLabel: "send",
        onConfirm: (cmt) => {
          if (!cmt) { setStatus("a comment is required to send back"); return; }
          decideSet(set, at, "sent_back", cmt, null);
        },
      },
    };

    return (
      <PlateCard title={step.title || step.slug} sum={st.sub + (picked?.choice ? ` · picked ${picked.choice}` : "")}
                 html={htmlRef.current} bodyRef={bodyRef}
                 strip={<CardStrip strip={strip} defs={defs} />}
                 acts={review ? [
                   <ActBtn key="a" label={picked ? "approved" : "approve"} cls="hub-btn--accent" disabled={locked || !!picked} onClick={pickA} />,
                   <ActBtn key="b" label="send back" cls="hub-btn--danger" disabled={locked}
                           onClick={(e) => { strip.show("back", e.currentTarget); }} />,
                 ] : [
                   <ActBtn key="c" label="carousel" onClick={carousel} />,
                   <ActBtn key="f" label={n ? `fork ${n} selected` : "fork selected"} disabled={locked || !n}
                           onClick={(e) => {
                             const s = sel();
                             keepRef.current = s;
                             strip.show("fork", e.currentTarget, `keep ${s.join(", ")}, drop the other ${total - s.length}, and get 4 new options that branch from them`);
                           }} />,
                   <ActBtn key="d" label={n ? `delete ${n} selected` : "delete selected"} disabled={locked || !n || n === total}
                           onClick={() => {
                             const s = sel();
                             if (!confirm(`Delete option${s.length > 1 ? "s" : ""} ${s.join(", ")}? The rest re-letter.`)) return;
                             deleteCards(set, at, s).then((sha) => { if (sha && !set.pending) UI.reopen(at, `deleted ${s.join(", ")}`); });
                           }} />,
                   <ActBtn key="b" label="send back" cls="hub-btn--danger" disabled={locked}
                           onClick={(e) => { strip.show("back", e.currentTarget); }} />,
                 ]} />
    );
  }

  /* The cards of a drawn stage: the order-lock note first, then the doc cards or the option set.
     lock is local so a retry that flips it only re-renders this stage. */
  function StageCards({ stage }) {
    const [lock, setLock] = useState(stage.lock);
    const { step, cur, at, d } = stage;
    return (
      <React.Fragment>
        <div className="wb-lock-note" hidden={!lock.locked}>
          {lock.note}
          {lock.failed ? <React.Fragment>{" "}<ActBtn label="retry" onClick={() => {
            lockFor(stage.build, step).then((l2) => { if (stage.gen === S.gen) setLock(l2); });
          }} /></React.Fragment> : null}
        </div>
        {step.kind === "design" && d
          ? <OptionCards set={d} step={step} st={cur} at={at} locked={lock.locked} />
          : <DocCards d={d} step={step} st={cur} at={at} locked={lock.locked} />}
      </React.Fragment>
    );
  }

  // ── stage track and carousel ─────────────────────────────────────────────

  function StageTrack({ track }) {
    const { stages, key, slug } = track;
    return (
      <React.Fragment>
        {UI.GROUPS.map(([g, label]) => {
          const members = stages.filter((x) => UI.groupOf(x) === g);
          if (!members.length) return null;
          const s = UI.groupSummary(g, members), active = members.some((x) => x.key === key && !x.disabled);
          return (
            <button type="button" key={g} data-key={g} disabled={!!s.disabled}
                    className={["hub-tab", s.done && "is-done", s.now && "is-now", active && "active"].filter(Boolean).join(" ")}
                    onClick={s.to ? () => { UI.selectBuild(slug, members.some((x) => x.key === key) ? key : s.to, true); } : undefined}>
              <span className="hub-e3p-stage-dot" aria-hidden="true"></span>
              <span className="wb-stage-t">{label}</span>
              <span className="hub-e3p-stage-sub wb-stage-sub">{s.sub}</span>
            </button>
          );
        })}
      </React.Fragment>
    );
  }

  // options with more than one set: step through them here
  function Carousel({ track, hist }) {
    const sets = track ? track.stages.filter((x) => UI.groupOf(x) === "options" && !x.disabled) : [];
    const at = track ? sets.findIndex((x) => x.key === track.key) : -1;
    const hidden = hist || at < 0 || sets.length < 2;
    if (at < 0 || sets.length < 2) return <div className="wb-opt-car" id="optCar" hidden></div>;
    const cur = sets[at];
    const go = (to) => (to ? () => { UI.selectBuild(track.slug, to.key, true); } : undefined);
    return (
      <div className="wb-opt-car" id="optCar" hidden={hidden}>
        <button type="button" className="hub-btn wb-car-arrow" aria-label="previous option set" disabled={!sets[at - 1]} onClick={go(sets[at - 1])}>‹</button>
        <span className="wb-car-t"><span className={`wb-pip ${cur.done ? "is-approved" : "is-waiting"}`}></span><span className="wb-car-name" title={cur.label}>{cur.label}</span></span>
        <span className="wb-car-count">{`${at + 1} of ${sets.length}`}</span>
        <button type="button" className="hub-btn wb-car-arrow" aria-label="next option set" disabled={!sets[at + 1]} onClick={go(sets[at + 1])}>›</button>
      </div>
    );
  }

  // ── marks walk-through: ?walk=<session>, one card per fixed mark, his Close / Send back ──

  // "HUB · mail" -> "Mail"; a mark saved without a title falls back to the url's first segment
  function walkPages(marks) {
    const names = marks.map((m) => {
      const t = (m.title || "").split("·").pop().trim() || (m.url || "/").split(/[/?]/)[1] || "home";
      return t.charAt(0).toUpperCase() + t.slice(1);
    });
    return names.filter((x, i) => names.indexOf(x) === i);
  }
  // an answer still in its undo window already counts as answered
  const fixedOf = (marks) => marks.filter((m) => m.status === "fixed" && !S.markHeld[`${S.walk && S.walk.session}:${m.n}`]).length;

  function WalkPill({ marks }) {
    return <span className="hub-pill"><em>{fixedOf(marks)}</em>{` of ${marks.length} to check`}</span>;
  }

  /* The walk page's head, sized like a build's (mark 231818 #1): three tiles where the stage track sits
     (the page, what waits on him, what is still on Claude), then a bottom strip with when, where, which code. */
  function WalkHead({ walk }) {
    const ms = walk.marks, n = fixedOf(ms);
    const urls = ms.map((m) => m.url).filter((u, i, a) => a.indexOf(u) === i);
    const on = ms.filter((m) => m.status !== "fixed");
    const count = (k, label) => (k ? `${k} ${label}` : "");
    const busy = [count(on.filter((m) => m.status === "open").length, "new"),
      count(on.filter((m) => m.options).length, "in an option set"),
      count(on.filter((m) => m.status !== "open" && !m.options).length, "sent back")].filter(Boolean).join(" · ");
    const tile = (dot, t, sub, now) => (
      <div className={`hub-tab wb-walk-tile${now ? " is-now" : ""}`}>
        <span className="hub-e3p-stage-dot" data-n={dot} aria-hidden="true"></span>
        <span className="wb-stage-t">{t}</span>
        <span className="hub-e3p-stage-sub wb-stage-sub" title={sub}>{sub}</span>
      </div>
    );
    const at = walk.started ? new Date(walk.started).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";
    return (
      <React.Fragment>
        <div className="hub-tabs hub-e3p-stages wb-walk-track">
          {tile(ms.length, urls.length > 1 ? `${urls.length} pages` : "Page", `${count(ms.length, ms.length > 1 ? "marks on" : "mark on")} ${urls.join(" · ")}`)}
          {tile(n, "To check", n ? `${n} fixed, waiting on your Close or Send back` : "nothing waiting on you", n > 0)}
          {tile(on.length, "Fixing", busy || "nothing left to fix")}
        </div>
        <div className="wb-walk-foot">
          <span className="wb-walk-foot-l">Marked</span>
          <span className="wb-walk-foot-v">{[at, walk.machine, walk.code_commit && `code ${walk.code_commit}`].filter(Boolean).join(" · ")}</span>
          <span className="wb-walk-foot-n">{walk.session}</span>
        </div>
      </React.Fragment>
    );
  }

  function WalkCard({ session, m }) {
    const strip = UI.useStrip(["back", "opts"]);
    // once answered the plate shows the result in place of its buttons
    // fixed: his buttons; sent back: his words; still open: nothing to answer until Claude fixes it
    const asked = <span className="hub-pill">options requested</span>;
    const hk = `${session}:${m.n}`;
    const pillOf = (verdict) => (verdict === "close" ? <span className="hub-pill is-good">closed</span>
      : verdict === "options" ? asked
      : <VerdictPill v="sent_back" />);
    // the head carries only the pill; his words go in the body as You said (a long reply in the head ran three lines)
    // an answer held in its undo window (he left and came back) draws as given, not as Close again
    const [result, setResult] = useState(S.markHeld[hk] ? pillOf(S.markHeld[hk])
      : m.status === "fixed" ? null
      : m.options ? asked
      : m.reply ? <VerdictPill v="sent_back" />
      : <span className="hub-pill">not fixed yet</span>);
    const [said, setSaid] = useState(m.reply || m.answered || m.comment);
    const first = (m.reply || m.answered) ? m.comment : "";
    // the options rig's three preview kinds: a still, the live page he drives, the live page playing the fix's motion
    const hub = /^\/(?!\/)/.test(m.url || "");
    const views = [["still", "Static"]].concat(hub ? [["live", "Motion interaction"]] : [], hub && m.play ? [["play", "Motion play"]] : []);
    const [view, setView] = useState("still");
    // after first, full width; the glass toggle flips to the before crop in place
    const [before, setBefore] = useState(!m.after);
    const flip = (b, label) => <button type="button" className="hub-tab" role="tab" aria-selected={before === b} onClick={() => { setBefore(b); }}>{label}</button>;
    const still = (m.after || m.crop) ? (
      <figure className="wb-walk-pic">
        <img src={before ? m.crop : m.after} alt={`${before ? "before" : "after"} mark ${m.n}`} />
        {m.after && m.crop ? <span className="hub-tabs hub-tabs--segmented wb-walk-flip" role="tablist" aria-label="after or before">{flip(false, "After")}{flip(true, "Before")}</span> : null}
      </figure>)
      // an essay mark has no picture: the passage he highlighted stands in for the crop
      : m.quote ? <blockquote className="wb-walk-quote">{m.quote}</blockquote> : null;
    // play: the mark's NN-play.js added to the page once it loads, as the rig adds a set's data-js
    const onPlay = (e) => {
      const d = e.currentTarget.contentDocument;
      if (!d) return;
      const s = d.createElement("script");
      s.src = m.play;
      d.body.appendChild(s);
    };
    // the answer shows on the card at the click; undo or a failed write puts the buttons back
    const send = (verdict, reply) => {
      const was = [result, said];
      strip.hide();
      setResult(pillOf(verdict));
      if (verdict === "send_back" || (verdict === "options" && reply)) setSaid(reply);
      // the list row drops this mark from its count now, not when the hold sends
      S.markHeld[hk] = verdict;
      UI.rerender();
      hold(`mark ${m.n} ${{ close: "close", options: "make options" }[verdict] || "send back"}`, () => sendNow(verdict, reply),
        () => { delete S.markHeld[hk]; UI.rerender(); setResult(was[0]); setSaid(was[1]); });
    };
    const sendNow = (verdict, reply) => post("/marks/api/walk/decide",
      { session: session, n: m.n, verdict: verdict, reply: reply }, `mark ${m.n}`).then((r) => r.json().then((e) => { if (!r.ok) throw new Error(e.error || "failed"); }))
      .then(() => {
        // the server has it now; the refresh's counts replace the held one (no redraw in between)
        delete S.markHeld[hk];
        // reload so the inbox row's count (or the row itself) follows the answer
        UI.refresh({},`mark ${m.n} ${{ close: "closed", options: "sent for options" }[verdict] || "sent back"}`);
        return true;
      })
      .catch((e) => { setStatus(msgOf(e)); return null; });
    const defs = {
      back: {
        label: "still off", placeholder: "what is still off…", confirmLabel: "send",
        onConfirm: (t) => {
          if (!t) { setStatus("say what is still off"); return; }
          send("send_back", t);
        },
      },
      // his note rides along to the option set; empty is fine
      opts: {
        label: "note", placeholder: "optional note for the options…", confirmLabel: "make options",
        onConfirm: (t) => { send("options", t); },
      },
    };
    return (
      <PlateCard title={`Mark ${m.n}`} sum={result} bodyClass="wb-card-body wb-doc"
                 strip={<CardStrip strip={strip} defs={defs} />}
                 acts={result ? null : [
                   <ActBtn key="c" label="close" cls="hub-btn--accent" onClick={() => { send("close"); }} />,
                   <ActBtn key="s" label="send back" cls="hub-btn--danger" onClick={(e) => { strip.show("back", e.currentTarget); }} />,
                   // a full Workbench option set for this element instead of one fix; /marks runs it in its own tab
                   <ActBtn key="o" label="make options" onClick={(e) => { strip.show("opts", e.currentTarget); }} />,
                 ]}>
        {/* after a send-back, what he said is his latest words; the first comment stays below for context */}
        <p><b>You said:</b> {said || "(no comment)"}</p>
        {first && first !== said ? <p className="wb-dim"><b>First mark:</b> {first}</p> : null}
        {m.fix_note ? <p><b>What changed:</b> {m.fix_note}</p> : null}
        {views.length > 1 ? (
          <div className="hub-tabs hub-tabs--segmented wb-walk-tabs" role="tablist">
            {views.map(([k, label]) => <button key={k} type="button" className="hub-tab" role="tab" aria-selected={view === k} onClick={() => { setView(k); }}>{label}</button>)}
          </div>) : null}
        {view === "still" ? still
          : <div className="wb-walk-live"><iframe key={view} src={m.url} title={`mark ${m.n} live page`} onLoad={view === "play" ? onPlay : undefined}></iframe></div>}
        {/* a Hub path only: the url came from the browser that saved the mark */}
        {hub ? <p><a href={m.url} target="_blank" rel="noopener">open the live page</a></p> : null}
      </PlateCard>
    );
  }

  Object.assign(UI, {
    decide, decideSet, deleteCards, staleSet, fetchStep, fetchLedger, lockFor, StageCards, StageTrack, Carousel, WalkCard, WalkHead, WalkPill, walkPages,
  });
})();
