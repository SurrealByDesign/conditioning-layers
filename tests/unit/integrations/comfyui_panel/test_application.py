from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from conditioning_layers.capabilities.multi_layer import ORDINARY_PRODUCT_ENTRY_IDENTIFIER
from conditioning_layers.execution.comfyui import (
    ComfyUIExecutionPolicy,
    ComfyUIServerConfiguration,
    ExecutionState,
)
from conditioning_layers.integrations.comfyui_panel.application import (
    ExistingBackendApplication,
    PanelHostContext,
)
from conditioning_layers.integrations.comfyui_panel.documents import (
    PanelDocumentDraft,
    PanelDocumentStore,
)
from conditioning_layers.integrations.comfyui_panel.models import (
    PanelExecutionDraft,
    PanelLayerDraft,
    RetainedField,
    parse_panel_request,
)
from conditioning_layers.runtime.comfyui import (
    ComfyUIHostConfiguration,
    StagingCleanupPolicy,
)

from _support import grayscale_png, metadata, row, upload


def host_context(root: Path) -> PanelHostContext:
    configuration = ComfyUIHostConfiguration(
        comfyui_root=root / "ComfyUI",
        input_directory=root / "input",
        output_directory=root / "output",
        user_directory=root / "user",
        model_root=root / "models",
        model_directories={
            "diffusion_models": (root / "models" / "diffusion_models",),
            "text_encoders": (root / "models" / "text_encoders",),
            "vae": (root / "models" / "vae",),
        },
        git_checkout_path=root / "ComfyUI",
        supported_profile_identifier="krea2-turbo-bf16-1024-comfyui-0.28.0.v1",
        launch_profile_identifier="test-loopback-8000",
        staging_cleanup_policy=StagingCleanupPolicy.CALLER_MANAGED,
        checkout_trusted_root=root,
        data_trusted_root=root,
        model_trusted_root=root / "models",
    )
    return PanelHostContext(
        host_configuration=configuration,
        server_configuration=ComfyUIServerConfiguration(port=8000),
        execution_policy=ComfyUIExecutionPolicy(),
    )


def draft(rows, field_data):
    uploads = {
        f"field-{item['row_id']}": upload(item["row_id"], field_data[index])
        for index, item in enumerate(rows)
    }
    body = metadata(rows)
    return parse_panel_request(
        body,
        uploads,
        multipart_part_count=len(rows) + 1,
        total_bytes=len(body) + sum(len(item.data) for item in uploads.values()),
    )


