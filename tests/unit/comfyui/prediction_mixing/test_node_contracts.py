from __future__ import annotations

from dataclasses import replace
import hashlib
import unittest

from conditioning_layers.comfyui.prediction_mixing import (
    COMFYUI_0280_NODE_CONTRACTS,
    COMFYUI_0280_NODE_SNAPSHOT,
    create_host_node_contract_snapshot,
    extract_static_symbol_evidence,
    fingerprint_host_node_contract_snapshot,
    fingerprint_node_contract,
    snapshot_is_supported,
)


class StaticContractExtractionTests(unittest.TestCase):
    def test_controlled_symbol_extraction_is_deterministic(self) -> None:
        source = "class Example:\n    FUNCTION = 'run'\n"
        expected_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
        first = extract_static_symbol_evidence(
            source,
            source_file="fixtures/nodes.py",
            symbol="Example",
            expected_source_sha256=expected_hash,
        )
        second = extract_static_symbol_evidence(
            source,
            source_file="fixtures/nodes.py",
            symbol="Example",
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first.symbol_fingerprint), 64)

    def test_unparseable_missing_or_hash_mismatched_evidence_fails_closed(self) -> None:
        cases = (
            {"source_text": "class", "symbol": "Example"},
            {"source_text": "class Other:\n    pass\n", "symbol": "Example"},
            {
                "source_text": "class Example:\n    pass\n",
                "symbol": "Example",
                "expected_source_sha256": "0" * 64,
            },
        )
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError):
                extract_static_symbol_evidence(
                    source_file="fixtures/nodes.py",
                    **case,
                )

    def test_required_contracts_capture_graph_values_and_outputs(self) -> None:
        self.assertEqual(len(COMFYUI_0280_NODE_CONTRACTS), 11)
        clip = COMFYUI_0280_NODE_CONTRACTS["CLIPLoader"]
        clip_inputs = {item.name: item for item in clip.input_evidence}
        self.assertEqual(clip.host_optional_inputs, ("device",))
        self.assertIn("krea2", clip_inputs["type"].enum_values)
        self.assertEqual(clip_inputs["device"].default_value, "default")

        mask = COMFYUI_0280_NODE_CONTRACTS["ConditioningSetMask"]
        mask_inputs = {item.name: item for item in mask.input_evidence}
        self.assertEqual(mask_inputs["strength"].default_value, 1.0)
        self.assertEqual(
            mask_inputs["set_cond_area"].enum_values,
            ("default", "mask bounds"),
        )
        self.assertEqual(mask.return_types, ("CONDITIONING",))
        self.assertEqual(mask.output_indices, (0,))

        sampler = COMFYUI_0280_NODE_CONTRACTS["KSampler"]
        sampler_inputs = {item.name: item for item in sampler.input_evidence}
        self.assertEqual(sampler_inputs["sampler_name"].enum_values, ("euler",))
        self.assertEqual(sampler_inputs["scheduler"].enum_values, ("simple",))
        for record in COMFYUI_0280_NODE_CONTRACTS.values():
            self.assertEqual(
                record.contract_fingerprint,
                fingerprint_node_contract(record),
            )


class SnapshotTests(unittest.TestCase):
    def test_canonical_snapshot_is_supported_portable_and_self_consistent(self) -> None:
        snapshot = COMFYUI_0280_NODE_SNAPSHOT
        self.assertTrue(snapshot_is_supported(snapshot))
        self.assertEqual(
            snapshot.snapshot_fingerprint,
            fingerprint_host_node_contract_snapshot(snapshot),
        )
        serialized = repr(snapshot)
        self.assertNotIn("C:\\", serialized)
        self.assertNotIn("D:\\", serialized)

    def test_timestamp_is_excluded_from_deterministic_fingerprint(self) -> None:
        changed = replace(COMFYUI_0280_NODE_SNAPSHOT, evidence_timestamp="2099-01-01")
        self.assertEqual(
            fingerprint_host_node_contract_snapshot(changed),
            COMFYUI_0280_NODE_SNAPSHOT.snapshot_fingerprint,
        )

    def test_altered_source_hash_changes_fingerprint(self) -> None:
        hashes = dict(COMFYUI_0280_NODE_SNAPSHOT.source_file_hashes)
        hashes["nodes.py"] = "f" * 64
        changed = replace(COMFYUI_0280_NODE_SNAPSHOT, source_file_hashes=hashes)
        self.assertNotEqual(
            fingerprint_host_node_contract_snapshot(changed),
            COMFYUI_0280_NODE_SNAPSHOT.snapshot_fingerprint,
        )

    def test_missing_semantic_evidence_prevents_support(self) -> None:
        incomplete = create_host_node_contract_snapshot(
            snapshot_identifier="incomplete",
            profile_identifier="test",
            comfyui_version="0",
            comfyui_revision="0" * 40,
            contracts={},
            source_reference="fixtures/incomplete",
            semantic_evidence=(),
            source_file_hashes={},
            unresolved_items=("semantic review missing",),
        )
        self.assertFalse(snapshot_is_supported(incomplete))


if __name__ == "__main__":
    unittest.main()
