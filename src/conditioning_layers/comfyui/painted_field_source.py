"""One inline native Influence Field, validated before the retained conversion."""

from conditioning_layers.assets.field_png import decode_field_data_url
from conditioning_layers.comfyui.influence_field_sources import codes_to_mask


PAINTED_FIELD_NODE_CLASS_NAMES = ("ConditioningLayersPaintedField",)


class ConditioningLayersPaintedField:
    DESCRIPTION = "Paint exact 128x128 Influence Field codes in a node-launched editor."
    RETURN_TYPES = ("MASK",)
    RETURN_NAMES = ("mask",)
    FUNCTION = "load"
    CATEGORY = "conditioning/conditioning_layers/fields"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"field": ("STRING", {
            "default": "", "widgetType": "CONDITIONING_LAYERS_PAINTED_FIELD",
            "socketless": True,
            "tooltip": "Inline 128x128 grayscale-8 PNG; empty means zero influence. Edit Field opens the editor.",
        })}}

    def load(self, field):
        return (codes_to_mask(decode_field_data_url(field)),)


def initialize_painted_field_node_registration():
    return ({PAINTED_FIELD_NODE_CLASS_NAMES[0]: ConditioningLayersPaintedField},
            {PAINTED_FIELD_NODE_CLASS_NAMES[0]: "Painted Field"})
