"""Plan v4 diagnostic compatibility with retained 2f4deeb6986e65e2e6fb3305dc409926ad937f4a.

Run through tests/tooling/p3c_offline.py translation (developer CPython 3.10.11).
The case builders also support a fenced differential run against the pinned
translator source; no Git subprocess or production authority is added here.
"""

from dataclasses import replace
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import conditioning_layers.adapters.prediction_mixing.blend.translate as tr
import conditioning_layers.capabilities.blend as capability
from conditioning_layers.adapters.prediction_mixing.v2.models import TranslationStatus
from conditioning_layers.assets import (
    FieldRelationshipInput, fingerprint_field_relationship_certificate,
    inspect_field_relationships, to_field_asset_profile,
)
from conditioning_layers.domain import FindingSeverity, REQUIRE_NO_OVERLAP
from conditioning_layers.domain.execution_projection import fingerprint_document_execution_projection

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tooling"))
from blend_fixture import blend_fixture


ELIGIBILITY = "blend.eligibility.invalid"
PLAN = "blend.plan.invalid"
IDENTITY = "blend.plan.identity"
PROFILE = "blend.profile.invalid"
CERTIFICATE = "translation.certificate_mismatch"

# Captured from the pinned translator before the production edit. These are
# additional compatibility fixtures, not regenerated historical artifacts.
RETAINED_WARNING_CODES = (
    "capability.adapter_experimental", "risk.seam", "risk.leakage", "risk.fusion", "risk.topology",
    "capability.strength_non_linear", "capability.order_nonsemantic", "risk.runtime_scaling",
    "risk.vram", "evidence.limited", "capability.continuous_field_tradeoff",
    "blend.not_live_qualified", "blend.not_product_admitted",
)
RETAINED_IDENTITIES = {
    "standard": ("bc921b6cae1f6004a168ff11e3e736f9419a2f84988bfab59a70e9ca2a8497b0",
                 "13accda46239d0f4662b4777e84b445c14b6617ad6b1b6bbb1222a5851bdde72"),
    "rgb": ("fb1be3c64110ccbafcf229b71a29184f123bfe9ecc716fca7721edde36f4d91d",
            "a55b0930d6aa519f14dc4f54b211d16e4e149638ce6ee9f9dbe302b9cc8dbac4"),
    "disjoint": ("06999f00d6f0346aa00c0bcade84e19d8603d3d605a61e45dc1aefcecf2c3b0f",
                 "198a3340d5c9618ca26735d37cd825420a6e1e48c40bf55e01f3d6ac9f6ac4be"),
    "reordered": ("5c6373e6edc3745cdc02dbd55ccc91b3c625c48c8ed942619d566964afeafad0",
                  "0fd59712c3b2f3d338a3b6afb435d478c2f8f78aa7de29e48f959c780fa846be"),
    "all_zero": ("f9eef10e4f1618f68fc52514ab6ec713d2af8e6b380ad59181e7533b6fdfd754",
                 "88f165b3a563d5ae42a02f2617ec9c50ddfe9a7a7f232a3b0357bd76582e88f5"),
    "subnormal": ("2f7f37ce373cb1641057199bc156349612dfe7d61e5985a751b52237bb1b0df3",
                  "529d3cdf7e60252511bb0a2757a671fd4946983707cc6c45531b9c011e10eca7"),
    "disabled_before": ("209fc6b6fb12f2fed478e614cfc8caf5f42859f6216ef08fe38248a1ac56f074",
                        "914bb76f760bf73a55d1adc8a4928126aa683b1ff7464f9efd75c144bd965c05"),
    "disabled_between": ("8498f2e77be31956b73469bc1235e47d8778d9c8997879b5843beff58f1225eb",
                         "345cdb9cad67a7b09e888d26f01e6b90513ffaafb76742b601cd4ee1a9d27e4e"),
    "disabled_after": ("bc921b6cae1f6004a168ff11e3e736f9419a2f84988bfab59a70e9ca2a8497b0",
                       "13accda46239d0f4662b4777e84b445c14b6617ad6b1b6bbb1222a5851bdde72"),
}


def rehash_plan(plan, **changes):
    changed = replace(plan, **changes)
    return replace(changed, fingerprint=tr.fingerprint_translation_plan_v4(changed))


