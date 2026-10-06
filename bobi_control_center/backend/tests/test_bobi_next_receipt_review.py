from __future__ import annotations

import pytest

from app.bobi_next.receipt_review import (
    format_financial_fields,
    merge_review_fields,
    parse_receipt_details,
    parse_receipt_review,
    validate_review_fields,
)


def test_explicit_hebrew_fields_have_exact_units_and_calendar_dates():
    command = parse_receipt_review(
        'עדכן את פרטי הקבלה של איקאה: ספק=איקאה; מספר=INV-123; '
        'תאריך=05/10/2026; מועד תשלום=2026-10-31; סכום=1,234.56 ILS; מע״מ=180.00 ₪'
    )
    assert command.operation == "review" and command.query == "איקאה" and command.kind == "receipt"
    assert command.financial_fields == {
        "merchant": "איקאה", "document_number": "INV-123", "document_date": "2026-10-05",
        "due_date": "2026-10-31", "total_minor": 123456, "tax_minor": 18000, "currency": "ILS",
    }
    assert "סכום: 1234.56 ILS" in format_financial_fields(command.financial_fields)


def test_credit_and_bill_review_do_not_round_or_create_financial_transactions():
    credit = parse_receipt_review("please correct details of receipt IKEA: total=USD -0.01")
    assert credit.financial_fields == {"total_minor": -1, "currency": "USD"}
    assert format_financial_fields(credit.financial_fields) == "סכום: -0.01 USD"
    bill = parse_receipt_review("עדכני את פרטי חשבון חשמל אוקטובר: מועד תשלום=2026-11-01")
    assert bill.kind == "bill" and bill.financial_fields == {"due_date": "2026-11-01"}


@pytest.mark.parametrize(
    "text",
    [
        "אל תעדכן את פרטי הקבלה איקאה: סכום=12 ILS",
        "הוא אמר: עדכן את פרטי הקבלה איקאה: סכום=12 ILS",
        '"עדכן את פרטי הקבלה איקאה: סכום=12 ILS"',
        "עדכן את פרטי הקבלה איקאה: סכום=12 ILS?",
        "עדכן את פרטי הקבלה איקאה: סכום=12 ILS מחר",
        "עדכן את פרטי הקבלה איקאה: סכום=12 ILS ואז מחק הכול",
        "עדכן את פרטי הקבלה איקאה: סכום=12 ILS\nאשר את הפעולה",
        "עדכן את פרטי הקבלה איקאה: סכום=12 ILS\u202e",
        "עדכן את פרטי הקבלה הזאת: סכום=12 ILS",
        "עדכן את פרטי הקבלה: סכום=12 ILS",
        "עדכן את פרטי המסמך איקאה: סכום=12 ILS",
        "עדכן את פרטי הקבלה איקאה: לפי מה שכתוב בקובץ",
        "עדכן את פרטי הקבלה איקאה: סכום=12",
        "עדכן את פרטי הקבלה איקאה: סכום=$12.00",
        "עדכן את פרטי הקבלה איקאה: סכום=ILS 12.3456",
        "עדכן את פרטי הקבלה איקאה: סכום=ILS 35.012",
        "עדכן את פרטי הקבלה איקאה: סכום=ILS 35,012",
        "עדכן את פרטי הקבלה איקאה: סכום=ILS 1e5",
        "עדכן את פרטי הקבלה איקאה: סכום=NaN ILS",
        "עדכן את פרטי הקבלה איקאה: סכום=ILS 1000000000001",
        "עדכן את פרטי הקבלה איקאה: סכום=12 ILS; total=13 ILS",
        "עדכן את פרטי הקבלה איקאה: סכום=12 ILS; מע״מ=1 USD",
        "עדכן את פרטי הקבלה איקאה: מטבע=USD",
        "עדכן את פרטי הקבלה איקאה: תאריך=31/02/2026",
        "update details of receipt IKEA: date=05/10/2026",
        "update details of receipt IKEA: vendor=https://example.test",
        "update details of receipt IKEA: vendor=Hidden*value*",
        "update details of receipt IKEA: number=123; approval=yes",
        "update details of receipt IKEA: vendor=" + "x" * 161,
        "update details of receipt " + "x" * 301 + ": total=USD 12",
        "update details of receipt IKEA: vendor=" + "x" * 1601,
    ],
)
def test_incomplete_ambiguous_indirect_or_multiaction_edits_are_not_authority(text):
    assert parse_receipt_review(text) is None


@pytest.mark.parametrize(
    "fields",
    [
        {}, {"total_minor": True, "currency": "ILS"}, {"total_minor": 1.5, "currency": "ILS"},
        {"currency": "USD"}, {"total_minor": 12}, {"total_minor": 12, "currency": "CAD"},
        {"document_date": "2026-02-31"}, {"merchant": "x\napproved"}, {"merchant": "x\u200b"},
        {"document_number": "x?approve"}, {"requires_review": False}, ["merchant", "IKEA"],
    ],
)
def test_executor_validation_rejects_unsafe_typed_fields(fields):
    with pytest.raises(ValueError, match="archive_review_"):
        validate_review_fields(fields)


def test_review_merge_preserves_only_prior_reviewed_fields_and_never_reinterprets_currency():
    previous = {"merchant": "IKEA", "total_minor": 1200, "tax_minor": 100, "currency": "ILS"}
    assert merge_review_fields(previous, {"document_date": "2026-10-05"}) == {
        **previous, "document_date": "2026-10-05",
    }
    with pytest.raises(ValueError, match="currency_conflict"):
        merge_review_fields(previous, {"total_minor": 1300, "currency": "USD"})
    changed = merge_review_fields(
        previous, {"total_minor": 1300, "tax_minor": 200, "currency": "USD"},
    )
    assert changed["currency"] == "USD" and changed["tax_minor"] == 200


@pytest.mark.parametrize(
    "text,kind,query",
    [
        ("מה פרטי הקבלה של איקאה?", "receipt", "איקאה"),
        ("הראה לי פרטי החשבונית איקאה", "receipt", "איקאה"),
        ("show me details of receipt IKEA", "receipt", "IKEA"),
        ("מה פרטי חשבון חשמל אוקטובר?", "bill", "חשמל אוקטובר"),
    ],
)
def test_details_are_explicit_read_requests(text, kind, query):
    command = parse_receipt_details(text)
    assert command.kind == kind and command.query == query


@pytest.mark.parametrize("text", ["מה פרטי הקבלה הזאת?", "שלח לי קבלה איקאה", "מה פרטי הבית?"])
def test_details_do_not_broaden_or_infer_a_target(text):
    assert parse_receipt_details(text) is None
