from __future__ import annotations

from dataclasses import replace
import unittest

from conditioning_layers.comfyui.prediction_mixing import (
    CANONICAL_COMFYUI_0280_INVENTORY,
    CANONICAL_COMFYUI_INVENTORY,
    COMFYUI_0280_NODE_SNAPSHOT,
    ProfileCompatibilityVerdict,
    RuntimeGenerationSettings,
    evaluate_graph_profile_compatibility,
    generate_prediction_mixing_workflow,
)

from test_graph import codes, make_plan, make_staging


def graph_for(layer_ids: tuple[str, ...]):
    plan = make_plan(layer_ids)
    result = generate_prediction_mixing_workflow(
        plan,
        CANONICAL_COMFYUI_0280_INVENTORY,
        RuntimeGenerationSettings(
            seed=18472639,
            output_filename_prefix="conditioning-layers/document-1/profile-test",
        ),
        make_staging(layer_ids),
    )
    assert result.artifact is not None, result.errors
    return result.artifact.to_api_graph()


class GraphProfileCompatibilityTests(unittest.TestCase):
    def test_one_and_two_layer_graphs_are_compatible(self) -> None:
        for layer_ids in (("a",), ("a", "b")):
            with self.subTest(layer_ids=layer_ids):
                result = evaluate_graph_profile_compatibility(
                    graph_for(layer_ids),
                    CANONICAL_COMFYUI_0280_INVENTORY,
                    COMFYUI_0280_NODE_SNAPSHOT,
                )
                self.assertTrue(result.supported, result.findings)
                self.assertIs(result.verdict, ProfileCompatibilityVerdict.COMPATIBLE)
                self.assertIn("profile.graph_compatible", codes(result.findings))

    def test_changed_input_missing_node_and_output_index_are_rejected(self) -> None:
        changed_input = graph_for(("a",))
        changed_input["1"]["inputs"]["unexpected"] = "value"
        missing_node = graph_for(("a",))
        missing_node["1"]["class_type"] = "MissingBuiltIn"
        changed_output = graph_for(("a",))
        sampler_id = next(
            key
            for key, node in changed_output.items()
            if node["class_type"] == "KSampler"
        )
        changed_output[sampler_id]["inputs"]["model"] = ["1", 9]
        cases = (
            (changed_input, "profile.node_contract_changed"),
            (missing_node, "profile.node_missing"),
            (changed_output, "profile.output_contract_changed"),
        )
        for graph, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                result = evaluate_graph_profile_compatibility(
                    graph,
                    CANONICAL_COMFYUI_0280_INVENTORY,
                    COMFYUI_0280_NODE_SNAPSHOT,
                )
                self.assertFalse(result.supported)
                self.assertIn(expected_code, codes(result.findings))

    def test_wrong_revision_and_semantic_uncertainty_block_support(self) -> None:
        graph = graph_for(("a", "b"))
        wrong_revision = replace(
            COMFYUI_0280_NODE_SNAPSHOT,
            comfyui_revision="f" * 40,
        )
        wrong = evaluate_graph_profile_compatibility(
            graph,
            CANONICAL_COMFYUI_0280_INVENTORY,
            wrong_revision,
        )
        self.assertFalse(wrong.supported)
        self.assertIn("profile.graph_incompatible", codes(wrong.findings))

        unresolved = replace(
            COMFYUI_0280_NODE_SNAPSHOT,
            unresolved_items=("manual semantic review pending",),
        )
        semantic = evaluate_graph_profile_compatibility(
            graph,
            CANONICAL_COMFYUI_0280_INVENTORY,
            unresolved,
        )
        self.assertTrue(semantic.structurally_compatible)
        self.assertFalse(semantic.supported)
        self.assertIs(
            semantic.verdict,
            ProfileCompatibilityVerdict.STRUCTURAL_SEMANTICS_UNRESOLVED,
        )
        self.assertIn("profile.semantic_contract_unresolved", codes(semantic.findings))


class InventoryProfileTests(unittest.TestCase):
    def test_historical_profile_is_unchanged_and_profiles_are_distinct(self) -> None:
        self.assertEqual(CANONICAL_COMFYUI_INVENTORY.expected_comfyui_version, "0.27.1")
        self.assertEqual(
            CANONICAL_COMFYUI_INVENTORY.expected_comfyui_revision,
            "c2638ce6c00e3426c48d56a775bc46e9a8464094",
        )
        self.assertNotEqual(
            CANONICAL_COMFYUI_INVENTORY.inventory_identifier,
            CANONICAL_COMFYUI_0280_INVENTORY.inventory_identifier,
        )
        for field in (
            "model_filename",
            "model_sha256",
            "text_encoder_filename",
            "text_encoder_sha256",
            "vae_filename",
            "vae_sha256",
            "sampler_name",
            "scheduler_name",
            "steps",
            "cfg",
            "denoise",
            "output_width",
            "output_height",
            "batch_size",
        ):
            self.assertEqual(
                getattr(CANONICAL_COMFYUI_INVENTORY, field),
                getattr(CANONICAL_COMFYUI_0280_INVENTORY, field),
            )

    def test_inventory_profile_mismatch_is_rejected(self) -> None:
        invalid = replace(
            CANONICAL_COMFYUI_0280_INVENTORY,
            expected_comfyui_revision=CANONICAL_COMFYUI_INVENTORY.expected_comfyui_revision,
        )
        plan = make_plan(("a",))
        result = generate_prediction_mixing_workflow(
            plan,
            invalid,
            RuntimeGenerationSettings(seed=1, output_filename_prefix="test/profile"),
            make_staging(("a",)),
        )
        self.assertIn("workflow.inventory_profile", codes(result.errors))


if __name__ == "__main__":
    unittest.main()
