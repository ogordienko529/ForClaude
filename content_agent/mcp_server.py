"""MCP server: the content agent's tools (project state, footage, validation, pipeline jobs, previews).

Run:  python -m content_agent mcp   (stdio transport)
Every CLI step runs in a subprocess, so nothing a step prints can corrupt the MCP stream. Long steps
(voice, render, make) are background jobs: run_step waits up to wait_seconds, then returns a job id
to poll with job_status.
"""

from __future__ import annotations

import functools
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Literal

try:  # mcp >= 2.0 renamed FastMCP to MCPServer
    from mcp.server.mcpserver import Image, MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server, Image

from . import status as st
from .jobs import Job, JobManager, cli

Step = Literal["make", "make_draft", "voice", "music", "mix", "build", "render", "render_draft",
               "render_scene", "qa", "thumbnail"]
Format = Literal["explainer", "shorts", "review"]
OptionsKind = Literal["ideas", "edit_variants"]

# Claude Code cuts a tool call after MCP_TOOL_TIMEOUT (some setups use 60 s), so a call waits at most
# this long; the agent runner raises both. Jobs keep running after a call returns.
MAX_WAIT = int(os.environ.get("CONTENT_AGENT_MAX_WAIT", "50"))
QA_CHARS = 9000

INSTRUCTIONS = """Local, zero-cost video production tools (Kokoro voice, procedural music, ffmpeg, Remotion).
Flow: project_status / list_projects -> new_project or import_footage -> write storyboard.json
(explainer/review) or edit.json (gameplay Short) with your file tools -> validate until ok ->
run_step make (poll job_status while it renders) -> read the QA report and Read the overview and
contact sheet PNGs -> fix by scene id -> run_step again. catalog lists templates, styles, palettes
and music. preview_frame shows one frame of a scene without a full render. When asked for ideas or
variants, save them with propose_options and stop: the user picks one before anything is produced."""

mcp = _Server("content-agent", instructions=INSTRUCTIONS)
JOBS = JobManager()


