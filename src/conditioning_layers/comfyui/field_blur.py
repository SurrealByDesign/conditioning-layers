"""Non-destructive, code-space Gaussian smoothing of native Influence Fields.

For integer radius r > 0, sigma=r/2 and the normalized 1-D kernel is
exp(-k*k/(2*sigma*sigma)), k=-r..r. Apply X then Y with zero padding,
binary64 intermediates and no intermediate quantization or edge renormalization.
Round the final value once to nearest code, exact half ties upward.
"""

import math

from conditioning_layers.comfyui.influence_field_sources import FIELD_SHAPE, codes_to_mask
from conditioning_layers.comfyui.prediction_mixing.blend_preparation import recover_sample_code


FIELD_BLUR_NODE_CLASS_NAMES = ("ConditioningLayersFieldBlur",)


def _quantize(value):
    # Compare the fractional part: adding .5 can round a value just below a tie
    # onto the next integer in binary64. No epsilon or near-tie snapping.
    whole = math.floor(value)
    return min(255, max(0, whole + int(value - whole >= 0.5)))


class ConditioningLayersFieldBlur:
    DESCRIPTION = ("Gaussian smoothing of any exact-codebook 128x128 CPU Influence Field. "
                   "Radius is kernel support in field cells; sigma = radius/2. "
                   "Zero influence outside the canvas, no wrapping or edge renormalization. "
                   "Nearest-code rounding, exact half ties up. Soft fields do not feather FIXED ownership.")
    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("mask",)
    FUNCTION = "blur"
    CATEGORY = "conditioning/conditioning_layers/fields"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "mask": ("MASK", {"tooltip": "CPU binary32 exact-codebook 128x128 field; input is never modified."}),
            "radius": ("INT", {"default": 0, "min": 0, "max": 32, "step": 1,
                               "tooltip": "Kernel extends this many field cells each way; sigma = radius/2. Zero preserves codes."}),
        }}

    def blur(self, mask, radius=0):
        if type(radius) is not int or not 0 <= radius <= 32:
            raise ValueError("radius must be an integer in [0, 32]")

        import torch
        import torch.nn.functional as functional

        if not isinstance(mask, torch.Tensor) or mask.dtype != torch.float32:
            raise ValueError("Field Blur requires a binary32 MASK")
        if mask.device.type != "cpu":
            raise ValueError("Field Blur requires a CPU MASK")
        if mask.ndim == 2:
            mask = mask.unsqueeze(0)
        if tuple(mask.shape) != FIELD_SHAPE:
            raise ValueError("Field Blur requires one unresized 128x128 mask")
        try:
            codes = tuple(recover_sample_code(value) for value in mask.detach().reshape(-1).tolist())
        except ValueError:
            raise ValueError("Field Blur requires the exact retained 8-bit codebook; "
                             "arbitrary input floats are not quantized") from None
        if radius == 0:
            return (codes_to_mask(codes),)

        sigma = radius / 2.0
        weights = tuple(math.exp(-k * k / (2 * sigma * sigma))
                        for k in range(-radius, radius + 1))
        total = math.fsum(weights)
        kernel = torch.tensor([weight / total for weight in weights], dtype=torch.float64, device="cpu")
        source = torch.tensor(codes, dtype=torch.float64, device="cpu").reshape(1, 1, 128, 128)
        horizontal = functional.conv2d(source, kernel.reshape(1, 1, 1, -1), padding=(0, radius))
        smoothed = functional.conv2d(horizontal, kernel.reshape(1, 1, -1, 1), padding=(radius, 0))
        return (codes_to_mask(_quantize(value) for value in smoothed.reshape(-1).tolist()),)


def initialize_field_blur_node_registration():
    """Fresh mappings without runtime, asset or consumer imports."""
    return ({FIELD_BLUR_NODE_CLASS_NAMES[0]: ConditioningLayersFieldBlur},
            {FIELD_BLUR_NODE_CLASS_NAMES[0]: "Field Blur"})
