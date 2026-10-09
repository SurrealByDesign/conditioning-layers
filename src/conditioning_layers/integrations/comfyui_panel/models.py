"""Bounded transport and UI-safe result models for the ComfyUI sidebar."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Any

from conditioning_layers.domain import (
    COMPOSITION_POLICY_PROTOTYPE_VERSION, CURRENT_PROTOTYPE_VERSION,
    CompositionPolicyError, CompositionPolicyReference, PrototypeDocumentVersion,
    FindingSeverity, ValidationFinding, resolve_composition_policy,
)


REQUEST_METADATA_PART = "request"
FIELD_PART_PREFIX = "field-"
PNG_MIME_TYPE = "image/png"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_METADATA_BYTES = 64 * 1024
MAX_FIELD_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 17 * 1024 * 1024
MAX_MULTIPART_PARTS = 65
MAX_RESPONSE_FINDINGS = 16
MAX_MESSAGE_LENGTH = 240
MAX_GENERATION_SEED = 2**64 - 1

_OPAQUE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_ROW_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_EXECUTION_ID = re.compile(r"^[a-f0-9]{32}$")
_SEED_DECIMAL = re.compile(r"(?:0|[1-9][0-9]{0,19})")


@dataclass(frozen=True, slots=True)
class UploadedField:
    """One filename-independent PNG upload held only as bounded bytes."""

    part_name: str
    content_type: str
    data: bytes


@dataclass(frozen=True, slots=True)
class RetainedField:
    """One server-owned field selected by canonical layer identity."""

    layer_id: str


@dataclass(frozen=True, slots=True)
class PanelLayerDraft:
    """Temporary browser row state after structural transport validation."""

    row_id: str
    name: str
    prompt_text: str
    strength: int | float
    active: bool
    layer_id: str | None
    field: UploadedField | RetainedField


@dataclass(frozen=True, slots=True)
class PanelExecutionDraft:
    """Ordered temporary request state; never the canonical document."""

    base_prompt: str
    layers: tuple[PanelLayerDraft, ...]
    idempotency_key: str
    document_id: str | None = None
    document_key: str | None = None
    seed: int | None = None
    document_version: PrototypeDocumentVersion = CURRENT_PROTOTYPE_VERSION
    composition_policy: CompositionPolicyReference | None = None

    def __post_init__(self) -> None:
        policy_transport(self.document_version, self.composition_policy)
        if self.seed is not None and (
            type(self.seed) is not int or not 0 <= self.seed <= MAX_GENERATION_SEED
        ):
            raise ValueError("Seed must be an unsigned 64-bit integer.")

    @property
    def resolved_seed(self) -> int:
        """Keep legacy automatic selection independent of execution identity."""

        if self.seed is not None:
            return self.seed
        return int.from_bytes(
            hashlib.sha256(self.idempotency_key.encode("utf-8")).digest()[:8],
            "big",
        )

    @property
    def fingerprint(self) -> str:
        payload = {
            "base_prompt": self.base_prompt,
            "idempotency_key": self.idempotency_key,
            "layers": [
                {
                    "row_id": layer.row_id,
                    "layer_id": layer.layer_id,
                    "name": layer.name,
                    "prompt_text": layer.prompt_text,
                    "strength": layer.strength,
                    "active": layer.active,
                    "field_identity": (
                        hashlib.sha256(layer.field.data).hexdigest()
                        if isinstance(layer.field, UploadedField)
                        else f"retained:{layer.field.layer_id}"
                    ),
                }
                for layer in self.layers
            ],
        }
        # Omitting the optional run value preserves existing request identities.
        if self.seed is not None:
            payload["seed"] = str(self.seed)
        payload.update(policy_transport(self.document_version, self.composition_policy))
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class PanelFinding:
    """Bounded artist-facing projection of an authoritative Python finding."""

    code: str
    severity: str
    message: str
    layer: str | None = None

    def to_json(self) -> dict[str, str]:
        result = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
        }
        if self.layer is not None:
            result["layer"] = self.layer
        return result


@dataclass(frozen=True, slots=True)
class PanelOutput:
    """Safe ComfyUI output metadata with no host filesystem path."""

    filename: str
    subfolder: str
    storage_type: str
    view_url: str

    def to_json(self) -> dict[str, str]:
        return {
            "filename": self.filename,
            "subfolder": self.subfolder,
            "type": self.storage_type,
            "view_url": self.view_url,
        }


@dataclass(frozen=True, slots=True)
class PanelRunResult:
    """Terminal application result containing only UI-safe data."""

    state: str
    findings: tuple[PanelFinding, ...] = ()
    output: PanelOutput | None = None


class PanelRequestError(ValueError):
    """A bounded malformed-request response suitable for the sidebar."""

    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.status = status
        self.finding = PanelFinding(
            code=code,
            severity=FindingSeverity.ERROR.value,
            message=_bounded_text(message),
        )


def policy_transport(version, policy) -> dict[str, object]:
    """Preserve the legacy omission; carry exactly the existing 2.0 intent."""
    if type(version) is not PrototypeDocumentVersion or type(version.major) is not int or type(version.minor) is not int:
        raise PanelRequestError("panel.request.composition_policy", "Invalid document version.")
    if version == CURRENT_PROTOTYPE_VERSION and policy is None:
        return {}
    if version != COMPOSITION_POLICY_PROTOTYPE_VERSION:
        raise PanelRequestError("panel.request.composition_policy", "Explicit Composition Policy requires document 2.0.")
    try:
        resolve_composition_policy(policy)
    except CompositionPolicyError as error:
        raise PanelRequestError("panel.request.composition_policy", str(error)) from error
    return {"document_version": asdict(version), "composition_policy": asdict(policy)}


def parse_policy_transport(payload):
    if not {"document_version", "composition_policy"} & payload.keys():
        return CURRENT_PROTOTYPE_VERSION, None
    version, policy = payload.get("document_version"), payload.get("composition_policy")
    if (type(version) is not dict or set(version) != {"major", "minor"}
            or type(policy) is not dict or set(policy) != {"policy_identifier", "policy_version"}):
        raise PanelRequestError("panel.request.composition_policy", "Document 2.0 requires an exact explicit Composition Policy reference.")
    version, policy = PrototypeDocumentVersion(**version), CompositionPolicyReference(**policy)
    policy_transport(version, policy)
    return version, policy


def parse_panel_request(
    metadata_bytes: bytes,
    uploads: Mapping[str, UploadedField],
    *,
    multipart_part_count: int,
    total_bytes: int,
) -> PanelExecutionDraft:
    """Parse strict structure while leaving all semantic rules to Python APIs."""

    if not isinstance(metadata_bytes, bytes) or len(metadata_bytes) > MAX_METADATA_BYTES:
        raise PanelRequestError(
            "panel.request.metadata_size",
            "Request metadata exceeds the 64 KiB transport limit.",
            status=413,
        )
    if multipart_part_count > MAX_MULTIPART_PARTS:
        raise PanelRequestError(
            "panel.request.part_limit",
            "The multipart request contains too many parts.",
            status=413,
        )
    if total_bytes > MAX_TOTAL_BYTES:
        raise PanelRequestError(
            "panel.request.total_size",
            "The multipart request exceeds the 17 MiB transport limit.",
            status=413,
        )
    try:
        payload = json.loads(
            metadata_bytes.decode("utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-standard JSON constant: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PanelRequestError(
            "panel.request.metadata_json",
            "Request metadata must be one valid UTF-8 JSON object.",
        ) from exc
    if not isinstance(payload, dict):
        raise PanelRequestError(
            "panel.request.metadata_shape",
            "Request metadata must be a JSON object.",
        )
    _require_exact_keys(
        payload,
        {"base_prompt", "layers", "idempotency_key", "document_id", "document_key"}
        | ({"seed"} if "seed" in payload else set())
        | ({"document_version", "composition_policy"} & payload.keys()),
        "panel.request.fields",
        "Request metadata contains missing or unsupported fields.",
    )

    document_version, composition_policy = parse_policy_transport(payload)

    base_prompt = payload["base_prompt"]
    idempotency_key = payload["idempotency_key"]
    document_id = payload["document_id"]
    document_key = payload["document_key"]
    rows = payload["layers"]
    seed = None
    if "seed" in payload:
        seed_text = payload["seed"]
        if (
            not isinstance(seed_text, str)
            or _SEED_DECIMAL.fullmatch(seed_text) is None
            or int(seed_text) > MAX_GENERATION_SEED
        ):
            raise PanelRequestError(
                "panel.request.seed",
                "Seed must be decimal text from 0 to 18446744073709551615, without signs or leading zeros.",
            )
        seed = int(seed_text)
    if not isinstance(base_prompt, str):
        raise PanelRequestError(
            "panel.request.base_prompt_type",
            "Base Prompt must be text.",
        )
    if not isinstance(idempotency_key, str) or _OPAQUE_ID.fullmatch(idempotency_key) is None:
        raise PanelRequestError(
            "panel.request.idempotency_key",
            "The idempotency key must be a bounded opaque identifier.",
        )
    if document_id is not None and (
        not isinstance(document_id, str) or _OPAQUE_ID.fullmatch(document_id) is None
    ):
        raise PanelRequestError(
            "panel.request.document_id",
            "The document identity must be a bounded opaque identifier.",
        )
    if document_key is not None and (
        not isinstance(document_key, str) or _OPAQUE_ID.fullmatch(document_key) is None
    ):
        raise PanelRequestError(
            "panel.request.document_key",
            "The document key must be a bounded server-issued identifier.",
        )
    if not isinstance(rows, list):
        raise PanelRequestError(
            "panel.request.layers_type",
            "Prompt Layers must be an ordered JSON array.",
        )

    layers: list[PanelLayerDraft] = []
    seen_rows: set[str] = set()
    referenced_parts: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise PanelRequestError(
                "panel.request.layer_shape",
                f"Layer {index + 1} must be a JSON object.",
            )
        _require_exact_keys(
            row,
            {
                "row_id",
                "layer_id",
                "name",
                "prompt_text",
                "strength",
                "active",
                "field_part",
                "retained_field",
            },
            "panel.request.layer_fields",
            f"Layer {index + 1} contains missing or unsupported fields.",
        )
        row_id = row["row_id"]
        layer_id = row["layer_id"]
        field_part = row["field_part"]
        if not isinstance(row_id, str) or _ROW_ID.fullmatch(row_id) is None:
            raise PanelRequestError(
                "panel.request.row_id",
                f"Layer {index + 1} has an invalid temporary row identifier.",
            )
        if row_id in seen_rows:
            raise PanelRequestError(
                "panel.request.row_id_duplicate",
                "Temporary layer row identifiers must be unique.",
            )
        seen_rows.add(row_id)
        if layer_id is not None and (
            not isinstance(layer_id, str) or _OPAQUE_ID.fullmatch(layer_id) is None
        ):
            raise PanelRequestError(
                "panel.request.layer_id",
                f"Layer {index + 1} has an invalid canonical layer identifier.",
            )
        retained_field = row["retained_field"]
        if not isinstance(retained_field, bool):
            raise PanelRequestError(
                "panel.request.retained_field",
                f"Layer {index + 1} has an invalid retained-field marker.",
            )
        if retained_field:
            if field_part is not None or layer_id is None or document_key is None:
                raise PanelRequestError(
                    "panel.request.retained_field",
                    f"Layer {index + 1} has an invalid retained-field association.",
                )
            field: UploadedField | RetainedField = RetainedField(layer_id)
        else:
            if (
                not isinstance(field_part, str)
                or field_part != FIELD_PART_PREFIX + row_id
                or field_part in referenced_parts
            ):
                raise PanelRequestError(
                    "panel.request.field_part",
                    f"Layer {index + 1} has an invalid or duplicate field-part association.",
                )
            referenced_parts.add(field_part)
            uploaded = uploads.get(field_part)
            if uploaded is None:
                raise PanelRequestError(
                    "panel.request.field_missing",
                    f"Layer {index + 1} requires a PNG Influence Field upload.",
                )
            _validate_upload(uploaded, index)
            field = uploaded
        name = row["name"]
        prompt_text = row["prompt_text"]
        strength = row["strength"]
        active = row["active"]
        if not isinstance(name, str) or not isinstance(prompt_text, str):
            raise PanelRequestError(
                "panel.request.layer_text_type",
                f"Layer {index + 1} name and prompt must be text.",
            )
        if (
            isinstance(strength, bool)
            or not isinstance(strength, (int, float))
        ):
            raise PanelRequestError(
                "panel.request.strength_type",
                f"Layer {index + 1} Strength must be a JSON number.",
            )
        if not isinstance(active, bool):
            raise PanelRequestError(
                "panel.request.active_type",
                f"Layer {index + 1} Active state must be true or false.",
            )
        layers.append(
            PanelLayerDraft(
                row_id=row_id,
                layer_id=layer_id,
                name=name,
                prompt_text=prompt_text,
                strength=strength,
                active=active,
                field=field,
            )
        )

    if set(uploads) != referenced_parts:
        raise PanelRequestError(
            "panel.request.field_unreferenced",
            "Every uploaded field part must belong to exactly one visible layer row.",
        )
    return PanelExecutionDraft(
        base_prompt=base_prompt,
        layers=tuple(layers),
        idempotency_key=idempotency_key,
        document_id=document_id,
        document_key=document_key,
        seed=seed,
        document_version=document_version,
        composition_policy=composition_policy,
    )


def project_findings(
    findings: Sequence[ValidationFinding],
    layer_labels: Mapping[str, str] | None = None,
) -> tuple[PanelFinding, ...]:
    """Project stable codes and concise text without internal evidence details."""

    labels = layer_labels or {}
    result: list[PanelFinding] = []
    seen: set[str] = set()
    for finding in findings:
        if finding.code in seen:
            continue
        seen.add(finding.code)
        result.append(
            PanelFinding(
                code=_bounded_text(finding.code, 96),
                severity=finding.severity.value,
                message=_bounded_text(finding.message),
                layer=(
                    _bounded_text(labels[finding.layer_id], 96)
                    if finding.layer_id in labels
                    else None
                ),
            )
        )
        if len(result) >= MAX_RESPONSE_FINDINGS:
            break
    return tuple(result)


def validate_execution_id(value: str) -> bool:
    return isinstance(value, str) and _EXECUTION_ID.fullmatch(value) is not None


def validate_layer_identifier(value: object) -> bool:
    """Accept only the bounded opaque identifier shape used for layer IDs."""

    return isinstance(value, str) and _OPAQUE_ID.fullmatch(value) is not None


def _validate_upload(field: UploadedField, index: int) -> None:
    if field.content_type.casefold() != PNG_MIME_TYPE:
        raise PanelRequestError(
            "panel.request.field_mime",
            f"Layer {index + 1} Influence Field must use image/png.",
            status=415,
        )
    if not field.data or len(field.data) > MAX_FIELD_BYTES:
        raise PanelRequestError(
            "panel.request.field_size",
            f"Layer {index + 1} Influence Field exceeds the 8 MiB per-file limit.",
            status=413,
        )
    if not field.data.startswith(PNG_SIGNATURE):
        raise PanelRequestError(
            "panel.request.field_signature",
            f"Layer {index + 1} Influence Field is not a PNG payload.",
            status=415,
        )


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    code: str,
    message: str,
) -> None:
    if set(value) != expected:
        raise PanelRequestError(code, message)


def _bounded_text(value: object, limit: int = MAX_MESSAGE_LENGTH) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    return text[:limit]
