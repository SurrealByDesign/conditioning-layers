"""Canonical prototype JSON encoding, decoding, and atomic file operations."""

from __future__ import annotations

from collections.abc import Mapping
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

from conditioning_layers.capabilities import evaluate_prediction_mixing
from conditioning_layers.domain import (
    COMPOSITION_POLICY_PROTOTYPE_VERSION,
    CURRENT_PROTOTYPE_VERSION,
    ConditioningDocument,
    CompositionPolicyError,
    CompositionPolicyReference,
    FindingSeverity,
    InfluenceFieldAssetReference,
    PromptLayer,
    PrototypeDocumentVersion,
    ValidationFinding,
    resolve_composition_policy,
    validate_document,
)

from .errors import (
    AssetPathError,
    DocumentEncodeError,
    DocumentIOError,
    LoadResult,
    PersistenceFinding,
)
from .migrations import (
    COMPOSITION_POLICY_FORMAT_VERSION,
    CURRENT_FORMAT_VERSION,
    PrototypeFormatVersion,
    dispatch_migration,
)
from .paths import normalize_asset_reference


PROTOTYPE_FORMAT_ID = "conditioning-layers.prototype-document"
MAX_ADAPTER_SETTINGS_DEPTH = 32

_TOP_LEVEL_KEYS = {"format", "format_version", "document"}
_VERSION_KEYS = {"major", "minor"}
_DOCUMENT_KEYS = {"version", "id", "base_prompt", "layers", "adapter"}
_POLICY_DOCUMENT_KEYS = _DOCUMENT_KEYS | {"composition_policy"}
_COMPOSITION_POLICY_KEYS = {"policy_identifier", "policy_version"}
_ADAPTER_KEYS = {"id", "settings"}
_LAYER_KEYS = {
    "id",
    "name",
    "prompt",
    "visible",
    "strength",
    "influence_field",
}
_INFLUENCE_FIELD_KEYS = {"path", "sha256"}


