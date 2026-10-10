"""Fast vertical edits of gameplay footage (no voice-over): analysis, edit list, soundtrack, timeline.

Workflow (driven by Claude Code, see .claude/skills/edit-gameplay/SKILL.md):

1. `footage`  copies the raw recording into the project, measures motion / bursts / idle stretches
              and draws footage sheets (one frame per second with timecodes) to look at.
2. The agent writes `edit.json`: which moments to use, in what order, how fast, with which zooms,
              texts, effects and sound effects. Cuts can be given in beats so they land on the music.
3. `build`    turns edit.json into a soundtrack (procedural beat + SFX, -14 LUFS) and timeline.json.
4. `render`   renders 1080x1920 with the Remotion "Gameplay" composition; `qa` checks pacing and
              draws contact sheets for review.

edit.json:
{
  "title": "I built a house... then TNT",
  "style": "meme",                      # text + cut style: meme | boxed | pixel | comic | neon | clean
  "framing": "crop",                    # crop: fill 9:16 around `focus`; fit: whole frame on a blurred copy
                                        # (a segment can override it, e.g. "fit" for wide shots and timelapses)
  "music": {"style": "phonk", "bpm": 140, "drop": "s05", "volume_db": -4},
  "sfx_on_text": "pop",                 # automatic SFX when a text appears (or null)
  "progress_bar": true,
  "segments": [
    {"id": "s01", "src": "footage/raw.mp4", "in": 65.2, "beats": 2, "speed": 1,
     "zoom": 1.15, "zoom_to": 1.5, "focus": [0.45, 0.5], "punch": false, "framing": "fit",
     "fx": ["shake", "flash", "bw"],
     "text": {"text": "POV: your *house*", "style": "hook|caption|big|label", "at": 0, "dur": null,
              "target": [0.5, 0.6]},     # label arrow target (fraction of the output frame)
     "badge": "x8",
     "transition": "flash",            # optional: this cut's transition (default: the style's)
     "sfx": [{"name": "boom", "at": 0.0}],
     "freeze": {"dur": 0.8, "text": "WAIT...", "zoom": 1.12, "bw": true, "music_stop": true}}
  ]
}
Times inside a segment (`at`) are output seconds from the segment start.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .schema import Issue

FPS = 30
OUT_W, OUT_H = 1080, 1920
TEXT_STYLES = ("hook", "caption", "big", "label")
FX = ("shake", "flash", "bw")
MUSIC_STYLES = ("phonk", "hype", "none")
# Text + cut styles for Shorts (remotion/src/gameplay/Gameplay.tsx SHORT_STYLES)
SHORT_STYLES = {
    "meme": "white uppercase with a thick black outline, yellow key word, hard cuts (default)",
    "boxed": "every word on its own coloured box, popping in one by one, zoom-blur cuts",
    "pixel": "pixel font with a hard shadow, in-game tooltip boxes, pixel-dissolve cuts",
    "comic": "speech bubbles and comic-book reaction words, white flash cuts",
    "neon": "glowing Orbitron text, cyan key word, glitch cuts",
    "clean": "white rounded boxes with dark text, orange key word, whip-pan cuts",
}
CUTS = ("cut", "zoomblur", "pixel", "flash", "glitch", "whip")


# ---------------------------------------------------------------- footage analysis
def probe(video: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "stream=codec_type,width,height,r_frame_rate:format=duration", "-of", "json", str(video)],
                         capture_output=True, text=True, check=True)
    data = json.loads(out.stdout)
    v = next(s for s in data["streams"] if s["codec_type"] == "video")
    num, _, den = v["r_frame_rate"].partition("/")
    return {"duration": float(data["format"]["duration"]), "width": v["width"], "height": v["height"],
            "fps": float(num) / float(den or 1),
            "has_audio": any(s["codec_type"] == "audio" for s in data["streams"])}


def _frames(video: Path, fps: float, w: int = 160, h: int = 90) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"fps={fps},scale={w}:{h}",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)


def analyze(video: Path, sample_fps: float = 10.0) -> dict:
    """Per-second motion, 'burst' (sudden bright / fiery colour change) and idle stretches."""
    info = probe(video)
    fr = _frames(video, sample_fps).astype(np.float32)
    gray = fr.mean(axis=3)
    motion = np.concatenate([[0.0], np.abs(np.diff(gray, axis=0)).mean(axis=(1, 2))])
    r, g, b = fr[..., 0], fr[..., 1], fr[..., 2]
    hot = ((r > 200) & (g > 70) & (g < 210) & (b < 110)).mean(axis=(1, 2))  # fire, explosions, lava
    bright = gray.mean(axis=(1, 2))
    n_sec = int(np.ceil(len(fr) / sample_fps))
    per_sec = []
    for s in range(n_sec):
        sl = slice(int(s * sample_fps), int((s + 1) * sample_fps))
        if not len(motion[sl]):
            break
        per_sec.append({"t": s, "motion": round(float(motion[sl].mean()), 2), "hot": round(float(hot[sl].max()), 3),
                        "bright": round(float(bright[sl].mean()), 1)})
    m = np.array([p["motion"] for p in per_sec])
    h = np.array([p["hot"] for p in per_sec])
    events = []
    # bursts: fiery colour appearing suddenly (explosions, lava, fire)
    for i in range(1, len(h)):
        jump = h[i] - h[max(i - 3, 0):i].mean()
        if jump > 0.02:
            events.append({"t": per_sec[i]["t"], "kind": "burst", "score": round(float(jump), 3)})
    # action peaks: motion well above this recording's normal
    hi = np.percentile(m, 85) if len(m) else 0
    for i, p in enumerate(per_sec):
        if m[i] >= hi and m[i] > 2 and (i == 0 or m[i] >= m[i - 1]) and (i + 1 == len(m) or m[i] >= m[i + 1]):
            events.append({"t": p["t"], "kind": "action", "score": round(float(m[i]), 2)})
    # idle: low motion for 2+ seconds (cut or speed up)
    lo = max(np.percentile(m, 25) if len(m) else 0, 0.6)
    idle, start = [], None
    for i, p in enumerate(per_sec + [{"t": len(per_sec), "motion": 99}]):
        if p["motion"] <= lo and start is None:
            start = p["t"]
        elif p["motion"] > lo and start is not None:
            if p["t"] - start >= 2:
                idle.append({"start": start, "end": p["t"]})
            start = None
    events.sort(key=lambda e: e["t"])
    return {"video": str(video), **info, "per_second": per_sec, "events": events, "idle": idle}


def footage_sheets(video: Path, analysis: dict, outdir: Path, every: float = 1.0, cols: int = 10,
                   rows: int = 8) -> list[Path]:
    """One frame per `every` seconds with timecode, motion bar (blue) and burst bar (orange)."""
    from PIL import Image, ImageDraw

    from .qa import _font

    outdir.mkdir(parents=True, exist_ok=True)
    w, h = 256, int(256 * analysis["height"] / analysis["width"])
    fr = _frames(video, 1 / every, w, h)
    per = {p["t"]: p for p in analysis["per_second"]}
    mmax = max([p["motion"] for p in analysis["per_second"]] + [1])
    font = _font(15)
    sheets = []
    per_sheet = cols * rows
    for k in range(0, len(fr), per_sheet):
        chunk = fr[k : k + per_sheet]
        r = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * (w + 4) + 4, r * (h + 4) + 4), (18, 18, 22))
        draw = ImageDraw.Draw(sheet)
        for i, img in enumerate(chunk):
            t = (k + i) * every
            x, y = 4 + (i % cols) * (w + 4), 4 + (i // cols) * (h + 4)
            sheet.paste(Image.fromarray(img), (x, y))
            draw.rectangle([x, y, x + 62, y + 19], fill=(0, 0, 0))
            draw.text((x + 4, y + 1), f"{int(t // 60)}:{t % 60:04.1f}", font=font, fill=(255, 220, 80))
            p = per.get(int(t), {"motion": 0, "hot": 0})
            draw.rectangle([x, y + h - 6, x + int(w * min(p["motion"] / mmax, 1)), y + h - 3], fill=(80, 170, 255))
            draw.rectangle([x, y + h - 3, x + int(w * min(p["hot"] * 8, 1)), y + h], fill=(255, 140, 40))
        path = outdir / f"footage_{k // per_sheet + 1:02d}.png"
        sheet.save(path)
        sheets.append(path)
    return sheets


def import_footage(project: Path, videos: list[Path]) -> dict:
    """Copy recordings into <project>/footage, analyse them and draw footage sheets."""
    (project / "footage").mkdir(parents=True, exist_ok=True)
    report = {}
    for v in videos:
        dest = project / "footage" / v.name
        if v.resolve() != dest.resolve():
            shutil.copy2(v, dest)
        a = analyze(dest)
        sheets = footage_sheets(dest, a, project / "review" / dest.stem)
        a["sheets"] = [str(s) for s in sheets]
        (project / "footage" / f"{dest.stem}.analysis.json").write_text(json.dumps(a, indent=1) + "\n")
        report[f"footage/{dest.name}"] = a
    if not (project / "edit.json").exists() and not (project / "storyboard.json").exists():
        first = next(iter(report))
        skeleton = {"title": "", "framing": "crop", "music": {"style": "phonk", "bpm": 140, "drop": None},
                    "sfx_on_text": "pop", "progress_bar": True,
                    "segments": [{"id": "s01", "src": first, "in": 0.0, "beats": 2, "speed": 1,
                                  "text": {"text": "Hook text", "style": "hook"}}]}
        (project / "edit.json").write_text(json.dumps(skeleton, indent=2) + "\n")
    return report


# ---------------------------------------------------------------- edit list
@dataclass
class Edit:
    data: dict
    project: Path

    @classmethod
    def load(cls, project: Path) -> "Edit":
        return cls(json.loads((project / "edit.json").read_text(encoding="utf-8")), project)

    @property
    def segments(self) -> list[dict]:
        return self.data.get("segments", [])

    @property
    def bpm(self) -> float:
        return float((self.data.get("music") or {}).get("bpm", 140))

    def seg_duration(self, s: dict) -> float:
        """Output seconds of the moving part of a segment (freeze excluded)."""
        if "beats" in s:
            return float(s["beats"]) * 60 / self.bpm
        return float(s.get("dur", 1.0))


def _texts(s: dict) -> list[dict]:
    t = s.get("text")
    if not t:
        return []
    items = t if isinstance(t, list) else [t]
    return [{"text": x, "style": "caption"} if isinstance(x, str) else x for x in items]


def _sfx(s: dict) -> list[dict]:
    return [{"name": x, "at": 0.0} if isinstance(x, str) else x for x in s.get("sfx", [])]


def validate_edit(edit: Edit, durations: dict[str, float] | None = None) -> list[Issue]:
    from .sound import SFX_NAMES

    issues: list[Issue] = []
    segs = edit.segments
    if not segs:
        return [Issue("error", None, "edit.json has no segments")]
    music = edit.data.get("music") or {}
    if music.get("style", "phonk") not in MUSIC_STYLES:
        issues.append(Issue("error", None, f"music.style must be one of {MUSIC_STYLES}"))
    if not 60 <= edit.bpm <= 200:
        issues.append(Issue("error", None, "music.bpm must be 60-200"))
    ids = [s.get("id") for s in segs]
    if music.get("drop") and music["drop"] not in ids:
        issues.append(Issue("error", None, f"music.drop {music['drop']!r} is not a segment id"))
    if edit.data.get("style", "meme") not in SHORT_STYLES:
        issues.append(Issue("error", None, f"style must be one of {tuple(SHORT_STYLES)}"))
    if edit.data.get("framing", "crop") not in ("crop", "fit"):
        issues.append(Issue("error", None, "framing must be crop or fit"))
    durations = durations or {}
    seen, total = set(), 0.0
    for i, s in enumerate(segs):
        sid = s.get("id") or f"#{i + 1}"
        if sid in seen:
            issues.append(Issue("error", sid, "duplicate segment id"))
        seen.add(sid)
        src = s.get("src")
        if not src or not (edit.project / src).exists():
            issues.append(Issue("error", sid, f"source {src!r} not found in the project"))
            continue
        speed = float(s.get("speed", 1))
        if not 0.1 <= speed <= 16:
            issues.append(Issue("error", sid, "speed must be 0.1-16"))
        dur = edit.seg_duration(s)
        if dur <= 0:
            issues.append(Issue("error", sid, "duration must be positive"))
            continue
        span = dur * speed
        src_len = durations.get(src)
        if src_len is None:
            src_len = probe(edit.project / src)["duration"]
            durations[src] = src_len
        if float(s.get("in", 0)) < 0 or float(s.get("in", 0)) + span > src_len + 0.05:
            issues.append(Issue("error", sid, f"in {s.get('in')} + {span:.2f}s of source runs past the end ({src_len:.1f}s)"))
        for key in ("zoom", "zoom_to"):
            if key in s and not 1 <= float(s[key]) <= 4:
                issues.append(Issue("error", sid, f"{key} must be 1-4"))
        if s.get("transition") and s["transition"] not in CUTS:
            issues.append(Issue("error", sid, f"transition must be one of {CUTS}"))
        if s.get("framing", "crop") not in ("crop", "fit"):
            issues.append(Issue("error", sid, "framing must be crop or fit"))
        f = s.get("focus", [0.5, 0.5])
        if not (isinstance(f, list) and len(f) == 2 and all(0 <= v <= 1 for v in f)):
            issues.append(Issue("error", sid, "focus must be [x, y] fractions 0-1"))
        for fx in s.get("fx", []):
            if fx not in FX:
                issues.append(Issue("error", sid, f"unknown fx {fx!r} (use {FX})"))
        for x in _sfx(s):
            if x.get("name") not in SFX_NAMES:
                issues.append(Issue("error", sid, f"unknown sfx {x.get('name')!r} (use {SFX_NAMES})"))
        for t in _texts(s):
            if t.get("style", "caption") not in TEXT_STYLES:
                issues.append(Issue("error", sid, f"unknown text style {t.get('style')!r}"))
            words = len(t.get("text", "").replace("*", "").split())
            if words > 6:
                issues.append(Issue("warning", sid, f"text has {words} words: keep on-screen text to 1-6 words"))
        fr = s.get("freeze")
        if fr and not 0.2 <= float(fr.get("dur", 0.8)) <= 2.5:
            issues.append(Issue("warning", sid, "freeze should last 0.2-2.5 s"))
        has_change = bool(_texts(s) or s.get("zoom_to") or s.get("fx") or s.get("badge"))
        if dur > 3.5 and not has_change:
            issues.append(Issue("warning", sid, f"{dur:.1f}s with nothing changing: cut it shorter or add a zoom/text"))
        total += dur + (float(fr.get("dur", 0.8)) if fr else 0)
    if total < 8:
        issues.append(Issue("warning", None, f"only {total:.1f}s total"))
    try:  # structure advice; a broken edit list already has errors above
        issues += retention_checks(edit, durations)
    except (ValueError, TypeError, KeyError, ZeroDivisionError):
        pass
    return issues


# ---------------------------------------------------------------- retention structure
# hook -> stakes -> escalation (re-hook mid-way) -> payoff in the last third -> quick end that loops.
# Small-channel breakout Shorts (YouTube API, 60 days to Oct 2026): Minecraft drone Shorts 9-29 s
# (median ~15 s), gun mods median ~27 s, war mods median ~36 s. Good Shorts keep 70%+ "viewed"
# (vs swiped away); under 60% the hook is the problem.
RETENTION = {"max_total_s": 35.0, "hook_seg_s": 2.0, "hook_text_at_s": 0.3, "hook_words": 5,
             "payoff_min_frac": 0.4, "tail_after_payoff_s": 3.0, "min_text_s": 0.7, "rehook_after_s": 20.0}


def _timeline_marks(edit: Edit) -> tuple[list[dict], float]:
    """Start/end (output seconds) of every segment including freezes."""
    marks, t = [], 0.0
    for s in edit.segments:
        dur = edit.seg_duration(s)
        fr = float((s.get("freeze") or {}).get("dur", 0.8)) if s.get("freeze") else 0.0
        marks.append({"seg": s, "start": t, "end": t + dur + fr})
        t += dur + fr
    return marks, t


def _source_motion(edit: Edit, s: dict, span: float) -> tuple[float, float] | None:
    """(motion of this source window, median motion of the whole recording) from the footage analysis."""
    a_path = edit.project / Path(s["src"]).with_suffix(".analysis.json")
    try:
        per = json.loads(a_path.read_text(encoding="utf-8"))["per_second"]
    except (OSError, ValueError, KeyError):
        return None
    vals = sorted(x["motion"] for x in per)
    if not vals:
        return None
    t0 = float(s.get("in", 0))
    win = [x["motion"] for x in per if t0 - 0.5 <= x["t"] <= t0 + span + 0.5]
    return (sum(win) / len(win) if win else 0.0), vals[len(vals) // 2]


def retention_checks(edit: Edit, durations: dict[str, float] | None = None) -> list[Issue]:
    """Warnings for the structure that keeps viewers: hook, re-hook, payoff placement, ending, length."""
    r = RETENTION
    out: list[Issue] = []
    segs = edit.segments
    marks, total = _timeline_marks(edit)
    first = segs[0]
    fid = first.get("id")
    if total > r["max_total_s"]:
        out.append(Issue("warning", None, f"{total:.1f}s total: breakout Minecraft Shorts on small channels run 15-36 s "
                                          f"(drones ~15 s, guns ~27 s, war mods ~36 s). Keep only the strongest "
                                          f"20-30 s; length must be earned by escalation"))
    if edit.seg_duration(first) > r["hook_seg_s"]:
        out.append(Issue("warning", fid, f"hook segment is {edit.seg_duration(first):.1f}s: cut to the next shot within "
                                         f"{r['hook_seg_s']:.0f} s"))
    hook_texts = _texts(first)
    if not hook_texts:
        out.append(Issue("warning", fid, "no text on the first segment: a 2-5 word question or claim stops the swipe"))
    else:
        t = hook_texts[0]
        if float(t.get("at", 0)) > r["hook_text_at_s"]:
            out.append(Issue("warning", fid, f"hook text appears at {t.get('at')}s: show it on the first frame"))
        words = len(t.get("text", "").replace("*", "").split())
        if words > r["hook_words"]:
            out.append(Issue("warning", fid, f"hook text has {words} words: 2-{r['hook_words']} words read in one glance"))
    span = edit.seg_duration(first) * float(first.get("speed", 1))
    mm = _source_motion(edit, first, span) if first.get("src") else None
    calm_fx = first.get("punch") or first.get("fx") or abs(float(first.get("zoom_to", first.get("zoom", 1)))
                                                            - float(first.get("zoom", 1))) > 0.1
    if mm and mm[0] < 0.8 * mm[1] and not calm_fx:
        out.append(Issue("warning", fid, "calm first shot (less motion than the recording's median): open on the action "
                                         "or the payoff itself and treat the first frame like a thumbnail"))
    drop = (edit.data.get("music") or {}).get("drop")
    drop_mark = next((m for m in marks if m["seg"].get("id") == drop), None)
    if not drop_mark:
        out.append(Issue("warning", None, "no payoff marked: set music.drop to the segment with the biggest moment"))
    else:
        frac = drop_mark["start"] / total if total else 0
        if frac < r["payoff_min_frac"]:
            out.append(Issue("warning", drop, f"payoff at {frac:.0%} of the video: build tension first and put it in the "
                                              f"last third, or open on it as the hook and rebuild to a second payoff"))
        # the payoff segment itself plus one reaction beat is fine; after that the viewer leaves
        after = [m for m in marks if m["start"] >= drop_mark["end"] - 1e-6]
        tail = sum(m["end"] - m["start"] for m in after[1:]) if after else 0.0
        if tail > r["tail_after_payoff_s"]:
            out.append(Issue("warning", after[1]["seg"].get("id") if len(after) > 1 else None,
                             f"{tail:.1f}s still running after the payoff and its reaction: end within "
                             f"{r['tail_after_payoff_s']:.0f} s, on a frame or line that leads back to the hook"))
    if total > r["rehook_after_s"]:
        lo, hi = 0.35 * total, 0.65 * total
        rehook = any(lo <= m["start"] <= hi and (_texts(m["seg"]) or m["seg"].get("badge") or m["seg"].get("freeze"))
                     for m in marks)
        if not rehook:
            out.append(Issue("warning", None, f"no re-hook between {lo:.0f}s and {hi:.0f}s: add a text, counter, badge or "
                                              f"freeze mid-video ('wait for it', 'round 2', '3 left') so the middle "
                                              f"does not sag"))
    for m in marks:
        s = m["seg"]
        texts = _texts(s)
        if len(texts) > 2:
            out.append(Issue("warning", s.get("id"), f"{len(texts)} texts in one segment: at most 2, one idea at a time"))
        for t in texts:
            if t.get("dur") is not None and float(t["dur"]) < r["min_text_s"]:
                out.append(Issue("warning", s.get("id"), f"text '{t.get('text', '')[:30]}' shows for {t['dur']}s: "
                                                         f"give it at least {r['min_text_s']} s to be read"))
    return out


# ---------------------------------------------------------------- build: timeline + soundtrack
def _still(src: Path, t: float, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(t, 0):.3f}", "-i", str(src), "-frames:v", "1",
                    str(out)], check=True)
    return out


def build(edit: Edit) -> tuple[dict, dict]:
    """Returns (timeline, sound_plan). Freeze frames are extracted to build/."""
    project = edit.project
    d = edit.data
    first_src = edit.segments[0]["src"]
    src_info = probe(project / first_src)
    clips, texts, badges, scenes, sfx = [], [], [], [], []
    stops = []
    t = 0.0
    drop_at = None
    sfx_on_text = d.get("sfx_on_text", "pop")
    for s in edit.segments:
        sid = s["id"]
        dur = edit.seg_duration(s)
        speed = float(s.get("speed", 1))
        f0 = round(t * FPS)
        f1 = round((t + dur) * FPS)
        if (d.get("music") or {}).get("drop") == sid:
            drop_at = f0 / FPS
        common = {"focus": s.get("focus", [0.5, 0.5]), "fx": s.get("fx", []),
                  "framing": s.get("framing", d.get("framing", "crop")), "transition": s.get("transition")}
        clips.append({"id": sid, "kind": "video", "src": s["src"], "from": f0, "durationInFrames": max(f1 - f0, 1),
                      "startFrom": round(float(s.get("in", 0)) * FPS), "playbackRate": speed,
                      "zoom": float(s.get("zoom", 1)), "zoomTo": float(s.get("zoom_to", s.get("zoom", 1))),
                      "punch": bool(s.get("punch")), **common})
        for x in _texts(s):
            a = f0 + round(float(x.get("at", 0)) * FPS)
            b = a + round(float(x["dur"]) * FPS) if x.get("dur") else None
            texts.append({"text": x["text"], "style": x.get("style", "caption"), "from": a, "to": b, "seg": sid,
                          "target": x.get("target")})
            if sfx_on_text and x.get("style") != "big":
                sfx.append({"t": a / FPS, "name": sfx_on_text, "gain": 0.6})
        if s.get("badge"):
            badges.append({"text": s["badge"], "from": f0, "to": f1})
        for x in _sfx(s):
            sfx.append({"t": f0 / FPS + float(x.get("at", 0)), "name": x["name"], "gain": float(x.get("gain", 1.0))})
        end = f1
        fr = s.get("freeze")
        if fr:
            fd = float(fr.get("dur", 0.8))
            src_t = float(s.get("in", 0)) + dur * speed - 1 / src_info["fps"]
            still = _still(project / s["src"], src_t, project / "build" / f"freeze_{sid}.png")
            g1 = f1 + round(fd * FPS)
            clips.append({"id": f"{sid}_freeze", "kind": "still", "src": str(still.relative_to(project)), "from": f1,
                          "durationInFrames": g1 - f1, "zoom": float(s.get("zoom_to", s.get("zoom", 1))),
                          "zoomTo": float(fr.get("zoom", 1.12)) * float(s.get("zoom_to", s.get("zoom", 1))),
                          "punch": False, "focus": s.get("focus", [0.5, 0.5]),
                          "framing": common["framing"], "fx": (["bw"] if fr.get("bw", True) else [])})
            if fr.get("text"):
                texts.append({"text": fr["text"], "style": fr.get("style", "big"), "from": f1, "to": g1, "seg": sid,
                              "target": None})
            if fr.get("music_stop", True):
                stops.append((f1 / FPS, g1 / FPS))
            if fr.get("sfx"):
                sfx.append({"t": f1 / FPS, "name": fr["sfx"], "gain": 1.0})
            end = g1
        scenes.append({"id": sid, "template": "gameplay", "from": f0, "durationInFrames": end - f0})
        t = end / FPS
    total = round(t * FPS)
    # texts without an explicit end stay until the end of their segment (incl. freeze)
    seg_end = {sc["id"]: sc["from"] + sc["durationInFrames"] for sc in scenes}
    for x in texts:
        if x["to"] is None:
            x["to"] = seg_end[x["seg"]]
    timeline = {
        "kind": "gameplay", "title": d.get("title", ""), "fps": FPS, "width": OUT_W, "height": OUT_H,
        "durationInFrames": total, "format": "gameplay", "audio": "audio/mix.wav",
        "framing": d.get("framing", "crop"), "srcWidth": src_info["width"], "srcHeight": src_info["height"],
        "progressBar": bool(d.get("progress_bar", True)), "style": d.get("style", "meme"),
        "clips": clips, "texts": texts, "badges": badges,
        "scenes": scenes, "showCaptions": False,
        # QA reads these as the on-screen text and checks reading speed
        "captions": [{"from": x["from"], "to": x["to"], "text": x["text"].replace("*", "")} for x in texts],
    }
    music = d.get("music") or {}
    plan = {"duration": total / FPS, "bpm": edit.bpm, "style": music.get("style", "phonk"),
            "volume_db": float(music.get("volume_db", -4)), "drop_at": drop_at, "stops": stops, "sfx": sfx,
            "source_audio": d.get("source_audio", False), "clips": clips}
    return timeline, plan


def render_soundtrack(project: Path, plan: dict, out: Path, sr: int = 48_000) -> dict:
    """Beat music (with drop and tape-stops) + SFX (+ optional game audio), normalised to -14 LUFS."""
    import soundfile as sf

    from .audio import loudnorm_file
    from .sound import beat_music, sfx

    n = int(plan["duration"] * sr) + 1
    mix = np.zeros(n, dtype=np.float32)
    if plan["style"] != "none":
        music = beat_music(plan["duration"], plan["bpm"], plan["style"], plan["drop_at"], plan["stops"], sr)
        mix[: len(music)] += music * 10 ** (plan["volume_db"] / 20)
    if plan.get("source_audio"):
        for c in plan["clips"]:
            if c["kind"] == "video" and 0.5 <= c["playbackRate"] <= 2:
                a = _source_audio(project / c["src"], c["startFrom"] / FPS, c["durationInFrames"] / FPS,
                                  c["playbackRate"], sr)
                i = int(c["from"] / FPS * sr)
                mix[i : i + len(a)] += 0.5 * a[: max(n - i, 0)]
    cache: dict[str, np.ndarray] = {}
    for x in plan["sfx"]:
        snd = cache.setdefault(x["name"], sfx(x["name"], sr))
        i = int(x["t"] * sr)
        if i < n:
            m = min(len(snd), n - i)
            mix[i : i + m] += x.get("gain", 1.0) * snd[:m]
    peak = float(np.max(np.abs(mix))) or 1.0
    raw = out.with_name(out.stem + "_raw.wav")
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(raw, mix / max(peak, 1.0) * 0.98, sr, subtype="FLOAT")
    info = loudnorm_file(raw, out, target=-14.0)
    raw.unlink(missing_ok=True)
    return info


def _source_audio(src: Path, start: float, out_dur: float, speed: float, sr: int) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{out_dur * speed:.3f}", "-i", str(src),
                          "-af", f"atempo={speed}", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True).stdout
    return np.frombuffer(raw, np.float32)
