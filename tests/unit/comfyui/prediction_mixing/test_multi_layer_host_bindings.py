"""Additive ComfyUI 0.37.2 N=3 realization authority: exact host selection only.

Offline. Retained 0.34.6 authorities are compared with literal reviewed
identities. The 0.37.2 authorities may differ only by identifier and exact host
pins. No host evidence is observed and no selection falls back to another host.
"""

from dataclasses import replace
from pathlib import Path
import sys
import tempfile
from types import MappingProxyType, SimpleNamespace
import unittest
from unittest.mock import patch

from conditioning_layers.capabilities.blend import EXACT_FOUR_BLEND_ELIGIBILITY, EXACT_THREE_BLEND_ELIGIBILITY
from conditioning_layers.capabilities.multi_layer import EXACT_THREE_ELIGIBILITY
from conditioning_layers.capabilities.product import product_supported_cardinalities
from conditioning_layers.comfyui.prediction_mixing import (
    COMFYUI_0280_SUPPORTED_PROFILE, COMFYUI_0345_QUALIFICATION_PROFILE,
    COMFYUI_0346_QUALIFICATION_PROFILE, COMFYUI_0346_SUPPORTED_PROFILE,
    COMFYUI_0372_QUALIFICATION_PROFILE, DEFAULT_SUPPORTED_PROFILE,
    REGISTERED_COMFYUI_PROFILES, ProfileSupportStatus,
)
from conditioning_layers.comfyui.prediction_mixing.blend import authority as blend_authority
from conditioning_layers.comfyui.prediction_mixing.blend import (
    BLEND_GRAPH_PERMITTED_CLASSES, BLEND_GRAPH_PERMITTED_CLASSES_COMFYUI_0372,
    EXACT_THREE_BLEND_REALIZATION, EXACT_THREE_BLEND_REALIZATION_COMFYUI_0372,
    generate_prediction_mixing_blend_workflow, select_blend_realization,
    validate_blend_artifact, verify_permitted_class_authority,
)
from conditioning_layers.comfyui.prediction_mixing.blend import realization_host_profile as blend_host_profile
from conditioning_layers.comfyui.prediction_mixing.generalized_blend import (
    REGISTERED_GENERALIZED_BLEND_REALIZATION_BINDINGS,
)
from conditioning_layers.comfyui.prediction_mixing.multi_layer import authority
from conditioning_layers.comfyui.prediction_mixing.multi_layer import (
    EXACT_THREE_REALIZATION, EXACT_THREE_REALIZATION_COMFYUI_0372,
    generate_prediction_mixing_multi_layer_workflow, realization_host_profile,
    select_realization_binding, validate_multi_layer_artifact, verify_realization_binding,
)
from conditioning_layers.comfyui.prediction_mixing.multi_layer.canonical import (
    canonical_bytes, fingerprint, json_value,
)
from conditioning_layers.comfyui.prediction_mixing.node_contracts import fingerprint_host_node_contract_snapshot

from test_multi_layer_graph import fixture as no_overlap_fixture

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tooling"))
from blend_fixture import blend_fixture


P0346, P0372 = COMFYUI_0346_SUPPORTED_PROFILE, COMFYUI_0372_QUALIFICATION_PROFILE
B0346, B0372 = EXACT_THREE_REALIZATION, EXACT_THREE_REALIZATION_COMFYUI_0372
X0346, X0372 = EXACT_THREE_BLEND_REALIZATION, EXACT_THREE_BLEND_REALIZATION_COMFYUI_0372
C0346, C0372 = BLEND_GRAPH_PERMITTED_CLASSES, BLEND_GRAPH_PERMITTED_CLASSES_COMFYUI_0372
REVIEWED = (
    (B0346, "prediction-mixing.multi-layer.realization.exact-3.comfyui-0.34.6.v1",
     "1374a3b76426b10e69d4cd2f4510b7ee2801035dbee850e6c4698bfd6ca684c6"),
    (X0346, "prediction-mixing.multi-layer.realization.exact-3.normalized-blend.comfyui-0.34.6.v1",
     "8264274afbcbb7db30f3389fd03289618bfa4b99e104d0d71405f620cec3f781"),
    (C0346, "prediction-mixing.normalized-blend.graph-permitted-classes.v1",
     "64ef986a170b8e84cf24287b32681e20ae768b32f95ce4817c917f4d972479bd"),
    (B0372, "prediction-mixing.multi-layer.realization.exact-3.comfyui-0.37.2.v1",
     "34e7dfbb218c3211cfe019e0cbe76e722a52f5e4b45d5d7822b31a9b680b50e9"),
    (X0372, "prediction-mixing.multi-layer.realization.exact-3.normalized-blend.comfyui-0.37.2.v1",
     "3da29d14ede0958be81e2809ccd5c8b27cda5647cba0b46e796b2f38386b6f9e"),
    (C0372, "prediction-mixing.normalized-blend.graph-permitted-classes.comfyui-0.37.2.v1",
     "308b32ffae42ee611146a9af1446cda943aeed0ca88130ad1a844e9db401b812"),
)
HOST_FIELDS = ("identifier", "fingerprint", "inventory_identifier", "inventory_fingerprint",
               "snapshot_identifier", "snapshot_fingerprint", "comfyui_profile_identifier", "comfyui_revision")
