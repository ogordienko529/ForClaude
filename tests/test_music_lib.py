"""Music library: tempo, beats and drops of real tracks; Shorts follow the track's tempo and land the drop."""

import json
import shutil

import numpy as np
import pytest
import soundfile as sf

from content_agent import music_lib as ml
from content_agent.gameplay import Edit, build, render_soundtrack, validate_edit

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
SR = 44_100


def _track(path, bpm=128.0, drop=12.0, dur=26.0, first=0.3):
    """Kick on every beat (quiet before the drop), hi-hats between beats after it."""
    rng = np.random.default_rng(1)
    y = np.zeros(int(dur * SR), np.float32)
    period = 60 / bpm
    n = int(0.12 * SR)
    t = np.arange(n) / SR
    kick = np.sin(2 * np.pi * (55 + 90 * np.exp(-t * 40)) * t) * np.exp(-t * 30)
    for bt in np.arange(first, dur, period):
        i = int(bt * SR)
        y[i:i + n] += (kick * (0.25 if bt < drop else 0.9))[: len(y) - i]
        if bt >= drop:
            j, m = int((bt + period / 2) * SR), int(0.03 * SR)
            if j + m < len(y):
                y[j:j + m] += rng.standard_normal(m).astype(np.float32) * 0.15 * np.exp(-np.arange(m) / SR * 120)
    y += 0.08 * np.sin(2 * np.pi * 220 * np.arange(len(y)) / SR) * (np.arange(len(y)) / SR >= drop)
    sf.write(path, y, SR)
    return path


@needs_ffmpeg
@pytest.mark.parametrize("bpm,drop", [(95.0, 10.0), (128.0, 12.0), (174.0, 9.0)])
def test_analyze_finds_tempo_beats_and_drop(tmp_path, bpm, drop):
    a = ml.analyze(_track(tmp_path / "t.wav", bpm, drop))
    assert a["bpm"] == pytest.approx(bpm, abs=0.3)
    assert a["drops"][0] == pytest.approx(drop, abs=0.4)
    true = np.arange(0.3, 30, 60 / bpm)
    errors = [np.min(np.abs(true - b)) for b in a["beats"]]
    assert np.median(errors) < 0.05  # beats on the kick, not on the hi-hats between them


@needs_ffmpeg
def test_scan_caches_and_reads_credits(tmp_path):
    lib = tmp_path / "music"
    lib.mkdir()
    _track(lib / "song.wav")
    (lib / "notes.txt").write_text("not audio")
    (lib / "tracks.json").write_text(json.dumps({"song.wav": {"title": "Song", "artist": "Someone", "source": "Pixabay",
                                                              "license": "Pixabay Content License"}}))
    idx = ml.scan(lib)
    assert list(idx) == ["song.wav"] and idx["song.wav"]["artist"] == "Someone"
    assert ml.load(lib)["song.wav"]["bpm"] == idx["song.wav"]["bpm"]
    assert ml.credit(idx["song.wav"]) == "Music: “Song” by Someone (Pixabay, Pixabay Content License)"


def test_place_lands_a_drop_on_the_payoff():
    entry = {"beats": [0.3 + i * 0.5 for i in range(80)], "drops": [20.3], "intro_end": 4.0}
    start = ml.place(entry, drop_at=7.0)
    assert start == pytest.approx(13.3) and start in entry["beats"]
    assert ml.place(entry, drop_at=None) == pytest.approx(4.3)        # no payoff: after the intro, on a beat
    assert ml.place(entry, drop_at=30.0) == pytest.approx(4.3)        # the drop comes too early in the track
    assert ml.place(entry, drop_at=7.0, start=2.0) == 2.0             # explicit start wins


@needs_ffmpeg
def test_short_with_a_track_uses_its_tempo_and_credits_it(tmp_path):
    project = tmp_path / "proj"
    (project / "footage").mkdir(parents=True)
    lib = tmp_path / "music"
    lib.mkdir()
    _track(lib / "song.wav", bpm=100.0, drop=12.0, dur=30.0)
    ml.scan(lib)
    import subprocess

    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=320x180:r=30:d=12", "-pix_fmt", "yuv420p",
                    str(project / "footage" / "raw.mp4")], check=True)
    edit = Edit({"title": "t", "style": "plain", "music": {"track": "song.wav", "drop": "s02"},
                 "segments": [{"id": "s01", "src": "footage/raw.mp4", "in": 0, "beats": 4, "text": {"text": "hi"}},
                              {"id": "s02", "src": "footage/raw.mp4", "in": 3, "beats": 8}]}, project)
    assert edit.bpm == pytest.approx(100.0, abs=0.3)
    assert not [i for i in validate_edit(edit) if i.level == "error"]
    assert not any("generated beat" in str(i) for i in validate_edit(edit))
    tl, plan = build(edit)
    assert plan["style"] == "track" and plan["drop_at"] == pytest.approx(4 * 0.6, abs=0.05)
    # the payoff segment starts on the track's drop
    assert plan["track_start"] + plan["drop_at"] == pytest.approx(12.0, abs=0.35)
    render_soundtrack(project, plan, project / "audio" / "mix.wav")
    assert (project / "audio" / "mix.wav").exists()
    assert "Music:" in (project / "out" / "credits.txt").read_text()
    missing = Edit({**edit.data, "music": {"track": "nope.mp3"}}, project)
    assert any("not in the analysed library" in str(i) for i in validate_edit(missing))
