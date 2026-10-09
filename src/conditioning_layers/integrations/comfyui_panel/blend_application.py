"""Exact-three product plumbing; retained Blend backend contracts are reused."""

import re
from urllib.parse import urlencode

from conditioning_layers.adapters.prediction_mixing.blend import translate_prediction_mixing_blend
from conditioning_layers.assets import FieldRelationshipInput, inspect_field_relationships, to_field_asset_profile
from conditioning_layers.capabilities.blend import BLEND_CONTRACT_IDENTIFIER
from conditioning_layers.comfyui.prediction_mixing import FieldStagingMap, RuntimeGenerationSettings
from conditioning_layers.comfyui.prediction_mixing.blend import (
    generate_prediction_mixing_blend_workflow, select_blend_realization,
)
from conditioning_layers.comfyui.prediction_mixing.blend_component import blend_component_identity
from conditioning_layers.execution.comfyui import ExecutionState, execute_submission_bundle
from conditioning_layers.execution.comfyui.blend import (
    BlendExecutionResult, EXECUTION_RESULT_VERSION, execute_blend_submission_bundle,
    build_blend_execution_provenance, fingerprint_blend_result_identity, validate_blend_execution_provenance,
)
from conditioning_layers.execution.comfyui.models import AssociatedOutput
from conditioning_layers.execution.comfyui.outputs import _safe_relative_locator
from conditioning_layers.runtime.comfyui import staging_namespace_for_document
from conditioning_layers.runtime.comfyui.blend import capture_blend_component_availability, prepare_blend_submission_bundle

from .application import PreparedPanelExecution
from .guidance import project_product_warnings
from .models import PanelFinding, PanelOutput, PanelRunResult, project_findings, validate_execution_id


def _failure(code, message, *, state="rejected"):
    return PanelRunResult(state, (PanelFinding(code, "error", message),))


def prepare_blend(application, materialized, draft, execution_id, publish_state, route):
    policy = application._host.execution_policy
    if (not validate_execution_id(execution_id) or policy.require_output_prefix_match is not True
            or policy.require_expected_save_image_node is not True):
        return _failure("panel.blend.execution_contract", "Blend requires the exact product output association contract.")
    document, labels = materialized.document, materialized.layer_labels
    inspected = inspect_field_relationships(materialized.asset_root, tuple(
        FieldRelationshipInput(layer, index) for index, layer in enumerate(document.layers) if layer.visible
    ))
    translated = translate_prediction_mixing_blend(
        document, inspected.certificate, tuple(to_field_asset_profile(item) for item in inspected.fields),
        eligibility_entry=route.eligibility_entry,
    )
    if not translated.translated or translated.plan is None:
        return PanelRunResult("rejected", project_findings(translated.errors, labels))
    namespace = staging_namespace_for_document(document.document_id)
    settings = RuntimeGenerationSettings(
        seed=draft.resolved_seed, output_filename_prefix=f"conditioning-layers-panel/{execution_id}",
        execution_request_id=execution_id,
    )
    # Exact registered-host selection; an unbound host is rejected, never rebound.
    binding, classes = select_blend_realization(
        translated.plan.eligibility_entry, application.compatibility) or (None, None)
    generated = generate_prediction_mixing_blend_workflow(
        translated.plan, application.compatibility.inventory, settings,
        FieldStagingMap({layer.layer_id: f"{namespace}/{layer.layer_id}.png" for layer in document.active_layers}),
        document_id=document.document_id,
        disabled_layer_ids=tuple(layer.layer_id for layer in document.layers if not layer.visible),
        binding=binding, permitted_class_authority=classes,
    )
    if not generated.generated or generated.artifact is None:
        return PanelRunResult("rejected", project_findings(generated.errors, labels))
    publish_state("preparing")
    try:
        availability = capture_blend_component_availability(blend_component_identity())
    except (ImportError, ValueError, OSError):
        return _failure("panel.blend.component_unavailable", "The qualified Blend component is unavailable in this host process.")
    prepared = prepare_blend_submission_bundle(
        generated.artifact, generated.artifact.provenance_inputs, application.compatibility.inventory,
        application._host.host_configuration, inspected.fields, materialized.asset_root,
        application.compatibility.node_snapshot, component_availability=availability,
    )
    if not prepared.ready or prepared.bundle is None:
        return PanelRunResult("rejected", project_findings(prepared.errors, labels))
    # multi_layer retains its exact historical meaning: the No Overlap client.
    return PreparedPanelExecution(prepared.bundle, labels, translated.warnings, False, BLEND_CONTRACT_IDENTIFIER)


