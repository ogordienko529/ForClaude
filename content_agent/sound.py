"""Procedural sound for fast edits: beat music and sound effects, generated from scratch.

Nothing is sampled from anywhere, so there is no licence to track and nothing for Content ID to
match. Music is built on a beat grid so the editor can cut on beats and land a drop on the payoff.
"""

from __future__ import annotations

import math

import numpy as np

SR = 48_000


def _t(seconds: float, sr: int = SR) -> np.ndarray:
    return np.arange(int(seconds * sr), dtype=np.float32) / sr


def _env(n: int, attack: float, decay: float, sr: int = SR) -> np.ndarray:
    t = np.arange(n, dtype=np.float32) / sr
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    return a * np.exp(-np.maximum(t - attack, 0) / max(decay, 1e-4))


def _sweep(f0: float, f1: float, seconds: float, sr: int = SR, curve: float = 6.0) -> np.ndarray:
    """Sine whose frequency glides exponentially from f0 to f1."""
    t = _t(seconds, sr)
    f = f1 + (f0 - f1) * np.exp(-curve * t / max(seconds, 1e-3))
    return np.sin(2 * np.pi * np.cumsum(f) / sr).astype(np.float32)


def _noise(seconds: float, rng: np.random.Generator, sr: int = SR) -> np.ndarray:
    return rng.standard_normal(int(seconds * sr)).astype(np.float32)


def _lp(x: np.ndarray, cutoff: float, sr: int = SR, order: int = 2) -> np.ndarray:
    """Zero-phase Butterworth-shaped low-pass applied in the frequency domain (pure numpy)."""
    if len(x) == 0:
        return x
    n = 1 << int(math.ceil(math.log2(len(x) + 1024)))
    f = np.fft.rfftfreq(n, 1 / sr)
    gain = 1 / np.sqrt(1 + (f / cutoff) ** (2 * order))
    return np.fft.irfft(np.fft.rfft(x, n) * gain, n)[: len(x)].astype(np.float32)


def _hp(x: np.ndarray, cutoff: float, sr: int = SR) -> np.ndarray:
    return (x - _lp(x, cutoff, sr)).astype(np.float32)