def _safe(fn):
    """Turn expected failures into structured errors the model can act on."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ValueError, KeyError, RuntimeError, FileNotFoundError) as exc:
            msg = exc.args[0] if isinstance(exc, KeyError) and exc.args else str(exc)
            return {"error": msg, "error_type": type(exc).__name__}

    return wrapper


def _run_cli(*args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cli(*args), capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, stdin=subprocess.DEVNULL)


def _result(job: Job) -> dict[str, Any]:
    p = job.project
    if job.state != "done":
        return {"hint": "the step failed: read log_tail, fix the storyboard/edit (or the cause it names) "
                        "and run the step again"} if job.state == "failed" else {}
    res: dict[str, Any] = {}
    if job.step in ("make", "make_draft", "qa"):
        qa = p / "review" / "qa.md"
        if qa.exists():
            res["qa_report"] = qa.read_text(encoding="utf-8")[:QA_CHARS]
        res["overview"] = str(p / "review" / "overview.png")
        res["sheets"] = [str(x) for x in sorted((p / "review").glob("sheet_*.png"))]
        res["look_at"] = "Read the overview and every contact sheet PNG before deciding what to fix"
    if job.step in ("make", "make_draft", "render", "render_draft"):
        video = p / "out" / "video.mp4"
        res["video"] = str(video)
        if video.exists():
            res["size_mb"] = round(video.stat().st_size / 1e6, 1)
    if job.step == "render_scene":
        res["clip"] = str(p / "review" / f"scene_{job.cmd[-1]}.mp4")
    if job.step == "build":
        res["timeline"] = str(p / "timeline.json")
        if (p / "out" / "description.md").exists():
            res["description"] = str(p / "out" / "description.md")
    if job.step == "thumbnail":
        res["thumbnail"] = str(p / "out" / "thumbnail.png")
    if job.step == "footage":
        res["footage"] = st.footage(p)
        res["look_at"] = "Read the footage sheet PNGs to see what was recorded and when"
    return res


def _job_view(job: Job, log_lines: int = 25) -> dict[str, Any]:
    end = job.ended or time.time()
    view = {"job_id": job.id, "step": job.step, "state": job.state, "elapsed_s": round(end - job.started, 1),
            **job.progress(), "log": str(job.log), "log_tail": job.tail(log_lines)}
    if job.state == "running":
        view["next"] = f"still running: call job_status(job_id, wait_seconds={MAX_WAIT}) again until it is done"
    else:
        view["result"] = _result(job)
    return view


@mcp.tool()
@_safe
def list_projects() -> dict[str, Any]:
    """Projects in the projects folder with their kind and next step."""
    return {"root": str(st.projects_root()), "projects": st.list_projects()}


@mcp.tool()
@_safe
def project_status(project: str) -> dict[str, Any]:
    """What a project has (script, footage, audio, timeline, video, QA), what is stale and the next step.

    project: a slug like "war_mod" (folder under the projects root) or an absolute folder path."""
    p = st.resolve(project)
    info = st.project_status(p)
    busy = JOBS.running_for(p)
    if busy:
        info["running_job"] = _job_view(busy, 5)
    return info


@mcp.tool()
@_safe
def new_project(project: str, title: str, format: Format = "explainer", overwrite: bool = False) -> dict[str, Any]:
    """Create a narrated project (storyboard.json skeleton + research.md). Use import_footage instead for a
    gameplay Short: it creates edit.json. format: explainer (topic video), review (mod review from footage),
    shorts (narrated vertical)."""
    p = st.resolve(project)
    args = ["new", str(p), "--title", title, "--format", format] + (["--force"] if overwrite else [])
    r = _run_cli(*args)
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip())
    return {"project": str(p), "storyboard": str(p / "storyboard.json"), "research": str(p / "research.md"),
            "next": "read the playbook for this format, research, then write storyboard.json"}


@mcp.tool()
@_safe
def import_footage(project: str, paths: list[str], wait_seconds: int = 50) -> dict[str, Any]:
    """Copy recordings into the project, analyse motion/action/idle per second and draw footage sheets
    (thumbnails with timecodes) to Read. Creates an edit.json skeleton when the project has no script yet.
    paths: absolute paths of video files."""
    p = st.resolve(project)
    files = [Path(x).expanduser().resolve() for x in paths]
    missing = [str(f) for f in files if not f.exists()]
    if missing:
        raise FileNotFoundError("not found: " + ", ".join(missing))
    p.mkdir(parents=True, exist_ok=True)
    job = JOBS.start(p, "footage", [str(f) for f in files])
    return _job_view(JOBS.wait(job, min(wait_seconds, MAX_WAIT)), 60)


@mcp.tool()
@_safe
def detect_mods(project: str, source: str) -> dict[str, Any]:
    """List the mods of a recording session from .minecraft/logs/latest.log, a mods folder or a Luanti
    world folder. Saves mods.json. Look every mod up on its official page before writing about it."""
    p = st.resolve(project)
    p.mkdir(parents=True, exist_ok=True)
    r = _run_cli("mods", str(p), str(Path(source).expanduser().resolve()))
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout).strip()[-2000:])
    mods = json.loads((p / "mods.json").read_text(encoding="utf-8"))
    return {"mods": [m for m in mods if not m.get("platform")], "platform_mods_hidden": sum(bool(m.get("platform")) for m in mods),
            "saved": str(p / "mods.json")}


@mcp.tool()
@_safe
def catalog() -> dict[str, Any]:
    """Everything a script can use: the storyboard.json and edit.json formats with every field, visual
    templates with their props, long-form styles and transitions, Shorts text styles and cuts, palettes,
    music moods, voice engines, gameplay fx/sfx/text styles. Call it before writing a script."""
    from .gameplay import CUTS, FX, SHORT_STYLES, TEXT_STYLES
    from .schema import FORMATS, MUSIC_MOODS, PALETTES, STYLES, TEMPLATES, TRANSITIONS, VOICE_ENGINES
    from .sound import SFX_NAMES

    def tname(t) -> str:
        return "/".join(x.__name__ for x in t) if isinstance(t, tuple) else t.__name__

    templates = {k: {"doc": v["doc"], "required": {a: tname(t) for a, t in v["required"].items()},
                     "optional": {a: tname(t) for a, t in v["optional"].items()}, "limits": v["limits"]}
                 for k, v in TEMPLATES.items()}
    from . import gameplay, schema

    refs = {"storyboard_json": schema.__doc__.split("\n\n", 2)[2].strip(),
            "edit_json": "edit.json:" + gameplay.__doc__.split("edit.json:", 1)[1].rstrip()}
    return {"file_formats": refs, "formats": FORMATS, "templates": templates, "styles": STYLES, "transitions": TRANSITIONS,
            "palettes": PALETTES, "music_moods": MUSIC_MOODS, "voice_engines": VOICE_ENGINES,
            "shorts": {"styles": SHORT_STYLES, "cuts": CUTS, "fx": FX, "sfx": SFX_NAMES, "text_styles": TEXT_STYLES}}


@mcp.tool()
@_safe
def validate(project: str) -> dict[str, Any]:
    """Check storyboard.json (or edit.json for a gameplay Short) without rendering. Fix every error before
    run_step; warnings are worth reading."""
    p = st.resolve(project)
    r = _run_cli("validate", str(p), timeout=180)
    lines = (r.stdout + r.stderr).strip().splitlines()
    return {"ok": r.returncode == 0,
            "summary": lines[0] if lines else "",
            "errors": [ln for ln in lines if ln.startswith("ERROR")],
            "warnings": [ln for ln in lines if ln.startswith("WARNING")],
            "output": "\n".join(lines[-80:]) if r.returncode and not any(ln.startswith("ERROR") for ln in lines) else ""}


@mcp.tool()
@_safe
def run_step(project: str, step: Step, scene: str | None = None, wait_seconds: int = 50) -> dict[str, Any]:
    """Run a pipeline step as a background job and wait up to wait_seconds for it (capped by the server).

    make = validate -> voice -> music -> mix -> build -> render -> qa (gameplay: build -> render -> qa);
    make_draft / render_draft render at half resolution (faster, for a first look);
    render_scene re-renders one scene (scene=id) into review/scene_<id>.mp4;
    thumbnail renders out/thumbnail.png from the storyboard's "thumbnail" block.
    After changing narration run make again; after changing only visuals, build + render + qa is enough.
    If the result says running, poll job_status(job_id)."""
    p = st.resolve(project)
    if step == "render_scene" and not scene:
        raise ValueError("render_scene needs scene=<scene id>")
    job = JOBS.start(p, step, [scene] if step == "render_scene" else None)
    return _job_view(JOBS.wait(job, min(wait_seconds, MAX_WAIT)))


@mcp.tool()
@_safe
def job_status(job_id: str, wait_seconds: int = 50, log_lines: int = 25) -> dict[str, Any]:
    """Wait up to wait_seconds (capped by the server) for a job, then report its state, progress, log tail
    and result. The job keeps running between calls: call again until state is done or failed."""
    job = JOBS.wait(JOBS.get(job_id), min(wait_seconds, MAX_WAIT))
    return _job_view(job, log_lines)


@mcp.tool()
@_safe
def cancel_job(job_id: str) -> dict[str, Any]:
    """Stop a running job (and its renderer processes)."""
    return _job_view(JOBS.cancel(JOBS.get(job_id)), 10)


@mcp.tool()
def preview_frame(project: str, scene: str, at: float = 0.6) -> list:
    """Render one frame of a scene (needs timeline.json from build) and show it. at: 0-1 inside the scene."""
    try:
        p = st.resolve(project)
        r = _run_cli("still", str(p), scene, "--at", str(at), timeout=600)
        if r.returncode:
            return [f"error: {(r.stderr or r.stdout).strip()[-1500:]}"]
        path = Path(r.stdout.strip().splitlines()[-1])
        return [f"{path}", Image(path=path)]
    except (ValueError, subprocess.TimeoutExpired) as exc:
        return [f"error: {exc}"]


@mcp.tool()
@_safe
def read_qa(project: str) -> dict[str, Any]:
    """The last QA report (technical checks, pacing, rubric) and the sheet images to Read, without re-running QA."""
    p = st.resolve(project)
    qa = p / "review" / "qa.md"
    if not qa.exists():
        raise FileNotFoundError("no QA report yet: run_step qa (or make)")
    return {"qa_report": qa.read_text(encoding="utf-8")[:QA_CHARS], "overview": str(p / "review" / "overview.png"),
            "sheets": [str(x) for x in sorted((p / "review").glob("sheet_*.png"))]}


@mcp.tool()
@_safe
def propose_options(kind: OptionsKind, context: str, options: list[dict[str, Any]],
                    project: str | None = None) -> dict[str, Any]:
    """Save the options you propose (2-6) so the user can pick one by number, then stop and present them.

    kind: "ideas" (what video to make) or "edit_variants" (different ways to cut a recording).
    context: one or two sentences on what the options are based on (data, footage, channel).
    Each option: title (working title, English), format ("short" | "explainer" | "review"),
    pitch (1-2 sentences, Ukrainian), why (evidence it can work: numbers, example videos with views
    and subscriber counts, trends; never invented), needs (what the user must do: "nothing" or a short
    shooting list), length ("20 s", "10 min"); optional: titles (list of YouTube titles), hook (first
    shot + line), moments (timecodes from the footage it uses), style, effort (time to make), sources
    (URLs)."""
    from . import options as opts

    saved = opts.save(st.projects_root(), kind, context, options, project)
    return {**saved, "count": len(options),
            "next": "stop now: summarise the options in Ukrainian in a few lines; the user picks with --pick N"}


@mcp.tool()
@_safe
def doctor() -> dict[str, Any]:
    """Check this machine: Python packages, ffmpeg, Node.js, renderer packages, voice model, Claude Code,
    API keys (set or not, never the value) and free disk space."""
    from .doctor import report, run_checks

    checks = run_checks()
    return {"ready": all(c["ok"] for c in checks if c["required"]), "checks": checks, "report": report(checks)}


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
