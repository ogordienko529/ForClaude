"""sleep_voice tests: text normalisation, parsing, pacing, rendering (fake engine), mastering."""

import shutil
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from sleep_voice.__main__ import estimate_seconds
from sleep_voice.engine import parse_voice
from sleep_voice.render import Pacing, level_match, pause_scale_at, render, speed_at, srt_time, write_chapters, write_srt
from sleep_voice.text import normalize, parse_script, split_sentences, year_words


@pytest.mark.parametrize("src,expected", [
    ("In 1888, it snowed.", "In eighteen eighty-eight, it snowed."),
    ("the 1950s diner", "the nineteen fifties diner"),
    ("the 1800s", "the eighteen hundreds"),
    ("It cost $20.", "It cost 20 dollars."),
    ("It was -40°C.", "It was minus 40 degrees Celsius."),
    ("Dr. Smith met Mr. Jones in St. Louis.", "Doctor Smith met Mister Jones in Saint Louis."),
    ("WWII ended.", "World War Two ended."),
    ("at 4 AM!", "at 4 A M."),
    ("at 4:00 PM", "at 4 o'clock P M"),
    ("9/11 changed it.", "9 11 changed it."),
    ("3.5 km away", "3.5 kilometers away"),
    ("about 20% left", "about 20 percent left"),
    ("It was REALLY quiet!!", "It was Really quiet."),
    ("Sleep well 😴", "Sleep well"),
    ("1,000,000 years", "1,000,000 years"),
    ("Apollo 11", "Apollo 11"),
])
def test_normalize(src, expected):
    assert normalize(src) == expected


def test_year_words():
    assert year_words(1905) == "nineteen oh five"
    assert year_words(1900) == "nineteen hundred"
    assert year_words(2000) == "two thousand"
    assert year_words(2010) == "twenty ten"


def test_lexicon():
    assert normalize("Meteora at dusk", {"Meteora": "Meh-teh-OR-ah"}) == "Meh-teh-OR-ah at dusk"


def test_long_sentences_split_at_commas_and_end_with_punctuation():
    s = "The keeper walked, " * 30 + "and then he slept"
    parts = split_sentences(s, max_chars=120)
    assert all(len(p) <= 125 for p in parts)
    assert all(p[-1] in ".,?;:" for p in parts)


def test_parse_script_structure():
    raw = "# Chapter One\n\nFirst sentence. Second sentence.\n\nNew paragraph. [pause 3s] After pause.\n\n# Two\nLast one."
    sc = parse_script(raw)
    kinds = [(s.kind, s.after, s.chapter) for s in sc.segments]
    assert kinds[0] == ("sentence", "chapter", "Chapter One")
    assert ("sentence", "paragraph", "Chapter One") in kinds
    assert any(s.kind == "pause" and s.seconds == 3 for s in sc.segments)
    assert sc.segments[-1].chapter == "Two"
    assert sc.word_count() > 8


def test_wind_down_curve():
    p = Pacing(speed=0.9, wind_down_speed=0.8, wind_down_start=0.2, wind_down_pause_scale=1.4)
    assert speed_at(0.0, p) == speed_at(0.2, p) == 0.9
    assert speed_at(1.0, p) == pytest.approx(0.8)
    assert 0.8 < speed_at(0.6, p) < 0.9
    assert pause_scale_at(1.0, p) == pytest.approx(1.4)


def test_level_match_evens_loudness_and_caps_gain():
    loud = np.full(24000, 0.5, dtype=np.float32)
    quiet = np.full(24000, 0.01, dtype=np.float32)
    a, b = level_match(loud, -23, 6), level_match(quiet, -23, 6)
    rms = lambda x: 20 * np.log10(np.sqrt(np.mean(x ** 2)))  # noqa: E731
    assert rms(a) == pytest.approx(-23, abs=0.1)
    assert rms(b) == pytest.approx(20 * np.log10(0.01) + 6, abs=0.1)  # gain capped at +6 dB


def test_parse_voice_blend():
    assert parse_voice("am_michael") == [("am_michael", 1.0)]
    assert parse_voice("am_michael:3,bm_george:1") == [("am_michael", 0.75), ("bm_george", 0.25)]


class FakeEngine:
    """0.25 s of tone per word; counts calls so caching can be checked."""
    sample_rate = 24000
    engine_id = "fake"
    preferred_unit = "sentence"

    def __init__(self, unit="sentence"):
        self.calls = 0
        self.preferred_unit = unit
        self.texts = []

    def synthesize(self, text, speed, sentence_pause=0.0):
        self.calls += 1
        self.texts.append(text)
        n = int(self.sample_rate * 0.25 * len(text.split()) / speed)
        return (0.2 * np.sin(np.arange(n) * 2 * np.pi * 150 / self.sample_rate)).astype(np.float32)


SCRIPT = "# Intro\n\nOne two three. Four five six.\n\n# Middle\nSeven eight nine. [pause 2s] Ten eleven twelve."


