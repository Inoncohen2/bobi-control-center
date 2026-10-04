"""Provider-neutral understanding orchestration for Bobi Next.

AI/LLM providers may propose semantic intent, but they never resolve HA targets or
execute side effects.  This module optionally lets a secondary provider (for
example Instinct) rescue an unresolved/low-confidence primary interpretation.
Every rescued result still re-enters the deterministic Bobi engine: routing,
resolver, capability validation, policy, approval and executor.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Protocol

from .intent import SemanticIntent


class IntentProvider(Protocol):
    async def understand(self, text: str, *, context: Any) -> SemanticIntent: ...


class UnderstandingError(RuntimeError):
    """Base class for expected understanding failures."""


class UnderstandingUnresolved(UnderstandingError):
    """The provider could not produce a safe semantic interpretation."""


class UnderstandingTemporaryFailure(UnderstandingError):
    """A provider is temporarily unavailable and another provider may be tried."""


@dataclass(slots=True, frozen=True)
class RescuePolicy:
    minimum_confidence: float = 0.72
    fallback_on_unresolved: bool = True
    fallback_on_temporary_failure: bool = True
    rescue_device_control_missing_contract: bool = True


@dataclass(slots=True, frozen=True)
class UnderstandingTrace:
    provider: str
    rescued: bool
    rescue_reason: str = ""
    primary_confidence: float | None = None


def _needs_rescue(intent: SemanticIntent, policy: RescuePolicy) -> str:
    confidence = float(intent.confidence or 0.0)
    if confidence < policy.minimum_confidence:
        return "low_confidence"
    if (
        policy.rescue_device_control_missing_contract
        and intent.family == "device_control"
        and (not intent.canonical_domain or not intent.canonical_operation)
    ):
        return "missing_device_contract"
    return ""


def _safety_metadata(intent: SemanticIntent | None) -> dict[str, Any]:
    if intent is None:
        return {}
    metadata = intent.metadata if isinstance(intent.metadata, dict) else {}
    protected: dict[str, Any] = {}
    for key in ("question", "literal_name", "quoted_only", "non_execution"):
        if metadata.get(key):
            protected[key] = True
    return protected


def _annotate(
    intent: SemanticIntent,
    *,
    provider_name: str,
    rescued: bool,
    rescue_reason: str = "",
    primary: SemanticIntent | None = None,
    original_text: str,
) -> SemanticIntent:
    metadata = dict(intent.metadata or {})
    metadata.update(_safety_metadata(primary))
    metadata["understanding_provider"] = provider_name
    metadata["rescue_used"] = rescued
    if rescue_reason:
        metadata["rescue_reason"] = rescue_reason
    if primary is not None:
        metadata["primary_confidence"] = float(primary.confidence or 0.0)
        metadata["primary_family"] = primary.family
        metadata["primary_domain"] = primary.canonical_domain
        metadata["primary_operation"] = primary.canonical_operation

    # Rescue is allowed to improve semantics but never to erase conservative
    # safety evidence found by the primary interpreter.
    return replace(
        intent,
        raw_text=original_text,
        negated=bool(intent.negated or (primary.negated if primary else False)),
        metadata=metadata,
    )


class ResilientUnderstandingProvider:
    """Primary understanding with a constrained, semantic-only rescue provider."""

    def __init__(
        self,
        primary: IntentProvider,
        *,
        fallback: IntentProvider | None = None,
        primary_name: str = "primary",
        fallback_name: str = "instinct",
        policy: RescuePolicy | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.primary_name = primary_name
        self.fallback_name = fallback_name
        self.policy = policy or RescuePolicy()

    async def _fallback(
        self,
        text: str,
        *,
        context: Any,
        reason: str,
        primary: SemanticIntent | None,
    ) -> SemanticIntent:
        if self.fallback is None:
            raise UnderstandingUnresolved(reason)
        fallback_intent = await self.fallback.understand(text, context=context)
        fallback_reason = _needs_rescue(fallback_intent, self.policy)
        if fallback_reason:
            raise UnderstandingUnresolved(f"fallback_{fallback_reason}")
        return _annotate(
            fallback_intent,
            provider_name=self.fallback_name,
            rescued=True,
            rescue_reason=reason,
            primary=primary,
            original_text=text,
        )

    async def understand(self, text: str, *, context: Any) -> SemanticIntent:
        primary: SemanticIntent | None = None
        try:
            primary = await self.primary.understand(text, context=context)
        except UnderstandingUnresolved as exc:
            if not self.policy.fallback_on_unresolved:
                raise
            return await self._fallback(
                text,
                context=context,
                reason=str(exc) or "primary_unresolved",
                primary=None,
            )
        except UnderstandingTemporaryFailure as exc:
            if not self.policy.fallback_on_temporary_failure:
                raise
            return await self._fallback(
                text,
                context=context,
                reason=str(exc) or "primary_temporary_failure",
                primary=None,
            )

        rescue_reason = _needs_rescue(primary, self.policy)
        if rescue_reason:
            return await self._fallback(
                text,
                context=context,
                reason=rescue_reason,
                primary=primary,
            )

        return _annotate(
            primary,
            provider_name=self.primary_name,
            rescued=False,
            primary=None,
            original_text=text,
        )
