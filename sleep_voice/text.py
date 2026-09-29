"""Script parsing and sleep-friendly text normalisation.

Script format (plain text / markdown):
  * blank line            -> paragraph break (longer pause)
  * line starting with #  -> chapter heading (read, then a long pause)
  * [pause 5s]            -> explicit silence of that many seconds
  * everything else       -> narration

Normalisation fixes what the phonemizer reads wrong in documentary scripts (years, decades,
currency, units, abbreviations) and removes things that jolt a listener awake
(exclamation marks, SHOUTED WORDS, emoji).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------- numbers
_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen " \
        "sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def two_digits(n: int) -> str:
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return _TENS[tens] + (f"-{_ONES[ones]}" if ones else "")


def year_words(y: int) -> str:
    """1888 -> eighteen eighty-eight, 1905 -> nineteen oh five, 2000 -> two thousand,
    2010 -> twenty ten, 1900 -> nineteen hundred."""
    if 2000 <= y <= 2009:
        return "two thousand" + (f" {_ONES[y - 2000]}" if y > 2000 else "")
    hi, lo = divmod(y, 100)
    if lo == 0:
        return f"{two_digits(hi)} hundred"
    if lo < 10:
        return f"{two_digits(hi)} oh {_ONES[lo]}"
    return f"{two_digits(hi)} {two_digits(lo)}"


def _plural(words: str) -> str:
    """nineteen fifty -> nineteen fifties; eighteen hundred -> eighteen hundreds."""
    if words.endswith("y"):
        return words[:-1] + "ies"
    return words + "s"


# ---------------------------------------------------------------- rules
ABBREVIATIONS = {
    r"\bDr\.(?=\s+[A-Z])": "Doctor",
    r"\bMr\.(?=\s+[A-Z])": "Mister",
    r"\bMrs\.(?=\s+[A-Z])": "Missus",
    r"\bMs\.(?=\s+[A-Z])": "Miz",
    r"\bSt\.(?=\s+[A-Z])": "Saint",
    r"\bMt\.(?=\s+[A-Z])": "Mount",
    r"\bProf\.(?=\s+[A-Z])": "Professor",
    r"\be\.g\.,?": "for example,",
    r"\bi\.e\.,?": "that is,",
    r"\betc\.": "et cetera.",
    r"\bvs\.?(?=\s)": "versus",
    r"\bapprox\.": "approximately",
    r"\bWWII\b": "World War Two",
    r"\bWWI\b": "World War One",
    r"\bWW2\b": "World War Two",
    r"\bWW1\b": "World War One",
    r"\bU\.S\.A?\.?(?=\s|$)": "U S",
    r"\bBC\b": "B C",
    r"\bAD\b": "A D",
}

UNITS = {
    "km/h": "kilometers per hour", "mph": "miles per hour", "km": "kilometers", "cm": "centimeters",
    "mm": "millimeters", "kg": "kilograms", "lbs": "pounds", "lb": "pounds", "ft": "feet", "mi": "miles",
    "m": "meters", "g": "grams",
}

EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")


def normalize(text: str, lexicon: dict[str, str] | None = None) -> str:
    t = text
    t = EMOJI_RE.sub("", t)
    t = t.replace("…", "...").replace("—", ", ").replace("–", ", ").replace("’", "'").replace("“", '"').replace("”", '"')

    # Calm punctuation: no exclamations.
    t = re.sub(r"\?!|!\?", "?", t)
    t = re.sub(r"!+", ".", t)

    # AM/PM right after a number (before clock times turn "4:00" into "4 o'clock").
    t = re.sub(r"(?<=\d)\s*(?:AM|A\.M\.?)(?=\W|$)", " A M", t)
    t = re.sub(r"(?<=\d)\s*(?:PM|P\.M\.?)(?=\W|$)", " P M", t)

    # Clock times: 4:00 -> 4 o'clock, 4:17 -> 4 17, 4:05 -> 4 oh 5.
    t = re.sub(r"\b(\d{1,2}):00\b", r"\1 o'clock", t)
    t = re.sub(r"\b(\d{1,2}):0(\d)\b", r"\1 oh \2", t)
    t = re.sub(r"\b(\d{1,2}):(\d\d)\b", r"\1 \2", t)

    for pat, rep in ABBREVIATIONS.items():
        t = re.sub(pat, rep, t)
    # No SHOUTING (after abbreviations, so WWII etc. are already expanded).
    t = re.sub(r"\b([A-Z]{4,})\b", lambda m: m.group(1).capitalize(), t)

    # Temperatures and signed numbers.
    t = re.sub(r"(-?\d+(?:\.\d+)?)\s*°\s*C\b", lambda m: f"{_signed(m.group(1))} degrees Celsius", t)
    t = re.sub(r"(-?\d+(?:\.\d+)?)\s*°\s*F\b", lambda m: f"{_signed(m.group(1))} degrees Fahrenheit", t)
    t = re.sub(r"(\d+)\s*°", r"\1 degrees", t)

    # Currency: $20 -> 20 dollars, $3.5 million -> 3.5 million dollars.
    t = re.sub(r"\$(\d[\d,]*(?:\.\d+)?)(\s+(?:thousand|million|billion|trillion))?",
               lambda m: f"{m.group(1)}{m.group(2) or ''} dollars", t)
    t = re.sub(r"£(\d[\d,]*(?:\.\d+)?)(\s+(?:thousand|million|billion))?",
               lambda m: f"{m.group(1)}{m.group(2) or ''} pounds", t)

    # Dates like 9/11 read as "nine eleven".
    t = re.sub(r"\b(\d{1,2})/(\d{1,2})\b(?!/)", lambda m: f"{m.group(1)} {m.group(2)}", t)

    # Decades and centuries: 1950s, '50s, 1800s.
    t = re.sub(r"\b(1[0-9]|20)(\d)0s\b", lambda m: _plural(year_words(int(m.group(0)[:4]))), t)
    t = re.sub(r"'(\d)0s\b", lambda m: _plural(two_digits(int(m.group(1)) * 10)), t)

    # Years: 4-digit numbers 1100-2099 not followed by a unit or part of a bigger number.
    t = re.sub(r"(?<![\d,.$£])\b(1[1-9]\d\d|20\d\d)\b(?![\d,.]\d|\s*(?:%|percent|km|kilometers|meters|miles|feet|people|years? old))",
               lambda m: year_words(int(m.group(1))), t)

    # Units after numbers.
    for unit in sorted(UNITS, key=len, reverse=True):
        t = re.sub(rf"(\d)\s*{re.escape(unit)}\b", rf"\1 {UNITS[unit]}", t)
    t = re.sub(r"(\d)\s*%", r"\1 percent", t)

    for word, respelling in (lexicon or {}).items():
        t = re.sub(rf"\b{re.escape(word)}\b", respelling, t)

    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\s+([,.;:?])", r"\1", t)
    return t.strip()


def _signed(num: str) -> str:
    return f"minus {num[1:]}" if num.startswith("-") else num


# ---------------------------------------------------------------- parsing
@dataclass
class Segment:
    kind: str                 # "sentence" | "pause"
    text: str = ""
    seconds: float = 0.0      # for explicit pauses
    after: str = "sentence"   # what follows: sentence | paragraph | chapter
    chapter: str | None = None
    index: int = 0


@dataclass
class Script:
    segments: list[Segment] = field(default_factory=list)

    @property
    def sentences(self) -> list[Segment]:
        return [s for s in self.segments if s.kind == "sentence"]

    def word_count(self) -> int:
        return sum(len(s.text.split()) for s in self.sentences)


_SENT_SPLIT = re.compile(r"(?<=[.?;:])\s+(?=[A-Z\"'(])")
_PAUSE_TAG = re.compile(r"\[pause\s+(\d+(?:\.\d+)?)\s*s?\]", re.I)


def split_sentences(paragraph: str, max_chars: int = 280) -> list[str]:
    """Sentence split; overlong sentences are split at commas so each chunk stays natural."""
    out: list[str] = []
    for s in _SENT_SPLIT.split(paragraph):
        s = s.strip()
        if not s:
            continue
        while len(s) > max_chars:
            cut = s.rfind(", ", 0, max_chars)
            if cut < max_chars // 3:
                cut = s.rfind(" ", 0, max_chars)
            head, s = s[: cut + 1].strip(), s[cut + 1 :].strip()
            out.append(head.rstrip(",") + ",")
        if s:
            out.append(s)
    # Every chunk ends with punctuation, so the voice closes the sentence naturally.
    return [s if s[-1] in ".?,;:\"')" else s + "." for s in out]


def parse_script(raw: str, lexicon: dict[str, str] | None = None) -> Script:
    script = Script()
    chapter = None
    paragraphs = re.split(r"\n\s*\n", raw.replace("\r\n", "\n"))
    for para in paragraphs:
        lines = [ln.strip() for ln in para.strip().splitlines() if ln.strip()]
        if not lines:
            continue
        body: list[str] = []
        for ln in lines:
            if ln.startswith("#"):
                if body:
                    _add_body(script, " ".join(body), chapter, lexicon)
                    body = []
                chapter = ln.lstrip("#").strip()
                heading = normalize(chapter, lexicon)
                if heading and not heading.endswith((".", "?")):
                    heading += "."
                script.segments.append(Segment("sentence", heading, after="chapter", chapter=chapter))
            else:
                body.append(ln)
        if body:
            _add_body(script, " ".join(body), chapter, lexicon)
    for i, s in enumerate(script.segments):
        s.index = i
    return script


def _add_body(script: Script, text: str, chapter: str | None, lexicon: dict[str, str] | None) -> None:
    parts = _PAUSE_TAG.split(text)
    # parts alternates: text, seconds, text, seconds, ...
    for i, part in enumerate(parts):
        if i % 2 == 1:
            script.segments.append(Segment("pause", seconds=float(part), chapter=chapter))
            continue
        sentences = split_sentences(normalize(part, lexicon))
        for s in sentences:
            script.segments.append(Segment("sentence", s, chapter=chapter))
    # the last sentence of a paragraph gets the paragraph pause
    for seg in reversed(script.segments):
        if seg.kind == "sentence":
            if seg.after == "sentence":
                seg.after = "paragraph"
            break
