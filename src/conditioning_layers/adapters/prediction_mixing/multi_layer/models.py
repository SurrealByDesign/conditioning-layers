"""Immutable ADR-0024 execution-local profile and Translation Plan v3 values."""

from __future__ import annotations

from dataclasses import dataclass, replace

from conditioning_layers.adapters.prediction_mixing.models import (
    BasePromptPolicy, EFFECTIVE_WEIGHT_EXPRESSION, FieldAssetProfile,
    NegativePromptPolicy, OverlapPolicy, PROMPT_COMBINATION_DELIMITER,
)
from conditioning_layers.adapters.prediction_mixing.v2.identity import fingerprint_without_field
from conditioning_layers.adapters.prediction_mixing.v2.models import (
    AbstractFoldStep, DocumentExecutionProjection, OrderedLeftFoldTopologyPolicy,
    TranslationStatus,
)
from conditioning_layers.assets.models import FieldOrientation, FieldPolarity, FieldRelationshipCertificate
from conditioning_layers.capabilities.multi_layer import MultiLayerEligibilityEntry
from conditioning_layers.domain import PREDICTION_MIXING_ADAPTER_ID, ValidationFinding


TRANSLATION_PLAN_V3_IDENTIFIER = "prediction-mixing.translation-plan.v3"
TRANSLATION_PLAN_V3_VERSION = 3


@dataclass(frozen=True, slots=True)
class MultiLayerExecutionProfile:
    profile_identifier: str
    profile_version: int
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
    expected_field_encodings: tuple[str, ...]
    field_bit_depth: int
    field_interlaced: bool
    field_normalization: str
    field_values_finite: bool
    field_minimum: float
    field_maximum: float
    field_nonconstant_required: bool
    polarity: FieldPolarity
    orientation: FieldOrientation
    overlap_policy: OverlapPolicy
    base_prompt_policy: BasePromptPolicy
    prompt_combination_delimiter: str
    negative_prompt_policy: NegativePromptPolicy
    effective_weight_expression: str
    homogeneous_condition_kind: str
    fingerprint: str


_PROFILE = MultiLayerExecutionProfile(
    profile_identifier="krea2-turbo-bf16-1024.v2", profile_version=2,
    adapter_identifier=PREDICTION_MIXING_ADAPTER_ID, backend_identifier="krea2.comfyui",
    model_family="Krea 2", model_variant="Turbo BF16",
    output_width=1024, output_height=1024, latent_width=128, latent_height=128,
    expected_field_width=128, expected_field_height=128,
    expected_field_encodings=("grayscale_8", "rgb_identical_8"),
    field_bit_depth=8, field_interlaced=False, field_normalization="stored 8-bit sample / 255",
    field_values_finite=True, field_minimum=0.0, field_maximum=1.0,
    field_nonconstant_required=True, polarity=FieldPolarity(), orientation=FieldOrientation(),
    overlap_policy=OverlapPolicy.REQUIRE_NO_OVERLAP,
    base_prompt_policy=BasePromptPolicy.REPEAT_IN_REGIONAL_PROMPTS,
    prompt_combination_delimiter=PROMPT_COMBINATION_DELIMITER,
    negative_prompt_policy=NegativePromptPolicy.EMPTY,
    effective_weight_expression=EFFECTIVE_WEIGHT_EXPRESSION,
    homogeneous_condition_kind="homogeneous-prompt-layer-prediction-mixing", fingerprint="",
)
MULTI_LAYER_EXECUTION_PROFILE = replace(_PROFILE, fingerprint=fingerprint_without_field(_PROFILE))


@dataclass(frozen=True, slots=True)
class RegionalConditionPlanV3:
    active_ordinal: int
    document_index: int
    layer_id: str
    regional_prompt_text: str
    combined_prompt_text: str
    requested_strength: float
    field_profile: FieldAssetProfile
    polarity: FieldPolarity
    orientation: FieldOrientation
    effective_weight_expression: str


@dataclass(frozen=True, slots=True)
class TranslationPlanV3:
    format_identifier: str
    format_version: int
    contract_identifier: str
    contract_version: int
    document_projection: DocumentExecutionProjection
    eligibility_entry: MultiLayerEligibilityEntry
    execution_profile: MultiLayerExecutionProfile
    certificate: FieldRelationshipCertificate
    regional_conditions: tuple[RegionalConditionPlanV3, ...]
    topology_policy: OrderedLeftFoldTopologyPolicy
    fold_schedule: tuple[AbstractFoldStep, ...]
    fingerprint: str

    @property
    def active_layer_count(self) -> int:
        return len(self.regional_conditions)

    @property
    def execution_profile_identifier(self) -> str:
        return self.execution_profile.profile_identifier

    @property
    def exact_admitted_cardinality(self) -> int:
        return self.eligibility_entry.exact_cardinality


@dataclass(frozen=True, slots=True)
class TranslationResultV3:
    status: TranslationStatus
    plan: TranslationPlanV3 | None
    findings: tuple[ValidationFinding, ...]

    @property
    def translated(self) -> bool:
        return self.status is TranslationStatus.TRANSLATED

    @property
    def errors(self) -> tuple[ValidationFinding, ...]:
        from conditioning_layers.domain import FindingSeverity
        return tuple(item for item in self.findings if item.severity is FindingSeverity.ERROR)

    @property
    def warnings(self) -> tuple[ValidationFinding, ...]:
        from conditioning_layers.domain import FindingSeverity
        return tuple(item for item in self.findings if item.severity is FindingSeverity.WARNING)

    @property
    def information(self) -> tuple[ValidationFinding, ...]:
        from conditioning_layers.domain import FindingSeverity
        return tuple(item for item in self.findings if item.severity is FindingSeverity.INFORMATION)
