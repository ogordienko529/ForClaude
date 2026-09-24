from niche_core.patterns import expand_candidates


def test_expand_requires_multiple_channels_and_skips_seed():
    vids = [
        ("c1", "The fall of Carthage explained", ["punic wars", "carthage"], 20),
        ("c2", "Why Carthage lost the Punic Wars", ["punic wars", "hannibal"], 15),
        ("c3", "Hannibal crosses the Alps", ["punic wars", "hannibal"], 10),
        ("c3", "Hannibal at Cannae", ["spamtag", "hannibal"], 10),
        ("c3", "Hannibal's elephants", ["spamtag"], 10),
    ]
    out = expand_candidates(vids, seed="roman history")
    phrases = {d["phrase"]: d for d in out}
    assert "punic wars" in phrases and phrases["punic wars"]["channels"] == 3
    assert "spamtag" not in phrases  # one channel only
    assert all(d["phrase"] not in ("roman", "history", "roman history") for d in out)
    assert not any(w in ("explained", "fall") for d in out for w in d["phrase"].split()[:1] + d["phrase"].split()[-1:])
    assert phrases["punic wars"]["query"] == "punic wars"
    single = next(d for d in out if len(d["phrase"].split()) == 1)
    assert single["query"].startswith("roman history ")


def test_compare_niches_ranks_and_renders(service, fake):
    dry = service.compare_niches(["lighthouse lore", "keeper stories"], format="both", dry_run=True)
    assert dry["quota_estimate"]["total"] == sum(dry["quota_estimate"]["per_query"].values())
    assert fake.calls == []
    out = service.compare_niches(["lighthouse lore", "keeper stories", "lighthouse lore"], format="both")
    assert {r["query"] for r in out["ranking"]} == {"lighthouse lore", "keeper stories"}  # duplicate removed
    assert out["table_markdown"].startswith("## Niche comparison")
    assert "| 1 |" in out["table_markdown"]
    scores = [r["final_score"] for r in out["ranking"]]
    assert scores == sorted(scores, reverse=True)
    assert 0 < out["quota"]["actual"] <= out["quota"]["estimated"]


def test_expand_keywords_uses_cache_after_first_run(service, fake):
    first = service.expand_keywords("lighthouse lore", format="both")
    assert first["source"].startswith("find_outliers")
    calls = len(fake.calls)
    second = service.expand_keywords("lighthouse lore", format="both")
    assert second["source"] == "cache"
    assert second["quota"]["estimated"] == 0 and second["quota"]["actual"] == 0
    assert len(fake.calls) == calls


def test_quota_status_after_compare(service, fake):
    service.compare_niches(["lighthouse lore"], format="shorts")
    st = service.quota_status()
    assert st["used_today"] > 0 and st["remaining"] == 10_000 - st["used_today"]


def test_expand_drops_seed_variants():
    vids = [(f"c{i}", f"Rome and the Romans: legion tactics #romanempire", ["romanempire", "rome"], 5) for i in range(3)]
    phrases = {d["phrase"] for d in expand_candidates(vids, seed="roman empire")}
    assert not phrases & {"rome", "romans", "romanempire"}
    assert "legion tactics" in phrases
