"""Own-voice narration: splitting a recording on pauses, matching lines to beats, assembling voice.wav."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf
import pytest

from content_agent import recording as rec
from content_agent.schema import Storyboard, validate

SR = 24_000
BEATS = [
    {"id": "b01", "narration": "Verity found my base on night three, and I had no idea it was watching.",
     "visual": {"template": "footage", "props": {"src": "footage/raw.mp4", "in": 10}}},
    {"id": "b02", "narration": "This is the mod.", "visual": {"template": "title", "props": {"title": "Verity"}}},
    {"id": "b03", "narration": "Every door I closed was open again by morning, every torch was gone, and the chat kept "
                               "saying one word: behind.", "visual": {"template": "footage", "props": {"src": "footage/raw.mp4", "in": 40}}},
    {"id": "b04", "narration": "So I built a wall of lava around the whole house.",
     "visual": {"template": "footage", "props": {"src": "footage/raw.mp4", "in": 90}}},
    {"id": "b05", "narration": "It did not help. Here is why.",
     "visual": {"template": "footage", "props": {"src": "footage/raw.mp4", "in": 120}}},
]


def _speech(seconds: float, rng: np.random.Generator) -> np.ndarray:
    """Speech-like burst: band-limited noise with a syllable envelope."""
    n = int(seconds * SR)
    x = rng.standard_normal(n).astype(np.float32)
    k = np.ones(8, np.float32) / 8
    x = np.convolve(x, k, mode="same")
    env = 0.6 + 0.4 * np.sin(np.linspace(0, seconds * 2 * np.pi * 4, n))
    return (x * env * 0.2).astype(np.float32)


def _silence(seconds: float, rng: np.random.Generator) -> np.ndarray:
    return (rng.standard_normal(int(seconds * SR)) * 0.002).astype(np.float32)   # room noise, about -54 dBFS


def _recording(lines: list[float], gap: float = 1.3, retake_of: int | None = None) -> tuple[np.ndarray, list[float]]:
    rng = np.random.default_rng(1)
    parts, durations = [_silence(0.8, rng)], []
    for i, d in enumerate(lines):
        if retake_of == i:                       # a fumbled short try, a pause, then the full line
            parts += [_speech(d * 0.35, rng), _silence(gap, rng)]
            durations.append(d * 0.35)
        parts += [_speech(d, rng), _silence(gap, rng)]
        durations.append(d)
    return np.concatenate(parts), durations


def test_segments_split_on_pauses():
    y, durs = _recording([3.0, 1.0, 4.5, 2.0, 1.6])
    segs = rec.segments(y, SR, min_gap=0.7)
    assert len(segs) == 5
    for (a, b), d in zip(segs, durs):
        assert abs((b - a) - d) < 0.35


def test_match_prefers_the_retake():
    expected = [rec.expected_seconds(b["narration"]) for b in BEATS]
    y, durs = _recording([3.0, 1.0, 4.5, 2.0, 1.6], retake_of=2)
    segs = rec.segments(y, SR)
    assert len(segs) == 6
    picks = rec.match(expected, [b - a for a, b in segs])
    assert picks == [0, 1, 3, 4, 5]            # the short fumbled take (index 2) is dropped


def test_match_needs_enough_lines():
    with pytest.raises(rec.RecordingError, match="found 2 spoken lines"):
        rec.match([2.0, 1.0, 3.0], [2.0, 1.0])


def test_assemble_recording_writes_voice_and_timing(tmp_path, monkeypatch):
    y, _ = _recording([3.0, 1.0, 4.5, 2.0, 1.6], retake_of=2)
    (tmp_path / "voice").mkdir()
    sf.write(tmp_path / "voice" / "narration.wav", y, SR)
    monkeypatch.setattr(rec, "decode", lambda path, sr=SR: sf.read(path, dtype="float32")[0])
    sb = {"voice_engine": "recording", "voice_recording": "voice/narration.wav", "beats": BEATS}
    logs: list[str] = []
    timing = rec.assemble_recording(BEATS, sb, tmp_path, tmp_path / "audio" / "voice.wav", fmt="review", log=logs.append)
    assert [t["id"] for t in timing["beats"]] == [b["id"] for b in BEATS]
    assert timing["engine"] == "recording"
    starts = [t["start"] for t in timing["beats"]]
    assert starts == sorted(starts) and all(t["end"] > t["start"] for t in timing["beats"])
    assert abs((timing["beats"][2]["end"] - timing["beats"][2]["start"]) - 4.5) < 0.4   # the full take, not 1.6 s
    assert timing["beats"][2]["source"]["start"] > timing["beats"][1]["source"]["end"]
    audio, sr = sf.read(tmp_path / "audio" / "voice.wav")
    assert sr == SR and abs(len(audio) / sr - timing["duration"]) < 0.05
    assert any("1 dropped" in m for m in logs)
    # sentences inside a beat are timed by their length and stay inside the beat
    b3 = timing["beats"][2]
    assert b3["sentences"][0]["start"] == b3["start"] and b3["sentences"][-1]["end"] == pytest.approx(b3["end"], abs=0.01)


def test_per_beat_audio_and_pinned_segments(tmp_path, monkeypatch):
    rng = np.random.default_rng(2)
    (tmp_path / "voice").mkdir()
    one = np.concatenate([_silence(0.5, rng), _speech(1.2, rng), _silence(0.5, rng)])
    sf.write(tmp_path / "voice" / "b02.wav", one, SR)
    y, _ = _recording([3.0, 4.5, 2.0, 1.6])
    sf.write(tmp_path / "voice" / "narration.wav", y, SR)
    monkeypatch.setattr(rec, "decode", lambda path, sr=SR: sf.read(path, dtype="float32")[0])
    beats = [dict(b) for b in BEATS]
    beats[1]["audio"] = "voice/b02.wav"
    segs = rec.segments(y, SR)
    sb = {"voice_recording": "voice/narration.wav", "voice_segments": [list(s) for s in segs], "beats": beats}
    timing = rec.assemble_recording(beats, sb, tmp_path, tmp_path / "audio" / "voice.wav", log=lambda m: None)
    assert timing["beats"][1]["source"]["file"] == "voice/b02.wav"
    assert abs((timing["beats"][1]["end"] - timing["beats"][1]["start"]) - 1.2) < 0.4   # leading/trailing silence trimmed
    assert timing["beats"][0]["source"]["file"] == "voice/narration.wav"


def test_missing_recording_is_a_clear_error(tmp_path):
    sb = {"voice_engine": "recording", "voice_recording": "voice/narration.m4a", "beats": BEATS}
    with pytest.raises(rec.RecordingError, match="recording not found"):
        rec.assemble_recording(BEATS, sb, tmp_path, tmp_path / "audio" / "voice.wav", log=lambda m: None)
    with pytest.raises(rec.RecordingError, match="needs \"voice_recording\""):
        rec.assemble_recording(BEATS, {"beats": BEATS}, tmp_path, tmp_path / "audio" / "voice.wav", log=lambda m: None)


def test_lines_md_lists_every_beat(tmp_path):
    out = rec.write_lines({"title": "Verity ate my base", "beats": BEATS}, tmp_path / "lines.md")
    text = out.read_text(encoding="utf-8")
    assert "# Lines to record: Verity ate my base" in text
    assert "**5.** (b05)" in text and "2 seconds" in text and "voice/narration.m4a" in text
    assert text.count("**") == 10


def test_validate_recording_engine(tmp_path):
    base = {"title": "T", "format": "review", "music": "none", "beats": BEATS, "captions": False}
    sb = Storyboard({**base, "voice_engine": "recording"})
    msgs = [i.message for i in validate(sb) if i.level == "error"]
    assert any('needs "voice_recording"' in m for m in msgs)
    path = tmp_path / "storyboard.json"
    data = {**base, "voice_engine": "recording", "voice_recording": "voice/narration.m4a", "captions": True}
    path.write_text(json.dumps(data))
    issues = validate(Storyboard(data, path))
    assert not [i for i in issues if i.level == "error"]
    warns = " ".join(i.message for i in issues if i.level == "warning")
    assert "not there yet" in warns and "captions" in warns
    (tmp_path / "voice").mkdir()
    (tmp_path / "voice" / "narration.m4a").write_bytes(b"x")
    warns = " ".join(i.message for i in validate(Storyboard(data, path)) if i.level == "warning")
    assert "not there yet" not in warns


def test_next_step_waits_for_the_recording(tmp_path):
    from content_agent.status import kind_of, next_step

    (tmp_path / "storyboard.json").write_text(json.dumps(
        {"format": "review", "voice_engine": "recording", "voice_recording": "voice/narration.m4a", "beats": BEATS}))
    assert "waiting for the creator's recording" in next_step(tmp_path, kind_of(tmp_path))
    (tmp_path / "voice").mkdir()
    (tmp_path / "voice" / "narration.m4a").write_bytes(b"x")
    assert next_step(tmp_path, kind_of(tmp_path)).startswith("validate, then run_step make")


def test_retention_warnings_on_long_form():
    from content_agent.__main__ import retention_warnings

    fps = 30
    tl = {"fps": fps, "format": "review", "durationInFrames": 150 * fps, "scenes": [
        {"id": "b01", "template": "title", "props": {}, "from": 0, "durationInFrames": 8 * fps},
        {"id": "b02", "template": "footage", "props": {"src": "f.mp4", "in": 0}, "from": 8 * fps, "durationInFrames": 30 * fps},
        {"id": "b03", "template": "footage", "props": {"src": "f.mp4", "in": 40}, "from": 38 * fps, "durationInFrames": 20 * fps},
        {"id": "b04", "template": "footage", "props": {"src": "f.mp4", "in": 70}, "from": 58 * fps, "durationInFrames": 92 * fps},
    ]}
    w = retention_warnings(tl)
    assert any("opens on a title card" in x for x in w)
    assert any("b02: one footage clip for 30s" in x for x in w)
    assert any("Re-hook every 40s" in x for x in w)
    assert retention_warnings({**tl, "format": "shorts"}) == []
