"""Metadata-only validation for Prediction Mixing translation inputs."""

from __future__ import annotations

import math
import re

from conditioning_layers.capabilities import PredictionMixingCapability
from conditioning_layers.domain import (
    ConditioningDocument,
    FindingSeverity,
    InfluenceFieldAssetReference,
    ValidationFinding,
)

from .models import (
    BasePromptPolicy,
    FieldAssetProfile,
    FieldChannelProfile,
    FieldValueKind,
    NegativePromptPolicy,
    OverlapAssessment,
    OverlapPolicy,
    PredictionMixingExecutionProfile,
    PROVENANCE_PROFILE_IDENTIFIER,
)


_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


def validate_translation_inputs(
    document: ConditioningDocument,
    field_profiles: tuple[FieldAssetProfile, ...],
    execution_profile: PredictionMixingExecutionProfile,
    overlap_assessment: OverlapAssessment | None,
    capability: PredictionMixingCapability,
) -> tuple[ValidationFinding, ...]:
    """Return every metadata-level translation error without accessing assets."""

    if not isinstance(document, ConditioningDocument):
        raise TypeError("document must be a ConditioningDocument")
    if not isinstance(field_profiles, tuple) or not all(
        isinstance(profile, FieldAssetProfile) for profile in field_profiles
    ):
        raise TypeError("field_profiles must be a tuple of FieldAssetProfile values")
    if not isinstance(execution_profile, PredictionMixingExecutionProfile):
        raise TypeError(
            "execution_profile must be a PredictionMixingExecutionProfile"
        )
    if overlap_assessment is not None and not isinstance(
        overlap_assessment, OverlapAssessment
    ):
        raise TypeError("overlap_assessment must be OverlapAssessment or None")
    if not isinstance(capability, PredictionMixingCapability):
        raise TypeError("capability must be a PredictionMixingCapability")

    findings: list[ValidationFinding] = []
    active_layers = document.active_layers
    active_ids = tuple(layer.layer_id for layer in active_layers)

    profiles_by_id: dict[str, FieldAssetProfile] = {}
    duplicate_ids: set[str] = set()
    for profile in field_profiles:
        if profile.layer_id in profiles_by_id:
            duplicate_ids.add(profile.layer_id)
        else:
            profiles_by_id[profile.layer_id] = profile

    for layer_id in sorted(duplicate_ids):
        findings.append(
            _error(
                "translation.field_profile_duplicate",
                "Only one field profile may be supplied for each active layer.",
                layer_id=layer_id,
                field_path="field_profiles",
            )
        )

    for layer_id in active_ids:
        if layer_id not in profiles_by_id:
            findings.append(
                _error(
                    "translation.field_profile_missing",
                    "An active Prompt Layer is missing its field asset profile.",
                    layer_id=layer_id,
                    field_path="field_profiles",
                )
            )

    for profile in field_profiles:
        if profile.layer_id not in active_ids:
            findings.append(
                _error(
                    "translation.field_profile_extra",
                    "A field asset profile does not correspond to an active Prompt Layer.",
                    layer_id=profile.layer_id,
                    field_path="field_profiles",
                )
            )

    for profile in field_profiles:
        findings.extend(_validate_field_profile(profile, execution_profile))

    for layer in active_layers:
        profile = profiles_by_id.get(layer.layer_id)
        if profile is None:
            continue
        reference = layer.influence_field
        if isinstance(reference, InfluenceFieldAssetReference):
            expected_reference = reference.relative_path.replace("\\", "/")
            if profile.relative_path != expected_reference:
                findings.append(
                    _error(
                        "translation.field_reference_mismatch",
                        "Field profile reference does not match the document reference.",
                        layer_id=layer.layer_id,
                        field_path="field_profiles.relative_path",
                    )
                )
            if (
                reference.checksum is not None
                and profile.checksum is not None
                and reference.checksum.lower() != profile.checksum.lower()
            ):
                findings.append(
                    _error(
                        "translation.field_checksum_mismatch",
                        "Field profile checksum does not match the document checksum.",
                        layer_id=layer.layer_id,
                        field_path="field_profiles.checksum",
                    )
                )

    findings.extend(_validate_execution_profile(execution_profile, capability))
    findings.extend(_validate_overlap(len(active_layers), overlap_assessment))
    return tuple(findings)


