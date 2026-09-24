"""Orchestration layer: cache-first data access with quota estimates and receipts.

Every public operation returns a JSON-serialisable dict containing a `quota` receipt
(estimated before running, actual after) and supports `dry_run` / `max_units`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .cache import Store, search_cache_key
from .config import Config, get_api_key, load_config
from .durations import LIVE, LONG, SHORT, SHORT_LONGFORM, SHORT_UNVERIFIED
from .models import Channel, QuotaReceipt, Video, to_iso, utcnow
from .quota import COSTS, QuotaTracker, estimate_list_calls, search_pages
from .youtube_client import QuotaExceededError, YouTubeAPIError, YouTubeClient

FORMATS = ("shorts", "long", "both")
# search.list videoDuration buckets per format: short < 4 min, medium 4-20 min, long > 20 min.
FORMAT_DURATIONS = {
    "shorts": ("short",),
    "long": ("medium", "long"),
    "both": ("short", "medium", "long"),
}
# Which locally-classified videos count for each format.
FORMAT_CLASSES = {
    "shorts": {SHORT},
    "long": {LONG},
    "both": {SHORT, LONG},
}


class QuotaBudgetError(Exception):
    """The estimate exceeds max_units or today's remaining quota; nothing was spent."""


@dataclass(frozen=True)
class SearchSpec:
    query: str
    video_duration: str
    published_within_days: int
    max_results: int
    order: str
    region_code: str
    relevance_language: str

    def cache_params(self) -> dict[str, Any]:
        return {
            "videoDuration": self.video_duration,
            "published_within_days": self.published_within_days,
            "maxResults": self.max_results,
            "order": self.order,
            "regionCode": self.region_code,
            "relevanceLanguage": self.relevance_language,
        }

    @property
    def key(self) -> str:
        return search_cache_key(self.query, self.cache_params())


def validate_format(fmt: str) -> str:
    fmt = (fmt or "").lower().strip()
    if fmt == "short":
        fmt = "shorts"
    if fmt not in FORMATS:
        raise ValueError(f"format must be one of {FORMATS}, got {fmt!r}")
    return fmt


