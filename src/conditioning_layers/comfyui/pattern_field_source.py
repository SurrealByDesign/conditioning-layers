"""Read-only native source for the original STUDY-0001 reference fields.

The study-local pairs.json owns filenames, order and original checksums. No
directory discovery, image conversion, resampling or procedural generation.
Registration needs neither the asset files nor Torch/ComfyUI runtime imports.
"""

import json
from pathlib import Path
import re

from conditioning_layers.assets.errors import AssetInspectionError
from conditioning_layers.assets.models import InspectionLimits
from conditioning_layers.assets.png_inspector import inspect_png_bytes
from conditioning_layers.comfyui.influence_field_sources import codes_to_mask


REFERENCE_FIELD_ROOT = Path(__file__).resolve().parents[3] / "studies/STUDY-0001/reference-fields"
PATTERN_FIELD_NODE_CLASS_NAMES = ("ConditioningLayersPatternField",)
_LIMITS = InspectionLimits(maximum_width=128, maximum_height=128,
                           maximum_pixels=128 * 128, maximum_decoded_bytes=128 * 129)


def pattern_registry():
    """Fresh ordered filename/checksum mapping from the existing pair manifest."""
    try:
        manifest = json.loads((REFERENCE_FIELD_ROOT / "pairs.json").read_text(encoding="utf-8"))
        if (manifest["format"] != "STUDY-0001 reference-field pairs"
                or manifest["version"] != 1 or not manifest["pairs"]):
            raise ValueError("unsupported or empty manifest")
        registry = {}
        for pair in manifest["pairs"]:
            if (pair["dimensions"] != {"width": 128, "height": 128}
                    or pair["image_mode"] != "grayscale-8"
                    or pair["field_type"] not in ("binary", "grayscale")):
                raise ValueError("incompatible field profile")
            for kind in ("source", "inverse"):
                name, checksum = pair[kind + "_filename"], pair[kind + "_sha256"]
                if (not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*\.png", name)
                        or name in registry or not isinstance(checksum, str)
                        or not re.fullmatch(r"[0-9a-f]{64}", checksum)):
                    raise ValueError("invalid or duplicate field entry")
                registry[name] = checksum
        return registry
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f"Pattern Field library manifest is missing or invalid: {error}") from error


def _read_pattern(asset):
    registry = pattern_registry()
    if not isinstance(asset, str) or asset not in registry:
        raise ValueError(f"Pattern Field: unknown library asset {asset!r}")
    try:
        decoded = inspect_png_bytes(REFERENCE_FIELD_ROOT / asset, layer_id="pattern-field",
                                    relative_reference=asset, limits=_LIMITS)
    except AssetInspectionError as error:
        raise ValueError(f"Pattern Field {asset!r}: missing or invalid asset: {error}") from error
    profile = decoded.profile
    if (profile.width, profile.height, profile.channel_count) != (128, 128, 1):
        raise ValueError(f"Pattern Field {asset!r}: requires an original 128x128 grayscale-8 PNG")
    if profile.checksum != registry[asset]:
        raise ValueError(f"Pattern Field {asset!r}: checksum differs from the original library asset")
    if not profile.nonzero_value_count:
        raise ValueError(f"Pattern Field {asset!r}: field has no positive sample")
    return decoded


class ConditioningLayersPatternField:
    DESCRIPTION = ("Load an original STUDY-0001 pattern or inverse as a 128x128 Influence Field. "
                   "Connect directly to Conditioning Layer (FIXED or BLENDED). "
                   "These reference fields carry no visual-quality or product-admission claim.")
    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("mask",)
    FUNCTION = "load"
    CATEGORY = "conditioning/conditioning_layers/fields"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"asset": (list(pattern_registry()), {
            "tooltip": "Original field PNG, including exact inverse entries. White requests stronger influence."})}}

    @classmethod
    def IS_CHANGED(cls, asset):
        # Revalidate disk input even when ComfyUI could reuse a cached tensor.
        return _read_pattern(asset).profile.checksum

    def load(self, asset):
        return (codes_to_mask(_read_pattern(asset).values),)


def initialize_pattern_field_node_registration():
    return ({PATTERN_FIELD_NODE_CLASS_NAMES[0]: ConditioningLayersPatternField},
            {PATTERN_FIELD_NODE_CLASS_NAMES[0]: "Pattern Field"})
