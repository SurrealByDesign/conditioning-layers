"""Evidence-bound, all-or-nothing Translation Plan v3; no asset or host I/O."""

from __future__ import annotations

from dataclasses import fields, replace
import hashlib
import json
import math
import re

from conditioning_layers.adapters.prediction_mixing import FieldAssetProfile, combine_prompt_text
from conditioning_layers.adapters.prediction_mixing.validation import _validate_field_profile
from conditioning_layers.adapters.prediction_mixing.v2.canonical import canonical_json_bytes
from conditioning_layers.adapters.prediction_mixing.v2.identity import (
    exact_contract_equal, fingerprint_document_execution_projection, fingerprint_without_field,
)
from conditioning_layers.adapters.prediction_mixing.v2.models import DocumentExecutionProjection, TranslationStatus
from conditioning_layers.adapters.prediction_mixing.v2.projections import build_document_execution_projection
from conditioning_layers.adapters.prediction_mixing.v2.topology import (
    ORDERED_LEFT_FOLD_TOPOLOGY_POLICY, build_ordered_left_fold_schedule,
)
from conditioning_layers.assets import (
    DEFAULT_FIELD_RELATIONSHIP_POLICY, FIELD_RELATIONSHIP_CERTIFICATE_FORMAT,
    FIELD_RELATIONSHIP_CERTIFICATE_VERSION, FieldRelationshipCertificate,
    FieldRelationshipCertificationStatus, InspectedChannelProfile, InspectedValueKind,
    PartitionClassification, SharedRasterEvidence, fingerprint_field_relationship_certificate,
)
from conditioning_layers.capabilities.multi_layer import (
    EXACT_THREE_ELIGIBILITY, MULTI_LAYER_CONTRACT_IDENTIFIER, MULTI_LAYER_CONTRACT_VERSION,
    MultiLayerEligibilityEntry, evaluate_multi_layer_eligibility, multi_layer_warnings, verify_eligibility_entry,
)
from conditioning_layers.domain import (
    ConditioningDocument, CURRENT_PROTOTYPE_VERSION, FindingSeverity,
    InfluenceFieldAssetReference, PromptLayer, ValidationFinding,
)

from .models import (
    MULTI_LAYER_EXECUTION_PROFILE, TRANSLATION_PLAN_V3_IDENTIFIER, TRANSLATION_PLAN_V3_VERSION,
    MultiLayerExecutionProfile, RegionalConditionPlanV3, TranslationPlanV3, TranslationResultV3,
)


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def fingerprint_execution_profile(profile: MultiLayerExecutionProfile) -> str:
    if not isinstance(profile, MultiLayerExecutionProfile):
        raise TypeError("profile must be a MultiLayerExecutionProfile")
    return fingerprint_without_field(profile)


def fingerprint_translation_plan_v3(plan: TranslationPlanV3) -> str:
    if not isinstance(plan, TranslationPlanV3):
        raise TypeError("plan must be a TranslationPlanV3")
    return fingerprint_without_field(plan)


def serialize_translation_plan_v3(plan: TranslationPlanV3) -> bytes:
    if not isinstance(plan, TranslationPlanV3):
        raise TypeError("plan must be a TranslationPlanV3")
    return canonical_json_bytes(plan)


