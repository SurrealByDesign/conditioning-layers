from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from conditioning_layers.execution.comfyui import (
    ComfyUIExecutionPolicy,
    ComfyUIServerConfiguration,
    ExecutionState,
    ServerIdentityMode,
    execute_submission_bundle,
)

from _support import (
    PROMPT_ID,
    FakeComfyUI,
    Response,
    codes,
    completed_history,
    configure_success,
    identity_payload,
    make_bundle,
)


class ExecutionClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.bundle = make_bundle(self.root)
        self.policy = ComfyUIExecutionPolicy()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_ready_bundle_submits_exactly_once_and_preserves_exact_graph(self) -> None:
        with FakeComfyUI() as server:
            configure_success(server, self.bundle)
            result = execute_submission_bundle(self.bundle, server.config(), self.policy)
        prompt_requests = [item for item in server.requests if item[:2] == ("POST", "/prompt")]
        self.assertEqual(len(prompt_requests), 1)
        self.assertEqual(prompt_requests[0][2]["prompt"], self.bundle.to_api_graph())
        self.assertEqual(result.prompt_id, PROMPT_ID)
        self.assertEqual(result.terminal_state, ExecutionState.COMPLETED)
        self.assertTrue(result.submitted)
        self.assertTrue(result.completed)
        self.assertEqual(len(result.outputs), 1)
        self.assertIn("execution.completed", codes(result.information))

    def test_queued_running_completed_state_sequence(self) -> None:
        with FakeComfyUI() as server:
            server.add("GET", "/system_stats", Response(payload=identity_payload(self.bundle)))
            server.add("POST", "/prompt", Response(payload={"prompt_id": PROMPT_ID}))
            server.add(
                "GET",
                "/queue",
                Response(payload={"queue_running": [], "queue_pending": [[0, PROMPT_ID]]}),
                Response(payload={"queue_running": [[0, PROMPT_ID]], "queue_pending": []}),
                Response(payload={"queue_running": [], "queue_pending": []}),
            )
            server.add(
                "GET",
                f"/history/{PROMPT_ID}",
                Response(payload={}),
                Response(payload={}),
                Response(payload=completed_history(self.bundle)),
            )
            result = execute_submission_bundle(self.bundle, server.config(), self.policy)
        self.assertEqual(
            tuple(item.state for item in result.observations),
            (ExecutionState.QUEUED, ExecutionState.RUNNING, ExecutionState.COMPLETED),
        )

    def test_not_ready_and_tampered_graph_are_rejected_before_network(self) -> None:
        graph = self.bundle.to_api_graph()
        graph[next(iter(graph))]["class_type"] = "Tampered"
        cases = (
            replace(self.bundle, submission_ready=False),
            replace(self.bundle, graph_mapping=graph),
        )
        for bundle in cases:
            with self.subTest(ready=bundle.submission_ready):
                result = execute_submission_bundle(
                    bundle,
                    ComfyUIServerConfiguration(port=9),
                    self.policy,
                )
                self.assertEqual(result.terminal_state, ExecutionState.NOT_SUBMITTED)
                self.assertFalse(result.submitted)
                self.assertTrue(
                    {"execution.bundle_not_ready", "execution.bundle_fingerprint"}
                    & codes(result.errors)
                )

    def test_identity_failure_never_posts_graph(self) -> None:
        for identity in (
            identity_payload(self.bundle, comfyui_version="99.0.0"),
            identity_payload(self.bundle, git_revision=None, argv=[]),
        ):
            with self.subTest(identity=identity), FakeComfyUI() as server:
                server.add("GET", "/system_stats", Response(payload=identity))
                result = execute_submission_bundle(self.bundle, server.config(), self.policy)
                self.assertEqual(result.terminal_state, ExecutionState.NOT_SUBMITTED)
                self.assertIn("execution.server_identity_unverified", codes(result.errors))
                self.assertFalse(any(path == "/prompt" for _, path, _ in server.requests))

    def test_malformed_submission_response_and_http_error_do_not_retry(self) -> None:
        responses = (
            Response(payload={}),
            Response(raw_body=b"{"),
            Response(status=400, payload={"error": "bad"}),
        )
        expected_codes = (
            "execution.prompt_id",
            "execution.submission_response",
            "execution.submission_http",
        )
        for response, expected_code in zip(responses, expected_codes, strict=True):
            with self.subTest(expected_code=expected_code), FakeComfyUI() as server:
                server.add("GET", "/system_stats", Response(payload=identity_payload(self.bundle)))
                server.add("POST", "/prompt", response)
                result = execute_submission_bundle(self.bundle, server.config(), self.policy)
                prompt_posts = [item for item in server.requests if item[:2] == ("POST", "/prompt")]
                self.assertEqual(len(prompt_posts), 1)
                self.assertIn(expected_code, codes(result.errors))
                self.assertFalse(result.completed)
                self.assertEqual(
                    result.terminal_state,
                    ExecutionState.UNKNOWN
                    if expected_code != "execution.submission_http"
                    else ExecutionState.NOT_SUBMITTED,
                )

    def test_oversized_request_is_blocked_without_prompt_post(self) -> None:
        with FakeComfyUI() as server:
            server.add("GET", "/system_stats", Response(payload=identity_payload(self.bundle)))
            result = execute_submission_bundle(
                self.bundle,
                server.config(maximum_request_bytes=1024),
                self.policy,
            )
        self.assertEqual(result.terminal_state, ExecutionState.UNKNOWN)
        self.assertIn("execution.submission_response", codes(result.errors))
        self.assertFalse(any(path == "/prompt" for _, path, _ in server.requests))

    def test_execution_failure_is_terminal_not_completion(self) -> None:
        history = {
            PROMPT_ID: {
                "status": {"status_str": "error", "completed": False, "messages": []},
                "outputs": {},
            }
        }
        with FakeComfyUI() as server:
            server.add("GET", "/system_stats", Response(payload=identity_payload(self.bundle)))
            server.add("POST", "/prompt", Response(payload={"prompt_id": PROMPT_ID}))
            server.add("GET", "/queue", Response(payload={"queue_running": [], "queue_pending": []}))
            server.add("GET", f"/history/{PROMPT_ID}", Response(payload=history))
            result = execute_submission_bundle(self.bundle, server.config(), self.policy)
        self.assertEqual(result.terminal_state, ExecutionState.FAILED)
        self.assertIn("execution.failed", codes(result.errors))
        self.assertFalse(result.completed)

    def test_interrupted_history_is_distinct_from_failure(self) -> None:
        history = {
            PROMPT_ID: {
                "status": {
                    "status_str": "error",
                    "completed": False,
                    "messages": [["execution_interrupted", {}]],
                },
                "outputs": {},
            }
        }
        with FakeComfyUI() as server:
            server.add("GET", "/system_stats", Response(payload=identity_payload(self.bundle)))
            server.add("POST", "/prompt", Response(payload={"prompt_id": PROMPT_ID}))
            server.add("GET", "/queue", Response(payload={"queue_running": [], "queue_pending": []}))
            server.add("GET", f"/history/{PROMPT_ID}", Response(payload=history))
            result = execute_submission_bundle(self.bundle, server.config(), self.policy)
        self.assertEqual(result.terminal_state, ExecutionState.INTERRUPTED)
        self.assertIn("execution.interrupted", codes(result.errors))

    def test_server_unreachable_after_submission_becomes_unknown(self) -> None:
        with FakeComfyUI() as server:
            server.add("GET", "/system_stats", Response(payload=identity_payload(self.bundle)))
            server.add("POST", "/prompt", Response(payload={"prompt_id": PROMPT_ID}))
            server.add("GET", "/queue", Response(disconnect=True))
            result = execute_submission_bundle(self.bundle, server.config(), self.policy)
        self.assertEqual(result.terminal_state, ExecutionState.UNKNOWN)
        self.assertIn("execution.connection", codes(result.errors))
        self.assertTrue(result.submitted)

    def test_result_provenance_is_portable_and_preserves_identity(self) -> None:
        with FakeComfyUI() as server:
            configure_success(server, self.bundle)
            result = execute_submission_bundle(self.bundle, server.config(), self.policy)
        serialized = json.dumps(result.provenance.__dict__ if hasattr(result.provenance, "__dict__") else {
            name: str(getattr(result.provenance, name))
            for name in result.provenance.__dataclass_fields__
        })
        self.assertNotIn(str(self.root), serialized)
        self.assertEqual(result.provenance.prompt_id, PROMPT_ID)
        self.assertEqual(result.provenance.terminal_state, ExecutionState.COMPLETED)
        self.assertEqual(result.provenance.bundle_fingerprint, self.bundle.bundle_fingerprint)
        self.assertEqual(result.provenance.graph_fingerprint, self.bundle.graph_fingerprint)
        self.assertIs(
            result.provenance.server_identity_mode,
            ServerIdentityMode.EXACT_REVISION,
        )
        self.assertEqual(
            result.provenance.reported_server_revision,
            self.bundle.provenance.comfyui_revision,
        )
        self.assertEqual(
            result.provenance.server_identity_finding_codes,
            ("execution.server_identity_exact",),
        )
        self.assertEqual(
            result.provenance.output_locators,
            ("conditioning-layers/document-1/request-1_00001_.png",),
        )

    def test_execution_never_deletes_staged_assets(self) -> None:
        before = tuple(item.destination_path.read_bytes() for item in self.bundle.staged_assets)
        with FakeComfyUI() as server:
            configure_success(server, self.bundle)
            result = execute_submission_bundle(self.bundle, server.config(), self.policy)
        after = tuple(item.destination_path.read_bytes() for item in self.bundle.staged_assets)
        self.assertEqual(before, after)
        self.assertEqual(result.cleanup_recommendation.state.value, "retain")

    def test_checksum_safe_cleanup_is_only_recommended_for_review(self) -> None:
        policy = ComfyUIExecutionPolicy(retain_staged_assets=False)
        with FakeComfyUI() as server:
            configure_success(server, self.bundle)
            result = execute_submission_bundle(self.bundle, server.config(), policy)
        self.assertEqual(
            result.cleanup_recommendation.state.value,
            "review_checksum_safe_plan",
        )
        self.assertTrue(result.cleanup_recommendation.cleanup_plan.safe_to_execute_elsewhere)
        self.assertTrue(all(item.destination_path.exists() for item in self.bundle.staged_assets))


if __name__ == "__main__":
    unittest.main()
