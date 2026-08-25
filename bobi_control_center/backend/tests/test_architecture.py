"""Automated guards for the rules in docs/architecture.md.

These are the tests that keep the project honest as it grows:

1. the frontend must never hard-code Home Assistant identifiers;
2. no secret may be committed;
3. Phase 1 must be incapable of writing to a real installation.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"
BACKEND_APP = REPO_ROOT / "backend" / "app"

#: Home Assistant domain prefixes that must not appear in frontend logic.
HA_DOMAIN_PATTERN = re.compile(
    r"\b(?:light|switch|climate|sensor|binary_sensor|camera|cover|vacuum|"
    r"media_player|input_text|input_boolean|input_number|input_datetime|"
    r"input_select|automation|script|scene|todo)\."
    r"[a-z_][a-z0-9_]{2,}\b"
)

#: Files allowed to mention such strings — they only ever display them.
FRONTEND_ALLOWLIST = {"types/api.ts"}


#: String and template literals. A hard-coded entity id is necessarily quoted,
#: which is what separates it from property access like ``automation.start_time``.
_ANY_LITERAL = re.compile(r"""(['"`])(.*?)\1""")


def scan_for_entity_ids(source: str) -> list[tuple[int, str]]:
    """Return ``(line_number, literal)`` for every entity id in a source file.

    Only quoted literals are considered, and comment lines are skipped.
    """
    found: list[tuple[int, str]] = []
    for number, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith(("//", "*", "#")):
            continue
        for _, value in _ANY_LITERAL.findall(line):
            if _ENTITY_ID_IN_STRING.match(value.strip()):
                found.append((number, value))
    return found


def _frontend_sources() -> list[Path]:
    """Application sources only.

    Tests and their fixtures are excluded: a fixture stands in for an API
    response, so it may legitimately contain the entity ids that a real response
    would carry — the same reason the backend's ``mock/`` package is exempt.
    """
    if not FRONTEND_SRC.is_dir():
        return []
    return [
        path
        for path in FRONTEND_SRC.rglob("*")
        if path.suffix in {".ts", ".tsx"}
        and ".test." not in path.name
        and "test" not in path.relative_to(FRONTEND_SRC).parts
    ]


def test_frontend_never_hardcodes_home_assistant_entity_ids() -> None:
    """The core architectural rule of the project.

    The frontend may *render* an ``advanced.entity_id`` handed to it by the API,
    but it must never contain one as a literal or branch on one.

    Only string and template literals are scanned: a hard-coded entity id is
    necessarily quoted, whereas ``automation.start_time`` is ordinary property
    access on a typed model and must not trip the guard.
    """
    sources = _frontend_sources()
    if not sources:
        pytest.skip("frontend not present in this checkout")

    offenders: list[str] = []
    for path in sources:
        relative = path.relative_to(FRONTEND_SRC).as_posix()
        if relative in FRONTEND_ALLOWLIST:
            continue
        for number, value in scan_for_entity_ids(path.read_text("utf-8")):
            offenders.append(f"{relative}:{number}: {value}")

    assert not offenders, (
        "Home Assistant identifiers must not appear in frontend code:\n"
        + "\n".join(offenders)
    )


def test_the_frontend_guard_actually_catches_a_violation() -> None:
    """Guard the guard, so a future refactor cannot quietly neuter it."""
    violating = "\n".join(
        [
            "const entity = 'climate.demo_living_room_ac';",
            'const helper = "input_text.bobi_local_schedule";',
            "const script = `script.bobi_local_schedule_parse`;",
        ]
    )
    assert len(scan_for_entity_ids(violating)) == 3

    # Ordinary frontend code must not trip it.
    clean = "\n".join(
        [
            "const when = automation.start_time;",
            "if (automation.crosses_midnight) return null;",
            "await api.post('/api/bobi/shabbat/confirm', { token });",
            "const op = 'automation.save';",
            "// climate.demo_living_room_ac in a comment is fine",
        ]
    )
    assert scan_for_entity_ids(clean) == []


#: An entity id inside a string literal, e.g. "climate.demo_living_room_ac".
#: Requiring an underscore in the object id keeps operation names such as
#: ``"automation.save"`` and file names such as ``"camera.png"`` from matching.
_ENTITY_ID_IN_STRING = re.compile(
    r"^(?:light|switch|climate|sensor|binary_sensor|camera|cover|vacuum|"
    r"media_player|input_text|input_boolean|input_number|input_datetime|"
    r"input_select|automation|script|scene|todo)\.[a-z0-9]+_[a-z0-9_]+"
)


def test_only_the_adapter_layer_speaks_home_assistant() -> None:
    """HA entity ids may only be written where HA is allowed to be known.

    Scans string literals rather than whole lines, so that ordinary attribute
    access (``automation.start_time``) and operation names (``"shabbat.save"``)
    are not mistaken for Home Assistant identifiers.

    The whole ``mock/`` package is exempt: fixtures stand in for what a real
    installation would return, and diagnostic ``technical_details`` are supposed
    to quote entity ids verbatim.
    """
    allowed_files = {
        "adapters/base.py",
        "adapters/mock.py",
        "adapters/real.py",
        "services/devices.py",
        "models/device.py",
    }
    offenders: list[str] = []
    for path in BACKEND_APP.rglob("*.py"):
        relative = path.relative_to(BACKEND_APP).as_posix()
        if relative in allowed_files or relative.startswith("mock/"):
            continue
        for number, value in scan_for_entity_ids(path.read_text("utf-8")):
            offenders.append(f"{relative}:{number}: {value}")

    assert not offenders, (
        "Home Assistant identifiers outside the adapter layer:\n" + "\n".join(offenders)
    )


def test_no_secrets_are_committed() -> None:
    """A committed .env, key file or long-lived token would fail this."""
    forbidden_files = [".env", "secrets.yaml", "id_rsa"]
    for name in forbidden_files:
        assert not (REPO_ROOT / name).exists(), f"{name} must never be committed"

    assert (REPO_ROOT / ".env.example").exists()
    example = (REPO_ROOT / ".env.example").read_text("utf-8")
    # The example must ship empty values, not real ones.
    for line in example.splitlines():
        if line.startswith("BOBI_HA_TOKEN") or line.startswith("BOBI_HA_URL"):
            assert line.split("=", 1)[1].strip() == ""


def test_mock_data_contains_no_real_phone_numbers() -> None:
    """Reject anything that looks like a dialable Israeli or E.164 number."""
    phone_pattern = re.compile(r"(?:\+\d{9,15})|(?:\b0\d{1,2}-?\d{7}\b)")
    offenders: list[str] = []
    for path in (BACKEND_APP / "mock").rglob("*.py"):
        for number, line in enumerate(path.read_text("utf-8").splitlines(), start=1):
            if phone_pattern.search(line):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, "mock data must not contain real phone numbers:\n" + "\n".join(
        offenders
    )


def test_phase_one_cannot_write_to_home_assistant() -> None:
    """Every write returns ``dry_run`` because the active adapter is read-only."""
    from app.adapters import MockHomeAssistantAdapter

    assert MockHomeAssistantAdapter.read_only is True


def test_probe_endpoint_hardcodes_would_execute_false() -> None:
    """Guard against a future refactor deriving this flag from input."""
    source = (BACKEND_APP / "services" / "bobi.py").read_text("utf-8")
    assert "result.would_execute = False" in source
