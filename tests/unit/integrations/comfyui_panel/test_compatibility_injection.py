"""Offline ordinary-v1 preparation with retained, explicitly selected evidence."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import os
import sys
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from conditioning_layers.comfyui.prediction_mixing import (
    COMFYUI_0280_SUPPORTED_PROFILE,
    DEFAULT_SUPPORTED_PROFILE,
    COMFYUI_0345_QUALIFICATION_PROFILE,
)
from conditioning_layers.integrations.comfyui_panel.application import (
    ExistingBackendApplication,
)
from conditioning_layers.integrations.comfyui_panel import routes
from conditioning_layers.runtime.comfyui import (
    fingerprint_submission_bundle,
    prepare_submission_bundle,
)
from conditioning_layers.runtime.comfyui.staging import stage_field_assets

from _support import grayscale_png, row
from test_application import draft, host_context


_APPLICATION = "conditioning_layers.integrations.comfyui_panel.application"
_COMPONENTS = "conditioning_layers.runtime.comfyui.component_validation"
_BUNDLE = "conditioning_layers.runtime.comfyui.bundle"


def fake_checkout(root, profile):
    """Create observation fixtures only; no installed host is read or imported."""
    context = host_context(root)
    inventory = profile.inventory
    context = replace(
        context,
        host_configuration=replace(
            context.host_configuration,
            supported_profile_identifier=inventory.comfyui_profile_identifier,
        ),
    )
    configuration = context.host_configuration
    for directory in (
        configuration.comfyui_root,
        configuration.input_directory,
        configuration.output_directory,
        configuration.user_directory,
        *(paths[0] for paths in configuration.model_directories.values()),
    ):
        directory.mkdir(parents=True, exist_ok=True)
    checkout = configuration.git_checkout_path
    (checkout / ".git").mkdir()
    (checkout / ".git" / "HEAD").write_text(
        inventory.expected_comfyui_revision, encoding="utf-8"
    )
    (checkout / "comfyui_version.py").write_text(
        f'__version__ = "{inventory.expected_comfyui_version}"\n', encoding="utf-8"
    )

    # Both profiles retain the same model evidence. Virtualize only these large
    # files' I/O observations; the production component validator still compares
    # every size/hash and validates the real temporary layout and containment.
    model_evidence = COMFYUI_0280_SUPPORTED_PROFILE.inventory
    observations = {}
    for category, prefix in (
        ("diffusion_models", "model"),
        ("text_encoders", "text_encoder"),
        ("vae", "vae"),
    ):
        path = (
            configuration.model_directories[category][0]
            / getattr(model_evidence, f"{prefix}_filename")
        )
        path.write_bytes(b"offline model file placeholder")
        observations[path] = (
            getattr(model_evidence, f"{prefix}_size_bytes"),
            getattr(model_evidence, f"{prefix}_sha256"),
        )
    return context, observations


@contextmanager
def model_file_observations(observations):
    original_stat = Path.stat

    def stat(path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        if path in observations:
            fields = list(result)
            fields[6] = observations[path][0]
            return os.stat_result(fields)
        return result

    with patch.object(Path, "stat", stat), patch(
        f"{_COMPONENTS}._sha256_file",
        side_effect=lambda path: observations[path][1],
    ):
        yield


class CompatibilityInjectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.request = draft([row("left")], [grayscale_png(255, 0)])

    def run_application(self, context, observations, *, compatibility=None):
        preparations = []
        states = []

        def prepare(*args, **kwargs):
            result = prepare_submission_bundle(*args, **kwargs)
            preparations.append(result)
            return result

        execution = Mock(
            return_value=SimpleNamespace(
                completed=True,
                errors=(),
                outputs=(SimpleNamespace(
                    filename="offline-result.png",
                    subfolder="conditioning-layers-panel",
                    storage_type="output",
                ),),
            )
        )
        options = {} if compatibility is None else {"compatibility": compatibility}
        application = ExistingBackendApplication(
            context, execution_client=execution, **options
        )
        with model_file_observations(observations), patch(
            f"{_APPLICATION}.prepare_submission_bundle", side_effect=prepare
        ), patch(
            f"{_BUNDLE}.stage_field_assets", wraps=stage_field_assets
        ) as stage, patch(
            "socket.create_connection", side_effect=AssertionError("offline test")
        ):
            result = application.run(self.request, "a" * 32, states.append)
        self.assertEqual(len(preparations), 1)
        return application, result, preparations[0], execution, stage, states

    def assert_rejected_before_staging(self, outcome, context, expected_codes):
        _application, result, prepared, execution, stage, states = outcome
        self.assertEqual(result.state, "rejected")
        self.assertFalse(prepared.ready)
        self.assertIsNone(prepared.bundle)
        self.assertTrue(expected_codes <= {item.code for item in result.findings})
        self.assertEqual(prepared.staged_assets, ())
        self.assertEqual(states, ["validating", "preparing"])
        stage.assert_not_called()
        execution.assert_not_called()
        self.assertFalse(
            (context.host_configuration.input_directory / "conditioning-layers").exists()
        )

    def test_current_default_and_explicit_historical_profiles_prepare_and_bind_evidence(self):
        bundles = []
        for profile, explicit in (
            (DEFAULT_SUPPORTED_PROFILE, False),
            (COMFYUI_0280_SUPPORTED_PROFILE, True),
            (COMFYUI_0345_QUALIFICATION_PROFILE, True),
        ):
            with self.subTest(profile=profile.inventory.comfyui_profile_identifier):
                context, observations = fake_checkout(self.root / profile.inventory.expected_comfyui_version, profile)
                application, result, prepared, execution, stage, states = self.run_application(
                    context, observations, compatibility=profile if explicit else None
                )
                self.assertIs(application.compatibility, profile)
                self.assertEqual(result.state, "completed", result.findings)
                self.assertTrue(prepared.ready, prepared.errors)
                self.assertEqual(states, ["validating", "preparing", "executing"])
                stage.assert_called_once()
                bundle = prepared.bundle
                self.assertTrue(all(item.destination_path.is_file() for item in bundle.staged_assets))
                execution.assert_called_once_with(
                    bundle,
                    context.server_configuration,
                    context.execution_policy,
                    trusted_snapshot=profile.node_snapshot,
                )
                self.assertIs(execution.call_args.kwargs["trusted_snapshot"], profile.node_snapshot)
                inventory = profile.inventory
                self.assertEqual(bundle.profile_identifier, inventory.comfyui_profile_identifier)
                self.assertEqual(bundle.inventory_identifier, inventory.inventory_identifier)
                self.assertEqual(bundle.provenance.host_profile_identifier, inventory.comfyui_profile_identifier)
                self.assertEqual(bundle.provenance.comfyui_revision, inventory.expected_comfyui_revision)
                self.assertEqual(bundle.provenance.comfyui_version, inventory.expected_comfyui_version)
                self.assertEqual(
                    bundle.provenance.node_contract_snapshot_fingerprint,
                    profile.node_snapshot.snapshot_fingerprint,
                )
                self.assertEqual(bundle.provenance.bundle_fingerprint, bundle.bundle_fingerprint)
                self.assertEqual(
                    bundle.graph_artifact.provenance_inputs.execution_profile_identifier,
                    inventory.supported_execution_profile_identifier,
                )
                common = dict(
                    artifact=bundle.graph_artifact,
                    host_snapshot=bundle.host_snapshot,
                    components=bundle.verified_components,
                    staged_assets=bundle.staged_assets,
                    warning_codes=bundle.warnings,
                )
                self.assertEqual(fingerprint_submission_bundle(**common), bundle.bundle_fingerprint)
                self.assertNotEqual(
                    fingerprint_submission_bundle(**{
                        **common,
                        "host_snapshot": replace(bundle.host_snapshot, profile_identifier="other-profile"),
                    }),
                    bundle.bundle_fingerprint,
                )
                bundles.append(bundle)
        self.assertNotEqual(bundles[0].bundle_fingerprint, bundles[1].bundle_fingerprint)
        self.assertEqual(bundles[0].graph_mapping, bundles[1].graph_mapping)

    def test_default_application_rejects_candidate_host_before_staging(self):
        context, observations = fake_checkout(self.root, COMFYUI_0345_QUALIFICATION_PROFILE)
        outcome = self.run_application(context, observations)
        self.assertIs(outcome[0].compatibility, DEFAULT_SUPPORTED_PROFILE)
        self.assert_rejected_before_staging(
            outcome, context,
            {"runtime.host_profile", "runtime.host_version", "runtime.host_revision", "runtime.node_contract_mismatch"},
        )

    def test_normal_route_context_prepares_exact_0346_without_profile_injection(self):
        context, observations = fake_checkout(self.root, DEFAULT_SUPPORTED_PROFILE)
        host = context.host_configuration
        folder_paths = SimpleNamespace(
            __file__=str(host.comfyui_root / "folder_paths.py"),
            models_dir=str(host.model_root),
            get_input_directory=lambda: str(host.input_directory),
            get_output_directory=lambda: str(host.output_directory),
            get_user_directory=lambda: str(host.user_directory),
            get_folder_paths=lambda category: host.model_directories[category],
        )
        with patch.dict(sys.modules, {
            "folder_paths": folder_paths,
            "comfy": SimpleNamespace(),
            "comfy.cli_args": SimpleNamespace(args=SimpleNamespace(port=8000)),
        }), patch("socket.socket", side_effect=AssertionError("offline only")):
            context = routes._build_host_context()
            application, result, prepared, execution, _stage, _states = self.run_application(
                context, observations
            )
        self.assertIs(application.compatibility, DEFAULT_SUPPORTED_PROFILE)
        self.assertTrue(prepared.ready, prepared.errors)
        self.assertEqual(result.state, "completed")
        self.assertEqual(prepared.bundle.profile_identifier, "comfyui-0.34.6.prediction-mixing.v1")
        self.assertEqual(prepared.bundle.inventory_identifier, "krea2-turbo-bf16-1024-comfyui-0.34.6.v1")
        self.assertEqual(prepared.bundle.provenance.comfyui_revision,
                         "8fed37813848259fbdd2548ae3cd9f14df7fd68b")
        self.assertEqual(prepared.bundle.provenance.node_contract_snapshot_fingerprint,
                         "174ac696ee790419563c48481cf12e532c0aa133431c46f72c8f25e8bc6f47ca")
        self.assertIs(execution.call_args.kwargs["trusted_snapshot"], DEFAULT_SUPPORTED_PROFILE.node_snapshot)

    def test_default_rejects_historical_0280_host_before_staging(self):
        context, observations = fake_checkout(self.root, COMFYUI_0280_SUPPORTED_PROFILE)
        self.assert_rejected_before_staging(
            self.run_application(context, observations), context,
            {"runtime.host_profile", "runtime.host_version", "runtime.host_revision"},
        )

    def test_default_rejects_other_versions_and_wrong_0346_revision(self):
        for version, revision, code in (
            ("0.34.5", DEFAULT_SUPPORTED_PROFILE.inventory.expected_comfyui_revision, "runtime.host_version"),
            ("99.0.0", DEFAULT_SUPPORTED_PROFILE.inventory.expected_comfyui_revision, "runtime.host_version"),
            ("0.34.6", "f" * 40, "runtime.host_revision"),
        ):
            with self.subTest(version=version, revision=revision):
                context, observations = fake_checkout(self.root / version, DEFAULT_SUPPORTED_PROFILE)
                checkout = context.host_configuration.git_checkout_path
                (checkout / "comfyui_version.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
                (checkout / ".git/HEAD").write_text(revision, encoding="utf-8")
                self.assert_rejected_before_staging(
                    self.run_application(context, observations), context, {code},
                )

    def test_default_component_mismatch_rejected_before_staging(self):
        context, observations = fake_checkout(self.root, DEFAULT_SUPPORTED_PROFILE)
        observations[next(iter(observations))] = (1, "f" * 64)
        self.assert_rejected_before_staging(
            self.run_application(context, observations), context,
            {"runtime.component_size", "runtime.component_checksum"},
        )

    def test_candidate_wrong_observed_version_and_revision_fail_before_staging(self):
        for field, code in (("version", "runtime.host_version"), ("revision", "runtime.host_revision")):
            with self.subTest(field=field):
                context, observations = fake_checkout(self.root / field, COMFYUI_0345_QUALIFICATION_PROFILE)
                checkout = context.host_configuration.git_checkout_path
                if field == "version":
                    (checkout / "comfyui_version.py").write_text('__version__ = "0.34.4"\n', encoding="utf-8")
                else:
                    (checkout / ".git" / "HEAD").write_text("f" * 40, encoding="utf-8")
                self.assert_rejected_before_staging(
                    self.run_application(context, observations, compatibility=COMFYUI_0345_QUALIFICATION_PROFILE),
                    context, {code},
                )

    def test_candidate_stale_or_altered_snapshot_fails_before_staging(self):
        candidate = COMFYUI_0345_QUALIFICATION_PROFILE
        contracts = dict(candidate.node_snapshot.contracts)
        contracts["ConditioningSetMask"] = replace(
            contracts["ConditioningSetMask"], required_inputs=("wrong",)
        )
        for name, snapshot in (
            ("stale-m2", COMFYUI_0280_SUPPORTED_PROFILE.node_snapshot),
            ("altered-candidate", replace(candidate.node_snapshot, contracts=contracts)),
        ):
            with self.subTest(snapshot=name):
                context, observations = fake_checkout(self.root / name, candidate)
                self.assert_rejected_before_staging(
                    self.run_application(context, observations, compatibility=replace(candidate, node_snapshot=snapshot)),
                    context, {"runtime.node_contract_mismatch"},
                )

    def test_candidate_component_mismatch_is_still_validated_before_staging(self):
        candidate = COMFYUI_0345_QUALIFICATION_PROFILE
        context, observations = fake_checkout(self.root, candidate)
        path = next(iter(observations))
        observations[path] = (1, "f" * 64)
        self.assert_rejected_before_staging(
            self.run_application(context, observations, compatibility=candidate),
            context, {"runtime.component_size", "runtime.component_checksum"},
        )


if __name__ == "__main__":
    unittest.main()
