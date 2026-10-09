"""Fresh-process and static boundaries for the additive offline Blend route."""
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[4]


class BlendArchitectureTests(unittest.TestCase):
    def test_metadata_boundaries_do_not_import_tensor_or_host_runtime(self):
        source = """
import sys
from conditioning_layers.capabilities import blend
from conditioning_layers.adapters.prediction_mixing.blend import translate_prediction_mixing_blend
from conditioning_layers.comfyui.prediction_mixing.blend import generate_prediction_mixing_blend_workflow
from conditioning_layers.runtime.comfyui.blend import prepare_blend_submission_bundle
from conditioning_layers.execution.comfyui.blend import execute_blend_submission_bundle
for name in ('torch', 'numpy', 'av', 'comfy', 'nodes', 'server'):
    assert name not in sys.modules, name
"""
        result = subprocess.run([sys.executable, "-B", "-W", "error", "-c", source],
                                cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_product_entry_points_do_not_import_blend_realization(self):
        for relative in (
            "src/conditioning_layers/integrations/comfyui_panel/application.py",
            "src/conditioning_layers/integrations/comfyui_panel/routes.py",
            "src/conditioning_layers/capabilities/multi_layer.py",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn(".blend import", source, relative)
            self.assertNotIn("execute_blend_submission_bundle", source, relative)
            self.assertNotIn("prepare_blend_submission_bundle", source, relative)


if __name__ == "__main__":
    unittest.main()
