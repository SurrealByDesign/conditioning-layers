"""Native 128x128 field sources: integer codes first, retained binary32 second.

Coordinates are in field cells, origin top-left, sampled at (x + .5, y + .5).
Half-cell controls are converted to doubled integers before geometry. Linear
ramps adapt EXP-0004 pixel-center sampling and nearest/half-up quantization.
Radial falloff adapts STUDY-0001/generate-assets.py: subtract the quantized
squared-distance loss from the center value (no square root).

No host or Torch import occurs at registration. These sources confer no
composition, host qualification or product admission authority.
"""

import math

from conditioning_layers.comfyui.prediction_mixing.blend_preparation import (
    recover_sample_code,
    round_ratio_to_binary32_bits,
)


FIELD_SHAPE = (1, 128, 128)
_CODE_BITS = tuple(round_ratio_to_binary32_bits(code, 255) for code in range(256))


def _integer(name, value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")
    return value


def _half_cells(name, value, low=0, high=128):
    if (type(value) not in (int, float) or not low <= value <= high
            or not math.isfinite(value) or value * 2 != int(value * 2)):
        raise ValueError(f"{name} must be in [{low}, {high}] in half-cell steps")
    return int(value * 2)


def _values(first, second):
    return (_integer("first influence value", first, 0, 255),
            _integer("second influence value", second, 0, 255))


def _round_ratio(numerator, denominator):
    """Nonnegative integer ratio, nearest integer with midpoint ties up."""
    return (2 * numerator + denominator) // (2 * denominator)


def codes_to_mask(codes):
    """Install retained code/255 binary32 bits; never divide a Torch tensor."""
    codes = tuple(codes)
    if len(codes) != 128 * 128:
        raise ValueError("A field must contain exactly 128x128 integer codes")
    bits = tuple(_CODE_BITS[_integer("influence code", code, 0, 255)] for code in codes)
    import torch

    return torch.tensor(bits, dtype=torch.int32, device="cpu").view(torch.float32).reshape(FIELD_SHAPE)


def _field(sample):
    return codes_to_mask(sample(2 * x + 1, 2 * y + 1) for y in range(128) for x in range(128))


def _code_input(default):
    return ("INT", {"default": default, "min": 0, "max": 255,
                    "tooltip": "Influence code: 0 is no influence, 255 is full requested influence."})


def _coordinate(default, *, radius=False):
    return ("FLOAT", {"default": default, "min": 0.5 if radius else 0.0, "max": 128.0,
                      "step": 0.5, "tooltip": "Field cells in half-cell steps; x goes right, y goes down."})


def _center_inputs():
    return {"center_x": _coordinate(64.0), "center_y": _coordinate(64.0)}


def _ellipse_inputs():
    return {**_center_inputs(), "radius_x": _coordinate(32.0, radius=True),
            "radius_y": _coordinate(32.0, radius=True)}


def _ellipse_geometry(center_x, center_y, radius_x, radius_y):
    cx, cy = _half_cells("center_x", center_x), _half_cells("center_y", center_y)
    rx, ry = _half_cells("radius_x", radius_x, 0.5), _half_cells("radius_y", radius_y, 0.5)
    return cx, cy, rx * rx, ry * ry


class _FieldSource:
    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("mask",)
    FUNCTION = "generate"
    CATEGORY = "conditioning/conditioning_layers/fields"


class ConditioningLayersSolidField(_FieldSource):
    DESCRIPTION = "A constant 128x128 Influence Field. Zero is constructible; enabled empty layers fail composition."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"value": _code_input(255)}}

    def generate(self, value):
        code = _integer("value", value, 0, 255)
        return (codes_to_mask((code,) * (128 * 128)),)


class ConditioningLayersRectangleField(_FieldSource):
    DESCRIPTION = "Hard rectangle sampled at cell centers; left/top edges included, right/bottom edges excluded."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {**_center_inputs(),
                             "width": ("INT", {"default": 64, "min": 1, "max": 256}),
                             "height": ("INT", {"default": 64, "min": 1, "max": 256}),
                             "inside_value": _code_input(255), "outside_value": _code_input(0)}}

    def generate(self, center_x, center_y, width, height, inside_value, outside_value):
        cx, cy = _half_cells("center_x", center_x), _half_cells("center_y", center_y)
        width, height = _integer("width", width, 1, 256), _integer("height", height, 1, 256)
        inside, outside = _values(inside_value, outside_value)
        return (_field(lambda x, y: inside if cx - width <= x < cx + width
                       and cy - height <= y < cy + height else outside),)


class ConditioningLayersEllipseField(_FieldSource):
    DESCRIPTION = "Hard ellipse sampled at cell centers, boundary included. Independent horizontal and vertical radii."

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {**_ellipse_inputs(), "inside_value": _code_input(255),
                             "outside_value": _code_input(0)}}

    def generate(self, center_x, center_y, radius_x, radius_y, inside_value, outside_value):
        cx, cy, rx2, ry2 = _ellipse_geometry(center_x, center_y, radius_x, radius_y)
        inside, outside = _values(inside_value, outside_value)
        return (_field(lambda x, y: inside if (x - cx)**2 * ry2 + (y - cy)**2 * rx2 <= rx2 * ry2
                       else outside),)


