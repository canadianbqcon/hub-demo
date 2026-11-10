"""Cold verification of the Forge builder, end to end, in a real browser.

    python3 verify_frontend.py            # the Hub must already be up on 5002

Fresh browser context every run, no localStorage carried in. That is the whole
point and it is the module's own rule: driving the page into a state and
screenshotting the result is how the empty landing state went unnoticed for a
build, because every screenshot was of a page you cannot reach by opening it.

Two things this cannot do, and works around instead:

  * HTML5 drag and drop cannot be driven by Playwright. So the drop handlers are
    fired directly with a live DataTransfer and the RESULT is read back out of
    localStorage. That tests the logic, not the browser's drag chrome.
  * The two source headings are uppercased by CSS, so inner_text() comes back
    shouting. Every text assertion here lowercases first.

Exits non-zero on the first failing run, and prints every check either way.
Screenshots land in the Downloads process folder.
"""
import json
import re
import urllib.request
import sys
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import Error as PlaywrightError, sync_playwright

BASE = 'http://127.0.0.1:5002/forge'
SHOT = '/app/home/Downloads/forge-item-builder-rework'

SET_JSON = json.dumps({
    "title": "verify",
    "associatedChampions": [234],
    "blocks": [
        {"type": "Starting Items", "items": [
            {"id": "1055", "count": 1}, {"id": "2003", "count": 2}]},
        {"type": "Core", "items": [
            {"id": "6673", "count": 1}, {"id": "3153", "count": 1},
            {"id": "3072", "count": 1}]},
    ],
})

# Same set, Core opening on an item people actually rush. 6676 (The Collector)
# carries 39k games as a first legendary on Viego and is the fixture for a
# measured reading; 6673 (Immortal Shieldbow) is nobody's rush and is the fixture
# for the DROPPED path, where the condition has to be named as unmet rather than
# collapsing the shop to one thin row.
SET_RUSH = json.dumps({
    "title": "verify-rush",
    "associatedChampions": [234],
    "blocks": [
        {"type": "Starting Items", "items": [{"id": "1101", "count": 1}]},
        {"type": "Core", "items": [
            {"id": "6676", "count": 1}, {"id": "3036", "count": 1}]},
    ],
})

# Same rush, second slot on an item nobody actually takes second. 6676 -> 3033
# (Mortal Reminder) comes back nine rows with a 828-game top line, so the PAIR is
# under the floor while the single still carries 39k: the fixture for the middle
# state, where slot 0 reads and slot 1 has to say it was dropped. Without it the
# suite only ever sees both-read or both-thin, and a slot 1 that silently rides
# along on slot 0's ring is exactly the lie the marker exists to prevent.
SET_PAIR_THIN = json.dumps({
    "title": "verify-pair-thin",
    "associatedChampions": [234],
    "blocks": [
        {"type": "Starting Items", "items": [{"id": "1101", "count": 1}]},
        {"type": "Core", "items": [
            {"id": "6676", "count": 1}, {"id": "3033", "count": 1},
            {"id": "3031", "count": 1}]},
    ],
})

fails = []


def settle(was, ms=12000):
    """Wait for the shop legend to stop saying what it said before.

    Every conditioned reading is a live coachless call behind /api/conditioned, so
    the sentence and the figures land together some hundreds of ms after the
    click. Anything asserting on them has to wait for the change itself."""
    try:
        page.wait_for_function(
            "was => document.getElementById('metaWhere').textContent.trim() !== was",
            arg=was.strip(), timeout=ms)
    except Exception as e:  # the check that follows reports it with its own detail
        print(f"wait_for_change timed out: {e}", file=sys.stderr)
    page.wait_for_timeout(120)


def check(label, ok, detail: object = ''):
    print(('  PASS  ' if ok else '  FAIL  ') + label + (' :: ' + str(detail) if detail else ''))
    if not ok:
        fails.append(label)


# ── the layout at a half-snapped window ───────────────────────────────
# Sam snaps browsers to half of a 2560x1440 monitor, so 1280x1300 is a
# size the page is USED at, not an edge case. The page is height-locked, so
# any panel that is overflow:hidden and taller than its box has silently
# eaten its own content: it is still in the DOM and still in the tab order
# and completely unreachable with a mouse. That is how 302px of the stat
# filter went missing. Rule: wiki/patterns/dashboard-responsive-layout.md
# On a hit this also dumps what the page was still doing at that instant --
# fonts unloaded and images in flight both reflow a box after it was measured,
# and that is the difference between a real clip and a probe fired too early.
CLIP_PROBE = """() => {
  const out = [];
  document.querySelectorAll('*').forEach(el => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return;
    const cy = el.scrollHeight - el.clientHeight;
    const cx = el.scrollWidth - el.clientWidth;
    if ((cy > 2 || cx > 2) && (cs.overflowY === 'hidden' || cs.overflowX === 'hidden'))
      out.push((el.className || el.tagName) + ' x=' + cx + ' y=' + cy +
               ' [' + el.clientWidth + 'x' + el.clientHeight + ' -> ' +
               el.scrollWidth + 'x' + el.scrollHeight + ']' +
               ' kids=' + el.childElementCount);
  });
  if (out.length) {
    const imgs = [...document.images];
    out.push('DIAG fonts=' + document.fonts.status +
             ' imgsPending=' + imgs.filter(i => !i.complete).length +
             '/' + imgs.length +
             ' body=' + document.body.clientHeight + '/' +
             document.body.scrollHeight +
             ' ready=' + document.readyState);
  }
  return out;
}"""

def settled_clip(page):
    """Measure only once the page has stopped moving, and say so if it moved.

    This check reported a 44px BODY overflow once and then passed fifty-odd
    runs across four probe designs, including a 25ms sampler installed at
    document start. It cannot have been the layout: swept from 1300px down to
    400px of viewport height, body scrollHeight equals clientHeight at every
    step, because the page is a grid whose last row is minmax(0, 1fr) and
    absorbs anything the rows above it take. A reading the steady state cannot
    produce was taken before the state was steady.

    So this waits on the settling conditions themselves -- webfonts resolved,
    no image still in flight -- rather than on a longer sleep, then reads
    twice and only believes a clip that survives both. A hit on the first read
    and not the second prints as a settling artefact, which is what a check
    that goes red at random could never tell you.
    """
    try:
        page.wait_for_function(
            '() => document.fonts.status === "loaded"'
            ' && [...document.images].every(i => i.complete)', timeout=15000)
    except Exception:
        print('    (never settled in 15s; measuring anyway)')
    first = page.evaluate(CLIP_PROBE)
    page.wait_for_timeout(150)
    second = page.evaluate(CLIP_PROBE)
    if first and not second:
        print(f'    (settling artefact, gone on the second read: {first[:2]})')
    return second


CHAMP_SECTIONS = ('identity', 'abilities', 'play', 'traits', 'stats', 'history', 'sets')


def champion_link_pass(b, href, role, arch):
    """The champion page a seat links to: same role and archetype, every section, and
    a second archetype named in the URL is the one it opens on."""
    print('\n== the champion page from a seat ==')
    cc = b.new_context(viewport={'width': 1280, 'height': 900}, service_workers='block')
    pc = cc.new_page()
    errs = []
    pc.on('pageerror', lambda e: errs.append(str(e)))
    pc.goto(BASE.rsplit('/forge', 1)[0] + href)
    pc.wait_for_selector('.cp-arch.on', timeout=15000)
    on_role = pc.locator('.who .role.on').first.inner_text().split()[0] if pc.locator('.who .role.on').count() else ''
    check('the champion page opens on the seat\'s role', on_role == role, (on_role, role))
    check('the champion page opens on the seat\'s archetype',
          pc.locator('.cp-arch.on').first.get_attribute('data-arch') == arch,
          (pc.locator('.cp-arch.on').first.get_attribute('data-arch'), arch))
    missing = [s for s in CHAMP_SECTIONS if not pc.locator(f'#{s}').count()]
    check('the champion page mounts every section', not missing, missing)
    ids = pc.locator('.cp-arch').evaluate_all('els => els.map(e => e.dataset.arch)')
    if len(ids) > 1:
        pc.goto(f"{BASE.rsplit('/forge', 1)[0]}/forge/c/Viego/{role}?arch={ids[1]}")
        pc.wait_for_selector('.cp-arch.on', timeout=15000)
        check('an archetype named in the URL is the one selected',
              pc.locator('.cp-arch.on').first.get_attribute('data-arch') == ids[1])
    check('the champion page throws no error', not errs, errs[:2])
    cc.close()


def estimate_pass(b):
    """Nasus's damage rides on STACKS estimates; the page must never call it computed. Its own
    pass, run first, so a later pass that raises cannot skip it; a missing row or a timeout FAILs."""
    print('\n== an estimated trait on the champion page ==')
    cc = b.new_context(viewport={'width': 1280, 'height': 900}, service_workers='block')
    pc = cc.new_page()
    errs = []
    pc.on('pageerror', lambda e: errs.append(str(e)))
    try:
        pc.goto(f"{BASE.rsplit('/forge', 1)[0]}/forge/c/Nasus/top")
        pc.wait_for_selector('.cp-traits.wide .cp-t', timeout=15000)
        row = pc.locator('.cp-traits.wide .cp-t', has_text='10 s damage')
        notes = pc.locator('.cp-note', has_text=re.compile('^(Computed|Estimate):'))
        dmg = row.first.inner_text(timeout=5000) if row.count() else ''
        note = notes.first.inner_text(timeout=5000) if notes.count() else ''
        check('an estimated trait reads ~ with its range', '~' in dmg and ' to ' in dmg, dmg or 'no 10 s damage row')
        check('an estimated trait is not called computed', note.startswith('Estimate:'), note[:60] or 'no trait note')
        check('the Nasus page throws no error', not errs, errs[:2])
    except PlaywrightError as e:
        check('the Nasus estimate pass ran to its end', False, str(e).splitlines()[0])
    finally:
        cc.close()


