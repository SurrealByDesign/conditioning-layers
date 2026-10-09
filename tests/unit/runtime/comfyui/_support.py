from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from pathlib import Path

from conditioning_layers.adapters.prediction_mixing import (
    FieldAssetProfile,
    FieldChannelProfile,
    FieldValueKind,
    OverlapAssessment,
    translate_prediction_mixing,
)
from conditioning_layers.assets import (
    DimensionValidationResult,
    FieldInspectionResult,
    InspectedChannelProfile,
    InspectedFieldProfile,
    InspectedValueKind,
)
from conditioning_layers.capabilities import PREDICTION_MIXING_CAPABILITY
from conditioning_layers.comfyui.prediction_mixing import (
    CANONICAL_COMFYUI_INVENTORY,
    NODE_CONTRACTS,
    FieldStagingMap,
    RuntimeGenerationSettings,
    SemanticEvidenceRecord,
    create_host_node_contract_snapshot,
    create_node_contract_record,
    generate_prediction_mixing_workflow,
)
from conditioning_layers.domain import (
    CURRENT_PROTOTYPE_VERSION,
    ConditioningDocument,
    InfluenceFieldAssetReference,
    PromptLayer,
)
from conditioning_layers.runtime.comfyui import (
    ComfyUIHostConfiguration,
    HostNodeContractRecord,
    HostNodeContractSnapshot,
    StagingCleanupPolicy,
)


COMPONENT_BYTES = {
    "model": b"test-model-component",
    "text_encoder": b"test-text-encoder-component",
    "vae": b"test-vae-component",
}
FIELD_BYTES = {"a": b"certified-field-a", "b": b"certified-field-b"}


@dataclass(frozen=True)
class RuntimeCase:
    inventory: object
    translation_plan: object
    artifact: object
    provenance: object
    inspections: tuple[FieldInspectionResult, ...]
    asset_root: Path
    configuration: ComfyUIHostConfiguration
    node_snapshot: HostNodeContractSnapshot


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_case(
    root: Path,
    canonical_inventory=CANONICAL_COMFYUI_INVENTORY,
    *,
    layer_ids: tuple[str, ...] = ("a", "b"),
) -> RuntimeCase:
    if layer_ids not in {("a",), ("a", "b")}:
        raise ValueError("historical runtime cases require ('a',) or ('a', 'b')")
    asset_root = root / "document.conditioning.assets"
    (asset_root / "fields").mkdir(parents=True)
    for layer_id in layer_ids:
        data = FIELD_BYTES[layer_id]
        (asset_root / "fields" / f"{layer_id}.png").write_bytes(data)

    inventory = replace(
        canonical_inventory,
        model_sha256=sha256(COMPONENT_BYTES["model"]),
        model_size_bytes=len(COMPONENT_BYTES["model"]),
        text_encoder_sha256=sha256(COMPONENT_BYTES["text_encoder"]),
        text_encoder_size_bytes=len(COMPONENT_BYTES["text_encoder"]),
        vae_sha256=sha256(COMPONENT_BYTES["vae"]),
        vae_size_bytes=len(COMPONENT_BYTES["vae"]),
    )
    layers = tuple(
        PromptLayer(
            layer_id=layer_id,
            name=f"Layer {layer_id}",
            prompt_text=f"Regional prompt {layer_id}",
            visible=True,
            strength=1.0,
            influence_field=InfluenceFieldAssetReference(
                relative_path=f"fields/{layer_id}.png",
                checksum=sha256(FIELD_BYTES[layer_id]),
            ),
        )
        for layer_id in layer_ids
    )
    document = ConditioningDocument(
        version=CURRENT_PROTOTYPE_VERSION,
        document_id="document-1",
        base_prompt="A coherent studio scene",
        layers=layers,
        selected_adapter_id=PREDICTION_MIXING_CAPABILITY.adapter_identifier,
        adapter_settings={},
    )
    profiles = tuple(
        FieldAssetProfile(
            layer_id=layer_id,
            relative_path=f"fields/{layer_id}.png",
            checksum=sha256(FIELD_BYTES[layer_id]),
            width=128,
            height=128,
            channel_count=1,
            channel_profile=FieldChannelProfile.GRAYSCALE_8,
            minimum_normalized_value=0.0,
            maximum_normalized_value=1.0,
            finite_values=True,
            value_kind=FieldValueKind.BINARY,
        )
        for layer_id in layer_ids
    )
    translated = translate_prediction_mixing(
        document,
        profiles,
        overlap_assessment=(
            OverlapAssessment.NO_OVERLAP if len(layer_ids) == 2 else None
        ),
    )
    assert translated.plan is not None
    generated = generate_prediction_mixing_workflow(
        translated.plan,
        canonical_inventory,
        RuntimeGenerationSettings(
            seed=18472639,
            output_filename_prefix="conditioning-layers/document-1/request-1",
            execution_request_id="request-1",
        ),
        FieldStagingMap(
            {
                layer_id: f"conditioning-layers/document-1/{layer_id}.png"
                for layer_id in layer_ids
            }
        ),
    )
    assert generated.artifact is not None
    canonical_provenance = generated.artifact.provenance_inputs
    provenance = replace(
        canonical_provenance,
        model_sha256=inventory.model_sha256,
        text_encoder_sha256=inventory.text_encoder_sha256,
        vae_sha256=inventory.vae_sha256,
    )
    artifact = replace(generated.artifact, provenance_inputs=provenance)

    inspections = tuple(
        make_inspection(layer_id, FIELD_BYTES[layer_id])
        for layer_id in layer_ids
    )
    configuration = make_host_configuration(root, inventory)
    snapshot = make_node_snapshot(artifact.required_host_components, inventory)
    return RuntimeCase(
        inventory=inventory,
        translation_plan=translated.plan,
        artifact=artifact,
        provenance=provenance,
        inspections=inspections,
        asset_root=asset_root,
        configuration=configuration,
        node_snapshot=snapshot,
    )