class _DuplicateJsonKeyError(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


class _NonFiniteJsonNumberError(Exception):
    def __init__(self, value: str) -> None:
        super().__init__(value)
        self.value = value


def encode_document(document: ConditioningDocument) -> str:
    """Encode a valid document as deterministic, readable prototype JSON.

    Output uses UTF-8-compatible Unicode text, sorted keys, two-space indentation,
    explicit booleans/nulls, finite numbers only, and exactly one trailing newline.
    """

    if not isinstance(document, ConditioningDocument):
        raise TypeError("encode_document requires a ConditioningDocument")

    domain_findings = validate_document(document)
    blocking: list[object] = [
        finding
        for finding in domain_findings
        if finding.severity is FindingSeverity.ERROR
    ]
    if document.version not in (
        CURRENT_PROTOTYPE_VERSION,
        COMPOSITION_POLICY_PROTOTYPE_VERSION,
    ):
        blocking.append(
            _error(
                "document.version.unsupported_for_save",
                "Only supported domain document versions may be saved.",
                "$.document.version",
            )
        )

    settings_ok, settings, settings_findings = _normalize_json_value(
        document.adapter_settings,
        "$.document.adapter.settings",
    )
    blocking.extend(
        finding
        for finding in settings_findings
        if finding.severity is FindingSeverity.ERROR
    )

    encoded_layers: list[dict[str, Any]] = []
    if not blocking:
        for index, layer in enumerate(document.layers):
            encoded, findings = _encode_layer(layer, index)
            blocking.extend(findings)
            if encoded is not None:
                encoded_layers.append(encoded)

    if blocking or not settings_ok:
        raise DocumentEncodeError(tuple(blocking))

    payload = {
        "document": {
            "adapter": {
                "id": document.selected_adapter_id,
                "settings": settings,
            },
            "base_prompt": document.base_prompt,
            "id": document.document_id,
            "layers": encoded_layers,
            "version": _version_object(document.version.major, document.version.minor),
        },
        "format": PROTOTYPE_FORMAT_ID,
        "format_version": _version_object(
            CURRENT_FORMAT_VERSION.major,
            CURRENT_FORMAT_VERSION.minor,
        ),
    }
    if document.version == COMPOSITION_POLICY_PROTOTYPE_VERSION:
        assert document.composition_policy is not None
        payload["document"]["composition_policy"] = {
            "policy_identifier": document.composition_policy.policy_identifier,
            "policy_version": document.composition_policy.policy_version,
        }
        payload["format_version"] = _version_object(
            COMPOSITION_POLICY_FORMAT_VERSION.major,
            COMPOSITION_POLICY_FORMAT_VERSION.minor,
        )
    return (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def decode_document(
    text: str,
    *,
    include_adapter_capability_findings: bool = False,
) -> LoadResult:
    """Decode user-authored JSON without raising for malformed file content."""

    if not isinstance(text, str):
        raise TypeError("decode_document requires text")

    try:
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_json_number,
        )
    except _DuplicateJsonKeyError as error:
        return LoadResult(
            document=None,
            persistence_findings=(
                _error(
                    "json.duplicate_key",
                    f"Duplicate JSON key is not allowed: {error.key!r}.",
                    "$",
                ),
            ),
        )
    except _NonFiniteJsonNumberError as error:
        return LoadResult(
            document=None,
            persistence_findings=(
                _error(
                    "json.number.non_finite",
                    f"Non-finite JSON number is not allowed: {error.value}.",
                    "$",
                ),
            ),
        )
    except json.JSONDecodeError as error:
        return LoadResult(
            document=None,
            persistence_findings=(
                _error(
                    "json.syntax.invalid",
                    f"Invalid JSON at line {error.lineno}, column {error.colno}.",
                    "$",
                ),
            ),
        )
    except RecursionError:
        return LoadResult(
            document=None,
            persistence_findings=(
                _error(
                    "json.nesting.too_deep",
                    "JSON nesting exceeds the interpreter's safe parsing depth.",
                    "$",
                ),
            ),
        )

    if not isinstance(payload, dict):
        return LoadResult(
            document=None,
            persistence_findings=(
                _error(
                    "json.root.invalid_type",
                    "Prototype document JSON root must be an object.",
                    "$",
                ),
            ),
        )

    findings: list[PersistenceFinding] = []
    findings.extend(_unknown_field_warnings(payload, _TOP_LEVEL_KEYS, "$"))

    format_id = payload.get("format", _MISSING)
    if format_id is _MISSING:
        findings.append(_missing("$.format"))
    elif not isinstance(format_id, str):
        findings.append(_wrong_type("$.format", "string"))
    elif format_id != PROTOTYPE_FORMAT_ID:
        findings.append(
            _error(
                "format.identifier.unsupported",
                f"Unsupported prototype format identifier: {format_id!r}.",
                "$.format",
            )
        )

    format_version = _decode_format_version(
        payload.get("format_version", _MISSING),
        findings,
    )
    if format_version is not None:
        decision = dispatch_migration(format_version)
        findings.extend(decision.findings)

    document_payload = payload.get("document", _MISSING)
    document: ConditioningDocument | None = None
    if document_payload is _MISSING:
        findings.append(_missing("$.document"))
    elif not isinstance(document_payload, dict):
        findings.append(_wrong_type("$.document", "object"))
    elif not _has_errors(findings):
        assert format_version is not None
        document = _decode_document_object(document_payload, format_version, findings)

    domain_findings = validate_document(document) if document is not None else ()
    capability_findings: tuple[ValidationFinding, ...] = ()
    if document is not None and include_adapter_capability_findings:
        capability_evaluation = evaluate_prediction_mixing(document)
        capability_findings = capability_evaluation.errors + tuple(
            finding
            for finding in capability_evaluation.warnings
            if finding.code == "capability.zero_strength_active"
        )
    return LoadResult(
        document=document,
        persistence_findings=tuple(findings),
        domain_findings=domain_findings,
        capability_findings=capability_findings,
    )


def save_document(
    document: ConditioningDocument,
    path: str | Path,
    *,
    overwrite: bool = False,
    create_parents: bool = False,
) -> None:
    """Validate and atomically publish a UTF-8 prototype document file.

    With overwrite disabled, an atomic hard-link publication prevents replacing
    a destination that appears concurrently. With overwrite enabled, ``os.replace``
    atomically replaces the destination. Referenced assets are never touched.
    """

    encoded = encode_document(document)
    destination = Path(path)
    parent = destination.parent

    if not parent.exists():
        if not create_parents:
            raise DocumentIOError(
                "io.parent_missing",
                "Destination parent directory does not exist.",
                str(destination),
            )
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise DocumentIOError(
                "io.parent_create_failed",
                f"Could not create destination parent directory: {error}.",
                str(destination),
            ) from error

    if destination.exists() and not overwrite:
        raise DocumentIOError(
            "io.destination_exists",
            "Destination exists and overwrite was not enabled.",
            str(destination),
        )

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())

        if overwrite:
            os.replace(temporary_path, destination)
            temporary_path = None
        else:
            try:
                os.link(temporary_path, destination)
            except FileExistsError as error:
                raise DocumentIOError(
                    "io.destination_exists",
                    "Destination exists and overwrite was not enabled.",
                    str(destination),
                ) from error
            temporary_path.unlink()
            temporary_path = None
    except DocumentIOError:
        raise
    except OSError as error:
        raise DocumentIOError(
            "io.write_failed",
            f"Atomic document write failed: {error}.",
            str(destination),
        ) from error
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def load_document(
    path: str | Path,
    *,
    include_adapter_capability_findings: bool = False,
) -> LoadResult:
    """Read a UTF-8 document file and return normal structured diagnostics."""

    source = Path(path)
    try:
        data = source.read_bytes()
    except OSError as error:
        return LoadResult(
            document=None,
            persistence_findings=(
                _error(
                    "io.read_failed",
                    f"Could not read prototype document: {error}.",
                    "$",
                ),
            ),
        )

    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        return LoadResult(
            document=None,
            persistence_findings=(
                _error(
                    "io.invalid_utf8",
                    f"Prototype document is not valid UTF-8 at byte {error.start}.",
                    "$",
                ),
            ),
        )
    return decode_document(
        text,
        include_adapter_capability_findings=include_adapter_capability_findings,
    )


