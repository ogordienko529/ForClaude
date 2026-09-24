"""Pure functions: join videos with their channels and compute outlier metrics. No I/O."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .durations import SHORT
from .models import Channel, Video, to_iso

METRIC_SUBS = "subs"                          # views / channel subscribers
METRIC_CHANNEL_RELATIVE = "channel_relative"  # views / (channel views / channel video count)
METRIC_EITHER = "either"
OUTLIER_METRICS = (METRIC_SUBS, METRIC_CHANNEL_RELATIVE, METRIC_EITHER)


@dataclass
class EnrichedVideo:
    video: Video
    channel: Channel | None
    age_days: float | None
    views_per_day: float | None
    sub_outlier_score: float | None        # None when subs are hidden or channel unknown
    channel_relative_score: float | None   # None when channel views/video count unavailable
    is_new_channel: bool | None            # channel created within new_channel_max_age_days
    is_hit: bool                           # views >= format hit threshold
    hit_within_14d: bool                   # a hit while still <= 14 days old (direct evidence)

    @property
    def subs(self) -> int | None:
        return self.channel.subscriber_count if self.channel else None

    @property
    def is_short(self) -> bool:
        return self.video.format_class == SHORT

    @property
    def primary_score(self) -> float | None:
        """Shorts prefer the channel-relative score (Shorts subs are a weak signal); long-form prefers subs."""
        order = (
            (self.channel_relative_score, self.sub_outlier_score)
            if self.is_short
            else (self.sub_outlier_score, self.channel_relative_score)
        )
        return next((s for s in order if s is not None), None)

    @property
    def primary_metric(self) -> str | None:
        if self.primary_score is None:
            return None
        if self.is_short:
            return METRIC_CHANNEL_RELATIVE if self.channel_relative_score is not None else METRIC_SUBS
        return METRIC_SUBS if self.sub_outlier_score is not None else METRIC_CHANNEL_RELATIVE

    def to_dict(self) -> dict[str, Any]:
        v, c = self.video, self.channel
        return {
            "video_id": v.video_id,
            "title": v.title,
            "url": v.url,
            "format": v.format_class,
            "channel_id": v.channel_id,
            "channel_title": v.channel_title,
            "channel_subs": self.subs,
            "channel_subs_hidden": c.subs_hidden if c else None,
            "channel_video_count": c.video_count if c else None,
            "channel_created": to_iso(c.published_at) if c else None,
            "is_new_channel": self.is_new_channel,
            "views": v.view_count,
            "likes": v.like_count,
            "comments": v.comment_count,
            "duration_s": v.duration_s,
            "published_at": to_iso(v.published_at),
            "age_days": _round(self.age_days, 1),
            "views_per_day": _round(self.views_per_day, 0),
            "sub_outlier_score": _round(self.sub_outlier_score, 2),
            "channel_relative_score": _round(self.channel_relative_score, 2),
            "primary_metric": self.primary_metric,
            "primary_score": _round(self.primary_score, 2),
            "hit_within_14d": self.hit_within_14d,
        }


def _round(x: float | None, nd: int) -> float | None:
    if x is None:
        return None
    return round(x, nd) if nd else round(x)


def enrich(
    videos: list[Video],
    channels: dict[str, Channel],
    *,
    now: datetime,
    hit_views: dict[str, int],
    sub_floor: int = 100,
    new_channel_max_age_days: int = 365,
) -> list[EnrichedVideo]:
    """hit_views: {'shorts': N, 'long': M} — thresholds differ per format."""
    out = []
    for v in videos:
        c = channels.get(v.channel_id)
        views = v.view_count or 0
        sub_score = None
        rel_score = None
        is_new = None
        if c is not None:
            if c.subscriber_count is not None:
                sub_score = views / max(c.subscriber_count, sub_floor)
            avg = c.avg_views_per_video
            if avg:
                rel_score = views / avg
            age_c = c.age_days(now)
            is_new = age_c is not None and age_c <= new_channel_max_age_days
        threshold = hit_views["shorts" if v.format_class == SHORT else "long"]
        # Views are as of the fetch, so ages/velocity are measured at fetch time, not "now"
        # (matters when cached data is reused hours or days later).
        as_of = v.fetched_at if v.fetched_at and v.fetched_at <= now else now
        age = v.age_days(as_of)
        is_hit = views >= threshold
        out.append(
            EnrichedVideo(
                video=v,
                channel=c,
                age_days=age,
                views_per_day=v.views_per_day(as_of),
                sub_outlier_score=sub_score,
                channel_relative_score=rel_score,
                is_new_channel=is_new,
                is_hit=is_hit,
                hit_within_14d=is_hit and age is not None and age <= 14,
            )
        )
    return out


def select_outliers(
    enriched: list[EnrichedVideo],
    *,
    min_outlier_score: float,
    max_channel_subs: int,
    metric: str = METRIC_SUBS,
) -> tuple[list[EnrichedVideo], dict[str, int]]:
    """Keep videos from small channels whose chosen metric >= min_outlier_score.

    Channels with hidden subscriber counts can't be confirmed as small, so they are excluded
    (and counted). Returns (outliers sorted by primary score desc, rejection counts).
    """
    if metric not in OUTLIER_METRICS:
        raise ValueError(f"metric must be one of {OUTLIER_METRICS}")
    rejected = {"channel_unknown": 0, "subs_hidden": 0, "channel_too_big": 0, "below_threshold": 0}
    kept = []
    for e in enriched:
        if e.channel is None:
            rejected["channel_unknown"] += 1
            continue
        if e.subs is None:
            rejected["subs_hidden"] += 1
            continue
        if e.subs > max_channel_subs:
            rejected["channel_too_big"] += 1
            continue
        scores = {
            METRIC_SUBS: [e.sub_outlier_score],
            METRIC_CHANNEL_RELATIVE: [e.channel_relative_score],
            METRIC_EITHER: [e.sub_outlier_score, e.channel_relative_score],
        }[metric]
        if not any(s is not None and s >= min_outlier_score for s in scores):
            rejected["below_threshold"] += 1
            continue
        kept.append(e)
    kept.sort(key=lambda e: (e.primary_score or 0, e.video.view_count or 0), reverse=True)
    return kept, rejected
