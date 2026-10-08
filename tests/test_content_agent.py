"""content_agent tests: storyboard validation, timeline, captions, voice timing (fake engine), music, mix, QA."""

import copy
import json
import shutil
import subprocess

import numpy as np
import pytest
import soundfile as sf

from content_agent.__main__ import main
from content_agent.audio import ambient_music, mix, synthesize_voice
from content_agent.qa import contact_sheets, technical_checks
from content_agent.schema import Storyboard, validate
from content_agent.timeline import build_timeline, chunk_text

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")

GOOD = {
    "title": "Test",
    "format": "explainer",
    "palette": "midnight",
    "music": "calm",
    "beats": [
        {"id": "b01", "narration": "There was a time when you could cross the ocean before lunch.",
         "visual": {"template": "kinetic", "props": {"lines": ["Before lunch."]}}},
        {"id": "b02", "narration": "It cruised at more than twice the speed of sound, in 1976.",
         "visual": {"template": "stat", "props": {"value": 2.04, "label": "Cruising speed", "prefix": "Mach"}},
         "sources": ["https://example.org/a"]},
        {"id": "b03", "narration": "It flew from London to New York in about three and a half hours.",
         "visual": {"template": "map_route", "props": {"from": {"name": "London", "lat": 51.5, "lon": -0.4},
                                                       "to": {"name": "New York", "lat": 40.6, "lon": -73.8}}}},
    ],
}


def _issues(data):
    return validate(Storyboard(copy.deepcopy(data)))


def _with(beat_idx, **visual):
    d = copy.deepcopy(GOOD)
    d["beats"][beat_idx]["visual"] = visual
    return d


def test_valid_storyboard_has_no_issues():
    assert _issues(GOOD) == []


@pytest.mark.parametrize("data,level,needle", [
    (_with(0, template="hologram", props={}), "error", "unknown template"),
    (_with(1, template="stat", props={"label": "x"}), "error", "missing prop 'value'"),
    (_with(1, template="stat", props={"value": "fast", "label": "x"}), "error", "wrong type"),
    (_with(2, template="map_point", props={"place": {"name": "X", "lat": 120, "lon": 0}}), "error", "lat"),
    (_with(0, template="kinetic", props={"lines": ["x" * 60]}), "warning", "line longer"),
    (_with(0, template="kinetic", props={"lines": ["a"], "colour": "red"}), "warning", "unknown prop"),
    (_with(0, template="timeline", props={"events": [{"year": "1969"}]}), "error", "year and label"),
])
def test_validation_findings(data, level, needle):
    issues = _issues(data)
    assert any(i.level == level and needle in i.message for i in issues), issues


def test_validation_flags_repetition_duplicates_and_missing_sources():
    d = copy.deepcopy(GOOD)
    for b in d["beats"]:
        b["visual"] = {"template": "kinetic", "props": {"lines": ["Same look."]}}
    d["beats"][2]["id"] = "b01"
    d["beats"].append({"id": "b04", "narration": "Fourteen of them flew with airlines, seven each.",
                       "visual": {"template": "stat", "props": {"value": 14, "label": "In service"}}})
    msgs = [str(i) for i in _issues(d)]
    assert any("three 'kinetic' scenes in a row" in m for m in msgs)
    assert any("duplicate beat id" in m for m in msgs)
    assert any("[b04]" in m and "no sources" in m for m in msgs)  # data template without sources


def test_chunk_text_keeps_words_and_limits():
    s = ("Concorde burned roughly twice as much fuel per hour as a jumbo jet, while carrying a quarter "
         "of the passengers across the same ocean.")
    parts = chunk_text(s, 50)
    assert " ".join(parts) == s
    assert all(len(p) <= 50 * 1.25 for p in parts)
    assert len(parts) >= 3
    assert chunk_text("Short.", 50) == ["Short."]


