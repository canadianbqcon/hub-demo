"""Song fact sheet, the venv half: numpy arithmetic for meter, drum slots and onsets.

Pure functions only here; the model imports (librosa, torch, essentia, beat_this) arrive inside later
functions so tests and the Hub can import this file without them.
Design: vault docs/specs/2026-11-02-song-fact-sheet-design.md.
"""

import argparse
import json
import sys
import traceback
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))  # run as a child script from the music folder
from listener_measure import (  # noqa: E402,F401  (_hits is not reused: it asks per grid slot, we need onsets)
    CHOP_BURST_S, CHOP_RATE, HOLD_BEATS, SR, SUNG_BURST_S, SUNG_SHARE,
    _band_flux, _bpm, _change_points, _runs, _madmom_beats, _stems, _stft, tempo_intervals)

HIT_FRAC = 0.3  # an onset is band flux at least this share of the stem's biggest
# Absolute flux floor per FFT bin of the band: white noise stepping on at -50 dBFS RMS measured 0.04 per bin
# (Hann 2048 frame, any rate), so 0.05 rejects stem bleed at -50 dBFS however small the stem's own peak.
ONSET_FLOOR = 0.05
STEM_FLOOR_DB = -50.0  # a stem slice quieter than this RMS dBFS counts as silent
HAT_MIN = 0.5  # hat hits per beat at or above this means hats are present
MIN_ONSET_GAP_S = 0.05  # two onsets closer than this are one

SWING_MIN_N = 8  # fewer qualifying off-beats than this and swing is not reported
WOBBLE_PROM = 20.0  # wobble peak power must be this many times the median modulation power (white noise peaks near 7x)
WOBBLE_MIN_DEPTH = 0.01  # depth under this is STFT ripple (a steady 50 Hz sine aliases to 14 Hz at depth 0.0004), no rate
VOCAL_REL_DB = -30.0  # a vocal frame counts as on at this many dB under the song's loudest vocal frame (negative)
VOCAL_MIN_SHARE = 0.05  # vocal share under this is "none"
SNAP_S = 2.0  # a raw section boundary moves to a downbeat this close
BEAT_SNAP_S = 1.0  # no downbeat in reach: moves to a beat this close
MIN_SECTION_S = 4.0  # a section shorter than this merges into its shorter neighbour
SECTION_S = 20  # librosa segmentation target: about one section per 20 s
MIN_SECTIONS = 2  # fewest librosa segments asked for
MAX_SECTIONS = 16  # most librosa segments asked for
VOCAL_GAP_S = 0.15  # vocal gaps shorter than this are one burst
VOCAL_ABS_DB = -100.0  # a frame must also beat this, so a silent stem never counts as on

BANDS = {"kick": (20, 120), "snare": (1000, 4000), "hats": (6000, 16000)}


def onsets(flux, frame_s, floor):
    """Times (s) of flux local maxima at least MIN_ONSET_GAP_S apart, above HIT_FRAC * max and floor."""
    flux = np.asarray(flux, dtype=float)
    if len(flux) < 3:
        return np.zeros(0)
    bar = max(HIT_FRAC * flux.max(), floor)
    left = np.concatenate([[-1.0], flux[:-1]])
    right = np.concatenate([flux[1:], [-1.0]])
    cand = np.flatnonzero((flux > bar) & (flux >= left) & (flux > right))
    keep = []
    for k in cand[np.argsort(-flux[cand], kind="stable")]:  # strongest first wins a crowded stretch
        if all(abs(k - j) * frame_s >= MIN_ONSET_GAP_S for j in keep):
            keep.append(k)
    return np.sort(np.array(keep, dtype=float)) * frame_s


def band_onsets(drums, sr):
    """Kick, snare and hats onset times over the whole stem, plus its overall RMS dBFS."""
    x = np.asarray(drums, dtype=np.float32)
    S, f, fs = _stft(x, sr)
    rms = float(np.sqrt(np.mean(x.astype(float) ** 2))) if len(x) else 0.0
    out = {name: onsets(_band_flux(S, f, lo, hi), fs, ONSET_FLOOR * ((f >= lo) & (f < hi)).sum()) + 1024 / sr
           for name, (lo, hi) in BANDS.items()}  # + 1024 / sr: frame centre, not its start
    out["drums_db"] = float(20 * np.log10(rms)) if rms > 0 else float("-inf")
    return out


