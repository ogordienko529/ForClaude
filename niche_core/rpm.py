"""Monetization ESTIMATE. This is a heuristic lookup, not data from the API.

Tier comes from keyword rules on the query first (high, then low, then medium keywords, since
advertiser demand follows the topic), then from the most common YouTube category of the analysed videos.
Shorts use a separate, much lower table: Shorts revenue is pooled and RPMs are a fraction of long-form.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

# Defaults; every table can be overridden in config.toml under [monetization].
DEFAULT_MONETIZATION: dict[str, Any] = {
    "high_keywords": [
        "finance", "invest", "stock", "money", "crypto", "bitcoin", "real estate", "mortgage", "insurance",
        "loan", "credit", "tax", "budget", "retire", "business", "entrepreneur", "saas", "software",
        "marketing", "lawyer", "legal", "ai tool", "productivity", "tech review", "b2b", "trading", "wealth",
    ],
    "low_keywords": [
        "prank", "meme", "funny", "compilation", "kids", "nursery", "asmr", "minecraft", "fortnite", "roblox",
        "gaming", "gameplay", "lyrics", "music", "reaction", "tiktok", "edit", "anime", "fancam",
    ],
    # Topic keywords that advertisers treat as mid-value. Checked after high and low keywords.
    "medium_keywords": [
        "history", "documentary", "science", "education", "explained", "geography", "space", "psychology",
        "health", "fitness", "cooking", "recipe", "travel", "diy", "how to", "tutorial", "lore", "mystery",
        "true crime", "philosophy", "language", "car", "cars",
    ],
    # YouTube videoCategory IDs -> tier
    "category_tiers": {
        "28": "high",    # Science & Technology
        "2": "high",     # Autos & Vehicles
        "27": "medium",  # Education
        "26": "medium",  # Howto & Style
        "19": "medium",  # Travel & Events
        "25": "medium",  # News & Politics
        "1": "medium",   # Film & Animation
        "15": "medium",  # Pets & Animals
        "17": "medium",  # Sports
        "29": "medium",  # Nonprofits & Activism
        "22": "low",     # People & Blogs
        "24": "low",     # Entertainment
        "23": "low",     # Comedy
        "20": "low",     # Gaming
        "10": "low",     # Music
    },
    "default_tier": "medium",
    "long": {
        "high": {"score": 90, "rpm_range_usd": "$8-20+"},
        "medium": {"score": 60, "rpm_range_usd": "$3-8"},
        "low": {"score": 30, "rpm_range_usd": "$0.5-3"},
    },
    "shorts": {
        "high": {"score": 35, "rpm_range_usd": "$0.10-0.30"},
        "medium": {"score": 22, "rpm_range_usd": "$0.05-0.10"},
        "low": {"score": 10, "rpm_range_usd": "$0.01-0.05"},
    },
}

CATEGORY_NAMES = {
    "1": "Film & Animation", "2": "Autos & Vehicles", "10": "Music", "15": "Pets & Animals", "17": "Sports",
    "19": "Travel & Events", "20": "Gaming", "22": "People & Blogs", "23": "Comedy", "24": "Entertainment",
    "25": "News & Politics", "26": "Howto & Style", "27": "Education", "28": "Science & Technology",
    "29": "Nonprofits & Activism",
}


def estimate_monetization(query: str, category_ids: list[str | None], fmt: str,
                          table: dict[str, Any] | None = None) -> dict[str, Any]:
    t = table or DEFAULT_MONETIZATION
    q = query.lower()
    tier = None
    basis = ""
    for level in ("high", "low", "medium"):
        hit = next((k for k in t.get(f"{level}_keywords", []) if re.search(rf"\b{re.escape(k)}", q)), None)
        if hit:
            tier, basis = level, f"query keyword '{hit}'"
            break
    cats = Counter(c for c in category_ids if c)
    top_cat = cats.most_common(1)[0][0] if cats else None
    if tier is None:
        if top_cat and top_cat in t["category_tiers"]:
            tier = t["category_tiers"][top_cat]
            basis = f"most common category '{CATEGORY_NAMES.get(top_cat, top_cat)}'"
        else:
            tier, basis = t["default_tier"], "default tier (no keyword or known category)"
    row = t["shorts" if fmt == "shorts" else "long"][tier]
    return {
        "is_estimate": True,
        "tier": tier,
        "score": row["score"],
        "rpm_range_usd": row["rpm_range_usd"],
        "basis": basis,
        "top_category": CATEGORY_NAMES.get(top_cat, top_cat) if top_cat else None,
        "label": "ESTIMATE, not data. Typical US-audience RPM; actual RPM varies by audience geography, "
                 "season, ad suitability and channel.",
    }
