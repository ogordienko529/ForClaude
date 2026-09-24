import tomllib
from datetime import timedelta
from pathlib import Path

import pytest

from niche_core.backtest import Case, drift_sd, evaluate_cases, fit_weights, forecast_eval, ranks, spearman
from niche_core.calibrate import analyse, render
from niche_core.config import DEFAULTS, load_config
from niche_core.enrich import enrich
from niche_core.models import Channel, Video
from niche_core.rpm import estimate_monetization
from niche_core.service import NicheService

from .fakes import FIXED_NOW

ROOT = Path(__file__).resolve().parents[1]


def test_example_config_matches_defaults():
    with open(ROOT / "config.example.toml", "rb") as fh:
        example = tomllib.load(fh)
    for section in ("cache", "search", "shorts", "thresholds", "bands", "weights", "forecast"):
        assert example[section] == DEFAULTS[section], section


def test_ranks_and_spearman():
    assert ranks([10, 20, 20, 5]) == [2, 3.5, 3.5, 1]
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1)
    assert spearman([1, 1, 1], [1, 2, 3]) is None


@pytest.fixture(scope="module")
def svc():
    return NicheService(load_config(overrides={"paths": {"db_path": ":memory:"}}), purge_on_start=False,
                        clock=lambda: FIXED_NOW)


def _case(svc, name, hit_rate_past, hit_rate_future, n=30, big_views=2_000_000):
    """Synthetic niche: small channels whose uploads hit at the given rates in each window."""
    chans, vids = {}, {"pool": [], "sample": [], "target": []}
    for g, rate, age in (("sample", hit_rate_past, 40), ("target", hit_rate_future, 10), ("pool", hit_rate_past, 40)):
        for i in range(n):
            cid = f"{name}{g}{i}"
            chans[cid] = Channel(cid, cid, 5_000, False, 500_000, 50, FIXED_NOW - timedelta(days=200))
            hit = i < round(rate * n)
            views = (big_views if g == "pool" else 50_000) if hit else 800
            vids[g].append(Video(f"v{cid}", cid, cid, "t", FIXED_NOW - timedelta(days=age), 900, "long", views,
                                 like_count=views // 50))
    e = {g: svc.enrich(v, chans) for g, v in vids.items()}
    return Case(name, "long", e["pool"], e["sample"], e["target"], estimate_monetization(name, [], "long"), {})


def test_backtest_recovers_a_persistent_signal(svc):
    p = svc.scoring_params("long")
    rates = [0.02, 0.05, 0.1, 0.2, 0.3, 0.45]
    cases = [_case(svc, f"n{i}", r, r) for i, r in enumerate(rates)]
    rows = evaluate_cases(cases, p)
    assert len(rows) == len(rates)
    assert spearman([r.features["view_score"] for r in rows], [r.outcome["rate"] for r in rows]) > 0.9
    fe = forecast_eval(rows, p)
    assert fe["mae"] < fe["mae_constant_baseline"]
    assert drift_sd(rows, p.prior_strength) < 0.05
    w = fit_weights(rows, ["opportunity", "demand", "competition"])
    assert w["opportunity"] > 0
    text = render(analyse(cases, p), p)
    assert "Backtest: long" in text and "Suggested bands" in text


def test_incomplete_cases_are_skipped(svc):
    p = svc.scoring_params("long")
    c = _case(svc, "x", 0.2, 0.2)
    c.pool = []
    assert evaluate_cases([c], p) == []
