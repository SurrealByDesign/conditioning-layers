"""Node System Phase 1 FIXED/BLENDED composition over exact 8-bit codes; developer lane.

The retained per-sample normalization is the reference throughout: all-BLENDED
input must reach it unchanged, and FIXED ownership may only zero competing
codes before it. Blended remainders are checked against the retained function
called on the BLENDED subset alone, a different call path from production.
"""

from fractions import Fraction
from pathlib import Path
import random
import unittest

from conditioning_layers.assets.models import DEFAULT_INSPECTION_LIMITS
from conditioning_layers.assets.png_inspector import inspect_png_bytes
from conditioning_layers.comfyui.prediction_mixing.blend_preparation import normalize_sample_codes_bits
from conditioning_layers.comfyui.prediction_mixing.layer_nodes import (
    LayerCompositionError, LayerMode, compose_field_codes, fixed_overlaps,
)


ROOT = Path(__file__).resolve().parents[4]
FIELDS = ROOT / "node-workflows/phase1/fields"
B, F = LayerMode.BLENDED, LayerMode.FIXED
ONE, HALF = 0x3F800000, 0x3F000000


def decoded(path):
    return inspect_png_bytes(path, layer_id="field", relative_reference=path.name,
                             limits=DEFAULT_INSPECTION_LIMITS).values


def fixture_planes(prefix, names):
    return tuple(decoded(FIELDS / f"{prefix}{name}.png") for name in names)


VASE3 = ("cl-phase1-vase3-", "abc")
VASE9 = ("cl-phase1-vase9-", tuple(f"cell-{index}" for index in range(1, 10)))
THIRDS = tuple(decoded(ROOT / f"influence-field-library/v1/three-layer/vertical-thirds/field-{letter}.png")
               for letter in "abc")


class PreparedAssertions(unittest.TestCase):
    def assertPrepared(self, actual, expected):
        """Exact comparison that reports the first difference instead of diffing 16,384-sample tuples."""
        if actual != expected:
            shape = (len(actual), len(actual[0]) if actual else 0, len(expected), len(expected[0]) if expected else 0)
            first = next(((layer, index) for layer, (left, right) in enumerate(zip(actual, expected))
                          for index, (a, b) in enumerate(zip(left, right)) if a != b), None)
            self.fail(f"prepared weights differ: shapes {shape}, first difference (layer, sample) {first}")


def retained(planes, strengths):
    """The per-sample loop both retained preparation nodes run."""
    prepared = [[] for _ in planes]
    for codes in zip(*planes):
        for layer, weight in zip(prepared, normalize_sample_codes_bits(codes, tuple(strengths))):
            layer.append(weight)
    return tuple(map(tuple, prepared))


def subset_reference(planes, strengths, modes):
    """Independent mixed-mode reference: owner weight, else Blend over the BLENDED subset only."""
    blended = tuple(index for index, mode in enumerate(modes) if mode is B)
    prepared = [[] for _ in planes]
    for codes in zip(*planes):
        owners = [index for index, mode in enumerate(modes) if mode is F and codes[index]]
        weights = [0] * len(planes)
        if owners:
            (owner,) = owners
            weights[owner] = ONE if strengths[owner] > 0 else 0
        elif blended:
            subset = normalize_sample_codes_bits(tuple(codes[index] for index in blended),
                                                 tuple(strengths[index] for index in blended))
            for index, weight in zip(blended, subset):
                weights[index] = weight
        for layer, weight in zip(prepared, weights):
            layer.append(weight)
    return tuple(map(tuple, prepared))


