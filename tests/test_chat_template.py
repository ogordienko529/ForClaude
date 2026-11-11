"""The `chat` template (messenger-style AI chat for AI-tip Shorts): prop validation, limits, renderer registration."""

import copy
import re
from pathlib import Path

import pytest

from content_agent.schema import TEMPLATES, Storyboard, validate
from content_agent.timeline import build_timeline

REMOTION = Path(__file__).resolve().parent.parent / "content_agent" / "remotion" / "src"

PROPS = {
    "title": "Промпт",
    "prompt": "Explain how a transformer reads a sentence, in three short steps.",
    "answer": ["1. It splits the text into tokens.", "2. Every token looks at the others.", "3. It predicts the next one."],
    "highlight": ["three short steps", "tokens"],
}
SB = {"title": "AI tip", "format": "shorts", "beats": [
    {"id": "b01", "narration": "Ask it for steps, and it splits the text, compares the tokens, then predicts.",
     "cues": ["splits", "compares", "predicts"],
     "visual": {"template": "chat", "props": PROPS}},
]}


def _issues(**props):
    d = copy.deepcopy(SB)
    d["beats"][0]["visual"]["props"].update(props)
    for k in [k for k, v in props.items() if v is None]:
        del d["beats"][0]["visual"]["props"][k]
    return validate(Storyboard(d))


def test_valid_chat_beat_has_no_issues():
    assert _issues() == []
    assert _issues(title=None, highlight=None, answer=["Just one line."]) == []
    assert TEMPLATES["chat"]["limits"] == {"prompt": 280, "answer": 6, "answer_line": 90, "title": 30, "highlight": 6}


@pytest.mark.parametrize("props,level,needle", [
    ({"prompt": None}, "error", "missing prop 'prompt'"),
    ({"answer": None}, "error", "missing prop 'answer'"),
    ({"answer": "one long string"}, "error", "wrong type"),
    ({"prompt": "   "}, "error", "prompt is empty"),
    ({"answer": ["fine", {"text": "no"}]}, "error", "list of strings"),
    ({"highlight": "tokens"}, "error", "highlight must be a list"),
    ({"highlight": ["tokens", 3]}, "error", "highlight must be a list"),
    ({"prompt": "x" * 281}, "warning", "prompt longer than 280"),
    ({"answer": [f"Line {i}." for i in range(7)]}, "warning", "use 1-6 answer lines"),
    ({"answer": []}, "warning", "use 1-6 answer lines"),
    ({"answer": ["y" * 91]}, "warning", "answer line longer than 90"),
    ({"title": "A header label that is far too long"}, "warning", "title longer than 30"),
    ({"highlight": ["quantum"]}, "warning", "'quantum' does not occur"),
    ({"highlight": ["a", "b", "c", "d", "e", "f", "g"]}, "warning", "at most 6 highlights"),
    ({"colour": "green"}, "warning", "unknown prop"),
])
def test_chat_validation_findings(props, level, needle):
    issues = _issues(**props)
    assert any(i.level == level and needle in i.message for i in issues), issues


def test_highlight_matches_answer_and_ignores_case():
    assert _issues(highlight=["THREE SHORT", "Predicts the next"]) == []


def test_chat_props_and_cues_reach_the_timeline():
    timing = {"duration": 8.0, "beats": [
        {"id": "b01", "start": 0.4, "end": 7.5, "sentences": [
            {"start": 0.4, "end": 7.5, "text": SB["beats"][0]["narration"]}]}]}
    tl = build_timeline(SB, timing, "a.wav", fmt="shorts")
    scene = tl["scenes"][0]
    assert scene["template"] == "chat" and scene["props"] == PROPS
    assert (tl["width"], tl["height"]) == (1080, 1920)
    assert len(scene["cues"]) == 3 and scene["cues"] == sorted(scene["cues"])  # answer line i appears on cue i


def test_python_and_renderer_agree_on_template_names():
    """Every template the validator accepts has a component in the renderer's switch, and the other way round."""
    video = (REMOTION / "Video.tsx").read_text()
    block = video.split("export const TEMPLATES", 1)[1].split("};", 1)[0]
    assert set(re.findall(r"^  (\w+): \w+,", block, re.M)) == set(TEMPLATES)
    assert (REMOTION / "templates" / "chat.tsx").exists()
