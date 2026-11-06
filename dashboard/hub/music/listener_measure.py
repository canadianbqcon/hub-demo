"""Song listener, the venv half: one audio file in, one JSON reading out.

Runs only in ~/.venvs/listener (Python 3.11, torch, Beat This!, Demucs, Essentia). listener.py calls it
as a child so the Hub's Python never loads the ML stack. JSON goes to --out only: the libraries print
banners and progress bars on stdout. Design: vault docs/specs/2026-10-27-song-listener-design.md.

  python listener_measure.py measure <audio> --out <json>
  python listener_measure.py search "<artist> <title>" --out <json>

The helpers above main() are pure numpy so the tests can run them without loading a model.
"""

import argparse
import json
import sys
import traceback
from statistics import median

import numpy as np

GAP_S = 4.0  # no beat for this long is a beatless gap, stored with no BPM
CHANGE_BPM = 2.0  # a raw tempo move past this, held HOLD_BEATS, splits an interval
HOLD_BEATS = 8
UNSURE_BPM = 2.0  # the two beat tracks disagreeing past this (folded) marks an interval unsure
MIN_SPLIT_BEATS = 4  # a section boundary splits an interval only when both sides keep this many beats
DROP_SKIP = 0.15  # calibrated: Task 8. No drop is picked inside the first 15% of the song
DROP_BAR = 1.0  # calibrated: Task 8. The drop must score this far above the median section
DROP_MIN_BARS = 8
RMS_SD_FLOOR = 1.5  # calibrated: Task 8. dB; section loudness spread below this counts as flat
SUB_SD_FLOOR = 1.5  # calibrated: Task 8. dB
SUB_HZ = 120
LATER_DROP_GAP = 1.0  # calibrated: Task 8. a later drop scores within this of the top one
DROP_BASE_Q = 0.25  # calibrated: Task 8. the drop bar is measured from the song's quieter quarter
# Drop tellers. Values are what check compares; "unknown" when no threshold is met.
TELLER_LABELS = {"drums": {"four-on-the-floor", "half-time", "two-step breakbeat"},
                 "bass": {"sub", "wobble", "growl"},
                 "hook": {"sung vocal", "chopped vocal", "synth lead"}}
HIT_WIN_S = 0.07  # an onset within this of a grid slot counts as on it
HIT_FRAC = 0.3  # calibrated: Task 8. a hit is band flux at least this share of the clip's biggest
KICK_EVERY = 0.8  # calibrated: Task 8. kick on this share of beats is four-on-the-floor
SNARE_ONE_SLOT = 0.7  # calibrated: Task 8. this share of snares on one slot of four is half-time
BREAKBEAT_BPM = 160
SUB_SHARE = 0.6  # calibrated: Task 8. bass stem energy under 100 Hz for "sub"
WOBBLE_DEPTH = 0.3  # calibrated: Task 8. envelope std / mean
WOBBLE_SYNC = 0.4  # calibrated: Task 8. share of envelope modulation power on beat-related rates
GROWL_FLUX = 0.5  # calibrated: Task 8. normalized 200 Hz to 2 kHz spectral flux
VOCAL_ON_DB = -35.0  # calibrated: Task 8. vocal stem frame loudness that counts as singing
SUNG_SHARE, SUNG_BURST_S = 0.4, 1.0  # calibrated: Task 8
CHOP_BURST_S, CHOP_RATE = 0.5, 0.5  # calibrated: Task 8. bursts shorter than this, at least this many per second
LEAD_REPEAT = 0.6  # calibrated: Task 8. other-stem chroma self-similarity at 1, 2 or 4 bars
DROP_WINDOW_S = 30  # Demucs and EffNet run on this much of the top drop (30 s costs about 25 s on CPU)
EFFNET = "~/.cache/listener/models/discogs-effnet-bs64-1.pb"
BEATS_SOURCE = "beat_this+madmom"  # All-In-One will not build here (Task 1), so Beat This! + madmom + librosa sections
EMBEDDING_DIMS = 1280
SECTION_S = 10  # librosa segmentation: about one section per 10 s, 6 to 30 sections
SR = 22050


