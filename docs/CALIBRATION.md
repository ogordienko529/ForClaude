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

## Round 2 (2026-09-25): out-of-sample test on new niches, then refit

12 new Shorts and 9 new long-form niches (`*_holdout` in `calibration/panel.toml`), never used while
designing v2. They cost 8,643 units. First v2 was run **unchanged** on them:

| Out-of-sample (holdout only, v2 unchanged) | Shorts (n=11) | Long (n=9) |
|---|---:|---:|
| View score ρ with the outcome | **0.78** | **0.32** |
| Opportunity alone | 0.79 | 0.57 |
| Demand alone | 0.72 | 0.38 |

Shorts generalised: the holdout ρ even beat the design set's. Long-form did not. On the 5 design
niches, demand, velocity and consistency had looked strong; on new niches only opportunity and
demand held up. The long-form holdout is also harder to rank, because its outcome rates sit in a
narrow 6–25% band.

**Refit, using all niches (21 Shorts, 14 long-form).** Five pre-declared weight sets were compared:
current, current-Shorts, correlation-fitted, opportunity+demand, and demand-heavy. Bands were reset to
the panel's 10th–90th percentiles widened ×1.5. To keep the choice honest, the whole "pick the best of
five" procedure was scored leave-one-out: each niche is predicted by the set chosen without it.

| | Shorts | Long |
|---|---:|---:|
| Chosen weights | unchanged: opportunity .35, demand .30, new-channel .15, velocity .10, consistency .10 | opportunity .50, demand .50 |
| ρ, all niches (in-sample) | 0.76 | 0.83 |
| ρ, holdout niches | 0.78 (untouched) | 0.75 (after the refit) |
| **ρ, leave-one-out selection (honest)** | **0.73** | **0.83** |
| Forecast MAE (leave-one-out) vs constant | 0.288 vs 0.320 | 0.046 vs 0.058 |
| 80% range coverage | 71% | 86% |
| Score std across niches | 21.7 | 24.3 |

Forecast priors were updated to prior hit rate 0.48 for Shorts and 0.13 for long-form, with drift
sd 0.30 and 0.055.

**Why Shorts coverage is 71%, not 80%.** In the backtest, the 60–30-day window's search results have
systematically lower hit rates than the 21–7-day outcome window (mean 0.2 vs 0.48). YouTube search
returns older date windows differently, so forecasts from the past window run low. In production,
the forecast's input sample and the period it predicts are the same age (uploads ≥ 7 days old,
newest first), so this bias should not apply. That cannot be proven without real day-14 tracking,
though, so P2 for Shorts is marked partially met.

### Final backtest tables (all niches, final config)

#### Shorts

| Niche | View score (past) | Past small hit rate | Outcome hit rate | Outcome n |
|---|---:|---:|---:|---:|
| funny cats | 89 | 0.45 (15/33) | 0.80 (16/20) | 20 |
| life hacks | 86 | 0.53 (9/17) | 0.94 (15/16) | 16 |
| football skills | 85 | 0.54 (14/26) | 0.88 (14/16) | 16 |
| fishing | 79 | 0.26 (9/34) | 0.86 (12/14) | 14 |
| cooking hacks | 75 | 0.80 (16/20) | 0.54 (7/13) | 13 |
| minecraft shorts | 69 | 0.17 (5/29) | 1.00 (15/15) | 15 |
| motivational quotes | 67 | 0.10 (3/29) | 1.00 (16/16) | 16 |
| gym motivation | 65 | 0.10 (3/31) | 0.33 (4/12) | 12 |
| makeup tutorial | 64 | 0.13 (4/31) | 0.67 (8/12) | 12 |
| history facts | 62 | 0.17 (8/47) | 0.44 (12/27) | 27 |
| science experiments | 60 | 0.29 (7/24) | 0.38 (10/26) | 26 |
| geography facts | 54 | 0.18 (6/33) | 0.03 (1/29) | 29 |
| english learning | 52 | 0.15 (4/27) | 0.94 (17/18) | 18 |
| tech gadgets | 51 | 0.04 (1/23) | 0.17 (3/18) | 18 |
| psychology facts | 42 | 0.15 (5/34) | 0.50 (15/30) | 30 |
| space facts | 32 | 0.03 (1/32) | 0.07 (2/30) | 30 |
| dog training tips | 32 | 0.12 (5/41) | 0.14 (5/35) | 35 |
| roman empire history | 31 | 0.00 (0/42) | 0.18 (8/44) | 44 |
| bible verses | 25 | 0.06 (2/31) | 0.05 (1/22) | 22 |
| math tricks | 23 | 0.07 (2/27) | 0.00 (0/15) | 15 |
| personal finance tips | 15 | 0.03 (1/39) | 0.08 (2/25) | 25 |

**P1/P3: Spearman ρ with the outcome hit rate**

