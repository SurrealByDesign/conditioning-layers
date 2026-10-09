"""Fail-closed Translation Plan v2 construction with no asset or host I/O."""

from __future__ import annotations

from dataclasses import replace
import re

from conditioning_layers.adapters.prediction_mixing.models import (
    EFFECTIVE_WEIGHT_EXPRESSION,
    PREDICTION_MIXING_EXECUTION_PROFILE,
)
from conditioning_layers.assets import (
    FIELD_RELATIONSHIP_CERTIFICATE_FORMAT,
    FIELD_RELATIONSHIP_CERTIFICATE_VERSION,
    HOMOGENEOUS_PROMPT_LAYER_CONDITION_KIND,
    INFLUENCE_FIELD_BINDING_FORMAT_IDENTIFIER,
    INFLUENCE_FIELD_BINDING_FORMAT_VERSION,
    ORDERED_N_WAY_RELATIONSHIP_POLICY_IDENTIFIER,
    ORDERED_N_WAY_RELATIONSHIP_POLICY_VERSION,
    FieldOrientation,
    FieldPolarity,
    FieldRelationshipCertificate,
    FieldRelationshipCertificationStatus,
    InfluenceFieldBinding,
    InfluenceFieldBindingStatus,
    InspectedChannelProfile,
    PartitionClassification,
    fingerprint_field_relationship_certificate,
    fingerprint_influence_field_binding,
)
from conditioning_layers.capabilities import (
    PREDICTION_MIXING_CAPABILITY,
    evaluate_prediction_mixing,
)
from conditioning_layers.domain import (
    ConditioningDocument,
    FindingSeverity,
    PromptLayer,
    ValidationFinding,
)

from .canonical import CanonicalizationError, canonical_json_bytes
from .models import (
    CAPABILITY_EXECUTION_PROJECTION_IDENTIFIER,
    CAPABILITY_EXECUTION_PROJECTION_VERSION,
    CAPABILITY_POLICY_IDENTIFIER,
    CAPABILITY_POLICY_VERSION,
    DOCUMENT_EXECUTION_PROJECTION_IDENTIFIER,
    DOCUMENT_EXECUTION_PROJECTION_VERSION,
    EXECUTION_PROFILE_PROJECTION_IDENTIFIER,
    EXECUTION_PROFILE_PROJECTION_VERSION,
    TOPOLOGY_POLICY_IDENTIFIER,
    TOPOLOGY_POLICY_VERSION,
    TRANSLATION_PLAN_V2_IDENTIFIER,
    TRANSLATION_PLAN_V2_VERSION,
    CapabilityExecutionProjection,
    CertificateIdentity,
    DocumentExecutionProjection,
    EvidenceIdentity,
    ExecutionProfileProjection,
    OrderedLeftFoldTopologyPolicy,
    RegionalConditionPlanV2,
    TranslationPlanV2,
    TranslationResultV2,
    TranslationStatus,
)
from .identity import exact_contract_equal, fingerprint_translation_plan_v2
from .projections import (
    PREDICTION_MIXING_BACKEND_IDENTIFIER,
    build_capability_execution_projection,
    build_document_execution_projection,
    build_execution_profile_projection,
    fingerprint_capability_execution_projection,
    fingerprint_capability_policy,
    fingerprint_document_execution_projection,
    fingerprint_execution_profile_projection,
)
from .topology import (
    ORDERED_LEFT_FOLD_TOPOLOGY_POLICY,
    build_ordered_left_fold_schedule,
    fingerprint_topology_policy,
)


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_FROZEN_POLARITY = FieldPolarity()
_FROZEN_ORIENTATION = FieldOrientation()


