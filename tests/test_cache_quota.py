from datetime import datetime, timedelta, timezone

import pytest

from niche_core.cache import Store, search_cache_key
from niche_core.config import ConfigError, load_config
from niche_core.models import Channel, Video
from niche_core.quota import QuotaTracker, estimate_list_calls

from .conftest import Clock
from .fakes import FIXED_NOW, load_items


def _video(vid="v1", fetched=FIXED_NOW):
    item = next(i for i in load_items()["videos"] if i["id"] == "vShortVert01")
    return Video.from_api({**item, "id": vid}, fetched_at=fetched)


def test_search_key_includes_region_and_language():
    base = {"videoDuration": "short", "regionCode": "US", "relevanceLanguage": "en"}
    k1 = search_cache_key("Lore  Videos", base)
    assert k1 == search_cache_key("lore videos", dict(base))
    assert k1 != search_cache_key("lore videos", {**base, "regionCode": "GB"})
    assert k1 != search_cache_key("lore videos", {**base, "relevanceLanguage": "de"})


def test_video_ttl():
    clock = Clock()
    store = Store(":memory:", clock=clock)
    store.upsert_videos([_video()])
    assert "v1" in store.get_videos(["v1"], ttl_hours=24)
    clock.now = FIXED_NOW + timedelta(hours=25)
    assert store.get_videos(["v1"], ttl_hours=24) == {}
    assert "v1" in store.get_videos(["v1"])  # stale read still possible


def test_hidden_counts_roundtrip_as_none():
    store = Store(":memory:", clock=Clock())
    items = load_items()
    v = Video.from_api(items["videos"][1])  # likes hidden
    c = Channel.from_api(items["channels"][1])  # subs hidden
    store.upsert_videos([v])
    store.upsert_channels([c])
    assert store.get_videos([v.video_id])[v.video_id].like_count is None
    got = store.get_channels([c.channel_id])[c.channel_id]
    assert got.subscriber_count is None and got.subs_hidden
    assert got.avg_views_per_video is None  # videoCount 0


def test_snapshots_accumulate():
    clock = Clock()
    store = Store(":memory:", clock=clock)
    store.upsert_videos([_video()])
    clock.now = FIXED_NOW + timedelta(hours=30)
    store.upsert_videos([_video(fetched=clock.now)])
    assert len(store.get_snapshots("v1")) == 2


def test_purge_deletes_rows_older_than_retention():
    clock = Clock()
    store = Store(":memory:", clock=clock)
    old = FIXED_NOW - timedelta(days=31)
    store.upsert_videos([_video("old", fetched=old), _video("new")])
    store.upsert_channels([Channel.from_api(load_items()["channels"][0], fetched_at=old)])
    store.put_search("k", "q", {}, ["old"])
    clock.now = FIXED_NOW + timedelta(days=31)  # the search is now 31 days old too
    deleted = store.purge(30)
    assert deleted["videos"] == 2 and deleted["video_snapshots"] == 2
    assert deleted["channels"] == 1 and deleted["searches"] == 1

    clock.now = FIXED_NOW
    store.upsert_videos([_video("fresh")])
    assert store.purge(30)["videos"] == 0


def test_retention_cannot_exceed_30_days():
    with pytest.raises(ConfigError):
        load_config(overrides={"cache": {"retention_days": 45}})
    assert load_config(overrides={"cache": {"retention_days": 7}}).retention_days == 7


def test_quota_day_is_pacific():
    # 06:00 UTC on Sep 24 is still Sep 23 in Los Angeles (PDT, UTC-7).
    clock = Clock(datetime(2026, 9, 24, 6, 0, tzinfo=timezone.utc))
    q = QuotaTracker(Store(":memory:", clock=clock), daily_limit=10_000)
    q.record("search", 100)
    assert q.pt_date() == "2026-09-23"
    assert q.used_today() == 100
    clock.now = datetime(2026, 9, 24, 8, 0, tzinfo=timezone.utc)  # 01:00 PDT Sep 24: new day
    assert q.used_today() == 0
    assert q.remaining() == 10_000


def test_estimate_list_calls():
    assert estimate_list_calls(0) == 0
    assert estimate_list_calls(1) == 1
    assert estimate_list_calls(50) == 1
    assert estimate_list_calls(51) == 2
