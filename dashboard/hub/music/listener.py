"""Song listener, the system-Python half: identity, tempo vote, validation, storage.

The audio and ML work runs in the 3.11 venv (listener_measure.py) as a child process, so torch
and tensorflow never load into the Hub's Python. Design: vault docs/specs/2026-10-27-song-listener-design.md.
"""

import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from statistics import median

from .library import _norm

ACOUSTID_MIN = 0.9  # calibrated: Task 8
LENGTH_TOL_S = 2.0  # a upload this far from Spotify's length is a different edit
ENV_PATH = Path.home() / ".config" / "vault-api" / ".env"
VENV_PY = Path.home() / ".venvs" / "listener" / "bin" / "python"
FOLD_TOL = 2.0  # BPM: two tempos agree when within this after half/double folding


def deezer_bpm(isrc):
    """Deezer's tempo for an ISRC, or None. Deezer answers 0 for many songs, which is no vote."""
    try:
        with urllib.request.urlopen(f"https://api.deezer.com/track/isrc:{isrc}", timeout=15) as r:
            bpm = json.load(r).get("bpm")
    except (OSError, ValueError):
        return None
    return float(bpm) if isinstance(bpm, (int, float)) and bpm > 0 else None


def _beatport_tracks(o):
    if isinstance(o, dict):
        if "bpm" in o and "track_name" in o:
            yield o
        for v in o.values():
            yield from _beatport_tracks(v)
    elif isinstance(o, list):
        for v in o:
            yield from _beatport_tracks(v)


def beatport_bpm(isrc, query):
    """The label's BPM from Beatport's track search, matched on ISRC only, or None.
    The blind test's benchmark (Sam, 2026-10-28): it agreed with the measured tempo on 14 of 20
    calibration songs, where the export's tempo agreed on 2."""
    req = urllib.request.Request("https://www.beatport.com/search/tracks?q=" + urllib.parse.quote(query),
                                 headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0",
                                          "Accept-Language": "en-US"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.read().decode(), re.S)
        found = _beatport_tracks(json.loads(m.group(1))) if m else ()
        bpm = next((t["bpm"] for t in found if (t.get("isrc") or "").upper() == isrc.upper()), None)
    except (OSError, ValueError):
        return None
    finally:
        time.sleep(1)  # ponytail: polite fixed pause between Beatport searches
    return float(bpm) if isinstance(bpm, (int, float)) and bpm > 0 else None


def songbpm_bpm(artist, name):
    """songbpm.com's tempo for a song, or None. The second opinion when the listener and Beatport
    disagree; a page it cannot find or read leaves the song a miss."""
    def slug(t):
        return re.sub(r"\s+", "-", re.sub(r"[^\w\s-]", "", t.lower()).strip())
    url = f"https://songbpm.com/@{urllib.parse.quote(slug(artist))}/{urllib.parse.quote(slug(name))}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            page = r.read().decode(errors="ignore")
    except (OSError, ValueError):
        return None
    finally:
        time.sleep(1)
    return parse_songbpm(page)


def parse_songbpm(page):
    m = re.search(r"\b(\d{2,3}) ?BPM\b", page or "")
    bpm = float(m.group(1)) if m else None
    return bpm if bpm and 40 <= bpm <= 300 else None


def fold_to(bpm, anchor):
    """bpm moved by x0.5, x1 or x2, whichever lands closest to anchor."""
    return min((bpm * f for f in (0.5, 1.0, 2.0)), key=lambda v: abs(v - anchor))


def vote(votes, measured_only_ok=False):
    """votes: [(source, bpm)], source "measured" for the listener's own reading.
    Each vote in turn is the anchor; the others fold to it and count when within FOLD_TOL.
    The anchor with the most supporters wins. Anchors tied with the same supporters in
    different octaves (70 vs 140) take the outside sources' octave, so a model hearing half
    time cannot drag Spotify and Deezer down with it; any other tie is no consensus.
    A lone measured vote stands only when measured_only_ok (the blind test passed on
    measured tempo alone). Returns {"consensus_bpm", "agreement", "cluster"}."""
    votes = [(s, float(b)) for s, b in votes if isinstance(b, (int, float)) and b == b and b > 0]
    none = {"consensus_bpm": None, "agreement": f"0 of {len(votes)}", "cluster": []}
    if not votes:
        return none
    if len(votes) == 1:
        s, b = votes[0]
        if s == "measured" and not measured_only_ok:
            return none
        return {"consensus_bpm": round(b, 1), "agreement": "1 of 1", "cluster": [s]}
    cands = []
    for _, anchor in votes:
        sup = frozenset(j for j, (_, b) in enumerate(votes) if abs(fold_to(b, anchor) - anchor) <= FOLD_TOL)
        cands.append((anchor, sup))
    best = max(len(sup) for _, sup in cands)
    if best < 2:
        return none
    top = [(a, sup) for a, sup in cands if len(sup) == best]
    if len({sup for _, sup in top}) > 1:
        return none  # two different groups of votes tie
    sup = top[0][1]
    # Same supporters, possibly in several octaves: the octave holding most outside votes unfolded.
    def outside(a):
        return sum(1 for j in sup if votes[j][0] != "measured" and abs(votes[j][1] - a) <= FOLD_TOL)
    most = max(outside(a) for a, _ in top)
    picks = [a for a, _ in top if outside(a) == most]
    if max(picks) - min(picks) > 2 * FOLD_TOL:
        return none  # outside sources split evenly between octaves
    anchor = median(picks)
    return {"consensus_bpm": round(median(fold_to(votes[j][1], anchor) for j in sup), 1),
            "agreement": f"{len(sup)} of {len(votes)}",
            "cluster": sorted(votes[j][0] for j in sup)}


