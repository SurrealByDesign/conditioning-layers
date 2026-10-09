"""Fail-closed validation for declared inputs and generated API graphs."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import math
from pathlib import PurePosixPath, PureWindowsPath
import re

from conditioning_layers.adapters.prediction_mixing import (
    PREDICTION_MIXING_EXECUTION_PROFILE,
    TRANSLATION_PLAN_VERSION,
    NegativePromptPolicy,
    OverlapAssessment,
    PredictionMixingTranslationPlan,
)
from conditioning_layers.domain import FindingSeverity, ValidationFinding

from .inventory import (
    NODE_CONTRACTS,
    node_id_layout,
)
from .models import (
    ComfyUIComponentInventory,
    FieldStagingMap,
    RuntimeGenerationSettings,
)


_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_URI_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def validate_generation_inputs(
    plan: object,
    inventory: object,
    settings: object,
    staging: object,
) -> tuple[ValidationFinding, ...]:
    """Validate all declared inputs without host, filesystem, or network access."""

    findings: list[ValidationFinding] = []
    if not isinstance(plan, PredictionMixingTranslationPlan):
        return (
            _error(
                "workflow.translation_required",
                "A successful PredictionMixingTranslationPlan is required.",
                field_path="translation_plan",
            ),
        )
    findings.extend(_validate_plan(plan))

    if not isinstance(inventory, ComfyUIComponentInventory):
        findings.append(
            _error(
                "workflow.component_inventory",
                "A declared ComfyUIComponentInventory is required.",
                field_path="component_inventory",
            )
        )
    else:
        findings.extend(_validate_inventory(inventory, plan))

    if not isinstance(settings, RuntimeGenerationSettings):
        findings.append(
            _error(
                "workflow.runtime_settings",
                "Runtime generation settings are required.",
                field_path="runtime_settings",
            )
        )
    else:
        findings.extend(_validate_settings(settings))

    if not isinstance(staging, FieldStagingMap):
        findings.append(
            _error(
                "workflow.field_staging_missing",
                "An explicit FieldStagingMap is required.",
                field_path="field_staging",
            )
        )
    else:
        findings.extend(_validate_staging(staging, plan))
    return tuple(findings)


def validate_api_graph(
    graph: Mapping[str, object],
    plan: PredictionMixingTranslationPlan,
    inventory: ComfyUIComponentInventory,
    settings: RuntimeGenerationSettings,
    staging: FieldStagingMap,
) -> tuple[ValidationFinding, ...]:
    """Validate node contracts, links, topology, and exact declared settings."""

    layer_ids = tuple(item.layer_id for item in plan.active_regional_conditions)
    layout = node_id_layout(layer_ids)
    findings: list[ValidationFinding] = []
    if set(graph) != set(layout.values()) or len(set(layout.values())) != len(layout):
        findings.append(
            _error(
                "workflow.graph_invalid",
                "Graph node IDs or semantic roles do not match the active-layer topology.",
                field_path="graph",
            )
        )

    for node_id, node in graph.items():
        if not isinstance(node, Mapping) or set(node) != {"class_type", "inputs"}:
            findings.append(
                _error(
                    "workflow.node_contract",
                    f"Node {node_id} must contain only class_type and inputs.",
                    field_path=f"graph.{node_id}",
                )
            )
            continue
        class_type = node.get("class_type")
        inputs = node.get("inputs")
        if (
            not isinstance(class_type, str)
            or class_type not in NODE_CONTRACTS
            or class_type not in inventory.required_node_class_names
        ):
            findings.append(
                _error(
                    "workflow.node_contract",
                    f"Node {node_id} uses an undeclared or unsupported class.",
                    field_path=f"graph.{node_id}.class_type",
                )
            )
            continue
        contract = NODE_CONTRACTS[class_type]
        if not isinstance(inputs, Mapping) or set(inputs) != contract.required_inputs:
            findings.append(
                _error(
                    "workflow.node_contract",
                    f"Node {node_id} does not match the verified input contract.",
                    field_path=f"graph.{node_id}.inputs",
                )
            )
            continue
        for input_name in contract.link_inputs:
            link = inputs[input_name]
            if (
                not isinstance(link, list | tuple)
                or len(link) != 2
                or not isinstance(link[0], str)
                or isinstance(link[1], bool)
                or not isinstance(link[1], int)
            ):
                findings.append(
                    _error(
                        "workflow.node_contract",
                        f"Node {node_id} input {input_name} is not a valid link.",
                        field_path=f"graph.{node_id}.inputs.{input_name}",
                    )
                )
                continue
            source_id, output_index = link
            source = graph.get(source_id)
            if source_id == node_id or not isinstance(source, Mapping):
                findings.append(
                    _error(
                        "workflow.graph_invalid",
                        f"Node {node_id} has a missing or self-referential link.",
                        field_path=f"graph.{node_id}.inputs.{input_name}",
                    )
                )
                continue
            source_type = source.get("class_type")
            if (
                not isinstance(source_type, str)
                or source_type not in NODE_CONTRACTS
                or output_index not in NODE_CONTRACTS[source_type].output_indices
            ):
                findings.append(
                    _error(
                        "workflow.graph_invalid",
                        f"Node {node_id} references an undeclared output index.",
                        field_path=f"graph.{node_id}.inputs.{input_name}",
                    )
                )

    findings.extend(
        _validate_exact_graph_values(graph, layout, plan, inventory, settings, staging)
    )
    return tuple(_deduplicate(findings))


def _validate_plan(plan: PredictionMixingTranslationPlan) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    conditions = plan.active_regional_conditions
    layer_ids = tuple(item.layer_id for item in conditions)
    warning_codes_valid = isinstance(plan.mandatory_warning_codes, tuple) and all(
        isinstance(code, str) and code for code in plan.mandatory_warning_codes
    )
    # The v1 graph contract can represent only the historically frozen one/two
    # layouts. This defends an authorized plan; it does not grant capability.
    if (
        plan.active_layer_count not in {1, 2}
        or plan.active_layer_count != len(conditions)
        or len(set(layer_ids)) != len(layer_ids)
    ):
        findings.append(
            _error(
                "workflow.active_layer_count",
                "Workflow generation supports exactly one or two unique Active Layers.",
                field_path="translation_plan.active_layer_count",
            )
        )
    if (
        not isinstance(plan.fingerprint, str)
        or _SHA256_PATTERN.fullmatch(plan.fingerprint) is None
        or plan.provenance_inputs.translation_plan_fingerprint != plan.fingerprint
        or plan.provenance_inputs.document_id != plan.document_id
        or plan.provenance_inputs.adapter_identifier != plan.adapter_identifier
        or plan.provenance_inputs.capability_identifier != plan.capability_identifier
        or plan.provenance_inputs.execution_profile_identifier
        != plan.execution_profile.profile_identifier
        or plan.provenance_inputs.warning_codes != plan.mandatory_warning_codes
        or not warning_codes_valid
        or (
            warning_codes_valid
            and len(plan.mandatory_warning_codes)
            != len(set(plan.mandatory_warning_codes))
        )
    ):
        findings.append(
            _error(
                "workflow.translation_required",
                "Translation plan identity and provenance must agree.",
                field_path="translation_plan",
            )
        )
    if (
        plan.execution_profile != PREDICTION_MIXING_EXECUTION_PROFILE
        or plan.translation_plan_version != TRANSLATION_PLAN_VERSION
        or plan.adapter_identifier
        != PREDICTION_MIXING_EXECUTION_PROFILE.adapter_identifier
        or plan.capability_identifier
        != PREDICTION_MIXING_EXECUTION_PROFILE.adapter_identifier
        or plan.separate_global_condition_emitted is not False
    ):
        findings.append(
            _error(
                "workflow.inventory_profile",
                "Translation plan does not use the frozen prototype execution profile.",
                field_path="translation_plan.execution_profile",
            )
        )
    if (
        plan.active_layer_count == 2
        and plan.overlap_assessment is not OverlapAssessment.NO_OVERLAP
    ) or (plan.active_layer_count == 1 and plan.overlap_assessment is not None):
        findings.append(
            _error(
                "workflow.translation_required",
                "Translation plan does not carry the required overlap state.",
                field_path="translation_plan.overlap_assessment",
            )
        )
    profile_ids = tuple(item.layer_id for item in plan.field_profiles)
    provenance_ids = tuple(item.layer_id for item in plan.provenance_inputs.layers)
    condition_profiles = tuple(item.field_profile for item in conditions)
    if (
        profile_ids != layer_ids
        or provenance_ids != layer_ids
        or condition_profiles != plan.field_profiles
    ):
        findings.append(
            _error(
                "workflow.translation_required",
                "Translation plan field and provenance records must match Active Layer order.",
                field_path="translation_plan.active_regional_conditions",
            )
        )
    for condition, provenance in zip(
        conditions, plan.provenance_inputs.layers, strict=False
    ):
        expected_hash = hashlib.sha256(
            condition.combined_prompt_text.encode("utf-8")
        ).hexdigest()
        if (
            condition.field_profile.layer_id != condition.layer_id
            or condition.field_profile.relative_path != provenance.field_reference
            or (
                condition.field_profile.checksum is not None
                and condition.field_profile.checksum != provenance.field_checksum
            )
            or expected_hash != provenance.combined_prompt_sha256
            or not math.isfinite(condition.requested_strength)
            or not 0.0 <= condition.requested_strength <= 1.0
        ):
            findings.append(
                _error(
                    "workflow.translation_required",
                    "Translation plan layer content or provenance is inconsistent.",
                    layer_id=condition.layer_id,
                    field_path="translation_plan.active_regional_conditions",
                )
            )
    return findings


def _validate_inventory(
    inventory: ComfyUIComponentInventory,
    plan: PredictionMixingTranslationPlan,
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    from .profiles import registered_inventory_for_profile

    canonical = registered_inventory_for_profile(inventory.comfyui_profile_identifier)
    if canonical is None:
        return [
            _error(
                "workflow.inventory_profile",
                "Component inventory does not identify a validated ComfyUI profile.",
                field_path="component_inventory",
            )
        ]
    profile_fields = (
        "inventory_identifier",
        "comfyui_profile_identifier",
        "supported_execution_profile_identifier",
        "expected_comfyui_version",
        "expected_comfyui_revision",
        "node_contract_identifier",
        "output_width",
        "output_height",
        "batch_size",
        "negative_prompt_policy",
        "filename_prefix_policy",
    )
    if any(getattr(inventory, name) != getattr(canonical, name) for name in profile_fields):
        findings.append(
            _error(
                "workflow.inventory_profile",
                "Component inventory does not identify the supported ComfyUI profile.",
                field_path="component_inventory",
            )
        )
    component_fields = (
        "required_node_class_names",
        "model_filename",
        "model_sha256",
        "model_size_bytes",
        "model_weight_dtype",
        "text_encoder_filename",
        "text_encoder_sha256",
        "text_encoder_size_bytes",
        "text_encoder_type",
        "text_encoder_device",
        "vae_filename",
        "vae_sha256",
        "vae_size_bytes",
        "sampler_name",
        "scheduler_name",
        "steps",
        "cfg",
        "denoise",
        "mask_channel",
        "mask_area_policy",
        "evidence_references",
    )
    if any(
        getattr(inventory, name) != getattr(canonical, name)
        for name in component_fields
    ):
        findings.append(
            _error(
                "workflow.component_inventory",
                "Component inventory differs from the verified built-in profile.",
                field_path="component_inventory",
            )
        )
    if (
        inventory.supported_execution_profile_identifier
        != plan.execution_profile.profile_identifier
        or inventory.output_width != plan.execution_profile.output_width
        or inventory.output_height != plan.execution_profile.output_height
        or inventory.negative_prompt_policy is not NegativePromptPolicy.EMPTY
    ):
        findings.append(
            _error(
                "workflow.inventory_profile",
                "Component inventory and translation execution profile do not agree.",
                field_path="component_inventory",
            )
        )
    return findings


def _validate_settings(settings: RuntimeGenerationSettings) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    if (
        isinstance(settings.seed, bool)
        or not isinstance(settings.seed, int)
        or not 0 <= settings.seed <= (2**64 - 1)
    ):
        findings.append(
            _error(
                "workflow.runtime_settings",
                "Seed must be an unsigned 64-bit integer.",
                field_path="runtime_settings.seed",
            )
        )
    if not _safe_relative_name(settings.output_filename_prefix, require_png=False):
        findings.append(
            _error(
                "workflow.runtime_settings",
                "Output filename prefix must be a safe relative POSIX path.",
                field_path="runtime_settings.output_filename_prefix",
            )
        )
    if settings.execution_request_id is not None and (
        not isinstance(settings.execution_request_id, str)
        or _REQUEST_ID_PATTERN.fullmatch(settings.execution_request_id) is None
    ):
        findings.append(
            _error(
                "workflow.runtime_settings",
                "Execution request ID must use 1-128 letters, digits, dots, underscores, or hyphens.",
                field_path="runtime_settings.execution_request_id",
            )
        )
    return findings


def _validate_staging(
    staging: FieldStagingMap,
    plan: PredictionMixingTranslationPlan,
) -> list[ValidationFinding]:
    if not isinstance(staging.filenames_by_layer_id, Mapping):
        return [
            _error(
                "workflow.field_staging_missing",
                "Field staging entries must be a layer-to-filename mapping.",
                field_path="field_staging",
            )
        ]
    expected = {item.layer_id for item in plan.active_regional_conditions}
    actual = set(staging.filenames_by_layer_id)
    findings: list[ValidationFinding] = []
    if expected - actual:
        findings.append(
            _error(
                "workflow.field_staging_missing",
                "Field staging map is missing one or more Active Layers.",
                field_path="field_staging",
            )
        )
    if actual - expected:
        findings.append(
            _error(
                "workflow.field_staging_extra",
                "Field staging map contains layers absent from the translation plan.",
                field_path="field_staging",
            )
        )
    filenames = tuple(staging.filenames_by_layer_id.values())
    normalized_filenames = tuple(
        name.casefold() for name in filenames if isinstance(name, str)
    )
    if (
        any(not _safe_relative_name(name, require_png=True) for name in filenames)
        or len(normalized_filenames) != len(filenames)
        or len(set(normalized_filenames)) != len(normalized_filenames)
    ):
        findings.append(
            _error(
                "workflow.field_staging_unsafe",
                "Staged fields require unique safe input-relative PNG filenames.",
                field_path="field_staging",
            )
        )
    return findings


def _validate_exact_graph_values(
    graph: Mapping[str, object],
    layout: Mapping[str, str],
    plan: PredictionMixingTranslationPlan,
    inventory: ComfyUIComponentInventory,
    settings: RuntimeGenerationSettings,
    staging: FieldStagingMap,
) -> list[ValidationFinding]:
    try:
        expected: dict[str, tuple[str, Mapping[str, object]]] = {
            layout["model"]: (
                "UNETLoader",
                {
                    "unet_name": inventory.model_filename,
                    "weight_dtype": inventory.model_weight_dtype,
                },
            ),
            layout["clip"]: (
                "CLIPLoader",
                {
                    "clip_name": inventory.text_encoder_filename,
                    "type": inventory.text_encoder_type,
                    "device": inventory.text_encoder_device,
                },
            ),
            layout["negative"]: (
                "CLIPTextEncode",
                {"text": "", "clip": [layout["clip"], 0]},
            ),
            layout["latent"]: (
                "EmptyLatentImage",
                {
                    "width": inventory.output_width,
                    "height": inventory.output_height,
                    "batch_size": inventory.batch_size,
                },
            ),
            layout["vae"]: (
                "VAELoader",
                {"vae_name": inventory.vae_filename},
            ),
            layout["decode"]: (
                "VAEDecode",
                {
                    "samples": [layout["sampler"], 0],
                    "vae": [layout["vae"], 0],
                },
            ),
            layout["save"]: (
                "SaveImage",
                {
                    "filename_prefix": settings.output_filename_prefix,
                    "images": [layout["decode"], 0],
                },
            ),
        }
        mask_ids: list[str] = []
        for condition in plan.active_regional_conditions:
            layer_id = condition.layer_id
            prompt_id = layout[f"prompt:{layer_id}"]
            field_id = layout[f"field:{layer_id}"]
            mask_id = layout[f"mask:{layer_id}"]
            expected[prompt_id] = (
                "CLIPTextEncode",
                {"text": condition.combined_prompt_text, "clip": [layout["clip"], 0]},
            )
            expected[field_id] = (
                "LoadImageMask",
                {
                    "image": staging.filenames_by_layer_id[layer_id],
                    "channel": inventory.mask_channel,
                },
            )
            expected[mask_id] = (
                "ConditioningSetMask",
                {
                    "strength": condition.requested_strength,
                    "set_cond_area": inventory.mask_area_policy,
                    "conditioning": [prompt_id, 0],
                    "mask": [field_id, 0],
                },
            )
            mask_ids.append(mask_id)
        positive_id = mask_ids[0]
        if len(mask_ids) == 2:
            combine_id = layout["combine"]
            expected[combine_id] = (
                "ConditioningCombine",
                {
                    "conditioning_1": [mask_ids[0], 0],
                    "conditioning_2": [mask_ids[1], 0],
                },
            )
            positive_id = combine_id
        expected[layout["sampler"]] = (
            "KSampler",
            {
                "seed": settings.seed,
                "steps": inventory.steps,
                "cfg": inventory.cfg,
                "sampler_name": inventory.sampler_name,
                "scheduler": inventory.scheduler_name,
                "denoise": inventory.denoise,
                "model": [layout["model"], 0],
                "positive": [positive_id, 0],
                "negative": [layout["negative"], 0],
                "latent_image": [layout["latent"], 0],
            },
        )
    except (KeyError, TypeError):
        return [
            _error(
                "workflow.graph_invalid",
                "Graph inputs cannot be reconciled with declared generation inputs.",
                field_path="graph",
            )
        ]

    for node_id, (class_type, inputs) in expected.items():
        node = graph.get(node_id)
        if (
            not isinstance(node, Mapping)
            or node.get("class_type") != class_type
            or node.get("inputs") != inputs
        ):
            return [
                _error(
                    "workflow.graph_invalid",
                    "Graph values differ from the translation plan or declared profile.",
                    field_path=f"graph.{node_id}",
                )
            ]
    return []


def _safe_relative_name(value: object, *, require_png: bool) -> bool:
    if not isinstance(value, str) or not value or not value.strip():
        return False
    if (
        "\\" in value
        or "\x00" in value
        or any(character in value for character in '<>:"|?*')
        or _URI_PATTERN.match(value)
    ):
        return False
    windows_path = PureWindowsPath(value)
    posix_path = PurePosixPath(value)
    if windows_path.drive or windows_path.is_absolute() or posix_path.is_absolute():
        return False
    if any(part in {"", ".", ".."} for part in value.split("/")):
        return False
    return not require_png or value.lower().endswith(".png")


def _deduplicate(findings: list[ValidationFinding]) -> list[ValidationFinding]:
    unique: list[ValidationFinding] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for finding in findings:
        key = (finding.code, finding.layer_id, finding.field_path)
        if key not in seen:
            seen.add(key)
            unique.append(finding)
    return unique


def _error(
    code: str,
    message: str,
    *,
    layer_id: str | None = None,
    field_path: str | None = None,
) -> ValidationFinding:
    return ValidationFinding(
        code=code,
        severity=FindingSeverity.ERROR,
        message=message,
        layer_id=layer_id,
        field_path=field_path,
    )
