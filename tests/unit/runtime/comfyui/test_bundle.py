from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from conditioning_layers.comfyui.prediction_mixing import (
    CANONICAL_COMFYUI_0280_INVENTORY,
    COMFYUI_0280_NODE_SNAPSHOT,
)
from conditioning_layers.runtime.comfyui import (
    build_cleanup_plan,
    fingerprint_submission_bundle,
    prepare_submission_bundle,
)

from _support import FIELD_BYTES, codes, make_case


class SubmissionBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.case = make_case(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def prepare(self, **overrides):
        values = {
            "artifact": self.case.artifact,
            "workflow_provenance": self.case.provenance,
            "inventory": self.case.inventory,
            "host_configuration": self.case.configuration,
            "field_inspections": self.case.inspections,
            "source_asset_root": self.case.asset_root,
            "node_contract_snapshot": self.case.node_snapshot,
        }
        values.update(overrides)
        return prepare_submission_bundle(**values)

    def test_ready_bundle(self) -> None:
        result = self.prepare()
        self.assertTrue(result.ready, result.errors)
        self.assertTrue(result.bundle.submission_ready)
        self.assertEqual(result.bundle.unresolved_runtime_requirements, ())
        self.assertEqual(result.bundle.to_api_graph(), self.case.artifact.to_api_graph())
        self.assertIn("runtime.bundle_ready", codes(result.information))

    def test_matching_0280_profile_can_prepare_without_server_or_model_loading(self) -> None:
        case = make_case(self.root / "profile-0280", CANONICAL_COMFYUI_0280_INVENTORY)
        result = prepare_submission_bundle(
            case.artifact,
            case.provenance,
            case.inventory,
            case.configuration,
            case.inspections,
            case.asset_root,
            COMFYUI_0280_NODE_SNAPSHOT,
        )
        self.assertTrue(result.ready, result.errors)
        self.assertEqual(
            result.bundle.host_snapshot.node_contract_snapshot_fingerprint,
            COMFYUI_0280_NODE_SNAPSHOT.snapshot_fingerprint,
        )

    def test_not_ready_on_host_mismatch(self) -> None:
        revision = "f" * 40
        (self.case.configuration.git_checkout_path / ".git" / "HEAD").write_text(
            revision, encoding="utf-8"
        )
        snapshot = replace(self.case.node_snapshot, comfyui_revision=revision)
        result = self.prepare(node_contract_snapshot=snapshot)
        self.assertFalse(result.ready)
        self.assertIsNone(result.bundle)
        self.assertIn("runtime.host_revision", codes(result.errors))
        self.assertFalse(
            (self.case.configuration.input_directory / "conditioning-layers").exists()
        )

    def test_not_ready_on_component_mismatch(self) -> None:
        model_path = (
            self.case.configuration.model_directories["diffusion_models"][0]
            / self.case.inventory.model_filename
        )
        model_path.write_bytes(b"changed")
        result = self.prepare()
        self.assertFalse(result.ready)
        self.assertTrue(
            {"runtime.component_size", "runtime.component_checksum"}
            <= codes(result.errors)
        )

    def test_not_ready_on_unresolved_node_contract(self) -> None:
        result = self.prepare(node_contract_snapshot=None)
        self.assertFalse(result.ready)
        self.assertIn("runtime.node_contract_unknown", codes(result.errors))
        self.assertEqual(
            result.unresolved_runtime_requirements,
            ("runtime.node_contract_unknown",),
        )

    def test_deterministic_bundle_fingerprint_across_equivalent_hosts(self) -> None:
        other_root = self.root / "equivalent"
        other_case = make_case(other_root)
        first = self.prepare()
        second = prepare_submission_bundle(
            other_case.artifact,
            other_case.provenance,
            other_case.inventory,
            other_case.configuration,
            other_case.inspections,
            other_case.asset_root,
            other_case.node_snapshot,
        )
        self.assertEqual(
            first.bundle.bundle_fingerprint, second.bundle.bundle_fingerprint
        )

    def test_fingerprint_covers_host_component_field_graph_and_seed(self) -> None:
        bundle = self.prepare().bundle
        base = bundle.bundle_fingerprint
        common = {
            "artifact": bundle.graph_artifact,
            "host_snapshot": bundle.host_snapshot,
            "components": bundle.verified_components,
            "staged_assets": bundle.staged_assets,
            "warning_codes": bundle.warnings,
        }
        changed_host = fingerprint_submission_bundle(
            **{**common, "host_snapshot": replace(bundle.host_snapshot, observed_comfyui_revision="f" * 40)}
        )
        components = list(bundle.verified_components)
        components[0] = replace(components[0], sha256="f" * 64)
        changed_component = fingerprint_submission_bundle(
            **{**common, "components": tuple(components)}
        )
        staged = list(bundle.staged_assets)
        staged[0] = replace(staged[0], staged_filename="conditioning-layers/document-1/changed.png")
        changed_staged = fingerprint_submission_bundle(
            **{**common, "staged_assets": tuple(staged)}
        )
        changed_graph = fingerprint_submission_bundle(
            **{**common, "artifact": replace(bundle.graph_artifact, graph_fingerprint="f" * 64)}
        )
        provenance = replace(bundle.graph_artifact.provenance_inputs, seed=9)
        changed_seed = fingerprint_submission_bundle(
            **{**common, "artifact": replace(bundle.graph_artifact, provenance_inputs=provenance)}
        )
        self.assertEqual(
            len({changed_host, changed_component, changed_staged, changed_graph, changed_seed}),
            5,
        )
        self.assertNotIn(base, {changed_host, changed_component, changed_staged, changed_graph, changed_seed})

    def test_portable_provenance_excludes_private_paths(self) -> None:
        bundle = self.prepare().bundle
        provenance = bundle.provenance
        serialized = repr(provenance)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn(str(self.case.configuration.comfyui_root), serialized)
        self.assertEqual(provenance.bundle_fingerprint, bundle.bundle_fingerprint)


class CleanupPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.case = make_case(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def prepare(self):
        return prepare_submission_bundle(
            self.case.artifact,
            self.case.provenance,
            self.case.inventory,
            self.case.configuration,
            self.case.inspections,
            self.case.asset_root,
            self.case.node_snapshot,
        ).bundle

    def test_plan_includes_only_created_files_and_deletes_nothing(self) -> None:
        bundle = self.prepare()
        before = tuple(record.destination_path.exists() for record in bundle.staged_assets)
        plan = build_cleanup_plan(bundle)
        after = tuple(record.destination_path.exists() for record in bundle.staged_assets)
        self.assertTrue(plan.safe_to_execute_elsewhere)
        self.assertEqual(len(plan.items), 2)
        self.assertEqual(before, after)

    def test_reused_file_is_excluded(self) -> None:
        destination = (
            self.case.configuration.input_directory
            / "conditioning-layers"
            / "document-1"
            / "a.png"
        )
        destination.parent.mkdir(parents=True)
        destination.write_bytes(FIELD_BYTES["a"])
        bundle = self.prepare()
        plan = build_cleanup_plan(bundle)
        self.assertEqual(tuple(item.staged_filename for item in plan.items), (
            "conditioning-layers/document-1/b.png",
        ))

    def test_checksum_change_blocks_planned_deletion(self) -> None:
        bundle = self.prepare()
        bundle.staged_assets[0].destination_path.write_bytes(b"changed")
        plan = build_cleanup_plan(bundle)
        self.assertFalse(plan.safe_to_execute_elsewhere)
        self.assertIn("runtime.staging_checksum", codes(plan.errors))
        self.assertNotIn(
            bundle.staged_assets[0].staged_filename,
            {item.staged_filename for item in plan.items},
        )


if __name__ == "__main__":
    unittest.main()
