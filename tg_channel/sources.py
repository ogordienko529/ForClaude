"""Free-to-keep game giveaways from the Epic Games Store and GamerPower, merged into one list without duplicates.

Both endpoints are public and need no key. Epic's is undocumented and may change: a source that fails is skipped
for that run and reported, the other one still works.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

EPIC_URL = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
EPIC_PARAMS = {"locale": "en-US", "country": "UA", "allowCountries": "UA"}
GAMERPOWER_URL = "https://www.gamerpower.com/api/giveaways"
GAMERPOWER_PARAMS = {"platform": "pc", "type": "game"}
HEADERS = {"User-Agent": "ForClaude-tg-bot/0.1 (+https://github.com/ogordienko529/ForClaude)"}

# GamerPower "platforms" words -> the store shown in the post; first match wins (order matters)
STORES = [("epic", "Epic Games Store"), ("steam", "Steam"), ("gog", "GOG"), ("itch", "itch.io"),
          ("ubisoft", "Ubisoft Connect"), ("ea games", "EA app"), ("origin", "EA app"), ("battle.net", "Battle.net")]
EPIC_IMAGES = ("OfferImageWide", "DieselStoreFrontWide", "Thumbnail", "OfferImageTall")


@dataclass
class Giveaway:
    key: str                   # stable id: "epic:<offer id>" or "gp:<giveaway id>"
    title: str
    store: str
    url: str                   # where the reader claims it
    image: str | None
    worth: str | None          # the regular price as the source writes it, e.g. "$19.99"
    ends: datetime | None      # UTC; None when the source gives no end
    ends_exact: bool           # Epic gives the exact moment; GamerPower only a date we show as a date
    source: str                # "Epic Games Store" or "GamerPower"

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["ends"] = self.ends.isoformat() if self.ends else None
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Giveaway":
        fields = {k: d.get(k) for k in cls.__dataclass_fields__}
        fields["ends"] = _iso(d.get("ends"))
        fields["ends_exact"] = bool(d.get("ends_exact"))
        return cls(**fields)


def _iso(s: Any) -> datetime | None:
    if not s or not isinstance(s, str):
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def norm(title: str) -> str:
    """A title reduced to letters and digits, to match the same game across sources."""
    return re.sub(r"[^0-9a-z]+", "", title.lower())


def clean_title(title: str) -> str:
    t = re.sub(r"\s*\((?:steam|epic games?(?: store)?|gog(?:\.com)?|itch\.io|ubisoft|ea(?: app)?|pc)\)", "", title, flags=re.I)
    t = re.sub(r"\s+(?:free\s+)?giveaway\s*$", "", t, flags=re.I)
    t = re.sub(r"\s+(?:steam\s+|gog\s+)?key\s*$", "", t, flags=re.I)
    return re.sub(r"\s{2,}", " ", t).strip(" -–")


# ---------------------------------------------------------------- Epic Games Store
def _epic_offer(el: dict, now: datetime) -> tuple[datetime, datetime] | None:
    """The promotion that makes the game free right now (Epic writes 0 % of the price as discountPercentage 0)."""
    for group in ((el.get("promotions") or {}).get("promotionalOffers") or []):
        for offer in group.get("promotionalOffers") or []:
            if (offer.get("discountSetting") or {}).get("discountPercentage") != 0:
                continue
            start, end = _iso(offer.get("startDate")), _iso(offer.get("endDate"))
            if start and end and start <= now < end:
                return start, end
    return None


def _epic_slug(el: dict) -> str | None:
    for m in (el.get("offerMappings") or []) + ((el.get("catalogNs") or {}).get("mappings") or []):
        if m.get("pageSlug") and m.get("pageType", "productHome") == "productHome":
            return m["pageSlug"]
    slug = el.get("productSlug") or el.get("urlSlug")
    return slug.split("/")[0] if slug else None


def parse_epic(data: dict, now: datetime) -> list[Giveaway]:
    elements = ((((data or {}).get("data") or {}).get("Catalog") or {}).get("searchStore") or {}).get("elements") or []
    out = []
    for el in elements:
        title = (el.get("title") or "").strip()
        if not title or "mystery" in title.lower():
            continue
        offer, slug = _epic_offer(el, now), _epic_slug(el)
        if not offer or not slug:
            continue
        price = ((el.get("price") or {}).get("totalPrice") or {})
        worth = (price.get("fmtPrice") or {}).get("originalPrice") if price.get("originalPrice") else None
        images = {img.get("type"): img.get("url") for img in el.get("keyImages") or []}
        image = next((images[t] for t in EPIC_IMAGES if images.get(t)), None)
        out.append(Giveaway(key=f"epic:{el.get('id') or slug}", title=title, store="Epic Games Store",
                            url=f"https://store.epicgames.com/p/{slug}", image=image,
                            worth=worth if worth and worth not in ("0", "$0.00") else None,
                            ends=offer[1], ends_exact=True, source="Epic Games Store"))
    return out


# ---------------------------------------------------------------- GamerPower
def _gp_store(platforms: str) -> str | None:
    p = platforms.lower()
    return next((name for word, name in STORES if word in p), None)


def _gp_end(s: Any) -> datetime | None:
    """GamerPower gives no time zone, so only the date is trusted (kept as that day's UTC midnight)."""
    if not s or not isinstance(s, str) or s.strip().upper() == "N/A":
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s.strip())
    return datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=timezone.utc) if m else None


