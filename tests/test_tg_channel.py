"""Telegram channel bot: scheduled posts and quizzes, the channel profile, and the free-games mode (sources, Ukrainian
posts, the owner's approval buttons, quiet hours, reminders, digest)."""

from __future__ import annotations

import copy
import json
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
    for uid in (7, 8, 9):                                                   # /start pressed three times
        tg.updates.append({"update_id": uid, "message": {"chat": {"id": OWNER, "type": "private"},
                                                         "from": {"id": OWNER}, "text": "/start"}})
    report = run(tg, state, owner=None, fetcher=lambda now: pytest.fail("must not fetch without an owner"))
    replies = tg.sent(OWNER)
    assert len(replies) == 1 and str(OWNER) in replies[0]["text"] and "TG_OWNER_CHAT_ID" in replies[0]["text"]
    assert state["offset"] == 10 and not state["items"] and "TG_OWNER_CHAT_ID" in report["note"]


def test_title_cleanup():
    from tg_channel.sources import clean_title
    assert clean_title("Dwarven Realms Key") == "Dwarven Realms"
    assert clean_title("Cozy Farm (Steam) Key Giveaway") == "Cozy Farm"
    assert clean_title("Keyboard Hero") == "Keyboard Hero"


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
    assert any("TG_CHANNEL" in p["text"] for m, p in tg.calls if m == "answerCallbackQuery")
    notes = [p["text"] for p in tg.sent(OWNER, ("sendMessage",)) if p["text"].startswith("⚠️")]
    assert len(notes) == 1 and "TG_CHANNEL" in notes[0]                    # also said in the chat: the press is old


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


# ---------------------------------------------------------------- the channel's own posts (tg_content/posts)
from pathlib import Path

from tg_channel import feed


def _write(folder, name, body):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(body, encoding="utf-8")


TEXT_POST = "---\nrubric: prompt\n---\n<b>План тижня за хвилину</b>\n\n<pre>Склади план на [тиждень]</pre>\n\n#промпт\n"
QUIZ_POST = ("---\nrubric: quiz\nquestion: Що ШІ не знає без пошуку?\noptions:\n- Таблицю множення\n"
             "- Сьогоднішній курс\ncorrect: 2\nexplanation: Модель знає світ лише до дати навчання.\n---\n")


def feed_bot(tg, state, posts, profile=None):
    return Bot(tg, state, owner=OWNER, channel=CHANNEL, auto=True, log=lambda m: None, posts=posts,
               giveaways=False, profile=profile)


def test_repo_posts_are_all_valid():
    posts = feed.load(Path(__file__).resolve().parents[1] / "tg_content" / "posts")
    assert posts, "tg_content/posts is empty"
    assert [p.id for p in posts if p.problems] == [], {p.id: p.problems for p in posts if p.problems}
    numbers = [p.id.split("-")[0] for p in posts]
    assert all(n.isdigit() and len(n) == 4 for n in numbers) and len(set(numbers)) == len(numbers)


def test_post_checks_catch_what_telegram_would_reject(tmp_path):
    _write(tmp_path, "0001-ok.md", TEXT_POST)
    _write(tmp_path, "0002-quiz.md", QUIZ_POST)
    _write(tmp_path, "0003-bad.md", "---\nrubric: prompt\n---\n<b>Тест <i>криво</b></i> 5 < 6 & ще <div>x</div>\n")
    _write(tmp_path, "0004-ai.md", "---\nrubric: myth\n---\nУ сучасному світі ШІ відіграє ключову роль.\n#міф\n")
    _write(tmp_path, "0005-quiz-bad.md", "---\nrubric: quiz\nquestion: Q?\noptions:\n- A\n- A\ncorrect: 3\n---\nтекст\n")
    _write(tmp_path, "0006-nohead.md", "просто текст #промпт")
    _write(tmp_path, "0007-long.md", "---\nrubric: career\n---\n" + "слово " * 600 + "#робота")
    posts = {p.id: p for p in feed.load(tmp_path)}
    assert posts["0001-ok"].problems == [] and posts["0002-quiz"].problems == []
    assert posts["0002-quiz"].correct == 2 and posts["0002-quiz"].options[1] == "Сьогоднішній курс"
    bad = " | ".join(posts["0003-bad"].problems)
    assert "does not close" in bad and "<div>" in bad and "bare <" in bad and "bare &" in bad and "hashtag" in bad
    assert any("у сучасному світі" in p for p in posts["0004-ai"].problems)
    quiz = " | ".join(posts["0005-quiz-bad"].problems)
    assert "same" in quiz and "correct" in quiz and "no text" in quiz
    assert "no header" in posts["0006-nohead"].problems[0]
    assert any("too long" in p for p in posts["0007-long"].problems)
    assert feed.html_problems('<a href="https://x.ua">x</a> <pre><code class="language-sql">a &lt; b</code></pre>') == []
    assert feed.html_problems("<pre><b>x</b></pre>")


