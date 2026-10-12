"""Job definition, preparation and dispatch use cases."""

from __future__ import annotations
from typing import Any, Mapping, Sequence
from pulsecrawl.application.ports.workspace import (
    DefinitionRepository,
    DefinitionSnapshots,
)
from pulsecrawl.domain.workspace.definitions import (
    _safe_identifier,
    _scope,
    _politeness,
    _templates,
)
from pulsecrawl.domain.crawling.urls import normalize_url
from pulsecrawl.domain.errors import WorkspaceError


class JobService:
    def __init__(
        self,
        *,
        repository: DefinitionRepository,
        datasets,
        templates,
        executions,
        snapshots: DefinitionSnapshots,
        now,
        id_factory,
    ):
        self._repository, self._datasets, self._templates = (
            repository,
            datasets,
            templates,
        )
        self._executions, self._snapshots = executions, snapshots
        self._now, self._id = now, id_factory

    def create(
        self,
        name: str,
        *,
        seeds: Sequence[str],
        dataset_id: str,
        templates: Sequence[Mapping[str, Any]],
        system_templates: Sequence[Mapping[str, Any]] = (),
        scope: Mapping[str, Any] | None = None,
        politeness: Mapping[str, Any] | None = None,
        store_raw_pages: bool = False,
    ) -> dict[str, Any]:
        if not name.strip() or len(name) > 256:
            raise ValueError("job name must contain between 1 and 256 characters")
        dataset = self._datasets.get(dataset_id)
        normalized_scope = _scope(scope)
        if not seeds:
            raise ValueError("a job needs at least one seed")
        if len(seeds) > 10_000:
            raise ValueError("a job supports at most 10000 seeds")
        if any(len(str(seed)) > 8_192 for seed in seeds):
            raise ValueError("seed URLs must not exceed 8192 characters")
        normalized_seeds = [normalize_url(str(seed)) for seed in seeds]
        if any(seed is None for seed in normalized_seeds):
            raise ValueError("every seed must be an absolute HTTP(S) URL")
        if normalized_scope["maxDepth"] < 0:
            raise ValueError("maxDepth must not be negative")
        if normalized_scope["maxUrlsPerExecution"] <= 0:
            raise ValueError("maxUrlsPerExecution must be positive")
        if normalized_scope["maxUrlsTotal"] < normalized_scope["maxUrlsPerExecution"]:
            raise ValueError("maxUrlsTotal must be at least maxUrlsPerExecution")

        field_ids = {str(field["fieldId"]) for field in dataset["fields"]}

        def resolve(
            entries: Sequence[Mapping[str, Any]], *, system: bool
        ) -> list[dict[str, Any]]:
            resolved: list[dict[str, Any]] = []
            for raw in entries:
                if "engine" not in raw:
                    identifier = str(raw.get("template_id") or raw.get("templateId"))
                    catalog = self._templates.get(identifier)
                    merged = {
                        **catalog,
                        **{
                            key: value
                            for key, value in raw.items()
                            if key != "template_id"
                        },
                        "templateId": identifier,
                        "origin": "system" if system else "org",
                    }
                    normalized = _templates([merged])[0]
                    unknown = sorted(set(normalized["mappings"]) - field_ids)
                    if unknown:
                        raise ValueError(
                            "template mappings reference fields outside the dataset schema: "
                            + ", ".join(unknown)
                        )
                    resolved.append(normalized)
                    continue
                normalized = _templates(
                    [
                        {
                            **raw,
                            "origin": "system" if system else "org",
                        }
                    ]
                )[0]
                unknown = sorted(set(normalized["mappings"]) - field_ids)
                if unknown:
                    raise ValueError(
                        "template mappings reference fields outside the dataset schema: "
                        + ", ".join(unknown)
                    )
                self._templates.save(
                    {
                        "templateId": normalized["templateId"],
                        "name": str(raw.get("name") or normalized["templateId"]),
                        "outputSchemaId": dataset["schemaId"],
                        "engine": normalized["engine"],
                        "mappings": normalized["mappings"],
                        "origin": normalized["origin"],
                    }
                )
                resolved.append(normalized)
            return resolved

        resolved_templates = resolve(templates, system=False)
        resolved_system = resolve(system_templates, system=True)
        all_templates = resolved_templates + resolved_system
        template_ids = [item["templateId"] for item in all_templates]
        if len(set(template_ids)) != len(template_ids):
            raise ValueError("template ids must be unique within a job")
        definition = {
            "jobId": self._id("job"),
            "name": name,
            "seeds": list(dict.fromkeys(str(seed) for seed in normalized_seeds)),
            "datasetId": dataset_id,
            "schema": {
                "schemaId": dataset["schemaId"],
                "fields": dataset["fields"],
            },
            "templates": resolved_templates,
            "systemTemplates": resolved_system,
            "scope": normalized_scope,
            "politeness": _politeness(politeness),
            "storeRawPages": bool(store_raw_pages),
            "createdAt": self._now(),
        }
        self._repository.add(definition)
        self._snapshots.write("jobs", definition["jobId"], definition)
        return definition

    def list(self):
        return self._repository.list()

    def get(self, job_id):
        return self._repository.get(job_id)

    async def run(
        self,
        job_id: str,
        *,
        trigger: str = "manual",
        scheduled_for: str | None = None,
        fetcher=None,
        allow_private_networks: bool = False,
        execution_id: str | None = None,
        max_urls_per_execution: int | None = None,
        max_depth: int | None = None,
        store_raw_pages: bool | None = None,
        publish_records: bool = True,
        should_stop=None,
    ) -> dict[str, Any]:
        execution_id = execution_id or self._id(
            "exec" if trigger == "manual" else "exec_sched"
        )
        _safe_identifier(execution_id, "execution_id")
        try:
            existing = self._executions.get(execution_id)
        except KeyError:
            existing = None
        if existing is not None:
            if existing["status"] == "succeeded":
                return self._executions.get(execution_id)
            if existing["status"] in ("queued", "running", "cancelling"):
                return await self._executions.execute(
                    execution_id,
                    fetcher=fetcher,
                    allow_private_networks=allow_private_networks,
                    should_stop=should_stop,
                )
            raise WorkspaceError(
                f"execution {execution_id} already ended as {existing['status']}"
            )
        prepared = self.prepare(
            job_id,
            trigger=trigger,
            scheduled_for=scheduled_for,
            execution_id=execution_id,
            max_urls_per_execution=max_urls_per_execution,
            max_depth=max_depth,
            store_raw_pages=store_raw_pages,
            publish_records=publish_records,
        )
        return await self._executions.execute(
            prepared["executionId"],
            fetcher=fetcher,
            allow_private_networks=allow_private_networks,
            should_stop=should_stop,
        )

    def prepare(
        self,
        job_id: str,
        *,
        trigger: str = "manual",
        scheduled_for: str | None = None,
        execution_id: str | None = None,
        max_urls_per_execution: int | None = None,
        max_depth: int | None = None,
        store_raw_pages: bool | None = None,
        publish_records: bool = True,
    ) -> dict[str, Any]:
        """Atomically freeze an intent and reserve its lifetime budget.

        The returned execution is queued but not run. This is useful to a
        scheduler or another local process; calling ``executions.resume``
        starts it without creating a second intent.
        """
        prepared = self._executions.prepare(
            job_id,
            trigger=trigger,
            scheduled_for=scheduled_for,
            execution_id=execution_id,
            max_urls_per_execution=max_urls_per_execution,
            max_depth=max_depth,
            store_raw_pages=store_raw_pages,
            publish_records=publish_records,
        )
        return prepared