def parse_gamerpower(items: Any, now: datetime) -> list[Giveaway]:
    out = []
    for it in items if isinstance(items, list) else []:
        if str(it.get("status", "")).lower() != "active" or str(it.get("type", "")).lower() != "game":
            continue
        store = _gp_store(str(it.get("platforms") or ""))
        title = clean_title(str(it.get("title") or ""))
        url = it.get("open_giveaway_url") or it.get("gamerpower_url")
        end = _gp_end(it.get("end_date"))
        if not store or not title or not url or (end and end.date() < now.date()):
            continue
        worth = it.get("worth")
        out.append(Giveaway(key=f"gp:{it.get('id')}", title=title, store=store, url=url,
                            image=it.get("image") or it.get("thumbnail"),
                            worth=worth if worth and str(worth).upper() != "N/A" else None,
                            ends=end, ends_exact=False, source="GamerPower"))
    return out


def merge(epic: list[Giveaway], gamerpower: list[Giveaway]) -> list[Giveaway]:
    """Epic's own data wins for Epic games (exact end time); the same game twice on GamerPower is kept once."""
    seen = {(norm(g.title), g.store) for g in epic}
    out = list(epic)
    for g in gamerpower:
        k = (norm(g.title), g.store)
        if k not in seen:
            seen.add(k)
            out.append(g)
    return out


def fetch_all(now: datetime, http: httpx.Client | None = None) -> tuple[list[Giveaway], list[str]]:
    """All giveaways active now, and one line per source that failed."""
    client = http or httpx.Client(timeout=20, headers=HEADERS, follow_redirects=True)
    errors: list[str] = []
    epic: list[Giveaway] = []
    gp: list[Giveaway] = []
    try:
        r = client.get(EPIC_URL, params=EPIC_PARAMS)
        r.raise_for_status()
        epic = parse_epic(r.json(), now)
    except (httpx.HTTPError, ValueError) as e:
        errors.append(f"Epic Games Store: {type(e).__name__}: {e}"[:300])
    try:
        r = client.get(GAMERPOWER_URL, params=GAMERPOWER_PARAMS)
        r.raise_for_status()
        gp = parse_gamerpower(r.json(), now)
    except (httpx.HTTPError, ValueError) as e:
        errors.append(f"GamerPower: {type(e).__name__}: {e}"[:300])
    return merge(epic, gp), errors
