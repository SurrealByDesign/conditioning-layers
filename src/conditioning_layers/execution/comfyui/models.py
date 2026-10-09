"""Immutable ComfyUI execution inputs, observations, outputs, and results."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath, PureWindowsPath
import re
from types import MappingProxyType

from conditioning_layers.domain import ValidationFinding
from conditioning_layers.runtime.comfyui import CleanupPlan

from .errors import ExecutionPolicyError, ServerConfigurationError


EXECUTION_RESULT_VERSION = "conditioning-layers.comfyui-execution-result.v1"
EXECUTION_PROVENANCE_VERSION = "conditioning-layers.execution-provenance.v2"
EXECUTION_CLIENT_VERSION = "conditioning-layers.comfyui-execution-client.v2"

_CLIENT_IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class ExecutionState(str, Enum):
    NOT_SUBMITTED = "not_submitted"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    TIMED_OUT = "timed_out"
    UNKNOWN = "unknown"


class OutputVerificationMode(str, Enum):
    METADATA_ONLY = "metadata_only"


class CleanupRecommendationState(str, Enum):
    RETAIN = "retain"
    REVIEW_CHECKSUM_SAFE_PLAN = "review_checksum_safe_plan"
    NOT_ELIGIBLE = "not_eligible"


class ServerIdentityMode(str, Enum):
    """The explicit evidence route used to accept one running server."""

    EXACT_REVISION = "EXACT_REVISION"
    SEMANTIC_CONTRACT = "SEMANTIC_CONTRACT"


@dataclass(frozen=True, slots=True)
class ComfyUIServerConfiguration:
    """One explicit, bounded, loopback-only ComfyUI HTTP endpoint."""

    scheme: str = "http"
    host: str = "127.0.0.1"
    port: int = 8188
    api_base_path: str = ""
    connection_timeout_seconds: float = 5.0
    request_timeout_seconds: float = 30.0
    polling_interval_seconds: float = 1.0
    total_execution_timeout_seconds: float = 600.0
    local_only: bool = True
    client_identifier: str | None = None
    maximum_request_bytes: int = 8 * 1024 * 1024
    maximum_response_bytes: int = 8 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.scheme != "http":
            raise ServerConfigurationError("only the http scheme is supported")
        if not isinstance(self.host, str):
            raise ServerConfigurationError("server host must be a string")
        if self.local_only is not True or self.host.casefold() not in _LOCAL_HOSTS:
            raise ServerConfigurationError("server host must be an explicit loopback host")
        if any(token in self.host for token in ("@", "/", "?", "#")):
            raise ServerConfigurationError("server host must not contain credentials or URL syntax")
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise ServerConfigurationError("server port must be between 1 and 65535")
        if not _safe_base_path(self.api_base_path):
            raise ServerConfigurationError("API base path must be a safe relative URL path")
        _bounded_timeout("connection timeout", self.connection_timeout_seconds, 0.05, 60.0)
        _bounded_timeout("request timeout", self.request_timeout_seconds, 0.05, 300.0)
        _bounded_timeout("polling interval", self.polling_interval_seconds, 0.01, 60.0)
        _bounded_timeout("execution timeout", self.total_execution_timeout_seconds, 0.05, 7200.0)
        if self.polling_interval_seconds > self.total_execution_timeout_seconds:
            raise ServerConfigurationError("polling interval cannot exceed execution timeout")
        _bounded_byte_size("maximum request size", self.maximum_request_bytes)
        _bounded_byte_size("maximum response size", self.maximum_response_bytes)
        if self.client_identifier is not None and (
            not isinstance(self.client_identifier, str)
            or _CLIENT_IDENTIFIER.fullmatch(self.client_identifier) is None
        ):
            raise ServerConfigurationError("client identifier is invalid")


@dataclass(frozen=True, slots=True)
class ComfyUIExecutionPolicy:
    """Conservative first-slice execution and cleanup choices."""

    permit_prompt_cancellation_on_timeout: bool = False
    require_output_prefix_match: bool = True
    require_expected_save_image_node: bool = True
    output_verification_mode: OutputVerificationMode = OutputVerificationMode.METADATA_ONLY
    retain_staged_assets: bool = True
    recommend_checksum_safe_cleanup: bool = True

    def __post_init__(self) -> None:
        boolean_fields = (
            self.permit_prompt_cancellation_on_timeout,
            self.require_output_prefix_match,
            self.require_expected_save_image_node,
            self.retain_staged_assets,
            self.recommend_checksum_safe_cleanup,
        )
        if any(not isinstance(value, bool) for value in boolean_fields):
            raise ExecutionPolicyError("execution policy switches must be boolean")
        if self.output_verification_mode is not OutputVerificationMode.METADATA_ONLY:
            raise ExecutionPolicyError("only metadata-only output verification is supported")


@dataclass(frozen=True, slots=True)
class ServerIdentitySnapshot:
    """Portable evidence tying the running server to the validated bundle host."""

    profile_identifier: str
    comfyui_version: str
    comfyui_revision: str
    revision_evidence: str
    launch_arguments_sha256: str | None
    device_count: int
    identity_mode: ServerIdentityMode = ServerIdentityMode.EXACT_REVISION
    reported_comfyui_revision: str | None = None
    trusted_snapshot_fingerprint: str | None = None
    live_contract_fingerprint: str | None = None
    finding_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class QueueHistoryObservation:
    """One bounded poll observation for only the submitted prompt ID."""

    sequence: int
    elapsed_seconds: float
    state: ExecutionState
    in_running_queue: bool
    in_pending_queue: bool
    history_present: bool
    history_status: str | None


@dataclass(frozen=True, slots=True)
class AssociatedOutput:
    """One safe metadata-only output associated through terminal history."""

    node_id: str
    output_type: str
    filename: str
    subfolder: str
    storage_type: str
    relative_locator: str
    metadata: Mapping[str, object]

    def __post_init__(self) -> None:
        if isinstance(self.metadata, Mapping):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class ExecutionProvenance:
    """Portable execution identity without prompts, local roots, or response objects."""

    provenance_version: str
    client_version_identifier: str
    document_id: str
    adapter_identifier: str
    capability_identifier: str
    translation_plan_fingerprint: str
    graph_fingerprint: str
    bundle_fingerprint: str
    server_profile_identifier: str
    server_version: str
    server_revision: str
    prompt_id: str | None
    seed: int
    output_prefix: str
    active_layer_ids: tuple[str, ...]
    disabled_layer_ids: tuple[str, ...]
    field_hashes: tuple[tuple[str, str], ...]
    component_hashes: tuple[tuple[str, str], ...]
    warning_codes: tuple[str, ...]
    terminal_state: ExecutionState
    output_locators: tuple[str, ...]
    execution_error_codes: tuple[str, ...]
    provenance_fingerprint: str
    server_identity_mode: ServerIdentityMode | None = None
    reported_server_revision: str | None = None
    trusted_snapshot_fingerprint: str | None = None
    live_contract_fingerprint: str | None = None
    launch_arguments_sha256: str | None = None
    server_identity_finding_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CleanupRecommendation:
    """Non-destructive recommendation; the execution client deletes nothing."""

    state: CleanupRecommendationState
    reason_codes: tuple[str, ...]
    cleanup_plan: CleanupPlan | None


@dataclass(frozen=True, slots=True)
class ComfyUIExecutionResult:
    """Terminal or pre-submission result containing no live HTTP objects."""

    result_version: str
    bundle_fingerprint: str
    graph_fingerprint: str
    server_identity: ServerIdentitySnapshot | None
    prompt_id: str | None
    terminal_state: ExecutionState
    submitted: bool
    completed: bool
    submission_elapsed_seconds: float | None
    terminal_elapsed_seconds: float
    observations: tuple[QueueHistoryObservation, ...]
    outputs: tuple[AssociatedOutput, ...]
    errors: tuple[ValidationFinding, ...]
    warnings: tuple[ValidationFinding, ...]
    information: tuple[ValidationFinding, ...]
    provenance: ExecutionProvenance
    cleanup_recommendation: CleanupRecommendation
    result_identity_fingerprint: str


def _bounded_timeout(label: str, value: float, minimum: float, maximum: float) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not minimum <= value <= maximum:
        raise ServerConfigurationError(f"{label} is outside the supported bound")


def _bounded_byte_size(label: str, value: int) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1024 <= value <= 64 * 1024 * 1024
    ):
        raise ServerConfigurationError(f"{label} is outside the supported bound")


def _safe_base_path(value: str) -> bool:
    if not isinstance(value, str) or "\\" in value or "?" in value or "#" in value or "@" in value:
        return False
    if value in {"", "/"}:
        return True
    stripped = value.strip("/")
    posix = PurePosixPath(stripped)
    windows = PureWindowsPath(stripped)
    return (
        bool(stripped)
        and not posix.is_absolute()
        and not windows.is_absolute()
        and windows.drive == ""
        and all(part not in {"", ".", ".."} for part in posix.parts)
    )
