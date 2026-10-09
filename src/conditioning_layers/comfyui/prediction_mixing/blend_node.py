"""Optional exact-3 node runtime; importing this file never imports ComfyUI."""

import sys

from .blend_preparation import normalize_sample_codes_bits, recover_sample_code
from .blend_component import (
    BLEND_DEPENDENCIES, BLEND_NODE_CLASS, blend_component_identity,
    blend_node_contract, verify_blend_component_source, _observed_sources,
)

# Captured when the runtime class is loaded, independently of later disk state.
LOADED_SOURCE_SHA256 = _observed_sources()


def _runtime_dependencies():
    import torch
    import numpy
    import av

    if tuple((name, module.__version__) for name, module in
             (("torch", torch), ("numpy", numpy), ("av", av))) != BLEND_DEPENDENCIES:
        raise RuntimeError("Blend runtime dependency versions are outside the governed contract")
    if any(argument.split("=", 1)[0] == "--fp16-intermediates" for argument in sys.argv):
        raise RuntimeError("Blend does not permit FP16 intermediates")
    return torch


class ConditioningLayersNormalizedBlend:
    """One CONDITIONING collection boundary; only the exact-3 route is registered."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"conditioning": ("CONDITIONING",)}}

    RETURN_TYPES = ("CONDITIONING",)
    FUNCTION = "prepare"
    CATEGORY = "conditioning/conditioning_layers"

    @classmethod
    def IS_CHANGED(cls, conditioning):
        if not verify_blend_component_source():
            raise RuntimeError("Blend implementation source identity is unavailable or changed")
        # ComfyUI separately keys linked input identities. This additional key
        # invalidates preparation caching on a governed algorithm/source change.
        return blend_component_identity().implementation_fingerprint

    def prepare(self, conditioning):
        torch = _runtime_dependencies()
        from comfy import model_management

        if not verify_blend_component_source():
            raise RuntimeError("Blend implementation source identity is unavailable or changed")
        if model_management.intermediate_dtype() != torch.float32:
            raise ValueError("Blend requires binary32 intermediate execution")
        if type(conditioning) not in (list, tuple) or len(conditioning) != 3:
            raise ValueError("Blend preparation requires exactly three conditioning entries")
        masks = []
        strengths = []
        for entry in conditioning:
            if type(entry) not in (list, tuple) or len(entry) != 2 or type(entry[1]) is not dict:
                raise ValueError("Malformed ordinary conditioning entry")
            prompt, metadata = entry
            if not isinstance(prompt, torch.Tensor) or prompt.ndim != 3 or prompt.shape[0] != 1:
                raise ValueError("Blend requires batch-one ordinary prompt conditioning")
            if not bool(torch.isfinite(prompt).all()):
                raise ValueError("Blend requires finite prompt conditioning")
            if (not {"mask", "mask_strength", "set_area_to_bounds"} <= metadata.keys()
                    or set(metadata) - set(blend_node_contract()["permitted_metadata"])
                    or metadata["set_area_to_bounds"] is not False):
                raise ValueError("Blend rejects area strength, hooks, scheduling, or ungoverned metadata")
            mask = metadata["mask"]
            if not isinstance(mask, torch.Tensor) or mask.dtype != torch.float32 or tuple(mask.shape) != (1, 128, 128):
                raise ValueError("Blend requires binary32 batch-one 128x128 masks without resizing")
            masks.append(tuple(recover_sample_code(value) for value in mask.detach().to(device="cpu").reshape(-1).tolist()))
            strengths.append(metadata["mask_strength"])
        prepared = [[], [], []]
        # Each sample uses exact integers. No floating F*S, division, tensor
        # multiplication, dtype cast, or device operation decides support.
        for codes in zip(*masks):
            weights = normalize_sample_codes_bits(codes, tuple(strengths))
            for ordinal, weight in enumerate(weights):
                prepared[ordinal].append(weight)
        result = []
        for ordinal, (prompt, metadata) in enumerate(conditioning):
            output = metadata.copy()
            # Install already-rounded IEEE bits without floating conversion.
            output["mask"] = torch.tensor(prepared[ordinal], dtype=torch.int32, device="cpu").view(torch.float32).reshape(1, 128, 128)
            output["mask_strength"] = 1.0
            result.append([prompt, output])
        return (result,)


def blend_runtime_dtype_available() -> bool:
    """Check this numerical component's pinned dependencies and dtype contract."""
    try:
        torch = _runtime_dependencies()
        from comfy import model_management

        return model_management.intermediate_dtype() == torch.float32
    except Exception:
        return False