# --- identity: is this YouTube Music upload the Spotify row's recording ---

# A bare "feat. X" runs to the next " - " or bracket, so "Song feat. X - Extended" keeps "Extended".
# "with" counts only in brackets: Spotify writes "(with X)", YouTube Music drops it.
_FEAT = re.compile(r"[(\[]\s*(?:feat|ft|featuring|with)\b[^)\]]*[)\]]"
                   r"|\s-?\s*(?:feat|ft|featuring)\.?\s[^()\[\]]*?(?=\s+-\s|\s*[(\[]|$)", re.I)
_ORIGINAL = re.compile(r"[(\[]?\s*original mix\s*[)\]]?", re.I)


def _title_key(s):
    """Title for comparison: feat. credits and "Original Mix" dropped, case/accents/punctuation folded.
    Extended, VIP, Remix, Edit, Live, Remaster, Sped Up stay in, so they must match on both sides."""
    return _norm(_ORIGINAL.sub("", _FEAT.sub("", s or "")))


# Some uploads carry all artists in one string ("Dabin, Inukshuk ft. Nevve").
_ARTIST_SPLIT = re.compile(r"\s*(?:,|&|\b(?:feat|ft|featuring|x)\b\.?)\s*", re.I)


def _artist_keys(names):
    return {_norm(p) for n in names for p in _ARTIST_SPLIT.split(n or "") if _norm(p)}


def _acoustid_key(env_path=ENV_PATH):
    if os.environ.get("ACOUSTID_KEY"):
        return os.environ["ACOUSTID_KEY"]
    try:
        for line in Path(env_path).read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() == "ACOUSTID_KEY" and v.strip():
                return v.strip().strip("\"'")
    except OSError:
        pass
    raise RuntimeError(f"ACOUSTID_KEY missing: add ACOUSTID_KEY=<key> to {env_path} (~/.config/vault-api/.env)")


def _search(query):
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "search.json"
        subprocess.run([str(VENV_PY), str(Path(__file__).with_name("listener_measure.py")),
                        "search", query, "--out", str(out)], check=True, timeout=120)
        return json.loads(out.read_text())


def _download(video_id, workdir):
    subprocess.run(["yt-dlp", "-q", "--no-warnings", "--js-runtimes", "node", "-x", "-o", f"{workdir}/%(id)s.%(ext)s",
                    f"https://music.youtube.com/watch?v={video_id}"], check=True, timeout=300)
    return next(Path(workdir).glob(f"{video_id}.*"))


def _fingerprint(path):
    j = json.loads(subprocess.run(["fpcalc", "-json", str(path)], check=True, capture_output=True,
                                  text=True, timeout=120).stdout)
    return j["duration"], j["fingerprint"]


def _acoustid(duration, fingerprint):
    # meta is space separated: urlencode writes the space as "+", a literal "+" would go out as %2B and be ignored
    q = urllib.parse.urlencode({"client": _acoustid_key(), "meta": "recordings isrcs",
                                "duration": int(duration), "fingerprint": fingerprint})
    with urllib.request.urlopen(f"https://api.acoustid.org/v2/lookup?{q}", timeout=30) as r:
        return json.load(r).get("results") or []


