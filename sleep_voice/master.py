"""Sleep mastering with ffmpeg: softer, warmer, even and quiet.

Chain (in order):
  highpass 70 Hz      - remove rumble
  lowpass 9 kHz       - take the edge off hiss and crisp consonants
  +2 dB @ 180 Hz      - warmth / chest
  -3 dB @ 3.5 kHz     - soften presence (the "alert" range of the voice)
  de-esser            - tame sharp s / sh
  gentle compressor   - no sudden loud words
  [optional bed]      - brown/pink noise or your own rain/ambience file, far below the voice
  loudnorm (2-pass)   - quiet, consistent loudness (default -20 LUFS, below YouTube's -14)
  true-peak ceiling   - -3 dBTP, no peaks
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Mastering:
    loudness_lufs: float = -20.0
    true_peak_db: float = -3.0
    lra: float = 6.0
    lowpass_hz: int = 9000
    highpass_hz: int = 70
    warmth_db: float = 2.0
    presence_cut_db: float = -3.0
    deess: float = 0.35
    background: str = "none"         # none | brown | pink | path to an audio file (looped)
    background_db: float = -30.0     # bed level relative to the voice
    bitrate: str = "192k"


CODECS = {
    ".mp3": ["-c:a", "libmp3lame"],
    ".m4a": ["-c:a", "aac"],
    ".aac": ["-c:a", "aac"],
    ".wav": ["-c:a", "pcm_s24le"],
    ".flac": ["-c:a", "flac"],
}


def require_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("ffmpeg not found. Install it (macOS: brew install ffmpeg; "
                           "Windows: winget install ffmpeg; Linux: apt install ffmpeg).")
    return exe


def voice_chain(m: Mastering) -> str:
    return ",".join([
        f"highpass=f={m.highpass_hz}",
        f"lowpass=f={m.lowpass_hz}:p=2",
        f"equalizer=f=180:t=q:w=0.9:g={m.warmth_db}",
        f"equalizer=f=3500:t=q:w=1.2:g={m.presence_cut_db}",
        f"deesser=i={m.deess}:m=0.5:f=0.5",
        "acompressor=threshold=-26dB:ratio=2.5:attack=25:release=300:knee=6:makeup=2",
    ])


def _inputs_and_graph(src: Path, m: Mastering, duration: float) -> tuple[list[str], str]:
    args = ["-i", str(src)]
    graph = f"[0:a]{voice_chain(m)}[v]"
    if m.background in ("brown", "pink"):
        args += ["-f", "lavfi", "-t", f"{duration:.2f}", "-i",
                 f"anoisesrc=color={m.background}:amplitude=0.5:sample_rate=48000"]
        graph += f";[1:a]lowpass=f=900,highpass=f=40,volume={m.background_db}dB[b];[v][b]amix=inputs=2:normalize=0:duration=first[mix]"
        return args, graph
    if m.background not in ("", "none"):
        args += ["-stream_loop", "-1", "-i", m.background]
        graph += (f";[1:a]aformat=channel_layouts=mono,volume={m.background_db}dB,afade=t=in:d=8[b];"
                  f"[v][b]amix=inputs=2:normalize=0:duration=first[mix]")
        return args, graph
    return args, graph.replace("[v]", "[mix]")


def master(src: Path, dst: Path, duration: float, m: Mastering | None = None) -> dict:
    """Two-pass EBU R128 loudness normalisation for an exact, stable level over hours of audio."""
    m = m or Mastering()
    ffmpeg = require_ffmpeg()
    inputs, graph = _inputs_and_graph(src, m, duration)
    ln = f"loudnorm=I={m.loudness_lufs}:TP={m.true_peak_db}:LRA={m.lra}"

    probe = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostats", *inputs, "-filter_complex", f"{graph};[mix]{ln}:print_format=json[o]",
         "-map", "[o]", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    if probe.returncode != 0:
        raise RuntimeError(f"ffmpeg analysis failed: {probe.stderr[-800:]}")
    stats = json.loads(re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", probe.stderr)[-1])
    measured = (f":measured_I={stats['input_i']}:measured_TP={stats['input_tp']}"
                f":measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}"
                f":offset={stats['target_offset']}:linear=true")

    dst.parent.mkdir(parents=True, exist_ok=True)
    codec = CODECS.get(dst.suffix.lower())
    if codec is None:
        raise ValueError(f"unsupported output format {dst.suffix}; use one of {', '.join(CODECS)}")
    bitrate = ["-b:a", m.bitrate] if dst.suffix.lower() in (".mp3", ".m4a", ".aac") else []
    run = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostats", "-y", *inputs, "-filter_complex", f"{graph};[mix]{ln}{measured}[o]",
         "-map", "[o]", "-ar", "48000", "-ac", "1", *codec, *bitrate, str(dst)],
        capture_output=True, text=True,
    )
    if run.returncode != 0:
        raise RuntimeError(f"ffmpeg mastering failed: {run.stderr[-800:]}")
    return {"input_lufs": float(stats["input_i"]), "target_lufs": m.loudness_lufs, "output": str(dst)}


def measure_loudness(path: Path) -> float:
    ffmpeg = require_ffmpeg()
    r = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-i", str(path), "-af", "loudnorm=print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True)
    return float(json.loads(re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr)[-1])["input_i"])
