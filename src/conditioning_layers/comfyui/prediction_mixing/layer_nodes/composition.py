"""Pure Node System Phase 1 composition over recovered 8-bit field codes.

The only rule added here is FIXED ownership:

* A FIXED layer owns every sample where its stored field code is positive,
  whatever its Strength. FIXED fields must be disjoint, as under the retained
  No Overlap policy; layer order grants no priority, so an overlap fails.
* At a FIXED-owned sample every other layer's code is treated as zero.
  Elsewhere all FIXED codes are already zero and BLENDED layers share it.

Every sample is then prepared by the retained exact normalization,
`normalize_sample_codes_bits`: u_i = F_i * S_i and w_i = u_i / sum(u) at
positive support, rounded once to binary32; zero support gives zero weights
(no Prompt Layer contribution, nothing fills it). A FIXED owner therefore
has weight 1, or 0 when its Strength is 0. All-BLENDED input reaches the
retained function unchanged. No count or maximum is assumed.
"""

from __future__ import annotations

import math

from conditioning_layers.comfyui.prediction_mixing.blend_preparation import normalize_sample_codes_bits

from .models import LayerMode


class LayerCompositionError(ValueError):
    """The layers are outside Phase 1 composition semantics; nothing is prepared."""


def fixed_overlaps(planes, modes) -> dict[tuple[int, int], int]:
    """Count shared positive samples for each overlapping pair of FIXED layers."""
    fixed = tuple(index for index, mode in enumerate(modes) if mode is LayerMode.FIXED)
    counts: dict[tuple[int, int], int] = {}
    if len(fixed) < 2:
        return counts
    for codes in zip(*(planes[index] for index in fixed)):
        owners = tuple(fixed[position] for position, code in enumerate(codes) if code)
        for position, first in enumerate(owners):
            for second in owners[position + 1:]:
                counts[(first, second)] = counts.get((first, second), 0) + 1
    return counts


def compose_field_codes(planes, strengths, modes, labels=None) -> tuple[tuple[int, ...], ...]:
    """Return per-layer binary32 bit patterns for equal-length ordered code planes."""
    count = len(planes)
    labels = tuple(str(ordinal) for ordinal in range(1, count + 1)) if labels is None else tuple(labels)
    if count == 0 or len(strengths) != count or len(modes) != count or len(labels) != count:
        raise LayerCompositionError("Composition requires one field, Strength and mode per layer")
    if any(type(mode) is not LayerMode for mode in modes):
        raise LayerCompositionError("Every layer mode must be BLENDED or FIXED")
    size = len(planes[0])
    for label, plane, strength in zip(labels, planes, strengths):
        if type(strength) not in (int, float) or not math.isfinite(strength) or not 0 <= strength <= 1:
            raise LayerCompositionError(f"Layer {label}: Strength must be a finite number in [0, 1]")
        if len(plane) != size or size == 0:
            raise LayerCompositionError("Every layer field must have the same nonzero sample count")
        # Validate before FIXED ownership can zero any sample.
        if any(type(code) is not int or not 0 <= code <= 255 for code in plane):
            raise LayerCompositionError(f"Layer {label}: field samples must be 8-bit codes")
        if not any(plane):
            raise LayerCompositionError(
                f"Layer {label}: field has no positive sample and can never contribute; disable the layer instead")
    overlaps = fixed_overlaps(planes, modes)
    if overlaps:
        detail = "; ".join(f"layers {labels[first]} and {labels[second]} share {shared} "
                           + ("sample" if shared == 1 else "samples")
                           for (first, second), shared in sorted(overlaps.items()))
        raise LayerCompositionError(
            f"FIXED fields must not overlap ({detail}). FIXED ownership is exclusive and layer "
            "order carries no priority: make the FIXED fields disjoint or set one layer to BLENDED")
    strengths = tuple(strengths)
    fixed = tuple(index for index, mode in enumerate(modes) if mode is LayerMode.FIXED)
    prepared: list[list[int]] = [[] for _ in range(count)]
    cache: dict[tuple[int, ...], tuple[int, ...]] = {}
    for codes in zip(*planes):
        owner = next((index for index in fixed if codes[index]), None)
        if owner is not None:
            codes = tuple(code if index == owner else 0 for index, code in enumerate(codes))
        weights = cache.get(codes)
        if weights is None:
            weights = cache[codes] = normalize_sample_codes_bits(codes, strengths)
        for layer, weight in zip(prepared, weights):
            layer.append(weight)
    return tuple(tuple(layer) for layer in prepared)
