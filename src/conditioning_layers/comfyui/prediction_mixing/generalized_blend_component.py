"""ADR-0028 generalized Blend preparation contract and implementation identity.

An additive successor beside the frozen ADR-0026 exact-3 component. Importing
this authority never imports Torch or ComfyUI. Nothing here registers a node:
the root loader, readiness and live mappings are unchanged, and availability
is offline fixture construction only. The expected count is trusted literal
authority from an exact realization binding; the received collection never
supplies it, and the component carries no maximum count.
"""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import sys

from .blend_component import BLEND_ALGORITHM_ID, BLEND_DEPENDENCIES
from .generalized_blend_component_manifest import SOURCE_SHA256
from .multi_layer.canonical import fingerprint


GENERALIZED_BLEND_NODE_CLASS = "ConditioningLayersGeneralizedNormalizedBlend"
GENERALIZED_BLEND_COMPONENT_CONTRACT_ID = (
    "prediction-mixing.normalized-blend.preparation.conditioning.expected-count.v1")


def generalized_blend_node_contract() -> dict:
    return {
        "class_name": GENERALIZED_BLEND_NODE_CLASS,
        "input_types": {"required": {
            "conditioning": ("CONDITIONING",), "expected_count": ("INT", {"min": 1}),
        }},
        "return_types": ("CONDITIONING",), "function": "prepare",
        "expected_count": "trusted exact-binding literal; int, not bool, positive; equals received length",
        "mask_shape": (1, 128, 128),
        "input_dtype": "binary32", "preparation_device": "cpu",
        "output_dtype": "binary32", "mask_strength": 1.0,
        "set_area_to_bounds": False,
        "decode": ("rne-binary32(n/255)", "rne-binary32(n*256/65535)"),
        "dependencies": BLEND_DEPENDENCIES,
        "permitted_metadata": ("mask", "mask_strength", "set_area_to_bounds", "pooled_output", "attention_mask"),
    }


@dataclass(frozen=True, slots=True)
class GeneralizedBlendComponentIdentity:
    component_id: str
    algorithm_id: str
    contract_id: str
    source_sha256: str
    contract_fingerprint: str
    implementation_fingerprint: str


def generalized_blend_component_identity() -> GeneralizedBlendComponentIdentity:
    """Return governed anchors, independently of observed disk or host state."""
    material = {
        "component_id": GENERALIZED_BLEND_NODE_CLASS, "algorithm_id": BLEND_ALGORITHM_ID,
        "contract_id": GENERALIZED_BLEND_COMPONENT_CONTRACT_ID,
        "source_sha256": fingerprint(SOURCE_SHA256),
        "contract_fingerprint": fingerprint(generalized_blend_node_contract()),
    }
    return GeneralizedBlendComponentIdentity(**material, implementation_fingerprint=fingerprint(material))


def validate_generalized_blend_component_identity(value: object) -> bool:
    return type(value) is GeneralizedBlendComponentIdentity and value == generalized_blend_component_identity()


def _observed_sources() -> dict[str, str]:
    root = Path(__file__).resolve().parent
    return {name: hashlib.sha256((root / name).read_text(encoding="utf-8").encode("utf-8")).hexdigest()
            for name in SOURCE_SHA256}


def verify_generalized_blend_component_source() -> bool:
    """Check current anchors and, when loaded, the node's import-time source."""
    try:
        runtime = sys.modules.get(__package__ + ".generalized_blend_node")
        loaded = getattr(runtime, "LOADED_SOURCE_SHA256", SOURCE_SHA256)
        return loaded == SOURCE_SHA256 == _observed_sources()
    except (OSError, UnicodeError):
        return False
