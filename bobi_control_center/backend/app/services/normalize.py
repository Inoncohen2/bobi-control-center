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

import contextlib
import logging
import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models.bridge import (
    AiStatus,
    BridgeCapabilities,
    BridgeCapability,
    BridgeDevice,
    BridgeDevices,
    BridgeDiagnostics,
    BridgeHealth,
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
    ConfigStatus,
    DeviceLimits,
    DiagnosticCheck,
    FeatureFlag,
    ProfileDevice,
    ShabbatAcTemperature,
    ShabbatProfile,
    StatusComponent,
    UsersSummary,
    WhatsAppStatus,
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


def _count(value: Any) -> int | None:
    """A figure, from a number or from the length of a collection.

    A boolean is not a figure: `active: true` means "yes", not "one".
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (list, dict)):
        return len(value)
    return _int(value)


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
    "ok", "healthy", "health", "is_healthy", "state", "status",
    "version", "uptime", "components", "counts", "writes_enabled", *_PROTOCOL_KEYS,
}


def normalize_status(payload: Payload) -> BridgeStatus:
    """`script.bobi_cc_status`.

    The real bridge reports rather more than a health list: WhatsApp
    connectivity, the AI fallback and its fast paths, how many household members
    are active, feature toggles and the health of Bobi's own configuration.
    Those are read into first-class sections rather than being flattened into
    `details`, where the dashboard could only print them as text.

    Each section is accepted nested (`{"whatsapp": {"connected": true}}`), bare
    (`{"whatsapp": "WORKING"}`) or flat-prefixed (`{"whatsapp_connected": true}`),
    because only the bridge decides which it sends. Whatever is left over still
    becomes a `details` row or a `counts` entry, so nothing is dropped.
    """
    used: set[str] = set()

    whatsapp, keys = _whatsapp_status(payload)
    used |= keys
    ai, keys = _ai_status(payload)
    used |= keys
    users, keys = _users_summary(payload)
    used |= keys
    config, keys = _config_status(payload)
    used |= keys
    features, keys = _feature_flags(payload)
    used |= keys

    components = [
        component
        for item in _as_items(payload.get("components"))
        if (component := _status_component(item))
    ]

    health = _health(payload, components, whatsapp, ai, config)
    if not components:
        # The real bridge sends no component list, so build the dashboard's top
        # row out of the sections it does send.
        components = _derived_components(health, whatsapp, ai, config)

    counts: dict[str, int] = {}
    raw_counts = payload.get("counts")
    if isinstance(raw_counts, dict):
        for key, value in raw_counts.items():
            number = _int(value)
            if number is not None:
                counts[key] = number

    details: dict[str, str] = {}
    for key, value in _leftover(payload, _STATUS_MAPPED | used).items():
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
        health=health,
        #: Mirrors `health.ok`, so an existing consumer of `ok` sees the
        #: resolved answer rather than the null it used to get.
        ok=health.ok,
        version=_text(_first(payload, "version", "bobi_version", "api_version")),
        uptime=_text(_first(payload, "uptime", "up_since", "started_at")),
        whatsapp=whatsapp,
        ai=ai,
        users=users,
        config=config,
        features=features,
        components=components,
        counts=counts,
        details=details,
        writes_enabled=False,
    )


#: Status words that answer "is Bobi healthy?", mapped to a canonical state.
#: Values that say yes or no and nothing more. A bridge reporting
#: `healthy: true` is not telling the household anything a sentence cannot.
_BOOLISH = frozenset({"true", "false", "1", "0", "yes", "no", "on", "off"})


def _health_reason(stated: Any, state: str) -> str:
    """Why the house is in this state, in Hebrew.

    This used to be `f"הגשר דיווח: {stated}"`, which put a Python literal —
    `True`, in English — on the dashboard as the headline explanation of the
    home's health. A boolean carries nothing a sentence does not, so it is
    said as a sentence; a real word from the bridge (`degraded`, `offline`) is
    still passed through, because that one does carry something.
    """
    word = str(stated).strip()
    if isinstance(stated, bool) or word.lower() in _BOOLISH:
        if state == "healthy":
            return "הגשר דיווח שהכול תקין"
        return "הגשר דיווח על תקלה" if state == "unhealthy" else "הגשר לא דיווח על מצב ברור"
    return f"הגשר דיווח: {word}"


#: What part of the house an issue is about, in Hebrew.
#:
#: The bridge names the component in its own words — `device`, `sensor`,
#: `whatsapp` — and the faults screen prints it on a chip beside the headline.
#: Two English words on a Hebrew screen, and both of them are Home Assistant's
#: vocabulary rather than anything the household said. A component this table
#: does not know is shown as it came: an unfamiliar word is still information,
#: and hiding it would leave the chip empty for no gain.
_COMPONENT_WORDS = {
    "device": "מכשיר",
    "devices": "מכשירים",
    "sensor": "חיישן",
    "sensors": "חיישנים",
    "battery": "סוללה",
    "camera": "מצלמה",
    "cameras": "מצלמות",
    "network": "רשת",
    "config": "תצורה",
    "configuration": "תצורה",
    "automation": "אוטומציה",
    "automations": "אוטומציות",
    "script": "סקריפט",
    "scripts": "סקריפטים",
    "scene": "סצנה",
    "scenes": "סצנות",
    "calendar": "יומן",
    "system": "מערכת",
    "bridge": "גשר",
    "integration": "אינטגרציה",
    "storage": "אחסון",
    "update": "עדכון",
    "updates": "עדכונים",
}


def _component_word(stated: str | None) -> str | None:
    if stated is None:
        return None
    return _COMPONENT_WORDS.get(stated.strip().lower(), stated)


_HEALTH_WORDS = {
    "healthy": "healthy", "ok": "healthy", "true": "healthy", "up": "healthy",
    "working": "healthy", "online": "healthy", "running": "healthy",
    "degraded": "degraded", "partial": "degraded", "warning": "degraded",
    "unhealthy": "unhealthy", "error": "unhealthy", "failed": "unhealthy",
    "down": "unhealthy", "offline": "unhealthy", "false": "unhealthy",
    "unknown": "unknown",
}


def _health(
    payload: Payload,
    components: list[StatusComponent],
    whatsapp: WhatsAppStatus | None,
    ai: AiStatus | None,
    config: ConfigStatus | None,
) -> BridgeHealth:
    """Resolve one overall answer, from authoritative information only.

    The real bridge does not send `ok`. It sends `healthy`, which used to fall
    through to `details` as the string `"True"` while `ok` stayed null — a
    question the API asked and then refused to answer.

    Two sources, in order:

    1. **What the bridge says about itself.** `ok`, `healthy`, `is_healthy`, or
       a status word. `_bool` already reads `"True"`, `"true"` and `1` alike,
       so a string boolean is handled without a special case.
    2. **The component states**, where only an *explicit* failure counts. A
       component the bridge could not resolve — `config` arriving with `ok:
       null` — leaves health unknown rather than dragging it to false. Nothing
       is inferred from an absence.

    `unknown` is a real answer, not a failure. It is never coerced to a
    boolean, and the UI must not render it as a problem.
    """
    # 1. The bridge's own statement.
    stated = _first(payload, "ok", "healthy", "is_healthy")
    nested = payload.get("health")
    if stated is None and isinstance(nested, dict):
        stated = _first(nested, "ok", "healthy", "status", "state", "value")
    if stated is None:
        stated = _first(payload, "status", "state")

    if stated is not None and not isinstance(stated, (dict, list)):
        word = str(stated).strip().lower()
        state = _HEALTH_WORDS.get(word)
        if state is None:
            # Not a health word, but `_bool` may still read it (1, "yes", "on").
            resolved = _bool(stated)
            state = "healthy" if resolved else "unhealthy" if resolved is False else None
        if state is not None:
            return BridgeHealth(
                status=state,
                ok=True if state == "healthy" else False if state == "unhealthy" else None,
                reason=_health_reason(stated, state),
            )

    # 2. Derived from the components, counting only explicit failures.
    known = [c for c in components if c.ok is not None] or [
        c for c in _derived_components(None, whatsapp, ai, config) if c.ok is not None
    ]
    failing = [c.name for c in known if c.ok is False]

    if not known:
        return BridgeHealth(
            status="unknown", ok=None, reason="הגשר לא דיווח על מצב כללי"
        )
    if not failing:
        return BridgeHealth(
            status="healthy", ok=True, reason="כל הרכיבים הידועים תקינים"
        )
    if len(failing) == len(known):
        return BridgeHealth(
            status="unhealthy", ok=False, reason=f"תקלה ב: {', '.join(failing)}"
        )
    return BridgeHealth(
        status="degraded", ok=False, reason=f"תקלה ב: {', '.join(failing)}"
    )


def _section(payload: Payload, *names: str) -> tuple[Payload, set[str]]:
    """Gather one status section, however the bridge chose to spell it.

    Returns the section's fields plus every top-level key consumed, so the
    caller can keep those out of the leftover `details` map.
    """
    section: Payload = {}
    used: set[str] = set()

    for name in names:
        if name not in payload:
            continue
        value = payload[name]
        if value is None:
            continue
        used.add(name)
        if isinstance(value, dict):
            for key, item in value.items():
                section.setdefault(key, item)
        elif isinstance(value, list):
            section.setdefault("items", value)
        else:
            # A bare scalar, e.g. {"whatsapp": "WORKING"}.
            section.setdefault("value", value)

    for key, value in payload.items():
        for name in names:
            if key.startswith(f"{name}_"):
                section.setdefault(key[len(name) + 1:], value)
                used.add(key)
                break

    return {key: value for key, value in section.items() if value is not None}, used


_WHATSAPP_MAPPED = {
    "value", "status", "state", "connected", "online", "linked", "label",
    "detail", "description", "message",
}


def _whatsapp_status(payload: Payload) -> tuple[WhatsAppStatus | None, set[str]]:
    section, used = _section(payload, "whatsapp", "whats_app")
    if not section:
        return None, used

    status = _text(_first(section, "status", "state", "value"))
    connected = _bool(_first(section, "connected", "online", "linked"))
    if connected is None:
        connected = _bool(status)

    return WhatsAppStatus(
        connected=connected,
        status=status,
        label=_text(section.get("label")) or _state_label(
            status, connected, yes="מחובר", no="מנותק"
        ),
        detail=_text(_first(section, "detail", "description", "message")),
        extra=_leftover(section, _WHATSAPP_MAPPED),
    ), used


_AI_MAPPED = {
    "value", "enabled", "active", "on", "status", "state", "fast_paths",
    "fastpaths", "fast_path", "fast_paths_enabled", "fast_paths_count",
    "fast_path_count", "label", "detail", "description", "message",
}

#: Fast-path keys the bridge may send at the top level rather than under `ai`.
_FAST_PATH_KEYS = (
    "fast_paths", "fastpaths", "fast_paths_enabled", "fast_paths_count",
    "fast_path_count",
)


def _ai_status(payload: Payload) -> tuple[AiStatus | None, set[str]]:
    section, used = _section(payload, "ai")
    for key in _FAST_PATH_KEYS:
        if key in payload and key not in used and payload[key] is not None:
            section.setdefault(key, payload[key])
            used.add(key)
    if not section:
        return None, used

    enabled = _bool(_first(section, "enabled", "active", "on", "value", "status", "state"))
    fast_enabled, fast_count, fast_names = _fast_paths(section)

    detail = _text(_first(section, "detail", "description", "message"))
    if detail is None and fast_count:
        detail = f"{fast_count} מסלולים מהירים"

    return AiStatus(
        enabled=enabled,
        fast_paths_enabled=fast_enabled,
        fast_paths_count=fast_count,
        fast_paths=fast_names,
        label=_text(section.get("label")) or _state_label(
            _text(_first(section, "status", "state")), enabled, yes="פעיל", no="כבוי"
        ),
        detail=detail,
        extra=_leftover(section, _AI_MAPPED),
    ), used


def _fast_paths(section: Payload) -> tuple[bool | None, int | None, list[str]]:
    """Read fast paths from a flag, a count, or a list of path names."""
    raw = _first(section, "fast_paths", "fastpaths", "fast_path")

    enabled: bool | None = None
    count: int | None = None
    names: list[str] = []

    if isinstance(raw, bool):
        enabled = raw
    elif isinstance(raw, (int, float)):
        count = int(raw)
    elif isinstance(raw, list):
        names = _str_list(raw)
        count = len(raw)
    elif isinstance(raw, dict):
        enabled = _bool(_first(raw, "enabled", "active"))
        count = _count(_first(raw, "count", "total"))
        names = _str_list(_first(raw, "paths", "names", "items", "list"))
        if count is None and names:
            count = len(names)
    elif raw is not None:
        enabled = _bool(raw)

    explicit_enabled = _bool(_first(section, "fast_paths_enabled"))
    if explicit_enabled is not None:
        enabled = explicit_enabled
    explicit_count = _count(_first(section, "fast_paths_count", "fast_path_count"))
    if explicit_count is not None:
        count = explicit_count

    if enabled is None and count is not None:
        enabled = count > 0
    return enabled, count, names


_USERS_MAPPED = {
    "items", "value", "names", "total", "count", "active", "active_count",
    "active_users", "admins", "admin", "admin_count", "admin_users",
}


def _users_summary(payload: Payload) -> tuple[UsersSummary | None, set[str]]:
    section, used = _section(payload, "users")
    for key in ("active_users", "admin_users", "admins"):
        if key in payload and key not in used and payload[key] is not None:
            section.setdefault(key.removesuffix("_users"), payload[key])
            used.add(key)
    if not section:
        return None, used

    names = _user_names(_first(section, "items", "names", "list"))
    total = _count(_first(section, "total", "count", "value"))
    if total is None and names:
        total = len(names)

    return UsersSummary(
        total=total,
        active=_count(_first(section, "active", "active_count", "active_users")),
        admins=_count(_first(section, "admins", "admin", "admin_count", "admin_users")),
        names=names,
        extra=_leftover(section, _USERS_MAPPED),
    ), used


def _user_names(raw: Any) -> list[str]:
    """Names out of a list of strings or a list of user objects."""
    if isinstance(raw, dict):
        raw = list(raw.values())
    if not isinstance(raw, list):
        return []
    names: list[str] = []
    for item in raw:
        name = (
            _text(_first(item, "name", "display_name", "id"))
            if isinstance(item, dict)
            else _text(item)
        )
        if name and name not in names:
            names.append(name)
    return names


_CONFIG_MAPPED = {
    "value", "ok", "valid", "healthy", "status", "state", "label", "detail",
    "description", "message",
}


def _config_status(payload: Payload) -> tuple[ConfigStatus | None, set[str]]:
    section, used = _section(payload, "config", "configuration")
    if not section:
        return None, used

    status = _text(_first(section, "status", "state", "value"))
    ok = _bool(_first(section, "ok", "valid", "healthy"))
    if ok is None:
        ok = _bool(status)

    return ConfigStatus(
        ok=ok,
        status=status,
        label=_text(section.get("label")) or _state_label(
            status, ok, yes="תקינה", no="דורשת טיפול"
        ),
        detail=_text(_first(section, "detail", "description", "message")),
        extra=_leftover(section, _CONFIG_MAPPED),
    ), used


#: Hebrew names for the feature toggles Bobi is known to report. An unknown
#: feature still renders, under a humanised version of its key.
_FEATURE_LABELS = {
    "whatsapp": "WhatsApp",
    "ai": "בינה מלאכותית",
    "ai_fallback": "AI fallback",
    "fast_paths": "מסלולים מהירים",
    "shabbat": "שעון שבת",
    "tasks": "משימות",
    "calendar": "יומן",
    "notifications": "התראות יזומות",
    "vision": "עיבוד תמונות",
    "cameras": "מצלמות",
    "scent": "מפיץ ריח",
    "vacuum": "שואב",
    "schedules": "תזמונים",
}


def _feature_flags(payload: Payload) -> tuple[list[FeatureFlag], set[str]]:
    """`features` as a map of name → flag, or a list of feature objects."""
    raw, key = _container(payload, "features", "feature_flags", "flags")
    used = {key} if key else set()

    flags: list[FeatureFlag] = []
    for item in _as_items(raw, id_key="id"):
        identifier = _text(_first(item, "id", "key", "name"))
        if identifier is None:
            continue
        flags.append(
            FeatureFlag(
                id=identifier,
                label=_text(_first(item, "label", "title"))
                or _FEATURE_LABELS.get(identifier, _humanize(identifier)),
                enabled=_bool(_first(item, "enabled", "value", "state", "active", "status")),
                detail=_text(_first(item, "detail", "description")),
            )
        )
    return flags, used


def _state_label(status: str | None, ok: bool | None, *, yes: str, no: str) -> str:
    """A readable label: the bridge's own word translated, or a yes/no."""
    if status is not None:
        return _STATE_WORDS.get(status.lower(), status)
    if ok is True:
        return yes
    if ok is False:
        return no
    return "לא ידוע"


#: Hebrew for each canonical health state.
_HEALTH_LABELS = {
    "healthy": "פעיל",
    "degraded": "פעיל חלקית",
    "unhealthy": "לא תקין",
    "unknown": "לא ידוע",
}


def _derived_components(
    health: BridgeHealth | None,
    whatsapp: WhatsAppStatus | None,
    ai: AiStatus | None,
    config: ConfigStatus | None,
) -> list[StatusComponent]:
    """The dashboard's health row, built from the sections the bridge sent.

    `health` is `None` while health is still being resolved *from* this row —
    the Bobi card is what health summarises, so including it would be circular.
    """
    components: list[StatusComponent] = []
    if whatsapp is not None:
        components.append(
            StatusComponent(
                id="whatsapp",
                name="WhatsApp",
                label=whatsapp.label or "לא ידוע",
                state=whatsapp.status,
                ok=whatsapp.connected,
                detail=whatsapp.detail,
            )
        )
    if ai is not None:
        components.append(
            StatusComponent(
                id="ai",
                name="בינה מלאכותית",
                label=ai.label or "לא ידוע",
                state=None,
                ok=ai.enabled,
                detail=ai.detail,
            )
        )
    if config is not None:
        components.append(
            StatusComponent(
                id="config",
                name="תצורה",
                label=config.label or "לא ידוע",
                state=config.status,
                ok=config.ok,
                detail=config.detail,
            )
        )

    # Bobi's own card leads the row — but only when there is something to say.
    # An empty payload must produce an empty screen, not a card invented out of
    # nothing.
    if health is not None and (components or health.status != "unknown"):
        components.insert(
            0,
            StatusComponent(
                id="bobi",
                name="בובי",
                label=_HEALTH_LABELS.get(health.status, "לא ידוע"),
                state=health.status,
                ok=health.ok,
                # The reason belongs to `health`, which the dashboard states
                # once at the top. Repeating it on the card says it twice.
                detail=None,
            ),
        )
    return components


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
        limits=_limits(item.get("limits")),
        last_changed=_text(item.get("last_changed")),
        extra=_leftover(item, _DEVICE_MAPPED),
    )


