"""music.db data layer: Spotify export load, refresh diff, change log, queries.

Run from dashboard/hub:
    python3 -m music.library load-export <dir> [--ignore-from <zip>]
    python3 -m music.library changes [--since YYYY-MM-DD]
    python3 -m music.library history <song>
    python3 -m music.library progress
    python3 -m music.library check <placements.json>
    python3 -m music.library set-group <playlist> <group>
    python3 -m music.library sort-playlists <sorts dir> [--create]
    python3 -m music.library login
    python3 -m music.library pull
"""

import argparse
import csv
import json
import re
import sqlite3
import unicodedata
import sys
import zipfile
from contextlib import contextmanager
from pathlib import Path

_DASH = Path(__file__).resolve().parent.parent.parent
if str(_DASH) not in sys.path:
    sys.path.insert(0, str(_DASH))  # dashboard/, for vault_path

DB_PATH = None  # set by init(); default resolved lazily to <vault>/data/music.db
# What the groups mean to Sam (2026-09-28):
#   Old Genres  - legacy genre lists, no longer updated.
#   New Genres  - the permanent genre buckets every song is being sorted into; still growing.
#   Temp Genres - "purgatory": the old auto-sort's rough genre lists ("2 ..." names), emptied by hand.
#   playlists   - vibe playlists with their own names, not genres.
#   root        - Liked Songs and a few general lists.
GENRE_GROUPS = ("New Genres", "Old Genres", "Temp Genres")
GROUPS = GENRE_GROUPS + ("playlists", "root")

# A new playlist is filed by its name: genre lists are named after a genre, vibe lists get
# a unique name. ponytail: word list, not a classifier; a miss is fixed with `set-group`.
_GENRE_WORDS = set("""
pop rap rock house trap techno trance dubstep bass drill r&b rnb hip-hop hiphop edm metal punk
indie garage disco funk soul jazz blues folk country reggaeton reggae latin synthwave synthpop
hyperpop electropop indietronica psytrance hardstyle riddim dnb drum lo-fi lofi ambient orchestral
classical acoustic instrumental electro electronic emo grunge britpop chillstep chillwave dancehall
afrobeats amapiano phonk breakbeat dub ska gospel idm progressive dance k-pop k-rap k-r&b k-rock
j-pop j-rock alt-r&b neo-soul club jersey grime shoegaze experimental melodic
""".split())
_GENRE_ENDINGS = ("pop", "core", "step", "wave", "hop", "house")


def group_for_name(name):
    """Group for a playlist first seen by the pull, judged from its name alone."""
    if re.match(r"2[ _]", name):
        return "Temp Genres"
    for w in re.split(r"[\s/,()]+", name.lower()):
        if w in _GENRE_WORDS or w.endswith(_GENRE_ENDINGS):
            return "New Genres"
    return "playlists"


# tracks column -> Exportify header
_CSV_COLS = {
    "uri": "Track URI", "isrc": "ISRC", "name": "Track Name", "album": "Album Name",
    "artists": "Artist Name(s)", "release_date": "Release Date", "duration_ms": "Duration (ms)",
    "explicit": "Explicit", "danceability": "Danceability", "energy": "Energy", "key": "Key",
    "loudness": "Loudness", "mode": "Mode", "speechiness": "Speechiness",
    "acousticness": "Acousticness", "instrumentalness": "Instrumentalness",
    "liveness": "Liveness", "valence": "Valence", "tempo": "Tempo", "time_signature": "Time Signature",
}
_INT = {"duration_ms", "key", "mode", "time_signature"}
_REAL = {"danceability", "energy", "loudness", "speechiness", "acousticness",
         "instrumentalness", "liveness", "valence", "tempo"}
_TRACK_COLS = [c for c in _CSV_COLS if c != "uri"] + ["is_local"]


def init(db_path=None):
    """Point the module at a db (default <vault>/data/music.db). Schema comes from db/migrate.py."""
    global DB_PATH
    if db_path is None:
        from vault_path import vault_root
        db_path = vault_root() / "data" / "music.db"
    DB_PATH = Path(db_path)


@contextmanager
def _tx():
    if DB_PATH is None:
        init()
    con = sqlite3.connect(DB_PATH)  # pyright: ignore[reportArgumentType]  init() sets DB_PATH / ref is members or settled, one is not None
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except BaseException:
        con.rollback()
        raise
    finally:
        con.close()


# ---- export parsing ----------------------------------------------------------

def _num(col, v):
    v = (v or "").strip()
    if v == "":
        return None
    if col == "explicit":
        return 1 if v.lower() == "true" else 0
    try:
        return int(float(v)) if col in _INT else float(v) if col in _REAL else v
    except ValueError:
        return None


