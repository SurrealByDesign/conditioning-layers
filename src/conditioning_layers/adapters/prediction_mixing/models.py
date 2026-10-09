"""Immutable inputs and outputs for Prediction Mixing translation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from conditioning_layers.capabilities import (
    PREDICTION_MIXING_CAPABILITY,
    CapabilityEvaluation,
    PredictionMixingCapability,
)
from conditioning_layers.domain import ValidationFinding


TRANSLATION_PLAN_VERSION = "prediction-mixing.translation-plan.v1"
PROVENANCE_PROFILE_IDENTIFIER = "prediction-mixing.provenance.v1"
EFFECTIVE_WEIGHT_EXPRESSION = (
    "effective field weight = normalized field value × requested Strength"
)
PROMPT_COMBINATION_DELIMITER = "\n\n"
ORDER_SEMANTICS = (
    "Document order is retained for deterministic translation and provenance; "
    "it has no execution-priority meaning for Prediction Mixing."
)


class FieldChannelProfile(str, Enum):
    """Supported declared PNG channel profiles; pixels are not inspected here."""

    GRAYSCALE_8 = "grayscale_8"
    RGB_IDENTICAL_8 = "rgb_identical_8"


class FieldValueKind(str, Enum):
    """Whether supplied metadata describes binary or continuous field values."""

    BINARY = "binary"
    CONTINUOUS = "continuous"


class OverlapAssessment(str, Enum):
    """Externally computed pairwise overlap state for two active fields."""

    NO_OVERLAP = "no_overlap"
    OVERLAP_PRESENT = "overlap_present"
    UNKNOWN = "unknown"


class OverlapPolicy(str, Enum):
    """The one overlap policy authorized for the prototype adapter."""

    REQUIRE_NO_OVERLAP = "require_no_overlap"


class BasePromptPolicy(str, Enum):
    """How Base Prompt text enters each translated regional condition."""

    REPEAT_IN_REGIONAL_PROMPTS = "repeat_in_regional_prompts"


class NegativePromptPolicy(str, Enum):
    """Negative-prompt behavior for the frozen prototype profile."""

    EMPTY = "empty"


@dataclass(frozen=True, slots=True)
class FieldAssetProfile:
    """Externally supplied metadata for one referenced Influence Field asset."""

    layer_id: str
    relative_path: str
    checksum: str | None
    width: int
    height: int
    channel_count: int
    channel_profile: FieldChannelProfile
    minimum_normalized_value: float
    maximum_normalized_value: float
    finite_values: bool
    value_kind: FieldValueKind


@dataclass(frozen=True, slots=True)
class PredictionMixingExecutionProfile:
    """Explicit tested execution conditions without sampler or host topology."""

    adapter_identifier: str
    model_family: str
    model_variant: str
    profile_identifier: str
    output_width: int
    output_height: int
    latent_width: int
    latent_height: int
    expected_field_width: int
    expected_field_height: int
    tested_hardware_note: str
    maximum_active_layers: int
    overlap_policy: OverlapPolicy
    base_prompt_policy: BasePromptPolicy
    negative_prompt_policy: NegativePromptPolicy
    provenance_profile_identifier: str


PREDICTION_MIXING_EXECUTION_PROFILE = PredictionMixingExecutionProfile(
    adapter_identifier=PREDICTION_MIXING_CAPABILITY.adapter_identifier,
    model_family="Krea 2",
    model_variant="Turbo BF16",
    profile_identifier="krea2-turbo-bf16-1024.v1",
    output_width=1024,
    output_height=1024,
    latent_width=128,
    latent_height=128,
    expected_field_width=128,
    expected_field_height=128,
    tested_hardware_note=(
        "Phase 1 reference environment: RTX 5080 with 16,303 MiB reported."
    ),
    maximum_active_layers=(
        PREDICTION_MIXING_CAPABILITY.maximum_tested_visible_prompt_layers
    ),
    overlap_policy=OverlapPolicy.REQUIRE_NO_OVERLAP,
    base_prompt_policy=BasePromptPolicy.REPEAT_IN_REGIONAL_PROMPTS,
    negative_prompt_policy=NegativePromptPolicy.EMPTY,
    provenance_profile_identifier=PROVENANCE_PROFILE_IDENTIFIER,
)


@dataclass(frozen=True, slots=True)
class RegionalConditionPlan:
    """One active Prompt Layer translated without tensors or node identifiers."""

    layer_id: str
    layer_name: str
    regional_prompt_text: str
    combined_prompt_text: str
    field_profile: FieldAssetProfile
    requested_strength: float
    document_index: int
    effective_weight_expression: str


@dataclass(frozen=True, slots=True)
class LayerProvenanceInput:
    """Deterministic per-layer provenance material known before execution."""

    layer_id: str
    regional_prompt_sha256: str
    combined_prompt_sha256: str
    field_reference: str
    field_checksum: str | None


@dataclass(frozen=True, slots=True)
class TranslationProvenanceInputs:
    """Compact provenance inputs associated with a translated plan."""

    document_id: str
    document_version: str
    adapter_identifier: str
    translation_plan_fingerprint: str
    layers: tuple[LayerProvenanceInput, ...]
    execution_profile_identifier: str
    capability_identifier: str
    warning_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PredictionMixingTranslationPlan:
    """Prototype-internal, deterministic description of future execution needs."""

    translation_plan_version: str
    document_id: str
    adapter_identifier: str
    capability_identifier: str
    base_prompt_text: str
    active_regional_conditions: tuple[RegionalConditionPlan, ...]
    excluded_disabled_layer_ids: tuple[str, ...]
    active_layer_count: int
    field_profiles: tuple[FieldAssetProfile, ...]
    effective_weight_expression: str
    document_order_layer_ids: tuple[str, ...]
    order_semantics: str
    separate_global_condition_emitted: bool
    overlap_assessment: OverlapAssessment | None
    execution_profile: PredictionMixingExecutionProfile
    mandatory_warning_codes: tuple[str, ...]
    provenance_inputs: TranslationProvenanceInputs
    fingerprint: str


@dataclass(frozen=True, slots=True)
class PredictionMixingTranslationResult:
    """Normal structured outcome for compatible and incompatible user intent."""

    plan: PredictionMixingTranslationPlan | None
    errors: tuple[ValidationFinding, ...]
    warnings: tuple[ValidationFinding, ...]
    information: tuple[ValidationFinding, ...]
    capability_evaluation: CapabilityEvaluation
    capability: PredictionMixingCapability
    compatible: bool
    translated: bool