def make_inspection(layer_id: str, data: bytes) -> FieldInspectionResult:
    checksum = sha256(data)
    profile = InspectedFieldProfile(
        layer_id=layer_id,
        relative_path=f"fields/{layer_id}.png",
        checksum=checksum,
        width=128,
        height=128,
        channel_count=1,
        channel_profile=InspectedChannelProfile.GRAYSCALE_8,
        minimum_normalized_value=0.0,
        maximum_normalized_value=1.0,
        finite_values=True,
        value_kind=InspectedValueKind.BINARY,
        distinct_value_count=2,
        zero_value_count=1,
        full_value_count=1,
        nonzero_value_count=1,
    )
    dimensions = DimensionValidationResult(
        certified=True,
        matches=True,
        expected_width=128,
        expected_height=128,
        observed_width=128,
        observed_height=128,
        errors=(),
        warnings=(),
        source_reference=f"fields/{layer_id}.png",
        checksum=checksum,
    )
    return FieldInspectionResult(
        successful=True,
        certified=True,
        profile=profile,
        dimension_validation=dimensions,
        errors=(),
        warnings=(),
        information=(),
        source_reference=f"fields/{layer_id}.png",
        checksum=checksum,
    )


def make_host_configuration(root: Path, inventory) -> ComfyUIHostConfiguration:
    checkout = root / "ComfyUI"
    data = root / "data"
    model_root = data / "models"
    directories = {
        "diffusion_models": (model_root / "diffusion_models",),
        "text_encoders": (model_root / "text_encoders",),
        "vae": (model_root / "vae",),
    }
    for path in (
        checkout,
        data / "input",
        data / "output",
        data / "user",
        *[item for paths in directories.values() for item in paths],
    ):
        path.mkdir(parents=True, exist_ok=True)
    (checkout / ".git").mkdir()
    (checkout / ".git" / "HEAD").write_text(
        inventory.expected_comfyui_revision, encoding="utf-8"
    )
    (checkout / "comfyui_version.py").write_text(
        f'__version__ = "{inventory.expected_comfyui_version}"\n',
        encoding="utf-8",
    )
    (directories["diffusion_models"][0] / inventory.model_filename).write_bytes(
        COMPONENT_BYTES["model"]
    )
    (directories["text_encoders"][0] / inventory.text_encoder_filename).write_bytes(
        COMPONENT_BYTES["text_encoder"]
    )
    (directories["vae"][0] / inventory.vae_filename).write_bytes(
        COMPONENT_BYTES["vae"]
    )
    return ComfyUIHostConfiguration(
        comfyui_root=checkout,
        input_directory=data / "input",
        output_directory=data / "output",
        user_directory=data / "user",
        model_root=model_root,
        model_directories=directories,
        git_checkout_path=checkout,
        supported_profile_identifier=inventory.comfyui_profile_identifier,
        launch_profile_identifier="test-launch",
        staging_cleanup_policy=StagingCleanupPolicy.CALLER_MANAGED,
        checkout_trusted_root=root,
        data_trusted_root=data,
        model_trusted_root=model_root,
    )


def make_node_snapshot(required_classes, inventory) -> HostNodeContractSnapshot:
    source_hash = "a" * 64
    contracts = {
        class_name: create_node_contract_record(
            class_name=class_name,
            required_inputs=tuple(sorted(NODE_CONTRACTS[class_name].required_inputs)),
            output_indices=tuple(sorted(NODE_CONTRACTS[class_name].output_indices)),
            host_required_inputs=tuple(sorted(NODE_CONTRACTS[class_name].required_inputs)),
            host_optional_inputs=(),
            input_evidence=(),
            return_types=("TEST",),
            function_name="test",
            source_file="tests/fixtures/nodes.py",
            source_symbol=class_name,
            source_file_sha256=source_hash,
            source_symbol_fingerprint="b" * 64,
        )
        for class_name in required_classes
    }
    semantic_evidence = tuple(
        SemanticEvidenceRecord(
            evidence_identifier=identifier,
            source_file="tests/fixtures/nodes.py",
            source_symbols=("test",),
            source_file_sha256=source_hash,
            symbol_fingerprints=("b" * 64,),
            conclusion="confirmed",
            notes="Test-only static evidence.",
        )
        for identifier in (
            "prediction_mixing.conditioning_set_mask",
            "prediction_mixing.conditioning_combine",
            "prediction_mixing.regional_accumulation",
            "prediction_mixing.cfg1_empty_negative",
        )
    )
    return create_host_node_contract_snapshot(
        snapshot_identifier="test-node-contract-snapshot",
        profile_identifier=inventory.comfyui_profile_identifier,
        comfyui_version=inventory.expected_comfyui_version,
        comfyui_revision=inventory.expected_comfyui_revision,
        contracts=contracts,
        source_reference="tests/static-node-contract-manifest",
        semantic_evidence=semantic_evidence,
        source_file_hashes={"tests/fixtures/nodes.py": source_hash},
    )


def codes(findings) -> set[str]:
    return {finding.code for finding in findings}