| Signal | ρ |
|---|---:|
| component: opportunity | 0.76 |
| component: demand | 0.77 |
| component: new_channel_proof | 0.44 |
| component: velocity | 0.43 |
| component: consistency | 0.22 |
| component: competition | -0.59 |
| component: monetization | -0.37 |
| view_score_current_weights | 0.76 |
| final_score_incl_monetization | 0.76 |
| past_small_hit_rate_only | 0.56 |
| sample_only_view_score | – |
| fitted weights, leave-one-out | 0.75 |

**P4: fitted (correlation-proportional) weights**: opportunity 0.29, demand 0.29, new_channel_proof 0.17, velocity 0.16, consistency 0.08, competition 0.00

**P2: forecast (leave-one-out)** MAE 0.288 (constant baseline 0.320); 80% interval coverage 71%; ρ 0.57. Drift sd 0.300.

**S2**: final score std 21.7; share of niches at 0/100 per component: opportunity 0%, demand 14%, new_channel_proof 0%, velocity 10%, consistency 0%, competition 0%, monetization 0%
**S3**: niches with ≥30 videos in the base sample: 79%
**D1**: short_unverified videos: 0; **D2**: kept videos with mostly non-Latin titles: 0.6%
**D4**: paid-promotion flagged channels: Desi Jugaad Facts, USZXEDITZ, shayari -0md 

**Suggested bands (panel p10 → p90)**: small_views 155468.0 → 12562059.0; demand_views 115836.0 → 8635583.0; velocity 5.1 → 1159.6
**Panel mean outcome hit rate (prior)**: 0.476

#### Long-form

| Niche | View score (past) | Past small hit rate | Outcome hit rate | Outcome n |
|---|---:|---:|---:|---:|
| true crime documentary | 92 | 0.28 (16/58) | 0.22 (13/59) | 59 |
| aviation history | 74 | 0.27 (17/64) | 0.25 (16/65) | 65 |
| home workout | 72 | 0.13 (7/55) | 0.12 (6/49) | 49 |
| ai tools tutorial | 71 | 0.18 (7/39) | 0.14 (4/28) | 28 |
| minecraft survival | 53 | 0.03 (2/72) | 0.25 (9/36) | 36 |
| woodworking projects | 53 | 0.16 (11/69) | 0.12 (8/64) | 64 |
| chess openings | 50 | 0.07 (5/75) | 0.18 (12/66) | 66 |
| real estate investing | 50 | 0.05 (4/83) | 0.13 (8/63) | 63 |
| space documentary | 49 | 0.06 (5/81) | 0.06 (4/71) | 71 |
| sleep stories | 47 | 0.17 (13/75) | 0.09 (7/77) | 77 |
| mythology explained | 39 | 0.14 (10/74) | 0.08 (6/73) | 73 |
| stoicism philosophy | 16 | 0.03 (2/78) | 0.05 (4/76) | 76 |
| budget travel | 12 | 0.05 (3/60) | 0.06 (2/32) | 32 |
| personal finance for beginners | 2 | 0.00 (0/67) | 0.01 (1/68) | 68 |

**P1/P3: Spearman ρ with the outcome hit rate**

| Signal | ρ |
|---|---:|
| component: opportunity | 0.58 |
| component: demand | 0.77 |
| component: new_channel_proof | 0.10 |
| component: velocity | 0.35 |
| component: consistency | -0.06 |
| component: competition | -0.54 |
| component: monetization | -0.33 |
| view_score_current_weights | 0.83 |
| final_score_incl_monetization | 0.71 |
| past_small_hit_rate_only | 0.50 |
| sample_only_view_score | – |
| without_20min_plus_bucket | 0.54 |
| share_of_hits_over_20min | 0.67 |
| fitted weights, leave-one-out | 0.52 |

**P4: fitted (correlation-proportional) weights**: opportunity 0.32, demand 0.43, new_channel_proof 0.05, velocity 0.19, consistency 0.00, competition 0.00

**P2: forecast (leave-one-out)** MAE 0.046 (constant baseline 0.058); 80% interval coverage 86%; ρ 0.50. Drift sd 0.055.

**S2**: final score std 24.3; share of niches at 0/100 per component: opportunity 0%, demand 7%, new_channel_proof 0%, velocity 7%, consistency 0%, competition 0%, monetization 0%
**S3**: niches with ≥30 videos in the base sample: 100%
**D1**: short_unverified videos: 0; **D2**: kept videos with mostly non-Latin titles: 0.5%
**D4**: paid-promotion flagged channels: none

**Suggested bands (panel p10 → p90)**: small_views 9462.0 → 338064.0; demand_views 20062.0 → 798588.0; velocity 1.6 → 67.0
**Panel mean outcome hit rate (prior)**: 0.127

## What calibration cannot fix

- **Shorts are volatile.** A niche's small-channel hit rate moves about ±30 percentage points from one month
  to the next, so Shorts forecasts are honest but wide. Long-form moves about ±5 pp.
- **YouTube search decides the sample:** at most 50 results per search, chosen by YouTube.
- **Current views only.** True "views at day 14" needs repeated snapshots of the same videos. The
  cache already stores snapshots, so a daily re-collection routine would turn this into real
  14-day tracking and a direct P2 check.
