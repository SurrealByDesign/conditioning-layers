from __future__ import annotations

import asyncio
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from conditioning_layers.integrations.comfyui_panel.application import (
    ExistingBackendApplication,
    materialize_document,
)
from conditioning_layers.integrations.comfyui_panel.documents import parse_document_request
from conditioning_layers.integrations.comfyui_panel.jobs import (
    PanelJobConflict,
    PanelJobCoordinator,
)
from conditioning_layers.integrations.comfyui_panel.models import (
    PanelExecutionDraft,
    PanelRequestError,
    PanelRunResult,
    parse_panel_request,
)
from conditioning_layers.persistence import encode_document

from _support import metadata, row, upload
from test_application import host_context


_OMITTED = object()
_MAX_SEED = 18446744073709551615


def request(seed=_OMITTED, *, key="request-1"):
    payload = json.loads(metadata([row("a")], key=key))
    if seed is not _OMITTED:
        payload["seed"] = seed
    body = json.dumps(payload).encode("utf-8")
    field = upload("a")
    return parse_panel_request(
        body,
        {field.part_name: field},
        multipart_part_count=2,
        total_bytes=len(body) + len(field.data),
    )


class SeedTransportTests(unittest.TestCase):
    def test_omitted_seed_preserves_captured_legacy_fingerprints_and_values(self):
        # Captured before M4 from the unchanged ordinary-v1 implementation.
        empty = PanelExecutionDraft("Base", (), "request-1")
        self.assertEqual(
            empty.fingerprint,
            "277558a698d69d53326f5db436901fbe03d4ce0bb67bd6375c87a1430e0ef111",
        )
        legacy = request()
        self.assertIsNone(legacy.seed)
        self.assertEqual(
            legacy.fingerprint,
            "fd2acd59f452033a83a861d49d4458ae23b2d9ae411d8d82497fa9708f5207c1",
        )
        self.assertEqual(legacy.resolved_seed, 1869282241165478355)
        self.assertEqual(request(key="request-2").resolved_seed, 8054183692118140505)

    def test_exact_decimal_boundaries_and_above_javascript_safe_range(self):
        for seed in (0, 1, 2**53 - 1, 2**53, 2**53 + 1, _MAX_SEED):
            with self.subTest(seed=seed):
                parsed = request(str(seed))
                self.assertIs(type(parsed.seed), int)
                self.assertEqual(parsed.seed, seed)
                self.assertEqual(parsed.resolved_seed, seed)

    def test_malformed_or_out_of_range_seed_is_rejected_without_coercion(self):
        for seed in (
            None, True, False, 0, 1, _MAX_SEED, 1.0, [], {}, "", " ",
            " 1", "1 ", "1\n", "\t1", "+1", "-0", "-1", "00", "01",
            "1.0", "1e2", "0x10", "1_000", "١", "１２", "1\x00",
            str(_MAX_SEED + 1), "9" * 21, "9" * 10000,
        ):
            with self.subTest(seed=repr(seed)[:80]):
                with self.assertRaises(PanelRequestError) as raised:
                    request(seed)
                self.assertEqual(raised.exception.finding.code, "panel.request.seed")
                self.assertEqual(raised.exception.status, 400)

    def test_direct_draft_explicit_seed_requires_exact_uint64_integer(self):
        for seed in (True, False, -1, 2**64, 1.0, "1"):
            with self.subTest(seed=seed):
                with self.assertRaises(ValueError):
                    PanelExecutionDraft("Base", (), "request-1", seed=seed)

    def test_explicit_seed_is_bound_into_request_fingerprint(self):
        legacy = request()
        explicit_same_value = request(str(legacy.resolved_seed))
        self.assertEqual(legacy.resolved_seed, explicit_same_value.resolved_seed)
        self.assertNotEqual(legacy.fingerprint, explicit_same_value.fingerprint)
        self.assertNotEqual(request("0").fingerprint, request("1").fingerprint)
        self.assertEqual(request("0").fingerprint, request("0").fingerprint)

    def test_seed_does_not_change_canonical_document_bytes(self):
        encoded = []
        for seed in (_OMITTED, "0", str(_MAX_SEED)):
            with tempfile.TemporaryDirectory() as root:
                materialized = materialize_document(request(seed), "a" * 32, Path(root))
                encoded.append(encode_document(materialized.document))
        self.assertEqual(encoded[0], encoded[1])
        self.assertEqual(encoded[1], encoded[2])

    def test_document_save_transport_still_rejects_seed(self):
        payload = {
            "display_name": "Seed stays outside intent",
            "source_document_key": None,
            "document_id": None,
            "base_prompt": "Base",
            "layers": [],
            "seed": "0",
        }
        body = json.dumps(payload).encode("utf-8")
        with self.assertRaises(PanelRequestError):
            parse_document_request(body, {}, multipart_part_count=1, total_bytes=len(body))


