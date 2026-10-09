from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from conditioning_layers.adapters.prediction_mixing import translate_prediction_mixing
from conditioning_layers.assets import inspect_field_asset, to_field_asset_profile
from conditioning_layers.comfyui.prediction_mixing import (
    DEFAULT_SUPPORTED_PROFILE, FieldStagingMap, RuntimeGenerationSettings,
    generate_prediction_mixing_workflow,
)
from conditioning_layers.integrations.comfyui_panel import starter_fields
from conditioning_layers.integrations.comfyui_panel.application import materialize_document
from conditioning_layers.integrations.comfyui_panel.documents import PanelDocumentStore
from conditioning_layers.integrations.comfyui_panel.models import PanelRequestError
from conditioning_layers.runtime.comfyui import (
    stage_field_assets, staging_namespace_for_document, validate_field_sources,
)

from _support import grayscale_png, row, upload
from test_starter_fields import LIBRARY, EXPECTED, parse_execution, parse_save
from test_starter_frontend import run_node, sidebar_script, store_script
from test_application import host_context


LEFT = "two-layer.left-right.v1:A"
RIGHT = "two-layer.left-right.v1:B"


def change_manifest(root, family, change):
    path = root / f"manifests/{family}.manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    change(manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    catalog_path = root / "library-manifest.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    record = next(item for item in catalog["families"] if item["pattern_family_id"] == family)
    record["manifest_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    record["support_status"] = manifest["support_status"]
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")


def copy_p1_library(root):
    """Explicit historical eligibility fixture, independent of current promotion."""
    shutil.copytree(LIBRARY, root)
    catalog = json.loads((root / "library-manifest.json").read_text(encoding="utf-8"))
    for record in catalog["families"][1:]:
        change_manifest(root, record["pattern_family_id"], lambda m: m.update(support_status="research-only"))


class ProductPresetTests(unittest.TestCase):
    def test_catalog_is_derived_ordered_unique_and_contains_only_eligible_partition_fields(self):
        catalog = json.loads((LIBRARY / "library-manifest.json").read_text(encoding="utf-8"))
        expected = []
        for record in catalog["families"]:
            if record["support_status"] != "validated-product-asset":
                continue
            manifest = json.loads((LIBRARY / record["manifest_filename"]).read_text(encoding="utf-8"))
            expected.extend(f"{manifest['pattern_family_id']}:{field['asset_id']}" for field in manifest["fields"])
        first = starter_fields.product_field_presets()
        self.assertEqual(first, starter_fields.product_field_presets())
        self.assertEqual([item.identifier for item in first], expected)
        self.assertEqual(expected[:2], [LEFT, RIGHT])
        self.assertEqual(len(expected), 13)
        self.assertEqual(len(set(expected)), len(expected))
        self.assertEqual([item.to_json() for item in first[:2]], [
            {"id": LEFT, "display_name": "Left"}, {"id": RIGHT, "display_name": "Right"},
        ])
        for item in first:
            self.assertEqual(hashlib.sha256(starter_fields.read_starter_field(item.identifier)).hexdigest(), item.checksum)

    def test_status_promotion_alone_exposes_existing_family_without_frontend_or_asset_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "library"
            copy_p1_library(root)
            family = "two-layer.top-bottom.v1"
            with patch.object(starter_fields, "_LIBRARY_ROOT", root):
                self.assertEqual([p.identifier for p in starter_fields.product_field_presets()], [LEFT, RIGHT])
                with self.assertRaises(PanelRequestError) as raised:
                    starter_fields.read_starter_field(f"{family}:A")
                self.assertEqual(raised.exception.status, 404)
                change_manifest(root, family, lambda manifest: manifest.update(support_status="validated-product-asset"))
                presets = starter_fields.product_field_presets()
                self.assertEqual([p.identifier for p in presets], [LEFT, RIGHT, f"{family}:A", f"{family}:B"])
                self.assertEqual([p.display_name for p in presets], ["Left", "Right", "Top", "Bottom"])
                self.assertEqual(starter_fields.read_starter_field(presets[2].identifier),
                                 (LIBRARY / presets[2].relative_path).read_bytes())
                self.assertFalse(any("three-layer" in p.identifier or "not-" in p.identifier for p in presets))

    def test_identity_and_label_mapping_survive_reordering_renaming_and_relocation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "different-location"
            copy_p1_library(root)
            def change(manifest):
                manifest["fields"].reverse()
                manifest["display_name"] = "West / East"
            change_manifest(root, "two-layer.left-right.v1", change)
            with patch.object(starter_fields, "_LIBRARY_ROOT", root):
                presets = starter_fields.product_field_presets()
                self.assertEqual([p.identifier for p in presets], [RIGHT, LEFT])
                self.assertEqual([p.display_name for p in presets], ["East", "West"])
                self.assertEqual(starter_fields.read_starter_field(LEFT), grayscale_png(255, 0))

    def test_empty_registry_is_explicit_and_unknown_or_path_like_ids_fail_closed(self):
        invalid = ["two-layer.unknown.v1:A", "two-layer.top-bottom.v1:C", "../left",
                   LEFT + "/../../x", "C:/private.png", "left.png", "Left", "", None, [],
                   "two-layer.left-right.v1:not-A", LEFT + "\n"]
        for identifier in invalid:
            with self.subTest(identifier=identifier), self.assertRaises(PanelRequestError) as raised:
                starter_fields.read_starter_field(identifier)
            self.assertEqual(raised.exception.status, 404)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "library-manifest.json").write_text(json.dumps({
                "library_id": "conditioning-layers.influence-field-library", "library_version": 1, "families": [],
            }), encoding="utf-8")
            with patch.object(starter_fields, "_LIBRARY_ROOT", root):
                self.assertEqual(starter_fields.product_field_presets(), ())
                with self.assertRaises(PanelRequestError) as raised:
                    starter_fields.read_starter_field(LEFT)
                self.assertEqual(raised.exception.status, 404)

    def test_metadata_enumeration_does_not_read_or_hash_pngs(self):
        read = starter_fields._read_contained
        paths = []
        def record(path, root, limit):
            paths.append(path)
            return read(path, root, limit)
        with patch.object(starter_fields, "_read_contained", side_effect=record):
            starter_fields.product_field_presets()
        self.assertTrue(paths)
        self.assertTrue(all(path.suffix == ".json" for path in paths))

    def test_corrupt_eligible_metadata_never_returns_a_partial_catalog(self):
        changes = [
            {"resolution": {"width": 64, "height": 128}}, {"image_mode": "rgb"},
            {"resolution": {"width": 128.0, "height": 128}},
            {"display_name": ""}, {"layer_count": 3}, {"fields": []},
            {"fields": [{"asset_id": "A"}, {"asset_id": "A"}]},
        ]
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "library"
                copy_p1_library(root)
                change_manifest(root, "two-layer.left-right.v1", lambda m: m.update(change))
                with patch.object(starter_fields, "_LIBRARY_ROOT", root):
                    with self.assertRaises(PanelRequestError) as raised:
                        starter_fields.product_field_presets()
                self.assertEqual(raised.exception.status, 503)
                self.assertNotIn(temporary, raised.exception.finding.message)

    def test_hash_matching_malformed_or_wrong_profile_png_is_rejected(self):
        for data in (b"\x89PNG\r\n\x1a\ncorrupt", grayscale_png(64, 128)):
            with self.subTest(data=data[:16]), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "library"
                copy_p1_library(root)
                (root / "two-layer/left-right/field-a.png").write_bytes(data)
                def change(manifest):
                    manifest["fields"][0]["sha256"] = hashlib.sha256(data).hexdigest()
                change_manifest(root, "two-layer.left-right.v1", change)
                with patch.object(starter_fields, "_LIBRARY_ROOT", root):
                    with self.assertRaises(PanelRequestError) as raised:
                        starter_fields.read_starter_field(LEFT)
                self.assertEqual(raised.exception.status, 503)

    def test_new_selector_and_legacy_left_right_produce_identical_v1_graphs(self):
        for side, identifier in (("left", LEFT), ("right", RIGHT)):
            with self.subTest(side=side), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fingerprints = []
                for source, data in (("legacy", starter_fields.read_starter_field(side)),
                                     ("preset", starter_fields.read_starter_field(identifier))):
                    self.assertEqual(hashlib.sha256(data).hexdigest(), EXPECTED[side][1])
                    draft = parse_execution([row("a")], {"field-a": upload("a", data)})
                    materialized = materialize_document(draft, "a" * 32, root / source)
                    document = materialized.document
                    inspection = inspect_field_asset(materialized.asset_root, document.layers[0])
                    self.assertTrue(inspection.certified, inspection.errors)
                    translated = translate_prediction_mixing(document, (to_field_asset_profile(inspection),))
                    self.assertTrue(translated.translated, translated.errors)
                    namespace = staging_namespace_for_document(document.document_id)
                    generated = generate_prediction_mixing_workflow(
                        translated.plan, DEFAULT_SUPPORTED_PROFILE.inventory,
                        RuntimeGenerationSettings(seed=draft.resolved_seed,
                                                  output_filename_prefix="conditioning-layers-panel/" + "a" * 32,
                                                  execution_request_id="a" * 32),
                        FieldStagingMap({document.layers[0].layer_id: f"{namespace}/{document.layers[0].layer_id}.png"}),
                    )
                    self.assertTrue(generated.generated, generated.errors)
                    # Actual staging uses only this test's temporary input root.
                    configuration = host_context(root / source).host_configuration
                    configuration.input_directory.mkdir()
                    sources = validate_field_sources(
                        generated.artifact, generated.artifact.provenance_inputs,
                        (inspection,), materialized.asset_root, configuration,
                    )
                    self.assertTrue(sources.verified, sources.errors)
                    staged = stage_field_assets(sources.candidates, configuration)
                    self.assertTrue(staged.successful, staged.errors)
                    self.assertEqual(staged.records[0].destination_path.read_bytes(), data)
                    fingerprints.append((draft.fingerprint, document, translated.plan.fingerprint,
                                         generated.artifact.graph_fingerprint))
                self.assertEqual(fingerprints[0], fingerprints[1])

    def test_save_reload_preserves_independent_resolved_fields_without_library_or_provenance(self):
        rows = [row("a"), row("b", active=False), row("custom", active=False)]
        data = [starter_fields.read_starter_field(LEFT), starter_fields.read_starter_field(RIGHT), grayscale_png(64, 128)]
        uploads = {f"field-{name}": upload(name, value) for name, value in zip(("a", "b", "custom"), data)}
        with tempfile.TemporaryDirectory() as temporary:
            store = PanelDocumentStore(Path(temporary) / "user")
            saved = store.save_as(parse_save("Presets", rows, uploads))
            document_path = store.root / "presets.conditioning.json"
            before = document_path.read_bytes()
            with patch.object(starter_fields, "_LIBRARY_ROOT", Path(temporary) / "absent"):
                opened = store.open(saved.document_key)
            self.assertEqual(opened.document, saved.document)
            self.assertEqual(list(opened.field_bytes.values()), data)
            self.assertEqual(document_path.read_bytes(), before)
            self.assertNotIn(b"preset", before)