def test_two_posts_a_day_in_order_quiz_as_a_poll(tmp_path):
    _write(tmp_path, "0001-a.md", TEXT_POST)
    _write(tmp_path, "0002-b.md", QUIZ_POST)
    _write(tmp_path, "0003-c.md", TEXT_POST)
    posts, tg, state = feed.load(tmp_path), FakeTG(), empty_state()
    feed_bot(tg, state, posts).run(utc("2026-11-13T05:00:00"), fetch)     # 07:00 Kyiv: quiet hours
    feed_bot(tg, state, posts).run(utc("2026-11-13T07:00:00"), fetch)     # 09:00: before the morning slot
    assert not tg.sent(CHANNEL) and not [c for c in tg.calls if c[0] == "sendPoll"]
    feed_bot(tg, state, posts).run(utc("2026-11-13T07:45:00"), fetch)     # 09:45: the morning post
    feed_bot(tg, state, posts).run(utc("2026-11-13T08:00:00"), fetch)     # 10:00: nothing more until evening
    sent = tg.sent(CHANNEL)
    assert len(sent) == 1 and sent[0]["text"].startswith("<b>План тижня за хвилину</b>") and sent[0]["parse_mode"] == "HTML"
    assert list(state["feed"]) == ["0001-a"]
    feed_bot(tg, state, posts).run(utc("2026-11-13T17:15:00"), fetch)     # 19:15: the evening quiz
    polls = [p for m, p in tg.calls if m == "sendPoll"]
    assert len(polls) == 1 and polls[0]["type"] == "quiz" and polls[0]["correct_option_id"] == 1
    assert polls[0]["options"] == [{"text": "Таблицю множення"}, {"text": "Сьогоднішній курс"}]
    feed_bot(tg, state, posts).run(utc("2026-11-13T20:30:00"), fetch)     # 22:30: both slots done today
    assert len(state["feed"]) == 2
    feed_bot(tg, state, posts).run(utc("2026-11-14T07:31:00"), fetch)     # next morning: the third one
    assert list(state["feed"]) == ["0001-a", "0002-b", "0003-c"]
    feed_bot(tg, state, posts).run(utc("2026-11-14T17:31:00"), fetch)     # queue low: the owner hears once a day
    feed_bot(tg, state, posts).run(utc("2026-11-14T18:31:00"), fetch)
    notes = [p["text"] for p in tg.sent(OWNER) if p["text"].startswith("⚠️ Постів у черзі")]
    assert len(notes) == 2 and "допиши пости" in notes[-1]                 # 13th and 14th


def test_a_late_start_does_not_fire_two_posts_back_to_back(tmp_path):
    for n in range(1, 4):
        _write(tmp_path, f"000{n}-p.md", TEXT_POST)
    posts, tg, state = feed.load(tmp_path), FakeTG(), empty_state()
    for minute in (0, 15, 30):                                          # 22:00-22:30 Kyiv, both slots "due"
        feed_bot(tg, state, posts).run(utc(f"2026-11-13T20:{minute:02d}:00"), fetch)
    assert len(state["feed"]) == 1