def meter(beats, downbeats, s, e):
    """Most common beats-per-bar over complete bars (downbeat to next downbeat, both inside [s, e))."""
    beats = np.asarray(beats, dtype=float)
    db = np.asarray(downbeats, dtype=float)
    db = db[(db >= s) & (db < e)]
    bars = [(float(a), [float(t) for t in beats[(beats >= a) & (beats < b)]]) for a, b in zip(db, db[1:])]
    if not bars:
        return {"beats_per_bar": None, "bar_share": None, "bars_used": 0, "bars_other": 0, "bars": []}
    counts = Counter(len(b) for _, b in bars)
    n, used = counts.most_common(1)[0]  # ties go to the first count seen
    return {"beats_per_bar": n, "bar_share": used / len(bars), "bars_used": used,
            "bars_other": len(bars) - used, "bars": [b for b in bars if len(b[1]) == n]}


def _labels(n, per_beat):
    sub = ["", "&"] if per_beat == 2 else ["", "e", "&", "a"]
    return [f"{i + 1}{s}" for i in range(n) for s in sub]


def slot_facts(times, bars, per_beat):
    """Place onsets on the nearest slot of each bar's grid, one onset per slot per bar."""
    if not bars:
        return {"slots": None, "per_bar": None, "off_grid": 0, "hits": 0}
    labels = _labels(len(bars[0][1]), per_beat)
    slots = dict.fromkeys(labels, 0)
    st, sw, sb, sl, spans = [], [], [], [], []
    for bi, (start, bt) in enumerate(bars):
        # ponytail: the bar's last beat borrows the previous beat's length (bars carry no next-bar start)
        ivs = list(np.diff(bt)) + [np.diff(bt)[-1] if len(bt) > 1 else 0.5]
        for t0, iv in zip(bt, ivs):
            for j in range(per_beat):
                st.append(t0 + j * iv / per_beat); sw.append(iv / per_beat); sb.append(bi)
        sl += labels
        spans.append((start, bt[-1] + ivs[-1]))
    st, sw = np.array(st), np.array(sw)
    taken, hits, off = set(), 0, 0
    for t in np.sort(np.asarray(times, dtype=float)):
        k = int(np.argmin(np.abs(st - t)))
        if abs(st[k] - t) <= sw[k] / 2:
            key = (sb[k], k)
            if key in taken:
                off += 1
            else:
                taken.add(key)
                slots[sl[k]] += 1
                hits += 1
        elif any(a <= t < b for a, b in spans):
            off += 1
    return {"slots": slots, "per_bar": hits / len(bars), "off_grid": off, "hits": hits}


def drum_facts(onsets_by_band, beats, downbeats, s, e, drums_quiet):
    """Meter, kick, snare and hats columns for one section [s, e)."""
    m = meter(beats, downbeats, s, e)

    def cut(name):
        if drums_quiet:
            return np.zeros(0)
        t = np.asarray(onsets_by_band[name], dtype=float)
        return t[(t >= s) & (t < e)]

    kick = slot_facts(cut("kick"), m["bars"], 2)
    snare = slot_facts(cut("snare"), m["bars"], 2)
    hats = slot_facts(cut("hats"), m["bars"], 4)
    n_beats = m["bars_used"] * (m["beats_per_bar"] or 0)
    hpb = hats["hits"] / n_beats if n_beats else None
    return {"kick_slots": kick["slots"], "kick_per_bar": kick["per_bar"], "kick_off_grid": kick["off_grid"],
            "snare_slots": snare["slots"], "snare_per_bar": snare["per_bar"], "snare_hits": snare["hits"],
            "snare_off_grid": snare["off_grid"],
            "hat_per_beat": hpb, "hat_present": None if hpb is None else int(hpb >= HAT_MIN),
            "hat_off_grid": hats["off_grid"],
            "beats_per_bar": m["beats_per_bar"], "bar_share": m["bar_share"],
            "bars_used": m["bars_used"], "bars_other": m["bars_other"]}


