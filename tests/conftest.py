from __future__ import annotations

import pytest

from niche_core.cache import Store
from niche_core.config import load_config
from niche_core.quota import QuotaTracker
from niche_core.service import NicheService
from niche_core.youtube_client import YouTubeClient

from .fakes import FIXED_NOW, FakeYouTube, load_items


class Clock:
    def __init__(self, now=FIXED_NOW):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def config(tmp_path):
    return load_config(overrides={"paths": {"db_path": ":memory:", "reports_dir": str(tmp_path / "reports")}})


@pytest.fixture
def fake():
    items = load_items()
    return FakeYouTube(
        items["videos"],
        items["channels"],
        search_results={
            "short": ["vShortVert01", "vShortHoriz1", "vLiveNow0001"],
            "medium": [],
            "long": ["vLongLore001"],
        },
    )


@pytest.fixture
def service(config, clock, fake):
    store = Store(":memory:", clock=clock)
    quota = QuotaTracker(store, config.daily_quota)
    client = YouTubeClient("TEST-KEY-123", quota, http=fake.http_client(), sleep=lambda s: None)
    return NicheService(config, store=store, client=client, clock=clock)