def identify(track, *, search=None, fingerprint=None, acoustid=None, download=None, workdir=None):
    """Find the track's audio on YouTube Music and prove it is the same recording: title,
    song-upload, length, then the row's ISRC on an AcoustID match scoring >= ACOUSTID_MIN.
    Survivors are tried in search order. Downloads land in workdir (caller's temp_run owns cleanup).
    Returns {"status": "ok"|"identity_failed", "reason", "video_id", "acoustid_score",
    "recording_id", "duration_s", "audio_hash", "path"}."""
    search, download = search or _search, download or _download
    fingerprint, acoustid = fingerprint or _fingerprint, acoustid or _acoustid
    out = {"status": "identity_failed", "reason": None, "video_id": None, "acoustid_score": None,
           "recording_id": None, "duration_s": None, "audio_hash": None, "path": None}

    def fail(why):
        return {**out, "reason": why}

    if track.get("is_local"):
        return fail("local file")
    isrc = (track.get("isrc") or "").strip().upper()
    if not isrc:
        return fail("no isrc")
    artists = [a.strip() for a in str(track.get("artists") or "").split(";") if a.strip()]
    name = track.get("name") or ""
    # The first-artist query misses some label uploads (Excision's "Fight Through The Pain"), so all artists too.
    results, seen = [], set()
    for q in dict.fromkeys([f"{artists[0] if artists else ''} {name}".strip(), f"{' '.join(artists)} {name}".strip()]):
        for r in search(q) or []:
            if r.get("videoId") not in seen:
                seen.add(r.get("videoId"))
                results.append(r)
    want, mine = _title_key(name), {_norm(a) for a in artists}
    secs = (track.get("duration_ms") or 0) / 1000
    pool, why = [r for r in results if _title_key(r.get("title")) == want], "name"
    if pool:
        pool, why = [r for r in pool if mine & _artist_keys(r.get("artists") or [])], "artist"
    if pool:
        pool, why = [r for r in pool if r.get("resultType") == "song"], "not a song upload"
    if pool:
        pool, why = [r for r in pool if abs((r.get("duration_seconds") or 0) - secs) <= LENGTH_TOL_S], "length"
    if pool:
        why = "isrc"
    workdir = Path(workdir) if workdir else Path(tempfile.gettempdir())

    def details_agree(rec):
        # Sam 2026-10-27: about 1 in 4 songs has no ISRC on MusicBrainz, so a recording with none
        # counts when artist, title and length agree. One carrying other ISRCs is a different release.
        return (not rec.get("isrcs") and _title_key(rec.get("title")) == want and _finite(rec.get("duration"))
                and abs(rec["duration"] - secs) <= LENGTH_TOL_S
                and bool(mine & {_norm(a.get("name") or "") for a in rec.get("artists") or []}))

    found = None  # (isrc_match, video result, score, recording, duration, path); an ISRC match ends the search
    for r in pool:
        path = Path(download(r["videoId"], workdir))
        dur, fp = fingerprint(path)
        for res in acoustid(dur, fp):
            if res.get("score", 0) < ACOUSTID_MIN:
                continue
            for rec in res.get("recordings") or []:
                if isrc in {i.upper() for i in rec.get("isrcs") or []}:
                    found = (1, r, res["score"], rec, dur, path)
                    break
                if found is None and details_agree(rec):
                    found = (0, r, res["score"], rec, dur, path)
            if found and found[0]:
                break
        if found and found[0]:
            break
        if not (found and found[5] == path):
            path.unlink(missing_ok=True)  # failed candidate: do not keep its audio
    if found is None:
        return fail(why)
    m, r, score, rec, dur, path = found
    return {"status": "ok", "reason": None, "video_id": r["videoId"], "acoustid_score": score,
            "recording_id": rec.get("id"), "isrc_match": m, "duration_s": dur,
            "audio_hash": hashlib.sha256(path.read_bytes()).hexdigest(), "path": str(path)}


@contextlib.contextmanager
def temp_run():
    """$TMPDIR/listener-<pid>-<ts>/, removed on the way out however the run ends."""
    import time
    d = Path(tempfile.gettempdir()) / f"listener-{os.getpid()}-{int(time.time())}"
    d.mkdir(parents=True)
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def sweep_stale(base=None):
    """Remove listener-<pid>-* folders whose process is gone (a killed run never reached its finally)."""
    for d in Path(base or tempfile.gettempdir()).glob("listener-*-*"):
        m = re.fullmatch(r"listener-(\d+)-\d+", d.name)
        if not (m and d.is_dir()):
            continue
        try:
            os.kill(int(m[1]), 0)
        except ProcessLookupError:
            shutil.rmtree(d, ignore_errors=True)
        except (PermissionError, OverflowError):
            pass  # alive under another user, or not a pid


# --- one song end to end: identity, the measuring child, the vote, one stored row ---

GPU_OK = False  # Task 1, 2026-10-27: any CUDA call segfaults in this WSL, so the child runs on CPU
MEASURE_PY = Path(__file__).with_name("listener_measure.py")
REQUIREMENTS = Path(__file__).with_name("listener-requirements.txt")
MEASURED_BAR = 45  # blind-test measured-tempo hits (of 50) that let a lone measured vote stand
CHILD_TIMEOUT_S = 1800


