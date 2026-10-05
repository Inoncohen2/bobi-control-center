"""Bounded, advisory receipt/bill extraction from current media-derived text.

Only labeled fields are extracted. OCR/vision text is untrusted evidence, never
execution authority. Conflicting amounts/currencies and ambiguous dates remain
missing; no financial transaction, reminder or archive mutation is created here.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

_MAX_TEXT = 32_000
_CURRENCY = re.compile(
    r"₪|€|£|\b(?:ILS|NIS|USD|EUR|GBP)\b|US\$|ש[\"״']ח|שקלים?",
    re.IGNORECASE,
)
_CODES = {
    "₪": "ILS",
    "ils": "ILS",
    "nis": "ILS",
    'ש"ח': "ILS",
    "ש״ח": "ILS",
    "ש'ח": "ILS",
    "שקל": "ILS",
    "שקלים": "ILS",
    "€": "EUR",
    "eur": "EUR",
    "£": "GBP",
    "gbp": "GBP",
    "usd": "USD",
    "us$": "USD",
}
_FIELDS = (
    (
        "merchant",
        re.compile(
            r"^(?:בית\s+עסק|שם\s+(?:העסק|הספק)|ספק|merchant|vendor|supplier|issuer)\s*[:：]\s*(.+)$",
            re.I,
        ),
    ),
    (
        "document_number",
        re.compile(
            r"^(?:מספר\s+(?:חשבונית|קבלה|מסמך)|(?:invoice|receipt|document)\s*(?:number|no\.?|#))\s*[:：]?\s*([A-Z0-9/-]{1,64})$",
            re.I,
        ),
    ),
    (
        "document_date",
        re.compile(
            r"^(?:תאריך(?:\s+(?:חשבונית|קבלה|מסמך))?|(?:invoice|receipt|document)\s+date|date)\s*[:：]\s*(.+)$",
            re.I,
        ),
    ),
    (
        "due_date",
        re.compile(
            r"^(?:לתשלום\s+עד|מועד\s+תשלום|תאריך\s+(?:פירעון|פרעון)|due\s+date|pay\s+by)\s*[:：]\s*(.+)$",
            re.I,
        ),
    ),
    (
        "total",
        re.compile(
            r"^(?:סה[\"״']?כ(?:\s+לתשלום)?|סך\s+הכל(?:\s+לתשלום)?|total(?:\s+amount)?(?:\s+due)?|amount\s+due|grand\s+total)\s*[:：]?\s+(.+)$",
            re.I,
        ),
    ),
    (
        "tax",
        re.compile(
            r"^(?:מע[\"״']?מ(?:\s+סכום)?|tax(?:\s+amount)?|vat(?:\s+amount)?)\s*[:：]?\s+(.+)$",
            re.I,
        ),
    ),
    ("currency", re.compile(r"^(?:מטבע|currency)\s*[:：]\s*(.+)$", re.I)),
)


@dataclass(slots=True, frozen=True)
class FinancialDocumentExtraction:
    kind: str
    fields: dict[str, str | int] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    text_sha256: str = ""

    def metadata(self, *, media_sha256: str) -> dict:
        return {
            "schema_version": 1,
            "kind": self.kind,
            "fields": dict(self.fields),
            "status": "partial" if self.fields else "unavailable",
            "requires_review": True,
            "source": "media_derived_labeled_text",
            "media_sha256": media_sha256,
            "text_sha256": self.text_sha256,
            "warnings": list(self.warnings),
        }


def _unique(values: list, *, name: str, warnings: list[str]):
    unique = list(dict.fromkeys(values))
    if len(unique) == 1:
        return unique[0]
    if len(unique) > 1:
        warnings.append(f"conflicting_{name}")
    return None


def _amount(value: str) -> int | None:
    text = value.strip().replace("\u00a0", " ")
    if len(text) > 32 or not re.fullmatch(r"[+-]?\d[\d., ]*", text):
        return None
    sign = "-" if text.startswith("-") else ""
    text = text.lstrip("+-")
    if " " in text:
        if not re.fullmatch(r"\d{1,3}(?: \d{3})+(?:[.,]\d{1,2})?", text):
            return None
        text = text.replace(" ", "")
    if "," in text and "." in text:
        if re.fullmatch(r"\d{1,3}(?:,\d{3})+\.\d{1,2}", text):
            text = text.replace(",", "")
        elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d{1,2}", text):
            text = text.replace(".", "").replace(",", ".")
        else:
            return None
    elif "," in text or "." in text:
        separator = "," if "," in text else "."
        escaped = re.escape(separator)
        if re.fullmatch(rf"\d+{escaped}\d{{1,2}}", text):
            text = text.replace(separator, ".")
        elif re.fullmatch(rf"\d{{1,3}}(?:{escaped}\d{{3}})+", text):
            text = text.replace(separator, "")
        else:
            return None
    try:
        amount = Decimal(sign + text)
        if not amount.is_finite() or abs(amount) > Decimal("1000000000000"):
            return None
        return int(amount * 100)
    except (InvalidOperation, ValueError):
        return None


def _money(value: str, *, currency: str | None) -> tuple[int, str] | None:
    codes = {_CODES[m.group().casefold()] for m in _CURRENCY.finditer(value)}
    if len(codes) > 1:
        return None
    explicit = next(iter(codes)) if codes else None
    if explicit and currency and explicit != currency:
        return None
    code = explicit or currency
    amount = _amount(_CURRENCY.sub("", value).strip().strip("*"))
    return (amount, code) if amount is not None and code else None


def _date(value: str, *, hebrew: bool) -> str | None:
    text = value.strip().strip("*")
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return date.fromisoformat(text).isoformat()
        if not re.fullmatch(r"\d{1,2}[/.]\d{1,2}[/.]\d{4}", text):
            return None
        first, second, year = map(int, re.split(r"[/.]", text))
        if hebrew or first > 12:
            day, month = first, second
        elif second > 12:
            month, day = first, second
        else:
            return None
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def extract_financial_document(
    text: str,
    *,
    requested_kind: str,
) -> FinancialDocumentExtraction | None:
    original = str(text or "").replace("\x00", "")
    bounded = original[:_MAX_TEXT]
    if len(original) > _MAX_TEXT:
        # Do not extract a partial amount/date cut at the byte/line boundary.
        bounded = bounded.rsplit("\n", 1)[0] if "\n" in bounded else ""
    lines = [line.strip().strip("#* ") for line in bounded.splitlines()[:512] if len(line) <= 600]
    kind = requested_kind if requested_kind in {"receipt", "bill"} else ""
    if not kind:
        for line in lines[:20]:
            if re.match(
                r"^(?:חשבון\s+(?:חשמל|מים)|utility\s+bill|electric\s+bill|water\s+bill)\b",
                line,
                re.I,
            ):
                kind = "bill"
                break
            if re.match(r"^(?:חשבונית(?:\s+מס)?|קבלה|tax\s+invoice|invoice|receipt)\b", line, re.I):
                kind = "receipt"
                break
    if not kind:
        return None
    candidates: dict[str, list] = {name: [] for name, _ in _FIELDS}
    warnings: list[str] = []
    for line in lines:
        for name, pattern in _FIELDS:
            match = pattern.fullmatch(line)
            if match is None:
                continue
            raw = match[1].strip().strip("*")
            if name.endswith("date"):
                value = _date(raw, hebrew=bool(re.search(r"[א-ת]", line[: match.start(1)])))
                if value is None:
                    warnings.append(f"ambiguous_or_invalid_{name}")
                else:
                    candidates[name].append(value)
            elif name == "merchant":
                if 0 < len(raw) <= 160 and not re.search(r"https?://|[\x00-\x1f]", raw):
                    candidates[name].append(raw)
            else:
                candidates[name].append(raw)
            break
    fields: dict[str, str | int] = {}
    for name in ("merchant", "document_number", "document_date", "due_date"):
        value = _unique(candidates[name], name=name, warnings=warnings)
        if value is not None:
            fields[name] = value
    currencies = []
    for raw in candidates["currency"]:
        match = _CURRENCY.fullmatch(raw)
        if match:
            currencies.append(_CODES[match.group().casefold()])
        else:
            warnings.append("invalid_currency")
    for raw in candidates["total"] + candidates["tax"]:
        currencies.extend(_CODES[m.group().casefold()] for m in _CURRENCY.finditer(raw))
    currency = _unique(currencies, name="currency", warnings=warnings)
    # A conflicting global currency makes every amount uncertain, even if one
    # line appears parseable in isolation.
    for name in ("total", "tax"):
        amounts = []
        invalid = False
        for raw in candidates[name]:
            value = _money(raw, currency=currency)
            if value is None:
                warnings.append(f"ambiguous_or_invalid_{name}")
                invalid = True
            else:
                amounts.append(value)
        chosen = _unique(amounts, name=name, warnings=warnings)
        if (
            chosen is not None
            and not invalid
            and not {"conflicting_currency", "invalid_currency"}.intersection(warnings)
        ):
            if currency and currency != chosen[1]:
                warnings.append("conflicting_currency")
                fields.pop("total_minor", None)
                fields.pop("currency", None)
                continue
            fields[f"{name}_minor"] = chosen[0]
            fields["currency"] = chosen[1]
            currency = chosen[1]
    return FinancialDocumentExtraction(
        kind,
        fields,
        tuple(dict.fromkeys(warnings)),
        hashlib.sha256(bounded.encode()).hexdigest(),
    )
