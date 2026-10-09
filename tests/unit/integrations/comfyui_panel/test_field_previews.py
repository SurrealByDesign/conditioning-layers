from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from conditioning_layers.integrations.comfyui_panel.documents import (
    PanelDocumentError,
    PanelDocumentStore,
    field_preview_url,
    parse_document_request,
)
from conditioning_layers.persistence import document_asset_root

from _support import grayscale_png, row, upload


def save_draft(name, rows, *, uploads):
    body = json.dumps(
        {
            "display_name": name,
            "source_document_key": None,
            "document_id": None,
            "base_prompt": "A quiet studio scene",
            "layers": rows,
        }
    ).encode("utf-8")
    return parse_document_request(
        body,
        uploads,
        multipart_part_count=len(uploads) + 1,
        total_bytes=len(body) + sum(len(item.data) for item in uploads.values()),
    )


def saved_store(root: str) -> tuple[PanelDocumentStore, object]:
    store = PanelDocumentStore(Path(root))
    draft = save_draft(
        "Preview Study",
        [row("a", prompt="First"), row("b", prompt="Second")],
        uploads={
            "field-a": upload("a", grayscale_png(255, 0)),
            "field-b": upload("b", grayscale_png(0, 255)),
        },
    )
    return store, store.save_as(draft)


class FieldPreviewProjectionTests(unittest.TestCase):
    def test_open_projection_includes_a_server_owned_field_url_per_layer(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            _store, opened = saved_store(root)
            payload = opened.to_json()
            for layer in payload["layers"]:
                self.assertTrue(layer["field_persisted"])
                self.assertEqual(
                    layer["field_url"],
                    field_preview_url(opened.document_key, layer["layer_id"]),
                )
                self.assertTrue(
                    layer["field_url"].startswith(
                        f"/conditioning-layers/documents/{opened.document_key}/fields/"
                    )
                )

    def test_read_field_returns_exact_verified_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store, opened = saved_store(root)
            layer = opened.document.layers[0]
            data = store.read_field(opened.document_key, layer.layer_id)
            self.assertEqual(data, opened.field_bytes[layer.layer_id])
            self.assertEqual(data, grayscale_png(255, 0))

    def test_unknown_layer_and_invalid_identifier_are_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store, opened = saved_store(root)
            with self.assertRaises(PanelDocumentError) as missing:
                store.read_field(opened.document_key, "layer-does-not-exist")
            self.assertEqual(missing.exception.status, 404)
            self.assertEqual(
                missing.exception.finding.code, "panel.document.field_missing"
            )
            for invalid in ("", "../escape", "fields/other.png", "a" * 200, None):
                with self.assertRaises(PanelDocumentError) as rejected:
                    store.read_field(opened.document_key, invalid)
                self.assertEqual(rejected.exception.status, 404)

    def test_unknown_document_is_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = PanelDocumentStore(Path(root))
            with self.assertRaises(PanelDocumentError) as raised:
                store.read_field("absent-document", "layer-a")
            self.assertEqual(raised.exception.status, 404)

    def test_failed_asset_restoration_serves_no_preview_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store, opened = saved_store(root)
            layer = opened.document.layers[0]
            asset = (
                document_asset_root(
                    store.root / f"{opened.document_key}.conditioning.json"
                )
                / "fields"
                / f"{layer.layer_id}.png"
            )
            original = asset.read_bytes()
            asset.write_bytes(original[:-1] + bytes([original[-1] ^ 0xFF]))
            with self.assertRaises(PanelDocumentError) as raised:
                store.read_field(opened.document_key, layer.layer_id)
            self.assertEqual(
                raised.exception.finding.code, "panel.document.field_checksum"
            )

    def test_preview_route_does_not_change_the_serialized_document(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store, opened = saved_store(root)
            document_path = store.root / f"{opened.document_key}.conditioning.json"
            before = document_path.read_bytes()
            self.assertNotIn(b"field_url", before)
            for layer in opened.document.layers:
                store.read_field(opened.document_key, layer.layer_id)
            opened.to_json()
            self.assertEqual(document_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