def _number(value: Any) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


_LIMIT_MAPPED = {
    "min", "max", "step",
    "min_temp", "max_temp", "min_temperature", "max_temperature",
    "temp_step", "target_temp_step", "temperature_step",
    "preset_modes", "fan_modes", "swing_modes", "hvac_modes", "modes",
    "min_kelvin", "max_kelvin", "min_color_temp_kelvin", "max_color_temp_kelvin",
    "min_brightness", "max_brightness",
    "intensity_min", "intensity_max", "min_intensity", "max_intensity",
    "scent_slots", "slots", "timer_max_seconds", "max_timer_seconds",
}

#: The list-valued limits, and where each is read from.
_LIMIT_LISTS = (
    ("preset_modes", ("preset_modes",)),
    ("fan_modes", ("fan_modes",)),
    ("swing_modes", ("swing_modes",)),
    ("hvac_modes", ("hvac_modes", "modes")),
    ("scent_slots", ("scent_slots", "slots")),
)


def _limits(raw: Any) -> DeviceLimits | None:
    """A device's constraints, kept whole.

    Bobi's catalog carries domain-specific limits — temperature ranges and mode
    lists for climate, colour temperature for lights, intensity, slots and a
    timer for the scent diffuser. Collapsing all of that into a bare
    min/max/step threw away exactly what Phase 3's editing controls will need,
    so every field is preserved and anything unrecognised lands in `extra`.

    `min`/`max`/`step` are still filled, from whichever domain range is the one
    a person would actually edit, so a generic slider keeps working.
    """
    if not isinstance(raw, dict) or not raw:
        return None

    min_temp = _number(_first(raw, "min_temp", "min_temperature"))
    max_temp = _number(_first(raw, "max_temp", "max_temperature"))
    temp_step = _number(_first(raw, "temp_step", "target_temp_step", "temperature_step"))
    min_kelvin = _number(_first(raw, "min_kelvin", "min_color_temp_kelvin"))
    max_kelvin = _number(_first(raw, "max_kelvin", "max_color_temp_kelvin"))
    min_brightness = _number(raw.get("min_brightness"))
    max_brightness = _number(raw.get("max_brightness"))
    intensity_min = _number(_first(raw, "intensity_min", "min_intensity"))
    intensity_max = _number(_first(raw, "intensity_max", "max_intensity"))

    generic_min = _number(raw.get("min"))
    generic_max = _number(raw.get("max"))
    generic_step = _number(raw.get("step"))
    if generic_min is None and generic_max is None:
        for low, high in (
            (min_temp, max_temp),
            (intensity_min, intensity_max),
            (min_brightness, max_brightness),
            (min_kelvin, max_kelvin),
        ):
            if low is not None or high is not None:
                generic_min, generic_max = low, high
                break
    if generic_step is None:
        generic_step = temp_step

    lists = {name: _str_list(_first(raw, *keys)) for name, keys in _LIMIT_LISTS}

    extra = _leftover(raw, _LIMIT_MAPPED)
    # A list of objects rather than of names is not something this contract can
    # represent, so keep the original instead of silently reporting none.
    for name, keys in _LIMIT_LISTS:
        if not lists[name]:
            for key in keys:
                if raw.get(key):
                    extra[key] = raw[key]

    return DeviceLimits(
        min=generic_min,
        max=generic_max,
        step=generic_step,
        min_temp=min_temp,
        max_temp=max_temp,
        temp_step=temp_step,
        min_kelvin=min_kelvin,
        max_kelvin=max_kelvin,
        min_brightness=min_brightness,
        max_brightness=max_brightness,
        intensity_min=intensity_min,
        intensity_max=intensity_max,
        timer_max_seconds=_int(_first(raw, "timer_max_seconds", "max_timer_seconds")),
        extra=extra,
        **lists,
    )


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
#: Where a map of air-conditioner token → temperature may appear. The real
#: bridge keeps it inside each profile rather than at the top level.
_AC_TEMPERATURE_KEYS = (
    "ac_temperatures", "ac_temps", "temperatures", "temps", "ac",
)

