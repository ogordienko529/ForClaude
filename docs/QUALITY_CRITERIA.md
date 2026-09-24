# Quality criteria

What "good" means for this tool, how each criterion is measured, what measuring it costs in API
quota, and where it stands. The **Status** column is updated as work progresses; results and
evidence are in `docs/CALIBRATION.md`.

The tool's job: *tell a new or small channel which niches give it a realistic chance of 10,000+
views per video within 1–14 days, and how much that is worth.* So the most important criteria are
predictive, not cosmetic.

## Status

| ID | Status | Evidence |
|---|---|---|
| P1 | Shorts ρ 0.76, long ρ 0.70 (v1: 0.24 / −0.10). Long-form rests on only 5 niches so far | CALIBRATION.md, round 1 |
| P2 | Forecast built (hit probability + 80% range). Beats the constant baseline in both formats; coverage 80% | CALIBRATION.md |
| P3 | Competition and monetization carry no predictive weight (competition reported only, monetization is a separate axis) | CALIBRATION.md |
| P4 | Fitted per format; final fit after round 2 | pending round 2 |
| S1 | Done: bootstrap 80% range on the view score; low-confidence flag uses its width | `scoring.bootstrap_interval` |
| S2 | Shorts std 22.6, long std 25.4; no component stuck at 0/100 | CALIBRATION.md |
| S3 | 75% of Shorts niches and 100% of long-form niches have ≥ 30 base-sample videos | CALIBRATION.md |
| D1 | 0 unverified Shorts in the panel | CALIBRATION.md |
| D2 | 0.7–0.8% non-Latin titles kept | CALIBRATION.md |
| D4 | Rule switched to engagement: organic hits are no longer flagged, the brand ad still is | tests + panel |
| C1 | The pool search is needed (demand is its strongest signal); the `long` bucket is needed (74% of long-form hits are over 20 min) | CALIBRATION.md |
| C2 | Fixed: pagination capped at the estimate; the guard is checked before every retry | tests |
| R2 | All 15 review findings fixed (3 high, 6 medium, 6 low) | `tests/test_review_fixes.py` |
| R3 | 99 tests green | pytest |

## P. Prediction

| ID | Criterion | Metric / target | How it is measured | Quota cost | Priority |
|---|---|---|---|---|---|
| P1 | The score ranks niches by the real future hit rate of small channels | Spearman ρ ≥ 0.5 between score (computed on a **past** window) and the **later** hit rate, ≥ 20 niches per format | Temporal backtest: features from uploads 30–60 days old, target = share of small-channel uploads 7–21 days old that reached the hit threshold | ~306 units per Shorts niche, ~612 per long-form niche | Critical |
| P2 | An explicit forecast: "chance that a small channel's upload reaches 10k within 14 days", with an interval | Backtest mean absolute error ≤ 10 percentage points; ≥ 70% of actual rates inside the 80% interval | Same backtest data | 0 extra | Critical |
| P3 | Every weighted component earns its weight | Each component has ρ ≥ 0 with the target, otherwise weight → 0 | Per-component correlation on backtest data | 0 extra | High |
| P4 | Weights come from data, not guesses | Fitted weights beat hand weights in leave-one-out cross-validation | Offline fit on backtest data | 0 extra | High |

## S. Statistical reliability

| ID | Criterion | Metric / target | How it is measured | Quota cost | Priority |
|---|---|---|---|---|---|
| S1 | Every score shows its uncertainty | Bootstrap 80% interval on final score and forecast; "low confidence" driven by interval width, not ad-hoc rules | Bootstrap resampling of the fetched videos | 0 | High |
| S2 | Scores discriminate between niches | Across the panel: std of final score ≥ 12; no component stuck at 0 or 100 for ≥ 80% of niches | Panel statistics | 0 extra | High |
| S3 | Samples are big enough | Base-rate sample ≥ 30 in-format videos in ≥ 80% of niches | Panel statistics | 0 extra | Medium |
| S4 | Scores are stable day to day | Re-run after 24 h: median change ≤ 8 points | Re-run a subset after caches expire | ~400 per niche | Low (deferred) |

## D. Data correctness

| ID | Criterion | Metric / target | How it is measured | Quota cost | Priority |
|---|---|---|---|---|---|
| D1 | Shorts vs long-form classification is right | Short = ≤ 180 s and vertical embed; `short_unverified` < 2% of short-bucket videos | Counts on panel data + unit tests | 0 extra | High |
| D2 | Language filter keeps the sample in the target language | < 5% of kept videos have mostly non-Latin titles when language = en | Title script check on panel data | 0 extra | Medium |
| D3 | Hidden/missing stats never become 0 | Unit tests; counts reported in `data_quality` | Tests | 0 | Done |
| D4 | Paid-promotion filter is precise | Flagged channels are really ad-driven on manual check | Manual review of flagged channels in panel | 0 extra | Medium |

## C. Cost

| ID | Criterion | Metric / target | How it is measured | Quota cost | Priority |
|---|---|---|---|---|---|
| C1 | An analysis costs as little as possible without losing P1 | Drop any search that doesn't improve backtest ρ | Ablations on backtest data (pool vs sample, `long` bucket) | 0 extra | High |
| C2 | Cost estimates are never below the real cost | actual ≤ estimated on every run | Tests + receipts | 0 | Done |
| C3 | Enough niches per day | ≥ 24 long-form or ≥ 45 Shorts analyses per 10,000 units | Arithmetic from C1 | 0 | Medium |
| C4 | Repeats are nearly free | Re-running within TTL costs ≤ 5 units | Receipts | 0 | Done |

## R. Robustness and code quality

| ID | Criterion | Metric / target | How it is measured | Quota cost | Priority |
|---|---|---|---|---|---|
| R1 | Failures degrade gracefully | Quota exhaustion / API errors give structured, partial results | Tests | 0 | Done |
| R2 | No known correctness bugs | 0 open high/medium findings from an independent code review | Review | 0 | High |
| R3 | Tests cover the scoring and forecast logic | All new logic has fixture tests; suite green | pytest | 0 | High |

## U. Usability

| ID | Criterion | Metric / target | How it is measured | Quota cost | Priority |
|---|---|---|---|---|---|
| U1 | Reports read as a decision, not a data dump | Report opens with forecast + interval + verdict, then evidence | Review of real reports | 0 | Medium |
| U2 | MCP tools and README describe the new behaviour | Docs updated, tools listed | Review | 0 | Medium |

## Feasibility and budget

- Search results are capped at 50 per call and chosen by YouTube, so "unbiased" samples are only
  approximately unbiased. The backtest measures the whole pipeline end to end, which is what matters.
- The API gives current views only, not views at day 14. The backtest target uses uploads that are
  7–21 days old, so their current views ≈ views within their first 1–3 weeks.
- A 24-niche panel (12 Shorts + 12 long-form) costs ≈ 11,000 units, i.e. about two days of quota.
  The panel is cached, so every later calibration iteration is free.
