"""Render a script to narration: per-sentence synthesis (cached, resumable), sleep pacing,
per-sentence level matching, click-free joins, SRT subtitles and YouTube chapter timestamps."""

from __future__ import annotations

import hashlib
import math
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from .engine import Engine
from .text import Script

CACHE_DIR = Path("~/.sleep_voice/cache").expanduser()


@dataclass
class Pacing:
    speed: float = 0.88              # Kokoro speed at the start (1.0 = normal reading pace)
    wind_down_speed: float = 0.80    # speed reached at the end of the wind-down
    wind_down_start: float = 0.15    # fraction of the script where slowing starts
    sentence_pause: float = 0.85     # seconds between sentences
    paragraph_pause: float = 2.0
    chapter_pause: float = 4.5
    wind_down_pause_scale: float = 1.35  # pauses grow by this factor by the end
    jitter: float = 0.15             # ±15% random variation in pauses: sounds human, not metronomic
    target_level_db: float = -23.0   # per-sentence RMS target before mastering
    max_gain_db: float = 6.0
    fade_ms: float = 12.0
    seed: int = 7


def progress_curve(pos: float, start: float) -> float:
    """0 before `start`, then a smooth (cosine) ramp to 1 at the end of the script."""
    if pos <= start:
        return 0.0
    x = (pos - start) / (1 - start)
    return 0.5 - 0.5 * math.cos(math.pi * min(x, 1.0))


def speed_at(pos: float, p: Pacing) -> float:
    return p.speed + (p.wind_down_speed - p.speed) * progress_curve(pos, p.wind_down_start)


def pause_scale_at(pos: float, p: Pacing) -> float:
    return 1 + (p.wind_down_pause_scale - 1) * progress_curve(pos, p.wind_down_start)


def level_match(audio: np.ndarray, target_db: float, max_gain_db: float) -> np.ndarray:
    """Bring every sentence to the same loudness so no sentence is suddenly louder."""
    if audio.size == 0:
        return audio
    rms = float(np.sqrt(np.mean(np.square(audio))))
    if rms < 1e-6:
        return audio
    gain_db = min(target_db - 20 * math.log10(rms), max_gain_db)
    out = audio * (10 ** (gain_db / 20))
    peak = float(np.max(np.abs(out)))
    return out / peak * 0.89 if peak > 0.89 else out


