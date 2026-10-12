import json
from pathlib import Path

import pytest

from pulsecrawl import Workspace
from pulsecrawl.cloud import (
    API_KEY_ENV,
    PROFILE_SERVICE,
    CloudProfile,
    CloudProfiles,
    CloudWorkspaceSync,
    export_workspace_bundle,
)
import pulsecrawl.cloud as cloud_module
import pulsecrawl.cli as cli_module


class FakeKeyring:
    def __init__(self):
        self.values = {}

    def set_password(self, service, name, secret):
        self.values[(service, name)] = secret

    def get_password(self, service, name):
        return self.values.get((service, name))

    def delete_password(self, service, name):
        self.values.pop((service, name), None)


class IdentityClient:
    def __init__(self, api_key=None, base_url=None, **_kwargs):
        self.api_key = api_key
        self.base_url = base_url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def close(self):
        return None

    def whoami(self):
        return {
            "kind": "apiKey",
            "orgId": "org_cloud",
            "keyId": "key_cloud",
            "scopes": ["catalog:read"],
        }


def test_cloud_profiles_keep_secrets_out_of_config(tmp_path, monkeypatch):
    keyring = FakeKeyring()
    monkeypatch.setattr(cloud_module, "_keyring", lambda: keyring)
    monkeypatch.setattr(cloud_module, "PulseCrawl", IdentityClient)
    store = CloudProfiles(tmp_path / "profiles.json")

    profile = store.connect(
        "production",
        base_url="https://api.example/v1/",
        api_key="pk_live_secret",
    )
    assert profile.org_id == "org_cloud"
    assert store.get("production") == profile
    assert store.list() == [profile]
    assert "pk_live_secret" not in store.path.read_text()
    assert store.path.stat().st_mode & 0o777 == 0o600

    client = store.client("production")
    assert client.api_key == "pk_live_secret"
    monkeypatch.setenv(API_KEY_ENV, "pk_live_ci")
    assert store.client("production").api_key == "pk_live_ci"

    store.disconnect("production")
    assert store.list() == []
    with pytest.raises(KeyError):
        store.get("production")


def test_profile_validation_and_missing_keyring_secret(tmp_path, monkeypatch):
    keyring = FakeKeyring()
    monkeypatch.setattr(cloud_module, "_keyring", lambda: keyring)
    monkeypatch.setattr(cloud_module, "PulseCrawl", IdentityClient)
    store = CloudProfiles(tmp_path / "profiles.json")
    with pytest.raises(ValueError, match="profile name"):
        store.connect("bad/name", base_url="https://api.example/v1", api_key="pk")
    store.connect("ok", base_url="https://api.example/v1", api_key="pk")
    keyring.values.clear()
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    with pytest.raises(ValueError, match="no credential"):
        store.client("ok")
    store.path.write_text('{"version": 2, "profiles": {}}')
    with pytest.raises(ValueError, match="unsupported"):
        store.list()


def test_profile_store_repairs_permissions_and_rolls_back_secret_on_write_failure(
    tmp_path, monkeypatch
):
    path = tmp_path / "profiles.json"
    path.write_text('{"version": 1, "profiles": {}}')
    path.chmod(0o644)
    store = CloudProfiles(path)
    assert path.stat().st_mode & 0o777 == 0o600

    keyring = FakeKeyring()
    monkeypatch.setattr(cloud_module, "_keyring", lambda: keyring)
    monkeypatch.setattr(cloud_module, "PulseCrawl", IdentityClient)
    monkeypatch.setattr(
        cloud_module,
        "_atomic_private_json",
        lambda *_args: (_ for _ in ()).throw(OSError("disk full")),
    )
    with pytest.raises(OSError, match="disk full"):
        store.connect("broken", base_url="https://api.example/v1", api_key="pk")
    assert keyring.values == {}


def test_headless_profile_connect_uses_environment_without_keyring(tmp_path, monkeypatch):
    monkeypatch.setattr(cloud_module, "PulseCrawl", IdentityClient)
    monkeypatch.setattr(
        cloud_module,
        "_keyring",
        lambda: (_ for _ in ()).throw(AssertionError("keyring must not be opened")),
    )
    store = CloudProfiles(tmp_path / "profiles.json")
    profile = store.connect(
        "ci",
        base_url="https://api.example/v1",
        api_key="pk_live_ci",
        store_secret=False,
    )
    assert profile.org_id == "org_cloud"
    assert "pk_live_ci" not in store.path.read_text()
    monkeypatch.setenv(API_KEY_ENV, "pk_live_ci")
    assert store.client("ci").api_key == "pk_live_ci"


