"""One run of the channel bot: the owner's button presses, new giveaways, drafts or posts, reminders, the digest.

State (a JSON file) remembers every giveaway seen, its status (new, pending, published, rejected, blocked), the
drafts waiting for a button press and the last Telegram update read, so nothing is sent twice.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from .posts import CAPTION_MAX, KYIV, digest_post, ending_post, new_post, unsupported_numbers
from .sources import Giveaway
from .telegram import Telegram, TelegramError

ACTIVE_HOURS = (8, 23)      # drafts and automatic posts only from 08:00 to 23:00 Kyiv time
REMINDER_HOUR = 10          # "last day" reminders from 10:00 on the end day
DIGEST_DAY, DIGEST_HOUR = 6, 11   # Sunday from 11:00
MAX_DRAFTS_PER_RUN = 8      # the first run can find a dozen giveaways: the rest wait for the next run
KEEP_DAYS = 21              # forget giveaways that ended this long ago

Fetch = Callable[[datetime], tuple[list[Giveaway], list[str]]]


def empty_state() -> dict[str, Any]:
    return {"version": 1, "offset": 0, "next_id": 1, "items": {}, "drafts": {}, "digests": {}}


def load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_state()
    state = empty_state()
    state.update({k: v for k, v in data.items() if k in state})
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def still_open(g: Giveaway, now: datetime) -> bool:
    """An exact end is a moment; a date-only end (GamerPower) lasts the whole day in Kyiv."""
    if not g.ends:
        return True
    if g.ends_exact:
        return g.ends > now
    return g.ends.date() >= now.astimezone(KYIV).date()


def channel_id(value: str | None) -> str | None:
    """«name», «@name» or a numeric id (-100...) as Telegram's chat_id."""
    v = (value or "").strip()
    if not v:
        return None
    return v if v.startswith("@") or v.lstrip("-").isdigit() else f"@{v}"