def _stable(v):
    """Sets sorted at any depth: str() of a set follows hash order, which changes per process."""
    if isinstance(v, (set, frozenset)):
        return sorted(_stable(x) for x in v)
    if isinstance(v, dict):
        return {k: _stable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_stable(x) for x in v]
    return v


def _constants(mod):
    return {k: _stable(v) for k, v in sorted(vars(mod).items())
            if k.isupper() and isinstance(v, (bool, int, float, str, set, frozenset, dict, tuple))}


def pipeline_id():
    """sha256 over the pinned requirements, every threshold constant in both halves, the beat source
    and the device. Readings and fingerprints from different ids are never compared."""
    import sys
    sys.path.insert(0, str(MEASURE_PY.parent))
    import listener_measure as M
    blob = json.dumps({"req": REQUIREMENTS.read_text(), "measure": _constants(M),
                       "listener": {k: v for k, v in _constants(sys.modules[__name__]).items()
                                    if k not in ("ENV_PATH", "VENV_PY", "MEASURE_PY", "REQUIREMENTS")},
                       "device": "cuda" if GPU_OK else "cpu"}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf")


def validate(r):
    """Problems with a child reading; empty means it may be stored."""
    import sys
    sys.path.insert(0, str(MEASURE_PY.parent))
    import listener_measure as M
    bad = []
    dur = r.get("duration_s")
    if not _finite(dur) or dur <= 0:
        return ["duration not a positive number"]
    if r.get("main_bpm") is not None and not (_finite(r["main_bpm"]) and r["main_bpm"] > 0):
        bad.append("main_bpm not a positive number")
    spans = []
    for i in r.get("intervals") or []:
        if not (_finite(i.get("start")) and _finite(i.get("end")) and i["start"] < i["end"]):
            bad.append(f"interval {i.get('start')}-{i.get('end')} not ordered")
        elif not all(_finite(i.get(k)) and i[k] > 0 for k in ("raw_bpm", "folded_bpm")):
            bad.append(f"interval at {i['start']} has a bad bpm")
        else:
            spans.append((i["start"], i["end"]))
    for g in r.get("gaps") or []:
        if _finite(g.get("start")) and _finite(g.get("end")) and g["start"] < g["end"]:
            spans.append((g["start"], g["end"]))
        else:
            bad.append("gap not ordered")
    spans.sort()
    edge = 0.0
    for s, e in spans:
        if abs(s - edge) > 0.05:
            bad.append(f"coverage hole {edge:.2f}-{s:.2f}")
        edge = max(edge, e)
    if abs(edge - dur) > 0.05:
        bad.append(f"coverage ends at {edge:.2f} of {dur:.2f}")
    for d in r.get("drops") or []:
        if not (_finite(d.get("start")) and _finite(d.get("end")) and d["start"] < d["end"]):
            bad.append("drop not ordered")
        bad += [f"teller {k}={v!r} unknown label" for k, v in (d.get("tellers") or {}).items()
                if k in M.bad_tellers({k: v})]
    emb = r.get("embedding") or []
    if len(emb) != M.EMBEDDING_DIMS or not all(_finite(v) for v in emb):
        bad.append(f"embedding is {len(emb)} values, want {M.EMBEDDING_DIMS} finite")
    return bad


def _child(path, out):
    env = {**os.environ, **({} if GPU_OK else {"CUDA_VISIBLE_DEVICES": ""})}
    p = subprocess.run([str(VENV_PY), str(MEASURE_PY), "measure", str(path), "--out", str(out)],
                       env=env, capture_output=True, text=True, timeout=CHILD_TIMEOUT_S)
    return p.returncode, (p.stderr.strip().splitlines() or [""])[-1]


def _measured_only_ok(con, pid):
    row = con.execute("SELECT measured_hits FROM blind_tests WHERE pipeline_id = ? ORDER BY run_at DESC LIMIT 1",
                      (pid,)).fetchone()
    return bool(row and (row[0] or 0) >= MEASURED_BAR)


def measure_track(uri, extra_votes=(), *, spotify=True, identify_fn=None, child=None, neighbours_fn=None):
    """Identify, measure and store one song. Identity failures are stored as a row (the reason is
    evidence); a measuring failure stores nothing, so a resumed batch re-measures the song.
    spotify=False withholds Spotify's tempo from the vote (the blind test scores against it).
    Returns {"reading_id", "status", "reason"}."""
    import array
    import time
    from . import library
    identify_fn, child = identify_fn or identify, child or _child
    pid = pipeline_id()
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    with library._tx() as con:
        track = con.execute("SELECT * FROM tracks WHERE uri = ?", (uri,)).fetchone()
    if track is None:
        raise ValueError(f"unknown track {uri}")
    track = dict(track)
    with temp_run() as d:
        ident = identify_fn(track, workdir=d)
        if ident["status"] != "ok":
            with library._tx() as con:
                rid = con.execute("INSERT INTO readings (uri, pipeline_id, measured_at, status, reason, video_id, "
                                  "acoustid_score) VALUES (?, ?, ?, 'identity_failed', ?, ?, ?)",
                                  (uri, pid, now, ident["reason"], ident["video_id"], ident["acoustid_score"])).lastrowid
            return {"reading_id": rid, "status": "identity_failed", "reason": ident["reason"]}
        out = d / "reading.json"
        rc, err = child(ident["path"], out)
        if rc != 0 or not out.exists():
            return {"reading_id": None, "status": "measure_failed", "reason": f"child exit {rc}: {err}"[:300]}
        r = json.loads(out.read_text())
    problems = validate(r)
    if problems:
        return {"reading_id": None, "status": "measure_failed", "reason": "invalid: " + "; ".join(problems)[:300]}
    votes = [("measured", r["main_bpm"])] if r.get("main_bpm") else []
    if spotify and track.get("tempo"):
        votes.append(("spotify", track["tempo"]))
    dz = deezer_bpm(track["isrc"])
    if dz:
        votes.append(("deezer", dz))
    votes += [(s, float(b)) for s, b in extra_votes]
    nb = neighbours_fn(r["embedding"], pid, exclude_isrcs=(track["isrc"],)) if neighbours_fn else None
    with library._tx() as con:
        v = vote(votes, _measured_only_ok(con, pid))
        sure = [i for i in r["intervals"] if not i["unsure"]]
        rid = con.execute(
            "INSERT INTO readings (uri, pipeline_id, measured_at, status, video_id, acoustid_score, recording_id, "
            "isrc_match, audio_hash, duration_s, intervals, main_bpm, tempo_change, drops, votes, consensus_bpm, "
            "agreement, neighbours) VALUES (?, ?, ?, 'ok', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uri, pid, now, ident["video_id"], ident["acoustid_score"], ident["recording_id"],
             ident.get("isrc_match", 1), ident["audio_hash"],
             r["duration_s"], json.dumps({"intervals": r["intervals"], "gaps": r["gaps"]}), r["main_bpm"],
             int(bool(r["tempo_change"] and sure)), json.dumps(r["drops"]),
             json.dumps([{"source": s, "bpm": b, "at": now} for s, b in votes]), v["consensus_bpm"],
             v["agreement"], json.dumps(nb) if nb else None)).lastrowid
        con.execute("INSERT INTO fingerprints (uri, pipeline_id, vector, dims, measured_at) VALUES (?, ?, ?, ?, ?)",
                    (uri, pid, array.array("f", r["embedding"]).tobytes(), len(r["embedding"]), now))
    return {"reading_id": rid, "status": "ok", "reason": None}


