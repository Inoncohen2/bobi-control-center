from __future__ import annotations

from app.bobi_next.archive_retrieval_commands import parse_archive_retrieval


def test_parses_specific_hebrew_receipt_request() -> None:
    command = parse_archive_retrieval("שלח לי את הקבלה של איקאה")
    assert command is not None
    assert command.kind == "receipt"
    assert command.query == "איקאה"


def test_parses_specific_english_invoice_request() -> None:
    command = parse_archive_retrieval("find me the invoice from IKEA")
    assert command is not None
    assert command.kind == "receipt"
    assert command.query == "IKEA"


def test_generic_image_request_is_not_hijacked_by_archive() -> None:
    assert parse_archive_retrieval("שלח לי תמונה של חתול") is None
    assert parse_archive_retrieval("send me a cat picture") is None


def test_statement_without_direct_retrieval_authority_is_ignored() -> None:
    assert parse_archive_retrieval("יש לי חשבונית מאיקאה") is None
    assert parse_archive_retrieval("החשבונית של איקאה") is None
