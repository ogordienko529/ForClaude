"""Visual styles: validation and that the chosen style and transitions reach the renderer's timeline."""

import copy
import json
import re
from pathlib import Path

import pytest

from content_agent.gameplay import CUTS, SHORT_STYLES
from content_agent.schema import STYLES, TRANSITIONS, Storyboard, validate
from content_agent.timeline import build_timeline

REMOTION = Path(__file__).resolve().parent.parent / "content_agent" / "remotion" / "src"

SB = {"title": "t", "style": "paper", "beats": [
    {"id": "b01", "narration": "A short line of narration here.", "transition": "wipe",
     "visual": {"template": "title", "props": {"title": "Hello"}}},
    {"id": "b02", "narration": "Another short line of narration.",
     "visual": {"template": "kinetic", "props": {"lines": ["Hi"]}}},
]}
TIMING = {"duration": 6.0, "beats": [
    {"id": "b01", "start": 0.4, "end": 2.5, "sentences": [{"start": 0.4, "end": 2.5, "text": "A short line."}]},
    {"id": "b02", "start": 3.0, "end": 5.0, "sentences": [{"start": 3.0, "end": 5.0, "text": "Another line."}]},
]}


def test_style_and_transition_validate_and_reach_the_timeline():
    assert [i for i in validate(Storyboard(copy.deepcopy(SB))) if i.level == "error"] == []
    tl = build_timeline(SB, TIMING, "a.wav")
    assert tl["style"] == "paper"
    assert tl["scenes"][0]["transition"] == "wipe" and "transition" not in tl["scenes"][1]


@pytest.mark.parametrize("change,needle", [
    (lambda d: d.update(style="vaporwave"), "style must be one of"),
    (lambda d: d["beats"][0].update(transition="spin"), "transition must be one of"),
])
def test_bad_style_values(change, needle):
    d = copy.deepcopy(SB)
    change(d)
    assert any(needle in i.message for i in validate(Storyboard(d)))


def test_python_and_renderer_agree_on_style_names():
    """The style names Python accepts must exist in the Remotion code, and the other way round."""
    styles_tsx = (REMOTION / "styles.tsx").read_text()
    block = styles_tsx.split("export const STYLES", 1)[1].split("};\n", 1)[0]
    renderer_styles = set(re.findall(r"^  (\w+): \{", block, re.M))
    assert renderer_styles == set(STYLES)
    kinds = re.search(r"export type TransitionKind = ([^;]+);", styles_tsx).group(1)
    assert set(re.findall(r"'(\w+)'", kinds)) == set(TRANSITIONS)
    gameplay_tsx = (REMOTION / "gameplay" / "Gameplay.tsx").read_text()
    shorts_block = gameplay_tsx.split("export const SHORT_STYLES", 1)[1].split("};\n", 1)[0]
    assert set(re.findall(r"^  (\w+): \{", shorts_block, re.M)) == set(SHORT_STYLES)
    for cut in CUTS:
        assert f"'{cut}'" in gameplay_tsx


def test_gameplay_style_and_cut_transition(tmp_path):
    import shutil
    import subprocess

    from content_agent.gameplay import Edit, build, validate_edit
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    (tmp_path / "footage").mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=320x180:r=30:d=4",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(tmp_path / "footage" / "raw.mp4")], check=True)
    edit = {"style": "pixel", "music": {"style": "none"}, "segments": [
        {"id": "s01", "src": "footage/raw.mp4", "in": 0, "dur": 1.0, "text": {"text": "Hi", "style": "hook"}},
        {"id": "s02", "src": "footage/raw.mp4", "in": 1, "dur": 1.0, "transition": "glitch"}]}
    (tmp_path / "edit.json").write_text(json.dumps(edit))
    e = Edit.load(tmp_path)
    assert [i for i in validate_edit(e) if i.level == "error"] == []
    tl, _ = build(e)
    assert tl["style"] == "pixel" and tl["clips"][1]["transition"] == "glitch" and tl["clips"][0]["transition"] is None
    edit["style"] = "sparkly"
    edit["segments"][1]["transition"] = "spin"
    (tmp_path / "edit.json").write_text(json.dumps(edit))
    msgs = [str(i) for i in validate_edit(Edit.load(tmp_path))]
    assert any("style must be one of" in m for m in msgs) and any("transition must be one of" in m for m in msgs)
