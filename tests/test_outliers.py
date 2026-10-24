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


def test_analyze_niche_end_to_end(service, fake, tmp_path):
    out = service.analyze_niche("lighthouse lore", format="both", export=True)
    assert set(out["formats"]) == {"shorts", "long"}
    assert out["best_format"] in out["formats"]
    assert out["low_confidence"] is True  # fixture has only a handful of videos
    searches = [c[1] for c in fake.calls if c[0] == "search"]
    assert {s["order"] for s in searches} == {"viewCount", "date"}
    assert all("publishedBefore" in s for s in searches if s["order"] == "date")
    assert "Niche report" in out["summary_markdown"]
    assert out["exported_to"].endswith(".md")
    assert 0 < out["quota"]["actual"] <= out["quota"]["estimated"]


# ---------------------------------------------------------------- breakout scan
def test_scan_merges_queries_and_groups(service, tmp_path):
    from niche_core import scan

    seeds_file = tmp_path / "seeds.txt"
    seeds_file.write_text("# comment\nlighthouse lore\n\nlighthouse lore  # dup\nsea shanty\n")
    seeds = scan.read_seeds([f"@{seeds_file}", "lighthouse lore"])
    assert seeds == ["lighthouse lore", "sea shanty"]
    r = scan.run(service, seeds, fmt="shorts", days=14, max_subs=100_000, min_views=1)
    assert r["per_query"].keys() == {"lighthouse lore", "sea shanty"}
    ids = [v["video_id"] for v in r["videos"]]
    assert ids == sorted(set(ids), key=lambda i: -next(v["views"] for v in r["videos"] if v["video_id"] == i))
    assert all(len(v["queries"]) >= 1 for v in r["videos"])
    md = scan.to_markdown(r)
    assert "# Breakout scan: shorts, last 14 days" in md and "## Top 40 videos" in md
    out = service.scan_breakouts(seeds, max_channel_subs=100_000, min_views=1, export=True)
    assert out["exported_to"].endswith("scan_shorts.md") and out["quota"]["actual"] == 0  # second run: all cached
    assert service.scan_breakouts(["x"], dry_run=True)["quota"]["actual"] == 0


def test_scan_drops_videos_that_are_not_about_the_game(service):
    from niche_core import scan

    assert scan.auto_require(["minecraft horror", "minecraft but"]) == scan.GAME_WORDS["minecraft"]
    assert scan.auto_require(["minecraft horror", "lighthouse lore"]) is None
    videos = {vid: {"video_id": vid, "title": vid, "views": n}
              for vid, n in (("vShortVert01", 30), ("vShortHoriz1", 20), ("vLongLore001", 10))}
    dropped = scan.verify_game(service, videos, require=["lighthouse"], exclude=["documentary"])
    assert set(videos) == {"vShortVert01"}                      # "I survived 100 days in a lighthouse"
    reasons = {d["video_id"]: d["reason"] for d in dropped}
    assert reasons["vShortHoriz1"] == "does not name the game"   # "Quick horizontal clip"
    assert reasons["vLongLore001"].startswith("another game")    # tagged documentary
    assert scan.verify_game(service, {"x": {"title": "x", "views": 1}}, None, None) == []
    # in a full scan the per-query counts and the report follow the filter
    r = scan.run(service, ["lighthouse lore"], fmt="shorts", days=14, max_subs=100_000, min_views=1,
                 require=["nothing-matches-this"], exclude=None)
    assert r["videos"] == [] and sum(r["per_query"].values()) == 0 and r["dropped"]
    assert "not about the game" in scan.to_markdown(r)


def test_niche_analysis_keeps_only_the_game():
    from niche_core.models import Video
    from niche_core.service import game_filter

    def v(vid, title, tags=()):
        return Video(video_id=vid, channel_id="c", channel_title="ch", title=title, published_at=None,
                     duration_s=600, format_class="long", tags=list(tags))

    vids = [v("a", "2 Idiots Try to Survive an EF5 Tornado in Minecraft"),
            v("b", "DOMINATOR 3! #reedtimmer #tornado #tornadochaser"),          # a real storm chaser
            v("c", "Surviving a tornado", tags=["minecraft", "weather mod"]),    # the game only in tags
            v("d", "Minecraft vs Roblox tornado")]                               # another game named
    kept, dropped = game_filter("minecraft tornado", vids)
    assert [x.video_id for x in kept] == ["a", "c"] and dropped == 2
    same, none = game_filter("lighthouse lore", vids)                            # no known game: untouched
    assert same == vids and none == 0
