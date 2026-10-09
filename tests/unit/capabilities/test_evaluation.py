from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from conditioning_layers.capabilities import (
    PREDICTION_MIXING_CAPABILITY,
    AdapterStatus,
    evaluate_prediction_mixing,
    validate_prediction_mixing_capability,
)
from conditioning_layers.domain import (
    CURRENT_PROTOTYPE_VERSION,
    ConditioningDocument,
    FindingSeverity,
    InfluenceFieldAssetReference,
    PromptLayer,
)


def make_layer(
    layer_id: str,
    *,
    visible: bool = True,
    strength: float = 1.0,
    path: str | None = None,
) -> PromptLayer:
    reference = InfluenceFieldAssetReference(
        relative_path=path or f"fields/{layer_id}.png",
        checksum="a" * 64,
    )
    return PromptLayer(
        layer_id=layer_id,
        name=f"Layer {layer_id}",
        prompt_text=f"Prompt {layer_id}",
        visible=visible,
        strength=strength,
        influence_field=reference,
    )


def make_document(
    *layers: PromptLayer,
    adapter_id: str | None = PREDICTION_MIXING_CAPABILITY.adapter_identifier,
    adapter_settings: object = None,
) -> ConditioningDocument:
    return ConditioningDocument(
        version=CURRENT_PROTOTYPE_VERSION,
        document_id="document-1",
        base_prompt="A coherent studio scene",
        layers=layers,
        selected_adapter_id=adapter_id,
        adapter_settings={} if adapter_settings is None else adapter_settings,
    )


def codes(findings: tuple[object, ...]) -> set[str]:
    return {finding.code for finding in findings}  # type: ignore[attr-defined]


class CompatibleDocumentTests(unittest.TestCase):
    def test_one_visible_layer_is_compatible_as_constrained_subset(self) -> None:
        result = evaluate_prediction_mixing(make_document(make_layer("one")))

        self.assertTrue(result.compatible, result.errors)
        self.assertEqual(result.active_layer_count, 1)
        self.assertIn("evidence.one_layer_subset", codes(result.warnings))
        self.assertIn("inferred constrained subset", result.summary.evidence_scope)

    def test_two_visible_layers_match_direct_evidence(self) -> None:
        result = evaluate_prediction_mixing(
            make_document(make_layer("one"), make_layer("two"))
        )

        self.assertTrue(result.compatible, result.errors)
        self.assertEqual(result.active_layer_count, 2)
        self.assertIn("evidence.two_layer_observed", codes(result.information))
        self.assertNotIn("evidence.one_layer_subset", codes(result.warnings))

    def test_disabled_layers_are_stored_but_excluded_from_active_count(self) -> None:
        result = evaluate_prediction_mixing(
            make_document(
                make_layer("one"),
                make_layer("two"),
                make_layer("disabled", visible=False, path="fields/disabled.jpg"),
            )
        )

        self.assertTrue(result.compatible, result.errors)
        self.assertEqual(result.active_layer_count, 2)
        self.assertNotIn("capability.field_format", codes(result.errors))

    def test_png_extension_is_case_insensitive(self) -> None:
        result = evaluate_prediction_mixing(
            make_document(make_layer("one", path="fields/one.PNG"))
        )

        self.assertTrue(result.compatible, result.errors)

    def test_zero_strength_visible_layer_remains_active_with_one_warning(self) -> None:
        result = evaluate_prediction_mixing(
            make_document(make_layer("zero", strength=0.0))
        )

        self.assertTrue(result.compatible, result.errors)
        self.assertEqual(result.active_layer_count, 1)
        self.assertEqual(
            [
                finding.code
                for finding in result.warnings
                if finding.code == "capability.zero_strength_active"
            ],
            ["capability.zero_strength_active"],
        )

    def test_absent_adapter_can_be_permitted_for_capability_inspection(self) -> None:
        document = make_document(make_layer("one"), adapter_id=None)

        permitted = evaluate_prediction_mixing(
            document,
            require_selected_adapter=False,
        )
        required = evaluate_prediction_mixing(document)

        self.assertTrue(permitted.compatible, permitted.errors)
        self.assertFalse(required.compatible)
        self.assertIn("capability.adapter_required", codes(required.errors))

    def test_evaluation_does_not_mutate_document(self) -> None:
        document = make_document(make_layer("one"))

        evaluate_prediction_mixing(document)

        self.assertEqual(document, make_document(make_layer("one")))


