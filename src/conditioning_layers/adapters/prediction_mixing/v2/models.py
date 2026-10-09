"""Immutable Translation Plan v2 projection, policy, plan, and result models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from typing import TYPE_CHECKING

from conditioning_layers.domain.validation import ValidationFinding

if TYPE_CHECKING:
    from conditioning_layers.assets.models import FieldOrientation, FieldPolarity


DOCUMENT_EXECUTION_PROJECTION_IDENTIFIER = (
    "conditioning-layers.document-execution-projection.v1"
)
DOCUMENT_EXECUTION_PROJECTION_VERSION = 1
CAPABILITY_EXECUTION_PROJECTION_IDENTIFIER = (
    "prediction-mixing.capability-execution-projection.v1"
)
CAPABILITY_EXECUTION_PROJECTION_VERSION = 1
CAPABILITY_POLICY_IDENTIFIER = "prediction-mixing.capability-policy.v1"
CAPABILITY_POLICY_VERSION = 1
EXECUTION_PROFILE_PROJECTION_IDENTIFIER = (
    "prediction-mixing.execution-profile-projection.v1"
)
EXECUTION_PROFILE_PROJECTION_VERSION = 1
TOPOLOGY_POLICY_IDENTIFIER = "prediction-mixing.ordered-left-fold.v1"
TOPOLOGY_POLICY_VERSION = 1
TRANSLATION_PLAN_V2_IDENTIFIER = "prediction-mixing.translation-plan.v2"
TRANSLATION_PLAN_V2_VERSION = 2


class TranslationStatus(str, Enum):
    """The complete all-or-nothing outcome of one v2 translation attempt."""

    TRANSLATED = "translated"
    REJECTED = "rejected"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class DocumentExecutionLayer:
    """One Active Prompt Layer in retained relative execution order."""

    active_ordinal: int
    layer_id: str
    prompt_text: str
    requested_strength: float
    influence_field_reference: str
    declared_field_sha256: str | None


@dataclass(frozen=True, slots=True)
class DocumentExecutionProjection:
    """Exact execution-relevant subset of one canonical document."""

    format_identifier: str
    format_version: int
    source_document_major_version: int
    source_document_minor_version: int
    selected_adapter_identifier: str | None
    canonical_adapter_settings_json: str
    base_prompt_text: str
    active_layers: tuple[DocumentExecutionLayer, ...]
    fingerprint: str


@dataclass(frozen=True, slots=True)
class CapabilityDecision:
    """Stable capability code and normalized target without diagnostic prose."""

    code: str
    active_ordinal: int | None
    layer_id: str | None
    field_path: str | None


@dataclass(frozen=True, slots=True)
class CapabilityExecutionProjection:
    """Execution-semantic result of the authoritative capability evaluator."""

    format_identifier: str
    format_version: int
    capability_policy_identifier: str
    capability_policy_version: int
    capability_policy_fingerprint: str
    subject_document_projection_fingerprint: str
    authoritative_adapter_identifier: str
    selected_adapter_identifier: str | None
    compatible: bool
    active_layer_count: int
    homogeneous_condition_kind: str
    minimum_active_layer_count: int
    maximum_active_layer_count: int
    decisions: tuple[CapabilityDecision, ...]
    accepted_constraints: tuple[CapabilityDecision, ...]
    fingerprint: str


@dataclass(frozen=True, slots=True)
class ExecutionProfileProjection:
    """Translation-owned semantics of one known Prediction Mixing profile."""

    format_identifier: str
    format_version: int
    profile_identifier: str
    adapter_identifier: str
    backend_identifier: str
    model_family: str
    model_variant: str
    output_width: int
    output_height: int
    latent_width: int
    latent_height: int
    expected_field_width: int
    expected_field_height: int
    expected_field_encoding: str
    base_prompt_policy: str
    prompt_combination_delimiter: str
    negative_prompt_policy: str
    effective_weight_expression: str
    homogeneous_condition_kind: str
    fingerprint: str


@dataclass(frozen=True, slots=True)
class OrderedLeftFoldTopologyPolicy:
    """Named abstract combination rule without graph nodes or links."""

    policy_identifier: str
    policy_version: int
    input_order_source: str
    single_condition_behavior: str
    multiple_condition_strategy: str
    balancing_permitted: bool
    sorting_permitted: bool
    commutation_permitted: bool
    tree_optimization_permitted: bool
    fingerprint: str


@dataclass(frozen=True, slots=True)
class EvidenceIdentity:
    """Verified identity of one upstream evidence artifact."""

    format_identifier: str
    format_version: int
    fingerprint: str


@dataclass(frozen=True, slots=True)
class CertificateIdentity:
    """Verified certificate and relationship-policy identity."""

    format_identifier: str
    format_version: int
    relationship_policy_identifier: str
    relationship_policy_version: int
    fingerprint: str


@dataclass(frozen=True, slots=True)
class RegionalConditionPlanV2:
    """One exact regional condition with no host-specific representation."""

    active_ordinal: int
    layer_id: str
    regional_prompt_text: str
    combined_prompt_text: str
    requested_strength: float
    library_identifier: str
    library_version: int
    family_identifier: str
    family_version: int
    permutation_identifier: str
    library_field_id: str
    library_field_reference: str
    document_field_reference: str
    source_field_sha256: str
    width: int
    height: int
    encoding: str
    polarity: FieldPolarity
    orientation: FieldOrientation
    effective_weight_expression: str


@dataclass(frozen=True, slots=True)
class AbstractFoldStep:
    """One deterministic logical step in an ordered iterative left fold."""

    step_ordinal: int
    left_operand: str
    right_condition: str
    result: str


@dataclass(frozen=True, slots=True)
class TranslationPlanV2:
    """Complete evidence-bound execution intent for future graph generation."""

    contract_identifier: str
    contract_version: int
    adapter_identifier: str
    document_projection: DocumentExecutionProjection
    capability_projection: CapabilityExecutionProjection
    binding_identity: EvidenceIdentity
    certificate_identity: CertificateIdentity
    execution_profile_projection: ExecutionProfileProjection
    topology_policy: OrderedLeftFoldTopologyPolicy
    regional_conditions: tuple[RegionalConditionPlanV2, ...]
    fold_schedule: tuple[AbstractFoldStep, ...]
    fingerprint: str


@dataclass(frozen=True, slots=True)
class TranslationResultV2:
    """All-or-nothing v2 result; only translated outcomes contain a plan."""

    status: TranslationStatus
    plan: TranslationPlanV2 | None
    findings: tuple[ValidationFinding, ...]

    @property
    def errors(self) -> tuple[ValidationFinding, ...]:
        return tuple(item for item in self.findings if item.severity.value == "error")

    @property
    def warnings(self) -> tuple[ValidationFinding, ...]:
        return tuple(
            item for item in self.findings if item.severity.value == "warning"
        )

    @property
    def information(self) -> tuple[ValidationFinding, ...]:
        return tuple(
            item for item in self.findings if item.severity.value == "information"
        )
