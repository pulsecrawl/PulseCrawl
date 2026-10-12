"""Synchronous schedule facade; the service and process driver are separate."""


class WorkspaceSchedules:
    def __init__(self, service, serve):
        self._service, self._serve = service, serve

    def set(self, *args, **kwargs):
        return self._service.set(*args, **kwargs)

    def list(self):
        return self._service.list()

    def pause(self, job_id):
        return self._service.set_status(job_id, "paused")

    def resume(self, job_id):
        return self._service.set_status(job_id, "active")

    def run_due(self, **kwargs):
        return self._service.run_due(**kwargs)

    def status(self):
        return self._service.status()

    def serve(self, **kwargs):
        return self._serve(self._service, **kwargs)
