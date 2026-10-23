"""Deterministic API-format graphs and graph semantics for the layer workflow.

`build_layer_node_workflow` writes the visible Phase 1 workflow used by the
acceptance fixtures: per layer one CLIP Text Encode, one Load Image (as Mask),
one Conditioning Layer and one Add Conditioning Layer; then one Compose node
and an ordinary KSampler, decode and save. `_meta.title` values are UI-only
labels. Nothing is staged, submitted, registered or admitted here.

`layer_workflow_semantics` reduces such a graph to what prediction mixing
uses: ordered layer sources, fields, Strength, mode, the enabled-layer count
and the sampler inputs. Node ids, titles and output naming are ignored, and
fields may be compared by content digest instead of staged filename, so
another graph family can be checked for the same meaning exactly.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math

from conditioning_layers.adapters.prediction_mixing import NegativePromptPolicy
from conditioning_layers.comfyui.prediction_mixing.inventory import NODE_CONTRACTS
from conditioning_layers.comfyui.prediction_mixing.models import (
    ComfyUIComponentInventory, RuntimeGenerationSettings,
)
from conditioning_layers.comfyui.prediction_mixing.multi_layer.canonical import fingerprint
from conditioning_layers.comfyui.prediction_mixing.validation import _safe_relative_name, _validate_settings

from .models import LayerMode, validate_blend_group
from .nodes import LAYER_NODE_CLASS_NAMES, initialize_layer_node_registration


LAYER_NODE, ADD_LAYER_NODE, COMPOSE_NODE, GROUPED_COMPOSE_NODE = LAYER_NODE_CLASS_NAMES
SAMPLER_SETTINGS = ("seed", "steps", "cfg", "sampler_name", "scheduler", "denoise")
_WIDGET_TYPES = frozenset({"INT", "FLOAT", "STRING", "BOOLEAN"})


@dataclass(frozen=True, slots=True)
class LayerWorkflowSpec:
    """One visible layer branch in a generated workflow."""

    prompt_text: str
    field_image: str
    strength: float = 1.0
    mode: LayerMode = LayerMode.BLENDED
    enabled: bool = True
    title: str = ""
    blend_group: str = ""


def _check_specs(layers):
    if type(layers) is not tuple or not layers or any(type(item) is not LayerWorkflowSpec for item in layers):
        raise ValueError("A layer workflow requires one or more LayerWorkflowSpec values")
    for ordinal, layer in enumerate(layers, start=1):
        strength = layer.strength
        if (type(layer.prompt_text) is not str or type(layer.title) is not str
                or not _safe_relative_name(layer.field_image, require_png=True)
                or type(strength) not in (int, float) or not math.isfinite(strength) or not 0 <= strength <= 1
                or type(layer.mode) is not LayerMode or type(layer.enabled) is not bool):
            raise ValueError(f"Layer {ordinal} is not a valid workflow layer")
        validate_blend_group(layer.blend_group)


def build_layer_node_workflow(layers, inventory, settings, *, grouped=False) -> dict[str, dict[str, object]]:
    """Return the dense, deterministic API graph: 4N + 9 nodes, 5N + 8 links."""
    _check_specs(layers)
    if type(grouped) is not bool:
        raise ValueError("grouped must be a boolean")
    if not grouped and any(layer.blend_group for layer in layers):
        raise ValueError("Explicit Blend Group assignments require Compose Blend Groups")
    if type(inventory) is not ComfyUIComponentInventory or inventory.negative_prompt_policy is not NegativePromptPolicy.EMPTY:
        raise ValueError("An inventory with the empty negative prompt policy is required")
    if type(settings) is not RuntimeGenerationSettings or _validate_settings(settings):
        raise ValueError("Valid runtime generation settings are required")
    n = len(layers)
    graph: dict[str, dict[str, object]] = {}

    def node(node_id, class_type, title, **inputs):
        graph[str(node_id)] = {"inputs": inputs, "class_type": class_type, "_meta": {"title": title}}

    def link(node_id):
        return [str(node_id), 0]

    labels = tuple(f"Layer {ordinal}" + (f": {layer.title}" if layer.title else "")
                   for ordinal, layer in enumerate(layers, start=1))
    node(1, "UNETLoader", "Load Diffusion Model",
         unet_name=inventory.model_filename, weight_dtype=inventory.model_weight_dtype)
    node(2, "CLIPLoader", "Load CLIP", clip_name=inventory.text_encoder_filename,
         type=inventory.text_encoder_type, device=inventory.text_encoder_device)
    for i, layer in enumerate(layers):
        node(3 + i, "CLIPTextEncode", f"{labels[i]} (prompt)", text=layer.prompt_text, clip=link(2))
    node(n + 3, "CLIPTextEncode", "Negative prompt (empty)", text="", clip=link(2))
    for i, layer in enumerate(layers):
        node(n + 4 + i, "LoadImageMask", f"{labels[i]} (field)",
             image=layer.field_image, channel=inventory.mask_channel)
    for i, layer in enumerate(layers):
        node(2 * n + 4 + i, LAYER_NODE, labels[i], conditioning=link(3 + i), mask=link(n + 4 + i),
             strength=0.0 if layer.strength == 0 else float(layer.strength),
             mode=layer.mode.value, enabled=layer.enabled,
             **({"blend_group": layer.blend_group} if layer.blend_group else {}))
    for i in range(n):
        stack = {"layers": link(3 * n + 3 + i)} if i else {}
        node(3 * n + 4 + i, ADD_LAYER_NODE, f"Add {labels[i]}", layer=link(2 * n + 4 + i), **stack)
    node(4 * n + 4, GROUPED_COMPOSE_NODE if grouped else COMPOSE_NODE,
         "Compose Blend Groups" if grouped else "Compose Conditioning Layers", layers=link(4 * n + 3))
    node(4 * n + 5, "EmptyLatentImage", "Empty Latent Image", width=inventory.output_width,
         height=inventory.output_height, batch_size=inventory.batch_size)
    node(4 * n + 6, "KSampler", "KSampler", seed=settings.seed, steps=inventory.steps, cfg=inventory.cfg,
         sampler_name=inventory.sampler_name, scheduler=inventory.scheduler_name, denoise=inventory.denoise,
         model=link(1), positive=link(4 * n + 4), negative=link(n + 3), latent_image=link(4 * n + 5))
    node(4 * n + 7, "VAELoader", "Load VAE", vae_name=inventory.vae_filename)
    node(4 * n + 8, "VAEDecode", "VAE Decode", samples=link(4 * n + 6), vae=link(4 * n + 7))
    node(4 * n + 9, "SaveImage", "Save Image", filename_prefix=settings.output_filename_prefix,
         images=link(4 * n + 8))
    validate_layer_node_workflow(graph)
    return graph


def _is_link(value):
    return type(value) is list and len(value) == 2 and type(value[0]) is str and type(value[1]) is int


def validate_layer_node_workflow(graph) -> None:
    """Check classes, input names and links against built-in and layer-node contracts."""
    layer_nodes, _ = initialize_layer_node_registration()
    if not isinstance(graph, Mapping) or not graph:
        raise ValueError("A non-empty API graph is required")
    for node_id, node in graph.items():
        if (type(node_id) is not str or not isinstance(node, Mapping)
                or set(node) - {"inputs", "class_type", "_meta"} or not isinstance(node.get("inputs"), Mapping)):
            raise ValueError(f"Node {node_id!r} is malformed")
        class_type, inputs = node.get("class_type"), node["inputs"]
        links = {name for name, value in inputs.items() if _is_link(value)}
        for name in links:
            if inputs[name][0] not in graph or inputs[name][1] != 0:
                raise ValueError(f"Node {node_id} input {name} links to a missing output")
        if class_type in NODE_CONTRACTS:
            contract = NODE_CONTRACTS[class_type]
            if set(inputs) != contract.required_inputs or links != contract.link_inputs:
                raise ValueError(f"Node {node_id} does not match the {class_type} contract")
        elif class_type in layer_nodes:
            declared = layer_nodes[class_type].INPUT_TYPES()
            required, optional = set(declared["required"]), set(declared.get("optional", {}))
            # Typed sockets are links; widget and combo values are literals.
            linked = {name for name, spec in {**declared["required"], **declared.get("optional", {})}.items()
                      if type(spec[0]) is str and spec[0] not in _WIDGET_TYPES}
            if not required <= set(inputs) <= required | optional or links != linked & set(inputs):
                raise ValueError(f"Node {node_id} does not match the {class_type} contract")
        else:
            raise ValueError(f"Node {node_id} uses an unexpected class {class_type!r}")


def describe_graph_input(graph, value, field_digests=None, _path=()):
    """Return a literal unchanged, or the canonical description of the linked upstream node."""
    if not _is_link(value):
        if isinstance(value, (list, tuple, Mapping)):
            raise ValueError("Only literal values or [node_id, output] links are supported")
        return value
    node_id, output = value
    node = graph.get(node_id)
    if node_id in _path or not isinstance(node, Mapping):
        raise ValueError(f"Link to {node_id!r} is missing or cyclic")
    inputs = {}
    for name, item in node["inputs"].items():
        if node["class_type"] == "LoadImageMask" and name == "image" and field_digests is not None:
            if item not in field_digests:
                raise ValueError(f"Field {item!r} has no content digest")
            inputs["image_sha256"] = field_digests[item]
        else:
            inputs[name] = describe_graph_input(graph, item, field_digests, _path + (node_id,))
    return {"class_type": node["class_type"], "output": output, "inputs": inputs}


def _linked(graph, value, class_type):
    if not _is_link(value) or graph.get(value[0], {}).get("class_type") != class_type:
        raise ValueError(f"Expected a link to {class_type}")
    return value[0]


def sampler_semantics(graph, sampler_id, layers, field_digests=None) -> dict[str, object]:
    """Shared record for one sampler: ordered layers plus everything else that shapes its prediction."""
    sampler = graph[sampler_id]["inputs"]
    decoders = [node_id for node_id, node in graph.items()
                if node["class_type"] == "VAEDecode" and node["inputs"].get("samples") == [sampler_id, 0]]
    if len(decoders) != 1:
        raise ValueError("Exactly one VAE Decode must consume the sampler")
    return {
        "layers": layers,
        "expected_count": sum(layer["enabled"] for layer in layers),
        "sampler": {name: sampler[name] for name in SAMPLER_SETTINGS},
        "model": describe_graph_input(graph, sampler["model"], field_digests),
        "negative": describe_graph_input(graph, sampler["negative"], field_digests),
        "latent_image": describe_graph_input(graph, sampler["latent_image"], field_digests),
        "vae": describe_graph_input(graph, graph[decoders[0]]["inputs"]["vae"], field_digests),
    }


def layer_workflow_semantics(graph, field_digests=None) -> dict[str, object]:
    """Extract the ordered layer composition that feeds the single KSampler's positive input."""
    try:
        return _layer_workflow_semantics(graph, field_digests)
    except (KeyError, TypeError, AttributeError, IndexError):
        raise ValueError("The graph is not a well-formed layer workflow") from None


