"""Cross-definition and published-output validation through narrow ports."""

from typing import Any


class WorkspaceValidationService:
    def __init__(
        self,
        *,
        authoring,
        datasets,
        jobs,
        executions,
        readers,
        snapshots,
        org_id,
        map_intent,
    ):
        self.authoring, self.datasets, self.jobs, self.executions = (
            authoring,
            datasets,
            jobs,
            executions,
        )
        self._readers, self._snapshots, self._org_id, self._map_intent = (
            readers,
            snapshots,
            org_id,
            map_intent,
        )

    def validate(self) -> dict[str, Any]:
        errors: list[str] = []
        try:
            drafts = self.authoring.list_drafts()
        except Exception as exc:
            drafts = []
            errors.append(f"template drafts: {exc}")
        for draft in drafts:
            if draft.status in ("approved", "promoted") and (
                not draft.validation or not draft.validation.get("passed")
            ):
                errors.append(f"draft {draft.draft_id} lacks a passing validation")
            if draft.status in ("approved", "promoted") and (
                not draft.approved_at or not draft.approved_by
            ):
                errors.append(f"draft {draft.draft_id} lacks approval provenance")
            if draft.status == "promoted" and not draft.promoted_template_ids:
                errors.append(f"draft {draft.draft_id} lacks promoted templates")
        try:
            datasets = self.datasets.list()
        except Exception as exc:
            datasets = []
            errors.append(f"dataset catalog: {exc}")
        dataset_ids = {item["datasetId"] for item in datasets}
        try:
            jobs = self.jobs.list()
        except Exception as exc:
            jobs = []
            errors.append(f"job catalog: {exc}")
        for job in jobs:
            if job["datasetId"] not in dataset_ids:
                errors.append(f"job {job['jobId']} references missing dataset")
            if not job.get("templates"):
                errors.append(f"job {job['jobId']} has no templates")
            try:
                self._map_intent(
                    execution_id="validation",
                    org_id=self._org_id,
                    job_id=str(job["jobId"]),
                    intent={
                        "seeds": job["seeds"],
                        "datasetId": job["datasetId"],
                        "templateStack": job["templates"],
                        "systemTemplates": job.get("systemTemplates", []),
                        "schema": job["schema"],
                        "scope": job["scope"],
                        "politeness": job["politeness"],
                    },
                )
            except Exception as exc:
                errors.append(f"job {job.get('jobId', 'unknown')}: {exc}")
            try:
                if self._snapshots.read("jobs", job["jobId"]) != job:
                    errors.append(f"job {job['jobId']} file differs from SQLite")
            except Exception as exc:
                errors.append(f"job {job['jobId']} file: {exc}")
        for dataset in datasets:
            reader = self._readers(dataset)
            try:
                reader.validate_files()
                manifest = reader.manifests.current()
                if manifest.get("datasetId") not in (None, dataset["datasetId"]):
                    errors.append(
                        f"dataset {dataset['datasetId']}: manifest datasetId mismatch"
                    )
            except Exception as exc:
                errors.append(f"dataset {dataset['datasetId']}: {exc}")
            try:
                if self._snapshots.read("datasets", dataset["datasetId"]) != dataset:
                    errors.append(
                        f"dataset {dataset['datasetId']} file differs from SQLite"
                    )
            except Exception as exc:
                errors.append(f"dataset {dataset['datasetId']} file: {exc}")
        try:
            executions = self.executions.list()
        except Exception as exc:
            executions = []
            errors.append(f"execution catalog: {exc}")
        return {
            "valid": not errors,
            "errors": errors,
            "jobs": len(jobs),
            "datasets": len(datasets),
            "executions": len(executions),
        }
