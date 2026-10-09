from __future__ import annotations

from pathlib import Path
import unittest

from conditioning_layers.persistence import (
    AssetPathError,
    document_asset_root,
    normalize_asset_reference,
    resolve_asset_path,
)


class AssetPathTests(unittest.TestCase):
    def test_document_asset_directory_convention(self) -> None:
        document = Path("work/example.conditioning.json")

        self.assertEqual(
            document_asset_root(document),
            Path("work/example.conditioning.assets"),
        )

    def test_valid_nested_reference_is_preserved(self) -> None:
        self.assertEqual(
            normalize_asset_reference("fields/subjects/left.png"),
            "fields/subjects/left.png",
        )

    def test_windows_separators_are_normalized(self) -> None:
        self.assertEqual(
            normalize_asset_reference(r"fields\subjects\left.png"),
            "fields/subjects/left.png",
        )

    def test_resolve_joins_only_beneath_asset_root(self) -> None:
        self.assertEqual(
            resolve_asset_path(
                Path("work/example.conditioning.json"),
                r"fields\left.png",
            ),
            Path("work/example.conditioning.assets/fields/left.png"),
        )

    def test_unsafe_windows_and_traversal_cases_are_rejected(self) -> None:
        cases = {
            r"C:\fields\field.png": "asset.path.drive_qualified",
            "C:/fields/field.png": "asset.path.drive_qualified",
            r"\\server\share\field.png": "asset.path.unc",
            r"..\field.png": "asset.path.traversal",
            r"folder\..\field.png": "asset.path.traversal",
            "/fields/field.png": "asset.path.absolute",
            "": "asset.path.empty",
        }

        for value, expected_code in cases.items():
            with self.subTest(value=value):
                with self.assertRaises(AssetPathError) as raised:
                    normalize_asset_reference(value)
                self.assertEqual(raised.exception.code, expected_code)

    def test_empty_segments_are_rejected(self) -> None:
        for value in ("fields//field.png", "fields/./field.png", "fields/"):
            with self.subTest(value=value):
                with self.assertRaises(AssetPathError) as raised:
                    normalize_asset_reference(value)
                self.assertEqual(raised.exception.code, "asset.path.empty_segment")


if __name__ == "__main__":
    unittest.main()
