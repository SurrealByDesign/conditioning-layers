"""Orchestrate verified host evidence and staging into a submission-ready bundle."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path

from conditioning_layers.assets import FieldInspectionResult
from conditioning_layers.comfyui.prediction_mixing import (
    GRAPH_FORMAT_IDENTIFIER,
    GRAPH_FORMAT_VERSION,
    NODE_CONTRACTS,
    ComfyUIApiGraphArtifact,
    ComfyUIComponentInventory,
    WorkflowGenerationProvenance,
    fingerprint_api_graph,
)
from conditioning_layers.domain import FindingSeverity, ValidationFinding

from .component_validation import validate_component_files
from .errors import deduplicate_findings, finding_codes, runtime_finding
from .host_validation import validate_local_host
from .models import (
    BUNDLE_VERSION,
    ComfyUIHostConfiguration,
    ComfyUIHostSnapshot,
    ComfyUISubmissionBundle,
    ComponentFileRecord,
    HostNodeContractSnapshot,
    RuntimePreparationResult,
    StagedAssetRecord,
)
from .provenance import build_runtime_provenance
from .staging import stage_field_assets, validate_field_sources


def prepare_submission_bundle(
    artifact: ComfyUIApiGraphArtifact,
    workflow_provenance: WorkflowGenerationProvenance,
    inventory: ComfyUIComponentInventory,
    host_configuration: ComfyUIHostConfiguration,
    field_inspections: tuple[FieldInspectionResult, ...],
    source_asset_root: Path,
    node_contract_snapshot: HostNodeContractSnapshot | None,
) -> RuntimePreparationResult:
    """Prepare a bundle without any server communication, submission, or execution."""

    artifact_errors = _validate_artifact(
        artifact, workflow_provenance, inventory
    )
    host_result = validate_local_host(
        host_configuration,
        inventory,
        artifact.required_host_components,
        node_contract_snapshot,
    )
    component_result = validate_component_files(host_configuration, inventory)
    field_result = validate_field_sources(
        artifact,
        workflow_provenance,
        field_inspections,
        source_asset_root,
        host_configuration,
    )

    warnings = list(host_result.warnings + component_result.warnings + field_result.warnings)
    warnings.extend(_artifact_warning_findings(artifact.warnings))
    information = list(
        host_result.information
        + component_result.information
        + field_result.information
    )
    errors = list(
        artifact_errors
        + host_result.errors
        + component_result.errors
        + field_result.errors
    )
    unresolved = list(host_result.unresolved_requirements)
    if errors:
        errors.append(
            runtime_finding(
                "runtime.bundle_not_ready",
                FindingSeverity.ERROR,
                "Submission bundle creation is blocked by runtime validation findings.",
                field_path="bundle",
            )
        )
        return RuntimePreparationResult(
            bundle=None,
            host_snapshot=host_result.snapshot,
            component_records=component_result.records,
            staged_assets=(),
            errors=deduplicate_findings(errors),
            warnings=deduplicate_findings(warnings),
            information=deduplicate_findings(information),
            unresolved_runtime_requirements=tuple(dict.fromkeys(unresolved)),
            ready=False,
        )

    staging_result = stage_field_assets(field_result.candidates, host_configuration)
    warnings.extend(staging_result.warnings)
    information.extend(staging_result.information)
    if not staging_result.successful:
        errors.extend(staging_result.errors)
        errors.append(
            runtime_finding(
                "runtime.bundle_not_ready",
                FindingSeverity.ERROR,
                "Submission bundle creation is blocked by field-staging findings.",
                field_path="bundle",
            )
        )
        return RuntimePreparationResult(
            bundle=None,
            host_snapshot=host_result.snapshot,
            component_records=component_result.records,
            staged_assets=staging_result.records,
            errors=deduplicate_findings(errors),
            warnings=deduplicate_findings(warnings),
            information=deduplicate_findings(information),
            unresolved_runtime_requirements=tuple(dict.fromkeys(unresolved)),
            ready=False,
        )

    warning_codes = tuple(
        dict.fromkeys(artifact.warnings + finding_codes(warnings))
    )
    bundle_fingerprint = fingerprint_submission_bundle(
        artifact=artifact,
        host_snapshot=host_result.snapshot,
        components=component_result.records,
        staged_assets=staging_result.records,
        warning_codes=warning_codes,
    )
    provenance = build_runtime_provenance(
        document_id=workflow_provenance.document_id,
        translation_plan_fingerprint=(
            workflow_provenance.translation_plan_fingerprint
        ),
        graph_fingerprint=artifact.graph_fingerprint,
        adapter_identifier=artifact.adapter_identifier,
        inventory_identifier=inventory.inventory_identifier,
        host_snapshot=host_result.snapshot,
        components=component_result.records,
        staged_assets=staging_result.records,
        seed=workflow_provenance.seed,
        output_prefix=workflow_provenance.output_filename_prefix,
        warning_codes=warning_codes,
        bundle_fingerprint=bundle_fingerprint,
    )
    bundle = ComfyUISubmissionBundle(
        bundle_version=BUNDLE_VERSION,
        graph_artifact=artifact,
        graph_fingerprint=artifact.graph_fingerprint,
        translation_plan_fingerprint=artifact.source_translation_plan_fingerprint,
        document_id=workflow_provenance.document_id,
        adapter_identifier=artifact.adapter_identifier,
        inventory_identifier=inventory.inventory_identifier,
        profile_identifier=inventory.comfyui_profile_identifier,
        host_snapshot=host_result.snapshot,
        verified_components=component_result.records,
        staged_assets=staging_result.records,
        graph_mapping=artifact.to_api_graph(),
        expected_output_prefix=workflow_provenance.output_filename_prefix,
        runtime_seed=workflow_provenance.seed,
        warnings=warning_codes,
        unresolved_runtime_requirements=(),
        bundle_fingerprint=bundle_fingerprint,
        provenance=provenance,
        submission_ready=True,
    )
    information.append(
        runtime_finding(
            "runtime.bundle_ready",
            FindingSeverity.INFORMATION,
            "A verified submission bundle is ready for a later execution-submission slice.",
            field_path="bundle",
        )
    )
    return RuntimePreparationResult(
        bundle=bundle,
        host_snapshot=host_result.snapshot,
        component_records=component_result.records,
        staged_assets=staging_result.records,
        errors=(),
        warnings=deduplicate_findings(warnings),
        information=deduplicate_findings(information),
        unresolved_runtime_requirements=(),
        ready=True,
    )


def fingerprint_submission_bundle(
    *,
    artifact: ComfyUIApiGraphArtifact,
    host_snapshot: ComfyUIHostSnapshot,
    components: tuple[ComponentFileRecord, ...],
    staged_assets: tuple[StagedAssetRecord, ...],
    warning_codes: tuple[str, ...],
) -> str:
    """Hash deterministic portable material; local paths and timestamps are excluded."""

    provenance = artifact.provenance_inputs
    payload = {
        "bundle_version": BUNDLE_VERSION,
        "graph_fingerprint": artifact.graph_fingerprint,
        "translation_plan_fingerprint": artifact.source_translation_plan_fingerprint,
        "document_id": provenance.document_id,
        "adapter_identifier": artifact.adapter_identifier,
        "inventory_identifier": provenance.component_inventory_identifier,
        "host": {
            "profile_identifier": host_snapshot.profile_identifier,
            "launch_profile_identifier": host_snapshot.launch_profile_identifier,
            "comfyui_version": host_snapshot.observed_comfyui_version,
            "comfyui_revision": host_snapshot.observed_comfyui_revision,
            "node_contract_snapshot_identifier": (
                host_snapshot.node_contract_snapshot_identifier
            ),
            "node_contract_snapshot_fingerprint": (
                host_snapshot.node_contract_snapshot_fingerprint
            ),
            "staging_cleanup_policy": host_snapshot.staging_cleanup_policy.value,
        },
        "components": [
            {
                "role": record.role.value,
                "category": record.category,
                "filename": record.filename,
                "byte_size": record.byte_size,
                "sha256": record.sha256,
            }
            for record in components
        ],
        "fields": [
            {
                "layer_id": record.layer_id,
                "document_reference": record.document_reference,
                "staged_filename": record.staged_filename,
                "sha256": record.observed_sha256,
                "disposition": record.disposition.value,
            }
            for record in staged_assets
        ],
        "seed": provenance.seed,
        "output_prefix": provenance.output_filename_prefix,
        "warning_codes": list(warning_codes),
    }
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_artifact(
    artifact: object,
    workflow_provenance: object,
    inventory: ComfyUIComponentInventory,
) -> tuple[ValidationFinding, ...]:
    errors: list[ValidationFinding] = []
    if not isinstance(artifact, ComfyUIApiGraphArtifact) or not isinstance(
        workflow_provenance, WorkflowGenerationProvenance
    ):
        return (
            runtime_finding(
                "runtime.bundle_not_ready",
                FindingSeverity.ERROR,
                "A generated graph artifact and matching workflow provenance are required.",
                field_path="artifact",
            ),
        )
    graph = artifact.to_api_graph()
    if (
        artifact.graph_format_identifier != GRAPH_FORMAT_IDENTIFIER
        or artifact.graph_format_version != GRAPH_FORMAT_VERSION
        or fingerprint_api_graph(graph) != artifact.graph_fingerprint
        or artifact.provenance_inputs != workflow_provenance
        or artifact.source_translation_plan_fingerprint
        != workflow_provenance.translation_plan_fingerprint
        or workflow_provenance.graph_fingerprint != artifact.graph_fingerprint
        or workflow_provenance.component_inventory_identifier
        != inventory.inventory_identifier
        or workflow_provenance.model_filename != inventory.model_filename
        or workflow_provenance.model_sha256 != inventory.model_sha256
        or workflow_provenance.text_encoder_filename
        != inventory.text_encoder_filename
        or workflow_provenance.text_encoder_sha256
        != inventory.text_encoder_sha256
        or workflow_provenance.vae_filename != inventory.vae_filename
        or workflow_provenance.vae_sha256 != inventory.vae_sha256
        or workflow_provenance.mandatory_warning_codes != artifact.warnings
        or workflow_provenance.execution_profile_identifier
        != inventory.supported_execution_profile_identifier
        or workflow_provenance.adapter_identifier != artifact.adapter_identifier
    ):
        errors.append(
            runtime_finding(
                "runtime.bundle_not_ready",
                FindingSeverity.ERROR,
                "Graph identity, inventory, or workflow-generation provenance is inconsistent.",
                field_path="artifact",
            )
        )
    actual_classes: list[str] = []
    for node_id, node in graph.items():
        if not isinstance(node, Mapping) or set(node) != {"class_type", "inputs"}:
            errors.append(_invalid_graph_finding(node_id))
            continue
        class_name = node.get("class_type")
        inputs = node.get("inputs")
        contract = NODE_CONTRACTS.get(class_name) if isinstance(class_name, str) else None
        if (
            contract is None
            or not isinstance(inputs, Mapping)
            or set(inputs) != contract.required_inputs
        ):
            errors.append(_invalid_graph_finding(node_id))
            continue
        actual_classes.append(class_name)
        for input_name in contract.link_inputs:
            link = inputs[input_name]
            if (
                not isinstance(link, list | tuple)
                or len(link) != 2
                or not isinstance(link[0], str)
                or isinstance(link[1], bool)
                or not isinstance(link[1], int)
                or link[0] == node_id
            ):
                errors.append(_invalid_graph_finding(node_id))
                continue
            source = graph.get(link[0])
            source_name = source.get("class_type") if isinstance(source, Mapping) else None
            source_contract = (
                NODE_CONTRACTS.get(source_name) if isinstance(source_name, str) else None
            )
            if source_contract is None or link[1] not in source_contract.output_indices:
                errors.append(_invalid_graph_finding(node_id))
    if (
        set(actual_classes) != set(artifact.required_host_components)
        or len(artifact.required_host_components)
        != len(set(artifact.required_host_components))
    ):
        errors.append(_invalid_graph_finding("components"))
    expected_values = {
        "UNETLoader": ("unet_name", inventory.model_filename),
        "CLIPLoader": ("clip_name", inventory.text_encoder_filename),
        "VAELoader": ("vae_name", inventory.vae_filename),
        "SaveImage": ("filename_prefix", workflow_provenance.output_filename_prefix),
    }
    for class_name, (input_name, expected) in expected_values.items():
        nodes = [
            node
            for node in graph.values()
            if isinstance(node, Mapping) and node.get("class_type") == class_name
        ]
        if len(nodes) != 1 or nodes[0]["inputs"].get(input_name) != expected:
            errors.append(_invalid_graph_finding(class_name))
    samplers = [
        node
        for node in graph.values()
        if isinstance(node, Mapping) and node.get("class_type") == "KSampler"
    ]
    if len(samplers) != 1 or any(
        samplers[0]["inputs"].get(name) != expected
        for name, expected in (
            ("seed", workflow_provenance.seed),
            ("steps", inventory.steps),
            ("cfg", inventory.cfg),
            ("sampler_name", inventory.sampler_name),
            ("scheduler", inventory.scheduler_name),
            ("denoise", inventory.denoise),
        )
    ):
        errors.append(_invalid_graph_finding("KSampler"))
    latents = [
        node
        for node in graph.values()
        if isinstance(node, Mapping)
        and node.get("class_type") == "EmptyLatentImage"
    ]
    if len(latents) != 1 or any(
        latents[0]["inputs"].get(name) != expected
        for name, expected in (
            ("width", inventory.output_width),
            ("height", inventory.output_height),
            ("batch_size", inventory.batch_size),
        )
    ):
        errors.append(_invalid_graph_finding("EmptyLatentImage"))
    active_layers = workflow_provenance.active_layers
    prompt_hashes = tuple(
        hashlib.sha256(node["inputs"]["text"].encode("utf-8")).hexdigest()
        for node in graph.values()
        if isinstance(node, Mapping)
        and node.get("class_type") == "CLIPTextEncode"
        and isinstance(node.get("inputs"), Mapping)
        and isinstance(node["inputs"].get("text"), str)
        and node["inputs"]["text"]
    )
    field_names = tuple(
        node["inputs"]["image"]
        for node in graph.values()
        if isinstance(node, Mapping)
        and node.get("class_type") == "LoadImageMask"
        and isinstance(node.get("inputs"), Mapping)
        and isinstance(node["inputs"].get("image"), str)
    )
    strengths = tuple(
        node["inputs"]["strength"]
        for node in graph.values()
        if isinstance(node, Mapping)
        and node.get("class_type") == "ConditioningSetMask"
        and isinstance(node.get("inputs"), Mapping)
    )
    negative_prompts = tuple(
        node["inputs"]["text"]
        for node in graph.values()
        if isinstance(node, Mapping)
        and node.get("class_type") == "CLIPTextEncode"
        and isinstance(node.get("inputs"), Mapping)
        and node["inputs"].get("text") == ""
    )
    # Bundle validation checks the frozen v1 graph/provenance shape after
    # capability authorization; it is not an independent product limit.
    if (
        len(active_layers) not in {1, 2}
        or prompt_hashes
        != tuple(layer.combined_prompt_sha256 for layer in active_layers)
        or field_names
        != tuple(layer.staged_field_filename for layer in active_layers)
        or strengths != tuple(layer.requested_strength for layer in active_layers)
        or negative_prompts != ("",)
    ):
        errors.append(_invalid_graph_finding("active_layers"))
    return deduplicate_findings(errors)


def _invalid_graph_finding(role: str) -> ValidationFinding:
    return runtime_finding(
        "runtime.bundle_not_ready",
        FindingSeverity.ERROR,
        "Generated graph no longer matches its verified built-in-node contract.",
        field_path=f"artifact.graph.{role}",
    )


def _artifact_warning_findings(codes: tuple[str, ...]) -> tuple[ValidationFinding, ...]:
    return tuple(
        runtime_finding(
            code,
            FindingSeverity.WARNING,
            f"Preserved workflow-generation warning: {code}.",
        )
        for code in codes
    )