class RejectedDocumentTests(unittest.TestCase):
    def test_zero_visible_layers_are_rejected(self) -> None:
        result = evaluate_prediction_mixing(
            make_document(make_layer("disabled", visible=False))
        )

        self.assertFalse(result.compatible)
        self.assertIn("capability.active_layer_minimum", codes(result.errors))

    def test_three_visible_layers_are_rejected(self) -> None:
        result = evaluate_prediction_mixing(
            make_document(make_layer("one"), make_layer("two"), make_layer("three"))
        )

        self.assertFalse(result.compatible)
        self.assertIn("capability.active_layer_limit", codes(result.errors))

    def test_legacy_findings_facade_delegates_to_authoritative_evaluation(self) -> None:
        authoritative_error = evaluate_prediction_mixing(
            make_document(
                make_layer("one"),
                make_layer("two"),
                make_layer("three"),
            )
        ).errors[0]
        evaluation = SimpleNamespace(
            errors=(authoritative_error,),
            warnings=(),
        )
        document = make_document(make_layer("one"))

        with patch(
            "conditioning_layers.capabilities.evaluation.evaluate_prediction_mixing",
            return_value=evaluation,
        ) as authority:
            findings = validate_prediction_mixing_capability(document)

        authority.assert_called_once_with(document)
        self.assertEqual(findings, (authoritative_error,))

    def test_missing_active_layer_field_is_rejected(self) -> None:
        layer = replace(make_layer("one"), influence_field=None)

        result = evaluate_prediction_mixing(make_document(layer))

        self.assertIn("capability.field_required", codes(result.errors))

    def test_non_png_active_layer_field_is_rejected(self) -> None:
        result = evaluate_prediction_mixing(
            make_document(make_layer("one", path="fields/one.jpg"))
        )

        self.assertIn("capability.field_format", codes(result.errors))

    def test_unsupported_adapter_is_rejected_even_when_selection_is_optional(self) -> None:
        result = evaluate_prediction_mixing(
            make_document(make_layer("one"), adapter_id="another.adapter"),
            require_selected_adapter=False,
        )

        self.assertIn("capability.adapter_unsupported", codes(result.errors))

    def test_nonempty_adapter_settings_are_rejected(self) -> None:
        result = evaluate_prediction_mixing(
            make_document(make_layer("one"), adapter_settings={"unknown": True})
        )

        self.assertIn(
            "capability.adapter_settings_unsupported",
            codes(result.errors),
        )

    def test_malformed_strength_is_carried_from_domain_validation(self) -> None:
        result = evaluate_prediction_mixing(
            make_document(make_layer("one", strength=1.1))
        )

        self.assertIn("layer.strength.out_of_range", codes(result.errors))


class WarningAndSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.result = evaluate_prediction_mixing(
            make_document(make_layer("one"), make_layer("two"))
        )

    def test_all_mandatory_risk_and_semantic_warnings_are_present(self) -> None:
        expected = {
            "capability.adapter_experimental",
            "risk.seam",
            "risk.leakage",
            "risk.fusion",
            "risk.topology",
            "capability.strength_non_linear",
            "capability.order_nonsemantic",
            "risk.runtime_scaling",
            "risk.vram",
            "evidence.limited",
            "capability.continuous_field_tradeoff",
        }

        self.assertTrue(expected.issubset(codes(self.result.warnings)))

    def test_warning_codes_are_not_duplicated(self) -> None:
        warning_codes = [finding.code for finding in self.result.warnings]

        self.assertEqual(len(warning_codes), len(set(warning_codes)))

    def test_findings_have_expected_severities(self) -> None:
        self.assertTrue(
            all(
                finding.severity is FindingSeverity.WARNING
                for finding in self.result.warnings
            )
        )
        self.assertTrue(
            all(
                finding.severity is FindingSeverity.INFORMATION
                for finding in self.result.information
            )
        )

    def test_summary_is_data_only_and_matches_evaluation(self) -> None:
        summary = self.result.summary

        self.assertEqual(summary.adapter_display_name, "Prediction Mixing (Experimental)")
        self.assertIs(summary.status, AdapterStatus.EXPERIMENTAL)
        self.assertTrue(summary.compatible)
        self.assertEqual(summary.active_layer_count, 2)
        self.assertEqual(summary.tested_maximum, 2)
        self.assertTrue(summary.supported_field_behavior)
        self.assertTrue(summary.unsupported_behavior)
        self.assertEqual(summary.key_warnings, self.result.warnings)
        self.assertIn("strongest direct Phase 1 evidence", summary.evidence_scope)


if __name__ == "__main__":
    unittest.main()
