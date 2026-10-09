from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from conditioning_layers.execution.comfyui import (
    ComfyUIExecutionPolicy,
    ComfyUIServerConfiguration,
    ExecutionPolicyError,
    ServerConfigurationError,
)
from conditioning_layers.execution.comfyui.errors import ProtocolFailure
from conditioning_layers.execution.comfyui.protocol import (
    LocalJsonTransport,
    parse_prompt_id,
    validate_server_identity,
)

from _support import PROMPT_ID, identity_payload, make_bundle


class ServerConfigurationTests(unittest.TestCase):
    def test_explicit_loopback_hosts_are_valid(self) -> None:
        for host in ("127.0.0.1", "localhost", "::1"):
            with self.subTest(host=host):
                self.assertEqual(ComfyUIServerConfiguration(host=host).host, host)

    def test_remote_scheme_port_and_excessive_timeout_are_rejected(self) -> None:
        invalid = (
            {"host": "example.com"},
            {"scheme": "https"},
            {"port": 0},
            {"port": 65536},
            {"total_execution_timeout_seconds": 7201.0},
        )
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ServerConfigurationError):
                ComfyUIServerConfiguration(**values)

    def test_credentials_query_fragment_and_unsafe_base_path_are_rejected(self) -> None:
        invalid = (
            {"host": "user@localhost"},
            {"host": "localhost?x=1"},
            {"host": "localhost#fragment"},
            {"api_base_path": "api?x=1"},
            {"api_base_path": "../api"},
        )
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ServerConfigurationError):
                ComfyUIServerConfiguration(**values)

    def test_request_and_response_bounds_are_finite(self) -> None:
        for name in ("maximum_request_bytes", "maximum_response_bytes"):
            with self.subTest(name=name), self.assertRaises(ServerConfigurationError):
                ComfyUIServerConfiguration(**{name: 65 * 1024 * 1024})

    def test_configuration_and_policy_reject_wrong_runtime_types(self) -> None:
        with self.assertRaises(ServerConfigurationError):
            ComfyUIServerConfiguration(host=None)  # type: ignore[arg-type]
        with self.assertRaises(ServerConfigurationError):
            ComfyUIServerConfiguration(local_only=1)  # type: ignore[arg-type]
        with self.assertRaises(ExecutionPolicyError):
            ComfyUIExecutionPolicy(retain_staged_assets=1)  # type: ignore[arg-type]

    def test_transport_rejects_unsafe_internal_endpoint(self) -> None:
        transport = LocalJsonTransport(ComfyUIServerConfiguration())
        with self.assertRaises(ProtocolFailure):
            transport.get_json("/queue?all=true")


class ProtocolParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.bundle = make_bundle(Path(self.temporary.name))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_canonical_prompt_id_is_required(self) -> None:
        self.assertEqual(parse_prompt_id({"prompt_id": PROMPT_ID}), PROMPT_ID)
        for payload in (
            {},
            {"prompt_id": "not-a-uuid"},
            {"prompt_id": "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"},
        ):
            with self.subTest(payload=payload), self.assertRaises(ProtocolFailure):
                parse_prompt_id(payload)

    def test_matching_version_and_revision_are_accepted(self) -> None:
        identity = validate_server_identity(identity_payload(self.bundle), self.bundle)
        self.assertEqual(identity.comfyui_revision, self.bundle.provenance.comfyui_revision)
        self.assertEqual(identity.revision_evidence, "system_stats_revision")

    def test_mismatch_and_unverifiable_identity_are_rejected(self) -> None:
        mismatched = identity_payload(self.bundle, comfyui_version="99.0.0")
        unverifiable = identity_payload(self.bundle, git_revision=None, argv=[])
        for payload in (mismatched, unverifiable):
            with self.subTest(payload=payload), self.assertRaises(ProtocolFailure):
                validate_server_identity(payload, self.bundle)

    def test_launch_path_alone_is_not_exact_revision_evidence(self) -> None:
        payload = identity_payload(
            self.bundle,
            git_revision=None,
            argv=[str(self.bundle.host_snapshot.comfyui_root / "main.py")],
        )
        with self.assertRaises(ProtocolFailure) as raised:
            validate_server_identity(payload, self.bundle)
        self.assertEqual(raised.exception.code, "execution.server_identity_unverified")


if __name__ == "__main__":
    unittest.main()
