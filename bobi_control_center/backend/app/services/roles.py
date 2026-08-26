"""Who may do what, by how much the operation could cost.

Every managed operation already carries a risk rating — the bridge rates it, or
the family's spec does. This maps that rating onto the least privileged role
allowed to run it, so the answer to "may this person do this?" is one comparison
rather than a list of special cases that has to be kept in step with the
operations.

## Where a role comes from

* **Home Assistant Ingress** — the household member is already authenticated by
  Home Assistant, and the panel is admin-only (`panel_admin: true` in the
  manifest). They get `owner`.
* **The public hostname behind Cloudflare** — one shared password today, so one
  role, and it defaults to `admin` rather than `owner`. A session that crossed
  the Internet gets everything except the handful of operations rated
  `destructive`; those stay on the screen a person reaches from inside the
  house. `external_role` in the add-on options moves it if a household wants it
  moved.

There is deliberately no way to raise a role from inside a request. A role is
decided when the session is created and read from there; nothing in a payload,
a header or a query string is consulted.

## Roles

| Role | What it is for |
| --- | --- |
| `viewer` | Reading. Every screen, no controls. |
| `operator` | The day-to-day: lights, climate, tasks, a Shabbat time. |
| `admin` | Managing Bobi — users, roles, settings, sensitive changes. |
| `owner` | The few operations that destroy something or touch the system. |
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Role(str, Enum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"
    OWNER = "owner"


#: Weakest first. Position in this tuple *is* the privilege ordering.
ORDER: tuple[Role, ...] = (Role.VIEWER, Role.OPERATOR, Role.ADMIN, Role.OWNER)

#: Hebrew, for the screen that shows a household member what they may do.
LABELS: dict[Role, str] = {
    Role.VIEWER: "צפייה בלבד",
    Role.OPERATOR: "הפעלה",
    Role.ADMIN: "ניהול",
    Role.OWNER: "בעלים",
}

#: The least privileged role allowed to run an operation of each risk.
#:
#: `destructive` sits at `owner` on purpose: deleting a rule or an event is the
#: category where being wrong cannot be undone from the same screen, and the
#: default external session is not an owner.
MINIMUM_ROLE: dict[str, Role] = {
    "read_only": Role.VIEWER,
    "low": Role.OPERATOR,
    "medium": Role.OPERATOR,
    "high": Role.ADMIN,
    "destructive": Role.OWNER,
}


def rank(role: Role | str | None) -> int:
    """Where a role sits, unknown counting as the weakest.

    An unrecognised role is treated as `viewer` rather than rejected outright:
    the failure mode of a typo in a stored session should be "can only read",
    never "can do anything".
    """
    try:
        return ORDER.index(Role(role))
    except (ValueError, TypeError):
        return 0


def minimum_role(risk: str | None) -> Role:
    """The role an operation of this risk needs.

    An unrated operation is treated as `high`, matching how `resources.rank`
    handles an unknown risk word: a rating this application does not recognise
    should not thereby become easier to run.
    """
    return MINIMUM_ROLE.get(risk or "", Role.ADMIN)


def allows(role: Role | str | None, risk: str | None) -> bool:
    return rank(role) >= rank(minimum_role(risk))


@dataclass(frozen=True)
class Actor:
    """Who is asking, and how they got here.

    `label` is what the audit trail records. It is a role and a route — "בעלים
    (Ingress)" — never a name, an address or anything else that identifies a
    person: the trail says what authority a change was made under, which is the
    question it exists to answer.
    """

    role: Role
    #: `ingress` or `external`.
    source: str

    @property
    def label(self) -> str:
        route = "Ingress" if self.source == "ingress" else "חיצוני"
        return f"{LABELS[self.role]} ({route})"

    def may(self, risk: str | None) -> bool:
        return allows(self.role, risk)


#: What a request that never reached the auth layer gets. Only reachable from a
#: test or a misconfiguration, and it can read and nothing else.
ANONYMOUS = Actor(role=Role.VIEWER, source="external")
