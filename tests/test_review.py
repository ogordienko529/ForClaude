"""Mod-review mode: mod list parsing, footage/verdict templates, voice engine choice, chapters, footage checks."""

import copy
import json
import shutil
import subprocess

import pytest

from content_agent.__main__ import _check_footage, _write_description, main
from content_agent.audio import make_voice_engine
from content_agent.mods import load_mods, parse_log, parse_mods_dir
from content_agent.schema import Storyboard, validate

FABRIC_LOG = """[12:00:01] [main/INFO]: Loading Minecraft 1.20.1 with Fabric Loader 0.15.7
[12:00:01] [main/INFO]: Loading 5 mods:
\t- fabric-api 0.92.0+1.20.1
\t   |-- fabric-api-base 0.4.31+1802ada577
\t- fabricloader 0.15.7
\t- java 17
\t- minecraft 1.20.1
\t- sodium 0.5.8+mc1.20.1
[12:00:02] [main/INFO]: SpongePowered MIXIN Subsystem Version=0.8.5
"""

FORGE_LOG = """[main/INFO] [ne.mi.fm.lo.mo.ModDiscoverer/SCAN]: Found valid mod file create-1.20.1-0.5.1.f.jar with {create} mods - versions {0.5.1.f}
[main/INFO] [ne.mi.fm.lo.mo.ModDiscoverer/SCAN]: Found valid mod file jei-1.20.1-forge-15.2.0.27.jar with {jei} mods - versions {15.2.0.27}
"""


def test_parse_fabric_log():
    mods = {m["id"]: m for m in parse_log(FABRIC_LOG)}
    assert set(mods) == {"fabric-api", "fabricloader", "java", "minecraft", "sodium"}  # sub-mods skipped
    assert mods["sodium"]["version"] == "0.5.8+mc1.20.1" and mods["sodium"]["loader"] == "fabric"
    assert mods["minecraft"]["platform"] and not mods["sodium"]["platform"]


def test_parse_forge_log():
    mods = {m["id"]: m for m in parse_log(FORGE_LOG)}
    assert mods["create"]["version"] == "0.5.1.f" and mods["jei"]["file"].startswith("jei-")


def test_parse_mods_folder_and_luanti_world(tmp_path):
    (tmp_path / "mods").mkdir()
    for name in ("sodium-fabric-0.5.8+mc1.20.1.jar", "Xaeros_Minimap_24.0.3_Fabric_1.20.jar", "weird.jar"):
        (tmp_path / "mods" / name).write_text("")
    ids = {m["id"]: m["version"] for m in parse_mods_dir(tmp_path / "mods")}
    assert ids["sodium-fabric"] == "0.5.8+mc1.20.1" and "weird" in ids
    world = tmp_path / "world"
    (world / "worldmods" / "nether").mkdir(parents=True)
    (world / "worldmods" / "nether" / "mod.conf").write_text("name = nether\n")
    (world / "world.mt").write_text("gameid = minetest_game\nload_mod_mobs_redo = true\nload_mod_off = false\n")
    assert [m["id"] for m in load_mods(world)] == ["mobs_redo", "nether"]


REVIEW = {
    "title": "Mod Review", "format": "review", "voice_engine": "kokoro", "music": "hype", "palette": "slate",
    "beats": [
        {"id": "b01", "chapter": "Intro", "narration": "This mod adds a whole new world to explore.",
         "visual": {"template": "footage", "props": {"src": "footage/raw.mp4", "in": 0.5, "label": "Nether"}}},
        {"id": "b02", "chapter": "Portal", "narration": "You build the portal from fourteen obsidian blocks.",
         "visual": {"template": "footage", "props": {"src": "footage/raw.mp4", "in": 2.0, "speed": 2}},
         "sources": ["https://example.org/mod"]},
        {"id": "b03", "chapter": "Verdict", "narration": "I would give it eight out of ten overall.",
         "visual": {"template": "verdict", "props": {"score": 8, "pros": ["New world"], "cons": ["Dark"]}},
         "sources": ["local test"]},
    ],
}


def _issues(data):
    return validate(Storyboard(copy.deepcopy(data)))


