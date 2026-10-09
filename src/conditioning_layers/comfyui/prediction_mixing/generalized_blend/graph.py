"""Deterministic graph-v4 realization of verified exact N=4..9 Blend Plan v4; no I/O.

An additive successor: the retained exact-3 graph-v3 generator, its class and
its bindings are unchanged and cannot accept these plans. Node and link
allocation keep the Plan v4 phase order (4N + 8 nodes, 5N + 7 host links); the
preparation node's expected-count literal adds no host link.
"""

from collections.abc import Mapping
import hashlib

from conditioning_layers.adapters.prediction_mixing.blend import verify_translation_plan, plan_warning_codes
from conditioning_layers.adapters.prediction_mixing.v2.identity import exact_contract_equal
from conditioning_layers.comfyui.prediction_mixing.models import (
    FieldStagingMap, RuntimeGenerationSettings, WorkflowLayerProvenance,
)
from conditioning_layers.comfyui.prediction_mixing.validation import _safe_relative_name, _validate_settings
from conditioning_layers.comfyui.prediction_mixing.generalized_blend_component import (
    GENERALIZED_BLEND_COMPONENT_CONTRACT_ID, GENERALIZED_BLEND_NODE_CLASS,
)
from conditioning_layers.comfyui.prediction_mixing.multi_layer.canonical import canonical_bytes, fingerprint
from conditioning_layers.domain import FindingSeverity, ValidationFinding

