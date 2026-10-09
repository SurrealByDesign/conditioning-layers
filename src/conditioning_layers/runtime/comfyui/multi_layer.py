"""ADR-0024 runtime preparation; ordinary-v1 runtime contracts stay independent."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from enum import Enum
import hashlib
import json
from pathlib import Path

from conditioning_layers.assets import FieldInspectionResult
from conditioning_layers.comfyui.prediction_mixing import (
    ComfyUIComponentInventory,
    HostNodeContractSnapshot,
)
from conditioning_layers.comfyui.prediction_mixing.multi_layer import (
    MultiLayerGraphArtifact,
    MultiLayerWorkflowProvenance,
    validate_multi_layer_artifact,
)
from conditioning_layers.comfyui.prediction_mixing.multi_layer.canonical import freeze_json
from conditioning_layers.comfyui.prediction_mixing.multi_layer.authority import (
    INVENTORY, SNAPSHOT, realization_host_profile,
)
from conditioning_layers.domain import FindingSeverity, ValidationFinding

from .component_validation import validate_component_files
from .errors import deduplicate_findings, finding_codes, runtime_finding
from .host_validation import validate_local_host
from .models import (
    ComfyUIHostConfiguration,
    ComfyUIHostSnapshot,
    ComponentFileRecord,
    PortableComponentProvenance,
    StagedAssetRecord,
    _thaw_json,
)
from .staging import stage_field_assets, validate_field_sources


BUNDLE_VERSION = "conditioning-layers.comfyui-submission-bundle.v2"
RUNTIME_PROVENANCE_VERSION = "conditioning-layers.runtime-provenance.v2"


@dataclass(frozen=True, slots=True)
class SelectedExecutionReferences:
    """Private embedded layout for explicit execution-local authority references."""

    contract_identifier: str
    contract_version: int
    translation_plan_identifier: str
    translation_plan_version: int
    eligibility_entry_identifier: str
    eligibility_entry_fingerprint: str
    exact_admitted_cardinality: int
    realization_binding_identifier: str
    realization_binding_fingerprint: str
    execution_profile_identifier: str
    execution_profile_fingerprint: str
    graph_identifier: str
    graph_version: str


def selected_references(value: object) -> dict[str, object]:
    """Copy the selected instance declarations; no registry/admission state enters."""

    return {item.name: getattr(value, item.name) for item in fields(SelectedExecutionReferences)}


@dataclass(frozen=True, slots=True)
class MultiLayerPortableFieldProvenance:
    """Stable staged availability; copy/reuse observations remain in staging records."""

    layer_id: str
    document_reference: str
    source_sha256: str
    staged_filename: str
    staged_sha256: str


@dataclass(frozen=True, slots=True)
class MultiLayerRuntimeProvenance(SelectedExecutionReferences):
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
    fields: tuple[MultiLayerPortableFieldProvenance, ...]
    workflow_provenance: MultiLayerWorkflowProvenance
    seed: int
    output_prefix: str
    warning_codes: tuple[str, ...]
    bundle_fingerprint: str


@dataclass(frozen=True, slots=True)
class MultiLayerSubmissionBundle(SelectedExecutionReferences):
    bundle_version: str
    graph_artifact: MultiLayerGraphArtifact
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
    provenance: MultiLayerRuntimeProvenance
    submission_ready: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "graph_mapping", freeze_json(self.graph_mapping))

    def to_api_graph(self) -> dict[str, object]:
        return _thaw_json(self.graph_mapping)


@dataclass(frozen=True, slots=True)
class MultiLayerRuntimePreparationResult:
    bundle: MultiLayerSubmissionBundle | None
    host_snapshot: ComfyUIHostSnapshot | None
    component_records: tuple[ComponentFileRecord, ...]
    staged_assets: tuple[StagedAssetRecord, ...]
    errors: tuple[ValidationFinding, ...]
    warnings: tuple[ValidationFinding, ...]
    information: tuple[ValidationFinding, ...]
    unresolved_runtime_requirements: tuple[str, ...]
    ready: bool


def portable_value(value: object) -> object:
    """Canonical portable values with exact integers, including uint64 seeds."""

    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {item.name: portable_value(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {key: portable_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [portable_value(item) for item in value]
    return value


def fingerprint_portable(value: object) -> str:
    canonical = json.dumps(
        portable_value(value), ensure_ascii=False, allow_nan=False,
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _portable_components(records: tuple[ComponentFileRecord, ...]) -> tuple:
    return tuple(PortableComponentProvenance(
        role=item.role.value, category=item.category, filename=item.filename,
        byte_size=item.byte_size, sha256=item.sha256,
    ) for item in records)


def _portable_fields(records: tuple[StagedAssetRecord, ...]) -> tuple:
    return tuple(MultiLayerPortableFieldProvenance(
        layer_id=item.layer_id, document_reference=item.document_reference,
        source_sha256=item.expected_sha256, staged_filename=item.staged_filename,
        staged_sha256=item.observed_sha256,
    ) for item in records)


def fingerprint_multi_layer_submission_bundle(
    *, artifact: object, host_snapshot: ComfyUIHostSnapshot,
    components: tuple[ComponentFileRecord, ...],
    staged_assets: tuple[StagedAssetRecord, ...], warning_codes: tuple[str, ...],
) -> str:
    workflow = artifact.provenance_inputs
    return fingerprint_portable({
        "bundle_version": BUNDLE_VERSION,
        **selected_references(workflow),
        "graph_fingerprint": artifact.graph_fingerprint,
        "translation_plan_fingerprint": artifact.source_translation_plan_fingerprint,
        "workflow_provenance": workflow,
        "host": {
            "profile_identifier": host_snapshot.profile_identifier,
            "launch_profile_identifier": host_snapshot.launch_profile_identifier,
            "comfyui_version": host_snapshot.observed_comfyui_version,
            "comfyui_revision": host_snapshot.observed_comfyui_revision,
            "node_contract_snapshot_identifier": host_snapshot.node_contract_snapshot_identifier,
            "node_contract_snapshot_fingerprint": host_snapshot.node_contract_snapshot_fingerprint,
            "staging_cleanup_policy": host_snapshot.staging_cleanup_policy.value,
        },
        "components": _portable_components(components),
        "fields": _portable_fields(staged_assets),
        "warning_codes": warning_codes,
    })


def _build_runtime_provenance(
    artifact: object, host_snapshot: ComfyUIHostSnapshot,
    components: tuple[ComponentFileRecord, ...], staged_assets: tuple[StagedAssetRecord, ...],
    warning_codes: tuple[str, ...], bundle_fingerprint: str,
) -> MultiLayerRuntimeProvenance:
    workflow = artifact.provenance_inputs
    return MultiLayerRuntimeProvenance(
        **selected_references(workflow),
        provenance_version=RUNTIME_PROVENANCE_VERSION,
        document_id=workflow.document_id,
        translation_plan_fingerprint=artifact.source_translation_plan_fingerprint,
        graph_fingerprint=artifact.graph_fingerprint,
        adapter_identifier=artifact.adapter_identifier,
        inventory_identifier=workflow.component_inventory_identifier,
        host_profile_identifier=host_snapshot.profile_identifier,
        comfyui_version=host_snapshot.observed_comfyui_version,
        comfyui_revision=host_snapshot.observed_comfyui_revision,
        node_contract_snapshot_identifier=host_snapshot.node_contract_snapshot_identifier,
        node_contract_snapshot_fingerprint=host_snapshot.node_contract_snapshot_fingerprint,
        components=_portable_components(components), fields=_portable_fields(staged_assets),
        workflow_provenance=workflow, seed=workflow.seed,
        output_prefix=workflow.output_filename_prefix, warning_codes=warning_codes,
        bundle_fingerprint=bundle_fingerprint,
    )


def prepare_multi_layer_submission_bundle(
    artifact: object, workflow_provenance: object,
    inventory: ComfyUIComponentInventory, host_configuration: ComfyUIHostConfiguration,
    field_inspections: tuple[FieldInspectionResult, ...], source_asset_root: Path,
    node_contract_snapshot: HostNodeContractSnapshot | None,
) -> MultiLayerRuntimePreparationResult:
    """Prepare through retained host, component, current-byte and staging primitives."""

    artifact_errors = validate_multi_layer_artifact(artifact, workflow_provenance, inventory)
    if artifact_errors:
        return MultiLayerRuntimePreparationResult(
            None, None, (), (), artifact_errors, (), (), (), False,
        )
    host = validate_local_host(
        host_configuration, inventory, artifact.required_host_components, node_contract_snapshot,
    )
    components = validate_component_files(host_configuration, inventory)
    sources = validate_field_sources(
        artifact, workflow_provenance, field_inspections, source_asset_root, host_configuration,
    )
    errors = host.errors + components.errors + sources.errors
    warnings = host.warnings + components.warnings + sources.warnings
    information = host.information + components.information + sources.information
    if errors or not host.compatible or not components.verified or not sources.verified:
        return MultiLayerRuntimePreparationResult(
            None, host.snapshot, components.records, (), deduplicate_findings(errors or (_invalid_bundle(),)),
            deduplicate_findings(warnings), deduplicate_findings(information),
            host.unresolved_requirements, False,
        )
    staged = stage_field_assets(sources.candidates, host_configuration)
    warnings += staged.warnings
    information += staged.information
    if not staged.successful:
        return MultiLayerRuntimePreparationResult(
            None, host.snapshot, components.records, staged.records, staged.errors,
            deduplicate_findings(warnings), deduplicate_findings(information), (), False,
        )
    warning_codes = tuple(dict.fromkeys(artifact.warnings + finding_codes(warnings)))
    fingerprint = fingerprint_multi_layer_submission_bundle(
        artifact=artifact, host_snapshot=host.snapshot, components=components.records,
        staged_assets=staged.records, warning_codes=warning_codes,
    )
    provenance = _build_runtime_provenance(
        artifact, host.snapshot, components.records, staged.records, warning_codes, fingerprint,
    )
    bundle = MultiLayerSubmissionBundle(
        **selected_references(workflow_provenance), bundle_version=BUNDLE_VERSION,
        graph_artifact=artifact, graph_fingerprint=artifact.graph_fingerprint,
        translation_plan_fingerprint=artifact.source_translation_plan_fingerprint,
        document_id=workflow_provenance.document_id,
        adapter_identifier=artifact.adapter_identifier,
        inventory_identifier=inventory.inventory_identifier,
        profile_identifier=inventory.comfyui_profile_identifier,
        host_snapshot=host.snapshot, verified_components=components.records,
        staged_assets=staged.records, graph_mapping=artifact.to_api_graph(),
        expected_output_prefix=workflow_provenance.output_filename_prefix,
        runtime_seed=workflow_provenance.seed, warnings=warning_codes,
        unresolved_runtime_requirements=(), bundle_fingerprint=fingerprint,
        provenance=provenance, submission_ready=True,
    )
    bundle_errors = validate_multi_layer_submission_bundle(bundle)
    if bundle_errors:
        return MultiLayerRuntimePreparationResult(
            None, host.snapshot, components.records, staged.records, bundle_errors,
            deduplicate_findings(warnings), deduplicate_findings(information), (), False,
        )
    return MultiLayerRuntimePreparationResult(
        bundle, host.snapshot, components.records, staged.records, (),
        deduplicate_findings(warnings), deduplicate_findings(information), (), True,
    )


def validate_multi_layer_submission_bundle(
    bundle: object, *, verify_current_staged_bytes: bool = False,
) -> tuple[ValidationFinding, ...]:
    """Reconcile every explicit declaration against the complete selected graph."""

    if type(bundle) is not MultiLayerSubmissionBundle:
        return (_invalid_bundle(),)
    try:
        artifact = bundle.graph_artifact
        workflow = artifact.provenance_inputs
        # A reviewed binding selects its own committed host pins. Any other
        # binding fails the artifact check whatever the inventory, so the
        # retained pins only keep its historical diagnostics exact.
        host = (realization_host_profile(artifact.realization_binding)
                if type(artifact) is MultiLayerGraphArtifact else None)
        inventory, pinned_snapshot = (INVENTORY, SNAPSHOT) if host is None else (host.inventory, host.node_snapshot)
        errors = validate_multi_layer_artifact(
            artifact, workflow, inventory,
        )
        if errors:
            return errors
        selected = selected_references(workflow)
        expected_fingerprint = fingerprint_multi_layer_submission_bundle(
            artifact=artifact, host_snapshot=bundle.host_snapshot,
            components=bundle.verified_components, staged_assets=bundle.staged_assets,
            warning_codes=bundle.warnings,
        )
        expected_provenance = _build_runtime_provenance(
            artifact, bundle.host_snapshot, bundle.verified_components,
            bundle.staged_assets, bundle.warnings, expected_fingerprint,
        )
        expected_fields = tuple((item.layer_id, item.document_field_reference,
                                 item.field_checksum, item.staged_field_filename)
                                for item in workflow.active_layers)
        staged_fields = tuple((item.layer_id, item.document_reference,
                               item.expected_sha256, item.staged_filename)
                              for item in bundle.staged_assets)
        expected_components = (
            ("model", "diffusion_models", inventory.model_filename, inventory.model_size_bytes, inventory.model_sha256),
            ("text_encoder", "text_encoders", inventory.text_encoder_filename, inventory.text_encoder_size_bytes, inventory.text_encoder_sha256),
            ("vae", "vae", inventory.vae_filename, inventory.vae_size_bytes, inventory.vae_sha256),
        )
        actual_components = tuple((item.role.value, item.category, item.filename,
                                   item.byte_size, item.sha256)
                                  for item in bundle.verified_components)
        snapshot = bundle.host_snapshot
        if (
            bundle.bundle_version != BUNDLE_VERSION
            or bundle.submission_ready is not True or bundle.unresolved_runtime_requirements
            or fingerprint_portable(selected_references(bundle)) != fingerprint_portable(selected)
            or type(bundle.exact_admitted_cardinality) is not int
            or fingerprint_portable(bundle.to_api_graph()) != fingerprint_portable(artifact.to_api_graph())
            or tuple(bundle.graph_mapping) != tuple(artifact.canonical_graph)
            or bundle.graph_fingerprint != artifact.graph_fingerprint
            or bundle.translation_plan_fingerprint != artifact.source_translation_plan_fingerprint
            or bundle.document_id != workflow.document_id
            or bundle.adapter_identifier != artifact.adapter_identifier
            or bundle.inventory_identifier != inventory.inventory_identifier
            or bundle.profile_identifier != inventory.comfyui_profile_identifier
            or bundle.runtime_seed != workflow.seed or type(bundle.runtime_seed) is not int
            or bundle.expected_output_prefix != workflow.output_filename_prefix
            or type(bundle.warnings) is not tuple
            or bundle.warnings[:len(artifact.warnings)] != artifact.warnings
            or len(set(bundle.warnings)) != len(bundle.warnings)
            or bundle.bundle_fingerprint != expected_fingerprint
            or type(bundle.provenance) is not MultiLayerRuntimeProvenance
            or fingerprint_portable(bundle.provenance) != fingerprint_portable(expected_provenance)
            or type(bundle.provenance.exact_admitted_cardinality) is not int
            or expected_fields != staged_fields
            or len(expected_fields) != bundle.exact_admitted_cardinality
            or actual_components != expected_components
            or snapshot.filesystem_verified is not True or snapshot.node_contracts_verified is not True
            or snapshot.profile_identifier != inventory.comfyui_profile_identifier
            or snapshot.observed_comfyui_version != inventory.expected_comfyui_version
            or snapshot.observed_comfyui_revision != inventory.expected_comfyui_revision
            or snapshot.node_contract_snapshot_identifier != pinned_snapshot.snapshot_identifier
            or snapshot.node_contract_snapshot_fingerprint != pinned_snapshot.snapshot_fingerprint
            or any(item.verified is not True or item.expected_sha256 != item.sha256
                   or item.expected_byte_size != item.byte_size for item in bundle.verified_components)
            or any(item.successful is not True or item.observed_sha256 != item.expected_sha256
                   for item in bundle.staged_assets)
        ):
            return (_invalid_bundle(),)
        if verify_current_staged_bytes:
            root = snapshot.input_directory.resolve(strict=True)
            for item in bundle.staged_assets:
                destination = item.destination_path.resolve(strict=True)
                if (not destination.is_relative_to(root)
                    or destination != root.joinpath(*item.staged_filename.split("/"))
                    or hashlib.sha256(destination.read_bytes()).hexdigest() != item.expected_sha256):
                    return (_invalid_bundle(),)
    except (AttributeError, KeyError, TypeError, ValueError, OSError, RuntimeError):
        return (_invalid_bundle(),)
    return ()


def _invalid_bundle() -> ValidationFinding:
    return runtime_finding(
        "runtime.multi_layer_bundle_invalid", FindingSeverity.ERROR,
        "Multi-layer bundle declarations, authority, or verified evidence disagree.",
        field_path="bundle",
    )
