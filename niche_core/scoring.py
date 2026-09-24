"""Niche scoring. Pure functions over EnrichedVideo lists — no I/O, fully testable.

Two samples feed the score:
  * `pool`   - search order=viewCount: what the audience actually sees (outliers, competition).
  * `sample` - search order=date, published at least `sample_min_age_days` ago: an unbiased
               slice of what gets uploaded, used for base rates (hit share).
Each component is 0-100 with its raw inputs and a plain-language explanation.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any

from .enrich import EnrichedVideo

COMPONENTS = ("opportunity", "new_channel_proof", "velocity", "consistency", "competition", "monetization")


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

    fmt: str                       # "shorts" | "long"
    hit_views: int
    velocity_low: float
    velocity_high: float
    outlier_median_low: float
    outlier_median_high: float
    hit_share_high: float          # hit share that earns 100
    small_channel_max_subs: int
    large_channel_min_subs: int
    new_channel_target: int        # new channels with hits that earn 100
    consistency_channel_target: int
    promo_avg_views_per_sub: float  # long-form only: channel avg views / subs above this = likely paid ads
    min_sample_videos: int
    min_small_channel_hits: int
    weights: dict[str, float] = field(default_factory=dict)


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
    return e.subs is not None and e.subs < p.small_channel_max_subs


def is_large(e: EnrichedVideo, p: ScoringParams) -> bool:
    return e.subs is not None and e.subs >= p.large_channel_min_subs


def suspected_paid_promotion(e: EnrichedVideo, p: ScoringParams) -> bool:
    """Long-form channels whose average views per video dwarf their subscriber count are
    usually running ads (e.g. brand channels). Shorts are exempt: huge views/subs is normal there."""
    if p.fmt != "long" or e.channel is None or e.subs is None:
        return False
    avg = e.channel.avg_views_per_video
    return avg is not None and avg / max(e.subs, 1) >= p.promo_avg_views_per_sub


def unique(videos: list[EnrichedVideo]) -> list[EnrichedVideo]:
    seen: dict[str, EnrichedVideo] = {}
    for e in videos:
        seen.setdefault(e.video.video_id, e)
    return list(seen.values())


# ---------------------------------------------------------------- components
def score_opportunity(pool: list[EnrichedVideo], sample: list[EnrichedVideo], p: ScoringParams) -> ScoreComponent:
    base = [e for e in sample if is_small(e, p) and not suspected_paid_promotion(e, p)]
    source = "date-ordered sample"
    if len(base) < 10:  # too thin: fall back to everything we have (biased upward, flagged)
        base = [e for e in unique(pool + sample) if is_small(e, p) and not suspected_paid_promotion(e, p)]
        source = "all results (sample too small; biased upward)"
    hits = [e for e in base if e.is_hit]
    hit_share = len(hits) / len(base) if base else 0.0

    small_pool = [e for e in unique(pool + sample) if is_small(e, p) and not suspected_paid_promotion(e, p)]
    med_outlier = median([e.primary_score for e in small_pool])
    metric = "channel_relative (views / channel avg)" if p.fmt == "shorts" else "views / subscribers"

    s_share = linear_score(hit_share, 0, p.hit_share_high)
    s_outlier = log_score(med_outlier, p.outlier_median_low, p.outlier_median_high)
    score = 0.6 * s_share + 0.4 * s_outlier
    return ScoreComponent(
        "opportunity",
        score,
        p.weights.get("opportunity", 0),
        {
            "small_channel_videos": len(base),
            "small_channel_hits": len(hits),
            "hit_share": round(hit_share, 3),
            "hit_views_threshold": p.hit_views,
            "median_outlier_score": round(med_outlier, 2) if med_outlier is not None else None,
            "outlier_metric": metric,
            "base_rate_source": source,
        },
        f"{len(hits)}/{len(base)} recent small-channel videos (<{p.small_channel_max_subs:,} subs) reached "
        f"{p.hit_views:,}+ views ({hit_share:.0%}; {p.hit_share_high:.0%}+ scores 100). "
        f"Median outlier score {med_outlier or 0:.2f} ({metric}).",
    )


def score_velocity(pool: list[EnrichedVideo], sample: list[EnrichedVideo], p: ScoringParams) -> ScoreComponent:
    # Use the date-ordered sample: the view-ordered pool is by construction the fastest movers.
    recent = [e for e in sample if e.age_days is not None and e.age_days < 30]
    source = "date-ordered sample"
    if len(recent) < 10:
        recent = [e for e in unique(pool + sample) if e.age_days is not None and e.age_days < 30]
        source = "all results (sample too small; biased upward)"
    med = median([e.views_per_day for e in recent])
    score = log_score(med, p.velocity_low, p.velocity_high)
    return ScoreComponent(
        "velocity",
        score,
        p.weights.get("velocity", 0),
        {"videos_under_30d": len(recent), "median_views_per_day": round(med) if med else None,
         "band_low": p.velocity_low, "band_high": p.velocity_high, "source": source},
        f"Median {med or 0:,.0f} views/day across {len(recent)} typical uploads under 30 days old "
        f"({p.fmt} band: {p.velocity_low:,.0f} -> 0, {p.velocity_high:,.0f} -> 100, log scale).",
    )


def score_competition(pool: list[EnrichedVideo], p: ScoringParams) -> ScoreComponent:
    known = [e for e in pool if e.subs is not None]
    large = [e for e in known if is_large(e, p)]
    video_share = len(large) / len(known) if known else 0.0
    total_views = sum(e.video.view_count or 0 for e in known)
    large_views = sum(e.video.view_count or 0 for e in large)
    view_share = large_views / total_views if total_views else 0.0
    large_channels = len({e.video.channel_id for e in large})
    score = 100 * (1 - (0.5 * video_share + 0.5 * view_share))
    return ScoreComponent(
        "competition",
        score,
        p.weights.get("competition", 0),
        {"top_results": len(known), "large_channel_videos": len(large), "large_channels": large_channels,
         "large_video_share": round(video_share, 3), "large_view_share": round(view_share, 3)},
        f"Channels with {p.large_channel_min_subs:,}+ subs made {video_share:.0%} of top results and took "
        f"{view_share:.0%} of their views ({large_channels} large channels). Higher score = less dominated.",
    )


def score_new_channel_proof(pool: list[EnrichedVideo], sample: list[EnrichedVideo], p: ScoringParams) -> ScoreComponent:
    channels: dict[str, str] = {}
    for e in unique(pool + sample):
        if e.is_new_channel and e.is_hit and not suspected_paid_promotion(e, p):
            channels.setdefault(e.video.channel_id, e.video.channel_title)
    n = len(channels)
    score = clamp(n / p.new_channel_target * 100)
    return ScoreComponent(
        "new_channel_proof",
        score,
        p.weights.get("new_channel_proof", 0),
        {"new_channels_with_hits": n, "target": p.new_channel_target, "channels": sorted(channels.values())[:15]},
        f"{n} channel(s) created in the last 12 months have a {p.hit_views:,}+ view video here "
        f"({p.new_channel_target}+ scores 100).",
    )


def score_consistency(pool: list[EnrichedVideo], sample: list[EnrichedVideo], p: ScoringParams) -> ScoreComponent:
    hits = [e for e in unique(pool + sample) if is_small(e, p) and e.is_hit and not suspected_paid_promotion(e, p)]
    channels = {e.video.channel_id for e in hits}
    views = [e.video.view_count or 0 for e in hits]
    top_share = max(views) / sum(views) if views and sum(views) else 1.0
    spread = clamp(len(channels) / p.consistency_channel_target * 100)
    score = 0.5 * spread + 0.5 * (1 - top_share) * 100 if hits else 0.0
    return ScoreComponent(
        "consistency",
        score,
        p.weights.get("consistency", 0),
        {"small_channel_hits": len(hits), "distinct_channels": len(channels),
         "top_video_view_share": round(top_share, 3), "channel_target": p.consistency_channel_target},
        f"Small-channel hits come from {len(channels)} different channel(s); the single biggest hit holds "
        f"{top_share:.0%} of their combined views. Many channels + low top share = repeatable, not one lucky video.",
    )


def score_monetization(estimate: dict[str, Any], p: ScoringParams) -> ScoreComponent:
    return ScoreComponent(
        "monetization",
        float(estimate["score"]),
        p.weights.get("monetization", 0),
        estimate,
        f"ESTIMATE, not data: {estimate['tier']} RPM tier for {p.fmt} "
        f"(~{estimate['rpm_range_usd']} per 1,000 views) based on {estimate['basis']}.",
    )


# ---------------------------------------------------------------- aggregate
def confidence_flags(pool: list[EnrichedVideo], sample: list[EnrichedVideo], opportunity: ScoreComponent,
                     p: ScoringParams) -> list[str]:
    flags = []
    n = len(unique(pool + sample))
    if n < p.min_sample_videos:
        flags.append(f"Only {n} {p.fmt} videos analysed (< {p.min_sample_videos}).")
    hits = opportunity.raw["small_channel_hits"]
    if hits < p.min_small_channel_hits:
        flags.append(f"Only {hits} small-channel hit(s) in the base sample (< {p.min_small_channel_hits}).")
    if "biased" in opportunity.raw["base_rate_source"]:
        flags.append("Date-ordered sample too small; hit share computed from view-ordered results (optimistic).")
    known = [e for e in pool if e.subs is not None]
    if pool and len(known) < 0.7 * len(pool):
        flags.append("Many channels hide subscriber counts; small/large split is uncertain.")
    return flags


def final_score(components: list[ScoreComponent]) -> float:
    total_w = sum(c.weight for c in components)
    return sum(c.score * c.weight for c in components) / total_w if total_w else 0.0


def score_niche(pool: list[EnrichedVideo], sample: list[EnrichedVideo], monetization: dict[str, Any],
                p: ScoringParams) -> dict[str, Any]:
    opportunity = score_opportunity(pool, sample, p)
    components = [
        opportunity,
        score_new_channel_proof(pool, sample, p),
        score_velocity(pool, sample, p),
        score_consistency(pool, sample, p),
        score_competition(pool, p),
        score_monetization(monetization, p),
    ]
    flags = confidence_flags(pool, sample, opportunity, p)
    promo = sum(1 for e in unique(pool + sample) if suspected_paid_promotion(e, p))
    return {
        "final_score": round(final_score(components), 1),
        "components": {c.name: c.to_dict() for c in components},
        "low_confidence": bool(flags),
        "confidence_flags": flags,
        "suspected_paid_promotion_excluded": promo,
    }
