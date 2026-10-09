"""Independent geometry/curve oracles and validation; pure developer lane."""

from decimal import Decimal, ROUND_HALF_UP, localcontext
import hashlib
import inspect
import math
import unittest

from conditioning_layers.comfyui.field_fade import ConditioningLayersFieldFade, _fade_function, _quantize


DEFAULTS = {k: v.default for k, v in inspect.signature(ConditioningLayersFieldFade.apply).parameters.items()
            if k not in ("self", "mask")}
GOLDENS = (
    ({}, "6d362758bfd7e5770b30240f87ef5b9dcac11ef6b697d3ba84d299456b97f018"),
    ({"fade_mode": "circular", "center_x": .3, "center_y": .65, "inner_size": .1,
      "outer_size": 1.2, "aspect_x": 1.6, "aspect_y": .7, "rotation_degrees": 31.,
      "curve_exponent": 2., "start_value": 180, "end_value": 40}, "57dc3af8615eb12322d8f1fa58f52218575facaa20b963e81270b87f19bc20b1"),
    ({"fade_mode": "square", "rotation_degrees": 45., "inner_size": .2,
      "outer_size": .9}, "6fa8350cc9eb67de91b2ac9e623956960be7dfa38d3fa9f0b18a86c2e11889d3"),
)


def fade(**kwargs):
    return _fade_function(**(DEFAULTS | kwargs))


def reference(x, y, code=255, **kwargs):
    """Decimal geometry, explicit corner projection, independently rounded product.

    Trig supplies only a direction; all subsequent work uses 50 decimal digits.
    Cardinal/diagonal angles have exact or high-precision algebraic axes.
    """
    p = DEFAULTS | kwargs
    with localcontext() as ctx:
        ctx.prec = 50
        d = lambda v: Decimal(str(v))
        mode = p['fade_mode']
        angle = p['angle_degrees'] if mode == 'linear' else p['rotation_degrees']
        if mode == 'circular' and p['aspect_x'] == p['aspect_y']:
            angle = 0
        if angle % 45 == 0:
            h = Decimal('.5').sqrt()
            c, s = ((1, 0), (h, h), (0, 1), (-h, h), (-1, 0),
                    (-h, -h), (0, -1), (h, -h))[int(angle % 360 / 45)]
            c, s = d(c), d(s)
        else:
            c, s = d(math.cos(math.radians(angle))), d(math.sin(math.radians(angle)))
        px, py = d(x) + d('.5'), d(y) + d('.5')
        if mode == 'linear':
            corners = [c * a + s * b for a in (0, 128) for b in (0, 128)]
            position = (px * c + py * s - min(corners)) / (max(corners) - min(corners))
            low, high = d(p['fade_start_position']), d(p['fade_end_position'])
        else:
            px, py = px - 128 * d(p['center_x']), py - 128 * d(p['center_y'])
            a = (px * c + py * s) / d(p['aspect_x']) / 64
            b = (py * c - px * s) / d(p['aspect_y']) / 64
            position = (a*a + b*b).sqrt() if mode == 'circular' else max(abs(a), abs(b))
            low, high = d(p['inner_size']), d(p['outer_size'])
        t = max(Decimal(0), min(Decimal(1), (position - low) / (high - low)))
        u = t ** d(p['curve_exponent'])
        f = d(p['start_value']) + u * d(p['end_value'] - p['start_value'])
        return int((d(code) * f / 255).quantize(Decimal(1), rounding=ROUND_HALF_UP))