# --- nearest settled songs, and what a batch still has to measure ---

NEAREST_N = 10
PER_LIST_N = 5  # each list's own nearest members kept for check's compared_to


def neighbours(vector, pid, exclude_isrcs=()):
    """The settled songs whose fingerprint (same pipeline_id) is closest by cosine. A song in
    several lists votes once for each; a tie or a one-vote margin gives no list vote."""
    from collections import Counter
    import numpy as np
    from . import library
    skip = {i for i in exclude_isrcs if i}
    with library._tx() as con:
        settled = {s["uri"]: s for s in library.settled_tracks(con) if s["isrc"] not in skip}
        rows = [(u, v) for u, v in con.execute(
            "SELECT uri, vector FROM fingerprints WHERE pipeline_id = ? ORDER BY measured_at", (pid,))
            if u in settled]
    latest = dict(rows)  # ordered by measured_at, so the last vector per song wins
    if not latest:
        return {"nearest": [], "list_vote": None, "margin": 0, "per_list": {}}
    uris = list(latest)
    m = np.stack([np.frombuffer(latest[u], dtype=np.float32) for u in uris])
    q = np.asarray(vector, dtype=np.float32)
    dist = 1 - (m @ q) / (np.linalg.norm(m, axis=1) * np.linalg.norm(q) + 1e-12)
    order = np.argsort(dist, kind="stable")

    def song(u):
        return f"{settled[u]['artists'].replace(';', ', ')} - {settled[u]['name']}"

    nearest = [{"uri": uris[i], "song": song(uris[i]), "lists": settled[uris[i]]["lists"],
                "distance": round(float(dist[i]), 5)} for i in order[:NEAREST_N]]
    counts = Counter(pl for n in nearest for pl in n["lists"]).most_common()
    margin = counts[0][1] - (counts[1][1] if len(counts) > 1 else 0)
    per_list = {}
    for pl, _ in counts:
        per_list[pl] = [song(uris[i]) for i in order if pl in settled[uris[i]]["lists"]][:PER_LIST_N]
    return {"nearest": nearest, "list_vote": counts[0][0] if margin > 1 else None, "margin": margin,
            "per_list": per_list}