def _fold_to(bpm, anchor):
    """bpm moved by whole octaves into anchor's octave, so a 300 read of a 75 song folds to 75."""
    while bpm > anchor * 2 ** 0.5:
        bpm /= 2
    while bpm < anchor / 2 ** 0.5:
        bpm *= 2
    return bpm


def _bpm(beats):
    """Mean of the beat gaps within 25% of the median gap: the median alone snaps to the beat
    tracker's 20 ms frames (0.42 s is 142.9, 0.44 s is 136.4), and the plain mean breaks on a missed beat."""
    gaps = np.diff(np.asarray(beats, dtype=float))
    if not len(gaps):
        return None
    m = np.median(gaps)
    near = gaps[np.abs(gaps - m) <= 0.25 * m]
    return float(60 / (near.mean() if len(near) else m))


def _runs(beats, duration):
    """Split the beat list at beatless stretches. Returns (runs of beat indices, gaps)."""
    runs, gaps, cur = [], [], [0]
    if beats[0] >= GAP_S:
        gaps.append({"start": 0.0, "end": float(beats[0])})
    for i in range(1, len(beats)):
        if beats[i] - beats[i - 1] >= GAP_S:
            runs.append(cur)
            gaps.append({"start": float(beats[i - 1]), "end": float(beats[i])})
            cur = []
        cur.append(i)
    runs.append(cur)
    if duration - beats[-1] >= GAP_S:
        gaps.append({"start": float(beats[-1]), "end": float(duration)})
    return [r for r in runs if len(r) >= 2], gaps


def _change_points(b):
    """Beat positions (within one run) where a raw tempo move of CHANGE_BPM holds HOLD_BEATS.
    ponytail: one smoothed walk with a hold counter; a proper changepoint model if this misses real changes."""
    inst = 60 / np.diff(b)
    half = HOLD_BEATS // 2
    smooth = np.array([median(inst[max(0, i - half):i + half]) for i in range(len(inst))])
    cuts, ref, held, start = [], float(np.median(smooth[:HOLD_BEATS])), 0, None
    for i, v in enumerate(smooth):
        if abs(v - ref) > CHANGE_BPM:
            start = i if held == 0 else start
            held += 1
            if held >= HOLD_BEATS:
                cuts.append(start)
                ref, held = float(np.median(smooth[start:i + 1])), 0
        else:
            held = 0
    return cuts


def tempo_intervals(beats_a, beats_b, sections, duration):
    """beats_a: main beat track (Beat This!), beats_b: second opinion (librosa or All-In-One).
    sections: [(start, end, label)] covering the song. Returns {"intervals", "gaps", "tempo_change"};
    intervals and gaps together cover 0..duration."""
    beats = np.asarray(beats_a, dtype=float)
    other = np.asarray(beats_b, dtype=float)
    if len(beats) < 2:
        return {"intervals": [], "gaps": [{"start": 0.0, "end": float(duration)}], "tempo_change": False}
    runs, gaps = _runs(beats, duration)
    pieces = []  # (first beat index, last beat index)
    for run in runs:
        lo, hi = run[0], run[-1]
        cuts = [lo + c for c in _change_points(beats[lo:hi + 1])]
        for s, _, _ in sections:
            k = int(np.searchsorted(beats, s))
            if lo + MIN_SPLIT_BEATS <= k <= hi - MIN_SPLIT_BEATS and all(abs(k - c) >= MIN_SPLIT_BEATS for c in cuts):
                cuts.append(k)
        bounds = [lo] + sorted(set(cuts)) + [hi]
        pieces += [(a, b) for a, b in zip(bounds, bounds[1:]) if b > a]
    gap_edges = {g["start"] for g in gaps} | {g["end"] for g in gaps}
    intervals = []
    for n, (a, b) in enumerate(pieces):
        start = 0.0 if a == 0 and beats[0] < GAP_S else float(beats[a])
        end = float(duration) if b == len(beats) - 1 and float(duration) not in gap_edges else float(beats[b])
        raw = _bpm(beats[a:b + 1])
        assert raw is not None  # every piece spans at least two beats
        inside = other[(other >= beats[a]) & (other <= beats[b])]
        second = _bpm(inside) if len(inside) >= 4 else None
        mid = (start + end) / 2
        label = next((lab for s, e, lab in sections if s <= mid < e), sections[-1][2] if sections else "")
        intervals.append({"start": start, "end": end, "label": label, "beats": b - a + 1, "raw_bpm": round(raw, 2),
                          "second_bpm": round(second, 2) if second else None,
                          "unsure": second is None or abs(_fold_to(second, raw) - raw) > UNSURE_BPM})
    # Fold every interval to the octave holding most of the song, so 70 next to 140 reads as a feel change.
    anchor = max(intervals, key=lambda i: i["end"] - i["start"])["raw_bpm"]
    for i in intervals:
        i["folded_bpm"] = round(_fold_to(i["raw_bpm"], anchor), 2)
    sure = [i["folded_bpm"] for i in intervals if not i["unsure"] and i["beats"] >= HOLD_BEATS]  # fragments are noise
    return {"intervals": intervals, "gaps": gaps,
            "tempo_change": bool(sure) and max(sure) - min(sure) > CHANGE_BPM}