def test_profile_reconnect_restores_previous_secret_when_metadata_write_fails(
    tmp_path, monkeypatch
):
    keyring = FakeKeyring()
    monkeypatch.setattr(cloud_module, "_keyring", lambda: keyring)
    monkeypatch.setattr(cloud_module, "PulseCrawl", IdentityClient)
    store = CloudProfiles(tmp_path / "profiles.json")
    store.connect("production", base_url="https://old.example/v1", api_key="old-secret")
    monkeypatch.setattr(
        cloud_module,
        "_atomic_private_json",
        lambda *_args: (_ for _ in ()).throw(OSError("disk full")),
    )
    with pytest.raises(OSError, match="disk full"):
        store.connect("production", base_url="https://new.example/v1", api_key="new-secret")
    assert keyring.get_password(PROFILE_SERVICE, "production") == "old-secret"


def test_export_workspace_bundle_contains_definitions_not_credentials(tmp_path):
    with Workspace.init(tmp_path / "workspace", name="Portable") as workspace:
        field = workspace.fields.create("title", "string", field_id="fld_title")
        schema = workspace.schemas.create("Page", [field["fieldId"]], schema_id="schema_page")
        template = workspace.templates.create(
            "Page CSS",
            output_schema_id=schema["schemaId"],
            engine="css",
            mappings={field["fieldId"]: "title"},
            template_id="tmpl_page",
        )
        dataset = workspace.datasets.create(
            "pages", schema_id=schema["schemaId"], mode="new_urls_only"
        )
        job = workspace.jobs.create(
            "example",
            seeds=["https://example.com/"],
            dataset_id=dataset["datasetId"],
            templates=[{"templateId": template["templateId"]}],
        )
        workspace.schedules.set(job["jobId"], "0 * * * *")
        bundle = export_workspace_bundle(workspace)

    assert bundle["bundleVersion"] == 1
    assert bundle["workspace"]["name"] == "Portable"
    assert bundle["fields"][0]["fieldId"] == "fld_title"
    assert bundle["jobs"][0]["name"] == "example"
    assert bundle["schedules"][0]["jobId"] == job["jobId"]
    assert "secret" not in json.dumps(bundle).lower()


def test_real_workspace_can_be_mapped_and_started_in_cloud(tmp_path):
    with Workspace.init(tmp_path / "workspace", name="End to end") as workspace:
        field = workspace.fields.create("title", "string", field_id="fld_title")
        schema = workspace.schemas.create("Page", [field["fieldId"]], schema_id="schema_page")
        template = workspace.templates.create(
            "Page CSS",
            output_schema_id=schema["schemaId"],
            engine="css",
            mappings={field["fieldId"]: "title"},
            template_id="tmpl_page",
        )
        dataset = workspace.datasets.create("pages", schema_id=schema["schemaId"])
        job = workspace.jobs.create(
            "example",
            seeds=["https://example.com/"],
            dataset_id=dataset["datasetId"],
            templates=[{"templateId": template["templateId"]}],
        )
        bundle = export_workspace_bundle(workspace)

    client = FakeCloudClient()
    mapping = CloudWorkspaceSync(client).apply(bundle)
    execution = client.jobs.run(mapping["jobIds"][job["jobId"]])
    assert execution == {
        "executionId": "exec_1",
        "jobId": "job_cloud_1",
        "status": "queued",
    }


class Collection:
    def __init__(self, prefix, id_key):
        self.prefix = prefix
        self.id_key = id_key
        self.items = []

    def list(self, **_kwargs):
        return [dict(item) for item in self.items]

    def _create(self, value):
        value = {self.id_key: f"{self.prefix}{len(self.items) + 1}", **value}
        self.items.append(value)
        return dict(value)


class Fields(Collection):
    def create(self, name, type, description=None):
        return self._create({"name": name, "type": type, "description": description, "origin": "org"})


class Schemas(Collection):
    def create(self, name, field_ids):
        return self._create({"name": name, "fieldIds": list(field_ids), "origin": "org"})


class Templates(Collection):
    def create(self, name, *, output_schema_id, engine, mappings):
        return self._create({
            "name": name,
            "outputSchemaId": output_schema_id,
            "engine": engine,
            "mappings": dict(mappings),
            "origin": "org",
        })


class Datasets(Collection):
    def create(self, name, *, schema_id, mode, identity_field):
        return self._create({
            "name": name,
            "schemaId": schema_id,
            "mode": mode,
            "identityField": identity_field,
        })


