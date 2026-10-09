"""Preset manifest rejection, deterministic selectors and isolated registration."""

import builtins
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

from conditioning_layers.comfyui import preset_field_source as presets
from conditioning_layers.comfyui.painted_field_source import PAINTED_FIELD_NODE_CLASS_NAMES
from conditioning_layers.comfyui import field_fade
from conditioning_layers.comfyui.prediction_mixing import blend_component
from conditioning_layers.integrations import blend_readiness
from conditioning_layers.integrations.comfyui_panel import routes
from test_field_fade_contracts import REGISTRATIONS, PREFIX
from test_preset_field_library import ROOT, LIBRARY, LABELS, IDS, manifest


class PresetContractTests(unittest.TestCase):
    def test_node_surface_and_fresh_registration(self):
        mappings, names = presets.initialize_preset_field_node_registration()
        self.assertEqual(tuple(mappings), ("ConditioningLayersPresetField",))
        self.assertEqual(names, {"ConditioningLayersPresetField": "Preset Field"})
        node = mappings["ConditioningLayersPresetField"]
        self.assertEqual((node.CATEGORY, node.FUNCTION, node.RETURN_TYPES, node.RETURN_NAMES),
                         ("conditioning/conditioning_layers/fields", "load", ("MASK",), ("mask",)))
        with patch.object(Path, "iterdir", side_effect=AssertionError("no discovery")), \
                patch.object(Path, "glob", side_effect=AssertionError("no discovery")):
            self.assertEqual(node.INPUT_TYPES()["required"]["preset"][0], list(LABELS))
            self.assertEqual(tuple(node.INPUT_TYPES()["required"]), ("preset",))
        mappings.clear()
        names.clear()
        self.assertTrue(presets.initialize_preset_field_node_registration()[0])
        self.assertTrue(presets.initialize_preset_field_node_registration()[1])

    def library(self, stack):
        directory = stack.enter_context(tempfile.TemporaryDirectory())
        root = Path(directory) / "presets"
        shutil.copytree(LIBRARY, root)
        stack.enter_context(patch.object(presets, "PRESET_FIELD_ROOT", root))
        return root

    def test_manifest_array_authority_polarity_order_and_unlisted_files(self):
        with ExitStack() as stack:
            root = self.library(stack)
            (root / "qr/unlisted.png").write_bytes((root / "qr/qr-code-dark.png").read_bytes())
            m = manifest()
            m["presets"].reverse()
            for p in m["presets"]:
                p["assets"] = dict(reversed(list(p["assets"].items())))
            (root / "preset-fields-manifest.json").write_text(json.dumps(m))
            self.assertEqual(tuple(presets.preset_registry()), LABELS[2:] + LABELS[:2])
            self.assertEqual(tuple(a["id"] for a in presets.preset_registry().values()), IDS[2:] + IDS[:2])

    def test_unknown_selection_cannot_expose_documents_data_or_arbitrary_files(self):
        for name in ("README.md", "preset-fields-manifest.json", "generator/generate_presets.py",
                     "qr/qr-code-matrix.json", "qr/unlisted.png", "../outside.png", None, []):
            with self.subTest(name=name), patch.object(presets, "codes_to_mask", side_effect=AssertionError("no runtime")), \
                    self.assertRaisesRegex(ValueError, "unknown preset"):
                presets.ConditioningLayersPresetField().load(name)

    def test_missing_and_malformed_manifest_fail_closed(self):
        with ExitStack() as stack:
            root = self.library(stack)
            path = root / "preset-fields-manifest.json"
            path.unlink()
            with self.assertRaises(ValueError):
                presets.preset_registry()
            for value in ("{", "null", "[]", "{}"):
                path.write_text(value)
                with self.subTest(value=value), self.assertRaises(ValueError):
                    presets.ConditioningLayersPresetField.INPUT_TYPES()

    def test_invalid_profile_duplicate_ids_names_paths_and_traversal(self):
        with ExitStack() as stack:
            root = self.library(stack)
            cases = (("width", 256), ("height", 64), ("bit_depth", 16), ("alpha", True),
                     ("field_type", "grayscale"), ("channel_mode", "rgb-8"), ("version", 2),
                     ("support_status", "validated-product-asset"), ("category", "glyph"))
            for key, value in cases:
                m = manifest(); m["presets"][0][key] = value
                (root / "preset-fields-manifest.json").write_text(json.dumps(m))
                with self.subTest(key=key), self.assertRaises(ValueError):
                    presets.preset_registry()
            for key, value in (("id", IDS[1]), ("display_name", LABELS[1]), ("sha256", "bad"),
                               ("path", "../outside.png"), ("path", "C:/outside.png"),
                               ("path", "qr/../../outside.png"), ("path", "qr\\outside.png"),
                               ("path", "qr/qr-code-light.png")):
                m = manifest(); m["presets"][0]["assets"]["dark"][key] = value
                (root / "preset-fields-manifest.json").write_text(json.dumps(m))
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    presets.preset_registry()
            m = manifest(); m["presets"].append(m["presets"][0])
            (root / "preset-fields-manifest.json").write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError, "duplicate preset ID"):
                presets.preset_registry()

    def test_resolved_symlink_escape_rejected_before_asset_io(self):
        actual_resolve = Path.resolve
        root = LIBRARY.resolve()
        def resolve(path, *args, **kwargs):
            if path.name == "qr-code-dark.png":
                return root.parent / "outside.png"
            return actual_resolve(path, *args, **kwargs)
        with patch.object(Path, "resolve", resolve), \
                patch.object(presets, "inspect_png_bytes", side_effect=AssertionError("no escaped read")), \
                self.assertRaisesRegex(ValueError, "escapes library"):
            presets.preset_registry()

    def test_missing_corrupt_changed_assets_and_cache_revalidation(self):
        with ExitStack() as stack:
            root = self.library(stack)
            path = root / "qr/qr-code-dark.png"
            original = path.read_bytes()
            path.unlink()
            for call in (presets.preset_registry, presets.ConditioningLayersPresetField.INPUT_TYPES):
                with self.assertRaises(ValueError):
                    call()
            for data in (b"not PNG", original[:-12], (root / "qr/qr-code-light.png").read_bytes()):
                path.write_bytes(data)
                for call in (presets.ConditioningLayersPresetField().load, presets.ConditioningLayersPresetField.IS_CHANGED):
                    with self.assertRaises(ValueError):
                        call(LABELS[0])
                self.assertEqual(path.read_bytes(), data)

    def test_incompatible_image_types_and_nonbinary_codes_even_with_matching_hash(self):
        def png(w, h, depth, color, code):
            channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
            def chunk(kind, data):
                return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
            return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, depth, color, 0, 0, 0))
                    + chunk(b"IDAT", zlib.compress((b"\0" + bytes([code]) * w * channels * (depth // 8)) * h))
                    + chunk(b"IEND", b""))
        with ExitStack() as stack:
            root = self.library(stack)
            for args in ((64,128,8,0,255), (128,128,8,2,255), (128,128,8,6,255),
                         (128,128,8,4,255), (128,128,8,3,255), (128,128,16,0,255),
                         (128,128,8,0,127), (128,128,8,0,0)):
                m = manifest(); asset = m["presets"][0]["assets"]["dark"]
                data = png(*args)
                (root / asset["path"]).write_bytes(data)
                asset["sha256"] = hashlib.sha256(data).hexdigest()
                (root / "preset-fields-manifest.json").write_text(json.dumps(m))
                with self.subTest(args=args), self.assertRaises(ValueError):
                    presets.preset_registry()

    def test_noncomplement_pair_rejected_even_with_valid_hashes(self):
        with ExitStack() as stack:
            root = self.library(stack)
            m = manifest(); dark, light = m["presets"][0]["assets"].values()
            (root / light["path"]).write_bytes((root / dark["path"]).read_bytes())
            light["sha256"] = dark["sha256"]
            (root / "preset-fields-manifest.json").write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError, "exact complements"):
                presets.preset_registry()

    def load_root(self, failure=None, upstream=False):
        ns = {"__file__": str(ROOT / "__init__.py"), "__name__": "_preset_root"}
        original = builtins.__import__
        def controlled(name, *args, **kwargs):
            if failure == "import" and name == presets.__name__:
                raise ImportError("offline")
            return original(name, *args, **kwargs)
        with ExitStack() as stack:
            stack.enter_context(patch.dict("os.environ", {}, clear=True))
            stack.enter_context(patch("builtins.__import__", side_effect=controlled))
            register = stack.enter_context(patch.object(routes, "register_routes"))
            ready = stack.enter_context(patch.object(blend_readiness, "register_readiness_route"))
            stack.enter_context(patch.object(blend_component, "initialize_blend_node_registration",
                return_value=({"ConditioningLayersNormalizedBlend": object}, None),
                side_effect=ImportError("offline") if upstream else None))
            if upstream:
                for module, function, _ in REGISTRATIONS + ((field_fade, "initialize_field_fade_node_registration", ()),):
                    stack.enter_context(patch.object(module, function, side_effect=ImportError("offline")))
            if failure == "init":
                stack.enter_context(patch.object(presets, "initialize_preset_field_node_registration", side_effect=RuntimeError("offline")))
            if failure == "collision":
                stack.enter_context(patch.object(presets, "initialize_preset_field_node_registration",
                                                return_value=({"ConditioningLayersPatternField": object}, {})))
            stack.enter_context(patch.object(presets, "preset_registry", side_effect=AssertionError("no registration asset IO")))
            exec(compile((ROOT / "__init__.py").read_text(encoding="utf-8"), "__init__.py", "exec"), ns)
        register.assert_called_once_with()
        ready.assert_called_once_with(None)
        return ns

    def test_registration_independent_of_all_upstream_failures(self):
        for upstream in (False, True):
            ns = self.load_root(upstream=upstream)
            expected = (() if upstream else PREFIX + field_fade.FIELD_FADE_NODE_CLASS_NAMES) + presets.PRESET_FIELD_NODE_CLASS_NAMES + PAINTED_FIELD_NODE_CLASS_NAMES
            self.assertEqual(tuple(ns["NODE_CLASS_MAPPINGS"]), expected)
            self.assertEqual(tuple(ns["NODE_DISPLAY_NAME_MAPPINGS"]), expected)
            self.assertIsNone(ns["PRESET_FIELD_REGISTRATION_ERROR"])

    def test_import_initialization_collision_preserve_other_registrations(self):
        for failure in ("import", "init", "collision"):
            ns = self.load_root(failure=failure)
            self.assertEqual(tuple(ns["NODE_CLASS_MAPPINGS"]), PREFIX + field_fade.FIELD_FADE_NODE_CLASS_NAMES + PAINTED_FIELD_NODE_CLASS_NAMES)
            self.assertEqual(tuple(ns["NODE_DISPLAY_NAME_MAPPINGS"]), PREFIX + field_fade.FIELD_FADE_NODE_CLASS_NAMES + PAINTED_FIELD_NODE_CLASS_NAMES)
            self.assertIsNotNone(ns["PRESET_FIELD_REGISTRATION_ERROR"])

    def test_fresh_import_and_selector_have_no_runtime_or_consumer_dependency(self):
        source = '''
import sys
from unittest.mock import patch
from conditioning_layers.comfyui.preset_field_source import (
    ConditioningLayersPresetField, initialize_preset_field_node_registration)
with patch('pathlib.Path.read_text', side_effect=AssertionError('registration does not read')):
    assert initialize_preset_field_node_registration()[0]
assert len(ConditioningLayersPresetField.INPUT_TYPES()['required']['preset'][0]) == 4
for name in ('torch', 'numpy', 'PIL', 'cv2', 'qrcodegen', 'av', 'comfy', 'nodes', 'server'):
    assert name not in sys.modules, name
assert not [n for n in sys.modules if 'layer_nodes' in n or 'comfyui_panel' in n
            or 'generalized_blend' in n or n.endswith('capabilities.product')]
'''
        result = subprocess.run([sys.executable, "-B", "-W", "error", "-c", source],
                                capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