_MISSING = object()


def _encode_layer(
    layer: PromptLayer,
    index: int,
) -> tuple[dict[str, Any] | None, list[PersistenceFinding]]:
    findings: list[PersistenceFinding] = []
    influence_field: dict[str, Any] | None = None
    if layer.influence_field is not None:
        try:
            normalized_path = normalize_asset_reference(
                layer.influence_field.relative_path
            )
        except AssetPathError as error:
            findings.append(
                _error(
                    error.code,
                    str(error),
                    f"$.document.layers[{index}].influence_field.path",
                    layer.layer_id,
                )
            )
        else:
            influence_field = {
                "path": normalized_path,
                "sha256": layer.influence_field.checksum,
            }

    if findings:
        return None, findings
    return (
        {
            "id": layer.layer_id,
            "influence_field": influence_field,
            "name": layer.name,
            "prompt": layer.prompt_text,
            "strength": float(layer.strength),
            "visible": layer.visible,
        },
        findings,
    )


def _decode_document_object(
    payload: dict[str, Any],
    format_version: PrototypeFormatVersion,
    findings: list[PersistenceFinding],
) -> ConditioningDocument | None:
    start = len(findings)
    policy_format = format_version == COMPOSITION_POLICY_FORMAT_VERSION
    findings.extend(_unknown_field_warnings(payload, _POLICY_DOCUMENT_KEYS, "$.document"))

    version = _decode_domain_version(payload.get("version", _MISSING), findings)
    composition_policy = None
    if policy_format:
        composition_policy = _decode_composition_policy(
            payload.get("composition_policy", _MISSING), findings
        )
        if version is not None and version != COMPOSITION_POLICY_PROTOTYPE_VERSION:
            findings.append(
                _error(
                    "composition_policy.document_version.mismatch",
                    "Composition Policy format 2.0 requires domain document version 2.0.",
                    "$.document.version",
                )
            )
    elif "composition_policy" in payload:
        findings.append(
            _error(
                "composition_policy.legacy_explicit",
                "Explicit Composition Policy requires document format 2.0; it cannot be discarded.",
                "$.document.composition_policy",
            )
        )
    elif version == COMPOSITION_POLICY_PROTOTYPE_VERSION:
        findings.append(
            _error(
                "composition_policy.document_version.mismatch",
                "Domain document version 2.0 requires Composition Policy format 2.0.",
                "$.document.version",
            )
        )
    document_id = _required_string(payload, "id", "$.document.id", findings)
    base_prompt = _required_string(
        payload,
        "base_prompt",
        "$.document.base_prompt",
        findings,
    )
    layers = _decode_layers(payload.get("layers", _MISSING), findings)
    adapter_id, adapter_settings = _decode_adapter(
        payload.get("adapter", _MISSING),
        findings,
    )

    if _has_errors(findings[start:]):
        return None
    assert version is not None
    assert document_id is not None
    assert base_prompt is not None
    assert layers is not None
    return ConditioningDocument(
        version=version,
        document_id=document_id,
        base_prompt=base_prompt,
        layers=tuple(layers),
        selected_adapter_id=adapter_id,
        adapter_settings=adapter_settings,
        composition_policy=composition_policy,
    )


