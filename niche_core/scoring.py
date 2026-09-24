"""Niche scoring. Pure functions over EnrichedVideo lists — no I/O, fully testable.

Two samples feed the score:
  * `pool`   - search order=viewCount: what the audience actually sees (demand, outliers).
  * `sample` - search order=date, uploads at least `sample_min_age_days` old: what a typical
               upload gets (base rates, velocity, the forecast).

The design is driven by the temporal backtest (docs/CALIBRATION.md): components that did not
predict later small-channel success get little or no weight, and "competition" (share of big
channels) turned out to signal *demand*, not a barrier, so it is reported but not penalised.

Scores:
  * view_score  - 0-100, weighted mean of the view components (weights fitted per format);
  * final_score - (1 - m) * view_score + m * monetization, m = monetization weight (default 0.15);
  * forecast    - chance that a small channel's upload reaches the hit threshold, with an interval.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any

from .enrich import EnrichedVideo

VIEW_COMPONENTS = ("opportunity", "demand", "new_channel_proof", "velocity", "consistency", "competition")
COMPONENTS = VIEW_COMPONENTS + ("monetization",)


@dataclass
class ScoreComponent:
    name: str
    score: float
    weight: float
    raw: dict[str, Any]
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["score"] = round(self.score, 1)
        return d


@dataclass
class ScoringParams:
    """Everything format-specific or tunable, resolved from Config by the caller."""

    fmt: str                           # "shorts" | "long"
    hit_views: int
    velocity_low: float
    velocity_high: float
    small_views_low: float             # median views of small-channel top results -> 0
    small_views_high: float            # -> 100
    demand_low: float                  # median views of top results -> 0
    demand_high: float                 # -> 100
    hit_share_high: float              # small-channel hit share that earns 100
    small_channel_max_subs: int
    large_channel_min_subs: int
    new_channel_target: int            # distinct new channels with hits that earn full count credit
    consistency_channel_target: int
    promo_min_views: int = 100_000
    promo_max_like_rate: float = 0.001
    promo_max_comment_rate: float = 0.00005
    promo_min_avg_views_per_sub: float = 20
    min_sample_videos: int = 30
    min_small_channel_hits: int = 5
    prior_hit_rate: float = 0.2        # panel mean outcome rate (backtest), used for shrinkage
    prior_strength: float = 10         # pseudo-uploads of prior weight
    drift_sd: float = 0.15             # month-to-month movement of a niche's hit rate (backtest)
    max_ci_width: float = 25           # 80% score interval wider than this => low confidence
    weights: dict[str, float] = field(default_factory=dict)   # view components
    monetization_weight: float = 0.15


# ---------------------------------------------------------------- helpers
def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def linear_score(x: float, low: float, high: float) -> float:
    if high == low:
        return 100.0 if x >= high else 0.0
    return clamp((x - low) / (high - low) * 100)


def log_score(x: float | None, low: float, high: float) -> float:
    """0 at `low`, 100 at `high`, logarithmic in between (views are heavy-tailed)."""
    if x is None or x <= 0:
        return 0.0
    return clamp((math.log10(x) - math.log10(low)) / (math.log10(high) - math.log10(low)) * 100)


def median(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def is_small(e: EnrichedVideo, p: ScoringParams) -> bool:
    return e.subs is not None and e.subs <= p.small_channel_max_subs


def is_large(e: EnrichedVideo, p: ScoringParams) -> bool:
    return e.subs is not None and e.subs >= p.large_channel_min_subs


def suspected_paid_promotion(e: EnrichedVideo, p: ScoringParams) -> bool:
    """Ad-driven views: lots of views, almost no likes/comments, and a channel whose average
    views dwarf its audience. Engagement is the tell — organic hits sit at 0.2-3% likes,
    paid in-stream views near 0% (e.g. a brand channel: 3.6M views, 0 likes, 0 comments)."""
    v = e.video
    views = v.view_count or 0
    if views < p.promo_min_views or e.channel is None:
        return False
    avg = e.channel.avg_views_per_video
    if avg is None or avg / max(e.subs or 1, 1) < p.promo_min_avg_views_per_sub:
        return False
    if v.like_count is not None:
        return v.like_count / views < p.promo_max_like_rate
    if v.comment_count is not None:
        return v.comment_count / views < p.promo_max_comment_rate
    return False


def unique(videos: list[EnrichedVideo]) -> list[EnrichedVideo]:
    seen: dict[str, EnrichedVideo] = {}
    for e in videos:
        seen.setdefault(e.video.video_id, e)
    return list(seen.values())


def small_uploads(videos: list[EnrichedVideo], p: ScoringParams) -> list[EnrichedVideo]:
    return [e for e in videos if is_small(e, p) and not suspected_paid_promotion(e, p)]


def shrunk_rate(hits: int, n: int, prior_mean: float, prior_strength: float) -> float:
    """Beta-binomial posterior mean: small samples are pulled toward the prior."""
    return (hits + prior_strength * prior_mean) / (n + prior_strength)


# ---------------------------------------------------------------- components
def score_opportunity(pool: list[EnrichedVideo], sample: list[EnrichedVideo], p: ScoringParams) -> ScoreComponent:
    base = small_uploads(sample, p)
    source = "date-ordered sample"
    if len(base) < 10:
        base = small_uploads(unique(pool + sample), p)
        source = "all results (sample too small; biased upward)"
    hits = sum(1 for e in base if e.is_hit)
    rate = shrunk_rate(hits, len(base), p.prior_hit_rate, p.prior_strength)
    small_top = [e.video.view_count for e in small_uploads(pool, p)]
    med_small_top = median(small_top)
    s_rate = linear_score(rate, 0, p.hit_share_high)
    s_top = log_score(med_small_top, p.small_views_low, p.small_views_high) if small_top else 0.0
    score = 0.5 * s_rate + 0.5 * s_top
    return ScoreComponent(
        "opportunity", score, p.weights.get("opportunity", 0),
        {"small_channel_uploads": len(base), "small_channel_hits": hits,
         "hit_share_raw": round(hits / len(base), 3) if base else None, "hit_share_shrunk": round(rate, 3),
         "hit_views_threshold": p.hit_views, "small_channel_top_results": len(small_top),
         "median_views_small_channel_top": round(med_small_top) if med_small_top else None,
         "base_rate_source": source},
        f"{hits}/{len(base)} typical small-channel uploads (≤{p.small_channel_max_subs:,} subs) reached "
        f"{p.hit_views:,}+ views ({rate:.0%} after shrinkage). Small channels that make the top results get a "
        f"median {med_small_top or 0:,.0f} views.",
    )


def score_demand(pool: list[EnrichedVideo], p: ScoringParams) -> ScoreComponent:
    med = median([e.video.view_count for e in pool])
    return ScoreComponent(
        "demand", log_score(med, p.demand_low, p.demand_high), p.weights.get("demand", 0),
        {"top_results": len(pool), "median_views_top_results": round(med) if med else None,
         "band_low": p.demand_low, "band_high": p.demand_high},
        f"The top results get a median {med or 0:,.0f} views: how much audience this topic pulls "
        f"({p.fmt} band {p.demand_low:,.0f} → 0, {p.demand_high:,.0f} → 100, log scale).",
    )


def score_velocity(pool: list[EnrichedVideo], sample: list[EnrichedVideo], p: ScoringParams) -> ScoreComponent:
    # Use the date-ordered sample: the view-ordered pool is by construction the fastest movers.
    recent = [e for e in sample if e.views_per_day is not None]
    source = "date-ordered sample"
    if len(recent) < 10:
        recent = [e for e in unique(pool + sample) if e.views_per_day is not None]
        source = "all results (sample too small; biased upward)"
    med = median([e.views_per_day for e in recent])
    return ScoreComponent(
        "velocity", log_score(med, p.velocity_low, p.velocity_high), p.weights.get("velocity", 0),
        {"videos": len(recent), "median_views_per_day": round(med, 1) if med else None,
         "band_low": p.velocity_low, "band_high": p.velocity_high, "source": source},
        f"A typical upload gets a median {med or 0:,.0f} views/day ({len(recent)} uploads; "
        f"{p.fmt} band {p.velocity_low:,.0f} → 0, {p.velocity_high:,.0f} → 100, log scale).",
    )


def score_competition(pool: list[EnrichedVideo], p: ScoringParams) -> ScoreComponent:
    known = [e for e in pool if e.subs is not None]
    large = [e for e in known if is_large(e, p)]
    if not known:
        return ScoreComponent("competition", 0.0, p.weights.get("competition", 0), {"top_results": 0},
                              "No channel data for the top results.")
    video_share = len(large) / len(known)
    total_views = sum(e.video.view_count or 0 for e in known)
    view_share = sum(e.video.view_count or 0 for e in large) / total_views if total_views else 0.0
    score = 100 * (1 - (0.5 * video_share + 0.5 * view_share))
    return ScoreComponent(
        "competition", score, p.weights.get("competition", 0),
        {"top_results": len(known), "large_channel_videos": len(large),
         "large_channels": len({e.video.channel_id for e in large}),
         "large_video_share": round(video_share, 3), "large_view_share": round(view_share, 3)},
        f"Channels with {p.large_channel_min_subs:,}+ subs made {video_share:.0%} of top results and took "
        f"{view_share:.0%} of their views. Higher = less dominated. Backtest: big-channel presence signals "
        f"demand rather than a barrier, so this is informational unless weighted in the config.",
    )


def score_new_channel_proof(pool: list[EnrichedVideo], sample: list[EnrichedVideo], p: ScoringParams) -> ScoreComponent:
    everything = small_uploads(unique(pool + sample), p)
    winners = {e.video.channel_id: e.video.channel_title for e in everything if e.is_new_channel and e.is_hit}
    new_sample = [e for e in small_uploads(sample, p) if e.is_new_channel]
    new_hits = sum(1 for e in new_sample if e.is_hit)
    rate = shrunk_rate(new_hits, len(new_sample), p.prior_hit_rate, p.prior_strength)
    s_count = clamp(math.log1p(len(winners)) / math.log1p(p.new_channel_target) * 100)
    s_rate = linear_score(rate, 0, p.hit_share_high)
    return ScoreComponent(
        "new_channel_proof", 0.5 * s_count + 0.5 * s_rate, p.weights.get("new_channel_proof", 0),
        {"new_channels_with_hits": len(winners), "count_target": p.new_channel_target,
         "new_channel_uploads_in_sample": len(new_sample), "new_channel_hits_in_sample": new_hits,
         "new_channel_hit_rate_shrunk": round(rate, 3), "channels": sorted(winners.values())[:15]},
        f"{len(winners)} channel(s) under 12 months old have a {p.hit_views:,}+ view video here; "
        f"{new_hits}/{len(new_sample)} typical uploads from new channels hit ({rate:.0%} after shrinkage).",
    )


def score_consistency(pool: list[EnrichedVideo], sample: list[EnrichedVideo], p: ScoringParams) -> ScoreComponent:
    hits = [e for e in small_uploads(unique(pool + sample), p) if e.is_hit]
    channels = {e.video.channel_id for e in hits}
    views = [e.video.view_count or 0 for e in hits]
    top_share = max(views) / sum(views) if views and sum(views) else 1.0
    spread = clamp(len(channels) / p.consistency_channel_target * 100)
    score = 0.5 * spread + 0.5 * (1 - top_share) * 100 if hits else 0.0
    return ScoreComponent(
        "consistency", score, p.weights.get("consistency", 0),
        {"small_channel_hits": len(hits), "distinct_channels": len(channels),
         "top_video_view_share": round(top_share, 3), "channel_target": p.consistency_channel_target},
        f"Small-channel hits come from {len(channels)} different channel(s); the single biggest hit holds "
        f"{top_share:.0%} of their combined views.",
    )


def score_monetization(estimate: dict[str, Any], p: ScoringParams) -> ScoreComponent:
    return ScoreComponent(
        "monetization", float(estimate["score"]), p.monetization_weight, estimate,
        f"ESTIMATE, not data: {estimate['tier']} RPM tier for {p.fmt} "
        f"(~{estimate['rpm_range_usd']} per 1,000 views) based on {estimate['basis']}.",
    )


# ---------------------------------------------------------------- aggregate
def view_score(components: dict[str, ScoreComponent], weights: dict[str, float]) -> float:
    total = sum(w for k, w in weights.items() if k in components)
    if not total:
        return 0.0
    return sum(components[k].score * w for k, w in weights.items() if k in components) / total


def combine(view: float, monetization: float, m: float) -> float:
    return (1 - m) * view + m * monetization


def view_components(pool: list[EnrichedVideo], sample: list[EnrichedVideo], p: ScoringParams) -> dict[str, ScoreComponent]:
    comps = [
        score_opportunity(pool, sample, p),
        score_demand(pool, p),
        score_new_channel_proof(pool, sample, p),
        score_velocity(pool, sample, p),
        score_consistency(pool, sample, p),
        score_competition(pool, p),
    ]
    return {c.name: c for c in comps}


def forecast(sample: list[EnrichedVideo], p: ScoringParams, draws: int = 4000, seed: int = 7) -> dict[str, Any]:
    """Chance that a typical small-channel upload reaches the hit threshold in its first 1-3 weeks.
    Beta-binomial posterior on the recent sample, widened by the month-to-month drift the backtest
    measured, so the interval reflects both sampling noise and niches changing."""
    base = small_uploads(sample, p)
    hits = sum(1 for e in base if e.is_hit)
    point = shrunk_rate(hits, len(base), p.prior_hit_rate, p.prior_strength)
    rng = random.Random(seed)
    a = hits + p.prior_strength * p.prior_hit_rate
    b = (len(base) - hits) + p.prior_strength * (1 - p.prior_hit_rate)
    draws_ = sorted(clamp(rng.betavariate(a, b) + rng.gauss(0, p.drift_sd), 0.0, 1.0) for _ in range(draws))
    lo, hi = draws_[int(0.1 * draws)], draws_[int(0.9 * draws) - 1]
    return {
        "hit_probability": round(point, 3),
        "interval_80": [round(lo, 3), round(hi, 3)],
        "based_on_uploads": len(base),
        "hits_observed": hits,
        "hit_views_threshold": p.hit_views,
        "explanation": (
            f"About {point:.0%} (80% range {lo:.0%}–{hi:.0%}) of uploads from small channels "
            f"(≤{p.small_channel_max_subs:,} subs) reach {p.hit_views:,}+ views in their first 1–3 weeks, "
            f"based on {len(base)} recent uploads ({hits} hits). The range includes how much niches "
            f"drift month to month in the backtest."
        ),
    }


def bootstrap_interval(pool: list[EnrichedVideo], sample: list[EnrichedVideo], p: ScoringParams,
                       iters: int = 150, seed: int = 11) -> tuple[float, float]:
    """80% interval of view_score under resampling of the fetched videos (sampling uncertainty)."""
    if not pool and not sample:
        return (0.0, 0.0)
    rng = random.Random(seed)
    vals = []
    for _ in range(iters):
        bp = [rng.choice(pool) for _ in pool] if pool else []
        bs = [rng.choice(sample) for _ in sample] if sample else []
        vals.append(view_score(view_components(bp, bs, p), p.weights))
    vals.sort()
    return vals[int(0.1 * iters)], vals[int(0.9 * iters) - 1]


def confidence_flags(pool: list[EnrichedVideo], sample: list[EnrichedVideo], opportunity: ScoreComponent,
                     interval: tuple[float, float], p: ScoringParams) -> list[str]:
    flags = []
    n = len(unique(pool + sample))
    if n == 0:
        return ["No videos could be analysed."]
    if n < p.min_sample_videos:
        flags.append(f"Only {n} {p.fmt} videos analysed (< {p.min_sample_videos}).")
    if opportunity.raw["small_channel_uploads"] < 15:
        flags.append(f"Only {opportunity.raw['small_channel_uploads']} typical small-channel uploads in the base sample.")
    if "biased" in opportunity.raw["base_rate_source"]:
        flags.append("Date-ordered sample too small; base rates computed from view-ordered results (optimistic).")
    if interval[1] - interval[0] > p.max_ci_width:
        flags.append(f"Score is uncertain: 80% interval {interval[0]:.0f}–{interval[1]:.0f}.")
    known = [e for e in pool if e.subs is not None]
    if pool and len(known) < 0.7 * len(pool):
        flags.append("Many channels hide subscriber counts; small/large split is uncertain.")
    return flags


def score_niche(pool: list[EnrichedVideo], sample: list[EnrichedVideo], monetization: dict[str, Any],
                p: ScoringParams, with_interval: bool = True) -> dict[str, Any]:
    comps = view_components(pool, sample, p)
    money = score_monetization(monetization, p)
    has_data = bool(pool or sample)
    vs = view_score(comps, p.weights) if has_data else None
    interval = bootstrap_interval(pool, sample, p) if (with_interval and has_data) else (vs or 0.0, vs or 0.0)
    flags = confidence_flags(pool, sample, comps["opportunity"], interval, p) if with_interval else []
    all_comps = {**comps, "monetization": money}
    return {
        "final_score": round(combine(vs, money.score, p.monetization_weight), 1) if vs is not None else None,
        "view_score": round(vs, 1) if vs is not None else None,
        "view_score_interval_80": [round(interval[0], 1), round(interval[1], 1)] if has_data else None,
        "forecast": forecast(sample, p) if has_data else None,
        "components": {k: c.to_dict() for k, c in all_comps.items()},
        "low_confidence": bool(flags) or not has_data,
        "confidence_flags": flags if has_data else ["No videos could be analysed."],
        "suspected_paid_promotion_excluded": sum(1 for e in unique(pool + sample) if suspected_paid_promotion(e, p)),
    }
