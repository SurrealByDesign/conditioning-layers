from __future__ import annotations

from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from conditioning_layers.adapters.prediction_mixing import EFFECTIVE_WEIGHT_EXPRESSION
from conditioning_layers.capabilities import (
    PREDICTION_MIXING_CAPABILITY,
    SupportStatus,
    evaluate_prediction_mixing,
    multi_layer, product,
)
from conditioning_layers.domain import (
    CURRENT_PROTOTYPE_VERSION,
    ConditioningDocument,
    FindingSeverity,
    InfluenceFieldAssetReference,
    PromptLayer,
    ValidationFinding,
)
from conditioning_layers.integrations.comfyui_panel.guidance import (
    panel_capability_guidance,
    project_product_warnings,
)


STATIC_CODES = {
    "capability.adapter_experimental",
    "risk.seam",
    "risk.leakage",
    "risk.fusion",
    "risk.topology",
    "risk.runtime_scaling",
    "risk.vram",
}


def document(*, strength: float = 1.0, visible: bool = True) -> ConditioningDocument:
    return ConditioningDocument(
        version=CURRENT_PROTOTYPE_VERSION,
        document_id="guidance-test",
        base_prompt="Base",
        selected_adapter_id=PREDICTION_MIXING_CAPABILITY.adapter_identifier,
        layers=(
            PromptLayer(
                layer_id="layer-a",
                name="A",
                prompt_text="A red object",
                strength=strength,
                visible=visible,
                influence_field=InfluenceFieldAssetReference("fields/a.png"),
            ),
        ),
    )


