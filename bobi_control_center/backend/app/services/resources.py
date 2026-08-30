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
    "lists",
    "vouchers",
    "settings",
    "users",
    "shabbat",
    "rules",
    "calendar",
    "devices",
    "helpers",
    "automations",
    "scripts",
    "scenes",
    "system",
)

#: Operations, per family. A closed set on both sides: the bridge declares which
#: of these it supports, and anything it omits is never offered. An operation
#: absent from this tuple cannot be requested at all, whatever a contract says —
#: a new verb has to be added here, deliberately, with a describer to match.
SETTINGS_OPERATIONS = ("set",)
#: `set` is here beside the granular verbs, and it is the one the live bridge
#: actually declares. This house publishes `operations: ["set"]` on every user,
#: every setting and every Shabbat row: its model is that a family is a list of
#: items each holding a value, and `set` sets it. The granular names below were
#: this application's idea, not Home Assistant's, and a verb only one side knows
#: is dropped by the closed-set filter — which is how `users` and `shabbat`
#: came back from a live contract fully described and entirely read-only.
#:
#: They are kept rather than replaced because they are more precise where a
#: bridge does offer them, and because dropping them would break the tasks and
#: features path that already speaks them. What `set` means is decided by the
#: payload, and the rules that used to key off the verb — the last-admin guard,
#: the phone door — now read the payload instead.
#: The household's own lists — shopping, recipes, reminders, the family list.
#:
#: These are separate from `tasks`, which is one specific list published by
#: `bobi_cc_task_snapshot` and addressed per household member. A list here is a
#: *group*, and its entries are the items; the bridge decides which lists exist
#: and this side never names a `todo.*` entity.
#:
#: Which lists appear is emphatically the bridge's call, and the reason matters:
#: this house has eighteen `todo` lists and only about half are for people. The
#: rest are Bobi's own machinery — a 338-entry activity log, a multimodal
#: context store keyed by chat id, a WhatsApp outbox. Publishing "every list"
#: would put a conversation log carrying phone numbers on a family screen.
LIST_OPERATIONS = ("create", "set", "complete", "reopen", "delete")
#: A voucher is a *reading* with two things you can do to it: say it has been
#: used, and throw it away. There is deliberately no `create` and no `set` —
#: a voucher is created by photographing one into WhatsApp, where Bobi reads
#: the provider, the item, the expiry and the code off the picture at a stated
#: confidence. A web form that let someone type a voucher by hand would be a
#: second, worse source of truth for the same object.
VOUCHER_OPERATIONS = ("complete", "reopen", "delete")
USER_OPERATIONS = ("set", "enable", "disable", "set_role", "rename", "set_phone")
SHABBAT_OPERATIONS = ("set", "set_timing", "set_membership", "set_temperature")
RULE_OPERATIONS = ("create", "edit", "enable", "disable", "delete")
CALENDAR_OPERATIONS = ("create", "edit", "move", "delete")
#: A device capability, named as the verb. The live `bobi_cc_devices` snapshot
#: declares `operations: ["power"]` on a socket and `["power", "temperature",
#: "fan_mode", "swing_mode"]` on an air conditioner — one verb per thing the
#: device can actually do — where this application had only `set`. Each of them
#: sets one capability to the value in the payload.
#:
#: This is still a closed set. A verb outside it is refused, and a verb inside
#: it is offered only where the bridge named it *on that item*, so a device that
#: cannot dim is never shown a brightness control.
DEVICE_CAPABILITY_OPERATIONS = (
    "power",
    "brightness",
    "color_temp",
    "temperature",
    #: Cool, heat, dry, fan-only. Declared by all three air conditioners in this
    #: house and by nothing on this side, so it was dropped in silence — the one
    #: capability of a climate device that is neither its power nor its target.
    "hvac_mode",
    "fan_mode",
    "fan_speed",
    "swing_mode",
    "preset_mode",
    "intensity",
    "scent",
    "timer",
    "start",
    "pause",
    "stop",
    "return_to_base",
    "locate",
)
DEVICE_OPERATIONS = ("set", *DEVICE_CAPABILITY_OPERATIONS)

