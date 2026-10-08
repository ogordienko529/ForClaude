"""Storyboard + voice timings -> timeline.json for the renderer.

Scenes cut on narration: each scene starts slightly before its beat is spoken and lasts until the
next scene starts. Captions come from the per-sentence timings, split into readable chunks.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

FPS = 30
SIZES = {"explainer": (1920, 1080), "sleep": (1920, 1080), "shorts": (1080, 1920)}
CAPTION_CHARS = {"explainer": 80, "sleep": 80, "shorts": 36}


def chunk_text(text: str, limit: int) -> list[str]:
    """Split a sentence into caption-sized pieces, preferring breaks after punctuation."""
    if len(text) <= limit:
        return [text]
    words = text.split()
    chunks: list[str] = []
    cur: list[str] = []
    for w in words:
        if cur and len(" ".join(cur + [w])) > limit:
            # move back to the last clause break if it leaves a reasonable chunk
            cut = next((i for i in range(len(cur) - 1, 0, -1) if re.search(r"[,;:—–]$", cur[i - 1])), None)
            if cut and len(" ".join(cur[:cut])) >= limit * 0.45:
                chunks.append(" ".join(cur[:cut]))
                cur = cur[cut:]
            else:
                chunks.append(" ".join(cur))
                cur = []
        cur.append(w)
    if cur:
        # avoid a dangling one- or two-word tail
        if chunks and len(cur) <= 2 and len(chunks[-1]) + len(" ".join(cur)) <= limit * 1.25:
            chunks[-1] = chunks[-1] + " " + " ".join(cur)
        else:
            chunks.append(" ".join(cur))
    return chunks


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


def build_timeline(storyboard: dict, voice_timing: dict, audio_rel: str, fmt: str = "explainer",
                   lead: float = 0.35, captions: bool = True) -> dict:
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
        scenes.append({
            "id": t["id"],
            "template": beat["visual"]["template"],
            "props": beat["visual"].get("props", {}),
            "from": f0,
            "durationInFrames": max(f1 - f0, 1),
            # when the narration of this beat actually starts, relative to the scene (for reveal timing)
            "speechOffset": max(round(t["start"] * FPS) - f0, 0),
        })
    caps = []
    if captions:
        limit = CAPTION_CHARS.get(fmt, 80)
        for t in timing:
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
        "format": fmt,
        "audio": audio_rel,
        "showCaptions": bool(storyboard.get("captions", True)),
        "scenes": scenes,
        "captions": caps,
    }


def write_timeline(timeline: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(timeline, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
