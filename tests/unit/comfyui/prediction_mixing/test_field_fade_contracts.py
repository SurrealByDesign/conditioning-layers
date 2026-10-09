"""Field Fade surface and isolated optional registration; developer lane."""

import builtins
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui import field_fade as fades
from conditioning_layers.comfyui.preset_field_source import PRESET_FIELD_NODE_CLASS_NAMES
from conditioning_layers.comfyui.painted_field_source import PAINTED_FIELD_NODE_CLASS_NAMES
from conditioning_layers.comfyui import field_blur, field_remap, field_repeat, field_transform
from conditioning_layers.comfyui import influence_field_sources, pattern_field_source, procedural_field_sources
from conditioning_layers.comfyui.prediction_mixing import blend_component, layer_nodes
from conditioning_layers.integrations import blend_readiness
from conditioning_layers.integrations.comfyui_panel import routes


ROOT = Path(__file__).resolve().parents[4]
REGISTRATIONS = (
    (layer_nodes, 'initialize_layer_node_registration', layer_nodes.LAYER_NODE_CLASS_NAMES),
    (influence_field_sources, 'initialize_field_source_node_registration', influence_field_sources.FIELD_SOURCE_NODE_CLASS_NAMES),
    (pattern_field_source, 'initialize_pattern_field_node_registration', pattern_field_source.PATTERN_FIELD_NODE_CLASS_NAMES),
    (field_transform, 'initialize_field_transform_node_registration', field_transform.FIELD_TRANSFORM_NODE_CLASS_NAMES),
    (field_repeat, 'initialize_field_repeat_node_registration', field_repeat.FIELD_REPEAT_NODE_CLASS_NAMES),
    (field_remap, 'initialize_field_remap_node_registration', field_remap.FIELD_REMAP_NODE_CLASS_NAMES),
    (field_blur, 'initialize_field_blur_node_registration', field_blur.FIELD_BLUR_NODE_CLASS_NAMES),
    (procedural_field_sources, 'initialize_procedural_field_node_registration', procedural_field_sources.PROCEDURAL_FIELD_NODE_CLASS_NAMES),
)
PREFIX = ('ConditioningLayersNormalizedBlend',) + sum((r[2] for r in REGISTRATIONS), ())


