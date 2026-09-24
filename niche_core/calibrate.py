"""Calibration report over backtest cases: measures the QUALITY_CRITERIA (P1-P4, S2-S3, C1, D1-D4)."""

from __future__ import annotations

import statistics
import unicodedata
from typing import Any

from .backtest import (
    Case, Row, drift_sd, evaluate_cases, fit_weights, forecast_eval, loo_spearman, spearman, weighted,
)
from .scoring import COMPONENTS, VIEW_COMPONENTS, ScoringParams, suspected_paid_promotion


def _non_latin(title: str) -> bool:
    letters = [ch for ch in title if ch.isalpha()]
    if not letters:
        return False
    latin = sum(1 for ch in letters if "LATIN" in unicodedata.name(ch, ""))
    return latin / len(letters) < 0.5


def _f(x: float | None, nd: int = 2) -> str:
    return "–" if x is None else f"{x:.{nd}f}"


def _pct(xs: list[float], q: float) -> float | None:
    xs = sorted(x for x in xs if x is not None and x > 0)
    if not xs:
        return None
    return xs[min(int(q * len(xs)), len(xs) - 1)]


def analyse(cases: list[Case], p: ScoringParams) -> dict[str, Any]:
    rows = evaluate_cases(cases, p)
    ys = [r.outcome["rate"] for r in rows]
    comps = list(VIEW_COMPONENTS)  # monetization doesn't predict views by design
    prior_strength, weights = p.prior_strength, p.weights

    per_component = {
        k: spearman([r.features["components"][k]["score"] for r in rows], ys) for k in COMPONENTS
    }
    finals = [r.features["view_score"] for r in rows]
    fitted = fit_weights(rows, comps) if len(rows) >= 5 else {}

    # Ablation C1: features from the date sample only (no view-ordered pool search).
    sample_only_rows = evaluate_cases(
        [Case(c.query, c.fmt, [], c.sample, c.target, c.monetization, c.excluded) for c in cases], p
    )
    ablations = {
        "view_score_current_weights": spearman(finals, ys),
        "final_score_incl_monetization": spearman([r.features["final_score"] for r in rows], ys),
        "past_small_hit_rate_only": spearman([r.past["rate"] or 0 for r in rows], ys),
        "sample_only_view_score": spearman([r.features["view_score"] for r in sample_only_rows],
                                      [r.outcome["rate"] for r in sample_only_rows]),
    }
    if p.fmt == "long":
        trimmed = [Case(c.query, c.fmt, [e for e in c.pool if (e.video.duration_s or 0) <= 1200],
                        [e for e in c.sample if (e.video.duration_s or 0) <= 1200],
                        [e for e in c.target if (e.video.duration_s or 0) <= 1200], c.monetization, c.excluded)
                   for c in cases]
        tr = evaluate_cases(trimmed, p)
        ablations["without_20min_plus_bucket"] = spearman([r.features["view_score"] for r in tr],
                                                          [r.outcome["rate"] for r in tr])
        all_hits = [e for c in cases for e in c.target + c.sample if e.is_hit]
        ablations["share_of_hits_over_20min"] = (
            sum(1 for e in all_hits if (e.video.duration_s or 0) > 1200) / len(all_hits) if all_hits else None
        )

    saturation = {}
    for k in COMPONENTS:
        vals = [r.features["components"][k]["score"] for r in rows]
        saturation[k] = sum(1 for v in vals if v <= 0.5 or v >= 99.5) / len(vals) if vals else None

    all_videos = [e for c in cases for e in c.pool + c.sample + c.target]
    short_bucket = sum(c.excluded.get("short_unverified", 0) for c in cases)
    promo = sorted({e.video.channel_title for c in cases for e in c.pool + c.sample if suspected_paid_promotion(e, p)})
    raw = lambda comp, key: [r.features["components"][comp]["raw"].get(key) for r in rows]  # noqa: E731
    bands = {
        "small_views": (_pct(raw("opportunity", "median_views_small_channel_top"), 0.1),
                        _pct(raw("opportunity", "median_views_small_channel_top"), 0.9)),
        "demand_views": (_pct(raw("demand", "median_views_top_results"), 0.1),
                         _pct(raw("demand", "median_views_top_results"), 0.9)),
        "velocity": (_pct(raw("velocity", "median_views_per_day"), 0.1), _pct(raw("velocity", "median_views_per_day"), 0.9)),
    }
    return {
        "suggested_bands": bands,
        "prior_hit_rate": statistics.fmean(ys) if ys else None,
        "rows": rows,
        "n_cases": len(cases),
        "n_evaluable": len(rows),
        "per_component": per_component,
        "fitted_weights": fitted,
        "loo_spearman_fitted": loo_spearman(rows, comps),
        "ablations": ablations,
        "forecast": forecast_eval(rows, p),
        "drift_sd": drift_sd(rows, prior_strength),
        "final_std": statistics.pstdev(finals) if len(finals) > 1 else None,
        "saturation": saturation,
        "sample_adequacy": (sum(1 for c in cases if len(c.sample) >= 30) / len(cases)) if cases else None,
        "short_unverified": short_bucket,
        "non_latin_share": (sum(1 for e in all_videos if _non_latin(e.video.title)) / len(all_videos)) if all_videos else None,
        "promo_flagged": promo,
        "current_weights_spearman": spearman([weighted(r, weights) for r in rows], ys),
    }


