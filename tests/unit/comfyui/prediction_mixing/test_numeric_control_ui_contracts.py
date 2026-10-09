"""Project-wide native numeric metadata contracts; developer lane, no browser.

Host behavior and evidence limits: docs/NUMERIC_CONTROL_UI_AUDIT.md.
None in the snapshot means metadata is absent, not a requested default.
Keep this inventory explicit: new nodes/controls require reviewing the UI rule.
"""

import ast
import importlib
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[4]
BASE = 'conditioning_layers.comfyui.'
MODULES = (
    'prediction_mixing.layer_nodes.nodes', 'influence_field_sources',
    'pattern_field_source', 'field_transform', 'field_repeat', 'field_remap',
    'field_blur', 'procedural_field_sources', 'field_fade', 'preset_field_source',
    'prediction_mixing.blend_node', 'prediction_mixing.generalized_blend_node',
    'painted_field_source',
)

# Class suffix -> (control, type, default, min, max, declared step).
# Captured and reviewed against retained da5c606; never regenerated during tests.
EXPECTED = {
    'Layer': [('strength', 'FLOAT', 1., 0., 1., .01)],
    'AddLayer': [], 'Compose': [],
    'SolidField': [('value', 'INT', 255, 0, 255, None)],
    'RectangleField': [
        ('center_x', 'FLOAT', 64., 0., 128., .5),
        ('center_y', 'FLOAT', 64., 0., 128., .5),
        ('width', 'INT', 64, 1, 256, None),
        ('height', 'INT', 64, 1, 256, None),
        ('inside_value', 'INT', 255, 0, 255, None),
        ('outside_value', 'INT', 0, 0, 255, None),
    ],
    'EllipseField': [
        ('center_x', 'FLOAT', 64., 0., 128., .5),
        ('center_y', 'FLOAT', 64., 0., 128., .5),
        ('radius_x', 'FLOAT', 32., .5, 128., .5),
        ('radius_y', 'FLOAT', 32., .5, 128., .5),
        ('inside_value', 'INT', 255, 0, 255, None),
        ('outside_value', 'INT', 0, 0, 255, None),
    ],
    'LinearGradientField': [
        ('start_x', 'FLOAT', .5, 0., 128., .5),
        ('start_y', 'FLOAT', 64., 0., 128., .5),
        ('end_x', 'FLOAT', 127.5, 0., 128., .5),
        ('end_y', 'FLOAT', 64., 0., 128., .5),
        ('start_value', 'INT', 0, 0, 255, None),
        ('end_value', 'INT', 255, 0, 255, None),
    ],
    'RadialGradientField': [
        ('center_x', 'FLOAT', 64., 0., 128., .5),
        ('center_y', 'FLOAT', 64., 0., 128., .5),
        ('radius_x', 'FLOAT', 64., .5, 128., .5),
        ('radius_y', 'FLOAT', 64., .5, 128., .5),
        ('center_value', 'INT', 255, 0, 255, None),
        ('outside_value', 'INT', 0, 0, 255, None),
    ],
    'InvertField': [], 'PatternField': [],
    'FieldTransform': [
        ('uniform_scale', 'FLOAT', 1., .01, 100., .01),
        ('scale_x', 'FLOAT', 1., .01, 100., .01),
        ('scale_y', 'FLOAT', 1., .01, 100., .01),
        ('rotation_degrees', 'FLOAT', 0., -360., 360., 1.),
        ('offset_x', 'FLOAT', 0., -16384., 16384., .5),
        ('offset_y', 'FLOAT', 0., -16384., 16384., .5),
    ],
    'FieldRepeat': [
        ('repeats_x', 'INT', 1, 1, 16, 1),
        ('repeats_y', 'INT', 1, 1, 16, 1),
        ('phase_x', 'INT', 0, -128, 128, 1),
        ('phase_y', 'INT', 0, -128, 128, 1),
    ],
    'FieldRemap': [
        ('input_low', 'INT', 0, 0, 255, 1),
        ('input_high', 'INT', 255, 0, 255, 1),
        ('output_low', 'INT', 0, 0, 255, 1),
        ('output_high', 'INT', 255, 0, 255, 1),
    ],
    'FieldBlur': [('radius', 'INT', 0, 0, 32, 1)],
    'ScatterField': [
        ('seed', 'INT', 0, 0, 4294967295, 1),
        ('grid', 'INT', 8, 1, 32, None),
        ('density_percent', 'INT', 50, 0, 100, None),
        ('jitter_percent', 'INT', 75, 0, 100, None),
        ('radius', 'FLOAT', 5., .5, 32., .5),
        ('radius_variation_percent', 'INT', 25, 0, 100, None),
    ],
    'CyclicPartitionField': [
        ('columns', 'INT', 8, 1, 32, 1), ('rows', 'INT', 8, 1, 32, 1),
        ('members', 'INT', 2, 2, 4, 1), ('shift', 'INT', 1, 0, 3, 1),
    ],
    'VoronoiPartitionField': [
        ('seed', 'INT', 0, 0, 4294967295, 1), ('grid', 'INT', 6, 1, 16, 1),
        ('jitter_percent', 'INT', 100, 0, 100, 1),
        ('members', 'INT', 2, 2, 4, 1), ('member_shift', 'INT', 0, 0, 3, 1),
    ],
    'NoiseField': [
        ('seed', 'INT', 0, 0, 4294967295, 1),
        ('frequency', 'FLOAT', 4., .5, 32., .5),
        ('octaves', 'INT', 4, 1, 6, 1),
        ('persistence', 'FLOAT', .5, 0., 1., .05),
        ('offset_x', 'FLOAT', 0., -128., 128., 1.),
        ('offset_y', 'FLOAT', 0., -128., 128., 1.),
    ],
    'PolarPartitionField': [
        ('center_x', 'FLOAT', .5, 0., 1., .01),
        ('center_y', 'FLOAT', .5, 0., 1., .01),
        ('rings', 'INT', 4, 1, 32, 1), ('sectors', 'INT', 8, 1, 64, 1),
        ('members', 'INT', 2, 2, 4, 1), ('radial_shift', 'INT', 0, 0, 3, 1),
        ('angular_shift', 'INT', 0, 0, 63, 1),
    ],
    'FieldFade': [
        ('start_value', 'INT', 255, 0, 255, 1),
        ('end_value', 'INT', 0, 0, 255, 1),
        ('curve_exponent', 'FLOAT', 1., .1, 10., .1),
        ('angle_degrees', 'FLOAT', 0., -360., 360., 1.),
        ('fade_start_position', 'FLOAT', 0., 0., 1., .01),
        ('fade_end_position', 'FLOAT', 1., 0., 1., .01),
        ('center_x', 'FLOAT', .5, 0., 1., .01),
        ('center_y', 'FLOAT', .5, 0., 1., .01),
        ('inner_size', 'FLOAT', .25, 0., 1.5, .01),
        ('outer_size', 'FLOAT', .5, 0., 1.5, .01),
        ('aspect_x', 'FLOAT', 1., .1, 10., .1),
        ('aspect_y', 'FLOAT', 1., .1, 10., .1),
        ('rotation_degrees', 'FLOAT', 0., -360., 360., 1.),
    ],
    'PresetField': [], 'PaintedField': [], 'NormalizedBlend': [],
    'GeneralizedNormalizedBlend': [('expected_count', 'INT', None, 1, None, None)],
}

