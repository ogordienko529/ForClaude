"""Fake YouTube API (httpx.MockTransport) serving fixture items. No network."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import httpx

FIXTURES = Path(__file__).parent / "fixtures"
FIXED_NOW = datetime(2026, 9, 24, 18, 0, tzinfo=timezone.utc)


def load_items() -> dict:
    return json.loads((FIXTURES / "api_items.json").read_text())


class FakeYouTube:
    """Serves search/videos/channels. `search_results` maps videoDuration -> list of video IDs."""

    def __init__(self, videos: list[dict], channels: list[dict], search_results: dict[str, list[str]]):
        self.videos = {v["id"]: v for v in videos}
        self.channels = {c["id"]: c for c in channels}
        self.search_results = search_results
        self.calls: list[tuple[str, dict]] = []
        self.fail_with: dict[str, list[httpx.Response]] = defaultdict(list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path.rsplit("/", 1)[-1]
        params = dict(request.url.params)
        self.calls.append((endpoint, params))
        if self.fail_with[endpoint]:
            return self.fail_with[endpoint].pop(0)
        if endpoint == "search":
            ids = self.search_results.get(params.get("videoDuration", "any"), [])
            n = int(params.get("maxResults", 5))
            start = int(params.get("pageToken", 0) or 0)
            page = ids[start : start + n]
            body = {"items": [{"id": {"videoId": i}} for i in page]}
            if start + n < len(ids):
                body["nextPageToken"] = str(start + n)
            return httpx.Response(200, json=body)
        if endpoint == "videos":
            ids = params["id"].split(",")
            assert len(ids) <= 50
            return httpx.Response(200, json={"items": [self.videos[i] for i in ids if i in self.videos]})
        if endpoint == "channels":
            ids = params["id"].split(",")
            assert len(ids) <= 50
            return httpx.Response(200, json={"items": [self.channels[i] for i in ids if i in self.channels]})
        return httpx.Response(404, json={"error": {"code": 404, "message": "nope", "errors": [{"reason": "notFound"}]}})

    def http_client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler), base_url="https://www.googleapis.com/youtube/v3")

    def count(self, endpoint: str) -> int:
        return sum(1 for e, _ in self.calls if e == endpoint)


def api_error(status: int, reason: str, message: str = "error") -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": status, "message": message, "errors": [{"reason": reason}]}})
