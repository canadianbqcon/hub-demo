/* build-overlay.jsx - the saved-build overlay, as React.

   One build read back out, runes on the left and the item set on the right, with
   Copy JSON / Edit / Copy-forward / Delete under it. The markup half of build-overlay.js:
   that module stays (its catalog and ban fetches are reached through window.ForgeLib, as
   are itemSetJSON and the rune-alternative helpers), so the fork POST, the DELETE and the
   Copy JSON text come from the same code as before. The read-only plan section is
   rendered here from loadout.js's tables rather than through planHTML, whose output is a
   string and cannot sit beside React children.

   Seam: ForgeUI.mountBuildOverlay({ dialog, runedex, live, onChanged }) returns { open },
   the same shape as ForgeLib.mountBuildOverlay. React owns the dialog's children through
   its own root; the dialog element itself belongs to the caller. Events stay delegated off
   the dialog, as before, and drive a closure view that is painted with flushSync so the
   markup is in place before showModal(). */
window.ForgeUI = window.ForgeUI || {};

(() => {
  const { useRef, useLayoutEffect } = React;
  const UI = window.ForgeUI;
  const lib = () => window.ForgeLib;
  const SHARD_ROWS = ['offense', 'flex', 'defense'];

  /* The hover card lives INSIDE the dialog, not on body. A modal dialog renders in the
     browser's top layer, which no z-index outside it can climb over, so a card parented
     to body would sit behind the backdrop and be invisible. */
  function Card({ card }) {
    const ref = useRef(null);
    useLayoutEffect(() => {
      if (!card) return;
      const r = card.el.getBoundingClientRect(), c = ref.current.getBoundingClientRect();
      const x = r.right + 12 + c.width < innerWidth ? r.right + 12 : r.left - 12 - c.width;
      ref.current.style.left = `${Math.max(8, x)}px`;
      ref.current.style.top = `${Math.max(8, Math.min(r.top, innerHeight - c.height - 8))}px`;
    });
    return <div className="hovercard" ref={ref} hidden={!card}>{card ? card.body : null}</div>;
  }

  const Sep = () => <i>{'›'}</i>;
  const joined = (list, sep) => list.reduce((acc, x, i) => (i ? acc.concat([sep(i), x]) : [x]), []);

  /* The plan, read-only: what you bring, how you level, where you walk, who you ban.
     Same shape loadout.js authors; `bans` comes in rather than being fetched here. */
  function planParts(rawPlan, { ver, role, bans, byKey }) {
    const L = lib();
    const plan = L.normalisePlan(rawPlan);
    const jungle = String(role || '').toLowerCase() === 'jungle';
    const parts = [];

    if (plan.spells.length) {
      parts.push(['Summoner spells', (
        <div className="pl-spells">{plan.spells.map(id => {
          const s = L.SPELLS.find(x => x.id === id);
          const note = plan.spellNotes[String(id)];
          return (
            <span className={`pl-spell${note ? ' noted' : ''}`} title={note || undefined} key={id}>
              <img src={L.spellIcon(s, ver)} alt="" width="28" height="28" loading="lazy" />
              {' '}{s.n}</span>
          );
        })}</div>
      )]);
    }

    if (plan.skills.some(Boolean)) {
      const order = L.maxOrder(plan.skills);
      parts.push(['Ability levels', (
        <React.Fragment>
          <div className="pl-skills">
            <div className="pl-sk-lv"></div>
            {plan.skills.map((_, i) => (
              <div className={`pl-sk-lv${L.ULT_LEVELS.includes(i + 1) ? ' ult' : ''}`} key={i}>{i + 1}</div>
            ))}
            {L.ABILITIES.map(a => (
              <React.Fragment key={a}>
                <div className="pl-sk-key">{a}</div>
                {plan.skills.map((got, i) => {
                  const lv = i + 1, on = got === a, legal = L.legalAt(a, lv);
                  return (
                    <div className={`pl-sk${on ? ' on' : ''}${legal ? '' : ' off'}`} key={lv}
                         data-ult={L.ULT_LEVELS.includes(lv) ? '' : undefined}>{on ? a : ''}</div>
                  );
                })}
              </React.Fragment>
            ))}
          </div>
          <p className="pl-order">{order.length
            ? <React.Fragment>{'max order '}<b>{order.join(' > ')}</b></React.Fragment>
            : 'max order reads off the grid once points are placed'}</p>
        </React.Fragment>
      )]);
    }

    // A path on a mid set is noise, and the ONLY thing that makes it noise is the
    // role, so the role is what gates it rather than whether one happens to exist.
    if (jungle && plan.paths.length) {
      parts.push(['Jungle pathing', (
        <ul className="pl-paths">{plan.paths.map((p, n) => (
          <li key={n}>
            <span className="pl-path-nm">{p.name || 'Unnamed path'}</span>
            <span className="pl-route">{joined(p.camps.map((c, at) => {
              const camp = L.CAMPS.find(x => x.id === c);
              return <span className="pl-camp" data-g={camp.g} key={at}>{camp.n}</span>;
            }), i => <Sep key={`s${i}`} />)}</span>
            {p.note ? <span className="pl-note">{p.note}</span> : null}
          </li>
        ))}</ul>
      )]);
    }

    if (bans?.length) {
      parts.push(['Bans', (
        <div className="pl-bans">{bans.map(k => {
          const c = byKey.get(k) || byKey.get(String(k));
          return c ? (
            <span className="pl-ban" key={k}><img src={c.u} alt="" width="24" height="24" loading="lazy" /> {c.n}</span>
          ) : null;
        })}</div>
      )]);
    }
    return parts;
  }

  function Overlay({ v, card, copied, runedex, live }) {
    const runeMeta = id => runedex?.runes?.[String(id)] || null;
    const treeMeta = id => runedex?.trees?.[String(id)] || null;
    const L = lib();
    const s = v.s;
    const stale = s.patch !== live;

    const runeRow = (id, key) => {
      const m = runeMeta(id);
      if (!m) return null;
      return (
        <div className="rp-row" data-rune={id} key={id}><span className={key ? 'key' : ''}>
          <img src={m.icon} alt="" /></span><span className="nm">{m.name}</span></div>
      );
    };

    /* The alternatives read as sentences, not as a second rune page: the swap, what
       it replaces, and when you make it. A build saved before alternatives existed has
       no `alts` and renders nothing, which is the correct amount of chrome for a build
       that has nothing to say. Both reads come from static/itemset.js, shared with the
       builder that wrote these. Only the name lookup is local. */
    const alts = r => {
      const list = r?.alts || [];
      if (!list.length) return null;
      const insteadOf = a => {
        const cur = L.altReplaces(r, a, id => runeMeta(id)?.row);
        if (!cur) return '';
        return `instead of ${(a.slot === 'secondary' ? treeMeta(cur) : runeMeta(cur))?.name || ''} · `;
      };
      const rows = list.map((a, i) => {
        const isTree = a.slot === 'secondary';
        const m = isTree ? treeMeta(a.tree) : runeMeta(a.id);
        if (!m) return null;
        const withRunes = isTree && (a.sec || []).length
          ? ` with ${a.sec.map(x => runeMeta(x)?.name).filter(Boolean).join(' and ')}` : '';
        return (
          <div className="rp-alt" key={i}>
            <img src={m.icon} alt="" />
            <p className="rp-who"><b>{m.name}</b>{withRunes}
              <span>{insteadOf(a) + L.altSlotLabel(a.slot)}</span></p>
            <p className="rp-note">{a.note || ''}</p>
          </div>
        );
      });
      return rows.some(Boolean) ? <div className="rp-alts"><h5>Alternatives</h5>{rows}</div> : null;
    };

    const runePage = r => {
      if (!r?.keystone) return <p className="quiet">No rune page was saved with this build.</p>;
      const tree = t => {
        const m = treeMeta(t);
        return m ? <div className="rp-tree">{m.icon ? <img src={m.icon} alt="" /> : null}<span>{m.name}</span></div> : null;
      };
      const shards = SHARD_ROWS.map(k => {
        const m = runeMeta(r.shards?.[k]);
        return m ? <span data-rune={r.shards[k]} key={k}><img src={m.icon} alt="" />{m.name}</span> : null;
      }).filter(Boolean);
      return (
        <React.Fragment>
          <div className="rp">
            {tree(r.primary)}
            {runeRow(r.keystone, true)}
            {(r.rows || []).map(id => runeRow(id))}
            {r.secondary ? tree(r.secondary) : null}
            {(r.sec || []).map(id => runeRow(id))}
            {shards.length ? <div className="rp-shards">{shards}</div> : null}
          </div>
          {alts(r)}
        </React.Fragment>
      );
    };

    const filled = (s.blocks || []).filter(b => b.items?.length);
    const blocks = !filled.length
      ? <p className="quiet">No items yet. This build is the rune page so far.</p>
      : filled.map((b, n) => (
        <div className="ov-block" key={n}>
          <h5>{b.type || 'Items'}</h5>
          <div className="ov-items">{b.items.map((it, i) => {
            const m = v.items.get(String(it.id));
            // data-noted is the only hint that there are words here; the words
            // themselves are one hover away, on the card
            return (
              <span className="it" data-item={it.id} data-note={it.note || undefined}
                    data-noted={it.note ? '' : undefined} key={i}>
                <img src={m ? m.u : ''} alt={m?.n || String(it.id)} />
                {it.count > 1 ? <span className="count">{it.count}</span> : null}</span>
            );
          })}</div>
        </div>
      ));

    const plan = planParts(s.plan, { ver: v.ver, role: s.role, bans: v.bans, byKey: v.champs });

    return (
      <React.Fragment>
        <div className="ov-head">
          <h2>{s.name}</h2>
          <span className="meta">{`patch ${s.patch}`}</span>
          {s.champion ? <span className="meta">{s.champion}</span> : null}
          {s.role ? <span className="meta">{s.role}</span> : null}
          <span className="grow"></span>
          <button type="button" className="x" data-act="close" aria-label="Close">{'×'}</button>
        </div>
        <div className="ov-body">
          <section>
            <h4>{`Rune page${stale ? ` · as built on ${s.patch}` : ''}`}</h4>
            {runePage(s.runes)}
          </section>
          <section>
            <h4>Item set</h4>
            {blocks}
          </section>
          {plan.length ? (
            <section className="ov-plan"><h4>Plan</h4>{plan.map(([h, body]) => (
              <React.Fragment key={h}><h4 className="pl-h">{h}</h4>{body}</React.Fragment>
            ))}</section>
          ) : null}
        </div>
        <div className="ov-foot">
          {/* no carry-forward for an Auto set: Autobuild on the new patch rebuilds it */}
          {stale && live && s.auto !== true ? <button type="button" className="btn-primary" data-act="fork">{`Copy to patch ${live}`}</button> : null}
          <button type="button" data-act="edit">{s.auto === true ? 'Open' : 'Edit'}</button>
          <button type="button" data-act="json">{copied ? 'Copied' : 'Copy JSON'}</button>
          <button type="button" className="kill" data-act="delete">Delete</button>
        </div>
        <Card card={card} />
      </React.Fragment>
    );
  }

  /* Mount the overlay on a <dialog>. Returns { open }.

       dialog   - the <dialog> element to fill and show
       runedex  - the parsed runes.json: { runes, trees }
       live     - the live two-part patch, for the "copy forward" offer
       onChanged- called after a fork or a delete, so the page behind can repaint */
  function mountBuildOverlay(opts) {
    const dialog = opts.dialog, runedex = opts.runedex, live = opts.live, onChanged = opts.onChanged;
    dialog.classList.add('buildov');
    const root = ReactDOM.createRoot(dialog);
    const runeMeta = id => runedex?.runes?.[String(id)] || null;

    let OPEN = null, view = null, card = null, copied = false;
    const paint = () => {
      if (!view) return;
      // flushSync: the markup has to be in the dialog before showModal() and before any click
      ReactDOM.flushSync(() => root.render(<Overlay v={view} card={card} copied={copied} runedex={runedex} live={live} />));
    };

    /* One card, two subjects. A rune says what the rune does; an item leads with
       the note written for THIS build, because that sentence is the only thing on
       the overlay that knows why the item is in it. */
    function cardFor(el) {
      if (el.dataset.rune) {
        const m = runeMeta(+el.dataset.rune);
        return m ? <React.Fragment><h4>{m.name}</h4><p>{m.long || m.short || ''}</p></React.Fragment> : null;
      }
      const m = view.items.get(String(el.dataset.item));
      const note = el.dataset.note;
      return (
        <React.Fragment>
          <h4>{m?.n || el.dataset.item}{m?.g != null ? <b>{`${m.g.toLocaleString()}g`}</b> : null}</h4>
          {note ? <p className="hc-note">{note}</p> : null}
          {m?.ps?.length ? <p>{m.ps.map(b => b.t).join('\n')}</p> : null}
        </React.Fragment>
      );
    }
    const hideCard = () => { if (card) { card = null; paint(); } };

    function open(s) {
      if (!s) return Promise.resolve();
      OPEN = s;
      const L = lib();
      return L.catalog().then(items => L.bansFor(s.champion).then(bans => {
        const x = L.catalogExtras();
        view = { s, items, bans, ver: x.ver, champs: x.champs };
        card = null; copied = false;
        paint();
        dialog.showModal();
      }));
    }

    dialog.addEventListener('mouseover', e => {
      const el = e.target.closest('[data-rune], [data-item]');
      if (!el) return hideCard();
      const body = cardFor(el);
      if (!body) return;
      card = { el, body };
      paint();
    });
    dialog.addEventListener('mouseleave', hideCard);
    dialog.addEventListener('scroll', hideCard, true);
    dialog.addEventListener('close', hideCard);

    dialog.addEventListener('click', e => {
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
        const text = JSON.stringify(lib().itemSetJSON({
          title: s.name, champions: s.champions, blocks: s.blocks,
        }), null, 2);
        return Promise.resolve().then(() => navigator.clipboard.writeText(text)).catch(() => {
          const ta = document.createElement('textarea');
          ta.value = text; document.body.append(ta); ta.select();
          document.execCommand('copy'); ta.remove();
        }).then(() => {
          copied = true; paint();
          setTimeout(() => { copied = false; paint(); }, 1300);
        });
      }

      if (act === 'fork') {
        // a copy forward is just a save under the live patch: same name, so the
        // library's own (name, patch) versioning does the forking
        return fetch('api/sets', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: s.name, patch: live, champion: s.champion, role: s.role,
            champions: s.champions || [], runes: s.runes || null, blocks: s.blocks || [],
            plan: s.plan || null,
          }),
        }).then(r => r.json().catch(() => ({})).then(out => {
          if (!r.ok) return alert(out.error || 'That copy did not save.');
          dialog.close();
          return onChanged?.();
        }));
      }

      if (act === 'delete') {
        if (!confirm(`Delete the patch ${s.patch} version of "${s.name}"? The other patches stay.`)) return;
        return fetch(`api/sets/${encodeURIComponent(s.id)}`, { method: 'DELETE' }).then(() => {
          dialog.close();
          return onChanged?.();
        });
      }
    });

    return { open };
  }

  UI.mountBuildOverlay = mountBuildOverlay;
})();
