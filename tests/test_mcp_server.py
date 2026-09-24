import asyncio

from niche_mcp import server


def test_all_seven_tools_registered():
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert names == {"search_niche", "get_channel_stats", "find_outliers", "analyze_niche",
                     "compare_niches", "expand_keywords", "quota_status"}


def test_tools_return_structured_errors(monkeypatch, service):
    monkeypatch.setattr(server, "service", lambda: service)
    assert server.analyze_niche("x", format="both", max_units=10)["error_type"] == "quota_budget"
    assert server.search_niche("x", format="bogus")["error_type"] == "invalid_argument"


def test_tool_passes_through_to_service(monkeypatch, service):
    monkeypatch.setattr(server, "service", lambda: service)
    out = server.find_outliers("lighthouse lore", format="shorts", min_outlier_score=1)
    assert out["tool"] == "find_outliers" and "quota" in out
    assert server.quota_status()["used_today"] == out["quota"]["used_today"]
