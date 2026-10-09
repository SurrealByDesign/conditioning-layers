"""Host dependency lane, offline: real product route and retained Blend client.

All transport is in memory. The existing registered-component fixture uses real
torch/numpy/av under the retained fences, with temporary host/model observations.
"""

from concurrent.futures import Future
from contextlib import ExitStack
from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from conditioning_layers.capabilities import multi_layer, product
from conditioning_layers.comfyui.prediction_mixing import (
    COMFYUI_0372_QUALIFICATION_PROFILE, DEFAULT_SUPPORTED_PROFILE, ProfileSupportStatus,
)
from conditioning_layers.comfyui.prediction_mixing.blend import (
    BLEND_GRAPH_PERMITTED_CLASSES_COMFYUI_0372, EXACT_THREE_BLEND_REALIZATION_COMFYUI_0372,
)
from conditioning_layers.domain import COMPOSITION_POLICY_PROTOTYPE_VERSION, NORMALIZED_BLEND, ValidationFinding, FindingSeverity
from conditioning_layers.execution.comfyui.blend import execute_blend_submission_bundle
from conditioning_layers.integrations.comfyui_panel.application import ExistingBackendApplication, PreparedPanelExecution
from conditioning_layers.integrations.comfyui_panel.blend_application import accept_blend_result
from conditioning_layers.integrations.comfyui_panel.jobs import PanelJobCoordinator
from conditioning_layers.integrations.comfyui_panel.models import PanelRunResult
from conditioning_layers.runtime.comfyui.blend import fingerprint_portable, validate_blend_submission_bundle

from test_compatibility_injection import fake_checkout, model_file_observations
from test_multi_layer_application import fixture_request, synthetic_fields
from test_blend_frontend import assert_observation


