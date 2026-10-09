from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui.prediction_mixing.blend import (
    BLEND_GRAPH_PERMITTED_CLASSES, EXACT_THREE_BLEND_REALIZATION, INVENTORY,
    fingerprint_authority, fingerprint_blend_graph, fingerprint_realization_binding,
    generate_prediction_mixing_blend_workflow, validate_blend_artifact,
    verify_permitted_class_authority, verify_realization_binding,
)
from conditioning_layers.comfyui.prediction_mixing.blend_component import BLEND_NODE_CLASS
from conditioning_layers.comfyui.prediction_mixing.multi_layer.canonical import canonical_bytes
from conditioning_layers.comfyui.prediction_mixing.multi_layer import generate_prediction_mixing_multi_layer_workflow
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tooling"))
from blend_fixture import blend_fixture


def generate(data, **kwargs):
    document, _, _, plan, settings, staging = data
    return generate_prediction_mixing_blend_workflow(plan, INVENTORY, settings, staging,
        document_id=document.document_id, **kwargs)


class BlendGraphTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        for target in ("socket.socket", "urllib.request.urlopen", "http.client.HTTPConnection", "subprocess.Popen"):
            guard = patch(target, side_effect=AssertionError("P3C is offline only"))
            guard.start()
            self.addCleanup(guard.stop)
        self.data = blend_fixture(self.temporary.name)

    def artifact(self, data=None, **kwargs):
        result = generate(self.data if data is None else data, **kwargs)
        self.assertTrue(result.generated, result.errors)
        return result.artifact

    def test_deterministic_successor_graph_has_exact_boundary_and_topology(self):
        artifact = self.artifact()
        self.assertEqual(canonical_bytes(artifact), canonical_bytes(self.artifact()))
        graph = artifact.to_api_graph()
        self.assertEqual(tuple(graph), tuple(str(i) for i in range(1, 21)))
        self.assertEqual(len(graph), 20)
        self.assertEqual(sum(isinstance(v, list) for node in graph.values() for v in node["inputs"].values()), 22)
        self.assertEqual(graph["13"]["inputs"], {"conditioning_1": ["10", 0], "conditioning_2": ["11", 0]})
        self.assertEqual(graph["14"]["inputs"], {"conditioning_1": ["13", 0], "conditioning_2": ["12", 0]})
        self.assertEqual(graph["15"], {"class_type": BLEND_NODE_CLASS, "inputs": {"conditioning": ["14", 0]}})
        self.assertEqual(graph["17"]["class_type"], "KSampler")
        self.assertEqual(graph["17"]["inputs"]["positive"], ["15", 0])
        self.assertEqual(graph["20"]["class_type"], "SaveImage")
        self.assertEqual(artifact.graph_format_version, "prediction-mixing.prototype.v3")
        self.assertEqual(artifact.provenance_inputs.generator_version_identifier, "conditioning-layers.comfyui-generator.v3")
        self.assertEqual(validate_blend_artifact(artifact, artifact.provenance_inputs, INVENTORY), ())
        self.assertFalse(generate_prediction_mixing_multi_layer_workflow(self.data[3], INVENTORY, self.data[4], self.data[5],
            document_id=self.data[0].document_id).generated)

    def test_permitted_class_authority_is_separate_from_frozen_inventory(self):
        artifact = self.artifact()
        self.assertEqual(len(INVENTORY.required_node_class_names), 11)
        self.assertNotIn(BLEND_NODE_CLASS, INVENTORY.required_node_class_names)
        self.assertEqual(artifact.required_host_components, INVENTORY.required_node_class_names + (BLEND_NODE_CLASS,))
        self.assertEqual(verify_permitted_class_authority(BLEND_GRAPH_PERMITTED_CLASSES, INVENTORY, artifact.canonical_graph), ())
        changed = replace(BLEND_GRAPH_PERMITTED_CLASSES, project_component_class="InventedMathNode")
        changed = replace(changed, fingerprint=fingerprint_authority(changed))
        self.assertFalse(generate(self.data, permitted_class_authority=changed).generated)
        changed_inventory = replace(INVENTORY, required_node_class_names=INVENTORY.required_node_class_names + (BLEND_NODE_CLASS,))
        self.assertTrue(verify_permitted_class_authority(BLEND_GRAPH_PERMITTED_CLASSES, changed_inventory))

    def test_source_strength_base_and_layer_order_survive_graph_projection(self):
        strengths = (5e-324, 1e-37, 0.0)
        data = blend_fixture(self.temporary.name, strengths=strengths, order=(2, 0, 1))
        artifact = self.artifact(data)
        graph = artifact.to_api_graph()
        self.assertEqual(tuple(graph[str(i)]["inputs"]["strength"] for i in (10, 11, 12)), (0.0, 5e-324, 1e-37))
        self.assertTrue(all(graph[str(i)]["inputs"]["set_cond_area"] == "default" for i in (10, 11, 12)))
        self.assertEqual(tuple(item.layer_id for item in artifact.provenance_inputs.active_layers), ("c", "a", "b"))
        self.assertTrue(all(graph[str(i)]["inputs"]["text"].startswith("Document context\n\n") for i in (3, 4, 5)))
        self.assertEqual(graph["6"]["inputs"]["text"], "")
        self.assertEqual(sum(node["class_type"] == "CLIPTextEncode" for node in graph.values()), 4)
        self.assertNotEqual(artifact.graph_fingerprint, self.artifact().graph_fingerprint)

    def test_self_consistent_component_or_binding_forgery_fails_closed(self):
        binding = EXACT_THREE_BLEND_REALIZATION
        identity = replace(binding.project_component_identity, implementation_fingerprint="0" * 64)
        for changed in (
            replace(binding, project_component_identity=identity),
            replace(binding, exact_cardinality=4),
            replace(binding, exact_cardinality=3.0),
            replace(binding, project_component_availability_required=False),
            replace(binding, project_component_availability_required=1),
        ):
            changed = replace(changed, fingerprint=fingerprint_realization_binding(changed))
            self.assertTrue(verify_realization_binding(changed, self.data[3], INVENTORY))
            self.assertFalse(generate(self.data, binding=changed).generated)
        with patch("conditioning_layers.comfyui.prediction_mixing.blend.authority.REGISTERED_BLEND_REALIZATION_BINDINGS", ()):
            self.assertFalse(generate(self.data).generated)

    def test_graph_provenance_and_class_tampering_cannot_be_rehashed(self):
        artifact = self.artifact()
        for node, key, value in (("15", "conditioning", ["13", 0]), ("17", "positive", ["14", 0]),
                                 ("10", "strength", 1.0e-37), ("16", "width", 512), ("3", "text", "forged")):
            graph = artifact.to_api_graph()
            graph[node]["inputs"][key] = value
            changed = replace(artifact, canonical_graph=graph)
            changed = replace(changed, graph_fingerprint=fingerprint_blend_graph(changed))
            self.assertTrue(validate_blend_artifact(changed, changed.provenance_inputs, INVENTORY))
        graph = artifact.to_api_graph()
        graph["15"]["class_type"] = "ArbitraryMath"
        changed = replace(artifact, canonical_graph=graph)
        self.assertTrue(validate_blend_artifact(changed, changed.provenance_inputs, INVENTORY))
        for name, value in (("composition_policy_version", True), ("project_component_implementation_fingerprint", "0" * 64),
                            ("permitted_class_authority_fingerprint", "0" * 64)):
            provenance = replace(artifact.provenance_inputs, **{name: value})
            self.assertTrue(validate_blend_artifact(artifact, provenance, INVENTORY))


if __name__ == "__main__":
    unittest.main()
