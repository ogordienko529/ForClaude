"""Scoring logic against fixture niches (tests/fixtures/niches.json). No API."""

import json
from datetime import timedelta

import pytest

from niche_core.config import load_config
from niche_core.enrich import enrich
from niche_core.models import Channel, Video
from niche_core.report import build_insights, render_format_section
from niche_core.rpm import estimate_monetization
from niche_core.scoring import (
    final_score, linear_score, log_score, score_competition, score_consistency, score_niche, suspected_paid_promotion,
)
from niche_core.service import NicheService

from .fakes import FIXED_NOW, FIXTURES

NICHES = json.loads((FIXTURES / "niches.json").read_text())


@pytest.fixture(scope="module")
def svc():
    return NicheService(load_config(overrides={"paths": {"db_path": ":memory:"}}), purge_on_start=False,
                        clock=lambda: FIXED_NOW)


def build(name, svc):
    fx = NICHES[name]
    chans = {
        c["channel_id"]: Channel(c["channel_id"], c["title"], c["subs"], False, c["views"], c["videos"],
                                 FIXED_NOW - timedelta(days=c["created_days_ago"]))
        for c in fx["channels"]
    }

    def videos(rows):
        return [Video(r["video_id"], r["channel_id"], chans[r["channel_id"]].title, r["title"],
                      FIXED_NOW - timedelta(days=r["age_days"]), r["duration_s"], r["format"], r["views"],
                      category_id=r["category_id"]) for r in rows]

    fmt = "shorts" if fx["format"] == "short" else "long"
    return svc.enrich(videos(fx["pool"]), chans), svc.enrich(videos(fx["sample"]), chans), svc.scoring_params(fmt), fmt


def run(name, svc, query="roman history"):
    pool, sample, p, fmt = build(name, svc)
    mon = estimate_monetization(query, [e.video.category_id for e in pool + sample], fmt)
    return score_niche(pool, sample, mon, p)


# ---------------------------------------------------------------- helpers
def test_log_and_linear_scores():
    assert log_score(100, 100, 10_000) == 0
    assert log_score(1_000, 100, 10_000) == 50
    assert log_score(1e9, 100, 10_000) == 100
    assert log_score(None, 1, 10) == 0 and log_score(0, 1, 10) == 0
    assert linear_score(0.15, 0, 0.3) == 50
    assert linear_score(0.9, 0, 0.3) == 100


def test_weights_default_and_final_score():
    w = load_config().weights
    assert w == {"opportunity": 0.25, "new_channel_proof": 0.20, "velocity": 0.15,
                 "consistency": 0.15, "competition": 0.10, "monetization": 0.15}
    assert abs(sum(w.values()) - 1) < 1e-9


def test_final_score_is_weighted_mean(svc):
    r = run("healthy", svc)
    comps = r["components"]
    expected = sum(c["score"] * c["weight"] for c in comps.values()) / sum(c["weight"] for c in comps.values())
    assert r["final_score"] == pytest.approx(expected, abs=0.1)


# ---------------------------------------------------------------- niche comparisons
def test_healthy_beats_dominated_and_one_viral(svc):
    healthy, dominated, viral = run("healthy", svc), run("dominated", svc), run("one_viral", svc)
    assert healthy["final_score"] > dominated["final_score"]
    assert healthy["final_score"] > viral["final_score"]
    assert healthy["components"]["opportunity"]["score"] > 50


def test_dominated_niche_has_low_competition_score(svc):
    assert run("dominated", svc)["components"]["competition"]["score"] < run("healthy", svc)["components"]["competition"]["score"]
    assert run("dominated", svc)["components"]["competition"]["score"] < 40


def test_one_viral_video_scores_low_consistency(svc):
    viral = run("one_viral", svc)["components"]["consistency"]
    assert viral["raw"]["small_channel_hits"] == 1
    assert viral["raw"]["top_video_view_share"] == 1.0
    assert viral["score"] < 10
    assert run("healthy", svc)["components"]["consistency"]["score"] > 60


def test_new_channel_proof_counts_distinct_new_channels(svc):
    healthy = run("healthy", svc)["components"]["new_channel_proof"]
    assert healthy["raw"]["new_channels_with_hits"] >= 5 and healthy["score"] == 100
    assert run("dominated", svc)["components"]["new_channel_proof"]["score"] < healthy["score"]


