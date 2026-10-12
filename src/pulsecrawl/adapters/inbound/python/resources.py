"""Synchronous public entry points wrap asynchronous application use cases."""

import asyncio
from pulsecrawl.application.workspace.jobs import JobService
from pulsecrawl.application.executions.service import ExecutionService


class WorkspaceJobs(JobService):
    def run(self, *args, **kwargs):
        return asyncio.run(super().run(*args, **kwargs))


class WorkspaceExecutions(ExecutionService):
    def resume(self, *args, **kwargs):
        return asyncio.run(super().resume(*args, **kwargs))
