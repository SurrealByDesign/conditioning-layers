"""Policy-bearing neutral document projection; no backend consumes v2 yet.

The retained document-execution-projection.v1 and its production consumers
remain unchanged. A v2 projection identifies semantic intent, including Blend,
without asserting admission, field certification or backend realizability.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass, replace

from .canonical import canonical_json_bytes, canonical_json_text, sha256_canonical
from .composition_policy import CompositionPolicyReference
from .models import (
    ConditioningDocument,
    InfluenceFieldAssetReference,
    get_effective_composition_policy,
)
from .validation import FindingSeverity, validate_document


DOCUMENT_EXECUTION_PROJECTION_IDENTIFIER = (
    "conditioning-layers.document-execution-projection.v2"
)
DOCUMENT_EXECUTION_PROJECTION_VERSION = 2


@dataclass(frozen=True, slots=True)
class DocumentExecutionLayer:
    """One Active Prompt Layer; relative order carries no visual priority."""

    active_ordinal: int
    layer_id: str
    prompt_text: str
    requested_strength: float
    influence_field_reference: str
    declared_field_sha256: str | None


@dataclass(frozen=True, slots=True)
class DocumentExecutionProjection:
    """Immutable semantic projection with an explicit, reviewed policy reference."""

    format_identifier: str
    format_version: int
    source_document_major_version: int
    source_document_minor_version: int
    selected_adapter_identifier: str | None
    canonical_adapter_settings_json: str
    base_prompt_text: str
    active_layers: tuple[DocumentExecutionLayer, ...]
    composition_policy: CompositionPolicyReference
    fingerprint: str


def build_document_execution_projection(
    document: ConditioningDocument,
) -> DocumentExecutionProjection:
    """Project valid known intent without selecting an executable route."""

    if not isinstance(document, ConditioningDocument):
        raise TypeError("document must be a ConditioningDocument")
    errors = tuple(
        finding for finding in validate_document(document)
        if finding.severity is FindingSeverity.ERROR
    )
    if errors:
        raise ValueError("document cannot be projected: " + ", ".join(
            finding.code for finding in errors
        ))
    policy = get_effective_composition_policy(document)
    projected_layers = []
    for layer in document.active_layers:
        reference = layer.influence_field
        if not isinstance(reference, InfluenceFieldAssetReference):
            raise ValueError("document cannot be projected: active field reference required")
        projected_layers.append(DocumentExecutionLayer(
            active_ordinal=len(projected_layers),
            layer_id=layer.layer_id,
            prompt_text=layer.prompt_text,
            requested_strength=float(layer.strength),
            influence_field_reference=reference.relative_path.replace("\\", "/"),
            declared_field_sha256=(
                reference.checksum.lower() if reference.checksum is not None else None
            ),
        ))
    projection = DocumentExecutionProjection(
        format_identifier=DOCUMENT_EXECUTION_PROJECTION_IDENTIFIER,
        format_version=DOCUMENT_EXECUTION_PROJECTION_VERSION,
        source_document_major_version=document.version.major,
        source_document_minor_version=document.version.minor,
        selected_adapter_identifier=document.selected_adapter_id,
        canonical_adapter_settings_json=canonical_json_text(dict(document.adapter_settings)),
        base_prompt_text=document.base_prompt,
        active_layers=tuple(projected_layers),
        composition_policy=policy.reference,
        fingerprint="",
    )
    return replace(projection, fingerprint=fingerprint_document_execution_projection(projection))


def fingerprint_document_execution_projection(
    projection: DocumentExecutionProjection,
) -> str:
    """Hash canonical content, excluding only the recorded fingerprint."""

    if type(projection) is not DocumentExecutionProjection:
        raise TypeError("projection must be a DocumentExecutionProjection")
    return sha256_canonical({
        item.name: getattr(projection, item.name)
        for item in fields(projection) if item.name != "fingerprint"
    })


def serialize_document_execution_projection(
    projection: DocumentExecutionProjection,
) -> bytes:
    if type(projection) is not DocumentExecutionProjection:
        raise TypeError("projection must be a DocumentExecutionProjection")
    return canonical_json_bytes(projection)


def verify_document_execution_projection(
    projection: DocumentExecutionProjection,
    document: ConditioningDocument,
) -> None:
    """Rebuild from source intent; a caller-supplied digest proves nothing."""

    expected = build_document_execution_projection(document)
    if not _same_representation(projection, expected):
        raise ValueError("document execution projection does not match source intent")


def _same_representation(value: object, expected: object) -> bool:
    if type(value) is not type(expected):
        return False
    if is_dataclass(expected):
        return all(_same_representation(
            getattr(value, item.name), getattr(expected, item.name)
        ) for item in fields(expected))
    if isinstance(expected, tuple):
        return len(value) == len(expected) and all(
            _same_representation(item, other) for item, other in zip(value, expected)
        )
    return value == expected
