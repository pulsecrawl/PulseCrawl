"""Restricted JSON profile metadata and lazily loaded OS credential store."""

import json
import os
from pathlib import Path


class JsonProfileRepository:
    def __init__(self, path, writer):
        self.path, self._writer = Path(path), writer
        if self.path.exists():
            os.chmod(self.path, 0o600)

    def read(self):
        if not self.path.exists():
            return {"version": 1, "profiles": {}}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if value.get("version") != 1 or not isinstance(value.get("profiles"), dict):
            raise ValueError(f"unsupported cloud profile file: {self.path}")
        return value

    def write(self, value):
        self._writer(self.path, value)


class KeyringCredentialStore:
    def __init__(self, backend):
        self._backend = backend

    def get_password(self, *args):
        return self._backend().get_password(*args)

    def set_password(self, *args):
        return self._backend().set_password(*args)

    def delete_password(self, *args):
        return self._backend().delete_password(*args)
