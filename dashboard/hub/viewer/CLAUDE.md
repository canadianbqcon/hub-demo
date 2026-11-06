# CLAUDE.md — viewer module

Hub module at `/viewer/`. Where Sam sees what Claude shows him (photos at
full resolution with click-to-100% zoom and version flip, RAW previews, video,
web pages, files) and drops files back, on the PC and his phone over Tailscale.
Tier `system`. Spec: `docs/specs/2026-10-26-hub-viewer-page-design.md` (vault);
plan: `docs/plans/2026-10-26-hub-viewer-page.md`.

- **Store (`store.py`):** one folder per item under `data/viewer/` (vault), no
  database. Folder name is the id, `YYYYMMDD-HHMMSS-<6 hex>-<slug>` (`ID_RE`);
  `item.json` holds `{id, kind, title, created, source, files, url, framable,
  preview_status}`, each file `{name, orig, src, label, preview, thumb}`.
  Publish stages into `.staging/<id>/` and lands with one `os.replace`. The feed
  is an in-memory list rebuilt when the folder mtime changes (30 s cap).
  `prune()` deletes items and loose files older than `KEEP_DAYS` (30) and
  staging left over a day; it runs on publish and at most hourly from the feed.
  A folder it cannot date is never touched.
- **Loose files:** anything dropped straight into `data/viewer/` (it is pinned
  to Explorer Quick Access) shows as an upload item in place, never moved; its
  thumbs and previews go in `.previews/`. A loose file ages from when the feed
  or prune first saw it (`.previews/seen.json`, entries `{name: [first_seen,
  "size:mtime_ns"]}`; a different file under the same name starts over), never
  from its mtime: Explorer keeps the mtime on copy and move, so an old photo
  would otherwise be hidden on arrival and deleted on the next prune, his only
  copy if he moved it. A seen.json that exists but cannot be read is never
  overwritten (that would reset every arrival time). A loose file's id and the
  `?v=<size:mtime>` on its URLs change with the file, so a replaced photo shows
  as new. `.previews/<name>.sig` holds the size:mtime its thumb was made from
  (or failed at) and the status, so a file is decoded again only once it
  changes, never on clock comparisons (camera mtimes in the future, WSL drift).
  rawpy missing writes no `.sig` and is retried every rebuild. A passing error
  (`_TRANSIENT` errnos: held open, EIO, disk full, read-only remount; or rawpy's `LibRawIOError`) writes no
  `.sig` and is decoded again at most once per `RETRY_SECS` (60 s on the monotonic clock; rebuilds
  can come every 3 s), never given up on, so a file held for an hour and
  released unchanged still recovers; a file damaged for good costs one decode a
  minute while the Viewer is open. A held thumb, preview or `.previews` write
  is retried the same way. The old `.sig` is removed before every decode (held:
  no decode, retried) so it cannot vouch for a thumb made from another version;
  thumbs are written by temp + rename, so between tries only a whole thumb a try
  of this same version saved shows. The status text is not shown on the page (only "failed" is), so
  it stays one generic string. PIL decode errors carry no errno and are final. On
  publish a passing error sends a RAW to the background child (which reads it
  again and fills in the thumb); another image keeps status `none`. A corrupt
  seen.json is moved to `seen.json.bad.<ns>` (one per corruption) and rebuilt from this
  process's last good times (a process with none, like the CLI, restarts the clocks at
  now, which only deletes later); a loose file that cannot be stat'd during a scan (held)
  keeps its arrival entry rather than losing it, but is left out of the feed
  and never pruned on that entry (it may be an older file's) until it stats; a passing read error keeps
  the last good copy, skips the write, and stops prune deleting any loose file
  on that copy. Arrival times this process gave but could not save (read or
  write failing) are held in `_unsaved` and used wherever seen.json has no
  entry for that file version, so a file keeps one arrival time through the
  outage and after it. Feed and prune go through `_scan()`, which holds
  `_seen_lock` across the folder scan and `_first_seen`; `resolve()` reads
  without the lock, never sets a corrupt copy aside and never writes the cache;
  prune re-stats a loose file before deleting it and skips it if it changed since the scan,
  and drops a deleted file's seen.json entry, so the same file moved back in starts a new 30 days;
  a decode whose `.sig` write is held waits `RETRY_SECS` like any other held write;
  `_tries` is keyed by name (sig inside), like the thumb file it describes, so a newer version's
  try replaces an older one's; prune drops a deleted file's entry; every store write (thumbs, RAW
  previews, item.json, seen.json) goes through `_write_bytes` (encode first, then temp + rename), and a held temp never masks the write's error;
  seen.json is saved only through `_save_seen`; after a set-aside, `_forget` writes the other files' times
  from `_unsaved` so a CLI publish that exits does not lose them; prune also sweeps `.previews` files a day old
  whose loose file left by hand, and dead `.tmp` files (not counted; `seen.json*` never touched);
  an entry whose symlink check fails (held) is kept for `_stats` to mark held; the lock is in-process only, so the CLI's publish
  (another process) can still write seen.json from an older scan, which only
  ever makes an arrival time later, never an early delete. The Viewer iframe's
  `referrerPolicy="no-referrer"` is load-bearing for sw.js (test locks it).
  A seen time before `SEEN_FLOOR` (2026-01-01) or in the future is a bad value
  and restarts that file's clock, so a junk entry can never get a file deleted.
  Feed rebuilds run one at a time under a lock; while any item's preview is
  `making`, the cache is skipped so the finished preview shows on the next poll.
  A `making` with no finished preview for `MAKING_SECS` (10 min) is reported as failed,
  since a preview child killed outright never writes its result. Progress is
  `item.json`'s `progress` (`time.time()` at commit and per finished preview; `created` only
  for items from before it), never a drvfs mtime, which the Windows clock stamps, so a long batch is not cut off.
