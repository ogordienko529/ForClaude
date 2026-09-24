import pytest

from niche_core.service import QuotaBudgetError

from .fakes import api_error


def test_search_niche_shorts_excludes_horizontal_and_live(service, fake):
    out = service.search_niche("lighthouse lore", format="shorts")
    assert [v["video_id"] for v in out["videos"]] == ["vShortVert01"]
    assert out["excluded"]["short_longform"] == 1 and out["excluded"]["live"] == 1
    assert out["videos"][0]["url"].startswith("https://www.youtube.com/shorts/")
    assert out["quota"]["actual"] == 101  # 1 search + 1 videos.list
    assert out["params"]["region_code"] == "US" and out["params"]["relevance_language"] == "en"


def test_long_uses_medium_and_long_buckets(service, fake):
    dry = service.search_niche("lighthouse lore", format="long", dry_run=True)
    assert dry["quota_estimate"]["search_calls"] == 2
    assert dry["quota"]["actual"] == 0 and fake.calls == []
    out = service.search_niche("lighthouse lore", format="long")
    assert {c[1]["videoDuration"] for c in fake.calls if c[0] == "search"} == {"medium", "long"}
    assert [v["video_id"] for v in out["videos"]] == ["vLongLore001"]
    assert out["videos"][0]["likes"] == 4100 and out["videos"][0]["comments"] is None


def test_second_run_is_served_from_cache(service, fake):
    service.search_niche("lighthouse lore", format="both")
    before = len(fake.calls)
    again = service.search_niche("lighthouse lore", format="both")
    assert len(fake.calls) == before
    assert again["quota"]["actual"] == 0 and again["quota_estimate"]["total"] == 0


def test_region_change_misses_cache(service, fake):
    service.search_niche("lighthouse lore", format="shorts")
    est = service.search_niche("lighthouse lore", format="shorts", region_code="GB", dry_run=True)
    assert est["quota_estimate"]["search"] == 100


def test_max_units_guard(service, fake):
    with pytest.raises(QuotaBudgetError):
        service.search_niche("lighthouse lore", format="both", max_units=150)
    assert fake.calls == []


def test_quota_exhaustion_returns_partial(service, fake):
    fake.fail_with["videos"].append(api_error(403, "quotaExceeded"))
    out = service.search_niche("lighthouse lore", format="shorts")
    assert out["partial"] is True and out["videos"] == []
    assert any("quota" in e.lower() for e in out["errors"])


def test_channel_stats_hidden_subs(service, fake):
    out = service.get_channel_stats(["UCsmall00001", "UCsmall00002", "UCmissing000"])
    assert out["not_found"] == ["UCmissing000"]
    by_id = {c["channel_id"]: c for c in out["channels"]}
    assert by_id["UCsmall00002"]["subscriber_count"] is None
    assert by_id["UCsmall00001"]["avg_views_per_video"] == 30000.0
    assert out["hidden_subscriber_counts"] == 1
    assert out["quota"]["estimated"] == 1 and out["quota"]["actual"] == 1


def test_quota_status(service):
    service.search_niche("lighthouse lore", format="shorts")
    status = service.quota_status()
    assert status["used_today"] == 101
    assert status["by_endpoint"]["search"]["units"] == 100


def test_missing_key_propagates_instead_of_silent_empty_result(config, clock):
    from niche_core.cache import Store
    from niche_core.service import NicheService
    from niche_core.youtube_client import MissingAPIKeyError

    svc = NicheService(config, store=Store(":memory:", clock=clock), clock=clock)
    import os
    old = os.environ.pop("YOUTUBE_API_KEY", None)
    try:
        with pytest.raises(MissingAPIKeyError):
            svc.search_niche("anything", format="shorts")
    finally:
        if old is not None:
            os.environ["YOUTUBE_API_KEY"] = old


def test_search_error_falls_back_to_expired_cache(service, fake, clock):
    from datetime import timedelta
    service.search_niche("lighthouse lore", format="shorts")
    clock.now = clock.now + timedelta(hours=30)  # search + videos now stale
    fake.fail_with["search"].append(api_error(400, "invalidSearchFilter"))
    out = service.search_niche("lighthouse lore", format="shorts")
    assert [v["video_id"] for v in out["videos"]] == ["vShortVert01"]
    assert out["errors"]
