"""The specification every `script.bobi_cc_*` bridge must satisfy.

This module is the written-down half of an agreement between two codebases that
cannot import each other. Home Assistant implements the scripts; this
application calls them and refuses anything that does not fit. Until now the
shape of that agreement lived in the reading of `real_management.py` — which is
fine for one bridge and hopeless for twenty.

So it is declared here, once, and **derived from the same specs the calling code
uses**: the service names, the id fields and the operations come from
`app.services.resources.SPECS`, so a contract that says one thing while the
adapter does another is not expressible. Adding a family means adding a spec;
the document follows.

It is served read-only at `GET /api/bobi/manage/bridge-contract`, so whoever is
writing the Home Assistant side can fetch exactly what this build expects rather
than working from a description of it.

## What every write bridge receives

Three fields on every commit, without exception:

* `preview_token` — opaque, server-side, five-minute, single-use. **Never
  empty.** The adapter refuses to build a commit without one, and Home Assistant
  must refuse a commit that arrives without one. This is what proves a change
  went through preview and confirmation rather than straight at the script.
* `confirmed` — always `true` by the time a commit is built. A commit without an
  explicit confirmation never leaves this application.
* `request_id` — a fresh id per attempt, for correlating the two logs.

Plus one `expected_<key>` per value the preview observed. Home Assistant
compares them immediately before acting and answers `stale_preview` if the world
moved on, in which case **nothing may be mutated**.

## What every write bridge answers

```json
{ "executed": true, "verified": true, "reason": "ok",
  "<id_field>": "…", "writes_enabled": true }
```

* `executed` — whether the change was applied.
* `verified` — the result of Home Assistant's own **read-after-write**. Absent
  means "not checked", which this application reports as *committed but
  unverified* rather than as success.
* `reason` — a token, not a sentence: `ok`, `stale_preview`, `already_in_state`,
  `duplicate`, `not_found`, `writes_disabled`, `invalid_commit_request`.
* `writes_enabled` — the master switch as it stood on that call.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.adapters.real_management import (
    CONTRACT,
    FEATURE_COMMIT,
    TASK_ADD_COMMIT,
    TASK_SNAPSHOT,
    TASK_UPDATE_COMMIT,
)
from app.services.resources import SPECS
from app.services.roles import MINIMUM_ROLE

#: Sent on every commit, by every family.
COMMON_COMMIT_INPUTS: tuple[tuple[str, str, str], ...] = (
    (
        "preview_token",
        "string, non-empty",
        "Opaque single-use token minted at preview time. Refuse the commit if it "
        "is missing or empty.",
    ),
    ("confirmed", "boolean, always true", "Refuse the commit if it is not true."),
    ("request_id", "string", "Correlates this attempt with the app's own log."),
)

#: Returned by every commit.
COMMON_COMMIT_OUTPUTS: tuple[tuple[str, str, str], ...] = (
    ("executed", "boolean", "Whether the change was applied."),
    (
        "verified",
        "boolean, optional",
        "Result of read-after-write. Omit it rather than guessing — an omitted "
        "value is reported as 'committed but unverified', which is honest.",
    ),
    (
        "reason",
        "token",
        "ok · stale_preview · already_in_state · duplicate · not_found · "
        "writes_disabled · invalid_commit_request",
    ),
    ("writes_enabled", "boolean", "The master switch as it stood on this call."),
)

#: The envelope every `*_snapshot` read service answers with. The normalizer is
#: tolerant about which of these are present, but this is the shape it is built
#: for and the one a new bridge should aim at.
SNAPSHOT_OUTPUT = """{
  "available": true,
  "reason": null,
  "writes_enabled": false,
  "groups": [{"id": "…", "label": "…", "items": [ <item>, … ]}],
  "items": [ <item>, … ]
}

