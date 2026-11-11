"""python -m tg_channel run | preview

run      one cycle (GitHub Actions calls it every 15 minutes). Reads TELEGRAM_BOT_TOKEN, TG_OWNER_CHAT_ID,
         TG_CHANNEL and TG_AUTO_PUBLISH ("1": post without asking) from the environment.
preview  print the posts for the giveaways active now; no Telegram, no token.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .bot import Bot, load_state, save_state
from .posts import new_post
from .sources import fetch_all
from .telegram import Telegram


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tg_channel", description="Telegram channel bot for free game giveaways")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="one cycle: buttons, new giveaways, drafts or posts, reminders, digest")
    run.add_argument("--state", default="state/state.json", help="the bot's memory (JSON)")
    sub.add_parser("preview", help="print the posts for the giveaways active now (no Telegram)")
    a = ap.parse_args(argv)
    now = datetime.now(timezone.utc)

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
    bot = Bot(Telegram(token), state, owner=int(owner) if owner.lstrip("-").isdigit() else None,
              channel=os.environ.get("TG_CHANNEL"), auto=os.environ.get("TG_AUTO_PUBLISH", "").strip() == "1",
              log=lambda m: print(m, file=sys.stderr))
    report = bot.run(now, fetch_all)
    save_state(path, state)
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
