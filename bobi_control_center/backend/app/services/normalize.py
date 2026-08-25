"""Map raw `script.bobi_cc_*` responses onto the canonical contract.

This module is the **only** place that knows what Home Assistant actually sends.
Everything above it — routes, and therefore React — sees one clean schema.

## Why it is written defensively

The bridge is Bobi's, not this app's. It names its collections `entries`,
`registry`, `upcoming`, `profiles`, `drafts`, `users`, and nests the probe answer
under `result`. Those names may keep evolving, and a payload may legitimately
omit fields. So each normalizer:

* accepts a small set of plausible key names for a collection rather than one;
* accepts a **map or a list** wherever the bridge could reasonably send either
  (`checks`, `profiles`, `registry` all vary in the wild);
* never raises on a missing or oddly-typed field — a partial response must
  produce a usable screen, not a 502;
* routes anything it did not map into `extra`, so new bridge fields surface in
  the UI's Advanced panel instead of vanishing.

The one thing it will not do is invent data: absent means absent.
"""

from __future__ import annotations

import logging
from typing import Any

from app.models.bridge import (
    BridgeCapabilities,
    BridgeCapability,
    BridgeDevice,
    BridgeDevices,
    BridgeDiagnostics,
    BridgeIssue,
    BridgeProbe,
    BridgeRule,
    BridgeRules,
    BridgeShabbat,
    BridgeStatus,
    BridgeTask,
    BridgeTasks,
    BridgeUser,
    BridgeUsers,
    CapabilityToggle,
    DeviceLimits,
    DiagnosticCheck,
    ShabbatProfile,
    StatusComponent,
)

logger = logging.getLogger("bobi.normalize")

Payload = dict[str, Any]


# --- small helpers ----------------------------------------------------------
def _first(payload: Payload, *keys: str) -> Any:
    """First key present with a meaningful value."""
    for key in keys:
        value = payload.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None


