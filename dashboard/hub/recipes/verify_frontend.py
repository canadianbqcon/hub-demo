"""Headless render check for /recipes, at the three widths the layout rule binds.

    python3 verify_frontend.py            # the Hub must already be up on 5002
    python3 verify_frontend.py http://127.0.0.1:5012/recipes   # any other Hub, e.g. the sandbox

Drives the page into its real interactive states — search typed, a category chip
pressed, the multi-select tray up, the pantry matcher run, the detail scaler used
— because a first-paint screenshot is a screenshot of a page nobody uses.

Two probes per state, per wiki/patterns/dashboard-responsive-layout:
  * CLIP    — content taller/wider than a box whose overflow is hidden (rules 1-3)
  * PORTHOLE — a released pane on a phone holding back its own content (rule 4)

Screenshots land in the Downloads process folder. Exits non-zero on any finding.

One artifact to ignore: CJK titles render as tofu boxes here because this WSL image
ships no CJK font. The notes are clean UTF-8 and Windows Chrome renders them.
"""
import sys
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:5002/recipes'
SHOT = '/app/home/Downloads/recipes-module-verify'

# 2560x1300 maximised, 1280x1300 half-snapped (the binding one), 390x844 phone.
SIZES = [(2560, 1300), (1280, 1300), (390, 844)]

CLIP_PROBE = """() => {
  const out = [];
  for (const el of document.querySelectorAll('*')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    if (cs.textOverflow === 'ellipsis') continue;
    if (cs.webkitLineClamp && cs.webkitLineClamp !== 'none') continue;
    if (/^(TEXTAREA|INPUT|SELECT)$/.test(el.tagName)) continue;
    const cy = el.scrollHeight - el.clientHeight, cx = el.scrollWidth - el.clientWidth;
    const hy = cs.overflowY === 'hidden' || cs.overflowY === 'clip';
    const hx = cs.overflowX === 'hidden' || cs.overflowX === 'clip';
    if ((cy > 4 && hy) || (cx > 4 && hx))
      out.push((el.tagName + '.' + el.className).slice(0, 60) + ' x=' + cx + ' y=' + cy);
  }
  return out;
}"""

# Rule 4's reading: once the document scrolls, no pane holds back its own content.
PORTHOLE_PROBE = """() => {
  const out = [];
  for (const sel of ['#recipes-root', '.rx-grid', '.rx-list', '.rx-cols', '.rx-detail']) {
    for (const el of document.querySelectorAll(sel)) {
      if (el.scrollHeight - el.clientHeight > 4) {
        const cs = getComputedStyle(el);
        if (cs.overflowY === 'auto' || cs.overflowY === 'scroll')
          out.push(sel + ' shows ' + el.clientHeight + ' of ' + el.scrollHeight);
      }
    }
  }
  return out;
}"""

# The clip/porthole probes measure boxes, not type — so they passed a page rendering
# in Times New Roman on white. This is the miss that shipped 2026-08-22: recipes.css had
# no `body` and no `.shell` rule, and /static/css/base.css carries no `body` selector to
# fall back on. Also asserts the [hidden] backstop, since .rx-tray/.rx-grid/.rx-chips each
# set `display` and an author `display` outranks the UA [hidden] rule.
SKELETON_PROBE = """() => {
  const out = [];
  const cs = getComputedStyle(document.body);
  const want = getComputedStyle(document.documentElement)
                 .getPropertyValue('--font-body').split(',')[0].trim().replace(/["']/g, '');
  if (!cs.fontFamily.includes(want))
    out.push('body font is ' + cs.fontFamily + ', expected ' + want + ' (no body rule?)');
  const shell = document.querySelector('.shell');
  if (shell && getComputedStyle(shell).display !== 'grid')
    out.push('.shell is not the page grid — #recipes-root has no bounded row');
  for (const el of document.querySelectorAll('[hidden]'))
    if (getComputedStyle(el).display !== 'none')
      out.push('[hidden] still rendering: .' + el.className);
  return out;
}"""

