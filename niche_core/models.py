"""Data model. Counts the API hides or omits are None, never 0."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .durations import classify_format, parse_iso8601_duration


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_rfc3339(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def to_iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds") if dt else None


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class Video:
    video_id: str
    channel_id: str
    channel_title: str
    title: str
    published_at: datetime | None
    duration_s: int | None
    format_class: str
    view_count: int | None = None
    like_count: int | None = None        # None when likes are hidden/disabled
    comment_count: int | None = None     # None when comments are disabled
    tags: list[str] = field(default_factory=list)
    category_id: str | None = None
    embed_width: int | None = None
    embed_height: int | None = None
    default_audio_language: str | None = None
    live_broadcast_content: str | None = None
    fetched_at: datetime | None = None

    @property
    def url(self) -> str:
        if self.format_class == "short":
            return f"https://www.youtube.com/shorts/{self.video_id}"
        return f"https://www.youtube.com/watch?v={self.video_id}"

    def age_days(self, now: datetime | None = None) -> float | None:
        if not self.published_at:
            return None
        now = now or utcnow()
        return max((now - self.published_at).total_seconds() / 86400, 0.0)

    def views_per_day(self, now: datetime | None = None) -> float | None:
        age = self.age_days(now)
        if self.view_count is None or age is None:
            return None
        # Floor at 1 day so a video that is 2 hours old isn't extrapolated x12.
        return self.view_count / max(age, 1.0)

    @classmethod
    def from_api(cls, item: dict, shorts_max_seconds: int = 180, fetched_at: datetime | None = None) -> "Video":
        snippet = item.get("snippet", {}) or {}
        stats = item.get("statistics", {}) or {}
        details = item.get("contentDetails", {}) or {}
        player = item.get("player", {}) or {}
        duration = parse_iso8601_duration(details.get("duration"))
        width = _int_or_none(player.get("embedWidth"))
        height = _int_or_none(player.get("embedHeight"))
        live = snippet.get("liveBroadcastContent")
        return cls(
            video_id=item["id"],
            channel_id=snippet.get("channelId", ""),
            channel_title=snippet.get("channelTitle", ""),
            title=snippet.get("title", ""),
            published_at=parse_rfc3339(snippet.get("publishedAt")),
            duration_s=duration,
            format_class=classify_format(duration, width, height, live, shorts_max_seconds),
            view_count=_int_or_none(stats.get("viewCount")),
            like_count=_int_or_none(stats.get("likeCount")),
            comment_count=_int_or_none(stats.get("commentCount")),
            tags=list(snippet.get("tags", []) or []),
            category_id=snippet.get("categoryId"),
            embed_width=width,
            embed_height=height,
            default_audio_language=snippet.get("defaultAudioLanguage"),
            live_broadcast_content=live,
            fetched_at=fetched_at or utcnow(),
        )

    def to_dict(self, now: datetime | None = None) -> dict[str, Any]:
        d = asdict(self)
        d["published_at"] = to_iso(self.published_at)
        d["fetched_at"] = to_iso(self.fetched_at)
        d["url"] = self.url
        age = self.age_days(now)
        vpd = self.views_per_day(now)
        d["age_days"] = round(age, 2) if age is not None else None
        d["views_per_day"] = round(vpd, 1) if vpd is not None else None
        return d


@dataclass
class Channel:
    channel_id: str
    title: str
    subscriber_count: int | None     # None when hidden
    subs_hidden: bool
    view_count: int | None
    video_count: int | None
    published_at: datetime | None
    country: str | None = None
    fetched_at: datetime | None = None

    @property
    def avg_views_per_video(self) -> float | None:
        if self.view_count is None or not self.video_count:
            return None
        return self.view_count / self.video_count

    def age_days(self, now: datetime | None = None) -> float | None:
        if not self.published_at:
            return None
        return max(((now or utcnow()) - self.published_at).total_seconds() / 86400, 0.0)

    @classmethod
    def from_api(cls, item: dict, fetched_at: datetime | None = None) -> "Channel":
        snippet = item.get("snippet", {}) or {}
        stats = item.get("statistics", {}) or {}
        hidden = bool(stats.get("hiddenSubscriberCount", False))
        return cls(
            channel_id=item["id"],
            title=snippet.get("title", ""),
            subscriber_count=None if hidden else _int_or_none(stats.get("subscriberCount")),
            subs_hidden=hidden,
            view_count=_int_or_none(stats.get("viewCount")),
            video_count=_int_or_none(stats.get("videoCount")),
            published_at=parse_rfc3339(snippet.get("publishedAt")),
            country=snippet.get("country"),
            fetched_at=fetched_at or utcnow(),
        )

    def to_dict(self, now: datetime | None = None) -> dict[str, Any]:
        d = asdict(self)
        d["published_at"] = to_iso(self.published_at)
        d["fetched_at"] = to_iso(self.fetched_at)
        avg = self.avg_views_per_video
        d["avg_views_per_video"] = round(avg, 1) if avg is not None else None
        age = self.age_days(now)
        d["age_days"] = round(age, 1) if age is not None else None
        d["url"] = f"https://www.youtube.com/channel/{self.channel_id}"
        return d


@dataclass
class QuotaReceipt:
    estimated: int
    actual: int
    used_today: int
    remaining: int
    daily_limit: int
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
