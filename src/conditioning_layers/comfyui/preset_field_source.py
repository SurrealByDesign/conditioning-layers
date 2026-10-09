"""Manifest-authorized binary presets, separate from STUDY-0001 and procedures."""

import json
from pathlib import Path
import re

from conditioning_layers.assets.errors import AssetInspectionError
from conditioning_layers.assets.models import InspectionLimits
from conditioning_layers.assets.png_inspector import inspect_png_bytes
from conditioning_layers.comfyui.influence_field_sources import codes_to_mask


PRESET_FIELD_ROOT = Path(__file__).resolve().parents[3] / "influence-field-library/preset-fields/v1"
PRESET_FIELD_NODE_CLASS_NAMES = ("ConditioningLayersPresetField",)
_LIMITS = InspectionLimits(maximum_width=128, maximum_height=128,
                           maximum_pixels=16384, maximum_decoded_bytes=128 * 129)
_ID = r"[a-z0-9]+(?:-[a-z0-9]+)*"


def _asset_path(relative):
    if not isinstance(relative, str) or not re.fullmatch(r"(?:qr|barcode)/" + _ID + r"\.png", relative):
        raise ValueError("invalid preset asset path")
    root = PRESET_FIELD_ROOT.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError("preset asset path escapes library")
    return path


def _read_asset(asset):
    path = _asset_path(asset["path"])
    try:
        decoded = inspect_png_bytes(path, layer_id="preset-field",
                                    relative_reference=asset["path"], limits=_LIMITS)
    except AssetInspectionError as error:
        raise ValueError(f"Preset Field: missing or invalid asset: {error}") from error
    profile = decoded.profile
    if ((profile.width, profile.height, profile.channel_count) != (128, 128, 1)
            or set(decoded.values) != {0, 255}):
        raise ValueError("Preset Field requires a binary 128x128 grayscale-8 PNG")
    if profile.checksum != asset["sha256"]:
        raise ValueError("Preset Field asset checksum differs from manifest")
    return decoded


def preset_registry():
    """Fresh validated display-name registry; array order then dark/light.

    Fail closed for an invalid collection instead of offering broken choices.
    Registration itself never calls this filesystem boundary.
    """
    try:
        manifest = json.loads((PRESET_FIELD_ROOT / "preset-fields-manifest.json").read_text(encoding="utf-8"))
        if (manifest["format"] != "conditioning-layers.preset-fields"
                or type(manifest["version"]) is not int or manifest["version"] != 1
                or manifest["polarity_order"] != ["dark", "light"]
                or not isinstance(manifest["presets"], list) or not manifest["presets"]):
            raise ValueError("unsupported or empty manifest")
        registry, ids, paths, preset_ids = {}, set(), set(), set()
        for preset in manifest["presets"]:
            preset_id = preset["preset_id"]
            if (not isinstance(preset_id, str) or not re.fullmatch(_ID, preset_id)
                    or preset_id in preset_ids):
                raise ValueError("invalid or duplicate preset ID")
            preset_ids.add(preset_id)
            if (preset["version"] != 1 or preset["field_type"] != "binary"
                    or (preset["width"], preset["height"], preset["bit_depth"]) != (128, 128, 8)
                    or preset["channel_mode"] != "grayscale-8" or preset["alpha"] is not False
                    or preset["support_status"] != "illustrative"
                    or preset["category"] not in ("qr", "barcode")
                    or preset["complement_relation"] != "light = 255 - dark at every sample"
                    or set(preset["assets"]) != {"dark", "light"}):
                raise ValueError("incompatible preset profile")
            codes = []
            for polarity in manifest["polarity_order"]:
                asset = preset["assets"][polarity]
                identifier, label, relative = asset["id"], asset["display_name"], asset["path"]
                if (identifier != preset_id + "-" + polarity or identifier in ids
                        or not isinstance(label, str) or not label.strip() or label in registry
                        or not isinstance(relative, str) or relative in paths
                        or relative != preset["category"] + "/" + identifier + ".png"
                        or not isinstance(asset["sha256"], str)
                        or not re.fullmatch(r"[0-9a-f]{64}", asset["sha256"])):
                    raise ValueError("invalid or duplicate preset entry")
                codes.append(_read_asset(asset).values)
                registry[label] = dict(asset)
                ids.add(identifier)
                paths.add(relative)
            if any(a + b != 255 for a, b in zip(*codes)):
                raise ValueError("preset assets are not exact complements")
        return registry
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f"Preset Field library is missing or invalid: {error}") from error


def _read_preset(preset):
    registry = preset_registry()
    if not isinstance(preset, str) or preset not in registry:
        raise ValueError(f"Preset Field: unknown preset {preset!r}")
    return _read_asset(registry[preset])


class ConditioningLayersPresetField:
    DESCRIPTION = ("Load a retained binary QR or UPC Influence Field. Dark selects printed modules/bars; "
                   "Light is its exact complement and conventional display orientation. "
                   "Transform, Blur, Fade or Repeat can destroy machine readability. "
                   "Conditioned generated images are not guaranteed to scan.")
    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("mask",)
    FUNCTION = "load"
    CATEGORY = "conditioning/conditioning_layers/fields"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"preset": (list(preset_registry()), {
            "tooltip": "Manifest-ordered retained binary presets; no resampling or file modification."})}}

    @classmethod
    def IS_CHANGED(cls, preset):
        return _read_preset(preset).profile.checksum

    def load(self, preset):
        return (codes_to_mask(_read_preset(preset).values),)


def initialize_preset_field_node_registration():
    return ({PRESET_FIELD_NODE_CLASS_NAMES[0]: ConditioningLayersPresetField},
            {PRESET_FIELD_NODE_CLASS_NAMES[0]: "Preset Field"})
