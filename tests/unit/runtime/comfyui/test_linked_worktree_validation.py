from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui.prediction_mixing import (
    CANONICAL_COMFYUI_0280_INVENTORY,
    COMFYUI_0280_NODE_SNAPSHOT,
)
from conditioning_layers.runtime.comfyui import (
    HostCompatibilityStatus,
    prepare_submission_bundle,
    validate_local_host,
)

from _support import codes, make_case


class LinkedWorktreeValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def linked_case(self, name: str):
        case = make_case(self.root / name, CANONICAL_COMFYUI_0280_INVENTORY)
        marker = case.configuration.git_checkout_path / ".git"
        (marker / "HEAD").unlink()
        marker.rmdir()
        common = self.root / f"{name}-repository" / ".git"
        admin = common / "worktrees" / "pinned"
        admin.mkdir(parents=True)
        marker.write_text(f"gitdir: {admin}\n", encoding="utf-8")
        (admin / "gitdir").write_text(f"{marker}\n", encoding="utf-8")
        (admin / "commondir").write_text("../..\n", encoding="utf-8")
        (admin / "HEAD").write_text(
            case.inventory.expected_comfyui_revision + "\n", encoding="utf-8"
        )
        return case, marker, admin, common

    def validate(self, case):
        return validate_local_host(
            case.configuration,
            case.inventory,
            case.artifact.required_host_components,
            COMFYUI_0280_NODE_SNAPSHOT,
        )

    def prepare_without_transport(self, case):
        with (
            patch("socket.socket", side_effect=AssertionError("Network forbidden"))
            as socket_constructor,
            patch(
                "socket.create_connection",
                side_effect=AssertionError("Network forbidden"),
            ) as create_connection,
        ):
            result = prepare_submission_bundle(
                case.artifact,
                case.provenance,
                case.inventory,
                case.configuration,
                case.inspections,
                case.asset_root,
                COMFYUI_0280_NODE_SNAPSHOT,
            )
        socket_constructor.assert_not_called()
        create_connection.assert_not_called()
        return result

    def assert_unverifiable(self, case) -> None:
        result = self.validate(case)
        self.assertFalse(result.compatible)
        self.assertIsNone(result.snapshot.observed_comfyui_revision)
        self.assertIs(
            result.snapshot.revision_status, HostCompatibilityStatus.UNABLE_TO_VERIFY
        )
        self.assertTrue(
            {"runtime.host_revision", "runtime.node_contract_mismatch"}
            <= codes(result.errors)
        )

    def test_exact_supported_linked_worktree_prepares_without_transport(self) -> None:
        for relative in (False, True):
            with self.subTest(relative_metadata_paths=relative):
                case, marker, admin, _ = self.linked_case(f"supported-{relative}")
                if relative:
                    marker.write_text(
                        f"gitdir: {os.path.relpath(admin, marker.parent)}\n",
                        encoding="utf-8",
                    )
                    (admin / "gitdir").write_text(
                        os.path.relpath(marker, admin) + "\n", encoding="utf-8"
                    )
                result = self.prepare_without_transport(case)
                self.assertTrue(result.ready, result.errors)
                self.assertIsNotNone(result.bundle)
                self.assertTrue(result.bundle.submission_ready)
                snapshot = result.bundle.host_snapshot
                self.assertEqual(
                    snapshot.profile_identifier, case.inventory.comfyui_profile_identifier
                )
                self.assertEqual(snapshot.observed_comfyui_version, "0.28.0")
                self.assertEqual(
                    snapshot.observed_comfyui_revision,
                    "700821e1364eaab0e8f21c538a2131719fec57bf",
                )
                self.assertIs(snapshot.revision_status, HostCompatibilityStatus.EXACT_MATCH)
                self.assertTrue(snapshot.node_contracts_verified)
                self.assertEqual(
                    snapshot.node_contract_snapshot_fingerprint,
                    COMFYUI_0280_NODE_SNAPSHOT.snapshot_fingerprint,
                )
                self.assertIn("runtime.bundle_ready", codes(result.information))

    def test_wrong_linked_revision_blocks_bundle_before_staging(self) -> None:
        case, _, admin, _ = self.linked_case("wrong-revision")
        (admin / "HEAD").write_text("f" * 40 + "\n", encoding="utf-8")
        result = self.prepare_without_transport(case)
        self.assertFalse(result.ready)
        self.assertIsNone(result.bundle)
        self.assertEqual(result.staged_assets, ())
        self.assertIs(
            result.host_snapshot.revision_status,
            HostCompatibilityStatus.UNSUPPORTED_MISMATCH,
        )
        self.assertTrue(
            {
                "runtime.host_revision",
                "runtime.node_contract_mismatch",
                "runtime.bundle_not_ready",
            }
            <= codes(result.errors)
        )
        self.assertEqual(tuple(case.configuration.input_directory.iterdir()), ())

    def test_missing_linked_metadata_fails_closed(self) -> None:
        for name in ("marker", "gitdir", "commondir", "HEAD"):
            with self.subTest(missing=name):
                case, marker, admin, _ = self.linked_case(f"missing-{name}")
                (marker if name == "marker" else admin / name).unlink()
                self.assert_unverifiable(case)

    def test_malformed_linked_metadata_fails_closed(self) -> None:
        for index, (name, value) in enumerate(
            (
                ("marker", "not a gitdir marker\n"),
                ("gitdir", "\n"),
                ("commondir", "\n"),
                ("commondir", "../..\n../..\n"),
                ("HEAD", "not-a-revision\n"),
            )
        ):
            with self.subTest(metadata=name, value=value):
                case, marker, admin, _ = self.linked_case(f"malformed-{index}")
                (marker if name == "marker" else admin / name).write_text(
                    value, encoding="utf-8"
                )
                self.assert_unverifiable(case)

    def test_backlink_to_another_checkout_fails_closed(self) -> None:
        case, _, admin, _ = self.linked_case("wrong-backlink")
        other, _, _, _ = self.linked_case("other-checkout")
        (admin / "gitdir").write_text(
            str(other.configuration.git_checkout_path / ".git") + "\n",
            encoding="utf-8",
        )
        self.assert_unverifiable(case)

    def test_common_directory_mismatch_fails_closed(self) -> None:
        case, _, admin, _ = self.linked_case("wrong-common")
        other_common = self.root / "unrelated-common"
        other_common.mkdir()
        (admin / "commondir").write_text(str(other_common) + "\n", encoding="utf-8")
        self.assert_unverifiable(case)

    def test_external_admin_outside_worktrees_layout_fails_closed(self) -> None:
        case, marker, admin, common = self.linked_case("wrong-admin-layout")
        unrelated_admin = common / "unrelated" / "pinned"
        unrelated_admin.mkdir(parents=True)
        for name in ("gitdir", "commondir", "HEAD"):
            (unrelated_admin / name).write_bytes((admin / name).read_bytes())
        marker.write_text(f"gitdir: {unrelated_admin}\n", encoding="utf-8")
        self.assert_unverifiable(case)

    def test_linked_metadata_resolving_outside_its_root_fails_closed(self) -> None:
        for name in ("marker", "gitdir", "commondir", "HEAD"):
            with self.subTest(escaping_metadata=name):
                case, marker, admin, _ = self.linked_case(f"escaping-{name}")
                target = marker if name == "marker" else admin / name
                outside = self.root / f"outside-{name}"
                outside.write_bytes(target.read_bytes())
                resolved_outside = outside.resolve(strict=True)
                path_type = type(target)
                original_resolve = path_type.resolve

                def resolve(path, strict=False):
                    if path == target:
                        return resolved_outside
                    return original_resolve(path, strict=strict)

                with patch.object(
                    path_type, "resolve", autospec=True, side_effect=resolve
                ):
                    self.assert_unverifiable(case)

    def test_external_symbolic_head_remains_unverifiable(self) -> None:
        case, _, admin, common = self.linked_case("symbolic-linked")
        (admin / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        reference = common / "refs" / "heads" / "main"
        reference.parent.mkdir(parents=True)
        reference.write_text(case.inventory.expected_comfyui_revision, encoding="utf-8")
        self.assert_unverifiable(case)

    def test_ordinary_git_directory_revision_layouts_remain_compatible(self) -> None:
        for layout in ("detached", "loose", "packed", "internal-marker"):
            with self.subTest(layout=layout):
                case = make_case(self.root / layout, CANONICAL_COMFYUI_0280_INVENTORY)
                checkout = case.configuration.git_checkout_path
                git_directory = checkout / ".git"
                revision = case.inventory.expected_comfyui_revision
                if layout in {"loose", "packed"}:
                    (git_directory / "HEAD").write_text(
                        "ref: refs/heads/main\n", encoding="utf-8"
                    )
                    if layout == "loose":
                        reference = git_directory / "refs" / "heads" / "main"
                        reference.parent.mkdir(parents=True)
                        reference.write_text(revision + "\n", encoding="utf-8")
                    else:
                        (git_directory / "packed-refs").write_text(
                            f"# pack-refs with: peeled\n{revision} refs/heads/main\n",
                            encoding="utf-8",
                        )
                elif layout == "internal-marker":
                    (git_directory / "HEAD").unlink()
                    git_directory.rmdir()
                    internal = checkout / "git-metadata"
                    internal.mkdir()
                    (internal / "HEAD").write_text(revision + "\n", encoding="utf-8")
                    git_directory.write_text("gitdir: git-metadata\n", encoding="utf-8")
                result = self.validate(case)
                self.assertTrue(result.compatible, result.errors)
                self.assertEqual(result.snapshot.observed_comfyui_revision, revision)


if __name__ == "__main__":
    unittest.main()
