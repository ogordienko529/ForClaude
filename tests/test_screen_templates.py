"""Screen-like templates for AI-tip Shorts (phone, terminal, browser, split), stickers, the progress bar,
sound effects and per-beat captions: validation, limits, timeline fields and renderer registration."""

import copy
import json
import re
from pathlib import Path

import numpy as np
import pytest

from content_agent.schema import TEMPLATES, Storyboard, sfx_on, validate
from content_agent.timeline import SFX_DIR, build_timeline, scene_marks

REMOTION = Path(__file__).resolve().parent.parent / "content_agent" / "remotion" / "src"

PHONE = {
    "prompt": "Ти рекрутер в IT. Піджени моє резюме під вакансію. Не додавай досвіду, якого немає.",
    "answer": ["Добре, вигадувати не буду.", "Де бракує фактів, поставлю [уточнити]."],
    "app_name": "ШІ-чат",
    "highlight": ["[уточнити]"],
    "focus": "Не додавай досвіду, якого немає",
    "tool_chips": ["ChatGPT", "Gemini", "Claude"],
}
TERMINAL = {
    "title": "main.py",
    "lines": [{"text": "print(scores['оцінка'])", "kind": "code"},
              {"text": "python main.py", "kind": "cmd"},
              {"text": "KeyError: 'оцінка'", "kind": "error"}],
    "explain": "Ключа «оцінка» немає у словнику.",
}
BROWSER = {"url": "library.example.org/books/kovalchuk-2019", "state": "notfound", "lines": ["Такої книжки немає."],
           "cursor": True}
SPLIT = {"title": "Промпт", "bad": {"text": "Покращ моє резюме.", "bubble": "prompt"},
         "good": {"text": "Піджени резюме під вакансію. Не вигадуй досвіду.", "label": "Так краще", "bubble": "prompt"}}
NARRATION = {
    "phone": "Головне речення: не додавай досвіду, якого немає. І він слухається.",
    "terminal": "Запускаєш код, а він падає з помилкою ключа.",
    "browser": "Відкриваєш посилання, а такої книжки немає.",
    "split": "Погано: покращ резюме. Добре: піджени під вакансію.",
}


def _sb(template: str, props: dict, **beat) -> dict:
    return {"title": "AI tip", "format": "shorts", "beats": [
        {"id": "b01", "narration": NARRATION.get(template, "A short line of narration here."),
         "visual": {"template": template, "props": copy.deepcopy(props)}, **beat}]}


def _issues(template: str, base: dict, **props):
    d = _sb(template, base)
    p = d["beats"][0]["visual"]["props"]
    p.update(props)
    for k in [k for k, v in props.items() if v is None]:
        del p[k]
    return validate(Storyboard(d))


def _has(issues, level, needle):
    return any(i.level == level and needle in i.message for i in issues)


@pytest.mark.parametrize("template,props", [("phone", PHONE), ("terminal", TERMINAL), ("browser", BROWSER), ("split", SPLIT)])
def test_valid_screen_beats_have_no_issues(template, props):
    assert _issues(template, props) == []


def test_minimal_screen_beats_are_valid():
    assert _issues("phone", {"prompt": "Explain recursion simply.", "answer": ["A function that calls itself."]}) == []
    assert _issues("terminal", {"lines": [{"text": "pip install numpy", "kind": "cmd"}, {"text": "Done", "kind": "ok"}]}) == []
    assert _issues("browser", {"url": "example.org", "title": "A page"}) == []
    assert _issues("split", {"bad": {"text": "Write my essay."}, "good": {"text": "Check my outline."}}) == []


def test_template_limits_are_documented():
    assert TEMPLATES["phone"]["limits"]["prompt"] == 160 and TEMPLATES["phone"]["limits"]["tool_chips"] == 4
    assert TEMPLATES["terminal"]["limits"] == {"lines": 12, "line": 48, "title": 40, "explain": 110}
    assert TEMPLATES["browser"]["limits"]["lines"] == 5 and TEMPLATES["split"]["limits"]["text"] == 140
    for name in ("phone", "terminal", "browser", "split"):
        assert TEMPLATES[name]["doc"]


