"""Pure Voronoi geometry and independent rational/translated-image oracle."""

from contextlib import ExitStack
from fractions import Fraction
import hashlib
import itertools
from pathlib import Path
import random
import struct
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui import procedural_field_sources as fields


DEFAULTS = dict(seed=0, grid=6, jitter_percent=100, members=2,
                assignment_mode="cyclic", member_shift=0)
# SHA-256 of A/B/C/D concatenated row-major code bytes, including unused planes.
GOLDENS = (
    ((0, 6, 0, 2, "cyclic", 0), "f06485c376a7ff65f4de266b83060130ab54b51c4d379dc4f671ff5daabe3b98"),
    ((1, 3, 100, 3, "cyclic", 1), "28b4d2f0341f147ff8b456bc88aa0155d5cd29fac40b2fe13e3900d9af838464"),
    ((4294967295, 8, 100, 4, "hashed", 3), "bc8ccd4558ef6afea7e2c65c84cc46049ac01d90c1860ab590535ec9cd6425d7"),
    ((1, 2, 100, 4, "cyclic", 0), "33ba3698dd240d94c9e5cf55ee6712037024cace09e2d1b421694434571432d4"),
)


def reference_sites(seed, grid, jitter_percent, members, assignment_mode, member_shift):
    sites = []
    for row in range(grid):
        for col in range(grid):
            digest = hashlib.sha256(
                ("conditioning-layers.voronoi-partition.v1:%d:%d:%d" %
                 (seed, col, row)).encode("ascii")).digest()
            wx, wy, wm, wt = struct.unpack(">QQQQ", digest)
            def position(cell, word):
                center = Fraction(2 * cell + 1, 2)
                jitter = Fraction(jitter_percent, 100) * (Fraction(2 * word + 1, 2**65) - Fraction(1, 2))
                return (Fraction(32768, grid) * (center + jitter)).__floor__()
            # Count crossed categorical boundaries, rather than multiply-high.
            member = (row * grid + col if assignment_mode == "cyclic" else
                      sum(wm * members >= edge * 2**64 for edge in range(1, members)))
            sites.append((position(col, wx), position(row, wy), wt, row, col,
                          (member + member_shift) % members))
    return tuple(sites)


def reference_codes(*args):
    sites = reference_sites(*args)
    # Closest of three translated axis images; no modular-distance formula.
    def axis(center):
        return [min(abs(256*p + 128 - center + image * 32768)
                    for image in (-1, 0, 1)) ** 2 for p in range(128)]
    distances = [(axis(cx), axis(cy), wt, j, i, owner) for cx, cy, wt, j, i, owner in sites]
    owners = [min((xs[x] + ys[y], wt, j, i, owner)
                  for xs, ys, wt, j, i, owner in distances)[-1]
              for y in range(128) for x in range(128)]
    return tuple(tuple(255 if owner == k else 0 for owner in owners) for k in range(4))


