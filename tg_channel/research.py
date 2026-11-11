"""Competitor study: the last posts of public Telegram channels from their web preview (t.me/s/<name>).

For each channel: title, description, subscribers, and per post the date, views, reactions, forwards-from, media
kind (photo, video, poll, document, link preview), the text and its length. The preview needs no account and no
key; it is fetched slowly (one page every couple of seconds). The numbers are what the page shows (views like "12.3K"
become 12300), so they are rounded.

    python -m tg_channel research --channels tg_content/research/channels.txt --pages 5 --out research.json
"""

from __future__ import annotations

import html
import json
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

import httpx

PREVIEW = "https://t.me/s/{name}"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; channel-study/0.1)", "Accept-Language": "uk,en;q=0.8"}


def number(text: str) -> int | None:
    """«12.3K» → 12300, «1.2M» → 1200000, «948» → 948, «1 234» → 1234."""
    t = (text or "").strip().replace(" ", "").replace(" ", "").replace(",", ".")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([KkMm]?)", t)
    if not m:
        return None
    mult = {"": 1, "k": 1_000, "m": 1_000_000}[m[2].lower()]
    return int(round(float(m[1]) * mult))


def read_channels(path: Path) -> list[str]:
    out = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        name = ln.split("#", 1)[0].strip().lstrip("@")
        if name and re.fullmatch(r"[A-Za-z0-9_]{4,64}", name) and name.lower() not in [n.lower() for n in out]:
            out.append(name)
    return out


TME = re.compile(r"https?://t\.me/([A-Za-z0-9_]{4,64})(?:[/?]|$)")
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def has(cls: str, prefix: str) -> bool:
    """A class token that starts with prefix (t.me adds suffixes like _wrap, _player)."""
    return any(t.startswith(prefix) for t in cls.split())