def test_dated_posts_wait_then_jump_the_queue_and_go_stale(tmp_path):
    _write(tmp_path, "0001-a.md", TEXT_POST)
    _write(tmp_path, "0002-news.md", TEXT_POST.replace("rubric: prompt", "rubric: news\ndate: 2026-11-14"))
    _write(tmp_path, "0003-old.md", TEXT_POST.replace("rubric: prompt", "rubric: news\ndate: 2026-11-01"))
    posts = feed.load(tmp_path)
    assert [p.id for p in feed.ready(posts, {}, feed.date(2026, 11, 13))] == ["0001-a"]
    assert [p.id for p in feed.ready(posts, {}, feed.date(2026, 11, 14))] == ["0002-news", "0001-a"]
    assert [p.id for p in feed.stale(posts, {}, feed.date(2026, 11, 14))] == ["0003-old"]


def test_bad_posts_are_skipped_and_reported_once_a_day(tmp_path):
    _write(tmp_path, "0001-bad.md", "---\nrubric: prompt\n---\n<b>криво\n#промпт")
    _write(tmp_path, "0002-ok.md", TEXT_POST)
    posts, tg, state = feed.load(tmp_path), FakeTG(), empty_state()
    feed_bot(tg, state, posts).run(utc("2026-11-13T07:45:00"), fetch)
    feed_bot(tg, state, posts).run(utc("2026-11-13T08:00:00"), fetch)
    assert list(state["feed"]) == ["0002-ok"]
    notes = [p["text"] for p in tg.sent(OWNER) if "з помилками" in p["text"]]
    assert len(notes) == 1 and "0001-bad" in notes[0]


def test_channel_name_is_set_once_and_the_numeric_id_survives_a_new_address(tmp_path):
    _write(tmp_path, "0001-a.md", TEXT_POST)
    posts, tg, state = feed.load(tmp_path), FakeTG(), empty_state()
    real = tg.call

    def call(method, **p):
        if method == "getChat":
            tg.calls.append((method, p))
            return {"id": -100123, "title": "Old name"}
        return real(method, **p)
    tg.call = call
    profile = {"title": "ШІ без води", "description": "Опис"}
    feed_bot(tg, state, posts, profile).run(utc("2026-11-13T07:45:00"), fetch)
    feed_bot(tg, state, posts, profile).run(utc("2026-11-13T08:00:00"), fetch)
    assert [p["title"] for m, p in tg.calls if m == "setChatTitle"] == ["ШІ без води"]
    assert [p["description"] for m, p in tg.calls if m == "setChatDescription"] == ["Опис"]
    assert len([c for c in tg.calls if c[0] == "getChat"]) == 1
    assert state["channel"]["id"] == -100123 and tg.sent(-100123)          # posts go to the id, not the @address


def test_channel_name_without_the_right_tells_the_owner_once(tmp_path):
    tg, state = FakeTG(), empty_state()
    tg.fail = {"setChatTitle"}
    for minute in (0, 15):
        feed_bot(tg, state, [], {"title": "ШІ без води"}).run(utc(f"2026-11-13T08:{minute:02d}:00"), fetch)
    assert state["profile"] == ""
    assert len([p for p in tg.sent(OWNER) if "назву" in p["text"]]) == 1


def test_queue_cli(tmp_path, capsys):
    posts = tmp_path / "c" / "posts"
    _write(posts, "0001-a.md", TEXT_POST)
    _write(posts, "0002-b.md", QUIZ_POST)
    state = empty_state()
    state["feed"]["0001-a"] = {"at": "2026-11-13T07:45:00+00:00", "day": "2026-11-13"}
    save_state(tmp_path / "state.json", state)
    assert main(["queue", "--posts", str(posts)]) == 0
    assert main(["queue", "--posts", str(posts), "--state", str(tmp_path / "state.json"), "--left"]) == 0
    assert capsys.readouterr().out.strip().splitlines()[-1] == "1"
    _write(posts, "0003-bad.md", "---\nrubric: nope\n---\nx")
    assert main(["queue", "--posts", str(posts)]) == 1
    assert "0003-bad" in capsys.readouterr().out


