"""Transient ADR-0036/ADR-0038 preview. No graph execution, tensors, storage or admission."""

import asyncio
import json

from conditioning_layers.comfyui.prediction_mixing.layer_nodes.composition import (
    compose_field_codes, fixed_overlaps,
)
from conditioning_layers.comfyui.prediction_mixing.layer_nodes.models import LayerDescriptor, LayerMode

PREVIEW_PATH = "/conditioning-layers/composition-preview"
MAX_REQUEST_BYTES = 8 * 1024 * 1024  # Transport budget, never a layer-count rule.
LEGACY_COMPOSE, GROUPED_COMPOSE = "ConditioningLayersCompose", "ConditioningLayersComposeGroups"
_REGISTERED = False


def preview_composition(payload):
    """Return selected prepared IEEE bits, or FIXED conflict cells; never mutate input."""
    if type(payload) is not dict or set(payload) != {"compose", "layers", "selected"}:
        raise ValueError("Expected Compose type, layers and selected layer identity")
    if type(payload["compose"]) is not str or payload["compose"] not in (LEGACY_COMPOSE, GROUPED_COMPOSE):
        raise ValueError("Unsupported Compose type")
    grouped = payload["compose"] == GROUPED_COMPOSE
    layers = payload["layers"]
    if type(layers) is not list or not layers:
        raise ValueError("The composition has no layers")
    ids, active, planes = set(), [], []
    for item in layers:
        if type(item) is not dict or set(item) != {"id", "strength", "mode", "enabled", "group", "codes"}:
            raise ValueError("Unresolved layer metadata")
        layer = LayerDescriptor(item["id"], None, None, item["strength"], item["mode"], item["enabled"], item["group"])
        if layer.layer_id in ids:
            raise ValueError("A layer cannot occur twice in one stack")
        ids.add(layer.layer_id)
        if layer.blend_group and not grouped:
            # Legacy Compose rejects every saved assignment, including disabled and FIXED layers.
            raise ValueError(f"Layer {layer.layer_id}: group {json.dumps(layer.blend_group)} needs Compose Blend Groups")
        if not layer.enabled:
            continue  # Disabled fields are neither read nor validated by Compose.
        codes = item["codes"]
        if (type(codes) is not list or len(codes) != 16384
                or any(type(code) is not int or not 0 <= code <= 255 for code in codes)):
            raise ValueError(f"Layer {layer.layer_id}: expected 128x128 exact integer codes")
        if not any(codes):
            raise ValueError(f"Layer {layer.layer_id}: field has no positive sample; disable the layer instead")
        active.append(layer)
        planes.append(tuple(codes))
    if type(payload["selected"]) is not str or payload["selected"] not in ids:
        raise ValueError("Selected layer is absent from the stack")
    if not active:
        raise ValueError("Compose has no enabled layer")
    modes = tuple(layer.mode for layer in active)
    conflicts = fixed_overlaps(planes, modes)
    if conflicts:
        fixed = [i for i, mode in enumerate(modes) if mode is LayerMode.FIXED]
        cells = [p for p in range(16384) if sum(planes[i][p] > 0 for i in fixed) > 1]
        pairs = [{"layers": [active[a].layer_id, active[b].layer_id], "count": count}
                 for (a, b), count in sorted(conflicts.items())]
        return {"status": "conflict", "cells": cells, "pairs": pairs}
    strengths, labels = tuple(layer.strength for layer in active), tuple(layer.layer_id for layer in active)
    if grouped:
        # Lazy, as in the node: a grouped import failure cannot disable legacy previews.
        from conditioning_layers.comfyui.prediction_mixing.layer_nodes.grouped_composition import (
            compose_grouped_field_codes,
        )
        prepared = compose_grouped_field_codes(tuple(planes), strengths, modes,
                                               tuple(layer.blend_group for layer in active), labels=labels)
    else:
        prepared = compose_field_codes(tuple(planes), strengths, modes, labels=labels)
    selected = next((i for i, layer in enumerate(active) if layer.layer_id == payload["selected"]), None)
    return {"status": "ready", "bits": list(prepared[selected]) if selected is not None else [0] * 16384,
            "disabled": selected is None}


def register_preview_route():
    """Optional route, isolated from all generation and document routes."""
    global _REGISTERED
    if _REGISTERED:
        return
    from aiohttp import web
    from server import PromptServer

    gate = asyncio.Semaphore(1)

    @PromptServer.instance.routes.post(PREVIEW_PATH)
    async def preview(request):
        try:
            # Bound bytes independently of the host's larger upload allowance.
            body = bytearray()
            async for chunk in request.content.iter_chunked(65536):
                body.extend(chunk)
                if len(body) > MAX_REQUEST_BYTES:
                    raise ValueError("Preview transport budget exceeded (8 MiB)")
            payload = json.loads(body)
            async with gate:
                result = await asyncio.to_thread(preview_composition, payload)
            return web.json_response(result)
        except (ValueError, TypeError, OverflowError) as error:
            return web.json_response({"status": "unavailable", "message": str(error)}, status=400)

    _REGISTERED = True