class ConditioningLayersLinearGradientField(_FieldSource):
    DESCRIPTION = ("Pixel-center linear ramp between two endpoints; values clamp beyond them. "
                   "Defaults reach 0 and 255 at the first and last columns. Nearest-code ties round up.")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"start_x": _coordinate(0.5), "start_y": _coordinate(64.0),
                             "end_x": _coordinate(127.5), "end_y": _coordinate(64.0),
                             "start_value": _code_input(0), "end_value": _code_input(255)}}

    def generate(self, start_x, start_y, end_x, end_y, start_value, end_value):
        sx, sy = _half_cells("start_x", start_x), _half_cells("start_y", start_y)
        ex, ey = _half_cells("end_x", end_x), _half_cells("end_y", end_y)
        start, end = _values(start_value, end_value)
        dx, dy = ex - sx, ey - sy
        denominator = dx * dx + dy * dy
        if denominator == 0:
            raise ValueError("Linear gradient endpoints must be distinct")

        def sample(x, y):
            projection = max(0, min(denominator, (x - sx) * dx + (y - sy) * dy))
            return _round_ratio(start * denominator + (end - start) * projection, denominator)

        return (_field(sample),)


class ConditioningLayersRadialGradientField(_FieldSource):
    DESCRIPTION = ("Squared-distance falloff from center to elliptical extent, clamped outside. "
                   "Nearest-code distance loss is subtracted from center influence, as in STUDY-0001.")

    @classmethod
    def INPUT_TYPES(cls):
        inputs = _ellipse_inputs()
        inputs.update(radius_x=_coordinate(64.0, radius=True), radius_y=_coordinate(64.0, radius=True))
        return {"required": {**inputs, "center_value": _code_input(255), "outside_value": _code_input(0)}}

    def generate(self, center_x, center_y, radius_x, radius_y, center_value, outside_value):
        cx, cy, rx2, ry2 = _ellipse_geometry(center_x, center_y, radius_x, radius_y)
        center, outside = _values(center_value, outside_value)
        denominator = rx2 * ry2

        def sample(x, y):
            distance = min(denominator, (x - cx)**2 * ry2 + (y - cy)**2 * rx2)
            change = _round_ratio(abs(outside - center) * distance, denominator)
            return center + (change if outside >= center else -change)

        return (_field(sample),)


class ConditioningLayersInvertField(_FieldSource):
    """Complement exact codes and canonicalize at this node's output boundary.

    Both retained input encodings are accepted. Double inversion preserves
    codes exactly; only canonical code/255 inputs retain their original bits.
    Noncanonical input float bit-pattern preservation is not required.
    """

    DESCRIPTION = "Invert an exact 8-bit Influence Field: 0 becomes 255, 255 becomes 0."
    FUNCTION = "invert"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"mask": ("MASK", {
            "tooltip": "An unresized exact-codebook 128x128 MASK; output uses canonical code/255 encoding."})}}

    def invert(self, mask):
        import torch

        if not isinstance(mask, torch.Tensor) or mask.dtype != torch.float32:
            raise ValueError("Invert Field requires a binary32 MASK")
        if mask.ndim == 2:
            mask = mask.unsqueeze(0)
        if tuple(mask.shape) != FIELD_SHAPE:
            raise ValueError("Invert Field requires one unresized 128x128 mask")
        try:
            codes = tuple(recover_sample_code(value)
                          for value in mask.detach().to(device="cpu").reshape(-1).tolist())
        except ValueError:
            raise ValueError("Invert Field requires the exact retained 8-bit codebook, "
                             "without resizing or other mask processing") from None
        return (codes_to_mask(255 - code for code in codes),)


_NODES = (
    ("ConditioningLayersSolidField", ConditioningLayersSolidField, "Solid Field"),
    ("ConditioningLayersRectangleField", ConditioningLayersRectangleField, "Rectangle Field"),
    ("ConditioningLayersEllipseField", ConditioningLayersEllipseField, "Ellipse Field"),
    ("ConditioningLayersLinearGradientField", ConditioningLayersLinearGradientField, "Linear Gradient Field"),
    ("ConditioningLayersRadialGradientField", ConditioningLayersRadialGradientField, "Radial Gradient Field"),
    ("ConditioningLayersInvertField", ConditioningLayersInvertField, "Invert Field"),
)
FIELD_SOURCE_NODE_CLASS_NAMES = tuple(name for name, _, _ in _NODES)


def initialize_field_source_node_registration():
    """Fresh mappings, independent of Layer/Blend availability and runtime imports."""
    return ({name: node for name, node, _ in _NODES},
            {name: display for name, _, display in _NODES})
