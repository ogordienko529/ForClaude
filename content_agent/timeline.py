"""Storyboard + voice timings -> timeline.json for the renderer.

Scenes cut on narration: each scene starts slightly before its beat is spoken and lasts until the
next scene starts. Captions come from the per-sentence timings, split into readable chunks.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

FPS = 30
SFX_DIR = "audio/sfx"  # sound effects the renderer plays (written by `build` when the storyboard has sfx on)
SIZES = {"explainer": (1920, 1080), "review": (1920, 1080), "sleep": (1920, 1080), "shorts": (1080, 1920)}
CAPTION_CHARS = {"explainer": 80, "review": 80, "sleep": 80, "shorts": 36}


def chunk_text(text: str, limit: int) -> list[str]:
    """Split a sentence into caption-sized pieces of similar length, preferring clause breaks."""
    if len(text) <= limit:
        return [text]
    words = text.split()
    ends, pos = [], 0
    for i, w in enumerate(words):
        pos += len(w) + (1 if i else 0)
        ends.append(pos)  # text length up to and including word i
    n = math.ceil(len(text) / limit)
    chunks, first = [], 0
    for k in range(1, n):
        target = ends[first - 1] + (len(text) - ends[first - 1]) / (n - k + 1) if first else len(text) * k / n
        base = ends[first - 1] + 1 if first else 0
        best, best_score = None, None
        for i in range(first, len(words) - 1):
            length = ends[i] - base
            if length > limit and best is not None:
                break
            score = abs(ends[i] - target)
            if re.search(r"[,;:\u2014\u2013]$", words[i]):
                score -= limit * 0.3  # break after a comma or dash when it is close enough
            head = " ".join(words[: i + 1])
            if head.count("\u00ab") > head.count("\u00bb") or head.count("\u201c") > head.count("\u201d"):
                score += limit * 0.5  # keep a quoted name (\u00ab\u0428\u0406 \u043d\u0430 \u0441\u0442\u0430\u0440\u0442\u0456\u00bb) on one caption
            if best_score is None or score < best_score:
                best, best_score = i, score
        if best is None:
            break
        chunks.append(" ".join(words[first : best + 1]))
        first = best + 1
    chunks.append(" ".join(words[first:]))
    return chunks


def cue_offsets(cues: list[str], sentences: list[dict], scene_from: int) -> list[int | None]:
    """Frames (relative to the scene) at which each cue phrase is spoken, estimated within its sentence."""
    out: list[int | None] = []
    cursor = (0, 0)  # (sentence index, char index) of the previous match: cues are matched in order
    last = None
    for cue in cues:
        found = _find(cue, sentences, cursor) or _find(cue, sentences, (0, 0))
        if not found:
            out.append(None)
            continue
        if found == last and out[-1] is not None:
            out.append(out[-1] + 6)  # the same phrase again: reveal right after the previous item
            continue
        last = found
        si, ci = found
        s = sentences[si]
        t = s["start"] + (s["end"] - s["start"]) * ci / max(len(s["text"]), 1)
        out.append(max(round(t * FPS) - scene_from, 0))
        cursor = (si, ci + 1)
    return out


def _find(cue: str, sentences: list[dict], cursor: tuple[int, int]) -> tuple[int, int] | None:
    needles = {cue.lower().strip()}
    try:
        from sleep_voice.text import normalize

        needles.add(normalize(cue).lower().strip().rstrip("."))
    except ImportError:
        pass
    for si in range(cursor[0], len(sentences)):
        hay = sentences[si]["text"].lower()
        start = cursor[1] if si == cursor[0] else 0
        hits = [hay.find(n, start) for n in needles if n]
        hits = [h for h in hits if h >= 0]
        if hits:
            return si, min(hits)
    return None


def _caption_cues(sentence: dict, limit: int) -> list[dict]:
    parts = chunk_text(sentence["text"], limit)
    span = sentence["end"] - sentence["start"]
    total = sum(len(p) for p in parts) or 1
    cues, t = [], sentence["start"]
    for p in parts:
        d = span * len(p) / total
        cues.append({"start": t, "end": t + d, "text": p})
        t += d
    return cues


def scene_marks(props: dict, sentences: list[dict], scene_from: int) -> dict[str, int]:
    """Frames (relative to the scene) at which template moments are spoken: `focus` (phone punch-in) is the
    `focus_cue` phrase, or the focus phrase itself when the narration says it."""
    marks: dict[str, int] = {}
    for phrase in (props.get("focus_cue"), props.get("focus")):
        if isinstance(phrase, str) and phrase.strip():
            at = cue_offsets([phrase], sentences, scene_from)[0]
            if at is not None:
                marks["focus"] = at
                break
    return marks


def build_timeline(storyboard: dict, voice_timing: dict, audio_rel: str, fmt: str = "explainer",
                   lead: float = 0.35, captions: bool = True) -> dict:
    from .schema import sfx_on

    width, height = SIZES.get(fmt, SIZES["explainer"])
    beats = {b["id"]: b for b in storyboard["beats"]}
    timing = voice_timing["beats"]
    total = voice_timing["duration"]
    starts = [0.0] + [max(t["start"] - lead, 0.0) for t in timing[1:]]
    ends = starts[1:] + [total]
    scenes = []
    for t, a, b in zip(timing, starts, ends):
        beat = beats[t["id"]]
        f0, f1 = round(a * FPS), round(b * FPS)
        marks = scene_marks(beat["visual"].get("props", {}), t["sentences"], f0)
        scenes.append({
            "id": t["id"],
            "template": beat["visual"]["template"],
            "props": beat["visual"].get("props", {}),
            "from": f0,
            "durationInFrames": max(f1 - f0, 1),
            # when the narration of this beat actually starts, relative to the scene (for reveal timing)
            "speechOffset": max(round(t["start"] * FPS) - f0, 0),
            "cues": cue_offsets(beat.get("cues", []), t["sentences"], f0),
            **({"marks": marks} if marks else {}),
            **({"chapter": beat["chapter"]} if beat.get("chapter") else {}),
            **({"transition": beat["transition"]} if beat.get("transition") else {}),
        })
    caps = []
    if captions:
        limit = CAPTION_CHARS.get(fmt, 80)
        for t in timing:
            if beats[t["id"]].get("captions") is False:  # the screen already types these words
                continue
            for s in t["sentences"]:
                for c in _caption_cues(s, limit):
                    caps.append({"from": round(c["start"] * FPS), "to": round(c["end"] * FPS), "text": c["text"]})
    return {
        "title": storyboard.get("title", ""),
        "fps": FPS,
        "width": width,
        "height": height,
        "durationInFrames": round(total * FPS),
        "palette": storyboard.get("palette", "midnight"),
        **({"style": storyboard["style"]} if storyboard.get("style") else {}),
        "format": fmt,
        "audio": audio_rel,
        "showCaptions": bool(storyboard.get("captions", True)),
        "progressBar": bool(storyboard.get("progress_bar", False)),
        **({"countdown": True} if storyboard.get("countdown") else {}),
        **({"sfx": SFX_DIR} if sfx_on(storyboard, fmt) else {}),
        "scenes": scenes,
        "captions": caps,
    }


def write_timeline(timeline: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(timeline, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