def _layer_workflow_semantics(graph, field_digests):
    samplers = [node_id for node_id, node in graph.items() if node.get("class_type") == "KSampler"]
    if len(samplers) != 1:
        raise ValueError("Exactly one KSampler is required")
    positive = graph[samplers[0]]["inputs"]["positive"]
    compose_type = graph.get(positive[0], {}).get("class_type") if _is_link(positive) else None
    if compose_type not in (COMPOSE_NODE, GROUPED_COMPOSE_NODE):
        raise ValueError("Expected a link to Compose Conditioning Layers or Compose Blend Groups")
    compose = _linked(graph, positive, compose_type)
    grouped = compose_type == GROUPED_COMPOSE_NODE
    chain = [_linked(graph, graph[compose]["inputs"]["layers"], ADD_LAYER_NODE)]
    while "layers" in graph[chain[-1]]["inputs"]:
        chain.append(_linked(graph, graph[chain[-1]]["inputs"]["layers"], ADD_LAYER_NODE))
        if chain[-1] in chain[:-1]:
            raise ValueError("The layer stack chain is cyclic")
    layers, authored = [], []
    for add in reversed(chain):
        layer = _linked(graph, graph[add]["inputs"]["layer"], LAYER_NODE)
        if layer in authored:
            raise ValueError(f"Layer node {layer} is added to the stack twice")
        authored.append(layer)
        inputs = graph[layer]["inputs"]
        group = validate_blend_group(inputs.get("blend_group", ""))
        if group and not grouped:
            raise ValueError("Explicit Blend Group assignments require Compose Blend Groups")
        strength, enabled = inputs["strength"], inputs["enabled"]
        if (type(strength) is not float or not math.isfinite(strength) or not 0 <= strength <= 1
                or type(enabled) is not bool):
            raise ValueError(f"Layer node {layer} has an invalid Strength or enabled value")
        layers.append({
            "conditioning": describe_graph_input(graph, inputs["conditioning"], field_digests),
            "field": describe_graph_input(graph, inputs["mask"], field_digests),
            "strength": strength,
            "mode": LayerMode(inputs["mode"]).value,
            "enabled": enabled,
            **({"blend_group": group} if grouped else {}),
        })
    semantics = sampler_semantics(graph, samplers[0], layers, field_digests)
    if grouped:
        semantics["composition"] = "strongest-member-groups.v1"
    return semantics


def fingerprint_semantics(semantics) -> str:
    return fingerprint(semantics)
