"""Independent integer-predicate oracle and deterministic identities; developer lane."""

import hashlib
import itertools
import random
import struct
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui import procedural_field_sources as scatter


DEFAULTS = dict(seed=0, grid=8, density_percent=50, jitter_percent=75,
                radius=5.0, radius_variation_percent=25, shape="disk")
# Pinned from the independent full-sample predicate oracle, not the span renderer.
GOLDENS = (
    ((0, 8, 50, 75, 5.0, 25, "disk"), "51cd5848a08cea350ae3fb8adda536ef6c96138eccd5605baa692ce6c33124e6"),
    ((4294967295, 3, 51, 100, 20, 100, "square"), "5e68a91a7669a559454b96d24962d8b1b4ec198c48feb32b5127c098b1fff322"),
    ((1, 5, 99, 50, 3.5, 0, "diamond"), "ec4aea7502f613abd66a44efd4224bad14526984e949e29efe4eb5ffb09e9446"),
)


def spec_sites(seed, grid, density):
    sites = []
    for row in range(grid):
        for column in range(grid):
            text = "conditioning-layers.scatter-field.v1:%d:%d:%d" % (seed, column, row)
            keep, x, y, radius = struct.unpack(">QQQQ", hashlib.sha256(text.encode("ascii")).digest())
            sites.append((keep, row, column, x, y, radius))
    return tuple(sorted(sites, key=lambda site: (site[0], site[1], site[2]))[:
        (grid * grid * density + 50) // 100])


def spec_codes(seed, grid, density, jitter, radius, variation, shape):
    """Intentionally slow sample-by-feature oracle, with no span logic."""
    period, word_range = 32768, 18446744073709551616
    features = []
    for _, j, i, wx, wy, wr in spec_sites(seed, grid, density):
        cx = period * ((2*i+1)*100*word_range + jitter*(2*wx+1-word_range)) // (2*grid*100*word_range)
        cy = period * ((2*j+1)*100*word_range + jitter*(2*wy+1-word_range)) // (2*grid*100*word_range)
        r0 = 128 * int(2 * radius)
        r = r0 - r0 * variation * wr // (100 * word_range)
        features.append((cx, cy, r))
    result = []
    for y in range(128):
        for x in range(128):
            code = 0
            for cx, cy, r in features:
                dx = ((256*x+128-cx+period//2) % period) - period//2
                dy = ((256*y+128-cy+period//2) % period) - period//2
                inside = (dx*dx+dy*dy <= r*r if shape == "disk" else
                          max(abs(dx), abs(dy)) <= r if shape == "square" else
                          abs(dx)+abs(dy) <= r)
                if inside:
                    code = 255
                    break
            result.append(code)
    return tuple(result)


class ScatterCodesTests(unittest.TestCase):
    def test_independent_sha256_vectors_and_word_order(self):
        # SHA-256 digests also checked with .NET SHA256 independently of hashlib.
        vectors = ((0, 0, 0, "b514888e27312fe308ee292db9e43d0384f5645b8fc0aa49d2aba18355219049"),
                   (4294967295, 2, 1, "135d356c187ab1d30712f17a8df1d0b57ff7c34d8f9266a79132bf140da937f6"))
        for seed, i, j, expected in vectors:
            digest = hashlib.sha256(f"conditioning-layers.scatter-field.v1:{seed}:{i}:{j}".encode("ascii"))
            self.assertEqual(digest.hexdigest(), expected)
            words = struct.unpack(">QQQQ", bytes.fromhex(expected))
            site = next(s for s in scatter._kept_sites(seed, 3, 100) if s[1:3] == (j, i))
            self.assertEqual(site, (words[0], j, i, *words[1:]))

    def test_bounded_full_sample_oracle_matrix(self):
        # 72 cases: full shape/jitter/variation/grid cross, rotating all radii/seeds.
        combinations = itertools.product(("disk", "square", "diamond"), (0, 50, 100),
                                         (0, 100), (1, 2, 3, 5))
        for index, (shape, jitter, variation, grid) in enumerate(combinations):
            args = ((0, 1, 4294967295)[index % 3], grid, (49, 100, 51)[index % 3],
                    jitter, (0.5, 3.5, 20)[(index // 3) % 3], variation, shape)
            with self.subTest(args=args):
                actual = scatter.scatter_field_codes(*args)
                self.assertEqual(actual, spec_codes(*args))
                self.assertEqual(len(actual), 16384)
                self.assertTrue(all(type(c) is int and c in (0, 255) for c in actual))

    def test_exact_kept_counts_and_site_nesting(self):
        densities = (0, 1, 49, 50, 51, 99, 100)
        expected = {1: (0, 0, 0, 1, 1, 1, 1), 3: (0, 0, 4, 5, 5, 9, 9),
                    32: (0, 10, 502, 512, 522, 1014, 1024)}
        for grid in (1, 3, 32):
            previous = ()
            for density, count in zip(densities, expected[grid]):
                sites = scatter._kept_sites(4294967295, grid, density)
                self.assertEqual(len(sites), count)
                self.assertEqual(sites, spec_sites(4294967295, grid, density))
                self.assertEqual(sites[:len(previous)], previous)
                previous = sites

    def test_keep_hash_ties_use_row_then_column(self):
        with patch.object(scatter.hashlib, "sha256") as sha:
            sha.return_value.digest.return_value = bytes(32)
            self.assertEqual([s[1:3] for s in scatter._kept_sites(0, 3, 50)],
                             [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1)])

    def test_pointwise_density_monotonicity(self):
        for shape, grid in itertools.product(("disk", "square", "diamond"), (1, 3, 32)):
            previous = (0,) * 16384
            for density in (0, 1, 49, 50, 51, 99, 100):
                current = scatter.scatter_field_codes(1, grid, density, 100, 3.5, 100, shape)
                self.assertTrue(all(a <= b for a, b in zip(previous, current)))
                previous = current

    def test_wrap_both_axes_and_inclusive_boundaries(self):
        # Force one center to (0,0), radius one cell: all four corners are in
        # the disk/square, and exactly on the diamond boundary.
        site = ((0, 0, 0, 0, 0, 0),)
        with patch.object(scatter, "_kept_sites", return_value=site):
            for shape in ("disk", "square", "diamond"):
                codes = scatter.scatter_field_codes(0, 1, 100, 100, 1, 0, shape)
                self.assertEqual([codes[k] for k in (0, 127, 16256, 16383)], [255]*4)
                self.assertEqual(sum(c != 0 for c in codes), 4)
        # At the smallest radius, centered between samples, disk/diamond
        # contain no sample; square includes its four boundary corners.
        for shape in ("disk", "square", "diamond"):
            codes = scatter.scatter_field_codes(0, 1, 100, 0, .5, 0, shape)
            self.assertEqual(sum(c != 0 for c in codes), 4 if shape == "square" else 0)

    def test_zero_jitter_periodicity_and_square_tiling(self):
        for shape in ("disk", "square", "diamond"):
            codes = scatter.scatter_field_codes(0, 8, 100, 0, 3.5, 0, shape)
            self.assertEqual(codes, tuple(codes[((y+16)%128)*128+(x+16)%128]
                                          for y in range(128) for x in range(128)))
            self.assertEqual(codes, tuple(codes[y*128+(x+16)%128]
                                          for y in range(128) for x in range(128)))
        self.assertEqual(set(scatter.scatter_field_codes(0, 8, 100, 0, 8, 0, "square")), {255})

    def test_zero_density(self):
        for shape in ("disk", "square", "diamond"):
            self.assertEqual(scatter.scatter_field_codes(4294967295, 32, 0, 100, 32, 100, shape), (0,)*16384)

    def test_repeatability_and_random_state_independence(self):
        state = random.getstate()
        try:
            expected = scatter.scatter_field_codes(**DEFAULTS)
            for seed in (0, 100, 4294967295):
                random.seed(seed)
                random.random()
                self.assertEqual(scatter.scatter_field_codes(**DEFAULTS), expected)
        finally:
            random.setstate(state)

    def test_pinned_golden_hashes(self):
        for args, expected in GOLDENS:
            self.assertEqual(hashlib.sha256(bytes(spec_codes(*args))).hexdigest(), expected)
            self.assertEqual(hashlib.sha256(bytes(scatter.scatter_field_codes(*args))).hexdigest(), expected)

    def test_integer_validation_names_every_control(self):
        class IntSubclass(int):
            pass
        for name, low, high in (("seed", 0, 4294967295), ("grid", 1, 32),
                                ("density_percent", 0, 100), ("jitter_percent", 0, 100),
                                ("radius_variation_percent", 0, 100)):
            for bad in (True, False, None, "1", 1.0, float("nan"), float("inf"),
                        IntSubclass(1), low-1, high+1):
                with self.subTest(name=name, bad=bad), self.assertRaisesRegex(ValueError, name):
                    scatter.scatter_field_codes(**{**DEFAULTS, name: bad})

    def test_radius_and_shape_validation(self):
        for bad in (True, False, None, "1", 0, .49, 32.5, .75, 1.1,
                    float("nan"), float("inf"), -float("inf"), 10**1000):
            with self.subTest(radius=bad), self.assertRaisesRegex(ValueError, "radius"):
                scatter.scatter_field_codes(**{**DEFAULTS, "radius": bad})
        for bad in (None, True, 0, [], {}, "Disk", "circle", " disk", "disk "):
            with self.subTest(shape=bad), self.assertRaisesRegex(ValueError, "shape"):
                scatter.scatter_field_codes(**{**DEFAULTS, "shape": bad})
        for radius in (.5, 1, 3.5, 32):
            self.assertEqual(len(scatter.scatter_field_codes(**{**DEFAULTS, "radius": radius})), 16384)


if __name__ == "__main__":
    unittest.main()
