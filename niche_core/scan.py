"""Breakout scan: where did tiny channels get big views lately, across many queries at once.

    python -m niche_core scan --seeds examples/seeds_minecraft.txt --days 14 --max-subs 1000 --min-views 100000

Runs find_outliers for every seed query (shorts by default), merges and dedupes the videos, keeps
those from channels at or under --max-subs with at least --min-views, and groups them by query, by
channel and by length. Searches are cached for 24 h, so a second run on the same day is free: the
scan is meant to be run daily and read as a feed. Cost: ~100 units per query (shorts), ~200 (long).
"""

from __future__ import annotations

import re
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

DEFAULT_SEEDS = [
    "minecraft", "minecraft mod", "minecraft update", "minecraft sift", "minecraft new dimension",
    "minecraft dungeons 2", "minecraft animation", "minecraft meme", "minecraft horror", "minecraft build",
    "minecraft survival", "minecraft pvp", "minecraft but", "minecraft hardcore", "minecraft facts",
    "minecraft lore", "minecraft seed", "minecraft tutorial", "minecraft redstone", "minecraft smp",
]


def read_seeds(spec: list[str] | None) -> list[str]:
    """Queries from the command line; an @file (one per line, # comments) expands in place."""
    if not spec:
        return list(DEFAULT_SEEDS)
    out: list[str] = []
    for item in spec:
        if item.startswith("@"):
            for line in Path(item[1:]).read_text(encoding="utf-8").splitlines():
                line = line.split("#", 1)[0].strip()
                if line:
                    out.append(line)
        else:
            out.append(item)
    return list(dict.fromkeys(out))


def _bucket(dur: int) -> str:
    for lo, hi in ((0, 20), (20, 40), (40, 70), (70, 120), (120, 181)):
        if lo <= dur < hi:
            return f"{lo}-{hi - 1}s"
    return "180s+"


def run(service, seeds: list[str], *, fmt: str = "shorts", days: int = 14, max_subs: int = 1000,
        min_views: int = 100_000, max_units: int | None = None, log=None) -> dict[str, Any]:
    videos: dict[str, dict] = {}
    per_query: dict[str, list[str]] = {}
    errors: list[str] = []
    start = service.quota.session_units
    for q in seeds:
        try:
            out = service.find_outliers(q, format=fmt, min_outlier_score=1, max_channel_subs=max_subs,
                                        published_within_days=days, limit=200, max_units=max_units)
        except Exception as exc:  # budget, quota, API: keep what we have and say so
            errors.append(f"{q}: {exc}")
            if log:
                log(f"  {q}: {exc}")
            break
        hits = [o for o in out.get("outliers", []) if o["views"] >= min_views]
        per_query[q] = [o["video_id"] for o in hits]
        for o in hits:
            v = videos.setdefault(o["video_id"], {**o, "queries": []})
            v["queries"].append(q)
        if log:
            log(f"  {q}: scanned {out.get('scanned', 0)}, breakouts {len(hits)}")
    ranked = sorted(videos.values(), key=lambda v: -v["views"])
    by_channel: dict[str, list[dict]] = defaultdict(list)
    for v in ranked:
        by_channel[v["channel_id"]].append(v)
    channels = sorted(({"channel_id": cid, "channel_title": vs[0]["channel_title"], "subs": vs[0]["channel_subs"],
                        "breakouts": len(vs), "views": sum(v["views"] for v in vs),
                        "titles": [v["title"] for v in vs[:4]]} for cid, vs in by_channel.items()),
                      key=lambda c: (-c["breakouts"], -c["views"]))
    lengths = Counter(_bucket(v["duration_s"]) for v in ranked)
    words = Counter()
    for v in ranked:
        words.update({w for w in re.findall(r"[a-z][a-z']{2,}", v["title"].lower())
                      if w not in {"the", "and", "minecraft", "shorts", "this", "with", "for", "you", "your", "that", "but"}})
    return {
        "tool": "scan", "format": fmt, "days": days, "max_subs": max_subs, "min_views": min_views,
        "seeds": seeds, "errors": errors,
        "videos": ranked,
        "per_query": {q: len(ids) for q, ids in per_query.items()},
        "channels": channels,
        "lengths": dict(lengths),
        "median_length_s": int(st.median([v["duration_s"] for v in ranked])) if ranked else None,
        "title_words": words.most_common(25),
        "quota": service.receipt(0, start).to_dict(),
    }


def _n(x: float) -> str:
    return f"{x / 1e6:.1f}M" if x >= 1e6 else f"{x / 1e3:.0f}k" if x >= 1e3 else f"{x:.0f}"


def to_markdown(r: dict, limit: int = 40) -> str:
    L = [f"# Breakout scan: {r['format']}, last {r['days']} days, channels ≤ {_n(r['max_subs'])} subs, ≥ {_n(r['min_views'])} views", ""]
    L.append(f"{len(r['videos'])} breakout videos from {len(r['channels'])} channels across {len(r['seeds'])} queries"
             + (f" (median length {r['median_length_s']} s)" if r["median_length_s"] else "") + ".")
    if r["errors"]:
        L += ["", "Stopped early: " + "; ".join(r["errors"])]
    L += ["", "## Where the breakouts are (per query)", ""]
    for q, n in sorted(r["per_query"].items(), key=lambda x: -x[1]):
        L.append(f"- {q}: {n}")
    L += ["", f"## Top {limit} videos", "", "| Views | Age | Len | Subs | Channel | Title |", "|---|---|---|---|---|---|"]
    for v in r["videos"][:limit]:
        L.append(f"| {_n(v['views'])} | {v['age_days']:.0f}d | {v['duration_s']}s | {_n(v['channel_subs'])} | "
                 f"{v['channel_title'][:18]} | [{v['title'][:70]}]({v['url']}) |")
    multi = [c for c in r["channels"] if c["breakouts"] >= 2]
    if multi:
        L += ["", "## Channels with 2+ breakouts (study these: `niche_core channel <id>`)", ""]
        for c in multi[:15]:
            L.append(f"- **{c['channel_title']}** ({_n(c['subs'])} subs, {c['breakouts']} breakouts, {_n(c['views'])} views) "
                     f"`{c['channel_id']}`: " + " · ".join(t[:50] for t in c["titles"][:3]))
    if r["lengths"]:
        L += ["", "## Length of the breakouts", "", "| Length | Videos |", "|---|---|"]
        L += [f"| {k} | {v} |" for k, v in sorted(r["lengths"].items(), key=lambda x: int(x[0].split('-')[0].rstrip('s+')))]
    if r["title_words"]:
        L += ["", "Title words: " + ", ".join(f"{w} ({n})" for w, n in r["title_words"][:20])]
    return "\n".join(L) + "\n"
