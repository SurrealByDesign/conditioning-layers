"""Offline exact-N=3 preparation using real PNG, host-path and staging checks."""

from contextlib import contextmanager
from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from conditioning_layers.adapters.prediction_mixing.multi_layer import translate_prediction_mixing_multi_layer
from conditioning_layers.assets import FieldRelationshipInput, inspect_field_relationships, to_field_asset_profile
from conditioning_layers.comfyui.prediction_mixing import DEFAULT_SUPPORTED_PROFILE, FieldStagingMap, RuntimeGenerationSettings
from conditioning_layers.comfyui.prediction_mixing.multi_layer import generate_prediction_mixing_multi_layer_workflow
from conditioning_layers.domain import ConditioningDocument, CURRENT_PROTOTYPE_VERSION, PREDICTION_MIXING_ADAPTER_ID, InfluenceFieldAssetReference, PromptLayer
from conditioning_layers.runtime.comfyui import ComfyUIHostConfiguration
from conditioning_layers.runtime.comfyui.multi_layer import (
    BUNDLE_VERSION, RUNTIME_PROVENANCE_VERSION, fingerprint_portable,
    prepare_multi_layer_submission_bundle, validate_multi_layer_submission_bundle,
)


REPOSITORY = Path(__file__).resolve().parents[4]


@contextmanager
def offline_fence():
    with patch("socket.socket", side_effect=AssertionError("offline socket fence")), \
         patch("urllib.request.urlopen", side_effect=AssertionError("offline HTTP fence")), \
         patch("http.client.HTTPConnection.connect", side_effect=AssertionError("offline HTTP fence")), \
         patch("subprocess.Popen", side_effect=AssertionError("offline process fence")), \
         patch("webbrowser.open", side_effect=AssertionError("offline browser fence")):
        yield


def make_graph_case(root, *, family="vertical-thirds", strengths=(1.0, 1.0, 1.0), seed=18472639):
    root = root.resolve()
    asset_root = root / "document.assets"
    (asset_root / "fields").mkdir(parents=True)
    layers = []
    for ordinal, (layer_id, strength) in enumerate(zip(("a", "b", "c"), strengths, strict=True)):
        data = (REPOSITORY / "influence-field-library" / "v1" / "three-layer" / family / f"field-{layer_id}.png").read_bytes()
        reference = f"fields/{layer_id}.png"
        (asset_root / reference).write_bytes(data)
        layers.append(PromptLayer(
            layer_id=layer_id, name=f"Layer {layer_id}", prompt_text=f"Regional prompt {layer_id}",
            visible=True, strength=strength,
            influence_field=InfluenceFieldAssetReference(relative_path=reference, checksum=hashlib.sha256(data).hexdigest()),
        ))
    document = ConditioningDocument(
        version=CURRENT_PROTOTYPE_VERSION, document_id="p2b-document",
        base_prompt="A coherent landscape", layers=tuple(layers),
        selected_adapter_id=PREDICTION_MIXING_ADAPTER_ID, adapter_settings={},
    )
    inspected = inspect_field_relationships(
        asset_root, tuple(FieldRelationshipInput(layer, document_index=i) for i, layer in enumerate(document.layers)),
    )
    assert not inspected.errors, inspected.errors
    profiles = tuple(to_field_asset_profile(item) for item in inspected.fields)
    translated = translate_prediction_mixing_multi_layer(document, inspected.certificate, profiles)
    assert translated.translated and translated.plan is not None, translated.errors
    generated = generate_prediction_mixing_multi_layer_workflow(
        translated.plan, DEFAULT_SUPPORTED_PROFILE.inventory,
        RuntimeGenerationSettings(seed=seed, output_filename_prefix="conditioning-layers/p2b/request-1", execution_request_id="request-1"),
        FieldStagingMap({layer.layer_id: f"conditioning-layers/p2b-document/{layer.layer_id}.png" for layer in document.layers}),
        document_id=document.document_id,
    )
    assert generated.generated, generated.errors
    return document, inspected, generated.artifact, asset_root


