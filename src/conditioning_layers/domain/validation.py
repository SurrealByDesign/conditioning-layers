"""Structured validation for backend-neutral document intent.

Validation never accesses assets, evaluates an adapter capability, or executes a
backend. Adapter-specific eligibility belongs to the capability layer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
import math
from pathlib import PurePosixPath, PureWindowsPath
import re

from .composition_policy import CompositionPolicyError
from .models import (
    COMPOSITION_POLICY_PROTOTYPE_VERSION,
    CURRENT_PROTOTYPE_VERSION,
    ConditioningDocument,
    InfluenceFieldAssetReference,
    PromptLayer,
    PrototypeDocumentVersion,
    get_effective_composition_policy,
)


PREDICTION_MIXING_ADAPTER_ID = "prediction-mixing.experimental.v1"
_ADAPTER_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_CHECKSUM_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_URI_SCHEME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


class FindingSeverity(str, Enum):
    """Small severity vocabulary for actionable prototype findings."""

    ERROR = "error"
    WARNING = "warning"
    INFORMATION = "information"


@dataclass(frozen=True, slots=True)
class ValidationFinding:
    """One stable, structured validation result."""

    code: str
    severity: FindingSeverity
    message: str
    layer_id: str | None = None
    field_path: str | None = None


def validate_document(document: ConditioningDocument) -> tuple[ValidationFinding, ...]:
    """Return every detectable backend-neutral document finding."""

    if not isinstance(document, ConditioningDocument):
        raise TypeError("validate_document requires a ConditioningDocument")

    findings: list[ValidationFinding] = []
    findings.extend(_validate_version(document.version))
    if (
        (
            type(document.version) is PrototypeDocumentVersion
            and type(document.version.major) is int
            and type(document.version.minor) is int
            and document.version == COMPOSITION_POLICY_PROTOTYPE_VERSION
        )
        or document.composition_policy is not None
    ):
        try:
            get_effective_composition_policy(document)
        except CompositionPolicyError as error:
            findings.append(
                _error(error.code, str(error), field_path="composition_policy")
            )

    if not isinstance(document.document_id, str) or not document.document_id.strip():
        findings.append(
            _error(
                "document.id.invalid",
                "Document ID must be a non-empty opaque string.",
                field_path="document_id",
            )
        )

    if not isinstance(document.base_prompt, str):
        findings.append(
            _error(
                "document.base_prompt.invalid_type",
                "Base Prompt must be text.",
                field_path="base_prompt",
            )
        )
    elif not document.base_prompt.strip():
        findings.append(
            _error(
                "document.base_prompt.empty",
                "Base Prompt must not be empty.",
                field_path="base_prompt",
            )
        )

    if not isinstance(document.layers, tuple):
        findings.append(
            _error(
                "document.layers.invalid_type",
                "Prompt Layers must be an ordered collection.",
                field_path="layers",
            )
        )
    else:
        findings.extend(_validate_layers(document.layers))

    findings.extend(_validate_adapter_selection(document.selected_adapter_id))
    findings.extend(_validate_adapter_settings(document.adapter_settings))
    return tuple(findings)


def _validate_version(version: object) -> list[ValidationFinding]:
    if not isinstance(version, PrototypeDocumentVersion):
        return [
            _error(
                "document.version.invalid_type",
                "Prototype document version must contain major and minor integers.",
                field_path="version",
            )
        ]

    if (
        isinstance(version.major, bool)
        or not isinstance(version.major, int)
        or isinstance(version.minor, bool)
        or not isinstance(version.minor, int)
        or version.major < 0
        or version.minor < 0
    ):
        return [
            _error(
                "document.version.invalid",
                "Prototype document major and minor versions must be non-negative integers.",
                field_path="version",
            )
        ]

    if (
        type(version) is PrototypeDocumentVersion
        and type(version.major) is int
        and type(version.minor) is int
        and version == COMPOSITION_POLICY_PROTOTYPE_VERSION
    ):
        return []

    if version.major != CURRENT_PROTOTYPE_VERSION.major:
        return [
            _error(
                "document.version.unsupported_major",
                f"Prototype document major version {version.major} is unsupported.",
                field_path="version.major",
            )
        ]

    if version.minor > CURRENT_PROTOTYPE_VERSION.minor:
        return [
            ValidationFinding(
                code="document.version.newer_minor",
                severity=FindingSeverity.WARNING,
                message=(
                    f"Prototype document minor version {version.minor} is newer than "
                    f"supported minor version {CURRENT_PROTOTYPE_VERSION.minor}."
                ),
                field_path="version.minor",
            )
        ]
    return []


def _validate_layers(layers: tuple[object, ...]) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    seen_ids: set[str] = set()
    for index, layer in enumerate(layers):
        path = f"layers[{index}]"
        if not isinstance(layer, PromptLayer):
            findings.append(
                _error(
                    "layer.invalid_type",
                    "Every layer entry must be a Prompt Layer.",
                    field_path=path,
                )
            )
            continue

        layer_id = layer.layer_id if isinstance(layer.layer_id, str) else None
        if layer_id is None or not layer_id.strip():
            findings.append(
                _error(
                    "layer.id.invalid",
                    "Layer ID must be a non-empty opaque string.",
                    layer_id=layer_id,
                    field_path=f"{path}.layer_id",
                )
            )
        elif layer_id in seen_ids:
            findings.append(
                _error(
                    "layer.id.duplicate",
                    "Layer IDs must be unique within a Conditioning Document.",
                    layer_id=layer_id,
                    field_path=f"{path}.layer_id",
                )
            )
        else:
            seen_ids.add(layer_id)

        if not isinstance(layer.name, str):
            findings.append(
                _error(
                    "layer.name.invalid_type",
                    "Layer name must be text.",
                    layer_id=layer_id,
                    field_path=f"{path}.name",
                )
            )
        elif not layer.name.strip():
            findings.append(
                _error(
                    "layer.name.empty",
                    "Layer name must not be empty.",
                    layer_id=layer_id,
                    field_path=f"{path}.name",
                )
            )

        if not isinstance(layer.prompt_text, str):
            findings.append(
                _error(
                    "layer.prompt.invalid_type",
                    "Prompt Layer prompt must be text.",
                    layer_id=layer_id,
                    field_path=f"{path}.prompt_text",
                )
            )
        elif not layer.prompt_text.strip():
            findings.append(
                _error(
                    "layer.prompt.empty",
                    "Prompt Layer prompt must not be empty.",
                    layer_id=layer_id,
                    field_path=f"{path}.prompt_text",
                )
            )

        if not isinstance(layer.visible, bool):
            findings.append(
                _error(
                    "layer.visibility.invalid_type",
                    "Visibility must be a boolean value.",
                    layer_id=layer_id,
                    field_path=f"{path}.visible",
                )
            )

        findings.extend(_validate_strength(layer.strength, layer_id, path))
        findings.extend(_validate_influence_field(layer.influence_field, layer_id, path))
    return findings


def _validate_strength(
    strength: object,
    layer_id: str | None,
    layer_path: str,
) -> list[ValidationFinding]:
    path = f"{layer_path}.strength"
    if isinstance(strength, bool) or not isinstance(strength, (int, float)):
        return [
            _error(
                "layer.strength.invalid_type",
                "Strength must be a finite number from 0.0 through 1.0.",
                layer_id=layer_id,
                field_path=path,
            )
        ]
    if not math.isfinite(strength):
        return [
            _error(
                "layer.strength.non_finite",
                "Strength must be finite.",
                layer_id=layer_id,
                field_path=path,
            )
        ]
    if not 0.0 <= strength <= 1.0:
        return [
            _error(
                "layer.strength.out_of_range",
                "Strength must be from 0.0 through 1.0.",
                layer_id=layer_id,
                field_path=path,
            )
        ]
    return []


def _validate_influence_field(
    reference: object,
    layer_id: str | None,
    layer_path: str,
) -> list[ValidationFinding]:
    if reference is None:
        return []
    if not isinstance(reference, InfluenceFieldAssetReference):
        return [
            _error(
                "influence_field.invalid_type",
                "Influence Field reference must use asset-reference metadata.",
                layer_id=layer_id,
                field_path=f"{layer_path}.influence_field",
            )
        ]

    findings = _validate_asset_path(
        reference.relative_path,
        layer_id,
        f"{layer_path}.influence_field.relative_path",
    )
    checksum = reference.checksum
    if checksum is not None:
        if not isinstance(checksum, str):
            findings.append(
                _error(
                    "influence_field.checksum.invalid_type",
                    "Influence Field checksum must be text when supplied.",
                    layer_id=layer_id,
                    field_path=f"{layer_path}.influence_field.checksum",
                )
            )
        elif not _CHECKSUM_PATTERN.fullmatch(checksum):
            findings.append(
                _error(
                    "influence_field.checksum.invalid_format",
                    "Influence Field checksum must be a 64-character SHA-256 hex digest.",
                    layer_id=layer_id,
                    field_path=f"{layer_path}.influence_field.checksum",
                )
            )
    return findings


def _validate_asset_path(
    path: object,
    layer_id: str | None,
    field_path: str,
) -> list[ValidationFinding]:
    if not isinstance(path, str):
        return [
            _error(
                "influence_field.path.invalid_type",
                "Influence Field asset path must be text.",
                layer_id=layer_id,
                field_path=field_path,
            )
        ]
    if not path.strip():
        return [
            _error(
                "influence_field.path.empty",
                "Influence Field asset path must not be empty.",
                layer_id=layer_id,
                field_path=field_path,
            )
        ]

    windows_path = PureWindowsPath(path)
    posix_path = PurePosixPath(path)
    segments = re.split(r"[\\/]", path)
    unsafe = (
        "\x00" in path
        or _URI_SCHEME_PATTERN.match(path) is not None
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or posix_path.is_absolute()
        or any(segment in {"", ".", ".."} for segment in segments)
    )
    if unsafe:
        return [
            _error(
                "influence_field.path.unsafe",
                "Influence Field asset path must be a normalized document-relative path.",
                layer_id=layer_id,
                field_path=field_path,
            )
        ]
    return []


def _validate_adapter_selection(adapter_id: object) -> list[ValidationFinding]:
    if adapter_id is None:
        return []
    if not isinstance(adapter_id, str):
        return [
            _error(
                "adapter.id.invalid_type",
                "Selected adapter identifier must be text when supplied.",
                field_path="selected_adapter_id",
            )
        ]
    if not _ADAPTER_ID_PATTERN.fullmatch(adapter_id):
        return [
            _error(
                "adapter.id.malformed",
                "Selected adapter identifier has an invalid form.",
                field_path="selected_adapter_id",
            )
        ]
    return []


def _validate_adapter_settings(settings: object) -> list[ValidationFinding]:
    if not isinstance(settings, Mapping):
        return [
            _error(
                "adapter.settings.invalid_type",
                "Adapter settings must be a separate mapping.",
                field_path="adapter_settings",
            )
        ]
    if any(not isinstance(key, str) or not key.strip() for key in settings):
        return [
            _error(
                "adapter.settings.invalid_key",
                "Adapter setting keys must be non-empty strings.",
                field_path="adapter_settings",
            )
        ]
    if "composition_policy" in settings:
        return [
            _error(
                "composition_policy.invalid_location",
                "Composition Policy belongs to the document, not adapter settings.",
                field_path="adapter_settings.composition_policy",
            )
        ]
    return []


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
