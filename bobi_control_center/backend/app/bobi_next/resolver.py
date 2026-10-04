"""Generic target resolution for Bobi Next.

Resolution is deterministic and fail-closed. It uses discovered HA names,
areas, aliases and optional learned aliases; it contains no private room/device
mapping. AI may propose text, but this resolver remains the authority that
binds text to actual HA targets.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable

from .models import DeviceRecord, TargetResolution

_SPACE = re.compile(r"\s+")
_PUNCT = re.compile(r"[^0-9a-zA-Zא-ת%._ -]+")
_REFERENCE_WORDS = {
    "אותו",
    "אותה",
    "אותם",
    "אותן",
    "בו",
    "בה",
    "שם",
    "זה",
    "זאת",
    "עוד",
    "קצת",
    "יותר",
    "פחות",
}


def normalize(text: str) -> str:
    return _SPACE.sub(" ", _PUNCT.sub(" ", text.casefold())).strip()


def _contains_phrase(query: str, phrase: str) -> bool:
    phrase = normalize(phrase)
    if not phrase:
        return False
    return f" {phrase} " in f" {query} " or phrase == query


def _domain_matches(device: DeviceRecord, domain_hint: str) -> bool:
    if not domain_hint:
        return True
    aliases = {
        "lighting": {"light"},
        "light": {"light"},
        "climate": {"climate"},
        "switch": {"switch"},
        "vacuum": {"vacuum"},
        "camera": {"camera"},
        "cover": {"cover"},
        "fan": {"fan"},
        "media": {"media_player"},
    }
    wanted = aliases.get(domain_hint, {domain_hint})
    return any(entity.domain in wanted for entity in device.entities)


def resolve_target(
    text: str,
    devices: Iterable[DeviceRecord],
    *,
    domain_hint: str = "",
    capability: str = "",
    active_device_id: str = "",
    learned_aliases: Callable[[str], Iterable[tuple[str, float]]] | None = None,
    allow_group: bool = False,
) -> TargetResolution:
    query = normalize(text)
    pool = [d for d in devices if _domain_matches(d, domain_hint)]
    if capability:
        pool = [d for d in pool if capability in d.capabilities]

    # Conversational references may reuse a recent device, but only when it is
    # still present and satisfies the requested capability/domain contract.
    query_words = set(query.split())
    reference_only = bool(query_words) and query_words.issubset(_REFERENCE_WORDS)
    if active_device_id and reference_only:
        active = next((d for d in pool if d.bobi_id == active_device_id), None)
        if active:
            return TargetResolution(
                ok=True,
                devices=(active,),
                confidence=0.96,
                reason="active_context",
                resolution_kind="context",
                candidate_ids=(active.bobi_id,),
            )

    scored: list[tuple[float, DeviceRecord, str]] = []
    for device in pool:
        best = 0.0
        reason = ""
        aliases: list[tuple[str, float]] = [(device.name, 1.0)]
        aliases.extend((alias, 1.0) for alias in device.aliases)
        if learned_aliases:
            aliases.extend(learned_aliases(device.bobi_id))

        for alias, weight in aliases:
            alias_n = normalize(alias)
            if not alias_n:
                continue
            if query == alias_n:
                score = 1.0 * weight
            elif _contains_phrase(query, alias_n):
                score = 0.92 * weight
            else:
                alias_tokens = set(alias_n.split())
                overlap = len(alias_tokens & query_words) / max(1, len(alias_tokens))
                score = (0.58 + 0.22 * overlap) * weight if overlap >= 0.75 else 0.0
            if score > best:
                best, reason = score, "alias"

        area_hit = bool(device.area_name and _contains_phrase(query, device.area_name))
        if area_hit:
            if best > 0:
                best += 0.07
                reason = "alias_area"
            elif domain_hint:
                # Domain + area may safely narrow the result; a bare area is
                # intentionally not enough to guess a device.
                best = 0.82
                reason = "domain_area"

        if best > 0:
            scored.append((min(best, 1.0), device, reason))

    scored.sort(key=lambda row: (-row[0], row[1].bobi_id))
    if not scored:
        return TargetResolution(ok=False, reason="no_target_match")

    if allow_group:
        threshold = max(0.82, scored[0][0] - 0.05)
        selected = tuple(row[1] for row in scored if row[0] >= threshold)
        if len(selected) > 1:
            return TargetResolution(
                ok=True,
                devices=selected,
                confidence=min(row[0] for row in scored if row[1] in selected),
                reason="explicit_group",
                resolution_kind="group",
                candidate_ids=tuple(d.bobi_id for d in selected),
            )

    top_score, top, top_reason = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    candidate_ids = tuple(row[1].bobi_id for row in scored[:5])

    # A close tie is ambiguity, not permission to guess. This mirrors Bobi's
    # current Target Authority fail-closed rule without hard-coded rooms.
    if second_score >= 0.80 and top_score - second_score < 0.08:
        return TargetResolution(
            ok=False,
            confidence=top_score,
            reason="ambiguous_target",
            resolution_kind="ambiguous",
            ambiguous=True,
            candidate_ids=candidate_ids,
        )
    if top_score < 0.80:
        return TargetResolution(
            ok=False,
            confidence=top_score,
            reason="low_confidence",
            resolution_kind="low_confidence",
            candidate_ids=candidate_ids,
        )

    return TargetResolution(
        ok=True,
        devices=(top,),
        confidence=top_score,
        reason=top_reason,
        resolution_kind="exact" if top_score >= 0.92 else "semantic",
        candidate_ids=candidate_ids,
    )
