class PulseCrawlError(Exception):
    """API error with the canonical code from contracts/errors/v1."""

    def __init__(
        self,
        code: str,
        message: str,
        http_status: int,
        *,
        request_id: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.http_status = http_status
        self.request_id = request_id
        self.retryable = retryable


class ExecutionTimeout(Exception):
    """wait() gave up before the execution reached a terminal state."""


class WorkspaceError(RuntimeError):
    """Base class for local workspace failures with actionable categories."""


class WorkspaceReadOnlyError(WorkspaceError):
    """The workspace cannot be modified with the current permissions."""


class InsufficientStorageError(WorkspaceError):
    """The filesystem cannot accept the requested durable write."""


class DatasetCorruptionError(WorkspaceError):
    """A dataset manifest or referenced file is inconsistent or unreadable."""


class WorkspaceBusyError(WorkspaceError):
    """An incompatible execution or maintenance operation owns the workspace."""


class QueryTimeoutError(WorkspaceError):
    """A local dataset query exceeded its configured deadline."""
