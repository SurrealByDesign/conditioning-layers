"""Policy transport/persistence through actual panel and materialization APIs."""

from dataclasses import replace
from concurrent.futures import Future
import asyncio
import json
from pathlib import Path
import tempfile
import unittest
import sys
from types import SimpleNamespace
from unittest.mock import patch

from conditioning_layers.capabilities import multi_layer, product
from conditioning_layers.domain import COMPOSITION_POLICY_PROTOTYPE_VERSION, CURRENT_PROTOTYPE_VERSION, NORMALIZED_BLEND, REQUIRE_NO_OVERLAP
from conditioning_layers.integrations.comfyui_panel.application import materialize_document
from conditioning_layers.integrations.comfyui_panel.documents import PanelDocumentError, PanelDocumentStore, parse_document_request
from conditioning_layers.integrations.comfyui_panel.models import PanelRequestError, parse_panel_request
from conditioning_layers.integrations.comfyui_panel.jobs import PanelJobCoordinator, PanelJobConflict
from conditioning_layers.persistence import load_document

from _support import metadata, row, upload
from test_documents import retained_rows, save_draft
from test_application import host_context


VERSION = {"major": 2, "minor": 0}
POLICY = {"policy_identifier": NORMALIZED_BLEND.identifier, "policy_version": 1}


def parse_execution(payload, uploads):
    body = json.dumps(payload).encode()
    return parse_panel_request(body, uploads, multipart_part_count=len(uploads) + 1,
                               total_bytes=len(body) + sum(len(item.data) for item in uploads.values()))


class PolicyEditorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = PanelDocumentStore(self.root / "user")
        self.draft = replace(save_draft("Blend", [row("a"), row("b", active=False, strength=0.25), row("c")],
                                       uploads={f"field-{x}": upload(x) for x in "abc"}),
                             document_version=COMPOSITION_POLICY_PROTOTYPE_VERSION, composition_policy=NORMALIZED_BLEND.reference)

    def test_capable_open_save_save_as_preview_and_generate_materialization_preserve_policy(self):
        saved = self.store.save_as(self.draft)
        path = self.store.root / "blend.conditioning.json"
        before = path.read_bytes()
        with self.assertRaises(PanelDocumentError):
            self.store.open("blend")
        opened = self.store.open("blend", policy_aware=True)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(opened.document, saved.document)
        response = opened.to_json()
        self.assertEqual(response["composition_policy"], POLICY)
        self.assertEqual(response["document_version"], VERSION)
        for layer in opened.document.layers:
            self.assertEqual(self.store.read_field("blend", layer.layer_id), opened.field_bytes[layer.layer_id])
        rows = retained_rows(opened)
        payload = {"display_name": "Blend", "source_document_key": "blend", "document_id": opened.document.document_id,
                   "base_prompt": "Edited", "layers": rows, "document_version": VERSION, "composition_policy": POLICY}
        body = json.dumps(payload).encode()
        draft = parse_document_request(body, {}, multipart_part_count=1, total_bytes=len(body))
        updated = self.store.save("blend", draft)
        self.assertEqual(updated.document.composition_policy, NORMALIZED_BLEND.reference)
        self.assertEqual(updated.document.layers, opened.document.layers)
        copied = self.store.save_as(replace(draft, display_name="Copy"))
        self.assertNotEqual(copied.document.document_id, updated.document.document_id)
        self.assertEqual(copied.document.layers, updated.document.layers)
        self.assertEqual(copied.field_bytes, updated.field_bytes)
        execution = parse_execution({**json.loads(metadata(rows, base_prompt="Edited")),
                                     "document_key": "blend", "document_id": updated.document.document_id,
                                     "document_version": VERSION, "composition_policy": POLICY}, {})
        materialized = materialize_document(execution, "a" * 32, self.root / "materialized", self.store)
        self.assertEqual(materialized.document, updated.document)
        self.assertEqual(load_document(path).document, updated.document)

    def test_missing_policy_cannot_strip_source_with_replacement_uploads(self):
        opened = self.store.save_as(self.draft)
        rows = [row("replacement")]
        rows[0]["layer_id"] = opened.document.layers[0].layer_id
        uploads = {"field-replacement": upload("replacement")}
        legacy_save = save_draft("Blend", rows, source="blend", document_id=opened.document.document_id, uploads=uploads)
        for callback in (lambda: self.store.save("blend", legacy_save),
                         lambda: self.store.save_as(replace(legacy_save, display_name="Stripped"))):
            with self.assertRaises(PanelDocumentError):
                callback()
        legacy_execution = parse_execution({**json.loads(metadata(rows)), "document_key": "blend",
                                            "document_id": opened.document.document_id}, uploads)
        with self.assertRaises(PanelDocumentError):
            materialize_document(legacy_execution, "a" * 32, self.root / "stripped", self.store)
        self.assertFalse((self.root / "stripped").exists())

    def test_legacy_and_explicit_no_overlap_remain_distinct(self):
        for name, version, policy in (("Legacy", CURRENT_PROTOTYPE_VERSION, None),
                                      ("Explicit", COMPOSITION_POLICY_PROTOTYPE_VERSION, REQUIRE_NO_OVERLAP.reference)):
            opened = self.store.save_as(replace(self.draft, display_name=name, document_version=version, composition_policy=policy))
            self.assertEqual(opened.document.version, version)
            self.assertEqual(opened.document.composition_policy, policy)
            self.assertEqual("composition_policy" in opened.to_json(), policy is not None)
        explicit = self.store.open("explicit", policy_aware=True)
        changed = replace(save_draft("Explicit", retained_rows(explicit), source="explicit", document_id=explicit.document.document_id),
                          document_version=COMPOSITION_POLICY_PROTOTYPE_VERSION, composition_policy=NORMALIZED_BLEND.reference)
        self.assertEqual(self.store.save("explicit", changed).document.composition_policy, NORMALIZED_BLEND.reference)

    def test_transport_rejects_missing_unknown_malformed_and_legacy_explicit_policy(self):
        original = json.loads(metadata([row("a")]))
        uploads = {"field-a": upload("a")}
        for extra in (
            {"document_version": VERSION}, {"composition_policy": POLICY},
            {"document_version": VERSION, "composition_policy": None},
            {"document_version": VERSION, "composition_policy": {**POLICY, "extra": True}},
            {"document_version": VERSION, "composition_policy": {**POLICY, "policy_identifier": "unknown"}},
            {"document_version": VERSION, "composition_policy": {**POLICY, "policy_version": True}},
            {"document_version": {"major": 1, "minor": 0}, "composition_policy": POLICY},
            {"document_version": {"major": True, "minor": 0}, "composition_policy": POLICY},
            {"product_admitted": True}, {"qualification_entry": "Blend"}, {"admitted_entries": [NORMALIZED_BLEND.identifier]},
        ):
            with self.subTest(extra=extra), self.assertRaises(PanelRequestError):
                parse_execution({**original, **extra}, uploads)

    def test_policy_is_in_request_conflict_identity_and_seed_is_unchanged(self):
        original = parse_execution(json.loads(metadata([row("a")])), {"field-a": upload("a")})
        blend = replace(original, document_version=COMPOSITION_POLICY_PROTOTYPE_VERSION, composition_policy=NORMALIZED_BLEND.reference)
        explicit = replace(blend, composition_policy=REQUIRE_NO_OVERLAP.reference)
        self.assertEqual(len({original.fingerprint, blend.fingerprint, explicit.fingerprint}), 3)
        self.assertEqual(original.resolved_seed, blend.resolved_seed)
        class Loop:
            def run_in_executor(self, *args):
                return Future()
        coordinator = PanelJobCoordinator(object())
        coordinator.submit(original, Loop())
        with self.assertRaises(PanelJobConflict):
            coordinator.submit(blend, Loop())

    def test_http_open_requires_exact_editor_marker_and_grants_no_admission(self):
        from conditioning_layers.integrations.comfyui_panel import routes
        from conditioning_layers.capabilities.product import route_product_prediction_mixing
        opened = self.store.save_as(self.draft)
        registered = {}

        def route(path):
            def register(callback):
                registered[callback.__name__] = callback
                return callback
            return register

        fake_server = SimpleNamespace(PromptServer=SimpleNamespace(instance=SimpleNamespace(
            routes=SimpleNamespace(get=route, post=route, put=route))))
        fake_web = SimpleNamespace(json_response=lambda payload, status=200, **kwargs: (status, payload))
        with patch.dict(sys.modules, {"server": fake_server, "aiohttp": SimpleNamespace(web=fake_web)}), \
                patch.object(routes, "_REGISTERED", False), patch.object(routes, "_COORDINATOR", None), \
                patch.object(routes, "_build_host_context", return_value=host_context(self.root)), \
                patch.object(routes, "PanelDocumentStore", return_value=self.store):
            routes.register_routes()
            handler = registered["open_document"]
            for headers in ({}, {"X-Conditioning-Layers-Policy-Editor": "0"}, {"X-Conditioning-Layers-Policy-Editor": "true"}):
                status, payload = asyncio.run(handler(SimpleNamespace(headers=headers, match_info={"document_key": "blend"})))
                self.assertEqual(status, 422)
                self.assertNotIn("composition_policy", payload)
            status, payload = asyncio.run(handler(SimpleNamespace(
                headers={"X-Conditioning-Layers-Policy-Editor": "1"}, match_info={"document_key": "blend"})))
            self.assertEqual(status, 200)
            self.assertEqual(payload["composition_policy"], POLICY)
        eligible = replace(opened.document, layers=tuple(replace(layer, visible=True) for layer in opened.document.layers))
        self.assertTrue(route_product_prediction_mixing(eligible).compatible)
        with patch.object(product, "PRODUCT_ADMITTED_ENTRIES", multi_layer.PRODUCT_ADMITTED_ENTRIES):
            rejected = route_product_prediction_mixing(eligible)
            self.assertFalse(rejected.compatible)
            self.assertEqual({finding.code for finding in rejected.errors}, {"capability.product_not_admitted"})


if __name__ == "__main__":
    unittest.main()
