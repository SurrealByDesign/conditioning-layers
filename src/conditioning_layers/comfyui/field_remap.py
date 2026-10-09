"""Non-destructive endpoint-clamped remapping in recovered influence codes.

Integer ratio arithmetic rounds the complete affine result once, with exact
half ties upward, including descending output ranges. Spatial samples stay put.
"""

from conditioning_layers.comfyui.influence_field_sources import FIELD_SHAPE, codes_to_mask
from conditioning_layers.comfyui.prediction_mixing.blend_preparation import recover_sample_code


FIELD_REMAP_NODE_CLASS_NAMES = ("ConditioningLayersFieldRemap",)


def _code(name, value):
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError(f"{name} must be an integer in [0, 255]")
    return value


class ConditioningLayersFieldRemap:
    DESCRIPTION = ("Remap any exact-codebook 128x128 CPU Influence Field in memory. "
                   "Input low must be less than input high. Values outside that range "
                   "clamp to its output endpoints. Descending output ranges reverse values. "
                   "Nearest integer code, exact half ties up; spatial positions are unchanged.")
    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("mask",)
    FUNCTION = "remap"
    CATEGORY = "conditioning/conditioning_layers/fields"

    @classmethod
    def INPUT_TYPES(cls):
        def control(default, tooltip):
            return ("INT", {"default": default, "min": 0, "max": 255, "step": 1,
                            "tooltip": tooltip})

        return {"required": {
            "mask": ("MASK", {"tooltip": "CPU binary32 exact-codebook 128x128 field; input is never modified."}),
            "input_low": control(0, "Input code mapped to output low; must be less than input high."),
            "input_high": control(255, "Input code mapped to output high; must exceed input low."),
            "output_low": control(0, "Output code at and below input low; may exceed output high."),
            "output_high": control(255, "Output code at and above input high; may be below output low."),
        }}

    def remap(self, mask, input_low=0, input_high=255, output_low=0, output_high=255):
        low = _code("input_low", input_low)
        high = _code("input_high", input_high)
        first = _code("output_low", output_low)
        last = _code("output_high", output_high)
        if low >= high:
            raise ValueError("Field Remap requires input_low < input_high")

        import torch

        if not isinstance(mask, torch.Tensor) or mask.dtype != torch.float32:
            raise ValueError("Field Remap requires a binary32 MASK")
        if mask.device.type != "cpu":
            raise ValueError("Field Remap requires a CPU MASK")
        if mask.ndim == 2:
            mask = mask.unsqueeze(0)
        if tuple(mask.shape) != FIELD_SHAPE:
            raise ValueError("Field Remap requires one unresized 128x128 mask")
        try:
            codes = tuple(recover_sample_code(value) for value in mask.detach().reshape(-1).tolist())
        except ValueError:
            raise ValueError("Field Remap requires the exact retained 8-bit codebook; "
                             "arbitrary input floats are not quantized") from None

        span = high - low

        def remap_code(code):
            position = min(high, max(low, code)) - low
            numerator = first * span + position * (last - first)
            # Round the full nonnegative ratio, not its possibly negative delta.
            rounded = (2 * numerator + span) // (2 * span)
            return min(255, max(0, rounded))

        return (codes_to_mask(remap_code(code) for code in codes),)


def initialize_field_remap_node_registration():
    """Fresh mappings without runtime, source-file or consumer imports."""
    return ({FIELD_REMAP_NODE_CLASS_NAMES[0]: ConditioningLayersFieldRemap},
            {FIELD_REMAP_NODE_CLASS_NAMES[0]: "Field Remap"})