def _read_csv(path):
    """-> (ordered unique uris, {uri: track dict})."""
    uris, tracks = [], {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            uri = (row.get("Track URI") or "").strip()
            if not uri:
                continue
            if uri not in tracks:
                uris.append(uri)
                t = {c: _num(c, row.get(h)) for c, h in _CSV_COLS.items() if c != "uri"}
                t["name"] = t["name"] or ""
                t["is_local"] = 1 if uri.startswith("spotify:local:") else 0
                tracks[uri] = t
    return uris, tracks


def _export_files(export_dir):
    """Yield (grp, csv path): subfolder name, or 'root' for top-level files."""
    root = Path(export_dir)
    for p in sorted(root.rglob("*.csv")):
        rel = p.relative_to(root)
        yield (rel.parts[0] if len(rel.parts) > 1 else "root"), p


# ---- core diff ---------------------------------------------------------------

def _apply(con, snapshot, tracks, source):
    """Diff snapshot against playlist_tracks and write everything; caller owns the transaction."""
    have = {r[0] for r in con.execute("SELECT uri FROM tracks")}
    for pid, uris in snapshot.items():
        missing = set(uris) - have - set(tracks)
        if missing:
            raise ValueError(f"playlist {pid}: {len(missing)} uris have no track data, e.g. {sorted(missing)[0]}")
    cols = ", ".join(["uri"] + _TRACK_COLS)
    marks = ", ".join("?" * (len(_TRACK_COLS) + 1))
    # COALESCE keeps export-only audio features when a pull row carries NULLs
    upd = ", ".join(f"{c}=COALESCE(NULLIF(excluded.{c}, ''), tracks.{c})" if c == "name"
                    else f"{c}=COALESCE(excluded.{c}, tracks.{c})" for c in _TRACK_COLS)
    for uri, t in tracks.items():
        t = dict(t)
        t.setdefault("is_local", 1 if uri.startswith("spotify:local:") else 0)
        t["name"] = t.get("name") or ""
        con.execute(f"INSERT INTO tracks ({cols}) VALUES ({marks}) "  # noqa: S608  identifiers from fixed whitelist/placeholders, values bound
                    f"ON CONFLICT(uri) DO UPDATE SET {upd}, updated=datetime('now')",
                    [uri] + [t.get(c) for c in _TRACK_COLS])
    rid = con.execute("INSERT INTO refreshes (source) VALUES (?)", (source,)).lastrowid
    n_add = n_rem = 0
    for pid, new in snapshot.items():
        old = {r[0] for r in con.execute("SELECT track_uri FROM playlist_tracks WHERE playlist_id=?", (pid,))}
        new = set(new)
        for kind, uris in (("added", new - old), ("removed", old - new)):
            for u in sorted(uris):
                con.execute("INSERT INTO changes (refresh_id, playlist_id, track_uri, kind) VALUES (?,?,?,?)",
                            (rid, pid, u, kind))
                if kind == "added":
                    con.execute("INSERT INTO playlist_tracks VALUES (?,?)", (pid, u))
                else:
                    con.execute("DELETE FROM playlist_tracks WHERE playlist_id=? AND track_uri=?", (pid, u))
        n_add += len(new - old)
        n_rem += len(old - new)
        con.execute("UPDATE playlists SET last_seen=datetime('now'), updated=datetime('now') WHERE id=?", (pid,))
    summary = f"{len(snapshot)} playlists, +{n_add} -{n_rem}"
    con.execute("UPDATE refreshes SET summary=? WHERE id=?", (summary, rid))
    return {"refresh_id": rid, "playlists": len(snapshot), "added": n_add, "removed": n_rem}


def apply(snapshot, tracks, source="pull", failed=False):
    """snapshot {playlist_id: set(uri)} must be complete for every playlist it names."""
    if failed:
        raise RuntimeError("refresh failed upstream; nothing written")
    with _tx() as con:
        return _apply(con, snapshot, tracks, source)


def mark_gone(playlist_ids):
    with _tx() as con:
        con.executemany("UPDATE playlists SET status='gone', updated=datetime('now') WHERE id=?",
                        [(i,) for i in playlist_ids])


_FEATURES = ("danceability", "energy", "key", "loudness", "mode", "speechiness", "acousticness",
             "instrumentalness", "liveness", "valence", "tempo", "time_signature")


def _conflicts(per_file):
    """uris whose audio features differ between export files. Exportify (2026-09-28) attached
    another song's features to about 44% of rows, shifted by whole batches; only a value every
    file agrees on is kept (Sam, 2026-10-28)."""
    seen = {}
    for t in per_file:
        for uri, row in t.items():
            f = tuple(row.get(c) for c in _FEATURES)
            if any(v is not None for v in f):
                seen.setdefault(uri, set()).add(f)
    return {u for u, fs in seen.items() if len(fs) > 1}


def _scrub(con, uris):
    sets = ", ".join(f"{c}=NULL" for c in _FEATURES)
    con.executemany(f"UPDATE tracks SET {sets}, updated=datetime('now') WHERE uri=?",  # noqa: S608  fixed column names
                    [(u,) for u in sorted(uris)])


def scrub_features(export_dir):
    """Clear audio features the export files disagree on. Returns how many songs were cleared."""
    bad = _conflicts(_read_csv(p)[1] for _, p in _export_files(export_dir))
    with _tx() as con:
        _scrub(con, bad)
    return len(bad)


def load_export(export_dir, ignore_zip=None):
    snapshot, tracks, seen_names, per_file = {}, {}, set(), []
    with _tx() as con:
        for grp, path in _export_files(export_dir):
            seen_names.add(path.name)
            uris, t = _read_csv(path)
            per_file.append(t)
            tracks.update(t)
            row = con.execute("SELECT id FROM playlists WHERE file_name=? AND grp=?", (path.name, grp)).fetchone()
            if row:
                pid = row[0]
            else:
                sid = "liked" if path.name == "Liked_Songs.csv" and grp == "root" else None
                pid = con.execute("INSERT INTO playlists (name, file_name, grp, spotify_id) VALUES (?,?,?,?)",
                                  (path.stem, path.name, grp, sid)).lastrowid
            snapshot[pid] = set(uris)
        ignored = 0
        if ignore_zip:
            with zipfile.ZipFile(ignore_zip) as zf:
                names = {Path(n).name for n in zf.namelist() if n.lower().endswith(".csv")}
            for n in sorted(names - seen_names):
                if not con.execute("SELECT 1 FROM playlists WHERE file_name=? AND status='ignored'", (n,)).fetchone():
                    con.execute("INSERT INTO playlists (name, file_name, status) VALUES (?,?, 'ignored')",
                                (Path(n).stem, n))
                    ignored += 1
        res = _apply(con, snapshot, tracks, "export")
        bad = _conflicts(per_file)
        _scrub(con, bad)  # after _apply: its COALESCE would otherwise keep an older value
    res["ignored_added"] = ignored
    res["features_cleared"] = len(bad)
    return res


# ---- change report -----------------------------------------------------------

def _label(r):
    return f"{r['artists'] or '?'} - {r['name']}"


def changes(since=None):
    """Per playlist {playlist, group, added, removed, moved}, oldest refresh first.

    moved = removed from this playlist and added to another anywhere in the window, so a song
    taken out of a Temp list on Monday and put in a New Genre on Wednesday is one move. It is
    listed once, on the source playlist ({song, to: [names]}), and left out of both added/removed.
    """
    out = {}
    with _tx() as con:
        where, args = ("WHERE r.taken_at >= ?", [since]) if since else ("", [])
        rows = con.execute(
            "SELECT c.refresh_id rid, c.playlist_id pid, p.name pname, p.grp, c.kind, t.uri, t.name, t.artists "  # noqa: S608  identifiers from fixed whitelist/placeholders, values bound
            "FROM changes c JOIN refreshes r ON r.id=c.refresh_id JOIN playlists p ON p.id=c.playlist_id "
            f"JOIN tracks t ON t.uri=c.track_uri {where} ORDER BY c.refresh_id, p.id, t.uri", args).fetchall()
        seed = con.execute("SELECT min(id) FROM refreshes").fetchone()[0]
    # The first refresh is the initial load: songs already there, never a move's destination.
    added_to = {}
    for r in rows:
        if r["kind"] == "added" and r["rid"] != seed:
            added_to.setdefault(r["uri"], []).append(r)
    # removed from one playlist, added to a different one: (uri, source pid) -> destinations
    moves = {}
    for r in rows:
        if r["kind"] == "removed":
            to = [a for a in added_to.get(r["uri"], []) if a["pid"] != r["pid"]]
            if to:
                moves[(r["uri"], r["pid"])] = to
    move_dest = {(a["uri"], a["pid"]) for to in moves.values() for a in to}
    for r in rows:
        e = out.setdefault(r["pid"], {"playlist": r["pname"], "group": r["grp"],
                                      "added": [], "removed": [], "moved": []})
        if (r["uri"], r["pid"]) in moves and r["kind"] == "removed":
            e["moved"].append({"song": _label(r), "to": [a["pname"] for a in moves[(r["uri"], r["pid"])]]})
        elif not ((r["uri"], r["pid"]) in move_dest and r["kind"] == "added"):
            e[r["kind"]].append(_label(r))
    return list(out.values())


# ---- queries -----------------------------------------------------------------

def _track(r):
    return {"uri": r["uri"], "name": r["name"], "artists": r["artists"]}


def _pl(r):
    return {"playlist": r["pname"], "group": r["grp"], "status": r["status"],
            "unlinked": r["status"] == "unlinked"}


def playlist_songs(name_or_file, grp=None):
    """One result per matching playlist (same name in two groups gives two)."""
    with _tx() as con:
        pls = con.execute(
            "SELECT id, name pname, grp, status FROM playlists "
            "WHERE (name=? OR file_name=? OR file_name=?) AND (? IS NULL OR grp=?) ORDER BY grp, id",
            (name_or_file, name_or_file, name_or_file + ".csv", grp, grp)).fetchall()
        out = []
        for p in pls:
            songs = con.execute("SELECT t.uri, t.name, t.artists FROM playlist_tracks pt "
                                "JOIN tracks t ON t.uri=pt.track_uri WHERE pt.playlist_id=? ORDER BY t.name, t.uri",
                                (p["id"],)).fetchall()
            out.append({**_pl(p), "songs": [_track(s) for s in songs]})
        return out


def _with_playlists(con, tracks):
    out = []
    for t in tracks:
        pls = con.execute("SELECT p.name pname, p.grp, p.status FROM playlist_tracks pt "
                          "JOIN playlists p ON p.id=pt.playlist_id WHERE pt.track_uri=? ORDER BY p.grp, p.name",
                          (t["uri"],)).fetchall()
        out.append({**_track(t), "playlists": [_pl(p) for p in pls]})
    return out


def song_playlists(query):
    """Songs matching uri or a name/artist substring, each with the playlists holding it."""
    like = f"%{query}%"
    with _tx() as con:
        ts = con.execute("SELECT uri, name, artists FROM tracks WHERE uri=? OR name LIKE ? OR artists LIKE ? "
                         "ORDER BY name, uri", (query, like, like)).fetchall()
        return _with_playlists(con, ts)


def ungrouped_songs():
    """Songs held by no New/Old/Temp Genres playlist."""
    ph = ",".join("?" * len(GENRE_GROUPS))
    with _tx() as con:
        ts = con.execute(
            "SELECT uri, name, artists FROM tracks WHERE uri NOT IN ("  # noqa: S608  identifiers from fixed whitelist/placeholders, values bound
            "SELECT pt.track_uri FROM playlist_tracks pt JOIN playlists p ON p.id=pt.playlist_id "
            f"WHERE p.grp IN ({ph})) ORDER BY name, uri", GENRE_GROUPS).fetchall()
        return _with_playlists(con, ts)


def song_history(query):
    """Every change for songs matching uri or a name/artist substring, oldest first."""
    like = f"%{query}%"
    with _tx() as con:
        ts = con.execute("SELECT uri, name, artists FROM tracks WHERE uri=? OR name LIKE ? OR artists LIKE ? "
                         "ORDER BY name, uri", (query, like, like)).fetchall()
        out = []
        for t in ts:
            ev = con.execute("SELECT r.taken_at, r.source, c.kind, p.name pname, p.grp FROM changes c "
                             "JOIN refreshes r ON r.id=c.refresh_id JOIN playlists p ON p.id=c.playlist_id "
                             "WHERE c.track_uri=? ORDER BY r.id, c.kind DESC, p.name", (t["uri"],)).fetchall()
            out.append({**_track(t), "events": [
                {"when": e["taken_at"], "source": e["source"], "kind": e["kind"],
                 "playlist": e["pname"], "group": e["grp"]} for e in ev]})
        return out


def sorting_progress():
    """How far the sort into New Genres has got.

    unsorted: songs in no New Genres list. temp: per Temp list, its songs, how many already
    have a New Genres home (safe to clear from Temp) and how many are left.
    """
    with _tx() as con:
        homed = ("SELECT pt.track_uri FROM playlist_tracks pt JOIN playlists p ON p.id=pt.playlist_id "
                 "WHERE p.grp='New Genres' AND p.status!='gone'")
        unsorted = con.execute(f"SELECT count(*) FROM tracks WHERE uri NOT IN ({homed})").fetchone()[0]  # noqa: S608  identifiers from fixed whitelist/placeholders, values bound
        temp = con.execute(
            f"SELECT p.name, count(*) songs, sum(pt.track_uri IN ({homed})) homed FROM playlists p "  # noqa: S608  identifiers from fixed whitelist/placeholders, values bound
            "JOIN playlist_tracks pt ON pt.playlist_id=p.id WHERE p.grp='Temp Genres' AND p.status!='gone' "
            "GROUP BY p.id ORDER BY songs - homed DESC, p.name").fetchall()
    return {"unsorted": unsorted,
            "temp": [{"playlist": n, "songs": s, "homed": h, "left": s - h} for n, s, h in temp]}


# Placement check: a proposed sort is tested against the numbers before Sam sees it, so a
# placement made on artist memory against the song's own numbers gets caught (Hunter, 2026-09-28).
_CHECK_METRICS = ("tempo", "energy", "danceability")
# Slack past the fences: Spotify's tempo sits a few BPM off and a tight list (Club Pop is 124-128
# at the middle) would otherwise flag a 120 or a 133.
_PAD = {"tempo": 8, "energy": .05, "danceability": .05}


def _fold_tempo(t):
    # Spotify reads half/double time; fold into one octave so 64 and 128 compare as the same pulse.
    if t <= 0:
        raise ValueError(f"tempo {t} has no pulse to fold")  # doubling 0 never reaches 80
    while t < 80:
        t *= 2
    while t >= 160:
        t /= 2
    return t


def _fences(vals):
    import statistics
    q1, _, q3 = statistics.quantiles(vals, n=4)
    return q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)