@pytest.mark.parametrize("props,level,needle", [
    ({"prompt": None}, "error", "missing prop 'prompt'"),
    ({"answer": "one string"}, "error", "wrong type"),
    ({"prompt": "  "}, "error", "prompt is empty"),
    ({"prompt": "x" * 161}, "warning", "prompt longer than 160"),
    ({"answer": [f"Line {i}." for i in range(5)]}, "warning", "use 1-4 answer lines"),
    ({"answer": ["fine", 3]}, "error", "list of strings"),
    ({"answer": ["y" * 71]}, "warning", "answer line longer than 70"),
    ({"highlight": "tokens"}, "error", "highlight must be a list"),
    ({"highlight": ["quantum"]}, "warning", "'quantum' does not occur"),
    ({"focus": "quantum leap"}, "warning", "no punch-in"),
    ({"focus": ""}, "error", "focus must be a phrase"),
    ({"focus_cue": 3}, "error", "focus_cue must be a phrase"),
    ({"focus_cue": "never said"}, "warning", "does not occur in the narration"),
    ({"app_name": "ChatGPT"}, "warning", "product name"),
    ({"app_name": "Мій дуже довгий чат-бот для навчання"}, "warning", "app_name longer than 20"),
    ({"tool_chips": "ChatGPT"}, "error", "tool_chips must be a list"),
    ({"tool_chips": ["a", "b", "c", "d", "e"]}, "warning", "at most 4 tool_chips"),
    ({"tool_chips": ["A very long tool name"]}, "warning", "longer than 14"),
    ({"colour": "green"}, "warning", "unknown prop"),
])
def test_phone_validation_findings(props, level, needle):
    issues = _issues("phone", PHONE, **props)
    assert _has(issues, level, needle), issues


def test_focus_cue_in_the_narration_is_fine():
    assert _issues("phone", PHONE, focus_cue="і він слухається") == []


@pytest.mark.parametrize("props,level,needle", [
    ({"lines": None}, "error", "missing prop 'lines'"),
    ({"lines": ["python main.py"]}, "error", "line 0 must be"),
    ({"lines": [{"text": "x", "kind": "shell"}]}, "error", "kind must be one of"),
    ({"lines": [{"text": "x" * 49, "kind": "out"}]}, "warning", "longer than 48"),
    ({"lines": [{"text": "x", "kind": "out"}] * 13}, "warning", "use 1-12 lines"),
    ({"highlight_line": 7}, "error", "highlight_line must be a line index"),
    ({"highlight_line": True}, "error", "highlight_line must be a line index"),
    ({"lines": [{"text": "ls", "kind": "cmd"}], "explain": "Lists files."}, "warning", "explain needs a line"),
    ({"line_numbers": "yes"}, "error", "line_numbers must be true or false"),
    ({"explain": "x" * 111}, "warning", "explain longer than 110"),
])
def test_terminal_validation_findings(props, level, needle):
    issues = _issues("terminal", TERMINAL, **props)
    assert _has(issues, level, needle), issues


def test_terminal_highlight_line_points_explain_without_an_error_line():
    lines = [{"text": "git push", "kind": "cmd"}, {"text": "Everything up-to-date", "kind": "out"}]
    assert _issues("terminal", TERMINAL, lines=lines, highlight_line=1) == []


@pytest.mark.parametrize("props,level,needle", [
    ({"url": None}, "error", "missing prop 'url'"),
    ({"url": ""}, "error", "url is empty"),
    ({"url": "example.org/" + "x" * 60}, "warning", "url longer than 60"),
    ({"url": "my site.org"}, "warning", "url has spaces"),
    ({"state": "error"}, "error", "state must be one of"),
    ({"lines": "text"}, "error", "lines must be a list of strings"),
    ({"lines": ["a"] * 6}, "warning", "at most 5 lines"),
    ({"lines": ["y" * 91]}, "warning", "line longer than 90"),
    ({"state": "page", "lines": [], "title": None}, "warning", "empty page"),
    ({"cursor": "yes"}, "error", "cursor must be true or false"),
])
def test_browser_validation_findings(props, level, needle):
    issues = _issues("browser", BROWSER, **props)
    assert _has(issues, level, needle), issues