def rehash_entry(entry, **changes):
    changed = replace(entry, **changes)
    return replace(changed, fingerprint=capability.fingerprint_blend_eligibility(changed))


def rehash_projection(projection, **changes):
    changed = replace(projection, **changes)
    return replace(changed, fingerprint=fingerprint_document_execution_projection(changed))


def rehash_certificate(certificate, **changes):
    changed = replace(certificate, **changes)
    return replace(changed, fingerprint=fingerprint_field_relationship_certificate(changed))


def authority_cases(entry):
    """Entries whose count/policy relations remain independent of authority validity."""
    return (
        ("valid", entry, ()),
        ("equal_copy", replace(entry), ()),
        ("forged", rehash_entry(entry, relationship_constraint="invented"), (ELIGIBILITY,)),
        ("unknown_id", rehash_entry(entry, identifier="unknown.blend.authority"), (ELIGIBILITY,)),
        ("bad_entry_fingerprint", replace(entry, fingerprint="0" * 64), (ELIGIBILITY,)),
        ("float_cardinality", rehash_entry(entry, exact_cardinality=3.0), (ELIGIBILITY,)),
        ("wrong_field_constraint", rehash_entry(entry, field_width=256), (ELIGIBILITY,)),
        ("wrong_contract", rehash_entry(entry, contract_identifier="unknown"), (ELIGIBILITY,)),
    )


def plan_defects(plan):
    """(name, input, pre-authority findings, pre-return findings, late findings).

    Late source/fold validation historically runs only when earlier findings
    are empty. These expectations were checked against the pinned translator
    before changing production code.
    """
    projection = plan.document_projection
    certificate = plan.certificate
    conditions = plan.regional_conditions
    bad_profile = replace(plan.execution_profile, numerical_realization="invented")
    bad_profile = replace(bad_profile, fingerprint=tr.fingerprint_execution_profile(bad_profile))
    reversed_layers = tuple(replace(layer, active_ordinal=index)
                            for index, layer in enumerate(reversed(projection.active_layers)))
    bad_certificate = replace(certificate, fingerprint="0" * 64)
    return (
        ("clean", plan, (), (), ()),
        ("plan_fingerprint", replace(plan, fingerprint="0" * 64), (IDENTITY,), (), ()),
        ("plan_version", rehash_plan(plan, format_version=4.0), (IDENTITY,), (), ()),
        ("profile", rehash_plan(plan, execution_profile=bad_profile), (), (PROFILE,), ()),
        ("projection_type", rehash_plan(plan, document_projection=None), (), (PLAN,), ()),
        ("projection_fingerprint", rehash_plan(plan, document_projection=replace(
            projection, fingerprint="0" * 64)), (), (PLAN,), ()),
        ("projection_json", rehash_plan(plan, document_projection=rehash_projection(
            projection, canonical_adapter_settings_json="{")), (), (PLAN,), ()),
        ("projection_policy", rehash_plan(plan, document_projection=rehash_projection(
            projection, composition_policy=REQUIRE_NO_OVERLAP.reference)), (), (PLAN,), ()),
        ("projection_version", rehash_plan(plan, document_projection=rehash_projection(
            projection, source_document_major_version=1)), (), (PLAN,), ()),
        ("projection_truncated", rehash_plan(plan, document_projection=rehash_projection(
            projection, active_layers=projection.active_layers[:-1])), (), (PLAN,), ()),
        ("projection_reordered", rehash_plan(plan, document_projection=rehash_projection(
            projection, active_layers=tuple(reversed(projection.active_layers)))), (), (PLAN,), ()),
        ("projection_reordered_renumbered", rehash_plan(plan, document_projection=rehash_projection(
            projection, active_layers=reversed_layers)), (), (CERTIFICATE,), ()),
        ("conditions_truncated", rehash_plan(plan, regional_conditions=conditions[:-1]), (), (PLAN,), ()),
        ("condition_prompt", rehash_plan(plan, regional_conditions=(replace(
            conditions[0], combined_prompt_text="invented"),) + conditions[1:]), (), (), (PLAN,)),
        ("conditions_reordered", rehash_plan(plan, regional_conditions=tuple(reversed(conditions))),
         (), (CERTIFICATE,), ()),
        ("field_checksum", rehash_plan(plan, regional_conditions=(replace(conditions[0],
            field_profile=replace(conditions[0].field_profile, checksum="0" * 64)),) + conditions[1:]),
         (), (CERTIFICATE,), ()),
        ("certificate_type", rehash_plan(plan, certificate=None), (), (CERTIFICATE,), ()),
        ("certificate_fingerprint", rehash_plan(plan, certificate=bad_certificate), (), (CERTIFICATE,), ()),
        ("certificate_relationship", rehash_plan(plan, certificate=rehash_certificate(certificate,
            whole_set_evidence=replace(certificate.whole_set_evidence, mutual_exclusion=True))),
         (), (CERTIFICATE,), ()),
        ("certificate_policy", rehash_plan(plan, certificate=rehash_certificate(certificate,
            relationship_policy_identifier="invented")), (), (CERTIFICATE,), ()),
        ("certificate_pairs_reordered", rehash_plan(plan, certificate=rehash_certificate(certificate,
            pairwise_evidence=tuple(reversed(certificate.pairwise_evidence)))), (), (CERTIFICATE,), ()),
        ("certificate_pairs_truncated", rehash_plan(plan, certificate=rehash_certificate(certificate,
            pairwise_evidence=certificate.pairwise_evidence[:-1])), (), (CERTIFICATE,), ()),
        ("certificate_fields_reordered", rehash_plan(plan, certificate=rehash_certificate(certificate,
            ordered_fields=tuple(reversed(certificate.ordered_fields)))), (), (CERTIFICATE,), ()),
        ("topology", rehash_plan(plan, topology_policy=None), (), (), (PLAN,)),
        ("fold_reordered", rehash_plan(plan, fold_schedule=tuple(reversed(plan.fold_schedule))), (), (), (PLAN,)),
        ("fold_truncated", rehash_plan(plan, fold_schedule=plan.fold_schedule[:-1]), (), (), (PLAN,)),
        ("profile_and_certificate", rehash_plan(plan, execution_profile=bad_profile,
            certificate=bad_certificate), (), (PROFILE, CERTIFICATE), ()),
        ("identity_profile_certificate", rehash_plan(plan, format_version=4.0,
            execution_profile=bad_profile, certificate=bad_certificate), (IDENTITY,), (PROFILE, CERTIFICATE), ()),
        ("identity_profile_projection", rehash_plan(plan, format_version=4.0,
            execution_profile=bad_profile, document_projection=None), (IDENTITY,), (PROFILE, PLAN), ()),
    )


