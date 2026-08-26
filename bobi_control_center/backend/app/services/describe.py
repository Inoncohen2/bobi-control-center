"""What a change will do, said in Hebrew — and the four refusals that are ours.

Every managed family reaches this module the same way: the bridge published an
item, the user asked for a new value, and a dialog has to say what that means
before anyone presses a button. The description is generated from what the
bridge published — its label, its options, its unit — because inventing labels
for settings this application has never seen would mean inventing settings.

Four checks are *not* generated, and run whatever the bridge says. They are the
ones where being wrong is expensive and where a bridge that has not shipped yet
cannot be relied on to catch the mistake:

1. **A household never runs out of admins.**
2. **A phone number is shown masked, and never lands in the audit trail.**
3. **Saving a Shabbat profile changes no device**, and the dialog says so.
4. **A control the bridge did not advertise is refused**, not passed along.

Home Assistant checks all four again. That is the point: two independent layers,
neither relaxed because of the other.
"""

from __future__ import annotations

from typing import Any

from app.models.manage import (
    ChangeField,
    ManagedItem,
    ObservedState,
    PreviewResponse,
    ResourceSnapshot,
)
from app.models.manage import ValidationError as FieldError
from app.services.resources import (
    DEVICE_SWITCH_OPERATIONS,
    SPECS,
    constraint_errors,
    humanise,
    is_forbidden_system_action,
    mask_phone,
    needs_confirm_word,
    rank,
)

#: The word a destructive change asks the user to type.
DESTRUCTIVE_CONFIRM_WORD = "מחק"

#: And the word a merely sensitive one asks for. Typing "מחק" to change a phone
#: number would be a small lie about what is happening, and the whole point of
#: making someone type a word is that they read it first.
SENSITIVE_CONFIRM_WORD = "אישור"

#: Fields a family's operation may carry even though they look private. Exactly
#: one door, opened deliberately: changing a phone number is a thing the spec
#: asks for, and it cannot be done without the number. Everything else stays
#: stripped, including on this operation.
#:
#: `set` is the same door under the name the live bridge uses. This house
#: declares `operations: ["set"]` on every user and decides what is being set
#: from the payload, so keying the door to `set_phone` alone would mean the one
#: allowed field could never arrive. It is still one field, on one family.
PRIVATE_FIELDS_ALLOWED: dict[tuple[str, str], frozenset[str]] = {
    ("users", "set_phone"): frozenset({"phone"}),
    ("users", "set"): frozenset({"phone"}),
}


def allowed_private_fields(resource: str, operation: str) -> frozenset[str]:
    return PRIVATE_FIELDS_ALLOWED.get((resource, operation), frozenset())


def _invalid(
    resource: str, operation: str, resource_id: str | None, title: str, *errors: FieldError
) -> PreviewResponse:
    from app.services.manage import _now

    return PreviewResponse(
        preview_id="",
        operation=operation,
        resource_type=resource,
        resource_id=resource_id,
        title=title,
        valid=False,
        errors=list(errors),
        expires_at=_now().isoformat(),
    )


def _title(resource: str, operation: str, item: ManagedItem | None) -> str:
    spec = SPECS[resource]
    base = spec.titles.get(operation, f"שינוי ב{spec.label}")
    return f"{base} — {item.label}" if item else base


def find_item(snapshot: ResourceSnapshot, resource_id: str | None) -> ManagedItem | None:
    if resource_id is None:
        return None
    return next((item for item in snapshot.items if item.id == resource_id), None)


def observed_from(item: ManagedItem | None) -> ObservedState:
    """What the commit will send back as `expected_*`.

    Only scalars: a nested structure could not be compared field-by-field on the
    Home Assistant side anyway, and half a comparison is worse than none.
    """
    if item is None:
        return ObservedState(resource_id=None, label=None, values={})
    values: dict[str, Any] = {"value": item.value}
    for key, value in item.detail.items():
        if isinstance(value, str | int | float | bool):
            values[key] = value
    return ObservedState(resource_id=item.id, label=item.label, values=values)


