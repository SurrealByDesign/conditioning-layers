"""Non-destructive spatial modulation in recovered Influence Field codes.

Sample centers use canvas-edge projection for linear fades. Radial distances
use 64-cell units, inverse clockwise rotation, then local-axis aspect division.
All geometry and modulation use binary64; only the final product is quantized.
"""

import math

from conditioning_layers.comfyui.influence_field_sources import FIELD_SHAPE, codes_to_mask
from conditioning_layers.comfyui.prediction_mixing.blend_preparation import recover_sample_code


FIELD_FADE_NODE_CLASS_NAMES = ("ConditioningLayersFieldFade",)


def _number(name, value, low, high):
    if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number in [{low}, {high}]")
    return float(value)


def _code(name, value):
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError(f"{name} must be an integer in [0, 255]")
    return value


def _axes(angle):
    angle %= 360.0
    # Exact cardinal axes and equal diagonal components preserve grid symmetry.
    if angle % 45.0 == 0.0:
        h = math.sqrt(0.5)
        return ((1., 0.), (h, h), (0., 1.), (-h, h),
                (-1., 0.), (-h, -h), (0., -1.), (h, -h))[int(angle / 45)]
    return math.cos(math.radians(angle)), math.sin(math.radians(angle))


def _quantize(value):
    whole = math.floor(value)
    # Do not add .5: that can round a binary64 value just below a tie upward.
    return min(255, max(0, whole + int(value - whole >= 0.5)))


def _fade_function(fade_mode, start_value, end_value, curve_exponent,
                   angle_degrees, fade_start_position, fade_end_position,
                   center_x, center_y, inner_size, outer_size,
                   aspect_x, aspect_y, rotation_degrees):
    """Validate active controls and return unquantized fade codes at cell indices."""
    if type(fade_mode) is not str or fade_mode not in ("linear", "circular", "square"):
        raise ValueError("fade_mode must be linear, circular or square")
    first, last = _code("start_value", start_value), _code("end_value", end_value)
    exponent = _number("curve_exponent", curve_exponent, 0.1, 10.0)
    if fade_mode == "linear":
        c, s = _axes(_number("angle_degrees", angle_degrees, -360, 360))
        low = _number("fade_start_position", fade_start_position, 0, 1)
        high = _number("fade_end_position", fade_end_position, 0, 1)
        if low >= high:
            raise ValueError("Field Fade requires fade_start_position < fade_end_position")
        span = 128.0 * (abs(c) + abs(s))

        def coordinate(x, y):
            return 0.5 + ((x + 0.5 - 64) * c + (y + 0.5 - 64) * s) / span
    else:
        cx = 128 * _number("center_x", center_x, 0, 1)
        cy = 128 * _number("center_y", center_y, 0, 1)
        low = _number("inner_size", inner_size, 0, 1.5)
        high = _number("outer_size", outer_size, 0, 1.5)
        if low >= high:
            raise ValueError("Field Fade requires inner_size < outer_size")
        ax = _number("aspect_x", aspect_x, 0.1, 10)
        ay = _number("aspect_y", aspect_y, 0.1, 10)
        angle = _number("rotation_degrees", rotation_degrees, -360, 360)
        # A true circle is exactly rotation-invariant, including near code ties.
        c, s = _axes(0 if fade_mode == "circular" and ax == ay else angle)

        def coordinate(x, y):
            dx, dy = x + 0.5 - cx, y + 0.5 - cy
            lx = (c * dx + s * dy) / (64.0 * ax)
            ly = (-s * dx + c * dy) / (64.0 * ay)
            return math.hypot(lx, ly) if fade_mode == "circular" else max(abs(lx), abs(ly))

    def fade(x, y):
        position = coordinate(x, y)
        if position <= low:
            return float(first)
        if position >= high:
            return float(last)
        t = (position - low) / (high - low)
        return first + t ** exponent * (last - first)

    return fade


