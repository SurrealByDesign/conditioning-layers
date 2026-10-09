"""ADR-0024 N=3 preparation/persistence evidence with all live surfaces fenced."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zlib

from conditioning_layers.capabilities.multi_layer import (
    EXACT_THREE_ELIGIBILITY, ORDINARY_PRODUCT_ENTRY_IDENTIFIER,
    product_supported_cardinalities,
)
from conditioning_layers.comfyui.prediction_mixing import (
    COMFYUI_0345_QUALIFICATION_PROFILE, COMFYUI_0372_QUALIFICATION_PROFILE, DEFAULT_SUPPORTED_PROFILE,
    ProfileSupportStatus,
)
from conditioning_layers.comfyui.prediction_mixing.multi_layer import (
    EXACT_THREE_REALIZATION, EXACT_THREE_REALIZATION_COMFYUI_0372,
)
from conditioning_layers.execution.comfyui import ExecutionState
from conditioning_layers.execution.comfyui.multi_layer import (
    build_multi_layer_execution_provenance, execute_multi_layer_submission_bundle,
    validate_multi_layer_execution_provenance,
)
from conditioning_layers.integrations.comfyui_panel.application import (
    ExistingBackendApplication, PreparedPanelExecution, materialize_document,
)
from conditioning_layers.integrations.comfyui_panel.documents import PanelDocumentStore
from conditioning_layers.integrations.comfyui_panel.models import (
    PanelExecutionDraft, PanelLayerDraft, PanelRunResult, RetainedField, parse_panel_request,
)
from conditioning_layers.integrations.comfyui_panel.starter_fields import read_starter_field
from conditioning_layers.persistence import document_asset_root
from conditioning_layers.runtime.comfyui.multi_layer import (
    fingerprint_portable, validate_multi_layer_submission_bundle,
)

from _support import metadata, row, upload
from test_compatibility_injection import fake_checkout, model_file_observations
from test_documents import retained_rows, save_draft


ROOT = Path(__file__).resolve().parents[4]
EXECUTION_ID = "3" * 32
SEED = 18472639
APPLICATION = "conditioning_layers.integrations.comfyui_panel.application"
RUNTIME = "conditioning_layers.runtime.comfyui.multi_layer"
FAMILIES = ("three-layer.vertical-thirds.v1", "three-layer.horizontal-thirds.v1")
FENCES = (
    "socket.socket", "socket.create_connection", "socket.getaddrinfo",
    "urllib.request.urlopen", "urllib.request.OpenerDirector.open",
    "http.client.HTTPConnection.connect", "subprocess.Popen", "webbrowser.open",
    "os.system", "os.startfile",
)


def no_live_activity(*args, **kwargs):
    raise AssertionError("P2B preparation is offline: live activity forbidden")


def png_from_samples(samples):
    def chunk(kind, payload):
        content = kind + payload
        return struct.pack(">I", len(payload)) + content + struct.pack(">I", zlib.crc32(content))

    header = struct.pack(">IIBBBBB", 128, 128, 8, 0, 0, 0, 0)
    scanlines = b"".join(b"\x00" + bytes(samples[y * 128:(y + 1) * 128]) for y in range(128))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(scanlines, level=9)) + chunk(b"IEND", b""))


def synthetic_fields(*, gaps=False, continuous=False, overlap_pair=None):
    samples = [[0] * (128 * 128) for _ in range(3)]
    for y in range(128):
        for x in range(128):
            ordinal = min(x * 3 // 128, 2)
            if gaps and x % 16 < 4:
                continue
            samples[ordinal][y * 128 + x] = 32 + y if continuous else 255
    if overlap_pair is not None:
        left, right = overlap_pair
        index = next(i for i, value in enumerate(samples[left]) if value)
        samples[right][index] = 1
    return tuple(png_from_samples(values) for values in samples)


def fixture_request(family=FAMILIES[0], *, field_data=None, strengths=(1.0, 1.0, 1.0)):
    data = field_data or tuple(read_starter_field(f"{family}:{letter}") for letter in "ABC")
    rows = [row(letter.lower(), prompt=prompt, strength=strengths[index]) for index, (letter, prompt) in enumerate(zip(
        "ABC", ("A red ceramic vessel", "A blue glass vessel", "A green stone vessel"), strict=True,
    ))]
    for item, letter in zip(rows, "ABC", strict=True):
        item["layer_id"] = f"layer-{letter}"
    payload = json.loads(metadata(rows, base_prompt="A quiet studio with three distinct vessels", key="p2b-offline"))
    payload.update(document_id="p2b-canonical-document", seed=str(SEED))
    body = json.dumps(payload).encode()
    uploads = {f"field-{letter.lower()}": upload(letter.lower(), item) for letter, item in zip("ABC", data, strict=True)}
    return parse_panel_request(body, uploads, multipart_part_count=4,
                               total_bytes=len(body) + sum(len(item) for item in data))


def prepare_case(root, request, *, qualification=False):
    context, observations = fake_checkout(root, DEFAULT_SUPPORTED_PROFILE)
    options = {"qualification_entry": EXACT_THREE_ELIGIBILITY} if qualification else {}
    application = ExistingBackendApplication(context, execution_client=no_live_activity, **options)
    with model_file_observations(observations):
        prepared = application.prepare(request, EXECUTION_ID, lambda _: None)
    return prepared, context, observations


def canonical_snapshot(family=FAMILIES[0]):
    """Portable offline identities only; no execution event or success is claimed."""
    with tempfile.TemporaryDirectory(prefix="p2b-canonical-") as temporary:
        prepared, _, _ = prepare_case(Path(temporary), fixture_request(family))
        assert isinstance(prepared, PreparedPanelExecution), prepared
        bundle = prepared.bundle
        plan = bundle.graph_artifact.source_plan
        provenance = build_multi_layer_execution_provenance(
            bundle=bundle, server_identity=None, prompt_id=None,
            terminal_state=ExecutionState.NOT_SUBMITTED, outputs=(), errors=(), warnings=(),
        )
        return {
            "fixture": family, "seed": bundle.runtime_seed,
            "entry_identifier": bundle.eligibility_entry_identifier,
            "entry_fingerprint": bundle.eligibility_entry_fingerprint,
            "exact_cardinality": bundle.exact_admitted_cardinality,
            "profile_identifier": bundle.execution_profile_identifier,
            "profile_fingerprint": bundle.execution_profile_fingerprint,
            "plan_identifier": bundle.translation_plan_identifier,
            "plan_fingerprint": plan.fingerprint,
            "binding_identifier": bundle.realization_binding_identifier,
            "binding_fingerprint": bundle.realization_binding_fingerprint,
            "graph_identifier": bundle.graph_version,
            "graph_fingerprint": bundle.graph_fingerprint,
            "graph": bundle.to_api_graph(),
            "certificate_fingerprint": plan.certificate.fingerprint,
            "bundle_identifier": bundle.bundle_version,
            "bundle_fingerprint": bundle.bundle_fingerprint,
            "runtime_provenance_fingerprint": fingerprint_portable(bundle.provenance),
            "execution_provenance_identifier": provenance.provenance_version,
            "not_submitted_provenance_fingerprint": provenance.provenance_fingerprint,
        }


class MultiLayerApplicationTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        for target in FENCES:
            stack.enter_context(patch(target, side_effect=no_live_activity, create=True))
        self.temporary = stack.enter_context(tempfile.TemporaryDirectory(prefix="p2b-application-"))
        self.root = Path(self.temporary)

    def prepare(self, request, *, name="case", qualification=False):
        return prepare_case(self.root / name, request, qualification=qualification)

    def assert_prepared(self, prepared):
        self.assertIsInstance(prepared, PreparedPanelExecution, prepared)
        self.assertTrue(prepared.multi_layer)
        bundle = prepared.bundle
        self.assertTrue(bundle.submission_ready)
        self.assertEqual(bundle.exact_admitted_cardinality, 3)
        self.assertEqual(len(bundle.staged_assets), 3)
        self.assertTrue(all(item.destination_path.is_file() for item in bundle.staged_assets))
        self.assertEqual(len(bundle.graph_artifact.source_plan.certificate.pairwise_evidence), 3)
        return bundle

    def test_vertical_and_horizontal_thirds_prepare_through_real_inspection_host_and_staging(self):
        for family in FAMILIES:
            with self.subTest(family=family):
                bundle = self.assert_prepared(self.prepare(fixture_request(family), name=family)[0])
                graph = bundle.to_api_graph()
                self.assertEqual(len(graph), 19)
                self.assertEqual(sum(isinstance(value, list) for node in graph.values() for value in node["inputs"].values()), 21)
                self.assertEqual([graph[str(i)]["class_type"] for i in (3, 4, 5)], ["CLIPTextEncode"] * 3)
                self.assertEqual(graph["13"]["inputs"], {"conditioning_1": ["10", 0], "conditioning_2": ["11", 0]})
                self.assertEqual(graph["14"]["inputs"], {"conditioning_1": ["13", 0], "conditioning_2": ["12", 0]})
                self.assertEqual(graph["16"]["inputs"]["positive"], ["14", 0])
                self.assertEqual(bundle.runtime_seed, SEED)

    def test_closed_admission_fixture_rejects_three_before_translation_and_staging(self):
        with patch("conditioning_layers.capabilities.multi_layer.PRODUCT_ADMITTED_ENTRIES", (
            ORDINARY_PRODUCT_ENTRY_IDENTIFIER,
        )), patch(f"{APPLICATION}.translate_prediction_mixing") as ordinary, patch(
            "conditioning_layers.adapters.prediction_mixing.multi_layer.translate_prediction_mixing_multi_layer"
        ) as successor, patch(f"{RUNTIME}.stage_field_assets") as stage:
            self.assertEqual(product_supported_cardinalities(), (1, 2))
            prepared, context, _ = self.prepare(fixture_request())
        self.assertIsInstance(prepared, PanelRunResult)
        self.assertEqual(prepared.state, "rejected")
        self.assertIn("capability.product_not_admitted", {item.code for item in prepared.findings})
        ordinary.assert_not_called()
        successor.assert_not_called()
        stage.assert_not_called()
        self.assertFalse((context.host_configuration.input_directory / "conditioning-layers").exists())

    def test_normal_product_and_qualification_preparation_have_identical_frozen_identities(self):
        request = fixture_request()
        qualified = self.assert_prepared(self.prepare(request, name="qualified", qualification=True)[0])
        admitted = self.assert_prepared(self.prepare(request, name="admitted")[0])
        self.assertEqual(qualified.eligibility_entry_identifier, EXACT_THREE_ELIGIBILITY.identifier)
        self.assertEqual(admitted.eligibility_entry_identifier, EXACT_THREE_ELIGIBILITY.identifier)
        self.assertEqual(admitted.eligibility_entry_fingerprint, EXACT_THREE_ELIGIBILITY.fingerprint)
        self.assertEqual(qualified.graph_artifact.source_plan, admitted.graph_artifact.source_plan)
        self.assertEqual(qualified.translation_plan_fingerprint, admitted.translation_plan_fingerprint)
        self.assertEqual(qualified.graph_fingerprint, admitted.graph_fingerprint)
        self.assertEqual(qualified.to_api_graph(), admitted.to_api_graph())
        self.assertEqual(qualified.bundle_fingerprint, admitted.bundle_fingerprint)
        self.assertEqual(qualified.provenance, admitted.provenance)
        self.assertEqual(product_supported_cardinalities(), (1, 2, 3))

    def test_normal_product_run_selects_real_multi_layer_client_once_and_projects_safe_output(self):
        context, observations = fake_checkout(self.root / "normal-run", DEFAULT_SUPPORTED_PROFILE)
        requests, states = [], []
        prompt_id = "11111111-1111-4111-8111-111111111111"
        inventory = DEFAULT_SUPPORTED_PROFILE.inventory

        def get_json(path):
            requests.append(("GET", path, None))
            if path == "/system_stats":
                return {"system": {
                    "comfyui_version": inventory.expected_comfyui_version,
                    "git_revision": inventory.expected_comfyui_revision,
                }, "devices": []}
            if path == "/queue":
                return {"queue_running": [], "queue_pending": []}
            if path == f"/history/{prompt_id}":
                return {prompt_id: {
                    "status": {"status_str": "success", "completed": True, "messages": []},
                    "outputs": {"19": {"images": [{
                        "filename": f"{EXECUTION_ID}_00001_.png",
                        "subfolder": "conditioning-layers-panel", "type": "output",
                    }]}},
                }}
            raise AssertionError(f"Unexpected memory-only read: {path}")

        def post_json(path, payload):
            self.assertEqual(path, "/prompt")
            self.assertFalse(any(item[0] == "POST" for item in requests))
            requests.append(("POST", path, payload))
            return {"prompt_id": prompt_id}

        transport = SimpleNamespace(
            configuration=context.server_configuration, get_json=get_json, post_json=post_json,
        )
        with model_file_observations(observations), patch(
            "conditioning_layers.execution.comfyui.multi_layer.LocalJsonTransport", return_value=transport,
        ) as factory, patch(
            "conditioning_layers.execution.comfyui.multi_layer.execute_multi_layer_submission_bundle",
            wraps=execute_multi_layer_submission_bundle,
        ) as client, patch(f"{APPLICATION}.prepare_submission_bundle") as ordinary:
            result = ExistingBackendApplication(context).run(fixture_request(), EXECUTION_ID, states.append)
        self.assertEqual(result.state, "completed", result.findings)
        self.assertEqual(states, ["validating", "preparing", "executing"])
        client.assert_called_once()
        factory.assert_called_once_with(context.server_configuration)
        ordinary.assert_not_called()
        bundle = client.call_args.args[0]
        self.assertEqual(bundle.eligibility_entry_identifier, EXACT_THREE_ELIGIBILITY.identifier)
        self.assertEqual(bundle.exact_admitted_cardinality, 3)
        self.assertIs(client.call_args.kwargs["trusted_snapshot"], DEFAULT_SUPPORTED_PROFILE.node_snapshot)
        submissions = [item for item in requests if item[0] == "POST"]
        self.assertEqual(len(submissions), 1)
        self.assertEqual(submissions[0][2]["prompt"], bundle.to_api_graph())
        self.assertEqual(result.output.view_url,
                         f"/view?filename={EXECUTION_ID}_00001_.png&subfolder=conditioning-layers-panel&type=output")

    def test_distinct_strengths_are_in_plan_graph_and_provenance(self):
        strengths = (0.5, 1.0, 0.75)
        bundle = self.assert_prepared(self.prepare(fixture_request(strengths=strengths))[0])
        plan = bundle.graph_artifact.source_plan
        self.assertEqual(tuple(item.requested_strength for item in plan.regional_conditions), strengths)
        self.assertEqual(tuple(bundle.to_api_graph()[str(i)]["inputs"]["strength"] for i in (10, 11, 12)), strengths)
        self.assertEqual(tuple(item.requested_strength for item in bundle.provenance.workflow_provenance.active_layers), strengths)

    def test_one_and_all_zero_strength_active_layers_are_retained(self):
        bundles = []
        for index, strengths in enumerate(((0.0, 1.0, 0.75), (0.0, 0.0, 0.0), (-0.0, -0.0, -0.0))):
            with self.subTest(strengths=strengths):
                bundle = self.assert_prepared(self.prepare(fixture_request(strengths=strengths), name=str(index))[0])
                self.assertEqual(len(bundle.graph_artifact.source_plan.regional_conditions), 3)
                self.assertEqual(len(bundle.to_api_graph()), 19)
                bundles.append(bundle)
        self.assertEqual(bundles[1].translation_plan_fingerprint, bundles[2].translation_plan_fingerprint)
        self.assertEqual(bundles[1].graph_fingerprint, bundles[2].graph_fingerprint)
        self.assertEqual(bundles[1].bundle_fingerprint, bundles[2].bundle_fingerprint)
        self.assertEqual(fingerprint_portable(bundles[1].provenance), fingerprint_portable(bundles[2].provenance))
        provenance = tuple(build_multi_layer_execution_provenance(
            bundle=bundle, server_identity=None, prompt_id=None,
            terminal_state=ExecutionState.NOT_SUBMITTED, outputs=(), errors=(), warnings=(),
        ) for bundle in bundles[1:])
        self.assertEqual(provenance[0].provenance_fingerprint, provenance[1].provenance_fingerprint)

    def test_disjoint_gaps_and_continuous_full_coverage_are_accepted_custom_pngs(self):
        for name, gaps, continuous in (("gaps", True, False), ("continuous", False, True), ("soft-gaps", True, True)):
            with self.subTest(name=name):
                bundle = self.assert_prepared(self.prepare(fixture_request(field_data=synthetic_fields(gaps=gaps, continuous=continuous)), name=name)[0])
                plan = bundle.graph_artifact.source_plan
                whole = plan.certificate.whole_set_evidence
                self.assertEqual(whole.complete_coverage, not gaps)
                self.assertTrue(whole.mutual_exclusion)
                if continuous:
                    self.assertLess(whole.maximum_normalized_total_sum, 1.0)
                    self.assertTrue(all(item.field_profile.value_kind.value == "continuous" for item in plan.regional_conditions))

    def test_each_pair_and_zero_strength_overlap_reject_without_artifact_or_staging(self):
        for index, (pair, strengths) in enumerate((((0, 1), (1.0, 1.0, 1.0)), ((0, 2), (1.0, 1.0, 1.0)), ((1, 2), (1.0, 1.0, 1.0)), ((0, 2), (0.0, 1.0, 1.0)))):
            with self.subTest(pair=pair, strengths=strengths), patch(f"{RUNTIME}.stage_field_assets") as stage:
                prepared, _, _ = self.prepare(fixture_request(field_data=synthetic_fields(overlap_pair=pair), strengths=strengths), name=str(index))
            self.assertIsInstance(prepared, PanelRunResult)
            self.assertEqual(prepared.state, "rejected")
            self.assertTrue(any("overlap" in item.code for item in prepared.findings), prepared.findings)
            stage.assert_not_called()

    def test_four_active_rejects_normal_and_qualification_before_translation_or_staging(self):
        request = fixture_request()
        request = replace(request, layers=request.layers + (replace(request.layers[-1], row_id="d", layer_id="layer-D"),))
        for qualification in (False, True):
            with self.subTest(qualification=qualification), patch(
                "conditioning_layers.adapters.prediction_mixing.multi_layer.translate_prediction_mixing_multi_layer"
            ) as translate, patch(f"{APPLICATION}.translate_prediction_mixing") as ordinary, patch(
                f"{RUNTIME}.stage_field_assets"
            ) as stage:
                prepared, _, _ = self.prepare(request, name=str(qualification), qualification=qualification)
            self.assertIsInstance(prepared, PanelRunResult)
            self.assertIn("capability.active_layer_limit", {item.code for item in prepared.findings})
            translate.assert_not_called()
            ordinary.assert_not_called()
            stage.assert_not_called()

    def test_missing_malformed_and_changed_field_fail_before_staging(self):
        for mode in ("missing", "malformed", "changed"):
            def materialize(*args, **kwargs):
                value = materialize_document(*args, **kwargs)
                target = value.asset_root / value.document.layers[1].influence_field.relative_path
                if mode == "missing":
                    target.unlink()
                elif mode == "changed":
                    target.write_bytes(synthetic_fields()[0])
                return value
            request = fixture_request()
            if mode == "malformed":
                # Materialization computes the correct checksum of malformed
                # PNG bytes, so this reaches decode validation, not hash drift.
                request = replace(request, layers=(request.layers[0], replace(
                    request.layers[1], field=upload("b", b"\x89PNG\r\n\x1a\ninvalid"),
                ), request.layers[2]))
            with self.subTest(mode=mode), patch(f"{APPLICATION}.materialize_document", side_effect=materialize), patch(f"{RUNTIME}.stage_field_assets") as stage, patch(f"{APPLICATION}.translate_prediction_mixing") as ordinary:
                prepared, _, _ = self.prepare(request, name=mode)
            self.assertIsInstance(prepared, PanelRunResult)
            self.assertEqual(prepared.state, "rejected")
            self.assertTrue(prepared.findings)
            stage.assert_not_called()
            ordinary.assert_not_called()

    def test_custom_import_of_preset_bytes_and_display_names_do_not_change_execution_identity(self):
        preset = fixture_request()
        imported = fixture_request(field_data=tuple(item.field.data for item in preset.layers))
        imported = replace(imported, layers=tuple(replace(item, name=f"Renamed {index}") for index, item in enumerate(imported.layers)))
        first = self.assert_prepared(self.prepare(preset, name="preset")[0])
        second = self.assert_prepared(self.prepare(imported, name="custom")[0])
        self.assertEqual(first.translation_plan_fingerprint, second.translation_plan_fingerprint)
        self.assertEqual(first.graph_fingerprint, second.graph_fingerprint)
        self.assertEqual(first.bundle_fingerprint, second.bundle_fingerprint)

    def test_reorder_changes_identity_and_retains_requested_order(self):
        request = fixture_request()
        original = self.assert_prepared(self.prepare(request, name="original")[0])
        reordered = self.assert_prepared(self.prepare(replace(request, layers=tuple(reversed(request.layers))), name="reordered")[0])
        self.assertNotEqual(original.translation_plan_fingerprint, reordered.translation_plan_fingerprint)
        self.assertNotEqual(original.graph_fingerprint, reordered.graph_fingerprint)
        self.assertEqual(tuple(item.layer_id for item in reordered.provenance.workflow_provenance.active_layers), ("layer-C", "layer-B", "layer-A"))

    def test_save_open_resave_preserves_three_active_layers_owned_bytes_and_prepares_without_library(self):
        request = fixture_request(strengths=(0.5, 1.0, 0.75))
        store = PanelDocumentStore(self.root / "saved-user")
        rows = [row(item.row_id, name=item.name, prompt=item.prompt_text, strength=item.strength) for item in request.layers]
        uploads = {item.field.part_name: item.field for item in request.layers}
        saved = store.save_as(save_draft("Three Layers", rows, uploads=uploads, base_prompt=request.base_prompt))
        opened = store.open(saved.document_key)
        saved_again = store.save(opened.document_key, save_draft("Three Layers", retained_rows(opened), source=opened.document_key, document_id=opened.document.document_id, base_prompt=opened.document.base_prompt))
        self.assertEqual(saved.document, opened.document)
        self.assertEqual(saved_again.document, opened.document)
        self.assertEqual(saved.field_bytes, opened.field_bytes)
        self.assertEqual(saved_again.field_bytes, opened.field_bytes)
        self.assertEqual(tuple(layer.visible for layer in opened.document.layers), (True, True, True))
        asset_root = document_asset_root(store.root / f"{saved.document_key}.conditioning.json")
        for layer, draft_layer in zip(opened.document.layers, request.layers, strict=True):
            self.assertEqual((asset_root / layer.influence_field.relative_path).read_bytes(), draft_layer.field.data)
            self.assertEqual(layer.influence_field.checksum, hashlib.sha256(draft_layer.field.data).hexdigest())
        retained = PanelExecutionDraft(base_prompt=opened.document.base_prompt, layers=tuple(PanelLayerDraft(
            row_id=f"opened-{index}", layer_id=layer.layer_id, name=layer.name, prompt_text=layer.prompt_text,
            strength=layer.strength, active=layer.visible, field=RetainedField(layer.layer_id),
        ) for index, layer in enumerate(opened.document.layers)), idempotency_key="p2b-reopened", document_id=opened.document.document_id, document_key=opened.document_key, seed=SEED)
        context, observations = fake_checkout(self.root / "opened-host", DEFAULT_SUPPORTED_PROFILE)
        context = replace(context, host_configuration=replace(
            context.host_configuration, user_directory=self.root / "saved-user", data_trusted_root=self.root,
        ))
        with model_file_observations(observations), patch("conditioning_layers.integrations.comfyui_panel.starter_fields.read_starter_field", side_effect=AssertionError("Saved fields do not consult library authority")):
            prepared = ExistingBackendApplication(context).prepare(retained, EXECUTION_ID, lambda _: None)
        self.assert_prepared(prepared)

    def test_repeated_same_input_has_identical_plan_graph_bundle_and_provenance(self):
        first = canonical_snapshot()
        second = canonical_snapshot()
        self.assertEqual(first, second)

    def test_repeated_preparation_reusing_staged_bytes_has_identical_identity(self):
        request = fixture_request()
        prepared, context, observations = self.prepare(request)
        first = self.assert_prepared(prepared)
        with model_file_observations(observations):
            repeated = ExistingBackendApplication(context).prepare(
                request, EXECUTION_ID, lambda _: None,
            )
        second = self.assert_prepared(repeated)
        self.assertEqual(first.translation_plan_fingerprint, second.translation_plan_fingerprint)
        self.assertEqual(first.graph_fingerprint, second.graph_fingerprint)
        self.assertEqual(first.to_api_graph(), second.to_api_graph())
        self.assertEqual(first.bundle_fingerprint, second.bundle_fingerprint)
        self.assertEqual(first.provenance, second.provenance)


class HostSelectedMultiLayerTests(unittest.TestCase):
    """0.37.2 N=3 is reachable only by explicit QUALIFICATION_ONLY injection; offline."""

    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        for target in FENCES:
            stack.enter_context(patch(target, side_effect=no_live_activity, create=True))
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="p2b-host-")))

    def prepare(self, name, checkout, compatibility=None):
        context, observations = fake_checkout(self.root / name, checkout)
        options = {} if compatibility is None else {"compatibility": compatibility}
        application = ExistingBackendApplication(context, execution_client=no_live_activity, **options)
        with model_file_observations(observations):
            return application.prepare(fixture_request(), EXECUTION_ID, lambda _: None), context

    def test_explicit_0372_profile_prepares_under_its_own_binding(self):
        profile = COMFYUI_0372_QUALIFICATION_PROFILE
        retained, _ = self.prepare("retained", DEFAULT_SUPPORTED_PROFILE)
        current, _ = self.prepare("current", profile, profile)
        self.assertIsInstance(retained, PreparedPanelExecution, retained)
        self.assertIsInstance(current, PreparedPanelExecution, current)
        old, new = retained.bundle, current.bundle
        self.assertEqual((old.realization_binding_identifier, old.realization_binding_fingerprint),
                         (EXACT_THREE_REALIZATION.identifier, EXACT_THREE_REALIZATION.fingerprint))
        self.assertEqual((new.realization_binding_identifier, new.realization_binding_fingerprint),
                         (EXACT_THREE_REALIZATION_COMFYUI_0372.identifier, EXACT_THREE_REALIZATION_COMFYUI_0372.fingerprint))
        self.assertEqual((new.profile_identifier, new.inventory_identifier),
                         (profile.inventory.comfyui_profile_identifier, profile.inventory.inventory_identifier))
        self.assertEqual((new.host_snapshot.observed_comfyui_revision, new.host_snapshot.node_contract_snapshot_fingerprint),
                         (profile.inventory.expected_comfyui_revision, profile.node_snapshot.snapshot_fingerprint))
        # Same entry, plan and API graph; only host-bound identities differ.
        self.assertEqual(new.eligibility_entry_fingerprint, old.eligibility_entry_fingerprint)
        self.assertEqual(new.translation_plan_fingerprint, old.translation_plan_fingerprint)
        self.assertEqual(new.to_api_graph(), old.to_api_graph())
        self.assertNotEqual(new.graph_fingerprint, old.graph_fingerprint)
        self.assertEqual(validate_multi_layer_submission_bundle(new), ())
        provenance = build_multi_layer_execution_provenance(
            bundle=new, server_identity=None, prompt_id=None, terminal_state=ExecutionState.NOT_SUBMITTED,
            outputs=(), errors=(), warnings=(),
        )
        self.assertEqual(validate_multi_layer_execution_provenance(provenance, new), ())
        for changed in (
            replace(new, host_snapshot=old.host_snapshot), replace(new, graph_artifact=old.graph_artifact),
            replace(new, profile_identifier=old.profile_identifier),
            replace(new, inventory_identifier=old.inventory_identifier),
        ):
            self.assertEqual({item.code for item in validate_multi_layer_submission_bundle(changed)},
                             {"runtime.multi_layer_bundle_invalid"})

    def test_unbound_promoted_or_mismatched_hosts_fail_closed_before_staging(self):
        promoted = replace(COMFYUI_0372_QUALIFICATION_PROFILE, status=ProfileSupportStatus.SUPPORTED)
        for index, (name, checkout, compatibility, expected) in enumerate((
            ("caller-promoted 0.37.2", COMFYUI_0372_QUALIFICATION_PROFILE, promoted,
             {"multi_layer.realization.invalid"}),
            ("registered 0.34.5 without N=3 authority", COMFYUI_0345_QUALIFICATION_PROFILE,
             COMFYUI_0345_QUALIFICATION_PROFILE, {"multi_layer.realization.invalid"}),
            ("unchanged product default on a 0.37.2 checkout", COMFYUI_0372_QUALIFICATION_PROFILE, None, None),
            ("0.37.2 profile on a 0.34.6 checkout", DEFAULT_SUPPORTED_PROFILE, COMFYUI_0372_QUALIFICATION_PROFILE, None),
        )):
            with self.subTest(name):
                prepared, context = self.prepare(f"case-{index}", checkout, compatibility)
                self.assertIsInstance(prepared, PanelRunResult, prepared)
                self.assertEqual(prepared.state, "rejected")
                codes = {item.code for item in prepared.findings}
                if expected is None:
                    # The selected authority is valid; the observed host is not that host.
                    self.assertTrue(codes and all(code.startswith("runtime.") for code in codes), codes)
                else:
                    self.assertEqual(codes, expected)
                self.assertFalse((context.host_configuration.input_directory / "conditioning-layers").exists())

    def test_explicit_0372_run_submits_once_in_memory_with_its_own_trusted_snapshot(self):
        profile = COMFYUI_0372_QUALIFICATION_PROFILE
        context, observations = fake_checkout(self.root / "run", profile)
        requests, prompt_id = [], "22222222-2222-4222-8222-222222222222"

        def get_json(path):
            requests.append(("GET", path, None))
            if path == "/system_stats":
                return {"system": {
                    "comfyui_version": profile.inventory.expected_comfyui_version,
                    "git_revision": profile.inventory.expected_comfyui_revision,
                }, "devices": []}
            if path == "/queue":
                return {"queue_running": [], "queue_pending": []}
            if path == f"/history/{prompt_id}":
                return {prompt_id: {
                    "status": {"status_str": "success", "completed": True, "messages": []},
                    "outputs": {"19": {"images": [{
                        "filename": f"{EXECUTION_ID}_00001_.png",
                        "subfolder": "conditioning-layers-panel", "type": "output",
                    }]}},
                }}
            raise AssertionError(f"Unexpected memory-only read: {path}")

        def post_json(path, payload):
            requests.append(("POST", path, payload))
            return {"prompt_id": prompt_id}

        transport = SimpleNamespace(configuration=context.server_configuration, get_json=get_json, post_json=post_json)
        with model_file_observations(observations), patch(
            "conditioning_layers.execution.comfyui.multi_layer.LocalJsonTransport", return_value=transport,
        ), patch(
            "conditioning_layers.execution.comfyui.multi_layer.execute_multi_layer_submission_bundle",
            wraps=execute_multi_layer_submission_bundle,
        ) as client:
            result = ExistingBackendApplication(context, compatibility=profile).run(
                fixture_request(), EXECUTION_ID, lambda _: None,
            )
        self.assertEqual(result.state, "completed", result.findings)
        client.assert_called_once()
        self.assertIs(client.call_args.kwargs["trusted_snapshot"], profile.node_snapshot)
        self.assertEqual(client.call_args.args[0].realization_binding_identifier,
                         EXACT_THREE_REALIZATION_COMFYUI_0372.identifier)
        self.assertEqual(len([item for item in requests if item[0] == "POST"]), 1)


class MultiLayerFreshProcessTests(unittest.TestCase):
    def test_fresh_process_hash_seed_and_temp_directory_do_not_change_identities(self):
        source = "from test_multi_layer_application import canonical_snapshot; import json; print(json.dumps(canonical_snapshot(), sort_keys=True))"
        snapshots = []
        for seed in ("1", "73"):
            environment = os.environ.copy()
            environment["PYTHONHASHSEED"] = seed
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            environment["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src"), str(Path(__file__).parent)))
            with tempfile.TemporaryDirectory(prefix="p2b-process-") as temporary:
                completed = subprocess.run([sys.executable, "-B", "-W", "error", "-c", source], cwd=temporary, env=environment, capture_output=True, text=True, check=True)
            snapshots.append(json.loads(completed.stdout))
        self.assertEqual(snapshots[0], snapshots[1])


if __name__ == "__main__":
    unittest.main()
