"""Where a project stands: what exists, what is stale, and the next pipeline step."""

from __future__ import annotations

import json
import os
from pathlib import Path

ARTIFACTS = {
    "storyboard": "storyboard.json",
    "edit": "edit.json",
    "research": "research.md",
    "mods": "mods.json",
    "voice": "audio/voice.wav",
    "mix": "audio/mix.wav",
    "timeline": "timeline.json",
    "video": "out/video.mp4",
    "qa": "review/qa.md",
    "overview": "review/overview.png",
    "thumbnail": "out/thumbnail.png",
    "description": "out/description.md",
}


def projects_root() -> Path:
    return Path(os.environ.get("CONTENT_AGENT_HOME", Path.cwd() / "content_projects")).resolve()


def resolve(project: str) -> Path:
    """A slug under the projects folder, or a path to a project folder."""
    p = Path(project).expanduser()
    if p.is_absolute() or (p / "storyboard.json").exists() or (p / "edit.json").exists():
        return p.resolve()
    if not project or any(c in project for c in "\\/:") or project.startswith("."):
        raise ValueError(f"project must be a short slug like 'war_mod' or an absolute path, got {project!r}")
    return projects_root() / project


def _mtime(path: Path) -> float | None:
    return path.stat().st_mtime if path.exists() else None


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def kind_of(project: Path) -> str:
    if (project / "storyboard.json").exists():
        return _read_json(project / "storyboard.json").get("format", "explainer")
    if (project / "edit.json").exists():
        return "gameplay_short"
    if (project / "footage").exists():
        return "footage_only"
    return "empty"


def footage(project: Path) -> list[dict]:
    out = []
    for v in sorted((project / "footage").glob("*")) if (project / "footage").exists() else []:
        if v.suffix.lower() not in (".mp4", ".mov", ".mkv", ".webm", ".avi"):
            continue
        a = _read_json(v.with_name(f"{v.stem}.analysis.json"))
        out.append({"src": f"footage/{v.name}", "duration_s": a.get("duration"),
                    "size": f"{a.get('width')}x{a.get('height')}" if a else None,
                    "events": len(a.get("events", [])) if a else None,
                    "sheets": a.get("sheets", []), "analysed": bool(a)})
    return out


def next_step(project: Path, kind: str) -> str:
    m = {k: _mtime(project / v) for k, v in ARTIFACTS.items()}
    source = m["storyboard"] if kind not in ("gameplay_short",) else m["edit"]
    if kind == "empty":
        return "plan: import footage (import_footage) or create the project (new_project), then write the script"
    if kind == "footage_only":
        return "write storyboard.json (review/explainer) or edit.json (Short) for this footage"
    if m["timeline"] is None or (source and m["timeline"] < source):
        return "validate, then run_step make (storyboard/edit changed since the last build)"
    if m["video"] is None or m["video"] < m["timeline"]:
        return "run_step render, then qa"
    if m["qa"] is None or m["qa"] < m["video"]:
        return "run_step qa"
    if kind == "review" and m["thumbnail"] is None:
        return "look at the QA sheets, fix what is wrong; then run_step thumbnail"
    return "look at the QA sheets and fix what is wrong, or deliver"


def project_status(project: Path) -> dict:
    kind = kind_of(project)
    data = _read_json(project / ("storyboard.json" if kind not in ("gameplay_short", "footage_only", "empty")
                                 else "edit.json"))
    info: dict = {
        "project": str(project),
        "exists": project.exists(),
        "kind": kind,
        "title": data.get("title"),
        "style": data.get("style"),
        "footage": footage(project),
        "artifacts": {k: str(project / v) for k, v in ARTIFACTS.items() if (project / v).exists()},
        "next_step": next_step(project, kind),
    }
    if kind not in ("gameplay_short", "footage_only", "empty"):
        beats = data.get("beats", [])
        info["beats"] = len(beats)
        info["words"] = sum(len(b.get("narration", "").split()) for b in beats)
        info["voice_engine"] = data.get("voice_engine", "kokoro")
    elif kind == "gameplay_short":
        info["segments"] = len(data.get("segments", []))
    tl = _read_json(project / "timeline.json")
    if tl.get("fps"):
        info["duration_s"] = round(tl["durationInFrames"] / tl["fps"], 1)
    return info


def list_projects(root: Path | None = None) -> list[dict]:
    root = root or projects_root()
    out = []
    for p in sorted(root.glob("*")) if root.exists() else []:
        if not p.is_dir():
            continue
        kind = kind_of(p)
        if kind == "empty":
            continue
        out.append({"project": p.name, "kind": kind, "has_video": (p / "out" / "video.mp4").exists(),
                    "next_step": next_step(p, kind)})
    return out
