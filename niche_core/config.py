"""Configuration: built-in defaults, optionally overridden by a TOML file.

Lookup order for the config file:
  1. $NICHE_CONFIG
  2. ./config.toml
  3. ~/.niche_research/config.toml
Only keys present in the file override the defaults (deep merge).
The YouTube API key is never read from the file, only from $YOUTUBE_API_KEY.
"""

from __future__ import annotations

import copy
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

API_KEY_ENV = "YOUTUBE_API_KEY"
CONFIG_ENV = "NICHE_CONFIG"
MAX_RETENTION_DAYS = 30  # YouTube API Services policy: refresh or delete stored data within 30 days

DEFAULTS: dict[str, Any] = {
    "paths": {
        "db_path": "~/.niche_research/cache.db",
        "reports_dir": "reports",
    },
    "cache": {
        "video_ttl_hours": 24,
        "channel_ttl_hours": 168,
        "search_ttl_hours": 24,
        "retention_days": 30,
    },
    "quota": {
        "daily_limit": 10_000,
    },
    "search": {
        "region_code": "US",
        "relevance_language": "en",
        "max_results": 50,
        "published_within_days": 30,
        # relevanceLanguage is only a hint; also drop videos whose declared audio language differs.
        "filter_by_audio_language": True,
    },
    "shorts": {
        # A Short must be <= this long AND have a vertical embed (height > width).
        "max_seconds": 180,
        # maxHeight passed to videos.list so the API returns player.embedWidth/embedHeight.
        "player_max_height": 720,
    },
    "thresholds": {
        "small_channel_max_subs": 50_000,
        "large_channel_min_subs": 100_000,
        "new_channel_max_age_days": 365,
        # Floor for the subscriber denominator so 0-sub channels don't produce infinite scores.
        "outlier_sub_floor": 100,
        "min_sample_videos": 30,
        "min_small_channel_hits": 5,
        # Base-rate sample: newest uploads that are at least this old, so they had time to get views.
        "sample_min_age_days": 7,
        "new_channel_target": 20,         # distinct new channels with hits for full count credit (log scale)
        "consistency_channel_target": 8,  # distinct small channels with hits for full spread credit
        # Paid-promotion filter: many views, near-zero engagement, channel avg views >> subscribers.
        "promo_min_views": 100_000,
        "promo_max_like_rate": 0.001,
        "promo_max_comment_rate": 0.00005,
        "promo_min_avg_views_per_sub": 20,
        # 80% bootstrap interval of the view score wider than this => low confidence.
        "max_ci_width": 25,
    },
    # Per-format bands. Shorts views count every play/replay, so the numbers are not
    # comparable with long-form and must be normalised separately.
    "bands": {
        "shorts": {
            "hit_views": 10_000,
            # Median views/day of *typical* uploads (date-ordered sample), not of top videos.
            "velocity_views_per_day_low": 3,
            "velocity_views_per_day_high": 1_700,
            "hit_share_high": 0.60,          # small-channel hit share that scores 100
            "small_views_low": 100_000,      # median views of small channels in the top results -> 0
            "small_views_high": 20_000_000,  # -> 100
            "demand_views_low": 75_000,      # median views of the top results -> 0
            "demand_views_high": 13_000_000, # -> 100
        },
        "long": {
            "hit_views": 10_000,
            "velocity_views_per_day_low": 1,
            "velocity_views_per_day_high": 100,
            "hit_share_high": 0.30,
            "small_views_low": 6_000,
            "small_views_high": 500_000,
            "demand_views_low": 13_000,
            "demand_views_high": 1_200_000,
        },
    },
    # Share of the final score that is money; the rest is the view-opportunity score. View weights are
    # per format and were fitted on the temporal backtest (docs/CALIBRATION.md).
    "weights": {
        "monetization": 0.15,
        "shorts": {
            "opportunity": 0.35, "demand": 0.30, "new_channel_proof": 0.15,
            "velocity": 0.10, "consistency": 0.10, "competition": 0.0,
        },
        "long": {
            "opportunity": 0.50, "demand": 0.50, "new_channel_proof": 0.0,
            "velocity": 0.0, "consistency": 0.0, "competition": 0.0,
        },
    },
    # Forecast of a small channel's hit probability (Beta-binomial shrinkage + month-to-month drift),
    # both measured by the backtest.
    "forecast": {
        "prior_strength": 10,
        "shorts": {"prior_hit_rate": 0.48, "drift_sd": 0.30},
        "long": {"prior_hit_rate": 0.13, "drift_sd": 0.055},
    },
}


