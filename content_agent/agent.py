"""Run content-maker autonomously: Claude Code in headless mode with the content-agent MCP tools.

    content-agent agent "make a 20 s Short from this" --files D:\\rec\\tnt.mp4
    content-agent agent --resume "use ElevenLabs voice Adam"      # answer / continue the last run
    content-agent agent -i "war mod video" --project war_mod       # chat with the agent instead

Claude Code runs on the user's subscription (`claude` logged in once). ANTHROPIC_API_KEY is removed
from its environment unless --use-api-key is given: with a key present, headless runs bill the API.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .doctor import AGENT_FILE, PLAYBOOKS, REPO
from .status import projects_root

SERVER = "content-agent"
NICHE_SERVER = "youtube-niche"
# Read-only and web tools plus our MCP servers are pre-approved; file edits are allowed inside the
# working folders by acceptEdits; any other shell command is denied (nobody is there to approve it).
ALLOWED = ["Read", "Glob", "Grep", "WebSearch", "WebFetch", "TodoWrite", f"mcp__{SERVER}", "Bash(ffprobe *)"]
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
MAX_WAIT = 300          # seconds one job_status call may wait for a render
TOOL_TIMEOUT_MS = 900_000  # MCP_TOOL_TIMEOUT for the run, comfortably above MAX_WAIT


def agent_prompt() -> str:
    """The content-maker system prompt: the agent file without its frontmatter."""
    text = AGENT_FILE.read_text(encoding="utf-8")
    if text.startswith("---"):
        text = text.split("---", 2)[2]
    return text.strip() + "\n"


def state_dir(root: Path) -> Path:
    d = root / ".agent"
    (d / "runs").mkdir(parents=True, exist_ok=True)
    return d


def mcp_config(root: Path) -> dict:
    env = {"CONTENT_AGENT_HOME": str(root), "PYTHONIOENCODING": "utf-8", "CONTENT_AGENT_MAX_WAIT": str(MAX_WAIT)}
    servers = {SERVER: {"type": "stdio", "command": sys.executable, "args": ["-m", "content_agent", "mcp"],
                        "env": env}}
    if os.environ.get("YOUTUBE_API_KEY", "").strip():  # niche research, if the user has a key
        servers[NICHE_SERVER] = {"type": "stdio", "command": sys.executable, "args": ["-m", "niche_mcp"]}
    return {"mcpServers": servers}


def _size(path: Path) -> str:
    try:
        n = path.stat().st_size
    except OSError:
        return "missing"
    return f"{n / 1e9:.1f} GB" if n > 1e9 else f"{n / 1e6:.0f} MB" if n > 1e6 else f"{n / 1e3:.0f} KB"


def task_message(task: str, files: list[Path], project: str | None, root: Path, plan: bool) -> str:
    lines = ["TASK FROM THE USER:", task.strip(), ""]
    if project:
        lines.append(f"Project: {project} (folder {root / project})")
    else:
        lines.append("Project: choose a short slug (lowercase, underscores) and create it under the projects folder.")
    lines.append(f"Projects folder: {root}")
    if files:
        lines.append("Input files (absolute paths):")
        for f in files:
            kind = "video" if f.suffix.lower() in VIDEO_EXT else "file"
            lines.append(f"- {f} ({kind}, {_size(f)})")
    lines.append("Playbooks: " + ", ".join(f"{k}: {v}" for k, v in PLAYBOOKS.items()))
    lines.append("")
    lines.append("This is an unattended run: nobody can answer questions until it ends. Work autonomously to a "
                 "finished, self-reviewed video, then give the final report in Ukrainian.")
    if plan:
        lines.append("PLAN FIRST: stop after the script validates and present the plan for approval.")
    return "\n".join(lines)


def build_command(claude: str, message: str, root: Path, files: list[Path], *, interactive: bool = False,
                  resume: str | None = None, max_turns: int = 250, model: str | None = None) -> list[str]:
    sd = state_dir(root)
    prompt_file = sd / "content-maker.prompt.md"
    prompt_file.write_text(agent_prompt(), encoding="utf-8")
    cfg_file = sd / "mcp.json"
    cfg = mcp_config(root)
    cfg_file.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    allowed = ALLOWED + ([f"mcp__{NICHE_SERVER}"] if NICHE_SERVER in cfg["mcpServers"] else [])

    # The task never goes on the command line: through claude.cmd (npm install on Windows) cmd.exe
    # would cut a multi-line argument. Headless runs read it from stdin; interactive runs get a
    # one-line pointer to a file.
    cmd = [claude]
    if not interactive:
        cmd.append("-p")
    elif message:
        task_file = sd / "task.md"
        task_file.write_text(message, encoding="utf-8")
        cmd.append(f"Read {task_file} and do the task described there.")
    if resume:
        cmd += ["--resume", resume]
    cmd += ["--append-system-prompt-file", str(prompt_file),
            "--mcp-config", str(cfg_file), "--strict-mcp-config",
            "--permission-mode", "acceptEdits",
            "--add-dir", str(root)]
    for d in sorted({str(f.parent) for f in files}):
        cmd += ["--add-dir", d]
    cmd += ["--allowedTools", *allowed]
    if model:
        cmd += ["--model", model]
    if not interactive:
        cmd += ["--max-turns", str(max_turns), "--output-format", "stream-json", "--verbose"]
    return cmd


# Set when the runner is started from inside a Claude Code session (e.g. by a local Claude through its
# shell): without removing them the child would attach to the parent's session.
PARENT_SESSION_VARS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_REMOTE_SESSION_ID",
                       "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_TEE_SDK_STDOUT", "CLAUDE_CODE_POST_FOR_SESSION_INGRESS_V",
                       "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_SYNC_SESSION_REFS",
                       "CLAUDE_CODE_SYNC_SKILLS", "CLAUDE_CODE_SESSION_ATTENDED", "CLAUDE_PID")


def child_env(root: Path, use_api_key: bool) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in PARENT_SESSION_VARS}
    env["CONTENT_AGENT_HOME"] = str(root)
    env.setdefault("MCP_TIMEOUT", "60000")
    env["MCP_TOOL_TIMEOUT"] = str(max(TOOL_TIMEOUT_MS, int(env.get("MCP_TOOL_TIMEOUT") or 0)))
    if not use_api_key:
        env.pop("ANTHROPIC_API_KEY", None)
    return env


# ---------------------------------------------------------------- progress printing
def _short(value, n: int = 110) -> str:
    s = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _tool_label(name: str) -> str:
    for prefix in (f"mcp__{SERVER}__", f"mcp__{NICHE_SERVER}__"):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def _args_label(name: str, args: dict) -> str:
    if name in ("Read", "Write", "Edit"):
        return str(args.get("file_path", ""))
    if name in ("WebSearch",):
        return str(args.get("query", ""))
    if name == "WebFetch":
        return str(args.get("url", ""))
    if name == "Bash":
        return str(args.get("command", ""))
    keep = {k: v for k, v in args.items() if k not in ("wait_seconds", "log_lines")}
    return _short(keep, 100) if keep else ""


def _result_text(block: dict) -> str:
    c = block.get("content")
    if isinstance(c, list):
        return "\n".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
    return c if isinstance(c, str) else ""


def _result_label(name: str, text: str, is_error: bool) -> str | None:
    if is_error:
        return "ERROR " + _short(text, 160)
    if not name.startswith("mcp__"):
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    if data.get("error"):
        return "ERROR " + _short(data["error"], 160)
    if "state" in data:
        bits = [data["state"]]
        if data.get("stage"):
            bits.append(str(data["stage"]))
        if data.get("percent") is not None:
            bits.append(f"{data['percent']}%")
        bits.append(f"{data.get('elapsed_s', 0):.0f}s")
        return " · ".join(bits)
    if "ok" in data:
        return "ok" if data["ok"] else f"{len(data.get('errors', []))} error(s)"
    return None


class Printer:
    """Turns stream-json events into a readable log line by line."""

    def __init__(self, out=None) -> None:
        self.out = out or sys.stdout
        self.tools: dict[str, str] = {}
        self.session: str | None = None
        self.result: dict | None = None
        self.last_text = ""
        self.t0 = time.time()

    def p(self, text: str) -> None:
        print(text, file=self.out, flush=True)

    def stamp(self) -> str:
        s = int(time.time() - self.t0)
        return f"{s // 60:02d}:{s % 60:02d}"

    def handle(self, ev: dict) -> None:
        t = ev.get("type")
        if t == "system" and ev.get("subtype") == "init":
            self.session = ev.get("session_id")
            servers = ", ".join(f"{s.get('name')}={s.get('status')}" for s in ev.get("mcp_servers", []))
            self.p(f"[{self.stamp()}] content-maker started · model {ev.get('model')} · auth {ev.get('apiKeySource')} · {servers}")
            bad = [s for s in ev.get("mcp_servers", []) if s.get("status") != "connected"]
            if bad:
                self.p(f"          ! MCP server not connected: {bad}. Run: python -m content_agent doctor")
        elif t == "system" and ev.get("subtype") == "api_retry":
            self.p(f"[{self.stamp()}] API retry {ev.get('attempt')}/{ev.get('max_retries')}: {ev.get('error_status')}")
        elif t == "assistant" and not ev.get("parent_tool_use_id"):
            for b in ev.get("message", {}).get("content", []):
                if b.get("type") == "text" and b.get("text", "").strip():
                    self.last_text = b["text"].strip()
                    self.p(f"[{self.stamp()}] {self.last_text}")
                elif b.get("type") == "tool_use":
                    self.tools[b["id"]] = b["name"]
                    label = _args_label(b["name"], b.get("input") or {})
                    self.p(f"[{self.stamp()}]   → {_tool_label(b['name'])} {label}".rstrip())
        elif t == "user" and isinstance(ev.get("message", {}).get("content"), list):
            for b in ev["message"]["content"]:
                if b.get("type") != "tool_result":
                    continue
                name = self.tools.get(b.get("tool_use_id"), "")
                label = _result_label(name, _result_text(b), bool(b.get("is_error")))
                if label:
                    self.p(f"[{self.stamp()}]     {label}")
        elif t == "result":
            self.result = ev
            self.session = ev.get("session_id") or self.session


def expand(files: list[str]) -> list[str]:
    """Expand wildcards ourselves: Windows shells pass clips\\*.mp4 through literally."""
    import glob

    out = []
    for f in files:
        hits = sorted(glob.glob(os.path.expanduser(f))) if any(c in f for c in "*?[") else []
        out += hits or [f]
    return out


def find_claude() -> str | None:
    return shutil.which("claude")


def run(task: str, files: list[str] | None = None, project: str | None = None, *, plan: bool = False,
        resume: bool = False, session: str | None = None, interactive: bool = False, max_turns: int = 250,
        model: str | None = None, use_api_key: bool = False, dry_run: bool = False) -> int:
    claude = find_claude()
    if not claude and not dry_run:
        print("Claude Code is not installed: https://code.claude.com/docs/en/setup (then run `claude` once to log in)",
              file=sys.stderr)
        return 2
    root = projects_root()
    root.mkdir(parents=True, exist_ok=True)
    paths = [Path(f).expanduser().resolve() for f in expand(files or [])]
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        print("not found: " + ", ".join(missing), file=sys.stderr)
        return 2
    sd = state_dir(root)
    last = sd / "last_session.txt"
    sid = session
    if resume and not sid:
        sid = last.read_text(encoding="utf-8").strip() if last.exists() else None
        if not sid:
            print("no previous run to resume", file=sys.stderr)
            return 2
    if sid:
        message = task.strip() or "Continue where you stopped."
        if paths:
            message += "\nNew input files:\n" + "\n".join(f"- {p} ({_size(p)})" for p in paths)
    else:
        message = task_message(task, paths, project, root, plan)
    cmd = build_command(claude or "claude", message, root, paths, interactive=interactive, resume=sid,
                        max_turns=max_turns, model=model)
    if dry_run:
        print(json.dumps(cmd, indent=1, ensure_ascii=False))
        if not interactive:
            print("stdin:\n" + message)
        return 0
    env = child_env(root, use_api_key)
    if use_api_key is False and os.environ.get("ANTHROPIC_API_KEY"):
        print("note: ANTHROPIC_API_KEY is ignored for this run so it uses your Claude subscription "
              "(pass --use-api-key to bill the API instead)", file=sys.stderr)
    if interactive:
        return subprocess.call(cmd, cwd=REPO, env=env)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    log = sd / "runs" / f"{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    printer = Printer()
    print(f"log: {log}", file=sys.stderr)
    with open(log, "w", encoding="utf-8") as fh:
        proc = subprocess.Popen(cmd, cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                stdin=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        proc.stdin.write(message)
        proc.stdin.close()
        try:
            for line in proc.stdout:
                fh.write(line)
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    printer.p(line)
                    continue
                known = printer.session
                printer.handle(ev)
                if printer.session and printer.session != known:
                    last.write_text(printer.session, encoding="utf-8")
        except KeyboardInterrupt:
            proc.terminate()
            print("\nstopped. Continue later with: content-agent agent --resume", file=sys.stderr)
            return 130
        err = proc.stderr.read()
        rc = proc.wait()
    res = printer.result
    if res is None:
        print(err.strip()[-3000:] or f"claude exited with code {rc}", file=sys.stderr)
        return rc or 1
    mins = (res.get("duration_ms") or 0) / 60000
    final = (res.get("result") or "\n".join(res.get("errors") or []) or res.get("subtype", "")).strip()
    print("\n" + "=" * 70)
    if final != printer.last_text:  # the final report was usually just printed as the last message
        print(final)
        print("=" * 70)
    print(f"{res.get('subtype')} · {res.get('num_turns')} turns · {mins:.1f} min · session {printer.session}")
    if res.get("permission_denials"):
        names = sorted({d.get("tool_name", "?") for d in res["permission_denials"]})
        print(f"denied (not pre-approved): {', '.join(names)}")
    if res.get("subtype") == "error_max_turns":
        print("Turn limit reached. Continue with: content-agent agent --resume")
    print("Answer or continue: content-agent agent --resume \"...\"")
    return 0 if not res.get("is_error") else 1
