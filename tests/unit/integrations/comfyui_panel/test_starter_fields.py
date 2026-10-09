from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from conditioning_layers.integrations.comfyui_panel import routes, starter_fields
from conditioning_layers.integrations.comfyui_panel.application import materialize_document
from conditioning_layers.integrations.comfyui_panel.documents import (
    PanelDocumentStore,
    parse_document_request,
)
from conditioning_layers.integrations.comfyui_panel.models import (
    MAX_FIELD_BYTES,
    PanelRequestError,
    UploadedField,
    parse_panel_request,
)
from conditioning_layers.persistence import document_asset_root, save_document

from _support import grayscale_png, metadata, row, upload


LIBRARY = Path(__file__).parents[4] / "influence-field-library" / "v1"
MANIFEST = Path("manifests/two-layer.left-right.v1.manifest.json")
EXPECTED = {
    "left": ("field-a.png", "0c519e60efdffbfebbbe2c60235a0f03fb10af8f33d1d3f59c900739ae0fd3e0", (255, 0)),
    "right": ("field-b.png", "b649d32ce6f7481291adaa4b7e68988ade1d9ec53e9624bbf52dd92be628ee4d", (0, 255)),
}


def copy_library(root: Path) -> None:
    (root / MANIFEST).parent.mkdir(parents=True)
    shutil.copyfile(LIBRARY / "library-manifest.json", root / "library-manifest.json")
    catalog_path = root / "library-manifest.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["families"] = catalog["families"][:1]
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    shutil.copyfile(LIBRARY / MANIFEST, root / MANIFEST)
    family = root / "two-layer/left-right"
    family.mkdir(parents=True)
    for filename, _checksum, _pixels in EXPECTED.values():
        shutil.copyfile(LIBRARY / "two-layer/left-right" / filename, family / filename)


