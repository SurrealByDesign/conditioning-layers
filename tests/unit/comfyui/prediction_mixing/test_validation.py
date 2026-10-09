from __future__ import annotations

from dataclasses import replace
import unittest

from conditioning_layers.adapters.prediction_mixing import OverlapAssessment
from conditioning_layers.comfyui.prediction_mixing import (
    CANONICAL_COMFYUI_INVENTORY,
    FieldStagingMap,
    RuntimeGenerationSettings,
    generate_prediction_mixing_workflow,
)

from test_graph import codes, make_plan, make_staging


SETTINGS = RuntimeGenerationSettings(
    seed=18472639,
    output_filename_prefix="conditioning-layers/document-1/request-1",
    execution_request_id="request-1",
)


def generate(plan, inventory=CANONICAL_COMFYUI_INVENTORY, staging=None, settings=SETTINGS):
    return generate_prediction_mixing_workflow(
        plan,
        inventory,
        settings,
        staging or make_staging(
            tuple(item.layer_id for item in plan.active_regional_conditions)
        ),
    )


class TranslationAndCountValidationTests(unittest.TestCase):
    def test_translation_plan_is_required(self) -> None:
        result = generate_prediction_mixing_workflow(
            None,
            CANONICAL_COMFYUI_INVENTORY,
            SETTINGS,
            FieldStagingMap({}),
        )
        self.assertIn("workflow.translation_required", codes(result.errors))

    def test_zero_and_more_than_two_active_layers_fail(self) -> None:
        plan = make_plan()
        zero = replace(
            plan,
            active_layer_count=0,
            active_regional_conditions=(),
            field_profiles=(),
            provenance_inputs=replace(plan.provenance_inputs, layers=()),
            overlap_assessment=None,
        )
        third_condition = replace(
            plan.active_regional_conditions[0],
            layer_id="c",
            field_profile=replace(plan.field_profiles[0], layer_id="c", relative_path="fields/c.png", checksum="c" * 64),
        )
        three = replace(
            plan,
            active_layer_count=3,
            active_regional_conditions=plan.active_regional_conditions + (third_condition,),
        )
        self.assertIn("workflow.active_layer_count", codes(generate(zero, staging=FieldStagingMap({})).errors))
        self.assertIn("workflow.active_layer_count", codes(generate(three).errors))

    def test_two_layer_plan_requires_certified_no_overlap(self) -> None:
        invalid = replace(
            make_plan(), overlap_assessment=OverlapAssessment.OVERLAP_PRESENT
        )
        self.assertIn("workflow.translation_required", codes(generate(invalid).errors))

    def test_mismatched_execution_profile_fails(self) -> None:
        plan = make_plan()
        invalid = replace(
            plan,
            execution_profile=replace(plan.execution_profile, output_width=768),
        )
        self.assertIn("workflow.inventory_profile", codes(generate(invalid).errors))


class InventoryValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = make_plan()

    def test_unsupported_comfyui_profile(self) -> None:
        inventory = replace(
            CANONICAL_COMFYUI_INVENTORY,
            comfyui_profile_identifier="unsupported",
        )
        self.assertIn("workflow.inventory_profile", codes(generate(self.plan, inventory).errors))

    def test_missing_required_component_declaration(self) -> None:
        inventory = replace(
            CANONICAL_COMFYUI_INVENTORY,
            required_node_class_names=CANONICAL_COMFYUI_INVENTORY.required_node_class_names[:-1],
        )
        self.assertIn("workflow.component_inventory", codes(generate(self.plan, inventory).errors))

    def test_wrong_model_encoder_and_vae_filenames(self) -> None:
        for field_name in (
            "model_filename",
            "text_encoder_filename",
            "vae_filename",
        ):
            with self.subTest(field_name=field_name):
                inventory = replace(
                    CANONICAL_COMFYUI_INVENTORY,
                    **{field_name: "wrong.safetensors"},
                )
                self.assertIn("workflow.component_inventory", codes(generate(self.plan, inventory).errors))

    def test_sampler_profile_cannot_be_overridden(self) -> None:
        inventory = replace(CANONICAL_COMFYUI_INVENTORY, steps=9)
        self.assertIn("workflow.component_inventory", codes(generate(self.plan, inventory).errors))


class StagingAndRuntimeValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = make_plan()

    def test_missing_and_extra_staged_fields(self) -> None:
        missing = FieldStagingMap({"a": "inputs/a.png"})
        extra = FieldStagingMap(
            {"a": "inputs/a.png", "b": "inputs/b.png", "c": "inputs/c.png"}
        )
        self.assertIn("workflow.field_staging_missing", codes(generate(self.plan, staging=missing).errors))
        self.assertIn("workflow.field_staging_extra", codes(generate(self.plan, staging=extra).errors))

    def test_unsafe_staged_filenames(self) -> None:
        for filename in (
            "../a.png",
            "C:/inputs/a.png",
            "/inputs/a.png",
            "inputs\\a.png",
            "inputs/a.jpg",
        ):
            with self.subTest(filename=filename):
                staging = FieldStagingMap({"a": filename, "b": "inputs/b.png"})
                self.assertIn("workflow.field_staging_unsafe", codes(generate(self.plan, staging=staging).errors))

    def test_duplicate_staged_filename_is_rejected(self) -> None:
        staging = FieldStagingMap({"a": "inputs/shared.png", "b": "inputs/shared.png"})
        self.assertIn("workflow.field_staging_unsafe", codes(generate(self.plan, staging=staging).errors))

    def test_seed_prefix_and_request_id_are_validated(self) -> None:
        cases = (
            replace(SETTINGS, seed=-1),
            replace(SETTINGS, output_filename_prefix="../outside"),
            replace(SETTINGS, execution_request_id="bad/request"),
        )
        for settings in cases:
            with self.subTest(settings=settings):
                self.assertIn("workflow.runtime_settings", codes(generate(self.plan, settings=settings).errors))


if __name__ == "__main__":
    unittest.main()

