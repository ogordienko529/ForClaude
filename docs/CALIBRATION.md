# Calibration log

How the scoring was checked against reality and what changed as a result. Criteria and targets are
in `docs/QUALITY_CRITERIA.md`. Reproduce any table with
`python -m niche_core backtest -f shorts|long` (offline from the cache; add `--collect` to fetch).

## Method: temporal backtest

For each niche in `calibration/panel.toml`:

- **Features:** the normal scoring pipeline run on uploads published 60–30 days ago (a view-ordered
  pool plus a date-ordered sample, exactly like `analyze_niche`).
- **Outcome:** uploads published 21–7 days ago, small channels only (≤ 50k subs). It measures the
  share that reached 10,000 views. Their views are 1–3 weeks old, so this is close to "10k within
  14 days".
- **P1:** Spearman ρ between the past score and the later outcome, across niches.
- **P2:** leave-one-out evaluation of the production forecast (`scoring.forecast`). For each held-out
  niche, the prior and drift are measured on the other niches.
- Only aggregates are kept here. Raw API data stays in the local cache, which is purged after 30 days.

## Round 1 (2026-09-24): v1 scoring, 10 Shorts + 5 long-form niches

| Signal (Spearman ρ with outcome) | Shorts | Long |
|---|---:|---:|
| Opportunity (v1) | 0.45 | 0.40 |
| New-channel proof (v1) | 0.52 | −0.22 |
| Velocity (v1) | −0.17 (bug) | – (bug) |
| Consistency | 0.30 | −0.30 |
| Competition (fewer big channels = better) | **−0.61** | **−0.90** |
| Monetization (not meant to predict views) | −0.72 | −0.74 |
| **Final score, v1 weights** | **0.24** | **−0.10** |
| Past small-channel hit rate alone | 0.49 | 0.70 |

Findings:

1. **Competition had the wrong sign.** Niches where 100k+ channels dominate the top results are the
   ones where small channels also do well. Big channels signal demand, not a barrier.
2. **Velocity was broken.** It only counted videos younger than 30 days, so on the 30–60-day
   window it was always 0. The same bug affected any `published_within_days > 30`.
3. **The paid-promotion rule** (channel avg views/subs ≥ 100) flagged tiny channels with 1 sub and
   1 video, plus successful small Minecraft channels. A real ad-driven brand video shows 0.00% likes
   and 0 comments on 3.6M views, while organic hits sit at 0.2–3% likes. The rule was switched to engagement.
4. **The best new signals**, by a feature sweep over the Shorts panel:
   - median views of small channels in the top results: ρ 0.83;
   - median views of the top results ("demand"): ρ 0.77 Shorts, 0.66 long.
5. **New-channel proof and velocity saturated** at 0 or 100 for ≥ 60–90% of niches.
6. **74% of long-form hits are over 20 minutes long.** The `long` duration bucket must stay (C1).

## v2 scoring (this commit)

- Opportunity = shrunk small-channel hit rate (date sample) + median views of small channels in
  the top results.
- New **Demand** component = median views of the top results.
- Competition kept as information, weight 0 by default.
- New-channel proof made continuous: log count of new channels with hits, plus their shrunk hit rate.
- Velocity fixed.
- Monetization separated out: `final = 0.85 × view_score + 0.15 × monetization`.
- New **forecast** (hit probability + 80% range).
- New bootstrap 80% range on the view score.
- Paid-promotion filter based on engagement.
- Bands set from the panel's 10th–90th percentiles.

### Round 1 data, v2 scoring: Shorts

| Niche | View score (past) | Past small hit rate | Outcome hit rate | Outcome n |
|---|---:|---:|---:|---:|
| funny cats | 91 | 0.45 (15/33) | 0.80 (16/20) | 20 |
| life hacks | 88 | 0.53 (9/17) | 0.94 (15/16) | 16 |
| football skills | 88 | 0.54 (14/26) | 0.88 (14/16) | 16 |
| cooking hacks | 78 | 0.80 (16/20) | 0.54 (7/13) | 13 |
| motivational quotes | 72 | 0.10 (3/29) | 1.00 (16/16) | 16 |
| geography facts | 58 | 0.18 (6/33) | 0.03 (1/29) | 29 |
| psychology facts | 48 | 0.15 (5/34) | 0.50 (15/30) | 30 |
| space facts | 38 | 0.03 (1/32) | 0.07 (2/30) | 30 |
| roman empire history | 36 | 0.00 (0/42) | 0.18 (8/44) | 44 |
| math tricks | 29 | 0.07 (2/27) | 0.00 (0/15) | 15 |

**P1/P3: Spearman ρ with the outcome hit rate**

