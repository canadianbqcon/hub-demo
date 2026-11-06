# CLAUDE.md — dashboard/hub/ledger

Float & Ledger: a CS2 inventory book served at `/ledger`, backed by `data/cs2.db`.

Listed on the Hub `/artifacts` page under **Projects** — a self-hosted project, not
a claude.ai Artifact — rather than getting a `hub_modules.py` launcher tile. Same
call as `/forge`, for the same reason: the `/artifacts` catalog is Sam's list of
"things I made", and registering it in both places would give it two meanings.

Design of record: `docs/archive/specs/2026-08-25-ledger-hub-module-design.md`
(surfaces, table shapes, ship order) over
`docs/archive/specs/2026-08-25-cs2-inventory-value-tracker-design.md`
(methodology, endpoint list, the agy+codex adversarial verdicts). Both are reviewed;
a material divergence from either needs `/adversarial` re-run before it ships.

## Four surfaces

| URL | Surface | File |
|---|---|---|
| `/ledger/` | **the book** — portfolio mark, the three numbers, every holding in one table | `book.html` |
| `/ledger/i/<market_hash_name>` | **one item** — price history, sale tape, venue board, float comps | `item.html` |
| `/ledger/sell` | **the sell desk** — liquidation schedule, per-item route, a batch plan | `sell.html` |
| `/ledger/index` | **the index** — constant-basket chart, category baskets, snapshot diffs | `index.html` |

## The basis is the whole problem, not the venue

The same inventory prices **$810 to $1,400** depending on which defensible statistic
you pick, against a cross-venue floor spread of only ~13%. So every number this
module renders carries the basis that produced it, and the ones that must never
appear are enumerated:

- **Never price off `min_price` / cheapest listing.** It is an order statistic that
  falls with listing depth — measured 2.3% below median at 1–9 listings, 37.5% at
  200–999. Genesis Terminal reads $23.52 on one Skinport listing against a $0.20
  30-day sale median over 751 trades. A 118x error inside an ordinary-looking number.
- **Never blend venues into one number.** A blended price exists on zero exchanges.
  The venue board averages nothing; only the net column ranks.
- **Never emit an instant-liquidation value.** No free feed carries a buy-order book,
  so it is unknowable rather than estimable. The sell desk is a 1/7/30/90-day
  schedule instead, naming what would not clear at each horizon.
- **Never collapse the two fee lines.** Seller fee (CSFloat 2%, Buff163 2.5%,
  Waxpeer 6%, Skinport 12% / 6% over EUR1000, Steam 15%) and then withdrawal +
  processor + FX friction at 2–5%. "Net after fee" is not cash in hand.
- **The total is labelled "marketable inventory".** Thirteen coins, medals and badges
  are correctly $0, and the label carries the caveat the number cannot.

## Collector and engine are separate on purpose

`collect.py` writes snapshots and interprets nothing: six sources, each in its own
`snapshot` row and its own try block, so a Waxpeer 500 marks that source `ok=0` and
the run prices from the sources that answered. `value.py` is a pure function over
stored snapshots — adaptive window, outlier filter, confidence scoring, fees. The
basis will change; re-pricing the whole history must not mean re-fetching it.

Two collector details that are load-bearing rather than incidental:

- **`_get()` shells to `curl --compressed`.** Skinport serves brotli and 406s on
  gzip or identity, and the stdlib has no brotli decoder. curl links one in already,
  so this is the cheap route, not a new dependency.
- **Steam's public inventory endpoint rate-limits an IP hard** once it has seen a
  portfolio sweep, and stays 429 for a long while. `--steam-json` seeds holdings from
  a saved dump; a throttled run degrades to pricing the holdings already on file.
  Do not retry-loop it — the throttle is the endpoint working as intended.

## The outlier filter is trailing, never lifetime

CSFloat's daily series publishes an **average**, not a median, so a 2-trade day on a
cheap item reads ~9x high (3.89% of item-days sit above 3x their own trailing median).
`flag_outliers()` compares each day against the median of the **trailing 30 calendar
days** and rejects above 3x.

Comparing against whole-history median instead is a known trap and was caught before
any conclusion was drawn from it: the P250 See Ya Later reads a $3.15 lifetime median
against $99 today, so lifetime comparison flags genuine appreciation as contamination.
`--selfcheck` asserts exactly this, plus that a baseline older than the lookback never
judges today. Run it after touching the filter.

**Rejected days are kept in `daily_sale` with `rejected=1` and drawn greyed on the
item page — never deleted.** A filter that hides its own discards cannot be checked
by the person relying on it, and the discards are where the $23.52 seven-cent item
would have shown up.

## The confidence chip is the point of the table, not decoration

`solid` = ≥30 trades inside a window of 7 days or shorter. `thin` = priced, but the
window stretched to 30 or 90 days. `stale` = no sale in 90 days, carrying the last
mark, never zeroed. `n/a` = untradable, excluded from every total.

A row reading `$252.34` with a `thin` chip and `16` in the depth column is telling the
truth about a knife. The same row with the chip removed is not. **The chip is never
suppressed for compactness**, and the header's change figure ships with a noise
verdict that defaults to *"not distinguishable from marking noise"* until a move
clears the friction band.

## Known gap: floats are uncaptured

The public Steam inventory JSON returns generic `%propid:6%` action links with no
D-parameter, so inspect links — and therefore float values — are not derivable from
it. `holding.float_value` and `holding.paint_seed` stay NULL until a logged-in Steam
session can supply them. This gates the Talon, which is 22% of the book on 16 trades
a month. The item page renders the float band it *would* use and says the float is
uncaptured, so the gap is visible on the page rather than buried in a spec.