def draft_pass(b):
    """The Draft page on two recorded feed bodies. `--draft` runs only this."""
    # ── the Draft page, on two recorded feed bodies ───────────────────────
    # api/draft is answered from tests/fixtures/forge_draft/page-*.json (whole
    # bodies from the real engines on a full 5v5), so the page is checked in both
    # states without a League client. capturedAt is restamped to now.
    import pathlib
    import time as _time
    fx = pathlib.Path(__file__).resolve().parent.parent / 'tests' / 'fixtures' / 'forge_draft'
    print('\n== the Draft page, mock ==')
    cm = b.new_context(viewport={'width': 1600, 'height': 1000}, service_workers='block')
    pm = cm.new_page()
    pm.goto(f'{BASE}/draft')
    pm.wait_for_selector('[data-react-mounted="forge-draft"]', timeout=15000)
    pm.locator('nav.modes a', has_text='Mock draft').click()
    pm.wait_for_selector('#allies select.pickc', timeout=10000)
    check('the Mock link stays on the Draft page', pm.url.endswith('/forge/draft?mock'), pm.url)
    check('mock status line', 'mock draft' in pm.locator('#status').inner_text())
    def no_bans():
        return {'bans': pm.locator('#bans').count(), 'heading': pm.locator('h3', has_text='Bans').count(),
                'aria': pm.locator('[aria-label^="Ban "]').count()}
    pickers = (pm.locator('#allies select.pickc').count(), pm.locator('#enemies select.pickc').count())
    check('five pickers a side', pickers == (5, 5), pickers)
    check('no bans drawn in mock', not any(no_bans().values()), no_bans())
    pm.locator('#allies select.pickc').first.select_option(label='Viego')
    pm.locator('#enemies select.pickc').first.select_option(label='Darius')
    pm.wait_for_selector('#pool .pick, #overall .pick', timeout=10000)
    check('a champion picked once is greyed out elsewhere',
          pm.locator('#enemies select.pickc').nth(1).locator('option', has_text='Viego').is_disabled())
    pm.wait_for_selector('#allies .ax-open', timeout=10000)
    check('a seated champion carries an archetype chip', pm.locator('#allies .ax-open').count() >= 1)
    pm.locator('#allies .ax-open').first.click()
    check('the chip opens the seat in place', pm.locator('#allies .seat .ax-body .ax-row').count() >= 1
          and pm.locator('#allies .ax-open').first.get_attribute('aria-expanded') == 'true')
    learn = pm.locator('#allies .seat .ax-body a.ax-learn')
    href = learn.first.get_attribute('href') if learn.count() else ''
    hm = re.search(r'/forge/c/Viego/([a-z]+)\?arch=(.+)$', href or '')
    check('the open seat links to the champion page at its role and archetype', bool(hm), href)
    if hm:
        champion_link_pass(b, href, hm.group(1), hm.group(2))
    pm.keyboard.press('Escape')
    check('Escape closes the seat', pm.locator('.ax-body').count() == 0)
    pm.screenshot(path=f'{SHOT}/10-draft-mock-picking.png', full_page=True)
    pm.locator('#allies input[type=checkbox]').check()
    pm.wait_for_selector('.locked', timeout=10000)
    check('locking in shows the build', pm.locator('.locked').count() == 1)
    pm.screenshot(path=f'{SHOT}/10-draft-mock-locked.png', full_page=True)
    def mock_query(r):
        return parse_qs(urlparse(r.url).query) if 'api/draft/mock' in r.url else {}
    pm.locator('#allies .ax-open').first.click()      # a build pick, for Shuffle to clear
    with pm.expect_response(lambda r: 'picks' in mock_query(r), timeout=15000):
        pm.locator('#allies .seat .ax-body .ax-row:not(.on)').first.click()
    pm.keyboard.press('Escape')
    def seated(r):
        q = mock_query(r)
        return len(q.get('allies', [''])[0].split(',')) == 4 and len(q.get('enemies', [''])[0].split(',')) == 5
    with pm.expect_response(seated, timeout=15000) as got:
        pm.locator('#shuffle').click()
    q = mock_query(got.value)
    check('Shuffle drops bans, queue and build picks from the mock request',
          not {'bans', 'queue', 'picks'} & set(q), sorted(q))
    check('Shuffle draws no bans', not any(no_bans().values()), no_bans())
    vals = pm.locator('#allies select.pickc').evaluate_all('els => els.map(e => e.value)') + \
           pm.locator('#enemies select.pickc').evaluate_all('els => els.map(e => e.value)')
    check('Shuffle fills every seat with no repeats, his pick kept',
          all(vals) and len(set(vals)) == 10 and pm.locator('#allies select.pickc').first.locator('option:checked').inner_text() == 'Viego', vals)
    pm.screenshot(path=f'{SHOT}/10-draft-mock-shuffled.png', full_page=True)
    cm.close()
    for state in ('picking', 'locked'):
        print(f'\n== the Draft page, {state} ==')
        body = json.loads((fx / f'page-{state}.json').read_text())
        body['capturedAt'] = _time.time() - 0.4
        body['advice']['stores']['opggFetchedAt'] = _time.time() - 120
        cd = b.new_context(viewport={'width': 1600, 'height': 1000}, service_workers='block')
        pd = cd.new_page()
        payload = json.dumps(body)
        pd.route('**/forge/api/draft', lambda r: r.fulfill(
            status=200, content_type='application/json', body=payload))
        pd.goto(f'{BASE}/draft')
        pd.wait_for_selector('[data-react-mounted="forge-draft"] #allies', timeout=15000)
        pd.wait_for_timeout(800)
        check('the Draft tab is the current one',
              pd.locator('a[aria-current="page"]:not(nav.modes a)').inner_text().strip().lower() == 'draft')
        check('five seats on each side',
              pd.locator('#allies .seat').count() == 5 and pd.locator('#enemies .seat').count() == 5)
        seats = sorted([*body['draft']['allies'], body['draft']['me']], key=lambda a: a['cellId'])
        missing = [a['cellId'] for i, a in enumerate(seats)
                   if a.get('championId') and not pd.locator('#allies .seat').nth(i).locator('img').count()]
        check('every locked ally has a portrait', not missing, missing)
        check('the live page draws every ban', pd.locator('#bans img').count() == len(body['draft']['bans']),
              (pd.locator('#bans img').count(), len(body['draft']['bans'])))
        check('status line reads live', 'live' in pd.locator('#status').inner_text())
        check('team traits card shows paired rows', pd.locator('#traits .tr').count() > 5,
              pd.locator('#traits .tr').count())
        gaps = len(body['advice']['gaps'])
        check('gap rows are marked', pd.locator('#traits .tr.gap').count() == gaps,
              (pd.locator('#traits .tr.gap').count(), gaps))
        if state == 'picking':
            check('best overall lists the engine rows',
                  pd.locator('#overall .pick').count() == len(body['advice']['overall']))
            check('pool lists every pool row',
                  pd.locator('#pool .pick').count() == len(body['advice']['pool']))
            first = body['advice']['overall'][0]
            check('first pick carries its score and reason',
                  first['champ'] in pd.locator('#overall .pick').first.inner_text()
                  and first['reason'][:20] in pd.locator('#overall .pick').first.inner_text())
            check('the me seat is highlighted and picking',
                  'picking now' in pd.locator('#allies .seat.me').inner_text())
        else:
            bd = body['build']
            n_steps = len(bd['items']) + (1 if bd.get('boots') else 0)
            check('build shows every step', pd.locator('#build .step').count() == n_steps,
                  (pd.locator('#build .step').count(), n_steps))
            check('plan names his job', body['advice']['plan']['job'] in pd.locator('#plan').inner_text())
            check('runes list keystone, 3 primary, 2 secondary, shards',
                  pd.locator('#runes .rune').count() == 7, pd.locator('#runes .rune').count())
            check('heal block shows when the build carries it',
                  (pd.locator('#heal').count() == 1) == bool(bd.get('heal')))
            check('the me seat says locked', 'locked' in pd.locator('#allies .seat.me').inner_text())
            check('every build step carries a why',
                  all(t.strip() for t in pd.locator('#build .step .why').all_inner_texts()))
            # Save as set against a stub, so the check never writes his set library;
            # the body is held to the same rules api._set_body_error applies.
            posted = []
            pd.route('**/forge/api/sets', lambda r: (posted.append(r.request.post_data_json),
                                                     r.fulfill(status=200, content_type='application/json',
                                                               body='{"ok": true}')))
            pd.click('#saveSet')
            pd.wait_for_timeout(500)
            sb = posted[0] if posted else {}
            check('Save as set posts a named, patched set with a why on every item',
                  sb.get('name') and sb.get('patch') and sb.get('blocks')
                  and all(i.get('id') and i.get('note') for i in sb['blocks'][0]['items'])
                  and (sb.get('runes') or {}).get('keystone') and len(sb['runes'].get('sec') or []) == 2,
                  {k: sb.get(k) for k in ('name', 'patch', 'champion', 'role')})
        broken = pd.evaluate("[...document.images].filter(i => i.complete && !i.naturalWidth).map(i => i.src.slice(0, 80))")
        check(f'draft {state}: every portrait, item and rune icon loaded', not broken, broken[:3])
        clipped = settled_clip(pd)
        check(f'draft {state}: nothing clipped by a hidden overflow', not clipped, clipped[:4])
        pd.screenshot(path=f'{SHOT}/10-draft-{state}.png', full_page=True)
        cd.close()


def guarded_draft_pass(b):
    try:
        draft_pass(b)
    except PlaywrightError as e:      # a timeout stops the pass, and the summary still names it
        check('the Draft pass ran to its end', False, str(e).splitlines()[0])


