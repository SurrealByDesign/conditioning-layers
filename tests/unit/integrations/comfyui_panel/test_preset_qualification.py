"""P1A exact-asset qualification through the ordinary offline v1 field path."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from conditioning_layers.adapters.prediction_mixing import translate_prediction_mixing
from conditioning_layers.assets import (
    inspect_field_asset, inspect_field_pair, to_field_asset_profile, to_overlap_assessment,
)
from conditioning_layers.capabilities import evaluate_prediction_mixing
from conditioning_layers.comfyui.prediction_mixing import (
    DEFAULT_SUPPORTED_PROFILE, FieldStagingMap, RuntimeGenerationSettings,
    generate_prediction_mixing_workflow,
)
from conditioning_layers.domain import FindingSeverity, validate_document
from conditioning_layers.integrations.comfyui_panel import routes, starter_fields
from conditioning_layers.integrations.comfyui_panel.application import materialize_document
from conditioning_layers.integrations.comfyui_panel.models import PanelRequestError, UploadedField
from conditioning_layers.runtime.comfyui import (
    stage_field_assets, staging_namespace_for_document, validate_field_sources,
)

from _support import metadata, row
from test_application import host_context
from test_product_presets import change_manifest, copy_p1_library
from test_routes import FakePart, FakeRequest
from test_starter_fields import LIBRARY


FAMILIES = (
    ("two-layer.left-right.v1", ("Left", "Right")),
    ("two-layer.top-bottom.v1", ("Top", "Bottom")),
    ("three-layer.vertical-thirds.v1", tuple(f"Vertical Thirds — Field {x}" for x in "ABC")),
    ("three-layer.horizontal-thirds.v1", tuple(f"Horizontal Thirds — Field {x}" for x in "ABC")),
    ("three-layer.center-ring-outer.v1", ("Center Disk", "Middle Ring", "Outer Field")),
)
EXPECTED_CATALOG = [
    {"id": f"{family}:{asset}", "display_name": label}
    for family, labels in FAMILIES
    for asset, label in zip("ABC", labels)
]


@contextmanager
def offline_routes(root):
    """Real read-only handlers; fake registration/response objects, no server."""
    handlers = {}
    def register(method):
        def decorate(path):
            def record(handler):
                handlers[(method, path)] = handler
                return handler
            return record
        return decorate
    registry = SimpleNamespace(**{m.lower(): register(m) for m in ("GET", "POST", "PUT")})
    web = SimpleNamespace(Response=lambda **kw: kw,
                          json_response=lambda payload, **kw: {"payload": payload, **kw})
    server = SimpleNamespace(PromptServer=SimpleNamespace(instance=SimpleNamespace(routes=registry)))
    with ExitStack() as stack:
        # Async event loops already exist before these fences are installed.
        for target in ("socket.socket", "socket.create_connection", "socket.getaddrinfo",
                       "urllib.request.urlopen", "urllib.request.OpenerDirector.open",
                       "subprocess.Popen", "webbrowser.open"):
            stack.enter_context(patch(target, side_effect=AssertionError("P1A must remain offline")))
        stack.enter_context(patch.dict(sys.modules, {"aiohttp": SimpleNamespace(web=web), "server": server}))
        stack.enter_context(patch.object(routes, "_build_host_context", return_value=host_context(root)))
        stack.enter_context(patch.object(routes, "_REGISTERED", False))
        stack.enter_context(patch.object(routes, "_COORDINATOR", None))
        stack.enter_context(patch.object(routes.PanelJobCoordinator, "submit", side_effect=AssertionError("no execution")))
        routes.register_routes()
        yield handlers


class PresetQualificationTests(unittest.IsolatedAsyncioTestCase):
    async def qualify(self, handlers, identifiers, root):
        catalog = await handlers[("GET", "/conditioning-layers/starter-fields")](None)
        self.assertTrue(set(identifiers) <= {p["id"] for p in catalog["payload"]["presets"]})
        rows, parts, payloads = [], [], []
        for index, identifier in enumerate(identifiers):
            response = await handlers[("GET", "/conditioning-layers/starter-fields/{starter_id}")](
                SimpleNamespace(match_info={"starter_id": identifier}))
            self.assertEqual(response["content_type"], "image/png")
            preset = next(p for p in starter_fields.product_field_presets() if p.identifier == identifier)
            data = response["body"]
            self.assertEqual(hashlib.sha256(data).hexdigest(), preset.checksum)
            self.assertEqual(data, (LIBRARY / preset.relative_path).read_bytes())
            name = str(index)
            rows.append(row(name, prompt=f"A matte red sculpture, study {index}"))
            parts.append(FakePart(f"field-{name}", "image/png", data))
            payloads.append(data)
        body = json.loads(metadata(rows, base_prompt="A quiet studio, neutral light", key="p1a-offline"))
        body["seed"] = "18472639"
        draft = await routes._read_multipart_request(FakeRequest([
            FakePart("request", "application/json", json.dumps(body).encode()), *parts,
        ]))
        self.assertEqual(draft.resolved_seed, 18472639)
        self.assertTrue(all(isinstance(layer.field, UploadedField) for layer in draft.layers))
        materialized = materialize_document(draft, "a" * 32, root)
        document = materialized.document
        self.assertEqual(len(document.active_layers), len(identifiers))
        self.assertFalse(any(f.severity is FindingSeverity.ERROR for f in validate_document(document)))
        self.assertTrue(evaluate_prediction_mixing(document).compatible)
        for layer, data in zip(document.layers, payloads, strict=True):
            self.assertEqual((materialized.asset_root / layer.influence_field.relative_path).read_bytes(), data)
        overlap = None
        if len(identifiers) == 1:
            inspections = (inspect_field_asset(materialized.asset_root, document.active_layers[0]),)
        else:
            pair = inspect_field_pair(materialized.asset_root, *document.active_layers)
            inspections = pair.fields
            overlap = to_overlap_assessment(pair.overlap)
            self.assertFalse(pair.overlap.errors)
            self.assertTrue(pair.overlap.certified)
            self.assertEqual(pair.overlap.evidence.overlap_pixel_count, 0)
            self.assertTrue(pair.overlap.evidence.exact_complements)
            self.assertFalse(pair.overlap.evidence.has_unassigned_pixels)
        self.assertTrue(all(i.certified for i in inspections), inspections)
        translated = translate_prediction_mixing(
            document, tuple(to_field_asset_profile(i) for i in inspections), overlap_assessment=overlap)
        self.assertTrue(translated.translated, translated.errors)
        namespace = staging_namespace_for_document(document.document_id)
        generated = generate_prediction_mixing_workflow(
            translated.plan, DEFAULT_SUPPORTED_PROFILE.inventory,
            RuntimeGenerationSettings(seed=draft.resolved_seed,
                                      output_filename_prefix="conditioning-layers-panel/" + "a" * 32,
                                      execution_request_id="a" * 32),
            FieldStagingMap({layer.layer_id: f"{namespace}/{layer.layer_id}.png" for layer in document.active_layers}),
        )
        self.assertTrue(generated.generated, generated.errors)
        configuration = replace(host_context(root).host_configuration,
                                supported_profile_identifier=DEFAULT_SUPPORTED_PROFILE.inventory.comfyui_profile_identifier)
        configuration.input_directory.mkdir()
        sources = validate_field_sources(generated.artifact, generated.artifact.provenance_inputs,
                                         inspections, materialized.asset_root, configuration)
        self.assertTrue(sources.verified, sources.errors)
        staged = stage_field_assets(sources.candidates, configuration)
        self.assertTrue(staged.successful, staged.errors)
        self.assertEqual(len(staged.records), len(payloads))
        self.assertEqual([r.destination_path.read_bytes() for r in staged.records], payloads)

    async def test_each_family_authority_and_asset_fail_closed(self):
        for family, labels in FAMILIES:
            for damage in ("research-only", "support-mismatch", "manifest-hash", "asset-hash"):
                with self.subTest(family=family, damage=damage), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    shutil.copytree(LIBRARY, root / "library")
                    library = root / "library"
                    path = library / f"manifests/{family}.manifest.json"
                    manifest = json.loads(path.read_bytes())
                    if damage == "research-only":
                        change_manifest(library, family, lambda m: m.update(support_status="research-only"))
                    elif damage == "support-mismatch":
                        # Hash is correct but family status disagrees with catalog.
                        manifest["support_status"] = "research-only"
                        path.write_text(json.dumps(manifest), encoding="utf-8")
                        catalog_path = library / "library-manifest.json"
                        catalog = json.loads(catalog_path.read_bytes())
                        record = next(r for r in catalog["families"] if r["pattern_family_id"] == family)
                        record["manifest_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                        catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
                    elif damage == "manifest-hash":
                        path.write_bytes(path.read_bytes() + b" ")
                    else:
                        asset = library / manifest["fields"][0]["filename"]
                        asset.write_bytes(asset.read_bytes() + b" ")
                    with patch.object(starter_fields, "_LIBRARY_ROOT", library):
                        if damage == "research-only":
                            catalog = starter_fields.product_field_presets()
                            self.assertEqual(len(catalog), 13 - len(labels))
                            self.assertFalse(any(p.identifier.startswith(family + ":") for p in catalog))
                        elif damage != "asset-hash":
                            with self.assertRaises(PanelRequestError) as raised:
                                starter_fields.product_field_presets()
                            self.assertEqual(raised.exception.status, 503)
                        with self.assertRaises(PanelRequestError) as raised:
                            starter_fields.read_starter_field(f"{family}:A")
                        self.assertEqual(raised.exception.status, 404 if damage == "research-only" else 503)

    async def test_all_complement_ids_remain_unqualified_and_unexposed(self):
        with tempfile.TemporaryDirectory() as temporary, offline_routes(Path(temporary)) as handlers:
            catalog = await handlers[("GET", "/conditioning-layers/starter-fields")](None)
            ids = {p["id"] for p in catalog["payload"]["presets"]}
            for family, _ in FAMILIES:
                manifest = json.loads((LIBRARY / f"manifests/{family}.manifest.json").read_bytes())
                for complement in manifest["pixel_complements"]:
                    identifier = f"{family}:{complement['asset_id']}"
                    with self.subTest(complement=identifier):
                        self.assertNotIn(identifier, ids)
                        response = await handlers[("GET", "/conditioning-layers/starter-fields/{starter_id}")](
                            SimpleNamespace(match_info={"starter_id": identifier}))
                        self.assertEqual(response["status"], 404)

    async def test_every_candidate_single_field_with_fixture_only_promotion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            library = root / "library"
            copy_p1_library(library)
            with patch.object(starter_fields, "_LIBRARY_ROOT", library):
                self.assertEqual([p.to_json() for p in starter_fields.product_field_presets()], EXPECTED_CATALOG[:2])
            for family, _ in FAMILIES[1:]:
                change_manifest(library, family, lambda m: m.update(support_status="validated-product-asset"))
            with patch.object(starter_fields, "_LIBRARY_ROOT", library), offline_routes(root) as handlers:
                self.assertEqual([p.to_json() for p in starter_fields.product_field_presets()], EXPECTED_CATALOG)
                for entry in EXPECTED_CATALOG[2:]:
                    with self.subTest(field=entry["id"]):
                        await self.qualify(handlers, [entry["id"]], root / entry["id"].replace(":", "-"))

    async def test_top_bottom_pair_with_fixture_only_promotion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            library = root / "library"
            copy_p1_library(library)
            change_manifest(library, FAMILIES[1][0], lambda m: m.update(support_status="validated-product-asset"))
            with patch.object(starter_fields, "_LIBRARY_ROOT", library), offline_routes(root) as handlers:
                await self.qualify(handlers, [f"{FAMILIES[1][0]}:{x}" for x in "AB"], root / "pair")

    async def test_authoritative_catalog_and_every_exposed_field_through_staging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with offline_routes(root) as handlers:
                catalog = await handlers[("GET", "/conditioning-layers/starter-fields")](None)
                self.assertEqual(catalog["payload"]["presets"], EXPECTED_CATALOG)
                self.assertEqual(len({p["id"] for p in EXPECTED_CATALOG}), 13)
                for entry in catalog["payload"]["presets"]:
                    with self.subTest(field=entry["id"]):
                        await self.qualify(handlers, [entry["id"]], root / entry["id"].replace(":", "-"))


if __name__ == "__main__":
    unittest.main()