def execute_blend(application, prepared, execution_id, publish_state):
    client = application._execution_client
    if client is execute_submission_bundle:
        client = execute_blend_submission_bundle
    publish_state("executing")
    result = client(
        prepared.bundle, application._host.server_configuration, application._host.execution_policy,
        trusted_snapshot=application.compatibility.node_snapshot,
    )
    return accept_blend_result(prepared, result, execution_id)


def accept_blend_result(prepared, result, execution_id):
    """Completion is insufficient: publish only one fully reconciled output.

    No history search, separator repair, first-output choice or qualification
    recovery is available here. The unchanged client owns normal association.
    """
    failed = _failure("panel.blend.output_association", "Blend completed without one verified execution-owned image.", state="failed")
    if (not validate_execution_id(execution_id) or type(result) is not BlendExecutionResult
            or result.result_version != EXECUTION_RESULT_VERSION or result.completed is not True
            or result.submitted is not True or result.terminal_state is not ExecutionState.COMPLETED
            or result.errors or type(result.outputs) is not tuple or len(result.outputs) != 1
            or type(result.prompt_id) is not str or not result.prompt_id.strip()):
        return failed
    bundle, provenance, output = prepared.bundle, result.provenance, result.outputs[0]
    if type(output) is not AssociatedOutput or validate_blend_execution_provenance(provenance, bundle):
        return failed
    try:
        expected = build_blend_execution_provenance(
            bundle=bundle, server_identity=result.server_identity, prompt_id=result.prompt_id,
            terminal_state=result.terminal_state, outputs=result.outputs,
            errors=result.errors, warnings=result.warnings,
        )
    except (AttributeError, TypeError, ValueError):
        return failed
    if provenance.provenance_fingerprint != expected.provenance_fingerprint:
        return failed
    prefix = f"conditioning-layers-panel/{execution_id}"
    if (
        prepared.route_identifier != BLEND_CONTRACT_IDENTIFIER
        or tuple(node_id for node_id, node in bundle.graph_mapping.items() if node["class_type"] == "SaveImage") != ("20",)
        or bundle.expected_output_prefix != prefix
        or output.node_id != "20" or output.output_type != "images" or output.storage_type != "output"
        or output.subfolder != "conditioning-layers-panel" or type(output.filename) is not str
        or len(output.filename) > 255 or re.fullmatch(re.escape(execution_id) + r"_[0-9]+_\.png", output.filename) is None
        or output.relative_locator != f"conditioning-layers-panel/{output.filename}"
        or not _safe_relative_locator(output.relative_locator, bundle.host_snapshot.output_directory)
        or result.bundle_fingerprint != bundle.bundle_fingerprint or result.graph_fingerprint != bundle.graph_fingerprint
        or provenance.execution_request_id != execution_id or provenance.prompt_id != result.prompt_id
        or provenance.terminal_state is not result.terminal_state or provenance.execution_error_codes
        or provenance.output_locators != (output.relative_locator,)
        or result.result_identity_fingerprint != fingerprint_blend_result_identity(provenance)
    ):
        return failed
    projected = PanelOutput(output.filename, output.subfolder, output.storage_type, "/view?" + urlencode({
        "filename": output.filename, "subfolder": output.subfolder, "type": output.storage_type,
    }))
    return PanelRunResult("completed", project_product_warnings(prepared.warnings, prepared.layer_labels), projected)
