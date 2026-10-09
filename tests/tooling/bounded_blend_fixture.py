"""Slice A authored-field fixtures and planning only; no graph or runtime work."""

from dataclasses import replace
import hashlib
from pathlib import Path

from blend_fixture import png
from conditioning_layers.adapters.prediction_mixing.blend import translate_prediction_mixing_blend
from conditioning_layers.assets import FieldRelationshipInput, inspect_field_relationships, to_field_asset_profile
from conditioning_layers.capabilities._bounded_blend import select_bounded_blend_eligibility
from conditioning_layers.domain import (
    COMPOSITION_POLICY_PROTOTYPE_VERSION, NORMALIZED_BLEND, PREDICTION_MIXING_ADAPTER_ID,
    ConditioningDocument, InfluenceFieldAssetReference, PromptLayer,
)


def bounded_document(root, count, *, order=None, disabled=False):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    layers = []
    for ordinal in range(count):
        data = png(bytes((ordinal + 1) * (pixel % 23) for pixel in range(128 * 128)))
        reference = f"field-{ordinal}.png"
        (root / reference).write_bytes(data)
        layers.append(PromptLayer(
            f"layer-{ordinal}", f"Layer {ordinal}", f"regional prompt {ordinal}",
            strength=(0.0, 0.1, 1.0, 5e-324)[ordinal % 4],
            influence_field=InfluenceFieldAssetReference(reference, hashlib.sha256(data).hexdigest()),
        ))
    ordered = tuple(layers[index] for index in (range(count) if order is None else order))
    if disabled:
        saved_only = PromptLayer("disabled", "Saved only", "unused", visible=False)
        ordered = (saved_only,) + tuple(row for index, layer in enumerate(ordered)
            for row in (layer, replace(saved_only, layer_id=f"disabled-{index}")))
    return ConditioningDocument(
        COMPOSITION_POLICY_PROTOTYPE_VERSION, "offline-bounded-blend", "Document context", ordered,
        PREDICTION_MIXING_ADAPTER_ID, composition_policy=NORMALIZED_BLEND.reference,
    )


def inspect_document(root, document):
    inspection = inspect_field_relationships(root, tuple(
        FieldRelationshipInput(layer, index) for index, layer in enumerate(document.layers)
        if layer.visible is True))
    return inspection, tuple(to_field_asset_profile(field) for field in inspection.fields)


def bounded_plan(root, count, **options):
    document = bounded_document(root, count, **options)
    entry = select_bounded_blend_eligibility(document)
    inspection, profiles = inspect_document(root, document)
    result = translate_prediction_mixing_blend(document, inspection.certificate, profiles, eligibility_entry=entry)
    if not result.translated:
        raise AssertionError(result.findings)
    return document, inspection, profiles, result
