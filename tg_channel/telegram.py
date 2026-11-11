"""The few Telegram Bot API calls the channel bot needs. The token lives only in the URL of each request and is
cut out of every error message, so it never reaches a log."""

from __future__ import annotations

import json
from pathlib import Path
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
        return self._post(method, json={k: v for k, v in params.items() if v is not None})

    def upload(self, method: str, field: str, path: Path, **params: Any) -> Any:
        """A call with one file (e.g. setChatPhoto); the other parameters go as form fields."""
        form = {k: v if isinstance(v, str) else json.dumps(v) for k, v in params.items() if v is not None}
        with open(path, "rb") as f:
            return self._post(method, data=form, files={field: (Path(path).name, f.read())})

    def _post(self, method: str, **kwargs: Any) -> Any:
        try:
            r = self._http.post(f"https://api.telegram.org/bot{self._token}/{method}", **kwargs)
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise TelegramError(self._redact(f"{method}: {type(e).__name__}: {e}")) from None
        if not data.get("ok"):
            raise TelegramError(self._redact(f"{method}: {data.get('description', 'error')}"))
        return data["result"]
