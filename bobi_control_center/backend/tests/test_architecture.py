"""Structural guards for the Phase 2 rules.

These keep the project honest as it grows:

1. the frontend must never hard-code Home Assistant identifiers;
2. no secret, token or phone number may be committed;
3. Phase 2 must be structurally incapable of writing to Home Assistant;
4. the app must be a valid Home Assistant apps repository.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

APP_ROOT = Path(__file__).resolve().parents[2]  # bobi_control_center/
REPO_ROOT = APP_ROOT.parent
FRONTEND_SRC = APP_ROOT / "frontend" / "src"
BACKEND_APP = APP_ROOT / "backend" / "app"

#: An entity id inside a string literal, e.g. "climate.demo_living_room".
#: Requiring an underscore in the object id keeps operation names such as
#: "automation.save" and file names such as "camera.png" from matching.
_ENTITY_ID_IN_STRING = re.compile(
    r"^(?:light|switch|climate|sensor|binary_sensor|camera|cover|vacuum|"
    r"media_player|input_text|input_boolean|input_number|input_datetime|"
    r"input_select|automation|script|scene|todo|person)\.[a-z0-9]+_[a-z0-9_]+"
)

#: String and template literals.
_ANY_LITERAL = re.compile(r"""(['"`])(.*?)\1""")


def scan_for_entity_ids(source: str) -> list[tuple[int, str]]:
    """Return `(line_number, literal)` for every entity id in a source file.

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


_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"^\s*//.*$", re.MULTILINE)
_JSX_COMMENT = re.compile(r"\{/\*.*?\*/\}", re.DOTALL)


def strip_comments(source: str) -> str:
    """Remove TS/JSX comments.

    The guards below search for forbidden strings, and a comment *explaining*
    why something is forbidden must not itself trip the check.
    """
    source = _JSX_COMMENT.sub("", source)
    source = _BLOCK_COMMENT.sub("", source)
    return _LINE_COMMENT.sub("", source)


def _frontend_sources() -> list[Path]:
    """Application sources only; tests and fixtures stand in for API responses."""
    if not FRONTEND_SRC.is_dir():
        return []
    return [
        path
        for path in FRONTEND_SRC.rglob("*")
        if path.suffix in {".ts", ".tsx"}
        and ".test." not in path.name
        and "test" not in path.relative_to(FRONTEND_SRC).parts
    ]


# --- the architectural rule -------------------------------------------------
def test_frontend_never_hardcodes_home_assistant_entity_ids() -> None:
    """The frontend may render an entity id it was handed, never contain one."""
    sources = _frontend_sources()
    if not sources:
        pytest.skip("frontend not present in this checkout")

    offenders: list[str] = []
    for path in sources:
        relative = path.relative_to(FRONTEND_SRC).as_posix()
        for number, value in scan_for_entity_ids(strip_docstrings(path.read_text("utf-8"))):
            offenders.append(f"{relative}:{number}: {value}")

    assert not offenders, (
        "Home Assistant identifiers must not appear in frontend code:\n"
        + "\n".join(offenders)
    )


def strip_docstrings(source: str) -> str:
    """Blank out triple-quoted blocks, keeping line numbers intact.

    A service name inside a docstring documents the contract; a service name in
    code calls it. Only the second is a leak, and only the second survives this.
    """
    out: list[str] = []
    fence: str | None = None
    for line in source.splitlines():
        if fence is None:
            for quote in ('"""', "'''"):
                if quote in line:
                    before, _, rest = line.partition(quote)
                    if quote in rest:  # opened and closed on one line
                        out.append(before)
                    else:
                        fence = quote
                        out.append(before)
                    break
            else:
                out.append(line)
        else:
            if fence in line:
                fence = None
            out.append("")
    return "\n".join(out)


def test_only_the_adapter_layer_speaks_home_assistant() -> None:
    """Entity ids may only be written where Home Assistant may be known.

    The `mock/` package is exempt: its fixtures stand in for what a real bridge
    would return.
    """
    # The bridge-knowing layer: base.py declares the contract, real.py and
    # real_management.py are the transport, management.py is the write seam, and
    # normalize.py maps raw responses onto the canonical models. They
    # necessarily name the services involved — including, in a comment, the
    # `todo.*` services this app must never call.
    allowed_files = {
        "adapters/base.py",
        "adapters/real.py",
        "adapters/real_management.py",
        "adapters/management.py",
        "models/bridge.py",
        "services/normalize.py",
    }

    offenders: list[str] = []
    for path in BACKEND_APP.rglob("*.py"):
        relative = path.relative_to(BACKEND_APP).as_posix()
        if relative in allowed_files or relative.startswith("mock/"):
            continue
        for number, value in scan_for_entity_ids(strip_docstrings(path.read_text("utf-8"))):
            offenders.append(f"{relative}:{number}: {value}")

    assert not offenders, (
        "Home Assistant identifiers outside the adapter layer:\n" + "\n".join(offenders)
    )


def test_the_guard_actually_catches_a_violation() -> None:
    """Guard the guard, so a refactor cannot quietly neuter it."""
    violating = "\n".join(
        [
            "const entity = 'climate.demo_living_room';",
            'const helper = "input_text.bobi_local_schedule";',
            "const script = `script.bobi_local_schedule_parse`;",
        ]
    )
    assert len(scan_for_entity_ids(violating)) == 3

    clean = "\n".join(
        [
            "const when = rule.last_triggered;",
            "await api.post('/api/bobi/probe', { text });",
            "const op = 'automation.save';",
            "// climate.demo_living_room in a comment is fine",
        ]
    )
    assert scan_for_entity_ids(clean) == []


# --- the frontend must never reach Home Assistant directly ------------------
def test_frontend_never_references_the_supervisor_or_a_hardcoded_host() -> None:
    """React → FastAPI → Home Assistant. Never React → Supervisor."""
    forbidden = [
        "supervisor/core",
        "SUPERVISOR_TOKEN",
        "homeassistant.local",
        "hassio_ingress",
        "http://localhost:8123",
        "Bearer ",
    ]
    offenders: list[str] = []
    for path in _frontend_sources():
        # Comments explaining the Ingress prefix must not trip the check.
        text = strip_comments(path.read_text("utf-8"))
        relative = path.relative_to(FRONTEND_SRC).as_posix()
        for needle in forbidden:
            if needle in text:
                offenders.append(f"{relative}: {needle}")

    assert not offenders, "frontend must not reference Home Assistant directly:\n" + "\n".join(
        offenders
    )


def test_frontend_builds_api_urls_relative_to_the_app_root() -> None:
    """Ingress serves the app from a generated prefix that cannot be assumed."""
    client = (FRONTEND_SRC / "api" / "client.ts").read_text("utf-8")
    assert "resolveBasePath" in client
    assert "location.pathname" in client
    # No absolute origin may be baked into request URLs.
    assert "http://" not in client.replace("http://localhost", "")


# --- secrets ----------------------------------------------------------------
def test_no_secrets_are_committed() -> None:
    for name in (".env", "secrets.yaml", "id_rsa", "token.txt"):
        assert not (REPO_ROOT / name).exists(), f"{name} must never be committed"


def test_no_supervisor_token_value_appears_anywhere() -> None:
    """The token may be *named* in code; a value must never be assigned to it."""
    assignment = re.compile(r"SUPERVISOR_TOKEN\s*[:=]\s*['\"][^'\"]{8,}['\"]")
    offenders: list[str] = []

    for path in [*BACKEND_APP.rglob("*.py"), *_frontend_sources()]:
        for number, line in enumerate(path.read_text("utf-8").splitlines(), start=1):
            if assignment.search(line):
                offenders.append(f"{path.name}:{number}")

    assert not offenders, "a SUPERVISOR_TOKEN value is hard-coded:\n" + "\n".join(offenders)


def test_mock_data_contains_no_real_phone_numbers() -> None:
    phone = re.compile(r"(?:\+\d{9,15})|(?:\b0\d{1,2}-?\d{7}\b)")
    offenders: list[str] = []
    for path in (BACKEND_APP / "mock").rglob("*.py"):
        for number, line in enumerate(path.read_text("utf-8").splitlines(), start=1):
            if phone.search(line):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, "mock data must not contain phone numbers:\n" + "\n".join(offenders)


def test_authorization_headers_are_never_logged() -> None:
    """The header is built in one place and never handed to a logger."""
    real = (BACKEND_APP / "adapters" / "real.py").read_text("utf-8")
    for line in real.splitlines():
        if "logger." in line:
            assert "header" not in line.lower()
            assert "Authorization" not in line
            assert "_token" not in line


def test_response_bodies_are_only_logged_in_debug_mode() -> None:
    real = (BACKEND_APP / "adapters" / "real.py").read_text("utf-8")
    # Every payload log sits behind the debug flag.
    for index, line in enumerate(real.splitlines()):
        if "logger.debug" in line and "payload" in line:
            preceding = real.splitlines()[max(0, index - 2) : index]
            assert any("_debug_http" in p for p in preceding)


# --- read-only guarantee ----------------------------------------------------
def test_unrestricted_writes_stay_off() -> None:
    """Phase 3A adds management, not a general permission to write."""
    from app.adapters import MockHomeAssistantAdapter, RealHomeAssistantAdapter

    assert RealHomeAssistantAdapter.writes_enabled is False
    assert MockHomeAssistantAdapter.writes_enabled is False


def test_the_mock_adapter_declares_no_write_bridge() -> None:
    """Mock mode never writes: there is no Home Assistant there to write to."""
    from app.adapters import MockHomeAssistantAdapter

    assert MockHomeAssistantAdapter().management_bridge() is None


def test_nothing_in_the_app_can_set_the_master_write_switch() -> None:
    """Home Assistant owns the switch. This application reads it and stops there.

    Enabling writes is a Home Assistant-side decision taken after its own
    end-to-end testing, so no endpoint, service or setting here may assign it.
    """
    for name in ("api/manage.py", "services/manage.py", "adapters/real_management.py"):
        code = strip_docstrings(strip_comments((BACKEND_APP / name).read_text("utf-8")))
        for assignment in ("writes_enabled=True", "writes_enabled = True", '"writes_enabled": True'):
            assert assignment not in code, f"{name} must not set the master switch"

    # The write services are only ever reached from apply().
    bridge = strip_docstrings((BACKEND_APP / "adapters" / "real_management.py").read_text("utf-8"))
    for service in ("TASK_ADD_COMMIT", "TASK_UPDATE_COMMIT", "FEATURE_COMMIT"):
        # Each appears once as a constant and once at its single call site.
        assert bridge.count(service) <= 3, f"{service} is reached from too many places"


def test_the_adapter_interface_declares_no_write_method() -> None:
    """Writing is not something an adapter can implement.

    The abstract surface is still read-only. A write path arrives only as a
    `ManagementBridge` an adapter hands back, which Home Assistant has to
    declare — never as a method someone can fill in here.
    """
    import inspect

    from app.adapters.base import HomeAssistantAdapter

    abstract = {
        name
        for name, member in inspect.getmembers(HomeAssistantAdapter, inspect.isfunction)
        if getattr(member, "__isabstractmethod__", False)
    }
    assert abstract == {
        "connection_info",
        "get_status",
        "get_devices",
        "get_capabilities",
        "get_users",
        "get_shabbat",
        "get_rules",
        "get_tasks",
        "get_diagnostics",
        "probe",
    }


def test_management_cannot_be_switched_on_by_configuration() -> None:
    """No setting, flag or environment variable may enable writes."""
    from app.config import Settings

    fields = set(Settings.model_fields)
    for name in fields:
        assert "write" not in name.lower(), f"a settings field must not gate writes: {name}"
        assert "manage" not in name.lower(), f"a settings field must not gate writes: {name}"

    # And the seam itself reads nothing from the process environment.
    source = (BACKEND_APP / "adapters" / "management.py").read_text("utf-8")
    for reader in ("os.environ", "os.getenv", "getenv(", "import os"):
        assert reader not in source, f"the write seam must not read configuration: {reader}"


def test_management_writes_only_through_declared_operations() -> None:
    """No management route or service may name a Home Assistant service."""
    forbidden = ("todo.", "input_boolean.", "call_service", "homeassistant.")
    for name in ("api/manage.py", "services/manage.py", "models/manage.py"):
        code = strip_docstrings(strip_comments((BACKEND_APP / name).read_text("utf-8")))
        for token in forbidden:
            assert token not in code, f"{name} must not reach a raw HA service: {token}"


def test_every_non_get_route_is_auth_a_probe_or_a_managed_change() -> None:
    """Enumerate the published surface: nothing writes outside known flows.

    Read from the OpenAPI schema rather than `app.routes`, because an included
    router appears there as one opaque entry — the schema is what a client can
    actually reach.
    """
    from app.main import create_app

    paths = create_app().openapi()["paths"]
    non_get = {
        (path, method.upper())
        for path, methods in paths.items()
        for method in methods
        if method.upper() not in {"GET", "HEAD", "OPTIONS"}
    }

    assert non_get == {
        ("/api/auth/login", "POST"),
        ("/api/auth/logout", "POST"),
        ("/api/bobi/probe", "POST"),
        ("/api/bobi/manage/{resource}/preview", "POST"),
        ("/api/bobi/manage/{resource}/commit", "POST"),
    }


def test_a_commit_cannot_run_without_a_confirmed_preview() -> None:
    """The guard lives in the service, so no caller can route around it."""
    source = (BACKEND_APP / "services" / "manage.py").read_text("utf-8")
    assert "raise ConfirmationRequiredError" in source
    assert "stored.consumed = True" in source


def test_probe_hardcodes_would_execute_false() -> None:
    """Guard against a refactor deriving this flag from bridge input.

    Normalization is where a probe response is assembled, so that is where the
    invariant has to be asserted.
    """
    source = (BACKEND_APP / "services" / "normalize.py").read_text("utf-8")
    assert "would_execute=False" in source
    # And the model itself defaults to the safe value.
    model = (BACKEND_APP / "models" / "bridge.py").read_text("utf-8")
    assert "would_execute: bool = False" in model


#: Collection names the raw bridge uses. The backend normalizes them away, so
#: their appearance in frontend code would mean normalization leaked upward.
_RAW_BRIDGE_KEYS = ("entries", "registry", "upcoming", "drafts", "service_response")

#: `Object.entries(x)` and `map.entries()` are standard JavaScript. A bridge
#: field would be *read* as a property, never called, so calls are excluded.
_JS_ENTRIES_CALL = re.compile(r"\.entries\s*\(")


def test_normalization_is_the_only_place_that_knows_bridge_field_names() -> None:
    """React must receive one clean schema, not the raw bridge structure."""
    offenders: list[str] = []
    for path in _frontend_sources():
        code = _JS_ENTRIES_CALL.sub(".__call__(", strip_comments(path.read_text("utf-8")))
        relative = path.relative_to(FRONTEND_SRC).as_posix()
        for key in _RAW_BRIDGE_KEYS:
            # Either read as a property or written as a literal key.
            if re.search(rf"[.\['\"]{key}\b", code):
                offenders.append(f"{relative}: {key}")

    assert not offenders, (
        "the frontend must not touch raw bridge field names:\n" + "\n".join(offenders)
    )


def test_the_frontend_cannot_write_without_a_preview() -> None:
    """The commit guard lives in one hook, so no screen can route around it."""
    hook = strip_comments(
        (FRONTEND_SRC / "features" / "manage" / "useManagedChange.ts").read_text("utf-8")
    )
    # A commit without a valid preview returns early.
    assert "if (!preview?.preview_id || !preview.valid) return;" in hook
    # And every commit states the confirmation explicitly.
    assert "confirmed: true" in hook

    # No screen may call the commit endpoint itself.
    for path in _frontend_sources():
        if path.parts[-2:] == ("manage", "useManagedChange.ts"):
            continue
        code = strip_comments(path.read_text("utf-8"))
        assert "commitChange" not in code or "api/bobi" in path.as_posix(), (
            f"{path.name} must commit through useManagedChange, not directly"
        )


def test_a_destructive_change_needs_more_than_a_click() -> None:
    dialog = strip_comments(
        (FRONTEND_SRC / "features" / "manage" / "ChangeDialog.tsx").read_text("utf-8")
    )
    # The confirm button is disabled until the typed word matches.
    assert "wordMatches" in dialog
    assert "disabled={!preview?.valid || !wordMatches}" in dialog


def test_the_preview_and_the_commit_are_labelled_differently() -> None:
    """A user must never mistake "this is what would happen" for "done"."""
    dialog = (FRONTEND_SRC / "features" / "manage" / "ChangeDialog.tsx").read_text("utf-8")
    assert "'תצוגה מקדימה'" in dialog
    assert "'ביצוע'" in dialog
    for outcome in ("השינוי בוצע ואומת", "השינוי בוצע אך לא הצלחנו לאמת", "השינוי לא בוצע"):
        assert outcome in (BACKEND_APP / "services" / "manage.py").read_text("utf-8"), outcome


def test_the_unavailable_message_is_the_agreed_wording() -> None:
    seam = (BACKEND_APP / "adapters" / "management.py").read_text("utf-8")
    assert 'UNAVAILABLE_MESSAGE = "ניהול עדיין לא הופעל ב-Home Assistant"' in seam


def test_the_frontend_names_no_raw_home_assistant_service() -> None:
    """The browser talks to this backend, never to a `todo.*` or `input_boolean.*`."""
    offenders: list[str] = []
    for path in _frontend_sources():
        code = strip_comments(path.read_text("utf-8"))
        for name in ("todo.add_item", "todo.update_item", "todo.remove_item", "input_boolean."):
            if name in code:
                offenders.append(f"{path.relative_to(FRONTEND_SRC).as_posix()}: {name}")

    assert not offenders, "the frontend must not name a Home Assistant service:\n" + "\n".join(
        offenders
    )


def test_the_frontend_offers_no_way_to_enable_writes() -> None:
    """The master switch is Home Assistant's. The UI reads it and stops there."""
    for path in _frontend_sources():
        code = strip_comments(path.read_text("utf-8"))
        for attempt in (
            "writes_enabled: true",
            "writes_enabled=true",
            '"writes_enabled": true',
            "setWritesEnabled",
            "enableWrites",
        ):
            assert attempt not in code, f"{path.name} must not enable writes"

    # And no API function posts to anything that could.
    client = strip_comments((FRONTEND_SRC / "api" / "bobi.ts").read_text("utf-8"))
    posts = {line for line in client.splitlines() if "api.post" in line}
    for line in posts:
        assert any(
            allowed in line for allowed in ("/probe", "/preview", "/commit")
        ), f"unexpected write call: {line.strip()}"


def test_writes_disabled_is_shown_as_a_disabled_feature() -> None:
    """Not an error state: the same sentence, and no failure wording."""
    notice = (FRONTEND_SRC / "features" / "manage" / "ManagementNotice.tsx").read_text("utf-8")
    assert "ניהול עדיין לא הופעל ב-Home Assistant" in notice
    # It renders through the read-only affordance, not the error boundary.
    assert "ReadOnlyNotice" in notice
    assert "ErrorState" not in notice


def test_an_inert_control_says_where_the_working_one_is() -> None:
    """A row that does not write must point at the control that does.

    The wording used to promise a later phase, and that phase arrived: these
    screens carry a live "שליטה" section driven by the contract. A row saying
    editing comes later while a working control sits on the same page is worse
    than no label — it tells a person not to bother scrolling, which is exactly
    how a fully wired devices screen came to look like a catalogue.
    """
    read_only = (FRONTEND_SRC / "components" / "ui" / "ReadOnly.tsx").read_text("utf-8")
    assert "שליטה" in read_only
    assert "בשלב הבא" not in read_only


def test_no_screen_promises_a_later_phase_for_a_family_that_can_be_written() -> None:
    """A hard-coded sentence that contradicts the contract is the one thing this
    architecture exists to avoid: the bridge says what is possible, and a page
    that asserts otherwise is wrong the day the bridge ships. Five screens said
    "coming in the next stage" while carrying a working managed section
    underneath, and a person reading the top of the page believed them."""
    for name in ("DevicesPage", "RulesPage", "ShabbatPage", "UsersPage", "SettingsPage"):
        page = (FRONTEND_SRC / "pages" / f"{name}.tsx").read_text("utf-8")
        assert "ManagedSection" in page, name
        # A banner over the whole screen is the claim that cannot be true here.
        # One row of it still may be — the Shabbat drafts have no bridge and say
        # so — so this is about the screen-wide notice, not the word.
        assert "ReadOnlyNotice" not in page, name


def test_test_center_has_no_execute_control() -> None:
    """The Test Center must offer probing and nothing else."""
    page = (FRONTEND_SRC / "pages" / "TestCenterPage.tsx").read_text("utf-8")
    assert "בדוק בלי לבצע" in page
    assert "בדיקה בלבד — לא בוצעה שום פעולה" in page

    code = strip_comments(page)
    for forbidden in ("בצע עכשיו", "הפעל עכשיו", "execute", "runNow"):
        assert forbidden not in code


# --- Home Assistant apps repository -----------------------------------------
def test_repository_manifest_exists_and_is_valid() -> None:
    manifest = REPO_ROOT / "repository.yaml"
    assert manifest.exists(), "a custom apps repository needs repository.yaml at its root"

    data = yaml.safe_load(manifest.read_text("utf-8"))
    assert data["name"]
    assert data["url"].startswith("https://")


def test_app_config_is_valid() -> None:
    config = yaml.safe_load((APP_ROOT / "config.yaml").read_text("utf-8"))

    assert config["slug"] == "bobi_control_center"
    assert config["name"] == "Bobi Control Center"
    assert config["version"]
    assert config["arch"]

    # Ingress, on the required port, with no published host port.
    assert config["ingress"] is True
    assert config["ingress_port"] == 8099
    assert "ports" not in config, "the app must not expose an external port"

    assert config["panel_title"] == "Bobi"
    assert config["panel_icon"] == "mdi:robot-outline"
    assert config["startup"] == "application"
    assert config["boot"] == "auto"

    # Needed for SUPERVISOR_TOKEN to be injected.
    assert config["homeassistant_api"] is True

    # A Cloudflare hostname reaches the app only through the internal Docker
    # network. External auth is opt-in and stores a salted hash, not a password.
    assert config["options"]["external_hostname"] == ""
    assert config["options"]["external_password_hash"] == ""
    assert config["schema"]["external_password_hash"] == "password?"

    assert config["watchdog"].endswith("/health")


def test_the_build_context_is_self_contained() -> None:
    """The Dockerfile must not reference anything outside the app directory."""
    dockerfile = (APP_ROOT / "Dockerfile").read_text("utf-8")

    for line in dockerfile.splitlines():
        stripped = line.strip()
        if stripped.startswith("COPY") and "--from=" not in stripped:
            for token in stripped.split()[1:-1]:
                assert not token.startswith(("..", "/")), f"escapes the context: {stripped}"

    # Everything the Dockerfile copies must actually be here.
    assert (APP_ROOT / "frontend" / "package.json").exists()
    assert (APP_ROOT / "backend" / "requirements.txt").exists()
    assert (APP_ROOT / "run.sh").exists()


def test_the_app_listens_on_the_ingress_port() -> None:
    run_sh = (APP_ROOT / "run.sh").read_text("utf-8")
    assert "--port 8099" in run_sh
    assert "0.0.0.0" in run_sh
    # Ingress terminates TLS and proxies, so forwarded headers must be honoured.
    assert "--proxy-headers" in run_sh


# --- the release version ----------------------------------------------------
#: Semantic version, the form the Supervisor compares.
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def test_one_version_number_everywhere() -> None:
    """`config.yaml` is what the Supervisor compares — nothing may drift from it.

    The Supervisor decides whether an update exists by reading the manifest
    version alone. A code change that leaves it untouched simply never reaches a
    running Home Assistant, and a half-applied bump is the same failure wearing
    a disguise, so all three copies are asserted equal here.
    """
    manifest = yaml.safe_load((APP_ROOT / "config.yaml").read_text("utf-8"))
    manifest_version = str(manifest["version"])
    assert _SEMVER.match(manifest_version), f"not a comparable version: {manifest_version}"

    # The backend reports it on /health and /api/bobi/connection.
    from app.version import APP_VERSION

    assert manifest_version == APP_VERSION, (
        "app/version.py disagrees with config.yaml; the UI would report a "
        "version the Supervisor never installed"
    )

    package = json.loads((REPO_ROOT / "package.json").read_text("utf-8"))
    assert package["version"] == manifest_version


# --- 3.0: the families the bridge describes ---------------------------------
def test_the_allowed_service_list_is_built_from_the_declarations() -> None:
    """No service reaches Home Assistant unless a spec named it.

    The point is that the list cannot drift: adding a family means adding a
    spec, and a service typed into a call site without one is refused before a
    request is built.
    """
    from app.adapters.real import ALLOWED_SERVICES
    from app.services.resources import SPECS

    for spec in SPECS.values():
        if spec.snapshot_service:
            assert spec.snapshot_service in ALLOWED_SERVICES
        if spec.commit_service:
            assert spec.commit_service in ALLOWED_SERVICES

    # And nothing outside the `bobi_cc_` family is in there at all.
    assert all(service.startswith("bobi_cc_") for service in ALLOWED_SERVICES)


def test_no_managed_service_is_a_raw_domain_service() -> None:
    from app.adapters.real import ALLOWED_SERVICES

    for service in ALLOWED_SERVICES:
        assert "." not in service, f"{service} looks like a domain service"


def test_every_family_has_a_commit_service_and_a_title_per_operation() -> None:
    """A verb with no Hebrew title would reach a dialog as a bare token."""
    from app.services.resources import SPECS

    for spec in SPECS.values():
        assert spec.commit_service, spec.id
        for operation in spec.operations:
            assert operation in spec.titles, f"{spec.id}.{operation} has no title"


def test_the_router_and_the_specs_agree_on_the_family_list() -> None:
    """A family the router accepts but nothing implements would 500 on use."""
    from app.models.manage import MANAGED_RESOURCES
    from app.services.resources import RESOURCE_IDS

    assert set(MANAGED_RESOURCES) == set(RESOURCE_IDS)


def test_the_forbidden_system_actions_cover_the_named_categories() -> None:
    """The spec names these explicitly. A rename must not quietly drop one."""
    from app.services.resources import is_forbidden_system_action

    for action in (
        "ha_restart",
        "supervisor_update",
        "integration_delete",
        "device_delete",
        "backup_restore",
        "run_shell_command",
    ):
        assert is_forbidden_system_action(action), action
    # And something ordinary is not caught by an over-broad rule.
    assert not is_forbidden_system_action("self_check")
    assert not is_forbidden_system_action("benchmark")


def test_the_resource_normalizer_drops_anything_entity_shaped() -> None:
    from app.services.resource_normalize import safe_detail

    safe = safe_detail(
        {
            "entity_id": "light.kitchen",
            "backing": "switch.boiler",
            "members": ["climate.salon", "kitchen"],
            "nested": {"entity_id": "camera.lia", "area": "סלון"},
            "area": "מטבח",
        }
    )

    assert "entity_id" not in safe
    assert "backing" not in safe
    assert safe["members"] == ["kitchen"]
    assert safe["nested"] == {"area": "סלון"}
    assert safe["area"] == "מטבח"


def test_a_masked_value_survives_but_is_masked_again() -> None:
    """The suffix is a claim; re-masking costs nothing and trusting could cost a number."""
    from app.services.resource_normalize import safe_detail

    safe = safe_detail({"phone_masked": "0000000042"})

    assert "phone_masked" in safe
    assert safe["phone_masked"].endswith("42")
    assert "0000000042" not in safe["phone_masked"]


def test_an_item_is_not_controllable_unless_the_bridge_said_so() -> None:
    """Fail closed, on the two ways a bridge can stay silent."""
    from app.services.resource_normalize import normalize_resource

    snapshot = normalize_resource(
        "settings",
        {
            "available": True,
            "items": [
                {"id": "a", "label": "בלי דגל", "value": True, "operations": ["set"]},
                {"id": "b", "label": "בלי פעולות", "value": True, "controllable": True},
                {"id": "c", "label": "שניהם", "value": True, "controllable": True,
                 "operations": ["set"]},
            ],
        },
    )

    operable = {item.id: item.controllable for item in snapshot.items}
    assert operable == {"a": False, "b": False, "c": True}


def test_the_audit_trail_redacts_before_it_writes() -> None:
    """On the way in, not on the way out — there is no unredacted path."""
    source = strip_docstrings((BACKEND_APP / "services" / "audit.py").read_text("utf-8"))

    assert "redact(entry.model_dump())" in source
    # And nothing writes a raw entry anywhere in the module.
    assert "json.dumps(entry" not in source
