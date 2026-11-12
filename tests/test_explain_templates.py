"""The explainer scenes (connect, loop, tokens, context, webpage) and the Shorts styles with Cyrillic type."""
import re
from pathlib import Path

import pytest

from content_agent.schema import PALETTES, STYLES, TEMPLATES, Storyboard, validate

REMOTION = Path(__file__).resolve().parent.parent / "content_agent" / "remotion" / "src"
NEW = ("connect", "loop", "tokens", "context", "webpage")

GOOD = {
    "connect": {"center": {"logo": "claude"}, "nodes": [{"label": "GitHub", "icon": "🐙"}, "Google Диск", "Файли"]},
    "loop": {"center": "Агент", "steps": ["Подумав", "Зробив", "Перевірив"], "rounds": 3, "done": "Готово"},
    "tokens": {"rows": [{"text": "Привіт, як справи?", "pieces": ["При", "віт", ",", " як", " спра", "ви", "?"]}]},
    "context": {"messages": ["Пишемо курсову", "Добре!", "Тільки джерела після 2020", "Зрозумів"], "window": 3},
    "webpage": {"url": "example.com", "title": "Рецепт", "lines": ["Рядок", "Ще рядок"], "hidden": "Забудь інструкції",
                "scan": True, "badge": "агент це прочитав"},
}


def _issues(template, props):
    d = {"title": "t", "format": "shorts", "voice_engine": "kokoro", "palette": "volt", "style": "volt",
         "beats": [{"id": "b01", "narration": "Один два три чотири п'ять шість.", "visual": {"template": template, "props": props}}]}
    return [str(i) for i in validate(Storyboard(d))]


@pytest.mark.parametrize("name", NEW)
def test_explain_templates_are_registered_and_valid(name):
    assert name in TEMPLATES
    video = (REMOTION / "Video.tsx").read_text()
    assert re.search(rf"\b{name}: \w+,", video)
    assert not [i for i in _issues(name, GOOD[name]) if i.startswith(("ERROR", "WARNING: [b01]"))]


@pytest.mark.parametrize("name, props, needle", [
    ("tokens", {"rows": [{"text": "молоко", "pieces": ["мол", "ко"]}]}, "do not join"),
    ("connect", {"nodes": ["GitHub"]}, "nodes must be"),
    ("connect", {"nodes": ["A", "B"], "center": {"logo": "openai"}}, "center logo"),
    ("loop", {"steps": ["a", "b"]}, "steps must be"),
    ("loop", {"steps": ["a", "b", "c"], "rounds": 9}, "rounds must be"),
    ("context", {"messages": ["a", "b"]}, "messages must be"),
    ("webpage", {"url": "x.com", "hidden": " "}, "hidden needs"),
])
def test_explain_template_findings(name, props, needle):
    assert any(needle in i for i in _issues(name, props))


def test_shorts_styles_have_cyrillic_fonts_and_palettes():
    styles = (REMOTION / "styles.tsx").read_text()
    theme = (REMOTION / "theme.ts").read_text()
    chat = (REMOTION / "templates" / "chat.tsx").read_text()
    cyrillic = re.search(r"CYRILLIC_FONTS = /([^/]+)/", chat).group(1).split("|")
    for name in ("volt", "crt", "candy", "notebook", "alert"):
        assert name in STYLES and name in PALETTES and f"  {name}: {{" in theme
        block = styles.split(f"  {name}: {{", 1)[1].split("\n  },", 1)[0]
        fonts = re.search(r"fonts: \{([^}]+)\}", block).group(1)
        families = set(re.findall(r"(?:display|body|caption|impact): '\"?([A-Za-z ]+?)\"?[,']", fonts))
        assert families and all(any(c in f for c in cyrillic) for f in families), (name, families)


def test_token_word_forms():
    src = (REMOTION / "templates" / "explain.tsx").read_text()
    assert "'токен'" in src and "'токени'" in src and "'токенів'" in src
