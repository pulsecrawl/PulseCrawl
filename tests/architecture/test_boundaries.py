"""Architecture rules are executable, not just a directory naming convention."""

import ast
import importlib
import importlib.util
from pathlib import Path
import subprocess
import sys

import pulsecrawl
import pytest

SOURCE = Path(pulsecrawl.__file__).parent


def imports(path):
    module = "pulsecrawl." + path.relative_to(SOURCE).with_suffix(
        ""
    ).as_posix().replace("/", ".")
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            yield from (entry.name for entry in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                yield importlib.util.resolve_name(
                    "." * node.level + (node.module or ""), module.rsplit(".", 1)[0]
                )
            elif node.module:
                yield node.module


@pytest.mark.parametrize("layer", ["domain", "application"])
def test_inner_layers_have_no_infrastructure_dependencies(layer):
    allowed = (
        ("pulsecrawl.domain",)
        if layer == "domain"
        else ("pulsecrawl.domain", "pulsecrawl.application")
    )
    errors = []
    for path in (SOURCE / layer).rglob("*.py"):
        for target in imports(path):
            root = target.split(".")[0]
            if root == "pulsecrawl":
                if not any(
                    target == prefix or target.startswith(prefix + ".")
                    for prefix in allowed
                ):
                    errors.append(f"{path.relative_to(SOURCE)} imports {target}")
            elif root not in sys.stdlib_module_names and root != "__future__":
                errors.append(
                    f"{path.relative_to(SOURCE)} imports external dependency {target}"
                )
    assert not errors, "\n".join(errors)


def test_application_has_no_sql_or_file_operations():
    errors = []
    for path in (SOURCE / "application").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call):
                name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else getattr(node.func, "attr", "")
                )
                if name in {
                    "open",
                    "read_text",
                    "write_text",
                    "mkdir",
                    "unlink",
                    "execute_sql",
                    "executescript",
                    "fetchone",
                    "fetchall",
                    "transaction",
                }:
                    errors.append(f"{path.relative_to(SOURCE)}:{node.lineno}: {name}")
                # Runtime factories expose open(); this is a port, not a file.
                if name == "open" and isinstance(node.func, ast.Attribute):
                    if ast.unparse(node.func.value) == "self._runtime":
                        errors.pop()
    assert not errors, "\n".join(errors)


def test_outbound_adapters_do_not_import_inbound_or_bootstrap():
    errors = []
    for path in (SOURCE / "adapters" / "outbound").rglob("*.py"):
        for target in imports(path):
            if target.startswith(
                (
                    "pulsecrawl.bootstrap",
                    "pulsecrawl.adapters.inbound",
                    "pulsecrawl.core",
                )
            ):
                errors.append(f"{path.relative_to(SOURCE)} imports {target}")
    assert not errors, "\n".join(errors)


def test_domain_and_application_import_without_adapters_or_optional_dependencies():
    code = r"""
import importlib.abc, sys
class BlockInfrastructure(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        blocked = ("pulsecrawl.adapters", "pulsecrawl.bootstrap", "pulsecrawl.core",
                   "aiohttp", "httpx", "selectolax", "sqlite3", "duckdb", "pyarrow", "keyring", "croniter")
        if any(fullname == prefix or fullname.startswith(prefix + ".") for prefix in blocked):
            raise AssertionError("infrastructure imported: " + fullname)
sys.meta_path.insert(0, BlockInfrastructure())
from pulsecrawl.domain.crawling.model import ExecutionIntent
from pulsecrawl.domain.templates.authoring import TemplateDraft
from pulsecrawl.application.crawling.engine import CrawlEngine
from pulsecrawl.application.executions.service import ExecutionService
from pulsecrawl.application.scheduling.service import ScheduleService
from pulsecrawl.application.synchronization.service import WorkspaceSyncService
assert not hasattr(ExecutionIntent, "from_message_intent")
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr


def test_public_exports_and_legacy_type_identity():
    assert set(pulsecrawl.__all__).issubset(dir(pulsecrawl))
    for name in pulsecrawl.__all__:
        assert name == "DEFAULT_BASE_URL" or getattr(pulsecrawl, name) is not None
    with pytest.raises(AttributeError):
        getattr(pulsecrawl, "not_a_public_export")
    for legacy, canonical, name in [
        ("core.model", "domain.crawling.model", "ExecutionIntent"),
        ("core.adapters.memory", "adapters.outbound.memory.crawling", "FakeClock"),
        (
            "core.adapters.aiohttp_fetcher",
            "adapters.outbound.http.fetcher",
            "AiohttpFetcher",
        ),
        ("core.ports", "application.ports.crawling", "Fetcher"),
        (
            "workspace",
            "adapters.outbound.filesystem.legacy_execution",
            "LocalExecutionWriter",
        ),
    ]:
        assert getattr(
            importlib.import_module("pulsecrawl." + legacy), name
        ) is getattr(importlib.import_module("pulsecrawl." + canonical), name)


def test_shared_engine_composition_does_not_load_local_persistence():
    code = r"""
import importlib.abc, sys
class BlockLocalPersistence(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        blocked = ("pulsecrawl.adapters.outbound.sqlite",
                   "pulsecrawl.adapters.outbound.filesystem",
                   "pulsecrawl.adapters.outbound.duckdb",
                   "pulsecrawl.adapters.outbound.parquet",
                   "pulsecrawl.bootstrap.datasets", "sqlite3", "duckdb", "pyarrow")
        if any(fullname == prefix or fullname.startswith(prefix + ".") for prefix in blocked):
            raise AssertionError("local persistence imported: " + fullname)
sys.meta_path.insert(0, BlockLocalPersistence())
from pulsecrawl.bootstrap.crawling import engine_ports, fetch_resources
from pulsecrawl.bootstrap.ephemeral import run_ephemeral
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr
