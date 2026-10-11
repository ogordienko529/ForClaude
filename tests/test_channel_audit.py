"""Channel audit: resolving the channel, uploads, comments, month-by-month and title comparisons (no network)."""

from datetime import datetime, timezone

import httpx
import pytest

from niche_core import channel_audit as ca
from niche_core.cache import Store
from niche_core.config import load_config
from niche_core.quota import QuotaTracker
from niche_core.service import NicheService
from niche_core.youtube_client import YouTubeClient

NOW = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)
CID = "UCGrPib_Y6DpH-TvNxbQ7eGw"


def _videos():
    vids = []
    for i in range(24):
        hit = i < 6
        vids.append({"id": f"v{i:02d}", "snippet": {
            "publishedAt": f"2026-08-{1 + i:02d}T10:00:00Z",
            "title": ("How to find the Tiny Anomaly? 🩷 update" if hit else f"Day {i} in the hospital"),
            "description": "Music: generated." if i == 7 else "", "tags": []},
            "contentDetails": {"duration": "PT22S" if hit else "PT45S"},
            "statistics": {"viewCount": str(20000 - i * 100 if hit else 300 + i), "likeCount": "100" if hit else "2",
                           "commentCount": "5"}})
    vids.append({"id": "fresh1", "snippet": {"publishedAt": "2026-10-11T02:00:00Z", "title": "3 Sniper Kills 🎯",
                 "description": "", "tags": []}, "contentDetails": {"duration": "PT15S"},
                 "statistics": {"viewCount": "800", "likeCount": "4", "commentCount": "1"}})
    return vids


class Fake:
    def __init__(self):
        self.videos = {v["id"]: v for v in _videos()}
        self.calls = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        ep = request.url.path.rsplit("/", 1)[-1]
        q = dict(request.url.params)
        self.calls.append((ep, q))
        if ep == "channels":
            if q.get("forHandle") not in (None, "@hartyidi") or q.get("id") not in (None, CID):
                return httpx.Response(200, json={"items": []})
            return httpx.Response(200, json={"items": [{"id": CID, "snippet": {"title": "HartyiDi", "customUrl": "@hartyidi",
                                                                               "publishedAt": "2017-04-25T00:00:00Z"},
                                                        "statistics": {"subscriberCount": "585", "videoCount": "25",
                                                                       "viewCount": "210653"},
                                                        "contentDetails": {"relatedPlaylists": {"uploads": "UUx"}}}]})
        if ep == "playlistItems":
            ids = ["fresh1"] + [f"v{i:02d}" for i in range(23, -1, -1)]
            start = int(q.get("pageToken", 0) or 0)
            body = {"items": [{"contentDetails": {"videoId": i}} for i in ids[start:start + 20]]}
            if start + 20 < len(ids):
                body["nextPageToken"] = str(start + 20)
            return httpx.Response(200, json=body)
        if ep == "videos":
            return httpx.Response(200, json={"items": [self.videos[i] for i in q["id"].split(",") if i in self.videos]})
        if ep == "commentThreads":
            if q["videoId"] == "v01":  # comments turned off
                return httpx.Response(403, json={"error": {"code": 403, "message": "off", "errors": [{"reason": "commentsDisabled"}]}})
            items = [{"snippet": {"topLevelComment": {"snippet": {"authorDisplayName": "@kid", "authorChannelId": {"value": "UCkid"},
                                                                  "textDisplay": t, "likeCount": 3, "publishedAt": "2026-08-02"}}}}
                     for t in ("I found it at shift 3", "AI voice >:(", "liar\nclickbait")]
            items.append({"snippet": {"topLevelComment": {"snippet": {"authorDisplayName": "@hartyidi", "authorChannelId": {"value": CID},
                                                                      "textDisplay": "thanks!", "likeCount": 9}}}})
            return httpx.Response(200, json={"items": items})
        return httpx.Response(404, json={"error": {"code": 404, "message": "?", "errors": [{"reason": "notFound"}]}})


@pytest.fixture
def svc(tmp_path):
    fake = Fake()
    config = load_config(overrides={"paths": {"db_path": ":memory:", "reports_dir": str(tmp_path / "reports")}})
    store = Store(":memory:", clock=lambda: NOW)
    quota = QuotaTracker(store, config.daily_quota)
    http = httpx.Client(transport=httpx.MockTransport(fake.handler), base_url="https://www.googleapis.com/youtube/v3")
    client = YouTubeClient("TEST-KEY", quota, http=http, sleep=lambda s: None)
    return NicheService(config, store=store, client=client, clock=lambda: NOW), fake


@pytest.mark.parametrize("text,expected", [
    (CID, (CID, None)),
    (f"https://studio.youtube.com/channel/{CID}/videos/short?filter=%5B%5D", (CID, None)),
    ("https://www.youtube.com/@hartyidi/shorts", (None, "@hartyidi")),
    ("@hartyidi", (None, "@hartyidi")),
    ("hartyidi", (None, "@hartyidi")),
])
def test_parse_channel(text, expected):
    assert ca.parse_channel(text) == expected


def test_audit_report(svc):
    service, fake = svc
    out = service.channel_audit("https://www.youtube.com/@hartyidi", comment_videos=4, export=True)
    r = out["report"]
    assert r["channel"]["id"] == CID and r["analysed"] == {"videos": 25, "settled": 24, "fresh": 1, "comments": 9}
    assert [v["id"] for v in r["fresh"]] == ["fresh1"]  # too young to compare
    assert r["top"][0]["id"] == "v00" and all(v["id"] != "fresh1" for v in r["top"] + r["bottom"])
    features = {f["feature"]: f for f in r["title_features"]}
    assert features["how to / guide / tips"]["top"] == 6 and features["how to / guide / tips"]["bottom"] == 0
    assert all(c["author_channel"] != CID for c in r["comments"])  # the creator's replies are not audience
    themes = r["comment_themes"]
    assert len(themes["ai"]) == 3 and len(themes["clickbait"]) == 3
    assert r["music_in_descriptions"] == {"generated": 1}
    md = out["markdown"]
    assert "| 2026-08 | 24 |" in md and "Too fresh to judge" in md and "how to / guide / tips | 6 | 0 ←" in md
    assert '"liar clickbait"' in md  # multi-line comments stay on one line
    # 1 channels + 2 playlist pages + 1 videos + 4 commentThreads (the refused one is charged too)
    assert out["quota"]["actual"] == 8 and ca.estimate(100, 4) >= 8
    assert (service.config.reports_dir / f"channel_{CID}.md").exists()


def test_dry_run_and_unknown_channel(svc):
    service, fake = svc
    out = service.channel_audit("@hartyidi", dry_run=True)
    assert out["quota"]["actual"] == 0 and not fake.calls
    with pytest.raises(ValueError, match="channel not found"):
        service.channel_audit("@somebodyelse")
