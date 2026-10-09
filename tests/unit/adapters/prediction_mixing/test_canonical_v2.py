from __future__ import annotations

import math
import unittest

from conditioning_layers.adapters.prediction_mixing.v2 import (
    CanonicalizationError,
    build_ordered_left_fold_schedule,
    canonical_json_bytes,
    canonical_json_text,
)


class TranslationV2CanonicalizationTests(unittest.TestCase):
    def test_equivalent_numeric_spellings_have_identical_semantic_bytes(self) -> None:
        self.assertEqual(canonical_json_bytes(1), canonical_json_bytes(1.0))
        self.assertEqual(canonical_json_bytes(1.0), canonical_json_bytes(1e0))
        self.assertEqual(canonical_json_text(1.0), "1")

    def test_negative_zero_canonicalizes_to_zero(self) -> None:
        self.assertEqual(canonical_json_text(-0.0), "0")
        self.assertEqual(
            canonical_json_bytes({"strength": -0.0}),
            canonical_json_bytes({"strength": 0.0}),
        )

    def test_non_finite_values_are_rejected(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaises(CanonicalizationError):
                    canonical_json_bytes(value)

    def test_unsafe_integer_is_rejected(self) -> None:
        with self.assertRaises(CanonicalizationError):
            canonical_json_bytes(1 << 53)

    def test_unicode_is_value_exact_and_not_normalized(self) -> None:
        composed = "caf\u00e9"
        decomposed = "cafe\u0301"
        self.assertNotEqual(
            canonical_json_bytes(composed),
            canonical_json_bytes(decomposed),
        )
        self.assertIn(composed.encode("utf-8"), canonical_json_bytes(composed))

    def test_lone_surrogate_is_rejected(self) -> None:
        with self.assertRaises(CanonicalizationError):
            canonical_json_bytes("bad-\ud800-value")

    def test_object_keys_are_canonical_and_arrays_retain_order(self) -> None:
        self.assertEqual(canonical_json_text({"b": 1, "a": 2}), '{"a":2,"b":1}')
        self.assertEqual(canonical_json_text(["b", "a"]), '["b","a"]')
        self.assertNotEqual(
            canonical_json_bytes(["a", "b"]),
            canonical_json_bytes(["b", "a"]),
        )

    def test_canonical_bytes_have_no_bom_or_trailing_newline(self) -> None:
        value = canonical_json_bytes({"value": 1})
        self.assertFalse(value.startswith(b"\xef\xbb\xbf"))
        self.assertFalse(value.endswith(b"\n"))


class OrderedLeftFoldScheduleTests(unittest.TestCase):
    def test_zero_and_one_condition_have_no_fold_step(self) -> None:
        self.assertEqual(build_ordered_left_fold_schedule(0), ())
        self.assertEqual(build_ordered_left_fold_schedule(1), ())

    def test_arbitrary_count_uses_deterministic_iterative_left_fold(self) -> None:
        steps = build_ordered_left_fold_schedule(4)
        self.assertEqual(
            tuple(
                (item.step_ordinal, item.left_operand, item.right_condition, item.result)
                for item in steps
            ),
            (
                (0, "condition:0", "condition:1", "fold:0"),
                (1, "fold:0", "condition:2", "fold:1"),
                (2, "fold:1", "condition:3", "fold:2"),
            ),
        )

    def test_boolean_and_negative_counts_are_rejected(self) -> None:
        for value in (True, -1):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    build_ordered_left_fold_schedule(value)


if __name__ == "__main__":
    unittest.main()
