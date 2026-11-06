/* The saved-build overlay: one build read back out, runes on the left and the item
 * set on the right, with Copy JSON / Edit / Copy-forward / Delete under it.
 *
 * It lives here rather than in champion.html because two surfaces raise it now. The
 * front door used to link a shelf row at the champion page and let that page open the
 * dialog off the hash, which meant a whole second page load - api/landing, api/sets and
 * runes.json all fetched again - to read a build you were already looking at. Now the
 * shelf pops it in place and the champion page calls the same function.
 *
 * Runes come first because they are the half that cannot be exported: the client has no
 * rune import, so this panel IS how a rune page gets into the game, read off and typed
 * in by hand.
 */
import { itemSetJSON, altSlotLabel, altReplaces, applyPassives } from './itemset.js';
import { planHTML } from './loadout.js';

const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;' }[c]));
const SHARD_ROWS = ['offense', 'flex', 'defense'];

/* The catalog is what turns item ids into icons and it is the heaviest file in the
 * tool. One fetch per page, on the first open, and kept: the list itself never pays for
 * it and every overlay after the first is instant. Module-level, so two mounts on one
 * page would still only fetch it once. */
let CAT = null;
/* The same file already carries the champion list and the Data Dragon version, and
 * the plan section needs both: champions to draw the bans, the version for the
 * summoner-spell icons. Kept beside the item map rather than fetched again. */
let CHAMPS = new Map(), VER = '';
export async function catalog() {
  if (!CAT) {
    /* Both in flight together: the passives file is a few KB against the
       catalog's 424, so it never decides when this resolves. */
    const [baked, passives] = await Promise.all([
      fetch('static/catalog.json').then(r => r.json()).catch(() => ({ items: [] })),
      fetch('api/passives').then(r => r.json()).catch(() => ({ items: {} })),
    ]);
    CAT = new Map(applyPassives(baked.items || [], passives).map(i => [String(i.id), i]));
    CHAMPS = new Map((baked.champs || []).map(c => [c.k, c]));
    VER = baked.ver || '';
  }
  return CAT;
}

/* Bans are keyed by champion, not by set, so two builds on one champion share one
 * answer and the second open of either costs nothing. */
const BANS = new Map();
export async function bansFor(champ) {
  if (!champ) return [];
  if (!BANS.has(champ)) {
    BANS.set(champ, await fetch(`api/bans/${encodeURIComponent(champ)}`)
      .then(r => r.json()).then(j => j.champions || []).catch(() => []));
  }
  return BANS.get(champ);
}

/* The champion list and Data Dragon version the same fetch carried, for the JSX overlay
 * (build-overlay.jsx) to render the plan with. Empty until catalog() has resolved. */
export const catalogExtras = () => ({ champs: CHAMPS, ver: VER });

/* Warm it while nothing is waiting on it, so the first pop-out does not stall on a
 * 400 KB download. Idle if the browser offers idle, a timeout if it does not.
 *
 * The three bake reads go with it. They are not what the overlay needs — they are what
 * the BUILDER needs, and the builder is one click from every surface that calls this.
 * Pulling them into the cache while the shelf sits idle is the difference between
 * opening a build in half a second and opening it in a quarter of one; the browser
 * still revalidates each on the way in, so nothing here can serve a stale bake. */
export function prefetchCatalog() {
  const go = () => {
    // The three small ones go first on purpose. A warm-up is only worth what it
    // finishes before the click that ends it, and 90 KB of bake reads land in the time
    // the 260 KB catalog spends on its first third.
    // .blob() matters: a response whose body is never read is not committed to the
    // HTTP cache, so a bare fetch() here would spend the bytes and warm nothing.
    for (const u of ['api/stats', 'api/lolalytics', 'api/diff'])
      fetch(u).then(r => r.blob()).catch(() => {});
    catalog();
  };
  if (typeof requestIdleCallback === 'function') requestIdleCallback(go, { timeout: 2500 });
  else setTimeout(go, 400);
}

/* Mount the overlay on a <dialog>. Returns { open }.
 *
 *   dialog   - the <dialog> element to fill and show
 *   runedex  - the parsed runes.json: { runes, trees }
 *   live     - the live two-part patch, for the "copy forward" offer
 *   onChanged- called after a fork or a delete, so the page behind can repaint
 */
