from __future__ import annotations

from dataclasses import replace
import math
import unittest

from conditioning_layers.domain import (
    CURRENT_PROTOTYPE_VERSION,
    PREDICTION_MIXING_ADAPTER_ID,
    ConditioningDocument,
    FindingSeverity,
    InfluenceFieldAssetReference,
    PromptLayer,
    PrototypeDocumentVersion,
    validate_document,
)


def make_layer(
    layer_id: str,
    *,
    visible: bool = True,
    strength: float = 1.0,
) -> PromptLayer:
    return PromptLayer(
        layer_id=layer_id,
        name=f"Layer {layer_id}",
        prompt_text=f"Prompt {layer_id}",
        visible=visible,
        strength=strength,
        influence_field=InfluenceFieldAssetReference(
            relative_path=f"assets/{layer_id}.png"
        ),
    )


def make_document(
    *layers: PromptLayer,
    version: PrototypeDocumentVersion = CURRENT_PROTOTYPE_VERSION,
    adapter_id: str | None = PREDICTION_MIXING_ADAPTER_ID,
    adapter_settings: object = None,
) -> ConditioningDocument:
    settings = {} if adapter_settings is None else adapter_settings
    return ConditioningDocument(
        version=version,
        document_id="document-1",
        base_prompt="A coherent studio scene",
        layers=layers,
        selected_adapter_id=adapter_id,
        adapter_settings=settings,
    )


def codes(findings: tuple[object, ...]) -> set[str]:
    return {finding.code for finding in findings}  # type: ignore[attr-defined]


class DomainValidationTests(unittest.TestCase):
    def test_valid_document_has_no_domain_findings(self) -> None:
        document = make_document(make_layer("a"), make_layer("b", visible=False))

        self.assertEqual(validate_document(document), ())

    def test_three_active_layers_are_intrinsically_valid_domain_intent(self) -> None:
        document = make_document(
            make_layer("a"),
            make_layer("b"),
            make_layer("c"),
        )

        self.assertEqual(validate_document(document), ())

    def test_duplicate_ids_are_reported_together(self) -> None:
        document = make_document(make_layer("same"), make_layer("same"))

        findings = validate_document(document)

        self.assertIn("layer.id.duplicate", codes(findings))
        duplicate = next(f for f in findings if f.code == "layer.id.duplicate")
        self.assertEqual(duplicate.layer_id, "same")
        self.assertEqual(duplicate.severity, FindingSeverity.ERROR)

    def test_empty_layer_id_and_name_are_reported(self) -> None:
        layer = replace(make_layer("valid"), layer_id=" ", name="")

        finding_codes = codes(validate_document(make_document(layer)))

        self.assertIn("layer.id.invalid", finding_codes)
        self.assertIn("layer.name.empty", finding_codes)

    def test_out_of_range_strength_is_reported(self) -> None:
        document = make_document(make_layer("a", strength=1.01))

        self.assertIn("layer.strength.out_of_range", codes(validate_document(document)))

    def test_non_finite_strength_values_are_reported(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                document = make_document(make_layer("a", strength=value))
                self.assertIn(
                    "layer.strength.non_finite",
                    codes(validate_document(document)),
                )

    def test_malformed_checksum_is_reported(self) -> None:
        layer = replace(
            make_layer("a"),
            influence_field=InfluenceFieldAssetReference(
                relative_path="assets/a.png",
                checksum="not-a-sha256-digest",
            ),
        )

        self.assertIn(
            "influence_field.checksum.invalid_format",
            codes(validate_document(make_document(layer))),
        )

    def test_malformed_asset_references_are_reported_without_filesystem_access(self) -> None:
        unsafe_paths = (
            "C:\\private\\field.png",
            "/private/field.png",
            "../outside.png",
            "assets/../outside.png",
            "https://example.test/field.png",
        )

        for path in unsafe_paths:
            with self.subTest(path=path):
                layer = replace(
                    make_layer("a"),
                    influence_field=InfluenceFieldAssetReference(relative_path=path),
                )
                self.assertIn(
                    "influence_field.path.unsafe",
                    codes(validate_document(make_document(layer))),
                )

    def test_unsupported_major_version_is_reported(self) -> None:
        document = make_document(
            version=PrototypeDocumentVersion(major=3, minor=0)
        )

        self.assertIn(
            "document.version.unsupported_major",
            codes(validate_document(document)),
        )

    def test_newer_minor_version_is_a_warning(self) -> None:
        document = make_document(
            version=PrototypeDocumentVersion(major=1, minor=1)
        )

        finding = next(
            f
            for f in validate_document(document)
            if f.code == "document.version.newer_minor"
        )

        self.assertEqual(finding.severity, FindingSeverity.WARNING)

    def test_malformed_adapter_id_and_settings_are_reported(self) -> None:
        document = make_document(
            adapter_id="Invalid Adapter ID",
            adapter_settings=[("unknown", True)],
        )

        finding_codes = codes(validate_document(document))

        self.assertIn("adapter.id.malformed", finding_codes)
        self.assertIn("adapter.settings.invalid_type", finding_codes)
if __name__ == "__main__":
    unittest.main()
