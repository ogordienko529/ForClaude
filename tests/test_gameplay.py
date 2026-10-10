"""Gameplay edit mode: procedural sound, footage analysis, edit validation, timeline build, pacing QA."""

import json
import shutil
import subprocess

import numpy as np
import pytest

from content_agent.gameplay import Edit, analyze, build, import_footage, validate_edit
from content_agent.qa import pacing_checks
from content_agent.sound import SFX_NAMES, beat_music, sfx

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
SR = 16_000


@pytest.mark.parametrize("name", SFX_NAMES)
def test_sfx_are_clean(name):
    x = sfx(name, sr=SR)
    assert x.dtype == np.float32 and len(x) > 0
    assert np.isfinite(x).all() and np.max(np.abs(x)) <= 1.0


def test_beat_music_drop_and_tape_stop():
    bpm, drop = 140, 4.0
    y = beat_music(10.0, bpm, "phonk", drop_at=drop, stops=[(7.0, 8.0)], sr=SR)
    assert len(y) == 10 * SR and np.isfinite(y).all()

    def rms(a, b):
        seg = y[int(a * SR):int(b * SR)]
        return float(np.sqrt(np.mean(seg ** 2)))

    beat = 60 / bpm
    assert rms(0.5, drop - beat - 0.1) < 0.5 * rms(drop, drop + 2)   # quiet build-up, then the drop
    assert rms(drop - beat * 0.5, drop - 0.02) < 0.2 * rms(drop, drop + 2)  # a beat of silence before it
    assert rms(7.4, 7.95) < 0.05 * rms(5, 7)                          # tape-stop gap is silent
    assert rms(8.1, 9.5) > 0.5 * rms(5, 7)                            # and the music comes back


def _make_video(path, seconds=6):
    """3 s static, then a moving box; a full-frame orange 'explosion' at 4-5 s."""
    vf = ("drawbox=enable='between(t,3,6)':x='mod(t*300,260)':y=40:w=60:h=60:color=white:t=fill,"
          "drawbox=enable='between(t,4,5)':x=0:y=0:w=320:h=180:color=0xFF8C1E:t=fill")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x336633:s=320x180:r=30:d={seconds}",
                    "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return path


@needs_ffmpeg
def test_analyze_finds_idle_and_burst(tmp_path):
    a = analyze(_make_video(tmp_path / "raw.mp4"))
    assert a["width"] == 320 and a["duration"] == pytest.approx(6, abs=0.1) and not a["has_audio"]
    assert any(i["start"] == 0 and i["end"] >= 3 for i in a["idle"])
    bursts = [e["t"] for e in a["events"] if e["kind"] == "burst"]
    assert bursts and bursts[0] == 4