class AllBlendedTests(PreparedAssertions):
    def test_fixture_fields_reach_the_retained_normalization_unchanged(self):
        for (prefix, names), strengths in (
                (VASE3, (1.0, 1.0, 1.0)), (VASE3, (1.0, 0.1, 5e-324)),
                (VASE9, (1.0,) * 9), (VASE9, (0.35, 1.0, 0.0, 0.5, 1.0, 2**-30, 1.0, 0.75, 0.1))):
            planes = fixture_planes(prefix, names)
            with self.subTest(prefix=prefix, strengths=strengths):
                self.assertPrepared(compose_field_codes(planes, strengths, (B,) * len(planes)),
                                    retained(planes, strengths))

    def test_any_positive_count_has_no_maximum(self):
        rng = random.Random(20260927)
        choices = (0.0, 1e-37, 0.1, 0.5, 1.0)
        for count in (1, 2, 4, 12, 17, 40):
            planes = tuple(bytes(rng.choice((0, 0, rng.randrange(1, 256))) for _ in range(97)) for _ in range(count))
            planes = tuple(plane if any(plane) else b"\x01" + plane[1:] for plane in planes)
            strengths = tuple(rng.choice(choices) for _ in range(count))
            with self.subTest(count=count):
                self.assertPrepared(compose_field_codes(planes, strengths, (B,) * count), retained(planes, strengths))

    def test_lone_layer_owns_its_positive_support(self):
        plane = (0, 1, 128, 255, 0)
        self.assertEqual(compose_field_codes((plane,), (0.25,), (B,)), ((0, ONE, ONE, ONE, 0),))
        self.assertEqual(compose_field_codes((plane,), (0.0,), (B,)), ((0,) * 5,))

    def test_repeated_fields_and_prompts_stay_two_layers(self):
        plane = (0, 7, 255)
        prepared = compose_field_codes((plane, plane), (1.0, 1.0), (B, B))
        self.assertEqual(prepared, ((0, HALF, HALF), (0, HALF, HALF)))

    def test_zero_support_is_explicit_and_never_filled(self):
        planes = ((0, 9, 0), (0, 0, 4))
        self.assertEqual(compose_field_codes(planes, (1.0, 1.0), (B, B)), ((0, ONE, 0), (0, 0, ONE)))
        self.assertEqual(compose_field_codes(planes, (0.0, 0.0), (B, B)), ((0, 0, 0), (0, 0, 0)))


class FixedTests(PreparedAssertions):
    def test_disjoint_fixed_layers_match_retained_no_overlap_weights(self):
        self.assertEqual(fixed_overlaps(THIRDS, (F, F, F)), {})
        for strengths in ((1.0, 1.0, 1.0), (1.0, 0.25, 0.0)):
            fixed = compose_field_codes(THIRDS, strengths, (F, F, F))
            self.assertPrepared(fixed, compose_field_codes(THIRDS, strengths, (B, B, B)))
            self.assertPrepared(fixed, retained(THIRDS, strengths))
            # Retained No Overlap mixes natively by m*S / sum(m*S): exact 1 or 0 here.
            for index, codes in enumerate(zip(*THIRDS)):
                products = [Fraction(code) * Fraction(strength) for code, strength in zip(codes, strengths)]
                total = sum(products)
                expected = [ONE if total and value / total == 1 else 0 for value in products]
                self.assertTrue(total == 0 or sorted(value / total for value in products) == [0, 0, 1])
                self.assertEqual([layer[index] for layer in fixed], expected)

    def test_fixed_owner_is_full_weight_at_every_positive_soft_sample(self):
        soft, blended = (0, 1, 64, 255), (200, 200, 200, 200)
        prepared = compose_field_codes((soft, blended), (0.01, 1.0), (F, B))
        self.assertEqual(prepared, ((0, ONE, ONE, ONE), (ONE, 0, 0, 0)))

    def test_fixed_zero_strength_owns_an_empty_area(self):
        prepared = compose_field_codes(((0, 5, 5), (9, 9, 9)), (0.0, 1.0), (F, B))
        self.assertEqual(prepared, ((0, 0, 0), (ONE, 0, 0)))

    def test_overlapping_fixed_fields_fail_regardless_of_strength_or_order(self):
        first, second, third = (0, 3, 3, 0), (0, 0, 1, 1), (1, 0, 0, 0)
        for planes, strengths in (((first, second, third), (1.0, 1.0, 1.0)),
                                  ((first, second, third), (0.0, 1.0, 0.0)),
                                  ((second, first, third), (1.0, 1.0, 1.0))):
            with self.subTest(strengths=strengths), self.assertRaises(LayerCompositionError) as raised:
                compose_field_codes(planes, strengths, (F, F, F), labels=("north", "south", "west"))
            self.assertIn("north and south share 1 sample", str(raised.exception))
            self.assertIn("no priority", str(raised.exception))
        self.assertEqual(fixed_overlaps((first, second, first), (F, F, F)), {(0, 1): 1, (0, 2): 2, (1, 2): 1})
        self.assertEqual(fixed_overlaps((first, first), (F, B)), {})


