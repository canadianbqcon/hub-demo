# How the demo stays safe

This copy of the Hub is public, so `dashboard/hub/demo_mode.py` wraps it when `DEMO_MODE=1`:

- **No way out.** Every socket connect to a non-loopback address is refused, and so is every
  new process except the one `node` call that transpiles the JSX pages.
- **Every route is classified** in `dashboard/hub/endpoints.json`. The app refuses to boot if a
  route is missing from it. Routes that would call Claude, Google, a bank or a mail service
  answer 403 with a note instead (listed below). Routes that take a file path refuse anything
  outside the demo folder.
- **Shared, then reset.** Visitors can add, edit and tick things; at 00:00 UTC (and on boot) every
  database and file goes back to the fake set in `demo-vault/pristine/`.
- **Nothing real inside.** The export copies only tracked code, rewrites names through a scrub
  map, and fails if its scan finds a personal name, email, path or key.


Routes: 231 read, 197 write to the demo's own data, 54 switched off.

## Switched-off routes

| route | class | what it would reach |
|---|---|---|
| `DELETE /api/calendar/events/<event_id>` | integration | google calendar delete |
| `GET /api/calendar/auth` | integration | google calendar oauth |
| `GET /api/calendar/calendars` | integration | google calendar list |
| `GET /api/calendar/callback` | integration | google calendar oauth |
| `GET /api/docs/auth` | integration | google docs oauth |
| `GET /api/docs/callback` | integration | google docs oauth |
| `GET /api/drive/auth` | integration | google drive oauth |
| `GET /api/drive/callback` | integration | google drive oauth |
| `GET /api/gmail/auth` | integration | gmail oauth |
| `GET /api/gmail/callback` | integration | gmail oauth |
| `GET /api/gmail/message/<message_id>` | integration | gmail message fetch |
| `GET /api/sheets/auth` | integration | google sheets oauth |
| `GET /api/sheets/callback` | integration | google sheets oauth |
| `GET /api/transit` | integration | transit feed and geocode |
| `GET /api/transit/routes` | integration | google routes transit lookup |
| `GET /api/wx-extras` | integration | pollen api fetch |
| `GET /forge/api/conditioned` | integration | live coachless fetch |
| `GET /forge/api/draft/history` | integration | op.gg fetch |
| `GET /forge/api/me` | integration | op.gg fetch |
| `GET /mail/api/attachment/<msg>/<att>` | integration | gmail attachment fetch |
| `GET /news/api/items/<int:item_id>/read` | integration | fetches the article url |
| `GET /trips/api/prefs/address-search` | integration | geocoder lookup |
| `GET /trips/api/share-url` | integration | spawns tailscale |
| `GET /trips/api/transit` | integration | transit api fetch |
| `GET /trips/api/trips/<int:trip_id>/housing/<int:hid>/nearby` | integration | overpass lookup |
| `GET /viewer/api/terminals` | integration | spawns terminal listing |
| `POST /api/calendar/events` | integration | google calendar create |
| `POST /automations/api/act` | integration | gmail modify |
| `POST /automations/api/decisions/<int:did>/fix` | integration | undoes then redoes a gmail action |
| `POST /automations/api/decisions/<int:did>/undo` | integration | may reverse a gmail action |
| `POST /finances/api/book/sync` | integration | simplefin bank sync plus anthropic categorize |
| `POST /finances/api/owed/payments/scan` | integration | reads gmail for payments |
| `POST /inventory/api/scan` | integration | spawns inventory-scan process |
| `POST /inventory/api/uninstall` | integration | runs an uninstall process |
| `POST /jobs/api/applications/<int:app_id>/ai-research` | integration | anthropic streaming |
| `POST /jobs/api/resumes/<int:resume_id>/reveal` | integration | spawns explorer.exe |
| `POST /mail/api/act` | integration | gmail write |
| `POST /mail/api/brief/sender` | integration | unsub choice runs the gmail unsubscribe |
| `POST /mail/api/decision/<int:item_id>` | integration | gmail action |
| `POST /mail/api/message/<msg_id>/translate` | integration | anthropic translate |
| `POST /mail/api/sync` | integration | gmail sync |
| `POST /mail/api/thread/<thread_id>/act` | integration | gmail write |
| `POST /mail/api/thread/<thread_id>/draft` | integration | anthropic draft |
| `POST /mail/api/thread/<thread_id>/draft/save` | integration | gmail draft save |
| `POST /mail/api/thread/<thread_id>/summary` | integration | anthropic summary |
| `POST /marks/api/mark` | integration | headless browser render and git spawn |
| `POST /purchases/api/orders/scan` | integration | reads gmail order mail |
| `POST /trips/api/prefs/sync` | integration | google forms fetch |
| `POST /trips/api/trips/<int:trip_id>/flights/search` | integration | spawns fare search process |
| `POST /trips/api/trips/<int:trip_id>/geocode` | integration | geocoder lookups |
| `POST /viewer/api/send` | integration | types into a terminal via subprocess |
| `POST /viewer/api/upload` | integration | may spawn RAW preview process |
| `POST /workbench/api/short-titles` | integration | anthropic naming |
| `PUT /api/calendar/events/<event_id>` | integration | google calendar update |
