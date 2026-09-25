"""MCP server: a thin wrapper exposing niche_core.NicheService as tools.

Run:  python -m niche_mcp   (stdio transport)
Every tool returns JSON with a `quota` receipt (estimated vs actual units). Pass
dry_run=true to get only the estimate, or max_units to refuse anything more expensive.
"""

from __future__ import annotations

import functools
import threading
from typing import Any, Literal

try:  # mcp >= 2.0 renamed FastMCP to MCPServer
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from niche_core.config import ConfigError
from niche_core.service import NicheService, QuotaBudgetError
from niche_core.youtube_client import MissingAPIKeyError, YouTubeAPIError

Format = Literal["shorts", "long", "both"]
OutlierMetric = Literal["subs", "channel_relative", "either"]

INSTRUCTIONS = """YouTube niche research on the official YouTube Data API v3 (10,000 quota units/day).
Goal: find niches where NEW or SMALL channels get 10k+ views per video within 1-14 days, scored on
earning potential too. Typical flow: expand_keywords(seed) -> compare_niches(candidates) ->
analyze_niche(best). search costs 100 units per call; analyze_niche costs ~200 (shorts) to ~400
(long) units uncached, ~600 for both. Results are cached (24h videos/searches, 7d channels),
so re-running is nearly free. Call with dry_run=true first when unsure about cost.
Omitted optional arguments (region_code, relevance_language, published_within_days, max_results,
max_channel_subs) use the config defaults (US, en, 30 days, 50 per search, 50,000 subs).
Monetization numbers are ESTIMATES, not API data."""

mcp = _Server("youtube-niche-research", instructions=INSTRUCTIONS)


@functools.lru_cache(maxsize=1)
def service() -> NicheService:
    return NicheService()


# Sync tools run on worker threads and clients call tools in parallel; the service holds one
# SQLite connection and quota counters, so calls are serialised.
_LOCK = threading.Lock()


def _safe(fn):
    """Serialise calls and turn expected failures into structured errors the model can act on."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs) -> dict[str, Any]:
        try:
            with _LOCK:
                return fn(*args, **kwargs)
        except MissingAPIKeyError as exc:
            return {"error": str(exc), "error_type": "missing_api_key"}
        except QuotaBudgetError as exc:
            return {"error": str(exc), "error_type": "quota_budget", "quota_status": service().quota_status()}
        except (ValueError, ConfigError) as exc:
            return {"error": str(exc), "error_type": "invalid_argument"}
        except YouTubeAPIError as exc:
            return {"error": str(exc), "error_type": "youtube_api", "reason": exc.reason}

    return wrapper


@mcp.tool()
@_safe
def search_niche(
    query: str,
    format: Format = "both",
    published_within_days: int | None = None,
    max_results: int | None = None,
    region_code: str | None = None,
    relevance_language: str | None = None,
    dry_run: bool = False,
    max_units: int | None = None,
) -> dict[str, Any]:
    """Recent videos for a query with views, likes, comments, duration, publish date and channel id.

    format: shorts (<=180s AND vertical), long (4-20 min and 20+ min searches), or both.
    max_results is per duration bucket (long = 2 buckets, both = 3). ~100 units per bucket uncached.
    """
    return service().search_niche(query, format, published_within_days, max_results, region_code,
                                  relevance_language, dry_run=dry_run, max_units=max_units)


@mcp.tool()
@_safe
def get_channel_stats(channel_ids: list[str], dry_run: bool = False, max_units: int | None = None) -> dict[str, Any]:
    """Subscribers (None if hidden), total views, video count, creation date and avg views/video
    for channel IDs (UC...). 1 unit per 50 uncached channels."""
    return service().get_channel_stats(channel_ids, dry_run=dry_run, max_units=max_units)


@mcp.tool()
@_safe
def find_outliers(
    query: str,
    format: Format = "both",
    min_outlier_score: float = 10,
    max_channel_subs: int | None = None,
    metric: OutlierMetric = "subs",
    published_within_days: int | None = None,
    region_code: str | None = None,
    relevance_language: str | None = None,
    limit: int = 30,
    dry_run: bool = False,
    max_units: int | None = None,
) -> dict[str, Any]:
    """Videos from small channels that massively out-performed the channel's size.

    Reports two scores: sub_outlier_score = views / subscribers, and channel_relative_score =
    views / (channel views / channel video count). `metric` picks which must pass min_outlier_score.
    Shorts are ranked by channel_relative_score, long-form by sub_outlier_score.
    """
    return service().find_outliers(query, format, min_outlier_score, max_channel_subs, metric,
                                   published_within_days, None, region_code, relevance_language, limit,
                                   dry_run=dry_run, max_units=max_units)


@mcp.tool()
@_safe
def analyze_niche(
    query: str,
    format: Format = "both",
    published_within_days: int | None = None,
    region_code: str | None = None,
    relevance_language: str | None = None,
    export: bool = False,
    dry_run: bool = False,
    max_units: int | None = None,
) -> dict[str, Any]:
    """Backtested niche report. `forecast`: chance a small channel's upload reaches 10k views in its
    first 1-3 weeks, with an 80% range. `view_score` (0-100, with 80% range) from opportunity, demand,
    new-channel proof, velocity, consistency (competition reported, not weighted); `final_score` adds
    the monetization ESTIMATE (15%). Also top 10 outliers, title patterns, typical length, recency and
    low-confidence flags. `summary_markdown` is a readable version; export=true writes it to reports/.
    format=both scores Shorts and long-form separately and reports the better one."""
    result = service().analyze_niche(query, format, published_within_days, None, region_code, relevance_language,
                                     export=export, dry_run=dry_run, max_units=max_units)
    return result


@mcp.tool()
@_safe
def compare_niches(
    queries: list[str],
    format: Format = "both",
    published_within_days: int | None = None,
    region_code: str | None = None,
    relevance_language: str | None = None,
    export: bool = False,
    dry_run: bool = False,
    max_units: int | None = None,
) -> dict[str, Any]:
    """Analyze several niches and rank them by final score. `table_markdown` is the ranked table.
    Cost is the sum of each analyze_niche (cached niches are nearly free): check with dry_run first."""
    return service().compare_niches(queries, format, published_within_days, None, region_code, relevance_language,
                                    export=export, dry_run=dry_run, max_units=max_units)


@mcp.tool()
@_safe
def expand_keywords(
    seed: str,
    format: Format = "both",
    max_suggestions: int = 15,
    region_code: str | None = None,
    relevance_language: str | None = None,
    dry_run: bool = False,
    max_units: int | None = None,
) -> dict[str, Any]:
    """Related sub-niche queries mined from titles and tags of the seed's top outlier videos.
    Uses cached data (0 units) if the seed was searched before; otherwise runs find_outliers once."""
    return service().expand_keywords(seed, format, max_suggestions, region_code, relevance_language,
                                     dry_run=dry_run, max_units=max_units)


@mcp.tool()
@_safe
def quota_status() -> dict[str, Any]:
    """Units used today (Pacific-time day, as YouTube counts it), remaining, and per-endpoint breakdown."""
    return service().quota_status()


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
