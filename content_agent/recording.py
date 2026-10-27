"""Narration from the creator's own recording instead of a synthetic voice (`voice_engine: "recording"`).

The creator reads `lines.md` (one line per beat, a pause of about two seconds between lines) into a
phone or a microphone and drops the file into the project. This module:

1. decodes the file (any format ffmpeg reads: m4a, ogg, mp3, wav);
2. finds the spoken segments between the pauses (energy envelope, noise floor from the file itself);
3. matches the segments to the beats by their expected length (words per minute), so a retake read
   right after a fumbled line replaces the first take; extra silence and clicks are dropped;
4. cleans each line (high-pass against rumble, equal loudness, fades) and assembles voice.wav with
   the same pacing gaps as the synthetic engines, writing the same timing JSON.

Per-beat files (`"audio": "voice/b03.m4a"`) override the split for single lines, and
`"voice_segments": [[start, end], ...]` in the storyboard pins the split by hand.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

import numpy as np
import soundfile as sf

from sleep_voice.render import fade, level_match
from sleep_voice.text import split_sentences

from .audio import FORMAT_PACING, VoicePacing, _lowpass

SR = 24_000
FRAME_S = 0.02
WORDS_PER_SECOND = 2.6   # a lively YouTube read; only the ratio between lines matters for the matching
SKIP_COST = 0.35         # a segment left unused (a retake, a cough) costs this much in the matching


class RecordingError(ValueError):
    """The recording cannot be mapped onto the beats; the message says what to change."""


def decode(path: Path, sr: int = SR) -> np.ndarray:
    from .music_lib import decode as _decode

    return _decode(path, sr=sr, channels=1)


# ---------------------------------------------------------------- segments
def envelope_db(y: np.ndarray, sr: int, frame_s: float = FRAME_S) -> np.ndarray:
    n = max(int(sr * frame_s), 1)
    frames = len(y) // n
    if frames == 0:
        return np.full(1, -120.0)
    rms = np.sqrt(np.mean(np.square(y[: frames * n].reshape(frames, n)), axis=1) + 1e-12)
    return 20 * np.log10(rms + 1e-9)


def segments(y: np.ndarray, sr: int, *, min_gap: float = 0.7, min_len: float = 0.25, pad: float = 0.12,
             threshold_db: float | None = None, frame_s: float = FRAME_S) -> list[tuple[float, float]]:
    """Spoken stretches as (start, end) seconds, split where the signal stays near the noise floor for
    at least `min_gap`. The threshold sits between the room noise and the speech of this very file."""
    return segments_from_envelope(envelope_db(y, sr, frame_s), frame_s, len(y) / sr, min_gap=min_gap,
                                  min_len=min_len, pad=pad, threshold_db=threshold_db)


def segments_from_envelope(env: np.ndarray, frame_s: float, total: float, *, min_gap: float = 0.7,
                           min_len: float = 0.25, pad: float = 0.12,
                           threshold_db: float | None = None) -> list[tuple[float, float]]:
    """`segments` on a level envelope in dB (one value per `frame_s`), for audio too long to hold in memory."""
    if threshold_db is None:
        floor = float(np.percentile(env, 15))
        loud = float(np.percentile(env, 90))
        threshold_db = max(floor + 8.0, min(floor + 0.45 * (loud - floor), loud - 6.0), -55.0)
    speech = env > threshold_db
    out: list[list[float]] = []
    gap_frames = max(int(round(min_gap / frame_s)), 1)
    i, n = 0, len(speech)
    while i < n:
        if not speech[i]:
            i += 1
            continue
        j = i
        quiet = 0
        while j < n and quiet < gap_frames:
            quiet = 0 if speech[j] else quiet + 1
            j += 1
        end = j - quiet
        out.append([i * frame_s, end * frame_s])
        i = j
    segs = [(a, b) for a, b in out if b - a >= min_len]
    padded = []
    for k, (a, b) in enumerate(segs):
        lo = max(a - pad, 0.0, padded[-1][1] if padded else 0.0)
        hi = min(b + pad, total, segs[k + 1][0] if k + 1 < len(segs) else total)
        padded.append((round(lo, 3), round(hi, 3)))
    return padded


# ---------------------------------------------------------------- matching
def expected_seconds(narration: str, wps: float = WORDS_PER_SECOND) -> float:
    words = len(narration.split())
    sentences = max(len(split_sentences(narration)), 1)
    return words / wps + 0.25 * (sentences - 1)


def match(expected: list[float], durations: list[float]) -> list[int]:
    """Index of the segment for every beat, in order, so that segment lengths fit the expected
    lengths best; unused segments are retakes or noise. Among equal fits the later take wins."""
    n, m = len(expected), len(durations)
    if m < n:
        raise RecordingError(f"found {m} spoken lines in the recording but the script has {n} beats")
    best: tuple[float, list[int]] | None = None
    naive = sum(durations) / max(sum(expected), 1e-6)
    for scale in (naive * f for f in (0.6, 0.75, 0.9, 1.0, 1.1, 1.3, 1.5)):
        exp = [e * scale for e in expected]
        INF = float("inf")
        # dp[i][j]: best cost with beats[:i] matched using segments[:j]
        dp = [[INF] * (m + 1) for _ in range(n + 1)]
        choice = [[0] * (m + 1) for _ in range(n + 1)]   # 1 = segment j-1 used for beat i-1, 0 = skipped
        dp[0][0] = 0.0
        for j in range(1, m + 1):
            dp[0][j] = dp[0][j - 1] + SKIP_COST
        for i in range(1, n + 1):
            for j in range(i, m + 1):
                skip = dp[i][j - 1] + SKIP_COST
                use = dp[i - 1][j - 1] + abs(math.log(max(durations[j - 1], 0.05) / max(exp[i - 1], 0.05)))
                if use <= skip:          # ties: use the later segment (a retake replaces the first try)
                    dp[i][j], choice[i][j] = use, 1
                else:
                    dp[i][j], choice[i][j] = skip, 0
        picks: list[int] = []
        i, j = n, m
        while i > 0:
            if choice[i][j]:
                picks.append(j - 1)
                i -= 1
            j -= 1
        picks.reverse()
        if best is None or dp[n][m] < best[0]:
            best = (dp[n][m], picks)
    assert best is not None
    return best[1]


# ---------------------------------------------------------------- assembly
def clean(y: np.ndarray, sr: int, target_db: float, fade_ms: float = 12.0) -> np.ndarray:
    y = y.astype(np.float32)
    if y.size > sr // 10:
        y = y - _lowpass(y, sr, 80.0)          # phone rumble, handling noise, breath thumps
    y = level_match(y, target_db, 14.0)
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    if peak > 0.95:
        y = y * (0.95 / peak)
    return fade(y, sr, fade_ms)


def write_lines(storyboard: dict, out: Path) -> Path:
    """lines.md: what to read, in order, plus the recording rules the splitter relies on."""
    beats = storyboard.get("beats", [])
    words = sum(len((b.get("narration") or "").split()) for b in beats)
    L = [f"# Lines to record: {storyboard.get('title', '')}", "",
         f"{len(beats)} lines, about {words} words, roughly {words / 150:.1f} minutes of speech.", "",
         "How to record (the tool splits the file on your pauses):", "",
         "- One take, one file. Phone 15-20 cm from your mouth, quiet room, no music.",
         "- Read a line, then stay silent for 2 seconds, then the next line. Do not read the numbers.",
         "- Fumbled a line? Stay silent 2 seconds and read the whole line again. The later take is used.",
         "- Send the recording as a file (Voice Memos, or Telegram as a *file*, not a voice message).",
         "- Drop it into the project folder as `voice/narration.m4a` (ogg, mp3 and wav are fine too).", "",
         "---", ""]
    for i, b in enumerate(beats, 1):
        L.append(f"**{i}.** ({b.get('id', '')}) {b.get('narration', '').strip()}")
        L.append("")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")
    return out


def _timing_entry(beat: dict, start: float, end: float, source: dict) -> dict:
    sentences = split_sentences(beat["narration"].strip())
    total_chars = sum(len(s) for s in sentences) or 1
    cursor, cues = start, []
    for s in sentences:
        span = (end - start) * len(s) / total_chars
        cues.append({"start": round(cursor, 3), "end": round(cursor + span, 3), "text": s})
        cursor += span
    return {"id": beat["id"], "start": round(start, 3), "end": round(end, 3), "sentences": cues, "source": source}


def assemble_recording(beats: list[dict], storyboard: dict, project: Path, out_wav: Path, fmt: str = "review",
                       *, sr: int = SR, seed: int = 3, min_gap: float | None = None, log=print) -> dict:
    """voice.wav + timing (same shape as synthesize_voice) from the creator's recording(s)."""
    p: VoicePacing = FORMAT_PACING.get(fmt, VoicePacing())
    rng = random.Random(seed)
    per_beat = [b.get("audio") for b in beats]
    sources: list[tuple[np.ndarray, dict]] = [None] * len(beats)  # type: ignore[list-item]

    need_split = [i for i, a in enumerate(per_beat) if not a]
    if need_split:
        rec = storyboard.get("voice_recording")
        if not rec:
            raise RecordingError('voice_engine "recording" needs "voice_recording": "voice/narration.m4a" '
                                 '(or an "audio" file on every beat)')
        path = project / rec
        if not path.exists():
            raise RecordingError(f"recording not found: {path}. Record lines.md and drop the file there")
        y = decode(path, sr)
        if y.size < sr // 2:
            raise RecordingError(f"recording {rec} is empty or shorter than half a second")
        pinned = storyboard.get("voice_segments")
        if pinned:
            segs = [(float(a), float(b)) for a, b in pinned]
            if len(segs) != len(need_split):
                raise RecordingError(f"voice_segments has {len(segs)} entries but {len(need_split)} beats need one")
            picks = list(range(len(segs)))
        else:
            gap = min_gap if min_gap is not None else float(storyboard.get("voice_split_gap", 0.7))
            segs = segments(y, sr, min_gap=gap)
            expected = [expected_seconds(beats[i]["narration"]) for i in need_split]
            durs = [b - a for a, b in segs]
            try:
                picks = match(expected, durs)
            except RecordingError as exc:
                listing = ", ".join(f"{a:.1f}-{b:.1f}s" for a, b in segs[:40])
                raise RecordingError(
                    f"{exc}. Segments found: {listing}. Pauses between lines were shorter than {gap:.1f}s: "
                    f"re-record with 2-second pauses, lower \"voice_split_gap\" (e.g. 0.45), or pin "
                    f"\"voice_segments\": [[start, end], ...] by hand") from None
            unused = len(segs) - len(picks)
            log(f"  recording {rec}: {len(segs)} spoken lines, {len(picks)} used, {unused} dropped (retakes/noise)")
        for i, k in zip(need_split, picks):
            a, b = segs[k]
            sources[i] = (y[int(a * sr):int(b * sr)], {"file": rec, "start": round(a, 3), "end": round(b, 3)})
    for i, a in enumerate(per_beat):
        if a:
            path = project / a
            if not path.exists():
                raise RecordingError(f"beat {beats[i]['id']}: audio file not found: {path}")
            z = decode(path, sr)
            segs_i = segments(z, sr, min_gap=0.5)
            if segs_i:   # trim the leading/trailing silence of a single-line file
                z = z[int(segs_i[0][0] * sr):int(segs_i[-1][1] * sr)]
            sources[i] = (z, {"file": a, "start": 0.0, "end": round(len(z) / sr, 3)})

    chunks: list[np.ndarray] = [np.zeros(int(sr * p.lead_in), dtype=np.float32)]
    t = p.lead_in
    timing = []
    for i, (beat, (audio, src)) in enumerate(zip(beats, sources)):
        audio = clean(audio, sr, p.target_level_db)
        start = t
        chunks.append(audio)
        t += audio.size / sr
        timing.append(_timing_entry(beat, start, t, src))
        gap = (p.tail if i == len(beats) - 1 else p.beat_pause) * (1 + rng.uniform(-p.jitter, p.jitter))
        chunks.append(np.zeros(int(sr * gap), dtype=np.float32))
        t += gap
        exp = expected_seconds(beat["narration"])
        flag = "" if 0.5 <= (audio.size / sr) / max(exp, 0.1) <= 2.0 else "  <- length differs from the text, check"
        log(f"  line {i + 1}/{len(beats)} {beat['id']}: {audio.size / sr:.1f}s{flag}")
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(out_wav, np.concatenate(chunks), sr, subtype="PCM_24")
    return {"duration": round(t, 3), "sample_rate": sr, "engine": "recording", "beats": timing}