# --- the four rules of our own ----------------------------------------------
def _admin_ids(snapshot: ResourceSnapshot) -> set[str]:
    """Everyone currently both enabled and an admin, by the bridge's reckoning."""
    admins: set[str] = set()
    for item in snapshot.items:
        role = str(item.detail.get("role") or "").lower()
        enabled = item.detail.get("enabled")
        if enabled is None:
            enabled = item.value
        if role == "admin" and bool(enabled):
            admins.add(item.id)
    return admins


def last_admin_error(
    snapshot: ResourceSnapshot, operation: str, resource_id: str | None, payload: dict[str, Any]
) -> FieldError | None:
    """Refuse the change that would leave the household with no administrator.

    Checked before a preview exists, so the refusal never becomes a token that
    something else could commit. Home Assistant checks again and is the
    authority; this is the earlier and more explicable of the two refusals.
    """
    admins = _admin_ids(snapshot)
    if resource_id not in admins:
        return None

    removes_admin = (
        operation == "disable"
        or (operation == "set_role" and str(payload.get("role") or "").lower() != "admin")
        # `set` is the verb the live bridge actually declares on users, and what
        # it sets is in the payload rather than in the name. A guard that reads
        # only the verb would have let the identical change through under the
        # one name Home Assistant uses — so it reads the payload: a role that is
        # not admin, or a value being switched off, is the same removal that
        # `set_role` and `disable` used to spell out.
        or (
            operation == "set"
            and "role" in payload
            and str(payload.get("role") or "").lower() != "admin"
        )
        or (operation == "set" and "value" in payload and not payload.get("value"))
    )
    if not removes_admin:
        return None
    if len(admins) > 1:
        return None
    return FieldError(
        field=None,
        code="last_admin",
        message=(
            "זה המנהל היחיד שנותר. צריך למנות מנהל נוסף לפני שמשביתים או משנים "
            "את ההרשאה של זה."
        ),
    )


def device_capability_error(item: ManagedItem, payload: dict[str, Any]) -> FieldError | None:
    """Refuse a control the bridge did not advertise for this device.

    `capabilities` is the bridge's list. A request naming something outside it
    is not passed along in the hope that Home Assistant will sort it out: this
    application does not ask for things it was not offered.
    """
    capabilities = item.detail.get("capabilities")
    wanted = payload.get("capability")
    if wanted is None:
        return None
    if not isinstance(capabilities, list) or str(wanted) not in [str(c) for c in capabilities]:
        return FieldError(
            field="capability",
            code="unsupported_capability",
            message=f"המכשיר {item.label} אינו תומך בפעולה הזו",
        )
    return None


def conflicts_of(item: ManagedItem | None, snapshot: ResourceSnapshot) -> list[dict[str, Any]]:
    """Conflicts the bridge reported, if it reported any.

    Bobi owns rule parsing and conflict detection; nothing here re-implements
    it. This only surfaces what came back, and blocks when the bridge said the
    conflict is blocking.
    """
    raw = None
    if item is not None:
        raw = item.detail.get("conflicts")
    if raw is None:
        raw = snapshot.detail.get("conflicts")
    if not isinstance(raw, list):
        return []
    return [entry for entry in raw if isinstance(entry, dict)]


def blocking_conflict(conflicts: list[dict[str, Any]]) -> FieldError | None:
    for conflict in conflicts:
        if conflict.get("blocking"):
            message = conflict.get("message") or "האוטומציה מתנגשת עם אוטומציה קיימת"
            return FieldError(field=None, code="conflict", message=str(message))
    return None


