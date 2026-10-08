"""Local video pipeline driven by Claude Code (or by hand).

    python -m content_agent new concorde --title "Why Concorde Stopped Flying"
    # edit content_projects/concorde/storyboard.json (the agent writes it)
    python -m content_agent make concorde          # validate -> voice -> music -> mix -> build -> render -> qa
    python -m content_agent still concorde b07     # preview one scene as a PNG
    python -m content_agent render concorde --scene b07   # re-render one scene as a clip for checking

Everything runs on this machine: Kokoro for the voice, numpy for the music, ffmpeg for the mix,
Remotion + headless Chromium for the picture. No paid APIs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from .schema import MUSIC_MOODS, PALETTES, TEMPLATES, Storyboard, validate

ROOT = Path(os.environ.get("CONTENT_AGENT_HOME", Path.cwd() / "content_projects"))

SKELETON = {
    "title": "",
    "format": "explainer",
    "voice": "am_michael",
    "music": "calm",
    "palette": "midnight",
    "captions": True,
    "beats": [
        {"id": "b01", "narration": "Replace this with the hook: one or two sentences.",
         "visual": {"template": "title", "props": {"title": "Working title"}}, "sources": []},
    ],
}


def project_dir(name: str) -> Path:
    p = Path(name)
    return p if (p / "storyboard.json").exists() or p.is_absolute() else ROOT / name


def _load(project: Path) -> Storyboard:
    path = project / "storyboard.json"
    if not path.exists():
        sys.exit(f"no storyboard at {path} (create one with: python -m content_agent new <name>)")
    return Storyboard.load(path)


def _step(name: str):
    print(f"\n== {name}", file=sys.stderr)
    return time.time()


def _done(t0: float, msg: str = "") -> None:
    print(f"   done in {time.time() - t0:.1f}s {msg}", file=sys.stderr)


# ---------------------------------------------------------------- commands
def cmd_new(a) -> None:
    project = project_dir(a.name)
    if (project / "storyboard.json").exists() and not a.force:
        sys.exit(f"{project} already exists (use --force to overwrite the storyboard)")
    project.mkdir(parents=True, exist_ok=True)
    sb = dict(SKELETON, title=a.title or a.name.replace("-", " ").title(), format=a.format)
    (project / "storyboard.json").write_text(json.dumps(sb, indent=2) + "\n", encoding="utf-8")
    if not (project / "research.md").exists():
        (project / "research.md").write_text(
            f"# {sb['title']}\n\n## Angle\n\n## Key facts (each with a source)\n\n## Sources\n", encoding="utf-8")
    print(project)


def cmd_templates(a) -> None:
    if a.json:
        out = {k: {"required": {p: _tname(t) for p, t in v["required"].items()},
                   "optional": {p: _tname(t) for p, t in v["optional"].items()},
                   "limits": v["limits"], "doc": v["doc"]} for k, v in TEMPLATES.items()}
        print(json.dumps({"templates": out, "palettes": PALETTES, "music": MUSIC_MOODS}, indent=2))
        return
    for name, v in TEMPLATES.items():
        req = ", ".join(v["required"])
        opt = ", ".join(v["optional"])
        print(f"{name:11s} {v['doc']}\n{'':11s} required: {req}" + (f" | optional: {opt}" if opt else ""))
    print(f"\npalettes: {', '.join(PALETTES)}   music: {', '.join(MUSIC_MOODS)}")


def _tname(t) -> str:
    return "/".join(x.__name__ for x in t) if isinstance(t, tuple) else t.__name__


def cmd_validate(a) -> int:
    sb = _load(project_dir(a.project))
    issues = validate(sb)
    words = sum(len(b.get("narration", "").split()) for b in sb.beats)
    print(f"{sb.title}: {len(sb.beats)} beats, {words} words (~{words / 160:.1f} min at a documentary pace)")
    for i in issues:
        print(i)
    errors = [i for i in issues if i.level == "error"]
    print("OK" if not errors else f"{len(errors)} error(s): fix the storyboard before rendering")
    return 1 if errors else 0


def cmd_voice(a) -> None:
    from .audio import synthesize_voice

    project = project_dir(a.project)
    sb = _load(project)
    t0 = _step("voice")
    timing = synthesize_voice(sb.beats, project / "audio" / "voice.wav", voice=sb.data.get("voice", "am_michael"),
                              fmt=sb.data.get("format", "explainer"),
                              log=lambda m: print(m, file=sys.stderr))
    (project / "audio" / "voice_timing.json").write_text(json.dumps(timing, indent=2) + "\n", encoding="utf-8")
    _done(t0, f"({timing['duration']:.1f}s of narration)")


def cmd_music(a) -> None:
    import soundfile as sf

    from .audio import ambient_music

    project = project_dir(a.project)
    sb = _load(project)
    mood = a.mood or sb.data.get("music", "calm")
    out = project / "audio" / "music.wav"
    if mood == "none":
        out.unlink(missing_ok=True)
        return
    timing = json.loads((project / "audio" / "voice_timing.json").read_text())
    t0 = _step(f"music ({mood})")
    music = ambient_music(timing["duration"] + 1.0, mood=mood, seed=a.seed)
    sf.write(out, music, 48_000, subtype="PCM_16")
    _done(t0)


def cmd_mix(a) -> None:
    from .audio import mix

    project = project_dir(a.project)
    sb = _load(project)
    music = project / "audio" / "music.wav"
    t0 = _step("mix")
    info = mix(project / "audio" / "voice.wav", music if music.exists() else None, project / "audio" / "mix.wav",
               fmt=sb.data.get("format", "explainer"), music_db=a.music_db)
    _done(t0, f"(-> {info['target_lufs']:.0f} LUFS)")


def cmd_build(a) -> None:
    from .timeline import build_timeline, write_timeline

    project = project_dir(a.project)
    sb = _load(project)
    timing = json.loads((project / "audio" / "voice_timing.json").read_text())
    if [b["id"] for b in timing["beats"]] != [b["id"] for b in sb.beats]:
        sys.exit("voice timings do not match the storyboard beats: run `voice` (and music/mix) again")
    audio = "audio/mix.wav" if (project / "audio" / "mix.wav").exists() else "audio/voice.wav"
    tl = build_timeline(sb.data, timing, audio, fmt=sb.data.get("format", "explainer"))
    write_timeline(tl, project / "timeline.json")
    print(f"timeline: {len(tl['scenes'])} scenes, {tl['durationInFrames'] / tl['fps']:.1f}s", file=sys.stderr)


def _scene(project: Path, scene_id: str) -> tuple[dict, dict]:
    tl = json.loads((project / "timeline.json").read_text())
    for s in tl["scenes"]:
        if s["id"] == scene_id:
            return tl, s
    sys.exit(f"no scene {scene_id!r} in timeline (ids: {', '.join(s['id'] for s in tl['scenes'])})")


def cmd_render(a) -> None:
    from .render import render

    project = project_dir(a.project)
    tl_path = project / "timeline.json"
    if a.scene:
        _, s = _scene(project, a.scene)
        out = project / "review" / f"scene_{a.scene}.mp4"
        frames = f"{s['from']}-{s['from'] + s['durationInFrames'] - 1}"
    else:
        out, frames = project / "out" / "video.mp4", None
    t0 = _step(f"render {a.scene or 'full video'}")
    render(project, tl_path, out, frames=frames, scale=0.5 if a.draft else None)
    _done(t0, f"-> {out}")


def cmd_still(a) -> None:
    from .render import still

    project = project_dir(a.project)
    _, s = _scene(project, a.scene)
    frame = s["from"] + int(s["durationInFrames"] * a.at)
    out = project / "review" / f"still_{a.scene}_{int(a.at * 100)}.png"
    still(project, project / "timeline.json", frame, out)
    print(out)


def cmd_qa(a) -> None:
    from .qa import run_qa

    project = project_dir(a.project)
    sb = _load(project)
    video = project / "out" / "video.mp4"
    t0 = _step("qa")
    tl = json.loads((project / "timeline.json").read_text())
    report = run_qa(project, video, tl, [i for i in validate(sb) if i.level == "warning"])
    _done(t0)
    print((project / "review" / "qa.md").read_text())
    print(f"Look at: {report['overview']} and {', '.join(report['sheets'])}")


def cmd_make(a) -> int:
    if cmd_validate(a):
        return 1
    ns = argparse.Namespace(**{**vars(a), "mood": None, "seed": 7, "music_db": -19.0, "scene": None})
    t0 = time.time()
    cmd_voice(ns)
    cmd_music(ns)
    cmd_mix(ns)
    cmd_build(ns)
    cmd_render(ns)
    cmd_qa(ns)
    print(f"\nTotal {time.time() - t0:.0f}s -> {project_dir(a.project) / 'out' / 'video.mp4'}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="content_agent", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new", help="create a project with a storyboard skeleton")
    p.add_argument("name")
    p.add_argument("--title")
    p.add_argument("--format", default="explainer", choices=["explainer", "shorts"])
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_new)

    p = sub.add_parser("templates", help="list visual templates and their props")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_templates)

    for name, fn, hlp in [("validate", cmd_validate, "check the storyboard (no rendering)"),
                          ("voice", cmd_voice, "narrate every beat (cached per beat)"),
                          ("build", cmd_build, "storyboard + voice timings -> timeline.json"),
                          ("qa", cmd_qa, "technical checks + contact sheets for review"),
                          ("make", cmd_make, "run the whole pipeline")]:
        p = sub.add_parser(name, help=hlp)
        p.add_argument("project")
        if name == "make":
            p.add_argument("--draft", action="store_true", help="half resolution render (faster)")
        p.set_defaults(fn=fn)

    p = sub.add_parser("music", help="generate procedural background music")
    p.add_argument("project")
    p.add_argument("--mood", choices=MUSIC_MOODS)
    p.add_argument("--seed", type=int, default=7)
    p.set_defaults(fn=cmd_music)

    p = sub.add_parser("mix", help="mix voice + music to the format's loudness")
    p.add_argument("project")
    p.add_argument("--music-db", type=float, default=-19.0)
    p.set_defaults(fn=cmd_mix)

    p = sub.add_parser("render", help="render the video (or one scene) with Remotion")
    p.add_argument("project")
    p.add_argument("--scene", help="render only this scene id into review/scene_<id>.mp4")
    p.add_argument("--draft", action="store_true", help="half resolution (faster)")
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser("still", help="render one frame of a scene as PNG")
    p.add_argument("project")
    p.add_argument("scene")
    p.add_argument("--at", type=float, default=0.6, help="position inside the scene, 0-1")
    p.set_defaults(fn=cmd_still)

    a = ap.parse_args(argv)
    rc = a.fn(a)
    return int(rc or 0)


if __name__ == "__main__":
    sys.exit(main())
