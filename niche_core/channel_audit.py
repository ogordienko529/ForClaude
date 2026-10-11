"""Audit a channel from its public data: what it posted, what worked, who watches, what viewers complain about.

Costs about 1 + 2x(videos/50) + comment_videos quota units (≈20 for 100 videos and 15 comment threads).
The report is meant for a creator (and the content agent) deciding what to make next, so it compares
the channel with itself: top vs bottom quarter, month by month, and the comments' recurring themes.
"""

from __future__ import annotations

import math
import re
import statistics as st
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from .durations import parse_iso8601_duration

CHANNEL_ID = re.compile(r"(UC[0-9A-Za-z_-]{22})")
HANDLE = re.compile(r"@([0-9A-Za-z._-]{3,30})")
FRESH_DAYS = 3  # newer uploads have not had their run yet: listed, not compared
STOP = set("""a an the and or of in on to for with at by from is are was were be it its this that these those i me my
we our you your he she they them his her their what why how who when where which not no yes so too very just
vs new now all every get got can will about after before into out up down over than then there here do does did
has have had more most one two shorts short roblox minecraft video game update""".split())
THEMES = {
    "ai": r"\bai\b|a\.i\.|artificial|robot voice|tts|text to speech|generated",
    "music_sound": r"\bmusic\b|\bsong\b|\bsound|\baudio\b|\bbeat\b",
    "clickbait": r"click ?bait|\bfake\b|\blie\b|\bliar\b|\blair\b|misinformation|not true|\bcap\b|wrong",
    "question": r"\?|\bhow (do|can|to)\b|\bwhere\b|\bwhich\b|\bwhen\b",
    "request": r"\bpart 2\b|\bmake (a|more|another)\b|\bplease\b|\bpls\b|\bnext\b|full version|\bmore\b",
    "praise": r"\bnice\b|\bcool\b|\bgood\b|\bgreat\b|\blove\b|\bbest\b|\bfunny\b|\bw\b|🔥|😂|🤣",
}
TITLE_FEATURES = {
    "how to / guide / tips": r"\bhow to\b|\bguide\b|\btips?\b|\bunlock\b|\bget\b.*\bfast\b",
    "question": r"\?",
    "number": r"\d",
    "update / new / added": r"\bupdate\b|\bnew\b|\badded\b",
    "emoji": r"[\U0001F300-\U0001FAFF☀-➿]",
    "ALL-CAPS word": r"\b[A-Z]{4,}\b",
    "I / my": r"\bI\b|\bmy\b",
    "hashtag": r"#\w",
    "secret / truth / lore": r"\bsecret|\btruth\b|\blore\b|\breally\b|\bnot who\b|\bhidden\b",
}


def parse_channel(text: str) -> tuple[str | None, str | None]:
    """(channel_id, handle) from an ID, @handle or any youtube/studio URL."""
    m = CHANNEL_ID.search(text)
    if m:
        return m.group(1), None
    m = HANDLE.search(text)
    if m:
        return None, "@" + m.group(1)
    t = text.strip()
    if re.fullmatch(r"[0-9A-Za-z._-]{3,30}", t):
        return None, "@" + t
    raise ValueError(f"not a channel id, @handle or channel URL: {text!r}")


def estimate(max_videos: int, comment_videos: int) -> int:
    pages = math.ceil(max_videos / 50)
    return 1 + pages + pages + comment_videos


def _age_days(published: str, now: datetime) -> float:
    t = datetime.fromisoformat(published.replace("Z", "+00:00"))
    return max((now - t).total_seconds() / 86400, 0.0)


def _video(item: dict, now: datetime) -> dict:
    s, stt = item["snippet"], item.get("statistics", {})
    dur = parse_iso8601_duration(item.get("contentDetails", {}).get("duration")) or 0
    return {"id": item["id"], "title": s.get("title", ""), "published_at": s.get("publishedAt", ""),
            "month": s.get("publishedAt", "")[:7], "duration_s": dur, "short": 0 < dur <= 180,
            "views": int(stt.get("viewCount", 0)), "likes": int(stt.get("likeCount", 0)),
            "comments": int(stt.get("commentCount", 0)), "description": s.get("description", ""),
            "tags": s.get("tags", []), "age_days": round(_age_days(s["publishedAt"], now), 1),
            "url": f"https://www.youtube.com/watch?v={item['id']}"}