class ConditioningLayersFieldFade:
    DESCRIPTION = ("Modulate an exact-codebook 128x128 CPU Influence Field with a linear, circular or square fade. "
                   "Start/end are influence codes; curve exponent shapes the transition. "
                   "Radial size 1 = 64 cells. Positive angles are clockwise. Unused mode controls are ignored. "
                   "This authors fields; soft values do not feather FIXED ownership.")
    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("mask",)
    FUNCTION = "apply"
    CATEGORY = "conditioning/conditioning_layers/fields"

    @classmethod
    def INPUT_TYPES(cls):
        def number(kind, default, low, high, step, tooltip):
            return (kind, {"default": default, "min": low, "max": high, "step": step,
                           "display": "number", "tooltip": tooltip})

        return {"required": {
            "mask": ("MASK", {"tooltip": "Exact-codebook CPU float32 128x128 field; never modified."}),
            "fade_mode": (["linear", "circular", "square"], {"default": "linear"}),
            "start_value": number("INT", 255, 0, 255, 1, "Fade code before/inside the transition; any endpoint ordering."),
            "end_value": number("INT", 0, 0, 255, 1, "Fade code after/outside the transition; input is multiplied by fade/255."),
            "curve_exponent": number("FLOAT", 1.0, .1, 10., .1, "t ** exponent: 1 linear; above 1 changes later; below 1 earlier."),
            "angle_degrees": number("FLOAT", 0., -360., 360., 1., "Linear only: 0 right, 90 down, 180 left, 270 up."),
            "fade_start_position": number("FLOAT", 0., 0., 1., .01, "Linear only: normalized projected canvas edge span; must be below end."),
            "fade_end_position": number("FLOAT", 1., 0., 1., .01, "Linear only: transition end in projected canvas edge span; must exceed start."),
            "center_x": number("FLOAT", .5, 0., 1., .01, "Circular/square only: 0 left edge, 1 right edge."),
            "center_y": number("FLOAT", .5, 0., 1., .01, "Circular/square only: 0 top edge, 1 bottom edge."),
            "inner_size": number("FLOAT", .25, 0., 1.5, .01, "Circular/square only: start plateau radius in 64-cell units, before aspect; below outer."),
            "outer_size": number("FLOAT", .5, 0., 1.5, .01, "Circular/square only: transition completion radius in 64-cell units; above inner."),
            "aspect_x": number("FLOAT", 1., .1, 10., .1, "Circular/square only: divide rotated local X distance by this value; larger stretches local X."),
            "aspect_y": number("FLOAT", 1., .1, 10., .1, "Circular/square only: divide rotated local Y distance by this value; larger stretches local Y."),
            "rotation_degrees": number("FLOAT", 0., -360., 360., 1., "Circular/square only: clockwise about the chosen center; rotates ellipse/rectangle axes."),
        }}

    def apply(self, mask, fade_mode="linear", start_value=255, end_value=0,
              curve_exponent=1.0, angle_degrees=0.0,
              fade_start_position=0.0, fade_end_position=1.0,
              center_x=0.5, center_y=0.5, inner_size=0.25, outer_size=0.5,
              aspect_x=1.0, aspect_y=1.0, rotation_degrees=0.0):
        fade = _fade_function(fade_mode, start_value, end_value, curve_exponent,
                              angle_degrees, fade_start_position, fade_end_position,
                              center_x, center_y, inner_size, outer_size,
                              aspect_x, aspect_y, rotation_degrees)
        import torch

        if not isinstance(mask, torch.Tensor) or mask.dtype != torch.float32:
            raise ValueError("Field Fade requires a binary32 MASK")
        if mask.device.type != "cpu":
            raise ValueError("Field Fade requires a CPU MASK")
        if mask.ndim == 2:
            mask = mask.unsqueeze(0)
        if tuple(mask.shape) != FIELD_SHAPE:
            raise ValueError("Field Fade requires one unresized 128x128 mask")
        try:
            codes = tuple(recover_sample_code(value) for value in mask.detach().reshape(-1).tolist())
        except ValueError:
            raise ValueError("Field Fade requires the exact retained 8-bit codebook; "
                             "arbitrary input floats are not quantized") from None
        return (codes_to_mask(_quantize(code * fade(i % 128, i // 128) / 255.0)
                              for i, code in enumerate(codes)),)


def initialize_field_fade_node_registration():
    """Fresh mappings without runtime, assets, consumers or admission imports."""
    return ({FIELD_FADE_NODE_CLASS_NAMES[0]: ConditioningLayersFieldFade},
            {FIELD_FADE_NODE_CLASS_NAMES[0]: "Field Fade"})