def _timing():
    return {"duration": 12.0, "beats": [
        {"id": "b01", "start": 0.6, "end": 3.5, "sentences": [{"start": 0.6, "end": 3.5, "text": "One."}]},
        {"id": "b02", "start": 4.1, "end": 7.8, "sentences": [{"start": 4.1, "end": 7.8, "text": "Two " * 40}]},
        {"id": "b03", "start": 8.4, "end": 10.4, "sentences": [{"start": 8.4, "end": 10.4, "text": "Three."}]},
    ]}


def test_build_timeline_scenes_are_contiguous():
    tl = build_timeline(GOOD, _timing(), "audio/mix.wav")
    scenes = tl["scenes"]
    assert [s["id"] for s in scenes] == ["b01", "b02", "b03"]
    assert scenes[0]["from"] == 0
    for a, b in zip(scenes, scenes[1:]):
        assert a["from"] + a["durationInFrames"] == b["from"]
    assert scenes[-1]["from"] + scenes[-1]["durationInFrames"] == tl["durationInFrames"] == 360
    assert all(s["speechOffset"] >= 0 for s in scenes)
    assert abs(scenes[1]["speechOffset"] - 0.35 * 30) <= 1  # cut slightly before the words
    assert (tl["width"], tl["height"]) == (1920, 1080)
    long_caps = [c for c in tl["captions"] if c["text"].startswith("Two")]
    assert len(long_caps) > 1 and all(len(c["text"]) <= 100 for c in long_caps)
    assert long_caps[0]["from"] == round(4.1 * 30) and long_caps[-1]["to"] == round(7.8 * 30)


def test_shorts_timeline_is_vertical():
    tl = build_timeline(GOOD, _timing(), "a.wav", fmt="shorts")
    assert (tl["width"], tl["height"]) == (1080, 1920)


class FakeEngine:
    sample_rate = 24000
    engine_id = "fake"

    def synthesize(self, text, speed, sentence_pause):
        n = int(self.sample_rate * 0.2 * len(text.split()) / speed)
        return (0.2 * np.sin(np.arange(n) * 2 * np.pi * 150 / self.sample_rate)).astype(np.float32)


def test_synthesize_voice_timing(tmp_path):
    out = tmp_path / "voice.wav"
    timing = synthesize_voice(GOOD["beats"], out, engine=FakeEngine(), cache_dir=tmp_path / "cache", log=lambda m: None)
    audio, sr = sf.read(out)
    assert sr == 24000
    assert timing["duration"] == pytest.approx(audio.size / sr, abs=0.01)
    starts = [b["start"] for b in timing["beats"]]
    assert starts == sorted(starts) and starts[0] == pytest.approx(0.6)
    for b in timing["beats"]:
        assert b["start"] < b["end"]
        assert b["sentences"][0]["start"] == pytest.approx(b["start"])
        assert b["sentences"][-1]["end"] == pytest.approx(b["end"], abs=0.01)
    assert len(list((tmp_path / "cache").glob("*.npy"))) == 3
    # second run is served from the cache and gives identical timings
    again = synthesize_voice(GOOD["beats"], out, engine=FakeEngine(), cache_dir=tmp_path / "cache", log=lambda m: None)
    assert again == timing


def test_ambient_music_is_smooth_and_bounded():
    y = ambient_music(8.0, mood="tense", sr=16000)
    assert y.shape == (8 * 16000,)
    assert np.isfinite(y).all()
    assert np.max(np.abs(y)) == pytest.approx(0.5, abs=1e-3)
    assert np.max(np.abs(y[:800])) < 0.05  # fades in, no click at the start
    assert np.max(np.abs(np.diff(y))) < 0.05  # no clicks between chords


def _loudness(path):
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return float(err.rsplit("I:", 1)[1].split("LUFS")[0])


