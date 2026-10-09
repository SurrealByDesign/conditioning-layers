from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from conditioning_layers.assets import (
    DEFAULT_INFLUENCE_FIELD_BINDING_TARGET,
    INFLUENCE_FIELD_BINDING_FORMAT_IDENTIFIER,
    FieldOrientation,
    FieldPolarity,
    FieldRelationshipCertificationStatus,
    FieldRelationshipInput,
    InfluenceFieldBindingStatus,
    InfluenceFieldLibrarySelection,
    PartitionClassification,
    bind_influence_field_library,
    fingerprint_field_relationship_certificate,
    fingerprint_influence_field_binding,
    inspect_field_relationships,
    serialize_influence_field_binding,
)
from conditioning_layers.domain import (
    CURRENT_PROTOTYPE_VERSION,
    PREDICTION_MIXING_ADAPTER_ID,
    ConditioningDocument,
    InfluenceFieldAssetReference,
    PromptLayer,
)

from test_inspection import png_bytes


ROOT = Path(__file__).resolve().parents[3]
LIBRARY_ROOT = ROOT / "influence-field-library" / "v1"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def family_record(root: Path, family_id: str) -> dict[str, object]:
    catalog = read_json(root / "library-manifest.json")
    return next(
        item
        for item in catalog["families"]  # type: ignore[index]
        if item["pattern_family_id"] == family_id
    )  # type: ignore[return-value]


def family_manifest(root: Path, family_id: str) -> dict[str, object]:
    record = family_record(root, family_id)
    return read_json(root / str(record["manifest_filename"]))


def selection_for(
    root: Path,
    family_id: str,
    permutation_id: str,
) -> InfluenceFieldLibrarySelection:
    record = family_record(root, family_id)
    return InfluenceFieldLibrarySelection(
        expected_catalog_sha256=sha256_bytes(
            (root / "library-manifest.json").read_bytes()
        ),
        family_identifier=family_id,
        family_version=1,
        permutation_identifier=permutation_id,
        expected_family_manifest_sha256=str(record["manifest_sha256"]),
    )


class BindingTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.case_number = 0

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_case(
        self,
        family_id: str,
        permutation_id: str,
        *,
        library_root: Path = LIBRARY_ROOT,
        document_source_ids: tuple[str, ...] | None = None,
        include_disabled_layer: bool = False,
        layer_ids: tuple[str, ...] | None = None,
        document_references: tuple[str, ...] | None = None,
    ):
        self.case_number += 1
        manifest = family_manifest(library_root, family_id)
        permutation = next(
            item
            for item in manifest["assignment_permutations"]  # type: ignore[index]
            if item["permutation_id"] == permutation_id
        )
        ordered_ids = tuple(permutation["ordered_field_ids"])
        source_ids = document_source_ids or ordered_ids
        field_map = {
            item["asset_id"]: item for item in manifest["fields"]  # type: ignore[index]
        }
        asset_root = self.root / f"document-{self.case_number}.conditioning.assets"
        layers: list[PromptLayer] = []
        certificate_inputs: list[FieldRelationshipInput] = []
        for ordinal, source_id in enumerate(source_ids):
            source = library_root / str(field_map[source_id]["filename"])
            data = source.read_bytes()
            relative = (
                document_references[ordinal]
                if document_references is not None
                else f"fields/layer-{ordinal}.png"
            )
            target = asset_root.joinpath(*relative.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            layer = PromptLayer(
                layer_id=(
                    layer_ids[ordinal]
                    if layer_ids is not None
                    else f"layer-{ordinal}"
                ),
                name=f"Layer {ordinal}",
                prompt_text=f"Prompt {ordinal}",
                visible=True,
                strength=1.0,
                influence_field=InfluenceFieldAssetReference(
                    relative_path=relative,
                    checksum=sha256_bytes(data),
                ),
            )
            document_index = len(layers)
            layers.append(layer)
            certificate_inputs.append(
                FieldRelationshipInput(layer=layer, document_index=document_index)
            )
            if include_disabled_layer and ordinal == 0:
                layers.append(
                    PromptLayer(
                        layer_id="disabled-layer",
                        name="Disabled Layer",
                        prompt_text="Retained but not assigned.",
                        visible=False,
                        strength=1.0,
                    )
                )
        document = ConditioningDocument(
            version=CURRENT_PROTOTYPE_VERSION,
            document_id=f"binding-document-{self.case_number}",
            base_prompt="A neutral reference scene.",
            layers=tuple(layers),
            selected_adapter_id=PREDICTION_MIXING_ADAPTER_ID,
        )
        inspected = inspect_field_relationships(asset_root, tuple(certificate_inputs))
        self.assertEqual(inspected.errors, ())
        self.assertEqual(
            inspected.certificate.status,
            FieldRelationshipCertificationStatus.CERTIFIED,
        )
        return (
            document,
            inspected.certificate,
            selection_for(library_root, family_id, permutation_id),
        )

    def bind(
        self,
        family_id: str,
        permutation_id: str,
        *,
        library_root: Path = LIBRARY_ROOT,
        document_source_ids: tuple[str, ...] | None = None,
        include_disabled_layer: bool = False,
        layer_ids: tuple[str, ...] | None = None,
        document_references: tuple[str, ...] | None = None,
    ):
        document, certificate, selection = self.make_case(
            family_id,
            permutation_id,
            library_root=library_root,
            document_source_ids=document_source_ids,
            include_disabled_layer=include_disabled_layer,
            layer_ids=layer_ids,
            document_references=document_references,
        )
        return bind_influence_field_library(
            library_root,
            document,
            selection,
            certificate,
        )

    def copied_library(self) -> Path:
        target = self.root / f"library-{self.case_number}"
        shutil.copytree(LIBRARY_ROOT, target)
        return target


class ValidBindingTests(BindingTestCase):
    def test_required_two_and_three_layer_families_bind(self) -> None:
        cases = (
            ("two-layer.left-right.v1", "AB"),
            ("two-layer.top-bottom.v1", "AB"),
            ("three-layer.vertical-thirds.v1", "ABC"),
            ("three-layer.horizontal-thirds.v1", "ABC"),
            ("three-layer.center-ring-outer.v1", "ABC"),
        )
        for family_id, permutation_id in cases:
            with self.subTest(family_id=family_id):
                result = self.bind(family_id, permutation_id)
                self.assertEqual(result.errors, ())
                self.assertEqual(
                    result.binding.status,
                    InfluenceFieldBindingStatus.BOUND,
                )
                self.assertEqual(
                    result.binding.format_identifier,
                    INFLUENCE_FIELD_BINDING_FORMAT_IDENTIFIER,
                )
                self.assertTrue(
                    all(
                        assignment.source_and_document_bytes_match
                        for assignment in result.binding.assignments
                    )
                )

    def test_every_committed_manifest_permutation_binds(self) -> None:
        catalog = read_json(LIBRARY_ROOT / "library-manifest.json")
        for record in catalog["families"]:  # type: ignore[index]
            manifest = read_json(LIBRARY_ROOT / record["manifest_filename"])
            for permutation in manifest["assignment_permutations"]:
                with self.subTest(
                    family=record["pattern_family_id"],
                    permutation=permutation["permutation_id"],
                ):
                    result = self.bind(
                        record["pattern_family_id"],
                        permutation["permutation_id"],
                    )
                    self.assertEqual(result.binding.status, InfluenceFieldBindingStatus.BOUND)

    def test_four_field_synthetic_family_is_structurally_bound(self) -> None:
        library_root = self.root / "four-field-library"
        library_root.mkdir()
        field_ids = ("A", "B", "C", "D")
        fields: list[dict[str, object]] = []
        for field_index, field_id in enumerate(field_ids):
            samples = bytes(
                255 if x // 32 == field_index else 0
                for _y in range(128)
                for x in range(128)
            )
            data = png_bytes(128, 128, samples)
            reference = f"four-layer/quarters/field-{field_id.lower()}.png"
            path = library_root / reference
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            fields.append(
                {
                    "asset_id": field_id,
                    "filename": reference,
                    "role": "partition-field",
                    "sha256": sha256_bytes(data),
                }
            )
        family_id = "four-layer.quarters.v1"
        manifest_reference = "manifests/four-layer.quarters.v1.manifest.json"
        manifest = {
            "schema_id": "conditioning-layers.influence-field-family-manifest",
            "schema_version": 1,
            "library_version": 1,
            "pattern_family_id": family_id,
            "resolution": {"width": 128, "height": 128},
            "image_mode": "grayscale-8",
            "layer_count": 4,
            "fields": fields,
            "assignment_permutations": [
                {"permutation_id": "ABCD", "ordered_field_ids": list(field_ids)}
            ],
            "support_status": "research-only",
        }
        manifest_path = library_root / manifest_reference
        write_json(manifest_path, manifest)
        catalog = {
            "library_id": "conditioning-layers.influence-field-library",
            "library_version": 1,
            "families": [
                {
                    "pattern_family_id": family_id,
                    "layer_count": 4,
                    "manifest_filename": manifest_reference,
                    "manifest_sha256": sha256_bytes(manifest_path.read_bytes()),
                    "support_status": "research-only",
                }
            ],
        }
        write_json(library_root / "library-manifest.json", catalog)

        result = self.bind(family_id, "ABCD", library_root=library_root)

        self.assertEqual(result.errors, ())
        self.assertEqual(result.binding.status, InfluenceFieldBindingStatus.BOUND)
        self.assertEqual(len(result.binding.assignments), 4)
        self.assertEqual(result.binding.library.ordered_field_ids, field_ids)

    def test_bound_means_identity_agreement_not_execution_authorization(self) -> None:
        result = self.bind("three-layer.vertical-thirds.v1", "ABC")

        self.assertEqual(result.binding.status, InfluenceFieldBindingStatus.BOUND)
        self.assertIn(
            "binding.execution_not_authorized",
            {finding.code for finding in result.information},
        )
        self.assertTrue(result.binding.certificate.order_matches_assignments)
        self.assertTrue(result.binding.certificate.hashes_match_assignments)

    def test_disabled_layers_are_retained_but_not_assigned(self) -> None:
        result = self.bind(
            "two-layer.left-right.v1",
            "AB",
            include_disabled_layer=True,
        )

        self.assertEqual(result.binding.status, InfluenceFieldBindingStatus.BOUND)
        self.assertEqual(
            tuple(item.document_index for item in result.binding.assignments),
            (0, 2),
        )
        self.assertEqual(
            tuple(item.layer_id for item in result.binding.assignments),
            ("layer-0", "layer-1"),
        )

    def test_models_are_immutable(self) -> None:
        result = self.bind("two-layer.left-right.v1", "AB")
        with self.assertRaises(FrozenInstanceError):
            result.binding.status = InfluenceFieldBindingStatus.UNBOUND  # type: ignore[misc]


class DeterminismAndPermutationTests(BindingTestCase):
    def test_repeated_binding_has_identical_canonical_bytes_and_fingerprint(self) -> None:
        document, certificate, selection = self.make_case(
            "two-layer.left-right.v1", "AB"
        )
        first = bind_influence_field_library(
            LIBRARY_ROOT, document, selection, certificate
        ).binding
        second = bind_influence_field_library(
            LIBRARY_ROOT, document, selection, certificate
        ).binding

        self.assertEqual(first, second)
        self.assertEqual(
            serialize_influence_field_binding(first),
            serialize_influence_field_binding(second),
        )
        self.assertEqual(
            first.fingerprint,
            fingerprint_influence_field_binding(first),
        )
        self.assertNotRegex(
            serialize_influence_field_binding(first),
            r"(?:[A-Za-z]:[\\/]|/(?:Users|home)/)",
        )

    def test_filesystem_creation_order_does_not_affect_binding(self) -> None:
        first_root = self.root / "first-library"
        second_root = self.root / "second-library"
        references = tuple(
            sorted(
                path.relative_to(LIBRARY_ROOT)
                for path in LIBRARY_ROOT.rglob("*")
                if path.is_file()
            )
        )
        for destination, ordered in (
            (first_root, references),
            (second_root, tuple(reversed(references))),
        ):
            for relative in ordered:
                path = destination / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((LIBRARY_ROOT / relative).read_bytes())
        first = self.bind(
            "two-layer.top-bottom.v1", "BA", library_root=first_root
        ).binding
        second = self.bind(
            "two-layer.top-bottom.v1", "BA", library_root=second_root
        ).binding
        self.assertEqual(first, second)

    def test_reordering_assignments_changes_identity_without_sorting(self) -> None:
        first = self.bind("two-layer.left-right.v1", "AB").binding
        second = self.bind("two-layer.left-right.v1", "BA").binding

        self.assertNotEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(
            tuple(item.library_field_id for item in first.assignments),
            ("A", "B"),
        )
        self.assertEqual(
            tuple(item.library_field_id for item in second.assignments),
            ("B", "A"),
        )
        self.assertEqual(
            tuple(item.layer_id for item in first.assignments),
            ("layer-0", "layer-1"),
        )

    def test_layer_id_filename_field_id_and_hash_sorting_never_replace_document_order(self) -> None:
        result = self.bind(
            "two-layer.left-right.v1",
            "BA",
            layer_ids=("z-layer", "a-layer"),
            document_references=("fields/z-field.png", "fields/a-field.png"),
        )

        self.assertEqual(result.binding.status, InfluenceFieldBindingStatus.BOUND)
        self.assertEqual(
            tuple(item.layer_id for item in result.binding.assignments),
            ("z-layer", "a-layer"),
        )
        self.assertEqual(
            tuple(item.document_field_reference for item in result.binding.assignments),
            ("fields/z-field.png", "fields/a-field.png"),
        )
        self.assertEqual(
            tuple(item.library_field_id for item in result.binding.assignments),
            ("B", "A"),
        )

    def test_unknown_selected_permutation_fails_closed(self) -> None:
        document, certificate, selection = self.make_case(
            "two-layer.left-right.v1", "AB"
        )
        selection = replace(selection, permutation_identifier="UNKNOWN")
        result = bind_influence_field_library(
            LIBRARY_ROOT, document, selection, certificate
        )
        self.assertEqual(result.binding.status, InfluenceFieldBindingStatus.UNBOUND)
        self.assertIn("binding.invalid_permutation", {item.code for item in result.errors})


class LibraryIntegrityTests(BindingTestCase):
    def test_catalog_identity_mismatch_fails_closed(self) -> None:
        document, certificate, selection = self.make_case(
            "two-layer.left-right.v1", "AB"
        )
        result = bind_influence_field_library(
            LIBRARY_ROOT,
            document,
            replace(selection, expected_catalog_sha256="0" * 64),
            certificate,
        )
        self.assertIn("binding.catalog_identity_mismatch", {item.code for item in result.errors})
        self.assertEqual(result.binding.status, InfluenceFieldBindingStatus.UNBOUND)

    def test_family_manifest_hash_mismatch_and_malformed_json_fail_closed(self) -> None:
        library_root = self.copied_library()
        record = family_record(library_root, "two-layer.left-right.v1")
        manifest_path = library_root / str(record["manifest_filename"])
        manifest_path.write_text("{malformed", encoding="utf-8")
        selection = InfluenceFieldLibrarySelection(
            expected_catalog_sha256=sha256_bytes(
                (library_root / "library-manifest.json").read_bytes()
            ),
            family_identifier="two-layer.left-right.v1",
            family_version=1,
            permutation_identifier="AB",
            expected_family_manifest_sha256=str(record["manifest_sha256"]),
        )
        document, certificate, _ = self.make_case(
            "two-layer.left-right.v1", "AB"
        )
        result = bind_influence_field_library(
            library_root, document, selection, certificate
        )
        codes = {item.code for item in result.errors}
        self.assertIn("binding.family_manifest_mismatch", codes)
        self.assertIn("binding.malformed_library_metadata", codes)

    def test_missing_and_altered_library_field_bytes_fail_closed(self) -> None:
        for mode in ("missing", "altered"):
            with self.subTest(mode=mode):
                library_root = self.copied_library()
                manifest = family_manifest(library_root, "two-layer.left-right.v1")
                field_path = library_root / manifest["fields"][0]["filename"]  # type: ignore[index]
                if mode == "missing":
                    field_path.unlink()
                else:
                    field_path.write_bytes(field_path.read_bytes() + b"changed")
                document, certificate, selection = self.make_case(
                    "two-layer.left-right.v1", "AB"
                )
                selection = replace(
                    selection,
                    expected_catalog_sha256=sha256_bytes(
                        (library_root / "library-manifest.json").read_bytes()
                    ),
                )
                result = bind_influence_field_library(
                    library_root, document, selection, certificate
                )
                self.assertEqual(result.binding.status, InfluenceFieldBindingStatus.UNBOUND)
                self.assertTrue(
                    {"binding.unknown_field_id", "binding.source_hash_mismatch"}
                    & {item.code for item in result.errors}
                )

    def test_preview_bytes_are_not_inspected_or_identity_bearing(self) -> None:
        library_root = self.copied_library()
        manifest = family_manifest(library_root, "two-layer.left-right.v1")
        preview = library_root / manifest["preview"]["filename"]  # type: ignore[index]
        preview.write_bytes(b"not an image and intentionally ignored")

        result = self.bind(
            "two-layer.left-right.v1", "AB", library_root=library_root
        )

        self.assertEqual(result.errors, ())
        self.assertEqual(result.binding.status, InfluenceFieldBindingStatus.BOUND)

    def test_manifest_path_escape_is_rejected(self) -> None:
        library_root = self.copied_library()
        catalog_path = library_root / "library-manifest.json"
        catalog = read_json(catalog_path)
        catalog["families"][0]["manifest_filename"] = "../outside.json"  # type: ignore[index]
        write_json(catalog_path, catalog)
        document, certificate, _selection = self.make_case(
            "two-layer.left-right.v1", "AB"
        )
        selection = InfluenceFieldLibrarySelection(
            expected_catalog_sha256=sha256_bytes(catalog_path.read_bytes()),
            family_identifier="two-layer.left-right.v1",
            family_version=1,
            permutation_identifier="AB",
        )

        result = bind_influence_field_library(
            library_root, document, selection, certificate
        )

        self.assertIn("binding.reference_non_portable", {item.code for item in result.errors})
        self.assertEqual(result.binding.status, InfluenceFieldBindingStatus.UNBOUND)

    def test_symlink_escape_is_rejected_where_supported(self) -> None:
        library_root = self.copied_library()
        manifest = family_manifest(library_root, "two-layer.left-right.v1")
        field_path = library_root / manifest["fields"][0]["filename"]  # type: ignore[index]
        outside = self.root / "outside-field.png"
        outside.write_bytes(field_path.read_bytes())
        field_path.unlink()
        try:
            field_path.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("platform cannot create a file symlink")
        document, certificate, selection = self.make_case(
            "two-layer.left-right.v1", "AB"
        )
        selection = replace(
            selection,
            expected_catalog_sha256=sha256_bytes(
                (library_root / "library-manifest.json").read_bytes()
            ),
        )

        result = bind_influence_field_library(
            library_root, document, selection, certificate
        )

        self.assertIn("binding.reference_non_portable", {item.code for item in result.errors})
        self.assertEqual(result.binding.status, InfluenceFieldBindingStatus.UNBOUND)

    def test_dimension_and_encoding_metadata_mismatches_fail_closed(self) -> None:
        for key, value in (("resolution", {"width": 127, "height": 128}), ("image_mode", "rgb-identical-8")):
            with self.subTest(key=key):
                library_root = self.copied_library()
                record = family_record(library_root, "two-layer.left-right.v1")
                manifest_path = library_root / str(record["manifest_filename"])
                manifest = read_json(manifest_path)
                manifest[key] = value
                write_json(manifest_path, manifest)
                record["manifest_sha256"] = sha256_bytes(manifest_path.read_bytes())
                catalog_path = library_root / "library-manifest.json"
                catalog = read_json(catalog_path)
                catalog["families"][0] = record  # type: ignore[index]
                write_json(catalog_path, catalog)
                document, certificate, _ = self.make_case(
                    "two-layer.left-right.v1", "AB"
                )
                selection = InfluenceFieldLibrarySelection(
                    expected_catalog_sha256=sha256_bytes(catalog_path.read_bytes()),
                    family_identifier="two-layer.left-right.v1",
                    family_version=1,
                    permutation_identifier="AB",
                    expected_family_manifest_sha256=str(record["manifest_sha256"]),
                )
                result = bind_influence_field_library(
                    library_root, document, selection, certificate
                )
                codes = {item.code for item in result.errors}
                self.assertIn("binding.dimension_encoding_mismatch", codes)
                if key == "image_mode":
                    self.assertIn("binding.malformed_library_metadata", codes)

    def test_partial_duplicate_and_unknown_manifest_permutations_fail_closed(self) -> None:
        mutations = (
            ["A"],
            ["A", "A"],
            ["A", "UNKNOWN"],
        )
        for ordered_ids in mutations:
            with self.subTest(ordered_ids=ordered_ids):
                library_root = self.copied_library()
                record = family_record(library_root, "two-layer.left-right.v1")
                manifest_path = library_root / str(record["manifest_filename"])
                manifest = read_json(manifest_path)
                manifest["assignment_permutations"][0]["ordered_field_ids"] = ordered_ids  # type: ignore[index]
                write_json(manifest_path, manifest)
                record["manifest_sha256"] = sha256_bytes(manifest_path.read_bytes())
                catalog_path = library_root / "library-manifest.json"
                catalog = read_json(catalog_path)
                catalog["families"][0] = record  # type: ignore[index]
                write_json(catalog_path, catalog)
                document, certificate, _ = self.make_case(
                    "two-layer.left-right.v1", "AB"
                )
                selection = InfluenceFieldLibrarySelection(
                    expected_catalog_sha256=sha256_bytes(catalog_path.read_bytes()),
                    family_identifier="two-layer.left-right.v1",
                    family_version=1,
                    permutation_identifier="AB",
                    expected_family_manifest_sha256=str(record["manifest_sha256"]),
                )
                result = bind_influence_field_library(
                    library_root, document, selection, certificate
                )
                self.assertIn("binding.invalid_permutation", {item.code for item in result.errors})


class DocumentAndCertificateIntegrityTests(BindingTestCase):
    def test_changed_document_bytes_fail_exact_source_reconciliation(self) -> None:
        result = self.bind(
            "two-layer.left-right.v1",
            "AB",
            document_source_ids=("B", "A"),
        )
        self.assertEqual(result.binding.status, InfluenceFieldBindingStatus.UNBOUND)
        self.assertIn(
            "binding.certificate_field_hash_mismatch",
            {item.code for item in result.errors},
        )

    def test_duplicate_missing_and_extra_document_assignments_fail_closed(self) -> None:
        document, certificate, selection = self.make_case(
            "two-layer.left-right.v1", "AB"
        )
        duplicate_layer = replace(
            document.layers[1],
            influence_field=document.layers[0].influence_field,
        )
        duplicate_document = replace(
            document,
            layers=(document.layers[0], duplicate_layer),
        )
        duplicate = bind_influence_field_library(
            LIBRARY_ROOT, duplicate_document, selection, certificate
        )
        self.assertIn("binding.assignment_duplicate", {item.code for item in duplicate.errors})

        missing_document = replace(document, layers=document.layers[:1])
        missing = bind_influence_field_library(
            LIBRARY_ROOT, missing_document, selection, certificate
        )
        self.assertIn("binding.assignment_extra", {item.code for item in missing.errors})

        extra_layer = replace(document.layers[0], layer_id="layer-extra")
        extra_document = replace(document, layers=document.layers + (extra_layer,))
        extra = bind_influence_field_library(
            LIBRARY_ROOT, extra_document, selection, certificate
        )
        self.assertIn("binding.assignment_missing", {item.code for item in extra.errors})

    def test_nonportable_document_reference_fails_closed(self) -> None:
        document, certificate, selection = self.make_case(
            "two-layer.left-right.v1", "AB"
        )
        bad_layer = replace(
            document.layers[0],
            influence_field=InfluenceFieldAssetReference(
                "C:/private/field.png",
                document.layers[0].influence_field.checksum,  # type: ignore[union-attr]
            ),
        )
        result = bind_influence_field_library(
            LIBRARY_ROOT,
            replace(document, layers=(bad_layer, document.layers[1])),
            selection,
            certificate,
        )
        self.assertIn("binding.reference_non_portable", {item.code for item in result.errors})

    def test_reordered_wrong_identity_hash_and_uncertified_certificates_fail(self) -> None:
        document, certificate, selection = self.make_case(
            "two-layer.left-right.v1", "AB"
        )
        reordered = replace(certificate, ordered_fields=tuple(reversed(certificate.ordered_fields)))
        reordered = replace(
            reordered,
            fingerprint=fingerprint_field_relationship_certificate(reordered),
        )
        wrong_identity_records = (
            replace(certificate.ordered_fields[0], layer_id="wrong-layer"),
            certificate.ordered_fields[1],
        )
        wrong_identity = replace(certificate, ordered_fields=wrong_identity_records)
        wrong_identity = replace(
            wrong_identity,
            fingerprint=fingerprint_field_relationship_certificate(wrong_identity),
        )
        wrong_hash_records = (
            replace(certificate.ordered_fields[0], source_sha256="f" * 64),
            certificate.ordered_fields[1],
        )
        wrong_hash = replace(certificate, ordered_fields=wrong_hash_records)
        wrong_hash = replace(
            wrong_hash,
            fingerprint=fingerprint_field_relationship_certificate(wrong_hash),
        )
        uncertified = replace(
            certificate,
            status=FieldRelationshipCertificationStatus.UNCERTIFIED,
        )
        uncertified = replace(
            uncertified,
            fingerprint=fingerprint_field_relationship_certificate(uncertified),
        )
        wrong_policy = replace(
            certificate,
            relationship_policy_identifier="different.relationship-policy.v1",
        )
        wrong_policy = replace(
            wrong_policy,
            fingerprint=fingerprint_field_relationship_certificate(wrong_policy),
        )
        cases = (
            (reordered, "binding.certificate_order_mismatch"),
            (wrong_identity, "binding.certificate_order_mismatch"),
            (wrong_hash, "binding.certificate_field_hash_mismatch"),
            (replace(certificate, fingerprint="0" * 64), "binding.certificate_fingerprint_mismatch"),
            (uncertified, "binding.certificate_uncertified"),
            (wrong_policy, "binding.certificate_policy_mismatch"),
        )
        for changed, code in cases:
            with self.subTest(code=code):
                result = bind_influence_field_library(
                    LIBRARY_ROOT, document, selection, changed
                )
                self.assertEqual(result.binding.status, InfluenceFieldBindingStatus.UNBOUND)
                self.assertIn(code, {item.code for item in result.errors})

    def test_partition_classification_is_evidence_not_execution_authority(self) -> None:
        document, certificate, selection = self.make_case(
            "three-layer.vertical-thirds.v1", "ABC"
        )
        changed = replace(
            certificate,
            partition_classification=PartitionClassification.OVERLAPPING,
        )
        changed = replace(
            changed,
            fingerprint=fingerprint_field_relationship_certificate(changed),
        )
        result = bind_influence_field_library(
            LIBRARY_ROOT, document, selection, changed
        )
        self.assertEqual(result.binding.status, InfluenceFieldBindingStatus.BOUND)
        self.assertIn(
            "binding.execution_not_authorized",
            {item.code for item in result.information},
        )


class SpatialContractAndFingerprintTests(BindingTestCase):
    def test_polarity_orientation_and_all_transform_mismatches_fail(self) -> None:
        document, certificate, selection = self.make_case(
            "two-layer.left-right.v1", "AB"
        )
        cases = (
            (
                replace(certificate, polarity=replace(certificate.polarity, inverted=True)),
                "binding.polarity_mismatch",
            ),
            (
                replace(certificate, orientation=replace(certificate.orientation, origin="bottom_left")),
                "binding.orientation_mismatch",
            ),
            (
                replace(certificate, orientation=replace(certificate.orientation, mirrored_x=True)),
                "binding.orientation_mismatch",
            ),
            (
                replace(certificate, orientation=replace(certificate.orientation, mirrored_y=True)),
                "binding.orientation_mismatch",
            ),
            (
                replace(certificate, orientation=replace(certificate.orientation, rotation_degrees=90)),
                "binding.orientation_mismatch",
            ),
            (
                replace(certificate, orientation=replace(certificate.orientation, resizing="fit")),
                "binding.unsupported_transform",
            ),
            (
                replace(certificate, orientation=replace(certificate.orientation, interpolation="linear")),
                "binding.unsupported_transform",
            ),
            (
                replace(certificate, orientation=replace(certificate.orientation, transformation="implicit")),
                "binding.unsupported_transform",
            ),
        )
        for changed, code in cases:
            with self.subTest(code=code, changed=changed):
                changed = replace(
                    changed,
                    fingerprint=fingerprint_field_relationship_certificate(changed),
                )
                result = bind_influence_field_library(
                    LIBRARY_ROOT, document, selection, changed
                )
                self.assertIn(code, {item.code for item in result.errors})
                self.assertEqual(result.binding.status, InfluenceFieldBindingStatus.UNBOUND)

    def test_fingerprint_covers_every_claimed_identity_boundary(self) -> None:
        binding = self.bind("two-layer.left-right.v1", "AB").binding
        assignment = binding.assignments[0]
        mutations = (
            replace(binding, format_version=2),
            replace(binding, status=InfluenceFieldBindingStatus.UNBOUND),
            replace(binding, target=replace(binding.target, adapter_identifier="different.v1")),
            replace(binding, target=replace(binding.target, backend_identifier="different.backend")),
            replace(binding, target=replace(binding.target, condition_kind="different-kind")),
            replace(binding, target=replace(binding.target, translation_contract_identifier="different.v2")),
            replace(binding, target=replace(binding.target, topology_policy_identifier="different.v1")),
            replace(binding, target=replace(binding.target, runtime_profile_identifier="different.runtime.v1")),
            replace(binding, library=replace(binding.library, expected_library_identifier="different.library")),
            replace(binding, library=replace(binding.library, expected_library_version=2)),
            replace(binding, library=replace(binding.library, expected_catalog_sha256="0" * 64)),
            replace(binding, library=replace(binding.library, observed_catalog_sha256="5" * 64)),
            replace(binding, library=replace(binding.library, selected_family_identifier="different.family.v1")),
            replace(binding, library=replace(binding.library, selected_family_version=2)),
            replace(binding, library=replace(binding.library, expected_family_manifest_sha256="1" * 64)),
            replace(binding, library=replace(binding.library, observed_family_manifest_sha256="6" * 64)),
            replace(binding, library=replace(binding.library, permutation_identifier="BA")),
            replace(binding, assignments=tuple(reversed(binding.assignments))),
            replace(binding, assignments=(replace(assignment, layer_id="changed"),) + binding.assignments[1:]),
            replace(binding, assignments=(replace(assignment, document_index=9),) + binding.assignments[1:]),
            replace(binding, assignments=(replace(assignment, document_field_reference="fields/other.png"),) + binding.assignments[1:]),
            replace(binding, assignments=(replace(assignment, library_field_id="Z"),) + binding.assignments[1:]),
            replace(binding, assignments=(replace(assignment, library_field_reference="different.png"),) + binding.assignments[1:]),
            replace(binding, assignments=(replace(assignment, expected_library_source_sha256="2" * 64),) + binding.assignments[1:]),
            replace(binding, assignments=(replace(assignment, observed_library_source_sha256="7" * 64),) + binding.assignments[1:]),
            replace(binding, assignments=(replace(assignment, inspected_document_field_sha256="3" * 64),) + binding.assignments[1:]),
            replace(binding, assignments=(replace(assignment, width=64),) + binding.assignments[1:]),
            replace(binding, assignments=(replace(assignment, encoding="other"),) + binding.assignments[1:]),
            replace(binding, assignments=(replace(assignment, polarity=FieldPolarity(inverted=True)),) + binding.assignments[1:]),
            replace(binding, assignments=(replace(assignment, orientation=FieldOrientation(rotation_degrees=90)),) + binding.assignments[1:]),
            replace(binding, certificate=replace(binding.certificate, fingerprint="4" * 64)),
            replace(binding, certificate=replace(binding.certificate, relationship_policy_identifier="other.v1")),
            replace(binding, certificate=replace(binding.certificate, ordered_layer_ids=tuple(reversed(binding.certificate.ordered_layer_ids)))),
            replace(binding, findings=()),
        )
        observed = {
            fingerprint_influence_field_binding(item) for item in mutations
        }
        self.assertEqual(len(observed), len(mutations))
        self.assertNotIn(binding.fingerprint, observed)


if __name__ == "__main__":
    unittest.main()