def todo(uris, pid, again=False):
    """uris still without a stored reading (ok or identity_failed) under pid, in order. A measuring
    failure stores nothing, so it comes back on the next run."""
    from . import library
    if again:
        return list(uris)
    with library._tx() as con:
        done = {u for (u,) in con.execute("SELECT DISTINCT uri FROM readings WHERE pipeline_id = ?", (pid,))}
    return [u for u in uris if u not in done]


def _print_reading(rid):
    from . import library
    with library._tx() as con:
        r = dict(con.execute("SELECT * FROM readings WHERE id = ?", (rid,)).fetchone())
    print(f"  identity ok: video {r['video_id']}, AcoustID {r['acoustid_score']}")
    for i in json.loads(r["intervals"])["intervals"]:
        print(f"  {i['start']:7.1f}-{i['end']:7.1f}s  {i['folded_bpm']:6.1f} BPM{'  (unsure)' if i['unsure'] else ''}")
    for d in json.loads(r["drops"] or "[]"):
        print(f"  drop {d['start']:.0f}-{d['end']:.0f}s: " + ", ".join(f"{k} {v}" for k, v in (d.get("tellers") or {}).items()))
    votes = ", ".join(f"{v['source']} {v['bpm']:.1f}" for v in json.loads(r["votes"] or "[]"))
    print(f"  vote: {votes} -> {r['consensus_bpm'] or 'no consensus'} ({r['agreement']})")
    nb = json.loads(r["neighbours"] or "{}")
    for n in nb.get("nearest", []):
        print(f"    {n['distance']:.3f}  {n['song']}  [{', '.join(n['lists'])}]")
    if nb:
        print(f"  list vote: {nb['list_vote'] or 'none'} (margin {nb['margin']})")


def _need_key():
    import sys
    try:
        _acoustid_key()  # every non-local song needs it; stop before the first download, not at song 4
    except RuntimeError as e:
        sys.exit(f"refused: {e}")


def _measure_retrying(uri, extra_votes, nb_fn, sleep, tries=3, wait_s=60):
    """measure_track, retried after a pause when it raises (a network blip killed a 51 h pass at
    song 48). Still raising after the last try is a measure_failed result: nothing is stored, so a
    rerun picks the song up. Locals, not module constants, so pipeline_id does not move."""
    for k in range(1, tries + 1):
        try:
            return measure_track(uri, extra_votes, neighbours_fn=nb_fn)
        except Exception as e:  # noqa: BLE001 - one song never ends the batch
            err = f"{type(e).__name__}: {e}"
            print(f"  error (try {k}/{tries}): {err[:200]}", flush=True)
            if k < tries:
                sleep(wait_s)
    return {"reading_id": None, "status": "error", "reason": err[:300]}


def run_batch(uris, *, again=False, extra_votes=(), reference=False, sleep=None, max_failed_in_row=5,
              pace_s=5, blocked_wait_s=1800):
    """Measure every uri still without a reading under this pipeline_id, printing as it goes.
    The reference pass skips the neighbour search (the settled set is what is being built).
    pace_s between songs: YouTube's bot check tripped after ~1,000 back-to-back downloads.
    After max_failed_in_row errors in a row (network down or YouTube blocking, not one song) it
    waits blocked_wait_s and retries the same song, for as long as that takes."""
    import time
    from . import library
    sleep = sleep or time.sleep
    _need_key()
    sweep_stale()
    pid = pipeline_id()
    left = todo(uris, pid, again)
    print(f"pipeline {pid}: {len(uris) - len(left)} done, {len(left)} left")
    t0 = time.time()
    failed_in_row = 0
    n = 0
    while n < len(left):
        uri = left[n]
        with library._tx() as con:
            t = con.execute("SELECT artists, name FROM tracks WHERE uri = ?", (uri,)).fetchone()
        print(f"[{n + 1}/{len(left)}] {t['artists'].replace(';', ', ')} - {t['name']}" if t
              else f"[{n + 1}/{len(left)}] {uri}", flush=True)
        res = _measure_retrying(uri, extra_votes, None if reference else neighbours, sleep)
        failed_in_row = failed_in_row + 1 if res["status"] == "error" else 0
        if failed_in_row >= max_failed_in_row:
            print(f"  blocked: {failed_in_row} songs failed in a row; waiting {blocked_wait_s // 60} min, "
                  f"then retrying this song ({time.strftime('%Y-%m-%d %H:%M')})", flush=True)
            sleep(blocked_wait_s)
            failed_in_row = max_failed_in_row - 1  # one more failure waits again
            continue
        if res["status"] == "ok" and not reference:
            _print_reading(res["reading_id"])
        else:
            print(f"  {res['status']}{': ' + res['reason'] if res['reason'] else ''}")
        n += 1
        eta = (time.time() - t0) / n * (len(left) - n)
        print(f"  done {n}, left {len(left) - n}, eta {eta / 3600:.1f} h", flush=True)
        if n < len(left):
            sleep(pace_s)


