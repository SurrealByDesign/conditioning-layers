"""ADR-0026 Blend-only preparation with independently verified project availability."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import sys
from types import CodeType, FunctionType

from conditioning_layers.comfyui.prediction_mixing.blend_component import (
    BLEND_NODE_CLASS, BlendComponentIdentity,
    validate_blend_component_identity, verify_blend_component_source,
)

from conditioning_layers.assets import FieldInspectionResult
from conditioning_layers.comfyui.prediction_mixing import (
    ComfyUIComponentInventory,
    HostNodeContractSnapshot,
)
from conditioning_layers.comfyui.prediction_mixing.blend import (
    BlendGraphArtifact,
    BlendWorkflowProvenance,
    realization_host_profile,
    validate_blend_artifact,
)
from conditioning_layers.comfyui.prediction_mixing.multi_layer.canonical import freeze_json
from conditioning_layers.comfyui.prediction_mixing.multi_layer.authority import INVENTORY, SNAPSHOT
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


BUNDLE_VERSION = "conditioning-layers.comfyui-submission-bundle.v3"
RUNTIME_PROVENANCE_VERSION = "conditioning-layers.runtime-provenance.v3"


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
    composition_policy_identifier: str
    composition_policy_version: int
    composition_policy_fingerprint: str
    project_component_identifier: str
    project_component_implementation_fingerprint: str
    permitted_class_authority_identifier: str
    permitted_class_authority_fingerprint: str


def selected_references(value: object) -> dict[str, object]:
    """Copy the selected instance declarations; no registry/admission state enters."""

    return {item.name: getattr(value, item.name) for item in fields(SelectedExecutionReferences)}


@dataclass(frozen=True, slots=True)
class BlendComponentAvailability:
    """Target-process registration observation, never a remote class attestation.

    The process ID is a freshness check, excluded from portable identity. Actual
    registration and source are rechecked before preparation and submission.
    This record asserts neither qualification nor observed prepared tensor bytes.
    """

    implementation: BlendComponentIdentity
    process_id: int
    launch_arguments: tuple[str, ...]
    available: bool


def _valid_launch_arguments(arguments: object) -> bool:
    if (type(arguments) is not tuple or not arguments
            or any(type(item) is not str or not item for item in arguments)):
        return False
    if not any(Path(item).name.casefold() == "main.py" for item in arguments):
        return False
    # Unqualified intermediate dtype/device settings fail this route only.
    if any(item.split("=", 1)[0] in (
        "--fp16-intermediates", "--force-fp16", "--cpu", "--directml",
    ) for item in arguments):
        return False
    return True


def _registered_component_matches() -> bool:
    """Observe this route's registration; the component owns only dtype checks."""
    try:
        from conditioning_layers.comfyui.prediction_mixing.blend_node import (
            ConditioningLayersNormalizedBlend, blend_runtime_dtype_available,
        )
        host_nodes = sys.modules.get("nodes")
        mapping = getattr(host_nodes, "NODE_CLASS_MAPPINGS", None)
        node = mapping.get(BLEND_NODE_CLASS) if isinstance(mapping, Mapping) else None
        return (
            node is ConditioningLayersNormalizedBlend
            and _loaded_node_methods_match(node)
            and node.INPUT_TYPES() == {"required": {"conditioning": ("CONDITIONING",)}}
            and node.RETURN_TYPES == ("CONDITIONING",)
            and node.FUNCTION == "prepare"
            and blend_runtime_dtype_available()
            and verify_blend_component_source()
        )
    except Exception:
        # Blend-specific dependency, initialization and contract failures are
        # route unavailability. Retained host/product validators are untouched.
        return False


def _loaded_node_methods_match(node) -> bool:
    """Compare loaded method code with the fixed, source-anchored node contract.

    Compilation is inspection only: no module or method code is executed. This
    closes mutation of the governed class object after registration while the
    original source and import-time manifest still match. Availability remains
    the single owner of this check; readiness merely invokes that owner.
    """

    from conditioning_layers.comfyui.prediction_mixing import blend_node

    if not verify_blend_component_source():
        return False
    source = Path(__file__).resolve().parents[2] / "comfyui" / "prediction_mixing" / "blend_node.py"
    if Path(blend_node.__file__).resolve() != source:
        return False
    compiled = compile(source.read_text(encoding="utf-8"), str(source), "exec",
                       dont_inherit=True, optimize=0)
    class_code = next(item for item in compiled.co_consts
                      if isinstance(item, CodeType) and item.co_name == BLEND_NODE_CLASS)
    expected = {item.co_name: item for item in class_code.co_consts
                if isinstance(item, CodeType)}
    for name in ("INPUT_TYPES", "IS_CHANGED", "prepare"):
        method = vars(node).get(name)
        if name != "prepare":
            if type(method) is not classmethod:
                return False
            method = method.__func__
        if (type(method) is not FunctionType or method.__code__ != expected[name]
                or method.__globals__ is not vars(blend_node)
                or method.__defaults__ is not None or method.__kwdefaults__ is not None
                or method.__closure__ is not None):
            return False
    return True