@pytest.mark.parametrize("props,level,needle", [
    ({"good": None}, "error", "missing prop 'good'"),
    ({"bad": "Покращ резюме"}, "error", "wrong type"),
    ({"bad": {"label": "Ні"}}, "error", "bad needs text"),
    ({"good": {"text": "x" * 141}}, "warning", "good text longer than 140"),
    ({"bad": {"text": "x", "bubble": "reply"}}, "error", "bubble must be one of"),
    ({"bad": {"text": "x", "label": 5}}, "error", "label must be text"),
    ({"bad": {"text": "x", "colour": "red"}}, "warning", "unknown keys"),
    ({"title": "x" * 41}, "warning", "title longer than 40"),
])
def test_split_validation_findings(props, level, needle):
    issues = _issues("split", SPLIT, **props)
    assert _has(issues, level, needle), issues


@pytest.mark.parametrize("template,props", [
    ("kinetic", {"lines": ["СТОП."]}),
    ("fact", {"text": "Досвід роботи з Jira — 2 роки"}),
    ("list", {"items": ["Тест-кейси", "SQL"]}),
])
def test_sticker_on_text_cards(template, props):
    assert _issues(template, props, sticker="🤯") == []
    assert _has(_issues(template, props, sticker="wow"), "warning", "one emoji")
    assert _has(_issues(template, props, sticker=""), "error", "sticker must be an emoji")
    assert _has(_issues(template, props, sticker=7), "error", "sticker must be an emoji")
    assert _issues(template, props, sticker="👍🏽") == []  # a skin-tone emoji is two code points


def test_storyboard_options_and_per_beat_captions():
    d = _sb("phone", PHONE, captions=False)
    d.update(progress_bar=True, sfx=False)
    assert validate(Storyboard(copy.deepcopy(d))) == []
    for key in ("progress_bar", "sfx"):
        bad = {**copy.deepcopy(d), key: "yes"}
        assert _has(validate(Storyboard(bad)), "error", f"{key} must be true or false")
    bad = copy.deepcopy(d)
    bad["beats"][0]["captions"] = "no"
    assert _has(validate(Storyboard(bad)), "error", "captions must be true or false")


def test_sfx_default_is_on_for_shorts_only():
    assert sfx_on({"format": "shorts"}) and not sfx_on({"format": "explainer"}) and not sfx_on({})
    assert sfx_on({"format": "explainer", "sfx": True}) and not sfx_on({"format": "shorts", "sfx": False})


def _timing(sb: dict) -> dict:
    beats, t = [], 0.0
    for b in sb["beats"]:
        beats.append({"id": b["id"], "start": t + 0.4, "end": t + 5.6,
                      "sentences": [{"start": t + 0.4, "end": t + 5.6, "text": b["narration"]}]})
        t += 6.0
    return {"duration": t, "beats": beats}


def test_timeline_gets_progress_bar_sfx_marks_and_skips_captions():
    sb = _sb("phone", PHONE, captions=False)
    sb["beats"].append({"id": "b02", "narration": "Then the terminal shows the error.",
                        "visual": {"template": "terminal", "props": TERMINAL}})
    sb["progress_bar"] = True
    tl = build_timeline(sb, _timing(sb), "a.wav", fmt="shorts")
    assert tl["progressBar"] is True and tl["sfx"] == SFX_DIR
    phone = tl["scenes"][0]
    # the focus phrase is spoken in the narration: the punch-in is timed to it
    assert phone["props"] == PHONE and 0 < phone["marks"]["focus"] < phone["durationInFrames"]
    assert "marks" not in tl["scenes"][1]
    assert tl["captions"] and all(c["from"] >= tl["scenes"][1]["from"] for c in tl["captions"])  # b01 has none
    long = build_timeline({**sb, "format": "explainer"}, _timing(sb), "a.wav", fmt="explainer")
    assert "sfx" not in long and build_timeline({**sb, "progress_bar": False}, _timing(sb), "a.wav")["progressBar"] is False


