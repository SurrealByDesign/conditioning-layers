"""Pure cyclic partition contract and independent cell-boundary oracle."""

from contextlib import ExitStack
import hashlib
import itertools
from pathlib import Path
import random
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui import procedural_field_sources as fields


DEFAULTS = dict(columns=8, rows=8, members=2, shift=1)
# SHA-256 of four concatenated row-major code planes, A/B/C/D including unused.
GOLDENS = (
    ((8, 8, 2, 1), "1bcb40b02acc3aa3e786a67792fa6deaf483e7d4836332d665a5e233e2ce4079"),
    ((7, 5, 3, 2), "5e38d86e60a2babd5d96bf6791291cd58e01f83da8c7ecad40dbbbcb0cf38794"),
    ((32, 3, 4, 3), "510487cd532a07e8a93db4ff9a4a3a9bd63b1149948ff537c1bdd9740194aafe"),
)


def reference_codes(columns, rows, members, shift):
    # Count crossed cell edges, independently of production's floor division.
    def cells(count):
        return [sum((2 * p + 1) * count >= 256 * edge
                    for edge in range(1, count)) for p in range(128)]
    owners = [(col + shift * row) % members
              for row in cells(rows) for col in cells(columns)]
    return tuple(tuple(255 if owner == k else 0 for owner in owners) for k in range(4))


