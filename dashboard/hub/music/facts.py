"""Song fact sheet, system-Python half: version, validate, store, print.

The measuring child (facts_measure.py) runs in the listener venv; this module never imports it.
Spec: docs/specs/2026-11-02-song-fact-sheet-design.md (vault).
"""

import hashlib
import json
import re
import sqlite3
import subprocess
import os
import time
from pathlib import Path

from . import library, listener

FACTS_MEASURE_PY = Path(__file__).with_name("facts_measure.py")
CHILD_TIMEOUT_S = 3600  # whole-song Demucs on CPU, about 3-4 min measured per spec; 1 h is a hang

SECTION_COLS = (
    "bpm", "bpm_unsure", "tempo_moves", "beats_per_bar", "bar_share", "bars_used", "bars_other",
    "kick_slots", "kick_per_bar", "kick_off_grid", "snare_slots", "snare_per_bar", "snare_hits",
    "snare_off_grid", "hat_per_beat", "hat_present", "hat_off_grid", "swing_ratio", "swing_n",
    "swing_spread", "swing_band", "sub_share", "wobble_depth", "wobble_rate_hz", "wobble_per_beat",
    "vocal_share", "mean_burst_s", "bursts_per_s", "vocal_kind", "loud_db", "jump_db",
    "loud_slope_db_s", "bright_slope_hz_s", "fit_frames", "key", "mode", "key_strength")
REQUIRED = ("idx", "start_s", "end_s", "beat_ok", "drums_quiet") + SECTION_COLS
# Null allowed here only; everything else in REQUIRED must be a value.
NULLABLE = {
    "bpm", "bpm_unsure", "tempo_moves", "beats_per_bar", "bar_share", "bars_used", "bars_other",
    "kick_slots", "kick_per_bar", "kick_off_grid", "snare_slots", "snare_per_bar", "snare_hits",
    "snare_off_grid", "hat_per_beat", "hat_present", "hat_off_grid", "swing_ratio", "swing_n",
    "swing_spread", "swing_band", "sub_share", "wobble_depth", "wobble_rate_hz", "wobble_per_beat",
    "vocal_share", "mean_burst_s", "bursts_per_s", "vocal_kind", "jump_db", "loud_slope_db_s",
    "bright_slope_hz_s", "fit_frames", "key", "mode", "key_strength",
    "song_key", "song_mode", "song_key_strength"}
SHARES = ("bar_share", "sub_share", "vocal_share")
COUNTS = ("tempo_moves", "beats_per_bar", "bars_used", "bars_other", "kick_off_grid", "snare_hits",
          "snare_off_grid", "hat_off_grid", "swing_n", "fit_frames")
FLAGS = ("beat_ok", "drums_quiet", "hat_present", "bpm_unsure")
TEXT = ("swing_band", "vocal_kind", "key", "mode")
KINDS = {"none", "sung", "chopped", "unclear"}
EAR_PASS = 0.9  # a fact is ear-verified at this right / (right + wrong)


