"""Closed, backend-neutral Composition Policy semantic authority.

Registration identifies authored meaning, never product admission or backend
realizability. No Overlap and Blend are distinct coexisting policies. Blend's
future semantic rule is u_i = F_i * S_i, then w_i = u_i / sum_j u_j when the
denominator is positive. A lone positive contributor has weight 1 for every
positive Strength; zero Strength contributes zero. A zero denominator means
no Prompt Layer contribution. Base Prompt is outside that denominator and is
neither Layer 0 nor an implicit gap filler. These are semantics, not execution.
"""

from __future__ import annotations

from dataclasses import dataclass


COMPOSITION_POLICY_FAMILY_ID = "conditioning-layers.composition-policy.v1"


class CompositionPolicyError(ValueError):
    """A policy reference cannot identify supported authored semantics."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CompositionPolicyReference:
    """The complete parameter-free persisted policy reference."""

    policy_identifier: str
    policy_version: int


@dataclass(frozen=True, slots=True)
class CompositionPolicyRecord:
    """Reviewed semantic authority; no settings or execution capability."""

    identifier: str
    version: int
    semantic_kind: str
    display_name: str
    description: str
    order_independent: bool

    @property
    def reference(self) -> CompositionPolicyReference:
        return CompositionPolicyReference(self.identifier, self.version)


REQUIRE_NO_OVERLAP = CompositionPolicyRecord(
    identifier="conditioning-layers.composition-policy.require-no-overlap.v1",
    version=1,
    semantic_kind="require-no-overlap",
    display_name="No Overlap",
    description=(
        "Active Prompt Layers must have no simultaneous positive stored Influence "
        "Field samples, regardless of Strength. Gaps are permitted."
    ),
    order_independent=True,
)
NORMALIZED_BLEND = CompositionPolicyRecord(
    identifier="conditioning-layers.composition-policy.normalized-blend.v1",
    version=1,
    semantic_kind="normalized-blend",
    display_name="Blend",
    description=(
        "Normalize Influence Field times Strength across Active Prompt Layers. "
        "A lone positive contributor has local weight 1; zero total contribution "
        "means no Prompt Layer contribution."
    ),
    order_independent=True,
)
REGISTERED_COMPOSITION_POLICIES = (REQUIRE_NO_OVERLAP, NORMALIZED_BLEND)


def resolve_composition_policy(reference: object) -> CompositionPolicyRecord:
    """Resolve an exact reviewed reference without fallback or registration."""

    if type(reference) is not CompositionPolicyReference:
        raise CompositionPolicyError(
            "composition_policy.invalid_representation",
            "Composition Policy must contain only its policy identifier and version.",
        )
    if type(reference.policy_identifier) is not str:
        raise CompositionPolicyError(
            "composition_policy.identifier.invalid_type",
            "Composition Policy identifier must be text.",
        )
    if type(reference.policy_version) is not int:
        raise CompositionPolicyError(
            "composition_policy.version.invalid_type",
            "Composition Policy version must be an integer, not a boolean.",
        )
    for policy in REGISTERED_COMPOSITION_POLICIES:
        if reference.policy_identifier == policy.identifier:
            if reference.policy_version != policy.version:
                raise CompositionPolicyError(
                    "composition_policy.version.unsupported",
                    "Composition Policy version is not registered for this identifier.",
                )
            return policy
    raise CompositionPolicyError(
        "composition_policy.identifier.unknown",
        "Composition Policy identifier is not registered.",
    )