def translate_prediction_mixing_multi_layer(
    document: ConditioningDocument,
    certificate: FieldRelationshipCertificate,
    field_profiles: tuple[FieldAssetProfile, ...],
    *, eligibility_entry: MultiLayerEligibilityEntry = EXACT_THREE_ELIGIBILITY,
    execution_profile: MultiLayerExecutionProfile = MULTI_LAYER_EXECUTION_PROFILE,
    contract_identifier: str = MULTI_LAYER_CONTRACT_IDENTIFIER,
    topology_policy=ORDERED_LEFT_FOLD_TOPOLOGY_POLICY,
) -> TranslationResultV3:
    """Consume inspected document-owned fields; admission belongs to the router.

    Invalid evidence takes precedence over well-formed unsupported intent. The
    function never reads bytes or retries another contract, and emits no partial plan.
    """
    invalid: list[ValidationFinding] = []
    rejected: list[ValidationFinding] = []
    try:
        projection = build_document_execution_projection(document)
    except (TypeError, ValueError, AttributeError, UnicodeError, OverflowError):
        projection = None
        invalid.append(_error("translation.document_invalid", "Document cannot supply a valid execution projection."))
    eligibility_findings = evaluate_multi_layer_eligibility(document, eligibility_entry)
    for item in eligibility_findings:
        (invalid if "identity_mismatch" in item.code or "invalid" in item.code else rejected).append(item)
    if contract_identifier != MULTI_LAYER_CONTRACT_IDENTIFIER:
        rejected.append(_error("translation.unsupported_contract", "Translation Plan v3 requires its selected multi-layer contract."))
    for item in _verify_profile(execution_profile):
        (rejected if item.code == "translation.unsupported_profile" else invalid).append(item)
    if not exact_contract_equal(topology_policy, ORDERED_LEFT_FOLD_TOPOLOGY_POLICY):
        invalid.append(_error("translation.topology_identity_mismatch", "Topology differs from the retained ordered-left-fold authority."))
    if projection is not None and isinstance(execution_profile, MultiLayerExecutionProfile):
        document_indexes = tuple(index for index, layer in enumerate(document.layers) if layer.visible is True)
        invalid.extend(_verify_certificate(projection, certificate, field_profiles, execution_profile, document_indexes))
    else:
        # A malformed document must not prevent independently checking certificate identity.
        if not isinstance(certificate, FieldRelationshipCertificate):
            invalid.append(_error("translation.certificate_invalid", "Field certificate is malformed."))
    if isinstance(certificate, FieldRelationshipCertificate) and not invalid:
        if certificate.whole_set_evidence.mutual_exclusion is not True:
            rejected.append(_error("translation.overlap_present", "Stored positive Influence Field samples overlap."))
    if invalid or rejected:
        return TranslationResultV3(TranslationStatus.INVALID if invalid else TranslationStatus.REJECTED,
                                   None, tuple(invalid + rejected))
    assert projection is not None
    conditions = _conditions(projection, certificate, field_profiles, execution_profile)
    plan = TranslationPlanV3(
        format_identifier=TRANSLATION_PLAN_V3_IDENTIFIER, format_version=TRANSLATION_PLAN_V3_VERSION,
        contract_identifier=contract_identifier, contract_version=MULTI_LAYER_CONTRACT_VERSION,
        document_projection=projection, eligibility_entry=eligibility_entry,
        execution_profile=execution_profile, certificate=certificate,
        regional_conditions=conditions, topology_policy=topology_policy,
        fold_schedule=build_ordered_left_fold_schedule(len(conditions)), fingerprint="",
    )
    plan = replace(plan, fingerprint=fingerprint_translation_plan_v3(plan))
    verified = verify_translation_plan(plan)
    if verified:
        return TranslationResultV3(TranslationStatus.INVALID, None, verified)
    findings = multi_layer_warnings(zero_strength_active=any(condition.requested_strength == 0.0 for condition in conditions))
    return TranslationResultV3(TranslationStatus.TRANSLATED, plan, findings)


def plan_warning_codes(plan: TranslationPlanV3) -> tuple[str, ...]:
    """Derive retained execution warnings without widening plan identity."""
    return tuple(item.code for item in multi_layer_warnings(
        zero_strength_active=any(item.requested_strength == 0.0 for item in plan.regional_conditions),
    ))


