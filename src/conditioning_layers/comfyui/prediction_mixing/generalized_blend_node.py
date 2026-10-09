"""Offline generalized Blend node runtime; importing this file never imports ComfyUI.

No loader registers this class: ADR-0028 Slices A-C construct it only through
offline fixtures. The reused `normalize_sample_codes_bits` is N-generic; its
docstring's exactly-three sentence is stale exact-3-era text kept unchanged
under the retained ADR-0026 source anchor.
"""

import sys

from .blend_component import BLEND_DEPENDENCIES
from .blend_preparation import normalize_sample_codes_bits, recover_sample_code
from .generalized_blend_component import (
    generalized_blend_component_identity, generalized_blend_node_contract,
    verify_generalized_blend_component_source, _observed_sources,
)

# Captured when the runtime class is loaded, independently of later disk state.
LOADED_SOURCE_SHA256 = _observed_sources()


def _runtime_dependencies():
    import torch
    import numpy
    import av

    if tuple((name, module.__version__) for name, module in
             (("torch", torch), ("numpy", numpy), ("av", av))) != BLEND_DEPENDENCIES:
        raise RuntimeError("Generalized Blend runtime dependency versions are outside the governed contract")
    if any(argument.split("=", 1)[0] == "--fp16-intermediates" for argument in sys.argv):
        raise RuntimeError("Generalized Blend does not permit FP16 intermediates")
    return torch


class ConditioningLayersGeneralizedNormalizedBlend:
    """One CONDITIONING collection plus explicit trusted expected-count authority."""

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"conditioning": ("CONDITIONING",), "expected_count": ("INT", {"min": 1})}}

    RETURN_TYPES = ("CONDITIONING",)
    FUNCTION = "prepare"
    CATEGORY = "conditioning/conditioning_layers"

    @classmethod
    def IS_CHANGED(cls, conditioning, expected_count):
        if not verify_generalized_blend_component_source():
            raise RuntimeError("Generalized Blend implementation source identity is unavailable or changed")
        # Linked input identities are keyed separately. This key invalidates
        # preparation caching on a governed algorithm/source change.
        return generalized_blend_component_identity().implementation_fingerprint

    def prepare(self, conditioning, expected_count):
        torch = _runtime_dependencies()
        from comfy import model_management

        if not verify_generalized_blend_component_source():
            raise RuntimeError("Generalized Blend implementation source identity is unavailable or changed")
        if model_management.intermediate_dtype() != torch.float32:
            raise ValueError("Generalized Blend requires binary32 intermediate execution")
        if type(expected_count) is not int or expected_count <= 0:
            raise ValueError("Generalized Blend requires a trusted positive integer expected count")
        # The received collection is checked against, never authorizes, its count.
        if type(conditioning) not in (list, tuple) or len(conditioning) != expected_count:
            raise ValueError("Generalized Blend conditioning count differs from its trusted expected count")
        masks = []
        strengths = []
        for entry in conditioning:
            if type(entry) not in (list, tuple) or len(entry) != 2 or type(entry[1]) is not dict:
                raise ValueError("Malformed ordinary conditioning entry")
            prompt, metadata = entry
            if not isinstance(prompt, torch.Tensor) or prompt.ndim != 3 or prompt.shape[0] != 1:
                raise ValueError("Generalized Blend requires batch-one ordinary prompt conditioning")
            if not bool(torch.isfinite(prompt).all()):
                raise ValueError("Generalized Blend requires finite prompt conditioning")
            if (not {"mask", "mask_strength", "set_area_to_bounds"} <= metadata.keys()
                    or set(metadata) - set(generalized_blend_node_contract()["permitted_metadata"])
                    or metadata["set_area_to_bounds"] is not False):
                raise ValueError("Generalized Blend rejects area strength, hooks, scheduling, or ungoverned metadata")
            mask = metadata["mask"]
            if not isinstance(mask, torch.Tensor) or mask.dtype != torch.float32 or tuple(mask.shape) != (1, 128, 128):
                raise ValueError("Generalized Blend requires binary32 batch-one 128x128 masks without resizing")
            masks.append(tuple(recover_sample_code(value) for value in mask.detach().to(device="cpu").reshape(-1).tolist()))
            strengths.append(metadata["mask_strength"])
        prepared = [[] for _ in range(expected_count)]
        # Each sample uses exact integers. No floating F*S, division, tensor
        # multiplication, dtype cast, or device operation decides support.
        for codes in zip(*masks, strict=True):
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
