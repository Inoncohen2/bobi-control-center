"""Who may do what.

The permission model has one job and one failure mode worth designing against:
it must never be possible to *gain* authority. So the tests here are mostly
about what does not happen — a weaker role cannot preview a change it may not
make, cannot spend a token a stronger one created, and cannot become stronger by
anything it puts in a request.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.mock.management import MockManagementBridge
from app.models.manage import CommitRequest, PreviewRequest
from app.services.manage import (
    InsufficientRoleError,
    ManagementService,
)
from app.services.roles import ANONYMOUS, LABELS, ORDER, Actor, Role, allows, minimum_role, rank

VIEWER = Actor(role=Role.VIEWER, source="external")
OPERATOR = Actor(role=Role.OPERATOR, source="external")
ADMIN = Actor(role=Role.ADMIN, source="external")
OWNER = Actor(role=Role.OWNER, source="ingress")


def service(**kwargs) -> ManagementService:
    kwargs.setdefault("writes_enabled", True)
    return ManagementService(MockManagementBridge(**kwargs))


# --- the ordering -----------------------------------------------------------
def test_the_roles_are_ordered_weakest_first() -> None:
    assert [role.value for role in ORDER] == ["viewer", "operator", "admin", "owner"]
    assert rank(Role.VIEWER) < rank(Role.OPERATOR) < rank(Role.ADMIN) < rank(Role.OWNER)


def test_an_unknown_role_is_the_weakest_one() -> None:
    """A typo in a stored session costs reading. It must never grant writing."""
    assert rank("superuser") == rank(Role.VIEWER)
    assert rank(None) == rank(Role.VIEWER)
    assert allows("superuser", "low") is False


def test_an_unrated_operation_needs_an_admin() -> None:
    """A risk word this application does not know is treated as a serious one."""
    assert minimum_role("something_new") is Role.ADMIN
    assert minimum_role(None) is Role.ADMIN
    assert allows(Role.OPERATOR, "something_new") is False


@pytest.mark.parametrize(
    ("risk", "role"),
    [
        ("read_only", Role.VIEWER),
        ("low", Role.OPERATOR),
        ("medium", Role.OPERATOR),
        ("high", Role.ADMIN),
        ("destructive", Role.OWNER),
    ],
)
def test_each_risk_names_the_role_it_needs(risk, role) -> None:
    assert minimum_role(risk) is role
    assert allows(role, risk) is True
    # And every weaker role is refused.
    for weaker in ORDER[: rank(role)]:
        assert allows(weaker, risk) is False


def test_a_request_that_reached_no_session_can_only_read() -> None:
    assert ANONYMOUS.role is Role.VIEWER
    assert ANONYMOUS.may("read_only") is True
    assert ANONYMOUS.may("low") is False


# --- the refusal ------------------------------------------------------------
async def test_a_viewer_cannot_preview_a_change() -> None:
    holder = MockManagementBridge(writes_enabled=True)
    svc = ManagementService(holder)

    with pytest.raises(InsufficientRoleError) as caught:
        await svc.preview(
            "settings",
            PreviewRequest(operation="set", resource_id="morning_enabled", payload={"value": False}),
            VIEWER,
        )

    assert caught.value.status_code == 403
    assert caught.value.details["required_role"] == "operator"
    assert holder.applied == [], "and nothing reached the bridge"


async def test_the_refusal_names_the_role_needed() -> None:
    """"You need X" is actionable. "You are only Y" is not."""
    with pytest.raises(InsufficientRoleError) as caught:
        await service().preview(
            "users",
            PreviewRequest(operation="set_phone", resource_id="user_2", payload={"phone": "0"}),
            OPERATOR,
        )

    assert LABELS[Role.ADMIN] in caught.value.message


async def test_an_operator_may_run_an_ordinary_change() -> None:
    response = await service().preview(
        "settings",
        PreviewRequest(operation="set", resource_id="morning_enabled", payload={"value": False}),
        OPERATOR,
    )

    assert response.valid is True
    assert response.risk == "low"


async def test_an_admin_may_not_destroy_something() -> None:
    """`destructive` sits at owner: it is the category that cannot be undone."""
    with pytest.raises(InsufficientRoleError) as caught:
        await service().preview(
            "rules", PreviewRequest(operation="delete", resource_id="rule_1"), ADMIN
        )

    assert caught.value.details["required_role"] == "owner"


async def test_an_owner_may_destroy_something() -> None:
    response = await service().preview(
        "rules", PreviewRequest(operation="delete", resource_id="rule_1"), OWNER
    )

    assert response.valid is True
    assert response.risk == "destructive"


# --- a token cannot be handed down ------------------------------------------
async def test_a_weaker_session_cannot_spend_a_stronger_ones_token() -> None:
    """The two requests are independent; nothing says they came from one place."""
    holder = MockManagementBridge(writes_enabled=True)
    svc = ManagementService(holder)
    preview = await svc.preview(
        "rules", PreviewRequest(operation="delete", resource_id="rule_1"), OWNER
    )

    with pytest.raises(InsufficientRoleError):
        await svc.commit(
            "rules",
            CommitRequest(
                preview_id=preview.preview_id, confirmed=True, confirm_word=preview.confirm_word
            ),
            ADMIN,
        )

    assert holder.applied == []
    # And the preview is still there for the owner who took it — a refusal for
    # someone else must not consume it.
    result = await svc.commit(
        "rules",
        CommitRequest(
            preview_id=preview.preview_id, confirmed=True, confirm_word=preview.confirm_word
        ),
        OWNER,
    )
    assert result.result.status in ("committed", "committed_unverified")


async def test_a_refused_preview_never_becomes_a_token() -> None:
    svc = service()
    with pytest.raises(InsufficientRoleError):
        await svc.preview(
            "rules", PreviewRequest(operation="delete", resource_id="rule_1"), ADMIN
        )

    assert svc._previews == {}


# --- the audit records the authority ----------------------------------------
async def test_the_trail_records_the_role_and_the_route() -> None:
    svc = service()
    await svc.preview(
        "settings",
        PreviewRequest(operation="set", resource_id="morning_enabled", payload={"value": False}),
        OPERATOR,
    )

    entry = svc.audit(limit=1).records[0]
    assert entry.source == "external"
    assert entry.actor == "הפעלה (חיצוני)"


async def test_a_refusal_is_recorded_too() -> None:
    """The interesting line in a trail is often the one that was refused."""
    svc = service()
    with pytest.raises(InsufficientRoleError):
        await svc.preview(
            "rules", PreviewRequest(operation="delete", resource_id="rule_1"), VIEWER
        )

    entry = svc.audit(limit=1).records[0]
    assert entry.result == "refused"
    assert entry.actor == "צפייה בלבד (חיצוני)"


def test_an_actor_label_names_no_person() -> None:
    """A role and a route. Never a name, an address or a session id."""
    for actor in (VIEWER, OPERATOR, ADMIN, OWNER):
        assert actor.label in {
            f"{LABELS[actor.role]} (Ingress)",
            f"{LABELS[actor.role]} (חיצוני)",
        }


# --- nothing in a request can raise a role ----------------------------------
def test_no_route_reads_a_role_from_the_client(tmp_path) -> None:
    """Ingress is owner because Home Assistant said so, not because a header did."""
    settings = Settings(adapter="mock", data_dir=tmp_path / "data")
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/bobi/manage/settings/preview",
            json={"operation": "set", "resource_id": "x", "payload": {}},
            headers={"X-Role": "owner", "X-Bobi-Role": "owner"},
        )
        # No bridge in the mock adapter, so this is the fail-closed answer —
        # what matters is that the headers changed nothing about who we are.
        assert response.status_code == 503

    body = PreviewRequest.model_json_schema()
    assert "role" not in body["properties"], "a payload must not be able to carry a role"