class ConfigError(ValueError):
    pass


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def find_config_file() -> Path | None:
    env = os.environ.get(CONFIG_ENV)
    if env:
        path = Path(env).expanduser()
        if not path.is_file():
            raise ConfigError(f"{CONFIG_ENV} points to missing file: {path}")
        return path
    for candidate in (Path("config.toml"), Path("~/.niche_research/config.toml").expanduser()):
        if candidate.is_file():
            return candidate
    return None


@dataclass(frozen=True)
class Config:
    raw: dict[str, Any]
    source: Path | None = None

    # --- paths ---
    @property
    def db_path(self) -> Path:
        value = self.raw["paths"]["db_path"]
        return value if value == ":memory:" else Path(value).expanduser()

    @property
    def reports_dir(self) -> Path:
        return Path(self.raw["paths"]["reports_dir"]).expanduser()

    # --- cache ---
    @property
    def video_ttl_hours(self) -> float:
        return float(self.raw["cache"]["video_ttl_hours"])

    @property
    def channel_ttl_hours(self) -> float:
        return float(self.raw["cache"]["channel_ttl_hours"])

    @property
    def search_ttl_hours(self) -> float:
        return float(self.raw["cache"]["search_ttl_hours"])

    @property
    def retention_days(self) -> int:
        return int(self.raw["cache"]["retention_days"])

    # --- quota / search ---
    @property
    def daily_quota(self) -> int:
        return int(self.raw["quota"]["daily_limit"])

    @property
    def search(self) -> dict[str, Any]:
        return self.raw["search"]

    @property
    def shorts(self) -> dict[str, Any]:
        return self.raw["shorts"]

    @property
    def thresholds(self) -> dict[str, Any]:
        return self.raw["thresholds"]

    @property
    def monetization_weight(self) -> float:
        w = self.raw["weights"]
        flat = self._flat_weights()
        if flat:  # old-style config: monetization's share of the flat total
            total = sum(flat.values()) + float(w.get("monetization", 0))
            return float(w.get("monetization", 0)) / total if total else 0.0
        return float(w.get("monetization", 0.15))

    def _flat_weights(self) -> dict[str, float]:
        """Old-style [weights] with component keys at top level (applies to both formats)."""
        return {k: float(v) for k, v in self.raw["weights"].items()
                if k not in ("monetization", "shorts", "long") and not isinstance(v, dict)}

    def view_weights(self, fmt: str) -> dict[str, float]:
        flat = self._flat_weights()
        if flat:
            return flat
        return {k: float(v) for k, v in self.raw["weights"][fmt].items()}

    def forecast(self, fmt: str) -> dict[str, float]:
        f = self.raw["forecast"]
        return {"prior_strength": float(f["prior_strength"]), **{k: float(v) for k, v in f[fmt].items()}}

    def bands(self, fmt: str) -> dict[str, float]:
        """fmt: 'shorts' or 'long'."""
        return self.raw["bands"][fmt]

    @property
    def monetization(self) -> dict[str, Any]:
        from .rpm import DEFAULT_MONETIZATION

        return _deep_merge(DEFAULT_MONETIZATION, self.raw.get("monetization", {}))

    def validate(self) -> None:
        rd = self.retention_days
        if not 1 <= rd <= MAX_RETENTION_DAYS:
            raise ConfigError(
                f"cache.retention_days must be between 1 and {MAX_RETENTION_DAYS} "
                f"(YouTube API policy), got {rd}"
            )
        for fmt in ("shorts", "long"):
            b = self.bands(fmt)
            if b["velocity_views_per_day_low"] >= b["velocity_views_per_day_high"]:
                raise ConfigError(f"bands.{fmt}: velocity low must be < high")
        for fmt in ("shorts", "long"):
            w = self.view_weights(fmt)
            if any(x < 0 for x in w.values()) or sum(w.values()) <= 0:
                raise ConfigError(f"weights.{fmt} must be non-negative and sum to > 0")
        if not 0 <= self.monetization_weight <= 1:
            raise ConfigError("weights.monetization must be between 0 and 1")


def load_config(path: Path | str | None = None, overrides: dict | None = None) -> Config:
    source = Path(path).expanduser() if path else find_config_file()
    raw = copy.deepcopy(DEFAULTS)
    if source:
        with open(source, "rb") as fh:
            raw = _deep_merge(raw, tomllib.load(fh))
    if overrides:
        raw = _deep_merge(raw, overrides)
    cfg = Config(raw=raw, source=source)
    cfg.validate()
    return cfg


def get_api_key() -> str | None:
    key = os.environ.get(API_KEY_ENV, "").strip()
    return key or None