def load_support():
    path = Path(__file__).resolve().parents[2] / "execution/comfyui/test_blend.py"
    spec = importlib.util.spec_from_file_location("_product_blend_execution_support", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SUPPORT = load_support()
EXECUTION_ID = "a" * 32


class RecordingApplication(ExistingBackendApplication):
    def prepare(self, *args):
        self.prepared = super().prepare(*args)
        return self.prepared


class ProductMemoryTransport(SUPPORT.MemoryTransport):
    def __init__(self, bundle, mutate=None):
        super().__init__(bundle)
        self.configuration = replace(self.configuration, port=8000)
        self.argv = list(sys.argv)
        self.mutate = mutate

    def get_json(self, path):
        value = super().get_json(path)
        if path.startswith("/history/"):
            record = value[SUPPORT.RETAINED.PROMPT_ID]
            execution_id = self.bundle.graph_artifact.provenance_inputs.execution_request_id
            record["outputs"] = {"20": {"images": [{"filename": execution_id + "_00001_.png",
                                                  "subfolder": "conditioning-layers-panel", "type": "output"}]}}
            # Another prompt's corrupt output must never affect this prompt.
            value["unrelated-prompt"] = {"outputs": {"wrong": {"images": [{"filename": "wrong.png"}]}}}
            if self.mutate:
                self.mutate(record)
        return value


class InlineLoop:
    """Deterministic coordinator scheduler, without threads or sockets."""
    def run_in_executor(self, executor, callback, *args):
        self.pending = callback, args
        self.future = Future()
        return self.future

    def call_soon_threadsafe(self, callback, *args):
        callback(*args)

    def flush(self):
        callback, args = self.pending
        callback(*args)
        self.future.set_result(None)


class BlendProductApplicationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix="p3d-product-")))
        self.context, observations = fake_checkout(self.root, DEFAULT_SUPPORTED_PROFILE)
        self.stack.enter_context(model_file_observations(observations))
        self.nodes = self.stack.enter_context(SUPPORT.SUPPORT.registered_component())
        sys.modules["server"].PromptServer.instance.port = 8000
        self.stack.enter_context(patch.object(sys, "argv", ["main.py", "--listen", "127.0.0.1", "--port", "8000"]))
        self.draft = replace(fixture_request(field_data=synthetic_fields(continuous=True, overlap_pair=(0, 1)),
                                            strengths=(0.0, 1e-37, 5e-324)),
                             document_version=COMPOSITION_POLICY_PROTOTYPE_VERSION, composition_policy=NORMALIZED_BLEND.reference)
        self.application = RecordingApplication(self.context)
        self.transports = []
        self.raw_results = []

    def transport_factory(self, mutate=None):
        def factory(configuration):
            transport = ProductMemoryTransport(self.application.prepared.bundle, mutate)
            self.assertEqual(configuration.port, transport.configuration.port)
            self.transports.append(transport)
            return transport
        return patch("conditioning_layers.execution.comfyui.blend.LocalJsonTransport", side_effect=factory)

    def execute(self, mutate=None):
        def client(*args, **kwargs):
            result = execute_blend_submission_bundle(*args, **kwargs)
            self.raw_results.append(result)
            return result
        self.application._execution_client = client
        with self.transport_factory(mutate):
            return self.application.run(self.draft, EXECUTION_ID, lambda _: None)

    def test_closed_authority_rejects_before_blend_preparation_even_with_components(self):
        with patch.object(product, "PRODUCT_ADMITTED_ENTRIES", multi_layer.PRODUCT_ADMITTED_ENTRIES), patch("conditioning_layers.integrations.comfyui_panel.blend_application.prepare_blend", side_effect=AssertionError("Admission must reject first")):
            result = self.application.run(self.draft, EXECUTION_ID, lambda _: None)
        self.assertEqual(result.state, "rejected")
        self.assertIn("capability.product_not_admitted", {finding.code for finding in result.findings})
        self.assertFalse((self.context.host_configuration.input_directory / "conditioning-layers").exists())

    def test_real_product_preparation_client_output_and_retained_identity(self):
        result = self.execute()
        self.assertEqual(result.state, "completed", result)
        prepared = self.application.prepared
        self.assertIsInstance(prepared, PreparedPanelExecution)
        self.assertFalse(prepared.multi_layer)
        self.assertEqual(prepared.route_identifier, "prediction-mixing.multi-layer.v2")
        bundle = prepared.bundle
        self.assertEqual(bundle.expected_output_prefix, f"conditioning-layers-panel/{EXECUTION_ID}")
        graph = bundle.to_api_graph()
        self.assertEqual(len(graph), 20)
        self.assertEqual(sum(isinstance(value, list) for node in graph.values() for value in node["inputs"].values()), 22)
        self.assertEqual(graph["20"]["class_type"], "SaveImage")
        self.assertEqual(graph["17"]["class_type"], "KSampler")
        self.assertEqual(bundle.eligibility_entry_fingerprint, "aeefb8a4c0697056f42bcd7078236838df4ef15defe68f05309c993666bcda22")
        self.assertEqual(bundle.realization_binding_fingerprint, "8264274afbcbb7db30f3389fd03289618bfa4b99e104d0d71405f620cec3f781")
        self.assertEqual(bundle.project_component_implementation_fingerprint, "46e33564c8b1327fae767099e008cf7a1f98b2b8a02c992d67f5a3fba0fd7e31")
        self.assertIn("blend.not_live_qualified", bundle.warnings)
        self.assertEqual(len([request for request in self.transports[-1].requests if request[0] == "POST"]), 1)
        identities = (bundle.graph_fingerprint, bundle.bundle_fingerprint, fingerprint_portable(bundle.provenance), self.raw_results[-1].result_identity_fingerprint)
        self.execute()
        again = self.application.prepared.bundle
        self.assertEqual(identities, (again.graph_fingerprint, again.bundle_fingerprint, fingerprint_portable(again.provenance), self.raw_results[-1].result_identity_fingerprint))

    def test_missing_multiple_duplicate_wrong_node_and_unsafe_outputs_never_succeed(self):
        def image_update(changes):
            return lambda record: record["outputs"]["20"]["images"][0].update(changes)
        def multiple(record):
            images = record["outputs"]["20"]["images"]
            images.append({**images[0], "filename": EXECUTION_ID + "_00002_.png"})
        cases = [
            lambda record: record.update(outputs={}), multiple,
            lambda record: record["outputs"]["20"]["images"].append(dict(record["outputs"]["20"]["images"][0])),
            lambda record: record["outputs"].update({"19": record["outputs"].pop("20")}),
            lambda record: record["outputs"].update({"unexpected": {"images": []}}),
            image_update({"subfolder": "wrong"}), image_update({"type": "temp"}),
            image_update({"filename": "b" * 32 + "_00001_.png"}),
            image_update({"filename": EXECUTION_ID + "_bad.png"}),
        ]
        cases += [image_update({"filename": name}) for name in ("../escape.png", "/absolute.png", "C:\\escape.png", "\\\\host\\share.png", "a/b.png")]
        cases.append(image_update({"subfolder": "conditioning-layers-panel\\nested"}))
        for index, mutate in enumerate(cases):
            with self.subTest(case=index):
                result = self.execute(mutate)
                self.assertEqual(result.state, "failed", result)
                self.assertIsNone(result.output)
                self.assertEqual(len([request for request in self.transports[-1].requests if request[0] == "POST"]), 1)

    def test_result_and_provenance_mismatches_rejected_without_repair(self):
        self.execute()
        raw, prepared = self.raw_results[-1], self.application.prepared
        for changes in (
            {"errors": (ValidationFinding("association.error", FindingSeverity.ERROR, "Failed"),)},
            {"result_identity_fingerprint": "0" * 64}, {"bundle_fingerprint": "0" * 64},
            {"graph_fingerprint": "0" * 64}, {"prompt_id": "different"}, {"submitted": False},
            {"server_identity": None},
            {"provenance": replace(raw.provenance, execution_request_id="b" * 32)},
            {"provenance": replace(raw.provenance, seed=43)},
            {"outputs": (replace(raw.outputs[0], relative_locator="mismatched.png"),)},
            {"outputs": (replace(raw.outputs[0], node_id="19"),)},
            {"outputs": raw.outputs * 2}, {"result_version": "old"},
        ):
            with self.subTest(changes=tuple(changes)):
                self.assertEqual(accept_blend_result(prepared, replace(raw, **changes), EXECUTION_ID).state, "failed")
        self.assertEqual(accept_blend_result(prepared, raw, "b" * 32).state, "failed")

    def test_absent_component_and_weakened_association_policy_prevent_execution(self):
        self.nodes.NODE_CLASS_MAPPINGS.clear()
        with patch("conditioning_layers.execution.comfyui.blend.LocalJsonTransport", side_effect=AssertionError("No transport")):
            result = self.application.run(self.draft, EXECUTION_ID, lambda _: None)
            self.assertEqual(result.state, "rejected")
            self.assertIn("panel.blend.component_unavailable", {finding.code for finding in result.findings})
        for key in ("require_output_prefix_match", "require_expected_save_image_node"):
            self.application._host = replace(self.context, execution_policy=replace(self.context.execution_policy, **{key: False}))
            result = self.application.run(self.draft, EXECUTION_ID, lambda _: None)
            self.assertEqual(result.findings[0].code, "panel.blend.execution_contract")

    def test_resolved_output_escape_fails_closed_without_needing_symlink_privilege(self):
        self.execute()
        prepared, raw = self.application.prepared, self.raw_results[-1]
        root = prepared.bundle.host_snapshot.output_directory
        candidate = root / raw.outputs[0].relative_locator
        original = Path.resolve

        def observed_resolution(path, *args, **kwargs):
            if path == candidate:
                return root.parent / "outside" / raw.outputs[0].filename
            return original(path, *args, **kwargs)

        # Substitute only the filesystem resolution observation, not acceptance.
        with patch.object(Path, "resolve", observed_resolution):
            self.assertEqual(accept_blend_result(prepared, raw, EXECUTION_ID).state, "failed")

    def test_product_admission_still_rejects_wrong_active_count_before_staging(self):
        with patch("conditioning_layers.integrations.comfyui_panel.blend_application.prepare_blend", side_effect=AssertionError("No preparation")):
            for count in (0, 1, 2, 4, 5, 6, 7, 8, 9, 10):
                rows = tuple(replace(self.draft.layers[i % 3], row_id=f"row-{i}", layer_id=f"layer-{i}") for i in range(count))
                result = self.application.run(replace(self.draft, layers=rows), EXECUTION_ID, lambda _: None)
                self.assertEqual(result.state, "rejected")
                self.assertIn("blend.cardinality.unsupported", {finding.code for finding in result.findings})
                self.assertIsNone(result.output)

    def test_coordinator_ownership_and_browser_projection_success_and_ambiguity(self):
        for ambiguous in (False, True):
            def mutate(record):
                if ambiguous:
                    images = record["outputs"]["20"]["images"]
                    images.append({**images[0], "filename": images[0]["filename"].replace("00001", "00002")})
            coordinator, loop = PanelJobCoordinator(self.application), InlineLoop()
            with self.transport_factory(mutate):
                accepted, created = coordinator.submit(self.draft, loop)
                self.assertTrue(created)
                loop.flush()
                completed = coordinator.get(accepted.execution_id)
                repeated, created = coordinator.submit(self.draft, loop)
                self.assertFalse(created)
                self.assertEqual(repeated, completed)
            self.assertEqual(completed.state, "failed" if ambiguous else "completed", completed)
            self.assertEqual(completed.execution_id, accepted.execution_id)
            self.assertIsNone(coordinator.get("wrong-job"))
            assert_observation(self, completed.to_json(), success=not ambiguous)


