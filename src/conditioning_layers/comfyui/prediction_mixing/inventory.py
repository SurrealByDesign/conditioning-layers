"""Frozen ComfyUI 0.27.1 built-in contracts and canonical prototype inventory."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from conditioning_layers.adapters.prediction_mixing import NegativePromptPolicy

from .models import ComfyUIComponentInventory


COMFYUI_PROFILE_IDENTIFIER = "comfyui-0.27.1.prediction-mixing.v1"
NODE_CONTRACT_IDENTIFIER = "comfyui-core-0.27.1.prediction-mixing.v1"
CANONICAL_INVENTORY_IDENTIFIER = (
    "comfyui-0.27.1.krea2-turbo-bf16-1024.prediction-mixing.v1"
)


@dataclass(frozen=True, slots=True)
class NodeContract:
    """Required API inputs and usable outputs for one verified built-in class."""

    required_inputs: frozenset[str]
    link_inputs: frozenset[str]
    output_indices: frozenset[int]


NODE_CONTRACTS = MappingProxyType(
    {
        "UNETLoader": NodeContract(
            frozenset({"unet_name", "weight_dtype"}), frozenset(), frozenset({0})
        ),
        "CLIPLoader": NodeContract(
            frozenset({"clip_name", "type", "device"}),
            frozenset(),
            frozenset({0}),
        ),
        "CLIPTextEncode": NodeContract(
            frozenset({"text", "clip"}), frozenset({"clip"}), frozenset({0})
        ),
        "LoadImageMask": NodeContract(
            frozenset({"image", "channel"}), frozenset(), frozenset({0})
        ),
        "ConditioningSetMask": NodeContract(
            frozenset({"strength", "set_cond_area", "conditioning", "mask"}),
            frozenset({"conditioning", "mask"}),
            frozenset({0}),
        ),
        "ConditioningCombine": NodeContract(
            frozenset({"conditioning_1", "conditioning_2"}),
            frozenset({"conditioning_1", "conditioning_2"}),
            frozenset({0}),
        ),
        "EmptyLatentImage": NodeContract(
            frozenset({"width", "height", "batch_size"}),
            frozenset(),
            frozenset({0}),
        ),
        "KSampler": NodeContract(
            frozenset(
                {
                    "seed",
                    "steps",
                    "cfg",
                    "sampler_name",
                    "scheduler",
                    "denoise",
                    "model",
                    "positive",
                    "negative",
                    "latent_image",
                }
            ),
            frozenset({"model", "positive", "negative", "latent_image"}),
            frozenset({0}),
        ),
        "VAELoader": NodeContract(
            frozenset({"vae_name"}), frozenset(), frozenset({0})
        ),
        "VAEDecode": NodeContract(
            frozenset({"samples", "vae"}),
            frozenset({"samples", "vae"}),
            frozenset({0}),
        ),
        "SaveImage": NodeContract(
            frozenset({"filename_prefix", "images"}),
            frozenset({"images"}),
            frozenset(),
        ),
    }
)


CANONICAL_NODE_CLASS_NAMES = tuple(NODE_CONTRACTS)


CANONICAL_COMFYUI_INVENTORY = ComfyUIComponentInventory(
    inventory_identifier=CANONICAL_INVENTORY_IDENTIFIER,
    comfyui_profile_identifier=COMFYUI_PROFILE_IDENTIFIER,
    supported_execution_profile_identifier="krea2-turbo-bf16-1024.v1",
    expected_comfyui_version="0.27.1",
    expected_comfyui_revision="c2638ce6c00e3426c48d56a775bc46e9a8464094",
    node_contract_identifier=NODE_CONTRACT_IDENTIFIER,
    required_node_class_names=CANONICAL_NODE_CLASS_NAMES,
    model_filename="krea2_turbo_bf16.safetensors",
    model_sha256="78bbf8f4165eda19cea3cb06c78089221932a39e2eed8af9da741f942c47ffb3",
    model_size_bytes=26_283_332_608,
    model_weight_dtype="default",
    text_encoder_filename="qwen3vl_4b_fp8_scaled.safetensors",
    text_encoder_sha256=(
        "54bd5144df0bbc25dd6ccadfcb826b521445a1b06ae5a42570bdd2974ca87094"
    ),
    text_encoder_size_bytes=5_242_467_968,
    text_encoder_type="krea2",
    text_encoder_device="default",
    vae_filename="qwen_image_vae.safetensors",
    vae_sha256="a70580f0213e67967ee9c95f05bb400e8fb08307e017a924bf3441223e023d1f",
    vae_size_bytes=253_806_246,
    sampler_name="euler",
    scheduler_name="simple",
    steps=8,
    cfg=1.0,
    denoise=1.0,
    output_width=1024,
    output_height=1024,
    batch_size=1,
    negative_prompt_policy=NegativePromptPolicy.EMPTY,
    mask_channel="red",
    mask_area_policy="default",
    filename_prefix_policy="safe_relative_posix",
    evidence_references=(
        "research/experiments/EXP-0001-krea2-baseline/results.md",
        "research/experiments/EXP-0001-krea2-baseline/workflows/EXP-0001_krea2-turbo-bf16_baseline_api.json",
        "research/experiments/EXP-0003-krea2-prediction-mixing/mechanism-trace.md",
        "research/experiments/EXP-0003-krea2-prediction-mixing/workflows/EXP-0003_krea2-hard-complementary_api.json",
    ),
)


def node_id_layout(layer_ids: tuple[str, ...]) -> dict[str, str]:
    """Assign dense numeric IDs in fixed topology phases."""

    # Frozen v1 node layouts are structural artifacts for already-authorized
    # one/two-layer plans; capability evaluation decides product eligibility.
    if len(layer_ids) not in {1, 2}:
        raise ValueError("node ID layout requires exactly one or two layer IDs")
    layout = {"model": "1", "clip": "2"}
    next_id = 3
    for layer_id in layer_ids:
        layout[f"prompt:{layer_id}"] = str(next_id)
        next_id += 1
    layout["negative"] = str(next_id)
    next_id += 1
    for layer_id in layer_ids:
        layout[f"field:{layer_id}"] = str(next_id)
        next_id += 1
    for layer_id in layer_ids:
        layout[f"mask:{layer_id}"] = str(next_id)
        next_id += 1
    if len(layer_ids) == 2:
        layout["combine"] = str(next_id)
        next_id += 1
    for role in ("latent", "sampler", "vae", "decode", "save"):
        layout[role] = str(next_id)
        next_id += 1
    return layout
