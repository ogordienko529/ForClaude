"""Long videos from a recording with live commentary (the creator talks while playing).

A narrated review is written and voiced after the session; viewers of horror and survival mods hear it
as a script. Here the voice is the one recorded live, on its own OBS track, and the edit only cuts:

1. `analyze`  reads the recording's audio tracks: when the creator speaks (voice track), when they
              react (a sudden jump in voice level: a scream, a laugh), loud game moments (game track) and
              dead stretches (no speech, little motion). Optional transcript with faster-whisper.
2. The agent writes `cut.json`: a cold open and the segments to keep, in order, with chapters.
3. `render`   cuts video, voice and game for every segment, joins them with short audio fades, ducks
              the game under the voice, normalises to -14 LUFS and writes out/video.mp4, the stems
              (out/voice_stem.wav, out/game_stem.wav) and out/description.md with chapters.
4. `dub`      mixes a dubbed voice (e.g. ElevenLabs dubbing of out/voice_stem.wav into English with the
              creator's own cloned voice, which keeps the live intonation and timing) with the game stem:
              out/video_en.mp4, plus out/audio_original.m4a to upload as a second language track.

cut.json:
{
  "title": "I Tamed the Wrong Dog in Minecraft",
  "voice_track": 1,          # audio stream of the microphone (OBS track 2 -> 1); null when there is only a mix
  "game_track": 2,           # audio stream of the game (OBS track 3 -> 2); null: game sound comes from voice_track
  "voice_gain_db": 0, "game_gain_db": -4, "duck_db": 6,
  "fps": 30, "height": 1080,
  "cold_open": [{"src": "footage/rec.mp4", "in": 4021.5, "out": 4026.0}],
  "segments": [{"id": "c01", "src": "footage/rec.mp4", "in": 12.0, "out": 47.5, "chapter": "The dog"}]
}
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import numpy as np

from .schema import Issue

SR = 48_000
FADE_S = 0.04
RULES = {"cold_open_max_s": 8.0, "first_reaction_by_s": 30.0, "dead_air_s": 2.5, "segment_max_s": 90.0,
         "min_total_s": 240.0}


# ---------------------------------------------------------------- probing and audio
def audio_streams(video: Path) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                          "-of", "csv=p=0", str(video)], capture_output=True, text=True, check=True).stdout
    return len([x for x in out.split() if x.strip()])


def read_audio(video: Path, track: int, start: float | None = None, duration: float | None = None,
               channels: int = 1, sr: int = SR) -> np.ndarray:
    """One audio stream as float32, mono (n,) or stereo (n, 2)."""
    cmd = ["ffmpeg", "-v", "error", "-nostdin"]
    if start is not None:
        cmd += ["-ss", f"{max(start, 0):.3f}"]
    if duration is not None:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-i", str(video), "-map", f"0:a:{track}", "-ac", str(channels), "-ar", str(sr), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    y = np.frombuffer(raw[: len(raw) // 4 * 4], np.float32)
    return y.reshape(-1, channels) if channels > 1 else y


def power(video: Path, track: int, frame_s: float = 0.025, sr: int = 16_000, chunk_s: float = 60.0) -> np.ndarray:
    """Mean square of one audio stream per `frame_s`, read a minute at a time: a 4-hour track needs a few MB,
    not the gigabytes of the whole waveform."""
    n = int(sr * frame_s)
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-i", str(video), "-map", f"0:a:{track}", "-ac", "1",
           "-ar", str(sr), "-f", "f32le", "-"]
    out, rest = [], np.zeros(0, np.float32)
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:
        while raw := proc.stdout.read(int(chunk_s * sr) * 4):
            y = np.concatenate([rest, np.frombuffer(raw[: len(raw) // 4 * 4], np.float32)])
            k = len(y) // n * n
            if k:
                out.append(np.mean(np.square(y[:k].reshape(-1, n), dtype=np.float64), axis=1))
            rest = y[k:]
    if proc.returncode:
        raise RuntimeError(f"ffmpeg could not read audio stream {track} of {video}")
    return np.concatenate(out) if out else np.zeros(1)


def power_db(pw: np.ndarray, group: int = 1) -> np.ndarray:
    """Power frames in dB, `group` frames averaged into one."""
    if group > 1 and len(pw) >= group:
        pw = pw[: len(pw) // group * group].reshape(-1, group).mean(axis=1)
    return 10 * np.log10(pw + 1e-12)


def level_db(y: np.ndarray, sr: int, win: float = 0.25) -> np.ndarray:
    n = max(int(sr * win), 1)
    m = y if y.ndim == 1 else y.mean(axis=1)
    frames = len(m) // n
    if frames == 0:
        return np.array([-120.0])
    rms = np.sqrt(np.mean(np.square(m[: frames * n].reshape(frames, n)), axis=1) + 1e-12)
    return 20 * np.log10(rms + 1e-9)


def reactions_from(db: np.ndarray, step: float, above_talk_db: float = 8.0, gap_s: float = 2.0) -> list[dict]:
    """Moments where the voice is much louder than the creator's normal talking level: screams, laughs, shouts.
    Measured against the median level of speech, so the start of an ordinary sentence is not a reaction."""
    talking = db[db > -40]
    if len(talking) < 4:
        return []
    talk = float(np.median(talking))
    out: list[dict] = []
    for i in range(len(db)):
        if db[i] >= talk + above_talk_db and db[i] > -30 and (i + 1 == len(db) or db[i] >= db[i + 1]):
            t = round(i * step, 2)
            if not out or t - out[-1]["t"] > gap_s:
                out.append({"t": t, "above_talk_db": round(float(db[i] - talk), 1)})
    return out


# ---------------------------------------------------------------- analysis
def analyze(video: Path, voice_track: int | None, game_track: int | None, transcribe: bool = False,
            log=print) -> dict[str, Any]:
    """Speech, reactions, loud game moments and dead stretches of one recording, in seconds."""
    from .gameplay import analyze as visual
    from .recording import segments_from_envelope

    n_tracks = audio_streams(video)
    for name, t in (("voice_track", voice_track), ("game_track", game_track)):
        if t is not None and t >= n_tracks:
            raise ValueError(f"{name} {t} does not exist: the recording has {n_tracks} audio stream(s) (0-{n_tracks - 1})")
    saved = video.with_suffix(".analysis.json")          # written by `footage` on import: hours of decoding saved
    if saved.exists() and saved.stat().st_mtime >= video.stat().st_mtime:
        vis = json.loads(saved.read_text(encoding="utf-8"))
        log(f"motion and events from {saved.name}")
    else:
        vis = visual(video)
    out: dict[str, Any] = {"video": str(video), "duration": vis["duration"], "audio_streams": n_tracks,
                           "voice_track": voice_track, "game_track": game_track}
    speech, reactions = [], []
    if voice_track is not None:
        pw = power(video, voice_track)                                    # 25 ms frames
        speech = [{"start": a, "end": b} for a, b in
                  segments_from_envelope(power_db(pw), 0.025, len(pw) * 0.025, min_gap=0.6, min_len=0.3)]
        reactions = reactions_from(power_db(pw, 10), 0.25)
    game_events = [e for e in vis["events"] if e["kind"] in ("burst", "loud", "action")]
    if game_track is not None:
        gdb = power_db(power(video, game_track), 20)                    # 0.5 s
        game_events += [{"t": round(i * 0.5, 1), "kind": "game_loud", "score": round(float(gdb[i] - np.median(gdb[max(i - 6, 0):i])), 1)}
                        for i in range(3, len(gdb)) if gdb[i] > -35 and gdb[i] - np.median(gdb[max(i - 6, 0):i]) >= 12]
    game_events.sort(key=lambda e: e["t"])
    # dead: no speech for 8+ s and below-median motion
    motion = {p["t"]: p["motion"] for p in vis["per_second"]}
    med = float(np.median(list(motion.values()))) if motion else 0.0
    talk = np.zeros(int(vis["duration"]) + 1, bool)
    for s in speech:
        talk[int(s["start"]):int(s["end"]) + 1] = True
    dead, start = [], None
    for t in range(len(talk)):
        quiet = not talk[t] and motion.get(t, 0) <= med
        if quiet and start is None:
            start = t
        elif not quiet and start is not None:
            if t - start >= 8:
                dead.append({"start": start, "end": t})
            start = None
    out.update(speech=speech, reactions=reactions, game_events=game_events[:400], dead=dead,
               talk_share=round(float(talk.mean()), 2) if len(talk) else 0.0)
    if transcribe and voice_track is not None:
        out["transcript"] = transcribe_voice(video, voice_track, log=log)
    return out


def transcribe_voice(video: Path, voice_track: int, model: str = "small", log=print) -> list[dict] | None:
    """Timed transcript of the voice track with faster-whisper (local, free); None if it is not installed."""
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        log("transcript skipped: pip install faster-whisper (local, free) to get one")
        return None
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "voice.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(video), "-map", f"0:a:{voice_track}",
                        "-ac", "1", "-ar", "16000", str(wav)], check=True)
        segs, info = WhisperModel(model, device="auto", compute_type="int8").transcribe(str(wav), vad_filter=True)
        return [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segs]


def to_markdown(a: dict) -> str:
    def tc(t):
        t = int(t)
        return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"
    L = [f"# Commentary analysis: {Path(a['video']).name}", "",
         f"{a['duration'] / 60:.1f} min, {a['audio_streams']} audio streams, you talk {a['talk_share']:.0%} of the time, "
         f"{len(a['reactions'])} reactions, {len(a['dead'])} dead stretches of 8+ s.", "",
         "## Reactions (voice jumps: screams, laughs) - candidates for the cold open and the Shorts", ""]
    L += [f"- {tc(r['t'])} (+{r['above_talk_db']} dB over your talking level)" for r in a["reactions"][:60]]
    L += ["", "## Dead stretches (no talking, little motion) - cut these", ""]
    L += [f"- {tc(d['start'])}-{tc(d['end'])}" for d in a["dead"][:80]]
    if a.get("transcript"):
        L += ["", "## Transcript", ""] + [f"[{tc(s['start'])}] {s['text']}" for s in a["transcript"]]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- cut.json
def load(project: Path) -> dict:
    return json.loads((project / "cut.json").read_text(encoding="utf-8"))


def parts(cut: dict) -> list[dict]:
    return [{**p, "cold": True} for p in cut.get("cold_open", [])] + [dict(p) for p in cut.get("segments", [])]


def validate_cut(project: Path, cut: dict) -> list[Issue]:
    from .gameplay import probe

    issues: list[Issue] = []
    ps = parts(cut)
    if not cut.get("segments"):
        return [Issue("error", None, "cut.json has no segments")]
    lengths: dict[str, tuple[float, int]] = {}
    total = 0.0
    for i, p in enumerate(ps):
        pid = p.get("id") or ("cold" if p.get("cold") else f"#{i + 1}")
        src = project / p.get("src", "")
        if not src.exists():
            issues.append(Issue("error", pid, f"source not found: {p.get('src')}"))
            continue
        if p["src"] not in lengths:
            lengths[p["src"]] = (probe(src)["duration"], audio_streams(src))
        dur, n_tracks = lengths[p["src"]]
        a, b = float(p.get("in", 0)), float(p.get("out", 0))
        if b <= a:
            issues.append(Issue("error", pid, f"out ({b}) must be after in ({a})"))
        elif b > dur + 0.05:
            issues.append(Issue("error", pid, f"out {b:.1f}s is past the end of {p['src']} ({dur:.1f}s)"))
        for name in ("voice_track", "game_track"):
            t = cut.get(name)
            if t is not None and t >= n_tracks:
                issues.append(Issue("error", pid, f"{name} {t} does not exist in {p['src']} ({n_tracks} audio streams)"))
        total += max(b - a, 0)
        if not p.get("cold") and b - a > RULES["segment_max_s"]:
            issues.append(Issue("warning", pid, f"{b - a:.0f}s in one piece: cut the quiet parts out, viewers leave in "
                                                f"long stretches without a new event"))
    cold = sum(float(p["out"]) - float(p["in"]) for p in cut.get("cold_open", []))
    if not cut.get("cold_open"):
        issues.append(Issue("warning", None, "no cold open: start on the strongest 3-8 s (a scare, a scream, the payoff), "
                                             "on the narrated videos 54% of viewers were gone by 0:30"))
    elif cold > RULES["cold_open_max_s"]:
        issues.append(Issue("warning", None, f"cold open is {cold:.1f}s: keep it to {RULES['cold_open_max_s']:.0f} s"))
    if cut.get("voice_track") is None:
        issues.append(Issue("warning", None, "voice_track is null: no separate voice, so no voice stem for dubbing "
                                             "(record with OBS on 3 tracks: mix, microphone, game)"))
    if total < RULES["min_total_s"]:
        issues.append(Issue("warning", None, f"{total / 60:.1f} min in total: the horror-mod hits run 9-20 min"))
    chapters = [p for p in cut["segments"] if p.get("chapter")]
    if chapters and (chapters[0] is not cut["segments"][0] or len(chapters) < 3):
        issues.append(Issue("warning", None, "YouTube chapters need one on the first segment and at least 3"))
    return issues


# ---------------------------------------------------------------- render
def _fade(y: np.ndarray, sr: int, s: float = FADE_S) -> np.ndarray:
    n = min(int(sr * s), len(y) // 2)
    if n <= 1:
        return y
    ramp = np.linspace(0, 1, n, dtype=np.float32)
    if y.ndim == 2:
        ramp = ramp[:, None]
    y = y.copy()
    y[:n] *= ramp
    y[-n:] *= ramp[::-1]
    return y


def _fit(y: np.ndarray, n: int) -> np.ndarray:
    if len(y) >= n:
        return y[:n]
    pad = np.zeros((n - len(y),) + y.shape[1:], np.float32)
    return np.concatenate([y, pad])


def duck(game: np.ndarray, voice: np.ndarray, sr: int, duck_db: float, win: float = 0.05) -> np.ndarray:
    """Lower the game while the voice is talking, smoothly (about 150 ms attack/release)."""
    if duck_db <= 0 or not len(voice):
        return game
    n = max(int(sr * win), 1)
    frames = len(voice) // n + 1
    v = _fit(voice, frames * n).reshape(frames, n)
    talking = (20 * np.log10(np.sqrt(np.mean(v * v, axis=1)) + 1e-9)) > -40
    target = np.where(talking, 10 ** (-duck_db / 20), 1.0).astype(np.float32)
    k = 3
    smooth = np.convolve(np.pad(target, (k, k), mode="edge"), np.ones(2 * k + 1) / (2 * k + 1), mode="valid")
    gain = np.repeat(smooth, n)[: len(game)].astype(np.float32)
    return game * (gain[:, None] if game.ndim == 2 else gain)


def render(project: Path, draft: bool = False, log=print) -> dict:
    import soundfile as sf

    cut = load(project)
    errors = [i for i in validate_cut(project, cut) if i.level == "error"]
    if errors:
        raise ValueError("cut.json has errors:\n" + "\n".join(str(e) for e in errors))
    out = project / "out"
    tmp = out / "parts"
    tmp.mkdir(parents=True, exist_ok=True)
    fps = int(cut.get("fps", 30))
    height = int(cut.get("height", 1080)) // (2 if draft else 1)
    vt, gt = cut.get("voice_track"), cut.get("game_track")
    vg, gg = 10 ** (float(cut.get("voice_gain_db", 0)) / 20), 10 ** (float(cut.get("game_gain_db", -4)) / 20)
    voices, games, list_lines, marks = [], [], [], []
    t = 0.0
    ps = parts(cut)
    for i, p in enumerate(ps):
        src = project / p["src"]
        a, b = float(p["in"]), float(p["out"])
        frames = max(int(round((b - a) * fps)), 1)
        dur = frames / fps            # whole frames, so the voice does not drift off the picture over many cuts
        clip = tmp / f"p{i:03d}.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-nostdin", "-ss", f"{a:.3f}", "-t", f"{dur + 1:.3f}", "-i", str(src),
                        "-an", "-frames:v", str(frames),
                        "-vf", f"scale=-2:{height},fps={fps},format=yuv420p", "-c:v", "libx264",
                        "-preset", "veryfast" if draft else "medium", "-crf", "24" if draft else "20", str(clip)],
                       check=True)
        n = int(round(dur * SR))
        voice = _fit(read_audio(src, vt, a, dur), n) * vg if vt is not None else np.zeros(n, np.float32)
        game_src = gt if gt is not None else (vt if vt is not None else 0)
        game = _fit(read_audio(src, game_src, a, dur, channels=2), n) * gg if (gt is not None or vt is None) else \
            np.zeros((n, 2), np.float32)
        voices.append(_fade(voice, SR))
        games.append(_fade(game, SR))
        list_lines.append(f"file '{clip.name}'")
        marks.append({"id": p.get("id"), "start": round(t, 2), "chapter": p.get("chapter"), "cold": bool(p.get("cold"))})
        t += dur
        p["dur"] = dur
        log(f"  part {i + 1}/{len(ps)}: {p.get('src')} {a:.1f}-{b:.1f}s")
    voice = np.concatenate(voices) if voices else np.zeros(0, np.float32)
    game = np.concatenate(games) if games else np.zeros((0, 2), np.float32)
    game = duck(game, voice, SR, float(cut.get("duck_db", 6)) if vt is not None and gt is not None else 0)
    mix = game + voice[:, None]
    peak = float(np.max(np.abs(mix))) if mix.size else 0
    if peak > 0.98:
        mix *= 0.98 / peak
    sf.write(out / "voice_stem.wav", voice, SR, subtype="PCM_24")
    sf.write(out / "game_stem.wav", game, SR, subtype="PCM_24")
    sf.write(tmp / "mix.wav", mix, SR, subtype="PCM_24")
    (tmp / "list.txt").write_text("\n".join(list_lines) + "\n", encoding="utf-8")
    video = out / "video.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-nostdin", "-f", "concat", "-safe", "0", "-i", str(tmp / "list.txt"),
                    "-i", str(tmp / "mix.wav"), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                    "-shortest", str(video)], check=True)
    desc = description(project, cut, marks)
    tl = {"kind": "commentary", "title": cut.get("title", ""), "fps": fps, "width": int(height * 16 / 9) // 2 * 2,
          "height": height, "durationInFrames": int(round(t * fps)), "format": "review",
          "scenes": [{"id": m["id"] or f"p{i}", "template": "footage", "from": int(round(m["start"] * fps)),
                      "durationInFrames": int(round(ps[i]["dur"] * fps))}
                     for i, m in enumerate(marks)],
          "captions": [], "marks": marks}
    (project / "timeline.json").write_text(json.dumps(tl, indent=1) + "\n", encoding="utf-8")
    return {"video": str(video), "duration": round(t, 2), "parts": len(ps), "description": str(desc),
            "voice_stem": str(out / "voice_stem.wav"), "game_stem": str(out / "game_stem.wav")}


def description(project: Path, cut: dict, marks: list[dict]) -> Path:
    def tc(s):
        s = int(s)
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"
    lines = [cut.get("title", ""), ""]
    chapters = [m for m in marks if m.get("chapter")]
    if chapters:
        lines.append("Chapters:")
        for k, m in enumerate(chapters):
            lines.append(f"{tc(0 if k == 0 else m['start'])} {m['chapter']}")
        lines.append("")
    for c in cut.get("credits", []):
        extra = ", ".join(x for x in (c.get("author"), c.get("license")) if x)
        lines.append(f"- {c['name']}" + (f" ({extra})" if extra else "") + (f": {c['url']}" if c.get("url") else ""))
    out = project / "out" / "description.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


# ---------------------------------------------------------------- dubbing
def dub(project: Path, voice_file: Path, log=print) -> dict:
    """Swap the live voice for a dubbed one (same timing) and keep the original as a language track."""
    import soundfile as sf

    from .music_lib import decode

    out = project / "out"
    game, sr = sf.read(out / "game_stem.wav", dtype="float32")
    orig, _ = sf.read(out / "voice_stem.wav", dtype="float32")
    dubbed = decode(voice_file, sr=sr, channels=1)
    note = None
    if abs(len(dubbed) - len(orig)) > sr * 0.5:
        note = f"dubbed voice is {len(dubbed) / sr:.1f}s, the cut is {len(orig) / sr:.1f}s: padded or trimmed to fit"
        log("  " + note)
    dubbed = _fit(dubbed, len(orig))
    cut = load(project)
    game2 = duck(game, dubbed, sr, float(cut.get("duck_db", 6)))
    mix = game2 + dubbed[:, None]
    peak = float(np.max(np.abs(mix))) if mix.size else 0
    if peak > 0.98:
        mix *= 0.98 / peak
    tmp = out / "parts"
    tmp.mkdir(parents=True, exist_ok=True)
    sf.write(tmp / "mix_dub.wav", mix, sr, subtype="PCM_24")
    video_en = out / "video_en.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-nostdin", "-i", str(out / "video.mp4"), "-i", str(tmp / "mix_dub.wav"),
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", str(video_en)], check=True)
    original = out / "audio_original.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-nostdin", "-i", str(out / "video.mp4"), "-vn", "-c:a", "copy",
                    str(original)], check=True)
    return {"video_en": str(video_en), "audio_original": str(original), "note": note}


# ---------------------------------------------------------------- QA
def qa(project: Path) -> dict:
    """Technical checks, the opening at phone size, dead air in the cut and the first reaction time."""
    from .qa import Finding, first_frames, technical_checks

    tl = json.loads((project / "timeline.json").read_text(encoding="utf-8"))
    video = project / "out" / "video.mp4"
    findings, info = technical_checks(video, tl)
    findings = [f for f in findings if f.check not in ("long_scene", "short_scene")]   # live footage runs long
    import soundfile as sf

    voice, sr = sf.read(project / "out" / "voice_stem.wav", dtype="float32")
    game, _ = sf.read(project / "out" / "game_stem.wav", dtype="float32")
    both = level_db(game.mean(axis=1) + voice if len(voice) else game.mean(axis=1), sr, 0.5)
    run = 0
    for i, d in enumerate(both):
        run = run + 1 if d < -45 else 0
        if run * 0.5 == RULES["dead_air_s"]:
            findings.append(Finding("dead_air", "medium", f"{RULES['dead_air_s']} s without voice or game sound", None,
                                    (i + 1) * 0.5 - RULES["dead_air_s"], (i + 1) * 0.5))
    vdb = level_db(voice, sr) if len(voice) else np.array([-120.0])
    first_voice = next((i * 0.25 for i, d in enumerate(vdb) if d > -40), None)
    if first_voice is None or first_voice > 1.5:
        findings.append(Finding("opening_voice", "medium", "your voice is not heard in the first 1.5 s: open on a "
                                                           "reaction, not on silent footage", None, 0, 1.5))
    jumps = [r["t"] for r in reactions_from(vdb, 0.25)]
    if not jumps or jumps[0] > RULES["first_reaction_by_s"]:
        findings.append(Finding("first_reaction", "high", f"no reaction (a voice jump) in the first "
                                                          f"{RULES['first_reaction_by_s']:.0f} s: viewers from the feed "
                                                          f"decide by 0:30", None, 0, RULES["first_reaction_by_s"]))
    ff = first_frames(video, project / "review" / "first_frame.png", (0.1, 3.0))
    review = project / "review"
    review.mkdir(parents=True, exist_ok=True)
    lines = [f"# QA (live commentary): {tl.get('title', '')}", "",
             f"Duration {info['duration'] / 60:.1f} min · {info.get('lufs', 0):.1f} LUFS · true peak "
             f"{info.get('true_peak', 0):.1f} dBTP", "", "| Severity | When | Check | Finding |", "|---|---|---|---|"]
    for f in sorted(findings, key=lambda f: ("high", "medium", "low").index(f.severity)):
        when = f"{int(f.t_start // 60)}:{int(f.t_start % 60):02d}" if f.t_start is not None else "-"
        lines.append(f"| {f.severity} | {when} | {f.check} | {f.message} |")
    if not findings:
        lines.append("| - | - | - | no findings |")
    lines += ["", f"Opening at phone size: {ff.name if ff else '-'} (frames at 0.1 s and 3 s): is the strongest moment "
                  f"on screen and does it read without context?",
              "After upload, Studio: audience retention at 0:30 (the narrated videos kept 46%; aim for 60%+)."]
    (review / "qa.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"findings": [f.__dict__ for f in findings], "first_frame": str(ff) if ff else None,
            "qa": str(review / "qa.md")}
