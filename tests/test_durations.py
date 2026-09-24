import pytest

from niche_core.durations import (
    LIVE, LONG, SHORT, SHORT_LONGFORM, SHORT_UNVERIFIED, classify_format, format_seconds, parse_iso8601_duration,
)


@pytest.mark.parametrize(
    "raw,expected",
    [("PT58S", 58), ("PT2M30S", 150), ("PT1H2M3S", 3723), ("PT42M10S", 2530), ("P1DT1S", 86401),
     ("P0D", 0), ("PT0.5S", 0), ("", None), (None, None), ("garbage", None)],
)
def test_parse_duration(raw, expected):
    assert parse_iso8601_duration(raw) == expected


def test_vertical_short_is_short():
    assert classify_format(58, 405, 720) == SHORT


def test_horizontal_under_180_is_short_longform():
    assert classify_format(150, 1280, 720) == SHORT_LONGFORM


def test_square_is_not_short():
    assert classify_format(60, 720, 720) == SHORT_LONGFORM


def test_missing_embed_is_unverified():
    assert classify_format(60, None, None) == SHORT_UNVERIFIED


def test_boundary_180_vs_181():
    assert classify_format(180, 405, 720) == SHORT
    assert classify_format(181, 405, 720) == LONG


def test_live_and_zero_duration():
    assert classify_format(0, 1280, 720) == LIVE
    assert classify_format(600, 1280, 720, "upcoming") == LIVE


def test_format_seconds():
    assert format_seconds(58) == "0:58"
    assert format_seconds(3723) == "1:02:03"
