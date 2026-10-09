"""Server-owned canonical document persistence for the ComfyUI sidebar."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any
from uuid import uuid4

from conditioning_layers.domain import (
    CURRENT_PROTOTYPE_VERSION,
    CompositionPolicyReference,
    PrototypeDocumentVersion,
    PREDICTION_MIXING_ADAPTER_ID,
    ConditioningDocument,
    FindingSeverity,
    InfluenceFieldAssetReference,
    PromptLayer,
)
from conditioning_layers.persistence import (
    PersistenceError,
    document_asset_root,
    load_document,
    resolve_asset_path,
    save_document,
)

from .models import (
    MAX_FIELD_BYTES,
    MAX_METADATA_BYTES,
    PanelExecutionDraft,
    PanelFinding,
    PanelLayerDraft,
    PanelRequestError,
    PNG_SIGNATURE,
    RetainedField,
    UploadedField,
    parse_panel_request,
    policy_transport,
    validate_layer_identifier,
)


DOCUMENT_EXTENSION = ".conditioning.json"
DOCUMENTS_RELATIVE_DIRECTORY = Path("conditioning-layers") / "documents"
MAX_DOCUMENTS = 256
_DOCUMENT_KEY = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$")


@dataclass(frozen=True, slots=True)
class PanelDocumentDraft:
    """Temporary save request projected from the browser editing surface."""

    display_name: str
    source_document_key: str | None
    document_id: str | None
    base_prompt: str
    layers: tuple[PanelLayerDraft, ...]
    document_version: PrototypeDocumentVersion = CURRENT_PROTOTYPE_VERSION
    composition_policy: CompositionPolicyReference | None = None

    def __post_init__(self) -> None:
        policy_transport(self.document_version, self.composition_policy)


@dataclass(frozen=True, slots=True)
class OpenedPanelDocument:
    """Canonical document plus safe server key and verified field bytes."""

    document_key: str
    display_name: str
    document: ConditioningDocument
    field_bytes: dict[str, bytes]

    def to_json(self) -> dict[str, Any]:
        return {
            **policy_transport(
                self.document.version if self.document.composition_policy is not None else CURRENT_PROTOTYPE_VERSION,
                self.document.composition_policy,
            ),
            "document_key": self.document_key,
            "display_name": self.display_name,
            "document_id": self.document.document_id,
            "base_prompt": self.document.base_prompt,
            "layers": [
                {
                    "layer_id": layer.layer_id,
                    "name": layer.name,
                    "prompt_text": layer.prompt_text,
                    "strength": layer.strength,
                    "active": layer.visible,
                    "field_persisted": layer.influence_field is not None,
                    "field_url": (
                        field_preview_url(self.document_key, layer.layer_id)
                        if layer.influence_field is not None
                        else None
                    ),
                }
                for layer in self.document.layers
            ],
        }


class PanelDocumentError(Exception):
    """Bounded persistence error safe for the artist surface."""

    def __init__(self, code: str, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.status = status
        self.finding = PanelFinding(code=code, severity="error", message=message)


class PanelDocumentStore:
    """Own canonical documents beneath the validated ComfyUI user directory."""

    def __init__(self, user_directory: Path) -> None:
        trusted = user_directory.resolve()
        root = (trusted / DOCUMENTS_RELATIVE_DIRECTORY).resolve()
        if not root.is_relative_to(trusted):
            raise ValueError("document storage must remain beneath the ComfyUI user directory")
        self.root = root

    def list_documents(self) -> tuple[dict[str, str], ...]:
        if not self.root.exists():
            return ()
        records = []
        for path in sorted(self.root.glob(f"*{DOCUMENT_EXTENSION}"))[:MAX_DOCUMENTS]:
            key = path.name[: -len(DOCUMENT_EXTENSION)]
            if _DOCUMENT_KEY.fullmatch(key):
                records.append({"document_key": key, "display_name": _display_name(key)})
        return tuple(records)

    def open(self, document_key: str, *, policy_aware: bool = False) -> OpenedPanelDocument:
        return self._load(document_key, policy_aware=policy_aware)

    def _load(self, document_key: str, *, policy_aware: bool) -> OpenedPanelDocument:
        path = self._path_for(document_key)
        if not path.is_file():
            raise PanelDocumentError(
                "panel.document.not_found",
                "The selected Conditioning Layers document was not found.",
                status=404,
            )
        loaded = load_document(path)
        errors = [
            finding
            for finding in loaded.findings
            if finding.severity is FindingSeverity.ERROR
        ]
        if loaded.document is None or errors:
            codes = {finding.code for finding in errors}
            if any("version" in code or "migration" in code for code in codes):
                code = "panel.document.version_unsupported"
                message = "This Conditioning Layers document version is not supported."
            elif any(code.startswith("io.") for code in codes):
                code = "panel.document.open_failed"
                message = "The Conditioning Layers document could not be read."
            elif any(code.startswith("document.") or code.startswith("layer.") for code in codes):
                code = "panel.document.validation_failed"
                message = "The Conditioning Layers document failed validation."
            else:
                code = "panel.document.corrupted"
                message = "The Conditioning Layers document is corrupted."
            raise PanelDocumentError(code, message, status=422)

        document = loaded.document
        if document.composition_policy is not None and not policy_aware:
            raise PanelDocumentError(
                "panel.document.composition_policy_editor_unsupported",
                "This document carries explicit Composition Policy intent that the current editor cannot preserve.",
                status=422,
            )
        fields: dict[str, bytes] = {}
        for layer in document.layers:
            reference = layer.influence_field
            if reference is None:
                raise PanelDocumentError(
                    "panel.document.field_missing",
                    f"{layer.name or 'A Prompt Layer'} has no persisted Influence Field.",
                    status=422,
                )
            asset_root = document_asset_root(path)
            path_to_field = resolve_asset_path(path, reference.relative_path)
            try:
                resolved_root = asset_root.resolve(strict=True)
                resolved_field = path_to_field.resolve(strict=True)
                if (
                    asset_root.is_symlink()
                    or path_to_field.is_symlink()
                    or not resolved_field.is_relative_to(resolved_root)
                    or not resolved_field.is_file()
                ):
                    raise OSError("asset is absent or not a regular file")
                data = resolved_field.read_bytes()
            except OSError as error:
                raise PanelDocumentError(
                    "panel.document.field_missing",
                    f"{layer.name or 'A Prompt Layer'} has a missing Influence Field asset.",
                    status=422,
                ) from error
            if not data.startswith(PNG_SIGNATURE) or len(data) > MAX_FIELD_BYTES:
                raise PanelDocumentError(
                    "panel.document.field_invalid",
                    f"{layer.name or 'A Prompt Layer'} has an invalid Influence Field asset.",
                    status=422,
                )
            checksum = hashlib.sha256(data).hexdigest()
            if reference.checksum is None or checksum != reference.checksum:
                raise PanelDocumentError(
                    "panel.document.field_checksum",
                    f"{layer.name or 'A Prompt Layer'} Influence Field checksum does not match.",
                    status=422,
                )
            fields[layer.layer_id] = data
        return OpenedPanelDocument(
            document_key=document_key,
            display_name=_display_name(document_key),
            document=document,
            field_bytes=fields,
        )

    def save_as(self, draft: PanelDocumentDraft) -> OpenedPanelDocument:
        target_key = document_key_for_name(draft.display_name)
        if self._path_for(target_key).exists():
            raise PanelDocumentError(
                "panel.document.exists",
                "A document with that name already exists. Choose another name.",
                status=409,
            )
        return self._save(
            draft,
            target_key,
            overwrite=False,
            create_document_identity=True,
        )

    def save(self, document_key: str, draft: PanelDocumentDraft) -> OpenedPanelDocument:
        self._validate_key(document_key)
        if draft.source_document_key != document_key:
            raise PanelDocumentError(
                "panel.document.identity_mismatch",
                "Save requires the currently opened document identity.",
                status=409,
            )
        if not self._path_for(document_key).is_file():
            raise PanelDocumentError(
                "panel.document.not_found",
                "The selected Conditioning Layers document was not found.",
                status=404,
            )
        return self._save(
            draft,
            document_key,
            overwrite=True,
            create_document_identity=False,
        )

    def read_field(self, document_key: str, layer_id: str) -> bytes:
        """Return one persisted field's verified bytes for informational preview.

        The bytes pass the complete open-time verification (containment,
        symlink, PNG signature, size bound, checksum) on every call. Serving a
        preview asserts nothing about executability; Python validation at
        save/generate time remains authoritative.
        """

        if not validate_layer_identifier(layer_id):
            raise PanelDocumentError(
                "panel.document.layer_identity",
                "The layer identifier is invalid.",
                status=404,
            )
        opened = self._load(document_key, policy_aware=True)
        try:
            return opened.field_bytes[layer_id]
        except KeyError as error:
            raise PanelDocumentError(
                "panel.document.field_missing",
                "The requested Influence Field does not belong to this document.",
                status=404,
            ) from error

    def resolve_execution_field(
        self,
        document_key: str,
        document_id: str | None,
        layer_id: str,
        *,
        composition_policy: CompositionPolicyReference | None = None,
    ) -> bytes:
        opened = self._load(document_key, policy_aware=composition_policy is not None)
        if document_id != opened.document.document_id:
            raise PanelDocumentError(
                "panel.document.identity_mismatch",
                "The opened document identity no longer matches the execution request.",
                status=409,
            )
        try:
            return opened.field_bytes[layer_id]
        except KeyError as error:
            raise PanelDocumentError(
                "panel.document.field_missing",
                "The retained Influence Field no longer belongs to this document.",
                status=422,
            ) from error

    def validate_execution_source(self, draft: PanelExecutionDraft) -> None:
        """Even replacement uploads cannot strip a saved source's policy."""
        if draft.document_key is None:
            return
        opened = self._load(draft.document_key, policy_aware=draft.composition_policy is not None)
        if draft.document_id != opened.document.document_id:
            raise PanelDocumentError(
                "panel.document.identity_mismatch",
                "The opened document identity no longer matches the execution request.",
                status=409,
            )

    def _save(
        self,
        draft: PanelDocumentDraft,
        target_key: str,
        *,
        overwrite: bool,
        create_document_identity: bool,
    ) -> OpenedPanelDocument:
        source = (
            self._load(draft.source_document_key, policy_aware=draft.composition_policy is not None)
            if draft.source_document_key is not None
            else None
        )
        if source is None:
            if draft.document_id is not None:
                raise PanelDocumentError(
                    "panel.document.identity_mismatch",
                    "A new document must not claim an existing document identity.",
                    status=409,
                )
            document_id = f"document-{uuid4().hex}"
            known_layer_ids: set[str] = set()
        else:
            if draft.document_id != source.document.document_id:
                raise PanelDocumentError(
                    "panel.document.identity_mismatch",
                    "The opened document identity no longer matches the save request.",
                    status=409,
                )
            document_id = (
                f"document-{uuid4().hex}"
                if create_document_identity
                else source.document.document_id
            )
            known_layer_ids = {layer.layer_id for layer in source.document.layers}

        layers: list[PromptLayer] = []
        field_payloads: dict[str, bytes] = {}
        seen_layer_ids: set[str] = set()
        for index, row in enumerate(draft.layers, start=1):
            layer_id = row.layer_id
            if layer_id is None:
                layer_id = f"layer-{uuid4().hex}"
            elif layer_id not in known_layer_ids:
                raise PanelDocumentError(
                    "panel.document.layer_identity",
                    f"Layer {index} does not belong to the opened document.",
                    status=409,
                )
            if layer_id in seen_layer_ids:
                raise PanelDocumentError(
                    "panel.document.layer_identity",
                    "Prompt Layer identities must remain unique.",
                    status=409,
                )
            seen_layer_ids.add(layer_id)
            if isinstance(row.field, UploadedField):
                data = row.field.data
            else:
                if source is None or row.field.layer_id != layer_id:
                    raise PanelDocumentError(
                        "panel.document.field_ownership",
                        f"Layer {index} has an invalid retained Influence Field.",
                        status=409,
                    )
                data = source.field_bytes.get(layer_id, b"")
            if not data.startswith(PNG_SIGNATURE) or len(data) > MAX_FIELD_BYTES:
                raise PanelDocumentError(
                    "panel.document.field_missing",
                    f"Layer {index} requires an Influence Field.",
                    status=422,
                )
            checksum = hashlib.sha256(data).hexdigest()
            relative_path = f"fields/{layer_id}.png"
            field_payloads[layer_id] = data
            layers.append(
                PromptLayer(
                    layer_id=layer_id,
                    name=row.name,
                    prompt_text=row.prompt_text,
                    visible=row.active,
                    strength=row.strength,
                    influence_field=InfluenceFieldAssetReference(
                        relative_path=relative_path,
                        checksum=checksum,
                    ),
                )
            )
        document = ConditioningDocument(
            version=draft.document_version,
            composition_policy=draft.composition_policy,
            document_id=document_id,
            base_prompt=draft.base_prompt,
            layers=tuple(layers),
            selected_adapter_id=PREDICTION_MIXING_ADAPTER_ID,
            adapter_settings={},
        )
        self._publish(document, field_payloads, target_key, overwrite=overwrite)
        return self._load(target_key, policy_aware=True)

    def _publish(
        self,
        document: ConditioningDocument,
        fields: dict[str, bytes],
        target_key: str,
        *,
        overwrite: bool,
    ) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise PanelDocumentError(
                "panel.document.save_failed",
                "The document storage directory could not be created.",
                status=500,
            ) from error
        document_path = self._path_for(target_key)
        asset_root = document_asset_root(document_path)
        staged = Path(tempfile.mkdtemp(prefix=f".{target_key}.", dir=self.root))
        backup = self.root / f".{target_key}.{uuid4().hex}.backup"
        replaced_assets = False
        document_published = False
        try:
            fields_root = staged / "fields"
            fields_root.mkdir()
            for layer_id, data in fields.items():
                (fields_root / f"{layer_id}.png").write_bytes(data)
            if asset_root.exists():
                asset_root.replace(backup)
                replaced_assets = True
            staged.replace(asset_root)
            save_document(document, document_path, overwrite=overwrite)
            document_published = True
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
        except (OSError, PersistenceError, ValueError) as error:
            if not document_published:
                try:
                    if asset_root.exists():
                        shutil.rmtree(asset_root)
                    if replaced_assets and backup.exists():
                        backup.replace(asset_root)
                except OSError:
                    pass
            raise PanelDocumentError(
                "panel.document.save_failed",
                "The Conditioning Layers document could not be saved.",
                status=500,
            ) from error
        finally:
            if staged.exists():
                shutil.rmtree(staged, ignore_errors=True)
            if backup.exists() and not replaced_assets:
                shutil.rmtree(backup, ignore_errors=True)

    def _path_for(self, document_key: str) -> Path:
        self._validate_key(document_key)
        path = self.root / f"{document_key}{DOCUMENT_EXTENSION}"
        if not path.resolve().is_relative_to(self.root):
            raise PanelDocumentError(
                "panel.document.key_invalid",
                "The document identifier is invalid.",
            )
        return path

    @staticmethod
    def _validate_key(document_key: str) -> None:
        if not isinstance(document_key, str) or _DOCUMENT_KEY.fullmatch(document_key) is None:
            raise PanelDocumentError(
                "panel.document.key_invalid",
                "The document identifier is invalid.",
            )


