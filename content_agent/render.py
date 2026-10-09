"""Render a project's timeline.json with the local Remotion project (headless Chromium, offline)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REMOTION_DIR = Path(__file__).parent / "remotion"

# Pre-installed browsers (e.g. Playwright's) avoid Remotion downloading Chrome on first run.
BROWSER_CANDIDATES = [
    "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell",
]


def find_browser() -> str | None:
    env = os.environ.get("CONTENT_AGENT_BROWSER")
    if env:
        return env
    return next((c for c in BROWSER_CANDIDATES if Path(c).exists()), None)


def composition(timeline_path: Path) -> str:
    """The Remotion composition that renders this timeline."""
    kind = json.loads(Path(timeline_path).read_text(encoding="utf-8")).get("kind")
    return "Gameplay" if kind == "gameplay" else "Video"


def ensure_node_modules() -> None:
    if not (REMOTION_DIR / "node_modules" / "remotion").exists():
        npm = shutil.which("npm")
        if not npm:
            raise RuntimeError("Node.js is required for rendering: install it from https://nodejs.org (LTS)")
        print("Installing renderer dependencies (one time)...", file=sys.stderr)
        subprocess.run([npm, "install", "--no-audit", "--no-fund"], cwd=REMOTION_DIR, check=True)


def render(project: Path, timeline_path: Path, out: Path, frames: str | None = None,
           concurrency: int | None = None, scale: float | None = None) -> Path:
    """frames: optional 'start-end' range for quick re-renders of one scene."""
    ensure_node_modules()
    npx = shutil.which("npx")
    if not npx:
        raise RuntimeError("npx not found: install Node.js")
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [npx, "remotion", "render", "src/index.ts", composition(timeline_path), str(out.resolve()),
           f"--props={timeline_path.resolve()}", f"--public-dir={project.resolve()}",
           "--codec=h264", "--crf=18"]
    browser = find_browser()
    if browser:
        cmd.append(f"--browser-executable={browser}")
    if frames:
        cmd.append(f"--frames={frames}")
    cmd.append(f"--concurrency={concurrency or max(1, (os.cpu_count() or 2) - 1)}")
    if scale:
        cmd.append(f"--scale={scale}")
    subprocess.run(cmd, cwd=REMOTION_DIR, check=True)
    return out


def still(project: Path, timeline_path: Path, frame: int, out: Path) -> Path:
    """Render a single frame (fast preview for checking one scene)."""
    ensure_node_modules()
    cmd = [shutil.which("npx") or "npx", "remotion", "still", "src/index.ts", composition(timeline_path), str(out.resolve()),
           f"--props={timeline_path.resolve()}", f"--public-dir={project.resolve()}", f"--frame={frame}",
           "--log=error"]
    browser = find_browser()
    if browser:
        cmd.append(f"--browser-executable={browser}")
    subprocess.run(cmd, cwd=REMOTION_DIR, check=True)
    return out