def flag_outliers(proposed, reference, min_ref=5):
    """proposed: {key: {metric: value or None}}; reference: list of the same dicts (the list's
    current members plus the proposed ones). Returns {key: [reason, ...]} for flagged songs only.
    ponytail: Tukey fences per metric; a list with few numbered songs can't flag, it says so."""
    out = {}
    for k, m in proposed.items():
        if all(m.get(x) is None for x in _CHECK_METRICS):
            out[k] = ["no numbers: needs a lookup or a listen"]
            continue
        if sum(r.get("energy") is not None for r in reference) < min_ref:
            out[k] = ["list has too few numbered songs to judge"]
            continue
        why = []
        for x in _CHECK_METRICS:
            # the song itself is left out, or an outlier widens its own fences
            ref = [r[x] for r in reference if r is not m and r.get(x) is not None]
            if m.get(x) is None:
                continue
            f = _fold_tempo if x == "tempo" else (lambda v: v)
            lo, hi = _fences([f(v) for v in ref])
            lo, hi = lo - _PAD[x], hi + _PAD[x]
            v = f(m[x])
            if not lo <= v <= hi:
                why.append(f"{x} {round(m[x], 2)} outside the list's {round(lo, 2)}-{round(hi, 2)}")
        if why:
            out[k] = why
    return out