def test_review_storyboard_validates():
    assert [i for i in _issues(REVIEW) if i.level == "error"] == []
    assert not any("in a row" in i.message for i in _issues(REVIEW))  # footage clips may follow each other


@pytest.mark.parametrize("change,needle", [
    (lambda d: d.update(voice_engine="robot"), "voice_engine must be one of"),
    (lambda d: d.update(voice_engine="elevenlabs", voice=""), "ElevenLabs voice_id"),
    (lambda d: d["beats"][0]["visual"]["props"].update(focus=[2, 0]), "focus"),
    (lambda d: d["beats"][1]["visual"]["props"].update(speed=50), "speed"),
    (lambda d: d["beats"][0]["visual"]["props"].pop("src"), "missing prop 'src'"),
    (lambda d: d["beats"][2]["visual"]["props"].update(pros=["a"] * 6), "at most"),
    (lambda d: d["beats"][1].pop("chapter") and d["beats"][2].pop("chapter"), "chapters"),
    (lambda d: d.update(format="podcast"), "format must be one of"),
])
def test_review_validation_findings(change, needle):
    d = copy.deepcopy(REVIEW)
    change(d)
    assert any(needle in i.message for i in _issues(d)), [str(i) for i in _issues(d)]


def test_elevenlabs_engine_needs_a_key(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ELEVENLABS_API_KEY"):
        make_voice_engine("elevenlabs", "some_voice_id", "review")


def test_review_engine_defaults(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key-not-real")
    eng = make_voice_engine("elevenlabs", "voice123", "review")
    assert "voice123" in eng.engine_id and "|0.45|" in eng.engine_id  # livelier stability for reviews


def _timeline():
    return {"fps": 30, "scenes": [
        {"id": "b01", "template": "footage", "props": {"src": "footage/raw.mp4", "in": 0.5}, "from": 0,
         "durationInFrames": 60, "chapter": "Intro"},
        {"id": "b02", "template": "footage", "props": {"src": "footage/raw.mp4", "in": 2.0, "speed": 2}, "from": 60,
         "durationInFrames": 60, "chapter": "Portal"},
        {"id": "b03", "template": "verdict", "props": {"score": 8}, "from": 120, "durationInFrames": 330,
         "chapter": "Verdict"},
    ]}


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_footage_check_reports_overruns(tmp_path):
    (tmp_path / "footage").mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=160x90:r=30:d=6",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(tmp_path / "footage" / "raw.mp4")], check=True)
    tl = _timeline()
    assert _check_footage(tmp_path, tl) == []                 # b01: 0.5-2.5 s, b02: 2 s at x2 = 2.0-6.0 s
    tl["scenes"][1]["durationInFrames"] = 120                 # 4 s at speed 2 = 8 s from 2.0 > 6 s
    problems = _check_footage(tmp_path, tl)
    assert len(problems) == 1 and "b02" in problems[0] and "raise speed" in problems[0]
    tl["scenes"][0]["props"]["src"] = "footage/missing.mp4"
    assert any("not found" in p for p in _check_footage(tmp_path, tl))


def test_description_has_chapters_credits_and_sources(tmp_path):
    sb = Storyboard(dict(copy.deepcopy(REVIEW), credits=[
        {"name": "Nether mod", "author": "PilzAdam and contributors", "license": "WTFPL", "url": "https://example.org/n"}]))
    out = _write_description(tmp_path, sb, _timeline())
    text = out.read_text()
    assert "Chapters:\n0:00 Intro\n0:02 Portal\n0:04 Verdict" in text
    assert "- Nether mod (PilzAdam and contributors, WTFPL): https://example.org/n" in text
    assert "https://example.org/mod" in text and "local test" not in text  # only URLs are listed as sources
    assert "Music: original" in text


def test_cli_mods_command(tmp_path, capsys):
    log = tmp_path / "latest.log"
    log.write_text(FABRIC_LOG)
    project = tmp_path / "proj"
    project.mkdir()
    (project / "storyboard.json").write_text(json.dumps(REVIEW))
    assert main(["mods", str(project), str(log)]) == 0
    out = capsys.readouterr().out
    assert "sodium" in out and "minecraft" not in out.split("->")[0]  # platform entries hidden
    assert json.loads((project / "mods.json").read_text())