def _decode_composition_policy(
    value: object,
    findings: list[PersistenceFinding],
) -> CompositionPolicyReference | None:
    path = "$.document.composition_policy"
    if value is _MISSING:
        findings.append(
            _error(
                "composition_policy.required",
                "Document format 2.0 requires an explicit Composition Policy.",
                path,
            )
        )
        return None
    if not isinstance(value, dict):
        findings.append(
            _error(
                "composition_policy.invalid_representation",
                "Composition Policy must be an object containing only policy_identifier and policy_version.",
                path,
            )
        )
        return None
    if set(value) != _COMPOSITION_POLICY_KEYS:
        findings.append(
            _error(
                "composition_policy.invalid_representation",
                "Composition Policy requires exactly policy_identifier and policy_version; parameters and unknown fields are unsupported.",
                path,
            )
        )
        return None
    reference = CompositionPolicyReference(
        policy_identifier=value["policy_identifier"],
        policy_version=value["policy_version"],
    )
    try:
        resolve_composition_policy(reference)
    except CompositionPolicyError as error:
        findings.append(_error(error.code, str(error), path))
        return None
    return reference


def _decode_layers(
    value: object,
    findings: list[PersistenceFinding],
) -> list[PromptLayer] | None:
    if value is _MISSING:
        findings.append(_missing("$.document.layers"))
        return None
    if not isinstance(value, list):
        findings.append(_wrong_type("$.document.layers", "array"))
        return None

    layers: list[PromptLayer] = []
    failed = False
    for index, item in enumerate(value):
        layer = _decode_layer(item, index, findings)
        if layer is None:
            failed = True
        else:
            layers.append(layer)
    return None if failed else layers