def test_burst_fills_a_new_channel_silently_then_the_schedule_resumes(tmp_path):
    for n in range(1, 6):
        _write(tmp_path, f"000{n}-p.md", QUIZ_POST if n == 2 else TEXT_POST)
    posts, tg, state, pauses = feed.load(tmp_path), FakeTG(), empty_state(), []
    Bot(tg, state, owner=OWNER, channel=CHANNEL, log=lambda m: None, posts=posts, giveaways=False, burst=3,
        pause=pauses.append).run(utc("2026-11-13T22:30:00"), fetch)          # 00:30 Kyiv: a burst ignores the hours
    assert list(state["feed"]) == ["0001-p", "0002-p", "0003-p"] and len(pauses) == 2
    sent = [p for m, p in tg.calls if m in ("sendMessage", "sendPoll")]
    assert all(p["disable_notification"] is True for p in sent)
    feed_bot(tg, state, posts).run(utc("2026-11-14T07:45:00"), fetch)     # the burst counted for that Kyiv day
    assert len(state["feed"]) == 3
    feed_bot(tg, state, posts).run(utc("2026-11-15T07:45:00"), fetch)     # the next morning: one, with a sound
    assert list(state["feed"])[-1] == "0004-p" and tg.calls[-1][1].get("disable_notification") is None


def test_profile_photo_and_one_time_cleanup(tmp_path):
    photo = tmp_path / "avatar.png"
    photo.write_bytes(b"\x89PNG fake")
    tg, state, uploads = FakeTG(), empty_state(), []
    tg.upload = lambda method, field, path, **p: uploads.append((method, field, str(path), p)) or True
    profile = {"title": "ШІ без води", "photo": str(photo), "delete_messages": [2, 3, 4]}
    for minute in (0, 15):
        feed_bot(tg, state, [], profile).run(utc(f"2026-11-13T08:{minute:02d}:00"), fetch)
    assert uploads == [("setChatPhoto", "photo", str(photo), {"chat_id": CHANNEL})]
    assert [p["message_ids"] for m, p in tg.calls if m == "deleteMessages"] == [[2, 3, 4]]
    photo.write_bytes(b"\x89PNG new")                                     # a new picture is uploaded again
    feed_bot(tg, state, [], profile).run(utc("2026-11-13T08:30:00"), fetch)
    assert len(uploads) == 2


def test_cleanup_falls_back_to_one_by_one(tmp_path):
    tg, state = FakeTG(), empty_state()
    tg.fail = {"deleteMessages"}
    feed_bot(tg, state, [], {"delete_messages": [2, 3]}).run(utc("2026-11-13T08:00:00"), fetch)
    assert [p["message_id"] for m, p in tg.calls if m == "deleteMessage"] == [2, 3] and state["deleted"] == [2, 3]


def test_with_giveaways_off_old_drafts_lose_their_buttons(tmp_path):
    tg, state = FakeTG(), empty_state()
    run(tg, state)                                                        # giveaway drafts sent to the owner
    assert state["drafts"]
    tg.press("p:1")
    feed_bot(tg, state, []).run(NOW, fetch)
    assert state["drafts"] == {} and not tg.sent(CHANNEL)
    cleared = [p for m, p in tg.calls if m == "editMessageReplyMarkup"]
    assert len(cleared) >= len(tg.drafts())


def test_upload_sends_the_file_as_multipart():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["type"] = request.headers["content-type"]
        seen["body"] = request.content
        return httpx.Response(200, json={"ok": True, "result": True})
    tg = Telegram("1:x", httpx.Client(transport=httpx.MockTransport(handler)))
    path = Path(__file__).parent / "conftest.py"
    assert tg.upload("setChatPhoto", "photo", path, chat_id=-100) is True
    assert seen["type"].startswith("multipart/form-data") and b'name="chat_id"' in seen["body"]
    assert b'name="photo"; filename="conftest.py"' in seen["body"]