def _bool(value: Any) -> bool | None:
    """Interpret the several ways the bridge spells a boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "on", "ok", "working", "healthy", "connected", "1"}:
            return True
        if lowered in {"false", "no", "off", "error", "failed", "broken", "0"}:
            return False
    return None


def _int(value: Any) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, list):
        return [text for item in value if (text := _text(item))]
    return []


def _as_items(value: Any, id_key: str = "id") -> list[Payload]:
    """Coerce a collection into a list of dicts.

    The bridge sends some collections as a list and others as a map keyed by id.
    A map's key is injected under `id_key` so nothing is lost either way.
    """
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        items: list[Payload] = []
        for key, item in value.items():
            if isinstance(item, dict):
                items.append({id_key: key, **item})
            else:
                # A scalar value keyed by name, e.g. {"whatsapp": "WORKING"}.
                items.append({id_key: key, "value": item})
        return items
    return []


def _leftover(payload: Payload, used: set[str]) -> dict[str, Any]:
    """Fields the normalizer did not map, kept for the Advanced panel."""
    return {
        key: value
        for key, value in payload.items()
        if key not in used and value not in (None, "", [], {})
    }


def _humanize(key: str) -> str:
    return key.replace("_", " ").strip().capitalize()


def _container(payload: Payload, *keys: str) -> tuple[Any, str | None]:
    """Find the collection a response carries, and report which key held it."""
    for key in keys:
        if key in payload and payload[key] not in (None, "", [], {}):
            return payload[key], key
    return None, None


# --- status -----------------------------------------------------------------
#: `api_version` is protocol metadata, not something to show a household member.
_PROTOCOL_KEYS = {"api_version", "schema_version"}

_STATUS_MAPPED = {
    "ok", "version", "uptime", "components", "counts", "writes_enabled", *_PROTOCOL_KEYS,
}


def normalize_status(payload: Payload) -> BridgeStatus:
    """`script.bobi_cc_status`.

    Beyond the documented fields, any remaining scalar becomes a `details` row
    and any remaining integer becomes a `counts` entry, so real Bobi status
    fields are displayed rather than dropped on the floor.
    """
    components = [
        component
        for item in _as_items(payload.get("components"))
        if (component := _status_component(item))
    ]

    counts: dict[str, int] = {}
    raw_counts = payload.get("counts")
    if isinstance(raw_counts, dict):
        for key, value in raw_counts.items():
            number = _int(value)
            if number is not None:
                counts[key] = number

    details: dict[str, str] = {}
    for key, value in _leftover(payload, _STATUS_MAPPED).items():
        number = _int(value) if not isinstance(value, bool) else None
        if number is not None and isinstance(value, (int, float)):
            # A bare integer beside the documented fields reads as a headline
            # figure, which is what the dashboard's count cards are for.
            counts.setdefault(key, number)
            continue
        text = _text(value)
        if text is not None:
            details[key] = text

    return BridgeStatus(
        ok=_bool(payload.get("ok")),
        version=_text(_first(payload, "version", "bobi_version", "api_version")),
        uptime=_text(_first(payload, "uptime", "up_since", "started_at")),
        components=components,
        counts=counts,
        details=details,
        writes_enabled=False,
    )


#: Machine status words the bridge may use in place of a human label.
_STATE_WORDS = {
    "working": "תקין",
    "ok": "תקין",
    "healthy": "תקין",
    "online": "פעיל",
    "connected": "מחובר",
    "degraded": "פעיל חלקית",
    "offline": "לא זמין",
    "disconnected": "מנותק",
    "error": "שגיאה",
    "failed": "נכשל",
    "unknown": "לא ידוע",
}


def _status_component(item: Payload) -> StatusComponent | None:
    identifier = _text(_first(item, "id", "name", "component", "key"))
    if identifier is None:
        return None
    name = _text(_first(item, "name", "label", "title")) or identifier
    ok = _bool(_first(item, "ok", "healthy", "connected", "state", "status"))
    state = _text(_first(item, "state", "status"))
    # An explicit label wins. Otherwise a bare status word like "WORKING" is
    # machine vocabulary, so translate it rather than showing it raw.
    label = _text(item.get("label"))
    if label is None and state is not None:
        label = _STATE_WORDS.get(state.lower(), state)
    if label is None:
        label = "תקין" if ok else "לא תקין" if ok is False else "לא ידוע"
    return StatusComponent(
        id=identifier,
        name=name,
        label=label,
        state=state,
        ok=ok,
        detail=_text(_first(item, "detail", "description", "message")),
    )


# --- devices ----------------------------------------------------------------
_DEVICE_MAPPED = {
    "id", "entity_id", "name", "canonical", "friendly_name", "area", "room",
    "group", "domain", "state", "aliases", "capabilities", "semantic_scopes",
    "scopes", "controllable", "logical_controllable", "handler", "limits",
    "last_changed",
}

_UNAVAILABLE_STATES = {"unavailable", "unknown", "none", ""}


def normalize_devices(
    payload: Payload, scope: str = "all", include_unavailable: bool = True
) -> BridgeDevices:
    """`script.bobi_cc_devices`.

    The real bridge returns the catalog under `entries`. Older/mock shapes used
    `devices`, so both are accepted — but exactly one list is emitted.
    """
    raw, _ = _container(payload, "entries", "devices", "items", "catalog")
    devices = [device for item in _as_items(raw) if (device := _device(item))]

    return BridgeDevices(
        scope=_text(payload.get("scope")) or scope,
        include_unavailable=(
            _bool(payload.get("include_unavailable"))
            if payload.get("include_unavailable") is not None
            else include_unavailable
        ),
        count=len(devices),
        devices=devices,
        areas=sorted({d.area for d in devices if d.area}),
        groups=sorted({d.group for d in devices if d.group}),
    )


def _device(item: Payload) -> BridgeDevice | None:
    entity_id = _text(item.get("entity_id"))
    name = _text(_first(item, "canonical", "name", "friendly_name", "label"))
    identifier = _text(item.get("id")) or entity_id or name
    if identifier is None:
        return None

    state = _text(item.get("state"))
    limits_raw = item.get("limits")
    limits = (
        DeviceLimits(
            min=_number(limits_raw.get("min")),
            max=_number(limits_raw.get("max")),
            step=_number(limits_raw.get("step")),
        )
        if isinstance(limits_raw, dict)
        else None
    )

    return BridgeDevice(
        id=identifier,
        # Never fall back to the entity id for a *displayed* name unless there
        # is genuinely nothing else.
        name=name or entity_id or identifier,
        area=_text(_first(item, "area", "room")),
        group=_text(item.get("group")),
        domain=_text(item.get("domain")),
        state=state,
        available=(state or "").lower() not in _UNAVAILABLE_STATES,
        aliases=_str_list(item.get("aliases")),
        capabilities=_str_list(item.get("capabilities")),
        semantic_scopes=_str_list(_first(item, "semantic_scopes", "scopes")),
        controllable=_bool(item.get("controllable")),
        logical_controllable=_bool(item.get("logical_controllable")),
        entity_id=entity_id,
        handler=_text(item.get("handler")),
        limits=limits,
        last_changed=_text(item.get("last_changed")),
        extra=_leftover(item, _DEVICE_MAPPED),
    )


def _number(value: Any) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


# --- capabilities -----------------------------------------------------------
_CAPABILITY_MAPPED = {
    "id", "key", "name", "label", "title", "example", "examples", "risk",
    "handler", "local", "local_after_parse", "group", "category",
}


def normalize_capabilities(payload: Payload) -> BridgeCapabilities:
    """`script.bobi_cc_capabilities`.

    The real bridge returns the registry under `registry`, commonly as a map
    keyed by capability id. Runtime master toggles arrive separately.
    """
    raw, _ = _container(payload, "registry", "capabilities", "items")
    capabilities = [
        capability for item in _as_items(raw) if (capability := _capability(item))
    ]

    raw_toggles, _ = _container(payload, "toggles", "runtime", "states", "master_toggles")
    toggles = [toggle for item in _as_items(raw_toggles) if (toggle := _toggle(item))]

    return BridgeCapabilities(
        count=len(capabilities), capabilities=capabilities, toggles=toggles
    )


def _capability(item: Payload) -> BridgeCapability | None:
    identifier = _text(_first(item, "id", "key", "handler", "label", "name"))
    if identifier is None:
        return None
    example = _first(item, "example", "examples")
    if isinstance(example, list):
        example = example[0] if example else None

    return BridgeCapability(
        id=identifier,
        # The registry's own label is what a person reads; fall back to the id
        # rather than showing nothing.
        label=_text(_first(item, "label", "name", "title")) or identifier,
        example=_text(example),
        risk=_text(item.get("risk")),
        handler=_text(item.get("handler")),
        local=_bool(item.get("local")),
        local_after_parse=_bool(item.get("local_after_parse")),
        group=_text(_first(item, "group", "category")),
        extra=_leftover(item, _CAPABILITY_MAPPED),
    )


def _toggle(item: Payload) -> CapabilityToggle | None:
    identifier = _text(_first(item, "id", "key", "entity_id", "name"))
    if identifier is None:
        return None
    state = _first(item, "state", "value", "status")
    return CapabilityToggle(
        id=identifier,
        label=_text(_first(item, "label", "name", "title")) or identifier,
        enabled=_bool(_first(item, "enabled", "on")) if _first(item, "enabled", "on") is not None
        else _bool(state),
        state=_text(state),
        entity_id=_text(item.get("entity_id")),
    )


# --- users ------------------------------------------------------------------
_USER_MAPPED = {
    "id", "key", "name", "display_name", "role", "enabled", "active",
    "whatsapp_connected", "whatsapp", "calendar", "task_list", "tasks_list",
    "permissions", "areas", "rooms",
}

#: Never surfaced, even if a future bridge version starts sending them.
_PRIVATE_USER_FIELDS = {
    "phone", "phone_number", "whatsapp_number", "number", "lid", "jid",
    "wa_id", "chat_id", "contact",
}


def normalize_users(payload: Payload) -> BridgeUsers:
    """`script.bobi_cc_users`.

    Any field that looks like a phone number, LID or chat id is dropped here
    rather than passed through `extra` — the bridge withholds them today and
    this app must not reintroduce them if that ever changes.
    """
    raw, _ = _container(payload, "users", "items", "people")
    users = [user for item in _as_items(raw) if (user := _user(item))]
    return BridgeUsers(count=len(users), users=users)


def _user(item: Payload) -> BridgeUser | None:
    identifier = _text(_first(item, "id", "key", "name"))
    if identifier is None:
        return None

    extra = _leftover(item, _USER_MAPPED)
    for key in list(extra):
        if any(private in key.lower() for private in _PRIVATE_USER_FIELDS):
            extra.pop(key)

    whatsapp = _first(item, "whatsapp_connected", "whatsapp")
    return BridgeUser(
        id=identifier,
        name=_text(_first(item, "name", "display_name")) or identifier,
        role=_text(item.get("role")),
        enabled=_bool(_first(item, "enabled", "active")),
        whatsapp_connected=_bool(whatsapp),
        calendar=_text(item.get("calendar")),
        task_list=_text(_first(item, "task_list", "tasks_list")),
        permissions=_str_list(item.get("permissions")),
        areas=_str_list(_first(item, "areas", "rooms")),
        extra=extra,
    )


# --- probe ------------------------------------------------------------------
_PROBE_MAPPED = {
    "handled", "status", "terminal", "skill", "understanding", "schedule_valid",
    "schedule_reason", "schedule_kind", "text", "error", "result", "executed",
    "probe_only", "would_execute",
}


def normalize_probe(payload: Payload, text: str) -> BridgeProbe:
    """`script.bobi_cc_probe`.

    The real bridge nests its answer under `result`; the flat shape is also
    accepted. `result` wins where both carry a key, and the untouched payload is
    kept in `raw` for the Test Center's JSON view.
    """
    result = payload.get("result")
    merged: Payload = dict(payload)
    if isinstance(result, dict):
        merged.update({k: v for k, v in result.items() if v is not None})

    understanding = merged.get("understanding")
    if not isinstance(understanding, dict):
        understanding = {}

    warnings: list[str] = []
    reason = _text(_first(merged, "schedule_reason", "reason", "message"))

    # `executed` is the bridge's own statement. It must be false — probe_only
    # guarantees it — so anything else is worth showing, not hiding.
    executed = _bool(_first(merged, "executed", "would_execute"))
    if executed:
        logger.warning("Bridge reported executed=true on a probe call; forcing false.")
        warnings.append(
            "הגשר דיווח על ביצוע בפועל. היישום חוסם זאת, אך כדאי לבדוק את הסקריפט ב-Home Assistant."
        )

    error = _text(_first(merged, "error", "error_message"))
    if error:
        warnings.append(error)

    return BridgeProbe(
        handled=_bool(merged.get("handled")),
        status=_text(merged.get("status")),
        terminal=_bool(merged.get("terminal")),
        skill=_text(merged.get("skill")),
        understanding=understanding,
        schedule_valid=_bool(merged.get("schedule_valid")),
        schedule_reason=reason,
        schedule_kind=_text(merged.get("schedule_kind")),
        text=_text(merged.get("text")) or text,
        error=error,
        warnings=warnings,
        probe_only=True,
        would_execute=False,
        raw=payload,
    )


# --- shabbat ----------------------------------------------------------------
_SHABBAT_MAPPED = {
    "upcoming", "times", "profiles", "drafts", "candle_lighting", "havdalah",
    "parasha", "pre_shabbat_offset_minutes", "offset_minutes", "ac_temperatures",
    "device_labels", "labels", "has_draft", "writes_enabled",
    "pre_off_profile", "pre_on_profile", "night_off_profile", "morning_on_profile",
}

_PROFILE_MAPPED = {
    "id", "key", "kind", "name", "label", "title", "active", "enabled",
    "time", "at", "offset_minutes", "offset", "devices", "targets",
}

#: Labels for the profile kinds Bobi is known to define. An unknown kind falls
#: back to a humanised version of its key, so a new profile still renders.
_PROFILE_LABELS = {
    "pre_off": "כיבוי לפני שבת",
    "pre_on": "הדלקה לפני שבת",
    "night_off": "כיבוי לילה",
    "night_on": "הדלקת לילה",
    "morning_on": "הדלקת בוקר",
    "morning_off": "כיבוי בוקר",
}


def normalize_shabbat(payload: Payload) -> BridgeShabbat:
    """`script.bobi_cc_shabbat`.

    The real bridge groups its data under `upcoming`, `profiles` and `drafts`.
    Times are looked up in `upcoming` first, then at the top level.
    """
    upcoming = payload.get("upcoming")
    if not isinstance(upcoming, dict):
        upcoming = payload.get("times") if isinstance(payload.get("times"), dict) else {}

    def time_of(*keys: str) -> str | None:
        return _text(_first(upcoming, *keys)) or _text(_first(payload, *keys))

    labels = _label_map(payload)

    profiles_raw, _ = _container(payload, "profiles")
    profiles = [
        profile
        for item in _as_items(profiles_raw, id_key="kind")
        if (profile := _shabbat_profile(item, labels))
    ]
    # A bridge that still sends the four named profiles is handled too.
    for key in ("pre_off_profile", "pre_on_profile", "night_off_profile", "morning_on_profile"):
        item = payload.get(key)
        if isinstance(item, dict):
            profile = _shabbat_profile({"kind": key.removesuffix("_profile"), **item}, labels)
            if profile:
                profiles.append(profile)

    drafts = payload.get("drafts")
    draft_owners = _draft_owners(drafts)

    ac_raw = payload.get("ac_temperatures")
    ac_temperatures: dict[str, str] = {}
    if isinstance(ac_raw, dict):
        for token, value in ac_raw.items():
            text = _text(value)
            if text is not None:
                # Resolve the token so the UI never shows a raw device token.
                ac_temperatures[labels.get(token, token)] = text

    return BridgeShabbat(
        candle_lighting=time_of("candle_lighting", "candles", "shabbat_start", "start"),
        havdalah=time_of("havdalah", "shabbat_end", "end"),
        parasha=time_of("parasha", "parsha"),
        pre_shabbat_offset_minutes=_int(
            _first(payload, "pre_shabbat_offset_minutes", "offset_minutes")
        ),
        profiles=profiles,
        ac_temperatures=ac_temperatures,
        has_draft=bool(draft_owners) or bool(_bool(payload.get("has_draft"))),
        draft_owners=draft_owners,
        writes_enabled=False,
        extra=_leftover(payload, _SHABBAT_MAPPED),
    )


def _label_map(payload: Payload) -> dict[str, str]:
    raw = _first(payload, "device_labels", "labels")
    if not isinstance(raw, dict):
        return {}
    return {key: text for key, value in raw.items() if (text := _text(value))}


def _shabbat_profile(item: Payload, labels: dict[str, str]) -> ShabbatProfile | None:
    kind = _text(_first(item, "kind", "id", "key"))
    if kind is None:
        return None
    label = _text(_first(item, "label", "name", "title"))
    return ShabbatProfile(
        id=kind,
        kind=kind,
        label=label or _PROFILE_LABELS.get(kind, _humanize(kind)),
        active=_bool(_first(item, "active", "enabled")),
        time=_text(_first(item, "time", "at")),
        offset_minutes=_int(_first(item, "offset_minutes", "offset")),
        devices=[
            labels.get(token, token)
            for token in _str_list(_first(item, "devices", "targets"))
        ],
        extra=_leftover(item, _PROFILE_MAPPED),
    )


def _draft_owners(drafts: Any) -> list[str]:
    """Who currently has an unsaved Shabbat draft."""
    owners: list[str] = []
    for item in _as_items(drafts, id_key="user"):
        # A draft entry may be a flag per user, or an object describing it.
        has_draft = _bool(_first(item, "has_draft", "value", "active"))
        owner = _text(_first(item, "user", "name", "owner", "id"))
        if owner and has_draft is not False:
            owners.append(owner)
    return owners


# --- rules ------------------------------------------------------------------
_RULE_MAPPED = {
    "id", "key", "name", "label", "title", "description", "summary", "enabled",
    "active", "kind", "type", "trigger", "schedule", "when", "targets",
    "devices", "last_triggered", "entity_id",
}


def normalize_rules(payload: Payload) -> BridgeRules:
    """`script.bobi_cc_rules`."""
    raw, _ = _container(payload, "rules", "items", "entries")
    rules = [rule for item in _as_items(raw) if (rule := _rule(item))]
    return BridgeRules(count=len(rules), rules=rules)


def _rule(item: Payload) -> BridgeRule | None:
    identifier = _text(_first(item, "id", "key", "name"))
    if identifier is None:
        return None
    return BridgeRule(
        id=identifier,
        name=_text(_first(item, "name", "label", "title")) or identifier,
        description=_text(_first(item, "description", "summary")),
        enabled=_bool(_first(item, "enabled", "active")),
        kind=_text(_first(item, "kind", "type")),
        trigger=_text(item.get("trigger")),
        schedule=_text(_first(item, "schedule", "when")),
        targets=_str_list(_first(item, "targets", "devices")),
        last_triggered=_text(item.get("last_triggered")),
        entity_id=_text(item.get("entity_id")),
        extra=_leftover(item, _RULE_MAPPED),
    )


# --- tasks ------------------------------------------------------------------
_TASK_MAPPED = {
    "id", "uid", "key", "title", "summary", "name", "owner", "user",
    "completed", "done", "status", "due", "due_date", "list_name", "list",
}


def normalize_tasks(payload: Payload) -> BridgeTasks:
    """`script.bobi_cc_tasks`.

    The real bridge groups tasks per user under `users`. They are flattened into
    one list with `owner` set from the group, which is what the UI renders; the
    owner names are kept so the screen can group them again if needed.
    """
    tasks: list[BridgeTask] = []
    owners: list[str] = []

    grouped, _ = _container(payload, "users", "by_user", "people")
    if grouped is not None:
        for group in _as_items(grouped, id_key="user"):
            owner = _text(_first(group, "user", "name", "owner", "id"))
            if owner and owner not in owners:
                owners.append(owner)
            # The list name lives on the group, so tasks inherit it.
            list_name = _text(_first(group, "list_name", "list"))
            raw_items, _ = _container(group, "tasks", "items", "todos", "entries")
            for item in _as_items(raw_items):
                task = _task(item, owner, list_name)
                if task:
                    tasks.append(task)

    if not tasks:
        # A flat `tasks` list is also accepted.
        flat, _ = _container(payload, "tasks", "items", "entries")
        for item in _as_items(flat):
            task = _task(item, None, None)
            if task:
                tasks.append(task)
                if task.owner and task.owner not in owners:
                    owners.append(task.owner)

    return BridgeTasks(count=len(tasks), tasks=tasks, owners=owners)


def _task(item: Payload, owner: str | None, list_name: str | None) -> BridgeTask | None:
    title = _text(_first(item, "title", "summary", "name"))
    identifier = _text(_first(item, "id", "uid", "key")) or title
    if identifier is None or title is None:
        return None

    status = _text(item.get("status"))
    completed = _bool(_first(item, "completed", "done"))
    if completed is None:
        completed = (status or "").lower() in {"completed", "done", "finished"}

    return BridgeTask(
        id=identifier,
        title=title,
        owner=_text(_first(item, "owner", "user")) or owner,
        completed=completed,
        status=status,
        due=_text(_first(item, "due", "due_date")),
        list_name=_text(_first(item, "list_name", "list")) or list_name,
        extra=_leftover(item, _TASK_MAPPED),
    )


# --- diagnostics ------------------------------------------------------------
_ISSUE_MAPPED = {
    "id", "key", "severity", "level", "title", "label", "message",
    "description", "component", "code", "entity_id", "entity_ids",
    "suggested_action", "action", "detail", "details",
}

_SEVERITIES = {"ok", "info", "warning", "error", "critical"}

#: `checks` values that read as a pass rather than a measurement.
_CHECK_LABELS = {
    "whatsapp": "WhatsApp",
    "config": "תצורה",
    "catalog_count": "מכשירים בקטלוג",
    "catalog_controllable": "מכשירים הניתנים לשליטה",
    "bridge": "גשר בובי",
}


def normalize_diagnostics(payload: Payload) -> BridgeDiagnostics:
    """`script.bobi_cc_diagnostics`.

    The real bridge sends `checks` as a **map** of name → value, mixing status
    words (`"WORKING"`) with plain figures (`catalog_count: 19`). Both become a
    check: a status word sets `ok`, a figure leaves it `None` and shows as
    informational. A list of check objects is accepted too.
    """
    issues = [
        issue
        for index, item in enumerate(_as_items(payload.get("issues")))
        if (issue := _issue(item, index))
    ]
    checks = [check for item in _as_items(payload.get("checks"), id_key="id")
              if (check := _check(item))]

    issue_count = _int(payload.get("issue_count"))
    return BridgeDiagnostics(
        ok=_bool(payload.get("ok")),
        issue_count=issue_count if issue_count is not None else len(issues),
        issues=issues,
        checks=checks,
    )


def _issue(item: Payload, index: int) -> BridgeIssue | None:
    title = _text(_first(item, "title", "label", "message", "description"))
    if title is None:
        return None

    # `code` repeats across issues of the same class (two unavailable devices
    # share `device_unavailable`), so it cannot be the key on its own. Qualify
    # it with the entity, then fall back to the position.
    identifier = _text(_first(item, "id", "key"))
    if identifier is None:
        code = _text(item.get("code"))
        entity = _text(item.get("entity_id"))
        identifier = ":".join(part for part in (code, entity) if part) or f"issue_{index}"

    severity = (_text(_first(item, "severity", "level")) or "warning").lower()
    if severity not in _SEVERITIES:
        severity = "warning"

    entity_ids = _str_list(item.get("entity_ids"))
    single = _text(item.get("entity_id"))
    if single and single not in entity_ids:
        entity_ids.insert(0, single)

    message = _text(_first(item, "message", "description"))
    return BridgeIssue(
        id=identifier,
        severity=severity,
        title=title,
        message=message if message != title else None,
        component=_text(item.get("component")),
        code=_text(item.get("code")),
        entity_ids=entity_ids,
        suggested_action=_text(_first(item, "suggested_action", "action")),
        detail=_text(_first(item, "detail", "details")),
        extra=_leftover(item, _ISSUE_MAPPED),
    )


def _check(item: Payload) -> DiagnosticCheck | None:
    identifier = _text(_first(item, "id", "key", "name"))
    if identifier is None:
        return None

    value = _first(item, "value", "state", "status", "result")
    ok = _bool(_first(item, "ok", "healthy"))
    if ok is None:
        ok = _bool(value)
    # A count is a measurement, not a pass/fail — do not colour it green.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        ok = None

    return DiagnosticCheck(
        id=identifier,
        label=_text(_first(item, "label", "title")) or _CHECK_LABELS.get(
            identifier, _humanize(identifier)
        ),
        ok=ok,
        value=_text(value),
        detail=_text(_first(item, "detail", "description")),
    )
