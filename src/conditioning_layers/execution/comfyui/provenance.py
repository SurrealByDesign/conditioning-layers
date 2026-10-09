"""Portable execution provenance and timing-independent identity fingerprints."""

from __future__ import annotations

import hashlib
import json

from conditioning_layers.domain import ValidationFinding
from conditioning_layers.runtime.comfyui import ComfyUISubmissionBundle

from .models import (
    EXECUTION_CLIENT_VERSION,
    EXECUTION_PROVENANCE_VERSION,
    AssociatedOutput,
    ExecutionProvenance,
    ExecutionState,
    ServerIdentitySnapshot,
)


def build_execution_provenance(
    *,
    bundle: ComfyUISubmissionBundle,
    server_identity: ServerIdentitySnapshot | None,
    prompt_id: str | None,
    terminal_state: ExecutionState,
    outputs: tuple[AssociatedOutput, ...],
    errors: tuple[ValidationFinding, ...],
    warnings: tuple[ValidationFinding, ...],
) -> ExecutionProvenance:
    """Build sanitized provenance without prompts, paths, or timing observations."""

    workflow = bundle.graph_artifact.provenance_inputs
    runtime = bundle.provenance
    warning_codes = tuple(
        dict.fromkeys(runtime.warning_codes + tuple(item.code for item in warnings))
    )
    error_codes = tuple(dict.fromkeys(item.code for item in errors))
    server_version = (
        server_identity.comfyui_version
        if server_identity is not None
        else runtime.comfyui_version
    )
    server_revision = (
        server_identity.comfyui_revision
        if server_identity is not None
        else runtime.comfyui_revision
    )
    server_profile = (
        server_identity.profile_identifier
        if server_identity is not None
        else runtime.host_profile_identifier
    )
    identity_mode = (
        server_identity.identity_mode if server_identity is not None else None
    )
    reported_revision = (
        server_identity.reported_comfyui_revision
        if server_identity is not None
        else None
    )
    trusted_snapshot_fingerprint = (
        server_identity.trusted_snapshot_fingerprint
        if server_identity is not None
        else runtime.node_contract_snapshot_fingerprint
    )
    live_contract_fingerprint = (
        server_identity.live_contract_fingerprint
        if server_identity is not None
        else None
    )
    launch_arguments_sha256 = (
        server_identity.launch_arguments_sha256
        if server_identity is not None
        else None
    )
    identity_finding_codes = (
        server_identity.finding_codes if server_identity is not None else ()
    )
    payload = {
        "provenance_version": EXECUTION_PROVENANCE_VERSION,
        "client_version_identifier": EXECUTION_CLIENT_VERSION,
        "document_id": runtime.document_id,
        "adapter_identifier": runtime.adapter_identifier,
        "capability_identifier": workflow.capability_identifier,
        "translation_plan_fingerprint": runtime.translation_plan_fingerprint,
        "graph_fingerprint": runtime.graph_fingerprint,
        "bundle_fingerprint": runtime.bundle_fingerprint,
        "server_profile_identifier": server_profile,
        "server_version": server_version,
        "server_revision": server_revision,
        "server_identity_mode": identity_mode.value if identity_mode is not None else None,
        "reported_server_revision": reported_revision,
        "trusted_snapshot_fingerprint": trusted_snapshot_fingerprint,
        "live_contract_fingerprint": live_contract_fingerprint,
        "launch_arguments_sha256": launch_arguments_sha256,
        "server_identity_finding_codes": list(identity_finding_codes),
        "prompt_id": prompt_id,
        "seed": runtime.seed,
        "output_prefix": runtime.output_prefix,
        "active_layer_ids": [item.layer_id for item in workflow.active_layers],
        "disabled_layer_ids": list(workflow.disabled_layer_ids),
        "field_hashes": [
            [item.layer_id, item.staged_sha256] for item in runtime.fields
        ],
        "component_hashes": [
            [item.role, item.sha256] for item in runtime.components
        ],
        "warning_codes": list(warning_codes),
        "terminal_state": terminal_state.value,
        "output_locators": [item.relative_locator for item in outputs],
        "execution_error_codes": list(error_codes),
    }
    fingerprint = _fingerprint(payload)
    return ExecutionProvenance(
        provenance_version=EXECUTION_PROVENANCE_VERSION,
        client_version_identifier=EXECUTION_CLIENT_VERSION,
        document_id=runtime.document_id,
        adapter_identifier=runtime.adapter_identifier,
        capability_identifier=workflow.capability_identifier,
        translation_plan_fingerprint=runtime.translation_plan_fingerprint,
        graph_fingerprint=runtime.graph_fingerprint,
        bundle_fingerprint=runtime.bundle_fingerprint,
        server_profile_identifier=server_profile,
        server_version=server_version,
        server_revision=server_revision,
        prompt_id=prompt_id,
        seed=runtime.seed,
        output_prefix=runtime.output_prefix,
        active_layer_ids=tuple(item.layer_id for item in workflow.active_layers),
        disabled_layer_ids=workflow.disabled_layer_ids,
        field_hashes=tuple(
            (item.layer_id, item.staged_sha256) for item in runtime.fields
        ),
        component_hashes=tuple(
            (item.role, item.sha256) for item in runtime.components
        ),
        warning_codes=warning_codes,
        terminal_state=terminal_state,
        output_locators=tuple(item.relative_locator for item in outputs),
        execution_error_codes=error_codes,
        provenance_fingerprint=fingerprint,
        server_identity_mode=identity_mode,
        reported_server_revision=reported_revision,
        trusted_snapshot_fingerprint=trusted_snapshot_fingerprint,
        live_contract_fingerprint=live_contract_fingerprint,
        launch_arguments_sha256=launch_arguments_sha256,
        server_identity_finding_codes=identity_finding_codes,
    )


def fingerprint_result_identity(
    provenance: ExecutionProvenance,
) -> str:
    """Fingerprint stable result identity while excluding poll timing observations."""

    return _fingerprint(
        {
            "provenance_fingerprint": provenance.provenance_fingerprint,
            "bundle_fingerprint": provenance.bundle_fingerprint,
            "graph_fingerprint": provenance.graph_fingerprint,
            "prompt_id": provenance.prompt_id,
            "terminal_state": provenance.terminal_state.value,
            "output_locators": list(provenance.output_locators),
            "error_codes": list(provenance.execution_error_codes),
        }
    )


def _fingerprint(payload: object) -> str:
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
