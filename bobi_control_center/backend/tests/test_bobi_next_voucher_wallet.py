from __future__ import annotations

import json

import httpx
import pytest

from app.bobi_next.supabase_storage import BobiStorageClient, BobiStorageError
from app.bobi_next.voucher_wallet import VoucherWallet

_TOKEN = "t" * 32
_ENDPOINT = "https://example.supabase.co/functions/v1/bobi-storage"


def _client(handler) -> BobiStorageClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    return BobiStorageClient(_ENDPOINT, _TOKEN, client=http)


def test_storage_client_rejects_insecure_remote_endpoint() -> None:
    with pytest.raises(ValueError, match="storage_endpoint_https_required"):
        BobiStorageClient("http://example.com/functions/v1/bobi-storage", _TOKEN)


@pytest.mark.asyncio
async def test_storage_client_sends_only_narrow_edge_contract() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["token"] = request.headers.get("x-bobi-token")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "service": "bobi-storage"})

    storage = _client(handler)
    result = await storage.ping()

    assert result["service"] == "bobi-storage"
    assert seen["url"] == _ENDPOINT
    assert seen["token"] == _TOKEN
    assert seen["body"] == {"op": "ping", "external_id": "", "payload": {}}
    await storage._injected_client.aclose()


@pytest.mark.asyncio
async def test_storage_client_does_not_follow_redirects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(307, headers={"location": "https://evil.example/collect"})

    storage = _client(handler)
    with pytest.raises(BobiStorageError, match="storage_redirect_rejected"):
        await storage.ping()
    await storage._injected_client.aclose()


@pytest.mark.asyncio
async def test_voucher_wallet_maps_list_and_hides_code_by_default() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["op"] == "voucher.list"
        assert body["external_id"] == "profile-1"
        return httpx.Response(
            200,
            json={
                "ok": True,
                "items": [
                    {
                        "id": "v1",
                        "name": "Gift",
                        "merchant": "Shop",
                        "amount": "100.50",
                        "remaining_amount": "75.25",
                        "currency": "ILS",
                        "status": "active",
                        "metadata": {"source": "test"},
                    }
                ],
            },
        )

    storage = _client(handler)
    wallet = VoucherWallet(storage, profile_external_id="profile-1")
    items = await wallet.list()

    assert len(items) == 1
    assert str(items[0].amount) == "100.50"
    assert str(items[0].remaining_amount) == "75.25"
    assert items[0].metadata == {"source": "test"}
    await storage._injected_client.aclose()


@pytest.mark.asyncio
async def test_voucher_media_upload_validates_signature_before_network() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, json={"ok": False})

    storage = _client(handler)
    wallet = VoucherWallet(storage, profile_external_id="profile-1")

    with pytest.raises(ValueError, match="voucher_media_signature_mismatch"):
        await wallet.upload_media(
            "v1",
            b"not a pdf",
            filename="voucher.pdf",
            content_type="application/pdf",
        )

    assert calls == 0
    await storage._injected_client.aclose()


@pytest.mark.asyncio
async def test_voucher_media_upload_uses_pdf_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["op"] == "voucher.media.upload"
        assert body["payload"]["voucher_id"] == "v1"
        assert body["payload"]["mime_type"] == "application/pdf"
        assert body["payload"]["media_base64"].startswith("JVBERi0")
        return httpx.Response(
            200,
            json={
                "ok": True,
                "media": {
                    "id": "m1",
                    "voucher_id": "v1",
                    "original_filename": "voucher.pdf",
                    "content_type": "application/pdf",
                    "size_bytes": 14,
                    "sha256": "abc",
                    "status": "active",
                    "storage_uri": "storage://bobi-vouchers/p/v/file.pdf",
                },
            },
        )

    storage = _client(handler)
    wallet = VoucherWallet(storage, profile_external_id="profile-1")
    media = await wallet.upload_media(
        "v1",
        b"%PDF-1.7\nhello",
        filename="voucher.pdf",
        content_type="application/pdf",
    )

    assert media.media_id == "m1"
    assert media.content_type == "application/pdf"
    await storage._injected_client.aclose()


@pytest.mark.asyncio
async def test_signed_url_is_short_lived_and_must_be_https() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["payload"]["expires_in"] == 900
        return httpx.Response(
            200,
            json={
                "ok": True,
                "media_id": "m1",
                "signed_url": "https://example.supabase.co/storage/v1/object/sign/private",
                "expires_in": 900,
            },
        )

    storage = _client(handler)
    wallet = VoucherWallet(storage, profile_external_id="profile-1")
    url = await wallet.signed_url(media_id="m1", expires_in=5000)

    assert url.startswith("https://example.supabase.co/")
    await storage._injected_client.aclose()


@pytest.mark.asyncio
async def test_storage_error_does_not_echo_server_detail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="sensitive internal detail")

    storage = _client(handler)
    with pytest.raises(BobiStorageError) as exc:
        await storage.ping()
    assert str(exc.value) == "storage_unavailable"
    assert "sensitive" not in str(exc.value)
    await storage._injected_client.aclose()