class FadeContractTests(unittest.TestCase):
    def test_surface_exact_control_order_defaults_ranges_steps_and_number_widgets(self):
        node = fades.ConditioningLayersFieldFade
        self.assertEqual(node.RETURN_TYPES, ('MASK',))
        self.assertEqual(node.RETURN_NAMES, ('mask',))
        self.assertEqual(node.FUNCTION, 'apply')
        self.assertEqual(node.CATEGORY, 'conditioning/conditioning_layers/fields')
        specs = (
            ('start_value', 'INT', 255, 0, 255, 1), ('end_value', 'INT', 0, 0, 255, 1),
            ('curve_exponent', 'FLOAT', 1., .1, 10., .1),
            ('angle_degrees', 'FLOAT', 0., -360., 360., 1.),
            ('fade_start_position', 'FLOAT', 0., 0., 1., .01),
            ('fade_end_position', 'FLOAT', 1., 0., 1., .01),
            ('center_x', 'FLOAT', .5, 0., 1., .01), ('center_y', 'FLOAT', .5, 0., 1., .01),
            ('inner_size', 'FLOAT', .25, 0., 1.5, .01), ('outer_size', 'FLOAT', .5, 0., 1.5, .01),
            ('aspect_x', 'FLOAT', 1., .1, 10., .1), ('aspect_y', 'FLOAT', 1., .1, 10., .1),
            ('rotation_degrees', 'FLOAT', 0., -360., 360., 1.),
        )
        inputs = node.INPUT_TYPES()
        self.assertEqual(tuple(inputs), ('required',))
        controls = inputs['required']
        self.assertEqual(tuple(controls), ('mask', 'fade_mode') + tuple(s[0] for s in specs))
        self.assertEqual(controls['mask'][0], 'MASK')
        self.assertEqual(controls['fade_mode'], (['linear', 'circular', 'square'], {'default': 'linear'}))
        for name, kind, *values in specs:
            self.assertEqual(controls[name][0], kind)
            self.assertEqual([controls[name][1][k] for k in ('default', 'min', 'max', 'step')], values)
            self.assertEqual(controls[name][1]['display'], 'number')
            self.assertTrue(controls[name][1]['tooltip'])

    def test_registration_returns_fresh_mappings(self):
        a, b = fades.initialize_field_fade_node_registration()
        self.assertEqual(tuple(a), ('ConditioningLayersFieldFade',))
        self.assertIs(a['ConditioningLayersFieldFade'], fades.ConditioningLayersFieldFade)
        self.assertEqual(b, {'ConditioningLayersFieldFade': 'Field Fade'})
        a.clear()
        b.clear()
        self.assertTrue(fades.initialize_field_fade_node_registration()[0])
        self.assertTrue(fades.initialize_field_fade_node_registration()[1])

    def load_root(self, failure=None, upstream=False):
        ns = {'__file__': str(ROOT / '__init__.py'), '__name__': '_fade_root'}
        original = builtins.__import__

        def controlled(name, *args, **kwargs):
            if failure == 'import' and name == fades.__name__:
                raise ImportError('offline')
            return original(name, *args, **kwargs)

        with ExitStack() as stack:
            stack.enter_context(patch.dict('os.environ', {}, clear=True))
            stack.enter_context(patch('builtins.__import__', side_effect=controlled))
            routes_mock = stack.enter_context(patch.object(routes, 'register_routes'))
            ready = stack.enter_context(patch.object(blend_readiness, 'register_readiness_route'))
            stack.enter_context(patch.object(blend_component, 'initialize_blend_node_registration',
                return_value=({'ConditioningLayersNormalizedBlend': object}, None),
                side_effect=ImportError('offline') if upstream else None))
            if upstream:
                for module, function, _ in REGISTRATIONS:
                    stack.enter_context(patch.object(module, function, side_effect=ImportError('offline')))
            if failure == 'init':
                stack.enter_context(patch.object(fades, 'initialize_field_fade_node_registration', side_effect=RuntimeError('offline')))
            if failure == 'collision':
                stack.enter_context(patch.object(fades, 'initialize_field_fade_node_registration',
                                                return_value=({'ConditioningLayersFieldBlur': object}, {})))
            stack.enter_context(patch.object(pattern_field_source, 'pattern_registry', side_effect=AssertionError('no assets')))
            exec(compile((ROOT / '__init__.py').read_text(encoding='utf-8'), '__init__.py', 'exec'), ns)
        routes_mock.assert_called_once_with()
        ready.assert_called_once_with(None)
        return ns

    def test_registration_and_upstream_failure_independence(self):
        for upstream in (False, True):
            ns = self.load_root(upstream=upstream)
            expected = (() if upstream else PREFIX) + fades.FIELD_FADE_NODE_CLASS_NAMES + PRESET_FIELD_NODE_CLASS_NAMES + PAINTED_FIELD_NODE_CLASS_NAMES
            self.assertEqual(tuple(ns['NODE_CLASS_MAPPINGS']), expected)
            self.assertEqual(tuple(ns['NODE_DISPLAY_NAME_MAPPINGS']), expected)
            self.assertIsNone(ns['FIELD_FADE_REGISTRATION_ERROR'])

    def test_import_initialization_and_collision_failures_preserve_other_nodes(self):
        for failure in ('import', 'init', 'collision'):
            ns = self.load_root(failure=failure)
            self.assertEqual(tuple(ns['NODE_CLASS_MAPPINGS']), PREFIX + PRESET_FIELD_NODE_CLASS_NAMES + PAINTED_FIELD_NODE_CLASS_NAMES)
            self.assertEqual(tuple(ns['NODE_DISPLAY_NAME_MAPPINGS']), PREFIX + PRESET_FIELD_NODE_CLASS_NAMES + PAINTED_FIELD_NODE_CLASS_NAMES)
            self.assertIsNotNone(ns['FIELD_FADE_REGISTRATION_ERROR'])
            for name in ('BLEND', 'BLEND_READINESS', 'LAYER_NODE', 'FIELD_SOURCE', 'PATTERN_FIELD',
                         'FIELD_TRANSFORM', 'FIELD_REPEAT', 'FIELD_REMAP', 'FIELD_BLUR', 'PROCEDURAL_FIELD'):
                self.assertIsNone(ns[name + '_REGISTRATION_ERROR'])

    def test_fresh_process_import_and_widgets_need_no_runtime_files_or_consumers(self):
        source = '''
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
with ExitStack() as stack:
    for target in ('builtins.open', 'io.open', 'os.open'):
        stack.enter_context(patch(target, side_effect=AssertionError('no file IO')))
    from conditioning_layers.comfyui.field_fade import ConditioningLayersFieldFade, initialize_field_fade_node_registration
    assert initialize_field_fade_node_registration()[0]
    assert len(ConditioningLayersFieldFade.INPUT_TYPES()['required']) == 15
for name in ('torch', 'numpy', 'PIL', 'av', 'comfy', 'nodes', 'server'):
    assert name not in sys.modules, name
assert not [n for n in sys.modules if 'layer_nodes' in n or 'comfyui_panel' in n
    or 'generalized_blend' in n or 'field_transform' in n or 'field_blur' in n
    or 'pattern_field_source' in n or n.endswith('capabilities.product')]
'''
        result = subprocess.run([sys.executable, '-B', '-W', 'error', '-c', source],
                                capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
