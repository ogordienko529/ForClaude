"""SQLite cache for API responses, snapshots and quota log.

All timestamps are stored as UTC ISO-8601 strings ('YYYY-MM-DDTHH:MM:SS+00:00'),
which sort lexicographically, so TTL/retention checks are plain string comparisons.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .models import Channel, Video, parse_rfc3339, to_iso, utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    channel_title TEXT,
    title TEXT,
    tags_json TEXT,
    category_id TEXT,
    published_at TEXT,
    duration_s INTEGER,
    format_class TEXT,
    embed_width INTEGER,
    embed_height INTEGER,
    view_count INTEGER,
    like_count INTEGER,
    comment_count INTEGER,
    default_audio_language TEXT,
    live_broadcast_content TEXT,
    fetched_at TEXT NOT NULL,
    raw_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos(channel_id);
CREATE INDEX IF NOT EXISTS idx_videos_fetched ON videos(fetched_at);

CREATE TABLE IF NOT EXISTS video_snapshots (
    video_id TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    view_count INTEGER,
    like_count INTEGER,
    comment_count INTEGER,
    PRIMARY KEY (video_id, fetched_at)
);
CREATE INDEX IF NOT EXISTS idx_snap_fetched ON video_snapshots(fetched_at);

CREATE TABLE IF NOT EXISTS channels (
    channel_id TEXT PRIMARY KEY,
    title TEXT,
    subscriber_count INTEGER,
    subs_hidden INTEGER NOT NULL DEFAULT 0,
    view_count INTEGER,
    video_count INTEGER,
    published_at TEXT,
    country TEXT,
    fetched_at TEXT NOT NULL,
    raw_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_channels_fetched ON channels(fetched_at);

CREATE TABLE IF NOT EXISTS searches (
    cache_key TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    params_json TEXT NOT NULL,
    video_ids_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_searches_fetched ON searches(fetched_at);

CREATE TABLE IF NOT EXISTS quota_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    pt_date TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    units INTEGER NOT NULL,
    ok INTEGER NOT NULL,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_quota_date ON quota_log(pt_date);
"""

Clock = Callable[[], datetime]


