/* hub · trips page, mount (2026-10-13): last script of the trips surface. Port of the tail of trips.js
   (lines 10654-10692): the laminate hotspot, the Escape handler, and the final call. The plain page ended in
   boot(); here U.mount() renders the React shell, whose layout effect calls boot(). Only caller of mount(). */
(() => {
const U = window.TripsUI;
const { closeModal } = U.fwd("closeModal");

  // ── the laminate hotspot ─────────────────────────────────────────────────────
  // One delegated listener for the whole board rather than one per card: the
  // pass cards are rebuilt on every repaint, and per-card listeners would leak a
  // set each time. Two custom properties written per frame inside one rAF -
  // writing straight from pointermove forces a style recalc against the
  // browser's schedule instead of with it, which is what makes a grid of cards
  // stutter. No tilt: these sit in a dense two-up grid inside a scrolling pane,
  // and a card that leans when you pass over it on the way to something else is
  // noise, not feedback.
  (() => {
    let livePass = null, passFrame = 0, passAt = null;
    const paintPass = () => {
      passFrame = 0;
      if (!passAt) return;
      passAt.card.style.setProperty("--mx", `${passAt.x.toFixed(2)}%`);
      passAt.card.style.setProperty("--my", `${passAt.y.toFixed(2)}%`);
    };
    const dropPass = () => { if (livePass) livePass.classList.remove("is-live"); livePass = null; };
    document.addEventListener("pointermove", (e) => {
      const card = e.target.closest?.(".pass");
      if (!card) return dropPass();
      if (livePass !== card) { dropPass(); livePass = card; card.classList.add("is-live"); }
      const r = card.getBoundingClientRect();
      if (!r.width || !r.height) return;
      passAt = { card: card, x: ((e.clientX - r.left) / r.width) * 100,
        y: ((e.clientY - r.top) / r.height) * 100 };
      if (!passFrame) passFrame = requestAnimationFrame(paintPass);
    }, { passive: true });
    document.addEventListener("pointerleave", dropPass);
  })();

  // ── go ───────────────────────────────────────────────────────────────────────
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    closeModal();
    if (U.mut.closeConfirmActive) U.mut.closeConfirmActive();
  });
  U.mount();
})();
