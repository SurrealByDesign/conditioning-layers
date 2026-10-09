"""Offline exact arithmetic and real retained decoder-path correspondence."""

import ast
from fractions import Fraction
import hashlib
import io
import logging
import math
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui.prediction_mixing.blend_preparation import (
    normalize_sample_codes, recover_sample_code, round_ratio_to_binary32,
)


def reference_round(value):
    """Independent exact rational binary search across all positive unit floats."""
    def f(bits):
        return struct.unpack(">f", struct.pack(">I", bits))[0]
    lower, upper = 0, 0x3f800000
    while lower < upper:
        middle = (lower + upper + 1) // 2
        if Fraction(f(middle)) <= value:
            lower = middle
        else:
            upper = middle - 1
    if Fraction(f(lower)) == value or lower == 0x3f800000:
        return f(lower)
    low_error, high_error = value - Fraction(f(lower)), Fraction(f(lower + 1)) - value
    return f(lower + (high_error < low_error or (high_error == low_error and lower & 1)))


class BlendPreparationTests(unittest.TestCase):
    def test_reference_cases_cover_full_strength_domain(self):
        tiny = float.fromhex('0x0.0000000000001p-1022')
        cases = [
            ((0, 0, 0), (1., 1., 1.)), ((255, 255, 255), (0., 0., 0.)),
            ((1, 0, 0), (tiny, 1., 1.)), ((255, 255, 255), (1., 1., 1.)),
            ((255, 255, 255), (.1, 1., .1)), ((1, 10, 1), (1., 1., 1.)),
            ((1, 1, 1), (1e-37, 1e-37, 1e-37)), ((1, 255, 1), (tiny, tiny, tiny)),
            ((1, 255, 0), (tiny, 1., 1.)), ((255, 1, 1), (1e-37, tiny, .5)),
            ((1, 1, 0), (2.**-149, 1., 0.)), ((1, 1, 0), (2.**-150, 1., 0.)),
        ]
        for codes, strengths in cases:
            with self.subTest(codes=codes, strengths=strengths):
                contributions = tuple(Fraction(code) * Fraction(strength) for code, strength in zip(codes, strengths))
                total = sum(contributions)
                expected = tuple(reference_round(value / total) if total else 0. for value in contributions)
                actual = normalize_sample_codes(codes, strengths)
                self.assertEqual(actual, expected)
                self.assertTrue(all(math.isfinite(value) for value in actual))
                if total:
                    self.assertTrue(any(value > 0 for value in actual))

    def test_support_precedes_underflow_and_solo_is_exact_one(self):
        tiny = math.ulp(0.)
        self.assertEqual((1 / 255) * tiny, 0.)
        self.assertEqual(normalize_sample_codes((1, 0, 0), (tiny, 1., 0.)), (1., 0., 0.))

    def test_zero_support_does_not_divide_or_round(self):
        with patch('conditioning_layers.comfyui.prediction_mixing.blend_preparation.round_ratio_to_binary32_bits', side_effect=AssertionError):
            self.assertEqual(normalize_sample_codes((0, 1, 255), (1., 0., -0.)), (0., 0., 0.))

    def test_order_preserved_without_priority_or_base_term(self):
        codes, strengths = (1, 13, 231), (.2, .7, .1)
        actual = normalize_sample_codes(codes, strengths)
        self.assertEqual(normalize_sample_codes(codes[::-1], strengths[::-1]), actual[::-1])
        self.assertEqual(normalize_sample_codes((13, 231), (.7, .1)), normalize_sample_codes((0, 13, 231), (1., .7, .1))[1:])

    def test_direct_binary32_rounding_not_double_rounding(self):
        for lower_bits in (0, 1, 2, 0x007fffff, 0x00800000, 0x3effffff, 0x3f000000, 0x3f000001, 0x3f7fffff):
            lower = Fraction(struct.unpack('>f', struct.pack('>I', lower_bits))[0])
            upper = Fraction(struct.unpack('>f', struct.pack('>I', lower_bits + 1))[0])
            midpoint = (lower + upper) / 2
            for value in (midpoint, midpoint - (upper-lower) / 2**70, midpoint + (upper-lower) / 2**70):
                self.assertEqual(round_ratio_to_binary32(value.numerator, value.denominator), reference_round(value))
        value = Fraction(1, 2) + Fraction(1, 2**25) + Fraction(1, 2**90)
        self.assertNotEqual(round_ratio_to_binary32(value.numerator, value.denominator), struct.unpack('f', struct.pack('f', float(value)))[0])

    def test_finite_input_and_code_domain_enforced(self):
        for strength in (math.nan, math.inf, -math.inf, -1., 1.1, True, '1'):
            with self.subTest(strength=strength), self.assertRaises(ValueError):
                normalize_sample_codes((1, 1, 1), (strength, 1., 1.))
        for code in (-1, 256, .5, True):
            with self.assertRaises(ValueError):
                normalize_sample_codes((code, 0, 0), (1., 1., 1.))
        for value in (.5, math.nan, math.inf, 1e-37):
            with self.assertRaises(ValueError):
                recover_sample_code(value)

    def test_both_codebooks_jointly_injective_all_256_codes(self):
        observed = {}
        for code in range(256):
            for value in (round_ratio_to_binary32(code, 255), round_ratio_to_binary32(code*256, 65535)):
                self.assertEqual(recover_sample_code(value), code)
                self.assertEqual(observed.setdefault(value, code), code)