export function mountBuildOverlay({ dialog, runedex, live, onChanged }) {
  dialog.classList.add('buildov');

  const runeMeta = id => runedex?.runes?.[String(id)] || null;
  const treeMeta = id => runedex?.trees?.[String(id)] || null;

  /* The hover card lives INSIDE the dialog, not on body. A modal dialog renders in the
     browser's top layer, which no z-index outside it can climb over, so a card parented
     to body would sit behind the backdrop and be invisible. open() rewrites the dialog's
     markup every time, so it is re-appended there on each open. */
  const CARD = document.createElement('div');
  CARD.className = 'hovercard';
  CARD.hidden = true;

  const hideCard = () => { CARD.hidden = true; };

  /* One card, two subjects. A rune says what the rune does; an item leads with
     the note written for THIS build, because that sentence is the only thing on
     the overlay that knows why the item is in it. Items used to carry a `title`
     attribute here, which is the thing this module has a rule against: a second
     of hover, unstyleable, and no room for a note. */
  function cardHTML(el) {
    if (el.dataset.rune) {
      const m = runeMeta(+el.dataset.rune);
      return m ? `<h4>${esc(m.name)}</h4><p>${esc(m.long || m.short || '')}</p>` : '';
    }
    const m = CAT?.get(String(el.dataset.item));
    const note = el.dataset.note;
    return `<h4>${esc(m?.n || el.dataset.item)}${
      m?.g != null ? `<b>${m.g.toLocaleString()}g</b>` : ''}</h4>`
      + (note ? `<p class="hc-note">${esc(note)}</p>` : '')
      + (m?.ps?.length ? `<p>${esc(m.ps.map(b => b.t).join('\n'))}</p>` : '');
  }

  function showCard(el) {
    const html = cardHTML(el);
    if (!html) return;
    CARD.innerHTML = html;
    CARD.hidden = false;
    const r = el.getBoundingClientRect(), c = CARD.getBoundingClientRect();
    const x = r.right + 12 + c.width < innerWidth ? r.right + 12 : r.left - 12 - c.width;
    CARD.style.left = `${Math.max(8, x)}px`;
    CARD.style.top = `${Math.max(8, Math.min(r.top, innerHeight - c.height - 8))}px`;
  }

  function runeRowHTML(id, key) {
    const m = runeMeta(id);
    if (!m) return '';
    return `<div class="rp-row" data-rune="${id}"><span class="${key ? 'key' : ''}">
      <img src="${esc(m.icon)}" alt=""></span><span class="nm">${esc(m.name)}</span></div>`;
  }

  /* The alternatives read as sentences, not as a second rune page: the swap, what
     it replaces, and when you make it. Read the page you built first, then this.
     A build saved before alternatives existed has no `alts` and renders nothing,
     which is the correct amount of chrome for a build that has nothing to say. */
  function altsHTML(r) {
    const alts = r?.alts || [];
    if (!alts.length) return '';
    /* Both reads come from static/itemset.js, shared with the builder that wrote
       these. Only the name lookup is local. */
    const insteadOf = a => {
      const cur = altReplaces(r, a, id => runeMeta(id)?.row);
      if (!cur) return '';
      return `instead of ${(a.slot === 'secondary' ? treeMeta(cur) : runeMeta(cur))?.name || ''} \u00b7 `;
    };

    const rows = alts.map(a => {
      const isTree = a.slot === 'secondary';
      const m = isTree ? treeMeta(a.tree) : runeMeta(a.id);
      if (!m) return '';
      const withRunes = isTree && (a.sec || []).length
        ? ` with ${a.sec.map(x => runeMeta(x)?.name).filter(Boolean).join(' and ')}` : '';
      return `<div class="rp-alt">
        <img src="${esc(m.icon)}" alt="">
        <p class="rp-who"><b>${esc(m.name)}</b>${esc(withRunes)}
          <span>${esc(insteadOf(a))}${esc(altSlotLabel(a.slot))}</span></p>
        <p class="rp-note">${esc(a.note || '')}</p>
      </div>`;
    }).join('');
    return rows ? `<div class="rp-alts"><h5>Alternatives</h5>${rows}</div>` : '';
  }

  function runePageHTML(r) {
    if (!r?.keystone) return '<p class="quiet">No rune page was saved with this build.</p>';
    const tree = t => {
      const m = treeMeta(t);
      return m ? `<div class="rp-tree">${m.icon ? `<img src="${esc(m.icon)}" alt="">` : ''}
        <span>${esc(m.name)}</span></div>` : '';
    };
    const shards = SHARD_ROWS.map(k => {
      const m = runeMeta(r.shards?.[k]);
      return m ? `<span data-rune="${r.shards[k]}"><img src="${esc(m.icon)}" alt="">${esc(m.name)}</span>` : '';
    }).join('');

    return `<div class="rp">
      ${tree(r.primary)}
      ${runeRowHTML(r.keystone, true)}
      ${(r.rows || []).map(id => runeRowHTML(id)).join('')}
      ${r.secondary ? tree(r.secondary) : ''}
      ${(r.sec || []).map(id => runeRowHTML(id)).join('')}
      ${shards ? `<div class="rp-shards">${shards}</div>` : ''}
    </div>${altsHTML(r)}`;
  }

  function blocksHTML(s, items) {
    const filled = (s.blocks || []).filter(b => b.items?.length);
    if (!filled.length) return '<p class="quiet">No items yet. This build is the rune page so far.</p>';
    return filled.map(b => `<div class="ov-block">
      <h5>${esc(b.type || 'Items')}</h5>
      <div class="ov-items">${b.items.map(it => {
        const m = items.get(String(it.id));
        // data-noted is the only hint that there are words here; the words
        // themselves are one hover away, on the card
        return `<span class="it" data-item="${esc(it.id)}"${
          it.note ? ` data-note="${esc(it.note)}" data-noted` : ''}>
          <img src="${m ? m.u : ''}" alt="${esc(m?.n || it.id)}">
          ${it.count > 1 ? `<span class="count">${it.count}</span>` : ''}</span>`;
      }).join('')}</div>
    </div>`).join('');
  }

  let OPEN = null;

  async function open(s) {
    if (!s) return;
    OPEN = s;
    const items = await catalog();
    const stale = s.patch !== live;
    // What you bring, how you level, where you walk, and who you ban. Same renderer
    // the builder authors with, so the page read back is the page authored.
    const plan = planHTML(s.plan, {
      ver: VER, role: s.role, bans: await bansFor(s.champion), byKey: CHAMPS,
    });

    dialog.innerHTML = `
      <div class="ov-head">
        <h2>${esc(s.name)}</h2>
        <span class="meta">patch ${esc(s.patch)}</span>
        ${s.champion ? `<span class="meta">${esc(s.champion)}</span>` : ''}
        ${s.role ? `<span class="meta">${esc(s.role)}</span>` : ''}
        <span class="grow"></span>
        <button class="x" data-act="close" aria-label="Close">&times;</button>
      </div>
      <div class="ov-body">
        <section>
          <h4>Rune page${stale ? ` · as built on ${esc(s.patch)}` : ''}</h4>
          ${runePageHTML(s.runes)}
        </section>
        <section>
          <h4>Item set</h4>
          ${blocksHTML(s, items)}
        </section>
        ${plan ? `<section class="ov-plan"><h4>Plan</h4>${plan}</section>` : ''}
      </div>
      <div class="ov-foot">
        ${stale && live ? `<button class="btn-primary" data-act="fork">Copy to patch ${esc(live)}</button>` : ''}
        <button data-act="edit">Edit</button>
        <button data-act="json">Copy JSON</button>
        <button class="kill" data-act="delete">Delete</button>
      </div>`;
    dialog.append(CARD);      // the innerHTML above just dropped it; see the CARD note
    dialog.showModal();
  }

  dialog.addEventListener('mouseover', e => {
    const el = e.target.closest('[data-rune], [data-item]');
    if (el) showCard(el); else hideCard();
  });
  dialog.addEventListener('mouseleave', hideCard);
  dialog.addEventListener('scroll', hideCard, true);
  dialog.addEventListener('close', hideCard);

  dialog.addEventListener('click', async e => {
    const btn = e.target.closest('[data-act]');
    const act = btn?.dataset.act;
    if (!act || !OPEN) return;
    const s = OPEN;

    if (act === 'close') return dialog.close();

    if (act === 'edit') {
      // a set saved with no champion has no /c/<champ>/ to live under, and the
      // editor's bare /edit reads ?set= the same way
      location.href = s.champion
        ? `c/${encodeURIComponent(s.champion)}/${encodeURIComponent(s.role || 'jungle')}`
          + `/build?set=${encodeURIComponent(s.id)}`
        : `edit?set=${encodeURIComponent(s.id)}`;
      return;
    }

    if (act === 'json') {
      const text = JSON.stringify(itemSetJSON({
        title: s.name, champions: s.champions, blocks: s.blocks,
      }), null, 2);
      try { await navigator.clipboard.writeText(text); } catch {
        const ta = document.createElement('textarea');
        ta.value = text; document.body.append(ta); ta.select();
        document.execCommand('copy'); ta.remove();
      }
      const was = btn.textContent;
      btn.textContent = 'Copied';
      setTimeout(() => { btn.textContent = was; }, 1300);
      return;
    }

    if (act === 'fork') {
      // a copy forward is just a save under the live patch: same name, so the
      // library's own (name, patch) versioning does the forking
      const r = await fetch('api/sets', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: s.name, patch: live, champion: s.champion, role: s.role,
          champions: s.champions || [], runes: s.runes || null, blocks: s.blocks || [],
          plan: s.plan || null,
        }),
      });
      const out = await r.json().catch(() => ({}));
      if (!r.ok) return alert(out.error || 'That copy did not save.');
      dialog.close();
      return onChanged?.();
    }

    if (act === 'delete') {
      if (!confirm(`Delete the patch ${s.patch} version of "${s.name}"? The other patches stay.`)) return;
      await fetch(`api/sets/${encodeURIComponent(s.id)}`, { method: 'DELETE' });
      dialog.close();
      return onChanged?.();
    }
  });

  return { open };
}