def test_thin_niche_flagged_low_confidence(svc):
    thin = run("thin", svc)
    assert thin["low_confidence"]
    assert any("videos analysed" in f for f in thin["confidence_flags"])
    assert not run("healthy", svc)["low_confidence"]


def test_shorts_use_their_own_bands_and_lower_monetization(svc):
    shorts = run("shorts_healthy", svc)
    assert shorts["components"]["velocity"]["raw"]["band_high"] == 50_000
    assert shorts["components"]["monetization"]["score"] < run("healthy", svc)["components"]["monetization"]["score"]
    assert "ESTIMATE" in shorts["components"]["monetization"]["explanation"]


def test_every_component_has_explanation_and_bounds(svc):
    for name in NICHES:
        for c in run(name, svc)["components"].values():
            assert 0 <= c["score"] <= 100 and c["explanation"]


# ---------------------------------------------------------------- specific rules
def _e(svc, subs, views, avg_views, fmt="long", created=2000, age=5.0, vid="v"):
    ch = Channel("c" + vid, "c", subs, False, int(avg_views * 10), 10, FIXED_NOW - timedelta(days=created))
    v = Video(vid, "c" + vid, "c", "t", FIXED_NOW - timedelta(days=age), 600 if fmt == "long" else 40,
              "long" if fmt == "long" else "short", views)
    return enrich([v], {ch.channel_id: ch}, now=FIXED_NOW, hit_views={"shorts": 10_000, "long": 10_000})[0]


def test_paid_promotion_detected_for_long_only(svc):
    brand = _e(svc, 5_100, 3_600_000, 3_500_000)  # avg/subs ~ 686
    organic = _e(svc, 5_200, 979_000, 291_000, vid="o")  # avg/subs ~ 56
    assert suspected_paid_promotion(brand, svc.scoring_params("long"))
    assert not suspected_paid_promotion(organic, svc.scoring_params("long"))
    assert not suspected_paid_promotion(_e(svc, 5_100, 3_600_000, 3_500_000, fmt="short", vid="s"),
                                        svc.scoring_params("shorts"))


def test_paid_promotion_excluded_from_consistency(svc):
    p = svc.scoring_params("long")
    brand = _e(svc, 5_100, 3_600_000, 3_500_000, vid="b")
    c = score_consistency([brand], [], p)
    assert c.raw["small_channel_hits"] == 0 and c.score == 0


def test_competition_empty_pool_is_neutral(svc):
    assert score_competition([], svc.scoring_params("long")).score == 100


def test_monetization_rules():
    assert estimate_monetization("personal finance tips", ["24"], "long")["tier"] == "high"
    assert estimate_monetization("minecraft builds", ["28"], "long")["tier"] == "low"
    edu = estimate_monetization("roman empire", ["27", "27", "24"], "long")
    assert edu["tier"] == "medium" and "Education" in edu["basis"]
    hist = estimate_monetization("roman history", ["22"], "shorts")
    assert hist["tier"] == "medium" and "history" in hist["basis"]
    assert estimate_monetization("minecraft history", [], "long")["tier"] == "low"  # low beats medium
    assert estimate_monetization("scarface", [], "long")["basis"].startswith("default")  # 'car' needs a word start
    assert estimate_monetization("roman history", ["27"], "shorts")["score"] < edu["score"]
    assert estimate_monetization("x", [], "long")["basis"].startswith("default")


def test_insights_and_markdown(svc):
    pool, sample, p, _ = build("healthy", svc)
    ins = build_insights(pool, sample, "roman history", p)
    assert 0 < len(ins["top_outliers"]) <= 10
    assert all(o["subs"] < 50_000 for o in ins["top_outliers"])
    assert all(o["views"] >= 10_000 for o in ins["top_outliers"])
    scores = [o["outlier_score"] for o in ins["top_outliers"]]
    assert scores == sorted(scores, reverse=True)
    assert ins["typical_length"]["median_seconds"] >= 480
    assert ins["posting_recency"]["hits"] > 0
    section = "\n".join(render_format_section("long", {**run("healthy", svc), **ins}))
    assert "Top outliers" in section and "ESTIMATE" in section
