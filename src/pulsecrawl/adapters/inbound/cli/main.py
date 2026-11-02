"""Command-line interface for a self-contained local workspace."""

from __future__ import annotations

import getpass
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any

from pulsecrawl.domain.errors import (
    DatasetCorruptionError,
    InsufficientStorageError,
    QueryTimeoutError,
    WorkspaceBusyError,
    WorkspaceError,
    WorkspaceReadOnlyError,
    PulseCrawlError,
)
from pulsecrawl.adapters.outbound.http.client import API_KEY_ENV
from pulsecrawl.bootstrap.cloud import (
    CloudProfiles,
    CloudWorkspaceSync,
    export_workspace_bundle,
)
from pulsecrawl.adapters.inbound.python.workspace import Workspace
from pulsecrawl.bootstrap.maintenance import WorkspaceMaintenance
from pulsecrawl.adapters.inbound.cli.parser import build_parser, _UsageError


def _print(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def _workspace(path: str) -> Workspace:
    return Workspace(Path(path))


def _json_argument(value: str, *, expected: type) -> Any:
    """Parse compact JSON or ``@path`` without accepting unbounded input."""
    if value.startswith("@"):
        path = Path(value[1:])
        if path.stat().st_size > 1024 * 1024:
            raise ValueError("JSON definition files must not exceed 1 MiB")
        encoded = path.read_text(encoding="utf-8")
    else:
        encoded = value
    if len(encoded.encode("utf-8")) > 1024 * 1024:
        raise ValueError("JSON definitions must not exceed 1 MiB")
    result = json.loads(encoded)
    if not isinstance(result, expected):
        raise ValueError(f"JSON definition must be a {expected.__name__}")
    return result


def _main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "cloud":
        profiles = CloudProfiles()
        if args.cloud_command == "profiles":
            _print([profile.__dict__ for profile in profiles.list()])
            return 0
        if args.cloud_command == "connect":
            environment_api_key = os.environ.get(API_KEY_ENV)
            api_key = environment_api_key
            if not api_key:
                api_key = getpass.getpass("PulseCrawl API key: ")
            profile = profiles.connect(
                args.profile,
                base_url=args.base_url,
                api_key=api_key,
                store_secret=environment_api_key is None,
            )
            _print(profile.__dict__)
            return 0
        if args.cloud_command == "disconnect":
            profiles.disconnect(args.profile)
            _print({"profile": args.profile, "connected": False})
            return 0
        if args.cloud_command == "whoami":
            with profiles.client(args.profile) as client:
                _print(client.whoami())
            return 0
        if args.cloud_command == "pull":
            with profiles.client(args.profile) as client:
                paths = client.datasets.download_files(
                    args.dataset_id,
                    args.destination,
                    overwrite=args.overwrite,
                )
            _print(
                {"datasetId": args.dataset_id, "files": [str(path) for path in paths]}
            )
            return 0
        with _workspace(args.workspace) as workspace:
            bundle = export_workspace_bundle(workspace)
            if args.cloud_command == "bundle":
                _print(bundle)
                return 0
            with profiles.client(args.profile) as client:
                sync = CloudWorkspaceSync(client)
                if args.cloud_command == "plan":
                    _print(sync.plan(bundle))
                else:
                    if args.cloud_command == "run":
                        sync.require_scopes({"executions:run"})
                    mapping = sync.apply(bundle)
                    if args.cloud_command == "run":
                        cloud_job_id = mapping["jobIds"].get(args.job_id)
                        if not cloud_job_id:
                            raise KeyError(f"unknown local job: {args.job_id}")
                        mapping["execution"] = client.jobs.run(cloud_job_id)
                    _print(mapping)
            return 0
    if args.command == "init":
        workspace = Workspace.init(args.path, name=args.name)
        try:
            _print({"workspace": str(workspace.path), **workspace.validate()})
        finally:
            workspace.close()
        return 0
    if args.command == "backup" and args.backup_command == "verify":
        _print(WorkspaceMaintenance.verify_backup(args.source))
        return 0
    if args.command == "backup" and args.backup_command == "restore":
        _print(WorkspaceMaintenance.restore(args.source, args.destination))
        return 0

    with _workspace(args.workspace) as workspace:
        if args.command == "validate":
            result = workspace.validate()
            _print(result)
            return 0 if result["valid"] else 1
        if args.command == "doctor":
            result = workspace.maintenance.doctor(repair_safe=args.repair_safe)
            _print(result)
            return 0 if result["valid"] else 1
        if args.command == "health":
            result = workspace.health(readiness=args.readiness)
            _print(result)
            return 0 if result["healthy"] else 1
        if args.command == "backup":
            _print(
                workspace.maintenance.backup(
                    args.destination,
                    include_raw_pages=not args.exclude_raw_pages,
                )
            )
            return 0
        if args.command == "field":
            if args.field_command == "list":
                _print(workspace.fields.list())
            elif args.field_command == "show":
                _print(workspace.fields.get(args.field_id))
            else:
                _print(
                    workspace.fields.create(
                        args.name,
                        args.type,
                        field_id=args.id,
                        description=args.description,
                    )
                )
            return 0
        if args.command == "schema":
            if args.schema_command == "list":
                _print(workspace.schemas.list())
            elif args.schema_command == "show":
                _print(workspace.schemas.get(args.schema_id))
            else:
                _print(
                    workspace.schemas.create(
                        args.name, args.field_ids, schema_id=args.id
                    )
                )
            return 0
        if args.command == "template":
            if args.template_command == "list":
                _print(workspace.templates.list())
            elif args.template_command == "show":
                _print(workspace.templates.get(args.template_id))
            else:
                _print(
                    workspace.templates.create(
                        args.name,
                        output_schema_id=args.schema_id,
                        engine=args.engine,
                        mappings=_json_argument(args.mappings, expected=dict),
                        template_id=args.id,
                    )
                )
            return 0
        if args.command == "job":
            if args.job_command == "list":
                _print(workspace.jobs.list())
            elif args.job_command == "show":
                _print(workspace.jobs.get(args.job_id))
            elif args.job_command == "create":
                _print(
                    workspace.jobs.create(
                        args.name,
                        seeds=args.seed,
                        dataset_id=args.dataset_id,
                        templates=_json_argument(args.templates, expected=list),
                        system_templates=(
                            _json_argument(args.system_templates, expected=list)
                            if args.system_templates
                            else ()
                        ),
                        scope=(
                            _json_argument(args.scope, expected=dict)
                            if args.scope
                            else None
                        ),
                        politeness=(
                            _json_argument(args.politeness, expected=dict)
                            if args.politeness
                            else None
                        ),
                        store_raw_pages=args.store_raw_pages,
                    )
                )
            else:
                _print(workspace.jobs.run(args.job_id))
            return 0
        if args.command == "execution":
            if args.execution_command == "list":
                _print(workspace.executions.list(args.job_id))
            elif args.execution_command == "show":
                _print(workspace.executions.get(args.execution_id))
            elif args.execution_command == "cancel":
                _print(workspace.executions.cancel(args.execution_id, force=args.force))
            elif args.execution_command == "urls":
                _print(
                    workspace.executions.urls(
                        args.execution_id,
                        cursor=args.cursor,
                        limit=args.limit,
                        newness=args.newness,
                        host=args.host,
                        url_contains=args.contains,
                    )
                )
            else:
                _print(workspace.executions.resume(args.execution_id))
            return 0
        if args.command == "dataset":
            if args.dataset_command == "list":
                _print(workspace.datasets.list())
            elif args.dataset_command == "show":
                _print(workspace.datasets.get(args.dataset_id))
            elif args.dataset_command == "create":
                _print(
                    workspace.datasets.create(
                        args.name,
                        fields=(
                            _json_argument(args.fields, expected=list)
                            if args.fields
                            else None
                        ),
                        schema_id=args.schema_id,
                        mode=args.mode,
                        identity_field=args.identity_field,
                    )
                )
            elif args.dataset_command == "files":
                _print(workspace.datasets.files(args.dataset_id, version=args.version))
            elif args.dataset_command == "query":
                _print(
                    workspace.datasets.query(
                        args.dataset_id,
                        args.sql,
                        version=args.version,
                        row_cap=args.row_cap,
                        timeout_s=args.timeout,
                    )
                )
            elif args.dataset_command == "urls":
                _print(
                    workspace.datasets.urls(
                        args.dataset_id,
                        cursor=args.cursor,
                        limit=args.limit,
                        newness=args.newness,
                        host=args.host,
                        url_contains=args.contains,
                    )
                )
            elif args.dataset_command == "compact":
                _print(
                    {
                        "partitionsCompacted": workspace.datasets.compact(
                            args.dataset_id, minimum_files=args.minimum_files
                        )
                    }
                )
            else:
                _print(
                    workspace.datasets.prune(
                        args.dataset_id,
                        keep_versions=args.keep_versions,
                        older_than_days=args.older_than_days,
                        dry_run=not args.apply,
                    )
                )
            return 0
        if args.command == "schedule":
            if args.schedule_command == "list":
                _print(workspace.schedules.list())
            elif args.schedule_command == "status":
                _print(workspace.schedules.status())
            elif args.schedule_command == "set":
                _print(
                    workspace.schedules.set(
                        args.job_id,
                        args.cron,
                        timezone_name=args.timezone,
                        max_duration_seconds=args.max_duration_seconds,
                    )
                )
            elif args.schedule_command == "pause":
                _print(workspace.schedules.pause(args.job_id))
            elif args.schedule_command == "resume":
                _print(workspace.schedules.resume(args.job_id))
            elif args.schedule_command == "run-due":
                _print(workspace.schedules.run_due())
            else:
                workspace.schedules.serve(poll_seconds=args.poll_seconds)
            return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    """Run the CLI with a stable, machine-readable failure envelope."""
    error: Exception
    try:
        return _main(argv)
    except _UsageError as exc:
        error = exc
        code, exit_code = "usage", 2
    except (KeyError, FileNotFoundError) as exc:
        error = exc
        code, exit_code = "not_found", 3
    except (ValueError, TypeError) as exc:
        error = exc
        code, exit_code = "invalid_input", 4
    except QueryTimeoutError as exc:
        error = exc
        code, exit_code = "timeout", 6
    except (
        DatasetCorruptionError,
        InsufficientStorageError,
        WorkspaceBusyError,
        WorkspaceError,
        WorkspaceReadOnlyError,
        sqlite3.DatabaseError,
    ) as exc:
        error = exc
        code, exit_code = "workspace_error", 5
    except ImportError as exc:
        error = exc
        code, exit_code = "missing_dependency", 7
    except PulseCrawlError as exc:
        error = exc
        code, exit_code = "cloud_error", 8
    except Exception as exc:  # pragma: no cover - last-resort process boundary
        error = exc
        code, exit_code = "internal_error", 1
    print(
        json.dumps(
            {
                "error": {
                    "code": code,
                    "type": type(error).__name__,
                    "message": str(error).strip("'"),
                }
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