class ApplicationTests(unittest.TestCase):
    def test_opened_document_executes_with_verified_retained_field(self) -> None:
        calls = []
        with tempfile.TemporaryDirectory() as root:
            context = host_context(Path(root))
            store = PanelDocumentStore(context.host_configuration.user_directory)
            saved = store.save_as(
                PanelDocumentDraft(
                    display_name="Retained",
                    source_document_key=None,
                    document_id=None,
                    base_prompt="Base",
                    layers=(
                        PanelLayerDraft(
                            row_id="row-a",
                            layer_id=None,
                            name="Layer A",
                            prompt_text="Red object",
                            strength=1.0,
                            active=True,
                            field=upload("row-a", grayscale_png(255, 0)),
                        ),
                    ),
                )
            )
            layer = saved.document.layers[0]
            request = PanelExecutionDraft(
                base_prompt=saved.document.base_prompt,
                layers=(
                    PanelLayerDraft(
                        row_id="opened-a",
                        layer_id=layer.layer_id,
                        name=layer.name,
                        prompt_text=layer.prompt_text,
                        strength=layer.strength,
                        active=layer.visible,
                        field=RetainedField(layer.layer_id),
                    ),
                ),
                idempotency_key="retained-request",
                document_id=saved.document.document_id,
                document_key=saved.document_key,
            )
            execution = SimpleNamespace(
                completed=True,
                terminal_state=ExecutionState.COMPLETED,
                errors=(),
                outputs=(
                    SimpleNamespace(
                        filename="retained_00001_.png",
                        subfolder="conditioning-layers-panel",
                        storage_type="output",
                    ),
                ),
            )
            prepared = SimpleNamespace(ready=True, bundle=object(), errors=())
            with patch(
                "conditioning_layers.integrations.comfyui_panel.application.prepare_submission_bundle",
                return_value=prepared,
            ):
                result = ExistingBackendApplication(
                    context,
                    execution_client=lambda *args, **kwargs: calls.append(args) or execution,
                ).run(request, "f" * 32, lambda _state: None)

        self.assertEqual(result.state, "completed")
        self.assertEqual(len(calls), 1)

    def test_closed_admission_fixture_rejects_three_active_layers_before_submission(self) -> None:
        rows = [row("a"), row("b"), row("c")]
        request = draft(rows, [grayscale_png(255, 0)] * 3)
        calls = []
        with tempfile.TemporaryDirectory() as root, patch(
            "conditioning_layers.capabilities.multi_layer.PRODUCT_ADMITTED_ENTRIES",
            (ORDINARY_PRODUCT_ENTRY_IDENTIFIER,),
        ), patch(
            "conditioning_layers.integrations.comfyui_panel.application.translate_prediction_mixing"
        ) as translate, patch(
            "conditioning_layers.integrations.comfyui_panel.application.prepare_submission_bundle"
        ) as prepare, patch(
            "conditioning_layers.adapters.prediction_mixing.multi_layer.translate_prediction_mixing_multi_layer"
        ) as successor, patch(
            "conditioning_layers.runtime.comfyui.multi_layer.stage_field_assets"
        ) as stage:
            result = ExistingBackendApplication(
                host_context(Path(root)),
                execution_client=lambda *args: calls.append(args),
            ).run(request, "a" * 32, lambda _state: None)
        self.assertEqual(result.state, "rejected")
        self.assertIn("capability.active_layer_limit", {item.code for item in result.findings})
        self.assertIn("capability.product_not_admitted", {item.code for item in result.findings})
        translate.assert_not_called()
        successor.assert_not_called()
        prepare.assert_not_called()
        stage.assert_not_called()
        self.assertEqual(calls, [])

    def test_invalid_png_and_two_field_overlap_prevent_submission(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            context = host_context(Path(root))
            invalid_request = draft([row("a")], [b"\x89PNG\r\n\x1a\ninvalid"])
            invalid = ExistingBackendApplication(context).run(
                invalid_request, "b" * 32, lambda _state: None
            )
            self.assertEqual(invalid.state, "rejected")
            self.assertTrue(invalid.findings)

            overlapping_request = draft(
                [row("a"), row("b")],
                [grayscale_png(255, 255), grayscale_png(255, 255)],
            )
            overlap = ExistingBackendApplication(context).run(
                overlapping_request, "c" * 32, lambda _state: None
            )
            self.assertEqual(overlap.state, "rejected")
            self.assertIn("translation.overlap_present", {item.code for item in overlap.findings})

    def test_supported_request_uses_existing_pipeline_and_submits_exactly_once(self) -> None:
        request = draft(
            [row("left", prompt="Red object"), row("right", prompt="Blue object")],
            [grayscale_png(255, 0), grayscale_png(0, 255)],
        )
        calls = []
        states = []

        def execute(bundle, server, policy, *, trusted_snapshot):
            calls.append((bundle, server, policy))
            return SimpleNamespace(
                completed=True,
                terminal_state=ExecutionState.COMPLETED,
                errors=(),
                outputs=(
                    SimpleNamespace(
                        filename="result_00001_.png",
                        subfolder="conditioning-layers-panel",
                        storage_type="output",
                    ),
                ),
            )

        prepared = SimpleNamespace(ready=True, bundle=object(), errors=())
        with tempfile.TemporaryDirectory() as root, patch(
            "conditioning_layers.integrations.comfyui_panel.application.prepare_submission_bundle",
            return_value=prepared,
        ) as prepare:
            result = ExistingBackendApplication(
                host_context(Path(root)), execution_client=execute
            ).run(request, "d" * 32, states.append)

        self.assertEqual(result.state, "completed")
        self.assertEqual(states, ["validating", "preparing", "executing"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(prepare.call_count, 1)
        self.assertEqual(
            {item.code for item in result.findings},
            {
                "capability.adapter_experimental",
                "risk.seam",
                "risk.leakage",
                "risk.fusion",
                "risk.topology",
                "risk.runtime_scaling",
                "risk.vram",
            },
        )
        self.assertIsNotNone(result.output)
        self.assertEqual(
            result.output.view_url,
            "/view?filename=result_00001_.png&subfolder=conditioning-layers-panel&type=output",
        )
        self.assertNotIn("\\", result.output.view_url)

    def test_wrong_port_fails_before_document_or_submission(self) -> None:
        request = draft([row("a")], [grayscale_png(255, 0)])
        calls = []
        with tempfile.TemporaryDirectory() as root:
            context = host_context(Path(root))
            context = PanelHostContext(
                host_configuration=context.host_configuration,
                server_configuration=ComfyUIServerConfiguration(port=8001),
                execution_policy=context.execution_policy,
            )
            result = ExistingBackendApplication(
                context, execution_client=lambda *args: calls.append(args)
            ).run(request, "e" * 32, lambda _state: None)
        self.assertEqual(result.state, "rejected")
        self.assertEqual(result.findings[0].code, "panel.host.port")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