class FadeCodeTests(unittest.TestCase):
    def test_linear_cardinal_diagonal_geometry_against_decimal_oracle(self):
        for angle in (0, 90, 180, 270, -90, 45, 135, 31):
            fn = fade(angle_degrees=angle)
            for x, y in ((0, 0), (127, 0), (0, 127), (127, 127), (31, 76), (63, 64)):
                self.assertEqual(_quantize(fn(x, y)), reference(x, y, angle_degrees=angle))
        self.assertEqual(fade()(0, 0), 255 * 255 / 256)
        self.assertEqual(fade()(127, 0), 255 / 256)
        for x in range(128):
            self.assertEqual(fade()(x, 17), fade(angle_degrees=90)(17, x))
            self.assertEqual(fade()(x, 17), fade(angle_degrees=180)(127-x, 17))
            self.assertEqual(fade()(x, 17), fade(angle_degrees=270)(17, 127-x))
            self.assertAlmostEqual(fade(angle_degrees=45)(x, 127-x), 127.5)

    def test_linear_narrow_broad_edge_bands(self):
        for low, high in ((0, 1), (.49, .51), (.01, .99), (0, .1), (.9, 1)):
            fn = fade(fade_start_position=low, fade_end_position=high)
            for x in range(128):
                self.assertEqual(_quantize(fn(x, 0)), reference(x, 0, fade_start_position=low, fade_end_position=high))

    def test_radial_geometry_center_aspect_rotation_and_sizes(self):
        for mode in ('circular', 'square'):
            for center in ((.5, .5), (.2, .8), (0, 1)):
                for inner, outer in ((0, .5), (.25, .5), (.5, 1.5)):
                    for ax, ay in ((1, 1), (2, .5)):
                        for angle in (0, 45, 90, 23):
                            p = dict(fade_mode=mode, center_x=center[0], center_y=center[1],
                                     inner_size=inner, outer_size=outer, aspect_x=ax, aspect_y=ay,
                                     rotation_degrees=angle)
                            fn = fade(**p)
                            for x, y in ((0, 0), (63, 63), (12, 81), (100, 127)):
                                self.assertEqual(_quantize(fn(x, y)), reference(x, y, **p), p)

    def test_circle_symmetry_and_exact_rotation_invariance(self):
        for aspect in (1, 1.7):
            p = dict(fade_mode='circular', aspect_x=aspect, aspect_y=aspect)
            a = fade(**p)
            for angle in (0, 45, 90, 31, -360):
                b = fade(**p, rotation_degrees=angle)
                for x, y in ((0, 17), (50, 43), (63, 64), (100, 110)):
                    self.assertEqual(a(x, y), b(x, y))
                    self.assertEqual(a(x, y), a(127-x, y))
                    self.assertEqual(a(x, y), a(y, x))

    def test_ellipse_local_axis_symmetry_clockwise_rotation_and_size_limits(self):
        p = dict(fade_mode='circular', aspect_x=2, aspect_y=.5, inner_size=0, outer_size=1.5)
        fn = fade(**p)
        for x, y in ((63, 63), (90, 75), (117, 60)):
            self.assertEqual(fn(x, y), fn(127-x, y))
            self.assertEqual(fn(x, y), fn(x, 127-y))
            self.assertEqual(fn(x, y), fade(**p, rotation_degrees=90)(127-y, x))
        # Positive 45 degrees stretches along the down-right diagonal.
        rotated = fade(**p, rotation_degrees=45)
        self.assertGreater(rotated(90, 90), rotated(90, 37))
        self.assertNotEqual(rotated(90, 90), fn(90, 90))
        for mode in ('circular', 'square'):
            for aspect in (.1, 10):
                for power in (.1, 10):
                    args = dict(fade_mode=mode, center_x=0, center_y=1, inner_size=0,
                                outer_size=1.5, aspect_x=aspect, aspect_y=aspect, curve_exponent=power)
                    self.assertEqual(_quantize(fade(**args)(17, 96)), reference(17, 96, **args))

    def test_square_chebyshev_rings_and_diamond(self):
        fn = fade(fade_mode='square', inner_size=0, outer_size=1)
        for x in range(64, 128):
            self.assertEqual(fn(x, 63), fn(x, x))
            self.assertEqual(fn(x, 63), fn(63, x))
        diamond = fade(fade_mode='square', rotation_degrees=45, inner_size=0, outer_size=1)
        for x, y in ((63, 64), (80, 92), (110, 110)):
            distance = (abs(x+.5-64) + abs(y+.5-64)) / (64 * math.sqrt(2))
            self.assertAlmostEqual(diamond(x, y), 255 * (1-min(1, distance)))
            self.assertEqual(diamond(x, y), diamond(127-x, y))
        p = dict(fade_mode='square', aspect_x=2, aspect_y=.5)
        for x, y in ((0, 63), (63, 0), (76, 88)):
            self.assertEqual(fade(**p)(x, y), fade(**p, rotation_degrees=90)(127-y, x))

    def test_exact_plateau_outside_and_authored_sample_center(self):
        for mode in ('circular', 'square'):
            for first, last in ((255, 0), (0, 255), (180, 40), (40, 180), (128, 128)):
                fn = fade(fade_mode=mode, center_x=64.5/128, center_y=64.5/128,
                          inner_size=.25, outer_size=.5, start_value=first, end_value=last)
                self.assertEqual(fn(64, 64), first)
                self.assertEqual(fn(80, 64), first)
                self.assertEqual(fn(96, 64), last)
                self.assertEqual(fn(127, 127), last)
            self.assertEqual(fade(fade_mode=mode, inner_size=0, center_x=64.5/128,
                                  center_y=64.5/128)(64, 64), 255)

    def test_curve_exponents_exact_endpoints_and_transition_order(self):
        for mode in ('linear', 'circular', 'square'):
            p = dict(fade_mode=mode, fade_start_position=.25, fade_end_position=.75,
                     center_x=.5/128, center_y=.5/128, inner_size=.25, outer_size=.75)
            point = (63.5, 0) if mode == 'linear' else (32, 0)
            for first, last in ((255, 0), (0, 255), (180, 40), (40, 180)):
                for power in (.5, 1, 2, 4):
                    fn = fade(**p, start_value=first, end_value=last, curve_exponent=power)
                    self.assertAlmostEqual(fn(*point), first + .5**power * (last-first))
                    self.assertEqual(fn(0, 0), first)
                    self.assertEqual(fn(127, 0), last)

    def test_active_validation_and_ignored_controls(self):
        controls = ConditioningLayersFieldFade.INPUT_TYPES()['required']
        linear = ('angle_degrees', 'fade_start_position', 'fade_end_position')
        radial = ('center_x', 'center_y', 'inner_size', 'outer_size', 'aspect_x', 'aspect_y', 'rotation_degrees')
        for mode in ('linear', 'circular', 'square'):
            active = ('start_value', 'end_value', 'curve_exponent') + (linear if mode == 'linear' else radial)
            for name in active:
                meta = controls[name][1]
                invalid = [True, False, None, '1', float('nan'), float('inf'), -float('inf'), meta['min']-1, meta['max']+1]
                if controls[name][0] == 'INT':
                    invalid += [1., 1.5]
                for value in invalid:
                    with self.subTest(mode=mode, name=name, value=value), self.assertRaisesRegex(ValueError, name):
                        fade(fade_mode=mode, **{name: value})
            ignored = radial if mode == 'linear' else linear
            a, b = fade(fade_mode=mode), fade(fade_mode=mode, **dict.fromkeys(ignored, None))
            self.assertEqual([a(x, 73) for x in range(128)], [b(x, 73) for x in range(128)])
        for mode in (None, True, 1, [], 'radial', 'LINEAR'):
            with self.assertRaisesRegex(ValueError, 'fade_mode'):
                fade(fade_mode=mode)

    def test_invalid_equal_and_reversed_regions_fail_even_constant_fades(self):
        for low, high in ((.5, .5), (.75, .25)):
            for value in (0, 255):
                with self.assertRaisesRegex(ValueError, 'fade_start_position < fade_end_position'):
                    fade(start_value=value, end_value=value, fade_start_position=low, fade_end_position=high)
                for mode in ('circular', 'square'):
                    with self.assertRaisesRegex(ValueError, 'inner_size < outer_size'):
                        fade(fade_mode=mode, start_value=value, end_value=value, inner_size=low, outer_size=high)

    def test_half_up_quantization_and_adjacent_binary64_values(self):
        for code in range(255):
            tie = code + .5
            self.assertEqual(_quantize(tie), code+1)
            self.assertEqual(_quantize(math.nextafter(tie, -math.inf)), code)
            self.assertEqual(_quantize(math.nextafter(tie, math.inf)), code+1)
        self.assertEqual(_quantize(-1), 0)
        self.assertEqual(_quantize(256), 255)

    def test_three_full_canvas_goldens_match_independent_decimal_oracle(self):
        for p, expected in GOLDENS:
            fn = fade(**p)
            actual = bytes(_quantize(255 * fn(x, y) / 255) for y in range(128) for x in range(128))
            oracle = bytes(reference(x, y, **p) for y in range(128) for x in range(128))
            self.assertEqual(actual, oracle)
            self.assertEqual(hashlib.sha256(actual).hexdigest(), expected)


if __name__ == '__main__':
    unittest.main()