fails = []


def check(page, w, h, label):
    page.wait_for_timeout(250)
    tag = '%s-%dx%d' % (label, w, h)
    page.screenshot(path='%s/%s.png' % (SHOT, tag), full_page=(w == 390))
    clips = page.evaluate(CLIP_PROBE)
    for c in clips:
        fails.append('CLIP  %s  %s' % (tag, c))
    for k in page.evaluate(SKELETON_PROBE):
        fails.append('SKELETON  %s  %s' % (tag, k))
    if w <= 560:
        for p in page.evaluate(PORTHOLE_PROBE):
            fails.append('PORTHOLE  %s  %s' % (tag, p))
    print('  %-42s %s' % (tag, 'clean' if not clips else '%d CLIP' % len(clips)))



def index_states(page, w, h):
    page.goto(BASE + '/', wait_until='networkidle')
    page.wait_for_selector('.rx-card', timeout=15000)
    check(page, w, h, 'index-default')

    page.fill('.rx-search', 'chicken')
    page.wait_for_timeout(300)
    check(page, w, h, 'index-search')
    page.fill('.rx-search', '')
    page.wait_for_timeout(300)

    # drawChips() rebuilds the chip row on every press, so a stale handle detaches.
    if page.query_selector('.rx-chip'):
        page.click('.rx-chips .rx-chip:first-child')
        page.wait_for_timeout(200)
        check(page, w, h, 'index-chip')
        page.click('.rx-chips .rx-chip:first-child')
        page.wait_for_timeout(200)

    # same rebuild: drawGrid() replaces every card after each pick.
    for i in range(3):
        page.click('.rx-grid .rx-card:nth-child(%d) .rx-pick' % (i + 1))
        page.wait_for_timeout(120)
    page.wait_for_timeout(250)
    if page.query_selector('.rx-tray:not([hidden])') is None:
        fails.append('STATE %dx%d  tray did not appear after 3 picks' % (w, h))
    check(page, w, h, 'index-tray')

    page.click('.rx-btn')  # "what can I make?"
    page.wait_for_timeout(200)
    page.fill('.rx-pantry textarea', 'chicken\ngarlic\nsoy sauce\nrice')
    page.click('.rx-pantry .rx-bar .rx-btn')
    page.wait_for_timeout(1200)
    check(page, w, h, 'index-pantry')


def detail_states(page, w, h):
    page.goto(BASE + '/dal', wait_until='networkidle')
    page.wait_for_selector('.rx-title', timeout=15000)
    check(page, w, h, 'detail-default')

    num = page.query_selector('.rx-scaler input[type=number]')
    if num:
        num.fill('12')
        num.dispatch_event('change')
        page.wait_for_timeout(700)
    else:
        btns = page.query_selector_all('.rx-scaler .rx-btn')
        if btns:
            btns[-1].click()
            page.wait_for_timeout(700)
    page.wait_for_selector('.rx-title', timeout=15000)
    check(page, w, h, 'detail-scaled')

    for i in range(3):
        page.click('.rx-cols .rx-item:nth-child(%d) input' % (i + 1))
        page.wait_for_timeout(80)
    page.wait_for_timeout(200)
    check(page, w, h, 'detail-cooking')


with sync_playwright() as pw:
    browser = pw.chromium.launch(channel='chrome')
    for w, h in SIZES:
        print('%dx%d' % (w, h))
        ctx = browser.new_context(viewport={'width': w, 'height': h},
                                  device_scale_factor=1)
        page = ctx.new_page()
        index_states(page, w, h)
        detail_states(page, w, h)
        ctx.close()
    browser.close()

print()
if fails:
    print('%d finding(s):' % len(fails))
    for f in fails:
        print('  ' + f)
    sys.exit(1)
print('clean at all three widths')
