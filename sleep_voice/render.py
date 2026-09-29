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


def render(script: Script, engine: Engine, out_wav: Path, pacing: Pacing | None = None,
           cache_dir: Path | None = CACHE_DIR, lead_in: float = 2.0, tail: float = 6.0,
           log=lambda msg: print(msg, file=sys.stderr)) -> RenderResult:
    p = pacing or Pacing()
    rng = random.Random(p.seed)
    sr = engine.sample_rate
    total_words = max(script.word_count(), 1)
    words_done = 0
    cues: list[tuple[float, float, str]] = []
    chapters: list[tuple[float, str]] = []
    t = 0.0
    synthesized = cached = 0
    started = time.time()
    sentences = script.sentences
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
        for i, seg in enumerate(script.segments):
            pos = words_done / total_words
            if seg.kind == "pause":
                silence(seg.seconds)
                continue
            if seg.chapter != last_chapter and seg.chapter:
                chapters.append((t, seg.chapter))
                last_chapter = seg.chapter
            speed = round(speed_at(pos, p), 3)
            key = cache_key(engine.engine_id, seg.text, speed)
            path = cache_dir / f"{key}.npy" if cache_dir else None
            if path and path.exists():
                audio = np.load(path)
                cached += 1
            else:
                audio = engine.synthesize(seg.text, speed)
                if path:
                    np.save(path, audio)
                synthesized += 1
            audio = fade(level_match(audio, p.target_level_db, p.max_gain_db), sr, p.fade_ms)
            start = t
            f.write(audio)
            t += audio.size / sr
            cues.append((start, t, seg.text))
            words_done += len(seg.text.split())

            base = {"sentence": p.sentence_pause, "paragraph": p.paragraph_pause, "chapter": p.chapter_pause}[seg.after]
            silence(base * pause_scale_at(pos, p) * (1 + rng.uniform(-p.jitter, p.jitter)))

            done = sum(1 for s in script.segments[: i + 1] if s.kind == "sentence")
            if done % 25 == 0 or done == len(sentences):
                elapsed = time.time() - started
                eta = elapsed / done * (len(sentences) - done)
                log(f"  {done}/{len(sentences)} sentences, {chapter_time(t)} of audio, ETA {eta / 60:.1f} min")
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
