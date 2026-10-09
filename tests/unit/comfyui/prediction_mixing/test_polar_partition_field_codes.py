"""Polar v1 pure contract; independent complex-coordinate / edge-count oracle."""

import cmath
from contextlib import ExitStack
import hashlib
import itertools
import math
from pathlib import Path
import random
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui import procedural_field_sources as fields


DEFAULTS = dict(center_x=.5, center_y=.5, rings=4, sectors=8, members=2,
                radial_shift=0, angular_shift=0, assignment_mode="checker")
CASES = ((.5, .5, 4, 8, 2, 0, 0, "radial"),
         (.5, .5, 4, 8, 3, 0, 0, "angular"),
         (.5, .5, 4, 8, 4, 0, 0, "checker"),
         (.35, .60, 5, 12, 3, 1, 2, "spiral"))
# SHA-256 of A/B/C/D concatenated row-major code bytes, including unused planes.
# Qualified from independent oracle / implementation full-canvas agreement.
GOLDENS = tuple(zip(CASES, (
    "3c5e0975601c02ba6a0dfae0df83cfcac1cadbe8cdd781258a0f27bca686ee73",
    "f68029416d66bf6459c9d9b335104e58dec592c804a2a85be7ddbe565357a641",
    "c67a4bf79a64c2cc9b4cd1d774637334bf22f14c0b189b6e0d0200e8d84900f6",
    "8b17e4877c31ab4859c731534961c6d248972b5e56587458a4c1b60738c8fe83",
)))


def reference_owner(x, y, center_x, center_y, rings, sectors, members,
                    radial_shift, angular_shift, assignment_mode):
    center = complex(128 * center_x, 128 * center_y)
    z = complex(x + .5, y + .5) - center
    # Farthest outer corner can be constructed independently per axis.
    corner = complex(0 if center.real >= 64 else 128,
                     0 if center.imag >= 64 else 128)
    radius = min(1, abs(z) / abs(corner - center))
    # Count crossed internal ring edges rather than floor(rn*rings).
    ring = sum(radius >= edge / rings for edge in range(1, rings))
    theta = cmath.phase(z) if z else 0.0
    if theta < 0:
        theta += 2 * math.pi
    position = theta / (2 * math.pi) * sectors
    if assignment_mode == "spiral":
        position = (position - radius * rings) % sectors
    sector = min(sectors - 1, int(position))
    shifted = (sector + angular_shift) % sectors
    label = {"radial": ring, "angular": shifted,
             "checker": ring + shifted, "spiral": shifted}[assignment_mode]
    return (label + radial_shift) % members


def reference_codes(*args):
    owners = [reference_owner(x, y, *args) for y in range(128) for x in range(128)]
    return tuple(tuple(255 * (owner == member) for owner in owners) for member in range(4))


def owners(**changes):
    return tuple(sample.index(255) for sample in zip(*fields.polar_partition_field_codes(
        **{**DEFAULTS, **changes})))


