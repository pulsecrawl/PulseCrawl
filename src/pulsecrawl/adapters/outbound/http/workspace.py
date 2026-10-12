"""Expose the hosted REST client as an application gateway."""


class HttpWorkspaceGateway:
    def __init__(self, client):
        self.client = client

    def identity(self):
        whoami = getattr(self.client, "whoami", None)
        return whoami() if whoami is not None else None

    def _resource(self, kind):
        if kind not in ("fields", "schemas", "templates", "datasets", "jobs"):
            raise ValueError("unsupported cloud resource kind")
        return getattr(self.client, kind)

    def list(self, kind, **filters):
        return self._resource(kind).list(**filters)

    def create(self, kind, *args, **values):
        return self._resource(kind).create(*args, **values)

    def snapshot(self):
        return {
            kind: self.list(
                kind,
                **(
                    {"origin": "all"}
                    if kind in ("fields", "schemas", "templates")
                    else {}
                ),
            )
            for kind in ("fields", "schemas", "templates", "datasets", "jobs")
        }

    def set_schedule(self, *args, **values):
        return self.client.schedules.set(*args, **values)

    def pause_schedule(self, job_id):
        return self.client.schedules.pause(job_id)