def swing(hat_times, snare_times, beats, s, e):
    """Swing ratio p/(1-p) from beats holding exactly one onset 35-80% of the way through, in [s, e)."""
    beats = np.asarray(beats, dtype=float)

    def ratios(times):
        times = np.asarray(times, dtype=float)
        out = []
        for a, b in zip(beats, beats[1:]):
            if a < s or b >= e:
                continue
            p = (times[(times > a) & (times < b)] - a) / (b - a)
            p = p[(p >= 0.35) & (p <= 0.8)]
            if len(p) == 1:
                out.append(p[0] / (1 - p[0]))
        return out

    for band, times in (("hats", hat_times), ("snare", snare_times)):
        r = ratios(times)
        if len(r) >= SWING_MIN_N:
            q1, q3 = np.percentile(r, [25, 75])
            return {"swing_ratio": float(np.median(r)), "swing_n": len(r), "swing_spread": float(q3 - q1),
                    "swing_band": band}
    return {"swing_ratio": None, "swing_n": len(r), "swing_spread": None, "swing_band": None}


def bass_facts(bass_slice, sr, beats):
    """Sub-bass share and wobble of a bass stem slice."""
    x = np.asarray(bass_slice, dtype=np.float32)
    null = {"sub_share": None, "wobble_depth": None, "wobble_rate_hz": None, "wobble_per_beat": None}
    rms = float(np.sqrt(np.mean(x.astype(float) ** 2))) if len(x) else 0.0
    if rms <= 0 or 20 * np.log10(rms) < STEM_FLOOR_DB:
        return null
    S, f, fs = _stft(x, sr)
    power = (S ** 2).sum(0)
    out = dict(null, sub_share=float((S[f < 100] ** 2).sum() / (S ** 2).sum()))
    env = np.sqrt(power)
    k = max(1, int(round(2 / fs)))
    ma = np.convolve(np.pad(env, (k // 2, k - 1 - k // 2), mode="edge"), np.ones(k) / k, "valid")
    res = env - ma
    # depth = std(residual) / mean(envelope): the 2 s average carries the song's slow level, the residual the wobble
    out["wobble_depth"] = float(res.std() / env.mean())
    m = np.abs(np.fft.rfft((res - res.mean()) * np.hanning(len(res)))) ** 2
    mf = np.fft.rfftfreq(len(res), fs)
    band = (mf >= 0.5) & (mf <= 16)
    if out["wobble_depth"] >= WOBBLE_MIN_DEPTH and band.any() and m[band].max() >= WOBBLE_PROM * max(np.median(m[band]), 1e-30):
        hz = float(mf[band][np.argmax(m[band])])
        if len(res) * fs * hz >= 4:
            out["wobble_rate_hz"] = hz
            bpm = _bpm(beats) if beats is not None and len(beats) > 1 else None
            out["wobble_per_beat"] = hz * 60 / bpm if bpm else None
    return out


def _frame_db(x):
    x = np.asarray(x, dtype=np.float32)
    if len(x) < 2048:
        x = np.pad(x, (0, 2048 - len(x)))
    fr = np.lib.stride_tricks.sliding_window_view(x, 2048)[::512]
    return 20 * np.log10(np.sqrt((fr.astype(float) ** 2).mean(1)) + 1e-6)


def peak_db(x, sr):
    """Loudest frame RMS dBFS of a whole stem."""
    return float(_frame_db(x).max())


def vocal_facts(vocal_slice, sr, song_peak_db):
    """Vocal share and burst shape of a vocal stem slice, against the whole song's loudest vocal frame."""
    fs = 512 / sr
    db = _frame_db(vocal_slice)
    on = (db >= song_peak_db + VOCAL_REL_DB) & (db > VOCAL_ABS_DB)
    idx = np.flatnonzero(on)
    if len(idx):  # fill gaps shorter than VOCAL_GAP_S between on frames
        for a, b in zip(idx, idx[1:]):
            if 1 < b - a and (b - a - 1) * fs < VOCAL_GAP_S:
                on[a:b] = True
    runs, k = [], 0
    for v in list(on) + [False]:
        if v:
            k += 1
        elif k:
            runs.append(k * fs)
            k = 0
    share = float(on.mean())
    mean_b = float(np.mean(runs)) if runs else 0.0
    rate = len(runs) / (len(on) * fs)
    if share < VOCAL_MIN_SHARE:
        kind = "none"
    elif share >= SUNG_SHARE and mean_b >= SUNG_BURST_S:
        kind = "sung"
    elif mean_b < CHOP_BURST_S and rate >= CHOP_RATE:
        kind = "chopped"
    else:
        kind = "unclear"
    return {"vocal_share": share, "mean_burst_s": mean_b, "bursts_per_s": float(rate), "vocal_kind": kind}


def _mono(mix):
    x = np.asarray(mix, dtype=np.float32)
    return x.mean(axis=0 if x.shape[0] <= 8 else 1) if x.ndim == 2 else x


def energy_facts(mix, sr, s, e, prev_tail_db):
    """Loudness, jump from the previous section's tail, and loudness and brightness slopes for [s, e)."""
    from scipy.ndimage import median_filter
    x = _mono(mix)[int(s * sr):int(e * sr)]
    db = _frame_db(x)
    fs = 512 / sr
    out = {"loud_db": float(db.mean()), "jump_db": None, "loud_slope_db_s": None, "bright_slope_hz_s": None,
           "fit_frames": len(db)}
    if prev_tail_db is not None:
        out["jump_db"] = float(db[:max(1, int(4 / fs))].mean() - prev_tail_db)
    if len(x) >= 2 * sr:
        fr = np.lib.stride_tricks.sliding_window_view(x, 2048)[::512] * np.hanning(2048)
        mag = np.abs(np.fft.rfft(fr, axis=1))
        cen = (mag * np.fft.rfftfreq(2048, 1 / sr)).sum(1) / (mag.sum(1) + 1e-9)
        w = max(1, int(round(1 / fs)))
        t = np.arange(len(db)) * fs
        out["loud_slope_db_s"] = float(np.polyfit(t, median_filter(db, size=w), 1)[0])
        out["bright_slope_hz_s"] = float(np.polyfit(t, median_filter(cen, size=w), 1)[0])
    return out


def tail_db(mix, sr, e):
    """Mean dB of the 4 s before e."""
    x = _mono(mix)[max(0, int((e - 4) * sr)):int(e * sr)]
    return float(_frame_db(x).mean())


def snap_sections(raw_bounds, beats, downbeats, duration):
    """Snap inner boundaries to downbeats, then beats, drop duplicates, merge sections under MIN_SECTION_S."""
    beats = np.asarray(beats, dtype=float)
    downs = np.asarray(downbeats, dtype=float)

    def near(grid, t, reach):
        if not len(grid):
            return None
        g = grid[np.argmin(np.abs(grid - t))]
        return float(g) if abs(g - t) <= reach else None

    inner = set()
    for t in raw_bounds:
        t = float(t)
        v = near(downs, t, SNAP_S)
        v = near(beats, t, BEAT_SNAP_S) if v is None else v
        v = t if v is None else v
        if 0.0 < v < duration:
            inner.add(v)
    edges = [0.0] + sorted(inner) + [float(duration)]
    while len(edges) > 2:
        lens = np.diff(edges)
        i = int(np.argmin(lens))
        if lens[i] >= MIN_SECTION_S:
            break
        if i == 0:
            drop = 1
        elif i == len(lens) - 1:
            drop = i
        else:
            drop = i if lens[i - 1] <= lens[i + 1] else i + 1  # merge into the shorter neighbour
        del edges[drop]
    return list(zip(edges, edges[1:]))


def section_tempo(beats_a, beats_b, s, e):
    """BPM, unsure flag and in-run tempo moves for the beats of track a inside [s, e)."""
    null = {"bpm": None, "bpm_unsure": None, "tempo_moves": None}
    a = np.asarray(beats_a, dtype=float)
    b = np.asarray(beats_b, dtype=float)
    a = a[(a >= s) & (a < e)] - s
    b = b[(b >= s) & (b < e)] - s
    if len(a) < 2:
        return null
    runs, _ = _runs(a, e - s)
    if not runs:
        return null
    ivs = tempo_intervals(a, b, [(0.0, e - s, "x")], e - s)["intervals"]
    if not ivs:
        return null
    w = np.array([i["end"] - i["start"] for i in ivs])
    bpm = float(np.average([i["folded_bpm"] for i in ivs], weights=w)) if w.sum() > 0 else ivs[0]["folded_bpm"]
    unsure = any(i["unsure"] and (i["end"] - i["start"]) > (e - s) / 2 for i in ivs)
    moves = sum(len(_change_points(a[r[0]:r[-1] + 1])) for r in runs if len(r) >= HOLD_BEATS + 1)
    return {"bpm": bpm, "bpm_unsure": int(unsure), "tempo_moves": moves}


# --- the models (imported only inside these functions, never at module load) ---

def thresholds():
    """Every upper-case constant of this module (imported ones included), JSON-safe."""
    return {k: _py(v) for k, v in sorted(globals().items()) if k.isupper() and not k.startswith("_")}


def _py(v):
    """numpy values and tuples to plain JSON types; non-finite floats to None."""
    if isinstance(v, dict):
        return {str(k): _py(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, np.ndarray)):
        return [_py(x) for x in v]
    if isinstance(v, (np.bool_, bool)):
        return int(v) if isinstance(v, np.bool_) else v
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return float(v) if np.isfinite(v) else None
    return v


def _db(x):
    x = np.asarray(x, dtype=float)
    rms = float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0
    return 20 * np.log10(rms) if rms > 0 else float("-inf")


def _key(extractor, y):
    """(key, mode, strength) of a mix slice, or all None when it is under STEM_FLOOR_DB."""
    if _db(y) < STEM_FLOOR_DB:
        return None, None, None
    k, mode, strength = extractor(np.asarray(y, dtype=np.float32))
    return k, mode, float(strength)


def measure(path):
    import librosa
    from beat_this.inference import File2Beats
    from essentia.standard import KeyExtractor
    y, _ = librosa.load(path, sr=SR, mono=True)
    duration = len(y) / SR
    beats, downbeats = File2Beats(checkpoint_path="final0", device="cpu", dbn=False)(path)
    second = _madmom_beats(y)
    stems = _stems(path, 0, None)
    sr2 = 44100
    drums, bass, vocals = stems["drums"], stems["bass"], stems["vocals"]
    bo = band_onsets(drums, sr2)
    voc_peak = peak_db(vocals, sr2)
    # sections: librosa agglomerative on chroma + mfcc, snapped to the downbeats
    S = np.abs(librosa.stft(y, hop_length=512))
    feats = np.vstack([librosa.feature.chroma_stft(S=S, sr=SR), librosa.feature.mfcc(S=librosa.power_to_db(S ** 2), sr=SR)])
    k = int(min(MAX_SECTIONS, max(MIN_SECTIONS, round(duration / SECTION_S))))
    raw = librosa.frames_to_time(librosa.segment.agglomerative(feats, k), sr=SR, hop_length=512)
    secs = snap_sections(raw[1:], beats, downbeats, duration)
    extractor = KeyExtractor(sampleRate=SR, profileType="bgate")
    song_key, song_mode, song_strength = _key(extractor, y)
    out, prev_tail = [], None
    for i, (s, e) in enumerate(secs):
        a, b = int(s * sr2), int(e * sr2)
        quiet = _db(drums[a:b]) < STEM_FLOOR_DB
        row = {"idx": i, "start_s": s, "end_s": e}
        row.update(section_tempo(beats, second, s, e))
        row.update(drum_facts(bo, beats, downbeats, s, e, quiet))
        row.update(swing(bo["hats"], bo["snare"], beats, s, e))
        row.update(bass_facts(bass[a:b], sr2, [t for t in beats if s <= t < e]))
        row.update(vocal_facts(vocals[a:b], sr2, voc_peak))
        row.update(energy_facts(y, SR, s, e, prev_tail))
        prev_tail = tail_db(y, SR, e)
        row["key"], row["mode"], row["key_strength"] = _key(extractor, y[int(s * SR):int(e * SR)])
        row["drums_quiet"] = int(quiet)
        row["beat_ok"] = int(row["bpm"] is not None and not row["bpm_unsure"] and row["bars_used"] >= 2)
        out.append(row)
    return _py({"duration_s": duration, "song_key": song_key, "song_mode": song_mode,
                "song_key_strength": song_strength, "thresholds": thresholds(), "sections": out})


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("measure")
    m.add_argument("audio")
    m.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        out = measure(a.audio)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 1
    with open(a.out, "w") as f:
        json.dump(out, f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
