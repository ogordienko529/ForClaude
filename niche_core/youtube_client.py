"""Thin YouTube Data API v3 client. Every HTTP call is metered in the quota log.

Official API only; no scraping. The API key is kept out of every error message.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

from .quota import COSTS, IDS_PER_CALL, MAX_RESULTS_PER_PAGE, QuotaTracker, search_pages

BASE_URL = "https://www.googleapis.com/youtube/v3"

# httpx logs every request URL at INFO (and MCP servers enable INFO logging); keep it quiet.
logging.getLogger("httpx").setLevel(logging.WARNING)

QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded"}
RETRY_REASONS = {"backendError", "rateLimitExceeded", "userRateLimitExceeded", "internalError"}

VIDEO_FIELDS = (
    "items(id,snippet(publishedAt,channelId,title,channelTitle,tags,categoryId,"
    "liveBroadcastContent,defaultAudioLanguage),contentDetails(duration),statistics,"
    "player(embedWidth,embedHeight))"
)
CHANNEL_FIELDS = "items(id,snippet(title,publishedAt,country),statistics)"
SEARCH_FIELDS = "nextPageToken,pageInfo,items(id/videoId)"


class YouTubeAPIError(Exception):
    def __init__(self, message: str, status: int | None = None, reason: str | None = None):
        super().__init__(message)
        self.status = status
        self.reason = reason


class QuotaExceededError(YouTubeAPIError):
    """Daily quota exhausted (reported by the API or predicted locally)."""

    partial_ids: list[str] = []  # search IDs collected (and paid for) before the quota ran out


class MissingAPIKeyError(Exception):
    """Configuration problem, not an API response: never falls back to cache silently."""


class YouTubeClient:
    def __init__(
        self,
        api_key: str | None,
        quota: QuotaTracker,
        http: httpx.Client | None = None,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = 20.0,
    ):
        if not api_key:
            raise MissingAPIKeyError(
                "YOUTUBE_API_KEY is not set. Create a key in Google Cloud Console "
                "(YouTube Data API v3) and export it as an environment variable."
            )
        self._key = api_key
        self.quota = quota
        self.http = http or httpx.Client(base_url=BASE_URL, timeout=timeout)
        self.max_retries = max_retries
        self.sleep = sleep

    # ------------------------------------------------------------------ public
    def search_video_ids(
        self,
        query: str,
        *,
        max_results: int = 50,
        video_duration: str = "any",
        published_after: str | None = None,
        published_before: str | None = None,
        order: str = "viewCount",
        region_code: str | None = None,
        relevance_language: str | None = None,
    ) -> list[str]:
        """search.list (100 units per page of up to 50 results).

        Pages are capped at ceil(max_results / 50) so the cost never exceeds the estimate, even when
        YouTube returns short pages with a nextPageToken. Fewer IDs than requested is normal.
        """
        ids: list[str] = []
        page_token: str | None = None
        for _page in range(search_pages(max_results)):
            params: dict[str, Any] = {
                "part": "id",
                "q": query,
                "type": "video",
                "order": order,
                "videoDuration": video_duration,
                "maxResults": min(MAX_RESULTS_PER_PAGE, max_results - len(ids)),
                "fields": SEARCH_FIELDS,
            }
            if published_after:
                params["publishedAfter"] = published_after
            if published_before:
                params["publishedBefore"] = published_before
            if region_code:
                params["regionCode"] = region_code
            if relevance_language:
                params["relevanceLanguage"] = relevance_language
            if page_token:
                params["pageToken"] = page_token
            try:
                data = self._get("search", params)
            except QuotaExceededError as exc:
                exc.partial_ids = list(ids)  # earlier pages were paid for; let the caller keep them
                raise
            before = len(ids)
            for item in data.get("items", []):
                vid = (item.get("id") or {}).get("videoId")
                if vid and vid not in ids:
                    ids.append(vid)
            page_token = data.get("nextPageToken")
            if not page_token or len(ids) == before or len(ids) >= max_results:
                break
        return ids[:max_results]

    def list_videos(self, ids: list[str], player_max_height: int = 720) -> list[dict]:
        """videos.list, batched 50 IDs per call (1 unit each). Deleted/private IDs are simply absent."""
        items: list[dict] = []
        for chunk in _chunks(list(dict.fromkeys(ids)), IDS_PER_CALL):
            data = self._get(
                "videos",
                {
                    "part": "snippet,contentDetails,statistics,player",
                    "id": ",".join(chunk),
                    "maxHeight": player_max_height,
                    "maxResults": IDS_PER_CALL,
                    "fields": VIDEO_FIELDS,
                },
            )
            items.extend(data.get("items", []))
        return items

    def list_channels(self, ids: list[str]) -> list[dict]:
        """channels.list, batched 50 IDs per call (1 unit each)."""
        items: list[dict] = []
        for chunk in _chunks(list(dict.fromkeys(ids)), IDS_PER_CALL):
            data = self._get(
                "channels",
                {
                    "part": "snippet,statistics",
                    "id": ",".join(chunk),
                    "maxResults": IDS_PER_CALL,
                    "fields": CHANNEL_FIELDS,
                },
            )
            items.extend(data.get("items", []))
        return items

    # ------------------------------------------------------------------ internals
    def _get(self, endpoint: str, params: dict[str, Any]) -> dict:
        cost = COSTS[endpoint]
        attempt = 0
        while True:
            attempt += 1
            # Checked before every attempt: retries are charged too.
            if self.quota.remaining() < cost:
                raise QuotaExceededError(
                    f"Local quota guard: {endpoint}.list needs {cost} units but only "
                    f"{self.quota.remaining()} remain today (resets at midnight Pacific).",
                    reason="localQuotaGuard",
                )
            try:
                # Key in a header, not the URL: URLs end up in logs (httpx logs requests at INFO).
                resp = self.http.get(f"/{endpoint}", params=params, headers={"X-Goog-Api-Key": self._key})
            except httpx.RequestError as exc:
                # No response received: Google did not charge for it.
                self.quota.record(endpoint, 0, ok=False, error=f"network: {type(exc).__name__}")
                if attempt <= self.max_retries:
                    self.sleep(2 ** attempt)
                    continue
                raise YouTubeAPIError(f"Network error calling {endpoint}.list: {type(exc).__name__}") from None

            if resp.status_code == 200:
                self.quota.record(endpoint, cost, ok=True)
                try:
                    return resp.json()
                except ValueError:
                    raise YouTubeAPIError(f"{endpoint}.list returned a malformed response", 200, "badJson") from None

            status, reason, message = _parse_error(resp)
            message = self._redact(message)
            if reason in QUOTA_REASONS:
                self.quota.record(endpoint, 0, ok=False, error=reason)
                raise QuotaExceededError(
                    f"YouTube API quota exhausted ({reason}). Resets at midnight Pacific Time.",
                    status=status,
                    reason=reason,
                )
            # Invalid requests are still charged by Google.
            self.quota.record(endpoint, cost, ok=False, error=f"{status} {reason}")
            retryable = status >= 500 or status == 429 or reason in RETRY_REASONS
            if retryable and attempt <= self.max_retries:
                self.sleep(2 ** attempt)
                continue
            raise YouTubeAPIError(f"{endpoint}.list failed: HTTP {status} {reason}: {message}", status, reason)

    def _redact(self, text: str) -> str:
        return text.replace(self._key, "***") if self._key else text


def _parse_error(resp: httpx.Response) -> tuple[int, str, str]:
    try:
        err = resp.json().get("error", {})
        errors = err.get("errors") or [{}]
        return resp.status_code, errors[0].get("reason", "unknown"), err.get("message", "")
    except ValueError:
        return resp.status_code, "unknown", resp.text[:200]


def _chunks(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]
