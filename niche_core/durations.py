"""ISO-8601 duration parsing and Shorts / long-form classification."""

from __future__ import annotations

import re

_DURATION_RE = re.compile(
    r"^P(?:(?P<weeks>\d+)W)?(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)

# Format classes
SHORT = "short"                      # <= max seconds AND vertical embed
SHORT_LONGFORM = "short_longform"    # <= max seconds but horizontal/square embed
SHORT_UNVERIFIED = "short_unverified"  # <= max seconds but no embed dimensions returned
LONG = "long"                        # > max seconds
LIVE = "live"                        # live/upcoming or zero duration: excluded from stats

FORMAT_CLASSES = (SHORT, SHORT_LONGFORM, SHORT_UNVERIFIED, LONG, LIVE)


def parse_iso8601_duration(value: str | None) -> int | None:
    """'PT1H2M3S' -> 3723. Returns None if missing or unparseable."""
    if not value:
        return None
    m = _DURATION_RE.match(value.strip())
    if not m:
        return None
    parts = {k: float(v) if v else 0.0 for k, v in m.groupdict().items()}
    total = (
        parts["weeks"] * 7 * 86400
        + parts["days"] * 86400
        + parts["hours"] * 3600
        + parts["minutes"] * 60
        + parts["seconds"]
    )
    return int(round(total))


def classify_format(
    duration_s: int | None,
    embed_width: int | None,
    embed_height: int | None,
    live_broadcast_content: str | None = None,
    shorts_max_seconds: int = 180,
) -> str:
    if live_broadcast_content in ("live", "upcoming") or not duration_s:
        return LIVE
    if duration_s > shorts_max_seconds:
        return LONG
    if not embed_width or not embed_height:
        return SHORT_UNVERIFIED
    return SHORT if embed_height > embed_width else SHORT_LONGFORM


def format_seconds(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
