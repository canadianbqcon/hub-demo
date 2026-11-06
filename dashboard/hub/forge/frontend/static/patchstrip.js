/* The patch strip, shared by the landing page and the editor.
 *
 * What it says: the statistics were measured on one patch and the game is on a
 * newer one, so anything Riot touched in between makes the figures above it a
 * description of the old item. That is a caveat, not a feature, which is why it
 * renders small and says nothing when nothing moved.
 *
 * Markup comes from .patchstrip / .change in forge-base.css.
 */

const esc = s => String(s).replace(/[&<>"]/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

/* Collapsed to the icon. The strip answers one question — "did anything under my
 * figures move" — and nine two-line cards answered it by pushing the shop below
 * the fold. The border carries the direction, the hover card carries the numbers.
 *
 * `verdict` is baked by build_diff.py rather than read off the changes here: the
 * rule that makes it useful (a tooltip rewrite rides along with every stat change
 * and must not count) is worth exactly one implementation, and it has a self-check
 * next to it. */
export function changeHTML(entry, mine = false) {
  return `<div class="change${mine ? ' mine' : ''}${entry.champ ? ' champ' : ''}" data-change="${esc(entry.id)}"
       data-verdict="${esc(entry.verdict || 'rework')}" tabindex="0" role="button"
       aria-label="${esc(entry.name)}, ${esc(entry.verdict || 'changed')} this patch">
    ${entry.icon ? `<img src="${entry.icon}" alt="">` : '<i></i>'}
  </div>`;
}

/* The hover card the collapsed icon opens. It is where the word lives: a border
 * colour alone is the same number to about 8% of men, so BUFF / NERF / REWORK is
 * printed, not implied — the rule the patch page's own badges already follow.
 *
 * Two shapes of change come out of build_diff.py and they read differently. A
 * LABELLED row is Riot's own "Attack Damage: 40 ⇒ 45" (or a figure read out of a
 * description) and belongs in the two-column grid. An `effect` row is a rewritten
 * tooltip line with no label at all, and only ever comes off the Data Dragon
 * fallback path; the honest way to show it is the old line struck above the new
 * one, since it used to be a note saying the text had changed without saying to
 * what. `why` is Riot's own reasoning, which the changelog carries and no diff can. */
export function changeCardHTML(entry) {
  const v = entry.verdict || 'rework';
  const changes = (entry.changes || []).filter(c => c.from !== null || c.to !== null);
  const val = (n, c) => esc(n) + (c.unit || '');
  const figs = changes
    .filter(c => !c.text)
    // Riot's "NEW" shape has no before at all, so there is nothing to arrow from
    .map(c => `<span class="k">${esc(c.label || c.field)}</span>`
            + (c.from === null || c.from === undefined
                ? `<b>${val(c.to, c)}</b>`
                : `<span><span class="was">${val(c.from, c)}</span> \u2192 <b>${val(c.to, c)}</b></span>`));
  const prose = changes
    .filter(c => c.text)
    .map(c => `<p class="hc-pas">`
            + (c.from ? `<s class="was">${esc(c.from)}</s>${c.to ? '<br>' : ''}` : '')
            + (c.to ? esc(c.to) : '')
            + `</p>`);
  const notes = [];
  if (entry.kind === 'added') notes.push('New this patch.');
  else if (entry.kind === 'removed') notes.push('Removed from the game.');
  return `<h4>${esc(entry.name)}<b class="verdict" data-verdict="${esc(v)}">`
    + `${esc(v.toUpperCase())}</b></h4>`
    + notes.map(n => `<p class="hc-pas">${esc(n)}</p>`).join('')
    + (figs.length ? `<div class="hc-figs">${figs.join('')}</div>` : '')
    + (prose.length ? `<div class="hc-txt">${prose.join('')}</div>` : '')
    // Riot's reasoning goes last: it is the longest thing on the card and the
    // question the strip answers is what moved, not why.
    + (entry.why ? `<p class="hc-why">${esc(entry.why)}</p>` : '');
}

/* `mine` is the set of item ids the champion on screen actually buys. The border
 * is spoken for by the verdict now, so those read at full strength and the rest
 * sit back — which is the right weighting for a strip that is a caveat on THIS
 * champion's figures. The landing page passes nothing. */
export function renderStrip({ strip, title, changes, none }, diff, mine = null, champ = null) {
  const items = diff?.items || [];
  if (!diff?.to) { strip.hidden = true; return; }
  strip.hidden = false;
  title.textContent = `Changed on ${diff.to}, since the ${diff.from} statistics`;
  // The champion the page is for leads the strip. Every figure above it is that
  // champion's, so Riot touching them is the loudest caveat on the page — louder
  // than any one item, which is why it sits first and always at full strength.
  const who = champ && diff.champions?.[champ.name];
  const head = who ? changeHTML({ ...who, id: `champ:${champ.name}`,
                                  icon: champ.icon, champ: true }, true) : '';
  changes.innerHTML = head
    + items.map(c => changeHTML(c, !!mine && mine.has(String(c.id)))).join('');
  none.hidden = items.length > 0 || !!who;
  if (!items.length && !who) {
    none.textContent = 'Nothing in the shop was touched. '
      + 'The figures above still describe the live items.';
  }
}
