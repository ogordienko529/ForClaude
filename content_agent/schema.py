"""Storyboard format and pre-render checks (QA level L0).

A storyboard is the single editable source of a video. The agent (Claude Code) writes it; every
later step (voice, music, timeline, render, QA) is derived from it, so a fix to one beat only
touches that beat.

{
  "title": "Why Concorde Stopped Flying",
  "format": "explainer",              # format pack: pacing, loudness and QA thresholds
  "voice": "am_michael",              # sleep_voice / Kokoro voice or blend
  "music": "calm",                    # procedural music mood: calm | tense | uplifting | none
  "palette": "midnight",              # renderer colour theme
  "beats": [
    {"id": "b01",
     "narration": "In 1976, you could cross the Atlantic in three and a half hours.",
     "visual": {"template": "map_route", "props": {...}},
     "sources": ["https://..."]}
  ]
}
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------- templates
# name -> (required props, optional props, description). Limits keep on-screen text readable.
TEMPLATES: dict[str, dict[str, Any]] = {
    "title": {
        "required": {"title": str}, "optional": {"subtitle": str, "kicker": str},
        "limits": {"title": 60, "subtitle": 90, "kicker": 30},
        "doc": "Opening or chapter card: big serif title, optional kicker above and subtitle below.",
    },
    "kinetic": {
        "required": {"lines": list}, "optional": {"emphasis": list},
        "limits": {"lines": 3, "line": 42},
        "doc": "1-3 short lines of animated text; words in `emphasis` are highlighted.",
    },
    "map_route": {
        "required": {"from": dict, "to": dict}, "optional": {"label": str, "vehicle": str},
        "limits": {"label": 50},
        "doc": "World map, animated great-circle route from -> to ({name, lat, lon}); vehicle: plane | ship | none.",
    },
    "map_point": {
        "required": {"place": dict}, "optional": {"label": str, "zoom": (int, float)},
        "limits": {"label": 50},
        "doc": "World map that zooms to one place ({name, lat, lon}) with a pulsing marker.",
    },
    "timeline": {
        "required": {"events": list}, "optional": {"highlight": int, "title": str},
        "limits": {"events": 6, "event_label": 34, "title": 50},
        "doc": "Horizontal timeline; events [{year, label}], 2-6 items; `highlight` = index to emphasise.",
    },
    "stat": {
        "required": {"value": (int, float), "label": str},
        "optional": {"prefix": str, "suffix": str, "decimals": int, "note": str},
        "limits": {"label": 60, "note": 80},
        "doc": "Big number counting up with a label (e.g. 2.04 -> 'Mach' prefix).",
    },
    "comparison": {
        "required": {"left": dict, "right": dict}, "optional": {"title": str, "unit": str},
        "limits": {"title": 50, "side_label": 28},
        "doc": "Two values side by side as growing bars: left/right = {label, value}.",
    },
    "bars": {
        "required": {"items": list}, "optional": {"title": str, "unit": str},
        "limits": {"items": 7, "title": 50, "item_label": 24},
        "doc": "Horizontal bar chart, items [{label, value}], 2-7 items.",
    },
    "fact": {
        "required": {"text": str}, "optional": {"source": str, "kicker": str},
        "limits": {"text": 170, "source": 60, "kicker": 30},
        "doc": "Quote or fact card with optional source line.",
    },
    "list": {
        "required": {"items": list}, "optional": {"title": str},
        "limits": {"items": 5, "item": 48, "title": 50},
        "doc": "Title plus 2-5 bullet items revealed one by one.",
    },
}

PALETTES = ("midnight", "parchment", "slate")
MUSIC_MOODS = ("calm", "tense", "uplifting", "none")


@dataclass
class Issue:
    level: str          # error | warning
    beat: str | None
    message: str

    def __str__(self) -> str:
        where = f"[{self.beat}] " if self.beat else ""
        return f"{self.level.upper()}: {where}{self.message}"


@dataclass
class Storyboard:
    data: dict[str, Any]
    path: Path | None = None
    issues: list[Issue] = field(default_factory=list)

    @property
    def beats(self) -> list[dict[str, Any]]:
        return self.data.get("beats", [])

    @property
    def title(self) -> str:
        return self.data.get("title", "Untitled")

    @classmethod
    def load(cls, path: Path) -> "Storyboard":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")), Path(path))

    def save(self, path: Path | None = None) -> None:
        target = path or self.path
        Path(target).write_text(json.dumps(self.data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


_NUMBER_RE = re.compile(r"\d")
DATA_TEMPLATES = {"stat", "comparison", "bars", "timeline"}


def validate(sb: Storyboard, max_words_per_beat: int = 45, min_words_per_beat: int = 4) -> list[Issue]:
    """Pre-render checks. Errors block rendering; warnings go to the reviewer."""
    issues: list[Issue] = []
    d = sb.data
    if not isinstance(d.get("beats"), list) or not d["beats"]:
        return [Issue("error", None, "storyboard has no beats")]
    if d.get("palette", "midnight") not in PALETTES:
        issues.append(Issue("error", None, f"palette must be one of {PALETTES}"))
    if d.get("music", "calm") not in MUSIC_MOODS:
        issues.append(Issue("error", None, f"music must be one of {MUSIC_MOODS}"))

    seen_ids: set[str] = set()
    prev_templates: list[str] = []
    for i, beat in enumerate(d["beats"]):
        bid = beat.get("id") or f"#{i + 1}"
        if bid in seen_ids:
            issues.append(Issue("error", bid, "duplicate beat id"))
        seen_ids.add(bid)

        narration = (beat.get("narration") or "").strip()
        words = len(narration.split())
        if not narration:
            issues.append(Issue("error", bid, "narration is empty"))
        elif words > max_words_per_beat:
            issues.append(Issue("warning", bid, f"{words} words: split into two beats so the picture changes "
                                                f"(max {max_words_per_beat})"))
        elif words < min_words_per_beat:
            issues.append(Issue("warning", bid, f"only {words} words: scene will flash by"))
        visual = beat.get("visual") or {}
        tname = visual.get("template")
        if (_NUMBER_RE.search(narration) or tname in DATA_TEMPLATES) and not beat.get("sources"):
            issues.append(Issue("warning", bid, "states numbers/dates but has no sources"))

        spec = TEMPLATES.get(tname)
        if spec is None:
            issues.append(Issue("error", bid, f"unknown template {tname!r}; use one of {sorted(TEMPLATES)}"))
            continue
        props = visual.get("props") or {}
        for key, typ in spec["required"].items():
            if key not in props:
                issues.append(Issue("error", bid, f"{tname}: missing prop {key!r}"))
            elif not isinstance(props[key], typ):
                issues.append(Issue("error", bid, f"{tname}: prop {key!r} has the wrong type"))
        for key in props:
            if key not in spec["required"] and key not in spec["optional"]:
                issues.append(Issue("warning", bid, f"{tname}: unknown prop {key!r} is ignored"))
        issues += _check_limits(bid, tname, props, spec["limits"])

        prev_templates.append(tname)
        if len(prev_templates) >= 3 and len(set(prev_templates[-3:])) == 1:
            issues.append(Issue("warning", bid, f"three {tname!r} scenes in a row: vary the visuals"))
    sb.issues = issues
    return issues


def _too_long(text: Any, limit: int) -> bool:
    return isinstance(text, str) and len(text) > limit


def _check_limits(bid: str, tname: str, props: dict, limits: dict) -> list[Issue]:
    out = []

    def warn(msg: str) -> None:
        out.append(Issue("warning", bid, f"{tname}: {msg}"))

    for key in ("title", "subtitle", "kicker", "label", "note", "text", "source"):
        if key in limits and _too_long(props.get(key), limits[key]):
            warn(f"{key} longer than {limits[key]} characters (hard to read on screen)")
    if tname == "kinetic":
        lines = props.get("lines") or []
        if not 1 <= len(lines) <= limits["lines"]:
            warn(f"use 1-{limits['lines']} lines")
        for ln in lines:
            if _too_long(ln, limits["line"]):
                warn(f"line longer than {limits['line']} characters")
    if tname == "timeline":
        ev = props.get("events") or []
        if not 2 <= len(ev) <= limits["events"]:
            warn(f"use 2-{limits['events']} events")
        for e in ev:
            if not isinstance(e, dict) or "year" not in e or "label" not in e:
                out.append(Issue("error", bid, "timeline: each event needs year and label"))
            elif _too_long(e["label"], limits["event_label"]):
                warn(f"event label longer than {limits['event_label']} characters")
    if tname in ("bars",):
        items = props.get("items") or []
        if not 2 <= len(items) <= limits["items"]:
            warn(f"use 2-{limits['items']} items")
        for it in items:
            if not isinstance(it, dict) or "label" not in it or not isinstance(it.get("value"), (int, float)):
                out.append(Issue("error", bid, "bars: each item needs label and numeric value"))
    if tname == "list":
        items = props.get("items") or []
        if not 2 <= len(items) <= limits["items"]:
            warn(f"use 2-{limits['items']} items")
        for it in items:
            if _too_long(it, limits["item"]):
                warn(f"item longer than {limits['item']} characters")
    if tname == "comparison":
        for side in ("left", "right"):
            s = props.get(side) or {}
            if "label" not in s or not isinstance(s.get("value"), (int, float)):
                out.append(Issue("error", bid, f"comparison: {side} needs label and numeric value"))
    if tname in ("map_route", "map_point"):
        for key in ("from", "to") if tname == "map_route" else ("place",):
            p = props.get(key) or {}
            lat, lon = p.get("lat"), p.get("lon")
            if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)) or not (-90 <= lat <= 90) \
                    or not (-180 <= lon <= 180):
                out.append(Issue("error", bid, f"{tname}: {key} needs numeric lat (-90..90) and lon (-180..180)"))
    return out
