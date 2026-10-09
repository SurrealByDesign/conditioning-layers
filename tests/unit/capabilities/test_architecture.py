from __future__ import annotations

import ast
import importlib
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[3]
DOMAIN_DIRECTORY = ROOT / "src" / "conditioning_layers" / "domain"
PERSISTENCE_DIRECTORY = ROOT / "src" / "conditioning_layers" / "persistence"
CAPABILITY_DIRECTORY = ROOT / "src" / "conditioning_layers" / "capabilities"
BANNED_IMPORT_ROOTS = {
    "comfy",
    "comfyui",
    "frontend",
    "krea",
    "numpy",
    "PIL",
    "torch",
}
ALLOWED_CAPABILITY_IMPORT_ROOTS = {
    "__future__",
    "collections",
    "conditioning_layers",
    "dataclasses",
    "enum",
    "hashlib",
    "json",
    "math",
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


class CapabilityImportBoundaryTests(unittest.TestCase):
    def test_domain_does_not_import_capabilities(self) -> None:
        offenders: list[str] = []
        for path in DOMAIN_DIRECTORY.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "conditioning_layers.capabilities" in text or "..capabilities" in text:
                offenders.append(str(path.relative_to(ROOT)))

        self.assertEqual(offenders, [])

    def test_domain_contains_no_prediction_mixing_capability_policy(self) -> None:
        forbidden = {
            "capability.active_layer_limit",
            "maximum_tested_visible_prompt_layers",
            "validate_prediction_mixing_capability",
        }
        offenders: dict[str, set[str]] = {}
        for path in DOMAIN_DIRECTORY.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            matches = {item for item in forbidden if item in text}
            if matches:
                offenders[str(path.relative_to(ROOT))] = matches

        self.assertEqual(offenders, {})

    def test_persistence_capability_diagnostics_use_capability_layer(self) -> None:
        codec = (PERSISTENCE_DIRECTORY / "json_codec.py").read_text(encoding="utf-8")

        self.assertIn(
            "from conditioning_layers.capabilities import evaluate_prediction_mixing",
            codec,
        )
        self.assertNotIn("validate_prediction_mixing_capability", codec)

    def test_capabilities_have_only_standard_library_and_core_absolute_imports(self) -> None:
        unexpected: dict[str, set[str]] = {}
        for path in CAPABILITY_DIRECTORY.glob("*.py"):
            outside = imported_roots(path) - ALLOWED_CAPABILITY_IMPORT_ROOTS
            if outside:
                unexpected[path.name] = outside

        self.assertEqual(unexpected, {})

    def test_capabilities_do_not_import_host_backend_or_execution_runtimes(self) -> None:
        banned: dict[str, set[str]] = {}
        for path in CAPABILITY_DIRECTORY.glob("*.py"):
            matches = imported_roots(path) & BANNED_IMPORT_ROOTS
            if matches:
                banned[path.name] = matches

        self.assertEqual(banned, {})

    def test_importing_capabilities_does_not_load_banned_runtime_modules(self) -> None:
        importlib.import_module("conditioning_layers.capabilities")
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


if __name__ == "__main__":
    unittest.main()