def _per_1k(xs: list[dict], key: str) -> float:
    views = sum(v["views"] for v in xs)
    return round(1000 * sum(v[key] for v in xs) / views, 2) if views else 0.0


def _keywords(titles: list[str], n: int = 4) -> list[str]:
    c: Counter = Counter()
    for t in titles:
        words = {w for w in re.findall(r"[a-z][a-z']{2,}", t.lower()) if w not in STOP}
        c.update(words)
    return [w for w, k in c.most_common(n) if k >= 2]


def _feature_table(ranked: list[dict]) -> list[dict]:
    q = max(1, len(ranked) // 4)
    top, bottom = ranked[:q], ranked[-q:]
    rows = []
    for name, pat in TITLE_FEATURES.items():
        flags = re.I if name not in ("ALL-CAPS word", "I / my") else 0
        t = sum(bool(re.search(pat, v["title"], flags)) for v in top)
        b = sum(bool(re.search(pat, v["title"], flags)) for v in bottom)
        rows.append({"feature": name, "top": t, "bottom": b, "n": q})
    return rows


def _length_buckets(xs: list[dict]) -> list[dict]:
    out = []
    for lo, hi in ((0, 15), (15, 25), (25, 40), (40, 61), (61, 181)):
        b = [v["views"] for v in xs if v["short"] and lo <= v["duration_s"] < hi]
        if b:
            out.append({"range": f"{lo}-{hi - 1}s", "n": len(b), "median_views": int(st.median(b))})
    return out


def _themes(comments: list[dict]) -> dict[str, list[dict]]:
    out = {}
    for name, pat in THEMES.items():
        hits = [c for c in comments if re.search(pat, c["text"], re.I)]
        out[name] = sorted(hits, key=lambda c: -c["likes"])
    return out


def run(client, channel: str, max_videos: int = 100, comment_videos: int = 15,
        now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    cid, handle = parse_channel(channel)
    ch = client.channel_details(channel_id=cid, handle=handle)
    if not ch:
        raise ValueError(f"channel not found: {channel}")
    cid = ch["id"]
    uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    ids = client.playlist_video_ids(uploads, max_videos)
    videos = sorted((_video(i, now) for i in client.list_videos_full(ids)), key=lambda v: v["published_at"], reverse=True)
    settled = [v for v in videos if v["age_days"] >= FRESH_DAYS]
    fresh = [v for v in videos if v["age_days"] < FRESH_DAYS]
    ranked = sorted(settled, key=lambda v: -v["views"])

    # comments: the most watched videos (what the audience is) and the newest (how new work lands)
    picks = list(dict.fromkeys([v["id"] for v in ranked[: max(1, comment_videos // 2)]] +
                               [v["id"] for v in videos[:comment_videos]]))[:comment_videos]
    by_id = {v["id"]: v for v in videos}
    comments = []
    for vid in picks:
        for c in client.comment_threads(vid):
            if c["author_channel"] == cid:  # the creator's own replies
                continue
            comments.append({**c, "video": by_id[vid]["title"], "video_id": vid})

    months = []
    for m in sorted({v["month"] for v in videos}, reverse=True):
        xs = [v for v in videos if v["month"] == m]
        sx = [v for v in xs if v["age_days"] >= FRESH_DAYS]
        months.append({"month": m, "uploads": len(xs), "median_views": int(st.median([v["views"] for v in sx])) if sx else None,
                       "likes_per_1k": _per_1k(xs, "likes"), "comments_per_1k": _per_1k(xs, "comments"),
                       "keywords": _keywords([v["title"] for v in xs])})
    words = Counter(w for c in comments for w in re.findall(r"[a-z][a-z']{2,}", c["text"].lower()) if w not in STOP)
    music_credits = Counter()
    for v in videos:
        d = v["description"].lower()
        if "music" in d:
            music_credits["generated" if "generated" in d else "credited track" if re.search(r"music[^\n]*(by|pixabay|\")", d)
                          else "mentioned"] += 1
    return {
        "channel": {"id": cid, "title": ch["snippet"]["title"], "handle": ch["snippet"].get("customUrl"),
                    "subscribers": int(ch.get("statistics", {}).get("subscriberCount", 0)),
                    "videos": int(ch.get("statistics", {}).get("videoCount", 0)),
                    "views": int(ch.get("statistics", {}).get("viewCount", 0)),
                    "created": ch["snippet"].get("publishedAt", "")[:10]},
        "analysed": {"videos": len(videos), "settled": len(settled), "fresh": len(fresh), "comments": len(comments)},
        "months": months,
        "top": ranked[:10], "bottom": ranked[-10:][::-1] if len(ranked) > 10 else [],
        "fresh": fresh,
        "title_features": _feature_table(ranked) if len(ranked) >= 8 else [],
        "length_buckets": _length_buckets(settled),
        "comment_themes": _themes(comments),
        "audience_words": words.most_common(20),
        "music_in_descriptions": dict(music_credits),
        "comments": comments,
    }


def _n(x: float) -> str:
    return f"{x / 1e6:.1f}M" if x >= 1e6 else f"{x / 1e3:.1f}k" if x >= 1e4 else f"{x:,.0f}"


def to_markdown(r: dict) -> str:
    c = r["channel"]
    a = r["analysed"]
    L = [f"# Channel audit: {c['title']} ({c['handle'] or c['id']})", "",
         f"{_n(c['subscribers'])} subscribers · {c['videos']} videos · {_n(c['views'])} views · created {c['created']}. "
         f"Analysed the last {a['videos']} uploads ({a['fresh']} younger than {FRESH_DAYS} days are listed but not "
         f"compared) and {a['comments']} viewer comments.", "",
         "## Month by month", "",
         "| Month | Uploads | Median views | Likes / 1k views | Comments / 1k | Title keywords |", "|---|---|---|---|---|---|"]
    for m in r["months"]:
        mv = _n(m["median_views"]) if m["median_views"] is not None else "too fresh"
        L.append(f"| {m['month']} | {m['uploads']} | {mv} | {m['likes_per_1k']} | {m['comments_per_1k']} | "
                 f"{', '.join(m['keywords'])} |")
    L += ["", "Likes and comments per 1k views do not depend on a video's age: they show how much the people "
              "YouTube showed it to cared.", "", "## What worked: top 10", ""]
    for v in r["top"]:
        L.append(f"- {_n(v['views'])} · {v['duration_s']}s · {v['published_at'][:10]} · {v['title']}")
    if r["bottom"]:
        L += ["", "## What did not: bottom 10", ""]
        for v in r["bottom"]:
            L.append(f"- {_n(v['views'])} · {v['duration_s']}s · {v['published_at'][:10]} · {v['title']}")
    if r["fresh"]:
        L += ["", f"## Too fresh to judge (< {FRESH_DAYS} days)", ""]
        for v in r["fresh"]:
            L.append(f"- {_n(v['views'])} after {v['age_days']} d · {v['duration_s']}s · {v['title']}")
    if r["title_features"]:
        n = r["title_features"][0]["n"]
        L += ["", f"## Titles: top quarter vs bottom quarter ({n} videos each)", "", "| Feature | Top | Bottom |", "|---|---|---|"]
        for f in r["title_features"]:
            mark = " ←" if f["top"] >= f["bottom"] + max(2, n // 5) else (" ✗" if f["bottom"] >= f["top"] + max(2, n // 5) else "")
            L.append(f"| {f['feature']} | {f['top']} | {f['bottom']}{mark} |")
    if r["length_buckets"]:
        L += ["", "## Shorts length vs views", "", "| Length | Shorts | Median views |", "|---|---|---|"]
        L += [f"| {b['range']} | {b['n']} | {_n(b['median_views'])} |" for b in r["length_buckets"]]
    L += ["", "## What viewers say", ""]
    total = max(1, a["comments"])
    labels = {"ai": "calls it AI", "music_sound": "music / sound", "clickbait": "clickbait / fake / wrong",
              "question": "asks a question", "request": "asks for more", "praise": "praise"}
    for k, label in labels.items():
        hits = r["comment_themes"].get(k, [])
        L.append(f"- **{label}:** {len(hits)} ({100 * len(hits) / total:.0f}%)")
        for h in hits[:3]:
            text = " ".join(h["text"].split())[:140]
            L.append(f"  - [{h['likes']}👍] \"{text}\" (on: {h['video'][:40]})")
    if r["audience_words"]:
        L += ["", "Words viewers use most: " + ", ".join(w for w, _ in r["audience_words"][:15])]
    if r["music_in_descriptions"]:
        L += ["", "Music in descriptions: " + ", ".join(f"{k} {v}" for k, v in r["music_in_descriptions"].items())]
    return "\n".join(L) + "\n"
