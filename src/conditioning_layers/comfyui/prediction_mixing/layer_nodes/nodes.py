"""Ordinary ComfyUI (V1) nodes for the Node System Phase 1 layer workflow.

    prompt / CLIP / LoRA chain -> CONDITIONING -+
    field source ------------> MASK ----------+-> Conditioning Layer
    Conditioning Layer -> Add Conditioning Layer -> ... -> Compose Conditioning Layers -> KSampler positive

Importing this module never imports Torch or ComfyUI; the tensor runtime is
loaded only when a node executes. Node availability is not product admission:
nothing here reads or changes product routing, admission, bindings or host
selection. Compose applies the retained preparation contract (unresized
binary32 masks decoded from 8-bit fields, plain prompt metadata, prepared
masks with mask_strength 1.0) and the retained exact normalization to any
positive number of layers.
"""

from __future__ import annotations

from conditioning_layers.comfyui.prediction_mixing.blend_preparation import recover_sample_code

from .composition import compose_field_codes
from .models import LAYER_STACK_TYPE, LAYER_TYPE, LayerDescriptor, LayerMode, LayerStack


CATEGORY = "conditioning/conditioning_layers"
# The retained preparation contract shared by the exact-3 and N-generic Blend
# components; tests pin these values to both. They are stated here so layer-node
# availability never depends on the Blend component module importing.
FIELD_SHAPE = (1, 128, 128)
PREPARED_MASK_STRENGTH = 1.0
PREPARED_SET_AREA_TO_BOUNDS = False
# The layer owns its field; upstream conditioning may carry only plain prompt metadata.
LAYER_OWNED_METADATA = ("mask", "mask_strength", "set_area_to_bounds")
UPSTREAM_METADATA = ("pooled_output", "attention_mask")


def _runtime_torch():
    import torch

    return torch


def _prepared_inputs(layer, torch):
    """Validate one enabled layer's tensors; return prompt, metadata and field codes."""
    name = f"Layer node {layer.layer_id}"
    conditioning = layer.conditioning
    if type(conditioning) not in (list, tuple) or len(conditioning) != 1:
        raise ValueError(f"{name}: connect CONDITIONING with exactly one entry (one prompt encode)")
    entry = conditioning[0]
    if type(entry) not in (list, tuple) or len(entry) != 2 or type(entry[1]) is not dict:
        raise ValueError(f"{name}: malformed CONDITIONING entry")
    prompt, metadata = entry
    if not isinstance(prompt, torch.Tensor) or prompt.ndim != 3 or prompt.shape[0] != 1:
        raise ValueError(f"{name}: prompt conditioning must be one batch-one tensor")
    if not bool(torch.isfinite(prompt).all()):
        raise ValueError(f"{name}: prompt conditioning must be finite")
    unsupported = sorted(str(key) for key in metadata if key not in UPSTREAM_METADATA)
    if unsupported:
        raise ValueError(
            f"{name}: unsupported conditioning metadata {unsupported}. Phase 1 layers accept plain "
            "prompt encodes; masks, areas, hooks, timestep ranges and ControlNets belong elsewhere")
    mask = layer.mask
    if not isinstance(mask, torch.Tensor) or mask.dtype != torch.float32:
        raise ValueError(f"{name}: the field must be a binary32 MASK")
    if mask.ndim == 2:
        # ConditioningSetMask's own promotion of a single 2-D mask.
        mask = mask.unsqueeze(0)
    if tuple(mask.shape) != FIELD_SHAPE:
        raise ValueError(f"{name}: the field must be one unresized {FIELD_SHAPE[1]}x{FIELD_SHAPE[2]} mask, "
                         f"got shape {tuple(mask.shape)}")
    try:
        codes = tuple(recover_sample_code(value)
                      for value in mask.detach().to(device="cpu").reshape(-1).tolist())
    except ValueError:
        raise ValueError(f"{name}: the field must use the exact retained 8-bit codebook, from an Influence "
                         "Field source or Load Image (as Mask), without resizing or other mask processing") from None
    return prompt, metadata, codes