def _validate_field_profile(
    profile: FieldAssetProfile,
    execution_profile: PredictionMixingExecutionProfile,
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    layer_id = profile.layer_id

    if (
        isinstance(profile.width, bool)
        or not isinstance(profile.width, int)
        or isinstance(profile.height, bool)
        or not isinstance(profile.height, int)
        or profile.width <= 0
        or profile.height <= 0
        or profile.width != execution_profile.expected_field_width
        or profile.height != execution_profile.expected_field_height
    ):
        findings.append(
            _error(
                "translation.field_dimensions",
                "Field dimensions must match the execution profile exactly.",
                layer_id=layer_id,
                field_path="field_profiles.dimensions",
            )
        )

    expected_channels = {
        FieldChannelProfile.GRAYSCALE_8: 1,
        FieldChannelProfile.RGB_IDENTICAL_8: 3,
    }
    if (
        not isinstance(profile.channel_profile, FieldChannelProfile)
        or isinstance(profile.channel_count, bool)
        or not isinstance(profile.channel_count, int)
        or expected_channels.get(profile.channel_profile) != profile.channel_count
    ):
        findings.append(
            _error(
                "translation.field_channel_profile",
                "Field profile must declare supported 8-bit grayscale or identical-channel RGB data.",
                layer_id=layer_id,
                field_path="field_profiles.channel_profile",
            )
        )

    minimum = profile.minimum_normalized_value
    maximum = profile.maximum_normalized_value
    numeric_range = (
        isinstance(minimum, (int, float))
        and not isinstance(minimum, bool)
        and isinstance(maximum, (int, float))
        and not isinstance(maximum, bool)
    )
    values_are_finite = (
        profile.finite_values is True
        and numeric_range
        and math.isfinite(minimum)
        and math.isfinite(maximum)
    )
    if not values_are_finite:
        findings.append(
            _error(
                "translation.field_nonfinite",
                "Field metadata must certify finite normalized values.",
                layer_id=layer_id,
                field_path="field_profiles.finite_values",
            )
        )
    elif not 0.0 <= minimum < maximum <= 1.0:
        findings.append(
            _error(
                "translation.field_range",
                "Field minimum and maximum must satisfy 0.0 <= minimum < maximum <= 1.0.",
                layer_id=layer_id,
                field_path="field_profiles.normalized_range",
            )
        )

    if not isinstance(profile.value_kind, FieldValueKind):
        findings.append(
            _error(
                "translation.field_value_kind",
                "Field value kind must be binary or continuous.",
                layer_id=layer_id,
                field_path="field_profiles.value_kind",
            )
        )
    elif (
        profile.value_kind is FieldValueKind.BINARY
        and values_are_finite
        and (minimum != 0.0 or maximum != 1.0)
    ):
        findings.append(
            _error(
                "translation.field_range",
                "A binary field profile must declare the normalized range 0.0 through 1.0.",
                layer_id=layer_id,
                field_path="field_profiles.normalized_range",
            )
        )

    if (
        not isinstance(profile.relative_path, str)
        or not profile.relative_path.lower().endswith(".png")
        or "\\" in profile.relative_path
    ):
        findings.append(
            _error(
                "translation.field_reference_mismatch",
                "Field profile reference must be a canonical relative PNG path.",
                layer_id=layer_id,
                field_path="field_profiles.relative_path",
            )
        )

    if profile.checksum is not None and (
        not isinstance(profile.checksum, str)
        or _SHA256_PATTERN.fullmatch(profile.checksum) is None
    ):
        findings.append(
            _error(
                "translation.field_checksum",
                "Field profile checksum must be a SHA-256 hex digest when supplied.",
                layer_id=layer_id,
                field_path="field_profiles.checksum",
            )
        )
    return findings


def _validate_execution_profile(
    profile: PredictionMixingExecutionProfile,
    capability: PredictionMixingCapability,
) -> list[ValidationFinding]:
    # This is a frozen v1 artifact-contract check. The capability record owns
    # eligibility; the profile must agree with it so a caller cannot smuggle a
    # wider plan into the historical translator.
    invalid_fields: list[str] = []
    expected_exact = (
        ("adapter_identifier", capability.adapter_identifier),
        ("model_family", "Krea 2"),
        ("model_variant", "Turbo BF16"),
        ("output_width", 1024),
        ("output_height", 1024),
        ("latent_width", 128),
        ("latent_height", 128),
        ("expected_field_width", 128),
        ("expected_field_height", 128),
        ("maximum_active_layers", capability.maximum_tested_visible_prompt_layers),
        ("overlap_policy", OverlapPolicy.REQUIRE_NO_OVERLAP),
        ("base_prompt_policy", BasePromptPolicy.REPEAT_IN_REGIONAL_PROMPTS),
        ("negative_prompt_policy", NegativePromptPolicy.EMPTY),
        ("provenance_profile_identifier", PROVENANCE_PROFILE_IDENTIFIER),
    )
    for field_name, expected in expected_exact:
        if getattr(profile, field_name) != expected:
            invalid_fields.append(field_name)

    for field_name in (
        "profile_identifier",
        "tested_hardware_note",
    ):
        value = getattr(profile, field_name)
        if not isinstance(value, str) or not value.strip():
            invalid_fields.append(field_name)

    if not invalid_fields:
        return []
    return [
        _error(
            "translation.execution_profile",
            "Execution profile is unsupported or malformed: "
            + ", ".join(invalid_fields)
            + ".",
            field_path="execution_profile",
        )
    ]


def _validate_overlap(
    active_layer_count: int,
    assessment: OverlapAssessment | None,
) -> list[ValidationFinding]:
    if active_layer_count == 1:
        if assessment is None:
            return []
        return [
            _error(
                "translation.overlap_unexpected",
                "One-layer translation does not accept a pairwise overlap assessment.",
                field_path="overlap_assessment",
            )
        ]
    if active_layer_count != 2:
        return []
    if assessment is OverlapAssessment.NO_OVERLAP:
        return []
    if assessment is OverlapAssessment.OVERLAP_PRESENT:
        return [
            _error(
                "translation.overlap_present",
                "Prediction Mixing does not support overlapping active Influence Fields.",
                field_path="overlap_assessment",
            )
        ]
    return [
        _error(
            "translation.overlap_unknown",
            "Two-layer translation requires an external NO_OVERLAP assessment.",
            field_path="overlap_assessment",
        )
    ]


def _error(
    code: str,
    message: str,
    *,
    layer_id: str | None = None,
    field_path: str | None = None,
) -> ValidationFinding:
    return ValidationFinding(
        code=code,
        severity=FindingSeverity.ERROR,
        message=message,
        layer_id=layer_id,
        field_path=field_path,
    )
