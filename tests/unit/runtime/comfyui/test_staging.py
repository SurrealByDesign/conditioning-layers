from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from conditioning_layers.runtime.comfyui import (
    StagingDisposition,
    stage_field_assets,
    staging_namespace_for_document,
    validate_field_sources,
)

from _support import FIELD_BYTES, codes, make_case, make_inspection, sha256


class FieldStagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.case = make_case(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def validate(self, artifact=None, provenance=None, inspections=None):
        return validate_field_sources(
            artifact or self.case.artifact,
            provenance or self.case.provenance,
            inspections or self.case.inspections,
            self.case.asset_root,
            self.case.configuration,
        )

    def candidates(self):
        result = self.validate()
        self.assertTrue(result.verified, result.errors)
        return result.candidates

    def test_deterministic_namespace(self) -> None:
        self.assertEqual(
            staging_namespace_for_document("document-1"),
            "conditioning-layers/document-1",
        )
        self.assertEqual(
            staging_namespace_for_document("unsafe/id"),
            staging_namespace_for_document("unsafe/id"),
        )
        self.assertNotIn("unsafe/id", staging_namespace_for_document("unsafe/id"))
        self.assertNotEqual(
            staging_namespace_for_document("CON"), "conditioning-layers/CON"
        )

    def test_new_files_are_copied_byte_identically(self) -> None:
        source_hashes = {
            candidate.layer_id: sha256(candidate.source_path.read_bytes())
            for candidate in self.candidates()
        }
        result = stage_field_assets(self.candidates(), self.case.configuration)
        self.assertTrue(result.successful, result.errors)
        self.assertTrue(
            all(record.disposition is StagingDisposition.CREATED for record in result.records)
        )
        for record in result.records:
            self.assertEqual(
                record.destination_path.read_bytes(), FIELD_BYTES[record.layer_id]
            )
            self.assertEqual(
                sha256(record.source_path.read_bytes()), source_hashes[record.layer_id]
            )

    def test_existing_identical_file_is_reused(self) -> None:
        candidates = self.candidates()
        first = candidates[0]
        first.destination_path.parent.mkdir(parents=True)
        first.destination_path.write_bytes(FIELD_BYTES[first.layer_id])
        result = stage_field_assets(candidates, self.case.configuration)
        record = next(item for item in result.records if item.layer_id == first.layer_id)
        self.assertIs(record.disposition, StagingDisposition.REUSED)
        self.assertFalse(record.cleanup_eligible)
        self.assertIn("runtime.staging_reused", codes(result.information))

    def test_existing_differing_file_is_rejected(self) -> None:
        candidate = self.candidates()[0]
        candidate.destination_path.parent.mkdir(parents=True)
        candidate.destination_path.write_bytes(b"different")
        result = stage_field_assets(self.candidates(), self.case.configuration)
        self.assertFalse(result.successful)
        self.assertIn("runtime.staging_collision", codes(result.errors))
        self.assertEqual(candidate.destination_path.read_bytes(), b"different")

    def test_unsafe_staged_filename_is_rejected(self) -> None:
        layers = list(self.case.provenance.active_layers)
        layers[0] = replace(layers[0], staged_field_filename="../unsafe.png")
        provenance = replace(self.case.provenance, active_layers=tuple(layers))
        graph = self.case.artifact.to_api_graph()
        first_field = next(
            node for node in graph.values() if node["class_type"] == "LoadImageMask"
        )
        first_field["inputs"]["image"] = "../unsafe.png"
        artifact = replace(
            self.case.artifact,
            canonical_graph=graph,
            provenance_inputs=provenance,
        )
        result = self.validate(artifact=artifact, provenance=provenance)
        self.assertFalse(result.verified)
        self.assertIn("runtime.staging_missing", codes(result.errors))

    def test_missing_source_is_rejected(self) -> None:
        (self.case.asset_root / "fields" / "a.png").unlink()
        result = self.validate()
        self.assertIn("runtime.staging_missing", codes(result.errors))

    def test_changed_source_checksum_invalidates_certification(self) -> None:
        (self.case.asset_root / "fields" / "a.png").write_bytes(b"changed")
        result = self.validate()
        self.assertIn("runtime.field_source_changed", codes(result.errors))

    def test_temporary_file_is_cleaned_after_failure(self) -> None:
        candidates = self.candidates()
        with patch(
            "conditioning_layers.runtime.comfyui.staging.os.link",
            side_effect=OSError("injected failure"),
        ):
            result = stage_field_assets(candidates, self.case.configuration)
        self.assertFalse(result.successful)
        self.assertEqual(
            list(self.case.configuration.input_directory.rglob("*.tmp")), []
        )

    def test_extra_inspection_is_not_staged(self) -> None:
        extra = make_inspection("c", b"extra")
        result = self.validate(inspections=self.case.inspections + (extra,))
        self.assertFalse(result.verified)
        self.assertIn("runtime.staging_extra", codes(result.errors))
        self.assertEqual(result.candidates[-1].layer_id, "b")


if __name__ == "__main__":
    unittest.main()
