"""Deterministic library-to-document Influence Field binding evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass, replace
from enum import Enum
import hashlib
import json
from pathlib import Path
import re

from conditioning_layers.adapters.prediction_mixing import (
    PREDICTION_MIXING_EXECUTION_PROFILE,
)
from conditioning_layers.domain import (
    PREDICTION_MIXING_ADAPTER_ID,
    ConditioningDocument,
    FindingSeverity,
    InfluenceFieldAssetReference,
    PromptLayer,
    ValidationFinding,
)
from conditioning_layers.persistence import AssetPathError, normalize_asset_reference

from .models import (
    DEFAULT_INSPECTION_LIMITS,
    FIELD_RELATIONSHIP_CERTIFICATE_FORMAT,
    FIELD_RELATIONSHIP_CERTIFICATE_VERSION,
    ORDERED_N_WAY_RELATIONSHIP_POLICY_IDENTIFIER,
    ORDERED_N_WAY_RELATIONSHIP_POLICY_VERSION,
    FieldOrientation,
    FieldPolarity,
    FieldRelationshipCertificate,
    FieldRelationshipCertificationStatus,
    InspectionLimits,
    InspectedChannelProfile,
)
from .overlap import inspect_field_asset
from .relationships import fingerprint_field_relationship_certificate


INFLUENCE_FIELD_BINDING_FORMAT_IDENTIFIER = (
    "conditioning-layers.influence-field-binding.v1"
)
INFLUENCE_FIELD_BINDING_FORMAT_VERSION = 1
INFLUENCE_FIELD_LIBRARY_IDENTIFIER = (
    "conditioning-layers.influence-field-library"
)
PREDICTION_MIXING_BINDING_BACKEND_IDENTIFIER = "krea2.comfyui"
HOMOGENEOUS_PROMPT_LAYER_CONDITION_KIND = (
    "homogeneous-prompt-layer-prediction-mixing"
)
FUTURE_TRANSLATION_CONTRACT_IDENTIFIER = "prediction-mixing.translation-plan.v2"
ORDERED_LEFT_FOLD_TOPOLOGY_POLICY_IDENTIFIER = (
    "prediction-mixing.ordered-left-fold.v1"
)

_FROZEN_POLARITY = FieldPolarity()
_FROZEN_ORIENTATION = FieldOrientation()
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_FAMILY_VERSION_PATTERN = re.compile(r"\.v([1-9][0-9]*)$")
_CATALOG_REFERENCE = "library-manifest.json"


class InfluenceFieldBindingStatus(str, Enum):
    """Whether exact library, document, and certificate identities agree."""

    BOUND = "bound"
    UNBOUND = "unbound"


@dataclass(frozen=True, slots=True)
class InfluenceFieldLibrarySelection:
    """Caller-declared trust anchor and selected reusable field assignment."""

    expected_catalog_sha256: str
    family_identifier: str
    family_version: int
    permutation_identifier: str
    expected_library_identifier: str = INFLUENCE_FIELD_LIBRARY_IDENTIFIER
    expected_library_version: int = 1
    expected_family_manifest_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class InfluenceFieldBindingTarget:
    """Declared future compatibility targets; never execution authorization."""

    adapter_identifier: str = PREDICTION_MIXING_ADAPTER_ID
    backend_identifier: str = PREDICTION_MIXING_BINDING_BACKEND_IDENTIFIER
    condition_kind: str = HOMOGENEOUS_PROMPT_LAYER_CONDITION_KIND
    translation_contract_identifier: str = FUTURE_TRANSLATION_CONTRACT_IDENTIFIER
    topology_policy_identifier: str = ORDERED_LEFT_FOLD_TOPOLOGY_POLICY_IDENTIFIER
    runtime_profile_identifier: str | None = (
        PREDICTION_MIXING_EXECUTION_PROFILE.profile_identifier
    )


DEFAULT_INFLUENCE_FIELD_BINDING_TARGET = InfluenceFieldBindingTarget()


@dataclass(frozen=True, slots=True)
class InfluenceFieldLibraryIdentity:
    """Observed and expected identity of one selected library family."""

    expected_library_identifier: str
    observed_library_identifier: str | None
    expected_library_version: int
    observed_library_version: int | None
    catalog_reference: str
    expected_catalog_sha256: str
    observed_catalog_sha256: str | None
    selected_family_identifier: str
    selected_family_version: int
    observed_family_identifier: str | None
    observed_family_version: int | None
    family_manifest_reference: str | None
    expected_family_manifest_sha256: str | None
    observed_family_manifest_sha256: str | None
    permutation_identifier: str
    ordered_field_ids: tuple[str, ...]
    width: int | None
    height: int | None
    encoding: str | None
    support_status: str | None


@dataclass(frozen=True, slots=True)
class InfluenceFieldBindingAssignment:
    """One retained Active Prompt Layer mapped to one exact library field."""

    ordinal: int
    layer_id: str
    document_index: int
    document_field_reference: str
    library_field_id: str | None
    library_field_reference: str | None
    expected_library_source_sha256: str | None
    observed_library_source_sha256: str | None
    inspected_document_field_sha256: str | None
    source_and_document_bytes_match: bool
    width: int | None
    height: int | None
    encoding: str | None
    polarity: FieldPolarity
    orientation: FieldOrientation
    finding_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InfluenceFieldCertificateBinding:
    """Cross-reference from ordered assignments to exact certificate evidence."""

    format_identifier: str
    format_version: int
    relationship_policy_identifier: str
    relationship_policy_version: int
    fingerprint: str
    fingerprint_valid: bool
    certified: bool
    ordered_layer_ids: tuple[str | None, ...]
    ordered_source_sha256: tuple[str | None, ...]
    order_matches_assignments: bool
    hashes_match_assignments: bool


@dataclass(frozen=True, slots=True)
class InfluenceFieldBinding:
    """Portable immutable planning evidence with no execution authority."""

    format_identifier: str
    format_version: int
    fingerprint: str
    status: InfluenceFieldBindingStatus
    findings: tuple[ValidationFinding, ...]
    target: InfluenceFieldBindingTarget
    library: InfluenceFieldLibraryIdentity
    assignments: tuple[InfluenceFieldBindingAssignment, ...]
    certificate: InfluenceFieldCertificateBinding


@dataclass(frozen=True, slots=True)
class InfluenceFieldBindingResult:
    """Binding artifact plus findings grouped for callers."""

    binding: InfluenceFieldBinding
    errors: tuple[ValidationFinding, ...]
    warnings: tuple[ValidationFinding, ...]
    information: tuple[ValidationFinding, ...]


@dataclass(frozen=True, slots=True)
class _LoadedField:
    asset_id: str
    reference: str
    expected_sha256: str
    observed_sha256: str | None
    width: int | None
    height: int | None
    encoding: str | None


@dataclass(frozen=True, slots=True)
class _LoadedFamily:
    identity: InfluenceFieldLibraryIdentity
    fields: tuple[_LoadedField, ...]
    permutations: tuple[tuple[str, tuple[str, ...]], ...]
    findings: tuple[ValidationFinding, ...]


def bind_influence_field_library(
    library_root: str | Path,
    document: ConditioningDocument,
    selection: InfluenceFieldLibrarySelection,
    certificate: FieldRelationshipCertificate,
    *,
    target: InfluenceFieldBindingTarget = DEFAULT_INFLUENCE_FIELD_BINDING_TARGET,
    limits: InspectionLimits = DEFAULT_INSPECTION_LIMITS,
) -> InfluenceFieldBindingResult:
    """Bind one library permutation to document-owned certified field bytes.

    This function reads only the supplied library root. Document bytes have
    already been read by the independently supplied N-way certificate. The
    result cannot translate, generate, prepare a runtime, or authorize execution.
    """

    if not isinstance(document, ConditioningDocument):
        raise TypeError("document must be a ConditioningDocument")
    if not isinstance(selection, InfluenceFieldLibrarySelection):
        raise TypeError("selection must be an InfluenceFieldLibrarySelection")
    if not isinstance(certificate, FieldRelationshipCertificate):
        raise TypeError("certificate must be a FieldRelationshipCertificate")
    if not isinstance(target, InfluenceFieldBindingTarget):
        raise TypeError("target must be an InfluenceFieldBindingTarget")
    if not isinstance(limits, InspectionLimits):
        raise TypeError("limits must be InspectionLimits")

    findings: list[ValidationFinding] = []
    findings.extend(_validate_selection(selection))
    findings.extend(_validate_target(target, document))
    loaded = _load_family(library_root, selection, limits)
    findings.extend(loaded.findings)

    active = tuple(
        (index, layer)
        for index, layer in enumerate(document.layers)
        if isinstance(layer, PromptLayer) and layer.visible is True
    )
    permutation = _selected_permutation(loaded.permutations, selection, findings)
    if len(active) > len(permutation):
        findings.append(
            _finding(
                "binding.assignment_missing",
                "One or more Active Prompt Layers have no library field assignment.",
            )
        )
    elif len(active) < len(permutation):
        findings.append(
            _finding(
                "binding.assignment_extra",
                "The selected permutation has fields without Active Prompt Layers.",
            )
        )

    fields_by_id = {item.asset_id: item for item in loaded.fields}
    certificate_records = certificate.ordered_fields
    assignments: list[InfluenceFieldBindingAssignment] = []
    normalized_document_references: list[str] = []
    selected_ids: list[str] = []

    for ordinal, (document_index, layer) in enumerate(active):
        assignment_findings: list[ValidationFinding] = []
        field_id = permutation[ordinal] if ordinal < len(permutation) else None
        if field_id is not None:
            selected_ids.append(field_id)
        loaded_field = fields_by_id.get(field_id) if field_id is not None else None
        if field_id is not None and loaded_field is None:
            assignment_findings.append(
                _finding(
                    "binding.unknown_field_id",
                    "The selected permutation references an unknown library field.",
                    layer_id=layer.layer_id,
                    field_path=f"assignments[{ordinal}].library_field_id",
                )
            )

        document_reference = ""
        if not isinstance(layer.influence_field, InfluenceFieldAssetReference):
            assignment_findings.append(
                _finding(
                    "binding.assignment_missing",
                    "An Active Prompt Layer is missing its document-owned field reference.",
                    layer_id=layer.layer_id,
                    field_path=f"layers[{document_index}].influence_field",
                )
            )
        else:
            try:
                document_reference = normalize_asset_reference(
                    layer.influence_field.relative_path
                )
                normalized_document_references.append(document_reference)
            except AssetPathError:
                assignment_findings.append(
                    _finding(
                        "binding.reference_non_portable",
                        "Document field references must be portable asset-root-relative paths.",
                        layer_id=layer.layer_id,
                        field_path=(
                            f"layers[{document_index}].influence_field.relative_path"
                        ),
                    )
                )

        record = certificate_records[ordinal] if ordinal < len(certificate_records) else None
        document_sha256 = record.source_sha256 if record is not None else None
        if (
            isinstance(layer.influence_field, InfluenceFieldAssetReference)
            and layer.influence_field.checksum is not None
            and document_sha256 != layer.influence_field.checksum.lower()
        ):
            assignment_findings.append(
                _finding(
                    "binding.certificate_field_hash_mismatch",
                    "The certificate hash does not match document field metadata.",
                    layer_id=layer.layer_id,
                    field_path=f"assignments[{ordinal}].inspected_document_field_sha256",
                )
            )

        expected_source = (
            loaded_field.expected_sha256 if loaded_field is not None else None
        )
        observed_source = (
            loaded_field.observed_sha256 if loaded_field is not None else None
        )
        bytes_match = bool(
            expected_source
            and observed_source == expected_source
            and document_sha256 == expected_source
        )
        if loaded_field is not None and observed_source != expected_source:
            assignment_findings.append(
                _finding(
                    "binding.source_hash_mismatch",
                    "The library field bytes do not match the family manifest.",
                    layer_id=layer.layer_id,
                    field_path=f"assignments[{ordinal}].observed_library_source_sha256",
                )
            )
        if loaded_field is not None and document_sha256 != expected_source:
            assignment_findings.append(
                _finding(
                    "binding.certificate_field_hash_mismatch",
                    "The certified document bytes do not match the selected library field.",
                    layer_id=layer.layer_id,
                    field_path=f"assignments[{ordinal}].inspected_document_field_sha256",
                )
            )

        assignments.append(
            InfluenceFieldBindingAssignment(
                ordinal=ordinal,
                layer_id=layer.layer_id,
                document_index=document_index,
                document_field_reference=document_reference,
                library_field_id=field_id,
                library_field_reference=(
                    loaded_field.reference if loaded_field is not None else None
                ),
                expected_library_source_sha256=expected_source,
                observed_library_source_sha256=observed_source,
                inspected_document_field_sha256=document_sha256,
                source_and_document_bytes_match=bytes_match,
                width=record.width if record is not None else None,
                height=record.height if record is not None else None,
                encoding=(
                    _portable_encoding(record.channel_profile)
                    if record is not None
                    else None
                ),
                polarity=certificate.polarity,
                orientation=certificate.orientation,
                finding_codes=(),
            )
        )
        findings.extend(assignment_findings)
        assignments[-1] = replace(
            assignments[-1],
            finding_codes=tuple(item.code for item in assignment_findings),
        )

    if _has_duplicates(tuple(selected_ids)) or _has_duplicates(
        tuple(normalized_document_references)
    ):
        findings.append(
            _finding(
                "binding.assignment_duplicate",
                "Library fields and document field references must map one-to-one.",
            )
        )

    certificate_binding = _reconcile_certificate(
        certificate,
        tuple(assignments),
        loaded.identity,
        findings,
    )
    findings.extend(_validate_frozen_spatial_contract(certificate))
    findings.append(
        ValidationFinding(
            code="binding.execution_not_authorized",
            severity=FindingSeverity.INFORMATION,
            message=(
                "Field binding is planning evidence and does not authorize translation, "
                "graph generation, runtime preparation, or execution."
            ),
        )
    )

    all_findings = _deduplicate_findings(findings)
    errors = tuple(
        item for item in all_findings if item.severity is FindingSeverity.ERROR
    )
    warnings = tuple(
        item for item in all_findings if item.severity is FindingSeverity.WARNING
    )
    information = tuple(
        item
        for item in all_findings
        if item.severity is FindingSeverity.INFORMATION
    )
    status = (
        InfluenceFieldBindingStatus.BOUND
        if not errors and certificate_binding.certified
        else InfluenceFieldBindingStatus.UNBOUND
    )
    binding = InfluenceFieldBinding(
        format_identifier=INFLUENCE_FIELD_BINDING_FORMAT_IDENTIFIER,
        format_version=INFLUENCE_FIELD_BINDING_FORMAT_VERSION,
        fingerprint="",
        status=status,
        findings=all_findings,
        target=target,
        library=loaded.identity,
        assignments=tuple(assignments),
        certificate=certificate_binding,
    )
    binding = replace(binding, fingerprint=fingerprint_influence_field_binding(binding))
    return InfluenceFieldBindingResult(
        binding=binding,
        errors=errors,
        warnings=warnings,
        information=information,
    )


def serialize_influence_field_binding(binding: InfluenceFieldBinding) -> str:
    """Return canonical portable JSON with one trailing newline."""

    if not isinstance(binding, InfluenceFieldBinding):
        raise TypeError("binding must be an InfluenceFieldBinding")
    return json.dumps(
        _portable(binding),
        allow_nan=False,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def fingerprint_influence_field_binding(binding: InfluenceFieldBinding) -> str:
    """Fingerprint every semantic binding field except the fingerprint itself."""

    if not isinstance(binding, InfluenceFieldBinding):
        raise TypeError("binding must be an InfluenceFieldBinding")
    material = _portable(binding)
    assert isinstance(material, dict)
    material.pop("fingerprint")
    return _sha256_json(material)


def _load_family(
    library_root: str | Path,
    selection: InfluenceFieldLibrarySelection,
    limits: InspectionLimits,
) -> _LoadedFamily:
    findings: list[ValidationFinding] = []
    catalog_bytes = _read_library_file(
        library_root,
        _CATALOG_REFERENCE,
        limits,
        missing_code="binding.catalog_identity_mismatch",
        findings=findings,
    )
    catalog_sha256 = _sha256_bytes(catalog_bytes) if catalog_bytes is not None else None
    catalog = _parse_json_object(catalog_bytes, "catalog", findings)
    observed_library_identifier = _mapping_string(catalog, "library_id")
    observed_library_version = _mapping_integer(catalog, "library_version")
    if (
        catalog_sha256 != selection.expected_catalog_sha256
        or observed_library_identifier != selection.expected_library_identifier
        or observed_library_version != selection.expected_library_version
    ):
        findings.append(
            _finding(
                "binding.catalog_identity_mismatch",
                "The library catalog does not match the declared trust anchor.",
            )
        )

    records = catalog.get("families") if isinstance(catalog, Mapping) else None
    if not isinstance(records, list) or not all(
        isinstance(item, Mapping) for item in records
    ):
        findings.append(
            _finding(
                "binding.malformed_library_metadata",
                "The library catalog family collection is malformed.",
            )
        )
        records = []
    matches = tuple(
        item
        for item in records
        if item.get("pattern_family_id") == selection.family_identifier
    )
    record = matches[0] if len(matches) == 1 else None
    if record is None:
        findings.append(
            _finding(
                "binding.family_manifest_mismatch",
                "The selected family is missing or ambiguous in the catalog.",
            )
        )

    manifest_reference = (
        _mapping_string(record, "manifest_filename") if record is not None else None
    )
    catalog_manifest_sha256 = (
        _mapping_string(record, "manifest_sha256") if record is not None else None
    )
    expected_manifest_sha256 = (
        selection.expected_family_manifest_sha256 or catalog_manifest_sha256
    )
    if (
        selection.expected_family_manifest_sha256 is not None
        and catalog_manifest_sha256 != selection.expected_family_manifest_sha256
    ):
        findings.append(
            _finding(
                "binding.family_manifest_mismatch",
                "The catalog family-manifest identity differs from the declared selection.",
            )
        )

    manifest_bytes = None
    if manifest_reference is not None:
        manifest_bytes = _read_library_file(
            library_root,
            manifest_reference,
            limits,
            missing_code="binding.family_manifest_mismatch",
            findings=findings,
        )
    manifest_sha256 = (
        _sha256_bytes(manifest_bytes) if manifest_bytes is not None else None
    )
    if manifest_sha256 != expected_manifest_sha256:
        findings.append(
            _finding(
                "binding.family_manifest_mismatch",
                "The selected family manifest bytes do not match their expected identity.",
            )
        )
    manifest = _parse_json_object(manifest_bytes, "family manifest", findings)

    observed_family_identifier = _mapping_string(manifest, "pattern_family_id")
    observed_family_version = _family_version(observed_family_identifier)
    width, height = _resolution(manifest, findings)
    encoding = _mapping_string(manifest, "image_mode")
    support_status = _mapping_string(manifest, "support_status")
    if encoding != "grayscale-8":
        findings.append(
            _finding(
                "binding.dimension_encoding_mismatch",
                "Binding v1 requires the declared grayscale-8 field encoding.",
            )
        )
    if (
        _mapping_string(manifest, "schema_id")
        != "conditioning-layers.influence-field-family-manifest"
        or _mapping_integer(manifest, "schema_version") != 1
        or _mapping_integer(manifest, "library_version")
        != selection.expected_library_version
        or observed_family_identifier != selection.family_identifier
        or observed_family_version != selection.family_version
        or encoding != "grayscale-8"
    ):
        findings.append(
            _finding(
                "binding.malformed_library_metadata",
                "The selected family manifest identity or raster contract is malformed.",
            )
        )

    loaded_fields = _load_fields(
        library_root,
        manifest,
        width,
        height,
        encoding,
        limits,
        findings,
    )
    permutations = _load_permutations(manifest, loaded_fields, findings)
    manifest_layer_count = _mapping_integer(manifest, "layer_count")
    catalog_layer_count = _mapping_integer(record, "layer_count")
    if (
        manifest_layer_count is None
        or manifest_layer_count < 1
        or manifest_layer_count != len(loaded_fields)
        or (
            catalog_layer_count is not None
            and catalog_layer_count != manifest_layer_count
        )
    ):
        findings.append(
            _finding(
                "binding.malformed_library_metadata",
                "The family field count is inconsistent.",
            )
        )

    selected_order = next(
        (
            ordered
            for permutation_id, ordered in permutations
            if permutation_id == selection.permutation_identifier
        ),
        (),
    )
    identity = InfluenceFieldLibraryIdentity(
        expected_library_identifier=selection.expected_library_identifier,
        observed_library_identifier=observed_library_identifier,
        expected_library_version=selection.expected_library_version,
        observed_library_version=observed_library_version,
        catalog_reference=_CATALOG_REFERENCE,
        expected_catalog_sha256=selection.expected_catalog_sha256,
        observed_catalog_sha256=catalog_sha256,
        selected_family_identifier=selection.family_identifier,
        selected_family_version=selection.family_version,
        observed_family_identifier=observed_family_identifier,
        observed_family_version=observed_family_version,
        family_manifest_reference=manifest_reference,
        expected_family_manifest_sha256=expected_manifest_sha256,
        observed_family_manifest_sha256=manifest_sha256,
        permutation_identifier=selection.permutation_identifier,
        ordered_field_ids=selected_order,
        width=width,
        height=height,
        encoding=encoding,
        support_status=support_status,
    )
    return _LoadedFamily(
        identity=identity,
        fields=loaded_fields,
        permutations=permutations,
        findings=_deduplicate_findings(findings),
    )


def _load_fields(
    library_root: str | Path,
    manifest: Mapping[str, object],
    width: int | None,
    height: int | None,
    encoding: str | None,
    limits: InspectionLimits,
    findings: list[ValidationFinding],
) -> tuple[_LoadedField, ...]:
    raw_fields = manifest.get("fields")
    if not isinstance(raw_fields, list) or not all(
        isinstance(item, Mapping) for item in raw_fields
    ):
        findings.append(
            _finding(
                "binding.malformed_library_metadata",
                "The family field collection is malformed.",
            )
        )
        return ()

    loaded: list[_LoadedField] = []
    for ordinal, raw in enumerate(raw_fields):
        asset_id = _mapping_string(raw, "asset_id")
        reference = _mapping_string(raw, "filename")
        expected_sha256 = _mapping_string(raw, "sha256")
        role = _mapping_string(raw, "role")
        if (
            not asset_id
            or not reference
            or not _valid_sha256(expected_sha256)
            or role != "partition-field"
            or width is None
            or height is None
            or encoding != "grayscale-8"
        ):
            findings.append(
                _finding(
                    "binding.malformed_library_metadata",
                    "A family field record is malformed.",
                    field_path=f"fields[{ordinal}]",
                )
            )
            continue
        raw_bytes = _read_library_file(
            library_root,
            reference,
            limits,
            missing_code="binding.unknown_field_id",
            findings=findings,
        )
        observed_sha256 = _sha256_bytes(raw_bytes) if raw_bytes is not None else None
        if observed_sha256 != expected_sha256:
            findings.append(
                _finding(
                    "binding.source_hash_mismatch",
                    "A library field does not match its manifest SHA-256.",
                    field_path=f"fields[{ordinal}].sha256",
                )
            )

        observed_width = observed_height = None
        observed_encoding = None
        if raw_bytes is not None:
            profile = replace(
                PREDICTION_MIXING_EXECUTION_PROFILE,
                expected_field_width=width,
                expected_field_height=height,
            )
            inspection = inspect_field_asset(
                library_root,
                PromptLayer(
                    layer_id=f"library-field-{ordinal}",
                    name=asset_id,
                    prompt_text="Library identity inspection only.",
                    influence_field=InfluenceFieldAssetReference(
                        relative_path=reference,
                        checksum=expected_sha256,
                    ),
                ),
                execution_profile=profile,
                limits=limits,
            )
            if inspection.profile is not None:
                observed_width = inspection.profile.width
                observed_height = inspection.profile.height
                observed_encoding = _portable_encoding(
                    inspection.profile.channel_profile
                )
            if (
                not inspection.certified
                or observed_width != width
                or observed_height != height
                or observed_encoding != encoding
            ):
                findings.append(
                    _finding(
                        "binding.dimension_encoding_mismatch",
                        "A library field does not match the family raster contract.",
                        field_path=f"fields[{ordinal}]",
                    )
                )
        loaded.append(
            _LoadedField(
                asset_id=asset_id,
                reference=_portable_reference(reference),
                expected_sha256=expected_sha256,
                observed_sha256=observed_sha256,
                width=observed_width,
                height=observed_height,
                encoding=observed_encoding,
            )
        )

    if _has_duplicates(tuple(item.asset_id for item in loaded)):
        findings.append(
            _finding(
                "binding.malformed_library_metadata",
                "Library field IDs must be unique.",
            )
        )
    return tuple(loaded)


def _load_permutations(
    manifest: Mapping[str, object],
    loaded_fields: tuple[_LoadedField, ...],
    findings: list[ValidationFinding],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    raw_permutations = manifest.get("assignment_permutations")
    if not isinstance(raw_permutations, list) or not all(
        isinstance(item, Mapping) for item in raw_permutations
    ):
        findings.append(
            _finding(
                "binding.invalid_permutation",
                "The family assignment-permutation collection is malformed.",
            )
        )
        return ()
    field_ids = tuple(item.asset_id for item in loaded_fields)
    permutations: list[tuple[str, tuple[str, ...]]] = []
    for ordinal, raw in enumerate(raw_permutations):
        permutation_id = _mapping_string(raw, "permutation_id")
        ordered = raw.get("ordered_field_ids")
        if not isinstance(ordered, list) or not all(
            isinstance(item, str) and item for item in ordered
        ):
            ordered_ids: tuple[str, ...] = ()
        else:
            ordered_ids = tuple(ordered)
        if (
            not permutation_id
            or len(ordered_ids) != len(field_ids)
            or len(set(ordered_ids)) != len(ordered_ids)
            or set(ordered_ids) != set(field_ids)
        ):
            findings.append(
                _finding(
                    "binding.invalid_permutation",
                    "A family assignment permutation is partial, duplicate, or unknown.",
                    field_path=f"assignment_permutations[{ordinal}]",
                )
            )
        permutations.append((permutation_id or "", ordered_ids))
    if _has_duplicates(tuple(item[0] for item in permutations)):
        findings.append(
            _finding(
                "binding.invalid_permutation",
                "Permutation IDs must be unique within a family.",
            )
        )
    return tuple(permutations)


def _selected_permutation(
    permutations: tuple[tuple[str, tuple[str, ...]], ...],
    selection: InfluenceFieldLibrarySelection,
    findings: list[ValidationFinding],
) -> tuple[str, ...]:
    matches = tuple(
        ordered
        for permutation_id, ordered in permutations
        if permutation_id == selection.permutation_identifier
    )
    if len(matches) != 1:
        findings.append(
            _finding(
                "binding.invalid_permutation",
                "The selected assignment permutation is missing or ambiguous.",
            )
        )
        return ()
    return matches[0]


def _reconcile_certificate(
    certificate: FieldRelationshipCertificate,
    assignments: tuple[InfluenceFieldBindingAssignment, ...],
    library: InfluenceFieldLibraryIdentity,
    findings: list[ValidationFinding],
) -> InfluenceFieldCertificateBinding:
    expected_fingerprint = fingerprint_field_relationship_certificate(certificate)
    fingerprint_valid = certificate.fingerprint == expected_fingerprint
    if not fingerprint_valid:
        findings.append(
            _finding(
                "binding.certificate_fingerprint_mismatch",
                "The relationship certificate fingerprint is invalid.",
            )
        )
    certified = (
        certificate.status is FieldRelationshipCertificationStatus.CERTIFIED
    )
    if not certified:
        findings.append(
            _finding(
                "binding.certificate_uncertified",
                "An uncertified relationship certificate cannot produce a bound result.",
            )
        )
    if (
        certificate.format_identifier != FIELD_RELATIONSHIP_CERTIFICATE_FORMAT
        or certificate.format_version != FIELD_RELATIONSHIP_CERTIFICATE_VERSION
    ):
        findings.append(
            _finding(
                "binding.certificate_fingerprint_mismatch",
                "The relationship certificate format is unsupported.",
            )
        )
    if (
        certificate.relationship_policy_identifier
        != ORDERED_N_WAY_RELATIONSHIP_POLICY_IDENTIFIER
        or certificate.relationship_policy_version
        != ORDERED_N_WAY_RELATIONSHIP_POLICY_VERSION
    ):
        findings.append(
            _finding(
                "binding.certificate_policy_mismatch",
                "The relationship certificate uses a different policy identity.",
            )
        )

    records = certificate.ordered_fields
    order_matches = len(records) == len(assignments) and all(
        record.ordinal == assignment.ordinal
        and record.layer_id == assignment.layer_id
        and record.document_index == assignment.document_index
        and record.portable_reference == assignment.document_field_reference
        for record, assignment in zip(records, assignments, strict=True)
    )
    if not order_matches:
        findings.append(
            _finding(
                "binding.certificate_order_mismatch",
                "Certificate field identities or order differ from document assignments.",
            )
        )
        findings.append(
            _finding(
                "binding.document_order_mismatch",
                "Retained Active Prompt Layer order is not preserved by the certificate.",
            )
        )
    hashes_match = len(records) == len(assignments) and all(
        record.source_sha256 == assignment.expected_library_source_sha256
        and record.source_sha256 == assignment.inspected_document_field_sha256
        for record, assignment in zip(records, assignments, strict=True)
    )
    if not hashes_match:
        findings.append(
            _finding(
                "binding.certificate_field_hash_mismatch",
                "Certificate field hashes differ from the exact assignment bytes.",
            )
        )

    expected_dimensions = (library.width, library.height)
    if any(
        (assignment.width, assignment.height) != expected_dimensions
        or assignment.encoding != library.encoding
        for assignment in assignments
    ):
        findings.append(
            _finding(
                "binding.dimension_encoding_mismatch",
                "Document certificate fields differ from the library raster contract.",
            )
        )
    return InfluenceFieldCertificateBinding(
        format_identifier=certificate.format_identifier,
        format_version=certificate.format_version,
        relationship_policy_identifier=certificate.relationship_policy_identifier,
        relationship_policy_version=certificate.relationship_policy_version,
        fingerprint=certificate.fingerprint,
        fingerprint_valid=fingerprint_valid,
        certified=certified,
        ordered_layer_ids=tuple(item.layer_id for item in records),
        ordered_source_sha256=tuple(item.source_sha256 for item in records),
        order_matches_assignments=order_matches,
        hashes_match_assignments=hashes_match,
    )


def _validate_frozen_spatial_contract(
    certificate: FieldRelationshipCertificate,
) -> tuple[ValidationFinding, ...]:
    findings: list[ValidationFinding] = []
    if certificate.polarity != _FROZEN_POLARITY:
        findings.append(
            _finding(
                "binding.polarity_mismatch",
                "Field polarity must remain 0=no influence and 255=full influence without inversion.",
            )
        )
    orientation = certificate.orientation
    if (
        orientation.origin != _FROZEN_ORIENTATION.origin
        or orientation.positive_x != _FROZEN_ORIENTATION.positive_x
        or orientation.positive_y != _FROZEN_ORIENTATION.positive_y
        or orientation.rotation_degrees != 0
        or orientation.mirrored_x
        or orientation.mirrored_y
    ):
        findings.append(
            _finding(
                "binding.orientation_mismatch",
                "Fields require top-left origin, right/down axes, and no rotation or mirroring.",
            )
        )
    if (
        orientation.resizing != "none"
        or orientation.interpolation != "none"
        or orientation.transformation != "none"
    ):
        findings.append(
            _finding(
                "binding.unsupported_transform",
                "Binding v1 permits no resizing, interpolation, or implicit transform.",
            )
        )
    return tuple(findings)


def _validate_selection(
    selection: InfluenceFieldLibrarySelection,
) -> tuple[ValidationFinding, ...]:
    findings: list[ValidationFinding] = []
    if not _valid_sha256(selection.expected_catalog_sha256):
        findings.append(
            _finding(
                "binding.malformed_library_metadata",
                "The expected catalog SHA-256 is malformed.",
            )
        )
    if (
        selection.expected_family_manifest_sha256 is not None
        and not _valid_sha256(selection.expected_family_manifest_sha256)
    ):
        findings.append(
            _finding(
                "binding.malformed_library_metadata",
                "The expected family-manifest SHA-256 is malformed.",
            )
        )
    for value in (
        selection.family_identifier,
        selection.permutation_identifier,
        selection.expected_library_identifier,
    ):
        if not isinstance(value, str) or not value.strip():
            findings.append(
                _finding(
                    "binding.malformed_library_metadata",
                    "Library selection identifiers must be non-empty strings.",
                )
            )
            break
    for value in (
        selection.family_version,
        selection.expected_library_version,
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            findings.append(
                _finding(
                    "binding.malformed_library_metadata",
                    "Library and family versions must be positive integers.",
                )
            )
            break
    return tuple(findings)


def _validate_target(
    target: InfluenceFieldBindingTarget,
    document: ConditioningDocument,
) -> tuple[ValidationFinding, ...]:
    findings: list[ValidationFinding] = []
    values = (
        target.adapter_identifier,
        target.backend_identifier,
        target.condition_kind,
        target.translation_contract_identifier,
        target.topology_policy_identifier,
    )
    if any(not isinstance(value, str) or not value.strip() for value in values) or (
        target.runtime_profile_identifier is not None
        and (
            not isinstance(target.runtime_profile_identifier, str)
            or not target.runtime_profile_identifier.strip()
        )
    ):
        findings.append(
            _finding(
                "binding.malformed_library_metadata",
                "Binding target identifiers must be non-empty strings.",
            )
        )
    if (
        target.adapter_identifier != PREDICTION_MIXING_ADAPTER_ID
        or target.backend_identifier
        != PREDICTION_MIXING_BINDING_BACKEND_IDENTIFIER
        or target.condition_kind != HOMOGENEOUS_PROMPT_LAYER_CONDITION_KIND
        or document.selected_adapter_id != target.adapter_identifier
    ):
        findings.append(
            _finding(
                "binding.target_adapter_mismatch",
                "Binding v1 targets homogeneous Prompt Layers through Prediction Mixing only.",
            )
        )
    return tuple(findings)


def _read_library_file(
    library_root: str | Path,
    reference: str,
    limits: InspectionLimits,
    *,
    missing_code: str,
    findings: list[ValidationFinding],
) -> bytes | None:
    try:
        normalized = normalize_asset_reference(reference)
    except AssetPathError:
        findings.append(
            _finding(
                "binding.reference_non_portable",
                "Library references must be portable library-root-relative paths.",
            )
        )
        return None
    root = Path(library_root)
    candidate = root.joinpath(*normalized.split("/"))
    try:
        resolved_root = root.resolve(strict=False)
        resolved_candidate = candidate.resolve(strict=False)
        if not resolved_candidate.is_relative_to(resolved_root):
            findings.append(
                _finding(
                    "binding.reference_non_portable",
                    "A resolved library reference escapes the supplied library root.",
                )
            )
            return None
        if not candidate.is_file():
            findings.append(
                _finding(missing_code, "A required library artifact is missing.")
            )
            return None
        size = candidate.stat().st_size
        if size > limits.maximum_file_bytes:
            findings.append(
                _finding(
                    "binding.malformed_library_metadata",
                    "A library artifact exceeds the bounded read limit.",
                )
            )
            return None
        return candidate.read_bytes()
    except OSError:
        findings.append(
            _finding(missing_code, "A required library artifact could not be read.")
        )
        return None


def _parse_json_object(
    data: bytes | None,
    label: str,
    findings: list[ValidationFinding],
) -> Mapping[str, object]:
    if data is None:
        return {}
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=lambda value: (_raise_json_value(value)),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        findings.append(
            _finding(
                "binding.malformed_library_metadata",
                f"The {label} is not deterministic UTF-8 JSON metadata.",
            )
        )
        return {}
    if not isinstance(value, Mapping):
        findings.append(
            _finding(
                "binding.malformed_library_metadata",
                f"The {label} must be a JSON object.",
            )
        )
        return {}
    return value


def _unique_object(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _raise_json_value(value: str) -> object:
    raise ValueError(f"unsupported JSON constant: {value}")


def _resolution(
    manifest: Mapping[str, object],
    findings: list[ValidationFinding],
) -> tuple[int | None, int | None]:
    resolution = manifest.get("resolution")
    width = _mapping_integer(resolution, "width")
    height = _mapping_integer(resolution, "height")
    if width is None or height is None or width < 1 or height < 1:
        findings.append(
            _finding(
                "binding.malformed_library_metadata",
                "The family resolution is malformed.",
            )
        )
        return None, None
    return width, height


def _mapping_string(value: object, key: str) -> str | None:
    if not isinstance(value, Mapping):
        return None
    item = value.get(key)
    return item if isinstance(item, str) and item else None


def _mapping_integer(value: object, key: str) -> int | None:
    if not isinstance(value, Mapping):
        return None
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int):
        return None
    return item


def _family_version(value: str | None) -> int | None:
    match = _FAMILY_VERSION_PATTERN.search(value or "")
    return int(match.group(1)) if match is not None else None


def _portable_reference(value: str) -> str:
    try:
        return normalize_asset_reference(value)
    except AssetPathError:
        return ""


def _portable_encoding(value: InspectedChannelProfile | None) -> str | None:
    if value is InspectedChannelProfile.GRAYSCALE_8:
        return "grayscale-8"
    if value is InspectedChannelProfile.RGB_IDENTICAL_8:
        return "rgb-identical-8"
    return None


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_PATTERN.fullmatch(value) is not None


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _has_duplicates(values: tuple[str, ...]) -> bool:
    return len(values) != len(set(values))


def _deduplicate_findings(
    findings: Sequence[ValidationFinding],
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


def _finding(
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


def _portable(value: object) -> object:
    if is_dataclass(value):
        return {
            item.name: _portable(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple | list):
        return [_portable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _portable(item) for key, item in value.items()}
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise TypeError(f"unsupported binding value: {type(value)!r}")


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        _portable(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
