"""A local music library: real tracks the user adds, analysed for tempo, beats and drops.

Generated beats sound synthetic and viewers call them out as AI music. Put licensed tracks in
content_projects/music/ (Pixabay Music, YouTube Audio Library, Free Music Archive CC-BY, your own),
optionally with tracks.json for credits:

    {"apathias.mp3": {"title": "Apathias", "artist": "DeusLower", "source": "Pixabay",
                      "license": "Pixabay Content License", "url": "https://pixabay.com/...", "mood": "dark"}}

`python -m content_agent music-lib` analyses every track (cached in index.json): duration, BPM,
beat times, energy, and the strongest drops. edit.json then uses `"music": {"track": "apathias.mp3"}`:
segment lengths in beats follow the track's tempo and the track is placed so a drop lands on the
payoff segment.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import numpy as np

AUDIO_EXT = {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".opus", ".aac"}
SR = 22_050
HOP = 512
SOURCES = ("Pixabay Music (pixabay.com/music)", "YouTube Audio Library (Studio → Audio Library)",
           "Free Music Archive, CC-BY tracks (freemusicarchive.org)", "your own music")


def library_dir(project: Path | None = None) -> Path:
    env = os.environ.get("CONTENT_AGENT_MUSIC")
    if env:
        return Path(env).expanduser()
    if project is not None:
        return project.parent / "music"
    from .status import projects_root

    return projects_root() / "music"


def decode(path: Path, sr: int = SR, start: float = 0.0, duration: float | None = None, channels: int = 1) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{max(start, 0):.3f}"]
    if duration is not None:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-i", str(path), "-ac", str(channels), "-ar", str(sr), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    a = np.frombuffer(raw, np.float32)
    return a.reshape(-1, channels) if channels > 1 else a


N_FFT = 2048
# a frame's flux peaks when an onset reaches the middle of its window
FRAME_DELAY = N_FFT / 2 / SR


def onset_envelope(y: np.ndarray, sr: int = SR, n_fft: int = N_FFT, hop: int = HOP,
                   low_hz: float | None = None) -> np.ndarray:
    """Spectral flux: how much new energy appears in each frame (log-compressed, rectified).

    low_hz keeps only the bins below it: the kick carries the beat, hi-hats often sit between beats."""
    if len(y) < n_fft:
        return np.zeros(1)
    win = np.hanning(n_fft).astype(np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(y, n_fft)[::hop] * win
    mag = np.log1p(10 * np.abs(np.fft.rfft(frames, axis=1)))
    d = np.maximum(np.diff(mag, axis=0), 0)
    if low_hz:
        freqs = np.fft.rfftfreq(n_fft, 1 / sr)
        d = d[:, freqs < low_hz]
    flux = np.concatenate([[0.0], d.sum(axis=1)])
    flux -= np.convolve(flux, np.ones(16) / 16, mode="same")  # remove the slow trend
    return np.maximum(flux, 0)


def tempo(env: np.ndarray, sr: int = SR, hop: int = HOP, lo: float = 70, hi: float = 180) -> float:
    """BPM from the autocorrelation of the onset envelope, with a mild preference for 90-150."""
    fps = sr / hop
    e = env - env.mean()
    ac = np.correlate(e, e, mode="full")[len(e) - 1:]
    lags = np.arange(len(ac))
    valid = (lags >= fps * 60 / hi) & (lags <= fps * 60 / lo)
    if not valid.any():
        return 120.0
    bpm = 60 * fps / np.maximum(lags, 1)
    prior = np.exp(-0.5 * (np.log2(bpm / 120) / 0.9) ** 2)
    score = np.where(valid, ac * prior, -np.inf)
    lag = int(np.argmax(score))
    # parabolic refinement of the peak for a sub-frame period
    if 1 <= lag < len(ac) - 1:
        a, b, c = ac[lag - 1], ac[lag], ac[lag + 1]
        denom = a - 2 * b + c
        lag = lag + (0.5 * (a - c) / denom if denom else 0)
    return float(60 * fps / lag)


def beat_grid(env: np.ndarray, bpm: float, sr: int = SR, hop: int = HOP, spread: float = 1.5) -> tuple[float, np.ndarray]:
    """(refined BPM, beat times in s): the constant-tempo grid near `bpm` that lands on the most onsets.

    Tempo and phase are searched together: a 0.5 BPM error drifts ~100 ms over 30 s of beats."""
    fps = sr / hop
    n = len(env)
    smooth = np.convolve(env, np.array([0.25, 0.5, 1.0, 0.5, 0.25]), mode="same")  # tolerate a frame of jitter
    best, best_bpm, best_off = -1.0, bpm, 0.0
    for cand in np.arange(bpm - spread, bpm + spread + 1e-9, 0.05):
        period = 60 * fps / cand
        grid = np.arange(0, n, period)
        for off in np.arange(0, period, 0.5):
            idx = np.round(grid + off).astype(int)
            sc = smooth[idx[idx < n]].sum()
            if sc > best:
                best, best_bpm, best_off = sc, float(cand), float(off)
    period = 60 * fps / best_bpm
    return best_bpm, np.arange(best_off, n, period) / fps + FRAME_DELAY


def beats(env: np.ndarray, bpm: float, sr: int = SR, hop: int = HOP) -> np.ndarray:
    """Beat times (s) of the best grid near `bpm`."""
    return beat_grid(env, bpm, sr, hop)[1]


def energy(y: np.ndarray, sr: int = SR, step: float = 0.5) -> np.ndarray:
    k = int(sr * step)
    m = len(y) // k
    if m == 0:
        return np.zeros(1)
    return np.sqrt((y[: m * k].reshape(m, k) ** 2).mean(axis=1))


def drops(en: np.ndarray, beat_times: np.ndarray, step: float = 0.5, n: int = 3, span: float = 2.0) -> list[float]:
    """The moments where energy jumps most (after vs before), snapped to beats, at least 8 s apart."""
    w = max(1, int(span / step))
    scores = []
    for i in range(w, len(en) - w):
        before, after = en[i - w:i].mean(), en[i:i + w].mean()
        scores.append((after - before, i * step))
    scores.sort(reverse=True)
    out: list[float] = []
    for sc, t in scores:
        if sc <= 0:
            break
        if len(beat_times):
            t = float(beat_times[np.argmin(np.abs(beat_times - t))])
        if all(abs(t - o) >= 8 for o in out):
            out.append(round(t, 3))
        if len(out) == n:
            break
    return out


def analyze(path: Path) -> dict:
    y = decode(path)
    dur = len(y) / SR
    env = onset_envelope(y)
    bpm = tempo(env)
    low = onset_envelope(y, low_hz=200)
    # phase from the kick when the track has one, else from all onsets
    bpm, bt = beat_grid(low if low.sum() > 0.02 * env.sum() else env, bpm)
    en = energy(y)
    loud = en > 0.6 * (np.median(en) or 1e-9)
    intro_end = float(np.argmax(loud) * 0.5) if loud.any() else 0.0
    return {"duration": round(dur, 2), "bpm": round(bpm, 1), "beats": [round(float(b), 3) for b in bt],
            "drops": drops(en, bt), "intro_end": round(intro_end, 2)}


def scan(lib: Path, rescan: bool = False) -> dict:
    """Analyse new or changed tracks; returns {file: {meta..., analysis...}} and writes index.json."""
    lib.mkdir(parents=True, exist_ok=True)
    idx_path = lib / "index.json"
    try:
        index = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() and not rescan else {}
    except ValueError:
        index = {}
    try:
        meta = json.loads((lib / "tracks.json").read_text(encoding="utf-8")) if (lib / "tracks.json").exists() else {}
    except ValueError:
        meta = {}
    out = {}
    for f in sorted(lib.iterdir()):
        if f.suffix.lower() not in AUDIO_EXT:
            continue
        stamp = f"{f.stat().st_size}:{int(f.stat().st_mtime)}"
        entry = index.get(f.name)
        if not entry or entry.get("stamp") != stamp:
            entry = {"stamp": stamp, **analyze(f)}
        m = meta.get(f.name, {})
        entry.update({"title": m.get("title", f.stem), "artist": m.get("artist", ""), "source": m.get("source", ""),
                      "license": m.get("license", ""), "url": m.get("url", ""), "mood": m.get("mood", "")})
        out[f.name] = entry
    idx_path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def load(lib: Path) -> dict:
    try:
        return json.loads((lib / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def credit(entry: dict) -> str:
    who = f"“{entry.get('title')}”" + (f" by {entry['artist']}" if entry.get("artist") else "")
    extra = ", ".join(x for x in (entry.get("source"), entry.get("license")) if x)
    return f"Music: {who}" + (f" ({extra})" if extra else "") + (f" {entry['url']}" if entry.get("url") else "")


def place(entry: dict, drop_at: float | None, track_drop: float | None = None, start: float | None = None) -> float:
    """Where in the track the video starts: a beat chosen so a drop lands on the payoff (drop_at, video seconds)."""
    bt = np.array(entry.get("beats") or [0.0])
    if start is not None:
        return float(start)
    target = None
    if drop_at is not None:
        d = track_drop if track_drop is not None else (entry.get("drops") or [None])[0]
        if d is not None and d - drop_at >= 0:
            target = d - drop_at
    if target is None:  # no payoff to land: start on the first beat after the intro
        later = bt[bt >= entry.get("intro_end", 0.0) - 1e-6]
        return float(later[0] if len(later) else bt[0])
    return float(bt[np.argmin(np.abs(bt - target))])


def track_audio(path: Path, start: float, duration: float, sr: int, stops: list[tuple[float, float]] | None = None,
                fade: float = 0.6) -> np.ndarray:
    """Mono track audio for the video: from `start`, looped if short, silent in stops, faded out."""
    y = decode(path, sr=sr, start=start, duration=duration + 0.1)
    n = int(duration * sr)
    if len(y) == 0:
        return np.zeros(n, np.float32)
    if len(y) < n:  # loop the track with a short crossfade
        full = decode(path, sr=sr)
        xf = int(0.05 * sr)
        while len(y) < n and len(full) > xf:
            tail = y[-xf:] * np.linspace(1, 0, xf, dtype=np.float32)
            y = np.concatenate([y[:-xf], tail + full[:xf] * np.linspace(0, 1, xf, dtype=np.float32), full[xf:]])
    y = y[:n].astype(np.float32).copy()
    ramp = int(0.03 * sr)
    for a, b in stops or []:
        i, j = int(a * sr), int(b * sr)
        y[i:j] = 0
        if i - ramp > 0:
            y[i - ramp:i] *= np.linspace(1, 0, ramp, dtype=np.float32)
        if j + ramp < len(y):
            y[j:j + ramp] *= np.linspace(0, 1, ramp, dtype=np.float32)
    f = min(int(fade * sr), len(y))
    if f:
        y[-f:] *= np.linspace(1, 0, f, dtype=np.float32)
    return y
