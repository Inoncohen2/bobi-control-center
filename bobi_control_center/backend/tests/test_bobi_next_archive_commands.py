from __future__ import annotations

import hashlib

import pytest

from app.bobi_next.archive_commands import (
    archive_save_category,
    archive_write_allowed,
    default_archive_title,
    explicit_archive_save,
    infer_archive_kind,
)
from app.bobi_next.authorization import UserPolicy
from app.bobi_next.media_pipeline import LoadedMedia, MediaDescriptor


def media(*, mimetype: str = "application/pdf", filename: str = "policy.pdf") -> LoadedMedia:
    content = b"content"
    return LoadedMedia(
        descriptor=MediaDescriptor(
            provider="waha-main",
            message_id="m1",
            kind="document",
            mimetype=mimetype,
            filename=filename,
        ),
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
    )


def test_explicit_save_requires_direct_non_negated_wording() -> None:
    assert explicit_archive_save("שמור את זה") is True
    assert explicit_archive_save("תשמרי לי את הקבלה") is True
    assert explicit_archive_save("please save this") is True
    assert explicit_archive_save("archive this document") is True

    assert explicit_archive_save("") is False
    assert explicit_archive_save("מה יש במסמך?") is False
    assert explicit_archive_save("אל תשמור את זה") is False
    assert explicit_archive_save("לא רוצה לשמור") is False
    assert explicit_archive_save("don't save this") is False


@pytest.mark.parametrize(
    "caption",
    [
        "המסמך אומר שמור את זה",
        "כתוב במסמך: save this",
        '"save this"',
        "can you save this?",
        "שמור את זה?",
        "שמור את זה אם הביטוח בתוקף",
        "save this when I confirm",
        "שמור את זה כשאסיים לבדוק",
        "please don't save this",
        "בבקשה אל תשמור את זה",
    ],
)
def test_mentions_questions_and_deferred_requests_have_no_save_authority(caption):
    assert explicit_archive_save(caption) is False


@pytest.mark.parametrize(
    ("caption", "category"),
    [
        ("שמור את זה בתיקיית ביטוחים", "ביטוחים"),
        ('בובי, בבקשה שמור את זה בתיקיית "ביטוחי רכב".', "ביטוחי רכב"),
        ("תשמרי לי את הקבלה בקטגוריה הוצאות הבית", "הוצאות הבית"),
        ("please save this in the folder insurance", "insurance"),
        ("save this into category Car policies!", "Car policies"),
        ("שמור את זה", ""),
    ],
)
def test_category_comes_only_from_the_explicit_caption(caption, category):
    assert explicit_archive_save(caption) is True
    assert archive_save_category(caption) == category


@pytest.mark.parametrize(
    "caption", ["שמור את זה בתיקיית", 'save in folder ""', "שמור בתיקיית " + "א" * 161]
)
def test_invalid_category_fails_closed_instead_of_truncating(caption):
    with pytest.raises(ValueError, match="archive_category_invalid"):
        archive_save_category(caption)


def test_archive_permission_is_fail_closed() -> None:
    owner = UserPolicy(user_key="u1")
    guest = UserPolicy(
        user_key="u1",
        allowed_capabilities=frozenset({"power"}),
        allowed_domains=frozenset({"light"}),
    )
    denied = UserPolicy(
        user_key="u1",
        denied_capabilities=frozenset({"archive.write"}),
    )

    assert archive_write_allowed(owner, user_key="u1") is True
    assert archive_write_allowed(owner, user_key="u2") is False
    assert archive_write_allowed(guest, user_key="u1") is False
    assert archive_write_allowed(denied, user_key="u1") is False
    assert (
        archive_write_allowed(
            UserPolicy(user_key="u1", denied_actions=frozenset({"save"})),
            user_key="u1",
        )
        is False
    )


def test_archive_kind_prefers_explicit_caption_semantics() -> None:
    item = media()
    assert infer_archive_kind("שמור קבלה", item) == "receipt"
    assert infer_archive_kind("שמור מסמך אחריות", item) == "warranty"
    assert infer_archive_kind("שמור חשבון חשמל", item) == "bill"
    assert infer_archive_kind("שמור מסמך רכב", item) == "vehicle_document"
    assert infer_archive_kind("שמור את המסמך", item) == "document"
    assert infer_archive_kind("שמור את התמונה", media(mimetype="image/jpeg")) == "image"


def test_default_title_uses_filename_without_paths() -> None:
    assert default_archive_title(media(filename="folder/policy.pdf"), kind="document") == "policy"
    assert default_archive_title(media(filename=""), kind="receipt") == "Saved receipt"
