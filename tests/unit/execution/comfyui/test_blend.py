"""Blend successor transport paths run only against an in-memory fake host."""

from dataclasses import fields, replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from conditioning_layers.execution.comfyui import ComfyUIServerConfiguration, ComfyUIExecutionPolicy, ExecutionState
from conditioning_layers.execution.comfyui.blend import (
    EXECUTION_CLIENT_VERSION, EXECUTION_PROVENANCE_VERSION, EXECUTION_RESULT_VERSION,
    execute_blend_submission_bundle, validate_blend_execution_provenance,
)
from conditioning_layers.runtime.comfyui.blend import fingerprint_portable


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


SUPPORT = load_module("_p3c_blend_bundle_support", Path(__file__).resolve().parents[2] / "runtime" / "comfyui" / "test_blend_bundle.py")
RETAINED = load_module("_p3c_retained_execution_support", Path(__file__).with_name("test_multi_layer.py"))


class MemoryTransport(RETAINED.MemoryTransport):
    def __init__(self, bundle):
        super().__init__(bundle)
        self.save_node_id = next(identifier for identifier, node in bundle.to_api_graph().items() if node["class_type"] == "SaveImage")
        self.argv = list(SUPPORT.ARGV)
        self.after_identity = None
        self.after_history = None

    def get_json(self, path):
        value = super().get_json(path)
        if path == "/system_stats":
            value["system"]["argv"] = self.argv
            if self.after_identity is not None:
                self.after_identity()
        elif path.startswith("/history/") and self.after_history is not None:
            self.after_history()
        return value


class BlendExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.fence = SUPPORT.SUPPORT.offline_fence()
        self.fence.__enter__()
        self.registration = SUPPORT.registered_component()
        self.nodes = self.registration.__enter__()
        self.bundle, _, _, _ = SUPPORT.make_prepared(Path(self.temporary.name), overlapping=True)
        self.configuration = ComfyUIServerConfiguration(port=9)
        self.policy = ComfyUIExecutionPolicy()

    def tearDown(self):
        self.registration.__exit__(None, None, None)
        self.fence.__exit__(None, None, None)
        self.temporary.cleanup()

    def execute(self, transport, bundle=None):
        with patch("conditioning_layers.execution.comfyui.blend.LocalJsonTransport", return_value=transport):
            return execute_blend_submission_bundle(bundle or self.bundle, self.configuration, self.policy)

    def test_one_in_memory_submission_successor_records_and_deterministic_identity(self):
        first = self.execute(MemoryTransport(self.bundle))
        transport = MemoryTransport(self.bundle)
        second = self.execute(transport)
        self.assertTrue(first.completed, first.errors)
        self.assertFalse(first.errors)
        self.assertEqual(first.result_version, EXECUTION_RESULT_VERSION)
        self.assertEqual(first.provenance.provenance_version, EXECUTION_PROVENANCE_VERSION)
        self.assertEqual(first.provenance.client_version_identifier, EXECUTION_CLIENT_VERSION)
        self.assertEqual(first.result_identity_fingerprint, second.result_identity_fingerprint)
        self.assertEqual(validate_blend_execution_provenance(first.provenance, self.bundle), ())
        self.assertEqual(len([item for item in transport.requests if item[0] == "POST"]), 1)
        self.assertEqual(first.provenance.project_component_implementation_fingerprint, self.bundle.project_component_implementation_fingerprint)

    def test_missing_component_rejects_before_transport(self):
        self.nodes.NODE_CLASS_MAPPINGS.clear()
        with patch("conditioning_layers.execution.comfyui.blend.LocalJsonTransport", side_effect=AssertionError("offline: transport must not exist")):
            result = execute_blend_submission_bundle(self.bundle, self.configuration, self.policy)
        self.assertFalse(result.submitted)
        self.assertIs(result.terminal_state, ExecutionState.NOT_SUBMITTED)
        self.assertIsNone(result.provenance)

    def test_identity_forgery_and_staged_mutation_fail_before_transport(self):
        forged = replace(self.bundle, project_component_implementation_fingerprint="0" * 64)
        with patch("conditioning_layers.execution.comfyui.blend.LocalJsonTransport", side_effect=AssertionError("offline: transport must not exist")):
            self.assertFalse(execute_blend_submission_bundle(forged, self.configuration, self.policy).submitted)
            self.bundle.staged_assets[0].destination_path.write_bytes(b"changed")
            self.assertFalse(execute_blend_submission_bundle(self.bundle, self.configuration, self.policy).submitted)

    def test_unqualified_fp16_runtime_arguments_have_zero_submission(self):
        transport = MemoryTransport(self.bundle)
        transport.argv += ["--fp16-intermediates"]
        result = self.execute(transport)
        self.assertFalse(result.submitted)
        self.assertFalse(any(item[0] == "POST" for item in transport.requests))

    def test_local_source_observation_cannot_attest_a_different_host_process(self):
        sys.modules["server"].PromptServer.instance.port = 1234
        transport = MemoryTransport(self.bundle)
        result = self.execute(transport)
        self.assertFalse(result.submitted)
        self.assertFalse(any(item[0] == "POST" for item in transport.requests))

    def test_registration_loss_during_identity_verification_prevents_submission(self):
        transport = MemoryTransport(self.bundle)
        transport.after_identity = self.nodes.NODE_CLASS_MAPPINGS.clear
        result = self.execute(transport)
        self.assertFalse(result.submitted)
        self.assertFalse(any(item[0] == "POST" for item in transport.requests))

    def test_registration_loss_after_submission_does_not_accept_output_or_retry(self):
        transport = MemoryTransport(self.bundle)
        transport.after_history = self.nodes.NODE_CLASS_MAPPINGS.clear
        result = self.execute(transport)
        self.assertTrue(result.submitted)
        self.assertFalse(result.completed)
        self.assertIs(result.terminal_state, ExecutionState.UNKNOWN)
        self.assertIsNone(result.provenance)
        self.assertFalse(result.outputs)
        self.assertTrue(result.errors)
        self.assertEqual(len([item for item in transport.requests if item[0] == "POST"]), 1)

    def test_provenance_resigning_cannot_change_policy_or_project_identity(self):
        provenance = self.execute(MemoryTransport(self.bundle)).provenance
        for changes in (
            {"composition_policy_identifier": "unknown"},
            {"project_component_implementation_fingerprint": "0" * 64},
            {"permitted_class_authority_fingerprint": "0" * 64},
            {"exact_admitted_cardinality": 4},
        ):
            changed = replace(provenance, **changes)
            payload = {field.name: getattr(changed, field.name) for field in fields(changed) if field.name != "provenance_fingerprint"}
            changed = replace(changed, provenance_fingerprint=fingerprint_portable(payload))
            self.assertTrue(validate_blend_execution_provenance(changed, self.bundle))

    def test_retained_client_cannot_consume_blend_bundle(self):
        from conditioning_layers.execution.comfyui.multi_layer import execute_multi_layer_submission_bundle
        with self.assertRaises(TypeError):
            execute_multi_layer_submission_bundle(self.bundle, self.configuration, self.policy)


if __name__ == "__main__":
    unittest.main()
