"""Read-only field orchestration, validation, overlap, and adapter conversion."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re

from conditioning_layers.adapters.prediction_mixing import (
    FieldAssetProfile,
    FieldChannelProfile,
    FieldValueKind,
    OverlapAssessment,
    PREDICTION_MIXING_EXECUTION_PROFILE,
    PredictionMixingExecutionProfile,
)
from conditioning_layers.domain import (
    FindingSeverity,
    InfluenceFieldAssetReference,
    PromptLayer,
    ValidationFinding,
)
from conditioning_layers.persistence import document_asset_root

from .errors import AssetInspectionError
from .models import (
    DEFAULT_INSPECTION_LIMITS,
    CertifiedOverlap,
    DimensionValidationResult,
    FieldInspectionResult,
    InspectionLimits,
    InspectedChannelProfile,
    InspectedFieldProfile,
    InspectedValueKind,
    OverlapEvidence,
    OverlapInspectionResult,
    PairInspectionResult,
)
from .paths import resolve_field_asset
from .png_inspector import DecodedField, inspect_png_bytes


_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


def inspect_document_field(
    document_path: str | Path,
    layer: PromptLayer,
    *,
    execution_profile: PredictionMixingExecutionProfile = (
        PREDICTION_MIXING_EXECUTION_PROFILE
    ),
    limits: InspectionLimits = DEFAULT_INSPECTION_LIMITS,
) -> FieldInspectionResult:
    """Inspect one layer using persistence's document-owned asset-root rule."""

    return inspect_field_asset(
        document_asset_root(document_path),
        layer,
        execution_profile=execution_profile,
        limits=limits,
    )


def inspect_document_pair(
    document_path: str | Path,
    first_layer: PromptLayer,
    second_layer: PromptLayer,
    *,
    execution_profile: PredictionMixingExecutionProfile = (
        PREDICTION_MIXING_EXECUTION_PROFILE
    ),
    limits: InspectionLimits = DEFAULT_INSPECTION_LIMITS,
) -> PairInspectionResult:
    """Inspect a pair using persistence's document-owned asset-root rule."""

    return inspect_field_pair(
        document_asset_root(document_path),
        first_layer,
        second_layer,
        execution_profile=execution_profile,
        limits=limits,
    )


def inspect_field_asset(
    asset_root: str | Path,
    layer: PromptLayer,
    *,
    execution_profile: PredictionMixingExecutionProfile = (
        PREDICTION_MIXING_EXECUTION_PROFILE
    ),
    limits: InspectionLimits = DEFAULT_INSPECTION_LIMITS,
) -> FieldInspectionResult:
    """Inspect one active layer and discard decoded pixels before returning."""

    result, _ = _inspect_with_values(
        asset_root, layer, execution_profile=execution_profile, limits=limits
    )
    return result


def inspect_field_pair(
    asset_root: str | Path,
    first_layer: PromptLayer,
    second_layer: PromptLayer,
    *,
    execution_profile: PredictionMixingExecutionProfile = (
        PREDICTION_MIXING_EXECUTION_PROFILE
    ),
    limits: InspectionLimits = DEFAULT_INSPECTION_LIMITS,
) -> PairInspectionResult:
    """Inspect exactly two fields once and certify their pairwise overlap."""

    first_result, first_decoded = _inspect_with_values(
        asset_root, first_layer, execution_profile=execution_profile, limits=limits
    )
    second_result, second_decoded = _inspect_with_values(
        asset_root, second_layer, execution_profile=execution_profile, limits=limits
    )
    sources = (first_result.source_reference, second_result.source_reference)
    checksums = (first_result.checksum, second_result.checksum)

    if first_decoded is not None and second_decoded is not None and (
        first_decoded.profile.width != second_decoded.profile.width
        or first_decoded.profile.height != second_decoded.profile.height
    ):
        finding = _finding(
            "overlap.dimensions",
            FindingSeverity.ERROR,
            "Pairwise overlap requires identical field dimensions.",
        )
        overlap = OverlapInspectionResult(
            certified=False,
            evidence=None,
            errors=(finding,),
            warnings=(),
            information=(),
            source_references=sources,
            checksums=checksums,
            input_digest=None,
        )
    elif (
        not first_result.certified
        or not second_result.certified
        or first_decoded is None
        or second_decoded is None
    ):
        finding = _finding(
            "overlap.inspection_failed",
            FindingSeverity.ERROR,
            "Pairwise overlap cannot be certified until both fields are certified.",
        )
        overlap = OverlapInspectionResult(
            certified=False,
            evidence=None,
            errors=(finding,),
            warnings=(),
            information=(),
            source_references=sources,
            checksums=checksums,
            input_digest=None,
        )
    else:
        overlap = _assess_overlap(first_decoded, second_decoded)

    return PairInspectionResult(fields=(first_result, second_result), overlap=overlap)


