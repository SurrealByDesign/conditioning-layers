"""Direct, deterministic realization of verified Plan v3; no filesystem or host I/O."""

from collections.abc import Mapping
import hashlib

from conditioning_layers.adapters.prediction_mixing.multi_layer import verify_translation_plan, plan_warning_codes
from conditioning_layers.comfyui.prediction_mixing.models import (
    FieldStagingMap, RuntimeGenerationSettings, WorkflowLayerProvenance,
)
from conditioning_layers.comfyui.prediction_mixing.validation import _safe_relative_name, _validate_settings
from conditioning_layers.domain import FindingSeverity, ValidationFinding

from .authority import EXACT_THREE_REALIZATION, verify_realization_binding
from .canonical import canonical_bytes, fingerprint
from .models import (
    GRAPH_FORMAT_IDENTIFIER, GRAPH_FORMAT_VERSION, GENERATOR_VERSION_IDENTIFIER,
    MultiLayerWorkflowProvenance, MultiLayerGraphArtifact, MultiLayerGraphResult,
)


def _error(code, message):
    return ValidationFinding(code, FindingSeverity.ERROR, message)


def _document_provenance_valid(plan, document_id, disabled_layer_ids):
    return (
        isinstance(document_id, str) and bool(document_id.strip())
        and type(disabled_layer_ids) is tuple
        and all(isinstance(item, str) and item.strip() for item in disabled_layer_ids)
        and len(set(disabled_layer_ids)) == len(disabled_layer_ids)
        and not set(disabled_layer_ids) & {item.layer_id for item in plan.regional_conditions}
    )


def _strength(condition):
    # Plan v3's binary64 canonical semantics identify both signed zeros as 0.
    # Preserve that identity when projecting into exact-integer host JSON.
    return 0.0 if condition.requested_strength == 0 else condition.requested_strength


def _inputs(plan, inventory, settings, staging, binding):
    errors = list(verify_translation_plan(plan))
    if errors:
        return tuple(errors)
    errors.extend(verify_realization_binding(binding, plan, inventory))
    if type(settings) is not RuntimeGenerationSettings:
        errors.append(_error("multi_layer.settings.invalid", "Explicit runtime settings are required."))
    else:
        errors.extend(_validate_settings(settings))
    if type(staging) is not FieldStagingMap or not isinstance(staging.filenames_by_layer_id, Mapping):
        errors.append(_error("multi_layer.staging.invalid", "Complete staging assignments are required."))
    else:
        names = tuple(staging.filenames_by_layer_id.values())
        if (set(staging.filenames_by_layer_id) != {item.layer_id for item in plan.regional_conditions}
                or any(not _safe_relative_name(name, require_png=True) for name in names)
                or len({name.casefold() for name in names if isinstance(name, str)}) != len(names)):
            errors.append(_error("multi_layer.staging.invalid", "Staging must bind every ordered layer to a unique safe PNG."))
    return tuple(errors)


def _build_graph(plan, inventory, settings, staging):
    # Called only after selected-entry/binding validation. This formula does not
    # register or admit another count; the only realization authority is exact 3.
    n = plan.eligibility_entry.exact_cardinality
    graph = {}
    def node(node_id, class_type, **inputs):
        graph[str(node_id)] = {"inputs": inputs, "class_type": class_type}
    def link(node_id):
        return [str(node_id), 0]
    node(1, "UNETLoader", unet_name=inventory.model_filename, weight_dtype=inventory.model_weight_dtype)
    node(2, "CLIPLoader", clip_name=inventory.text_encoder_filename, type=inventory.text_encoder_type, device=inventory.text_encoder_device)
    for i, condition in enumerate(plan.regional_conditions):
        node(3+i, "CLIPTextEncode", text=condition.combined_prompt_text, clip=link(2))
    node(n+3, "CLIPTextEncode", text="", clip=link(2))
    for i, condition in enumerate(plan.regional_conditions):
        node(n+4+i, "LoadImageMask", image=staging.filenames_by_layer_id[condition.layer_id], channel=inventory.mask_channel)
    operands = {}
    for i, condition in enumerate(plan.regional_conditions):
        node(2*n+4+i, "ConditioningSetMask", conditioning=link(3+i), mask=link(n+4+i),
             strength=_strength(condition), set_cond_area=inventory.mask_area_policy)
        operands[f"condition:{i}"] = 2*n+4+i
    for step in plan.fold_schedule:
        node_id = 3*n+4+step.step_ordinal
        node(node_id, "ConditioningCombine", conditioning_1=link(operands[step.left_operand]),
             conditioning_2=link(operands[step.right_condition]))
        operands[step.result] = node_id
    node(4*n+3, "EmptyLatentImage", width=inventory.output_width, height=inventory.output_height, batch_size=inventory.batch_size)
    node(4*n+4, "KSampler", seed=settings.seed, steps=inventory.steps, cfg=inventory.cfg,
         sampler_name=inventory.sampler_name, scheduler=inventory.scheduler_name, denoise=inventory.denoise,
         model=link(1), positive=link(operands[plan.fold_schedule[-1].result]), negative=link(n+3), latent_image=link(4*n+3))
    node(4*n+5, "VAELoader", vae_name=inventory.vae_filename)
    node(4*n+6, "VAEDecode", samples=link(4*n+4), vae=link(4*n+5))
    node(4*n+7, "SaveImage", filename_prefix=settings.output_filename_prefix, images=link(4*n+6))
    return graph