class PolarPartitionCodesTests(unittest.TestCase):
    def test_surface_control_order_defaults_ranges_and_native_numeric_widgets(self):
        node = fields.ConditioningLayersPolarPartitionField
        self.assertEqual(node.__name__, "ConditioningLayersPolarPartitionField")
        self.assertEqual(node.RETURN_TYPES, ("MASK",) * 4)
        self.assertEqual(node.RETURN_NAMES, ("field_a", "field_b", "field_c", "field_d"))
        self.assertEqual(node.FUNCTION, "generate")
        self.assertEqual(node.CATEGORY, "conditioning/conditioning_layers/fields")
        classes, names = fields.initialize_procedural_field_node_registration()
        self.assertIs(classes[node.__name__], node)
        self.assertEqual(names[node.__name__], "Polar Partition Field")
        declaration = node.INPUT_TYPES()
        self.assertEqual(tuple(declaration), ("required",))
        inputs = declaration["required"]
        self.assertEqual(tuple(inputs), tuple(DEFAULTS))
        for name, kind, low, high, step in (
            ("center_x", "FLOAT", 0., 1., .01), ("center_y", "FLOAT", 0., 1., .01),
            ("rings", "INT", 1, 32, 1), ("sectors", "INT", 1, 64, 1),
            ("members", "INT", 2, 4, 1), ("radial_shift", "INT", 0, 3, 1),
            ("angular_shift", "INT", 0, 63, 1),
        ):
            self.assertEqual(inputs[name][0], kind)
            self.assertEqual([inputs[name][1][k] for k in ("default", "min", "max", "step", "display")],
                             [DEFAULTS[name], low, high, step, "number"])
        self.assertEqual(inputs["assignment_mode"][0], ["radial", "angular", "checker", "spiral"])
        self.assertEqual(inputs["assignment_mode"][1]["default"], "checker")
        self.assertTrue(all(spec[1]["tooltip"] for spec in inputs.values()))
        for term in ("FIXED", "BLENDED", "empty", "Blur", "Fade", "Transform"):
            self.assertIn(term, node.DESCRIPTION)

    def test_full_canvas_oracle_and_partition_matrix(self):
        # All modes and member counts, centered/off-center/edge/corner/coincident
        # centers, minimum/representative/maximum ring and sector counts.
        geometries = ((.5, .5, 1, 1), (.5, .5, 4, 8), (.35, .6, 5, 12),
                      (0., .5, 32, 64), (1., 0., 7, 13), (64.5/128, 64.5/128, 9, 4))
        for geometry, members, mode in itertools.product(
                geometries, (2, 3, 4), ("radial", "angular", "checker", "spiral")):
            args = (*geometry, members, 1, 2, mode)
            with self.subTest(args=args):
                actual = fields.polar_partition_field_codes(*args)
                self.assertEqual(actual, reference_codes(*args))
                self.assertEqual(len(actual), 4)
                for plane in actual:
                    self.assertEqual(len(plane), 16384)
                    self.assertTrue(all(type(c) is int and c in (0, 255) for c in plane))
                self.assertTrue(all(sum(p) == 255 and p.count(255) == 1
                                    for p in zip(*actual[:members])))
                self.assertTrue(all(not any(p) for p in actual[members:]))

    def test_cardinals_and_sample_center_angle_zero(self):
        # Typed non-step centers must remain valid: exact sample coincidence.
        for mode in ("angular", "spiral"):
            actual = owners(center_x=64.5/128, center_y=64.5/128,
                            rings=1, sectors=4, members=4, assignment_mode=mode)
            self.assertEqual(actual[64*128+64], 0)
        actual = owners(center_x=64.5/128, center_y=64.5/128,
                        sectors=4, members=4, assignment_mode="angular")
        for x, y, expected in ((65, 64, 0), (64, 65, 1), (63, 64, 2), (64, 63, 3)):
            self.assertEqual(actual[y*128+x], expected)
        # Make the normative zero-angle branch observable independently of atan2(0,0).
        original = fields.math.atan2
        def no_origin(dy, dx):
            self.assertNotEqual((dx, dy), (0., 0.))
            return original(dy, dx)
        with patch.object(fields.math, "atan2", side_effect=no_origin):
            owners(center_x=.5/128, center_y=.5/128, assignment_mode="spiral")

    def test_outer_corner_normalization_and_euclidean_radius(self):
        # A corner center has r_max=hypot(128,128), not hypot(127.5,127.5).
        actual = owners(center_x=0., center_y=0., rings=32, members=4, assignment_mode="radial")
        expected = tuple(min(31, math.floor(math.hypot(x+.5, y+.5) /
                                            math.hypot(128, 128) * 32)) % 4
                         for y in range(128) for x in range(128))
        wrong = tuple(min(31, math.floor(math.hypot(x+.5, y+.5) /
                                         math.hypot(127.5, 127.5) * 32)) % 4
                      for y in range(128) for x in range(128))
        self.assertEqual(actual, expected)
        self.assertNotEqual(actual, wrong)

    def test_radial_and_angular_geometry_independence(self):
        radial = owners(assignment_mode="radial")
        self.assertEqual(radial, owners(assignment_mode="radial", sectors=64, angular_shift=63))
        angular = owners(assignment_mode="angular")
        self.assertEqual(angular, owners(assignment_mode="angular", rings=32))

    def test_member_shifts_and_full_sector_cycle(self):
        for mode, members in itertools.product(("radial", "angular", "checker", "spiral"), (2, 3, 4)):
            base = owners(assignment_mode=mode, members=members, sectors=7)
            for shift in range(4):
                self.assertEqual(owners(assignment_mode=mode, members=members, sectors=7, radial_shift=shift),
                                 tuple((owner + shift) % members for owner in base))
            for shift in (0, 1, 6, 7, 31, 56):
                self.assertEqual(owners(assignment_mode=mode, members=members, sectors=7, angular_shift=shift),
                                 owners(assignment_mode=mode, members=members, sectors=7, angular_shift=shift+7))

    def test_angular_shift_wraps_sectors_before_members(self):
        for mode in ("angular", "checker", "spiral"):
            args = (.35, .6, 5, 7, 3, 2, 63, mode)
            self.assertEqual(fields.polar_partition_field_codes(*args), reference_codes(*args))

    def test_spiral_near_origin_outer_radius_wrapping_and_ring_counts(self):
        for rings, sectors, members in itertools.product((1, 4, 32), (1, 8, 64), (2, 3, 4)):
            args = (0., 0., rings, sectors, members, 3, 63, "spiral")
            planes = fields.polar_partition_field_codes(*args)
            # rn ~ .0039 at (0,0), ~ .9961 at (127,127). At (127,0)
            # the negative phase wraps; rings=32 crosses several full turns.
            for x, y in ((0, 0), (1, 0), (127, 0), (63, 64), (127, 127)):
                self.assertEqual(tuple(p[y*128+x] for p in planes).index(255),
                                 reference_owner(x, y, *args))

    def test_spiral_clockwise_outward_and_continuous_not_ring_steps(self):
        args = {**DEFAULTS, "center_x": 0., "center_y": 0., "rings": 4,
                "sectors": 8, "members": 4, "assignment_mode": "spiral"}
        actual = owners(**args)
        # At 45 degrees, continuous phase crosses the angular boundary
        # immediately after the origin, then the next boundary at rn=1/4.
        self.assertEqual(actual[0], 0)
        self.assertEqual(actual[31*128+31], 0)
        self.assertEqual(actual[32*128+32], 3)
        # A boundary satisfies angle/tau*sectors = constant + rn*rings:
        # increasing radius increases screen angle (clockwise).
        self.assertEqual(actual, tuple(sample.index(255) for sample in zip(*reference_codes(*args.values()))))

    def test_spiral_default_nonredundancy_and_rejected_cancellation(self):
        spiral = owners(assignment_mode="spiral")
        angular = owners(assignment_mode="angular")
        checker = owners(assignment_mode="checker")
        self.assertEqual(sum(a != b for a, b in zip(spiral, angular)), 8704)
        self.assertEqual(sum(a != b for a, b in zip(spiral, checker)), 8512)
        for mode, actual in (("spiral", spiral), ("angular", angular), ("checker", checker)):
            args = {**DEFAULTS, "assignment_mode": mode}
            self.assertEqual(actual, tuple(sample.index(255) for sample in zip(*reference_codes(*args.values()))))
        rejected = []
        for y in range(128):
            for x in range(128):
                dx, dy = x+.5-64, y+.5-64
                ring = int(math.hypot(dx, dy) / math.hypot(64, 64) * 4)
                sector = int((math.atan2(dy, dx) % math.tau) / math.tau * 8)
                rejected.append(((sector + ring) % 8 + ring) % 2)
        self.assertEqual(tuple(rejected), angular)

    def test_empty_active_members_and_sectors_one_spiral_degeneracy(self):
        for mode in ("radial", "angular", "checker", "spiral"):
            for members in (2, 3, 4):
                self.assertEqual(owners(rings=1, sectors=1, members=members,
                                        radial_shift=3, assignment_mode=mode), (3 % members,) * 16384)
        self.assertEqual(owners(rings=32, sectors=1, assignment_mode="spiral"), (0,) * 16384)

    def test_determinism_no_rng_or_files(self):
        state = random.getstate()
        try:
            for mode in ("radial", "angular", "checker", "spiral"):
                expected = owners(assignment_mode=mode)
                with ExitStack() as stack:
                    for target in ("builtins.open", "io.open", "os.open", "random.random",
                                   "random.randrange", "random.randint", "random.getrandbits"):
                        stack.enter_context(patch(target, side_effect=AssertionError("not pure")))
                    for method in ("read_bytes", "read_text"):
                        stack.enter_context(patch.object(Path, method, side_effect=AssertionError("no files")))
                    for seed in (0, 42):
                        random.seed(seed)
                        before = random.getstate()
                        self.assertEqual(owners(assignment_mode=mode), expected)
                        self.assertEqual(random.getstate(), before)
        finally:
            random.setstate(state)

    def test_golden_hashes_match_independent_oracle(self):
        self.assertEqual(len(GOLDENS), 4)
        for args, digest in GOLDENS:
            actual, reference = fields.polar_partition_field_codes(*args), reference_codes(*args)
            self.assertEqual(actual, reference)
            for planes in (actual, reference):
                self.assertEqual(hashlib.sha256(b"".join(bytes(p) for p in planes)).hexdigest(), digest)

    def test_invalid_controls_name_control_before_encoding(self):
        invalid = {}
        for name in ("center_x", "center_y"):
            invalid[name] = (True, False, None, "0.5", [], {}, float("nan"),
                             float("inf"), -float("inf"), -.01, 1.01)
        for name, low, high in (("rings", 1, 32), ("sectors", 1, 64), ("members", 2, 4),
                                ("radial_shift", 0, 3), ("angular_shift", 0, 63)):
            invalid[name] = (True, False, None, "2", 2., [], {}, float("nan"),
                             float("inf"), -float("inf"), low-1, high+1)
        invalid["assignment_mode"] = (None, True, 0, [], {}, "", "SPIRAL", "noise")
        for name, values in invalid.items():
            for value in values:
                with self.subTest(name=name, value=value), patch.object(fields, "codes_to_mask") as encode:
                    for generate in (fields.polar_partition_field_codes,
                                     fields.ConditioningLayersPolarPartitionField().generate):
                        with self.assertRaisesRegex(ValueError, name):
                            generate(**{**DEFAULTS, name: value})
                    encode.assert_not_called()


if __name__ == "__main__":
    unittest.main()
