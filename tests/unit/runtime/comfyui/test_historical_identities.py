from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from conditioning_layers.comfyui.prediction_mixing import (
    CANONICAL_COMFYUI_0280_INVENTORY,
)
from conditioning_layers.execution.comfyui import (
    AssociatedOutput,
    ExecutionState,
    ServerIdentityMode,
    ServerIdentitySnapshot,
)
from conditioning_layers.execution.comfyui.provenance import (
    build_execution_provenance,
    fingerprint_result_identity,
)
from conditioning_layers.runtime.comfyui import prepare_submission_bundle


FIXTURE_PATH = Path(__file__).with_name(
    "historical-identities.prediction-mixing-v1.json"
)
PROMPT_ID = "11111111-1111-4111-8111-111111111111"
LAUNCH_ARGUMENTS_SHA256 = "d" * 64


def _load_runtime_support():
    path = Path(__file__).with_name("_support.py")
    spec = importlib.util.spec_from_file_location(
        "_historical_identity_runtime_support", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RUNTIME_SUPPORT = _load_runtime_support()


def _portable(value: object) -> object:
    if is_dataclass(value):
        return {
            item.name: _portable(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _portable(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple | list):
        return [_portable(item) for item in value]
    if isinstance(value, Path):
        raise AssertionError("historical identity material must not contain paths")
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise AssertionError(f"unsupported historical identity value: {type(value)!r}")


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _build_case(root: Path, layer_ids: tuple[str, ...]) -> dict[str, object]:
    case = RUNTIME_SUPPORT.make_case(
        root,
        CANONICAL_COMFYUI_0280_INVENTORY,
        layer_ids=layer_ids,
    )
    prepared = prepare_submission_bundle(
        case.artifact,
        case.provenance,
        case.inventory,
        case.configuration,
        case.inspections,
        case.asset_root,
        case.node_snapshot,
    )
    assert prepared.ready and prepared.bundle is not None, prepared.errors
    bundle = prepared.bundle
    graph = bundle.to_api_graph()
    workflow_provenance = _portable(bundle.graph_artifact.provenance_inputs)
    runtime_provenance = _portable(bundle.provenance)
    translation_plan = _portable(case.translation_plan)
    save_node_id = next(
        node_id
        for node_id, node in graph.items()
        if node["class_type"] == "SaveImage"
    )
    output = AssociatedOutput(
        node_id=save_node_id,
        output_type="images",
        filename="request-1_00001_.png",
        subfolder="conditioning-layers/document-1",
        storage_type="output",
        relative_locator="conditioning-layers/document-1/request-1_00001_.png",
        metadata={},
    )
    server_identity = ServerIdentitySnapshot(
        profile_identifier=bundle.profile_identifier,
        comfyui_version=bundle.host_snapshot.observed_comfyui_version,
        comfyui_revision=bundle.host_snapshot.observed_comfyui_revision,
        revision_evidence="historical-golden-exact-revision",
        launch_arguments_sha256=LAUNCH_ARGUMENTS_SHA256,
        device_count=1,
        identity_mode=ServerIdentityMode.EXACT_REVISION,
        reported_comfyui_revision=bundle.host_snapshot.observed_comfyui_revision,
        trusted_snapshot_fingerprint=(
            bundle.host_snapshot.node_contract_snapshot_fingerprint
        ),
        finding_codes=("execution.server_identity_exact",),
    )
    execution = build_execution_provenance(
        bundle=bundle,
        server_identity=server_identity,
        prompt_id=PROMPT_ID,
        terminal_state=ExecutionState.COMPLETED,
        outputs=(output,),
        errors=(),
        warnings=(),
    )
    execution_provenance = _portable(execution)
    return {
        "active_layer_ids": list(layer_ids),
        "translation_fingerprint": case.translation_plan.fingerprint,
        "translation_plan_sha256": _sha256_json(translation_plan),
        "graph": graph,
        "graph_fingerprint": bundle.graph_fingerprint,
        "workflow_provenance_sha256": _sha256_json(workflow_provenance),
        "bundle_fingerprint": bundle.bundle_fingerprint,
        "runtime_provenance_sha256": _sha256_json(runtime_provenance),
        "execution_provenance_fingerprint": execution.provenance_fingerprint,
        "execution_provenance_sha256": _sha256_json(execution_provenance),
        "result_identity_fingerprint": fingerprint_result_identity(execution),
    }


def build_current_snapshot() -> dict[str, object]:
    with tempfile.TemporaryDirectory(
        prefix="conditioning-layers-historical-identities-"
    ) as temporary:
        root = Path(temporary)
        return {
            "fixture_id": "conditioning-layers.historical-identities.prediction-mixing.v1",
            "fixture_version": 1,
            "profile_identifier": (
                CANONICAL_COMFYUI_0280_INVENTORY.comfyui_profile_identifier
            ),
            "cases": {
                "one_active_prompt_layer": _build_case(root / "one", ("a",)),
                "two_active_prompt_layers": _build_case(root / "two", ("a", "b")),
            },
        }


class HistoricalIdentityRegressionTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.fixture_text = FIXTURE_PATH.read_text(encoding="utf-8")
        self.expected = json.loads(self.fixture_text)

    def test_fixture_file_has_canonical_readable_serialization(self) -> None:
        expected_text = (
            json.dumps(
                self.expected,
                allow_nan=False,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        self.assertEqual(self.fixture_text, expected_text)

    def test_one_layer_historical_identities_are_byte_stable(self) -> None:
        current = build_current_snapshot()["cases"]["one_active_prompt_layer"]
        self.assertEqual(
            current,
            self.expected["cases"]["one_active_prompt_layer"],
        )

    def test_two_layer_historical_identities_are_byte_stable(self) -> None:
        current = build_current_snapshot()["cases"]["two_active_prompt_layers"]
        self.assertEqual(
            current,
            self.expected["cases"]["two_active_prompt_layers"],
        )

    def test_fixture_contains_only_one_and_two_layer_cases(self) -> None:
        self.assertEqual(
            set(self.expected["cases"]),
            {"one_active_prompt_layer", "two_active_prompt_layers"},
        )
        self.assertEqual(
            self.expected["cases"]["one_active_prompt_layer"]["active_layer_ids"],
            ["a"],
        )
        self.assertEqual(
            self.expected["cases"]["two_active_prompt_layers"]["active_layer_ids"],
            ["a", "b"],
        )


if __name__ == "__main__":
    unittest.main()
