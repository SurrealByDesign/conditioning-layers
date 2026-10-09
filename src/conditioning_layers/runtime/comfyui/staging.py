"""Certified source validation, byte-preserving staging, and cleanup planning."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import tempfile

from conditioning_layers.assets import FieldInspectionResult
from conditioning_layers.assets.errors import AssetInspectionError
from conditioning_layers.assets.paths import resolve_field_asset
from conditioning_layers.comfyui.prediction_mixing import (
    ComfyUIApiGraphArtifact,
    WorkflowGenerationProvenance,
)
from conditioning_layers.domain import FindingSeverity, ValidationFinding

from .errors import deduplicate_findings, runtime_finding
from .models import (
    CleanupPlan,
    CleanupPlanItem,
    ComfyUIHostConfiguration,
    ComfyUISubmissionBundle,
    FieldSourceValidationResult,
    FieldStagingCandidate,
    FieldStagingResult,
    StagedAssetRecord,
    StagingDisposition,
)


_SAFE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_URI_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def staging_namespace_for_document(document_id: str) -> str:
    """Return a deterministic safe namespace beneath the ComfyUI input root."""

    if isinstance(document_id, str) and _safe_token(document_id):
        token = document_id
    else:
        encoded = document_id.encode("utf-8") if isinstance(document_id, str) else b""
        token = "doc-" + hashlib.sha256(encoded).hexdigest()[:24]
    return f"conditioning-layers/{token}"


def validate_field_sources(
    artifact: ComfyUIApiGraphArtifact,
    provenance: WorkflowGenerationProvenance,
    inspection_results: tuple[FieldInspectionResult, ...],
    source_asset_root: Path,
    configuration: ComfyUIHostConfiguration,
) -> FieldSourceValidationResult:
    """Verify certification and unchanged bytes without decoding pixels again."""

    errors: list[ValidationFinding] = []
    information: list[ValidationFinding] = []
    candidates: list[FieldStagingCandidate] = []
    expected_layers = tuple(layer.layer_id for layer in provenance.active_layers)
    inspections_by_layer: dict[str, FieldInspectionResult] = {}
    for inspection in inspection_results:
        layer_id = inspection.profile.layer_id if inspection.profile is not None else ""
        if not layer_id or layer_id in inspections_by_layer:
            errors.append(
                runtime_finding(
                    "runtime.staging_missing",
                    FindingSeverity.ERROR,
                    "Certified field inspections must have unique Active Layer IDs.",
                    field_path="field_inspections",
                )
            )
        else:
            inspections_by_layer[layer_id] = inspection
    actual_layers = set(inspections_by_layer)
    if set(expected_layers) - actual_layers:
        errors.append(
            runtime_finding(
                "runtime.staging_missing",
                FindingSeverity.ERROR,
                "A certified source field inspection is missing for an Active Layer.",
                field_path="field_inspections",
            )
        )
    if actual_layers - set(expected_layers):
        errors.append(
            runtime_finding(
                "runtime.staging_extra",
                FindingSeverity.ERROR,
                "Field inspections include a layer that the graph will not stage.",
                field_path="field_inspections",
            )
        )

    try:
        resolved_asset_root = source_asset_root.resolve(strict=True)
        resolved_input_root = configuration.input_directory.resolve(strict=True)
        if not source_asset_root.is_absolute() or not resolved_asset_root.is_dir():
            raise ValueError("asset root is not an absolute directory")
    except (OSError, RuntimeError, ValueError):
        errors.append(
            runtime_finding(
                "runtime.staging_missing",
                FindingSeverity.ERROR,
                "The source document asset root is not a readable absolute directory.",
                field_path="source_asset_root",
            )
        )
        return FieldSourceValidationResult(
            candidates=(),
            errors=deduplicate_findings(errors),
            warnings=(),
            information=(),
            verified=False,
        )

    graph_field_names = _graph_field_names(artifact)
    provenance_field_names = tuple(
        layer.staged_field_filename for layer in provenance.active_layers
    )
    if graph_field_names != provenance_field_names:
        errors.append(
            runtime_finding(
                "runtime.staging_missing",
                FindingSeverity.ERROR,
                "Graph field inputs do not match workflow-generation provenance order.",
                field_path="graph",
            )
        )

    namespace = staging_namespace_for_document(provenance.document_id)
    for layer in provenance.active_layers:
        inspection = inspections_by_layer.get(layer.layer_id)
        if inspection is None:
            continue
        if (
            not inspection.certified
            or inspection.profile is None
            or inspection.dimension_validation is None
            or not inspection.dimension_validation.certified
            or not inspection.dimension_validation.matches
            or inspection.profile.relative_path != layer.document_field_reference
            or inspection.source_reference != layer.document_field_reference
            or inspection.checksum is None
            or inspection.profile.checksum != inspection.checksum
            or layer.field_checksum is None
            or layer.field_checksum.casefold() != inspection.checksum.casefold()
        ):
            errors.append(
                runtime_finding(
                    "runtime.field_source_changed",
                    FindingSeverity.ERROR,
                    "Field certification does not match graph-generation provenance.",
                    layer_id=layer.layer_id,
                    field_path="field_inspections",
                )
            )
            continue
        staged_filename = layer.staged_field_filename
        if not _safe_staged_filename(staged_filename, namespace):
            errors.append(
                runtime_finding(
                    "runtime.staging_missing",
                    FindingSeverity.ERROR,
                    "Staged filename is unsafe or outside the deterministic document namespace.",
                    layer_id=layer.layer_id,
                    field_path="workflow_provenance.active_layers.staged_field_filename",
                )
            )
            continue
        try:
            resolved_source = resolve_field_asset(
                resolved_asset_root, layer.document_field_reference
            ).path
            observed_sha256, byte_size = _sha256_and_size(resolved_source)
        except (AssetInspectionError, OSError):
            errors.append(
                runtime_finding(
                    "runtime.staging_missing",
                    FindingSeverity.ERROR,
                    "Certified source field is missing or unreadable.",
                    layer_id=layer.layer_id,
                    field_path="source_asset_root",
                )
            )
            continue
        if observed_sha256.casefold() != inspection.checksum.casefold():
            errors.append(
                runtime_finding(
                    "runtime.field_source_changed",
                    FindingSeverity.ERROR,
                    "Source field bytes changed after certification.",
                    layer_id=layer.layer_id,
                    field_path="source_asset_root",
                )
            )
            continue
        destination = resolved_input_root.joinpath(*staged_filename.split("/"))
        try:
            resolved_destination = destination.resolve(strict=False)
            if not resolved_destination.is_relative_to(resolved_input_root):
                raise ValueError("destination escapes input root")
        except (OSError, RuntimeError, ValueError):
            errors.append(
                runtime_finding(
                    "runtime.staging_missing",
                    FindingSeverity.ERROR,
                    "Staged destination resolves outside the configured input directory.",
                    layer_id=layer.layer_id,
                    field_path="host.input_directory",
                )
            )
            continue
        candidates.append(
            FieldStagingCandidate(
                layer_id=layer.layer_id,
                document_reference=layer.document_field_reference,
                source_path=resolved_source,
                source_sha256=observed_sha256,
                byte_size=byte_size,
                staged_filename=staged_filename,
                destination_path=destination,
            )
        )
        information.append(
            runtime_finding(
                "runtime.field_source_verified",
                FindingSeverity.INFORMATION,
                "Certified field source remains byte-identical to its inspection record.",
                layer_id=layer.layer_id,
                field_path="source_asset_root",
            )
        )

    errors_tuple = deduplicate_findings(errors)
    return FieldSourceValidationResult(
        candidates=tuple(candidates),
        errors=errors_tuple,
        warnings=(),
        information=deduplicate_findings(information),
        verified=(not errors_tuple and len(candidates) == len(expected_layers)),
    )


def stage_field_assets(
    candidates: tuple[FieldStagingCandidate, ...],
    configuration: ComfyUIHostConfiguration,
) -> FieldStagingResult:
    """Copy certified bytes atomically without replacing differing destinations."""

    errors: list[ValidationFinding] = []
    information: list[ValidationFinding] = []
    records: list[StagedAssetRecord] = []
    reuse_by_layer: dict[str, str] = {}

    for candidate in candidates:
        try:
            if candidate.destination_path.exists():
                if not candidate.destination_path.is_file():
                    raise OSError("destination is not a regular file")
                existing_hash, _ = _sha256_and_size(candidate.destination_path)
                if existing_hash.casefold() != candidate.source_sha256.casefold():
                    errors.append(
                        runtime_finding(
                            "runtime.staging_collision",
                            FindingSeverity.ERROR,
                            "Existing staged destination has different bytes and will not be overwritten.",
                            layer_id=candidate.layer_id,
                            field_path="host.input_directory",
                        )
                    )
                    records.append(
                        _staging_record(
                            candidate,
                            disposition=StagingDisposition.COLLISION_REJECTED,
                            observed_sha256=existing_hash,
                        )
                    )
                else:
                    reuse_by_layer[candidate.layer_id] = existing_hash
        except OSError:
            errors.append(
                runtime_finding(
                    "runtime.staging_collision",
                    FindingSeverity.ERROR,
                    "Existing staged destination cannot be safely inspected.",
                    layer_id=candidate.layer_id,
                    field_path="host.input_directory",
                )
            )
            records.append(
                _staging_record(candidate, disposition=StagingDisposition.FAILED)
            )
    if errors:
        return FieldStagingResult(
            records=tuple(records),
            errors=deduplicate_findings(errors),
            warnings=(),
            information=(),
            successful=False,
        )

    input_root = configuration.input_directory.resolve(strict=True)
    for candidate in candidates:
        if candidate.layer_id in reuse_by_layer:
            records.append(
                _staging_record(
                    candidate,
                    disposition=StagingDisposition.REUSED,
                    observed_sha256=reuse_by_layer[candidate.layer_id],
                )
            )
            information.append(
                runtime_finding(
                    "runtime.staging_reused",
                    FindingSeverity.INFORMATION,
                    "An existing byte-identical staged field was reused.",
                    layer_id=candidate.layer_id,
                    field_path="host.input_directory",
                )
            )
            continue
        temp_path: Path | None = None
        created = False
        try:
            candidate.destination_path.parent.mkdir(parents=True, exist_ok=True)
            resolved_parent = candidate.destination_path.parent.resolve(strict=True)
            if not resolved_parent.is_relative_to(input_root):
                raise OSError("staging parent escapes input root")
            with tempfile.NamedTemporaryFile(
                mode="xb",
                prefix=".conditioning-layers-",
                suffix=".tmp",
                dir=resolved_parent,
                delete=False,
            ) as temporary:
                temp_path = Path(temporary.name)
                with candidate.source_path.open("rb") as source:
                    shutil.copyfileobj(source, temporary, length=1024 * 1024)
                temporary.flush()
                os.fsync(temporary.fileno())
            temporary_hash, temporary_size = _sha256_and_size(temp_path)
            if (
                temporary_hash.casefold() != candidate.source_sha256.casefold()
                or temporary_size != candidate.byte_size
            ):
                raise OSError("temporary staging checksum mismatch")
            try:
                os.link(temp_path, candidate.destination_path)
                created = True
            except FileExistsError:
                existing_hash, _ = _sha256_and_size(candidate.destination_path)
                if existing_hash.casefold() != candidate.source_sha256.casefold():
                    raise OSError("destination appeared with different bytes")
            destination_hash, destination_size = _sha256_and_size(
                candidate.destination_path
            )
            if (
                destination_hash.casefold() != candidate.source_sha256.casefold()
                or destination_size != candidate.byte_size
            ):
                if created:
                    candidate.destination_path.unlink(missing_ok=True)
                raise OSError("published staging checksum mismatch")
            disposition = (
                StagingDisposition.CREATED if created else StagingDisposition.REUSED
            )
            records.append(
                _staging_record(
                    candidate,
                    disposition=disposition,
                    observed_sha256=destination_hash,
                )
            )
            information.append(
                runtime_finding(
                    (
                        "runtime.staging_created"
                        if created
                        else "runtime.staging_reused"
                    ),
                    FindingSeverity.INFORMATION,
                    (
                        "A certified field was staged byte-for-byte."
                        if created
                        else "A concurrently created byte-identical field was reused."
                    ),
                    layer_id=candidate.layer_id,
                    field_path="host.input_directory",
                )
            )
        except OSError:
            errors.append(
                runtime_finding(
                    "runtime.staging_checksum",
                    FindingSeverity.ERROR,
                    "Field staging failed or could not prove the destination checksum.",
                    layer_id=candidate.layer_id,
                    field_path="host.input_directory",
                )
            )
            records.append(
                _staging_record(candidate, disposition=StagingDisposition.FAILED)
            )
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    errors.append(
                        runtime_finding(
                            "runtime.staging_checksum",
                            FindingSeverity.ERROR,
                            "Temporary staging data could not be cleaned safely.",
                            layer_id=candidate.layer_id,
                            field_path="host.input_directory",
                        )
                    )

    errors_tuple = deduplicate_findings(errors)
    return FieldStagingResult(
        records=tuple(records),
        errors=errors_tuple,
        warnings=(),
        information=deduplicate_findings(information),
        successful=(
            not errors_tuple
            and len(records) == len(candidates)
            and all(record.successful for record in records)
        ),
    )


def build_cleanup_plan(bundle: ComfyUISubmissionBundle) -> CleanupPlan:
    """Identify checksum-proven created files without deleting anything."""

    errors: list[ValidationFinding] = []
    items: list[CleanupPlanItem] = []
    input_root = bundle.host_snapshot.input_directory.resolve(strict=True)
    for record in bundle.staged_assets:
        if not record.cleanup_eligible or record.disposition is not StagingDisposition.CREATED:
            continue
        try:
            destination = record.destination_path.resolve(strict=True)
            if not destination.is_relative_to(input_root) or not destination.is_file():
                raise OSError("cleanup path is invalid")
            observed_sha256, _ = _sha256_and_size(destination)
            if observed_sha256.casefold() != record.expected_sha256.casefold():
                raise ValueError("cleanup checksum changed")
            items.append(
                CleanupPlanItem(
                    staged_filename=record.staged_filename,
                    destination_path=destination,
                    expected_sha256=record.expected_sha256,
                )
            )
        except (OSError, RuntimeError, ValueError):
            errors.append(
                runtime_finding(
                    "runtime.staging_checksum",
                    FindingSeverity.ERROR,
                    "Cleanup planning refused a missing, changed, or escaping staged file.",
                    layer_id=record.layer_id,
                    field_path="cleanup",
                )
            )
    errors_tuple = deduplicate_findings(errors)
    return CleanupPlan(
        bundle_fingerprint=bundle.bundle_fingerprint,
        items=tuple(items),
        errors=errors_tuple,
        safe_to_execute_elsewhere=not errors_tuple,
    )


def _graph_field_names(artifact: ComfyUIApiGraphArtifact) -> tuple[str, ...]:
    names: list[str] = []
    for node in artifact.to_api_graph().values():
        if isinstance(node, dict) and node.get("class_type") == "LoadImageMask":
            inputs = node.get("inputs")
            if isinstance(inputs, dict) and isinstance(inputs.get("image"), str):
                names.append(inputs["image"])
    return tuple(names)


def _safe_staged_filename(value: str, namespace: str) -> bool:
    if (
        not isinstance(value, str)
        or not value.lower().endswith(".png")
        or "\\" in value
        or "\x00" in value
        or _URI_PATTERN.match(value)
        or any(character in value for character in '<>:"|?*')
    ):
        return False
    windows = PureWindowsPath(value)
    posix = PurePosixPath(value)
    if windows.drive or windows.is_absolute() or posix.is_absolute():
        return False
    parts = value.split("/")
    return (
        len(parts) == 3
        and "/".join(parts[:2]) == namespace
        and all(part not in {"", ".", ".."} for part in parts)
        and _safe_token(parts[-1])
    )


def _safe_token(value: str) -> bool:
    if _SAFE_TOKEN_PATTERN.fullmatch(value) is None or value in {".", ".."}:
        return False
    stem = value.split(".", 1)[0].upper()
    return stem not in _WINDOWS_RESERVED_NAMES


def _sha256_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def _staging_record(
    candidate: FieldStagingCandidate,
    *,
    disposition: StagingDisposition,
    observed_sha256: str | None = None,
) -> StagedAssetRecord:
    successful = disposition in {StagingDisposition.CREATED, StagingDisposition.REUSED}
    return StagedAssetRecord(
        layer_id=candidate.layer_id,
        document_reference=candidate.document_reference,
        staged_filename=candidate.staged_filename,
        source_path=candidate.source_path,
        destination_path=candidate.destination_path,
        expected_sha256=candidate.source_sha256,
        observed_sha256=observed_sha256,
        byte_size=candidate.byte_size,
        disposition=disposition,
        successful=successful,
        cleanup_eligible=disposition is StagingDisposition.CREATED,
    )
