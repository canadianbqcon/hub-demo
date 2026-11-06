# CLAUDE-first-run.md — dashboard/ first-run setup

Extracted from `dashboard/CLAUDE.md` on 2026-09-05 when adding the three-pane
layout law pushed that file past the 250-line ceiling. Reference material for
one task (standing a machine up), not a rule every session needs in context.

## First-run setup on a new machine

Three files are gitignored and must be created manually on each machine. If the connector dots in the Hub status strip are grey, this is why.

**`dashboard/credentials.json`** — Google OAuth client secret. One-time download, shared by all Google connectors.
1. console.cloud.google.com → project "Vesper Dashboard" (or create new) → APIs & Services
2. Enable: Google Calendar API, Gmail API, Google Drive API, Google Docs API, Google Sheets API
3. Credentials → OAuth 2.0 Client ID (Web application) → add redirect URIs:
   - `http://localhost:5002/api/calendar/callback`
   - `http://localhost:5002/api/gmail/callback`
   - `http://localhost:5002/api/drive/callback`
   - `http://localhost:5002/api/docs/callback`
   - `http://localhost:5002/api/sheets/callback`
4. Download JSON → rename to `credentials.json` → place in `dashboard/`

**Token files** — generated automatically by running each auth flow once (port 5002 must be running):

| Auth URL | Token file created | Scope |
|---|---|---|
| `http://localhost:5002/api/calendar/auth` | `token.json` | Google Calendar (read/write) |
| `http://localhost:5002/api/gmail/auth` | `gmail_token.json` | Gmail (modify) |
| `http://localhost:5002/api/drive/auth` | `drive_token.json` | Google Drive (full) |
| `http://localhost:5002/api/docs/auth` | `docs_token.json` | Google Docs (read/write) |
| `http://localhost:5002/api/sheets/auth` | `sheets_token.json` | Google Sheets (read/write) |

All OAuth round-trips through Hub (5002) — the only registered redirect URIs are 5002. (Swapped 2026-06-08; the legacy 5001 auth routes were deleted with `api.py` when the 5001 hub was retired 2026-06-17 — see [[wiki/decisions/retire-5001-hub]].)

**Python modules** — each service has a dedicated module in `dashboard/`:

| Module | Service | Key functions |
|---|---|---|
| `gcal.py` | Google Calendar | `fetch_events`, `fetch_events_window`, `create_event`, `update_event`, `patch_event`, `delete_event`, `push_trip`, `push_activity` |
| `gmail.py` | Gmail | auth + OAuth helpers (skill drives all reads/writes via Bash) |
| `gdrive.py` | Google Drive | `list_files`, `search_files`, `read_file`, `create_file`, `update_file`, `copy_file`, `delete_file`, `move_file` |
| `gdocs.py` | Google Docs | `read_doc`, `create_doc`, `append_text`, `insert_text`, `replace_text`, `overwrite_document`, `batch_update` |
| `gsheets.py` | Google Sheets | `read_range`, `read_sheet`, `write_range`, `append_rows`, `clear_range`, `create_spreadsheet`, `add_sheet`, `delete_rows` |

Note: Google Docs and Sheets content editing uses `gdocs.py`/`gsheets.py` directly via their respective APIs. `gdrive.py` handles file management (listing, searching, moving, permissions) and can read exported content, but does not write into existing Docs/Sheets content — use the dedicated modules for that.

**`dashboard/.env`** — copy from `dashboard/.env.example` and fill in values:
- `YNAB_TOKEN` — from ynab.com → Profile → Developer Settings → New Token
