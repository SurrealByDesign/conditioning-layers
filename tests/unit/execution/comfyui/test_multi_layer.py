"""The successor client is exercised entirely by an in-memory transport."""

from dataclasses import fields, replace
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from conditioning_layers.execution.comfyui import ComfyUIServerConfiguration, ComfyUIExecutionPolicy, ExecutionState, ServerIdentityMode
from conditioning_layers.comfyui.prediction_mixing.multi_layer.authority import SNAPSHOT
from conditioning_layers.execution.comfyui.client import execute_submission_bundle
from conditioning_layers.execution.comfyui.errors import ProtocolFailure
from conditioning_layers.execution.comfyui.multi_layer import (
    EXECUTION_CLIENT_VERSION, EXECUTION_PROVENANCE_VERSION, EXECUTION_RESULT_VERSION,
    build_multi_layer_execution_provenance, execute_multi_layer_submission_bundle,
    fingerprint_multi_layer_result_identity, validate_multi_layer_execution_provenance,
)
from conditioning_layers.runtime.comfyui.multi_layer import fingerprint_portable


def _load_support():
    path = Path(__file__).resolve().parents[2] / "runtime" / "comfyui" / "test_multi_layer_bundle.py"
    spec = importlib.util.spec_from_file_location("_p2b_multi_layer_runtime_support", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SUPPORT = _load_support()
PROMPT_ID = "11111111-1111-4111-8111-111111111111"


class MemoryTransport:
    def __init__(self, bundle):
        self.bundle = bundle
        self.requests = []
        self.submission_failure = None
        self.response = {"prompt_id": PROMPT_ID}
        self.history_state = "success"
        self.save_node_id = "19"
        self.version = bundle.host_snapshot.observed_comfyui_version
        self.configuration = ComfyUIServerConfiguration(port=9)
        self.semantic = False
        self.malformed_node = None

    def get_json(self, path):
        self.requests.append(("GET", path, None))
        if path == "/system_stats":
            return {"system": {
                "comfyui_version": self.version,
                "git_revision": None if self.semantic else self.bundle.host_snapshot.observed_comfyui_revision,
                "argv": ["main.py", "--listen", "127.0.0.1", "--port", "9"] if self.semantic else [],
            }, "devices": []}
        if path == "/queue":
            return {"queue_running": [], "queue_pending": []}
        if path == f"/history/{PROMPT_ID}":
            return {PROMPT_ID: {
                "status": {"status_str": self.history_state, "completed": self.history_state == "success", "messages": []},
                "outputs": {self.save_node_id: {"images": [{
                    "filename": "request-1_00001_.png", "subfolder": "conditioning-layers/p2b", "type": "output",
                }]}},
            }}
        raise AssertionError(f"Unexpected offline request: {path}")

    def get_required_node_contract(self, node_class):
        self.requests.append(("GET", f"/object_info/{node_class}", None))
        if node_class == self.malformed_node:
            return {node_class: {}}
        contract = SNAPSHOT.contracts[node_class]
        required, optional = {}, {}
        for evidence in contract.input_evidence:
            enum_values = list(evidence.enum_values)
            if evidence.external_enumeration is not None:
                enum_values.extend(sorted({
                    node["inputs"][evidence.name]
                    for node in self.bundle.to_api_graph().values()
                    if node["class_type"] == node_class and evidence.name in node["inputs"]
                }))
            options = {}
            if evidence.default_value is not None:
                options["default"] = evidence.default_value
            descriptor = enum_values if enum_values else evidence.accepted_type
            target = required if evidence.host_requirement == "required" else optional
            target[evidence.name] = [descriptor, options]
        return {node_class: {
            "name": node_class, "input": {"required": required, "optional": optional},
            "output": list(contract.return_types),
        }}

    def post_json(self, path, payload):
        self.requests.append(("POST", path, payload))
        if path != "/prompt":
            raise AssertionError(f"Unexpected offline POST: {path}")
        if self.submission_failure:
            raise self.submission_failure
        return self.response


class MultiLayerExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.fence = SUPPORT.offline_fence()
        self.fence.__enter__()
        self.bundle, _, _, _ = SUPPORT.make_prepared(Path(self.temporary.name))
        self.configuration = ComfyUIServerConfiguration(port=9)
        self.policy = ComfyUIExecutionPolicy()

    def tearDown(self):
        self.fence.__exit__(None, None, None)
        self.temporary.cleanup()

    def execute(self, transport, bundle=None):
        with patch("conditioning_layers.execution.comfyui.multi_layer.LocalJsonTransport", return_value=transport):
            return execute_multi_layer_submission_bundle(bundle or self.bundle, self.configuration, self.policy)

    def test_successor_client_submits_one_in_memory_prompt_and_associates_exact_output(self):
        transport = MemoryTransport(self.bundle)
        result = self.execute(transport)
        self.assertTrue(result.completed, result.errors)
        self.assertFalse(result.errors)
        prompts = [item for item in transport.requests if item[:2] == ("POST", "/prompt")]
        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0][2]["prompt"], self.bundle.to_api_graph())
        self.assertEqual(result.result_version, EXECUTION_RESULT_VERSION)
        self.assertEqual(result.provenance.provenance_version, EXECUTION_PROVENANCE_VERSION)
        self.assertEqual(result.provenance.client_version_identifier, EXECUTION_CLIENT_VERSION)
        self.assertEqual(result.provenance.exact_admitted_cardinality, 3)
        self.assertEqual(tuple(item.layer_id for item in result.provenance.active_layers), ("a", "b", "c"))
        self.assertEqual(result.outputs[0].node_id, "19")
        self.assertEqual(validate_multi_layer_execution_provenance(result.provenance, self.bundle), ())

    def test_repeated_execution_records_have_deterministic_portable_identity(self):
        first = self.execute(MemoryTransport(self.bundle))
        second = self.execute(MemoryTransport(self.bundle))
        self.assertEqual(first.provenance.provenance_fingerprint, second.provenance.provenance_fingerprint)
        self.assertEqual(first.result_identity_fingerprint, second.result_identity_fingerprint)
        self.assertEqual(first.result_identity_fingerprint, fingerprint_multi_layer_result_identity(first.provenance))

    def test_absent_revision_uses_retained_semantic_identity_with_all_eleven_classes(self):
        transport = MemoryTransport(self.bundle)
        transport.semantic = True
        result = self.execute(transport)
        self.assertTrue(result.completed, result.errors)
        self.assertIs(result.provenance.server_identity_mode, ServerIdentityMode.SEMANTIC_CONTRACT)
        contracts = [item[1] for item in transport.requests if item[1].startswith("/object_info/")]
        self.assertEqual(contracts, [f"/object_info/{name}" for name in SNAPSHOT.contracts])
        self.assertEqual(len([item for item in transport.requests if item[0] == "POST"]), 1)

    def test_semantic_contract_mismatch_has_no_submission(self):
        transport = MemoryTransport(self.bundle)
        transport.semantic, transport.malformed_node = True, "ConditioningCombine"
        result = self.execute(transport)
        self.assertFalse(result.submitted)
        self.assertFalse(any(item[0] == "POST" for item in transport.requests))

    def test_bundle_or_cardinality_tampering_never_constructs_transport(self):
        for bundle in (
            replace(self.bundle, exact_admitted_cardinality=2),
            replace(self.bundle, bundle_fingerprint="0" * 64),
            replace(self.bundle, submission_ready=False),
            replace(self.bundle, provenance=replace(self.bundle.provenance, exact_admitted_cardinality=4)),
            replace(self.bundle, staged_assets=(None,)),
            replace(self.bundle, host_snapshot=None),
        ):
            with self.subTest(bundle=bundle.bundle_fingerprint), patch(
                "conditioning_layers.execution.comfyui.multi_layer.LocalJsonTransport",
                side_effect=AssertionError("Invalid input must not construct a transport"),
            ):
                result = execute_multi_layer_submission_bundle(bundle, self.configuration, self.policy)
            self.assertIs(result.terminal_state, ExecutionState.NOT_SUBMITTED)
            self.assertFalse(result.submitted)
            self.assertIsNone(result.provenance)

    def test_changed_staged_field_never_constructs_transport(self):
        self.bundle.staged_assets[0].destination_path.write_bytes(b"changed")
        with patch("conditioning_layers.execution.comfyui.multi_layer.LocalJsonTransport", side_effect=AssertionError("must not submit")):
            result = execute_multi_layer_submission_bundle(self.bundle, self.configuration, self.policy)
        self.assertFalse(result.submitted)
        self.assertTrue(result.errors)

    def test_server_identity_failure_has_no_prompt(self):
        transport = MemoryTransport(self.bundle)
        transport.version = "99.0.0"
        result = self.execute(transport)
        self.assertFalse(result.submitted)
        self.assertEqual(len(transport.requests), 1)
        self.assertIs(result.terminal_state, ExecutionState.NOT_SUBMITTED)

    def test_submission_failure_and_malformed_response_have_no_retry(self):
        for failure, response, expected in (
            (ProtocolFailure("execution.submission_http", "rejected"), None, ExecutionState.NOT_SUBMITTED),
            (ProtocolFailure("execution.submission_response", "uncertain"), None, ExecutionState.UNKNOWN),
            (None, {}, ExecutionState.UNKNOWN),
        ):
            with self.subTest(expected=expected, response=response):
                transport = MemoryTransport(self.bundle)
                transport.submission_failure, transport.response = failure, response
                result = self.execute(transport)
                self.assertIs(result.terminal_state, expected)
                self.assertEqual(len([item for item in transport.requests if item[0] == "POST"]), 1)

    def test_wrong_output_node_is_rejected(self):
        transport = MemoryTransport(self.bundle)
        transport.save_node_id = "18"
        result = self.execute(transport)
        self.assertTrue(result.errors)
        self.assertFalse(result.outputs)
        self.assertIn("execution.output_unsafe", {item.code for item in result.errors})

    def test_explicit_provenance_cardinality_mismatch_fails_even_when_resigned(self):
        provenance = self.execute(MemoryTransport(self.bundle)).provenance
        for change in (
            {"exact_admitted_cardinality": 4}, {"exact_admitted_cardinality": 3.0},
            {"execution_profile_fingerprint": "0" * 64}, {"active_layers": provenance.active_layers[::-1]},
            {"active_layers": list(provenance.active_layers)}, {"server_version": "99.0.0"},
            {"server_profile_identifier": "unknown"}, {"trusted_snapshot_fingerprint": "0" * 64},
            {"server_identity_mode": "exact_revision"},
        ):
            changed = replace(provenance, **change)
            payload = {item.name: getattr(changed, item.name) for item in fields(changed) if item.name != "provenance_fingerprint"}
            changed = replace(changed, provenance_fingerprint=fingerprint_portable(payload))
            self.assertTrue(validate_multi_layer_execution_provenance(changed, self.bundle))

    def test_predecessor_client_does_not_accept_successor_bundle(self):
        with self.assertRaises(TypeError):
            execute_submission_bundle(self.bundle, self.configuration, self.policy)


if __name__ == "__main__":
    unittest.main()
