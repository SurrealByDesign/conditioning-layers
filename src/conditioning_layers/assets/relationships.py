"""Ordered N-way Influence Field relationship inspection and certification."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import fields, is_dataclass, replace
from enum import Enum
import hashlib
import json
from pathlib import Path

from conditioning_layers.adapters.prediction_mixing import (
    PREDICTION_MIXING_EXECUTION_PROFILE,
    PredictionMixingExecutionProfile,
)
from conditioning_layers.domain import (
    FindingSeverity,
    InfluenceFieldAssetReference,
    PromptLayer,
    ValidationFinding,
)
from conditioning_layers.persistence import AssetPathError, normalize_asset_reference

from .models import (
    DEFAULT_FIELD_RELATIONSHIP_POLICY,
    DEFAULT_INSPECTION_LIMITS,
    FIELD_RELATIONSHIP_CERTIFICATE_FORMAT,
    FIELD_RELATIONSHIP_CERTIFICATE_VERSION,
    FieldInspectionResult,
    FieldRelationshipCertificate,
    FieldRelationshipCertificationStatus,
    FieldRelationshipInput,
    FieldRelationshipInspectionResult,
    FieldRelationshipPolicy,
    InspectionLimits,
    OrderedFieldRecord,
    PairwiseRelationshipEvidence,
    PartitionClassification,
    SharedRasterEvidence,
    WholeSetRelationshipEvidence,
)
from .overlap import _inspect_with_values
from .png_inspector import DecodedField


_CHANNEL_INTERPRETATION = (
    "one normalized 8-bit influence sample per pixel; identical RGB channels "
    "are collapsed without conversion"
)
_NORMALIZATION_RULE = "stored 8-bit sample / 255"


def inspect_field_relationships(
    asset_root: str | Path,
    ordered_inputs: Sequence[FieldRelationshipInput],
    *,
    execution_profile: PredictionMixingExecutionProfile = (
        PREDICTION_MIXING_EXECUTION_PROFILE
    ),
    limits: InspectionLimits = DEFAULT_INSPECTION_LIMITS,
    policy: FieldRelationshipPolicy = DEFAULT_FIELD_RELATIONSHIP_POLICY,
) -> FieldRelationshipInspectionResult:
    """Inspect an ordered field set without granting translation or execution.

    The returned certificate retains caller order exactly. Relationship evidence
    is computed from ephemeral decoded samples, which are discarded before the
    result is returned.
    """

    if isinstance(ordered_inputs, (str, bytes)) or not isinstance(
        ordered_inputs, Sequence
    ):
        raw_inputs: tuple[object, ...] = ()
        input_collection_error = _finding(
            "field_relationship.inputs.invalid",
            FindingSeverity.ERROR,
            "Ordered field inputs must be a finite sequence.",
        )
    else:
        raw_inputs = tuple(ordered_inputs)
        input_collection_error = None
    if not isinstance(execution_profile, PredictionMixingExecutionProfile):
        raise TypeError("execution_profile must be a PredictionMixingExecutionProfile")
    if not isinstance(limits, InspectionLimits):
        raise TypeError("limits must be InspectionLimits")
    _validate_policy(policy)

    errors: list[ValidationFinding] = []
    warnings: list[ValidationFinding] = []
    information: list[ValidationFinding] = []
    if input_collection_error is not None:
        errors.append(input_collection_error)
    if not raw_inputs:
        errors.append(
            _finding(
                "field_relationship.inputs.empty",
                FindingSeverity.ERROR,
                "At least one ordered Influence Field is required.",
            )
        )

    layer_ids = tuple(
        item.layer.layer_id
        if isinstance(item, FieldRelationshipInput)
        and isinstance(item.layer, PromptLayer)
        and isinstance(item.layer.layer_id, str)
        else None
        for item in raw_inputs
    )
    document_indexes = tuple(
        item.document_index if isinstance(item, FieldRelationshipInput) else None
        for item in raw_inputs
    )
    duplicate_layer_ids = {
        item for item in layer_ids if item is not None and layer_ids.count(item) > 1
    }
    supplied_indexes = tuple(item for item in document_indexes if item is not None)
    duplicate_document_indexes = {
        item for item in supplied_indexes if supplied_indexes.count(item) > 1
    }

    field_results: list[FieldInspectionResult] = []
    decoded_fields: list[DecodedField | None] = []
    ordered_records: list[OrderedFieldRecord] = []
    per_field_input_errors: list[tuple[ValidationFinding, ...]] = []

    for ordinal, raw_input in enumerate(raw_inputs):
        input_errors: list[ValidationFinding] = []
        if not isinstance(raw_input, FieldRelationshipInput) or not isinstance(
            raw_input.layer, PromptLayer
        ):
            finding = _finding(
                "field_relationship.input.invalid",
                FindingSeverity.ERROR,
                "Every ordered field input must bind one Prompt Layer.",
                field_path=f"ordered_inputs[{ordinal}]",
            )
            input_errors.append(finding)
            result = _invalid_field_result(finding)
            decoded = None
            layer = None
            document_index = None
        else:
            layer = raw_input.layer
            document_index = raw_input.document_index
            if not isinstance(layer.layer_id, str) or not layer.layer_id.strip():
                input_errors.append(
                    _finding(
                        "field_relationship.layer_id.invalid",
                        FindingSeverity.ERROR,
                        "Each inspected field requires a non-empty layer ID.",
                        field_path=f"ordered_inputs[{ordinal}].layer.layer_id",
                    )
                )
            elif layer.layer_id in duplicate_layer_ids:
                input_errors.append(
                    _finding(
                        "field_relationship.layer_id.duplicate",
                        FindingSeverity.ERROR,
                        "Layer IDs must be unique within an ordered field certificate.",
                        layer_id=layer.layer_id,
                    )
                )
            if document_index is not None and (
                isinstance(document_index, bool)
                or not isinstance(document_index, int)
                or document_index < 0
            ):
                input_errors.append(
                    _finding(
                        "field_relationship.document_index.invalid",
                        FindingSeverity.ERROR,
                        "Document index must be a non-negative integer when supplied.",
                        layer_id=layer.layer_id,
                    )
                )
            elif document_index in duplicate_document_indexes:
                input_errors.append(
                    _finding(
                        "field_relationship.document_index.duplicate",
                        FindingSeverity.ERROR,
                        "Supplied document indexes must be unique.",
                        layer_id=layer.layer_id,
                    )
                )
            result, decoded = _inspect_with_values(
                asset_root,
                layer,
                execution_profile=execution_profile,
                limits=limits,
            )

        field_results.append(result)
        decoded_fields.append(decoded)
        per_field_input_errors.append(tuple(input_errors))
        errors.extend(input_errors)
        errors.extend(result.errors)
        warnings.extend(result.warnings)
        information.extend(result.information)
        ordered_records.append(
            _ordered_record(
                ordinal,
                layer,
                document_index,
                result,
                tuple(input_errors),
            )
        )

    shared_raster, shared_errors = _shared_raster(
        tuple(field_results),
        tuple(decoded_fields),
        tuple(per_field_input_errors),
        policy,
    )
    errors.extend(shared_errors)

    pairwise: list[PairwiseRelationshipEvidence] = []
    for first_ordinal in range(len(decoded_fields)):
        for second_ordinal in range(first_ordinal + 1, len(decoded_fields)):
            evidence, pair_findings = _pairwise_evidence(
                first_ordinal,
                second_ordinal,
                ordered_records,
                field_results,
                decoded_fields,
                per_field_input_errors,
                policy,
            )
            pairwise.append(evidence)
            for finding in pair_findings:
                if finding.severity is FindingSeverity.ERROR:
                    errors.append(finding)
                elif finding.severity is FindingSeverity.WARNING:
                    warnings.append(finding)
                else:
                    information.append(finding)

    whole_set, classification, whole_findings = _whole_set_evidence(
        tuple(ordered_records),
        tuple(decoded_fields),
        shared_raster,
        policy,
    )
    for finding in whole_findings:
        if finding.severity is FindingSeverity.ERROR:
            errors.append(finding)
        elif finding.severity is FindingSeverity.WARNING:
            warnings.append(finding)
        else:
            information.append(finding)

    errors_tuple = _deduplicate_findings(errors)
    warnings_tuple = _deduplicate_findings(warnings)
    information_tuple = _deduplicate_findings(information)
    status = (
        FieldRelationshipCertificationStatus.CERTIFIED
        if not errors_tuple and whole_set.certified
        else FieldRelationshipCertificationStatus.UNCERTIFIED
    )
    finding_codes = _unique_codes(
        errors_tuple + warnings_tuple + information_tuple
    )
    certificate = FieldRelationshipCertificate(
        format_identifier=FIELD_RELATIONSHIP_CERTIFICATE_FORMAT,
        format_version=FIELD_RELATIONSHIP_CERTIFICATE_VERSION,
        relationship_policy_identifier=policy.identifier,
        relationship_policy_version=policy.version,
        fingerprint="",
        status=status,
        finding_codes=finding_codes,
        ordered_fields=tuple(ordered_records),
        shared_raster=shared_raster,
        pairwise_evidence=tuple(pairwise),
        whole_set_evidence=whole_set,
        partition_classification=classification,
        polarity=policy.polarity,
        orientation=policy.orientation,
    )
    certificate = replace(
        certificate,
        fingerprint=fingerprint_field_relationship_certificate(certificate),
    )
    return FieldRelationshipInspectionResult(
        certificate=certificate,
        fields=tuple(field_results),
        errors=errors_tuple,
        warnings=warnings_tuple,
        information=information_tuple,
    )


def serialize_field_relationship_certificate(
    certificate: FieldRelationshipCertificate,
) -> str:
    """Return canonical portable JSON with exactly one trailing newline."""

    if not isinstance(certificate, FieldRelationshipCertificate):
        raise TypeError("certificate must be a FieldRelationshipCertificate")
    return json.dumps(
        _portable(certificate),
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def fingerprint_field_relationship_certificate(
    certificate: FieldRelationshipCertificate,
) -> str:
    """Fingerprint all semantic certificate material except the fingerprint itself."""

    if not isinstance(certificate, FieldRelationshipCertificate):
        raise TypeError("certificate must be a FieldRelationshipCertificate")
    return _sha256_json(_certificate_material(certificate))


def _ordered_record(
    ordinal: int,
    layer: PromptLayer | None,
    document_index: object,
    result: FieldInspectionResult,
    input_errors: tuple[ValidationFinding, ...],
) -> OrderedFieldRecord:
    profile = result.profile
    reference = ""
    if layer is not None and isinstance(
        layer.influence_field, InfluenceFieldAssetReference
    ):
        reference = _portable_reference(layer.influence_field.relative_path)
    if profile is not None:
        reference = profile.relative_path
    finding_codes = _unique_codes(
        input_errors + result.errors + result.warnings + result.information
    )
    return OrderedFieldRecord(
        ordinal=ordinal,
        layer_id=(layer.layer_id if layer is not None and isinstance(layer.layer_id, str) else None),
        document_index=(
            document_index
            if isinstance(document_index, int)
            and not isinstance(document_index, bool)
            and document_index >= 0
            else None
        ),
        portable_reference=reference,
        source_sha256=profile.checksum if profile is not None else None,
        width=profile.width if profile is not None else None,
        height=profile.height if profile is not None else None,
        bit_depth=8 if profile is not None else None,
        channel_profile=profile.channel_profile if profile is not None else None,
        value_kind=profile.value_kind if profile is not None else None,
        minimum_normalized_value=(
            profile.minimum_normalized_value if profile is not None else None
        ),
        maximum_normalized_value=(
            profile.maximum_normalized_value if profile is not None else None
        ),
        inspection_certified=result.certified and not input_errors,
        finding_codes=finding_codes,
    )


def _shared_raster(
    field_results: tuple[FieldInspectionResult, ...],
    decoded_fields: tuple[DecodedField | None, ...],
    per_field_errors: tuple[tuple[ValidationFinding, ...], ...],
    policy: FieldRelationshipPolicy,
) -> tuple[SharedRasterEvidence, tuple[ValidationFinding, ...]]:
    decoded = tuple(item for item in decoded_fields if item is not None)
    width = decoded[0].profile.width if decoded else None
    height = decoded[0].profile.height if decoded else None
    dimensions_match = bool(decoded) and all(
        item.profile.width == width and item.profile.height == height for item in decoded
    )
    all_fields_satisfy = (
        bool(field_results)
        and len(decoded) == len(field_results)
        and dimensions_match
        and all(item.certified for item in field_results)
        and not any(per_field_errors)
    )
    findings: tuple[ValidationFinding, ...] = ()
    if decoded and not dimensions_match:
        findings = (
            _finding(
                "field_relationship.shared_dimensions",
                FindingSeverity.ERROR,
                "All fields must have identical dimensions for whole-set certification.",
            ),
        )
    return SharedRasterEvidence(
        width=width if dimensions_match else None,
        height=height if dimensions_match else None,
        pixel_count=(width * height if dimensions_match and width and height else None),
        bit_depth=8 if decoded and dimensions_match else None,
        channel_interpretation=_CHANNEL_INTERPRETATION,
        normalization_rule=_NORMALIZATION_RULE,
        positive_sample_threshold_normalized=(
            policy.positive_sample_threshold / 255
        ),
        all_fields_satisfy=all_fields_satisfy,
    ), findings


def _pairwise_evidence(
    first_ordinal: int,
    second_ordinal: int,
    records: list[OrderedFieldRecord],
    field_results: list[FieldInspectionResult],
    decoded_fields: list[DecodedField | None],
    per_field_errors: list[tuple[ValidationFinding, ...]],
    policy: FieldRelationshipPolicy,
) -> tuple[PairwiseRelationshipEvidence, tuple[ValidationFinding, ...]]:
    first = decoded_fields[first_ordinal]
    second = decoded_fields[second_ordinal]
    finding_codes: tuple[str, ...] = ()
    findings: tuple[ValidationFinding, ...] = ()
    overlap_count: int | None = None
    overlap_fraction: float | None = None
    minimum_sum: float | None = None
    maximum_sum: float | None = None
    exact_complements: bool | None = None
    dimensions_match = (
        first is not None
        and second is not None
        and first.profile.width == second.profile.width
        and first.profile.height == second.profile.height
    )
    if dimensions_match:
        overlap_count = 0
        minimum_pair_sum = 510
        maximum_pair_sum = 0
        all_exact_complements = True
        for first_value, second_value in zip(
            first.values, second.values, strict=True  # type: ignore[union-attr]
        ):
            pair_sum = first_value + second_value
            overlap_count += int(
                first_value > policy.positive_sample_threshold
                and second_value > policy.positive_sample_threshold
            )
            minimum_pair_sum = min(minimum_pair_sum, pair_sum)
            maximum_pair_sum = max(maximum_pair_sum, pair_sum)
            all_exact_complements = (
                all_exact_complements
                and pair_sum == policy.partition_sum_sample
            )
        total = len(first.values)  # type: ignore[union-attr]
        overlap_fraction = overlap_count / total
        minimum_sum = minimum_pair_sum / 255
        maximum_sum = maximum_pair_sum / 255
        exact_complements = all_exact_complements
        if (
            not field_results[first_ordinal].certified
            or not field_results[second_ordinal].certified
            or per_field_errors[first_ordinal]
            or per_field_errors[second_ordinal]
        ):
            finding_codes = ("field_relationship.pair_uncertified",)
    elif first is not None and second is not None:
        finding = _finding(
            "field_relationship.pair_dimensions",
            FindingSeverity.ERROR,
            "Pairwise evidence requires identical field dimensions.",
        )
        findings = (finding,)
        finding_codes = (finding.code,)
    else:
        finding_codes = ("field_relationship.pair_uncertified",)

    material = {
        "certified": dimensions_match and not finding_codes,
        "exact_complements": exact_complements,
        "finding_codes": finding_codes,
        "first_layer_id": records[first_ordinal].layer_id,
        "first_ordinal": first_ordinal,
        "first_sha256": records[first_ordinal].source_sha256,
        "maximum_normalized_pairwise_sum": maximum_sum,
        "minimum_normalized_pairwise_sum": minimum_sum,
        "overlap_fraction": overlap_fraction,
        "policy_identifier": policy.identifier,
        "policy_version": policy.version,
        "second_layer_id": records[second_ordinal].layer_id,
        "second_ordinal": second_ordinal,
        "second_sha256": records[second_ordinal].source_sha256,
        "simultaneous_positive_pixel_count": overlap_count,
    }
    evidence = PairwiseRelationshipEvidence(
        first_ordinal=first_ordinal,
        second_ordinal=second_ordinal,
        first_layer_id=records[first_ordinal].layer_id,
        second_layer_id=records[second_ordinal].layer_id,
        certified=dimensions_match and not finding_codes,
        simultaneous_positive_pixel_count=overlap_count,
        overlap_fraction=overlap_fraction,
        minimum_normalized_pairwise_sum=minimum_sum,
        maximum_normalized_pairwise_sum=maximum_sum,
        exact_complements=exact_complements,
        finding_codes=finding_codes,
        digest=_sha256_json(material),
    )
    return evidence, findings


def _whole_set_evidence(
    records: tuple[OrderedFieldRecord, ...],
    decoded_fields: tuple[DecodedField | None, ...],
    shared_raster: SharedRasterEvidence,
    policy: FieldRelationshipPolicy,
) -> tuple[
    WholeSetRelationshipEvidence,
    PartitionClassification,
    tuple[ValidationFinding, ...],
]:
    duplicate_hashes = _duplicate_groups(
        tuple(record.source_sha256 for record in records)
    )
    duplicate_references = _duplicate_groups(
        tuple(record.portable_reference or None for record in records)
    )
    findings: list[ValidationFinding] = []
    if duplicate_hashes:
        findings.append(
            _finding(
                "field_relationship.duplicate_hash",
                FindingSeverity.WARNING,
                "Two or more ordered fields have identical source bytes.",
            )
        )
    if duplicate_references:
        findings.append(
            _finding(
                "field_relationship.duplicate_reference",
                FindingSeverity.WARNING,
                "Two or more ordered fields use the same portable reference.",
            )
        )

    if (
        any(item is None for item in decoded_fields)
        or shared_raster.width is None
        or shared_raster.height is None
    ):
        return WholeSetRelationshipEvidence(
            certified=False,
            complete_coverage=None,
            gap_pixel_count=None,
            gap_fraction=None,
            maximum_simultaneous_active_field_count=None,
            simultaneous_active_count_histogram=(),
            normalized_sum_policy_threshold=(
                policy.normalized_sum_threshold_sample / 255
            ),
            sum_exceeds_policy_pixel_count=None,
            minimum_normalized_total_sum=None,
            maximum_normalized_total_sum=None,
            partition_sum_normalized_value=policy.partition_sum_sample / 255,
            partition_sum_pixel_count=None,
            duplicate_hash_ordinal_groups=duplicate_hashes,
            duplicate_reference_ordinal_groups=duplicate_references,
            mutual_exclusion=None,
        ), PartitionClassification.UNABLE_TO_CERTIFY, tuple(findings)

    decoded = tuple(item for item in decoded_fields if item is not None)
    field_count = len(decoded)
    pixel_count = len(decoded[0].values)
    histogram = [0] * (field_count + 1)
    gap_count = 0
    maximum_active = 0
    exceeds_count = 0
    minimum_total = 255 * field_count
    maximum_total = 0
    partition_count = 0
    for pixel_index in range(pixel_count):
        values = tuple(item.values[pixel_index] for item in decoded)
        active_count = sum(
            value > policy.positive_sample_threshold for value in values
        )
        total = sum(values)
        histogram[active_count] += 1
        gap_count += int(active_count == 0)
        maximum_active = max(maximum_active, active_count)
        exceeds_count += int(total > policy.normalized_sum_threshold_sample)
        minimum_total = min(minimum_total, total)
        maximum_total = max(maximum_total, total)
        partition_count += int(total == policy.partition_sum_sample)

    complete_coverage = gap_count == 0
    mutual_exclusion = maximum_active <= 1
    measured_classification: PartitionClassification
    if mutual_exclusion and complete_coverage and partition_count == pixel_count:
        measured_classification = PartitionClassification.EXACT_DISJOINT_COMPLETE_PARTITION
        findings.append(
            _finding(
                "field_relationship.partition.exact",
                FindingSeverity.INFORMATION,
                "Fields form an exact disjoint complete partition.",
            )
        )
    elif mutual_exclusion and not complete_coverage:
        measured_classification = PartitionClassification.DISJOINT_WITH_GAPS
        findings.append(
            _finding(
                "field_relationship.gaps_present",
                FindingSeverity.WARNING,
                "Mutually exclusive fields leave one or more pixels unassigned.",
            )
        )
    elif not mutual_exclusion:
        measured_classification = PartitionClassification.OVERLAPPING
        findings.append(
            _finding(
                "field_relationship.overlap_present",
                FindingSeverity.WARNING,
                "Two or more fields are simultaneously positive at one or more pixels.",
            )
        )
    else:
        measured_classification = PartitionClassification.MIXED_NON_PARTITION
        findings.append(
            _finding(
                "field_relationship.partition.mixed",
                FindingSeverity.WARNING,
                "Field coverage is complete but does not form the declared exact partition.",
            )
        )
    classification = (
        measured_classification
        if shared_raster.all_fields_satisfy
        else PartitionClassification.UNABLE_TO_CERTIFY
    )
    return WholeSetRelationshipEvidence(
        certified=shared_raster.all_fields_satisfy,
        complete_coverage=complete_coverage,
        gap_pixel_count=gap_count,
        gap_fraction=gap_count / pixel_count,
        maximum_simultaneous_active_field_count=maximum_active,
        simultaneous_active_count_histogram=tuple(histogram),
        normalized_sum_policy_threshold=(
            policy.normalized_sum_threshold_sample / 255
        ),
        sum_exceeds_policy_pixel_count=exceeds_count,
        minimum_normalized_total_sum=minimum_total / 255,
        maximum_normalized_total_sum=maximum_total / 255,
        partition_sum_normalized_value=policy.partition_sum_sample / 255,
        partition_sum_pixel_count=partition_count,
        duplicate_hash_ordinal_groups=duplicate_hashes,
        duplicate_reference_ordinal_groups=duplicate_references,
        mutual_exclusion=mutual_exclusion,
    ), classification, tuple(findings)


def _certificate_material(certificate: FieldRelationshipCertificate) -> dict[str, object]:
    material = _portable(certificate)
    assert isinstance(material, dict)
    material.pop("fingerprint")
    return material


def _portable(value: object) -> object:
    if is_dataclass(value):
        return {item.name: _portable(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple | list):
        return [_portable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _portable(item) for key, item in value.items()}
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise TypeError(f"unsupported certificate value: {type(value)!r}")


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        _portable(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _portable_reference(value: object) -> str:
    if not isinstance(value, str):
        return ""
    try:
        return normalize_asset_reference(value)
    except AssetPathError:
        return ""


def _duplicate_groups(values: tuple[str | None, ...]) -> tuple[tuple[int, ...], ...]:
    groups: dict[str, list[int]] = {}
    for ordinal, value in enumerate(values):
        if value is not None:
            groups.setdefault(value, []).append(ordinal)
    return tuple(
        tuple(ordinals)
        for _, ordinals in sorted(groups.items(), key=lambda item: item[1][0])
        if len(ordinals) > 1
    )


def _invalid_field_result(finding: ValidationFinding) -> FieldInspectionResult:
    return FieldInspectionResult(
        successful=False,
        certified=False,
        profile=None,
        dimension_validation=None,
        errors=(finding,),
        warnings=(),
        information=(),
        source_reference="",
        checksum=None,
    )


def _validate_policy(policy: FieldRelationshipPolicy) -> None:
    if not isinstance(policy, FieldRelationshipPolicy):
        raise TypeError("policy must be a FieldRelationshipPolicy")
    if not isinstance(policy.identifier, str) or not policy.identifier.strip():
        raise ValueError("policy identifier must be non-empty")
    if isinstance(policy.version, bool) or not isinstance(policy.version, int) or policy.version < 1:
        raise ValueError("policy version must be a positive integer")
    for name in (
        "positive_sample_threshold",
        "normalized_sum_threshold_sample",
        "partition_sum_sample",
    ):
        value = getattr(policy, name)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
            raise ValueError(f"{name} must be an 8-bit sample")


def _deduplicate_findings(
    findings: list[ValidationFinding],
) -> tuple[ValidationFinding, ...]:
    retained: list[ValidationFinding] = []
    seen: set[tuple[object, ...]] = set()
    for finding in findings:
        key = (
            finding.code,
            finding.severity,
            finding.layer_id,
            finding.field_path,
        )
        if key not in seen:
            retained.append(finding)
            seen.add(key)
    return tuple(retained)


def _unique_codes(findings: tuple[ValidationFinding, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(finding.code for finding in findings))


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
