"""Environment checks for the content agent, with a fix hint for each problem (Windows, macOS, Linux)."""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REMOTION_DIR = Path(__file__).resolve().parent / "remotion"
AGENT_FILE = REPO / ".claude" / "agents" / "content-maker.md"
PLAYBOOKS = {name: REPO / ".claude" / "skills" / name / "SKILL.md"
             for name in ("make-video", "edit-gameplay", "review-video")}
KEYS = ("YOUTUBE_API_KEY", "ELEVENLABS_API_KEY", "OPENAI_API_KEY")


def _hint(win: str, mac: str, linux: str) -> str:
    return win if os.name == "nt" else mac if sys.platform == "darwin" else linux


def _version(cmd: list[str]) -> str | None:
    exe = shutil.which(cmd[0])
    if not exe:
        return None
    try:
        r = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = (r.stdout or r.stderr).strip().splitlines()
    return out[0] if out else ""


def check(name: str, ok: bool, detail: str = "", fix: str = "", required: bool = True) -> dict:
    return {"name": name, "ok": ok, "detail": detail, "fix": "" if ok else fix, "required": required}


def run_checks() -> list[dict]:
    out = []
    v = sys.version_info
    out.append(check("python", v >= (3, 11), f"{v.major}.{v.minor}.{v.micro} at {sys.executable}",
                     "install Python 3.11+ from python.org and recreate the venv"))

    missing = [m for m in ("numpy", "soundfile", "kokoro_onnx", "PIL", "mcp", "httpx")
               if importlib.util.find_spec(m) is None]
    out.append(check("python packages", not missing, "all installed" if not missing else "missing: " + ", ".join(missing),
                     'pip install -e ".[agent]"  (inside the venv, in the repo folder)'))

    for tool in ("ffmpeg", "ffprobe"):
        ver = _version([tool, "-version"])
        out.append(check(tool, ver is not None, (ver or "")[:60],
                         _hint("winget install Gyan.FFmpeg  (then open a new terminal)",
                               "brew install ffmpeg", "sudo apt install ffmpeg")))

    node = _version(["node", "--version"])
    major = int(re.sub(r"[^\d.]", "", node).split(".")[0] or 0) if node else 0
    out.append(check("node.js 18+", major >= 18, node or "not found",
                     _hint("winget install OpenJS.NodeJS.LTS  (then open a new terminal)",
                           "brew install node", "install Node.js LTS from nodejs.org or with nvm")))

    deps = (REMOTION_DIR / "node_modules" / "remotion").exists()
    out.append(check("renderer packages", deps, "installed" if deps else "not installed yet",
                     "python -m content_agent setup  (runs npm install once)", required=False))

    try:
        from sleep_voice.engine import MODEL_DIR, MODEL_FILES

        have = all((MODEL_DIR / f).exists() for f in MODEL_FILES)
        out.append(check("kokoro voice model", have, str(MODEL_DIR) if have else "not downloaded yet (~340 MB)",
                         "python -m content_agent setup  (downloads it once)", required=False))
    except ImportError:
        out.append(check("kokoro voice model", False, "sleep_voice not importable", 'pip install -e ".[agent]"'))

    claude = _version(["claude", "--version"])
    out.append(check("claude code", claude is not None, claude or "not found",
                     "install Claude Code: https://code.claude.com/docs/en/setup, then run `claude` once to log in"))

    files = [AGENT_FILE, *PLAYBOOKS.values()]
    lost = [str(p.relative_to(REPO)) for p in files if not p.exists()]
    out.append(check("agent + playbooks", not lost, "found" if not lost else "missing: " + ", ".join(lost),
                     "run from a git clone of the repo installed with pip install -e ."))

    for key in KEYS:
        is_set = bool(os.environ.get(key, "").strip())
        use = {"YOUTUBE_API_KEY": "niche research", "ELEVENLABS_API_KEY": "ElevenLabs voices",
               "OPENAI_API_KEY": "OpenAI voices"}[key]
        out.append(check(key, is_set, "set" if is_set else f"not set (only needed for {use})",
                         _hint(f'setx {key} "..."  then open a new terminal',
                               f"export {key}=... in ~/.zshrc", f"export {key}=... in ~/.bashrc"),
                         required=False))

    from .status import projects_root

    root = projects_root()
    probe = root if root.exists() else root.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    free_gb = shutil.disk_usage(probe).free / 1e9
    out.append(check("free disk space", free_gb >= 5, f"{free_gb:.0f} GB free at {probe}",
                     "free up space: renders and footage need several GB", required=False))
    return out


def report(checks: list[dict]) -> str:
    lines = []
    for c in checks:
        mark = "OK " if c["ok"] else ("ERR" if c["required"] else " - ")
        lines.append(f"[{mark}] {c['name']:20s} {c['detail']}")
        if c["fix"]:
            lines.append(f"{'':27s}fix: {c['fix']}")
    bad = [c for c in checks if c["required"] and not c["ok"]]
    lines.append("")
    lines.append("Ready." if not bad else f"{len(bad)} required check(s) failed.")
    return "\n".join(lines)
