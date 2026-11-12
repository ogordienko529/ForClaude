"""The channel's own posts, written ahead of time as files in tg_content/posts/ and published on a schedule.

One file per post, published in file-name order (0001-hello.md, 0002-..., ...). A file starts with a short header:

    ---
    rubric: prompt
    ---
    <b>Telegram HTML</b> text of the post ...

A quiz is a Telegram quiz poll and has no text, only header fields:

    ---
    rubric: quiz
    question: ...
    options:
    - first answer
    - second answer
    correct: 2              (1 = the first option)
    explanation: shown after a wrong answer, up to 200 characters
    ---

`date: 2026-11-20` holds a post until that day (Kyiv) and then puts it before the others; two days later it counts as
stale and is skipped. `pin: yes` pins the post once it is published. A post's id is its file name, so a published file
must never be renamed.

The limits come from a study of 2,120 posts of 30 Ukrainian and Russian-language AI and IT-career channels (November
2026): the channels whose readers react most write one idea per post, mostly under 600 characters, with a title line
that tells the whole story.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from .posts import KYIV

POSTS_DIR = Path("tg_content/posts")
RUBRICS = ("intro", "prompt", "study", "career", "tool", "explain", "news", "myth", "quiz")
SLOTS = ((9, 30), (17, 15))         # Kyiv time: 19:00 was the weakest hour in the competitor study
MIN_GAP = timedelta(hours=3)        # a late run never fires two posts back to back
STALE_DAYS = 2
LOW_DAYS = 4                        # tell the owner when fewer days than this are left in the queue
TEXT_MAX = 1000                     # visible characters; the best-reacted posts have a median of ~550
MYTH_MAX = 600
PROMPT_MAX = 350                    # characters inside <pre>: one task per prompt
TITLE_MAX = 60                      # the first line; shorter first lines get more reactions
QUIZ_EVERY = 14                     # at most one quiz in any 14 posts in a row
QUESTION_MAX, OPTION_MAX, EXPLANATION_MAX = 300, 100, 200      # Telegram's poll limits

TAGS = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "a", "code", "pre", "blockquote",
        "tg-spoiler", "span"}
ENTITY = re.compile(r"&(?:amp|lt|gt|quot|#\d+|#x[0-9a-fA-F]+);")
TAG = re.compile(r"<(/?)([a-zA-Z][\w-]*)((?:\s+[\w-]+(?:=\"[^\"<>]*\")?)*)\s*>")

# Phrases that make a post read like a machine wrote it. Lower case; matched inside the visible text.
STOP_PHRASES = (
    "у сучасному світі", "в сучасному світі", "у світі, що швидко змінюється", "не секрет, що", "варто зазначити",
    "варто відзначити", "давайте розберемося", "давайте розберемо", "давайте зануримося", "зануримося в",
    "у цій статті", "в цій статті", "у цьому пості", "в цьому пості", "відіграє ключову роль", "ключову роль",
    "безмежні можливості", "неймовірні можливості", "революційн", "змінить усе", "змінить все", "підсумовуючи",
    "на завершення", "сподіваюся, це допоможе", "сподіваюсь, це допоможе", "як мовна модель", "як ші-модель",
    "чарівна паличка", "гра змінилася", "game changer", "game-changer",
)


@dataclass
class Post:
    id: str
    rubric: str = ""
    text: str = ""
    date: date | None = None
    question: str = ""
    options: list[str] = field(default_factory=list)
    correct: int | None = None          # 1-based, as written in the file
    explanation: str = ""
    pin: bool = False
    problems: list[str] = field(default_factory=list)

    @property
    def is_quiz(self) -> bool:
        return self.rubric == "quiz"

    def preview(self) -> str:
        """One line for lists and the owner's messages."""
        first = self.question if self.is_quiz else visible(self.text).strip().splitlines()[0] if self.text.strip() else ""
        return f"{self.id} [{self.rubric}] {first[:80]}"