| Signal | ρ |
|---|---:|
| component: opportunity | 0.75 |
| component: demand | 0.77 |
| component: new_channel_proof | 0.56 |
| component: velocity | 0.50 |
| component: consistency | 0.30 |
| component: competition | -0.61 |
| component: monetization | -0.72 |
| view_score_current_weights | 0.76 |
| final_score_incl_monetization | 0.75 |
| past_small_hit_rate_only | 0.49 |
| sample_only_view_score | – |
| fitted weights, leave-one-out | 0.76 |

**P4: fitted (correlation-proportional) weights**: opportunity 0.26, demand 0.27, new_channel_proof 0.20, velocity 0.17, consistency 0.10, competition 0.00

**P2: forecast (leave-one-out)** MAE 0.299 (constant baseline 0.338); 80% interval coverage 80%; ρ 0.38. Drift sd 0.305.

**S2**: final score std 22.6; share of niches at 0/100 per component: opportunity 0%, demand 10%, new_channel_proof 0%, velocity 0%, consistency 0%, competition 0%, monetization 0%
**S3**: niches with ≥30 videos in the base sample: 75%
**D1**: short_unverified videos: 0; **D2**: kept videos with mostly non-Latin titles: 0.8%
**D4**: paid-promotion flagged channels: Desi Jugaad Facts, USZXEDITZ, shayari -0md 

**Suggested bands (panel p10 → p90)**: small_views 155468.0 → 12668135.0; demand_views 239318.0 → 14136495.0; velocity 9.7 → 1728.5
**Panel mean outcome hit rate (prior)**: 0.493

### Round 1 data, v2 scoring: long-form (only 5 niches: indicative)

| Niche | View score (past) | Past small hit rate | Outcome hit rate | Outcome n |
|---|---:|---:|---:|---:|
| true crime documentary | 85 | 0.28 (16/58) | 0.22 (13/59) | 59 |
| ai tools tutorial | 71 | 0.18 (7/39) | 0.14 (4/28) | 28 |
| minecraft survival | 37 | 0.03 (2/72) | 0.25 (9/36) | 36 |
| stoicism philosophy | 36 | 0.03 (2/78) | 0.05 (4/76) | 76 |
| personal finance for beginners | 15 | 0.00 (0/67) | 0.01 (1/68) | 68 |

**P1/P3: Spearman ρ with the outcome hit rate**

| Signal | ρ |
|---|---:|
| component: opportunity | 0.40 |
| component: demand | 1.00 |
| component: new_channel_proof | 0.00 |
| component: velocity | 0.40 |
| component: consistency | -0.40 |
| component: competition | -0.90 |
| component: monetization | -0.74 |
| view_score_current_weights | 0.70 |
| final_score_incl_monetization | 0.40 |
| past_small_hit_rate_only | 0.70 |
| sample_only_view_score | – |
| without_20min_plus_bucket | 0.70 |
| share_of_hits_over_20min | 0.74 |
| fitted weights, leave-one-out | 0.70 |

**P4: fitted (correlation-proportional) weights**: opportunity 0.22, demand 0.56, new_channel_proof 0.00, velocity 0.22, consistency 0.00, competition 0.00

**P2: forecast (leave-one-out)** MAE 0.058 (constant baseline 0.082); 80% interval coverage 80%; ρ 0.40. Drift sd 0.074.

**S2**: final score std 25.4; share of niches at 0/100 per component: opportunity 0%, demand 20%, new_channel_proof 0%, velocity 0%, consistency 0%, competition 0%, monetization 0%
**S3**: niches with ≥30 videos in the base sample: 100%
**D1**: short_unverified videos: 0; **D2**: kept videos with mostly non-Latin titles: 0.7%
**D4**: paid-promotion flagged channels: none

**Suggested bands (panel p10 → p90)**: small_views 1511.0 → 513879.0; demand_views 14382.0 → 2257858.0; velocity 1.0 → 127.5
**Panel mean outcome hit rate (prior)**: 0.136

### Where v2 stands against the criteria (round 1 data)

| Criterion | Shorts | Long | Target |
|---|---|---|---|
| P1: view score ρ with outcome (current weights) | **0.76** (v1: 0.24) | **0.70** (v1: −0.10; n=5) | ≥ 0.5 |
| P1: fitted weights, leave-one-out ρ | 0.76 | 0.70 (n=5) | ≥ 0.5 |
| P2: forecast MAE vs constant baseline | 0.30 vs 0.34 | 0.058 vs 0.082 | beat the baseline |
| P2: 80% interval coverage | 80% | 80% | ≈ 80% |
| S2: score std across niches; components stuck at 0/100 | 22.6; none ≥ 80% | 25.4; none ≥ 80% | ≥ 12; none |

Shorts hit rates move a lot from month to month (drift sd 0.30), so a Shorts forecast is honest
but wide. Long-form hit rates are stable (drift sd 0.08), so the long-form forecast is informative.

## Next

Round 2 will run after the quota reset: the rest of the long-form panel plus more Shorts niches,
so both formats have ≥ 12 niches. Then weights and bands are refitted, P1/P2 are re-checked, and
the results are appended here.
