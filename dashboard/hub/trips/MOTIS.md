# MOTIS — the transit router behind the day-of "Getting there" card

The Transit tab names actual trains and buses, in their own colours, drawn on the
map. The answer comes from a **self-hosted MOTIS instance** on this machine, not
from a public service.

- Engine: MOTIS v2.11.2, static Linux binary (no Docker on this host)
- Lives in: `~/motis` (WSL-side, deliberately — `/mnt/c` is ~243x slower and the
  street graph is a 1.8 GB read-heavy database)
- Serves: `http://127.0.0.1:8080`
- Runs as: `motis.service` (systemd **user** unit, same pattern as
  `hub-dashboard.service` and `trips-public.service`)
- Reached by the browser through: `/trips/api/transit` in `api.py`

## Why self-hosted, and why proxied

`api.transitous.org` runs the same engine and answers the same query, but their
usage policy asks that the consuming project be open source. vault-code is
private, so the engine is hosted here instead. Do not quietly fall back to their
public endpoint.

The browser never calls the router. It calls the Hub, which calls the router.
Two reasons, both the funnel: the router listens on loopback and a guest opening
the shared link has no loopback to reach, and a public router host in the
mirror's `connect-src` would be a second host to trust. Proxied, the mirror's CSP
stays at `'self'`.

## THE ONE THING THAT WILL GO WRONG: the bus horizon

The MTA publishes **bus** timetables about ten weeks at a time. Subway runs
months further out, and the commuter rails further still — but **no subway
reaches LaGuardia**, so every trip to that airport ends on a bus and inherits the
earliest horizon on the board.