class Bot:
    def __init__(self, tg: Telegram, state: dict[str, Any], owner: int | None, channel: str | None,
                 auto: bool = False, log: Callable[[str], None] = print):
        self.tg, self.state, self.owner, self.channel, self.auto, self.log = tg, state, owner, channel_id(channel), auto, log
        self.report: dict[str, Any] = {"updates": 0, "drafts": 0, "published": 0, "rejected": 0, "errors": []}

    # ------------------------------------------------------------ the run
    def run(self, now: datetime, fetch: Fetch) -> dict[str, Any]:
        self.handle_updates()
        if self.owner is None:
            self.report["note"] = "TG_OWNER_CHAT_ID is not set: send /start to the bot and add the id it replies with"
            return self.report
        giveaways, errors = fetch(now)
        self.report["errors"] += errors
        self.report["active_giveaways"] = len(giveaways)
        for g in giveaways:
            item = self.state["items"].setdefault(g.key, {"status": "new", "reminded": False, "first_seen": now.isoformat()})
            item["giveaway"] = g.to_dict()            # Epic sometimes moves an end date: keep the latest
        if self._active(now):
            self.send_new(now)
            self.reminders(now)
            self.digest(now)
        self.prune(now)
        return self.report

    def _active(self, now: datetime) -> bool:
        return ACTIVE_HOURS[0] <= now.astimezone(KYIV).hour < ACTIVE_HOURS[1]

    # ------------------------------------------------------------ owner's buttons and commands
    def handle_updates(self) -> None:
        self._replied: set[int] = set()              # one reply per chat per run, however many /start were sent
        try:
            updates = self.tg.call("getUpdates", offset=self.state["offset"], timeout=0,
                                   allowed_updates=["message", "callback_query"])
        except TelegramError as e:
            self.report["errors"].append(str(e))
            return
        for u in updates:
            self.state["offset"] = max(self.state["offset"], u["update_id"] + 1)
            self.report["updates"] += 1
            if "callback_query" in u:
                self.on_button(u["callback_query"])
            elif "message" in u:
                self.on_message(u["message"])

    def on_message(self, msg: dict) -> None:
        if (msg.get("chat") or {}).get("type") != "private" or not str(msg.get("text", "")).startswith(("/start", "/status")):
            return
        if msg["chat"]["id"] in self._replied:
            return
        self._replied.add(msg["chat"]["id"])
        sender = (msg.get("from") or {}).get("id")
        if self.owner is None:
            text = (f"Твій chat id: <code>{sender}</code>\n\nДодай його в секрети репозиторію GitHub як "
                    f"<b>TG_OWNER_CHAT_ID</b>, і я почну надсилати тобі чернетки постів.")
        elif sender == self.owner:
            pending = sum(1 for i in self.state["items"].values() if i["status"] == "pending")
            published = sum(1 for i in self.state["items"].values() if i["status"] == "published")
            text = (f"Бот працює. Чернеток чекає: {pending}. Опубліковано роздач: {published}. "
                    f"Канал: {self.channel or 'не налаштовано (TG_CHANNEL)'}.")
        else:
            text = "Це службовий бот каналу."
        self._quiet("sendMessage", chat_id=msg["chat"]["id"], text=text, parse_mode="HTML")

    def on_button(self, cq: dict) -> None:
        sender, data = (cq.get("from") or {}).get("id"), str(cq.get("data", ""))
        if sender != self.owner:
            return self._answer(cq, "Немає доступу")
        action, _, n = data.partition(":")
        draft = self.state["drafts"].get(n)
        if not draft:
            return self._answer(cq, "Цю чернетку вже оброблено")
        if action == "p":
            mid = self.publish(draft["text"], draft.get("image"))
            if mid is None:
                why = ("Канал не налаштовано: додай змінну TG_CHANNEL (@адреса каналу) у GitHub" if not self.channel
                       else "Не вдалося опублікувати: перевір, що бот адмін каналу з правом публікувати")
                self._answer(cq, why)        # the press is usually minutes old by now, so say it in the chat too
                self._quiet("sendMessage", chat_id=self.owner, text=f"⚠️ {why}. Чернетка чекає, натисни ще раз пізніше.",
                            reply_to_message_id=draft["message_id"])
                return None
            self._set_status(draft, "published")
            self.report["published"] += 1
            self._answer(cq, "Опубліковано")
        elif action == "r":
            self._set_status(draft, "rejected")
            self.report["rejected"] += 1
            self._answer(cq, "Відхилено")
        else:
            return self._answer(cq, "Невідома дія")
        self._quiet("editMessageReplyMarkup", chat_id=self.owner, message_id=draft["message_id"],
                    reply_markup={"inline_keyboard": []})
        mark = "✅ Опубліковано" if action == "p" else "❌ Відхилено"
        self._quiet("sendMessage", chat_id=self.owner, text=mark, reply_to_message_id=draft["message_id"])
        del self.state["drafts"][n]

    def _set_status(self, draft: dict, status: str) -> None:
        if draft["kind"] == "digest":
            self.state["digests"][draft["key"]] = status
        elif draft["kind"] == "new" and draft["key"] in self.state["items"]:
            self.state["items"][draft["key"]]["status"] = status

    def _answer(self, cq: dict, text: str) -> None:
        self._quiet("answerCallbackQuery", callback_query_id=cq.get("id"), text=text)   # fails when the press is old

    def _quiet(self, method: str, **params: Any) -> Any:
        try:
            return self.tg.call(method, **params)
        except TelegramError as e:
            self.log(f"{method}: {e}")
            return None

    # ------------------------------------------------------------ sending
    def send(self, chat: int | str, text: str, image: str | None, markup: dict | None = None) -> dict:
        extra = {"reply_markup": markup} if markup else {}
        if image and len(text) <= CAPTION_MAX:
            try:
                return self.tg.call("sendPhoto", chat_id=chat, photo=image, caption=text, parse_mode="HTML", **extra)
            except TelegramError as e:
                self.log(f"photo failed, sending text: {e}")
        return self.tg.call("sendMessage", chat_id=chat, text=text, parse_mode="HTML", **extra)

    def publish(self, text: str, image: str | None) -> int | None:
        if not self.channel:
            return None
        try:
            return self.send(self.channel, text, image)["message_id"]
        except TelegramError as e:
            self.report["errors"].append(str(e))
            return None

    def draft(self, kind: str, key: str, text: str, image: str | None) -> bool:
        n = str(self.state["next_id"])
        markup = {"inline_keyboard": [[{"text": "✅ Опублікувати", "callback_data": f"p:{n}"},
                                       {"text": "❌ Відхилити", "callback_data": f"r:{n}"}]]}
        try:
            msg = self.send(self.owner, text, image, markup)
        except TelegramError as e:
            self.report["errors"].append(str(e))
            return False
        self.state["next_id"] += 1
        self.state["drafts"][n] = {"kind": kind, "key": key, "text": text, "image": image,
                                   "message_id": msg["message_id"]}
        self.report["drafts"] += 1
        return True

    def offer(self, kind: str, key: str, text: str, image: str | None, items: list[Giveaway],
              extra: tuple[int, ...] = ()) -> str | None:
        """Publish (auto mode) or draft one post; returns the new status, or None to retry next run."""
        bad = unsupported_numbers(text, items, extra)
        if bad:
            self.report["errors"].append(f"{key}: numbers not in the source data {sorted(bad)}; post not sent")
            return "blocked"
        if self.auto:
            mid = self.publish(text, image)
            if mid is None:
                return None
            self.report["published"] += 1
            return "published"
        return "pending" if self.draft(kind, key, text, image) else None

    # ------------------------------------------------------------ the three kinds of post
    def send_new(self, now: datetime) -> None:
        sent = 0
        for key, item in self.state["items"].items():
            if item["status"] != "new" or "giveaway" not in item:
                continue
            g = Giveaway.from_dict(item["giveaway"])
            if not still_open(g, now):
                item["status"] = "expired"
                continue
            if sent >= MAX_DRAFTS_PER_RUN:
                break
            status = self.offer("new", key, new_post(g), g.image, [g])
            if status:
                item["status"] = status
                sent += 1

    def reminders(self, now: datetime) -> None:
        k_now = now.astimezone(KYIV)
        if k_now.hour < REMINDER_HOUR:
            return
        for key, item in self.state["items"].items():
            if item["status"] != "published" or item.get("reminded") or "giveaway" not in item:
                continue
            g = Giveaway.from_dict(item["giveaway"])
            if not g.ends:
                continue
            if g.ends_exact:
                due = g.ends.astimezone(KYIV).date() == k_now.date() and g.ends - now > timedelta(hours=1)
            else:
                due = g.ends.date() == k_now.date()
            if due and self.offer("ending", key, ending_post(g), g.image, [g]):
                item["reminded"] = True

    def digest(self, now: datetime) -> None:
        k_now = now.astimezone(KYIV)
        iso = k_now.isocalendar()
        week = f"{iso.year}-W{iso.week:02d}"
        if k_now.weekday() != DIGEST_DAY or k_now.hour < DIGEST_HOUR or week in self.state["digests"]:
            return
        live = [Giveaway.from_dict(i["giveaway"]) for i in self.state["items"].values()
                if i["status"] == "published" and "giveaway" in i]
        live = [g for g in live if still_open(g, now)]
        if len(live) < 2:
            self.state["digests"][week] = "skipped"
            return
        live.sort(key=lambda g: (g.ends is None, g.ends or now))
        extra = (len(live) - 15,) if len(live) > 15 else ()
        status = self.offer("digest", week, digest_post(live), None, live, extra)
        if status:
            self.state["digests"][week] = status

    def prune(self, now: datetime) -> None:
        items = self.state["items"]
        for key in list(items):
            g = items[key].get("giveaway")
            ends = Giveaway.from_dict(g).ends if g else None
            seen = datetime.fromisoformat(items[key]["first_seen"])
            if (ends and ends < now - timedelta(days=KEEP_DAYS)) or (not ends and seen < now - timedelta(days=60)):
                del items[key]
        for n in list(self.state["drafts"]):
            d = self.state["drafts"][n]
            if d["kind"] != "digest" and d["key"] not in items:
                del self.state["drafts"][n]
        for week in sorted(self.state["digests"])[:-8]:
            del self.state["digests"][week]