# --- the description --------------------------------------------------------
def describe(
    resource: str,
    operation: str,
    resource_id: str | None,
    payload: dict[str, Any],
    snapshot: ResourceSnapshot,
) -> PreviewResponse:
    """One change, described — or refused with a reason a person can act on."""
    from app.services.manage import _now

    spec = SPECS[resource]
    item = find_item(snapshot, resource_id)
    creating = operation in spec.creating
    title = _title(resource, operation, item)

    if operation not in spec.operations:
        return _invalid(
            resource,
            operation,
            resource_id,
            title,
            FieldError(field=None, code="unsupported", message="הפעולה הזו אינה נתמכת"),
        )

    # First, before anything else — including before asking whether the item
    # exists. A restart, a Supervisor update or a wholesale restore is refused
    # for being what it is, not for being absent from a snapshot: a bridge that
    # started advertising one tomorrow would meet the same answer today's
    # "not found" would quietly stop giving.
    if resource == "system":
        action = resource_id or str(payload.get("action_id") or "")
        if is_forbidden_system_action(action):
            return _invalid(
                resource,
                operation,
                resource_id,
                title,
                FieldError(
                    field=None,
                    code="forbidden_action",
                    message=(
                        "פעולה מסוג זה לא מתבצעת מהאתר. אם היא נחוצה, בצעו אותה "
                        "ישירות ב-Home Assistant."
                    ),
                ),
            )

    if not creating:
        if item is None:
            return _invalid(
                resource,
                operation,
                resource_id,
                title,
                FieldError(
                    field="resource_id",
                    code="not_found",
                    message="הפריט הזה לא נמצא. ייתכן שהוא נמחק — רעננו את הנתונים.",
                ),
            )
        # Fail closed twice over: the bridge has to have marked the item
        # controllable *and* to have named this operation on it.
        if not item.controllable or operation not in item.operations:
            return _invalid(
                resource,
                operation,
                resource_id,
                title,
                FieldError(
                    field=None,
                    code="not_controllable",
                    message=item.unavailable_reason or f"אי אפשר לשנות את {item.label} מכאן",
                ),
            )

    errors: list[FieldError] = []
    changes: list[ChangeField] = []
    explanation: str | None = None
    risk = (item.risk if item else spec.default_risk) or spec.default_risk

    # --- the family rules ---
    if resource == "users":
        if (error := last_admin_error(snapshot, operation, resource_id, payload)) is not None:
            errors.append(error)
        # Rated on what is changing, not on what the verb is called. A phone
        # number arriving under `set` is exactly as sensitive as one arriving
        # under `set_phone`, and only one of those names is the live bridge's.
        if operation == "set_phone" or "phone" in payload:
            risk = "high"

    if resource == "calendar" and creating:
        # Creating is the only calendar write Home Assistant exposes to a
        # script — there is no service that deletes or updates an event — so
        # this is the one calendar payload worth checking, and it is checked
        # here rather than left to the bridge: a preview that shows an event
        # with no time is a confirmation of nothing.
        for field, label in (("summary", "כותרת"), ("start", "התחלה"), ("end", "סיום")):
            if not str(payload.get(field) or "").strip():
                errors.append(
                    FieldError(field=field, code="required", message=f"חסר {label} לאירוע.")
                )
        if not str(payload.get("user_id") or "").strip():
            errors.append(
                FieldError(field="user_id", code="required", message="צריך לבחור יומן.")
            )

    if resource == "devices" and item is not None:
        error = device_capability_error(item, payload)
        if error is not None:
            errors.append(error)

    conflicts = conflicts_of(item, snapshot) if resource == "rules" else []
    if (error := blocking_conflict(conflicts)) is not None:
        errors.append(error)

    # --- the value being asked for ---
    wanted = payload.get("value")
    if operation == "enable":
        wanted = True
    elif operation == "disable":
        wanted = False

    if item is not None and wanted is not None:
        if resource == "devices" and operation in DEVICE_SWITCH_OPERATIONS:
            # A switch, not the item's published value. See
            # `DEVICE_SWITCH_OPERATIONS` for why the item's own limits do not
            # apply here — and note that the value is still checked, against
            # what a switch can actually hold.
            if not isinstance(wanted, bool):
                errors.append(
                    FieldError(
                        field="value",
                        code="invalid",
                        message="הערך צריך להיות פעיל או כבוי",
                    )
                )
        else:
            for code, message in constraint_errors(item, wanted):
                errors.append(FieldError(field="value", code=code, message=message))

    if errors:
        return _invalid(resource, operation, resource_id, title, *errors)

    # --- the rows the dialog shows ---
    if item is not None:
        changes.append(ChangeField(label="פריט", before=item.label, after=item.label))
        if wanted is not None:
            changes.append(
                ChangeField(
                    label=item.label,
                    before=humanise(item.value, item),
                    after=humanise(wanted, item),
                )
            )

    for key, value in payload.items():
        if key in ("value", "capability"):
            continue
        shown = mask_phone(value) if "phone" in key.lower() else humanise(value)
        before = None
        if item is not None and key in item.detail:
            raw_before = item.detail[key]
            before = mask_phone(raw_before) if "phone" in key.lower() else humanise(raw_before)
        changes.append(ChangeField(label=_FIELD_LABELS.get(key, key), before=before, after=shown))

    destructive = operation in spec.destructive
    explanation = _explain(resource, operation, item, conflicts, payload)

    return PreviewResponse(
        preview_id="",
        operation=operation,
        resource_type=resource,
        resource_id=resource_id,
        title=title,
        changes=changes,
        explanation=explanation,
        destructive=destructive,
        risk="destructive" if destructive else risk,
        warning=_warn(resource, operation, destructive, risk),
        confirm_word=_confirm_word(risk, destructive),
        confirm_label=spec.titles.get(operation, "בצע שינוי"),
        expires_at=_now().isoformat(),
    )


