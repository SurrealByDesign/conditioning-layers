from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
import unittest

from conditioning_layers.capabilities import (
    PREDICTION_MIXING_CAPABILITY,
    AdapterStatus,
    EvidenceLevel,
    SupportStatus,
)


ROOT = Path(__file__).resolve().parents[3]


class PredictionMixingCapabilityRecordTests(unittest.TestCase):
    def test_canonical_record_is_immutable(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            PREDICTION_MIXING_CAPABILITY.display_name = "Changed"  # type: ignore[misc]

        with self.assertRaises(FrozenInstanceError):
            PREDICTION_MIXING_CAPABILITY.known_risks[0].message = "Changed"  # type: ignore[misc]

    def test_exact_identifier_and_experimental_status(self) -> None:
        self.assertEqual(
            PREDICTION_MIXING_CAPABILITY.adapter_identifier,
            "prediction-mixing.experimental.v1",
        )
        self.assertIs(
            PREDICTION_MIXING_CAPABILITY.status,
            AdapterStatus.EXPERIMENTAL,
        )

    def test_supports_prompt_layers_only_in_one_to_two_range(self) -> None:
        capability = PREDICTION_MIXING_CAPABILITY

        self.assertEqual(capability.supported_layer_type, "Prompt Layer")
        self.assertEqual(capability.minimum_visible_prompt_layers, 1)
        self.assertEqual(capability.maximum_tested_visible_prompt_layers, 2)
        self.assertIs(capability.one_layer_evidence, EvidenceLevel.INFERRED)
        self.assertIs(capability.two_layer_evidence, EvidenceLevel.OBSERVED)

    def test_field_order_strength_and_overlap_claims_are_explicit(self) -> None:
        capability = PREDICTION_MIXING_CAPABILITY

        self.assertIs(
            capability.imported_png_fields.status,
            SupportStatus.SUPPORTED,
        )
        self.assertIs(
            capability.continuous_fields.status,
            SupportStatus.SUPPORTED,
        )
        self.assertIs(capability.overlap.status, SupportStatus.UNSUPPORTED)
        self.assertIs(
            capability.retained_order_execution.status,
            SupportStatus.NON_SEMANTIC,
        )
        self.assertIs(capability.strength.status, SupportStatus.EXPERIMENTAL)

    def test_required_risk_declarations_are_present(self) -> None:
        risk_codes = {
            risk.code for risk in PREDICTION_MIXING_CAPABILITY.known_risks
        }

        self.assertEqual(
            risk_codes,
            {"risk.seam", "risk.leakage", "risk.fusion", "risk.topology"},
        )
        self.assertTrue(
            all(
                risk.evidence is EvidenceLevel.OBSERVED
                for risk in PREDICTION_MIXING_CAPABILITY.known_risks
            )
        )

    def test_evidence_references_are_stable_repository_relative_files(self) -> None:
        references = PREDICTION_MIXING_CAPABILITY.evidence_references

        self.assertGreaterEqual(len(references), 4)
        self.assertTrue(all(not Path(reference).is_absolute() for reference in references))
        self.assertTrue(all(".." not in Path(reference).parts for reference in references))
        # Historical evidence references remain identity-bearing, but evidence is private.

    def test_record_disclaims_production_quality_and_declares_provenance(self) -> None:
        capability = PREDICTION_MIXING_CAPABILITY

        self.assertIs(
            capability.production_quality.status,
            SupportStatus.UNSUPPORTED,
        )
        self.assertIs(capability.provenance.status, SupportStatus.SUPPORTED)
        self.assertIs(capability.provenance.evidence, EvidenceLevel.DECLARED)


if __name__ == "__main__":
    unittest.main()
