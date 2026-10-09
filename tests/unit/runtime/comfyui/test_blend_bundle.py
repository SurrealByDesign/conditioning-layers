"""Offline Blend bundle, source identity and route availability checks."""

from contextlib import contextmanager
from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from conditioning_layers.adapters.prediction_mixing.blend import translate_prediction_mixing_blend
from conditioning_layers.assets import FieldRelationshipInput, inspect_field_relationships, to_field_asset_profile
from conditioning_layers.comfyui.prediction_mixing import DEFAULT_SUPPORTED_PROFILE, FieldStagingMap, RuntimeGenerationSettings
from conditioning_layers.comfyui.prediction_mixing.blend import generate_prediction_mixing_blend_workflow
from conditioning_layers.comfyui.prediction_mixing.blend_component import BLEND_NODE_CLASS, blend_component_identity
from conditioning_layers.comfyui.prediction_mixing.blend_node import ConditioningLayersNormalizedBlend
from conditioning_layers.domain import COMPOSITION_POLICY_PROTOTYPE_VERSION, NORMALIZED_BLEND
from conditioning_layers.runtime.comfyui.blend import (
    BUNDLE_VERSION, RUNTIME_PROVENANCE_VERSION, capture_blend_component_availability,
    fingerprint_portable, prepare_blend_submission_bundle, validate_blend_component_availability,
    validate_blend_submission_bundle,
)