def translate_prediction_mixing_v2(
    document: ConditioningDocument,
    document_projection: DocumentExecutionProjection,
    capability_projection: CapabilityExecutionProjection,
    binding: InfluenceFieldBinding,
    certificate: FieldRelationshipCertificate,
    execution_profile_projection: ExecutionProfileProjection,
    topology_policy: OrderedLeftFoldTopologyPolicy = (
        ORDERED_LEFT_FOLD_TOPOLOGY_POLICY
    ),
) -> TranslationResultV2:
    """Recompute, verify, reconcile, and translate one complete v2 request."""

    invalid: list[ValidationFinding] = []
    rejected: list[ValidationFinding] = []
    diagnostics: list[ValidationFinding] = []

    expected_document = _expected_document_projection(document, invalid)
    if expected_document is None:
        return _result(TranslationStatus.INVALID, None, invalid)

    _verify_document_projection(
        document_projection,
        expected_document,
        invalid,
    )
    expected_capability = _expected_capability_projection(
        document,
        expected_document,
        invalid,
    )
    if expected_capability is not None:
        _verify_capability_projection(
            capability_projection,
            expected_capability,
            invalid,
        )
        _capability_rejections(expected_capability, rejected)

    evaluation = evaluate_prediction_mixing(document)
    diagnostics.extend(evaluation.warnings)
    diagnostics.extend(evaluation.information)

    _verify_profile(execution_profile_projection, invalid, rejected)
    _verify_topology(topology_policy, invalid, rejected)
    _verify_evidence(
        document,
        expected_document,
        expected_capability,
        binding,
        certificate,
        execution_profile_projection,
        topology_policy,
        invalid,
        rejected,
    )

    if invalid:
        return _result(
            TranslationStatus.INVALID,
            None,
            invalid + rejected + diagnostics,
        )
    if rejected:
        return _result(
            TranslationStatus.REJECTED,
            None,
            rejected + diagnostics,
        )
    assert expected_capability is not None

    conditions = _regional_conditions(
        expected_document,
        binding,
        certificate,
        execution_profile_projection,
    )
    plan = TranslationPlanV2(
        contract_identifier=TRANSLATION_PLAN_V2_IDENTIFIER,
        contract_version=TRANSLATION_PLAN_V2_VERSION,
        adapter_identifier=PREDICTION_MIXING_CAPABILITY.adapter_identifier,
        document_projection=expected_document,
        capability_projection=expected_capability,
        binding_identity=EvidenceIdentity(
            format_identifier=binding.format_identifier,
            format_version=binding.format_version,
            fingerprint=binding.fingerprint,
        ),
        certificate_identity=CertificateIdentity(
            format_identifier=certificate.format_identifier,
            format_version=certificate.format_version,
            relationship_policy_identifier=(
                certificate.relationship_policy_identifier
            ),
            relationship_policy_version=certificate.relationship_policy_version,
            fingerprint=certificate.fingerprint,
        ),
        execution_profile_projection=execution_profile_projection,
        topology_policy=topology_policy,
        regional_conditions=conditions,
        fold_schedule=build_ordered_left_fold_schedule(len(conditions)),
        fingerprint="",
    )
    plan = replace(plan, fingerprint=fingerprint_translation_plan_v2(plan))
    diagnostics.append(
        _finding(
            "translation.v2.plan_created",
            FindingSeverity.INFORMATION,
            "A complete immutable Translation Plan v2 was created.",
        )
    )
    return _result(TranslationStatus.TRANSLATED, plan, diagnostics)


def serialize_translation_plan_v2(plan: TranslationPlanV2) -> bytes:
    """Serialize one complete plan using ADR-0008 canonical identity bytes."""

    if not isinstance(plan, TranslationPlanV2):
        raise TypeError("plan must be a TranslationPlanV2")
    return canonical_json_bytes(plan)


