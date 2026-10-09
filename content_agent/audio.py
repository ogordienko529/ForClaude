"""Audio for a project, all local: narration (Kokoro via sleep_voice), procedural music, final mix.

Narration is synthesised beat by beat (cached, so editing one beat re-voices only that beat) and the
start/end of every beat is recorded: the timeline cuts scenes on those times.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from sleep_voice.render import fade, level_match
from sleep_voice.text import normalize, split_sentences

CACHE_DIR = Path("~/.content_agent/cache/voice").expanduser()


@dataclass
class VoicePacing:
    speed: float = 0.94          # Kokoro speed; ~165 words per minute, a calm documentary read
    sentence_pause: float = 0.38
    beat_pause: float = 0.55     # between beats (scene changes)
    jitter: float = 0.12
    lead_in: float = 0.6
    tail: float = 1.6
    target_level_db: float = -20.0


FORMAT_PACING = {
    "explainer": VoicePacing(),
    "shorts": VoicePacing(speed=1.02, sentence_pause=0.22, beat_pause=0.25, lead_in=0.2, tail=0.8),
    "sleep": VoicePacing(speed=0.86, sentence_pause=0.9, beat_pause=2.0, lead_in=2.0, tail=6.0, target_level_db=-23),
}


def _beat_text(beat: dict) -> str:
    return normalize(beat["narration"])


def synthesize_voice(beats: list[dict], out_wav: Path, voice: str = "am_michael", fmt: str = "explainer",
                     engine=None, cache_dir: Path | None = CACHE_DIR, seed: int = 3, log=print) -> dict:
    """Returns {"duration": s, "beats": [{id, start, end, sentences: [{start, end, text}]}]}."""
    if engine is None:
        from sleep_voice.engine import make_engine

        engine = make_engine("kokoro", voice)
    p = FORMAT_PACING.get(fmt, VoicePacing())
    rng = random.Random(seed)
    sr = engine.sample_rate
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)

    chunks: list[np.ndarray] = [np.zeros(int(sr * p.lead_in), dtype=np.float32)]
    t = p.lead_in
    timing = []
    for i, beat in enumerate(beats):
        text = _beat_text(beat)
        sentences = split_sentences(text)
        key = hashlib.sha1(f"{engine.engine_id}|{p.speed}|{p.sentence_pause}|{text}".encode()).hexdigest()
        path = cache_dir / f"{key}.npy" if cache_dir else None
        if path and path.exists():
            audio = np.load(path)
        else:
            audio = engine.synthesize(text, p.speed, p.sentence_pause if len(sentences) > 1 else 0.0)
            if path:
                np.save(path, audio)
        audio = fade(level_match(audio, p.target_level_db, 8.0), sr, 10)
        start = t
        chunks.append(audio)
        t += audio.size / sr
        total_chars = sum(len(s) for s in sentences) or 1
        cursor, sent_cues = start, []
        for s in sentences:
            span = (t - start) * len(s) / total_chars
            sent_cues.append({"start": round(cursor, 3), "end": round(cursor + span, 3), "text": s})
            cursor += span
        timing.append({"id": beat["id"], "start": round(start, 3), "end": round(t, 3), "sentences": sent_cues})
        gap = (p.tail if i == len(beats) - 1 else p.beat_pause) * (1 + rng.uniform(-p.jitter, p.jitter))
        chunks.append(np.zeros(int(sr * gap), dtype=np.float32))
        t += gap
        log(f"  voice {i + 1}/{len(beats)} {beat['id']}: {audio.size / sr:.1f}s")
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(out_wav, np.concatenate(chunks), sr, subtype="PCM_24")
    return {"duration": round(t, 3), "sample_rate": sr, "beats": timing}


# ---------------------------------------------------------------- procedural music
NOTE = {n: i for i, n in enumerate("C C# D D# E F F# G G# A A# B".split())}


def _freq(name: str) -> float:
    pitch, octave = name[:-1], int(name[-1])
    return 440.0 * 2 ** ((NOTE[pitch] + 12 * (octave + 1) - 69) / 12)


MOODS = {
    # chord voicings, seconds per chord, brightness
    "calm": ([["A2", "E3", "A3", "C4", "E4"], ["F2", "C3", "F3", "A3", "C4"], ["C3", "G3", "C4", "E4", "G4"],
              ["G2", "D3", "G3", "B3", "D4"]], 7.5, 0.55),
    "tense": ([["D2", "A2", "D3", "F3", "A3"], ["A#1", "F2", "A#2", "D3", "F3"], ["C2", "G2", "C3", "D#3", "G3"],
               ["A1", "E2", "A2", "C#3", "E3"]], 6.0, 0.4),
    "uplifting": ([["C3", "G3", "C4", "E4", "G4"], ["G2", "D3", "G3", "B3", "D4"], ["A2", "E3", "A3", "C4", "E4"],
                   ["F2", "C3", "F3", "A3", "C4"]], 5.0, 0.7),
}


def _fft_convolve(x: np.ndarray, kernel: np.ndarray, block: int = 1 << 18) -> np.ndarray:
    """Overlap-add FFT convolution (memory-bounded, fast for hour-long signals)."""
    n = kernel.size
    nfft = 1 << int(math.ceil(math.log2(block + n)))
    K = np.fft.rfft(kernel, nfft)
    out = np.zeros(x.size + n, dtype=np.float32)
    for s in range(0, x.size, block):
        seg = x[s : s + block]
        y = np.fft.irfft(np.fft.rfft(seg, nfft) * K, nfft)[: seg.size + n]
        out[s : s + y.size] += y.astype(np.float32)
    return out


def _lowpass(x: np.ndarray, sr: int, cutoff: float, taps: int = 511) -> np.ndarray:
    """Windowed-sinc low-pass, zero phase (delay compensated)."""
    m = np.arange(taps) - (taps - 1) / 2
    h = np.sinc(2 * cutoff / sr * m) * np.blackman(taps)
    h = (h / h.sum()).astype(np.float32)
    d = (taps - 1) // 2
    return _fft_convolve(x, h)[d : d + x.size]


def _reverb(x: np.ndarray, sr: int, seconds: float = 2.8, mix: float = 0.35, seed: int = 1) -> np.ndarray:
    """Convolution with a synthetic decaying-noise impulse response."""
    rng = np.random.default_rng(seed)
    n = int(sr * seconds)
    ir = rng.standard_normal(n).astype(np.float32) * np.exp(-np.linspace(0, 7, n)).astype(np.float32)
    ir /= np.sqrt(np.sum(ir ** 2))
    return (1 - mix) * x + mix * _fft_convolve(x, ir)[: x.size]


def ambient_music(duration: float, mood: str = "calm", sr: int = 48_000, seed: int = 7) -> np.ndarray:
    """Soft evolving pads: detuned partials, slow crossfades between chords, sub bass, light reverb.
    Generated from scratch, so there is no licence or Content ID risk."""
    chords, seconds, bright = MOODS.get(mood, MOODS["calm"])
    rng = np.random.default_rng(seed)
    n = int(sr * duration)
    t = np.arange(n, dtype=np.float32) / sr
    out = np.zeros(n, dtype=np.float32)
    xfade = min(2.5, seconds / 2)
    k = 0
    start = 0.0
    while start < duration:
        chord = chords[k % len(chords)]
        a, b = max(start - xfade, 0), min(start + seconds + xfade, duration)
        i0, i1 = int(a * sr), int(b * sr)
        seg_t = t[i0:i1]
        env = np.ones_like(seg_t)
        rise = np.clip((seg_t - a) / xfade, 0, 1)
        fall = np.clip((b - seg_t) / xfade, 0, 1)
        env *= np.sin(rise * np.pi / 2) ** 2 * np.sin(fall * np.pi / 2) ** 2
        seg = np.zeros_like(seg_t)
        for j, note in enumerate(chord):
            f = _freq(note)
            amp = 0.5 if j == 0 else 0.22
            for det in (-0.12, 0.0, 0.11):  # cents-ish detune for width
                ff = f * (1 + det / 100)
                ph = rng.uniform(0, 2 * np.pi)
                seg += amp * (np.sin(2 * np.pi * ff * seg_t + ph) + bright * 0.18 * np.sin(4 * np.pi * ff * seg_t + ph))
        lfo = 0.85 + 0.15 * np.sin(2 * np.pi * 0.07 * seg_t + k)
        out[i0:i1] += seg * env * lfo
        start += seconds
        k += 1
    y = _lowpass(out, sr, 1800 + 1600 * bright)  # warmth
    y = _reverb(y, sr)
    fade_n = min(int(sr * 3), n // 3)
    y[:fade_n] *= np.linspace(0, 1, fade_n) ** 2
    y[-fade_n:] *= np.linspace(1, 0, fade_n) ** 2
    peak = float(np.max(np.abs(y))) or 1.0
    return (y / peak * 0.5).astype(np.float32)


# ---------------------------------------------------------------- final mix
def require_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not found (macOS: brew install ffmpeg; Windows: winget install ffmpeg)")
    return exe


LOUDNESS = {"explainer": -14.0, "shorts": -14.0, "sleep": -20.0, "gameplay": -14.0}


def mix(voice_wav: Path, music_wav: Path | None, out_wav: Path, fmt: str = "explainer",
        music_db: float = -19.0) -> dict:
    """Voice cleanup + music ducked under the voice + two-pass loudness normalisation."""
    import re

    ffmpeg = require_ffmpeg()
    target = LOUDNESS.get(fmt, -14.0)
    voice_chain = ("aresample=48000,aformat=channel_layouts=mono,highpass=f=75,equalizer=f=200:t=q:w=1:g=1.5,"
                   "deesser=i=0.3,acompressor=threshold=-22dB:ratio=2.5:attack=15:release=200:makeup=2")
    inputs = ["-i", str(voice_wav)]
    if music_wav:
        inputs += ["-i", str(music_wav)]
        graph = (f"[0:a]{voice_chain},asplit=2[v][sc];"
                 f"[1:a]aresample=48000,aformat=channel_layouts=mono,volume={music_db}dB[m];"
                 f"[m][sc]sidechaincompress=threshold=0.03:ratio=6:attack=30:release=500[md];"
                 f"[v][md]amix=inputs=2:normalize=0:duration=first[mix]")
    else:
        graph = f"[0:a]{voice_chain}[mix]"
    # Upmix before measuring: a mono signal copied to two channels is 3 LU louder.
    graph += ";[mix]pan=stereo|c0=c0|c1=c0[st]"
    ln = f"loudnorm=I={target}:TP=-1.5:LRA=11"
    probe = subprocess.run([ffmpeg, "-hide_banner", "-nostats", *inputs, "-filter_complex",
                            f"{graph};[st]{ln}:print_format=json[o]", "-map", "[o]", "-f", "null", "-"],
                           capture_output=True, text=True)
    if probe.returncode:
        raise RuntimeError(probe.stderr[-800:])
    st = json.loads(re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", probe.stderr)[-1])
    measured = (f":measured_I={st['input_i']}:measured_TP={st['input_tp']}:measured_LRA={st['input_lra']}"
                f":measured_thresh={st['input_thresh']}:offset={st['target_offset']}:linear=true")
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    run = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-y", *inputs, "-filter_complex",
                          f"{graph};[st]{ln}{measured}[o]", "-map", "[o]",
                          "-ar", "48000", "-c:a", "pcm_s16le", str(out_wav)], capture_output=True, text=True)
    if run.returncode:
        raise RuntimeError(run.stderr[-800:])
    return {"target_lufs": target, "input_lufs": float(st["input_i"])}


def loudnorm_file(in_wav: Path, out_wav: Path, target: float = -14.0, true_peak: float = -1.5) -> dict:
    """Two-pass loudness normalisation of any wav to a stereo 48 kHz file (mono is upmixed first,
    because copying mono to two channels raises loudness by 3 LU)."""
    import re

    ffmpeg = require_ffmpeg()
    channels = sf.info(str(in_wav)).channels
    pre = "aresample=48000" + (",pan=stereo|c0=c0|c1=c0" if channels == 1 else "")
    ln = f"loudnorm=I={target}:TP={true_peak}:LRA=11"
    probe = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-i", str(in_wav), "-af",
                            f"{pre},{ln}:print_format=json", "-f", "null", "-"], capture_output=True, text=True)
    if probe.returncode:
        raise RuntimeError(probe.stderr[-800:])
    st = json.loads(re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", probe.stderr)[-1])
    measured = (f":measured_I={st['input_i']}:measured_TP={st['input_tp']}:measured_LRA={st['input_lra']}"
                f":measured_thresh={st['input_thresh']}:offset={st['target_offset']}:linear=true")
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    run = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-y", "-i", str(in_wav), "-af", f"{pre},{ln}{measured}",
                          "-ar", "48000", "-c:a", "pcm_s16le", str(out_wav)], capture_output=True, text=True)
    if run.returncode:
        raise RuntimeError(run.stderr[-800:])
    return {"target_lufs": target, "input_lufs": float(st["input_i"])}
