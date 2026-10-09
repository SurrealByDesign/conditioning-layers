"""Offline synthetic authored PNG fixture; never a generated tensor artifact."""

import hashlib
from pathlib import Path
import struct
import zlib

from conditioning_layers.adapters.prediction_mixing.blend import translate_prediction_mixing_blend
from conditioning_layers.assets import FieldRelationshipInput, inspect_field_relationships, to_field_asset_profile
from conditioning_layers.comfyui.prediction_mixing.models import FieldStagingMap, RuntimeGenerationSettings
from conditioning_layers.domain import (
    COMPOSITION_POLICY_PROTOTYPE_VERSION, NORMALIZED_BLEND, PREDICTION_MIXING_ADAPTER_ID,
    ConditioningDocument, InfluenceFieldAssetReference, PromptLayer,
)


def png(samples, rgb=False):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    channels = 3 if rgb else 1
    data = bytes(value for sample in samples for value in (sample,) * channels)
    stride = 128 * channels
    rows = b"".join(b"\0" + data[index:index + stride] for index in range(0, len(data), stride))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 128, 128, 8, 2 if rgb else 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def blend_fixture(root, *, strengths=(1.0, 0.1, 1.0), order=(0, 1, 2), rgb=False, disjoint=False):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    layers = []
    for ordinal, letter in enumerate("abc"):
        samples = bytes((ordinal + 1) * (pixel % 64) if not disjoint else
                        (127 if pixel % 4 == ordinal else 0) for pixel in range(128 * 128))
        data = png(samples, rgb)
        (root / f"{letter}.png").write_bytes(data)
        layers.append(PromptLayer(letter, letter.upper(), f"regional prompt {letter}", strength=strengths[ordinal],
            influence_field=InfluenceFieldAssetReference(f"{letter}.png", hashlib.sha256(data).hexdigest())))
    document = ConditioningDocument(
        COMPOSITION_POLICY_PROTOTYPE_VERSION, "offline-blend-fixture", "Document context", tuple(layers[i] for i in order),
        PREDICTION_MIXING_ADAPTER_ID, composition_policy=NORMALIZED_BLEND.reference,
    )
    inspection = inspect_field_relationships(root, tuple(FieldRelationshipInput(layer, index)
        for index, layer in enumerate(document.layers)))
    profiles = tuple(to_field_asset_profile(item) for item in inspection.fields)
    result = translate_prediction_mixing_blend(document, inspection.certificate, profiles)
    if result.plan is None:
        raise AssertionError(result.findings)
    settings = RuntimeGenerationSettings(1234567, "conditioning-layers-p3c/offline", "p3c-offline")
    staging = FieldStagingMap({layer.layer_id: f"conditioning-layers/offline/{layer.layer_id}.png" for layer in document.layers})
    return document, inspection, profiles, result.plan, settings, staging
