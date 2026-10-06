"""Real Python client against the archive TypeScript handler on loopback.

The provider CI job requires this test. SQL is evaluated by embedded Postgres;
Supabase Storage HTTP is mocked. No live cloud or Home Assistant is involved.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import select
import subprocess
import time
from dataclasses import replace
from functools import partial
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfWriter

import app.bobi_next.archive_messaging_runtime as archive_runtime_module
from app.bobi_next.archive_capture import ArchiveCaptureRequest, ArchiveCaptureService
from app.bobi_next.archive_messaging_runtime import ArchiveMessagingRuntime
from app.bobi_next.archive_setup_api import create_archive_setup_router
from app.bobi_next.archive_store import ArchiveStore
from app.bobi_next.cloud_archive_storage import BobiCloudArchiveStorage
from app.bobi_next.integration_api import create_integration_setup_router
from app.bobi_next.integration_runtime import build_archive_storage
from app.bobi_next.intent import SemanticIntent
from app.bobi_next.media_analyzers import MediaAnalyzerRegistry
from app.bobi_next.media_pipeline import LoadedMedia, MediaDescriptor
from app.bobi_next.messaging import process_next_message
from app.bobi_next.pending_approval import PendingApprovalStore
from app.bobi_next.setup_api import create_setup_router
from app.bobi_next.setup_store import SetupStore
from app.bobi_next.supabase_storage import BobiStorageClient, BobiStorageError
from app.bobi_next.waha_adapter import WahaMediaLoader, WahaTransport
from app.bobi_next.waha_ingest import ingest_waha_event
from app.bobi_next.waha_outbound_media import WahaOutboundMediaTransport

pytestmark = pytest.mark.skipif(
    os.environ.get("BOBI_ARCHIVE_PROVIDER_CONTRACT") != "1",
    reason="requires Node 22+ and the isolated Supabase test dependencies",
)


def _configure_archive(path, endpoint):
    app = FastAPI()
    app.include_router(create_setup_router(path))
    app.include_router(create_integration_setup_router(path))
    app.include_router(create_archive_setup_router(path))
    with TestClient(app) as client:
        response = client.post(
            "/api/next/setup/integrations",
            json={
                "integration_key": "archive",
                "integration_type": "bobi_archive",
                "display_name": "Archive dev",
                "endpoint": endpoint,
                "secret_value": "a" * 40,
                "config": {"archive_enabled": True},
            },
        )
        assert response.status_code == 200 and "a" * 40 not in response.text
        checked = client.post("/api/next/setup/archive/check")
        assert checked.status_code == 200 and checked.json()["cloud"]["ready"]
        assert checked.json()["cloud"]["check_fresh"]
        selected = client.put("/api/next/setup/archive", json={"mode": "cloud"})
        assert selected.status_code == 200 and selected.json()["ready"]
        return client.post(
            "/api/next/setup/providers",
            json={
                "provider_key": "waha",
                "provider_type": "waha",
                "display_name": "WhatsApp",
                "endpoint": "http://waha-fixture:3000",
                "session": "default",
                "engine": "GOWS",
                "secret_value": "waha-fixture-key",
            },
        ).json()


@pytest.fixture
def archive_endpoint(tmp_path, monkeypatch):
    # This contract is strictly loopback. The setup handshake creates its own
    # HTTP client, so inherited workstation proxies must not intercept it.
    for key in ("ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "http_proxy", "https_proxy"):
        monkeypatch.delenv(key, raising=False)
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
    archive_endpoint,
    tmp_path,
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
        _configure_archive(tmp_path / "bobi-next-setup.db", archive_endpoint)
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
                ArchiveCaptureRequest("user-b", "document", "Other insurance"),
                media=media,
            )
            assert other.storage_uri != record.storage_uri
            assert await adapter.read(other.storage_uri, max_bytes=1024) == content

            # A valid token for another installation cannot sign this object's
            # exact URI even if it knows both the opaque subject and media ID.
            foreign = BobiCloudArchiveStorage(
                BobiStorageClient(archive_endpoint, "b" * 40, client=client),
                installation_id="installation-b",
                client=client,
            )
            with pytest.raises(BobiStorageError):
                await foreign.read(record.storage_uri, max_bytes=1024)
    finally:
        archive.close()


class _NeverHA:
    async def get_state(self, entity_id):
        raise AssertionError("archive flow must not query Home Assistant")

    async def call_service(self, *args):
        raise AssertionError("archive flow must not mutate Home Assistant")


class _Understanding:
    def __init__(self):
        self.texts = []

    async def understand(self, text, *, context):
        self.texts.append(text)
        assert "/api/files/" not in text and "http://" not in text
        return SemanticIntent(
            raw_text=text,
            family="device_control",
            domain="switch",
            operation="off",
            target_text="missing target",
            confidence=0.99,
        )


class _WahaHTTP:
    def __init__(self):
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        buffer = io.BytesIO()
        writer.write(buffer)
        self.content = buffer.getvalue()
        self.requests = []
        self.replies = []
        self.files = []
        self.fail_reply_once = False

    async def request(self, request):
        self.requests.append(request)
        assert request.url.host == "waha-fixture"
        assert request.headers["x-api-key"] == "waha-fixture-key"
        if request.method == "GET":
            assert request.url.path == "/api/files/current.pdf"
            return httpx.Response(
                200, content=self.content, headers={"content-type": "application/pdf"}
            )
        body = json.loads(request.content)
        if request.url.path == "/api/sendText":
            if self.fail_reply_once:
                self.fail_reply_once = False
                return httpx.Response(503)
            self.replies.append(body)
        elif request.url.path == "/api/sendFile":
            self.files.append(body)
        return httpx.Response(200, json={"id": "provider-" + str(len(self.requests))})


class _WhatsAppFlow:
    """Actual ingest, durable queues, conversation and runtime; HTTP seams only."""

    def __init__(self, path, understanding, *, dry_run=False):
        self.path = path
        self.understanding = understanding
        self.dry_run = dry_run
        self.now = int(time.time())
        self.open()

    def open(self):
        self.setup = SetupStore(self.path / "bobi-next-setup.db")
        if self.setup.get_user("owner") is None:
            self.setup.create_user(display_name="Owner", role="owner", user_key="owner")
            self.setup.link_identity(provider_key="waha", external_id="111@c.us", user_key="owner")
        self.pending = PendingApprovalStore(self.path / "pending.db")

        async def policy(key):
            return self.setup.get_user(key).policy

        async def devices():
            return ()

        self.runtime = ArchiveMessagingRuntime(
            data_dir=self.path,
            setup=self.setup,
            ha=_NeverHA(),
            list_devices=devices,
            policy_for=policy,
            pending_approvals=self.pending,
            dry_run=self.dry_run,
        )
        self.boundary = self.runtime._waha_boundary(
            self.setup.get_provider("waha"),
            understanding=self.understanding,
            analyzers=MediaAnalyzerRegistry(),
        )
        self.runtime.boundaries["waha"] = self.boundary

    async def close(self):
        await self.runtime.aclose()
        self.pending.close()
        self.setup.close()

    def event(self, key, text, *, media=False, quoted=False):
        payload = {
            "id": key,
            "from": "111@c.us",
            "fromMe": False,
            "body": text,
            "timestamp": self.now,
            "hasMedia": media,
        }
        if media:
            payload["media"] = {
                "url": "https://untrusted-host/api/files/current.pdf",
                "mimetype": "application/pdf",
                "filename": "insurance.pdf",
            }
        if quoted:
            payload["replyTo"] = {
                "id": "old-document",
                "body": "שמור את זה",
                "hasMedia": True,
                "media": {
                    "url": "https://untrusted-host/api/files/quoted.pdf",
                    "mimetype": "application/pdf",
                    "filename": "quoted.pdf",
                },
            }
        return {"event": "message", "session": "default", "payload": payload}

    def ingest(self, event):
        return ingest_waha_event(
            event,
            provider_key="waha",
            setup=self.setup,
            messages=self.boundary.messages,
            now_ts=self.now,
        )

    async def process(self):
        self.now += 20
        return await process_next_message(
            self.boundary.messages,
            self.boundary.transport,
            self.boundary.handler,
            owner_token="contract-worker",
            now_ts=self.now,
            reaction_for=lambda message: "📄",
            reply_allowed=self.boundary.reply_allowed,
        )

    async def send(self, key, text, **kwargs):
        assert self.ingest(self.event(key, text, **kwargs)).accepted
        processed = await self.process()
        assert processed is not None and processed.state == "completed"


def _inject_waha_http(monkeypatch, client):
    # The production constructors and adapters remain real; only their HTTP
    # clients are injected. No WAHA server or user phone is contacted.
    monkeypatch.setattr(
        archive_runtime_module, "WahaMediaLoader", partial(WahaMediaLoader, client=client)
    )
    monkeypatch.setattr(
        archive_runtime_module, "WahaTransport", partial(WahaTransport, client=client)
    )


@pytest.mark.asyncio
async def test_whatsapp_cloud_archive_retry_restart_approval_and_delivery(
    archive_endpoint,
    tmp_path,
    monkeypatch,
):
    _configure_archive(tmp_path / "bobi-next-setup.db", archive_endpoint)
    waha = _WahaHTTP()
    understanding = _Understanding()
    async with httpx.AsyncClient(transport=httpx.MockTransport(waha.request)) as client:
        _inject_waha_http(monkeypatch, client)
        flow = _WhatsAppFlow(tmp_path, understanding)
        try:
            save = flow.event("save", "שמור את זה בתיקיית ביטוחים", media=True, quoted=True)
            assert flow.ingest(save).accepted
            waha.fail_reply_once = True
            assert (await flow.process()).state == "retry"
            saved = flow.runtime.archive.index.search(owner_key="owner", category="ביטוחים")
            assert len(saved) == 1 and saved[0].source_message_id == "save"
            assert saved[0].sha256 == hashlib.sha256(waha.content).hexdigest()
            assert saved[0].storage_uri.startswith("bobi-storage://")
            assert not (tmp_path / "bobi-next-archive-files").exists()
            await flow.close()
            flow.open()
            assert (await flow.process()).state == "completed"
            assert waha.replies[-1]["text"] == "✅ שמרתי את הקובץ בתיקיית ביטוחים."
            assert flow.ingest(save).duplicate
            assert len([r for r in waha.requests if r.method == "GET"]) == 1
            assert understanding.texts == []

            await flow.send("retrieve", "שלח לי את המסמך insurance")
            # The queued private file must survive reopening every Bobi store.
            await flow.close()
            flow.open()
            outbound = WahaOutboundMediaTransport(
                base_url="http://waha-fixture:3000",
                session="default",
                api_key="waha-fixture-key",
                client=client,
            )
            delivered = await flow.runtime.archive.process_next(
                "waha",
                outbound,
                owner_token="file-worker",
                now_ts=flow.now,
            )
            assert delivered.state == "sent"
            assert len(waha.files) == 1 and waha.files[0]["reply_to"] == "retrieve"
            assert base64.b64decode(waha.files[0]["file"]["data"]) == waha.content
            assert waha.files[0]["file"]["filename"] == "insurance.pdf"
            assert "url" not in waha.files[0]["file"]
            assert "a" * 40 not in json.dumps(waha.files)

            await flow.send("delete", "מחק את המסמך insurance")
            assert "כן או לא" in waha.replies[-1]["text"]
            assert flow.runtime.archive.index.get(saved[0].object_id, owner_key="owner")
            await flow.close()
            flow.open()
            await flow.send("approve", "כן")
            assert "סל המחזור" in waha.replies[-1]["text"]
            assert flow.runtime.archive.index.get(saved[0].object_id, owner_key="owner") is None
            await flow.send("trashed", "שלח לי את המסמך insurance")
            assert "לא מצאתי" in waha.replies[-1]["text"]
            assert len(waha.files) == 1
            await flow.send("restore", "שחזר את המסמך insurance")
            await flow.send("move", "העבר את המסמך insurance לתיקיית רכב")
            current = flow.runtime.archive.index.get(saved[0].object_id, owner_key="owner")
            assert current.category == "רכב" and current.revision == 3
            assert current.storage_uri == saved[0].storage_uri
            assert (
                await flow.runtime.archive.storage.read(current.storage_uri, max_bytes=1024)
                == waha.content
            )
            assert flow.runtime.archive.index.search(owner_key="another-user") == ()
            assert understanding.texts == []
        finally:
            await flow.close()


@pytest.mark.asyncio
async def test_whatsapp_cloud_receipt_review_restart_reply_recovery_and_revoked_permission(
    archive_endpoint, tmp_path, monkeypatch,
):
    _configure_archive(tmp_path / "bobi-next-setup.db", archive_endpoint)
    waha = _WahaHTTP()
    understanding = _Understanding()
    async with httpx.AsyncClient(transport=httpx.MockTransport(waha.request)) as client:
        _inject_waha_http(monkeypatch, client)
        flow = _WhatsAppFlow(tmp_path, understanding)
        try:
            await flow.send("receipt-save", "שמור את הקבלה", media=True)
            item, = flow.runtime.archive.index.search(owner_key="owner", kind="receipt")
            assert item.metadata["financial_document"]["requires_review"] is True
            await flow.send("receipt-details", "מה פרטי הקבלה insurance?")
            assert "אין פרטים כספיים זמינים" in waha.replies[-1]["text"]
            await flow.send(
                "receipt-review",
                "עדכן את פרטי הקבלה insurance: סכום=123.45 ILS; ספק=IKEA; תאריך=2026-10-05",
                quoted=True,
            )
            assert "123.45 ILS" in waha.replies[-1]["text"]
            assert "כן או לא" in waha.replies[-1]["text"]
            assert "financial_review" not in flow.runtime.archive.index.get(
                item.object_id, owner_key="owner",
            ).metadata
            await flow.close()
            flow.open()
            confirmation = flow.event("receipt-confirm", "כן")
            assert flow.ingest(confirmation).accepted
            waha.fail_reply_once = True
            assert (await flow.process()).state == "retry"
            reviewed = flow.runtime.archive.index.get(item.object_id, owner_key="owner")
            assert reviewed.revision == 1
            assert reviewed.metadata["financial_review"]["fields"] == {
                "total_minor": 12345, "currency": "ILS", "merchant": "IKEA",
                "document_date": "2026-10-05",
            }
            await flow.close()
            flow.open()
            assert (await flow.process()).state == "completed"
            assert "שכתבת ואישרת" in waha.replies[-1]["text"]
            assert flow.ingest(confirmation).duplicate
            await flow.send("receipt-reviewed-details", "מה פרטי הקבלה IKEA?")
            assert "פרטים שכתבת ואישרת" in waha.replies[-1]["text"]
            assert "123.45 ILS" in waha.replies[-1]["text"]
            current = flow.runtime.archive.index.get(item.object_id, owner_key="owner")
            assert current.revision == 1 and current.storage_uri == item.storage_uri
            assert current.metadata["financial_document"] == item.metadata["financial_document"]
            assert await flow.runtime.archive.storage.read(current.storage_uri, max_bytes=1024)

            await flow.send("receipt-next-review", "עדכן את פרטי הקבלה insurance: מע״מ=12 ILS")
            user_policy = flow.setup.get_user("owner").policy
            flow.setup.update_user_policy(
                "owner", replace(user_policy, denied_actions=frozenset({"archive.review"})),
            )
            await flow.send("receipt-revoked-confirm", "כן")
            assert "✅" not in waha.replies[-1]["text"]
            assert flow.runtime.archive.index.get(item.object_id, owner_key="owner").revision == 1
            flow.setup.update_user_policy(
                "owner", replace(user_policy, denied_capabilities=frozenset({"archive.read"})),
            )
            await flow.send("receipt-denied-details", "מה פרטי הקבלה insurance?")
            assert "אין הרשאה" in waha.replies[-1]["text"]
            assert "123.45" not in waha.replies[-1]["text"]
            assert not waha.files and understanding.texts == []
            assert len([request for request in waha.requests if request.method == "GET"]) == 1
        finally:
            await flow.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["read_policy", "identity_relinked", "review_policy"])
async def test_private_financial_reply_retry_rechecks_current_policy_and_identity(
    archive_endpoint, tmp_path, monkeypatch, case,
):
    _configure_archive(tmp_path / "bobi-next-setup.db", archive_endpoint)
    waha = _WahaHTTP()
    understanding = _Understanding()
    async with httpx.AsyncClient(transport=httpx.MockTransport(waha.request)) as client:
        _inject_waha_http(monkeypatch, client)
        flow = _WhatsAppFlow(tmp_path, understanding)
        try:
            await flow.send("save", "שמור את הקבלה", media=True)
            text = "עדכן את פרטי הקבלה insurance: ספק=IKEA; סכום=123.45 ILS"
            if case != "review_policy":
                await flow.send("review", text)
                await flow.send("approve", "כן")
                text = "מה פרטי הקבלה IKEA?"
            event = flow.event("private-reply", text)
            assert flow.ingest(event).accepted
            waha.fail_reply_once = True
            assert (await flow.process()).state == "retry"
            message = flow.boundary.messages.get_inbound("waha", "private-reply")
            assert "sender_fingerprint" in message.metadata
            assert "111@c.us" not in str(message.metadata)
            cached = flow.boundary.messages.outbound_for(message)
            assert "123.45 ILS" in cached.text
            sends_before = sum(request.url.path == "/api/sendText" for request in waha.requests)
            if case == "identity_relinked":
                flow.setup.unlink_identity(provider_key="waha", external_id="111@c.us")
                flow.setup.create_user(display_name="Other", role="owner", user_key="other")
                flow.setup.link_identity(
                    provider_key="waha", external_id="111@c.us", user_key="other",
                )
            else:
                policy = flow.setup.get_user("owner").policy
                action = "archive.details" if case == "read_policy" else "archive.review"
                flow.setup.update_user_policy(
                    "owner", replace(policy, denied_actions=frozenset({action})),
                )
            await flow.close()
            flow.open()
            blocked = await flow.process()
            assert blocked.state == "failed"
            assert blocked.last_error.endswith("reply_authorization_denied")
            assert sum(request.url.path == "/api/sendText" for request in waha.requests) == sends_before
            assert flow.boundary.messages.outbound_for(blocked).text == cached.text
            assert await flow.process() is None  # No automatic retry after explicit revocation.
            assert understanding.texts == [] and not waha.files
        finally:
            await flow.close()


@pytest.mark.asyncio
async def test_receipt_expense_flow_requires_review_then_independent_approval_and_survives_reply_loss(
    archive_endpoint, tmp_path, monkeypatch,
):
    _configure_archive(tmp_path / "bobi-next-setup.db", archive_endpoint)
    waha = _WahaHTTP()
    understanding = _Understanding()
    async with httpx.AsyncClient(transport=httpx.MockTransport(waha.request)) as client:
        _inject_waha_http(monkeypatch, client)
        flow = _WhatsAppFlow(tmp_path, understanding)
        try:
            await flow.send("expense-receipt-save", "שמור את הקבלה", media=True)
            item, = flow.runtime.archive.index.search(owner_key="owner", kind="receipt")
            await flow.send("expense-unreviewed", "רשום הוצאה מהקבלה insurance בקטגוריית בית")
            assert "החילוץ האוטומטי אינו מספיק" in waha.replies[-1]["text"]
            assert flow.runtime.pending_approvals.peek_latest(user_key="owner") is None
            await flow.send(
                "expense-source-review",
                "עדכן את פרטי הקבלה insurance: סכום=12.34 ILS; ספק=IKEA; תאריך=2026-10-05",
            )
            await flow.send("expense-review-confirm", "כן")
            assert flow.runtime.expenses.for_source(owner_key="owner", sha256=item.sha256) is None
            await flow.send("expense-request", "רשום הוצאה מהקבלה IKEA בקטגוריית בית", quoted=True)
            prompt = waha.replies[-1]["text"]
            assert "12.34 ILS" in prompt and "2026-10-05" in prompt and "קטגוריה: בית" in prompt
            await flow.close()
            flow.open()
            event = flow.event("expense-confirm", "כן")
            assert flow.ingest(event).accepted
            waha.fail_reply_once = True
            assert (await flow.process()).state == "retry"
            entry = flow.runtime.expenses.for_source(owner_key="owner", sha256=item.sha256)
            assert entry.amount_minor == 1234 and entry.source_revision == 1
            await flow.close()
            flow.open()
            assert (await flow.process()).state == "completed"
            assert "נרשמה ואומתה" in waha.replies[-1]["text"]
            assert flow.ingest(event).duplicate
            await flow.send("expense-again", "רשום הוצאה מהקבלה IKEA בקטגוריית ריהוט")
            assert "לא נרשמה הוצאה נוספת" in waha.replies[-1]["text"]
            assert flow.runtime.expenses.for_source(owner_key="owner", sha256=item.sha256) == entry
            await flow.send("expense-summary", "הצג הוצאות לחודש 2026-10")
            assert "12.34 ILS (1 הוצאה)" in waha.replies[-1]["text"]
            assert "בית" in waha.replies[-1]["text"] and "ריהוט" not in waha.replies[-1]["text"]
            source = flow.runtime.archive.index.get(item.object_id, owner_key="owner")
            assert source.revision == 1 and source.storage_uri == item.storage_uri
            assert await flow.runtime.archive.storage.read(source.storage_uri, max_bytes=1024)
            assert flow.ingest(flow.event("expense-private-retry", "הצג הוצאות לחודש 2026-10")).accepted
            waha.fail_reply_once = True
            assert (await flow.process()).state == "retry"
            queued = flow.boundary.messages.get_inbound("waha", "expense-private-retry")
            cached = flow.boundary.messages.outbound_for(queued)
            assert "12.34 ILS" in cached.text
            sends = sum(request.url.path == "/api/sendText" for request in waha.requests)
            policy = flow.setup.get_user("owner").policy
            flow.setup.update_user_policy(
                "owner", replace(policy, denied_capabilities=frozenset({"expenses.read"})),
            )
            await flow.close()
            flow.open()
            blocked = await flow.process()
            assert blocked.state == "failed" and blocked.last_error.endswith("reply_authorization_denied")
            assert sum(request.url.path == "/api/sendText" for request in waha.requests) == sends
            assert flow.boundary.messages.outbound_for(blocked).text == cached.text
            assert not waha.files and understanding.texts == []
        finally:
            await flow.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["no_instruction", "quote_only", "denied", "shadow"])
async def test_cloud_whatsapp_requires_current_explicit_authority_and_permission(
    archive_endpoint,
    tmp_path,
    monkeypatch,
    case,
):
    _configure_archive(tmp_path / "bobi-next-setup.db", archive_endpoint)
    waha = _WahaHTTP()
    async with httpx.AsyncClient(transport=httpx.MockTransport(waha.request)) as client:
        _inject_waha_http(monkeypatch, client)
        flow = _WhatsAppFlow(tmp_path, _Understanding(), dry_run=case == "shadow")
        try:
            if case == "denied":
                policy = flow.setup.get_user("owner").policy
                flow.setup.update_user_policy(
                    "owner", replace(policy, denied_capabilities=frozenset({"archive.write"}))
                )
            caption = "מה כתוב במסמך?" if case == "no_instruction" else "שמור את זה"
            await flow.send("authority", caption, media=case != "quote_only", quoted=True)
            assert flow.runtime.archive.index.search(owner_key="owner") == ()
            assert not (tmp_path / "bobi-next-archive-files").exists()
            assert not waha.files
            assert all("שמרתי" not in reply["text"] for reply in waha.replies)
            if case != "no_instruction":
                assert not [r for r in waha.requests if r.method == "GET"]
        finally:
            await flow.close()


@pytest.mark.asyncio
async def test_manual_expense_whatsapp_restart_reply_loss_and_cached_prompt_revocation(
    archive_endpoint, tmp_path, monkeypatch,
):
    _configure_archive(tmp_path / "bobi-next-setup.db", archive_endpoint)
    waha = _WahaHTTP()
    understanding = _Understanding()
    text = "רשום הוצאה: סכום=35.01 ILS; ספק=מכולת; תאריך=2026-10-05; קטגוריה=מזון"
    async with httpx.AsyncClient(transport=httpx.MockTransport(waha.request)) as client:
        _inject_waha_http(monkeypatch, client)
        flow = _WhatsAppFlow(tmp_path, understanding)
        try:
            policy = flow.setup.get_user("owner").policy
            flow.setup.update_user_policy("owner", replace(
                policy, allowed_capabilities=frozenset({"expenses.write", "expenses.read"}),
                allowed_domains=frozenset({"expenses"}),
            ))
            await flow.send("manual-expense", text, quoted=True)
            prompt = waha.replies[-1]["text"]
            assert "35.01 ILS" in prompt and "מכולת" in prompt and "מזון" in prompt
            pending = flow.runtime.pending_approvals.peek_latest(user_key="owner")
            assert pending.plans[0].data["source_kind"] == "manual"
            assert flow.runtime.expenses.get(pending.plans[0].device_id, owner_key="owner") is None
            await flow.close()
            flow.open()
            event = flow.event("manual-confirm", "כן")
            assert flow.ingest(event).accepted
            waha.fail_reply_once = True
            assert (await flow.process()).state == "retry"
            entry = flow.runtime.expenses.get(pending.plans[0].device_id, owner_key="owner")
            assert entry.amount_minor == 3501 and entry.source_kind == "manual"
            assert entry.source_sha256 is None and entry.source_review_request_id == ""
            await flow.close()
            flow.open()
            assert (await flow.process()).state == "completed"
            assert flow.ingest(event).duplicate
            await flow.send("manual-summary", "הצג הוצאות לחודש 2026-10")
            assert "35.01 ILS (1 הוצאה)" in waha.replies[-1]["text"]
            assert flow.runtime.archive.index.search(owner_key="owner") == ()

            assert flow.ingest(flow.event("manual-private-prompt", text.replace("35.01", "99.99"))).accepted
            waha.fail_reply_once = True
            assert (await flow.process()).state == "retry"
            queued = flow.boundary.messages.get_inbound("waha", "manual-private-prompt")
            cached = flow.boundary.messages.outbound_for(queued)
            assert "99.99 ILS" in cached.text
            sends = sum(request.url.path == "/api/sendText" for request in waha.requests)
            current_policy = flow.setup.get_user("owner").policy
            flow.setup.update_user_policy("owner", replace(
                current_policy, denied_capabilities=frozenset({"expenses.write"}),
            ))
            await flow.close()
            flow.open()
            blocked = await flow.process()
            assert blocked.state == "failed" and blocked.last_error.endswith("reply_authorization_denied")
            assert sum(request.url.path == "/api/sendText" for request in waha.requests) == sends
            assert flow.boundary.messages.outbound_for(blocked).text == cached.text
            assert "35.01 ILS (1 הוצאה)" in flow.runtime.expenses.month_reply(owner_key="owner", month="2026-10")
            assert not waha.files and understanding.texts == []
            assert not [request for request in waha.requests if request.method == "GET"]
        finally:
            await flow.close()
