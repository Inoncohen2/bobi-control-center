from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.bobi_next.outbound_media import OutboundMediaPayload
from app.bobi_next.waha_outbound_media import WahaOutboundMediaTransport


@pytest.mark.asyncio
async def test_waha_send_file_uses_binary_schema_without_invented_id() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"id": "provider-file-message"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = WahaOutboundMediaTransport(
            base_url="http://waha.internal:3000",
            session="default",
            api_key="secret",
            client=client,
        )
        provider_id = await transport.send_file(
            "chat-1",
            OutboundMediaPayload(
                content=b"pdf-bytes",
                filename="policy.pdf",
                mime_type="application/pdf",
            ),
            caption="Your policy",
            reply_to="incoming-1",
        )

    assert provider_id == "provider-file-message"
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert request.url.path == "/api/sendFile"
    assert request.headers["x-api-key"] == "secret"
    body = json.loads(request.content)
    assert body["session"] == "default"
    assert body["chatId"] == "chat-1"
    assert body["caption"] == "Your policy"
    assert body["reply_to"] == "incoming-1"
    assert body["file"] == {
        "mimetype": "application/pdf",
        "filename": "policy.pdf",
        "data": base64.b64encode(b"pdf-bytes").decode("ascii"),
    }
    assert "id" not in body


@pytest.mark.asyncio
async def test_waha_send_file_requires_real_provider_message_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(201, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        transport = WahaOutboundMediaTransport(
            base_url="http://waha.internal:3000",
            session="default",
            client=client,
        )
        with pytest.raises(RuntimeError, match="waha_file_message_id_missing"):
            await transport.send_file(
                "chat-1",
                OutboundMediaPayload(
                    content=b"file",
                    filename="file.pdf",
                    mime_type="application/pdf",
                ),
                caption="",
                reply_to="",
            )


def test_waha_outbound_media_rejects_invalid_base_url() -> None:
    with pytest.raises(ValueError, match="invalid_waha_base_url"):
        WahaOutboundMediaTransport(base_url="waha.internal", session="default")