class BlendActualDecoderTests(unittest.TestCase):
    """Compile only source-bound decoding classes/methods; never import the host.

    All input files are synthetic local temporary PNGs. ComfyUI server, models,
    registry and sampler are neither imported nor run.
    """

    # Optional exact historical host-source decoder check. No host is launched.
    HOST = None

    def setUp(self):
        import os
        configured = os.environ.get('CONDITIONING_LAYERS_DECODER_HOST')
        if not configured:
            self.skipTest('Set CONDITIONING_LAYERS_DECODER_HOST to the exact anchored ComfyUI 0.37.2 checkout')
        self.HOST = Path(configured)

    def test_load_image_mask_both_real_paths_all_codes_both_encodings(self):
        import av
        import numpy as np
        import torch
        from PIL import Image, ImageOps, ImageSequence

        nodes_source = (self.HOST / 'nodes.py').read_text(encoding='utf-8')
        video_source = (self.HOST / 'comfy_api/latest/_input_impl/video_types.py').read_text(encoding='utf-8')
        # Exact source anchors are separate from the retained eleven-class snapshot.
        # ComfyUI 0.37.2 (830232b); see docs/COMFYUI_0_37_2_HOST_SUPPORT_REFRESH.md.
        self.assertEqual(hashlib.sha256(nodes_source.encode()).hexdigest(), '1af4a41e1d844550a836cf1d1b00fad85d3d0aefaf435743431a8f1598643e22')
        self.assertEqual(hashlib.sha256(video_source.encode()).hexdigest(), 'ca3ab830c3e71706762b03a7b239ce7a198a15abbf78d75de47fb3fb108449b9')
        video_module = ast.parse(video_source)
        video_class = next(item for item in video_module.body if isinstance(item, ast.ClassDef) and item.name == 'VideoFromFile')
        method = next(item for item in video_class.body if isinstance(item, ast.FunctionDef) and item.name == 'get_components_internal')
        rotation = next(item for item in video_module.body if isinstance(item, ast.FunctionDef) and item.name == '_rotation_quadrant')
        decode_namespace = dict(av=av, np=np, torch=torch, Fraction=Fraction, logging=logging,
                                VideoComponents=SimpleNamespace, last_decodable_audio_stream=lambda container: None)
        # The anchored helper is a module global, and compiling under the host class
        # name mangles the private crop attribute exactly as the host does.
        host_class = ast.parse('class VideoFromFile:\n    pass').body[0]
        host_class.body = [method]
        decode_module = ast.parse('from __future__ import annotations')
        decode_module.body += [rotation, host_class]
        exec(compile(ast.fix_missing_locations(decode_module), '<governed-local-video-decode>', 'exec'), decode_namespace)

        class SourceVideo:
            fallback = False
            # LoadImage constructs VideoFromFile(path), whose crop default is None.
            _VideoFromFile__crop = None

            def __init__(self, path):
                self.path = path

            def get_components(self):
                if self.fallback:
                    return SimpleNamespace(images=torch.zeros((0, 128, 128, 3)))
                with av.open(self.path, mode='r') as container:
                    return decode_namespace['VideoFromFile'].get_components_internal(self, container)

            def _get_first_video_stream(self, container):
                return container.streams.video[0]

            def get_active_trim_window(self):
                return 0., 0.

        selected = [item for item in ast.parse(nodes_source).body if isinstance(item, ast.ClassDef) and item.name in ('LoadImage', 'LoadImageMask')]
        namespace = dict(torch=torch, np=np, Image=Image, ImageOps=ImageOps, ImageSequence=ImageSequence,
                         InputImpl=SimpleNamespace(VideoFromFile=SourceVideo),
                         comfy=SimpleNamespace(model_management=SimpleNamespace(intermediate_dtype=lambda: torch.float32, intermediate_device=lambda: torch.device('cpu'))),
                         folder_paths=SimpleNamespace(get_annotated_filepath=lambda path: path),
                         node_helpers=SimpleNamespace(pillow=lambda function, *args: function(*args)))
        exec(compile(ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])), '<governed-local-mask-decode>', 'exec'), namespace)
        values = np.tile(np.arange(256, dtype=np.uint8), 64).reshape(128, 128)
        with tempfile.TemporaryDirectory(prefix='cl-p3c-decode-') as directory:
            for mode in ('L', 'RGB'):
                path = str(Path(directory) / (mode + '.png'))
                source_image = Image.fromarray(values if mode == 'L' else np.repeat(values[..., None], 3, axis=-1))
                source_image.save(path)
                for fallback in (False, True):
                    SourceVideo.fallback = fallback
                    mask, = namespace['LoadImageMask']().load_image_mask(path, 'red')
                    recovered = [recover_sample_code(value) for value in mask.reshape(-1).tolist()]
                    with self.subTest(mode=mode, fallback=fallback):
                        self.assertEqual(recovered, values.reshape(-1).tolist())
                        self.assertEqual(mask.dtype, torch.float32)
                        self.assertEqual(tuple(mask.shape), (1, 128, 128))


if __name__ == '__main__':
    unittest.main()
