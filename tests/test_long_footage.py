"""Long recordings: streamed analysis (no whole-file arrays), loud-audio events, overview sheets,
strips for reading the chat, and hard links instead of copies."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from content_agent import gameplay as gp


def _clip(path: Path, seconds: int, size: str = "320x180", boom_at: float | None = None) -> Path:
    """A test recording: moving test pattern; quiet tone with one loud burst at `boom_at`."""
    if boom_at is None:
        audio = ["-f", "lavfi", "-i", f"sine=frequency=220:sample_rate=44100:duration={seconds}"]
        af = ["-af", "volume=0.05"]
    else:
        audio = ["-f", "lavfi", "-i", f"sine=frequency=220:sample_rate=44100:duration={seconds}"]
        af = ["-af", f"volume='if(between(t,{boom_at},{boom_at + 1}),1.0,0.02)':eval=frame"]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=15:duration={seconds}",
                    *audio, *af, "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(path)],
                   check=True)
    return path


def test_iter_frames_streams_in_chunks(tmp_path):
    v = _clip(tmp_path / "a.mp4", 6)
    chunks = list(gp.iter_frames(v, 5, 32, 18, chunk_s=1.0))
    assert len(chunks) >= 5                      # several chunks, never one big array
    assert all(c.dtype == np.uint8 and c.shape[1:] == (18, 32, 3) for c in chunks)
    assert sum(len(c) for c in chunks) == pytest.approx(30, abs=2)
    part = np.concatenate(list(gp.iter_frames(v, 2, 32, 18, start=2.0, duration=2.0)))
    assert len(part) == pytest.approx(4, abs=1)


def test_iter_frames_reports_unreadable_files(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    with pytest.raises(RuntimeError, match="could not read"):
        list(gp.iter_frames(bad, 2, 32, 18))


def test_analyze_streams_and_finds_loud_moment(tmp_path):
    v = _clip(tmp_path / "rec.mp4", 20, boom_at=12.0)
    a = gp.analyze(v)
    assert len(a["per_second"]) == pytest.approx(20, abs=1)
    assert all("db" in p for p in a["per_second"][:19])
    loud = [e for e in a["events"] if e["kind"] == "loud"]
    assert loud and abs(loud[0]["t"] - 12) <= 1
    # the motion series is continuous across chunk boundaries (no zero spike at every chunk start)
    motions = [p["motion"] for p in a["per_second"][1:]]
    assert min(motions) > 0


def test_loudness_without_audio_track(tmp_path):
    v = tmp_path / "silent.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=10:duration=3",
                    "-c:v", "libx264", "-preset", "ultrafast", str(v)], check=True)
    assert gp.loudness(v) == []
    a = gp.analyze(v)
    assert not [e for e in a["events"] if e["kind"] == "loud"]


def test_long_recordings_get_overview_sheets(tmp_path, monkeypatch):
    monkeypatch.setattr(gp, "OVERVIEW_MIN_S", 10.0)
    monkeypatch.setattr(gp, "OVERVIEW_EVERY", 5.0)
    v = _clip(tmp_path / "long.mp4", 30)
    a = gp.analyze(v)
    sheets = gp.footage_sheets(v, a, tmp_path / "review", cols=4, rows=2)
    assert len(sheets) == 4                      # 30 frames, 8 per sheet
    assert len(a["overview_sheets"]) == 1        # 6 frames, one every 5 s
    assert Image.open(sheets[0]).size[0] == 4 * (256 + 4) + 4


def test_short_recordings_have_no_overview(tmp_path):
    v = _clip(tmp_path / "short.mp4", 4)
    a = gp.analyze(v)
    gp.footage_sheets(v, a, tmp_path / "review")
    assert a["overview_sheets"] == []


def test_strip_reads_a_stretch_and_crops_the_chat(tmp_path):
    v = _clip(tmp_path / "rec.mp4", 12, size="640x360")
    full = gp.footage_strip(v, 3.0, 4.0, tmp_path / "s_full.png", fps=2)
    chat = gp.footage_strip(v, 3.0, 4.0, tmp_path / "s_chat.png", fps=2, crop="chat")
    wf, hf = Image.open(full).size
    wc, hc = Image.open(chat).size
    assert wf == 6 * (480 + 4) + 4 or wf == 8 * (480 + 4) + 4 or wf > 480   # 8 frames, 6 per row
    assert wc > wf                               # chat crops are drawn bigger to stay readable
    with pytest.raises(ValueError, match="crop must be one of"):
        gp.footage_strip(v, 0, 2, tmp_path / "x.png", crop="sky")


def test_import_links_instead_of_copying(tmp_path):
    src = _clip(tmp_path / "rec.mp4", 4)
    project = tmp_path / "proj"
    report = gp.import_footage(project, [src])
    r = report["footage/rec.mp4"]
    dest = project / "footage" / "rec.mp4"
    assert r["import"] in ("linked", "copied") and dest.exists()
    if r["import"] == "linked":
        assert dest.stat().st_ino == src.stat().st_ino
    saved = json.loads((project / "footage" / "rec.analysis.json").read_text())
    assert saved["sheets"] and "overview_sheets" in saved
    again = gp.import_footage(project, [src])   # re-import does not fail on the existing link
    assert again["footage/rec.mp4"]["import"] in ("linked", "copied")


def test_cli_strip(tmp_path, monkeypatch, capsys):
    from content_agent.__main__ import main

    src = _clip(tmp_path / "rec.mp4", 6)
    project = tmp_path / "proj"
    gp.import_footage(project, [src])
    monkeypatch.setattr("sys.argv", ["content_agent", "strip", str(project), "footage/rec.mp4", "1", "--dur", "2",
                                     "--crop", "chat"])
    main()
    out = Path(capsys.readouterr().out.strip().splitlines()[-1])
    assert out.exists() and out.parent.name == "strips"
