"""Deterministic Prediction Mixing translation with no host or asset I/O."""

from __future__ import annotations

import hashlib
import json

from conditioning_layers.capabilities import (
    PREDICTION_MIXING_CAPABILITY,
    PredictionMixingCapability,
    evaluate_prediction_mixing,
)
from conditioning_layers.domain import (
    ConditioningDocument,
    FindingSeverity,
    InfluenceFieldAssetReference,
    ValidationFinding,
)

from .models import (
    EFFECTIVE_WEIGHT_EXPRESSION,
    ORDER_SEMANTICS,
    PREDICTION_MIXING_EXECUTION_PROFILE,
    PROMPT_COMBINATION_DELIMITER,
    TRANSLATION_PLAN_VERSION,
    FieldAssetProfile,
    LayerProvenanceInput,
    OverlapAssessment,
    PredictionMixingExecutionProfile,
    PredictionMixingTranslationPlan,
    PredictionMixingTranslationResult,
    RegionalConditionPlan,
    TranslationProvenanceInputs,
)
from .validation import validate_translation_inputs


def translate_prediction_mixing(
    document: ConditioningDocument,
    field_profiles: tuple[FieldAssetProfile, ...],
    *,
    execution_profile: PredictionMixingExecutionProfile = (
        PREDICTION_MIXING_EXECUTION_PROFILE
    ),
    overlap_assessment: OverlapAssessment | None = None,
    capability: PredictionMixingCapability = PREDICTION_MIXING_CAPABILITY,
) -> PredictionMixingTranslationResult:
    """Translate validated intent into an immutable prototype-internal plan."""

    if not isinstance(capability, PredictionMixingCapability):
        raise TypeError("capability must be a PredictionMixingCapability")

    capability_evaluation = evaluate_prediction_mixing(document)
    errors: list[ValidationFinding] = []
    if capability != PREDICTION_MIXING_CAPABILITY:
        _append_unique(
            errors,
            _finding(
                "translation.capability_incompatible",
                FindingSeverity.ERROR,
                "Translation requires the canonical Prediction Mixing capability record.",
                field_path="capability",
            ),
        )
    if not capability_evaluation.compatible:
        _append_unique(
            errors,
            _finding(
                "translation.capability_incompatible",
                FindingSeverity.ERROR,
                "Capability evaluation rejected this Conditioning Document.",
                field_path="document",
            ),
        )

    for finding in validate_translation_inputs(
        document,
        field_profiles,
        execution_profile,
        overlap_assessment,
        capability,
    ):
        errors.append(finding)

    warnings = list(capability_evaluation.warnings)
    if isinstance(document.base_prompt, str) and document.base_prompt.strip():
        _append_unique(
            warnings,
            _finding(
                "translation.base_prompt_repeated",
                FindingSeverity.WARNING,
                (
                    "The Base Prompt is repeated in every regional condition and no "
                    "separate global prediction item is emitted; competing scene "
                    "interpretations can contribute to seams, leakage, fusion, or "
                    "topology changes."
                ),
                field_path="base_prompt",
            ),
        )

    compatible = not errors
    if not compatible:
        return PredictionMixingTranslationResult(
            plan=None,
            errors=tuple(errors),
            warnings=tuple(warnings),
            information=(),
            capability_evaluation=capability_evaluation,
            capability=capability,
            compatible=False,
            translated=False,
        )

    profiles_by_id = {profile.layer_id: profile for profile in field_profiles}
    active_conditions: list[RegionalConditionPlan] = []
    ordered_profiles: list[FieldAssetProfile] = []
    provenance_layers: list[LayerProvenanceInput] = []

    for document_index, layer in enumerate(document.layers):
        if layer.visible is not True:
            continue
        profile = profiles_by_id[layer.layer_id]
        combined_prompt = combine_prompt_text(
            document.base_prompt,
            layer.prompt_text,
        )
        active_conditions.append(
            RegionalConditionPlan(
                layer_id=layer.layer_id,
                layer_name=layer.name,
                regional_prompt_text=layer.prompt_text,
                combined_prompt_text=combined_prompt,
                field_profile=profile,
                requested_strength=float(layer.strength),
                document_index=document_index,
                effective_weight_expression=EFFECTIVE_WEIGHT_EXPRESSION,
            )
        )
        ordered_profiles.append(profile)
        reference = layer.influence_field
        document_checksum = (
            reference.checksum
            if isinstance(reference, InfluenceFieldAssetReference)
            else None
        )
        provenance_layers.append(
            LayerProvenanceInput(
                layer_id=layer.layer_id,
                regional_prompt_sha256=_sha256_text(layer.prompt_text),
                combined_prompt_sha256=_sha256_text(combined_prompt),
                field_reference=profile.relative_path,
                field_checksum=profile.checksum or document_checksum,
            )
        )

    warning_codes = tuple(_unique_codes(warnings))
    document_version = f"{document.version.major}.{document.version.minor}"
    fingerprint_payload = _fingerprint_payload(
        document=document,
        active_conditions=tuple(active_conditions),
        excluded_disabled_layer_ids=tuple(
            layer.layer_id for layer in document.layers if layer.visible is False
        ),
        field_profiles=tuple(ordered_profiles),
        overlap_assessment=overlap_assessment,
        execution_profile=execution_profile,
        capability_identifier=capability.adapter_identifier,
        warning_codes=warning_codes,
        provenance_layers=tuple(provenance_layers),
        document_version=document_version,
    )
    fingerprint = _sha256_json(fingerprint_payload)
    provenance = TranslationProvenanceInputs(
        document_id=document.document_id,
        document_version=document_version,
        adapter_identifier=capability.adapter_identifier,
        translation_plan_fingerprint=fingerprint,
        layers=tuple(provenance_layers),
        execution_profile_identifier=execution_profile.profile_identifier,
        capability_identifier=capability.adapter_identifier,
        warning_codes=warning_codes,
    )
    plan = PredictionMixingTranslationPlan(
        translation_plan_version=TRANSLATION_PLAN_VERSION,
        document_id=document.document_id,
        adapter_identifier=capability.adapter_identifier,
        capability_identifier=capability.adapter_identifier,
        base_prompt_text=document.base_prompt,
        active_regional_conditions=tuple(active_conditions),
        excluded_disabled_layer_ids=tuple(
            layer.layer_id for layer in document.layers if layer.visible is False
        ),
        active_layer_count=len(active_conditions),
        field_profiles=tuple(ordered_profiles),
        effective_weight_expression=EFFECTIVE_WEIGHT_EXPRESSION,
        document_order_layer_ids=tuple(layer.layer_id for layer in document.layers),
        order_semantics=ORDER_SEMANTICS,
        separate_global_condition_emitted=False,
        overlap_assessment=overlap_assessment,
        execution_profile=execution_profile,
        mandatory_warning_codes=warning_codes,
        provenance_inputs=provenance,
        fingerprint=fingerprint,
    )
    information = (
        _finding(
            "translation.plan_created",
            FindingSeverity.INFORMATION,
            "A deterministic prototype-internal translation plan was created.",
        ),
    )
    return PredictionMixingTranslationResult(
        plan=plan,
        errors=(),
        warnings=tuple(warnings),
        information=information,
        capability_evaluation=capability_evaluation,
        capability=capability,
        compatible=True,
        translated=True,
    )


