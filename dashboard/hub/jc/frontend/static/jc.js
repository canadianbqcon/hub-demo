// ============================================================
// juniper & co umbrella — primary tab controller.
//
// Owns the three top-level tabs and nothing else. Each panel's payload
// (batch.js, barback.jsx) stays a black box: the only contract between
// them is the `jc:tab` event this file fires, which is how a panel
// knows to hydrate itself the first time it is shown.
//
// Deep-linkable: #batch / #barback / #map. Same tablist shape as the
// finances umbrella (click + arrow keys + hash), which is the pattern
// this page follows.
// ============================================================

(() => {
  // bar back leads the tab bar, so a hash-less /jc/ lands there. Keep this in
  // step with the first button in #jcTabs — a default that is not the leftmost
  // tab paints the bar with no tab underlined until select() runs.
  var DEFAULT_TAB = "barback";

  function tabs() { return Array.prototype.slice.call(document.querySelectorAll("#jcTabs .jc-tab")); }

  function tabFromHash() {
    var h = (window.location.hash || "").replace(/^#/, "");
    return document.getElementById(`panel-${h}`) ? h : DEFAULT_TAB;
  }

  // Exposed so a payload that boots after us can ask what is on screen
  // without re-parsing the hash itself.
  window.JcTabs = { current: tabFromHash };

  function select(name, focus) {
    var found = false;
    tabs().forEach((t) => {
      var on = t.getAttribute("data-tab") === name;
      found = found || on;
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
      if (on && focus) t.focus();
      var panel = document.getElementById(t.getAttribute("aria-controls"));
      if (panel) panel.hidden = !on;
    });
    if (!found) return;
    if (window.location.hash !== `#${name}`) {
      // replaceState, not assignment: switching tabs should not stack a
      // history entry per tap, but the URL still copy-pastes.
      history.replaceState(null, "", `#${name}`);
    }
    document.dispatchEvent(new CustomEvent("jc:tab", { detail: { tab: name } }));
    window.scrollTo(0, 0);
  }

  // --- sticky-stack measurement ---------------------------------------------
  // Each sticky layer sits at the summed height of the layers above it, so those
  // heights have to be exact. They are not knowable as literals: the topbar is
  // 88px on desktop and 67px on mobile (it reflows under 640px), and the display
  // face changes with the theme. Measure and publish; never hardcode.
  //
  // This is the bug it fixes: --topbar-h was a guessed 60px, so the tab bar
  // pinned 60px down from the viewport top while the 88px topbar scrolled away,
  // leaving a 28px band of page visible above it.
  function measure() {
    var root = document.documentElement;
    var set = (name, sel) => {
      var el = document.querySelector(sel);
      if (el) root.style.setProperty(name, `${Math.round(el.getBoundingClientRect().height)}px`);
    };
    set("--topbar-h", ".topbar");
    set("--jc-tabs-h", ".jc-tabs");
    // sub-tab bars are per-panel and identical in height; the visible one wins
    var sub = Array.prototype.slice.call(document.querySelectorAll(".jc-subtabs"))
      .filter((e) => e.offsetParent !== null)[0];
    if (sub) root.style.setProperty("--jc-subtabs-h", `${Math.round(sub.getBoundingClientRect().height)}px`);
  }

  function init() {
    var list = tabs();
    if (!list.length) return;

    measure();
    window.addEventListener("resize", measure);
    // the bar back panel mounts its sub-tabs later (React, on first activation),
    // and webfonts land after first paint — both change the measured heights
    document.addEventListener("jc:tab", () => { setTimeout(measure, 0); });
    if (document.fonts?.ready) document.fonts.ready.then(measure);

    list.forEach((t, i) => {
      t.addEventListener("click", () => { select(t.getAttribute("data-tab")); });
      t.addEventListener("keydown", (e) => {
        if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
        e.preventDefault();
        var next = list[(i + (e.key === "ArrowRight" ? 1 : -1) + list.length) % list.length];
        select(next.getAttribute("data-tab"), true);
      });
    });

    window.addEventListener("hashchange", () => { select(tabFromHash()); });
    select(tabFromHash());
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
