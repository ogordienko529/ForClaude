"""Telegram channel bot: free-to-keep game giveaways in Ukrainian, drafted for the owner's approval.

One run (`python -m tg_channel run`) reads the owner's button presses, fetches the giveaways (Epic Games Store,
GamerPower), sends a draft for every new one, publishes what the owner approved, adds "last day" reminders and a
Sunday digest. GitHub Actions runs it every 15 minutes (.github/workflows/tg-bot.yml); the bot's memory is a JSON
file kept on its own branch. Posts are built from templates: every name, price and date comes from the source data.
"""