Past the end of the timetable the router does **not** answer empty. It answers
with the last day it has, dated that day, with no flag on it — a plausible set of
trains for a day in the past, which is the worst failure this card could have.
`api_transit` catches it by comparing the date it asked for against the date it
got back (both read in the ride's zone) and returns `stale_for` / `asked_for`;
the card then says so in red above the Google Maps link.

**When the card says a timetable is not published yet, the fix is a re-import,
not a code change** — and only once the MTA has actually published the window.
Re-imported 2026-09-16: all seven MTA bus feeds now run to **2027-01-02**, and the
router was verified answering correctly-dated F + Q70-SBS itineraries to LGA for
2026-09-17, 2026-09-20 and 2026-12-20. The window before that ended 2026-09-05.

**One feed can run out while the others keep going, and the date check above misses
it.** The subway feed imported 2026-09-16 ended 2026-10-31 while the bus feeds ran to
2027-01-02, so from 2026-11-01 every answer was buses only, correctly dated (a
75-minute four-bus ride to Chrystie St where the F takes 20). `api_transit` now reads
each NYC feed zip's last service day (`_ended_feeds`) and returns `feeds_ended`; the
Home card drops those routes and names the timetable that ran out. Re-imported
2026-11-03: subway now runs to 2027-05-15, MTA buses still 2027-01-02.

**PATH is the exception, and it is stale right now.** Its last service day is
**2026-06-01**, so it was already past its horizon before the 2026-09-16 refresh and
re-downloading it changed nothing — Trillium's mirror is serving an expired feed.
Any Newark journey whose last leg is PATH will therefore answer with a date in the
past, and `api_transit`'s stale check only compares the date of the *itinerary*, so
it does catch this. Nothing depends on it until a trip departs from Newark; the fix
is a live source for PATH, not a re-import.

## THE OTHER THING: New Jersey needs BOTH a timetable and ground

Twelve feeds are loaded. Nine are MTA (five borough bus feeds, the bus company,
LIRR, Metro-North, subway); three are New Jersey — NJ Transit rail, NJ Transit bus
and PATH, added 2026-08-31 so the card could answer for Newark.

**Adding the feeds alone did nothing, and the reason is the trap worth writing
down.** After the first import the geocoder happily returned `NEWARK PENN STATION`
at the right coordinates — the timetable had New Jersey in it — and every routing
query into the state still came back empty. The discriminator was `one-to-all` on
foot: 79 walk-reachable stops from his Brooklyn door, **0** from downtown Newark.

`osr_footpath: true` means every stop is reached over the OSM street router, so a
stop with no roads under it is unreachable no matter how complete its timetable is.
Geofabrik's `new-york-latest.osm.pbf` is New York **State** — it has no New Jersey
streets. The stops were there; the ground was not.

So the extract is now NY + NJ merged (see the next section), and **a feed for a
place outside the current extract needs the extract widened in the same pass.**
Check with `one-to-all` before concluding a feed failed to import.

**AirTrain Newark is not available as open GTFS.** transit.land holds it behind an
API token and the Mobility Database catalog carries JFK's AirTrain but not Newark's.
The rail station is 2.1 km from the terminals with nothing published closing that
gap, which is why NJ Transit's *bus* feed is loaded too — its airport stop is about
690 m from Terminal C, inside the footpath limits.

**NJ Transit rail's timetable runs much further out than the MTA's buses** — as
imported 2026-08-31, service dates run 2026-08-18 to 2027-02-13, against the MTA
bus feeds' 2026-09-05. The horizon warning above is still governed by the earliest
feed the answer actually uses.

## The OSM extract is MERGED AND PATCHED, and a re-import must rebuild it

`config.yml` points at `data/nyc-metro-patched.osm.pbf`, **not** anything Geofabrik
ships. Two downloads stay pristine — `data/new-york-latest.osm.pbf` and
`data/new-jersey-latest.osm.pbf` — and the file the router reads is built from both
plus the Bergen St patch.

**Download both state extracts on the SAME DAY or the merge will not import.**
Geofabrik cuts every extract from one daily planet snapshot, so two files cut on
different days can carry the same node at different versions. `osmium merge`
dedupes on id *and* version, so it keeps both copies and the import dies on
`unable to import: input: duplicate absolute node id with mismatching coordinates`.
Seen 2026-08-31 with node `103148451`: v3 from 2009 in an Aug 28 New York cut, v4
from 2026-08-30 in a same-day New Jersey cut. Re-fetching New York that day made
both v4 with identical coordinates and the merge imported clean. The error names
one node id; the cause is the pair of cut dates, not that node.

Why: Bergen St (F,G) has six `railway=subway_entrance` nodes in OpenStreetMap and
nothing behind them — the nodes belong to no way at all, and both platforms are
four-corner closed areas at level -1 sharing no node with anything. There is no
street-to-platform path, so the router could not walk anyone into the station. It
answered by walking 2.7 km to the elevated 4 Av-9 St, or by putting the rider on a
one-minute bus to Carroll St, which is what made the Transit tab untrustworthy to a
New Yorker who would simply walk the eight minutes to Bergen.

The patch adds 16 ways and no new nodes: per entrance, a level-0 footway to the
nearest sidewalk node and a `highway=steps` way (`level=-1;0`) down to the nearest
platform corner, plus a level -1 footway perimeter on each platform and two
mezzanine cross-links between them.

```sh
cd ~/motis
osmium merge data/new-york-latest.osm.pbf data/new-jersey-latest.osm.pbf \
  patches/bergen-st-stairs.osm -o data/nyc-metro-patched.osm.pbf --overwrite
```

`patches/gen-bergen-st-stairs.py` regenerates the patch file from the node ids it
lists, so the mapping is readable rather than a blob of XML to trust.

**Skip the merge on a re-import and the one-minute bus comes straight back**, with
no error to say why — the import will succeed against an unpatched extract and the
card will simply go back to routing him onto a bus.

The permanent fix is the same six stairways added to OpenStreetMap itself, which
survives every extract refresh and fixes it for everyone. That is an edit on
Sam's own OSM account, so it is his to make, not something to do for him.

`osmium` here is the Ubuntu `osmium-tool` package, extracted without root into
`~/.local/opt/osmium` with a wrapper at `~/.local/bin/osmium` (the deb plus
`libboost-program-options1.90.0`, unpacked with `dpkg -x`).

## Re-import (refresh the feeds)

```sh
cd ~/motis
for f in gtfs_subway gtfs_b gtfs_q gtfs_m gtfs_bx gtfs_si gtfs_busco gtfsmnr gtfslirr; do
  curl -sL -o data/$f.zip https://rrgtfsfeeds.s3.amazonaws.com/$f.zip
done
# The New Jersey three. NJ Transit answers curl fine through its redirects; PATH
# comes off Trillium's mirror. Neither needs a token.
curl -sL -o data/gtfs_njt_rail.zip https://www.njtransit.com/rail_data.zip
curl -sL -o data/gtfs_njt_bus.zip  https://www.njtransit.com/bus_data.zip
curl -sL -o data/gtfs_path.zip \
  https://data.trilliumtransit.com/gtfs/path-nj-us/path-nj-us.zip

# The OSM extract only needs refreshing if the street network matters to you;
# it changes far more slowly than the timetables. If you DO refresh it, fetch
# BOTH states in the same run (see the same-day rule above) and re-merge the
# Bergen St patch before the import.
curl -sL -o data/new-york-latest.osm.pbf \
  https://download.geofabrik.de/north-america/us/new-york-latest.osm.pbf
curl -sL -o data/new-jersey-latest.osm.pbf \
  https://download.geofabrik.de/north-america/us/new-jersey-latest.osm.pbf
osmium merge data/new-york-latest.osm.pbf data/new-jersey-latest.osm.pbf \
  patches/bergen-st-stairs.osm -o data/nyc-metro-patched.osm.pbf --overwrite

systemctl --user stop motis
./motis import -c config.yml          # ~10 min, mostly the street graph
systemctl --user start motis
```

Two notes on the data:

- **`gtfslirr.zip` answers `curl -L` but returns nothing to `HEAD`.** An earlier
  session concluded the URL was dead on that basis. It is not; S3 just refuses the
  HEAD. Verify feed URLs with a GET.
- `config.yml` is generated by `motis config <files...>`. The generated file
  includes a `tiles:` block and `railviz: true`; both were removed here because we
  serve neither (the card uses OSM raster tiles), and the tile build is enormous.

`first_day: TODAY` is baked at import time, so a re-import is also how the
timetable window rolls forward.

## Timezone

The router refuses a time with no zone on it (a bare `2026-08-31T13:00:00`
answers `missing parameter`). The card sends a **naive** local time and `api.py`
stamps `_RIDE_TZ` on it, and converts the answers back to local
minutes-past-midnight (`start_min` / `end_min`) so the browser never guesses a
zone — a guest reading the page from another country would otherwise stamp their
own offset onto an American morning.

`_RIDE_TZ` is one constant because every airport this board departs from is
Eastern. An airport-to-timezone column is the upgrade the first non-Eastern
departure needs.