def main_tempo(intervals):
    """Duration-weighted median of the largest same-tempo group (folded within 2 BPM), unsure ones out.
    In the raw octave of that group's longest interval. None when every interval is unsure."""
    sure = [i for i in intervals if not i["unsure"]]
    if not sure:
        return None
    best, best_time = [], -1.0
    for anchor in sure:
        group = [i for i in sure if abs(_fold_to(i["raw_bpm"], anchor["raw_bpm"]) - anchor["raw_bpm"]) <= CHANGE_BPM]
        t = sum(i["end"] - i["start"] for i in group)
        if t > best_time:
            best, best_time = group, t
    ref = max(best, key=lambda i: i["end"] - i["start"])["raw_bpm"]
    pairs = sorted((_fold_to(i["raw_bpm"], ref), i["end"] - i["start"]) for i in best)
    half, acc = sum(w for _, w in pairs) / 2, 0.0
    for v, w in pairs:
        acc += w
        if acc >= half:
            return round(v, 2)


def _z(x, floor):
    """z-score with the spread floored, so a flat song's noise cannot score like a drop."""
    x = np.asarray(x, dtype=float)
    return (x - x.mean()) / max(float(x.std()), floor)


def pick_drops(sections, rms, sub, bar_s, duration):
    """sections: [(start, end, label)]; rms, sub: one mean dB value per section (whole band, under SUB_HZ).
    Score = z(rms) + z(sub). Onset density was the spec's second term, but builds (snare rolls) out-count
    a wall-of-sound drop, so sub-bass replaced it. Eligible: 8 bars or longer, starting after DROP_SKIP.
    The bar is DROP_BAR above the duration-weighted DROP_BASE_Q quantile, not the median: in heavy
    dubstep the drops are most of the song, so the median is drop level. Ranked, best first."""
    if not sections:
        return {"drops": [], "no_clear_drop": True}
    score = _z(rms, RMS_SD_FLOOR) + _z(sub, SUB_SD_FLOOR)
    w = np.array([e - s for s, e, _ in sections], dtype=float)
    order = np.argsort(score)
    cum = np.cumsum(w[order])
    bar = float(score[order][np.searchsorted(cum, DROP_BASE_Q * cum[-1])]) + DROP_BAR
    ok = [(float(score[k]), s, e) for k, (s, e, _) in enumerate(sections)
          if s >= DROP_SKIP * duration and e - s >= DROP_MIN_BARS * bar_s and score[k] >= bar]
    ok.sort(reverse=True)
    ok = [x for x in ok if x[0] >= ok[0][0] - LATER_DROP_GAP]  # a break louder than the intro is not a drop
    return {"drops": [{"start": float(s), "end": float(e), "score": round(sc, 3)} for sc, s, e in ok],
            "no_clear_drop": not ok}


# --- drop tellers, pure numpy on stem arrays ---

def _stft(x, sr):
    n = 2048
    hop = 512
    x = np.asarray(x, dtype=np.float32)
    if len(x) < n:
        x = np.pad(x, (0, n - len(x)))
    frames = np.lib.stride_tricks.sliding_window_view(x, n)[::hop] * np.hanning(n)
    return np.abs(np.fft.rfft(frames, axis=1)).T, np.fft.rfftfreq(n, 1 / sr), hop / sr


def _band_flux(S, freqs, lo, hi):
    e = S[(freqs >= lo) & (freqs < hi)].sum(0)  # linear: log energy lets a kick's click read as a snare
    return np.maximum(np.diff(e, prepend=e[:1]), 0)


