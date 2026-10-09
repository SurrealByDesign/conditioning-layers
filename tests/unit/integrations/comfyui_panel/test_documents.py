from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from conditioning_layers.integrations.comfyui_panel.documents import (
    PanelDocumentError,
    PanelDocumentStore,
    parse_document_request,
)
from conditioning_layers.integrations.comfyui_panel.models import PanelRequestError
from conditioning_layers.persistence import DocumentIOError, document_asset_root

from _support import grayscale_png, row, upload


def save_draft(
    name: str,
    rows: list[dict],
    *,
    source: str | None = None,
    document_id: str | None = None,
    uploads=None,
    base_prompt: str = "A quiet studio scene",
):
    field_uploads = uploads or {}
    body = json.dumps(
        {
            "display_name": name,
            "source_document_key": source,
            "document_id": document_id,
            "base_prompt": base_prompt,
            "layers": rows,
        }
    ).encode("utf-8")
    return parse_document_request(
        body,
        field_uploads,
        multipart_part_count=len(field_uploads) + 1,
        total_bytes=len(body) + sum(len(item.data) for item in field_uploads.values()),
    )


def retained_rows(opened):
    return [
        {
            "row_id": f"row-{index}",
            "layer_id": layer.layer_id,
            "name": layer.name,
            "prompt_text": layer.prompt_text,
            "strength": layer.strength,
            "active": layer.visible,
            "field_part": None,
            "retained_field": True,
        }
        for index, layer in enumerate(opened.document.layers, start=1)
    ]