def capture_blend_component_availability(
    published_identity: BlendComponentIdentity,
) -> BlendComponentAvailability:
    """Observe a successfully published identity in the local host process."""

    value = BlendComponentAvailability(
        implementation=published_identity, process_id=os.getpid(),
        launch_arguments=tuple(sys.argv), available=True,
    )
    if validate_blend_component_availability(value):
        raise ValueError("Blend preparation component is unavailable or its identity/runtime is unsupported")
    return value


def validate_blend_component_availability(value: object) -> tuple[ValidationFinding, ...]:
    try:
        valid = (
            type(value) is BlendComponentAvailability
            and value.available is True
            and type(value.process_id) is int and value.process_id == os.getpid()
            and value.launch_arguments == tuple(sys.argv)
            and _valid_launch_arguments(value.launch_arguments)
            and validate_blend_component_identity(value.implementation)
            and _registered_component_matches()
        )
    except (AttributeError, TypeError, ValueError, OSError):
        valid = False
    return () if valid else (runtime_finding(
        "runtime.blend_component_unavailable", FindingSeverity.ERROR,
        "Blend requires current target-process registration, governed project source identity, "
        "compatible ports and qualified intermediate dtype settings.",
        field_path="blend_component",
    ),)


def component_availability_projection(value: BlendComponentAvailability) -> dict[str, object]:
    return {
        "implementation": portable_value(value.implementation),
        "available": value.available,
        "launch_arguments_sha256": fingerprint_portable(value.launch_arguments),
        "preparation_device": "cpu", "prepared_dtype": "binary32",
        "execution_dtype": "binary32", "observation_scope": "target-process-registration",
        "observed_prepared_tensor": None,
    }


@dataclass(frozen=True, slots=True)
class BlendPortableFieldProvenance:
    """Stable staged availability; copy/reuse observations remain in staging records."""

    layer_id: str
    document_reference: str
    source_sha256: str
    staged_filename: str
    staged_sha256: str


@dataclass(frozen=True, slots=True)
class BlendRuntimeProvenance(SelectedExecutionReferences):
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
    fields: tuple[BlendPortableFieldProvenance, ...]
    workflow_provenance: BlendWorkflowProvenance
    seed: int
    output_prefix: str
    warning_codes: tuple[str, ...]
    bundle_fingerprint: str
    project_component_precondition: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_component_precondition", freeze_json(self.project_component_precondition))


@dataclass(frozen=True, slots=True)
class BlendSubmissionBundle(SelectedExecutionReferences):
    bundle_version: str
    graph_artifact: BlendGraphArtifact
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
    provenance: BlendRuntimeProvenance
    submission_ready: bool
    component_availability: BlendComponentAvailability

    def __post_init__(self) -> None:
        object.__setattr__(self, "graph_mapping", freeze_json(self.graph_mapping))

    def to_api_graph(self) -> dict[str, object]:
        return _thaw_json(self.graph_mapping)


@dataclass(frozen=True, slots=True)
class BlendRuntimePreparationResult:
    bundle: BlendSubmissionBundle | None
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
    return tuple(BlendPortableFieldProvenance(
        layer_id=item.layer_id, document_reference=item.document_reference,
        source_sha256=item.expected_sha256, staged_filename=item.staged_filename,
        staged_sha256=item.observed_sha256,
    ) for item in records)


def fingerprint_blend_submission_bundle(
    *, artifact: object, host_snapshot: ComfyUIHostSnapshot,
    components: tuple[ComponentFileRecord, ...],
    staged_assets: tuple[StagedAssetRecord, ...], warning_codes: tuple[str, ...],
    component_availability: BlendComponentAvailability,
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
        "project_component_precondition": component_availability_projection(component_availability),
    })


def _build_runtime_provenance(
    artifact: object, host_snapshot: ComfyUIHostSnapshot,
    components: tuple[ComponentFileRecord, ...], staged_assets: tuple[StagedAssetRecord, ...],
    warning_codes: tuple[str, ...], bundle_fingerprint: str,
    component_availability: BlendComponentAvailability,
) -> BlendRuntimeProvenance:
    workflow = artifact.provenance_inputs
    return BlendRuntimeProvenance(
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
        project_component_precondition=component_availability_projection(component_availability),
    )


