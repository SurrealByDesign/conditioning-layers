from __future__ import annotations

import ast
from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).parents[4]
SOURCE_ROOT = REPOSITORY_ROOT / "src" / "conditioning_layers"
EXECUTION_ROOT = SOURCE_ROOT / "execution"


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


class ExecutionArchitectureTests(unittest.TestCase):
    def test_inward_packages_do_not_import_execution(self) -> None:
        for package in ("domain", "persistence", "capabilities", "adapters", "assets", "comfyui", "runtime"):
            for path in (SOURCE_ROOT / package).rglob("*.py"):
                with self.subTest(path=path):
                    self.assertFalse(
                        any(name.startswith("conditioning_layers.execution") for name in imports(path))
                    )

    def test_execution_has_no_prohibited_runtime_or_frontend_imports(self) -> None:
        prohibited = ("comfy", "server", "torch", "PIL", "numpy", "frontend", "ui")
        for path in EXECUTION_ROOT.rglob("*.py"):
            for name in imports(path):
                with self.subTest(path=path, imported=name):
                    self.assertFalse(any(name == item or name.startswith(item + ".") for item in prohibited))

    def test_execution_uses_standard_library_http_only(self) -> None:
        protocol = (EXECUTION_ROOT / "comfyui" / "protocol.py").read_text(encoding="utf-8")
        self.assertIn("urllib.request", protocol)
        self.assertNotIn("requests", protocol)
        self.assertNotIn("httpx", protocol)

    def test_slice_adds_no_dependency_manifest(self) -> None:
        manifests = {
            "requirements.txt",
            "requirements-dev.txt",
            "pyproject.toml",
            "setup.py",
            "setup.cfg",
            "Pipfile",
            "poetry.lock",
        }
        self.assertFalse({path.name for path in EXECUTION_ROOT.rglob("*")} & manifests)


if __name__ == "__main__":
    unittest.main()
