"""Non-destructive native field geometry, with one code-space resampling pass.

Cell centers are (x + .5, y + .5); the canvas center is (64, 64). Forward
order: local flips, axis scales multiplied by uniform scale, clockwise rotation,
then canvas-axis translation. Inverse mapping samples the original field once.
The source footprint is [0,128) on each axis; outside is zero. Inside, bilinear
sampling clamps to edge centers. Binary64 code-space interpolation rounds to
nearest integer, ties up, then uses the retained canonical MASK encoder.
"""

import math

from conditioning_layers.comfyui.influence_field_sources import FIELD_SHAPE, codes_to_mask
from conditioning_layers.comfyui.prediction_mixing.blend_preparation import recover_sample_code


FIELD_TRANSFORM_NODE_CLASS_NAMES = ("ConditioningLayersFieldTransform",)


def _number(name, value, low, high):
    if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number in [{low}, {high}]")
    return float(value)


def _bilinear(codes, x, y):
    if not (0.0 <= x < 128.0 and 0.0 <= y < 128.0):
        return 0
    x, y = max(0.0, min(127.0, x - 0.5)), max(0.0, min(127.0, y - 0.5))
    left, top = math.floor(x), math.floor(y)
    right, bottom = min(127, left + 1), min(127, top + 1)
    fx, fy = x - left, y - top
    a, b = codes[top * 128 + left], codes[top * 128 + right]
    c, d = codes[bottom * 128 + left], codes[bottom * 128 + right]
    upper, lower = a + (b - a) * fx, c + (d - c) * fx
    return min(255, max(0, math.floor(upper + (lower - upper) * fy + 0.5)))


class ConditioningLayersFieldTransform:
    DESCRIPTION = ("Transform any exact-codebook 128x128 Influence Field in memory. "
                   "Flip, scale about center, rotate clockwise, then offset right/down in field cells. "
                   "Bilinear sampling with nearest-code ties up; zero outside the source footprint. "
                   "Hard edges can acquire intermediate codes; no wrapping or value inversion.")
    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("mask",)
    FUNCTION = "transform"
    CATEGORY = "conditioning/conditioning_layers/fields"

    @classmethod
    def INPUT_TYPES(cls):
        def scale(tooltip):
            return ("FLOAT", {"default": 1.0, "min": 0.01, "max": 100.0, "step": 0.01,
                              "tooltip": tooltip})

        def offset(axis):
            return ("FLOAT", {"default": 0.0, "min": -16384.0, "max": 16384.0, "step": 0.5,
                              "tooltip": f"{axis} translation in field cells, after rotation; clipped, never wrapped."})

        return {"required": {
            "mask": ("MASK", {"tooltip": "CPU binary32 exact-codebook 128x128 field; input is never modified."}),
            "uniform_scale": scale("Multiplies both axis scales; 1 is unchanged, below 1 shrinks."),
            "scale_x": scale("Local X scale multiplied by uniform scale, before rotation."),
            "scale_y": scale("Local Y scale multiplied by uniform scale, before rotation."),
            "rotation_degrees": ("FLOAT", {"default": 0.0, "min": -360.0, "max": 360.0, "step": 1.0,
                                           "tooltip": "Positive is clockwise about field center (64,64)."}),
            "offset_x": offset("Positive right"), "offset_y": offset("Positive down"),
            "flip_horizontal": ("BOOLEAN", {"default": False, "tooltip": "Mirror local X before rotation; values unchanged."}),
            "flip_vertical": ("BOOLEAN", {"default": False, "tooltip": "Mirror local Y before rotation; values unchanged."}),
        }}

    def transform(self, mask, uniform_scale=1.0, scale_x=1.0, scale_y=1.0,
                  rotation_degrees=0.0, offset_x=0.0, offset_y=0.0,
                  flip_horizontal=False, flip_vertical=False):
        uniform = _number("uniform_scale", uniform_scale, 0.01, 100.0)
        sx = uniform * _number("scale_x", scale_x, 0.01, 100.0)
        sy = uniform * _number("scale_y", scale_y, 0.01, 100.0)
        angle = _number("rotation_degrees", rotation_degrees, -360.0, 360.0) % 360.0
        ox = _number("offset_x", offset_x, -16384.0, 16384.0)
        oy = _number("offset_y", offset_y, -16384.0, 16384.0)
        if type(flip_horizontal) is not bool or type(flip_vertical) is not bool:
            raise ValueError("Field Transform flips must be booleans")
        if flip_horizontal:
            sx = -sx
        if flip_vertical:
            sy = -sy
        # Exact quarter turns avoid trigonometric noise at discrete sample centers.
        if angle % 90.0 == 0.0:
            cosine, sine = ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))[int(angle / 90)]
        else:
            radians = math.radians(angle)
            cosine, sine = math.cos(radians), math.sin(radians)

        import torch

        if not isinstance(mask, torch.Tensor) or mask.dtype != torch.float32:
            raise ValueError("Field Transform requires a binary32 MASK")
        if mask.device.type != "cpu":
            raise ValueError("Field Transform requires a CPU MASK")
        if mask.ndim == 2:
            mask = mask.unsqueeze(0)
        if tuple(mask.shape) != FIELD_SHAPE:
            raise ValueError("Field Transform requires one unresized 128x128 mask")
        try:
            codes = tuple(recover_sample_code(value) for value in mask.detach().reshape(-1).tolist())
        except ValueError:
            raise ValueError("Field Transform requires the exact retained 8-bit codebook; "
                             "arbitrary input floats are not quantized") from None

        def sample(x, y):
            dx, dy = x + 0.5 - 64.0 - ox, y + 0.5 - 64.0 - oy
            source_x = (cosine * dx + sine * dy) / sx + 64.0
            source_y = (-sine * dx + cosine * dy) / sy + 64.0
            return _bilinear(codes, source_x, source_y)

        return (codes_to_mask(sample(x, y) for y in range(128) for x in range(128)),)


def initialize_field_transform_node_registration():
    """No runtime imports, source assets, Layer runtime or host needed to register."""
    return ({FIELD_TRANSFORM_NODE_CLASS_NAMES[0]: ConditioningLayersFieldTransform},
            {FIELD_TRANSFORM_NODE_CLASS_NAMES[0]: "Field Transform"})
