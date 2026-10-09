from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib
import math
import unittest

from conditioning_layers.adapters.prediction_mixing import (
    EFFECTIVE_WEIGHT_EXPRESSION,
    PREDICTION_MIXING_EXECUTION_PROFILE,
    BasePromptPolicy,
    FieldAssetProfile,
    FieldChannelProfile,
    FieldValueKind,
    NegativePromptPolicy,
    OverlapAssessment,
    combine_prompt_text,
    translate_prediction_mixing,
)
from conditioning_layers.capabilities import PREDICTION_MIXING_CAPABILITY
from conditioning_layers.domain import (
    CURRENT_PROTOTYPE_VERSION,
    ConditioningDocument,
    InfluenceFieldAssetReference,
    PromptLayer,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
_AUTO_OVERLAP = object()


def make_layer(
    layer_id: str,
    *,
    visible: bool = True,
    strength: float = 1.0,
    path: str | None = None,
    checksum: str | None = SHA_A,
    name: str | None = None,
    prompt: str | None = None,
) -> PromptLayer:
    return PromptLayer(
        layer_id=layer_id,
        name=name or f"Layer {layer_id}",
        prompt_text=prompt or f"Prompt {layer_id}",
        visible=visible,
        strength=strength,
        influence_field=InfluenceFieldAssetReference(
            relative_path=path or f"fields/{layer_id}.png",
            checksum=checksum,
        ),
    )


def make_document(
    *layers: PromptLayer,
    base_prompt: str = "A coherent studio scene",
    adapter_id: str = PREDICTION_MIXING_CAPABILITY.adapter_identifier,
    adapter_settings: object = None,
) -> ConditioningDocument:
    return ConditioningDocument(
        version=CURRENT_PROTOTYPE_VERSION,
        document_id="document-1",
        base_prompt=base_prompt,
        layers=layers,
        selected_adapter_id=adapter_id,
        adapter_settings={} if adapter_settings is None else adapter_settings,
    )


def make_profile(
    layer_id: str,
    *,
    path: str | None = None,
    checksum: str | None = SHA_A,
    width: int = 128,
    height: int = 128,
    channel_count: int = 1,
    channel_profile: FieldChannelProfile = FieldChannelProfile.GRAYSCALE_8,
    minimum: float = 0.0,
    maximum: float = 1.0,
    finite_values: bool = True,
    value_kind: FieldValueKind = FieldValueKind.CONTINUOUS,
) -> FieldAssetProfile:
    return FieldAssetProfile(
        layer_id=layer_id,
        relative_path=path or f"fields/{layer_id}.png",
        checksum=checksum,
        width=width,
        height=height,
        channel_count=channel_count,
        channel_profile=channel_profile,
        minimum_normalized_value=minimum,
        maximum_normalized_value=maximum,
        finite_values=finite_values,
        value_kind=value_kind,
    )


def profiles_for(document: ConditioningDocument) -> tuple[FieldAssetProfile, ...]:
    profiles: list[FieldAssetProfile] = []
    for layer in document.active_layers:
        reference = layer.influence_field
        assert reference is not None
        profiles.append(
            make_profile(
                layer.layer_id,
                path=reference.relative_path.replace("\\", "/"),
                checksum=reference.checksum,
            )
        )
    return tuple(profiles)


def translate(
    document: ConditioningDocument,
    profiles: tuple[FieldAssetProfile, ...] | None = None,
    *,
    overlap: object = _AUTO_OVERLAP,
    execution_profile=PREDICTION_MIXING_EXECUTION_PROFILE,
):
    if overlap is _AUTO_OVERLAP:
        overlap = (
            OverlapAssessment.NO_OVERLAP
            if len(document.active_layers) == 2
            else None
        )
    return translate_prediction_mixing(
        document,
        profiles_for(document) if profiles is None else profiles,
        overlap_assessment=overlap,  # type: ignore[arg-type]
        execution_profile=execution_profile,
    )


def codes(findings: tuple[object, ...]) -> set[str]:
    return {finding.code for finding in findings}  # type: ignore[attr-defined]


class SuccessfulTranslationTests(unittest.TestCase):
    def test_frozen_execution_profile_delegates_maximum_to_capability_record(self) -> None:
        self.assertEqual(
            PREDICTION_MIXING_EXECUTION_PROFILE.maximum_active_layers,
            PREDICTION_MIXING_CAPABILITY.maximum_tested_visible_prompt_layers,
        )

    def test_one_active_layer_translates_without_pair_assessment(self) -> None:
        result = translate(make_document(make_layer("one")))

        self.assertTrue(result.compatible, result.errors)
        self.assertTrue(result.translated)
        self.assertIsNotNone(result.plan)
        self.assertEqual(result.plan.active_layer_count, 1)  # type: ignore[union-attr]
        self.assertIsNone(result.plan.overlap_assessment)  # type: ignore[union-attr]

    def test_two_active_layers_translate_with_no_overlap(self) -> None:
        result = translate(
            make_document(make_layer("one"), make_layer("two"))
        )

        self.assertTrue(result.translated, result.errors)
        self.assertEqual(
            result.plan.overlap_assessment,  # type: ignore[union-attr]
            OverlapAssessment.NO_OVERLAP,
        )

    def test_disabled_layers_are_excluded_and_recorded(self) -> None:
        document = make_document(
            make_layer("one"),
            make_layer("disabled", visible=False, path="fields/disabled.jpg"),
            make_layer("two"),
        )

        result = translate(document)
        plan = result.plan

        self.assertTrue(result.translated, result.errors)
        self.assertEqual(plan.excluded_disabled_layer_ids, ("disabled",))  # type: ignore[union-attr]
        self.assertEqual(
            tuple(condition.layer_id for condition in plan.active_regional_conditions),  # type: ignore[union-attr]
            ("one", "two"),
        )
        self.assertEqual(plan.document_order_layer_ids, ("one", "disabled", "two"))  # type: ignore[union-attr]

    def test_base_and_regional_prompts_use_exact_two_newline_rule(self) -> None:
        document = make_document(
            make_layer("one", prompt="regional text"),
            base_prompt="base text",
        )

        result = translate(document)
        condition = result.plan.active_regional_conditions[0]  # type: ignore[union-attr]

        self.assertEqual(condition.combined_prompt_text, "base text\n\nregional text")
        self.assertEqual(combine_prompt_text("base ", " regional"), "base \n\n regional")

    def test_empty_base_prompt_is_rejected_by_existing_domain_contract(self) -> None:
        result = translate(
            make_document(make_layer("one"), base_prompt="")
        )

        self.assertFalse(result.translated)
        self.assertIn("translation.capability_incompatible", codes(result.errors))
        self.assertIn(
            "document.base_prompt.empty",
            codes(result.capability_evaluation.errors),
        )

    def test_strength_is_preserved_and_expression_is_exact(self) -> None:
        result = translate(
            make_document(make_layer("one", strength=0.375))
        )
        condition = result.plan.active_regional_conditions[0]  # type: ignore[union-attr]

        self.assertEqual(condition.requested_strength, 0.375)
        self.assertEqual(
            condition.effective_weight_expression,
            EFFECTIVE_WEIGHT_EXPRESSION,
        )
        self.assertEqual(
            result.plan.effective_weight_expression,  # type: ignore[union-attr]
            EFFECTIVE_WEIGHT_EXPRESSION,
        )

    def test_visible_zero_strength_layer_is_retained(self) -> None:
        result = translate(
            make_document(make_layer("zero", strength=0.0))
        )

        self.assertTrue(result.translated, result.errors)
        self.assertEqual(
            result.plan.active_regional_conditions[0].requested_strength,  # type: ignore[union-attr]
            0.0,
        )
        self.assertIn("capability.zero_strength_active", codes(result.warnings))

    def test_document_order_and_original_indexes_are_retained(self) -> None:
        document = make_document(
            make_layer("first"),
            make_layer("disabled", visible=False),
            make_layer("third"),
        )

        result = translate(document)

        self.assertEqual(
            tuple(
                condition.document_index
                for condition in result.plan.active_regional_conditions  # type: ignore[union-attr]
            ),
            (0, 2),
        )
        self.assertIn("no execution-priority meaning", result.plan.order_semantics)  # type: ignore[union-attr]

    def test_unicode_names_and_prompts_are_preserved(self) -> None:
        document = make_document(
            make_layer("one", name="Lumière 青", prompt="青い花 — lumière"),
            base_prompt="静かな café",
        )

        condition = translate(document).plan.active_regional_conditions[0]  # type: ignore[union-attr]

        self.assertEqual(condition.layer_name, "Lumière 青")
        self.assertEqual(condition.regional_prompt_text, "青い花 — lumière")
        self.assertEqual(
            condition.combined_prompt_text,
            "静かな café\n\n青い花 — lumière",
        )

    def test_plan_emits_no_separate_global_or_negative_condition(self) -> None:
        plan = translate(make_document(make_layer("one"))).plan

        self.assertFalse(plan.separate_global_condition_emitted)  # type: ignore[union-attr]
        self.assertIs(
            plan.execution_profile.base_prompt_policy,  # type: ignore[union-attr]
            BasePromptPolicy.REPEAT_IN_REGIONAL_PROMPTS,
        )
        self.assertIs(
            plan.execution_profile.negative_prompt_policy,  # type: ignore[union-attr]
            NegativePromptPolicy.EMPTY,
        )

    def test_translation_inputs_and_plan_are_immutable(self) -> None:
        profile = make_profile("one")
        result = translate(make_document(make_layer("one")), (profile,))

        with self.assertRaises(FrozenInstanceError):
            profile.width = 64  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            result.plan.document_id = "changed"  # type: ignore[union-attr,misc]

    def test_translation_does_not_mutate_document(self) -> None:
        document = make_document(make_layer("one"))
        original = make_document(make_layer("one"))

        translate(document)

        self.assertEqual(document, original)


class FieldProfileValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = make_document(make_layer("one"))

    def test_missing_profile_is_rejected(self) -> None:
        result = translate(self.document, ())

        self.assertIn("translation.field_profile_missing", codes(result.errors))

    def test_extra_profile_is_rejected(self) -> None:
        result = translate(
            self.document,
            (make_profile("one"), make_profile("extra")),
        )

        self.assertIn("translation.field_profile_extra", codes(result.errors))

    def test_mismatched_layer_id_reports_missing_and_extra(self) -> None:
        result = translate(self.document, (make_profile("other"),))

        self.assertIn("translation.field_profile_missing", codes(result.errors))
        self.assertIn("translation.field_profile_extra", codes(result.errors))

    def test_duplicate_profile_is_rejected(self) -> None:
        result = translate(
            self.document,
            (make_profile("one"), make_profile("one")),
        )

        self.assertIn("translation.field_profile_duplicate", codes(result.errors))

    def test_mismatched_path_is_rejected(self) -> None:
        result = translate(
            self.document,
            (make_profile("one", path="fields/different.png"),),
        )

        self.assertIn("translation.field_reference_mismatch", codes(result.errors))

    def test_mismatched_checksum_is_rejected(self) -> None:
        result = translate(
            self.document,
            (make_profile("one", checksum=SHA_B),),
        )

        self.assertIn("translation.field_checksum_mismatch", codes(result.errors))

    def test_wrong_dimensions_are_rejected(self) -> None:
        result = translate(
            self.document,
            (make_profile("one", width=64),),
        )

        self.assertIn("translation.field_dimensions", codes(result.errors))

    def test_unsupported_channel_profile_is_rejected(self) -> None:
        profile = replace(make_profile("one"), channel_profile="rgba_8")  # type: ignore[arg-type]

        result = translate(self.document, (profile,))

        self.assertIn("translation.field_channel_profile", codes(result.errors))

    def test_channel_count_must_match_declared_profile(self) -> None:
        result = translate(
            self.document,
            (make_profile("one", channel_count=4),),
        )

        self.assertIn("translation.field_channel_profile", codes(result.errors))

    def test_nonfinite_status_and_values_are_rejected(self) -> None:
        for profile in (
            make_profile("one", finite_values=False),
            make_profile("one", maximum=math.nan),
            make_profile("one", minimum=-math.inf),
        ):
            with self.subTest(profile=profile):
                result = translate(self.document, (profile,))
                self.assertIn("translation.field_nonfinite", codes(result.errors))

    def test_values_outside_normalized_range_are_rejected(self) -> None:
        for profile in (
            make_profile("one", minimum=-0.01),
            make_profile("one", maximum=1.01),
            make_profile("one", minimum=0.5, maximum=0.5),
        ):
            with self.subTest(profile=profile):
                result = translate(self.document, (profile,))
                self.assertIn("translation.field_range", codes(result.errors))

    def test_valid_binary_profile_is_accepted(self) -> None:
        profile = make_profile("one", value_kind=FieldValueKind.BINARY)

        self.assertTrue(translate(self.document, (profile,)).translated)

    def test_valid_continuous_rgb_profile_is_accepted(self) -> None:
        profile = make_profile(
            "one",
            channel_count=3,
            channel_profile=FieldChannelProfile.RGB_IDENTICAL_8,
            minimum=0.1,
            maximum=0.9,
            value_kind=FieldValueKind.CONTINUOUS,
        )

        self.assertTrue(translate(self.document, (profile,)).translated)

    def test_malformed_profile_checksum_is_rejected(self) -> None:
        result = translate(
            make_document(make_layer("one", checksum=None)),
            (make_profile("one", checksum="bad"),),
        )

        self.assertIn("translation.field_checksum", codes(result.errors))


class OverlapBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.one = make_document(make_layer("one"))
        self.two = make_document(make_layer("one"), make_layer("two"))

    def test_one_layer_requires_no_pair_assessment(self) -> None:
        self.assertTrue(translate(self.one, overlap=None).translated)

    def test_two_layers_accept_no_overlap(self) -> None:
        self.assertTrue(
            translate(
                self.two,
                overlap=OverlapAssessment.NO_OVERLAP,
            ).translated
        )

    def test_overlap_present_is_rejected(self) -> None:
        result = translate(
            self.two,
            overlap=OverlapAssessment.OVERLAP_PRESENT,
        )

        self.assertIn("translation.overlap_present", codes(result.errors))

    def test_unknown_overlap_is_rejected(self) -> None:
        result = translate(
            self.two,
            overlap=OverlapAssessment.UNKNOWN,
        )

        self.assertIn("translation.overlap_unknown", codes(result.errors))

    def test_absent_two_layer_assessment_is_rejected(self) -> None:
        result = translate(self.two, overlap=None)

        self.assertIn("translation.overlap_unknown", codes(result.errors))

    def test_one_layer_rejects_pair_assessment(self) -> None:
        result = translate(
            self.one,
            overlap=OverlapAssessment.NO_OVERLAP,
        )

        self.assertIn("translation.overlap_unexpected", codes(result.errors))


class CapabilityInteractionTests(unittest.TestCase):
    def test_unsupported_adapter_blocks_translation(self) -> None:
        document = make_document(
            make_layer("one"),
            adapter_id="another.adapter",
        )

        result = translate(document)

        self.assertFalse(result.translated)
        self.assertIn("translation.capability_incompatible", codes(result.errors))

    def test_three_active_layers_are_blocked(self) -> None:
        document = make_document(
            make_layer("one"),
            make_layer("two"),
            make_layer("three"),
        )

        result = translate(document)

        self.assertFalse(result.translated)
        self.assertIsNone(result.plan)
        self.assertIn("translation.capability_incompatible", codes(result.errors))
        self.assertIn(
            "capability.active_layer_limit",
            codes(result.capability_evaluation.errors),
        )

    def test_no_active_layers_are_blocked(self) -> None:
        document = make_document(make_layer("disabled", visible=False))

        result = translate(document, ())

        self.assertIn("translation.capability_incompatible", codes(result.errors))
        self.assertIn(
            "capability.active_layer_minimum",
            codes(result.capability_evaluation.errors),
        )

    def test_nonempty_adapter_settings_are_blocked(self) -> None:
        document = make_document(
            make_layer("one"),
            adapter_settings={"unknown": True},
        )

        self.assertFalse(translate(document).translated)

    def test_capability_warnings_are_included_without_duplicates(self) -> None:
        result = translate(make_document(make_layer("one")))
        warning_codes = [finding.code for finding in result.warnings]

        self.assertIn("risk.seam", warning_codes)
        self.assertIn("risk.leakage", warning_codes)
        self.assertIn("risk.fusion", warning_codes)
        self.assertIn("risk.topology", warning_codes)
        self.assertIn("translation.base_prompt_repeated", warning_codes)
        self.assertEqual(len(warning_codes), len(set(warning_codes)))
        self.assertEqual(
            result.plan.mandatory_warning_codes,  # type: ignore[union-attr]
            tuple(warning_codes),
        )

    def test_created_plan_has_informational_finding(self) -> None:
        result = translate(make_document(make_layer("one")))

        self.assertIn("translation.plan_created", codes(result.information))


class FingerprintAndProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = make_document(make_layer("one"), make_layer("two"))

    def test_identical_inputs_produce_identical_fingerprint(self) -> None:
        first = translate(self.document)
        second = translate(self.document)

        self.assertEqual(first.plan, second.plan)
        self.assertEqual(first.plan.fingerprint, second.plan.fingerprint)  # type: ignore[union-attr]
        self.assertEqual(len(first.plan.fingerprint), 64)  # type: ignore[union-attr]

    def test_profile_input_order_does_not_change_fingerprint(self) -> None:
        profiles = profiles_for(self.document)

        first = translate(self.document, profiles)
        second = translate(self.document, tuple(reversed(profiles)))

        self.assertEqual(first.plan.fingerprint, second.plan.fingerprint)  # type: ignore[union-attr]

    def test_prompt_hashes_are_stable_utf8_sha256(self) -> None:
        document = make_document(
            make_layer("one", prompt="青い花"),
            base_prompt="静かな scene",
        )

        provenance = translate(document).plan.provenance_inputs.layers[0]  # type: ignore[union-attr]

        self.assertEqual(
            provenance.regional_prompt_sha256,
            hashlib.sha256("青い花".encode("utf-8")).hexdigest(),
        )
        self.assertEqual(
            provenance.combined_prompt_sha256,
            hashlib.sha256("静かな scene\n\n青い花".encode("utf-8")).hexdigest(),
        )

    def test_field_hashes_and_warning_codes_are_recorded(self) -> None:
        plan = translate(self.document).plan

        self.assertEqual(
            tuple(layer.field_checksum for layer in plan.provenance_inputs.layers),  # type: ignore[union-attr]
            (SHA_A, SHA_A),
        )
        self.assertEqual(
            plan.provenance_inputs.warning_codes,  # type: ignore[union-attr]
            plan.mandatory_warning_codes,  # type: ignore[union-attr]
        )
        self.assertEqual(
            plan.provenance_inputs.translation_plan_fingerprint,  # type: ignore[union-attr]
            plan.fingerprint,  # type: ignore[union-attr]
        )

    def test_fingerprint_changes_for_each_material_plan_input(self) -> None:
        original = translate(self.document).plan.fingerprint  # type: ignore[union-attr]

        prompt_document = replace(
            self.document,
            layers=(
                replace(self.document.layers[0], prompt_text="changed"),
                self.document.layers[1],
            ),
        )
        strength_document = replace(
            self.document,
            layers=(
                replace(self.document.layers[0], strength=0.5),
                self.document.layers[1],
            ),
        )
        checksum_document = replace(
            self.document,
            layers=(
                replace(
                    self.document.layers[0],
                    influence_field=InfluenceFieldAssetReference(
                        relative_path="fields/one.png",
                        checksum=SHA_B,
                    ),
                ),
                self.document.layers[1],
            ),
        )
        checksum_profiles = (
            make_profile("one", checksum=SHA_B),
            make_profile("two"),
        )
        reordered_document = replace(
            self.document,
            layers=tuple(reversed(self.document.layers)),
        )
        changed_execution = replace(
            PREDICTION_MIXING_EXECUTION_PROFILE,
            profile_identifier="krea2-turbo-bf16-1024.local-audit",
        )

        changed = {
            translate(prompt_document).plan.fingerprint,  # type: ignore[union-attr]
            translate(strength_document).plan.fingerprint,  # type: ignore[union-attr]
            translate(checksum_document, checksum_profiles).plan.fingerprint,  # type: ignore[union-attr]
            translate(reordered_document).plan.fingerprint,  # type: ignore[union-attr]
            translate(
                self.document,
                execution_profile=changed_execution,
            ).plan.fingerprint,  # type: ignore[union-attr]
        }

        self.assertNotIn(original, changed)
        self.assertEqual(len(changed), 5)

    def test_unsupported_execution_profile_is_rejected(self) -> None:
        unsupported = replace(
            PREDICTION_MIXING_EXECUTION_PROFILE,
            output_width=768,
        )

        result = translate(self.document, execution_profile=unsupported)

        self.assertIn("translation.execution_profile", codes(result.errors))


if __name__ == "__main__":
    unittest.main()