class Jobs(Collection):
    def create(self, name, **kwargs):
        return self._create({"name": name, **kwargs})

    def run(self, job_id):
        return {"executionId": "exec_1", "jobId": job_id, "status": "queued"}


class Schedules:
    def __init__(self):
        self.items = {}

    def set(self, job_id, cron, *, timezone):
        value = {"jobId": job_id, "cron": cron, "timezone": timezone, "status": "active"}
        self.items[job_id] = value
        return dict(value)

    def pause(self, job_id):
        self.items[job_id]["status"] = "paused"
        return dict(self.items[job_id])


class FakeCloudClient:
    def __init__(self):
        self.fields = Fields("fld_cloud_", "fieldId")
        self.schemas = Schemas("schema_cloud_", "schemaId")
        self.templates = Templates("tmpl_cloud_", "templateId")
        self.datasets = Datasets("ds_cloud_", "datasetId")
        self.jobs = Jobs("job_cloud_", "jobId")
        self.schedules = Schedules()


def sample_bundle():
    return {
        "bundleVersion": 1,
        "workspace": {"workspaceId": "ws_1", "name": "Local"},
        "fields": [
            {"fieldId": "fld_url", "name": "url", "type": "url", "description": "canonical"},
            {"fieldId": "fld_title", "name": "title", "type": "string"},
        ],
        "schemas": [
            {"schemaId": "schema_page", "name": "Page", "fieldIds": ["fld_url", "fld_title"]}
        ],
        "templates": [
            {
                "templateId": "tmpl_page",
                "name": "Page CSS",
                "outputSchemaId": "schema_page",
                "engine": "css",
                "mappings": {"fld_url": "link", "fld_title": "title"},
            }
        ],
        "datasets": [
            {
                "datasetId": "ds_pages",
                "name": "pages",
                "schemaId": "schema_page",
                "mode": "new_urls_only",
                "identityField": "fld_url",
            }
        ],
        "jobs": [
            {
                "jobId": "job_pages",
                "name": "example",
                "seeds": ["https://example.com/"],
                "datasetId": "ds_pages",
                "templates": [
                    {
                        "templateId": "tmpl_page",
                        "scope": {"hosts": ["example.com"], "urlPatterns": ["/news/*"]},
                    }
                ],
                "scope": {"maxDepth": 1, "maxUrlsPerExecution": 10, "maxUrlsTotal": 100},
                "politeness": {"requestsPerSecond": 0.5},
            }
        ],
        "schedules": [
            {
                "jobId": "job_pages",
                "cron": "0 * * * *",
                "timezone": "UTC",
                "status": "paused",
            }
        ],
    }


def test_cloud_workspace_sync_plans_applies_and_reuses():
    client = FakeCloudClient()
    sync = CloudWorkspaceSync(client)
    bundle = sample_bundle()
    plan = sync.plan(bundle)
    assert plan["safeToApply"] is True
    assert {item["action"] for item in plan["actions"]} == {"create"}

    mapping = sync.apply(bundle)
    assert mapping["fieldIds"] == {"fld_url": "fld_cloud_1", "fld_title": "fld_cloud_2"}
    assert mapping["schemaIds"]["schema_page"] == "schema_cloud_1"
    assert mapping["templateIds"]["tmpl_page"] == "tmpl_cloud_1"
    assert mapping["datasetIds"]["ds_pages"] == "ds_cloud_1"
    assert mapping["jobIds"]["job_pages"] == "job_cloud_1"
    assert client.schedules.items["job_cloud_1"]["status"] == "paused"
    assert client.templates.items[0]["mappings"] == {
        "fld_cloud_1": "link",
        "fld_cloud_2": "title",
    }
    assert client.jobs.items[0]["template_stack"] == [
        {
            "template_id": "tmpl_cloud_1",
            "hosts": ["example.com"],
            "url_patterns": ["/news/*"],
        }
    ]

    second = sync.plan(bundle)
    assert {item["action"] for item in second["actions"]} == {"reuse"}
    assert sync.apply(bundle) == mapping
    assert len(client.fields.items) == 2


def test_cloud_workspace_sync_rejects_contract_and_content_conflicts():
    client = FakeCloudClient()
    sync = CloudWorkspaceSync(client)
    with pytest.raises(ValueError, match="bundle version"):
        sync.plan({"bundleVersion": 99})

    client.fields.items.append({
        "fieldId": "fld_existing",
        "name": "url",
        "type": "string",
        "origin": "org",
    })
    with pytest.raises(ValueError, match="different type"):
        sync.apply(sample_bundle())

    client.fields.items.append({
        "fieldId": "fld_duplicate",
        "name": "url",
        "type": "url",
        "origin": "org",
    })
    with pytest.raises(ValueError, match="multiple field"):
        sync.plan(sample_bundle())


