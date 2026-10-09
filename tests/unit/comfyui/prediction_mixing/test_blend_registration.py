"""Optional Blend registration cannot prevent retained sidebar registration."""

import builtins
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from conditioning_layers.comfyui.prediction_mixing import blend_component
from conditioning_layers.integrations.comfyui_panel import routes
from conditioning_layers.comfyui.prediction_mixing.multi_layer.authority import EXACT_THREE_REALIZATION
from conditioning_layers.comfyui.influence_field_sources import FIELD_SOURCE_NODE_CLASS_NAMES
from conditioning_layers.comfyui.field_transform import FIELD_TRANSFORM_NODE_CLASS_NAMES
from conditioning_layers.comfyui.field_repeat import FIELD_REPEAT_NODE_CLASS_NAMES
from conditioning_layers.comfyui.field_remap import FIELD_REMAP_NODE_CLASS_NAMES
from conditioning_layers.comfyui.field_blur import FIELD_BLUR_NODE_CLASS_NAMES
from conditioning_layers.comfyui.procedural_field_sources import PROCEDURAL_FIELD_NODE_CLASS_NAMES
from conditioning_layers.comfyui.field_fade import FIELD_FADE_NODE_CLASS_NAMES
from conditioning_layers.comfyui.preset_field_source import PRESET_FIELD_NODE_CLASS_NAMES
from conditioning_layers.comfyui.painted_field_source import PAINTED_FIELD_NODE_CLASS_NAMES
from conditioning_layers.comfyui.pattern_field_source import PATTERN_FIELD_NODE_CLASS_NAMES
from conditioning_layers.comfyui.prediction_mixing.layer_nodes import LAYER_NODE_CLASS_NAMES
from test_multi_layer_graph import fixture, generate


ROOT = Path(__file__).resolve().parents[4]


