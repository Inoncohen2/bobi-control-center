from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.bobi_next.intent import SemanticIntent
from app.bobi_next.understanding import (
    RescuePolicy,
    ResilientUnderstandingProvider,
    UnderstandingTemporaryFailure,
    UnderstandingUnresolved,
)


@dataclass
class StaticProvider:
    result: SemanticIntent | Exception

    def __post_init__(self):
        self.calls = 0
        self.contexts = []

    async def understand(self, text: str, *, context):
        self.calls += 1
        self.contexts.append(context)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def intent(
    *,
    raw_text: str = "original",
    family: str = "device_control",
    domain: str = "switch",
    operation: str = "off",
    confidence: float = 0.95,
    negated: bool = False,
    metadata: dict | None = None,
):
    return SemanticIntent(
        raw_text=raw_text,
        family=family,
        domain=domain,
        operation=operation,
        target_text="room",
        confidence=confidence,
        negated=negated,
        metadata=metadata or {},
    )


@pytest.mark.asyncio
async def test_high_confidence_primary_does_not_call_fallback():
    primary = StaticProvider(intent(confidence=0.96))
    fallback = StaticProvider(intent(domain="light", confidence=0.99))
    provider = ResilientUnderstandingProvider(primary, fallback=fallback)

    result = await provider.understand("turn it off", context={"x": 1})

    assert result.canonical_domain == "switch"
    assert result.raw_text == "turn it off"
    assert result.metadata["understanding_provider"] == "primary"
    assert result.metadata["rescue_used"] is False
    assert primary.calls == 1
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_low_confidence_primary_uses_fallback():
    primary = StaticProvider(intent(domain="switch", confidence=0.31))
    fallback = StaticProvider(intent(domain="light", confidence=0.98))
    provider = ResilientUnderstandingProvider(primary, fallback=fallback)

    result = await provider.understand("lights off", context={})

    assert result.canonical_domain == "light"
    assert result.raw_text == "lights off"
    assert result.metadata["understanding_provider"] == "instinct"
    assert result.metadata["rescue_used"] is True
    assert result.metadata["rescue_reason"] == "low_confidence"
    assert result.metadata["primary_confidence"] == pytest.approx(0.31)
    assert fallback.calls == 1


@pytest.mark.asyncio
async def test_unresolved_primary_can_be_rescued():
    primary = StaticProvider(UnderstandingUnresolved("no_parse"))
    fallback = StaticProvider(intent(confidence=0.91))
    provider = ResilientUnderstandingProvider(primary, fallback=fallback)

    result = await provider.understand("off", context={})

    assert result.metadata["rescue_used"] is True
    assert result.metadata["rescue_reason"] == "no_parse"
    assert fallback.calls == 1


@pytest.mark.asyncio
async def test_temporary_primary_failure_can_be_rescued():
    primary = StaticProvider(UnderstandingTemporaryFailure("provider_timeout"))
    fallback = StaticProvider(intent(confidence=0.91))
    provider = ResilientUnderstandingProvider(primary, fallback=fallback)

    result = await provider.understand("off", context={})

    assert result.metadata["rescue_reason"] == "provider_timeout"
    assert fallback.calls == 1


@pytest.mark.asyncio
async def test_programming_error_is_not_hidden_by_fallback():
    primary = StaticProvider(RuntimeError("bug"))
    fallback = StaticProvider(intent(confidence=0.99))
    provider = ResilientUnderstandingProvider(primary, fallback=fallback)

    with pytest.raises(RuntimeError, match="bug"):
        await provider.understand("off", context={})
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_fallback_must_also_meet_confidence_floor():
    primary = StaticProvider(intent(confidence=0.20))
    fallback = StaticProvider(intent(confidence=0.40))
    provider = ResilientUnderstandingProvider(primary, fallback=fallback)

    with pytest.raises(UnderstandingUnresolved, match="fallback_low_confidence"):
        await provider.understand("off", context={})


@pytest.mark.asyncio
async def test_rescue_cannot_erase_negation_or_question_evidence():
    primary = StaticProvider(
        intent(
            confidence=0.20,
            negated=True,
            metadata={"question": True, "literal_name": True},
        )
    )
    fallback = StaticProvider(
        intent(
            domain="light",
            operation="on",
            confidence=0.99,
            negated=False,
            metadata={},
        )
    )
    provider = ResilientUnderstandingProvider(primary, fallback=fallback)

    result = await provider.understand("don't turn it on?", context={})

    assert result.negated is True
    assert result.metadata["question"] is True
    assert result.metadata["literal_name"] is True
    assert result.canonical_domain == "light"


@pytest.mark.asyncio
async def test_missing_device_contract_is_rescued():
    primary = StaticProvider(
        intent(domain="", operation="", confidence=0.94)
    )
    fallback = StaticProvider(intent(domain="cover", operation="open", confidence=0.97))
    provider = ResilientUnderstandingProvider(primary, fallback=fallback)

    result = await provider.understand("open shutter", context={})

    assert result.canonical_domain == "cover"
    assert result.canonical_operation == "open"
    assert result.metadata["rescue_reason"] == "missing_device_contract"


@pytest.mark.asyncio
async def test_policy_can_disable_temporary_failure_fallback():
    primary = StaticProvider(UnderstandingTemporaryFailure("down"))
    fallback = StaticProvider(intent(confidence=0.99))
    provider = ResilientUnderstandingProvider(
        primary,
        fallback=fallback,
        policy=RescuePolicy(fallback_on_temporary_failure=False),
    )

    with pytest.raises(UnderstandingTemporaryFailure, match="down"):
        await provider.understand("off", context={})
    assert fallback.calls == 0