def test_cloud_workspace_sync_rejects_dangling_references_and_changed_jobs():
    client = FakeCloudClient()
    sync = CloudWorkspaceSync(client)
    invalid = sample_bundle()
    invalid["schemas"][0]["fieldIds"] = ["fld_missing"]
    with pytest.raises(ValueError, match="unknown field"):
        sync.plan(invalid)

    bundle = sample_bundle()
    sync.apply(bundle)
    client.jobs.items[0]["seeds"] = ["https://changed.example/"]
    with pytest.raises(ValueError, match="different contents"):
        sync.apply(bundle)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update(fields={}), "fields must be a list"),
        (lambda value: value["fields"].append(dict(value["fields"][0])), "duplicate fields IDs"),
        (lambda value: value["fields"][1].update(name="url"), "duplicate fields names"),
        (lambda value: value["templates"][0].update(outputSchemaId="missing"), "unknown schema"),
        (lambda value: value["templates"][0].update(mappings={"missing": "x"}), "unknown field"),
        (lambda value: value["datasets"][0].update(schemaId="missing"), "unknown schema"),
        (lambda value: value["jobs"][0].update(datasetId="missing"), "unknown dataset"),
        (lambda value: value["jobs"][0].update(templates=[]), "unknown template"),
        (lambda value: value.update(schedules={}), "schedules must be a list"),
        (lambda value: value["schedules"][0].update(jobId="missing"), "unknown job"),
        (lambda value: value["schedules"].append(dict(value["schedules"][0])), "duplicate schedules"),
    ],
)
def test_bundle_contract_validation_catches_bad_graphs(mutate, message):
    bundle = sample_bundle()
    mutate(bundle)
    with pytest.raises(ValueError, match=message):
        CloudWorkspaceSync._validate_bundle(bundle)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["schemas"][0].update(fieldIds=["fld_url"]),
        lambda value: value["templates"][0].update(engine="meta"),
        lambda value: value["datasets"][0].update(mode="append_all"),
    ],
)
def test_plan_detects_existing_resource_conflicts_before_writing(mutate):
    client = FakeCloudClient()
    sync = CloudWorkspaceSync(client)
    sync.apply(sample_bundle())
    changed = sample_bundle()
    mutate(changed)
    plan = sync.plan(changed)
    assert plan["safeToApply"] is False
    assert "conflict" in {action["action"] for action in plan["actions"]}


def test_cloud_pull_cli_downloads_to_requested_destination(tmp_path, monkeypatch, capsys):
    class Downloads:
        def download_files(self, dataset_id, destination, *, overwrite):
            assert dataset_id == "ds_cloud"
            assert destination == str(tmp_path)
            assert overwrite is True
            return [tmp_path / "part.parquet"]

    class Client:
        datasets = Downloads()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    class Profiles:
        def client(self, name):
            assert name == "production"
            return Client()

    monkeypatch.setattr(cli_module, "CloudProfiles", Profiles)
    assert cli_module._main([
        "cloud", "pull", "ds_cloud", str(tmp_path),
        "--profile", "production", "--overwrite",
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result == {"datasetId": "ds_cloud", "files": [str(tmp_path / "part.parquet")]}


def test_cloud_connect_cli_does_not_store_environment_secret(monkeypatch, capsys):
    class Profiles:
        def connect(self, name, *, base_url, api_key, store_secret):
            assert (name, base_url, api_key) == (
                "ci", "https://api.example/v1", "pk_live_ci"
            )
            assert store_secret is False
            return CloudProfile(name, base_url, "org_cloud", "key_cloud")

    monkeypatch.setattr(cli_module, "CloudProfiles", Profiles)
    monkeypatch.setenv(API_KEY_ENV, "pk_live_ci")
    assert cli_module._main([
        "cloud", "connect", "--profile", "ci", "--base-url", "https://api.example/v1",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["key_id"] == "key_cloud"


def test_cloud_sync_reports_missing_key_scopes_before_reading_resources():
    class ScopedClient:
        def whoami(self):
            return {"kind": "apiKey", "scopes": ["catalog:read"]}

    with pytest.raises(ValueError, match="datasets:read, jobs:read"):
        CloudWorkspaceSync(ScopedClient()).plan(sample_bundle())