def _hits(flux, frame_s, grid):
    top = flux.max() if len(flux) else 0
    if top <= 0:
        return np.zeros(len(grid), bool)
    w = max(1, int(HIT_WIN_S / frame_s))
    out = []
    for t in grid:
        k = int(round(t / frame_s))
        out.append(flux[max(0, k - w):k + w + 1].max(initial=0) >= HIT_FRAC * top)
    return np.array(out)


def _grid(beats, bpm):
    """Beat grid at a tempo of 100 or more: a half-time beat track gets its midpoints filled in."""
    g = np.asarray(beats, dtype=float)
    while bpm and bpm < 100 and len(g) > 1:
        g = np.sort(np.concatenate([g, (g[:-1] + g[1:]) / 2]))
        bpm *= 2
    return g, bpm


def drums_teller(drums, sr, beats, bpm):
    S, f, fs = _stft(drums, sr)
    grid, bpm = _grid(beats, bpm)
    kick = _hits(_band_flux(S, f, 20, 120), fs, grid)
    snare = _hits(_band_flux(S, f, 1000, 4000), fs, grid)
    slots = np.bincount(np.arange(len(grid)) % 4, weights=snare.astype(float), minlength=4)
    n = {"kick_share": round(float(kick.mean()), 3) if len(kick) else 0.0,
         "snare_slots": [int(v) for v in slots], "grid_bpm": round(float(bpm or 0), 1)}
    total = slots.sum()
    one = slots.max() / total if total else 0
    back = max(slots[0] + slots[2], slots[1] + slots[3]) / total if total else 0
    if n["kick_share"] >= KICK_EVERY:
        label = "four-on-the-floor"
    elif total and one >= SNARE_ONE_SLOT:
        label = "half-time"
    elif total and back >= SNARE_ONE_SLOT and (bpm or 0) >= BREAKBEAT_BPM:
        label = "two-step breakbeat"
    else:
        label = "unknown"
    return label, n


def bass_teller(bass, sr, beats, bpm):
    S, f, fs = _stft(bass, sr)
    power = (S ** 2).sum(0)
    total = power.sum()
    if total <= 0:
        return "unknown", {"sub_share": 0.0}
    sub = float((S[f < 100] ** 2).sum() / (S ** 2).sum())
    env = np.sqrt(power)
    depth = float(env.std() / env.mean())
    m = np.abs(np.fft.rfft(env - env.mean())) ** 2
    mf = np.fft.rfftfreq(len(env), fs)
    beat_hz = (bpm or 120) / 60
    rates = [beat_hz * r for r in (0.5, 1, 2, 3, 4, 6, 8)]
    on = sum(m[np.abs(mf - r) <= 0.05 * r + mf[1]].sum() for r in rates)
    sync = float(on / m[mf > 0.2].sum()) if m[mf > 0.2].sum() > 0 else 0.0
    mid = _band_flux(S, f, 200, 2000)
    growl = float(mid.mean() / (mid.max() or 1))
    n = {"sub_share": round(sub, 3), "mod_depth": round(depth, 3), "mod_sync": round(sync, 3), "growl_flux": round(growl, 3)}
    if depth >= WOBBLE_DEPTH and sync >= WOBBLE_SYNC:
        return "wobble", n
    if growl >= GROWL_FLUX and sub < SUB_SHARE:
        return "growl", n
    if sub >= SUB_SHARE and depth < WOBBLE_DEPTH:
        return "sub", n
    return "unknown", n