#: Hebrew for the structured fields the families send. A key with no entry here
#: is shown under its own name rather than hidden — an unlabelled row a person
#: can still read beats a change they cannot see.
_FIELD_LABELS = {
    "role": "הרשאה",
    "name": "שם תצוגה",
    "label": "שם",
    "phone": "טלפון",
    "summary": "כותרת",
    "days": "ימים",
    "time": "שעה",
    "start": "התחלה",
    "end": "סיום",
    "location": "מיקום",
    "description": "תיאור",
    "next_due": "מועד הבא",
    "end_date": "תאריך סיום",
    "action": "פעולה",
    "user_id": "משתמש",
    "members": "מכשירים",
    "temperature": "טמפרטורה",
    "scope": "היקף",
}


def _explain(
    resource: str,
    operation: str,
    item: ManagedItem | None,
    conflicts: list[dict[str, Any]],
    payload: dict[str, Any] | None = None,
) -> str | None:
    if resource == "shabbat":
        # Said out loud in the dialog, because it is the question a person asks
        # when a screen full of device names has a save button under it.
        return (
            "זו עריכה של לוח הזמנים בלבד. שום מכשיר לא יידלק ולא יכובה עכשיו — "
            "השינוי ייכנס לתוקף בשבת הקרובה."
        )
    if resource == "rules" and conflicts:
        notes = "؛ ".join(
            str(entry.get("message", "")) for entry in conflicts if entry.get("message")
        )
        return f"בובי מצא חפיפה עם אוטומציה קיימת: {notes}" if notes else None
    if resource == "devices":
        return "הפעולה תישלח למכשיר, ובובי יקרא את המצב בחזרה כדי לוודא שהיא נקלטה."
    if resource == "users" and (operation == "set_phone" or "phone" in (payload or {})):
        return "המספר יישמר אצל בובי בלבד ולא יוצג במלואו באתר."
    if resource == "system":
        return item.description if item else None
    if resource == "calendar" and operation == "create":
        return (
            "האירוע ייווצר ביומן שנבחר. שינוי או מחיקה של אירוע קיים "
            "אינם אפשריים מ-Home Assistant."
        )
    if resource == "calendar" and operation == "delete":
        return "האירוע יימחק מהיומן."
    if resource == "settings":
        return "ההגדרה תשתנה אצל בובי. אפשר לשנות אותה חזרה בכל רגע."
    return None


def _confirm_word(risk: str, destructive: bool) -> str | None:
    """What the user must type, or `None` when a button is enough."""
    if destructive:
        return DESTRUCTIVE_CONFIRM_WORD
    if needs_confirm_word(risk, destructive):
        return SENSITIVE_CONFIRM_WORD
    return None


def _warn(resource: str, operation: str, destructive: bool, risk: str) -> str | None:
    if destructive:
        return "פעולה זו אינה הפיכה."
    if rank(risk) >= rank("high"):
        return "זו פעולה רגישה. ודאו שזה מה שהתכוונתם לעשות."
    return None
