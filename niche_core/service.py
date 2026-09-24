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
from .patterns import expand_candidates
from .report import build_insights, export_markdown, render_analysis_markdown, render_compare_markdown
from .rpm import estimate_monetization
from .scoring import ScoringParams, score_niche
from .enrich import METRIC_SUBS, OUTLIER_METRICS, EnrichedVideo, enrich, select_outliers
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
    published_before_days: int = 0  # >0: only videos at least this old (unbiased base-rate sample)

    def cache_params(self) -> dict[str, Any]:
        params = {
            "videoDuration": self.video_duration,
            "published_within_days": self.published_within_days,
            "maxResults": self.max_results,
            "order": self.order,
            "regionCode": self.region_code,
            "relevanceLanguage": self.relevance_language,
        }
        if self.published_before_days:
            params["published_before_days"] = self.published_before_days
        return params

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
        published_before_days: int = 0,
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
                published_before_days=int(published_before_days),
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
                published_after = _rfc3339(now - timedelta(days=spec.published_within_days))
                published_before = (
                    _rfc3339(now - timedelta(days=spec.published_before_days)) if spec.published_before_days else None
                )
                try:
                    ids = self.client.search_video_ids(
                        spec.query,
                        max_results=spec.max_results,
                        video_duration=spec.video_duration,
                        published_after=published_after,
                        published_before=published_before,
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
        groups, channels, excluded = self.collect_groups({"all": specs}, fmt, with_channels, errors)
        return groups["all"], channels, excluded

    def collect_groups(
        self, groups: dict[str, list[SearchSpec]], fmt: str, with_channels: bool, errors: list[str]
    ) -> tuple[dict[str, list[Video]], dict[str, Channel], dict[str, int]]:
        """Like collect() for several search groups, sharing one batched videos/channels fetch."""
        ids_by_group = {name: self.run_searches(specs, errors) for name, specs in groups.items()}
        all_ids = list(dict.fromkeys(i for ids in ids_by_group.values() for i in ids))
        videos = self.fetch_videos(all_ids, errors)
        allowed = FORMAT_CLASSES[validate_format(fmt)]
        first = next((specs[0] for specs in groups.values() if specs), None)
        lang = first.relevance_language if first else ""
        filter_lang = bool(lang) and self.config.search.get("filter_by_audio_language", True)
        excluded = {
            c: 0 for c in (SHORT_LONGFORM, SHORT_UNVERIFIED, LIVE, "other_format", "no_views", "other_language")
        }
        kept_ids: set[str] = set()
        for vid in all_ids:
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
            if filter_lang and not language_matches(v.default_audio_language, lang):
                excluded["other_language"] += 1
                continue
            kept_ids.add(vid)
        out = {name: [videos[i] for i in ids if i in kept_ids] for name, ids in ids_by_group.items()}
        kept = [videos[i] for i in all_ids if i in kept_ids]
        channels = self.fetch_channels([v.channel_id for v in kept], errors) if with_channels else {}
        return out, channels, excluded

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

    def enrich(self, videos: list[Video], channels: dict[str, Channel]) -> list[EnrichedVideo]:
        t = self.config.thresholds
        return enrich(
            videos,
            channels,
            now=self.clock(),
            hit_views={f: int(self.config.bands(f)["hit_views"]) for f in ("shorts", "long")},
            sub_floor=int(t["outlier_sub_floor"]),
            new_channel_max_age_days=int(t["new_channel_max_age_days"]),
        )

    def find_outliers(
        self,
        query: str,
        format: str = "both",
        min_outlier_score: float = 10,
        max_channel_subs: int | None = None,
        metric: str = METRIC_SUBS,
        published_within_days: int | None = None,
        max_results: int | None = None,
        region_code: str | None = None,
        relevance_language: str | None = None,
        limit: int = 50,
        dry_run: bool = False,
        max_units: int | None = None,
    ) -> dict[str, Any]:
        fmt = validate_format(format)
        if metric not in OUTLIER_METRICS:
            raise ValueError(f"metric must be one of {OUTLIER_METRICS}")
        max_subs = max_channel_subs if max_channel_subs is not None else self.config.thresholds["small_channel_max_subs"]
        days = published_within_days or self.config.search["published_within_days"]
        n = max_results or self.config.search["max_results"]
        specs = self.make_specs(query, fmt, days, n, "viewCount", region_code, relevance_language)
        est = self.estimate_collect(specs, with_channels=True)
        result: dict[str, Any] = {
            "tool": "find_outliers",
            "query": query,
            "format": fmt,
            "params": {
                "min_outlier_score": min_outlier_score,
                "max_channel_subs": max_subs,
                "metric": metric,
                "published_within_days": days,
                "duration_buckets": list(FORMAT_DURATIONS[fmt]),
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
        channels: dict[str, Channel] = {}
        excluded: dict[str, int] = {}
        try:
            videos, channels, excluded = self.collect(specs, fmt, with_channels=True, errors=errors)
        except QuotaExceededError as exc:
            errors.append(str(exc))
            result["partial"] = True
        enriched = self.enrich(videos, channels)
        outliers, rejected = select_outliers(
            enriched, min_outlier_score=min_outlier_score, max_channel_subs=max_subs, metric=metric
        )
        result.update(
            {
                "scanned": len(enriched),
                "count": len(outliers),
                "outliers": [e.to_dict() for e in outliers[:limit]],
                "rejected": rejected,
                "excluded": excluded,
                "summary": {
                    "distinct_channels": len({e.video.channel_id for e in outliers}),
                    "new_channels": len({e.video.channel_id for e in outliers if e.is_new_channel}),
                    "hits_within_14d": sum(1 for e in outliers if e.hit_within_14d),
                },
                "data_quality": {
                    **_video_quality(videos),
                    "channels_subs_hidden": sum(1 for c in channels.values() if c.subs_hidden),
                },
                "notes": [
                    "sub_outlier_score = views / max(subs, outlier_sub_floor)",
                    "channel_relative_score = views / (channel views / channel video count)",
                    "Shorts are ranked by channel_relative_score, long-form by sub_outlier_score.",
                ],
                "errors": errors,
                "quota": self.receipt(est["total"], start).to_dict(),
            }
        )
        return result

    def scoring_params(self, fmt: str) -> ScoringParams:
        t, b = self.config.thresholds, self.config.bands(fmt)
        return ScoringParams(
            fmt=fmt,
            hit_views=int(b["hit_views"]),
            velocity_low=float(b["velocity_views_per_day_low"]),
            velocity_high=float(b["velocity_views_per_day_high"]),
            outlier_median_low=float(b["outlier_median_low"]),
            outlier_median_high=float(b["outlier_median_high"]),
            hit_share_high=float(b["hit_share_high"]),
            small_channel_max_subs=int(t["small_channel_max_subs"]),
            large_channel_min_subs=int(t["large_channel_min_subs"]),
            new_channel_target=int(t["new_channel_target"]),
            consistency_channel_target=int(t["consistency_channel_target"]),
            promo_avg_views_per_sub=float(t["promo_avg_views_per_sub"]),
            min_sample_videos=int(t["min_sample_videos"]),
            min_small_channel_hits=int(t["min_small_channel_hits"]),
            weights=self.config.weights,
        )

    def analysis_specs(
        self, query: str, fmt: str, days: int, n: int, region_code: str | None, relevance_language: str | None
    ) -> dict[str, list[SearchSpec]]:
        """pool = view-ordered (what wins); sample = date-ordered uploads at least N days old (base rates)."""
        min_age = int(self.config.thresholds["sample_min_age_days"])
        return {
            "pool": self.make_specs(query, fmt, days, n, "viewCount", region_code, relevance_language),
            "sample": self.make_specs(query, fmt, days, n, "date", region_code, relevance_language, min_age),
        }

    def analyze_niche(
        self,
        query: str,
        format: str = "both",
        published_within_days: int | None = None,
        max_results: int | None = None,
        region_code: str | None = None,
        relevance_language: str | None = None,
        export: bool = False,
        dry_run: bool = False,
        max_units: int | None = None,
    ) -> dict[str, Any]:
        fmt = validate_format(format)
        days = published_within_days or self.config.search["published_within_days"]
        n = max_results or self.config.search["max_results"]
        groups = self.analysis_specs(query, fmt, days, n, region_code, relevance_language)
        est = self.estimate_collect(groups["pool"] + groups["sample"], with_channels=True)
        first = groups["pool"][0]
        result: dict[str, Any] = {
            "tool": "analyze_niche",
            "query": query,
            "format": fmt,
            "params": {
                "published_within_days": days,
                "max_results_per_search": n,
                "duration_buckets": list(FORMAT_DURATIONS[fmt]),
                "sample_min_age_days": groups["sample"][0].published_before_days,
                "region_code": first.region_code,
                "relevance_language": first.relevance_language,
            },
            "quota_estimate": est,
        }
        if dry_run:
            result["quota"] = self.receipt(est["total"], self.quota.session_units, "dry run: nothing spent").to_dict()
            return result
        self._check_budget(est["total"], max_units)

        start = self.quota.session_units
        errors: list[str] = []
        videos_by_group: dict[str, list[Video]] = {"pool": [], "sample": []}
        channels: dict[str, Channel] = {}
        excluded: dict[str, int] = {}
        try:
            videos_by_group, channels, excluded = self.collect_groups(groups, fmt, with_channels=True, errors=errors)
        except QuotaExceededError as exc:
            errors.append(str(exc))
            result["partial"] = True

        formats: dict[str, Any] = {}
        for f in (("shorts", "long") if fmt == "both" else (fmt,)):
            cls = SHORT if f == "shorts" else LONG
            pool = self.enrich([v for v in videos_by_group["pool"] if v.format_class == cls], channels)
            sample = self.enrich([v for v in videos_by_group["sample"] if v.format_class == cls], channels)
            params = self.scoring_params(f)
            categories = [e.video.category_id for e in pool + sample]
            monetization = estimate_monetization(query, categories, f, self.config.monetization)
            formats[f] = {
                **score_niche(pool, sample, monetization, params),
                **build_insights(pool, sample, query, params),
            }
        best = max(formats, key=lambda f: formats[f]["final_score"])
        result.update(
            {
                "final_score": formats[best]["final_score"],
                "best_format": best,
                "low_confidence": formats[best]["low_confidence"],
                "formats": formats,
                "excluded": excluded,
                "data_quality": {
                    "channels_subs_hidden": sum(1 for c in channels.values() if c.subs_hidden),
                    "channels": len(channels),
                },
                "errors": errors,
                "quota": self.receipt(est["total"], start).to_dict(),
            }
        )
        result["summary_markdown"] = render_analysis_markdown(result)
        if export:
            path = export_markdown(result["summary_markdown"], self.config.reports_dir,
                                   f"{query}-{fmt}", self.clock())
            result["exported_to"] = str(path)
        return result

    def compare_niches(
        self,
        queries: list[str],
        format: str = "both",
        published_within_days: int | None = None,
        max_results: int | None = None,
        region_code: str | None = None,
        relevance_language: str | None = None,
        export: bool = False,
        dry_run: bool = False,
        max_units: int | None = None,
    ) -> dict[str, Any]:
        fmt = validate_format(format)
        queries = [q.strip() for q in dict.fromkeys(queries) if q and q.strip()]
        if not queries:
            raise ValueError("queries must contain at least one niche")
        days = published_within_days or self.config.search["published_within_days"]
        n = max_results or self.config.search["max_results"]
        per_query = {}
        for q in queries:
            groups = self.analysis_specs(q, fmt, days, n, region_code, relevance_language)
            per_query[q] = self.estimate_collect(groups["pool"] + groups["sample"], with_channels=True)["total"]
        est = sum(per_query.values())
        result: dict[str, Any] = {
            "tool": "compare_niches",
            "format": fmt,
            "queries": queries,
            "quota_estimate": {"total": est, "per_query": per_query},
        }
        if dry_run:
            result["quota"] = self.receipt(est, self.quota.session_units, "dry run: nothing spent").to_dict()
            return result
        self._check_budget(est, max_units)

        start = self.quota.session_units
        rows: list[dict[str, Any]] = []
        reports: dict[str, Any] = {}
        for q in queries:
            try:
                r = self.analyze_niche(q, fmt, days, n, region_code, relevance_language)
            except QuotaBudgetError as exc:  # remaining quota ran out between niches
                rows.append({"query": q, "error": str(exc), "final_score": -1})
                continue
            best = r["formats"][r["best_format"]]
            rows.append(
                {
                    "query": q,
                    "final_score": r["final_score"],
                    "best_format": r["best_format"],
                    "low_confidence": r["low_confidence"],
                    "components": {k: v["score"] for k, v in best["components"].items()},
                    "rpm_tier": best["components"]["monetization"]["raw"]["tier"],
                    "confidence_flags": best["confidence_flags"],
                    "partial": r.get("partial", False),
                    "errors": r["errors"],
                }
            )
            reports[q] = r
        rows.sort(key=lambda r: r["final_score"], reverse=True)
        table = render_compare_markdown(rows, fmt)
        result.update(
            {
                "ranking": rows,
                "table_markdown": table,
                "top_outliers_by_niche": {
                    q: r["formats"][r["best_format"]]["top_outliers"][:3] for q, r in reports.items()
                },
                "quota": self.receipt(est, start).to_dict(),
            }
        )
        if export:
            md = table + "\n\n" + "\n\n---\n\n".join(r["summary_markdown"] for r in reports.values())
            result["exported_to"] = str(export_markdown(md, self.config.reports_dir, f"compare-{fmt}", self.clock()))
        return result

    def expand_keywords(
        self,
        seed: str,
        format: str = "both",
        max_suggestions: int = 15,
        region_code: str | None = None,
        relevance_language: str | None = None,
        dry_run: bool = False,
        max_units: int | None = None,
    ) -> dict[str, Any]:
        """Sub-niche queries mined from titles and tags of the seed's outlier videos.

        Uses cached data only. If the seed was never searched, runs find_outliers once first
        (cost reported); there is no dedicated paid keyword API call.
        """
        fmt = validate_format(format)
        ids = self.store.video_ids_for_query(seed)
        est = 0
        if ids:
            # Cached videos are reused at any age; only channels missing from the cache cost units.
            channel_ids = {
                v.channel_id for v in self.store.get_videos(ids).values()
                if v.format_class in FORMAT_CLASSES[fmt] and v.view_count
            }
            fresh = self.store.get_channels(channel_ids, self.config.channel_ttl_hours)
            est = estimate_list_calls(len(channel_ids - fresh.keys()))
        else:
            specs = self.make_specs(seed, fmt, self.config.search["published_within_days"],
                                    self.config.search["max_results"], "viewCount", region_code, relevance_language)
            est = self.estimate_collect(specs, with_channels=True)["total"]
        result: dict[str, Any] = {
            "tool": "expand_keywords",
            "seed": seed,
            "format": fmt,
            "source": "cache" if ids else "find_outliers (seed not cached yet)",
        }
        if dry_run:
            result["quota"] = self.receipt(est, self.quota.session_units, "dry run: nothing spent").to_dict()
            return result
        self._check_budget(est, max_units)
        start = self.quota.session_units
        errors: list[str] = []
        if not ids:
            self.find_outliers(seed, fmt, region_code=region_code, relevance_language=relevance_language)
            ids = self.store.video_ids_for_query(seed)

        allowed = FORMAT_CLASSES[fmt]
        videos = [v for v in self.store.get_videos(ids).values() if v.format_class in allowed and v.view_count]
        try:
            channels = self.fetch_channels([v.channel_id for v in videos], errors)
        except QuotaExceededError as exc:
            errors.append(str(exc))
            channels = self.store.get_channels([v.channel_id for v in videos])
        enriched = self.enrich(videos, channels)
        small_max = self.config.thresholds["small_channel_max_subs"]
        small = [e for e in enriched if e.subs is not None and e.subs < small_max]
        basis = [e for e in small if e.is_hit] or small
        basis.sort(key=lambda e: e.primary_score or 0, reverse=True)
        basis = basis[:40]
        candidates = expand_candidates(
            [(e.video.channel_id, e.video.title, e.video.tags, e.primary_score or 0) for e in basis],
            seed,
            top=max_suggestions,
        )
        result.update(
            {
                "based_on": {"outlier_videos": len(basis), "channels": len({e.video.channel_id for e in basis})},
                "suggestions": candidates,
                "next_step": "Run compare_niches on the most promising suggestions (each costs ~100-400 units).",
                "errors": errors,
                "quota": self.receipt(est, start).to_dict(),
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


def language_matches(audio_language: str | None, wanted: str) -> bool:
    """Unknown audio language passes; 'en-US' matches 'en'."""
    if not audio_language or not wanted:
        return True
    return audio_language.lower().split("-")[0] == wanted.lower().split("-")[0]


def _rfc3339(dt: datetime) -> str:
    return to_iso(dt).replace("+00:00", "Z")