def hook_teller(vocals, other, sr, beats, bpm):
    v = np.asarray(vocals, dtype=np.float32)
    fs = 512 / sr
    frames = np.lib.stride_tricks.sliding_window_view(np.pad(v, (0, max(0, 2048 - len(v)))), 2048)[::512]
    on = 20 * np.log10(np.sqrt((frames ** 2).mean(1)) + 1e-9) >= VOCAL_ON_DB  # dBFS per frame
    runs, k = [], 0
    for v in list(on) + [False]:
        if v:
            k += 1
        elif k:
            runs.append(k * fs)
            k = 0
    dur = len(on) * fs or 1
    n = {"vocal_share": round(float(on.mean()), 3) if len(on) else 0.0,
         "bursts_per_s": round(len(runs) / dur, 3), "mean_burst_s": round(float(np.mean(runs)), 3) if runs else 0.0}
    if n["vocal_share"] >= SUNG_SHARE and n["mean_burst_s"] >= SUNG_BURST_S:
        return "sung vocal", n
    if runs and n["mean_burst_s"] < CHOP_BURST_S and n["bursts_per_s"] >= CHOP_RATE:
        return "chopped vocal", n
    # Synth lead: the other stem's chroma repeating each 1, 2 or 4 bars.
    So, fo, _ = _stft(other, sr)
    if (So ** 2).sum() <= 0:
        return "unknown", n
    pc = np.round(12 * np.log2(np.maximum(fo, 1) / 440)) % 12
    chroma = np.stack([So[(pc == c) & (fo > 80)].sum(0) for c in range(12)])
    chroma = chroma / (np.linalg.norm(chroma, axis=0) + 1e-9)
    bar_frames = int(round(4 * 60 / (bpm or 120) / fs))
    best = 0.0
    for bars in (1, 2, 4):
        lag = bars * bar_frames
        if 0 < lag < chroma.shape[1]:
            best = max(best, float((chroma[:, :-lag] * chroma[:, lag:]).sum(0).mean()))
    n["lead_repeat"] = round(best, 3)
    return ("synth lead" if best >= LEAD_REPEAT else "unknown"), n


def bad_tellers(tellers):
    """Keys whose value is outside TELLER_LABELS (unknown is always allowed)."""
    return [k for k, v in tellers.items() if k not in TELLER_LABELS or (v != "unknown" and v not in TELLER_LABELS[k])]


# --- the models (imported only here, never at module load) ---

def _sections(y, duration):
    import librosa
    S = np.abs(librosa.stft(y, hop_length=512))
    feats = np.vstack([librosa.feature.chroma_stft(S=S, sr=SR),
                       librosa.feature.mfcc(S=librosa.power_to_db(S ** 2), sr=SR)])
    k = int(min(30, max(6, round(duration / SECTION_S))))
    t = [float(v) for v in librosa.frames_to_time(librosa.segment.agglomerative(feats, k), sr=SR, hop_length=512)]
    t = sorted(set([0.0] + t[1:])) + [float(duration)]
    return [(a, b, f"part {n + 1}") for n, (a, b) in enumerate(zip(t, t[1:])) if b > a]


def _section_energy(y, sections):
    """Mean dB per section, whole band and under SUB_HZ."""
    import librosa
    S = np.abs(librosa.stft(y, hop_length=512))
    ft = librosa.frames_to_time(np.arange(S.shape[1]), sr=SR, hop_length=512)
    low = librosa.fft_frequencies(sr=SR) < SUB_HZ
    full = librosa.amplitude_to_db(np.sqrt((S ** 2).mean(0)) + 1e-9)
    sub = librosa.amplitude_to_db(np.sqrt((S[low] ** 2).mean(0)) + 1e-9)
    r, u = [], []
    for s, e, _ in sections:
        m = (ft >= s) & (ft < e)
        r.append(float(full[m].mean()) if m.any() else -120.0)
        u.append(float(sub[m].mean()) if m.any() else -120.0)
    return r, u


def _stems(path, offset, duration):
    """htdemucs on [offset, offset + duration], mono stems at 44.1 kHz keyed by name."""
    import librosa
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model
    m = get_model("htdemucs")
    y2, _ = librosa.load(path, sr=44100, mono=False, offset=offset, duration=duration)
    if y2.ndim == 1:
        y2 = np.stack([y2, y2])
    with torch.no_grad():
        out = apply_model(m, torch.tensor(y2, dtype=torch.float32)[None], device="cpu")[0].numpy()
    return {name: out[k].mean(0) for k, name in enumerate(m.sources)}


def _embedding(y, w0, w1):
    """Discogs-EffNet embedding averaged over the window. The style head is never loaded."""
    import os
    import librosa
    from essentia.standard import TensorflowPredictEffnetDiscogs
    a = librosa.resample(y[int(w0 * SR):int(w1 * SR)], orig_sr=SR, target_sr=16000).astype(np.float32)
    e = TensorflowPredictEffnetDiscogs(graphFilename=os.path.expanduser(EFFNET), output="PartitionedCall:1")(a)
    return [round(float(v), 6) for v in np.asarray(e).mean(0)]


