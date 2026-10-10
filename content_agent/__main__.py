"""Local video pipeline driven by Claude Code (or by hand).

    python -m content_agent new concorde --title "Why Concorde Stopped Flying"
    # edit content_projects/concorde/storyboard.json (the agent writes it)
    python -m content_agent make concorde          # validate -> voice -> music -> mix -> build -> render -> qa
    python -m content_agent still concorde b07     # preview one scene as a PNG
    python -m content_agent render concorde --scene b07   # re-render one scene as a clip for checking

Gameplay edits (no voice-over, 9:16):
    python -m content_agent footage mc_tnt raw_gameplay.mp4   # import + analyse + footage sheets
    # write content_projects/mc_tnt/edit.json (the agent picks moments, zooms, texts, SFX)
    python -m content_agent make mc_tnt                       # validate -> soundtrack -> build -> render -> qa

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
    return p if (p / "storyboard.json").exists() or (p / "edit.json").exists() or p.is_absolute() else ROOT / name


def _gameplay(project: Path) -> bool:
    return (project / "edit.json").exists() and not (project / "storyboard.json").exists()


def _edit_issues(project: Path):
    from .gameplay import Edit, validate_edit

    edit = Edit.load(project)
    return edit, validate_edit(edit)


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


def cmd_styles(a) -> None:
    from .gameplay import CUTS, SHORT_STYLES
    from .schema import STYLES, TRANSITIONS

    print('Long-form styles (storyboard "style"):')
    for k, v in STYLES.items():
        print(f"  {k:8s} {v}")
    print(f"  per-beat override: \"transition\": {' | '.join(TRANSITIONS)}")
    print('\nShorts text styles (edit.json "style"):')
    for k, v in SHORT_STYLES.items():
        print(f"  {k:8s} {v}")
    print(f"  per-segment override: \"transition\": {' | '.join(CUTS)}")


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


def cmd_footage(a) -> None:
    from .gameplay import import_footage

    project = project_dir(a.project)
    t0 = _step("footage")
    report = import_footage(project, [Path(v) for v in a.videos])
    _done(t0)
    for src, r in report.items():
        print(f"{src}: {r['duration']:.1f}s {r['width']}x{r['height']} @{r['fps']:.0f}fps"
              f"{' with audio' if r['has_audio'] else ' (no audio)'}")
        print("  events: " + ", ".join(f"{e['kind']}@{e['t']}s" for e in r["events"][:20]))
        print("  idle: " + ", ".join(f"{i['start']}-{i['end']}s" for i in r["idle"]))
        print("  look at: " + ", ".join(r["sheets"]))
    if (project / "edit.json").exists():
        print(f"edit list: {project / 'edit.json'}")


def cmd_validate(a) -> int:
    project = project_dir(a.project)
    if _gameplay(project):
        edit, issues = _edit_issues(project)
        print(f"{edit.data.get('title', '')}: {len(edit.segments)} segments")
        for i in issues:
            print(i)
        errors = [i for i in issues if i.level == "error"]
        print("OK" if not errors else f"{len(errors)} error(s): fix edit.json before rendering")
        return 1 if errors else 0
    sb = _load(project)
    issues = validate(sb)
    words = sum(len(b.get("narration", "").split()) for b in sb.beats)
    print(f"{sb.title}: {len(sb.beats)} beats, {words} words (~{words / 160:.1f} min at a documentary pace)")
    for i in issues:
        print(i)
    errors = [i for i in issues if i.level == "error"]
    print("OK" if not errors else f"{len(errors)} error(s): fix the storyboard before rendering")
    return 1 if errors else 0


def cmd_voice(a) -> None:
    from .audio import make_voice_engine, synthesize_voice

    project = project_dir(a.project)
    sb = _load(project)
    fmt = sb.data.get("format", "explainer")
    engine_name = sb.data.get("voice_engine", "kokoro")
    t0 = _step(f"voice ({engine_name})")
    engine = make_voice_engine(engine_name, sb.data.get("voice") or None, fmt, sb.data.get("voice_options"))
    timing = synthesize_voice(sb.beats, project / "audio" / "voice.wav", fmt=fmt, engine=engine,
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
    if mood in ("hype", "phonk"):  # a beat under the voice (ducked in the mix), for reviews and gaming videos
        from .sound import beat_music

        music = beat_music(timing["duration"] + 1.0, bpm=100 if mood == "hype" else 120, style=mood, seed=a.seed) * 0.6
    else:
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
    if _gameplay(project):
        from .gameplay import Edit, build, render_soundtrack

        t0 = _step("build (timeline + soundtrack)")
        tl, plan = build(Edit.load(project))
        info = render_soundtrack(project, plan, project / "audio" / "mix.wav")
        write_timeline(tl, project / "timeline.json")
        _done(t0, f"({len(tl['clips'])} clips, {tl['durationInFrames'] / tl['fps']:.1f}s, {len(plan['sfx'])} sfx, "
                  f"-> {info['target_lufs']:.0f} LUFS)")
        return
    sb = _load(project)
    timing = json.loads((project / "audio" / "voice_timing.json").read_text())
    if [b["id"] for b in timing["beats"]] != [b["id"] for b in sb.beats]:
        sys.exit("voice timings do not match the storyboard beats: run `voice` (and music/mix) again")
    audio = "audio/mix.wav" if (project / "audio" / "mix.wav").exists() else "audio/voice.wav"
    tl = build_timeline(sb.data, timing, audio, fmt=sb.data.get("format", "explainer"))
    problems = _check_footage(project, tl)
    if problems:
        sys.exit("footage does not cover these scenes:\n" + "\n".join(problems))
    write_timeline(tl, project / "timeline.json")
    desc = _write_description(project, sb, tl)
    print(f"timeline: {len(tl['scenes'])} scenes, {tl['durationInFrames'] / tl['fps']:.1f}s; description: {desc}",
          file=sys.stderr)


def _check_footage(project: Path, tl: dict) -> list[str]:
    """Every footage scene needs enough recording after its `in` point (scene length x speed)."""
    from .gameplay import probe

    lengths: dict[str, float] = {}
    out = []
    for s in tl["scenes"]:
        if s["template"] != "footage":
            continue
        src = s["props"]["src"]
        if not (project / src).exists():
            out.append(f"  {s['id']}: {src} not found")
            continue
        lengths.setdefault(src, probe(project / src)["duration"])
        need = s["durationInFrames"] / tl["fps"] * float(s["props"].get("speed", 1))
        start = float(s["props"]["in"])
        if start + need > lengths[src] + 0.05:
            out.append(f"  {s['id']}: needs {need:.1f}s of {src} from {start}s but it ends at {lengths[src]:.1f}s "
                       f"(start earlier or raise speed to {need / max(lengths[src] - start, 0.1):.2f})")
    return out


def _tc(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def _write_description(project: Path, sb: Storyboard, tl: dict) -> Path:
    """YouTube description: chapters from beats with "chapter", credits and sources."""
    lines = [sb.title, ""]
    chapters = [(s["from"] / tl["fps"], s["chapter"]) for s in tl["scenes"] if s.get("chapter")]
    if chapters:
        lines.append("Chapters:")
        lines += [f"{_tc(0 if i == 0 else t)} {name}" for i, (t, name) in enumerate(chapters)]
        lines.append("")
    credits = sb.data.get("credits", [])
    if credits:
        lines.append("Shown in this video:")
        for c in credits:
            extra = ", ".join(x for x in (c.get("author"), c.get("license")) if x)
            lines.append(f"- {c['name']}" + (f" ({extra})" if extra else "") + (f": {c['url']}" if c.get("url") else ""))
        lines.append("")
    sources = sorted({u for b in sb.beats for u in b.get("sources", []) if u.startswith("http")})
    if sources:
        lines.append("Sources:")
        lines += [f"- {u}" for u in sources]
        lines.append("")
    if sb.data.get("music", "calm") != "none":
        lines.append("Music: original, generated for this video.")
    out = project / "out" / "description.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def cmd_thumbnail(a) -> None:
    """storyboard "thumbnail": {"src": "footage/x.mp4", "t": 61.5, "title": "This mod is *insane*", "tag": "Mod review"}"""
    import subprocess

    from .render import still

    project = project_dir(a.project)
    sb = _load(project)
    th = sb.data.get("thumbnail")
    if not th:
        sys.exit('add "thumbnail": {"src", "t", "title", "tag"} to the storyboard')
    frame = project / "build" / "thumb_src.png"
    frame.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(th.get("t", 0)), "-i", str(project / th["src"]),
                    "-frames:v", "1", "-vf",
                    # drop the bottom 12% (game HUD / hotbar), then fill 1280x720
                    "crop=iw:ih*0.88:0:0,scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720",
                    str(frame)], check=True)
    props = project / "build" / "thumbnail.json"
    props.write_text(json.dumps({"image": "build/thumb_src.png", "title": th["title"], "tag": th.get("tag", "")}))
    out = project / "out" / "thumbnail.png"
    still(project, props, 0, out, comp="Thumbnail")
    print(out)


def cmd_mods(a) -> None:
    from .mods import load_mods

    project = project_dir(a.project)
    mods = load_mods(Path(a.source))
    (project / "mods.json").parent.mkdir(parents=True, exist_ok=True)
    (project / "mods.json").write_text(json.dumps(mods, indent=2) + "\n")
    for m in mods:
        if not m["platform"]:
            print(f"{m['id']:28s} {m['version']:20s} {m['loader']}")
    print(f"-> {project / 'mods.json'} (look each one up on its official page before writing about it)")


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
    warnings = [i for i in (_edit_issues(project)[1] if _gameplay(project) else validate(_load(project)))
                if i.level == "warning"]
    video = project / "out" / "video.mp4"
    t0 = _step("qa")
    tl = json.loads((project / "timeline.json").read_text())
    report = run_qa(project, video, tl, warnings)
    _done(t0)
    print((project / "review" / "qa.md").read_text())
    print(f"Look at: {report['overview']} and {', '.join(report['sheets'])}")


def cmd_make(a) -> int:
    if cmd_validate(a):
        return 1
    ns = argparse.Namespace(**{**vars(a), "mood": None, "seed": 7, "music_db": -19.0, "scene": None})
    t0 = time.time()
    if not _gameplay(project_dir(a.project)):
        cmd_voice(ns)
        cmd_music(ns)
        cmd_mix(ns)
    cmd_build(ns)
    cmd_render(ns)
    cmd_qa(ns)
    print(f"\nTotal {time.time() - t0:.0f}s -> {project_dir(a.project) / 'out' / 'video.mp4'}", file=sys.stderr)
    return 0


def cmd_mcp(a) -> None:
    from .mcp_server import main as serve

    serve()


def cmd_doctor(a) -> int:
    from .doctor import report, run_checks

    checks = run_checks()
    print(report(checks))
    return 1 if any(c["required"] and not c["ok"] for c in checks) else 0


def cmd_setup(a) -> int:
    """One-time setup: renderer packages, voice model, MCP registration for interactive Claude Code."""
    import shutil
    import subprocess

    from .agent import PARENT_SESSION_VARS
    from .doctor import REPO
    from .render import ensure_node_modules
    from .status import projects_root

    t0 = _step("renderer packages (npm install)")
    try:
        ensure_node_modules()
        _done(t0)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(f"   skipped: {exc}", file=sys.stderr)
    t0 = _step("Kokoro voice model")
    try:
        from sleep_voice.engine import ensure_models

        ensure_models()
        _done(t0)
    except Exception as exc:  # network or disk problems: report and keep going
        print(f"   skipped: {exc}", file=sys.stderr)
    claude = shutil.which("claude")
    if a.no_register or not claude:
        if not claude:
            print("\nClaude Code not found: MCP registration skipped", file=sys.stderr)
    else:
        scope = "user" if a.everywhere else "local"
        t0 = _step(f"register the content-agent MCP server in Claude Code ({scope} scope)")
        env = {k: v for k, v in os.environ.items() if k not in PARENT_SESSION_VARS}
        subprocess.run([claude, "mcp", "remove", "content-agent", "-s", scope], cwd=REPO, capture_output=True, env=env)
        # the name goes before -e: -e takes several values and would swallow it
        r = subprocess.run([claude, "mcp", "add", "content-agent", "--scope", scope, "--transport", "stdio",
                            "-e", f"CONTENT_AGENT_HOME={projects_root()}", "--",
                            sys.executable, "-m", "content_agent", "mcp"], cwd=REPO, capture_output=True, text=True,
                           env=env)
        print("   " + (r.stdout or r.stderr).strip().replace("\n", "\n   "), file=sys.stderr)
        if r.returncode:
            print("   registration failed: the agent command still works, only plain `claude` lacks the tools",
                  file=sys.stderr)
    print()
    return cmd_doctor(a)


def cmd_agent(a) -> int:
    from .agent import run

    task = " ".join(a.task).strip()
    if not (task or a.resume or a.session or a.interactive or a.pick or a.options):
        sys.exit('say what to make, e.g.: content-agent agent "a 20 s Short from this" --files clip.mp4\n'
                 'or ask for ideas: content-agent ideas')
    if not task and a.options:
        task = "Propose edit variants for these recordings." if a.files else "Propose video ideas for my channel."
    return run(task, a.files, a.project, plan=a.plan, resume=a.resume, session=a.session,
               interactive=a.interactive, max_turns=a.max_turns, model=a.model, use_api_key=a.use_api_key,
               dry_run=a.dry_run, options=a.options, pick=a.pick, fresh=a.fresh)


def cmd_ideas(a) -> int:
    from .agent import run

    hint = " ".join(a.hint).strip()
    task = f"Propose {a.count} video ideas for my channel" + (f", around: {hint}" if hint else "") + "."
    return run(task, a.files, None, options=a.count, max_turns=a.max_turns, model=a.model,
               use_api_key=a.use_api_key, dry_run=a.dry_run)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="content_agent", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new", help="create a project with a storyboard skeleton")
    p.add_argument("name")
    p.add_argument("--title")
    p.add_argument("--format", default="explainer", choices=["explainer", "shorts", "review"])
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_new)

    p = sub.add_parser("footage", help="import gameplay recordings: analyse and draw footage sheets")
    p.add_argument("project")
    p.add_argument("videos", nargs="+")
    p.set_defaults(fn=cmd_footage)

    p = sub.add_parser("mods", help="list the mods in a recording from latest.log, a mods folder or a Luanti world")
    p.add_argument("project")
    p.add_argument("source")
    p.set_defaults(fn=cmd_mods)

    p = sub.add_parser("thumbnail", help="render out/thumbnail.png from the storyboard's thumbnail settings")
    p.add_argument("project")
    p.set_defaults(fn=cmd_thumbnail)

    p = sub.add_parser("styles", help="list the visual styles (long-form and Shorts)")
    p.set_defaults(fn=cmd_styles)

    p = sub.add_parser("templates", help="list visual templates and their props")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_templates)

    for name, fn, hlp in [("validate", cmd_validate, "check the storyboard or edit list (no rendering)"),
                          ("voice", cmd_voice, "narrate every beat (cached per beat)"),
                          ("build", cmd_build, "-> timeline.json (gameplay: also the soundtrack)"),
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

    p = sub.add_parser("agent", help="run the content-maker agent: it makes the whole video by itself")
    p.add_argument("task", nargs="*", help="what to make, in any language")
    p.add_argument("--files", "-f", nargs="+", default=[], help="footage, latest.log, a shooting script...")
    p.add_argument("--project", "-p", help="project slug (default: the agent picks one)")
    p.add_argument("--plan", action="store_true", help="stop after the script for your approval")
    p.add_argument("--resume", "-r", action="store_true", help="continue the last run (the task is your answer)")
    p.add_argument("--session", help="continue this session id instead of the last one")
    p.add_argument("--interactive", "-i", action="store_true", help="chat with the agent in Claude Code")
    p.add_argument("--max-turns", type=int, default=250)
    p.add_argument("--model", help="Claude model alias or id (default: your Claude Code default)")
    p.add_argument("--use-api-key", action="store_true", help="bill ANTHROPIC_API_KEY instead of the subscription")
    p.add_argument("--dry-run", action="store_true", help="print the claude command and exit")
    p.add_argument("--options", type=int, nargs="?", const=4, metavar="N",
                   help="propose N options (default 4) and stop: ideas, or edit variants of --files")
    p.add_argument("--pick", metavar="N[,M]", help="make option N (or several) from the last proposal")
    p.add_argument("--fresh", action="store_true", help="with --pick: start a new session instead of continuing")
    p.set_defaults(fn=cmd_agent)

    p = sub.add_parser("ideas", help="the agent proposes video ideas backed by niche data; pick one with agent --pick")
    p.add_argument("hint", nargs="*", help="optional theme, e.g. minecraft mods")
    p.add_argument("--count", type=int, default=4)
    p.add_argument("--files", "-f", nargs="+", default=[], help="recordings to build ideas around")
    p.add_argument("--max-turns", type=int, default=120)
    p.add_argument("--model")
    p.add_argument("--use-api-key", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_ideas)

    p = sub.add_parser("mcp", help="run the MCP server (stdio) with the agent's tools")
    p.set_defaults(fn=cmd_mcp)

    p = sub.add_parser("doctor", help="check this machine for everything the agent needs")
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("setup", help="one-time setup: npm packages, voice model, MCP registration, checks")
    p.add_argument("--everywhere", action="store_true", help="register the MCP tools for every folder (user scope)")
    p.add_argument("--no-register", action="store_true", help="do not register the MCP server in Claude Code")
    p.set_defaults(fn=cmd_setup)

    a = ap.parse_args(argv)
    rc = a.fn(a)
    return int(rc or 0)


if __name__ == "__main__":
    sys.exit(main())