def prepare_blend_submission_bundle(
    artifact: object, workflow_provenance: object,
    inventory: ComfyUIComponentInventory, host_configuration: ComfyUIHostConfiguration,
    field_inspections: tuple[FieldInspectionResult, ...], source_asset_root: Path,
    node_contract_snapshot: HostNodeContractSnapshot | None,
    *, component_availability: BlendComponentAvailability | None = None,
) -> BlendRuntimePreparationResult:
    """Prepare through retained host, component, current-byte and staging primitives."""

    artifact_errors = validate_blend_artifact(artifact, workflow_provenance, inventory)
    if artifact_errors:
        return BlendRuntimePreparationResult(
            None, None, (), (), artifact_errors, (), (), (), False,
        )
    component_errors = validate_blend_component_availability(component_availability)
    if component_errors:
        return BlendRuntimePreparationResult(
            None, None, (), (), component_errors, (), (), (), False,
        )
    host = validate_local_host(
        host_configuration, inventory,
        tuple(name for name in artifact.required_host_components if name != BLEND_NODE_CLASS),
        node_contract_snapshot,
    )
    components = validate_component_files(host_configuration, inventory)
    sources = validate_field_sources(
        artifact, workflow_provenance, field_inspections, source_asset_root, host_configuration,
    )
    errors = host.errors + components.errors + sources.errors
    warnings = host.warnings + components.warnings + sources.warnings
    information = host.information + components.information + sources.information
    if errors or not host.compatible or not components.verified or not sources.verified:
        return BlendRuntimePreparationResult(
            None, host.snapshot, components.records, (), deduplicate_findings(errors or (_invalid_bundle(),)),
            deduplicate_findings(warnings), deduplicate_findings(information),
            host.unresolved_requirements, False,
        )
    staged = stage_field_assets(sources.candidates, host_configuration)
    warnings += staged.warnings
    information += staged.information
    if not staged.successful:
        return BlendRuntimePreparationResult(
            None, host.snapshot, components.records, staged.records, staged.errors,
            deduplicate_findings(warnings), deduplicate_findings(information), (), False,
        )
    warning_codes = tuple(dict.fromkeys(artifact.warnings + finding_codes(warnings)))
    fingerprint = fingerprint_blend_submission_bundle(
        artifact=artifact, host_snapshot=host.snapshot, components=components.records,
        staged_assets=staged.records, warning_codes=warning_codes,
        component_availability=component_availability,
    )
    provenance = _build_runtime_provenance(
        artifact, host.snapshot, components.records, staged.records, warning_codes, fingerprint,
        component_availability,
    )
    bundle = BlendSubmissionBundle(
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
        component_availability=component_availability,
    )
    bundle_errors = validate_blend_submission_bundle(bundle)
    if bundle_errors:
        return BlendRuntimePreparationResult(
            None, host.snapshot, components.records, staged.records, bundle_errors,
            deduplicate_findings(warnings), deduplicate_findings(information), (), False,
        )
    return BlendRuntimePreparationResult(
        bundle, host.snapshot, components.records, staged.records, (),
        deduplicate_findings(warnings), deduplicate_findings(information), (), True,
    )


def validate_blend_submission_bundle(
    bundle: object, *, verify_current_staged_bytes: bool = False,
) -> tuple[ValidationFinding, ...]:
    """Reconcile every explicit declaration against the complete selected graph."""

    if type(bundle) is not BlendSubmissionBundle:
        return (_invalid_bundle(),)
    try:
        availability_errors = validate_blend_component_availability(bundle.component_availability)
        if availability_errors:
            return availability_errors
        artifact = bundle.graph_artifact
        workflow = artifact.provenance_inputs
        # A reviewed binding selects its own committed host pins. Any other
        # binding fails the artifact check whatever the inventory, so the
        # retained pins only keep its historical diagnostics exact.
        host = (realization_host_profile(artifact.realization_binding)
                if type(artifact) is BlendGraphArtifact else None)
        inventory, pinned_snapshot = (INVENTORY, SNAPSHOT) if host is None else (host.inventory, host.node_snapshot)
        errors = validate_blend_artifact(
            artifact, workflow, inventory,
        )
        if errors:
            return errors
        selected = selected_references(workflow)
        expected_fingerprint = fingerprint_blend_submission_bundle(
            artifact=artifact, host_snapshot=bundle.host_snapshot,
            components=bundle.verified_components, staged_assets=bundle.staged_assets,
            warning_codes=bundle.warnings,
            component_availability=bundle.component_availability,
        )
        expected_provenance = _build_runtime_provenance(
            artifact, bundle.host_snapshot, bundle.verified_components,
            bundle.staged_assets, bundle.warnings, expected_fingerprint,
            bundle.component_availability,
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
            or type(bundle.provenance) is not BlendRuntimeProvenance
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
        "runtime.blend_bundle_invalid", FindingSeverity.ERROR,
        "Multi-layer bundle declarations, authority, or verified evidence disagree.",
        field_path="bundle",
    )
