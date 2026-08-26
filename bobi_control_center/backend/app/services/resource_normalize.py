"""Bridge payloads → one canonical snapshot shape.

The same rule as everywhere else in this codebase: this is the only layer that
knows the bridge's field names, and it never raises on a missing or odd one. A
family whose bridge has not shipped answers `available: false` with a Hebrew
reason, and the screen says so — which is the honest result, not a degraded one.

Two things are enforced here rather than trusted:

* **Fail closed on operability.** `controllable` absent means *not* operable,
  and an item with no operations is read-only however interesting it looks. A
  bridge has to say yes; silence is no.
* **No raw entity id reaches a client.** Anything shaped like one — a key named
  `entity_id`, or a value like `light.kitchen` — is dropped from the extras a
  screen receives. The management path speaks canonical Bobi ids only, so a
  React component cannot learn a name it could call a service with even if it
  wanted to.
"""

from __future__ import annotations

import re
from typing import Any

from app.models.manage import (
    ITEM_KINDS,
    ManagedConstraints,
    ManagedGroup,
    ManagedItem,
    ManagedOption,
    ResourceSnapshot,
)
from app.services import normalize
from app.services.resources import DEVICE_SWITCH_OPERATIONS, humanise, mask_phone

#: `domain.object_id` — a Home Assistant entity id. Matched on the value as
#: well as the key, because a bridge could hand one over under any name.
_ENTITY_ID = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")

#: Keys never passed on, whatever a bridge sends. Phone numbers, LIDs and chat
#: ids belong to the household, not to a web page; tokens belong to nobody.
_PRIVATE_KEYS = (
    "phone",
    "lid",
    "jid",
    "wa_id",
    "chat_id",
    "number",
    "token",
    "secret",
    "password",
    "entity_id",
    "entity_ids",
    "service",
)

#: Keys consumed into the item's own fields, so they do not repeat in `detail`.
_ITEM_KEYS = {
    "id",
    "key",
    "label",
    "name",
    "title",
    "group",
    "section",
    "kind",
    "type",
    "value",
    "state",
    "display",
    "description",
    "detail",
    "risk",
    "controllable",
    "operations",
    "options",
    "constraints",
    "limits",
    "unavailable_reason",
    "reason",
}

#: Consumed into the snapshot's own fields. `items` and `groups` matter most:
#: they hold the raw entries, and copying them into the snapshot's extras would
#: carry every private field past the per-item redaction that just removed it.
_SNAPSHOT_KEYS = {
    "items",
    "groups",
    "available",
    "supported",
    "bridge_available",
    "reason",
    "detail",
    "writes_enabled",
}


#: Keys whose value the bridge has already reduced to something non-identifying
#: — `phone_masked` is the one that matters. They survive the private-key filter
#: they would otherwise trip on, and their value is masked again here rather
#: than trusted: the suffix is a claim, and a claim is not a guarantee.
_MASKED_SUFFIX = "_masked"


def _private(key: str) -> bool:
    if key.lower().endswith(_MASKED_SUFFIX):
        return False
    return any(private in key.lower() for private in _PRIVATE_KEYS)


def safe_detail(payload: dict[str, Any]) -> dict[str, Any]:
    """The extras a screen may see: no secrets, no entity ids.

    Values are copied as they are — a rule's days, an event's start — except
    that anything shaped like an entity id is dropped rather than masked: a
    masked one still tells a reader the domain.

    The filtering recurses through dicts **and through dicts inside lists**. It
    did not, once, and a snapshot's own extras carried the entire raw item list
    — phone numbers included — straight past a per-item redaction that was
    working perfectly. Anything that only checks the top level of a structure
    is checking the one level the data was not hiding in.
    """
    safe: dict[str, Any] = {}
    for key, value in payload.items():
        if key in _ITEM_KEYS or _private(key):
            continue
        if key.lower().endswith(_MASKED_SUFFIX):
            safe[key] = mask_phone(value)
            continue
        cleaned = _safe_value(value)
        if cleaned is _DROP:
            continue
        safe[key] = cleaned
    return safe


#: Distinguishes "this value must not be passed on" from a legitimate `None`.
_DROP = object()


def _safe_value(value: Any) -> Any:
    if isinstance(value, str):
        return _DROP if _ENTITY_ID.match(value) else value
    if isinstance(value, dict):
        return safe_detail(value)
    if isinstance(value, list):
        cleaned = [_safe_value(part) for part in value]
        return [part for part in cleaned if part is not _DROP]
    return value


