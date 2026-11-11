"""python -m tg_channel run | queue | preview

run      one cycle (GitHub Actions calls it every 15 minutes). Reads TELEGRAM_BOT_TOKEN, TG_OWNER_CHAT_ID,
         TG_CHANNEL, TG_AUTO_PUBLISH ("1": giveaways go out without asking) and TG_GIVEAWAYS ("1": post free game
         giveaways too) from the environment. The channel's own posts come from tg_content/posts.
queue    check every post in tg_content/posts and list the ones still to go (with --state: minus the published
         ones). Exit code 1 when a post has a problem. --left prints only how many are left.
preview  print the posts for the giveaways active now; no Telegram, no token.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import feed
from .bot import Bot, load_state, save_state
from .posts import new_post
from .sources import fetch_all
from .telegram import Telegram


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tg_channel", description="Telegram channel bot: scheduled posts, giveaways")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="one cycle: buttons, the next scheduled post, giveaways")
    run.add_argument("--state", default="state/state.json", help="the bot's memory (JSON)")
    run.add_argument("--posts", default=str(feed.POSTS_DIR), help="folder with the channel's posts")
    q = sub.add_parser("queue", help="check the posts and list the ones still to go")
    q.add_argument("--posts", default=str(feed.POSTS_DIR))
    q.add_argument("--state", help="the bot's memory, to leave out the published posts")
    q.add_argument("--left", action="store_true", help="print only how many posts are left")
    sub.add_parser("preview", help="print the posts for the giveaways active now (no Telegram)")
    a = ap.parse_args(argv)
    now = datetime.now(timezone.utc)

    if a.cmd == "queue":
        return queue(Path(a.posts), Path(a.state) if a.state else None, a.left, now)

    if a.cmd == "preview":
        giveaways, errors = fetch_all(now)
        for e in errors:
            print(f"! {e}", file=sys.stderr)
        for g in giveaways:
            print(new_post(g), "\n" + "-" * 40)
        print(f"{len(giveaways)} giveaways", file=sys.stderr)
        return 0

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("TELEGRAM_BOT_TOKEN is not set: add it in GitHub, Settings > Secrets and variables > Actions",
              file=sys.stderr)
        return 1
    owner = os.environ.get("TG_OWNER_CHAT_ID", "").strip()
    path = Path(a.state)
    state = load_state(path)
    posts_dir = Path(a.posts)
    bot = Bot(Telegram(token), state, owner=int(owner) if owner.lstrip("-").isdigit() else None,
              channel=os.environ.get("TG_CHANNEL"), auto=os.environ.get("TG_AUTO_PUBLISH", "").strip() == "1",
              log=lambda m: print(m, file=sys.stderr), posts=feed.load(posts_dir),
              giveaways=os.environ.get("TG_GIVEAWAYS", "").strip() == "1", profile=read_profile(posts_dir.parent))
    report = bot.run(now, fetch_all)
    save_state(path, state)
    print(json.dumps(report, ensure_ascii=False))
    return 0


def read_profile(folder: Path) -> dict[str, str] | None:
    """tg_content/profile.json: {"title": ..., "description": ...}; the bot sets them on the channel."""
    try:
        data = json.loads((folder / "profile.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {k: str(data[k]) for k in ("title", "description") if data.get(k)} or None


def queue(folder: Path, state_path: Path | None, only_count: bool, now: datetime) -> int:
    posts = feed.load(folder)
    published = load_state(state_path)["feed"] if state_path else {}
    today = feed.kyiv_day(now)
    left = feed.ready(posts, published, today)
    if only_count:
        print(len([p for p in left if not p.date]))
        return 0
    bad = [p for p in posts if p.problems]
    for p in bad:
        print(f"✗ {p.id}: " + "; ".join(p.problems))
    for p in left:
        print(f"  {p.preview()}")
    for p in feed.stale(posts, published, today):
        print(f"  (stale, skipped) {p.preview()}")
    waiting = [p for p in posts if p.id not in published and p.date and p.date > today and not p.problems]
    for p in waiting:
        print(f"  (waits for {p.date}) {p.preview()}")
    profile = read_profile(folder.parent)
    if profile and any(len(profile.get(k, "")) > n for k, n in (("title", 128), ("description", 255))):
        print("✗ profile.json: title at most 128 characters, description at most 255")
        bad.append(None)
    print(f"{len(posts)} posts, {len(published)} published, {len(left)} to go "
          f"(≈ {feed.days_left(posts, published, today):.1f} days at {len(feed.SLOTS)} a day), {len(bad)} with problems",
          file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
