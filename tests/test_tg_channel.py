"""Telegram giveaway bot: sources, Ukrainian posts, the owner's approval buttons, quiet hours, reminders, digest."""

from __future__ import annotations

import copy
from datetime import datetime, timezone

import httpx
import pytest

from tg_channel import bot as botmod
from tg_channel.__main__ import main
from tg_channel.bot import Bot, channel_id, empty_state, load_state, save_state
from tg_channel.posts import digest_post, new_post, unsupported_numbers
from tg_channel.sources import fetch_all, merge, parse_epic, parse_gamerpower
from tg_channel.telegram import Telegram, TelegramError

OWNER, STRANGER, CHANNEL = 555, 777, "@freegames_ua"


def utc(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


NOW = utc("2026-11-13T10:00:00")          # Friday, 12:00 in Kyiv


def _epic_el(title, oid, percent=0, current=True, slug=None):
    offer = {"startDate": "2026-11-12T16:00:00.000Z", "endDate": "2026-11-19T16:00:00.000Z",
             "discountSetting": {"discountType": "PERCENTAGE", "discountPercentage": percent}}
    return {"title": title, "id": oid, "productSlug": slug or title.lower().replace(" ", "-"),
            "keyImages": [{"type": "Thumbnail", "url": f"https://cdn1.epicgames.com/{oid}-t.jpg"},
                          {"type": "OfferImageWide", "url": f"https://cdn1.epicgames.com/{oid}-wide.jpg"}],
            "offerMappings": [{"pageSlug": f"{oid}-page", "pageType": "productHome"}],
            "price": {"totalPrice": {"discountPrice": 0, "originalPrice": 1999,
                                     "fmtPrice": {"originalPrice": "$19.99", "discountPrice": "0"}}},
            "promotions": {"promotionalOffers": [{"promotionalOffers": [offer]}] if current else [],
                           "upcomingPromotionalOffers": [] if current else [{"promotionalOffers": [offer]}]}}


EPIC = {"data": {"Catalog": {"searchStore": {"elements": [
    _epic_el("Hades Lite", "off1"),
    _epic_el("Mystery Game", "m1"),
    _epic_el("Next Week Game", "off2", current=False),
    _epic_el("Half Off", "off3", percent=50),
]}}}}

GP = [
    {"id": 101, "title": "Hades Lite (Epic Games) Giveaway", "worth": "$19.99", "image": "https://www.gamerpower.com/hl.jpg",
     "open_giveaway_url": "https://www.gamerpower.com/open/hades-lite", "type": "Game",
     "platforms": "PC, Epic Games Store", "end_date": "2026-11-19 23:59:00", "status": "Active"},
    {"id": 102, "title": "Cozy Farm (Steam) Giveaway", "worth": "$9.99", "image": "https://www.gamerpower.com/cozy.jpg",
     "open_giveaway_url": "https://www.gamerpower.com/open/cozy-farm", "type": "Game", "platforms": "PC, Steam",
     "end_date": "2026-11-15 23:59:00", "status": "Active"},
    {"id": 103, "title": "Old Thing Giveaway", "worth": "N/A", "image": None,
     "open_giveaway_url": "https://www.gamerpower.com/open/old-thing", "type": "Game", "platforms": "PC, GOG",
     "end_date": "N/A", "status": "Active"},
    {"id": 104, "title": "Skin Pack", "type": "DLC", "platforms": "PC, Steam", "status": "Active",
     "open_giveaway_url": "https://www.gamerpower.com/open/skins"},
    {"id": 105, "title": "Console Thing", "type": "Game", "platforms": "PS4", "status": "Active",
     "open_giveaway_url": "https://www.gamerpower.com/open/console"},
    {"id": 106, "title": "Ended Game", "type": "Game", "platforms": "PC, Steam", "status": "Active",
     "end_date": "2026-11-01 23:59:00", "open_giveaway_url": "https://www.gamerpower.com/open/ended"},
]


def fetch(now):
    return merge(parse_epic(EPIC, now), parse_gamerpower(GP, now)), []


class FakeTG:
    def __init__(self):
        self.calls, self.updates, self.mid, self.fail = [], [], 100, set()

    def call(self, method, **p):
        self.calls.append((method, p))
        if method in self.fail:
            raise TelegramError(f"{method}: failed")
        if method == "getUpdates":
            ups, self.updates = self.updates, []
            return ups
        if method in ("sendPhoto", "sendMessage"):
            self.mid += 1
            return {"message_id": self.mid}
        return True

    def sent(self, chat=None, methods=("sendPhoto", "sendMessage")):
        return [p for m, p in self.calls if m in methods and (chat is None or p.get("chat_id") == chat)]

    def drafts(self):
        return [p for p in self.sent(OWNER) if "reply_markup" in p]

    def press(self, data, sender=OWNER):
        self.updates.append({"update_id": len(self.calls) + 1000,
                             "callback_query": {"id": "cq", "from": {"id": sender}, "data": data}})


def run(tg, state, now=NOW, owner=OWNER, channel=CHANNEL, auto=False, fetcher=fetch):
    return Bot(tg, state, owner=owner, channel=channel, auto=auto, log=lambda m: None).run(now, fetcher)


# ---------------------------------------------------------------- sources and posts
def test_sources_parse_and_merge():
    epic = parse_epic(EPIC, NOW)
    assert [g.title for g in epic] == ["Hades Lite"]           # mystery, upcoming and half-price are not giveaways
    g = epic[0]
    assert g.url == "https://store.epicgames.com/p/off1-page" and g.image.endswith("off1-wide.jpg")
    assert g.worth == "$19.99" and g.ends == utc("2026-11-19T16:00:00") and g.ends_exact
    gp = parse_gamerpower(GP, NOW)
    assert [g.key for g in gp] == ["gp:101", "gp:102", "gp:103"]
    assert [g.title for g in gp] == ["Hades Lite", "Cozy Farm", "Old Thing"]
    assert gp[2].worth is None and gp[2].ends is None and not gp[1].ends_exact
    merged = merge(epic, gp)
    assert [g.key for g in merged] == ["epic:off1", "gp:102", "gp:103"]     # Epic's own data wins


def test_posts_are_ukrainian_and_carry_only_source_numbers():
    epic, cozy, old = fetch(NOW)[0]
    text = new_post(epic)
    assert "<b>Hades Lite</b>" in text and "Epic Games Store" in text and "$19.99" in text
    assert "до 19 листопада, 18:00 за Києвом" in text                       # 16:00 UTC is 18:00 in Kyiv
    assert 'href="https://store.epicgames.com/p/off1-page"' in text
    assert "до 15 листопада" in new_post(cozy) and "за Києвом" not in new_post(cozy)   # a date only
    assert "GamerPower" in new_post(cozy) and "Звичайна ціна" not in new_post(old)
    for g in (epic, cozy, old):
        assert unsupported_numbers(new_post(g), [g]) == set()
    assert unsupported_numbers(text.replace("безкоштовно", "знижка 50%"), [epic]) == {"50"}
    odd = copy.copy(epic)
    odd.title = "Tom & Jerry <3"
    assert "Tom &amp; Jerry &lt;3" in new_post(odd)
    many = [copy.copy(cozy) for _ in range(17)]
    assert "…і ще 2" in digest_post(many) and unsupported_numbers(digest_post(many), many, (2,)) == set()


def test_fetch_all_skips_a_failing_source():
    def handler(request: httpx.Request) -> httpx.Response:
        if "epicgames" in request.url.host:
            return httpx.Response(200, json=EPIC)
        return httpx.Response(500, json={"error": "down"})
    items, errors = fetch_all(NOW, httpx.Client(transport=httpx.MockTransport(handler)))
    assert [g.key for g in items] == ["epic:off1"]
    assert len(errors) == 1 and errors[0].startswith("GamerPower")


# ---------------------------------------------------------------- the bot
def test_without_owner_it_replies_with_the_chat_id_and_fetches_nothing():
    tg, state = FakeTG(), empty_state()
    tg.updates.append({"update_id": 7, "message": {"chat": {"id": OWNER, "type": "private"}, "from": {"id": OWNER},
                                                   "text": "/start"}})
    report = run(tg, state, owner=None, fetcher=lambda now: pytest.fail("must not fetch without an owner"))
    reply = tg.sent(OWNER)[0]["text"]
    assert str(OWNER) in reply and "TG_OWNER_CHAT_ID" in reply
    assert state["offset"] == 8 and not state["items"] and "TG_OWNER_CHAT_ID" in report["note"]


def test_drafts_once_then_publishes_what_the_owner_approves():
    tg, state = FakeTG(), empty_state()
    run(tg, state)
    drafts = tg.drafts()
    assert len(drafts) == 3 and all(p["chat_id"] == OWNER for p in drafts)
    assert {i["status"] for i in state["items"].values()} == {"pending"}
    assert drafts[2].get("text") and "photo" not in drafts[2]               # no image: a text draft
    run(tg, state)
    assert len(tg.drafts()) == 3                                            # nothing is drafted twice

    tg.press("p:1")
    run(tg, state)
    post = tg.sent(CHANNEL)
    assert len(post) == 1 and post[0]["caption"] == drafts[0]["caption"] and "reply_markup" not in post[0]
    assert state["items"]["epic:off1"]["status"] == "published" and "1" not in state["drafts"]
    assert any(m == "editMessageReplyMarkup" for m, _ in tg.calls)

    tg.press("r:2")
    tg.press("p:3", sender=STRANGER)
    tg.press("p:1")                                                         # pressed twice: already done
    run(tg, state)
    assert len(tg.sent(CHANNEL)) == 1
    assert state["items"]["gp:102"]["status"] == "rejected" and state["items"]["gp:103"]["status"] == "pending"
    answers = [p["text"] for m, p in tg.calls if m == "answerCallbackQuery"]
    assert "Немає доступу" in answers and "Цю чернетку вже оброблено" in answers


def test_quiet_hours_hold_the_drafts_until_morning():
    tg, state = FakeTG(), empty_state()
    run(tg, state, now=utc("2026-11-13T00:30:00"))                         # 02:30 in Kyiv
    assert not tg.drafts() and {i["status"] for i in state["items"].values()} == {"new"}
    run(tg, state, now=utc("2026-11-13T07:00:00"))                         # 09:00 in Kyiv
    assert len(tg.drafts()) == 3


def test_last_day_reminder_once():
    tg, state = FakeTG(), empty_state()
    run(tg, state, auto=True)
    run(tg, state, now=utc("2026-11-15T09:00:00"), auto=True)             # Cozy Farm ends on the 15th
    reminders = [p for p in tg.sent(CHANNEL) if "Останній день" in (p.get("caption") or p.get("text") or "")]
    assert len(reminders) == 1 and "Cozy Farm" in reminders[0]["caption"]
    assert state["items"]["gp:102"]["reminded"]
    run(tg, state, now=utc("2026-11-19T08:30:00"), auto=True)             # Hades Lite ends at 18:00 Kyiv today
    run(tg, state, now=utc("2026-11-19T09:00:00"), auto=True)
    reminders = [p for p in tg.sent(CHANNEL) if "Останній день" in (p.get("caption") or p.get("text") or "")]
    assert len(reminders) == 2 and "Hades Lite" in reminders[1]["caption"]


def test_sunday_digest_once_and_auto_mode():
    tg, state = FakeTG(), empty_state()
    run(tg, state, auto=True)
    assert len(tg.sent(CHANNEL)) == 3 and not tg.drafts()                  # auto mode posts without asking
    run(tg, state, now=utc("2026-11-15T10:00:00"), auto=True)             # Sunday 12:00 in Kyiv
    run(tg, state, now=utc("2026-11-15T12:00:00"), auto=True)
    digests = [p for p in tg.sent(CHANNEL) if "#дайджест" in (p.get("text") or "")]
    assert len(digests) == 1 and "Hades Lite" in digests[0]["text"] and "Cozy Farm" in digests[0]["text"]
    assert state["digests"]["2026-W46"] == "published"


def test_bad_post_is_blocked_and_source_errors_are_reported(monkeypatch):
    tg, state = FakeTG(), empty_state()
    monkeypatch.setattr(botmod, "new_post", lambda g: f"<b>{g.title}</b>: знижка 37%")   # 37 is in no source
    report = run(tg, state)
    assert not tg.drafts() and {i["status"] for i in state["items"].values()} == {"blocked"}
    assert any("37" in e for e in report["errors"])
    report = run(FakeTG(), empty_state(), fetcher=lambda now: ([], ["GamerPower: HTTPStatusError: 500"]))
    assert report["errors"] == ["GamerPower: HTTPStatusError: 500"]


def test_publish_without_channel_keeps_the_draft():
    tg, state = FakeTG(), empty_state()
    run(tg, state, channel=None)
    tg.press("p:1")
    run(tg, state, channel=None)
    assert "1" in state["drafts"] and state["items"]["epic:off1"]["status"] == "pending"
    assert "Канал не налаштовано (TG_CHANNEL)" in [p["text"] for m, p in tg.calls if m == "answerCallbackQuery"]


def test_state_file_channel_id_and_cli(tmp_path, monkeypatch):
    state = empty_state()
    state["items"]["x"] = {"status": "new"}
    save_state(tmp_path / "s" / "state.json", state)
    assert load_state(tmp_path / "s" / "state.json")["items"] == {"x": {"status": "new"}}
    assert load_state(tmp_path / "missing.json") == empty_state()
    assert channel_id("freegames") == "@freegames" and channel_id("@x") == "@x" and channel_id("-1001") == "-1001"
    assert channel_id("") is None
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert main(["run", "--state", str(tmp_path / "state.json")]) == 1


def test_token_never_appears_in_errors():
    token = "123456:SECRET-token"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("getMe"):
            raise httpx.ConnectError(f"cannot reach {request.url}")
        return httpx.Response(200, json={"ok": False, "description": "Bad Request: chat not found"})
    tg = Telegram(token, httpx.Client(transport=httpx.MockTransport(handler)))
    for method in ("getMe", "sendMessage"):
        with pytest.raises(TelegramError) as e:
            tg.call(method, chat_id=1, text="x")
        assert token not in str(e.value) and "SECRET" not in str(e.value)