@pytest.fixture
def project(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    (tmp_path / "footage").mkdir()
    _make_video(tmp_path / "footage" / "raw.mp4")
    return tmp_path


def _edit(project, **overrides):
    data = {"title": "t", "music": {"style": "phonk", "bpm": 120, "drop": "s02"}, "sfx_on_text": "pop",
            "segments": [
                {"id": "s01", "src": "footage/raw.mp4", "in": 3.0, "beats": 2, "text": {"text": "Hook *here*", "style": "hook"}},
                {"id": "s02", "src": "footage/raw.mp4", "in": 4.0, "beats": 2, "speed": 0.5, "fx": ["shake"],
                 "sfx": ["boom"], "freeze": {"dur": 0.5, "text": "WAIT"}},
                {"id": "s03", "src": "footage/raw.mp4", "in": 0.0, "dur": 1.0, "speed": 2, "framing": "fit"},
            ]}
    data.update(overrides)
    (project / "edit.json").write_text(json.dumps(data))
    return Edit.load(project)


def test_validate_edit_ok_and_errors(project):
    assert [i for i in validate_edit(_edit(project)) if i.level == "error"] == []
    bad = _edit(project, segments=[
        {"id": "a", "src": "footage/missing.mp4", "in": 0, "beats": 2},
        {"id": "b", "src": "footage/raw.mp4", "in": 5.5, "beats": 4, "speed": 2},   # runs past the end
        {"id": "b", "src": "footage/raw.mp4", "in": 0, "beats": 1, "fx": ["wobble"], "sfx": ["laser"],
         "text": {"text": "x", "style": "comic"}, "framing": "wide"},
    ])
    msgs = [str(i) for i in validate_edit(bad)]
    for needle in ("not found", "runs past the end", "duplicate", "unknown fx", "unknown sfx",
                   "unknown text style", "framing", "no text on the first segment"):
        assert any(needle in m for m in msgs), needle


def test_build_timeline(project):
    tl, plan = build(_edit(project))
    clips = tl["clips"]
    assert [c["id"] for c in clips] == ["s01", "s02", "s02_freeze", "s03"]
    for a, b in zip(clips, clips[1:]):
        assert a["from"] + a["durationInFrames"] == b["from"]           # contiguous
    beat = 30 * 60 / 120
    assert clips[0]["durationInFrames"] == round(2 * beat)               # lengths in beats
    assert clips[1]["startFrom"] == 120 and clips[1]["playbackRate"] == 0.5
    freeze = clips[2]
    assert freeze["kind"] == "still" and (project / freeze["src"]).exists() and "bw" in freeze["fx"]
    assert clips[3]["framing"] == "fit" and clips[0]["framing"] == "crop"
    assert plan["drop_at"] == pytest.approx(clips[1]["from"] / 30)
    assert plan["stops"] == [(freeze["from"] / 30, (freeze["from"] + freeze["durationInFrames"]) / 30)]
    assert {s["name"] for s in plan["sfx"]} == {"pop", "boom"}
    hook = tl["texts"][0]
    assert hook["from"] == 0 and hook["to"] == clips[1]["from"]          # text lasts to the segment end
    assert tl["captions"][0]["text"] == "Hook here"
    assert [s["id"] for s in tl["scenes"]] == ["s01", "s02", "s03"]
    assert tl["scenes"][1]["durationInFrames"] == clips[1]["durationInFrames"] + freeze["durationInFrames"]
    assert tl["durationInFrames"] == clips[-1]["from"] + clips[-1]["durationInFrames"]


def test_pacing_checks(project):
    tl, _ = build(_edit(project))
    assert {f.check for f in pacing_checks(tl)} == {"length"}  # 3.5 s demo edit: only too short
    slow, _ = build(_edit(project, segments=[{"id": "s01", "src": "footage/raw.mp4", "in": 0, "dur": 5.0}]))
    checks = {f.check for f in pacing_checks(slow)}
    assert {"pacing", "hook", "length"} <= checks


def test_import_footage_creates_sheets_and_edit(project):
    report = import_footage(project, [project / "footage" / "raw.mp4"])
    a = report["footage/raw.mp4"]
    assert a["sheets"] and all((project / "review" / "raw").exists() for _ in a["sheets"])
    assert (project / "footage" / "raw.analysis.json").exists()
    skeleton = json.loads((project / "edit.json").read_text())
    assert skeleton["segments"][0]["src"] == "footage/raw.mp4"


# ---------------------------------------------------------------- retention structure
def _seg(sid, beats, text=None, **kw):
    s = {"id": sid, "src": "footage/raw.mp4", "in": 0, "beats": beats, **kw}
    if text:
        s["text"] = {"text": text, "style": "hook" if sid == "s01" else "caption"}
    return s


def _redit(tmp_path, segments, drop=None):
    # 120 bpm: one beat is 0.5 s
    return Edit({"title": "t", "music": {"style": "phonk", "bpm": 120, "drop": drop}, "segments": segments}, tmp_path)


def test_retention_good_structure_has_no_warnings(tmp_path):
    from content_agent.gameplay import retention_checks

    segs = [_seg("s01", 3, "WAIT FOR *IT*"), _seg("s02", 6, "1 drone vs 50"), _seg("s03", 6), _seg("s04", 6, "ROUND *2*"),
            _seg("s05", 6), _seg("s06", 6, "LAST ONE"), _seg("s07", 4, "*BOOM*"), _seg("s08", 3, "again?")]
    assert retention_checks(_redit(tmp_path, segs, drop="s07")) == []


def test_retention_flags_long_slow_unstructured_edits(tmp_path):
    from content_agent.gameplay import retention_checks

    segs = [_seg("s01", 6, "this is my drone and my base today"), *[_seg(f"s{i:02d}", 8) for i in range(2, 12)]]
    segs[0]["text"]["at"] = 0.8
    msgs = " | ".join(str(i) for i in retention_checks(_redit(tmp_path, segs)))
    for needle in ("total: breakout Minecraft Shorts", "hook segment is 3.0s", "hook text appears at 0.8s",
                   "hook text has 8 words", "no payoff marked", "no re-hook between"):
        assert needle in msgs, needle


def test_retention_payoff_placement_and_tail(tmp_path):
    from content_agent.gameplay import retention_checks

    early = [_seg("s01", 2, "WATCH"), _seg("s02", 4, "*BOOM*"), *[_seg(f"s{i:02d}", 4) for i in range(3, 9)]]
    msgs = " | ".join(str(i) for i in retention_checks(_redit(tmp_path, early, drop="s02")))
    assert "payoff at" in msgs and "still running after the payoff" in msgs
    too_many = [_seg("s01", 2, "WATCH"), _seg("s02", 4, drop=None)]
    too_many[1]["text"] = [{"text": "a", "dur": 0.3}, {"text": "b"}, {"text": "c"}]
    msgs = " | ".join(str(i) for i in retention_checks(_redit(tmp_path, too_many, drop="s02")))
    assert "3 texts in one segment" in msgs and "shows for 0.3s" in msgs


def test_retention_calm_first_shot_from_footage_analysis(tmp_path):
    from content_agent.gameplay import retention_checks

    (tmp_path / "footage").mkdir()
    per = [{"t": t, "motion": 1.0 if t < 5 else 9.0} for t in range(20)]
    (tmp_path / "footage" / "raw.analysis.json").write_text(json.dumps({"per_second": per}))
    calm = [_seg("s01", 3, "WAIT"), _seg("s02", 6, "BOOM")]
    msgs = " | ".join(str(i) for i in retention_checks(_redit(tmp_path, calm, drop="s02")))
    assert "calm first shot" in msgs
    calm[0]["in"] = 10.0  # open on the action instead
    msgs = " | ".join(str(i) for i in retention_checks(_redit(tmp_path, calm, drop="s02")))
    assert "calm first shot" not in msgs