def test_focus_cue_wins_over_the_focus_phrase():
    sentences = [{"start": 0.0, "end": 4.0, "text": "First the prompt, then the key line arrives at the end."}]
    early = scene_marks({"focus": "the prompt"}, sentences, 0)["focus"]
    late = scene_marks({"focus": "the prompt", "focus_cue": "at the end"}, sentences, 0)["focus"]
    assert early < late
    assert scene_marks({"focus": "not spoken"}, sentences, 0) == {}
    assert scene_marks({"focus": [0.4, 0.5]}, sentences, 0) == {}  # footage's focus is a point, not a phrase


def test_sfx_bank_is_written(tmp_path):
    import soundfile as sf

    from content_agent.sound import SFX_BANK, SFX_NAMES, write_sfx_bank

    assert set(SFX_BANK) <= set(SFX_NAMES)
    paths = write_sfx_bank(tmp_path / SFX_DIR)
    assert sorted(p.stem for p in paths) == sorted(SFX_BANK)
    for p in paths:
        y, sr = sf.read(p)
        assert sr == 48_000 and np.isfinite(y).all() and 0 < np.max(np.abs(y)) <= 1.0
    keys, _ = sf.read(tmp_path / SFX_DIR / "keys.wav")
    assert len(keys) >= 48_000  # a recorded typing run (assets/sfx), looped under any typing animation


def test_renderer_sfx_names_match_the_bank():
    from content_agent.sound import SFX_BANK

    motion = (REMOTION / "motion.tsx").read_text()
    names = set(re.findall(r"'(\w+)'", re.search(r"export type SfxName = ([^;]+);", motion).group(1)))
    assert names == set(SFX_BANK)
    used = set()
    for f in [*REMOTION.glob("*.tsx"), *(REMOTION / "templates").glob("*.tsx")]:
        used |= set(re.findall(r'<Sfx[^>]*name="(\w+)"', f.read_text()))
    assert used and used <= set(SFX_BANK)


def test_new_templates_are_in_the_renderer():
    for name in ("phone", "terminal", "browser", "split"):
        assert (REMOTION / "templates" / f"{name}.tsx").exists()
    video = (REMOTION / "Video.tsx").read_text()
    assert "<ProgressBar" in video and "SfxContext.Provider" in video and "intro={i > 0}" in video
    text = (REMOTION / "templates" / "text.tsx").read_text()
    assert text.count("<Sticker") == 3  # kinetic, fact, list


def test_build_writes_the_sfx_bank_and_mix_leaves_headroom(tmp_path, monkeypatch):
    from content_agent.__main__ import main

    project = tmp_path / "tip"
    (project / "audio").mkdir(parents=True)
    sb = _sb("phone", PHONE)
    (project / "storyboard.json").write_text(json.dumps(sb, ensure_ascii=False))
    (project / "audio" / "voice_timing.json").write_text(json.dumps(_timing(sb), ensure_ascii=False))
    assert main(["build", str(project)]) in (0, None)
    tl = json.loads((project / "timeline.json").read_text())
    assert tl["sfx"] == SFX_DIR and (project / SFX_DIR / "keys.wav").exists()

    seen = {}

    def fake_mix(voice, music, out, fmt="explainer", music_db=-19.0, true_peak=-1.5):
        seen["true_peak"] = true_peak
        return {"target_lufs": -14.0, "input_lufs": -20.0}

    monkeypatch.setattr("content_agent.audio.mix", fake_mix)
    main(["mix", str(project)])
    assert seen["true_peak"] == -3.0  # the renderer's sound effects go on top of this mix
    sb["sfx"] = False
    (project / "storyboard.json").write_text(json.dumps(sb, ensure_ascii=False))
    main(["mix", str(project)])
    assert seen["true_peak"] == -1.5


def test_missing_renderer_packages_are_detected(tmp_path, monkeypatch):
    from content_agent import render

    (tmp_path / "node_modules" / "remotion").mkdir(parents=True)
    (tmp_path / "node_modules" / "remotion" / "package.json").write_text("{}")
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"remotion": "1", "@fontsource/jetbrains-mono": "5"}}))
    monkeypatch.setattr(render, "REMOTION_DIR", tmp_path)
    assert render.missing_node_modules() == ["@fontsource/jetbrains-mono"]
