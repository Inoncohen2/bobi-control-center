from __future__ import annotations

import httpx
import pytest

from app.bobi_next.messaging import InboundMessage
from app.bobi_next.waha_adapter import (
    WahaTransport,
    deterministic_waha_message_id,
    parse_waha_webhook,
)


def test_parse_waha_direct_message():
    parsed = parse_waha_webhook(
        {
            "event": "message",
            "session": "default",
            "payload": {
                "id": "false_972501234567@c.us_ABC",
                "timestamp": 1234,
                "from": "972501234567@c.us",
                "fromMe": False,
                "body": "hello",
                "hasMedia": False,
            },
        }
    )
    assert parsed is not None
    assert parsed.message_id == "false_972501234567@c.us_ABC"
    assert parsed.chat_id == "972501234567@c.us"
    assert parsed.sender_id == "972501234567@c.us"
    assert parsed.kind == "text"
    assert parsed.text == "hello"


def test_parse_waha_group_uses_participant_as_sender():
    parsed = parse_waha_webhook(
        {
            "event": "message",
            "session": "family",
            "payload": {
                "id": "false_group_ABC",
                "timestamp": 1234,
                "from": "120363000000000@g.us",
                "participant": "972501234567@s.whatsapp.net",
                "fromMe": False,
                "body": "turn off the light",
                "hasMedia": False,
            },
        }
    )
    assert parsed is not None
    assert parsed.chat_id == "120363000000000@g.us"
    assert parsed.sender_id == "972501234567@c.us"


def test_parse_waha_media_classifies_voice_and_keeps_metadata():
    parsed = parse_waha_webhook(
        {
            "event": "message",
            "session": "default",
            "payload": {
                "id": "false_1@c.us_MEDIA",
                "timestamp": 1234.9,
                "from": "1@c.us",
                "fromMe": False,
                "body": "",
                "hasMedia": True,
                "media": {
                    "url": "http://waha/api/files/x.ogg",
                    "mimetype": "audio/ogg; codecs=opus",
                    "filename": "voice.ogg",
                },
            },
        }
    )
    assert parsed is not None
    assert parsed.kind == "voice"
    assert parsed.media_url.endswith("x.ogg")
    assert parsed.media_filename == "voice.ogg"
    assert parsed.timestamp == 1234


def test_parse_waha_ignores_self_status_and_non_message_events():
    base = {
        "event": "message",
        "session": "default",
        "payload": {
            "id": "m1",
            "from": "1@c.us",
            "fromMe": True,
            "body": "own reply",
        },
    }
    assert parse_waha_webhook(base) is None

    status = {
        **base,
        "payload": {**base["payload"], "fromMe": False, "from": "status@broadcast"},
    }
    assert parse_waha_webhook(status) is None
    assert parse_waha_webhook({"event": "message.ack", "payload": {}}) is None


def test_deterministic_message_id_is_stable_and_compact():
    key = "abcdef0123456789" * 4
    first = deterministic_waha_message_id(key)
    second = deterministic_waha_message_id(key)
    assert first == second
    assert len(first) == 22
    assert first == "ABCDEF0123456789ABCDEF"


class RecordingHttpClient:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = list(responses or [])

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        data = self.responses.pop(0) if self.responses else {}
        request = httpx.Request(method, url)
        return httpx.Response(200, json=data, request=request)


def _inbound() -> InboundMessage:
    return InboundMessage(
        row_id=1,
        provider="waha",
        message_id="false_1@c.us_ABC",
        chat_id="1@c.us",
        user_key="u1",
        text="hello",
        kind="text",
        received_ts=1,
        state="running",
    )


@pytest.mark.asyncio
async def test_waha_transport_reaction_and_presence_contract():
    client = RecordingHttpClient()
    transport = WahaTransport(
        base_url="http://waha:3000",
        session="default",
        api_key="secret",
        engine="GOWS",
        client=client,
    )

    await transport.react(_inbound(), "💡")
    await transport.set_typing("1@c.us", True)
    await transport.set_typing("1@c.us", False)

    reaction = client.calls[0]
    assert reaction[0] == "PUT"
    assert reaction[1].endswith("/api/reaction")
    assert reaction[2]["json"] == {
        "session": "default",
        "messageId": "false_1@c.us_ABC",
        "reaction": "💡",
    }
    assert reaction[2]["headers"]["X-Api-Key"] == "secret"

    assert client.calls[1][2]["json"]["presence"] == "typing"
    assert client.calls[2][2]["json"]["presence"] == "paused"
    assert client.calls[1][1].endswith("/api/default/presence")


@pytest.mark.asyncio
async def test_gows_send_text_uses_reply_and_deterministic_custom_id():
    client = RecordingHttpClient([{"id": "true_1@c.us_PROVIDER"}])
    transport = WahaTransport(
        base_url="http://waha:3000",
        session="default",
        engine="GOWS",
        client=client,
    )
    key = "0123456789abcdef" * 4
    provider_id = await transport.send_text(
        "1@c.us",
        "done",
        reply_to="false_1@c.us_ABC",
        idempotency_key=key,
    )

    body = client.calls[0][2]["json"]
    assert body["session"] == "default"
    assert body["chatId"] == "1@c.us"
    assert body["text"] == "done"
    assert body["reply_to"] == "false_1@c.us_ABC"
    assert body["id"] == deterministic_waha_message_id(key)
    assert provider_id == "true_1@c.us_PROVIDER"


@pytest.mark.asyncio
async def test_webjs_does_not_send_custom_message_id():
    client = RecordingHttpClient([{}])
    transport = WahaTransport(
        base_url="http://waha:3000",
        session="default",
        engine="WEBJS",
        client=client,
    )
    key = "0123456789abcdef" * 4
    provider_id = await transport.send_text(
        "1@c.us",
        "done",
        reply_to="false_1@c.us_ABC",
        idempotency_key=key,
    )

    body = client.calls[0][2]["json"]
    assert "id" not in body
    assert provider_id == deterministic_waha_message_id(key)