class GuidanceTests(unittest.TestCase):
    def test_active_guidance_uses_admitted_authority_without_capping_documents(self) -> None:
        capability = PREDICTION_MIXING_CAPABILITY
        result = panel_capability_guidance()
        self.assertEqual(result["minimum_active_layers"], capability.minimum_visible_prompt_layers)
        self.assertEqual(capability.maximum_tested_visible_prompt_layers, 2)
        self.assertEqual(result["maximum_active_layers"], 3)
        self.assertEqual(result["supported_active_layer_counts"], [1, 2, 3])
        self.assertIn("1 to 3 Active Prompt Layers", result["active_guidance"])
        self.assertIn("Only Active layers participate", result["active_guidance"])
        self.assertIn("Disabled layers remain saved", result["active_guidance"])
        self.assertIn("zero Strength still counts", result["active_guidance"])
        # Frozen ordinary-v1 maximum is no longer product admission authority.
        with patch(
            "conditioning_layers.integrations.comfyui_panel.guidance.PREDICTION_MIXING_CAPABILITY",
            replace(capability, maximum_tested_visible_prompt_layers=4),
        ):
            changed = panel_capability_guidance()
        self.assertEqual(changed["maximum_active_layers"], 3)
        self.assertEqual(changed["supported_active_layer_counts"], [1, 2, 3])
        self.assertIn("1 to 3 Active Prompt Layers", changed["active_guidance"])

    def test_sparse_admitted_set_is_not_displayed_as_a_range(self) -> None:
        with patch("conditioning_layers.integrations.comfyui_panel.guidance.product_supported_cardinalities", return_value=(1, 3)):
            result = panel_capability_guidance()
        self.assertIsNone(result["maximum_active_layers"])
        self.assertEqual(result["supported_active_layer_counts"], [1, 3])
        self.assertIn("1, 3 Active Prompt Layers", result["active_guidance"])

    def test_strength_order_overlap_and_profile_match_current_semantics(self) -> None:
        capability = PREDICTION_MIXING_CAPABILITY
        result = panel_capability_guidance()
        strength = result["strength_guidance"]
        self.assertIn("requested overall influence", strength)
        self.assertIn("Field values are multiplied by Strength", strength)
        self.assertEqual(
            EFFECTIVE_WEIGHT_EXPRESSION,
            "effective field weight = normalized field value \u00d7 requested Strength",
        )
        self.assertIn("0.0 to 1.0", strength)
        self.assertIn("not perceptually linear or Opacity", strength)
        self.assertIn("Normalization can cancel equal scaling", strength)
        self.assertEqual(result["order_guidance"], capability.retained_order_execution.note)
        self.assertIn("not interpreted as execution priority", result["order_guidance"])
        self.assertIs(capability.overlap.status, SupportStatus.UNSUPPORTED)
        self.assertIn("No Overlap: overlapping Active Influence Fields are rejected before generation", result["overlap_guidance"])
        self.assertIn("Normalized Blend: overlapping Active Influence Fields are allowed under explicit Blend policy", result["overlap_guidance"])
        self.assertIn("exactly three Active Prompt Layers", result["overlap_guidance"])
        self.assertEqual(result["profile_guidance"], capability.tested_resolution.statement)

    def test_blend_guidance_tracks_product_authority_and_retains_format_limitation(self) -> None:
        admitted = panel_capability_guidance()
        self.assertEqual([item["supported_active_layer_counts"] for item in admitted["composition_policies"]], [[1, 2, 3], [3]])
        self.assertIn("exactly three Active Prompt Layers", admitted["blend_guidance"])
        with patch.object(product, "PRODUCT_ADMITTED_ENTRIES", multi_layer.PRODUCT_ADMITTED_ENTRIES):
            closed = panel_capability_guidance()
        self.assertEqual([item["supported_active_layer_counts"] for item in closed["composition_policies"]], [[1, 2, 3], []])
        self.assertIn("not product admitted", closed["blend_guidance"])
        self.assertIn("Normalized Blend generation is unavailable", closed["overlap_guidance"])
        self.assertEqual(admitted["explicit_no_overlap_guidance"], closed["explicit_no_overlap_guidance"])
        self.assertIn("cannot execute", admitted["explicit_no_overlap_guidance"])

    def test_persistent_findings_are_bounded_existing_product_authority(self) -> None:
        capability = PREDICTION_MIXING_CAPABILITY
        result = panel_capability_guidance()
        findings = {item["code"]: item for item in result["findings"]}
        self.assertEqual(set(findings), STATIC_CODES)
        self.assertEqual(len(result["findings"]), 7)
        self.assertEqual(result["status"], capability.status.value)
        self.assertEqual(result["backend_name"], capability.backend_name)
        self.assertEqual(
            findings["capability.adapter_experimental"]["message"],
            capability.production_quality.note,
        )
        for risk in capability.known_risks:
            self.assertEqual(findings[risk.code]["message"], risk.message)
        self.assertEqual(findings["risk.runtime_scaling"]["message"], capability.runtime_scaling.statement)
        self.assertEqual(findings["risk.vram"]["message"], capability.vram.statement)
        for finding in findings.values():
            self.assertEqual(set(finding), {"code", "severity", "message"})
            self.assertEqual(finding["severity"], "warning")
        self.assertNotIn("evidence_reference", json.dumps(result))

    def test_success_projection_excludes_unrelated_and_qualification_findings(self) -> None:
        evaluation = evaluate_prediction_mixing(document())
        unrelated = tuple(
            ValidationFinding(code, FindingSeverity.WARNING, "Private diagnostic detail")
            for code in (
                "runtime_qualification.resource_unqualified",
                "exp0014.stage0.failed",
                "execution.host_diagnostic",
                "risk.future_unreviewed",
            )
        )
        wrong_severity = ValidationFinding(
            "capability.zero_strength_active", FindingSeverity.ERROR, "Not a warning"
        )
        result = project_product_warnings(
            unrelated + (wrong_severity,) + evaluation.warnings + evaluation.warnings
        )
        self.assertEqual({item.code for item in result}, STATIC_CODES)
        self.assertEqual(len(result), 7)
        source_messages = {item.code: item.message for item in evaluation.warnings}
        for finding in result:
            self.assertEqual(finding.message, source_messages[finding.code])
        self.assertNotIn("Private diagnostic", json.dumps([item.to_json() for item in result]))
        self.assertEqual(project_product_warnings(unrelated), ())

    def test_zero_strength_warning_is_conditional_on_actual_active_intent(self) -> None:
        for strength, visible, expected in ((1.0, True, False), (0.0, True, True), (0.0, False, False)):
            with self.subTest(strength=strength, visible=visible):
                evaluation = evaluate_prediction_mixing(document(strength=strength, visible=visible))
                result = project_product_warnings(evaluation.warnings)
                self.assertEqual("capability.zero_strength_active" in {item.code for item in result}, expected)
                self.assertEqual(len(result), 8 if expected else 7)
                self.assertEqual(evaluation.active_layer_count, 1 if visible else 0)

    def test_selected_warning_text_and_labels_remain_bounded(self) -> None:
        finding = ValidationFinding(
            "risk.seam", FindingSeverity.WARNING, "Long warning " * 100, layer_id="layer-a"
        )
        result = project_product_warnings((finding,), {"layer-a": "Layer A " * 100})
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0].message), 240)
        self.assertEqual(len(result[0].layer), 96)


if __name__ == "__main__":
    unittest.main()
