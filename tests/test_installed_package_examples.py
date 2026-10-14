"""Consumer examples work independently of repository imports."""

import ast
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from examples.installed_package import crawl_page, workspace_setup


@pytest.mark.parametrize("name", ["crawl_page.py", "workspace_setup.py"])
def test_standalone_files_import_only_standard_library_and_public_api(name):
    tree = ast.parse((ROOT / "examples/installed_package" / name).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name in sys.stdlib_module_names for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert not node.level
            assert node.module in sys.stdlib_module_names | {"pulsecrawl"}
            if node.module == "pulsecrawl":
                assert {alias.name for alias in node.names} <= {"crawl", "Workspace"}


@pytest.mark.parametrize("name", ["crawl_page.py", "workspace_setup.py"])
def test_single_copied_file_help_needs_no_examples_tree(name, tmp_path):
    script = tmp_path / name
    shutil.copy2(ROOT / "examples/installed_package" / name, script)
    result = subprocess.run(
        [sys.executable, "-I", str(script), "--help"],
        cwd=tmp_path, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
    assert list(tmp_path.iterdir()) == [script]


def test_standalone_workspace_is_offline_and_refuses_existing_data(tmp_path, monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", Mock(side_effect=AssertionError("no HTTP")))
    root = tmp_path / "workspace"
    result = workspace_setup.run(root)
    assert result["valid"] is True
    assert result["datasetId"]
    with pytest.raises(ValueError, match="never overwritten"):
        workspace_setup.run(root)
    file = tmp_path / "not-a-directory"
    file.write_text("keep me")
    with pytest.raises(ValueError, match="never overwritten"):
        workspace_setup.run(file)
    assert file.read_text() == "keep me"


def test_live_example_defaults_to_help_without_calling_crawler(monkeypatch, capsys):
    forbidden = Mock(side_effect=AssertionError("no live opt-in"))
    monkeypatch.setattr(crawl_page, "crawl", forbidden)
    crawl_page.main([])
    assert "--live" in capsys.readouterr().out
    forbidden.assert_not_called()


@pytest.mark.parametrize("arguments", [
    ["--live"], ["--url", "https://example.com/"],
    ["--live", "--url", "https://example.com/"],
    ["--user-agent", "Crawler (+https://operator.example/contact)"],
])
def test_live_example_requires_explicit_complete_arguments(arguments, monkeypatch):
    monkeypatch.setattr(crawl_page, "crawl", Mock(side_effect=AssertionError("no HTTP")))
    with pytest.raises(SystemExit) as error:
        crawl_page.main(arguments)
    assert error.value.code == 2


@pytest.mark.parametrize("agent", [None, "", "AnonymousCrawler", "x\nhttps://example.com"])
def test_live_example_requires_contact_and_rejects_header_injection(agent, monkeypatch):
    monkeypatch.setattr(crawl_page, "crawl", Mock(side_effect=AssertionError("no HTTP")))
    with pytest.raises(ValueError, match="working"):
        crawl_page.run("https://example.com/", agent)


def test_live_example_keeps_network_safeguards_and_one_page_limit(monkeypatch):
    fake = Mock(return_value=SimpleNamespace(records=[], stats={}))
    monkeypatch.setattr(crawl_page, "crawl", fake)
    crawl_page.run("https://example.com/", "Crawler (+https://operator.example/contact)")
    options = fake.call_args.kwargs
    assert options["seeds"] == ["https://example.com/"]
    assert options["scope"] == {"maxUrlsPerExecution": 1, "maxDepth": 0}
    assert options["politeness"]["respectRobotsTxt"] is True
    assert options["politeness"]["requestsPerSecond"] == 1.0
    assert options["store_raw_pages"] is False
    assert "allow_private_networks" not in options


@pytest.mark.parametrize("document", ["README.md", "PYPI_README.md"])
def test_first_readme_python_example_runs_offline_without_a_checkout(document, tmp_path, monkeypatch):
    snippet = re.search(r"```python\n(.*?)\n```", (ROOT / document).read_text(), re.S)[1]
    assert "from pulsecrawl import Workspace" in snippet
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(socket.socket, "connect", Mock(side_effect=AssertionError("no HTTP")))
    exec(compile(snippet, document, "exec"), {"__name__": "__main__"})
    assert (tmp_path / "my-crawls/state/pulsecrawl.sqlite").is_file()