class PanelDocumentStoreTests(unittest.TestCase):
    def test_document_name_is_not_a_browser_filesystem_path(self) -> None:
        with self.assertRaises(PanelRequestError) as raised:
            save_draft("C:\\private\\study", [row("a")], uploads={"field-a": upload("a")})
        self.assertEqual(raised.exception.finding.code, "panel.document.name_invalid")

    def test_save_open_round_trip_preserves_order_disabled_strength_fields_and_identity(self) -> None:
        rows = [
            row("third", prompt="Third", strength=0.375, active=False),
            row("first", prompt="First", strength=1.0, active=True),
            row("second", prompt="Second", strength=0.625, active=True),
        ]
        uploads = {
            "field-third": upload("third", grayscale_png(128, 128)),
            "field-first": upload("first", grayscale_png(255, 0)),
            "field-second": upload("second", grayscale_png(0, 255)),
        }
        with tempfile.TemporaryDirectory() as root:
            store = PanelDocumentStore(Path(root) / "user")
            saved = store.save_as(save_draft("Ceramic Study", rows, uploads=uploads))
            opened = store.open("ceramic-study")

            self.assertEqual(opened.document, saved.document)
            self.assertEqual(opened.document.document_id, saved.document.document_id)
            self.assertEqual([item.prompt_text for item in opened.document.layers], ["Third", "First", "Second"])
            self.assertEqual([item.visible for item in opened.document.layers], [False, True, True])
            self.assertEqual([item.strength for item in opened.document.layers], [0.375, 1.0, 0.625])
            self.assertEqual(set(opened.field_bytes), {item.layer_id for item in opened.document.layers})
            self.assertEqual(store.list_documents(), ({"document_key": "ceramic-study", "display_name": "Ceramic Study"},))

    def test_save_and_repeated_open_preserve_identity_and_retained_assets(self) -> None:
        rows = [row("a", strength=0.25, active=False), row("b", strength=0.75)]
        uploads = {"field-a": upload("a"), "field-b": upload("b", grayscale_png(0, 255))}
        with tempfile.TemporaryDirectory() as root:
            store = PanelDocumentStore(Path(root) / "user")
            first = store.save_as(save_draft("Repeated", rows, uploads=uploads))
            identity = first.document.document_id
            edited_rows = retained_rows(first)
            edited_rows.reverse()
            edited_rows[0]["prompt_text"] = "Edited after reopen"
            edited_rows[0]["strength"] = 0.5

            second = store.save(
                "repeated",
                save_draft(
                    "Repeated",
                    edited_rows,
                    source="repeated",
                    document_id=identity,
                ),
            )
            third = store.open("repeated")
            fourth = store.save(
                "repeated",
                save_draft(
                    "Repeated",
                    retained_rows(third),
                    source="repeated",
                    document_id=identity,
                    base_prompt=third.document.base_prompt,
                ),
            )

            self.assertEqual(second.document.document_id, identity)
            self.assertEqual(third.document, second.document)
            self.assertEqual(fourth.document, third.document)
            self.assertEqual(third.document.layers[0].prompt_text, "Edited after reopen")
            self.assertEqual(third.document.layers[0].strength, 0.5)

    def test_save_as_creates_document_identity_and_copies_asset_ownership(self) -> None:
        rows = [row("a")]
        with tempfile.TemporaryDirectory() as root:
            store = PanelDocumentStore(Path(root) / "user")
            first = store.save_as(save_draft("Original", rows, uploads={"field-a": upload("a")}))
            copied = store.save_as(
                save_draft(
                    "Copy",
                    retained_rows(first),
                    source="original",
                    document_id=first.document.document_id,
                )
            )
            original_path = store.root / "original.conditioning.json"
            copy_path = store.root / "copy.conditioning.json"

            self.assertNotEqual(copied.document.document_id, first.document.document_id)
            self.assertEqual(copied.document.base_prompt, first.document.base_prompt)
            self.assertEqual(copied.document.layers, first.document.layers)
            self.assertNotEqual(document_asset_root(original_path), document_asset_root(copy_path))
            self.assertTrue(document_asset_root(original_path).is_dir())
            self.assertTrue(document_asset_root(copy_path).is_dir())

    def test_corrupt_missing_asset_unsupported_version_and_validation_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = PanelDocumentStore(Path(root) / "user")
            store.root.mkdir(parents=True)
            corrupt = store.root / "corrupt.conditioning.json"
            corrupt.write_text("{broken", encoding="utf-8")
            with self.assertRaises(PanelDocumentError) as raised:
                store.open("corrupt")
            self.assertEqual(raised.exception.finding.code, "panel.document.corrupted")

            unsupported = store.root / "unsupported.conditioning.json"
            unsupported.write_text(
                json.dumps(
                    {
                        "format": "conditioning-layers.prototype-document",
                        "format_version": {"major": 99, "minor": 0},
                        "document": {},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(PanelDocumentError) as raised:
                store.open("unsupported")
            self.assertEqual(raised.exception.finding.code, "panel.document.version_unsupported")

            saved = store.save_as(save_draft("Missing", [row("a")], uploads={"field-a": upload("a")}))
            field_path = next((document_asset_root(store.root / "missing.conditioning.json") / "fields").iterdir())
            field_path.unlink()
            with self.assertRaises(PanelDocumentError) as raised:
                store.open("missing")
            self.assertEqual(raised.exception.finding.code, "panel.document.field_missing")

            invalid = row("invalid", strength=2.0)
            with self.assertRaises(PanelDocumentError) as raised:
                store.save_as(save_draft("Invalid", [invalid], uploads={"field-invalid": upload("invalid")}))
            self.assertEqual(raised.exception.finding.code, "panel.document.save_failed")
            self.assertFalse((store.root / "invalid.conditioning.json").exists())

    def test_save_failure_rolls_back_existing_document_and_assets(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = PanelDocumentStore(Path(root) / "user")
            first = store.save_as(save_draft("Rollback", [row("a")], uploads={"field-a": upload("a")}))
            document_path = store.root / "rollback.conditioning.json"
            original_json = document_path.read_bytes()
            original_assets = {
                path.name: path.read_bytes()
                for path in (document_asset_root(document_path) / "fields").iterdir()
            }
            with patch(
                "conditioning_layers.integrations.comfyui_panel.documents.save_document",
                side_effect=DocumentIOError("io.write_failed", "failed", "bounded"),
            ):
                with self.assertRaises(PanelDocumentError) as raised:
                    store.save(
                        "rollback",
                        save_draft(
                            "Rollback",
                            retained_rows(first),
                            source="rollback",
                            document_id=first.document.document_id,
                        ),
                    )
            self.assertEqual(raised.exception.finding.code, "panel.document.save_failed")
            self.assertEqual(
                raised.exception.finding.message,
                "The Conditioning Layers document could not be saved.",
            )
            for private_detail in ("path", "traceback", "checksum", "provenance"):
                self.assertNotIn(private_detail, raised.exception.finding.message.casefold())
            self.assertEqual(document_path.read_bytes(), original_json)
            self.assertEqual(
                {path.name: path.read_bytes() for path in (document_asset_root(document_path) / "fields").iterdir()},
                original_assets,
            )

    def test_retained_field_cannot_be_claimed_by_another_layer_or_document(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = PanelDocumentStore(Path(root) / "user")
            opened = store.save_as(save_draft("Owned", [row("a")], uploads={"field-a": upload("a")}))
            rows = retained_rows(opened)
            rows[0]["layer_id"] = "layer-not-owned"
            with self.assertRaises(PanelDocumentError) as raised:
                store.save(
                    "owned",
                    save_draft(
                        "Owned",
                        rows,
                        source="owned",
                        document_id=opened.document.document_id,
                    ),
                )
            self.assertEqual(raised.exception.finding.code, "panel.document.layer_identity")


if __name__ == "__main__":
    unittest.main()
