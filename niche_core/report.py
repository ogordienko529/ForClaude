"""Report building: descriptive insights, markdown rendering and export to reports/."""

from __future__ import annotations

import re
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

from .durations import format_seconds
from .enrich import EnrichedVideo
from .patterns import title_patterns, top_ngrams
from .scoring import ScoringParams, is_small, suspected_paid_promotion, unique

COMPONENT_LABELS = {
    "opportunity": "Opportunity",
    "new_channel_proof": "New-channel proof",
    "velocity": "Velocity",
    "consistency": "Consistency",
    "competition": "Competition",
    "monetization": "Monetization (ESTIMATE)",
}


def _quantiles(values: list[float]) -> dict[str, float] | None:
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    if len(values) == 1:
        return {"p25": values[0], "median": values[0], "p75": values[0]}
    q = statistics.quantiles(values, n=4, method="inclusive")
    return {"p25": q[0], "median": statistics.median(values), "p75": q[2]}


def build_insights(pool: list[EnrichedVideo], sample: list[EnrichedVideo], query: str,
                   p: ScoringParams) -> dict[str, Any]:
    everything = unique(pool + sample)
    small = [e for e in everything if is_small(e, p) and not suspected_paid_promotion(e, p)]
    hits = [e for e in small if e.is_hit]
    hit_ids = {e.video.video_id for e in hits}
    others = [e for e in everything if e.video.video_id not in hit_ids]

    # Only videos that actually reached the hit threshold: a 5-sub channel with 1k views is noise.
    candidates = hits or small
    top = sorted(candidates, key=lambda e: (e.primary_score or 0, e.video.view_count or 0), reverse=True)[:10]
    top_outliers = [
        {
            "title": e.video.title,
            "channel": e.video.channel_title,
            "subs": e.subs,
            "views": e.video.view_count,
            "outlier_score": round(e.primary_score, 1) if e.primary_score is not None else None,
            "outlier_metric": e.primary_metric,
            "sub_outlier_score": round(e.sub_outlier_score, 1) if e.sub_outlier_score is not None else None,
            "channel_relative_score": round(e.channel_relative_score, 1) if e.channel_relative_score is not None else None,
            "age_days": round(e.age_days, 1) if e.age_days is not None else None,
            "new_channel": e.is_new_channel,
            "duration": format_seconds(e.video.duration_s),
            "url": e.video.url,
        }
        for e in top
    ]

    basis = hits or small or everything
    durations = _quantiles([e.video.duration_s for e in basis])
    ages = [e.age_days for e in hits if e.age_days is not None]
    query_words = re.findall(r"\w+", query.lower())
    return {
        "top_outliers": top_outliers,
        "title_patterns": title_patterns([e.video.title for e in hits], [e.video.title for e in others]),
        "common_phrases": [{"phrase": g, "count": c} for g, c in
                           top_ngrams([e.video.title for e in hits or small], exclude=query_words, top=12)],
        "typical_length": {
            "basis": "small-channel hits" if hits else ("small-channel videos" if small else "all videos"),
            **({k: format_seconds(v) for k, v in durations.items()} if durations else {}),
            "median_seconds": round(durations["median"]) if durations else None,
        },
        "posting_recency": {
            "hits": len(hits),
            "median_hit_age_days": round(statistics.median(ages), 1) if ages else None,
            "hits_in_last_7_days": sum(1 for a in ages if a <= 7),
            "hits_within_14_days_of_upload": sum(1 for e in hits if e.hit_within_14d),
            "newest_hit_age_days": round(min(ages), 1) if ages else None,
        },
        "sample_sizes": {
            "view_ordered_results": len(pool),
            "date_ordered_sample": len(sample),
            "unique_videos": len(everything),
            "small_channel_videos": len(small),
        },
    }