class ConditioningLayersLayer:
    """One visible layer branch; identity is this node, never its content."""

    DESCRIPTION = ("One conditioning layer: ordinary CONDITIONING from any prompt, CLIP or LoRA chain, "
                   "its field MASK, a Strength and a FIXED or BLENDED mode.")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "conditioning": ("CONDITIONING", {
                    "tooltip": "Ordinary CONDITIONING from one prompt encode, e.g. CLIP Text Encode fed by "
                               "any CLIP or LoRA loader chain."}),
                "mask": ("MASK", {
                    "tooltip": "This layer's field: an exact-codebook 128x128 MASK from an Influence "
                               "Field source or an unresized 8-bit image loaded with Load Image (as Mask)."}),
                "strength": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "BLENDED: overlapping layers share each sample in proportion to field x "
                               "Strength. FIXED: any Strength above 0 owns the area fully; 0 leaves it empty."}),
                "mode": ([mode.value for mode in LayerMode], {
                    "default": LayerMode.BLENDED.value,
                    "tooltip": "BLENDED may overlap other BLENDED layers. FIXED owns every sample where its "
                               "field is positive; no other layer contributes there and FIXED fields must "
                               "not overlap."}),
                "enabled": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Off keeps the layer in the stack but leaves it out of the composition."}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = (LAYER_TYPE,)
    RETURN_NAMES = ("layer",)
    FUNCTION = "create"
    CATEGORY = CATEGORY

    def create(self, conditioning, mask, strength, mode, enabled, unique_id=None):
        layer = LayerDescriptor(unique_id, conditioning, mask, strength, mode, enabled)
        if layer.enabled:
            # Fail at the authoring node; Compose validates again before use.
            _prepared_inputs(layer, _runtime_torch())
        return (layer,)


class ConditioningLayersAddLayer:
    """Append one layer to a stack; a chain of these fixes the authored order."""

    DESCRIPTION = "Append a layer to the stack. Chain one per layer; chain order is layer order."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {"layer": (LAYER_TYPE, {"tooltip": "The layer to append."})},
            "optional": {"layers": (LAYER_STACK_TYPE, {
                "tooltip": "The stack so far. Leave unconnected to start a new stack."})},
        }

    RETURN_TYPES = (LAYER_STACK_TYPE,)
    RETURN_NAMES = ("layers",)
    FUNCTION = "add"
    CATEGORY = CATEGORY

    def add(self, layer, layers=None):
        if type(layer) is not LayerDescriptor:
            raise ValueError("Add Conditioning Layer requires a Conditioning Layer output")
        if layers is None:
            return (LayerStack((layer,)),)
        if type(layers) is not LayerStack:
            raise ValueError("Add Conditioning Layer requires a layer stack from another Add Conditioning Layer")
        return (layers.append(layer),)


class ConditioningLayersCompose:
    """Compose an ordered stack into ordinary CONDITIONING for KSampler positive."""

    DESCRIPTION = ("Compose the layer stack: FIXED layers own their positive field samples exclusively; "
                   "BLENDED layers share the remaining samples by normalized field x Strength. Samples no "
                   "layer supports receive no layer contribution. Connect to KSampler positive.")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"layers": (LAYER_STACK_TYPE, {"tooltip": "The ordered layer stack."})}}

    RETURN_TYPES = ("CONDITIONING",)
    RETURN_NAMES = ("conditioning",)
    FUNCTION = "compose"
    CATEGORY = CATEGORY

    def compose(self, layers):
        torch = _runtime_torch()
        from comfy import model_management

        if model_management.intermediate_dtype() != torch.float32:
            raise ValueError("Compose Conditioning Layers requires binary32 intermediate execution")
        if type(layers) is not LayerStack:
            raise ValueError("Compose Conditioning Layers requires a stack from Add Conditioning Layer")
        # Re-check the stack invariants and every descriptor, then use only the checked values.
        active = tuple(LayerDescriptor(layer.layer_id, layer.conditioning, layer.mask, layer.strength,
                                       layer.mode, layer.enabled)
                       for layer in LayerStack(layers.layers).enabled_layers)
        if not active:
            raise ValueError("Compose Conditioning Layers has no enabled layer")
        entries, planes = [], []
        for layer in active:
            prompt, metadata, codes = _prepared_inputs(layer, torch)
            entries.append((prompt, metadata))
            planes.append(codes)
        prepared = compose_field_codes(
            tuple(planes), tuple(layer.strength for layer in active),
            tuple(layer.mode for layer in active), labels=tuple(layer.layer_id for layer in active))
        conditioning = []
        for (prompt, metadata), bits in zip(entries, prepared, strict=True):
            output = metadata.copy()
            # Install the already-rounded IEEE bits, as the retained preparation does.
            output["mask"] = torch.tensor(bits, dtype=torch.int32, device="cpu").view(torch.float32).reshape(FIELD_SHAPE)
            output["set_area_to_bounds"] = PREPARED_SET_AREA_TO_BOUNDS
            output["mask_strength"] = PREPARED_MASK_STRENGTH
            conditioning.append([prompt, output])
        return (conditioning,)


_NODES = (
    ("ConditioningLayersLayer", ConditioningLayersLayer, "Conditioning Layer"),
    ("ConditioningLayersAddLayer", ConditioningLayersAddLayer, "Add Conditioning Layer"),
    ("ConditioningLayersCompose", ConditioningLayersCompose, "Compose Conditioning Layers"),
)
LAYER_NODE_CLASS_NAMES = tuple(name for name, _, _ in _NODES)


def initialize_layer_node_registration():
    """Return fresh node and display-name mappings; registering is the root loader's job."""
    return ({name: node for name, node, _ in _NODES},
            {name: display for name, _, display in _NODES})