class NicheService:
    def __init__(
        self,
        config: Config | None = None,
        store: Store | None = None,
        client: YouTubeClient | None = None,
        clock: Callable[[], datetime] = utcnow,
        purge_on_start: bool = True,
    ):
        self.config = config or load_config()
        self.clock = clock
        self.store = store or Store(self.config.db_path, clock=clock)
        # Share the client's tracker so "actual" cost reflects the calls it makes.
        self.quota = client.quota if client else QuotaTracker(self.store, self.config.daily_quota)
        self._client = client
        self.last_purge: dict[str, int] | None = None
        if purge_on_start:
            self.last_purge = self.store.purge(self.config.retention_days)

    @property
    def client(self) -> YouTubeClient:
        if self._client is None:
            self._client = YouTubeClient(get_api_key(), self.quota)
        return self._client

    # ================================================================ planning
    def make_specs(
        self,
        query: str,
        fmt: str,
        published_within_days: int,
        max_results: int,
        order: str = "viewCount",
        region_code: str | None = None,
        relevance_language: str | None = None,
    ) -> list[SearchSpec]:
        fmt = validate_format(fmt)
        region = region_code if region_code is not None else self.config.search["region_code"]
        lang = relevance_language if relevance_language is not None else self.config.search["relevance_language"]
        return [
            SearchSpec(
                query=query.strip(),
                video_duration=d,
                published_within_days=int(published_within_days),
                max_results=int(max_results),
                order=order,
                region_code=(region or "").upper(),
                relevance_language=(lang or "").lower(),
            )
            for d in FORMAT_DURATIONS[fmt]
        ]

    def estimate_collect(self, specs: list[SearchSpec], with_channels: bool) -> dict[str, Any]:
        """Upper-bound estimate: assumes every uncached result is new."""
        search_units = 0
        candidate_ids: set[str] = set()
        unknown_ids = 0
        for spec in specs:
            cached = self.store.get_search(spec.key, self.config.search_ttl_hours)
            if cached is None:
                search_units += search_pages(spec.max_results) * COSTS["search"]
                unknown_ids += spec.max_results
            else:
                candidate_ids.update(cached)
        fresh_videos = self.store.get_videos(candidate_ids, self.config.video_ttl_hours)
        stale_video_ids = candidate_ids - fresh_videos.keys()
        video_units = estimate_list_calls(len(stale_video_ids) + unknown_ids)

        channel_units = 0
        if with_channels:
            known_channels = {v.channel_id for v in fresh_videos.values()}
            fresh_channels = self.store.get_channels(known_channels, self.config.channel_ttl_hours)
            # Worst case: every not-yet-known video is from a different, uncached channel.
            channel_units = estimate_list_calls(
                len(known_channels - fresh_channels.keys()) + len(stale_video_ids) + unknown_ids
            )
        total = search_units + video_units + channel_units
        return {
            "total": total,
            "search": search_units,
            "videos": video_units,
            "channels": channel_units,
            "search_calls": search_units // COSTS["search"],
        }

    def _check_budget(self, estimated: int, max_units: int | None) -> None:
        if max_units is not None and estimated > max_units:
            raise QuotaBudgetError(f"Estimated cost {estimated} units exceeds max_units={max_units}; nothing was run.")
        remaining = self.quota.remaining()
        if estimated > remaining:
            raise QuotaBudgetError(
                f"Estimated cost {estimated} units exceeds today's remaining quota ({remaining}); nothing was run."
            )

    def receipt(self, estimated: int, start_units: int, note: str = "") -> QuotaReceipt:
        used = self.quota.used_today()
        return QuotaReceipt(
            estimated=estimated,
            actual=self.quota.session_units - start_units,
            used_today=used,
            remaining=max(self.config.daily_quota - used, 0),
            daily_limit=self.config.daily_quota,
            note=note,
        )

    # ================================================================ data access
    def run_searches(self, specs: list[SearchSpec], errors: list[str]) -> list[str]:
        """Return de-duplicated video IDs across specs, cache-first."""
        all_ids: list[str] = []
        now = self.clock()
        for spec in specs:
            ids = self.store.get_search(spec.key, self.config.search_ttl_hours)
            if ids is None:
                published_after = to_iso(now - timedelta(days=spec.published_within_days)).replace("+00:00", "Z")
                try:
                    ids = self.client.search_video_ids(
                        spec.query,
                        max_results=spec.max_results,
                        video_duration=spec.video_duration,
                        published_after=published_after,
                        order=spec.order,
                        region_code=spec.region_code or None,
                        relevance_language=spec.relevance_language or None,
                    )
                except QuotaExceededError:
                    raise
                except YouTubeAPIError as exc:
                    errors.append(f"search ({spec.video_duration}/{spec.order}): {exc}")
                    # Fall back to an expired cached result, if any.
                    ids = self.store.get_search(spec.key) or []
                else:
                    self.store.put_search(spec.key, spec.query, spec.cache_params(), ids)
            all_ids.extend(i for i in ids if i not in all_ids)
        return all_ids

    def fetch_videos(self, ids: list[str], errors: list[str]) -> dict[str, Video]:
        cached = self.store.get_videos(ids, self.config.video_ttl_hours)
        missing = [i for i in ids if i not in cached]
        if missing:
            try:
                items = self.client.list_videos(missing, self.config.shorts["player_max_height"])
                now = self.clock()
                videos = [Video.from_api(it, self.config.shorts["max_seconds"], now) for it in items]
                self.store.upsert_videos(videos, {it["id"]: it for it in items})
                cached.update({v.video_id: v for v in videos})
            except YouTubeAPIError as exc:
                errors.append(f"videos.list: {exc}")
                stale = self.store.get_videos(missing)  # any age within retention
                if stale:
                    errors.append(f"using {len(stale)} stale cached videos")
                cached.update(stale)
                if isinstance(exc, QuotaExceededError):
                    raise
        return cached

    def fetch_channels(self, ids: list[str], errors: list[str]) -> dict[str, Channel]:
        ids = [i for i in dict.fromkeys(ids) if i]
        cached = self.store.get_channels(ids, self.config.channel_ttl_hours)
        missing = [i for i in ids if i not in cached]
        if missing:
            try:
                items = self.client.list_channels(missing)
                now = self.clock()
                channels = [Channel.from_api(it, now) for it in items]
                self.store.upsert_channels(channels, {it["id"]: it for it in items})
                cached.update({c.channel_id: c for c in channels})
            except YouTubeAPIError as exc:
                errors.append(f"channels.list: {exc}")
                stale = self.store.get_channels(missing)
                if stale:
                    errors.append(f"using {len(stale)} stale cached channels")
                cached.update(stale)
                if isinstance(exc, QuotaExceededError):
                    raise
        return cached

    def collect(
        self, specs: list[SearchSpec], fmt: str, with_channels: bool, errors: list[str]
    ) -> tuple[list[Video], dict[str, Channel], dict[str, int]]:
        """Search -> videos (-> channels). Returns in-format videos, channels, excluded counts."""
        ids = self.run_searches(specs, errors)
        videos = self.fetch_videos(ids, errors)
        allowed = FORMAT_CLASSES[validate_format(fmt)]
        excluded = {c: 0 for c in (SHORT_LONGFORM, SHORT_UNVERIFIED, LIVE, "other_format", "no_views")}
        kept: list[Video] = []
        for vid in ids:
            v = videos.get(vid)
            if v is None:
                continue
            if v.format_class not in allowed:
                key = v.format_class if v.format_class in excluded else "other_format"
                excluded[key] += 1
                continue
            if v.view_count is None:
                excluded["no_views"] += 1
                continue
            kept.append(v)
        channels = self.fetch_channels([v.channel_id for v in kept], errors) if with_channels else {}
        return kept, channels, excluded

    # ================================================================ tools
    def search_niche(
        self,
        query: str,
        format: str = "both",
        published_within_days: int | None = None,
        max_results: int | None = None,
        region_code: str | None = None,
        relevance_language: str | None = None,
        order: str = "viewCount",
        dry_run: bool = False,
        max_units: int | None = None,
    ) -> dict[str, Any]:
        fmt = validate_format(format)
        days = published_within_days or self.config.search["published_within_days"]
        n = max_results or self.config.search["max_results"]
        specs = self.make_specs(query, fmt, days, n, order, region_code, relevance_language)
        est = self.estimate_collect(specs, with_channels=False)
        result: dict[str, Any] = {
            "tool": "search_niche",
            "query": query,
            "format": fmt,
            "params": {
                "published_within_days": days,
                "max_results_per_duration_bucket": n,
                "duration_buckets": list(FORMAT_DURATIONS[fmt]),
                "order": order,
                "region_code": specs[0].region_code,
                "relevance_language": specs[0].relevance_language,
            },
            "quota_estimate": est,
        }
        if dry_run:
            result["quota"] = self.receipt(est["total"], self.quota.session_units, "dry run: nothing spent").to_dict()
            return result
        self._check_budget(est["total"], max_units)

        start = self.quota.session_units
        errors: list[str] = []
        videos: list[Video] = []
        excluded: dict[str, int] = {}
        try:
            videos, _, excluded = self.collect(specs, fmt, with_channels=False, errors=errors)
        except QuotaExceededError as exc:
            errors.append(str(exc))
            result["partial"] = True
        now = self.clock()
        videos.sort(key=lambda v: v.view_count or 0, reverse=True)
        result.update(
            {
                "count": len(videos),
                "videos": [_video_summary(v, now) for v in videos],
                "excluded": excluded,
                "data_quality": _video_quality(videos),
                "errors": errors,
                "quota": self.receipt(est["total"], start).to_dict(),
            }
        )
        return result

    def get_channel_stats(
        self, channel_ids: list[str], dry_run: bool = False, max_units: int | None = None
    ) -> dict[str, Any]:
        ids = [c.strip() for c in channel_ids if c and c.strip()]
        cached = self.store.get_channels(ids, self.config.channel_ttl_hours)
        est = estimate_list_calls(len(set(ids) - cached.keys()))
        result: dict[str, Any] = {"tool": "get_channel_stats", "requested": len(ids)}
        if dry_run:
            result["quota"] = self.receipt(est, self.quota.session_units, "dry run: nothing spent").to_dict()
            return result
        self._check_budget(est, max_units)
        start = self.quota.session_units
        errors: list[str] = []
        channels: dict[str, Channel] = {}
        try:
            channels = self.fetch_channels(ids, errors)
        except QuotaExceededError as exc:
            errors.append(str(exc))
            result["partial"] = True
        now = self.clock()
        result.update(
            {
                "channels": [channels[i].to_dict(now) for i in ids if i in channels],
                "not_found": [i for i in ids if i not in channels],
                "hidden_subscriber_counts": sum(1 for c in channels.values() if c.subs_hidden),
                "errors": errors,
                "quota": self.receipt(est, start).to_dict(),
            }
        )
        return result

    def quota_status(self) -> dict[str, Any]:
        return {"tool": "quota_status", **self.quota.status()}

    def purge(self) -> dict[str, Any]:
        deleted = self.store.purge(self.config.retention_days)
        return {
            "tool": "purge",
            "retention_days": self.config.retention_days,
            "deleted": deleted,
            "remaining_rows": self.store.counts(),
        }


def _video_summary(v: Video, now: datetime) -> dict[str, Any]:
    vpd = v.views_per_day(now)
    age = v.age_days(now)
    return {
        "video_id": v.video_id,
        "title": v.title,
        "channel_id": v.channel_id,
        "channel_title": v.channel_title,
        "format": v.format_class,
        "views": v.view_count,
        "likes": v.like_count,
        "comments": v.comment_count,
        "duration_s": v.duration_s,
        "published_at": to_iso(v.published_at),
        "age_days": round(age, 1) if age is not None else None,
        "views_per_day": round(vpd) if vpd is not None else None,
        "url": v.url,
    }


def _video_quality(videos: list[Video]) -> dict[str, int]:
    return {
        "videos": len(videos),
        "likes_hidden": sum(1 for v in videos if v.like_count is None),
        "comments_disabled": sum(1 for v in videos if v.comment_count is None),
    }