class HostSelectedBlendApplicationTests(unittest.TestCase):
    """Explicit 0.37.2 QUALIFICATION_ONLY injection; in-memory transport only."""

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix="p3d-host-")))
        self.nodes = self.stack.enter_context(SUPPORT.SUPPORT.registered_component())
        sys.modules["server"].PromptServer.instance.port = 8000
        self.stack.enter_context(patch.object(sys, "argv", ["main.py", "--listen", "127.0.0.1", "--port", "8000"]))
        self.draft = replace(fixture_request(field_data=synthetic_fields(continuous=True, overlap_pair=(0, 1)),
                                            strengths=(0.0, 1e-37, 5e-324)),
                             document_version=COMPOSITION_POLICY_PROTOTYPE_VERSION, composition_policy=NORMALIZED_BLEND.reference)

    def run_host(self, name, checkout, compatibility=None):
        context, observations = fake_checkout(self.root / name, checkout)
        options = {} if compatibility is None else {"compatibility": compatibility}
        application = RecordingApplication(context, **options)
        calls = []

        def client(*args, **kwargs):
            calls.append((execute_blend_submission_bundle(*args, **kwargs), kwargs))
            return calls[-1][0]

        application._execution_client = client
        with model_file_observations(observations), patch(
            "conditioning_layers.execution.comfyui.blend.LocalJsonTransport",
            side_effect=lambda configuration: ProductMemoryTransport(application.prepared.bundle),
        ):
            result = application.run(self.draft, EXECUTION_ID, lambda _: None)
        return result, application, context, calls

    def test_explicit_0372_profile_runs_exact3_under_its_own_authority(self):
        profile = COMFYUI_0372_QUALIFICATION_PROFILE
        result, application, _, calls = self.run_host("current", profile, profile)
        self.assertEqual(result.state, "completed", result)
        bundle = application.prepared.bundle
        binding, classes = EXACT_THREE_BLEND_REALIZATION_COMFYUI_0372, BLEND_GRAPH_PERMITTED_CLASSES_COMFYUI_0372
        self.assertEqual((bundle.realization_binding_identifier, bundle.realization_binding_fingerprint),
                         (binding.identifier, binding.fingerprint))
        self.assertEqual((bundle.permitted_class_authority_identifier, bundle.permitted_class_authority_fingerprint),
                         (classes.identifier, classes.fingerprint))
        self.assertEqual(bundle.eligibility_entry_fingerprint, "aeefb8a4c0697056f42bcd7078236838df4ef15defe68f05309c993666bcda22")
        self.assertEqual(bundle.project_component_implementation_fingerprint, "46e33564c8b1327fae767099e008cf7a1f98b2b8a02c992d67f5a3fba0fd7e31")
        self.assertEqual((bundle.profile_identifier, bundle.host_snapshot.node_contract_snapshot_fingerprint),
                         (profile.inventory.comfyui_profile_identifier, profile.node_snapshot.snapshot_fingerprint))
        self.assertEqual(validate_blend_submission_bundle(bundle), ())
        (execution, options), = calls
        self.assertIs(options["trusted_snapshot"], profile.node_snapshot)
        self.assertEqual(execution.provenance.trusted_snapshot_fingerprint, profile.node_snapshot.snapshot_fingerprint)
        self.assertEqual(execution.provenance.realization_binding_fingerprint, binding.fingerprint)
        # The retained 0.34.6 route realizes the identical exact-3 graph under its own binding.
        retained, retained_application, _, _ = self.run_host("retained", DEFAULT_SUPPORTED_PROFILE)
        self.assertEqual(retained.state, "completed", retained)
        old = retained_application.prepared.bundle
        self.assertEqual(old.realization_binding_fingerprint, "8264274afbcbb7db30f3389fd03289618bfa4b99e104d0d71405f620cec3f781")
        self.assertEqual(old.to_api_graph(), bundle.to_api_graph())
        self.assertEqual(len(bundle.to_api_graph()), 20)
        self.assertNotEqual(old.graph_fingerprint, bundle.graph_fingerprint)

    def test_caller_promoted_or_unbound_hosts_reject_before_blend_preparation(self):
        promoted = replace(COMFYUI_0372_QUALIFICATION_PROFILE, status=ProfileSupportStatus.SUPPORTED)
        with patch("conditioning_layers.integrations.comfyui_panel.blend_application.capture_blend_component_availability",
                   side_effect=AssertionError("No Blend preparation")):
            result, _, context, calls = self.run_host("promoted", COMFYUI_0372_QUALIFICATION_PROFILE, promoted)
        self.assertEqual(result.state, "rejected")
        self.assertEqual({finding.code for finding in result.findings},
                         {"blend.realization.invalid", "blend.graph_classes.invalid"})
        self.assertEqual(calls, [])
        self.assertFalse((context.host_configuration.input_directory / "conditioning-layers").exists())


if __name__ == "__main__":
    unittest.main()
