"""Shorts overlays (series plaque, Telegram handle, ending comment sticker) and the `tgpost` call-to-action scene."""

import copy
import re
from pathlib import Path

import pytest

from content_agent.schema import TEMPLATES, Storyboard, validate
from content_agent.timeline import build_timeline

REMOTION = Path(__file__).resolve().parent.parent / "content_agent" / "remotion" / "src"

POST = {"title": "Промпт для чесної критики", "tag": "#зролика",
        "prompt": "Знайди три слабкі місця в моїй ідеї: [ідея]. Для кожного — чому це ризик і як перевірити."}
SB = {"title": "t", "format": "shorts", "voice_engine": "kokoro", "style": "candy", "palette": "candy",
      "countdown": True, "series": "ШІ за 30 · №8", "handle": "@shi_start_ua", "comment": "Що відповів твій чат?",
      "beats": [
          {"id": "b01", "narration": "Один два три чотири п'ять шість.",
           "visual": {"template": "kinetic", "props": {"lines": ["Один два три"]}}},
          {"id": "b02", "narration": "Промпт для чесної критики — у телеграм-каналі.", "cues": ["телеграм"],
           "visual": {"template": "tgpost", "props": POST}},
      ]}


def _issues(**top):
    d = copy.deepcopy(SB)
    d.update(top)
    for k in [k for k, v in top.items() if v is None]:
        del d[k]
    return validate(Storyboard(d))


def _post_issues(**props):
    d = copy.deepcopy(SB)
    d["beats"][1]["visual"]["props"].update(props)
    for k in [k for k, v in props.items() if v is None]:
        del d["beats"][1]["visual"]["props"][k]
    return validate(Storyboard(d))


def test_band_and_tgpost_are_valid():
    assert _issues() == []
    assert _issues(countdown=None, series=None, handle=None, comment=None) == []
    assert _post_issues(tag=None, channel="ШІ на старті") == []


def test_tgpost_is_registered_in_the_renderer():
    assert "tgpost" in TEMPLATES
    video = (REMOTION / "Video.tsx").read_text()
    assert re.search(r"\btgpost: TgPost,", video)
    assert "<TopBand" in video and "<CommentSticker" in video


@pytest.mark.parametrize("top,level,needle", [
    ({"series": "x" * 25}, "error", "series is 25 characters"),
    ({"handle": 5}, "error", "handle must be a short text"),
    ({"comment": "   "}, "error", "comment must be a short text"),
    ({"comment": "y" * 49}, "error", "at most 48"),
    ({"countdown": "yes"}, "error", "countdown must be true or false"),
    ({"format": "explainer"}, "warning", "9:16 Shorts only"),
])
def test_band_findings(top, level, needle):
    issues = _issues(**top)
    assert any(i.level == level and needle in i.message for i in issues), issues


@pytest.mark.parametrize("props,level,needle", [
    ({"prompt": None}, "error", "missing prop 'prompt'"),
    ({"prompt": " "}, "error", "prompt needs the text"),
    ({"prompt": "z" * 161}, "warning", "prompt longer than 160"),
    ({"title": "t" * 61}, "warning", "title longer than 60"),
    ({"tag": "зролика"}, "warning", "start it with «#»"),
    ({"channel": "Claude News"}, "warning", "product name"),
])
def test_tgpost_findings(props, level, needle):
    issues = _post_issues(**props)
    assert any(i.level == level and needle in i.message for i in issues), issues


def test_band_reaches_the_timeline():
    timing = {"duration": 6.0, "beats": [
        {"id": "b01", "start": 0.1, "end": 2.6, "sentences": [{"start": 0.1, "end": 2.6, "text": SB["beats"][0]["narration"]}]},
        {"id": "b02", "start": 2.8, "end": 5.6, "sentences": [{"start": 2.8, "end": 5.6, "text": SB["beats"][1]["narration"]}]}]}
    tl = build_timeline(SB, timing, "a.wav", fmt="shorts")
    assert (tl["countdown"], tl["series"], tl["handle"], tl["comment"]) == (True, "ШІ за 30 · №8", "@shi_start_ua", "Що відповів твій чат?")
    post = tl["scenes"][1]
    assert post["template"] == "tgpost" and post["props"] == POST and isinstance(post["cues"][0], int)
    bare = build_timeline({**SB, "series": " ", "handle": None, "comment": None, "countdown": False}, timing, "a.wav", fmt="shorts")
    assert not {"series", "handle", "comment", "countdown"} & set(bare)
