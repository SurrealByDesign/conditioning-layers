"""P3B server-side editor firewall prevents silent policy loss."""

from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from conditioning_layers.domain import (
    COMPOSITION_POLICY_PROTOTYPE_VERSION, CURRENT_PROTOTYPE_VERSION,
    NORMALIZED_BLEND, REQUIRE_NO_OVERLAP, ConditioningDocument,
    FindingSeverity, PrototypeDocumentVersion,
)
from conditioning_layers.integrations.comfyui_panel.documents import (
    PanelDocumentDraft, PanelDocumentError, PanelDocumentStore,
)
from conditioning_layers.persistence import load_document, save_document


class CompositionPolicyPanelFirewallTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        for target in (
            "socket.socket", "socket.create_connection", "socket.getaddrinfo",
            "urllib.request.urlopen", "http.client.HTTPConnection.connect",
            "subprocess.Popen", "webbrowser.open",
        ):
            stack.enter_context(patch(target, side_effect=AssertionError("P3B is offline")))
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="p3b-panel-")))
        self.store = PanelDocumentStore(self.root)
        self.store.root.mkdir(parents=True)

    def write_document(self, policy=None):
        document = ConditioningDocument(
            version=CURRENT_PROTOTYPE_VERSION if policy is None else COMPOSITION_POLICY_PROTOTYPE_VERSION,
            document_id="p3b-panel", base_prompt="Base", composition_policy=policy,
        )
        path = self.store.root / "source.conditioning.json"
        save_document(document, path, overwrite=True)
        return path, document

    def assert_editor_rejects(self, callback):
        with self.assertRaises(PanelDocumentError) as raised:
            callback()
        self.assertEqual(raised.exception.finding.code, "panel.document.composition_policy_editor_unsupported")

    def test_legacy_open_does_not_rewrite_bytes_or_expose_new_selector_data(self):
        path, document = self.write_document()
        before = path.read_bytes()
        opened = self.store.open("source")
        self.assertEqual(opened.document, document)
        self.assertNotIn("composition_policy", opened.to_json())
        self.assertEqual(path.read_bytes(), before)

    def test_successor_policy_documents_remain_persisted_but_cannot_enter_lossy_editor(self):
        for policy in (REQUIRE_NO_OVERLAP, NORMALIZED_BLEND):
            with self.subTest(policy=policy):
                path, document = self.write_document(policy.reference)
                before = path.read_bytes()
                self.assertEqual(load_document(path).document, document)
                self.assert_editor_rejects(lambda: self.store.open("source"))
                self.assertEqual(path.read_bytes(), before)

    def test_legacy_newer_minor_opens_with_warning_and_retains_editor_save_path(self):
        path, document = self.write_document()
        payload = json.loads(path.read_text(encoding="utf-8"))
        # The legacy envelope stays 1.0; only the domain document is newer-minor.
        payload["document"]["version"]["minor"] = 1
        path.write_text(json.dumps(payload), encoding="utf-8")
        before = path.read_bytes()
        loaded = load_document(path)
        self.assertTrue(loaded.ok, loaded.findings)
        self.assertIn(
            ("document.version.newer_minor", FindingSeverity.WARNING),
            {(finding.code, finding.severity) for finding in loaded.findings},
        )

        opened = self.store.open("source")
        self.assertEqual(opened.document, loaded.document)
        self.assertEqual(opened.document.version, PrototypeDocumentVersion(1, 1))
        self.assertIsNone(opened.document.composition_policy)
        self.assertEqual(opened.to_json()["base_prompt"], document.base_prompt)
        self.assertNotIn("composition_policy", opened.to_json())
        self.assertEqual(path.read_bytes(), before)

        draft = PanelDocumentDraft(
            opened.display_name, "source", document.document_id, "Edited Base", (),
        )
        saved = self.store.save("source", draft)
        self.assertEqual(saved.document.document_id, document.document_id)
        self.assertEqual(saved.document.base_prompt, "Edited Base")
        self.assertEqual(saved.document.version, CURRENT_PROTOTYPE_VERSION)
        self.assertIsNone(saved.document.composition_policy)

    def test_successor_open_rejects_explicit_policy_before_editor_projection(self):
        for policy in (REQUIRE_NO_OVERLAP, NORMALIZED_BLEND):
            with self.subTest(policy=policy):
                path, document = self.write_document(policy.reference)
                before = path.read_bytes()
                loaded = load_document(path)
                self.assertTrue(loaded.ok, loaded.findings)
                self.assertEqual(loaded.document, document)
                with patch(
                    "conditioning_layers.integrations.comfyui_panel.documents.OpenedPanelDocument"
                ) as projection:
                    with self.assertRaises(PanelDocumentError) as raised:
                        self.store.open("source")
                    projection.assert_not_called()
                self.assertEqual(raised.exception.status, 422)
                self.assertEqual(
                    raised.exception.finding.code,
                    "panel.document.composition_policy_editor_unsupported",
                )
                self.assertEqual(
                    raised.exception.finding.message,
                    "This document carries explicit Composition Policy intent that the current editor cannot preserve.",
                )
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(load_document(path).document, document)

    def test_save_and_save_as_cannot_strip_source_policy(self):
        path, document = self.write_document(NORMALIZED_BLEND.reference)
        before = path.read_bytes()
        for name, action in (
            ("Source", lambda draft: self.store.save("source", draft)),
            ("Copy", self.store.save_as),
        ):
            draft = PanelDocumentDraft(name, "source", document.document_id, "Edited Base", ())
            self.assert_editor_rejects(lambda: action(draft))
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.store.root / "copy.conditioning.json").exists())

    def test_retained_field_generation_resolution_cannot_bypass_policy_firewall(self):
        path, document = self.write_document(NORMALIZED_BLEND.reference)
        before = path.read_bytes()
        self.assert_editor_rejects(lambda: self.store.resolve_execution_field("source", document.document_id, "layer-1"))
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