def _envelope(plan, binding, graph):
    return {
        "graph_identifier": GRAPH_FORMAT_IDENTIFIER, "graph_version": GRAPH_FORMAT_VERSION,
        "generator_identifier": GENERATOR_VERSION_IDENTIFIER,
        "contract_identifier": plan.contract_identifier, "contract_version": plan.contract_version,
        "eligibility_entry_identifier": plan.eligibility_entry.identifier,
        "eligibility_entry_fingerprint": plan.eligibility_entry.fingerprint,
        "exact_admitted_cardinality": plan.eligibility_entry.exact_cardinality,
        "realization_binding_identifier": binding.identifier,
        "realization_binding_fingerprint": binding.fingerprint,
        "translation_plan_identifier": plan.format_identifier,
        "translation_plan_version": plan.format_version, "translation_plan_fingerprint": plan.fingerprint,
        "execution_profile_identifier": plan.execution_profile.profile_identifier,
        "execution_profile_fingerprint": plan.execution_profile.fingerprint,
        "api_graph": graph,
    }


def fingerprint_multi_layer_graph(artifact):
    return fingerprint(_envelope(artifact.source_plan, artifact.realization_binding, artifact.canonical_graph))


def _provenance(plan, binding, inventory, settings, staging, graph_fingerprint, document_id, disabled_layer_ids, warnings):
    return MultiLayerWorkflowProvenance(
        document_id=document_id, contract_identifier=plan.contract_identifier, contract_version=plan.contract_version,
        translation_plan_identifier=plan.format_identifier, translation_plan_version=plan.format_version,
        translation_plan_fingerprint=plan.fingerprint, eligibility_entry_identifier=plan.eligibility_entry.identifier,
        eligibility_entry_fingerprint=plan.eligibility_entry.fingerprint, exact_admitted_cardinality=plan.eligibility_entry.exact_cardinality,
        realization_binding_identifier=binding.identifier, realization_binding_fingerprint=binding.fingerprint,
        execution_profile_identifier=plan.execution_profile.profile_identifier, execution_profile_fingerprint=plan.execution_profile.fingerprint,
        graph_identifier=GRAPH_FORMAT_IDENTIFIER, graph_version=GRAPH_FORMAT_VERSION, graph_fingerprint=graph_fingerprint,
        adapter_identifier=plan.execution_profile.adapter_identifier, component_inventory_identifier=inventory.inventory_identifier,
        model_filename=inventory.model_filename, model_sha256=inventory.model_sha256,
        text_encoder_filename=inventory.text_encoder_filename, text_encoder_sha256=inventory.text_encoder_sha256,
        vae_filename=inventory.vae_filename, vae_sha256=inventory.vae_sha256,
        active_layers=tuple(WorkflowLayerProvenance(
            layer_id=item.layer_id, combined_prompt_sha256=hashlib.sha256(item.combined_prompt_text.encode("utf-8")).hexdigest(),
            document_field_reference=item.field_profile.relative_path, staged_field_filename=staging.filenames_by_layer_id[item.layer_id],
            field_checksum=item.field_profile.checksum, requested_strength=_strength(item),
        ) for item in plan.regional_conditions),
        disabled_layer_ids=disabled_layer_ids, seed=settings.seed, output_filename_prefix=settings.output_filename_prefix,
        execution_request_id=settings.execution_request_id, mandatory_warning_codes=warnings,
        generator_version_identifier=GENERATOR_VERSION_IDENTIFIER,
    )