class MixedTests(PreparedAssertions):
    def check(self, planes, strengths, modes):
        prepared = compose_field_codes(planes, strengths, modes)
        self.assertPrepared(prepared, subset_reference(planes, strengths, modes))
        return prepared

    def test_fixed_first_and_middle_with_blended_remainder(self):
        planes = fixture_planes(*VASE3)
        for modes in ((F, B, B), (B, F, B), (B, B, F)):
            for strengths in ((1.0, 1.0, 1.0), (0.5, 1.0, 0.1)):
                with self.subTest(modes=modes, strengths=strengths):
                    prepared = self.check(planes, strengths, modes)
                    owner = modes.index(F)
                    for index, codes in enumerate(zip(*planes)):
                        if codes[owner]:
                            self.assertEqual([layer[index] for layer in prepared],
                                             [ONE if layer == owner else 0 for layer in range(3)])

    def test_documented_five_layer_example(self):
        # A and D are FIXED and disjoint; B, C and E are BLENDED and overlap everything.
        a = tuple(255 if x < 3 else 0 for x in range(12))
        d = tuple(128 if x > 8 else 0 for x in range(12))
        b = tuple(10 * x + 1 for x in range(12))
        c = tuple(255 - 10 * x for x in range(12))
        e = tuple(50 if x % 2 else 0 for x in range(12))
        planes, modes = (a, b, c, d, e), (F, B, B, F, B)
        prepared = self.check(planes, (1.0, 0.5, 1.0, 1.0, 0.25), modes)
        for x in range(12):
            column = [layer[x] for layer in prepared]
            if x < 3:
                self.assertEqual(column, [ONE, 0, 0, 0, 0])
            elif x > 8:
                self.assertEqual(column, [0, 0, 0, ONE, 0])
            else:
                self.assertEqual((column[0], column[3]), (0, 0))
                self.assertGreater(column[1] + column[2], 0)

    def test_multiple_fixed_with_blended_remainder_on_nine_vase_fields(self):
        planes = fixture_planes(*VASE9)
        # Corner cells are pairwise disjoint in the retained unified-vase layout.
        modes = tuple(F if index in (0, 2, 6, 8) else B for index in range(9))
        self.assertEqual(fixed_overlaps(planes, modes), {})
        self.check(planes, (1.0,) * 9, modes)

    def test_permuting_layers_permutes_prepared_weights_exactly(self):
        planes = fixture_planes(*VASE3) + ((0,) * 16000 + (255,) * 384,)
        strengths, modes = (1.0, 0.3, 0.7, 1.0), (B, B, B, F)
        prepared = compose_field_codes(planes, strengths, modes)
        for order in ((3, 2, 1, 0), (1, 3, 0, 2)):
            with self.subTest(order=order):
                self.assertPrepared(
                    compose_field_codes(tuple(planes[i] for i in order), tuple(strengths[i] for i in order),
                                        tuple(modes[i] for i in order)),
                    tuple(prepared[i] for i in order))


class MalformedTests(unittest.TestCase):
    def test_malformed_inputs_fail_closed(self):
        good = ((0, 1), (2, 0))
        cases = (
            ((), (), ()),
            (good, (1.0,), (B, B)),
            (good, (1.0, 1.0), (B,)),
            (((0, 1), (2,)), (1.0, 1.0), (B, B)),
            (((), ()), (1.0, 1.0), (B, B)),
            (((0, 256), (2, 0)), (1.0, 1.0), (B, B)),
            (((0, -1), (2, 0)), (1.0, 1.0), (B, B)),
            (((0, 1.0), (2, 0)), (1.0, 1.0), (B, B)),
            (((0, True), (2, 0)), (1.0, 1.0), (B, B)),
            (good, (float("nan"), 1.0), (B, B)),
            (good, (1.5, 1.0), (B, B)),
            (good, (-0.1, 1.0), (B, B)),
            (good, (True, 1.0), (B, B)),
            (good, ("1", 1.0), (B, B)),
            (good, (1.0, 1.0), ("BLENDED", B)),
            (good, (1.0, 1.0), (None, B)),
        )
        for planes, strengths, modes in cases:
            with self.subTest(planes=planes, strengths=strengths, modes=modes):
                with self.assertRaises(LayerCompositionError):
                    compose_field_codes(planes, strengths, modes)
        with self.assertRaises(LayerCompositionError):
            compose_field_codes(good, (1.0, 1.0), (B, B), labels=("one",))

    def test_enabled_empty_field_must_be_disabled_instead(self):
        with self.assertRaises(LayerCompositionError) as raised:
            compose_field_codes(((0, 0), (1, 2)), (1.0, 1.0), (B, B), labels=("empty", "full"))
        self.assertIn("Layer empty", str(raised.exception))
        self.assertIn("disable the layer", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