def _options(value: Any) -> list[ManagedOption]:
    """The choices a bridge published, however it published them.

    `[{"value": "auto", "label": "אוטומטי"}]` is the documented shape, but a
    bare `["auto", "low", "high"]` is what a bridge naturally sends when Home
    Assistant already holds the list — `hvac_modes`, `fan_modes`, `preset_modes`
    are all plain string lists. The coercion below drops anything that is not a
    dict, so those arrived as *no options at all*: a choice control with nothing
    to choose, and every value refused for not being among them.
    """
    if isinstance(value, list):
        value = [
            item if isinstance(item, dict) else {"value": item}
            for item in value
            if item is not None
        ]
    options: list[ManagedOption] = []
    for item in normalize._as_items(value, id_key="value"):
        token = normalize._text(normalize._first(item, "value", "id", "key"))
        if token is None:
            continue
        options.append(
            ManagedOption(
                value=token,
                label=normalize._text(normalize._first(item, "label", "name")) or token,
                detail=normalize._text(item.get("detail")),
            )
        )
    return options


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _constraints(payload: dict[str, Any]) -> ManagedConstraints | None:
    raw = payload.get("constraints")
    if not isinstance(raw, dict):
        raw = payload.get("limits")
    if not isinstance(raw, dict):
        return None
    limits = ManagedConstraints(
        minimum=_number(normalize._first(raw, "minimum", "min", "min_value")),
        maximum=_number(normalize._first(raw, "maximum", "max", "max_value")),
        step=_number(raw.get("step")),
        unit=normalize._text(normalize._first(raw, "unit", "unit_of_measurement")),
        max_length=(
            int(length) if (length := _number(normalize._first(raw, "max_length", "maxlength")))
            else None
        ),
        allowed=_options(normalize._first(raw, "allowed", "choices", "members")),
    )
    # An all-empty constraints block says nothing; `None` says the same thing
    # more clearly, and keeps it out of the JSON a screen has to read.
    if limits.model_dump(exclude_defaults=True):
        return limits
    return None


#: The bridge's word for a control → this application's.
#:
#: The live contract says `boolean` and `select` where the specification says
#: `toggle` and `choice`. Both are reasonable names for the same thing, and the
#: cost of not reconciling them is not an error but something worse: an
#: unrecognised kind falls through to the text editor, so a household member is
#: shown a free-text box where a switch belongs. Synonyms are cheap; a screen
#: that renders a boolean as a string is not.
_KIND_SYNONYMS = {
    "boolean": "toggle",
    "bool": "toggle",
    "switch": "toggle",
    "on_off": "toggle",
    "select": "choice",
    "enum": "choice",
    "option": "choice",
    "options": "choice",
    "numeric": "number",
    "int": "number",
    "integer": "number",
    "float": "number",
    "string": "text",
    "str": "text",
    "multi": "list",
    "members": "list",
    "timestamp": "datetime",
    "date_time": "datetime",
}


def canonical_kind(kind: str | None, value: Any, options: list[ManagedOption]) -> str:
    """One of `ITEM_KINDS`, or `readonly`.

    A kind this application does not recognise becomes `readonly` rather than
    being passed through. Rendering an unknown kind as a text field would let
    someone type a value the bridge never said it would accept; showing it as a
    reading is the honest failure.
    """
    if kind is None:
        return _infer_kind(value, options)
    name = kind.strip().lower()
    name = _KIND_SYNONYMS.get(name, name)
    if name in ITEM_KINDS:
        return name
    return _infer_kind(value, options)


#: Value shape → how it is edited, when the bridge did not say. Deliberately
#: conservative: anything unrecognised is read-only rather than guessed into an
#: editor that would send the wrong type.
def _infer_kind(value: Any, options: list[ManagedOption]) -> str:
    if options:
        return "choice"
    if isinstance(value, bool):
        return "toggle"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, list):
        return "list"
    return "readonly"


