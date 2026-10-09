"""ADR-0028 Slice B offline bundle-v4 and runtime-provenance-v4 successors.

Developer/offline lane: retained host, component, source and staging
primitives run against temporary fixtures; only model-file measurements are
simulated. No Torch, ComfyUI, host process, network or submission is used.
"""

from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui.prediction_mixing import DEFAULT_SUPPORTED_PROFILE, FieldStagingMap, RuntimeGenerationSettings
from conditioning_layers.comfyui.prediction_mixing.generalized_blend import (
    generate_generalized_blend_workflow, select_generalized_realization_binding,
)
from conditioning_layers.comfyui.prediction_mixing.generalized_blend_component import generalized_blend_component_identity
from conditioning_layers.runtime.comfyui import generalized_blend as runtime
from conditioning_layers.runtime.comfyui.blend import validate_blend_submission_bundle

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tests/tooling"))
from bounded_blend_fixture import bounded_document, inspect_document  # noqa: E402
from conditioning_layers.adapters.prediction_mixing.blend import translate_prediction_mixing_blend  # noqa: E402
from conditioning_layers.capabilities._bounded_blend import select_bounded_blend_eligibility  # noqa: E402


def _load_support():
    path = Path(__file__).with_name("test_multi_layer_bundle.py")
    spec = importlib.util.spec_from_file_location("_slice_b_retained_runtime_support", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SUPPORT = _load_support()
INVENTORY = DEFAULT_SUPPORTED_PROFILE.inventory
FIXTURE = "slice-b-offline-fixture"


def make_case(root, n, *, seed=18472639, **options):
    root = Path(root).resolve()
    assets = root / "assets"
    document = bounded_document(assets, n, **options)
    inspection, profiles = inspect_document(assets, document)
    translated = translate_prediction_mixing_blend(
        document, inspection.certificate, profiles, eligibility_entry=select_bounded_blend_eligibility(document))
    assert translated.translated, translated.findings
    plan = translated.plan
    generated = generate_generalized_blend_workflow(
        plan, INVENTORY,
        RuntimeGenerationSettings(seed=seed, output_filename_prefix="conditioning-layers/slice-b/request-1",
                                  execution_request_id="request-1"),
        FieldStagingMap({layer.layer_id: f"conditioning-layers/{document.document_id}/{layer.layer_id}.png"
                         for layer in document.active_layers}),
        binding=select_generalized_realization_binding(plan), document_id=document.document_id,
        disabled_layer_ids=tuple(layer.layer_id for layer in document.layers if layer.visible is not True),
    )
    assert generated.generated, generated.errors
    return document, inspection, generated.artifact, assets


def prepare(root, n, *, availability=None, **options):
    document, inspection, artifact, assets = make_case(root, n, **options)
    host, facts = SUPPORT.make_host(Path(root).resolve())
    if availability is None:
        availability = runtime.capture_generalized_blend_offline_fixture_availability(FIXTURE)
    with SUPPORT.component_measurements(facts):
        result = runtime.prepare_generalized_blend_bundle(
            artifact, artifact.provenance_inputs, INVENTORY, host, inspection.fields, assets,
            DEFAULT_SUPPORTED_PROFILE.node_snapshot, component_availability=availability)
    return result, document, artifact, host


class GeneralizedBlendBundleTests(unittest.TestCase):
    def test_each_exact_count_prepares_a_bound_never_submission_ready_bundle(self):
        identity = generalized_blend_component_identity()
        for n in range(4, 10):
            with self.subTest(n=n), tempfile.TemporaryDirectory() as directory, SUPPORT.offline_fence():
                result, document, artifact, _ = prepare(directory, n)
                self.assertTrue(result.prepared, result.errors)
                bundle = result.bundle
                self.assertEqual(bundle.bundle_version, "conditioning-layers.comfyui-submission-bundle.v4")
                self.assertEqual(bundle.provenance.provenance_version, "conditioning-layers.runtime-provenance.v4")
                self.assertIs(bundle.submission_ready, False)
                self.assertIs(bundle.provenance.submission_authorized, False)
                self.assertEqual(bundle.unresolved_runtime_requirements, runtime.UNRESOLVED_RUNTIME_REQUIREMENTS)
                self.assertEqual(result.unresolved_runtime_requirements, runtime.UNRESOLVED_RUNTIME_REQUIREMENTS)
                self.assertEqual((bundle.exact_admitted_cardinality, bundle.expected_count), (n, n))
                self.assertEqual(bundle.eligibility_entry_identifier, f"prediction-mixing.multi-layer.exact-{n}.normalized-blend.v1")
                self.assertEqual(bundle.realization_binding_identifier, artifact.realization_binding.identifier)
                self.assertEqual(bundle.realization_binding_fingerprint, artifact.realization_binding.fingerprint)
                self.assertEqual(bundle.project_component_identifier, "ConditioningLayersGeneralizedNormalizedBlend")
                self.assertEqual(bundle.project_component_implementation_fingerprint, identity.implementation_fingerprint)
                self.assertEqual(bundle.translation_plan_identifier, "prediction-mixing.translation-plan.v4")
                self.assertEqual((bundle.graph_version, bundle.graph_fingerprint),
                                 ("prediction-mixing.prototype.v4", artifact.graph_fingerprint))
                self.assertEqual(len(bundle.to_api_graph()), 4 * n + 8)
                self.assertEqual(tuple(item.layer_id for item in bundle.staged_assets),
                                 tuple(layer.layer_id for layer in document.active_layers))
                for item in bundle.staged_assets:
                    self.assertEqual(item.source_path.read_bytes(), item.destination_path.read_bytes())
                self.assertEqual(runtime.validate_generalized_blend_bundle(bundle, verify_current_staged_bytes=True), ())
                availability = bundle.provenance.component_availability
                self.assertEqual(availability["observation_scope"], "offline-fixture-construction")
                self.assertEqual(availability["fixture_identifier"], FIXTURE)
                self.assertNotIn("process_id", availability)
                self.assertNotIn("launch_arguments_sha256", availability)
                self.assertEqual(tuple(availability["not_claimed"]), runtime.NOT_CLAIMED)
                self.assertIsNone(availability["observed_prepared_tensor"])

    def test_portable_identity_is_root_independent_and_carries_disabled_zero_and_uint64(self):
        with tempfile.TemporaryDirectory() as directory, SUPPORT.offline_fence():
            first, _, _, _ = prepare(Path(directory) / "first", 9)
            second, _, _, _ = prepare(Path(directory) / "second", 9)
            self.assertEqual(first.bundle.bundle_fingerprint, second.bundle.bundle_fingerprint)
            self.assertEqual(runtime.fingerprint_portable(first.bundle.provenance),
                             runtime.fingerprint_portable(second.bundle.provenance))
            disabled, document, _, _ = prepare(Path(directory) / "disabled", 7, disabled=True, seed=2**64 - 1)
            self.assertTrue(disabled.prepared, disabled.errors)
            workflow = disabled.bundle.provenance.workflow_provenance
            self.assertEqual(workflow.disabled_layer_ids, ("disabled",) + tuple(f"disabled-{i}" for i in range(7)))
            self.assertEqual((disabled.bundle.runtime_seed, disabled.bundle.provenance.seed), (2**64 - 1, 2**64 - 1))
            strengths = tuple(item.requested_strength for item in workflow.active_layers)
            self.assertIn(0.0, strengths)
            self.assertIn(5e-324, strengths)
            self.assertNotEqual(disabled.bundle.bundle_fingerprint, first.bundle.bundle_fingerprint)

    def test_missing_or_forged_offline_availability_fails_before_host_and_staging(self):
        record = runtime.capture_generalized_blend_offline_fixture_availability(FIXTURE)
        for availability in (None, replace(record, observation_scope="target-process-registration"),
                             replace(record, available_to_offline_fixture=False),
                             {"available": True, "class_type": "ConditioningLayersGeneralizedNormalizedBlend"}):
            with self.subTest(availability=availability), tempfile.TemporaryDirectory() as directory, SUPPORT.offline_fence():
                document, inspection, artifact, assets = make_case(directory, 4)
                host, _ = SUPPORT.make_host(Path(directory).resolve())
                with patch("conditioning_layers.runtime.comfyui.generalized_blend.validate_local_host",
                           side_effect=AssertionError("no host check")):
                    result = runtime.prepare_generalized_blend_bundle(
                        artifact, artifact.provenance_inputs, INVENTORY, host, inspection.fields, assets,
                        DEFAULT_SUPPORTED_PROFILE.node_snapshot, component_availability=availability)
                self.assertFalse(result.prepared)
                self.assertIsNone(result.bundle)
                self.assertEqual(tuple(f.code for f in result.errors), ("runtime.generalized_blend_component_unavailable",))
                self.assertEqual(result.staged_assets, ())
                self.assertEqual(list(host.input_directory.rglob("*.png")), [])

    def test_submission_ready_count_reference_and_order_tampering_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory, SUPPORT.offline_fence():
            result, _, _, _ = prepare(directory, 6)
            bundle = result.bundle
            code = ("runtime.generalized_blend_bundle_invalid",)
            for changes in (
                {"submission_ready": True}, {"submission_ready": None}, {"unresolved_runtime_requirements": ()},
                {"expected_count": 7}, {"expected_count": True}, {"exact_admitted_cardinality": 7},
                {"exact_admitted_cardinality": 6.0}, {"realization_binding_identifier": "unknown"},
                {"project_component_implementation_fingerprint": "0" * 64},
                {"eligibility_entry_fingerprint": "0" * 64}, {"graph_fingerprint": "0" * 64},
                {"staged_assets": bundle.staged_assets[::-1]}, {"bundle_version": "conditioning-layers.comfyui-submission-bundle.v3"},
                {"provenance": replace(bundle.provenance, submission_authorized=True)},
                {"provenance": replace(bundle.provenance, component_availability={})},
                {"provenance": replace(bundle.provenance, expected_count=5)},
            ):
                with self.subTest(changes=tuple(changes)):
                    self.assertEqual(tuple(f.code for f in runtime.validate_generalized_blend_bundle(replace(bundle, **changes))), code)
            forged = replace(bundle.component_availability, observation_scope="target-process-registration")
            self.assertEqual(tuple(f.code for f in runtime.validate_generalized_blend_bundle(replace(bundle, component_availability=forged))),
                             ("runtime.generalized_blend_component_unavailable",))
            bundle.staged_assets[2].destination_path.write_bytes(b"changed")
            self.assertEqual(tuple(f.code for f in runtime.validate_generalized_blend_bundle(bundle, verify_current_staged_bytes=True)), code)

    def test_retained_exact3_bundle_family_rejects_the_successor(self):
        with tempfile.TemporaryDirectory() as directory, SUPPORT.offline_fence():
            result, _, _, _ = prepare(directory, 4)
            self.assertEqual(tuple(f.code for f in validate_blend_submission_bundle(result.bundle)),
                             ("runtime.blend_bundle_invalid",))
            for value in (None, object(), result.bundle.provenance):
                self.assertEqual(tuple(f.code for f in runtime.validate_generalized_blend_bundle(value)),
                                 ("runtime.generalized_blend_bundle_invalid",))


if __name__ == "__main__":
    unittest.main()