def to_field_asset_profile(result: FieldInspectionResult) -> FieldAssetProfile | None:
    """Convert only certified neutral measurements into the Slice 4 input."""

    if not result.certified or result.profile is None:
        return None
    profile = result.profile
    channel_profile = {
        InspectedChannelProfile.GRAYSCALE_8: FieldChannelProfile.GRAYSCALE_8,
        InspectedChannelProfile.RGB_IDENTICAL_8: FieldChannelProfile.RGB_IDENTICAL_8,
    }[profile.channel_profile]
    value_kind = {
        InspectedValueKind.BINARY: FieldValueKind.BINARY,
        InspectedValueKind.CONTINUOUS: FieldValueKind.CONTINUOUS,
    }[profile.value_kind]
    return FieldAssetProfile(
        layer_id=profile.layer_id,
        relative_path=profile.relative_path,
        checksum=profile.checksum,
        width=profile.width,
        height=profile.height,
        channel_count=profile.channel_count,
        channel_profile=channel_profile,
        minimum_normalized_value=profile.minimum_normalized_value,
        maximum_normalized_value=profile.maximum_normalized_value,
        finite_values=profile.finite_values,
        value_kind=value_kind,
    )


def to_overlap_assessment(
    result: OverlapInspectionResult,
) -> OverlapAssessment | None:
    """Convert only a certified pairwise state into the Slice 4 input."""

    if not result.certified or result.evidence is None:
        return None
    if result.evidence.assessment is CertifiedOverlap.NO_OVERLAP:
        return OverlapAssessment.NO_OVERLAP
    return OverlapAssessment.OVERLAP_PRESENT


def validate_field_dimensions(
    profile: InspectedFieldProfile,
    execution_profile: PredictionMixingExecutionProfile,
) -> DimensionValidationResult:
    """Compare explicit field dimensions exactly; never infer or resize."""

    matches = (
        profile.width == execution_profile.expected_field_width
        and profile.height == execution_profile.expected_field_height
    )
    errors = ()
    if not matches:
        errors = (
            _finding(
                "asset.dimensions",
                FindingSeverity.ERROR,
                (
                    f"Field dimensions {profile.width}x{profile.height} do not match "
                    f"expected {execution_profile.expected_field_width}x"
                    f"{execution_profile.expected_field_height}."
                ),
                layer_id=profile.layer_id,
                field_path="influence_field",
            ),
        )
    return DimensionValidationResult(
        certified=matches,
        matches=matches,
        expected_width=execution_profile.expected_field_width,
        expected_height=execution_profile.expected_field_height,
        observed_width=profile.width,
        observed_height=profile.height,
        errors=errors,
        warnings=(),
        source_reference=profile.relative_path,
        checksum=profile.checksum,
    )


def _inspect_with_values(
    asset_root: str | Path,
    layer: PromptLayer,
    *,
    execution_profile: PredictionMixingExecutionProfile,
    limits: InspectionLimits,
) -> tuple[FieldInspectionResult, DecodedField | None]:
    if not isinstance(layer, PromptLayer):
        raise TypeError("layer must be a PromptLayer")
    if not isinstance(execution_profile, PredictionMixingExecutionProfile):
        raise TypeError("execution_profile must be a PredictionMixingExecutionProfile")
    if not isinstance(limits, InspectionLimits):
        raise TypeError("limits must be InspectionLimits")

    reference = layer.influence_field
    source = (
        reference.relative_path
        if isinstance(reference, InfluenceFieldAssetReference)
        and isinstance(reference.relative_path, str)
        else ""
    )
    if layer.visible is not True:
        return _failed(
            source,
            "asset.layer_inactive",
            "Only Active Prompt Layers may be inspected for execution.",
            layer.layer_id,
        ), None
    if not isinstance(reference, InfluenceFieldAssetReference):
        return _failed(
            source,
            "asset.reference_missing",
            "Active Prompt Layer has no Influence Field reference.",
            layer.layer_id,
        ), None

    try:
        resolved = resolve_field_asset(asset_root, reference.relative_path)
        decoded = inspect_png_bytes(
            resolved.path,
            layer_id=layer.layer_id,
            relative_reference=resolved.relative_reference,
            limits=limits,
        )
    except AssetInspectionError as error:
        return _failed(source, error.code, error.message, layer.layer_id), None

    profile = decoded.profile
    dimensions = validate_field_dimensions(profile, execution_profile)
    errors = list(dimensions.errors)
    warnings: list[ValidationFinding] = []
    if reference.checksum is not None:
        if (
            not isinstance(reference.checksum, str)
            or _SHA256_PATTERN.fullmatch(reference.checksum) is None
        ):
            errors.append(
                _finding(
                    "asset.checksum_invalid",
                    FindingSeverity.ERROR,
                    "Document asset checksum is not a valid SHA-256 digest.",
                    layer_id=layer.layer_id,
                    field_path="influence_field.checksum",
                )
            )
        elif reference.checksum.lower() != profile.checksum:
            errors.append(
                _finding(
                    "asset.checksum_mismatch",
                    FindingSeverity.ERROR,
                    "Inspected file checksum does not match the document reference.",
                    layer_id=layer.layer_id,
                    field_path="influence_field.checksum",
                )
            )
    if profile.distinct_value_count == 1:
        warnings.append(
            _finding(
                "asset.constant_field",
                FindingSeverity.WARNING,
                "Field is binary but constant and has no spatial variation.",
                layer_id=layer.layer_id,
                field_path="influence_field",
            )
        )
    information = (
        _finding(
            "asset.inspected",
            FindingSeverity.INFORMATION,
            "Influence Field PNG was inspected read-only.",
            layer_id=layer.layer_id,
            field_path="influence_field",
        ),
    )
    result = FieldInspectionResult(
        successful=True,
        certified=not errors,
        profile=profile,
        dimension_validation=dimensions,
        errors=tuple(errors),
        warnings=tuple(warnings),
        information=information,
        source_reference=profile.relative_path,
        checksum=profile.checksum,
    )
    return result, decoded


