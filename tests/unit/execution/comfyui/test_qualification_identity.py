from __future__ import annotations

from dataclasses import replace
import inspect
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui.prediction_mixing import (
    COMFYUI_0280_SUPPORTED_PROFILE,
    COMFYUI_0345_QUALIFICATION_PROFILE,
    DEFAULT_SUPPORTED_PROFILE,
)
from conditioning_layers.execution.comfyui import (
    ComfyUIExecutionPolicy,
    ComfyUIServerConfiguration,
    ExecutionState,
    ServerIdentityMode,
    execute_submission_bundle,
)
from conditioning_layers.execution.comfyui.errors import ProtocolFailure
from conditioning_layers.execution.comfyui.protocol import establish_server_identity
from conditioning_layers.runtime.comfyui import prepare_submission_bundle

from _support import (
    PROMPT_ID,
    _RUNTIME_SUPPORT,
    codes,
    completed_history,
    identity_payload,
    object_info_payload,
    semantic_identity_payload,
)


M2 = COMFYUI_0280_SUPPORTED_PROFILE
QUALIFICATION = COMFYUI_0345_QUALIFICATION_PROFILE


class OfflineTransport:
    """In-memory execution responses; never opens a socket or contacts a host."""

    def __init__(self, bundle, snapshot, *, exact_revision: bool = False):
        self.configuration = ComfyUIServerConfiguration()
        self.requests = []
        self.responses = {
            "/system_stats": (
                identity_payload(bundle)
                if exact_revision
                else semantic_identity_payload(bundle, self.configuration.port)
            ),
            "/queue": {"queue_running": [], "queue_pending": []},
            f"/history/{PROMPT_ID}": completed_history(bundle),
        }
        for node_class in snapshot.contracts:
            self.responses[f"/object_info/{node_class}"] = object_info_payload(
                bundle, node_class, node_snapshot=snapshot
            )

    def get_json(self, endpoint):
        self.requests.append(("GET", endpoint, None))
        return self.responses[endpoint]

    def get_required_node_contract(self, node_class):
        return self.get_json(f"/object_info/{node_class}")

    def post_json(self, endpoint, payload):
        if endpoint != "/prompt":
            raise AssertionError(f"Unexpected offline POST: {endpoint}")
        self.requests.append(("POST", endpoint, payload))
        return {"prompt_id": PROMPT_ID}


class QualificationExecutionIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.bundles = {}
        for name, profile in (("m2", M2), ("qualification", QUALIFICATION), ("current", DEFAULT_SUPPORTED_PROFILE)):
            case = _RUNTIME_SUPPORT.make_case(root / name, profile.inventory)
            prepared = prepare_submission_bundle(
                case.artifact,
                case.provenance,
                case.inventory,
                case.configuration,
                case.inspections,
                case.asset_root,
                profile.node_snapshot,
            )
            self.assertTrue(prepared.ready, prepared.errors)
            self.assertIsNotNone(prepared.bundle)
            self.bundles[name] = prepared.bundle

    def test_execution_keywords_preserve_exact_m2_snapshot_default(self) -> None:
        for function in (establish_server_identity, execute_submission_bundle):
            with self.subTest(function=function.__name__):
                parameter = inspect.signature(function).parameters["trusted_snapshot"]
                self.assertIs(parameter.kind, inspect.Parameter.KEYWORD_ONLY)
                self.assertIs(parameter.default, M2.node_snapshot)

    def test_exact_revision_route_is_unchanged_for_both_profiles(self) -> None:
        for name, profile in (("m2", M2), ("qualification", QUALIFICATION)):
            with self.subTest(profile=name):
                bundle = self.bundles[name]
                transport = OfflineTransport(bundle, profile.node_snapshot, exact_revision=True)
                identity = establish_server_identity(transport, bundle)
                self.assertIs(identity.identity_mode, ServerIdentityMode.EXACT_REVISION)
                self.assertEqual(identity.comfyui_revision, profile.inventory.expected_comfyui_revision)
                self.assertEqual(identity.finding_codes, ("execution.server_identity_exact",))
                self.assertEqual(
                    identity.trusted_snapshot_fingerprint,
                    bundle.host_snapshot.node_contract_snapshot_fingerprint,
                )
                self.assertEqual(transport.requests, [("GET", "/system_stats", None)])

    def test_reported_revision_mismatch_does_not_fall_back_to_semantics(self) -> None:
        for name, profile in (("m2", M2), ("qualification", QUALIFICATION)):
            with self.subTest(profile=name):
                bundle = self.bundles[name]
                transport = OfflineTransport(bundle, profile.node_snapshot, exact_revision=True)
                transport.responses["/system_stats"]["system"]["git_revision"] = "f" * 40
                with self.assertRaises(ProtocolFailure) as raised:
                    establish_server_identity(
                        transport, bundle, trusted_snapshot=profile.node_snapshot
                    )
                self.assertEqual(raised.exception.code, "execution.server_revision")
                self.assertEqual(transport.requests, [("GET", "/system_stats", None)])

    def test_malformed_reported_revision_still_fails_without_semantic_fallback(self) -> None:
        bundle = self.bundles["qualification"]
        transport = OfflineTransport(bundle, QUALIFICATION.node_snapshot, exact_revision=True)
        transport.responses["/system_stats"]["system"]["git_revision"] = "unverified"
        with self.assertRaises(ProtocolFailure) as raised:
            establish_server_identity(
                transport, bundle, trusted_snapshot=QUALIFICATION.node_snapshot
            )
        self.assertEqual(raised.exception.code, "execution.server_identity_unverified")
        self.assertEqual(transport.requests, [("GET", "/system_stats", None)])

    def test_default_semantic_route_uses_m2_evidence(self) -> None:
        bundle = self.bundles["m2"]
        transport = OfflineTransport(bundle, M2.node_snapshot)
        identity = establish_server_identity(transport, bundle)
        self.assert_semantic_identity(identity, transport, M2)

    def test_qualification_semantic_route_uses_injected_evidence(self) -> None:
        bundle = self.bundles["qualification"]
        transport = OfflineTransport(bundle, QUALIFICATION.node_snapshot)
        identity = establish_server_identity(
            transport, bundle, trusted_snapshot=QUALIFICATION.node_snapshot
        )
        self.assert_semantic_identity(identity, transport, QUALIFICATION)

    def test_semantic_route_rejects_cross_profile_snapshots_before_contract_requests(self) -> None:
        for name, profile, snapshot in (
            ("qualification", QUALIFICATION, M2.node_snapshot),
            ("m2", M2, QUALIFICATION.node_snapshot),
        ):
            with self.subTest(profile=name):
                bundle = self.bundles[name]
                transport = OfflineTransport(bundle, profile.node_snapshot)
                with self.assertRaises(ProtocolFailure) as raised:
                    establish_server_identity(transport, bundle, trusted_snapshot=snapshot)
                self.assertEqual(raised.exception.code, "execution.server_identity_unverified")
                self.assertEqual(transport.requests, [("GET", "/system_stats", None)])

    def test_stale_qualification_snapshot_fails_before_contract_requests(self) -> None:
        bundle = self.bundles["qualification"]
        for snapshot in self.stale_snapshots():
            with self.subTest(snapshot=snapshot.snapshot_fingerprint, unresolved=snapshot.unresolved_items):
                transport = OfflineTransport(bundle, QUALIFICATION.node_snapshot)
                with self.assertRaises(ProtocolFailure) as raised:
                    establish_server_identity(transport, bundle, trusted_snapshot=snapshot)
                self.assertEqual(raised.exception.code, "execution.server_identity_unverified")
                self.assertEqual(transport.requests, [("GET", "/system_stats", None)])

    def test_stale_prepared_snapshot_binding_fails_before_contract_requests(self) -> None:
        bundle = self.bundles["qualification"]
        for changed in (
            replace(bundle, host_snapshot=replace(
                bundle.host_snapshot, node_contract_snapshot_fingerprint="0" * 64
            )),
            replace(bundle, provenance=replace(
                bundle.provenance, node_contract_snapshot_fingerprint="0" * 64
            )),
        ):
            with self.subTest(host=changed.host_snapshot.node_contract_snapshot_fingerprint):
                transport = OfflineTransport(changed, QUALIFICATION.node_snapshot)
                with self.assertRaises(ProtocolFailure) as raised:
                    establish_server_identity(
                        transport, changed, trusted_snapshot=QUALIFICATION.node_snapshot
                    )
                self.assertEqual(raised.exception.code, "execution.server_identity_unverified")
                self.assertEqual(transport.requests, [("GET", "/system_stats", None)])

    def test_client_default_and_qualification_preserve_submission_and_output_association(self) -> None:
        for name, profile, keywords in (
            ("m2", M2, {}),
            ("qualification", QUALIFICATION, {"trusted_snapshot": QUALIFICATION.node_snapshot}),
            ("current", DEFAULT_SUPPORTED_PROFILE, {"trusted_snapshot": DEFAULT_SUPPORTED_PROFILE.node_snapshot}),
        ):
            with self.subTest(profile=name):
                bundle = self.bundles[name]
                transport = OfflineTransport(bundle, profile.node_snapshot)
                result = self.execute_offline(bundle, transport, **keywords)
                self.assertIs(result.terminal_state, ExecutionState.COMPLETED)
                self.assertTrue(result.completed)
                self.assertTrue(result.submitted)
                self.assertEqual(result.prompt_id, PROMPT_ID)
                self.assertEqual(len(result.outputs), 1)
                self.assertFalse(result.errors)
                self.assertEqual(
                    result.provenance.trusted_snapshot_fingerprint,
                    profile.node_snapshot.snapshot_fingerprint,
                )
                posts = [item for item in transport.requests if item[0] == "POST"]
                self.assertEqual(posts, [("POST", "/prompt", {"prompt": bundle.to_api_graph()})])
                self.assertEqual(
                    [path for method, path, _ in transport.requests if path.startswith("/history/")],
                    [f"/history/{PROMPT_ID}"],
                )

    def test_client_default_cannot_semantically_execute_qualification_bundle(self) -> None:
        bundle = self.bundles["qualification"]
        transport = OfflineTransport(bundle, QUALIFICATION.node_snapshot)
        result = self.execute_offline(bundle, transport)
        self.assert_not_submitted(result, transport, "execution.server_identity_unverified")
        self.assertEqual(transport.requests, [("GET", "/system_stats", None)])

    def test_client_wrong_or_stale_snapshot_never_posts(self) -> None:
        bundle = self.bundles["qualification"]
        for snapshot in (M2.node_snapshot, *self.stale_snapshots()):
            with self.subTest(snapshot=snapshot.snapshot_fingerprint, unresolved=snapshot.unresolved_items):
                transport = OfflineTransport(bundle, QUALIFICATION.node_snapshot)
                result = self.execute_offline(bundle, transport, trusted_snapshot=snapshot)
                self.assert_not_submitted(result, transport, "execution.server_identity_unverified")
                self.assertEqual(transport.requests, [("GET", "/system_stats", None)])

    def test_client_altered_qualification_contract_never_posts(self) -> None:
        bundle = self.bundles["qualification"]
        transport = OfflineTransport(bundle, QUALIFICATION.node_snapshot)
        transport.responses["/object_info/VAEDecode"]["VAEDecode"]["output"] = ["MASK"]
        result = self.execute_offline(
            bundle, transport, trusted_snapshot=QUALIFICATION.node_snapshot
        )
        self.assert_not_submitted(result, transport, "execution.server_contract_mismatch")

    def test_current_product_snapshot_rejects_each_altered_observed_contract(self) -> None:
        profile = DEFAULT_SUPPORTED_PROFILE
        bundle = self.bundles["current"]
        for name in profile.node_snapshot.contracts:
            with self.subTest(node=name):
                transport = OfflineTransport(bundle, profile.node_snapshot)
                transport.responses[f"/object_info/{name}"][name]["input"]["required"] = {}
                result = self.execute_offline(bundle, transport, trusted_snapshot=profile.node_snapshot)
                self.assert_not_submitted(result, transport, "execution.server_contract_mismatch")

    def test_current_product_snapshot_rejects_wrong_reported_version_and_revision(self) -> None:
        profile = DEFAULT_SUPPORTED_PROFILE
        bundle = self.bundles["current"]
        for field, value, code in (
            ("comfyui_version", "0.34.5", "execution.server_identity_unverified"),
            ("comfyui_version", "0.28.0", "execution.server_identity_unverified"),
            ("comfyui_version", "99.0.0", "execution.server_identity_unverified"),
            ("git_revision", "f" * 40, "execution.server_revision"),
        ):
            with self.subTest(field=field, value=value):
                transport = OfflineTransport(bundle, profile.node_snapshot, exact_revision=True)
                transport.responses["/system_stats"]["system"][field] = value
                result = self.execute_offline(bundle, transport, trusted_snapshot=profile.node_snapshot)
                self.assert_not_submitted(result, transport, code)

    def test_client_wrong_reported_revision_never_posts(self) -> None:
        bundle = self.bundles["qualification"]
        transport = OfflineTransport(bundle, QUALIFICATION.node_snapshot, exact_revision=True)
        transport.responses["/system_stats"]["system"]["git_revision"] = "f" * 40
        result = self.execute_offline(
            bundle, transport, trusted_snapshot=QUALIFICATION.node_snapshot
        )
        self.assert_not_submitted(result, transport, "execution.server_revision")
        self.assertEqual(transport.requests, [("GET", "/system_stats", None)])

    def test_client_wrong_reported_version_never_posts(self) -> None:
        bundle = self.bundles["qualification"]
        transport = OfflineTransport(bundle, QUALIFICATION.node_snapshot)
        transport.responses["/system_stats"]["system"]["comfyui_version"] = "0.34.6"
        result = self.execute_offline(
            bundle, transport, trusted_snapshot=QUALIFICATION.node_snapshot
        )
        self.assert_not_submitted(result, transport, "execution.server_identity_unverified")
        self.assertEqual(transport.requests, [("GET", "/system_stats", None)])

    @staticmethod
    def stale_snapshots():
        snapshot = QUALIFICATION.node_snapshot
        return (
            replace(snapshot, snapshot_fingerprint="0" * 64),
            replace(snapshot, comfyui_version="0.34.6"),
            replace(snapshot, comfyui_revision="f" * 40),
            replace(snapshot, unresolved_items=("unreviewed semantic evidence",)),
        )

    def execute_offline(self, bundle, transport, **keywords):
        with patch(
            "conditioning_layers.execution.comfyui.client.LocalJsonTransport",
            return_value=transport,
        ), patch(
            "socket.socket", side_effect=AssertionError("offline test: no sockets")
        ):
            return execute_submission_bundle(
                bundle, transport.configuration, ComfyUIExecutionPolicy(), **keywords
            )

    def assert_semantic_identity(self, identity, transport, profile):
        self.assertIs(identity.identity_mode, ServerIdentityMode.SEMANTIC_CONTRACT)
        self.assertEqual(identity.profile_identifier, profile.inventory.comfyui_profile_identifier)
        self.assertEqual(identity.trusted_snapshot_fingerprint, profile.node_snapshot.snapshot_fingerprint)
        self.assertEqual(identity.finding_codes, ("execution.server_identity_semantic",))
        self.assertEqual(
            transport.requests,
            [("GET", "/system_stats", None)]
            + [("GET", f"/object_info/{name}", None) for name in profile.node_snapshot.contracts],
        )

    def assert_not_submitted(self, result, transport, code):
        self.assertIs(result.terminal_state, ExecutionState.NOT_SUBMITTED)
        self.assertFalse(result.submitted)
        self.assertIsNone(result.prompt_id)
        self.assertIn(code, codes(result.errors))
        self.assertFalse(any(method == "POST" for method, _, _ in transport.requests))


if __name__ == "__main__":
    unittest.main()