@needs_ffmpeg
def test_mix_hits_target_loudness(tmp_path):
    sr = 24000
    t = np.arange(sr * 8) / sr
    speech = (0.1 * np.sin(2 * np.pi * 180 * t) * (np.sin(2 * np.pi * 3 * t) > 0)).astype(np.float32)
    sf.write(tmp_path / "voice.wav", speech, sr)
    sf.write(tmp_path / "music.wav", ambient_music(9.0, sr=48000), 48000)
    info = mix(tmp_path / "voice.wav", tmp_path / "music.wav", tmp_path / "mix.wav")
    assert info["target_lufs"] == -14.0
    data, sr_out = sf.read(tmp_path / "mix.wav")
    assert sr_out == 48000 and data.shape[1] == 2
    assert _loudness(tmp_path / "mix.wav") == pytest.approx(-14.0, abs=1.5)


@needs_ffmpeg
def test_qa_flags_static_picture_and_silence(tmp_path):
    video = tmp_path / "v.mp4"
    # 8 s: a frozen frame and 3 s of silence in the middle of a tone
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x223344:s=320x180:r=30:d=8",
                    "-f", "lavfi", "-i", "sine=f=220:d=8:sample_rate=48000",
                    "-af", "volume=enable='between(t,2.5,5.5)':volume=0", "-shortest",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video)], check=True)
    timeline = {"fps": 30, "width": 320, "height": 180, "durationInFrames": 240, "format": "explainer",
                "scenes": [{"id": "b01", "template": "title", "from": 0, "durationInFrames": 120},
                           {"id": "b02", "template": "stat", "from": 120, "durationInFrames": 120}],
                "captions": [{"from": 0, "to": 15, "text": "This caption is far too long to read in half a second."}]}
    findings, info = technical_checks(video, timeline)
    checks = {f.check for f in findings}
    assert {"static_picture", "silence", "caption_speed"} <= checks
    assert "duration" not in checks and "resolution" not in checks
    silence = next(f for f in findings if f.check == "silence")
    assert silence.scene == "b01" and silence.t_start == pytest.approx(2.5, abs=0.3)
    sheets = contact_sheets(video, timeline, tmp_path / "review")
    assert len(sheets) == 1 and sheets[0].exists()


def test_cli_new_and_validate(tmp_path, capsys):
    project = tmp_path / "demo"
    assert main(["new", str(project), "--title", "Demo"]) == 0
    sb = json.loads((project / "storyboard.json").read_text())
    assert sb["title"] == "Demo" and sb["beats"]
    assert (project / "research.md").exists()
    assert main(["validate", str(project)]) == 0
    sb["beats"][0]["visual"]["template"] = "nope"
    (project / "storyboard.json").write_text(json.dumps(sb))
    assert main(["validate", str(project)]) == 1
    assert "unknown template" in capsys.readouterr().out


def test_cue_offsets_follow_the_narration():
    from content_agent.timeline import cue_offsets

    sents = [{"start": 1.0, "end": 3.0, "text": "Concorde carried about one hundred passengers."},
             {"start": 3.5, "end": 7.5, "text": "A Boeing jumbo jet carried around four hundred."}]
    frames = cue_offsets(["Concorde", "boeing", "Boeing", "not said"], sents, scene_from=15)
    assert frames[0] == 30 - 15                       # at the start of the first sentence
    assert frames[1] == round((3.5 + 4.0 * 2 / 47) * 30) - 15  # 'Boeing' is 2 characters into sentence 2
    assert frames[2] == frames[1] + 6                 # repeated cue: next item right after
    assert frames[3] is None                          # unknown phrase: template falls back to its default timing


def test_timeline_carries_cues_and_validation_checks_them():
    d = copy.deepcopy(GOOD)
    d["beats"][1]["cues"] = ["twice the speed"]
    tl = build_timeline(d, _timing(), "a.wav")
    assert tl["scenes"][1]["cues"] and tl["scenes"][0]["cues"] == []
    d["beats"][1]["cues"] = ["three times the speed"]
    assert any("does not occur" in i.message for i in _issues(d))
    d["beats"][1]["cues"] = "twice"
    assert any(i.level == "error" and "cues" in i.message for i in _issues(d))
