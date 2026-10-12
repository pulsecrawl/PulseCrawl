"""Composition root for a local workspace: all concrete dependencies live here."""

from pathlib import Path

from pulsecrawl.adapters.outbound.filesystem.workspace import (
    _load_workspace_config,
    JsonDefinitionSnapshots,
)
from pulsecrawl.adapters.outbound.filesystem.catalogs import JsonCatalogRepository
from pulsecrawl.adapters.outbound.sqlite.state import SQLiteState
from pulsecrawl.adapters.outbound.sqlite.clock import utc_now
from pulsecrawl.adapters.outbound.sqlite.definitions import SQLiteDefinitionRepository
from pulsecrawl.adapters.outbound.sqlite.executions import SQLiteExecutionRepository
from pulsecrawl.adapters.outbound.sqlite.leases import SQLiteExecutionLease
from pulsecrawl.adapters.outbound.sqlite.health import WorkspaceHealth
from pulsecrawl.adapters.inbound.python.tasks import ExecutionTaskRegistry
from pulsecrawl.adapters.inbound.python.resources import (
    WorkspaceJobs,
    WorkspaceExecutions,
)
from pulsecrawl.adapters.inbound.python.intent import IntentMapper
from pulsecrawl.application.workspace.catalogs import (
    FieldService,
    SchemaService,
    TemplateService,
)
from pulsecrawl.application.workspace.validation import WorkspaceValidationService
from pulsecrawl.application.datasets.service import DatasetService
from pulsecrawl.domain.workspace.definitions import _identifier
from pulsecrawl.bootstrap.datasets import LocalDatasetReader
from pulsecrawl.bootstrap.crawling import LocalExecutionRuntimeFactory


def configure_workspace(workspace, path):
    workspace.path = Path(path).expanduser().resolve()
    config_path = workspace.path / "pulsecrawl.json"
    if not config_path.exists():
        raise FileNotFoundError(
            f"{workspace.path} is not a PulseCrawl workspace; call Workspace.init(path)"
        )
    workspace.config = _load_workspace_config(config_path)
    workspace.state = state = SQLiteState(
        workspace.path / "state" / "pulsecrawl.sqlite"
    )
    try:
        _configure_services(workspace, state)
    except BaseException:
        state.close()
        raise


def _configure_services(workspace, state):
    snapshots = JsonDefinitionSnapshots(workspace.path)
    readers = lambda definition: LocalDatasetReader(state, workspace.path, definition)
    catalog = lambda kind, key: JsonCatalogRepository(workspace.path, kind, key)
    common = {"now": utc_now, "id_factory": _identifier}
    workspace.fields = FieldService(catalog("fields", "fieldId"), **common)
    workspace.schemas = SchemaService(
        catalog("schemas", "schemaId"), fields=workspace.fields, **common
    )
    workspace.templates = TemplateService(
        catalog("templates", "templateId"), schemas=workspace.schemas, **common
    )
    workspace.datasets = DatasetService(
        repository=SQLiteDefinitionRepository(state, "datasets"),
        fields=workspace.fields,
        schemas=workspace.schemas,
        readers=readers,
        snapshots=snapshots,
        prune=lambda *args, **kwargs: workspace.maintenance.prune_dataset(
            *args, **kwargs
        ),
        **common,
    )
    job_repository = SQLiteDefinitionRepository(state, "jobs")
    execution_repository = SQLiteExecutionRepository(state, job_repository, utc_now)
    workspace.executions = WorkspaceExecutions(
        repository=execution_repository,
        leases=SQLiteExecutionLease(state),
        runtime=LocalExecutionRuntimeFactory(
            state=state,
            root=workspace.path,
            datasets=workspace.datasets,
            org_id=str(workspace.config.get("orgId", "local")),
        ),
        datasets=workspace.datasets,
        readers=readers,
        snapshots=snapshots,
        tasks=ExecutionTaskRegistry(),
        **common,
    )
    workspace.jobs = WorkspaceJobs(
        repository=job_repository,
        datasets=workspace.datasets,
        templates=workspace.templates,
        executions=workspace.executions,
        snapshots=snapshots,
        **common,
    )
    from pulsecrawl.bootstrap.authoring import WorkspaceTemplateAuthoring
    from pulsecrawl.adapters.inbound.python.schedules import WorkspaceSchedules
    from pulsecrawl.application.scheduling.service import ScheduleService
    from pulsecrawl.adapters.outbound.cron.calculator import CronScheduleCalculator
    from pulsecrawl.adapters.outbound.sqlite.schedules import SQLiteScheduleRepository
    from pulsecrawl.adapters.outbound.sqlite.scheduler_lease import SQLiteSchedulerLease
    from pulsecrawl.adapters.outbound.sqlite.clock import EpochClock
    from pulsecrawl.adapters.inbound.scheduler.process import serve
    from pulsecrawl.bootstrap.maintenance import WorkspaceMaintenance

    workspace.authoring = WorkspaceTemplateAuthoring(workspace)
    schedule_service = ScheduleService(
        repository=SQLiteScheduleRepository(state),
        jobs=workspace.jobs,
        executions=workspace.executions,
        snapshots=snapshots,
        calculator=CronScheduleCalculator(),
        clock=EpochClock(),
    )
    workspace.schedules = WorkspaceSchedules(
        schedule_service,
        lambda service, **kwargs: serve(service, SQLiteSchedulerLease(state), **kwargs),
    )
    workspace.maintenance = WorkspaceMaintenance(workspace)
    workspace._validation = WorkspaceValidationService(
        authoring=workspace.authoring,
        datasets=workspace.datasets,
        jobs=workspace.jobs,
        executions=workspace.executions,
        readers=readers,
        snapshots=snapshots,
        org_id=str(workspace.config.get("orgId", "local")),
        map_intent=IntentMapper.from_message_intent,
    )
    workspace._health = WorkspaceHealth(workspace)