def check_sort(placements):
    """placements: {playlist name: [track uri, ...]} for a proposed sort into New Genres lists
    (a list that does not exist yet is judged on the proposed songs alone).
    Returns {playlist: {"Title - Artist": [reasons]}} for every flagged song."""
    # Spotify stores 0.0 when it has no tempo reading; treat it as missing, like NULL
    cols = ", ".join("NULLIF(tempo, 0) AS tempo" if x == "tempo" else x for x in _CHECK_METRICS)
    res = {}
    with _tx() as con:
        for pl, uris in placements.items():
            members = con.execute(
                f"SELECT t.uri, {cols} FROM tracks t JOIN playlist_tracks pt ON pt.track_uri=t.uri "  # noqa: S608  identifiers from fixed whitelist/placeholders, values bound
                "JOIN playlists p ON p.id=pt.playlist_id WHERE p.name=? AND p.grp='New Genres' "
                "AND p.status!='gone'", (pl,)).fetchall()
            prop = {}
            for u in uris:
                r = con.execute(f"SELECT name, artists, {cols} FROM tracks WHERE uri=?", (u,)).fetchone()  # noqa: S608  identifiers from fixed whitelist/placeholders, values bound
                if r is None:
                    raise ValueError(f"unknown track {u}")
                prop[f"{r['name']} - {r['artists'].replace(';', ', ')}"] = {x: r[x] for x in _CHECK_METRICS}
            seen = {m["uri"] for m in members}
            ref = [{x: m[x] for x in _CHECK_METRICS} for m in members]
            ref += [v for u, v in zip(uris, prop.values(), strict=False) if u not in seen]
            flags = flag_outliers(prop, ref)
            if flags:
                res[pl] = flags
    return res


# Grading check: the numbers above only catch a song whose own row contradicts the list, and they
# say nothing about a song with no row. 2026-10-01/02 sorts were written off Gemini/Beatport genre
# wording instead, so every placement now has to carry the evidence the grading procedure names:
# a BPM with where it came from, the drop's tellers, and real members of the list it matches.
NEEDS_LISTEN = "needs a listen"
_TELLERS = ("bass", "drums", "hook")  # lead is optional: not every list has one
# Someone else's genre call is never evidence. Beatport is fine as a tempo source only.
_TAG_RE = re.compile(r"(?i)\b(gemini|agy|beatport|tagged|genre tag|label\w*|described as|"
                     r"g-house|dance\s*/\s*pop)\b")


def _norm(s):
    return re.sub(r"[^0-9a-z]", "", unicodedata.normalize("NFKD", s).casefold())


def grade_song(e, members, settled=None):
    """e: one placement entry; members: the list's current songs as "Artist - Title", or None
    when it is not a settled list yet. settled: every settled list's songs, the only reference a
    new list may compare to, because a "(new)" list's songs were never checked (Sam,
    2026-10-02: "lock in the genre but i didnt check the songs so dont assume the vibe").
    Returns the reasons it fails (empty = graded)."""
    why = []
    bpm, src = e.get("bpm"), str(e.get("bpm_source") or "")
    if not isinstance(bpm, (int, float)) or bpm <= 0:
        why.append("no BPM number")
    if not src.strip():
        why.append("no bpm_source (music.db or the BPM site it came from)")
    elif re.search(r"(?i)\b(gemini|agy)\b", src):
        why.append(f"bpm_source {src!r} is a model's guess, not a tempo reading")
    t = e.get("drop_tellers") or {}
    if not isinstance(t, dict):
        t = {}
    why += [f"no drop teller for {k}" for k in _TELLERS if not str(t.get(k) or "").strip()]
    comp = [c for c in e.get("compared_to") or [] if str(c).strip()]
    if not comp:
        why.append("compared_to names no song from the list")
    elif members is not None or settled is not None:
        ref = members if members is not None else settled
        have = {_norm(m) for m in ref} | {_norm(m.split(" - ", 1)[-1]) for m in ref}  # pyright: ignore[reportOptionalIterable]  init() sets DB_PATH / ref is members or settled, one is not None
        where = "this list" if members is not None else "any settled list"
        why += [f"compared_to {c!r} is not in {where}" for c in comp if _norm(c) not in have]
    text = " ".join([*map(str, t.values()), *map(str, comp), str(e.get("why") or "")])
    if m := _TAG_RE.search(text):
        why.append(f"cites a genre tag ({m.group(0)!r}); only BPM and the drop's tellers count")
    return why