def test_a_new_channel_waits_for_its_first_burst(tmp_path):
    for n in range(1, 4):
        _write(tmp_path, f"000{n}-p.md", TEXT_POST)
    posts, tg, state = feed.load(tmp_path), FakeTG(), empty_state()
    profile = {"wait_for_burst": True}
    feed_bot(tg, state, posts, profile).run(utc("2026-11-13T07:45:00"), fetch)
    assert state["feed"] == {}
    Bot(tg, state, owner=OWNER, channel=CHANNEL, log=lambda m: None, posts=posts, giveaways=False, burst=2,
        profile=profile, pause=lambda s: None).run(utc("2026-11-13T19:00:00"), fetch)
    assert len(state["feed"]) == 2 and state["burst_at"]
    feed_bot(tg, state, posts, profile).run(utc("2026-11-14T07:45:00"), fetch)
    assert len(state["feed"]) == 3


# ---------------------------------------------------------------- competitor study (t.me/s previews)
from tg_channel import research


def test_preview_page_is_parsed_into_channel_and_posts():
    page = (Path(__file__).parent / "fixtures" / "tme_preview.html").read_text(encoding="utf-8")
    ch, posts = research.parse(page)
    assert ch["title"] == "Штучка Інтелект" and ch["counters"]["subscribers"] == 11700
    assert ch["description"] == "Про ШІ просто\nщодня"
    a, b = posts
    assert a["id"] == "shtuchka_intelekt/1233" and a["views"] == 12300 and a["reactions"] == 1245
    assert a["media"] == ["photo"] and a["text"].startswith("10 промптів для резюме\nЗберігай & ділися тут")
    assert a["hashtags"] == ["#промпти"] and a["date"] == "2026-11-09T07:15:00+00:00"
    assert b["forwarded"] and b["reply"] and b["media"] == ["poll"] and b["views"] == 948 and b["text"] == ""
    assert research.number("1.2M") == 1_200_000 and research.number("x") is None


def test_study_pages_back_and_summarises(tmp_path):
    page = (Path(__file__).parent / "fixtures" / "tme_preview.html").read_text(encoding="utf-8")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if "before=" in str(request.url):
            return httpx.Response(200, text=page)            # the same posts again: paging stops
        if "nochannel" in str(request.url):
            return httpx.Response(200, text="<html><body>nothing</body></html>")
        return httpx.Response(200, text=page)
    http = httpx.Client(transport=httpx.MockTransport(handler))
    (tmp_path / "c.txt").write_text("# A\nshtuchka_intelekt  # comment\n@nochannel\nbad name\n", encoding="utf-8")
    names = research.read_channels(tmp_path / "c.txt")
    assert names == ["shtuchka_intelekt", "nochannel"]
    result = research.study(names, 3, tmp_path / "out", http=http, pause=lambda s: None, log=lambda m: None)
    s = result["channels"][0]
    assert s["subscribers"] == 11700 and s["posts"] == 2 and s["median_views"] == 12300
    assert s["by_kind"]["photo"]["n"] == 1 and s["top_posts"][0]["views"] == 12300
    assert result["channels"][1] == {"name": "nochannel", "posts": 0, "found_via": "seed"}
    assert any("before=1233" in u for u in seen)
    data = json.loads((tmp_path / "out" / "channels.json").read_text(encoding="utf-8"))
    assert "no posts" in data["channels"][1]["error"]


def test_snowball_follows_channels_the_seeds_link_to(tmp_path):
    def page(name, links):
        body = " ".join(f'<a href="https://t.me/{n}">x</a>' for n in links)
        return (f'<div class="tgme_widget_message js-widget_message" data-post="{name}/5"><div '
                f'class="tgme_widget_message_text js-message_text">пост {body} @{links[0]}</div>'
                f'<span class="tgme_widget_message_views">10</span></div>')
    pages = {"aaaa": page("aaaa", ["popular", "single"]), "bbbb": page("bbbb", ["popular", "aaaa"]),
             "popular": page("popular", ["zzzz"])}

    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, text=pages.get(name, ""))
    http = httpx.Client(transport=httpx.MockTransport(handler))
    result = research.study(["aaaa", "bbbb"], 1, tmp_path, http=http, pause=lambda s: None, log=lambda m: None,
                            snowball=5)
    names = [c["name"] for c in result["channels"]]
    assert names == ["aaaa", "bbbb", "popular"]                         # «single» is linked by one channel only
    assert result["channels"][2]["found_via"] == "linked by 2 studied channels"