def plan_cases(plan):
    for entry_name, entry, authority_errors in authority_cases(plan.eligibility_entry):
        for name, changed, before, after, late in plan_defects(rehash_plan(plan, eligibility_entry=entry)):
            expected = before + authority_errors + after
            yield entry_name + "/" + name, changed, expected or late
    for name, entry in (
        ("wrong_cardinality", rehash_entry(plan.eligibility_entry, exact_cardinality=4)),
        ("wrong_policy", rehash_entry(plan.eligibility_entry, composition_policy=REQUIRE_NO_OVERLAP.reference)),
        ("wrong_entry_type", None),
    ):
        changed = rehash_plan(plan, eligibility_entry=entry)
        yield name, changed, (ELIGIBILITY, PLAN)
    yield "wrong_plan_type", None, (PLAN,)


def inspect_document(root, document):
    inspection = inspect_field_relationships(root, tuple(
        FieldRelationshipInput(layer, index) for index, layer in enumerate(document.layers)
        if layer.visible is True))
    profiles = tuple(to_field_asset_profile(field) for field in inspection.fields)
    return inspection, profiles


def valid_inputs(root):
    for name, options in (
        ("standard", {}), ("rgb", {"rgb": True}), ("disjoint", {"disjoint": True}),
        ("reordered", {"order": (2, 0, 1)}), ("all_zero", {"strengths": (0.0, 0.0, 0.0)}),
        ("subnormal", {"strengths": (5e-324, 1.0, 0.0)}),
    ):
        document, inspection, profiles, *_ = blend_fixture(root, **options)
        yield name, document, inspection, profiles
    document = blend_fixture(root)[0]
    disabled = replace(document.layers[0], layer_id="disabled", visible=False, prompt_text="saved only")
    for name, layers in (
        ("disabled_before", (disabled,) + document.layers),
        ("disabled_between", document.layers[:1] + (disabled,) + document.layers[1:]),
        ("disabled_after", document.layers + (disabled,)),
    ):
        changed = replace(document, layers=layers)
        inspection, profiles = inspect_document(root, changed)
        yield name, changed, inspection, profiles