def make_host(root):
    inventory = DEFAULT_SUPPORTED_PROFILE.inventory
    checkout = root / "ComfyUI"
    data = root / "data"
    models = data / "models"
    directories = {category: (models / category,) for category in ("diffusion_models", "text_encoders", "vae")}
    for path in (checkout, data / "input", data / "output", data / "user", *(items[0] for items in directories.values())):
        path.mkdir(parents=True, exist_ok=True)
    (checkout / ".git").mkdir()
    (checkout / ".git" / "HEAD").write_text(inventory.expected_comfyui_revision, encoding="utf-8")
    (checkout / "comfyui_version.py").write_text(f'__version__ = "{inventory.expected_comfyui_version}"\n', encoding="utf-8")
    component_facts = {}
    for category, filename, size, digest in (
        ("diffusion_models", inventory.model_filename, inventory.model_size_bytes, inventory.model_sha256),
        ("text_encoders", inventory.text_encoder_filename, inventory.text_encoder_size_bytes, inventory.text_encoder_sha256),
        ("vae", inventory.vae_filename, inventory.vae_size_bytes, inventory.vae_sha256),
    ):
        path = directories[category][0] / filename
        path.write_bytes(b"offline component fixture; measurement seam is mocked")
        component_facts[path] = (size, digest)
    host = ComfyUIHostConfiguration(
        comfyui_root=checkout, input_directory=data / "input", output_directory=data / "output",
        user_directory=data / "user", model_root=models, model_directories=directories,
        git_checkout_path=checkout, supported_profile_identifier=inventory.comfyui_profile_identifier,
        launch_profile_identifier="p2b-offline-fixture", checkout_trusted_root=root,
        data_trusted_root=data, model_trusted_root=models,
    )
    return host, component_facts


@contextmanager
def component_measurements(component_facts):
    # Keep the full production inventory immutable. Only external observations
    # of temporary model-file bytes/size are simulated; validators remain real.
    original_stat = Path.stat

    def observed_stat(path, *args, **kwargs):
        value = original_stat(path, *args, **kwargs)
        if path in component_facts:
            values = list(value)
            values[6] = component_facts[path][0]
            return type(value)(values)
        return value

    with patch.object(Path, "stat", observed_stat), patch(
        "conditioning_layers.runtime.comfyui.component_validation._sha256_file",
        side_effect=lambda path: component_facts[path][1],
    ):
        yield


def make_prepared(root, **graph_options):
    case = make_graph_case(root, **graph_options)
    document, inspected, artifact, asset_root = case
    host, facts = make_host(root)
    with component_measurements(facts):
        result = prepare_multi_layer_submission_bundle(
            artifact, artifact.provenance_inputs, DEFAULT_SUPPORTED_PROFILE.inventory,
            host, inspected.fields, asset_root, DEFAULT_SUPPORTED_PROFILE.node_snapshot,
        )
    assert result.ready, result.errors
    return result.bundle, case, host, facts