<item> = {
  "id":        "canonical Bobi id — never a Home Assistant entity_id",
  "label":     "Hebrew, shown as-is",
  "kind":      "toggle|number|time|date|datetime|choice|text|list|readonly",
  "value":     <current value; omit the item rather than sending a guess>,
  "controllable": true,          // absent means NOT controllable
  "operations":   ["…"],         // absent or empty means read-only
  "risk":      "read_only|low|medium|high|destructive",
  "description":  "Hebrew, optional",
  "options":      [{"value": "…", "label": "…"}],        // for kind=choice
  "constraints":  {"min": 0, "max": 100, "step": 5, "unit": "…",
                   "max_length": 40, "allowed": [{"value": "…", "label": "…"}]},
  "unavailable_reason": "Hebrew, when present the item is shown but not operable"
}"""


@dataclass(frozen=True)
class BridgeService:
    """One `script.bobi_cc_*` and everything the other side needs to build it."""

    #: Without the `script.` domain prefix.
    name: str
    #: `read` or `write`.
    kind: str
    #: What it is for, in one line.
    purpose: str
    #: `(field, type, note)`. Write services also receive `COMMON_COMMIT_INPUTS`.
    inputs: tuple[tuple[str, str, str], ...] = ()
    #: What it must answer.
    outputs: str = ""
    #: What it must refuse, and how.
    validation: tuple[str, ...] = ()
    #: How it must confirm the change landed.
    verification: str = ""
    #: The highest risk any operation on this bridge carries.
    risk: str = "read_only"
    #: Which managed family it serves, when it serves one.
    resource: str | None = None
    #: The operations it must accept, when it is a write bridge.
    operations: tuple[str, ...] = ()
    #: `(operation, risk)` for the operations this application rates itself.
    operation_risk: dict[str, str] = field(default_factory=dict)


_READ_VALIDATION = (
    "Never include a Home Assistant entity_id, a phone number, a LID or a chat "
    "id. The application drops them, but they must not be sent.",
    "An item whose current value cannot be read must be omitted or marked "
    "`unavailable_reason` — never sent with a guessed value, because a preview "
    "binds to what you report and Home Assistant compares against it.",
)

_WRITE_VALIDATION = (
    "Refuse a commit with an empty or missing `preview_token` "
    "(`reason: invalid_commit_request`).",
    "Refuse a commit whose `expected_*` values no longer match the current "
    "state (`reason: stale_preview`) and **mutate nothing**.",
    "Refuse an operation outside the declared list for this resource.",
    "Honour the master write switch: with it off, answer "
    "`executed: false, reason: writes_disabled` and change nothing.",
)

_VERIFICATION = (
    "Read the value back after writing it and report the comparison in "
    "`verified`. Omit `verified` rather than assuming success."
)

#: The risks this application assigns per operation, so the Home Assistant side
#: can mirror the same judgement rather than inventing a second one.
_OPERATION_RISK: dict[tuple[str, str], str] = {
    ("users", "set_phone"): "high",
    ("users", "set_role"): "high",
    ("users", "disable"): "high",
    ("rules", "delete"): "destructive",
    ("calendar", "delete"): "destructive",
    ("automations", "trigger"): "medium",
    ("scripts", "run"): "medium",
    ("system", "run"): "medium",
}


def _operation_risk(resource: str, operation: str) -> str:
    spec = SPECS[resource]
    if operation in spec.destructive:
        return "destructive"
    return _OPERATION_RISK.get((resource, operation), spec.default_risk)


def _highest(risks: list[str]) -> str:
    order = ("read_only", "low", "medium", "high", "destructive")
    return max(risks, key=lambda risk: order.index(risk) if risk in order else 3, default="low")


def _family_services(resource: str) -> list[BridgeService]:
    """The read and write bridge for one managed family, from its own spec."""
    spec = SPECS[resource]
    services: list[BridgeService] = []

    if spec.snapshot_service:
        services.append(
            BridgeService(
                name=spec.snapshot_service,
                kind="read",
                purpose=f"Current state of {spec.label}, as canonical items.",
                inputs=(),
                outputs=SNAPSHOT_OUTPUT,
                validation=_READ_VALIDATION,
                verification="Not applicable — this service must never change anything.",
                risk="read_only",
                resource=resource,
            )
        )

    if spec.commit_service:
        risks = {operation: _operation_risk(resource, operation) for operation in spec.operations}
        services.append(
            BridgeService(
                name=spec.commit_service,
                kind="write",
                purpose=f"Apply one previewed, confirmed change to {spec.label}.",
                inputs=(
                    ("operation", f"one of {', '.join(spec.operations)}", "The declared verb."),
                    (
                        spec.id_field,
                        "string",
                        "The canonical id of the target. Absent when creating.",
                    ),
                    (
                        "<operation fields>",
                        "flat",
                        "The validated payload — `value` for a set, `name` for a rename, "
                        "and so on. Flat, never nested.",
                    ),
                    (
                        "expected_<key>",
                        "one per observed value",
                        "What the preview saw. Compare before acting.",
                    ),
                    *COMMON_COMMIT_INPUTS,
                ),
                outputs="{\n"
                + "\n".join(f'  "{name}": <{kind}>,' for name, kind, _ in COMMON_COMMIT_OUTPUTS)
                + f'\n  "{spec.id_field}": "<id of the affected item>"\n'
                + "}",
                validation=_WRITE_VALIDATION,
                verification=_VERIFICATION,
                risk=_highest(list(risks.values())),
                resource=resource,
                operations=spec.operations,
                operation_risk=risks,
            )
        )
    return services


def _phase_3a_services() -> list[BridgeService]:
    """The five bridges Home Assistant has already implemented.

    Listed so the document is complete rather than because anything about them
    needs changing. Their shapes are frozen: they are live, and 2.2.1 exists
    because one field went missing from them.
    """
    return [
        BridgeService(
            name=CONTRACT,
            kind="read",
            purpose="Discovery. Which families exist, which operations they accept, "
            "and whether the master write switch is on.",
            outputs='{\n'
            '  "contract_version": "3c",\n'
            '  "bridge_available": true,\n'
            '  "writes_enabled": false,\n'
            '  "resources": [\n'
            '    {"id": "settings", "label": "…", "supported": true,\n'
            '     "operations": ["set"], "targets": [{"id": "…", "label": "…"}]}\n'
            "  ]\n"
            "}",
            validation=(
                "`resources` is authoritative. A family omitted from it is treated as "
                "not offered, whatever else the payload contains.",
                "A family declared with an empty `operations` list is read-only: the "
                "screens show its values and draw no save button. That is the correct "
                "way to publish a snapshot bridge before its commit bridge exists.",
                "`writes_enabled` is read and never written. No endpoint in this "
                "application can set it.",
            ),
            verification="Not applicable — read-only.",
            risk="read_only",
        ),
        BridgeService(
            name=TASK_SNAPSHOT,
            kind="read",
            purpose="Open and completed tasks, with the bridge's own uid.",
            outputs='{"users": [{"id": "user_1", "name": "…", "items": '
            '[{"uid": "…", "summary": "…", "status": "needs_action|completed", '
            '"due": "YYYY-MM-DD"}]}], "writes_enabled": false}',
            validation=_READ_VALIDATION,
            verification="Not applicable — read-only.",
            risk="read_only",
            resource="tasks",
        ),
        BridgeService(
            name=TASK_ADD_COMMIT,
            kind="write",
            purpose="Add one task.",
            inputs=(
                ("user_id", "string", "Whose list."),
                ("summary", "string", "The task text."),
                ("due_date", "YYYY-MM-DD or ''", "Empty string means no date."),
                *COMMON_COMMIT_INPUTS,
            ),
            outputs='{"executed": …, "verified": …, "reason": "…", "uid": "…", '
            '"writes_enabled": …}',
            validation=(*_WRITE_VALIDATION, "Refuse a duplicate open task (`reason: duplicate`)."),
            verification=_VERIFICATION,
            risk="low",
            resource="tasks",
            operations=("add",),
            operation_risk={"add": "low"},
        ),
        BridgeService(
            name=TASK_UPDATE_COMMIT,
            kind="write",
            purpose="Edit, complete, reopen or delete one task.",
            inputs=(
                ("operation", "edit|complete|reopen|delete", "The declared verb."),
                ("user_id", "string", "Whose list."),
                ("uid", "string", "The task."),
                ("new_summary", "string", "For `edit`; empty otherwise."),
                ("expected_summary", "string", "What the preview saw."),
                ("expected_status", "string", "What the preview saw."),
                *COMMON_COMMIT_INPUTS,
            ),
            outputs='{"executed": …, "verified": …, "reason": "…", "uid": "…", '
            '"writes_enabled": …}',
            validation=_WRITE_VALIDATION,
            verification=_VERIFICATION,
            risk="destructive",
            resource="tasks",
            operations=("edit", "complete", "reopen", "delete"),
            operation_risk={
                "edit": "low",
                "complete": "low",
                "reopen": "low",
                "delete": "destructive",
            },
        ),
        BridgeService(
            name=FEATURE_COMMIT,
            kind="write",
            purpose="Turn one declared feature on or off.",
            inputs=(
                ("feature_id", "string", "From the contract's feature targets."),
                ("enabled", "boolean", "The wanted state."),
                ("expected_state", "on|off", "What the preview observed."),
                *COMMON_COMMIT_INPUTS,
            ),
            outputs='{"executed": …, "verified": …, "reason": "…", "feature_id": "…", '
            '"writes_enabled": …}',
            validation=(
                *_WRITE_VALIDATION,
                "Report `already_in_state` when the feature already holds the wanted "
                "value — that is a verified success needing no change, not a failure.",
            ),
            verification=_VERIFICATION,
            risk="low",
            resource="features",
            operations=("set",),
            operation_risk={"set": "low"},
        ),
    ]


#: The Phase 2 read services. They predate management, they are live, and they
#: are the ones the read-only screens use. Listed so the document covers every
#: `script.bobi_cc_*` this application can call rather than only the newer half.
_PHASE_2_READS: tuple[tuple[str, str], ...] = (
    ("bobi_cc_status", "Overall health, WhatsApp, AI, Fast Paths, feature flags, counters."),
    ("bobi_cc_devices", "The device catalogue, with areas, capabilities and limits."),
    ("bobi_cc_capabilities", "What Bobi can do, as a registry."),
    ("bobi_cc_users", "The household, without phone numbers or LIDs."),
    ("bobi_cc_shabbat", "Shabbat times, profiles and AC temperatures."),
    ("bobi_cc_rules", "Bobi's smart rules."),
    ("bobi_cc_tasks", "Tasks, read-only."),
    ("bobi_cc_diagnostics", "Open issues, with suggested actions."),
    ("bobi_cc_probe", "Parse a sentence and report what Bobi *would* do. Never executes."),
)


def _phase_2_services() -> list[BridgeService]:
    return [
        BridgeService(
            name=name,
            kind="read",
            purpose=purpose,
            inputs=(
                ("text", "string", "The sentence to parse.")
                ,) if name == "bobi_cc_probe" else (),
            outputs="Normalized by `app/services/normalize.py`; see docs/api.md for each "
            "shape. Unmapped fields survive in a per-item `extra` map rather than "
            "being dropped.",
            validation=_READ_VALIDATION
            + (
                (
                    "`bobi_cc_probe` must run with probe-only semantics and change "
                    "nothing, whatever the sentence says.",
                )
                if name == "bobi_cc_probe"
                else ()
            ),
            verification="Not applicable — read-only.",
            risk="read_only",
        )
        for name, purpose in _PHASE_2_READS
    ]


def all_services() -> list[BridgeService]:
    """Every bridge this build knows how to call, read services first."""
    services = _phase_2_services() + _phase_3a_services()
    for resource in SPECS:
        if resource in ("tasks", "features"):
            continue
        services.extend(_family_services(resource))
    return services


#: Home Assistant service domains this application will never call, whatever a
#: contract advertises. Published so the other side can assert the same list.
NEVER_CALLED = (
    "todo",
    "input_boolean",
    "input_number",
    "input_select",
    "input_text",
    "input_datetime",
    "timer",
    "counter",
    "light",
    "switch",
    "climate",
    "cover",
    "fan",
    "media_player",
    "vacuum",
    "lock",
    "humidifier",
    "water_heater",
    "scene",
    "script",
    "automation",
    "camera",
    "calendar",
    "homeassistant",
    "hassio",
    "shell_command",
)

#: Operations no bridge may offer, because this application refuses to ask for
#: them however they are advertised. Mirrors
#: `app.services.resources.FORBIDDEN_SYSTEM_ACTIONS`.
NEVER_REQUESTED = (
    "Restarting Home Assistant, the host or the Supervisor",
    "Updating the Supervisor or Home Assistant Core",
    "Deleting an integration, a device or an entity",
    "Restoring a backup",
    "Any shell or arbitrary command execution",
)


def risk_to_role() -> dict[str, str]:
    """The permission mapping, published so both sides rate operations alike."""
    return {risk: role.value for risk, role in MINIMUM_ROLE.items()}
