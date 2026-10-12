"""Command-line interface for a self-contained local workspace."""

from __future__ import annotations

import argparse


class _UsageError(Exception):
    pass


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(prog="pulsecrawl")
    parser.add_argument("--workspace", "-w", default=".")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="create a portable workspace")
    init.add_argument("path", nargs="?", default=".")
    init.add_argument("--name")
    commands.add_parser("validate", help="validate definitions and active manifests")
    doctor = commands.add_parser("doctor", help="check workspace durability and state")
    doctor.add_argument("--repair-safe", action="store_true")
    health = commands.add_parser("health", help="report liveness or readiness")
    health.add_argument("--readiness", action="store_true")

    field = commands.add_parser("field")
    field_commands = field.add_subparsers(dest="field_command", required=True)
    field_commands.add_parser("list")
    field_show = field_commands.add_parser("show")
    field_show.add_argument("field_id")
    field_create = field_commands.add_parser("create")
    field_create.add_argument("name")
    field_create.add_argument(
        "type", choices=("string", "number", "boolean", "datetime", "url")
    )
    field_create.add_argument("--id")
    field_create.add_argument("--description", default="")

    schema = commands.add_parser("schema")
    schema_commands = schema.add_subparsers(dest="schema_command", required=True)
    schema_commands.add_parser("list")
    schema_show = schema_commands.add_parser("show")
    schema_show.add_argument("schema_id")
    schema_create = schema_commands.add_parser("create")
    schema_create.add_argument("name")
    schema_create.add_argument("field_ids", nargs="+")
    schema_create.add_argument("--id")

    template = commands.add_parser("template")
    template_commands = template.add_subparsers(dest="template_command", required=True)
    template_commands.add_parser("list")
    template_show = template_commands.add_parser("show")
    template_show.add_argument("template_id")
    template_create = template_commands.add_parser("create")
    template_create.add_argument("name")
    template_create.add_argument("--schema-id", required=True)
    template_create.add_argument(
        "--engine", choices=("css", "jsonld", "meta"), required=True
    )
    template_create.add_argument(
        "--mappings", required=True, help="JSON object or @file"
    )
    template_create.add_argument("--id")

    job = commands.add_parser("job")
    job_commands = job.add_subparsers(dest="job_command", required=True)
    job_commands.add_parser("list")
    job_show = job_commands.add_parser("show")
    job_show.add_argument("job_id")
    job_create = job_commands.add_parser("create")
    job_create.add_argument("name")
    job_create.add_argument("--dataset-id", required=True)
    job_create.add_argument("--seed", action="append", required=True)
    job_create.add_argument("--templates", required=True, help="JSON array or @file")
    job_create.add_argument("--system-templates", help="JSON array or @file")
    job_create.add_argument("--scope", help="JSON object or @file")
    job_create.add_argument("--politeness", help="JSON object or @file")
    job_create.add_argument("--store-raw-pages", action="store_true")
    job_run = job_commands.add_parser("run")
    job_run.add_argument("job_id")

    execution = commands.add_parser("execution")
    execution_commands = execution.add_subparsers(
        dest="execution_command", required=True
    )
    execution_list = execution_commands.add_parser("list")
    execution_list.add_argument("--job-id")
    execution_show = execution_commands.add_parser("show")
    execution_show.add_argument("execution_id")
    execution_resume = execution_commands.add_parser("resume")
    execution_resume.add_argument("execution_id")
    execution_urls = execution_commands.add_parser("urls")
    execution_urls.add_argument("execution_id")
    execution_urls.add_argument("--cursor")
    execution_urls.add_argument("--limit", type=int, default=50)
    execution_urls.add_argument(
        "--newness", choices=("all", "new", "repeat"), default="all"
    )
    execution_urls.add_argument("--host")
    execution_urls.add_argument("--contains")
    execution_cancel = execution_commands.add_parser("cancel")
    execution_cancel.add_argument("execution_id")
    execution_cancel.add_argument("--force", action="store_true")

    dataset = commands.add_parser("dataset")
    dataset_commands = dataset.add_subparsers(dest="dataset_command", required=True)
    dataset_commands.add_parser("list")
    dataset_show = dataset_commands.add_parser("show")
    dataset_show.add_argument("dataset_id")
    dataset_create = dataset_commands.add_parser("create")
    dataset_create.add_argument("name")
    dataset_create_source = dataset_create.add_mutually_exclusive_group(required=True)
    dataset_create_source.add_argument("--schema-id")
    dataset_create_source.add_argument("--fields", help="JSON array or @file")
    dataset_create.add_argument(
        "--mode", choices=("append_all", "new_urls_only"), default="append_all"
    )
    dataset_create.add_argument("--identity-field", default="_source_url")
    files = dataset_commands.add_parser("files")
    files.add_argument("dataset_id")
    files.add_argument("--version", type=int)
    query = dataset_commands.add_parser("query")
    query.add_argument("dataset_id")
    query.add_argument("sql")
    query.add_argument("--version", type=int)
    query.add_argument("--row-cap", type=int, default=1_000)
    query.add_argument("--timeout", type=float, default=30.0)
    urls = dataset_commands.add_parser("urls")
    urls.add_argument("dataset_id")
    urls.add_argument("--cursor")
    urls.add_argument("--limit", type=int, default=50)
    urls.add_argument("--newness", choices=("all", "new", "repeat"), default="all")
    urls.add_argument("--host")
    urls.add_argument("--contains")
    compact = dataset_commands.add_parser("compact")
    compact.add_argument("dataset_id")
    compact.add_argument("--minimum-files", type=int, default=2)
    prune = dataset_commands.add_parser("prune")
    prune.add_argument("dataset_id")
    prune.add_argument(
        "--keep-versions",
        "--keep-snapshots",
        dest="keep_versions",
        type=int,
        default=30,
        help="number of dataset versions to retain (default: 30)",
    )
    prune.add_argument("--older-than-days", type=int)
    prune.add_argument("--apply", action="store_true")

    schedule = commands.add_parser("schedule")
    schedule_commands = schedule.add_subparsers(dest="schedule_command", required=True)
    schedule_commands.add_parser("list")
    schedule_commands.add_parser("status")
    schedule_set = schedule_commands.add_parser("set")
    schedule_set.add_argument("job_id")
    schedule_set.add_argument("cron")
    schedule_set.add_argument("--timezone", default="UTC")
    for action in ("pause", "resume"):
        item = schedule_commands.add_parser(action)
        item.add_argument("job_id")
    schedule_commands.add_parser("run-due")
    serve = schedule_commands.add_parser("start")
    serve.add_argument("--poll-seconds", type=float, default=30.0)

    backup = commands.add_parser("backup")
    backup_commands = backup.add_subparsers(dest="backup_command", required=True)
    backup_create = backup_commands.add_parser("create")
    backup_create.add_argument("destination")
    backup_create.add_argument("--exclude-raw-pages", action="store_true")
    backup_verify = backup_commands.add_parser("verify")
    backup_verify.add_argument("source")
    backup_restore = backup_commands.add_parser("restore")
    backup_restore.add_argument("source")
    backup_restore.add_argument("destination")

    cloud = commands.add_parser(
        "cloud", help="explicitly connect this OSS workspace to cloud"
    )
    cloud_commands = cloud.add_subparsers(dest="cloud_command", required=True)
    cloud_commands.add_parser("profiles", help="list configured cloud profiles")
    cloud_connect = cloud_commands.add_parser(
        "connect", help="validate and store a cloud profile"
    )
    cloud_connect.add_argument("--profile", default="default")
    cloud_connect.add_argument("--base-url", required=True)
    cloud_disconnect = cloud_commands.add_parser("disconnect")
    cloud_disconnect.add_argument("--profile", default="default")
    cloud_whoami = cloud_commands.add_parser("whoami")
    cloud_whoami.add_argument("--profile", default="default")
    cloud_bundle = cloud_commands.add_parser(
        "bundle", help="print a credential-free workspace bundle"
    )
    cloud_bundle.add_argument("--profile", default="default", help=argparse.SUPPRESS)
    cloud_plan = cloud_commands.add_parser(
        "plan", help="preview local definition import"
    )
    cloud_plan.add_argument("--profile", default="default")
    cloud_push = cloud_commands.add_parser(
        "push", help="idempotently import local definitions"
    )
    cloud_push.add_argument("--profile", default="default")
    cloud_run = cloud_commands.add_parser(
        "run", help="push definitions and run a local job in cloud"
    )
    cloud_run.add_argument("job_id")
    cloud_run.add_argument("--profile", default="default")
    cloud_pull = cloud_commands.add_parser(
        "pull", help="download active cloud dataset Parquet"
    )
    cloud_pull.add_argument("dataset_id")
    cloud_pull.add_argument("destination")
    cloud_pull.add_argument("--profile", default="default")
    cloud_pull.add_argument("--overwrite", action="store_true")
    return parser