class MultiLayerBundleTests(unittest.TestCase):
    def test_both_thirds_prepare_all_three_real_fields(self):
        for family in ("vertical-thirds", "horizontal-thirds"):
            with self.subTest(family=family), tempfile.TemporaryDirectory() as directory, offline_fence():
                bundle, case, _, _ = make_prepared(Path(directory), family=family)
                self.assertEqual(bundle.bundle_version, BUNDLE_VERSION)
                self.assertEqual(bundle.provenance.provenance_version, RUNTIME_PROVENANCE_VERSION)
                self.assertEqual(bundle.exact_admitted_cardinality, 3)
                self.assertEqual(len(bundle.staged_assets), 3)
                self.assertEqual(len(bundle.to_api_graph()), 19)
                self.assertEqual(validate_multi_layer_submission_bundle(bundle, verify_current_staged_bytes=True), ())
                for item in bundle.staged_assets:
                    self.assertEqual(item.source_path.read_bytes(), item.destination_path.read_bytes())

    def test_fresh_roots_have_identical_bundle_and_runtime_identity(self):
        with tempfile.TemporaryDirectory() as directory, offline_fence():
            left, _, _, _ = make_prepared(Path(directory) / "left")
            right, _, _, _ = make_prepared(Path(directory) / "right")
            self.assertEqual(left.bundle_fingerprint, right.bundle_fingerprint)
            self.assertEqual(fingerprint_portable(left.provenance), fingerprint_portable(right.provenance))

    def test_reused_staged_bytes_preserve_bundle_and_runtime_identity(self):
        with tempfile.TemporaryDirectory() as directory, offline_fence():
            first, case, host, facts = make_prepared(Path(directory))
            _, inspected, artifact, assets = case
            with component_measurements(facts):
                repeated = prepare_multi_layer_submission_bundle(
                    artifact, artifact.provenance_inputs, DEFAULT_SUPPORTED_PROFILE.inventory,
                    host, inspected.fields, assets, DEFAULT_SUPPORTED_PROFILE.node_snapshot,
                )
            self.assertTrue(repeated.ready, repeated.errors)
            self.assertEqual(first.bundle_fingerprint, repeated.bundle.bundle_fingerprint)
            self.assertEqual(fingerprint_portable(first.provenance), fingerprint_portable(repeated.bundle.provenance))
            self.assertNotEqual(first.staged_assets[0].disposition, repeated.bundle.staged_assets[0].disposition)

    def test_explicit_reference_and_cardinality_mismatches_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory, offline_fence():
            bundle, _, _, _ = make_prepared(Path(directory))
            for changes in (
                {"exact_admitted_cardinality": 2}, {"exact_admitted_cardinality": 3.0},
                {"eligibility_entry_fingerprint": "0" * 64},
                {"realization_binding_identifier": "unknown"},
                {"contract_identifier": "unknown"},
                {"provenance": replace(bundle.provenance, exact_admitted_cardinality=4)},
                {"graph_fingerprint": "0" * 64},
                {"staged_assets": bundle.staged_assets[::-1]},
            ):
                with self.subTest(changes=changes):
                    self.assertTrue(validate_multi_layer_submission_bundle(replace(bundle, **changes)))

    def test_source_changed_or_inspection_missing_prevents_staging(self):
        with tempfile.TemporaryDirectory() as directory, offline_fence():
            root = Path(directory)
            _, inspected, artifact, assets = make_graph_case(root)
            host, facts = make_host(root)
            for inspections in (inspected.fields[:-1], inspected.fields):
                if len(inspections) == 3:
                    (assets / "fields/b.png").write_bytes(b"changed bytes")
                with component_measurements(facts):
                    result = prepare_multi_layer_submission_bundle(
                        artifact, artifact.provenance_inputs, DEFAULT_SUPPORTED_PROFILE.inventory,
                        host, inspections, assets, DEFAULT_SUPPORTED_PROFILE.node_snapshot,
                    )
                self.assertFalse(result.ready)
                self.assertIsNone(result.bundle)
                self.assertEqual(result.staged_assets, ())
                self.assertEqual(list(host.input_directory.rglob("*.png")), [])

    def test_host_or_component_failure_prevents_staging(self):
        with tempfile.TemporaryDirectory() as directory, offline_fence():
            root = Path(directory)
            _, inspected, artifact, assets = make_graph_case(root)
            host, _ = make_host(root)
            result = prepare_multi_layer_submission_bundle(
                artifact, artifact.provenance_inputs, DEFAULT_SUPPORTED_PROFILE.inventory,
                host, inspected.fields, assets, DEFAULT_SUPPORTED_PROFILE.node_snapshot,
            )
            self.assertFalse(result.ready)
            self.assertIsNone(result.bundle)
            self.assertEqual(result.staged_assets, ())

    def test_graph_tampering_rejects_before_host_or_staging_work(self):
        with tempfile.TemporaryDirectory() as directory, offline_fence():
            root = Path(directory)
            _, inspected, artifact, assets = make_graph_case(root)
            host, _ = make_host(root)
            with patch("conditioning_layers.runtime.comfyui.multi_layer.validate_local_host", side_effect=AssertionError("must not inspect host")):
                result = prepare_multi_layer_submission_bundle(
                    replace(artifact, graph_fingerprint="0" * 64), artifact.provenance_inputs,
                    DEFAULT_SUPPORTED_PROFILE.inventory, host, inspected.fields, assets,
                    DEFAULT_SUPPORTED_PROFILE.node_snapshot,
                )
            self.assertIsNone(result.bundle)
            self.assertFalse(result.ready)

    def test_changed_staged_bytes_are_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as directory, offline_fence():
            bundle, _, _, _ = make_prepared(Path(directory))
            bundle.staged_assets[1].destination_path.write_bytes(b"changed")
            self.assertTrue(validate_multi_layer_submission_bundle(bundle, verify_current_staged_bytes=True))

    def test_submitted_graph_numeric_alias_and_reorder_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory, offline_fence():
            bundle, _, _, _ = make_prepared(Path(directory))
            graph = bundle.to_api_graph()
            graph["10"]["inputs"]["strength"] = True
            self.assertTrue(validate_multi_layer_submission_bundle(replace(bundle, graph_mapping=graph)))
            self.assertTrue(validate_multi_layer_submission_bundle(replace(bundle, graph_mapping=dict(reversed(tuple(bundle.to_api_graph().items()))))))
            graph = bundle.to_api_graph()
            graph[19] = graph.pop("19")
            with self.assertRaises(TypeError):
                replace(bundle, graph_mapping=graph)

    def test_uint64_seed_and_zero_strength_are_retained(self):
        with tempfile.TemporaryDirectory() as directory, offline_fence():
            bundle, _, _, _ = make_prepared(Path(directory), strengths=(0.0, 0.5, 0.75), seed=2**64-1)
            self.assertEqual(bundle.runtime_seed, 2**64-1)
            self.assertEqual(bundle.provenance.seed, 2**64-1)
            self.assertEqual(tuple(item.requested_strength for item in bundle.provenance.workflow_provenance.active_layers), (0.0, 0.5, 0.75))


if __name__ == "__main__":
    unittest.main()
