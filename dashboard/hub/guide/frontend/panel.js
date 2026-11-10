// The Guide as a side panel (demo only). Open on a first visit; closing tucks it
// into a tab on the right edge, and the choice is kept in localStorage.
(() => {
  const p = document.getElementById('demo-guide'), tab = document.getElementById('demo-guide-tab');
  if (!p || !tab) return;
  // same-origin frames (trips view-as, phone previews) get the page alone
  if (window.self !== window.top) { p.remove(); tab.remove(); return; }
  const K = 'demo.guide', x = p.querySelector('.dg-x'), body = p.querySelector('.dg-body'),
        b = document.getElementById('demo-banner');
  let loaded = false;
  const top = () => document.documentElement.style.setProperty('--demo-top', (b ? b.offsetHeight : 0) + 'px');
  function load() {
    loaded = true;
    fetch('/guide/panel')
      .then(r => { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(h => { body.innerHTML = h; })
      .catch(() => { loaded = false; body.textContent = 'The guide did not load. Close and reopen to try again, or open /guide/.'; });
  }
  function set(open, focus) {
    if (open && !loaded) load();
    p.classList.toggle('is-closed', !open);
    tab.hidden = open;
    tab.setAttribute('aria-expanded', open);
    try { localStorage.setItem(K, open ? 'open' : 'closed'); } catch (_e) {}
    if (focus) (open ? x : tab).focus();
  }
  x.onclick = () => set(false, true);
  tab.onclick = () => set(true, true);
  const l = document.getElementById('demo-guide-link');
  if (l) l.onclick = e => { e.preventDefault(); set(p.classList.contains('is-closed'), true); };
  addEventListener('keydown', e => {
    if (e.key !== 'Escape' || e.defaultPrevented || p.classList.contains('is-closed')) return;
    const a = document.activeElement;
    // a Hub modal or field owns Escape unless focus is on the page or in the panel
    if (a && a !== document.body && !p.contains(a)) return;
    set(false, true);
  });
  addEventListener('resize', top);
  top();
  let s = null;
  try { s = localStorage.getItem(K); } catch (_e) {}
  set(s !== 'closed', false);
})();
