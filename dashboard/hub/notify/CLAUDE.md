# CLAUDE.md — dashboard/hub/notify/ (Hub notifications)

Scoped rules for the notifications module (the bell in the top bar). Cross-module rules are in `dashboard/CLAUDE.md`, which loads too. Design: `docs/specs/2026-11-10-hub-notifications-design.md` in the vault.

Store: `data/notify.db`, gitignored, one per machine, one STRICT table `notification`, schema from `db/migrations/notify/` (self-migrating: a new migration applies on the next connect), rebuilt on connect when missing. Importing needs `dashboard/` on the path (`PYTHONPATH=..` from `hub/`): `from notify import post, cancel`.

## The post call [BINDING]

Signatures are frozen:

```python
post(source, title, body=None, url=None, push=False, due_at=None, key=None, *, conn=None) -> int
cancel(key, *, conn=None) -> bool
```

- `source` and `title` are required. Title is cut at 200 characters, body at 2000.
- `url` is a Hub path (`/gaming/clash`) or an `https://` link with a host. `//x`, `/\x`, whitespace and control characters raise `ValueError`.
- `due_at` must be timezone-aware (datetime, or ISO string with an offset). Naive or malformed raises `ValueError`. It is stored as UTC `YYYY-MM-DDTHH:MM:SSZ`. None means now. A row shows in the bell and is pushed only once due.
- `push=True` marks the row for an ntfy push. `post` returns the row id. `conn` is for tests; omit it in callers.
- `cancel(key)` deletes the row only while it is not yet due and returns whether it did. A due row stays.

Key table (`key` names one occurrence; namespace it by module, `clash:...`):

| call on an existing key | effect |
|---|---|
| `due_at=None` | keeps the stored `due_at` |
| same fields | nothing changes |
| `due_at` moved under 5 minutes | counts as unchanged |
| `due_at` moved 5 minutes or more, row not yet due | updated in place, set unread, push back to `pending` if `push` |
| `due_at` moved, row already due | keeps its time (that occurrence fired) |
| only wording changed | text updated; read and push state untouched, so a sent push never re-sends |
| `push` on with state `none` | set `pending` |
| `push` off with state `pending` | set `none` |

## Sources: rows for what waits on him [BINDING]

`notify/sources.py` posts rows for things waiting on Sam elsewhere in the Hub, and removes them once he deals with them where they live. A module with "something is waiting on you" state adds a source there rather than calling `post` from its own write paths.

- Each source returns `{key: post() kwargs}` for what waits right now. Keys start with `<source>:`, and the source name is the Hub module whose icon the row shows. `reconcile()` runs at the start of every `notify-push` tick and hands each result to `db.sync()`.
- `db.sync()` adds new keys, updates changed wording, and hard-deletes keys that are no longer waiting, tombstone included, so the same key waiting again later shows as new.
- A source that raises (store missing, locked, a bad read) is logged and skipped for that tick. It is never synced as empty, which would wipe its rows.
- The sources today:
  - `mail`: inbox and unread, not Promotions or Social, arrived after `MAIL_SINCE` and within the last 3 days.
  - `automations`: one row counting proposed rules, keyed by the newest id so a new proposal rings again. Links to `/automations/?tab=rules`.
  - `trips`: pending code requests and pending trip submissions.
  - `jobs`: fit over 7.5 (`fit_score` > 75), not applied, cut, ignored or rejected, created in the last 30 days.
  - `workbench`: a port of the Workbench inbox (`workbench-docs.jsx` `inboxRows`): each build's first unapproved step that waits on him, plus marks sessions with fixes to check. Change both together.

Delete: `POST /notify/api/delete` takes `{"ids": [...]}` and answers with the list, with no confirm. It tombstones the row (`deleted_at`, read set, a pending push skipped), so a source still reporting the key does not bring it back. Every list query skips tombstones.

## No network in post [BINDING]

`post` only writes the store. Pushes go out from the `notify-push` trigger job (`scheduler.py` `_run_notify_push`, every 30 s tick, only on the `active_machine`, a non-blocking flock skips an overlapping tick):

- A row is claimed (`pending` to `sending`, committed) before the send and never resent; a raise marks it `failed`, never retried. A `sending` row older than 5 minutes turns `failed`.
- A pending row more than 6 hours past due is `skipped` (it still shows in the bell).
- The sweep pushes nothing unless `~/.config/vault-api/ntfy_topic` exists, is readable and non-empty, since `news.alerts._post` would otherwise mint a topic the phone does not follow; the 30-day prune runs either way. Logs name the row id, never the request URL (it holds the topic).
- A relative `url` gets the Hub tailnet base before sending. Read rows older than 30 days are deleted in the same run.

## Fail open [BINDING]

- `post` and `cancel` raise `sqlite3.Error` when the store is locked or broken. Callers must treat that as non-fatal (wrap the call); a missed post is not recovered, so repost from your own state on the next run.
- The top bar renders on every page, so a store failure must not break it. `GET /notify/api/list` answers 503 when the store fails; the bell keeps its last good count and the pane says `unavailable`. `POST /notify/api/read` takes `{"ids": [n, ...]}` (due rows only), answers with the fresh list, and 400 otherwise. There is no mark-everything call: "mark all read" sends the ids the pane showed, so a row that came due after the last refresh stays unread. An unread row with a url links to `GET /notify/go/<id>`, which marks it read and redirects (to Home when the store fails), so every way of opening it marks it first.
- Routes sit behind the Hub sign-in gate; nothing here is on the public list, and the bell does not render when `window.MODULES` is empty (public trips mirror, login page).

Tests: `dashboard/hub/tests/test_notify.py`.