def facts_version():
    """16 hex over the child's source (its constants live there), listener_measure, the
    requirements, the key extractor settings and the device."""
    blob = json.dumps({
        "facts_measure": FACTS_MEASURE_PY.read_text(),  # FileNotFoundError when missing
        "listener_measure": listener.MEASURE_PY.read_text(),
        "req": listener.REQUIREMENTS.read_text(),
        "key": {"KeyExtractor": {"sampleRate": 22050, "profileType": "bgate"}},
        "device": "cuda" if listener.GPU_OK else "cpu"}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _num(v):
    return listener._finite(v)


def _flag(v):
    return isinstance(v, bool) or v in (0, 1) and not isinstance(v, float)


def _labels(n):
    return {x for i in range(1, n + 1) for x in (str(i), f"{i}&")}


def validate(r):
    """Problems with the child's JSON; empty means it may be stored."""
    if not isinstance(r, dict):
        return ["output is not an object"]
    dur = r.get("duration_s")
    if dur is None or not _num(dur) or dur <= 0:
        return ["duration not a positive number"]
    bad = []
    for k in ("song_key", "song_mode", "song_key_strength", "thresholds"):
        if k not in r:
            bad.append(f"missing {k}")
    if r.get("song_key_strength") is not None and not _num(r["song_key_strength"]):
        bad.append("song_key_strength not finite")
    secs = r.get("sections")
    if not isinstance(secs, list) or not secs:
        return bad + ["no sections"]
    edge = 0.0
    for n, s in enumerate(secs):
        if not isinstance(s, dict):
            bad.append(f"section {n} not an object")
            continue
        p = f"section {n}: "
        miss = [k for k in REQUIRED if k not in s]
        if miss:
            bad.append(p + "missing " + ", ".join(miss))
            continue
        bad += [p + f"{k} is null" for k in REQUIRED if s[k] is None and k not in NULLABLE]
        if s["idx"] != n or isinstance(s["idx"], bool):
            bad.append(p + f"idx {s['idx']!r} want {n}")
        a, b = s["start_s"], s["end_s"]
        if not (_num(a) and _num(b) and a < b):
            bad.append(p + "span not ordered")
        else:
            if abs(a - edge) > 0.05:
                bad.append(p + f"coverage {'hole' if a > edge else 'overlap'} {edge:.2f}-{a:.2f}")
            edge = b
        for k in FLAGS:
            if s[k] is not None and not _flag(s[k]):
                bad.append(p + f"{k} not 0/1")
        for k in SHARES:
            if s[k] is not None and not (_num(s[k]) and 0 <= s[k] <= 1):
                bad.append(p + f"{k} {s[k]!r} not in 0..1")
        for k in COUNTS:
            if s[k] is not None and not (isinstance(s[k], int) and not isinstance(s[k], bool) and s[k] >= 0):
                bad.append(p + f"{k} {s[k]!r} not a non-negative int")
        for k in SECTION_COLS:
            v = s[k]
            if v is None or k in FLAGS or k in COUNTS or k in TEXT or k.endswith("_slots"):
                continue
            if not _num(v):
                bad.append(p + f"{k} {v!r} not a finite number")
        if s["vocal_kind"] is not None and s["vocal_kind"] not in KINDS:
            bad.append(p + f"vocal_kind {s['vocal_kind']!r} unknown")
        for k in ("kick_slots", "snare_slots"):
            v = s[k]
            if v is None:
                continue
            bpb = s["beats_per_bar"]
            if not isinstance(v, dict):
                bad.append(p + f"{k} not an object")
            elif not (isinstance(bpb, int) and not isinstance(bpb, bool) and bpb >= 1):
                bad.append(p + f"{k} set without beats_per_bar")
            else:
                if set(v) != _labels(bpb):
                    bad.append(p + f"{k} keys are not the slots of a {bpb}-beat bar")
                if not all(isinstance(c, int) and not isinstance(c, bool) and c >= 0 for c in v.values()):
                    bad.append(p + f"{k} has a bad count")
    if abs(edge - dur) > 0.05:
        bad.append(f"coverage ends at {edge:.2f} of {dur:.2f}")
    return bad


def _child(path, out):
    env = {**os.environ, **({} if listener.GPU_OK else {"CUDA_VISIBLE_DEVICES": ""})}
    try:
        p = subprocess.run([str(listener.VENV_PY), str(FACTS_MEASURE_PY), "measure", str(path), "--out", str(out)],
                           env=env, capture_output=True, text=True, timeout=CHILD_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    except OSError as e:
        return -1, str(e)
    return p.returncode, (p.stderr.strip().splitlines() or [""])[-1]


def _resolve(con, target):
    row = con.execute("SELECT * FROM tracks WHERE uri = ?", (target,)).fetchone()
    if row:
        return dict(row)
    artist, sep, title = target.partition(" - ")
    if not sep:
        raise ValueError(f"no track with uri {target!r}; use a uri or 'Artist - Title'")
    a = artist.strip().lower()
    hits = [dict(r) for r in con.execute("SELECT * FROM tracks WHERE lower(name) = ?", (title.strip().lower(),))
            if a == (r["artists"] or "").lower() or a in [x.strip().lower() for x in (r["artists"] or "").split(";")]]
    if len(hits) != 1:
        found = "; ".join(f"{h['uri']} ({h['artists']} - {h['name']})" for h in hits)
        raise ValueError(f"{len(hits)} tracks match {target!r}" + (f": {found}" if hits else ""))
    return hits[0]


def _bit(v):
    return int(v) if isinstance(v, bool) else v  # other values reach the CHECK as given


def _store(con, uri, version, status, reason=None, ident=None, r=None):
    ident, now = ident or {}, time.strftime("%Y-%m-%dT%H:%M:%S")
    r = r or {}
    sid = con.execute(
        "INSERT INTO fact_sheets (uri, facts_version, measured_at, status, reason, video_id, recording_id, "
        "acoustid_score, audio_hash, duration_s, song_key, song_mode, song_key_strength, thresholds) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (uri, version, now, status, reason and reason[:300], ident.get("video_id"), ident.get("recording_id"),
         ident.get("acoustid_score"), ident.get("audio_hash"), r.get("duration_s"), r.get("song_key"),
         r.get("song_mode"), r.get("song_key_strength"),
         json.dumps(r["thresholds"]) if "thresholds" in r else None)).lastrowid
    for s in r.get("sections", []):
        row = {k: s[k] for k in REQUIRED}
        for k in ("kick_slots", "snare_slots"):
            row[k] = None if row[k] is None else json.dumps(row[k])
        for k in FLAGS:
            row[k] = _bit(row[k])
        cols = ", ".join(row)
        con.execute(f"INSERT INTO fact_sections (sheet_id, {cols}) VALUES (?{', ?' * len(row)})", (sid, *row.values()))
    return sid


def _failed(uri, version, status, reason, ident=None):
    with library._tx() as con:
        sid = _store(con, uri, version, status, reason, ident)
    return {"sheet_id": sid, "status": status, "reason": reason[:300]}


def describe(target, again=False, *, identify_fn=None, child=None):
    """Measure and store one song's fact sheet. Returns {"sheet_id", "status", "reason"};
    status "skipped" when an ok sheet for this version exists and again is false."""
    listener.sweep_stale()
    identify_fn, child = identify_fn or listener.identify, child or _child
    version = facts_version()
    with library._tx() as con:
        track = _resolve(con, target)
        uri = track["uri"]
        have = con.execute("SELECT id FROM fact_sheets WHERE uri = ? AND facts_version = ? AND status = 'ok' "
                           "ORDER BY id DESC LIMIT 1", (uri, version)).fetchone()
    if have and not again:
        return {"sheet_id": have["id"], "status": "skipped", "reason": "ok sheet exists for this version"}
    with listener.temp_run() as d:
        ident = identify_fn(track, workdir=d)
        if ident["status"] != "ok":
            return _failed(uri, version, "identity_failed", ident.get("reason") or "identity failed",
                           {k: ident.get(k) for k in ("video_id", "acoustid_score")})
        out = d / "facts.json"
        rc, err = child(ident["path"], out)
        if rc != 0 or not out.exists():
            return _failed(uri, version, "measure_failed", f"child exit {rc}: {err}", ident)
        try:
            r = json.loads(out.read_text())
        except ValueError as e:
            return _failed(uri, version, "measure_failed", f"child output is not JSON: {e}", ident)
    problems = validate(r)
    if problems:
        return _failed(uri, version, "measure_failed", "invalid: " + "; ".join(problems), ident)
    try:
        with library._tx() as con:
            sid = _store(con, uri, version, "ok", None, ident, r)
    except sqlite3.Error as e:  # the transaction rolled back whole: no sheet, no sections
        return _failed(uri, version, "measure_failed", f"store failed: {e}", ident)
    return {"sheet_id": sid, "status": "ok", "reason": None}


# --- printout ---

WIDTH = 140


def _t(s):
    return f"{int(s) // 60}:{int(s) % 60:02d}"


STEADY_SHARE = 0.5  # a slot is part of the pattern when it is hit in at least this share of the bars


def _hit_list(slots, bars):
    """The slots hit in most bars, in bar order ("2" < "2e" < "2&" < "2a"); stored counts keep the rest."""
    def order(k):
        return int(re.sub(r"\D", "", k)), "0e&a".find(k[-1]) if not k[-1].isdigit() else 0
    if not any(slots.values()):
        return "no hits"
    steady = [k for k in sorted(slots, key=order) if slots[k] >= max(1, STEADY_SHARE * (bars or 0))]
    return " ".join(steady) or "scattered"


def _slots(name, slots, per_bar, tilde, bars):
    if slots is None:
        return f"{name} none"
    return f"{name} {tilde}{_hit_list(slots, bars)}" + (f" ({tilde}{per_bar:.1f}/bar)" if per_bar is not None else "")


def _facts(s):
    w = "" if s["beat_ok"] else "~"
    f = []
    if s["bpm"] is not None:
        f.append(f"tempo {s['bpm']:.1f}" + ("?" if s["bpm_unsure"] else "") + f" moves {s['tempo_moves']}")
    else:
        f.append("tempo none")
    if s["beats_per_bar"] is not None:
        f.append(f"meter {w}{s['beats_per_bar']}/bar ({s['bar_share']:.0%} of {s['bars_used'] + s['bars_other']} bars)")
    else:
        f.append("meter none")
    f.append("drums quiet" if s["drums_quiet"] else "")
    f.append(_slots("kick band", s["kick_slots"], s["kick_per_bar"], w, s["bars_used"]))
    f.append(_slots("snare band", s["snare_slots"], s["snare_per_bar"], w, s["bars_used"]))
    if s["hat_per_beat"] is not None:
        f.append(f"hats band {w}{s['hat_per_beat']:.1f}/beat" if s["hat_present"] else "hats band none")
    if s["swing_ratio"] is not None:
        f.append(f"swing {w}{s['swing_ratio']:.2f} (n {s['swing_n']}, {s['swing_band']} band)")
    if s["sub_share"] is not None:
        f.append(f"sub {s['sub_share']:.0%}")
    if s["wobble_rate_hz"] is not None:
        f.append(f"wobble {s['wobble_rate_hz']:.1f} Hz depth {s['wobble_depth']:.2f}"
                 + (f" ({w}{s['wobble_per_beat']:.2f}/beat)" if s["wobble_per_beat"] is not None else ""))
    if s["vocal_kind"] is not None:
        f.append(f"vocals {s['vocal_kind']} ({s['vocal_share']:.0%})" if s["vocal_share"] is not None
                 else f"vocals {s['vocal_kind']}")
    if s["loud_db"] is not None:
        f.append(f"loud {s['loud_db']:.1f} dB"
                 + (f" jump {s['jump_db']:+.1f}" if s["jump_db"] is not None else "")
                 + (f" slope {s['loud_slope_db_s']:+.2f} dB/s" if s["loud_slope_db_s"] is not None else "")
                 + (f" bright {s['bright_slope_hz_s']:+.0f} Hz/s" if s["bright_slope_hz_s"] is not None else ""))
    if s["key"] is not None:
        f.append(f"key {s['key']} {s['mode']}")
    return [x for x in f if x]


def print_sheet(sheet_id):
    with library._tx() as con:
        sh = con.execute("SELECT f.*, t.name, t.artists FROM fact_sheets f JOIN tracks t ON t.uri = f.uri "
                         "WHERE f.id = ?", (sheet_id,)).fetchone()
        if sh is None:
            raise ValueError(f"no sheet {sheet_id}")
        secs = [dict(r) for r in con.execute("SELECT * FROM fact_sections WHERE sheet_id = ? ORDER BY idx", (sheet_id,))]
        checks = con.execute("SELECT fact, SUM(right) r, SUM(wrong) w FROM fact_checks WHERE facts_version = ? "
                             "GROUP BY fact", (sh["facts_version"],)).fetchall()
    for s in secs:
        for k in ("kick_slots", "snare_slots"):
            s[k] = json.loads(s[k]) if s[k] else None
    song = f"{sh['artists']} - {sh['name']}"
    if sh["status"] != "ok":
        return f"{song}  [{sh['status']}] {sh['reason'] or ''}  (facts {sh['facts_version']})"
    ok = sorted(c["fact"] for c in checks if c["r"] + c["w"] and c["r"] / (c["r"] + c["w"]) >= EAR_PASS)
    key = f"{sh['song_key']} {sh['song_mode']}" if sh["song_key"] else "key unknown"
    lines = [f"{song}  {_t(sh['duration_s'])}  {key}  facts {sh['facts_version']}  "
             f"ear-verified: {', '.join(ok) or 'none yet'}"]
    for s in secs:
        head = f"part {s['idx'] + 1}  {_t(s['start_s'])}-{_t(s['end_s'])}  "
        cur = head
        for x in _facts(s):
            if len(cur) + len(x) > WIDTH and cur.strip() and cur != head:
                lines.append(cur.rstrip(" |"))
                cur = "    "
            cur += x + " | "
        lines.append(cur.rstrip(" |"))
    return "\n".join(lines)


# --- ear check ---

# code -> fact name stored in fact_checks
EAR_CODES = {"T": "tempo", "M": "meter", "K": "kick", "S": "snare", "H": "hats", "W": "swing",
             "B": "wobble", "V": "vocal kind", "J": "energy jump", "C": "climbing"}
SWUNG_AT = 1.25  # swing ratio from here reads "swung", below "straight"
JUMP_DB = 1.0  # energy jump size an ear hears as louder or quieter
CLIMB_DB_S = 0.05  # loudness slope that reads as getting louder
CLIMB_HZ_S = 20.0  # brightness slope that reads as getting brighter


def _ear_cells(s):
    """One short cell per ear code for a section dict (slots already decoded)."""
    w = "" if s["beat_ok"] else "~"
    c = {}
    c["T"] = ("none" if s["bpm"] is None else f"{s['bpm']:.1f} bpm" + ("?" if s["bpm_unsure"] else "")
              + (f", changes {s['tempo_moves']}" if s["tempo_moves"] else ", steady"))
    c["M"] = "none" if s["beats_per_bar"] is None else f"{w}{s['beats_per_bar']} beats per bar"
    for code, name in (("K", "kick"), ("S", "snare")):
        slots, per = s[f"{name}_slots"], s[f"{name}_per_bar"]
        c[code] = ("drums quiet" if s["drums_quiet"] else f"{name} none" if slots is None
                   else f"{w}{per:.1f}/bar: {name} {_hit_list(slots, s['bars_used'])}")
    c["H"] = ("drums quiet" if s["drums_quiet"] else "none" if s["hat_per_beat"] is None
              else f"{w}{s['hat_per_beat']:.1f} hits/beat" if s["hat_present"] else "no hats")
    c["W"] = ("none" if s["swing_ratio"] is None else
              f"{w}{s['swing_ratio']:.2f}: {'swung' if s['swing_ratio'] >= SWUNG_AT else 'straight'}")
    c["B"] = "no wobble" if s["wobble_rate_hz"] is None else f"{s['wobble_rate_hz']:.1f} Hz: wobble"
    c["V"] = s["vocal_kind"] or "none"
    j = s["jump_db"]
    c["J"] = ("none" if j is None else f"{j:+.1f} dB: " + ("louder" if j >= JUMP_DB else "quieter" if j <= -JUMP_DB else "same"))
    d, b = s["loud_slope_db_s"], s["bright_slope_hz_s"]
    c["C"] = ("none" if d is None and b is None else
              f"{'louder' if (d or 0) >= CLIMB_DB_S else 'not louder'}, {'brighter' if (b or 0) >= CLIMB_HZ_S else 'not brighter'}")
    return c


def ear_sheet(uris, path):
    """Write the markdown ear check for each uri's newest ok sheet of the current facts version."""
    version, parts, ids = facts_version(), [], []
    with library._tx() as con:
        for uri in uris:
            sh = con.execute("SELECT f.id, f.duration_s, t.name, t.artists FROM fact_sheets f JOIN tracks t ON t.uri = f.uri "
                             "WHERE f.uri = ? AND f.facts_version = ? AND f.status = 'ok' ORDER BY f.id DESC LIMIT 1",
                             (uri, version)).fetchone()
            if sh is None:
                raise ValueError(f"no ok sheet for {uri} at facts version {version}")
            ids.append(sh["id"])
            parts += [f"## {sh['artists']} - {sh['name']} (sheet {sh['id']}, {_t(sh['duration_s'])})", "",
                      "| Section | Span | " + " | ".join(f"{k} {v}" for k, v in EAR_CODES.items()) + " | Mark |",
                      "|" + "---|" * (len(EAR_CODES) + 3)]
            for r in con.execute("SELECT * FROM fact_sections WHERE sheet_id = ? ORDER BY idx", (sh["id"],)):
                s = dict(r)
                for k in ("kick_slots", "snare_slots"):
                    s[k] = json.loads(s[k]) if s[k] else None
                cells = _ear_cells(s)
                parts.append(f"| {s['idx'] + 1} | {_t(s['start_s'])}-{_t(s['end_s'])} | "
                             + " | ".join(cells[k] for k in EAR_CODES) + " | |")
            parts.append("")
    head = ["# Song fact sheet ear check", "",
            f"- facts_version: {version}", f"- sheet_ids: {json.dumps(ids)}",
            "- codes: " + ", ".join(f"{k} {v}" for k, v in EAR_CODES.items()), "",
            "Mark every row. `+` = every fact in the row is right. `- K S` = those codes are wrong. "
            "Add `? W` for codes you could not judge (`- K ? W`). `~` marks numbers that depend on a shaky beat.", ""]
    Path(path).write_text("\n".join(head + parts))


def _marks(mark, where):
    """(wrong codes, unsure codes) for one Mark cell."""
    mark = mark.strip()
    if mark == "+":
        return set(), set()
    if not mark.startswith(("-", "?")):
        raise ValueError(f"{where}: mark {mark!r} is empty or not + / - / ?")
    wrong, _, unsure = mark.lstrip("-").partition("?")
    sets = []
    for chunk in (wrong, unsure):
        codes = re.sub(r"[\s,]", "", chunk).upper()
        bad = sorted({c for c in codes if c not in EAR_CODES})
        if bad:
            raise ValueError(f"{where}: unknown code {', '.join(bad)} in {mark!r}")
        sets.append(set(codes))
    if "?" in unsure or not (sets[0] or sets[1]) or sets[0] & sets[1]:
        raise ValueError(f"{where}: mark {mark!r} names no code, repeats one or has two '?'")
    return sets[0], sets[1]


def ear_score(path):
    """Score a filled ear sheet, store one fact_checks row per fact, return {fact: {right, wrong, unsure}}."""
    text = Path(path).read_text()
    m = re.search(r"^- facts_version: (\w+)$", text, re.M)
    n = re.search(r"^- sheet_ids: (\[.*\])$", text, re.M)
    if not (m and n):
        raise ValueError("ear sheet header lacks facts_version or sheet_ids")
    tally = {name: {"right": 0, "wrong": 0, "unsure": 0} for name in EAR_CODES.values()}
    song, rows = "?", 0
    for line in text.splitlines():
        if line.startswith("## "):
            song = line[3:]
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.startswith("|") else []
        if not cells or not cells[0].isdigit():
            continue
        rows += 1
        wrong, unsure = _marks(cells[-1], f"{song} section {cells[0]}")
        for code, name in EAR_CODES.items():
            tally[name]["wrong" if code in wrong else "unsure" if code in unsure else "right"] += 1
    if not rows:
        raise ValueError("ear sheet has no section rows")
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    with library._tx() as con:
        for name, t in tally.items():
            con.execute("INSERT INTO fact_checks (facts_version, fact, right, wrong, unsure, sheet_ids, checked_at) "
                        "VALUES (?,?,?,?,?,?,?)", (m.group(1), name, t["right"], t["wrong"], t["unsure"], n.group(1), now))
    return tally