def _failed(
    source: str,
    code: str,
    message: str,
    layer_id: str,
) -> FieldInspectionResult:
    finding = _finding(
        code,
        FindingSeverity.ERROR,
        message,
        layer_id=layer_id,
        field_path="influence_field",
    )
    return FieldInspectionResult(
        successful=False,
        certified=False,
        profile=None,
        dimension_validation=None,
        errors=(finding,),
        warnings=(),
        information=(),
        source_reference=source,
        checksum=None,
    )


def _assess_overlap(first: DecodedField, second: DecodedField) -> OverlapInspectionResult:
    values_a = first.values
    values_b = second.values
    total = len(values_a)
    overlap_count = 0
    minimum_sum = 510
    maximum_sum = 0
    exact_complements = True
    has_unassigned = False
    exceeds_one = False
    for value_a, value_b in zip(values_a, values_b, strict=True):
        pair_sum = value_a + value_b
        overlap_count += int(value_a > 0 and value_b > 0)
        minimum_sum = min(minimum_sum, pair_sum)
        maximum_sum = max(maximum_sum, pair_sum)
        exact_complements = exact_complements and pair_sum == 255
        has_unassigned = has_unassigned or (value_a == 0 and value_b == 0)
        exceeds_one = exceeds_one or pair_sum > 255

    assessment = (
        CertifiedOverlap.OVERLAP_PRESENT
        if overlap_count
        else CertifiedOverlap.NO_OVERLAP
    )
    digest_payload = (
        f"{first.profile.checksum}\n{second.profile.checksum}\n"
        f"{first.profile.width}x{first.profile.height}\n"
        "conditioning-layers.overlap.v1"
    )
    digest = hashlib.sha256(digest_payload.encode("ascii")).hexdigest()
    evidence = OverlapEvidence(
        assessment=assessment,
        total_pixel_count=total,
        overlap_pixel_count=overlap_count,
        overlap_fraction=overlap_count / total,
        minimum_pairwise_sum=minimum_sum / 255,
        maximum_pairwise_sum=maximum_sum / 255,
        exact_complements=exact_complements,
        has_unassigned_pixels=has_unassigned,
        sums_exceed_one=exceeds_one,
        input_digest=digest,
    )
    warnings: list[ValidationFinding] = []
    information: list[ValidationFinding] = []
    if overlap_count:
        warnings.append(
            _finding(
                "overlap.present",
                FindingSeverity.WARNING,
                "Both fields are nonzero at one or more pixels.",
            )
        )
    else:
        information.append(
            _finding(
                "overlap.none",
                FindingSeverity.INFORMATION,
                "No pixel is nonzero in both fields.",
            )
        )
    if has_unassigned:
        warnings.append(
            _finding(
                "overlap.unassigned",
                FindingSeverity.WARNING,
                "At least one pixel is zero in both fields.",
            )
        )
    if exceeds_one:
        warnings.append(
            _finding(
                "overlap.sum_exceeds_one",
                FindingSeverity.WARNING,
                "At least one normalized pairwise sum exceeds one.",
            )
        )
    if exact_complements:
        information.append(
            _finding(
                "overlap.exact_complements",
                FindingSeverity.INFORMATION,
                "Every pair of stored 8-bit values sums exactly to 255.",
            )
        )
    return OverlapInspectionResult(
        certified=True,
        evidence=evidence,
        errors=(),
        warnings=tuple(warnings),
        information=tuple(information),
        source_references=(
            first.profile.relative_path,
            second.profile.relative_path,
        ),
        checksums=(first.profile.checksum, second.profile.checksum),
        input_digest=digest,
    )


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