#: The capability verbs that operate a switch rather than the item's own value.
#:
#: An item publishes one `kind` and one set of `constraints`, and they describe
#: the value it reports — for an air conditioner, its temperature. Once a family
#: has one verb per capability, a single item has several values of different
#: types, and only one of them is the published one. Checking `power: true`
#: against a number item's limits produces "the value must be a number", which
#: is the check being wrong rather than the request.
#:
#: So these verbs are checked as switches, and every other capability verb is
#: still checked against the limits the bridge published. Home Assistant
#: validates its own side either way; this is the earlier and friendlier of the
#: two refusals, and an earlier refusal that is wrong is worse than none.
DEVICE_SWITCH_OPERATIONS = frozenset(
    {"power", "start", "pause", "stop", "return_to_base", "locate"}
)
#: Home Assistant helpers. `set` covers every kind — the item's `kind` decides
#: what a value means — and the timer/counter verbs are named separately
#: because "start a timer" is not a value being set.
HELPER_OPERATIONS = ("set", "start", "pause", "cancel", "reset", "increment", "decrement")
#: Home Assistant automations, which are *not* Bobi's smart rules. Renaming is
#: the only edit exposed: changing triggers or actions from a web page would
#: mean either arbitrary YAML or a schema this application cannot validate.
AUTOMATION_OPERATIONS = ("enable", "disable", "trigger", "rename")
#: Scripts run with the parameters their own schema declares, and nothing else.
SCRIPT_OPERATIONS = ("run", "rename")
SCENE_OPERATIONS = ("activate", "rename")
SYSTEM_OPERATIONS = ("run",)

#: Verbs that carry no payload — the thing they name *is* the whole request.
#:
#: "Activate the film-night scene" and "run the goodnight script" say everything
#: there is to say; "rename it" and "set it to 22" do not, and a screen that
#: offered those as a single button would be sending a change nobody described.
#:
#: The distinction is published in the contract because only this side knows it,
#: and without it a screen has to guess. It guessed badly: a scene arrived as a
#: reading with `activate` named on it, and the scenes screen — a screen whose
#: entire purpose is activating scenes — offered no way to activate one. Naming
#: the arity here lets a screen draw a button for the verbs that need nothing
#: else, and keep its hands off the ones that do, without knowing what any of
#: them mean.
#:
#: `delete` belongs here — it takes no payload — and it is still not something a
#: screen should put a one-tap button on. That is a separate judgement, made
#: where the button is drawn, from the fact recorded here.
VALUELESS_OPERATIONS = frozenset(
    {
        "run",
        "activate",
        "trigger",
        "start",
        "pause",
        "stop",
        "cancel",
        "reset",
        "return_to_base",
        "locate",
        "increment",
        "decrement",
        "enable",
        "disable",
        "complete",
        "reopen",
        "delete",
    }
)

