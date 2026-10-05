from __future__ import annotations

import base64
import hashlib
import sqlite3

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.bobi_next.archive_configuration import archive_configuration_guard
from app.bobi_next.archive_store import ArchiveStore
from app.bobi_next.integration_api import create_integration_setup_router
from app.bobi_next.integration_runtime import IntegrationRuntimeError, RoutedArchiveStorage
from app.bobi_next.integration_store import IntegrationStore
from app.bobi_next.request_ledger import RequestLedger
from app.bobi_next.setup_store import SetupStore


def config(endpoint="https://example.supabase.co/functions/v1/bobi-archive-next", token="a" * 40):
    return {
        "integration_key": "archive",
        "integration_type": "bobi_archive",
        "display_name": "Archive",
        "endpoint": endpoint,
        "secret_value": token,
        "config": {"archive_enabled": True},
    }


def api(tmp_path):
    path = tmp_path / "bobi-next-setup.db"
    app = FastAPI()
    app.include_router(create_integration_setup_router(path))
    return TestClient(app)


def mode(tmp_path, value):
    setup = SetupStore(tmp_path / "bobi-next-setup.db")
    setup.update_settings({"archive_storage_mode": value})
    setup.close()


@pytest.mark.asyncio
async def test_provider_switch_keeps_both_local_and_cloud_reads_and_has_no_outage_fallback(
    tmp_path,
):
    client = api(tmp_path)
    assert client.post("/api/next/setup/integrations", json=config()).status_code == 200
    cloud_bytes = {}
    operations = []

    async def server(request):
        if request.method == "GET":
            return httpx.Response(200, content=cloud_bytes["saved"])
        import json

        body = json.loads(request.content)
        operations.append(body["op"])
        if body["op"] == "archive.media.upload":
            data = base64.b64decode(body["payload"]["media_base64"])
            cloud_bytes["saved"] = data
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "media": {
                        "id": "saved",
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "size_bytes": len(data),
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "ok": True,
                "signed_url": "https://example.supabase.co/storage/v1/object/sign/private/saved?token=temporary",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as cloud:
        storage = RoutedArchiveStorage(tmp_path, client=cloud)
        content = b"local insurance"
        local = await storage.upload(
            owner_key="u1",
            content=content,
            filename="a.pdf",
            mime_type="application/pdf",
            sha256=hashlib.sha256(content).hexdigest(),
            idempotency_key="local",
        )
        mode(tmp_path, "cloud")
        assert await storage.read(local.storage_uri, max_bytes=100) == content
        remote_content = b"cloud receipt"
        remote = await storage.upload(
            owner_key="u1",
            content=remote_content,
            filename="b.pdf",
            mime_type="application/pdf",
            sha256=hashlib.sha256(remote_content).hexdigest(),
            idempotency_key="cloud",
        )
        mode(tmp_path, "local")
        assert await storage.read(remote.storage_uri, max_bytes=100) == remote_content
        assert await storage.read(local.storage_uri, max_bytes=100) == content
        assert client.post("/api/next/setup/integrations/archive/enabled/false").status_code == 200
        with pytest.raises(IntegrationRuntimeError):
            await storage.read(remote.storage_uri, max_bytes=100)
        assert await storage.read(local.storage_uri, max_bytes=100) == content
        mode(tmp_path, "cloud")
        with pytest.raises(IntegrationRuntimeError):
            await storage.upload(
                owner_key="u1",
                content=b"new",
                filename="c.pdf",
                mime_type="application/pdf",
                sha256=hashlib.sha256(b"new").hexdigest(),
                idempotency_key="failed",
            )
        assert list((tmp_path / "bobi-next-archive-files").rglob("*.blob"))
        assert len(list((tmp_path / "bobi-next-archive-files").rglob("*.blob"))) == 1
        assert operations == ["archive.media.upload", "archive.media.signed_url"]


@pytest.mark.parametrize("trash", [False, True])
def test_changing_endpoint_requires_migration_when_cloud_objects_exist(tmp_path, trash):
    client = api(tmp_path)
    assert client.post("/api/next/setup/integrations", json=config()).status_code == 200
    index = ArchiveStore(tmp_path / "bobi-next-archive.db")
    item = index.register(
        owner_key="u1",
        kind="document",
        title="Private",
        storage_uri="bobi-storage://opaque-subject/immutable-object",
        now_ts=100,
    )
    if trash:
        index.soft_delete(item.object_id, owner_key="u1", now_ts=101)
    index.close()
    response = client.post(
        "/api/next/setup/integrations",
        json=config(
            "https://other.supabase.co/functions/v1/bobi-archive-next",
            "b" * 40,
        ),
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "archive_provider_change_requires_migration"
    assert "b" * 40 not in response.text
    assert (
        client.post("/api/next/setup/integrations", json=config(token="c" * 40)).status_code == 200
    )
    store = IntegrationStore(tmp_path / "bobi-next-setup.db")
    assert store.get("archive").endpoint == config()["endpoint"]
    store.close()


def test_active_save_blocks_provider_update_and_disable_even_after_lease_expiry(tmp_path):
    client = api(tmp_path)
    assert client.post("/api/next/setup/integrations", json=config()).status_code == 200
    requests = RequestLedger(tmp_path / "bobi-next-requests.db")
    requests.claim(
        request_id="archive-save:waha:current",
        user_key="u1",
        input_text="save",
        owner_token="worker",
        now_ts=100,
        lease_seconds=5,
    )
    update = client.post("/api/next/setup/integrations", json=config(token="b" * 40))
    assert update.status_code == 409 and update.json()["detail"] == "archive_save_in_progress"
    assert client.post("/api/next/setup/integrations/archive/enabled/false").status_code == 409
    requests.complete(
        "archive-save:waha:current",
        owner_token="worker",
        terminal_kind="archive_saved",
        now_ts=200,
    )
    assert (
        client.post("/api/next/setup/integrations", json=config(token="b" * 40)).status_code == 200
    )
    requests.close()


def test_configuration_write_lock_prevents_a_new_save_claim(tmp_path):
    path = tmp_path / "bobi-next-setup.db"
    requests = RequestLedger(tmp_path / "bobi-next-requests.db")
    requests._db.execute("PRAGMA busy_timeout=1")
    with archive_configuration_guard(path), pytest.raises(sqlite3.OperationalError, match="locked"):
        requests.claim(
            request_id="archive-save:waha:new", user_key="u1", input_text="save",
            owner_token="worker", now_ts=100,
        )
    assert requests.claim(
        request_id="archive-save:waha:new",
        user_key="u1",
        input_text="save",
        owner_token="worker",
        now_ts=100,
    ).claimed
    requests.close()