def _bandpass_sweep(x: np.ndarray, f0: float, f1: float, sr: int = SR, block: int = 512, q: float = 0.35) -> np.ndarray:
    """Band-pass whose centre moves from f0 to f1 over the signal (short FFT blocks with overlap)."""
    out = np.zeros(len(x) + block, dtype=np.float32)
    win = np.hanning(block * 2).astype(np.float32)
    freqs = np.fft.rfftfreq(block * 2, 1 / sr)
    n_blocks = max(len(x) // block, 1)
    for i in range(n_blocks):
        seg = x[i * block : i * block + block * 2]
        if len(seg) < block * 2:
            seg = np.pad(seg, (0, block * 2 - len(seg)))
        c = f0 * (f1 / f0) ** (i / max(n_blocks - 1, 1))
        mask = np.exp(-0.5 * (np.log(np.maximum(freqs, 1) / c) / q) ** 2)
        y = np.fft.irfft(np.fft.rfft(seg * win) * mask, block * 2).astype(np.float32)
        out[i * block : i * block + block * 2] += y
    return out[: len(x)]


def _norm(x: np.ndarray, peak: float = 0.9) -> np.ndarray:
    m = float(np.max(np.abs(x))) or 1.0
    return (x / m * peak).astype(np.float32)


# ---------------------------------------------------------------- sound effects
def sfx(name: str, sr: int = SR, seed: int = 1) -> np.ndarray:
    """boom, whoosh, pop, riser, hit, ding, tick."""
    rng = np.random.default_rng(seed)
    if name == "boom":  # deep meme-style impact: sub drop + dull noise burst + tail
        sub = _sweep(90, 32, 1.6, sr, curve=5) * _env(int(1.6 * sr), 0.004, 0.55, sr)
        body = _lp(_noise(1.6, rng, sr), 700, sr) * _env(int(1.6 * sr), 0.002, 0.18, sr) * 0.9
        x = np.tanh(2.2 * (sub + body))
        return _norm(x, 0.95)
    if name == "whoosh":
        n = 0.42
        x = _bandpass_sweep(_noise(n, rng, sr), 350, 4200, sr)
        e = np.sin(np.pi * np.clip(_t(n, sr) / n, 0, 1)) ** 1.5
        return _norm(x * e, 0.7)
    if name == "pop":
        x = _sweep(1300, 380, 0.09, sr, curve=8) * _env(int(0.09 * sr), 0.001, 0.025, sr)
        return _norm(x, 0.6)
    if name == "tick":
        x = _hp(_noise(0.02, rng, sr), 3000, sr) * _env(int(0.02 * sr), 0.0005, 0.004, sr)
        return _norm(x, 0.4)
    if name == "riser":
        n = 1.6
        t = _t(n, sr)
        tone = _sweep(180, 1500, n, sr, curve=-2.5)
        noise = _hp(_noise(n, rng, sr), 2500, sr)
        e = (t / n) ** 2.2
        return _norm((0.5 * tone + 0.6 * noise) * e, 0.6)
    if name == "hit":
        kick = _sweep(160, 45, 0.3, sr, curve=9) * _env(int(0.3 * sr), 0.001, 0.09, sr)
        snap = _hp(_noise(0.3, rng, sr), 1800, sr) * _env(int(0.3 * sr), 0.0005, 0.04, sr)
        return _norm(np.tanh(1.8 * (kick + 0.6 * snap)), 0.9)
    if name == "ding":
        n = 1.0
        t = _t(n, sr)
        x = sum(a * np.sin(2 * np.pi * f * t) for f, a in ((1568, 1.0), (3136, 0.4), (4704, 0.2)))
        return _norm(x * _env(len(t), 0.002, 0.25, sr), 0.5)
    raise ValueError(f"unknown sound effect {name!r}")


SFX_NAMES = ("boom", "whoosh", "pop", "tick", "riser", "hit", "ding")


# ---------------------------------------------------------------- beat music
NOTES = {n: i for i, n in enumerate("C C# D D# E F F# G G# A A# B".split())}


def _hz(note: str) -> float:
    name, octave = note[:-1], int(note[-1])
    return 440.0 * 2 ** ((NOTES[name] + 12 * (octave + 1) - 69) / 12)


def _cowbell(f: float, sr: int, length: float = 0.32) -> np.ndarray:
    """Pitched 808-style cowbell: two detuned square waves, band-passed, fast decay (the phonk sound)."""
    t = _t(length, sr)
    sq = np.sign(np.sin(2 * np.pi * f * t)) + 0.8 * np.sign(np.sin(2 * np.pi * f * 1.4983 * t))
    x = _hp(_lp(sq.astype(np.float32), 3200, sr), 500, sr)
    return x * _env(len(t), 0.001, 0.09, sr)


def _bass808(f: float, sr: int, length: float) -> np.ndarray:
    t = _t(length, sr)
    glide = f * (1 + 1.0 * np.exp(-t / 0.025))
    x = np.sin(2 * np.pi * np.cumsum(glide) / sr)
    return np.tanh(2.5 * x * _env(len(t), 0.003, length * 0.55, sr)).astype(np.float32)


def _kick(sr: int) -> np.ndarray:
    return (_sweep(150, 42, 0.35, sr, curve=10) * _env(int(0.35 * sr), 0.001, 0.11, sr)).astype(np.float32)


def _clap(sr: int, rng: np.random.Generator) -> np.ndarray:
    n = int(0.25 * sr)
    x = np.zeros(n, dtype=np.float32)
    burst = _bandpass_sweep(_noise(0.25, rng, sr), 1400, 1100, sr)
    for k, d in enumerate((0.0, 0.011, 0.022)):
        i = int(d * sr)
        x[i:] += burst[: n - i] * _env(n - i, 0.0005, 0.012 if k < 2 else 0.07, sr)
    return x


def _hat(sr: int, rng: np.random.Generator, open_: bool = False) -> np.ndarray:
    length = 0.18 if open_ else 0.04
    return _hp(_noise(length, rng, sr), 7000, sr) * _env(int(length * sr), 0.0005, 0.06 if open_ else 0.012, sr)


STYLES = {
    # bass roots per bar, melody (step, note) over 16 steps, kick/clap steps
    "phonk": {"bass": ["F1", "F1", "C#1", "D#1"],
              "melody": [(0, "F5"), (3, "F5"), (6, "G#5"), (8, "F5"), (10, "D#5"), (11, "C5"), (14, "D#5")],
              "kick": [0, 7, 10], "clap": [4, 12], "hats": 2},
    "hype": {"bass": ["A1", "A1", "F1", "G1"],
             "melody": [(0, "A5"), (2, "C6"), (4, "E6"), (6, "C6"), (8, "A5"), (10, "C6"), (12, "D6"), (14, "B5")],
             "kick": [0, 4, 8, 12], "clap": [4, 12], "hats": 2},
}


def beat_music(duration: float, bpm: float = 140, style: str = "phonk", drop_at: float | None = None,
               stops: list[tuple[float, float]] | None = None, sr: int = SR, seed: int = 3) -> np.ndarray:
    """Loopable beat. Before `drop_at` only a filtered melody plays (build-up) with a beat of silence
    just before the drop; `stops` are (start, end) gaps where the music halts with a tape-stop."""
    spec = STYLES.get(style, STYLES["phonk"])
    rng = np.random.default_rng(seed)
    step = 60 / bpm / 4
    n = int(duration * sr) + sr
    drums = np.zeros(n, dtype=np.float32)
    bass = np.zeros(n, dtype=np.float32)
    mel = np.zeros(n, dtype=np.float32)
    kick, clap = _kick(sr), _clap(sr, rng)
    hats = [_hat(sr, rng), _hat(sr, rng, True)]
    total_steps = int(duration / step) + 1

    def put(buf: np.ndarray, x: np.ndarray, t: float, gain: float = 1.0) -> None:
        i = int(t * sr)
        if i >= len(buf):
            return
        m = min(len(x), len(buf) - i)
        buf[i : i + m] += gain * x[:m]

    melody = dict(spec["melody"])
    for s in range(total_steps):
        t = s * step
        bar, pos = divmod(s, 16)
        if pos in melody:
            put(mel, _cowbell(_hz(melody[pos]), sr), t, 0.55)
        if pos == 0:
            root = spec["bass"][bar % len(spec["bass"])]
            put(bass, _bass808(_hz(root), sr, step * 14), t, 0.7)
        if pos in spec["kick"]:
            put(drums, kick, t, 1.0)
        if pos in spec["clap"]:
            put(drums, clap, t, 0.55)
        if pos % spec["hats"] == 0 or (pos >= 13 and bar % 2 == 1):
            put(drums, hats[1 if pos == 14 and bar % 4 == 3 else 0], t, 0.22 if pos % 4 else 0.3)

    if drop_at is not None and drop_at > 0:
        i = int(drop_at * sr)
        gap = int(60 / bpm * sr)  # one beat of silence right before the drop
        pre_mel = _lp(mel[:i], 900, sr) * 0.8
        mel[:i] = pre_mel
        drums[:i] = _hp(drums[:i], 5000, sr) * 0.6  # only hats in the build-up
        bass[:i] = 0
        for buf in (mel, drums):
            buf[max(i - gap, 0) : i] *= np.linspace(1, 0, min(gap, i)) ** 3
    mix = np.tanh(1.3 * (0.9 * drums + 0.75 * bass + 0.6 * mel))
    for start, end in stops or []:
        mix = _tape_stop(mix, start, end, sr)
    fade = int(0.01 * sr)
    mix[:fade] *= np.linspace(0, 1, fade)
    return _norm(mix[: int(duration * sr)], 0.9)


def _tape_stop(x: np.ndarray, start: float, end: float, sr: int, spin_down: float = 0.35) -> np.ndarray:
    """Slow the music to a halt at `start`, silence until `end`, then resume from where it stopped."""
    i0, i1 = int(start * sr), int(end * sr)
    if i0 >= len(x):
        return x
    d = int(spin_down * sr)
    rate = np.linspace(1, 0, d) ** 1.5
    pos = i0 + np.cumsum(rate)
    spun = np.interp(pos, np.arange(len(x)), x).astype(np.float32) * np.linspace(1, 0.2, d)
    consumed = int(pos[-1]) - i0
    rest = x[i0 + consumed :]
    out = np.concatenate([x[:i0], spun, np.zeros(max(i1 - i0 - d, 0), np.float32), rest])
    return out[: len(x)]
