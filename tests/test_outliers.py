from datetime import timedelta

import pytest

from niche_core.enrich import enrich, select_outliers
from niche_core.models import Channel, Video
from niche_core.service import language_matches

from .fakes import FIXED_NOW

HITS = {"shorts": 10_000, "long": 10_000}


def _ch(cid, subs, views=1_000_000, videos=100, created_days_ago=2000, hidden=False):
    return Channel(cid, cid, None if hidden else subs, hidden, views, videos,
                   FIXED_NOW - timedelta(days=created_days_ago))


def _v(vid, cid, views, fmt="long", age_days=5, lang="en"):
    return Video(vid, cid, cid, f"title {vid}", FIXED_NOW - timedelta(days=age_days),
                 60 if fmt == "short" else 900, fmt, views, default_audio_language=lang)


def _run(videos, channels, **kw):
    e = enrich(videos, {c.channel_id: c for c in channels}, now=FIXED_NOW, hit_views=HITS)
    return select_outliers(e, **{"min_outlier_score": 10, "max_channel_subs": 50_000, **kw})


def test_sub_outlier_score_and_threshold():
    chans = [_ch("small", 1_000), _ch("mid", 20_000)]
    kept, rejected = _run([_v("a", "small", 50_000), _v("b", "mid", 100_000)], chans)
    assert [e.video.video_id for e in kept] == ["a"]  # 50x vs 5x
    assert kept[0].sub_outlier_score == 50
    assert rejected["below_threshold"] == 1


def test_big_and_hidden_channels_rejected():
    chans = [_ch("big", 200_000), _ch("hid", 0, hidden=True)]
    kept, rejected = _run([_v("a", "big", 5_000_000), _v("b", "hid", 5_000_000)], chans)
    assert kept == []
    assert rejected["channel_too_big"] == 1 and rejected["subs_hidden"] == 1


def test_sub_floor_prevents_division_explosion():
    e = enrich([_v("a", "zero", 5_000)], {"zero": _ch("zero", 0)}, now=FIXED_NOW, hit_views=HITS, sub_floor=100)
    assert e[0].sub_outlier_score == 50


def test_channel_relative_score():
    # channel average = 1,000,000 / 100 = 10,000 views per video
    e = enrich([_v("a", "c", 80_000)], {"c": _ch("c", 5_000)}, now=FIXED_NOW, hit_views=HITS)[0]
    assert e.channel_relative_score == 8
    assert e.sub_outlier_score == 16


def test_channel_relative_none_when_no_video_count():
    e = enrich([_v("a", "c", 80_000)], {"c": _ch("c", 5_000, videos=0)}, now=FIXED_NOW, hit_views=HITS)[0]
    assert e.channel_relative_score is None
    assert e.primary_metric == "subs"


def test_shorts_prefer_channel_relative_long_prefers_subs():
    chans = {"c": _ch("c", 5_000)}
    short, long_ = enrich([_v("s", "c", 80_000, "short"), _v("l", "c", 80_000)], chans, now=FIXED_NOW, hit_views=HITS)
    assert short.primary_metric == "channel_relative" and short.primary_score == 8
    assert long_.primary_metric == "subs" and long_.primary_score == 16


def test_metric_choice_changes_selection():
    chans = [_ch("c", 5_000)]  # subs score 16, channel-relative 8
    vids = [_v("a", "c", 80_000)]
    assert len(_run(vids, chans, metric="subs")[0]) == 1
    assert len(_run(vids, chans, metric="channel_relative")[0]) == 0
    assert len(_run(vids, chans, metric="either")[0]) == 1
    with pytest.raises(ValueError):
        _run(vids, chans, metric="nope")


def test_hits_and_new_channels():
    chans = {"new": _ch("new", 900, created_days_ago=40), "old": _ch("old", 900, created_days_ago=3000)}
    fresh, old = enrich(
        [_v("a", "new", 12_000, age_days=6), _v("b", "old", 12_000, age_days=25)], chans, now=FIXED_NOW, hit_views=HITS
    )
    assert fresh.is_new_channel and fresh.hit_within_14d
    assert not old.is_new_channel and old.is_hit and not old.hit_within_14d


def test_per_format_hit_threshold():
    e = enrich([_v("s", "c", 15_000, "short")], {"c": _ch("c", 100)}, now=FIXED_NOW,
               hit_views={"shorts": 20_000, "long": 10_000})[0]
    assert not e.is_hit


@pytest.mark.parametrize("audio,wanted,ok", [(None, "en", True), ("en-US", "en", True), ("ru", "en", False), ("de", "", True)])
def test_language_matches(audio, wanted, ok):
    assert language_matches(audio, wanted) is ok


def test_find_outliers_end_to_end(service, fake):
    out = service.find_outliers("lighthouse lore", format="both", min_outlier_score=5)
    ids = [o["video_id"] for o in out["outliers"]]
    # Tiny Lore: 4,200 subs, avg 30k/video. Short 154k -> 36.7x subs; long 88k -> 21x subs.
    # Ranked by primary score: long 20.95x subs, short 5.13x channel average.
    assert ids == ["vLongLore001", "vShortVert01"]
    short = next(o for o in out["outliers"] if o["video_id"] == "vShortVert01")
    assert short["primary_metric"] == "channel_relative"
    assert short["is_new_channel"] is True and short["hit_within_14d"] is True
    assert out["excluded"]["short_longform"] == 1
    assert 0 < out["quota"]["actual"] <= out["quota"]["estimated"]


def test_find_outliers_language_filter(service, fake):
    fake.videos["vShortVert01"]["snippet"]["defaultAudioLanguage"] = "ru"
    out = service.find_outliers("lighthouse lore", format="shorts", min_outlier_score=5)
    assert out["count"] == 0 and out["excluded"]["other_language"] == 1
