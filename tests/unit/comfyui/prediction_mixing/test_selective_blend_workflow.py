"""Static native API serialization and semantic compatibility (no frontend simulation)."""
from dataclasses import replace
import json
import unittest

from conditioning_layers.comfyui.prediction_mixing import DEFAULT_SUPPORTED_PROFILE, RuntimeGenerationSettings
from conditioning_layers.comfyui.prediction_mixing.layer_nodes import (
    LayerMode, LayerWorkflowSpec, build_layer_node_workflow, layer_workflow_semantics,
    fingerprint_semantics, validate_layer_node_workflow,
)

INVENTORY = DEFAULT_SUPPORTED_PROFILE.inventory
SETTINGS = RuntimeGenerationSettings(18472639, "conditioning-layers/groups-test")


class GroupWorkflowTests(unittest.TestCase):
    def specs(self):
        return tuple(LayerWorkflowSpec(f"prompt {i}", f"field{i}.png", blend_group=g)
                     for i,g in enumerate(("material", "material", "environment")))

    def test_api_round_trip_preserves_membership_and_explicit_node(self):
        graph = build_layer_node_workflow(self.specs(), INVENTORY, SETTINGS, grouped=True)
        restored = json.loads(json.dumps(graph))
        validate_layer_node_workflow(restored)
        self.assertEqual(restored, graph)
        semantics = layer_workflow_semantics(restored)
        self.assertEqual([l["blend_group"] for l in semantics["layers"]], ["material", "material", "environment"])
        self.assertEqual(semantics["composition"], "strongest-member-groups.v1")
        self.assertEqual(restored["16"]["class_type"], "ConditioningLayersComposeGroups")

    def test_old_and_explicit_empty_workflows_have_identical_legacy_semantics(self):
        specs = tuple(replace(l, blend_group="") for l in self.specs())
        original = build_layer_node_workflow(specs, INVENTORY, SETTINGS)
        loaded = json.loads(json.dumps(original))
        for node in loaded.values():
            if node["class_type"] == "ConditioningLayersLayer":
                self.assertNotIn("blend_group", node["inputs"])
                node["inputs"]["blend_group"] = ""
        validate_layer_node_workflow(loaded)
        self.assertEqual(layer_workflow_semantics(original), layer_workflow_semantics(loaded))
        self.assertEqual(fingerprint_semantics(layer_workflow_semantics(original)),
                         fingerprint_semantics(layer_workflow_semantics(loaded)))

    def test_no_silent_grouping_or_legacy_flattening(self):
        with self.assertRaisesRegex(ValueError, "Compose Blend Groups"):
            build_layer_node_workflow(self.specs(), INVENTORY, SETTINGS)
        graph = build_layer_node_workflow(self.specs(), INVENTORY, SETTINGS, grouped=True)
        graph["16"]["class_type"] = "ConditioningLayersCompose"
        with self.assertRaisesRegex(ValueError, "Compose Blend Groups"):
            layer_workflow_semantics(graph)

    def test_membership_changes_semantic_fingerprint_titles_do_not(self):
        graph = build_layer_node_workflow(self.specs(), INVENTORY, SETTINGS, grouped=True)
        original = fingerprint_semantics(layer_workflow_semantics(graph))
        graph["10"]["_meta"]["title"] = "any title"
        self.assertEqual(fingerprint_semantics(layer_workflow_semantics(graph)), original)
        graph["10"]["inputs"]["blend_group"] = "environment"
        self.assertNotEqual(fingerprint_semantics(layer_workflow_semantics(graph)), original)

    def test_duplicate_identity_and_invalid_membership_rejected(self):
        graph = build_layer_node_workflow(self.specs(), INVENTORY, SETTINGS, grouped=True)
        graph["14"]["inputs"]["layer"] = graph["13"]["inputs"]["layer"]
        with self.assertRaisesRegex(ValueError, "twice"):
            layer_workflow_semantics(graph)
        for bad in (None, ["one", "two"], " ", 1):
            graph = build_layer_node_workflow(self.specs(), INVENTORY, SETTINGS, grouped=True)
            graph["10"]["inputs"]["blend_group"] = bad
            with self.assertRaises(ValueError):
                layer_workflow_semantics(graph)

    def test_saved_disabled_and_fixed_values_are_preserved(self):
        specs = self.specs() + (LayerWorkflowSpec("fixed", "fixed.png", mode=LayerMode.FIXED, blend_group="retained"),
                                LayerWorkflowSpec("disabled", "off.png", enabled=False, blend_group="off"))
        graph = build_layer_node_workflow(specs, INVENTORY, SETTINGS, grouped=True)
        layers = layer_workflow_semantics(json.loads(json.dumps(graph)))["layers"]
        self.assertEqual((layers[-2]["mode"], layers[-2]["blend_group"]), ("FIXED", "retained"))
        self.assertEqual((layers[-1]["enabled"], layers[-1]["blend_group"]), (False, "off"))