def _load_support():
    path = Path(__file__).with_name("test_multi_layer_bundle.py")
    spec = importlib.util.spec_from_file_location("_p3c_retained_runtime_support", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SUPPORT = _load_support()
ARGV = ["main.py", "--listen", "127.0.0.1", "--port", "9"]


@contextmanager
def registered_component():
    # Shared graph/identity helpers are developer-owned. Only this host-runtime
    # fixture needs torch; retain real dependencies and propagate import failure.
    import torch

    nodes = ModuleType("nodes")
    nodes.NODE_CLASS_MAPPINGS = {BLEND_NODE_CLASS: ConditioningLayersNormalizedBlend}
    server = ModuleType("server")
    server.PromptServer = SimpleNamespace(instance=SimpleNamespace(port=9))
    comfy = ModuleType("comfy")
    model_management = ModuleType("comfy.model_management")
    model_management.intermediate_dtype = lambda: torch.float32
    comfy.model_management = model_management
    with patch.dict(sys.modules, {"nodes": nodes, "server": server, "comfy": comfy, "comfy.model_management": model_management}), patch.object(sys, "argv", ARGV):
        yield nodes


def make_graph_case(root, *, overlapping=False, **options):
    document, inspected, _, assets = SUPPORT.make_graph_case(root, **options)
    if overlapping:
        document = replace(document, layers=tuple(
            replace(layer, influence_field=document.layers[0].influence_field)
            for layer in document.layers
        ))
        inspected = inspect_field_relationships(assets, tuple(
            FieldRelationshipInput(layer, document_index=index)
            for index, layer in enumerate(document.layers)
        ))
    document = replace(
        document, version=COMPOSITION_POLICY_PROTOTYPE_VERSION,
        composition_policy=NORMALIZED_BLEND.reference,
    )
    translated = translate_prediction_mixing_blend(
        document, inspected.certificate, tuple(to_field_asset_profile(item) for item in inspected.fields),
    )
    assert translated.translated, translated.errors
    generated = generate_prediction_mixing_blend_workflow(
        translated.plan, DEFAULT_SUPPORTED_PROFILE.inventory,
        RuntimeGenerationSettings(seed=options.get("seed", 18472639), output_filename_prefix="conditioning-layers/p2b/request-1", execution_request_id="request-1"),
        FieldStagingMap({layer.layer_id: f"conditioning-layers/p2b-document/{layer.layer_id}.png" for layer in document.layers}),
        document_id=document.document_id,
    )
    assert generated.generated, generated.errors
    return document, inspected, generated.artifact, assets


def make_prepared(root, **options):
    case = make_graph_case(root, **options)
    _, inspected, artifact, assets = case
    host, facts = SUPPORT.make_host(root)
    availability = capture_blend_component_availability(blend_component_identity())
    with SUPPORT.component_measurements(facts):
        result = prepare_blend_submission_bundle(
            artifact, artifact.provenance_inputs, DEFAULT_SUPPORTED_PROFILE.inventory,
            host, inspected.fields, assets, DEFAULT_SUPPORTED_PROFILE.node_snapshot,
            component_availability=availability,
        )
    assert result.ready, result.errors
    return result.bundle, case, host, facts


class BlendBundleTests(unittest.TestCase):
    def test_overlap_backend_bundle_stages_original_pngs_with_successor_identity(self):
        with tempfile.TemporaryDirectory() as directory, SUPPORT.offline_fence(), registered_component():
            bundle, _, _, _ = make_prepared(Path(directory), overlapping=True, strengths=(0.0, 1e-37, 5e-324))
            self.assertEqual(bundle.bundle_version, BUNDLE_VERSION)
            self.assertEqual(bundle.provenance.provenance_version, RUNTIME_PROVENANCE_VERSION)
            self.assertEqual(bundle.exact_admitted_cardinality, 3)
            self.assertEqual(len(bundle.to_api_graph()), 20)
            self.assertEqual(validate_blend_submission_bundle(bundle, verify_current_staged_bytes=True), ())
            self.assertEqual(bundle.composition_policy_identifier, NORMALIZED_BLEND.identifier)
            self.assertEqual(len(DEFAULT_SUPPORTED_PROFILE.node_snapshot.contracts), 11)
            for item in bundle.staged_assets:
                self.assertEqual(item.source_path.read_bytes(), item.destination_path.read_bytes())
            self.assertIsNone(bundle.provenance.project_component_precondition["observed_prepared_tensor"])

    def test_portable_identity_is_independent_of_filesystem_root(self):
        with tempfile.TemporaryDirectory() as directory, SUPPORT.offline_fence(), registered_component():
            first, _, _, _ = make_prepared(Path(directory) / "first")
            second, _, _, _ = make_prepared(Path(directory) / "second")
            self.assertEqual(first.bundle_fingerprint, second.bundle_fingerprint)
            self.assertEqual(fingerprint_portable(first.provenance), fingerprint_portable(second.provenance))

    def test_absence_fails_only_blend_before_host_and_staging(self):
        with tempfile.TemporaryDirectory() as directory, SUPPORT.offline_fence():
            root = Path(directory)
            _, inspected, artifact, assets = make_graph_case(root)
            host, _ = SUPPORT.make_host(root)
            with patch("conditioning_layers.runtime.comfyui.blend.validate_local_host", side_effect=AssertionError("no host check")):
                result = prepare_blend_submission_bundle(
                    artifact, artifact.provenance_inputs, DEFAULT_SUPPORTED_PROFILE.inventory,
                    host, inspected.fields, assets, DEFAULT_SUPPORTED_PROFILE.node_snapshot,
                )
            self.assertFalse(result.ready)
            self.assertEqual(result.errors[0].code, "runtime.blend_component_unavailable")
            self.assertEqual(result.staged_assets, ())
        with tempfile.TemporaryDirectory() as directory, SUPPORT.offline_fence():
            retained, _, _, _ = SUPPORT.make_prepared(Path(directory))
            self.assertEqual(len(retained.to_api_graph()), 19)

    def test_forged_identity_presence_only_and_stale_process_fail_closed(self):
        with registered_component() as nodes:
            current = capture_blend_component_availability(blend_component_identity())
            for changed in (
                replace(current, available=False), replace(current, process_id=-1),
                replace(current, implementation=replace(current.implementation, source_sha256="0" * 64)),
                replace(current, implementation=replace(current.implementation, implementation_fingerprint="0" * 64)),
                {"available": True, "class_type": BLEND_NODE_CLASS},
            ):
                self.assertTrue(validate_blend_component_availability(changed))
            nodes.NODE_CLASS_MAPPINGS[BLEND_NODE_CLASS] = type("Impostor", (), {})
            self.assertTrue(validate_blend_component_availability(current))

    def test_fp16_and_missing_launch_evidence_fail_closed(self):
        with registered_component():
            for arguments in ([], ARGV + ["--fp16-intermediates"], ARGV + ["--fp16-intermediates=true"]):
                with patch.object(sys, "argv", arguments), self.assertRaises(ValueError):
                    capture_blend_component_availability(blend_component_identity())

    def test_actual_intermediate_dtype_and_dependency_failure_fail_closed(self):
        import torch

        with registered_component():
            with patch("comfy.model_management.intermediate_dtype", return_value=torch.float16), self.assertRaises(ValueError):
                capture_blend_component_availability(blend_component_identity())
            with patch("conditioning_layers.comfyui.prediction_mixing.blend_node._runtime_dependencies", side_effect=ImportError("offline missing dependency")), self.assertRaises(ValueError):
                capture_blend_component_availability(blend_component_identity())

    def test_registration_disappearing_invalidates_bundle(self):
        with tempfile.TemporaryDirectory() as directory, SUPPORT.offline_fence(), registered_component() as nodes:
            bundle, _, _, _ = make_prepared(Path(directory))
            nodes.NODE_CLASS_MAPPINGS.clear()
            self.assertTrue(validate_blend_submission_bundle(bundle))

    def test_resigned_authority_and_component_provenance_disagreement_rejected(self):
        with tempfile.TemporaryDirectory() as directory, SUPPORT.offline_fence(), registered_component():
            bundle, _, _, _ = make_prepared(Path(directory))
            for changes in (
                {"composition_policy_identifier": "unknown"},
                {"project_component_implementation_fingerprint": "0" * 64},
                {"permitted_class_authority_fingerprint": "0" * 64},
                {"exact_admitted_cardinality": 4},
                {"staged_assets": bundle.staged_assets[::-1]},
                {"provenance": replace(bundle.provenance, project_component_precondition={})},
            ):
                self.assertTrue(validate_blend_submission_bundle(replace(bundle, **changes)))


if __name__ == "__main__":
    unittest.main()
