"""Regression tests for the independent code review findings."""

import logging
import threading

import httpx
import pytest

from niche_core.cache import Store
from niche_core.patterns import _same_stem, expand_candidates, title_patterns
from niche_core.quota import QuotaTracker
from niche_core.youtube_client import QuotaExceededError, YouTubeAPIError, YouTubeClient

from .conftest import Clock
from .fakes import FakeYouTube, api_error


def _client(fake, limit=10_000):
    q = QuotaTracker(Store(":memory:", clock=Clock()), daily_limit=limit)
    return YouTubeClient("SECRET-KEY", q, http=fake.http_client(), sleep=lambda s: None), q


def test_key_sent_in_header_not_url_and_httpx_quiet():
    seen = {}

    def handler(req):
        seen["url"], seen["hdr"] = str(req.url), req.headers.get("x-goog-api-key")
        return httpx.Response(200, json={"items": []})

    q = QuotaTracker(Store(":memory:", clock=Clock()))
    c = YouTubeClient("SECRET-KEY", q, http=httpx.Client(transport=httpx.MockTransport(handler), base_url="https://x"))
    c.list_channels(["UC1"])
    assert "SECRET-KEY" not in seen["url"] and seen["hdr"] == "SECRET-KEY"
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING


def test_short_pages_with_token_do_not_overspend():
    class ShortPages(FakeYouTube):
        def handler(self, request):
            self.calls.append(("search", dict(request.url.params)))
            return httpx.Response(200, json={"items": [{"id": {"videoId": f"v{len(self.calls)}{i}"}} for i in range(47)],
                                             "nextPageToken": "more"})
    fake = ShortPages([], [], {})
    client, q = _client(fake)
    ids = client.search_video_ids("x", max_results=50)
    assert len(ids) == 47 and q.used_today() == 100


def test_no_progress_page_stops_pagination():
    class Dupes(FakeYouTube):
        def handler(self, request):
            self.calls.append(("search", {}))
            return httpx.Response(200, json={"items": [{"id": {"videoId": "same"}}], "nextPageToken": "t"})
    fake = Dupes([], [], {})
    client, q = _client(fake)
    client.search_video_ids("x", max_results=500)
    assert len(fake.calls) == 2  # second page added nothing -> stop


def test_retries_rechecked_against_guard():
    fake = FakeYouTube([], [], {})
    fake.fail_with["search"] += [httpx.Response(500, text="x")] * 4
    client, q = _client(fake, limit=250)
    with pytest.raises(QuotaExceededError):
        client.search_video_ids("x")
    assert q.used_today() <= 250


def test_malformed_json_is_api_error():
    fake = FakeYouTube([], [], {})
    fake.fail_with["channels"].append(httpx.Response(200, text="not json"))
    client, _ = _client(fake)
    with pytest.raises(YouTubeAPIError):
        client.list_channels(["UC1"])


def test_channels_quota_error_keeps_videos(service, fake):
    fake.fail_with["channels"].append(api_error(403, "quotaExceeded"))
    out = service.find_outliers("lighthouse lore", format="both", min_outlier_score=1)
    assert out["partial"] is True
    assert out["scanned"] > 0  # videos fetched before the failure are still analysed


def test_store_usable_from_other_thread():
    store = Store(":memory:")
    errors = []
    t = threading.Thread(target=lambda: errors.append(store.counts()))
    t.start(); t.join()
    assert isinstance(errors[0], dict)


def test_small_window_widens_sample(service):
    groups = service.analysis_specs("x", "shorts", 5, 50, None, None)
    s = groups["sample"][0]
    assert s.published_within_days > s.published_before_days


def test_invalid_window_rejected(service):
    with pytest.raises(ValueError):
        service.search_niche("x", "shorts", published_within_days=0)
    with pytest.raises(ValueError):
        service.search_niche("x", "shorts", max_results=-5)


def test_seed_matching_is_token_based():
    assert _same_stem("rome", "roman") and _same_stem("romans", "roman")
    assert not _same_stem("oman", "roman") and not _same_stem("chain", "ai")
    vids = [(f"c{i}", "Chain reaction experiments", ["chain reaction"], 5) for i in range(3)]
    assert "chain reaction" in {d["phrase"] for d in expand_candidates(vids, seed="ai")}


def test_exclusive_pattern_gets_capped_lift():
    pats = {p["pattern"]: p for p in title_patterns(["Why is this?"], ["plain title"])}
    assert pats["question"]["lift"] == 3.0
