"""Portable group semantics against an independent Fraction/IEEE-754 """
from dataclasses import dataclass, replace
from fractions import Fraction as Q
from functools import lru_cache
import random
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui.prediction_mixing.layer_nodes.models import LayerDescriptor, LayerMode, LayerStack
from conditioning_layers.comfyui.prediction_mixing.layer_nodes.composition import compose_field_codes
from conditioning_layers.comfyui.prediction_mixing.layer_nodes.grouped_composition import compose_grouped_field_codes
from conditioning_layers.comfyui.prediction_mixing.layer_nodes.nodes import ConditioningLayersLayer

TINY = float.fromhex("0x0.0000000000001p-1022")


@dataclass(frozen=True)
class ReferenceLayer:
    identity: str
    codes: tuple
    strength: float = 1.0
    mode: LayerMode = LayerMode.BLENDED
    enabled: bool = True
    group: str = ""


@lru_cache(maxsize=8192)
def value(bits):
    exponent, mantissa = bits >> 23, bits & 0x7fffff
    return Q(mantissa, 2**149) if exponent == 0 else Q(2**23 + mantissa) * Q(2)**(exponent - 150)


def reference_bits(number):
    """Find adjacent floats and round ties to even, without production helpers."""
    number = Q(number)
    assert 0 <= number <= 1
    low, high = 0, 0x3f800000
    while low < high:
        mid = (low + high + 1) // 2
        if value(mid) <= number:
            low = mid
        else:
            high = mid - 1
    if value(low) == number:
        return low
    below, above = number - value(low), value(low + 1) - number
    return low if below < above or (below == above and low % 2 == 0) else low + 1


def reference(layers, rule="strongest"):
    active = [layer for layer in layers if layer.enabled]
    result = [[] for _ in active]
    for p in range(len(active[0].codes)):
        owners = [i for i, layer in enumerate(active) if layer.mode is LayerMode.FIXED and layer.codes[p] > 0]
        if len(owners) > 1:
            raise ValueError("FIXED overlap")
        weights = [Q(0)] * len(active)
        if owners:
            weights[owners[0]] = Q(active[owners[0]].strength > 0)
        else:
            products = [Q(layer.codes[p], 255) * Q(layer.strength) for layer in active]
            groups = {}
            for i, layer in enumerate(active):
                if layer.mode is LayerMode.BLENDED:
                    key = "" if rule == "flat" else layer.group
                    groups.setdefault(key, []).append(i)
            groups = [members for members in groups.values() if sum(products[i] for i in members) > 0]
            envelopes = [max(products[i] for i in members) for members in groups]
            for members, envelope in zip(groups, envelopes):
                total = sum(products[i] for i in members)
                share = envelope / sum(envelopes)
                for i in members:
                    weights[i] = share * products[i] / total
        for row, weight in zip(result, weights):
            row.append(reference_bits(weight))
    return tuple(tuple(row) for row in result)


def scalar(codes, groups, strengths=None):
    strengths = strengths or [1.0] * len(codes)
    return tuple(ReferenceLayer(str(i), (code,), s, group=g)
                 for i, (code, g, s) in enumerate(zip(codes, groups, strengths)))


def promoted(layers):
    active = tuple(layer for layer in layers if layer.enabled)
    return compose_grouped_field_codes(tuple(l.codes for l in active), tuple(l.strength for l in active),
                                      tuple(l.mode for l in active), tuple(l.group or "" for l in active),
                                      tuple(l.identity for l in active))


