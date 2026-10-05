"""Coordinate provider configuration with durable archive-save ownership."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path

from .archive_store import ArchiveStore
from .integration_store import ExternalIntegration, IntegrationStore
from .request_ledger import RequestLedger


class ArchiveConfigurationConflict(ValueError):
    pass


def archive_connection_fingerprint(installation_id: str, item: ExternalIntegration) -> str:
    """Bind a connection proof to the immutable credential version and tenant."""
    return hashlib.sha256(
        json.dumps(
            {
                "installation_id": installation_id,
                "key": item.integration_key,
                "endpoint": item.endpoint,
                "secret_ref": item.secret_ref,
                "enabled": item.enabled,
                "archive_enabled": item.config.get("archive_enabled"),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


@contextmanager
def archive_configuration_guard(setup_path: Path):
    """Hold the save-claim lock while checking/changing archive configuration.

    Conversation saves hold a durable running claim through upload/index commit.
    Configuration cannot cross an active save, and a new save cannot claim until
    the configuration transaction ends. Expired running claims also block: an
    upload may still be returning and must finish/recover first.
    """
    requests = RequestLedger(setup_path.with_name("bobi-next-requests.db"))
    try:
        requests._db.execute("BEGIN IMMEDIATE")
        active = requests._db.execute(
            "SELECT 1 FROM request_ledger WHERE state='running' "
            "AND request_id LIKE 'archive-save:%' LIMIT 1"
        ).fetchone()
        if active:
            raise ArchiveConfigurationConflict("archive_save_in_progress")
        yield
    finally:
        if requests._db.in_transaction:
            requests._db.rollback()
        requests.close()


def archive_provider_change_allowed(setup_path: Path, endpoint: str) -> None:
    archive = ArchiveStore(setup_path.with_name("bobi-next-archive.db"))
    try:
        has_cloud = archive.has_cloud_objects()
    finally:
        archive.close()
    if not has_cloud:
        return
    integrations = IntegrationStore(setup_path)
    try:
        candidates = integrations.list(integration_type="bobi_archive")
        if not candidates:
            candidates = tuple(
                item
                for item in integrations.list(integration_type="bobi_storage")
                if item.config.get("archive_enabled") is True
            )
        enabled = tuple(item for item in candidates if item.enabled)
        current = (
            enabled[0] if len(enabled) == 1 else (candidates[0] if len(candidates) == 1 else None)
        )
        if current is None or current.endpoint != endpoint:
            raise ArchiveConfigurationConflict("archive_provider_change_requires_migration")
    finally:
        integrations.close()
