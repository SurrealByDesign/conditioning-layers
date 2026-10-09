from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from conditioning_layers.comfyui.prediction_mixing import (
    DEFAULT_SUPPORTED_PROFILE,
    COMFYUI_0345_QUALIFICATION_PROFILE,
)
from conditioning_layers.integrations.comfyui_panel import routes as route_module
from conditioning_layers.integrations.comfyui_panel.application import ExistingBackendApplication

from conditioning_layers.integrations.comfyui_panel.models import PanelRequestError
from conditioning_layers.integrations.comfyui_panel.routes import (
    _read_document_multipart_request,
    _read_multipart_request,
    _trusted_model_directories,
)

from _support import grayscale_png, metadata, row
from test_application import host_context


class FakePart:
    def __init__(self, name, content_type, data):
        self.name = name
        self.headers = {"Content-Type": content_type}
        self._data = data
        self._read = False

    @property
    def filename(self):
        raise AssertionError("client filename must not be read")

    async def read_chunk(self, size):
        if self._read:
            return b""
        self._read = True
        return self._data


class FakeReader:
    def __init__(self, parts):
        self.parts = iter(parts)

    async def next(self):
        return next(self.parts, None)


class FakeRequest:
    def __init__(self, parts, content_type="multipart/form-data; boundary=test"):
        self.headers = {"Content-Type": content_type}
        self.content_length = None
        self.reader = FakeReader(parts)

    async def multipart(self):
        return self.reader


class RouteAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_qualification_fields_cannot_select_a_profile(self) -> None:
        for field in (
            "profile", "profile_identifier", "comfyui_profile_identifier",
            "compatibility", "qualification", "qualification_mode", "trusted_snapshot",
        ):
            with self.subTest(field=field):
                payload = json.loads(metadata([row("a")]))
                payload[field] = COMFYUI_0345_QUALIFICATION_PROFILE.inventory.comfyui_profile_identifier
                with self.assertRaises(PanelRequestError):
                    await _read_multipart_request(FakeRequest([
                        FakePart("request", "application/json", json.dumps(payload).encode("utf-8")),
                        FakePart("field-a", "image/png", grayscale_png(255, 0)),
                    ]))

    async def test_query_and_header_cannot_add_profile_selection_to_draft(self) -> None:
        request = FakeRequest([
            FakePart("request", "application/json", metadata([row("a")])),
            FakePart("field-a", "image/png", grayscale_png(255, 0)),
        ])
        candidate = COMFYUI_0345_QUALIFICATION_PROFILE.inventory.comfyui_profile_identifier
        request.query = {"compatibility": candidate, "profile": candidate}
        request.headers["X-Conditioning-Layers-Profile"] = candidate
        parsed = await _read_multipart_request(request)
        self.assertFalse(hasattr(parsed, "compatibility"))
        self.assertFalse(hasattr(parsed, "profile"))
        self.assertFalse(hasattr(parsed, "comfyui_profile_identifier"))

    async def test_strict_multipart_maps_without_reading_client_filename(self) -> None:
        request = FakeRequest(
            [
                FakePart("request", "application/json", metadata([row("a")])),
                FakePart("field-a", "image/png", grayscale_png(255, 0)),
            ]
        )
        draft = await _read_multipart_request(request)
        self.assertEqual(draft.layers[0].row_id, "a")

    async def test_document_multipart_maps_name_without_accepting_a_browser_path(self) -> None:
        payload = json.dumps(
            {
                "display_name": "Artist Study",
                "source_document_key": None,
                "document_id": None,
                "base_prompt": "Base",
                "layers": [row("a")],
            }
        ).encode("utf-8")
        draft = await _read_document_multipart_request(
            FakeRequest(
                [
                    FakePart("request", "application/json", payload),
                    FakePart("field-a", "image/png", grayscale_png(255, 0)),
                ]
            )
        )
        self.assertEqual(draft.display_name, "Artist Study")
        self.assertFalse(hasattr(draft, "filesystem_path"))

    async def test_non_multipart_unknown_part_and_wrong_metadata_mime_are_rejected(self) -> None:
        with self.subTest("content type"):
            with self.assertRaises(PanelRequestError) as raised:
                await _read_multipart_request(FakeRequest([], "application/json"))
            self.assertEqual(raised.exception.status, 415)

    async def test_model_directories_are_filtered_to_the_declared_trusted_root(self) -> None:
        from pathlib import Path
        import tempfile

        class FolderPaths:
            @staticmethod
            def get_folder_paths(category):
                return [str(trusted / category), str(outside / category)]

        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            trusted = base / "models"
            outside = base / "extra"
            result = _trusted_model_directories(FolderPaths, trusted)
        self.assertEqual(
            result,
            {
                category: (trusted.resolve() / category,)
                for category in ("diffusion_models", "text_encoders", "vae")
            },
        )
        with self.subTest("unknown part"):
            with self.assertRaises(PanelRequestError):
                await _read_multipart_request(
                    FakeRequest([FakePart("path", "text/plain", b"C:\\private")])
                )
        with self.subTest("metadata mime"):
            with self.assertRaises(PanelRequestError) as raised:
                await _read_multipart_request(
                    FakeRequest([FakePart("request", "text/plain", metadata([]))])
                )
            self.assertEqual(raised.exception.status, 415)


class RouteApplicationDefaultTests(unittest.TestCase):
    def test_registration_constructs_real_application_with_only_host_argument(self):
        registered = {}

        def route(method):
            def decorate(path):
                def capture(handler):
                    registered[method, path] = handler
                    return handler
                return capture
            return decorate

        fake_server = SimpleNamespace(PromptServer=SimpleNamespace(
            instance=SimpleNamespace(routes=SimpleNamespace(
                get=route("GET"), post=route("POST"), put=route("PUT")
            ))
        ))
        # Import-boundary fakes register closures without aiohttp or a host.
        with tempfile.TemporaryDirectory() as root:
            context = host_context(Path(root))
            with patch.dict(sys.modules, {
                "aiohttp": SimpleNamespace(web=SimpleNamespace()),
                "server": fake_server,
            }), patch.object(route_module, "_REGISTERED", False), patch.object(
                route_module, "_COORDINATOR", None
            ), patch.object(
                route_module, "_build_host_context", return_value=context
            ), patch.object(
                route_module, "ExistingBackendApplication", wraps=ExistingBackendApplication
            ) as application:
                route_module.register_routes()
                application.assert_called_once_with(context)
                self.assertIs(
                    route_module._COORDINATOR._application.compatibility,
                    DEFAULT_SUPPORTED_PROFILE,
                )
        self.assertIn(("POST", "/conditioning-layers/executions"), registered)


if __name__ == "__main__":
    unittest.main()
