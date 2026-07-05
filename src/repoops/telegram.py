"""Minimal Telegram Bot API transport.

Pure HTTP boundary: knows how to POST a text message to the Telegram Bot API
and nothing about repoops config, snapshots, or reports. Stdlib-only so the
notification path never grows a third-party HTTP dependency.
"""

import json
import urllib.error
import urllib.request

API_BASE = "https://api.telegram.org"
_ERROR_DETAIL_LIMIT = 200


class TelegramError(RuntimeError):
    """Raised when a Telegram API call fails. Never carries the bot token or URL."""


def send_message(*, bot_token: str, chat_id: str, text: str, timeout: float = 10.0) -> None:
    """Send a plain-text message via the Telegram Bot API `sendMessage` method.

    Raises `TelegramError` with a sanitized, bounded message on any failure —
    never the request URL (which embeds `bot_token`) or raw exception text.
    """
    url = f"{API_BASE}/bot{bot_token}/sendMessage"
    payload = json.dumps(
        {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    ).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            status = response.status
    except urllib.error.HTTPError as exc:
        raise TelegramError(f"Telegram API returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        # Covers connection failures and timeouts alike — urlopen wraps both
        # (including socket timeouts) in URLError, never raises TimeoutError bare.
        reason = str(exc.reason)[:_ERROR_DETAIL_LIMIT]
        raise TelegramError(f"Telegram request failed: {reason}") from exc

    if status != 200:
        raise TelegramError(f"Telegram API returned unexpected status {status}")