class VoronoiPartitionCodesTests(unittest.TestCase):
    def test_surface_and_numeric_widget_contract(self):
        node = fields.ConditioningLayersVoronoiPartitionField
        self.assertEqual(node.__name__, "ConditioningLayersVoronoiPartitionField")
        self.assertEqual(fields.initialize_procedural_field_node_registration()[1][node.__name__],
                         "Voronoi Partition Field")
        self.assertEqual(node.RETURN_TYPES, ("MASK",) * 4)
        self.assertEqual(node.RETURN_NAMES, ("field_a", "field_b", "field_c", "field_d"))
        self.assertEqual(node.CATEGORY, "conditioning/conditioning_layers/fields")
        self.assertEqual(node.FUNCTION, "generate")
        declaration = node.INPUT_TYPES()
        self.assertEqual(tuple(declaration), ("required",))
        inputs = declaration["required"]
        self.assertEqual(tuple(inputs), tuple(DEFAULTS))
        for name, default, low, high in (("seed", 0, 0, 4294967295), ("grid", 6, 1, 16),
                                        ("jitter_percent", 100, 0, 100), ("members", 2, 2, 4),
                                        ("member_shift", 0, 0, 3)):
            self.assertEqual(inputs[name][0], "INT")
            self.assertEqual([inputs[name][1][k] for k in ("default", "min", "max", "step", "display")],
                             [default, low, high, 1, "number"])
        self.assertIs(inputs["seed"][1]["control_after_generate"], False)
        self.assertEqual(inputs["assignment_mode"][0], ["cyclic", "hashed"])
        self.assertEqual(inputs["assignment_mode"][1]["default"], "cyclic")
        self.assertTrue(all(value[1]["tooltip"] for value in inputs.values()))

    def test_site_geometry_matrix_and_cell_containment(self):
        for grid, jitter, seed in itertools.product((1, 2, 3, 8, 16), (0, 50, 100), (0, 1, 4294967295)):
            args = (seed, grid, jitter, 4, "hashed", 3)
            with self.subTest(args=args):
                actual = fields._voronoi_sites(*args)
                self.assertEqual(actual, reference_sites(*args))
                self.assertEqual(len(actual), grid * grid)
                for cx, cy, _, j, i, _ in actual:
                    for position, cell in ((cx, i), (cy, j)):
                        # Floor-quantized cells, matching retained Scatter placement.
                        self.assertGreaterEqual(position, (cell * 32768) // grid)
                        self.assertLess(position, ((cell + 1) * 32768 + grid - 1) // grid)
                        if jitter == 0:
                            self.assertEqual(position, ((2 * cell + 1) * 32768) // (2 * grid))

    def test_hash_word_order_and_extreme_jitter_words(self):
        words = (0, 2**64 - 1, 2**63, 17)
        with patch.object(fields.hashlib, "sha256") as digest:
            digest.return_value.digest.return_value = struct.pack(">QQQQ", *words)
            sites = fields._voronoi_sites(7, 1, 100, 4, "hashed", 3)
            digest.assert_called_once_with(b"conditioning-layers.voronoi-partition.v1:7:0:0")
            self.assertEqual(sites, ((0, 32767, 17, 0, 0, 1),))
            self.assertEqual(fields._voronoi_sites(7, 1, 0, 4, "hashed", 0),
                             ((16384, 16384, 17, 0, 0, 2),))

    def test_full_canvas_oracle_and_partition_matrix(self):
        for grid, jitter in itertools.product((1, 2, 3, 8, 16), (0, 50, 100)):
            seed = (0, 1, 4294967295)[(jitter // 50) % 3]
            args = (seed, grid, jitter, 3, "hashed", 2)
            with self.subTest(args=args):
                actual = fields.voronoi_partition_field_codes(*args)
                self.assertEqual(actual, reference_codes(*args))
                self.assert_partition(actual, 3)

    def assert_partition(self, planes, members):
        self.assertEqual(len(planes), 4)
        for plane in planes:
            self.assertEqual(len(plane), 16384)
            self.assertTrue(all(type(c) is int and c in (0, 255) for c in plane))
        self.assertTrue(all(sum(values) == 255 and values.count(255) == 1
                            for values in zip(*planes[:members])))
        self.assertTrue(all(not any(p) for p in planes[members:]))

    def test_assignments_all_member_counts_modes_and_shifts(self):
        for members, mode, shift in itertools.product((2, 3, 4), ("cyclic", "hashed"), range(4)):
            args = (1, 3, 100, members, mode, shift)
            with self.subTest(args=args):
                actual = fields.voronoi_partition_field_codes(*args)
                self.assertEqual(actual, reference_codes(*args))
                self.assert_partition(actual, members)
                base = fields.voronoi_partition_field_codes(1, 3, 100, members, mode, 0)
                for k in range(members):
                    self.assertEqual(actual[(k + shift) % members], base[k])

    def test_hashed_categorical_boundaries(self):
        for members in (2, 3, 4):
            boundaries = [(edge * 2**64 + members - 1) // members for edge in range(1, members)]
            for word in [0, 2**64 - 1] + [w + delta for w in boundaries for delta in (-1, 0, 1)]:
                with patch.object(fields.hashlib, "sha256") as digest:
                    digest.return_value.digest.return_value = struct.pack(">QQQQ", 0, 0, word, 0)
                    owner = fields._voronoi_sites(0, 1, 0, members, "hashed", 0)[0][-1]
                    self.assertEqual(owner, sum(word >= boundary for boundary in boundaries))

    def test_periodic_x_y_and_corner_wrapping(self):
        for cx, cy in ((32760, 128), (128, 32760), (32760, 32760)):
            sites = ((cx, cy, 1, 0, 0, 0), (1000, 1000, 0, 0, 1, 1))
            # At sample (128,128), wrapped site wins across either/both seams.
            self.assertEqual(fields._voronoi_partition_codes(sites)[0][0], 255)
            self.assertEqual(fields._voronoi_partition_codes(tuple(reversed(sites))),
                             fields._voronoi_partition_codes(sites))

    def test_squared_euclidean_not_manhattan_or_chebyshev(self):
        for diagonal, axis, expected in ((6, 10, 0), (8, 10, 1)):
            sites = ((128 + diagonal, 128 + diagonal, 0, 0, 0, 0),
                     (128 + axis, 128, 1, 0, 1, 1))
            self.assertEqual(fields._voronoi_partition_codes(sites)[expected][0], 255)

    def test_ties_use_word_then_row_then_column_never_iteration(self):
        for left_key, right_key in (((9, 0, 0), (1, 1, 1)),
                                    ((1, 2, 0), (1, 1, 5)),
                                    ((1, 1, 5), (1, 1, 2))):
            sites = ((100, 128, *left_key, 0), (156, 128, *right_key, 1))
            for order in (sites, tuple(reversed(sites))):
                self.assertEqual(fields._voronoi_partition_codes(order)[1][0], 255)
        # Distance takes priority even over the largest tie word.
        self.assertEqual(fields._voronoi_partition_codes(
            ((128, 128, 2**64 - 1, 1, 1, 0), (129, 128, 0, 0, 0, 1)))[0][0], 255)

    def test_empty_members_are_valid_and_not_forced(self):
        for members, mode, shift in itertools.product((2, 3, 4), ("cyclic", "hashed"), range(4)):
            planes = fields.voronoi_partition_field_codes(0, 1, 100, members, mode, shift)
            self.assert_partition(planes, members)
            self.assertEqual(sum(any(p) for p in planes), 1)

    def test_repeatability_no_rng_or_filesystem(self):
        state = random.getstate()
        try:
            expected = fields.voronoi_partition_field_codes(**DEFAULTS)
            with ExitStack() as stack:
                for target in ("builtins.open", "io.open", "os.open", "random.random",
                               "random.randrange", "random.randint", "random.getrandbits"):
                    stack.enter_context(patch(target, side_effect=AssertionError("not pure")))
                for method in ("read_bytes", "read_text"):
                    stack.enter_context(patch.object(Path, method, side_effect=AssertionError("no files")))
                for seed in (0, 1, 4294967295):
                    random.seed(seed)
                    before = random.getstate()
                    self.assertEqual(fields.voronoi_partition_field_codes(**DEFAULTS), expected)
                    self.assertEqual(random.getstate(), before)
        finally:
            random.setstate(state)

    def test_goldens_match_independent_oracle(self):
        for args, expected in GOLDENS:
            for generator in (reference_codes, fields.voronoi_partition_field_codes):
                self.assertEqual(hashlib.sha256(b"".join(bytes(p) for p in generator(*args))).hexdigest(), expected)

    def test_invalid_controls_name_control_before_mask_conversion(self):
        class IntSubclass(int):
            pass
        bad_values = (True, False, None, "2", 2.0, [], {}, IntSubclass(2),
                      float("nan"), float("inf"), -float("inf"))
        for name, low, high in (("seed", 0, 4294967295), ("grid", 1, 16),
                                ("jitter_percent", 0, 100), ("members", 2, 4), ("member_shift", 0, 3)):
            for bad in bad_values + (low - 1, high + 1):
                self.assert_invalid(name, bad)
        for bad in (True, False, None, 0, 1.0, [], {}, "", "CYCLIC", "random", "hashed "):
            self.assert_invalid("assignment_mode", bad)

    def assert_invalid(self, name, bad):
        with self.subTest(name=name, bad=bad), patch.object(fields, "codes_to_mask") as encode:
            for generator in (fields.voronoi_partition_field_codes,
                              fields.ConditioningLayersVoronoiPartitionField().generate):
                with self.assertRaisesRegex(ValueError, name):
                    generator(**{**DEFAULTS, name: bad})
            encode.assert_not_called()