def generate_prediction_mixing_multi_layer_workflow(plan, inventory, settings, staging, *,
        document_id, disabled_layer_ids=(), binding=EXACT_THREE_REALIZATION):
    errors = _inputs(plan, inventory, settings, staging, binding)
    if errors:
        return MultiLayerGraphResult(None, errors)
    if not _document_provenance_valid(plan, document_id, disabled_layer_ids):
        return MultiLayerGraphResult(None, (_error("multi_layer.provenance.invalid", "Document provenance is malformed."),))
    try:
        graph = _build_graph(plan, inventory, settings, staging)
        digest = fingerprint(_envelope(plan, binding, graph))
        # Warnings are execution evidence, not UI prose or registry state.
        warnings = plan_warning_codes(plan)
        provenance = _provenance(plan, binding, inventory, settings, staging, digest, document_id, disabled_layer_ids, warnings)
        artifact = MultiLayerGraphArtifact(
            GRAPH_FORMAT_IDENTIFIER, GRAPH_FORMAT_VERSION, plan.execution_profile.adapter_identifier,
            plan.fingerprint, graph, digest, inventory.required_node_class_names, warnings, provenance,
            plan, binding, settings, staging,
        )
        errors = validate_multi_layer_artifact(artifact, provenance, inventory)
        return MultiLayerGraphResult(None if errors else artifact, errors)
    except (TypeError, ValueError, KeyError, AttributeError, UnicodeError):
        return MultiLayerGraphResult(None, (_error("multi_layer.graph.invalid", "Graph realization inputs are inconsistent."),))


def validate_multi_layer_artifact(artifact, provenance, inventory):
    """Reconcile every declaration and exact graph against verified source authority."""
    if type(artifact) is not MultiLayerGraphArtifact or type(provenance) is not MultiLayerWorkflowProvenance:
        return (_error("multi_layer.graph.type", "The direct multi-layer graph family is required."),)
    try:
        plan, binding = artifact.source_plan, artifact.realization_binding
        errors = _inputs(plan, inventory, artifact.settings, artifact.staging, binding)
        if errors:
            return errors
        if not _document_provenance_valid(plan, provenance.document_id, provenance.disabled_layer_ids):
            raise ValueError("document provenance malformed")
        graph = _build_graph(plan, inventory, artifact.settings, artifact.staging)
        n = plan.eligibility_entry.exact_cardinality
        links = sum(isinstance(value, list) for node in graph.values() for value in node["inputs"].values())
        if len(graph) != 4*n+7 or links != 5*n+6:
            raise ValueError("allocation invariant")
        if canonical_bytes(artifact.canonical_graph) != canonical_bytes(graph):
            raise ValueError("graph nodes, ports, values or ordering differ")
        if tuple(artifact.canonical_graph) != tuple(graph):
            raise ValueError("allocation order differs")
        digest = fingerprint_multi_layer_graph(artifact)
        expected = _provenance(plan, binding, inventory, artifact.settings, artifact.staging,
                               digest, provenance.document_id, provenance.disabled_layer_ids, plan_warning_codes(plan))
        if (canonical_bytes(provenance) != canonical_bytes(expected)
                or canonical_bytes(artifact.provenance_inputs) != canonical_bytes(expected)
                or artifact.graph_fingerprint != digest
                or artifact.graph_format_identifier != GRAPH_FORMAT_IDENTIFIER
                or artifact.graph_format_version != GRAPH_FORMAT_VERSION
                or artifact.adapter_identifier != plan.execution_profile.adapter_identifier
                or artifact.source_translation_plan_fingerprint != plan.fingerprint
                or artifact.warnings != plan_warning_codes(plan)
                or artifact.required_host_components != inventory.required_node_class_names):
            raise ValueError("explicit identity declarations disagree")
    except (TypeError, ValueError, KeyError, AttributeError, UnicodeError):
        return (_error("multi_layer.graph.invalid", "Graph, provenance and selected authority must agree exactly."),)
    return ()