# --- calibration and the blind test (spec section 6) ---

BLIND_N = 50
TEMPO_BAR = 45  # measured-tempo hits of 50, the only gate since 2026-11-01
LIST_BAR = 35  # ponytail: no longer gates; deleting it moves pipeline_id and discards the reference pass
PER_LIST_CAP = 5


def is_calibration(uri):
    """A fixed tenth of songs, by uri hash, is the calibration pool; the blind test never draws from it."""
    return hashlib.sha256(uri.encode()).digest()[0] % 10 == 0


def blind_passed(n, measured_hits):
    """Tempo only (Sam, 2026-11-01): the fingerprint cannot name a list, so the list count is
    reported, not gated."""
    return n >= BLIND_N and measured_hits * BLIND_N >= TEMPO_BAR * n


def _pool(calibration):
    """Settled songs with an ISRC on one side of the calibration split, in uri order, each with
    its stored tempo (None when the export files disagreed and it was cleared)."""
    from . import library
    with library._tx() as con:
        tempo = dict(con.execute("SELECT uri, NULLIF(tempo, 0) FROM tracks").fetchall())
        settled = library.settled_tracks(con)
    return [{**s, "tempo": tempo.get(s["uri"])} for s in settled
            if s.get("isrc") and is_calibration(s["uri"]) == calibration]


def _with_truth(s):
    """s plus its benchmark tempo: Beatport by ISRC, else the stored tempo (kept only where every
    export file agreed), else None and the song is not sampled."""
    first = str(s.get("artists") or "").split(";")[0]
    bp = beatport_bpm(s["isrc"], f"{first} {s.get('name') or ''}".strip())
    if bp:
        return {**s, "truth": bp, "truth_source": "beatport"}
    return {**s, "truth": s["tempo"], "truth_source": "export"} if s.get("tempo") else None


def _sample(pool, n, seed, cap):
    import random
    from collections import Counter
    per, out = Counter(), []
    random.Random(seed).shuffle(pool)
    for s in pool:
        if len(out) == n:
            break
        if cap and not all(per[pl] < cap for pl in s["lists"]):
            continue
        s = _with_truth(s)
        if s:
            out.append(s)
            per.update(s["lists"])
    return out


def calibration_sample(n, seed=0):
    return _sample(_pool(True), n, seed, None)


def _blind_sample(n, seed, skip=()):
    return _sample([s for s in _pool(False) if s["uri"] not in skip], n, seed, PER_LIST_CAP)


def _score(s, pid, measure, songbpm=songbpm_bpm):
    """One song scored against its benchmark tempo (s["truth"], see _with_truth); the export's
    Spotify tempo never enters the vote. Reuses a stored
    reading for pid (the child never sees Spotify); measures only when there is none."""
    import numpy as np
    from . import library

    def latest():
        with library._tx() as con:
            r = con.execute("SELECT * FROM readings WHERE uri = ? AND pipeline_id = ? ORDER BY id DESC LIMIT 1",
                            (s["uri"], pid)).fetchone()
            fp = con.execute("SELECT vector FROM fingerprints WHERE uri = ? AND pipeline_id = ? "
                             "ORDER BY measured_at DESC LIMIT 1", (s["uri"], pid)).fetchone()
        return (dict(r) if r else None), fp

    r, fp = latest()
    if r is None:
        measure(s["uri"], spotify=False)
        r, fp = latest()
    p = {"uri": s["uri"], "lists": s["lists"], "spotify": s["tempo"], "truth": s["truth"],
         "truth_source": s["truth_source"], "status": r["status"] if r else "measure_failed",
         "reason": r["reason"] if r else "no reading stored", "measured_hit": False, "consensus_hit": False,
         "list_hit": False}
    if not r or r["status"] != "ok":
        return p
    votes = [(v["source"], v["bpm"]) for v in json.loads(r["votes"] or "[]") if v["source"] != "spotify"]
    v = vote(votes)
    nb = neighbours(np.frombuffer(fp[0], dtype=np.float32).tolist(), pid, exclude_isrcs=(s["isrc"],)) if fp else {}

    def near(bpm, other):
        return bool(bpm) and bool(other) and abs(fold_to(bpm, other) - other) <= FOLD_TOL

    def hit(bpm):
        return near(bpm, s["truth"])

    def second_opinion():
        """Beatport's own value is wrong on some songs. A measured miss stands unless a source
        other than the benchmark backs the measured tempo."""
        for src, bpm in votes:
            if src != "measured" and near(r["main_bpm"], bpm):
                return f"{src} {bpm}"
        bpm = songbpm(str(s.get("artists") or "").split(";")[0], s.get("name") or "")
        return f"songbpm {bpm}" if near(r["main_bpm"], bpm) else None

    if not hit(r["main_bpm"]):
        p["second_opinion"] = second_opinion()
    p.update(main_bpm=r["main_bpm"], consensus_bpm=v["consensus_bpm"], agreement=v["agreement"],
             votes=[{"source": a, "bpm": b} for a, b in votes], list_vote=nb.get("list_vote"),
             measured_hit=hit(r["main_bpm"]) or bool(p.get("second_opinion")), consensus_hit=hit(v["consensus_bpm"]),
             list_hit=nb.get("list_vote") in s["lists"], drops=json.loads(r["drops"] or "[]"))
    return p