EXPLICIT_NUMBER = {
    'CyclicPartitionField', 'VoronoiPartitionField', 'NoiseField',
    'PolarPartitionField', 'FieldFade',
}
SEED_NODES = {'ScatterField', 'VoronoiPartitionField', 'NoiseField'}
# All nonnumeric inputs, including numeric-looking categorical labels and
# hidden host identity. Pin these too so a duplicate custom/COMBO control cannot
# evade the INT/FLOAT inventory above.
EXEMPT = {
    'Layer': {'required': {'conditioning': 'CONDITIONING', 'mask': 'MASK',
                           'mode': ['BLENDED', 'FIXED'], 'enabled': 'BOOLEAN'},
              'hidden': {'unique_id': 'UNIQUE_ID'}},
    'AddLayer': {'required': {'layer': 'CONDITIONING_LAYER'},
                 'optional': {'layers': 'CONDITIONING_LAYER_STACK'}},
    'Compose': {'required': {'layers': 'CONDITIONING_LAYER_STACK'}},
    'InvertField': {'required': {'mask': 'MASK'}},
    'PatternField': {'required': {'asset': 'COMBO'}},
    'FieldTransform': {'required': {'mask': 'MASK', 'flip_horizontal': 'BOOLEAN',
                                    'flip_vertical': 'BOOLEAN'}},
    'FieldRepeat': {'required': {'mask': 'MASK'}},
    'FieldRemap': {'required': {'mask': 'MASK'}},
    'FieldBlur': {'required': {'mask': 'MASK'}},
    'ScatterField': {'required': {'shape': ['disk', 'square', 'diamond']}},
    'VoronoiPartitionField': {'required': {'assignment_mode': ['cyclic', 'hashed']}},
    'PolarPartitionField': {'required': {'assignment_mode': ['radial', 'angular', 'checker', 'spiral']}},
    'FieldFade': {'required': {'mask': 'MASK', 'fade_mode': ['linear', 'circular', 'square']}},
    'PresetField': {'required': {'preset': 'COMBO'}},
    'PaintedField': {'required': {'field': 'STRING'}},  # socketless custom editor; JS controls audited separately.
    'NormalizedBlend': {'required': {'conditioning': 'CONDITIONING'}},
    'GeneralizedNormalizedBlend': {'required': {'conditioning': 'CONDITIONING'}},
}


