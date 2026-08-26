"""The managed families, and the one rule each of them adds.

Phase 3A hard-coded tasks and features because Home Assistant had published
exactly those two contracts. Version 3.0 manages eight more, and hard-coding
them would mean inventing eight contracts that Home Assistant has not written
yet. So the shape of every family lives here as a small declaration — which
bridge services it uses, which operations exist, which of them destroy
something — and everything else is read from the bridge at runtime.

That is not a shortcut. It is the only honest option: this application cannot
know which four features a household has, which devices are dimmable, or what
the Shabbat profile list looks like, and a screen that guessed would be lying.
The bridge says; this module renders and refuses.

## What is *not* generic

Four rules are the application's own, and they are enforced here whatever the
bridge says, because getting them wrong is expensive and a bridge that has not
shipped cannot be relied on to catch them:

* **A household never runs out of admins.** Disabling or demoting the last
  enabled admin is refused before a preview exists.
* **A phone number is never shown in full**, and never travels into the audit
  trail.
* **Saving a Shabbat profile touches no device.** It edits a schedule.
* **A control the bridge did not advertise is not offered**, and asking for one
  anyway is refused rather than passed along.

Home Assistant re-checks all of these. Neither side relies on the other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models.manage import (
    ManagedConstraints,
    ManagedItem,
)

#: The families 3.0 manages. `tasks` and `features` keep their Phase 3A
#: implementations untouched; the rest are driven by the declarations below.
RESOURCE_IDS = (
    "tasks",
    "features",
    "settings",
    "users",
    "shabbat",
    "rules",
    "calendar",
    "devices",
    "system",
)

#: Operations, per family. A closed set on both sides: the bridge declares which
#: of these it supports, and anything it omits is never offered. An operation
#: absent from this tuple cannot be requested at all, whatever a contract says —
#: a new verb has to be added here, deliberately, with a describer to match.
SETTINGS_OPERATIONS = ("set",)
USER_OPERATIONS = ("enable", "disable", "set_role", "rename", "set_phone")
SHABBAT_OPERATIONS = ("set_timing", "set_membership", "set_temperature")
RULE_OPERATIONS = ("create", "edit", "enable", "disable", "delete")
CALENDAR_OPERATIONS = ("create", "edit", "move", "delete")
DEVICE_OPERATIONS = ("set",)
SYSTEM_OPERATIONS = ("run",)

#: Risk words, weakest first. The UI escalates its confirmation with the rank,
#: and `read_only` never gets a write control at all.
RISK_ORDER = ("read_only", "low", "medium", "high", "destructive")

#: Risks that demand the typed confirmation word rather than a button.
STRONG_RISKS = frozenset({"high", "destructive"})


@dataclass(frozen=True)
class ResourceSpec:
    """One managed family, and the services behind it."""

    id: str
    #: Hebrew, for headings and audit lines.
    label: str
    #: `script.bobi_cc_*`, without the domain. `None` for a family whose reads
    #: come from somewhere else — devices reuse the Phase 2 read service.
    snapshot_service: str | None
    commit_service: str | None
    operations: tuple[str, ...]
    #: Operations that remove something a person cannot get back.
    destructive: frozenset[str] = frozenset()
    #: The commit field carrying the target's canonical id. Named per family so
    #: the bridge reads what it expects — `uid`, `feature_id`, `device_id`.
    id_field: str = "resource_id"
    #: Operations that create something, and so have no existing target.
    creating: frozenset[str] = frozenset()
    #: The default risk of an operation the contract did not rate.
    default_risk: str = "low"
    #: Hebrew titles per operation, for the preview heading.
    titles: dict[str, str] = field(default_factory=dict)


SPECS: dict[str, ResourceSpec] = {
    "settings": ResourceSpec(
        id="settings",
        label="הגדרות בובי",
        snapshot_service="bobi_cc_settings_snapshot",
        commit_service="bobi_cc_settings_commit",
        operations=SETTINGS_OPERATIONS,
        id_field="setting_id",
        titles={"set": "שינוי הגדרה"},
    ),
    "users": ResourceSpec(
        id="users",
        label="משתמשים והרשאות",
        snapshot_service="bobi_cc_users_manage_snapshot",
        commit_service="bobi_cc_users_commit",
        operations=USER_OPERATIONS,
        id_field="user_id",
        default_risk="medium",
        titles={
            "enable": "הפעלת משתמש",
            "disable": "השבתת משתמש",
            "set_role": "שינוי הרשאה",
            "rename": "שינוי שם תצוגה",
            "set_phone": "שינוי מספר טלפון",
        },
    ),
    "shabbat": ResourceSpec(
        id="shabbat",
        label="שעון שבת",
        snapshot_service="bobi_cc_shabbat",
        commit_service="bobi_cc_shabbat_commit",
        operations=SHABBAT_OPERATIONS,
        id_field="profile_id",
        titles={
            "set_timing": "שינוי תזמון שבת",
            "set_membership": "שינוי מכשירים בפרופיל",
            "set_temperature": "שינוי טמפרטורת מזגן בפרופיל",
        },
    ),
    "rules": ResourceSpec(
        id="rules",
        label="אוטומציות",
        snapshot_service="bobi_cc_rules",
        commit_service="bobi_cc_rule_commit",
        operations=RULE_OPERATIONS,
        destructive=frozenset({"delete"}),
        creating=frozenset({"create"}),
        id_field="rule_id",
        titles={
            "create": "יצירת אוטומציה",
            "edit": "עריכת אוטומציה",
            "enable": "הפעלת אוטומציה",
            "disable": "השבתת אוטומציה",
            "delete": "מחיקת אוטומציה",
        },
    ),
    "calendar": ResourceSpec(
        id="calendar",
        label="יומן",
        snapshot_service="bobi_cc_calendar_snapshot",
        commit_service="bobi_cc_calendar_commit",
        operations=CALENDAR_OPERATIONS,
        destructive=frozenset({"delete"}),
        creating=frozenset({"create"}),
        id_field="event_uid",
        titles={
            "create": "יצירת אירוע",
            "edit": "עריכת אירוע",
            "move": "העברת אירוע",
            "delete": "מחיקת אירוע",
        },
    ),
    "devices": ResourceSpec(
        id="devices",
        label="מכשירים",
        snapshot_service="bobi_cc_devices",
        commit_service="bobi_cc_device_commit",
        operations=DEVICE_OPERATIONS,
        id_field="device_id",
        titles={"set": "שינוי מצב מכשיר"},
    ),
    "system": ResourceSpec(
        id="system",
        label="מערכת",
        snapshot_service="bobi_cc_system_snapshot",
        commit_service="bobi_cc_system_commit",
        operations=SYSTEM_OPERATIONS,
        id_field="action_id",
        default_risk="medium",
        titles={"run": "הרצת פעולת מערכת"},
    ),
}

#: Every service the 3.0 families may reach. Read and write are separated so the
#: adapter can keep refusing a write service outside `apply()`.
RESOURCE_READ_SERVICES = frozenset(
    spec.snapshot_service for spec in SPECS.values() if spec.snapshot_service
)
RESOURCE_WRITE_SERVICES = frozenset(
    spec.commit_service for spec in SPECS.values() if spec.commit_service
)

#: System actions this application refuses to ask for, whatever a future
#: contract advertises. Restarting Home Assistant, updating the Supervisor,
#: deleting an integration or a device, restoring a backup wholesale and
#: anything shell-shaped are outside what a household web page should be able to
#: start — and a bridge that started offering them would be a bridge to argue
#: with, not to obey. Matching is on the substring, so a prefixed variant of a
#: forbidden name is caught too.
FORBIDDEN_SYSTEM_ACTIONS = (
    "ha_restart",
    "core_restart",
    "host_reboot",
    "host_shutdown",
    "supervisor_update",
    "supervisor_restart",
    "integration_delete",
    "integration_remove",
    "device_delete",
    "device_remove",
    "entity_delete",
    "backup_restore",
    "restore_backup",
    "factory_reset",
    "shell",
    "exec",
)


def is_forbidden_system_action(action_id: str) -> bool:
    """Whether this action is one no web page may start.

    Checked before a preview exists, so a forbidden action never reaches the
    stage of having a token that could commit it.
    """
    name = action_id.strip().lower()
    return any(banned in name for banned in FORBIDDEN_SYSTEM_ACTIONS)


def mask_phone(value: object) -> str:
    """A phone number as a screen may see it.

    Enough to recognise which number it is, never enough to dial it or to
    identify anyone from a shared screenshot. Applied to anything the bridge
    hands over as already-masked too: a key called `phone_masked` is a claim,
    and re-masking a value that was already masked costs nothing while trusting
    one that was not would cost a phone number.
    """
    digits = [character for character in str(value) if character.isdigit()]
    if len(digits) < 4:
        return "•" * len(digits)
    return "•••• ••• " + "".join(digits[-2:])


def rank(risk: str | None) -> int:
    """Where a risk word sits in the escalation, unknown counting as high.

    An unrecognised rating is treated as more dangerous rather than less: a
    bridge inventing a new word should not thereby get a quieter dialog.
    """
    try:
        return RISK_ORDER.index(risk or "")
    except ValueError:
        return RISK_ORDER.index("high")


def needs_confirm_word(risk: str | None, destructive: bool) -> bool:
    return destructive or rank(risk) >= rank("high")


# --- values, rendered -------------------------------------------------------
def humanise(value: Any, item: ManagedItem | None = None) -> str:
    """One canonical value as a person reads it.

    Falls back to the raw text rather than to an empty string: a value this
    module does not recognise is still a value the household can see, and
    hiding it would be the worse failure.
    """
    if value is None:
        return "לא ידוע"
    if isinstance(value, bool):
        return "פעיל" if value else "כבוי"
    if item is not None:
        for option in item.options:
            if str(option.value) == str(value):
                return option.label
        unit = item.constraints.unit if item.constraints else None
        if unit and isinstance(value, int | float):
            return f"{_number(value)}{unit}"
    if isinstance(value, int | float):
        return _number(value)
    if isinstance(value, list):
        return "، ".join(str(part) for part in value) if value else "ריק"
    return str(value)


def _number(value: float) -> str:
    """Whole numbers without a trailing `.0`, which reads as a typo."""
    return str(int(value)) if float(value).is_integer() else str(value)


def constraint_errors(item: ManagedItem, value: Any) -> list[tuple[str, str]]:
    """Every published limit this value breaks, as (code, Hebrew message).

    Only limits the bridge actually published are checked. An item with no
    `maximum` is not treated as unbounded — Home Assistant checks its own
    limits again, and this is the earlier, friendlier of the two refusals.
    """
    limits: ManagedConstraints | None = item.constraints
    errors: list[tuple[str, str]] = []

    if item.kind == "choice" and item.options:
        allowed = {str(option.value) for option in item.options}
        if str(value) not in allowed:
            labels = "، ".join(option.label for option in item.options)
            errors.append(("not_allowed", f"אפשר לבחור רק אחת מהאפשרויות: {labels}"))
        return errors

    if item.kind == "toggle" and not isinstance(value, bool):
        errors.append(("invalid", "הערך צריך להיות פעיל או כבוי"))
        return errors

    if limits is None:
        return errors

    if item.kind in ("number",):
        if not isinstance(value, int | float) or isinstance(value, bool):
            errors.append(("invalid", "הערך צריך להיות מספר"))
            return errors
        if limits.minimum is not None and value < limits.minimum:
            errors.append(("too_low", f"הערך המזערי הוא {_number(limits.minimum)}"))
        if limits.maximum is not None and value > limits.maximum:
            errors.append(("too_high", f"הערך המרבי הוא {_number(limits.maximum)}"))
        # A step the value does not sit on is a value the device cannot hold,
        # so it is refused here rather than silently rounded — rounding would
        # commit something other than what the dialog showed.
        if limits.step:
            base = limits.minimum if limits.minimum is not None else 0
            offset = (value - base) / limits.step
            if abs(offset - round(offset)) > 1e-6:
                errors.append(("bad_step", f"הערך חייב לעלות בקפיצות של {_number(limits.step)}"))

    if (
        item.kind == "text"
        and limits.max_length is not None
        and len(str(value)) > limits.max_length
    ):
        errors.append(("too_long", f"הטקסט ארוך מדי (עד {limits.max_length} תווים)"))

    if item.kind == "list" and limits.allowed:
        allowed = {str(option.value) for option in limits.allowed}
        unknown = [str(part) for part in (value or []) if str(part) not in allowed]
        if unknown:
            errors.append(
                ("not_allowed", f"המכשירים האלה אינם חלק מהפרופיל: {'، '.join(unknown)}")
            )

    return errors
