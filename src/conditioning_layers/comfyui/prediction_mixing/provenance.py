"""Deterministic workflow-generation provenance construction."""

from __future__ import annotations

from conditioning_layers.adapters.prediction_mixing import (
    PredictionMixingTranslationPlan,
)

from .models import (
    GENERATOR_VERSION_IDENTIFIER,
    ComfyUIComponentInventory,
    FieldStagingMap,
    RuntimeGenerationSettings,
    WorkflowGenerationProvenance,
    WorkflowLayerProvenance,
)


def build_workflow_provenance(
    plan: PredictionMixingTranslationPlan,
    inventory: ComfyUIComponentInventory,
    settings: RuntimeGenerationSettings,
    staging: FieldStagingMap,
    graph_fingerprint: str,
    warning_codes: tuple[str, ...],
) -> WorkflowGenerationProvenance:
    """Build immutable inputs known before any host submission or execution."""

    translation_provenance = {
        item.layer_id: item for item in plan.provenance_inputs.layers
    }
    active_layers: list[WorkflowLayerProvenance] = []
    for condition in plan.active_regional_conditions:
        source = translation_provenance[condition.layer_id]
        active_layers.append(
            WorkflowLayerProvenance(
                layer_id=condition.layer_id,
                combined_prompt_sha256=source.combined_prompt_sha256,
                document_field_reference=condition.field_profile.relative_path,
                staged_field_filename=(
                    staging.filenames_by_layer_id[condition.layer_id]
                ),
                field_checksum=source.field_checksum,
                requested_strength=condition.requested_strength,
            )
        )
    return WorkflowGenerationProvenance(
        document_id=plan.document_id,
        translation_plan_fingerprint=plan.fingerprint,
        graph_fingerprint=graph_fingerprint,
        adapter_identifier=plan.adapter_identifier,
        capability_identifier=plan.capability_identifier,
        execution_profile_identifier=plan.execution_profile.profile_identifier,
        component_inventory_identifier=inventory.inventory_identifier,
        model_filename=inventory.model_filename,
        model_sha256=inventory.model_sha256,
        text_encoder_filename=inventory.text_encoder_filename,
        text_encoder_sha256=inventory.text_encoder_sha256,
        vae_filename=inventory.vae_filename,
        vae_sha256=inventory.vae_sha256,
        active_layers=tuple(active_layers),
        disabled_layer_ids=plan.excluded_disabled_layer_ids,
        seed=settings.seed,
        output_filename_prefix=settings.output_filename_prefix,
        execution_request_id=settings.execution_request_id,
        mandatory_warning_codes=warning_codes,
        generator_version_identifier=GENERATOR_VERSION_IDENTIFIER,
    )
