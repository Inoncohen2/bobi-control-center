from __future__ import annotations

from app.bobi_next.archive_store import ArchiveStore, sha256_hex


def test_register_dedupes_active_sha_per_owner(tmp_path) -> None:
    store = ArchiveStore(tmp_path / "archive.db")
    digest = sha256_hex(b"same document")

    first = store.register(
        owner_key="u1",
        kind="document",
        title="Insurance",
        category="vehicle",
        filename="insurance.pdf",
        mime_type="application/pdf",
        size_bytes=123,
        sha256=digest,
        storage_uri="storage://documents/insurance.pdf",
        tags=["car", "policy"],
        now_ts=100,
    )
    second = store.register(
        owner_key="u1",
        kind="document",
        title="Duplicate title",
        sha256=digest,
        storage_uri="storage://documents/copy.pdf",
        now_ts=200,
    )
    other_owner = store.register(
        owner_key="u2",
        kind="document",
        title="Insurance",
        sha256=digest,
        storage_uri="storage://documents/u2.pdf",
        now_ts=200,
    )

    assert second.object_id == first.object_id
    assert second.title == "Insurance"
    assert other_owner.object_id != first.object_id
    store.close()


def test_move_category_tags_search_and_owner_isolation(tmp_path) -> None:
    store = ArchiveStore(tmp_path / "archive.db")
    record = store.register(
        owner_key="u1",
        kind="receipt",
        title="Coffee machine receipt",
        category="receipts",
        filename="receipt.jpg",
        mime_type="image/jpeg",
        text_excerpt="Coffee Store model X warranty two years",
        tags=["Kitchen", "Warranty", "kitchen"],
        metadata={"merchant": "Coffee Store", "currency": "ILS"},
        now_ts=100,
    )
    store.register(
        owner_key="u2",
        kind="receipt",
        title="Coffee machine receipt",
        category="private",
        now_ts=100,
    )

    moved = store.move_category(
        record.object_id,
        owner_key="u1",
        category=" appliances ",
        now_ts=110,
    )
    tagged = store.set_tags(
        record.object_id,
        owner_key="u1",
        tags=["Warranty", "Coffee", "coffee"],
        now_ts=120,
    )

    assert moved.category == "appliances"
    assert tagged.tags == ("Warranty", "Coffee")
    assert [item.object_id for item in store.search(owner_key="u1", query="warranty")] == [
        record.object_id
    ]
    assert [item.object_id for item in store.search(owner_key="u1", query="Coffee Store")] == [
        record.object_id
    ]
    assert store.search(owner_key="u2", category="appliances") == ()
    store.close()


def test_soft_delete_restore_and_reingest(tmp_path) -> None:
    store = ArchiveStore(tmp_path / "archive.db")
    digest = sha256_hex(b"document bytes")
    first = store.register(
        owner_key="u1",
        kind="vehicle_document",
        title="Registration",
        sha256=digest,
        now_ts=100,
    )

    deleted = store.soft_delete(first.object_id, owner_key="u1", now_ts=110)
    replacement = store.register(
        owner_key="u1",
        kind="vehicle_document",
        title="Registration re-upload",
        sha256=digest,
        now_ts=120,
    )

    assert deleted.status == "deleted"
    assert store.get(first.object_id, owner_key="u1") is None
    assert replacement.object_id != first.object_id
    assert len(store.search(owner_key="u1", include_deleted=True)) == 2

    restored = store.restore(first.object_id, owner_key="u1", now_ts=130)
    assert restored.status == "active"
    assert store.get(first.object_id, owner_key="u1") is not None
    store.close()


def test_validation_and_metadata_bounds(tmp_path) -> None:
    store = ArchiveStore(tmp_path / "archive.db")

    try:
        store.register(owner_key="", kind="document", title="x")
    except ValueError as exc:
        assert str(exc) == "archive_owner_required"
    else:
        raise AssertionError("missing owner must fail")

    try:
        store.register(owner_key="u1", kind="unknown", title="x")
    except ValueError as exc:
        assert str(exc) == "archive_kind_invalid"
    else:
        raise AssertionError("unknown kind must fail")

    try:
        store.register(owner_key="u1", kind="document", title="x", sha256="bad")
    except ValueError as exc:
        assert str(exc) == "archive_sha256_invalid"
    else:
        raise AssertionError("invalid sha must fail")

    try:
        store.register(
            owner_key="u1",
            kind="document",
            title="x",
            metadata={"blob": "x" * 40_000},
        )
    except ValueError as exc:
        assert str(exc) == "archive_metadata_too_large"
    else:
        raise AssertionError("oversized metadata must fail")
    store.close()
