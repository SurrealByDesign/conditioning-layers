"""First-class immutable projections frozen by ADR-0008."""

from __future__ import annotations

from dataclasses import replace

from conditioning_layers.adapters.prediction_mixing.models import (
    EFFECTIVE_WEIGHT_EXPRESSION,
    PREDICTION_MIXING_EXECUTION_PROFILE,
    PROMPT_COMBINATION_DELIMITER,
    PredictionMixingExecutionProfile,
)
from conditioning_layers.assets import HOMOGENEOUS_PROMPT_LAYER_CONDITION_KIND
from conditioning_layers.capabilities import (
    PREDICTION_MIXING_CAPABILITY,
    CapabilityEvaluation,
    evaluate_prediction_mixing,
)
from conditioning_layers.domain import (
    CURRENT_PROTOTYPE_VERSION,
    ConditioningDocument,
    FindingSeverity,
    InfluenceFieldAssetReference,
    validate_document,
)

from .canonical import canonical_json_text, sha256_canonical
from .identity import (
    fingerprint_capability_execution_projection,
    fingerprint_document_execution_projection,
    fingerprint_execution_profile_projection,
)
from .models import (
    CAPABILITY_EXECUTION_PROJECTION_IDENTIFIER,
    CAPABILITY_EXECUTION_PROJECTION_VERSION,
    CAPABILITY_POLICY_IDENTIFIER,
    CAPABILITY_POLICY_VERSION,
    DOCUMENT_EXECUTION_PROJECTION_IDENTIFIER,
    DOCUMENT_EXECUTION_PROJECTION_VERSION,
    EXECUTION_PROFILE_PROJECTION_IDENTIFIER,
    EXECUTION_PROFILE_PROJECTION_VERSION,
    CapabilityDecision,
    CapabilityExecutionProjection,
    DocumentExecutionLayer,
    DocumentExecutionProjection,
    ExecutionProfileProjection,
)


PREDICTION_MIXING_BACKEND_IDENTIFIER = "krea2.comfyui"
PREDICTION_MIXING_FIELD_ENCODING = "grayscale-8"


def build_document_execution_projection(
    document: ConditioningDocument,
) -> DocumentExecutionProjection:
    """Validate and project exact execution-relevant document semantics."""

    if not isinstance(document, ConditioningDocument):
        raise TypeError("document must be a ConditioningDocument")
    errors = tuple(
        item
        for item in validate_document(document)
        if item.severity is FindingSeverity.ERROR
    )
    if errors:
        raise ValueError(
            "document cannot be projected: "
            + ", ".join(item.code for item in errors)
        )
    if document.version != CURRENT_PROTOTYPE_VERSION:
        raise ValueError("document cannot be projected: unsupported exact version")

    settings_json = canonical_json_text(dict(document.adapter_settings))
    projected_layers: list[DocumentExecutionLayer] = []
    for layer in document.active_layers:
        reference = layer.influence_field
        if not isinstance(reference, InfluenceFieldAssetReference):
            raise ValueError(
                "document cannot be projected: active field reference required"
            )
        projected_layers.append(
            DocumentExecutionLayer(
                active_ordinal=len(projected_layers),
                layer_id=layer.layer_id,
                prompt_text=layer.prompt_text,
                requested_strength=float(layer.strength),
                influence_field_reference=reference.relative_path.replace("\\", "/"),
                declared_field_sha256=(
                    reference.checksum.lower()
                    if reference.checksum is not None
                    else None
                ),
            )
        )
    projection = DocumentExecutionProjection(
        format_identifier=DOCUMENT_EXECUTION_PROJECTION_IDENTIFIER,
        format_version=DOCUMENT_EXECUTION_PROJECTION_VERSION,
        source_document_major_version=document.version.major,
        source_document_minor_version=document.version.minor,
        selected_adapter_identifier=document.selected_adapter_id,
        canonical_adapter_settings_json=settings_json,
        base_prompt_text=document.base_prompt,
        active_layers=tuple(projected_layers),
        fingerprint="",
    )
    return replace(
        projection,
        fingerprint=fingerprint_document_execution_projection(projection),
    )


def serialize_document_execution_projection(
    projection: DocumentExecutionProjection,
) -> bytes:
    """Serialize one document projection to its canonical identity bytes."""

    if not isinstance(projection, DocumentExecutionProjection):
        raise TypeError("projection must be a DocumentExecutionProjection")
    from .canonical import canonical_json_bytes

    return canonical_json_bytes(projection)


def build_capability_execution_projection(
    document: ConditioningDocument,
    document_projection: DocumentExecutionProjection,
) -> CapabilityExecutionProjection:
    """Freshly evaluate the exact document and project semantic capability data."""

    expected_document = build_document_execution_projection(document)
    if document_projection != expected_document:
        raise ValueError("capability projection subject does not match document")
    evaluation = evaluate_prediction_mixing(document)
    return _capability_projection(evaluation, document, document_projection)


def fingerprint_capability_policy() -> str:
    """Fingerprint the execution-relevant canonical capability policy."""

    capability = PREDICTION_MIXING_CAPABILITY
    material = {
        "adapter_identifier": capability.adapter_identifier,
        "adapter_selection_required": True,
        "adapter_settings_supported": False,
        "continuous_field_status": capability.continuous_fields.status.value,
        "disabled_layers_excluded": True,
        "field_format": "png",
        "field_reference_required": True,
        "homogeneous_condition_kind": HOMOGENEOUS_PROMPT_LAYER_CONDITION_KIND,
        "maximum_active_layer_count": (
            capability.maximum_tested_visible_prompt_layers
        ),
        "minimum_active_layer_count": capability.minimum_visible_prompt_layers,
        "overlap_status": capability.overlap.status.value,
        "policy_identifier": CAPABILITY_POLICY_IDENTIFIER,
        "policy_version": CAPABILITY_POLICY_VERSION,
        "retained_order_status": capability.retained_order_execution.status.value,
        "strength_maximum": 1.0,
        "strength_minimum": 0.0,
        "supported_layer_type": capability.supported_layer_type,
        "zero_strength_active_is_represented": True,
    }
    return sha256_canonical(material)


