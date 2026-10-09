"""Pure Noise v1 contract and independently evaluated Fraction oracle."""

from contextlib import ExitStack
from fractions import Fraction
from functools import lru_cache
import hashlib
import math
from pathlib import Path
import random
import struct
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui import procedural_field_sources as fields


DEFAULTS = dict(seed=0, frequency=4.0, octaves=4, persistence=0.5, offset_x=0.0, offset_y=0.0)
# SHA-256 of 16384 row-major recovered code bytes (no MASK or PNG headers).
GOLDENS = (
    ((0, 4.0, 1, 0.5, 0.0, 0.0), "8bbe0dda26be6a0632feb0ef846a80635d2cc5435da11fe207055ca8e00bad16"),
    ((0, 4.0, 4, 0.5, 0.0, 0.0), "92edb7adb228076fa8d2510c34a88da951a4a51bd39ffcaf822d81b156524474"),
    ((4294967295, 8.0, 6, 1.0, 0.0, 0.0), "704a060866103429f0c351f0f54746f94a9babaaa9c838498931ce1c47c24bdb"),
    ((1, 4.5, 4, 0.25, 127.0, -17.0), "75d19a44649b6918eeabffd7e084e07c88d68a5483340d084a409e1429167372"),
)


def reference_sampler(seed, frequency, octaves, persistence, offset_x, offset_y):
    """Fraction lerps at arbitrary field-cell coordinates, no production helpers."""
    count = math.floor(Fraction(frequency) + Fraction(1, 2))
    amplitudes = [Fraction(persistence)**o for o in range(octaves)]

    @lru_cache(None)
    def value(octave, x, y):
        payload = "conditioning-layers.noise-field.v1:%d:%d:%d:%d" % (seed, octave, x, y)
        word, = struct.unpack(">Q", hashlib.sha256(payload.encode("ascii")).digest()[:8])
        return Fraction(word, 18446744073709551615)

    def sample(x, y):
        total = Fraction(0)
        for octave, amplitude in enumerate(amplitudes):
            if not amplitude:
                continue
            period = count * 2**octave
            u = (Fraction(x) - Fraction(offset_x)) * period / 128
            v = (Fraction(y) - Fraction(offset_y)) * period / 128
            i, j = math.floor(u), math.floor(v)
            a, b = u - i, v - j
            a, b = 3*a**2 - 2*a**3, 3*b**2 - 2*b**3
            corners = [value(octave, ix % period, iy % period)
                       for iy in (j, j+1) for ix in (i, i+1)]
            upper = corners[0] + (corners[1] - corners[0]) * a
            lower = corners[2] + (corners[3] - corners[2]) * a
            total += amplitude * (upper + (lower - upper) * b)
        return total / sum(amplitudes)
    return sample


def reference_codes(*args):
    sample = reference_sampler(*args)
    return tuple(math.floor(255 * sample(Fraction(2*x+1, 2), Fraction(2*y+1, 2)) + Fraction(1, 2))
                 for y in range(128) for x in range(128))