class SelectiveGroupMathTests(unittest.TestCase):
    def test_unequal_group_sizes_have_known_exact_shares(self):
        layers = scalar((255,) * 5, ("a", "a", "a", "b", "b"))
        expected = ((0x3e2aaaab,),) * 3 + ((0x3e800000,),) * 2
        self.assertEqual(promoted(layers), expected)
        self.assertEqual(promoted(layers), reference(layers))
        weaker = scalar((255, 255, 255), ("a", "a", "b"), (.5, .5, 1.))
        self.assertEqual(promoted(weaker), ((0x3e2aaaab,), (0x3e2aaaab,), (0x3f2aaaab,)))

    def test_independent_reference_extremes_and_mixed_fixed(self):
        rng = random.Random(3701)
        for trial in range(80):
            count = rng.randrange(2, 13)
            layers = tuple(ReferenceLayer(str(i), (255,) + tuple(rng.randrange(256) for _ in range(7)),
                                           rng.choice((0., TINY, 1e-37, 2**-149, .1, 1.)),
                                           group=str(rng.randrange(4))) for i in range(count))
            fixed = ReferenceLayer("fixed", (0, 1, 0, 0, 0, 0, 0, 1),
                                     rng.choice((0., TINY, 1.)), LayerMode.FIXED, group="elsewhere")
            for sample in (layers, layers + (fixed,)):
                self.assertEqual(promoted(sample), reference(sample, "strongest"))

    def test_missing_and_single_group_delegate_bit_identically(self):
        rng = random.Random(3702)
        for count in (1, 2, 3, 9, 12, 40):
            planes = tuple(tuple(rng.randrange(256) for _ in range(32)) for _ in range(count))
            strengths = tuple((0., TINY, 1e-37, .1, .5, 1.)[i % 6] for i in range(count))
            modes = (LayerMode.BLENDED,) * count
            expected = compose_field_codes(planes, strengths, modes)
            for groups in (None, ("",) * count, ("one",) * count):
                with patch("conditioning_layers.comfyui.prediction_mixing.layer_nodes.grouped_composition.compose_field_codes",
                           wraps=compose_field_codes) as retained:
                    self.assertEqual(compose_grouped_field_codes(planes, strengths, modes, groups), expected)
                    retained.assert_called_once()

    def test_fixed_conflicts_strength_zero_and_invalid_suppressed_data(self):
        modes = (LayerMode.FIXED, LayerMode.FIXED, LayerMode.BLENDED, LayerMode.BLENDED)
        with self.assertRaisesRegex(ValueError, "A.*B"):
            compose_grouped_field_codes(((1,), (255,), (1,), (1,)), (0., 0., 1., 1.), modes,
                                        ("x", "y", "x", "y"), ("A", "B", "C", "D"))
        for invalid in ((0, 0), (256, 1), (True, 1), (.5, 1), ()):
            with self.assertRaises(ValueError):
                compose_grouped_field_codes(((255, 255), invalid, (1, 1)), (0., 1., 1.),
                                            (LayerMode.FIXED, LayerMode.BLENDED, LayerMode.BLENDED), ("", "a", "b"))

    def test_zero_local_support_singletons_and_order(self):
        layers = (ReferenceLayer("a", (255, 255, 0, 0), group="a"),
                  ReferenceLayer("b", (0, 128, 255, 0), group="b"))
        self.assertEqual(promoted(layers), reference(layers, "flat"))
        self.assertEqual(promoted(tuple(reversed(layers))), tuple(reversed(promoted(layers))))
        self.assertEqual(tuple(row[-1] for row in promoted(layers)), (0, 0))

    def test_nondominant_addition_and_strongest_coupling(self):
        base = scalar((200, 100), ("a", "b"))
        extended = base + (ReferenceLayer("detail", (50,), group="a"),)
        self.assertEqual(promoted(base)[1], promoted(extended)[1])
        low = scalar((255, 255, 255), ("a", "a", "b"), (.5, .5, 1.))
        high = tuple(replace(l, strength=.75) if l.identity == "1" else l for l in low)
        self.assertGreater(promoted(high)[0][0], promoted(low)[0][0])
        self.assertEqual(promoted(high), reference(high, "strongest"))

    def test_only_final_rounding_matches_independent_witnesses(self):
        rng = random.Random(153)
        witnesses = 0
        for _ in range(200):
            a, b, c = [rng.randrange(1, 256) for _ in range(3)]
            r, q = Q(a, a+b), Q(max(a,b), max(a,b)+c)
            exact = reference_bits(r*q)
            staged = reference_bits(value(reference_bits(r))*value(reference_bits(q)))
            if exact != staged:
                self.assertEqual(promoted(scalar((a,b,c), ("a","a","b")))[0][0], exact)
                witnesses += 1
        self.assertGreater(witnesses, 0)

    def test_group_and_shape_validation(self):
        for groups in ((None, "b"), (["a", "b"], "c"), (("a",), "b"), (" ", "b"), (" a", "b"), ("a",)):
            with self.assertRaises(ValueError):
                compose_grouped_field_codes(((255,), (128,)), (1., 1.), (LayerMode.BLENDED,)*2, groups)
        with self.assertRaises(ValueError):
            compose_grouped_field_codes((), (), ())


class SelectiveGroupDescriptorTests(unittest.TestCase):
    def test_optional_widget_is_appended_and_default_is_old_behavior(self):
        inputs = ConditioningLayersLayer.INPUT_TYPES()
        widgets = [name for section in ("required", "optional") for name, spec in inputs[section].items()
                   if spec[0] in ("FLOAT", "BOOLEAN", "STRING") or isinstance(spec[0], list)]
        self.assertEqual(widgets, ["strength", "mode", "enabled", "blend_group"])
        node = ConditioningLayersLayer()
        old = node.create(object(), object(), 1., "BLENDED", False, unique_id="1")[0]
        explicit = node.create(object(), object(), 1., "BLENDED", False, unique_id="2", blend_group="Group 1")[0]
        self.assertEqual((old.blend_group, explicit.blend_group), ("", "Group 1"))

    def test_membership_is_one_literal_key_not_identity_or_hierarchy(self):
        for invalid in (None, 1, True, ["a", "b"], {"group": "a"}, ("a",), " ", "a "):
            with self.assertRaises(ValueError):
                LayerDescriptor("1", None, None, 1., LayerMode.BLENDED, False, invalid)
        a = LayerDescriptor("a", None, None, 1., LayerMode.BLENDED, False, "Group 1")
        b = replace(a, layer_id="b")
        self.assertEqual(len(LayerStack((a,b)).layers), 2)
        with self.assertRaisesRegex(ValueError, "already"):
            LayerStack((a, replace(a, blend_group="Group 2")))
