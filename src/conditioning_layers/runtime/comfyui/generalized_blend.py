"""ADR-0028 generalized Blend offline bundle and runtime-provenance successors.

Offline preparation only. The generalized component is available to an offline
fixture; it is never registered in a host process. No live node mapping,
loader, readiness, product or qualification state is inspected or claimed.
Bundles are never submission-ready, and the retained exact-3 client rejects
them by type. Retained host, component, source and staging primitives are
reused unchanged against temporary offline fixtures.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from types import CodeType, FunctionType

from conditioning_layers.assets import FieldInspectionResult
from conditioning_layers.comfyui.prediction_mixing import ComfyUIComponentInventory, HostNodeContractSnapshot
from conditioning_layers.comfyui.prediction_mixing.generalized_blend import (
    OFFLINE_FIXTURE_AVAILABILITY_SCOPE, GeneralizedBlendGraphArtifact,
    GeneralizedBlendWorkflowProvenance, validate_generalized_blend_artifact,
)
from conditioning_layers.comfyui.prediction_mixing.generalized_blend.authority import INVENTORY, SNAPSHOT
from conditioning_layers.comfyui.prediction_mixing.generalized_blend_component import (
    GENERALIZED_BLEND_NODE_CLASS, GeneralizedBlendComponentIdentity,
    generalized_blend_component_identity, generalized_blend_node_contract,
    validate_generalized_blend_component_identity, verify_generalized_blend_component_source,
)
from conditioning_layers.comfyui.prediction_mixing.multi_layer.canonical import freeze_json
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


BUNDLE_VERSION = "conditioning-layers.comfyui-submission-bundle.v4"
RUNTIME_PROVENANCE_VERSION = "conditioning-layers.runtime-provenance.v4"
OFFLINE_AVAILABILITY_VERSION = "conditioning-layers.generalized-blend.offline-fixture-availability.v1"
# Named explicitly so no successor record can be read as claiming them.
NOT_CLAIMED = (
    "target-process-registration", "live-node-class-mappings", "root-loader-registration",
    "product-loader-registration", "readiness", "live-host-availability", "product-support",
    "product-admission", "live-qualification", "resource-qualification", "submission",
)
UNRESOLVED_RUNTIME_REQUIREMENTS = (
    "runtime.generalized_host_registration_not_authorized",
    "runtime.generalized_submission_not_authorized",
)
_FIXTURE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


@dataclass(frozen=True, slots=True)
class GeneralizedSelectedExecutionReferences:
    """Private embedded layout for explicit offline authority references."""

    contract_identifier: str
    contract_version: int
    translation_plan_identifier: str
    translation_plan_version: int
    eligibility_entry_identifier: str
    eligibility_entry_fingerprint: str
    exact_admitted_cardinality: int
    expected_count: int
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
    project_component_contract_identifier: str
    project_component_implementation_fingerprint: str
    permitted_class_authority_identifier: str
    permitted_class_authority_fingerprint: str


def selected_references(value: object) -> dict[str, object]:
    """Copy the selected instance declarations; no registry/admission state enters."""

    return {item.name: getattr(value, item.name) for item in fields(GeneralizedSelectedExecutionReferences)}


@dataclass(frozen=True, slots=True)
class GeneralizedBlendOfflineFixtureAvailability:
    """The generalized component is available to one offline fixture only.

    Capture checks the governed identity, current and import-time source
    anchors, node ports and loaded class methods. It never inspects or claims
    host registration, live node mappings, a loader, readiness or live
    availability, and it records no process identifier or launch arguments.
    """

    record_version: str
    implementation: GeneralizedBlendComponentIdentity
    node_class: str
    fixture_identifier: str
    observation_scope: str
    available_to_offline_fixture: bool


def _offline_node_matches() -> bool:
    """Compare the constructed class with its source-anchored contract.

    Compilation is inspection only; no module or method code is executed.
    """

    try:
        from conditioning_layers.comfyui.prediction_mixing import generalized_blend_node

        node = vars(generalized_blend_node)[GENERALIZED_BLEND_NODE_CLASS]
        contract = generalized_blend_node_contract()
        source = Path(__file__).resolve().parents[2] / "comfyui" / "prediction_mixing" / "generalized_blend_node.py"
        if (not verify_generalized_blend_component_source()
                or Path(generalized_blend_node.__file__).resolve() != source
                or node.__name__ != GENERALIZED_BLEND_NODE_CLASS
                or node.INPUT_TYPES() != contract["input_types"]
                or node.RETURN_TYPES != contract["return_types"]
                or node.FUNCTION != contract["function"]):
            return False
        compiled = compile(source.read_text(encoding="utf-8"), str(source), "exec",
                           dont_inherit=True, optimize=0)
        class_code = next(item for item in compiled.co_consts
                          if isinstance(item, CodeType) and item.co_name == GENERALIZED_BLEND_NODE_CLASS)
        expected = {item.co_name: item for item in class_code.co_consts if isinstance(item, CodeType)}
        for name in ("INPUT_TYPES", "IS_CHANGED", "prepare"):
            method = vars(node).get(name)
            if name != "prepare":
                if type(method) is not classmethod:
                    return False
                method = method.__func__
            if (type(method) is not FunctionType or method.__code__ != expected[name]
                    or method.__globals__ is not vars(generalized_blend_node)
                    or method.__defaults__ is not None or method.__kwdefaults__ is not None
                    or method.__closure__ is not None):
                return False
        return True
    except Exception:
        # Generalized component failure is fixture unavailability only.
        return False


def capture_generalized_blend_offline_fixture_availability(
    fixture_identifier: str,
) -> GeneralizedBlendOfflineFixtureAvailability:
    """Record that the governed class is available to this offline fixture."""

    value = GeneralizedBlendOfflineFixtureAvailability(
        record_version=OFFLINE_AVAILABILITY_VERSION,
        implementation=generalized_blend_component_identity(),
        node_class=GENERALIZED_BLEND_NODE_CLASS, fixture_identifier=fixture_identifier,
        observation_scope=OFFLINE_FIXTURE_AVAILABILITY_SCOPE, available_to_offline_fixture=True,
    )
    if validate_generalized_blend_offline_fixture_availability(value):
        raise ValueError("Generalized Blend component is unavailable to this offline fixture")
    return value


def validate_generalized_blend_offline_fixture_availability(value: object) -> tuple[ValidationFinding, ...]:
    try:
        valid = (
            type(value) is GeneralizedBlendOfflineFixtureAvailability
            and value.record_version == OFFLINE_AVAILABILITY_VERSION
            and value.observation_scope == OFFLINE_FIXTURE_AVAILABILITY_SCOPE
            and value.available_to_offline_fixture is True
            and value.node_class == GENERALIZED_BLEND_NODE_CLASS
            and type(value.fixture_identifier) is str
            and _FIXTURE_IDENTIFIER.match(value.fixture_identifier) is not None
            and validate_generalized_blend_component_identity(value.implementation)
            and _offline_node_matches()
        )
    except (AttributeError, TypeError, ValueError):
        valid = False
    return () if valid else (runtime_finding(
        "runtime.generalized_blend_component_unavailable", FindingSeverity.ERROR,
        "Generalized Blend requires offline fixture availability with governed identity, source and ports.",
        field_path="generalized_blend_component",
    ),)


def offline_availability_projection(value: GeneralizedBlendOfflineFixtureAvailability) -> dict[str, object]:
    return {
        "record_version": value.record_version,
        "implementation": portable_value(value.implementation),
        "node_class": value.node_class, "fixture_identifier": value.fixture_identifier,
        "observation_scope": value.observation_scope,
        "available_to_offline_fixture": value.available_to_offline_fixture,
        "preparation_device": "cpu", "prepared_dtype": "binary32", "execution_dtype": "binary32",
        "not_claimed": NOT_CLAIMED, "observed_prepared_tensor": None,
    }


@dataclass(frozen=True, slots=True)
class GeneralizedBlendPortableFieldProvenance:
    """Stable staged availability; copy/reuse observations remain in staging records."""

    layer_id: str
    document_reference: str
    source_sha256: str
    staged_filename: str
    staged_sha256: str


@dataclass(frozen=True, slots=True)
class GeneralizedBlendRuntimeProvenance(GeneralizedSelectedExecutionReferences):
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
    fields: tuple[GeneralizedBlendPortableFieldProvenance, ...]
    workflow_provenance: GeneralizedBlendWorkflowProvenance
    seed: int
    output_prefix: str
    warning_codes: tuple[str, ...]
    bundle_fingerprint: str
    component_availability: Mapping[str, object]
    submission_authorized: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "component_availability", freeze_json(self.component_availability))


@dataclass(frozen=True, slots=True)
class GeneralizedBlendSubmissionBundle(GeneralizedSelectedExecutionReferences):
    bundle_version: str
    graph_artifact: GeneralizedBlendGraphArtifact
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
    provenance: GeneralizedBlendRuntimeProvenance
    submission_ready: bool
    component_availability: GeneralizedBlendOfflineFixtureAvailability

    def __post_init__(self) -> None:
        object.__setattr__(self, "graph_mapping", freeze_json(self.graph_mapping))

    def to_api_graph(self) -> dict[str, object]:
        return _thaw_json(self.graph_mapping)


@dataclass(frozen=True, slots=True)
class GeneralizedBlendRuntimePreparationResult:
    bundle: GeneralizedBlendSubmissionBundle | None
    host_snapshot: ComfyUIHostSnapshot | None
    component_records: tuple[ComponentFileRecord, ...]
    staged_assets: tuple[StagedAssetRecord, ...]
    errors: tuple[ValidationFinding, ...]
    warnings: tuple[ValidationFinding, ...]
    information: tuple[ValidationFinding, ...]
    unresolved_runtime_requirements: tuple[str, ...]
    prepared: bool


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
    return tuple(GeneralizedBlendPortableFieldProvenance(
        layer_id=item.layer_id, document_reference=item.document_reference,
        source_sha256=item.expected_sha256, staged_filename=item.staged_filename,
        staged_sha256=item.observed_sha256,
    ) for item in records)


def fingerprint_generalized_blend_bundle(
    *, artifact: object, host_snapshot: ComfyUIHostSnapshot,
    components: tuple[ComponentFileRecord, ...],
    staged_assets: tuple[StagedAssetRecord, ...], warning_codes: tuple[str, ...],
    component_availability: GeneralizedBlendOfflineFixtureAvailability,
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
        "component_availability": offline_availability_projection(component_availability),
        "submission_ready": False,
        "unresolved_runtime_requirements": UNRESOLVED_RUNTIME_REQUIREMENTS,
    })


def _build_runtime_provenance(
    artifact: object, host_snapshot: ComfyUIHostSnapshot,
    components: tuple[ComponentFileRecord, ...], staged_assets: tuple[StagedAssetRecord, ...],
    warning_codes: tuple[str, ...], bundle_fingerprint: str,
    component_availability: GeneralizedBlendOfflineFixtureAvailability,
) -> GeneralizedBlendRuntimeProvenance:
    workflow = artifact.provenance_inputs
    return GeneralizedBlendRuntimeProvenance(
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
        component_availability=offline_availability_projection(component_availability),
        submission_authorized=False,
    )


def prepare_generalized_blend_bundle(
    artifact: object, workflow_provenance: object,
    inventory: ComfyUIComponentInventory, host_configuration: ComfyUIHostConfiguration,
    field_inspections: tuple[FieldInspectionResult, ...], source_asset_root: Path,
    node_contract_snapshot: HostNodeContractSnapshot | None,
    *, component_availability: GeneralizedBlendOfflineFixtureAvailability | None = None,
) -> GeneralizedBlendRuntimePreparationResult:
    """Prepare an offline, never-submission-ready bundle through retained primitives."""

    artifact_errors = validate_generalized_blend_artifact(artifact, workflow_provenance, inventory)
    if artifact_errors:
        return GeneralizedBlendRuntimePreparationResult(None, None, (), (), artifact_errors, (), (), (), False)
    component_errors = validate_generalized_blend_offline_fixture_availability(component_availability)
    if component_errors:
        return GeneralizedBlendRuntimePreparationResult(None, None, (), (), component_errors, (), (), (), False)
    host = validate_local_host(
        host_configuration, inventory,
        tuple(name for name in artifact.required_host_components if name != GENERALIZED_BLEND_NODE_CLASS),
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
        return GeneralizedBlendRuntimePreparationResult(
            None, host.snapshot, components.records, (), deduplicate_findings(errors or (_invalid_bundle(),)),
            deduplicate_findings(warnings), deduplicate_findings(information),
            host.unresolved_requirements, False,
        )
    staged = stage_field_assets(sources.candidates, host_configuration)
    warnings += staged.warnings
    information += staged.information
    if not staged.successful:
        return GeneralizedBlendRuntimePreparationResult(
            None, host.snapshot, components.records, staged.records, staged.errors,
            deduplicate_findings(warnings), deduplicate_findings(information), (), False,
        )
    warning_codes = tuple(dict.fromkeys(artifact.warnings + finding_codes(warnings)))
    fingerprint = fingerprint_generalized_blend_bundle(
        artifact=artifact, host_snapshot=host.snapshot, components=components.records,
        staged_assets=staged.records, warning_codes=warning_codes,
        component_availability=component_availability,
    )
    provenance = _build_runtime_provenance(
        artifact, host.snapshot, components.records, staged.records, warning_codes, fingerprint,
        component_availability,
    )
    bundle = GeneralizedBlendSubmissionBundle(
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
        unresolved_runtime_requirements=UNRESOLVED_RUNTIME_REQUIREMENTS, bundle_fingerprint=fingerprint,
        provenance=provenance, submission_ready=False,
        component_availability=component_availability,
    )
    bundle_errors = validate_generalized_blend_bundle(bundle)
    if bundle_errors:
        return GeneralizedBlendRuntimePreparationResult(
            None, host.snapshot, components.records, staged.records, bundle_errors,
            deduplicate_findings(warnings), deduplicate_findings(information), (), False,
        )
    return GeneralizedBlendRuntimePreparationResult(
        bundle, host.snapshot, components.records, staged.records, (),
        deduplicate_findings(warnings), deduplicate_findings(information),
        UNRESOLVED_RUNTIME_REQUIREMENTS, True,
    )


def validate_generalized_blend_bundle(
    bundle: object, *, verify_current_staged_bytes: bool = False,
) -> tuple[ValidationFinding, ...]:
    """Reconcile every explicit declaration against the complete selected graph."""

    if type(bundle) is not GeneralizedBlendSubmissionBundle:
        return (_invalid_bundle(),)
    try:
        availability_errors = validate_generalized_blend_offline_fixture_availability(bundle.component_availability)
        if availability_errors:
            return availability_errors
        artifact = bundle.graph_artifact
        workflow = artifact.provenance_inputs
        errors = validate_generalized_blend_artifact(artifact, workflow, INVENTORY)
        if errors:
            return errors
        selected = selected_references(workflow)
        expected_fingerprint = fingerprint_generalized_blend_bundle(
            artifact=artifact, host_snapshot=bundle.host_snapshot,
            components=bundle.verified_components, staged_assets=bundle.staged_assets,
            warning_codes=bundle.warnings, component_availability=bundle.component_availability,
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
        inventory = INVENTORY
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
            # Slice B authorizes no generalized submission.
            or bundle.submission_ready is not False
            or bundle.unresolved_runtime_requirements != UNRESOLVED_RUNTIME_REQUIREMENTS
            or fingerprint_portable(selected_references(bundle)) != fingerprint_portable(selected)
            or type(bundle.exact_admitted_cardinality) is not int
            or type(bundle.expected_count) is not int
            or bundle.expected_count != bundle.exact_admitted_cardinality
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
            or type(bundle.provenance) is not GeneralizedBlendRuntimeProvenance
            or fingerprint_portable(bundle.provenance) != fingerprint_portable(expected_provenance)
            or bundle.provenance.submission_authorized is not False
            or expected_fields != staged_fields
            or len(expected_fields) != bundle.expected_count
            or actual_components != expected_components
            or snapshot.filesystem_verified is not True or snapshot.node_contracts_verified is not True
            or snapshot.profile_identifier != inventory.comfyui_profile_identifier
            or snapshot.observed_comfyui_version != inventory.expected_comfyui_version
            or snapshot.observed_comfyui_revision != inventory.expected_comfyui_revision
            or snapshot.node_contract_snapshot_identifier != SNAPSHOT.snapshot_identifier
            or snapshot.node_contract_snapshot_fingerprint != SNAPSHOT.snapshot_fingerprint
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
        "runtime.generalized_blend_bundle_invalid", FindingSeverity.ERROR,
        "Generalized Blend bundle declarations, authority, or offline evidence disagree.",
        field_path="bundle",
    )