def translation_cases(document, inspection, profiles):
    args = (document, inspection.certificate, profiles)
    yield "valid", args, {}, TranslationStatus.TRANSLATED, ()
    for name, entry, errors in authority_cases(capability.EXACT_THREE_BLEND_ELIGIBILITY):
        yield name, args, {"eligibility_entry": entry}, (
            TranslationStatus.REJECTED if errors else TranslationStatus.TRANSLATED), errors
    for name, changed, code in (
        ("two_active", replace(document, layers=document.layers[:2]), "blend.cardinality.unsupported"),
        ("four_active", replace(document, layers=document.layers + (replace(
            document.layers[0], layer_id="fourth"),)), "blend.cardinality.unsupported"),
        ("wrong_policy", replace(document, composition_policy=REQUIRE_NO_OVERLAP.reference),
         "blend.policy.unsupported"),
    ):
        yield name, (changed, *args[1:]), {}, TranslationStatus.REJECTED, (code,)
    for name, certificate, fields in (
        ("certificate_fingerprint", replace(inspection.certificate, fingerprint="0" * 64), profiles),
        ("certificate_relationship", rehash_certificate(inspection.certificate,
            whole_set_evidence=replace(inspection.certificate.whole_set_evidence, mutual_exclusion=True)), profiles),
        ("profiles_reordered", inspection.certificate, tuple(reversed(profiles))),
        ("profiles_truncated", inspection.certificate, profiles[:-1]),
    ):
        yield name, (document, certificate, fields), {}, TranslationStatus.INVALID, (CERTIFICATE,)
    invalid_entry = rehash_entry(capability.EXACT_THREE_BLEND_ELIGIBILITY, relationship_constraint="invented")
    yield "authority_before_certificate", (document, None, ()), {"eligibility_entry": invalid_entry}, (
        TranslationStatus.REJECTED), (ELIGIBILITY,)
    yield "authority_profile_contract_topology", args, {
        "eligibility_entry": invalid_entry, "execution_profile": None,
        "contract_identifier": "invented", "topology_policy": None,
    }, TranslationStatus.REJECTED, (ELIGIBILITY, PROFILE, "blend.contract.invalid", "blend.topology.invalid")


def observable_result(result):
    """Complete findings plus governed successful artifact/selected authority."""
    plan = result.plan
    return (
        result.status, result.translated, result.errors, result.warnings, result.information,
        None if plan is None else plan.eligibility_entry,
        None if plan is None else tr.serialize_translation_plan_v4(plan),
        None if plan is None else plan.fingerprint,
    )


class BlendPlanDiagnosticCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data = blend_fixture(self.temporary.name)

    def test_exact_ordered_plan_diagnostics_including_compound_defects(self):
        for name, plan, expected in plan_cases(self.data[3]):
            with self.subTest(case=name):
                findings = tr.verify_translation_plan(plan)
                self.assertEqual(tuple(item.code for item in findings), expected)
                self.assertTrue(all(item.severity is FindingSeverity.ERROR for item in findings))

    def test_translation_status_diagnostics_and_selected_entry(self):
        for name, args, kwargs, status, errors in translation_cases(*self.data[:3]):
            with self.subTest(case=name):
                result = tr.translate_prediction_mixing_blend(*args, **kwargs)
                self.assertIs(result.status, status)
                self.assertEqual(tuple(item.code for item in result.errors), errors)
                if errors:
                    self.assertIsNone(result.plan)
                    self.assertEqual(result.warnings, ())
                else:
                    self.assertEqual(result.plan.eligibility_entry, capability.EXACT_THREE_BLEND_ELIGIBILITY)

    def test_valid_disabled_arrangements_and_strengths(self):
        for name, document, inspection, profiles in valid_inputs(self.temporary.name):
            with self.subTest(case=name):
                result = tr.translate_prediction_mixing_blend(document, inspection.certificate, profiles)
                self.assertTrue(result.translated, result.findings)
                self.assertEqual(tr.verify_translation_plan(result.plan), ())
                self.assertEqual(tuple(item.document_index for item in result.plan.regional_conditions),
                                 tuple(index for index, layer in enumerate(document.layers) if layer.visible is True))
                warnings = RETAINED_WARNING_CODES
                if name in ("all_zero", "subnormal"):
                    warnings = warnings[:-2] + ("capability.zero_strength_active",) + warnings[-2:]
                self.assertEqual(tuple(item.code for item in result.warnings), warnings)
                self.assertEqual(tr.plan_warning_codes(result.plan), warnings)
                self.assertEqual((result.plan.fingerprint, hashlib.sha256(
                    tr.serialize_translation_plan_v4(result.plan)).hexdigest()), RETAINED_IDENTITIES[name])
                self.assertEqual(result.plan.eligibility_entry.fingerprint,
                                 "aeefb8a4c0697056f42bcd7078236838df4ef15defe68f05309c993666bcda22")

    def test_failed_authority_never_reaches_projection_as_authority(self):
        plan = self.data[3]
        for name, entry, errors in authority_cases(plan.eligibility_entry):
            if not errors:
                continue
            with self.subTest(case=name), patch.object(
                tr, "evaluate_blend_eligibility", wraps=tr.evaluate_blend_eligibility,
            ) as evaluate:
                self.assertEqual(tuple(item.code for item in tr.verify_translation_plan(
                    rehash_plan(plan, eligibility_entry=entry))), errors)
                evaluate.assert_called_once()
                for call in evaluate.call_args_list:
                    propagated = call.args[1] if len(call.args) > 1 else capability.EXACT_THREE_BLEND_ELIGIBILITY
                    self.assertIs(propagated, capability.EXACT_THREE_BLEND_ELIGIBILITY)


