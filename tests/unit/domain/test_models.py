from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from conditioning_layers.domain import (
    CURRENT_PROTOTYPE_VERSION,
    PREDICTION_MIXING_ADAPTER_ID,
    ConditioningDocument,
    DuplicateLayerIdError,
    InfluenceFieldAssetReference,
    InvalidLayerPositionError,
    LayerNotFoundError,
    PromptLayer,
)


def make_layer(
    layer_id: str,
    *,
    visible: bool = True,
    strength: float = 1.0,
) -> PromptLayer:
    return PromptLayer(
        layer_id=layer_id,
        name=f"Layer {layer_id}",
        prompt_text=f"Prompt {layer_id}",
        visible=visible,
        strength=strength,
        influence_field=InfluenceFieldAssetReference(
            relative_path=f"assets/{layer_id}.png"
        ),
    )


def make_document(*layers: PromptLayer) -> ConditioningDocument:
    return ConditioningDocument(
        version=CURRENT_PROTOTYPE_VERSION,
        document_id="document-1",
        base_prompt="A coherent studio scene",
        layers=layers,
    )


class ConstructionTests(unittest.TestCase):
    def test_empty_document_with_base_prompt(self) -> None:
        document = make_document()

        self.assertEqual(document.base_prompt, "A coherent studio scene")
        self.assertEqual(document.layers, ())
        self.assertIsNone(document.selected_adapter_id)

    def test_one_prompt_layer(self) -> None:
        layer = make_layer("layer-1")

        document = make_document(layer)

        self.assertEqual(document.layers, (layer,))
        self.assertEqual(document.active_layers, (layer,))

    def test_multiple_saved_layers_include_disabled_layer(self) -> None:
        visible = make_layer("visible")
        disabled = make_layer("disabled", visible=False)

        document = make_document(visible, disabled)

        self.assertEqual(document.layers, (visible, disabled))
        self.assertEqual(document.active_layers, (visible,))

    def test_selected_adapter_may_be_absent_or_present(self) -> None:
        absent = make_document()
        present = ConditioningDocument(
            version=CURRENT_PROTOTYPE_VERSION,
            document_id="document-1",
            base_prompt="A coherent studio scene",
            selected_adapter_id=PREDICTION_MIXING_ADAPTER_ID,
            adapter_settings={},
        )

        self.assertIsNone(absent.selected_adapter_id)
        self.assertEqual(present.selected_adapter_id, PREDICTION_MIXING_ADAPTER_ID)
        self.assertEqual(dict(present.adapter_settings), {})

    def test_models_are_immutable(self) -> None:
        document = make_document()

        with self.assertRaises(FrozenInstanceError):
            document.base_prompt = "Changed"  # type: ignore[misc]


class LayerOperationTests(unittest.TestCase):
    def test_add_layer_appends_and_can_insert(self) -> None:
        first = make_layer("first")
        second = make_layer("second")

        appended = make_document().add_layer(first)
        inserted = appended.add_layer(second, position=0)

        self.assertEqual([layer.layer_id for layer in appended.layers], ["first"])
        self.assertEqual(
            [layer.layer_id for layer in inserted.layers],
            ["second", "first"],
        )

    def test_add_rejects_duplicate_id(self) -> None:
        document = make_document(make_layer("same"))

        with self.assertRaises(DuplicateLayerIdError):
            document.add_layer(make_layer("same"))

    def test_remove_layer(self) -> None:
        original = make_document(make_layer("first"), make_layer("second"))

        changed = original.remove_layer("first")

        self.assertEqual([layer.layer_id for layer in changed.layers], ["second"])
        self.assertEqual(
            [layer.layer_id for layer in original.layers],
            ["first", "second"],
        )

    def test_remove_missing_layer_raises(self) -> None:
        with self.assertRaises(LayerNotFoundError):
            make_document().remove_layer("missing")

    def test_duplicate_copies_properties_with_new_id_after_source(self) -> None:
        source = make_layer("source", visible=False, strength=0.4)
        document = make_document(source, make_layer("other"))

        changed = document.duplicate_layer("source", "copy")
        duplicate = changed.layers[1]

        self.assertEqual(
            [layer.layer_id for layer in changed.layers],
            ["source", "copy", "other"],
        )
        self.assertEqual(duplicate.name, source.name)
        self.assertEqual(duplicate.prompt_text, source.prompt_text)
        self.assertEqual(duplicate.visible, source.visible)
        self.assertEqual(duplicate.strength, source.strength)
        self.assertEqual(duplicate.influence_field, source.influence_field)

    def test_move_upward_and_downward_has_stable_exact_order(self) -> None:
        document = make_document(
            make_layer("a"),
            make_layer("b"),
            make_layer("c"),
        )

        upward = document.move_layer("c", 0)
        downward = upward.move_layer("c", 2)

        self.assertEqual([layer.layer_id for layer in upward.layers], ["c", "a", "b"])
        self.assertEqual(
            [layer.layer_id for layer in downward.layers],
            ["a", "b", "c"],
        )

    def test_move_rejects_out_of_range_position(self) -> None:
        with self.assertRaises(InvalidLayerPositionError):
            make_document(make_layer("a")).move_layer("a", 1)

    def test_toggle_visibility_and_update_strength(self) -> None:
        document = make_document(make_layer("a"))

        hidden = document.toggle_visibility("a")
        changed = hidden.update_strength("a", 0.25)

        self.assertFalse(changed.layers[0].visible)
        self.assertEqual(changed.layers[0].strength, 0.25)
        self.assertEqual(document.layers[0].strength, 1.0)

    def test_update_prompts_and_name_without_changing_identity(self) -> None:
        document = make_document(make_layer("a"))

        changed = (
            document.update_prompt_text("a", "A revised prompt")
            .update_layer_name("a", "Foreground")
            .update_base_prompt("A revised Base Prompt")
        )

        self.assertEqual(changed.layers[0].layer_id, "a")
        self.assertEqual(changed.layers[0].prompt_text, "A revised prompt")
        self.assertEqual(changed.layers[0].name, "Foreground")
        self.assertEqual(changed.base_prompt, "A revised Base Prompt")


if __name__ == "__main__":
    unittest.main()
