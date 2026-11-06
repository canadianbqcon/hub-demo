# Hub demo

A working copy of a personal dashboard (the Hub), running on one made-up person's month of data.
Built by Brendan Quan, mostly by directing Claude Code: specs, plans, sign-offs and the code itself.

Start at **/guide** on the live site: a ten-minute tour of the pages worth seeing, what each one
does, and where AI does the work in the real Hub.

## What you are looking at

- **Python and Flask**, one blueprint per page under `dashboard/hub/<module>/`.
- **One SQLite database per module**, built from the migrations in `db/migrations/<module>/`.
- **React pages with no build step**: each `.jsx` file is transpiled once by `node` with a vendored
  Babel (`dashboard/hub/jsx_build.py`) and cached.
- **Fake data**: `seed/` writes the persona's month into `demo-vault/pristine/`. Every date in it is
  stored as an offset (`@d-3`), so the month always ends today.

## What is switched off

The real Hub calls Claude, Google Calendar and Gmail, a bank feed and a few public APIs. Here those
routes answer with a short note instead, and the process cannot open an outside connection at all.
`DEMO-SECURITY.md` explains the guard and lists every switched-off route.

Visitors share one copy of the data and can add, edit and tick things. It all resets at 00:00 UTC.

## Run it yourself

Needs Python 3.14 and `node` on the PATH.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.lock
cd dashboard/hub
DEMO_MODE=1 VAULT_PATH="$PWD/../../demo-vault" ../../.venv/bin/gunicorn -w 1 --threads 8 -b 127.0.0.1:5099 app:app
```

Then open http://127.0.0.1:5099/guide/. Or build the `Dockerfile`, which runs the same command.

Tests for the demo layer: `DEMO_MODE=1 VAULT_PATH="$PWD/demo-vault" python3 -m pytest tests/demo -q`. The seeder tests run without the demo layer: `python3 -m pytest tests/demo/test_seed.py -q`.
from the repo root.

## How this copy was made

An export script in the private repo copies the tracked code, swaps personal names for fake ones,
adds the demo layer, the Guide and the seeders, builds every database and seeds it, then scans
the result for names, emails, paths and keys and refuses to write it if anything turns up.
