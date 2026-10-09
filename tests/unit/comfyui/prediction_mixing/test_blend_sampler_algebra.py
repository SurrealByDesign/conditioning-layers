"""Independent rational emulation of the unchanged binary32 accumulator.

No Torch, ComfyUI, model, network, host or image generation is used here.
The reference rounds by searching IEEE-754 bit patterns, independently of the
production integer quotient/remainder rounding implementation.
"""
from __future__ import annotations

from fractions import Fraction
from functools import lru_cache
from itertools import permutations, product
import math
import random
import unittest

from conditioning_layers.comfyui.prediction_mixing.blend_preparation import normalize_sample_codes


UNIT_ROUNDOFF = Fraction(1, 2**24)
MIN_SUBNORMAL = Fraction(1, 2**149)
# Test-only bounds; no production consumer or runtime branch uses these.
COEFFICIENT_ERROR_BOUND = 8 * UNIT_ROUNDOFF + 8 * MIN_SUBNORMAL


@lru_cache(maxsize=65536)
def binary32_value(bits):
    exponent, mantissa = (bits >> 23) & 255, bits & 0x7FFFFF
    if exponent == 0:
        return Fraction(mantissa, 2**149)
    return Fraction(2**23 + mantissa) * Fraction(2) ** (exponent - 150)


def reference_round(value):
    """Correctly round a bounded rational to binary32 without a float cast."""
    value = Fraction(value)
    if value < 0:
        return -reference_round(-value)
    if value == 0:
        return value
    lo, hi = 0, 0x7F7FFFFF
    if value > binary32_value(hi):
        raise AssertionError("Test fixture exceeds the finite reference domain")
    while lo < hi:
        middle = (lo + hi + 1) // 2
        if binary32_value(middle) <= value:
            lo = middle
        else:
            hi = middle - 1
    lower = binary32_value(lo)
    if lower == value:
        return lower
    upper = binary32_value(lo + 1)
    below, above = value - lower, upper - value
    return lower if below < above or (below == above and lo % 2 == 0) else upper


def exact_weights(codes, strengths):
    products = tuple(Fraction(code) * Fraction(strength) for code, strength in zip(codes, strengths, strict=True))
    total = sum(products)
    return tuple(value / total for value in products) if total else (Fraction(0),) * 3


def accumulate(values, order, seed=Fraction(0)):
    result = seed
    for index in order:
        result = reference_round(result + values[index])
    return result


class BlendSamplerAlgebraTests(unittest.TestCase):
    def corpus(self):
        tiny = float.fromhex("0x0.0000000000001p-1022")
        strengths = (0.0, tiny, 1e-37, 2**-149, 2**-126, 2**-25, 0.1, 1.0)
        # Includes subnormals, all-zero, sole-positive and every mixed scale.
        for triple in product(strengths, repeat=3):
            yield (1, 10, 255), triple
        for codes in ((1, 1, 1), (1, 10, 1), (255, 255, 255), (0, 1, 0), (255, 1, 255)):
            for triple in ((1.0,) * 3, (1e-37,) * 3, (tiny,) * 3, (1.0, 0.1, 1.0)):
                yield codes, triple
        rng = random.Random(2603)
        for _ in range(160):
            yield tuple(rng.randrange(256) for _ in range(3)), tuple(
                math.ldexp(rng.random(), -rng.randrange(1074)) for _ in range(3)
            )

    def test_seed_neutralization_and_exact_coefficients_in_every_order(self):
        seed = reference_round(Fraction(1e-37))
        for codes, strengths in self.corpus():
            expected = exact_weights(codes, strengths)
            prepared = tuple(Fraction(value) for value in normalize_sample_codes(codes, strengths))
            self.assertEqual(prepared, tuple(reference_round(value) for value in expected))
            for order in permutations(range(3)):
                with self.subTest(codes=codes, strengths=strengths, order=order):
                    denominator = accumulate(prepared, order, seed)
                    if not any(expected):
                        self.assertEqual(prepared, (0, 0, 0))
                        self.assertEqual(denominator, seed)
                    else:
                        self.assertEqual(denominator, accumulate(prepared, order))
                        self.assertGreater(denominator, Fraction(1, 2))
                    for value, weight in zip(prepared, expected, strict=True):
                        coefficient = reference_round(value / denominator)
                        self.assertLessEqual(abs(coefficient - weight), COEFFICIENT_ERROR_BOUND)

    def test_canonical_ratios_and_tiny_sole_support(self):
        tiny = float.fromhex("0x0.0000000000001p-1022")
        for strength in (1.0, 1e-37, tiny):
            self.assertEqual(normalize_sample_codes((1, 0, 0), (strength,) * 3), (1.0, 0.0, 0.0))
            for codes in ((1, 1, 1), (1, 10, 1)):
                expected = exact_weights(codes, (strength,) * 3)
                self.assertEqual(tuple(map(Fraction, normalize_sample_codes(codes, (strength,) * 3))),
                                 tuple(map(reference_round, expected)))

    def test_signed_prediction_algebra_error_is_operation_bounded(self):
        # Bound scales with sum of absolute exact weighted predictions, so
        # cancellation does not spuriously claim relative output accuracy.
        predictions = ((1, -1, 1), (10, -3, 7), (0, 0, 0),
                       (Fraction(1, 2**120), 1, -1), (2**120, 0, 0))
        cases = (((1, 1, 1), (1e-37,) * 3), ((1, 10, 1), (1.0,) * 3),
                 ((1, 255, 1), (2**-1074, 1.0, 1e-37)),
                 ((1, 1, 0), (2**-150, 1.0, 0.0)), ((0, 0, 0), (1.0,) * 3))
        seed = reference_round(Fraction(1e-37))
        for codes, strengths in cases:
            weights = exact_weights(codes, strengths)
            prepared = tuple(map(Fraction, normalize_sample_codes(codes, strengths)))
            for prediction in predictions:
                exact = sum(w * p for w, p in zip(weights, prediction, strict=True))
                magnitude = sum(abs(w * p) for w, p in zip(weights, prediction, strict=True))
                # A subnormal preparation error is absolute and is multiplied
                # by the prediction; it cannot be bounded by output scale alone.
                prediction_magnitude = sum(map(abs, prediction))
                bound = (16 * UNIT_ROUNDOFF * magnitude
                         + 16 * MIN_SUBNORMAL * (prediction_magnitude + 1))
                terms = tuple(reference_round(w * p) for w, p in zip(prepared, prediction, strict=True))
                for order in permutations(range(3)):
                    denominator = accumulate(prepared, order, seed)
                    actual = reference_round(accumulate(terms, order) / denominator)
                    self.assertLessEqual(abs(actual - exact), bound)

    def test_reference_ties_and_subnormal_transition(self):
        for bits in (0, 1, 0x7FFFFE, 0x7FFFFF, 0x800000, 0x3EAAAAAA, 0x3EAAAAAB, 0x3F7FFFFF):
            midpoint = (binary32_value(bits) + binary32_value(bits + 1)) / 2
            self.assertEqual(reference_round(midpoint), binary32_value(bits if bits % 2 == 0 else bits + 1))


if __name__ == "__main__":
    unittest.main()
