"""The public guides and example tree stay focused on local execution."""

import ast
from pathlib import Path
import re
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_REFERENCES = re.compile(
    r"\bhosted\b|\bcloud\b|\bcontrol[- ]plane\b|Firebase|"
    r"PULSECRAWL_API_KEY|PULSECRAWL_BASE_URL",
    re.IGNORECASE,
)
DOCUMENTS = [
    *ROOT.glob("*.md"),
    *ROOT.glob("docs/**/*.md"),
    *ROOT.glob("examples/**/*.md"),
]


@pytest.mark.parametrize("document", DOCUMENTS, ids=lambda path: str(path.relative_to(ROOT)))
def test_public_documentation_is_local_only(document):
    assert not PRODUCT_REFERENCES.search(document.read_text()), document.relative_to(ROOT)


def test_package_summary_describes_local_use_without_changing_optional_extras():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert "local" in project["description"].lower()
    assert not PRODUCT_REFERENCES.search(project["description"])
    # Presentation changes must not remove compatibility dependency groups.
    assert set(project["optional-dependencies"]) == {"sql", "workspace", "cloud", "dev"}


def test_example_tree_has_no_remote_client_entry_points_or_imports():
    for path in (ROOT / "examples").rglob("*.py"):
        assert "hosted" not in path.name.lower()
        source = path.read_text()
        assert not PRODUCT_REFERENCES.search(source), path.relative_to(ROOT)
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom):
                assert all(
                    alias.name not in {"PulseCrawl", "CloudProfiles", "CloudWorkspaceSync"}
                    for alias in node.names
                ), path.relative_to(ROOT)
            elif isinstance(node, ast.Import):
                assert not any(
                    alias.name in {"pulsecrawl.client", "pulsecrawl.cloud"}
                    for alias in node.names
                ), path.relative_to(ROOT)