def search(query):
    """YouTube Music songs-filter results, the fields identity needs."""
    from ytmusicapi import YTMusic
    return [{"videoId": r.get("videoId"), "title": r.get("title"), "resultType": r.get("resultType"),
             "artists": [a.get("name") for a in r.get("artists") or []],
             "duration_seconds": r.get("duration_seconds")}
            for r in YTMusic().search(query, filter="songs", limit=10) if r.get("videoId")]


def _madmom_beats(y):
    """Second beat track from madmom's RNN + DBN, a separate model from Beat This!. librosa's tracker
    was tried first and read Firefly at 86 against 130 (3:2), which folding cannot reconcile."""
    from madmom.audio.signal import Signal
    from madmom.features.beats import DBNBeatTrackingProcessor, RNNBeatProcessor
    act = RNNBeatProcessor()(Signal(y.astype(np.float32), sample_rate=SR, num_channels=1))
    return DBNBeatTrackingProcessor(fps=100)(act)


def _versions():
    from importlib.metadata import version
    import torch
    v = {p: version(p) for p in ("beat-this", "demucs", "essentia-tensorflow", "librosa", "madmom", "ytmusicapi")}
    v["device"] = "cuda" if torch.cuda.is_available() else "cpu"
    return v


def measure(path):
    import librosa
    from beat_this.inference import File2Beats
    y, _ = librosa.load(path, sr=SR, mono=True)
    duration = len(y) / SR
    beats, _downbeats = File2Beats(checkpoint_path="final0", device="cpu", dbn=False)(path)
    second = _madmom_beats(y)
    sections = _sections(y, duration)
    t = tempo_intervals(beats, second, sections, duration)
    main = main_tempo(t["intervals"])
    rms, sub = _section_energy(y, sections)
    bar_bpm = main or 120
    while bar_bpm < 100:  # a half-time read (75 for a 150 song) would double the 8-bar minimum
        bar_bpm *= 2
    while bar_bpm >= 200:
        bar_bpm /= 2
    d = pick_drops(sections, rms, sub, 4 * 60 / bar_bpm, duration)
    if d["drops"]:
        top = d["drops"][0]
        mid = (top["start"] + top["end"]) / 2
        w0 = max(top["start"], mid - DROP_WINDOW_S / 2)
    else:
        w0 = max(0.0, duration / 2 - DROP_WINDOW_S / 2)  # no drop: the fingerprint still needs a window
    w1 = min(duration, w0 + DROP_WINDOW_S)
    stems = _stems(path, w0, w1 - w0)
    beats_in = [b - w0 for b in beats if w0 <= b < w1]
    tellers, numbers = {}, {}
    tellers["drums"], numbers["drums"] = drums_teller(stems["drums"], 44100, beats_in, bar_bpm)
    tellers["bass"], numbers["bass"] = bass_teller(stems["bass"], 44100, beats_in, bar_bpm)
    tellers["hook"], numbers["hook"] = hook_teller(stems["vocals"], stems["other"], 44100, beats_in, bar_bpm)
    if d["no_clear_drop"]:
        tellers = {k: "unknown" for k in tellers}
    else:
        d["drops"][0].update(tellers=tellers, teller_numbers=numbers)
        for x in d["drops"][1:]:
            x["tellers"] = {k: "unknown" for k in tellers}  # stems run on the top drop only
    emb = _embedding(y, w0, w1)
    return {"duration_s": round(duration, 2), **t, "main_bpm": main, **d,
            "sections": [{"start": s, "end": e, "label": lab} for s, e, lab in sections],
            "window": [round(w0, 2), round(w1, 2)], "embedding": emb, "embedding_dims": len(emb),
            "beats_source": BEATS_SOURCE, "versions": _versions()}


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("measure")
    m.add_argument("audio")
    m.add_argument("--out", required=True)
    q = sub.add_parser("search")
    q.add_argument("query")
    q.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        out = measure(a.audio) if a.cmd == "measure" else search(a.query)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 1
    with open(a.out, "w") as f:
        json.dump(out, f)
    return 0


if __name__ == "__main__":
    sys.exit(main())