class ProductPresetFrontendTests(unittest.TestCase):
    def test_selector_has_native_label_no_default_and_per_layer_independent_selection(self):
        result = run_node(sidebar_script("""
          const initial = {value:presetSelect().value, selected:selected(),
            label:presetSelect().parent.children[0].textContent, tag:presetSelect().tagName};
          await button('Generate').fire('click');
          const missing = find(node => node.className === 'cl-status').textContent;
          await choosePreset('Left');
          await button('Add Layer').fire('click');
          const added = presetSelect(1).value;
          await choosePreset('Right',1);
          const values = [presetSelect(0).value,presetSelect(1).value];
          fileInput().files = [new File(['custom'],'custom.png',{type:'image/png'})];
          await fileInput().fire('change');
          const custom = [presetSelect(0).value,presetSelect(1).value];
          await choosePreset('Left');
          const final = [presetSelect(0).value,presetSelect(1).value];
          console.log(JSON.stringify({initial,missing,added,values,custom,final,requests,
            labels:presetSelect().children.map(option => option.textContent),
            oldButtons:Boolean(button('Left') || button('Right'))}));
        """))
        self.assertEqual(result["initial"], {"value": "", "selected": "No PNG selected", "label": "Preset", "tag": "select"})
        self.assertIn("requires a PNG", result["missing"])
        self.assertEqual(result["added"], "")
        self.assertEqual(result["values"], [LEFT, RIGHT])
        self.assertEqual(result["custom"], ["", RIGHT])
        self.assertEqual(result["final"], [LEFT, RIGHT])
        self.assertEqual(result["labels"], ["Select preset"] + [p.display_name for p in starter_fields.product_field_presets()])
        self.assertFalse(result["oldButtons"])
        self.assertTrue(all(request["method"] == "GET" for request in result["requests"]))
        self.assertEqual(sum(request["url"] == "/conditioning-layers/starter-fields" for request in result["requests"]), 1)

    def test_promoted_fixture_appears_in_actual_sidebar_without_frontend_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "library"
            copy_p1_library(root)
            change_manifest(root, "two-layer.top-bottom.v1", lambda m: m.update(support_status="validated-product-asset"))
            with patch.object(starter_fields, "_LIBRARY_ROOT", root):
                result = run_node(sidebar_script("""
                  console.log(JSON.stringify(presetSelect().children.map(option => ({id:option.value,label:option.textContent}))));
                """))
        self.assertEqual([option["label"] for option in result], ["Select preset", "Left", "Right", "Top", "Bottom"])
        self.assertEqual(result[3]["id"], "two-layer.top-bottom.v1:A")

    def test_empty_or_invalid_catalog_keeps_custom_png_available_without_substitution(self):
        for payload in ("{presets:[]}", "{presets:[presets[0],presets[0]]}", "{presets:[{id:'../file',display_name:'Bad'}]}"):
            with self.subTest(payload=payload):
                result = run_node(sidebar_script("""
                  const disabled = presetSelect().disabled; const value = presetSelect().value;
                  const message = container.textContent;
                  fileInput().files = [new File(['custom'],'artist.png',{type:'image/png'})];
                  await fileInput().fire('change');
                  console.log(JSON.stringify({disabled,value,message,selected:selected(),requests}));
                """, before_render=f"catalogPayload = {payload};"))
                self.assertTrue(result["disabled"])
                self.assertEqual(result["value"], "")
                self.assertIn("Custom PNG", result["message"])
                self.assertEqual(result["selected"], "Selected: artist.png")
                self.assertFalse(any("/starter-fields/" in request["url"] for request in result["requests"]))

    def test_unknown_stale_or_unavailable_selection_preserves_previous_field(self):
        result = run_node(sidebar_script("""
          await choosePreset('Left');
          const failures = [];
          for (const id of ['left','../field','two-layer.unknown.v1:A']) {
            presetSelect().value = id; await presetSelect().fire('change');
            failures.push({value:presetSelect().value,selected:selected()});
          }
          const fetch = testApi.fetchApi;
          testApi.fetchApi = async (url, options) => url.includes('/starter-fields/')
            ? new Response('unavailable',{status:503}) : fetch(url,options);
          await choosePreset('Right');
          failures.push({value:presetSelect().value,selected:selected()});
          console.log(JSON.stringify({failures,created:created.length}));
        """))
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["failures"], [{"value": LEFT, "selected": "Selected preset: Left"}] * 4)

        # Even reselecting the identical File object is a newer source choice.
        result = run_node(sidebar_script("""
          const custom = new File(['custom'],'artist.png',{type:'image/png'});
          fileInput().files = [custom]; await fileInput().fire('change');
          let release; deferStarter = new Promise(resolve => { release = resolve; });
          const pending = choosePreset('Left');
          fileInput().files = [custom]; await fileInput().fire('change');
          release(); await pending;
          console.log(JSON.stringify({value:presetSelect().value,selected:selected(),
            allCustom:created.every(item => item.file === custom)}));
        """))
        self.assertEqual(result, {"value": "", "selected": "Selected: artist.png", "allCustom": True})

    def test_editing_id_is_stable_but_transport_remains_resolved_png_and_conflicts_fail_closed(self):
        result = run_node(store_script("""
          const store = createLayerStore(() => 'row-a'); const layer = store.addLayer();
          const file = await loadPresetField(presets[0].id,presets,fetchStarter);
          store.assignField(layer.rowId,file,presets[0].id);
          const id = layer.presetId;
          const preset = await parts(store.toMultipart('Base','key'));
          const presetSave = await parts(store.toDocumentMultipart('Base','Study'));
          store.assignField(layer.rowId,file);
          const customId = layer.presetId;
          const custom = await parts(store.toMultipart('Base','key'));
          store.assignField(layer.rowId,await loadPresetField(presets[1].id,presets,fetchStarter),presets[1].id);
          const finalId = layer.presetId;
          const final = await parts(store.toMultipart('Base','key'));
          layer.persistedField = true;
          let conflict;
          try { store.toMultipart('Base','key'); } catch (error) { conflict = error.message; }
          console.log(JSON.stringify({id,preset,presetSave,customId,custom,finalId,final,conflict}));
        """))
        self.assertEqual(result["id"], LEFT)
        self.assertIsNone(result["customId"])
        self.assertEqual(result["finalId"], RIGHT)
        self.assertEqual(result["final"]["uploads"][0]["sha256"], EXPECTED["right"][1])
        self.assertEqual(result["preset"], result["custom"])
        self.assertEqual(result["presetSave"]["uploads"], result["preset"]["uploads"])
        self.assertNotIn("preset", json.dumps(result["preset"]))
        self.assertIn("conflicting", result["conflict"])


if __name__ == "__main__":
    unittest.main()