class BlendPlanVerifiedAuthorityTests(unittest.TestCase):
    def test_verified_exact_four_uses_plan_authority_and_invalid_entries_stop_before_construction(self):
        # A single explicit test-only reviewed authority, not a production entry
        # or an allow-all verifier. The real committed-content verifier and real
        # evaluator remain in use; only their expected fixture data is scoped.
        entry = rehash_entry(capability.EXACT_THREE_BLEND_ELIGIBILITY,
                             identifier="test-only.blend.exact-4.v1", exact_cardinality=4)
        registered = capability.REGISTERED_BLEND_ELIGIBILITY_ENTRIES
        with tempfile.TemporaryDirectory() as root:
            document = blend_fixture(root)[0]
            document = replace(document, layers=document.layers + (replace(document.layers[0], layer_id="fourth"),))
            inspection, profiles = inspect_document(root, document)
            with patch.object(capability, "_REVIEWED_ENTRIES", (entry,)), patch.object(
                capability, "REGISTERED_BLEND_ELIGIBILITY_ENTRIES", (entry,),
            ):
                self.assertEqual(capability.verify_blend_eligibility(entry), ())
                # The retained exact-3 default cannot accidentally satisfy this
                # fixture: only the independently fixed exact-4 entry can pass.
                self.assertTrue(capability.evaluate_blend_eligibility(document))
                result = tr.translate_prediction_mixing_blend(
                    document, inspection.certificate, profiles, eligibility_entry=entry)
                self.assertTrue(result.translated, result.findings)
                self.assertIs(result.plan.eligibility_entry, entry)
                self.assertEqual(result.plan.active_layer_count, 4)
                self.assertEqual(len(result.plan.fold_schedule), 3)
                self.assertEqual(tr.verify_translation_plan(result.plan), ())
                for invalid in (
                    rehash_entry(entry, identifier="unknown.blend.exact-4"),
                    rehash_entry(entry, relationship_constraint="invented"),
                    replace(entry, fingerprint="0" * 64),
                ):
                    with self.subTest(entry=invalid.identifier), patch.object(
                        tr, "verify_translation_plan", side_effect=AssertionError("failed authority reached plan validation"),
                    ):
                        rejected = tr.translate_prediction_mixing_blend(
                            document, inspection.certificate, profiles, eligibility_entry=invalid)
                        self.assertIs(rejected.status, TranslationStatus.REJECTED)
                        self.assertIsNone(rejected.plan)
                        self.assertEqual(tuple(item.code for item in rejected.errors), (ELIGIBILITY,))
                        self.assertEqual(rejected.warnings, ())
            self.assertEqual(capability.REGISTERED_BLEND_ELIGIBILITY_ENTRIES,
                             registered)
            self.assertTrue(capability.verify_blend_eligibility(entry))


if __name__ == "__main__":
    unittest.main()
