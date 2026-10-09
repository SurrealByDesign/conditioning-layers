from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import tempfile
import unittest

from conditioning_layers.runtime.comfyui import validate_component_files

from _support import codes, make_case


class ComponentValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.case = make_case(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def validate(self, configuration=None, inventory=None):
        return validate_component_files(
            configuration or self.case.configuration,
            inventory or self.case.inventory,
        )

    def model_path(self) -> Path:
        return (
            self.case.configuration.model_directories["diffusion_models"][0]
            / self.case.inventory.model_filename
        )

    def test_all_files_present_and_matching(self) -> None:
        result = self.validate()
        self.assertTrue(result.verified, result.errors)
        self.assertEqual(len(result.records), 3)
        self.assertTrue(all(record.verified for record in result.records))

    def test_missing_model(self) -> None:
        self.model_path().unlink()
        result = self.validate()
        self.assertIn("runtime.component_missing", codes(result.errors))

    def test_wrong_checksum(self) -> None:
        result = self.validate(
            inventory=replace(self.case.inventory, model_sha256="f" * 64)
        )
        self.assertIn("runtime.component_checksum", codes(result.errors))

    def test_wrong_size(self) -> None:
        result = self.validate(
            inventory=replace(
                self.case.inventory,
                model_size_bytes=self.case.inventory.model_size_bytes + 1,
            )
        )
        self.assertIn("runtime.component_size", codes(result.errors))

    def test_duplicate_filename_ambiguity(self) -> None:
        duplicate_directory = self.case.configuration.model_root / "diffusion-extra"
        duplicate_directory.mkdir()
        shutil.copyfile(
            self.model_path(),
            duplicate_directory / self.case.inventory.model_filename,
        )
        directories = dict(self.case.configuration.model_directories)
        directories["diffusion_models"] = (
            *directories["diffusion_models"],
            duplicate_directory,
        )
        result = self.validate(
            configuration=replace(
                self.case.configuration, model_directories=directories
            )
        )
        self.assertIn("runtime.component_ambiguous", codes(result.errors))

    def test_category_path_mismatch(self) -> None:
        target = (
            self.case.configuration.model_directories["text_encoders"][0]
            / self.case.inventory.model_filename
        )
        self.model_path().replace(target)
        result = self.validate()
        self.assertIn("runtime.component_category", codes(result.errors))


if __name__ == "__main__":
    unittest.main()
