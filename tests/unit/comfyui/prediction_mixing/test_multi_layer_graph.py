"""ADR-0024 exact N=3 direct graph evidence; no host or transport."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from conditioning_layers.adapters.prediction_mixing.multi_layer import translate_prediction_mixing_multi_layer
from conditioning_layers.assets import FieldRelationshipInput, inspect_field_relationships, to_field_asset_profile
from conditioning_layers.comfyui.prediction_mixing import (
    COMFYUI_0346_SUPPORTED_PROFILE, FieldStagingMap, RuntimeGenerationSettings,
    generate_prediction_mixing_workflow,
)
from conditioning_layers.comfyui.prediction_mixing.multi_layer import (
    EXACT_THREE_REALIZATION, fingerprint_realization_binding,
    generate_prediction_mixing_multi_layer_workflow, validate_multi_layer_artifact,
)
from conditioning_layers.comfyui.prediction_mixing.multi_layer import authority
from conditioning_layers.comfyui.prediction_mixing.multi_layer.canonical import canonical_bytes
from conditioning_layers.domain import (
    ConditioningDocument, PromptLayer, InfluenceFieldAssetReference,
    CURRENT_PROTOTYPE_VERSION, PREDICTION_MIXING_ADAPTER_ID,
)

ROOT = Path(__file__).resolve().parents[4]
INVENTORY = COMFYUI_0346_SUPPORTED_PROFILE.inventory


def fixture(root, family="vertical-thirds", strengths=(1.0, 1.0, 1.0), order=(0, 1, 2)):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    layers = []
    for i, letter in enumerate("abc"):
        data = (ROOT / "influence-field-library/v1/three-layer" / family / f"field-{letter}.png").read_bytes()
        (root / f"{letter}.png").write_bytes(data)
        layers.append(PromptLayer(layer_id=f"layer-{letter}", name=letter.upper(),
            prompt_text=("a red ceramic sphere", "a blue glass cube", "a golden metal cone")[i], strength=strengths[i],
            influence_field=InfluenceFieldAssetReference(f"{letter}.png", hashlib.sha256(data).hexdigest())))
    document = ConditioningDocument(version=CURRENT_PROTOTYPE_VERSION,
        document_id=f"three-layer.{family}.v1", base_prompt="Three distinct objects in a softly lit studio.",
        selected_adapter_id=PREDICTION_MIXING_ADAPTER_ID, layers=tuple(layers[i] for i in order))
    inspected = inspect_field_relationships(root, tuple(FieldRelationshipInput(layer, i) for i, layer in enumerate(document.layers)))
    translated = translate_prediction_mixing_multi_layer(document, inspected.certificate,
        tuple(to_field_asset_profile(item) for item in inspected.fields))
    if translated.plan is None:
        raise AssertionError(translated.findings)
    staging = FieldStagingMap({layer.layer_id: f"conditioning-layers/fixture/{layer.layer_id}.png" for layer in document.layers})
    settings = RuntimeGenerationSettings(18472639, "conditioning-layers-p2b/canonical", "p2b-offline")
    return document, inspected, translated.plan, settings, staging


def generate(data, **kwargs):
    document, inspected, plan, settings, staging = data
    return generate_prediction_mixing_multi_layer_workflow(plan, INVENTORY, settings, staging,
        document_id=document.document_id, **kwargs)


class MultiLayerGraphTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data = fixture(self.temporary.name)

    def test_canonical_vertical_and_horizontal_realization(self):
        for family in ("vertical-thirds", "horizontal-thirds"):
            result = generate(fixture(self.temporary.name, family))
            self.assertTrue(result.generated, result.errors)
            artifact = result.artifact
            graph = artifact.to_api_graph()
            self.assertEqual(tuple(graph), tuple(str(i) for i in range(1, 20)))
            self.assertEqual(len(graph), 19)
            self.assertEqual(sum(isinstance(v, list) for node in graph.values() for v in node["inputs"].values()), 21)
            self.assertEqual(graph["13"], {"class_type": "ConditioningCombine", "inputs": {"conditioning_1": ["10", 0], "conditioning_2": ["11", 0]}})
            self.assertEqual(graph["14"], {"class_type": "ConditioningCombine", "inputs": {"conditioning_1": ["13", 0], "conditioning_2": ["12", 0]}})
            self.assertEqual(graph["16"]["inputs"]["positive"], ["14", 0])
            self.assertEqual(graph["19"]["class_type"], "SaveImage")
            self.assertEqual([graph[str(i)]["class_type"] for i in range(3, 7)], ["CLIPTextEncode"] * 4)
            self.assertEqual([graph[str(i)]["class_type"] for i in range(7, 10)], ["LoadImageMask"] * 3)
            self.assertEqual([graph[str(i)]["class_type"] for i in range(10, 13)], ["ConditioningSetMask"] * 3)
            self.assertEqual(artifact.provenance_inputs.exact_admitted_cardinality, 3)
            self.assertEqual(validate_multi_layer_artifact(artifact, artifact.provenance_inputs, INVENTORY), ())

    def test_repeated_and_fresh_process_determinism(self):
        first, second = generate(self.data).artifact, generate(self.data).artifact
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))
        source = (
            "import sys,tempfile,json; "
            f"sys.path.insert(0, {str(Path(__file__).parent)!r}); "
            "from test_multi_layer_graph import fixture,generate; "
            "t=tempfile.TemporaryDirectory(); a=generate(fixture(t.name)).artifact; "
            "print(json.dumps([a.source_plan.fingerprint,a.graph_fingerprint,a.to_api_graph()],sort_keys=True)); t.cleanup()"
        )
        output = subprocess.check_output([sys.executable, "-B", "-W", "error", "-c", source], text=True)
        self.assertEqual(json.loads(output), [first.source_plan.fingerprint, first.graph_fingerprint, first.to_api_graph()])

    def test_strengths_and_zero_active_branches_are_preserved(self):
        canonical = generate(self.data).artifact
        for strengths in ((0.5, 1.0, 0.75), (0.0, 1.0, 1.0), (0.0, 0.0, 1.0), (0.0, 0.0, 0.0)):
            artifact = generate(fixture(self.temporary.name, strengths=strengths)).artifact
            self.assertIsNotNone(artifact)
            graph = artifact.to_api_graph()
            self.assertEqual(tuple(graph[str(i)]["inputs"]["strength"] for i in (10, 11, 12)), strengths)
            self.assertEqual(len(graph), 19)
            self.assertEqual(tuple(item.requested_strength for item in artifact.provenance_inputs.active_layers), strengths)
            self.assertNotEqual(artifact.graph_fingerprint, canonical.graph_fingerprint)
            self.assertNotEqual(artifact.source_plan.fingerprint, canonical.source_plan.fingerprint)

    def test_order_is_identity_bearing(self):
        original = generate(self.data).artifact
        changed = generate(fixture(self.temporary.name, order=(2, 0, 1))).artifact
        self.assertNotEqual(original.source_plan.fingerprint, changed.source_plan.fingerprint)
        self.assertNotEqual(original.graph_fingerprint, changed.graph_fingerprint)
        self.assertEqual(tuple(item.layer_id for item in changed.provenance_inputs.active_layers), ("layer-c", "layer-a", "layer-b"))

    def test_canonical_signed_zero_has_one_graph_and_workflow_identity(self):
        positive = generate(fixture(self.temporary.name, strengths=(0.0, 1.0, 1.0))).artifact
        negative = generate(fixture(self.temporary.name, strengths=(-0.0, 1.0, 1.0))).artifact
        self.assertEqual(positive.source_plan.fingerprint, negative.source_plan.fingerprint)
        self.assertEqual(positive.graph_fingerprint, negative.graph_fingerprint)
        self.assertEqual(canonical_bytes(positive.canonical_graph), canonical_bytes(negative.canonical_graph))
        self.assertEqual(canonical_bytes(positive.provenance_inputs), canonical_bytes(negative.provenance_inputs))

    def test_seed_is_exact_uint64_and_outside_plan(self):
        original = generate(self.data).artifact
        data = (*self.data[:3], replace(self.data[3], seed=2**64-1), self.data[4])
        changed = generate(data).artifact
        self.assertEqual(changed.source_plan.fingerprint, original.source_plan.fingerprint)
        self.assertEqual(changed.to_api_graph()["16"]["inputs"]["seed"], 2**64-1)
        self.assertNotEqual(changed.graph_fingerprint, original.graph_fingerprint)
        for seed in (True, -1, 2**64):
            self.assertFalse(generate((*self.data[:3], replace(self.data[3], seed=seed), self.data[4])).generated)

    def test_binding_and_graph_tampering_fail_closed(self):
        for binding in (replace(EXACT_THREE_REALIZATION, exact_cardinality=4),
                        replace(EXACT_THREE_REALIZATION, inventory_fingerprint="0"*64), None):
            if binding is not None:
                binding = replace(binding, fingerprint=fingerprint_realization_binding(binding))
            self.assertFalse(generate(self.data, binding=binding).generated)
        artifact = generate(self.data).artifact
        for node_id in ("1", "7", "13", "14", "19"):
            graph = artifact.to_api_graph()
            del graph[node_id]
            changed = replace(artifact, canonical_graph=graph)
            self.assertTrue(validate_multi_layer_artifact(changed, changed.provenance_inputs, INVENTORY))
        changed = replace(artifact.provenance_inputs, exact_admitted_cardinality=2)
        self.assertTrue(validate_multi_layer_artifact(artifact, changed, INVENTORY))
        self.assertFalse(generate_prediction_mixing_workflow(self.data[2], INVENTORY, self.data[3], self.data[4]).generated)

    def test_only_selected_realization_enters_identity(self):
        artifact = generate(self.data).artifact
        # Opaque fixture-only unselected record: no executable cardinality or binding.
        class Unselected:
            identifier = "fixture-unselected-record"
        with patch.object(authority, "REGISTERED_REALIZATION_BINDINGS", (EXACT_THREE_REALIZATION, Unselected())):
            self.assertEqual(generate(self.data).artifact.graph_fingerprint, artifact.graph_fingerprint)
        with patch.object(authority, "REGISTERED_REALIZATION_BINDINGS", ()):
            self.assertFalse(generate(self.data).generated)

    def test_direct_consumer_rejects_malformed_document_provenance_and_warnings(self):
        artifact = generate(self.data).artifact
        graph = artifact.to_api_graph()
        graph[19] = graph.pop("19")
        with self.assertRaises(TypeError):
            replace(artifact, canonical_graph=graph)
        for change in ({"document_id": ""}, {"disabled_layer_ids": ("layer-a",)},
                       {"disabled_layer_ids": ("disabled", "disabled")},
                       {"disabled_layer_ids": ["disabled"]}):
            provenance = replace(artifact.provenance_inputs, **change)
            changed = replace(artifact, provenance_inputs=provenance)
            self.assertTrue(validate_multi_layer_artifact(changed, provenance, INVENTORY))
        provenance = replace(artifact.provenance_inputs, mandatory_warning_codes=())
        changed = replace(artifact, warnings=(), provenance_inputs=provenance)
        self.assertTrue(validate_multi_layer_artifact(changed, provenance, INVENTORY))

    def test_staging_and_inventory_mismatch_fail_before_graph(self):
        document, _, plan, settings, staging = self.data
        for changed in (FieldStagingMap({}), FieldStagingMap({item: "../bad.png" for item in staging.filenames_by_layer_id})):
            self.assertFalse(generate_prediction_mixing_multi_layer_workflow(plan, INVENTORY, settings, changed,
                document_id=document.document_id).generated)
        altered = replace(INVENTORY, supported_execution_profile_identifier="krea2-turbo-bf16-1024.v2")
        self.assertFalse(generate_prediction_mixing_multi_layer_workflow(plan, altered, settings, staging,
            document_id=document.document_id).generated)


if __name__ == "__main__":
    unittest.main()
