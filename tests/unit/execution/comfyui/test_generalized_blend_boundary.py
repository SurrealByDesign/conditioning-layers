"""ADR-0028 Slice B: the retained exact-3 client rejects generalized bundles.

Developer/offline lane. The generalized bundle is prepared against temporary
fixtures; the retained client must reject it by type before any transport,
server identity, network setup or `/prompt` submission can begin.
"""

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from conditioning_layers.execution.comfyui import blend as client
from conditioning_layers.execution.comfyui.models import ComfyUIExecutionPolicy, ComfyUIServerConfiguration
from conditioning_layers.runtime.comfyui.blend import BlendSubmissionBundle
from conditioning_layers.runtime.comfyui.generalized_blend import GeneralizedBlendSubmissionBundle


ROOT = Path(__file__).resolve().parents[4]


def _load_bundle_support():
    path = ROOT / "tests/unit/runtime/comfyui/test_generalized_blend_bundle.py"
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("_slice_b_generalized_bundle_support", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SUPPORT = _load_bundle_support()


class GeneralizedBundleClientBoundaryTests(unittest.TestCase):
    def test_retained_client_rejects_generalized_bundle_before_transport_or_submission(self):
        configuration = ComfyUIServerConfiguration(port=9)
        policy = ComfyUIExecutionPolicy()
        for n in (4, 9):
            with self.subTest(n=n), tempfile.TemporaryDirectory() as directory, SUPPORT.SUPPORT.offline_fence():
                result, _, _, _ = SUPPORT.prepare(directory, n)
                bundle = result.bundle
                self.assertIs(type(bundle), GeneralizedBlendSubmissionBundle)
                self.assertNotIsInstance(bundle, BlendSubmissionBundle)
                self.assertIs(bundle.submission_ready, False)
                with patch.object(client, "LocalJsonTransport", side_effect=AssertionError("transport created")) as transport, \
                        patch.object(client, "establish_server_identity", side_effect=AssertionError("identity")) as identity, \
                        patch.object(client, "submission_payload", side_effect=AssertionError("payload")) as payload, \
                        patch.object(client, "validate_blend_submission_bundle",
                                     side_effect=AssertionError("validation reached")) as validation:
                    with self.assertRaisesRegex(TypeError, "bundle must be a BlendSubmissionBundle"):
                        client.execute_blend_submission_bundle(bundle, configuration, policy)
                for mock in (transport, identity, payload, validation):
                    mock.assert_not_called()
                # Retained provenance builders also refuse the successor family.
                with self.assertRaises(ValueError):
                    client.build_blend_execution_provenance(
                        bundle=bundle, server_identity=None, prompt_id=None,
                        terminal_state=client.ExecutionState.NOT_SUBMITTED, outputs=(), errors=(), warnings=())
                self.assertEqual(tuple(f.code for f in client.validate_blend_execution_provenance(object(), bundle)),
                                 ("execution.blend_provenance_invalid",))


if __name__ == "__main__":
    unittest.main()
