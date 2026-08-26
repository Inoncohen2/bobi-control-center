"""The bridge specification, answered against the live contract.

`bridge_contract.py` says what every service must look like. This turns that
into the response, and adds the one thing a static document cannot know: which
of those services Home Assistant has actually published.

The split matters. The specification is a property of this build and never
changes at runtime; what is implemented is a property of the house and changes
the moment a script is added. Keeping them in separate modules stops the second
from being written into the first.
"""

from __future__ import annotations

from app.models.manage import (
    BridgeContract,
    BridgeField,
    BridgeServiceContract,
)
from app.services.bridge_contract import (
    COMMON_COMMIT_INPUTS,
    COMMON_COMMIT_OUTPUTS,
    NEVER_CALLED,
    NEVER_REQUESTED,
    all_services,
    risk_to_role,
)
from app.services.resources import SPECS
from app.version import APP_VERSION


def _fields(rows: tuple[tuple[str, str, str], ...]) -> list[BridgeField]:
    return [BridgeField(name=name, type=kind, note=note) for name, kind, note in rows]


async def build_bridge_contract(service) -> BridgeContract:
    """The specification, plus what the live contract says exists.

    A bridge is counted implemented when the contract declares its family — and,
    for a commit service, declares at least one operation on it. A family
    announced with no operations has a snapshot bridge and no commit bridge yet,
    which is exactly the state this report exists to make visible.
    """
    status = await service.status()
    declared = {resource.id: resource for resource in status.resources}

    implemented: list[str] = []
    missing: list[str] = []
    services: list[BridgeServiceContract] = []

    for entry in all_services():
        contract = BridgeServiceContract(
            name=entry.name,
            kind=entry.kind,
            purpose=entry.purpose,
            resource=entry.resource,
            operations=list(entry.operations),
            inputs=_fields(entry.inputs),
            outputs=entry.outputs,
            validation=list(entry.validation),
            verification=entry.verification,
            risk=entry.risk,
            operation_risk=dict(entry.operation_risk),
        )
        services.append(contract)

        if entry.name == "bobi_cc_manage_contract":
            # It answered, so it exists. Nothing else could have been read.
            (implemented if status.available else missing).append(entry.name)
            continue

        resource = declared.get(entry.resource or "")
        # A family the contract does not declare has neither bridge. A family it
        # declares with no operations has the snapshot and not the commit —
        # which is the state this report exists to make visible.
        undeclared = resource is None or not resource.available
        no_commit_bridge = (
            not undeclared and entry.kind == "write" and not resource.operations
        )
        if undeclared or no_commit_bridge:
            missing.append(entry.name)
        else:
            implemented.append(entry.name)

    return BridgeContract(
        app_version=APP_VERSION,
        implemented=implemented,
        missing=missing,
        services=services,
        common_commit_inputs=_fields(COMMON_COMMIT_INPUTS),
        common_commit_outputs=_fields(COMMON_COMMIT_OUTPUTS),
        never_called_domains=list(NEVER_CALLED),
        never_requested=list(NEVER_REQUESTED),
        risk_to_role=risk_to_role(),
    )


def declared_service_names() -> set[str]:
    """Every service name the specification covers. Used by the guard test."""
    return {entry.name for entry in all_services()} | {
        name
        for spec in SPECS.values()
        for name in (spec.snapshot_service, spec.commit_service)
        if name
    }
