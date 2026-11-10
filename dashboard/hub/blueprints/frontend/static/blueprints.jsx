/* blueprints.jsx — body of the /blueprints page (the shared UI vocabulary).

   The page's job is to show REAL nodes: previews are cloned out of this page's own
   DOM and the cards are strings built from the registry, so those parts stay
   imperative (refs to empty divs React never reconciles into). React owns the
   frame: tabs, panels, the debt and budget blocks, the status strip, the clock.
   Same DOM and classes as the plain page; the only requests are the two GETs on
   window load, in the same order. The top bar is topbar.jsx's, outside this root. */
window.BlueprintsUI = window.BlueprintsUI || {};
(() => {
  const { useState, useEffect, useLayoutEffect } = React;

  const esc = s => s.replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

  // Components that are fixed + full-bleed need a taller frame to read at all.
  const TALL = new Set(["module-launcher", "modal", "modal-form", "theme-picker"]);

  /* The active theme's own version of a piece, and only that theme's: the other
     themes' rules never reach the DOM (spec §8). Under liquid the head also badges
     the layer and whether the piece has its own rules or inherits the shared ones. */
  const activeTheme = () => (window.HubTheme ? HubTheme.get() : document.documentElement.dataset.theme);
  function themeBadges(e) {
    if (activeTheme() !== "liquid") return "";
    const own = (e.theme_css?.liquid || []).length;
    return `<span class="el-token">${esc(e.liquid_layer || "")}</span>` +
      `<span class="el-token"${own ? "" : ` title="${esc(e.liquid_inherits || "")}"`}>${own ? "own version" : "inherits shared"}</span>`;
  }
  function themeFold(e) {
    const t = activeTheme(), own = e.theme_css?.[t] || [];
    return `
      <details class="el-fold">
        <summary>${esc(t)} version — ${own.length} rules</summary>
        <pre class="el-code">${own.length ? cssBlock(own) : esc(e.liquid_inherits && t === "liquid" ? e.liquid_inherits : "no rules of its own; the shared rules above apply")}</pre>
      </details>`;
  }

  function cssBlock(css) {
    let out = "", at = null;
    for (const r of css) {
      if (r.at_rule !== at) {
        at = r.at_rule;
        if (at) out += `<span class="el-at">${esc(at)} {</span>`;
      }
      const decls = r.body.split(";").map(d => d.trim()).filter(Boolean)
                      .map(d => `  ${esc(d)};`).join("\n");
      out += `${esc(r.selector)} {\n${decls}\n}\n`;
    }
    return out;
  }

  /* The whole point of the page. Every chrome component is drawn by topbar.jsx
     at runtime and appears in no template, so the previous hand-written markup fields
     were guesses — and every one of them was wrong. These clone the REAL node out of
     this page's own DOM. Run before a single card is inserted, or the selectors start
     matching the clones instead of the originals. */
  function captureAll(entries) {
    // clear first: on a re-render the previous clones are still in the document and
    // `.module-launcher` would match the one sitting inside the old top-bar card.
    const TIERS = ["basics", "elements", "modules"];
    TIERS.forEach(t => { document.getElementById(`cards-${t}`).innerHTML = ""; });
    const shot = {};
    let opened = null;
    for (const e of entries) {
      if (!e.live) continue;
      if (e.live.open && !opened) {
        opened = document.querySelector(".module-launcher");
        // flushSync: React would otherwise draw the overlay a tick after the click
        if (opened) ReactDOM.flushSync(() => opened.click());
      }
      const node = document.querySelector(e.live.sel);
      if (!node) continue;
      const clone = node.cloneNode(true);
      // ids are the page's, not the component's; two in one document is a bug.
      clone.removeAttribute("id");
      clone.querySelectorAll("[id]").forEach(n => { n.removeAttribute("id"); });
      clone.removeAttribute("hidden");
      // a dropdown parks itself at display:none; the blueprint has to show the menu.
      if (e.live.expand) {
        clone.querySelectorAll(e.live.expand).forEach(n => { n.style.display = ""; });
      }
      shot[e.id] = clone;
    }
    // closed through the launcher's own Escape handler: the overlay is React's to remove
    if (opened) ReactDOM.flushSync(() => document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape"})));
    return shot;
  }

  function card(e, shot) {
    const tall = TALL.has(e.id) ? " el-preview-tall" : "";
    const live = !!shot[e.id];
    const code = e.markup || (live ? shot[e.id].outerHTML : "");
    const label = e.markup
      ? `markup — verbatim from <code>${esc(e.markup_from)}</code>`
      : "rendered dom — topbar.jsx draws this; your page writes nothing";
    return `
    <section class="el-card" id="el-${esc(e.id)}">
      <div class="el-card-head">
        <span class="el-name">${esc(e.name)}</span>
        <span class="el-src">${esc(e.source)} · ${e.css.length} rules</span>${themeBadges(e)}
      </div>
      <p class="el-purpose">${esc(e.purpose)}</p>
      <div class="el-preview${tall}" data-slot="${e.id}">
        <span class="el-preview-label">${live ? "live — cloned from this page" : "static"}</span>
        ${live ? "" : e.markup}
      </div>
      <div class="el-rules">
        <div class="el-rule"><span class="el-rule-k">use when</span><span class="el-rule-v">${esc(e.use_when)}</span></div>
        <div class="el-rule el-rule-dont"><span class="el-rule-k">don't</span><span class="el-rule-v">${esc(e.dont)}</span></div>
      </div>
      <details class="el-fold">
        <summary>${label}<button class="el-copy" data-copy="${e.id}">copy</button></summary>
        <pre class="el-code" id="mk-${e.id}">${esc(code)}</pre>
      </details>
      <details class="el-fold">
        <summary>css — read live from ${esc(e.source)}</summary>
        <pre class="el-code">${cssBlock(e.css)}</pre>
        <div class="el-tokens">${e.tokens.map(t => `<span class="el-token">${esc(t)}</span>`).join("")}</div>
      </details>${themeFold(e)}
    </section>`;
  }

  function render(d, setSrc, setDebt) {
    // flushSync: the status strip is itself a captured blueprint, so the source dots
    // must be in the DOM before captureAll clones it
    ReactDOM.flushSync(() => setSrc(
      `<span class="ok">●</span> base.css<span class="sep">·</span><span class="ok">●</span> chrome.css` +
      `<span class="sep">·</span><span class="ok">●</span> theme-switch.js<span class="sep">·</span><span class="ok">●</span> topbar.jsx`));
    const shot = captureAll(d.blueprints);
    for (const t of ["basics", "elements", "modules"]) {
      document.getElementById(`cards-${t}`).innerHTML =
        d.blueprints.filter(e => e.tier === t).map(e => card(e, shot)).join("");
    }
    for (const [id, node] of Object.entries(shot)) {
      document.querySelector(`[data-slot="${id}"]`).appendChild(node);
    }

    const b = d.baselines;
    const und = d.undocumented.length;
    setDebt(`
      <p>Everything here is pre-existing and ratcheted: the checks fail on anything
      <em>new</em>, and each list carries a committed max so it can't be quietly
      appended to.</p>
      <ul>
        <li><strong>${und}</strong> shared classes with no blueprint
          ${und === 0 ? '<span class="el-clean">— clean, every class is claimed</span>' : ""}</li>
        <li><strong>${b.copies.length}</strong> re-creations of a blueprinted component under a new name:
          <ul>${b.copies.map(c => `<li><code>${esc(c.split("  (")[0])}</code></li>`).join("")}</ul></li>
        <li><strong>${b.overrides.length}</strong> module rules re-styling a blueprinted class
          <ul>${Object.entries(b.overrides.reduce((m, o) => {
                const f = o.split(":")[0]; m[f] = (m[f] || 0) + 1; return m; }, {}))
              .sort((a, x) => x[1] - a[1])
              .map(([f, n]) => `<li><code>${esc(f)}</code> — ${n}</li>`).join("")}</ul></li>
        <li><strong>${b.markup.length}</strong> buttons, tables, cards and pills built with no shared class on them
          <ul>${Object.entries(b.markup.reduce((m, o) => {
                const f = o.split(":")[0]; m[f] = (m[f] || 0) + 1; return m; }, {}))
              .sort((a, x) => x[1] - a[1])
              .map(([f, n]) => `<li><code>${esc(f)}</code> — ${n}</li>`).join("")}</ul></li>
      </ul>`);
  }

  /* The basics tab's brand sheet. Token NAMES come from whichever theme rules match
     the page right now, VALUES from getComputedStyle, and the symbols from the real
     assets and window.MODULES. No list of names or values is written here, so a
     token added to a theme shows up with no edit to this page. */
  function themeTokens() {
    const r = document.documentElement, names = new Set();
    const walk = rules => { for (const rule of rules) {
      if (rule.cssRules && !rule.style) { walk(rule.cssRules); continue; }
      if (!rule.style || !rule.selectorText || !r.matches(rule.selectorText)) continue;
      for (const p of rule.style) if (p.startsWith("--")) names.add(p);
    } };
    for (const sh of document.styleSheets) { try { walk(sh.cssRules); } catch {} }
    const cs = getComputedStyle(r);
    return [...names].map(n => [n, cs.getPropertyValue(n).trim()]).filter(([, v]) => v);
  }

  function renderBrand() {
    const tok = themeTokens();
    const pick = re => tok.filter(([n]) => re.test(n));
    const fonts = pick(/^--font/);
    const colors = tok.filter(([n, v]) => !/^--(font|feat|s-|r\b|r-)/.test(n) && CSS.supports("color", v));
    const space = pick(/^--s-\d/);
    const radii = pick(/^--r(-|$)/);
    const sample = "Aa Bb Cc 0123456789 — the quick brown fox";
    const marks = ["brand-mark.svg"];
    const mods = (window.MODULES || []).filter(m => m.icon);
    const r = document.documentElement;
    document.getElementById("brand").innerHTML = `
    <section class="el-card bp-brand">
      <div class="el-card-head">
        <span class="el-name">brand</span>
        <span class="el-src">${esc(r.dataset.theme)} · ${esc(r.dataset.surface)} · read live</span>
      </div>
      <h3 class="el-section-h">type</h3>
      ${fonts.map(([n, v]) => `<div class="bp-font"><code>${esc(n)}</code>
        <span style="font-family:var(${n})">${esc(sample)}</span>
        <span class="el-src">${esc(v.split(",")[0].replace(/"/g, ""))}</span></div>`).join("")}
      <h3 class="el-section-h">colour</h3>
      <div class="bp-swatches">${colors.map(([n, v]) => `
        <div class="bp-swatch"><span class="bp-chip" style="background:var(${n})"></span>
          <code>${esc(n)}</code><span class="el-src">${esc(v)}</span></div>`).join("")}</div>
      <h3 class="el-section-h">spacing · radius</h3>
      <div class="bp-scale">${space.map(([n, v]) => `
        <div><span class="bp-bar" style="width:var(${n})"></span><code>${esc(n)}</code> ${esc(v)}</div>`).join("")}
        ${radii.map(([n, v]) => `
        <div><span class="bp-chip" style="border-radius:var(${n})"></span><code>${esc(n)}</code> ${esc(v)}</div>`).join("")}</div>
      <h3 class="el-section-h">symbols</h3>
      <div class="bp-symbols">
        ${marks.map(m => `<figure><img src="/static/assets/${m}" alt=""><figcaption>${m}</figcaption></figure>`).join("")}
        ${mods.map(m => `<figure><svg viewBox="0 0 24 24" aria-hidden="true">${m.icon}</svg><figcaption>${esc(m.name)}</figcaption></figure>`).join("")}
        <figure><span class="bp-glyph">&#x263E;&#xFE0E;</span><figcaption>dark</figcaption></figure>
        <figure><span class="bp-glyph">&#x2600;&#xFE0E;</span><figcaption>light</figcaption></figure>
      </div>
    </section>`;
  }

  /* The pages tab (was "layouts"), generated the same way the components tab is: one .bp-origin
     card per registry origin, reusing el-card/el-rules/el-fold so a layout
     archetype reads as the same kind of thing a component blueprint is. The live
     render is the origin's own skeleton HTML, injected verbatim -- it is a normal
     descendant of this page (never a body child), so the origin's own
     `body:has(> .hub-t3p)` viewport lock cannot fire here. */
  function originCard(o, derivatives) {
    const rows = derivatives.filter(dv => dv.origin === o.id);
    return `
    <section class="el-card bp-origin" id="el-${esc(o.id)}">
      <div class="el-card-head">
        <span class="el-name">${esc(o.name)}</span>
        <span class="el-src">${esc(o.id)} · ${esc(o.source)} · ${o.css.length} rules</span>${themeBadges(o)}
      </div>
      <div class="bp-composes">
        composes ${o.composes.map(c => `<a href="#el-${esc(c)}" data-goto-component="${esc(c)}">${esc(c)}</a>`).join(" · ")}
      </div>
      <div class="bp-map">
        <div class="bp-origin-frame" data-origin="${esc(o.id)}">${o.skeleton}<div class="bp-overlay"></div></div>
        <ol class="bp-legend">${(o.regions || []).map((r, i) => `
          <li class="bp-legend-item" data-region="${i}">
            <span class="bp-badge">${i + 1}</span>
            <span><b>${esc(r.name)}</b>${esc(r.holds)}</span>
          </li>`).join("")}
        </ol>
      </div>
      ${o.phone_notes ? `
      <div class="bp-phone">
        <iframe class="bp-phone-frame" title="${esc(o.name)} at phone width" data-phone="${esc(o.id)}"></iframe>
        <div class="bp-phone-notes">
          <h3 class="el-section-h">on a phone (under 900px)</h3>
          <ul>${o.phone_notes.map(n => `<li>${esc(n)}</li>`).join("")}</ul>
        </div>
      </div>` : ""}
      <div class="el-rules">
        <div class="el-rule"><span class="el-rule-k">purpose</span><span class="el-rule-v">${esc(o.purpose)}</span></div>
        <div class="el-rule"><span class="el-rule-k">use when</span><span class="el-rule-v">${esc(o.use_when)}</span></div>
        <div class="el-rule el-rule-dont"><span class="el-rule-k">don't</span><span class="el-rule-v">${esc(o.dont)}</span></div>
      </div>
      <details class="el-fold">
        <summary>skeleton, read off ${esc(o.skeleton_from)}<button class="el-copy" data-copy="origin-${o.id}">copy</button></summary>
        <pre class="el-code" id="mk-origin-${o.id}">${esc(o.skeleton)}</pre>
      </details>
      <details class="el-fold">
        <summary>css — read live from ${esc(o.source)}</summary>
        <pre class="el-code">${cssBlock(o.css)}</pre>
        <div class="el-tokens">${o.tokens.map(t => `<span class="el-token">${esc(t)}</span>`).join("")}</div>
      </details>${themeFold(o)}
      <div class="bp-derivatives">
        <h3 class="el-section-h">derivatives</h3>
        ${rows.map(r => `
          <div class="bp-derivative-row">
            <a href="${esc(r.href)}">${esc(r.dashboard)}</a>
            <code>${esc(r.page_mods)}</code>
            <span>${r.page_mods_lines} lines of page mods</span>
          </div>`).join("")}
      </div>
    </section>`;
  }

  function renderOrigins(d) {
    document.getElementById("panel-pages").innerHTML =
      `<p class="el-intro">
        Whole-page shapes a new module starts from. Each one is drawn live from its
        real skeleton and stylesheet, filled with sample content so you can see what
        goes where. <strong>Numbers on the page match the list below it; hover either
        to light up the region.</strong> To build on one: paste the skeleton, link the
        origin after <code>components.css</code>, and register the page under derivatives.
      </p>` +
      d.origins.map(o => originCard(o, d.derivatives)).join("");
    for (const o of d.origins) {
      const frame = document.querySelector(`.bp-origin-frame[data-origin="${o.id}"]`);
      fillSample(frame, o);
      const phone = document.querySelector(`[data-phone="${o.id}"]`);
      if (phone) phone.srcdoc = phoneDoc(frame.querySelector(".hub-shell").outerHTML);
    }
    requestAnimationFrame(placeRegions);
  }

  /* The skeleton ships with every text node emptied, so on its own it reads as a
     set of blank boxes. Sample text from the registry goes into the rendered copy
     only; the skeleton a reader copies stays empty. */
  function fillSample(frame, o) {
    for (const [sel, texts] of Object.entries(o.sample || {})) {
      frame.querySelectorAll(sel).forEach((el, i) => {
        const t = texts[Math.min(i, texts.length - 1)];
        if (el instanceof SVGElement) el.innerHTML = `<path d="${t}"/>`;
        else if (el.tagName === "INPUT") el.placeholder = t;
        else if (el.tagName === "SELECT") el.innerHTML = `<option>${esc(t)}</option>`;
        // text goes after a leading decorative child (a glyph, a stage dot), else before the children (a group head's count)
        else if (el.children.length) el.firstElementChild.getAttribute("aria-hidden") ? el.firstElementChild.after(t) : el.prepend(t);
        else el.textContent = t;
      });
    }
    // card bodies belong to the derivative, so these rows are marked as filler
    frame.querySelectorAll(".hub-plate-card").forEach((card, i) => {
      for (const r of (o.sample_rows || [])[i] || []) {
        card.insertAdjacentHTML("beforeend", `<div class="bp-row">${esc(r)}</div>`);
      }
    });
    // the pane head is an empty slot; outline it so the reader (and badge 3) can see it
    frame.querySelectorAll(".hub-t3p-head:empty").forEach(h => { h.innerHTML = `<div class="bp-slot">your page fills this, or leaves it out</div>`; });
    frame.querySelectorAll(".hub-e3p-rail:empty").forEach(h => { h.innerHTML = `<div class="bp-slot">your page's rail cards</div>`; });
    // the skeleton's right group is one empty light/dark button: topbar.jsx fills the
    // real one at runtime and never mounts in a copy. Show this page's own live group
    // instead, inert, so the layout reads like a real page. The copyable skeleton is untouched.
    const live = document.querySelector("body > .topbar .topbar-r");
    frame.querySelectorAll(".topbar-r").forEach(el => {
      if (!live) { el.remove(); return; }
      const c = live.cloneNode(true);
      c.querySelectorAll("[id]").forEach(n => { n.removeAttribute("id"); });
      c.querySelectorAll(".gc-panel").forEach(n => { n.remove(); });
      c.inert = true;
      el.replaceWith(c);
    });
    frame._regions = o.regions || [];
  }

  // numbered badges pinned to each region, measured off the live render
  function placeRegions() {
    document.querySelectorAll(".bp-origin-frame").forEach(frame => {
      const box = frame.getBoundingClientRect();
      const overlay = frame.querySelector(".bp-overlay");
      overlay.innerHTML = (frame._regions || []).map((r, i) => {
        const el = frame.querySelector(r.sel);
        if (!el) return "";
        const b = el.getBoundingClientRect();
        return `<div class="bp-region" data-region="${i}" style="left:${b.left - box.left}px;top:${b.top - box.top}px;width:${b.width}px;height:${b.height}px"></div>` +
          // badge sits on the region's corner, nudged off its content, kept inside the crop
          `<span class="bp-badge bp-pin" data-region="${i}" style="left:${Math.max(3, b.left - box.left - 9)}px;top:${Math.max(3, b.top - box.top - 9)}px">${i + 1}</span>`;
      }).join("");
    });
  }

  // the phone view has to be its own viewport: the origin's phone shape is a
  // media query, and a narrow div inside a wide page never trips it.
  function phoneDoc(shell) {
    const head = [...document.querySelectorAll('link[rel="stylesheet"], style')]
      .map(n => n.outerHTML).join("");
    const r = document.documentElement;
    return `<!DOCTYPE html><html data-theme="${r.dataset.theme}" data-surface="${r.dataset.surface}">` +
      `<head><base href="${location.origin}/"><style>:where(button,input,select){font:inherit;color:inherit;background:none;border:0}</style>${head}</head><body class="bp-phone-body">${shell}</body></html>`;
  }

  const TABS = ["basics", "elements", "modules", "pages"];

  class ErrorBoundary extends React.Component {
    constructor(p) { super(p); this.state = { err: null }; }
    static getDerivedStateFromError(err) { return { err }; }
    render() {
      return this.state.err
        ? <div className="hub-error">Could not draw the page ({String(this.state.err)}).</div>
        : this.props.children;
    }
  }

  // the shared StatusStrip (topbar.jsx) with this page's source link as its context
  function Status({ src }) {
    return (
      <StatusStrip id="bp-status">
        <span className="src" id="src" dangerouslySetInnerHTML={{ __html: src === null ? "\u2014" : src }} />
      </StatusStrip>
    );
  }

  function Body() {
    const [tab, setTab] = useState({ name: "basics", n: 0 });
    const [debt, setDebt] = useState("reading\u2026");
    const [budget, setBudget] = useState("reading\u2026");
    const [src, setSrc] = useState(null);

    // badges are measured off the visible panel, so re-place after every tab click
    useLayoutEffect(() => { placeRegions(); }, [tab]);

    useEffect(() => {
      document.getElementById("bp-root").setAttribute("data-react-mounted", "blueprints");
      const onResize = () => placeRegions();
      window.addEventListener("resize", onResize);

      const onOver = e => {
        const item = e.target.closest(".bp-legend-item, .bp-region, .bp-pin");
        document.querySelectorAll(".is-lit").forEach(n => { n.classList.remove("is-lit"); });
        if (!item) return;
        item.closest(".bp-map").querySelectorAll(`[data-region="${item.dataset.region}"]`)
          .forEach(n => { n.classList.add("is-lit"); });
      };
      const onClick = e => {
        const copyBtn = e.target.closest("[data-copy]");
        if (copyBtn) {
          e.preventDefault();
          navigator.clipboard.writeText(document.getElementById(`mk-${copyBtn.dataset.copy}`).textContent)
            .then(() => { copyBtn.textContent = "copied"; setTimeout(() => copyBtn.textContent = "copy", 1200); });
          return;
        }
        // composes link: jump to the components tab card it names.
        const gotoBtn = e.target.closest("[data-goto-component]");
        if (gotoBtn) {
          e.preventDefault();
          const target = document.getElementById(`el-${gotoBtn.dataset.gotoComponent}`);
          const panel = target?.closest(".el-panel");
          // flushSync: the panel must be visible before scrollIntoView measures it
          if (panel) ReactDOM.flushSync(() => document.querySelector(`.el-tab[data-tab="${panel.id.slice(6)}"]`).click());
          target?.scrollIntoView({ block: "start" });
        }
      };
      document.addEventListener("mouseover", onOver);
      document.addEventListener("click", onClick);

      const listeners = [];
      const start = () => {
        fetch("/blueprints/api/budget.json").then(r => r.json()).then(b => {
          const top = b.files.slice(0, 3).map(f => `<code>${esc(f.path)}</code> ${f.lines}`).join(" · ");
          setBudget(`page CSS: ${b.total} lines · largest: ${top}`);
        }).catch(() => { setBudget("budget unavailable"); });

        fetch("/blueprints/api/blueprints.json?resolved=1").then(r => {
          if (!r.ok) throw new Error(r.status);
          return r.json();
        }).then(d => {
          const draw = () => {
            renderBrand();
            render(d, setSrc, setDebt);
            renderOrigins(d);
          };
          draw();
          for (const ev of ["hub:themechange", "hub:surfacechange"]) {
            // setTimeout, not a direct call: theme-switch.js dispatches the event and
            // THEN repaints the toggle glyph, so capturing inline clones the old icon.
            const h = () => setTimeout(draw, 0);
            document.addEventListener(ev, h);
            listeners.push([ev, h]);
          }
        }).catch(err => {
          document.getElementById("cards-basics").innerHTML =
            `<div class="hub-error">Could not read the shared layer (${esc(String(err))}).
             <button class="hub-btn hub-error-retry" onclick="location.reload()">Retry</button></div>`;
          setDebt("unavailable");
          document.getElementById("panel-pages").innerHTML =
            `<p class="el-intro">pages unavailable (${esc(String(err))}).</p>`;
        });
      };
      // on load, not mount: theme-switch.js and topbar.jsx are deferred, so before
      // load none of the chrome exists yet and every capture would miss.
      if (document.readyState === "complete") start(); else window.addEventListener("load", start);

      return () => {
        window.removeEventListener("resize", onResize);
        window.removeEventListener("load", start);
        document.removeEventListener("mouseover", onOver);
        document.removeEventListener("click", onClick);
        listeners.forEach(([ev, h]) => { document.removeEventListener(ev, h); });
      };
    }, []);

    const pick = name => setTab(t => ({ name, n: t.n + 1 }));
    return (
      <React.Fragment>
        <div className="el-tabs" role="tablist">
          {TABS.map(t => (
            <button key={t} type="button" className={`el-tab${tab.name === t ? " is-active" : ""}`}
              data-tab={t} role="tab" aria-selected={tab.name === t ? "true" : "false"}
              onClick={() => pick(t)}>{t}</button>
          ))}
        </div>

        {/* innerHTML, not JSX text: JSX drops the space where a line ends on a tag */}
        <p className="el-intro" dangerouslySetInnerHTML={{ __html: `
          The Hub's shared UI vocabulary. Every card is a <strong>blueprint</strong>:
          what a page author actually types, the rules that govern it, and the CSS behind it
          read live off <code>base.css</code>, <code>chrome.css</code>, <code>components.css</code>
          and the stylesheets <code>theme-switch.js</code> injects. <strong>Nothing here is a
          drawing.</strong> Each preview is the real node, so it cannot disagree with what ships.
          <strong>Build from these before writing a new component.</strong> If you make something
          shared, it gets a blueprint (and a <code>tier</code>) in the same change.
        ` }} />

        <div className="el-panel" id="panel-basics" role="tabpanel" hidden={tab.name !== "basics"}>
          <div id="brand"></div>
          <h2 className="el-section-h">basic parts</h2>
          <div id="cards-basics"></div>
        </div>

        <div className="el-panel" id="panel-elements" role="tabpanel" hidden={tab.name !== "elements"}>
          <div id="cards-elements"></div>
          <h2 className="el-section-h">known debt</h2>
          <div className="el-debt" id="debt" dangerouslySetInnerHTML={{ __html: debt }} />
          <div className="el-debt" id="budget" dangerouslySetInnerHTML={{ __html: budget }} />
        </div>

        <div className="el-panel" id="panel-modules" role="tabpanel" hidden={tab.name !== "modules"}>
          <div id="cards-modules"></div>
        </div>

        <div className="el-panel" id="panel-pages" role="tabpanel" hidden={tab.name !== "pages"}></div>

        {ReactDOM.createPortal(<Status src={src} />, document.body)}
      </React.Fragment>
    );
  }

  window.BlueprintsUI.mount = () => {
    ReactDOM.createRoot(document.getElementById("bp-root")).render(<ErrorBoundary><Body /></ErrorBoundary>);
  };
  window.BlueprintsUI.mount();
})();
