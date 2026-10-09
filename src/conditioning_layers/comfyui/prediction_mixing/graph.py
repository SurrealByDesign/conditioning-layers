"""Pure deterministic generation of a prototype ComfyUI API prompt graph."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json

from conditioning_layers.adapters.prediction_mixing import (
    PredictionMixingTranslationPlan,
)
from conditioning_layers.domain import FindingSeverity, ValidationFinding

from .inventory import node_id_layout
from .models import (
    GRAPH_FORMAT_IDENTIFIER,
    GRAPH_FORMAT_VERSION,
    ComfyUIApiGraphArtifact,
    ComfyUIComponentInventory,
    FieldStagingMap,
    RuntimeGenerationSettings,
    WorkflowGenerationResult,
)
from .provenance import build_workflow_provenance
from .validation import validate_api_graph, validate_generation_inputs


def generate_prediction_mixing_workflow(
    plan: object,
    inventory: object,
    settings: object,
    staging: object,
) -> WorkflowGenerationResult:
    """Generate and validate an API graph without any host or filesystem access."""

    errors = validate_generation_inputs(plan, inventory, settings, staging)
    warnings = _preserved_warnings(plan)
    if errors:
        return WorkflowGenerationResult(
            artifact=None,
            errors=errors,
            warnings=warnings,
            information=(),
            generated=False,
        )
    assert isinstance(plan, PredictionMixingTranslationPlan)
    assert isinstance(inventory, ComfyUIComponentInventory)
    assert isinstance(settings, RuntimeGenerationSettings)
    assert isinstance(staging, FieldStagingMap)

    graph = _build_graph(plan, inventory, settings, staging)
    graph_errors = validate_api_graph(graph, plan, inventory, settings, staging)
    if graph_errors:
        return WorkflowGenerationResult(
            artifact=None,
            errors=graph_errors,
            warnings=warnings,
            information=(),
            generated=False,
        )
    fingerprint = fingerprint_api_graph(graph)
    warning_codes = tuple(finding.code for finding in warnings)
    provenance = build_workflow_provenance(
        plan,
        inventory,
        settings,
        staging,
        fingerprint,
        warning_codes,
    )
    required_components = tuple(
        class_name
        for class_name in inventory.required_node_class_names
        if any(node["class_type"] == class_name for node in graph.values())
    )
    artifact = ComfyUIApiGraphArtifact(
        graph_format_identifier=GRAPH_FORMAT_IDENTIFIER,
        graph_format_version=GRAPH_FORMAT_VERSION,
        adapter_identifier=plan.adapter_identifier,
        source_translation_plan_fingerprint=plan.fingerprint,
        canonical_graph=graph,
        graph_fingerprint=fingerprint,
        required_host_components=required_components,
        warnings=warning_codes,
        provenance_inputs=provenance,
    )
    information = (
        ValidationFinding(
            code="workflow.graph_created",
            severity=FindingSeverity.INFORMATION,
            message="A deterministic prototype ComfyUI API graph was created.",
            field_path="graph",
        ),
    )
    return WorkflowGenerationResult(
        artifact=artifact,
        errors=(),
        warnings=warnings,
        information=information,
        generated=True,
    )


def fingerprint_api_graph(graph: Mapping[str, object]) -> str:
    """Hash the canonical JSON-compatible graph with no timestamps or whitespace."""

    canonical = json.dumps(
        _json_compatible(graph),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _json_compatible(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_compatible(item) for item in value]
    return value


def _build_graph(
    plan: PredictionMixingTranslationPlan,
    inventory: ComfyUIComponentInventory,
    settings: RuntimeGenerationSettings,
    staging: FieldStagingMap,
) -> dict[str, dict[str, object]]:
    layer_ids = tuple(item.layer_id for item in plan.active_regional_conditions)
    ids = node_id_layout(layer_ids)
    graph: dict[str, dict[str, object]] = {
        ids["model"]: {
            "inputs": {
                "unet_name": inventory.model_filename,
                "weight_dtype": inventory.model_weight_dtype,
            },
            "class_type": "UNETLoader",
        },
        ids["clip"]: {
            "inputs": {
                "clip_name": inventory.text_encoder_filename,
                "type": inventory.text_encoder_type,
                "device": inventory.text_encoder_device,
            },
            "class_type": "CLIPLoader",
        },
    }
    for condition in plan.active_regional_conditions:
        prompt_id = ids[f"prompt:{condition.layer_id}"]
        graph[prompt_id] = {
            "inputs": {
                "text": condition.combined_prompt_text,
                "clip": [ids["clip"], 0],
            },
            "class_type": "CLIPTextEncode",
        }
    graph[ids["negative"]] = {
        "inputs": {"text": "", "clip": [ids["clip"], 0]},
        "class_type": "CLIPTextEncode",
    }
    for condition in plan.active_regional_conditions:
        layer_id = condition.layer_id
        graph[ids[f"field:{layer_id}"]] = {
            "inputs": {
                "image": staging.filenames_by_layer_id[layer_id],
                "channel": inventory.mask_channel,
            },
            "class_type": "LoadImageMask",
        }
    mask_ids: list[str] = []
    for condition in plan.active_regional_conditions:
        layer_id = condition.layer_id
        mask_id = ids[f"mask:{layer_id}"]
        graph[mask_id] = {
            "inputs": {
                "strength": condition.requested_strength,
                "set_cond_area": inventory.mask_area_policy,
                "conditioning": [ids[f"prompt:{layer_id}"], 0],
                "mask": [ids[f"field:{layer_id}"], 0],
            },
            "class_type": "ConditioningSetMask",
        }
        mask_ids.append(mask_id)
    positive_id = mask_ids[0]
    if len(mask_ids) == 2:
        graph[ids["combine"]] = {
            "inputs": {
                "conditioning_1": [mask_ids[0], 0],
                "conditioning_2": [mask_ids[1], 0],
            },
            "class_type": "ConditioningCombine",
        }
        positive_id = ids["combine"]
    graph[ids["latent"]] = {
        "inputs": {
            "width": inventory.output_width,
            "height": inventory.output_height,
            "batch_size": inventory.batch_size,
        },
        "class_type": "EmptyLatentImage",
    }
    graph[ids["sampler"]] = {
        "inputs": {
            "seed": settings.seed,
            "steps": inventory.steps,
            "cfg": inventory.cfg,
            "sampler_name": inventory.sampler_name,
            "scheduler": inventory.scheduler_name,
            "denoise": inventory.denoise,
            "model": [ids["model"], 0],
            "positive": [positive_id, 0],
            "negative": [ids["negative"], 0],
            "latent_image": [ids["latent"], 0],
        },
        "class_type": "KSampler",
    }
    graph[ids["vae"]] = {
        "inputs": {"vae_name": inventory.vae_filename},
        "class_type": "VAELoader",
    }
    graph[ids["decode"]] = {
        "inputs": {
            "samples": [ids["sampler"], 0],
            "vae": [ids["vae"], 0],
        },
        "class_type": "VAEDecode",
    }
    graph[ids["save"]] = {
        "inputs": {
            "filename_prefix": settings.output_filename_prefix,
            "images": [ids["decode"], 0],
        },
        "class_type": "SaveImage",
    }
    return graph


def _preserved_warnings(plan: object) -> tuple[ValidationFinding, ...]:
    if not isinstance(plan, PredictionMixingTranslationPlan):
        return ()
    warnings: list[ValidationFinding] = []
    seen: set[str] = set()
    for code in plan.mandatory_warning_codes:
        if isinstance(code, str) and code and code not in seen:
            seen.add(code)
            warnings.append(
                ValidationFinding(
                    code=code,
                    severity=FindingSeverity.WARNING,
                    message=f"Preserved translation warning: {code}.",
                )
            )
    return tuple(warnings)
