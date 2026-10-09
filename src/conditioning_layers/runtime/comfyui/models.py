"""Immutable local-host, staging, bundle, and portable provenance models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType

from conditioning_layers.comfyui.prediction_mixing import (
    ComfyUIApiGraphArtifact,
    HostNodeContractRecord,
    HostNodeContractSnapshot,
)
from conditioning_layers.domain import ValidationFinding


BUNDLE_VERSION = "conditioning-layers.comfyui-submission-bundle.v1"
RUNTIME_PROVENANCE_VERSION = "conditioning-layers.runtime-provenance.v1"


class HostCompatibilityStatus(str, Enum):
    """Four explicit outcomes for independently checked host evidence."""

    EXACT_MATCH = "exact_match"
    SUPPORTED_MISMATCH = "supported_mismatch"
    UNSUPPORTED_MISMATCH = "unsupported_mismatch"
    UNABLE_TO_VERIFY = "unable_to_verify"


class StagingCleanupPolicy(str, Enum):
    """Who decides whether eligible files are eventually removed."""

    CALLER_MANAGED = "caller_managed"
    BUNDLE_MANAGED = "bundle_managed"


class ComponentRole(str, Enum):
    """The three model-file roles in the canonical prototype profile."""

    MODEL = "model"
    TEXT_ENCODER = "text_encoder"
    VAE = "vae"


class StagingDisposition(str, Enum):
    """Outcome for one requested field destination."""

    CREATED = "created"
    REUSED = "reused"
    COLLISION_REJECTED = "collision_rejected"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ComfyUIHostConfiguration:
    """Caller-selected local installation; no automatic discovery is performed."""

    comfyui_root: Path
    input_directory: Path
    output_directory: Path
    user_directory: Path | None
    model_root: Path
    model_directories: Mapping[str, tuple[Path, ...]]
    git_checkout_path: Path
    supported_profile_identifier: str
    launch_profile_identifier: str | None = None
    staging_cleanup_policy: StagingCleanupPolicy = StagingCleanupPolicy.CALLER_MANAGED
    checkout_trusted_root: Path | None = None
    data_trusted_root: Path | None = None
    model_trusted_root: Path | None = None

    def __post_init__(self) -> None:
        if isinstance(self.model_directories, Mapping):
            frozen = {
                str(category): tuple(paths)
                for category, paths in self.model_directories.items()
            }
            object.__setattr__(self, "model_directories", MappingProxyType(frozen))


@dataclass(frozen=True, slots=True)
class ComfyUIHostSnapshot:
    """Internal verified host evidence; local paths are intentionally non-portable."""

    profile_identifier: str
    launch_profile_identifier: str | None
    comfyui_root: Path
    input_directory: Path
    output_directory: Path
    user_directory: Path | None
    model_root: Path
    git_checkout_path: Path
    observed_comfyui_version: str | None
    observed_comfyui_revision: str | None
    version_status: HostCompatibilityStatus
    revision_status: HostCompatibilityStatus
    node_contract_snapshot_identifier: str | None
    node_contract_snapshot_fingerprint: str | None
    staging_cleanup_policy: StagingCleanupPolicy
    filesystem_verified: bool
    node_contracts_verified: bool


@dataclass(frozen=True, slots=True)
class HostValidationResult:
    """Read-only host validation result with an internal snapshot when possible."""

    snapshot: ComfyUIHostSnapshot
    errors: tuple[ValidationFinding, ...]
    warnings: tuple[ValidationFinding, ...]
    information: tuple[ValidationFinding, ...]
    compatible: bool
    unresolved_requirements: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ComponentFileRecord:
    """One narrowly resolved component file and its read-only verification."""

    role: ComponentRole
    category: str
    filename: str
    local_path: Path | None
    byte_size: int | None
    sha256: str | None
    expected_byte_size: int | None
    expected_sha256: str | None
    verified: bool


@dataclass(frozen=True, slots=True)
class ComponentValidationResult:
    """All three component checks without loading model data."""

    records: tuple[ComponentFileRecord, ...]
    errors: tuple[ValidationFinding, ...]
    warnings: tuple[ValidationFinding, ...]
    information: tuple[ValidationFinding, ...]
    verified: bool


@dataclass(frozen=True, slots=True)
class FieldStagingCandidate:
    """A certified source paired with its exact graph destination."""

    layer_id: str
    document_reference: str
    source_path: Path
    source_sha256: str
    byte_size: int
    staged_filename: str
    destination_path: Path


@dataclass(frozen=True, slots=True)
class FieldSourceValidationResult:
    """Pre-copy field coverage and unchanged-byte validation."""

    candidates: tuple[FieldStagingCandidate, ...]
    errors: tuple[ValidationFinding, ...]
    warnings: tuple[ValidationFinding, ...]
    information: tuple[ValidationFinding, ...]
    verified: bool


@dataclass(frozen=True, slots=True)
class StagedAssetRecord:
    """One created, reused, rejected, or failed staging request."""

    layer_id: str
    document_reference: str
    staged_filename: str
    source_path: Path
    destination_path: Path
    expected_sha256: str
    observed_sha256: str | None
    byte_size: int
    disposition: StagingDisposition
    successful: bool
    cleanup_eligible: bool


@dataclass(frozen=True, slots=True)
class FieldStagingResult:
    """Byte-preserving staging outcome; no execution side effect follows."""

    records: tuple[StagedAssetRecord, ...]
    errors: tuple[ValidationFinding, ...]
    warnings: tuple[ValidationFinding, ...]
    information: tuple[ValidationFinding, ...]
    successful: bool


@dataclass(frozen=True, slots=True)
class PortableComponentProvenance:
    """Component identity without private host paths."""

    role: str
    category: str
    filename: str
    byte_size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class PortableFieldProvenance:
    """Source and staged field identity without private host paths."""

    layer_id: str
    document_reference: str
    source_sha256: str
    staged_filename: str
    staged_sha256: str
    disposition: str


@dataclass(frozen=True, slots=True)
class RuntimeProvenance:
    """Portable pre-submission provenance with no result or timestamp."""

    provenance_version: str
    document_id: str
    translation_plan_fingerprint: str
    graph_fingerprint: str
    adapter_identifier: str
    inventory_identifier: str
    host_profile_identifier: str
    comfyui_version: str
    comfyui_revision: str
    node_contract_snapshot_identifier: str
    node_contract_snapshot_fingerprint: str
    components: tuple[PortableComponentProvenance, ...]
    fields: tuple[PortableFieldProvenance, ...]
    seed: int
    output_prefix: str
    warning_codes: tuple[str, ...]
    bundle_fingerprint: str


@dataclass(frozen=True, slots=True)
class ComfyUISubmissionBundle:
    """Verified local bundle ready for a later, separate submission client."""

    bundle_version: str
    graph_artifact: ComfyUIApiGraphArtifact
    graph_fingerprint: str
    translation_plan_fingerprint: str
    document_id: str
    adapter_identifier: str
    inventory_identifier: str
    profile_identifier: str
    host_snapshot: ComfyUIHostSnapshot
    verified_components: tuple[ComponentFileRecord, ...]
    staged_assets: tuple[StagedAssetRecord, ...]
    graph_mapping: Mapping[str, object]
    expected_output_prefix: str
    runtime_seed: int
    warnings: tuple[str, ...]
    unresolved_runtime_requirements: tuple[str, ...]
    bundle_fingerprint: str
    provenance: RuntimeProvenance
    submission_ready: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "graph_mapping", _freeze_json(self.graph_mapping))

    def to_api_graph(self) -> dict[str, object]:
        """Return an isolated mapping for a later authorized submission slice."""

        return _thaw_json(self.graph_mapping)  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class RuntimePreparationResult:
    """Submission bundle or deterministic reasons that preparation is unsafe."""

    bundle: ComfyUISubmissionBundle | None
    host_snapshot: ComfyUIHostSnapshot
    component_records: tuple[ComponentFileRecord, ...]
    staged_assets: tuple[StagedAssetRecord, ...]
    errors: tuple[ValidationFinding, ...]
    warnings: tuple[ValidationFinding, ...]
    information: tuple[ValidationFinding, ...]
    unresolved_runtime_requirements: tuple[str, ...]
    ready: bool


@dataclass(frozen=True, slots=True)
class CleanupPlanItem:
    """Checksum-proven deletion candidate; this model performs no deletion."""

    staged_filename: str
    destination_path: Path
    expected_sha256: str


@dataclass(frozen=True, slots=True)
class CleanupPlan:
    """Read-only cleanup proposal limited to assets created by one bundle."""

    bundle_fingerprint: str
    items: tuple[CleanupPlanItem, ...]
    errors: tuple[ValidationFinding, ...]
    safe_to_execute_elsewhere: bool


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value