def primary_operation(kind: str, value: Any, operations: list[str]) -> str | None:
    """The declared verb that sets the value this item reports.

    Under the live vocabulary one item carries several verbs — an air
    conditioner accepts `power`, `temperature`, `fan_mode` and `swing_mode`
    while reporting a temperature — and the payload never says which of them
    produces the reported value. Taking the first name in the list would send
    `power` when someone edits a temperature: the wrong change, previewed
    honestly, and confirmed by a person who read a correct-looking dialog.

    So it is worked out from the item's own `kind`, which is the one thing that
    does describe the reported value:

    * a toggle is switched by `enable`/`disable` where the bridge named them,
      otherwise by `set`, otherwise by `power`;
    * everything else is set by `set` where it exists, and otherwise by the
      first verb that is not a switch — because a switch does not set a
      published number, choice or text.

    A guess remains a guess, and this one is checked twice more: the bridge
    still has to have named the verb on the item, and Home Assistant still
    validates the commit it receives.
    """
    if not operations:
        return None
    if kind == "action":
        # An action has no value, so there is no "verb that sets it" to work
        # out — the bridge named what may be done and the first is it.
        return operations[0]
    if kind == "toggle":
        on = value is True
        # `stop`/`start` last: a vacuum is the one device whose on and off are
        # two different verbs rather than one verb and a value.
        for candidate in (
            "disable" if on else "enable",
            "set",
            "power",
            "stop" if on else "start",
        ):
            if candidate in operations:
                return candidate
    if "set" in operations:
        return "set"
    for operation in operations:
        if operation not in DEVICE_SWITCH_OPERATIONS:
            return operation
    return operations[0]


def _item(payload: dict[str, Any], *, default_group: str | None = None) -> ManagedItem | None:
    identifier = normalize._text(normalize._first(payload, "id", "key"))
    if identifier is None:
        return None

    label = normalize._text(normalize._first(payload, "label", "name", "title"))
    options = _options(normalize._first(payload, "options", "choices"))
    value = normalize._first(payload, "value", "state")
    kind = canonical_kind(
        normalize._text(normalize._first(payload, "kind", "type")), value, options
    )

    operations = normalize._str_list(payload.get("operations"))
    # Fail closed: a bridge that does not say an item is controllable has not
    # said it is, and an item with nothing to do to it cannot be operated.
    controllable = bool(normalize._bool(payload.get("controllable"))) and bool(operations)

    constraints = _constraints(payload)
    item = ManagedItem(
        id=identifier,
        label=label or identifier,
        group=normalize._text(normalize._first(payload, "group", "section")) or default_group,
        kind=kind,
        value=value,
        description=normalize._text(payload.get("description")),
        risk=normalize._text(payload.get("risk")) or ("low" if controllable else "read_only"),
        controllable=controllable,
        operations=operations,
        primary_operation=primary_operation(kind, value, operations) if controllable else None,
        options=options,
        constraints=constraints,
        unavailable_reason=normalize._text(
            normalize._first(payload, "unavailable_reason", "reason")
        ),
        detail=safe_detail(payload),
    )
    item.display = normalize._text(payload.get("display")) or humanise(value, item)
    return item


def normalize_resource(resource: str, payload: dict[str, Any]) -> ResourceSnapshot:
    """One family's bridge payload → the envelope every screen reads.

    Groups may arrive nested (`groups: [{items: […]}]`) or flat (`items: […]`)
    and both produce the same result: a flat list for logic, and grouped cards
    for the screen.
    """
    available = normalize._bool(
        normalize._first(payload, "available", "supported", "bridge_available")
    )
    items: list[ManagedItem] = []
    groups: list[ManagedGroup] = []

    for raw_group in normalize._as_items(payload.get("groups")):
        group_id = normalize._text(normalize._first(raw_group, "id", "key"))
        if group_id is None:
            continue
        members = [
            item
            for entry in normalize._as_items(raw_group.get("items"))
            if (item := _item(entry, default_group=group_id))
        ]
        items.extend(members)
        groups.append(
            ManagedGroup(
                id=group_id,
                label=normalize._text(normalize._first(raw_group, "label", "name")) or group_id,
                description=normalize._text(raw_group.get("description")),
                items=members,
            )
        )

    loose = [item for entry in normalize._as_items(payload.get("items")) if (item := _item(entry))]
    items.extend(loose)
    # Ungrouped items still need somewhere to render, and one titled card is
    # kinder than a heading-less list floating above the grouped ones.
    if loose:
        groups.append(ManagedGroup(id="_", label="כללי", items=loose))

    return ResourceSnapshot(
        resource=resource,
        # An empty answer from a service that does exist is still an answer:
        # available stays true and the screen shows "nothing to manage here".
        available=bool(available) if available is not None else bool(items or groups),
        reason=normalize._text(normalize._first(payload, "reason", "detail")),
        writes_enabled=bool(normalize._bool(payload.get("writes_enabled"))),
        groups=groups,
        items=items,
        detail=safe_detail(
            {key: value for key, value in payload.items() if key not in _SNAPSHOT_KEYS}
        ),
    )


def unavailable(resource: str, reason: str) -> ResourceSnapshot:
    """The answer for a family whose bridge is not there yet."""
    return ResourceSnapshot(resource=resource, available=False, reason=reason)
