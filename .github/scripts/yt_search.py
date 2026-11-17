"""What a niche watches: YouTube search results for a list of queries, without an API key (yt-dlp).

For each query: the top results by relevance and the newest uploads, with title, channel, views and length; then
the subscriber count of every channel that appears, so a video can be judged against its channel's size (a big
video on a small channel means demand for the topic, not for the channel).

Usage: python yt_search.py OUT.json "query one" "query two" ... [--top 40] [--recent 25]
"""

from __future__ import annotations

import argparse
import json
import sys

import yt_dlp


def flat(url: str) -> dict:
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "ignoreerrors": True, "extract_flat": "in_playlist"}
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            return y.extract_info(url, download=False) or {}
    except Exception as e:  # noqa: BLE001
        print(f"{url}: {e}", file=sys.stderr)
        return {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("queries", nargs="+")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--recent", type=int, default=25)
    a = ap.parse_args()
    videos: dict[str, dict] = {}
    for q in a.queries:
        for kind, url in (("top", f"ytsearch{a.top}:{q}"), ("recent", f"ytsearchdate{a.recent}:{q}")):
            for e in flat(url).get("entries") or []:
                if not e or not e.get("id"):
                    continue
                v = videos.setdefault(e["id"], {"id": e["id"], "title": e.get("title"), "channel": e.get("channel"),
                                                "channel_id": e.get("channel_id"), "views": e.get("view_count"),
                                                "duration": e.get("duration"), "queries": []})
                v["queries"].append(f"{kind}:{q}")
    channels: dict[str, int | None] = {}
    for cid in {v["channel_id"] for v in videos.values() if v.get("channel_id")}:
        info = flat(f"https://www.youtube.com/channel/{cid}/videos")
        channels[cid] = info.get("channel_follower_count")
    for v in videos.values():
        v["subscribers"] = channels.get(v.get("channel_id"))
    json.dump({"queries": a.queries, "videos": list(videos.values())}, open(a.out, "w"), ensure_ascii=False, indent=1)
    print(f"{len(videos)} videos from {len(channels)} channels", file=sys.stderr)


if __name__ == "__main__":
    main()