class BlendRegistrationTests(unittest.TestCase):
    def load_root(self):
        namespace = {'__file__': str(ROOT / '__init__.py'), '__name__': '_p3c_offline_root'}
        exec(compile((ROOT / '__init__.py').read_text(encoding='utf-8'), str(ROOT / '__init__.py'), 'exec'), namespace)
        return namespace

    def test_component_import_failure_preserves_sidebar_and_no_overlap(self):
        original_import = builtins.__import__
        def fail_blend(name, *args, **kwargs):
            if name.endswith('.blend_component'):
                raise ImportError('deliberate offline Blend failure')
            return original_import(name, *args, **kwargs)
        retained = EXACT_THREE_REALIZATION
        with patch.object(routes, 'register_routes') as register, patch('builtins.__import__', side_effect=fail_blend):
            result = self.load_root()
        register.assert_called_once_with()
        self.assertEqual(tuple(result['NODE_CLASS_MAPPINGS']), LAYER_NODE_CLASS_NAMES + FIELD_SOURCE_NODE_CLASS_NAMES + PATTERN_FIELD_NODE_CLASS_NAMES + FIELD_TRANSFORM_NODE_CLASS_NAMES + FIELD_REPEAT_NODE_CLASS_NAMES + FIELD_REMAP_NODE_CLASS_NAMES + FIELD_BLUR_NODE_CLASS_NAMES + PROCEDURAL_FIELD_NODE_CLASS_NAMES + FIELD_FADE_NODE_CLASS_NAMES + PRESET_FIELD_NODE_CLASS_NAMES + PAINTED_FIELD_NODE_CLASS_NAMES)
        self.assertIsNone(result['BLEND_COMPONENT_IDENTITY'])
        self.assertIn('ImportError', result['BLEND_REGISTRATION_ERROR'])
        self.assertIs(EXACT_THREE_REALIZATION, retained)
        self.assertEqual(retained.identifier, 'prediction-mixing.multi-layer.realization.exact-3.comfyui-0.34.6.v1')
        with tempfile.TemporaryDirectory(prefix='cl-p3c-retained-') as directory:
            graph = generate(fixture(directory))
            self.assertTrue(graph.generated, graph.errors)
            self.assertEqual(len(graph.artifact.to_api_graph()), 19)

    def test_real_sidebar_registration_survives_blend_import_failure(self):
        registered = []
        class RouteTable:
            def route(self, path):
                registered.append(path)
                return lambda function: function
            get = post = put = delete = route
        server = SimpleNamespace(PromptServer=SimpleNamespace(instance=SimpleNamespace(routes=RouteTable())))
        context = SimpleNamespace(host_configuration=SimpleNamespace(user_directory=ROOT))
        with patch.dict('sys.modules', {'server': server}), patch.object(routes, '_REGISTERED', False), \
                patch.object(routes, '_COORDINATOR', None), patch.object(routes, '_build_host_context', return_value=context), \
                patch.object(routes, 'ExistingBackendApplication'), patch.object(routes, 'PanelJobCoordinator'), \
                patch.object(routes, 'PanelDocumentStore'), \
                patch.object(blend_component, 'initialize_blend_node_registration', side_effect=ImportError('offline missing dependency')):
            result = self.load_root()
            self.assertTrue(routes._REGISTERED)
        self.assertIn('/conditioning-layers/capabilities', registered)
        self.assertIn('/conditioning-layers/executions', registered)
        self.assertIn('/conditioning-layers/documents', registered)
        self.assertEqual(tuple(result['NODE_CLASS_MAPPINGS']), LAYER_NODE_CLASS_NAMES + FIELD_SOURCE_NODE_CLASS_NAMES + PATTERN_FIELD_NODE_CLASS_NAMES + FIELD_TRANSFORM_NODE_CLASS_NAMES + FIELD_REPEAT_NODE_CLASS_NAMES + FIELD_REMAP_NODE_CLASS_NAMES + FIELD_BLUR_NODE_CLASS_NAMES + PROCEDURAL_FIELD_NODE_CLASS_NAMES + FIELD_FADE_NODE_CLASS_NAMES + PRESET_FIELD_NODE_CLASS_NAMES + PAINTED_FIELD_NODE_CLASS_NAMES)

    def test_dependency_registration_and_initialization_failures_are_isolated(self):
        for failure in (ImportError('missing torch'), RuntimeError('initialization'), ValueError('registration')):
            events = []
            def register():
                events.append('sidebar')
            def initialize():
                events.append('blend')
                raise failure
            with patch.object(routes, 'register_routes', side_effect=register), patch.object(blend_component, 'initialize_blend_node_registration', side_effect=initialize):
                result = self.load_root()
            self.assertEqual(events, ['sidebar', 'blend'])
            self.assertEqual(tuple(result['NODE_CLASS_MAPPINGS']), LAYER_NODE_CLASS_NAMES + FIELD_SOURCE_NODE_CLASS_NAMES + PATTERN_FIELD_NODE_CLASS_NAMES + FIELD_TRANSFORM_NODE_CLASS_NAMES + FIELD_REPEAT_NODE_CLASS_NAMES + FIELD_REMAP_NODE_CLASS_NAMES + FIELD_BLUR_NODE_CLASS_NAMES + PROCEDURAL_FIELD_NODE_CLASS_NAMES + FIELD_FADE_NODE_CLASS_NAMES + PRESET_FIELD_NODE_CLASS_NAMES + PAINTED_FIELD_NODE_CLASS_NAMES)
            self.assertIsNone(result['BLEND_COMPONENT_IDENTITY'])

    def test_success_publishes_project_identity_after_sidebar(self):
        with patch.object(routes, 'register_routes') as register:
            result = self.load_root()
        register.assert_called_once_with()
        self.assertEqual(tuple(result['NODE_CLASS_MAPPINGS']), ('ConditioningLayersNormalizedBlend',) + LAYER_NODE_CLASS_NAMES + FIELD_SOURCE_NODE_CLASS_NAMES + PATTERN_FIELD_NODE_CLASS_NAMES + FIELD_TRANSFORM_NODE_CLASS_NAMES + FIELD_REPEAT_NODE_CLASS_NAMES + FIELD_REMAP_NODE_CLASS_NAMES + FIELD_BLUR_NODE_CLASS_NAMES + PROCEDURAL_FIELD_NODE_CLASS_NAMES + FIELD_FADE_NODE_CLASS_NAMES + PRESET_FIELD_NODE_CLASS_NAMES + PAINTED_FIELD_NODE_CLASS_NAMES)
        self.assertEqual(result['BLEND_COMPONENT_IDENTITY'], blend_component.blend_component_identity())
        self.assertIsNone(result['BLEND_REGISTRATION_ERROR'])


if __name__ == '__main__':
    unittest.main()
