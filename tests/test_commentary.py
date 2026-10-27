"""Live-commentary videos: track analysis, cut.json validation, render with stems, QA and dubbing."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from content_agent import commentary as cm

VOICE = ("volume='if(between(t,1,4)+between(t,6,9)+between(t,15,20),0.3,"
         "if(between(t,12,12.6),1.0,0))':eval=frame")                 # talking, and one scream at 12 s
GAME = "volume='if(between(t,25,26),0.9,0.05)':eval=frame"            # quiet game, one explosion at 25 s


def _recording(path: Path, seconds: int = 30) -> Path:
    """Like an OBS recording on 3 tracks: stream 0 mix, 1 microphone, 2 game."""
    subprocess.run([
        "ffmpeg", "-v", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=30:duration={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=220:sample_rate=48000:duration={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=300:sample_rate=48000:duration={seconds}",
        "-f", "lavfi", "-i", f"anoisesrc=sample_rate=48000:duration={seconds}:amplitude=0.5",
        "-filter_complex", f"[1:a]volume=0.1[mix];[2:a]{VOICE}[voice];[3:a]{GAME}[game]",
        "-map", "0:v", "-map", "[mix]", "-map", "[voice]", "-map", "[game]",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
        check=True)
    return path


@pytest.fixture(scope="module")
def rec(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("rec")
    return _recording(d / "session.mp4")


def _project(tmp_path: Path, rec: Path, cut: dict) -> Path:
    p = tmp_path / "proj"
    (p / "footage").mkdir(parents=True)
    (p / "footage" / "session.mp4").write_bytes(rec.read_bytes())
    (p / "cut.json").write_text(json.dumps(cut))
    return p


CUT = {"title": "I Tamed the Wrong Dog", "voice_track": 1, "game_track": 2,
       "cold_open": [{"src": "footage/session.mp4", "in": 12.0, "out": 14.5}],
       "segments": [{"id": "c01", "src": "footage/session.mp4", "in": 1.0, "out": 9.0, "chapter": "The dog"},
                    {"id": "c02", "src": "footage/session.mp4", "in": 15.0, "out": 20.0, "chapter": "Night"},
                    {"id": "c03", "src": "footage/session.mp4", "in": 24.0, "out": 28.0, "chapter": "The end"}]}


def test_audio_streams_and_analysis(rec):
    assert cm.audio_streams(rec) == 3
    a = cm.analyze(rec, voice_track=1, game_track=2, log=lambda m: None)
    starts = [round(s["start"]) for s in a["speech"]]
    assert {1, 6, 12, 15} <= set(starts) or len(a["speech"]) >= 4
    assert [round(r["t"]) for r in a["reactions"]] == [12]           # the scream, not every sentence start
    assert any(abs(e["t"] - 25) <= 1 for e in a["game_events"] if e["kind"] == "game_loud")
    assert 0.3 < a["talk_share"] < 0.8
    md = cm.to_markdown(a)
    assert "Reactions" in md and "0:12" in md
    with pytest.raises(ValueError, match="voice_track 5 does not exist"):
        cm.analyze(rec, voice_track=5, game_track=2, log=lambda m: None)


def test_validate_cut(tmp_path, rec):
    p = _project(tmp_path, rec, CUT)
    issues = cm.validate_cut(p, cm.load(p))
    assert not [i for i in issues if i.level == "error"]
    assert any("min in total" in i.message for i in issues)          # 19.5 s is far below a real upload
    bad = {**CUT, "game_track": 7, "cold_open": [],
           "segments": [{"id": "x", "src": "footage/session.mp4", "in": 9, "out": 5},
                        {"id": "y", "src": "footage/nope.mp4", "in": 0, "out": 1},
                        {"id": "z", "src": "footage/session.mp4", "in": 20, "out": 99}]}
    (p / "cut.json").write_text(json.dumps(bad))
    msgs = [str(i) for i in cm.validate_cut(p, cm.load(p))]
    assert any("must be after in" in m for m in msgs)
    assert any("source not found" in m for m in msgs)
    assert any("past the end" in m for m in msgs)
    assert any("game_track 7 does not exist" in m for m in msgs)
    assert any("no cold open" in m for m in msgs)


def test_render_stems_description_and_qa(tmp_path, rec):
    p = _project(tmp_path, rec, CUT)
    res = cm.render(p, draft=True, log=lambda m: None)
    assert res["parts"] == 4 and res["duration"] == pytest.approx(19.5, abs=0.05)
    from content_agent.gameplay import probe

    info = probe(Path(res["video"]))
    assert info["duration"] == pytest.approx(19.5, abs=0.25) and info["has_audio"]
    voice, sr = sf.read(res["voice_stem"])
    game, _ = sf.read(res["game_stem"])
    assert len(voice) == len(game) == int(round(19.5 * sr)) and game.ndim == 2
    desc = Path(res["description"]).read_text()
    assert "0:00 The dog" in desc and "0:10 Night" in desc and "0:15 The end" in desc
    # the cold open is the scream: louder than the talking that follows
    assert np.abs(voice[: int(2 * sr)]).max() > 2 * np.abs(voice[int(4 * sr): int(9 * sr)]).max()
    rep = cm.qa(p)
    checks = {f["check"] for f in rep["findings"]}
    assert "first_reaction" not in checks                              # reaction right at the start
    assert Path(rep["first_frame"]).exists() and Path(rep["qa"]).exists()
    assert "retention at 0:30" in Path(rep["qa"]).read_text()


def test_qa_flags_a_slow_opening(tmp_path, rec):
    slow = {**CUT, "cold_open": [], "segments": [
        {"id": "c01", "src": "footage/session.mp4", "in": 20.5, "out": 24.5, "chapter": "a"},   # silence first
        {"id": "c02", "src": "footage/session.mp4", "in": 1.0, "out": 9.0, "chapter": "b"},
        {"id": "c03", "src": "footage/session.mp4", "in": 15.0, "out": 20.0, "chapter": "c"}]}
    p = _project(tmp_path, rec, slow)
    cm.render(p, draft=True, log=lambda m: None)
    checks = {f["check"] for f in cm.qa(p)["findings"]}
    assert "opening_voice" in checks and "first_reaction" in checks


def test_dub_keeps_timing_and_original_track(tmp_path, rec):
    p = _project(tmp_path, rec, CUT)
    cm.render(p, draft=True, log=lambda m: None)
    n = int(19.5 * 48000)
    t = np.arange(n) / 48000
    sf.write(p / "dub_en.wav", (0.2 * np.sin(2 * np.pi * 410 * t)).astype(np.float32), 48000)
    res = cm.dub(p, p / "dub_en.wav", log=lambda m: None)
    from content_agent.gameplay import probe

    assert probe(Path(res["video_en"]))["duration"] == pytest.approx(19.5, abs=0.25)
    assert Path(res["audio_original"]).exists() and res["note"] is None
    sf.write(p / "short.wav", np.zeros(48000 * 5, np.float32), 48000)
    assert "padded or trimmed" in cm.dub(p, p / "short.wav", log=lambda m: None)["note"]


def test_status_knows_commentary_projects(tmp_path, rec):
    from content_agent.status import project_status

    p = _project(tmp_path, rec, CUT)
    s = project_status(p)
    assert s["kind"] == "commentary" and s["segments"] == 3 and s["cold_open"]
    assert s["next_step"].startswith("run_step cut")


def test_cuts_snap_to_whole_frames(tmp_path, rec):
    """Six cuts of 1.517 s: each becomes 46 frames, so voice and picture stay together to the last cut."""
    segs = [{"id": f"c{k}", "src": "footage/session.mp4", "in": 1.0 + 3 * k, "out": 2.517 + 3 * k} for k in range(6)]
    p = _project(tmp_path, rec, {**CUT, "cold_open": [], "segments": segs})
    res = cm.render(p, draft=True, log=lambda m: None)
    assert res["duration"] == pytest.approx(6 * 46 / 30, abs=0.01)
    frames = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                             "stream=nb_read_frames", "-of", "csv=p=0", res["video"]],
                            capture_output=True, text=True, check=True).stdout.strip()
    assert int(frames) == 6 * 46
    voice, sr = sf.read(res["voice_stem"])
    assert len(voice) == 6 * 46 * sr // 30


def test_analysis_reuses_the_import_analysis(tmp_path, rec):
    video = tmp_path / "session.mp4"
    video.write_bytes(rec.read_bytes())
    saved = {"duration": 30.0, "events": [{"t": 3.0, "kind": "burst", "score": 9}],
             "per_second": [{"t": t, "motion": 1.0} for t in range(30)]}
    video.with_suffix(".analysis.json").write_text(json.dumps(saved))
    logs: list[str] = []
    a = cm.analyze(video, voice_track=1, game_track=2, log=logs.append)
    assert any(e["t"] == 3.0 and e["kind"] == "burst" for e in a["game_events"])
    assert any("session.analysis.json" in m for m in logs)