def _expected_document_projection(
    document: object,
    invalid: list[ValidationFinding],
) -> DocumentExecutionProjection | None:
    if not isinstance(document, ConditioningDocument):
        invalid.append(
            _finding(
                "translation.document_projection_malformed",
                FindingSeverity.ERROR,
                "Translation requires a canonical ConditioningDocument.",
                field_path="document",
            )
        )
        return None
    try:
        return build_document_execution_projection(document)
    except (TypeError, ValueError, CanonicalizationError):
        invalid.append(
            _finding(
                "translation.document_projection_malformed",
                FindingSeverity.ERROR,
                "The document cannot produce the required execution projection.",
                field_path="document_projection",
            )
        )
        return None


def _verify_document_projection(
    supplied: object,
    expected: DocumentExecutionProjection,
    invalid: list[ValidationFinding],
) -> None:
    if not isinstance(supplied, DocumentExecutionProjection):
        invalid.append(
            _finding(
                "translation.document_projection_malformed",
                FindingSeverity.ERROR,
                "The supplied Document Execution Projection is malformed.",
                field_path="document_projection",
            )
        )
        return
    if (
        supplied.format_identifier != DOCUMENT_EXECUTION_PROJECTION_IDENTIFIER
        or supplied.format_version != DOCUMENT_EXECUTION_PROJECTION_VERSION
    ):
        invalid.append(
            _finding(
                "translation.document_projection_malformed",
                FindingSeverity.ERROR,
                "The Document Execution Projection contract is unsupported.",
                field_path="document_projection",
            )
        )
    try:
        fingerprint = fingerprint_document_execution_projection(supplied)
    except (TypeError, ValueError, CanonicalizationError):
        fingerprint = None
    if fingerprint != supplied.fingerprint:
        invalid.append(
            _finding(
                "translation.document_projection_malformed",
                FindingSeverity.ERROR,
                "The Document Execution Projection fingerprint is invalid.",
                field_path="document_projection.fingerprint",
            )
        )
    elif not exact_contract_equal(supplied, expected):
        invalid.append(
            _finding(
                "translation.document_projection_mismatch",
                FindingSeverity.ERROR,
                "The Document Execution Projection is stale or belongs to different intent.",
                field_path="document_projection",
            )
        )


def _expected_capability_projection(
    document: ConditioningDocument,
    document_projection: DocumentExecutionProjection,
    invalid: list[ValidationFinding],
) -> CapabilityExecutionProjection | None:
    try:
        return build_capability_execution_projection(document, document_projection)
    except (TypeError, ValueError, CanonicalizationError):
        invalid.append(
            _finding(
                "translation.capability_projection_mismatch",
                FindingSeverity.ERROR,
                "The authoritative capability result could not be projected.",
                field_path="capability_projection",
            )
        )
        return None


def _verify_capability_projection(
    supplied: object,
    expected: CapabilityExecutionProjection,
    invalid: list[ValidationFinding],
) -> None:
    if not isinstance(supplied, CapabilityExecutionProjection):
        invalid.append(
            _finding(
                "translation.capability_projection_mismatch",
                FindingSeverity.ERROR,
                "The supplied Capability Execution Projection is malformed.",
                field_path="capability_projection",
            )
        )
        return
    if (
        supplied.format_identifier != CAPABILITY_EXECUTION_PROJECTION_IDENTIFIER
        or supplied.format_version != CAPABILITY_EXECUTION_PROJECTION_VERSION
        or supplied.capability_policy_identifier != CAPABILITY_POLICY_IDENTIFIER
        or supplied.capability_policy_version != CAPABILITY_POLICY_VERSION
        or supplied.capability_policy_fingerprint != fingerprint_capability_policy()
    ):
        invalid.append(
            _finding(
                "translation.capability_projection_mismatch",
                FindingSeverity.ERROR,
                "The Capability Execution Projection policy identity is invalid.",
                field_path="capability_projection",
            )
        )
    try:
        fingerprint = fingerprint_capability_execution_projection(supplied)
    except (TypeError, ValueError, CanonicalizationError):
        fingerprint = None
    if fingerprint != supplied.fingerprint or not exact_contract_equal(
        supplied,
        expected,
    ):
        invalid.append(
            _finding(
                "translation.capability_projection_mismatch",
                FindingSeverity.ERROR,
                "The Capability Execution Projection is stale, altered, or mismatched.",
                field_path="capability_projection.fingerprint",
            )
        )