class CyclicPartitionCodesTests(unittest.TestCase):
    def test_surface_and_native_exact_entry_metadata(self):
        node = fields.ConditioningLayersCyclicPartitionField
        self.assertEqual(node.__name__, "ConditioningLayersCyclicPartitionField")
        self.assertEqual(node.RETURN_TYPES, ("MASK",) * 4)
        self.assertEqual(node.RETURN_NAMES, ("field_a", "field_b", "field_c", "field_d"))
        self.assertEqual(node.FUNCTION, "generate")
        self.assertEqual(node.CATEGORY, "conditioning/conditioning_layers/fields")
        declaration = node.INPUT_TYPES()
        self.assertEqual(tuple(declaration), ("required",))
        inputs = declaration["required"]
        self.assertEqual(tuple(inputs), ("columns", "rows", "members", "shift"))
        for name, default, low, high in (("columns", 8, 1, 32), ("rows", 8, 1, 32),
                                        ("members", 2, 2, 4), ("shift", 1, 0, 3)):
            kind, options = inputs[name]
            self.assertEqual(kind, "INT")
            self.assertEqual([options[k] for k in ("default", "min", "max", "step", "display")],
                             [default, low, high, 1, "number"])
            self.assertTrue(options["tooltip"])
        self.assertIn("empty", node.DESCRIPTION)
        self.assertIn("BLENDED", node.DESCRIPTION)
        self.assertIn("no longer safe as FIXED", node.DESCRIPTION)

    def test_geometry_and_exact_ownership_matrix(self):
        # 192 complete canvases, including indivisible grids and all shifts/counts.
        for columns, rows, members, shift in itertools.product((1, 3, 8, 32),
                                                               (1, 5, 8, 32),
                                                               (2, 3, 4), range(4)):
            with self.subTest(columns=columns, rows=rows, members=members, shift=shift):
                actual = fields.cyclic_partition_field_codes(columns, rows, members, shift)
                self.assertEqual(actual, reference_codes(columns, rows, members, shift))
                self.assertEqual(len(actual), 4)
                for plane in actual:
                    self.assertEqual(len(plane), 16384)
                    self.assertTrue(all(type(c) is int and c in (0, 255) for c in plane))
                self.assertTrue(all(sum(codes) == 255 and codes.count(255) == 1
                                    for codes in zip(*actual[:members])))
                self.assertTrue(all(not any(plane) for plane in actual[members:]))

    def owners(self, columns, rows, members, shift):
        return tuple(codes.index(255) for codes in
                     zip(*fields.cyclic_partition_field_codes(columns, rows, members, shift)))

    def test_rows_one_column_cycle_is_independent_of_shift(self):
        for members, shift in itertools.product((2, 3, 4), range(4)):
            expected_row = tuple((x // 16) % members for x in range(128))
            self.assertEqual(self.owners(8, 1, members, shift), expected_row * 128)

    def test_columns_one_row_cycles_and_degenerate_shift(self):
        for members, shift in itertools.product((2, 3, 4), range(4)):
            self.assertEqual(self.owners(1, 8, members, shift),
                             tuple((shift * (y // 16)) % members
                                   for y in range(128) for _ in range(128)))

    def test_shift_zero_has_only_vertical_bands(self):
        for members, rows in itertools.product((2, 3, 4), (1, 7, 32)):
            self.assertEqual(self.owners(8, rows, members, 0),
                             tuple((x // 16) % members for x in range(128)) * 128)

    def test_representative_cell_patterns(self):
        for members, shift, expected in (
            (2, 1, ((0, 1, 0, 1), (1, 0, 1, 0), (0, 1, 0, 1))),
            (3, 1, ((0, 1, 2, 0), (1, 2, 0, 1), (2, 0, 1, 2))),
            (3, 2, ((0, 1, 2, 0), (2, 0, 1, 2), (1, 2, 0, 1))),
            (4, 3, ((0, 1, 2, 3), (3, 0, 1, 2), (2, 3, 0, 1))),
        ):
            owners = self.owners(4, 4, members, shift)
            self.assertEqual(tuple(tuple(owners[(32*y+16)*128+32*x+16] for x in range(4))
                                   for y in range(3)), expected)

    def test_active_members_need_not_all_have_support(self):
        for members in (2, 3, 4):
            for shift in range(4):
                self.assertEqual(fields.cyclic_partition_field_codes(1, 1, members, shift),
                                 ((255,) * 16384,) + ((0,) * 16384,) * 3)
        planes = fields.cyclic_partition_field_codes(1, 8, 4, 2)
        self.assertTrue(any(planes[0]) and any(planes[2]))
        self.assertFalse(any(planes[1]) or any(planes[3]))

    def test_repeatability_without_rng_or_filesystem_dependency(self):
        state = random.getstate()
        try:
            expected = fields.cyclic_partition_field_codes(**DEFAULTS)
            with ExitStack() as stack:
                for target in ("builtins.open", "io.open", "os.open", "random.random",
                               "random.randrange", "random.randint", "random.getrandbits"):
                    stack.enter_context(patch(target, side_effect=AssertionError("not pure")))
                for method in ("read_bytes", "read_text"):
                    stack.enter_context(patch.object(Path, method, side_effect=AssertionError("no files")))
                for seed in (0, 42, 4294967295):
                    random.seed(seed)
                    seeded_state = random.getstate()
                    self.assertEqual(fields.cyclic_partition_field_codes(**DEFAULTS), expected)
                    self.assertEqual(random.getstate(), seeded_state)
        finally:
            random.setstate(state)

    def test_golden_hashes_match_independent_oracle(self):
        for args, expected in GOLDENS:
            for generator in (reference_codes, fields.cyclic_partition_field_codes):
                digest = hashlib.sha256(b"".join(bytes(p) for p in generator(*args))).hexdigest()
                self.assertEqual(digest, expected)

    def test_invalid_controls_fail_before_mask_conversion(self):
        class IntSubclass(int):
            pass
        for name, low, high in (("columns", 1, 32), ("rows", 1, 32),
                                ("members", 2, 4), ("shift", 0, 3)):
            for bad in (True, False, None, "2", 2.0, [], {}, IntSubclass(2),
                        float("nan"), float("inf"), -float("inf"), low-1, high+1):
                with self.subTest(name=name, bad=bad), patch.object(fields, "codes_to_mask") as encode:
                    args = {**DEFAULTS, name: bad}
                    for generate in (fields.cyclic_partition_field_codes,
                                     fields.ConditioningLayersCyclicPartitionField().generate):
                        with self.assertRaisesRegex(ValueError, name):
                            generate(**args)
                    encode.assert_not_called()


if __name__ == "__main__":
    unittest.main()