def settled_tracks(con):
    """Every track in a settled list: [{uri, isrc, artists, name, lists: [names]}].
    Storage is the one exclusion; "+ X (new)" lists are group `playlists`, so already outside."""
    out = {}
    for r in con.execute(
            "SELECT t.uri, t.isrc, t.artists, t.name, p.name pname FROM playlist_tracks pt "
            "JOIN playlists p ON p.id=pt.playlist_id JOIN tracks t ON t.uri=pt.track_uri "
            "WHERE p.grp='New Genres' AND p.status!='gone' AND p.name!='Storage' "
            "ORDER BY t.uri, p.name"):
        e = out.setdefault(r["uri"], {"uri": r["uri"], "isrc": r["isrc"], "artists": r["artists"],
                                      "name": r["name"], "lists": []})
        e["lists"].append(r["pname"])
    return list(out.values())


def listener_why(con, e, playlist):
    """Extra reasons a bpm_source "listener" entry fails: it must name its reading, and the
    BPM, tellers and comparisons must be that reading's own, under a pipeline whose blind test
    passed (spec 2026-10-27-song-listener-design.md section 6). Empty = the evidence holds."""
    from music.listener import FOLD_TOL, fold_to
    r = con.execute("SELECT * FROM readings WHERE id=?", (e.get("reading_id"),)).fetchone() \
        if isinstance(e.get("reading_id"), int) else None
    if r is None or not e.get("uri") or r["uri"] != e.get("uri"):
        return ["listener evidence names no reading for this song (needs uri and reading_id)"]
    # A lone measured vote stored before the blind test passed has no consensus; its tempo stands now.
    try:
        lone = [v["source"] for v in json.loads(r["votes"] or "[]")] == ["measured"]
    except (ValueError, TypeError, KeyError):
        lone = False
    tempo = r["consensus_bpm"] if r["consensus_bpm"] is not None else (r["main_bpm"] if lone else None)
    if r["status"] != "ok" or tempo is None:
        return [f"listener reading {r['id']} has no agreed tempo ({r['status']}: {r['reason'] or 'no consensus'})"]
    why = []
    if not con.execute("SELECT 1 FROM blind_tests WHERE pipeline_id=? AND passed=1", (r["pipeline_id"],)).fetchone():
        why.append("no passed blind test for this listener version")
    bpm = e.get("bpm")
    if isinstance(bpm, (int, float)) and bpm > 0 and abs(fold_to(bpm, tempo) - tempo) > FOLD_TOL:
        why.append(f"bpm {bpm} is not the reading's {tempo}")
    try:
        drops, nb = json.loads(r["drops"] or "[]"), json.loads(r["neighbours"] or "{}")
    except ValueError:
        return why + [f"listener reading {r['id']} is malformed"]
    heard = (drops[0].get("tellers") or {}) if drops and isinstance(drops[0], dict) else {}
    t = e.get("drop_tellers") if isinstance(e.get("drop_tellers"), dict) else {}
    for k, v in t.items():
        if str(v).strip().casefold() == "unknown" or heard.get(k) == "unknown":
            why.append(f"drop teller {k} is unknown in the reading")
        elif str(v).strip() != str(heard.get(k, "")).strip():
            why.append(f"drop teller {k} {v!r} is not the reading's {heard.get(k)!r}")
    near = {_norm(s) for s in (nb.get("per_list") or {}).get(playlist, [])}
    why += [f"compared_to {c!r} is not among the reading's nearest {playlist} songs"
            for c in e.get("compared_to") or [] if str(c).strip() and _norm(str(c)) not in near]
    return why


def grade_sort(placements):
    """placements: {playlist: [entry, ...]}, entry = {"song": "Artist - Title", "uri"?: ...,
    "bpm", "bpm_source", "drop_tellers": {bass, drums, hook, lead?}, "compared_to": [songs]}.
    The "needs a listen" group needs only the song. Returns {"ok": [(playlist, song)],
    "fail": {(playlist, song): [reasons]}, "warn": check_sort's number flags for entries with a uri}."""
    ok, fail, uris = [], {}, {}
    with _tx() as con:
        settled = [f"{a.replace(';', ', ')} - {n}" for a, n in con.execute(
            "SELECT DISTINCT t.artists, t.name FROM tracks t JOIN playlist_tracks pt ON pt.track_uri=t.uri "
            "JOIN playlists p ON p.id=pt.playlist_id WHERE p.grp='New Genres' AND p.status!='gone'")]
        for pl, entries in placements.items():
            if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
                raise ValueError(f"{pl}: each song must be an evidence entry, not a bare uri")
            rows = con.execute(
                "SELECT t.artists, t.name FROM tracks t JOIN playlist_tracks pt ON pt.track_uri=t.uri "
                "JOIN playlists p ON p.id=pt.playlist_id WHERE p.name=? AND p.grp='New Genres' "
                "AND p.status!='gone'", (pl,)).fetchall()
            # An empty list has no members to compare to, so it falls back to the settled lists
            # like a new one (2026-10-02: the freshly made Riddim list failed every placement).
            members = [f"{a.replace(';', ', ')} - {n}" for a, n in rows] if rows else None
            for e in entries:
                song = str(e.get("song") or "").strip()
                if not song:
                    raise ValueError(f"{pl}: entry with no song name")
                why = [] if pl.casefold() == NEEDS_LISTEN else grade_song(e, members, settled)
                if pl.casefold() != NEEDS_LISTEN and str(e.get("bpm_source") or "").strip() == "listener":
                    why += listener_why(con, e, pl)
                if why:
                    fail[(pl, song)] = why
                else:
                    ok.append((pl, song))
                if e.get("uri") and pl.casefold() != NEEDS_LISTEN:
                    uris.setdefault(pl, []).append(e["uri"])
    return {"ok": ok, "fail": fail, "warn": check_sort(uris) if uris else {}}


def set_group(name, grp):
    """Refile a playlist, for when group_for_name guessed wrong. Returns rows changed."""
    if grp not in GROUPS:
        raise ValueError(f"group must be one of {GROUPS}")
    with _tx() as con:
        return con.execute("UPDATE playlists SET grp=?, updated=datetime('now') WHERE name=? AND status!='ignored'",
                           (grp, name)).rowcount


# ---- Spotify pull ------------------------------------------------------------

def _key(name):
    """Export file stem for a Spotify name: illegal filename chars dropped, spaces to '_'.

    Trailing '_' is ignored on both sides (the export shows 'R&B_', 'Pop_'); overlap breaks ties.
    """
    s = unicodedata.normalize("NFC", name)
    return re.sub(r'[\\/:*?"<>|]', "", s).replace(" ", "_").rstrip("_").casefold()