def _verify_profile(
    supplied: object,
    invalid: list[ValidationFinding],
    rejected: list[ValidationFinding],
) -> None:
    if not isinstance(supplied, ExecutionProfileProjection):
        invalid.append(
            _finding(
                "translation.profile_identity_mismatch",
                FindingSeverity.ERROR,
                "The supplied Execution Profile Projection is malformed.",
                field_path="execution_profile_projection",
            )
        )
        return
    try:
        fingerprint = fingerprint_execution_profile_projection(supplied)
    except (TypeError, ValueError, CanonicalizationError):
        fingerprint = None
    if fingerprint != supplied.fingerprint:
        invalid.append(
            _finding(
                "translation.profile_identity_mismatch",
                FindingSeverity.ERROR,
                "The Execution Profile Projection fingerprint is invalid.",
                field_path="execution_profile_projection.fingerprint",
            )
        )
        return
    expected = build_execution_profile_projection(
        PREDICTION_MIXING_EXECUTION_PROFILE
    )
    if (
        supplied.format_identifier != EXECUTION_PROFILE_PROJECTION_IDENTIFIER
        or supplied.format_version != EXECUTION_PROFILE_PROJECTION_VERSION
    ):
        invalid.append(
            _finding(
                "translation.profile_identity_mismatch",
                FindingSeverity.ERROR,
                "The Execution Profile Projection contract is unsupported.",
                field_path="execution_profile_projection",
            )
        )
    elif supplied.profile_identifier != expected.profile_identifier:
        rejected.append(
            _finding(
                "translation.unsupported_profile",
                FindingSeverity.ERROR,
                "The requested execution profile is not supported by Translation Plan v2.",
                field_path="execution_profile_projection.profile_identifier",
            )
        )
    elif not exact_contract_equal(supplied, expected):
        invalid.append(
            _finding(
                "translation.profile_content_mismatch",
                FindingSeverity.ERROR,
                "The known execution profile identifier has different semantic content.",
                field_path="execution_profile_projection",
            )
        )
        if (
            supplied.base_prompt_policy != expected.base_prompt_policy
            or supplied.prompt_combination_delimiter
            != expected.prompt_combination_delimiter
        ):
            invalid.append(
                _finding(
                    "translation.prompt_policy_mismatch",
                    FindingSeverity.ERROR,
                    "The Base Prompt composition policy differs from the known profile.",
                    field_path="execution_profile_projection.base_prompt_policy",
                )
            )


def _verify_topology(
    supplied: object,
    invalid: list[ValidationFinding],
    rejected: list[ValidationFinding],
) -> None:
    if not isinstance(supplied, OrderedLeftFoldTopologyPolicy):
        invalid.append(
            _finding(
                "translation.topology_fingerprint_mismatch",
                FindingSeverity.ERROR,
                "The supplied topology descriptor is malformed.",
                field_path="topology_policy",
            )
        )
        return
    try:
        fingerprint = fingerprint_topology_policy(supplied)
    except (TypeError, ValueError, CanonicalizationError):
        fingerprint = None
    if fingerprint != supplied.fingerprint:
        invalid.append(
            _finding(
                "translation.topology_fingerprint_mismatch",
                FindingSeverity.ERROR,
                "The topology policy fingerprint is invalid.",
                field_path="topology_policy.fingerprint",
            )
        )
        return
    if (
        supplied.policy_identifier != TOPOLOGY_POLICY_IDENTIFIER
        or supplied.policy_version != TOPOLOGY_POLICY_VERSION
    ):
        rejected.append(
            _finding(
                "translation.unsupported_topology",
                FindingSeverity.ERROR,
                "The requested topology policy is unsupported.",
                field_path="topology_policy.policy_identifier",
            )
        )
    elif not exact_contract_equal(supplied, ORDERED_LEFT_FOLD_TOPOLOGY_POLICY):
        invalid.append(
            _finding(
                "translation.topology_fingerprint_mismatch",
                FindingSeverity.ERROR,
                "The known topology identifier has different semantic content.",
                field_path="topology_policy",
            )
        )