def _decode_layer(
    value: object,
    index: int,
    findings: list[PersistenceFinding],
) -> PromptLayer | None:
    path = f"$.document.layers[{index}]"
    if not isinstance(value, dict):
        findings.append(_wrong_type(path, "object"))
        return None

    layer_id_value = value.get("id", _MISSING)
    layer_id = layer_id_value if isinstance(layer_id_value, str) else None
    findings.extend(
        _unknown_field_warnings(value, _LAYER_KEYS, path, layer_id=layer_id)
    )
    start = len(findings)

    layer_id = _required_string(value, "id", f"{path}.id", findings)
    name = _required_string(value, "name", f"{path}.name", findings)
    prompt = _required_string(value, "prompt", f"{path}.prompt", findings)

    visible_value = value.get("visible", _MISSING)
    visible: bool | None = None
    if visible_value is _MISSING:
        findings.append(_missing(f"{path}.visible", layer_id))
    elif not isinstance(visible_value, bool):
        findings.append(_wrong_type(f"{path}.visible", "boolean", layer_id))
    else:
        visible = visible_value

    strength_value = value.get("strength", _MISSING)
    strength: float | int | None = None
    if strength_value is _MISSING:
        findings.append(_missing(f"{path}.strength", layer_id))
    elif isinstance(strength_value, bool) or not isinstance(
        strength_value, (int, float)
    ):
        findings.append(_wrong_type(f"{path}.strength", "number", layer_id))
    elif not math.isfinite(strength_value):
        findings.append(
            _error(
                "json.number.non_finite",
                "Strength must be finite.",
                f"{path}.strength",
                layer_id,
            )
        )
    else:
        strength = strength_value

    influence_field = _decode_influence_field(
        value.get("influence_field", _MISSING),
        path,
        layer_id,
        findings,
    )

    if _has_errors(findings[start:]):
        return None
    assert layer_id is not None
    assert name is not None
    assert prompt is not None
    assert visible is not None
    assert strength is not None
    return PromptLayer(
        layer_id=layer_id,
        name=name,
        prompt_text=prompt,
        visible=visible,
        strength=strength,
        influence_field=influence_field,
    )


def _decode_influence_field(
    value: object,
    layer_path: str,
    layer_id: str | None,
    findings: list[PersistenceFinding],
) -> InfluenceFieldAssetReference | None:
    path = f"{layer_path}.influence_field"
    if value is _MISSING:
        findings.append(_missing(path, layer_id))
        return None
    if value is None:
        return None
    if not isinstance(value, dict):
        findings.append(_wrong_type(path, "object or null", layer_id))
        return None

    findings.extend(
        _unknown_field_warnings(
            value,
            _INFLUENCE_FIELD_KEYS,
            path,
            layer_id=layer_id,
        )
    )
    start = len(findings)
    raw_path = _required_string(value, "path", f"{path}.path", findings, layer_id)
    normalized_path: str | None = None
    if raw_path is not None:
        try:
            normalized_path = normalize_asset_reference(raw_path)
        except AssetPathError as error:
            findings.append(
                _error(error.code, str(error), f"{path}.path", layer_id)
            )

    checksum_value = value.get("sha256", _MISSING)
    checksum: str | None = None
    if checksum_value is _MISSING:
        findings.append(_missing(f"{path}.sha256", layer_id))
    elif checksum_value is not None and not isinstance(checksum_value, str):
        findings.append(_wrong_type(f"{path}.sha256", "string or null", layer_id))
    else:
        checksum = checksum_value

    if _has_errors(findings[start:]):
        return None
    assert normalized_path is not None
    return InfluenceFieldAssetReference(
        relative_path=normalized_path,
        checksum=checksum,
    )


