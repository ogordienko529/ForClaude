"""The few Telegram Bot API calls the channel bot needs. The token lives only in the URL of each request and is
cut out of every error message, so it never reaches a log."""

from __future__ import annotations

from typing import Any

import httpx


class TelegramError(RuntimeError):
    pass


class Telegram:
    def __init__(self, token: str, http: httpx.Client | None = None):
        if not token:
            raise TelegramError("TELEGRAM_BOT_TOKEN is not set")
        self._token = token
        self._http = http or httpx.Client(timeout=30)

    def _redact(self, text: str) -> str:
        return text.replace(self._token, "<token>")

    def call(self, method: str, **params: Any) -> Any:
        try:
            r = self._http.post(f"https://api.telegram.org/bot{self._token}/{method}", json=params)
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise TelegramError(self._redact(f"{method}: {type(e).__name__}: {e}")) from None
        if not data.get("ok"):
            raise TelegramError(self._redact(f"{method}: {data.get('description', 'error')}"))
        return data["result"]