def _verify_evidence(
    document: ConditioningDocument,
    document_projection: DocumentExecutionProjection,
    capability_projection: CapabilityExecutionProjection | None,
    binding: object,
    certificate: object,
    profile: object,
    topology: object,
    invalid: list[ValidationFinding],
    rejected: list[ValidationFinding],
) -> None:
    if not isinstance(binding, InfluenceFieldBinding):
        invalid.append(
            _finding(
                "translation.binding_stale",
                FindingSeverity.ERROR,
                "The supplied Influence Field binding is malformed.",
                field_path="binding",
            )
        )
        return
    if not isinstance(certificate, FieldRelationshipCertificate):
        invalid.append(
            _finding(
                "translation.certificate_stale",
                FindingSeverity.ERROR,
                "The supplied N-way Field Certificate is malformed.",
                field_path="certificate",
            )
        )
        return

    try:
        binding_fingerprint = fingerprint_influence_field_binding(binding)
    except (TypeError, ValueError, UnicodeError):
        binding_fingerprint = None
    if binding_fingerprint != binding.fingerprint:
        invalid.append(
            _finding(
                "translation.binding_fingerprint_mismatch",
                FindingSeverity.ERROR,
                "The Influence Field binding fingerprint is invalid.",
                field_path="binding.fingerprint",
            )
        )
    if (
        binding.format_identifier != INFLUENCE_FIELD_BINDING_FORMAT_IDENTIFIER
        or binding.format_version != INFLUENCE_FIELD_BINDING_FORMAT_VERSION
    ):
        invalid.append(
            _finding(
                "translation.binding_stale",
                FindingSeverity.ERROR,
                "The Influence Field binding contract is unsupported.",
                field_path="binding",
            )
        )
    if binding.status is not InfluenceFieldBindingStatus.BOUND:
        invalid.append(
            _finding(
                "translation.binding_unbound",
                FindingSeverity.ERROR,
                "Translation Plan v2 requires a bound Influence Field assignment.",
                field_path="binding.status",
            )
        )
    if any(item.severity is FindingSeverity.ERROR for item in binding.findings):
        invalid.append(
            _finding(
                "translation.binding_unbound",
                FindingSeverity.ERROR,
                "The binding retains blocking findings.",
                field_path="binding.findings",
            )
        )

    try:
        certificate_fingerprint = fingerprint_field_relationship_certificate(
            certificate
        )
    except (TypeError, ValueError, UnicodeError):
        certificate_fingerprint = None
    if certificate_fingerprint != certificate.fingerprint:
        invalid.append(
            _finding(
                "translation.certificate_fingerprint_mismatch",
                FindingSeverity.ERROR,
                "The N-way Field Certificate fingerprint is invalid.",
                field_path="certificate.fingerprint",
            )
        )
    if (
        certificate.format_identifier != FIELD_RELATIONSHIP_CERTIFICATE_FORMAT
        or certificate.format_version != FIELD_RELATIONSHIP_CERTIFICATE_VERSION
    ):
        invalid.append(
            _finding(
                "translation.certificate_stale",
                FindingSeverity.ERROR,
                "The N-way Field Certificate contract is unsupported.",
                field_path="certificate",
            )
        )
    if certificate.status is not FieldRelationshipCertificationStatus.CERTIFIED:
        invalid.append(
            _finding(
                "translation.certificate_uncertified",
                FindingSeverity.ERROR,
                "Translation Plan v2 requires certified whole-set evidence.",
                field_path="certificate.status",
            )
        )
    if (
        certificate.relationship_policy_identifier
        != ORDERED_N_WAY_RELATIONSHIP_POLICY_IDENTIFIER
        or certificate.relationship_policy_version
        != ORDERED_N_WAY_RELATIONSHIP_POLICY_VERSION
    ):
        invalid.append(
            _finding(
                "translation.relationship_policy_mismatch",
                FindingSeverity.ERROR,
                "The N-way relationship policy is not the supported policy.",
                field_path="certificate.relationship_policy_identifier",
            )
        )
    if (
        not certificate.shared_raster.all_fields_satisfy
        or not certificate.whole_set_evidence.certified
        or certificate.partition_classification
        is not PartitionClassification.EXACT_DISJOINT_COMPLETE_PARTITION
        or any(not item.inspection_certified for item in certificate.ordered_fields)
    ):
        invalid.append(
            _finding(
                "translation.relationship_policy_mismatch",
                FindingSeverity.ERROR,
                "The certified fields do not satisfy the exact disjoint partition contract.",
                field_path="certificate.whole_set_evidence",
            )
        )

    target = binding.target
    if (
        target.translation_contract_identifier != TRANSLATION_PLAN_V2_IDENTIFIER
        or target.backend_identifier != PREDICTION_MIXING_BACKEND_IDENTIFIER
        or target.condition_kind != HOMOGENEOUS_PROMPT_LAYER_CONDITION_KIND
    ):
        invalid.append(
            _finding(
                "translation.binding_stale",
                FindingSeverity.ERROR,
                "The binding target does not match Translation Plan v2.",
                field_path="binding.target",
            )
        )
    if target.adapter_identifier != document.selected_adapter_id:
        invalid.append(
            _finding(
                "translation.binding_stale",
                FindingSeverity.ERROR,
                "The binding adapter target differs from the document.",
                field_path="binding.target.adapter_identifier",
            )
        )
    elif target.adapter_identifier != PREDICTION_MIXING_CAPABILITY.adapter_identifier:
        rejected.append(
            _finding(
                "translation.unsupported_adapter",
                FindingSeverity.ERROR,
                "The requested adapter is unsupported by Translation Plan v2.",
                field_path="binding.target.adapter_identifier",
            )
        )
    if isinstance(profile, ExecutionProfileProjection) and (
        target.runtime_profile_identifier != profile.profile_identifier
    ):
        invalid.append(
            _finding(
                "translation.binding_stale",
                FindingSeverity.ERROR,
                "The binding runtime-profile target differs from the profile projection.",
                field_path="binding.target.runtime_profile_identifier",
            )
        )
    if isinstance(topology, OrderedLeftFoldTopologyPolicy) and (
        target.topology_policy_identifier != topology.policy_identifier
    ):
        invalid.append(
            _finding(
                "translation.binding_stale",
                FindingSeverity.ERROR,
                "The binding topology target differs from the topology descriptor.",
                field_path="binding.target.topology_policy_identifier",
            )
        )

    embedded = binding.certificate
    if (
        embedded.fingerprint != certificate.fingerprint
        or embedded.format_identifier != certificate.format_identifier
        or embedded.format_version != certificate.format_version
        or embedded.relationship_policy_identifier
        != certificate.relationship_policy_identifier
        or embedded.relationship_policy_version
        != certificate.relationship_policy_version
        or not embedded.fingerprint_valid
        or not embedded.certified
        or not embedded.order_matches_assignments
        or not embedded.hashes_match_assignments
    ):
        invalid.append(
            _finding(
                "translation.binding_certificate_mismatch",
                FindingSeverity.ERROR,
                "The binding and independently supplied certificate do not agree.",
                field_path="binding.certificate",
            )
        )

    library = binding.library
    if (
        library.expected_library_identifier != library.observed_library_identifier
        or library.expected_library_version != library.observed_library_version
        or library.expected_catalog_sha256 != library.observed_catalog_sha256
        or library.selected_family_identifier != library.observed_family_identifier
        or library.selected_family_version != library.observed_family_version
        or library.expected_family_manifest_sha256
        != library.observed_family_manifest_sha256
    ):
        invalid.append(
            _finding(
                "translation.binding_stale",
                FindingSeverity.ERROR,
                "The binding library identities are not internally reconciled.",
                field_path="binding.library",
            )
        )

    active = tuple(
        (index, layer)
        for index, layer in enumerate(document.layers)
        if isinstance(layer, PromptLayer) and layer.visible is True
    )
    counts = (
        len(active),
        len(document_projection.active_layers),
        len(binding.assignments),
        len(certificate.ordered_fields),
    )
    if capability_projection is not None:
        counts += (capability_projection.active_layer_count,)
    if len(set(counts)) != 1:
        invalid.append(
            _finding(
                "translation.document_order_mismatch",
                FindingSeverity.ERROR,
                "Active condition counts differ across planning evidence.",
                field_path="regional_conditions",
            )
        )
        return

    for ordinal, ((document_index, layer), projected, assignment, record) in enumerate(
        zip(
            active,
            document_projection.active_layers,
            binding.assignments,
            certificate.ordered_fields,
            strict=True,
        )
    ):
        if (
            projected.active_ordinal != ordinal
            or assignment.ordinal != ordinal
            or record.ordinal != ordinal
            or projected.layer_id != layer.layer_id
            or assignment.layer_id != layer.layer_id
            or record.layer_id != layer.layer_id
            or assignment.document_index != document_index
            or record.document_index != document_index
        ):
            invalid.append(
                _finding(
                    "translation.document_order_mismatch",
                    FindingSeverity.ERROR,
                    "Active Prompt Layer order or identity differs across evidence.",
                    layer_id=layer.layer_id,
                    field_path=f"regional_conditions[{ordinal}]",
                )
            )
        if (
            projected.influence_field_reference
            != assignment.document_field_reference
            or projected.influence_field_reference != record.portable_reference
        ):
            invalid.append(
                _finding(
                    "translation.field_identity_mismatch",
                    FindingSeverity.ERROR,
                    "The document field reference differs across planning evidence.",
                    layer_id=layer.layer_id,
                    field_path=f"regional_conditions[{ordinal}].field_reference",
                )
            )
        hashes = (
            record.source_sha256,
            assignment.expected_library_source_sha256,
            assignment.observed_library_source_sha256,
            assignment.inspected_document_field_sha256,
        )
        if (
            any(not _valid_sha256(item) for item in hashes)
            or len(set(hashes)) != 1
            or (
                projected.declared_field_sha256 is not None
                and projected.declared_field_sha256 != record.source_sha256
            )
            or not assignment.source_and_document_bytes_match
            or assignment.library_field_id is None
            or assignment.library_field_reference is None
        ):
            invalid.append(
                _finding(
                    "translation.field_identity_mismatch",
                    FindingSeverity.ERROR,
                    "The exact field-byte or library assignment identity differs.",
                    layer_id=layer.layer_id,
                    field_path=f"regional_conditions[{ordinal}].source_field_sha256",
                )
            )
        expected_encoding = _certificate_encoding(record.channel_profile)
        if (
            assignment.width != record.width
            or assignment.height != record.height
            or assignment.encoding != expected_encoding
            or assignment.width != library.width
            or assignment.height != library.height
            or assignment.encoding != library.encoding
            or (
                isinstance(profile, ExecutionProfileProjection)
                and (
                    assignment.width != profile.expected_field_width
                    or assignment.height != profile.expected_field_height
                    or assignment.encoding != profile.expected_field_encoding
                )
            )
        ):
            invalid.append(
                _finding(
                    "translation.field_identity_mismatch",
                    FindingSeverity.ERROR,
                    "Field dimensions or encoding differ across planning evidence.",
                    layer_id=layer.layer_id,
                    field_path=f"regional_conditions[{ordinal}].dimensions",
                )
            )
        if (
            certificate.polarity != _FROZEN_POLARITY
            or certificate.orientation != _FROZEN_ORIENTATION
            or assignment.polarity != certificate.polarity
            or assignment.orientation != certificate.orientation
        ):
            invalid.append(
                _finding(
                    "translation.field_identity_mismatch",
                    FindingSeverity.ERROR,
                    "Field polarity or orientation differs from the frozen contract.",
                    layer_id=layer.layer_id,
                    field_path=f"regional_conditions[{ordinal}].orientation",
                )
            )