def link(owned, con=None):
    """Tie export rows with no spotify_id to owned playlists; add the rest of `owned` as new rows.

    owned: [{"id", "name", "uris": set}] (already excluding ignored names).
    -> {"linked": [names], "unlinked": [names], "new": [names]}.
    """
    if con is None:
        with _tx() as c:
            return link(owned, c)
    have = {r[0] for r in con.execute("SELECT spotify_id FROM playlists WHERE spotify_id IS NOT NULL")}
    free = [o for o in owned if o["id"] not in have]
    pend = con.execute("SELECT id, name, file_name FROM playlists WHERE spotify_id IS NULL "
                       "AND file_name IS NOT NULL AND status IN ('active','unlinked') ORDER BY id").fetchall()
    uris = {p["id"]: {r[0] for r in con.execute("SELECT track_uri FROM playlist_tracks WHERE playlist_id=?", (p["id"],))}
            for p in pend}
    matched, linked = {}, []  # row id -> owned dict

    def take(p, o):
        matched[p["id"]] = o
        free.remove(o)

    for p in pend:  # pass 1: name candidates
        cands = [o for o in free if _key(o["name"]) == _key(Path(p["file_name"]).stem)]
        if len(cands) == 1:
            take(p, cands[0])
        elif len(cands) > 1:
            ranked = sorted(cands, key=lambda o: -len(uris[p["id"]] & o["uris"]))
            a, b = (len(uris[p["id"]] & o["uris"]) for o in ranked[:2])
            if a > b:  # a tie is not a decision
                take(p, ranked[0])
    for p in pend:  # pass 2: renamed since the export
        if p["id"] in matched or not uris[p["id"]] or not free:
            continue
        best = max(free, key=lambda o: len(uris[p["id"]] & o["uris"]))
        if len(uris[p["id"]] & best["uris"]) * 2 >= len(uris[p["id"]]):
            take(p, best)
    for p in pend:
        o = matched.get(p["id"])
        if o:
            con.execute("UPDATE playlists SET spotify_id=?, name=?, status='active', updated=datetime('now') WHERE id=?",
                        (o["id"], o["name"], p["id"]))
            linked.append(o["name"])
        elif con.execute("SELECT status FROM playlists WHERE id=?", (p["id"],)).fetchone()[0] != "unlinked":
            con.execute("UPDATE playlists SET status='unlinked', updated=datetime('now') WHERE id=?", (p["id"],))
    new = []
    for o in free:
        con.execute("INSERT INTO playlists (name, grp, spotify_id) VALUES (?,?,?)",
                    (o["name"], group_for_name(o["name"]), o["id"]))
        new.append(f'{o["name"]} -> {group_for_name(o["name"])}')
    unl = [r[0] for r in con.execute("SELECT name FROM playlists WHERE status='unlinked' ORDER BY name")]
    return {"linked": linked, "unlinked": unl, "new": new}


def pull():
    """Read every owned playlist that changed since the last pull, and Liked Songs if it
    changed, then link and apply in one transaction. Unchanged playlists cost no requests.

    Any failed read raises before anything is written.
    """
    from music import spotify
    owned = spotify.owned_playlists()
    with _tx() as con:
        ignored = {_key(Path(r[0]).stem) for r in con.execute(
            "SELECT file_name FROM playlists WHERE status='ignored' AND file_name IS NOT NULL")}
        pending = {_key(Path(r[0]).stem) for r in con.execute(
            "SELECT file_name FROM playlists WHERE spotify_id IS NULL AND file_name IS NOT NULL "
            "AND status IN ('active','unlinked')")}
        linked_ids = {r[0] for r in con.execute("SELECT spotify_id FROM playlists WHERE spotify_id IS NOT NULL")}
        # A playlist whose version tag matches the last read has not changed: skip it.
        seen = dict(con.execute("SELECT spotify_id, snapshot_id FROM playlists "
                                "WHERE spotify_id IS NOT NULL AND snapshot_id IS NOT NULL AND status='active'"))
        liked_have = {r[0] for r in con.execute(
            "SELECT track_uri FROM playlist_tracks JOIN playlists p ON p.id=playlist_id WHERE p.spotify_id='liked'")}
    want = [o for o in owned
            if o["id"] in linked_ids or _key(o["name"]) not in ignored or _key(o["name"]) in pending]
    read = [o for o in want if not o.get("snapshot_id") or seen.get(o["id"]) != o["snapshot_id"]]
    tracks, items = {}, {}
    for o in read:
        its = spotify.playlist_items(o["id"])
        items[o["id"]] = {t["uri"] for t in its}
        tracks.update({t["uri"]: t for t in its})
    # Liked Songs has no version tag. Same count and every newest-50 uri already known
    # means nothing was added (adds land on top), so nothing was removed either.
    total, head = spotify.liked_head()
    liked = None
    if not liked_have or total != len(liked_have) or not head <= liked_have:
        liked = spotify.liked_tracks()
        tracks.update({t["uri"]: t for t in liked})
    with _tx() as con:
        res = link([{**o, "uris": items.get(o["id"], set())} for o in want], con)
        if not con.execute("SELECT 1 FROM playlists WHERE spotify_id='liked'").fetchone():
            con.execute("INSERT INTO playlists (name, grp, spotify_id) VALUES ('Liked Songs','root','liked')")
        snap_src = dict(items)
        if liked is not None:
            snap_src["liked"] = {t["uri"] for t in liked}
        con.executemany("UPDATE playlists SET snapshot_id=? WHERE spotify_id=?",
                        [(o["snapshot_id"], o["id"]) for o in read])
        snapshot = {}
        for sid, uris in snap_src.items():
            pid = con.execute("SELECT id FROM playlists WHERE spotify_id=?", (sid,)).fetchone()[0]
            snapshot[pid] = uris
            con.execute("UPDATE playlists SET status='active' WHERE id=? AND status='gone'", (pid,))
        owned_ids = {o["id"] for o in owned} | {"liked"}
        gone = [r[0] for r in con.execute("SELECT id FROM playlists WHERE spotify_id IS NOT NULL AND status='active'"  # noqa: S608  identifiers from fixed whitelist/placeholders, values bound
                                          " AND spotify_id NOT IN (%s)" % ",".join("?" * len(owned_ids)), list(owned_ids))]
        con.executemany("UPDATE playlists SET status='gone', updated=datetime('now') WHERE id=?", [(i,) for i in gone])
        out = _apply(con, snapshot, tracks, "pull")
        summary = (f"pull: {out['playlists']} playlists read, {len(want) - len(read)} unchanged, "
                   f"+{out['added']} -{out['removed']}, "
                   f"{len(res['linked'])} linked, {len(res['unlinked'])} unlinked, "
                   f"{len(res['new'])} new, {len(gone)} gone")
        con.execute("UPDATE refreshes SET summary=? WHERE id=?", (summary, out["refresh_id"]))
    return {"read": len(read), "skipped": len(want) - len(read),
            "linked": len(res["linked"]), "unlinked": res["unlinked"], "new": len(res["new"]),
            "gone": len(gone), "added": out["added"], "removed": out["removed"]}


