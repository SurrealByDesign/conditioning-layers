from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from conditioning_layers.domain import (
    CURRENT_PROTOTYPE_VERSION,
    ConditioningDocument,
    InfluenceFieldAssetReference,
    PromptLayer,
)
from conditioning_layers.persistence import (
    DocumentIOError,
    document_asset_root,
    load_document,
    save_document,
)


def make_document() -> ConditioningDocument:
    return ConditioningDocument(
        version=CURRENT_PROTOTYPE_VERSION,
        document_id="document-io",
        base_prompt="静かな UTF-8 scene",
        layers=(
            PromptLayer(
                layer_id="layer-1",
                name="Lumière",
                prompt_text="青い花",
                influence_field=InfluenceFieldAssetReference(
                    relative_path="fields/one.png",
                    checksum="a" * 64,
                ),
            ),
        ),
    )


class SaveLoadTests(unittest.TestCase):
    def test_atomic_save_and_load_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "example.conditioning.json"

            save_document(make_document(), path)
            result = load_document(path)

            self.assertTrue(result.ok, result.findings)
            self.assertEqual(result.document, make_document())
            self.assertIn("青い花", path.read_text(encoding="utf-8"))
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_save_does_not_create_or_modify_asset_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "example.conditioning.json"
            assets = document_asset_root(path)

            save_document(make_document(), path)

            self.assertFalse(assets.exists())

    def test_overwrite_is_disabled_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "example.conditioning.json"
            path.write_text("original", encoding="utf-8")

            with self.assertRaises(DocumentIOError) as raised:
                save_document(make_document(), path)

            self.assertEqual(raised.exception.code, "io.destination_exists")
            self.assertEqual(path.read_text(encoding="utf-8"), "original")

    def test_overwrite_must_be_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "example.conditioning.json"
            path.write_text("original", encoding="utf-8")

            save_document(make_document(), path, overwrite=True)

            self.assertTrue(load_document(path).ok)
            self.assertNotEqual(path.read_text(encoding="utf-8"), "original")

    def test_missing_parent_is_not_created_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory) / "missing" / "nested"
            path = parent / "example.conditioning.json"

            with self.assertRaises(DocumentIOError) as raised:
                save_document(make_document(), path)

            self.assertEqual(raised.exception.code, "io.parent_missing")
            self.assertFalse(parent.exists())

    def test_parent_creation_must_be_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = (
                Path(directory)
                / "created"
                / "nested"
                / "example.conditioning.json"
            )

            save_document(make_document(), path, create_parents=True)

            self.assertTrue(path.exists())
            self.assertTrue(load_document(path).ok)

    def test_failed_atomic_publish_leaves_no_destination_or_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "example.conditioning.json"

            with patch(
                "conditioning_layers.persistence.json_codec.os.link",
                side_effect=OSError("simulated publish failure"),
            ):
                with self.assertRaises(DocumentIOError) as raised:
                    save_document(make_document(), path)

            self.assertEqual(raised.exception.code, "io.write_failed")
            self.assertFalse(path.exists())
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_load_missing_file_returns_structured_finding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = load_document(Path(directory) / "missing.conditioning.json")

            self.assertIsNone(result.document)
            self.assertEqual(result.persistence_findings[0].code, "io.read_failed")

    def test_load_rejects_invalid_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.conditioning.json"
            path.write_bytes(b"\xff\xfe")

            result = load_document(path)

            self.assertIsNone(result.document)
            self.assertEqual(result.persistence_findings[0].code, "io.invalid_utf8")


if __name__ == "__main__":
    unittest.main()
