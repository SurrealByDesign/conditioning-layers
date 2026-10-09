from __future__ import annotations

from dataclasses import fields
import json
from pathlib import Path
import tempfile
import unittest

from conditioning_layers.integrations.comfyui_panel.application import (
    materialize_document,
)
from conditioning_layers.integrations.comfyui_panel.models import (
    MAX_FIELD_BYTES,
    MAX_MULTIPART_PARTS,
    PanelRequestError,
    UploadedField,
    parse_panel_request,
)

from _support import grayscale_png, metadata, row, upload


def parse(rows, uploads, **overrides):
    body = metadata(rows)
    return parse_panel_request(
        body,
        uploads,
        multipart_part_count=overrides.get("parts", len(uploads) + 1),
        total_bytes=overrides.get("total", len(body) + sum(len(item.data) for item in uploads.values())),
    )


class TransportMappingTests(unittest.TestCase):
    def test_order_text_strength_visibility_and_field_association_are_exact(self) -> None:
        rows = [
            row("third", prompt="Prompt C", strength=0.25, active=False),
            row("first", prompt="Prompt A", strength=1, active=True),
            row("second", prompt="Prompt B", strength=0.75, active=True),
        ]
        uploads = {
            "field-first": upload("first", grayscale_png(255, 0)),
            "field-second": upload("second", grayscale_png(0, 255)),
            "field-third": upload("third", grayscale_png(128, 128)),
        }
        draft = parse(rows, uploads)
        self.assertEqual([item.row_id for item in draft.layers], ["third", "first", "second"])
        self.assertEqual([item.prompt_text for item in draft.layers], ["Prompt C", "Prompt A", "Prompt B"])
        self.assertEqual([item.strength for item in draft.layers], [0.25, 1, 0.75])
        self.assertEqual([item.active for item in draft.layers], [False, True, True])
        self.assertEqual(draft.layers[0].field.data, uploads["field-third"].data)

        with tempfile.TemporaryDirectory() as root:
            materialized = materialize_document(draft, "a" * 32, Path(root))
            document = materialized.document
            self.assertEqual([item.name for item in document.layers], ["Layer third", "Layer first", "Layer second"])
            self.assertEqual([item.visible for item in document.layers], [False, True, True])
            self.assertEqual(document.layers[0].strength, 0.25)
            self.assertEqual(len(list((materialized.asset_root / "fields").glob("*.png"))), 3)

    def test_zero_layers_is_transport_valid_for_python_capability_feedback(self) -> None:
        draft = parse([], {})
        self.assertEqual(draft.layers, ())

    def test_unknown_path_field_is_rejected(self) -> None:
        payload = row("a")
        payload["filesystem_path"] = "C:\\private\\field.png"
        with self.assertRaisesRegex(PanelRequestError, "missing or unsupported"):
            parse([payload], {"field-a": upload("a")})

    def test_non_standard_nan_number_is_rejected_as_malformed_json(self) -> None:
        body = metadata([row("a")]).replace(b"1.0", b"NaN")
        with self.assertRaises(PanelRequestError):
            parse_panel_request(
                body,
                {"field-a": upload("a")},
                multipart_part_count=2,
                total_bytes=len(body) + len(upload("a").data),
            )

    def test_mime_signature_per_file_total_and_part_limits_are_bounded(self) -> None:
        with self.subTest("mime"):
            with self.assertRaises(PanelRequestError) as raised:
                parse([row("a")], {"field-a": upload("a", mime="image/jpeg")})
            self.assertEqual(raised.exception.status, 415)
        with self.subTest("signature"):
            invalid = UploadedField("field-a", "image/png", b"not-png")
            with self.assertRaises(PanelRequestError):
                parse([row("a")], {"field-a": invalid})
        with self.subTest("per-file"):
            oversized = UploadedField(
                "field-a",
                "image/png",
                b"\x89PNG\r\n\x1a\n" + b"x" * MAX_FIELD_BYTES,
            )
            with self.assertRaises(PanelRequestError) as raised:
                parse([row("a")], {"field-a": oversized})
            self.assertEqual(raised.exception.status, 413)
        with self.subTest("parts"):
            with self.assertRaises(PanelRequestError) as raised:
                parse([], {}, parts=MAX_MULTIPART_PARTS + 1)
            self.assertEqual(raised.exception.status, 413)

    def test_upload_model_cannot_retain_client_filename_or_path(self) -> None:
        self.assertEqual(
            {item.name for item in fields(UploadedField)},
            {"part_name", "content_type", "data"},
        )

    def test_idempotency_fingerprint_changes_with_order_and_field_bytes(self) -> None:
        first = parse(
            [row("a"), row("b")],
            {"field-a": upload("a"), "field-b": upload("b", grayscale_png(0, 255))},
        )
        second = parse(
            [row("b"), row("a")],
            {"field-a": upload("a"), "field-b": upload("b", grayscale_png(0, 255))},
        )
        self.assertNotEqual(first.fingerprint, second.fingerprint)


if __name__ == "__main__":
    unittest.main()
