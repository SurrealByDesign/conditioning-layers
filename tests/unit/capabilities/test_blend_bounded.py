"""ADR-0028 committed exact authority and offline selection; developer lane."""

from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from conditioning_layers.capabilities import blend
from conditioning_layers.capabilities._bounded_blend import select_bounded_blend_eligibility
from conditioning_layers.domain import CURRENT_PROTOTYPE_VERSION, REQUIRE_NO_OVERLAP

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tooling"))
from bounded_blend_fixture import bounded_document


def rehash(entry, **changes):
    changed = replace(entry, **changes)
    return replace(changed, fingerprint=blend.fingerprint_blend_eligibility(changed))


class BoundedBlendAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.entries = blend.REGISTERED_BLEND_ELIGIBILITY_ENTRIES

    def document(self, count):
        return bounded_document(self.temporary.name, count)

    def assertInvalid(self, entry):
        self.assertEqual(tuple(item.code for item in blend.verify_blend_eligibility(entry)),
                         ("blend.eligibility.invalid",))

    def test_exact_complete_immutable_entries_preserve_all_other_semantics(self):
        self.assertIs(type(self.entries), tuple)
        self.assertEqual(tuple(entry.exact_cardinality for entry in self.entries), (3, 4, 5, 6, 7, 8, 9))
        self.assertEqual(len({entry.identifier for entry in self.entries}), 7)
        self.assertEqual(len({entry.fingerprint for entry in self.entries}), 7)
        for entry in self.entries:
            with self.subTest(count=entry.exact_cardinality):
                self.assertIs(type(entry.exact_cardinality), int)
                self.assertEqual(entry.identifier,
                    f"prediction-mixing.multi-layer.exact-{entry.exact_cardinality}.normalized-blend.v1")
                self.assertEqual(blend.verify_blend_eligibility(entry), ())
                self.assertEqual(blend.verify_blend_eligibility(replace(entry)), ())
                for field in fields(entry):
                    if field.name not in ("identifier", "exact_cardinality", "fingerprint"):
                        self.assertEqual(getattr(entry, field.name), getattr(blend.EXACT_THREE_BLEND_ELIGIBILITY, field.name))
                with self.assertRaises(FrozenInstanceError):
                    entry.exact_cardinality = 10
        self.assertEqual(blend.EXACT_THREE_BLEND_ELIGIBILITY.fingerprint,
                         "aeefb8a4c0697056f42bcd7078236838df4ef15defe68f05309c993666bcda22")

    def test_exact_selection_is_deterministic_and_ignores_registration_order(self):
        for entry in self.entries[1:]:
            document = self.document(entry.exact_cardinality)
            with self.subTest(count=entry.exact_cardinality):
                self.assertIs(select_bounded_blend_eligibility(document), entry)
                self.assertIs(select_bounded_blend_eligibility(document), entry)
                with patch.object(blend, "REGISTERED_BLEND_ELIGIBILITY_ENTRIES", tuple(reversed(self.entries))):
                    self.assertIs(select_bounded_blend_eligibility(document), entry)
                self.assertEqual(blend.evaluate_blend_eligibility(document, entry), ())

    def test_unsupported_counts_and_wrong_document_fail_without_fallback(self):
        for count in (0, 1, 2, 3, 10):
            with self.subTest(count=count), self.assertRaises(ValueError):
                select_bounded_blend_eligibility(self.document(count))
        with self.assertRaises(ValueError):
            select_bounded_blend_eligibility(None)

    def test_each_missing_authority_including_every_interior_count_fails_closed(self):
        for entry in self.entries[1:]:
            with self.subTest(count=entry.exact_cardinality), patch.object(
                blend, "REGISTERED_BLEND_ELIGIBILITY_ENTRIES", tuple(item for item in self.entries if item != entry),
            ):
                self.assertInvalid(entry)
                with self.assertRaises(ValueError):
                    select_bounded_blend_eligibility(self.document(entry.exact_cardinality))
                self.assertEqual(blend.verify_blend_eligibility(blend.EXACT_THREE_BLEND_ELIGIBILITY), ())

    def test_unknown_ids_cannot_self_register_or_shadow_reviewed_content(self):
        for entry in self.entries[1:]:
            unknown = rehash(entry, identifier=f"unknown.exact-{entry.exact_cardinality}")
            replaced = tuple(unknown if item == entry else item for item in self.entries)
            with self.subTest(count=entry.exact_cardinality), patch.object(blend, "REGISTERED_BLEND_ELIGIBILITY_ENTRIES", replaced):
                self.assertInvalid(unknown)
                self.assertInvalid(entry)
                with self.assertRaises(ValueError):
                    select_bounded_blend_eligibility(self.document(entry.exact_cardinality))

    def test_all_forged_semantic_fields_fail_even_with_matching_registration(self):
        entry = blend.EXACT_FOUR_BLEND_ELIGIBILITY
        for field in fields(entry):
            value = getattr(entry, field.name)
            if field.name == "fingerprint":
                forged = replace(entry, fingerprint="0" * 64)
            else:
                if type(value) is str:
                    changed = value + ".forged"
                elif type(value) is bool:
                    changed = not value
                elif type(value) in (int, float):
                    changed = value + 1
                elif type(value) is tuple:
                    changed = value + ("forged",)
                else:
                    changed = REQUIRE_NO_OVERLAP.reference
                forged = rehash(entry, **{field.name: changed})
            with self.subTest(field=field.name):
                self.assertInvalid(forged)
                with patch.object(blend, "REGISTERED_BLEND_ELIGIBILITY_ENTRIES", (forged,)):
                    self.assertInvalid(forged)
                    self.assertInvalid(entry)
                    with self.assertRaises(ValueError):
                        select_bounded_blend_eligibility(self.document(4))

    def test_duplicate_ids_and_shadowed_contract_counts_are_rejected(self):
        for entry in self.entries:
            for extra in (entry, rehash(entry, identifier="shadow.exact-entry"),
                          rehash(entry, identifier="shadow.wrong-policy", composition_policy=REQUIRE_NO_OVERLAP.reference)):
                with self.subTest(count=entry.exact_cardinality, extra=extra.identifier), patch.object(
                    blend, "REGISTERED_BLEND_ELIGIBILITY_ENTRIES", self.entries + (extra,),
                ):
                    self.assertInvalid(entry)
                    self.assertInvalid(extra)
                    if entry.exact_cardinality != 3:
                        with self.assertRaises(ValueError):
                            select_bounded_blend_eligibility(self.document(entry.exact_cardinality))

    def test_wrong_types_ranges_and_nested_numeric_aliases_cannot_be_authority(self):
        entry = blend.EXACT_FOUR_BLEND_ELIGIBILITY
        class Text(str):
            pass
        malformed = (None, {}, replace(entry, composition_policy={}),
                     rehash(entry, exact_cardinality=4.0), rehash(entry, exact_cardinality=True),
                     rehash(entry, exact_cardinality=(4, 9)), rehash(entry, exact_cardinality="4..9"),
                     rehash(entry, identifier="*"), rehash(entry, field_minimum=0),
                     rehash(entry, field_encodings=list(entry.field_encodings)),
                     rehash(entry, identifier=Text(entry.identifier)),
                     rehash(entry, composition_policy=replace(entry.composition_policy, policy_version=1.0)),
                     rehash(entry, composition_policy=replace(entry.composition_policy, policy_version=True)))
        for value in malformed:
            with self.subTest(value=value):
                self.assertInvalid(value)

    def test_valid_entry_wrong_count_policy_and_legacy_format_are_rejected(self):
        for entry in self.entries[1:]:
            document = self.document(entry.exact_cardinality)
            with self.subTest(count=entry.exact_cardinality):
                self.assertEqual(tuple(f.code for f in blend.evaluate_blend_eligibility(
                    replace(document, layers=document.layers[:-1]), entry)), ("blend.cardinality.unsupported",))
                wrong_policy = replace(document, composition_policy=REQUIRE_NO_OVERLAP.reference)
                legacy = replace(document, version=CURRENT_PROTOTYPE_VERSION, composition_policy=None)
                for changed in (wrong_policy, legacy):
                    self.assertEqual(tuple(f.code for f in blend.evaluate_blend_eligibility(changed, entry)),
                                     ("blend.policy.unsupported",))
                    with self.assertRaises(ValueError):
                        select_bounded_blend_eligibility(changed)


if __name__ == "__main__":
    unittest.main()
