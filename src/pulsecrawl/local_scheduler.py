"""Compatibility scheduling API."""

from pulsecrawl.adapters.outbound.cron.calculator import validate_cron, _next, _croniter
from pulsecrawl.domain.scheduling.identity import _execution_id


def set_schedule(workspace, job_id, cron, **kwargs):
    return workspace.schedules.set(job_id, cron, **kwargs)


def list_schedules(workspace):
    return workspace.schedules.list()


def set_status(workspace, job_id, status):
    return workspace.schedules._service.set_status(job_id, status)


def run_due(workspace, **kwargs):
    return workspace.schedules.run_due(**kwargs)


def recover_incomplete(workspace, **kwargs):
    return workspace.schedules._service.recover_incomplete(**kwargs)


def serve(workspace, **kwargs):
    return workspace.schedules.serve(**kwargs)
