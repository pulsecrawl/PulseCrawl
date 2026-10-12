"""Local maintenance adapter composition and restore validation."""

from pulsecrawl.application.workspace.maintenance import MaintenanceService
from pulsecrawl.adapters.outbound.sqlite.maintenance_lease import SQLiteMaintenanceLease
from pulsecrawl.adapters.outbound.filesystem.backups import LocalBackupAdapter
from pulsecrawl.adapters.outbound.filesystem.retention import LocalRetentionAdapter
from pulsecrawl.adapters.outbound.filesystem.doctor import LocalDoctorAdapter
from pulsecrawl.bootstrap.datasets import LocalDatasetReader


class WorkspaceMaintenance(MaintenanceService):
    def __init__(self, workspace):
        lease = SQLiteMaintenanceLease(workspace.state)
        common = dict(
            root=workspace.path,
            state=workspace.state,
            datasets=workspace.datasets,
            readers=lambda definition: LocalDatasetReader(
                workspace.state, workspace.path, definition
            ),
            validate=workspace.validate,
            lock=lease.hold,
        )
        super().__init__(
            lease=lease,
            backups=LocalBackupAdapter(
                root=workspace.path,
                state=workspace.state,
                config=workspace.config,
                lock=lease.hold,
            ),
            retention=LocalRetentionAdapter(**common),
            diagnostics=LocalDoctorAdapter(**common),
        )

    verify_backup = staticmethod(LocalBackupAdapter.verify_backup)

    @staticmethod
    def restore(source, destination):
        def validate_restored(path):
            from pulsecrawl.adapters.inbound.python.workspace import Workspace

            with Workspace(path) as workspace:
                return workspace.validate(), workspace.state.integrity_check()

        return LocalBackupAdapter.restore(source, destination, validate_restored)
