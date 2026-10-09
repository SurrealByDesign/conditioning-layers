"""Immutable inputs and outputs for deterministic ComfyUI API graph generation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from conditioning_layers.adapters.prediction_mixing import NegativePromptPolicy
from conditioning_layers.domain import ValidationFinding


GRAPH_FORMAT_IDENTIFIER = "comfyui.api.prompt"
GRAPH_FORMAT_VERSION = "prediction-mixing.prototype.v1"
GENERATOR_VERSION_IDENTIFIER = "conditioning-layers.comfyui-generator.v1"


@dataclass(frozen=True, slots=True)
class ComfyUIComponentInventory:
    """Caller-declared host profile; no installed host is discovered here."""

    inventory_identifier: str
    comfyui_profile_identifier: str
    supported_execution_profile_identifier: str
    expected_comfyui_version: str
    expected_comfyui_revision: str
    node_contract_identifier: str
    required_node_class_names: tuple[str, ...]
    model_filename: str
    model_sha256: str | None
    model_size_bytes: int | None
    model_weight_dtype: str
    text_encoder_filename: str
    text_encoder_sha256: str | None
    text_encoder_size_bytes: int | None
    text_encoder_type: str
    text_encoder_device: str
    vae_filename: str
    vae_sha256: str | None
    vae_size_bytes: int | None
    sampler_name: str
    scheduler_name: str
    steps: int
    cfg: float
    denoise: float
    output_width: int
    output_height: int
    batch_size: int
    negative_prompt_policy: NegativePromptPolicy
    mask_channel: str
    mask_area_policy: str
    filename_prefix_policy: str
    evidence_references: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RuntimeGenerationSettings:
    """Per-request values not represented as neutral document intent."""

    seed: int
    output_filename_prefix: str
    execution_request_id: str | None = None


@dataclass(frozen=True, slots=True)
class FieldStagingMap:
    """Active layer IDs mapped to caller-staged ComfyUI input filenames."""

    filenames_by_layer_id: Mapping[str, str]

    def __post_init__(self) -> None:
        if isinstance(self.filenames_by_layer_id, Mapping):
            object.__setattr__(
                self,
                "filenames_by_layer_id",
                MappingProxyType(dict(self.filenames_by_layer_id)),
            )


@dataclass(frozen=True, slots=True)
class WorkflowLayerProvenance:
    """One active translated layer and its staged host input."""

    layer_id: str
    combined_prompt_sha256: str
    document_field_reference: str
    staged_field_filename: str
    field_checksum: str | None
    requested_strength: float


@dataclass(frozen=True, slots=True)
class WorkflowGenerationProvenance:
    """Deterministic pre-execution workflow provenance with no result data."""

    document_id: str
    translation_plan_fingerprint: str
    graph_fingerprint: str
    adapter_identifier: str
    capability_identifier: str
    execution_profile_identifier: str
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
class ComfyUIApiGraphArtifact:
    """Immutable prototype API graph plus host and provenance declarations."""

    graph_format_identifier: str
    graph_format_version: str
    adapter_identifier: str
    source_translation_plan_fingerprint: str
    canonical_graph: Mapping[str, object]
    graph_fingerprint: str
    required_host_components: tuple[str, ...]
    warnings: tuple[str, ...]
    provenance_inputs: WorkflowGenerationProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "canonical_graph", _freeze_json(self.canonical_graph))

    def to_api_graph(self) -> dict[str, object]:
        """Return an isolated JSON-compatible mapping for later submission."""

        return _thaw_json(self.canonical_graph)  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class WorkflowGenerationResult:
    """Normal structured success or failure without contacting ComfyUI."""

    artifact: ComfyUIApiGraphArtifact | None
    errors: tuple[ValidationFinding, ...]
    warnings: tuple[ValidationFinding, ...]
    information: tuple[ValidationFinding, ...]
    generated: bool


def _freeze_json(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value