class NoiseFieldCodesTests(unittest.TestCase):
    def test_surface_and_numeric_widgets(self):
        node = fields.ConditioningLayersNoiseField
        self.assertEqual(node.__name__, "ConditioningLayersNoiseField")
        self.assertEqual(fields.initialize_procedural_field_node_registration()[1][node.__name__], "Noise Field")
        self.assertEqual(node.RETURN_TYPES, ("MASK",))
        self.assertEqual(node.RETURN_NAMES, ("mask",))
        self.assertEqual(node.FUNCTION, "generate")
        self.assertEqual(node.CATEGORY, "conditioning/conditioning_layers/fields")
        declaration = node.INPUT_TYPES()
        self.assertEqual(tuple(declaration), ("required",))
        inputs = declaration["required"]
        self.assertEqual(tuple(inputs), tuple(DEFAULTS))
        limits = (("INT", 0, 4294967295, 1), ("FLOAT", .5, 32., .5),
                  ("INT", 1, 6, 1), ("FLOAT", 0., 1., .05),
                  ("FLOAT", -128., 128., 1.), ("FLOAT", -128., 128., 1.))
        for (name, default), (kind, low, high, step) in zip(DEFAULTS.items(), limits):
            self.assertEqual(inputs[name][0], kind)
            self.assertEqual([inputs[name][1][key] for key in ("default", "min", "max", "step", "display")],
                             [default, low, high, step, "number"])
            self.assertTrue(inputs[name][1]["tooltip"])
        self.assertIs(inputs["seed"][1]["control_after_generate"], False)
        inputs["frequency"][1]["min"] = 123
        self.assertEqual(node.INPUT_TYPES()["required"]["frequency"][1]["min"], .5)

    def test_hash_vectors_and_first_unsigned_big_endian_word(self):
        self.assertEqual(fields.NOISE_FIELD_ALGORITHM, "conditioning-layers.noise-field.v1")
        for seed, expected in ((0, "b95c3a74693e30e20b0e8fad4a451c1ed1034583550e883f5bc6d8759da5fe53"),
                               (1, "6811a7e9d43ded26e5c46d0991472810bb0c63470e0e149f63c972bc438c763f"),
                               (4294967295, "842cde99107815e3175eb87a23a46281e591b43b03a8a1b430b6840d502b08c7")):
            payload = ("conditioning-layers.noise-field.v1:%d:0:0:0" % seed).encode("ascii")
            self.assertEqual(hashlib.sha256(payload).hexdigest(), expected)
            self.assertEqual(fields._noise_lattice_word(seed, 0, 0, 0), int(expected[:16], 16))
        for seed in (0, 1, 4294967295):
            for o, x, y in ((0, 0, 0), (3, 7, 19), (5, 1023, 1023)):
                message = "conditioning-layers.noise-field.v1:%d:%d:%d:%d" % (seed, o, x, y)
                expected = struct.unpack(">Q", hashlib.sha256(message.encode("ascii")).digest()[:8])[0]
                self.assertEqual(fields._noise_lattice_word(seed, o, x, y), expected)
        for word in (0, 2**63 + 17, 2**64-1):
            with patch.object(fields.hashlib, "sha256") as digest:
                digest.return_value.digest.return_value = struct.pack(">Q", word) + b"\xff" * 24
                self.assertEqual(fields._noise_lattice_word(1, 2, 3, 4), word)
                digest.assert_called_once_with(b"conditioning-layers.noise-field.v1:1:2:3:4")

    def test_goldens_and_full_canvas_independent_oracle(self):
        for args, expected in GOLDENS:
            with self.subTest(args=args):
                actual = fields.noise_field_codes(*args)
                reference = reference_codes(*args)
                self.assertEqual(actual, reference)
                self.assertEqual(hashlib.sha256(bytes(reference)).hexdigest(), expected)

    def test_frequency_half_up_contract_and_low_lattice(self):
        for frequency, effective in ((.5, 1), (1., 1), (1.499999999999, 1), (1.5, 2),
                                     (4., 4), (4.49, 4), (4.5, 5), (31.5, 32), (32., 32)):
            actual = fields.noise_field_codes(**{**DEFAULTS, "frequency": frequency})
            self.assertEqual(actual, fields.noise_field_codes(**{**DEFAULTS, "frequency": effective}))
        low = fields.noise_field_codes(0, .5, 1, .5, 0, 0)
        self.assertEqual(len(set(low)), 1)
        self.assertEqual(low, reference_codes(0, .5, 1, .5, 0, 0))

    def test_frequency_octaves_persistence_and_grayscale_matrix(self):
        # All specified representative frequencies, octave counts and amplitudes.
        for frequency in (.5, 4., 32.):
            for octaves in (1, 4, 6):
                for persistence in (0., .25, .5, 1.):
                    args = (1, frequency, octaves, persistence, 0, 0)
                    with self.subTest(args=args):
                        actual = fields.noise_field_codes(*args)
                        self.assertEqual(len(actual), 16384)
                        self.assertTrue(all(type(c) is int and 0 <= c <= 255 for c in actual))
                        self.assertTrue(any(0 < c < 255 for c in actual))
                        sample = reference_sampler(*args)
                        for x, y in ((0, 0), (127, 127), (63, 31), (17, 91)):
                            self.assertEqual(actual[y*128+x], math.floor(
                                sample(Fraction(2*x+1, 2), Fraction(2*y+1, 2))*255 + Fraction(1, 2)))
        default = fields.noise_field_codes(**DEFAULTS)
        self.assertGreater(len(set(default)), 64)
        # A coherent low octave is smooth locally, unlike independent pixels.
        low = fields.noise_field_codes(0, 4., 1, .5, 0, 0)
        self.assertLess(max(abs(low[y*128+x] - low[y*128+(x+1)%128])
                            for y in range(128) for x in range(128)), 16)

    def test_persistence_zero_equals_first_octave_only(self):
        for seed in (0, 1, 4294967295):
            expected = fields.noise_field_codes(seed, 8, 1, .5, 7, -9)
            for octaves in (1, 4, 6):
                self.assertEqual(fields.noise_field_codes(seed, 8, octaves, 0, 7, -9), expected)

    def test_analytic_normalization_and_exact_half_up(self):
        # Constant synthetic lattice values must not be stretched by image range.
        for word, code in ((0, 0), ((2**64-1)//3, 85), (2**64-1, 255)):
            with patch.object(fields, "_noise_lattice_word", return_value=word):
                actual = fields.noise_field_codes(0, 4, 4, .5, 0, 0)
                self.assertEqual(set(actual), {code})
        # Equal amplitudes at 0 and 1 give exactly 127.5, which rounds to 128.
        def words(seed, octave, x, y):
            return 0 if octave == 0 else 2**64-1
        with patch.object(fields, "_noise_lattice_word", side_effect=words):
            self.assertEqual(set(fields.noise_field_codes(0, 4, 2, 1, 0, 0)), {128})
            self.assertEqual(set(fields.noise_field_codes(0, 4, 2, .25, 0, 0)), {51})
        actual = fields.noise_field_codes(**DEFAULTS)
        self.assertGreater(min(actual), 0)
        self.assertLess(max(actual), 255)

    def test_offsets_are_exact_positive_and_negative_spatial_rolls(self):
        base = fields.noise_field_codes(**DEFAULTS)
        for dx, dy in ((1, 0), (0, 1), (17, 29), (-7, -11), (127, -128), (128, 128), (-128, -128)):
            with self.subTest(offset=(dx, dy)):
                actual = fields.noise_field_codes(**{**DEFAULTS, "offset_x": dx, "offset_y": dy})
                self.assertEqual(actual, tuple(base[((y-dy)%128)*128+(x-dx)%128]
                                              for y in range(128) for x in range(128)))

    def test_fractional_offsets_wrap_and_match_oracle(self):
        args = (1, 4.5, 4, .3, .25, -17.5)
        actual = fields.noise_field_codes(*args)
        self.assertEqual(actual, fields.noise_field_codes(1, 4.5, 4, .3, -127.75, 110.5))
        sample = reference_sampler(*args)
        for x, y in ((0, 0), (127, 0), (0, 127), (127, 127), (63, 31)):
            self.assertEqual(actual[y*128+x], math.floor(
                sample(Fraction(2*x+1, 2), Fraction(2*y+1, 2))*255 + Fraction(1, 2)))

    def test_periodic_boundary_values_and_smoothstep_continuity(self):
        # Boundary coordinates coincide, but first/last pixel centers need not.
        sample = reference_sampler(1, 4.5, 4, .5, 0, 0)
        for t in (0, Fraction(1, 2), 63, 128):
            self.assertEqual(sample(0, t), sample(128, t))
            self.assertEqual(sample(t, 0), sample(t, 128))
        for lattice in (1, 5, 40, 1024):
            for offset in (Fraction(1, 2), Fraction(-255, 2)):
                # At cell 0, offset .5 samples exactly the boundary; translating
                # the sampling phase by a full period yields identical tables.
                first, d = fields._noise_axis(lattice, (offset.numerator, offset.denominator))
                shifted = offset + 128
                self.assertEqual((first, d), fields._noise_axis(lattice, (shifted.numerator, shifted.denominator)))
                self.assertEqual(first[0], (0, 1 % lattice, 0))
        epsilon = Fraction(1, 2**20)
        for t in (Fraction(1, 2), 31):
            self.assertLess(abs(sample(-epsilon, t) - sample(epsilon, t)), Fraction(1, 10**8))

    def test_each_required_corner_hashed_once_per_octave_and_no_global_cache(self):
        original = fields._noise_lattice_word
        for frequency in (4., 32.):
            with patch.object(fields, "_noise_lattice_word", wraps=original) as word:
                fields.noise_field_codes(0, frequency, 6, .5, 0, 0)
                calls = [call.args for call in word.call_args_list]
                self.assertEqual(len(calls), len(set(calls)))
                for o in range(6):
                    period = int(frequency) * 2**o
                    octave_calls = [args for args in calls if args[1] == o]
                    self.assertTrue(octave_calls)
                    self.assertLessEqual(len(octave_calls), min(period, 256)**2)
                    self.assertTrue(all(0 <= x < period and 0 <= y < period for _, _, x, y in octave_calls))
        with patch.object(fields, "_noise_lattice_word", wraps=original) as word:
            fields.noise_field_codes(**DEFAULTS)
            count = word.call_count
            fields.noise_field_codes(**DEFAULTS)
            self.assertEqual(word.call_count, count*2)

    def test_repeatability_rng_and_filesystem_independence(self):
        state = random.getstate()
        try:
            expected = fields.noise_field_codes(**DEFAULTS)
            with ExitStack() as stack:
                for target in ("builtins.open", "io.open", "os.open", "random.random", "random.randrange",
                               "random.randint", "random.getrandbits", "builtins.hash"):
                    stack.enter_context(patch(target, side_effect=AssertionError("not pure")))
                for method in ("read_bytes", "read_text"):
                    stack.enter_context(patch.object(Path, method, side_effect=AssertionError("no files")))
                for seed in (0, 1, 4294967295):
                    random.seed(seed)
                    before = random.getstate()
                    self.assertEqual(fields.noise_field_codes(**DEFAULTS), expected)
                    self.assertEqual(random.getstate(), before)
        finally:
            random.setstate(state)

    def test_finite_typed_values_not_limited_to_widget_steps(self):
        args = (1, 4.2, 2, .123, .125, -.3)
        actual = fields.noise_field_codes(*args)
        sample = reference_sampler(*args)
        self.assertEqual(actual[0], math.floor(sample(Fraction(1, 2), Fraction(1, 2))*255 + Fraction(1, 2)))
        # Range-safe arithmetic even for the smallest positive binary64 input.
        tiny = float.fromhex("0x0.0000000000001p-1022")
        actual = fields.noise_field_codes(0, 4, 6, tiny, 0, 0)
        self.assertEqual(actual, fields.noise_field_codes(0, 4, 1, 0, 0, 0))

    def test_invalid_parameters_fail_before_hashing_or_mask_conversion(self):
        class IntSubclass(int):
            pass
        class FloatSubclass(float):
            pass
        common = (True, False, None, "2", [], {}, IntSubclass(1), FloatSubclass(.5),
                  float("nan"), float("inf"), -float("inf"))
        for name, low, high in (("seed", 0, 4294967295), ("octaves", 1, 6),
                                ("frequency", .5, 32), ("persistence", 0, 1),
                                ("offset_x", -128, 128), ("offset_y", -128, 128)):
            invalid = common + (low-1, high+1, 10**400)
            if name in ("seed", "octaves"):
                invalid += (1.0, 1.5)
            for bad in invalid:
                with self.subTest(name=name, bad=bad), patch.object(fields, "codes_to_mask") as encode, \
                        patch.object(fields, "_noise_lattice_word") as word:
                    for generate in (fields.noise_field_codes, fields.ConditioningLayersNoiseField().generate):
                        with self.assertRaisesRegex(ValueError, name):
                            generate(**{**DEFAULTS, name: bad})
                    encode.assert_not_called()
                    word.assert_not_called()