#: The verbs a toggle's switch already stands for.
#:
#: `primary_operation` picks one of these for a toggle, and which one depends on
#: the item's current value — an enabled automation names `disable`, a stopped
#: vacuum names `start`. So excluding only the verb it picked would leave the
#: other half of the same switch sitting beside it as a button: a switch that is
#: on, and a "הפעלה" button that turns it on again.
#:
#: `power`, `start` and `stop` are all here for the same reason on a vacuum,
#: whose on and off are two verbs rather than one verb and a value. What is left
#: after these — pause, return to base, locate — is the part a switch genuinely
#: cannot express.
TOGGLE_VERBS = frozenset({"enable", "disable", "set", "power", "start", "stop"})

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
    "vouchers": ResourceSpec(
        id="vouchers",
        label="ארנק השוברים",
        snapshot_service="bobi_cc_vouchers_snapshot",
        commit_service="bobi_cc_voucher_commit",
        operations=VOUCHER_OPERATIONS,
        destructive=frozenset({"delete"}),
        id_field="voucher_id",
        titles={
            "complete": "סימון כמומש",
            "reopen": "החזרה לארנק",
            "delete": "מחיקת שובר",
        },
    ),
    "lists": ResourceSpec(
        id="lists",
        label="רשימות הבית",
        snapshot_service="bobi_cc_lists_snapshot",
        commit_service="bobi_cc_list_commit",
        operations=LIST_OPERATIONS,
        destructive=frozenset({"delete"}),
        creating=frozenset({"create"}),
        id_field="item_id",
        titles={
            "create": "הוספה לרשימה",
            "set": "שינוי פריט",
            "complete": "סימון כבוצע",
            "reopen": "החזרה לרשימה",
            "delete": "מחיקה מהרשימה",
        },
    ),
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
            "set": "שינוי הגדרת משתמש",
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
            "set": "שינוי הגדרת שבת",
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
        titles={
            "set": "שינוי מצב מכשיר",
            "power": "הדלקה או כיבוי",
            "brightness": "שינוי בהירות",
            "color_temp": "שינוי גוון האור",
            "temperature": "שינוי טמפרטורה",
            "hvac_mode": "שינוי מצב הפעלה",
            "fan_mode": "שינוי עוצמת מאוורר",
            "fan_speed": "שינוי מהירות מאוורר",
            "swing_mode": "שינוי הנפה",
            "preset_mode": "שינוי מצב מוגדר",
            "intensity": "שינוי עוצמה",
            "scent": "שינוי ניחוח",
            "timer": "שינוי טיימר",
            "start": "הפעלה",
            "pause": "השהיה",
            "stop": "עצירה",
            "return_to_base": "חזרה לעמדת הטעינה",
            "locate": "איתור המכשיר",
        },
    ),
    "helpers": ResourceSpec(
        id="helpers",
        label="עזרים",
        snapshot_service="bobi_cc_helpers_snapshot",
        commit_service="bobi_cc_helper_commit",
        operations=HELPER_OPERATIONS,
        id_field="helper_id",
        titles={
            "set": "שינוי ערך",
            "start": "הפעלת טיימר",
            "pause": "השהיית טיימר",
            "cancel": "ביטול טיימר",
            "reset": "איפוס",
            "increment": "הגדלה",
            "decrement": "הקטנה",
        },
    ),
    "automations": ResourceSpec(
        id="automations",
        label="אוטומציות Home Assistant",
        snapshot_service="bobi_cc_automations_snapshot",
        commit_service="bobi_cc_automation_commit",
        operations=AUTOMATION_OPERATIONS,
        id_field="automation_id",
        default_risk="medium",
        titles={
            "enable": "הפעלת אוטומציה",
            "disable": "השבתת אוטומציה",
            "trigger": "הרצת אוטומציה עכשיו",
            "rename": "שינוי שם",
        },
    ),
    "scripts": ResourceSpec(
        id="scripts",
        label="סקריפטים",
        snapshot_service="bobi_cc_scripts_snapshot",
        commit_service="bobi_cc_script_commit",
        operations=SCRIPT_OPERATIONS,
        id_field="script_id",
        default_risk="medium",
        titles={"run": "הרצת סקריפט", "rename": "שינוי שם"},
    ),
    "scenes": ResourceSpec(
        id="scenes",
        label="סצנות",
        snapshot_service="bobi_cc_scenes_snapshot",
        commit_service="bobi_cc_scene_commit",
        operations=SCENE_OPERATIONS,
        id_field="scene_id",
        titles={"activate": "הפעלת סצנה", "rename": "שינוי שם"},
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
    # The bare words first. The live bridge publishes its own refusal list and
    # calls one of them simply `restart` — which the prefixed entries below did
    # not match, because the test runs the other way round: each banned string
    # must appear *inside* the action name. Anything containing "restart",
    # "reboot" or "shutdown" is now caught however it is spelled.
    "restart",
    "reboot",
    "shutdown",
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


#: The bridge's word for an operation → this application's.
#:
#: The live 3c contract declares `add` for rules and calendar events where this
#: application calls it `create`. They are the same verb, and an unreconciled
#: synonym is dropped by the closed-set filter — so the contract would announce
#: the operation, the app would silently not offer it, and neither side would
#: report anything wrong.
#:
#: Only true synonyms belong here. A bridge verb that means something this
#: application cannot describe and check must stay dropped, because the closed
#: set is what makes the write path safe.
OPERATION_SYNONYMS: dict[str, str] = {
    "add": "create",
    "new": "create",
    "remove": "delete",
    "toggle": "set",
    "activate_scene": "activate",
}


def canonical_operation(resource: str, operation: str) -> str:
    """The name this application knows an operation by.

    A synonym is translated only when the family actually declares the target
    verb — `add` becomes `create` for rules, and stays `add` for tasks, where
    `add` is the declared name and `create` means nothing.
    """
    spec = SPECS.get(resource)
    if spec is None or operation in spec.operations:
        return operation
    mapped = OPERATION_SYNONYMS.get(operation)
    if mapped and mapped in spec.operations:
        return mapped
    return operation


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
#: Home Assistant's own state words, in Hebrew.
#:
#: A bridge that publishes no `display` for an item leaves this side to render
#: the value, and for anything that is not a number, a boolean or a published
#: option that meant printing Home Assistant's word as it came: a scene read
#: `ready`, a timer read `idle`, the undo row read `available`. Three English
#: words in a Hebrew right-to-left panel, and nothing in the app knew they were
#: words rather than data.
#:
#: These are the universal ones — the vocabulary Home Assistant uses for every
#: integration rather than any single one's. A word that is not here still falls
#: through to itself, which is the same honest failure as before: a value this
#: table does not know is shown rather than hidden.
_STATE_WORDS: dict[str, str] = {
    "on": "פעיל",
    "off": "כבוי",
    "idle": "ממתין",
    "active": "פעיל",
    "paused": "מושהה",
    "running": "רץ",
    "ready": "מוכן",
    "available": "זמין",
    "unavailable": "לא זמין",
    "unknown": "לא ידוע",
    "open": "פתוח",
    "closed": "סגור",
    "opening": "נפתח",
    "closing": "נסגר",
    "locked": "נעול",
    "unlocked": "פתוח",
    "home": "בבית",
    "not_home": "לא בבית",
    "streaming": "משדרת",
    "recording": "מקליטה",
    "cleaning": "מנקה",
    "docked": "בעמדה",
    "returning": "חוזר לעמדה",
    "error": "תקלה",
    # Climate. The live air conditioners publish `hvac_modes`, `fan_modes`,
    # `swing_modes` and `preset_modes` as bare English lists, and a bare list
    # becomes an option whose label is its own token — so all four dropdowns on
    # every air conditioner read "cool", "fan_only", "silent", "boost".
    "cool": "מקרר",
    "heat": "מחמם",
    "dry": "מייבש",
    "fan_only": "אוורור",
    "heat_cool": "חימום וקירור",
    "auto": "אוטומטי",
    "silent": "שקט",
    "low": "נמוך",
    "medium": "בינוני",
    "high": "גבוה",
    "full": "מלא",
    "turbo": "טורבו",
    "vertical": "אנכי",
    "horizontal": "אופקי",
    "both": "אנכי ואופקי",
    "none": "ללא",
    "comfort": "נוחות",
    "eco": "חסכוני",
    "boost": "מוגבר",
    "sleep": "שינה",
    "away": "מחוץ לבית",
}


#: Words whose plain reading is wrong for one particular domain.
#:
#: A camera sitting at `idle` came through the table below as *"ממתין"*, which
#: reads as a camera that is fine and waiting. It says no such thing: `idle`
#: means only that nothing is streaming right now, and the camera in this house
#: was `idle` for days while every attempt to fetch a picture answered HTTP 500.
#: The devices screen therefore looked healthy while the cameras screen failed.
#:
#: The honest word for a camera says what the state actually reports and claims
#: nothing about whether the camera can produce a picture — which this side has
#: not asked and cannot know without fetching one.
_DOMAIN_STATE_WORDS: dict[str, dict[str, str]] = {
    "camera": {"idle": "לא משדרת"},
}


def state_word(text: str, domain: str | None = None) -> str:
    """Home Assistant's word for a state, in Hebrew — or the text unchanged.

    Separate from `humanise` because a bridge may publish its own `display`,
    and the live one does: it sends the entity's raw state there. So every
    device row on the busiest screen in the app read "off", "cool", "docked"
    and "idle" — the bridge had filled in the field whose whole purpose is to
    be the human reading, with the machine one.

    Only the universal vocabulary is translated, and anything else is returned
    as it came: a bridge that publishes a real Hebrew display must pass through
    this untouched.

    `domain` narrows the reading where the universal word would be misleading —
    see `_DOMAIN_STATE_WORDS`. It is optional because most callers have a bare
    word and no context, and a missing domain must never change an answer that
    was already right.
    """
    token = text.strip().lower()
    if domain:
        override = _DOMAIN_STATE_WORDS.get(domain.strip().lower())
        if override and token in override:
            return override[token]
    return _STATE_WORDS.get(token, text)


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
    return state_word(str(value))


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

    # A list's permitted values live in `constraints.allowed` by the
    # specification and in `options` by the live bridge's habit. Reading only
    # the first was a hole rather than a cosmetic gap: with the choices in
    # `options`, `limits.allowed` was empty, the check below was skipped
    # entirely, and a Shabbat profile would have accepted a device token that
    # was never on offer. Checked before `limits` is tested for None, because
    # an item can publish options and no constraints block at all.
    if item.kind == "list":
        permitted = limits.allowed if (limits and limits.allowed) else item.options
        if permitted:
            allowed = {str(option.value) for option in permitted}
            unknown = [str(part) for part in (value or []) if str(part) not in allowed]
            if unknown:
                errors.append(
                    ("not_allowed", f"המכשירים האלה אינם חלק מהפרופיל: {'، '.join(unknown)}")
                )
        return errors

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

    return errors
