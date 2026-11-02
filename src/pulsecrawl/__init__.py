"""PulseCrawl public API. Heavy/optional adapters load only when requested."""

from importlib import import_module

_EXPORTS = {
    "API_KEY_ENV": "pulsecrawl.client",
    "BASE_URL_ENV": "pulsecrawl.client",
    "DEFAULT_BASE_URL": "pulsecrawl.client",
    "PulseCrawl": "pulsecrawl.client",
    "DatasetCorruptionError": "pulsecrawl.errors",
    "ExecutionTimeout": "pulsecrawl.errors",
    "InsufficientStorageError": "pulsecrawl.errors",
    "PulseCrawlError": "pulsecrawl.errors",
    "QueryTimeoutError": "pulsecrawl.errors",
    "WorkspaceBusyError": "pulsecrawl.errors",
    "WorkspaceError": "pulsecrawl.errors",
    "WorkspaceReadOnlyError": "pulsecrawl.errors",
    "LocalResult": "pulsecrawl.local",
    "crawl": "pulsecrawl.local",
    "Workspace": "pulsecrawl.workspace_runtime",
    "CloudProfile": "pulsecrawl.cloud",
    "CloudProfiles": "pulsecrawl.cloud",
    "CloudWorkspaceSync": "pulsecrawl.cloud",
    "export_workspace_bundle": "pulsecrawl.cloud",
    "PageInspection": "pulsecrawl.template_authoring",
    "RepresentativePage": "pulsecrawl.template_authoring",
    "TemplateDraft": "pulsecrawl.template_authoring",
    "inspect_page": "pulsecrawl.template_authoring",
    "validate_template_stack": "pulsecrawl.template_authoring",
}


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(_EXPORTS[name]), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(_EXPORTS))


__all__ = [
    "PulseCrawl",
    "crawl",
    "LocalResult",
    "Workspace",
    "CloudProfile",
    "CloudProfiles",
    "CloudWorkspaceSync",
    "export_workspace_bundle",
    "PulseCrawlError",
    "ExecutionTimeout",
    "WorkspaceError",
    "WorkspaceReadOnlyError",
    "WorkspaceBusyError",
    "InsufficientStorageError",
    "DatasetCorruptionError",
    "QueryTimeoutError",
    "DEFAULT_BASE_URL",
    "BASE_URL_ENV",
    "API_KEY_ENV",
    "PageInspection",
    "RepresentativePage",
    "TemplateDraft",
    "inspect_page",
    "validate_template_stack",
]

__version__ = "0.3.0"