def serialize_capability_execution_projection(
    projection: CapabilityExecutionProjection,
) -> bytes:
    """Serialize one capability projection to canonical identity bytes."""

    if not isinstance(projection, CapabilityExecutionProjection):
        raise TypeError("projection must be a CapabilityExecutionProjection")
    from .canonical import canonical_json_bytes

    return canonical_json_bytes(projection)


def build_execution_profile_projection(
    profile: PredictionMixingExecutionProfile = PREDICTION_MIXING_EXECUTION_PROFILE,
) -> ExecutionProfileProjection:
    """Derive the narrow execution-semantic projection of a known profile."""

    if not isinstance(profile, PredictionMixingExecutionProfile):
        raise TypeError("profile must be a PredictionMixingExecutionProfile")
    projection = ExecutionProfileProjection(
        format_identifier=EXECUTION_PROFILE_PROJECTION_IDENTIFIER,
        format_version=EXECUTION_PROFILE_PROJECTION_VERSION,
        profile_identifier=profile.profile_identifier,
        adapter_identifier=profile.adapter_identifier,
        backend_identifier=PREDICTION_MIXING_BACKEND_IDENTIFIER,
        model_family=profile.model_family,
        model_variant=profile.model_variant,
        output_width=profile.output_width,
        output_height=profile.output_height,
        latent_width=profile.latent_width,
        latent_height=profile.latent_height,
        expected_field_width=profile.expected_field_width,
        expected_field_height=profile.expected_field_height,
        expected_field_encoding=PREDICTION_MIXING_FIELD_ENCODING,
        base_prompt_policy=profile.base_prompt_policy.value,
        prompt_combination_delimiter=PROMPT_COMBINATION_DELIMITER,
        negative_prompt_policy=profile.negative_prompt_policy.value,
        effective_weight_expression=EFFECTIVE_WEIGHT_EXPRESSION,
        homogeneous_condition_kind=HOMOGENEOUS_PROMPT_LAYER_CONDITION_KIND,
        fingerprint="",
    )
    return replace(
        projection,
        fingerprint=fingerprint_execution_profile_projection(projection),
    )


def serialize_execution_profile_projection(
    projection: ExecutionProfileProjection,
) -> bytes:
    """Serialize one profile projection to canonical identity bytes."""

    if not isinstance(projection, ExecutionProfileProjection):
        raise TypeError("projection must be an ExecutionProfileProjection")
    from .canonical import canonical_json_bytes

    return canonical_json_bytes(projection)


def _capability_projection(
    evaluation: CapabilityEvaluation,
    document: ConditioningDocument,
    document_projection: DocumentExecutionProjection,
) -> CapabilityExecutionProjection:
    active_ordinals = {
        layer.layer_id: ordinal
        for ordinal, layer in enumerate(document.active_layers)
    }
    decisions = tuple(
        sorted(
            (
                CapabilityDecision(
                    code=item.code,
                    active_ordinal=active_ordinals.get(item.layer_id),
                    layer_id=item.layer_id,
                    field_path=item.field_path,
                )
                for item in evaluation.errors
            ),
            key=_decision_sort_key,
        )
    )
    accepted_constraints = tuple(
        CapabilityDecision(
            code="capability.zero_strength_active",
            active_ordinal=ordinal,
            layer_id=layer.layer_id,
            field_path="layers.strength",
        )
        for ordinal, layer in enumerate(document.active_layers)
        if float(layer.strength) == 0.0
    )
    projection = CapabilityExecutionProjection(
        format_identifier=CAPABILITY_EXECUTION_PROJECTION_IDENTIFIER,
        format_version=CAPABILITY_EXECUTION_PROJECTION_VERSION,
        capability_policy_identifier=CAPABILITY_POLICY_IDENTIFIER,
        capability_policy_version=CAPABILITY_POLICY_VERSION,
        capability_policy_fingerprint=fingerprint_capability_policy(),
        subject_document_projection_fingerprint=document_projection.fingerprint,
        authoritative_adapter_identifier=(
            PREDICTION_MIXING_CAPABILITY.adapter_identifier
        ),
        selected_adapter_identifier=evaluation.selected_adapter_identifier,
        compatible=evaluation.compatible,
        active_layer_count=evaluation.active_layer_count,
        homogeneous_condition_kind=HOMOGENEOUS_PROMPT_LAYER_CONDITION_KIND,
        minimum_active_layer_count=(
            PREDICTION_MIXING_CAPABILITY.minimum_visible_prompt_layers
        ),
        maximum_active_layer_count=(
            PREDICTION_MIXING_CAPABILITY.maximum_tested_visible_prompt_layers
        ),
        decisions=decisions,
        accepted_constraints=accepted_constraints,
        fingerprint="",
    )
    return replace(
        projection,
        fingerprint=fingerprint_capability_execution_projection(projection),
    )


def _decision_sort_key(item: CapabilityDecision) -> tuple[object, ...]:
    return (
        item.code,
        item.active_ordinal if item.active_ordinal is not None else (1 << 53) - 1,
        item.layer_id or "",
        item.field_path or "",
    )
