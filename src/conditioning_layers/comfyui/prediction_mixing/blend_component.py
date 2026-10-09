"""Narrow project-owned Blend preparation node and separate implementation identity.

Importing this authority never imports Torch or ComfyUI. Runtime dependencies
are initialized only by the optional node registration or node execution.
"""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import sys

from .blend_component_manifest import SOURCE_SHA256
from .multi_layer.canonical import fingerprint


BLEND_NODE_CLASS = "ConditioningLayersNormalizedBlend"
BLEND_ALGORITHM_ID = "prediction-mixing.normalized-blend.exact-rational-binary32.v1"
BLEND_COMPONENT_CONTRACT_ID = "prediction-mixing.normalized-blend.preparation.conditioning.exact-3.v1"
BLEND_DEPENDENCIES = (("torch", "2.8.0+cu129"), ("numpy", "2.4.6"), ("av", "17.0.1"))


def blend_node_contract() -> dict:
    return {
        "class_name": BLEND_NODE_CLASS,
        "input_types": {"required": {"conditioning": ("CONDITIONING",)}},
        "return_types": ("CONDITIONING",), "function": "prepare",
        "exact_cardinality": 3, "mask_shape": (1, 128, 128),
        "input_dtype": "binary32", "preparation_device": "cpu",
        "output_dtype": "binary32", "mask_strength": 1.0,
        "set_area_to_bounds": False,
        "decode": ("rne-binary32(n/255)", "rne-binary32(n*256/65535)"),
        "dependencies": BLEND_DEPENDENCIES,
        "permitted_metadata": ("mask", "mask_strength", "set_area_to_bounds", "pooled_output", "attention_mask"),
    }


@dataclass(frozen=True, slots=True)
class BlendComponentIdentity:
    component_id: str
    algorithm_id: str
    contract_id: str
    source_sha256: str
    contract_fingerprint: str
    implementation_fingerprint: str


def blend_component_identity() -> BlendComponentIdentity:
    """Return governed anchors, independently of observed disk or host state."""
    material = {
        "component_id": BLEND_NODE_CLASS, "algorithm_id": BLEND_ALGORITHM_ID,
        "contract_id": BLEND_COMPONENT_CONTRACT_ID,
        "source_sha256": fingerprint(SOURCE_SHA256),
        "contract_fingerprint": fingerprint(blend_node_contract()),
    }
    return BlendComponentIdentity(**material, implementation_fingerprint=fingerprint(material))


def validate_blend_component_identity(value: object) -> bool:
    return type(value) is BlendComponentIdentity and value == blend_component_identity()


def _observed_sources() -> dict[str, str]:
    root = Path(__file__).resolve().parent
    return {name: hashlib.sha256((root / name).read_text(encoding="utf-8").encode("utf-8")).hexdigest()
            for name in SOURCE_SHA256}


def verify_blend_component_source() -> bool:
    """Check current anchors and, when loaded, the node's import-time source."""
    try:
        runtime = sys.modules.get(__package__ + '.blend_node')
        loaded = getattr(runtime, 'LOADED_SOURCE_SHA256', SOURCE_SHA256)
        return loaded == SOURCE_SHA256 == _observed_sources()
    except (OSError, UnicodeError):
        return False


def initialize_blend_node_registration():
    """Optional Blend registration initialization, isolated by the root loader."""
    from .blend_node import ConditioningLayersNormalizedBlend, _runtime_dependencies

    _runtime_dependencies()
    if not verify_blend_component_source():
        raise RuntimeError("Blend implementation does not match its governed source anchors")
    return {BLEND_NODE_CLASS: ConditioningLayersNormalizedBlend}, blend_component_identity()
