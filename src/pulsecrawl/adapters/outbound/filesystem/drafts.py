"""Filesystem draft and representative-page repositories."""

import json
import re
from pathlib import Path
from pulsecrawl.domain.templates.authoring import TemplateDraft, RepresentativePage
from pulsecrawl.adapters.outbound.filesystem.atomic import _atomic_json


class JsonDraftRepository:
    def __init__(self, root: Path):
        self.directory = root / "template-drafts"
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, draft_id):
        if not re.fullmatch(r"draft_[A-Za-z0-9_]+", draft_id):
            raise ValueError("invalid draft id")
        return self.directory / f"{draft_id}.json"

    def save(self, draft):
        _atomic_json(self._path(draft.draft_id), draft.to_dict())
        return draft

    def get(self, draft_id):
        path = self._path(draft_id)
        if not path.exists():
            raise KeyError(f"unknown template draft: {draft_id}")
        return TemplateDraft.from_dict(json.loads(path.read_text()))

    def list(self):
        return [
            TemplateDraft.from_dict(json.loads(path.read_text()))
            for path in sorted(self.directory.glob("*.json"))
        ]


class JsonRepresentativePages:
    def __init__(self, root):
        self.root = root

    def load(self, execution_id):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,255}", execution_id):
            raise ValueError("invalid execution id")
        return [
            RepresentativePage.from_value(
                {**json.loads(path.read_text()), "role": "positive"}
            )
            for path in sorted(
                (self.root / "executions" / execution_id / "pages").glob("*.json")
            )
        ]