class SeedApplicationTests(unittest.TestCase):
    def test_exact_explicit_and_automatic_seed_reach_existing_graph_and_provenance(self):
        for seed in (_OMITTED, "0", "9007199254740993", str(_MAX_SEED)):
            with self.subTest(seed=seed):
                draft = request(seed)
                execution_id = "a" * 32
                execution = SimpleNamespace(
                    completed=True,
                    errors=(),
                    outputs=(SimpleNamespace(
                        filename="test_00001_.png",
                        subfolder=f"conditioning-layers-panel/{execution_id}",
                        storage_type="output",
                    ),),
                )
                prepared = SimpleNamespace(ready=True, bundle=object(), errors=())
                with tempfile.TemporaryDirectory() as root, patch(
                    "conditioning_layers.integrations.comfyui_panel.application.prepare_submission_bundle",
                    return_value=prepared,
                ) as prepare:
                    calls = []
                    result = ExistingBackendApplication(
                        host_context(Path(root)),
                        execution_client=lambda *args, **kwargs: calls.append(args) or execution,
                    ).run(draft, execution_id, lambda _state: None)
                self.assertEqual(result.state, "completed")
                self.assertEqual(len(calls), 1)
                artifact = prepare.call_args.args[0]
                self.assertEqual(artifact.provenance_inputs.seed, draft.resolved_seed)
                self.assertEqual(artifact.provenance_inputs.execution_request_id, execution_id)
                self.assertEqual(
                    artifact.provenance_inputs.output_filename_prefix,
                    f"conditioning-layers-panel/{execution_id}",
                )
                sampler = next(
                    node for node in artifact.to_api_graph().values()
                    if "seed" in node["inputs"]
                )
                self.assertEqual(sampler["inputs"]["seed"], draft.resolved_seed)


class RecordingApplication:
    def __init__(self, state="completed"):
        self.state = state
        self.calls = []

    def run(self, draft, execution_id, publish):
        self.calls.append((draft, execution_id))
        return PanelRunResult(state=self.state)


class SeedJobTests(unittest.IsolatedAsyncioTestCase):
    async def wait_terminal(self, coordinator, execution_id):
        for _ in range(100):
            snapshot = coordinator.get(execution_id)
            if snapshot.to_json()["terminal"]:
                return snapshot
            await asyncio.sleep(0.01)
        self.fail("Offline job did not reach terminal state")

    async def test_seed_is_exact_decimal_in_accepted_and_terminal_snapshots(self):
        for seed in ("0", "9007199254740993", str(_MAX_SEED)):
            with self.subTest(seed=seed):
                coordinator = PanelJobCoordinator(RecordingApplication())
                accepted, created = coordinator.submit(request(seed), asyncio.get_running_loop())
                self.assertTrue(created)
                self.assertEqual(accepted.state, "accepted")
                self.assertEqual(accepted.to_json()["seed"], seed)
                terminal = await self.wait_terminal(coordinator, accepted.execution_id)
                self.assertEqual(terminal.state, "completed")
                self.assertEqual(terminal.to_json()["seed"], seed)

    async def test_same_seed_new_key_is_new_execution_even_after_edit(self):
        application = RecordingApplication()
        coordinator = PanelJobCoordinator(application)
        loop = asyncio.get_running_loop()
        first_draft = request(str(_MAX_SEED))
        first, _ = coordinator.submit(first_draft, loop)
        await self.wait_terminal(coordinator, first.execution_id)
        revised = replace(
            request(str(_MAX_SEED), key="request-2"), base_prompt="Revised Base"
        )
        second, created = coordinator.submit(revised, loop)
        await self.wait_terminal(coordinator, second.execution_id)
        self.assertTrue(created)
        self.assertNotEqual(first.execution_id, second.execution_id)
        self.assertEqual(first.to_json()["seed"], second.to_json()["seed"])
        self.assertNotEqual(first_draft.fingerprint, revised.fingerprint)
        self.assertEqual(len(application.calls), 2)
        replay, created = coordinator.submit(first_draft, loop)
        self.assertFalse(created)
        self.assertEqual(replay.execution_id, first.execution_id)
        self.assertEqual(len(application.calls), 2)

    async def test_seed_change_under_same_key_conflicts_and_duplicate_is_once(self):
        application = RecordingApplication()
        coordinator = PanelJobCoordinator(application)
        loop = asyncio.get_running_loop()
        first, _ = coordinator.submit(request("0"), loop)
        replay, created = coordinator.submit(request("0"), loop)
        self.assertFalse(created)
        self.assertEqual(replay.execution_id, first.execution_id)
        with self.assertRaises(PanelJobConflict) as raised:
            coordinator.submit(request("1"), loop)
        self.assertEqual(raised.exception.finding.code, "panel.idempotency.reused")
        await self.wait_terminal(coordinator, first.execution_id)
        self.assertEqual(len(application.calls), 1)

    async def test_automatic_next_run_keeps_legacy_new_key_seed_selection(self):
        coordinator = PanelJobCoordinator(RecordingApplication())
        loop = asyncio.get_running_loop()
        first, _ = coordinator.submit(request(), loop)
        await self.wait_terminal(coordinator, first.execution_id)
        second, _ = coordinator.submit(request(key="request-2"), loop)
        await self.wait_terminal(coordinator, second.execution_id)
        self.assertEqual(first.to_json()["seed"], "1869282241165478355")
        self.assertEqual(second.to_json()["seed"], "8054183692118140505")
        self.assertNotEqual(first.execution_id, second.execution_id)

    async def test_failed_and_rejected_jobs_keep_their_selected_seed_without_output(self):
        for state in ("failed", "rejected"):
            with self.subTest(state=state):
                coordinator = PanelJobCoordinator(RecordingApplication(state))
                accepted, _ = coordinator.submit(request("0"), asyncio.get_running_loop())
                terminal = await self.wait_terminal(coordinator, accepted.execution_id)
                self.assertEqual(terminal.state, state)
                self.assertEqual(terminal.to_json()["seed"], "0")
                self.assertNotIn("output", terminal.to_json())


if __name__ == "__main__":
    unittest.main()