def test_author_voice_hints_are_caught_outside_prompts_and_quotes(tmp_path):
    body = ("---\nrubric: prompt\n---\n<b>Тест</b>\n\nЯ прогнав його на прикладі, і в мене теж вийшло.\n"
            "<pre>Задай питання, на яке я відповів найслабше</pre>\n<blockquote>Я підготувала звіт</blockquote>\n"
            "🧪 Прогін: перевіряю на трьох прикладах.\n#промпт\n")
    _write(tmp_path, "0001-a.md", body)
    problems = " | ".join(feed.load(tmp_path)[0].problems)
    assert "«я прогнав»" in problems and "«в мене теж»" in problems
    assert "відповів" not in problems and "підготувала" not in problems and "перевіряю" not in problems


def test_rename_and_photo_notices_in_the_channel_are_deleted():
    tg, state = FakeTG(), empty_state()
    state["channel"] = {"ref": CHANNEL, "id": -100123}
    tg.updates += [
        {"update_id": 1, "channel_post": {"message_id": 7, "chat": {"id": -100123}, "new_chat_title": "Нова назва"}},
        {"update_id": 2, "channel_post": {"message_id": 8, "chat": {"id": -100123}, "new_chat_photo": [{}]}},
        {"update_id": 3, "channel_post": {"message_id": 9, "chat": {"id": -100123}, "text": "звичайний пост"}},
        {"update_id": 4, "channel_post": {"message_id": 3, "chat": {"id": -100999}, "new_chat_title": "чужий"}},
    ]
    feed_bot(tg, state, []).run(utc("2026-11-13T08:00:00"), fetch)
    assert [(p["chat_id"], p["message_id"]) for m, p in tg.calls if m == "deleteMessage"] == [(-100123, 7), (-100123, 8)]
    assert state["offset"] == 5


def test_study_limits_title_prompt_length_quiz_spacing_and_pin(tmp_path):
    long_prompt = "x" * 360
    _write(tmp_path, "0001-a.md", f"---\nrubric: prompt\n---\n<b>Промпт дня: резюме</b>\n<pre>{long_prompt}</pre>\n#промпт\n")
    _write(tmp_path, "0002-b.md", "---\nrubric: myth\n---\n<b>Міф</b>\n" + "слово " * 110 + "\n#міф\n")
    _write(tmp_path, "0003-c.md", "---\nrubric: career\n---\n<b>" + "Дуже довгий заголовок " * 4 + "</b>\nтекст\n#робота\n")
    _write(tmp_path, "0004-q.md", QUIZ_POST)
    _write(tmp_path, "0005-q.md", QUIZ_POST)
    _write(tmp_path, "0006-pin.md", "---\nrubric: intro\npin: yes\n---\n<b>Що тут є</b>\n#навігація\n")
    posts = {p.id: p for p in feed.load(tmp_path)}
    a = " | ".join(posts["0001-a"].problems)
    assert "Промпт дня" in a and "prompt too long" in a
    assert any("at most 600 for myth" in x for x in posts["0002-b"].problems)
    assert any("title line too long" in x for x in posts["0003-c"].problems)
    assert feed.queue_problems(list(posts.values())) == ["0005-q: a second quiz within 14 posts (after 0004-q)"]
    assert posts["0006-pin"].pin and posts["0006-pin"].problems == []
    tg, state = FakeTG(), empty_state()
    Bot(tg, state, owner=OWNER, channel=CHANNEL, log=lambda m: None, posts=[posts["0006-pin"]], giveaways=False,
        burst=1, pause=lambda s: None).run(utc("2026-11-13T08:00:00"), fetch)
    pins = [p for m, p in tg.calls if m == "pinChatMessage"]
    assert len(pins) == 1 and pins[0]["message_id"] == state["feed"]["0006-pin"]["message_id"]