def verify_translation_plan(plan: object) -> tuple[ValidationFinding, ...]:
    """Consumer verification of exact selected authority and all owned relations."""
    if not isinstance(plan, TranslationPlanV3):
        return (_error("translation.plan_invalid", "A Translation Plan v3 is required."),)
    invalid: list[ValidationFinding] = []
    try:
        if (plan.format_identifier != TRANSLATION_PLAN_V3_IDENTIFIER
                or type(plan.format_version) is not int or plan.format_version != TRANSLATION_PLAN_V3_VERSION
                or plan.contract_identifier != MULTI_LAYER_CONTRACT_IDENTIFIER
                or type(plan.contract_version) is not int or plan.contract_version != MULTI_LAYER_CONTRACT_VERSION):
            invalid.append(_error("translation.plan_contract_mismatch", "Plan contract declarations disagree."))
        if fingerprint_translation_plan_v3(plan) != plan.fingerprint:
            invalid.append(_error("translation.plan_fingerprint_mismatch", "Plan fingerprint is stale or forged."))
        invalid.extend(verify_eligibility_entry(plan.eligibility_entry))
        invalid.extend(_verify_profile(plan.execution_profile))
        _validate_projection(plan.document_projection)
        count = len(plan.document_projection.active_layers)
        if count != plan.eligibility_entry.exact_cardinality or count != len(plan.regional_conditions):
            invalid.append(_error("translation.exact_cardinality_mismatch", "Plan count must equal the selected exact-cardinality entry."))
        profiles = tuple(item.field_profile for item in plan.regional_conditions)
        invalid.extend(_verify_certificate(plan.document_projection, plan.certificate, profiles, plan.execution_profile))
        expected = _conditions(plan.document_projection, plan.certificate, profiles, plan.execution_profile)
        if (not exact_contract_equal(plan.regional_conditions, expected)
                or any(item.requested_strength == 0.0 and math.copysign(1.0, item.requested_strength) < 0
                       for item in plan.regional_conditions)):
            invalid.append(_error("translation.conditions_mismatch", "Derived conditions disagree with their verified sources."))
        if not exact_contract_equal(plan.topology_policy, ORDERED_LEFT_FOLD_TOPOLOGY_POLICY):
            invalid.append(_error("translation.topology_identity_mismatch", "Topology authority was altered."))
        if not exact_contract_equal(plan.fold_schedule, build_ordered_left_fold_schedule(count)):
            invalid.append(_error("translation.fold_mismatch", "Ordered fold differs from the selected schedule."))
        if plan.certificate.whole_set_evidence.mutual_exclusion is not True:
            invalid.append(_error("translation.overlap_present", "Plan contains unsupported stored-positive overlap."))
    except (TypeError, ValueError, AttributeError, IndexError, KeyError, UnicodeError, OverflowError):
        invalid.append(_error("translation.plan_invalid", "Plan contains malformed or inconsistent evidence."))
    return tuple(invalid)


def _verify_profile(profile: object) -> tuple[ValidationFinding, ...]:
    try:
        if (isinstance(profile, MultiLayerExecutionProfile)
                and fingerprint_execution_profile(profile) == profile.fingerprint
                and profile.profile_identifier != MULTI_LAYER_EXECUTION_PROFILE.profile_identifier):
            return (_error("translation.unsupported_profile", "This execution profile is not registered for the multi-layer contract."),)
        valid = (isinstance(profile, MultiLayerExecutionProfile)
                 and fingerprint_execution_profile(profile) == profile.fingerprint
                 and exact_contract_equal(profile, MULTI_LAYER_EXECUTION_PROFILE))
    except (TypeError, ValueError, UnicodeError):
        valid = False
    return () if valid else (_error("translation.profile_identity_mismatch", "Execution profile differs from the immutable count-free v2 authority."),)


def _validate_projection(projection: DocumentExecutionProjection) -> None:
    _require(isinstance(projection, DocumentExecutionProjection), "document projection type")
    _require(fingerprint_document_execution_projection(projection) == projection.fingerprint, "document projection digest")
    document = ConditioningDocument(
        version=CURRENT_PROTOTYPE_VERSION, document_id="projection-verification",
        base_prompt=projection.base_prompt_text,
        selected_adapter_id=projection.selected_adapter_identifier,
        adapter_settings=json.loads(projection.canonical_adapter_settings_json),
        layers=tuple(PromptLayer(
            layer_id=item.layer_id, name="Projection layer", prompt_text=item.prompt_text,
            strength=item.requested_strength,
            influence_field=InfluenceFieldAssetReference(item.influence_field_reference, item.declared_field_sha256),
        ) for item in projection.active_layers),
    )
    _require(exact_contract_equal(build_document_execution_projection(document), projection), "document projection semantics")
    _require(document.selected_adapter_id == EXACT_THREE_ELIGIBILITY.adapter_identifier and not document.adapter_settings,
             "document adapter semantics")


