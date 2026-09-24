"""CLI: python -m niche_core <command> ...

Every paid command prints its quota estimate first. In an interactive terminal it asks
for confirmation unless --yes is given; --dry-run prints the estimate and exits.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .config import ConfigError, load_config
from .enrich import OUTLIER_METRICS
from .service import FORMATS, NicheService, QuotaBudgetError
from .youtube_client import MissingAPIKeyError, YouTubeAPIError


def _add_search_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("query")
    p.add_argument("--format", "-f", choices=FORMATS, default="both")
    p.add_argument("--region", dest="region_code", default=None, help="regionCode, default from config (US)")
    p.add_argument("--lang", dest="relevance_language", default=None, help="relevanceLanguage, default from config (en)")


def _add_budget_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--dry-run", action="store_true", help="only print the quota estimate")
    p.add_argument("--max-units", type=int, default=None, help="refuse to run if the estimate exceeds this")
    p.add_argument("--yes", "-y", action="store_true", help="don't ask for confirmation")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="niche_core", description="YouTube niche research")
    parser.add_argument("--config", default=None, help="path to config.toml")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("search", help="search_niche: recent videos for a query")
    _add_search_args(p)
    p.add_argument("--days", type=int, default=None, help="published within N days (default 30)")
    p.add_argument("--max-results", type=int, default=None, help="per duration bucket (default 50)")
    p.add_argument("--order", default="viewCount", choices=["viewCount", "date", "relevance", "rating"])
    _add_budget_args(p)

    p = sub.add_parser("outliers", help="find_outliers: small-channel videos far above their channel's size")
    _add_search_args(p)
    p.add_argument("--min-score", type=float, default=10, help="minimum outlier score (default 10)")
    p.add_argument("--max-subs", type=int, default=None, help="max channel subscribers (default 50000)")
    p.add_argument("--metric", choices=OUTLIER_METRICS, default="subs",
                   help="which score must pass --min-score (default subs = views/subscribers)")
    p.add_argument("--days", type=int, default=None)
    p.add_argument("--max-results", type=int, default=None, help="per duration bucket (default 50)")
    p.add_argument("--limit", type=int, default=50, help="max outliers returned")
    p.add_argument("--table", action="store_true", help="print a readable table instead of JSON")
    _add_budget_args(p)

    p = sub.add_parser("analyze", help="analyze_niche: scored niche report")
    _add_search_args(p)
    p.add_argument("--days", type=int, default=None)
    p.add_argument("--max-results", type=int, default=None, help="per search (default 50)")
    p.add_argument("--export", action="store_true", help="also write the markdown report to reports/")
    p.add_argument("--json", action="store_true", help="print full JSON instead of the markdown summary")
    _add_budget_args(p)

    p = sub.add_parser("compare", help="compare_niches: ranked table of several niches")
    p.add_argument("queries", nargs="+", help="niche queries (quote multi-word ones)")
    p.add_argument("--format", "-f", choices=FORMATS, default="both")
    p.add_argument("--region", dest="region_code", default=None)
    p.add_argument("--lang", dest="relevance_language", default=None)
    p.add_argument("--days", type=int, default=None)
    p.add_argument("--max-results", type=int, default=None)
    p.add_argument("--export", action="store_true")
    p.add_argument("--json", action="store_true")
    _add_budget_args(p)

    p = sub.add_parser("expand", help="expand_keywords: sub-niche queries from outlier titles/tags")
    p.add_argument("seed")
    p.add_argument("--format", "-f", choices=FORMATS, default="both")
    p.add_argument("--region", dest="region_code", default=None)
    p.add_argument("--lang", dest="relevance_language", default=None)
    p.add_argument("--max-suggestions", type=int, default=15)
    p.add_argument("--json", action="store_true")
    _add_budget_args(p)

    p = sub.add_parser("backtest", help="temporal backtest + calibration report (see docs/QUALITY_CRITERIA.md)")
    p.add_argument("--format", "-f", choices=["shorts", "long"], required=True)
    p.add_argument("--queries", nargs="*", default=None, help="default: calibration/panel.toml")
    p.add_argument("--set", dest="panel_set", choices=["design", "holdout", "all"], default="design",
                   help="panel list: design (used to build the scoring), holdout (test only), or all")
    p.add_argument("--panel", default="calibration/panel.toml")
    p.add_argument("--collect", action="store_true", help="fetch missing data from the API (costs quota)")
    p.add_argument("--prior-strength", type=float, default=None)
    _add_budget_args(p)

    p = sub.add_parser("channels", help="get_channel_stats for channel IDs")
    p.add_argument("channel_ids", nargs="+")
    _add_budget_args(p)

    sub.add_parser("quota", help="quota_status: units used today and remaining")
    sub.add_parser("purge", help="delete cached API data older than retention_days (max 30)")
    return parser


def _confirm(estimate: int, assume_yes: bool) -> bool:
    print(f"Estimated quota cost: {estimate} units (upper bound).", file=sys.stderr)
    if assume_yes or estimate == 0 or not sys.stdin.isatty():
        return True
    return input("Proceed? [y/N] ").strip().lower() in ("y", "yes")


def _run_paid(fn, kwargs: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    preview = fn(**kwargs, dry_run=True)
    if args.dry_run:
        return preview
    if not _confirm(preview["quota"]["estimated"], args.yes):
        return {"cancelled": True, "quota": preview["quota"]}
    return fn(**kwargs, max_units=args.max_units)


def _fmt_num(x) -> str:
    if x is None:
        return "?"
    x = float(x)
    for unit, div in (("M", 1e6), ("k", 1e3)):
        if abs(x) >= div:
            return f"{x / div:.1f}{unit}"
    return f"{x:.0f}"


def outliers_table(out: dict[str, Any]) -> str:
    lines = [
        f"find_outliers '{out['query']}' [{out['format']}]  scanned={out['scanned']}  outliers={out['count']}",
        f"rejected={out['rejected']}  excluded={out['excluded']}",
        f"summary={out['summary']}",
        "",
        f"{'views':>7} {'subs':>6} {'x subs':>7} {'x chan':>6} {'age':>5} {'new':>3}  {'channel':<22} title",
    ]
    for o in out["outliers"]:
        lines.append(
            f"{_fmt_num(o['views']):>7} {_fmt_num(o['channel_subs']):>6} "
            f"{_fmt_num(o['sub_outlier_score']):>7} {_fmt_num(o['channel_relative_score']):>6} "
            f"{o['age_days'] or 0:>4.0f}d {'Y' if o['is_new_channel'] else '':>3}  "
            f"{o['channel_title'][:22]:<22} {o['title'][:70]}"
        )
    return "\n".join(lines)


def _backtest(svc: NicheService, args: argparse.Namespace) -> int:
    import tomllib

    from .backtest import collect_case, estimate_case
    from .calibrate import analyse, render

    queries = args.queries
    if not queries:
        with open(args.panel, "rb") as fh:
            panel = tomllib.load(fh)
        design, holdout = panel.get(args.format, []), panel.get(f"{args.format}_holdout", [])
        queries = {"design": design, "holdout": holdout, "all": design + holdout}[args.panel_set]
    if args.collect:
        est = sum(estimate_case(svc, q, args.format) for q in queries)
        if args.dry_run:
            print(f"Estimated quota cost to collect {len(queries)} niches: {est} units", file=sys.stderr)
            return 0
        if args.max_units is not None and est > args.max_units:
            print(f"error: estimate {est} > max_units {args.max_units}", file=sys.stderr)
            return 2
        if not _confirm(est, args.yes):
            return 1
    else:
        svc.offline = True
    start = svc.quota.session_units
    cases = []
    for q in queries:
        try:
            case = collect_case(svc, q, args.format)
        except YouTubeAPIError as exc:  # quota ran out mid-panel: evaluate what we have
            print(f"stopped at {q!r}: {exc}", file=sys.stderr)
            break
        cases.append(case)
        print(f"  {q}: pool {len(case.pool)}, sample {len(case.sample)}, target {len(case.target)}"
              + (f"  [{'; '.join(case.errors)}]" if case.errors else ""), file=sys.stderr)
    params = svc.scoring_params(args.format)
    if args.prior_strength:
        params.prior_strength = args.prior_strength
    print(render(analyse(cases, params), params))
    print(f"\nQuota spent: {svc.quota.session_units - start}; used today {svc.quota.used_today()}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        svc = NicheService(load_config(args.config))
        if args.command == "search":
            out = _run_paid(
                svc.search_niche,
                dict(
                    query=args.query,
                    format=args.format,
                    published_within_days=args.days,
                    max_results=args.max_results,
                    region_code=args.region_code,
                    relevance_language=args.relevance_language,
                    order=args.order,
                ),
                args,
            )
        elif args.command == "outliers":
            out = _run_paid(
                svc.find_outliers,
                dict(
                    query=args.query,
                    format=args.format,
                    min_outlier_score=args.min_score,
                    max_channel_subs=args.max_subs,
                    metric=args.metric,
                    published_within_days=args.days,
                    max_results=args.max_results,
                    region_code=args.region_code,
                    relevance_language=args.relevance_language,
                    limit=args.limit,
                ),
                args,
            )
        elif args.command == "analyze":
            out = _run_paid(
                svc.analyze_niche,
                dict(
                    query=args.query,
                    format=args.format,
                    published_within_days=args.days,
                    max_results=args.max_results,
                    region_code=args.region_code,
                    relevance_language=args.relevance_language,
                    export=args.export,
                ),
                args,
            )
        elif args.command == "compare":
            out = _run_paid(
                svc.compare_niches,
                dict(
                    queries=args.queries,
                    format=args.format,
                    published_within_days=args.days,
                    max_results=args.max_results,
                    region_code=args.region_code,
                    relevance_language=args.relevance_language,
                    export=args.export,
                ),
                args,
            )
        elif args.command == "expand":
            out = _run_paid(
                svc.expand_keywords,
                dict(
                    seed=args.seed,
                    format=args.format,
                    max_suggestions=args.max_suggestions,
                    region_code=args.region_code,
                    relevance_language=args.relevance_language,
                ),
                args,
            )
        elif args.command == "backtest":
            return _backtest(svc, args)
        elif args.command == "channels":
            out = _run_paid(svc.get_channel_stats, dict(channel_ids=args.channel_ids), args)
        elif args.command == "quota":
            out = svc.quota_status()
        elif args.command == "purge":
            out = svc.purge()
        else:  # pragma: no cover
            raise SystemExit(f"unknown command {args.command}")
    except (MissingAPIKeyError, QuotaBudgetError, ConfigError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except YouTubeAPIError as exc:
        print(f"YouTube API error: {exc}", file=sys.stderr)
        return 1
    if args.command == "compare" and not args.json and "table_markdown" in out:
        print(out["table_markdown"])
        if out.get("exported_to"):
            print(f"\nExported to {out['exported_to']}", file=sys.stderr)
    elif args.command == "expand" and not args.json and "suggestions" in out:
        print(f"Sub-niches for '{out['seed']}' ({out['based_on']['outlier_videos']} outlier videos, "
              f"{out['based_on']['channels']} channels):")
        for s in out["suggestions"]:
            print(f"  {s['score']:>6.1f}  {s['query']:<40} channels={s['channels']:<3} {'/'.join(s['sources']):<9} "
                  f"e.g. {s['example_titles'][0][:60]}")
    elif args.command == "analyze" and not args.json and "summary_markdown" in out:
        print(out["summary_markdown"])
        if out.get("exported_to"):
            print(f"\nExported to {out['exported_to']}", file=sys.stderr)
    elif getattr(args, "table", False) and "outliers" in out:
        print(outliers_table(out))
    else:
        print(json.dumps(out, indent=2, ensure_ascii=False))
    if out.get("quota"):
        q = out["quota"]
        print(
            f"Quota: estimated {q['estimated']}, actual {q['actual']}, "
            f"used today {q['used_today']}/{q['daily_limit']}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