class _Page(HTMLParser):
    """Walks t.me/s markup: the channel header and each message block."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.channel: dict[str, Any] = {"counters": {}}
        self.posts: list[dict[str, Any]] = []
        self._stack: list[tuple[str, str]] = []      # (tag, class) of open elements
        self._post: dict[str, Any] | None = None
        self._post_depth = 0
        self._grab: str | None = None                 # which field the current text goes to
        self._grab_depth = 0
        self._counter: list[str] = []
        self._reaction: list[str] | None = None

    # -- helpers
    def _classes(self) -> list[str]:
        return [c for _, c in self._stack]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        cls = a.get("class", "")
        if tag in VOID:
            if tag == "br" and self._grab in ("text", "description"):
                self._add("\n")
            return
        self._stack.append((tag, cls))
        depth = len(self._stack)
        if "tgme_widget_message" in cls.split() and a.get("data-post"):
            self._post = {"id": a["data-post"], "text": "", "views": None, "date": None, "media": [],
                          "reactions": 0, "forwarded": False, "reply": False, "links_to": []}
            self.posts.append(self._post)
            self._post_depth = depth
        p = self._post
        if p is not None:
            in_reply = any(has(c, "tgme_widget_message_reply") for c in self._classes()[:-1])
            media = next((m for pre, m in (("tgme_widget_message_photo", "photo"), ("tgme_widget_message_video", "video"),
                                           ("tgme_widget_message_roundvideo", "video"), ("tgme_widget_message_poll", "poll"),
                                           ("tgme_widget_message_document", "document"),
                                           ("tgme_widget_message_voice", "voice"),
                                           ("tgme_widget_message_link_preview", "link_preview")) if has(cls, pre)), None)
            m = TME.match(a.get("href", "")) if tag == "a" else None
            if m and m[1].lower() not in ("s", "share", "joinchat", "addstickers", "proxy", "iv", "c") \
                    and m[1].lower() != p["id"].split("/")[0].lower() and m[1] not in p["links_to"]:
                p["links_to"].append(m[1])
            if "tgme_widget_message_text" in cls.split() and self._grab is None and not in_reply:
                self._grab, self._grab_depth = "text", depth
            elif "tgme_widget_message_views" in cls.split():
                self._grab, self._grab_depth = "views", depth
            elif tag == "time" and a.get("datetime"):
                p["date"] = a["datetime"]
            elif media and not in_reply:
                if media not in p["media"]:
                    p["media"].append(media)
            elif has(cls, "tgme_widget_message_forwarded_from"):
                p["forwarded"] = True
            elif has(cls, "tgme_widget_message_reply"):
                p["reply"] = True
            elif "tgme_reaction" in cls.split():
                self._reaction = []
        else:
            if "tgme_channel_info_header_title" in cls.split():
                self._grab, self._grab_depth = "title", depth
            elif "tgme_channel_info_description" in cls.split():
                self._grab, self._grab_depth = "description", depth
            elif "tgme_channel_info_counter" in cls.split():
                self._counter = []
                self._grab, self._grab_depth = "counter", depth

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID:
            return
        depth = len(self._stack)
        if self._reaction is not None and self._stack and "tgme_reaction" in self._stack[-1][1].split():
            m = re.search(r"(\d+(?:[.,]\d+)?[KkMm]?)\s*$", "".join(self._reaction))
            n = number(m[1]) if m else None
            if self._post is not None and n:
                self._post["reactions"] += n
            self._reaction = None
        if self._grab and depth == self._grab_depth:
            if self._grab == "counter":
                words = " ".join("".join(self._counter).split()).split(" ")
                if len(words) >= 2 and number(words[0]) is not None:
                    self.channel["counters"][words[1].lower()] = number(words[0])
            self._grab = None
        if self._post is not None and depth == self._post_depth:
            self._post = None
        if self._stack:
            self._stack.pop()

    def handle_data(self, data: str) -> None:
        if self._reaction is not None:
            self._reaction.append(data)
        if self._grab == "counter":
            self._counter.append(data)
        elif self._grab:
            self._add(data)

    def _add(self, data: str) -> None:
        if self._grab in ("title", "description"):
            self.channel[self._grab] = self.channel.get(self._grab, "") + data
        elif self._post is not None and self._grab == "text":
            self._post["text"] += data
        elif self._post is not None and self._grab == "views":
            self._post["views"] = number(data) if number(data) is not None else self._post["views"]


def parse(page: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    p = _Page()
    p.feed(page)
    ch = {k: (v.strip() if isinstance(v, str) else v) for k, v in p.channel.items()}
    for post in p.posts:
        post["text"] = html.unescape(post["text"]).strip()
        post["chars"] = len(post["text"])
        post["hashtags"] = re.findall(r"#\w+", post["text"])
        post["links"] = len(re.findall(r"https?://", post["text"]))
        own = post["id"].split("/")[0].lower()
        for name in re.findall(r"(?<![\w@])@([A-Za-z][A-Za-z0-9_]{3,63})\b", post["text"]):
            if name.lower() != own and name not in post["links_to"]:
                post["links_to"].append(name)
    return ch, p.posts


def fetch_channel(name: str, pages: int, http: httpx.Client, pause: Callable[[float], None] = time.sleep,
                  delay: float = 2.0) -> dict[str, Any]:
    out: dict[str, Any] = {"name": name, "url": f"https://t.me/{name}", "posts": [], "error": None}
    before = None
    for i in range(pages):
        if i:
            pause(delay)
        url = PREVIEW.format(name=name) + (f"?before={before}" if before else "")
        try:
            r = http.get(url)
            for wait in (10, 30, 60):              # t.me asks to slow down with 429
                if r.status_code != 429:
                    break
                pause(wait)
                r = http.get(url)
            r.raise_for_status()
        except httpx.HTTPError as e:
            out["error"] = f"{type(e).__name__}: {e}"[:200]
            break
        ch, posts = parse(r.text)
        if i == 0:
            out.update({"title": ch.get("title"), "description": ch.get("description"),
                        "subscribers": (ch.get("counters") or {}).get("subscribers"),
                        "counters": ch.get("counters")})
            if not posts:
                out["error"] = "no posts in the preview (private, a group, a bot, or no such channel)"
                out["sample"] = r.text[:1500]
                break
        known = {p["id"] for p in out["posts"]}
        new = [p for p in posts if p["id"] not in known]
        if not new:
            break
        out["posts"] = new + out["posts"]
        ids = [int(p["id"].rsplit("/", 1)[-1]) for p in new if p["id"].rsplit("/", 1)[-1].isdigit()]
        if not ids or min(ids) <= 1:
            break
        before = min(ids)
    out["posts"].sort(key=lambda p: p.get("date") or "")
    return out


def summary(ch: dict[str, Any]) -> dict[str, Any]:
    """Per channel: how often it posts, typical views, ERR, what kind of post does best."""
    posts = [p for p in ch.get("posts", []) if p.get("views")]
    if not posts:
        return {"name": ch["name"], "posts": 0}
    views = sorted(p["views"] for p in posts)
    med = views[len(views) // 2]
    dates = [datetime.fromisoformat(p["date"]) for p in posts if p.get("date")]
    days = max((max(dates) - min(dates)).total_seconds() / 86400, 1) if len(dates) > 1 else 1
    subs = ch.get("subscribers") or 0

    def kind(p: dict[str, Any]) -> str:
        return p["media"][0] if p["media"] else ("text_long" if p["chars"] > 600 else "text_short")
    kinds: dict[str, list[int]] = {}
    for p in posts:
        kinds.setdefault(kind(p), []).append(p["views"])
    hours: dict[int, int] = {}
    for d in dates:
        h = d.astimezone(timezone.utc).hour
        hours[h] = hours.get(h, 0) + 1
    top = sorted(posts, key=lambda p: p["views"], reverse=True)[:5]
    return {
        "name": ch["name"], "title": ch.get("title"), "subscribers": subs, "posts": len(posts),
        "posts_per_day": round(len(posts) / days, 2), "median_views": med,
        "err_median": round(med / subs, 3) if subs else None,
        "median_chars": sorted(p["chars"] for p in posts)[len(posts) // 2],
        "reactions_per_post": round(sum(p["reactions"] for p in posts) / len(posts), 1),
        "by_kind": {k: {"n": len(v), "median_views": sorted(v)[len(v) // 2]} for k, v in kinds.items()},
        "busiest_hours_utc": sorted(hours, key=hours.get, reverse=True)[:4],
        "top_posts": [{"id": p["id"], "views": p["views"], "reactions": p["reactions"], "kind": kind(p),
                       "text": p["text"][:300]} for p in top],
    }


def mentioned(channels: list[dict[str, Any]], exclude: set[str]) -> list[tuple[str, int]]:
    """Channels the studied ones link to or forward from most, by how many studied channels do it."""
    count: dict[str, set[str]] = {}
    for ch in channels:
        for p in ch.get("posts", []):
            for name in p.get("links_to", []):
                if name.lower() not in exclude:
                    count.setdefault(name, set()).add(ch["name"].lower())
    return sorted(((n, len(v)) for n, v in count.items()), key=lambda x: (-x[1], x[0].lower()))


def study(names: list[str], pages: int, out_dir: Path, http: httpx.Client | None = None,
          pause: Callable[[float], None] = time.sleep, log: Callable[[str], None] = print,
          snowball: int = 0) -> dict[str, Any]:
    """Fetch the seed channels, then (snowball=N) up to N channels they link to or repost from, 2 pages each."""
    client = http or httpx.Client(timeout=30, headers=HEADERS, follow_redirects=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    channels: list[dict[str, Any]] = []

    def one(name: str, n: int, via: str) -> None:
        if channels:
            pause(3)
        ch = fetch_channel(name, n, client, pause)
        ch["found_via"] = via
        log(f"{name}: {len(ch['posts'])} posts, {ch.get('subscribers')} subscribers"
            + (f", {ch['error']}" if ch.get("error") else ""))
        channels.append(ch)
    for name in names:
        one(name, pages, "seed")
    if snowball:
        seen = {n.lower() for n in names}
        for name, k in [x for x in mentioned(channels, seen) if x[1] >= 2][:snowball]:
            one(name, 2, f"linked by {k} studied channels")
    summaries = [dict(summary(ch), found_via=ch["found_via"]) for ch in channels]
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (out_dir / "channels.json").write_text(json.dumps({"fetched": stamp, "channels": channels}, ensure_ascii=False,
                                                      indent=1), encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps({"fetched": stamp, "channels": summaries}, ensure_ascii=False,
                                                     indent=1), encoding="utf-8")
    return {"fetched": stamp, "channels": summaries}
