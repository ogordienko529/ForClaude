"""Background jobs: long pipeline steps (voice, render, make...) run as CLI subprocesses with a log file.

The MCP server starts a job, waits a bounded time and returns either the result or a job id the
agent polls with job_status. A step never blocks a tool call for longer than the caller allows.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# step -> extra CLI arguments after "<cmd> <project>"
STEPS: dict[str, tuple[str, list[str]]] = {
    "make": ("make", []),
    "make_draft": ("make", ["--draft"]),
    "voice": ("voice", []),
    "music": ("music", []),
    "mix": ("mix", []),
    "build": ("build", []),
    "render": ("render", []),
    "render_draft": ("render", ["--draft"]),
    "render_scene": ("render", ["--scene"]),  # + scene id
    "qa": ("qa", []),
    "thumbnail": ("thumbnail", []),
    "footage": ("footage", []),  # + video paths
}

PROGRESS = re.compile(r"(\d+)\s*/\s*(\d+)")
STAGE = re.compile(r"^== (.+)$")
ETA = re.compile(r"time remaining:\s*([\dhms ]+)")
# Remotion prints one line per frame; keep the last line of each run of these
COUNTER = re.compile(r"^(Rendered|Encoded|Bundling|Downloading|Rendering)\b")
# environment chatter that says nothing about the job
NOISE = re.compile(r"^(Detected differing memory amounts|Memory reported by|You might have inadvertently|"
                   r"Using the lower amount of memory)")


def cli(*args: str) -> list[str]:
    return [sys.executable, "-m", "content_agent", *args]


@dataclass
class Job:
    id: str
    project: Path
    step: str
    cmd: list[str]
    log: Path
    started: float = field(default_factory=time.time)
    ended: float | None = None
    returncode: int | None = None
    proc: subprocess.Popen | None = None

    @property
    def state(self) -> str:
        if self.returncode is None:
            return "running"
        if self.returncode == 0:
            return "done"
        return "cancelled" if self.returncode == -999 else "failed"

    def poll(self) -> None:
        if self.returncode is None and self.proc is not None:
            rc = self.proc.poll()
            if rc is not None:
                self.returncode, self.ended = rc, time.time()
                self._save()

    def _save(self) -> None:
        meta = {"id": self.id, "project": str(self.project), "step": self.step, "cmd": self.cmd,
                "log": str(self.log), "started": self.started, "ended": self.ended,
                "returncode": self.returncode}
        self.log.with_suffix(".json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")

    def lines(self) -> list[str]:
        """The log without per-frame counters (only the latest of each run) and environment noise."""
        if not self.log.exists():
            return []
        text = self.log.read_text(encoding="utf-8", errors="replace")
        out: list[str] = []
        for ln in text.splitlines():
            ln = ln.rsplit("\r", 1)[-1].rstrip()  # progress bars rewrite one line with \r
            if not ln.strip() or NOISE.match(ln.strip()):
                continue
            m = COUNTER.match(ln.strip())
            if m and out and out[-1].strip().startswith(m.group(1)):
                out[-1] = ln
            else:
                out.append(ln)
        return out

    def tail(self, lines: int = 30) -> str:
        return "\n".join(self.lines()[-lines:])

    def progress(self) -> dict:
        stage, pct, eta = None, None, None
        for ln in self.lines():
            m = STAGE.match(ln.strip())
            if m:
                stage, pct, eta = m.group(1), None, None
                continue
            for a, b in PROGRESS.findall(ln):
                a, b = int(a), int(b)
                if 0 < b and a <= b and b >= 10:
                    pct = round(100 * a / b)
            e = ETA.search(ln)
            eta = e.group(1).strip() if e else (eta if pct != 100 else None)
        return {"stage": stage, "percent": pct, "eta": eta}


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()

    def running_for(self, project: Path) -> Job | None:
        with self.lock:
            for j in self.jobs.values():
                j.poll()
                if j.project == project and j.state == "running":
                    return j
        return None

    def start(self, project: Path, step: str, extra: list[str] | None = None) -> Job:
        if step not in STEPS:
            raise ValueError(f"unknown step {step!r} (known: {', '.join(STEPS)})")
        busy = self.running_for(project)
        if busy:
            raise RuntimeError(f"job {busy.id} ({busy.step}) is still running for this project: "
                               "wait for it with job_status or cancel_job it first")
        cmd_name, flags = STEPS[step]
        cmd = cli(cmd_name, str(project), *flags, *(extra or []))
        jid = f"{time.strftime('%H%M%S')}-{step}-{uuid.uuid4().hex[:4]}"
        logdir = project / "agent" / "jobs"
        logdir.mkdir(parents=True, exist_ok=True)
        job = Job(jid, project, step, cmd, logdir / f"{jid}.log")
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        kwargs: dict = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        with open(job.log, "wb") as fh:
            job.proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                        env=env, **kwargs)
        job._save()
        with self.lock:
            self.jobs[jid] = job
        return job

    def get(self, job_id: str) -> Job:
        with self.lock:
            job = self.jobs.get(job_id)
        if not job:
            raise KeyError(f"no job {job_id!r} in this session")
        job.poll()
        return job

    def wait(self, job: Job, seconds: float) -> Job:
        deadline = time.time() + max(0.0, seconds)
        while True:
            job.poll()
            if job.state != "running" or time.time() >= deadline:
                return job
            time.sleep(0.5)

    def cancel(self, job: Job) -> Job:
        job.poll()
        if job.state == "running" and job.proc is not None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(job.proc.pid)], capture_output=True)
            else:
                try:
                    os.killpg(job.proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            try:
                job.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                job.proc.kill()
            job.returncode, job.ended = -999, time.time()
            job._save()
        return job
