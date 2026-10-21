"""Short formats (length windows from 100k+ breakouts) and the feed-readiness checks on the rendered file."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from content_agent import gameplay as gp
from content_agent.qa import FEED, feed_checks


def _render(path: Path, video_filter: str, audio_filter: str, seconds: float) -> Path:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", video_filter, "-f", "lavfi", "-i",
                    f"sine=frequency=330:sample_rate=48000:duration={seconds}", "-af", audio_filter,
                    "-t", str(seconds), "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(path)], check=True)
    return path


def _tl(seconds: float, fmt: str | None = None, loop=None, text_at: float = 0.0) -> dict:
    return {"kind": "gameplay", "fps": 30, "durationInFrames": int(seconds * 30), "shortFormat": fmt, "loop": loop,
            "texts": [{"from": int(text_at * 30), "to": 60, "text": "can tnt kill it?"}]}


def test_calm_opening_is_flagged(tmp_path):
    # 2 s of a still grey frame, then a busy moving pattern
    v = _render(tmp_path / "calm.mp4",
                "color=c=gray:s=270x480:d=2:r=30[a];testsrc2=s=270x480:d=6:r=30[b];[a][b]concat=n=2:v=1[out]".replace(
                    "[out]", ""), "volume=0.5", 8)
    findings, feed = feed_checks(v, _tl(8, "test"))
    assert feed["opening_motion_ratio"] < FEED["opening_motion"]
    assert any(f.check == "feed_opening" and f.severity == "high" for f in findings)
    assert feed["ready"] is False


def test_busy_opening_with_sound_and_loop_passes(tmp_path):
    v = _render(tmp_path / "busy.mp4", "testsrc2=s=270x480:d=20:r=30", "volume=0.5", 20)
    findings, feed = feed_checks(v, _tl(20, "test"))
    assert feed["ready"] and feed["length_ok"] and feed["hook_text"]
    assert not [f for f in findings if f.check in ("feed_opening", "feed_sound", "feed_length")]


def test_silent_start_is_flagged(tmp_path):
    v = _render(tmp_path / "quiet.mp4", "testsrc2=s=270x480:d=8:r=30", "volume='if(lt(t,1),0,0.5)':eval=frame", 8)
    findings, feed = feed_checks(v, _tl(8, "meme"))
    assert feed["start_db"] < FEED["start_db"]
    assert any(f.check == "feed_sound" for f in findings)


def test_loop_rule_follows_the_format(tmp_path):
    v = _render(tmp_path / "noloop.mp4",
                "color=c=red:s=270x480:d=4:r=30[a];color=c=blue:s=270x480:d=4:r=30[b];[a][b]concat=n=2:v=1",
                "volume=0.5", 8)
    findings, feed = feed_checks(v, _tl(8, "meme"))
    assert feed["loop_diff"] > FEED["loop_diff"]
    assert any(f.check == "feed_loop" for f in findings)
    story, _ = feed_checks(v, _tl(8, "story"))                 # stories end on the answer, not a loop
    assert not any(f.check == "feed_loop" for f in story)
    off, _ = feed_checks(v, _tl(8, "meme", loop=False))
    assert not any(f.check == "feed_loop" for f in off)


def test_length_window_and_missing_format(tmp_path):
    v = _render(tmp_path / "long.mp4", "testsrc2=s=270x480:d=12:r=30", "volume=0.5", 12)
    findings, feed = feed_checks(v, _tl(12, "story"))           # stories run 35-60 s
    assert feed["length_ok"] is False and any(f.check == "feed_length" for f in findings)
    findings, feed = feed_checks(v, _tl(12, None))
    assert any(f.check == "feed_format" for f in findings) and feed["length_ok"] is None


# ---------------------------------------------------------------- edit.json format field
def _edit(tmp_path, data: dict) -> gp.Edit:
    p = tmp_path / "proj"
    (p / "footage").mkdir(parents=True, exist_ok=True)
    (p / "edit.json").write_text(json.dumps(data))
    return gp.Edit.load(p)


def _segs(n: int, beats: int = 4) -> list[dict]:
    return [{"id": f"s{i:02d}", "src": "footage/raw.mp4", "in": i * 5.0, "beats": beats,
             **({"text": {"text": "can tnt kill it?", "style": "hook"}} if i == 1 else {})} for i in range(1, n + 1)]


def test_format_must_be_known(tmp_path):
    e = _edit(tmp_path, {"format": "vlog", "music": {"style": "none", "bpm": 120}, "segments": _segs(3)})
    assert any(i.level == "error" and "format must be one of" in i.message for i in gp.validate_edit(e))


def test_missing_format_is_a_warning(tmp_path):
    e = _edit(tmp_path, {"music": {"style": "none", "bpm": 120}, "segments": _segs(3)})
    assert any("set \"format\"" in i.message for i in gp.retention_checks(e))


def test_length_window_by_format(tmp_path):
    # 120 bpm: 4 beats = 2 s per segment
    long_meme = _edit(tmp_path, {"format": "meme", "music": {"style": "none", "bpm": 120}, "segments": _segs(16)})
    assert any("long for a meme Short" in i.message for i in gp.retention_checks(long_meme))
    story = _edit(tmp_path, {"format": "story", "music": {"style": "none", "bpm": 120}, "segments": _segs(24)})
    msgs = " ".join(i.message for i in gp.retention_checks(story))
    assert "long for a story" not in msgs and "short for a story" not in msgs   # 48 s is inside 35-60 s
    short_story = _edit(tmp_path, {"format": "story", "music": {"style": "none", "bpm": 120}, "segments": _segs(6)})
    assert any("short for a story Short" in i.message for i in gp.retention_checks(short_story))