BLEND_HOST_FIELDS = HOST_FIELDS + ("permitted_class_authority_identifier", "permitted_class_authority_fingerprint")
CLASS_HOST_FIELDS = ("identifier", "fingerprint", "retained_inventory_identifier", "retained_inventory_fingerprint")


def resign(value):
    return replace(value, fingerprint=blend_authority.fingerprint_authority(value))


def pins(binding):
    return (binding.comfyui_profile_identifier, binding.comfyui_revision, binding.inventory_identifier,
            binding.inventory_fingerprint, binding.snapshot_identifier, binding.snapshot_fingerprint)


def host_pins(profile):
    inventory, snapshot = profile.inventory, profile.node_snapshot
    return (inventory.comfyui_profile_identifier, inventory.expected_comfyui_revision,
            inventory.inventory_identifier, fingerprint(inventory), snapshot.snapshot_identifier,
            fingerprint_host_node_contract_snapshot(snapshot))


def without(value, names):
    material = json_value(value)
    for name in names:
        material.pop(name)
    return material


def select(profile):
    return (select_realization_binding(EXACT_THREE_ELIGIBILITY, profile),
            select_blend_realization(EXACT_THREE_BLEND_ELIGIBILITY, profile))


class AdditiveHostAuthorityTests(unittest.TestCase):
    def test_every_authority_keeps_its_literal_reviewed_identity(self):
        for value, identifier, digest in REVIEWED:
            with self.subTest(identifier=identifier):
                self.assertEqual((value.identifier, value.fingerprint), (identifier, digest))
                self.assertEqual(blend_authority.fingerprint_authority(value), digest)
        self.assertEqual(EXACT_THREE_ELIGIBILITY.fingerprint,
                         "fc1c0d96a8de733ebcb71f08b2db3123a588da8afcf046bd70c92852cd9b6c55")
        self.assertEqual(EXACT_THREE_BLEND_ELIGIBILITY.fingerprint,
                         "aeefb8a4c0697056f42bcd7078236838df4ef15defe68f05309c993666bcda22")

    def test_each_binding_pins_exactly_its_own_registered_host(self):
        for binding, profile in ((B0346, P0346), (X0346, P0346), (B0372, P0372), (X0372, P0372)):
            with self.subTest(binding=binding.identifier):
                self.assertEqual(pins(binding), host_pins(profile))
                self.assertIs(REGISTERED_COMFYUI_PROFILES[profile.inventory.comfyui_profile_identifier], profile)
        self.assertEqual(B0372.snapshot_fingerprint, "c33f6ee7c3143853316c6667118b0cb34794b09bcc5fd4a8f126f69f09319209")
        self.assertEqual(B0372.comfyui_revision, "830232b856045ca2892833212d7771078a13edd5")
        self.assertEqual(B0346.snapshot_fingerprint, "174ac696ee790419563c48481cf12e532c0aa133431c46f72c8f25e8bc6f47ca")
        self.assertEqual(B0346.comfyui_revision, "8fed37813848259fbdd2548ae3cd9f14df7fd68b")
        self.assertEqual((C0346.retained_inventory_fingerprint, C0372.retained_inventory_fingerprint),
                         (fingerprint(P0346.inventory), fingerprint(P0372.inventory)))

    def test_0372_authority_changes_only_identity_and_host_pins(self):
        # Contract, eligibility, profile, topology, graph, generator, allocation,
        # component, algorithm and realization semantics are the retained values.
        self.assertEqual(without(B0372, HOST_FIELDS), without(B0346, HOST_FIELDS))
        self.assertEqual(without(X0372, BLEND_HOST_FIELDS), without(X0346, BLEND_HOST_FIELDS))
        self.assertEqual(without(C0372, CLASS_HOST_FIELDS), without(C0346, CLASS_HOST_FIELDS))
        self.assertEqual((X0372.permitted_class_authority_identifier, X0372.permitted_class_authority_fingerprint),
                         (C0372.identifier, C0372.fingerprint))
        self.assertEqual(X0372.project_component_identity.implementation_fingerprint,
                         "46e33564c8b1327fae767099e008cf7a1f98b2b8a02c992d67f5a3fba0fd7e31")
        self.assertEqual(len(C0372.required_builtin_classes), 11)
        self.assertEqual(C0372.required_builtin_classes, P0372.inventory.required_node_class_names)
        self.assertNotEqual(B0372.identifier, B0346.identifier)
        self.assertNotEqual(X0372.identifier, X0346.identifier)
        self.assertNotEqual(C0372.identifier, C0346.identifier)

    def test_registration_is_additive_and_leaves_product_and_bounded_n_unchanged(self):
        self.assertEqual(tuple(item.identifier for item in authority.REGISTERED_REALIZATION_BINDINGS),
                         (B0346.identifier, B0372.identifier, authority.EXACT_THREE_REALIZATION_COMFYUI_0374.identifier))
        self.assertEqual(tuple(item.identifier for item in blend_authority.REGISTERED_BLEND_REALIZATION_BINDINGS),
                         (X0346.identifier, X0372.identifier, blend_authority.EXACT_THREE_BLEND_REALIZATION_COMFYUI_0374.identifier))
        self.assertIs(DEFAULT_SUPPORTED_PROFILE, P0346)
        self.assertIs(P0372.status, ProfileSupportStatus.QUALIFICATION_ONLY)
        self.assertEqual(product_supported_cardinalities(), (1, 2, 3))
        # Offline N=4..9 authority is untouched: no 0.37.2 generalized binding exists.
        self.assertEqual(len(REGISTERED_GENERALIZED_BLEND_REALIZATION_BINDINGS), 6)
        self.assertTrue(all(pins(item) == host_pins(P0346) for item in REGISTERED_GENERALIZED_BLEND_REALIZATION_BINDINGS))
        for profile in (P0346, P0372):
            self.assertIsNone(select_blend_realization(EXACT_FOUR_BLEND_ELIGIBILITY, profile))

    def test_bundle_pin_resolution_accepts_only_exact_reviewed_bindings(self):
        self.assertIs(realization_host_profile(B0346), P0346)
        self.assertIs(realization_host_profile(B0372), P0372)
        self.assertIs(blend_host_profile(X0346), P0346)
        self.assertIs(blend_host_profile(X0372), P0372)
        for value in (resign(replace(B0372, comfyui_revision=B0346.comfyui_revision)), X0372, None, object()):
            self.assertIsNone(realization_host_profile(value))
        for value in (resign(replace(X0372, snapshot_fingerprint=X0346.snapshot_fingerprint)), B0372, None):
            self.assertIsNone(blend_host_profile(value))


