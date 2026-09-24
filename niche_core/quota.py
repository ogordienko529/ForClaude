"""Daily quota tracking. YouTube resets quota at midnight Pacific Time."""

from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo

from .cache import Store
from .models import to_iso

PACIFIC = ZoneInfo("America/Los_Angeles")

COSTS = {
    "search": 100,
    "videos": 1,
    "channels": 1,
}
IDS_PER_CALL = 50
MAX_RESULTS_PER_PAGE = 50


class QuotaTracker:
    def __init__(self, store: Store, daily_limit: int = 10_000):
        self.store = store
        self.daily_limit = daily_limit
        # Units recorded by this process; the service diffs it to report "actual" cost.
        self.session_units = 0

    def pt_date(self, when: datetime | None = None) -> str:
        return (when or self.store.clock()).astimezone(PACIFIC).date().isoformat()

    def used_today(self) -> int:
        row = self.store.conn.execute(
            "SELECT COALESCE(SUM(units), 0) FROM quota_log WHERE pt_date = ?", (self.pt_date(),)
        ).fetchone()
        return int(row[0])

    def remaining(self) -> int:
        return max(self.daily_limit - self.used_today(), 0)

    def record(self, endpoint: str, units: int, ok: bool = True, error: str | None = None) -> None:
        now = self.store.clock()
        self.store.conn.execute(
            "INSERT INTO quota_log (ts, pt_date, endpoint, units, ok, error) VALUES (?, ?, ?, ?, ?, ?)",
            (to_iso(now), self.pt_date(now), endpoint, units, int(ok), error),
        )
        self.store.conn.commit()
        self.session_units += units

    def breakdown_today(self) -> dict[str, dict[str, int]]:
        rows = self.store.conn.execute(
            "SELECT endpoint, COUNT(*) AS calls, SUM(units) AS units, SUM(1 - ok) AS errors "
            "FROM quota_log WHERE pt_date = ? GROUP BY endpoint",
            (self.pt_date(),),
        ).fetchall()
        return {r["endpoint"]: {"calls": r["calls"], "units": r["units"], "errors": r["errors"]} for r in rows}

    def status(self) -> dict:
        used = self.used_today()
        return {
            "pt_date": self.pt_date(),
            "daily_limit": self.daily_limit,
            "used_today": used,
            "remaining": max(self.daily_limit - used, 0),
            "by_endpoint": self.breakdown_today(),
            "note": "Quota resets at midnight Pacific Time. Counts only calls made by this tool.",
        }


def estimate_list_calls(n_ids: int) -> int:
    """videos.list / channels.list: 1 unit per call, up to 50 IDs per call."""
    return math.ceil(n_ids / IDS_PER_CALL) * COSTS["videos"] if n_ids > 0 else 0


def search_pages(max_results: int) -> int:
    return max(math.ceil(max_results / MAX_RESULTS_PER_PAGE), 1)