def parse_document_request(
    metadata_bytes: bytes,
    uploads: dict[str, UploadedField],
    *,
    multipart_part_count: int,
    total_bytes: int,
) -> PanelDocumentDraft:
    """Parse a strict save request through the existing field transport rules."""

    if not isinstance(metadata_bytes, bytes) or len(metadata_bytes) > MAX_METADATA_BYTES:
        raise PanelRequestError(
            "panel.request.metadata_size",
            "Request metadata exceeds the 64 KiB transport limit.",
            status=413,
        )
    try:
        payload = json.loads(
            metadata_bytes.decode("utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-standard JSON constant: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise PanelRequestError(
            "panel.request.metadata_json",
            "Save metadata must be one valid UTF-8 JSON object.",
        ) from error
    expected = {
        "display_name",
        "source_document_key",
        "document_id",
        "base_prompt",
        "layers",
    }
    if isinstance(payload, dict):
        expected |= {"document_version", "composition_policy"} & payload.keys()
    if not isinstance(payload, dict) or set(payload) != expected:
        raise PanelRequestError(
            "panel.request.fields",
            "Save metadata contains missing or unsupported fields.",
        )
    display_name = payload["display_name"]
    source_key = payload["source_document_key"]
    if not isinstance(display_name, str):
        raise PanelRequestError("panel.document.name_invalid", "Document name must be text.")
    document_key_for_name(display_name)
    if source_key is not None and (
        not isinstance(source_key, str) or _DOCUMENT_KEY.fullmatch(source_key) is None
    ):
        raise PanelRequestError(
            "panel.document.key_invalid",
            "The source document identifier is invalid.",
        )
    execution_payload = {
        "base_prompt": payload["base_prompt"],
        "layers": payload["layers"],
        "idempotency_key": "document-save",
        "document_id": payload["document_id"],
        "document_key": source_key,
    }
    for key in ("document_version", "composition_policy"):
        if key in payload:
            execution_payload[key] = payload[key]
    parsed: PanelExecutionDraft = parse_panel_request(
        json.dumps(execution_payload, allow_nan=False).encode("utf-8"),
        uploads,
        multipart_part_count=multipart_part_count,
        total_bytes=total_bytes,
    )
    return PanelDocumentDraft(
        display_name=display_name.strip(),
        source_document_key=source_key,
        document_id=parsed.document_id,
        base_prompt=parsed.base_prompt,
        layers=parsed.layers,
        document_version=parsed.document_version,
        composition_policy=parsed.composition_policy,
    )


def field_preview_url(document_key: str, layer_id: str) -> str:
    """Build the server-owned, read-only preview route for one persisted field."""

    return f"/conditioning-layers/documents/{document_key}/fields/{layer_id}"


def document_key_for_name(display_name: str) -> str:
    """Convert an artist label to one flat, server-owned document key."""

    if not isinstance(display_name, str):
        raise PanelRequestError("panel.document.name_invalid", "Document name must be text.")
    if any(character in display_name for character in ("/", "\\", ":")):
        raise PanelRequestError(
            "panel.document.name_invalid",
            "Document name must not contain filesystem path syntax.",
        )
    normalized = re.sub(r"[^a-z0-9]+", "-", display_name.strip().casefold()).strip("-")
    normalized = normalized[:80].rstrip("-")
    if not normalized or _DOCUMENT_KEY.fullmatch(normalized) is None:
        raise PanelRequestError(
            "panel.document.name_invalid",
            "Document name must include letters or numbers.",
        )
    return normalized


def _display_name(document_key: str) -> str:
    return " ".join(part.capitalize() for part in document_key.split("-"))