def blind_test(n=BLIND_N, seed=20261027, measure=None, songbpm=songbpm_bpm):
    """Spec section 6: freeze the sample, score every song (a failure is a miss, never swapped),
    store one blind_tests row. Neighbours need the reference pass for this pipeline_id."""
    import time
    from collections import Counter
    from . import library
    measure = measure or (lambda uri, spotify: measure_track(uri, spotify=spotify))
    pid = pipeline_id()
    with library._tx() as con:
        seen = {u for (x,) in con.execute("SELECT sample FROM blind_tests WHERE pipeline_id = ?", (pid,))
                for u in json.loads(x or "[]")}  # a retest uses songs no earlier test scored
    sample = _blind_sample(n, seed, seen)
    with library._tx() as con:
        majority = Counter(pl for t in library.settled_tracks(con) for pl in t["lists"]).most_common(1)
        bid = con.execute("INSERT INTO blind_tests (run_at, pipeline_id, seed, sample, n) VALUES (?, ?, ?, ?, ?)",
                          (time.strftime("%Y-%m-%dT%H:%M:%S"), pid, seed, json.dumps([s["uri"] for s in sample]),
                           len(sample))).lastrowid
    preds = []
    for i, s in enumerate(sample, 1):
        preds.append(_score(s, pid, measure, songbpm))
        print(f"[{i}/{len(sample)}] {s['artists'].replace(';', ', ')} - {s['name']}: {preds[-1]['status']}", flush=True)
    c = {k: sum(p[k] for p in preds) for k in ("measured_hit", "consensus_hit", "list_hit")}
    res = {"identity_ok": sum(p["status"] == "ok" for p in preds), "measured_hits": c["measured_hit"],
           "consensus_hits": c["consensus_hit"], "list_hits": c["list_hit"],
           "baseline_hits": sum(bool(majority) and majority[0][0] in s["lists"] for s in sample), "n": len(sample)}
    res["passed"] = int(blind_passed(len(sample), res["measured_hits"]))
    with library._tx() as con:
        con.execute("UPDATE blind_tests SET predictions=?, identity_ok=?, measured_hits=?, consensus_hits=?, "
                    "list_hits=?, baseline_hits=?, passed=? WHERE id=?",
                    (json.dumps(preds), res["identity_ok"], res["measured_hits"], res["consensus_hits"],
                     res["list_hits"], res["baseline_hits"], res["passed"], bid))
    return {**res, "id": bid, "pipeline_id": pid, "misses": [p for p in preds if not p["measured_hit"]],
            "second_opinions": [p for p in preds if p.get("second_opinion")]}


def calibrate(n=30, seed=0, measure=None):
    """Measure n calibration-pool songs and print what each threshold did. The constants are set by
    hand from this table (ponytail: no auto-fit; 30 songs is too few to fit more than a glance)."""
    from collections import Counter
    measure = measure or (lambda uri, spotify: measure_track(uri, spotify=spotify))
    pid = pipeline_id()
    preds = [_score(s, pid, measure) for s in calibration_sample(n, seed)]
    unknown, nodrop = Counter(), 0
    for p in preds:
        d = p.get("drops") or []
        nodrop += p["status"] == "ok" and not d
        unknown.update(k for k, v in ((d[0].get("tellers") or {}) if d else {}).items() if v == "unknown")
        print(f"{p['status']:16} {p['truth_source']:8} {p['truth']:6.1f}  measured {p.get('main_bpm') or 0:6.1f}  "
              f"consensus {p.get('consensus_bpm') or 0:6.1f}  drops {len(d)}  {p['reason'] or ''}  {p['uri']}")
    ok = sum(p["status"] == "ok" for p in preds)
    print(f"pipeline {pid}: identity ok {ok}/{len(preds)}, measured hits {sum(p['measured_hit'] for p in preds)}, "
          f"consensus hits {sum(p['consensus_hit'] for p in preds)}, no drop {nodrop}, unknown tellers {dict(unknown)}")
    return preds