def combine_prompt_text(base_prompt: str, regional_prompt: str) -> str:
    """Combine artist text exactly with two newlines and no semantic rewriting."""

    if not isinstance(base_prompt, str) or not isinstance(regional_prompt, str):
        raise TypeError("base_prompt and regional_prompt must be strings")
    return base_prompt + PROMPT_COMBINATION_DELIMITER + regional_prompt


def _fingerprint_payload(
    *,
    document: ConditioningDocument,
    active_conditions: tuple[RegionalConditionPlan, ...],
    excluded_disabled_layer_ids: tuple[str, ...],
    field_profiles: tuple[FieldAssetProfile, ...],
    overlap_assessment: OverlapAssessment | None,
    execution_profile: PredictionMixingExecutionProfile,
    capability_identifier: str,
    warning_codes: tuple[str, ...],
    provenance_layers: tuple[LayerProvenanceInput, ...],
    document_version: str,
) -> dict[str, object]:
    return {
        "translation_plan_version": TRANSLATION_PLAN_VERSION,
        "document_id": document.document_id,
        "document_version": document_version,
        "adapter_identifier": capability_identifier,
        "capability_identifier": capability_identifier,
        "base_prompt_text": document.base_prompt,
        "active_regional_conditions": [
            {
                "layer_id": condition.layer_id,
                "layer_name": condition.layer_name,
                "regional_prompt_text": condition.regional_prompt_text,
                "combined_prompt_text": condition.combined_prompt_text,
                "requested_strength": condition.requested_strength,
                "document_index": condition.document_index,
                "effective_weight_expression": (
                    condition.effective_weight_expression
                ),
                "field_profile": _field_profile_payload(condition.field_profile),
            }
            for condition in active_conditions
        ],
        "excluded_disabled_layer_ids": list(excluded_disabled_layer_ids),
        "active_layer_count": len(active_conditions),
        "field_profiles": [
            _field_profile_payload(profile) for profile in field_profiles
        ],
        "effective_weight_expression": EFFECTIVE_WEIGHT_EXPRESSION,
        "document_order_layer_ids": [layer.layer_id for layer in document.layers],
        "order_semantics": ORDER_SEMANTICS,
        "separate_global_condition_emitted": False,
        "overlap_assessment": (
            overlap_assessment.value if overlap_assessment is not None else None
        ),
        "execution_profile": _execution_profile_payload(execution_profile),
        "mandatory_warning_codes": list(warning_codes),
        "provenance_layers": [
            {
                "layer_id": layer.layer_id,
                "regional_prompt_sha256": layer.regional_prompt_sha256,
                "combined_prompt_sha256": layer.combined_prompt_sha256,
                "field_reference": layer.field_reference,
                "field_checksum": layer.field_checksum,
            }
            for layer in provenance_layers
        ],
    }