def fade(audio: np.ndarray, sr: int, ms: float) -> np.ndarray:
    n = min(int(sr * ms / 1000), audio.size // 2)
    if n <= 1:
        return audio
    ramp = np.sin(np.linspace(0, np.pi / 2, n, dtype=np.float32)) ** 2
    audio = audio.copy()
    audio[:n] *= ramp
    audio[-n:] *= ramp[::-1]
    return audio


def stretch_pauses(audio: np.ndarray, sr: int, target: float, rng: random.Random, jitter: float,
                   min_gap: float = 0.35, floor_db: float = -45.0) -> np.ndarray:
    """Lengthen the silences between sentences inside a paragraph to `target` seconds (±jitter).
    Short gaps (commas, breaths) are left alone, so the paragraph keeps its natural intonation."""
    if audio.size == 0 or target <= 0:
        return audio
    frame = max(int(sr * 0.01), 1)
    n = audio.size // frame
    if n == 0:
        return audio
    rms = np.sqrt(np.mean(np.square(audio[: n * frame].reshape(n, frame)), axis=1) + 1e-12)
    quiet = 20 * np.log10(rms) < floor_db
    pieces, last, i = [], 0, 0
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            gap = (j - i) * frame / sr
            if gap >= min_gap and i > 0 and j < n:  # interior gap between two sentences
                want = target * (1 + rng.uniform(-jitter, jitter))
                if want > gap:
                    mid = (i + j) // 2 * frame
                    pieces.append(audio[last:mid])
                    pieces.append(np.zeros(int((want - gap) * sr), dtype=audio.dtype))
                    last = mid
            i = j
        else:
            i += 1
    pieces.append(audio[last:])
    return np.concatenate(pieces)


def cache_key(engine_id: str, text: str, speed: float) -> str:
    return hashlib.sha1(f"{engine_id}|{speed:.3f}|{text}".encode()).hexdigest()


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def chapter_time(t: float) -> str:
    t = int(t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


@dataclass
class RenderResult:
    wav_path: Path
    duration: float
    cues: list[tuple[float, float, str]]
    chapters: list[tuple[float, str]]
    synthesized: int
    cached: int


def _units(script: Script, unit: str):
    """Yield ("pause", seconds, None) or ("speech", [segments], after) groups.
    unit="paragraph": consecutive sentences up to a paragraph/chapter break are spoken in one go,
    so intonation flows like a person reading; unit="sentence": one sentence at a time."""
    group = []
    for seg in script.segments:
        if seg.kind == "pause":
            if group:
                yield "speech", group, "sentence"
                group = []
            yield "pause", seg.seconds, None
            continue
        group.append(seg)
        if unit == "sentence" or seg.after != "sentence":
            yield "speech", group, seg.after
            group = []
    if group:
        yield "speech", group, group[-1].after


def render(script: Script, engine: Engine, out_wav: Path, pacing: Pacing | None = None,
           cache_dir: Path | None = CACHE_DIR, lead_in: float = 2.0, tail: float = 6.0,
           unit: str | None = None, log=lambda msg: print(msg, file=sys.stderr)) -> RenderResult:
    p = pacing or Pacing()
    unit = unit or getattr(engine, "preferred_unit", "sentence")
    rng = random.Random(p.seed)
    sr = engine.sample_rate
    total_words = max(script.word_count(), 1)
    words_done = 0
    cues: list[tuple[float, float, str]] = []
    chapters: list[tuple[float, str]] = []
    t = 0.0
    synthesized = cached = 0
    started = time.time()
    groups = list(_units(script, unit))
    speech_groups = [g for g in groups if g[0] == "speech"]
    texts = [" ".join(s.text for s in g[1]) for g in speech_groups]
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)

    out_wav.parent.mkdir(parents=True, exist_ok=True)
    with sf.SoundFile(out_wav, "w", samplerate=sr, channels=1, subtype="PCM_24") as f:
        def silence(seconds: float) -> None:
            nonlocal t
            n = int(sr * max(seconds, 0))
            if n:
                f.write(np.zeros(n, dtype=np.float32))
                t += n / sr

        silence(lead_in)
        last_chapter = None
        done = 0
        for kind, payload, after in groups:
            if kind == "pause":
                silence(payload)
                continue
            segs = payload
            pos = words_done / total_words
            if segs[0].chapter != last_chapter and segs[0].chapter:
                chapters.append((t, segs[0].chapter))
                last_chapter = segs[0].chapter
            text = texts[done]
            speed = round(speed_at(pos, p), 3)
            inner = round(p.sentence_pause * pause_scale_at(pos, p), 2) if len(segs) > 1 else 0.0
            key = cache_key(f"{engine.engine_id}|{unit}|{inner}", text, speed)
            path = cache_dir / f"{key}.npy" if cache_dir else None
            if path and path.exists():
                audio = np.load(path)
                cached += 1
            else:
                if hasattr(engine, "context"):  # engines that use neighbouring text for continuity
                    engine.context = (texts[done - 1] if done else "", texts[done + 1] if done + 1 < len(texts) else "")
                audio = engine.synthesize(text, speed, inner)
                if path:
                    np.save(path, audio)
                synthesized += 1
            if len(segs) > 1:
                audio = stretch_pauses(audio, sr, p.sentence_pause * pause_scale_at(pos, p), rng, p.jitter)
            audio = fade(level_match(audio, p.target_level_db, p.max_gain_db), sr, p.fade_ms)
            start = t
            f.write(audio)
            t += audio.size / sr
            # Subtitle cues: split the group's time across its sentences by text length.
            total_chars = sum(len(s.text) for s in segs) or 1
            cursor = start
            for s in segs:
                span = (t - start) * len(s.text) / total_chars
                cues.append((cursor, cursor + span, s.text))
                cursor += span
            words_done += sum(len(s.text.split()) for s in segs)
            done += 1

            base = {"sentence": p.sentence_pause, "paragraph": p.paragraph_pause, "chapter": p.chapter_pause}[after]
            silence(base * pause_scale_at(pos, p) * (1 + rng.uniform(-p.jitter, p.jitter)))

            if done % 10 == 0 or done == len(speech_groups):
                elapsed = time.time() - started
                eta = elapsed / done * (len(speech_groups) - done)
                log(f"  {done}/{len(speech_groups)} {unit}s, {chapter_time(t)} of audio, ETA {eta / 60:.1f} min")
        silence(tail)
    if chapters and chapters[0][0] > 0:
        chapters[0] = (0.0, chapters[0][1])  # YouTube requires the first chapter at 0:00
    return RenderResult(out_wav, t, cues, chapters, synthesized, cached)


def write_srt(cues: list[tuple[float, float, str]], path: Path) -> None:
    lines = []
    for i, (a, b, text) in enumerate(cues, 1):
        lines += [str(i), f"{srt_time(a)} --> {srt_time(b)}", text, ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_chapters(chapters: list[tuple[float, str]], path: Path) -> None:
    path.write_text("\n".join(f"{chapter_time(t)} {title}" for t, title in chapters) + "\n", encoding="utf-8")
