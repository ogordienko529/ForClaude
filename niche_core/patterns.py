"""Title pattern mining and keyword expansion from already-fetched data (0 quota)."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable

STOPWORDS = set(
    """a an the and or but of to in on at for with from by as is are was were be been being it its this that
    these those i you he she we they me my your his her our their them what which who whom how why when where
    not no do does did so if then than too very can will just about into over after before up down out off
    again more most some such only own same all any both each few other s t don now vs x shorts short video
    videos youtube new full part ep episode official watch""".split()
)

# Title-hook words: they describe packaging, not a topic, so they never form a sub-niche on their own.
GENERIC_WORDS = set(
    """entire complete everything full whole real really amazing facts fact inside story stories truth true
    explained explain explanation top best most biggest greatest worst ever rise fall untold hidden secret
    secrets shocking insane crazy incredible unbelievable things thing people world life day days years year
    time times minutes hours first last one two three nobody anyone everyone why happened happens found
    changed documentary documentaries history historical""".split()
)

EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9'\-]+")

PATTERNS: dict[str, re.Pattern | None] = {
    "question": re.compile(r"\?"),
    "number_or_list": re.compile(r"\b(top\s*)?\d+\b", re.I),
    "how_why_what": re.compile(r"^\s*(how|why|what|who|when|where)\b", re.I),
    "caps_word": re.compile(r"\b[A-Z]{3,}\b"),
    "emoji": EMOJI_RE,
    "hashtag": re.compile(r"#\w+"),
    "superlative": re.compile(r"\b(most|biggest|greatest|worst|best|largest|deadliest|craziest|strangest)\b", re.I),
    "explained_history": re.compile(r"\b(explained|history of|story of|entire|complete|truth)\b", re.I),
    "curiosity_gap": re.compile(r"(nobody|no one|never|secret|hidden|real reason|actually|what happened)", re.I),
    "ellipsis_or_dash": re.compile(r"(\.\.\.|…| - | — )"),
    "first_person": re.compile(r"\b(I|I'm|I've|my|we)\b"),
    "versus": re.compile(r"\b(vs\.?|versus|then vs now)\b", re.I),
}


def title_features(title: str) -> set[str]:
    return {name for name, rx in PATTERNS.items() if rx and rx.search(title)}


def title_patterns(hit_titles: list[str], other_titles: list[str], top: int = 8) -> list[dict]:
    """Share of hit titles with each pattern vs non-hit titles (lift > 1 = over-represented in hits)."""
    if not hit_titles:
        return []
    out = []
    for name in PATTERNS:
        h = sum(1 for t in hit_titles if name in title_features(t)) / len(hit_titles)
        o = sum(1 for t in other_titles if name in title_features(t)) / len(other_titles) if other_titles else None
        if h == 0:
            continue
        lift = h / o if o else None
        out.append({"pattern": name, "hit_share": round(h, 2),
                    "other_share": round(o, 2) if o is not None else None,
                    "lift": round(lift, 2) if lift is not None else None})
    out.sort(key=lambda d: (d["hit_share"] * (min(d["lift"], 3) if d["lift"] else 1)), reverse=True)
    return out[:top]


def tokens(text: str, exclude: Iterable[str] = ()) -> list[str]:
    excl = {w.lower() for w in exclude}
    return [w for w in (m.group(0).lower().strip("'-") for m in WORD_RE.finditer(text))
            if len(w) > 2 and w not in STOPWORDS and w not in excl]


def top_ngrams(titles: list[str], exclude: Iterable[str] = (), n_max: int = 3, top: int = 15) -> list[tuple[str, int]]:
    """Most frequent 1-3 word phrases; each phrase counted once per title."""
    counts: Counter[str] = Counter()
    for t in titles:
        toks = tokens(t, exclude)
        grams = set()
        for n in range(1, n_max + 1):
            for i in range(len(toks) - n + 1):
                grams.add(" ".join(toks[i : i + n]))
        counts.update(grams)
    # Prefer longer phrases when they are as frequent as their parts.
    ranked = sorted(counts.items(), key=lambda kv: (kv[1], len(kv[0].split())), reverse=True)
    return [(g, c) for g, c in ranked if c >= 2][:top]


def expand_candidates(
    videos: list[tuple[str, str, list[str], float]],
    seed: str,
    min_channels: int = 2,
    top: int = 15,
) -> list[dict]:
    """Sub-niche candidates from outlier videos.

    videos: (channel_id, title, tags, weight) tuples; weight = outlier strength.
    A phrase must appear on at least `min_channels` distinct channels, so one channel's
    repeated tag stuffing can't create a "niche".
    """
    seed_words = set(tokens(seed))
    seed_joined = "".join(seed.lower().split())
    stats: dict[str, dict] = {}

    def add(phrase: str, source: str, channel: str, title: str, weight: float) -> None:
        words = phrase.split()
        if not words or len(phrase) < 4 or all(w in seed_words or w in GENERIC_WORDS for w in words):
            return
        if phrase.replace(" ", "") in seed_joined or seed_joined in phrase.replace(" ", ""):
            return  # "historydocumentary" / "romanempire" tags = the seed itself
        if len(words) == 1 and any(words[0][:3] == sw[:3] for sw in seed_words):
            return  # inflections of a seed word: rome/romans for "roman empire"
        if words[0] in GENERIC_WORDS or words[-1] in GENERIC_WORDS:
            return  # "entire history", "rome explained": trim to the topical core instead
        st = stats.setdefault(phrase, {"sources": set(), "channels": set(), "videos": 0, "weight": 0.0, "titles": []})
        st["sources"].add(source)
        st["channels"].add(channel)
        st["videos"] += 1
        st["weight"] += weight
        if len(st["titles"]) < 3 and title not in st["titles"]:
            st["titles"].append(title)

    for channel, title, tags, weight in videos:
        seen: set[str] = set()
        toks = tokens(title, exclude=seed_words)
        for n in (1, 2, 3):
            for i in range(len(toks) - n + 1):
                g = " ".join(toks[i : i + n])
                if g not in seen:
                    seen.add(g)
                    add(g, "title", channel, title, weight)
        for tag in tags:
            t = " ".join(tokens(tag, exclude=seed_words))
            if t and t not in seen and len(t.split()) <= 5:
                seen.add(t)
                add(t, "tag", channel, title, weight)

    out = []
    for phrase, st in stats.items():
        if len(st["channels"]) < min_channels:
            continue
        # Multi-word phrases are more specific sub-niches; weight by channels and outlier strength.
        specificity = 1 + 0.5 * (len(phrase.split()) - 1)
        score = len(st["channels"]) * specificity * (1 + math.log10(1 + st["weight"]))
        query = phrase if len(phrase.split()) >= 2 else f"{seed} {phrase}"
        out.append({
            "query": query,
            "phrase": phrase,
            "sources": sorted(st["sources"]),
            "channels": len(st["channels"]),
            "videos": st["videos"],
            "score": round(score, 2),
            "example_titles": st["titles"],
        })
    out.sort(key=lambda d: d["score"], reverse=True)
    # Drop single words already covered by a stronger multi-word phrase.
    kept: list[dict] = []
    for d in out:
        if len(d["phrase"].split()) == 1 and any(d["phrase"] in k["phrase"].split() for k in kept):
            continue
        kept.append(d)
    return kept[:top]