- **RAW previews:** the RAW's embedded JPEG when its long edge is at least
  `BIG_EDGE` (3000 px), else one detached driver per item (`python -m viewer.store
  --make-previews <dir> <name>...`) runs each RAW in its own `--make-preview <dir> <name>`
  process, in turn (a full demosaic holds ~300 MB; parallel children could OOM WSL on a big
  drop), so a crash or OOM kill costs that one preview and the rest still run. Each process
  gets `MAKING_SECS // 2`, so a hung decode never blocks the rest and start-up fits before the
  feed calls it stuck; a held item.json read raises (only a missing one is "pruned"), so the
  driver sees the failed record; a held `.preview.log` falls back to devnull; one that exits badly after its
  preview was written (record held) gets the preview recorded, not a failure. Driver log and
  child tracebacks go to `<item>/.preview.log`. Updates go to
  `item.json` under an `fcntl` lock on `<item>/.item.lock`. An embedded JPEG with no
  Orientation tag (or tag 0 or 1) is turned by LibRaw's `sizes.flip` (3 = 180, 5 = ROTATE_90, 6 = ROTATE_270,
  checked against postprocess on portrait ARWs; Sony's JPEGs carry the tag). `rawpy` missing shows
  as a failed status, not a crash.
- **Thumbs:** 320 px JPEG; a picture with transparency sits on a grey checkerboard, an
  image taller than 3x its width shows its top 3:4, one wider than 4x its height its middle 4:3.