with sync_playwright() as pw:
    if '--draft' in sys.argv:
        _b = pw.chromium.launch(channel='chrome')
        guarded_draft_pass(_b)
        _b.close()
        print('\n' + ('ALL CHECKS PASSED' if not fails else f'{len(fails)} FAILED: ' + '; '.join(fails)))
        sys.exit(1 if fails else 0)
    b = pw.chromium.launch(channel='chrome')
    estimate_pass(b)   # first, so a later pass that raises cannot skip it
    ctx = b.new_context(viewport={'width': 1700, 'height': 1000})
    page = ctx.new_page()
    errs, bad = [], []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.on('response', lambda r: bad.append(f'{r.status} {r.url}') if r.status >= 400 else None)

    # ── step one, cold ────────────────────────────────────────────────────
    print('\n== the rune page, cold ==')
    page.goto(f'{BASE}/c/Viego/jungle/build', wait_until='networkidle')
    page.wait_for_timeout(700)
    check('the builder opens on the items, not the rune page',
          page.locator('#step2').is_visible() and page.locator('#step1').is_hidden()
          and page.locator('#shelves .item:visible').count() > 10,
          page.locator('#shelves .item:visible').count())
    page.locator('#stepnav [data-step="runes"]').click()
    page.wait_for_timeout(400)
    check('no uncaught script errors on load', not errs, errs[:3])
    check('every request answered', not bad, bad[:5])
    check('rune picker painted', page.locator('#primaryCol .rpick').count() > 0)

    # the hover card
    row = page.locator('#primaryCol .rpick').nth(1)
    row.hover()
    page.wait_for_timeout(250)
    card = page.locator('.hovercard')
    card_on = card.is_visible()
    card_text = card.inner_text() if card_on else ''
    check('rune hover card opens', card_on)
    check('hover card carries the long text', len(card_text) > 60, repr(card_text[:70]))
    page.screenshot(path=f'{SHOT}/01-rune-hover-card.png')

    # a shard click has to land on the shard it was clicked on: pick a row whose
    # current selection is NOT the one about to be clicked, so the assertion is
    # about the click landing rather than about the toggle
    picked0 = page.evaluate(
        "() => [...document.querySelectorAll('#shardCol .rrow')].map(r =>"
        " [...r.querySelectorAll('.rpick')].findIndex(b => b.getAttribute('aria-pressed') === 'true'))")
    want = 0 if picked0[0] != 0 else 2
    page.locator('#shardCol .rrow').first.locator('.rpick').nth(want).click()
    page.wait_for_timeout(200)
    picked = page.evaluate(
        "() => [...document.querySelectorAll('#shardCol .rrow')].map(r =>"
        " [...r.querySelectorAll('.rpick')].findIndex(b => b.getAttribute('aria-pressed') === 'true'))")
    check('the shard highlight lands on the shard clicked',
          picked[0] == want, f'was {picked0}, clicked {want}, now {picked}')
    check('the other two shard rows kept their picks',
          picked[1] == picked0[1] and picked[2] == picked0[2], picked)
    check('shards did not leak into the secondary list',
          page.locator('#secondaryCol .rpick[aria-pressed="true"]').count() <= 2)

    # The picker is built once and painted after. It used to reassign innerHTML on
    # all three columns per click, which threw the pressed button away mid-gesture:
    # the focus ring went to <body>, the hover card pointed at a dead node, and no
    # state change could transition because its element was gone. Nothing under
    # #step1 may be destroyed by a click any more, and the button must keep focus.
    print('\n== step 1: clicking around does not rebuild the picker ==')
    page.evaluate('''() => { window.__killed = 0;
      new MutationObserver(ms => { for (const m of ms) for (const n of m.removedNodes)
        if (n.nodeType === 1) window.__killed++; })
        .observe(document.getElementById('step1'), {childList: true, subtree: true}); }''')
    clicked = 0
    for sel in ('#primaryCol .rpick.key', '#primaryCol .rpick:not(.key)',
                '#secondaryCol .rpick', '#shardCol .rpick'):
        for el in [e for e in page.query_selector_all(sel) if e.is_visible()][:4]:
            el.click()
            page.wait_for_timeout(60)
            clicked += 1
    focused = page.evaluate("() => document.activeElement.className")
    check('the button you pressed still has focus', 'rpick' in focused, focused)

    # a tree switch swaps which panel is shown, it does not rebuild the column
    for side in ('primary', 'secondary'):
        for t in [e for e in page.query_selector_all(
                f'.treepick button[data-side="{side}"]:not([disabled])') if e.is_visible()][:3]:
            # the last primary pick disables its twin on the secondary side once React
            # flushes, so a handle collected a moment ago can be disabled by now
            if not t.is_enabled():
                continue
            t.click()
            page.wait_for_timeout(80)
            clicked += 1
    shown = page.evaluate('''() => ['primaryCol', 'secondaryCol'].map(c =>
      [...document.querySelectorAll('#' + c + ' [data-tree-body]')].filter(b => !b.hidden).length)''')
    check('exactly one tree panel is open per column', shown == [1, 1], shown)
    killed = page.evaluate('() => window.__killed')
    check(f'no element destroyed across {clicked} clicks', killed == 0, killed)
    check('the secondary picker blocks the primary tree',
          page.locator('.treepick button[data-side="secondary"]:disabled').count() == 1)

    # ── the layout the page is read in ────────────────────────────────────
    # Every header label sits over the column it names, to the pixel. It used to
    # run four header columns against a row's six, so "wpa . n" straddled the seam
    # between two figures. Right edges, because that is where numbers line up.
    print('\n== step 1: the two columns and their headers ==')
    page.locator('.treepick button[data-side="primary"][data-tree="8000"]').click()
    page.wait_for_timeout(300)
    edges = page.evaluate('''() => {
      const R = e => Math.round(e.getBoundingClientRect().right);
      const out = {};
      for (const c of ['primaryCol', 'secondaryCol', 'shardCol']) {
        const bar = document.querySelector('#' + c + ' .srcbar');
        const rows = [...document.querySelectorAll(
          '#' + c + ' .treebody:not([hidden]) .rpick, #' + c + ' > .rrow .rpick')];
        out[c] = {
          head: [...bar.querySelectorAll('.u1,.u2,.u3,.u4')].map(R),
          rows: rows.map(r => [2, 3, 4, 5].map(i => R(r.children[i]))),
        };
      }
      return out;
    }''')
    for col, e in edges.items():
        check(f'{col}: every figure lines up under its label',
              all(r == e['head'] for r in e['rows']),
              e['head'] if all(r == e['head'] for r in e['rows'])
              else [r for r in e['rows'] if r != e['head']][:2])

    # What the blocks are sized against is the League client's own rune page, not
    # each other: a keystone block is 1.13x a minor and a shard is 0.50x, measured
    # off Downloads/runes.png. The two columns therefore do NOT finish level, and
    # that is the settled call (2026-08-18) -- this picker shows all 3-4 keystones
    # where the client shows the one you took, so filling the column meant four
    # boxes of mostly empty space. Read the BLOCKS, not the columns: the old check
    # compared #primaryCol to .rune-side and passed on 1073 == 1073, which is the
    # box `align-items: stretch` inflates, identical whatever the content does.
    rows = page.evaluate('''() => {
      const h = s => { const e = document.querySelector(s);
                       return e ? +e.getBoundingClientRect().height.toFixed(1) : null; };
      return {
        key:   h('#primaryCol .treebody:not([hidden]) .rrow.keys .rpick'),
        minor: h('#primaryCol .treebody:not([hidden]) .rrow:not(.keys) .rpick'),
        shard: h('#shardCol .rrow .rpick'),
      };
    }''')
    ratios = {k: round(v / rows['minor'], 3) for k, v in rows.items()}
    check('a keystone block is the client\'s 1.13x a minor, not a stretched 2.33x',
          abs(ratios['key'] - 1.13) <= 0.08, f"{rows} -> {ratios}")
    check('a shard block is the client\'s 0.50x a minor',
          abs(ratios['shard'] - 0.50) <= 0.08, ratios['shard'])

    # ragged is intentional, but only downward: the primary column ending BELOW
    # the shard stack would mean a keystone row started growing again.
    ends = page.evaluate('''() => {
      const B = s => { const n = [...document.querySelectorAll(s)].pop();
                       return n ? Math.round(n.getBoundingClientRect().bottom) : null; };
      return [B('#primaryCol .treebody:not([hidden]) > *'), B('.rune-side #shardCol .rrow')];
    }''')
    check('the primary column ends at or above the shard stack, never past it',
          ends[0] is not None and ends[1] is not None and ends[0] <= ends[1] + 1, ends)
    check('the shards are stacked under the secondary, not in a third column',
          page.locator('.rune-side #shardCol').count() == 1
          and page.locator('.rune-cols > #shardCol').count() == 0)
    check('save sits in the page head, not under a column',
          page.locator('.meta-head #toItems').count() == 1)

    # a keystone swap re-reads every figure but leaves the picks alone: re-seeding
    # them from most-taken overwrote a deliberate choice on every comparison
    page.locator('#primaryCol .treebody:not([hidden]) .rpick.key').first.click()
    page.wait_for_timeout(200)
    page.locator('#primaryCol .treebody:not([hidden]) .rpick:not(.key)').first.click()
    page.wait_for_timeout(200)
    def kept_rows():
        return page.evaluate('''() => [...document.querySelectorAll(
      '#primaryCol .treebody:not([hidden]) .rpick:not(.key)[aria-pressed="true"]')]
      .map(b => b.querySelector('.nm').textContent)''')
    was = kept_rows()
    page.locator('#primaryCol .treebody:not([hidden]) .rpick.key').nth(2).click()
    page.wait_for_timeout(250)
    check('the rows you picked survive a keystone swap', kept_rows() == was and was != [],
          f'{was} -> {kept_rows()}')

    # The lolalytics lane is read under the keystone too, off runesByKeystone.
    # It matters as much as the coachless half: Legend: Alacrity is 8.0% pick on
    # Shyvana jungle under Press the Attack and 80.0% under Conqueror, and the
    # keystone-blind grid averages the two into a figure describing neither.
    # The keystone ROW is the deliberate exception and must NOT move — under a
    # keystone filter lolalytics reads the picked one at 100% and every other one
    # as a dash, which is the column of pick rates that row exists to compare.
    def lanes():
        return page.evaluate("""() => {
      const g = s => [...document.querySelectorAll(s)].map(b => b.children[4].textContent
                     + '/' + b.children[5].textContent);
      return {key: g('#primaryCol .treebody:not([hidden]) .rpick.key'),
              minor: g('#primaryCol .treebody:not([hidden]) .rpick:not(.key)')};
    }""")
    was_lanes = lanes()
    page.locator('#primaryCol .treebody:not([hidden]) .rpick.key').nth(1).click()
    page.wait_for_timeout(250)
    now_lanes = lanes()
    check('the lolalytics lane is read under the keystone, not role-overall',
          was_lanes['minor'] != now_lanes['minor']
          and any(x != '\u2013/' for x in now_lanes['minor']),
          f"{was_lanes['minor'][:3]} -> {now_lanes['minor'][:3]}")
    check('and the keystone row keeps its role-overall pick rates',
          was_lanes['key'] == now_lanes['key']
          and any(x != '\u2013/' for x in now_lanes['key']),
          f"{was_lanes['key'][:3]} -> {now_lanes['key'][:3]}")

    # The item figures are baked per keystone (roles.<role>.itemsByKeystone), so
    # switching one has to move the shop as well -- a keystone click only called
    # renderRunes() before, which left step two showing one flat average of build
    # paths that do not resemble each other. Viego jungle is the fixture because
    # its keystones disagree hard: Umbral Glaive reads +4.54 under Hail of Blades
    # and does not place at all under Conqueror.
    def figs():
        return page.evaluate("""() => [...document.querySelectorAll('#shelves .fig')]
      .map(f => f.textContent.trim()).filter(Boolean)""")
    before = figs()
    page.locator('#primaryCol .treebody:not([hidden]) .rpick.key').first.click()
    page.wait_for_timeout(300)
    after = figs()
    check('the shop figures are read under the keystone, not one flat average',
          bool(before) and bool(after) and before != after,
          f'{len(before)} figures -> {len(after)}, changed={before != after}')
    where = page.locator('#metaWhere').inner_text()
    check('the shop legend says which keystone the figures came from',
          'under ' in where or 'all keystones' in where, where)

    # There is no start picker. Conditioning on what the build opened with was its
    # own axis until 2026-08-19; the jungle pet is now an ordinary item carrying
    # its own figures, which is what it always was on the page. A chip row coming
    # back is a regression, not a feature.
    page.locator('#stepnav [data-step="items"]').click()
    page.wait_for_timeout(300)
    check('there is no jungle-pet selector', page.locator('#starterPick').count() == 0,
          page.locator('#starterPick').count())

    # And the pet reads like any other item: coachless splits its statistics into
    # classes on one endpoint, and pets are itemType 6. Asking only for 1 and 2 is
    # what left three of a jungler's items unrated on a page whose whole subject is
    # what an item is worth.
    pet_figs = page.evaluate("""() => ['1101','1102','1103'].map(id => {
      const el = document.querySelector(`#shelves .item[data-id="${id}"] .fig`);
      return el ? el.textContent.trim() : '';
    }).filter(Boolean)""")
    check('a jungle pet carries its own figures like any other item',
          len(pet_figs) == 3, pet_figs)

    # the inverse reading: the same bake pivoted, so an item says which keystone it
    # wants rather than only what it is worth under the one you happen to have picked.
    # A row only counts if it GAINED win probability over at least MIN_GAMES games --
    # one player going 1-0 out of Hail of Blades must not make an item want it. Both
    # sides of that rule are checked: an item that qualifies shows the line, and an
    # item whose only positive reading is thin does not.
    MIN_GAMES = 1000
    served = json.loads(urllib.request.urlopen(f'{BASE}/api/stats', timeout=20).read())
    by_ks = served['champions']['Viego']['roles']['jungle'].get('itemsByKeystone', {})
    rows = {}
    for _kid, lst in by_ks.items():
        for it in lst:
            if it.get('wpa') is not None:
                rows.setdefault(str(it['id']), []).append((it['wpa'], it['n']))
    def visible(i):
        return page.locator(f'#shelves .item[data-id="{i}"]:not([hidden])').count()

    def qualifies(v):
        return any(w >= 0 and n >= MIN_GAMES for w, n in v)
    target = next((i for i, v in rows.items() if qualifies(v) and visible(i)), None)
    thin = next((i for i, v in rows.items()
                 if not qualifies(v) and any(w >= 0 for w, n in v) and visible(i)), None)

    check('an item measured well over real volume is available to check', target, target)
    if target:
        page.locator(f'#shelves .item[data-id="{target}"]').hover()
        page.wait_for_timeout(450)
        card = page.locator('.hovercard').first.inner_text()
        check('the item card names the keystone it wants, and the sample behind it',
              'wants' in card.lower() and 'games' in card.lower(),
              card.replace('\n', ' | ')[:160])
        check('and it does not also print the keystone it is worst under',
              card.lower().count('under ') == 1, card.replace('\n', ' | ')[:160])
    if thin:
        page.locator(f'#shelves .item[data-id="{thin}"]').hover()
        page.wait_for_timeout(450)
        card2 = page.locator('.hovercard').first.inner_text()
        check('an item whose only positive reading is thin claims no keystone',
              'wants' not in card2.lower(), f'{thin} :: ' + card2.replace('\n', ' | ')[:140])

    # ── the patch strip ───────────────────────────────────────────────────
    # Every item the SHOP carries, not only the ones this champion has bought.
    # Narrowing it to the coachless bake hid a change to an item you were about to
    # consider on the grounds that nobody had bought it yet, which is backwards for
    # a strip whose whole job is "did anything under my figures move".
    served_diff = json.loads(urllib.request.urlopen(f'{BASE}/api/diff', timeout=20).read())
    strip = page.locator('#patchChanges .change')
    check('the strip renders every changed item the diff carries',
          strip.count() == len(served_diff.get('items', [])),
          f"{strip.count()} on page vs {len(served_diff.get('items', []))} served")
    mine_n = page.locator('#patchChanges .change.mine').count()
    check('including items this champion does not buy',
          strip.count() > mine_n > 0, f'{mine_n} of {strip.count()} are bought here')

    # Collapsed to the icon: the numbers moved into the hover card, and the edge
    # carries the direction. A verdict of 'rework' on every entry is the failure
    # mode -- Riot rewrites the tooltip alongside every stat change, so counting
    # that as unquantified makes the border say nothing at all.
    check('the strip is icons, with the numbers no longer inline',
          page.locator('#patchChanges .nm').count() == 0
          and page.locator('#patchChanges .fig').count() == 0,
          page.locator('#patchChanges').inner_text().replace('\n', ' | ')[:120])
    verdicts = page.evaluate("""() => [...document.querySelectorAll('#patchChanges .change')]
      .map(c => c.dataset.verdict)""")
    check('every icon carries a verdict on its edge',
          all(v in ('buff', 'nerf', 'rework') for v in verdicts) and verdicts, verdicts)
    check('and they are not all the same verdict', len(set(verdicts)) > 1, verdicts)

    page.locator('#patchChanges .change').first.hover()
    page.wait_for_timeout(450)
    card = page.locator('.hovercard').first.inner_text()
    # the word, not only the colour -- a red edge and a green edge are the same
    # edge to about 8% of men, which is the rule the patch page's badges follow
    check('hovering an icon opens the full change, with the verdict spelled out',
          any(w in card.upper() for w in ('BUFF', 'NERF', 'REWORK')) and '\u2192' in card,
          card.replace('\n', ' | ')[:160])

    # The strip has to carry what RIOT says changed, not what Data Dragon happens to
    # expose. Riot templates its passive numbers out of ddragon -- Sterak's Gage
    # reads "Gain  bonus Attack Damage" with the number absent, identically on both
    # patches -- so a ddragon diff missed Eclipse and Sterak's entirely and half the
    # rows on everything else. Checked against the SERVED notes, so it survives a
    # patch instead of pinning one item's numbers.
    notes = json.loads(urllib.request.urlopen(f'{BASE}/api/patchnotes', timeout=20).read())
    items_sec = next((s for s in notes.get('sections', []) if s.get('name') == 'Items'), {})
    riot = {}
    for e in items_sec.get('entries', []):
        rows = [c for g in e.get('groups', []) for c in g.get('changes', [])]
        if rows:
            riot[e['name']] = rows
    on_page = {e['name']: e for e in served_diff.get('items', [])}
    # the one alias Riot writes by its own older name
    matched = {n: r for n, r in riot.items()
               if n in on_page or n.replace('Cape', 'Aegis') in on_page}
    check("every item Riot's notes name is on the strip",
          len(matched) == len(riot),
          f'{len(matched)} of {len(riot)}: missing {sorted(set(riot) - set(matched))}')
    thin = [n for n, r in matched.items()
            if len((on_page.get(n) or on_page[n.replace('Cape', 'Aegis')])['changes']) < len(r)]
    check('and carries every row Riot listed for it, not the ddragon subset',
          not thin, f'short: {thin}')
    check('no dead both-null rows survive anywhere in the item diff',
          not any(c.get('from') is None and c.get('to') is None
                  for e in served_diff.get('items', []) for c in (e.get('changes') or [])))

    # The champion half of the strip cannot be checked against live data on a patch
    # where Riot touched no pool champion, which is most patches -- and it went
    # unrendered for months precisely because nothing ever exercised it. So the
    # real module is imported into the page and handed a champion-shaped entry.
    champ_html = page.evaluate("""async () => {
      const m = await import('/forge/static/patchstrip.js');
      return m.changeCardHTML({
        name: 'Viego', kind: 'changed', verdict: 'rework', why: 'Shifting power out of the ult.',
        changes: [{field: 'base health', from: '610', to: '630'},
                  {field: 'R Cooldown', from: '120 / 100 / 80', to: '140 / 120 / 100'},
                  {field: 'R True Form Indicator', from: null, to: 'Resource bar turns purple'}],
      });
    }""")
    txt = re.sub(r'<[^>]+>', ' ', champ_html)
    check('a champion entry renders its rows, labelled and directional',
          all(s in txt for s in ('Viego', 'REWORK', 'base health', '610', '630',
                                 'R Cooldown', '140 / 120 / 100')),
          txt.strip()[:150])
    # Riot's "NEW" shape has no before, so an arrow from nothing would be a lie
    check("and a row Riot added shows its value with nothing arrowed from it",
          'Resource bar turns purple' in txt and '\u2192 Resource bar' not in txt,
          txt.strip()[:150])

    if matched:
        name = sorted(matched)[0]
        entry = on_page.get(name) or on_page[name.replace('Cape', 'Aegis')]
        row = matched[name][0]
        page.locator(f'#patchChanges .change[data-change="{entry["id"]}"]').hover()
        page.wait_for_timeout(450)
        named = page.locator('.hovercard').first.inner_text()
        check("and the card prints Riot's row, labelled, before and after",
              all(s in named for s in (row['field'], row['from'], row['to'])),
              f'{name}: {named.replace(chr(10), " | ")[:150]}')

    # ── step two ──────────────────────────────────────────────────────────
    print('\n== the item builder ==')
    page.locator('#stepnav [data-step="items"]').click()
    page.wait_for_timeout(300)

    page.once('dialog', lambda d: d.accept(SET_JSON))
    page.locator('#import').click()
    page.wait_for_timeout(400)

    check('blocks populated from import', page.locator('#blocks .slot').count() == 5,
          page.locator('#blocks .slot').count())

    # ── the first item in Core is the second axis every figure is read under ──
    # A build is centred on a keystone and a first item, so what the shop is worth
    # has to move when the Core block's opener changes. Both halves are checked:
    # an item nobody rushes must DROP the condition out loud rather than collapse
    # the shop to one thin row, and a real rush must actually cross.
    def legend():
        return page.locator('#metaWhere').inner_text()

    # The set marks the slot the figures are read out of, and it has to say WHICH
    # of three things is true rather than just glowing: measured, asked-and-thin,
    # or still in flight. A confident ring over a dropped reading is the same lie
    # the shop legend already learned not to tell.
    def marked():
        return page.evaluate("""() => {
      const el = document.querySelector('#blocks .slot[data-first]');
      const p = document.querySelector('#blocks .fnote');
      return el && {state: el.dataset.first, ii: el.dataset.ii,
                    item: el.querySelector('img').alt,
                    note: (p && p.textContent || '').trim(),
                    noteState: p && p.dataset.state};
    }""")

    # Both marked slots, because the axis is two deep now: one lit slot with an
    # unmarked one beside it reads as "both of these count", which is the whole
    # thing the second marker exists to deny.
    def marks():
        return page.evaluate("""() => {
      const p = document.querySelector('#blocks .fnote');
      return {slots: [...document.querySelectorAll('#blocks .slot[data-first]')].map(
                el => ({state: el.dataset.first, ii: el.dataset.ii,
                        item: el.querySelector('img').alt})),
              note: (p && p.textContent || '').trim(),
              noteState: p && p.dataset.state};
    }""")
    settle(legend())
    check('a first item nobody rushes says so instead of emptying the shop',
          'too few games rush' in legend().lower()
          and page.locator('#shelves .item:visible').count() > 5,
          legend() + ' :: ' + str(page.locator('#shelves .item:visible').count()))
    m = marked()
    check('the set marks the slot the figures were asked about',
          m and m['ii'] == '0' and 'Shieldbow' in m['item'], m)
    check('and it says the reading was dropped rather than claiming one',
          m and m['state'] == 'thin' and m['noteState'] == 'thin'
          and 'too few games' in m['note'], m)
    # Three items in Core, two marked. The depth is the build's to choose and the
    # ceiling is coachless': `thirdLegendaryId` answers 200 and is then ignored, so
    # a third marked slot would be claiming a condition that never went on the wire.
    check('the axis stops at two slots however many the Core block holds',
          len(marks()['slots']) == 2
          and page.locator('#blocks .block:last-child .slot').count() == 3,
          [x['ii'] for x in marks()['slots']])

    pre_rush, was = figs(), legend()
    page.once('dialog', lambda d: d.accept(SET_RUSH))
    page.locator('#import').click()
    settle(was)
    # The reading takes the first legendary straight off the build -- no control to
    # set, and no start crossed into it: the pet is an item with its own figures.
    check('a real first-item rush is what the shop is read out of',
          'collector' in legend().lower() and 'scorchclaw' not in legend().lower(),
          legend())
    check('and the shop figures actually moved onto it', pre_rush != figs(),
          f'{len(pre_rush)} figures -> {len(figs())}')
    # This Core is two deep and both slots measure: 6676 -> 3036 is 15 rows with 8
    # over the floor. So the reading is the PAIR, not the opener, and every surface
    # has to say two rather than one.
    mk = marks()
    check('both core slots are read when the pair clears the floor',
          [x['state'] for x in mk['slots']] == ['read', 'read']
          and 'Collector' in mk['slots'][0]['item']
          and 'Dominik' in mk['slots'][1]['item'], mk['slots'])
    check('and the note says the stats are based on both, not on the opener',
          mk['noteState'] == 'read'
          and mk['note'].endswith('stats based on these as the first two items'),
          mk['note'])
    # The legend names the condition and stops there. The swatch key it used to
    # carry said in words what every tile already says in colour and edge length.
    check('the legend names both items and nothing else',
          legend().rstrip().endswith("The Collector into Lord Dominik's Regards"
                                     ' first two items')
          and 'not crossed' not in legend(), legend())
    check('the swatch key is gone from the legend',
          page.locator('#shopLegend .swatch').count() == 0,
          page.locator('#shopLegend').inner_text().replace('\n', ' | '))
    served_cond = json.loads(urllib.request.urlopen(
        f'{BASE}/api/conditioned?champ=Viego&role=jungle&first=6676', timeout=30).read())
    check('the endpoint that fed it clears the sample floor it claims',
          any((r.get('n') or 0) >= MIN_GAMES for r in served_cond),
          f'{len(served_cond)} rows, max n='
          + str(max([r.get('n') or 0 for r in served_cond], default=0)))
    # The pet is in the conditioned answer too, not only in the flat bake: it is an
    # ordinary item, so it gets read out of the first legendary like every other one.
    check('and it carries the jungle pets, read out of that same first item',
          {1101, 1102, 1103} & {r.get('id') for r in served_cond},
          sorted({r.get('id') for r in served_cond} & {1101, 1102, 1103}))
    check('an unconditioned call stays empty rather than re-serving the bake',
          json.loads(urllib.request.urlopen(
              f'{BASE}/api/conditioned?champ=Viego&role=jungle', timeout=20).read()) == [])
    # The keystone crosses in too, and the floor is what decides whether the cell
    # survives -- not a rule about which axis is allowed. This USED to assert the
    # opposite, on a number measured against Press the Attack (2,909 games alone on
    # Viego, so anything crossed with it dies) and read as a property of the cross.
    ks_fat = json.loads(urllib.request.urlopen(
        f'{BASE}/api/conditioned?champ=Viego&role=jungle&first=6676&keystone=9923',
        timeout=30).read())
    check('a popular keystone crosses in rather than being ignored',
          ks_fat != served_cond
          and any((r.get('n') or 0) >= MIN_GAMES for r in ks_fat),
          f'{len(ks_fat)} rows, max n='
          + str(max([r.get('n') or 0 for r in ks_fat], default=0)))
    ks_thin = json.loads(urllib.request.urlopen(
        f'{BASE}/api/conditioned?champ=Viego&role=jungle&first=6676&keystone=8005',
        timeout=30).read())
    check('and a thin one comes back under the floor, which is what the walk drops',
          not any((r.get('n') or 0) >= MIN_GAMES for r in ks_thin),
          f'{len(ks_thin)} rows, max n='
          + str(max([r.get('n') or 0 for r in ks_thin], default=0)))
    # Keystone-only is `roles.<role>.itemsByKeystone`, baked and already on the page.
    # Serving it live as well would be a second answer to a settled question.
    check('a keystone with no first item is not served live — that reading is baked',
          json.loads(urllib.request.urlopen(
              f'{BASE}/api/conditioned?champ=Viego&role=jungle&keystone=9923',
              timeout=20).read()) == [])
    # The second legendary is the one thing that IS crossed in, because it is the
    # one thing that survives the cross. If this ever stops differing the parameter
    # has stopped reaching the wire and every pair reading on the page is the
    # opener's reading wearing a two-item caption.
    served_pair = json.loads(urllib.request.urlopen(
        f'{BASE}/api/conditioned?champ=Viego&role=jungle&first=6676&second=3036',
        timeout=30).read())
    check('a second legendary cuts the sample rather than being ignored',
          served_pair != served_cond and len(served_pair) < len(served_cond),
          f'{len(served_pair)} rows vs {len(served_cond)}')
    check('and the pair still clears the floor it claims',
          any((r.get('n') or 0) >= MIN_GAMES for r in served_pair),
          'max n=' + str(max([r.get('n') or 0 for r in served_pair], default=0)))
    # Slot 1 with no slot 0 is a half-read query string, not a condition anyone
    # builds. It has to fall to the unconditioned answer, not measure on its own.
    check('a second with no first is ignored, not honoured',
          json.loads(urllib.request.urlopen(
              f'{BASE}/api/conditioned?champ=Viego&role=jungle&second=3036',
              timeout=20).read()) == [])

    # The middle state: the pair was asked and came back under the floor, the
    # opener alone still measures. Slot 0 is honestly lit and slot 1 must say it
    # was dropped -- an unmarked slot 1 beside a lit slot 0 reads as "both count".
    was = legend()
    page.once('dialog', lambda d: d.accept(SET_PAIR_THIN))
    page.locator('#import').click()
    settle(was)
    mk = marks()
    check('a pair under the floor falls back to the opener rather than emptying',
          legend().rstrip().endswith('The Collector first item')
          and page.locator('#shelves .item:visible').count() > 5, legend())
    check('slot 0 reads and slot 1 says its cross was dropped',
          [x['state'] for x in mk['slots']] == ['read', 'thin'], mk['slots'])
    check('and the note names the drop instead of claiming two items',
          mk['note'].endswith('too few games take that one second'), mk['note'])

    # The same floor rule, driven from the page: pick a keystone whose cross clears
    # and the legend has to name it beside the items; pick one whose cross does not
    # and it has to disappear from the sentence while the items stay. Both keystones
    # are clicked by id rather than by position, because which one an nth() lands on
    # is not stable and the whole point of these two checks is WHICH keystone.
    def pick_keystone(tree, rune):
        page.locator('#stepnav [data-step="runes"]').click()
        page.wait_for_timeout(200)
        page.locator(f'#primaryCol .treepick button[data-tree="{tree}"]').click()
        page.wait_for_timeout(200)
        page.locator(f'#primaryCol .rpick.key[data-rune="{rune}"]').click()
        page.wait_for_timeout(200)
        page.locator('#stepnav [data-step="items"]').click()
        page.wait_for_timeout(200)

    was = legend()
    page.once('dialog', lambda d: d.accept(SET_RUSH))
    page.locator('#import').click()
    settle(was)
    was = legend()
    pick_keystone(8100, 9923)          # Domination -> Hail of Blades
    settle(was)
    check('a keystone whose cross clears the floor is named beside the items',
          'under Hail of Blades' in legend()
          and legend().rstrip().endswith("The Collector into Lord Dominik's Regards"
                                         ' first two items'), legend())
    was = legend()
    pick_keystone(8000, 8005)          # Precision -> Press the Attack, 2,909 games
    settle(was)
    check('and one whose cross does not clear says so instead of going quiet',
          'too few games under Press the Attack' in legend()
          and 'read under Press the Attack' not in legend()
          and legend().rstrip().endswith("The Collector into Lord Dominik's Regards"
                                         ' first two items'), legend())

    # Put the fixture back: everything below this line was written against the
    # five-slot set, and a probe that leaves the page in its own state quietly
    # rewrites every check that follows it.
    page.once('dialog', lambda d: d.accept(SET_JSON))
    page.locator('#import').click()
    page.wait_for_timeout(600)
    check('the five-slot fixture is restored for the checks below',
          page.locator('#blocks .slot').count() == 5,
          page.locator('#blocks .slot').count())
    check('block gold total is gone', page.locator('.btotal').count() == 0)
    check('every slot carries its own gold', page.locator('#blocks .slot .sgold').count() == 5)
    check('every slot has a remove x', page.locator('#blocks .slot .rm').count() == 5)
    check('slots are draggable',
          page.evaluate("() => [...document.querySelectorAll('#blocks .slot')].every(s => s.draggable)"))

    # clicking a slot READS, it must not remove
    n_before = page.locator('#blocks .slot').count()
    page.locator('#blocks .slot').nth(3).click()
    page.wait_for_timeout(250)
    check('clicking a slot leaves the set alone',
          page.locator('#blocks .slot').count() == n_before,
          page.locator('#blocks .slot').count())
    check('clicking a slot opens the inspector', page.locator('#inspect').is_visible())
    check('the inspector names the item in THAT slot',
          'Blade of The Ruined King' in page.locator('#inspect h3').inner_text(),
          page.locator('#inspect h3').inner_text())

    # the x removes
    page.locator('#blocks .slot').nth(4).locator('.rm').click(force=True)
    page.wait_for_timeout(250)
    check('the x takes one out', page.locator('#blocks .slot').count() == n_before - 1,
          page.locator('#blocks .slot').count())

    # inspector, in full, on a legendary both sources measured
    page.locator('.item[data-id="6673"]').click()
    page.wait_for_timeout(300)
    box = page.locator('#inspect')
    txt = box.inner_text().lower()          # the source headings are uppercased by CSS
    check('inspector shows gold in the header', 'gold' in txt)
    check('stats carry the rail glyph', box.locator('dl img').count() > 0,
          box.locator('dl img').count())
    check('coachless figures rendered in full',
          'coachless' in txt and 'wpa' in txt and 'before' in txt, txt[:160])
    check('lolalytics figures rendered slot by slot',
          'lolalytics' in txt and '3rd' in txt and 'pick' in txt, txt[:400])
    check('build-path nodes name themselves',
          box.locator('.tier .node .nn strong').count() > 0)
    check('build-path nodes carry their gold',
          box.locator('.tier .node .ng').count() > 0)
    check('build-path nodes are draggable',
          page.evaluate("() => [...document.querySelectorAll('#inspect .node')].every(n => n.draggable)"))
    page.screenshot(path=f'{SHOT}/02-inspector-expanded.png')

    # ── drag: HTML5 drag cannot be driven, so drive the events and read state ──
    print('\n== drag: reorder, move between blocks, add from the build path ==')

    def fire_drop(payload, target_sel, index=None):
        """Dispatch a real drop on a target with a live DataTransfer."""
        return page.evaluate("""([payload, sel, idx]) => {
          const dt = new DataTransfer();
          dt.setData('text/plain', payload);
          const el = idx == null ? document.querySelector(sel)
                                 : document.querySelectorAll(sel)[idx];
          if (!el) return 'no target';
          el.dispatchEvent(new DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: dt}));
          return 'ok';
        }""", [payload, target_sel, index])

    def block_ids():
        return page.evaluate("() => JSON.parse(localStorage.getItem('itemSetForge')).blocks"
                             ".map(b => b.items.map(i => i.id))")

    start = block_ids()
    print('   before:', start)
    check('the fixture left two items in block 1 to reorder', len(start[1]) >= 2, start)

    # reorder inside block 1: its LAST slot, dropped in front of its first
    last = len(start[1]) - 1
    fire_drop(f'move:1:{last}', '#blocks .block[data-bi="1"] .slot', 0)
    page.wait_for_timeout(200)
    after = block_ids()
    print('   reorder:', after)
    check('reorder put the dragged item in front of the drop target',
          after[1][0] == start[1][last] and len(after[1]) == len(start[1]), after[1])

    # move between blocks: block 1's first slot into block 0, in front of slot 0
    moved_id = after[1][0]
    fire_drop('move:1:0', '#blocks .block[data-bi="0"] .slot', 0)
    page.wait_for_timeout(200)
    after2 = block_ids()
    print('   cross-block:', after2)
    check('moving between blocks lands in front of the drop target',
          after2[0][0] == moved_id and moved_id not in after2[1], after2)

    # drop on empty block space appends
    fire_drop('move:0:0', '#blocks .block[data-bi="1"] .slots')
    page.wait_for_timeout(200)
    after3 = block_ids()
    print('   append:', after3)
    check('a drop on empty block space appends', after3[1][-1] == moved_id, after3[1])

    # a plain item id (shop tile, build-path node) still ADDS rather than moves
    fire_drop('1036', '#blocks .block[data-bi="0"] .slots')
    page.wait_for_timeout(200)
    after4 = block_ids()
    check('a plain item id still adds', '1036' in after4[0], after4[0])

    # and nothing was lost across all of it
    check('no item vanished across the drags',
          sorted(sum(after4, [])) == sorted(sum(start, []) + ['1036']),
          (sorted(sum(start, [])), sorted(sum(after4, []))))

    page.screenshot(path=f'{SHOT}/03-set-after-drags.png')

    # ── the stats are ON SCREEN when you hover, not in an attribute ───────
    # This is the check that was wrong the first time. Reading a `title`
    # attribute proves a string exists in the DOM; it proves nothing about what
    # Sam can see, and a native tooltip is unstyleable browser chrome that
    # takes about a second to appear. Assert the card is VISIBLE and that the
    # stat text is rendered inside it.
    print('\n== hovering an item shows its stats ==')
    card_loc = page.locator('.hovercard')

    def hover_card(locator):
        locator.scroll_into_view_if_needed()
        locator.hover()
        page.wait_for_timeout(350)
        return card_loc.inner_text() if card_loc.is_visible() else ''

    tile_text = hover_card(page.locator('.item[data-id="6673"]'))
    check('hovering a shop tile shows a card at all', bool(tile_text))
    check('the card shows the item and its gold',
          'Immortal Shieldbow' in tile_text and '3,000g' in tile_text, tile_text[:80])
    check('THE STATS ARE ON SCREEN',
          '55' in tile_text and 'Attack Damage' in tile_text
          and '25%' in tile_text and 'Critical Strike Chance' in tile_text, tile_text[:200])
    check('each stat is rendered with the rail glyph beside it',
          card_loc.locator('dl img').count() == 2, card_loc.locator('dl img').count())
    check('the passive is on the card', 'Lifeline' in tile_text, tile_text[:200])
    check('both sources are on the card',
          'coachless' in tile_text and '3rd' in tile_text, tile_text[:250])

    slot_text = hover_card(page.locator('#blocks .slot').first)
    check('hovering a set slot shows the same card',
          'Attack Damage' in slot_text or 'Health' in slot_text or 'Move Speed' in slot_text,
          slot_text[:120])

    page.mouse.move(5, 5)
    page.wait_for_timeout(300)
    check('the card goes away when the pointer leaves', not card_loc.is_visible())

    check('no native title tooltip is left to double up on it',
          page.evaluate("() => [...document.querySelectorAll('.item, .slot')]"
                        ".every(e => !e.getAttribute('title'))"))

    # ── the shop sells the role its own opening items ─────────────────────
    def visible_subs():
        return page.evaluate("""() => Object.fromEntries(
          [...document.querySelectorAll('.shelf .sub')].map(s =>
            [s.dataset.sub.split('|')[1],
             [...s.querySelectorAll('.item')].filter(i => !i.hidden).length]))""")

    # Viego jungle is on screen: pets yes, support items and starters no
    subs = visible_subs()
    print('   jungle:', {k: v for k, v in subs.items() if k in
                         ('Jungle pets', 'Support items', 'Starter items', 'Potions')})
    check('jungle shows jungle pets', subs.get('Jungle pets', 0) > 0, subs)
    check('jungle hides support items', subs.get('Support items', 0) == 0, subs)
    check('jungle hides starter items', subs.get('Starter items', 0) == 0, subs)
    check('jungle still shows potions', subs.get('Potions', 0) > 0, subs)
    check('the shelf says which aisles the role took away',
          'jungle' in page.locator('.shelf[data-shelf="Utility"] .what').inner_text().lower(),
          page.locator('.shelf[data-shelf="Utility"] .what').inner_text())

    page.select_option('#metaRole', 'mid')
    page.wait_for_timeout(400)
    subs = visible_subs()
    print('   mid:   ', {k: v for k, v in subs.items() if k in
                         ('Jungle pets', 'Support items', 'Starter items')})
    check('a laner shows starter items', subs.get('Starter items', 0) > 0, subs)
    check('a laner hides jungle pets', subs.get('Jungle pets', 0) == 0, subs)
    check('a laner hides support items', subs.get('Support items', 0) == 0, subs)

    # The champion has to move too. Viego carries the two checks above, but the
    # role select only ever lists the roles the coachless bake actually has for
    # the champion on screen, and Viego has no support row — select_option then
    # sits waiting for an <option> that will never exist and takes every check
    # after this point down with it. Pyke is the pool's support.
    page.select_option('#metaChamp', 'Pyke')
    page.wait_for_timeout(500)
    page.select_option('#metaRole', 'support')
    page.wait_for_timeout(400)
    subs = visible_subs()
    print('   supp:  ', {k: v for k, v in subs.items() if k in
                         ('Jungle pets', 'Support items', 'Starter items')})
    check('a support shows support items', subs.get('Support items', 0) > 0, subs)
    check('a support hides jungle pets', subs.get('Jungle pets', 0) == 0, subs)
    check('a support hides starter items', subs.get('Starter items', 0) == 0, subs)
    check('a role switch does not empty anyone\'s set',
          page.locator('#blocks .slot').count() > 0,
          page.locator('#blocks .slot').count())
    page.screenshot(path=f'{SHOT}/07-support-shop.png')

    # With no role at all, nothing is hidden. This needs its OWN fresh context:
    # /forge/edit restores the last champion out of localStorage by design, so
    # reusing this one would just reopen the support shop and prove nothing.
    bare = b.new_context(viewport={'width': 1700, 'height': 1000})
    bp = bare.new_page()
    bp.goto(f'{BASE}/edit', wait_until='networkidle')
    bp.wait_for_timeout(700)
    bp.locator('#stepnav [data-step="items"]').click()
    bp.wait_for_timeout(400)
    subs = bp.evaluate("""() => Object.fromEntries(
      [...document.querySelectorAll('.shelf .sub')].map(s =>
        [s.dataset.sub.split('|')[1],
         [...s.querySelectorAll('.item')].filter(i => !i.hidden).length]))""")
    print('   none:  ', {k: v for k, v in subs.items() if k in
                         ('Jungle pets', 'Support items', 'Starter items')})
    check('a set with no role at all hides nothing',
          all(subs.get(k, 0) > 0 for k in ('Jungle pets', 'Support items', 'Starter items')), subs)
    check('and says nothing about a role it does not have',
          'not bought' not in bp.locator('.shelf[data-shelf="Utility"] .what').inner_text(),
          bp.locator('.shelf[data-shelf="Utility"] .what').inner_text())
    bare.close()

    # ── columns still scroll alone ────────────────────────────────────────
    over = page.evaluate("() => ({doc: document.documentElement.scrollHeight <= innerHeight + 2,"
                         " cols: [...document.querySelectorAll('main .col')]"
                         ".map(c => getComputedStyle(c).overflowY)})")
    check('the document itself does not scroll', over['doc'], over)
    check('the shop and set columns own their scrollbars',
          over['cols'].count('auto') >= 2, over['cols'])

    check('no uncaught script errors through step 2', not errs, errs[:4])
    check('every request answered through step 2', not bad, bad[:5])

    # ── champion.html: the saved-build rune summary ───────────────────────
    print('\n== champion page: rune hover in the saved-build overlay ==')
    page2 = ctx.new_page()
    e2 = []
    page2.on('pageerror', lambda e: e2.append(str(e)))
    page2.goto(f'{BASE}/c/Viego/jungle', wait_until='networkidle')
    page2.wait_for_timeout(500)
    sets = page2.locator('[data-set]')
    if sets.count() == 0:
        check('a saved build exists to open', False, 'no sets saved for Viego jungle')
    else:
        sets.first.click()
        page2.wait_for_timeout(700)
        rows = page2.locator('#ov [data-rune]')
        check('rune rows carry their id', rows.count() > 0, rows.count())
        if rows.count():
            rows.nth(1).hover()
            page2.wait_for_timeout(300)
            c2 = page2.locator('#ov .hovercard')
            check('hover card opens over the dialog', c2.is_visible())
            check('hover card is inside the dialog, not behind it',
                  page2.evaluate("() => document.querySelector('.hovercard')?.closest('dialog') !== null"))
            check('hover card carries the long text',
                  len(c2.inner_text()) > 60, repr(c2.inner_text()[:70]))
            page2.screenshot(path=f'{SHOT}/04-champion-rune-hover.png')
    check('no uncaught script errors on the champion page', not e2, e2[:3])

    # ── the front door: a shelf row pops the build where it stands ────────
    # The whole point of the change: no second page load to read a build you are
    # already looking at. So the assertion is not "a dialog appeared" but "a
    # dialog appeared AND the URL never moved AND nothing fetched the champion
    # page behind your back".
    print('\n== landing page: the build pops out in place ==')
    page4 = ctx.new_page()
    e4, seen = [], []
    page4.on('pageerror', lambda e: e4.append(str(e)))
    page4.on('request', lambda r: seen.append(r.url))
    page4.goto(f'{BASE}/', wait_until='networkidle')
    page4.wait_for_timeout(900)

    rows = page4.locator('.build')
    if rows.count() == 0:
        check('a shelf row exists to open', False, 'no saved sets on the front door')
    else:
        was_url, mark = page4.url, len(seen)
        rows.first.click()
        page4.wait_for_timeout(800)
        check('the overlay opens', page4.locator('#ov[open]').count() == 1)
        check('the page never navigated', page4.url == was_url, page4.url)
        check('and never fetched the champion page',
              not [u for u in seen[mark:] if '/forge/c/' in u],
              [u for u in seen[mark:] if '/forge/c/' in u][:2])
        check('the rune page is drawn', page4.locator('#ov .rp-row').count() > 0,
              page4.locator('#ov .rp-row').count())
        page4.locator('#ov [data-rune]').first.hover()
        page4.wait_for_timeout(300)
        check('the rune hover card works here too',
              page4.locator('#ov .hovercard').is_visible())
        page4.screenshot(path=f'{SHOT}/09-landing-popout.png')
        page4.keyboard.press('Escape')
        page4.wait_for_timeout(250)
        check('escape closes it and leaves the URL alone',
              page4.locator('#ov[open]').count() == 0 and page4.url == was_url)

    # Art drawn larger than it exists is the blur. Champion portraits were baked
    # at 32px and drawn at 62-72px; the tree emblems, which Riot only ships at
    # 32x32, were stretched to 46px in the builder. Both are fixed, and this is
    # the check that keeps them fixed - it reads every rendered <img> and fails on
    # any one whose CSS box is wider than the pixels behind it.
    upscaled = """() => [...document.images]
        .filter(i => i.naturalWidth && i.clientWidth > i.naturalWidth)
        .map(i => `${i.clientWidth}px drawn from ${i.naturalWidth}px :: ${i.src.slice(0, 70)}`)"""
    for label, pg in (('front door', page4), ('builder', page), ('build list', page2)):
        up = pg.evaluate(upscaled)
        check(f'no art is upscaled on the {label}', not up, up[:4])

    check('no uncaught script errors on the landing page', not e4, e4[:3])

    # ── the patch page: its own surface, and nothing wraps mid-comparison ──
    # Cold, in this same context but on a URL nothing has primed. The two things
    # that can only be checked on a rendered page are here: that a comparison
    # never breaks across lines, and that no row escapes the card it lives in.
    print('\n== patch page ==')
    page3 = ctx.new_page()
    e3, bad3 = [], []
    page3.on('pageerror', lambda e: e3.append(str(e)))
    page3.on('response', lambda r: bad3.append(f'{r.status} {r.url}') if r.status >= 400
             and 'favicon' not in r.url else None)
    page3.goto(f'{BASE}/patch', wait_until='networkidle')
    page3.wait_for_timeout(700)

    check('the patch page paints entries', page3.locator('.entry').count() > 0,
          page3.locator('.entry').count())
    check('every entry carries a triage badge',
          page3.locator('.entry .tri').count() == page3.locator('.entry').count())
    tris = set(page3.eval_on_selector_all('.entry', 'ns => ns.map(n => n.dataset.triage)'))
    check('the badge is one of the three readings', tris <= {'buff', 'nerf', 'rework'}, tris)
    check('direction is coloured, not left to arithmetic',
          page3.locator('.d[data-v="buff"], .d[data-v="nerf"]').count() > 0)

    # Per NUMBER, not per row. Bel'Veth's ultimate is buffed at rank 1 and cut at
    # ranks 2 and 3, and the page printed NERF over the whole line until it
    # stopped reading a per-level list by its total. This is the check for that:
    # at least one row has to carry both colours at once, or the per-element
    # reading has quietly collapsed back to one verdict a row.
    both = page3.evaluate("""() => [...document.querySelectorAll('.rows dd')]
        .filter(d => d.querySelector('.d[data-v="buff"]')
                  && d.querySelector('.d[data-v="nerf"]'))
        .map(d => d.textContent.trim().slice(0, 48))""")
    check('a row whose numbers disagree shows both directions', both, both[:2])

    # A curve that changed its BAND COUNT is the row most worth reading and the
    # one the page used to grey out whole. Camille's passive is both shapes at
    # once: a flat shield that became a 4-band curve (weaker until 13, stronger
    # after) and a 4-band cooldown that became 3 (three buffs, then a NERF at
    # 19+, where the dropped band's value persists). Each has to render band by
    # band with both colours on the row, or the run pairing has collapsed back
    # to bailing on every shape change.
    curves = page3.evaluate("""() => {
      const card = [...document.querySelectorAll('.entry')]
        .find(e => e.querySelector('.nm')?.textContent.trim() === 'Camille');
      if (!card) return null;
      const grp = [...card.querySelectorAll('.grp')]
        .find(g => /Passive/.test(g.querySelector('h4')?.textContent || ''));
      if (!grp) return null;
      return [...grp.querySelectorAll('.rows dt')].map(t => [
        t.textContent.trim(),
        t.nextElementSibling.querySelectorAll('.d[data-v="buff"]').length,
        t.nextElementSibling.querySelectorAll('.d[data-v="nerf"]').length,
        t.nextElementSibling.querySelectorAll('.d.whole').length]);
    }""")
    # Pinned to the patch that changed Camille's passive. On a patch whose notes do
    # not carry it there is nothing to read, and the skip says so out loud.
    if curves is None:
        print('  SKIP  band-count curve check: no Camille passive in this patch\'s notes')
    else:
        check('a curve whose band count changed is read band by band, not greyed out',
              len(curves) >= 2 and all(b and n and not w for _, b, n, w in curves), curves)

    # One grid per CARD. Every value on a card starts at the same x however many
    # groups it spans - Base Stats and each ability used to own a separate grid,
    # so the label column was a different width in each and nothing on the card
    # lined up with anything above it.
    ragged = page3.evaluate("""() => {
      const out = [];
      for (const card of document.querySelectorAll('.entry')) {
        const xs = [...card.querySelectorAll('.rows dd')]
          .map(d => Math.round(d.getBoundingClientRect().left));
        if (new Set(xs).size > 1)
          out.push([card.querySelector('.nm').textContent, [...new Set(xs)]]);
      }
      return out;
    }""")
    check('every value on a card starts at the same x', not ragged, ragged[:3])

    # the whole complaint this page answers: a comparison broken across two lines
    wrapped = page3.evaluate("""() => {
      const out = [];
      document.querySelectorAll('.d').forEach(d => {
        d.querySelectorAll('.was, .now').forEach(v => {
          // more than one client rect means the browser broke the value in half
          if (v.getClientRects().length > 1) out.push(v.textContent.slice(0, 40));
        });
      });
      return out;
    }""")
    check('no compared value is wrapped across lines', not wrapped, wrapped[:3])
    check('there are comparisons to check at all',
          page3.locator('.d .now').count() > 20,
          page3.locator('.d .now').count())

    escaped = page3.evaluate("""() => {
      const out = [];
      document.querySelectorAll('.entry').forEach(e => {
        const r = e.getBoundingClientRect();
        e.querySelectorAll('dd, .grp, .gist, h3').forEach(n => {
          const q = n.getBoundingClientRect();
          if (q.width && q.right > r.right + 1) out.push(n.className || n.tagName);
        });
      });
      return out;
    }""")
    check('no row escapes its card', not escaped, escaped[:4])
    check('the page never scrolls sideways',
          page3.evaluate('document.documentElement.scrollWidth <= '
                         'document.documentElement.clientWidth + 1'))

    # every section tab paints, and the shared tail really is factored out
    n_tabs = page3.locator('#tabs button').count()
    check('the patch page carries the Hub top bar like every other page',
          page3.locator('.topbar .module-launcher').count() == 1)

    # patch.jsx RIFT: Champions, Items, Runes, Systems, whichever this patch's notes carry
    rift = [x['name'] for x in notes.get('sections', [])
            if x.get('name') in ('Champions', 'Items', 'Runes', 'Systems')]
    check('one tab per rift section', n_tabs == len(rift), (n_tabs, rift))
    for i in range(n_tabs):
        page3.locator(f'#tabs button[data-i="{i}"]').click()
        page3.wait_for_timeout(250)
        check(f'tab {i} paints', page3.locator('.entry').count() > 0)
    page3.locator('#tabs button[data-i="0"]').click()
    page3.wait_for_timeout(250)
    page3.screenshot(path=f'{SHOT}/08-patch-page.png', full_page=True)

    # the build shelf is the front door again: no patch surface on it at all
    page3.goto(f'{BASE}/', wait_until='networkidle')
    page3.wait_for_timeout(500)
    check('the landing page carries no patch surface',
          page3.locator('#notes, .entries').count() == 0,
          page3.locator('#notes, .entries').count())
    check('and links to the patch tab instead',
          page3.locator('.navtabs a[href="patch"]').count() == 1)
    page3.locator('.navtabs a[href="patch"]').click()
    page3.wait_for_load_state('networkidle')
    check('the tab actually navigates', page3.url.endswith('/forge/patch'), page3.url)

    check('no uncaught script errors on the patch page', not e3, e3[:3])
    check('every request answered on the patch page', not bad3, bad3[:4])

    # ── the qualitative layer: alternatives and notes ─────────────────────
    # Authoring only, on its own page. Nothing here saves: writing a set would
    # leave a run's scratch build in the real library, and the round trip is
    # already pinned in tests/test_forge_api.py without a browser.
    print('\n== the qualitative layer ==')
    p5 = ctx.new_page()
    e5 = []
    p5.on('pageerror', lambda e: e5.append(str(e)))
    p5.goto(f'{BASE}/c/Viego/jungle/build', wait_until='networkidle')
    p5.wait_for_timeout(700)
    p5.locator('#stepnav [data-step="runes"]').click()
    p5.wait_for_timeout(300)
    check('the alternatives panel stays hidden with nothing recorded',
          p5.locator('#alts').is_hidden())

    p5.locator('#armAlt').click()
    p5.wait_for_timeout(200)
    check('arming opens the panel and says what to click',
          p5.locator('#alts').is_visible()
          and 'record it as an alternative' in p5.locator('#alts .quiet').first.inner_text())
    check('and the half with no alternative is visibly out of play',
          p5.locator('#step1[data-arming]').count() == 1)

    p5.locator('#secondaryCol .treebody:not([hidden]) .rpick[aria-pressed="false"]').first.click()
    p5.wait_for_timeout(300)
    check('a rune click opens the note editor rather than taking the rune',
          p5.locator('#noteDlg').is_visible())
    p5.locator('#noteText').fill('Into a poke lane where you never get to auto them.')
    p5.locator('#noteOk').click()
    p5.wait_for_timeout(300)
    row = p5.locator('#alts .alt').first.inner_text().lower()
    check('the alternative records with what it replaces and its note',
          p5.locator('#alts .alt').count() == 1 and 'instead of' in row and 'poke lane' in row,
          row.replace('\n', ' | '))
    check('and arming turns itself off after the one',
          p5.locator('#armAlt[aria-pressed="false"]').count() == 1)

    # the build itself has no alternative: a different keystone is a different build
    p5.locator('#armAlt').click()
    p5.locator('#primaryCol .rrow.keys .rpick').first.click()
    p5.wait_for_timeout(250)
    check('the keystone refuses, with the reason on the page',
          'keystone is the build' in p5.locator('#alts .quiet').first.inner_text())
    check('and refusing never opens the editor', p5.locator('#noteDlg').is_hidden())
    p5.locator('#primaryCol .treepick button').nth(1).click()
    p5.wait_for_timeout(250)
    check('the primary tree refuses too',
          'primary tree is the build' in p5.locator('#alts .quiet').first.inner_text())
    p5.locator('#armAlt').click()

    # an item note, and the card it has to be visible on
    p5.locator('[data-step="items"]').click()
    p5.wait_for_timeout(500)
    p5.evaluate("""() => {
      const el = [...document.querySelectorAll('#shelves .item')].find(e => e.offsetParent !== null);
      const dt = new DataTransfer();
      dt.setData('text/plain', el.dataset.id);
      document.querySelector('.slots').dispatchEvent(
        new DragEvent('drop', { dataTransfer: dt, bubbles: true }));
    }""")
    p5.wait_for_timeout(300)
    p5.locator('#blocks .slot').first.hover()
    p5.locator('#blocks .slot .nt').first.click()
    p5.wait_for_timeout(300)
    check('the same editor serves an item', p5.locator('#noteDlg').is_visible())
    p5.locator('#noteText').fill('Rush this whenever they have a bruiser jungler.')
    p5.locator('#noteOk').click()
    p5.wait_for_timeout(300)
    check('the annotated slot is marked without being hovered',
          p5.locator('#blocks .slot[data-noted]').count() == 1)
    p5.locator('#blocks .slot').first.hover()
    p5.wait_for_timeout(350)
    hc = p5.locator('.hovercard')
    # read the RENDERED card, never an attribute: the note has to be on screen
    check('and the note is rendered on the card, above the measurements',
          hc.is_visible() and 'bruiser jungler' in hc.inner_text(),
          hc.inner_text()[:70] if hc.is_visible() else 'card hidden')
    check('the client export carries none of it',
          'bruiser' not in p5.locator('#out').inner_text())
    p5.screenshot(path=f'{SHOT}/09-qualitative-layer.png', full_page=True)
    check('no uncaught script errors through the whole qualitative flow', not e5, e5[:3])


    # ── autosave: after one manual save the row keeps itself current ─────────
    print('\n== autosave: items and runes write themselves once the row exists ==')
    NAME = 'autosave probe zz'

    def probe_rows():
        return [x for x in json.loads(
            p6.evaluate("async () => JSON.stringify(await (await fetch('api/sets')).json())")
        )['sets'] if x['name'] == NAME]

    p6 = ctx.new_page()
    e6 = []
    p6.on('pageerror', lambda e: e6.append(str(e)))
    p6.goto(f'{BASE}/c/Master%20Yi/jungle/build', wait_until='networkidle')
    p6.evaluate("() => localStorage.removeItem('itemSetForge')")
    p6.reload(wait_until='networkidle')

    p6.locator('#stepnav [data-step="runes"]').click()
    p6.wait_for_timeout(300)
    p6.evaluate("() => document.querySelector('[data-slot=\"ks\"]')?.click()")
    p6.fill('#title', NAME)
    p6.click('#toItems')                       # the manual save that creates the row
    p6.wait_for_timeout(1500)
    rows = probe_rows()
    check('the manual save creates exactly one row to autosave onto', len(rows) == 1, len(rows))

    if len(rows) == 1:
        n0 = sum(len(b_['items']) for b_ in rows[0]['blocks'])
        p6.evaluate("""() => {
          const dt = new DataTransfer();
          dt.setData('text/plain', '1001');
          document.querySelector('#blocks .block[data-bi="0"] .slots')
            .dispatchEvent(new DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: dt}));
        }""")
        p6.wait_for_timeout(2200)
        after = probe_rows()
        n1 = sum(len(b_['items']) for b_ in after[0]['blocks'])
        check('an item edit writes itself with no Save clicked', n1 > n0, f'{n0} -> {n1}')

        r0 = json.dumps(after[0].get('runes'))
        p6.click('[data-step="runes"]')
        p6.wait_for_timeout(300)
        sel = ('() => document.querySelector(\'[data-slot="ks"][aria-pressed="true"]\')'
               '?.dataset.rune')
        ks0 = p6.evaluate(sel)
        p6.evaluate("""() => {
          const cur = document.querySelector('[data-slot="ks"][aria-pressed="true"]');
          const alt = [...document.querySelectorAll('[data-slot="ks"]')].find(e => e !== cur);
          if (alt) alt.click();
        }""")
        p6.wait_for_timeout(300)
        ks1 = p6.evaluate(sel)
        # guard the test itself: a selector that stops matching would otherwise
        # read as "autosave is broken" when nothing was ever edited
        check('the probe actually changed the keystone', ks0 != ks1, f'{ks0} -> {ks1}')
        p6.wait_for_timeout(2200)
        r1 = json.dumps(probe_rows()[0].get('runes'))
        check('a rune edit writes itself with no Save clicked', r0 != r1)

    for row in probe_rows():                   # leave the log as it was found
        p6.evaluate("id => fetch('api/sets/' + id, {method: 'DELETE'})", row['id'])
    p6.wait_for_timeout(400)
    check('the autosave probe cleaned up after itself', not probe_rows())
    check('no uncaught script errors through the autosave flow', not e6, e6[:3])

    # ── the plan page: spells, levels, pathing, bans ──────────────────────
    # Cold, on a jungler, because pathing shows on the role and nowhere else. The
    # five things checked are the five the page could get wrong quietly: the ult
    # rule, the five-point cap, a max order that disagrees with the grid it is read
    # off, a path note dropped on the way to the server, and bans that fork with a
    # set instead of staying with the champion.
    print('\n== the plan page ==')
    PNAME = 'plan probe zz'
    PCHAMP = 'Master Yi'

    def plan_rows(pg):
        return [x for x in json.loads(
            pg.evaluate("async () => JSON.stringify(await (await fetch('api/sets')).json())")
        )['sets'] if x['name'] == PNAME]

    def ban_keys(pg):
        return json.loads(pg.evaluate(
            "async c => JSON.stringify(await (await fetch('api/bans/' + encodeURIComponent(c)))"
            ".json())", PCHAMP))['champions']

    p7 = ctx.new_page()
    e7 = []
    p7.on('pageerror', lambda e: e7.append(str(e)))
    p7.goto(f'{BASE}/c/Master%20Yi/jungle/build', wait_until='networkidle')
    p7.evaluate("() => localStorage.removeItem('itemSetForge')")
    p7.reload(wait_until='networkidle')

    # a row to autosave onto, the same way the autosave probe makes one
    p7.locator('#stepnav [data-step="runes"]').click()
    p7.wait_for_timeout(300)
    p7.evaluate("() => document.querySelector('[data-slot=\"ks\"]')?.click()")
    p7.fill('#title', PNAME)
    p7.click('#toItems')
    p7.wait_for_timeout(1200)

    p7.locator('#stepnav [data-step="plan"]').click()
    p7.wait_for_timeout(400)
    check('the plan step opens', p7.locator('#step3:visible').count() == 1)
    check('pathing shows on a jungler', p7.locator('#planPathCard:visible').count() == 1)

    # --- summoner spells: two slots, and the third pick drops the older one
    for sid in (4, 11, 14):
        p7.click(f'[data-spell="{sid}"]')
        p7.wait_for_timeout(120)
    on = p7.evaluate("() => [...document.querySelectorAll('#planSpells [data-spell]')]"
                     ".filter(b => b.getAttribute('aria-pressed') === 'true')"
                     ".map(b => +b.dataset.spell)")
    check('two spells at a time, the oldest dropped', sorted(on) == [11, 14], on)

    # --- the ult rule, which is the only rule the grid enforces itself
    def dis(a, lv):
        return p7.locator(f'button[data-sk="{a}"][data-lv="{lv}"]').is_disabled()
    check('R is refused off 6/11/16', dis('R', 1) and dis('R', 5) and dis('R', 7))
    check('R is offered at 6, 11 and 16',
          not dis('R', 6) and not dis('R', 11) and not dis('R', 16))
    check('6/11/16 take nothing but R', dis('Q', 6) and dis('W', 11) and dis('E', 16))

    # --- the five-point cap, which the grid cannot show and so has to say
    for lv in (1, 3, 5, 7, 9):
        p7.click(f'button[data-sk="Q"][data-lv="{lv}"]')
        p7.wait_for_timeout(80)
    p7.click('button[data-sk="Q"][data-lv="12"]')
    p7.wait_for_timeout(200)
    qn = p7.evaluate("() => [...document.querySelectorAll('button[data-sk=\"Q\"]')]"
                     ".filter(b => b.getAttribute('aria-pressed') === 'true').length")
    check('a sixth point in Q is refused', qn == 5, qn)
    check('and the page says why', 'already at 5' in p7.inner_text('#planSub'))

    # --- the max order is READ OFF the grid, never typed
    for lv in (2, 4, 8, 10, 12):
        p7.click(f'button[data-sk="W"][data-lv="{lv}"]')
        p7.wait_for_timeout(80)
    p7.click('button[data-sk="E"][data-lv="13"]')
    p7.wait_for_timeout(200)
    order = p7.inner_text('.pl-order')
    check('the max order reads Q then W off the grid', 'Q > W > E' in order, order)
    p7.click('button[data-sk="Q"][data-lv="1"]')          # take a point back out
    p7.wait_for_timeout(250)
    check('and it moves when the grid does, with nothing typed',
          'W > Q > E' in p7.inner_text('.pl-order'), p7.inner_text('.pl-order'))

    # --- a path, its camps, and the note that says when you take it
    p7.click('#planPathAdd')
    p7.wait_for_timeout(200)
    p7.fill('[data-pathname="0"]', 'Full clear, top side')
    for camp in ('red', 'krugs', 'raptors', 'gank-mid'):
        p7.click(f'[data-pathadd="0:{camp}"]')
        p7.wait_for_timeout(80)
    p7.click('[data-pathnote="0"]')
    p7.wait_for_timeout(300)
    p7.fill('#noteText', 'Take this when their jungler starts bot side.')
    p7.click('#noteOk')
    p7.wait_for_timeout(2400)                              # autosave rides persist()

    rows = plan_rows(p7)
    check('the plan saved onto the one row', len(rows) == 1, len(rows))
    if len(rows) == 1:
        pl = rows[0].get('plan') or {}
        path = (pl.get('paths') or [{}])[0]
        check('the spells survived the save', sorted(pl.get('spells') or []) == [11, 14],
              pl.get('spells'))
        check('the skill grid survived the save',
              (pl.get('skills') or [None])[1] == 'W' and (pl.get('skills') or [None])[12] == 'E',
              (pl.get('skills') or [])[:14])
        check('the path camps survived the save',
              path.get('camps') == ['red', 'krugs', 'raptors', 'gank-mid'], path.get('camps'))
        check('the path NOTE survived the save',
              'bot side' in (path.get('note') or ''), path.get('note'))
        check('no ban rode along inside the set', 'bans' not in (rows[0].get('plan') or {}))

    # --- the figures: every element that HAS a reading shows it, and the one
    # that has none says so. The failure these catch is the quiet one - a
    # figure rendered from nothing, or a lane that silently went blank when a
    # bake key was renamed - not a crash.
    lo = json.loads(p7.evaluate(
        "async () => JSON.stringify(await (await fetch('api/lolalytics')).json())"
    ))['champions'].get(PCHAMP, {}).get('jungle', {})

    check('the plan page is two columns, not four full-bleed cards',
          len(p7.evaluate("() => getComputedStyle(document.querySelector('.planpage'))"
                          ".gridTemplateColumns.split(' ')")) == 2)

    spell_fig = p7.evaluate(
        # [data-spell] and not `.pl-opt > button`: the note button is a direct
        # child too, and it correctly carries no figure.
        "() => [...document.querySelectorAll('#planSpells button[data-spell]')]"
        ".map(b => [...b.querySelectorAll('.wpa')].map(e => e.textContent.trim()))")
    check('every spell row carries a coachless lane, dash or figure',
          all(len(f) == 1 and f[0] for f in spell_fig), spell_fig[:3])
    check('and at least one of them is a real reading, not all dashes',
          any(f[0].startswith(('+', '\u2212')) for f in spell_fig), spell_fig[:3])

    # lolalytics publishes ONE pair and no per-spell figure, so it must be
    # printed under the list and must never appear in a per-spell lane.
    pair = p7.inner_text('#planSpellPair')
    check('the lolalytics pair is printed under the list, not in a lane',
          'pair is' in pair and 'win over' in pair, pair)

    fig = p7.inner_text('#planSkillFig')
    lv = (lo.get('plan') or {}).get('levels')
    check("the skill order is lolalytics' own, level for level",
          not lv or all(f"{a} {chr(183).join(str(n) for n in ns)}" in fig
                        for a, ns in lv['levels'].items() if ns), fig)

    # A ban list built from the champions this one loses to, worst first.
    sug = p7.evaluate("() => [...document.querySelectorAll('#planBanSug .pl-opt')]"
                      ".map(e => [e.querySelector('.nm').textContent.trim(),"
                      " parseFloat(e.querySelector('.wpa').textContent)])")
    counters = [(c['n'], c['wr']) for c in lo.get('counters') or []]
    check('the ban card suggests the worst matchups, worst first',
          not counters or (sug and [w for _, w in sug] == sorted(w for _, w in sug)), sug[:3])
    check('and every suggestion is a champion lolalytics actually named',
          all(n in dict(counters) for n, _ in sug), [n for n, _ in sug][:5])

    # --- bans: keyed by champion, so they do not fork with a set
    before = ban_keys(p7)
    p7.fill('#planBanIn', 'Kayle')
    p7.dispatch_event('#planBanIn', 'change')
    p7.wait_for_timeout(900)
    after = ban_keys(p7)
    check('a ban writes itself against the champion', 10 in after and 10 not in before, after)

    p8 = ctx.new_page()
    p8.goto(f'{BASE}/c/Master%20Yi/jungle/build?new=1', wait_until='networkidle')
    p8.locator('#stepnav [data-step="plan"]').click()
    p8.wait_for_timeout(700)
    check('a DIFFERENT set on the same champion reads the same bans',
          p8.locator('#planBans [data-banoff="10"]').count() == 1)
    check('and no plan came with it', not p8.evaluate(
        "() => (JSON.parse(localStorage.getItem('itemSetForge') || '{}').plan?.skills || [])"
        ".some(Boolean)"))
    p8.close()

    # leave the log and the ban list as they were found
    p7.evaluate("""async ([c, keep]) => {
      await fetch('api/bans/' + encodeURIComponent(c), {
        method: 'PUT', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({champions: keep}),
      });
    }""", [PCHAMP, before])
    for row in plan_rows(p7):
        p7.evaluate("id => fetch('api/sets/' + id, {method: 'DELETE'})", row['id'])
    p7.wait_for_timeout(400)
    check('the plan probe cleaned up after itself',
          not plan_rows(p7) and ban_keys(p7) == before)
    p7.screenshot(path=f'{SHOT}/10-plan.png', full_page=True)
    check('no uncaught script errors through the plan flow', not e7, e7[:3])
    p7.close()

    for w, h in ((2560, 1300), (1280, 1300)):
        print(f'\n== layout at {w}x{h} ==')
        cw = b.new_context(viewport={'width': w, 'height': h})
        pw_ = cw.new_page()
        pw_.goto(f'{BASE}/c/Viego/jungle/build', wait_until='networkidle')
        pw_.wait_for_timeout(700)
        # guard the check itself: a probe that never reaches step two would pass
        # on an empty page and read as "nothing is clipped"
        pw_.click('[data-step="items"]')
        pw_.wait_for_timeout(900)
        shown = pw_.locator('.item:visible')
        check(f'{w}px: the shop actually painted', shown.count() > 20, shown.count())
        clipped = settled_clip(pw_)
        check(f'{w}px: nothing clipped by a hidden overflow', not clipped, clipped[:4])
        shown.first.click()                     # the inspector is the narrow-column case
        pw_.wait_for_timeout(600)
        clipped = settled_clip(pw_)
        check(f'{w}px: nothing clipped with the inspector open', not clipped, clipped[:4])
        pw_.screenshot(path=f'{SHOT}/09-layout-{w}.png')
        cw.close()

    guarded_draft_pass(b)

    ctx.close()
    b.close()

print('\n' + ('ALL CHECKS PASSED' if not fails else f'{len(fails)} FAILED: ' + '; '.join(fails)))
sys.exit(1 if fails else 0)
