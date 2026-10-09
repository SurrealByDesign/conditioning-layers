"""Non-destructive periodic resampling of any native CPU Influence Field.

Destination centers map to source sample indices as
((x + .5 - phase_x) * repeats_x - .5) modulo 128 (and likewise Y).
Integer controls keep coordinates on exact integer/half-integer positions;
bilinear interpolation and half-up quantization are therefore exact in binary64.
Both neighbors wrap at a seam. No source-category detection or Transform logic.
"""

import math

from conditioning_layers.comfyui.influence_field_sources import FIELD_SHAPE, codes_to_mask
from conditioning_layers.comfyui.prediction_mixing.blend_preparation import recover_sample_code


FIELD_REPEAT_NODE_CLASS_NAMES = ("ConditioningLayersFieldRepeat",)


def _integer(name, value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")
    return value


class ConditioningLayersFieldRepeat:
    DESCRIPTION = ("Repeat any exact-codebook 128x128 Influence Field in memory. "
                   "Integer counts fit complete source tiles across each axis. "
                   "Phase shifts right/down in destination field cells and wraps. "
                   "Periodic bilinear code-space sampling, nearest-code ties up. "
                   "Graph order determines operation order; no automatic Transform ordering.")
    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("mask",)
    FUNCTION = "repeat"
    CATEGORY = "conditioning/conditioning_layers/fields"

    @classmethod
    def INPUT_TYPES(cls):
        def count(axis):
            return ("INT", {"default": 1, "min": 1, "max": 16, "step": 1,
                            "tooltip": f"Complete source repetitions across field {axis}; output stays 128x128."})

        def phase(direction):
            return ("INT", {"default": 0, "min": -128, "max": 128, "step": 1,
                            "tooltip": f"Periodic origin shift in destination field cells; positive {direction}, wraps."})

        return {"required": {
            "mask": ("MASK", {"tooltip": "CPU binary32 exact-codebook 128x128 field; input is never modified."}),
            "repeats_x": count("width"), "repeats_y": count("height"),
            "phase_x": phase("right"), "phase_y": phase("down"),
        }}

    def repeat(self, mask, repeats_x=1, repeats_y=1, phase_x=0, phase_y=0):
        rx = _integer("repeats_x", repeats_x, 1, 16)
        ry = _integer("repeats_y", repeats_y, 1, 16)
        px = _integer("phase_x", phase_x, -128, 128)
        py = _integer("phase_y", phase_y, -128, 128)

        import torch

        if not isinstance(mask, torch.Tensor) or mask.dtype != torch.float32:
            raise ValueError("Field Repeat requires a binary32 MASK")
        if mask.device.type != "cpu":
            raise ValueError("Field Repeat requires a CPU MASK")
        if mask.ndim == 2:
            mask = mask.unsqueeze(0)
        if tuple(mask.shape) != FIELD_SHAPE:
            raise ValueError("Field Repeat requires one unresized 128x128 mask")
        try:
            codes = tuple(recover_sample_code(value) for value in mask.detach().reshape(-1).tolist())
        except ValueError:
            raise ValueError("Field Repeat requires the exact retained 8-bit codebook; "
                             "arbitrary input floats are not quantized") from None

        def sample(x, y):
            sx = ((x + 0.5 - px) * rx - 0.5) % 128
            sy = ((y + 0.5 - py) * ry - 0.5) % 128
            left, top = math.floor(sx), math.floor(sy)
            right, bottom = (left + 1) % 128, (top + 1) % 128
            fx, fy = sx - left, sy - top
            a, b = codes[top * 128 + left], codes[top * 128 + right]
            c, d = codes[bottom * 128 + left], codes[bottom * 128 + right]
            upper, lower = a + (b - a) * fx, c + (d - c) * fx
            return min(255, max(0, math.floor(upper + (lower - upper) * fy + 0.5)))

        return (codes_to_mask(sample(x, y) for y in range(128) for x in range(128)),)


def initialize_field_repeat_node_registration():
    """Fresh mappings without runtime, source-file or consumer imports."""
    return ({FIELD_REPEAT_NODE_CLASS_NAMES[0]: ConditioningLayersFieldRepeat},
            {FIELD_REPEAT_NODE_CLASS_NAMES[0]: "Field Repeat"})
