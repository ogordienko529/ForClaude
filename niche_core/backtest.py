"""Temporal backtest: does a score computed on the past predict what small channels get later?

For each niche:
  * features: the normal scoring pipeline run on uploads published 60-30 days ago
    (view-ordered pool + date-ordered sample, exactly like analyze_niche);
  * outcome: uploads published 21-7 days ago (date-ordered), small channels only:
    the share that reached the format's hit threshold. Their views are 1-3 weeks old,
    i.e. close to the "10k within 14 days" the tool is about.

Everything goes through the cache, so after one paid collection every calibration iteration
runs offline for free (NicheService(offline=True)).
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field, replace
from typing import Any

from .durations import LONG, SHORT
from .enrich import EnrichedVideo
from .rpm import estimate_monetization
from .scoring import ScoringParams, forecast, score_niche, shrunk_rate, small_uploads
from .service import NicheService, SearchSpec

PAST_WINDOW = (60, 30)    # published between 60 and 30 days ago -> features
TARGET_WINDOW = (21, 7)   # published between 21 and 7 days ago -> outcome


@dataclass
class Case:
    query: str
    fmt: str                              # "shorts" | "long"
    pool: list[EnrichedVideo]
    sample: list[EnrichedVideo]
    target: list[EnrichedVideo]
    monetization: dict[str, Any]
    excluded: dict[str, int]
    errors: list[str] = field(default_factory=list)


def case_specs(svc: NicheService, query: str, fmt: str, n: int = 50) -> dict[str, list[SearchSpec]]:
    (p_after, p_before), (t_after, t_before) = PAST_WINDOW, TARGET_WINDOW
    return {
        "pool": svc.make_specs(query, fmt, p_after, n, "viewCount", None, None, p_before),
        "sample": svc.make_specs(query, fmt, p_after, n, "date", None, None, p_before),
        "target": svc.make_specs(query, fmt, t_after, n, "date", None, None, t_before),
    }


def estimate_case(svc: NicheService, query: str, fmt: str) -> int:
    groups = case_specs(svc, query, fmt)
    return svc.estimate_collect([s for specs in groups.values() for s in specs], with_channels=True)["total"]


def collect_case(svc: NicheService, query: str, fmt: str) -> Case:
    errors: list[str] = []
    groups = case_specs(svc, query, fmt)
    videos, channels, excluded = svc.collect_groups(groups, fmt, with_channels=True, errors=errors)
    cls = SHORT if fmt == "shorts" else LONG
    enriched = {g: svc.enrich([v for v in vs if v.format_class == cls], channels) for g, vs in videos.items()}
    cats = [e.video.category_id for e in enriched["pool"] + enriched["sample"]]
    return Case(query, fmt, enriched["pool"], enriched["sample"], enriched["target"],
                estimate_monetization(query, cats, fmt, svc.config.monetization), excluded, errors)


# ---------------------------------------------------------------- outcome and forecast inputs
def small_upload_stats(videos: list[EnrichedVideo], p: ScoringParams) -> dict[str, Any]:
    small = small_uploads(videos, p)
    hits = [e for e in small if e.is_hit]
    new = [e for e in small if e.is_new_channel]
    views = [e.video.view_count or 0 for e in small]
    return {
        "n": len(small),
        "hits": len(hits),
        "rate": len(hits) / len(small) if small else None,
        "new_n": len(new),
        "new_hits": sum(1 for e in new if e.is_hit),
        "median_views": statistics.median(views) if views else None,
    }


# ---------------------------------------------------------------- statistics helpers
def ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def spearman(xs: list[float], ys: list[float]) -> float | None:
    return pearson(ranks(xs), ranks(ys))


# ---------------------------------------------------------------- evaluation
@dataclass
class Row:
    query: str
    features: dict[str, Any]          # score_niche output on the past window
    past: dict[str, Any]              # small-upload stats, past sample
    outcome: dict[str, Any]           # small-upload stats, target window
    case: Case | None = None


def evaluate_cases(cases: list[Case], p: ScoringParams, min_target_n: int = 8) -> list[Row]:
    rows = []
    for c in cases:
        if not c.pool or not c.sample:
            continue  # incomplete collection (e.g. quota ran out mid-niche)
        out = small_upload_stats(c.target, p)
        if out["n"] < min_target_n:
            continue  # outcome too noisy to judge the prediction
        rows.append(Row(c.query, score_niche(c.pool, c.sample, c.monetization, p, with_interval=False),
                        small_upload_stats(c.sample, p), out, c))
    return rows


def weighted(row: Row, weights: dict[str, float]) -> float:
    comps = row.features["components"]
    total = sum(w for k, w in weights.items() if k in comps) or 1.0
    return sum(comps[k]["score"] * w for k, w in weights.items() if k in comps) / total


def fit_weights(rows: list[Row], components: list[str]) -> dict[str, float]:
    """Correlation-proportional weights: w_i = max(spearman(component_i, outcome), 0).
    Deliberately simple: with ~10-20 niches anything fancier overfits."""
    ys = [r.outcome["rate"] for r in rows]
    w = {}
    for k in components:
        rho = spearman([r.features["components"][k]["score"] for r in rows], ys)
        w[k] = max(rho or 0.0, 0.0)
    if sum(w.values()) == 0:
        w = {k: 1.0 for k in components}
    return w


def loo_spearman(rows: list[Row], components: list[str]) -> float | None:
    """Leave-one-out: weights fitted without niche i are used to score niche i."""
    if len(rows) < 5:
        return None
    preds = []
    for i, r in enumerate(rows):
        w = fit_weights(rows[:i] + rows[i + 1 :], components)
        preds.append(weighted(r, w))
    return spearman(preds, [r.outcome["rate"] for r in rows])


def forecast_eval(rows: list[Row], p: ScoringParams) -> dict[str, Any]:
    """Evaluate the production forecast (scoring.forecast) leave-one-out: prior hit rate and drift
    are measured on the other niches, then the held-out niche's past sample predicts its outcome."""
    if len(rows) < 5:
        return {}
    errs, covered, preds = [], 0, []
    for i, r in enumerate(rows):
        train = rows[:i] + rows[i + 1 :]
        q = replace(p, prior_hit_rate=statistics.fmean(t.outcome["rate"] for t in train),
                    drift_sd=drift_sd(train, p.prior_strength))
        f = forecast(r.case.sample, q)
        actual = r.outcome["rate"]
        preds.append(f["hit_probability"])
        errs.append(abs(f["hit_probability"] - actual))
        covered += f["interval_80"][0] <= actual <= f["interval_80"][1]
    ys = [r.outcome["rate"] for r in rows]
    return {
        "mae": statistics.fmean(errs),
        "mae_constant_baseline": statistics.fmean(abs(y - statistics.fmean(ys)) for y in ys),
        "coverage_80": covered / len(rows),
        "spearman_forecast": spearman(preds, ys),
    }


def drift_sd(rows: list[Row], prior_strength: float) -> float:
    """How much a niche's small-upload hit rate moves between the past and target windows,
    after removing sampling noise. Used to widen production forecast intervals."""
    if len(rows) < 3:
        return 0.1
    prior = statistics.fmean(r.outcome["rate"] for r in rows)
    diffs = [r.outcome["rate"] - shrunk_rate(r.past["hits"], r.past["n"], prior, prior_strength) for r in rows]
    sampling = statistics.fmean(
        (r.outcome["rate"] * (1 - r.outcome["rate"])) / max(r.outcome["n"], 1) for r in rows
    )
    return math.sqrt(max(statistics.pvariance(diffs) - sampling, 0.0))
