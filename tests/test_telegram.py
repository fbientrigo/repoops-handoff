import json
import urllib.error
import urllib.request

import pytest

from repoops import telegram


class _FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


def test_send_message_success(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: urllib.request.Request, timeout: float) -> _FakeResponse:
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeResponse(200)

    monkeypatch.setattr(telegram.urllib.request, "urlopen", fake_urlopen)

    telegram.send_message(bot_token="TOKEN123", chat_id="42", text="hello", timeout=5.0)

    assert captured["url"] == "https://api.telegram.org/botTOKEN123/sendMessage"
    assert captured["body"] == {
        "chat_id": "42",
        "text": "hello",
        "disable_web_page_preview": True,
    }
    assert captured["timeout"] == 5.0


def test_send_message_http_error_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: urllib.request.Request, timeout: float) -> _FakeResponse:
        raise urllib.error.HTTPError(
            "https://api.telegram.org/botSECRET/sendMessage", 401, "Unauthorized", None, None
        )

    monkeypatch.setattr(telegram.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(telegram.TelegramError) as exc_info:
        telegram.send_message(bot_token="SECRET", chat_id="42", text="hello")

    assert "SECRET" not in str(exc_info.value)
    assert "401" in str(exc_info.value)


def test_send_message_url_error_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: urllib.request.Request, timeout: float) -> _FakeResponse:
        raise urllib.error.URLError("Name or service not known")

    monkeypatch.setattr(telegram.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(telegram.TelegramError) as exc_info:
        telegram.send_message(bot_token="SECRET", chat_id="42", text="hello")

    assert "SECRET" not in str(exc_info.value)
    assert "botSECRET" not in str(exc_info.value)


def test_send_message_unexpected_status_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: urllib.request.Request, timeout: float) -> _FakeResponse:
        return _FakeResponse(500)

    monkeypatch.setattr(telegram.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(telegram.TelegramError):
        telegram.send_message(bot_token="TOKEN", chat_id="42", text="hello")
