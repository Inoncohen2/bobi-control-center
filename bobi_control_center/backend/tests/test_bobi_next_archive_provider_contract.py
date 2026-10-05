"""Real Python client against the production TypeScript handler on loopback.

The provider CI job requires this test. SQL is evaluated by embedded Postgres;
Supabase Storage HTTP is mocked. No live cloud or Home Assistant is involved.
"""

from __future__ import annotations

import hashlib
import json
import os
import select
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.bobi_next.archive_capture import ArchiveCaptureRequest, ArchiveCaptureService
from app.bobi_next.archive_store import ArchiveStore
from app.bobi_next.cloud_archive_storage import BobiCloudArchiveStorage
from app.bobi_next.integration_api import create_integration_setup_router
from app.bobi_next.integration_runtime import build_archive_storage
from app.bobi_next.media_pipeline import LoadedMedia, MediaDescriptor
from app.bobi_next.setup_store import SetupStore
from app.bobi_next.supabase_storage import BobiStorageClient, BobiStorageError

pytestmark = pytest.mark.skipif(
    os.environ.get("BOBI_ARCHIVE_PROVIDER_CONTRACT") != "1",
    reason="requires Node 22+ and the isolated Supabase test dependencies",
)


@pytest.fixture
def archive_endpoint(tmp_path):
    root = Path(__file__).resolve().parents[3]
    setup = SetupStore(tmp_path / "bobi-next-setup.db")
    installation = setup.installation_id()
    setup.update_settings({"archive_storage_mode": "cloud"})
    setup.close()
    with (tmp_path / "provider-test.log").open("w+") as log:
        process = subprocess.Popen(
            ["node", "--experimental-strip-types", "supabase/tests/contract-server.ts"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=log,
            text=True,
            env={**os.environ, "BOBI_ARCHIVE_TEST_INSTALLATION_ID": installation},
        )
        try:
            assert process.stdout is not None
            ready, _, _ = select.select([process.stdout], [], [], 30)
            assert ready, "isolated archive server did not start"
            line = process.stdout.readline()
            if not line:
                log.seek(0)
                pytest.fail(f"isolated archive server failed: {log.read()}")
            port = json.loads(line)["port"]
            yield f"http://127.0.0.1:{port}/functions/v1/bobi-archive-next"
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            if process.stdout is not None:
                process.stdout.close()


@pytest.mark.asyncio
async def test_capture_dedupe_and_signed_retrieval_with_actual_provider(
    archive_endpoint, tmp_path,
) -> None:
    content = b"%PDF-1.4\nprivate insurance contract\n%%EOF"
    digest = hashlib.sha256(content).hexdigest()
    media = LoadedMedia(
        MediaDescriptor("waha", "current-media", "document", "application/pdf", "insurance.pdf"),
        content,
        digest,
    )
    archive = ArchiveStore(tmp_path / "archive.db")
    try:
        app = FastAPI()
        app.include_router(create_integration_setup_router(tmp_path / "bobi-next-setup.db"))
        with TestClient(app) as setup_client:
            response = setup_client.post("/api/next/setup/integrations", json={
                "integration_key": "archive", "integration_type": "bobi_archive",
                "display_name": "Archive dev", "endpoint": archive_endpoint,
                "secret_value": "a" * 40, "config": {"archive_enabled": True},
            })
            assert response.status_code == 200
            assert "a" * 40 not in response.text
        async with httpx.AsyncClient(trust_env=False) as client:
            adapter = build_archive_storage(tmp_path, client=client)
            assert isinstance(adapter, BobiCloudArchiveStorage)
            assert adapter.storage.endpoint == archive_endpoint
            capture = ArchiveCaptureService(archive, adapter)
            request = ArchiveCaptureRequest("user-a", "document", "Insurance", category="insurance")
            record = await capture.capture(request, media=media)
            assert record.category == "insurance"
            assert record.storage_uri.startswith("bobi-storage://bobi2_")
            assert await adapter.read(record.storage_uri, max_bytes=1024) == content

            duplicate = await capture.capture(
                ArchiveCaptureRequest("user-a", "document", "Renamed", category="other"),
                media=media,
            )
            assert duplicate.object_id == record.object_id
            assert duplicate.category == "insurance"
            assert len(archive.search(owner_key="user-a", query="")) == 1
            assert archive.get(record.object_id, owner_key="user-b") is None

            other = await capture.capture(
                ArchiveCaptureRequest("user-b", "document", "Other insurance"), media=media,
            )
            assert other.storage_uri != record.storage_uri
            assert await adapter.read(other.storage_uri, max_bytes=1024) == content

            # A valid token for another installation cannot sign this object's
            # exact URI even if it knows both the opaque subject and media ID.
            foreign = BobiCloudArchiveStorage(
                BobiStorageClient(archive_endpoint, "b" * 40, client=client),
                installation_id="installation-b", client=client,
            )
            with pytest.raises(BobiStorageError):
                await foreign.read(record.storage_uri, max_bytes=1024)
    finally:
        archive.close()
