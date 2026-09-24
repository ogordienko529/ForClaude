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