def _capability_rejections(
    projection: CapabilityExecutionProjection,
    rejected: list[ValidationFinding],
) -> None:
    if projection.compatible:
        return
    rejected.append(
        _finding(
            "translation.capability_rejected",
            FindingSeverity.ERROR,
            "Capability Authority rejected this document.",
            field_path="capability_projection",
        )
    )
    codes = {item.code for item in projection.decisions}
    if "capability.active_layer_limit" in codes:
        rejected.append(
            _finding(
                "translation.active_layer_limit",
                FindingSeverity.ERROR,
                "The requested Active Prompt Layer count exceeds current capability.",
                field_path="layers",
            )
        )
    if {
        "capability.adapter_required",
        "capability.adapter_unsupported",
    } & codes:
        rejected.append(
            _finding(
                "translation.unsupported_adapter",
                FindingSeverity.ERROR,
                "The selected adapter is unsupported.",
                field_path="selected_adapter_id",
            )
        )


def _regional_conditions(
    document_projection: DocumentExecutionProjection,
    binding: InfluenceFieldBinding,
    certificate: FieldRelationshipCertificate,
    profile: ExecutionProfileProjection,
) -> tuple[RegionalConditionPlanV2, ...]:
    library = binding.library
    conditions: list[RegionalConditionPlanV2] = []
    for projected, assignment, record in zip(
        document_projection.active_layers,
        binding.assignments,
        certificate.ordered_fields,
        strict=True,
    ):
        assert assignment.library_field_id is not None
        assert assignment.library_field_reference is not None
        assert record.source_sha256 is not None
        assert assignment.width is not None and assignment.height is not None
        assert assignment.encoding is not None
        conditions.append(
            RegionalConditionPlanV2(
                active_ordinal=projected.active_ordinal,
                layer_id=projected.layer_id,
                regional_prompt_text=projected.prompt_text,
                combined_prompt_text=(
                    document_projection.base_prompt_text
                    + profile.prompt_combination_delimiter
                    + projected.prompt_text
                ),
                requested_strength=projected.requested_strength,
                library_identifier=library.expected_library_identifier,
                library_version=library.expected_library_version,
                family_identifier=library.selected_family_identifier,
                family_version=library.selected_family_version,
                permutation_identifier=library.permutation_identifier,
                library_field_id=assignment.library_field_id,
                library_field_reference=assignment.library_field_reference,
                document_field_reference=assignment.document_field_reference,
                source_field_sha256=record.source_sha256,
                width=assignment.width,
                height=assignment.height,
                encoding=assignment.encoding,
                polarity=certificate.polarity,
                orientation=certificate.orientation,
                effective_weight_expression=EFFECTIVE_WEIGHT_EXPRESSION,
            )
        )
    return tuple(conditions)


def _certificate_encoding(value: object) -> str | None:
    if value is InspectedChannelProfile.GRAYSCALE_8:
        return "grayscale-8"
    if value is InspectedChannelProfile.RGB_IDENTICAL_8:
        return "rgb-identical-8"
    return None


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_PATTERN.fullmatch(value) is not None


def _result(
    status: TranslationStatus,
    plan: TranslationPlanV2 | None,
    findings: list[ValidationFinding],
) -> TranslationResultV2:
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
    return TranslationResultV2(
        status=status,
        plan=plan,
        findings=tuple(retained),
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