def _decode_adapter(
    value: object,
    findings: list[PersistenceFinding],
) -> tuple[str | None, object]:
    path = "$.document.adapter"
    if value is _MISSING:
        findings.append(_missing(path))
        return None, {}
    if not isinstance(value, dict):
        findings.append(_wrong_type(path, "object"))
        return None, {}

    findings.extend(_unknown_field_warnings(value, _ADAPTER_KEYS, path))
    adapter_id_value = value.get("id", _MISSING)
    adapter_id: str | None = None
    if adapter_id_value is _MISSING:
        findings.append(_missing(f"{path}.id"))
    elif adapter_id_value is not None and not isinstance(adapter_id_value, str):
        findings.append(_wrong_type(f"{path}.id", "string or null"))
    else:
        adapter_id = adapter_id_value

    settings_value = value.get("settings", _MISSING)
    if settings_value is _MISSING:
        findings.append(_missing(f"{path}.settings"))
        return adapter_id, {}
    if not isinstance(settings_value, dict):
        findings.append(_wrong_type(f"{path}.settings", "object"))
        return adapter_id, {}
    if "composition_policy" in settings_value:
        findings.append(
            _error(
                "composition_policy.invalid_location",
                "Composition Policy belongs to the document, not adapter settings.",
                f"{path}.settings.composition_policy",
            )
        )
        return adapter_id, {}

    settings_ok, settings, settings_findings = _normalize_json_value(
        settings_value,
        f"{path}.settings",
    )
    findings.extend(settings_findings)
    return adapter_id, settings if settings_ok else {}


def _decode_format_version(
    value: object,
    findings: list[PersistenceFinding],
) -> PrototypeFormatVersion | None:
    parts = _decode_version_parts(value, "$.format_version", findings)
    if parts is None:
        return None
    return PrototypeFormatVersion(*parts)


def _decode_domain_version(
    value: object,
    findings: list[PersistenceFinding],
) -> PrototypeDocumentVersion | None:
    parts = _decode_version_parts(value, "$.document.version", findings)
    if parts is None:
        return None
    return PrototypeDocumentVersion(*parts)


def _decode_version_parts(
    value: object,
    path: str,
    findings: list[PersistenceFinding],
) -> tuple[int, int] | None:
    if value is _MISSING:
        findings.append(_missing(path))
        return None
    if not isinstance(value, dict):
        findings.append(_wrong_type(path, "object"))
        return None
    findings.extend(_unknown_field_warnings(value, _VERSION_KEYS, path))

    parts: list[int] = []
    for key in ("major", "minor"):
        item = value.get(key, _MISSING)
        item_path = f"{path}.{key}"
        if item is _MISSING:
            findings.append(_missing(item_path))
        elif isinstance(item, bool) or not isinstance(item, int):
            findings.append(_wrong_type(item_path, "integer"))
        elif item < 0:
            findings.append(
                _error(
                    "json.value.invalid",
                    "Version components must be non-negative.",
                    item_path,
                )
            )
        else:
            parts.append(item)
    return (parts[0], parts[1]) if len(parts) == 2 else None


