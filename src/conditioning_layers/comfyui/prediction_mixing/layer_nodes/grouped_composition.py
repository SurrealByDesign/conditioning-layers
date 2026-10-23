"""Flat strongest-member groups, promoted from the EXP-0015 integer algorithm.

Global FIXED ownership is unchanged. Else w_i = (u_i/U_g)*(max_g(u)/sum_h max_h(u)).
Only the final exact ratio is rounded to binary32. No intermediate rounded masks,
epsilon, fallback, implicit contributor or group-level field is introduced.
"""
import math

from conditioning_layers.comfyui.prediction_mixing.blend_preparation import round_ratio_to_binary32_bits

from .composition import LayerCompositionError, compose_field_codes, fixed_overlaps
from .models import LayerMode, validate_blend_group


def compose_grouped_field_codes(planes, strengths, modes, groups=None, labels=None):
    """Prepare enabled-layer-major bits in authored order; caller excludes disabled layers."""
    count = len(planes)
    labels = tuple(str(i) for i in range(1, count + 1)) if labels is None else tuple(labels)
    groups = ("",) * count if groups is None else tuple(groups)
    if count == 0 or any(len(items) != count for items in (strengths, modes, groups, labels)):
        raise LayerCompositionError("Composition requires one field, Strength, mode and group per layer")
    if any(type(mode) is not LayerMode for mode in modes):
        raise LayerCompositionError("Every layer mode must be BLENDED or FIXED")
    for group in groups:
        validate_blend_group(group)
    keys = tuple(dict.fromkeys(group for group, mode in zip(groups, modes) if mode is LayerMode.BLENDED))
    if len(keys) <= 1:
        return compose_field_codes(planes, strengths, modes, labels)

    size = len(planes[0])
    for label, plane, strength in zip(labels, planes, strengths):
        if type(strength) not in (int, float) or not math.isfinite(strength) or not 0 <= strength <= 1:
            raise LayerCompositionError(f"Layer {label}: Strength must be a finite number in [0, 1]")
        if len(plane) != size or size == 0:
            raise LayerCompositionError("Every layer field must have the same nonzero sample count")
        # Validate every enabled plane before FIXED can suppress invalid samples.
        if any(type(code) is not int or not 0 <= code <= 255 for code in plane):
            raise LayerCompositionError(f"Layer {label}: field samples must be 8-bit codes")
        if not any(plane):
            raise LayerCompositionError(f"Layer {label}: field has no positive sample; disable the layer instead")
    conflicts = fixed_overlaps(planes, modes)
    if conflicts:
        detail = "; ".join(f"layers {labels[a]} and {labels[b]} share {n} samples"
                           for (a, b), n in sorted(conflicts.items()))
        raise LayerCompositionError(f"FIXED fields must not overlap ({detail}); ownership is global across groups")

    ratios = tuple(float(s).as_integer_ratio() for s in strengths)
    denominator = max(d for _, d in ratios)
    scales = tuple(n * (denominator // d) for n, d in ratios)
    members = tuple(tuple(i for i, (group, mode) in enumerate(zip(groups, modes))
                          if mode is LayerMode.BLENDED and group == key) for key in keys)
    fixed = tuple(i for i, mode in enumerate(modes) if mode is LayerMode.FIXED)
    output = [[] for _ in range(count)]
    cache = {}
    for codes in zip(*planes):
        weights = cache.get(codes)
        if weights is None:
            owner = next((i for i in fixed if codes[i] > 0), None)
            values = [0] * count
            if owner is not None:
                values[owner] = 0x3F800000 if strengths[owner] > 0 else 0
            else:
                products = tuple(code * scale for code, scale in zip(codes, scales))
                totals = tuple(sum(products[i] for i in group) for group in members)
                envelopes = tuple(max(products[i] for i in group) for group in members)
                total_envelope = sum(envelopes)
                for group, total, envelope in zip(members, totals, envelopes):
                    if total == 0:
                        continue
                    for i in group:
                        values[i] = round_ratio_to_binary32_bits(
                            products[i] * envelope, total * total_envelope)
            weights = cache[codes] = tuple(values)
        for row, weight in zip(output, weights):
            row.append(weight)
    return tuple(tuple(row) for row in output)