class ExactHostSelectionTests(unittest.TestCase):
    def test_each_exact_host_selects_only_its_own_authority(self):
        for name, profile, expected in (
            ("0.34.6 supported", P0346, (B0346, X0346, C0346)),
            # The historical qualification-time wrapper shares the 0.34.6 evidence.
            ("0.34.6 historical qualification record", COMFYUI_0346_QUALIFICATION_PROFILE, (B0346, X0346, C0346)),
            ("0.37.2 qualification-only", P0372, (B0372, X0372, C0372)),
        ):
            with self.subTest(name):
                no_overlap, blend = select(profile)
                self.assertIs(no_overlap, expected[0])
                self.assertIs(blend[0], expected[1])
                self.assertIs(blend[1], expected[2])

    def test_unbound_unknown_forged_or_promoted_hosts_select_nothing(self):
        inventory, snapshot = P0372.inventory, P0372.node_snapshot
        contracts = dict(snapshot.contracts)
        contracts["EmptyLatentImage"] = P0346.node_snapshot.contracts["EmptyLatentImage"]
        altered = replace(snapshot, contracts=contracts)
        resigned = replace(altered, snapshot_fingerprint=fingerprint_host_node_contract_snapshot(altered))
        unknown = replace(inventory, inventory_identifier="krea2-turbo-bf16-1024-comfyui-0.37.3.v1",
                          comfyui_profile_identifier="comfyui-0.37.3.prediction-mixing.v1",
                          expected_comfyui_version="0.37.3")
        historical = REGISTERED_COMFYUI_PROFILES[COMFYUI_0280_SUPPORTED_PROFILE.inventory.comfyui_profile_identifier]
        for name, profile in (
            ("0.34.5 registered without N=3 authority", COMFYUI_0345_QUALIFICATION_PROFILE),
            ("0.28.0 registered historical record", historical),
            ("0.28.0 legacy supported record", COMFYUI_0280_SUPPORTED_PROFILE),
            ("unknown host", replace(P0372, inventory=unknown)),
            ("0.37.2 inventory with 0.34.6 snapshot", replace(P0372, node_snapshot=P0346.node_snapshot)),
            ("0.34.6 inventory with 0.37.2 snapshot", replace(P0346, node_snapshot=snapshot)),
            ("0.37.2 identity at the 0.34.6 revision", replace(P0372, inventory=replace(
                inventory, expected_comfyui_revision=P0346.inventory.expected_comfyui_revision))),
            ("altered 0.37.2 contract evidence", replace(P0372, node_snapshot=altered)),
            ("self-consistent re-signed 0.37.2 evidence", replace(P0372, node_snapshot=resigned)),
            ("caller-promoted 0.37.2", replace(P0372, status=ProfileSupportStatus.SUPPORTED)),
            ("status alias", replace(P0372, status="qualification_only")),
            ("duck-typed profile", SimpleNamespace(inventory=inventory, node_snapshot=snapshot, status=P0372.status)),
            ("missing profile", None),
        ):
            with self.subTest(name):
                self.assertEqual(select(profile), (None, None))

    def test_selection_requires_the_routed_exact_entry(self):
        for profile in (P0346, P0372):
            with self.subTest(profile=profile.inventory.comfyui_profile_identifier):
                self.assertIsNone(select_realization_binding(EXACT_THREE_BLEND_ELIGIBILITY, profile))
                self.assertIsNone(select_blend_realization(EXACT_THREE_ELIGIBILITY, profile))
                self.assertIsNone(select_realization_binding(replace(EXACT_THREE_ELIGIBILITY, fingerprint="0" * 64), profile))
                self.assertIsNone(select_blend_realization(replace(EXACT_THREE_BLEND_ELIGIBILITY, fingerprint="0" * 64), profile))

    def test_selection_requires_current_registration(self):
        registered = MappingProxyType({key: value for key, value in REGISTERED_COMFYUI_PROFILES.items()
                                       if value is not P0372})
        with patch.object(authority, "REGISTERED_COMFYUI_PROFILES", registered):
            self.assertEqual(select(P0372), (None, None))
            self.assertIs(select(P0346)[0], B0346)

    def test_duplicate_ambiguous_missing_or_altered_registration_fails_closed_without_fallback(self):
        for route, registry_name, retained, current, entry, chooser in (
            ("no-overlap", "REGISTERED_REALIZATION_BINDINGS", B0346, B0372,
             EXACT_THREE_ELIGIBILITY, select_realization_binding),
            ("blend", "REGISTERED_BLEND_REALIZATION_BINDINGS", X0346, X0372,
             EXACT_THREE_BLEND_ELIGIBILITY, lambda *args: (select_blend_realization(*args) or (None,))[0]),
        ):
            module = authority if route == "no-overlap" else blend_authority
            shadow = resign(replace(current, identifier=current.identifier + ".shadow"))
            partial = resign(replace(retained, identifier=retained.identifier + ".partial",
                                     snapshot_fingerprint=current.snapshot_fingerprint))
            altered = resign(replace(current, realization_semantics=current.realization_semantics[:-1]))
            for name, registry, expected_retained, expected_current in (
                ("duplicate current host", (retained, current, current), retained, None),
                ("duplicate retained host", (retained, retained, current), None, current),
                ("self-consistent shadow of the current host", (retained, current, shadow), retained, None),
                ("one shared identity shadows both hosts", (retained, current, partial), None, None),
                ("current host missing: no fallback", (retained,), retained, None),
                ("retained host missing: no fallback", (current,), None, current),
                ("altered current registration", (retained, altered), retained, None),
                ("empty registry", (), None, None),
                ("unselected opaque records", (retained, object(), current), retained, current),
            ):
                with self.subTest(route=route, case=name), patch.object(module, registry_name, registry):
                    self.assertIs(chooser(entry, P0346), expected_retained)
                    self.assertIs(chooser(entry, P0372), expected_current)


class HostRealizationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        for target in ("socket.socket", "urllib.request.urlopen", "http.client.HTTPConnection", "subprocess.Popen"):
            guard = patch(target, side_effect=AssertionError("host binding tests are offline only"))
            guard.start()
            self.addCleanup(guard.stop)
        root = Path(self.temporary.name)
        self.no_overlap_data = no_overlap_fixture(root / "no-overlap")
        self.blend_data = blend_fixture(root / "blend")

    def no_overlap(self, profile, binding):
        document, _, plan, settings, staging = self.no_overlap_data
        return generate_prediction_mixing_multi_layer_workflow(
            plan, profile.inventory, settings, staging, document_id=document.document_id, binding=binding)

    def blend(self, profile, binding, classes):
        document, _, _, plan, settings, staging = self.blend_data
        return generate_prediction_mixing_blend_workflow(
            plan, profile.inventory, settings, staging, document_id=document.document_id,
            binding=binding, permitted_class_authority=classes)

    def test_both_hosts_realize_the_same_graph_under_their_own_authority(self):
        retained = self.no_overlap(P0346, select_realization_binding(EXACT_THREE_ELIGIBILITY, P0346))
        current = self.no_overlap(P0372, select_realization_binding(EXACT_THREE_ELIGIBILITY, P0372))
        document, _, plan, settings, staging = self.no_overlap_data
        default = generate_prediction_mixing_multi_layer_workflow(
            plan, P0346.inventory, settings, staging, document_id=document.document_id)
        self.assertTrue(retained.generated and current.generated and default.generated,
                        (retained.errors, current.errors, default.errors))
        self.assertEqual(canonical_bytes(retained.artifact), canonical_bytes(default.artifact))
        self.assertEqual(current.artifact.to_api_graph(), retained.artifact.to_api_graph())
        self.assertNotEqual(current.artifact.graph_fingerprint, retained.artifact.graph_fingerprint)
        self.assertEqual((current.artifact.provenance_inputs.realization_binding_identifier,
                          current.artifact.provenance_inputs.realization_binding_fingerprint,
                          current.artifact.provenance_inputs.component_inventory_identifier),
                         (B0372.identifier, B0372.fingerprint, P0372.inventory.inventory_identifier))
        self.assertEqual(validate_multi_layer_artifact(current.artifact, current.artifact.provenance_inputs,
                                                       P0372.inventory), ())

        retained = self.blend(P0346, *select_blend_realization(EXACT_THREE_BLEND_ELIGIBILITY, P0346))
        current = self.blend(P0372, *select_blend_realization(EXACT_THREE_BLEND_ELIGIBILITY, P0372))
        self.assertTrue(retained.generated and current.generated, (retained.errors, current.errors))
        self.assertEqual(current.artifact.to_api_graph(), retained.artifact.to_api_graph())
        self.assertEqual(len(current.artifact.to_api_graph()), 20)
        self.assertNotEqual(current.artifact.graph_fingerprint, retained.artifact.graph_fingerprint)
        provenance = current.artifact.provenance_inputs
        self.assertEqual((provenance.realization_binding_identifier, provenance.permitted_class_authority_identifier,
                          provenance.project_component_implementation_fingerprint),
                         (X0372.identifier, C0372.identifier, retained.artifact.provenance_inputs.project_component_implementation_fingerprint))
        self.assertEqual(validate_blend_artifact(current.artifact, provenance, P0372.inventory), ())

    def test_cross_host_combinations_fail_closed(self):
        for profile, binding in ((P0372, B0346), (P0346, B0372), (P0372, None), (P0346, None)):
            with self.subTest(profile=profile.inventory.comfyui_profile_identifier,
                              binding=getattr(binding, "identifier", None)):
                result = self.no_overlap(profile, binding)
                self.assertIsNone(result.artifact)
                self.assertEqual({item.code for item in result.errors}, {"multi_layer.realization.invalid"})
        realization, classes = "blend.realization.invalid", "blend.graph_classes.invalid"
        for profile, binding, authority_value, expected in (
            (P0372, X0346, C0346, {realization, classes}),
            (P0372, X0372, C0346, {classes}),
            (P0372, X0346, C0372, {realization}),
            (P0346, X0346, C0372, {classes}),
            (P0346, X0372, C0372, {realization, classes}),
            (P0372, None, None, {realization, classes}),
        ):
            with self.subTest(profile=profile.inventory.comfyui_profile_identifier,
                              binding=getattr(binding, "identifier", None),
                              classes=getattr(authority_value, "identifier", None)):
                result = self.blend(profile, binding, authority_value)
                self.assertIsNone(result.artifact)
                self.assertEqual({item.code for item in result.errors}, expected)
        self.assertEqual(verify_permitted_class_authority(C0372, P0372.inventory), ())
        self.assertEqual(verify_permitted_class_authority(C0346, P0346.inventory), ())
        self.assertTrue(verify_permitted_class_authority(C0372, P0346.inventory))
        self.assertTrue(verify_permitted_class_authority(C0346, P0372.inventory))
        artifact = self.no_overlap(P0372, B0372).artifact
        self.assertTrue(validate_multi_layer_artifact(artifact, artifact.provenance_inputs, P0346.inventory))
        artifact = self.blend(P0372, X0372, C0372).artifact
        self.assertTrue(validate_blend_artifact(artifact, artifact.provenance_inputs, P0346.inventory))

    def test_self_consistent_forgery_and_registry_tampering_fail_closed(self):
        plan = self.no_overlap_data[2]
        for changed in (
            resign(replace(B0372, exact_cardinality=4)),
            resign(replace(B0372, comfyui_revision=B0346.comfyui_revision)),
            resign(replace(B0372, snapshot_fingerprint=B0346.snapshot_fingerprint)),
            resign(replace(B0372, identifier=B0346.identifier)),
        ):
            with self.subTest(binding=changed.fingerprint):
                self.assertFalse(self.no_overlap(P0372, changed).generated)
                with patch.object(authority, "REGISTERED_REALIZATION_BINDINGS", (B0346, changed)):
                    # Registration alone cannot authenticate a forgery.
                    self.assertTrue(verify_realization_binding(changed, plan, P0372.inventory))
        with patch.object(authority, "REGISTERED_REALIZATION_BINDINGS", (B0346, B0372, B0372)):
            self.assertFalse(self.no_overlap(P0372, B0372).generated)
            self.assertTrue(self.no_overlap(P0346, B0346).generated)
        identity = replace(X0372.project_component_identity, implementation_fingerprint="0" * 64)
        for changed in (
            resign(replace(X0372, project_component_identity=identity)),
            resign(replace(X0372, permitted_class_authority_identifier=C0346.identifier,
                           permitted_class_authority_fingerprint=C0346.fingerprint)),
            resign(replace(X0372, project_component_availability_required=False)),
        ):
            with self.subTest(binding=changed.fingerprint):
                self.assertFalse(self.blend(P0372, changed, C0372).generated)
        forged = resign(replace(C0372, project_component_class="InventedMathNode"))
        self.assertFalse(self.blend(P0372, X0372, forged).generated)
        with patch.object(blend_authority, "REGISTERED_BLEND_REALIZATION_BINDINGS", (X0346,)):
            self.assertFalse(self.blend(P0372, X0372, C0372).generated)
            self.assertTrue(self.blend(P0346, X0346, C0346).generated)


if __name__ == "__main__":
    unittest.main()