from .authority import (
    GENERALIZED_BLEND_GRAPH_PERMITTED_CLASSES,
    verify_generalized_permitted_class_authority, verify_generalized_realization_binding,
)
from .models import (
    GRAPH_FORMAT_IDENTIFIER, GRAPH_FORMAT_VERSION, GENERATOR_VERSION_IDENTIFIER,
    GeneralizedBlendGraphArtifact, GeneralizedBlendGraphResult, GeneralizedBlendWorkflowProvenance,
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
    # Plan v4's binary64 canonical semantics identify both signed zeros as 0.
    return 0.0 if condition.requested_strength == 0 else condition.requested_strength


def _inputs(plan, inventory, settings, staging, binding):
    errors = list(verify_translation_plan(plan))
    if errors:
        return tuple(errors)
    errors.extend(verify_generalized_realization_binding(binding, plan, inventory))
    if type(settings) is not RuntimeGenerationSettings:
        errors.append(_error("blend.settings.invalid", "Explicit runtime settings are required."))
    else:
        errors.extend(_validate_settings(settings))
    if type(staging) is not FieldStagingMap or not isinstance(staging.filenames_by_layer_id, Mapping):
        errors.append(_error("blend.staging.invalid", "Complete staging assignments are required."))
    else:
        names = tuple(staging.filenames_by_layer_id.values())
        if (set(staging.filenames_by_layer_id) != {item.layer_id for item in plan.regional_conditions}
                or any(not _safe_relative_name(name, require_png=True) for name in names)
                or len({name.casefold() for name in names if isinstance(name, str)}) != len(names)):
            errors.append(_error("blend.staging.invalid", "Staging must bind every ordered layer to a unique safe PNG."))
    return tuple(errors)


def _build_graph(plan, inventory, settings, staging, binding):
    # Called only after exact entry/binding validation: n is the verified
    # selected count, and the literal is the binding's trusted expected count.
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
    node(4*n+3, GENERALIZED_BLEND_NODE_CLASS, conditioning=link(operands[plan.fold_schedule[-1].result]),
         expected_count=binding.expected_count)
    node(4*n+4, "EmptyLatentImage", width=inventory.output_width, height=inventory.output_height, batch_size=inventory.batch_size)
    node(4*n+5, "KSampler", seed=settings.seed, steps=inventory.steps, cfg=inventory.cfg,
         sampler_name=inventory.sampler_name, scheduler=inventory.scheduler_name, denoise=inventory.denoise,
         model=link(1), positive=link(4*n+3), negative=link(n+3), latent_image=link(4*n+4))
    node(4*n+6, "VAELoader", vae_name=inventory.vae_filename)
    node(4*n+7, "VAEDecode", samples=link(4*n+5), vae=link(4*n+6))
    node(4*n+8, "SaveImage", filename_prefix=settings.output_filename_prefix, images=link(4*n+7))
    return graph


def _envelope(plan, binding, graph):
    return {
        "graph_identifier": GRAPH_FORMAT_IDENTIFIER, "graph_version": GRAPH_FORMAT_VERSION,
        "generator_identifier": GENERATOR_VERSION_IDENTIFIER,
        "contract_identifier": plan.contract_identifier, "contract_version": plan.contract_version,
        "eligibility_entry_identifier": plan.eligibility_entry.identifier,
        "eligibility_entry_fingerprint": plan.eligibility_entry.fingerprint,
        "exact_admitted_cardinality": plan.eligibility_entry.exact_cardinality,
        "expected_count": binding.expected_count,
        "realization_binding_identifier": binding.identifier,
        "realization_binding_fingerprint": binding.fingerprint,
        "translation_plan_identifier": plan.format_identifier,
        "translation_plan_version": plan.format_version, "translation_plan_fingerprint": plan.fingerprint,
        "execution_profile_identifier": plan.execution_profile.profile_identifier,
        "execution_profile_fingerprint": plan.execution_profile.fingerprint,
        "composition_policy": plan.document_projection.composition_policy,
        "project_component_identity": binding.project_component_identity,
        "permitted_class_authority_identifier": binding.permitted_class_authority_identifier,
        "permitted_class_authority_fingerprint": binding.permitted_class_authority_fingerprint,
        "api_graph": graph,
    }


def fingerprint_generalized_blend_graph(artifact):
    return fingerprint(_envelope(artifact.source_plan, artifact.realization_binding, artifact.canonical_graph))


def _provenance(plan, binding, inventory, settings, staging, graph_fingerprint, document_id, disabled_layer_ids, warnings):
    return GeneralizedBlendWorkflowProvenance(
        document_id=document_id, contract_identifier=plan.contract_identifier, contract_version=plan.contract_version,
        translation_plan_identifier=plan.format_identifier, translation_plan_version=plan.format_version,
        translation_plan_fingerprint=plan.fingerprint, eligibility_entry_identifier=plan.eligibility_entry.identifier,
        eligibility_entry_fingerprint=plan.eligibility_entry.fingerprint,
        exact_admitted_cardinality=plan.eligibility_entry.exact_cardinality, expected_count=binding.expected_count,
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
        composition_policy_identifier=plan.document_projection.composition_policy.policy_identifier,
        composition_policy_version=plan.document_projection.composition_policy.policy_version,
        composition_policy_fingerprint=fingerprint(plan.document_projection.composition_policy),
        project_component_identifier=binding.project_component_identity.component_id,
        project_component_contract_identifier=binding.project_component_identity.contract_id,
        project_component_implementation_fingerprint=binding.project_component_identity.implementation_fingerprint,
        permitted_class_authority_identifier=binding.permitted_class_authority_identifier,
        permitted_class_authority_fingerprint=binding.permitted_class_authority_fingerprint,
    )


def generate_generalized_blend_workflow(plan, inventory, settings, staging, *, binding,
        document_id, disabled_layer_ids=(), permitted_class_authority=GENERALIZED_BLEND_GRAPH_PERMITTED_CLASSES):
    """Emit graph v4 for one verified plan and its explicitly selected exact binding."""
    errors = (_inputs(plan, inventory, settings, staging, binding)
              + verify_generalized_permitted_class_authority(permitted_class_authority, inventory))
    if errors:
        return GeneralizedBlendGraphResult(None, errors)
    if not _document_provenance_valid(plan, document_id, disabled_layer_ids):
        return GeneralizedBlendGraphResult(None, (_error("blend.provenance.invalid", "Document provenance is malformed."),))
    try:
        graph = _build_graph(plan, inventory, settings, staging, binding)
        digest = fingerprint(_envelope(plan, binding, graph))
        warnings = plan_warning_codes(plan)
        provenance = _provenance(plan, binding, inventory, settings, staging, digest, document_id, disabled_layer_ids, warnings)
        artifact = GeneralizedBlendGraphArtifact(
            GRAPH_FORMAT_IDENTIFIER, GRAPH_FORMAT_VERSION, plan.execution_profile.adapter_identifier,
            plan.fingerprint, graph, digest, inventory.required_node_class_names + (GENERALIZED_BLEND_NODE_CLASS,),
            warnings, provenance, plan, binding, permitted_class_authority, settings, staging,
        )
        errors = validate_generalized_blend_artifact(artifact, provenance, inventory)
        return GeneralizedBlendGraphResult(None if errors else artifact, errors)
    except (TypeError, ValueError, KeyError, AttributeError, UnicodeError):
        return GeneralizedBlendGraphResult(None, (_error("blend.graph.invalid", "Graph realization inputs are inconsistent."),))


def validate_generalized_blend_artifact(artifact, provenance, inventory):
    """Reconcile every declaration and exact graph against verified source authority."""
    if type(artifact) is not GeneralizedBlendGraphArtifact or type(provenance) is not GeneralizedBlendWorkflowProvenance:
        return (_error("blend.graph.type", "The generalized Blend graph-v4 family is required."),)
    try:
        plan, binding = artifact.source_plan, artifact.realization_binding
        errors = _inputs(plan, inventory, artifact.settings, artifact.staging, binding)
        if errors:
            return errors
        if not _document_provenance_valid(plan, provenance.document_id, provenance.disabled_layer_ids):
            raise ValueError("document provenance malformed")
        graph = _build_graph(plan, inventory, artifact.settings, artifact.staging, binding)
        n = plan.eligibility_entry.exact_cardinality
        links = sum(isinstance(value, list) for node in graph.values() for value in node["inputs"].values())
        preparation = graph[str(4*n+3)]
        if (len(graph) != 4*n+8 or links != 5*n+7
                or preparation["class_type"] != GENERALIZED_BLEND_NODE_CLASS
                or type(preparation["inputs"]["expected_count"]) is not int
                or preparation["inputs"]["expected_count"] != n
                or tuple(graph)[-1] != str(4*n+8) or graph[str(4*n+8)]["class_type"] != "SaveImage"):
            raise ValueError("allocation invariant")
        class_errors = verify_generalized_permitted_class_authority(
            artifact.permitted_class_authority, inventory, artifact.canonical_graph)
        if class_errors:
            return class_errors
        if canonical_bytes(artifact.canonical_graph) != canonical_bytes(graph):
            raise ValueError("graph nodes, ports, values or ordering differ")
        if tuple(artifact.canonical_graph) != tuple(graph):
            raise ValueError("allocation order differs")
        digest = fingerprint_generalized_blend_graph(artifact)
        expected = _provenance(plan, binding, inventory, artifact.settings, artifact.staging,
                               digest, provenance.document_id, provenance.disabled_layer_ids, plan_warning_codes(plan))
        if (not exact_contract_equal(provenance, expected)
                or not exact_contract_equal(artifact.provenance_inputs, expected)
                or provenance.project_component_contract_identifier != GENERALIZED_BLEND_COMPONENT_CONTRACT_ID
                or artifact.graph_fingerprint != digest
                or artifact.graph_format_identifier != GRAPH_FORMAT_IDENTIFIER
                or artifact.graph_format_version != GRAPH_FORMAT_VERSION
                or artifact.adapter_identifier != plan.execution_profile.adapter_identifier
                or artifact.source_translation_plan_fingerprint != plan.fingerprint
                or artifact.warnings != plan_warning_codes(plan)
                or artifact.required_host_components != inventory.required_node_class_names + (GENERALIZED_BLEND_NODE_CLASS,)):
            raise ValueError("explicit identity declarations disagree")
    except (TypeError, ValueError, KeyError, AttributeError, UnicodeError):
        return (_error("blend.graph.invalid", "Graph, provenance and selected authority must agree exactly."),)
    return ()
