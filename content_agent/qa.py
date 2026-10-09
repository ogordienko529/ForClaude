"""Self-review of a rendered video.

L1 (deterministic, ffmpeg): loudness, peaks, silence, black and frozen frames, scene lengths,
caption reading speed, A/V duration.
L2 prep (for a multimodal reviewer, e.g. Claude Code reading images): contact sheets with three
frames per scene, a one-frame-per-scene overview, a timed transcript and the review rubric.
Every finding carries the scene id, so fixes go back into exactly one storyboard beat.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .audio import LOUDNESS, require_ffmpeg

THRESHOLDS = {
    "explainer": {"max_scene_s": 14.0, "min_scene_s": 1.8, "freeze_s": 3.5, "silence_s": 1.6, "cps": 20},
    "shorts": {"max_scene_s": 5.0, "min_scene_s": 0.8, "freeze_s": 2.0, "silence_s": 0.8, "cps": 22},
    "sleep": {"max_scene_s": 60.0, "min_scene_s": 6.0, "freeze_s": 30.0, "silence_s": 9.0, "cps": 16},
    # fast gameplay edits: something must change every ~2 s, quick cuts are fine
    "gameplay": {"max_scene_s": 4.0, "min_scene_s": 0.3, "freeze_s": 1.5, "silence_s": 0.6, "cps": 18,
                 "max_gap_s": 2.2, "hook_s": 0.5, "min_total_s": 10.0, "max_total_s": 60.0},
}

RUBRIC = """Review rubric (score each 1-5 and list concrete fixes with scene ids):
1. Hook: do the first 5 s and first 30 s make a viewer want to keep watching?
2. Visual-narration match: does every scene show what is being said at that moment?
3. Readability: is on-screen text large, short, inside the frame and on screen long enough?
4. Variety and pacing: no scene feels static or repetitive; cuts follow the narration.
5. Accuracy: numbers, dates, places and map positions are right (check against sources).
6. Polish: no overlapping elements, clipped text, empty frames, wrong colours or glitches.
7. Audio: narration clear, music never competes with it, no abrupt jumps.
Write findings to review/review.json as
[{"scene": "b03", "severity": "high|medium|low", "category": "...", "problem": "...", "fix": "..."}]."""


RUBRIC_GAMEPLAY = """Review rubric for fast gameplay edits (score each 1-5, list fixes with segment ids):
1. Hook: is the subject visible in the very first frame, with text that makes you stay?
2. Clarity: in every segment, can you tell what is happening at phone size?
3. Pacing: something new every 1-2 s; no dead air; speed-ups on boring parts, slow-mo on the payoff.
4. Payoff: is the big moment set up (tension, freeze, silence) and hit hard (boom, shake, drop)?
5. Text: short, big, readable, inside the safe zone, never covering the action.
6. Sound: cuts and hits land on the beat; SFX support the moment instead of cluttering it.
7. Loop: does the end lead back into the start so the replay feels natural?
Write findings to review/review.json as
[{"scene": "s03", "severity": "high|medium|low", "category": "...", "problem": "...", "fix": "..."}]."""


@dataclass
class Finding:
    check: str
    severity: str           # high | medium | low
    message: str
    scene: str | None = None
    t_start: float | None = None
    t_end: float | None = None


def _ffmpeg(args: list[str]) -> str:
    r = subprocess.run([require_ffmpeg(), "-hide_banner", "-nostats", *args], capture_output=True, text=True)
    return r.stderr


def probe(video: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "stream=codec_type,width,height,r_frame_rate:format=duration", "-of", "json", str(video)],
                         capture_output=True, text=True)
    data = json.loads(out.stdout or "{}")
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    num, _, den = (v.get("r_frame_rate") or "0/1").partition("/")
    return {"duration": float(data.get("format", {}).get("duration", 0)), "width": v.get("width"),
            "height": v.get("height"), "fps": float(num) / float(den or 1), "has_audio": a is not None}


def _scene_at(t: float, scenes: list[dict], fps: int) -> str | None:
    f = t * fps
    for s in scenes:
        if s["from"] <= f < s["from"] + s["durationInFrames"]:
            return s["id"]
    return None


def technical_checks(video: Path, timeline: dict) -> tuple[list[Finding], dict]:
    fmt = timeline.get("format", "explainer")
    th = THRESHOLDS.get(fmt, THRESHOLDS["explainer"])
    fps = timeline["fps"]
    scenes = timeline["scenes"]
    findings: list[Finding] = []
    info = probe(video)

    expected = timeline["durationInFrames"] / fps
    if abs(info["duration"] - expected) > 0.5:
        findings.append(Finding("duration", "high", f"video is {info['duration']:.1f}s, timeline says {expected:.1f}s"))
    if (info["width"], info["height"]) != (timeline["width"], timeline["height"]):
        findings.append(Finding("resolution", "high", f"{info['width']}x{info['height']} != timeline size"))
    if not info["has_audio"]:
        findings.append(Finding("audio", "high", "no audio stream"))

    # Loudness
    err = _ffmpeg(["-i", str(video), "-af", "loudnorm=print_format=json", "-f", "null", "-"])
    m = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", err)
    loud = json.loads(m[-1]) if m else {}
    target = LOUDNESS.get(fmt, -14.0)
    if loud:
        i, tp = float(loud["input_i"]), float(loud["input_tp"])
        info.update(lufs=i, true_peak=tp, lra=float(loud["input_lra"]))
        if abs(i - target) > 1.5:
            findings.append(Finding("loudness", "medium", f"{i:.1f} LUFS, target {target:.0f}"))
        if tp > -1.0:
            findings.append(Finding("true_peak", "medium", f"true peak {tp:.1f} dBTP (> -1)"))

    # Silence inside the video (not at the very end)
    err = _ffmpeg(["-i", str(video), "-af", f"silencedetect=noise=-45dB:d={th['silence_s']}", "-f", "null", "-"])
    for s, e in zip(re.findall(r"silence_start: ([\d.]+)", err), re.findall(r"silence_end: ([\d.]+)", err)):
        s, e = float(s), float(e)
        if e < info["duration"] - 1.0 and s > 0.5:
            findings.append(Finding("silence", "medium", f"{e - s:.1f}s of silence", _scene_at(s, scenes, fps), s, e))

    # Black frames
    err = _ffmpeg(["-i", str(video), "-vf", "blackdetect=d=0.3:pic_th=0.95", "-an", "-f", "null", "-"])
    for s, e in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", err):
        findings.append(Finding("black_frames", "high", f"black frames {float(e) - float(s):.1f}s",
                                _scene_at(float(s), scenes, fps), float(s), float(e)))

    # Frozen picture: motion graphics should always move a little
    err = _ffmpeg(["-i", str(video), "-vf", f"freezedetect=n=0.0008:d={th['freeze_s']}", "-an", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"freeze_end: ([\d.]+)", err)]
    for s, e in zip(starts, ends + [info["duration"]] * (len(starts) - len(ends))):
        findings.append(Finding("static_picture", "medium", f"picture does not change for {e - s:.1f}s",
                                _scene_at(s, scenes, fps), s, e))

    # Scene lengths: a long scene is fine while new elements keep appearing on narration cues
    for s in scenes:
        dur = s["durationInFrames"] / fps
        t0 = s["from"] / fps
        events = sorted({0, s.get("speechOffset", 0), s["durationInFrames"],
                         *[c for c in s.get("cues") or [] if c is not None]})
        longest_still = max(b - a for a, b in zip(events, events[1:])) / fps
        if dur > th["max_scene_s"] and longest_still > th["max_scene_s"] * 0.6:
            findings.append(Finding("long_scene", "medium", f"scene lasts {dur:.1f}s (max {th['max_scene_s']:.0f}s): "
                                    "split the beat or add movement", s["id"], t0, t0 + dur))
        elif dur < th["min_scene_s"]:
            findings.append(Finding("short_scene", "low", f"scene lasts only {dur:.1f}s", s["id"], t0, t0 + dur))

    # Captions: characters per second
    for c in timeline.get("captions", []):
        dur = max((c["to"] - c["from"]) / fps, 0.01)
        cps = len(c["text"]) / dur
        if cps > th["cps"]:
            t0 = c["from"] / fps
            findings.append(Finding("caption_speed", "low", f"caption reads at {cps:.0f} chars/s: '{c['text'][:50]}'",
                                    _scene_at(t0, scenes, fps), t0, c["to"] / fps))
    return findings, info


def pacing_checks(timeline: dict) -> list[Finding]:
    """Fast-edit rules: a hook on screen at once, something new every ~2 s, sensible total length."""
    th = THRESHOLDS["gameplay"]
    fps = timeline["fps"]
    total = timeline["durationInFrames"] / fps
    out: list[Finding] = []
    events = {0}
    for c in timeline.get("clips", []):
        events.add(c["from"])
        if abs(c.get("zoomTo", 1) - c.get("zoom", 1)) > 0.05:  # a moving zoom counts as change
            events.update(range(c["from"], c["from"] + c["durationInFrames"], round(fps)))
    for x in timeline.get("texts", []) + timeline.get("badges", []):
        events.add(x["from"])
    ev = sorted(e for e in events if e <= timeline["durationInFrames"]) + [timeline["durationInFrames"]]
    for a, b in zip(ev, ev[1:]):
        if (b - a) / fps > th["max_gap_s"]:
            out.append(Finding("pacing", "medium", f"{(b - a) / fps:.1f}s without a cut, zoom or text: viewers swipe",
                               _scene_at(a / fps, timeline["scenes"], fps), a / fps, b / fps))
    texts = timeline.get("texts", [])
    if not any(x["from"] / fps <= th["hook_s"] for x in texts):
        out.append(Finding("hook", "high", f"no text on screen in the first {th['hook_s']}s"))
    if total < th["min_total_s"] or total > th["max_total_s"]:
        out.append(Finding("length", "medium", f"{total:.1f}s; fast edits work best at "
                                               f"{th['min_total_s']:.0f}-{th['max_total_s']:.0f}s"))
    for x in texts:
        if len(x["text"].replace("*", "").split()) > 6:
            out.append(Finding("text_length", "low", f"'{x['text'][:40]}' has more than 6 words",
                               _scene_at(x["from"] / fps, timeline["scenes"], fps), x["from"] / fps))
    return out


# ---------------------------------------------------------------- contact sheets
def _font(size: int) -> ImageFont.ImageFont:
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/System/Library/Fonts/Helvetica.ttc",
                 "C:/Windows/Fonts/arialbd.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _grab(video: Path, t: float, out: Path, width: int = 480) -> Path:
    subprocess.run([require_ffmpeg(), "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
                    "-vf", f"scale={width}:-2", str(out)], check=True)
    return out


def contact_sheets(video: Path, timeline: dict, outdir: Path, per_sheet: int = 6) -> list[Path]:
    """Three frames per scene (early / middle / late) with scene id and timecodes burned in."""
    fps = timeline["fps"]
    thumb = 480 if timeline["width"] >= timeline["height"] else 220
    frames_dir = outdir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for s in timeline["scenes"]:
        t0, dur = s["from"] / fps, s["durationInFrames"] / fps
        shots = []
        for k, frac in enumerate((0.15, 0.55, 0.92)):
            t = t0 + dur * frac
            shots.append((t, _grab(video, t, frames_dir / f"{s['id']}_{k}.png", width=thumb)))
        rows.append((s, shots))
    sheets = []
    font, small = _font(22), _font(18)
    for n in range(0, len(rows), per_sheet):
        chunk = rows[n : n + per_sheet]
        w, h = thumb, Image.open(chunk[0][1][0][1]).height
        label_w = 190
        sheet = Image.new("RGB", (label_w + 3 * (w + 8), len(chunk) * (h + 8) + 8), (18, 18, 22))
        draw = ImageDraw.Draw(sheet)
        for r, (s, shots) in enumerate(chunk):
            y = 8 + r * (h + 8)
            t0 = s["from"] / fps
            draw.text((10, y + 8), s["id"], font=font, fill=(255, 210, 90))
            draw.text((10, y + 40), s["template"], font=small, fill=(200, 200, 210))
            draw.text((10, y + 66), f"{_tc(t0)}-{_tc(t0 + s['durationInFrames'] / fps)}", font=small,
                      fill=(160, 160, 170))
            for c, (t, img) in enumerate(shots):
                x = label_w + c * (w + 8)
                sheet.paste(Image.open(img), (x, y))
                draw.rectangle([x, y + h - 26, x + 86, y + h], fill=(0, 0, 0))
                draw.text((x + 6, y + h - 24), _tc(t), font=small, fill=(255, 255, 255))
        path = outdir / f"sheet_{n // per_sheet + 1:02d}.png"
        sheet.save(path)
        sheets.append(path)
    return sheets


def overview(video: Path, timeline: dict, outdir: Path, cols: int = 6) -> Path:
    """One mid-scene frame per scene in a grid: the whole video at a glance."""
    fps = timeline["fps"]
    imgs = []
    tw = 320 if timeline["width"] >= timeline["height"] else 180
    for s in timeline["scenes"]:
        t = (s["from"] + s["durationInFrames"] * 0.6) / fps
        imgs.append((s["id"], _grab(video, t, outdir / "frames" / f"ov_{s['id']}.png", width=tw)))
    w, h = tw, Image.open(imgs[0][1]).height
    rows = (len(imgs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (w + 6) + 6, rows * (h + 6) + 6), (18, 18, 22))
    draw = ImageDraw.Draw(sheet)
    font = _font(18)
    for i, (sid, img) in enumerate(imgs):
        x, y = 6 + (i % cols) * (w + 6), 6 + (i // cols) * (h + 6)
        sheet.paste(Image.open(img), (x, y))
        draw.rectangle([x, y, x + 54, y + 24], fill=(0, 0, 0))
        draw.text((x + 5, y + 2), sid, font=font, fill=(255, 210, 90))
    path = outdir / "overview.png"
    sheet.save(path)
    return path


def _tc(t: float) -> str:
    m, s = divmod(t, 60)
    return f"{int(m)}:{s:04.1f}"


def run_qa(project: Path, video: Path, timeline: dict, storyboard_issues: list | None = None) -> dict:
    review = project / "review"
    review.mkdir(parents=True, exist_ok=True)
    findings, info = technical_checks(video, timeline)
    rubric = RUBRIC
    if timeline.get("kind") == "gameplay":
        findings += pacing_checks(timeline)
        rubric = RUBRIC_GAMEPLAY
    sheets = contact_sheets(video, timeline, review)
    ov = overview(video, timeline, review)
    fps = timeline["fps"]
    transcript = "\n".join(f"[{_tc(c['from'] / fps)}] {c['text']}" for c in timeline.get("captions", []))
    (review / "transcript.txt").write_text(transcript + "\n", encoding="utf-8")
    report = {
        "video": str(video),
        "info": info,
        "findings": [asdict(f) for f in findings],
        "storyboard_warnings": [str(i) for i in (storyboard_issues or [])],
        "sheets": [str(p) for p in sheets],
        "overview": str(ov),
        "transcript": str(review / "transcript.txt"),
        "rubric": rubric,
    }
    (review / "qa.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = [f"# QA: {timeline.get('title', '')}", "",
             f"Duration {info['duration']:.1f}s · {info['width']}x{info['height']} · {info.get('lufs', 0):.1f} LUFS "
             f"· true peak {info.get('true_peak', 0):.1f} dBTP", ""]
    if findings:
        lines.append("| Severity | Scene | Check | Finding |")
        lines.append("|---|---|---|---|")
        for f in sorted(findings, key=lambda f: ("high", "medium", "low").index(f.severity)):
            when = f" ({_tc(f.t_start)})" if f.t_start is not None else ""
            lines.append(f"| {f.severity} | {f.scene or '-'}{when} | {f.check} | {f.message} |")
    else:
        lines.append("No technical issues found.")
    lines += ["", "Contact sheets: " + ", ".join(p.name for p in sheets), f"Overview: {ov.name}", "", rubric]
    (review / "qa.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report
