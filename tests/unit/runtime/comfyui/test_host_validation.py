from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from conditioning_layers.runtime.comfyui import (
    HostCompatibilityStatus,
    validate_local_host,
)
from conditioning_layers.comfyui.prediction_mixing import (
    CANONICAL_COMFYUI_0280_INVENTORY,
    COMFYUI_0280_NODE_SNAPSHOT,
)

from _support import codes, make_case


class HostValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.case = make_case(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def validate(self, configuration=None, snapshot="default"):
        return validate_local_host(
            configuration or self.case.configuration,
            self.case.inventory,
            self.case.artifact.required_host_components,
            self.case.node_snapshot if snapshot == "default" else snapshot,
        )

    def test_valid_declared_host_layout_exact_revision(self) -> None:
        result = self.validate()
        self.assertTrue(result.compatible, result.errors)
        self.assertTrue(result.snapshot.filesystem_verified)
        self.assertTrue(result.snapshot.node_contracts_verified)
        self.assertIs(
            result.snapshot.version_status, HostCompatibilityStatus.EXACT_MATCH
        )
        self.assertIs(
            result.snapshot.revision_status, HostCompatibilityStatus.EXACT_MATCH
        )

    def test_exact_0280_host_and_trusted_snapshot_are_compatible(self) -> None:
        case = make_case(self.root / "profile-0280", CANONICAL_COMFYUI_0280_INVENTORY)
        result = validate_local_host(
            case.configuration,
            case.inventory,
            case.artifact.required_host_components,
            COMFYUI_0280_NODE_SNAPSHOT,
        )
        self.assertTrue(result.compatible, result.errors)
        self.assertEqual(
            result.snapshot.node_contract_snapshot_fingerprint,
            COMFYUI_0280_NODE_SNAPSHOT.snapshot_fingerprint,
        )

    def test_missing_version_artifact_fails_closed(self) -> None:
        (self.case.configuration.git_checkout_path / "comfyui_version.py").unlink()

        result = self.validate()

        self.assertIsNone(result.snapshot.observed_comfyui_version)
        self.assertIs(
            result.snapshot.version_status, HostCompatibilityStatus.UNABLE_TO_VERIFY
        )
        self.assertIn("runtime.host_version", codes(result.errors))

    def test_malformed_version_artifact_fails_closed(self) -> None:
        (self.case.configuration.git_checkout_path / "comfyui_version.py").write_text(
            "__version__ =\n", encoding="utf-8"
        )

        result = self.validate()

        self.assertIsNone(result.snapshot.observed_comfyui_version)
        self.assertIs(
            result.snapshot.version_status, HostCompatibilityStatus.UNABLE_TO_VERIFY
        )
        self.assertIn("runtime.host_version", codes(result.errors))

    def test_missing_version_assignment_fails_closed(self) -> None:
        (self.case.configuration.git_checkout_path / "comfyui_version.py").write_text(
            'VERSION = "0.27.1"\n', encoding="utf-8"
        )

        result = self.validate()

        self.assertIsNone(result.snapshot.observed_comfyui_version)
        self.assertIs(
            result.snapshot.version_status, HostCompatibilityStatus.UNABLE_TO_VERIFY
        )
        self.assertIn("runtime.host_version", codes(result.errors))

    def test_invalid_version_value_fails_closed(self) -> None:
        (self.case.configuration.git_checkout_path / "comfyui_version.py").write_text(
            '__version__ = "not-a-version"\n', encoding="utf-8"
        )

        result = self.validate()

        self.assertEqual(result.snapshot.observed_comfyui_version, "not-a-version")
        self.assertIs(
            result.snapshot.version_status,
            HostCompatibilityStatus.UNSUPPORTED_MISMATCH,
        )
        self.assertIn("runtime.host_version", codes(result.errors))

    def test_pyproject_only_checkout_fails_closed(self) -> None:
        checkout = self.case.configuration.git_checkout_path
        (checkout / "comfyui_version.py").unlink()
        (checkout / "pyproject.toml").write_text(
            '[project]\nversion = "0.27.1"\n', encoding="utf-8"
        )

        result = self.validate()

        self.assertIsNone(result.snapshot.observed_comfyui_version)
        self.assertIs(
            result.snapshot.version_status, HostCompatibilityStatus.UNABLE_TO_VERIFY
        )
        self.assertIn("runtime.host_version", codes(result.errors))

    def test_pyproject_does_not_rescue_malformed_version_artifact(self) -> None:
        checkout = self.case.configuration.git_checkout_path
        (checkout / "comfyui_version.py").write_text(
            "__version__ =\n", encoding="utf-8"
        )
        (checkout / "pyproject.toml").write_text(
            '[project]\nversion = "0.27.1"\n', encoding="utf-8"
        )

        result = self.validate()

        self.assertIsNone(result.snapshot.observed_comfyui_version)
        self.assertIs(
            result.snapshot.version_status, HostCompatibilityStatus.UNABLE_TO_VERIFY
        )
        self.assertIn("runtime.host_version", codes(result.errors))

    def test_version_artifact_resolving_outside_checkout_fails_closed(self) -> None:
        checkout = self.case.configuration.git_checkout_path
        version_file = checkout / "comfyui_version.py"
        outside = self.root / "outside-comfyui-version.py"
        outside.write_text(
            f'__version__ = "{self.case.inventory.expected_comfyui_version}"\n',
            encoding="utf-8",
        )
        resolved_outside = outside.resolve(strict=True)
        path_type = type(version_file)
        original_resolve = path_type.resolve

        def resolve(path, strict=False):
            if path == version_file:
                return resolved_outside
            return original_resolve(path, strict=strict)

        with patch.object(path_type, "resolve", autospec=True, side_effect=resolve):
            result = self.validate()

        self.assertIsNone(result.snapshot.observed_comfyui_version)
        self.assertIs(
            result.snapshot.version_status, HostCompatibilityStatus.UNABLE_TO_VERIFY
        )
        self.assertIn("runtime.host_version", codes(result.errors))

    def test_historical_snapshot_cannot_validate_0280_revision(self) -> None:
        case = make_case(
            self.root / "profile-0280-old", CANONICAL_COMFYUI_0280_INVENTORY
        )
        result = validate_local_host(
            case.configuration,
            case.inventory,
            case.artifact.required_host_components,
            self.case.node_snapshot,
        )
        self.assertFalse(result.compatible)
        self.assertIn("runtime.node_contract_mismatch", codes(result.errors))

    def test_missing_root(self) -> None:
        missing = self.root / "missing"
        result = self.validate(
            replace(
                self.case.configuration,
                comfyui_root=missing,
                git_checkout_path=missing,
            )
        )
        self.assertFalse(result.compatible)
        self.assertIn("runtime.host_root", codes(result.errors))

    def test_missing_input_and_output_directories(self) -> None:
        self.case.configuration.input_directory.rmdir()
        self.case.configuration.output_directory.rmdir()
        result = self.validate()
        self.assertIn("runtime.host_root", codes(result.errors))

    def test_non_directory_path(self) -> None:
        file_path = self.root / "not-directory"
        file_path.write_bytes(b"x")
        result = self.validate(
            replace(self.case.configuration, output_directory=file_path)
        )
        self.assertIn("runtime.host_root", codes(result.errors))

    def test_unsupported_profile(self) -> None:
        result = self.validate(
            replace(
                self.case.configuration,
                supported_profile_identifier="unsupported",
            )
        )
        self.assertIn("runtime.host_profile", codes(result.errors))

    def test_mismatched_revision_is_unsupported(self) -> None:
        revision = "f" * 40
        (self.case.configuration.git_checkout_path / ".git" / "HEAD").write_text(
            revision, encoding="utf-8"
        )
        snapshot = replace(self.case.node_snapshot, comfyui_revision=revision)
        result = self.validate(snapshot=snapshot)
        self.assertIs(
            result.snapshot.revision_status,
            HostCompatibilityStatus.UNSUPPORTED_MISMATCH,
        )
        self.assertIn("runtime.host_revision", codes(result.errors))

    def test_unverifiable_revision(self) -> None:
        (self.case.configuration.git_checkout_path / ".git" / "HEAD").write_text(
            "invalid", encoding="utf-8"
        )
        result = self.validate()
        self.assertIs(
            result.snapshot.revision_status,
            HostCompatibilityStatus.UNABLE_TO_VERIFY,
        )
        self.assertIn("runtime.host_revision", codes(result.errors))

    def test_missing_node_snapshot_is_unresolved(self) -> None:
        result = self.validate(snapshot=None)
        self.assertIn("runtime.node_contract_unknown", codes(result.errors))
        self.assertEqual(
            result.unresolved_requirements, ("runtime.node_contract_unknown",)
        )

    def test_node_contract_mismatch(self) -> None:
        contracts = dict(self.case.node_snapshot.contracts)
        class_name = self.case.artifact.required_host_components[0]
        contracts[class_name] = replace(
            contracts[class_name], required_inputs=("wrong",)
        )
        result = self.validate(
            snapshot=replace(self.case.node_snapshot, contracts=contracts)
        )
        self.assertIn("runtime.node_contract_mismatch", codes(result.errors))

    def test_symlink_escape_where_supported(self) -> None:
        outside = self.root.parent / f"{self.root.name}-outside"
        outside.mkdir()
        link = self.case.configuration.data_trusted_root / "escaped"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symlink creation unavailable: {error}")
        finally:
            self.addCleanup(outside.rmdir)
        result = self.validate(replace(self.case.configuration, output_directory=link))
        self.assertIn("runtime.host_root", codes(result.errors))


if __name__ == "__main__":
    unittest.main()
