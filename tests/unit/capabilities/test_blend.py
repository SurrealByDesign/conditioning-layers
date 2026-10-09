from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from conditioning_layers.capabilities.blend import (
    BLEND_LIVE_QUALIFIED, BLEND_PRODUCT_ADMITTED, EXACT_THREE_BLEND_ELIGIBILITY,
    evaluate_blend_eligibility, fingerprint_blend_eligibility, select_blend_eligibility,
    verify_blend_eligibility,
)
from conditioning_layers.capabilities.multi_layer import product_supported_cardinalities, route_prediction_mixing
from conditioning_layers.domain import REQUIRE_NO_OVERLAP
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tooling"))
from blend_fixture import blend_fixture


class BlendEligibilityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        for target in ("socket.socket", "urllib.request.urlopen", "http.client.HTTPConnection", "subprocess.Popen"):
            guard = patch(target, side_effect=AssertionError("P3C is offline only"))
            guard.start()
            self.addCleanup(guard.stop)
        self.document = blend_fixture(temporary.name)[0]

    def test_backend_registration_and_product_admission_are_distinct(self):
        self.assertEqual(evaluate_blend_eligibility(self.document), ())
        self.assertEqual(select_blend_eligibility(self.document), EXACT_THREE_BLEND_ELIGIBILITY)
        self.assertTrue(BLEND_PRODUCT_ADMITTED)
        self.assertTrue(BLEND_LIVE_QUALIFIED)
        self.assertFalse(route_prediction_mixing(self.document).compatible)
        self.assertEqual(product_supported_cardinalities(), (1, 2, 3))

    def test_only_exact_three_and_exact_policy_are_registered(self):
        for count in (0, 1, 2, 4):
            layers = self.document.layers[:count] if count < 4 else self.document.layers + (replace(self.document.layers[0], layer_id="fourth"),)
            self.assertTrue(evaluate_blend_eligibility(replace(self.document, layers=layers)))
        self.assertTrue(evaluate_blend_eligibility(replace(self.document, composition_policy=REQUIRE_NO_OVERLAP.reference)))

    def test_missing_registration_and_self_registered_forgery_fail(self):
        self.assertEqual(verify_blend_eligibility(EXACT_THREE_BLEND_ELIGIBILITY), ())
        with patch("conditioning_layers.capabilities.blend.REGISTERED_BLEND_ELIGIBILITY_ENTRIES", ()):
            self.assertTrue(evaluate_blend_eligibility(self.document))
        forged = replace(EXACT_THREE_BLEND_ELIGIBILITY, exact_cardinality=4)
        forged = replace(forged, fingerprint=fingerprint_blend_eligibility(forged))
        with patch("conditioning_layers.capabilities.blend.REGISTERED_BLEND_ELIGIBILITY_ENTRIES", (forged,)):
            self.assertTrue(verify_blend_eligibility(forged))


if __name__ == "__main__":
    unittest.main()
