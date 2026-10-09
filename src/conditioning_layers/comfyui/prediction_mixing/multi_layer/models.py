"""Direct graph successor records owned by ADR-0024."""

from collections.abc import Mapping
from dataclasses import dataclass

from conditioning_layers.adapters.prediction_mixing.multi_layer import TranslationPlanV3
from conditioning_layers.comfyui.prediction_mixing.models import (
    FieldStagingMap, RuntimeGenerationSettings, WorkflowLayerProvenance,
    _thaw_json,
)
from conditioning_layers.domain import ValidationFinding

from .canonical import freeze_json


GRAPH_FORMAT_IDENTIFIER = "comfyui.api.prompt"
GRAPH_FORMAT_VERSION = "prediction-mixing.prototype.v2"
GENERATOR_VERSION_IDENTIFIER = "conditioning-layers.comfyui-generator.v2"


@dataclass(frozen=True, slots=True)
class RealizationBinding:
    identifier: str
    contract_identifier: str
    contract_version: int
    eligibility_entry_identifier: str
    eligibility_entry_fingerprint: str
    exact_cardinality: int
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
    realization_semantics: tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True, slots=True)
class MultiLayerWorkflowProvenance:
    document_id: str
    contract_identifier: str
    contract_version: int
    translation_plan_identifier: str
    translation_plan_version: int
    translation_plan_fingerprint: str
    eligibility_entry_identifier: str
    eligibility_entry_fingerprint: str
    exact_admitted_cardinality: int
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


@dataclass(frozen=True, slots=True)
class MultiLayerGraphArtifact:
    graph_format_identifier: str
    graph_format_version: str
    adapter_identifier: str
    source_translation_plan_fingerprint: str
    canonical_graph: Mapping[str, object]
    graph_fingerprint: str
    required_host_components: tuple[str, ...]
    warnings: tuple[str, ...]
    provenance_inputs: MultiLayerWorkflowProvenance
    source_plan: TranslationPlanV3
    realization_binding: RealizationBinding
    settings: RuntimeGenerationSettings
    staging: FieldStagingMap

    def __post_init__(self) -> None:
        object.__setattr__(self, "canonical_graph", freeze_json(self.canonical_graph))

    def to_api_graph(self) -> dict[str, object]:
        return _thaw_json(self.canonical_graph)


@dataclass(frozen=True, slots=True)
class MultiLayerGraphResult:
    artifact: MultiLayerGraphArtifact | None
    errors: tuple[ValidationFinding, ...]
    warnings: tuple[ValidationFinding, ...] = ()
    information: tuple[ValidationFinding, ...] = ()

    @property
    def generated(self) -> bool:
        return self.artifact is not None and not self.errors