def nodes():
    result = {}
    for module_name in MODULES:
        module = importlib.import_module(BASE + module_name)
        for name, value in vars(module).items():
            if (isinstance(value, type) and value.__module__ == module.__name__
                    and name.startswith('ConditioningLayers') and hasattr(value, 'INPUT_TYPES')):
                result[name.removeprefix('ConditioningLayers')] = value
    return result


class NumericControlUIContractTests(unittest.TestCase):
    def test_inventory_covers_every_node_declaration_including_internal_nodes(self):
        discovered = set()
        for path in (ROOT / 'src/conditioning_layers').rglob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
            for item in ast.walk(tree):
                if isinstance(item, ast.ClassDef) and any(
                    isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and child.name == 'INPUT_TYPES' for child in item.body
                ):
                    discovered.add(item.name)
        self.assertEqual(discovered, {'ConditioningLayers' + name for name in EXPECTED})
        self.assertEqual(set(nodes()), set(EXPECTED))

    def test_exact_numeric_inventory_types_defaults_ranges_steps_and_metadata(self):
        count = 0
        for suffix, node in nodes().items():
            declared = node.INPUT_TYPES()
            actual = []
            for group, inputs in declared.items():
                for control, spec in inputs.items():
                    if not isinstance(spec, tuple) or spec[0] not in ('INT', 'FLOAT'):
                        continue
                    with self.subTest(node=suffix, control=control):
                        self.assertEqual(group, 'required')
                        self.assertEqual(len(spec), 2)
                        actual.append((control, spec[0], *(spec[1].get(key) for key in
                                      ('default', 'min', 'max', 'step'))))
            # Detect removed, converted, added or redundant parallel numeric controls.
            self.assertEqual(actual, EXPECTED[suffix], suffix)
            count += len(actual)
            for control, kind, default, low, high, step in EXPECTED[suffix]:
                with self.subTest(node=suffix, control=control):
                    options = declared['required'][control][1]
                    expected_options = {key: value for key, value in
                                        zip(('default', 'min', 'max', 'step'),
                                            (default, low, high, step)) if value is not None}
                    if suffix in EXPLICIT_NUMBER:
                        expected_options['display'] = 'number'
                    if suffix in SEED_NODES and control == 'seed':
                        expected_options['control_after_generate'] = False
                    tooltip_expected = not (
                        suffix == 'GeneralizedNormalizedBlend'
                        or (suffix == 'RectangleField' and control in ('width', 'height')))
                    if tooltip_expected:
                        self.assertIsInstance(options.get('tooltip'), str)
                        self.assertTrue(options['tooltip'])
                    else:
                        self.assertNotIn('tooltip', options)
                    # Exact key/value comparison rejects forceInput, custom display,
                    # read-only metadata, rounding overrides and seed randomization.
                    self.assertEqual({k: v for k, v in options.items() if k != 'tooltip'},
                                     expected_options)
                    for key, value in expected_options.items():
                        self.assertIs(type(options[key]), type(value))
                    self.assertIn(options.get('display'), (None, 'number'))
                    self.assertGreater(options.get('step', 1 if kind == 'INT' else .5), 0)
        self.assertEqual(count, 83)  # 82 registered controls + one internal contract.

    def test_seed_controls_keep_explicit_no_post_generation_changes(self):
        for suffix in SEED_NODES:
            with self.subTest(node=suffix):
                spec = nodes()[suffix].INPUT_TYPES()['required']['seed']
                self.assertEqual(spec[0], 'INT')
                self.assertIs(spec[1]['control_after_generate'], False)

    def test_complete_input_inventory_has_no_parallel_or_restrictive_controls(self):
        for suffix, node in nodes().items():
            with self.subTest(node=suffix):
                declared = node.INPUT_TYPES()
                exempt = EXEMPT.get(suffix, {})
                self.assertEqual(set(declared), {'required'} | set(exempt))
                for group, inputs in declared.items():
                    numeric_names = {row[0] for row in EXPECTED[suffix]} if group == 'required' else set()
                    self.assertEqual(set(inputs), numeric_names | set(exempt.get(group, {})))
                    for control, kind in exempt.get(group, {}).items():
                        spec = inputs[control]
                        actual = spec[0] if isinstance(spec, tuple) else spec
                        if kind == 'COMBO':
                            self.assertIsInstance(actual, list)
                            self.assertTrue(actual)
                        else:
                            self.assertEqual(actual, kind)


if __name__ == '__main__':
    unittest.main()