#: `HH:MM`, however the bridge said it.
#:
#: The Shabbat bridge is meant to publish a time of day, and now does. It did
#: not: it forwarded the `jewish_calendar` sensor, which is a UTC instant, so
#: the screen showed `2026-08-28T15:51:00+00:00` where a household wants
#: "18:51" — the wrong hour as well as the wrong shape, this house being three
#: hours ahead of UTC.
#:
#: The bridge is fixed; this is the second lock, because a time of day is what
#: the field means and a screen should not have to wonder. A timestamp that
#: carries its own offset is rendered in that offset — no timezone database is
#: consulted and none is needed, since the bridge speaks in the house's own
#: local time. Anything already shaped like a clock is left exactly as it is,
#: and anything unrecognised is passed through rather than blanked: an odd
#: value a household can see beats a dash it cannot explain.
def _clock(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if _CLOCK.match(text):
        return text[:5]
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return text
    # A stamp that arrived in UTC is not a time anybody here reads: 15:51Z is
    # 18:51 in this house, which is the whole bug. Convert it where the system
    # has a timezone database, and fall back to its own offset where it does
    # not — the add-on's base image is not guaranteed to ship one, and a
    # missing tzdata must not turn a clock into a stack trace.
    if moment.utcoffset() == _UTC_OFFSET:
        with contextlib.suppress(ZoneInfoNotFoundError, KeyError, ValueError):
            moment = moment.astimezone(ZoneInfo(_HOUSE_TZ))
    return moment.strftime("%H:%M")


_CLOCK = re.compile(r"^([01]\d|2[0-3]):[0-5]\d(:[0-5]\d)?$")

#: Where this house is, used only to rescue a bridge that sent UTC.
_HOUSE_TZ = "Asia/Jerusalem"
_UTC_OFFSET = timedelta(0)


_SHABBAT_MAPPED = {
    "upcoming", "times", "profiles", "drafts", "candle_lighting", "havdalah",
    "parasha", "parsha", "hebrew_date", "holiday",
    "candle_lighting_at", "havdalah_at",
    "pre_shabbat_offset_minutes", "pre_offset_minutes",
    "offset_minutes", *_AC_TEMPERATURE_KEYS,
    "device_labels", "labels", "has_draft", "writes_enabled",
    "pre_off_profile", "pre_on_profile", "night_off_profile", "morning_on_profile",
}

_PROFILE_MAPPED = {
    "id", "key", "kind", "name", "label", "title", "active", "enabled",
    "time", "at", "offset_minutes", "offset", "devices", "targets", "tokens",
    "device_tokens", *_AC_TEMPERATURE_KEYS,
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

    # The real bridge carries the pre-Shabbat offset inside `upcoming`, under a
    # shorter name than the canonical one.
    offset_keys = ("pre_offset_minutes", "pre_shabbat_offset_minutes", "offset_minutes")
    pre_offset = _int(_first(upcoming, *offset_keys))
    if pre_offset is None:
        pre_offset = _int(_first(payload, *offset_keys))

    return BridgeShabbat(
        candle_lighting=_clock(time_of("candle_lighting", "candles", "shabbat_start", "start")),
        havdalah=_clock(time_of("havdalah", "shabbat_end", "end")),
        candle_lighting_at=time_of("candle_lighting_at"),
        havdalah_at=time_of("havdalah_at"),
        parasha=time_of("parasha", "parsha"),
        hebrew_date=time_of("hebrew_date", "hebrew_day"),
        holiday=time_of("holiday", "yom_tov") or None,
        pre_shabbat_offset_minutes=pre_offset,
        profiles=profiles,
        ac_temperatures=_collect_ac_temperatures(payload, upcoming, profiles_raw, labels),
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
        devices=_profile_devices(
            _first(item, "devices", "targets", "tokens", "device_tokens"), labels
        ),
        extra=_leftover(item, _PROFILE_MAPPED),
    )


def _profile_devices(raw: Any, labels: dict[str, str]) -> list[ProfileDevice]:
    """Resolve a profile's device tokens into id + label pairs.

    The bridge lists a profile's devices as its own short tokens (`led_salon`),
    which mean nothing to a household member, and supplies a `device_labels` map
    to translate them. Both halves are kept: the label is what the screen shows,
    and the token is what Phase 3 will have to send back to change the profile.
    """
    entries: list[Any]
    if isinstance(raw, dict):
        entries = [{"id": key, "label": value} for key, value in raw.items()]
    elif isinstance(raw, list):
        entries = raw
    elif raw is None:
        entries = []
    else:
        entries = [raw]

    devices: list[ProfileDevice] = []
    seen: set[str] = set()
    for entry in entries:
        if isinstance(entry, dict):
            token = _text(_first(entry, "id", "token", "key", "device", "entity_id"))
            label = _text(_first(entry, "label", "name"))
        else:
            token = _text(entry)
            label = None
        if token is None or token in seen:
            continue
        seen.add(token)
        devices.append(
            ProfileDevice(id=token, label=label or labels.get(token) or _humanize(token))
        )
    return devices


def _collect_ac_temperatures(
    payload: Payload, upcoming: Payload, profiles_raw: Any, labels: dict[str, str]
) -> list[ShabbatAcTemperature]:
    """Gather the air-conditioner temperatures from wherever the bridge keeps them.

    The real bridge does not send a top-level `ac_temperatures` map: each
    profile carries its own, which is why this list came back empty while the
    values sat unread. They are collected from the top level, from `upcoming`
    and from every profile, then de-duplicated by device.

    **First value wins**, in that order. Two profiles disagreeing about one air
    conditioner is a contradiction this layer cannot resolve, and picking a
    winner arbitrarily — or listing the device twice — would both be worse than
    reporting the first reading deterministically.
    """
    pairs: list[tuple[str | None, Any]] = []
    for source in (payload, upcoming):
        for key in _AC_TEMPERATURE_KEYS:
            pairs.extend(_ac_pairs(source.get(key)))
    for item in _as_items(profiles_raw, id_key="kind"):
        for key in _AC_TEMPERATURE_KEYS:
            pairs.extend(_ac_pairs(item.get(key)))

    temperatures: list[ShabbatAcTemperature] = []
    seen: set[str] = set()
    for token, value in pairs:
        text = _text(value)
        if token is None or text is None or token in seen:
            continue
        seen.add(token)
        temperatures.append(
            ShabbatAcTemperature(
                id=token,
                label=labels.get(token) or _humanize(token),
                # A setting the bridge does not express as a number — "auto",
                # say — keeps its text rather than being reported as a value.
                temperature=_number(value),
                text=text,
            )
        )
    return temperatures


def _ac_pairs(raw: Any) -> list[tuple[str | None, Any]]:
    """`(device token, temperature)` out of a map or a list of objects.

    Both the token and its label travel with the temperature, because a bare
    `{token: degrees}` map loses the device the moment the token is translated
    for display.
    """
    if isinstance(raw, dict):
        return list(raw.items())
    if isinstance(raw, list):
        return [
            (
                _text(_first(item, "id", "token", "device", "key", "entity_id")),
                _first(item, "temperature", "temp", "value", "degrees"),
            )
            for item in raw
            if isinstance(item, dict)
        ]
    return []


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
        component=_component_word(_text(item.get("component"))),
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
