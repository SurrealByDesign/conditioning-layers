"""ADR-0028 generalized Blend graph successor, bindings and permitted classes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from conditioning_layers.adapters.prediction_mixing.blend import TranslationPlanV4
from conditioning_layers.comfyui.prediction_mixing.models import (
    FieldStagingMap, RuntimeGenerationSettings, WorkflowLayerProvenance,
    _thaw_json,
)
from conditioning_layers.domain import ValidationFinding

from conditioning_layers.comfyui.prediction_mixing.multi_layer.canonical import freeze_json
from conditioning_layers.comfyui.prediction_mixing.generalized_blend_component import GeneralizedBlendComponentIdentity


GRAPH_FORMAT_IDENTIFIER = "comfyui.api.prompt"
GRAPH_FORMAT_VERSION = "prediction-mixing.prototype.v4"
GENERATOR_VERSION_IDENTIFIER = "conditioning-layers.comfyui-generator.v4"
OFFLINE_FIXTURE_AVAILABILITY_SCOPE = "offline-fixture-construction"


@dataclass(frozen=True, slots=True)
class GeneralizedBlendRealizationBinding:
    identifier: str
    contract_identifier: str
    contract_version: int
    eligibility_entry_identifier: str
    eligibility_entry_fingerprint: str
    exact_cardinality: int
    expected_count: int
    execution_profile_identifier: str
    execution_profile_fingerprint: str
    topology_policy_identifier: str
    topology_policy_fingerprint: str
    graph_identifier: str
    graph_version: str
    generator_identifier: str
    inventory_identifier: str
    inventory_fingerprint: str
    snapshot_identifier: str
    snapshot_fingerprint: str
    comfyui_profile_identifier: str
    comfyui_revision: str
    node_allocation: str
    host_link_allocation: str
    algorithm_identifier: str
    project_component_identity: GeneralizedBlendComponentIdentity
    permitted_class_authority_identifier: str
    permitted_class_authority_fingerprint: str
    component_availability_scope: str
    realization_semantics: tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True, slots=True)
class GeneralizedBlendGraphPermittedClassAuthority:
    identifier: str
    graph_identifier: str
    graph_version: str
    retained_inventory_identifier: str
    retained_inventory_fingerprint: str
    required_builtin_classes: tuple[str, ...]
    project_component_class: str
    project_component_contract_fingerprint: str
    project_component_implementation_fingerprint: str
    fingerprint: str


@dataclass(frozen=True, slots=True)
class GeneralizedBlendWorkflowProvenance:
    document_id: str
    contract_identifier: str
    contract_version: int
    translation_plan_identifier: str
    translation_plan_version: int
    translation_plan_fingerprint: str
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
    graph_fingerprint: str
    adapter_identifier: str
    component_inventory_identifier: str
    model_filename: str
    model_sha256: str | None
    text_encoder_filename: str
    text_encoder_sha256: str | None
    vae_filename: str
    vae_sha256: str | None
    active_layers: tuple[WorkflowLayerProvenance, ...]
    disabled_layer_ids: tuple[str, ...]
    seed: int
    output_filename_prefix: str
    execution_request_id: str | None
    mandatory_warning_codes: tuple[str, ...]
    generator_version_identifier: str
    composition_policy_identifier: str
    composition_policy_version: int
    composition_policy_fingerprint: str
    project_component_identifier: str
    project_component_contract_identifier: str
    project_component_implementation_fingerprint: str
    permitted_class_authority_identifier: str
    permitted_class_authority_fingerprint: str


@dataclass(frozen=True, slots=True)
class GeneralizedBlendGraphArtifact:
    graph_format_identifier: str
    graph_format_version: str
    adapter_identifier: str
    source_translation_plan_fingerprint: str
    canonical_graph: Mapping[str, object]
    graph_fingerprint: str
    required_host_components: tuple[str, ...]
    warnings: tuple[str, ...]
    provenance_inputs: GeneralizedBlendWorkflowProvenance
    source_plan: TranslationPlanV4
    realization_binding: GeneralizedBlendRealizationBinding
    permitted_class_authority: GeneralizedBlendGraphPermittedClassAuthority
    settings: RuntimeGenerationSettings
    staging: FieldStagingMap

    def __post_init__(self) -> None:
        object.__setattr__(self, "canonical_graph", freeze_json(self.canonical_graph))

    def to_api_graph(self) -> dict[str, object]:
        return _thaw_json(self.canonical_graph)


@dataclass(frozen=True, slots=True)
class GeneralizedBlendGraphResult:
    artifact: GeneralizedBlendGraphArtifact | None
    errors: tuple[ValidationFinding, ...]
    warnings: tuple[ValidationFinding, ...] = ()
    information: tuple[ValidationFinding, ...] = ()

    @property
    def generated(self) -> bool:
        return self.artifact is not None and not self.errors
