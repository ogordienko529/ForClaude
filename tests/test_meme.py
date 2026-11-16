"""The `meme` scene: a real meme picture or video fragment with meme text boxes, and its punchline sounds."""

import copy
import re
from pathlib import Path

import numpy as np
import pytest

from content_agent.schema import TEMPLATES, Storyboard, validate
from content_agent.sound import SFX_BANK, SR, sfx

REMOTION = Path(__file__).resolve().parent.parent / "content_agent" / "remotion" / "src"

MEME = {"src": "memes/drake.png", "size": [892, 698], "sfx": "ding", "texts": [
    {"text": "Дай джерела", "x": 0.53, "y": 0.05, "w": 0.44, "h": 0.4, "font": "thin", "style": "none"},
    {"text": "Дай джерела з посиланнями й точною цитатою", "x": 0.53, "y": 0.55, "w": 0.44, "h": 0.4,
     "font": "thin", "style": "none", "cue": 1},
]}
SB = {"title": "t", "format": "shorts", "voice_engine": "kokoro", "style": "comic",
      "beats": [
          {"id": "b01", "narration": "Тому проси так: дай джерела з посиланнями.", "captions": False,
           "cues": ["проси так", "посиланнями"], "visual": {"template": "meme", "props": MEME}},
          {"id": "b02", "narration": "Назва, автор, рік — усе як справжнє.", "captions": False,
           "visual": {"template": "meme", "props": {"src": "memes/buzz.mp4", "size": [728, 420], "texts": [
               {"text": "Вигадані джерела", "x": 0, "y": 0, "w": 1, "h": 0.2}]}}},
          {"id": "b03", "narration": "А ти здаєш курсову і думаєш, що все нормально.", "captions": False,
           "visual": {"template": "meme", "props": {"src": "memes/fine.mp4", "size": [500, 484], "sfx": "sad",
                                                    "fit": "band", "texts": [
               {"text": "Все нормально", "x": 0, "y": 0.8, "w": 1, "h": 0.2}]}}},
      ]}


def _issues(**props):
    d = copy.deepcopy(SB)
    d["beats"][0]["visual"]["props"].update(props)
    for k in [k for k, v in props.items() if v is None]:
        del d["beats"][0]["visual"]["props"][k]
    return validate(Storyboard(d))


def test_memes_are_valid_and_may_run_in_a_row():
    assert _issues() == []


def test_meme_is_registered_in_the_renderer():
    assert "meme" in TEMPLATES
    assert re.search(r"\bmeme: Meme,", (REMOTION / "Video.tsx").read_text())
    motion = (REMOTION / "motion.tsx").read_text()
    assert "'boom'" in motion and "'sad'" in motion


@pytest.mark.parametrize("props,needle", [
    ({"src": "memes/drake.gif"}, "src must be a picture"),
    ({"size": [892]}, "size must be [width, height]"),
    ({"texts": []}, "texts must be 1-4"),
    ({"texts": [{"text": "x", "x": 1.2, "y": 0, "w": 0.5, "h": 0.2}]}, "fractions of the media"),
    ({"texts": [{"text": "  "}]}, "needs a text"),
    ({"texts": [{"text": "x", "font": "bold"}]}, "font must be thick or thin"),
    ({"sfx": "airhorn"}, "sfx must be boom, sad, ding, buzz or pop"),
    ({"fit": "full"}, "fit must be band or tall"),
])
def test_meme_findings(props, needle):
    found = [i for i in _issues(**props) if i.level == "error"]
    assert any(needle in i.message for i in found), [i.message for i in found]


def test_meme_sounds_are_in_the_bank():
    assert {"boom", "sad"} <= set(SFX_BANK)
    sad = sfx("sad")
    assert 1.5 < len(sad) / SR < 2.3
    assert 0.3 < float(np.max(np.abs(sad))) <= 1.0