# ---------------------------------------------------------------- markdown
def _num(x: Any) -> str:
    if x is None:
        return "?"
    x = float(x)
    for unit, div in (("M", 1e6), ("k", 1e3)):
        if abs(x) >= div:
            return f"{x / div:.1f}{unit}"
    return f"{x:.0f}"


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_format_section(fmt: str, r: dict[str, Any]) -> list[str]:
    lines = [f"### {fmt.capitalize()}: {r['final_score']:.0f}/100" + ("  ⚠️ LOW CONFIDENCE" if r["low_confidence"] else "")]
    for flag in r["confidence_flags"]:
        lines.append(f"- ⚠️ {flag}")
    lines += ["", "| Component | Score | Weight | Why |", "|---|---:|---:|---|"]
    for name, c in r["components"].items():
        lines.append(f"| {COMPONENT_LABELS.get(name, name)} | {c['score']:.0f} | {c['weight']:.2f} | "
                     f"{_md_escape(c['explanation'])} |")
    if r.get("suspected_paid_promotion_excluded"):
        lines.append(f"\n_{r['suspected_paid_promotion_excluded']} video(s) from channels that look like paid "
                     f"promotion were excluded from scoring._")

    lines += ["", "**Top outliers (small channels)**", "",
              "| # | Title | Channel | Subs | Views | Outlier | Age | Link |", "|---:|---|---|---:|---:|---:|---:|---|"]
    for i, o in enumerate(r["top_outliers"], 1):
        metric = "×avg" if o["outlier_metric"] == "channel_relative" else "×subs"
        new = " 🆕" if o["new_channel"] else ""
        lines.append(
            f"| {i} | {_md_escape(o['title'][:80])} | {_md_escape(o['channel'])}{new} | {_num(o['subs'])} | "
            f"{_num(o['views'])} | {o['outlier_score'] or 0:.1f}{metric} | {o['age_days'] or 0:.0f}d | [▶]({o['url']}) |"
        )
    tl, rec = r["typical_length"], r["posting_recency"]
    lines += ["", f"**Typical length** ({tl['basis']}): median {tl.get('median', '?')} "
                  f"(middle half {tl.get('p25', '?')}–{tl.get('p75', '?')})",
              f"**Recency**: {rec['hits']} small-channel hits, median age {rec['median_hit_age_days']} days, "
              f"{rec['hits_in_last_7_days']} in the last 7 days, {rec['hits_within_14_days_of_upload']} "
              f"reached the threshold while ≤14 days old."]
    if r["title_patterns"]:
        pats = ", ".join(
            f"{t['pattern']} ({t['hit_share']:.0%}" + (f", ×{t['lift']:.1f} vs others)" if t["lift"] else ")")
            for t in r["title_patterns"][:6]
        )
        lines.append(f"**Title patterns in hits**: {pats}")
    if r["common_phrases"]:
        lines.append("**Common phrases**: " + ", ".join(f"{p['phrase']} ({p['count']})" for p in r["common_phrases"][:10]))
    m = r["components"]["monetization"]["raw"]
    lines.append(f"**Monetization (ESTIMATE, not data)**: {m['tier']} tier, ~{m['rpm_range_usd']} RPM; {m['basis']}.")
    return lines


def render_analysis_markdown(result: dict[str, Any]) -> str:
    q = result["quota"]
    lines = [
        f"## Niche report: “{result['query']}” [{result['format']}]",
        f"Final score **{result['final_score']:.0f}/100**"
        + (f" (best format: {result['best_format']})" if result["format"] == "both" else "")
        + f" · region {result['params']['region_code']} · language {result['params']['relevance_language']}"
        + f" · last {result['params']['published_within_days']} days",
        f"_Quota: estimated {q['estimated']}, actual {q['actual']}, used today {q['used_today']}/{q['daily_limit']}_",
        "",
    ]
    for fmt, r in result["formats"].items():
        lines += render_format_section(fmt, r) + [""]
    if result.get("errors"):
        lines.append("**Errors**: " + "; ".join(result["errors"]))
    return "\n".join(lines)


def render_compare_markdown(rows: list[dict[str, Any]], fmt: str) -> str:
    lines = [
        f"## Niche comparison [{fmt}]",
        "",
        "| # | Niche | Final | Best format | Opportunity | New-channel proof | Velocity | Consistency "
        "| Competition | Monetization (est.) | Confidence |",
        "|---:|---|---:|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for i, r in enumerate(rows, 1):
        if r.get("error"):
            lines.append(f"| {i} | {_md_escape(r['query'])} | – | – | – | – | – | – | – | – | error: {_md_escape(r['error'])} |")
            continue
        c = r["components"]
        conf = "⚠️ low" if r["low_confidence"] else "ok"
        lines.append(
            f"| {i} | {_md_escape(r['query'])} | **{r['final_score']:.0f}** | {r['best_format']} | "
            f"{c['opportunity']:.0f} | {c['new_channel_proof']:.0f} | {c['velocity']:.0f} | {c['consistency']:.0f} | "
            f"{c['competition']:.0f} | {c['monetization']:.0f} ({r['rpm_tier']}) | {conf} |"
        )
    lines += ["", "_Scores are 0–100; higher is better (Competition: higher = less dominated by 100k+ channels). "
                  "Monetization is an ESTIMATE, not data._"]
    return "\n".join(lines)


def export_markdown(markdown: str, reports_dir: Path, name: str, now: datetime) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "report"
    path = reports_dir / f"{now:%Y%m%d-%H%M}-{slug}.md"
    path.write_text(markdown, encoding="utf-8")
    return path