def render(result: dict[str, Any], p: ScoringParams) -> str:
    rows: list[Row] = result["rows"]
    L = [f"### Backtest: {p.fmt} ({result['n_evaluable']}/{result['n_cases']} niches with ≥8 small-channel "
         f"uploads in the outcome window)", ""]
    L += ["| Niche | View score (past) | Past small hit rate | Outcome hit rate | Outcome n |", "|---|---:|---:|---:|---:|"]
    for r in sorted(rows, key=lambda r: -r.features["view_score"]):
        L.append(f"| {r.query} | {r.features['view_score']:.0f} | {_f(r.past['rate'])} ({r.past['hits']}/{r.past['n']}) "
                 f"| {_f(r.outcome['rate'])} ({r.outcome['hits']}/{r.outcome['n']}) | {r.outcome['n']} |")
    L += ["", "**P1/P3: Spearman ρ with the outcome hit rate**", ""]
    L += ["| Signal | ρ |", "|---|---:|"]
    for k, v in result["per_component"].items():
        L.append(f"| component: {k} | {_f(v)} |")
    for k, v in result["ablations"].items():
        L.append(f"| {k} | {_f(v)} |")
    L.append(f"| fitted weights, leave-one-out | {_f(result['loo_spearman_fitted'])} |")
    fw = result["fitted_weights"]
    if fw:
        tot = sum(fw.values()) or 1
        L += ["", "**P4: fitted (correlation-proportional) weights**: "
              + ", ".join(f"{k} {v / tot:.2f}" for k, v in fw.items())]
    fc = result["forecast"]
    if fc:
        L += ["", f"**P2: forecast (leave-one-out)** MAE {fc['mae']:.3f} "
                  f"(constant baseline {fc['mae_constant_baseline']:.3f}); 80% interval coverage "
                  f"{fc['coverage_80']:.0%}; ρ {_f(fc['spearman_forecast'])}. Drift sd {result['drift_sd']:.3f}."]
    L += ["", f"**S2**: final score std {_f(result['final_std'], 1)}; share of niches at 0/100 per component: "
          + ", ".join(f"{k} {v:.0%}" for k, v in result["saturation"].items() if v is not None)]
    L += [f"**S3**: niches with ≥30 videos in the base sample: {_f(result['sample_adequacy'] and result['sample_adequacy'] * 100, 0)}%"]
    L += [f"**D1**: short_unverified videos: {result['short_unverified']}; "
          f"**D2**: kept videos with mostly non-Latin titles: {_f(result['non_latin_share'] and result['non_latin_share'] * 100, 1)}%"]
    L += [f"**D4**: paid-promotion flagged channels: {', '.join(result['promo_flagged']) or 'none'}"]
    sb = result["suggested_bands"]
    L += ["", "**Suggested bands (panel p10 → p90)**: " + "; ".join(
        f"{k} {_f(v[0], 1)} → {_f(v[1], 1)}" for k, v in sb.items()),
        f"**Panel mean outcome hit rate (prior)**: {_f(result['prior_hit_rate'], 3)}"]
    return "\n".join(L)
