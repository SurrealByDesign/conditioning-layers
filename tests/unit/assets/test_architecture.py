from __future__ import annotations

import ast
import importlib
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = ROOT / "src" / "conditioning_layers"
ASSET_DIRECTORY = PACKAGE_ROOT / "assets"
INWARD_DIRECTORIES = tuple(
    PACKAGE_ROOT / name for name in ("domain", "persistence", "capabilities")
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
ALLOWED_ASSET_IMPORT_ROOTS = {
    "base64",  # ADR-0031 section 11: bounded inline Painted Field codec only.
    "__future__",
    "collections",
    "conditioning_layers",
    "dataclasses",
    "enum",
    "hashlib",
    "json",
    "pathlib",
    "re",
    "struct",
    "zlib",
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


class AssetArchitectureTests(unittest.TestCase):
    def test_domain_persistence_and_capabilities_do_not_import_assets(self) -> None:
        offenders: list[str] = []
        for directory in INWARD_DIRECTORIES:
            for path in directory.glob("*.py"):
                text = path.read_text(encoding="utf-8")
                if "conditioning_layers.assets" in text or "..assets" in text:
                    offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_assets_use_only_standard_library_and_declared_inward_imports(self) -> None:
        unexpected: dict[str, set[str]] = {}
        for path in ASSET_DIRECTORY.glob("*.py"):
            outside = imported_roots(path) - ALLOWED_ASSET_IMPORT_ROOTS
            if outside:
                unexpected[path.name] = outside
        self.assertEqual(unexpected, {})

    def test_assets_do_not_import_host_image_or_execution_runtimes(self) -> None:
        banned: dict[str, set[str]] = {}
        for path in ASSET_DIRECTORY.glob("*.py"):
            matches = imported_roots(path) & BANNED_IMPORT_ROOTS
            if matches:
                banned[path.name] = matches
        self.assertEqual(banned, {})

    def test_importing_assets_does_not_load_banned_runtime_modules(self) -> None:
        importlib.import_module("conditioning_layers.assets")
        loaded_roots = {name.split(".", 1)[0] for name in sys.modules}
        self.assertEqual(loaded_roots & BANNED_IMPORT_ROOTS, set())

    def test_no_dependency_manifest_was_added(self) -> None:
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
            {name for name in manifests if (ROOT / name).exists()}, set()
        )

    def test_library_binding_is_consumed_only_by_isolated_translation_v2(self) -> None:
        consumer_directories = tuple(
            PACKAGE_ROOT / name
            for name in (
                "adapters",
                "capabilities",
                "comfyui",
                "execution",
                "integrations",
                "persistence",
                "runtime",
            )
        )
        tokens = (
            "InfluenceFieldBinding",
            "bind_influence_field_library",
            "influence-field-binding.v1",
            "library_binding",
        )
        offenders: list[str] = []
        allowed_v2_root = (
            PACKAGE_ROOT / "adapters" / "prediction_mixing" / "v2"
        )
        for directory in consumer_directories:
            for path in directory.rglob("*.py"):
                if path.is_relative_to(allowed_v2_root):
                    continue
                text = path.read_text(encoding="utf-8")
                if any(token in text for token in tokens):
                    offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

        v2_consumers = [
            path
            for path in allowed_v2_root.rglob("*.py")
            if any(token in path.read_text(encoding="utf-8") for token in tokens)
        ]
        self.assertEqual(
            [path.name for path in v2_consumers],
            ["translate.py"],
        )


if __name__ == "__main__":
    unittest.main()