def _verify_certificate(
    projection: DocumentExecutionProjection, certificate: object,
    profiles: tuple[FieldAssetProfile, ...], profile: MultiLayerExecutionProfile,
    document_indexes: tuple[int, ...] | None = None,
) -> tuple[ValidationFinding, ...]:
    try:
        _validate_certificate(projection, certificate, profiles, profile, document_indexes)
    except (TypeError, ValueError, AttributeError, IndexError, KeyError, UnicodeError, OverflowError) as exc:
        return (_error("translation.certificate_mismatch", f"Field certificate is malformed, stale, or inconsistent: {exc}."),)
    return ()


def _validate_certificate(projection, certificate, profiles, profile, document_indexes) -> None:
    _require(isinstance(certificate, FieldRelationshipCertificate), "certificate type")
    _require(fingerprint_field_relationship_certificate(certificate) == certificate.fingerprint, "certificate fingerprint")
    policy = DEFAULT_FIELD_RELATIONSHIP_POLICY
    _require(certificate.format_identifier == FIELD_RELATIONSHIP_CERTIFICATE_FORMAT
             and type(certificate.format_version) is int and certificate.format_version == FIELD_RELATIONSHIP_CERTIFICATE_VERSION,
             "certificate format")
    _require(certificate.relationship_policy_identifier == policy.identifier
             and type(certificate.relationship_policy_version) is int and certificate.relationship_policy_version == policy.version,
             "relationship policy")
    _require(certificate.status is FieldRelationshipCertificationStatus.CERTIFIED, "uncertified fields")
    _require(exact_contract_equal(certificate.polarity, policy.polarity)
             and exact_contract_equal(certificate.orientation, policy.orientation), "polarity/orientation")
    count = len(projection.active_layers)
    _require(type(profiles) is tuple and len(profiles) == count, "complete ordered field profiles")
    _require(type(certificate.ordered_fields) is tuple and len(certificate.ordered_fields) == count, "ordered field count")
    indexes = tuple(record.document_index for record in certificate.ordered_fields)
    _require(all(type(index) is int and index >= 0 for index in indexes)
             and all(left < right for left, right in zip(indexes, indexes[1:])), "document indexes/order")
    if document_indexes is not None:
        _require(indexes == document_indexes, "actual document indexes")
    for ordinal, (layer, record, field) in enumerate(zip(projection.active_layers, certificate.ordered_fields, profiles, strict=True)):
        _require(isinstance(field, FieldAssetProfile), "field profile type")
        _require(not _validate_field_profile(field, profile), "invalid field profile")
        _require(isinstance(field.checksum, str) and _SHA256.fullmatch(field.checksum) is not None, "field SHA-256")
        _require(type(record.ordinal) is int and record.ordinal == ordinal
                 and record.inspection_certified is True, "field ordinal/certification")
        _require(layer.active_ordinal == ordinal and record.layer_id == layer.layer_id == field.layer_id, "field layer identity")
        _require(record.portable_reference == layer.influence_field_reference == field.relative_path, "field reference")
        _require(record.source_sha256 == field.checksum
                 and (layer.declared_field_sha256 is None or layer.declared_field_sha256 == field.checksum), "field checksum")
        _require(type(record.width) is int and type(record.height) is int
                 and record.width == field.width and record.height == field.height
                 and type(record.bit_depth) is int and record.bit_depth == 8, "field raster")
        _require(isinstance(record.channel_profile, InspectedChannelProfile)
                 and record.channel_profile.value == field.channel_profile.value
                 and isinstance(record.value_kind, InspectedValueKind)
                 and record.value_kind.value == field.value_kind.value, "field encoding/classification")
        _require(_number(record.minimum_normalized_value) and _number(record.maximum_normalized_value)
                 and record.minimum_normalized_value == field.minimum_normalized_value
                 and record.maximum_normalized_value == field.maximum_normalized_value, "field measured range")
        _codes(record.finding_codes)
    width, height = profile.expected_field_width, profile.expected_field_height
    pixels = width * height
    expected_raster = SharedRasterEvidence(
        width=width, height=height, pixel_count=pixels, bit_depth=8,
        channel_interpretation="one normalized 8-bit influence sample per pixel; identical RGB channels are collapsed without conversion",
        normalization_rule="stored 8-bit sample / 255",
        positive_sample_threshold_normalized=0.0, all_fields_satisfy=True,
    )
    _require(exact_contract_equal(certificate.shared_raster, expected_raster), "shared raster and exact stored-positive threshold")
    pairs = tuple((first, second) for first in range(count) for second in range(first + 1, count))
    _require(type(certificate.pairwise_evidence) is tuple and len(certificate.pairwise_evidence) == len(pairs), "complete pair evidence")
    for pair, (first, second) in zip(certificate.pairwise_evidence, pairs, strict=True):
        first_record, second_record = certificate.ordered_fields[first], certificate.ordered_fields[second]
        _require(type(pair.first_ordinal) is int and type(pair.second_ordinal) is int
                 and (pair.first_ordinal, pair.second_ordinal) == (first, second), "pair order")
        _require(pair.first_layer_id == first_record.layer_id and pair.second_layer_id == second_record.layer_id,
                 "pair field identity")
        _require(pair.certified is True and pair.finding_codes == (), "pair certification")
        _count(pair.simultaneous_positive_pixel_count, pixels)
        _require(type(pair.overlap_fraction) is float
                 and pair.overlap_fraction == pair.simultaneous_positive_pixel_count / pixels, "pair overlap fraction")
        _range(pair.minimum_normalized_pairwise_sum, pair.maximum_normalized_pairwise_sum, 2)
        _require(type(pair.exact_complements) is bool
                 and pair.exact_complements == (pair.minimum_normalized_pairwise_sum == pair.maximum_normalized_pairwise_sum == 1.0),
                 "pair complement evidence")
        material = {item.name: getattr(pair, item.name) for item in fields(pair) if item.name != "digest"}
        material.update(first_sha256=first_record.source_sha256, second_sha256=second_record.source_sha256,
                        policy_identifier=policy.identifier, policy_version=policy.version)
        digest = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":"),
                                ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()
        _require(digest == pair.digest, "pair digest")
    whole = certificate.whole_set_evidence
    _require(whole.certified is True, "whole-set certification")
    histogram = whole.simultaneous_active_count_histogram
    _require(type(histogram) is tuple and len(histogram) == count + 1, "whole-set histogram")
    for value in histogram:
        _count(value, pixels)
    _require(sum(histogram) == pixels, "histogram pixel count")
    maximum_active = max(index for index, value in enumerate(histogram) if value)
    _require(type(whole.maximum_simultaneous_active_field_count) is int
             and whole.maximum_simultaneous_active_field_count == maximum_active, "maximum simultaneous count")
    _count(whole.gap_pixel_count, pixels)
    _require(whole.gap_pixel_count == histogram[0]
             and type(whole.gap_fraction) is float and whole.gap_fraction == histogram[0] / pixels, "gap evidence")
    _require(type(whole.complete_coverage) is bool and whole.complete_coverage == (histogram[0] == 0)
             and type(whole.mutual_exclusion) is bool and whole.mutual_exclusion == (maximum_active <= 1), "coverage/exclusion evidence")
    _require(sum(pair.simultaneous_positive_pixel_count for pair in certificate.pairwise_evidence)
             == sum(index * (index - 1) // 2 * value for index, value in enumerate(histogram)), "pair/whole-set overlap relation")
    _require(type(whole.normalized_sum_policy_threshold) is float and whole.normalized_sum_policy_threshold == 1.0
             and type(whole.partition_sum_normalized_value) is float and whole.partition_sum_normalized_value == 1.0, "sum measurement policy")
    _count(whole.sum_exceeds_policy_pixel_count, pixels)
    _count(whole.partition_sum_pixel_count, pixels)
    _range(whole.minimum_normalized_total_sum, whole.maximum_normalized_total_sum, count)
    _require((whole.minimum_normalized_total_sum == 0.0) == (whole.gap_pixel_count > 0), "gap/sum relation")
    _require(whole.partition_sum_pixel_count + whole.sum_exceeds_policy_pixel_count <= pixels - whole.gap_pixel_count, "sum count relation")
    if whole.mutual_exclusion:
        _require(whole.sum_exceeds_policy_pixel_count == 0
                 and whole.maximum_normalized_total_sum == max(field.maximum_normalized_value for field in profiles), "disjoint sum relation")
        _require(all(pair.maximum_normalized_pairwise_sum <= 1.0 for pair in certificate.pairwise_evidence), "disjoint pair sums")
        for pair in certificate.pairwise_evidence:
            _require(pair.maximum_normalized_pairwise_sum == max(
                profiles[pair.first_ordinal].maximum_normalized_value,
                profiles[pair.second_ordinal].maximum_normalized_value), "disjoint pair maximum")
            if count > 2:
                _require(pair.minimum_normalized_pairwise_sum == 0.0, "other disjoint field requires pair gap")
    _require(whole.duplicate_hash_ordinal_groups == _duplicate_groups(tuple(record.source_sha256 for record in certificate.ordered_fields))
             and whole.duplicate_reference_ordinal_groups == _duplicate_groups(tuple(record.portable_reference for record in certificate.ordered_fields)),
             "duplicate field evidence")
    if not whole.mutual_exclusion:
        classification = PartitionClassification.OVERLAPPING
    elif not whole.complete_coverage:
        classification = PartitionClassification.DISJOINT_WITH_GAPS
    elif whole.partition_sum_pixel_count == pixels:
        classification = PartitionClassification.EXACT_DISJOINT_COMPLETE_PARTITION
    else:
        classification = PartitionClassification.MIXED_NON_PARTITION
    _require(certificate.partition_classification is classification, "partition classification")
    _codes(certificate.finding_codes)


def _conditions(projection, certificate, profiles, profile) -> tuple[RegionalConditionPlanV3, ...]:
    return tuple(RegionalConditionPlanV3(
        active_ordinal=ordinal, document_index=record.document_index, layer_id=layer.layer_id,
        regional_prompt_text=layer.prompt_text,
        combined_prompt_text=combine_prompt_text(projection.base_prompt_text, layer.prompt_text),
        # Canonical binary64 treats signed zero as zero. Keep the downstream
        # ordinary JSON graph from exposing a second representation for one plan.
        requested_strength=0.0 if layer.requested_strength == 0.0 else layer.requested_strength,
        field_profile=field,
        polarity=certificate.polarity, orientation=certificate.orientation,
        effective_weight_expression=profile.effective_weight_expression,
    ) for ordinal, (layer, record, field) in enumerate(zip(projection.active_layers, certificate.ordered_fields, profiles, strict=True)))


def _duplicate_groups(values: tuple[object, ...]) -> tuple[tuple[int, ...], ...]:
    groups: list[tuple[int, ...]] = []
    for index, value in enumerate(values):
        if value not in values[:index]:
            indexes = tuple(other for other, candidate in enumerate(values) if candidate == value)
            if len(indexes) > 1:
                groups.append(indexes)
    return tuple(groups)


def _codes(values: object) -> None:
    _require(type(values) is tuple and all(type(item) is str and item for item in values)
             and len(set(values)) == len(values), "finding codes")


def _number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _range(minimum, maximum, bound: int) -> None:
    _require(_number(minimum) and _number(maximum) and 0 <= minimum <= maximum <= bound, "finite normalized sums")


def _count(value: object, maximum: int) -> None:
    _require(type(value) is int and 0 <= value <= maximum, "pixel count")


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _error(code: str, message: str) -> ValidationFinding:
    return ValidationFinding(code=code, severity=FindingSeverity.ERROR, message=message)
