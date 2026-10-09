from __future__ import annotations

import ast
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[4]
PACKAGE_ROOT = ROOT / "src" / "conditioning_layers"
ADAPTER_DIRECTORY = PACKAGE_ROOT / "adapters" / "prediction_mixing"
INWARD_DIRECTORIES = (
    PACKAGE_ROOT / "domain",
    PACKAGE_ROOT / "persistence",
    PACKAGE_ROOT / "capabilities",
)
BANNED_IMPORT_ROOTS = {
    "comfy",
    "comfyui",
    "frontend",
    "krea",
    "numpy",
    "PIL",
    "torch",
}
ALLOWED_ADAPTER_IMPORT_ROOTS = {
    "__future__",
    "collections",
    "conditioning_layers",
    "dataclasses",
    "decimal",
    "enum",
    "hashlib",
    "importlib",
    "json",
    "math",
    "re",
    "typing",
}


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


class AdapterArchitectureTests(unittest.TestCase):
    def test_domain_persistence_and_capabilities_do_not_import_adapters(self) -> None:
        offenders: list[str] = []
        for directory in INWARD_DIRECTORIES:
            for path in directory.glob("*.py"):
                text = path.read_text(encoding="utf-8")
                if "conditioning_layers.adapters" in text or "..adapters" in text:
                    offenders.append(str(path.relative_to(ROOT)))

        self.assertEqual(offenders, [])

    def test_adapter_does_not_import_persistence(self) -> None:
        offenders = [
            path.name
            for path in ADAPTER_DIRECTORY.rglob("*.py")
            if "conditioning_layers.persistence" in path.read_text(encoding="utf-8")
            or "..persistence" in path.read_text(encoding="utf-8")
        ]

        self.assertEqual(offenders, [])

    def test_adapter_has_only_standard_library_and_inward_absolute_imports(self) -> None:
        unexpected: dict[str, set[str]] = {}
        for path in ADAPTER_DIRECTORY.rglob("*.py"):
            outside = imported_roots(path) - ALLOWED_ADAPTER_IMPORT_ROOTS
            if outside:
                unexpected[path.name] = outside

        self.assertEqual(unexpected, {})

    def test_adapter_does_not_import_host_image_or_execution_runtimes(self) -> None:
        banned: dict[str, set[str]] = {}
        for path in ADAPTER_DIRECTORY.rglob("*.py"):
            matches = imported_roots(path) & BANNED_IMPORT_ROOTS
            if matches:
                banned[path.name] = matches

        self.assertEqual(banned, {})

    def test_importing_adapter_does_not_load_banned_runtime_modules(self) -> None:
        importlib.import_module("conditioning_layers.adapters.prediction_mixing")
        loaded_roots = {name.split(".", 1)[0] for name in sys.modules}

        self.assertEqual(loaded_roots & BANNED_IMPORT_ROOTS, set())

    def test_no_runtime_dependency_manifest_was_added(self) -> None:
        manifests = {
            "pyproject.toml",
            "requirements.txt",
            "setup.py",
            "setup.cfg",
            "Pipfile",
            "poetry.lock",
            "uv.lock",
        }

        self.assertEqual(
            {name for name in manifests if (ROOT / name).exists()},
            set(),
        )

    def test_translation_v2_has_no_production_consumer(self) -> None:
        v2_directory = ADAPTER_DIRECTORY / "v2"
        # ADR-0024 reuses these unchanged value/canonical/projection/topology
        # primitives. It does not authorize consuming Plan v2 or its translator.
        prefix = "conditioning_layers.adapters.prediction_mixing.v2."
        shared_imports = {
            ADAPTER_DIRECTORY / "multi_layer" / "models.py": {
                "identity": {"fingerprint_without_field"},
                "models": {"AbstractFoldStep", "DocumentExecutionProjection",
                           "OrderedLeftFoldTopologyPolicy", "TranslationStatus"},
            },
            ADAPTER_DIRECTORY / "multi_layer" / "translate.py": {
                "canonical": {"canonical_json_bytes"},
                "identity": {"exact_contract_equal", "fingerprint_document_execution_projection",
                             "fingerprint_without_field"},
                "models": {"DocumentExecutionProjection", "TranslationStatus"},
                "projections": {"build_document_execution_projection"},
                "topology": {"ORDERED_LEFT_FOLD_TOPOLOGY_POLICY", "build_ordered_left_fold_schedule"},
            },
            PACKAGE_ROOT / "comfyui" / "prediction_mixing" / "multi_layer" / "authority.py": {
                "topology": {"ORDERED_LEFT_FOLD_TOPOLOGY_POLICY"},
            },
            # ADR-0025/0026 retain these value, exact identity and ordered-fold
            # primitives. Blend consumes its own Plan v4, never Plan v2 or the
            # isolated translator/emitter/qualification pipeline.
            ADAPTER_DIRECTORY / "blend" / "models.py": {
                "identity": {"fingerprint_without_field"},
                "models": {"AbstractFoldStep", "OrderedLeftFoldTopologyPolicy", "TranslationStatus"},
            },
            ADAPTER_DIRECTORY / "blend" / "translate.py": {
                "canonical": {"canonical_json_bytes"},
                "identity": {"exact_contract_equal", "fingerprint_without_field"},
                "models": {"TranslationStatus"},
                "topology": {"ORDERED_LEFT_FOLD_TOPOLOGY_POLICY", "build_ordered_left_fold_schedule"},
            },
            PACKAGE_ROOT / "comfyui" / "prediction_mixing" / "blend" / "authority.py": {
                "identity": {"exact_contract_equal"},
                "topology": {"ORDERED_LEFT_FOLD_TOPOLOGY_POLICY"},
            },
            PACKAGE_ROOT / "comfyui" / "prediction_mixing" / "blend" / "graph.py": {
                "identity": {"exact_contract_equal"},
            },
            # ADR-0028 Slice B graph-v4 successor reuses the same two primitives.
            PACKAGE_ROOT / "comfyui" / "prediction_mixing" / "generalized_blend" / "authority.py": {
                "identity": {"exact_contract_equal"},
                "topology": {"ORDERED_LEFT_FOLD_TOPOLOGY_POLICY"},
            },
            PACKAGE_ROOT / "comfyui" / "prediction_mixing" / "generalized_blend" / "graph.py": {
                "identity": {"exact_contract_equal"},
            },
        }
        tokens = (
            "conditioning_layers.adapters.prediction_mixing.v2",
            "TranslationPlanV2",
            "translate_prediction_mixing_v2",
        )
        offenders: list[str] = []
        for path in PACKAGE_ROOT.rglob("*.py"):
            if path.is_relative_to(v2_directory):
                continue
            text = path.read_text(encoding="utf-8")
            if path in shared_imports:
                self.assertNotIn("TranslationPlanV2", text)
                self.assertNotIn("translate_prediction_mixing_v2", text)
                for node in ast.walk(ast.parse(text)):
                    if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(prefix):
                        allowed = shared_imports[path].get(node.module.removeprefix(prefix), set())
                        self.assertTrue({alias.name for alias in node.names} <= allowed, (path, node.module))
                    elif isinstance(node, ast.Import):
                        self.assertFalse(any(alias.name.startswith(prefix) for alias in node.names))
                continue
            if any(token in text for token in tokens):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_logical_graph_v2_has_only_the_isolated_emitter_consumers(self) -> None:
        v2_directory = ADAPTER_DIRECTORY / "v2"
        ingress_consumer = (
            PACKAGE_ROOT
            / "comfyui"
            / "prediction_mixing"
            / "emitter_v2"
            / "ingress.py"
        )
        realization_consumer = (
            PACKAGE_ROOT
            / "comfyui"
            / "prediction_mixing"
            / "emitter_v2"
            / "realization.py"
        )
        realization_v3_consumer = (
            PACKAGE_ROOT
            / "comfyui"
            / "prediction_mixing"
            / "emitter_v2"
            / "realization_v3.py"
        )
        allowed_consumers = {
            ingress_consumer,
            realization_consumer,
            realization_v3_consumer,
        }
        tokens = (
            "LogicalExecutionGraph",
            "translate_plan_to_logical_execution_graph",
            "prediction-mixing.logical-execution-graph.v1",
        )
        offenders: list[str] = []
        for path in PACKAGE_ROOT.rglob("*.py"):
            if path.is_relative_to(v2_directory) or path in allowed_consumers:
                continue
            text = path.read_text(encoding="utf-8")
            if any(token in text for token in tokens):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_logical_graph_engine_depends_only_on_v2_contracts(self) -> None:
        allowed_relative_modules = {
            "canonical",
            "collections.abc",
            "dataclasses",
            "enum",
            "identity",
            "logical_graph_models",
            "models",
            "re",
            "topology",
        }
        unexpected: dict[str, set[str]] = {}
        for path in (
            ADAPTER_DIRECTORY / "v2" / "logical_graph.py",
            ADAPTER_DIRECTORY / "v2" / "logical_graph_models.py",
        ):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            modules: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level > 0:
                    modules.add(node.module or "")
                elif (
                    isinstance(node, ast.ImportFrom)
                    and node.level == 0
                    and node.module != "__future__"
                ):
                    modules.add(node.module or "")
            outside = modules - allowed_relative_modules
            if outside:
                unexpected[path.name] = outside
        self.assertEqual(unexpected, {})

    def test_fresh_logical_graph_import_loads_no_forbidden_subsystem(self) -> None:
        script = """
import json
import sys
import conditioning_layers.adapters.prediction_mixing.v2.logical_graph

forbidden_prefixes = (
    "conditioning_layers.persistence",
    "conditioning_layers.runtime",
    "conditioning_layers.execution",
    "conditioning_layers.bundle",
    "conditioning_layers.bundles",
    "conditioning_layers.panel",
    "conditioning_layers.experiments",
    "aiohttp",
    "comfy",
    "comfyui",
)
forbidden_fragments = ("output_association", ".http", ".routes")
loaded = sorted(
    name
    for name in sys.modules
    if name.startswith(forbidden_prefixes)
    or any(fragment in name for fragment in forbidden_fragments)
)
print(json.dumps(loaded))
"""
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONPATH"] = str(ROOT / "src")
        with tempfile.TemporaryDirectory() as temporary_directory:
            completed = subprocess.run(
                [sys.executable, "-c", script],
                cwd=temporary_directory,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
        self.assertEqual(json.loads(completed.stdout), [])


if __name__ == "__main__":
    unittest.main()