def search_cache_key(query: str, params: dict[str, Any]) -> str:
    """Stable key over the normalised query and every parameter that changes results."""
    payload = json.dumps({"q": " ".join(query.lower().split()), **params}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


class Store:
    def __init__(self, db_path: Path | str, clock: Clock = utcnow):
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.clock = clock

    def close(self) -> None:
        self.conn.close()

    def _cutoff(self, hours: float) -> str:
        return to_iso(self.clock() - timedelta(hours=hours))

    # ------------------------------------------------------------------ searches
    def get_search(self, key: str, ttl_hours: float | None = None) -> list[str] | None:
        """Cached search result; ttl_hours=None accepts any age still within retention."""
        cutoff = self._cutoff(ttl_hours) if ttl_hours is not None else ""
        row = self.conn.execute(
            "SELECT video_ids_json FROM searches WHERE cache_key = ? AND fetched_at >= ?",
            (key, cutoff),
        ).fetchone()
        return json.loads(row["video_ids_json"]) if row else None

    def put_search(self, key: str, query: str, params: dict[str, Any], video_ids: list[str]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO searches VALUES (?, ?, ?, ?, ?)",
            (key, query, json.dumps(params, sort_keys=True), json.dumps(video_ids), to_iso(self.clock())),
        )
        self.conn.commit()

    def video_ids_for_query(self, query: str) -> list[str]:
        """All cached result IDs for a query across any params (region, format, order...)."""
        norm = " ".join(query.lower().split())
        ids: list[str] = []
        for row in self.conn.execute("SELECT query, video_ids_json FROM searches ORDER BY fetched_at DESC"):
            if " ".join(row["query"].lower().split()) == norm:
                ids.extend(i for i in json.loads(row["video_ids_json"]) if i not in ids)
        return ids

    # ------------------------------------------------------------------ videos
    def upsert_videos(self, videos: Iterable[Video], raw_items: dict[str, dict] | None = None) -> None:
        raw_items = raw_items or {}
        now = to_iso(self.clock())
        for v in videos:
            fetched = to_iso(v.fetched_at) or now
            raw = raw_items.get(v.video_id)
            self.conn.execute(
                """INSERT OR REPLACE INTO videos VALUES
                   (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    v.video_id, v.channel_id, v.channel_title, v.title, json.dumps(v.tags),
                    v.category_id, to_iso(v.published_at), v.duration_s, v.format_class,
                    v.embed_width, v.embed_height, v.view_count, v.like_count, v.comment_count,
                    v.default_audio_language, v.live_broadcast_content, fetched,
                    json.dumps(raw) if raw is not None else None,
                ),
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO video_snapshots VALUES (?, ?, ?, ?, ?)",
                (v.video_id, fetched, v.view_count, v.like_count, v.comment_count),
            )
        self.conn.commit()

    def get_videos(self, ids: Iterable[str], ttl_hours: float | None = None) -> dict[str, Video]:
        """Return cached videos (only those fresher than ttl_hours, if given)."""
        ids = list(dict.fromkeys(ids))
        out: dict[str, Video] = {}
        cutoff = self._cutoff(ttl_hours) if ttl_hours is not None else ""
        for chunk in _chunks(ids, 500):
            marks = ",".join("?" * len(chunk))
            rows = self.conn.execute(
                f"SELECT * FROM videos WHERE video_id IN ({marks}) AND fetched_at >= ?",
                (*chunk, cutoff),
            ).fetchall()
            for r in rows:
                out[r["video_id"]] = _row_to_video(r)
        return out

    def get_snapshots(self, video_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT fetched_at, view_count, like_count, comment_count FROM video_snapshots "
            "WHERE video_id = ? ORDER BY fetched_at",
            (video_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def all_videos(self) -> list[Video]:
        return [_row_to_video(r) for r in self.conn.execute("SELECT * FROM videos").fetchall()]

    # ------------------------------------------------------------------ channels
    def upsert_channels(self, channels: Iterable[Channel], raw_items: dict[str, dict] | None = None) -> None:
        raw_items = raw_items or {}
        now = to_iso(self.clock())
        for c in channels:
            raw = raw_items.get(c.channel_id)
            self.conn.execute(
                "INSERT OR REPLACE INTO channels VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    c.channel_id, c.title, c.subscriber_count, int(c.subs_hidden), c.view_count,
                    c.video_count, to_iso(c.published_at), c.country, to_iso(c.fetched_at) or now,
                    json.dumps(raw) if raw is not None else None,
                ),
            )
        self.conn.commit()

    def get_channels(self, ids: Iterable[str], ttl_hours: float | None = None) -> dict[str, Channel]:
        ids = list(dict.fromkeys(ids))
        out: dict[str, Channel] = {}
        cutoff = self._cutoff(ttl_hours) if ttl_hours is not None else ""
        for chunk in _chunks(ids, 500):
            marks = ",".join("?" * len(chunk))
            rows = self.conn.execute(
                f"SELECT * FROM channels WHERE channel_id IN ({marks}) AND fetched_at >= ?",
                (*chunk, cutoff),
            ).fetchall()
            for r in rows:
                out[r["channel_id"]] = Channel(
                    channel_id=r["channel_id"],
                    title=r["title"] or "",
                    subscriber_count=r["subscriber_count"],
                    subs_hidden=bool(r["subs_hidden"]),
                    view_count=r["view_count"],
                    video_count=r["video_count"],
                    published_at=parse_rfc3339(r["published_at"]),
                    country=r["country"],
                    fetched_at=parse_rfc3339(r["fetched_at"]),
                )
        return out

    # ------------------------------------------------------------------ retention
    def purge(self, retention_days: int) -> dict[str, int]:
        """Delete every row older than retention_days (YouTube API data policy)."""
        cutoff = to_iso(self.clock() - timedelta(days=retention_days))
        deleted = {}
        for table in ("videos", "video_snapshots", "channels", "searches"):
            cur = self.conn.execute(f"DELETE FROM {table} WHERE fetched_at < ?", (cutoff,))
            deleted[table] = cur.rowcount
        cur = self.conn.execute("DELETE FROM quota_log WHERE ts < ?", (cutoff,))
        deleted["quota_log"] = cur.rowcount
        self.conn.commit()
        return deleted

    def counts(self) -> dict[str, int]:
        return {
            t: self.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("videos", "video_snapshots", "channels", "searches", "quota_log")
        }


def _row_to_video(r: sqlite3.Row) -> Video:
    return Video(
        video_id=r["video_id"],
        channel_id=r["channel_id"],
        channel_title=r["channel_title"] or "",
        title=r["title"] or "",
        published_at=parse_rfc3339(r["published_at"]),
        duration_s=r["duration_s"],
        format_class=r["format_class"],
        view_count=r["view_count"],
        like_count=r["like_count"],
        comment_count=r["comment_count"],
        tags=json.loads(r["tags_json"] or "[]"),
        category_id=r["category_id"],
        embed_width=r["embed_width"],
        embed_height=r["embed_height"],
        default_audio_language=r["default_audio_language"],
        live_broadcast_content=r["live_broadcast_content"],
        fetched_at=parse_rfc3339(r["fetched_at"]),
    )


def _chunks(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]