# ---- Sort playlists ------------------------------------------------------------
# The Temp grind's proposed sorts, made real in Spotify so Sam merges lists instead of
# hand-moving songs. Every list is new: an existing New Genres target gets a "+ <name>"
# add-on holding only songs not already in it, a missing one gets "+ <name> (new)".
# Created rows are filed as `playlists` so the pull never counts their songs as sorted.

SORT_STATE = "_created.json"
LISTEN = "+ Needs a listen"


def _listen_songs(con, sort_dir):
    """uris under each .md's "Needs a listen" heading, matched to its Temp list by "Artist - Title"."""
    out = []
    for md in sorted(Path(sort_dir).glob("*.md")):
        if md.name.startswith(("_", "2-misc-part")):
            continue
        temp, lines, on = None, [], False
        for ln in md.read_text().splitlines():
            if ln.startswith("## "):
                temp = ln[3:].strip()
            elif ln.startswith("### "):
                on = "needs a listen" in ln.lower()
            elif on and ln.startswith("- [ ] "):
                lines.append(ln[6:])
        if not lines:
            continue
        keys = [(f"{r[1].replace(';', ', ')} - {r[2]}", r[0]) for r in con.execute(
            "SELECT t.uri, t.artists, t.name FROM playlist_tracks pt JOIN tracks t ON t.uri=pt.track_uri "
            "JOIN playlists p ON p.id=pt.playlist_id WHERE p.name=? AND p.grp='Temp Genres'", (temp,))]
        for ln in lines:
            hit = max((k for k in keys if ln.startswith(k[0])), key=lambda k: len(k[0]), default=None)
            if hit:
                out.append(hit[1])
            else:
                print(f"needs a listen, no match in {temp}: {ln}", file=sys.stderr)
    return out


def sort_plan(sort_dir):
    """-> [{"name", "target", "existing", "uris"}] from sorts/*.json, add-ons already subtracted."""
    targets = {}
    for f in sorted(Path(sort_dir).glob("*.json")):
        if f.name.startswith(("_", "2-misc-part")):  # 2-misc.json is the reconciled merge of the parts
            continue
        for tgt, uris in json.loads(f.read_text()).items():
            targets.setdefault(tgt, []).extend(uris)
    with _tx() as con:
        ng = {r[0]: r[1] for r in con.execute(
            "SELECT name, id FROM playlists WHERE grp='New Genres' AND status!='ignored'")}
        if "EDM Trap" not in ng and "Trap" in ng:  # his EDM Trap is still named Trap in Spotify
            ng["EDM Trap"] = ng["Trap"]
        plan = []
        for tgt in sorted(targets):
            have = {r[0] for r in con.execute("SELECT track_uri FROM playlist_tracks WHERE playlist_id=?",
                                              (ng[tgt],))} if tgt in ng else set()
            uris = [u for u in dict.fromkeys(targets[tgt]) if u.startswith("spotify:track:") and u not in have]
            if uris:
                plan.append({"name": f"+ {tgt}" if tgt in ng else f"+ {tgt} (new)",
                             "target": tgt, "existing": tgt in ng, "uris": uris})
        listen = [u for u in dict.fromkeys(_listen_songs(con, sort_dir)) if u.startswith("spotify:track:")]
    if listen:
        plan.append({"name": LISTEN, "target": None, "existing": False, "uris": listen})
    return plan


def create_sort_playlists(sort_dir, plan=None):
    """Create each planned playlist and fill it. Resumable: progress is saved to
    <sort_dir>/_created.json after every request, so a rerun after a lockout picks up where it stopped."""
    from music import spotify
    plan = plan if plan is not None else sort_plan(sort_dir)
    state_p = Path(sort_dir) / SORT_STATE
    state = json.loads(state_p.read_text()) if state_p.exists() else {}

    def save():
        state_p.write_text(json.dumps(state, indent=1))

    for pl in plan:
        st = state.get(pl["name"])
        if st is None:
            what = f"merge into {pl['target']}" if pl["existing"] else "new list"
            pid = spotify.create_playlist(pl["name"], f"Proposed Temp sort 2026-09-29: {what}.")
            st = state[pl["name"]] = {"id": pid, "added": 0}
            save()
            with _tx() as con:
                con.execute("INSERT INTO playlists (name, grp, spotify_id) VALUES (?, 'playlists', ?) "
                            "ON CONFLICT(spotify_id) DO NOTHING", (pl["name"], pid))
            spotify._sleep(1)  # ponytail: flat 1s between writes; the 21-hour lockout came from bursts
        while st["added"] < len(pl["uris"]):
            batch = pl["uris"][st["added"]:st["added"] + 100]
            spotify.add_items(st["id"], batch)
            st["added"] += len(batch)
            save()
            spotify._sleep(1)
    return state


