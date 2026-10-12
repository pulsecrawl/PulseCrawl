"""SQLite-backed operational definitions."""

import json


class SQLiteDefinitionRepository:
    def __init__(self, state, kind):
        if kind not in ("jobs", "datasets"):
            raise ValueError("unsupported definition kind")
        self.state, self.kind = state, kind
        self.id_key = "jobId" if kind == "jobs" else "datasetId"
        self.column = "job_id" if kind == "jobs" else "dataset_id"

    def get(self, identifier):
        row = self.state.execute(
            f"SELECT definition_json FROM {self.kind} WHERE {self.column}=?",
            (identifier,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown {self.kind[:-1]}: {identifier}")
        return json.loads(row["definition_json"])

    def list(self):
        return [
            json.loads(row["definition_json"])
            for row in self.state.execute(
                f"SELECT definition_json FROM {self.kind} ORDER BY created_at"
            ).fetchall()
        ]

    def add(self, definition):
        with self.state.transaction() as db:
            if self.kind == "datasets":
                db.execute(
                    "INSERT INTO datasets VALUES(?,?,?,?)",
                    (
                        definition["datasetId"],
                        definition["name"],
                        json.dumps(definition, sort_keys=True),
                        definition["createdAt"],
                    ),
                )
            else:
                db.execute(
                    "INSERT INTO jobs VALUES(?,?,?,?,0,0,?)",
                    (
                        definition["jobId"],
                        definition["name"],
                        json.dumps(definition, sort_keys=True),
                        definition["scope"]["maxUrlsTotal"],
                        definition["createdAt"],
                    ),
                )