- **Paths shown:** feed files carry `src` (original path, `C:\` form, null for
  uploads) and `path` (stored location, `C:\` form) for the details panel.
- **CLI (`cli.py`):** how Claude shows something. `show <path>... [--title T]
  [--label L ...]` (several images = versions of one photo), `show --url URL`
  (probes `X-Frame-Options` / CSP `frame-ancestors` within 5 s and stores
  `framable` true/false/null; the page offers "open in new tab" when not
  framable), `uploads [--since ISO]` (what he dropped in, absolute paths). `show`
  prints the `http://localhost:5002/viewer/?item=<id>` link as its last line.
  Runs as a script from any directory. Delivery rule: vault
  `CLAUDE-file-delivery.md` → "Viewer".
- **Routes (`api.py`):** `/viewer/` page, `/viewer/api/feed` (the app-wide
  after_request hook ETags it, so an unchanged feed is a 304),
  `/viewer/file/<id>/<name>` (`<id>` is `loose` for loose files),
  `POST /viewer/api/upload` (multipart field `files`), `GET /viewer/api/terminals`,
  `POST /viewer/api/send`.
- **File serving is hardened:** `store.resolve()` only returns a name listed in
  that item's `item.json` (or a loose file and its previews), inside the
  retention window, not a symlink, resolved under `data/viewer/`. Responses carry
  `X-Content-Type-Options: nosniff` and `Content-Security-Policy: sandbox`
  (except PDFs: Chrome will not open its PDF viewer in a sandboxed document);
  only the `INLINE` types (common images, mp4/webm/mov, PDF) render, everything
  else (HTML, SVG, RAW) downloads. Upload names lose leading dots, and ones that
  collide with what the store writes itself (`item.json`, `*.thumb.jpg`,
  `*.preview.jpg`, case-blind) get a `-N` suffix; the store's temp files are
  hidden and unique (`.<name>.<pid>.<hex>.tmp`) and removed if the write fails.
  The web frame is sandboxed without `allow-top-navigation`, so a framed site
  cannot redirect the Hub tab, nor `allow-modals` (a looping alert would lock
  it). A Hub URL is never framed (same-origin with scripts it could lift its
  sandbox; without, its API calls fail): it shows "open in its own tab". The
  iframe is keyed by URL. A foreign framed page that redirects or navigates to
  the Hub is refused app-wide by `app.py` `_refuse_cross_site_framing` (403 on
  `Sec-Fetch-Dest` iframe/frame/object/embed with `Sec-Fetch-Site`
  cross-site/same-site), and `static/js/sw.js` answers a frame load not started
  by a Hub page (referrer not on the Hub origin) from the network only, so a
  cached page cannot skip that check; Hub-started frames keep the offline
  fallback. `sameHub` counts localhost, 127.0.0.1 and ::1 on the Hub's scheme
  and port as the Hub; any other alias (tailnet name, LAN IP) is framed and
  gets the 403, whose text reads "Hub pages open in their own tab."
- **Upload limits:** same-site callers only (`marks.api._same_site`), 2 GiB per
  request, 50 files per drop, refused when under 2 GiB free. Title is the first
  file's name, `name +N more` for several.
- **Paste:** Ctrl+V anywhere on the page (not in a text field) sends the
  clipboard's files through the same upload: Explorer-copied files keep their
  names, a screenshot's bare `image.png` becomes `paste-YYYYMMDD-HHMMSS.png`.
  The Paste button uses `navigator.clipboard.read()`, which gives images only
  and needs a secure context (localhost); elsewhere it says to press Ctrl+V.
- **Send to Claude (`terminals.py`):** the item line's "send to Claude" menu
  lists live interactive Claude sessions in herdr tabs, newest first, as
  `<tab label> · <topic> · <idle|busy>` (`claude agents --json`; pane and tab
  from the process's `HERDR_PANE_ID`/`HERDR_TAB_ID` in `/proc/<pid>/environ`;
  label from `herdr tab list`; topic from `~/.claude/terminal-title-state/`).
  Picking one (`POST /viewer/api/send {item, pane}`, same-site only) types
  `Look at what I sent you from the Hub Viewer (<title>): "<path>" ...` (a web
  item sends its URL) into that pane with `herdr pane run`, so an idle session
  starts on it and a busy one queues it. The pane must be in the live list at
  send time (409 otherwise) and control characters are stripped so Enter comes
  once. Nothing is auto-claimed: an upload reaches a session only when he picks
  one (his 2026-10-27 pick, so a handoff or scheduled prompt cannot take it).
  Claude's peer socket (`messagingSocketPath`) is not used: its format is
  internal. Sessions outside herdr do not appear. `GET /viewer/api/terminals`
  answers 502 when either CLI fails.
- **Frontend:** `frontend/viewer.html` + `frontend/static/viewer.jsx` /
  `viewer.css`, on the tabbed 3-pane origin. The Workbench pick is "Contact sheet
  with kind filters" (build from that title, not its card letter). Phone layout
  below 900 px (the origin's own breakpoint). Full-screen overlay: click to 100%
  on the clicked spot, flip between versions at the same zoom. New items arrive
  by polling the feed. `viewer.css` is listed in `blueprints.json`
  `baselines.page_css_files`.
- **Wiring in `app.py`:** `from viewer import api as viewer_api`;
  `app.register_blueprint(viewer_api.bp)` (Blueprint carries
  `static_folder="frontend/static"`). No `init()`; vault path comes from
  `vault_path.vault_root()`. Tile in `hub_modules.py`.
- **Not synced:** `data/viewer/` is gitignored in the vault, so items stay on
  the machine they were shown or dropped on.
- **Tests:** `tests/test_viewer_store.py`, `test_viewer_cli.py`,
  `test_viewer_api.py`; `tests/viewer_ui_check.py` drives the live page
  headless (zoom, flip, video, web fallback, upload, live arrival).
- **Design:** inherits the Hub token system (base.css + themes), no bespoke
  palette.
