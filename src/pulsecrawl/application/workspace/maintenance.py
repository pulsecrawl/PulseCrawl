"""Maintenance entry points use explicit native-operation gateways."""


class MaintenanceService:
    def __init__(self, *, lease, backups, retention, diagnostics):
        self._lease, self._backups = lease, backups
        self._retention, self._diagnostics = retention, diagnostics

    def lock(self, **kwargs):
        return self._lease.hold(**kwargs)

    def backup(self, *args, **kwargs):
        return self._backups.backup(*args, **kwargs)

    def prune_dataset(self, *args, **kwargs):
        return self._retention.prune_dataset(*args, **kwargs)

    def doctor(self, **kwargs):
        return self._diagnostics.doctor(**kwargs)