def _field_profile_payload(profile: FieldAssetProfile) -> dict[str, object]:
    return {
        "layer_id": profile.layer_id,
        "relative_path": profile.relative_path,
        "checksum": profile.checksum,
        "width": profile.width,
        "height": profile.height,
        "channel_count": profile.channel_count,
        "channel_profile": profile.channel_profile.value,
        "minimum_normalized_value": profile.minimum_normalized_value,
        "maximum_normalized_value": profile.maximum_normalized_value,
        "finite_values": profile.finite_values,
        "value_kind": profile.value_kind.value,
    }


def _execution_profile_payload(
    profile: PredictionMixingExecutionProfile,
) -> dict[str, object]:
    return {
        "adapter_identifier": profile.adapter_identifier,
        "model_family": profile.model_family,
        "model_variant": profile.model_variant,
        "profile_identifier": profile.profile_identifier,
        "output_width": profile.output_width,
        "output_height": profile.output_height,
        "latent_width": profile.latent_width,
        "latent_height": profile.latent_height,
        "expected_field_width": profile.expected_field_width,
        "expected_field_height": profile.expected_field_height,
        "tested_hardware_note": profile.tested_hardware_note,
        "maximum_active_layers": profile.maximum_active_layers,
        "overlap_policy": profile.overlap_policy.value,
        "base_prompt_policy": profile.base_prompt_policy.value,
        "negative_prompt_policy": profile.negative_prompt_policy.value,
        "provenance_profile_identifier": (
            profile.provenance_profile_identifier
        ),
    }


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _unique_codes(findings: list[ValidationFinding]) -> list[str]:
    codes: list[str] = []
    for finding in findings:
        if finding.code not in codes:
            codes.append(finding.code)
    return codes


def _append_unique(
    findings: list[ValidationFinding],
    candidate: ValidationFinding,
) -> None:
    if all(existing.code != candidate.code for existing in findings):
        findings.append(candidate)


def _finding(
    code: str,
    severity: FindingSeverity,
    message: str,
    *,
    layer_id: str | None = None,
    field_path: str | None = None,
) -> ValidationFinding:
    return ValidationFinding(
        code=code,
        severity=severity,
        message=message,
        layer_id=layer_id,
        field_path=field_path,
    )
