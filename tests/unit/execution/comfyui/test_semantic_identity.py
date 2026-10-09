from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from conditioning_layers.comfyui.prediction_mixing import COMFYUI_0280_NODE_SNAPSHOT
from conditioning_layers.execution.comfyui import ExecutionState, ServerIdentityMode
from conditioning_layers.execution.comfyui.errors import ProtocolFailure
from conditioning_layers.execution.comfyui.protocol import (
    LocalJsonTransport,
    establish_server_identity,
    validate_semantic_server_identity,
)
from conditioning_layers.execution.comfyui.provenance import build_execution_provenance

from _support import (
    FakeComfyUI,
    Response,
    configure_semantic_contracts,
    identity_payload,
    make_bundle,
    object_info_payload,
    semantic_identity_payload,
)


class SemanticServerIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.bundle = make_bundle(Path(self.temporary.name), semantic_profile=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_exact_revision_route_uses_no_object_info(self) -> None:
        with FakeComfyUI() as server:
            server.add("GET", "/system_stats", Response(payload=identity_payload(self.bundle)))
            identity = establish_server_identity(
                LocalJsonTransport(server.config()), self.bundle
            )
        self.assertIs(identity.identity_mode, ServerIdentityMode.EXACT_REVISION)
        self.assertEqual(identity.finding_codes, ("execution.server_identity_exact",))
        self.assertEqual([item[:2] for item in server.requests], [("GET", "/system_stats")])

    def test_genuine_exact_revision_mismatch_preserves_revision_finding(self) -> None:
        with FakeComfyUI() as server:
            server.add(
                "GET",
                "/system_stats",
                Response(payload=identity_payload(self.bundle, git_revision="f" * 40)),
            )
            with self.assertRaises(ProtocolFailure) as raised:
                establish_server_identity(LocalJsonTransport(server.config()), self.bundle)
        self.assertEqual(raised.exception.code, "execution.server_revision")
        self.assertEqual(len(server.requests), 1)

    def test_semantic_route_accepts_all_eleven_contracts_without_prompt(self) -> None:
        with FakeComfyUI() as server:
            server.add(
                "GET",
                "/system_stats",
                Response(payload=semantic_identity_payload(self.bundle, server.port)),
            )
            configure_semantic_contracts(server, self.bundle)
            identity = establish_server_identity(
                LocalJsonTransport(server.config()), self.bundle
            )
        paths = [path for _, path, _ in server.requests]
        self.assertIs(identity.identity_mode, ServerIdentityMode.SEMANTIC_CONTRACT)
        self.assertEqual(
            identity.finding_codes, ("execution.server_identity_semantic",)
        )
        self.assertEqual(len(paths), 12)
        self.assertEqual(paths[0], "/system_stats")
        self.assertEqual(sum(path.startswith("/object_info/") for path in paths), 11)
        self.assertNotIn("/object_info", paths)
        self.assertNotIn("/prompt", paths)
        self.assertIsNotNone(identity.live_contract_fingerprint)

    def test_version_only_evidence_is_rejected_before_object_info(self) -> None:
        with FakeComfyUI() as server:
            server.add(
                "GET",
                "/system_stats",
                Response(payload=identity_payload(self.bundle, git_revision=None, argv=[])),
            )
            with self.assertRaises(ProtocolFailure) as raised:
                establish_server_identity(LocalJsonTransport(server.config()), self.bundle)
        self.assertEqual(raised.exception.code, "execution.server_identity_unverified")
        self.assertEqual(len(server.requests), 1)

    def test_missing_node_is_distinct(self) -> None:
        with FakeComfyUI() as server:
            self._configure(server, missing="VAEDecode")
            with self.assertRaises(ProtocolFailure) as raised:
                establish_server_identity(LocalJsonTransport(server.config()), self.bundle)
        self.assertEqual(raised.exception.code, "execution.server_contract_missing")

    def test_changed_required_input_is_rejected(self) -> None:
        payload = deepcopy(object_info_payload(self.bundle, "KSampler"))
        del payload["KSampler"]["input"]["required"]["steps"]
        with FakeComfyUI() as server:
            self._configure(server, override=("KSampler", Response(payload=payload)))
            with self.assertRaises(ProtocolFailure) as raised:
                establish_server_identity(LocalJsonTransport(server.config()), self.bundle)
        self.assertEqual(raised.exception.code, "execution.server_contract_mismatch")

    def test_changed_output_is_rejected(self) -> None:
        payload = deepcopy(object_info_payload(self.bundle, "VAEDecode"))
        payload["VAEDecode"]["output"] = ["MASK"]
        with FakeComfyUI() as server:
            self._configure(server, override=("VAEDecode", Response(payload=payload)))
            with self.assertRaises(ProtocolFailure) as raised:
                establish_server_identity(LocalJsonTransport(server.config()), self.bundle)
        self.assertEqual(raised.exception.code, "execution.server_contract_mismatch")

    def test_changed_relevant_enum_is_rejected(self) -> None:
        payload = deepcopy(object_info_payload(self.bundle, "KSampler"))
        payload["KSampler"]["input"]["required"]["sampler_name"][0] = ["heun"]
        with FakeComfyUI() as server:
            self._configure(server, override=("KSampler", Response(payload=payload)))
            with self.assertRaises(ProtocolFailure) as raised:
                establish_server_identity(LocalJsonTransport(server.config()), self.bundle)
        self.assertEqual(raised.exception.code, "execution.server_contract_mismatch")

    def test_first_enum_value_is_the_implicit_default(self) -> None:
        payload = deepcopy(object_info_payload(self.bundle, "UNETLoader"))
        del payload["UNETLoader"]["input"]["required"]["weight_dtype"][1][
            "default"
        ]
        with FakeComfyUI() as server:
            self._configure(server, override=("UNETLoader", Response(payload=payload)))
            identity = establish_server_identity(
                LocalJsonTransport(server.config()), self.bundle
            )
        self.assertIs(identity.identity_mode, ServerIdentityMode.SEMANTIC_CONTRACT)

    def test_malformed_object_info_is_protocol_failure(self) -> None:
        with FakeComfyUI() as server:
            self._configure(
                server,
                override=("CLIPTextEncode", Response(raw_body=b"{")),
            )
            with self.assertRaises(ProtocolFailure) as raised:
                establish_server_identity(LocalJsonTransport(server.config()), self.bundle)
        self.assertEqual(raised.exception.code, "execution.server_contract_protocol")

    def test_wrong_version_is_rejected_before_object_info(self) -> None:
        with FakeComfyUI() as server:
            payload = semantic_identity_payload(
                self.bundle, server.port, comfyui_version="99.0.0"
            )
            server.add("GET", "/system_stats", Response(payload=payload))
            with self.assertRaises(ProtocolFailure) as raised:
                establish_server_identity(LocalJsonTransport(server.config()), self.bundle)
        self.assertEqual(raised.exception.code, "execution.server_identity_unverified")
        self.assertEqual(len(server.requests), 1)

    def test_offline_snapshot_mismatch_is_rejected_before_object_info(self) -> None:
        changed = replace(
            self.bundle,
            host_snapshot=replace(
                self.bundle.host_snapshot,
                node_contract_snapshot_fingerprint="0" * 64,
            ),
        )
        with FakeComfyUI() as server:
            server.add(
                "GET",
                "/system_stats",
                Response(payload=semantic_identity_payload(changed, server.port)),
            )
            with self.assertRaises(ProtocolFailure) as raised:
                establish_server_identity(LocalJsonTransport(server.config()), changed)
        self.assertEqual(raised.exception.code, "execution.server_identity_unverified")
        self.assertEqual(len(server.requests), 1)

    def test_unresolved_semantic_evidence_is_rejected(self) -> None:
        unresolved = replace(
            COMFYUI_0280_NODE_SNAPSHOT,
            unresolved_items=("test unresolved evidence",),
        )
        with FakeComfyUI() as server:
            payload = semantic_identity_payload(self.bundle, server.port)
            with self.assertRaises(ProtocolFailure) as raised:
                validate_semantic_server_identity(
                    payload,
                    LocalJsonTransport(server.config()),
                    self.bundle,
                    trusted_snapshot=unresolved,
                )
        self.assertEqual(raised.exception.code, "execution.server_identity_unverified")
        self.assertEqual(server.requests, [])

    def test_identity_mode_and_sanitized_evidence_enter_provenance(self) -> None:
        with FakeComfyUI() as server:
            self._configure(server)
            identity = establish_server_identity(
                LocalJsonTransport(server.config()), self.bundle
            )
        provenance = build_execution_provenance(
            bundle=self.bundle,
            server_identity=identity,
            prompt_id=None,
            terminal_state=ExecutionState.NOT_SUBMITTED,
            outputs=(),
            errors=(),
            warnings=(),
        )
        self.assertIs(
            provenance.server_identity_mode, ServerIdentityMode.SEMANTIC_CONTRACT
        )
        self.assertEqual(
            provenance.server_identity_finding_codes,
            ("execution.server_identity_semantic",),
        )
        self.assertEqual(
            provenance.trusted_snapshot_fingerprint,
            COMFYUI_0280_NODE_SNAPSHOT.snapshot_fingerprint,
        )
        self.assertEqual(
            provenance.live_contract_fingerprint,
            identity.live_contract_fingerprint,
        )
        self.assertIsNotNone(provenance.launch_arguments_sha256)
        self.assertIsNone(provenance.reported_server_revision)

    def test_live_contract_fingerprint_is_deterministic(self) -> None:
        fingerprints = []
        for _ in range(2):
            with FakeComfyUI() as server:
                self._configure(server)
                identity = establish_server_identity(
                    LocalJsonTransport(server.config()), self.bundle
                )
            fingerprints.append(identity.live_contract_fingerprint)
        self.assertEqual(fingerprints[0], fingerprints[1])

    def test_presentation_metadata_does_not_change_contract_fingerprint(self) -> None:
        with FakeComfyUI() as server:
            self._configure(server)
            first = establish_server_identity(
                LocalJsonTransport(server.config()), self.bundle
            )
        payload = object_info_payload(self.bundle, "VAEDecode")
        payload["VAEDecode"]["display_name"] = "different ignored label"
        with FakeComfyUI() as server:
            self._configure(server, override=("VAEDecode", Response(payload=payload)))
            second = establish_server_identity(
                LocalJsonTransport(server.config()), self.bundle
            )
        self.assertEqual(
            first.live_contract_fingerprint,
            second.live_contract_fingerprint,
        )

    def test_live_function_mismatch_is_rejected_when_exposed(self) -> None:
        payload = object_info_payload(
            self.bundle, "SaveImage", include_function=True
        )
        payload["SaveImage"]["function"] = "changed"
        with FakeComfyUI() as server:
            self._configure(server, override=("SaveImage", Response(payload=payload)))
            with self.assertRaises(ProtocolFailure) as raised:
                establish_server_identity(LocalJsonTransport(server.config()), self.bundle)
        self.assertEqual(raised.exception.code, "execution.server_contract_mismatch")

    def _configure(
        self,
        server: FakeComfyUI,
        *,
        missing: str | None = None,
        override: tuple[str, Response] | None = None,
    ) -> None:
        server.add(
            "GET",
            "/system_stats",
            Response(payload=semantic_identity_payload(self.bundle, server.port)),
        )
        override_name = override[0] if override is not None else None
        for node_class in COMFYUI_0280_NODE_SNAPSHOT.contracts:
            if node_class == missing:
                server.add(
                    "GET", f"/object_info/{node_class}", Response(payload={})
                )
            elif node_class == override_name:
                server.add("GET", f"/object_info/{node_class}", override[1])
            else:
                server.add(
                    "GET",
                    f"/object_info/{node_class}",
                    Response(payload=object_info_payload(self.bundle, node_class)),
                )


if __name__ == "__main__":
    unittest.main()