def test_render_timeline_srt_chapters_and_cache(tmp_path):
    sc = parse_script(SCRIPT)
    eng = FakeEngine()
    res = render(sc, eng, tmp_path / "a.wav", Pacing(jitter=0), cache_dir=tmp_path / "cache", log=lambda m: None)
    audio, sr = sf.read(tmp_path / "a.wav")
    assert abs(len(audio) / sr - res.duration) < 0.01
    assert len(res.cues) == len(sc.sentences) and eng.calls == len(sc.sentences)
    assert [c for _, c in res.chapters] == ["Intro", "Middle"] and res.chapters[0][0] == 0
    starts = [a for a, _, _ in res.cues]
    assert starts == sorted(starts)
    # pauses exist between sentences: next start > previous end
    assert all(res.cues[i + 1][0] - res.cues[i][1] >= 0.5 for i in range(len(res.cues) - 1))
    write_srt(res.cues, tmp_path / "a.srt")
    write_chapters(res.chapters, tmp_path / "a.chapters.txt")
    assert "-->" in (tmp_path / "a.srt").read_text()
    assert (tmp_path / "a.chapters.txt").read_text().startswith("0:00 Intro")
    # second render: everything from cache (resumable, and edits only re-synthesise changed sentences)
    eng2 = FakeEngine()
    res2 = render(sc, eng2, tmp_path / "b.wav", Pacing(jitter=0), cache_dir=tmp_path / "cache", log=lambda m: None)
    assert eng2.calls == 0 and res2.cached == len(sc.sentences)


def test_estimate_is_in_the_right_ballpark():
    sc = parse_script("Word " * 1500 + ".")
    minutes = estimate_seconds(sc, Pacing()) / 60
    assert 9 < minutes < 15   # ~1500 words at sleep pace


def test_srt_time():
    assert srt_time(3723.456) == "01:02:03,456"


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_master_hits_target_loudness_and_peak(tmp_path):
    from sleep_voice.master import Mastering, master, measure_loudness

    sc = parse_script(SCRIPT * 3)
    res = render(sc, FakeEngine(), tmp_path / "raw.wav", Pacing(jitter=0), cache_dir=None, log=lambda m: None)
    out = tmp_path / "out.mp3"
    master(res.wav_path, out, res.duration, Mastering(background="brown"))
    assert measure_loudness(out) == pytest.approx(-20, abs=1.0)


def test_paragraph_mode_speaks_whole_paragraphs(tmp_path):
    sc = parse_script(SCRIPT)
    eng = FakeEngine(unit="paragraph")
    res = render(sc, eng, tmp_path / "p.wav", Pacing(jitter=0), cache_dir=None, log=lambda m: None)
    assert "One two three. Four five six." in eng.texts      # one call for the 2-sentence paragraph
    assert eng.calls < len(sc.sentences)
    assert len(res.cues) == len(sc.sentences)                 # subtitles still per sentence
    assert all(b > a for a, b, _ in res.cues)


def _mock_http(handler):
    import httpx
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_openai_engine_request():
    import json
    import httpx
    from sleep_voice.engine import OpenAIEngine

    seen = {}

    def handler(req):
        seen["url"], seen["auth"], seen["body"] = str(req.url), req.headers["authorization"], json.loads(req.content)
        return httpx.Response(200, content=(np.ones(2400, dtype="<i2") * 1000).tobytes())

    eng = OpenAIEngine("onyx", api_key="sk-test", http=_mock_http(handler))
    audio = eng.synthesize("Hello there.", 0.8)
    assert seen["url"].endswith("/v1/audio/speech") and seen["auth"] == "Bearer sk-test"
    assert seen["body"]["model"] == "gpt-4o-mini-tts" and seen["body"]["response_format"] == "pcm"
    assert "very slowly" in seen["body"]["instructions"]
    assert audio.dtype == np.float32 and audio.size == 2400
    assert OpenAIEngine("onyx", api_key="x", http=_mock_http(handler)).engine_id == eng.engine_id  # stable cache id


def test_elevenlabs_engine_sends_context_and_retries():
    import json
    import httpx
    from sleep_voice.engine import ElevenLabsEngine

    calls = []

    def handler(req):
        calls.append(json.loads(req.content))
        if len(calls) == 1:
            return httpx.Response(429, text="slow down")
        return httpx.Response(200, content=np.zeros(100, dtype="<i2").tobytes())

    eng = ElevenLabsEngine("voice123", api_key="k", http=_mock_http(handler))
    eng.context = ("Before.", "After.")
    import time as _t
    real_sleep = _t.sleep
    _t.sleep = lambda s: None
    try:
        eng.synthesize("Middle.", 0.85)
    finally:
        _t.sleep = real_sleep
    assert len(calls) == 2
    assert calls[-1]["previous_text"] == "Before." and calls[-1]["next_text"] == "After."
    assert calls[-1]["voice_settings"]["speed"] == 0.85


def test_cloud_engines_require_keys(monkeypatch):
    from sleep_voice.engine import make_engine
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        make_engine("openai")
    with pytest.raises(ValueError):
        make_engine("elevenlabs")


def test_stretch_pauses_lengthens_sentence_gaps_only():
    import random
    from sleep_voice.render import stretch_pauses
    sr = 24000
    tone = lambda sec: (0.2 * np.sin(np.arange(int(sr * sec)) * 0.05)).astype(np.float32)  # noqa: E731
    gap = lambda sec: np.zeros(int(sr * sec), dtype=np.float32)  # noqa: E731
    audio = np.concatenate([tone(1), gap(0.15), tone(1), gap(0.4), tone(1)])  # comma-like, then sentence gap
    out = stretch_pauses(audio, sr, target=1.0, rng=random.Random(1), jitter=0)
    assert abs(out.size / sr - (audio.size / sr + 0.6)) < 0.03   # only the 0.4 s gap grew, to ~1.0 s