def write_manifest(root: Path, manifest: dict) -> None:
    """Keep synthetic catalog identity valid to exercise deeper checks."""
    (root / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    refresh_catalog_hash(root)


def refresh_catalog_hash(root: Path) -> None:
    catalog_path = root / "library-manifest.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["families"][0]["manifest_sha256"] = hashlib.sha256((root / MANIFEST).read_bytes()).hexdigest()
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")


def parse_execution(rows, uploads):
    body = metadata(rows)
    return parse_panel_request(
        body, uploads, multipart_part_count=len(uploads) + 1,
        total_bytes=len(body) + sum(len(item.data) for item in uploads.values()),
    )


def parse_save(name, rows, uploads):
    body = json.dumps({
        "display_name": name, "source_document_key": None, "document_id": None,
        "base_prompt": "Base", "layers": rows,
    }).encode("utf-8")
    return parse_document_request(
        body, uploads, multipart_part_count=len(uploads) + 1,
        total_bytes=len(body) + sum(len(item.data) for item in uploads.values()),
    )


class StarterFieldTests(unittest.TestCase):
    def assert_starter(self, side):
        filename, checksum, pixels = EXPECTED[side]
        data = starter_fields.read_starter_field(side)
        self.assertEqual(data, (LIBRARY / "two-layer/left-right" / filename).read_bytes())
        self.assertEqual(hashlib.sha256(data).hexdigest(), checksum)
        # This exact grayscale fixture is white for x < 64 on Left, x >= 64
        # on Right, with the opposite half black throughout all 128 rows.
        self.assertEqual(data, grayscale_png(*pixels))

    def test_left_is_the_retained_authoritative_left_png(self):
        self.assert_starter("left")

    def test_right_is_the_retained_authoritative_right_png(self):
        self.assert_starter("right")

    def test_only_exact_left_and_right_ids_are_supported(self):
        for invalid in ("", "A", "Left", "top", "not-A", "../left", None, [], "left.png"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(PanelRequestError) as raised:
                    starter_fields.read_starter_field(invalid)
                self.assertEqual(raised.exception.status, 404)
                self.assertEqual(raised.exception.finding.code, "panel.starter.not_found")

    def test_missing_authority_is_bounded_and_does_not_disclose_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "private-library-name"
            with patch.object(starter_fields, "_LIBRARY_ROOT", root):
                with self.assertRaises(PanelRequestError) as raised:
                    starter_fields.read_starter_field("left")
            self.assertEqual(raised.exception.status, 503)
            self.assertEqual(raised.exception.finding.code, "panel.starter.unavailable")
            self.assertNotIn(str(root), raised.exception.finding.message)
            self.assertIn("Custom PNG", raised.exception.finding.message)

    def test_unsupported_or_malformed_manifest_is_rejected(self):
        for change in (
            {"support_status": "research-only"}, {"pattern_family_id": "other"},
            {"schema_version": True}, {"library_version": 2}, {"fields": []},
            {"fields": [{"asset_id": "A"}, {"asset_id": "A"}]},
        ):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                copy_library(root)
                manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
                manifest.update(change)
                write_manifest(root, manifest)
                with patch.object(starter_fields, "_LIBRARY_ROOT", root):
                    with self.assertRaises(PanelRequestError) as raised:
                        starter_fields.read_starter_field("left")
                    self.assertEqual(raised.exception.status, 503)

    def test_manifest_parse_failure_is_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copy_library(root)
            (root / MANIFEST).write_bytes(b"{broken")
            refresh_catalog_hash(root)
            with patch.object(starter_fields, "_LIBRARY_ROOT", root):
                with self.assertRaises(PanelRequestError) as raised:
                    starter_fields.read_starter_field("left")
            self.assertEqual(raised.exception.status, 503)

    def test_catalog_pins_manifest_identity_and_product_support(self):
        for damage in ("manifest_hash", "catalog_support", "duplicate_family"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                copy_library(root)
                if damage == "manifest_hash":
                    # Still valid JSON and PNG references, but no longer the
                    # catalog's exact retained family manifest bytes.
                    with (root / MANIFEST).open("ab") as stream:
                        stream.write(b" ")
                else:
                    catalog_path = root / "library-manifest.json"
                    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
                    if damage == "catalog_support":
                        catalog["families"][0]["support_status"] = "research-only"
                    else:
                        catalog["families"].append(catalog["families"][0])
                    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
                with patch.object(starter_fields, "_LIBRARY_ROOT", root):
                    with self.assertRaises(PanelRequestError) as raised:
                        starter_fields.read_starter_field("left")
                self.assertEqual(raised.exception.status, 503)

    def test_missing_nonregular_oversized_or_changed_png_is_rejected(self):
        for damage in ("missing", "directory", "oversized", "checksum"):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                copy_library(root)
                asset = root / "two-layer/left-right/field-a.png"
                if damage in {"missing", "directory"}:
                    asset.unlink()
                    if damage == "directory":
                        asset.mkdir()
                elif damage == "oversized":
                    asset.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * MAX_FIELD_BYTES)
                else:
                    asset.write_bytes(grayscale_png(0, 255))
                with patch.object(starter_fields, "_LIBRARY_ROOT", root):
                    with self.assertRaises(PanelRequestError) as raised:
                        starter_fields.read_starter_field("left")
                self.assertEqual(raised.exception.status, 503)

    def test_manifest_cannot_select_paths_outside_the_fixed_family(self):
        for filename in ("../outside.png", "/outside.png", "C:/private/field.png", "two-layer\\left-right\\field-a.png", "two-layer/top-bottom/field-a.png"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                copy_library(root)
                outside_family = root / "two-layer/top-bottom"
                outside_family.mkdir()
                (outside_family / "field-a.png").write_bytes(grayscale_png(255, 0))
                manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
                manifest["fields"][0]["filename"] = filename
                write_manifest(root, manifest)
                with patch.object(starter_fields, "_LIBRARY_ROOT", root):
                    with self.assertRaises(PanelRequestError) as raised:
                        starter_fields.read_starter_field("left")
                self.assertEqual(raised.exception.status, 503)

    def test_symlink_escape_cannot_serve_starter_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "library"
            copy_library(root)
            outside = base / "outside.png"
            outside.write_bytes(grayscale_png(255, 0))
            asset = root / "two-layer/left-right/field-a.png"
            asset.unlink()
            try:
                asset.symlink_to(outside)
            except OSError:
                self.skipTest("platform does not permit creating symlinks")
            with patch.object(starter_fields, "_LIBRARY_ROOT", root):
                with self.assertRaises(PanelRequestError) as raised:
                    starter_fields.read_starter_field("left")
            self.assertEqual(raised.exception.status, 503)

    def test_starter_and_manual_upload_have_identical_canonical_execution_intent(self):
        rows = [row("a", strength=0.375), row("b", active=False)]
        starters = {
            "field-a": upload("a", starter_fields.read_starter_field("left")),
            "field-b": upload("b", starter_fields.read_starter_field("right")),
        }
        manual = {
            "field-a": upload("a", (LIBRARY / "two-layer/left-right/field-a.png").read_bytes()),
            "field-b": upload("b", (LIBRARY / "two-layer/left-right/field-b.png").read_bytes()),
        }
        starter_draft, manual_draft = parse_execution(rows, starters), parse_execution(rows, manual)
        self.assertEqual(starter_draft, manual_draft)
        self.assertEqual(starter_draft.fingerprint, manual_draft.fingerprint)
        self.assertIsInstance(starter_draft.layers[0].field, UploadedField)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = materialize_document(starter_draft, "a" * 32, root / "starter")
            second = materialize_document(manual_draft, "a" * 32, root / "manual")
            self.assertEqual(first.document, second.document)
            for layer in first.document.layers:
                relative = layer.influence_field.relative_path
                self.assertEqual((first.asset_root / relative).read_bytes(), (second.asset_root / relative).read_bytes())

    def test_save_open_and_preview_use_ordinary_owned_fields_without_starter_identity(self):
        rows = [row("left", strength=0.625), row("right", active=False)]
        uploads = {f"field-{side}": upload(side, starter_fields.read_starter_field(side)) for side in EXPECTED}
        with tempfile.TemporaryDirectory() as temporary:
            store = PanelDocumentStore(Path(temporary) / "user")
            saved = store.save_as(parse_save("Starters", rows, uploads))
            opened = store.open(saved.document_key)
            self.assertEqual(saved.document, opened.document)
            encoded = (store.root / "starters.conditioning.json").read_bytes()
            self.assertNotIn(b"starter", encoded)
            self.assertNotIn(b"influence-field-library", encoded)
            for side, layer in zip(EXPECTED, opened.document.layers):
                self.assertEqual(layer.influence_field.checksum, EXPECTED[side][1])
                self.assertEqual(layer.influence_field.relative_path, f"fields/{layer.layer_id}.png")
                self.assertEqual(store.read_field(saved.document_key, layer.layer_id), uploads[f"field-{side}"].data)
                self.assertEqual(opened.field_bytes[layer.layer_id], uploads[f"field-{side}"].data)

    def test_pre_m3_saved_format_and_custom_png_open_without_any_library(self):
        draft = parse_execution([row("custom", strength=0.25)], {"field-custom": upload("custom", grayscale_png(64, 128))})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = PanelDocumentStore(root / "user")
            legacy = materialize_document(draft, "f" * 32, root / "legacy")
            store.root.mkdir(parents=True)
            path = store.root / "pre-m3.conditioning.json"
            shutil.copytree(legacy.asset_root, document_asset_root(path))
            save_document(legacy.document, path)
            before = path.read_bytes()
            with patch.object(starter_fields, "_LIBRARY_ROOT", root / "absent-library"):
                opened = store.open("pre-m3")
                self.assertEqual(opened.document, legacy.document)
                self.assertEqual(store.read_field("pre-m3", opened.document.layers[0].layer_id), grayscale_png(64, 128))
                self.assertEqual(opened.to_json()["layers"][0]["field_persisted"], True)
            self.assertEqual(path.read_bytes(), before)


class StarterRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_only_route_returns_png_and_bounded_errors_without_execution(self):
        handlers = {}

        def register(method):
            def decorate(path):
                def record(handler):
                    handlers[(method, path)] = handler
                    return handler
                return record
            return decorate

        registry = SimpleNamespace(get=register("GET"), post=register("POST"), put=register("PUT"))
        web = SimpleNamespace(Response=lambda **kwargs: kwargs, json_response=lambda payload, **kwargs: {"payload": payload, **kwargs})
        server = SimpleNamespace(PromptServer=SimpleNamespace(instance=SimpleNamespace(routes=registry)))
        with tempfile.TemporaryDirectory() as temporary:
            context = SimpleNamespace(host_configuration=SimpleNamespace(user_directory=Path(temporary)))
            with (
                patch.dict(sys.modules, {"aiohttp": SimpleNamespace(web=web), "server": server}),
                patch.object(routes, "_build_host_context", return_value=context),
                patch.object(routes, "_REGISTERED", False),
                patch.object(routes, "_COORDINATOR", None),
                patch.object(routes.PanelJobCoordinator, "submit", side_effect=AssertionError("must not execute")),
            ):
                routes.register_routes()
                guidance = await handlers[("GET", "/conditioning-layers/capabilities")](None)
                self.assertEqual(guidance["payload"], routes.panel_capability_guidance())
                self.assertEqual(guidance["headers"]["Cache-Control"], "no-store")
                catalog_handler = handlers[("GET", "/conditioning-layers/starter-fields")]
                catalog = await catalog_handler(None)
                self.assertEqual(catalog["payload"], {"presets": [
                    p.to_json() for p in starter_fields.product_field_presets()
                ]})
                self.assertEqual(catalog["headers"]["Cache-Control"], "no-store")
                with patch.object(routes, "product_field_presets", return_value=()):
                    self.assertEqual((await catalog_handler(None))["payload"], {"presets": []})
                handler = handlers[("GET", "/conditioning-layers/starter-fields/{starter_id}")]
                preset = await handler(SimpleNamespace(match_info={"starter_id": "two-layer.left-right.v1:A"}))
                self.assertEqual(preset["body"], starter_fields.read_starter_field("left"))
                response = await handler(SimpleNamespace(match_info={"starter_id": "right"}))
                self.assertEqual(response["body"], starter_fields.read_starter_field("right"))
                self.assertEqual(response["content_type"], "image/png")
                self.assertEqual(response["headers"]["Cache-Control"], "no-store")
                missing = await handler(SimpleNamespace(match_info={"starter_id": "../other"}))
                self.assertEqual(missing["status"], 404)
                with patch.object(starter_fields, "_LIBRARY_ROOT", Path(temporary) / "absent"):
                    unavailable = await handler(SimpleNamespace(match_info={"starter_id": "left"}))
                    catalog_unavailable = await catalog_handler(None)
                    self.assertEqual(catalog_unavailable["status"], 503)
                    self.assertNotIn(temporary, json.dumps(catalog_unavailable))
                self.assertEqual(unavailable["status"], 503)
                self.assertEqual(unavailable["payload"]["findings"][0]["code"], "panel.starter.unavailable")
                self.assertNotIn(temporary, json.dumps(unavailable))
        self.assertNotIn(("POST", "/conditioning-layers/starter-fields/{starter_id}"), handlers)
        self.assertNotIn(("POST", "/conditioning-layers/starter-fields"), handlers)


if __name__ == "__main__":
    unittest.main()