# ---- CLI ---------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(prog="music.library")
    sub = ap.add_subparsers(dest="cmd", required=True)
    le = sub.add_parser("load-export")
    le.add_argument("dir")
    le.add_argument("--ignore-from", dest="ignore_from")
    sf = sub.add_parser("scrub-features", help="clear audio features the export files disagree on")
    sf.add_argument("dir")
    ch = sub.add_parser("changes")
    ch.add_argument("--since")
    hi = sub.add_parser("history")
    hi.add_argument("song")
    sub.add_parser("progress")
    ck = sub.add_parser("check")
    ck.add_argument("json", help='file of {"playlist": [{"song", "bpm", "bpm_source", "drop_tellers", '
                                 '"compared_to", "uri"?}, ...]}; see grade_sort')
    sg = sub.add_parser("set-group")
    sg.add_argument("playlist")
    sg.add_argument("group", choices=GROUPS)
    sp = sub.add_parser("sort-playlists")
    sp.add_argument("dir")
    sp.add_argument("--create", action="store_true", help="create them in Spotify; default only prints the plan")
    li = sub.add_parser("listen", help="measure songs that have no reading for the current listener version")
    li.add_argument("what", nargs="+", help="a playlist name or track uris")
    li.add_argument("--again", action="store_true", help="re-measure songs that already have a reading")
    li.add_argument("--vote", action="append", default=[], metavar="SOURCE=BPM", help="an extra tempo vote")
    sub.add_parser("listen-reference", help="measure every settled song (resumable)")
    de = sub.add_parser("describe", help="measure one song's sections and print its fact sheet")
    de.add_argument("song", help='a track uri or "Artist - Title"')
    de.add_argument("--again", action="store_true", help="re-measure even when a sheet for this version exists")
    bt = sub.add_parser("blind-test", help="score the listener on held-out settled songs; gates check")
    bt.add_argument("--n", type=int, default=50)
    bt.add_argument("--seed", type=int, default=20261027)
    cb = sub.add_parser("calibrate", help="measure calibration-pool songs and print what each threshold did")
    cb.add_argument("--n", type=int, default=30)
    cb.add_argument("--seed", type=int, default=0)
    sub.add_parser("pull")
    sub.add_parser("login")
    a = ap.parse_args(argv)
    if a.cmd == "login":
        from music import spotify
        spotify.login()
    elif a.cmd == "sort-playlists":
        plan = sort_plan(a.dir)
        for pl in plan:
            print(f"{len(pl['uris']):5}  {pl['name']}")
        print(f"{len(plan)} playlists, {sum(len(pl['uris']) for pl in plan)} songs")
        if a.create:
            st = create_sort_playlists(a.dir, plan)
            print(f"done: {len(st)} playlists created and filled")
    elif a.cmd == "pull":
        print(json.dumps(pull(), indent=1))
    elif a.cmd == "scrub-features":
        print(f"{scrub_features(a.dir)} songs had conflicting audio features; cleared")
    elif a.cmd == "history":
        for t in song_history(a.song):
            print(f"{t['artists']} - {t['name']}")
            for e in t["events"]:
                sign = "+" if e["kind"] == "added" else "-"
                print(f"  {e['when'][:16]} {sign} {e['playlist']} [{e['group']}] ({e['source']})")
    elif a.cmd == "progress":
        p = sorting_progress()
        print(f"{p['unsorted']} songs not in any New Genres list")
        for t in p["temp"]:
            print(f"  {t['playlist']}: {t['left']} left of {t['songs']} ({t['homed']} already homed)")
    elif a.cmd == "check":
        # The Stop gate (vault .claude/hooks/vault-music-sort-gate.py) reads the "ok:" lines.
        try:
            g = grade_sort(json.loads(Path(a.json).read_text()))
        except ValueError as e:
            sys.exit(f"refused: {e}")
        for pl, song in g["ok"]:
            print(f"ok: {pl}: {song}")
        for (pl, song), why in g["fail"].items():
            print(f"FAIL: {pl}: {song}: {'; '.join(why)}")
        for pl, songs in g["warn"].items():
            for song, why in songs.items():
                print(f"warn: {pl}: {song}: {'; '.join(why)}")
        print(f"graded: {len(g['ok'])} ok, {len(g['fail'])} failed, "
              f"{sum(map(len, g['warn'].values()))} number warnings")
        sys.exit(1 if g["fail"] else 0)
    elif a.cmd in ("listen", "listen-reference"):
        from music import listener
        with _tx() as con:
            if a.cmd == "listen-reference":
                uris = [t["uri"] for t in settled_tracks(con)]
            elif all(w.startswith("spotify:track:") for w in a.what):
                uris = a.what
            else:
                uris = [u for (u,) in con.execute(
                    "SELECT pt.track_uri FROM playlist_tracks pt JOIN playlists p ON p.id=pt.playlist_id "
                    "WHERE p.name=? AND p.status!='gone' ORDER BY pt.rowid", (" ".join(a.what),))]
                if not uris:
                    sys.exit(f"no playlist named {' '.join(a.what)!r} with songs")
        votes = [(v.split("=", 1)[0], float(v.split("=", 1)[1])) for v in getattr(a, "vote", [])]
        listener.run_batch(uris, again=getattr(a, "again", False), extra_votes=votes,
                           reference=a.cmd == "listen-reference")
    elif a.cmd == "describe":
        from music import facts, listener
        listener._need_key()
        r = facts.describe(a.song, again=a.again)
        if r["status"] not in ("ok", "skipped"):
            sys.exit(f"{r['status']}: {r['reason']}")
        print(facts.print_sheet(r["sheet_id"]))
    elif a.cmd in ("blind-test", "calibrate"):
        from music import listener
        listener._need_key()
        if a.cmd == "calibrate":
            listener.calibrate(a.n, a.seed)
            return
        r = listener.blind_test(a.n, a.seed)
        print(f"blind test {r['id']} (pipeline {r['pipeline_id']}): n {r['n']}, identity ok {r['identity_ok']}, "
              f"measured hits {r['measured_hits']} (bar 45), consensus hits {r['consensus_hits']}, "
              f"list hits {r['list_hits']} (reported only), majority-list baseline {r['baseline_hits']}: "
              f"{'PASSED' if r['passed'] else 'FAILED'}")
        for m in r["second_opinions"]:
            print(f"  second opinion: {m['uri']} {m['truth_source']} {m['truth']} measured {m['main_bpm']}, "
                  f"{m['second_opinion']}")
        for m in r["misses"]:
            print(f"  miss: {m['uri']} {m['truth_source']} {m['truth']} measured {m.get('main_bpm')} "
                  f"({m['status']}{': ' + m['reason'] if m['reason'] else ''})")
    elif a.cmd == "set-group":
        print(f"{set_group(a.playlist, a.group)} playlist(s) moved to {a.group}")
    elif a.cmd == "load-export":
        print(json.dumps(load_export(a.dir, a.ignore_from)))
    else:
        for c in changes(a.since):
            print(f"{c['playlist']} [{c['group']}]: +{len(c['added'])} -{len(c['removed'])} ~{len(c['moved'])}")
            for k, sign in (("added", "+"), ("removed", "-")):
                for s in c[k]:
                    print(f"  {sign} {s}")
            for m in c["moved"]:
                print(f"  ~ {m['song']} -> {', '.join(m['to'])}")


if __name__ == "__main__":
    main()