def _normalize_json_value(
    value: object,
    path: str,
    *,
    depth: int = 0,
    ancestors: set[int] | None = None,
) -> tuple[bool, object, list[PersistenceFinding]]:
    findings: list[PersistenceFinding] = []
    if depth > MAX_ADAPTER_SETTINGS_DEPTH:
        return (
            False,
            None,
            [
                _error(
                    "adapter_settings.depth_exceeded",
                    f"Adapter settings exceed the maximum depth of {MAX_ADAPTER_SETTINGS_DEPTH}.",
                    path,
                )
            ],
        )

    if value is None or isinstance(value, (str, bool, int)):
        return True, value, findings
    if isinstance(value, float):
        if not math.isfinite(value):
            return (
                False,
                None,
                [
                    _error(
                        "adapter_settings.non_finite",
                        "Adapter settings numbers must be finite.",
                        path,
                    )
                ],
            )
        return True, value, findings

    if ancestors is None:
        ancestors = set()
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in ancestors:
            return (
                False,
                None,
                [
                    _error(
                        "adapter_settings.cycle",
                        "Adapter settings must not contain reference cycles.",
                        path,
                    )
                ],
            )
        ancestors.add(identity)
        normalized: dict[str, object] = {}
        ok = True
        for key, item in value.items():
            if not isinstance(key, str):
                findings.append(
                    _error(
                        "adapter_settings.non_string_key",
                        "Adapter settings object keys must be strings.",
                        path,
                    )
                )
                ok = False
                continue
            child_ok, child, child_findings = _normalize_json_value(
                item,
                _child_json_path(path, key),
                depth=depth + 1,
                ancestors=ancestors,
            )
            findings.extend(child_findings)
            if child_ok:
                normalized[key] = child
            else:
                ok = False
        ancestors.remove(identity)
        return ok, normalized, findings

    if isinstance(value, list):
        identity = id(value)
        if identity in ancestors:
            return (
                False,
                None,
                [
                    _error(
                        "adapter_settings.cycle",
                        "Adapter settings must not contain reference cycles.",
                        path,
                    )
                ],
            )
        ancestors.add(identity)
        normalized_items: list[object] = []
        ok = True
        for index, item in enumerate(value):
            child_ok, child, child_findings = _normalize_json_value(
                item,
                f"{path}[{index}]",
                depth=depth + 1,
                ancestors=ancestors,
            )
            findings.extend(child_findings)
            if child_ok:
                normalized_items.append(child)
            else:
                ok = False
        ancestors.remove(identity)
        return ok, normalized_items, findings

    return (
        False,
        None,
        [
            _error(
                "adapter_settings.unsupported_type",
                f"Adapter settings value has unsupported type {type(value).__name__!r}.",
                path,
            )
        ],
    )


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError(key)
        result[key] = value
    return result


def _reject_non_finite_json_number(value: str) -> None:
    raise _NonFiniteJsonNumberError(value)


def _unknown_field_warnings(
    value: Mapping[str, object],
    allowed: set[str],
    path: str,
    *,
    layer_id: str | None = None,
) -> list[PersistenceFinding]:
    return [
        _error(
            "composition_policy.invalid_location",
            "Composition Policy belongs only at document.composition_policy in format 2.0.",
            _child_json_path(path, key),
            layer_id,
        )
        if key == "composition_policy"
        else PersistenceFinding(
            code="json.unknown_field",
            severity=FindingSeverity.WARNING,
            message=(
                "Unknown neutral field will be discarded if this document is saved."
            ),
            json_path=_child_json_path(path, key),
            layer_id=layer_id,
        )
        for key in value
        if key not in allowed
    ]


def _required_string(
    value: Mapping[str, object],
    key: str,
    path: str,
    findings: list[PersistenceFinding],
    layer_id: str | None = None,
) -> str | None:
    item = value.get(key, _MISSING)
    if item is _MISSING:
        findings.append(_missing(path, layer_id))
        return None
    if not isinstance(item, str):
        findings.append(_wrong_type(path, "string", layer_id))
        return None
    return item


def _version_object(major: int, minor: int) -> dict[str, int]:
    return {"major": major, "minor": minor}


def _child_json_path(path: str, key: str) -> str:
    if key.isidentifier():
        return f"{path}.{key}"
    escaped = key.replace("\\", "\\\\").replace("'", "\\'")
    return f"{path}['{escaped}']"


def _has_errors(findings: list[PersistenceFinding]) -> bool:
    return any(finding.severity is FindingSeverity.ERROR for finding in findings)


def _missing(path: str, layer_id: str | None = None) -> PersistenceFinding:
    return _error(
        "json.field.missing",
        "Required JSON field is missing.",
        path,
        layer_id,
    )


def _wrong_type(
    path: str,
    expected: str,
    layer_id: str | None = None,
) -> PersistenceFinding:
    return _error(
        "json.field.wrong_type",
        f"JSON field must be {expected}.",
        path,
        layer_id,
    )


def _error(
    code: str,
    message: str,
    json_path: str,
    layer_id: str | None = None,
) -> PersistenceFinding:
    return PersistenceFinding(
        code=code,
        severity=FindingSeverity.ERROR,
        message=message,
        json_path=json_path,
        layer_id=layer_id,
    )
