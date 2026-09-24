import httpx
import pytest

from niche_core.cache import Store
from niche_core.quota import QuotaTracker
from niche_core.youtube_client import MissingAPIKeyError, QuotaExceededError, YouTubeAPIError, YouTubeClient

from .conftest import Clock
from .fakes import FakeYouTube, api_error


def _client(fake, limit=10_000):
    quota = QuotaTracker(Store(":memory:", clock=Clock()), daily_limit=limit)
    return YouTubeClient("SECRET-KEY", quota, http=fake.http_client(), sleep=lambda s: None), quota


def _video_item(i):
    return {"id": f"v{i:03d}", "snippet": {"channelId": "c"}, "contentDetails": {"duration": "PT1M"}, "statistics": {}}


def test_missing_key():
    with pytest.raises(MissingAPIKeyError):
        YouTubeClient(None, QuotaTracker(Store(":memory:")))


def test_videos_batched_by_50_and_metered():
    items = [_video_item(i) for i in range(120)]
    fake = FakeYouTube(items, [], {})
    client, quota = _client(fake)
    got = client.list_videos([i["id"] for i in items])
    assert len(got) == 120
    assert fake.count("videos") == 3
    assert quota.used_today() == 3
    params = fake.calls[0][1]
    assert "player" in params["part"] and params["maxHeight"] == "720"


def test_search_pagination_regions_and_cost():
    fake = FakeYouTube([], [], {"long": [f"id{i}" for i in range(80)]})
    client, quota = _client(fake)
    ids = client.search_video_ids("lore", max_results=75, video_duration="long", region_code="GB", relevance_language="en")
    assert len(ids) == 75
    assert fake.count("search") == 2
    assert quota.used_today() == 200
    assert fake.calls[0][1]["regionCode"] == "GB" and fake.calls[0][1]["relevanceLanguage"] == "en"


def test_quota_exceeded_is_raised_and_not_charged():
    fake = FakeYouTube([], [], {})
    fake.fail_with["search"].append(api_error(403, "quotaExceeded", "The request cannot be completed"))
    client, quota = _client(fake)
    with pytest.raises(QuotaExceededError):
        client.search_video_ids("x")
    assert quota.used_today() == 0


def test_local_guard_blocks_before_calling():
    fake = FakeYouTube([], [], {})
    client, quota = _client(fake, limit=99)
    with pytest.raises(QuotaExceededError):
        client.search_video_ids("x")
    assert fake.calls == []


def test_retries_backend_errors_then_succeeds():
    fake = FakeYouTube([_video_item(1)], [], {})
    fake.fail_with["videos"] += [httpx.Response(503, text="unavailable"), api_error(403, "rateLimitExceeded")]
    client, quota = _client(fake)
    assert len(client.list_videos(["v001"])) == 1
    assert fake.count("videos") == 3
    assert quota.used_today() == 3  # failed attempts are charged too


def test_error_message_never_contains_key():
    fake = FakeYouTube([], [], {})
    fake.fail_with["channels"].append(api_error(400, "keyInvalid", "API key SECRET-KEY not valid"))
    client, _ = _client(fake)
    with pytest.raises(YouTubeAPIError) as exc:
        client.list_channels(["UC1"])
    assert "SECRET-KEY" not in str(exc.value)
    assert exc.value.reason == "keyInvalid"
