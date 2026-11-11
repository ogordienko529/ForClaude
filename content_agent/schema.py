"""Storyboard format and pre-render checks (QA level L0).

A storyboard is the single editable source of a video. The agent (Claude Code) writes it; every
later step (voice, music, timeline, render, QA) is derived from it, so a fix to one beat only
touches that beat.

{
  "title": "Why Concorde Stopped Flying",
  "format": "explainer",              # explainer | review (16:9) | shorts (9:16): pacing, loudness, QA thresholds
  "voice": "am_michael",              # Kokoro voice (or blend), or an ElevenLabs voice_id / OpenAI voice
  "voice_engine": "kokoro",           # recording (the creator's own voice, see below) | kokoro (free, local) |
                                      # elevenlabs | openai | chatterbox
  "voice_options": {},                # engine options, e.g. {"stability": 0.45, "style": 0.3} for ElevenLabs
  "voice_recording": "voice/narration.m4a",
                                      # recording: the creator reads lines.md (`content_agent lines <slug>`) in one
                                      # take with ~2 s pauses; the file is split on the pauses and matched to the
                                      # beats (a retake replaces the first try). Per-beat "audio": "voice/b03.m4a"
                                      # overrides one line; "voice_segments": [[start, end], ...] pins the split.
  "music": "calm",                    # calm | tense | uplifting (generated ambient pads) | none, or a real track
                                      # {"track": "file.mp3", "start": 12.0} from content_projects/music (hype and
                                      # phonk are generated beats that sound synthetic)
  "palette": "midnight",              # colour theme for the default style (other styles bring their own colours)
  "style": "cosmos",                  # cosmos | paper | blocky | neon | clean | comic (see `content_agent styles`)
  "captions": true,                   # burned-in captions from the narration (a beat can set "captions": false)
  "progress_bar": false,              # a thin accent bar at the top that fills over the whole video
  "sfx": null,                        # quiet sound effects hooked to the animation (typing, taps, scene changes,
                                      # stickers); default: on for "shorts", off for long-form
  "credits": [{"name": "Superb Warfare", "author": "...", "license": "...", "url": "https://..."}],
                                      # reviews: every mod/creator shown, goes into out/description.md
  "thumbnail": {"src": "footage/x.mp4", "t": 61.5, "title": "This mod is *insane*", "tag": "Mod review"},
  "beats": [
    {"id": "b01",
     "narration": "In 1976, you could cross the Atlantic in three and a half hours.",
     "visual": {"template": "map_route", "props": {...}},
     "cues": ["Atlantic"],            # optional: phrases that time the reveals (item i appears on cue i)
     "chapter": "The supersonic dream",  # optional: starts a YouTube chapter here (reviews: >= 3, first beat)
     "transition": "wipe",            # optional: this beat's transition in (default: the style's)
     "captions": false,               # optional: no burned captions over this beat (the screen already types the words)
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
        "required": {"lines": list}, "optional": {"emphasis": list, "sticker": str, "fast": bool},
        "limits": {"lines": 3, "line": 42, "sticker": 8},
        "doc": "1-3 short lines of animated text; words in `emphasis` are highlighted; optional `sticker` (one emoji, "
               "e.g. \"🤯\") pops in beside the text once it is on screen; `fast`: true puts the whole text on "
               "screen within ~0.4 s (hooks, calls to action).",
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
        "required": {"text": str}, "optional": {"source": str, "kicker": str, "sticker": str},
        "limits": {"text": 170, "source": 60, "kicker": 30, "sticker": 8},
        "doc": "Quote or fact card with optional source line; optional `sticker` emoji pops onto the card's corner.",
    },
    "list": {
        "required": {"items": list}, "optional": {"title": str, "sticker": str},
        "limits": {"items": 5, "item": 48, "title": 50, "sticker": 8},
        "doc": "Title plus 2-5 bullet items revealed one by one; optional `sticker` emoji pops in after the last item.",
    },
    "footage": {
        "required": {"src": str, "in": (int, float)},
        "optional": {"speed": (int, float), "zoom": (int, float), "zoom_to": (int, float), "focus": list,
                     "label": str, "sublabel": str, "badge": str, "brightness": (int, float)},
        "limits": {"label": 40, "sublabel": 60},
        "doc": "A clip of your recording (src relative to the project, from `in` seconds, at `speed`), slow push-in "
               "from zoom to zoom_to around focus [x, y]; optional lower-third label/sublabel and a corner badge.",
    },
    "verdict": {
        "required": {"score": (int, float)}, "optional": {"out_of": (int, float), "pros": list, "cons": list, "title": str},
        "limits": {"items": 4, "item": 40, "title": 40},
        "doc": "Review verdict: big score (e.g. 8.5 / 10) with pros and cons revealed on narration cues.",
    },
    "chat": {
        "required": {"prompt": str, "answer": list}, "optional": {"title": str, "highlight": list, "app_logo": str},
        "limits": {"prompt": 280, "answer": 6, "answer_line": 90, "title": 30, "highlight": 6},
        "doc": "Messenger-style AI chat (no brand look, for AI-tip Shorts, 9:16 and 16:9): `prompt` types into a "
               "user bubble, a typing indicator, then 1-6 short `answer` lines appear one by one (line i on cue i); "
               "optional `title` is a small header label, `highlight` lists phrases of the prompt or answer to mark.",
    },
    "phone": {
        "required": {"prompt": str, "answer": list},
        "optional": {"app_name": str, "app_logo": str, "highlight": list, "focus": str, "focus_cue": str,
                     "tool_chips": list},
        "limits": {"prompt": 160, "answer": 4, "answer_line": 70, "app_name": 20, "highlight": 6, "focus": 60,
                   "tool_chips": 4, "chip": 14},
        "doc": "A floating smartphone with a generic AI chat app (9:16 first): `prompt` types into the composer, a "
               "fingertip taps send, the message flies up, typing dots, then 1-4 short `answer` lines (line i on cue i). "
               "`focus` (a phrase of the prompt or answer) gets a smooth 1.6x camera punch-in that lands ~0.2 s before "
               "the narration says it (or `focus_cue`, a narration phrase, when the wording differs); `app_name` is a "
               "generic label (default «ШІ-чат» / \"AI chat\"), `highlight` marks phrases, `tool_chips` (up to 4 "
               "names, plain text, no logos) float beside the phone.",
    },
    "terminal": {
        "required": {"lines": list},
        "optional": {"title": str, "highlight_line": int, "explain": str, "line_numbers": bool},
        "limits": {"lines": 12, "line": 48, "title": 40, "explain": 110},
        "doc": "A dark terminal / code-editor window: `lines` [{text, kind: cmd|code|out|error|ok}] - cmd and code "
               "type in, out/error/ok lines appear (line i on cue i); `highlight_line` (index, default: the first "
               "error) gets a box, `explain` pops in a bubble next to it; `line_numbers` defaults to on for code.",
    },
    "browser": {
        "required": {"url": str},
        "optional": {"state": str, "title": str, "lines": list, "cursor": bool},
        "limits": {"url": 60, "title": 70, "lines": 5, "line": 90},
        "doc": "A browser window: the `url` types into the address bar, the page loads (skeleton, then content). "
               "state \"page\": `title` and up to 5 text `lines` (line i on cue i); state \"notfound\": a big 404 "
               "with a shake (`title`/`lines` replace the default message). `cursor`: a mouse pointer clicks the "
               "address bar and follows the text.",
    },
    "split": {
        "required": {"bad": dict, "good": dict},
        "optional": {"title": str},
        "limits": {"text": 140, "label": 18, "title": 40},
        "doc": "Two stacked panels, weak on top and strong below (\"погано / добре\"): bad/good = {text, label?, "
               "bubble?: prompt|answer}; the ❌ stamp slams onto the top panel on cue 0, the bottom panel arrives on "
               "cue 1 and its ✅ stamp follows. `bubble` shows the text as a mini chat message.",
    },
}

# Tool and brand names: fine as plain text in `tool_chips`, but not as the name of the mock app, which would
# then pass for that product's own app.
BRAND_NAMES = ("chatgpt", "openai", "gemini", "claude", "anthropic", "copilot", "perplexity", "deepseek", "grok",
               "bard", "mistral", "llama", "notion", "google", "microsoft")
TERMINAL_KINDS = ("cmd", "code", "out", "error", "ok")
BROWSER_STATES = ("page", "notfound")
SPLIT_BUBBLES = ("prompt", "answer")

VOICE_ENGINES = ("recording", "kokoro", "elevenlabs", "openai", "chatterbox")

# Visual styles (content_agent/remotion/src/styles.tsx): fonts, colours, background, captions, labels, transitions.
STYLES = {
    "cosmos": "dark night sky with drifting stars, serif titles, caption pill, accent-bar labels, soft fades (default)",
    "paper": "documentary on textured paper, typewriter captions, paper-card labels with an ink underline, wipes",
    "blocky": "game look: voxel grid, pixel font, in-game tooltip captions, achievement-style toasts, pixel dissolves",
    "neon": "synthwave grid and sun, Orbitron, karaoke captions that glow word by word, neon frame labels, glitch cuts",
    "clean": "bright minimal, heavy sans, 2-3 big words at a time with the spoken word highlighted, white tags, slides",
    "comic": "halftone and rays, Bangers, speech-bubble captions and labels, zoom-burst transitions",
    "ember": "bright orange: heavy Montserrat on an orange background, navy highlights, slides",
}
TRANSITIONS = ("fadePush", "wipe", "pixel", "glitch", "slide", "zoomBurst", "cut")
FORMATS = ("explainer", "shorts", "review")

PALETTES = ("midnight", "parchment", "slate", "ember")
# Product marks the chat and phone scenes can show to name the tool (remotion/src/logos.ts), never as the
# channel's own brand.
LOGOS = ("claude",)
MUSIC_MOODS = ("calm", "tense", "uplifting", "hype", "phonk", "none")  # hype/phonk: beat music (sound.py)


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
    music = d.get("music", "calm")
    if isinstance(music, dict):
        if not music.get("track"):
            issues.append(Issue("error", None, 'music as an object needs "track": a file from the music library'))
    elif music not in MUSIC_MOODS:
        issues.append(Issue("error", None, f"music must be one of {MUSIC_MOODS} or {{\"track\": \"file.mp3\"}}"))
    elif music in ("hype", "phonk"):
        issues.append(Issue("warning", None, f"music '{music}' is a generated beat: viewers hear it as AI music. "
                                             f"Use {{\"track\": \"file.mp3\"}} from the music library (music-lib)"))
    if d.get("format", "explainer") not in FORMATS:
        issues.append(Issue("error", None, f"format must be one of {FORMATS}"))
    for key in ("progress_bar", "sfx"):
        if d.get(key) is not None and not isinstance(d[key], bool):
            issues.append(Issue("error", None, f"{key} must be true or false"))
    if d.get("style", "cosmos") not in STYLES:
        issues.append(Issue("error", None, f"style must be one of {tuple(STYLES)}"))
    engine = d.get("voice_engine", "kokoro")
    if engine not in VOICE_ENGINES:
        issues.append(Issue("error", None, f"voice_engine must be one of {VOICE_ENGINES}"))
    elif engine == "elevenlabs" and not str(d.get("voice", "")).strip():
        issues.append(Issue("error", None, "voice_engine elevenlabs needs `voice` set to an ElevenLabs voice_id"))
    elif engine == "recording":
        rec = d.get("voice_recording")
        per_beat = all(b.get("audio") for b in d["beats"])
        if not rec and not per_beat:
            issues.append(Issue("error", None, 'voice_engine recording needs "voice_recording": "voice/narration.m4a" '
                                               '(write lines.md with `content_agent lines`, the creator records it) '
                                               'or an "audio" file on every beat'))
        elif rec and sb.path is not None and not (sb.path.parent / rec).exists():
            issues.append(Issue("warning", None, f"voice_recording {rec} is not there yet: the voice step will wait for it"))
        if d.get("captions", True):
            issues.append(Issue("warning", None, "captions with a recording are timed by sentence length, not by the words: "
                                                 "check them on the contact sheets or set captions to false"))
    chapters = [b for b in d["beats"] if b.get("chapter")]
    if chapters and (chapters[0] is not d["beats"][0] or len(chapters) < 3):
        issues.append(Issue("warning", None, "YouTube chapters need the first beat to start a chapter and at least 3 chapters"))

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
        if "captions" in beat and not isinstance(beat["captions"], bool):
            issues.append(Issue("error", bid, "captions must be true or false"))
        if tname == "phone" and isinstance(props.get("focus_cue"), str) \
                and props["focus_cue"].strip().lower() not in narration.lower():
            issues.append(Issue("warning", bid, f"phone: focus_cue {props['focus_cue']!r} does not occur in the narration"))
        if beat.get("transition") and beat["transition"] not in TRANSITIONS:
            issues.append(Issue("error", bid, f"transition must be one of {TRANSITIONS}"))
        cues = beat.get("cues", [])
        if not isinstance(cues, list) or not all(isinstance(c, str) for c in cues):
            issues.append(Issue("error", bid, "cues must be a list of phrases from the narration"))
        else:
            for c in cues:
                if c.lower() not in narration.lower():
                    issues.append(Issue("warning", bid, f"cue {c!r} does not occur in the narration"))

        prev_templates.append(tname)
        # different clips of a recording are different visuals, so footage may run in a row
        if len(prev_templates) >= 3 and len(set(prev_templates[-3:])) == 1 and tname != "footage":
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
    if tname == "verdict":
        for key in ("pros", "cons"):
            items = props.get(key) or []
            if len(items) > limits["items"]:
                warn(f"use at most {limits['items']} {key}")
            for it in items:
                if _too_long(it, limits["item"]):
                    warn(f"{key} item longer than {limits['item']} characters")
    if tname == "chat":
        prompt = props.get("prompt")
        if isinstance(prompt, str) and not prompt.strip():
            out.append(Issue("error", bid, "chat: prompt is empty"))
        elif _too_long(prompt, limits["prompt"]):
            warn(f"prompt longer than {limits['prompt']} characters (hard to read on screen)")
        answer = props.get("answer")
        if isinstance(answer, list):
            if not 1 <= len(answer) <= limits["answer"]:
                warn(f"use 1-{limits['answer']} answer lines")
            if not all(isinstance(a, str) for a in answer):
                out.append(Issue("error", bid, "chat: answer must be a list of strings, one per line"))
            for a in answer:
                if _too_long(a, limits["answer_line"]):
                    warn(f"answer line longer than {limits['answer_line']} characters")
        hl = props.get("highlight", [])
        if not isinstance(hl, list) or not all(isinstance(h, str) and h.strip() for h in hl):
            out.append(Issue("error", bid, "chat: highlight must be a list of phrases from the prompt or answer"))
        else:
            if len(hl) > limits["highlight"]:
                warn(f"use at most {limits['highlight']} highlights")
            texts = [t.lower() for t in [prompt, *(answer if isinstance(answer, list) else [])] if isinstance(t, str)]
            for h in hl:
                if not any(h.strip().lower() in t for t in texts):
                    warn(f"highlight {h!r} does not occur in the prompt or answer")
    if "sticker" in limits and "sticker" in props:
        out += _check_sticker(bid, tname, props["sticker"], limits["sticker"])
    if tname == "phone":
        out += _check_phone(bid, props, limits)
    if tname == "terminal":
        out += _check_terminal(bid, props, limits)
    if tname == "browser":
        out += _check_browser(bid, props, limits)
    if tname == "split":
        out += _check_split(bid, props, limits)
    if tname == "footage":
        f = props.get("focus", [0.5, 0.5])
        if not (isinstance(f, list) and len(f) == 2 and all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in f)):
            out.append(Issue("error", bid, "footage: focus must be [x, y] fractions 0-1"))
        if not 0.1 <= float(props.get("speed", 1)) <= 16:
            out.append(Issue("error", bid, "footage: speed must be 0.1-16"))
    if tname in ("map_route", "map_point"):
        for key in ("from", "to") if tname == "map_route" else ("place",):
            p = props.get(key) or {}
            lat, lon = p.get("lat"), p.get("lon")
            if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)) or not (-90 <= lat <= 90) \
                    or not (-180 <= lon <= 180):
                out.append(Issue("error", bid, f"{tname}: {key} needs numeric lat (-90..90) and lon (-180..180)"))
    return out


_TEXTY = re.compile(r"[A-Za-z0-9\u0400-\u04ff]")


def _check_sticker(bid: str, tname: str, sticker: Any, limit: int) -> list[Issue]:
    if not isinstance(sticker, str) or not sticker.strip():
        return [Issue("error", bid, f"{tname}: sticker must be an emoji, e.g. \"🤯\"")]
    if len(sticker.strip()) > limit or _TEXTY.search(sticker):
        return [Issue("warning", bid, f"{tname}: sticker should be one emoji (\"🤯\", \"✅\", \"❌\"), not text")]
    return []


def _phrases(bid: str, tname: str, key: str, value: Any, texts: list[str], limit: int) -> list[Issue]:
    """A list of phrases that must occur in one of the texts (highlights)."""
    if not isinstance(value, list) or not all(isinstance(h, str) and h.strip() for h in value):
        return [Issue("error", bid, f"{tname}: {key} must be a list of phrases from the prompt or answer")]
    out = []
    if len(value) > limit:
        out.append(Issue("warning", bid, f"{tname}: use at most {limit} {key} phrases"))
    low = [t.lower() for t in texts]
    for h in value:
        if not any(h.strip().lower() in t for t in low):
            out.append(Issue("warning", bid, f"{tname}: {key} {h!r} does not occur in the prompt or answer"))
    return out


def _check_phone(bid: str, props: dict, limits: dict) -> list[Issue]:
    out: list[Issue] = []

    def warn(msg: str) -> None:
        out.append(Issue("warning", bid, f"phone: {msg}"))

    prompt = props.get("prompt")
    if isinstance(prompt, str) and not prompt.strip():
        out.append(Issue("error", bid, "phone: prompt is empty"))
    elif _too_long(prompt, limits["prompt"]):
        warn(f"prompt longer than {limits['prompt']} characters (the phone screen is small: keep the key sentence)")
    answer = props.get("answer")
    if isinstance(answer, list):
        if not 1 <= len(answer) <= limits["answer"]:
            warn(f"use 1-{limits['answer']} answer lines")
        if not all(isinstance(a, str) for a in answer):
            out.append(Issue("error", bid, "phone: answer must be a list of strings, one per line"))
        for a in answer:
            if _too_long(a, limits["answer_line"]):
                warn(f"answer line longer than {limits['answer_line']} characters")
    texts = [t for t in [prompt, *(answer if isinstance(answer, list) else [])] if isinstance(t, str)]
    if "highlight" in props:
        out += _phrases(bid, "phone", "highlight", props["highlight"], texts, limits["highlight"])
    focus = props.get("focus")
    if focus is not None:
        if not isinstance(focus, str) or not focus.strip():
            out.append(Issue("error", bid, "phone: focus must be a phrase of the prompt or answer"))
        else:
            if not any(focus.strip().lower() in t.lower() for t in texts):
                warn(f"focus {focus!r} does not occur in the prompt or answer (no punch-in)")
            if _too_long(focus, limits["focus"]):
                warn(f"focus longer than {limits['focus']} characters: punch in on one short phrase")
    if "focus_cue" in props and not isinstance(props["focus_cue"], str):
        out.append(Issue("error", bid, "phone: focus_cue must be a phrase of the narration"))
    name = props.get("app_name")
    if _too_long(name, limits["app_name"]):
        warn(f"app_name longer than {limits['app_name']} characters")
    logo = props.get("app_logo")
    if logo is not None and logo not in LOGOS:
        out.append(Issue("error", bid, f"phone: app_logo must be one of {', '.join(LOGOS)}"))
    if isinstance(name, str) and any(b in name.lower() for b in BRAND_NAMES) and not (logo and logo in name.lower()):
        warn(f"app_name {name!r} is a product name: the phone shows a generic app, so give it a generic label "
             f"(«ШІ-чат») and name the tools in tool_chips, or show that product on purpose with app_logo")
    chips = props.get("tool_chips")
    if chips is not None:
        if not isinstance(chips, list) or not all(isinstance(c, str) and c.strip() for c in chips):
            out.append(Issue("error", bid, "phone: tool_chips must be a list of short names, e.g. [\"ChatGPT\", \"Gemini\"]"))
        else:
            if len(chips) > limits["tool_chips"]:
                warn(f"use at most {limits['tool_chips']} tool_chips")
            for c in chips:
                if _too_long(c, limits["chip"]):
                    warn(f"tool chip {c!r} longer than {limits['chip']} characters")
    return out


def _check_terminal(bid: str, props: dict, limits: dict) -> list[Issue]:
    out: list[Issue] = []
    lines = props.get("lines")
    if not isinstance(lines, list):
        return out
    if not 1 <= len(lines) <= limits["lines"]:
        out.append(Issue("warning", bid, f"terminal: use 1-{limits['lines']} lines"))
    for i, ln in enumerate(lines):
        if not isinstance(ln, dict) or not isinstance(ln.get("text"), str):
            out.append(Issue("error", bid, f"terminal: line {i} must be {{\"text\": \"...\", \"kind\": \"cmd\"}}"))
            continue
        if ln.get("kind", "out") not in TERMINAL_KINDS:
            out.append(Issue("error", bid, f"terminal: line {i} kind must be one of {TERMINAL_KINDS}"))
        if _too_long(ln["text"], limits["line"]):
            out.append(Issue("warning", bid, f"terminal: line {i} longer than {limits['line']} characters (it wraps "
                                             f"or the font shrinks)"))
    hl = props.get("highlight_line")
    if hl is not None and (isinstance(hl, bool) or not isinstance(hl, int) or not 0 <= hl < len(lines)):
        out.append(Issue("error", bid, f"terminal: highlight_line must be a line index 0-{len(lines) - 1}"))
    explain = props.get("explain")
    if explain is not None and not isinstance(explain, str):
        out.append(Issue("error", bid, "terminal: explain must be text"))
    elif _too_long(explain, limits["explain"]):
        out.append(Issue("warning", bid, f"terminal: explain longer than {limits['explain']} characters"))
    has_error = any(isinstance(ln, dict) and ln.get("kind") == "error" for ln in lines)
    if props.get("explain") is not None and hl is None and not has_error:
        out.append(Issue("warning", bid, "terminal: explain needs a line to point at: set highlight_line or add an "
                                         "error line"))
    if "line_numbers" in props and not isinstance(props["line_numbers"], bool):
        out.append(Issue("error", bid, "terminal: line_numbers must be true or false"))
    return out


def _check_browser(bid: str, props: dict, limits: dict) -> list[Issue]:
    out: list[Issue] = []
    url = props.get("url")
    if isinstance(url, str):
        if not url.strip():
            out.append(Issue("error", bid, "browser: url is empty"))
        elif _too_long(url, limits["url"]):
            out.append(Issue("warning", bid, f"browser: url longer than {limits['url']} characters"))
        if " " in url.strip():
            out.append(Issue("warning", bid, "browser: url has spaces"))
    state = props.get("state", "page")
    if state not in BROWSER_STATES:
        out.append(Issue("error", bid, f"browser: state must be one of {BROWSER_STATES}"))
    lines = props.get("lines", [])
    if not isinstance(lines, list) or not all(isinstance(x, str) for x in lines):
        out.append(Issue("error", bid, "browser: lines must be a list of strings"))
    else:
        if len(lines) > limits["lines"]:
            out.append(Issue("warning", bid, f"browser: use at most {limits['lines']} lines"))
        for x in lines:
            if _too_long(x, limits["line"]):
                out.append(Issue("warning", bid, f"browser: line longer than {limits['line']} characters"))
        if state == "page" and not lines and not props.get("title"):
            out.append(Issue("warning", bid, "browser: a page with no title and no lines loads into an empty page"))
    if "cursor" in props and not isinstance(props["cursor"], bool):
        out.append(Issue("error", bid, "browser: cursor must be true or false"))
    return out


def _check_split(bid: str, props: dict, limits: dict) -> list[Issue]:
    out: list[Issue] = []
    for side in ("bad", "good"):
        s = props.get(side)
        if not isinstance(s, dict):
            continue
        text = s.get("text")
        if not isinstance(text, str) or not text.strip():
            out.append(Issue("error", bid, f"split: {side} needs text"))
        elif _too_long(text, limits["text"]):
            out.append(Issue("warning", bid, f"split: {side} text longer than {limits['text']} characters"))
        if "label" in s and not isinstance(s["label"], str):
            out.append(Issue("error", bid, f"split: {side} label must be text"))
        elif _too_long(s.get("label"), limits["label"]):
            out.append(Issue("warning", bid, f"split: {side} label longer than {limits['label']} characters"))
        if s.get("bubble") is not None and s["bubble"] not in SPLIT_BUBBLES:
            out.append(Issue("error", bid, f"split: {side} bubble must be one of {SPLIT_BUBBLES}"))
        extra = set(s) - {"text", "label", "bubble"}
        if extra:
            out.append(Issue("warning", bid, f"split: {side} has unknown keys {sorted(extra)} (ignored)"))
    return out


def sfx_on(storyboard: dict, fmt: str | None = None) -> bool:
    """Sound effects hooked to the animation: the storyboard's "sfx", else on for Shorts only."""
    value = storyboard.get("sfx")
    if value is None:
        return (fmt or storyboard.get("format", "explainer")) == "shorts"
    return bool(value)