# ---------------------------------------------------------------- reading
def parse(path: Path) -> Post:
    post = Post(id=path.stem)
    try:
        raw = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeDecodeError) as e:
        post.problems.append(f"cannot read: {e}")
        return post
    lines = raw.split("\n")
    if not lines or lines[0].strip() != "---" or "---" not in [ln.strip() for ln in lines[1:]]:
        post.problems.append("no header: the file must start with ---, the fields, then ---")
        return post
    end = 1 + [ln.strip() for ln in lines[1:]].index("---")
    key = None
    for ln in lines[1:end]:
        if not ln.strip():
            continue
        if ln.lstrip().startswith("- ") and key == "options":
            post.options.append(ln.lstrip()[2:].strip())
            continue
        k, sep, v = ln.partition(":")
        key, v = k.strip().lower(), v.strip()
        if not sep:
            post.problems.append(f"header line without a colon: {ln.strip()[:40]}")
        elif key == "rubric":
            post.rubric = v.lower()
        elif key == "date":
            try:
                post.date = date.fromisoformat(v)
            except ValueError:
                post.problems.append(f"date is not YYYY-MM-DD: {v}")
        elif key == "question":
            post.question = v
        elif key == "options":
            if v:
                post.problems.append("options go one per line below «options:», each starting with «- »")
        elif key == "correct":
            post.correct = int(v) if v.isdigit() else None
            if post.correct is None:
                post.problems.append(f"correct must be the option number: {v}")
        elif key == "explanation":
            post.explanation = v
        elif key == "pin":
            post.pin = v.lower() in ("yes", "true", "1", "так")
        else:
            post.problems.append(f"unknown header field: {key}")
    post.text = "\n".join(lines[end + 1:]).strip()
    post.problems += check(post)
    return post


def load(folder: Path = POSTS_DIR) -> list[Post]:
    return [parse(p) for p in sorted(Path(folder).glob("*.md"))]


# ---------------------------------------------------------------- checks
def visible(text: str) -> str:
    """The text as the reader sees it: tags removed, entities decoded."""
    return html.unescape(TAG.sub("", text))


def html_problems(text: str) -> list[str]:
    """Telegram rejects the whole post for one bad tag or a bare <, > or &, so check before sending."""
    out, stack, pos = [], [], 0
    for m in TAG.finditer(text):
        out += _bare(text[pos:m.start()])
        pos = m.end()
        closing, name, attrs = m[1] == "/", m[2].lower(), m[3].strip()
        if name not in TAGS:
            out.append(f"tag <{name}> is not allowed in Telegram")
            continue
        if closing:
            if not stack or stack[-1] != name:
                out.append(f"</{name}> does not close the last open tag")
            else:
                stack.pop()
            continue
        if stack and stack[-1] in ("pre", "code") and not (stack[-1] == "pre" and name == "code"):
            out.append(f"<{name}> inside <{stack[-1]}>: Telegram allows no formatting there")
        if name == "a" and not re.fullmatch(r'href="https?://[^"\s]+"', attrs):
            out.append('a link must be <a href="https://...">')
        elif name == "span" and attrs != 'class="tg-spoiler"':
            out.append('<span> is only allowed as <span class="tg-spoiler">')
        elif name in ("pre", "code") and attrs and not re.fullmatch(r'class="language-[\w+-]+"', attrs):
            out.append(f"<{name}> takes only class=\"language-...\"")
        elif name == "blockquote" and attrs not in ("", "expandable"):
            out.append("<blockquote> takes only «expandable»")
        elif name not in ("a", "span", "pre", "code", "blockquote") and attrs:
            out.append(f"<{name}> takes no attributes")
        stack.append(name)
    out += _bare(text[pos:])
    if stack:
        out.append(f"unclosed tags: {', '.join('<' + t + '>' for t in stack)}")
    return out


def _bare(chunk: str) -> list[str]:
    out = []
    if "<" in chunk or ">" in chunk:
        out.append(f"bare < or > (write &lt; &gt;) near «{chunk.strip()[:30]}»")
    if len(re.findall("&", chunk)) != len(ENTITY.findall(chunk)):
        out.append(f"bare & (write &amp;) near «{chunk.strip()[:30]}»")
    return out


# The author's «я» in the past tense has a gender in Ukrainian («я прогнав / прогнала») and says who writes the channel;
# so does «в мене теж». Prompts (<pre>) and quoted results (<blockquote>) speak for the reader or the example.
AUTHOR_HINTS = re.compile(r"(?<![\w'ʼ])я\s+(?:[а-яіїєґʼ'-]+\s+)?[а-яіїєґʼ'-]{2,}(?:в|ла)(?![\w'ʼ])"
                          r"|(?:в|у) мене теж|як і я(?![\w'ʼ])", re.I)


