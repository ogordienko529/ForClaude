"""Post texts in Ukrainian, built from templates so that every name, price and date comes from the source data."""

from __future__ import annotations

import html
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from .sources import Giveaway

KYIV = ZoneInfo("Europe/Kyiv")
MONTHS = ["січня", "лютого", "березня", "квітня", "травня", "червня", "липня", "серпня", "вересня", "жовтня",
          "листопада", "грудня"]
TAGS = {"Epic Games Store": "#epic", "Steam": "#steam", "GOG": "#gog", "itch.io": "#itchio",
        "Ubisoft Connect": "#ubisoft", "EA app": "#ea", "Battle.net": "#battlenet"}
CAPTION_MAX = 1024        # Telegram's limit for a photo caption


def esc(s: str) -> str:
    return html.escape(str(s), quote=False)


def until(g: Giveaway) -> str | None:
    """«до 20 листопада, 18:00 за Києвом» for an exact end, «до 20 листопада» for a date only."""
    if not g.ends:
        return None
    if g.ends_exact:
        k = g.ends.astimezone(KYIV)
        return f"до {k.day} {MONTHS[k.month - 1]}, {k:%H:%M} за Києвом"
    return f"до {g.ends.day} {MONTHS[g.ends.month - 1]}"


def _source(g: Giveaway) -> str:
    if g.source == "GamerPower":
        return 'Джерело: <a href="https://www.gamerpower.com">GamerPower</a>'
    return f"Джерело: {esc(g.source)}"


def _link(url: str, text: str) -> str:
    return f'<a href="{html.escape(url, quote=True)}">{esc(text)}</a>'


def new_post(g: Giveaway) -> str:
    lines = [f"🎁 <b>{esc(g.title)}</b>: безкоштовно назавжди", f"🏪 {esc(g.store)}"]
    if g.worth:
        lines.append(f"💰 Звичайна ціна: {esc(g.worth)}")
    if until(g):
        lines.append(f"⏳ Забрати {until(g)}")
    lines += ["", f"👉 {_link(g.url, 'Забрати гру')}", "", _source(g), f"#роздача {TAGS.get(g.store, '')}".strip()]
    return "\n".join(lines)


def ending_post(g: Giveaway) -> str:
    lines = [f"⏰ <b>Останній день:</b> {esc(g.title)} безкоштовно в {esc(g.store)}"]
    if until(g):
        lines.append(f"Встигни {until(g)}")
    lines += ["", f"👉 {_link(g.url, 'Забрати гру')}", "", f"#закінчується {TAGS.get(g.store, '')}".strip()]
    return "\n".join(lines)


def digest_post(items: list[Giveaway], limit: int = 15) -> str:
    lines = ["🗓 <b>Що можна забрати безкоштовно зараз</b>", ""]
    for g in items[:limit]:
        tail = f", {until(g)}" if until(g) else ""
        lines.append(f"• {_link(g.url, g.title)} ({esc(g.store)}{tail})")
    if len(items) > limit:
        lines.append(f"…і ще {len(items) - limit} в каналі вище")
    lines += ["", "#дайджест"]
    return "\n".join(lines)


def unsupported_numbers(text: str, items: list[Giveaway], extra: tuple[int, ...] = ()) -> set[str]:
    """Numbers in a post's visible text that the source data does not contain: a template bug, so the post is not
    sent. Link targets and hashtags are ignored; `extra` allows counts the bot computes itself (the digest's rest)."""
    visible = re.sub(r"<a [^>]*>|</?\w+>|#\S+", " ", text)
    allowed = {str(n) for n in extra}
    for g in items:
        for s in (g.title, g.worth or "", g.store, until(g) or ""):
            allowed |= set(re.findall(r"\d+", s))
    return {n for n in re.findall(r"\d+", visible) if n not in allowed}


def kyiv_now(now: datetime) -> datetime:
    return now.astimezone(KYIV)
