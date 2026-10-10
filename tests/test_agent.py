"""The autonomous agent layer: project status, background jobs, MCP tools, runner, doctor."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest

from content_agent import agent, jobs, status
from content_agent.doctor import report, run_checks


@pytest.fixture
def home(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setenv("CONTENT_AGENT_HOME", str(root))
    return root


def _touch(path: Path, text: str = "x", age: float = 0.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if age:
        t = time.time() - age
        os.utime(path, (t, t))


# ---------------------------------------------------------------- status
def test_resolve_accepts_slugs_and_rejects_paths_in_disguise(home):
    assert status.resolve("war_mod") == home / "war_mod"
    for bad in ("../etc", "a/b", "..", "", "c:x"):
        with pytest.raises(ValueError):
            status.resolve(bad)
    assert status.resolve(str(home / "abs")) == (home / "abs").resolve()


def test_next_step_follows_the_pipeline(home):
    p = home / "vid"
    assert status.project_status(p)["kind"] == "empty"
    _touch(p / "storyboard.json", json.dumps({"title": "T", "format": "review", "beats": [{"narration": "a b"}]}), age=50)
    s = status.project_status(p)
    assert s["kind"] == "review" and s["words"] == 2 and "make" in s["next_step"]
    _touch(p / "timeline.json", json.dumps({"fps": 30, "durationInFrames": 300}), age=40)
    assert "render" in status.project_status(p)["next_step"]
    _touch(p / "out" / "video.mp4", age=30)
    assert status.project_status(p)["next_step"] == "run_step qa"
    _touch(p / "review" / "qa.md", age=20)
    s = status.project_status(p)
    assert "thumbnail" in s["next_step"] and s["duration_s"] == 10.0
    _touch(p / "storyboard.json", json.dumps({"title": "T2", "format": "review", "beats": []}))
    assert "make" in status.project_status(p)["next_step"]  # script edited after the build


def test_gameplay_project_and_listing(home):
    p = home / "short"
    _touch(p / "edit.json", json.dumps({"title": "S", "segments": [{}, {}]}))
    _touch(p / "footage" / "a.mp4")
    _touch(p / "footage" / "a.analysis.json", json.dumps({"duration": 12.5, "width": 1280, "height": 720,
                                                          "events": [1, 2], "sheets": ["s.png"]}))
    s = status.project_status(p)
    assert s["kind"] == "gameplay_short" and s["segments"] == 2
    assert s["footage"] == [{"src": "footage/a.mp4", "duration_s": 12.5, "size": "1280x720", "events": 2,
                             "sheets": ["s.png"], "analysed": True}]
    (home / "empty_dir").mkdir()
    assert [x["project"] for x in status.list_projects()] == ["short"]


# ---------------------------------------------------------------- jobs
@pytest.fixture
def fake_cli(monkeypatch):
    """Jobs run a tiny Python script instead of the real pipeline."""
    scripts = {}

    def cli(cmd, project, *rest):
        return [sys.executable, "-c", scripts[cmd]]

    monkeypatch.setattr(jobs, "cli", cli)
    return scripts


def test_job_runs_reports_progress_and_finishes(tmp_path, fake_cli):
    fake_cli["render"] = "print('== render full video'); print('Rendered 30/120'); print('Rendered 90/120')"
    m = jobs.JobManager()
    job = m.wait(m.start(tmp_path, "render"), 20)
    assert job.state == "done" and job.returncode == 0
    assert job.progress() == {"stage": "render full video", "percent": 75, "eta": None}
    assert "Rendered 90/120" in job.tail()
    assert json.loads(job.log.with_suffix(".json").read_text())["returncode"] == 0


def test_log_tail_collapses_frame_counters_and_noise(tmp_path, fake_cli):
    fake_cli["render"] = ("print('== render full video'); print('Memory reported by CGroup: 1 MB');"
                          "[print(f'Rendered {i}/300, time remaining: {300 - i}s') for i in range(1, 151)]")
    m = jobs.JobManager()
    job = m.wait(m.start(tmp_path, "render"), 20)
    assert job.tail() == "== render full video\nRendered 150/300, time remaining: 150s"
    assert job.progress() == {"stage": "render full video", "percent": 50, "eta": "150s"}


def test_one_job_per_project_and_cancel(tmp_path, fake_cli):
    fake_cli["make"] = "import time; time.sleep(30)"
    fake_cli["qa"] = "print('ok')"
    m = jobs.JobManager()
    job = m.start(tmp_path, "make")
    with pytest.raises(RuntimeError, match="still running"):
        m.start(tmp_path, "qa")
    assert m.wait(job, 0.2).state == "running"
    assert m.cancel(job).state == "cancelled"
    assert m.wait(m.start(tmp_path, "qa"), 20).state == "done"
    with pytest.raises(ValueError):
        m.start(tmp_path, "rm -rf")


def test_failed_job(tmp_path, fake_cli):
    fake_cli["build"] = "import sys; print('footage does not cover b07'); sys.exit(1)"
    m = jobs.JobManager()
    job = m.wait(m.start(tmp_path, "build"), 20)
    assert job.state == "failed" and "b07" in job.tail()


# ---------------------------------------------------------------- MCP tools
def test_mcp_tools_listed():
    from content_agent import mcp_server

    names = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert names == {"list_projects", "project_status", "new_project", "import_footage", "detect_mods", "catalog",
                     "validate", "run_step", "job_status", "cancel_job", "preview_frame", "read_qa", "doctor",
                     "propose_options"}


def test_mcp_new_project_validate_and_status(home):
    from content_agent import mcp_server as m

    r = m.new_project("demo", "Demo Video", "explainer")
    assert Path(r["storyboard"]).exists()
    v = m.validate("demo")
    assert v["summary"].startswith("Demo Video") and isinstance(v["errors"], list)
    s = m.project_status("demo")
    assert s["kind"] == "explainer" and s["title"] == "Demo Video"
    assert m.project_status("../x")["error_type"] == "ValueError"
    assert "not found" in m.import_footage("demo", [str(home / "nope.mp4")])["error"]
    assert "templates" in m.catalog() and "meme" in m.catalog()["shorts"]["styles"]
    assert m.read_qa("demo")["error_type"] == "FileNotFoundError"
    assert m.job_status("nope")["error_type"] == "KeyError"


def test_run_step_result_and_error(home, fake_cli, monkeypatch):
    from content_agent import mcp_server as m

    monkeypatch.setattr(m, "JOBS", jobs.JobManager())
    p = home / "vid"
    _touch(p / "review" / "qa.md", "# QA\nall good")
    _touch(p / "review" / "sheet_01.png")
    fake_cli["qa"] = "print('== qa')"
    r = m.run_step("vid", "qa", wait_seconds=20)
    assert r["state"] == "done" and r["result"]["qa_report"].startswith("# QA")
    assert r["result"]["sheets"] == [str(p / "review" / "sheet_01.png")]
    assert "scene" in m.run_step("vid", "render_scene")["error"]


# ---------------------------------------------------------------- runner
def test_agent_prompt_has_no_frontmatter():
    text = agent.agent_prompt()
    assert not text.startswith("---") and "content-maker" in text and "import_footage" in text


def test_build_command_is_headless_scoped_and_logged(home, tmp_path):
    clip = tmp_path / "rec" / "a.mp4"
    _touch(clip)
    msg = agent.task_message("make a short", [clip], "demo", home, plan=True)
    assert str(clip) in msg and "PLAN FIRST" in msg and "Project: demo" in msg
    cmd = agent.build_command("claude", msg, home, [clip])
    assert cmd[:2] == ["claude", "-p"] and msg not in cmd  # the task goes through stdin
    for flag in ("--append-system-prompt-file", "--mcp-config", "--strict-mcp-config", "--max-turns", "--verbose"):
        assert flag in cmd
    assert cmd[cmd.index("--permission-mode") + 1] == "acceptEdits"
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    assert str(clip.parent) in cmd and "mcp__content-agent" in cmd and "Bash" not in cmd
    cfg = json.loads((home / ".agent" / "mcp.json").read_text())
    assert cfg["mcpServers"]["content-agent"]["args"] == ["-m", "content_agent", "mcp"]
    assert cfg["mcpServers"]["content-agent"]["env"]["CONTENT_AGENT_HOME"] == str(home)
    inter = agent.build_command("claude", "hi\nthere", home, [], interactive=True, resume="abc")
    assert "-p" not in inter and inter[inter.index("--resume") + 1] == "abc"
    assert "\n" not in inter[1] and (home / ".agent" / "task.md").read_text() == "hi\nthere"
    assert "--output-format" not in inter


def test_child_env_keeps_subscription_and_detaches_from_parent(home, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "parent")
    monkeypatch.setenv("CLAUDECODE", "1")
    env = agent.child_env(home, use_api_key=False)
    assert "ANTHROPIC_API_KEY" not in env and "CLAUDE_CODE_SESSION_ID" not in env and "CLAUDECODE" not in env
    assert env["CONTENT_AGENT_HOME"] == str(home)
    assert agent.child_env(home, use_api_key=True)["ANTHROPIC_API_KEY"] == "sk-test"


def test_tool_waits_fit_inside_the_tool_timeout(home, monkeypatch):
    monkeypatch.setenv("MCP_TOOL_TIMEOUT", "60000")  # some setups cut tool calls after 60 s
    env = agent.child_env(home, use_api_key=False)
    server_env = agent.mcp_config(home)["mcpServers"]["content-agent"]["env"]
    assert int(env["MCP_TOOL_TIMEOUT"]) / 1000 > int(server_env["CONTENT_AGENT_MAX_WAIT"]) + 60
    from content_agent import mcp_server

    assert mcp_server.MAX_WAIT <= 50  # without the runner: safe under a 60 s client timeout


def test_niche_server_only_with_a_youtube_key(home, monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    assert list(agent.mcp_config(home)["mcpServers"]) == ["content-agent"]
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    cfg = agent.mcp_config(home)
    assert "youtube-niche" in cfg["mcpServers"] and "k" not in json.dumps(cfg)  # the key is inherited, never written


def test_printer_turns_stream_json_into_progress(capsys):
    import io

    out = io.StringIO()
    pr = agent.Printer(out)
    events = [
        {"type": "system", "subtype": "init", "session_id": "s1", "model": "m", "apiKeySource": "none",
         "mcp_servers": [{"name": "content-agent", "status": "connected"}]},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Беру режим шортса."},
            {"type": "tool_use", "id": "t1", "name": "mcp__content-agent__run_step",
             "input": {"project": "demo", "step": "make", "wait_seconds": 300}},
            {"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "/p/review/sheet_01.png"}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1",
             "content": [{"type": "text", "text": json.dumps({"state": "running", "stage": "render", "percent": 40,
                                                              "elapsed_s": 61})}]},
            {"type": "tool_result", "tool_use_id": "t2", "content": "image"}]}},
        {"type": "assistant", "parent_tool_use_id": "x", "message": {"content": [{"type": "text", "text": "sub"}]}},
        {"type": "result", "subtype": "success", "session_id": "s1", "result": "Готово", "num_turns": 3},
    ]
    for ev in events:
        pr.handle(ev)
    text = out.getvalue()
    assert "content-maker started" in text and "Беру режим шортса." in text
    assert "→ run_step" in text and '"step": "make"' in text and "wait_seconds" not in text
    assert "→ Read /p/review/sheet_01.png" in text and "running · render · 40% · 61s" in text
    assert "sub" not in text.splitlines()[-1]
    assert pr.session == "s1" and pr.result["result"] == "Готово"
    assert pr.last_text == "Беру режим шортса."


def test_run_dry_run_and_resume_without_history(home, capsys):
    assert agent.run("make a video", dry_run=True) == 0
    out = capsys.readouterr().out
    assert '"-p"' in out and "stdin:\nTASK FROM THE USER:\nmake a video" in out
    assert agent.run("", resume=True, dry_run=True) == 2
    (home / ".agent" / "last_session.txt").write_text("sess-1")
    assert agent.run("так", resume=True, dry_run=True) == 0
    out = capsys.readouterr().out
    assert '"--resume"' in out and '"sess-1"' in out
    assert agent.run("x", files=[str(home / "missing.mp4")], dry_run=True) == 2


# ---------------------------------------------------------------- doctor
def test_doctor_reports_missing_tools(monkeypatch):
    checks = {c["name"]: c for c in run_checks()}
    assert {"python", "ffmpeg", "node.js 18+", "claude code", "agent + playbooks"} <= set(checks)
    assert checks["agent + playbooks"]["ok"]
    monkeypatch.setenv("PATH", "")
    checks = {c["name"]: c for c in run_checks()}
    assert not checks["ffmpeg"]["ok"] and checks["ffmpeg"]["fix"]
    assert "required check(s) failed" in report(list(checks.values()))


# ---------------------------------------------------------------- options: ideas and edit variants
def _opt(title, fmt="short"):
    return {"title": title, "format": fmt, "pitch": "Коротко.", "why": "3 small channels got 100k+ this month",
            "needs": "nothing", "length": "20 s", "titles": ["A", "B"], "moments": ["65.2 s explosion"]}


def test_options_are_checked_saved_and_rendered(home):
    from content_agent import options as opts

    assert opts.check([_opt("one")])  # fewer than 2
    bad = _opt("x")
    del bad["why"]
    bad["colour"] = "red"
    errs = " ".join(opts.check([bad, _opt("y", fmt="podcast")]))
    assert "missing why" in errs and "unknown fields" in errs and "format must be" in errs
    saved = opts.save(home, "edit_variants", "From the TNT recording.", [_opt("Twist"), _opt("Timelapse", "review")])
    path, batch = opts.latest(home)
    assert str(path) == saved["json"] and batch["kind"] == "edit_variants" and batch["session"] is None
    md = Path(saved["markdown"]).read_text()
    assert "## 1. Twist · Шортс 9:16 · 20 s" in md and "## 2. Timelapse · огляд 16:9" in md
    assert "**Моменти із запису:** 65.2 s explosion" in md and "--pick N" in md
    with pytest.raises(ValueError):
        opts.save(home, "memes", "", [_opt("a"), _opt("b")])


def test_pick_numbers_and_message(home):
    from content_agent import options as opts

    assert opts.parse_pick("2", 3) == [2] and opts.parse_pick("1, 3,1", 3) == [1, 3]
    for bad in ("0", "4", "two", ""):
        with pytest.raises(ValueError):
            opts.parse_pick(bad, 3)
    batch = {"kind": "ideas", "context": "niche data", "options": [_opt("A"), _opt("B"), _opt("C")]}
    msg = opts.pick_message(batch, [1, 3], "make it darker")
    assert "option 1 «A», 3 «C»" in msg and "one after another" in msg and "make it darker" in msg
    assert '"title": "B"' not in msg


def test_mcp_propose_options(home):
    from content_agent import mcp_server as m

    r = m.propose_options("ideas", "Based on compare_niches.", [_opt("A", "explainer"), _opt("B")])
    assert r["count"] == 2 and Path(r["markdown"]).exists() and "stop now" in r["next"]
    assert "missing" in m.propose_options("ideas", "", [{"title": "A"}, _opt("B")])["error"]


def test_task_message_for_options(home, tmp_path):
    clip = tmp_path / "a.mp4"
    _touch(clip)
    ideas = agent.task_message("ideas please", [], None, home, plan=False, options=4)
    assert "OPTIONS FIRST: propose 4 video ideas" in ideas and "Project: none yet" in ideas
    assert "unattended run" not in ideas
    variants = agent.task_message("variants", [clip], None, home, plan=False, options=3)
    assert "propose 3 edit variants" in variants and "choose a short slug" in variants
    _touch(home / "channel.md", "Minecraft mods, English, 16+")
    assert "channel.md" in agent.task_message("x", [], None, home, plan=False)


def test_pick_resumes_the_proposing_session_or_starts_fresh(home, tmp_path, capsys):
    from content_agent import options as opts

    clip = tmp_path / "rec.mp4"
    _touch(clip)
    assert agent.run("", pick="1", dry_run=True) == 2  # nothing proposed yet
    opts.save(home, "edit_variants", "TNT recording", [_opt("Twist"), _opt("Timelapse")], project="tnt")
    path, _ = opts.latest(home)
    opts.update(path, session="sess-9", files=[str(clip)])
    capsys.readouterr()
    assert agent.run("", pick="2", dry_run=True) == 0
    out = capsys.readouterr().out
    assert '"--resume"' in out and '"sess-9"' in out and "option 2 «Timelapse»" in out
    assert agent.run("vertical please", pick="1", fresh=True, dry_run=True) == 0
    out = capsys.readouterr().out
    assert '"--resume"' not in out and "Project: tnt" in out and str(clip) in out and "vertical please" in out
    assert agent.run("", pick="7", dry_run=True) == 2


def test_a_run_that_proposes_options_records_its_session(home, monkeypatch, capsys):
    """End to end with a stand-in for claude: it streams events and saves options like the agent would."""
    fake = home.parent / "fake_claude.py"
    fake.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "sys.stdin.read()\n"
        "from content_agent import options as opts\n"
        f"opts.save(Path({str(home)!r}), 'ideas', 'web search', [\n"
        "  {'title': 'A', 'format': 'explainer', 'pitch': 'p', 'why': 'w', 'needs': 'nothing', 'length': '8 min'},\n"
        "  {'title': 'B', 'format': 'short', 'pitch': 'p', 'why': 'w', 'needs': 'record 2 min', 'length': '20 s'}])\n"
        "print(json.dumps({'type': 'system', 'subtype': 'init', 'session_id': 'S1', 'mcp_servers': []}))\n"
        "print(json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'Два варіанти.'}]}}))\n"
        "print(json.dumps({'type': 'result', 'subtype': 'success', 'session_id': 'S1', 'result': 'Два варіанти.',\n"
        "                  'num_turns': 2, 'duration_ms': 1000}))\n", encoding="utf-8")
    monkeypatch.setattr(agent, "find_claude", lambda: sys.executable)
    monkeypatch.setattr(agent, "build_command", lambda *a, **k: [sys.executable, str(fake)])
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parent.parent))
    assert agent.run("ideas", options=2) == 0
    out = capsys.readouterr().out
    assert "## 1. A · пояснювальне відео 16:9 · 8 min" in out and "--pick N" in out
    from content_agent import options as opts

    assert opts.latest(home)[1]["session"] == "S1"