def author_hints(text: str) -> list[str]:
    own = re.sub(r"<(pre|blockquote)\b[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    return sorted({m[0].lower() for m in AUTHOR_HINTS.finditer(visible(own))})


def check(post: Post) -> list[str]:
    out = []
    if post.rubric not in RUBRICS:
        out.append(f"rubric must be one of {', '.join(RUBRICS)}")
    words = [post.question, post.explanation, *post.options] if post.is_quiz else [visible(post.text)]
    low = " ".join(words).lower()
    out += [f"stop phrase «{p}»: say it plainly" for p in STOP_PHRASES if p in low]
    if post.is_quiz:
        if post.text:
            out.append("a quiz has no text below the header: put everything in question/options/explanation")
        if not 1 <= len(post.question) <= QUESTION_MAX:
            out.append(f"question: 1 to {QUESTION_MAX} characters")
        if not 2 <= len(post.options) <= 10:
            out.append("options: 2 to 10")
        if any(not 1 <= len(o) <= OPTION_MAX for o in post.options):
            out.append(f"every option: 1 to {OPTION_MAX} characters")
        if len(set(post.options)) != len(post.options):
            out.append("two options are the same")
        if post.correct is None or not 1 <= post.correct <= len(post.options):
            out.append("correct: the number of the right option (1 = the first)")
        if len(post.explanation) > EXPLANATION_MAX:
            out.append(f"explanation: at most {EXPLANATION_MAX} characters ({len(post.explanation)})")
        if any(c in w for w in words for c in "<>"):
            out.append("a quiz is plain text: no tags")
        return out
    if post.question or post.options or post.correct is not None or post.explanation:
        out.append("question/options/correct/explanation are only for rubric: quiz")
    if not post.text:
        out.append("empty post")
        return out
    out += html_problems(post.text)
    out += [f"«{h}» tells who writes the channel: use the present tense («перевіряю») or no «я» at all"
            for h in author_hints(post.text)]
    n = len(visible(post.text))
    limit = MYTH_MAX if post.rubric == "myth" else TEXT_MAX
    if n > limit:
        out.append(f"too long: {n} characters, at most {limit} for {post.rubric}")
    for block in re.findall(r"<pre\b[^>]*>(.*?)</pre>", post.text, flags=re.S):
        if len(visible(block)) > PROMPT_MAX:
            out.append(f"prompt too long: {len(visible(block))} characters in <pre>, at most {PROMPT_MAX}")
    title = visible(post.text).strip().splitlines()[0].strip() if post.text.strip() else ""
    if len(title) > TITLE_MAX:
        out.append(f"title line too long: {len(title)} characters, at most {TITLE_MAX}")
    if re.match(r"\W*промпт дня\b", title, flags=re.I):
        out.append("do not open with the label «Промпт дня»: the title states the outcome and one concrete detail")
    if not re.search(r"#\w", visible(post.text)):
        out.append("end with the rubric's hashtag, e.g. #промпт")
    return out


# ---------------------------------------------------------------- the schedule
def kyiv_day(now: datetime) -> date:
    return now.astimezone(KYIV).date()


def due_slots(now: datetime) -> int:
    k = now.astimezone(KYIV)
    return sum(1 for h, m in SLOTS if (k.hour, k.minute) >= (h, m))


def ready(posts: list[Post], published: dict, today: date) -> list[Post]:
    """The posts still to go, in the order they will go: dated posts of the last days first, then the queue."""
    left = [p for p in posts if p.id not in published and not p.problems]
    dated = [p for p in left if p.date and timedelta(0) <= today - p.date <= timedelta(days=STALE_DAYS)]
    return sorted(dated, key=lambda p: p.date) + [p for p in left if not p.date]


def stale(posts: list[Post], published: dict, today: date) -> list[Post]:
    return [p for p in posts if p.id not in published and p.date and today - p.date > timedelta(days=STALE_DAYS)]


def queue_problems(posts: list[Post]) -> list[str]:
    """Checks across the queue: quizzes spaced out."""
    out, last = [], None
    for i, p in enumerate(posts):
        if p.is_quiz:
            if last is not None and i - last < QUIZ_EVERY:
                out.append(f"{p.id}: a second quiz within {QUIZ_EVERY} posts (after {posts[last].id})")
            last = i
    return out


def days_left(posts: list[Post], published: dict, today: date) -> float:
    return len([p for p in ready(posts, published, today) if not p.date]) / len(SLOTS)
